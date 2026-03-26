"""
run_normalization.py — Process raw declarations through the normalization pipeline.

Reads raw JSON files from the data directory, runs them through
sanitization and all parsing steps, and prints a summary.

Usage: python scripts/run_normalization.py [--data-dir PATH] [--year YEAR]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the backend package is importable when running from the scripts/ dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.normalization.sanitize import sanitize
from app.normalization.parse_step_1 import parse_step_1
from app.normalization.parse_step_2 import build_family_index, parse_step_2
from app.normalization.parse_step_3 import parse_step_3
from app.normalization.parse_step_6 import parse_step_6
from app.normalization.parse_step_11 import parse_step_11
from app.normalization.parse_step_12 import parse_step_12
from app.normalization.parse_step_17 import parse_step_17

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def normalize_one(raw: dict) -> dict:
    """Run all normalization steps on a single raw declaration."""
    clean = sanitize(raw)
    family_index = build_family_index(clean)

    return {
        "id": raw.get("id", "unknown"),
        "bio": parse_step_1(clean),
        "family_members": parse_step_2(clean),
        "real_estate": parse_step_3(clean),
        "vehicles": parse_step_6(clean, family_index),
        "incomes": parse_step_11(clean),
        "monetary": parse_step_12(clean),
        "bank_accounts": parse_step_17(clean, family_index),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize raw declarations.")
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

    success = 0
    errors = 0
    for f in files:
        try:
            raw = load_declaration(f)
            result = normalize_one(raw)
            doc_id = result["id"]
            bio = result["bio"]
            name = f"{bio.get('firstname', '')} {bio.get('lastname', '')}".strip() or "Unknown"
            logger.info(
                "  %s | %s | family=%d income=%d monetary=%d re=%d vehicles=%d bank=%d",
                doc_id[:12],
                name,
                len(result["family_members"]),
                len(result["incomes"]),
                len(result["monetary"]),
                len(result["real_estate"]),
                len(result["vehicles"]),
                len(result["bank_accounts"]),
            )
            success += 1
        except Exception:
            logger.exception("  Failed to process %s", f.name)
            errors += 1

    logger.info("Done. %d succeeded, %d failed.", success, errors)


if __name__ == "__main__":
    main()
