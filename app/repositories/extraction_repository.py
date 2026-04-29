from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ComplianceResult,
    ComplianceRuleResult,
    ExtractionAudit,
    ExtractionRow,
    ExtractionRun,
    ReimbursementCase,
    ReimbursementCaseEvent,
)
from app.services.compliance import ComplianceEvaluation, ComplianceRuleEvaluation
from app.services.extraction_engine import ExtractionResult


class ExtractionRunRepository:
    """Persists an extraction run, its rows, and audit entries.

    All inserts run inside a single SQLAlchemy transaction owned by the caller.
    The repository never commits — the route's `async with session.begin()`
    block does, which means any exception from `persist` rolls every insert
    back atomically.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def persist(
        self,
        result: ExtractionResult,
        *,
        spec_hash: str,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        compliance_results: list[ComplianceEvaluation] | None = None,
    ) -> uuid.UUID:
        run = ExtractionRun(
            document_id=result.document_id,
            spec_version=result.spec_version,
            spec_hash=spec_hash,
            tenant_id=tenant_id,
            masked=result.masked,
            pii_masked_count=result.pii_masked_count,
            duration_ms=duration_ms,
            context_metadata=metadata or {},
        )
        self.session.add(run)
        # Flush to materialize run.id before children are inserted. If this
        # raises, the surrounding transaction will roll back.
        await self.session.flush()

        for row in result.rows:
            values = _strip_row_envelope(row)
            self.session.add(
                ExtractionRow(
                    run_id=run.id,
                    document_id=str(row.get("document_id", result.document_id)),
                    treatment_code=str(row["treatment_code"]),
                    values=values,
                )
            )

        for audit_entry in result.audit:
            self.session.add(
                ExtractionAudit(
                    run_id=run.id,
                    treatment_code=audit_entry.treatment_code,
                    field_name=audit_entry.field_name,
                    value=audit_entry.value,
                    confidence=audit_entry.confidence,
                    evidence=list(audit_entry.evidence),
                    reason=audit_entry.reason or None,
                    error=audit_entry.error,
                )
            )

        if compliance_results:
            await self._persist_compliance_results(
                run_id=run.id,
                tenant_id=tenant_id,
                metadata=metadata or {},
                compliance_results=compliance_results,
            )

        await self.session.flush()
        return run.id

    async def _persist_compliance_results(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: str | None,
        metadata: dict[str, Any],
        compliance_results: list[ComplianceEvaluation],
    ) -> None:
        for evaluation in compliance_results:
            result_model = ComplianceResult(
                run_id=run_id,
                document_id=evaluation.document_id,
                treatment_code=evaluation.treatment_code,
                status=evaluation.status,
                recommended_action=evaluation.recommended_action,
                failed_count=len(evaluation.failed_rules),
                passed_count=len(evaluation.passed_rules),
                insufficient_data_count=len(evaluation.insufficient_data_rules),
                highest_severity=evaluation.highest_severity,
            )
            self.session.add(result_model)
            await self.session.flush()

            for rule in _all_rule_evaluations(evaluation):
                self.session.add(
                    ComplianceRuleResult(
                        compliance_result_id=result_model.id,
                        run_id=run_id,
                        treatment_code=evaluation.treatment_code,
                        rule_id=rule.rule_id,
                        field_name=rule.field,
                        operator=rule.operator,
                        expected=rule.expected,
                        actual=rule.actual,
                        status=rule.status,
                        severity=rule.severity,
                        reason=rule.reason or None,
                        evidence=list(rule.evidence),
                    )
                )

            if (
                evaluation.status == "non_compliant"
                and evaluation.recommended_action == "request_reimbursement"
            ):
                reimbursement_case = ReimbursementCase(
                    run_id=run_id,
                    compliance_result_id=result_model.id,
                    tenant_id=tenant_id,
                    document_id=evaluation.document_id,
                    treatment_code=evaluation.treatment_code,
                    status="draft",
                    reason=_case_reason(evaluation),
                    estimated_amount=_decimal_from_metadata(metadata),
                    currency=_currency_from_metadata(metadata),
                )
                self.session.add(reimbursement_case)
                await self.session.flush()
                self.session.add(
                    ReimbursementCaseEvent(
                        case_id=reimbursement_case.id,
                        tenant_id=tenant_id,
                        previous_status=None,
                        new_status=reimbursement_case.status,
                        event_type="case_created",
                        note="Case created automatically from compliance result",
                        created_at=datetime.now(UTC),
                    )
                )


def _strip_row_envelope(row: dict[str, Any]) -> dict[str, Any]:
    """Return only the dynamic rule fields. document_id/treatment_code live
    on the row record itself and must not be duplicated inside ``values``.
    """
    return {key: value for key, value in row.items() if key not in {"document_id", "treatment_code"}}


def _all_rule_evaluations(evaluation: ComplianceEvaluation) -> list[ComplianceRuleEvaluation]:
    return [
        *evaluation.failed_rules,
        *evaluation.passed_rules,
        *evaluation.insufficient_data_rules,
        *evaluation.manual_review_rules,
    ]


def _case_reason(evaluation: ComplianceEvaluation) -> str:
    reasons = [rule.reason for rule in evaluation.failed_rules if rule.reason]
    return "; ".join(reasons) if reasons else "Non-compliant treatment detected"


def _decimal_from_metadata(metadata: dict[str, Any]) -> Decimal | None:
    for key in ("estimated_reimbursement_amount", "billed_amount"):
        value = metadata.get(key)
        if value is None or value == "":
            continue
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
    return None


def _currency_from_metadata(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("currency")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:8]
