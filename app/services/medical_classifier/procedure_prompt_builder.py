from __future__ import annotations

from typing import Any

from app.services.medical_classifier.procedure_definition_loader import ProcedureDefinition

DEFAULT_SYSTEM_MESSAGE = """
You are a senior medical document reviewer.
Your job is to classify only what was actually performed during the current hospitalization/action.
Do not infer performance from admission reason, plan, referral, recommendation, consent, previous surgeries, or future scheduling.
Return only the requested structured JSON fields.
""".strip()


def _format_list(title: str, values: list[str]) -> str:
    if not values:
        return f"{title}: none specified"
    items = "\n".join(f"- {value}" for value in values)
    return f"{title}:\n{items}"


def build_prompt_json_from_definition(definition: ProcedureDefinition) -> dict[str, object]:
    aliases = ", ".join(definition.procedure_aliases) if definition.procedure_aliases else "none specified"

    system_message = f"""
{DEFAULT_SYSTEM_MESSAGE}

Procedure under review: {definition.procedure_name}
Treatment code: {definition.treatment_code}
Aliases: {aliases}
Source: {definition.source}

Hard rules:
- If the text only says the patient was admitted for / planned for / referred to / recommended for the procedure, return 0.
- If the procedure appears only as past medical/surgical history, return 0.
- If the document describes actual operative/procedural execution in the current encounter, return 1.
- If evidence is ambiguous, prefer 0 unless there is concrete execution evidence.
- Hebrew, English, abbreviations, and mixed-language clinical notes are all valid.

{_format_list("Priority sections", definition.priority_sections)}
{_format_list("Global positive execution signals", definition.global_positive_signals)}
{_format_list("Global negative/planning/history signals", definition.global_negative_signals)}
""".strip()

    prompt_json: dict[str, object] = {
        "system_message": system_message,
        "to_summarize": False,
    }

    for category in definition.categories:
        prompt = f"""
Classify category: {category.title}
Category key: {category.key}

Category description:
{category.description}

Return result_code = 1 only if this category has clear evidence of actual performance/findings during the current hospitalization/action.
Return result_code = 0 if it is only planned, recommended, admission purpose, historical, negated, or unclear.

{_format_list("Positive signals for this category", category.positive_signals)}
{_format_list("Negative signals for this category", category.negative_signals)}
{_format_list("Positive examples", category.examples_positive)}
{_format_list("Negative examples", category.examples_negative)}

Output strictly as JSON with these fields:
{{
  "result_code": "0" or "1",
  "matched_text": "short exact supporting snippet or null",
  "evidence": ["short supporting snippets"],
  "confidence": 0.0,
  "explanation": "brief non-sensitive reason"
}}

If result_code is "0", use null/empty evidence fields unless there is useful negative evidence.
""".strip()
        prompt_json[category.key] = [prompt, category.scope]

    return prompt_json


def build_prompt_json_from_spec_body(spec: dict[str, Any]) -> dict[str, object]:
    """Build the classifier prompt JSON from the cloud procedure spec body.

    The persisted spec is product data edited in OmniScan and stored in the
    MedicalClassifier backend. This function converts that structured data into
    the same prompt-json shape used by the existing classification service.
    """
    system_prompt = str(spec.get("system_prompt") or DEFAULT_SYSTEM_MESSAGE).strip()
    prompt_json: dict[str, object] = {
        "system_message": system_prompt,
        "to_summarize": False,
    }
    indexes = spec.get("indexes") or []
    if not isinstance(indexes, list):
        return prompt_json

    for index in indexes:
        if not isinstance(index, dict):
            continue
        key = str(index.get("key") or "").strip()
        if not key.startswith("IDX_"):
            continue
        prompt_json[key] = [_prompt_from_spec_index(index), "full"]

    return prompt_json


def _prompt_from_spec_index(index: dict[str, Any]) -> str:
    raw_examples = index.get("examples")
    examples: list[Any] = raw_examples if isinstance(raw_examples, list) else []
    formatted_examples = []
    for example in examples:
        if not isinstance(example, dict):
            continue
        text = str(example.get("text") or "").strip()
        expected = str(example.get("expected_result") or "").strip()
        if text or expected:
            formatted_examples.append(f"- Text: {text}\n  Expected result: {expected}")

    return f"""
Classify index: {index.get("label") or index.get("key")}
Index key: {index.get("key")}
Category: {index.get("category") or "unspecified"}
Output type: {index.get("output_type") or "binary"}
Required evidence: {"yes" if index.get("required_evidence") else "no"}

Return result_code = 1 only when the document contains clear evidence that satisfies this index.
Return result_code = 0 for negation, historical mention, planned/future care, ambiguity, or unrelated text.

{_format_list("Positive terms", _as_str_list(index.get("positive_terms")))}
{_format_list("Negative terms", _as_str_list(index.get("negative_terms")))}
{_format_list("Positive phrases", _as_str_list(index.get("positive_phrases")))}
{_format_list("Negative phrases", _as_str_list(index.get("negative_phrases")))}
{_format_list("Rules", _as_str_list(index.get("rules")))}
{_format_list("Examples", formatted_examples)}

Output strictly as JSON with these fields:
{{
  "result_code": "0" or "1",
  "matched_text": "short exact supporting snippet or null",
  "evidence": ["short supporting snippets"],
  "confidence": 0.0,
  "explanation": "brief non-sensitive reason"
}}
""".strip()


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
