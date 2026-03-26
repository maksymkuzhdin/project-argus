"""Add person metadata to declarant_profiles.

Adds user_declarant_id, declaration_year, and declaration_type — the three
top-level fields needed to group declarations by person across years.

Revision ID: 002_person_metadata
Revises: 001_initial
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_person_metadata"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "declarant_profiles",
        sa.Column("user_declarant_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "declarant_profiles",
        sa.Column("declaration_year", sa.Integer(), nullable=True),
    )
    op.add_column(
        "declarant_profiles",
        sa.Column("declaration_type", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_declarant_profiles_user_declarant_id",
        "declarant_profiles",
        ["user_declarant_id"],
    )
    op.create_index(
        "ix_declarant_profiles_declaration_year",
        "declarant_profiles",
        ["declaration_year"],
    )


def downgrade() -> None:
    op.drop_index("ix_declarant_profiles_declaration_year", table_name="declarant_profiles")
    op.drop_index("ix_declarant_profiles_user_declarant_id", table_name="declarant_profiles")
    op.drop_column("declarant_profiles", "declaration_type")
    op.drop_column("declarant_profiles", "declaration_year")
    op.drop_column("declarant_profiles", "user_declarant_id")
