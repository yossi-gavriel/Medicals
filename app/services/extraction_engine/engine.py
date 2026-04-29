from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.extraction_engine.preprocessor import normalize_whitespace, split_sentences
from app.services.extraction_engine.rule_extractors import (
    ExtractionRecord,
    LLMRuleResolver,
    extract_rule,
)
from app.services.extraction_engine.spec import Specification, Treatment
from app.services.medical_classifier.pii_cleaner import mask_israeli_ids

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionAuditEntry:
    document_id: str
    treatment_code: str
    field_name: str
    value: Any
    confidence: float
    evidence: list[str]
    reason: str
    error: dict[str, str] | None = None


@dataclass(frozen=True)
class ExtractionResult:
    document_id: str
    spec_version: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    audit: list[ExtractionAuditEntry] = field(default_factory=list)
    masked: bool = False
    pii_masked_count: int = 0


class ExtractionEngine:
    """Orchestrates JSON-spec-driven extraction over a single document.

    The spec is the only source of output columns. The engine does not invent
    fields, treatment codes, or extraction goals; it only iterates the spec.
    """

    def __init__(
        self,
        *,
        llm_resolver: LLMRuleResolver | None = None,
        mask_pii: bool = False,
    ) -> None:
        self.llm_resolver = llm_resolver
        self.mask_pii = mask_pii

    def run(
        self,
        *,
        document_id: str,
        document_text: str,
        spec: Specification,
    ) -> ExtractionResult:
        masked_text, masked_count = self._prepare_text(document_text)
        sentences = split_sentences(masked_text)

        rows: list[dict[str, Any]] = []
        audit: list[ExtractionAuditEntry] = []

        for treatment in spec.treatments:
            row, treatment_audit = self._run_treatment(
                document_id=document_id,
                treatment=treatment,
                sentences=sentences,
            )
            rows.append(row)
            audit.extend(treatment_audit)

        return ExtractionResult(
            document_id=document_id,
            spec_version=spec.version,
            rows=rows,
            audit=audit,
            masked=self.mask_pii,
            pii_masked_count=masked_count,
        )

    def _prepare_text(self, document_text: str) -> tuple[str, int]:
        cleaned = normalize_whitespace(document_text)
        if not self.mask_pii or not cleaned:
            return cleaned, 0
        masked, count = mask_israeli_ids(cleaned)
        if count:
            logger.info("Masked %d possible ID values before extraction", count)
        return masked, count

    def _run_treatment(
        self,
        *,
        document_id: str,
        treatment: Treatment,
        sentences: list[str],
    ) -> tuple[dict[str, Any], list[ExtractionAuditEntry]]:
        row: dict[str, Any] = {
            "document_id": document_id,
            "treatment_code": treatment.treatment_code,
        }
        audit: list[ExtractionAuditEntry] = []

        for rule in treatment.rules:
            record = extract_rule(rule, sentences, self.llm_resolver)
            row[rule.field_name] = record.value
            audit.append(
                ExtractionAuditEntry(
                    document_id=document_id,
                    treatment_code=treatment.treatment_code,
                    field_name=rule.field_name,
                    value=record.value,
                    confidence=record.confidence,
                    evidence=list(record.evidence),
                    reason=record.reason,
                    error=record.error,
                )
            )
        return row, audit


def build_extraction_engine_from_settings(
    settings,
    *,
    llm_resolver: LLMRuleResolver | None = None,
) -> ExtractionEngine:
    """Construct the engine using values from app settings.

    Reuses the medical classifier's PII flag so operators have one switch.
    """
    return ExtractionEngine(
        llm_resolver=llm_resolver,
        mask_pii=settings.medical_classifier_mask_pii_before_llm,
    )


__all__ = [
    "ExtractionAuditEntry",
    "ExtractionEngine",
    "ExtractionRecord",
    "ExtractionResult",
    "build_extraction_engine_from_settings",
]
