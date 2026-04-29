from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from app.core.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExternalInteraction:
    severity: str
    risk: str
    recommendation: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class BaseInteractionProvider:
    provider_key = "base"
    provider_name = "base"

    # Deterministic fallback table used when external APIs are not configured.
    default_matrix: dict[tuple[str, str], tuple[str, str, str]] = {
        ("aspirin", "warfarin"): (
            "D",
            "increased bleeding",
            "Avoid routine combination or use strict INR and bleeding monitoring",
        ),
        ("clarithromycin", "simvastatin"): (
            "X",
            "severe myopathy and rhabdomyolysis risk",
            "Contraindicated: use non-CYP3A4 statin alternative",
        ),
        ("lisinopril", "spironolactone"): (
            "C",
            "hyperkalemia",
            "Monitor potassium and renal function",
        ),
    }

    def __init__(self, settings: Settings, api_url: str, api_key: str, enabled: bool = True) -> None:
        self.settings = settings
        self.api_url = api_url
        self.api_key = api_key
        self.enabled = enabled

    @staticmethod
    def pair_key(drug_a: str, drug_b: str) -> tuple[str, str]:
        a, b = drug_a.strip().lower(), drug_b.strip().lower()
        return (a, b) if a <= b else (b, a)

    async def get_drug_interactions(self, drug_a: str, drug_b: str) -> ExternalInteraction | None:
        if not self.enabled:
            return None

        if self.api_url:
            interaction = await self._call_external(drug_a, drug_b)
            if interaction:
                return interaction

        pair = self.pair_key(drug_a, drug_b)
        fallback = self.default_matrix.get(pair)
        if fallback is None:
            return None
        severity, risk, recommendation = fallback
        return ExternalInteraction(
            severity=severity,
            risk=risk,
            recommendation=recommendation,
            source=self.provider_name,
        )

    async def _call_external(self, drug_a: str, drug_b: str) -> ExternalInteraction | None:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"drugA": drug_a, "drugB": drug_b}

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self.settings.external_retry_attempts),
            wait=wait_exponential(
                multiplier=self.settings.external_retry_backoff_seconds,
                min=self.settings.external_retry_backoff_seconds,
                max=2,
            ),
            reraise=False,
        )

        async for attempt in retrying:
            with attempt:
                async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                    response = await client.post(self.api_url, headers=headers, json=payload)
                    if response.status_code == 404:
                        return None
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict) or "severity" not in data:
                        return None
                    return ExternalInteraction(
                        severity=str(data.get("severity", "A")),
                        risk=str(data.get("risk", "none")),
                        recommendation=str(data.get("recommendation", "No action")),
                        source=self.provider_name,
                    )

        logger.warning(
            "provider_request_failed",
            extra={"extra": {"provider": self.provider_name, "drug_a": drug_a, "drug_b": drug_b}},
        )
        return None
