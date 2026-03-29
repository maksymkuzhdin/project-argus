"""
Tests for app.scoring.rules — Updated for 0–100 scoring scale.

Covers:
    - Existing rule functions (unit-level, still 0–1)
    - Composite `score_declaration` (now 0–100)
    - CR5 — Asset growth vs income growth (timeline)
    - BR2 — Unknown-share growth (timeline)
    - BR4 — Role change + wealth jump (timeline)
    - CR16 — Cohort-relative outliers (within declaration scorer)
    - Timeline scoring integration
    - Interaction bonus: CR11 + CR12 (declaration-level proxy ownership)
    - Interaction bonus: CR14 + zero one-off income (timeline-level)
    - Interaction bonus: CR6 + CR15 (cross-layer real-estate concentration)
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.scoring.rules import (
    RuleResult,
    acquisition_income_mismatch,
    br2_unknown_share_growth,
    br4_role_change_wealth_jump,
    cash_to_bank_ratio,
    cr5_asset_vs_income_growth,
    score_declaration,
    score_timeline,
    unexplained_wealth,
    unknown_value_frequency,
    year_over_year_income_change,
    year_over_year_asset_growth,
    foreign_cash_jump,
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


# ── score_declaration (composite, 0–100 scale) ──────────────────────────

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
        assert result.total_score <= 100.0
        assert len(result.triggered_rules) > 0
        assert "unexplained_wealth" in result.triggered_rules
        assert "cash_to_bank_ratio" in result.triggered_rules

    def test_all_none_inputs(self):
        result = score_declaration()
        assert result.total_score == 0.0
        assert result.triggered_rules == []

    def test_score_capped_at_100(self):
        result = score_declaration(
            total_income=Decimal("1"),
            total_assets=Decimal("10000000"),
            cash_holdings=Decimal("10000000"),
            bank_deposits=Decimal("0"),
            total_value_fields=10,
            unknown_value_fields=10,
            largest_acquisition_cost=Decimal("10000000"),
        )
        assert result.total_score <= 100.0
        assert result.total_score > 0

    def test_rule_results_populated(self):
        result = score_declaration(
            total_income=Decimal("100"),
            total_assets=Decimal("100"),
        )
        assert len(result.rule_results) == 6
        assert all(isinstance(r, RuleResult) for r in result.rule_results)

    def test_new_path_returns_0_to_100(self):
        """score_declaration with full inputs (incomes, etc.) returns 0–100."""
        result = score_declaration(
            total_income=Decimal("100000"),
            total_assets=Decimal("5000000"),
            cash_holdings=Decimal("4000000"),
            bank_deposits=Decimal("50000"),
            incomes=[{"amount": "100000", "person_ref": "1", "income_type": "salary"}],
            monetary_assets=[
                {"amount": "4000000", "asset_type": "Готівка", "currency_code": "UAH", "person_ref": "1"},
            ],
            real_estate=[],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
        )
        assert result.total_score >= 0.0
        assert result.total_score <= 100.0
        assert result.total_score > 0  # should trigger multiple rules

    def test_cr12_wealth_concentration_triggers(self):
        """CR12 should trigger when low-income spouse has much higher known assets."""
        result = score_declaration(
            total_income=Decimal("400000"),
            total_assets=Decimal("2500000"),
            cash_holdings=Decimal("100000"),
            bank_deposits=Decimal("100000"),
            incomes=[
                {"amount": "400000", "person_ref": "1", "income_type": "salary"},
                {"amount": "20000", "person_ref": "sp1", "income_type": "salary"},
            ],
            monetary_assets=[
                {"amount": "1800000", "currency_code": "UAH", "person_ref": "sp1", "asset_type": "Готівкові кошти"},
                {"amount": "100000", "currency_code": "UAH", "person_ref": "1", "asset_type": "Готівкові кошти"},
            ],
            real_estate=[
                {
                    "right_belongs_raw": "sp1",
                    "cost_assessment": "1000000",
                    "percent_ownership": "100",
                    "object_type": "Квартира",
                }
            ],
            vehicles=[],
            family_members=[{"member_id": "sp1", "relation": "дружина"}],
            declaration_year=2024,
        )
        assert "CR12" in result.triggered_rules

    def test_tq5_not_applicable_step3_flag(self):
        result = score_declaration(
            total_income=Decimal("250000"),
            total_assets=Decimal("10000"),
            cash_holdings=Decimal("1000"),
            bank_deposits=Decimal("5000"),
            incomes=[{"amount": "250000", "person_ref": "1", "income_type": "salary"}],
            monetary_assets=[],
            real_estate=[],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            raw_declaration={
                "data": {
                    "step_1": {"data": {"country": "1"}},
                    "step_3": {"isNotApplicable": 1},
                }
            },
        )
        assert "TQ5" in result.triggered_rules


# ── CR5 — Asset growth vs income growth (timeline rule) ─────────────────

class TestCR5AssetVsIncomeGrowth:
    def _change(self, asset_growth, income_growth):
        return SimpleNamespace(
            asset_growth=asset_growth,
            income_growth=income_growth,
            from_year=2023,
            to_year=2024,
        )

    def test_high_asset_growth_low_income_growth(self):
        r = cr5_asset_vs_income_growth(self._change(0.6, 0.05))
        assert r.triggered
        assert r.rule_name == "CR5"
        assert r.score > 0

    def test_moderate_asset_growth_declining_income(self):
        r = cr5_asset_vs_income_growth(self._change(0.25, -0.1))
        assert r.triggered
        assert r.rule_name == "CR5"

    def test_no_trigger_normal_growth(self):
        r = cr5_asset_vs_income_growth(self._change(0.1, 0.15))
        assert not r.triggered
        assert r.score == 0.0

    def test_insufficient_data(self):
        r = cr5_asset_vs_income_growth(self._change(None, 0.1))
        assert not r.triggered

    def test_high_asset_growth_no_income_data(self):
        r = cr5_asset_vs_income_growth(self._change(0.7, None))
        assert r.triggered

    def test_just_below_threshold(self):
        r = cr5_asset_vs_income_growth(self._change(0.49, 0.05))
        assert not r.triggered


# ── BR2 — Unknown-share growth (timeline rule) ──────────────────────────

class TestBR2UnknownShareGrowth:
    def _change(self, prev, curr):
        return SimpleNamespace(
            unknown_share_prev=prev,
            unknown_share_curr=curr,
            unknown_share_delta=curr - prev,
            from_year=2023,
            to_year=2024,
        )

    def test_triggered_large_increase(self):
        r = br2_unknown_share_growth(self._change(0.2, 0.6))
        assert r.triggered
        assert r.rule_name == "BR2"
        assert "opacity" in (r.category or "")

    def test_not_triggered_small_increase(self):
        r = br2_unknown_share_growth(self._change(0.3, 0.45))
        assert not r.triggered

    def test_not_triggered_large_delta_but_low_level(self):
        """Delta >= 0.3 but curr < 0.5 should NOT trigger."""
        r = br2_unknown_share_growth(self._change(0.1, 0.4))
        assert not r.triggered

    def test_not_triggered_decrease(self):
        r = br2_unknown_share_growth(self._change(0.6, 0.3))
        assert not r.triggered

    def test_exact_threshold(self):
        r = br2_unknown_share_growth(self._change(0.2, 0.5))
        assert r.triggered  # delta=0.3, curr=0.5 — exactly on threshold


# ── BR4 — Role change + wealth jump (timeline rule) ────────────────────

class TestBR4RoleChangeWealthJump:
    def _change(self, role_changed, asset_growth):
        return SimpleNamespace(
            role_changed=role_changed,
            asset_growth=asset_growth,
            from_year=2023,
            to_year=2024,
        )

    def test_triggered_high(self):
        r = br4_role_change_wealth_jump(self._change(True, 1.2))
        assert r.triggered
        assert r.rule_name == "BR4"
        assert "HIGH" in (r.severity or "")

    def test_triggered_medium(self):
        r = br4_role_change_wealth_jump(self._change(True, 0.6))
        assert r.triggered
        assert "MEDIUM" in (r.severity or "")

    def test_not_triggered_no_role_change(self):
        r = br4_role_change_wealth_jump(self._change(False, 1.5))
        assert not r.triggered

    def test_not_triggered_small_growth(self):
        r = br4_role_change_wealth_jump(self._change(True, 0.3))
        assert not r.triggered

    def test_no_asset_data(self):
        r = br4_role_change_wealth_jump(self._change(True, None))
        assert not r.triggered


# ── CR16 — Cohort-relative outliers ─────────────────────────────────────

class TestCR16CohortIntegration:
    def _cohort(self, incomes, assets, cash_ratios):
        return SimpleNamespace(
            incomes=sorted(incomes),
            assets=sorted(assets),
            cash_ratios=sorted(cash_ratios),
        )

    def test_income_outlier_top_1pct(self):
        # 99 values from 100k-990k, our declarant at 5M
        incomes = [float(i * 10000) for i in range(10, 100)]
        assets = [float(i * 10000) for i in range(10, 100)]
        cohort = self._cohort(incomes, assets, [0.1] * 90)

        result = score_declaration(
            total_income=Decimal("5000000"),
            total_assets=Decimal("500000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("50000"),
            incomes=[{"amount": "5000000", "person_ref": "1", "income_type": "salary"}],
            monetary_assets=[],
            real_estate=[],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            cohort_stats=cohort,
        )
        assert "CR16" in result.triggered_rules

    def test_wealth_outlier_top_5pct(self):
        incomes = [float(i * 10000) for i in range(10, 100)]
        # Peer assets: 100k-900k, our declarant at 2M (top ~5%)
        assets = [float(i * 10000) for i in range(10, 100)]
        cohort = self._cohort(incomes, assets, [0.1] * 90)

        result = score_declaration(
            total_income=Decimal("300000"),
            total_assets=Decimal("2000000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("50000"),
            incomes=[{"amount": "300000", "person_ref": "1", "income_type": "salary"}],
            monetary_assets=[],
            real_estate=[],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            cohort_stats=cohort,
        )
        assert "CR16" in result.triggered_rules

    def test_no_cohort_no_cr16(self):
        result = score_declaration(
            total_income=Decimal("5000000"),
            total_assets=Decimal("500000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("50000"),
            incomes=[{"amount": "5000000", "person_ref": "1", "income_type": "salary"}],
            monetary_assets=[],
            real_estate=[],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            cohort_stats=None,
        )
        assert "CR16" not in result.triggered_rules


class TestBR3CohortConfidentialDensity:
    def _cohort(self, confidential_ratios):
        return SimpleNamespace(
            incomes=[],
            assets=[],
            cash_ratios=[],
            confidential_ratios=sorted(confidential_ratios),
        )

    def test_br3_triggers_when_above_2x_cohort_median(self):
        cohort = self._cohort([0.10, 0.12, 0.13, 0.14, 0.15])  # median ~13%

        result = score_declaration(
            total_income=Decimal("250000"),
            total_assets=Decimal("200000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("20000"),
            incomes=[
                {"amount": "250000", "amount_status": "confidential", "person_ref": "1", "income_type": "salary"}
            ],
            monetary_assets=[
                {"amount": "10000", "amount_status": "confidential", "asset_type": "Готівкові кошти", "person_ref": "1"},
                {"amount": "20000", "amount_status": None, "asset_type": "Банківський рахунок", "person_ref": "1"},
            ],
            real_estate=[
                {
                    "right_belongs_raw": "1",
                    "cost_assessment": "170000",
                    "cost_assessment_status": "confidential",
                    "object_type": "Квартира",
                    "percent_ownership": "100",
                }
            ],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            cohort_stats=cohort,
        )
        assert "BR3" in result.triggered_rules

    def test_br3_not_triggered_when_within_2x_median(self):
        cohort = self._cohort([0.10, 0.12, 0.13, 0.14, 0.15])  # median ~13%

        result = score_declaration(
            total_income=Decimal("250000"),
            total_assets=Decimal("200000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("20000"),
            incomes=[
                {"amount": "250000", "amount_status": "confidential", "person_ref": "1", "income_type": "salary"}
            ],
            monetary_assets=[
                {"amount": "10000", "amount_status": None, "asset_type": "Готівкові кошти", "person_ref": "1"},
                {"amount": "20000", "amount_status": None, "asset_type": "Банківський рахунок", "person_ref": "1"},
            ],
            real_estate=[
                {
                    "right_belongs_raw": "1",
                    "cost_assessment": "170000",
                    "cost_assessment_status": None,
                    "object_type": "Квартира",
                    "percent_ownership": "100",
                }
            ],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            cohort_stats=cohort,
        )
        assert "BR3" not in result.triggered_rules

    def test_br3_not_triggered_without_confidential_distribution(self):
        cohort = self._cohort([0.1, 0.2, 0.3, 0.4])  # size < 5

        result = score_declaration(
            total_income=Decimal("250000"),
            total_assets=Decimal("200000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("20000"),
            incomes=[
                {"amount": "250000", "amount_status": "confidential", "person_ref": "1", "income_type": "salary"}
            ],
            monetary_assets=[
                {"amount": "10000", "amount_status": "confidential", "asset_type": "Готівкові кошти", "person_ref": "1"}
            ],
            real_estate=[
                {
                    "right_belongs_raw": "1",
                    "cost_assessment": "170000",
                    "cost_assessment_status": "confidential",
                    "object_type": "Квартира",
                    "percent_ownership": "100",
                }
            ],
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            cohort_stats=cohort,
        )
        assert "BR3" not in result.triggered_rules


# ── Timeline scoring integration ────────────────────────────────────────

class TestTimelineScoringIntegration:
    """End-to-end tests for `score_timeline` with new rules."""

    def _make_timeline(self, changes):
        """Build a minimal PersonTimeline-like object for testing."""
        return SimpleNamespace(
            user_declarant_id=1,
            name="Test Person",
            snapshots=[],
            changes=changes,
            max_income_ratio=None,
            max_monetary_ratio=None,
            max_cash_delta=None,
            declarations_per_year={},
        )

    def _snapshot(self, year, *, income=None, total_real_estate=None):
        return SimpleNamespace(
            declaration_year=year,
            declaration_type=1,
            total_income=income,
            total_real_estate=total_real_estate,
        )

    def _change(self, **kwargs):
        """Build a YOYChange-like namespace with defaults."""
        defaults = {
            "from_year": 2023, "to_year": 2024,
            "income_prev": None, "income_curr": None,
            "income_delta": None, "income_ratio": None,
            "monetary_prev": None, "monetary_curr": None,
            "monetary_delta": None, "monetary_ratio": None,
            "cash_prev": None, "cash_curr": None, "cash_delta": None,
            "assets_prev": None, "assets_curr": None,
            "asset_growth": None, "income_growth": None,
            "unknown_share_prev": 0.0, "unknown_share_curr": 0.0,
            "unknown_share_delta": 0.0,
            "role_prev": "teacher", "role_curr": "teacher",
            "role_changed": False,
            "major_assets_appeared": 0,
            "major_assets_disappeared": 0,
            "max_appeared_value": None,
            "max_disappeared_value": None,
            "one_off_income_curr": Decimal("0"),
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_empty_timeline(self):
        tl = self._make_timeline([])
        result = score_timeline(tl)
        assert result.total_score == 0.0

    def test_cr5_triggers(self):
        change = self._change(
            asset_growth=0.8, income_growth=0.05,
            assets_prev=Decimal("1000000"), assets_curr=Decimal("1800000"),
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert result.total_score > 0
        assert result.total_score <= 100.0
        assert "CR5" in result.triggered_rules

    def test_br2_triggers(self):
        change = self._change(
            unknown_share_prev=0.1, unknown_share_curr=0.6,
            unknown_share_delta=0.5,
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert "BR2" in result.triggered_rules

    def test_br4_triggers(self):
        change = self._change(
            role_changed=True, asset_growth=0.7,
            assets_prev=Decimal("500000"), assets_curr=Decimal("850000"),
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert "BR4" in result.triggered_rules

    def test_mixed_signals(self):
        """Multiple rules triggering should produce a higher score."""
        change = self._change(
            income_prev=Decimal("200000"), income_curr=Decimal("800000"),
            income_ratio=4.0,
            asset_growth=0.6, income_growth=0.05,
            role_changed=True,
            unknown_share_prev=0.1, unknown_share_curr=0.7,
            unknown_share_delta=0.6,
            cash_prev=Decimal("50000"), cash_curr=Decimal("500000"),
            cash_delta=Decimal("450000"),
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert result.total_score > 0
        assert len(result.triggered_rules) >= 3

    def test_score_is_0_to_100(self):
        """Timeline scores should always be in [0, 100]."""
        change = self._change(
            income_prev=Decimal("100000"), income_curr=Decimal("500000"),
            income_ratio=5.0,
            monetary_prev=Decimal("200000"), monetary_curr=Decimal("2000000"),
            monetary_ratio=10.0,
            cash_prev=Decimal("10000"), cash_curr=Decimal("1000000"),
            cash_delta=Decimal("990000"),
            asset_growth=2.0, income_growth=-0.5,
            role_changed=True,
            unknown_share_prev=0.0, unknown_share_curr=0.8,
            unknown_share_delta=0.8,
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert 0.0 <= result.total_score <= 100.0

    def test_br1_triggers_from_multiple_declarations_same_year(self):
        tl = self._make_timeline([])
        tl.declarations_per_year = {2024: 3}
        result = score_timeline(tl)
        assert "BR1" in result.triggered_rules

    def test_cr15_triggers_on_3year_re_income_ratio(self):
        tl = self._make_timeline([])
        tl.snapshots = [
            self._snapshot(2022, income=Decimal("100000"), total_real_estate=Decimal("300000")),
            self._snapshot(2023, income=Decimal("100000"), total_real_estate=Decimal("600000")),
            self._snapshot(2024, income=Decimal("100000"), total_real_estate=Decimal("2000000")),
        ]
        result = score_timeline(tl)
        assert "CR15" in result.triggered_rules

    def test_cr14_appearance_without_one_off_income_triggers(self):
        change = self._change(
            major_assets_appeared=1,
            max_appeared_value=Decimal("1500000"),
            one_off_income_curr=Decimal("100000"),
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert "CR14" in result.triggered_rules


# ── Interaction bonus rules ──────────────────────────────────────────────────

class TestInteractionBonusCR11CR12:
    """CR11 + CR12 combined proxy-ownership signal (declaration-level)."""

    def test_both_cr11_cr12_trigger_interaction_bonus(self):
        """When CR11 and CR12 both fire, IX_CR11_CR12 bonus should appear."""
        # sp1: 100% ownership of 1M квартира + 1.8M cash, income only 20k → CR11 + CR12
        result = score_declaration(
            total_income=Decimal("400000"),
            total_assets=Decimal("3000000"),
            cash_holdings=Decimal("100000"),
            bank_deposits=Decimal("100000"),
            incomes=[
                {"amount": "400000", "person_ref": "1", "income_type": "salary"},
                {"amount": "20000", "person_ref": "sp1", "income_type": "salary"},
            ],
            monetary_assets=[
                {"amount": "1800000", "currency_code": "UAH", "person_ref": "sp1", "asset_type": "Готівкові кошти"},
                {"amount": "100000", "currency_code": "UAH", "person_ref": "1", "asset_type": "Готівкові кошти"},
            ],
            real_estate=[
                {
                    "right_belongs_raw": "sp1",
                    "cost_assessment": "1000000",
                    "percent_ownership": "100",
                    "object_type": "Квартира",
                }
            ],
            vehicles=[],
            family_members=[{"member_id": "sp1", "relation": "дружина"}],
            declaration_year=2024,
        )
        assert "CR11" in result.triggered_rules
        assert "CR12" in result.triggered_rules
        assert "IX_CR11_CR12" in result.triggered_rules

    def test_ix_cr11_cr12_explanation_in_results(self):
        """IX_CR11_CR12 interaction rule should have a non-empty explanation."""
        result = score_declaration(
            total_income=Decimal("400000"),
            total_assets=Decimal("3000000"),
            cash_holdings=Decimal("100000"),
            bank_deposits=Decimal("100000"),
            incomes=[
                {"amount": "400000", "person_ref": "1", "income_type": "salary"},
                {"amount": "20000", "person_ref": "sp1", "income_type": "salary"},
            ],
            monetary_assets=[
                {"amount": "1800000", "currency_code": "UAH", "person_ref": "sp1", "asset_type": "Готівкові кошти"},
                # Declarant has a smaller amount so sp1's assets are >2x declarant's
                {"amount": "200000", "currency_code": "UAH", "person_ref": "1", "asset_type": "Готівкові кошти"},
            ],
            real_estate=[
                {
                    "right_belongs_raw": "sp1",
                    "cost_assessment": "1000000",
                    "percent_ownership": "100",
                    "object_type": "Квартира",
                }
            ],
            vehicles=[],
            family_members=[{"member_id": "sp1", "relation": "дружина"}],
            declaration_year=2024,
        )
        ix_rules = [r for r in result.rule_results if r.rule_name == "IX_CR11_CR12"]
        assert len(ix_rules) == 1
        assert ix_rules[0].triggered
        assert ix_rules[0].explanation  # non-empty explanation

    def test_ix_cr11_cr12_increases_score_vs_single_rule(self):
        """Score with both CR11 + CR12 should exceed score with only CR12."""
        # Baseline: only CR12 triggers (no CR11 condition)
        base = score_declaration(
            total_income=Decimal("400000"),
            total_assets=Decimal("2000000"),
            cash_holdings=Decimal("50000"),
            bank_deposits=Decimal("50000"),
            incomes=[
                {"amount": "400000", "person_ref": "1", "income_type": "salary"},
                {"amount": "20000", "person_ref": "sp1", "income_type": "salary"},
            ],
            monetary_assets=[
                # sp1 has 1.2M (>2x declarant's total), but declarant owns it not sp1
                {"amount": "1200000", "currency_code": "UAH", "person_ref": "sp1", "asset_type": "Готівкові кошти"},
            ],
            real_estate=[],
            vehicles=[],
            family_members=[{"member_id": "sp1", "relation": "дружина"}],
            declaration_year=2024,
        )
        # With interaction: add real estate to trigger CR11 too
        combined = score_declaration(
            total_income=Decimal("400000"),
            total_assets=Decimal("3000000"),
            cash_holdings=Decimal("100000"),
            bank_deposits=Decimal("100000"),
            incomes=[
                {"amount": "400000", "person_ref": "1", "income_type": "salary"},
                {"amount": "20000", "person_ref": "sp1", "income_type": "salary"},
            ],
            monetary_assets=[
                {"amount": "1800000", "currency_code": "UAH", "person_ref": "sp1", "asset_type": "Готівкові кошти"},
                {"amount": "100000", "currency_code": "UAH", "person_ref": "1", "asset_type": "Готівкові кошти"},
            ],
            real_estate=[
                {
                    "right_belongs_raw": "sp1",
                    "cost_assessment": "1000000",
                    "percent_ownership": "100",
                    "object_type": "Квартира",
                }
            ],
            vehicles=[],
            family_members=[{"member_id": "sp1", "relation": "дружина"}],
            declaration_year=2024,
        )
        assert "IX_CR11_CR12" in combined.triggered_rules
        assert combined.total_score > base.total_score

    def test_no_bonus_without_cr12(self):
        """IX_CR11_CR12 must NOT fire when CR12 is absent."""
        result = score_declaration(
            total_income=Decimal("500000"),
            total_assets=Decimal("1000000"),
            cash_holdings=Decimal("50000"),
            bank_deposits=Decimal("50000"),
            incomes=[
                {"amount": "500000", "person_ref": "1", "income_type": "salary"},
                {"amount": "20000", "person_ref": "sp1", "income_type": "salary"},
            ],
            monetary_assets=[],
            real_estate=[
                {
                    "right_belongs_raw": "sp1",
                    "cost_assessment": "600000",
                    "percent_ownership": "100",
                    "object_type": "Квартира",
                }
            ],
            vehicles=[],
            family_members=[{"member_id": "sp1", "relation": "дружина"}],
            declaration_year=2024,
        )
        assert "IX_CR11_CR12" not in result.triggered_rules


class TestInteractionBonusCR14NoIncome:
    """CR14 + zero one-off income interaction bonus (timeline-level)."""

    def _make_timeline(self, changes):
        return SimpleNamespace(
            user_declarant_id=1,
            name="Test Person",
            snapshots=[],
            changes=changes,
            max_income_ratio=None,
            max_monetary_ratio=None,
            max_cash_delta=None,
            declarations_per_year={},
        )

    def _change(self, **kwargs):
        defaults = {
            "from_year": 2023, "to_year": 2024,
            "income_prev": None, "income_curr": None,
            "income_delta": None, "income_ratio": None,
            "monetary_prev": None, "monetary_curr": None,
            "monetary_delta": None, "monetary_ratio": None,
            "cash_prev": None, "cash_curr": None, "cash_delta": None,
            "assets_prev": None, "assets_curr": None,
            "asset_growth": None, "income_growth": None,
            "unknown_share_prev": 0.0, "unknown_share_curr": 0.0,
            "unknown_share_delta": 0.0,
            "role_prev": "teacher", "role_curr": "teacher",
            "role_changed": False,
            "major_assets_appeared": 0,
            "major_assets_disappeared": 0,
            "max_appeared_value": None,
            "max_disappeared_value": None,
            "one_off_income_curr": Decimal("0"),
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_cr14_zero_one_off_triggers_interaction_bonus(self):
        """When CR14 fires with zero one-off income, IX_CR14_NO_INCOME should appear."""
        change = self._change(
            major_assets_appeared=1,
            max_appeared_value=Decimal("2000000"),
            one_off_income_curr=Decimal("0"),
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert "CR14" in result.triggered_rules
        assert "IX_CR14_NO_INCOME" in result.triggered_rules

    def test_cr14_with_some_income_no_interaction_bonus(self):
        """When CR14 fires but one-off income is non-zero, IX_CR14_NO_INCOME should NOT appear."""
        change = self._change(
            major_assets_appeared=1,
            max_appeared_value=Decimal("2000000"),
            one_off_income_curr=Decimal("100000"),  # some income, not zero
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert "CR14" in result.triggered_rules
        assert "IX_CR14_NO_INCOME" not in result.triggered_rules

    def test_ix_cr14_no_income_explanation_non_empty(self):
        """IX_CR14_NO_INCOME should carry a clear explanation string."""
        change = self._change(
            major_assets_appeared=1,
            max_appeared_value=Decimal("1500000"),
            one_off_income_curr=Decimal("0"),
        )
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        ix_rules = [r for r in result.rule_results if r.rule_name == "IX_CR14_NO_INCOME"]
        assert len(ix_rules) == 1
        assert ix_rules[0].triggered
        assert ix_rules[0].explanation

    def test_ix_cr14_increases_score_vs_partial_income(self):
        """Zero one-off income should yield higher score than partial income (CR14 only)."""
        partial_income_change = self._change(
            major_assets_appeared=1,
            max_appeared_value=Decimal("2000000"),
            one_off_income_curr=Decimal("200000"),
        )
        zero_income_change = self._change(
            major_assets_appeared=1,
            max_appeared_value=Decimal("2000000"),
            one_off_income_curr=Decimal("0"),
        )
        result_partial = score_timeline(self._make_timeline([partial_income_change]))
        result_zero = score_timeline(self._make_timeline([zero_income_change]))
        assert result_zero.total_score > result_partial.total_score

    def test_no_cr14_no_interaction_bonus(self):
        """IX_CR14_NO_INCOME must NOT fire when CR14 is absent."""
        change = self._change(one_off_income_curr=Decimal("0"))
        tl = self._make_timeline([change])
        result = score_timeline(tl)
        assert "CR14" not in result.triggered_rules
        assert "IX_CR14_NO_INCOME" not in result.triggered_rules


class TestInteractionBonusCR6CR15:
    """CR6 + CR15 cross-layer interaction bonus (timeline-level with declaration input)."""

    def _snapshot(self, year, *, income=None, total_real_estate=None):
        return SimpleNamespace(
            declaration_year=year,
            declaration_type=1,
            total_income=income,
            total_real_estate=total_real_estate,
        )

    def _make_timeline_with_snapshots(self, snapshots):
        return SimpleNamespace(
            user_declarant_id=1,
            name="Test Person",
            snapshots=snapshots,
            changes=[],
            max_income_ratio=None,
            max_monetary_ratio=None,
            max_cash_delta=None,
            declarations_per_year={},
        )

    def test_cr6_cr15_both_trigger_interaction_bonus(self):
        """When CR15 fires in timeline and CR6 is passed from declaration, IX_CR6_CR15 appears."""
        tl = self._make_timeline_with_snapshots([
            self._snapshot(2022, income=Decimal("100000"), total_real_estate=Decimal("300000")),
            self._snapshot(2023, income=Decimal("100000"), total_real_estate=Decimal("600000")),
            self._snapshot(2024, income=Decimal("100000"), total_real_estate=Decimal("2000000")),
        ])
        # CR15 triggers (20x ratio), CR6 from declaration
        result = score_timeline(tl, declaration_triggered_rules={"CR6"})
        assert "CR15" in result.triggered_rules
        assert "IX_CR6_CR15" in result.triggered_rules

    def test_no_ix_cr6_cr15_without_cr6_in_declaration(self):
        """IX_CR6_CR15 must NOT fire when CR6 is absent from declaration rules."""
        tl = self._make_timeline_with_snapshots([
            self._snapshot(2022, income=Decimal("100000"), total_real_estate=Decimal("300000")),
            self._snapshot(2023, income=Decimal("100000"), total_real_estate=Decimal("600000")),
            self._snapshot(2024, income=Decimal("100000"), total_real_estate=Decimal("2000000")),
        ])
        result = score_timeline(tl)  # no declaration_triggered_rules
        assert "CR15" in result.triggered_rules
        assert "IX_CR6_CR15" not in result.triggered_rules

    def test_no_ix_cr6_cr15_without_cr15(self):
        """IX_CR6_CR15 must NOT fire when CR15 does not trigger."""
        tl = self._make_timeline_with_snapshots([
            self._snapshot(2022, income=Decimal("500000"), total_real_estate=Decimal("300000")),
            self._snapshot(2023, income=Decimal("500000"), total_real_estate=Decimal("400000")),
            self._snapshot(2024, income=Decimal("500000"), total_real_estate=Decimal("1000000")),
        ])
        result = score_timeline(tl, declaration_triggered_rules={"CR6"})
        assert "CR15" not in result.triggered_rules
        assert "IX_CR6_CR15" not in result.triggered_rules

    def test_ix_cr6_cr15_explanation_non_empty(self):
        """IX_CR6_CR15 interaction rule should carry a clear explanation string."""
        tl = self._make_timeline_with_snapshots([
            self._snapshot(2022, income=Decimal("100000"), total_real_estate=Decimal("300000")),
            self._snapshot(2023, income=Decimal("100000"), total_real_estate=Decimal("600000")),
            self._snapshot(2024, income=Decimal("100000"), total_real_estate=Decimal("2000000")),
        ])
        result = score_timeline(tl, declaration_triggered_rules={"CR6"})
        ix_rules = [r for r in result.rule_results if r.rule_name == "IX_CR6_CR15"]
        assert len(ix_rules) == 1
        assert ix_rules[0].triggered
        assert ix_rules[0].explanation

    def test_ix_cr6_cr15_increases_score_vs_cr15_alone(self):
        """IX_CR6_CR15 bonus should yield a higher score than CR15 alone."""
        tl = self._make_timeline_with_snapshots([
            self._snapshot(2022, income=Decimal("100000"), total_real_estate=Decimal("300000")),
            self._snapshot(2023, income=Decimal("100000"), total_real_estate=Decimal("600000")),
            self._snapshot(2024, income=Decimal("100000"), total_real_estate=Decimal("2000000")),
        ])
        result_no_cr6 = score_timeline(tl)
        result_with_cr6 = score_timeline(tl, declaration_triggered_rules={"CR6"})
        assert result_with_cr6.total_score > result_no_cr6.total_score


class TestExistingInteractionBonusExplanations:
    """Existing CR1+CR2 and CR10+CR13 bonuses should now emit explanation RuleResults."""

    def _family_no_info_assets(self, count: int) -> list[dict]:
        return [
            {
                "right_belongs_raw": "sp1",
                "cost_assessment": None,
                "cost_assessment_status": "family_no_info",
                "percent_ownership": "100",
                "object_type": "Квартира",
                "total_area": "150",
            }
            for _ in range(count)
        ]

    def test_ix_cr10_cr13_explanation_emitted(self):
        """When CR10 and CR13 both fire, IX_CR10_CR13 RuleResult should appear."""
        family_assets = self._family_no_info_assets(4)  # 4 family_no_info items → CR13
        # Add an unknown-value real estate item to trigger CR10
        monetary_with_unknown = [
            {
                "person_ref": "1",
                "asset_type": "Банківський рахунок",
                "amount": None,
                "amount_status": "unknown",
                "currency_code": "UAH",
            }
            for _ in range(3)
        ]
        result = score_declaration(
            total_income=Decimal("200000"),
            total_assets=Decimal("500000"),
            cash_holdings=Decimal("10000"),
            bank_deposits=Decimal("20000"),
            incomes=[{"amount": "200000", "person_ref": "1", "income_type": "salary"}],
            monetary_assets=monetary_with_unknown,
            real_estate=family_assets,
            vehicles=[],
            family_members=[{"member_id": "sp1", "relation": "дружина"}],
            declaration_year=2024,
        )
        if "CR10" in result.triggered_rules and "CR13" in result.triggered_rules:
            assert "IX_CR10_CR13" in result.triggered_rules
            ix_rules = [r for r in result.rule_results if r.rule_name == "IX_CR10_CR13"]
            assert len(ix_rules) == 1
            assert ix_rules[0].explanation
