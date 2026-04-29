from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import JobEnqueuer
from app.core.settings import Settings
from app.core.storage import DocumentStorage
from app.models import ClassificationRun, Document
from app.repositories.classification_repository import ClassificationRunRepository
from app.repositories.document_repository import DocumentRepository, compute_document_hash
from app.repositories.outbox_repository import OutboxRepository
from app.services.medical_classifier import (
    ProcedureClassificationInput,
    ProcedureClassificationService,
)

logger = logging.getLogger(__name__)

CLASSIFY_FUNCTION_NAME = "classify_document_job"
EVENT_CLASSIFICATION_DONE = "classification.completed"
EVENT_CLASSIFICATION_FAILED = "classification.failed"


@dataclass(slots=True)
class IngestionResult:
    document: Document
    run: ClassificationRun
    deduplicated: bool


class ClassificationPipeline:
    """Owns the async ingestion flow: store doc -> create run -> enqueue."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: DocumentStorage,
        enqueuer: JobEnqueuer,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.enqueuer = enqueuer

    async def ingest(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        procedure_code: str,
        document_text: str,
        external_document_id: str | None,
        source_system: str | None,
        callback_url: str | None,
        metadata: dict[str, object],
        batch_id: uuid.UUID | None = None,
    ) -> IngestionResult:
        document_hash = compute_document_hash(document_text)
        encoded = document_text.encode("utf-8")

        document_repo = DocumentRepository(session)
        existing = await document_repo.get_by_hash(tenant_id, document_hash)
        deduplicated = existing is not None

        if existing is None:
            storage_key = f"{tenant_id}/{document_hash[:2]}/{document_hash}.txt"
            storage_uri = await self.storage.put(storage_key, encoded, content_type="text/plain")
            document = await document_repo.upsert(
                tenant_id=tenant_id,
                document_hash=document_hash,
                procedure_code=procedure_code,
                storage_uri=storage_uri,
                size_bytes=len(encoded),
                source_system=source_system,
                external_document_id=external_document_id,
                metadata=metadata,
            )
        else:
            document = existing

        run_repo = ClassificationRunRepository(session)
        run = await run_repo.create_pending(
            document_id=document.id,
            tenant_id=tenant_id,
            procedure_code=procedure_code,
            max_attempts=self.settings.classification_max_retries,
            callback_url=callback_url,
            batch_id=batch_id,
        )
        await session.commit()

        try:
            await self.enqueuer.enqueue(
                CLASSIFY_FUNCTION_NAME,
                run_id=str(run.id),
                job_id=str(run.job_id),
            )
        except Exception:
            logger.exception("enqueue_failed", extra={"extra": {"run_id": str(run.id)}})
            raise

        return IngestionResult(document=document, run=run, deduplicated=deduplicated)


class ClassificationExecutor:
    """Executes a classification run inside a worker context."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: DocumentStorage,
        classifier: ProcedureClassificationService,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.classifier = classifier

    async def execute(self, session: AsyncSession, run_id: uuid.UUID) -> None:
        run_repo = ClassificationRunRepository(session)
        outbox_repo = OutboxRepository(session)

        run = await run_repo.get_for_update(run_id)
        if run is None:
            logger.warning("run_not_found", extra={"extra": {"run_id": str(run_id)}})
            return
        if run.status not in {"pending", "failed"}:
            logger.info(
                "run_skipped_non_pending",
                extra={"extra": {"run_id": str(run_id), "status": run.status}},
            )
            return

        await run_repo.mark_running(run)
        await session.commit()

        document_text = await self._load_document_text(session, run.document_id)
        if document_text is None:
            error_payload = {"code": "document_not_found", "message": "document missing in storage"}
            await run_repo.mark_failed(run, error_payload)
            await self._publish_event(outbox_repo, run, EVENT_CLASSIFICATION_FAILED, error=error_payload)
            await session.commit()
            return

        started = time.perf_counter()
        try:
            result = self.classifier.classify_document(
                ProcedureClassificationInput(
                    treatment_code=run.procedure_code,
                    file_desc=document_text,
                    file_full_text=document_text,
                )
            )
        except LookupError as exc:
            error_payload = {"code": "no_prompt", "message": str(exc)}
            await run_repo.mark_failed(run, error_payload)
            await self._publish_event(outbox_repo, run, EVENT_CLASSIFICATION_FAILED, error=error_payload)
            await session.commit()
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("classifier_unexpected_error")
            error_payload = {"code": "classifier_failed", "message": str(exc)}
            await run_repo.mark_failed(run, error_payload)
            await self._publish_event(outbox_repo, run, EVENT_CLASSIFICATION_FAILED, error=error_payload)
            await session.commit()
            return

        latency_ms = int((time.perf_counter() - started) * 1000)
        pii_masked_count = self._count_redactions(result.masked_file_full_text)

        await run_repo.mark_done(
            run,
            prompt_source=result.prompt_source,
            used_definition=result.used_definition,
            result_code=result.result_code,
            idx_results=result.idx_results,
            raw_model_output=result.raw_model_output,
            error=result.error,
            llm_provider=self.settings.medical_classifier_llm_provider,
            llm_model=self.settings.medical_classifier_llm_model,
            masked=result.masked,
            pii_masked_count=pii_masked_count,
            latency_ms=latency_ms,
        )
        event_type = EVENT_CLASSIFICATION_FAILED if result.error else EVENT_CLASSIFICATION_DONE
        await self._publish_event(outbox_repo, run, event_type, error=result.error)
        await session.commit()

    async def _load_document_text(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
    ) -> str | None:
        document = await session.get(Document, document_id)
        if document is None:
            return None
        try:
            key = self._storage_key_from_uri(document.storage_uri, document.tenant_id, document.document_hash)
            payload = await self.storage.get(key)
            return payload.decode("utf-8")
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception("storage_read_failed", extra={"extra": {"document_id": str(document_id)}})
            return None

    @staticmethod
    def _storage_key_from_uri(uri: str, tenant_id: str, document_hash: str) -> str:
        return f"{tenant_id}/{document_hash[:2]}/{document_hash}.txt"

    @staticmethod
    def _count_redactions(text: str) -> int:
        return text.count("[ID_REMOVED]") if text else 0

    async def _publish_event(
        self,
        outbox_repo: OutboxRepository,
        run: ClassificationRun,
        event_type: str,
        *,
        error: dict[str, object] | None,
    ) -> None:
        if not run.callback_url:
            return
        payload: dict[str, object] = {
            "event": event_type,
            "job_id": str(run.job_id),
            "document_id": str(run.document_id),
            "tenant_id": run.tenant_id,
            "procedure_code": run.procedure_code,
            "result_code": run.result_code,
            "idx_results": run.idx_results,
            "prompt_source": run.prompt_source,
            "used_definition": run.used_definition,
            "masked": run.masked,
            "pii_masked_count": run.pii_masked_count,
            "latency_ms": run.latency_ms,
            "error": error,
        }
        await outbox_repo.enqueue(
            aggregate_type="classification_run",
            aggregate_id=str(run.id),
            event_type=event_type,
            payload=payload,
            destination_url=run.callback_url,
        )
