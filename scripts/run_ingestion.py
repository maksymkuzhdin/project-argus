#!/usr/bin/env python3
"""
Project Argus — Bulk Ingestion CLI.

Fetches declarations from the NAZK public API, writes raw JSON to
data/raw/{year}/declaration_{id}.json, and supports large-scale crawls
(50,000+ declarations) with resumability, stratified category crawling,
and progress reporting.

Usage examples:
    # Basic run — uniform strategy, all years, up to 5 pages per category
    python scripts/run_ingestion.py

    # Targeted strategy, 2024 declarations only, 50 pages per category
    python scripts/run_ingestion.py --year 2024 --strategy targeted --max-pages 50

    # Preview crawl plan without fetching anything
    python scripts/run_ingestion.py --strategy targeted --dry-run

    # Resume an interrupted run
    python scripts/run_ingestion.py --resume

Preserved CLI arguments (backward compatible):
    --year, --max-pages, --concurrency, --resume, --state-file,
    --start-page, --page-delay, --max-docs

New CLI arguments:
    --strategy {uniform,targeted}   Crawl strategy (default: uniform)
    --rate-limit FLOAT              Max requests per second (default: 3)
    --checkpoint-file PATH          Checkpoint file (default: data/checkpoints/ingestion_checkpoint.json)
    --dry-run                       Print crawl plan and exit without fetching
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap — ensure backend package is importable regardless of CWD
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.ingestion.client import NazkClient
from app.ingestion.crawl_state import CrawlState, load_state, new_state, save_state
from app.ingestion.save_raw import declaration_exists, save_declaration

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("argus.ingestion")

# ---------------------------------------------------------------------------
# NAZK post_category taxonomy
# Value → (label, risk_tier)  where risk_tier: 1=high, 2=medium, 3=low
# These integer codes come directly from the NAZK API.
# ---------------------------------------------------------------------------
POST_CATEGORIES: dict[int, tuple[str, int]] = {
    1:  ("National officials (President/PM/Cabinet)",   1),
    2:  ("Parliament members (Verkhovna Rada)",          1),
    3:  ("Judges (Supreme & appellate courts)",          1),
    4:  ("Prosecutors & senior law enforcement",         1),
    5:  ("Regional officials (oblast/raion heads)",      2),
    6:  ("Local officials (city/village mayors)",        2),
    7:  ("State enterprise executives",                  2),
    8:  ("National bank & financial regulators",         1),
    9:  ("Military & security service leaders",          1),
    10: ("Other public officials",                       3),
    0:  ("Uncategorised / legacy records",               3),
}

# Strategies define ordered category priorities
STRATEGY_CATEGORIES: dict[str, list[int]] = {
    # uniform: iterate all categories with equal page budget
    "uniform": list(POST_CATEGORIES.keys()),
    # targeted: high-risk first (tier 1), then medium (tier 2), then low/other last
    "targeted": (
        [cat for cat, (_, tier) in POST_CATEGORIES.items() if tier == 1]
        + [cat for cat, (_, tier) in POST_CATEGORIES.items() if tier == 2]
        + [cat for cat, (_, tier) in POST_CATEGORIES.items() if tier == 3]
    ),
}

# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------
_DEFAULT_CHECKPOINT = Path("data/checkpoints/ingestion_checkpoint.json")
_CHECKPOINT_INTERVAL = 100   # write checkpoint every N successful fetches
_PROGRESS_INTERVAL = 500     # print progress summary every N declarations


def _load_checkpoint(path: Path) -> dict | None:
    """Load checkpoint file, or None if absent / corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load checkpoint (%s): %s — starting fresh.", path, exc)
        return None


