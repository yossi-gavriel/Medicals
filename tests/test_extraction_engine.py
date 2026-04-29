from __future__ import annotations

from app.services.extraction_engine import (
    ExtractionEngine,
    ExtractionRecord,
    LLMRuleResolver,
    Rule,
    load_specification,
)


def _spec_cataract() -> dict:
    return {
        "version": "1.0",
        "treatments": [
            {
                "treatment_code": "CATARACT_SURGERY",
                "display_name": "Cataract Surgery",
                "rules": [
                    {
                        "field_name": "has_cataract_diagnosis",
                        "type": "boolean",
                        "positive_indicators": ["cataract", "קטרקט"],
                        "negative_indicators": ["no cataract", "ללא קטרקט"],
                        "evidence_required": True,
                        "default_when_missing": False,
                    },
                    {
                        "field_name": "surgery_date",
                        "type": "date",
                        "positive_indicators": ["surgery date", "תאריך ניתוח"],
                        "evidence_required": True,
                    },
                    {
                        "field_name": "operated_eye",
                        "type": "enum",
                        "allowed_values": ["left", "right", "both", "unknown"],
                        "evidence_required": True,
                    },
                    {
                        "field_name": "patient_age",
                        "type": "number",
                        "positive_indicators": ["age", "גיל"],
                    },
                    {
                        "field_name": "summary",
                        "type": "text",
                        "positive_indicators": ["summary", "סיכום"],
                    },
                ],
            }
        ],
    }


def test_valid_spec_creates_stable_output_columns_and_one_row_per_treatment():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = (
        "Surgery date: 10/02/2024. The patient (age 67) underwent left eye cataract removal. "
        "Summary: procedure successful."
    )

    result = engine.run(document_id="doc_123", document_text=text, spec=spec)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert list(row.keys()) == [
        "document_id",
        "treatment_code",
        "has_cataract_diagnosis",
        "surgery_date",
        "operated_eye",
        "patient_age",
        "summary",
    ]
    assert row["document_id"] == "doc_123"
    assert row["treatment_code"] == "CATARACT_SURGERY"


def test_boolean_positive_indicator_is_detected():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Patient diagnosed with cataract. Surgery scheduled."

    result = engine.run(document_id="d1", document_text=text, spec=spec)

    assert result.rows[0]["has_cataract_diagnosis"] is True
    audit = _audit_for(result, "has_cataract_diagnosis")
    assert audit.value is True
    assert audit.confidence > 0
    assert any("cataract" in e.lower() for e in audit.evidence)


def test_boolean_negative_indicator_overrides_positive():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Examination shows no cataract in either eye."

    result = engine.run(document_id="d2", document_text=text, spec=spec)

    assert result.rows[0]["has_cataract_diagnosis"] is False
    audit = _audit_for(result, "has_cataract_diagnosis")
    assert audit.reason.startswith("Matched negative indicator")


def test_hebrew_indicators_work_for_boolean():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "המטופל אובחן עם קטרקט בעין ימין."

    result = engine.run(document_id="d3", document_text=text, spec=spec)

    assert result.rows[0]["has_cataract_diagnosis"] is True
    audit = _audit_for(result, "has_cataract_diagnosis")
    assert any("קטרקט" in e for e in audit.evidence)


def test_hebrew_negative_indicator_overrides_positive():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "ללא קטרקט בבדיקה הנוכחית."

    result = engine.run(document_id="d4", document_text=text, spec=spec)

    assert result.rows[0]["has_cataract_diagnosis"] is False


def test_enum_value_is_normalized_and_validated():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Surgery performed on the LEFT eye."

    result = engine.run(document_id="d5", document_text=text, spec=spec)

    assert result.rows[0]["operated_eye"] == "left"


def test_enum_returns_null_when_no_allowed_value_present():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Patient was admitted yesterday."

    result = engine.run(document_id="d6", document_text=text, spec=spec)

    assert result.rows[0]["operated_eye"] is None


def test_date_value_is_normalized_to_iso():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Surgery date 10/02/2024 — operative report follows."

    result = engine.run(document_id="d7", document_text=text, spec=spec)

    assert result.rows[0]["surgery_date"] == "2024-02-10"


