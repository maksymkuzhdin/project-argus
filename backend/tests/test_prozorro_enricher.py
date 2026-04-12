import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from app.services.prozorro_enricher import enrich_edrpou
from app.db.models import ProzorroEnrichment

class MockResponse:
    def __init__(self, json_data, status_code):
        self._json_data = json_data
        self.status_code = status_code
        self.text = str(json_data)
        
    def json(self):
        return self._json_data

def test_enrich_edrpou_valid(mocker):
    # Mock DB
    db = MagicMock()
    db.query().filter().first.return_value = None
    
    response_data = {
        "data": [
            {
                "value": {"amountNet": 1000, "currency": "UAH"},
                "dateSigned": "2024-01-01T12:00:00Z",
                "procuringEntity": {"identifier": {"id": "11111111"}}
            },
            {
                "value": {"amount": 500, "currency": "UAH"},
                "dateSigned": "2024-02-01T12:00:00Z",
                "procuringEntity": {"identifier": {"id": "11111111"}}
            }
        ]
    }
    
    mock_get = mocker.patch("httpx.Client.get", return_value=MockResponse(response_data, 200))
    mocker.patch("time.sleep")
    
    res = enrich_edrpou("99999999", db)
    
    assert res["is_supplier"] is True
    assert res["contract_count"] == 2
    assert res["total_value_uah"] == 1500
    assert res["procuring_entity_edrpou"] == ["11111111"]
    assert str(res["most_recent_contract_date"]) == "2024-02-01"

def test_enrich_edrpou_pagination(mocker):
    db = MagicMock()
    db.query().filter().first.return_value = None
    
    page1 = {
        "data": [{"value": {"amount": 100, "currency": "UAH"}}],
        "next_page": {"uri": "http://next"}
    }
    page2 = {
        "data": [{"value": {"amount": 200, "currency": "UAH"}}]
    }
    
    # sequence of responses
    mocker.patch("httpx.Client.get", side_effect=[MockResponse(page1, 200), MockResponse(page2, 200)])
    mocker.patch("time.sleep")
    
    res = enrich_edrpou("99999999", db)
    
    assert res["is_supplier"] is True
    assert res["contract_count"] == 2
    assert res["total_value_uah"] == 300

def test_enrich_edrpou_429_retry(mocker):
    db = MagicMock()
    db.query().filter().first.return_value = None
    
    success = {"data": [{"value": {"amount": 10, "currency": "UAH"}}]}
    
    mocker.patch("httpx.Client.get", side_effect=[MockResponse({}, 429), MockResponse(success, 200)])
    sleep_mock = mocker.patch("time.sleep")
    
    res = enrich_edrpou("88888888", db)
    
    assert res["is_supplier"] is True
    assert sleep_mock.call_count >= 1

def test_enrich_edrpou_cache(mocker):
    db = MagicMock()
    existing = ProzorroEnrichment(
        edrpou="77777777", 
        is_supplier=True, 
        contract_count=1, 
        total_value_uah=10.0,
        enriched_at=datetime.now(timezone.utc) - timedelta(days=1),
        procuring_entity_edrpou=["123"]
    )
    db.query().filter().first.return_value = existing
    
    mock_get = mocker.patch("httpx.Client.get")
    
    res = enrich_edrpou("77777777", db)
    
    assert mock_get.called is False
    assert res["is_supplier"] is True
    assert res["procuring_entity_edrpou"] == ["123"]
