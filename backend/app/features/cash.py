"""
Project Argus — Feature engineering: Cash vs Bank classification.

Classifies monetary assets into cash, bank deposits, and other categories,
then computes the cash-to-bank ratio used by scoring rules.

All amounts are normalised to UAH before summation so that USD/EUR
deposits are comparable to UAH holdings.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.normalization.currency import to_uah

# Ukrainian-language asset type substrings used to classify monetary items.
# Matched case-insensitively.
_CASH_KEYWORDS = ("готівкові", "готівка")
_BANK_KEYWORDS = ("банківських", "фінансових", "внески")


@dataclass
class CashBankSplit:
    """Result of classifying monetary assets into cash vs bank."""

    cash: Decimal | None
    bank: Decimal | None
    other: Decimal | None

    @property
    def cash_ratio(self) -> float | None:
        """Cash / (cash + bank).  Returns ``None`` if both are zero or missing."""
        c = self.cash or Decimal(0)
        b = self.bank or Decimal(0)
        total = c + b
        if total <= 0:
            return None
        return round(float(c / total), 4)


def classify_monetary_assets(
    monetary: list[dict[str, Any]],
) -> CashBankSplit:
    """Split monetary assets into cash, bank, and other buckets.

    Classification is based on the Ukrainian ``asset_type`` string
    (case-insensitive).  Amounts are converted to UAH using the
    item's ``currency_code`` before summation.
    """
    cash = Decimal(0)
    bank = Decimal(0)
    other = Decimal(0)
    has_cash = False
    has_bank = False
    has_other = False

    for item in monetary:
        asset_type = (item.get("asset_type") or "").lower()
        amount_uah = to_uah(item.get("amount"), item.get("currency_code"))
        if amount_uah is None:
            continue

        if any(kw in asset_type for kw in _CASH_KEYWORDS):
            cash += amount_uah
            has_cash = True
        elif any(kw in asset_type for kw in _BANK_KEYWORDS):
            bank += amount_uah
            has_bank = True
        else:
            other += amount_uah
            has_other = True

    return CashBankSplit(
        cash=cash if has_cash else None,
        bank=bank if has_bank else None,
        other=other if has_other else None,
    )
