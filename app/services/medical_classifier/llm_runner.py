from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import httpx

from app.core.settings import Settings

logger = logging.getLogger(__name__)

RequestSender = Callable[[str, dict[str, str], dict[str, Any], float], Mapping[str, Any]]


class JsonPromptRunner(Protocol):
    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str) -> Mapping[str, Any]:
        ...


def build_runner_error(code: str, message: str, *, raw_output: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result_code": 0,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if raw_output is not None:
        payload["raw_output"] = raw_output
    return payload


def _normalize_result_code(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value in {0, 1} else None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in {"0", "1"}:
            return int(normalized)
    return None


class ConfigurableLLMJsonPromptRunner:
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
    ) -> "ConfigurableLLMJsonPromptRunner":
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

    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str) -> Mapping[str, Any]:
        config_error = self._validate_configuration()
        if config_error is not None:
            return config_error

        endpoint = self._resolve_endpoint()
        if endpoint is None:
            return build_runner_error(
                "unsupported_llm_provider",
                f'Medical classifier provider "{self.provider}" is not supported yet.',
            )

        payload = self._build_payload(text=text, prompt=prompt, system_message=system_message)
        headers = self._build_headers()

        try:
            raw_response = self.request_sender(endpoint, headers, payload, self.timeout_seconds)
        except httpx.TimeoutException as exc:
            return build_runner_error("llm_timeout", f"Timed out while calling the medical classifier LLM: {exc}")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return build_runner_error(
                "llm_http_error",
                f"Medical classifier LLM returned HTTP {status}.",
            )
        except httpx.HTTPError as exc:
            return build_runner_error("llm_request_failed", f"Medical classifier LLM request failed: {exc}")
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected medical classifier LLM failure")
            return build_runner_error("llm_runner_failed", f"Medical classifier LLM runner failed: {exc}")

        return self._normalize_provider_response(raw_response, key=key)

    def _validate_configuration(self) -> dict[str, Any] | None:
        if not self.provider or self.provider == "disabled":
            return build_runner_error(
                "llm_not_configured",
                "Medical classifier LLM provider is not configured.",
            )
        if not self.model:
            return build_runner_error(
                "llm_not_configured",
                "Medical classifier LLM model is not configured.",
            )
        if not self.api_key:
            source = self.api_key_env_name or "medical_classifier_llm_api_key"
            return build_runner_error(
                "llm_not_configured",
                f"Medical classifier LLM API key is not configured. Expected value from {source}.",
            )
        return None

    def _resolve_endpoint(self) -> str | None:
        endpoints = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        }
        return endpoints.get(self.provider)

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, *, text: str, prompt: str, system_message: str) -> dict[str, Any]:
        user_prompt = f"{prompt}\n\nDocument text:\n{text}"
        return {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt},
            ],
        }

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

    def _normalize_provider_response(self, raw_response: Mapping[str, Any], *, key: str) -> dict[str, Any]:
        content = self._extract_content(raw_response)
        if content is None:
            return build_runner_error(
                "invalid_model_output",
                f"Medical classifier model returned no usable content for {key}.",
                raw_output=raw_response,
            )

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return build_runner_error(
                "invalid_model_output",
                f"Medical classifier model returned non-JSON content for {key}.",
                raw_output=content,
            )

        if not isinstance(parsed, Mapping):
            return build_runner_error(
                "invalid_model_output",
                f"Medical classifier model returned a non-object JSON payload for {key}.",
                raw_output=parsed,
            )

        normalized_result_code = _normalize_result_code(parsed.get("result_code"))
        if normalized_result_code is None:
            return build_runner_error(
                "invalid_model_output",
                f"Medical classifier model returned an invalid result_code for {key}.",
                raw_output=parsed,
            )

        normalized: dict[str, Any] = {"result_code": normalized_result_code}
        for optional_key in ("explanation", "confidence", "reasoning"):
            if optional_key in parsed:
                normalized[optional_key] = parsed[optional_key]
        return normalized

    @staticmethod
    def _extract_content(raw_response: Mapping[str, Any]) -> str | None:
        choices = raw_response.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, Mapping):
                message = first_choice.get("message")
                if isinstance(message, Mapping):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
        return None


def build_medical_classifier_llm_runner(
    settings: Settings,
    *,
    request_sender: RequestSender | None = None,
) -> JsonPromptRunner:
    return ConfigurableLLMJsonPromptRunner.from_settings(settings, request_sender=request_sender)
