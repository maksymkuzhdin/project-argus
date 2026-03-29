"""
Project Argus — Multi-year timeline assembler.

Groups processed declarations for the same person (by ``user_declarant_id``),
sorts them chronologically, and computes year-over-year deltas used by the
temporal scoring rules (CR5, BR2, BR4, and the existing YOY rules).
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
    total_assets: Decimal | None  # combined real_estate + monetary
    cash: Decimal | None
    bank: Decimal | None

    income_count: int
    monetary_count: int
    real_estate_count: int
    vehicle_count: int

    # BR2: unknown-value share among high-value assets
    unknown_share: float  # fraction of high-value asset fields with unknown values

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

    # CR5: asset growth vs income growth
    assets_prev: Decimal | None
    assets_curr: Decimal | None
    asset_growth: float | None   # (assets_curr - assets_prev) / assets_prev
    income_growth: float | None  # (income_curr - income_prev) / income_prev

    # BR2: unknown-share trend
    unknown_share_prev: float
    unknown_share_curr: float
    unknown_share_delta: float  # curr - prev

    # BR4: role change detection
    role_prev: str
    role_curr: str
    role_changed: bool


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


def _safe_growth(prev: Decimal | None, curr: Decimal | None) -> float | None:
    """Compute (curr - prev) / max(prev, 1) growth rate."""
    if prev is None or curr is None:
        return None
    if prev <= 0:
        return None
    return float((curr - prev) / prev)


def _compute_unknown_share(
    real_estate: list[dict[str, Any]],
    monetary: list[dict[str, Any]],
    vehicles: list[dict[str, Any]],
) -> float:
    """Compute the fraction of high-value asset fields with unknown/placeholder values.

    Checks cost_assessment_status on real estate, amount_status on monetary
    assets, and cost_date on vehicles.
    """
    total = 0
    unknown = 0
    unknown_statuses = {"unknown", "family_no_info", "confidential", "redacted_other"}

    for r in real_estate:
        if r is None:
            continue
        status = r.get("cost_assessment_status")
        if status is not None or r.get("cost_assessment") is not None:
            total += 1
            if str(status or "") in unknown_statuses:
                unknown += 1

    for m in monetary:
        if m is None:
            continue
        status = m.get("amount_status")
        if status is not None or m.get("amount") is not None:
            total += 1
            if str(status or "") in unknown_statuses:
                unknown += 1

    for v in vehicles:
        if v is None:
            continue
        # Vehicles don't have a dedicated status field, but cost_date being None
        # when the vehicle exists is a proxy for unknown value
        if v.get("cost_date") is not None or v.get("brand"):
            total += 1
            if v.get("cost_date") is None:
                unknown += 1

    if total == 0:
        return 0.0
    return unknown / total


def _snapshot_from_full(full: dict[str, Any]) -> YearlySnapshot:
    """Build a YearlySnapshot from a ``process_declaration_full()`` result."""
    features = full.get("features") or {}
    bio = full.get("bio") or {}

    total_monetary = _to_decimal(features.get("total_assets"))  # monetary only
    total_real_estate = None  # not tracked separately in features yet

    # Compute combined total_assets for CR5
    total_assets = total_monetary  # start with monetary
    # Add real estate cost assessments if available
    re_total = Decimal(0)
    for r in full.get("real_estate", []):
        c = r.get("cost_assessment")
        if c is not None:
            re_total += Decimal(str(c))
    if re_total > 0:
        total_real_estate = re_total
        total_assets = (total_assets or Decimal(0)) + re_total

    # Compute unknown_share for BR2
    unknown_share = _compute_unknown_share(
        full.get("real_estate", []),
        full.get("monetary", []),
        full.get("vehicles", []),
    )

    return YearlySnapshot(
        declaration_id=str(full["declaration_id"]),
        declaration_year=full.get("declaration_year") or 0,
        declaration_type=full.get("declaration_type") or 1,
        total_income=_to_decimal(features.get("total_income")),
        total_monetary=total_monetary,
        total_real_estate=total_real_estate,
        total_assets=total_assets,
        cash=_to_decimal(features.get("cash")),
        bank=_to_decimal(features.get("bank")),
        income_count=len(full.get("incomes", [])),
        monetary_count=len(full.get("monetary", [])),
        real_estate_count=len(full.get("real_estate", [])),
        vehicle_count=len(full.get("vehicles", [])),
        unknown_share=unknown_share,
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

    # BR4: role change detection — compare normalized role strings
    role_prev = (a.role or "").strip().lower()
    role_curr = (b.role or "").strip().lower()
    role_changed = role_prev != role_curr and bool(role_prev) and bool(role_curr)

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
        # CR5: asset growth vs income growth
        assets_prev=a.total_assets,
        assets_curr=b.total_assets,
        asset_growth=_safe_growth(a.total_assets, b.total_assets),
        income_growth=_safe_growth(a.total_income, b.total_income),
        # BR2: unknown-share trend
        unknown_share_prev=a.unknown_share,
        unknown_share_curr=b.unknown_share,
        unknown_share_delta=b.unknown_share - a.unknown_share,
        # BR4: role change
        role_prev=a.role,
        role_curr=b.role,
        role_changed=role_changed,
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
