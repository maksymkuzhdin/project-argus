from __future__ import annotations

import os

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
