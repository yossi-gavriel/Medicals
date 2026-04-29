from __future__ import annotations

from pydantic import BaseModel


class InteractionIssue(BaseModel):
    drug: str
    conflicts_with: str
    severity: str
    risk: str
    recommendation: str
    source: str
    explanation: str


class SuggestedAlternative(BaseModel):
    drug: str
    reason: str
    interaction_risk: str


class PrescriptionSafetyResponse(BaseModel):
    safe: bool
    issues: list[InteractionIssue]
    suggested_alternatives: list[SuggestedAlternative]
