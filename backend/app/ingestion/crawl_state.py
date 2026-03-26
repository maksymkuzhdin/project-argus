"""
Project Argus — Crawl state tracking.

Simple JSON-file-based state so ingestion can resume after interruption.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_STATE_FILE = Path("data/crawl_state.json")


@dataclass
class CrawlState:
    """Tracks progress of a crawl session."""

    year: int | None = None
    last_page: int = 0
    total_fetched: int = 0
    total_saved: int = 0
    total_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    completed: bool = False

    def mark_page(self, page: int, fetched: int, saved: int, skipped: int) -> None:
        """Update state after processing a page."""
        self.last_page = page
        self.total_fetched += fetched
        self.total_saved += saved
        self.total_skipped += skipped
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_completed(self) -> None:
        self.completed = True
        self.updated_at = datetime.now(timezone.utc).isoformat()

    @property
    def summary(self) -> str:
        return (
            f"Crawl state: year={self.year} pages={self.last_page} "
            f"fetched={self.total_fetched} saved={self.total_saved} "
            f"skipped={self.total_skipped} errors={len(self.errors)} "
            f"completed={self.completed}"
        )


def save_state(
    state: CrawlState,
    path: Path = _DEFAULT_STATE_FILE,
) -> None:
    """Persist crawl state to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.debug("Saved crawl state: %s", path)


def load_state(path: Path = _DEFAULT_STATE_FILE) -> CrawlState | None:
    """Load crawl state from disk, or return None if not found."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return CrawlState(**data)


def new_state(year: int | None = None) -> CrawlState:
    """Create a fresh crawl state."""
    return CrawlState(
        year=year,
        started_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
