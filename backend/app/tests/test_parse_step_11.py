"""
Tests for app.normalization.parse_step_11
"""

from decimal import Decimal

import pytest

from app.normalization.parse_step_11 import parse_step_11


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_declaration(step_11_data: dict) -> dict:
    """Wrap step_11 data in a minimal declaration envelope."""
    return {
        "id": "test-decl-001",
        "data": {"step_11": step_11_data},
    }


# ── Happy path ──────────────────────────────────────────────────────────

class TestParseStep11Basic:
    ITEM = {
        "sources": [
            {
                "iteration": "1771145111733",
                "source_ua_company_name": "ТЕСТОВА КОМПАНІЯ",
                "incomeSource": "j",
                "source_citizen": "Юридична особа, зареєстрована в Україні",
                "source_ua_company_code": "12345678",
            }
        ],
        "person_who_care": [{"person": "1"}],
        "sizeIncome": "255515",
        "iteration": "1493363043296",
        "objectType": "Заробітна плата (грошове забезпечення)",
    }

    def test_single_income(self):
        decl = _make_declaration({"data": [self.ITEM]})
        rows = parse_step_11(decl)
        assert len(rows) == 1
        r = rows[0]
        assert r["declaration_id"] == "test-decl-001"
        assert r["person_ref"] == "1"
        assert r["income_type"] == "Заробітна плата (грошове забезпечення)"
        assert r["amount"] == Decimal("255515")
        assert r["amount_raw"] == "255515"
        assert r["amount_status"] is None
        assert r["source_name"] == "ТЕСТОВА КОМПАНІЯ"
        assert r["source_code"] == "12345678"
        assert r["source_type"] == "j"

    def test_family_member_person_ref(self):
        item = dict(self.ITEM)
        item["person_who_care"] = [{"person": "1493359672274"}]
        decl = _make_declaration({"data": [item]})
        rows = parse_step_11(decl)
        assert rows[0]["person_ref"] == "1493359672274"

    def test_comma_decimal_amount(self):
        item = dict(self.ITEM)
        item["sizeIncome"] = "3,40"
        decl = _make_declaration({"data": [item]})
        rows = parse_step_11(decl)
        assert rows[0]["amount"] == Decimal("3.40")

    def test_other_object_type(self):
        item = dict(self.ITEM)
        item["objectType"] = "Інше"
        item["otherObjectType"] = "Соціальні виплати"
        decl = _make_declaration({"data": [item]})
        rows = parse_step_11(decl)
        assert rows[0]["income_type"] == "Інше"
        assert rows[0]["income_type_other"] == "Соціальні виплати"

    def test_multiple_items(self):
        decl = _make_declaration({"data": [self.ITEM, self.ITEM]})
        rows = parse_step_11(decl)
        assert len(rows) == 2


# ── Edge cases ──────────────────────────────────────────────────────────

class TestParseStep11EdgeCases:
    def test_not_applicable(self):
        decl = _make_declaration({"isNotApplicable": 1})
        assert parse_step_11(decl) == []

    def test_empty_data_list(self):
        decl = _make_declaration({"data": []})
        assert parse_step_11(decl) == []

    def test_missing_step_11(self):
        decl = {"id": "test", "data": {}}
        assert parse_step_11(decl) == []

    def test_placeholder_income(self):
        item = {
            "sources": [],
            "person_who_care": [{"person": "1"}],
            "sizeIncome": "[Не відомо]",
            "iteration": "123",
            "objectType": "Salary",
        }
        decl = _make_declaration({"data": [item]})
        rows = parse_step_11(decl)
        assert rows[0]["amount"] is None
        assert rows[0]["amount_status"] == "unknown"

    def test_no_sources(self):
        item = {
            "person_who_care": [{"person": "1"}],
            "sizeIncome": "100",
            "iteration": "123",
            "objectType": "Test",
        }
        decl = _make_declaration({"data": [item]})
        rows = parse_step_11(decl)
        assert rows[0]["source_name"] is None
        assert rows[0]["source_code"] is None


# ── Real data snippet ───────────────────────────────────────────────────

class TestParseStep11RealData:
    """Test against a slice from a real declaration."""

    REAL_DECLARATION = {
        "id": "0030c328-a228-414c-a97e-76d23ca1d745",
        "data": {
            "step_11": {
                "data": [
                    {
                        "sources": [
                            {
                                "iteration": "1771145111733",
                                "source_ua_company_name": "ЦЕНТР ЗВ'ЯЗКУ",
                                "incomeSource": "j",
                                "source_citizen": "Юридична особа",
                                "source_ua_company_code": "33962437",
                            }
                        ],
                        "person_who_care": [{"person": "1493359672274"}],
                        "sizeIncome": "255515",
                        "iteration": "1493363043296",
                        "objectType": "Заробітна плата (грошове забезпечення)",
                    },
                    {
                        "sources": [
                            {
                                "iteration": "1771145341265",
                                "source_ua_company_name": "ТАШАНСЬКА СІЛЬСЬКА РАДА",
                                "incomeSource": "j",
                                "source_citizen": "Юридична особа",
                                "source_ua_company_code": "04361605",
                            }
                        ],
                        "person_who_care": [{"person": "1"}],
                        "sizeIncome": "96048",
                        "iteration": "1493363805610",
                        "objectType": "Заробітна плата (грошове забезпечення)",
                    },
                ]
            }
        },
    }

    def test_parses_two_incomes(self):
        rows = parse_step_11(self.REAL_DECLARATION)
        assert len(rows) == 2

    def test_first_income_is_family(self):
        rows = parse_step_11(self.REAL_DECLARATION)
        assert rows[0]["person_ref"] == "1493359672274"
        assert rows[0]["amount"] == Decimal("255515")

    def test_second_income_is_declarant(self):
        rows = parse_step_11(self.REAL_DECLARATION)
        assert rows[1]["person_ref"] == "1"
        assert rows[1]["amount"] == Decimal("96048")
        assert rows[1]["source_code"] == "04361605"
