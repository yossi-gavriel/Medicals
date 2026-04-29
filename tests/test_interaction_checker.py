from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.algorithms.interaction_checker import InteractionChecker
from app.algorithms.interaction_graph import InteractionGraph
from app.core.cache import CacheClient
from app.core.settings import Settings
from app.integrations.base import ExternalInteraction


@dataclass
class FakeDrug:
    id: int
    normalized_name: str


@dataclass
class FakeInteraction:
    severity: str
    risk: str
    recommendation: str
    source: str


class FakeDrugRepository:
    def __init__(self) -> None:
        self._items: dict[str, FakeDrug] = {}
        self._next_id = 1

    async def resolve_canonical_name(self, name: str) -> str:
        aliases = {"asa": "aspirin", "acetylsalicylic acid": "aspirin"}
        return aliases.get(name.strip().lower(), name.strip().lower())

    async def get_or_create(self, name: str) -> FakeDrug:
        normalized = name.strip().lower()
        if normalized not in self._items:
            self._items[normalized] = FakeDrug(id=self._next_id, normalized_name=normalized)
            self._next_id += 1
        return self._items[normalized]


class FakeInteractionRepository:
    def __init__(self) -> None:
        self._pairs: dict[tuple[int, int], FakeInteraction] = {}

    async def get_pair_interaction(self, drug_a_id: int, drug_b_id: int) -> FakeInteraction | None:
        key = tuple(sorted((drug_a_id, drug_b_id)))
        return self._pairs.get(key)

    async def upsert_pair_interaction(
        self,
        drug_a_id: int,
        drug_b_id: int,
        severity: str,
        risk: str,
        recommendation: str,
        source: str,
    ) -> FakeInteraction:
        key = tuple(sorted((drug_a_id, drug_b_id)))
        interaction = FakeInteraction(
            severity=severity,
            risk=risk,
            recommendation=recommendation,
            source=source,
        )
        self._pairs[key] = interaction
        return interaction


class FakeProvider:
    def __init__(self, provider_key: str, provider_name: str, severity: str | None) -> None:
        self.provider_key = provider_key
        self.provider_name = provider_name
        self._severity = severity
        self.calls = 0

    async def get_drug_interactions(self, drug_a: str, drug_b: str) -> ExternalInteraction | None:
        self.calls += 1
        pair = tuple(sorted((drug_a.strip().lower(), drug_b.strip().lower())))
        if pair != ("aspirin", "warfarin") or self._severity is None:
            return None
        return ExternalInteraction(
            severity=self._severity,
            risk=f"{self.provider_name} risk",
            recommendation="monitor",
            source=self.provider_name,
        )


@pytest.mark.asyncio
async def test_interaction_checker_aggregates_providers_and_uses_cache() -> None:
    settings = Settings(provider_priority=["lexicomp", "drugbank"])
    cache = CacheClient()
    providers = [
        FakeProvider("drugbank", "DrugBank", "C"),
        FakeProvider("lexicomp", "Lexicomp", "D"),
    ]
    checker = InteractionChecker(settings, cache, InteractionGraph(), providers)

    drugs = FakeDrugRepository()
    interactions = FakeInteractionRepository()

    first = await checker.check_pair("ASA", "warfarin", drugs, interactions)
    assert first.severity == "D"
    assert first.source == "Lexicomp"
    assert providers[0].calls == 1
    assert providers[1].calls == 1

    second = await checker.check_pair("aspirin", "warfarin", drugs, interactions)
    assert second.severity == "D"
    assert providers[0].calls == 1
    assert providers[1].calls == 1


@pytest.mark.asyncio
async def test_interaction_checker_respects_priority_on_tie() -> None:
    settings = Settings(provider_priority=["lexicomp", "drugbank"])
    cache = CacheClient()
    providers = [
        FakeProvider("drugbank", "DrugBank", "D"),
        FakeProvider("lexicomp", "Lexicomp", "D"),
    ]
    checker = InteractionChecker(settings, cache, InteractionGraph(), providers)

    drugs = FakeDrugRepository()
    interactions = FakeInteractionRepository()

    result = await checker.check_pair("aspirin", "warfarin", drugs, interactions)
    assert result.severity == "D"
    assert result.source == "Lexicomp"
