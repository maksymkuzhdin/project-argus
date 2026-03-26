#!/usr/bin/env python3
"""
Project Argus — Ingestion CLI.

Fetches declarations from the NAZK public API and saves them as raw JSON.

Usage:
    python scripts/run_ingestion.py --year 2023 --max-pages 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.ingestion.client import NazkClient
from app.ingestion.crawl_state import CrawlState, load_state, new_state, save_state
from app.ingestion.save_raw import declaration_exists, save_declaration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("argus.ingestion")


async def run(
    year: int | None,
    max_pages: int,
    concurrency: int,
    resume: bool,
    state_file: Path,
    start_page: int,
    page_delay: float,
    max_docs: int,
) -> None:
    raw_dir = Path(settings.raw_data_dir)

    state: CrawlState
    if resume:
        existing = load_state(state_file)
        if existing is not None and existing.completed:
            logger.info("State already marked completed; starting a fresh crawl state.")
            existing = None

        if existing is not None:
            if year is not None and existing.year not in (None, year):
                raise ValueError(
                    f"Cannot resume: state year={existing.year} does not match requested year={year}"
                )
            state = existing
            if state.year is None:
                state.year = year
            logger.info("Resuming from page %d", state.last_page + 1)
        else:
            state = new_state(year=year)
    else:
        state = new_state(year=year)

    save_state(state, path=state_file)

    start_from = max(start_page, state.last_page + 1 if resume else start_page)

    async with NazkClient(
        base_url=settings.nazk_api_base_url,
        concurrency=concurrency,
        max_retries=settings.nazk_retry_attempts,
        timeout=settings.nazk_timeout_seconds,
    ) as client:
        for page in range(start_from, start_from + max_pages):
            logger.info("Fetching page %d (year=%s)", page, year)
            try:
                response = await client.search_declarations(
                    declaration_year=year,
                    page=page,
                )
            except Exception as exc:
                logger.error("Failed to fetch page %d: %s", page, exc)
                state.add_error(f"page:{page}:{exc}")
                save_state(state, path=state_file)
                continue

            items = response.get("items", response.get("data", []))
            if not items:
                logger.info("No more results at page %d, stopping.", page)
                state.mark_completed()
                save_state(state, path=state_file)
                break

            fetched_page = 0
            saved_page = 0
            skipped_page = 0

            for summary in items:
                doc_id = summary.get("id", summary.get("doc_id"))
                if not doc_id:
                    continue

                doc_id = str(doc_id)
                year_hint = summary.get("declaration_year")
                if year_hint is not None and declaration_exists(doc_id, str(year_hint), base_dir=raw_dir):
                    skipped_page += 1
                    continue

                fetched_page += 1
                try:
                    full_doc = await client.fetch_declaration(doc_id)
                except Exception as exc:
                    logger.error("Failed to fetch %s: %s", doc_id, exc)
                    state.add_error(f"fetch:{doc_id}:{exc}")
                    continue

                file_exists_before = declaration_exists(
                    doc_id,
                    str(full_doc.get("declaration_year", year_hint or "unknown")),
                    base_dir=raw_dir,
                )
                save_declaration(full_doc, base_dir=raw_dir)
                if file_exists_before:
                    skipped_page += 1
                else:
                    saved_page += 1

                if max_docs > 0 and (state.total_saved + saved_page) >= max_docs:
                    logger.info("Reached --max-docs=%d limit, stopping early.", max_docs)
                    state.mark_page(
                        page=page,
                        fetched=fetched_page,
                        saved=saved_page,
                        skipped=skipped_page,
                    )
                    save_state(state, path=state_file)
                    logger.info(state.summary)
                    return

            state.mark_page(
                page=page,
                fetched=fetched_page,
                saved=saved_page,
                skipped=skipped_page,
            )
            save_state(state, path=state_file)
            logger.info(state.summary)

            if len(items) < 100:
                state.mark_completed()
                save_state(state, path=state_file)
                break

            if page_delay > 0:
                await asyncio.sleep(page_delay)

    save_state(state, path=state_file)
    logger.info("Done. %s", state.summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Argus — Ingest declarations")
    parser.add_argument("--year", type=int, default=None, help="Declaration year")
    parser.add_argument("--max-pages", type=int, default=5, help="Max pages to fetch (default 5)")
    parser.add_argument("--concurrency", type=int, default=settings.nazk_concurrency, help="Concurrent requests")
    parser.add_argument("--resume", action="store_true", help="Resume from crawl state if available")
    parser.add_argument("--state-file", type=Path, default=Path("data/crawl_state.json"), help="Path to crawl-state JSON")
    parser.add_argument("--start-page", type=int, default=1, help="Start page for non-resume runs")
    parser.add_argument("--page-delay", type=float, default=settings.nazk_page_delay_seconds, help="Delay in seconds between pages")
    parser.add_argument("--max-docs", type=int, default=0, help="Stop after saving this many new documents (0 = no limit)")
    args = parser.parse_args()

    asyncio.run(
        run(
            args.year,
            args.max_pages,
            args.concurrency,
            args.resume,
            args.state_file,
            args.start_page,
            args.page_delay,
            args.max_docs,
        )
    )


if __name__ == "__main__":
    main()