def test_date_value_handles_iso_format_in_text():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Surgery date is 2024-02-10."

    result = engine.run(document_id="d8", document_text=text, spec=spec)

    assert result.rows[0]["surgery_date"] == "2024-02-10"


def test_number_value_extracted_from_indicator_sentence():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Patient age 72. Procedure: cataract surgery."

    result = engine.run(document_id="d9", document_text=text, spec=spec)

    assert result.rows[0]["patient_age"] == 72


def test_text_value_returns_indicator_sentence():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Summary: procedure was uncomplicated."

    result = engine.run(document_id="d10", document_text=text, spec=spec)

    assert "uncomplicated" in result.rows[0]["summary"].lower()


def test_missing_value_returns_configured_default_for_boolean():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Patient came for follow-up."

    result = engine.run(document_id="d11", document_text=text, spec=spec)

    # default_when_missing is False for has_cataract_diagnosis
    assert result.rows[0]["has_cataract_diagnosis"] is False
    # operated_eye has no default — should be null
    assert result.rows[0]["operated_eye"] is None
    # patient_age has no default — should be null
    assert result.rows[0]["patient_age"] is None


def test_missing_value_returns_null_when_no_default_set():
    payload = _spec_cataract()
    # Remove the configured default on the boolean rule.
    payload["treatments"][0]["rules"][0].pop("default_when_missing")
    spec = load_specification(payload)
    engine = ExtractionEngine()

    result = engine.run(document_id="d12", document_text="No relevant content.", spec=spec)

    assert result.rows[0]["has_cataract_diagnosis"] is None


def test_audit_contains_evidence_confidence_reason_separately():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine()
    text = "Patient diagnosed with cataract. Surgery date: 2024-02-10. Left eye operated."

    result = engine.run(document_id="d13", document_text=text, spec=spec)

    audit_fields = {entry.field_name for entry in result.audit}
    assert audit_fields == {
        "has_cataract_diagnosis",
        "surgery_date",
        "operated_eye",
        "patient_age",
        "summary",
    }
    diag_audit = _audit_for(result, "has_cataract_diagnosis")
    # Audit carries evidence/confidence/reason; the flat row only carries the value.
    assert diag_audit.evidence
    assert isinstance(diag_audit.confidence, float)
    assert diag_audit.reason
    assert "evidence" not in result.rows[0]
    assert "confidence" not in result.rows[0]
    assert "reason" not in result.rows[0]


def test_engine_does_not_invent_fields_not_defined_in_spec():
    payload = _spec_cataract()
    # Strip the spec down to a single rule so we can assert exact columns.
    payload["treatments"][0]["rules"] = [payload["treatments"][0]["rules"][0]]
    spec = load_specification(payload)
    engine = ExtractionEngine()
    text = "Surgery date 10/02/2024. The patient underwent LEFT eye cataract removal."

    result = engine.run(document_id="d14", document_text=text, spec=spec)

    assert set(result.rows[0].keys()) == {
        "document_id",
        "treatment_code",
        "has_cataract_diagnosis",
    }
    assert {entry.field_name for entry in result.audit} == {"has_cataract_diagnosis"}


def test_multiple_treatments_produce_one_row_each():
    payload = _spec_cataract()
    payload["treatments"].append(
        {
            "treatment_code": "GLAUCOMA_CHECK",
            "rules": [
                {
                    "field_name": "iop_high",
                    "type": "boolean",
                    "positive_indicators": ["intraocular pressure elevated"],
                }
            ],
        }
    )
    spec = load_specification(payload)
    engine = ExtractionEngine()
    text = "intraocular pressure elevated; cataract present. Surgery date 10/02/2024. Left eye."

    result = engine.run(document_id="d15", document_text=text, spec=spec)

    treatment_codes = [row["treatment_code"] for row in result.rows]
    assert treatment_codes == ["CATARACT_SURGERY", "GLAUCOMA_CHECK"]
    glaucoma_row = next(r for r in result.rows if r["treatment_code"] == "GLAUCOMA_CHECK")
    assert glaucoma_row["iop_high"] is True


