from __future__ import annotations

from app.services.extraction_engine import compute_spec_hash, load_specification


def _spec_v1() -> dict:
    return {
        "version": "1.0",
        "treatments": [
            {
                "treatment_code": "CATARACT_SURGERY",
                "rules": [
                    {
                        "field_name": "has_cataract_diagnosis",
                        "type": "boolean",
                        "positive_indicators": ["cataract", "קטרקט"],
                        "negative_indicators": ["no cataract"],
                        "default_when_missing": False,
                    },
                    {"field_name": "surgery_date", "type": "date"},
                    {
                        "field_name": "operated_eye",
                        "type": "enum",
                        "allowed_values": ["left", "right", "both", "unknown"],
                    },
                ],
            }
        ],
    }


def _spec_v1_reordered_keys() -> dict:
    """Same logical spec as _spec_v1, but with keys in a different order."""
    return {
        "treatments": [
            {
                "rules": [
                    {
                        "default_when_missing": False,
                        "negative_indicators": ["no cataract"],
                        "positive_indicators": ["cataract", "קטרקט"],
                        "type": "boolean",
                        "field_name": "has_cataract_diagnosis",
                    },
                    {"type": "date", "field_name": "surgery_date"},
                    {
                        "allowed_values": ["left", "right", "both", "unknown"],
                        "type": "enum",
                        "field_name": "operated_eye",
                    },
                ],
                "treatment_code": "CATARACT_SURGERY",
            }
        ],
        "version": "1.0",
    }


def test_spec_hash_is_stable_for_equivalent_specs_with_different_key_order():
    spec_a = load_specification(_spec_v1())
    spec_b = load_specification(_spec_v1_reordered_keys())

    hash_a = compute_spec_hash(spec_a)
    hash_b = compute_spec_hash(spec_b)

    assert hash_a == hash_b
    assert len(hash_a) == 64  # sha256 hex


def test_spec_hash_changes_when_a_rule_changes():
    spec_a = load_specification(_spec_v1())
    payload = _spec_v1()
    payload["treatments"][0]["rules"][0]["positive_indicators"] = ["cataract"]
    spec_b = load_specification(payload)

    assert compute_spec_hash(spec_a) != compute_spec_hash(spec_b)


def test_spec_hash_changes_when_a_treatment_code_changes():
    spec_a = load_specification(_spec_v1())
    payload = _spec_v1()
    payload["treatments"][0]["treatment_code"] = "DIFFERENT_TREATMENT"
    spec_b = load_specification(payload)

    assert compute_spec_hash(spec_a) != compute_spec_hash(spec_b)


def test_spec_hash_is_unaffected_by_indicator_whitespace_padding():
    """Spec validators trim indicator whitespace, so the hash should be the
    same regardless of caller-side padding."""
    spec_a = load_specification(_spec_v1())
    payload = _spec_v1()
    payload["treatments"][0]["rules"][0]["positive_indicators"] = ["  cataract  ", "קטרקט"]
    spec_b = load_specification(payload)

    assert compute_spec_hash(spec_a) == compute_spec_hash(spec_b)
