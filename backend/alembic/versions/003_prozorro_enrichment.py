"""Add Prozorro enrichment and EDRPOU fields.
 
Revision ID: 003_prozorro_enrichment
Revises: 002_person_metadata
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa


revision = "003_prozorro_enrichment"
down_revision = "002_person_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the prozorro_enrichment table
    op.create_table(
        "prozorro_enrichment",
        sa.Column("edrpou", sa.String(8), nullable=False),
        sa.Column("is_supplier", sa.Boolean(), nullable=True),
        sa.Column("contract_count", sa.Integer(), nullable=True),
        sa.Column("total_value_uah", sa.Numeric(), nullable=True),
        sa.Column("most_recent_contract_date", sa.Date(), nullable=True),
        sa.Column("procuring_entity_edrpou", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("enriched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("enrichment_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("edrpou"),
    )

    # Add EDRPOU columns to the declarant_profiles table
    op.add_column("declarant_profiles", sa.Column("employer_edrpou", sa.String(8), nullable=True))
    op.add_column("declarant_profiles", sa.Column("income_source_edrpous", sa.ARRAY(sa.Text()), nullable=True))
    op.add_column("declarant_profiles", sa.Column("securities_edrpous", sa.ARRAY(sa.Text()), nullable=True))
    op.add_column("declarant_profiles", sa.Column("bank_edrpous", sa.ARRAY(sa.Text()), nullable=True))
    op.add_column("declarant_profiles", sa.Column("edrpou_extracted_at", sa.TIMESTAMP(), nullable=True))


def downgrade() -> None:
    op.drop_column("declarant_profiles", "edrpou_extracted_at")
    op.drop_column("declarant_profiles", "bank_edrpous")
    op.drop_column("declarant_profiles", "securities_edrpous")
    op.drop_column("declarant_profiles", "income_source_edrpous")
    op.drop_column("declarant_profiles", "employer_edrpou")

    op.drop_table("prozorro_enrichment")
