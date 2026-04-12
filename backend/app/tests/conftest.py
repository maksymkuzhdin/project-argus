from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "db_integration: marks tests that require database integration setup",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    requires_db = os.getenv("ARGUS_REQUIRE_DB_TESTS") == "1"
    markexpr = (config.getoption("-m") or "").strip()
    requested_db_only = markexpr == "db_integration"

    if requested_db_only and not requires_db:
        raise pytest.UsageError(
            "DB integration tests were explicitly selected with '-m db_integration', "
            "but ARGUS_REQUIRE_DB_TESTS is not set. Use ARGUS_REQUIRE_DB_TESTS=1."
        )

    if requires_db:
        return

    skip_db = pytest.mark.skip(
        reason=(
            "DB integration tests are disabled by default. "
            "Set ARGUS_REQUIRE_DB_TESTS=1 to run them."
        )
    )
    for item in items:
        if "db_integration" in item.keywords:
            item.add_marker(skip_db)


@pytest.fixture
def declaration_factory():
    """Build minimal score_declaration kwargs with optional overrides."""

    def _build(**overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "total_income": Decimal("100000"),
            "total_assets": Decimal("100000"),
            "cash_holdings": Decimal("10000"),
            "bank_deposits": Decimal("90000"),
            "incomes": [],
            "monetary_assets": [],
            "real_estate": [],
            "vehicles": [],
            "family_members": [],
            "declaration_year": 2024,
        }
        payload.update(overrides)
        return payload

    return _build
