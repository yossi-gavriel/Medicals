from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.extraction_engine.normalizer import (
    normalize_date,
    normalize_enum_value,
    normalize_number,
)
from app.services.extraction_engine.spec import Rule


@dataclass(frozen=True)
class ExtractionRecord:
    value: Any
    confidence: float
    evidence: list[str] = field(default_factory=list)
    reason: str = ""
    error: dict[str, str] | None = None


class LLMRuleResolver(Protocol):
    def is_available(self) -> bool: ...
    def resolve(self, *, rule: Rule, sentences: list[str]) -> ExtractionRecord: ...


def default_for_missing(rule: Rule) -> Any:
    """Return the configured default for a missing value, or None when unset.

    For boolean rules the spec allows the operator to choose between False and
    None; an unset default falls back to None per the product requirements.
    """
    return rule.default_when_missing


def _missing(rule: Rule, reason: str) -> ExtractionRecord:
    return ExtractionRecord(
        value=default_for_missing(rule),
        confidence=0.0,
        evidence=[],
        reason=reason,
    )


def _classify_sentence(
    sentence: str,
    positives: list[str],
    negatives: list[str],
    planning: list[str] | None = None,
    historical: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """Return (verdict, indicator) for a sentence.

    Precedence: negative > planning/historical (mention-context suppressors) > positive.
    Matching is case-insensitive substring — safe for Hebrew (no case) and
    the standard case-fold comparison for English.
    """
    if not sentence:
        return (None, None)
    lowered = sentence.lower()
    for indicator in negatives:
        if indicator and indicator.lower() in lowered:
            return ("negative", indicator)
    if planning:
        for indicator in planning:
            if indicator and indicator.lower() in lowered:
                return ("planning", indicator)
    if historical:
        for indicator in historical:
            if indicator and indicator.lower() in lowered:
                return ("historical", indicator)
    for indicator in positives:
        if indicator and indicator.lower() in lowered:
            return ("positive", indicator)
    return (None, None)


def _scan_indicators(
    sentences: list[str],
    positives: list[str],
    negatives: list[str],
    planning: list[str] | None = None,
    historical: list[str] | None = None,
):
    pos_hits: list[tuple[str, str]] = []
    neg_hits: list[tuple[str, str]] = []
    plan_hits: list[tuple[str, str]] = []
    hist_hits: list[tuple[str, str]] = []
    for sentence in sentences:
        verdict, indicator = _classify_sentence(sentence, positives, negatives, planning, historical)
        if verdict == "negative":
            neg_hits.append((sentence, indicator or ""))
        elif verdict == "planning":
            plan_hits.append((sentence, indicator or ""))
        elif verdict == "historical":
            hist_hits.append((sentence, indicator or ""))
        elif verdict == "positive":
            pos_hits.append((sentence, indicator or ""))
    return pos_hits, neg_hits, plan_hits, hist_hits


def _format_indicators(hits: list[tuple[str, str]]) -> str:
    seen: list[str] = []
    for _, indicator in hits:
        if indicator and indicator not in seen:
            seen.append(indicator)
    return ", ".join(seen)


def _try_llm(
    rule: Rule,
    sentences: list[str],
    llm: LLMRuleResolver | None,
) -> ExtractionRecord | None:
    if llm is None or not llm.is_available():
        return None
    try:
        record = llm.resolve(rule=rule, sentences=sentences)
    except Exception as exc:  # pragma: no cover - defensive
        return ExtractionRecord(
            value=default_for_missing(rule),
            confidence=0.0,
            evidence=[],
            reason="LLM resolver failed; returning default.",
            error={"code": "llm_failed", "message": str(exc)},
        )
    if rule.evidence_required and not record.evidence:
        return _missing(rule, "LLM returned a value but evidence_required is true and no evidence was provided.")
    return record


def extract_boolean(
    rule: Rule,
    sentences: list[str],
    llm: LLMRuleResolver | None = None,
) -> ExtractionRecord:
    # When allow_*_mentions is set, drop those indicators so the suppressor never
    # fires — the same sentence can then fall through to a positive verdict.
    planning = [] if rule.allow_planned_mentions else rule.planning_indicators
    historical = [] if rule.allow_historical_mentions else rule.historical_indicators

    pos_hits, neg_hits, plan_hits, hist_hits = _scan_indicators(
        sentences,
        rule.positive_indicators,
        rule.negative_indicators,
        planning=planning,
        historical=historical,
    )

    if neg_hits:
        return ExtractionRecord(
            value=False,
            confidence=0.95,
            evidence=[s for s, _ in neg_hits],
            reason=f"Matched negative indicator(s): {_format_indicators(neg_hits)}",
        )
    if plan_hits:
        return ExtractionRecord(
            value=False,
            confidence=0.85,
            evidence=[s for s, _ in plan_hits],
            reason=(
                f"Matched planning indicator(s) suppressing positive: "
                f"{_format_indicators(plan_hits)}"
            ),
        )
    if hist_hits:
        return ExtractionRecord(
            value=False,
            confidence=0.85,
            evidence=[s for s, _ in hist_hits],
            reason=(
                f"Matched historical indicator(s) suppressing positive: "
                f"{_format_indicators(hist_hits)}"
            ),
        )
    if pos_hits:
        return ExtractionRecord(
            value=True,
            confidence=0.9,
            evidence=[s for s, _ in pos_hits],
            reason=f"Matched positive indicator(s): {_format_indicators(pos_hits)}",
        )

    llm_record = _try_llm(rule, sentences, llm)
    if llm_record is not None:
        if llm_record.value is None:
            return llm_record
        if isinstance(llm_record.value, bool):
            return llm_record
        return ExtractionRecord(
            value=default_for_missing(rule),
            confidence=0.0,
            evidence=llm_record.evidence,
            reason=f"LLM returned '{llm_record.value}' which is not a boolean.",
            error={"code": "boolean_value_invalid", "message": "value is not a boolean"},
        )
    return _missing(rule, "No positive or negative indicators matched.")


def extract_enum(
    rule: Rule,
    sentences: list[str],
    llm: LLMRuleResolver | None = None,
) -> ExtractionRecord:
    allowed = rule.allowed_values or []
    for sentence in sentences:
        match = normalize_enum_value(sentence, allowed)
        if match is not None:
            return ExtractionRecord(
                value=match,
                confidence=0.9,
                evidence=[sentence],
                reason=f"Matched allowed value '{match}' as a sentence.",
            )
        lowered = sentence.lower()
        for value in allowed:
            if value.lower() in lowered:
                return ExtractionRecord(
                    value=value,
                    confidence=0.85,
                    evidence=[sentence],
                    reason=f"Matched allowed value '{value}' inside sentence.",
                )

    llm_record = _try_llm(rule, sentences, llm)
    if llm_record is not None:
        if llm_record.value is None:
            return llm_record
        normalized = normalize_enum_value(str(llm_record.value), allowed)
        if normalized is None:
            return ExtractionRecord(
                value=default_for_missing(rule),
                confidence=0.0,
                evidence=llm_record.evidence,
                reason=f"LLM returned '{llm_record.value}' which is not in allowed_values.",
                error={"code": "enum_value_invalid", "message": "value not in allowed_values"},
            )
        return ExtractionRecord(
            value=normalized,
            confidence=llm_record.confidence,
            evidence=llm_record.evidence,
            reason=llm_record.reason,
        )

    return _missing(rule, "No allowed_values appeared in the document.")


def extract_date(
    rule: Rule,
    sentences: list[str],
    llm: LLMRuleResolver | None = None,
) -> ExtractionRecord:
    candidate_sentences: list[str]
    if rule.positive_indicators:
        candidate_sentences = [s for s in sentences if _classify_sentence(s, rule.positive_indicators, [])[0] == "positive"]
        if not candidate_sentences:
            candidate_sentences = sentences
    else:
        candidate_sentences = sentences

    for sentence in candidate_sentences:
        iso = normalize_date(sentence)
        if iso:
            return ExtractionRecord(
                value=iso,
                confidence=0.9,
                evidence=[sentence],
                reason="Matched a date pattern in the document text.",
            )

    llm_record = _try_llm(rule, sentences, llm)
    if llm_record is not None:
        if llm_record.value is None:
            return llm_record
        iso = normalize_date(str(llm_record.value))
        if iso is None:
            return ExtractionRecord(
                value=default_for_missing(rule),
                confidence=0.0,
                evidence=llm_record.evidence,
                reason=f"LLM returned '{llm_record.value}' which is not a recognizable date.",
                error={"code": "date_value_invalid", "message": "could not normalize date"},
            )
        return ExtractionRecord(
            value=iso,
            confidence=llm_record.confidence,
            evidence=llm_record.evidence,
            reason=llm_record.reason,
        )

    return _missing(rule, "No date pattern matched in the document.")


def extract_number(
    rule: Rule,
    sentences: list[str],
    llm: LLMRuleResolver | None = None,
) -> ExtractionRecord:
    candidate_sentences: list[str]
    if rule.positive_indicators:
        candidate_sentences = [s for s in sentences if _classify_sentence(s, rule.positive_indicators, [])[0] == "positive"]
        if not candidate_sentences:
            candidate_sentences = sentences
    else:
        candidate_sentences = sentences

    for sentence in candidate_sentences:
        value = normalize_number(sentence)
        if value is not None:
            return ExtractionRecord(
                value=value,
                confidence=0.9,
                evidence=[sentence],
                reason="Matched a numeric token in the document text.",
            )

    llm_record = _try_llm(rule, sentences, llm)
    if llm_record is not None:
        if llm_record.value is None:
            return llm_record
        value = llm_record.value
        if isinstance(value, bool):
            value = None
        if isinstance(value, (int, float)):
            return ExtractionRecord(
                value=value,
                confidence=llm_record.confidence,
                evidence=llm_record.evidence,
                reason=llm_record.reason,
            )
        normalized = normalize_number(str(value)) if value is not None else None
        if normalized is None:
            return ExtractionRecord(
                value=default_for_missing(rule),
                confidence=0.0,
                evidence=llm_record.evidence,
                reason=f"LLM returned '{llm_record.value}' which is not a recognizable number.",
                error={"code": "number_value_invalid", "message": "could not normalize number"},
            )
        return ExtractionRecord(
            value=normalized,
            confidence=llm_record.confidence,
            evidence=llm_record.evidence,
            reason=llm_record.reason,
        )

    return _missing(rule, "No numeric token matched in the document.")


def extract_text(
    rule: Rule,
    sentences: list[str],
    llm: LLMRuleResolver | None = None,
) -> ExtractionRecord:
    pos_hits, _, _, _ = _scan_indicators(sentences, rule.positive_indicators, [])
    if pos_hits:
        sentence, _ = pos_hits[0]
        return ExtractionRecord(
            value=sentence,
            confidence=0.7,
            evidence=[sentence],
            reason="Returned the first sentence matching a positive indicator.",
        )

    llm_record = _try_llm(rule, sentences, llm)
    if llm_record is not None:
        if llm_record.value is None:
            return llm_record
        return ExtractionRecord(
            value=str(llm_record.value),
            confidence=llm_record.confidence,
            evidence=llm_record.evidence,
            reason=llm_record.reason,
        )

    return _missing(rule, "No matching evidence found and no LLM resolver available.")


_DISPATCH = {
    "boolean": extract_boolean,
    "enum": extract_enum,
    "date": extract_date,
    "number": extract_number,
    "text": extract_text,
}


def extract_rule(
    rule: Rule,
    sentences: list[str],
    llm: LLMRuleResolver | None = None,
) -> ExtractionRecord:
    """Dispatch a rule to its type-specific extractor."""
    extractor = _DISPATCH.get(rule.type)
    if extractor is None:  # pragma: no cover - guarded by spec validation
        return _missing(rule, f"No extractor registered for type '{rule.type}'.")
    return extractor(rule, sentences, llm)
