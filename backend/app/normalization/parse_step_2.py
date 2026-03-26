"""
Project Argus — Parser for step_2 (family members).

Builds a lookup index of family members from a declaration so that
ownership resolution can map ``rightBelongs`` IDs to real people.
"""

from __future__ import annotations

from typing import Any


def parse_step_2(declaration: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse step_2 family-member data from a full declaration.

    Returns
    -------
    A list of flat dicts, one per family member.
    """
    declaration_id = declaration.get("id", "")
    step = declaration.get("data", {}).get("step_2", {})

    if step.get("isNotApplicable") == 1:
        return []

    raw_items = step.get("data", [])
    if not isinstance(raw_items, list):
        return []

    results: list[dict[str, Any]] = []

    for item in raw_items:
        results.append(
            {
                "declaration_id": declaration_id,
                "member_id": str(item.get("id", "")),
                "relation": item.get("subjectRelation"),
                "firstname": item.get("firstname"),
                "lastname": item.get("lastname"),
                "middlename": item.get("middlename"),
            }
        )

    return results


def build_family_index(declaration: dict[str, Any]) -> dict[str, str]:
    """Build a mapping of family-member ID → human-readable label.

    The index always includes ``"1" → "declarant"``.

    Returns
    -------
    dict mapping string IDs to labels like ``"declarant"``,
    ``"чоловік (Микола Рубан)"``, etc.
    """
    index: dict[str, str] = {"1": "declarant"}

    members = parse_step_2(declaration)
    for m in members:
        mid = m["member_id"]
        parts = [m.get("firstname") or "", m.get("lastname") or ""]
        name = " ".join(p for p in parts if p).strip()
        relation = m.get("relation") or "family"
        label = f"{relation} ({name})" if name else relation
        index[mid] = label

    return index
