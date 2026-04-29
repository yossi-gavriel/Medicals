from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.extraction_engine import Specification, load_specification


def _base_spec() -> dict:
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
                        "positive_indicators": ["cataract"],
                        "negative_indicators": ["no cataract"],
                    }
                ],
            }
        ],
    }


def test_valid_spec_loads():
    spec = load_specification(_base_spec())
    assert isinstance(spec, Specification)
    assert spec.treatments[0].treatment_code == "CATARACT_SURGERY"
    assert spec.treatments[0].rules[0].field_name == "has_cataract_diagnosis"


def test_spec_rejects_duplicate_treatment_code():
    payload = _base_spec()
    payload["treatments"].append(payload["treatments"][0])
    with pytest.raises(ValidationError) as excinfo:
        load_specification(payload)
    assert "Duplicate treatment_code" in str(excinfo.value)


def test_spec_rejects_duplicate_field_name_in_same_treatment():
    payload = _base_spec()
    payload["treatments"][0]["rules"].append(payload["treatments"][0]["rules"][0])
    with pytest.raises(ValidationError) as excinfo:
        load_specification(payload)
    assert "Duplicate field_name" in str(excinfo.value)


def test_spec_rejects_enum_without_allowed_values():
    payload = _base_spec()
    payload["treatments"][0]["rules"].append(
        {
            "field_name": "operated_eye",
            "type": "enum",
        }
    )
    with pytest.raises(ValidationError) as excinfo:
        load_specification(payload)
    assert "allowed_values" in str(excinfo.value)


def test_spec_rejects_enum_with_empty_allowed_values_entry():
    payload = _base_spec()
    payload["treatments"][0]["rules"].append(
        {
            "field_name": "operated_eye",
            "type": "enum",
            "allowed_values": ["left", "  "],
        }
    )
    with pytest.raises(ValidationError):
        load_specification(payload)


def test_spec_rejects_non_enum_with_allowed_values():
    payload = _base_spec()
    payload["treatments"][0]["rules"][0]["allowed_values"] = ["left", "right"]
    with pytest.raises(ValidationError):
        load_specification(payload)


def test_spec_rejects_invalid_default_for_boolean():
    payload = _base_spec()
    payload["treatments"][0]["rules"][0]["default_when_missing"] = "false"
    with pytest.raises(ValidationError):
        load_specification(payload)


def test_spec_rejects_default_outside_enum_allowed_values():
    payload = _base_spec()
    payload["treatments"][0]["rules"].append(
        {
            "field_name": "operated_eye",
            "type": "enum",
            "allowed_values": ["left", "right"],
            "default_when_missing": "both",
        }
    )
    with pytest.raises(ValidationError):
        load_specification(payload)


def test_spec_rejects_unknown_rule_type():
    payload = _base_spec()
    payload["treatments"][0]["rules"][0]["type"] = "blob"
    with pytest.raises(ValidationError):
        load_specification(payload)


def test_spec_rejects_extra_fields():
    payload = _base_spec()
    payload["treatments"][0]["rules"][0]["unexpected"] = True
    with pytest.raises(ValidationError):
        load_specification(payload)


def test_spec_rejects_empty_treatments_list():
    with pytest.raises(ValidationError):
        load_specification({"version": "1.0", "treatments": []})


def test_spec_rejects_treatment_without_rules():
    payload = _base_spec()
    payload["treatments"][0]["rules"] = []
    with pytest.raises(ValidationError):
        load_specification(payload)
