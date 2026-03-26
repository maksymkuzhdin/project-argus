"""
Project Argus — Database persistence layer.

Takes the output of ``process_declaration_full()`` and upserts all
parsed / scored rows into PostgreSQL.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    AnomalyScore,
    BankAccount,
    DeclarantProfile,
    FamilyMember,
    IncomeEntry,
    MonetaryAsset,
    RealEstateAsset,
    Vehicle,
)

logger = logging.getLogger(__name__)


def _as_db_string(value: Any) -> str | None:
    """Convert parser outputs to a DB-safe string representation.

    Some declaration fields occasionally arrive as structured placeholder
    objects; storing a JSON string preserves traceability and avoids adapter
    errors in SQLAlchemy/psycopg.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _delete_existing(db: Session, declaration_id: str) -> None:
    """Remove all rows for a declaration so we can re-insert cleanly."""
    for model in (
        AnomalyScore,
        BankAccount,
        DeclarantProfile,
        FamilyMember,
        IncomeEntry,
        MonetaryAsset,
        RealEstateAsset,
        Vehicle,
    ):
        db.query(model).filter(model.declaration_id == declaration_id).delete()


def persist_declaration(db: Session, full: dict[str, Any]) -> None:
    """Write a fully-processed declaration into all normalised tables.

    Parameters
    ----------
    db:
        An active SQLAlchemy session (caller is responsible for commit).
    full:
        The dict returned by ``process_declaration_full()``.

    Field names here must match the parser output (snake_case).
    """
    decl_id = str(full["declaration_id"])

    # Idempotent: wipe previous rows for this declaration
    _delete_existing(db, decl_id)

    # -- DeclarantProfile (step_1 + top-level person metadata) ----------------
    bio = full.get("bio") or {}
    db.add(DeclarantProfile(
        declaration_id=decl_id,
        user_declarant_id=full.get("user_declarant_id"),
        declaration_year=full.get("declaration_year"),
        declaration_type=full.get("declaration_type"),
        firstname=_as_db_string(bio.get("firstname")),
        lastname=_as_db_string(bio.get("lastname")),
        middlename=_as_db_string(bio.get("middlename")),
        work_post=_as_db_string(bio.get("work_post")),
        work_place=_as_db_string(bio.get("work_place")),
        post_type=_as_db_string(bio.get("post_type")),
        post_category=_as_db_string(bio.get("post_category")),
    ))

    # -- FamilyMembers (step_2) --------------------------------------------
    for fm in full.get("family_members") or []:
        db.add(FamilyMember(
            declaration_id=decl_id,
            member_id=_as_db_string(fm.get("member_id", "")) or "",
            relation=_as_db_string(fm.get("relation")),
            firstname=_as_db_string(fm.get("firstname")),
            lastname=_as_db_string(fm.get("lastname")),
            middlename=_as_db_string(fm.get("middlename")),
        ))

    # -- RealEstateAssets (step_3) -----------------------------------------
    for re_row in full.get("real_estate") or []:
        db.add(RealEstateAsset(
            declaration_id=decl_id,
            object_type=_as_db_string(re_row.get("object_type")),
            other_object_type=_as_db_string(re_row.get("other_object_type")),
            total_area=re_row.get("total_area"),
            total_area_raw=_as_db_string(re_row.get("total_area_raw")),
            total_area_status=_as_db_string(re_row.get("total_area_status")),
            cost_assessment=re_row.get("cost_assessment"),
            cost_assessment_raw=_as_db_string(re_row.get("cost_assessment_raw")),
            cost_assessment_status=_as_db_string(re_row.get("cost_assessment_status")),
            owning_date=_as_db_string(re_row.get("owning_date")),
            right_belongs_raw=_as_db_string(re_row.get("right_belongs_raw")),
            right_belongs_resolved=_as_db_string(re_row.get("right_belongs_resolved")),
            ownership_type=_as_db_string(re_row.get("ownership_type")),
            percent_ownership=_as_db_string(re_row.get("percent_ownership")),
            country=_as_db_string(re_row.get("country")),
            region=_as_db_string(re_row.get("region")),
            district=_as_db_string(re_row.get("district")),
            community=_as_db_string(re_row.get("community")),
            city=_as_db_string(re_row.get("city")),
            city_type=_as_db_string(re_row.get("city_type")),
            raw_iteration=_as_db_string(re_row.get("raw_iteration")),
        ))

    # -- Vehicles (step_6) -------------------------------------------------
    for v in full.get("vehicles") or []:
        db.add(Vehicle(
            declaration_id=decl_id,
            object_type=_as_db_string(v.get("object_type")),
            brand=_as_db_string(v.get("brand")),
            model=_as_db_string(v.get("model")),
            graduation_year=v.get("graduation_year"),
            owning_date=_as_db_string(v.get("owning_date")),
            cost_date=v.get("cost_date"),
            ownership_type=_as_db_string(v.get("ownership_type")),
            right_belongs_resolved=_as_db_string(v.get("right_belongs_resolved")),
            raw_iteration=_as_db_string(v.get("raw_iteration")),
        ))

    # -- IncomeEntries (step_11) -------------------------------------------
    for inc in full.get("incomes") or []:
        db.add(IncomeEntry(
            declaration_id=decl_id,
            person_ref=_as_db_string(inc.get("person_ref")),
            income_type=_as_db_string(inc.get("income_type")),
            income_type_other=_as_db_string(inc.get("income_type_other")),
            amount=inc.get("amount"),
            amount_raw=_as_db_string(inc.get("amount_raw")),
            amount_status=_as_db_string(inc.get("amount_status")),
            source_name=_as_db_string(inc.get("source_name")),
            source_code=_as_db_string(inc.get("source_code")),
            source_type=_as_db_string(inc.get("source_type")),
            raw_iteration=_as_db_string(inc.get("raw_iteration")),
        ))

    # -- MonetaryAssets (step_12) ------------------------------------------
    for ma in full.get("monetary") or []:
        db.add(MonetaryAsset(
            declaration_id=decl_id,
            person_ref=ma.get("person_ref"),
            asset_type=ma.get("asset_type"),
            currency_raw=_as_db_string(ma.get("currency_raw")),
            currency_code=_as_db_string(ma.get("currency_code")),
            amount=ma.get("amount"),
            amount_raw=ma.get("amount_raw"),
            organization=_as_db_string(ma.get("organization")),
            organization_status=_as_db_string(ma.get("organization_status")),
            ownership_type=_as_db_string(ma.get("ownership_type")),
            raw_iteration=_as_db_string(ma.get("raw_iteration")),
        ))

    # -- BankAccounts (step_17) --------------------------------------------
    for ba in full.get("bank_accounts") or []:
        db.add(BankAccount(
            declaration_id=decl_id,
            institution_name=_as_db_string(ba.get("institution_name")),
            institution_code=_as_db_string(ba.get("institution_code")),
            account_owner_resolved=_as_db_string(ba.get("account_owner_resolved")),
            raw_iteration=_as_db_string(ba.get("raw_iteration")),
        ))

    # -- AnomalyScore ------------------------------------------------------
    score_data = full.get("score") or {}
    rule_details = score_data.get("rule_details", [])
    triggered = score_data.get("triggered_rules", [])
    db.add(AnomalyScore(
        declaration_id=decl_id,
        total_score=score_data.get("total_score"),
        triggered_rules=_as_db_string(",".join(triggered) if triggered else None),
        explanation_summary=_as_db_string(score_data.get("explanation")),
        rule_details_json=_as_db_string(json.dumps(rule_details) if rule_details else None),
    ))

    db.flush()


def persist_batch(db: Session, raws: list[dict]) -> int:
    """Process and persist a batch of raw declarations.

    Returns the number of declarations successfully persisted.
    """
    from app.services.pipeline import process_declaration_full

    count = 0
    for raw in raws:
        decl_id = raw.get("id", "unknown")
        try:
            full = process_declaration_full(raw)
            persist_declaration(db, full)
            count += 1
        except Exception:
            db.rollback()
            logger.exception("Failed to persist declaration %s", decl_id)
            continue

    db.commit()
    return count
