from __future__ import annotations

import re
from typing import Any

from app.services.medical_classifier.cloud_store import (
    MedicalClassifierCloudStore,
    normalize_procedure_code,
    normalize_project_number,
    utc_now_iso,
)


def export_current_spec_to_omniscan_json(
    *,
    store: MedicalClassifierCloudStore,
    tenant_id: str,
    project_number: str,
    procedure_code: str,
) -> dict[str, Any]:
    """Export the current active procedure spec as an OmniScan Constitution snapshot."""
    normalized_project = normalize_project_number(project_number)
    normalized_code = normalize_procedure_code(procedure_code)
    current = store.get_current_procedure_spec_version(tenant_id, normalized_project, normalized_code)
    if not current:
        raise LookupError("procedure_spec_not_found")
    return build_omniscan_export_from_current_spec(current)


def build_omniscan_export_from_current_spec(current: dict[str, Any]) -> dict[str, Any]:
    spec = current.get("spec") if isinstance(current.get("spec"), dict) else {}
    procedure_spec = current.get("procedure_spec") if isinstance(current.get("procedure_spec"), dict) else {}
    source = spec.get("source") if isinstance(spec.get("source"), dict) else {}
    snapshot = _constitution_snapshot(source)

    return {
        "constitution_version": _text(
            snapshot.get("constitution_version")
            or source.get("constitution_version")
            or current.get("version")
            or procedure_spec.get("current_version")
        ),
        "exported_at": utc_now_iso(),
        "subject": _export_subject(snapshot, source, procedure_spec),
        "indexes": _export_indexes(spec, snapshot),
        "rules": _export_rules(spec, snapshot),
    }


def _constitution_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    for key in ("constitution_snapshot", "omniscan_constitution", "omniscan_export"):
        snapshot = source.get(key)
        if isinstance(snapshot, dict):
            return snapshot
    return {}


def _export_subject(
    snapshot: dict[str, Any],
    source: dict[str, Any],
    procedure_spec: dict[str, Any],
) -> dict[str, Any]:
    subject = snapshot.get("subject") if isinstance(snapshot.get("subject"), dict) else {}
    exported = dict(subject)
    exported.setdefault(
        "ProjectID", _code_value(source.get("project_id") or procedure_spec.get("project_number"))
    )
    exported.setdefault("SubjectNumber", _code_value(source.get("subject_number")))
    exported.setdefault("SubjectName", _text(procedure_spec.get("procedure_name")))
    exported.setdefault("Active", 1)
    return _coerce_active_fields(exported)


