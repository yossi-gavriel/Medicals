from __future__ import annotations

import pytest

from app.services.drug_normalization_service import DrugNormalizationService
from app.services.drug_normalization_service import MedicationInput


class FakeDrugRepository:
    def __init__(self) -> None:
        self.aliases = {
            "asa": "aspirin",
            "acetylsalicylic acid": "aspirin",
            "cartia": "aspirin",
            "glucophage": "metformin",
        }

    async def resolve_canonical_name(self, name: str) -> str:
        normalized = name.strip().lower()
        return self.aliases.get(normalized, normalized)


@pytest.mark.asyncio
async def test_normalize_names_resolves_synonyms_and_deduplicates() -> None:
    service = DrugNormalizationService()
    repo = FakeDrugRepository()

    normalized = await service.normalize_names(
        ["ASA", "aspirin", "Acetylsalicylic Acid", "Metformin", "Glucophage"],
        repo,  # type: ignore[arg-type]
    )
    assert normalized == ["aspirin", "metformin"]


@pytest.mark.asyncio
async def test_normalize_medications_keeps_dosage_metadata() -> None:
    service = DrugNormalizationService()
    repo = FakeDrugRepository()

    meds = await service.normalize_medications(
        [
            MedicationInput(name="Cartia", dose="100", unit="mg", frequency="daily"),
            MedicationInput(name="ASA", dose="75", unit="mg", frequency="daily"),
        ],
        repo,  # type: ignore[arg-type]
    )

    assert len(meds) == 1
    assert meds[0].canonical_name == "aspirin"
    assert meds[0].dose == "100"
    assert meds[0].unit == "mg"
    assert meds[0].frequency == "daily"
