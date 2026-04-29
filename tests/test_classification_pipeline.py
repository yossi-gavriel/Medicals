from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.queue import InMemoryJobEnqueuer
from app.core.settings import Settings
from app.core.storage import LocalDocumentStorage
from app.models import ClassificationRun, ClassificationStatus, Document
from app.repositories.classification_repository import ClassificationRunRepository
from app.repositories.outbox_repository import OutboxRepository
from app.services.classification_pipeline import (
    CLASSIFY_FUNCTION_NAME,
    ClassificationExecutor,
    ClassificationPipeline,
)
from app.services.medical_classifier import (
    ProcedureClassificationService,
    build_generic_fallback_prompt_json,
)


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path/'test.db'}"
    try:
        engine = create_async_engine(db_url, future=True)
    except ModuleNotFoundError:
        pytest.skip("aiosqlite is required for async SQLite tests")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _settings(tmp_path) -> Settings:
    return Settings(
        document_storage_backend="local",
        document_storage_local_path=str(tmp_path / "docs"),
        classification_max_retries=3,
        medical_classifier_llm_provider="disabled",
    )


class _StubRunner:
    def __init__(self, result_code: str = "1") -> None:
        self.result_code = result_code

    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str) -> dict[str, Any]:
        return {"result_code": self.result_code}


def _classifier() -> ProcedureClassificationService:
    return ProcedureClassificationService(
        llm_runner=_StubRunner(),
        prompt_provider=build_generic_fallback_prompt_json,
    )


@pytest.mark.asyncio
async def test_pipeline_ingest_creates_document_and_pending_run(session_factory, tmp_path):
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_local_path)
    enqueuer = InMemoryJobEnqueuer()
    pipeline = ClassificationPipeline(settings=settings, storage=storage, enqueuer=enqueuer)

    async with session_factory() as session:
        result = await pipeline.ingest(
            session,
            tenant_id="t1",
            procedure_code="proc-async",
            document_text="בוצע ניתוח לדוגמה",
            external_document_id="doc-1",
            source_system="EHR-A",
            callback_url=None,
            metadata={},
        )

    assert result.deduplicated is False
    assert result.run.status == ClassificationStatus.PENDING.value
    assert enqueuer.calls and enqueuer.calls[0][0] == CLASSIFY_FUNCTION_NAME


@pytest.mark.asyncio
async def test_pipeline_ingest_deduplicates_repeated_text(session_factory, tmp_path):
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_local_path)
    enqueuer = InMemoryJobEnqueuer()
    pipeline = ClassificationPipeline(settings=settings, storage=storage, enqueuer=enqueuer)

    async with session_factory() as session:
        first = await pipeline.ingest(
            session,
            tenant_id="t1",
            procedure_code="proc-async",
            document_text="content X",
            external_document_id=None,
            source_system=None,
            callback_url=None,
            metadata={},
        )
    async with session_factory() as session:
        second = await pipeline.ingest(
            session,
            tenant_id="t1",
            procedure_code="proc-async",
            document_text="content X",
            external_document_id=None,
            source_system=None,
            callback_url=None,
            metadata={},
        )

    assert second.deduplicated is True
    assert first.document.id == second.document.id
    # both runs should still be enqueued (dedup of doc only)
    assert len(enqueuer.calls) == 2


@pytest.mark.asyncio
async def test_executor_marks_run_done_and_writes_results(session_factory, tmp_path):
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_local_path)
    pipeline = ClassificationPipeline(settings=settings, storage=storage, enqueuer=InMemoryJobEnqueuer())
    executor = ClassificationExecutor(settings=settings, storage=storage, classifier=_classifier())

    async with session_factory() as session:
        ingest = await pipeline.ingest(
            session,
            tenant_id="t1",
            procedure_code="proc-async",
            document_text="בוצע ניתוח 123456789",
            external_document_id=None,
            source_system=None,
            callback_url="https://example.test/cb",
            metadata={},
        )
        run_id = ingest.run.id

    async with session_factory() as session:
        await executor.execute(session, run_id)

    async with session_factory() as session:
        repo = ClassificationRunRepository(session)
        run = await repo.get_for_update(run_id)
        assert run is not None
        assert run.status == ClassificationStatus.DONE.value
        assert run.result_code == 1
        assert run.idx_results == {"IDX_PROCEDURE_PERFORMED": 1}
        assert run.pii_masked_count == 1
        assert run.latency_ms is not None and run.latency_ms >= 0
        assert run.finished_at is not None


@pytest.mark.asyncio
async def test_executor_publishes_outbox_event_when_callback_present(session_factory, tmp_path):
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_local_path)
    pipeline = ClassificationPipeline(settings=settings, storage=storage, enqueuer=InMemoryJobEnqueuer())
    executor = ClassificationExecutor(settings=settings, storage=storage, classifier=_classifier())

    async with session_factory() as session:
        ingest = await pipeline.ingest(
            session,
            tenant_id="t1",
            procedure_code="proc-async",
            document_text="text body",
            external_document_id=None,
            source_system=None,
            callback_url="https://example.test/cb",
            metadata={},
        )
        run_id = ingest.run.id

    async with session_factory() as session:
        await executor.execute(session, run_id)

    async with session_factory() as session:
        outbox_repo = OutboxRepository(session)
        events = await outbox_repo.fetch_due(batch_size=10)
        assert events
        assert events[0].event_type == "classification.completed"
        assert events[0].destination_url == "https://example.test/cb"


@pytest.mark.asyncio
async def test_executor_no_outbox_when_no_callback(session_factory, tmp_path):
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_local_path)
    pipeline = ClassificationPipeline(settings=settings, storage=storage, enqueuer=InMemoryJobEnqueuer())
    executor = ClassificationExecutor(settings=settings, storage=storage, classifier=_classifier())

    async with session_factory() as session:
        ingest = await pipeline.ingest(
            session,
            tenant_id="t1",
            procedure_code="proc-async",
            document_text="another body",
            external_document_id=None,
            source_system=None,
            callback_url=None,
            metadata={},
        )
        run_id = ingest.run.id

    async with session_factory() as session:
        await executor.execute(session, run_id)

    async with session_factory() as session:
        outbox_repo = OutboxRepository(session)
        events = await outbox_repo.fetch_due(batch_size=10)
        assert events == []


@pytest.mark.asyncio
async def test_outbox_retry_increments_attempts(session_factory):
    async with session_factory() as session:
        repo = OutboxRepository(session)
        event = await repo.enqueue(
            aggregate_type="t",
            aggregate_id="1",
            event_type="x",
            payload={"k": "v"},
            destination_url="https://example.test",
            max_attempts=3,
        )
        await repo.mark_retry(event, error="boom", backoff_seconds=0.0)
        assert event.attempts == 1
        assert event.status == "pending"
        await repo.mark_retry(event, error="boom", backoff_seconds=0.0)
        await repo.mark_retry(event, error="boom", backoff_seconds=0.0)
        assert event.attempts == 3
        assert event.status == "dead"
