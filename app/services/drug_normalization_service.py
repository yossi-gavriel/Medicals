from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.repositories.drug_repository import DrugRepository


@dataclass(slots=True)
class MedicationInput:
    name: str
    dose: str | None = None
    unit: str | None = None
    frequency: str | None = None


@dataclass(slots=True)
class NormalizedMedication:
    canonical_name: str
    dose: str | None = None
    unit: str | None = None
    frequency: str | None = None


class DrugNormalizationService:
    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.strip().lower()

    async def normalize_name(self, raw_name: str, drug_repo: DrugRepository) -> str:
        normalized = self._normalize_text(raw_name)
        if not normalized:
            return ""
        return await drug_repo.resolve_canonical_name(normalized)

    async def normalize_names(self, raw_names: Sequence[str], drug_repo: DrugRepository) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_name in raw_names:
            canonical = await self.normalize_name(raw_name, drug_repo)
            if canonical and canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)
        return normalized

    async def normalize_medications(
        self,
        medications: Sequence[MedicationInput],
        drug_repo: DrugRepository,
    ) -> list[NormalizedMedication]:
        normalized: list[NormalizedMedication] = []
        seen: set[str] = set()
        for medication in medications:
            canonical = await self.normalize_name(medication.name, drug_repo)
            if not canonical or canonical in seen:
                continue
            normalized.append(
                NormalizedMedication(
                    canonical_name=canonical,
                    dose=medication.dose,
                    unit=medication.unit,
                    frequency=medication.frequency,
                )
            )
            seen.add(canonical)
        return normalized
