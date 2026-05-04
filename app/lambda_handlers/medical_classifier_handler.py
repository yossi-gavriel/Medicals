from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.core.settings import Settings
from app.schemas.medical_classifier import MedicalClassifierDocumentRequest
from app.services.medical_classifier import (
    ProcedureClassificationInput,
    ProcedureClassificationService,
    build_generic_fallback_prompt_json,
    build_medical_classifier_llm_runner,
)

logger = logging.getLogger(__name__)

CLASSIFY_PATH = "/v1/medical-classifier/classify-document"
REQUEST_ID_HEADER = "X-Request-ID"

_classifier_service: ProcedureClassificationService | None = None
_dynamodb_client: Any | None = None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = _request_id(event)
    path = _path_from_event(event)
    method = _method_from_event(event)

    if path != CLASSIFY_PATH:
        return _json_response(
            404,
            _error_payload(request_id, "not_found"),
            request_id=request_id,
        )
    if method != "POST":
        return _json_response(
            405,
            _error_payload(request_id, "method_not_allowed"),
            request_id=request_id,
        )

    api_key = _header(event, "X-API-Key")
    api_key_id_hash = _validate_api_key(api_key)
    if api_key_id_hash is None:
        return _json_response(
            401,
            _error_payload(request_id, "invalid_api_key"),
            request_id=request_id,
        )

    try:
        payload_dict = _json_body(event)
        payload = MedicalClassifierDocumentRequest.model_validate(payload_dict)
    except (ValueError, TypeError, ValidationError):
        return _json_response(
            422,
            _error_payload(request_id, "invalid_request"),
            request_id=request_id,
        )

    document_text = payload.cleaned_full or payload.cleaned_desc or ""
    document_hash = _sha256(document_text)

    try:
        result = _get_classifier_service().classify_document(
            ProcedureClassificationInput(
                treatment_code=payload.treatment_code,
                file_desc=document_text,
                file_full_text=document_text,
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
            {
                "request_id": request_id,
                "api_key_id_hash": api_key_id_hash,
                "treatment_code": payload.treatment_code,
                "document_hash": document_hash,
                "result_code": 9,
                "indexes": {},
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

    _safe_write_audit(
        {
            "request_id": request_id,
            "api_key_id_hash": api_key_id_hash,
            "treatment_code": payload.treatment_code,
            "document_hash": document_hash,
            "result_code": int(result.result_code),
            "indexes": indexes,
            "created_at": _utc_now_iso(),
        }
    )

    response_body: dict[str, Any] = {
        "result_code": result.result_code,
        "request_id": request_id,
        "indexes": indexes,
        "index_details": index_details,
    }
    if error_code:
        response_body["error_code"] = error_code
    return _json_response(200, response_body, request_id=request_id)


def _get_classifier_service() -> ProcedureClassificationService:
    global _classifier_service
    if _classifier_service is None:
        settings = Settings()
        _classifier_service = ProcedureClassificationService.from_settings(
            llm_runner=build_medical_classifier_llm_runner(settings),
            settings=settings,
            prompt_provider=build_generic_fallback_prompt_json,
        )
    return _classifier_service


def _validate_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None

    api_key_hash = _sha256(api_key)
    hash_candidates = _csv_env("MEDICAL_CLASSIFIER_API_KEY_HASHES")
    for candidate in hash_candidates:
        if secrets.compare_digest(api_key_hash, candidate):
            return api_key_hash

    if _truthy_env("MEDICAL_CLASSIFIER_ALLOW_PLAINTEXT_API_KEYS"):
        for candidate in _csv_env("MEDICAL_CLASSIFIER_API_KEYS"):
            if secrets.compare_digest(api_key, candidate):
                return api_key_hash

    return None


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


def _safe_write_audit(item: dict[str, Any]) -> None:
    table_name = os.getenv("MEDICAL_CLASSIFIER_AUDIT_TABLE", "").strip()
    if not table_name:
        return
    try:
        _put_audit_item(table_name, item)
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
) -> dict[str, Any]:
    return {
        "result_code": result_code,
        "request_id": request_id,
        "indexes": indexes or {},
        "index_details": index_details or {},
        "error_code": error_code,
    }


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
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reset_caches_for_tests() -> None:
    global _classifier_service, _dynamodb_client
    _classifier_service = None
    _dynamodb_client = None

