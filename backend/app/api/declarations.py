"""
Project Argus — Declarations API Router.

Queries PostgreSQL for analysed declarations.  Falls back to an in-memory
cache built from raw JSON files when the database is empty (zero-config dev).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
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
from app.db.session import get_db
from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.services.pipeline import process_declaration_full

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/declarations", tags=["declarations"])


# ---------------------------------------------------------------------------
# Helpers — ORM row → dict serialisation
#
# Field names MUST match the parser output (snake_case) so the frontend
# renders identically regardless of whether data comes from the DB or the
# in-memory fallback cache.
# ---------------------------------------------------------------------------

def _profile_to_dict(p: DeclarantProfile) -> dict[str, Any]:
    return {
        "firstname": p.firstname,
        "lastname": p.lastname,
        "middlename": p.middlename,
        "work_post": p.work_post,
        "work_place": p.work_place,
        "post_type": p.post_type,
        "post_category": p.post_category,
    }


def _family_to_dict(f: FamilyMember) -> dict[str, Any]:
    return {
        "member_id": f.member_id,
        "relation": f.relation,
        "firstname": f.firstname,
        "lastname": f.lastname,
        "middlename": f.middlename,
    }


def _real_estate_to_dict(r: RealEstateAsset) -> dict[str, Any]:
    return {
        "object_type": r.object_type,
        "other_object_type": r.other_object_type,
        "total_area": float(r.total_area) if r.total_area is not None else None,
        "total_area_raw": r.total_area_raw,
        "total_area_status": r.total_area_status,
        "cost_assessment": float(r.cost_assessment) if r.cost_assessment is not None else None,
        "cost_assessment_raw": r.cost_assessment_raw,
        "cost_assessment_status": r.cost_assessment_status,
        "owning_date": r.owning_date,
        "right_belongs_raw": r.right_belongs_raw,
        "right_belongs_resolved": r.right_belongs_resolved,
        "ownership_type": r.ownership_type,
        "percent_ownership": r.percent_ownership,
        "country": r.country,
        "region": r.region,
        "district": r.district,
        "community": r.community,
        "city": r.city,
        "city_type": r.city_type,
    }


def _vehicle_to_dict(v: Vehicle) -> dict[str, Any]:
    return {
        "object_type": v.object_type,
        "brand": v.brand,
        "model": v.model,
        "graduation_year": v.graduation_year,
        "owning_date": v.owning_date,
        "cost_date": float(v.cost_date) if v.cost_date is not None else None,
        "ownership_type": v.ownership_type,
        "right_belongs_resolved": v.right_belongs_resolved,
    }


def _income_to_dict(i: IncomeEntry) -> dict[str, Any]:
    return {
        "person_ref": i.person_ref,
        "income_type": i.income_type,
        "income_type_other": i.income_type_other,
        "amount": float(i.amount) if i.amount is not None else None,
        "amount_raw": i.amount_raw,
        "amount_status": i.amount_status,
        "source_name": i.source_name,
        "source_code": i.source_code,
        "source_type": i.source_type,
    }


def _monetary_to_dict(m: MonetaryAsset) -> dict[str, Any]:
    return {
        "person_ref": m.person_ref,
        "asset_type": m.asset_type,
        "currency_raw": m.currency_raw,
        "currency_code": m.currency_code,
        "amount": float(m.amount) if m.amount is not None else None,
        "amount_raw": m.amount_raw,
        "organization": m.organization,
        "organization_status": m.organization_status,
        "ownership_type": m.ownership_type,
    }


def _bank_to_dict(b: BankAccount) -> dict[str, Any]:
    return {
        "institution_name": b.institution_name,
        "institution_code": b.institution_code,
        "account_owner_resolved": b.account_owner_resolved,
    }


# ---------------------------------------------------------------------------
# In-memory fallback cache (for dev without Postgres)
# ---------------------------------------------------------------------------

_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_SUMMARY: list[dict[str, Any]] = []
_CACHE_BY_UID: dict[int, list[str]] = {}  # user_declarant_id → [declaration_ids]
_LOADED = False
_LOCK = threading.Lock()


def _ensure_loaded() -> None:
    """Populate the in-memory cache from raw JSON files.

    Uses ``process_declaration_full`` once per declaration, then optionally
    re-scores with cohort context (CR16) in a second pass.
    """
    global _LOADED
    if _LOADED:
        return

    with _LOCK:
        if _LOADED:
            return

        raw_dir = Path(settings.raw_data_dir)
        project_root = Path(__file__).resolve().parents[3]
        example_dir = project_root.parent / "example declarations"
        files = iter_raw_declarations(raw_dir)
        if not files and example_dir.exists():
            files = iter_raw_declarations(example_dir)

        # ── Pass 1: Process all declarations (no cohort context) ──────
        raw_entries: list[tuple[dict, dict]] = []  # (raw, full)
        for f in files:
            raw = load_declaration(f)
            full = process_declaration_full(raw)
            raw_entries.append((raw, full))

        # ── Build cohort distributions from pass 1 ────────────────────
        from app.scoring.cohorts import build_cohort_distributions, CohortKey
        cohort_summaries = []
        for _, full in raw_entries:
            features = full.get("features", {})
            inc = features.get("total_income")
            ast = features.get("total_assets")
            cohort_summaries.append({
                "post_type": features.get("post_type", ""),
                "declaration_year": full.get("declaration_year"),
                "total_income": float(inc) if inc else None,
                "total_assets": float(ast) if ast else None,
                "cash_ratio": features.get("cash_ratio"),
            })
        distributions = build_cohort_distributions(cohort_summaries)

        # ── Pass 2: Re-score with cohort context if distributions exist ─
        for raw, full in raw_entries:
            features = full.get("features", {})
            pt = features.get("post_type", "")
            yr = full.get("declaration_year")
            cohort = None
            if pt and yr and distributions:
                cohort = distributions.get(CohortKey(post_type=str(pt), year=int(yr)))

            # Re-score with cohort context if available
            if cohort is not None:
                full = process_declaration_full(raw, cohort_stats=cohort)

            doc_id = raw.get("id", raw.get("doc_id", "unknown"))
            bio = full["bio"]
            score_data = full["score"]

            detail: dict[str, Any] = {
                "id": doc_id,
                "user_declarant_id": full.get("user_declarant_id"),
                "declaration_year": full.get("declaration_year"),
                "declaration_type": full.get("declaration_type"),
                "raw_metadata": {
                    "year": raw.get("declaration_year"),
                    "date": raw.get("date"),
                    "declaration_type": raw.get("declaration_type"),
                },
                "bio": bio,
                "family_members": full["family_members"],
                "real_estate": full["real_estate"],
                "vehicles": full["vehicles"],
                "bank_accounts": full["bank_accounts"],
                "incomes": full["incomes"],
                "monetary": full["monetary"],
                "features": full["features"],
            }

            name = " ".join(
                p for p in [
                    bio.get("lastname", ""),
                    bio.get("firstname", ""),
                    bio.get("middlename", ""),
                ] if p
            ) or "Unknown Official"

            summary = {
                "declaration_id": doc_id,
                "user_declarant_id": full.get("user_declarant_id"),
                "declaration_year": full.get("declaration_year"),
                "declaration_type": full.get("declaration_type"),
                "family_members": len(full["family_members"]),
                "incomes": len(full["incomes"]),
                "monetary_assets": len(full["monetary"]),
                "real_estate_rights": len(full["real_estate"]),
                "total_income": full["features"].get("total_income"),
                "total_assets": full["features"].get("total_assets"),
                "score": score_data["total_score"],
                "triggered_rules": score_data["triggered_rules"],
                "explanation": score_data["explanation"],
                "rule_details": score_data.get("rule_details", []),
                "name": name,
                "role": bio.get("work_post", ""),
                "institution": bio.get("work_place", ""),
                "post_type": features.get("post_type", ""),
            }

            detail["summary"] = summary
            _CACHE[str(doc_id)] = detail
            _CACHE_SUMMARY.append(summary)

            uid = full.get("user_declarant_id")
            if uid is not None:
                _CACHE_BY_UID.setdefault(int(uid), []).append(str(doc_id))

        _CACHE_SUMMARY.sort(key=lambda x: x["score"], reverse=True)
        _LOADED = True


def _db_has_data(db: Session) -> bool:
    """Quick check: does the DB contain any analysed declarations?"""
    try:
        return db.query(DeclarantProfile.id).limit(1).first() is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class StatsResponse(BaseModel):
    total_declarations: int
    flagged_declarations: int
    average_score: float
    rule_distribution: dict[str, int]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_declarations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=500000),
    min_score: float = Query(default=0.0, ge=0.0, le=100.0),
    query: str | None = Query(default=None, max_length=120),
    sort_by: str = Query(default="score"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Paginated list of declaration summaries."""

    allowed_sort_fields = {"score", "income", "assets", "name", "year"}
    sort_by = sort_by.lower().strip()
    if sort_by not in allowed_sort_fields:
        sort_by = "score"

    sort_dir = sort_dir.lower().strip()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "desc"

    if not _db_has_data(db):
        _ensure_loaded()
        results = list(_CACHE_SUMMARY)
        if min_score:
            results = [r for r in results if r["score"] >= min_score]
        if query:
            q = query.lower()
            results = [
                r for r in results
                if q in r.get("name", "").lower()
                or q in r.get("institution", "").lower()
            ]

        def _cache_sort_key(item: dict[str, Any]) -> Any:
            if sort_by == "income":
                return float(item.get("total_income") or 0)
            if sort_by == "assets":
                return float(item.get("total_assets") or 0)
            if sort_by == "name":
                return (item.get("name") or "").lower()
            if sort_by == "year":
                return int(item.get("declaration_year") or 0)
            return float(item.get("score") or 0)

        results.sort(key=_cache_sort_key, reverse=(sort_dir == "desc"))

        total = len(results)
        return {
            "items": results[offset : offset + limit],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    # --- Database path (N+1 eliminated via subqueries) ---
    income_sub = (
        db.query(
            IncomeEntry.declaration_id,
            func.sum(IncomeEntry.amount).label("total_income"),
        )
        .group_by(IncomeEntry.declaration_id)
        .subquery("income_agg")
    )
    monetary_sub = (
        db.query(
            MonetaryAsset.declaration_id,
            func.sum(MonetaryAsset.amount).label("total_assets"),
        )
        .group_by(MonetaryAsset.declaration_id)
        .subquery("monetary_agg")
    )

    q_base = (
        db.query(
            DeclarantProfile.declaration_id,
            DeclarantProfile.user_declarant_id,
            DeclarantProfile.declaration_year,
            DeclarantProfile.firstname,
            DeclarantProfile.middlename,
            DeclarantProfile.lastname,
            DeclarantProfile.work_post,
            DeclarantProfile.work_place,
            AnomalyScore.total_score,
            AnomalyScore.triggered_rules,
            AnomalyScore.explanation_summary,
            income_sub.c.total_income,
            monetary_sub.c.total_assets,
        )
        .outerjoin(
            AnomalyScore,
            AnomalyScore.declaration_id == DeclarantProfile.declaration_id,
        )
        .outerjoin(
            income_sub,
            income_sub.c.declaration_id == DeclarantProfile.declaration_id,
        )
        .outerjoin(
            monetary_sub,
            monetary_sub.c.declaration_id == DeclarantProfile.declaration_id,
        )
    )

    if min_score:
        q_base = q_base.filter(AnomalyScore.total_score >= min_score)

    if query:
        like = f"%{query}%"
        q_base = q_base.filter(
            DeclarantProfile.firstname.ilike(like)
            | DeclarantProfile.middlename.ilike(like)
            | DeclarantProfile.lastname.ilike(like)
            | DeclarantProfile.work_place.ilike(like)
        )

    if sort_by == "income":
        order_col = income_sub.c.total_income
        order_clause = order_col.asc().nullslast() if sort_dir == "asc" else order_col.desc().nullslast()
    elif sort_by == "assets":
        order_col = monetary_sub.c.total_assets
        order_clause = order_col.asc().nullslast() if sort_dir == "asc" else order_col.desc().nullslast()
    elif sort_by == "name":
        if sort_dir == "asc":
            order_clause = (
                DeclarantProfile.lastname.asc().nullslast(),
                DeclarantProfile.firstname.asc().nullslast(),
                DeclarantProfile.middlename.asc().nullslast(),
            )
        else:
            order_clause = (
                DeclarantProfile.lastname.desc().nullslast(),
                DeclarantProfile.firstname.desc().nullslast(),
                DeclarantProfile.middlename.desc().nullslast(),
            )
    elif sort_by == "year":
        order_col = DeclarantProfile.declaration_year
        order_clause = order_col.asc().nullslast() if sort_dir == "asc" else order_col.desc().nullslast()
    else:
        order_col = AnomalyScore.total_score
        order_clause = order_col.asc().nullslast() if sort_dir == "asc" else order_col.desc().nullslast()

    total = q_base.count()
    q_ordered = q_base.order_by(*order_clause) if isinstance(order_clause, tuple) else q_base.order_by(order_clause)
    rows = q_ordered.offset(offset).limit(limit).all()

    items = []
    for row in rows:
        name = " ".join(
            p for p in [row.lastname, row.firstname, row.middlename] if p
        ) or "Unknown Official"
        triggered = row.triggered_rules.split(",") if row.triggered_rules else []

        items.append({
            "declaration_id": row.declaration_id,
            "user_declarant_id": row.user_declarant_id,
            "declaration_year": row.declaration_year,
            "name": name,
            "role": row.work_post or "",
            "institution": row.work_place or "",
            "total_income": str(row.total_income) if row.total_income else None,
            "total_assets": str(row.total_assets) if row.total_assets else None,
            "score": float(row.total_score) if row.total_score is not None else 0.0,
            "triggered_rules": triggered,
            "explanation": row.explanation_summary or "No anomaly signals detected.",
        })

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    """Aggregate statistics for the dashboard."""

    if not _db_has_data(db):
        _ensure_loaded()
        total = len(_CACHE_SUMMARY)
        if total == 0:
            return StatsResponse(
                total_declarations=0,
                flagged_declarations=0,
                average_score=0.0,
                rule_distribution={},
            )
        flagged = sum(1 for r in _CACHE_SUMMARY if r["score"] > 0)
        avg_score = sum(r["score"] for r in _CACHE_SUMMARY) / total
        rules: dict[str, int] = {}
        for r in _CACHE_SUMMARY:
            for rule in r.get("triggered_rules", []):
                rules[rule] = rules.get(rule, 0) + 1
        return StatsResponse(
            total_declarations=total,
            flagged_declarations=flagged,
            average_score=round(avg_score, 3),
            rule_distribution=rules,
        )

    # --- Database path ---
    total = db.query(func.count(DeclarantProfile.id)).scalar() or 0
    if total == 0:
        return StatsResponse(
            total_declarations=0,
            flagged_declarations=0,
            average_score=0.0,
            rule_distribution={},
        )

    flagged = (
        db.query(func.count(AnomalyScore.id))
        .filter(AnomalyScore.total_score > 0)
        .scalar()
        or 0
    )
    avg_score = (
        db.query(func.avg(AnomalyScore.total_score)).scalar() or 0.0
    )

    rule_rows = (
        db.query(AnomalyScore.triggered_rules)
        .filter(AnomalyScore.triggered_rules.isnot(None))
        .filter(AnomalyScore.triggered_rules != "")
        .all()
    )
    rules: dict[str, int] = {}
    for (tr,) in rule_rows:
        for rule_name in tr.split(","):
            name = rule_name.strip()
            if name:
                rules[name] = rules.get(name, 0) + 1

    return StatsResponse(
        total_declarations=total,
        flagged_declarations=flagged,
        average_score=round(float(avg_score), 3),
        rule_distribution=rules,
    )


@router.get("/{doc_id}")
def get_declaration(doc_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Full details for a single declaration."""

    if not _db_has_data(db):
        _ensure_loaded()
        doc = _CACHE.get(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Declaration not found")
        return doc

    # --- Database path ---
    profile = (
        db.query(DeclarantProfile)
        .filter(DeclarantProfile.declaration_id == doc_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Declaration not found")

    family = db.query(FamilyMember).filter(FamilyMember.declaration_id == doc_id).all()
    real_estate = db.query(RealEstateAsset).filter(RealEstateAsset.declaration_id == doc_id).all()
    vehicles = db.query(Vehicle).filter(Vehicle.declaration_id == doc_id).all()
    incomes = db.query(IncomeEntry).filter(IncomeEntry.declaration_id == doc_id).all()
    monetary = db.query(MonetaryAsset).filter(MonetaryAsset.declaration_id == doc_id).all()
    banks = db.query(BankAccount).filter(BankAccount.declaration_id == doc_id).all()
    score_row = (
        db.query(AnomalyScore)
        .filter(AnomalyScore.declaration_id == doc_id)
        .first()
    )

    bio = _profile_to_dict(profile)
    triggered = score_row.triggered_rules.split(",") if score_row and score_row.triggered_rules else []
    rule_details = json.loads(score_row.rule_details_json) if score_row and score_row.rule_details_json else []

    total_income_val = db.query(func.sum(IncomeEntry.amount)).filter(
        IncomeEntry.declaration_id == doc_id
    ).scalar()
    total_assets_val = db.query(func.sum(MonetaryAsset.amount)).filter(
        MonetaryAsset.declaration_id == doc_id
    ).scalar()

    summary = {
        "declaration_id": doc_id,
        "family_members": len(family),
        "incomes": len(incomes),
        "monetary_assets": len(monetary),
        "real_estate_rights": len(real_estate),
        "total_income": str(total_income_val) if total_income_val else None,
        "total_assets": str(total_assets_val) if total_assets_val else None,
        "score": float(score_row.total_score) if score_row and score_row.total_score else 0.0,
        "triggered_rules": triggered,
        "explanation": score_row.explanation_summary if score_row else "No anomaly signals detected.",
        "name": " ".join(
            p for p in [
                bio.get("lastname", ""),
                bio.get("firstname", ""),
                bio.get("middlename", ""),
            ] if p
        ) or "Unknown Official",
        "role": bio.get("work_post", ""),
        "institution": bio.get("work_place", ""),
        "rule_details": rule_details,
    }

    return {
        "id": doc_id,
        "user_declarant_id": profile.user_declarant_id,
        "raw_metadata": {
            "year": profile.declaration_year,
            "date": None,
            "declaration_type": profile.declaration_type,
        },
        "bio": bio,
        "family_members": [_family_to_dict(f) for f in family],
        "real_estate": [_real_estate_to_dict(r) for r in real_estate],
        "vehicles": [_vehicle_to_dict(v) for v in vehicles],
        "bank_accounts": [_bank_to_dict(b) for b in banks],
        "incomes": [_income_to_dict(i) for i in incomes],
        "monetary": [_monetary_to_dict(m) for m in monetary],
        "summary": summary,
    }
