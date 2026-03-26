"""
Project Argus — Multi-year timeline assembler.

Groups processed declarations for the same person (by ``user_declarant_id``),
sorts them chronologically, and computes year-over-year deltas used by the
Layer 1 temporal scoring rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class YearlySnapshot:
    """Financial snapshot extracted from a single declaration."""

    declaration_id: str
    declaration_year: int
    declaration_type: int  # 1=annual, 2=initial, 3=cessation

    total_income: Decimal | None
    total_monetary: Decimal | None  # step_12 monetary assets
    total_real_estate: Decimal | None  # step_3 cost assessments
    cash: Decimal | None
    bank: Decimal | None

    income_count: int
    monetary_count: int
    real_estate_count: int
    vehicle_count: int

    role: str
    institution: str


@dataclass
class YOYChange:
    """Year-over-year comparison between two consecutive snapshots."""

    from_year: int
    to_year: int

    income_prev: Decimal | None
    income_curr: Decimal | None
    income_delta: Decimal | None
    income_ratio: float | None  # curr / prev

    monetary_prev: Decimal | None
    monetary_curr: Decimal | None
    monetary_delta: Decimal | None
    monetary_ratio: float | None

    cash_prev: Decimal | None
    cash_curr: Decimal | None
    cash_delta: Decimal | None


@dataclass
class PersonTimeline:
    """All declarations for a single person, sorted chronologically."""

    user_declarant_id: int
    name: str

    snapshots: list[YearlySnapshot]   # sorted by declaration_year
    changes: list[YOYChange]          # consecutive-year comparisons

    # Pre-computed worst-case signals (used by YOY scoring rules)
    max_income_ratio: float | None    # highest single-step income change ratio
    max_monetary_ratio: float | None  # highest single-step monetary change ratio
    max_cash_delta: Decimal | None    # largest absolute cash increase in one year


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def _to_decimal(val: Any) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _snapshot_from_full(full: dict[str, Any]) -> YearlySnapshot:
    """Build a YearlySnapshot from a ``process_declaration_full()`` result."""
    features = full.get("features", {})
    bio = full.get("bio", {})

    return YearlySnapshot(
        declaration_id=str(full["declaration_id"]),
        declaration_year=full.get("declaration_year") or 0,
        declaration_type=full.get("declaration_type") or 1,
        total_income=_to_decimal(features.get("total_income")),
        total_monetary=_to_decimal(features.get("total_assets")),  # monetary only
        total_real_estate=None,  # not tracked separately in features yet
        cash=_to_decimal(features.get("cash")),
        bank=_to_decimal(features.get("bank")),
        income_count=len(full.get("incomes", [])),
        monetary_count=len(full.get("monetary", [])),
        real_estate_count=len(full.get("real_estate", [])),
        vehicle_count=len(full.get("vehicles", [])),
        role=bio.get("work_post", "") or "",
        institution=bio.get("work_place", "") or "",
    )


def _compute_change(a: YearlySnapshot, b: YearlySnapshot) -> YOYChange:
    """Compute the year-over-year change from snapshot a to snapshot b."""

    def _delta(prev: Decimal | None, curr: Decimal | None) -> Decimal | None:
        if prev is None or curr is None:
            return None
        return curr - prev

    def _ratio(prev: Decimal | None, curr: Decimal | None) -> float | None:
        if prev is None or curr is None:
            return None
        if prev == 0:
            return None  # avoid div-by-zero; handled separately in scoring
        return float(curr / prev)

    return YOYChange(
        from_year=a.declaration_year,
        to_year=b.declaration_year,
        income_prev=a.total_income,
        income_curr=b.total_income,
        income_delta=_delta(a.total_income, b.total_income),
        income_ratio=_ratio(a.total_income, b.total_income),
        monetary_prev=a.total_monetary,
        monetary_curr=b.total_monetary,
        monetary_delta=_delta(a.total_monetary, b.total_monetary),
        monetary_ratio=_ratio(a.total_monetary, b.total_monetary),
        cash_prev=a.cash,
        cash_curr=b.cash,
        cash_delta=_delta(a.cash, b.cash),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_timeline(fulls: list[dict[str, Any]]) -> PersonTimeline | None:
    """Build a PersonTimeline from a list of ``process_declaration_full()`` outputs.

    All items must share the same ``user_declarant_id``.

    Parameters
    ----------
    fulls:
        Processed declarations for a single person, in any order.

    Returns
    -------
    A ``PersonTimeline``, or ``None`` if the list is empty or has no valid
    ``user_declarant_id``.
    """
    if not fulls:
        return None

    uid = fulls[0].get("user_declarant_id")
    if uid is None:
        return None

    # Build name from the most recent declaration
    sorted_raws = sorted(fulls, key=lambda f: f.get("declaration_year") or 0, reverse=True)
    bio = sorted_raws[0].get("bio", {})
    name = (
        f"{bio.get('firstname', '')} {bio.get('lastname', '')}".strip()
        or "Unknown Official"
    )

    # Build snapshots, deduplicate by year (keep highest-scored if multiple)
    by_year: dict[int, YearlySnapshot] = {}
    for full in fulls:
        snap = _snapshot_from_full(full)
        year = snap.declaration_year
        if year not in by_year:
            by_year[year] = snap
        # If duplicate year, keep the one with more data (more income entries)
        elif snap.income_count > by_year[year].income_count:
            by_year[year] = snap

    snapshots = sorted(by_year.values(), key=lambda s: s.declaration_year)

    # Compute year-over-year changes between consecutive annual declarations
    annual = [s for s in snapshots if s.declaration_type == 1]
    changes: list[YOYChange] = []
    for i in range(1, len(annual)):
        changes.append(_compute_change(annual[i - 1], annual[i]))

    # Pre-compute worst-case signals
    income_ratios = [
        c.income_ratio for c in changes
        if c.income_ratio is not None
    ]
    monetary_ratios = [
        c.monetary_ratio for c in changes
        if c.monetary_ratio is not None
    ]
    cash_deltas = [
        c.cash_delta for c in changes
        if c.cash_delta is not None and c.cash_delta > 0
    ]

    return PersonTimeline(
        user_declarant_id=int(uid),
        name=name,
        snapshots=snapshots,
        changes=changes,
        max_income_ratio=max(income_ratios, default=None),
        max_monetary_ratio=max(monetary_ratios, default=None),
        max_cash_delta=max(cash_deltas, default=None),
    )


def assemble_timelines_from_raw(
    raws: list[dict[str, Any]],
) -> dict[int, PersonTimeline]:
    """Build timelines for all persons across a corpus of raw declarations.

    Parameters
    ----------
    raws:
        Raw declaration dicts (from ``load_declaration``).

    Returns
    -------
    Dict mapping ``user_declarant_id`` → ``PersonTimeline`` for persons with
    more than one declaration in the corpus.
    """
    from app.services.pipeline import process_declaration_full

    # Group by user_declarant_id
    groups: dict[int, list[dict]] = {}
    for raw in raws:
        uid = raw.get("user_declarant_id")
        if uid is None:
            continue
        full = process_declaration_full(raw)
        groups.setdefault(int(uid), []).append(full)

    # Only build timelines for persons with 2+ declarations
    timelines: dict[int, PersonTimeline] = {}
    for uid, fulls in groups.items():
        if len(fulls) < 2:
            continue
        tl = assemble_timeline(fulls)
        if tl is not None:
            timelines[uid] = tl

    return timelines
