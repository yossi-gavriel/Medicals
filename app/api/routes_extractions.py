from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import ApiKeyDep, resolve_tenant_id
from app.repositories.extraction_repository import ExtractionRunRepository
from app.schemas.extraction import (
    ComplianceResultView,
    ComplianceRuleResultView,
    ExtractionAuditEntryView,
    ExtractionRunRequest,
    ExtractionRunResponse,
)
from app.services.compliance import ComplianceEvaluation, ComplianceEvaluator, ComplianceRuleEvaluation
from app.services.extraction_engine import ExtractionEngine, compute_spec_hash

router = APIRouter(prefix="/v1/extractions", tags=["extractions"])


def get_extraction_engine(request: Request) -> ExtractionEngine:
    engine = getattr(request.app.state, "extraction_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="extraction engine is not initialized",
        )
    return engine


@router.post("/run", response_model=ExtractionRunResponse)
async def run_extraction(
    payload: ExtractionRunRequest,
    request: Request,
    _api_key: ApiKeyDep,
    engine: ExtractionEngine = Depends(get_extraction_engine),
    session: AsyncSession = Depends(get_db_session),
) -> ExtractionRunResponse:
    started = time.perf_counter()
    result = engine.run(
        document_id=payload.document_id,
        document_text=payload.document_text,
        spec=payload.spec,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    compliance_results = ComplianceEvaluator().evaluate(extraction_result=result, spec=payload.spec)

    spec_hash = compute_spec_hash(payload.spec)
    # Tenant identity is derived strictly from the authenticated API key,
    # never from a client-supplied header or request body field.
    tenant_id = resolve_tenant_id(request)
    repository = ExtractionRunRepository(session)
    # Single transaction. Any failure inside `persist` raises and the context
    # manager rolls everything back; nothing is committed unless every insert
    # succeeded.
    async with session.begin():
        run_id = await repository.persist(
            result,
            spec_hash=spec_hash,
            tenant_id=tenant_id,
            metadata=payload.metadata,
            duration_ms=duration_ms,
            compliance_results=compliance_results,
        )

    return ExtractionRunResponse(
        run_id=str(run_id),
        document_id=result.document_id,
        spec_version=result.spec_version,
        spec_hash=spec_hash,
        rows=result.rows,
        audit=[
            ExtractionAuditEntryView(
                document_id=entry.document_id,
                treatment_code=entry.treatment_code,
                field_name=entry.field_name,
                value=entry.value,
                confidence=entry.confidence,
                evidence=entry.evidence,
                reason=entry.reason,
                error=entry.error,
            )
            for entry in result.audit
        ],
        compliance=[_compliance_view(item) for item in compliance_results],
        masked=result.masked,
        pii_masked_count=result.pii_masked_count,
    )


def _rule_view(rule: ComplianceRuleEvaluation) -> ComplianceRuleResultView:
    return ComplianceRuleResultView(
        rule_id=rule.rule_id,
        description=rule.description,
        field=rule.field,
        operator=rule.operator,
        expected=rule.expected,
        actual=rule.actual,
        severity=rule.severity,
        reason=rule.reason,
        recommended_action=rule.recommended_action,
        evidence=rule.evidence,
    )


def _compliance_view(evaluation: ComplianceEvaluation) -> ComplianceResultView:
    return ComplianceResultView(
        document_id=evaluation.document_id,
        treatment_code=evaluation.treatment_code,
        status=evaluation.status,
        recommended_action=evaluation.recommended_action,
        failed_rules=[_rule_view(rule) for rule in evaluation.failed_rules],
        passed_rules=[_rule_view(rule) for rule in evaluation.passed_rules],
        insufficient_data_rules=[_rule_view(rule) for rule in evaluation.insufficient_data_rules],
        manual_review_rules=[_rule_view(rule) for rule in evaluation.manual_review_rules],
    )
