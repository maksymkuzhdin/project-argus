#!/usr/bin/env python3
"""
Project Argus — Populate PostgreSQL from raw JSON declarations.

Reads raw declarations, runs the full pipeline (sanitize → parse → score),
and writes all normalized rows into the database.

Usage:
    python scripts/run_persist.py [--year 2023] [--limit 50]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.db.session import SessionLocal
from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.services.persist import persist_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("argus.persist")


def main() -> None:
    parser = argparse.ArgumentParser(description="Argus — Persist to DB")
    parser.add_argument("--year", type=str, default=None, help="Filter by year")
    parser.add_argument("--limit", type=int, default=None, help="Max declarations")
    parser.add_argument(
        "--data-dir", type=str, default=settings.raw_data_dir, help="Raw data dir"
    )
    parser.add_argument(
        "--batch-size", type=int, default=50, help="Commit every N declarations"
    )
    args = parser.parse_args()

    raw_dir = Path(args.data_dir)
    files = iter_raw_declarations(raw_dir, year=args.year)

    if args.limit:
        files = files[: args.limit]

    if not files:
        logger.warning("No raw declarations found in %s", raw_dir)
        return

    logger.info("Persisting %d declarations from %s", len(files), raw_dir)

    db = SessionLocal()
    total_persisted = 0
    try:
        # Process in batches
        for i in range(0, len(files), args.batch_size):
            batch_files = files[i : i + args.batch_size]
            raws = [load_declaration(f) for f in batch_files]
            count = persist_batch(db, raws)
            total_persisted += count
            logger.info(
                "  Batch %d–%d: %d/%d persisted",
                i + 1,
                min(i + args.batch_size, len(files)),
                count,
                len(batch_files),
            )
    finally:
        db.close()

    print(f"\nDone: {total_persisted}/{len(files)} declarations written to database.")


if __name__ == "__main__":
    main()