class _StubLLMResolver(LLMRuleResolver):
    def __init__(self, *, value, evidence=None, confidence=0.7, reason="stub"):
        self.value = value
        self.evidence = list(evidence) if evidence is not None else ["stub-evidence"]
        self.confidence = confidence
        self.reason = reason
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return True

    def resolve(self, *, rule: Rule, sentences):
        self.calls.append(rule.field_name)
        return ExtractionRecord(
            value=self.value,
            confidence=self.confidence,
            evidence=self.evidence,
            reason=self.reason,
        )


def test_llm_resolver_is_only_called_when_deterministic_path_misses():
    payload = _spec_cataract()
    spec = load_specification(payload)
    text = (
        "Surgery date 10/02/2024. The patient (age 67) underwent LEFT eye cataract removal. "
        "Summary: procedure successful."
    )
    llm = _StubLLMResolver(value="right", evidence=["stub"], confidence=0.5)

    engine = ExtractionEngine(llm_resolver=llm)
    result = engine.run(document_id="d16", document_text=text, spec=spec)

    # Every rule has deterministic evidence in this text, so LLM must not be called.
    assert llm.calls == []
    assert result.rows[0]["operated_eye"] == "left"


def test_llm_resolver_normalizes_enum_values_returned_by_llm():
    payload = _spec_cataract()
    # Drop hints so the deterministic enum path cannot match.
    spec = load_specification(payload)
    text = "Patient came for follow-up. Surgery date 10/02/2024."
    llm = _StubLLMResolver(value="LEFT", evidence=["from LLM: left eye"], confidence=0.8)

    engine = ExtractionEngine(llm_resolver=llm)
    result = engine.run(document_id="d17", document_text=text, spec=spec)

    assert "operated_eye" in llm.calls
    assert result.rows[0]["operated_eye"] == "left"


def test_llm_resolver_rejects_enum_value_outside_allowed_values():
    payload = _spec_cataract()
    spec = load_specification(payload)
    text = "Patient came for follow-up."
    llm = _StubLLMResolver(value="middle", evidence=["LLM said middle"], confidence=0.6)

    engine = ExtractionEngine(llm_resolver=llm)
    result = engine.run(document_id="d18", document_text=text, spec=spec)

    assert result.rows[0]["operated_eye"] is None
    audit = _audit_for(result, "operated_eye")
    assert audit.error is not None
    assert audit.error["code"] == "enum_value_invalid"


def test_evidence_required_blocks_llm_value_without_evidence():
    payload = _spec_cataract()
    spec = load_specification(payload)
    text = "Patient came for follow-up."
    llm = _StubLLMResolver(value="left", evidence=[], confidence=0.4)

    engine = ExtractionEngine(llm_resolver=llm)
    result = engine.run(document_id="d19", document_text=text, spec=spec)

    assert result.rows[0]["operated_eye"] is None
    audit = _audit_for(result, "operated_eye")
    assert "evidence_required" in audit.reason


def test_pii_masking_runs_when_enabled_before_extraction():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine(mask_pii=True)
    text = "Patient ID 123456789 had cataract surgery on 10/02/2024 — left eye."

    result = engine.run(document_id="d20", document_text=text, spec=spec)

    assert result.masked is True
    assert result.pii_masked_count >= 1
    diag_audit = _audit_for(result, "has_cataract_diagnosis")
    assert all("123456789" not in e for e in diag_audit.evidence)


def _audit_for(result, field_name):
    return next(entry for entry in result.audit if entry.field_name == field_name)


def _spec_with_planning() -> dict:
    return {
        "version": "1.0",
        "treatments": [
            {
                "treatment_code": "CATARACT_SURGERY",
                "rules": [
                    {
                        "field_name": "performed",
                        "type": "boolean",
                        "positive_indicators": ["cataract surgery", "ניתוח קטרקט"],
                        "planning_indicators": [
                            "planned for cataract surgery",
                            "scheduled for cataract surgery",
                            "מתוכנן לניתוח קטרקט",
                        ],
                        "historical_indicators": [
                            "history of cataract surgery",
                            "past cataract surgery",
                            "עבר ניתוח קטרקט",
                        ],
                        "default_when_missing": False,
                    }
                ],
            }
        ],
    }


