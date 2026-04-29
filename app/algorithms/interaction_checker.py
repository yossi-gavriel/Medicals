from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.algorithms.interaction_graph import InteractionGraph
from app.core.cache import CacheClient
from app.core.settings import Settings
from app.integrations.base import BaseInteractionProvider
from app.integrations.base import ExternalInteraction
from app.repositories.drug_repository import DrugRepository
from app.repositories.interaction_repository import InteractionRepository

UNSAFE_SEVERITIES = {"C", "D", "X"}
SEVERITY_ORDER: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4}

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MedicationContext:
    dose: str | None = None
    unit: str | None = None
    frequency: str | None = None


@dataclass(slots=True)
class InteractionResult:
    drug_a: str
    drug_b: str
    severity: str
    risk: str
    recommendation: str
    source: str

    @property
    def is_unsafe(self) -> bool:
        return self.severity in UNSAFE_SEVERITIES


class InteractionChecker:
    def __init__(
        self,
        settings: Settings,
        cache_client: CacheClient,
        graph: InteractionGraph,
        providers: list[BaseInteractionProvider],
    ) -> None:
        self.settings = settings
        self.cache = cache_client
        self.graph = graph
        self.providers = providers
        priority = settings.provider_priority or [self._provider_key(provider) for provider in providers]
        self._provider_priority = {name: index for index, name in enumerate(priority)}

    @staticmethod
    def _normalize(name: str) -> str:
        return name.strip().lower()

    @staticmethod
    def _provider_key(provider: BaseInteractionProvider) -> str:
        return getattr(provider, "provider_key", getattr(provider, "provider_name", "unknown")).strip().lower()

    @staticmethod
    def _severity_score(severity: str) -> int:
        return SEVERITY_ORDER.get(severity.strip().upper(), -1)

    async def _query_provider(
        self,
        provider: BaseInteractionProvider,
        drug_a: str,
        drug_b: str,
    ):
        try:
            return await provider.get_drug_interactions(drug_a, drug_b)
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "provider_query_failed",
                extra={
                    "extra": {
                        "provider": self._provider_key(provider),
                        "drug_a": drug_a,
                        "drug_b": drug_b,
                        "error": str(exc),
                    }
                },
            )
            return None

    async def _aggregate_external(self, drug_a: str, drug_b: str):
        if not self.providers:
            return None

        responses = await asyncio.gather(
            *[self._query_provider(provider, drug_a, drug_b) for provider in self.providers]
        )

        candidates: list[tuple[int, int, int, BaseInteractionProvider, ExternalInteraction]] = []
        for index, (provider, response) in enumerate(zip(self.providers, responses, strict=False)):
            if response is None:
                continue
            provider_key = self._provider_key(provider)
            priority = self._provider_priority.get(provider_key, len(self._provider_priority) + index)
            severity_score = self._severity_score(response.severity)
            candidates.append((severity_score, -priority, -index, provider, response))

        if not candidates:
            return None

        best = max(candidates, key=lambda item: (item[0], item[1], item[2]))
        return best[4]

    def _cache_key(self, drug_a: str, drug_b: str) -> str:
        a, b = sorted([self._normalize(drug_a), self._normalize(drug_b)])
        return f"interaction:{a}:{b}"

    async def check_pair(
        self,
        drug_a: str,
        drug_b: str,
        drug_repo: DrugRepository,
        interaction_repo: InteractionRepository,
        drug_a_context: MedicationContext | None = None,
        drug_b_context: MedicationContext | None = None,
    ) -> InteractionResult:
        a = self._normalize(drug_a)
        b = self._normalize(drug_b)
        _unused_context = (drug_a_context, drug_b_context)

        if a == b:
            return InteractionResult(a, b, "A", "same drug", "No additive interaction", "local")

        canonical_a = await drug_repo.resolve_canonical_name(a)
        canonical_b = await drug_repo.resolve_canonical_name(b)

        cache_key = self._cache_key(canonical_a, canonical_b)

        cached = await self.cache.get_json(cache_key)
        if cached:
            return InteractionResult(
                drug_a=canonical_a,
                drug_b=canonical_b,
                severity=str(cached.get("severity", "A")),
                risk=str(cached.get("risk", "none")),
                recommendation=str(cached.get("recommendation", "No action")),
                source=str(cached.get("source", "cache")),
            )

        graph_edge = self.graph.get_interaction(canonical_a, canonical_b)
        if graph_edge:
            payload = {
                "severity": graph_edge.severity,
                "risk": graph_edge.risk,
                "recommendation": graph_edge.recommendation,
                "source": graph_edge.source,
            }
            await self.cache.set_json(cache_key, payload, self.settings.interaction_cache_ttl_seconds)
            return InteractionResult(canonical_a, canonical_b, **payload)

        drug_a_row = await drug_repo.get_or_create(canonical_a)
        drug_b_row = await drug_repo.get_or_create(canonical_b)

        local = await interaction_repo.get_pair_interaction(drug_a_row.id, drug_b_row.id)
        if local:
            self.graph.upsert_interaction(
                canonical_a,
                canonical_b,
                local.severity,
                local.risk,
                local.recommendation,
                local.source,
            )
            payload = {
                "severity": local.severity,
                "risk": local.risk,
                "recommendation": local.recommendation,
                "source": local.source,
            }
            await self.cache.set_json(cache_key, payload, self.settings.interaction_cache_ttl_seconds)
            return InteractionResult(canonical_a, canonical_b, **payload)

        external = await self._aggregate_external(canonical_a, canonical_b)

        if external is None:
            severity, risk, recommendation, source = (
                "A",
                "none detected",
                "No action required",
                "local-default",
            )
        else:
            severity = external.severity
            risk = external.risk
            recommendation = external.recommendation
            source = external.source

        await interaction_repo.upsert_pair_interaction(
            drug_a_row.id,
            drug_b_row.id,
            severity,
            risk,
            recommendation,
            source,
        )

        self.graph.upsert_interaction(canonical_a, canonical_b, severity, risk, recommendation, source)
        payload = {
            "severity": severity,
            "risk": risk,
            "recommendation": recommendation,
            "source": source,
        }
        await self.cache.set_json(cache_key, payload, self.settings.interaction_cache_ttl_seconds)

        return InteractionResult(canonical_a, canonical_b, severity, risk, recommendation, source)
