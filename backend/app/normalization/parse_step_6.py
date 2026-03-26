"""
Project Argus — Parser for step_6 (vehicles).

Extracts vehicles such as cars, motorcycles, boats, etc.
"""

from __future__ import annotations

from typing import Any

from app.normalization.parse_utils import safe_parse_number

def _resolve_owner(right_belongs: str, family_index: dict[str, str]) -> str:
    if right_belongs in family_index:
        return family_index[right_belongs]
    if right_belongs == "j":
        return "third_party"
    return f"unknown:{right_belongs}"



def parse_step_6(
    declaration: dict[str, Any], family_index: dict[str, str]
) -> list[dict[str, Any]]:
    """Parse step_6 vehicles from a sanitized declaration.

    Builds normalized representations of vehicles including ownership resolution.

    Returns
    -------
    A list of flat dictionaries ready for the `vehicles` database table.
    """
    declaration_id = str(declaration.get("id", ""))
    step = declaration.get("data", {}).get("step_6", {})

    if step.get("isNotApplicable") == 1:
        return []

    raw_items = step.get("data", [])
    if not isinstance(raw_items, list):
        # Sometime step_6.data is a dict containing {"empty": True}
        if isinstance(raw_items, dict):
            raw_items = list(raw_items.values())
        else:
            return []

    results: list[dict[str, Any]] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue
            
        obj_type = item.get("objectType")
        if obj_type == "Інше":
            obj_type = item.get("otherObjectType")

        cost = item.get("costDate")
        cost_status = item.get("costDate_extendedstatus")
        if cost_status and not cost:
            cost_val = None
        else:
            cost_val, _, _ = safe_parse_number(cost)
            
        try:
            grad_year = int(item.get("graduationYear"))
        except (ValueError, TypeError):
            grad_year = None

        # Resolve primary ownership
        rights = item.get("rights", [])
        if not isinstance(rights, list):
            rights = []

        primary_right = rights[0] if rights else {}
        ownership_type = primary_right.get("ownershipType")
        belongs_raw = str(primary_right.get("rightBelongs", ""))
        resolved_owner = _resolve_owner(belongs_raw, family_index)

        results.append(
            {
                "declaration_id": declaration_id,
                "object_type": obj_type,
                "brand": item.get("brand"),
                "model": item.get("model"),
                "graduation_year": grad_year,
                "owning_date": item.get("owningDate"),
                "cost_date": cost_val,
                "ownership_type": ownership_type,
                "right_belongs_resolved": resolved_owner,
                "raw_iteration": item.get("iteration"),
            }
        )

    return results
