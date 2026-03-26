"""
Project Argus — Currency normalisation utility.

Provides approximate fixed exchange rates to convert multi-currency
monetary-asset amounts into UAH for feature computation.

Income declarations (step_11) are always denominated in UAH per NAZK
regulations, so no conversion is required there.  Monetary assets
(step_12) carry an explicit ``currency_code`` that may be USD, EUR,
GBP, etc.

The rates below are approximate NBU (National Bank of Ukraine) mid-rates
for the 2023–2024 period.  They are intentionally rounded — the goal is
order-of-magnitude normalisation for anomaly detection, not accounting
precision.
"""

from __future__ import annotations

from decimal import Decimal


# Approximate NBU mid-rates, 2023–2024.
_RATES_TO_UAH: dict[str, Decimal] = {
    "UAH": Decimal("1"),
    "USD": Decimal("37"),
    "EUR": Decimal("40"),
    "GBP": Decimal("46"),
    "PLN": Decimal("9"),
    "CHF": Decimal("42"),
    "CAD": Decimal("28"),
    "CZK": Decimal("1.65"),
    "JPY": Decimal("0.25"),
}


def to_uah(
    amount: Decimal | float | None,
    currency_code: str | None,
) -> Decimal | None:
    """Convert *amount* to UAH using a fixed approximate rate.

    Parameters
    ----------
    amount:
        The original amount in the source currency.
    currency_code:
        ISO 4217 code (e.g. ``"USD"``).  ``None`` or ``"UAH"`` returns
        *amount* unchanged.  Unknown codes are treated as UAH (safe
        default for a Ukrainian-centric corpus).

    Returns
    -------
    The amount expressed in approximate UAH, or ``None`` if *amount*
    is ``None``.
    """
    if amount is None:
        return None

    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))

    if currency_code is None or currency_code == "UAH":
        return amount

    rate = _RATES_TO_UAH.get(currency_code)
    if rate is None:
        # Unknown currency — return as-is rather than discarding.
        return amount

    return amount * rate
