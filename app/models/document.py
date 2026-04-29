from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, UUIDType


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("tenant_id", "document_hash", name="uq_documents_tenant_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    document_hash: Mapped[str] = mapped_column(String(64))
    procedure_code: Mapped[str] = mapped_column(String(128), index=True)
    storage_uri: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer)
    source_system: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_document_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs = relationship(
        "ClassificationRun",
        back_populates="document",
        cascade="all, delete-orphan",
    )