def _export_indexes(spec: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw_indexes = snapshot.get("indexes") if isinstance(snapshot.get("indexes"), list) else []
    raw_by_row_id = _raw_indexes_by_identity(raw_indexes, "RowID")
    raw_by_key = _raw_indexes_by_identity(raw_indexes, "key", "IndexKey")

    exported: list[dict[str, Any]] = []
    indexes = spec.get("indexes") if isinstance(spec.get("indexes"), list) else []
    for index in indexes:
        if not isinstance(index, dict):
            continue
        metadata = index.get("omniscan") if isinstance(index.get("omniscan"), dict) else {}
        raw = raw_by_row_id.get(_identity_text(metadata.get("row_id")))
        if raw is None:
            raw = raw_by_key.get(_identity_text(index.get("key")))
        exported.append(_export_index(index, metadata, raw if isinstance(raw, dict) else {}))
    return exported


def _raw_indexes_by_identity(raw_indexes: list[Any], *keys: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index in raw_indexes:
        if not isinstance(index, dict):
            continue
        identity = ""
        for key in keys:
            identity = _identity_text(index.get(key))
            if identity:
                break
        if identity:
            indexed[identity] = index
    return indexed


def _export_index(index: dict[str, Any], metadata: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    expression = raw.get("Expression")
    if expression is None:
        expression = metadata.get("expression") or _prefixed_rule_value(index, "OmniScan expression:")

    category_desc = raw.get("CategoryDesc")
    if category_desc is None:
        category_desc = (
            metadata.get("category_desc")
            or index.get("description")
            or _prefixed_rule_value(index, "Index description:")
        )

    return {
        "RowID": _nullable_code(raw.get("RowID", metadata.get("row_id"))),
        "IndexTypeCode": _code_value(raw.get("IndexTypeCode", metadata.get("index_type_code"))),
        "IndexTypeDesc": _text(
            raw.get("IndexTypeDesc") or metadata.get("index_type_desc") or index.get("category") or "omniscan"
        ),
        "CategoryCode": _code_value(raw.get("CategoryCode", metadata.get("category_code"))),
        "CategoryName": _text(
            raw.get("CategoryName") or metadata.get("category_name") or index.get("label") or index.get("key")
        ),
        "CategoryDesc": _text(category_desc),
        "Expression": _text(expression),
        "Active": _active_int(raw.get("Active", metadata.get("active")), default=1),
    }


def _export_rules(spec: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rules = spec.get("rules")
    if not isinstance(raw_rules, list):
        raw_rules = snapshot.get("rules") if isinstance(snapshot.get("rules"), list) else []
    if raw_rules:
        return [_export_rule(rule if isinstance(rule, dict) else {}) for rule in raw_rules]

    rules: list[dict[str, Any]] = []
    indexes = spec.get("indexes") if isinstance(spec.get("indexes"), list) else []
    for index in indexes:
        if not isinstance(index, dict):
            continue
        index_rules = index.get("rules") if isinstance(index.get("rules"), list) else []
        for rule_text in index_rules:
            rule = _rule_from_text(rule_text)
            if rule:
                rules.append(_export_rule(rule))
    return rules


def _export_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "RuleCode": _nullable_code(_first_present(rule, "RuleCode", "rule_code")),
        "RuleName": _text(_first_present(rule, "RuleName", "rule_name")),
        "RuleDesc": _text(_first_present(rule, "RuleDesc", "rule_desc", "description")),
        "ApprovalCategoryCode": _csv_string(
            _first_present(rule, "ApprovalCategoryCode", "approval_category_code")
        ),
        "ApprovalCategoryDesc": _csv_string(
            _first_present(rule, "ApprovalCategoryDesc", "approval_category_desc")
        ),
        "AlertCategoryCode": _csv_string(_first_present(rule, "AlertCategoryCode", "alert_category_code")),
        "AlertCategoryDesc": _csv_string(_first_present(rule, "AlertCategoryDesc", "alert_category_desc")),
        "ApprovalTypeCode": _code_value(_first_present(rule, "ApprovalTypeCode", "approval_type_code")),
        "ApprovalTypeDesc": _text(_first_present(rule, "ApprovalTypeDesc", "approval_type_desc")),
        "RulePriority": _code_value(_first_present(rule, "RulePriority", "rule_priority")),
        "Active": _active_int(rule.get("Active", rule.get("active")), default=1),
    }


def _rule_from_text(value: Any) -> dict[str, Any] | None:
    text = _text(value)
    if not text.startswith("OmniScan rule"):
        return None
    match = re.match(
        r"OmniScan rule(?: (?P<code>[^:]+))?: (?P<body>.*?)(?:\. Priority: (?P<priority>[^.]+)\.)?$", text
    )
    if not match:
        return {"RuleDesc": text, "Active": 1}
    parts = [part.strip() for part in match.group("body").rstrip(".").split("|")]
    return {
        "RuleCode": match.group("code"),
        "RuleName": parts[0] if parts else "",
        "RuleDesc": parts[1] if len(parts) > 1 else "",
        "ApprovalTypeDesc": parts[-1] if len(parts) > 2 else "",
        "RulePriority": match.group("priority"),
        "Active": 1,
    }


def _prefixed_rule_value(index: dict[str, Any], prefix: str) -> str:
    rules = index.get("rules") if isinstance(index.get("rules"), list) else []
    for rule in rules:
        text = _text(rule)
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return ""


def _coerce_active_fields(payload: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(payload)
    if "Active" in coerced:
        coerced["Active"] = _active_int(coerced["Active"], default=1)
    return coerced


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def _nullable_code(value: Any) -> int | str | None:
    if value is None or value == "":
        return None
    return _code_value(value)


def _code_value(value: Any) -> int | float | str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _csv_string(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        return ",".join(_text(item) for item in value if _text(item))
    text = _text(value)
    if "," not in text:
        return text
    return ",".join(part.strip() for part in text.split(",") if part.strip())


def _active_int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int | float):
        return 1 if value else 0
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "y", "on"} else 0


def _identity_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
