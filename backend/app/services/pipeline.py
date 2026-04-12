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


def _count_confidentials(rows_list: list[list[dict]]) -> tuple[int, int]:
    """Count value-status fields and those marked confidential/redacted."""
    total = 0
    confidential = 0
    status_fields = [
        "amount_status", "total_area_status",
        "cost_assessment_status", "organization_status",
    ]
    confidential_statuses = {"confidential", "redacted_other"}

    for rows in rows_list:
        for row in rows:
            for sf in status_fields:
                if sf in row:
                    total += 1
                    if str(row.get(sf) or "") in confidential_statuses:
                        confidential += 1
    return total, confidential


def process_declaration(raw: dict) -> dict:
    """Process a single declaration through the full pipeline.

    Returns a summary dict with parsed counts and scores.
    """
    declaration_id = raw.get("id", "unknown")
    declaration_year = raw.get("declaration_year")

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
    conf_total_fields, confidential_fields = _count_confidentials(
        [incomes, monetary, real_estate]
    )
    confidential_ratio = (
        confidential_fields / conf_total_fields
        if conf_total_fields > 0
        else 0.0
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
        incomes=incomes,
        monetary_assets=monetary,
        real_estate=real_estate,
        vehicles=vehicles,
        family_members=family,
        declaration_year=declaration_year,
        raw_declaration=raw,
    )


    return {
        "declaration_id": declaration_id,
        "family_members": len(family),
        "incomes": len(incomes),
        "monetary_assets": len(monetary),
        "real_estate_rights": len(real_estate),
        "total_income": str(total_income) if total_income else None,
        "total_assets": str(total_assets) if total_assets else None,
        "confidential_ratio": confidential_ratio,
        "score": result.total_score,
        "triggered_rules": result.triggered_rules,
        "explanation": result.explanation_summary,
    }



