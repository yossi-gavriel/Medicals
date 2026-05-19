from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import ApiKeyDep, InternalApiKeyDep, resolve_tenant_id
from app.models import MedicalClassifierAuditLog
from app.schemas import (
    MedicalClassifierDocumentRequest,
    MedicalClassifierDocumentResponse,
    MedicalClassifierRequest,
    MedicalClassifierResponse,
)
from app.services.medical_classifier import (
    ProcedureClassificationInput,
    ProcedureClassificationService,
    sanitize_metadata_for_audit,
)

router = APIRouter(tags=["medical-classifier"])
MAX_AUDIT_METADATA_BYTES = 32 * 1024


def get_medical_classifier_service(request: Request) -> ProcedureClassificationService:
    return request.app.state.medical_classifier_service


def _classify(
    *,
    medical_classifier_service: ProcedureClassificationService,
    treatment_code: str,
    document_text: str,
) -> object:
    return medical_classifier_service.classify_document(
        ProcedureClassificationInput(
            treatment_code=treatment_code,
            file_desc=document_text,
            file_full_text=document_text,
        )
    )


def _sha256_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(metadata or {}, ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError):
        return {"_invalid": True}
    if len(encoded) <= MAX_AUDIT_METADATA_BYTES:
        return json.loads(encoded.decode("utf-8"))
    return {
        "_truncated": True,
        "original_size_bytes": len(encoded),
        "limit_bytes": MAX_AUDIT_METADATA_BYTES,
    }


async def _persist_connector_audit(
    session: AsyncSession,
    *,
    request_id: str,
    request: Request,
    payload: MedicalClassifierDocumentRequest,
    document_text: str,
    status: str,
    result_code: int | str | None,
    indexes: dict[str, Any],
    error_code: str | None,
    retryable: bool,
    model_version: str | None,
    duration_ms: int,
) -> None:
    try:
        normalized_result_code = int(result_code) if result_code is not None and str(result_code).isdigit() else None
        audit = MedicalClassifierAuditLog(
            request_id=request_id,
            api_key_id=getattr(request.state, "api_key_id", None),
            tenant_id=resolve_tenant_id(request),
            file_name=payload.file_name or payload.document_id or payload.external_document_id or "unknown",
            doc_type=payload.doc_type,
            treatment_code=payload.treatment_code,
            subject_ind=str(payload.subject_ind) if payload.subject_ind is not None else None,
            document_text_hash=_sha256_or_none(document_text) or "",
            cleaned_desc_hash=_sha256_or_none(payload.cleaned_desc),
            cleaned_full_hash=_sha256_or_none(payload.cleaned_full),
            text_length=len(document_text),
            metadata_json=_safe_metadata(sanitize_metadata_for_audit(payload.metadata)),
            status=status,
            result_code=normalized_result_code,
            indexes_json=indexes,
            error_code=error_code,
            retryable=retryable,
            model_version=model_version,
            duration_ms=duration_ms,
        )
        async with session.begin():
            session.add(audit)
    except Exception:
        # Do not leak document text through exception messages; request context
        # middleware will still capture path/status for operational debugging.
        raise


@router.post("/internal/medical-classifier/classify", response_model=MedicalClassifierResponse)
async def classify_medical_document(
    payload: MedicalClassifierRequest,
    _api_key: InternalApiKeyDep,
    medical_classifier_service: ProcedureClassificationService = Depends(get_medical_classifier_service),
) -> MedicalClassifierResponse:
    try:
        result = _classify(
            medical_classifier_service=medical_classifier_service,
            treatment_code=payload.procedure_code,
            document_text=payload.document_text,
        )
        return MedicalClassifierResponse(
            document_id=payload.document_id,
            procedure_code=payload.procedure_code,
            result_code=result.result_code,
            masked=result.masked,
            model_output={
                "prompt_source": result.prompt_source,
                "used_definition": result.used_definition,
                "idx_results": result.idx_results,
                "index_details": result.index_details,
                "raw": result.raw_model_output,
            },
            error=result.error,
        )
    except Exception as exc:
        return MedicalClassifierResponse(
            document_id=payload.document_id,
            procedure_code=payload.procedure_code,
            result_code=0,
            masked=medical_classifier_service.mask_pii_before_llm,
            model_output={},
            error={"code": "unexpected_error", "message": str(exc)},
        )


@router.post(
    "/v1/medical-classifier/classify-document",
    response_model=MedicalClassifierDocumentResponse,
)
async def classify_connector_document(
    payload: MedicalClassifierDocumentRequest,
    request: Request,
    _api_key: ApiKeyDep,
    medical_classifier_service: ProcedureClassificationService = Depends(get_medical_classifier_service),
    session: AsyncSession = Depends(get_db_session),
) -> MedicalClassifierDocumentResponse:
    started = time.perf_counter()
    document_text = payload.document_text or payload.cleaned_full or payload.cleaned_desc or ""
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    try:
        result = _classify(
            medical_classifier_service=medical_classifier_service,
            treatment_code=payload.treatment_code,
            document_text=document_text,
        )
        error = result.error or {}
        response = MedicalClassifierDocumentResponse(
            status="error" if error else "success",
            result_code=result.result_code,
            indexes=dict(result.idx_results or {}),
            index_details=dict(result.index_details or {}),
            message=error.get("message") if error else None,
            error_code=error.get("code") if error else None,
            retryable=False,
            model_version=getattr(medical_classifier_service.llm_runner, "model", None),
            request_id=request_id,
        )
        await _persist_connector_audit(
            session,
            request_id=request_id,
            request=request,
            payload=payload,
            document_text=document_text,
            status=response.status,
            result_code=response.result_code,
            indexes=response.indexes,
            error_code=response.error_code,
            retryable=response.retryable,
            model_version=response.model_version,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return response
    except Exception:
        response = MedicalClassifierDocumentResponse(
            status="error",
            result_code=9,
            indexes={},
            message="MedicalClassifier backend failed to classify document",
            error_code="unexpected_error",
            retryable=False,
            model_version=None,
            request_id=request_id,
        )
        await _persist_connector_audit(
            session,
            request_id=request_id,
            request=request,
            payload=payload,
            document_text=document_text,
            status=response.status,
            result_code=response.result_code,
            indexes=response.indexes,
            error_code=response.error_code,
            retryable=response.retryable,
            model_version=response.model_version,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return response
