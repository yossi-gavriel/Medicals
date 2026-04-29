from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, UUIDType


class ClassificationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ClassificationRun(Base):
    __tablename__ = "classification_runs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_classification_runs_job_id"),
        Index("ix_classification_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUIDType, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    procedure_code: Mapped[str] = mapped_column(String(128))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(16), default=ClassificationStatus.PENDING.value)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    prompt_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    used_definition: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    idx_results: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    raw_model_output: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    masked: Mapped[bool] = mapped_column(Boolean, default=True)
    pii_masked_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    document = relationship("Document", back_populates="runs")
