from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.settings import Settings
from app.services.medical_classifier import ConfigurableLLMJsonPromptRunner
from app.services.medical_classifier import ProcedureClassificationInput
from app.services.medical_classifier import ProcedureClassificationService
from app.services.medical_classifier import ProcedureDefinitionLoader
from app.services.medical_classifier import build_medical_classifier_llm_runner
from app.services.medical_classifier import build_prompt_json_from_definition
from app.services.medical_classifier import mask_israeli_ids


def _definition_payload(treatment_code: str = "PROC_1") -> dict[str, Any]:
    return {
        "treatment_code": treatment_code,
        "procedure_name": "ניתוח לדוגמה",
        "procedure_aliases": ["Example surgery"],
        "source": "unit_test",
        "current_hospitalization_only": True,
        "require_actual_performance": True,
        "priority_sections": ["סיכום פעולה", "operative report"],
        "global_positive_signals": ["בוצע", "performed"],
        "global_negative_signals": ["התקבל לצורך", "planned"],
        "categories": [
            {
                "key": "IDX_PROCEDURE_PERFORMED",
                "title": "בוצע בפועל",
                "description": "האם הפרוצדורה בוצעה בפועל באשפוז הנוכחי.",
                "scope": "full",
                "positive_signals": ["בוצע ניתוח"],
                "negative_signals": ["התקבל לצורך ניתוח"],
                "examples_positive": ["בוצע ניתוח ללא סיבוכים."],
                "examples_negative": ["התקבל לצורך ניתוח."],
            }
        ],
    }


def _write_definition(path: Path, treatment_code: str) -> None:
    path.write_text(json.dumps(_definition_payload(treatment_code), ensure_ascii=False), encoding="utf-8")


class RecordingRunner:
    def __init__(self, result_code: str = "1") -> None:
        self.result_code = result_code
        self.calls: list[dict[str, str]] = []

    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str) -> dict[str, str]:
        self.calls.append(
            {
                "text": text,
                "prompt": prompt,
                "key": key,
                "system_message": system_message,
            }
        )
        return {"result_code": self.result_code}


class RichRunner:
    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str) -> dict[str, object]:
        return {
            "result_code": "1",
            "matched_text": "procedure was performed",
            "evidence": ["procedure was performed"],
            "confidence": 0.91,
            "explanation": "Clear performance language.",
        }


class PlanningAwareRunner:
    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str) -> dict[str, str]:
        has_negative_guidance = "התקבל לצורך ניתוח" in prompt and "Negative examples" in prompt
        result_code = "0" if "התקבל לצורך ניתוח" in text and has_negative_guidance else "1"
        return {"result_code": result_code}


def test_definition_loader_loads_single_json_file(tmp_path: Path) -> None:
    definition_file = tmp_path / "single.json"
    _write_definition(definition_file, "PROC_SINGLE")

    loader = ProcedureDefinitionLoader(str(definition_file))

    definitions = loader.load()

    assert list(definitions) == ["PROC_SINGLE"]
    assert definitions["PROC_SINGLE"].categories[0].key == "IDX_PROCEDURE_PERFORMED"


def test_definition_loader_loads_directory_of_json_files(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "a.json", "PROC_A")
    _write_definition(definitions_dir / "b.json", "PROC_B")

    loader = ProcedureDefinitionLoader(str(definitions_dir))

    definitions = loader.load()

    assert set(definitions) == {"PROC_A", "PROC_B"}


def test_prompt_builder_preserves_existing_json_prompt_shape(tmp_path: Path) -> None:
    definition_file = tmp_path / "prompt.json"
    _write_definition(definition_file, "PROC_PROMPT")
    definition = ProcedureDefinitionLoader(str(definition_file)).load()["PROC_PROMPT"]

    prompt_json = build_prompt_json_from_definition(definition)

    assert prompt_json["to_summarize"] is False
    assert "system_message" in prompt_json
    assert isinstance(prompt_json["IDX_PROCEDURE_PERFORMED"], list)
    assert prompt_json["IDX_PROCEDURE_PERFORMED"][1] == "full"
    assert '"matched_text"' in prompt_json["IDX_PROCEDURE_PERFORMED"][0]
    assert '"evidence"' in prompt_json["IDX_PROCEDURE_PERFORMED"][0]


def test_service_uses_definition_prompt_when_treatment_code_exists(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "defined.json", "PROC_DEFINED")
    runner = RecordingRunner()

    service = ProcedureClassificationService(
        llm_runner=runner,
        definitions_path=definitions_dir,
        prompt_provider=lambda treatment_code: None,
    )

    result = service.classify_document(
        ProcedureClassificationInput(
            treatment_code="PROC_DEFINED",
            file_desc="מסמך עם מזהה 123456789",
            file_full_text="בוצע ניתוח בהצלחה. מזהה 123456789",
        )
    )

    assert result.used_definition is True
    assert result.prompt_source == "definition"
    assert result.idx_results["IDX_PROCEDURE_PERFORMED"] == 1
    assert result.index_details["IDX_PROCEDURE_PERFORMED"] == {
        "result_code": 1,
        "found": True,
        "matched_text": None,
        "evidence": [],
        "confidence": None,
        "explanation": None,
    }
    assert runner.calls[0]["key"] == "IDX_PROCEDURE_PERFORMED"
    assert "[ID_REMOVED]" in runner.calls[0]["text"]


