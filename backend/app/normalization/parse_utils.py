"""
Project Argus — Shared utilities for declaration parsers.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.normalization.sanitize import classify_placeholder


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def safe_parse_number(value: Any) -> tuple[Optional[Decimal], Optional[str], Optional[str]]:
    """Attempt to parse a numeric string from a declaration field.

    Handles:
    - Ukrainian comma-as-decimal (``"3,40"`` → ``3.40``)
    - Space-separated thousands (``"1 000 000"`` → ``1000000``)
    - Bracketed placeholder strings → ``(None, raw, status)``
    - Already-sanitized dicts ``{"value": None, "status": "..."}``

    Returns
    -------
    tuple of (parsed_amount, raw_string, status)
        - ``(Decimal, raw, None)`` on success
        - ``(None, raw, status_code)`` if the value is a placeholder
        - ``(None, raw, "parse_error")`` if parsing fails
        - ``(None, None, None)`` if *value* is ``None`` or empty
    """
    if value is None or value == "":
        return None, None, None

    # Handle already-sanitized dict from sanitize()
    if isinstance(value, dict):
        return None, value.get("original"), value.get("status")

    if not isinstance(value, str):
        # Try to convert numbers directly
        try:
            return Decimal(str(value)), str(value), None
        except (InvalidOperation, ValueError):
            return None, str(value), "parse_error"

    raw = value

    # Check for placeholder
    status = classify_placeholder(value)
    if status is not None:
        return None, raw, status

    # Normalise: strip whitespace, replace comma decimal, remove spaces
    cleaned = value.strip().replace(" ", "").replace(",", ".")

    try:
        return Decimal(cleaned), raw, None
    except (InvalidOperation, ValueError):
        return None, raw, "parse_error"


# ---------------------------------------------------------------------------
# Currency extraction
# ---------------------------------------------------------------------------

#: Pattern to pull ISO-style currency code from strings like
#: ``"UAH (Українська гривня)"`` or just ``"USD"``.
_CURRENCY_CODE_RE = re.compile(r"^([A-Z]{3})\b")

#: Known long-form Ukrainian currency names → codes.
_CURRENCY_ALIASES: dict[str, str] = {
    "грн": "UAH",
    "гривня": "UAH",
    "гривні": "UAH",
    "долар": "USD",
    "євро": "EUR",
}


def extract_currency_code(raw: Any) -> str | None:
    """Extract an ISO 4217-ish currency code from a declaration currency string.

    Examples::

        >>> extract_currency_code("UAH (Українська гривня)")
        'UAH'
        >>> extract_currency_code("USD (Долар США)")
        'USD'
        >>> extract_currency_code("USD")
        'USD'
        >>> extract_currency_code(None)

    """
    if raw is None or raw == "":
        return None

    # Sanitized placeholders may be dicts like
    # {"value": None, "status": "unknown", "original": "[Не відомо]"}.
    if isinstance(raw, dict):
        candidate = raw.get("value")
        if candidate in (None, ""):
            candidate = raw.get("original")
        raw = candidate
        if raw is None or raw == "":
            return None

    if not isinstance(raw, str):
        raw = str(raw)

    # Try leading 3-letter code first
    m = _CURRENCY_CODE_RE.match(raw.strip())
    if m:
        return m.group(1)

    # Try known aliases (case-insensitive substring)
    lower = raw.lower()
    for alias, code in _CURRENCY_ALIASES.items():
        if alias in lower:
            return code

    return None