def _save_checkpoint(path: Path, checkpoint: dict) -> None:
    """Write checkpoint atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.debug("Checkpoint written: %s", path)


def _delete_checkpoint(path: Path) -> None:
    if path.exists():
        path.unlink()
        logger.info("Checkpoint deleted (clean completion): %s", path)


def _build_checkpoint(
    category: int,
    page: int,
    fetched_ids: set[str],
    counters: dict,
) -> dict:
    return {
        "version": 2,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "last_category": category,
        "last_page": page,
        "fetched_ids": sorted(fetched_ids),
        "total_fetched": counters["fetched"],
        "total_skipped": counters["skipped"],
        "total_failed":  counters["failed"],
    }


# ---------------------------------------------------------------------------
# Dry-run plan printing
# ---------------------------------------------------------------------------

def print_crawl_plan(
    categories: list[int],
    max_pages: int,
    year: int | None,
    rate_limit: float,
    concurrency: int,
) -> None:
    """Print a human-readable crawl plan and exit."""
    page_size = 100          # NAZK returns up to 100 items per page
    estimated_per_cat = max_pages * page_size
    total_estimated = estimated_per_cat * len(categories)
    estimated_calls  = max_pages * len(categories) + total_estimated  # pages + individual docs
    if rate_limit > 0:
        estimated_seconds = math.ceil(estimated_calls / rate_limit)
        eta_str = f"~{estimated_seconds // 3600}h {(estimated_seconds % 3600) // 60}m"
    else:
        eta_str = "unlimited rate"

    print("\n" + "=" * 65)
    print("  Project Argus — Bulk Ingestion Crawl Plan (DRY RUN)")
    print("=" * 65)
    print(f"  Year filter      : {year or 'all years'}")
    print(f"  Max pages / cat  : {max_pages}")
    print(f"  Page size        : {page_size} (NAZK API max)")
    print(f"  Concurrency      : {concurrency} concurrent requests")
    print(f"  Rate limit       : {rate_limit} req/s")
    print(f"  Categories       : {len(categories)}")
    print(f"  Est. declarations: {total_estimated:,}")
    print(f"  Est. API calls   : {estimated_calls:,}")
    print(f"  Est. wall-clock  : {eta_str}")
    print()
    print(f"  {'Cat':>4}  {'Label':<48}  {'Tier':>4}  {'Est. docs':>10}  {'Pages':>6}")
    print("  " + "-" * 80)
    for cat in categories:
        label, tier = POST_CATEGORIES.get(cat, (f"Unknown ({cat})", 9))
        tier_label = {1: "HIGH", 2: "MED", 3: "LOW"}.get(tier, "?")
        print(f"  {cat:>4}  {label:<48}  {tier_label:>4}  {estimated_per_cat:>10,}  {max_pages:>6}")
    print("=" * 65 + "\n")


# ---------------------------------------------------------------------------
# Rate limiter — simple token bucket
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token-bucket rate limiter (requests per second)."""

    def __init__(self, rate: float) -> None:
        self._rate = max(rate, 0.0)
        self._min_interval = (1.0 / rate) if rate > 0 else 0.0
        self._last_call = 0.0

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_call
        wait = self._min_interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = asyncio.get_event_loop().time()


# ---------------------------------------------------------------------------
# Fetch helpers with exponential backoff for 429 / 503
# ---------------------------------------------------------------------------

async def _fetch_page_with_backoff(
    client: NazkClient,
    *,
    year: int | None,
    post_category: int | None,
    page: int,
    max_retries: int = 5,
) -> dict | None:
    """Fetch a search-results page, retrying on 429/503 with 2^attempt backoff."""
    import httpx

    url = f"{client.base_url}/documents/list"
    params: dict[str, Any] = {"page": page}
    if year is not None:
        params["declaration_year"] = year
    if post_category is not None:
        params["post_category"] = post_category

    for attempt in range(max_retries):
        try:
            return await client._get(url, params=params)
        except Exception as exc:
            # Detect rate-limit / server errors from the exception message
            exc_str = str(exc)
            is_retryable = "429" in exc_str or "503" in exc_str or "rate" in exc_str.lower()
            if is_retryable and attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "Rate-limited / server error on page %d (attempt %d/%d): %s — backoff %.0fs",
                    page, attempt + 1, max_retries, exc, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error("Failed to fetch page %d after %d attempts: %s", page, attempt + 1, exc)
                return None
    return None


