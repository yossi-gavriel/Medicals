from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Drug, DrugSynonym


class DrugRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def normalize_name(name: str) -> str:
        return name.strip().lower()

    async def get_by_name(self, name: str) -> Drug | None:
        normalized = self.normalize_name(name)
        result = await self.session.execute(select(Drug).where(Drug.normalized_name == normalized))
        return result.scalar_one_or_none()

    async def get_by_synonym(self, name: str) -> Drug | None:
        normalized = self.normalize_name(name)
        result = await self.session.execute(
            select(Drug).join(DrugSynonym, DrugSynonym.drug_id == Drug.id).where(DrugSynonym.synonym == normalized)
        )
        return result.scalar_one_or_none()

    async def get_by_name_or_synonym(self, name: str) -> Drug | None:
        direct = await self.get_by_name(name)
        if direct:
            return direct
        return await self.get_by_synonym(name)

    async def resolve_canonical_name(self, name: str) -> str:
        drug = await self.get_by_name_or_synonym(name)
        if drug:
            return drug.normalized_name
        return self.normalize_name(name)

    async def get_or_create(self, name: str, atc_code: str | None = None) -> Drug:
        normalized = self.normalize_name(name)
        drug = await self.get_by_name_or_synonym(normalized)
        if drug:
            if atc_code and drug.atc_code != atc_code:
                drug.atc_code = atc_code
                await self.session.flush()
            return drug

        drug = Drug(name=name.strip(), normalized_name=normalized, atc_code=atc_code)
        self.session.add(drug)
        await self.session.flush()
        return drug

    async def add_synonym(self, drug_id: int, synonym: str) -> DrugSynonym | None:
        normalized = self.normalize_name(synonym)
        if not normalized:
            return None

        canonical = await self.session.execute(select(Drug).where(Drug.normalized_name == normalized))
        canonical_drug = canonical.scalar_one_or_none()
        if canonical_drug:
            return None

        existing = await self.session.execute(select(DrugSynonym).where(DrugSynonym.synonym == normalized))
        synonym_row = existing.scalar_one_or_none()
        if synonym_row:
            if synonym_row.drug_id != drug_id:
                synonym_row.drug_id = drug_id
                await self.session.flush()
            return synonym_row

        synonym_row = DrugSynonym(drug_id=drug_id, synonym=normalized)
        self.session.add(synonym_row)
        await self.session.flush()
        return synonym_row

    async def add_synonyms(self, drug_id: int, synonyms: Sequence[str]) -> int:
        inserted = 0
        for synonym in synonyms:
            row = await self.add_synonym(drug_id, synonym)
            if row is not None:
                inserted += 1
        return inserted

    async def get_many_by_names(self, names: Sequence[str]) -> list[Drug]:
        normalized: list[str] = []
        for item in names:
            clean = self.normalize_name(item)
            if clean:
                normalized.append(clean)
        if not normalized:
            return []
        result = await self.session.execute(
            select(Drug).outerjoin(DrugSynonym, DrugSynonym.drug_id == Drug.id).where(
                (Drug.normalized_name.in_(normalized)) | (DrugSynonym.synonym.in_(normalized))
            )
        )
        return list({item.id: item for item in result.scalars().all()}.values())

    async def find_by_atc_class(self, atc_code: str | None, limit: int = 50) -> list[Drug]:
        if not atc_code:
            return []
        prefix = atc_code[:4]
        result = await self.session.execute(
            select(Drug)
            .where(Drug.atc_code.like(f"{prefix}%"), Drug.is_in_israel_basket.is_(True))
            .order_by(Drug.normalized_name)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_israel_basket_flags(self, basket_drugs: Sequence[str]) -> None:
        normalized = [self.normalize_name(item) for item in basket_drugs]

        await self.session.execute(update(Drug).values(is_in_israel_basket=False))
        if normalized:
            await self.session.execute(
                update(Drug)
                .where(Drug.normalized_name.in_(normalized))
                .values(is_in_israel_basket=True)
            )
        await self.session.flush()

    async def list_common_drugs(self, limit: int = 2000) -> list[Drug]:
        result = await self.session.execute(
            select(Drug).order_by(Drug.is_in_israel_basket.desc(), Drug.id.asc()).limit(limit)
        )
        return list(result.scalars().all())
