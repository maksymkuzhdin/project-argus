"""
Tests for app.normalization.parse_step_3 (and parse_step_2 helpers)
"""

from decimal import Decimal

import pytest

from app.normalization.parse_step_2 import build_family_index, parse_step_2
from app.normalization.parse_step_3 import parse_step_3


# ── parse_step_2 tests ──────────────────────────────────────────────────

class TestParseStep2:
    DECL = {
        "id": "test-001",
        "data": {
            "step_2": {
                "data": [
                    {
                        "id": 1493359672274,
                        "subjectRelation": "чоловік",
                        "firstname": "Микола",
                        "lastname": "Рубан",
                        "middlename": "Петрович",
                    },
                    {
                        "id": 1706802317181,
                        "subjectRelation": "дочка",
                        "firstname": "Діана",
                        "lastname": "Пастух",
                        "middlename": "Олегівна",
                    },
                ],
                "isNotApplicable": 0,
            }
        },
    }

    def test_parses_family_members(self):
        rows = parse_step_2(self.DECL)
        assert len(rows) == 2
        assert rows[0]["member_id"] == "1493359672274"
        assert rows[0]["relation"] == "чоловік"
        assert rows[0]["firstname"] == "Микола"
        assert rows[1]["relation"] == "дочка"

    def test_not_applicable(self):
        decl = {"id": "t", "data": {"step_2": {"isNotApplicable": 1}}}
        assert parse_step_2(decl) == []


class TestBuildFamilyIndex:
    DECL = {
        "id": "test-001",
        "data": {
            "step_2": {
                "data": [
                    {
                        "id": 1493359672274,
                        "subjectRelation": "чоловік",
                        "firstname": "Микола",
                        "lastname": "Рубан",
                    }
                ],
                "isNotApplicable": 0,
            }
        },
    }

    def test_includes_declarant(self):
        idx = build_family_index(self.DECL)
        assert idx["1"] == "declarant"

    def test_includes_family_member(self):
        idx = build_family_index(self.DECL)
        assert "1493359672274" in idx
        assert "чоловік" in idx["1493359672274"]
        assert "Микола" in idx["1493359672274"]

    def test_empty_step_2(self):
        decl = {"id": "t", "data": {}}
        idx = build_family_index(decl)
        assert idx == {"1": "declarant"}


# ── parse_step_3 — basic ────────────────────────────────────────────────