def test_planned_mention_does_not_count_as_performed_by_default():
    spec = load_specification(_spec_with_planning())
    engine = ExtractionEngine()
    text = "Patient is planned for cataract surgery next week."

    result = engine.run(document_id="d_plan", document_text=text, spec=spec)

    assert result.rows[0]["performed"] is False
    audit = _audit_for(result, "performed")
    assert "planning indicator" in audit.reason


def test_historical_mention_does_not_count_as_performed_by_default():
    spec = load_specification(_spec_with_planning())
    engine = ExtractionEngine()
    text = "History of cataract surgery in 2018."

    result = engine.run(document_id="d_hist", document_text=text, spec=spec)

    assert result.rows[0]["performed"] is False
    audit = _audit_for(result, "performed")
    assert "historical indicator" in audit.reason


def test_planned_mention_counts_when_explicitly_allowed():
    payload = _spec_with_planning()
    payload["treatments"][0]["rules"][0]["allow_planned_mentions"] = True
    spec = load_specification(payload)
    engine = ExtractionEngine()
    text = "Patient is planned for cataract surgery next week."

    result = engine.run(document_id="d_plan_allowed", document_text=text, spec=spec)

    assert result.rows[0]["performed"] is True


def test_negative_indicator_still_wins_over_planning():
    spec = load_specification(_spec_with_planning())
    engine = ExtractionEngine()
    payload = _spec_with_planning()
    payload["treatments"][0]["rules"][0]["negative_indicators"] = ["no cataract surgery"]
    spec = load_specification(payload)
    text = "No cataract surgery; planned for cataract surgery next week."

    result = engine.run(document_id="d_neg_over_plan", document_text=text, spec=spec)

    assert result.rows[0]["performed"] is False
    audit = _audit_for(result, "performed")
    assert audit.reason.startswith("Matched negative indicator")


def test_hebrew_planning_indicator_suppresses_positive():
    spec = load_specification(_spec_with_planning())
    engine = ExtractionEngine()
    text = "מתוכנן לניתוח קטרקט בשבוע הבא."

    result = engine.run(document_id="d_plan_he", document_text=text, spec=spec)

    assert result.rows[0]["performed"] is False


def test_llm_boolean_value_must_be_a_boolean():
    spec = load_specification(_spec_cataract())
    engine = ExtractionEngine(llm_resolver=_StubLLMResolver(value="maybe", confidence=0.6))
    # Strip indicators on the boolean rule so the LLM path is reached.
    payload = _spec_cataract()
    payload["treatments"][0]["rules"][0]["positive_indicators"] = []
    payload["treatments"][0]["rules"][0]["negative_indicators"] = []
    spec = load_specification(payload)
    text = "Patient came for follow-up. Surgery date 10/02/2024. Left eye."

    result = engine.run(document_id="d_bool_invalid", document_text=text, spec=spec)

    assert result.rows[0]["has_cataract_diagnosis"] is False  # default_when_missing=False
    audit = _audit_for(result, "has_cataract_diagnosis")
    assert audit.error is not None
    assert audit.error["code"] == "boolean_value_invalid"


def test_llm_unknown_keys_do_not_pollute_the_row():
    """LLM Protocol forbids inventing new fields. Even if a stub returned extra
    fields on its record, the engine writes ONLY the spec-declared columns to the row.
    """
    payload = _spec_cataract()
    spec = load_specification(payload)
    text = "Patient came for follow-up."

    class _OverreachingLLM:
        def is_available(self):
            return True

        def resolve(self, *, rule, sentences):
            return ExtractionRecord(
                value="left",
                confidence=0.8,
                evidence=["From LLM: left eye"],
                reason="stub",
            )

    engine = ExtractionEngine(llm_resolver=_OverreachingLLM())
    result = engine.run(document_id="d_overreach", document_text=text, spec=spec)

    declared_columns = {
        "document_id",
        "treatment_code",
        "has_cataract_diagnosis",
        "surgery_date",
        "operated_eye",
        "patient_age",
        "summary",
    }
    assert set(result.rows[0].keys()) == declared_columns
