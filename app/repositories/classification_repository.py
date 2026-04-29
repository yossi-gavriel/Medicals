from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClassificationRun, ClassificationStatus


class ClassificationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(
        self,
        *,
        document_id: uuid.UUID,
        tenant_id: str,
        procedure_code: str,
        max_attempts: int,
        callback_url: str | None,
        batch_id: uuid.UUID | None = None,
    ) -> ClassificationRun:
        run = ClassificationRun(
            document_id=document_id,
            tenant_id=tenant_id,
            procedure_code=procedure_code,
            status=ClassificationStatus.PENDING.value,
            max_attempts=max_attempts,
            callback_url=callback_url,
            batch_id=batch_id,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_by_job_id(self, job_id: uuid.UUID) -> ClassificationRun | None:
        result = await self.session.execute(
            select(ClassificationRun).where(ClassificationRun.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_by_batch_id(
        self, batch_id: uuid.UUID, *, tenant_id: str | None = None
    ) -> list[ClassificationRun]:
        stmt = select(ClassificationRun).where(ClassificationRun.batch_id == batch_id)
        if tenant_id is not None:
            stmt = stmt.where(ClassificationRun.tenant_id == tenant_id)
        stmt = stmt.order_by(ClassificationRun.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_update(self, run_id: uuid.UUID) -> ClassificationRun | None:
        result = await self.session.execute(
            select(ClassificationRun).where(ClassificationRun.id == run_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def mark_running(self, run: ClassificationRun) -> None:
        run.status = ClassificationStatus.RUNNING.value
        run.attempt = run.attempt + 1
        run.started_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def mark_done(
        self,
        run: ClassificationRun,
        *,
        prompt_source: str,
        used_definition: bool,
        result_code: int,
        idx_results: dict[str, int],
        raw_model_output: dict[str, Any],
        error: dict[str, Any] | None,
        llm_provider: str,
        llm_model: str,
        masked: bool,
        pii_masked_count: int,
        latency_ms: int,
    ) -> None:
        run.status = (
            ClassificationStatus.FAILED.value if error is not None else ClassificationStatus.DONE.value
        )
        run.prompt_source = prompt_source
        run.used_definition = used_definition
        run.result_code = result_code
        run.idx_results = idx_results
        run.raw_model_output = raw_model_output
        run.error = error
        run.llm_provider = llm_provider
        run.llm_model = llm_model
        run.masked = masked
        run.pii_masked_count = pii_masked_count
        run.latency_ms = latency_ms
        run.finished_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def mark_failed(self, run: ClassificationRun, error: dict[str, Any]) -> None:
        run.status = ClassificationStatus.FAILED.value
        run.error = error
        run.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
