"""extraction engine persistence tables

Revision ID: 0005_extraction_persistence
Revises: 0004_classification_batch
Create Date: 2026-04-28 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_extraction_persistence"
down_revision = "0004_classification_batch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.String(length=256), nullable=False),
        sa.Column("spec_version", sa.String(length=32), nullable=True),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("masked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pii_masked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_extraction_runs_document_id", "extraction_runs", ["document_id"])
    op.create_index("ix_extraction_runs_spec_hash", "extraction_runs", ["spec_hash"])
    op.create_index("ix_extraction_runs_tenant_id", "extraction_runs", ["tenant_id"])

    op.create_table(
        "extraction_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.String(length=256), nullable=False),
        sa.Column("treatment_code", sa.String(length=128), nullable=False),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_extraction_rows_run_id", "extraction_rows", ["run_id"])
    op.create_index(
        "ix_extraction_rows_doc_treatment",
        "extraction_rows",
        ["document_id", "treatment_code"],
    )

    op.create_table(
        "extraction_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treatment_code", sa.String(length=128), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_extraction_audit_run_treatment",
        "extraction_audit",
        ["run_id", "treatment_code"],
    )
    op.create_index(
        "ix_extraction_audit_field_name",
        "extraction_audit",
        ["field_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_audit_field_name", table_name="extraction_audit")
    op.drop_index("ix_extraction_audit_run_treatment", table_name="extraction_audit")
    op.drop_table("extraction_audit")

    op.drop_index("ix_extraction_rows_doc_treatment", table_name="extraction_rows")
    op.drop_index("ix_extraction_rows_run_id", table_name="extraction_rows")
    op.drop_table("extraction_rows")

    op.drop_index("ix_extraction_runs_tenant_id", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_spec_hash", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_document_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
