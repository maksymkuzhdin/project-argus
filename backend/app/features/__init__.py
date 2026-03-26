"""
Project Argus — Feature engineering modules.

Each module computes a focused set of features from parsed declaration data:

- ``wealth``: Total assets, asset-to-income ratio, largest acquisition.
- ``income``: Total income, source count, type breakdown.
- ``cash``: Cash vs bank classification and ratio.
- ``ownership``: Ownership distribution across asset types.
"""

from app.features.cash import CashBankSplit, classify_monetary_assets
from app.features.income import (
    compute_income_source_count,
    compute_income_type_breakdown,
    compute_total_income,
)
from app.features.ownership import OwnershipSummary, compute_ownership_summary
from app.features.wealth import (
    compute_asset_income_ratio,
    compute_largest_acquisition,
    compute_total_assets,
)

__all__ = [
    "CashBankSplit",
    "classify_monetary_assets",
    "compute_total_income",
    "compute_income_source_count",
    "compute_income_type_breakdown",
    "OwnershipSummary",
    "compute_ownership_summary",
    "compute_total_assets",
    "compute_asset_income_ratio",
    "compute_largest_acquisition",
]
