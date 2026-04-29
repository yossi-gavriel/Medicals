"""medical classifier connector audit logs

Revision ID: 0008_medical_classifier_audit_logs
Revises: 0007_reimbursement_case_events
Create Date: 2026-04-29 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0008_medical_classifier_audit_logs"
down_revision = "0007_reimbursement_case_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "medical_classifier_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("api_key_id", sa.String(length=128), nullable=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("file_name", sa.String(length=256), nullable=False),
        sa.Column("doc_type", sa.Integer(), nullable=True),
        sa.Column("treatment_code", sa.String(length=128), nullable=False),
        sa.Column("subject_ind", sa.String(length=64), nullable=True),
        sa.Column("document_text_hash", sa.String(length=64), nullable=False),
        sa.Column("cleaned_desc_hash", sa.String(length=64), nullable=True),
        sa.Column("cleaned_full_hash", sa.String(length=64), nullable=True),
        sa.Column("text_length", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_code", sa.SmallInteger(), nullable=True),
        sa.Column("indexes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_medical_classifier_audit_logs_request_id",
        "medical_classifier_audit_logs",
        ["request_id"],
    )
    op.create_index(
        "ix_medical_classifier_audit_logs_api_key_id",
        "medical_classifier_audit_logs",
        ["api_key_id"],
    )
    op.create_index(
        "ix_medical_classifier_audit_logs_tenant_id",
        "medical_classifier_audit_logs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_medical_classifier_audit_logs_treatment_code",
        "medical_classifier_audit_logs",
        ["treatment_code"],
    )
    op.create_index(
        "ix_medical_classifier_audit_logs_status",
        "medical_classifier_audit_logs",
        ["status"],
    )
    op.create_index(
        "ix_medical_classifier_audit_logs_created_at",
        "medical_classifier_audit_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_medical_classifier_audit_logs_created_at", table_name="medical_classifier_audit_logs")
    op.drop_index("ix_medical_classifier_audit_logs_status", table_name="medical_classifier_audit_logs")
    op.drop_index("ix_medical_classifier_audit_logs_treatment_code", table_name="medical_classifier_audit_logs")
    op.drop_index("ix_medical_classifier_audit_logs_tenant_id", table_name="medical_classifier_audit_logs")
    op.drop_index("ix_medical_classifier_audit_logs_api_key_id", table_name="medical_classifier_audit_logs")
    op.drop_index("ix_medical_classifier_audit_logs_request_id", table_name="medical_classifier_audit_logs")
    op.drop_table("medical_classifier_audit_logs")
