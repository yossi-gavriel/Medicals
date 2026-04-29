from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.extraction_engine.spec import Specification


class ExtractionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=256)
    document_text: str = Field(min_length=1)
    spec: Specification
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize(self) -> ExtractionRunRequest:
        self.document_id = self.document_id.strip()
        self.document_text = self.document_text.strip()
        if not self.document_id:
            raise ValueError("document_id must not be blank")
        if not self.document_text:
            raise ValueError("document_text must not be blank")
        return self


class ExtractionAuditEntryView(BaseModel):
    document_id: str
    treatment_code: str
    field_name: str
    value: Any
    confidence: float
    evidence: list[str]
    reason: str
    error: dict[str, str] | None = None


class ComplianceRuleResultView(BaseModel):
    rule_id: str
    description: str
    field: str
    operator: str
    expected: Any = None
    actual: Any = None
    severity: str | None = None
    reason: str
    recommended_action: str
    evidence: list[str]


class ComplianceResultView(BaseModel):
    document_id: str
    treatment_code: str
    status: str
    recommended_action: str
    failed_rules: list[ComplianceRuleResultView] = Field(default_factory=list)
    passed_rules: list[ComplianceRuleResultView] = Field(default_factory=list)
    insufficient_data_rules: list[ComplianceRuleResultView] = Field(default_factory=list)
    manual_review_rules: list[ComplianceRuleResultView] = Field(default_factory=list)


class ExtractionRunResponse(BaseModel):
    run_id: str | None = None
    document_id: str
    spec_version: str
    spec_hash: str | None = None
    rows: list[dict[str, Any]]
    audit: list[ExtractionAuditEntryView]
    compliance: list[ComplianceResultView] = Field(default_factory=list)
    masked: bool = False
    pii_masked_count: int = 0


__all__ = [
    "ComplianceResultView",
    "ComplianceRuleResultView",
    "ExtractionAuditEntryView",
    "ExtractionRunRequest",
    "ExtractionRunResponse",
]
