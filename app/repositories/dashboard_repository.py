from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ComplianceResult,
    ComplianceRuleResult,
    ExtractionRow,
    ExtractionRun,
    ReimbursementCase,
    ReimbursementCaseEvent,
)

_UNSET = object()
REIMBURSEMENT_CASE_STATUSES = {"draft", "ready", "sent", "accepted", "rejected", "closed"}
ALLOWED_REIMBURSEMENT_TRANSITIONS = {
    "draft": {"ready", "closed"},
    "ready": {"sent", "closed", "draft"},
    "sent": {"accepted", "rejected", "closed"},
    "accepted": {"closed"},
    "rejected": {"closed"},
    "closed": set(),
}


class InvalidCaseTransition(ValueError):
    pass


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(
        self,
        *,
        tenant_id: str | None | object = _UNSET,
        date_from: date | None = None,
        date_to: date | None = None,
        treatment_code: str | None = None,
        status: str | None = None,
        recommended_action: str | None = None,
    ) -> dict[str, Any]:
        data = await self._load_scope(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            treatment_code=treatment_code,
            status=status,
            recommended_action=recommended_action,
        )
        runs = data["runs"]
        rows = data["rows"]
        compliance = data["compliance"]
        rule_results = data["rule_results"]
        cases = data["cases"]

        compliance_status = Counter(item.status for item in compliance)
        cases_status = Counter(item.status for item in cases)
        non_compliant = [item for item in compliance if item.status == "non_compliant"]
        failed_rules = [item for item in rule_results if item.status == "failed"]
        fields_with_evidence = [item for item in data["audit_like_rule_results"] if item["has_evidence"]]
        failed_with_evidence = [item for item in failed_rules if item.evidence]
        patient_ids = {
            str(run.context_metadata.get("patient_id"))
            for run in runs
            if run.context_metadata.get("patient_id")
        }
        document_treatment_counts = Counter(row.document_id for row in rows)
        case_document_ids = {case.document_id for case in cases}
        manual_review_document_ids = {
            item.document_id for item in compliance if item.status == "manual_review"
        }
        document_id_by_run_id = {run.id: run.document_id for run in runs}
        critical_missing_document_ids = {
            document_id_by_run_id[item.run_id]
            for item in rule_results
            if item.status == "insufficient_data"
            and item.severity == "critical"
            and item.run_id in document_id_by_run_id
        }
        tenant_case_amounts: dict[str | None, float] = defaultdict(float)
        tenant_document_counts = Counter(run.tenant_id for run in runs)
        for case in cases:
            tenant_case_amounts[case.tenant_id] += _sum_amount([case])

        return {
            "total_documents": len({run.document_id for run in runs}),
            "total_patients": len(patient_ids),
            "total_extraction_runs": len(runs),
            "total_treatments_detected": len(rows),
            "total_compliance_results": len(compliance),
            "compliant_count": compliance_status["compliant"],
            "non_compliant_count": compliance_status["non_compliant"],
            "insufficient_data_count": compliance_status["insufficient_data"],
            "manual_review_count": compliance_status["manual_review"],
            "reimbursement_cases_total": len(cases),
            "reimbursement_cases_draft": cases_status["draft"],
            "reimbursement_cases_ready": cases_status["ready"],
            "reimbursement_cases_sent": cases_status["sent"],
            "reimbursement_cases_accepted": cases_status["accepted"],
            "reimbursement_cases_rejected": cases_status["rejected"],
            "reimbursement_cases_closed": cases_status["closed"],
            "estimated_reimbursement_amount_total": _sum_amount(cases),
            "accepted_reimbursement_amount_total": _sum_amount(
                [case for case in cases if case.status == "accepted"]
            ),
            "average_processing_time_ms": _average(
                [run.duration_ms for run in runs if run.duration_ms is not None]
            ),
            "average_rules_per_document": _safe_div(len(rule_results), len({run.document_id for run in runs})),
            "average_failed_rules_per_non_compliant_case": _safe_div(
                len(failed_rules),
                len(non_compliant),
            ),
            "extraction_success_count": len(runs),
            "extraction_failure_count": 0,
            "compliance_evaluation_success_count": len(compliance),
            "compliance_evaluation_failure_count": 0,
            "average_run_duration": _average(
                [run.duration_ms for run in runs if run.duration_ms is not None]
            ),
            "p95_run_duration": _percentile(
                [run.duration_ms for run in runs if run.duration_ms is not None],
                0.95,
            ),
            "llm_fallback_usage_count": 0,
            "llm_fallback_rate": 0.0,
            "audit_evidence_coverage": {
                "percent_of_fields_with_evidence": _safe_percent(
                    len(fields_with_evidence),
                    len(data["audit_like_rule_results"]),
                ),
                "percent_of_failed_compliance_rules_with_evidence": _safe_percent(
                    len(failed_with_evidence),
                    len(failed_rules),
                ),
            },
            "spec_hash_usage_counts": dict(Counter(run.spec_hash for run in runs)),
            "spec_versions_used": dict(Counter(run.spec_version for run in runs if run.spec_version)),
            "appeal_acceptance_rate": _safe_percent(
                cases_status["accepted"],
                cases_status["accepted"] + cases_status["rejected"],
            ),
            "appeals_created": len(cases),
            "appeals_sent": cases_status["sent"],
            "appeals_accepted": cases_status["accepted"],
            "appeals_rejected": cases_status["rejected"],
            "appeals_pending": cases_status["draft"] + cases_status["ready"] + cases_status["sent"],
            "amount_pending": _sum_amount(
                [case for case in cases if case.status in {"draft", "ready", "sent"}]
            ),
            "amount_accepted": _sum_amount([case for case in cases if case.status == "accepted"]),
            "amount_rejected": _sum_amount([case for case in cases if case.status == "rejected"]),
            "tenants_count": len({run.tenant_id for run in runs}),
            "active_tenants_count": len({run.tenant_id for run in runs}),
            "documents_with_multiple_treatments": sum(
                1 for count in document_treatment_counts.values() if count > 1
            ),
            "documents_that_generated_reimbursement_cases": len(case_document_ids),
            "documents_needing_manual_review": len(manual_review_document_ids),
            "documents_missing_critical_fields": len(critical_missing_document_ids),
            "top_tenants_by_potential_reimbursement": [
                {"tenant_id": tenant, "estimated_amount": amount}
                for tenant, amount in sorted(
                    tenant_case_amounts.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:10]
            ],
            "top_tenants_by_document_volume": [
                {"tenant_id": tenant, "documents": count}
                for tenant, count in tenant_document_counts.most_common(10)
            ],
            "top_treatments_by_refund_opportunity": _counter_amount_items(
                cases,
                "treatment_code",
                "estimated_amount",
            ),
            "top_failing_treatment_codes": _counter_items(
                Counter(item.treatment_code for item in non_compliant),
                "treatment_code",
                "non_compliant_count",
            ),
            "top_hospitals": _counter_items(
                Counter(
                    str(run.context_metadata.get("hospital_name"))
                    for run in runs
                    if run.context_metadata.get("hospital_name")
                ),
                "hospital_name",
                "documents",
            ),
            "top_providers": _counter_items(
                Counter(
                    str(run.context_metadata.get("provider_name"))
                    for run in runs
                    if run.context_metadata.get("provider_name")
                ),
                "provider_name",
                "documents",
            ),
            "top_failure_reasons": _counter_items(
                Counter(item.reason for item in failed_rules if item.reason),
                "reason",
                "failed_count",
            ),
        }

    async def treatments(self, **filters: Any) -> list[dict[str, Any]]:
        data = await self._load_scope(**filters)
        rows = data["rows"]
        compliance = data["compliance"]
        cases = data["cases"]

        treatment_codes = sorted(
            {
                *[row.treatment_code for row in rows],
                *[item.treatment_code for item in compliance],
                *[case.treatment_code for case in cases],
            }
        )
        results: list[dict[str, Any]] = []
        for code in treatment_codes:
            code_rows = [row for row in rows if row.treatment_code == code]
            code_compliance = [item for item in compliance if item.treatment_code == code]
            code_non_compliant = [item for item in code_compliance if item.status == "non_compliant"]
            code_cases = [case for case in cases if case.treatment_code == code]
            results.append(
                {
                    "treatment_code": code,
                    "documents": len({row.document_id for row in code_rows}),
                    "extraction_rows": len(code_rows),
                    "compliance_results": len(code_compliance),
                    "non_compliant_cases": len(code_non_compliant),
                    "non_compliance_rate": _safe_percent(
                        len(code_non_compliant),
                        len(code_compliance),
                    ),
                    "reimbursement_cases": len(code_cases),
                    "estimated_reimbursement_amount": _sum_amount(code_cases),
                }
            )
        return sorted(results, key=lambda item: item["non_compliant_cases"], reverse=True)

    async def rules(self, **filters: Any) -> dict[str, Any]:
        data = await self._load_scope(**filters)
        rule_results = data["rule_results"]
        failed = [item for item in rule_results if item.status == "failed"]
        insufficient = [item for item in rule_results if item.status == "insufficient_data"]
        by_rule_total = Counter(item.rule_id for item in rule_results)
        by_rule_failed = Counter(item.rule_id for item in failed)
        failure_rates = [
            {
                "rule_id": rule_id,
                "failed_count": failed_count,
                "total_count": by_rule_total[rule_id],
                "failure_rate": _safe_percent(failed_count, by_rule_total[rule_id]),
            }
            for rule_id, failed_count in by_rule_failed.items()
        ]
        return {
            "failed_rules_by_rule_id": _counter_items(by_rule_failed, "rule_id", "failed_count"),
            "failed_rules_by_field_name": _counter_items(
                Counter(item.field_name for item in failed),
                "field_name",
                "failed_count",
            ),
            "failure_rate_per_rule_id": sorted(
                failure_rates,
                key=lambda item: item["failure_rate"],
                reverse=True,
            ),
            "insufficient_data_by_field_name": _counter_items(
                Counter(item.field_name for item in insufficient),
                "field_name",
                "insufficient_data_count",
            ),
            "fields_most_often_missing": _counter_items(
                Counter(item.field_name for item in insufficient),
                "field_name",
                "missing_count",
            ),
            "top_rules_causing_reimbursement_cases": _counter_items(
                Counter(item.rule_id for item in failed if item.evidence),
                "rule_id",
                "failed_with_evidence_count",
            ),
        }

    async def documents_timeseries(self, **filters: Any) -> list[dict[str, Any]]:
        data = await self._load_scope(**filters)
        buckets: dict[date, dict[str, Any]] = defaultdict(
            lambda: {
                "date": "",
                "documents": 0,
                "extraction_runs": 0,
                "compliant": 0,
                "non_compliant": 0,
                "insufficient_data": 0,
                "manual_review": 0,
                "reimbursement_cases": 0,
            }
        )
        documents_by_day: dict[date, set[str]] = defaultdict(set)
        for run in data["runs"]:
            day = _as_date(run.created_at)
            documents_by_day[day].add(run.document_id)
            buckets[day]["date"] = day.isoformat()
            buckets[day]["extraction_runs"] += 1
        for item in data["compliance"]:
            day = _as_date(item.created_at)
            buckets[day]["date"] = day.isoformat()
            buckets[day][item.status] += 1
        for case in data["cases"]:
            day = _as_date(case.created_at)
            buckets[day]["date"] = day.isoformat()
            buckets[day]["reimbursement_cases"] += 1
        for day, documents in documents_by_day.items():
            buckets[day]["documents"] = len(documents)
        return [buckets[day] for day in sorted(buckets)]

    async def reimbursement_cases(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        data = await self._load_scope(**filters)
        cases = sorted(data["cases"], key=lambda item: item.created_at, reverse=True)
        total = len(cases)
        page = cases[offset : offset + limit]
        return {
            "items": [_case_view(case) for case in page],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def reimbursement_case_detail(
        self,
        case_id: str,
        *,
        tenant_id: str | None | object = _UNSET,
    ) -> dict[str, Any] | None:
        case = await self._get_case(case_id, tenant_id=tenant_id)
        if case is None:
            return None
        return await self._case_detail_view(case)

    async def update_reimbursement_case(
        self,
        case_id: str,
        *,
        tenant_id: str | None | object = _UNSET,
        updates: dict[str, Any],
        actor_id: str | None = None,
    ) -> dict[str, Any] | None:
        case = await self._get_case(case_id, tenant_id=tenant_id)
        if case is None:
            return None

        previous_status = case.status
        requested_status = updates.get("status")
        status_changed = requested_status is not None and requested_status != previous_status
        if requested_status is not None:
            self._validate_status_transition(previous_status, str(requested_status))

        note = updates.get("note")
        amount_changed = False
        currency_changed = False
        event_metadata: dict[str, Any] = {}

        if "estimated_amount" in updates:
            new_amount = _decimal_or_none(updates.get("estimated_amount"))
            old_amount = _decimal_or_none(case.estimated_amount)
            amount_changed = new_amount != old_amount
            if amount_changed:
                event_metadata["previous_estimated_amount"] = _decimal_to_float(old_amount)
                event_metadata["new_estimated_amount"] = _decimal_to_float(new_amount)
                case.estimated_amount = new_amount

        if "currency" in updates:
            new_currency = updates.get("currency")
            currency_changed = new_currency != case.currency
            if currency_changed:
                event_metadata["previous_currency"] = case.currency
                event_metadata["new_currency"] = new_currency
                case.currency = new_currency

        if status_changed:
            event_created_at = datetime.now(UTC)
            case.status = str(requested_status)
            self._apply_status_timestamps(case)
            self.session.add(
                ReimbursementCaseEvent(
                    case_id=case.id,
                    tenant_id=case.tenant_id,
                    previous_status=previous_status,
                    new_status=case.status,
                    event_type="status_changed",
                    note=note,
                    actor_id=actor_id,
                    created_at=event_created_at,
                )
            )

        if amount_changed or currency_changed:
            event_created_at = datetime.now(UTC)
            self.session.add(
                ReimbursementCaseEvent(
                    case_id=case.id,
                    tenant_id=case.tenant_id,
                    previous_status=previous_status,
                    new_status=case.status,
                    event_type="amount_updated",
                    note=None,
                    actor_id=actor_id,
                    event_metadata=event_metadata,
                    created_at=event_created_at,
                )
            )

        if note and not status_changed:
            event_created_at = datetime.now(UTC)
            self.session.add(
                ReimbursementCaseEvent(
                    case_id=case.id,
                    tenant_id=case.tenant_id,
                    previous_status=previous_status,
                    new_status=case.status,
                    event_type="note_added",
                    note=note,
                    actor_id=actor_id,
                    created_at=event_created_at,
                )
            )

        case.updated_at = datetime.now(UTC)
        await self.session.flush()
        return await self._case_detail_view(case)

    async def tenants(self, **filters: Any) -> list[dict[str, Any]]:
        data = await self._load_scope(**filters)
        tenant_ids = sorted({run.tenant_id for run in data["runs"]}, key=lambda item: item or "")
        rows: list[dict[str, Any]] = []
        for tenant_id in tenant_ids:
            tenant_runs = [run for run in data["runs"] if run.tenant_id == tenant_id]
            tenant_rows = [row for row in data["rows"] if row.run_id in {run.id for run in tenant_runs}]
            tenant_compliance = [
                item for item in data["compliance"] if item.run_id in {run.id for run in tenant_runs}
            ]
            tenant_cases = [case for case in data["cases"] if case.tenant_id == tenant_id]
            insufficient = [item for item in tenant_compliance if item.status == "insufficient_data"]
            non_compliant = [item for item in tenant_compliance if item.status == "non_compliant"]
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "documents": len({run.document_id for run in tenant_runs}),
                    "treatments": len(tenant_rows),
                    "non_compliant_count": len(non_compliant),
                    "reimbursement_cases": len(tenant_cases),
                    "estimated_amount": _sum_amount(tenant_cases),
                    "accepted_amount": _sum_amount(
                        [case for case in tenant_cases if case.status == "accepted"]
                    ),
                    "insufficient_data_rate": _safe_percent(
                        len(insufficient),
                        len(tenant_compliance),
                    ),
                    "non_compliance_rate": _safe_percent(
                        len(non_compliant),
                        len(tenant_compliance),
                    ),
                }
            )
        return rows

    async def _load_scope(
        self,
        *,
        tenant_id: str | None | object = _UNSET,
        date_from: date | None = None,
        date_to: date | None = None,
        treatment_code: str | None = None,
        status: str | None = None,
        recommended_action: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        runs_stmt = select(ExtractionRun)
        if tenant_id is _UNSET:
            pass
        elif tenant_id is None:
            runs_stmt = runs_stmt.where(ExtractionRun.tenant_id.is_(None))
        else:
            runs_stmt = runs_stmt.where(ExtractionRun.tenant_id == tenant_id)
        if date_from is not None:
            runs_stmt = runs_stmt.where(ExtractionRun.created_at >= _start_of_day(date_from))
        if date_to is not None:
            runs_stmt = runs_stmt.where(ExtractionRun.created_at <= _end_of_day(date_to))

        runs = (await self.session.execute(runs_stmt)).scalars().all()
        run_ids = [run.id for run in runs]
        if not run_ids:
            return {
                "runs": [],
                "rows": [],
                "compliance": [],
                "rule_results": [],
                "cases": [],
                "audit_like_rule_results": [],
            }

        rows_stmt = select(ExtractionRow).where(ExtractionRow.run_id.in_(run_ids))
        compliance_stmt = select(ComplianceResult).where(ComplianceResult.run_id.in_(run_ids))
        rules_stmt = select(ComplianceRuleResult).where(ComplianceRuleResult.run_id.in_(run_ids))
        cases_stmt = select(ReimbursementCase).where(ReimbursementCase.run_id.in_(run_ids))

        if treatment_code:
            rows_stmt = rows_stmt.where(ExtractionRow.treatment_code == treatment_code)
            compliance_stmt = compliance_stmt.where(ComplianceResult.treatment_code == treatment_code)
            rules_stmt = rules_stmt.where(ComplianceRuleResult.treatment_code == treatment_code)
            cases_stmt = cases_stmt.where(ReimbursementCase.treatment_code == treatment_code)
        if status:
            compliance_stmt = compliance_stmt.where(ComplianceResult.status == status)
            cases_stmt = cases_stmt.where(ReimbursementCase.status == status)
        if recommended_action:
            compliance_stmt = compliance_stmt.where(
                ComplianceResult.recommended_action == recommended_action
            )

        rows = (await self.session.execute(rows_stmt)).scalars().all()
        compliance = (await self.session.execute(compliance_stmt)).scalars().all()
        rule_results = (await self.session.execute(rules_stmt)).scalars().all()
        cases = (await self.session.execute(cases_stmt)).scalars().all()
        audit_like = [{"has_evidence": bool(item.evidence)} for item in rule_results]
        return {
            "runs": runs,
            "rows": rows,
            "compliance": compliance,
            "rule_results": rule_results,
            "cases": cases,
            "audit_like_rule_results": audit_like,
        }

    async def _get_case(
        self,
        case_id: str,
        *,
        tenant_id: str | None | object = _UNSET,
    ) -> ReimbursementCase | None:
        parsed_id = _uuid_or_none(case_id)
        if parsed_id is None:
            return None
        stmt = select(ReimbursementCase).where(ReimbursementCase.id == parsed_id)
        if tenant_id is _UNSET:
            pass
        elif tenant_id is None:
            stmt = stmt.where(ReimbursementCase.tenant_id.is_(None))
        else:
            stmt = stmt.where(ReimbursementCase.tenant_id == tenant_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _case_detail_view(self, case: ReimbursementCase) -> dict[str, Any]:
        events = (
            await self.session.execute(
                select(ReimbursementCaseEvent)
                .where(ReimbursementCaseEvent.case_id == case.id)
                .order_by(ReimbursementCaseEvent.created_at.asc(), ReimbursementCaseEvent.id.asc())
            )
        ).scalars().all()
        compliance = (
            await self.session.execute(
                select(ComplianceResult).where(ComplianceResult.id == case.compliance_result_id)
            )
        ).scalar_one_or_none()
        view = _case_view(case)
        view["compliance_summary"] = _compliance_summary_view(compliance)
        view["events"] = [_event_view(event) for event in events]
        return view

    @staticmethod
    def _validate_status_transition(previous_status: str, new_status: str) -> None:
        if new_status not in REIMBURSEMENT_CASE_STATUSES:
            raise InvalidCaseTransition(f"Unknown reimbursement case status '{new_status}'")
        if previous_status == new_status:
            return
        allowed = ALLOWED_REIMBURSEMENT_TRANSITIONS.get(previous_status, set())
        if new_status not in allowed:
            raise InvalidCaseTransition(
                f"Invalid reimbursement case status transition: {previous_status} -> {new_status}"
            )

    @staticmethod
    def _apply_status_timestamps(case: ReimbursementCase) -> None:
        now = datetime.now(UTC)
        if case.status == "sent" and case.sent_at is None:
            case.sent_at = now
        if case.status in {"accepted", "rejected", "closed"} and case.resolved_at is None:
            case.resolved_at = now


def _start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=UTC)


def _as_date(value: datetime) -> date:
    return value.date()


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _safe_percent(numerator: float, denominator: float) -> float:
    return round(_safe_div(numerator, denominator) * 100, 2)


def _average(values: list[int]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return float(ordered[index])


def _sum_amount(cases: list[ReimbursementCase]) -> float:
    total = Decimal("0")
    for case in cases:
        if case.estimated_amount is not None:
            total += Decimal(str(case.estimated_amount))
    return float(total)


def _counter_items(counter: Counter, key_name: str, count_name: str) -> list[dict[str, Any]]:
    return [
        {key_name: key, count_name: count}
        for key, count in counter.most_common()
    ]


def _counter_amount_items(
    cases: list[ReimbursementCase],
    group_attr: str,
    amount_name: str,
) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    for case in cases:
        totals[str(getattr(case, group_attr))] += _sum_amount([case])
    return [
        {group_attr: key, amount_name: value}
        for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _case_view(case: ReimbursementCase) -> dict[str, Any]:
    return {
        "id": str(case.id),
        "run_id": str(case.run_id),
        "compliance_result_id": str(case.compliance_result_id),
        "tenant_id": case.tenant_id,
        "document_id": case.document_id,
        "treatment_code": case.treatment_code,
        "status": case.status,
        "reason": case.reason,
        "estimated_amount": float(case.estimated_amount) if case.estimated_amount is not None else None,
        "currency": case.currency,
        "sent_at": case.sent_at.isoformat() if case.sent_at else None,
        "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


def _event_view(event: ReimbursementCaseEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "case_id": str(event.case_id),
        "tenant_id": event.tenant_id,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "event_type": event.event_type,
        "note": event.note,
        "actor_id": event.actor_id,
        "metadata": event.event_metadata,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _compliance_summary_view(compliance: ComplianceResult | None) -> dict[str, Any] | None:
    if compliance is None:
        return None
    return {
        "id": str(compliance.id),
        "run_id": str(compliance.run_id),
        "document_id": compliance.document_id,
        "treatment_code": compliance.treatment_code,
        "status": compliance.status,
        "recommended_action": compliance.recommended_action,
        "failed_count": compliance.failed_count,
        "passed_count": compliance.passed_count,
        "insufficient_data_count": compliance.insufficient_data_count,
        "highest_severity": compliance.highest_severity,
        "created_at": compliance.created_at.isoformat() if compliance.created_at else None,
    }
