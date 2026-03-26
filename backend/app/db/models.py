"""
Project Argus — SQLAlchemy ORM models.
"""

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# step_11 — Income entries
# ---------------------------------------------------------------------------

class IncomeEntry(Base):
    __tablename__ = "income_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    person_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    income_type: Mapped[str | None] = mapped_column(String, nullable=True)
    income_type_other: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    amount_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_status: Mapped[str | None] = mapped_column(String, nullable=True)
    source_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_code: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_iteration: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# step_12 — Monetary assets
# ---------------------------------------------------------------------------

class MonetaryAsset(Base):
    __tablename__ = "monetary_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    person_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_type: Mapped[str | None] = mapped_column(String, nullable=True)
    currency_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    amount_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    organization: Mapped[str | None] = mapped_column(String, nullable=True)
    organization_status: Mapped[str | None] = mapped_column(String, nullable=True)
    ownership_type: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_iteration: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# step_2 — Family members
# ---------------------------------------------------------------------------

class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    member_id: Mapped[str] = mapped_column(String, nullable=False)
    relation: Mapped[str | None] = mapped_column(String, nullable=True)
    firstname: Mapped[str | None] = mapped_column(String, nullable=True)
    lastname: Mapped[str | None] = mapped_column(String, nullable=True)
    middlename: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# step_3 — Real estate assets
# ---------------------------------------------------------------------------

class RealEstateAsset(Base):
    __tablename__ = "real_estate_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type: Mapped[str | None] = mapped_column(String, nullable=True)
    other_object_type: Mapped[str | None] = mapped_column(String, nullable=True)
    total_area: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    total_area_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    total_area_status: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_assessment: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    cost_assessment_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_assessment_status: Mapped[str | None] = mapped_column(String, nullable=True)
    owning_date: Mapped[str | None] = mapped_column(String, nullable=True)
    right_belongs_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    right_belongs_resolved: Mapped[str | None] = mapped_column(String, nullable=True)
    ownership_type: Mapped[str | None] = mapped_column(String, nullable=True)
    percent_ownership: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    district: Mapped[str | None] = mapped_column(String, nullable=True)
    community: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    city_type: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_iteration: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# Anomaly scores
# ---------------------------------------------------------------------------

class AnomalyScore(Base):
    __tablename__ = "anomaly_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    total_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    triggered_rules: Mapped[str | None] = mapped_column(String, nullable=True)
    explanation_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_details_json: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# step_6 — Vehicles
# ---------------------------------------------------------------------------

class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type: Mapped[str | None] = mapped_column(String, nullable=True)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owning_date: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_date: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    ownership_type: Mapped[str | None] = mapped_column(String, nullable=True)
    right_belongs_resolved: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_iteration: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# step_1 — Declarant Profile
# ---------------------------------------------------------------------------

class DeclarantProfile(Base):
    __tablename__ = "declarant_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    # Person-level identifier — stable across years for the same declarant
    user_declarant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    declaration_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    declaration_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    firstname: Mapped[str | None] = mapped_column(String, nullable=True)
    lastname: Mapped[str | None] = mapped_column(String, nullable=True)
    middlename: Mapped[str | None] = mapped_column(String, nullable=True)
    work_post: Mapped[str | None] = mapped_column(String, nullable=True)
    work_place: Mapped[str | None] = mapped_column(String, nullable=True)
    post_type: Mapped[str | None] = mapped_column(String, nullable=True)
    post_category: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# step_17 — Bank Accounts
# ---------------------------------------------------------------------------

class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declaration_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    institution_name: Mapped[str | None] = mapped_column(String, nullable=True)
    institution_code: Mapped[str | None] = mapped_column(String, nullable=True)
    account_owner_resolved: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_iteration: Mapped[str | None] = mapped_column(String, nullable=True)



