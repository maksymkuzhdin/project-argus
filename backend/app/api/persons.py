"""
Project Argus — Persons API Router.

Returns multi-year person profiles built from the timeline assembler.
Each person is identified by ``user_declarant_id``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import DeclarantProfile, IncomeEntry, MonetaryAsset, RealEstateAsset, Vehicle
from app.db.session import get_db
from app.features.cash import classify_monetary_assets
from app.normalization.assemble_timeline import YearlySnapshot, YOYChange, PersonTimeline, assemble_timeline
from app.scoring.rules import score_timeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/persons", tags=["persons"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap_to_dict(s: YearlySnapshot) -> dict[str, Any]:
    return {
        "declaration_id": s.declaration_id,
        "declaration_year": s.declaration_year,
        "declaration_type": s.declaration_type,
        "total_income": str(s.total_income) if s.total_income is not None else None,
        "total_monetary": str(s.total_monetary) if s.total_monetary is not None else None,
        "cash": str(s.cash) if s.cash is not None else None,
        "bank": str(s.bank) if s.bank is not None else None,
        "income_count": s.income_count,
        "monetary_count": s.monetary_count,
        "real_estate_count": s.real_estate_count,
        "vehicle_count": s.vehicle_count,
        "role": s.role,
        "institution": s.institution,
    }


def _change_to_dict(c: YOYChange) -> dict[str, Any]:
    def _fmt(v: Decimal | None) -> str | None:
        return str(v) if v is not None else None

    return {
        "from_year": c.from_year,
        "to_year": c.to_year,
        "income_prev": _fmt(c.income_prev),
        "income_curr": _fmt(c.income_curr),
        "income_delta": _fmt(c.income_delta),
        "income_ratio": c.income_ratio,
        "monetary_prev": _fmt(c.monetary_prev),
        "monetary_curr": _fmt(c.monetary_curr),
        "monetary_delta": _fmt(c.monetary_delta),
        "monetary_ratio": c.monetary_ratio,
        "cash_prev": _fmt(c.cash_prev),
        "cash_curr": _fmt(c.cash_curr),
        "cash_delta": _fmt(c.cash_delta),
    }


def _timeline_response(
    timeline: PersonTimeline,
    timeline_score: Any,
) -> dict[str, Any]:
    return {
        "user_declarant_id": timeline.user_declarant_id,
        "name": timeline.name,
        "snapshot_count": len(timeline.snapshots),
        "snapshots": [_snap_to_dict(s) for s in timeline.snapshots],
        "changes": [_change_to_dict(c) for c in timeline.changes],
        "timeline_score": {
            "total_score": timeline_score.total_score,
            "triggered_rules": timeline_score.triggered_rules,
            "explanation": timeline_score.explanation_summary,
            "rule_details": [
                {
                    "rule_name": r.rule_name,
                    "score": r.score,
                    "triggered": r.triggered,
                    "explanation": r.explanation,
                }
                for r in timeline_score.rule_results
            ],
        },
    }


def _income_row_to_dict(row: IncomeEntry) -> dict[str, Any]:
    return {
        "person_ref": row.person_ref,
        "income_type": row.income_type,
        "income_type_other": row.income_type_other,
        "amount": float(row.amount) if row.amount is not None else None,
        "amount_status": row.amount_status,
        "source_name": row.source_name,
        "source_code": row.source_code,
        "source_type": row.source_type,
    }


def _monetary_row_to_dict(row: MonetaryAsset) -> dict[str, Any]:
    return {
        "person_ref": row.person_ref,
        "asset_type": row.asset_type,
        "currency_raw": row.currency_raw,
        "currency_code": row.currency_code,
        "amount": float(row.amount) if row.amount is not None else None,
        "amount_status": None,
        "organization": row.organization,
        "organization_status": row.organization_status,
        "ownership_type": row.ownership_type,
    }


def _real_estate_row_to_dict(row: RealEstateAsset) -> dict[str, Any]:
    return {
        "object_type": row.object_type,
        "other_object_type": row.other_object_type,
        "total_area": float(row.total_area) if row.total_area is not None else None,
        "total_area_status": row.total_area_status,
        "cost_assessment": float(row.cost_assessment) if row.cost_assessment is not None else None,
        "cost_assessment_status": row.cost_assessment_status,
        "owning_date": row.owning_date,
        "right_belongs_raw": row.right_belongs_raw,
        "right_belongs_resolved": row.right_belongs_resolved,
        "ownership_type": row.ownership_type,
        "percent_ownership": row.percent_ownership,
        "city": row.city,
        "district": row.district,
        "region": row.region,
    }


def _vehicle_row_to_dict(row: Vehicle) -> dict[str, Any]:
    return {
        "object_type": row.object_type,
        "brand": row.brand,
        "model": row.model,
        "graduation_year": row.graduation_year,
        "owning_date": row.owning_date,
        "cost_date": float(row.cost_date) if row.cost_date is not None else None,
        "ownership_type": row.ownership_type,
        "right_belongs_resolved": row.right_belongs_resolved,
    }


# ---------------------------------------------------------------------------
# DB path helper — build a timeline from database rows
# ---------------------------------------------------------------------------

def _build_timeline_from_db(
    user_declarant_id: int,
    db: Session,
) -> PersonTimeline | None:
    profiles = (
        db.query(DeclarantProfile)
        .filter(DeclarantProfile.user_declarant_id == user_declarant_id)
        .order_by(DeclarantProfile.declaration_year)
        .all()
    )
    if not profiles:
        return None

    # Reconstruct full dicts from DB rows to feed assemble_timeline
    fulls = []
    for p in profiles:
        decl_id = p.declaration_id

        incomes_rows = db.query(IncomeEntry).filter(
            IncomeEntry.declaration_id == decl_id
        ).all()
        monetary_rows = db.query(MonetaryAsset).filter(
            MonetaryAsset.declaration_id == decl_id
        ).all()
        real_estate_rows = db.query(RealEstateAsset).filter(
            RealEstateAsset.declaration_id == decl_id
        ).all()
        vehicle_rows = db.query(Vehicle).filter(
            Vehicle.declaration_id == decl_id
        ).all()

        incomes = [_income_row_to_dict(r) for r in incomes_rows]
        monetary = [_monetary_row_to_dict(r) for r in monetary_rows]
        real_estate = [_real_estate_row_to_dict(r) for r in real_estate_rows]
        vehicles = [_vehicle_row_to_dict(r) for r in vehicle_rows]

        total_income = db.query(func.sum(IncomeEntry.amount)).filter(
            IncomeEntry.declaration_id == decl_id
        ).scalar()
        total_monetary = db.query(func.sum(MonetaryAsset.amount)).filter(
            MonetaryAsset.declaration_id == decl_id
        ).scalar()
        total_real_estate = db.query(func.sum(RealEstateAsset.cost_assessment)).filter(
            RealEstateAsset.declaration_id == decl_id
        ).scalar()

        total_assets = Decimal(0)
        has_assets = False
        if total_monetary is not None:
            total_assets += Decimal(total_monetary)
            has_assets = True
        if total_real_estate is not None:
            total_assets += Decimal(total_real_estate)
            has_assets = True

        cash_bank = classify_monetary_assets(monetary)

        # Re-build features dict so assemble_timeline can use it
        full = {
            "declaration_id": decl_id,
            "user_declarant_id": p.user_declarant_id,
            "declaration_year": p.declaration_year,
            "declaration_type": p.declaration_type,
            "bio": {
                "firstname": p.firstname,
                "lastname": p.lastname,
                "middlename": p.middlename,
                "work_post": p.work_post,
                "work_place": p.work_place,
            },
            "incomes": incomes,
            "monetary": monetary,
            "real_estate": real_estate,
            "vehicles": vehicles,
            "bank_accounts": [],
            "family_members": [],
            "features": {
                "total_income": str(total_income) if total_income else None,
                "total_assets": str(total_assets) if has_assets else None,
                "cash": str(cash_bank.cash) if cash_bank.cash else None,
                "bank": str(cash_bank.bank) if cash_bank.bank else None,
            },
        }
        fulls.append(full)

    return assemble_timeline(fulls)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{user_declarant_id}")
def get_person_timeline(
    user_declarant_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the multi-year timeline for a specific person."""
    from app.api.declarations import _db_has_data, _ensure_loaded, _CACHE_BY_UID, _CACHE
    from app.normalization.assemble_timeline import assemble_timeline

    if not _db_has_data(db):
        # In-memory path
        _ensure_loaded()
        decl_ids = _CACHE_BY_UID.get(user_declarant_id)
        if not decl_ids or len(decl_ids) < 2:
            raise HTTPException(
                status_code=404,
                detail="No multi-year data found for this person.",
            )

        # Reconstruct full-pipeline dicts from the cache
        fulls = []
        for decl_id in decl_ids:
            detail = _CACHE.get(decl_id)
            if not detail:
                continue
            summary = detail.get("summary", {})
            fulls.append({
                "declaration_id": decl_id,
                "user_declarant_id": detail.get("user_declarant_id"),
                "declaration_year": detail.get("declaration_year"),
                "declaration_type": detail.get("declaration_type"),
                "bio": detail.get("bio", {}),
                "incomes": detail.get("incomes", []),
                "monetary": detail.get("monetary", []),
                "real_estate": detail.get("real_estate", []),
                "vehicles": detail.get("vehicles", []),
                "bank_accounts": detail.get("bank_accounts", []),
                "family_members": detail.get("family_members", []),
                "features": detail.get("features", {}),
            })

        timeline = assemble_timeline(fulls)
        if not timeline:
            raise HTTPException(status_code=404, detail="Could not build timeline.")

        ts = score_timeline(timeline)
        return _timeline_response(timeline, ts)

    # DB path
    timeline = _build_timeline_from_db(user_declarant_id, db)
    if not timeline:
        raise HTTPException(
            status_code=404,
            detail="No declarations found for this user_declarant_id.",
        )
    if len(timeline.snapshots) < 2:
        raise HTTPException(
            status_code=404,
            detail="Only one year of data found — multi-year timeline requires 2+.",
        )

    ts = score_timeline(timeline)
    return _timeline_response(timeline, ts)
