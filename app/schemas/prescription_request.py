from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class MedicationEntry(BaseModel):
    drug: str = Field(min_length=1)
    dose: str | None = None
    unit: str | None = None
    frequency: str | None = None

    @model_validator(mode="after")
    def normalize_drug(self) -> "MedicationEntry":
        self.drug = self.drug.strip().lower()
        if not self.drug:
            raise ValueError("drug must be non-empty")
        return self


class PrescriptionSafetyRequest(BaseModel):
    patient_id: str = Field(min_length=1, max_length=128)
    new_drugs: list[str] = Field(default_factory=list)
    new_medications: list[MedicationEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_drugs(self) -> "PrescriptionSafetyRequest":
        normalized = []
        for item in self.new_drugs:
            drug = item.strip().lower()
            if drug:
                normalized.append(drug)
        self.new_drugs = list(dict.fromkeys(normalized))

        if not self.new_drugs and not self.new_medications:
            raise ValueError("provide at least one entry in new_drugs or new_medications")
        return self
