from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, UUIDType


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    spec_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    masked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pii_masked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONType,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    rows = relationship(
        "ExtractionRow",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    audit_entries = relationship(
        "ExtractionAudit",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    compliance_results = relationship(
        "ComplianceResult",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ExtractionRow(Base):
    __tablename__ = "extraction_rows"
    __table_args__ = (
        Index("ix_extraction_rows_run_id", "run_id"),
        Index("ix_extraction_rows_doc_treatment", "document_id", "treatment_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(String(256), nullable=False)
    treatment_code: Mapped[str] = mapped_column(String(128), nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    run = relationship("ExtractionRun", back_populates="rows")


class ExtractionAudit(Base):
    __tablename__ = "extraction_audit"
    __table_args__ = (
        Index("ix_extraction_audit_run_treatment", "run_id", "treatment_code"),
        Index("ix_extraction_audit_field_name", "field_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    treatment_code: Mapped[str] = mapped_column(String(128), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[Any | None] = mapped_column(JSONType, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    run = relationship("ExtractionRun", back_populates="audit_entries")


class ComplianceResult(Base):
    __tablename__ = "compliance_results"
    __table_args__ = (
        Index("ix_compliance_results_run_id", "run_id"),
        Index("ix_compliance_results_doc_treatment", "document_id", "treatment_code"),
        Index("ix_compliance_results_status", "status"),
        Index("ix_compliance_results_recommended_action", "recommended_action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(String(256), nullable=False)
    treatment_code: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(64), nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    insufficient_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    highest_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    run = relationship("ExtractionRun", back_populates="compliance_results")
    rule_results = relationship(
        "ComplianceRuleResult",
        back_populates="compliance_result",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reimbursement_cases = relationship(
        "ReimbursementCase",
        back_populates="compliance_result",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ComplianceRuleResult(Base):
    __tablename__ = "compliance_rule_results"
    __table_args__ = (
        Index("ix_compliance_rule_results_compliance_result_id", "compliance_result_id"),
        Index("ix_compliance_rule_results_run_treatment", "run_id", "treatment_code"),
        Index("ix_compliance_rule_results_rule_id", "rule_id"),
        Index("ix_compliance_rule_results_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    compliance_result_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("compliance_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    treatment_code: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    operator: Mapped[str] = mapped_column(String(32), nullable=False)
    expected: Mapped[Any | None] = mapped_column(JSONType, nullable=True)
    actual: Mapped[Any | None] = mapped_column(JSONType, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    compliance_result = relationship("ComplianceResult", back_populates="rule_results")


class ReimbursementCase(Base):
    __tablename__ = "reimbursement_cases"
    __table_args__ = (
        Index("ix_reimbursement_cases_tenant_id", "tenant_id"),
        Index("ix_reimbursement_cases_status", "status"),
        Index("ix_reimbursement_cases_treatment_code", "treatment_code"),
        Index("ix_reimbursement_cases_created_at", "created_at"),
        Index("ix_reimbursement_cases_tenant_status", "tenant_id", "status"),
        Index("ix_reimbursement_cases_tenant_treatment", "tenant_id", "treatment_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    compliance_result_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("compliance_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_id: Mapped[str] = mapped_column(String(256), nullable=False)
    treatment_code: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    run = relationship("ExtractionRun")
    compliance_result = relationship("ComplianceResult", back_populates="reimbursement_cases")
    events = relationship(
        "ReimbursementCaseEvent",
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ReimbursementCaseEvent(Base):
    __tablename__ = "reimbursement_case_events"
    __table_args__ = (
        Index("ix_reimbursement_case_events_case_id", "case_id"),
        Index("ix_reimbursement_case_events_tenant_id", "tenant_id"),
        Index("ix_reimbursement_case_events_event_type", "event_type"),
        Index("ix_reimbursement_case_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("reimbursement_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONType,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    case = relationship("ReimbursementCase", back_populates="events")
