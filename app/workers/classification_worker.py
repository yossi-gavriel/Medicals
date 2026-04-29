from __future__ import annotations

import logging
import uuid
from typing import Any

from arq.connections import RedisSettings

from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.core.metrics import CLASSIFICATION_JOBS, CLASSIFICATION_LATENCY
from app.core.settings import get_settings
from app.core.storage import build_document_storage
from app.repositories.classification_repository import ClassificationRunRepository
from app.services.classification_pipeline import (
    CLASSIFY_FUNCTION_NAME,
    ClassificationExecutor,
)
from app.services.medical_classifier import (
    ProcedureClassificationService,
    build_generic_fallback_prompt_json,
    build_medical_classifier_llm_runner,
)

logger = logging.getLogger(__name__)


async def classify_document_job(ctx: dict[str, Any], run_id: str, job_id: str) -> dict[str, str]:
    executor: ClassificationExecutor = ctx["executor"]
    parsed_run_id = uuid.UUID(run_id)

    async with SessionLocal() as session:
        await executor.execute(session, parsed_run_id)

    async with SessionLocal() as session:
        run_repo = ClassificationRunRepository(session)
        run = await run_repo.get_by_job_id(uuid.UUID(job_id))

    tenant = run.tenant_id if run is not None else "unknown"
    status = run.status if run is not None else "unknown"
    CLASSIFICATION_JOBS.labels(status=status, tenant=tenant).inc()
    if run is not None and run.latency_ms is not None:
        CLASSIFICATION_LATENCY.labels(tenant=tenant).observe(run.latency_ms / 1000.0)
    return {"run_id": run_id, "job_id": job_id, "status": status}


classify_document_job.__name__ = CLASSIFY_FUNCTION_NAME


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    settings = get_settings()

    storage = build_document_storage(settings)
    classifier = ProcedureClassificationService.from_settings(
        llm_runner=build_medical_classifier_llm_runner(settings),
        settings=settings,
        prompt_provider=build_generic_fallback_prompt_json,
    )
    ctx["executor"] = ClassificationExecutor(
        settings=settings,
        storage=storage,
        classifier=classifier,
    )
    logger.info("worker_started", extra={"extra": {"queue": settings.classification_queue_name}})


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker_stopped")


class WorkerSettings:
    settings_obj = get_settings()
    functions = [classify_document_job]
    queue_name = settings_obj.classification_queue_name
    max_jobs = settings_obj.worker_concurrency
    job_timeout = settings_obj.classification_job_timeout_seconds
    max_tries = settings_obj.classification_max_retries
    redis_settings = RedisSettings.from_dsn(settings_obj.queue_redis_url)
    on_startup = startup
    on_shutdown = shutdown
