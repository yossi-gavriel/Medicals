from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.settings import Settings
from app.services.medical_classifier.llm_runner import JsonPromptRunner
from app.services.medical_classifier.pii_cleaner import mask_israeli_ids
from app.services.medical_classifier.procedure_definition_loader import ProcedureDefinitionLoader
from app.services.medical_classifier.procedure_prompt_builder import build_prompt_json_from_definition

logger = logging.getLogger(__name__)

PromptProvider = Callable[[str], Mapping[str, object] | None]


@dataclass(frozen=True)
class ProcedureClassificationInput:
    treatment_code: str
    file_desc: str = ""
    file_full_text: str = ""


@dataclass(frozen=True)
class ProcedureClassificationResult:
    treatment_code: str
    prompt_source: str
    used_definition: bool
    result_code: int
    masked: bool
    idx_results: dict[str, int]
    raw_model_output: dict[str, dict[str, Any]]
    error: dict[str, Any] | None
    masked_file_desc: str
    masked_file_full_text: str


def _coerce_result_code(response: Mapping[str, Any] | Any) -> int:
    raw: Any = response
    if isinstance(response, Mapping):
        raw = response.get("result_code")
    elif hasattr(response, "result_code"):
        raw = getattr(response, "result_code")
    return 1 if str(raw).strip() == "1" else 0


def _derive_overall_result_code(idx_results: Mapping[str, int]) -> int:
    if not idx_results:
        return 0
    return 1 if all(value == 1 for value in idx_results.values()) else 0


class ProcedureClassificationService:
    def __init__(
        self,
        *,
        llm_runner: JsonPromptRunner,
        definitions_path: str | Path | None = None,
        mask_pii_before_llm: bool = True,
        prompt_provider: PromptProvider | None = None,
    ) -> None:
        self.llm_runner = llm_runner
        self.mask_pii_before_llm = mask_pii_before_llm
        self.prompt_provider = prompt_provider
        path_str = str(definitions_path) if definitions_path else None
        self.definition_loader = ProcedureDefinitionLoader(path_str)
        self.procedure_definitions = self.definition_loader.load()

    @classmethod
    def from_settings(
        cls,
        *,
        llm_runner: JsonPromptRunner,
        settings: Settings,
        prompt_provider: PromptProvider | None = None,
    ) -> "ProcedureClassificationService":
        return cls(
            llm_runner=llm_runner,
            definitions_path=settings.medical_classifier_procedure_definitions_path,
            mask_pii_before_llm=settings.medical_classifier_mask_pii_before_llm,
            prompt_provider=prompt_provider,
        )

    def classify_document(self, document: ProcedureClassificationInput) -> ProcedureClassificationResult:
        prompt_json, prompt_source, used_definition = self._resolve_prompt_json(document.treatment_code)
        masked_desc = self._prepare_text(document.file_desc)
        masked_full = self._prepare_text(document.file_full_text or document.file_desc)
        idx_results, raw_model_output, error = self._run_prompt_json(prompt_json, masked_desc, masked_full)

        return ProcedureClassificationResult(
            treatment_code=document.treatment_code,
            prompt_source=prompt_source,
            used_definition=used_definition,
            result_code=_derive_overall_result_code(idx_results),
            masked=self.mask_pii_before_llm,
            idx_results=idx_results,
            raw_model_output=raw_model_output,
            error=error,
            masked_file_desc=masked_desc,
            masked_file_full_text=masked_full,
        )

    def _resolve_prompt_json(self, treatment_code: str) -> tuple[dict[str, object], str, bool]:
        definition = self.procedure_definitions.get(str(treatment_code))
        if definition is not None:
            logger.info("Using procedure definition prompt for treatment_code=%s", treatment_code)
            return build_prompt_json_from_definition(definition), "definition", True

        if self.prompt_provider is None:
            raise LookupError(f"No medical classifier definition or fallback prompt found for {treatment_code}")

        prompt_json = self.prompt_provider(str(treatment_code))
        if not prompt_json:
            raise LookupError(f"No medical classifier fallback prompt found for {treatment_code}")

        logger.info("Using fallback prompt provider for treatment_code=%s", treatment_code)
        return dict(prompt_json), "fallback", False

    def _prepare_text(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not self.mask_pii_before_llm:
            return cleaned
        masked, count = mask_israeli_ids(cleaned)
        if count:
            logger.info("Masked %s possible ID values before classification", count)
        return masked

    def _run_prompt_json(
        self,
        prompt_json: dict[str, object],
        masked_desc: str,
        masked_full: str,
    ) -> tuple[dict[str, int], dict[str, dict[str, Any]], dict[str, Any] | None]:
        system_message = str(prompt_json.get("system_message", "") or "")
        idx_results: dict[str, int] = {}
        raw_model_output: dict[str, dict[str, Any]] = {}
        error: dict[str, Any] | None = None

        for key, prompt_obj in prompt_json.items():
            if not key.startswith("IDX_"):
                continue

            if not isinstance(prompt_obj, (list, tuple)) or len(prompt_obj) != 2:
                logger.warning("Skipping invalid prompt object for %s: %r", key, prompt_obj)
                continue

            prompt_text, scope = prompt_obj
            text_to_analyze = masked_full if str(scope).strip().lower() == "full" else masked_desc
            response = self.llm_runner.run_idx(
                text=text_to_analyze,
                prompt=str(prompt_text),
                key=key,
                system_message=system_message,
            )
            idx_results[key] = _coerce_result_code(response)
            raw_model_output[key] = dict(response)
            response_error = response.get("error") if isinstance(response, Mapping) else None
            if error is None and isinstance(response_error, Mapping):
                error = dict(response_error)

        return idx_results, raw_model_output, error
