"""
Project Argus — Feature engineering: Ownership analysis.

Computes ownership distribution metrics across real estate, vehicles,
and bank accounts for a single declaration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OwnershipSummary:
    """Aggregated ownership metrics for a declaration."""

    total_items: int = 0
    declarant_items: int = 0
    family_items: int = 0
    third_party_items: int = 0
    unknown_items: int = 0

    @property
    def declarant_share(self) -> float | None:
        if self.total_items == 0:
            return None
        return round(self.declarant_items / self.total_items, 4)


def _classify_owner(resolved: str | None) -> str:
    """Map a resolved owner string to a classification bucket."""
    if resolved is None:
        return "unknown"
    if resolved == "declarant":
        return "declarant"
    if resolved == "third_party":
        return "third_party"
    if resolved.startswith("unknown:"):
        return "unknown"
    # Anything else is a named family member
    return "family"


def compute_ownership_summary(
    real_estate: list[dict[str, Any]],
    vehicles: list[dict[str, Any]],
    bank_accounts: list[dict[str, Any]],
) -> OwnershipSummary:
    """Build an ownership summary across all asset types.

    Uses the ``right_belongs_resolved`` / ``account_owner_resolved`` field
    from each parsed item.
    """
    summary = OwnershipSummary()

    for item in real_estate:
        summary.total_items += 1
        bucket = _classify_owner(item.get("right_belongs_resolved"))
        if bucket == "declarant":
            summary.declarant_items += 1
        elif bucket == "family":
            summary.family_items += 1
        elif bucket == "third_party":
            summary.third_party_items += 1
        else:
            summary.unknown_items += 1

    for item in vehicles:
        summary.total_items += 1
        bucket = _classify_owner(item.get("right_belongs_resolved"))
        if bucket == "declarant":
            summary.declarant_items += 1
        elif bucket == "family":
            summary.family_items += 1
        elif bucket == "third_party":
            summary.third_party_items += 1
        else:
            summary.unknown_items += 1

    for item in bank_accounts:
        summary.total_items += 1
        bucket = _classify_owner(item.get("account_owner_resolved"))
        if bucket == "declarant":
            summary.declarant_items += 1
        elif bucket == "family":
            summary.family_items += 1
        elif bucket == "third_party":
            summary.third_party_items += 1
        else:
            summary.unknown_items += 1

    return summary