def test_service_falls_back_to_prompt_provider_when_definition_is_missing(tmp_path: Path) -> None:
    runner = RecordingRunner()
    requested_codes: list[str] = []

    def fallback_prompt_provider(treatment_code: str) -> dict[str, object]:
        requested_codes.append(treatment_code)
        return {
            "system_message": "Fallback system",
            "to_summarize": False,
            "IDX_FALLBACK": ["Return 1 for any text", "cut"],
        }

    service = ProcedureClassificationService(
        llm_runner=runner,
        definitions_path=tmp_path / "missing",
        prompt_provider=fallback_prompt_provider,
    )

    result = service.classify_document(
        ProcedureClassificationInput(
            treatment_code="UNKNOWN_CODE",
            file_desc="fallback description",
            file_full_text="full text that should not be used for cut scope",
        )
    )

    assert requested_codes == ["UNKNOWN_CODE"]
    assert result.used_definition is False
    assert result.prompt_source == "fallback"
    assert result.idx_results == {"IDX_FALLBACK": 1}
    assert result.index_details["IDX_FALLBACK"]["found"] is True
    assert runner.calls[0]["text"] == "fallback description"


def test_service_builds_rich_index_details_without_storing_snippets_in_raw_output(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "defined.json", "PROC_DEFINED")
    service = ProcedureClassificationService(
        llm_runner=RichRunner(),
        definitions_path=definitions_dir,
    )

    result = service.classify_document(
        ProcedureClassificationInput(
            treatment_code="PROC_DEFINED",
            file_full_text="procedure was performed",
        )
    )

    assert result.idx_results == {"IDX_PROCEDURE_PERFORMED": 1}
    assert result.index_details["IDX_PROCEDURE_PERFORMED"] == {
        "result_code": 1,
        "found": True,
        "matched_text": "procedure was performed",
        "evidence": ["procedure was performed"],
        "confidence": 0.91,
        "explanation": "Clear performance language.",
    }
    assert "matched_text" not in result.raw_model_output["IDX_PROCEDURE_PERFORMED"]
    assert "evidence" not in result.raw_model_output["IDX_PROCEDURE_PERFORMED"]


def test_pii_masking_removes_likely_israeli_ids() -> None:
    masked, count = mask_israeli_ids("מספרים 123456789 ו-54321 צריכים להימחק, אבל 1234 צריך להישאר.")

    assert count == 2
    assert "123456789" not in masked
    assert "54321" not in masked
    assert "1234" in masked


def test_planning_phrase_alone_is_not_positive_with_llm_mock(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "plan.json", "PROC_PLAN")
    service = ProcedureClassificationService(
        llm_runner=PlanningAwareRunner(),
        definitions_path=definitions_dir,
    )

    result = service.classify_document(
        ProcedureClassificationInput(
            treatment_code="PROC_PLAN",
            file_full_text="התקבל לצורך ניתוח",
        )
    )

    assert result.idx_results["IDX_PROCEDURE_PERFORMED"] == 0


def test_build_llm_runner_uses_env_api_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("MEDICAL_CLASSIFIER_TEST_KEY", "env-secret")
    settings = Settings(
        medical_classifier_llm_provider="openai",
        medical_classifier_llm_model="gpt-4o-mini",
        medical_classifier_llm_api_key_env_name="MEDICAL_CLASSIFIER_TEST_KEY",
        medical_classifier_llm_api_key="",
    )

    runner = build_medical_classifier_llm_runner(settings)

    assert isinstance(runner, ConfigurableLLMJsonPromptRunner)
    assert runner.api_key == "env-secret"


def test_llm_runner_normalizes_legacy_and_rich_index_payloads() -> None:
    responses = iter(
        [
            {"choices": [{"message": {"content": '{"result_code": 1}'}}]},
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "result_code": 1,
                                    "matched_text": "procedure was performed",
                                    "evidence": ["procedure was performed"],
                                    "confidence": 0.91,
                                    "explanation": "Clear performance language.",
                                }
                            )
                        }
                    }
                ]
            },
        ]
    )

    def sender(
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        return next(responses)

    settings = Settings(
        medical_classifier_llm_provider="openai",
        medical_classifier_llm_model="gpt-4o-mini",
        medical_classifier_llm_api_key="test-key",
    )
    runner = ConfigurableLLMJsonPromptRunner.from_settings(settings, request_sender=sender)

    legacy = runner.run_idx(text="text", prompt="prompt", key="IDX_A", system_message="system")
    rich = runner.run_idx(text="text", prompt="prompt", key="IDX_A", system_message="system")

    assert legacy == {"result_code": 1}
    assert rich == {
        "result_code": 1,
        "matched_text": "procedure was performed",
        "evidence": ["procedure was performed"],
        "confidence": 0.91,
        "explanation": "Clear performance language.",
    }
