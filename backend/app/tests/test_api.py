"""
Tests for app.api.declarations

These tests require the FastAPI app to import successfully, which in turn
needs the SQLAlchemy engine (session.py) to connect to Postgres.  If Postgres
is unavailable the entire module is skipped gracefully so the rest of the
test suite can still run.
"""

from unittest.mock import patch

import pytest

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import declarations
    from app.db.session import get_db

    # Override the DB dependency for tests to avoid real queries
    def _mock_get_db():
        yield None

    app.dependency_overrides[get_db] = _mock_get_db
    client = TestClient(app)
except Exception as _import_err:
    pytestmark = pytest.mark.skip(
        reason=f"Cannot import API layer (Postgres unavailable?): {_import_err}"
    )
    client = None  # type: ignore[assignment]
    declarations = None  # type: ignore[assignment]

# A clean state for testing
MOCK_SUMMARY = [
    {"id": "test-1", "score": 1.0, "triggered_rules": ["cash_to_bank_ratio"]},
    {"id": "test-2", "score": 0.5, "triggered_rules": ["unknown_value_frequency"]},
    {"id": "test-3", "score": 0.0, "triggered_rules": []},
]

MOCK_CACHE = {
    "test-1": {"id": "test-1", "summary": {"score": 1.0}},
    "test-2": {"id": "test-2", "summary": {"score": 0.5}},
    "test-3": {"id": "test-3", "summary": {"score": 0.0}},
}

@pytest.fixture(autouse=True)
def mock_cache():
    # Store originals
    orig_summary = declarations._CACHE_SUMMARY
    orig_cache = declarations._CACHE
    orig_loaded = declarations._LOADED

    # Apply mocks
    declarations._CACHE_SUMMARY = list(MOCK_SUMMARY)
    declarations._CACHE = dict(MOCK_CACHE)
    declarations._LOADED = True

    yield

    # Restore
    declarations._CACHE_SUMMARY = orig_summary
    declarations._CACHE = orig_cache
    declarations._LOADED = orig_loaded


@pytest.fixture(autouse=True)
def mock_db_has_data():
    """Ensure the API always takes the in-memory cache path during tests."""
    with patch.object(declarations, "_db_has_data", return_value=False):
        yield


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_declarations():
    response = client.get("/api/declarations")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_list_declarations_min_score():
    response = client.get("/api/declarations?min_score=0.1")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2  # Only test-1 and test-2


def test_get_stats():
    response = client.get("/api/declarations/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_declarations"] == 3
    assert data["flagged_declarations"] == 2
    assert data["average_score"] == 0.5  # (1.0 + 0.5 + 0.0) / 3
    assert data["rule_distribution"] == {
        "cash_to_bank_ratio": 1,
        "unknown_value_frequency": 1,
    }


def test_get_declaration_exists():
    response = client.get("/api/declarations/test-1")
    assert response.status_code == 200
    assert response.json()["id"] == "test-1"


def test_get_declaration_not_found():
    response = client.get("/api/declarations/fake-id")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "http_error"
    assert payload["error"]["message"] == "Declaration not found"


def test_list_declarations_limit_validation_error():
    response = client.get("/api/declarations?limit=9999")
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["path"] == "/api/declarations"


def test_list_declarations_min_score_validation_error():
    response = client.get("/api/declarations?min_score=101.0")
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"


def test_list_declarations_offset_pagination():
    response = client.get("/api/declarations?limit=1&offset=1")
    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 1
    assert data["offset"] == 1
    assert len(data["items"]) == 1


def test_person_timeline_path_validation_error():
    response = client.get("/api/persons/0")
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["path"] == "/api/persons/0"
