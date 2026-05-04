from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MedicalClassifierRequest(BaseModel):
    procedure_code: str = Field(min_length=1, max_length=128)
    document_text: str = Field(min_length=1)
    document_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def normalize_fields(self) -> "MedicalClassifierRequest":
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
    file_name: str = Field(min_length=1, max_length=256)
    doc_type: int | None = None
    treatment_code: str = Field(min_length=1, max_length=128)
    subject_ind: int | str | None = None
    cleaned_desc: str | None = None
    cleaned_full: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_fields(self) -> "MedicalClassifierDocumentRequest":
        self.file_name = self.file_name.strip()
        self.treatment_code = self.treatment_code.strip().lower()
        if isinstance(self.cleaned_desc, str):
            self.cleaned_desc = self.cleaned_desc.strip() or None
        if isinstance(self.cleaned_full, str):
            self.cleaned_full = self.cleaned_full.strip() or None
        if not self.file_name:
            raise ValueError("file_name must be non-empty")
        if not self.treatment_code:
            raise ValueError("treatment_code must be non-empty")
        if not self.cleaned_full and not self.cleaned_desc:
            raise ValueError("cleaned_full or cleaned_desc must be non-empty")
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
