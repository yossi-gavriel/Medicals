"""classification pipeline tables

Revision ID: 0003_classification_pipeline
Revises: 0002_synonyms_and_dosage_fields
Create Date: 2026-04-27 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_classification_pipeline"
down_revision = "0002_synonyms_and_dosage_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("document_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("procedure_code", sa.String(length=128), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=128), nullable=True),
        sa.Column("external_document_id", sa.String(length=256), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "document_hash", name="uq_documents_tenant_hash"),
    )
    op.create_index("ix_documents_procedure_code", "documents", ["procedure_code"])
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_external_document_id", "documents", ["external_document_id"])

    op.create_table(
        "classification_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("procedure_code", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("prompt_source", sa.String(length=32), nullable=True),
        sa.Column("used_definition", sa.Boolean(), nullable=True),
        sa.Column("result_code", sa.SmallInteger(), nullable=True),
        sa.Column("idx_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_model_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_provider", sa.String(length=64), nullable=True),
        sa.Column("llm_model", sa.String(length=128), nullable=True),
        sa.Column("masked", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pii_masked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_classification_runs_job_id"),
    )
    op.create_index(
        "ix_classification_runs_status_created_at",
        "classification_runs",
        ["status", "created_at"],
    )
    op.create_index("ix_classification_runs_document_id", "classification_runs", ["document_id"])
    op.create_index("ix_classification_runs_tenant_id", "classification_runs", ["tenant_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("destination_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_outbox_events_status_next_attempt_at",
        "outbox_events",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_next_attempt_at", table_name="outbox_events")
    op.drop_table("outbox_events")

    op.drop_index("ix_classification_runs_tenant_id", table_name="classification_runs")
    op.drop_index("ix_classification_runs_document_id", table_name="classification_runs")
    op.drop_index("ix_classification_runs_status_created_at", table_name="classification_runs")
    op.drop_table("classification_runs")

    op.drop_index("ix_documents_external_document_id", table_name="documents")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_index("ix_documents_procedure_code", table_name="documents")
    op.drop_table("documents")
