from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class InteractionSeverity(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    X = "X"


class DrugInteraction(Base):
    __tablename__ = "drug_interactions"
    __table_args__ = (
        UniqueConstraint("drug_a_id", "drug_b_id", name="uq_drug_pair"),
        Index("ix_drug_interactions_severity", "severity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    drug_a_id: Mapped[int] = mapped_column(ForeignKey("drugs.id", ondelete="CASCADE"), index=True)
    drug_b_id: Mapped[int] = mapped_column(ForeignKey("drugs.id", ondelete="CASCADE"), index=True)

    severity: Mapped[str] = mapped_column(String(1), default=InteractionSeverity.A.value)
    risk: Mapped[str] = mapped_column(String(512), default="none")
    recommendation: Mapped[str] = mapped_column(String(1024), default="No major action required")
    source: Mapped[str] = mapped_column(String(64), default="local")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    drug_a = relationship("Drug", foreign_keys=[drug_a_id], back_populates="outgoing_interactions")
    drug_b = relationship("Drug", foreign_keys=[drug_b_id], back_populates="incoming_interactions")
