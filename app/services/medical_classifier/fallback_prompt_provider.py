from __future__ import annotations


def build_generic_fallback_prompt_json(procedure_code: str) -> dict[str, object]:
    normalized_code = procedure_code.strip() or "unknown_procedure"
    system_message = f"""
You are a senior medical document reviewer.
Your job is to classify only what was actually performed during the current hospitalization/action.
Do not infer performance from admission reason, plan, referral, recommendation, consent, previous surgeries, or future scheduling.
Procedure code under review: {normalized_code}
Return only the requested structured result_code values.
""".strip()

    prompt = f"""
Classify whether procedure code "{normalized_code}" was actually performed in the current encounter.

Return result_code = 1 only if the text contains clear evidence of actual procedural execution during the current hospitalization/action.
Return result_code = 0 if the procedure is only planned, recommended, historical, admission purpose, consent-related, or unclear.

Negative examples:
- התקבל לצורך ניתוח
- planned for procedure
- history of prior procedure

Output strictly as JSON with one field:
{{"result_code": "0"}} or {{"result_code": "1"}}
""".strip()

    return {
        "system_message": system_message,
        "to_summarize": False,
        "IDX_PROCEDURE_PERFORMED": [prompt, "full"],
    }
