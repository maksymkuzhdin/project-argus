import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from app.scoring.rules import score_declaration

@pytest.fixture
def mock_db_session(mocker):
    # Mock the SessionLocal context manager
    mock_session_cls = mocker.patch("app.db.session.SessionLocal")
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session
    return mock_session

def _make_dummy_declaration(employer_edrpou=None, income_edrpous=None):
    data = {}
    if employer_edrpou:
        data["step_1"] = {"data": {"workPlaceEdrpou": employer_edrpou}}
    if income_edrpous:
        data["step_11"] = {"data": []}
        for code in income_edrpous:
            data["step_11"]["data"].append({"sources": [{"sourceuacompanycode": code}]})
            
    return {
        "data": data
    }

def _make_enrichment(edrpou, is_supplier, target_buyers=None):
    mock_enrichment = MagicMock()
    mock_enrichment.edrpou = edrpou
    mock_enrichment.is_supplier = is_supplier
    mock_enrichment.contract_count = 5
    mock_enrichment.total_value_uah = 1000.0
    mock_enrichment.procuring_entity_edrpou = target_buyers or []
    return mock_enrichment

def test_cr17_cr18_cr19_missing_data(mock_db_session):
    # If enrichments aren't found, it should degrade gracefully and not trigger
    mock_db_session.query().filter().all.return_value = []
    
    res = score_declaration(
        total_income=Decimal("1000"),
        total_assets=Decimal("1000"),
        cash_holdings=None,
        bank_deposits=None,
        total_value_fields=10,
        unknown_value_fields=0,
        largest_acquisition_cost=None,
        ownership_declarant=1,
        ownership_family=0,
        ownership_total=1,
        incomes=[],
        monetary_assets=[],
        real_estate=[],
        vehicles=[],
        family_members=[],
        declaration_year=2024,
        raw_declaration=_make_dummy_declaration("11111111", ["22222222"])
    )
    
    triggers = res.triggered_rules
    assert "CR17" not in triggers
    assert "CR18" not in triggers
    assert "CR19" not in triggers

def test_cr17_triggers(mock_db_session):
    mock_db_session.query().filter().all.return_value = [
        _make_enrichment("11111111", True)
    ]
    
    res = score_declaration(
        total_income=Decimal("1000"), total_assets=Decimal("1000"),
        cash_holdings=None, bank_deposits=None,
        total_value_fields=10, unknown_value_fields=0, largest_acquisition_cost=None,
        ownership_declarant=1, ownership_family=0, ownership_total=1,
        incomes=[], monetary_assets=[], real_estate=[], vehicles=[], family_members=[],
        declaration_year=2024,
        raw_declaration=_make_dummy_declaration("11111111")
    )
    
    triggers = res.triggered_rules
    assert "CR17" in triggers

def test_cr18_triggers(mock_db_session):
    mock_db_session.query().filter().all.return_value = [
        _make_enrichment("22222222", True)
    ]
    
    res = score_declaration(
        total_income=Decimal("1000"), total_assets=Decimal("1000"),
        cash_holdings=None, bank_deposits=None,
        total_value_fields=10, unknown_value_fields=0, largest_acquisition_cost=None,
        ownership_declarant=1, ownership_family=0, ownership_total=1,
        incomes=[], monetary_assets=[], real_estate=[], vehicles=[], family_members=[],
        declaration_year=2024,
        raw_declaration=_make_dummy_declaration(None, ["22222222"])
    )
    
    triggers = res.triggered_rules
    assert "CR18" in triggers

def test_cr19_triggers(mock_db_session):
    # CR19 requires both employer and income, and income source has employer in buyers
    mock_db_session.query().filter().all.return_value = [
        _make_enrichment("11111111", False),
        _make_enrichment("22222222", True, target_buyers=["11111111"])
    ]
    
    res = score_declaration(
        total_income=Decimal("1000"), total_assets=Decimal("1000"),
        cash_holdings=None, bank_deposits=None,
        total_value_fields=10, unknown_value_fields=0, largest_acquisition_cost=None,
        ownership_declarant=1, ownership_family=0, ownership_total=1,
        incomes=[], monetary_assets=[], real_estate=[], vehicles=[], family_members=[],
        declaration_year=2024,
        raw_declaration=_make_dummy_declaration("11111111", ["22222222"])
    )
    
    triggers = res.triggered_rules
    assert "CR18" in triggers
    assert "CR19" in triggers
