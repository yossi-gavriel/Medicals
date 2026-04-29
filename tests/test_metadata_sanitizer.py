from __future__ import annotations

import pytest

from app.services.medical_classifier.metadata_sanitizer import (
    AUDIT_METADATA_ALLOWLIST,
    _MAX_VALUE_LENGTH,
    sanitize_metadata_for_audit,
)

# ---------------------------------------------------------------------------
# Null / empty input
# ---------------------------------------------------------------------------


def test_none_returns_empty_dict() -> None:
    assert sanitize_metadata_for_audit(None) == {}


def test_empty_dict_returns_empty_dict() -> None:
    assert sanitize_metadata_for_audit({}) == {}


# ---------------------------------------------------------------------------
# Allowlisted keys pass through (one per key in the contract)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "document_id",
        "source_system",
        "source_table",
        "batch_id",
        "run_id",
        "connector_version",
        "environment",
        "customer_reference",
        "external_trace_id",
    ],
)
def test_allowlisted_string_key_passes_through(key: str) -> None:
    result = sanitize_metadata_for_audit({key: "value"})
    assert result == {key: "value"}


def test_allowlisted_int_key_passes_through() -> None:
    result = sanitize_metadata_for_audit({"document_id": 42})
    assert result == {"document_id": 42}


def test_allowlisted_float_key_passes_through() -> None:
    result = sanitize_metadata_for_audit({"document_id": 1.5})
    assert result == {"document_id": 1.5}


def test_allowlisted_bool_key_passes_through() -> None:
    result = sanitize_metadata_for_audit({"environment": True})
    assert result == {"environment": True}


def test_all_allowlisted_keys_together() -> None:
    metadata = {key: f"v_{key}" for key in AUDIT_METADATA_ALLOWLIST}
    result = sanitize_metadata_for_audit(metadata)
    assert set(result.keys()) == AUDIT_METADATA_ALLOWLIST


# ---------------------------------------------------------------------------
# Removed / never-allowed keys are dropped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        # keys removed from the old allowlist — must never appear in audit storage
        "source",
        "doc_category",
        "workflow",
        "schema_version",
        "processing_mode",
        # tenant identity must come from auth context, not client-supplied metadata
        "tenant",
    ],
)
def test_removed_key_is_dropped(key: str) -> None:
    result = sanitize_metadata_for_audit({key: "some_value"})
    assert key not in result
    assert result == {}


# ---------------------------------------------------------------------------
# PHI / suspicious keys are dropped
# ---------------------------------------------------------------------------


def test_unknown_phi_key_is_dropped() -> None:
    result = sanitize_metadata_for_audit(
        {"patient_name": "John Doe", "source_system": "connector"}
    )
    assert "patient_name" not in result
    assert result == {"source_system": "connector"}


def test_all_unknown_keys_returns_empty_dict() -> None:
    result = sanitize_metadata_for_audit(
        {"phi_field": "secret", "diagnosis": "condition X"}
    )
    assert result == {}


def test_cleaned_full_key_is_dropped() -> None:
    result = sanitize_metadata_for_audit(
        {"cleaned_full": "very sensitive patient text", "source_system": "ok"}
    )
    assert "cleaned_full" not in result
    assert result == {"source_system": "ok"}


# ---------------------------------------------------------------------------
# Nested structures are dropped (can contain PHI)
# ---------------------------------------------------------------------------


def test_nested_dict_value_is_dropped() -> None:
    result = sanitize_metadata_for_audit({"source_system": {"nested": "phi"}})
    assert result == {}


def test_list_value_is_dropped() -> None:
    result = sanitize_metadata_for_audit({"source_system": ["item1", "item2"]})
    assert result == {}


def test_none_value_is_dropped() -> None:
    result = sanitize_metadata_for_audit({"source_system": None})
    assert result == {}


# ---------------------------------------------------------------------------
# String truncation
# ---------------------------------------------------------------------------


def test_string_value_truncated_to_max_length() -> None:
    long_value = "x" * (_MAX_VALUE_LENGTH + 100)
    result = sanitize_metadata_for_audit({"source_system": long_value})
    assert result["source_system"] == "x" * _MAX_VALUE_LENGTH


def test_string_value_exactly_at_max_length_not_truncated() -> None:
    exact_value = "a" * _MAX_VALUE_LENGTH
    result = sanitize_metadata_for_audit({"source_system": exact_value})
    assert result["source_system"] == exact_value


# ---------------------------------------------------------------------------
# Mixed payload (realistic connector usage)
# ---------------------------------------------------------------------------


def test_mixed_allowlisted_and_phi_keys() -> None:
    result = sanitize_metadata_for_audit(
        {
            "source_system": "EHR-A",
            "connector_version": "2.1.0",
            "batch_id": "batch-abc",
            "patient_id": "ID-001",         # PHI — must be dropped
            "diagnosis": "some condition",   # PHI — must be dropped
            "tenant": "acme",               # identity via auth, not metadata
        }
    )
    assert result == {
        "source_system": "EHR-A",
        "connector_version": "2.1.0",
        "batch_id": "batch-abc",
    }


def test_does_not_mutate_original_dict() -> None:
    original = {"source_system": "connector", "phi": "secret"}
    sanitize_metadata_for_audit(original)
    assert "phi" in original
    assert "source_system" in original
