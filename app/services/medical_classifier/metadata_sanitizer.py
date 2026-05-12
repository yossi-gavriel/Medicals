from __future__ import annotations

# Keys explicitly permitted in the audit log.
# Everything not on this list is dropped to prevent accidental PHI persistence.
AUDIT_METADATA_ALLOWLIST: frozenset[str] = frozenset(
    {
        "document_id",
        "source_system",
        "source_table",
        "batch_id",
        "run_id",
        "connector_version",
        "environment",
        "external_document_id",
        "customer_reference",
        "external_trace_id",
    }
)

_MAX_VALUE_LENGTH = 256


def sanitize_metadata_for_audit(metadata: dict | None) -> dict:
    """Return a copy of *metadata* containing only allowlisted, scalar-safe keys.

    - Unknown keys are silently dropped (they may contain PHI).
    - String values are truncated to _MAX_VALUE_LENGTH characters.
    - Nested structures (dicts, lists) are dropped because they can contain PHI.
    - None is treated the same as an empty dict.
    """
    if not metadata:
        return {}

    result: dict = {}
    for key, value in metadata.items():
        if key not in AUDIT_METADATA_ALLOWLIST:
            continue
        if isinstance(value, (bool, int, float)):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:_MAX_VALUE_LENGTH]
        # dicts, lists, and anything else are silently dropped
    return result
