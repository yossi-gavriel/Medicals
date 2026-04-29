from __future__ import annotations

import asyncio

from app.core.database import SessionLocal, create_all
from app.repositories.drug_repository import DrugRepository

SYNONYM_SEED: dict[str, list[str]] = {
    "aspirin": ["acetylsalicylic acid", "asa", "cartia"],
    "metformin": ["glucophage"],
    "atorvastatin": ["lipitor"],
}


async def main() -> None:
    await create_all()
    async with SessionLocal() as session:
        drug_repo = DrugRepository(session)
        total_synonyms = 0

        for canonical_name, synonyms in SYNONYM_SEED.items():
            drug = await drug_repo.get_or_create(canonical_name)
            total_synonyms += await drug_repo.add_synonyms(drug.id, synonyms)

        await session.commit()
        print(f"Seeded synonym rows: {total_synonyms}")


if __name__ == "__main__":
    asyncio.run(main())
