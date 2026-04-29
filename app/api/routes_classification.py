from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.metrics import CLASSIFICATION_BATCHES
from app.core.security import InternalApiKeyDep
from app.core.settings import Settings, get_settings
from app.repositories.classification_repository import ClassificationRunRepository
from app.schemas import (
    BatchStatusCounts,
    BatchStatusView,
    ClassificationRunView,
    ClassifyAsyncAck,
    ClassifyAsyncRequest,
    ClassifyBatchAck,
    ClassifyBatchRequest,
)
from app.services.classification_pipeline import ClassificationPipeline

router = APIRouter(prefix="/v1/classifications", tags=["classifications"])


def get_classification_pipeline(request: Request) -> ClassificationPipeline:
    return request.app.state.classification_pipeline


def _tenant_from_request(request: Request) -> str:
    tenant = request.headers.get("X-Tenant-Id")
    if tenant:
        return tenant.strip()[:64] or "default"
    return "default"


@router.post(
    "",
    response_model=ClassifyAsyncAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a document for asynchronous classification.",
)
async def submit_classification(
    payload: ClassifyAsyncRequest,
    request: Request,
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    pipeline: ClassificationPipeline = Depends(get_classification_pipeline),
) -> ClassifyAsyncAck:
    tenant = _tenant_from_request(request)
    result = await pipeline.ingest(
        session,
        tenant_id=tenant,
        procedure_code=payload.procedure_code,
        document_text=payload.document_text,
        external_document_id=payload.document_id,
        source_system=payload.source_system,
        callback_url=str(payload.callback_url) if payload.callback_url else None,
        metadata=payload.metadata,
    )
    return ClassifyAsyncAck(
        job_id=result.run.job_id,
        document_id=result.document.id,
        status=result.run.status,
        deduplicated=result.deduplicated,
        poll_url=f"/v1/classifications/{result.run.job_id}",
    )


@router.post(
    "/batch",
    response_model=ClassifyBatchAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit multiple documents in one call; returns a shared batch_id.",
)
async def submit_classification_batch(
    payload: ClassifyBatchRequest,
    request: Request,
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    pipeline: ClassificationPipeline = Depends(get_classification_pipeline),
) -> ClassifyBatchAck:
    settings: Settings = get_settings()
    if len(payload.items) > settings.classification_batch_max_items:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"batch exceeds maximum of {settings.classification_batch_max_items} items"
            ),
        )

    tenant = _tenant_from_request(request)
    batch_id = uuid.uuid4()
    acks: list[ClassifyAsyncAck] = []
    deduplicated = 0
    for item in payload.items:
        result = await pipeline.ingest(
            session,
            tenant_id=tenant,
            procedure_code=item.procedure_code,
            document_text=item.document_text,
            external_document_id=item.document_id,
            source_system=item.source_system,
            callback_url=str(item.callback_url) if item.callback_url else None,
            metadata=item.metadata,
            batch_id=batch_id,
        )
        if result.deduplicated:
            deduplicated += 1
        acks.append(
            ClassifyAsyncAck(
                job_id=result.run.job_id,
                document_id=result.document.id,
                status=result.run.status,
                deduplicated=result.deduplicated,
                poll_url=f"/v1/classifications/{result.run.job_id}",
            )
        )

    CLASSIFICATION_BATCHES.labels(tenant=tenant).inc()
    return ClassifyBatchAck(
        batch_id=batch_id,
        submitted=len(acks),
        deduplicated=deduplicated,
        items=acks,
        poll_url=f"/v1/classifications/batch/{batch_id}",
    )


@router.get(
    "/batch/{batch_id}",
    response_model=BatchStatusView,
    summary="Fetch aggregate status and per-item results of a classification batch.",
)
async def get_classification_batch(
    batch_id: uuid.UUID,
    request: Request,
    _api_key: InternalApiKeyDep,
    include_raw: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
) -> BatchStatusView:
    tenant = _tenant_from_request(request)
    repo = ClassificationRunRepository(session)
    runs = await repo.list_by_batch_id(batch_id, tenant_id=tenant)
    if not runs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="batch not found"
        )

    counts = BatchStatusCounts(
        total=len(runs),
        pending=sum(1 for r in runs if r.status == "pending"),
        running=sum(1 for r in runs if r.status == "running"),
        done=sum(1 for r in runs if r.status == "done"),
        failed=sum(1 for r in runs if r.status == "failed"),
    )
    return BatchStatusView(
        batch_id=batch_id,
        counts=counts,
        items=[ClassificationRunView.from_model(r, include_raw=include_raw) for r in runs],
    )


@router.get(
    "/{job_id}",
    response_model=ClassificationRunView,
    summary="Fetch the status and outcome of a classification job.",
)
async def get_classification_job(
    job_id: uuid.UUID,
    _api_key: InternalApiKeyDep,
    include_raw: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
) -> ClassificationRunView:
    repo = ClassificationRunRepository(session)
    run = await repo.get_by_job_id(job_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return ClassificationRunView.from_model(run, include_raw=include_raw)
