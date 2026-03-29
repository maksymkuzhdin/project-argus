from decimal import Decimal

from app.normalization.assemble_timeline import (
    _asset_fingerprint,
    _compute_one_off_income,
    _compute_unknown_share,
    _snapshot_from_full,
    assemble_timeline,
)


def test_asset_fingerprint_vehicle_uses_resolved_owner_and_year() -> None:
    fp = _asset_fingerprint(
        {
            "brand": "BMW",
            "model": "X5",
            "graduation_year": 2022,
            "right_belongs_resolved": "spouse",
        },
        "vh",
    )
    assert fp == "vh|bmw|x5|2022|spouse"


def test_compute_one_off_income_accepts_ua_ru_en_stems() -> None:
    incomes = [
        {"income_type": "успадкування", "amount": "100000"},
        {"income_type": "продаж майна", "amount": "200000"},
        {"income_type": "gift", "amount": "300000"},
        {"income_type": "salary", "amount": "999999"},
    ]
    assert _compute_one_off_income(incomes) == Decimal("600000")


def test_compute_unknown_share_vehicles_no_cost_count_unknown() -> None:
    share = _compute_unknown_share(
        real_estate=[],
        monetary=[],
        vehicles=[
            {"brand": "Toyota", "cost_date": None},
            {"brand": "Mazda", "cost_date": Decimal("200000")},
        ],
    )
    assert share == 0.5


def test_snapshot_uses_cash_bank_for_total_monetary() -> None:
    snap = _snapshot_from_full(
        {
            "declaration_id": "d1",
            "declaration_year": 2024,
            "declaration_type": 1,
            "bio": {"work_post": "Inspector", "work_place": "Office"},
            "features": {
                "total_income": "100000",
                "cash": "40000",
                "bank": "60000",
            },
            "real_estate": [],
            "monetary": [{"amount": "5000000"}],
            "vehicles": [],
            "incomes": [],
        }
    )
    assert snap.total_monetary == Decimal("100000")


def test_snapshot_falls_back_to_monetary_rows_when_cash_bank_absent() -> None:
    snap = _snapshot_from_full(
        {
            "declaration_id": "d2",
            "declaration_year": 2024,
            "declaration_type": 1,
            "bio": {},
            "features": {"total_income": "100000"},
            "real_estate": [],
            "monetary": [{"amount": "1500"}, {"amount": "3500"}],
            "vehicles": [],
            "incomes": [],
        }
    )
    assert snap.total_monetary == Decimal("5000")


def test_assemble_timeline_tracks_declarations_per_year() -> None:
    timeline = assemble_timeline(
        [
            {
                "declaration_id": "d-2024-a",
                "user_declarant_id": 10,
                "declaration_year": 2024,
                "declaration_type": 1,
                "bio": {"firstname": "A", "lastname": "B"},
                "features": {"total_income": "100", "cash": "10", "bank": "20"},
                "real_estate": [],
                "monetary": [],
                "vehicles": [],
                "incomes": [],
            },
            {
                "declaration_id": "d-2024-b",
                "user_declarant_id": 10,
                "declaration_year": 2024,
                "declaration_type": 3,
                "bio": {"firstname": "A", "lastname": "B"},
                "features": {"total_income": "120", "cash": "10", "bank": "20"},
                "real_estate": [],
                "monetary": [],
                "vehicles": [],
                "incomes": [],
            },
            {
                "declaration_id": "d-2025",
                "user_declarant_id": 10,
                "declaration_year": 2025,
                "declaration_type": 1,
                "bio": {"firstname": "A", "lastname": "B"},
                "features": {"total_income": "200", "cash": "20", "bank": "30"},
                "real_estate": [],
                "monetary": [],
                "vehicles": [],
                "incomes": [],
            },
        ]
    )
    assert timeline is not None
    assert timeline.declarations_per_year == {2024: 2, 2025: 1}
