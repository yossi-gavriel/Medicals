from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.core.settings import Settings
from app.schemas.medical_classifier import MedicalClassifierDocumentRequest
from app.services.medical_classifier import (
    ProcedureClassificationInput,
    ProcedureClassificationService,
    build_generic_fallback_prompt_json,
    build_medical_classifier_llm_runner,
    build_prompt_json_from_spec_body,
)
from app.services.medical_classifier.cloud_store import (
    ApiKeyContext,
    MedicalClassifierCloudStore,
    MedicalClassifierTableNames,
    normalize_procedure_code,
    normalize_project_number,
    normalize_storage_mode,
    resolve_storage_policy,
    sanitize_index_details_for_storage,
    sha256_text,
    spec_hash,
)
from app.services.medical_classifier.metadata_sanitizer import sanitize_metadata_for_audit

logger = logging.getLogger(__name__)

CLASSIFY_PATH = "/v1/medical-classifier/classify-document"
REQUEST_ID_HEADER = "X-Request-ID"

_classifier_service: ProcedureClassificationService | None = None
_dynamodb_client: Any | None = None
_cloud_store: MedicalClassifierCloudStore | None = None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = _request_id(event)
    path = _path_from_event(event)
    method = _method_from_event(event)

    auth = _authenticate(event)
    if auth is None:
        return _json_response(
            401,
            _error_payload(request_id, "invalid_api_key"),
            request_id=request_id,
        )

    try:
        return _route_request(
            event=event,
            request_id=request_id,
            path=path,
            method=method,
            auth=auth,
        )
    except ValueError as exc:
        return _json_response(
            422,
            _error_payload(request_id, "invalid_request", message=str(exc)),
            request_id=request_id,
        )
    except LookupError as exc:
        return _json_response(
            404,
            _error_payload(request_id, str(exc) or "not_found"),
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning(
            "medical_classifier_request_failed",
            extra={"extra": {"request_id": request_id, "error_type": type(exc).__name__}},
        )
        return _json_response(
            500,
            _error_payload(request_id, "internal_error"),
            request_id=request_id,
        )


def _route_request(
    *,
    event: dict[str, Any],
    request_id: str,
    path: str,
    method: str,
    auth: ApiKeyContext,
) -> dict[str, Any]:
    parts = [part for part in path.strip("/").split("/") if part]

    if parts == ["v1", "customer", "me"] and method == "GET":
        return _json_response(
            200,
            {"customer": _get_cloud_store().public_tenant_view(auth.tenant_id)},
            request_id=request_id,
        )

    if parts == ["v1", "customer", "me", "storage-policy"] and method == "PUT":
        customer = _get_cloud_store().update_tenant_storage_policy(
            auth.tenant_id,
            _json_body(event),
            updated_by=auth.api_key_id,
        )
        return _json_response(
            200,
            {"customer": _get_cloud_store().public_tenant_view(customer["tenant_id"])},
            request_id=request_id,
        )

    if path == CLASSIFY_PATH:
        if method != "POST":
            return _json_response(405, _error_payload(request_id, "method_not_allowed"), request_id=request_id)
        return _handle_classify_document(event, request_id=request_id, auth=auth, legacy_route=True)

    if parts == ["v1", "projects"] and method == "GET":
        return _json_response(200, {"projects": _get_cloud_store().list_projects(auth.tenant_id)}, request_id=request_id)

    if parts == ["v1", "projects"] and method == "POST":
        created_project = _get_cloud_store().put_project(auth.tenant_id, _json_body(event))
        return _json_response(201, {"project": created_project}, request_id=request_id)

    if len(parts) == 3 and parts[:2] == ["v1", "projects"] and method == "GET":
        project_item = _get_cloud_store().get_project(auth.tenant_id, parts[2])
        if not project_item:
            raise LookupError("project_not_found")
        return _json_response(200, {"project": project_item}, request_id=request_id)

    if len(parts) == 3 and parts[:2] == ["v1", "projects"] and method == "PUT":
        payload = _json_body(event)
        payload["project_number"] = parts[2]
        project_item = _get_cloud_store().put_project(auth.tenant_id, payload)
        return _json_response(200, {"project": project_item}, request_id=request_id)

    if (
        len(parts) == 4
        and parts[:2] == ["v1", "projects"]
        and parts[3] == "storage-policy"
        and method == "PATCH"
    ):
        project_item = _get_cloud_store().update_project_storage_policy(
            auth.tenant_id,
            parts[2],
            _json_body(event),
        )
        return _json_response(200, {"project": project_item}, request_id=request_id)

    if len(parts) == 4 and parts[:2] == ["v1", "projects"] and parts[3] == "procedure-specs":
        if method == "GET":
            specs = _get_cloud_store().list_procedure_specs(auth.tenant_id, parts[2])
            return _json_response(200, {"procedure_specs": specs}, request_id=request_id)
        if method == "POST":
            created_spec = _get_cloud_store().save_procedure_spec(auth.tenant_id, parts[2], _json_body(event))
            return _json_response(201, {"procedure_spec": created_spec}, request_id=request_id)

    if len(parts) >= 5 and parts[:2] == ["v1", "projects"] and parts[3] == "procedure-specs":
        project_number = parts[2]
        procedure_code = parts[4]
        if len(parts) == 5 and method == "GET":
            spec_item = _get_cloud_store().get_procedure_spec(auth.tenant_id, project_number, procedure_code)
            if not spec_item:
                raise LookupError("procedure_spec_not_found")
            return _json_response(200, {"procedure_spec": spec_item}, request_id=request_id)
        if len(parts) == 5 and method == "PUT":
            payload = _json_body(event)
            payload["procedure_code"] = procedure_code
            spec = _get_cloud_store().save_procedure_spec(auth.tenant_id, project_number, payload)
            return _json_response(200, {"procedure_spec": spec}, request_id=request_id)
        if len(parts) == 6 and parts[5] == "publish" and method == "POST":
            spec = _get_cloud_store().publish_procedure_spec(
                auth.tenant_id,
                project_number,
                procedure_code,
                published_by=auth.api_key_id,
            )
            return _json_response(200, {"procedure_spec": spec}, request_id=request_id)
        if len(parts) == 6 and parts[5] == "versions" and method == "GET":
            versions = _get_cloud_store().list_procedure_spec_versions(
                auth.tenant_id, project_number, procedure_code
            )
            return _json_response(200, {"versions": versions}, request_id=request_id)
        if len(parts) == 6 and parts[5] == "current" and method == "GET":
            current = _get_cloud_store().get_current_procedure_spec_version(
                auth.tenant_id, project_number, procedure_code
            )
            if not current:
                raise LookupError("current_procedure_spec_not_found")
            return _json_response(200, {"current": current}, request_id=request_id)

    if parts == ["v1", "classification-runs"] and method == "POST":
        return _handle_classify_document(event, request_id=request_id, auth=auth, legacy_route=False)

    if len(parts) == 3 and parts[:2] == ["v1", "classification-runs"] and method == "GET":
        run = _get_cloud_store().get_classification_run(auth.tenant_id, parts[2])
        if not run:
            raise LookupError("classification_run_not_found")
        result = _get_cloud_store().get_classification_result(auth.tenant_id, parts[2])
        return _json_response(
            200,
            {"classification_run": run, "classification_result": result},
            request_id=request_id,
        )

    if (
        len(parts) == 4
        and parts[:2] == ["v1", "projects"]
        and parts[3] == "classification-runs"
        and method == "GET"
    ):
        runs = _get_cloud_store().list_project_classification_runs(auth.tenant_id, parts[2])
        return _json_response(200, {"classification_runs": runs}, request_id=request_id)

    return _json_response(404, _error_payload(request_id, "not_found"), request_id=request_id)


def _handle_classify_document(
    event: dict[str, Any],
    *,
    request_id: str,
    auth: ApiKeyContext,
    legacy_route: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload_dict = _json_body(event)
        payload = MedicalClassifierDocumentRequest.model_validate(payload_dict)
    except (ValueError, TypeError, ValidationError):
        return _json_response(
            422,
            _error_payload(request_id, "invalid_request"),
            request_id=request_id,
        )

    document_text = payload.document_text or payload.cleaned_full or payload.cleaned_desc or ""
    document_hash = sha256_text(document_text)
    project_number = payload.project_number
    procedure_code = payload.procedure_code or payload.treatment_code or ""
    tenant = _get_cloud_store().get_tenant(auth.tenant_id) or {"storage_mode": "local_only"}
    project_item = None
    storage_policy_used = normalize_storage_mode(tenant.get("storage_mode")) or "local_only"
    active_spec = None
    prompt_json = None
    spec_version = None
    active_spec_hash = None

    if project_number:
        project_item = _get_cloud_store().get_project(auth.tenant_id, project_number)
        project_storage_override = (
            project_item.get("default_storage_mode_override") if project_item else None
        )
        storage_policy_used = resolve_storage_policy(
            tenant_storage_mode=tenant.get("storage_mode"),
            project_storage_mode_override=project_storage_override,
            request_storage_preference=payload.storage_preference,
        )
        active_spec = _get_cloud_store().get_current_procedure_spec_version(
            auth.tenant_id,
            project_number,
            procedure_code,
        )
        if not active_spec:
            return _classification_error_response(
                request_id,
                "current_procedure_spec_not_found",
                status_code=404,
            )
        spec = active_spec.get("spec")
        if not isinstance(spec, dict):
            return _classification_error_response(request_id, "invalid_procedure_spec", status_code=500)
        prompt_json = build_prompt_json_from_spec_body(spec)
        spec_version = active_spec.get("version")
        active_spec_hash = active_spec.get("spec_hash") or spec_hash(spec)
    elif not legacy_route:
        return _classification_error_response(request_id, "project_number_required", status_code=422)

    try:
        result = _get_classifier_service().classify_document(
            ProcedureClassificationInput(
                treatment_code=procedure_code,
                file_desc=document_text,
                file_full_text=document_text,
                prompt_json=prompt_json,
                prompt_source="procedure_spec" if prompt_json is not None else None,
            )
        )
    except Exception as exc:
        logger.warning(
            "medical_classifier_classification_failed",
            extra={
                "extra": {
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                }
            },
        )
        _safe_write_audit(
            auth.tenant_id,
            {
                "request_id": request_id,
                "api_key_id": auth.api_key_id,
                "api_key_hash_prefix": auth.api_key_hash_prefix,
                "project_number": project_number,
                "procedure_code": procedure_code,
                "document_hash": document_hash,
                "action": "classify_document",
                "status": "error",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "storage_policy_used": storage_policy_used,
                "error_code": "classifier_exception",
                "created_at": _utc_now_iso(),
            }
        )
        return _json_response(
            500,
            _error_payload(
                request_id,
                "classifier_exception",
                result_code=9,
                indexes={},
                index_details={},
            ),
            request_id=request_id,
        )

    indexes = dict(result.idx_results or {})
    index_details = dict(result.index_details or {})
    error = result.error if isinstance(result.error, dict) else None
    error_code = None
    if error:
        raw_code = error.get("code")
        error_code = str(raw_code) if raw_code else "classification_error"

    run_id = str(uuid.uuid4())
    status = "error" if error_code else "success"
    if project_number:
        _safe_write_classification_records(
            auth=auth,
            run_id=run_id,
            project_number=project_number,
            procedure_code=procedure_code,
            spec_version=spec_version,
            spec_hash_value=active_spec_hash,
            document_hash=document_hash,
            document_storage_uri=None,
            storage_policy_used=storage_policy_used,
            external_document_id=payload.external_document_id,
            file_name=payload.file_name,
            metadata=sanitize_metadata_for_audit(
                {
                    **payload.metadata,
                    "source_system": payload.source_system,
                    "connector_version": payload.connector_version,
                    "external_document_id": payload.external_document_id,
                }
            ),
            status=status,
            result_code=int(result.result_code),
            indexes=indexes,
            index_details=index_details,
        )
    _safe_write_audit(
        auth.tenant_id,
        {
            "request_id": request_id,
            "api_key_id": auth.api_key_id,
            "api_key_hash_prefix": auth.api_key_hash_prefix,
            "project_number": project_number,
            "procedure_code": procedure_code,
            "document_hash": document_hash,
            "action": "classify_document",
            "status": status,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "storage_policy_used": storage_policy_used,
            "error_code": error_code,
            "created_at": _utc_now_iso(),
        }
    )

    response_body: dict[str, Any] = {
        "result_code": result.result_code,
        "request_id": request_id,
        "indexes": indexes,
        "index_details": index_details,
        "run_id": run_id if project_number else None,
        "spec_version": spec_version,
        "spec_hash": active_spec_hash,
        "storage_policy_used": storage_policy_used,
        "document_storage_uri": None,
    }
    if error_code:
        response_body["error_code"] = error_code
    return _json_response(200, response_body, request_id=request_id)


def _get_classifier_service() -> ProcedureClassificationService:
    global _classifier_service
    if _classifier_service is None:
        _hydrate_lambda_secrets()
        settings = Settings()
        _classifier_service = ProcedureClassificationService.from_settings(
            llm_runner=build_medical_classifier_llm_runner(settings),
            settings=settings,
            prompt_provider=build_generic_fallback_prompt_json,
        )
    return _classifier_service


def _get_cloud_store() -> MedicalClassifierCloudStore:
    global _cloud_store
    if _cloud_store is None:
        tables = MedicalClassifierTableNames.from_env()
        client = _get_dynamodb_client() if tables.api_keys or tables.has_project_spec_storage else None
        _cloud_store = MedicalClassifierCloudStore(client=client, tables=tables)
    return _cloud_store


def _authenticate(event: dict[str, Any]) -> ApiKeyContext | None:
    return _get_cloud_store().resolve_api_key(_header(event, "X-API-Key"))


def _validate_api_key(api_key: str | None) -> str | None:
    auth = _get_cloud_store().resolve_api_key(api_key)
    return auth.api_key_hash if auth else None


def _json_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if raw_body is None:
        raise ValueError("missing body")
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(str(raw_body)).decode("utf-8")
    parsed = json.loads(str(raw_body))
    if not isinstance(parsed, dict):
        raise ValueError("body must be a JSON object")
    return parsed


def _safe_write_classification_records(
    *,
    auth: ApiKeyContext,
    run_id: str,
    project_number: str,
    procedure_code: str,
    spec_version: Any,
    spec_hash_value: Any,
    document_hash: str,
    document_storage_uri: str | None,
    storage_policy_used: str,
    external_document_id: str | None,
    file_name: str | None,
    metadata: dict[str, Any],
    status: str,
    result_code: int,
    indexes: dict[str, Any],
    index_details: dict[str, Any],
) -> None:
    try:
        store = _get_cloud_store()
        store.put_classification_run(
            auth.tenant_id,
            {
                "run_id": run_id,
                "project_number": normalize_project_number(project_number),
                "procedure_code": normalize_procedure_code(procedure_code),
                "spec_version": spec_version,
                "spec_hash": spec_hash_value,
                "document_hash": document_hash,
                "document_storage_uri": document_storage_uri,
                "storage_policy_used": storage_policy_used,
                "external_document_id": external_document_id,
                "file_name": file_name,
                "metadata": metadata,
                "status": status,
                "result_code": result_code,
            },
        )
        store.put_classification_result(
            auth.tenant_id,
            {
                "run_id": run_id,
                "indexes": indexes,
                "index_details": sanitize_index_details_for_storage(index_details),
                "result_code": result_code,
                "project_number": normalize_project_number(project_number),
                "procedure_code": normalize_procedure_code(procedure_code),
                "document_hash": document_hash,
                "document_storage_uri": document_storage_uri,
                "storage_policy_used": storage_policy_used,
                "external_document_id": external_document_id,
                "file_name": file_name,
                "status": status,
                "spec_version": spec_version,
                "spec_hash": spec_hash_value,
            },
        )
    except Exception as exc:
        logger.warning(
            "medical_classifier_result_write_failed",
            extra={"extra": {"run_id": run_id, "error_type": type(exc).__name__}},
        )


def _safe_write_audit(tenant_id: str, item: dict[str, Any]) -> None:
    legacy_audit_table = os.getenv("MEDICAL_CLASSIFIER_AUDIT_TABLE", "").strip()
    if legacy_audit_table and not os.getenv("MEDICAL_CLASSIFIER_AUDIT_LOGS_TABLE", "").strip():
        try:
            _put_audit_item(legacy_audit_table, {"tenant_id": tenant_id, **item})
        except Exception as exc:
            logger.warning(
                "medical_classifier_audit_write_failed",
                extra={"extra": {"request_id": item.get("request_id"), "error_type": type(exc).__name__}},
            )
        return
    if not _get_cloud_store().tables.audit_logs:
        return
    try:
        _get_cloud_store().put_audit_log(tenant_id, item)
    except Exception as exc:
        logger.warning(
            "medical_classifier_audit_write_failed",
            extra={
                "extra": {
                    "request_id": item.get("request_id"),
                    "error_type": type(exc).__name__,
                }
            },
        )


def _classification_error_response(
    request_id: str,
    error_code: str,
    *,
    status_code: int,
) -> dict[str, Any]:
    return _json_response(
        status_code,
        _error_payload(request_id, error_code, result_code=9, indexes={}, index_details={}),
        request_id=request_id,
    )


def _hydrate_lambda_secrets() -> None:
    parameter_name = os.getenv("MEDICAL_CLASSIFIER_LLM_API_KEY_SSM_PARAMETER_NAME", "").strip()
    if not parameter_name or os.getenv("MEDICAL_CLASSIFIER_LLM_API_KEY"):
        return
    try:
        client = _get_ssm_client()
        response = client.get_parameter(Name=parameter_name, WithDecryption=True)
        value = str(response.get("Parameter", {}).get("Value") or "").strip()
        if value:
            os.environ["MEDICAL_CLASSIFIER_LLM_API_KEY"] = value
    except Exception as exc:
        logger.warning(
            "medical_classifier_secret_load_failed",
            extra={"extra": {"error_type": type(exc).__name__}},
        )


def _get_ssm_client() -> Any:
    import boto3

    return boto3.client("ssm")


def _put_audit_item(table_name: str, item: dict[str, Any]) -> None:
    _get_dynamodb_client().put_item(
        TableName=table_name,
        Item={key: _to_dynamodb_value(value) for key, value in item.items()},
    )


def _get_dynamodb_client() -> Any:
    global _dynamodb_client
    if _dynamodb_client is None:
        import boto3

        _dynamodb_client = boto3.client("dynamodb")
    return _dynamodb_client


def _to_dynamodb_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int | float):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": {str(key): _to_dynamodb_value(val) for key, val in value.items()}}
    if isinstance(value, list):
        return {"L": [_to_dynamodb_value(item) for item in value]}
    return {"S": str(value)}


def _error_payload(
    request_id: str,
    error_code: str,
    *,
    result_code: int = 9,
    indexes: dict[str, Any] | None = None,
    index_details: dict[str, Any] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    payload = {
        "result_code": result_code,
        "request_id": request_id,
        "indexes": indexes or {},
        "index_details": index_details or {},
        "error_code": error_code,
    }
    if message:
        payload["message"] = message
    return payload


def _json_response(status_code: int, body: dict[str, Any], *, request_id: str) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            REQUEST_ID_HEADER: request_id,
        },
        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    }


def _request_id(event: dict[str, Any]) -> str:
    incoming = _header(event, REQUEST_ID_HEADER)
    if incoming and len(incoming) <= 64:
        return incoming
    return str(uuid.uuid4())


def _header(event: dict[str, Any], name: str) -> str | None:
    headers = event.get("headers") or {}
    if not isinstance(headers, dict):
        return None
    lower_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower_name and value is not None:
            return str(value)
    return None


def _path_from_event(event: dict[str, Any]) -> str:
    raw_path = event.get("rawPath")
    if isinstance(raw_path, str):
        return raw_path
    path = event.get("path")
    if isinstance(path, str):
        return path
    return ""


def _method_from_event(event: dict[str, Any]) -> str:
    request_context = event.get("requestContext")
    if isinstance(request_context, dict):
        http = request_context.get("http")
        if isinstance(http, dict):
            method = http.get("method")
            if isinstance(method, str):
                return method.upper()
    method = event.get("httpMethod")
    return str(method or "").upper()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _reset_caches_for_tests() -> None:
    global _classifier_service, _dynamodb_client, _cloud_store
    _classifier_service = None
    _dynamodb_client = None
    _cloud_store = None
