"""
Tests for app.normalization.sanitize
"""

import pytest

from app.normalization.sanitize import (
    PLACEHOLDER_MAP,
    classify_placeholder,
    is_placeholder,
    sanitize,
)


# ── classify_placeholder ────────────────────────────────────────────────

class TestClassifyPlaceholder:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("[Конфіденційна інформація]", "confidential"),
            ("[Не застосовується]", "not_applicable"),
            ("[Не відомо]", "unknown"),
            ("[Член сім'ї не надав інформацію]", "family_no_info"),
        ],
    )
    def test_known_placeholders(self, text: str, expected: str):
        assert classify_placeholder(text) == expected

    def test_unknown_bracket_pattern(self):
        assert classify_placeholder("[Щось невідоме]") == "redacted_other"

    def test_non_placeholder_string(self):
        assert classify_placeholder("Київська") is None

    def test_empty_string(self):
        assert classify_placeholder("") is None

    def test_partial_brackets(self):
        assert classify_placeholder("[incomplete") is None
        assert classify_placeholder("not a bracket]") is None


# ── is_placeholder ──────────────────────────────────────────────────────

class TestIsPlaceholder:
    def test_known_returns_true(self):
        for text in PLACEHOLDER_MAP:
            assert is_placeholder(text) is True

    def test_regular_string_returns_false(self):
        assert is_placeholder("Бориспільський") is False

    def test_unknown_bracket_returns_false(self):
        # is_placeholder only matches the known set
        assert is_placeholder("[Something else]") is False


# ── sanitize — scalars ──────────────────────────────────────────────────

class TestSanitizeScalars:
    def test_confidential(self):
        assert sanitize("[Конфіденційна інформація]") == {
            "value": None,
            "status": "confidential",
        }

    def test_not_applicable(self):
        assert sanitize("[Не застосовується]") == {
            "value": None,
            "status": "not_applicable",
        }

    def test_unknown(self):
        assert sanitize("[Не відомо]") == {
            "value": None,
            "status": "unknown",
        }

    def test_family_no_info(self):
        assert sanitize("[Член сім'ї не надав інформацію]") == {
            "value": None,
            "status": "family_no_info",
        }

    def test_unrecognised_bracket(self):
        result = sanitize("[Нова категорія]")
        assert result == {
            "value": None,
            "status": "redacted_other",
            "original": "[Нова категорія]",
        }

    def test_regular_string_unchanged(self):
        assert sanitize("Київська") == "Київська"

    def test_integer_unchanged(self):
        assert sanitize(42) == 42

    def test_float_unchanged(self):
        assert sanitize(3.14) == 3.14

    def test_boolean_unchanged(self):
        assert sanitize(True) is True

    def test_none_unchanged(self):
        assert sanitize(None) is None


# ── sanitize — containers ───────────────────────────────────────────────

class TestSanitizeContainers:
    def test_empty_dict(self):
        assert sanitize({}) == {}

    def test_empty_list(self):
        assert sanitize([]) == []

    def test_flat_dict_with_mix(self):
        data = {
            "region": "Київська",
            "passport": "[Конфіденційна інформація]",
            "count": 5,
        }
        result = sanitize(data)
        assert result["region"] == "Київська"
        assert result["passport"] == {"value": None, "status": "confidential"}
        assert result["count"] == 5

    def test_list_of_mixed_items(self):
        data = ["normal", "[Не відомо]", 99]
        result = sanitize(data)
        assert result == [
            "normal",
            {"value": None, "status": "unknown"},
            99,
        ]

    def test_deeply_nested(self):
        data = {
            "step_3": {
                "data": [
                    {
                        "cost_date_assessment": "[Не відомо]",
                        "totalArea": "3,40",
                    }
                ]
            }
        }
        result = sanitize(data)
        inner = result["step_3"]["data"][0]
        assert inner["cost_date_assessment"] == {
            "value": None,
            "status": "unknown",
        }
        assert inner["totalArea"] == "3,40"

    def test_does_not_mutate_original(self):
        original = {"passport": "[Конфіденційна інформація]"}
        original_copy = original.copy()
        _ = sanitize(original)
        assert original == original_copy


# ── sanitize — real declaration snippet ─────────────────────────────────

class TestSanitizeRealSnippet:
    """Round-trip test against a slice of a real declaration."""

    SNIPPET = {
        "cityType": "Село",
        "country": "1",
        "city": "Мала Каратуль",
        "birthday": "[Конфіденційна інформація]",
        "passport": "[Конфіденційна інформація]",
        "actual_cityType": "[Не застосовується]",
        "cost_date_assessment": "[Не відомо]",
        "owningDate": "[Член сім'ї не надав інформацію]",
        "totalArea": "112",
        "rights": [
            {
                "ownershipType": "Власність",
                "percent-ownership": "100",
                "rightBelongs": "1493359672274",
            }
        ],
    }

    def test_placeholder_fields_converted(self):
        result = sanitize(self.SNIPPET)
        assert result["birthday"] == {"value": None, "status": "confidential"}
        assert result["passport"] == {"value": None, "status": "confidential"}
        assert result["actual_cityType"] == {"value": None, "status": "not_applicable"}
        assert result["cost_date_assessment"] == {"value": None, "status": "unknown"}
        assert result["owningDate"] == {"value": None, "status": "family_no_info"}

    def test_normal_fields_unchanged(self):
        result = sanitize(self.SNIPPET)
        assert result["cityType"] == "Село"
        assert result["totalArea"] == "112"
        assert result["rights"][0]["ownershipType"] == "Власність"
