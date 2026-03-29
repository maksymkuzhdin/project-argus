"""
run_scoring.py — Run the full scoring pipeline on raw declarations.

Reads raw JSON files, processes each through normalization, feature
extraction, and scoring, then prints a ranked summary.

Usage: python scripts/run_scoring.py [--data-dir PATH] [--year YEAR] [--top N] [--csv FILE] [--layer2]
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.features.cash import classify_monetary_assets
from app.normalization.parse_step_1 import parse_step_1
from app.normalization.parse_step_12 import parse_step_12
from app.normalization.sanitize import sanitize
from app.services.pipeline import process_declaration

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score raw declarations.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/raw"),
        help="Root directory containing raw declaration JSON files.",
    )
    parser.add_argument("--year", type=str, default=None, help="Filter by year.")
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Show only the top N by score (0 = show all).",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to write CSV output (e.g. output/scores.csv).",
    )
    parser.add_argument(
        "--layer2",
        action="store_true",
        help="Enable Layer 2 cohort-based scoring on top of Layer 1.",
    )
    args = parser.parse_args()

    files = iter_raw_declarations(args.data_dir, year=args.year)
    if not files:
        logger.warning("No raw files found in %s", args.data_dir)
        return

    logger.info("Found %d raw declaration files.", len(files))

    # ── Pass 1: Process all declarations (Layer 1) ──────────────────────
    results: list[dict] = []
    for f in files:
        try:
            raw = load_declaration(f)
            summary = process_declaration(raw)

            # Attach bio data for display and cohort grouping
            clean = sanitize(raw)
            bio = parse_step_1(clean)
            monetary = parse_step_12(clean)
            cash_stats = classify_monetary_assets(monetary)
            summary["name"] = (
                f"{bio.get('firstname', '')} {bio.get('lastname', '')}".strip()
                or "Unknown"
            )
            summary["work_post"] = bio.get("work_post", "")
            summary["work_place"] = bio.get("work_place", "")

            # Cohort grouping fields
            summary["post_type"] = bio.get("post_type", "")
            summary["declaration_year"] = bio.get("declaration_year") or raw.get("declaration_year")

            # Cash ratio for cohort stats (if applicable)
            total_inc = summary.get("total_income")
            total_ast = summary.get("total_assets")
            summary["_income_float"] = float(Decimal(total_inc)) if total_inc else None
            summary["_assets_float"] = float(Decimal(total_ast)) if total_ast else None
            summary["_cash_ratio"] = cash_stats.cash_ratio

            results.append(summary)
        except Exception:
            logger.exception("  Failed to process %s", f.name)

    # ── Pass 2: Layer 2 cohort scoring (optional) ────────────────────────
    if args.layer2:
        from app.scoring.cohorts import (
            build_cohort_distributions,
            CohortKey,
            score_declaration_l2,
        )

        # Build cohort distributions from all processed summaries
        cohort_summaries = [
            {
                "post_type": r.get("post_type"),
                "declaration_year": r.get("declaration_year"),
                "total_income": r["_income_float"],
                "total_assets": r["_assets_float"],
                "cash_ratio": r.get("_cash_ratio"),
            }
            for r in results
        ]
        distributions = build_cohort_distributions(cohort_summaries)

        # Score each declaration against its cohort
        l2_hit_count = 0
        for r in results:
            pt = r.get("post_type")
            yr = r.get("declaration_year")
            if pt and yr:
                key = CohortKey(post_type=str(pt), year=int(yr))
                cohort = distributions.get(key)
            else:
                cohort = None

            l2_results = score_declaration_l2(
                total_income=r["_income_float"],
                total_assets=r["_assets_float"],
                cohort=cohort,
            )

            # Merge L2 into L1 results
            l2_triggered = [lr for lr in l2_results if lr.triggered]
            if l2_triggered:
                l2_hit_count += 1
                l2_score = sum(lr.score for lr in l2_triggered)
                r["score"] = min(100.0, round(r["score"] + l2_score * 3.0, 2))
                r["triggered_rules"].extend(lr.rule_name for lr in l2_triggered)
                existing = r.get("explanation", "")
                l2_lines = "\n".join(f"• {lr.explanation}" for lr in l2_triggered)
                r["explanation"] = f"{existing}\n{l2_lines}".strip()

        logger.info(
            "Layer 2: %d cohorts built, %d declarations received L2 flags.",
            len(distributions), l2_hit_count,
        )

    # ── Sort and display ─────────────────────────────────────────────────
    results.sort(key=lambda r: r["score"], reverse=True)

    if args.top > 0:
        results = results[: args.top]

    logger.info("")
    logger.info("%-14s %-30s %8s  %s", "ID", "NAME", "SCORE", "FLAGS")
    logger.info("-" * 80)
    for r in results:
        flags = ", ".join(r["triggered_rules"]) if r["triggered_rules"] else "—"
        logger.info(
            "%-14s %-30s %8.1f  %s",
            str(r["declaration_id"])[:14],
            r["name"][:30],
            r["score"],
            flags,
        )

    logger.info("")
    logger.info(
        "Total: %d declarations, %d flagged.",
        len(results),
        sum(1 for r in results if r["score"] > 0),
    )

    # CSV export
    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "declaration_id", "name", "work_post", "work_place",
            "total_income", "total_assets", "score",
            "triggered_rules", "explanation",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                row = dict(r)
                row["triggered_rules"] = ", ".join(r.get("triggered_rules") or [])
                writer.writerow(row)
        logger.info("CSV written to %s (%d rows)", csv_path, len(results))


if __name__ == "__main__":
    main()
