from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.metrics import INTERACTION_CHECKS
from app.core.security import ApiKeyDep
from app.schemas import PrescriptionSafetyRequest, PrescriptionSafetyResponse
from app.services.drug_normalization_service import MedicationInput
from app.services.interaction_service import InteractionService

router = APIRouter(prefix="/v1", tags=["interactions"])


def get_interaction_service(request: Request) -> InteractionService:
    return request.app.state.interaction_service


@router.post("/check-prescription-safety", response_model=PrescriptionSafetyResponse)
async def check_prescription_safety(
    payload: PrescriptionSafetyRequest,
    _api_key: ApiKeyDep,
    session: AsyncSession = Depends(get_db_session),
    interaction_service: InteractionService = Depends(get_interaction_service),
) -> PrescriptionSafetyResponse:
    medications = [
        MedicationInput(
            name=item.drug,
            dose=item.dose,
            unit=item.unit,
            frequency=item.frequency,
        )
        for item in payload.new_medications
    ]
    response = await interaction_service.check_prescription(
        patient_id=payload.patient_id,
        new_drugs=payload.new_drugs,
        session=session,
        new_medications=medications,
    )
    INTERACTION_CHECKS.labels(safe="true" if response.safe else "false").inc()
    return response
