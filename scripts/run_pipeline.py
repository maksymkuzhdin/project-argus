#!/usr/bin/env python3
"""
Project Argus — End-to-end pipeline.

Loads raw declaration JSONs, sanitizes, parses, scores, and prints a report.

Usage:
    python scripts/run_pipeline.py [--year 2023] [--limit 10]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.normalization.sanitize import sanitize
from app.services.pipeline import process_declaration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("argus.pipeline")


def main() -> None:
    parser = argparse.ArgumentParser(description="Argus — Run pipeline")
    parser.add_argument("--year", type=str, default=None, help="Filter by year")
    parser.add_argument("--limit", type=int, default=None, help="Max declarations")
    parser.add_argument("--data-dir", type=str, default=settings.raw_data_dir, help="Raw data dir")
    args = parser.parse_args()

    raw_dir = Path(args.data_dir)
    files = iter_raw_declarations(raw_dir, year=args.year)

    if args.limit:
        files = files[: args.limit]

    if not files:
        logger.warning("No raw declarations found in %s", raw_dir)
        return

    logger.info("Processing %d declarations from %s", len(files), raw_dir)

    results = []
    for f in files:
        raw = load_declaration(f)
        summary = process_declaration(raw)
        results.append(summary)
        logger.info(
            "  %s — score=%.3f triggered=%s income=%s assets=%s",
            summary["declaration_id"][:20],
            summary["score"],
            summary["triggered_rules"],
            summary["total_income"],
            summary["total_assets"],
        )

    # Summary
    print("\n" + "=" * 60)
    print(f"Pipeline complete: {len(results)} declarations processed")
    flagged = [r for r in results if r["triggered_rules"]]
    print(f"Flagged: {len(flagged)} / {len(results)}")
    if flagged:
        print("\nFlagged declarations:")
        for r in flagged:
            print(f"  {r['declaration_id'][:30]} — score={r['score']:.3f}")
            for rule in r["triggered_rules"]:
                print(f"    • {rule}")
    print("=" * 60)


if __name__ == "__main__":
    main()
