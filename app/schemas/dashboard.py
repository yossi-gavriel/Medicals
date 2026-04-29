from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReimbursementCaseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    note: str | None = None
    estimated_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def _normalize(self) -> ReimbursementCaseUpdateRequest:
        if self.status is not None:
            self.status = self.status.strip()
            if not self.status:
                raise ValueError("status must not be blank")
        if self.note is not None:
            self.note = self.note.strip() or None
        if self.currency is not None:
            self.currency = self.currency.strip().upper()
            if not self.currency:
                self.currency = None
        return self

    def update_fields(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.model_fields_set}


__all__ = ["ReimbursementCaseUpdateRequest"]
