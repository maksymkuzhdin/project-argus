"""
Project Argus — Feature engineering: Wealth metrics.

Computes total asset value across real estate and monetary holdings,
plus asset-to-income ratio for a single declaration.

Monetary amounts are normalised to UAH before summation.
Real estate cost assessments are already in UAH.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.normalization.currency import to_uah

# Cap for the asset-to-income ratio to avoid float("inf") breaking
# downstream ML pipelines (sklearn, pandas, etc.).
_MAX_RATIO = 1_000.0


def compute_total_assets(
    real_estate: list[dict[str, Any]],
    monetary: list[dict[str, Any]],
) -> Decimal | None:
    """Sum of real estate cost assessments + monetary asset amounts (UAH).

    Real estate values are already in UAH.  Monetary amounts are
    converted from their declared currency to UAH before summation.

    Returns ``None`` if no numeric values are available.
    """
    total = Decimal(0)
    found_any = False

    for item in real_estate:
        val = item.get("cost_assessment")
        if val is not None:
            total += val
            found_any = True

    for item in monetary:
        val_uah = to_uah(item.get("amount"), item.get("currency_code"))
        if val_uah is not None:
            total += val_uah
            found_any = True

    return total if found_any else None


def compute_asset_income_ratio(
    total_assets: Decimal | None,
    total_income: Decimal | None,
) -> float | None:
    """Assets-to-income ratio, clamped to avoid infinity.

    Returns ``None`` when either input is missing.  When income ≤ 0
    and assets > 0, returns ``_MAX_RATIO`` instead of ``float("inf")``
    to keep downstream ML pipelines safe.
    """
    if total_assets is None or total_income is None:
        return None
    if total_income <= 0:
        return _MAX_RATIO if total_assets > 0 else None
    return min(round(float(total_assets / total_income), 2), _MAX_RATIO)


def compute_largest_acquisition(
    real_estate: list[dict[str, Any]],
) -> Decimal | None:
    """Return the highest cost_assessment across all real estate entries."""
    largest = None
    for item in real_estate:
        cost = item.get("cost_assessment")
        if cost is not None:
            if largest is None or cost > largest:
                largest = cost
    return largest
