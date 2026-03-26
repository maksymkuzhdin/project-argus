"""
Tests for app.ingestion.save_raw and app.ingestion.crawl_state.

NazkClient is tested via mocks — real API calls are not made.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.ingestion.save_raw import (
    declaration_exists,
    declaration_path,
    load_declaration,
    save_declaration,
    iter_raw_declarations,
)
from app.ingestion.crawl_state import CrawlState, load_state, new_state, save_state


# ── save_raw ────────────────────────────────────────────────────────────

class TestSaveRaw:
    SAMPLE = {
        "id": "abc-123",
        "declaration_year": 2023,
        "data": {"step_1": {}},
    }

    def test_save_and_load(self, tmp_path: Path):
        path = save_declaration(self.SAMPLE, base_dir=tmp_path)
        assert path.exists()
        loaded = load_declaration(path)
        assert loaded["id"] == "abc-123"

    def test_idempotent_skip(self, tmp_path: Path):
        save_declaration(self.SAMPLE, base_dir=tmp_path)
        path = save_declaration(self.SAMPLE, base_dir=tmp_path)
        assert path.exists()  # still works, no error

    def test_overwrite(self, tmp_path: Path):
        save_declaration(self.SAMPLE, base_dir=tmp_path)
        modified = {**self.SAMPLE, "extra": "data"}
        path = save_declaration(modified, base_dir=tmp_path, overwrite=True)
        loaded = load_declaration(path)
        assert loaded.get("extra") == "data"

    def test_path_by_year(self, tmp_path: Path):
        path = declaration_path("abc-123", "2023", base_dir=tmp_path)
        assert "2023" in str(path)
        assert "declaration_abc-123.json" in str(path)

    def test_exists_check(self, tmp_path: Path):
        assert not declaration_exists("abc-123", "2023", base_dir=tmp_path)
        save_declaration(self.SAMPLE, base_dir=tmp_path)
        assert declaration_exists("abc-123", "2023", base_dir=tmp_path)

    def test_iter_raw(self, tmp_path: Path):
        save_declaration(self.SAMPLE, base_dir=tmp_path)
        files = iter_raw_declarations(tmp_path)
        assert len(files) == 1

    def test_iter_raw_by_year(self, tmp_path: Path):
        save_declaration(self.SAMPLE, base_dir=tmp_path)
        files = iter_raw_declarations(tmp_path, year="2023")
        assert len(files) == 1
        files = iter_raw_declarations(tmp_path, year="2022")
        assert len(files) == 0

    def test_fallback_year_from_date(self, tmp_path: Path):
        data = {"id": "xyz", "date": "2022-01-15"}
        path = save_declaration(data, base_dir=tmp_path)
        assert "2022" in str(path)


# ── crawl_state ─────────────────────────────────────────────────────────

class TestCrawlState:
    def test_new_state(self):
        state = new_state(year=2023)
        assert state.year == 2023
        assert state.last_page == 0
        assert state.completed is False
        assert state.started_at != ""

    def test_mark_page(self):
        state = new_state()
        state.mark_page(page=1, fetched=100, saved=95, skipped=5)
        assert state.last_page == 1
        assert state.total_fetched == 100
        assert state.total_saved == 95

    def test_save_and_load(self, tmp_path: Path):
        state = new_state(year=2023)
        state.mark_page(1, 50, 45, 5)
        state.add_error("test error")

        path = tmp_path / "state.json"
        save_state(state, path=path)
        loaded = load_state(path=path)

        assert loaded is not None
        assert loaded.year == 2023
        assert loaded.total_fetched == 50
        assert len(loaded.errors) == 1

    def test_load_missing(self, tmp_path: Path):
        assert load_state(path=tmp_path / "nonexistent.json") is None

    def test_summary(self):
        state = new_state(year=2023)
        state.mark_page(3, 300, 280, 20)
        assert "2023" in state.summary
        assert "300" in state.summary

    def test_mark_completed(self):
        state = new_state(year=2024)
        state.mark_completed()
        assert state.completed is True
        assert "completed=True" in state.summary
