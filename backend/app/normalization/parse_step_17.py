"""
Project Argus — Parser for step_17 (Bank Accounts).

Extracts banking institutions where the declarant or family members hold accounts.
"""

from __future__ import annotations

from typing import Any

def _resolve_owner(right_belongs: str, family_index: dict[str, str]) -> str:
    if right_belongs in family_index:
        return family_index[right_belongs]
    if right_belongs == "j":
        return "third_party"
    return f"unknown:{right_belongs}"


def parse_step_17(
    declaration: dict[str, Any], family_index: dict[str, str]
) -> list[dict[str, Any]]:
    """Parse step_17 bank accounts from a sanitized declaration.

    Builds normalized representations of bank accounts including ownership resolution.
    Note that a single 'institution' entry may have multiple accounts for different
    family members listed under `persons_has_accounts`. We generate a flat list.

    Returns
    -------
    A list of flat dictionaries ready for the `bank_accounts` database table.
    """
    declaration_id = str(declaration.get("id", ""))
    step = declaration.get("data", {}).get("step_17", {})

    if step.get("isNotApplicable") == 1:
        return []

    raw_items = step.get("data", [])
    if not isinstance(raw_items, list):
        if isinstance(raw_items, dict):
            raw_items = list(raw_items.values())
        else:
            return []

    results: list[dict[str, Any]] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        institution_name = item.get("establishment_ua_company_name")
        institution_code = item.get("establishment_ua_company_code")

        # Accounts are listed under `persons_has_accounts` which is usually a dict of {id: {person_has_account: ...}}
        persons_has_accounts = item.get("persons_has_accounts", {})
        
        # Sometimes it's a list if the JSON arrays were preserved
        if isinstance(persons_has_accounts, list):
            accounts = persons_has_accounts
        elif isinstance(persons_has_accounts, dict):
            accounts = list(persons_has_accounts.values())
        else:
            accounts = []

        # If there are no specific accounts, but the institution is listed, we can try to fallback to `person_who_care`
        if not accounts:
            fallback_persons = item.get("person_who_care", [])
            for p in fallback_persons:
                if isinstance(p, dict) and "person" in p:
                    accounts.append({"person_has_account": p["person"]})

        # Generate one row per account owner
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
                
            owner_id = str(acc.get("person_has_account", ""))
            resolved_owner = _resolve_owner(owner_id, family_index)
            
            # Use the item's iteration as the raw_iteration
            raw_iter = str(item.get("iteration", ""))
            # Or the account's specific iteration if available
            if "iteration" in acc:
                raw_iter = str(acc["iteration"])

            results.append(
                {
                    "declaration_id": declaration_id,
                    "institution_name": institution_name,
                    "institution_code": institution_code,
                    "account_owner_resolved": resolved_owner,
                    "raw_iteration": raw_iter,
                }
            )

    return results
