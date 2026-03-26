"""
Tests for app.normalization.parse_step_12
"""

from decimal import Decimal

import pytest

from app.normalization.parse_step_12 import parse_step_12


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_declaration(step_12_data: dict) -> dict:
    return {
        "id": "test-decl-002",
        "data": {"step_12": step_12_data},
    }


# ── Happy path ──────────────────────────────────────────────────────────

class TestParseStep12Basic:
    ITEM = {
        "assetsCurrency": "USD (Долар США)",
        "iteration": "1508416898792",
        "objectType": "Готівкові кошти",
        "organization": "[Не застосовується]",
        "organization_extendedstatus": "1",
        "rights": [{"ownershipType": "Власність", "rightBelongs": "1"}],
        "sizeAssets": "63900",
    }

    def test_single_asset(self):
        decl = _make_declaration({"data": [self.ITEM]})
        rows = parse_step_12(decl)
        assert len(rows) == 1
        r = rows[0]
        assert r["declaration_id"] == "test-decl-002"
        assert r["person_ref"] == "1"
        assert r["asset_type"] == "Готівкові кошти"
        assert r["currency_raw"] == "USD (Долар США)"
        assert r["currency_code"] == "USD"
        assert r["amount"] == Decimal("63900")
        assert r["organization"] == "[Не застосовується]"
        assert r["organization_status"] == "not_applicable"
        assert r["ownership_type"] == "Власність"

    def test_uah_currency(self):
        item = dict(self.ITEM)
        item["assetsCurrency"] = "UAH (Українська гривня)"
        decl = _make_declaration({"data": [item]})
        rows = parse_step_12(decl)
        assert rows[0]["currency_code"] == "UAH"

    def test_bare_usd(self):
        item = dict(self.ITEM)
        item["assetsCurrency"] = "USD"
        decl = _make_declaration({"data": [item]})
        rows = parse_step_12(decl)
        assert rows[0]["currency_code"] == "USD"

    def test_family_member_ref(self):
        item = dict(self.ITEM)
        item["rights"] = [
            {"ownershipType": "Власність", "rightBelongs": "1493359672274"}
        ]
        decl = _make_declaration({"data": [item]})
        rows = parse_step_12(decl)
        assert rows[0]["person_ref"] == "1493359672274"

    def test_multiple_assets(self):
        item2 = dict(self.ITEM)
        item2["assetsCurrency"] = "UAH (Українська гривня)"
        item2["sizeAssets"] = "150000"
        decl = _make_declaration({"data": [self.ITEM, item2]})
        rows = parse_step_12(decl)
        assert len(rows) == 2
        assert rows[0]["currency_code"] == "USD"
        assert rows[1]["currency_code"] == "UAH"


# ── Edge cases ──────────────────────────────────────────────────────────

class TestParseStep12EdgeCases:
    def test_not_applicable(self):
        decl = _make_declaration({"isNotApplicable": 1})
        assert parse_step_12(decl) == []

    def test_empty_data_list(self):
        decl = _make_declaration({"data": []})
        assert parse_step_12(decl) == []

    def test_missing_step_12(self):
        decl = {"id": "test", "data": {}}
        assert parse_step_12(decl) == []

    def test_no_rights(self):
        item = {
            "assetsCurrency": "USD",
            "sizeAssets": "1000",
            "iteration": "1",
            "objectType": "Cash",
        }
        decl = _make_declaration({"data": [item]})
        rows = parse_step_12(decl)
        assert rows[0]["person_ref"] is None
        assert rows[0]["ownership_type"] is None

    def test_organization_status_zero_means_provided(self):
        item = {
            "assetsCurrency": "USD",
            "sizeAssets": "1000",
            "iteration": "1",
            "objectType": "Cash",
            "organization": "Приватбанк",
            "organization_extendedstatus": "0",
            "rights": [{"ownershipType": "Власність", "rightBelongs": "1"}],
        }
        decl = _make_declaration({"data": [item]})
        rows = parse_step_12(decl)
        # extendedstatus 0 = value was provided, so status should be None
        assert rows[0]["organization_status"] is None
        assert rows[0]["organization"] == "Приватбанк"


# ── Real data snippet ───────────────────────────────────────────────────

class TestParseStep12RealData:
    REAL_DECLARATION = {
        "id": "009b2575-9717-48a1-a9c4-b57f47d3e568",
        "data": {
            "step_12": {
                "data": [
                    {
                        "assetsCurrency": "UAH (Українська гривня)",
                        "iteration": "1770901038027",
                        "objectType": "Готівкові кошти",
                        "organization": "[Не застосовується]",
                        "organization_extendedstatus": "1",
                        "rights": [
                            {"ownershipType": "Власність", "rightBelongs": "1"}
                        ],
                        "sizeAssets": "150000",
                    },
                    {
                        "assetsCurrency": "USD (Долар США)",
                        "iteration": "1771236201685",
                        "objectType": "Готівкові кошти",
                        "organization": "[Не застосовується]",
                        "organization_extendedstatus": "1",
                        "rights": [
                            {"ownershipType": "Власність", "rightBelongs": "1"}
                        ],
                        "sizeAssets": "8000",
                    },
                ]
            }
        },
    }

    def test_parses_two_assets(self):
        rows = parse_step_12(self.REAL_DECLARATION)
        assert len(rows) == 2

    def test_first_asset_uah(self):
        rows = parse_step_12(self.REAL_DECLARATION)
        assert rows[0]["currency_code"] == "UAH"
        assert rows[0]["amount"] == Decimal("150000")

    def test_second_asset_usd(self):
        rows = parse_step_12(self.REAL_DECLARATION)
        assert rows[1]["currency_code"] == "USD"
        assert rows[1]["amount"] == Decimal("8000")
