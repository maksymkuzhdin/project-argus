"""
Project Argus — Parser for step_12 (monetary assets).

Extracts normalised monetary-asset rows from a full declaration dict.
"""

from __future__ import annotations

from typing import Any

from app.normalization.parse_utils import extract_currency_code, safe_parse_number
from app.normalization.sanitize import EXTENDEDSTATUS_MAP


def parse_step_12(declaration: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse step_12 monetary-asset data from a full declaration.

    Parameters
    ----------
    declaration:
        The top-level declaration dict (must contain ``data.step_12``).

    Returns
    -------
    A list of flat dicts, one per monetary-asset row, ready for DB insertion.
    Returns an empty list when step_12 is marked not-applicable or has
    no data.
    """
    declaration_id = declaration.get("id", "")
    step = declaration.get("data", {}).get("step_12", {})

    if step.get("isNotApplicable") == 1:
        return []

    raw_items = step.get("data", [])
    if not isinstance(raw_items, list):
        return []

    results: list[dict[str, Any]] = []

    for item in raw_items:
        amount, amount_raw, amount_status = safe_parse_number(
            item.get("sizeAssets")
        )

        currency_raw = item.get("assetsCurrency")
        currency_code = extract_currency_code(currency_raw)

        # Person linkage: capture all rights holders.
        # Primary holder promoted to top-level; extras in ``extra_rights``.
        person_ref = None
        ownership_type = None
        extra_rights: list[dict[str, Any]] = []

        rights = item.get("rights", [])
        if isinstance(rights, list):
            for idx, r in enumerate(rights):
                raw_belongs = r.get("rightBelongs")
                ref = str(raw_belongs) if raw_belongs is not None else None
                otype = r.get("ownershipType")
                if idx == 0:
                    person_ref = ref
                    ownership_type = otype
                else:
                    extra_rights.append({
                        "person_ref": ref,
                        "ownership_type": otype,
                    })

        # Organisation (may be a placeholder)
        organization = item.get("organization")
        organization_status = None
        ext = item.get("organization_extendedstatus")
        if ext is not None:
            organization_status = EXTENDEDSTATUS_MAP.get(int(ext))

        row: dict[str, Any] = {
            "declaration_id": declaration_id,
            "person_ref": person_ref,
            "asset_type": item.get("objectType"),
            "currency_raw": currency_raw,
            "currency_code": currency_code,
            "amount": amount,
            "amount_raw": amount_raw,
            "amount_status": amount_status,
            "organization": organization,
            "organization_status": organization_status,
            "ownership_type": ownership_type,
            "raw_iteration": str(item.get("iteration", "")),
        }

        if extra_rights:
            row["extra_rights"] = extra_rights

        results.append(row)

    return results
