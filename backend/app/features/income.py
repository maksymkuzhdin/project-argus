"""
Project Argus — Feature engineering: Income metrics.

Computes total declared income and income source diversity for a
single declaration.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def compute_total_income(incomes: list[dict[str, Any]]) -> Decimal | None:
    """Sum all parsed income amounts.

    Returns ``None`` if no numeric values are available.
    """
    total = Decimal(0)
    found_any = False

    for item in incomes:
        val = item.get("amount")
        if val is not None:
            total += val
            found_any = True

    return total if found_any else None


def compute_income_source_count(incomes: list[dict[str, Any]]) -> int:
    """Count distinct income sources by ``source_name``."""
    sources: set[str] = set()
    for item in incomes:
        name = item.get("source_name")
        if name:
            sources.add(name)
    return len(sources)


def compute_income_type_breakdown(
    incomes: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """Aggregate income amounts by ``income_type``.

    Returns a dict mapping income type to total amount.
    """
    breakdown: dict[str, Decimal] = {}
    for item in incomes:
        itype = item.get("income_type") or "unknown"
        amount = item.get("amount")
        if amount is not None:
            breakdown[itype] = breakdown.get(itype, Decimal(0)) + amount
    return breakdown
