from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ClassifyAsyncRequest(BaseModel):
    procedure_code: str = Field(min_length=1, max_length=128)
    document_text: str = Field(min_length=1, max_length=2_000_000)
    document_id: str | None = Field(default=None, max_length=256)
    source_system: str | None = Field(default=None, max_length=128)
    callback_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize(self) -> "ClassifyAsyncRequest":
        self.procedure_code = self.procedure_code.strip().lower()
        self.document_text = self.document_text.strip()
        if self.document_id is not None:
            self.document_id = self.document_id.strip() or None
        if self.source_system is not None:
            self.source_system = self.source_system.strip() or None
        if not self.procedure_code:
            raise ValueError("procedure_code must be non-empty")
        if not self.document_text:
            raise ValueError("document_text must be non-empty")
        return self


class ClassifyAsyncAck(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    status: str
    deduplicated: bool = False
    poll_url: str


class ClassifyBatchRequest(BaseModel):
    items: list[ClassifyAsyncRequest] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ensure_unique_document_ids(self) -> ClassifyBatchRequest:
        seen: set[str] = set()
        for item in self.items:
            if item.document_id and item.document_id in seen:
                raise ValueError(f"duplicate document_id within batch: {item.document_id}")
            if item.document_id:
                seen.add(item.document_id)
        return self


class ClassifyBatchAck(BaseModel):
    batch_id: uuid.UUID
    submitted: int
    deduplicated: int
    items: list[ClassifyAsyncAck]
    poll_url: str


class BatchStatusCounts(BaseModel):
    total: int
    pending: int
    running: int
    done: int
    failed: int


class BatchStatusView(BaseModel):
    batch_id: uuid.UUID
    counts: BatchStatusCounts
    items: list[ClassificationRunView]


class ClassificationRunView(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    status: str
    procedure_code: str
    attempt: int
    max_attempts: int
    result_code: int | None
    idx_results: dict[str, int] | None
    prompt_source: str | None
    used_definition: bool | None
    masked: bool
    pii_masked_count: int
    llm_provider: str | None
    llm_model: str | None
    latency_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error: dict[str, Any] | None
    raw_model_output: dict[str, Any] | None = None

    @classmethod
    def from_model(cls, run: Any, *, include_raw: bool = False) -> "ClassificationRunView":
        return cls(
            job_id=run.job_id,
            document_id=run.document_id,
            status=run.status,
            procedure_code=run.procedure_code,
            attempt=run.attempt,
            max_attempts=run.max_attempts,
            result_code=run.result_code,
            idx_results=run.idx_results,
            prompt_source=run.prompt_source,
            used_definition=run.used_definition,
            masked=run.masked,
            pii_masked_count=run.pii_masked_count,
            llm_provider=run.llm_provider,
            llm_model=run.llm_model,
            latency_ms=run.latency_ms,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error=run.error,
            raw_model_output=run.raw_model_output if include_raw else None,
        )


BatchStatusView.model_rebuild()
