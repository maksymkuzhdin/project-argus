"""
Project Argus — Parser for step_3 (real estate) with ownership resolution.

Extracts normalised real-estate rows and resolves ``rights.rightBelongs``
to determine whether the owner is the declarant, a family member, or
another entity.
"""

from __future__ import annotations

from typing import Any

from app.normalization.parse_step_2 import build_family_index
from app.normalization.parse_utils import safe_parse_number


def _resolve_owner(right_belongs: str, family_index: dict[str, str]) -> str:
    """Classify a ``rightBelongs`` value.

    Returns
    -------
    One of:
    - ``"declarant"`` if *right_belongs* == ``"1"``
    - A family label like ``"чоловік (Микола Рубан)"`` if found in index
    - ``"third_party"`` if *right_belongs* == ``"j"``
    - ``"unknown:<raw>"`` otherwise
    """
    if right_belongs in family_index:
        return family_index[right_belongs]
    if right_belongs == "j":
        return "third_party"
    return f"unknown:{right_belongs}"


def parse_step_3(declaration: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse step_3 real-estate data with ownership resolution.

    Each property may have **multiple** rights entries (shared ownership).
    This parser produces **one row per right** so that every ownership
    stake is independently queryable.

    Parameters
    ----------
    declaration:
        The full declaration dict.

    Returns
    -------
    A list of flat dicts, one per (property × right) combination.
    """
    declaration_id = declaration.get("id", "")
    step = declaration.get("data", {}).get("step_3", {})

    if step.get("isNotApplicable") == 1:
        return []

    raw_items = step.get("data", [])
    if not isinstance(raw_items, list):
        return []

    family_index = build_family_index(declaration)

    results: list[dict[str, Any]] = []

    for item in raw_items:
        # Total area
        area, area_raw, area_status = safe_parse_number(item.get("totalArea"))

        # Cost / assessment value
        cost, cost_raw, cost_status = safe_parse_number(
            item.get("cost_date_assessment")
        )

        # Location fields
        location = {
            "country": item.get("country"),
            "region": item.get("region"),
            "district": item.get("district"),
            "community": item.get("community"),
            "city": item.get("city"),
            "city_type": item.get("cityType"),
        }

        # Rights — one row per right
        rights = item.get("rights", [])
        if not isinstance(rights, list) or len(rights) == 0:
            # Property with no rights info — emit one row anyway
            results.append(
                {
                    "declaration_id": declaration_id,
                    "object_type": item.get("objectType"),
                    "other_object_type": item.get("otherObjectType"),
                    "total_area": area,
                    "total_area_raw": area_raw,
                    "total_area_status": area_status,
                    "cost_assessment": cost,
                    "cost_assessment_raw": cost_raw,
                    "cost_assessment_status": cost_status,
                    "owning_date": item.get("owningDate"),
                    "right_belongs_raw": None,
                    "right_belongs_resolved": None,
                    "ownership_type": None,
                    "percent_ownership": None,
                    **location,
                    "raw_iteration": str(item.get("iteration", "")),
                }
            )
        else:
            for r in rights:
                rb_raw = str(r.get("rightBelongs", ""))
                pct = r.get("percent-ownership")

                results.append(
                    {
                        "declaration_id": declaration_id,
                        "object_type": item.get("objectType"),
                        "other_object_type": item.get("otherObjectType"),
                        "total_area": area,
                        "total_area_raw": area_raw,
                        "total_area_status": area_status,
                        "cost_assessment": cost,
                        "cost_assessment_raw": cost_raw,
                        "cost_assessment_status": cost_status,
                        "owning_date": item.get("owningDate"),
                        "right_belongs_raw": rb_raw,
                        "right_belongs_resolved": _resolve_owner(
                            rb_raw, family_index
                        ),
                        "ownership_type": r.get("ownershipType"),
                        "percent_ownership": pct,
                        **location,
                        "raw_iteration": str(item.get("iteration", "")),
                    }
                )

    return results
