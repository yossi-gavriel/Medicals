"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-03-08 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drugs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("atc_code", sa.String(length=32), nullable=True),
        sa.Column("is_in_israel_basket", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_index("ix_drugs_name", "drugs", ["name"])
    op.create_index("ix_drugs_normalized_name", "drugs", ["normalized_name"])
    op.create_index("ix_drugs_atc_code", "drugs", ["atc_code"])
    op.create_index("ix_drugs_is_in_israel_basket", "drugs", ["is_in_israel_basket"])

    op.create_table(
        "drug_interactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("drug_a_id", sa.Integer(), nullable=False),
        sa.Column("drug_b_id", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=1), nullable=False, server_default="A"),
        sa.Column("risk", sa.String(length=512), nullable=False, server_default="none"),
        sa.Column(
            "recommendation",
            sa.String(length=1024),
            nullable=False,
            server_default="No major action required",
        ),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["drug_a_id"], ["drugs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["drug_b_id"], ["drugs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("drug_a_id", "drug_b_id", name="uq_drug_pair"),
    )
    op.create_index("ix_drug_interactions_drug_a_id", "drug_interactions", ["drug_a_id"])
    op.create_index("ix_drug_interactions_drug_b_id", "drug_interactions", ["drug_b_id"])
    op.create_index("ix_drug_interactions_severity", "drug_interactions", ["severity"])

    op.create_table(
        "patient_medications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("patient_id", sa.String(length=128), nullable=False),
        sa.Column("drug_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["drug_id"], ["drugs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_id", "drug_id", name="uq_patient_drug"),
    )
    op.create_index("ix_patient_medications_drug_id", "patient_medications", ["drug_id"])
    op.create_index("ix_patient_medications_patient_id", "patient_medications", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_patient_medications_patient_id", table_name="patient_medications")
    op.drop_index("ix_patient_medications_drug_id", table_name="patient_medications")
    op.drop_table("patient_medications")

    op.drop_index("ix_drug_interactions_severity", table_name="drug_interactions")
    op.drop_index("ix_drug_interactions_drug_b_id", table_name="drug_interactions")
    op.drop_index("ix_drug_interactions_drug_a_id", table_name="drug_interactions")
    op.drop_table("drug_interactions")

    op.drop_index("ix_drugs_is_in_israel_basket", table_name="drugs")
    op.drop_index("ix_drugs_atc_code", table_name="drugs")
    op.drop_index("ix_drugs_normalized_name", table_name="drugs")
    op.drop_index("ix_drugs_name", table_name="drugs")
    op.drop_table("drugs")
