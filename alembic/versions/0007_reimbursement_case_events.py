"""reimbursement case lifecycle events

Revision ID: 0007_reimbursement_case_events
Revises: 0006_compliance_dashboard
Create Date: 2026-04-28 15:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0007_reimbursement_case_events"
down_revision = "0006_compliance_dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reimbursement_case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["reimbursement_cases.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_reimbursement_case_events_case_id",
        "reimbursement_case_events",
        ["case_id"],
    )
    op.create_index(
        "ix_reimbursement_case_events_tenant_id",
        "reimbursement_case_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_reimbursement_case_events_event_type",
        "reimbursement_case_events",
        ["event_type"],
    )
    op.create_index(
        "ix_reimbursement_case_events_created_at",
        "reimbursement_case_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reimbursement_case_events_created_at", table_name="reimbursement_case_events")
    op.drop_index("ix_reimbursement_case_events_event_type", table_name="reimbursement_case_events")
    op.drop_index("ix_reimbursement_case_events_tenant_id", table_name="reimbursement_case_events")
    op.drop_index("ix_reimbursement_case_events_case_id", table_name="reimbursement_case_events")
    op.drop_table("reimbursement_case_events")
