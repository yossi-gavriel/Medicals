from __future__ import annotations

import re
from typing import Any

from app.services.medical_classifier.cloud_store import (
    MedicalClassifierCloudStore,
    normalize_procedure_code,
    normalize_project_number,
    validate_procedure_spec_body,
)

SUPPORTED_OMNISCAN_EXPORT_FIELDS = {
    "root": ["constitution_version", "exported_at", "subject", "indexes", "rules"],
    "subject": [
        "SubjectNumber",
        "SubjectName",
        "ProjectID",
        "ProjectName",
        "FolderName",
        "ProcessType",
        "ProcedureName",
        "TreatmentCode",
        "TreatmentDesc",
        "Active",
    ],
    "index": [
        "key",
        "IndexKey",
        "RowID",
        "IndexTypeCode",
        "IndexTypeDesc",
        "CategoryCode",
        "CategoryName",
        "CategoryDesc",
        "Expression",
        "Active",
        "output_type",
    ],
    "rule": [
        "RuleCode",
        "RuleName",
        "RuleDesc",
        "ApprovalCategoryCode",
        "ApprovalCategoryDesc",
        "AlertCategoryCode",
        "AlertCategoryDesc",
        "SubjectStatusCode",
        "SubjectStatusDesc",
        "ApprovalTypeCode",
        "ApprovalTypeDesc",
        "RulePriority",
        "Active",
    ],
}


def import_spec_from_omniscan_json(
    *,
    store: MedicalClassifierCloudStore,
    tenant_id: str,
    project_number: str,
    procedure_code: str | None = None,
    treatment_code: str | None = None,
    procedure_name: str | None = None,
    exported_spec: dict[str, Any],
    publish: bool = True,
    published_by: str,
) -> dict[str, Any]:
    """Import an OmniScan Constitution JSON export as a procedure spec.

    Supported OmniScan shape is the export produced by
    `/api/constitution/export`: `{subject, indexes, rules}`. The mapper is
    intentionally allow-list based so document text, case identifiers, OCR
    snippets, or other PHI-like accidental fields are not persisted in the spec.
    """
    normalized_project = normalize_project_number(project_number)
    normalized_code = normalize_procedure_code(procedure_code or treatment_code)
    if not isinstance(exported_spec, dict):
        raise ValueError("exported_spec must be a JSON object")

    draft_spec = build_draft_spec_from_omniscan_json(exported_spec)
    resolved_name = _resolve_procedure_name(
        procedure_name=procedure_name,
        exported_spec=exported_spec,
        procedure_code=normalized_code,
    )
    payload = {
        "procedure_code": normalized_code,
        "procedure_name": resolved_name,
        "description": _procedure_description(exported_spec),
        "draft_spec": draft_spec,
        "status": "draft",
    }
    procedure_spec = store.save_procedure_spec(tenant_id, normalized_project, payload)
    published_spec = None
    if publish:
        published_spec = store.publish_procedure_spec(
            tenant_id,
            normalized_project,
            normalized_code,
            published_by=published_by,
        )
    return {
        "procedure_spec": published_spec or procedure_spec,
        "published": bool(published_spec),
        "project_number": normalized_project,
        "procedure_code": normalized_code,
        "indexes_count": len(draft_spec.get("indexes") or []),
        "rules_count": len(_list_from(exported_spec, "rules", "Rules")),
        "warnings": [],
        "import_summary": {
            "source_system": "omniscan",
            "index_count": len(draft_spec.get("indexes") or []),
            "rule_count": len(_list_from(exported_spec, "rules", "Rules")),
            "supported_fields": SUPPORTED_OMNISCAN_EXPORT_FIELDS,
        },
    }


