"""classification batch_id column

Revision ID: 0004_classification_batch
Revises: 0003_classification_pipeline
Create Date: 2026-04-28 09:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_classification_batch"
down_revision = "0003_classification_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classification_runs",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_classification_runs_batch_id",
        "classification_runs",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_classification_runs_batch_id", table_name="classification_runs")
    op.drop_column("classification_runs", "batch_id")
