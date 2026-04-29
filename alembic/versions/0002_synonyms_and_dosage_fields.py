"""add drug synonyms and dosage metadata

Revision ID: 0002_synonyms_and_dosage_fields
Revises: 0001_initial
Create Date: 2026-03-08 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_synonyms_and_dosage_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drug_synonyms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("drug_id", sa.Integer(), nullable=False),
        sa.Column("synonym", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["drug_id"], ["drugs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("synonym", name="uq_drug_synonym"),
    )
    op.create_index("ix_drug_synonyms_drug_id", "drug_synonyms", ["drug_id"])
    op.create_index("ix_drug_synonyms_synonym", "drug_synonyms", ["synonym"])

    op.add_column("patient_medications", sa.Column("dose", sa.String(length=64), nullable=True))
    op.add_column("patient_medications", sa.Column("unit", sa.String(length=32), nullable=True))
    op.add_column("patient_medications", sa.Column("frequency", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("patient_medications", "frequency")
    op.drop_column("patient_medications", "unit")
    op.drop_column("patient_medications", "dose")

    op.drop_index("ix_drug_synonyms_synonym", table_name="drug_synonyms")
    op.drop_index("ix_drug_synonyms_drug_id", table_name="drug_synonyms")
    op.drop_table("drug_synonyms")