def build_draft_spec_from_omniscan_json(exported_spec: dict[str, Any]) -> dict[str, Any]:
    indexes = _list_from(exported_spec, "indexes", "Indexes", "indices", "categories", "Categories")
    if not indexes:
        raise ValueError("exported_spec.indexes must contain at least one index")

    rules = _list_from(exported_spec, "rules", "Rules")
    subject = exported_spec.get("subject") if isinstance(exported_spec.get("subject"), dict) else {}
    mapped_indexes = _map_indexes(indexes, rules)
    constitution_snapshot = _constitution_snapshot(exported_spec, indexes, rules)
    draft_spec = {
        "system_prompt": _system_prompt(subject),
        "indexes": mapped_indexes,
        "source": {
            "system": "omniscan",
            "format": "constitution",
            "constitution_version": _safe_text(exported_spec.get("constitution_version"), max_len=64),
            "subject_number": _safe_text(subject.get("SubjectNumber"), max_len=64),
            "project_id": _safe_text(subject.get("ProjectID"), max_len=64),
            "index_count": len(mapped_indexes),
            "rule_count": len(rules),
            "constitution_snapshot": constitution_snapshot,
        },
    }
    validate_procedure_spec_body(draft_spec, require_publishable=True)
    return draft_spec


def _map_indexes(indexes: list[Any], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[tuple[int, dict[str, Any], str, bool]] = []
    key_counts: dict[str, int] = {}
    for position, index in enumerate(indexes, start=1):
        if not isinstance(index, dict):
            raise ValueError(f"index #{position} must be an object")
        key = _index_key(index, position)
        explicit = _has_explicit_key(index)
        prepared.append((position, index, key, explicit))
        key_counts[key] = key_counts.get(key, 0) + 1

    mapped: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    for position, index, key, explicit in prepared:
        if key_counts[key] > 1 and not explicit:
            key = _disambiguate_generated_key(key, index, position, used_keys)
        mapped_index = _map_index(index, rules, position, key=key)
        used_keys.add(mapped_index["key"])
        mapped.append(mapped_index)
    return mapped


def _map_index(
    index: Any, rules: list[dict[str, Any]], position: int, *, key: str | None = None
) -> dict[str, Any]:
    if not isinstance(index, dict):
        raise ValueError(f"index #{position} must be an object")

    key = key or _index_key(index, position)
    label = _first_text(index, "label", "Label", "CategoryName", "IndexName", "name")
    if not label:
        raise ValueError(f"label is required for {key}")

    output_type = (_first_text(index, "output_type", "OutputType") or "binary").lower()
    if output_type not in {"binary", "score", "text"}:
        raise ValueError(f"unsupported output_type for {key}: {output_type}")

    category_code = _first_text(index, "CategoryCode", "category_code")
    index_type = _first_text(index, "IndexTypeDesc", "index_type", "category") or "omniscan"
    related_rules = _related_rule_texts(index, rules)
    expression = _first_text(index, "Expression", "expression", "query", "rule")
    description = _first_text(index, "CategoryDesc", "description", "Description")
    evidence_definition = _first_text(
        index,
        "evidence_definition",
        "EvidenceDefinition",
        "RequiredEvidence",
        "required_evidence_definition",
    )

    rule_lines: list[str] = []
    if expression:
        rule_lines.append(f"OmniScan expression: {expression}")
    if description:
        rule_lines.append(f"Index description: {description}")
    if evidence_definition:
        rule_lines.append(f"Evidence definition: {evidence_definition}")
    rule_lines.extend(related_rules)
    if not rule_lines:
        raise ValueError(
            f"{key} must include Expression, CategoryDesc, evidence_definition, or a linked rule"
        )

    return {
        "key": key,
        "label": label,
        "category": index_type,
        "description": description,
        "output_type": output_type,
        "required_evidence": _bool_from(index.get("required_evidence", index.get("RequiredEvidence"))),
        "positive_terms": _str_list(index.get("positive_terms") or index.get("PositiveTerms")),
        "negative_terms": _str_list(index.get("negative_terms") or index.get("NegativeTerms")),
        "positive_phrases": _str_list(index.get("positive_phrases") or index.get("PositivePhrases")),
        "negative_phrases": _str_list(index.get("negative_phrases") or index.get("NegativePhrases")),
        "rules": rule_lines,
        "omniscan": {
            "row_id": _safe_omniscan_value(index.get("RowID"), max_len=64),
            "index_type_code": _safe_omniscan_value(index.get("IndexTypeCode"), max_len=64),
            "index_type_desc": _safe_omniscan_value(index.get("IndexTypeDesc"), max_len=256),
            "category_code": _safe_omniscan_value(category_code, max_len=64),
            "category_name": _safe_omniscan_value(label, max_len=512),
            "category_desc": _safe_omniscan_value(description, max_len=4000),
            "expression": _safe_omniscan_value(expression, max_len=8000),
            "active": _active_int_or_none(index.get("Active")),
        },
    }


def _constitution_snapshot(
    exported_spec: dict[str, Any],
    indexes: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    subject = exported_spec.get("subject") if isinstance(exported_spec.get("subject"), dict) else {}
    return {
        "constitution_version": _safe_omniscan_value(
            exported_spec.get("constitution_version"),
            max_len=64,
        ),
        "subject": _allowlisted_object(subject, SUPPORTED_OMNISCAN_EXPORT_FIELDS["subject"]),
        "indexes": [
            _allowlisted_object(index, SUPPORTED_OMNISCAN_EXPORT_FIELDS["index"])
            for index in indexes
            if isinstance(index, dict)
        ],
        "rules": [
            _allowlisted_object(rule, SUPPORTED_OMNISCAN_EXPORT_FIELDS["rule"])
            for rule in rules
            if isinstance(rule, dict)
        ],
    }


def _allowlisted_object(payload: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for field in fields:
        if field not in payload:
            continue
        sanitized_value = _safe_omniscan_value(payload.get(field), max_len=8000)
        if sanitized_value is not None:
            sanitized[field] = sanitized_value
    return sanitized


def _safe_omniscan_value(value: Any, *, max_len: int = 2000) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    if isinstance(value, list):
        sanitized = [_safe_omniscan_value(item, max_len=max_len) for item in value]
        return [item for item in sanitized if item is not None]
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _active_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return 1 if _bool_from(value) else 0


def _index_key(index: dict[str, Any], position: int) -> str:
    explicit = _first_text(index, "key", "Key", "index_key", "IndexKey", "idx_key", "IDXKey")
    if explicit:
        return _normalize_idx_key(explicit)

    category_code = _first_text(index, "CategoryCode", "category_code")
    row_id = _first_text(index, "RowID", "row_id")
    if not category_code and not row_id:
        raise ValueError(
            f"index #{position} key is required; provide key/IndexKey or OmniScan CategoryCode/RowID"
        )
    type_prefix = _index_type_prefix(index)
    suffix = category_code or row_id
    return _normalize_idx_key(f"{type_prefix}_{suffix}")


def _has_explicit_key(index: dict[str, Any]) -> bool:
    return bool(_first_text(index, "key", "Key", "index_key", "IndexKey", "idx_key", "IDXKey"))


def _disambiguate_generated_key(
    base_key: str,
    index: dict[str, Any],
    position: int,
    used_keys: set[str],
) -> str:
    row_id = _first_text(index, "RowID", "row_id")
    suffixes = [
        f"ROW_{row_id}" if row_id else "",
        _first_text(index, "CategoryName", "IndexName", "label", "Label", "name"),
        str(position),
    ]
    for suffix in suffixes:
        if not suffix:
            continue
        candidate = _normalize_idx_key(f"{base_key}_{suffix}")
        if candidate not in used_keys:
            return candidate
    counter = position
    while True:
        candidate = _normalize_idx_key(f"{base_key}_{counter}")
        if candidate not in used_keys:
            return candidate
        counter += 1


def _normalize_idx_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("IDX key is required")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    if not text:
        raise ValueError("IDX key is required")
    if not text.startswith("IDX_"):
        text = f"IDX_{text}"
    return text


def _index_type_prefix(index: dict[str, Any]) -> str:
    desc = _first_text(index, "IndexTypeDesc", "index_type") or ""
    code = _first_text(index, "IndexTypeCode", "index_type_code") or ""
    lowered = desc.lower()
    if "approve" in lowered or code == "1":
        return "APPROVAL"
    if "alert" in lowered or code == "2":
        return "ALERT"
    return "CATEGORY"


def _related_rule_texts(index: dict[str, Any], rules: list[dict[str, Any]]) -> list[str]:
    category_code = _first_text(index, "CategoryCode", "category_code")
    if not category_code:
        return []
    index_kind = _index_type_prefix(index)
    matched: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        approval_codes = set(_code_list(rule, "ApprovalCategoryCode", "approvalCategoryCode"))
        alert_codes = set(_code_list(rule, "AlertCategoryCode", "alertCategoryCode"))
        if index_kind == "APPROVAL" and category_code not in approval_codes:
            continue
        if index_kind == "ALERT" and category_code not in alert_codes:
            continue
        if index_kind == "CATEGORY" and category_code not in approval_codes | alert_codes:
            continue
        text = _rule_text(rule)
        if text:
            matched.append(text)
    return matched


def _rule_text(rule: dict[str, Any]) -> str:
    parts = [
        _first_text(rule, "RuleName", "rule_name"),
        _first_text(rule, "RuleDesc", "rule_desc", "description"),
        _status_rule_text(rule),
        _first_text(rule, "ApprovalTypeDesc", "approval_type"),
    ]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    code = _first_text(rule, "RuleCode", "rule_code")
    priority = _first_text(rule, "RulePriority", "rule_priority")
    prefix = f"OmniScan rule {code}" if code else "OmniScan rule"
    suffix = f" Priority: {priority}." if priority else ""
    return f"{prefix}: {' | '.join(parts)}.{suffix}"


def _status_rule_text(rule: dict[str, Any]) -> str:
    status_desc = _first_text(rule, "SubjectStatusDesc", "subject_status_desc")
    if status_desc:
        return f"Subject status: {status_desc}"
    status_codes = _code_list(rule, "SubjectStatusCode", "subject_status_code")
    if status_codes:
        return f"Subject status codes: {', '.join(status_codes)}"
    return ""


def _system_prompt(subject: dict[str, Any]) -> str:
    subject_name = _safe_text(subject.get("SubjectName"), max_len=160)
    process_type = _safe_text(subject.get("ProcessType"), max_len=120)
    context = []
    if subject_name:
        context.append(f"Subject: {subject_name}")
    if process_type:
        context.append(f"Process type: {process_type}")
    context_text = "\n".join(context) if context else "Subject metadata: not provided"
    return f"""
You are a senior medical document reviewer using an OmniScan exported Constitution.
Classify only from the provided document text and the imported index/rule definitions.
Do not infer from planned, future, historical, consent-only, or ambiguous mentions.
Return only structured JSON for the requested IDX keys.

{context_text}
""".strip()


def _resolve_procedure_name(
    *,
    procedure_name: str | None,
    exported_spec: dict[str, Any],
    procedure_code: str,
) -> str:
    if procedure_name and procedure_name.strip():
        return procedure_name.strip()
    subject = exported_spec.get("subject") if isinstance(exported_spec.get("subject"), dict) else {}
    for key in ("ProcedureName", "TreatmentDesc", "SubjectName"):
        value = _safe_text(subject.get(key), max_len=256)
        if value:
            return value
    return procedure_code


def _procedure_description(exported_spec: dict[str, Any]) -> str:
    subject = exported_spec.get("subject") if isinstance(exported_spec.get("subject"), dict) else {}
    project = _safe_text(subject.get("ProjectName"), max_len=160)
    subject_name = _safe_text(subject.get("SubjectName"), max_len=160)
    parts = [part for part in (project, subject_name) if part]
    return "Imported from OmniScan Constitution" + (": " + " / ".join(parts) if parts else "")


def _list_from(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError(f"exported_spec.{key} must be a list")
        return value
    return []


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _safe_text(payload.get(key))
        if value:
            return value
    return ""


def _code_list(payload: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = payload.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, list):
            return [_safe_text(item, max_len=64) for item in value if _safe_text(item, max_len=64)]
        return [
            _safe_text(item, max_len=64) for item in str(value).split(",") if _safe_text(item, max_len=64)
        ]
    return []


def _safe_text(value: Any, *, max_len: int = 2000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text[:max_len]


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_text(item) for item in value if _safe_text(item)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _bool_from(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
