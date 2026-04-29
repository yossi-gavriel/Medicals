from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Drug(Base):
    __tablename__ = "drugs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    atc_code: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    is_in_israel_basket: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    outgoing_interactions = relationship(
        "DrugInteraction", foreign_keys="DrugInteraction.drug_a_id", back_populates="drug_a"
    )
    incoming_interactions = relationship(
        "DrugInteraction", foreign_keys="DrugInteraction.drug_b_id", back_populates="drug_b"
    )
    synonyms = relationship("DrugSynonym", back_populates="drug", cascade="all, delete-orphan")
