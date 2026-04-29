from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from app.services.extraction_engine.engine import ExtractionAuditEntry, ExtractionResult
from app.services.extraction_engine.spec import (
    ComplianceRule,
    ComplianceVerdict,
    RecommendedAction,
    Severity,
    Specification,
)

RULE_STATUS_PASSED = "passed"
RULE_STATUS_FAILED = "failed"
RULE_STATUS_INSUFFICIENT_DATA = "insufficient_data"
RULE_STATUS_MANUAL_REVIEW = "manual_review"

ACTION_PRIORITY: dict[RecommendedAction, int] = {
    "none": 0,
    "request_clarification": 1,
    "manual_review": 2,
    "reject_case": 3,
    "request_reimbursement": 4,
}
SEVERITY_PRIORITY: dict[Severity, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _severity_rank(severity: Severity) -> int:
    return SEVERITY_PRIORITY[severity]


@dataclass(frozen=True)
class ComplianceRuleEvaluation:
    rule_id: str
    description: str
    field: str
    operator: str
    expected: Any
    actual: Any
    status: str
    severity: Severity | None
    reason: str
    recommended_action: RecommendedAction
    evidence: list[str] = dc_field(default_factory=list)


@dataclass(frozen=True)
class ComplianceEvaluation:
    document_id: str
    treatment_code: str
    status: ComplianceVerdict
    recommended_action: RecommendedAction
    failed_rules: list[ComplianceRuleEvaluation] = dc_field(default_factory=list)
    passed_rules: list[ComplianceRuleEvaluation] = dc_field(default_factory=list)
    insufficient_data_rules: list[ComplianceRuleEvaluation] = dc_field(default_factory=list)
    manual_review_rules: list[ComplianceRuleEvaluation] = dc_field(default_factory=list)

    @property
    def highest_severity(self) -> Severity | None:
        candidates: list[Severity] = []
        for rule in [*self.failed_rules, *self.insufficient_data_rules, *self.manual_review_rules]:
            if rule.severity is not None:
                candidates.append(rule.severity)
        if not candidates:
            return None
        return max(candidates, key=_severity_rank)


class ComplianceEvaluator:
    """Evaluates extracted treatment-level values against JSON-defined rules.

    The evaluator never derives new fields. Every comparison reads only the
    treatment row fields produced by the extraction engine and already validated
    by the specification schema.
    """

    def evaluate(
        self,
        *,
        extraction_result: ExtractionResult,
        spec: Specification,
    ) -> list[ComplianceEvaluation]:
        row_by_treatment = {
            str(row.get("treatment_code")): row for row in extraction_result.rows
        }
        audit_index = self._audit_index(extraction_result.audit)
        evaluations: list[ComplianceEvaluation] = []

        for treatment in spec.treatments:
            if not treatment.compliance_rules:
                continue
            row = row_by_treatment.get(treatment.treatment_code, {})
            evaluations.append(
                self._evaluate_treatment(
                    document_id=extraction_result.document_id,
                    treatment_code=treatment.treatment_code,
                    row=row,
                    compliance_rules=treatment.compliance_rules,
                    audit_index=audit_index,
                )
            )
        return evaluations

    def _evaluate_treatment(
        self,
        *,
        document_id: str,
        treatment_code: str,
        row: dict[str, Any],
        compliance_rules: list[ComplianceRule],
        audit_index: dict[tuple[str, str], list[str]],
    ) -> ComplianceEvaluation:
        failed: list[ComplianceRuleEvaluation] = []
        passed: list[ComplianceRuleEvaluation] = []
        insufficient: list[ComplianceRuleEvaluation] = []
        manual_review: list[ComplianceRuleEvaluation] = []

        for rule in compliance_rules:
            evaluation = self._evaluate_rule(
                treatment_code=treatment_code,
                row=row,
                rule=rule,
                evidence=audit_index.get((treatment_code, rule.field), []),
            )
            if evaluation.status == RULE_STATUS_PASSED:
                passed.append(evaluation)
            elif evaluation.status == RULE_STATUS_FAILED:
                failed.append(evaluation)
            elif evaluation.status == RULE_STATUS_INSUFFICIENT_DATA:
                insufficient.append(evaluation)
            else:
                manual_review.append(evaluation)

        verdict = self._overall_status(failed, insufficient, manual_review)
        action = self._overall_action(failed, insufficient, manual_review, verdict)
        return ComplianceEvaluation(
            document_id=document_id,
            treatment_code=treatment_code,
            status=verdict,
            recommended_action=action,
            failed_rules=failed,
            passed_rules=passed,
            insufficient_data_rules=insufficient,
            manual_review_rules=manual_review,
        )

    def _evaluate_rule(
        self,
        *,
        treatment_code: str,
        row: dict[str, Any],
        rule: ComplianceRule,
        evidence: list[str],
    ) -> ComplianceRuleEvaluation:
        actual = row.get(rule.field)
        expected = rule.value
        missing = actual is None

        if missing and rule.operator not in {"exists", "missing"}:
            outcome = rule.on_missing
            if outcome is not None:
                return ComplianceRuleEvaluation(
                    rule_id=rule.rule_id,
                    description=rule.description,
                    field=rule.field,
                    operator=rule.operator,
                    expected=expected,
                    actual=actual,
                    status=self._rule_status_from_verdict(outcome.status),
                    severity=rule.severity,
                    reason=outcome.reason or f"Field '{rule.field}' is missing",
                    recommended_action=outcome.recommended_action,
                    evidence=evidence,
                )
            return ComplianceRuleEvaluation(
                rule_id=rule.rule_id,
                description=rule.description,
                field=rule.field,
                operator=rule.operator,
                expected=expected,
                actual=actual,
                status=RULE_STATUS_INSUFFICIENT_DATA,
                severity=rule.severity,
                reason=f"Required field '{rule.field}' is missing",
                recommended_action="request_clarification",
                evidence=evidence,
            )

        try:
            passed = self._compare(actual, rule)
        except (TypeError, ValueError):
            return ComplianceRuleEvaluation(
                rule_id=rule.rule_id,
                description=rule.description,
                field=rule.field,
                operator=rule.operator,
                expected=expected,
                actual=actual,
                status=RULE_STATUS_MANUAL_REVIEW,
                severity=rule.severity,
                reason=(
                    f"Compliance rule '{rule.rule_id}' could not be evaluated for treatment "
                    f"'{treatment_code}'"
                ),
                recommended_action="manual_review",
                evidence=evidence,
            )

        if passed:
            return ComplianceRuleEvaluation(
                rule_id=rule.rule_id,
                description=rule.description,
                field=rule.field,
                operator=rule.operator,
                expected=expected,
                actual=actual,
                status=RULE_STATUS_PASSED,
                severity=rule.severity,
                reason="Rule passed",
                recommended_action="none",
                evidence=evidence,
            )

        return ComplianceRuleEvaluation(
            rule_id=rule.rule_id,
            description=rule.description,
            field=rule.field,
            operator=rule.operator,
            expected=expected,
            actual=actual,
            status=RULE_STATUS_FAILED,
            severity=rule.severity,
            reason=rule.on_fail.reason or f"Rule '{rule.rule_id}' failed",
            recommended_action=rule.on_fail.recommended_action,
            evidence=evidence,
        )

    @staticmethod
    def _compare(actual: Any, rule: ComplianceRule) -> bool:
        expected = rule.value
        if rule.operator == "equals":
            return actual == expected
        if rule.operator == "not_equals":
            return actual != expected
        if rule.operator == "in":
            return actual in expected
        if rule.operator == "not_in":
            return actual not in expected
        if rule.operator == "exists":
            return actual is not None
        if rule.operator == "missing":
            return actual is None

        if isinstance(actual, bool) or isinstance(expected, bool):
            raise TypeError("boolean values are not valid for ordered comparison")
        if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
            raise TypeError("ordered comparison requires numeric values")

        if rule.operator == "gt":
            return actual > expected
        if rule.operator == "gte":
            return actual >= expected
        if rule.operator == "lt":
            return actual < expected
        if rule.operator == "lte":
            return actual <= expected
        raise ValueError(f"unsupported operator: {rule.operator}")

    @staticmethod
    def _rule_status_from_verdict(status: ComplianceVerdict) -> str:
        if status == "compliant":
            return RULE_STATUS_PASSED
        if status == "non_compliant":
            return RULE_STATUS_FAILED
        if status == "insufficient_data":
            return RULE_STATUS_INSUFFICIENT_DATA
        return RULE_STATUS_MANUAL_REVIEW

    @staticmethod
    def _overall_status(
        failed: list[ComplianceRuleEvaluation],
        insufficient: list[ComplianceRuleEvaluation],
        manual_review: list[ComplianceRuleEvaluation],
    ) -> ComplianceVerdict:
        if any(rule.recommended_action == "request_reimbursement" for rule in failed):
            return "non_compliant"
        if failed:
            return "non_compliant"
        if manual_review:
            return "manual_review"
        if insufficient:
            return "insufficient_data"
        return "compliant"

    @staticmethod
    def _overall_action(
        failed: list[ComplianceRuleEvaluation],
        insufficient: list[ComplianceRuleEvaluation],
        manual_review: list[ComplianceRuleEvaluation],
        verdict: ComplianceVerdict,
    ) -> RecommendedAction:
        rules = [*failed, *insufficient, *manual_review]
        if rules:
            return max((rule.recommended_action for rule in rules), key=lambda item: ACTION_PRIORITY[item])
        if verdict == "manual_review":
            return "manual_review"
        if verdict == "insufficient_data":
            return "request_clarification"
        return "none"

    @staticmethod
    def _audit_index(audit_entries: list[ExtractionAuditEntry]) -> dict[tuple[str, str], list[str]]:
        index: dict[tuple[str, str], list[str]] = {}
        for entry in audit_entries:
            key = (entry.treatment_code, entry.field_name)
            index.setdefault(key, [])
            for evidence in entry.evidence:
                if evidence not in index[key]:
                    index[key].append(evidence)
        return index


__all__ = [
    "ComplianceEvaluation",
    "ComplianceEvaluator",
    "ComplianceRuleEvaluation",
    "RULE_STATUS_FAILED",
    "RULE_STATUS_INSUFFICIENT_DATA",
    "RULE_STATUS_MANUAL_REVIEW",
    "RULE_STATUS_PASSED",
]
