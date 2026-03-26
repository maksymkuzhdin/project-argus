"""
Project Argus — Recursive sanitizer for Ukrainian declaration data.

Walks any JSON-derived data structure and converts bracketed placeholder
strings (e.g. "[Конфіденційна інформація]") into structured
``{"value": None, "status": "<code>"}`` representations.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Placeholder mappings
# ---------------------------------------------------------------------------

#: Ukrainian bracket → normalised status code
PLACEHOLDER_MAP: dict[str, str] = {
    "[Конфіденційна інформація]": "confidential",
    "[Не застосовується]": "not_applicable",
    "[Не відомо]": "unknown",
    "[Член сім'ї не надав інформацію]": "family_no_info",
}

#: Numeric ``_extendedstatus`` field values → status code.
#: ``0`` means the value was actually provided (no special status).
EXTENDEDSTATUS_MAP: dict[int, str | None] = {
    0: None,             # value provided normally
    1: "not_applicable",
    2: "unknown",
    3: "family_no_info",
}

_BRACKET_RE = re.compile(r"^\[.+\]$")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def classify_placeholder(text: str) -> str | None:
    """Return the status code if *text* is a known bracketed placeholder,
    ``"redacted_other"`` if it matches the bracket pattern but is not in the
    known map, or ``None`` if it is not a placeholder at all."""
    if text in PLACEHOLDER_MAP:
        return PLACEHOLDER_MAP[text]
    if _BRACKET_RE.match(text):
        return "redacted_other"
    return None


def is_placeholder(text: str) -> bool:
    """Return ``True`` if *text* is any recognised bracketed sentinel."""
    return text in PLACEHOLDER_MAP


# ---------------------------------------------------------------------------
# Core sanitizer
# ---------------------------------------------------------------------------

def _sanitize_value(value: str) -> Any:
    """Convert a placeholder string to structured form, or return as-is."""
    status = classify_placeholder(value)
    if status is not None:
        result: dict[str, Any] = {"value": None, "status": status}
        if status == "redacted_other":
            result["original"] = value
        return result
    return value


def sanitize(data: Any) -> Any:
    """Recursively walk *data* and replace bracketed placeholder strings
    with ``{"value": None, "status": "<code>"}`` dicts.

    Handles nested dicts, lists, and scalar values. Non-string scalars
    (numbers, booleans, ``None``) pass through unchanged.

    Parameters
    ----------
    data:
        Any JSON-compatible value — typically the parsed declaration dict.

    Returns
    -------
    A new structure with all placeholders converted. The original *data*
    is never mutated.
    """
    if isinstance(data, dict):
        return {key: sanitize(value) for key, value in data.items()}
    if isinstance(data, list):
        return [sanitize(item) for item in data]
    if isinstance(data, str):
        return _sanitize_value(data)
    # int, float, bool, None — pass through
    return data
