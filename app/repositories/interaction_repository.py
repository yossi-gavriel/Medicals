from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Drug, DrugInteraction


class InteractionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def ordered_ids(drug_a_id: int, drug_b_id: int) -> tuple[int, int]:
        return (drug_a_id, drug_b_id) if drug_a_id <= drug_b_id else (drug_b_id, drug_a_id)

    async def get_pair_interaction(self, drug_a_id: int, drug_b_id: int) -> DrugInteraction | None:
        a_id, b_id = self.ordered_ids(drug_a_id, drug_b_id)
        result = await self.session.execute(
            select(DrugInteraction).where(
                DrugInteraction.drug_a_id == a_id,
                DrugInteraction.drug_b_id == b_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_pair_interaction(
        self,
        drug_a_id: int,
        drug_b_id: int,
        severity: str,
        risk: str,
        recommendation: str,
        source: str,
    ) -> DrugInteraction:
        a_id, b_id = self.ordered_ids(drug_a_id, drug_b_id)
        existing = await self.get_pair_interaction(a_id, b_id)

        if existing:
            existing.severity = severity
            existing.risk = risk
            existing.recommendation = recommendation
            existing.source = source
            await self.session.flush()
            return existing

        interaction = DrugInteraction(
            drug_a_id=a_id,
            drug_b_id=b_id,
            severity=severity,
            risk=risk,
            recommendation=recommendation,
            source=source,
        )
        self.session.add(interaction)
        await self.session.flush()
        return interaction

    async def list_all_interactions(self) -> list[tuple[str, str, DrugInteraction]]:
        drug_a = aliased(Drug)
        drug_b = aliased(Drug)
        stmt = (
            select(drug_a.normalized_name, drug_b.normalized_name, DrugInteraction)
            .join(drug_a, drug_a.id == DrugInteraction.drug_a_id)
            .join(drug_b, drug_b.id == DrugInteraction.drug_b_id)
        )
        result = await self.session.execute(stmt)

        rows: list[tuple[str, str, DrugInteraction]] = list(result.all())
        mapped: list[tuple[str, str, DrugInteraction]] = []
        for drug_a_name, drug_b_name, interaction in rows:
            mapped.append((drug_a_name, drug_b_name, interaction))
        return mapped
