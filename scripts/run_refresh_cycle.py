#!/usr/bin/env python3
"""
Project Argus — Refresh cycle runner.

Runs a repeatable update cycle:
1) optional ingestion,
2) persistence to Postgres,
3) optional scored CSV export.

Usage examples:
    python scripts/run_refresh_cycle.py --year 2024 --skip-ingestion --csv output/scores_refresh.csv
    python scripts/run_refresh_cycle.py --year 2024 --ingest-pages 50 --resume --state-file data/crawl_state_refresh_2024.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.db.session import SessionLocal
from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.services.persist import persist_batch
from app.services.pipeline import process_declaration

import run_ingestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("argus.refresh")


def _persist(files: list[Path], batch_size: int) -> tuple[int, int]:
    db = SessionLocal()
    total_persisted = 0
    try:
        for i in range(0, len(files), batch_size):
            batch_files = files[i : i + batch_size]
            raws = [load_declaration(f) for f in batch_files]
            count = persist_batch(db, raws)
            total_persisted += count
            logger.info(
                "Persist batch %d-%d: %d/%d",
                i + 1,
                min(i + batch_size, len(files)),
                count,
                len(batch_files),
            )
    finally:
        db.close()

    return total_persisted, len(files)


def _db_available() -> bool:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("Skipping persistence phase: database unavailable (%s)", exc)
        return False
    finally:
        db.close()


def _write_csv(files: list[Path], csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "declaration_id", "name", "work_post", "work_place",
        "total_income", "total_assets", "score", "triggered_rules", "explanation",
    ]

    written = 0
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for f in files:
            raw = load_declaration(f)
            summary = process_declaration(raw)
            row = dict(summary)
            row["triggered_rules"] = ", ".join(summary.get("triggered_rules") or [])
            writer.writerow(row)
            written += 1

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Argus — Run refresh cycle")
    parser.add_argument("--year", type=int, default=None, help="Filter by declaration year")
    parser.add_argument("--data-dir", type=str, default=settings.raw_data_dir, help="Raw data directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit files for persist/export")

    parser.add_argument("--skip-ingestion", action="store_true", help="Skip ingestion phase")
    parser.add_argument("--ingest-pages", type=int, default=0, help="Pages to ingest before persistence")
    parser.add_argument("--ingest-max-docs", type=int, default=0, help="Optional max new docs during ingestion")
    parser.add_argument("--resume", action="store_true", help="Resume ingestion from state file")
    parser.add_argument("--state-file", type=Path, default=Path("data/crawl_state_refresh.json"), help="Ingestion state path")
    parser.add_argument("--concurrency", type=int, default=settings.nazk_concurrency, help="Ingestion concurrency")
    parser.add_argument("--page-delay", type=float, default=settings.nazk_page_delay_seconds, help="Delay between ingested pages")

    parser.add_argument("--persist-batch-size", type=int, default=50, help="Persistence batch size")
    parser.add_argument("--csv", type=Path, default=None, help="Optional path for scored CSV export")

    args = parser.parse_args()

    if not args.skip_ingestion and args.ingest_pages > 0:
        logger.info("Starting ingestion phase (pages=%d)", args.ingest_pages)
        asyncio.run(
            run_ingestion.run(
                year=args.year,
                max_pages=args.ingest_pages,
                concurrency=args.concurrency,
                resume=args.resume,
                state_file=args.state_file,
                start_page=1,
                page_delay=args.page_delay,
                max_docs=args.ingest_max_docs,
            )
        )
    else:
        logger.info("Skipping ingestion phase")

    files = iter_raw_declarations(Path(args.data_dir), year=str(args.year) if args.year else None)
    if args.limit:
        files = files[: args.limit]

    if not files:
        logger.warning("No raw declarations found for refresh cycle.")
        return

    if _db_available():
        logger.info("Persistence phase: %d files", len(files))
        persisted, total = _persist(files, args.persist_batch_size)
        logger.info("Persisted %d/%d declarations", persisted, total)

    if args.csv:
        logger.info("CSV export phase: %s", args.csv)
        rows = _write_csv(files, args.csv)
        logger.info("CSV rows written: %d", rows)


if __name__ == "__main__":
    main()
