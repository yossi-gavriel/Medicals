from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import ApiKeyDep, InternalApiKeyDep, resolve_tenant_id
from app.repositories.dashboard_repository import DashboardRepository, InvalidCaseTransition
from app.schemas.dashboard import ReimbursementCaseUpdateRequest

router = APIRouter(tags=["dashboard"])


@router.get("/v1/dashboard/summary")
async def customer_summary(
    request: Request,
    _api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> dict:
    return await DashboardRepository(session).summary(
        tenant_id=resolve_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
        treatment_code=treatment_code,
        status=status,
        recommended_action=recommended_action,
    )


@router.get("/v1/dashboard/treatments")
async def customer_treatments(
    request: Request,
    _api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> list[dict]:
    return await DashboardRepository(session).treatments(
        tenant_id=resolve_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
        treatment_code=treatment_code,
        status=status,
        recommended_action=recommended_action,
    )


@router.get("/v1/dashboard/rules")
async def customer_rules(
    request: Request,
    _api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> dict:
    return await DashboardRepository(session).rules(
        tenant_id=resolve_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
        treatment_code=treatment_code,
        status=status,
        recommended_action=recommended_action,
    )


@router.get("/v1/dashboard/documents/timeseries")
async def customer_documents_timeseries(
    request: Request,
    _api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> list[dict]:
    return await DashboardRepository(session).documents_timeseries(
        tenant_id=resolve_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
        treatment_code=treatment_code,
        status=status,
        recommended_action=recommended_action,
    )


@router.get("/v1/dashboard/reimbursement-cases")
async def customer_reimbursement_cases(
    request: Request,
    _api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await DashboardRepository(session).reimbursement_cases(
        tenant_id=resolve_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
        treatment_code=treatment_code,
        status=status,
        recommended_action=recommended_action,
        limit=limit,
        offset=offset,
    )


@router.get("/v1/dashboard/reimbursement-cases/{case_id}")
async def customer_reimbursement_case_detail(
    case_id: str,
    request: Request,
    _api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    item = await DashboardRepository(session).reimbursement_case_detail(
        case_id,
        tenant_id=resolve_tenant_id(request),
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return item


@router.patch("/v1/dashboard/reimbursement-cases/{case_id}")
async def customer_update_reimbursement_case(
    case_id: str,
    payload: ReimbursementCaseUpdateRequest,
    request: Request,
    api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    repo = DashboardRepository(session)
    try:
        async with session.begin():
            item = await repo.update_reimbursement_case(
                case_id,
                tenant_id=resolve_tenant_id(request),
                updates=payload.update_fields(),
                actor_id=api_key,
            )
    except InvalidCaseTransition as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return item


@router.get("/v1/admin/dashboard/summary")
async def admin_summary(
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> dict:
    repo = DashboardRepository(session)
    kwargs = _admin_scope_kwargs(
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
        treatment_code=treatment_code,
        status=status,
        recommended_action=recommended_action,
    )
    return await repo.summary(**kwargs)


@router.get("/v1/admin/dashboard/tenants")
async def admin_tenants(
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> list[dict]:
    return await DashboardRepository(session).tenants(
        **_admin_scope_kwargs(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            treatment_code=treatment_code,
            status=status,
            recommended_action=recommended_action,
        )
    )


@router.get("/v1/admin/dashboard/tenants/{tenant_id}/summary")
async def admin_tenant_summary(
    tenant_id: str,
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> dict:
    return await DashboardRepository(session).summary(
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
        treatment_code=treatment_code,
        status=status,
        recommended_action=recommended_action,
    )


@router.get("/v1/admin/dashboard/treatments")
async def admin_treatments(
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
) -> list[dict]:
    return await DashboardRepository(session).treatments(
        **_admin_scope_kwargs(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            treatment_code=treatment_code,
            status=status,
            recommended_action=recommended_action,
        )
    )


@router.get("/v1/admin/dashboard/reimbursement-cases")
async def admin_reimbursement_cases(
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    treatment_code: str | None = None,
    status: str | None = None,
    recommended_action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await DashboardRepository(session).reimbursement_cases(
        **_admin_scope_kwargs(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            treatment_code=treatment_code,
            status=status,
            recommended_action=recommended_action,
        ),
        limit=limit,
        offset=offset,
    )


@router.get("/v1/admin/dashboard/reimbursement-cases/{case_id}")
async def admin_reimbursement_case_detail(
    case_id: str,
    _api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    item = await DashboardRepository(session).reimbursement_case_detail(case_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return item


@router.patch("/v1/admin/dashboard/reimbursement-cases/{case_id}")
async def admin_update_reimbursement_case(
    case_id: str,
    payload: ReimbursementCaseUpdateRequest,
    api_key: InternalApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    repo = DashboardRepository(session)
    try:
        async with session.begin():
            item = await repo.update_reimbursement_case(
                case_id,
                updates=payload.update_fields(),
                actor_id=api_key,
            )
    except InvalidCaseTransition as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return item


def _admin_scope_kwargs(
    *,
    tenant_id: str | None,
    date_from: date | None,
    date_to: date | None,
    treatment_code: str | None,
    status: str | None,
    recommended_action: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "date_from": date_from,
        "date_to": date_to,
        "treatment_code": treatment_code,
        "status": status,
        "recommended_action": recommended_action,
    }
    if tenant_id is not None:
        kwargs["tenant_id"] = tenant_id
    return kwargs