async def _fetch_declaration_with_backoff(
    client: NazkClient,
    doc_id: str,
    *,
    max_retries: int = 5,
) -> dict | None:
    """Fetch a single declaration, retrying on 429/503 with 2^attempt backoff."""
    for attempt in range(max_retries):
        try:
            return await client.fetch_declaration(doc_id)
        except Exception as exc:
            exc_str = str(exc)
            is_retryable = "429" in exc_str or "503" in exc_str or "rate" in exc_str.lower()
            if is_retryable and attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(
                    "Rate-limited on %s (attempt %d/%d): %s — backoff %.0fs",
                    doc_id, attempt + 1, max_retries, exc, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error("Failed to fetch %s after %d attempts: %s", doc_id, attempt + 1, exc)
                return None
    return None


# ---------------------------------------------------------------------------
# Progress reporter
# ---------------------------------------------------------------------------

def _eta_str(start_ts: float, total_done: int, total_skipped: int) -> str:
    """Return rough ETA string based on current throughput."""
    elapsed = time.monotonic() - start_ts
    total_processed = total_done + total_skipped
    if total_processed == 0 or elapsed < 1:
        return "calculating..."
    rate = total_processed / elapsed
    # We don't know the total target upfront, so just report throughput
    return f"{rate:.1f} decl/s ({elapsed:.0f}s elapsed)"


def _print_progress(
    counters: dict,
    start_ts: float,
    category: int | None,
    page: int,
) -> None:
    cat_label = POST_CATEGORIES.get(category, (f"cat={category}", 0))[0] if category is not None else "all"
    eta = _eta_str(start_ts, counters["fetched"], counters["skipped"])
    logger.info(
        "[PROGRESS] fetched=%d skipped=%d failed=%d | category=%s page=%d | throughput %s",
        counters["fetched"],
        counters["skipped"],
        counters["failed"],
        cat_label,
        page,
        eta,
    )


# ---------------------------------------------------------------------------
# Core crawl routine for one category
# ---------------------------------------------------------------------------

async def crawl_category(
    client: NazkClient,
    *,
    category: int,
    year: int | None,
    start_page: int,
    max_pages: int,
    page_delay: float,
    rate_limiter: RateLimiter,
    raw_dir: Path,
    fetched_ids: set[str],   # mutated in-place
    counters: dict,           # mutated in-place: fetched, skipped, failed
    max_docs: int,
    start_ts: float,
    checkpoint_path: Path,
    state: CrawlState,
    state_file: Path,
) -> int:
    """Crawl all pages for a single post_category.

    Returns the last page successfully fetched (for checkpoint purposes).
    """
    last_page = start_page - 1
    checkpoint_since_last = 0

    for page in range(start_page, start_page + max_pages):
        await rate_limiter.acquire()

        logger.info("Fetching category=%d page=%d (year=%s)", category, page, year)
        response = await _fetch_page_with_backoff(
            client,
            year=year,
            post_category=category,
            page=page,
        )

        if response is None:
            state.add_error(f"page:{category}:{page}:fetch_failed")
            save_state(state, path=state_file)
            last_page = page
            continue

        items = response.get("items", response.get("data", []))
        if not items:
            logger.info("No more results at category=%d page=%d — moving on.", category, page)
            last_page = page
            break

        # Build batch of doc IDs on this page, skipping already-fetched ones
        to_fetch: list[tuple[str, dict]] = []
        for summary in items:
            doc_id = summary.get("id", summary.get("doc_id"))
            if not doc_id:
                continue
            doc_id = str(doc_id)

            # Idempotency: skip if already in checkpoint set or on disk
            if doc_id in fetched_ids:
                counters["skipped"] += 1
                continue
            year_hint = summary.get("declaration_year")
            if year_hint is not None and declaration_exists(doc_id, str(year_hint), base_dir=raw_dir):
                counters["skipped"] += 1
                fetched_ids.add(doc_id)
                continue

            to_fetch.append((doc_id, summary))

        # Fetch individual declarations concurrently (semaphore is inside client)
        async def _fetch_one(doc_id: str, summary: dict) -> None:
            nonlocal checkpoint_since_last
            await rate_limiter.acquire()
            full_doc = await _fetch_declaration_with_backoff(client, doc_id)
            if full_doc is None:
                counters["failed"] += 1
                state.add_error(f"fetch:{doc_id}:all_retries_failed")
                return

            # Write raw JSON to data/raw/{year}/{id}.json
            save_declaration(full_doc, base_dir=raw_dir)
            fetched_ids.add(doc_id)
            counters["fetched"] += 1
            checkpoint_since_last += 1

            # Progress every 500
            total = counters["fetched"] + counters["skipped"]
            if total % _PROGRESS_INTERVAL == 0:
                _print_progress(counters, start_ts, category, page)

            # Checkpoint every 100 successful fetches
            if checkpoint_since_last >= _CHECKPOINT_INTERVAL:
                checkpoint_since_last = 0
                cp = _build_checkpoint(category, page, fetched_ids, counters)
                _save_checkpoint(checkpoint_path, cp)

        # Run fetch tasks concurrently; the client semaphore caps parallelism
        tasks = [_fetch_one(did, summ) for did, summ in to_fetch]
        await asyncio.gather(*tasks)

        last_page = page

        # Legacy crawl-state tracking (backward-compatible)
        state.mark_page(page=page, fetched=len(to_fetch), saved=counters["fetched"], skipped=counters["skipped"])
        save_state(state, path=state_file)
        logger.info(state.summary)

        # --max-docs guard
        if max_docs > 0 and counters["fetched"] >= max_docs:
            logger.info("Reached --max-docs=%d limit, stopping.", max_docs)
            return last_page

        if len(items) < 100:
            logger.info("Partial page at category=%d page=%d (got %d) — end of category.", category, page, len(items))
            break

        if page_delay > 0:
            await asyncio.sleep(page_delay)

    return last_page


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------

async def run(
    year: int | None,
    max_pages: int,
    concurrency: int,
    resume: bool,
    state_file: Path,
    start_page: int,
    page_delay: float,
    max_docs: int,
    strategy: str,
    rate_limit: float,
    checkpoint_path: Path,
    dry_run: bool,
) -> None:
    raw_dir = Path(settings.raw_data_dir)
    categories = STRATEGY_CATEGORIES.get(strategy, STRATEGY_CATEGORIES["uniform"])

    # ------------------------------------------------------------------
    # Dry run — print plan and exit
    # ------------------------------------------------------------------
    if dry_run:
        print_crawl_plan(
            categories=categories,
            max_pages=max_pages,
            year=year,
            rate_limit=rate_limit,
            concurrency=concurrency,
        )
        return

    # ------------------------------------------------------------------
    # Checkpoint resume
    # ------------------------------------------------------------------
    fetched_ids: set[str] = set()
    counters = {"fetched": 0, "skipped": 0, "failed": 0}
    resume_category: int | None = None
    resume_page: int = start_page

    checkpoint = _load_checkpoint(checkpoint_path) if resume else None
    if checkpoint:
        fetched_ids = set(checkpoint.get("fetched_ids", []))
        counters["fetched"]  = checkpoint.get("total_fetched", 0)
        counters["skipped"]  = checkpoint.get("total_skipped", 0)
        counters["failed"]   = checkpoint.get("total_failed",  0)
        resume_category      = checkpoint.get("last_category")
        resume_page          = checkpoint.get("last_page", start_page) + 1
        logger.info(
            "Resuming from checkpoint: category=%s page=%d "
            "(%d already fetched, %d already skipped)",
            resume_category, resume_page,
            counters["fetched"], counters["skipped"],
        )

    # ------------------------------------------------------------------
    # Legacy crawl-state (backward-compatible with --state-file)
    # ------------------------------------------------------------------
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
            logger.info("Legacy state: resuming from page %d", state.last_page + 1)
        else:
            state = new_state(year=year)
    else:
        state = new_state(year=year)

    save_state(state, path=state_file)

    rate_limiter = RateLimiter(rate_limit)
    start_ts = time.monotonic()

    async with NazkClient(
        base_url=settings.nazk_api_base_url,
        concurrency=concurrency,
        max_retries=settings.nazk_retry_attempts,
        timeout=settings.nazk_timeout_seconds,
    ) as client:
        # Determine where to start in the category list
        cat_start_idx = 0
        if resume_category is not None and resume_category in categories:
            cat_start_idx = categories.index(resume_category)
            logger.info(
                "Resuming category loop at index %d (category=%d)",
                cat_start_idx, resume_category,
            )

        for cat_idx, category in enumerate(categories):
            if cat_idx < cat_start_idx:
                logger.debug("Skipping category %d (already completed in prior run)", category)
                continue

            # When resuming mid-category, start from saved page; otherwise page 1
            cat_start_page = resume_page if (cat_idx == cat_start_idx and resume_category == category) else start_page

            label, tier = POST_CATEGORIES.get(category, (f"cat={category}", 9))
            tier_str = {1: "HIGH", 2: "MED", 3: "LOW"}.get(tier, "?")
            logger.info(
                "=== Category %d: %s [%s] — starting at page %d ===",
                category, label, tier_str, cat_start_page,
            )

            last_page = await crawl_category(
                client,
                category=category,
                year=year,
                start_page=cat_start_page,
                max_pages=max_pages,
                page_delay=page_delay,
                rate_limiter=rate_limiter,
                raw_dir=raw_dir,
                fetched_ids=fetched_ids,
                counters=counters,
                max_docs=max_docs,
                start_ts=start_ts,
                checkpoint_path=checkpoint_path,
                state=state,
                state_file=state_file,
            )

            # Save checkpoint after each category completes
            cp = _build_checkpoint(category, last_page, fetched_ids, counters)
            _save_checkpoint(checkpoint_path, cp)

            # Reset resume page for subsequent categories
            resume_page = start_page
            resume_category = None

            if max_docs > 0 and counters["fetched"] >= max_docs:
                logger.info("--max-docs=%d reached; halting crawl.", max_docs)
                break

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    elapsed = time.monotonic() - start_ts
    state.mark_completed()
    save_state(state, path=state_file)

    logger.info(
        "Ingestion complete. fetched=%d skipped=%d failed=%d elapsed=%.0fs",
        counters["fetched"], counters["skipped"], counters["failed"], elapsed,
    )

    # Clean checkpoint on clean completion
    _delete_checkpoint(checkpoint_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Argus — Bulk Declaration Ingestion",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Preserved arguments (backward-compatible) ─────────────────────────
    parser.add_argument("--year",        type=int,   default=None,
                        help="Filter by declaration year (None = all years)")
    parser.add_argument("--max-pages",   type=int,   default=5,
                        help="Max pages to fetch per category")
    parser.add_argument("--concurrency", type=int,   default=settings.nazk_concurrency,
                        help="Max concurrent HTTP requests (semaphore cap)")
    parser.add_argument("--resume",      action="store_true",
                        help="Resume from checkpoint and crawl state if available")
    parser.add_argument("--state-file",  type=Path,  default=Path("data/crawl_state.json"),
                        help="Path to legacy crawl-state JSON")
    parser.add_argument("--start-page",  type=int,   default=1,
                        help="Starting page for non-resume runs")
    parser.add_argument("--page-delay",  type=float, default=settings.nazk_page_delay_seconds,
                        help="Additional delay (seconds) between page fetches")
    parser.add_argument("--max-docs",    type=int,   default=0,
                        help="Stop after saving this many new declarations (0 = unlimited)")

    # ── New arguments ──────────────────────────────────────────────────────
    parser.add_argument(
        "--strategy",
        choices=["uniform", "targeted"],
        default="uniform",
        help=(
            "Crawl strategy: "
            "'uniform' splits budget equally across all post_category values; "
            "'targeted' prioritises high-risk categories (national/regional officials) first."
        ),
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=3.0,
        metavar="RPS",
        help="Maximum requests per second (token-bucket rate limiter, 0 = unlimited)",
    )
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=_DEFAULT_CHECKPOINT,
        help="Path to the resumable checkpoint JSON file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the crawl plan (categories, estimated counts, depth) without fetching",
    )

    args = parser.parse_args()

    asyncio.run(
        run(
            year=args.year,
            max_pages=args.max_pages,
            concurrency=args.concurrency,
            resume=args.resume,
            state_file=args.state_file,
            start_page=args.start_page,
            page_delay=args.page_delay,
            max_docs=args.max_docs,
            strategy=args.strategy,
            rate_limit=args.rate_limit,
            checkpoint_path=args.checkpoint_file,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
