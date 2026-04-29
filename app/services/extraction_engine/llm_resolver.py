from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from app.core.settings import Settings
from app.services.extraction_engine.rule_extractors import ExtractionRecord
from app.services.extraction_engine.spec import Rule

logger = logging.getLogger(__name__)

RequestSender = Callable[[str, dict[str, str], dict[str, Any], float], Mapping[str, Any]]


_PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


_SYSTEM_MESSAGE = (
    "You are a medical document extraction assistant. You receive ONE specific extraction "
    "rule and the document text. Return ONLY valid JSON with the keys: value, confidence, "
    "evidence, reason. Never invent fields beyond those keys. If the requested information "
    "is not present, return value=null and reason explaining what is missing. Evidence must "
    "be exact quotes from the document. Documents may be in Hebrew or English."
)


def _build_user_prompt(rule: Rule, sentences: list[str]) -> str:
    body = "\n".join(sentences)
    rule_description = {
        "field_name": rule.field_name,
        "type": rule.type,
        "description": rule.description,
        "positive_indicators": rule.positive_indicators,
        "negative_indicators": rule.negative_indicators,
        "allowed_values": rule.allowed_values,
        "evidence_required": rule.evidence_required,
    }
    return (
        "Extract the following rule from the document text and respond with strict JSON "
        f"of the form {{\"value\": ..., \"confidence\": 0.0-1.0, \"evidence\": [..], "
        f"\"reason\": \"..\"}}.\n\nRule: {json.dumps(rule_description, ensure_ascii=False)}"
        f"\n\nDocument text:\n{body}"
    )


class HTTPLLMRuleResolver:
    """LLM-backed extraction resolver that calls an OpenAI-compatible chat endpoint.

    The resolver returns ExtractionRecord; type-specific normalization (date, number,
    enum) is applied by the caller. This class deliberately does not attempt to
    decide *what* to extract — it only resolves the configured rule.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        api_key_env_name: str = "",
        timeout_seconds: float = 15.0,
        request_sender: RequestSender | None = None,
    ) -> None:
        self.provider = provider.strip().lower()
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.api_key_env_name = api_key_env_name.strip()
        self.timeout_seconds = timeout_seconds
        self.request_sender = request_sender or self._default_request_sender

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        request_sender: RequestSender | None = None,
    ) -> HTTPLLMRuleResolver:
        api_key = settings.medical_classifier_llm_api_key.strip()
        env_name = settings.medical_classifier_llm_api_key_env_name.strip()
        if not api_key and env_name:
            api_key = os.getenv(env_name, "").strip()
        return cls(
            provider=settings.medical_classifier_llm_provider,
            model=settings.medical_classifier_llm_model,
            api_key=api_key,
            api_key_env_name=env_name,
            timeout_seconds=settings.medical_classifier_llm_timeout_seconds,
            request_sender=request_sender,
        )

    def is_available(self) -> bool:
        if not self.provider or self.provider == "disabled":
            return False
        if self.provider not in _PROVIDER_ENDPOINTS:
            return False
        return bool(self.model and self.api_key)

    def resolve(self, *, rule: Rule, sentences: list[str]) -> ExtractionRecord:
        endpoint = _PROVIDER_ENDPOINTS.get(self.provider)
        if endpoint is None:
            return ExtractionRecord(
                value=rule.default_when_missing,
                confidence=0.0,
                evidence=[],
                reason="LLM provider not supported.",
                error={"code": "llm_not_configured", "message": "provider unsupported"},
            )

        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_MESSAGE},
                {"role": "user", "content": _build_user_prompt(rule, sentences)},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            raw = self.request_sender(endpoint, headers, payload, self.timeout_seconds)
        except httpx.TimeoutException as exc:
            return self._error_record(rule, "llm_timeout", f"LLM call timed out: {exc}")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return self._error_record(rule, "llm_http_error", f"LLM HTTP {status}.")
        except httpx.HTTPError as exc:
            return self._error_record(rule, "llm_request_failed", f"LLM request failed: {exc}")
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected LLM extraction failure")
            return self._error_record(rule, "llm_runner_failed", f"LLM runner failed: {exc}")

        return self._parse(raw, rule)

    def _parse(self, raw: Mapping[str, Any], rule: Rule) -> ExtractionRecord:
        content = self._extract_content(raw)
        if content is None:
            return self._error_record(rule, "invalid_model_output", "no content in LLM response")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return self._error_record(rule, "invalid_model_output", "LLM returned non-JSON content")
        if not isinstance(parsed, Mapping):
            return self._error_record(rule, "invalid_model_output", "LLM returned non-object JSON")

        value = parsed.get("value")
        confidence = parsed.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        confidence_value = max(0.0, min(1.0, confidence_value))

        evidence_raw = parsed.get("evidence", [])
        if isinstance(evidence_raw, str):
            evidence_list = [evidence_raw]
        elif isinstance(evidence_raw, list):
            evidence_list = [str(e) for e in evidence_raw if e]
        else:
            evidence_list = []

        reason = str(parsed.get("reason", "")).strip()

        return ExtractionRecord(
            value=value,
            confidence=confidence_value,
            evidence=evidence_list,
            reason=reason or "LLM returned a value.",
        )

    def _error_record(self, rule: Rule, code: str, message: str) -> ExtractionRecord:
        return ExtractionRecord(
            value=rule.default_when_missing,
            confidence=0.0,
            evidence=[],
            reason=message,
            error={"code": code, "message": message},
        )

    @staticmethod
    def _extract_content(raw: Mapping[str, Any]) -> str | None:
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, Mapping):
                message = first.get("message")
                if isinstance(message, Mapping):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
        return None

    def _default_request_sender(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()


def build_llm_rule_resolver(
    settings: Settings,
    *,
    request_sender: RequestSender | None = None,
) -> HTTPLLMRuleResolver:
    return HTTPLLMRuleResolver.from_settings(settings, request_sender=request_sender)