def process_declaration_full(
    raw: dict,
    *,
    cohort_stats: object | None = None,
    cohort_resolver: object | None = None,
    declaration_sector: str | None = None,
    declaration_gov_level: str | None = None,
    declaration_region: str | None = None,
    cohort_key_used: str | None = None,
) -> dict[str, Any]:
    """Process a declaration and return all parsed sections + features + scores.

    Unlike ``process_declaration`` (summary only), this returns the full
    parsed data needed for the detail view and DB persistence.

    Parameters
    ----------
    cohort_stats:
        Optional ``CohortStats`` for cohort-aware declaration checks
        (including CR6 relative mode and CR16 outlier checks).
    cohort_resolver, declaration_sector, declaration_gov_level, declaration_region, cohort_key_used:
        Optional taxonomy-aware cohort context forwarded to the scoring layer.
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

    # 2b. Ukraine-specific cohort taxonomy normalization
    cohort_taxonomy = None
    try:
        from app.scoring.cohort_taxonomy import create_normalizer_from_config
        from pathlib import Path
        
        yaml_path = str(Path(__file__).parent.parent / "scoring" / "cohort_taxonomy.yaml")
        normalizer = create_normalizer_from_config(yaml_path)
        
        # Extract work and post type info
        work_info = clean.get("work_info", [{}])[0] if clean.get("work_info") else {}
        work_post = work_info.get("post") or ""
        work_place = work_info.get("place") or ""
        
        # post_type and post_category are dicts with 'value' and 'status' keys
        post_type_dict = bio.get("post_type", {})
        post_type = (post_type_dict.get("value") if isinstance(post_type_dict, dict) else post_type_dict) or ""
        
        post_category_dict = bio.get("post_category", {})
        post_category = (post_category_dict.get("value") if isinstance(post_category_dict, dict) else post_category_dict) or ""
        
        # Normalize
        cohort_taxonomy = normalizer.normalize(
            work_post=work_post,
            work_place=work_place,
            post_type=post_type,
            post_category=post_category,
        )
    except Exception as e:
        logger.warning(f"Failed to normalize cohort taxonomy for {declaration_id}: {e}")
        cohort_taxonomy = None

    # 2c. Extraction of EDRPOU codes
    from app.normalization.edrpou_extractor import extract_edrpous
    from datetime import datetime, timezone
    
    edrpou_data = extract_edrpous(raw)
    edrpou_data["edrpou_extracted_at"] = datetime.now(timezone.utc)

    # 3. Features
    total_income = compute_total_income(incomes)
    total_assets = compute_total_assets(real_estate, monetary)
    cash_bank = classify_monetary_assets(monetary)
    largest_acq = compute_largest_acquisition(real_estate)
    ownership = compute_ownership_summary(real_estate, vehicles, bank_accounts)
    total_fields, unknown_fields = _count_unknowns(
        [incomes, monetary, real_estate]
    )
    conf_total_fields, confidential_fields = _count_confidentials(
        [incomes, monetary, real_estate]
    )
    confidential_ratio = (
        confidential_fields / conf_total_fields
        if conf_total_fields > 0
        else 0.0
    )

    # 4. Score
    if cohort_taxonomy is not None:
        if declaration_sector is None:
            declaration_sector = cohort_taxonomy.sector
        if declaration_gov_level is None:
            declaration_gov_level = cohort_taxonomy.government_level
        if cohort_key_used is None:
            cohort_key_used = f"{declaration_sector or 'unknown'}_{declaration_gov_level or 'unknown'}"

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
        incomes=incomes,
        monetary_assets=monetary,
        real_estate=real_estate,
        vehicles=vehicles,
        family_members=family,
        declaration_year=declaration_year,
        raw_declaration=raw,
        cohort_stats=cohort_stats,
        cohort_resolver=cohort_resolver,
        declaration_sector=declaration_sector,
        declaration_gov_level=declaration_gov_level,
        declaration_region=declaration_region,
        cohort_key_used=cohort_key_used,
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
        "cohort_taxonomy": {
            "role_family": cohort_taxonomy.role_family if cohort_taxonomy else None,
            "role_family_confidence": cohort_taxonomy.role_family_confidence if cohort_taxonomy else None,
            "institution_family": cohort_taxonomy.institution_family if cohort_taxonomy else None,
            "institution_family_confidence": cohort_taxonomy.institution_family_confidence if cohort_taxonomy else None,
            "sector": cohort_taxonomy.sector if cohort_taxonomy else None,
            "government_level": cohort_taxonomy.government_level if cohort_taxonomy else None,
        } if cohort_taxonomy else None,
        "edrpou": edrpou_data,
        "features": {
            "total_income": str(total_income) if total_income else None,
            "total_assets": str(total_assets) if total_assets else None,
            "cash": str(cash_bank.cash) if cash_bank.cash else None,
            "bank": str(cash_bank.bank) if cash_bank.bank else None,
            "cash_ratio": cash_bank.cash_ratio,
            "largest_acquisition": str(largest_acq) if largest_acq else None,
            "total_value_fields": total_fields,
            "unknown_value_fields": unknown_fields,
            "confidential_ratio": confidential_ratio,
            "post_type": bio.get("post_type", ""),
        },
        "score": {
            "total_score": result.total_score,
            "corruption_risk_score": result.corruption_risk_score,
            "opacity_evasion_score": result.opacity_evasion_score,
            "data_quality_score": result.data_quality_score,
            "raw_total_score": result.raw_total_score,
            "triggered_rules": result.triggered_rules,
            "explanation": result.explanation_summary,
            "rule_details": [
                {
                    "rule_name": r.rule_name,
                    "score": r.score,
                    "triggered": r.triggered,
                    "explanation": r.explanation,
                    "category": r.category,
                    "severity": r.severity,
                    "confidence": r.confidence,
                    "metadata": r.metadata,
                }
                for r in result.rule_results
            ],
        },
    }
