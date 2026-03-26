"""
Project Argus — Internal pipeline processing logic.

Shared between the CLI pipeline runner and the API endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from app.features.cash import classify_monetary_assets
from app.features.income import compute_total_income
from app.features.ownership import compute_ownership_summary
from app.features.wealth import compute_largest_acquisition, compute_total_assets
from app.normalization.parse_step_2 import build_family_index, parse_step_2
from app.normalization.parse_step_3 import parse_step_3
from app.normalization.parse_step_6 import parse_step_6
from app.normalization.parse_step_11 import parse_step_11
from app.normalization.parse_step_12 import parse_step_12
from app.normalization.parse_step_17 import parse_step_17
from app.normalization.sanitize import sanitize
from app.scoring.rules import score_declaration

logger = logging.getLogger(__name__)


def _count_unknowns(rows_list: list[list[dict]]) -> tuple[int, int]:
    """Count total value fields and how many are unknown/placeholder.

    The sanitizer sets ``*_status`` fields to ``None`` when the original
    value was successfully parsed, and to a descriptive string (e.g.
    ``"not_applicable"``, ``"confidential"``, ``"unknown"``) when the
    original value was a placeholder.  So ``status is not None`` means
    the value is *missing*, which is the unknown count.
    """
    total = 0
    unknown = 0
    status_fields = [
        "amount_status", "total_area_status",
        "cost_assessment_status", "organization_status",
    ]
    for rows in rows_list:
        for row in rows:
            for sf in status_fields:
                if sf in row:
                    total += 1
                    if row[sf] is not None:
                        unknown += 1
    return total, unknown


def process_declaration(raw: dict) -> dict:
    """Process a single declaration through the full pipeline.

    Returns a summary dict with parsed counts and scores.
    """
    declaration_id = raw.get("id", "unknown")

    # 1. Sanitize
    clean = sanitize(raw)

    # 2. Parse
    family_index = build_family_index(clean)
    family = parse_step_2(clean)
    real_estate = parse_step_3(clean)
    vehicles = parse_step_6(clean, family_index)
    bank_accounts = parse_step_17(clean, family_index)
    incomes = parse_step_11(clean)
    monetary = parse_step_12(clean)

    # 3. Feature extraction (using dedicated modules)
    total_income = compute_total_income(incomes)
    total_assets = compute_total_assets(real_estate, monetary)
    cash_bank = classify_monetary_assets(monetary)
    largest_acq = compute_largest_acquisition(real_estate)
    ownership = compute_ownership_summary(real_estate, vehicles, bank_accounts)

    # Unknown-value frequency
    total_fields, unknown_fields = _count_unknowns(
        [incomes, monetary, real_estate]
    )

    # 4. Score
    result = score_declaration(
        total_income=total_income,
        total_assets=total_assets,
        cash_holdings=cash_bank.cash,
        bank_deposits=cash_bank.bank,
        total_value_fields=total_fields,
        unknown_value_fields=unknown_fields,
        largest_acquisition_cost=largest_acq,
        ownership_declarant=ownership.declarant_items,
        ownership_family=ownership.family_items,
        ownership_total=ownership.total_items,
    )

    return {
        "declaration_id": declaration_id,
        "family_members": len(family),
        "incomes": len(incomes),
        "monetary_assets": len(monetary),
        "real_estate_rights": len(real_estate),
        "total_income": str(total_income) if total_income else None,
        "total_assets": str(total_assets) if total_assets else None,
        "score": result.total_score,
        "triggered_rules": result.triggered_rules,
        "explanation": result.explanation_summary,
    }



def process_declaration_full(raw: dict) -> dict[str, Any]:
    """Process a declaration and return all parsed sections + features + scores.

    Unlike ``process_declaration`` (summary only), this returns the full
    parsed data needed for the detail view and DB persistence.
    """
    declaration_id = raw.get("id", "unknown")

    # Top-level person metadata (stable across years for the same person)
    user_declarant_id = raw.get("user_declarant_id")
    declaration_year = raw.get("declaration_year")
    declaration_type = raw.get("declaration_type")

    # 1. Sanitize
    clean = sanitize(raw)

    # 2. Parse all steps
    from app.normalization.parse_step_1 import parse_step_1
    from app.normalization.parse_step_2 import build_family_index
    from app.normalization.parse_step_6 import parse_step_6
    from app.normalization.parse_step_17 import parse_step_17

    family_index = build_family_index(clean)
    bio = parse_step_1(clean)
    family = parse_step_2(clean)
    real_estate = parse_step_3(clean)
    vehicles = parse_step_6(clean, family_index)
    bank_accounts = parse_step_17(clean, family_index)
    incomes = parse_step_11(clean)
    monetary = parse_step_12(clean)

    # 3. Features
    total_income = compute_total_income(incomes)
    total_assets = compute_total_assets(real_estate, monetary)
    cash_bank = classify_monetary_assets(monetary)
    largest_acq = compute_largest_acquisition(real_estate)
    ownership = compute_ownership_summary(real_estate, vehicles, bank_accounts)
    total_fields, unknown_fields = _count_unknowns(
        [incomes, monetary, real_estate]
    )

    # 4. Score
    result = score_declaration(
        total_income=total_income,
        total_assets=total_assets,
        cash_holdings=cash_bank.cash,
        bank_deposits=cash_bank.bank,
        total_value_fields=total_fields,
        unknown_value_fields=unknown_fields,
        largest_acquisition_cost=largest_acq,
        ownership_declarant=ownership.declarant_items,
        ownership_family=ownership.family_items,
        ownership_total=ownership.total_items,
    )

    return {
        "declaration_id": declaration_id,
        "user_declarant_id": user_declarant_id,
        "declaration_year": declaration_year,
        "declaration_type": declaration_type,
        "bio": bio,
        "family_members": family,
        "real_estate": real_estate,
        "vehicles": vehicles,
        "bank_accounts": bank_accounts,
        "incomes": incomes,
        "monetary": monetary,
        "features": {
            "total_income": str(total_income) if total_income else None,
            "total_assets": str(total_assets) if total_assets else None,
            "cash": str(cash_bank.cash) if cash_bank.cash else None,
            "bank": str(cash_bank.bank) if cash_bank.bank else None,
            "cash_ratio": cash_bank.cash_ratio,
            "largest_acquisition": str(largest_acq) if largest_acq else None,
            "total_value_fields": total_fields,
            "unknown_value_fields": unknown_fields,
        },
        "score": {
            "total_score": result.total_score,
            "triggered_rules": result.triggered_rules,
            "explanation": result.explanation_summary,
            "rule_details": [
                {
                    "rule_name": r.rule_name,
                    "score": r.score,
                    "triggered": r.triggered,
                    "explanation": r.explanation,
                }
                for r in result.rule_results
            ],
        },
    }
