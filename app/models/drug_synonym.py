from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DrugSynonym(Base):
    __tablename__ = "drug_synonyms"
    __table_args__ = (UniqueConstraint("synonym", name="uq_drug_synonym"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    drug_id: Mapped[int] = mapped_column(ForeignKey("drugs.id", ondelete="CASCADE"), index=True)
    synonym: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    drug = relationship("Drug", back_populates="synonyms")
