"""
Project Argus — Raw declaration storage.

Saves and loads raw declaration JSON, organized by year.
Designed to be idempotent — skips files that already exist.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = Path("data/raw")


def _year_for_declaration(data: dict) -> str:
    """Extract the declaration year from a raw declaration dict."""
    year = data.get("declaration_year")
    if year:
        return str(year)
    # Fallback: try to extract from date field
    date = data.get("date")
    if date and isinstance(date, str) and len(date) >= 4:
        return date[:4]
    return "unknown"


def _id_for_declaration(data: dict) -> str:
    """Extract the declaration ID."""
    return str(data.get("id", data.get("doc_id", "unknown")))


def declaration_path(
    doc_id: str,
    year: str,
    base_dir: Path = _DEFAULT_BASE_DIR,
) -> Path:
    """Return the canonical file path for a declaration."""
    return base_dir / year / f"declaration_{doc_id}.json"


def declaration_exists(
    doc_id: str,
    year: str,
    base_dir: Path = _DEFAULT_BASE_DIR,
) -> bool:
    """Check if a raw declaration file already exists."""
    return declaration_path(doc_id, year, base_dir).exists()


def save_declaration(
    data: dict[str, Any],
    base_dir: Path = _DEFAULT_BASE_DIR,
    *,
    overwrite: bool = False,
) -> Path:
    """Save a raw declaration dict as a JSON file.

    Parameters
    ----------
    data:
        The full declaration dict from the API.
    base_dir:
        Root directory for raw storage (default: ``data/raw``).
    overwrite:
        If False (default), skip writing if the file already exists.

    Returns
    -------
    The path to the saved (or existing) file.
    """
    year = _year_for_declaration(data)
    doc_id = _id_for_declaration(data)
    path = declaration_path(doc_id, year, base_dir)

    if path.exists() and not overwrite:
        logger.debug("Already exists, skipping: %s", path)
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved: %s", path)
    return path


def load_declaration(path: Path) -> dict[str, Any]:
    """Load a raw declaration JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def iter_raw_declarations(
    base_dir: Path = _DEFAULT_BASE_DIR,
    year: str | None = None,
) -> list[Path]:
    """List all raw declaration files, optionally filtered by year.

    Returns
    -------
    Sorted list of Paths.
    """
    if year:
        search_dir = base_dir / year
    else:
        search_dir = base_dir

    if not search_dir.exists():
        return []

    # Match both `declaration_*.json` (API-saved) and `full_declaration_*.json` (examples)
    files = sorted(search_dir.rglob("*declaration_*.json"))
    return files
