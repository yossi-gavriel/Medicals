from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Drug, PatientMedication


class PatientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_current_medications(self, patient_id: str) -> list[str]:
        stmt = (
            select(Drug.normalized_name)
            .join(PatientMedication, PatientMedication.drug_id == Drug.id)
            .where(PatientMedication.patient_id == patient_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_patient_medications(
        self,
        patient_id: str,
        drug_ids: list[int],
        metadata: dict[int, dict[str, str | None]] | None = None,
    ) -> None:
        for drug_id in drug_ids:
            item_metadata = (metadata or {}).get(drug_id, {})
            existing = await self.session.execute(
                select(PatientMedication).where(
                    PatientMedication.patient_id == patient_id,
                    PatientMedication.drug_id == drug_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row is None:
                self.session.add(
                    PatientMedication(
                        patient_id=patient_id,
                        drug_id=drug_id,
                        dose=item_metadata.get("dose"),
                        unit=item_metadata.get("unit"),
                        frequency=item_metadata.get("frequency"),
                    )
                )
            else:
                row.dose = item_metadata.get("dose")
                row.unit = item_metadata.get("unit")
                row.frequency = item_metadata.get("frequency")

        await self.session.flush()
