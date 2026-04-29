from __future__ import annotations

import pytest

from app.services.compliance import ComplianceEvaluator
from app.services.extraction_engine import ExtractionAuditEntry, ExtractionResult, load_specification


def _spec(operator: str, value=None, *, field_type: str = "number", on_fail=None) -> dict:
    rule = {
        "rule_id": f"rule_{operator}",
        "description": f"Test {operator}",
        "field": "value",
        "operator": operator,
        "severity": "high",
        "on_fail": on_fail
        or {
            "status": "non_compliant",
            "reason": "rule failed",
            "recommended_action": "request_reimbursement",
        },
    }
    if operator not in {"exists", "missing"}:
        rule["value"] = value
    return {
        "version": "1.0",
        "treatments": [
            {
                "treatment_code": "TREATMENT_A",
                "rules": [{"field_name": "value", "type": field_type}],
                "compliance_rules": [rule],
            }
        ],
    }


def _evaluate(spec_payload: dict, actual):
    spec = load_specification(spec_payload)
    result = ExtractionResult(
        document_id="doc_1",
        spec_version="1.0",
        rows=[{"document_id": "doc_1", "treatment_code": "TREATMENT_A", "value": actual}],
        audit=[
            ExtractionAuditEntry(
                document_id="doc_1",
                treatment_code="TREATMENT_A",
                field_name="value",
                value=actual,
                confidence=0.9,
                evidence=["source sentence"],
                reason="matched",
            )
        ],
    )
    return ComplianceEvaluator().evaluate(extraction_result=result, spec=spec)[0]


def test_compliant_when_all_compliance_rules_pass() -> None:
    result = _evaluate(_spec("gte", 24), 30)

    assert result.status == "compliant"
    assert result.recommended_action == "none"
    assert len(result.passed_rules) == 1


def test_non_compliant_when_required_rule_fails_with_expected_actual_and_evidence() -> None:
    result = _evaluate(_spec("gte", 24), 6)

    assert result.status == "non_compliant"
    assert result.recommended_action == "request_reimbursement"
    failed = result.failed_rules[0]
    assert failed.expected == 24
    assert failed.actual == 6
    assert failed.evidence == ["source sentence"]


def test_insufficient_data_when_required_field_missing() -> None:
    result = _evaluate(_spec("equals", "full_hospitalization", field_type="text"), None)

    assert result.status == "insufficient_data"
    assert result.insufficient_data_rules[0].actual is None
    assert result.insufficient_data_rules[0].recommended_action == "request_clarification"


def test_manual_review_for_ambiguous_ordered_comparison() -> None:
    result = _evaluate(_spec("gt", 5, field_type="text"), "not-a-number")

    assert result.status == "manual_review"
    assert result.manual_review_rules[0].recommended_action == "manual_review"


@pytest.mark.parametrize(
    ("operator", "expected", "actual", "passes"),
    [
        ("equals", "full", "full", True),
        ("equals", "full", "day", False),
        ("not_equals", "full", "day", True),
        ("not_equals", "full", "full", False),
        ("in", ["full", "day"], "day", True),
        ("in", ["full", "day"], "outpatient", False),
        ("not_in", ["full", "day"], "outpatient", True),
        ("not_in", ["full", "day"], "day", False),
        ("gt", 10, 11, True),
        ("gt", 10, 10, False),
        ("gte", 10, 10, True),
        ("lt", 10, 9, True),
        ("lt", 10, 10, False),
        ("lte", 10, 10, True),
        ("exists", None, "present", True),
        ("exists", None, None, False),
        ("missing", None, None, True),
        ("missing", None, "present", False),
    ],
)
def test_v1_operators(operator: str, expected, actual, passes: bool) -> None:
    field_type = "number" if operator in {"gt", "gte", "lt", "lte"} else "text"
    result = _evaluate(_spec(operator, expected, field_type=field_type), actual)

    if passes:
        assert result.status == "compliant"
    else:
        assert result.status in {"non_compliant", "insufficient_data"}


def test_compliance_rule_referencing_undefined_field_is_rejected() -> None:
    payload = _spec("equals", True)
    payload["treatments"][0]["compliance_rules"][0]["field"] = "missing_field"

    with pytest.raises(ValueError, match="references undefined field"):
        load_specification(payload)
