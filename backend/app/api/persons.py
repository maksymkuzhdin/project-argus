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

        total_income = db.query(func.sum(IncomeEntry.amount)).filter(
            IncomeEntry.declaration_id == decl_id
        ).scalar()
        total_monetary = db.query(func.sum(MonetaryAsset.amount)).filter(
            MonetaryAsset.declaration_id == decl_id
        ).scalar()

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
            "incomes": [None] * (db.query(func.count(IncomeEntry.id)).filter(
                IncomeEntry.declaration_id == decl_id
            ).scalar() or 0),
            "monetary": [None] * (db.query(func.count(MonetaryAsset.id)).filter(
                MonetaryAsset.declaration_id == decl_id
            ).scalar() or 0),
            "real_estate": [None] * (db.query(func.count(RealEstateAsset.id)).filter(
                RealEstateAsset.declaration_id == decl_id
            ).scalar() or 0),
            "vehicles": [None] * (db.query(func.count(Vehicle.id)).filter(
                Vehicle.declaration_id == decl_id
            ).scalar() or 0),
            "bank_accounts": [],
            "family_members": [],
            "features": {
                "total_income": str(total_income) if total_income else None,
                "total_assets": str(total_monetary) if total_monetary else None,
                "cash": None,
                "bank": None,
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
