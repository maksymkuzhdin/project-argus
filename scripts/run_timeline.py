#!/usr/bin/env python3
"""
Project Argus — Multi-year timeline scoring report.

Loads raw declarations across all available years, groups them by person
(user_declarant_id), builds PersonTimelines, runs temporal scoring rules,
and prints a ranked summary of persons with the highest anomaly signals.

Only persons with declarations in 2+ years are scored.

Usage:
    python scripts/run_timeline.py [--data-dir PATH] [--top N] [--min-score F]
    python scripts/run_timeline.py --data-dir data/raw --top 25
    python scripts/run_timeline.py --top 10 --min-score 0.2
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.normalization.assemble_timeline import assemble_timelines_from_raw
from app.scoring.rules import score_timeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def _fmt(val: Decimal | float | None, decimals: int = 0) -> str:
    if val is None:
        return "—"
    return f"{float(val):,.{decimals}f}"


def main() -> None:
    # Fix Windows console encoding for Cyrillic output
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Argus — Multi-year timeline anomaly report."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/raw"),
        help="Root directory containing raw declaration JSON files (default: data/raw).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Show only the top N persons by timeline score (0 = show all).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Only show persons with timeline score >= this value.",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Load ALL raw declarations (every year subdirectory)
    # ------------------------------------------------------------------
    raw_dir = Path(args.data_dir)
    if not raw_dir.exists():
        logger.error("Data directory not found: %s", raw_dir)
        sys.exit(1)

    # iter_raw_declarations with year=None returns all files across all years
    files = iter_raw_declarations(raw_dir, year=None)
    if not files:
        logger.warning("No raw declaration files found in %s", raw_dir)
        return

    logger.info("Loading %d raw declaration files from %s …", len(files), raw_dir)

    raws: list[dict] = []
    failed = 0
    for f in files:
        try:
            raws.append(load_declaration(f))
        except Exception:
            logger.debug("  Failed to load %s", f.name)
            failed += 1

    logger.info(
        "Loaded %d declarations (%d failed).", len(raws), failed
    )

    # ------------------------------------------------------------------
    # 2. Build timelines (groups 2+ declarations per person)
    # ------------------------------------------------------------------
    logger.info("Assembling multi-year timelines …")
    timelines = assemble_timelines_from_raw(raws)

    logger.info(
        "Found %d persons with declarations in 2+ years.", len(timelines)
    )

    if not timelines:
        logger.warning(
            "No multi-year persons found. Make sure data/raw contains "
            "multiple year subdirectories (e.g. 2023/, 2024/)."
        )
        return

    # ------------------------------------------------------------------
    # 3. Score each timeline
    # ------------------------------------------------------------------
    scored: list[tuple[float, object, object]] = []  # (score, timeline, result)
    for tl in timelines.values():
        result = score_timeline(tl)
        if result.total_score >= args.min_score:
            scored.append((result.total_score, tl, result))

    scored.sort(key=lambda x: x[0], reverse=True)

    if args.top > 0:
        scored = scored[: args.top]

    # ------------------------------------------------------------------
    # 4. Print report
    # ------------------------------------------------------------------
    years_in_corpus = sorted(
        {s.declaration_year for tl in timelines.values() for s in tl.snapshots}
    )
    year_range = f"{min(years_in_corpus)}–{max(years_in_corpus)}" if years_in_corpus else "?"

    print()
    print(f"  Project Argus — Multi-Year Timeline Anomaly Report")
    print(f"  Corpus: {len(raws)} declarations | {year_range}")
    print(f"  Multi-year persons: {len(timelines)} | Min score filter: {args.min_score:.2f}")
    print(f"  Showing: top {args.top if args.top > 0 else 'all'} results")
    print()

    col_id   = 10
    col_name = 28
    col_yrs  = 8
    col_sc   = 7
    col_inc  = 14
    col_mon  = 14
    col_flags = 30

    hdr = (
        f"{'UID':<{col_id}} "
        f"{'NAME':<{col_name}} "
        f"{'YEARS':<{col_yrs}} "
        f"{'SCORE':>{col_sc}} "
        f"{'INCOME RATIO':>{col_inc}} "
        f"{'ASSET RATIO':>{col_mon}} "
        f"{'FLAGS'}"
    )
    print(hdr)
    print("-" * (col_id + col_name + col_yrs + col_sc + col_inc + col_mon + col_flags + 6))

    for score, tl, result in scored:
        years_covered = ",".join(
            str(s.declaration_year) for s in sorted(tl.snapshots, key=lambda s: s.declaration_year)
        )
        flags = ", ".join(result.triggered_rules) if result.triggered_rules else "—"

        income_ratio = (
            f"{tl.max_income_ratio:.2f}x" if tl.max_income_ratio is not None else "—"
        )
        monetary_ratio = (
            f"{tl.max_monetary_ratio:.2f}x" if tl.max_monetary_ratio is not None else "—"
        )

        print(
            f"{str(tl.user_declarant_id):<{col_id}} "
            f"{tl.name[:col_name]:<{col_name}} "
            f"{years_covered[:col_yrs]:<{col_yrs}} "
            f"{score:>{col_sc}.3f} "
            f"{income_ratio:>{col_inc}} "
            f"{monetary_ratio:>{col_mon}} "
            f"{flags}"
        )

    print()
    print(
        f"Totals: {len(scored)} persons shown | "
        f"{sum(1 for s, _, _ in scored if s > 0)} with score > 0 | "
        f"{sum(1 for _, _, r in scored if r.triggered_rules)} with triggered rules"
    )
    print()

    # ------------------------------------------------------------------
    # 5. Detail section for top 5 (with explanation bullets)
    # ------------------------------------------------------------------
    top_detail = scored[:5]
    if top_detail:
        print("  — Top 5 Detail —")
        print()
        for score, tl, result in top_detail:
            years = [str(s.declaration_year) for s in sorted(tl.snapshots, key=lambda s: s.declaration_year)]
            print(f"  [{tl.user_declarant_id}] {tl.name}  |  years: {', '.join(years)}  |  score: {score:.3f}")
            for line in result.explanation_summary.split("\n"):
                print(f"    {line}")
            # Show year-over-year changes
            for ch in tl.changes:
                inc_str = (
                    f"{_fmt(ch.income_prev)} → {_fmt(ch.income_curr)}"
                    if ch.income_prev is not None or ch.income_curr is not None
                    else "n/a"
                )
                mon_str = (
                    f"{_fmt(ch.monetary_prev)} → {_fmt(ch.monetary_curr)}"
                    if ch.monetary_prev is not None or ch.monetary_curr is not None
                    else "n/a"
                )
                print(
                    f"    {ch.from_year}→{ch.to_year}:  "
                    f"income {inc_str}  |  assets {mon_str}"
                )
            print()


if __name__ == "__main__":
    main()
