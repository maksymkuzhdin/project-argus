"""
Tests for app.scoring.rules
"""

from decimal import Decimal

import pytest

from app.scoring.rules import (
    RuleResult,
    acquisition_income_mismatch,
    cash_to_bank_ratio,
    score_declaration,
    unexplained_wealth,
    unknown_value_frequency,
)


# ── unexplained_wealth ──────────────────────────────────────────────────

class TestUnexplainedWealth:
    def test_not_triggered_within_threshold(self):
        r = unexplained_wealth(Decimal("100000"), Decimal("200000"))
        assert not r.triggered
        assert r.score == 0.0

    def test_triggered_above_threshold(self):
        r = unexplained_wealth(Decimal("100000"), Decimal("500000"))
        assert r.triggered
        assert r.score > 0

    def test_extreme_ratio(self):
        r = unexplained_wealth(Decimal("100"), Decimal("1000000"))
        assert r.triggered
        assert r.score == 1.0  # capped

    def test_zero_income_with_assets(self):
        r = unexplained_wealth(Decimal("0"), Decimal("100000"))
        assert r.triggered
        assert r.score == 1.0

    def test_none_values(self):
        r = unexplained_wealth(None, None)
        assert not r.triggered

    def test_no_income_no_assets(self):
        r = unexplained_wealth(Decimal("0"), Decimal("0"))
        assert not r.triggered

    def test_custom_threshold(self):
        r = unexplained_wealth(
            Decimal("100000"), Decimal("250000"), threshold_ratio=2.0
        )
        assert r.triggered


# ── cash_to_bank_ratio ──────────────────────────────────────────────────

class TestCashToBankRatio:
    def test_not_triggered(self):
        r = cash_to_bank_ratio(Decimal("20000"), Decimal("80000"))
        assert not r.triggered

    def test_triggered_high_cash(self):
        r = cash_to_bank_ratio(Decimal("90000"), Decimal("10000"))
        assert r.triggered
        assert r.score > 0

    def test_all_cash(self):
        r = cash_to_bank_ratio(Decimal("100000"), Decimal("0"))
        assert r.triggered
        assert r.score == 1.0

    def test_no_assets(self):
        r = cash_to_bank_ratio(None, None)
        assert not r.triggered

    def test_zero_total(self):
        r = cash_to_bank_ratio(Decimal("0"), Decimal("0"))
        assert not r.triggered


# ── unknown_value_frequency ─────────────────────────────────────────────

class TestUnknownValueFrequency:
    def test_not_triggered(self):
        r = unknown_value_frequency(20, 3)
        assert not r.triggered

    def test_triggered(self):
        # 8 of 10 = 80%, well above 50% threshold
        r = unknown_value_frequency(10, 8)
        assert r.triggered

    def test_all_unknown(self):
        r = unknown_value_frequency(10, 10)
        assert r.triggered
        assert r.score == 1.0

    def test_too_few_fields(self):
        # Below min_fields (4), should not trigger even if all unknown
        r = unknown_value_frequency(2, 2)
        assert not r.triggered

    def test_no_fields(self):
        r = unknown_value_frequency(0, 0)
        assert not r.triggered

    def test_zero_unknown(self):
        r = unknown_value_frequency(10, 0)
        assert not r.triggered
        assert r.score == 0.0

    def test_below_new_threshold(self):
        # 4 of 10 = 40%, below 50% — should NOT trigger (was triggering before)
        r = unknown_value_frequency(10, 4)
        assert not r.triggered


# ── acquisition_income_mismatch ─────────────────────────────────────────

class TestAcquisitionIncomeMismatch:
    def test_not_triggered(self):
        r = acquisition_income_mismatch(Decimal("50000"), Decimal("100000"))
        assert not r.triggered

    def test_triggered(self):
        r = acquisition_income_mismatch(Decimal("200000"), Decimal("100000"))
        assert r.triggered

    def test_zero_income_with_acquisition(self):
        r = acquisition_income_mismatch(Decimal("50000"), Decimal("0"))
        assert r.triggered
        assert r.score == 1.0

    def test_none_values(self):
        r = acquisition_income_mismatch(None, None)
        assert not r.triggered


# ── score_declaration (composite) ───────────────────────────────────────

class TestScoreDeclaration:
    def test_clean_declaration(self):
        result = score_declaration(
            total_income=Decimal("200000"),
            total_assets=Decimal("100000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("90000"),
            total_value_fields=20,
            unknown_value_fields=2,
            largest_acquisition_cost=Decimal("50000"),
        )
        assert result.total_score == 0.0
        assert result.triggered_rules == []
        assert result.explanation_summary == "No anomaly signals detected."

    def test_suspicious_declaration(self):
        result = score_declaration(
            total_income=Decimal("100000"),
            total_assets=Decimal("1000000"),
            cash_holdings=Decimal("900000"),
            bank_deposits=Decimal("100000"),
            total_value_fields=10,
            unknown_value_fields=6,
            largest_acquisition_cost=Decimal("500000"),
        )
        assert result.total_score > 0
        assert len(result.triggered_rules) > 0
        assert "unexplained_wealth" in result.triggered_rules
        assert "cash_to_bank_ratio" in result.triggered_rules

    def test_all_none_inputs(self):
        result = score_declaration()
        assert result.total_score == 0.0
        assert result.triggered_rules == []

    def test_score_capped_at_one(self):
        result = score_declaration(
            total_income=Decimal("1"),
            total_assets=Decimal("10000000"),
            cash_holdings=Decimal("10000000"),
            bank_deposits=Decimal("0"),
            total_value_fields=10,
            unknown_value_fields=10,
            largest_acquisition_cost=Decimal("10000000"),
        )
        assert result.total_score <= 1.0

    def test_rule_results_populated(self):
        result = score_declaration(
            total_income=Decimal("100"),
            total_assets=Decimal("100"),
        )
        assert len(result.rule_results) == 6
        assert all(isinstance(r, RuleResult) for r in result.rule_results)
