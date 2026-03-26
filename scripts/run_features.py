"""
run_features.py — Extract features from raw declarations.

Reads raw JSON files, normalizes them, computes feature metrics,
and prints a feature summary for each declaration.

Usage: python scripts/run_features.py [--data-dir PATH] [--year YEAR]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.normalization.sanitize import sanitize
from app.normalization.parse_step_2 import build_family_index
from app.normalization.parse_step_3 import parse_step_3
from app.normalization.parse_step_6 import parse_step_6
from app.normalization.parse_step_11 import parse_step_11
from app.normalization.parse_step_12 import parse_step_12
from app.normalization.parse_step_17 import parse_step_17
from app.features.income import compute_total_income, compute_income_source_count
from app.features.wealth import (
    compute_total_assets,
    compute_asset_income_ratio,
    compute_largest_acquisition,
)
from app.features.cash import classify_monetary_assets
from app.features.ownership import compute_ownership_summary

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def extract_features(raw: dict) -> dict:
    """Parse and compute all features for a single declaration."""
    clean = sanitize(raw)
    family_index = build_family_index(clean)

    incomes = parse_step_11(clean)
    monetary = parse_step_12(clean)
    real_estate = parse_step_3(clean)
    vehicles = parse_step_6(clean, family_index)
    bank_accounts = parse_step_17(clean, family_index)

    total_income = compute_total_income(incomes)
    total_assets = compute_total_assets(real_estate, monetary)
    cash_bank = classify_monetary_assets(monetary)
    largest_acq = compute_largest_acquisition(real_estate)
    ownership = compute_ownership_summary(real_estate, vehicles, bank_accounts)

    return {
        "id": raw.get("id", "unknown"),
        "total_income": total_income,
        "income_sources": compute_income_source_count(incomes),
        "total_assets": total_assets,
        "asset_income_ratio": compute_asset_income_ratio(total_assets, total_income),
        "cash": cash_bank.cash,
        "bank": cash_bank.bank,
        "cash_ratio": cash_bank.cash_ratio,
        "largest_acquisition": largest_acq,
        "ownership_total": ownership.total_items,
        "ownership_declarant": ownership.declarant_items,
        "ownership_family": ownership.family_items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract features from raw declarations.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/raw"),
        help="Root directory containing raw declaration JSON files.",
    )
    parser.add_argument("--year", type=str, default=None, help="Filter by year.")
    args = parser.parse_args()

    files = iter_raw_declarations(args.data_dir, year=args.year)
    if not files:
        logger.warning("No raw files found in %s", args.data_dir)
        return

    logger.info("Found %d raw declaration files.", len(files))

    for f in files:
        try:
            raw = load_declaration(f)
            feat = extract_features(raw)
            doc_id = feat["id"]
            logger.info(
                "  %s | income=%s assets=%s ratio=%s cash_ratio=%s acq=%s own=%d/%d",
                str(doc_id)[:12],
                feat["total_income"],
                feat["total_assets"],
                feat["asset_income_ratio"],
                feat["cash_ratio"],
                feat["largest_acquisition"],
                feat["ownership_declarant"],
                feat["ownership_total"],
            )
        except Exception:
            logger.exception("  Failed to process %s", f.name)

    logger.info("Done.")


if __name__ == "__main__":
    main()
