"""
Project Argus — Parser for step_11 (income entries).

Extracts normalised income rows from a full declaration dict.
"""

from __future__ import annotations

from typing import Any

from app.normalization.parse_utils import safe_parse_number


def parse_step_11(declaration: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse step_11 income data from a full declaration.

    Parameters
    ----------
    declaration:
        The top-level declaration dict (must contain ``data.step_11``).

    Returns
    -------
    A list of flat dicts, one per income row, ready for DB insertion.
    Returns an empty list when step_11 is marked not-applicable or has
    no data.
    """
    declaration_id = declaration.get("id", "")
    step = declaration.get("data", {}).get("step_11", {})

    if step.get("isNotApplicable") == 1:
        return []

    raw_items = step.get("data", [])
    if not isinstance(raw_items, list):
        return []

    results: list[dict[str, Any]] = []

    for item in raw_items:
        amount, amount_raw, amount_status = safe_parse_number(
            item.get("sizeIncome")
        )

        # Person linkage: person_who_care[0].person
        person_ref = None
        pwc = item.get("person_who_care", [])
        if isinstance(pwc, list) and len(pwc) > 0:
            raw_person = pwc[0].get("person")
            person_ref = str(raw_person) if raw_person is not None else None

        # Source info: capture all sources, not just the first.
        # Primary source fields are promoted to top-level for backward
        # compat; additional sources stored in ``extra_sources``.
        source_name = None
        source_code = None
        source_type = None
        extra_sources: list[dict[str, Any]] = []

        sources = item.get("sources", [])
        if isinstance(sources, list):
            for idx, src in enumerate(sources):
                s_name = src.get("source_ua_company_name")
                s_code = src.get("source_ua_company_code")
                s_type = src.get("incomeSource")
                if idx == 0:
                    source_name = s_name
                    source_code = s_code
                    source_type = s_type
                else:
                    extra_sources.append({
                        "source_name": s_name,
                        "source_code": s_code,
                        "source_type": s_type,
                    })

        row: dict[str, Any] = {
            "declaration_id": declaration_id,
            "person_ref": person_ref,
            "income_type": item.get("objectType"),
            "income_type_other": item.get("otherObjectType"),
            "amount": amount,
            "amount_raw": amount_raw,
            "amount_status": amount_status,
            "source_name": source_name,
            "source_code": source_code,
            "source_type": source_type,
            "raw_iteration": str(item.get("iteration", "")),
        }

        if extra_sources:
            row["extra_sources"] = extra_sources

        results.append(row)

    return results
