from __future__ import annotations

import asyncio

from app.core.database import SessionLocal, create_all
from app.repositories.drug_repository import DrugRepository
from app.repositories.patient_repository import PatientRepository

SEED_DRUGS: list[tuple[str, str | None, bool]] = [
    ("aspirin", "B01AC06", True),
    ("warfarin", "B01AA03", True),
    ("clopidogrel", "B01AC04", True),
    ("simvastatin", "C10AA01", True),
    ("atorvastatin", "C10AA05", True),
    ("rosuvastatin", "C10AA07", True),
    ("clarithromycin", "J01FA09", True),
    ("azithromycin", "J01FA10", True),
    ("lisinopril", "C09AA03", True),
    ("losartan", "C09CA01", True),
    ("spironolactone", "C03DA01", False),
]


async def main() -> None:
    await create_all()
    async with SessionLocal() as session:
        drug_repo = DrugRepository(session)
        patient_repo = PatientRepository(session)

        seeded_ids: list[int] = []
        for name, atc, in_basket in SEED_DRUGS:
            drug = await drug_repo.get_or_create(name, atc)
            drug.is_in_israel_basket = in_basket
            seeded_ids.append(drug.id)

        # Sample patient baseline meds for API demo.
        await patient_repo.set_patient_medications("123", [seeded_ids[1]])  # warfarin
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
