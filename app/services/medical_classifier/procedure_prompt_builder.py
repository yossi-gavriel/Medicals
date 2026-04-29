from __future__ import annotations

from app.services.medical_classifier.procedure_definition_loader import ProcedureDefinition

DEFAULT_SYSTEM_MESSAGE = """
You are a senior medical document reviewer.
Your job is to classify only what was actually performed during the current hospitalization/action.
Do not infer performance from admission reason, plan, referral, recommendation, consent, previous surgeries, or future scheduling.
Return only the requested structured result_code values.
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

Output strictly as JSON with one field:
{{"result_code": "0"}} or {{"result_code": "1"}}
""".strip()
        prompt_json[category.key] = [prompt, category.scope]

    return prompt_json
