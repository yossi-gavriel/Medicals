from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, JSONType, UUIDType


class MedicalClassifierAuditLog(Base):
    __tablename__ = "medical_classifier_audit_logs"
    __table_args__ = (
        Index("ix_medical_classifier_audit_logs_request_id", "request_id"),
        Index("ix_medical_classifier_audit_logs_api_key_id", "api_key_id"),
        Index("ix_medical_classifier_audit_logs_tenant_id", "tenant_id"),
        Index("ix_medical_classifier_audit_logs_treatment_code", "treatment_code"),
        Index("ix_medical_classifier_audit_logs_status", "status"),
        Index("ix_medical_classifier_audit_logs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    doc_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    treatment_code: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_ind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cleaned_desc_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cleaned_full_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    indexes_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