class TestParseStep3Basic:
    DECL = {
        "id": "test-001",
        "data": {
            "step_2": {
                "data": [
                    {
                        "id": 1493359672274,
                        "subjectRelation": "чоловік",
                        "firstname": "Микола",
                        "lastname": "Рубан",
                    }
                ],
                "isNotApplicable": 0,
            },
            "step_3": {
                "data": [
                    {
                        "objectType": "Земельна ділянка",
                        "totalArea": "3,40",
                        "cost_date_assessment": "[Не відомо]",
                        "owningDate": "06.10.2005",
                        "country": "1",
                        "region": "Київська",
                        "district": "Бориспільський",
                        "community": "Ташанська",
                        "city": "Мала Каратуль",
                        "cityType": "Село",
                        "iteration": "1493359902212",
                        "rights": [
                            {
                                "ownershipType": "Власність",
                                "percent-ownership": "100",
                                "rightBelongs": "1",
                            }
                        ],
                    }
                ],
                "isNotApplicable": 0,
            },
        },
    }

    def test_single_property_declarant(self):
        rows = parse_step_3(self.DECL)
        assert len(rows) == 1
        r = rows[0]
        assert r["declaration_id"] == "test-001"
        assert r["object_type"] == "Земельна ділянка"
        assert r["total_area"] == Decimal("3.40")
        assert r["cost_assessment"] is None
        assert r["cost_assessment_status"] == "unknown"
        assert r["owning_date"] == "06.10.2005"
        assert r["right_belongs_raw"] == "1"
        assert r["right_belongs_resolved"] == "declarant"
        assert r["ownership_type"] == "Власність"
        assert r["percent_ownership"] == "100"
        assert r["region"] == "Київська"

    def test_family_member_ownership(self):
        decl = {
            "id": "test-001",
            "data": {
                "step_2": {
                    "data": [
                        {
                            "id": 1493359672274,
                            "subjectRelation": "чоловік",
                            "firstname": "Микола",
                            "lastname": "Рубан",
                        }
                    ],
                    "isNotApplicable": 0,
                },
                "step_3": {
                    "data": [
                        {
                            "objectType": "Житловий будинок",
                            "totalArea": "112",
                            "cost_date_assessment": "[Не відомо]",
                            "owningDate": "[Член сім'ї не надав інформацію]",
                            "iteration": "1493360577226",
                            "rights": [
                                {
                                    "ownershipType": "Власність",
                                    "percent-ownership": "100",
                                    "rightBelongs": "1493359672274",
                                }
                            ],
                        }
                    ],
                    "isNotApplicable": 0,
                },
            },
        }
        rows = parse_step_3(decl)
        assert len(rows) == 1
        r = rows[0]
        assert r["right_belongs_resolved"] == "чоловік (Микола Рубан)"
        assert r["total_area"] == Decimal("112")

    def test_shared_ownership_multiple_rows(self):
        """Properties with multiple rights produce one row per right."""
        decl = {
            "id": "test-002",
            "data": {
                "step_2": {"data": [], "isNotApplicable": 0},
                "step_3": {
                    "data": [
                        {
                            "objectType": "House",
                            "totalArea": "100",
                            "iteration": "1",
                            "rights": [
                                {"ownershipType": "A", "rightBelongs": "1"},
                                {"ownershipType": "B", "rightBelongs": "j"},
                            ],
                        }
                    ],
                    "isNotApplicable": 0,
                },
            },
        }
        rows = parse_step_3(decl)
        assert len(rows) == 2
        assert rows[0]["right_belongs_resolved"] == "declarant"
        assert rows[1]["right_belongs_resolved"] == "third_party"

    def test_third_party_j(self):
        decl = {
            "id": "t",
            "data": {
                "step_2": {"data": []},
                "step_3": {
                    "data": [
                        {
                            "objectType": "X",
                            "totalArea": "1",
                            "iteration": "1",
                            "rights": [{"ownershipType": "Y", "rightBelongs": "j"}],
                        }
                    ]
                },
            },
        }
        rows = parse_step_3(decl)
        assert rows[0]["right_belongs_resolved"] == "third_party"


# ── parse_step_3 — edge cases ──────────────────────────────────────────

class TestParseStep3EdgeCases:
    def test_not_applicable(self):
        decl = {"id": "t", "data": {"step_3": {"isNotApplicable": 1}}}
        assert parse_step_3(decl) == []

    def test_missing_step_3(self):
        decl = {"id": "t", "data": {}}
        assert parse_step_3(decl) == []

    def test_empty_data(self):
        decl = {"id": "t", "data": {"step_3": {"data": []}}}
        assert parse_step_3(decl) == []

    def test_no_rights_still_emits_row(self):
        decl = {
            "id": "t",
            "data": {
                "step_2": {"data": []},
                "step_3": {
                    "data": [
                        {
                            "objectType": "Land",
                            "totalArea": "500",
                            "iteration": "1",
                        }
                    ]
                },
            },
        }
        rows = parse_step_3(decl)
        assert len(rows) == 1
        assert rows[0]["right_belongs_raw"] is None
        assert rows[0]["right_belongs_resolved"] is None

    def test_placeholder_area(self):
        decl = {
            "id": "t",
            "data": {
                "step_2": {"data": []},
                "step_3": {
                    "data": [
                        {
                            "objectType": "X",
                            "totalArea": "[Не відомо]",
                            "iteration": "1",
                            "rights": [{"ownershipType": "A", "rightBelongs": "1"}],
                        }
                    ]
                },
            },
        }
        rows = parse_step_3(decl)
        assert rows[0]["total_area"] is None
        assert rows[0]["total_area_status"] == "unknown"

    def test_numeric_cost(self):
        decl = {
            "id": "t",
            "data": {
                "step_2": {"data": []},
                "step_3": {
                    "data": [
                        {
                            "objectType": "Land",
                            "totalArea": "750",
                            "cost_date_assessment": "66654",
                            "iteration": "1",
                            "rights": [{"ownershipType": "A", "rightBelongs": "1"}],
                        }
                    ]
                },
            },
        }
        rows = parse_step_3(decl)
        assert rows[0]["cost_assessment"] == Decimal("66654")
        assert rows[0]["cost_assessment_status"] is None
