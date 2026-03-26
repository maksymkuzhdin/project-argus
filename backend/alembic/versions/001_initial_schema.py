"""Initial schema - all declaration tables.

Revision ID: 001_initial
Revises:
Create Date: 2026-03-09

Creates tables:
- declarant_profiles (step_1)
- family_members (step_2)
- real_estate_assets (step_3)
- vehicles (step_6)
- income_entries (step_11)
- monetary_assets (step_12)
- bank_accounts (step_17)
- anomaly_scores
"""

from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- declarant_profiles (step_1)
    op.create_table(
        "declarant_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("firstname", sa.String(), nullable=True),
        sa.Column("lastname", sa.String(), nullable=True),
        sa.Column("middlename", sa.String(), nullable=True),
        sa.Column("work_post", sa.String(), nullable=True),
        sa.Column("work_place", sa.String(), nullable=True),
        sa.Column("post_type", sa.String(), nullable=True),
        sa.Column("post_category", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("declaration_id"),
    )
    op.create_index("ix_declarant_profiles_declaration_id", "declarant_profiles", ["declaration_id"])

    # -- family_members (step_2)
    op.create_table(
        "family_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=True),
        sa.Column("firstname", sa.String(), nullable=True),
        sa.Column("lastname", sa.String(), nullable=True),
        sa.Column("middlename", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_family_members_declaration_id", "family_members", ["declaration_id"])

    # -- real_estate_assets (step_3)
    op.create_table(
        "real_estate_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=True),
        sa.Column("other_object_type", sa.String(), nullable=True),
        sa.Column("total_area", sa.Numeric(), nullable=True),
        sa.Column("total_area_raw", sa.String(), nullable=True),
        sa.Column("total_area_status", sa.String(), nullable=True),
        sa.Column("cost_assessment", sa.Numeric(), nullable=True),
        sa.Column("cost_assessment_raw", sa.String(), nullable=True),
        sa.Column("cost_assessment_status", sa.String(), nullable=True),
        sa.Column("owning_date", sa.String(), nullable=True),
        sa.Column("right_belongs_raw", sa.String(), nullable=True),
        sa.Column("right_belongs_resolved", sa.String(), nullable=True),
        sa.Column("ownership_type", sa.String(), nullable=True),
        sa.Column("percent_ownership", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("district", sa.String(), nullable=True),
        sa.Column("community", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("city_type", sa.String(), nullable=True),
        sa.Column("raw_iteration", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_real_estate_assets_declaration_id", "real_estate_assets", ["declaration_id"])

    # -- vehicles (step_6)
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=True),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("graduation_year", sa.Integer(), nullable=True),
        sa.Column("owning_date", sa.String(), nullable=True),
        sa.Column("cost_date", sa.Numeric(), nullable=True),
        sa.Column("ownership_type", sa.String(), nullable=True),
        sa.Column("right_belongs_resolved", sa.String(), nullable=True),
        sa.Column("raw_iteration", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vehicles_declaration_id", "vehicles", ["declaration_id"])

    # -- income_entries (step_11)
    op.create_table(
        "income_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("person_ref", sa.String(), nullable=True),
        sa.Column("income_type", sa.String(), nullable=True),
        sa.Column("income_type_other", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("amount_raw", sa.String(), nullable=True),
        sa.Column("amount_status", sa.String(), nullable=True),
        sa.Column("source_name", sa.String(), nullable=True),
        sa.Column("source_code", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("raw_iteration", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_income_entries_declaration_id", "income_entries", ["declaration_id"])

    # -- monetary_assets (step_12)
    op.create_table(
        "monetary_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("person_ref", sa.String(), nullable=True),
        sa.Column("asset_type", sa.String(), nullable=True),
        sa.Column("currency_raw", sa.String(), nullable=True),
        sa.Column("currency_code", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("amount_raw", sa.String(), nullable=True),
        sa.Column("organization", sa.String(), nullable=True),
        sa.Column("organization_status", sa.String(), nullable=True),
        sa.Column("ownership_type", sa.String(), nullable=True),
        sa.Column("raw_iteration", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monetary_assets_declaration_id", "monetary_assets", ["declaration_id"])

    # -- bank_accounts (step_17)
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("institution_name", sa.String(), nullable=True),
        sa.Column("institution_code", sa.String(), nullable=True),
        sa.Column("account_owner_resolved", sa.String(), nullable=True),
        sa.Column("raw_iteration", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_accounts_declaration_id", "bank_accounts", ["declaration_id"])

    # -- anomaly_scores
    op.create_table(
        "anomaly_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("declaration_id", sa.String(), nullable=False),
        sa.Column("total_score", sa.Numeric(), nullable=True),
        sa.Column("triggered_rules", sa.String(), nullable=True),
        sa.Column("explanation_summary", sa.String(), nullable=True),
        sa.Column("rule_details_json", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anomaly_scores_declaration_id", "anomaly_scores", ["declaration_id"])


def downgrade() -> None:
    op.drop_table("anomaly_scores")
    op.drop_table("bank_accounts")
    op.drop_table("monetary_assets")
    op.drop_table("income_entries")
    op.drop_table("vehicles")
    op.drop_table("real_estate_assets")
    op.drop_table("family_members")
    op.drop_table("declarant_profiles")
