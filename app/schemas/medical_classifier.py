from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MedicalClassifierRequest(BaseModel):
    procedure_code: str = Field(min_length=1, max_length=128)
    document_text: str = Field(min_length=1)
    document_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def normalize_fields(self) -> MedicalClassifierRequest:
        self.procedure_code = self.procedure_code.strip().lower()
        self.document_text = self.document_text.strip()
        if self.document_id is not None:
            stripped = self.document_id.strip()
            self.document_id = stripped or None

        if not self.procedure_code:
            raise ValueError("procedure_code must be non-empty")
        if not self.document_text:
            raise ValueError("document_text must be non-empty")
        return self


class MedicalClassifierResponse(BaseModel):
    class ErrorPayload(BaseModel):
        code: str
        message: str

    document_id: str | None
    procedure_code: str
    result_code: int
    masked: bool
    model_output: dict[str, Any]
    error: ErrorPayload | None


class MedicalClassifierDocumentRequest(BaseModel):
    file_name: str | None = Field(default=None, max_length=256)
    doc_type: int | None = None
    project_number: str | None = Field(default=None, max_length=128)
    procedure_code: str | None = Field(default=None, max_length=128)
    treatment_code: str | None = Field(default=None, max_length=128)
    subject_ind: int | str | None = None
    document_text: str | None = None
    cleaned_desc: str | None = None
    cleaned_full: str | None = None
    source_system: str | None = Field(default=None, max_length=128)
    connector_version: str | None = Field(default=None, max_length=128)
    external_document_id: str | None = Field(default=None, max_length=256)
    storage_preference: Literal["local_only", "cloud", "hybrid"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_fields(self) -> MedicalClassifierDocumentRequest:
        if isinstance(self.file_name, str):
            self.file_name = self.file_name.strip() or None
        if isinstance(self.project_number, str):
            self.project_number = self.project_number.strip() or None
        if isinstance(self.procedure_code, str):
            self.procedure_code = self.procedure_code.strip().lower() or None
        if isinstance(self.treatment_code, str):
            self.treatment_code = self.treatment_code.strip().lower() or None
        resolved_code = self.procedure_code or self.treatment_code
        self.procedure_code = resolved_code
        self.treatment_code = resolved_code
        if isinstance(self.cleaned_desc, str):
            self.cleaned_desc = self.cleaned_desc.strip() or None
        if isinstance(self.cleaned_full, str):
            self.cleaned_full = self.cleaned_full.strip() or None
        if isinstance(self.document_text, str):
            self.document_text = self.document_text.strip() or None
        if isinstance(self.source_system, str):
            self.source_system = self.source_system.strip() or None
        if isinstance(self.connector_version, str):
            self.connector_version = self.connector_version.strip() or None
        if isinstance(self.external_document_id, str):
            self.external_document_id = self.external_document_id.strip() or None
        if not self.treatment_code:
            raise ValueError("procedure_code or treatment_code must be non-empty")
        if not self.cleaned_full and not self.cleaned_desc and not self.document_text:
            raise ValueError("document_text, cleaned_full, or cleaned_desc must be non-empty")
        return self


class MedicalClassifierDocumentResponse(BaseModel):
    status: Literal["success", "error"]
    result_code: int | str | None
    indexes: dict[str, Any] = Field(default_factory=dict)
    index_details: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
    error_code: str | None = None
    retryable: bool = False
    model_version: str | None = None
    request_id: str | None = None
