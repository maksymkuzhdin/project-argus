"""
Database-backed API integration tests.

These tests use a temporary SQLite database and hit the FastAPI app through
TestClient to exercise the DB query path (not the in-memory fallback cache).
"""

from __future__ import annotations

import json
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    AnomalyScore,
    Base,
    DeclarantProfile,
    IncomeEntry,
    MonetaryAsset,
)
from app.db.session import get_db
from app.main import app


def _seed_declarations(db_session) -> None:
    db_session.add_all(
        [
            DeclarantProfile(
                declaration_id="doc-1",
                user_declarant_id=777,
                declaration_year=2023,
                declaration_type=1,
                firstname="Iryna",
                lastname="Koval",
                work_post="Head",
                work_place="City Council",
                post_type="A",
            ),
            DeclarantProfile(
                declaration_id="doc-2",
                user_declarant_id=777,
                declaration_year=2024,
                declaration_type=1,
                firstname="Iryna",
                lastname="Koval",
                work_post="Head",
                work_place="City Council",
                post_type="A",
            ),
            IncomeEntry(
                declaration_id="doc-1",
                person_ref="1",
                income_type="salary",
                amount=Decimal("100000"),
            ),
            IncomeEntry(
                declaration_id="doc-2",
                person_ref="1",
                income_type="salary",
                amount=Decimal("150000"),
            ),
            MonetaryAsset(
                declaration_id="doc-1",
                person_ref="1",
                asset_type="cash",
                currency_code="UAH",
                amount=Decimal("50000"),
            ),
            MonetaryAsset(
                declaration_id="doc-2",
                person_ref="1",
                asset_type="cash",
                currency_code="UAH",
                amount=Decimal("120000"),
            ),
            AnomalyScore(
                declaration_id="doc-1",
                total_score=Decimal("0.25"),
                triggered_rules="unknown_value_frequency",
                explanation_summary="Minor transparency gap.",
                rule_details_json=json.dumps([]),
            ),
            AnomalyScore(
                declaration_id="doc-2",
                total_score=Decimal("0.80"),
                triggered_rules="cash_to_bank_ratio,unexplained_wealth",
                explanation_summary="High cash concentration and wealth mismatch.",
                rule_details_json=json.dumps(
                    [
                        {
                            "rule_name": "cash_to_bank_ratio",
                            "score": 0.5,
                            "triggered": True,
                            "explanation": "Cash ratio is unusually high.",
                        }
                    ]
                ),
            ),
        ]
    )
    db_session.commit()


def _make_client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as seed_session:
        _seed_declarations(seed_session)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_db_path_list_and_stats() -> None:
    client = _make_client()
    try:
        list_response = client.get("/api/declarations?limit=10")
        assert list_response.status_code == 200
        payload = list_response.json()

        assert payload["total"] == 2
        assert len(payload["items"]) == 2
        assert payload["items"][0]["declaration_id"] == "doc-2"
        assert payload["items"][0]["score"] == 0.8

        stats_response = client.get("/api/declarations/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()

        assert stats["total_declarations"] == 2
        assert stats["flagged_declarations"] == 2
        assert stats["rule_distribution"]["cash_to_bank_ratio"] == 1
    finally:
        app.dependency_overrides.clear()



def test_db_path_declaration_detail_and_person_timeline() -> None:
    client = _make_client()
    try:
        detail_response = client.get("/api/declarations/doc-2")
        assert detail_response.status_code == 200
        detail = detail_response.json()

        assert detail["id"] == "doc-2"
        assert detail["summary"]["score"] == 0.8
        assert detail["summary"]["rule_details"][0]["rule_name"] == "cash_to_bank_ratio"

        person_response = client.get("/api/persons/777")
        assert person_response.status_code == 200
        person = person_response.json()

        assert person["user_declarant_id"] == 777
        assert person["snapshot_count"] == 2
        assert len(person["changes"]) == 1
    finally:
        app.dependency_overrides.clear()
