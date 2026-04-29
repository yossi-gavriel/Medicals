"""compliance results and reimbursement cases

Revision ID: 0006_compliance_dashboard
Revises: 0005_extraction_persistence
Create Date: 2026-04-28 14:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0006_compliance_dashboard"
down_revision = "0005_extraction_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("extraction_runs", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column(
        "extraction_runs",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    op.create_table(
        "compliance_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.String(length=256), nullable=False),
        sa.Column("treatment_code", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("recommended_action", sa.String(length=64), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insufficient_data_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("highest_severity", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_compliance_results_run_id", "compliance_results", ["run_id"])
    op.create_index(
        "ix_compliance_results_doc_treatment",
        "compliance_results",
        ["document_id", "treatment_code"],
    )
    op.create_index("ix_compliance_results_status", "compliance_results", ["status"])
    op.create_index(
        "ix_compliance_results_recommended_action",
        "compliance_results",
        ["recommended_action"],
    )

    op.create_table(
        "compliance_rule_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("compliance_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treatment_code", sa.String(length=128), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("operator", sa.String(length=32), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actual", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["compliance_result_id"],
            ["compliance_results.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_compliance_rule_results_compliance_result_id",
        "compliance_rule_results",
        ["compliance_result_id"],
    )
    op.create_index(
        "ix_compliance_rule_results_run_treatment",
        "compliance_rule_results",
        ["run_id", "treatment_code"],
    )
    op.create_index(
        "ix_compliance_rule_results_rule_id",
        "compliance_rule_results",
        ["rule_id"],
    )
    op.create_index(
        "ix_compliance_rule_results_status",
        "compliance_rule_results",
        ["status"],
    )

    op.create_table(
        "reimbursement_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compliance_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("document_id", sa.String(length=256), nullable=False),
        sa.Column("treatment_code", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("estimated_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["compliance_result_id"],
            ["compliance_results.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_reimbursement_cases_tenant_id", "reimbursement_cases", ["tenant_id"])
    op.create_index("ix_reimbursement_cases_status", "reimbursement_cases", ["status"])
    op.create_index(
        "ix_reimbursement_cases_treatment_code",
        "reimbursement_cases",
        ["treatment_code"],
    )
    op.create_index("ix_reimbursement_cases_created_at", "reimbursement_cases", ["created_at"])
    op.create_index(
        "ix_reimbursement_cases_tenant_status",
        "reimbursement_cases",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_reimbursement_cases_tenant_treatment",
        "reimbursement_cases",
        ["tenant_id", "treatment_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_reimbursement_cases_tenant_treatment", table_name="reimbursement_cases")
    op.drop_index("ix_reimbursement_cases_tenant_status", table_name="reimbursement_cases")
    op.drop_index("ix_reimbursement_cases_created_at", table_name="reimbursement_cases")
    op.drop_index("ix_reimbursement_cases_treatment_code", table_name="reimbursement_cases")
    op.drop_index("ix_reimbursement_cases_status", table_name="reimbursement_cases")
    op.drop_index("ix_reimbursement_cases_tenant_id", table_name="reimbursement_cases")
    op.drop_table("reimbursement_cases")

    op.drop_index("ix_compliance_rule_results_status", table_name="compliance_rule_results")
    op.drop_index("ix_compliance_rule_results_rule_id", table_name="compliance_rule_results")
    op.drop_index(
        "ix_compliance_rule_results_run_treatment",
        table_name="compliance_rule_results",
    )
    op.drop_index(
        "ix_compliance_rule_results_compliance_result_id",
        table_name="compliance_rule_results",
    )
    op.drop_table("compliance_rule_results")

    op.drop_index("ix_compliance_results_recommended_action", table_name="compliance_results")
    op.drop_index("ix_compliance_results_status", table_name="compliance_results")
    op.drop_index("ix_compliance_results_doc_treatment", table_name="compliance_results")
    op.drop_index("ix_compliance_results_run_id", table_name="compliance_results")
    op.drop_table("compliance_results")

    op.drop_column("extraction_runs", "metadata")
    op.drop_column("extraction_runs", "duration_ms")
