from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

VALID_STORAGE_MODES = {"local_only", "cloud", "hybrid"}
VALID_TENANT_STATUSES = {"active", "disabled", "archived"}
VALID_PROJECT_STATUSES = {"active", "disabled", "archived"}
VALID_SPEC_STATUSES = {"draft", "active", "archived"}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def spec_hash(spec: dict[str, Any]) -> str:
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def normalize_project_number(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("project_number is required")
    return text


def normalize_procedure_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("procedure_code is required")
    return text


def normalize_storage_mode(value: Any, *, default: str = "local_only", allow_none: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        return None if allow_none else default
    mode = str(value).strip().lower()
    if mode not in VALID_STORAGE_MODES:
        raise ValueError("storage_mode must be one of: cloud, hybrid, local_only")
    return mode


def normalize_status(value: Any, *, valid: set[str], default: str) -> str:
    status = str(value or default).strip().lower()
    if status not in valid:
        raise ValueError(f"status must be one of: {', '.join(sorted(valid))}")
    return status


def resolve_storage_policy(
    *,
    tenant_storage_mode: Any,
    project_storage_mode_override: Any = None,
    request_storage_preference: Any = None,
) -> str:
    tenant_mode = normalize_storage_mode(tenant_storage_mode) or "local_only"
    if tenant_mode == "local_only":
        return "local_only"

    project_mode = normalize_storage_mode(project_storage_mode_override, allow_none=True)
    base_mode = project_mode or tenant_mode
    if base_mode == "local_only":
        return "local_only"

    request_mode = normalize_storage_mode(request_storage_preference, allow_none=True)
    if request_mode == "local_only":
        return "local_only"
    if request_mode == "cloud":
        return "cloud" if base_mode in {"cloud", "hybrid"} else "local_only"
    if request_mode == "hybrid":
        return "local_only" if base_mode == "hybrid" else base_mode

    if base_mode == "hybrid":
        return "local_only"
    return base_mode


def validate_procedure_spec_body(spec: dict[str, Any], *, require_publishable: bool) -> None:
    system_prompt = str(spec.get("system_prompt") or "").strip()
    indexes = spec.get("indexes")
    if indexes is None:
        indexes = []
    if not isinstance(indexes, list):
        raise ValueError("draft_spec.indexes must be a list")
    if require_publishable and not system_prompt:
        raise ValueError("draft_spec.system_prompt is required before publishing")
    if require_publishable and not indexes:
        raise ValueError("at least one IDX row is required before publishing")

    seen: set[str] = set()
    for index in indexes:
        if not isinstance(index, dict):
            raise ValueError("each IDX row must be an object")
        key = str(index.get("key") or "").strip()
        label = str(index.get("label") or "").strip()
        if not key:
            raise ValueError("IDX key is required")
        if not key.startswith("IDX_"):
            raise ValueError(f"IDX key must start with IDX_: {key}")
        if key in seen:
            raise ValueError(f"duplicate IDX key: {key}")
        seen.add(key)
        if not label:
            raise ValueError(f"label is required for {key}")
        output_type = str(index.get("output_type") or "binary").strip()
        if output_type not in {"binary", "score", "text"}:
            raise ValueError(f"unsupported output_type for {key}: {output_type}")
        _validate_string_list(index, "positive_terms", key)
        _validate_string_list(index, "negative_terms", key)
        _validate_string_list(index, "positive_phrases", key)
        _validate_string_list(index, "negative_phrases", key)
        _validate_string_list(index, "rules", key)
        _validate_examples(index.get("examples"), key)


def sanitize_index_details_for_storage(index_details: dict[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, raw_detail in (index_details or {}).items():
        if not isinstance(raw_detail, dict):
            continue
        detail: dict[str, Any] = {}
        for safe_key in ("result_code", "found", "confidence", "explanation"):
            if safe_key in raw_detail:
                detail[safe_key] = raw_detail[safe_key]
        sanitized[str(key)] = detail
    return sanitized


@dataclass(frozen=True)
class ApiKeyContext:
    tenant_id: str
    api_key_id: str
    api_key_hash_prefix: str
    api_key_hash: str


@dataclass(frozen=True)
class MedicalClassifierTableNames:
    tenants: str = ""
    api_keys: str = ""
    projects: str = ""
    procedure_specs: str = ""
    procedure_spec_versions: str = ""
    classification_runs: str = ""
    classification_results: str = ""
    audit_logs: str = ""

    @classmethod
    def from_env(cls) -> MedicalClassifierTableNames:
        return cls(
            tenants=os.getenv("MEDICAL_CLASSIFIER_TENANTS_TABLE", "").strip(),
            api_keys=os.getenv("MEDICAL_CLASSIFIER_API_KEYS_TABLE", "").strip(),
            projects=os.getenv("MEDICAL_CLASSIFIER_PROJECTS_TABLE", "").strip(),
            procedure_specs=os.getenv("MEDICAL_CLASSIFIER_PROCEDURE_SPECS_TABLE", "").strip(),
            procedure_spec_versions=os.getenv(
                "MEDICAL_CLASSIFIER_PROCEDURE_SPEC_VERSIONS_TABLE", ""
            ).strip(),
            classification_runs=os.getenv("MEDICAL_CLASSIFIER_CLASSIFICATION_RUNS_TABLE", "").strip(),
            classification_results=os.getenv(
                "MEDICAL_CLASSIFIER_CLASSIFICATION_RESULTS_TABLE", ""
            ).strip(),
            audit_logs=os.getenv("MEDICAL_CLASSIFIER_AUDIT_LOGS_TABLE", "").strip()
            or os.getenv("MEDICAL_CLASSIFIER_AUDIT_TABLE", "").strip(),
        )

    @property
    def has_project_spec_storage(self) -> bool:
        return all(
            [
                self.projects,
                self.procedure_specs,
                self.procedure_spec_versions,
                self.classification_runs,
                self.classification_results,
                self.audit_logs,
            ]
        )


class MedicalClassifierCloudStore:
    def __init__(
        self,
        *,
        client: Any | None,
        tables: MedicalClassifierTableNames | None = None,
    ) -> None:
        self.client = client
        self.tables = tables or MedicalClassifierTableNames.from_env()

    @classmethod
    def from_env(cls) -> MedicalClassifierCloudStore:
        import boto3

        return cls(client=boto3.client("dynamodb"))

    @property
    def enabled(self) -> bool:
        return self.tables.has_project_spec_storage

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        if not self.tables.tenants:
            return None
        item = self._get_item(self.tables.tenants, {"tenant_id": tenant_id})
        return self._normalize_tenant_item(item) if item else None

    def put_tenant(self, payload: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(payload.get("tenant_id") or "").strip() or str(uuid.uuid4())
        existing = self.get_tenant(tenant_id) or {}
        now = utc_now_iso()
        item = {
            "tenant_id": tenant_id,
            "customer_number": str(
                payload.get("customer_number")
                or payload.get("customer_id")
                or existing.get("customer_number")
                or tenant_id
            ).strip(),
            "customer_id": str(payload.get("customer_id") or existing.get("customer_id") or tenant_id).strip(),
            "license_number": str(payload.get("license_number") or existing.get("license_number") or "").strip(),
            "product_license_id": str(
                payload.get("product_license_id") or existing.get("product_license_id") or ""
            ).strip(),
            "customer_name": str(
                payload.get("customer_name")
                or payload.get("tenant_name")
                or existing.get("customer_name")
                or existing.get("tenant_name")
                or ""
            ).strip(),
            "tenant_name": str(
                payload.get("tenant_name")
                or payload.get("customer_name")
                or existing.get("tenant_name")
                or existing.get("customer_name")
                or ""
            ).strip(),
            "contact_name": str(payload.get("contact_name") or existing.get("contact_name") or "").strip(),
            "address": str(payload.get("address") or existing.get("address") or "").strip(),
            "email": str(payload.get("email") or existing.get("email") or "").strip(),
            "phone": str(payload.get("phone") or existing.get("phone") or "").strip(),
            "storage_mode": normalize_storage_mode(payload.get("storage_mode", existing.get("storage_mode"))),
            "status": normalize_status(
                payload.get("status", existing.get("status")),
                valid=VALID_TENANT_STATUSES,
                default="active",
            ),
            "allowed_project_count": payload.get(
                "allowed_project_count", existing.get("allowed_project_count")
            ),
            "allowed_storage_until": payload.get(
                "allowed_storage_until", existing.get("allowed_storage_until")
            ),
            "notes": str(payload.get("notes") or existing.get("notes") or "").strip(),
            "created_by": str(payload.get("created_by") or existing.get("created_by") or "").strip(),
            "updated_by": str(payload.get("updated_by") or existing.get("updated_by") or "").strip(),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        self._put_item(self.tables.tenants, item)
        return self._normalize_tenant_item(item)

    def update_tenant_storage_policy(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        tenant = self.get_tenant(tenant_id) or {
            "tenant_id": tenant_id,
            "customer_number": tenant_id,
            "customer_id": tenant_id,
            "status": "active",
        }
        tenant["storage_mode"] = normalize_storage_mode(payload.get("storage_mode"))
        tenant["updated_by"] = updated_by or tenant.get("updated_by")
        return self.put_tenant(tenant)

    def public_tenant_view(self, tenant_id: str) -> dict[str, Any]:
        tenant = self.get_tenant(tenant_id) or {
            "tenant_id": tenant_id,
            "customer_number": tenant_id,
            "customer_id": tenant_id,
            "customer_name": "",
            "tenant_name": "",
            "storage_mode": "local_only",
            "status": "active",
        }
        tenant = self._normalize_tenant_item(tenant)
        return {
            key: tenant.get(key)
            for key in (
                "tenant_id",
                "customer_number",
                "customer_id",
                "license_number",
                "product_license_id",
                "customer_name",
                "contact_name",
                "address",
                "email",
                "phone",
                "storage_mode",
                "status",
                "allowed_project_count",
                "allowed_storage_until",
                "notes",
                "created_at",
                "updated_at",
            )
            if tenant.get(key) not in {None, ""}
        }

    def resolve_api_key(self, api_key: str | None) -> ApiKeyContext | None:
        if not api_key:
            return None

        api_key_hash = sha256_text(api_key)
        prefix = api_key_hash[:16]
        if self.tables.api_keys:
            if self.client is None:
                return None
            item = self._get_item(
                self.tables.api_keys,
                {"api_key_hash_prefix": prefix},
            )
            if not item:
                return None
            if not secrets.compare_digest(str(item.get("api_key_hash", "")), api_key_hash):
                return None
            if str(item.get("status", "active")).lower() != "active":
                return None
            tenant_id = str(item.get("tenant_id") or "").strip()
            if not tenant_id:
                return None
            self._touch_api_key(prefix)
            return ApiKeyContext(
                tenant_id=tenant_id,
                api_key_id=str(item.get("key_id") or prefix),
                api_key_hash_prefix=prefix,
                api_key_hash=api_key_hash,
            )

        for candidate in _csv_env("MEDICAL_CLASSIFIER_API_KEY_HASHES"):
            if secrets.compare_digest(api_key_hash, candidate):
                tenant_id = os.getenv("MEDICAL_CLASSIFIER_DEFAULT_TENANT_ID", "").strip()
                return ApiKeyContext(
                    tenant_id=tenant_id or f"tenant#{prefix}",
                    api_key_id=prefix,
                    api_key_hash_prefix=prefix,
                    api_key_hash=api_key_hash,
                )

        if _truthy_env("MEDICAL_CLASSIFIER_ALLOW_PLAINTEXT_API_KEYS"):
            for candidate in _csv_env("MEDICAL_CLASSIFIER_API_KEYS"):
                if secrets.compare_digest(api_key, candidate):
                    tenant_id = os.getenv("MEDICAL_CLASSIFIER_DEFAULT_TENANT_ID", "").strip()
                    return ApiKeyContext(
                        tenant_id=tenant_id or f"tenant#{prefix}",
                        api_key_id=prefix,
                        api_key_hash_prefix=prefix,
                        api_key_hash=api_key_hash,
                    )
        return None

    def list_projects(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._query_by_prefix(self.tables.projects, tenant_id, "PROJECT#")

    def get_project(self, tenant_id: str, project_number: str) -> dict[str, Any] | None:
        return self._get_item(
            self.tables.projects,
            {
                "tenant_id": tenant_id,
                "sort_key": f"PROJECT#{normalize_project_number(project_number)}",
            },
        )

    def put_project(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project_number = normalize_project_number(payload.get("project_number"))
        existing = self.get_project(tenant_id, project_number) or {}
        now = utc_now_iso()
        storage_override = normalize_storage_mode(
            payload.get("default_storage_mode_override", existing.get("default_storage_mode_override")),
            allow_none=True,
        )
        item = {
            "tenant_id": tenant_id,
            "sort_key": f"PROJECT#{project_number}",
            "project_id": existing.get("project_id") or str(uuid.uuid4()),
            "project_number": project_number,
            "project_name": str(
                payload.get("project_name") or payload.get("name") or existing.get("project_name") or existing.get("name") or project_number
            ).strip(),
            "name": str(
                payload.get("name") or payload.get("project_name") or existing.get("name") or existing.get("project_name") or project_number
            ).strip(),
            "description": str(payload.get("description") or existing.get("description") or "").strip(),
            "status": normalize_status(
                payload.get("status", existing.get("status")),
                valid=VALID_PROJECT_STATUSES,
                default="active",
            ),
            "default_storage_mode_override": storage_override,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        self._put_item(self.tables.projects, item)
        return item

    def update_project_storage_policy(
        self,
        tenant_id: str,
        project_number: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        project = self.get_project(tenant_id, project_number)
        if not project:
            raise LookupError("project_not_found")
        project["default_storage_mode_override"] = normalize_storage_mode(
            payload.get("default_storage_mode_override", payload.get("storage_mode")),
            allow_none=True,
        )
        return self.put_project(tenant_id, project)

    def list_procedure_specs(self, tenant_id: str, project_number: str) -> list[dict[str, Any]]:
        project_number = normalize_project_number(project_number)
        return self._query_by_prefix(
            self.tables.procedure_specs,
            tenant_id,
            f"PROJECT#{project_number}#PROC#",
        )

    def get_procedure_spec(
        self,
        tenant_id: str,
        project_number: str,
        procedure_code: str,
    ) -> dict[str, Any] | None:
        return self._get_item(
            self.tables.procedure_specs,
            {
                "tenant_id": tenant_id,
                "sort_key": _procedure_spec_sort_key(project_number, procedure_code),
            },
        )

    def save_procedure_spec(
        self,
        tenant_id: str,
        project_number: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        project_number = normalize_project_number(project_number)
        procedure_code = normalize_procedure_code(
            payload.get("procedure_code") or payload.get("treatment_code")
        )
        existing = self.get_procedure_spec(tenant_id, project_number, procedure_code) or {}
        now = utc_now_iso()
        draft_spec = payload.get("draft_spec") or payload.get("spec") or {}
        if not isinstance(draft_spec, dict):
            raise ValueError("draft_spec must be a JSON object")
        validate_procedure_spec_body(draft_spec, require_publishable=False)
        procedure_name = str(payload.get("procedure_name") or existing.get("procedure_name") or "").strip()
        if not procedure_name:
            raise ValueError("procedure_name is required")

        item = {
            "tenant_id": tenant_id,
            "sort_key": _procedure_spec_sort_key(project_number, procedure_code),
            "project_number": project_number,
            "project_id": payload.get("project_id") or existing.get("project_id"),
            "procedure_code": procedure_code,
            "procedure_name": procedure_name,
            "description": str(payload.get("description") or existing.get("description") or "").strip(),
            "status": normalize_status(
                payload.get("status", existing.get("status")),
                valid=VALID_SPEC_STATUSES,
                default="draft",
            ),
            "current_version": int(existing.get("current_version") or 0),
            "draft_spec": draft_spec,
            "current_spec_hash": existing.get("current_spec_hash"),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        self._put_item(self.tables.procedure_specs, item)
        return item

    def publish_procedure_spec(
        self,
        tenant_id: str,
        project_number: str,
        procedure_code: str,
        *,
        published_by: str,
    ) -> dict[str, Any]:
        project_number = normalize_project_number(project_number)
        procedure_code = normalize_procedure_code(procedure_code)
        item = self.get_procedure_spec(tenant_id, project_number, procedure_code)
        if not item:
            raise LookupError("procedure_spec_not_found")
        draft_spec = item.get("draft_spec")
        if not isinstance(draft_spec, dict):
            raise ValueError("draft_spec must be present before publishing")
        validate_procedure_spec_body(draft_spec, require_publishable=True)

        version = int(item.get("current_version") or 0) + 1
        now = utc_now_iso()
        digest = spec_hash(draft_spec)
        version_item = {
            "tenant_id": tenant_id,
            "sort_key": _procedure_spec_version_sort_key(project_number, procedure_code, version),
            "project_number": project_number,
            "procedure_code": procedure_code,
            "version": version,
            "spec": draft_spec,
            "spec_hash": digest,
            "published_at": now,
            "published_by": published_by,
            "immutable": True,
        }
        self._put_item(self.tables.procedure_spec_versions, version_item)

        item["status"] = "active"
        item["current_version"] = version
        item["current_spec_hash"] = digest
        item["updated_at"] = now
        self._put_item(self.tables.procedure_specs, item)
        return {**item, "published_version": version_item}

    def list_procedure_spec_versions(
        self,
        tenant_id: str,
        project_number: str,
        procedure_code: str,
    ) -> list[dict[str, Any]]:
        project_number = normalize_project_number(project_number)
        procedure_code = normalize_procedure_code(procedure_code)
        return self._query_by_prefix(
            self.tables.procedure_spec_versions,
            tenant_id,
            f"PROJECT#{project_number}#PROC#{procedure_code}#VERSION#",
        )

    def get_current_procedure_spec_version(
        self,
        tenant_id: str,
        project_number: str,
        procedure_code: str,
    ) -> dict[str, Any] | None:
        spec_item = self.get_procedure_spec(tenant_id, project_number, procedure_code)
        if not spec_item or spec_item.get("status") != "active":
            return None
        version = int(spec_item.get("current_version") or 0)
        if version <= 0:
            return None
        version_item = self._get_item(
            self.tables.procedure_spec_versions,
            {
                "tenant_id": tenant_id,
                "sort_key": _procedure_spec_version_sort_key(project_number, procedure_code, version),
            },
        )
        if not version_item:
            return None
        return {**version_item, "procedure_spec": spec_item}

    def put_classification_run(self, tenant_id: str, item: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        run_id = str(item.get("run_id") or uuid.uuid4())
        project_number = normalize_project_number(item.get("project_number"))
        stored = {
            "tenant_id": tenant_id,
            "sort_key": f"RUN#{run_id}",
            "gsi1pk": f"TENANT#{tenant_id}#PROJECT#{project_number}",
            "gsi1sk": item.get("created_at") or now,
            "run_id": run_id,
            "project_number": project_number,
            "procedure_code": normalize_procedure_code(item.get("procedure_code")),
            "spec_version": item.get("spec_version"),
            "spec_hash": item.get("spec_hash"),
            "document_hash": item.get("document_hash"),
            "document_storage_uri": item.get("document_storage_uri"),
            "storage_policy_used": normalize_storage_mode(item.get("storage_policy_used")),
            "external_document_id": item.get("external_document_id"),
            "file_name": item.get("file_name"),
            "metadata": item.get("metadata") or {},
            "status": item.get("status") or "completed",
            "result_code": item.get("result_code"),
            "created_at": item.get("created_at") or now,
            "updated_at": now,
        }
        self._put_item(self.tables.classification_runs, stored)
        return stored

    def get_classification_run(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        return self._get_item(
            self.tables.classification_runs,
            {"tenant_id": tenant_id, "sort_key": f"RUN#{run_id}"},
        )

    def get_classification_result(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        return self._get_item(
            self.tables.classification_results,
            {"tenant_id": tenant_id, "sort_key": f"RUN#{run_id}#RESULT"},
        )

    def list_project_classification_runs(self, tenant_id: str, project_number: str) -> list[dict[str, Any]]:
        if self.client is None:
            raise RuntimeError("cloud_store_not_configured")
        response = self.client.query(
            TableName=self.tables.classification_runs,
            IndexName="project_created_at_index",
            KeyConditionExpression="#gpk = :gpk",
            ExpressionAttributeNames={"#gpk": "gsi1pk"},
            ExpressionAttributeValues={
                ":gpk": _to_dynamodb_value(
                    f"TENANT#{tenant_id}#PROJECT#{normalize_project_number(project_number)}"
                )
            },
            ScanIndexForward=False,
            Limit=100,
        )
        return [_from_dynamodb_item(item) for item in response.get("Items", [])]

    def put_classification_result(self, tenant_id: str, item: dict[str, Any]) -> dict[str, Any]:
        run_id = str(item.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        now = utc_now_iso()
        stored = {
            "tenant_id": tenant_id,
            "sort_key": f"RUN#{run_id}#RESULT",
            "run_id": run_id,
            "indexes": item.get("indexes") or {},
            "index_details": sanitize_index_details_for_storage(item.get("index_details")),
            "result_code": item.get("result_code"),
            "project_number": item.get("project_number"),
            "procedure_code": item.get("procedure_code"),
            "external_document_id": item.get("external_document_id"),
            "file_name": item.get("file_name"),
            "document_hash": item.get("document_hash"),
            "document_storage_uri": item.get("document_storage_uri"),
            "storage_policy_used": normalize_storage_mode(item.get("storage_policy_used")),
            "status": item.get("status"),
            "spec_version": item.get("spec_version"),
            "spec_hash": item.get("spec_hash"),
            "confidence_summary": item.get("confidence_summary") or {},
            "created_at": item.get("created_at") or now,
            "updated_at": now,
        }
        self._put_item(self.tables.classification_results, stored)
        return stored

    def put_audit_log(self, tenant_id: str, item: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        request_id = str(item.get("request_id") or uuid.uuid4())
        stored = {
            "tenant_id": tenant_id,
            "sort_key": f"AUDIT#{now}#{request_id}",
            "request_id": request_id,
            "api_key_id": item.get("api_key_id"),
            "api_key_hash_prefix": item.get("api_key_hash_prefix"),
            "project_number": item.get("project_number"),
            "procedure_code": item.get("procedure_code"),
            "document_hash": item.get("document_hash"),
            "action": item.get("action"),
            "status": item.get("status"),
            "duration_ms": item.get("duration_ms"),
            "storage_policy_used": normalize_storage_mode(item.get("storage_policy_used")),
            "error_code": item.get("error_code"),
            "created_at": now,
        }
        self._put_item(self.tables.audit_logs, stored)
        return stored

    def _normalize_tenant_item(self, item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        normalized["storage_mode"] = normalize_storage_mode(normalized.get("storage_mode"))
        normalized["status"] = normalize_status(
            normalized.get("status"),
            valid=VALID_TENANT_STATUSES,
            default="active",
        )
        if "customer_name" not in normalized and "tenant_name" in normalized:
            normalized["customer_name"] = normalized.get("tenant_name")
        if "customer_number" not in normalized:
            normalized["customer_number"] = normalized.get("customer_id") or normalized.get("tenant_id")
        if "customer_id" not in normalized:
            normalized["customer_id"] = normalized.get("customer_number") or normalized.get("tenant_id")
        return normalized

    def _touch_api_key(self, api_key_hash_prefix: str) -> None:
        if self.client is None:
            return
        try:
            self.client.update_item(
                TableName=self.tables.api_keys,
                Key={"api_key_hash_prefix": _to_dynamodb_value(api_key_hash_prefix)},
                UpdateExpression="SET last_used_at = :now",
                ExpressionAttributeValues={":now": _to_dynamodb_value(utc_now_iso())},
            )
        except Exception:
            return

    def _get_item(self, table_name: str, key: dict[str, Any]) -> dict[str, Any] | None:
        if self.client is None:
            raise RuntimeError("cloud_store_not_configured")
        response = self.client.get_item(
            TableName=table_name,
            Key={name: _to_dynamodb_value(value) for name, value in key.items()},
        )
        item = response.get("Item")
        return _from_dynamodb_item(item) if item else None

    def _put_item(self, table_name: str, item: dict[str, Any]) -> None:
        if self.client is None:
            raise RuntimeError("cloud_store_not_configured")
        self.client.put_item(TableName=table_name, Item=_to_dynamodb_item(item))

    def _query_by_prefix(self, table_name: str, tenant_id: str, prefix: str) -> list[dict[str, Any]]:
        if self.client is None:
            raise RuntimeError("cloud_store_not_configured")
        response = self.client.query(
            TableName=table_name,
            KeyConditionExpression="#tenant = :tenant AND begins_with(#sort, :prefix)",
            ExpressionAttributeNames={"#tenant": "tenant_id", "#sort": "sort_key"},
            ExpressionAttributeValues={
                ":tenant": _to_dynamodb_value(tenant_id),
                ":prefix": _to_dynamodb_value(prefix),
            },
        )
        return [_from_dynamodb_item(item) for item in response.get("Items", [])]


def _procedure_spec_sort_key(project_number: str, procedure_code: str) -> str:
    return (
        f"PROJECT#{normalize_project_number(project_number)}"
        f"#PROC#{normalize_procedure_code(procedure_code)}"
    )


def _procedure_spec_version_sort_key(project_number: str, procedure_code: str, version: int) -> str:
    return f"{_procedure_spec_sort_key(project_number, procedure_code)}#VERSION#{int(version):08d}"


def _to_dynamodb_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _to_dynamodb_value(value) for key, value in item.items() if value is not None}


def _to_dynamodb_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int | float):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": {str(key): _to_dynamodb_value(val) for key, val in value.items() if val is not None}}
    if isinstance(value, list):
        return {"L": [_to_dynamodb_value(item) for item in value]}
    return {"S": str(value)}


def _from_dynamodb_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _from_dynamodb_value(value) for key, value in item.items()}


def _from_dynamodb_value(value: dict[str, Any]) -> Any:
    if "NULL" in value:
        return None
    if "BOOL" in value:
        return bool(value["BOOL"])
    if "N" in value:
        raw = str(value["N"])
        try:
            return int(raw) if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()) else float(raw)
        except ValueError:
            return raw
    if "M" in value:
        return {key: _from_dynamodb_value(val) for key, val in value["M"].items()}
    if "L" in value:
        return [_from_dynamodb_value(item) for item in value["L"]]
    if "S" in value:
        return str(value["S"])
    return None


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _validate_string_list(index: dict[str, Any], field: str, key: str) -> None:
    value = index.get(field)
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError(f"{field} for {key} must be a list")
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} for {key} must contain only strings")


def _validate_examples(value: Any, key: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError(f"examples for {key} must be a list")
    for example in value:
        if not isinstance(example, dict):
            raise ValueError(f"examples for {key} must contain objects")
        if "text" in example and not isinstance(example["text"], str):
            raise ValueError(f"example text for {key} must be a string")
        expected = example.get("expected_result")
        if expected is not None and expected not in {0, 1, "0", "1"}:
            raise ValueError(f"example expected_result for {key} must be 0 or 1")
