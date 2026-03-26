"""
Project Argus — Parser for step_1 (Declarant Profile).

Extracts the main biographical and employment information from the declarant.
"""

from __future__ import annotations

from typing import Any


def parse_step_1(declaration: dict[str, Any]) -> dict[str, Any]:
    """Parse step_1 bio from a sanitized declaration.

    Returns
    -------
    A flat dictionary ready for the `declarant_profiles` database table.
    """
    declaration_id = str(declaration.get("id", ""))
    
    # Step 1 is structured as: {"data": {"step_1": {"data": {...}}}}
    step = declaration.get("data", {}).get("step_1", {})
    item = step.get("data", {})

    if not isinstance(item, dict):
        item = {}

    return {
        "declaration_id": declaration_id,
        "firstname": item.get("firstname"),
        "lastname": item.get("lastname"),
        "middlename": item.get("middlename"),
        "work_post": item.get("workPost"),
        "work_place": item.get("workPlace"),
        "post_type": item.get("postType"),
        "post_category": item.get("postCategory"),
    }
