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


# ── CR6 cohort-relative refinement ──────────────────────────────────────

class TestCR6CohortRefinement:
    """CR6 uses relative thresholds when valid cohort distributions are present,
    falling back to absolute thresholds otherwise."""

    # ---- helpers ----

    def _cohort(self, dwelling_areas, agri_areas):
        return SimpleNamespace(
            incomes=[],
            assets=[],
            cash_ratios=[],
            confidential_ratios=[],
            dwelling_areas=sorted(dwelling_areas),
            agri_areas=sorted(agri_areas),
        )

    def _base_call(self, real_estate, cohort_stats):
        return score_declaration(
            total_income=Decimal("400000"),
            total_assets=Decimal("1000000"),
            cash_holdings=Decimal("50000"),
            bank_deposits=Decimal("100000"),
            incomes=[{"amount": "400000", "person_ref": "1", "income_type": "salary"}],
            monetary_assets=[],
            real_estate=real_estate,
            vehicles=[],
            family_members=[],
            declaration_year=2024,
            cohort_stats=cohort_stats,
        )

    # ---- relative mode: dwelling ----

    def test_cr6_relative_dwelling_high_at_p99(self):
        """Dwelling area at 99th percentile of cohort → HIGH (relative mode)."""
        # 90 peers with areas 100-990 m2; our declarant at 1500 m2 (top 1%)
        areas = [float(i * 10) for i in range(10, 100)]  # 100-990
        cohort = self._cohort(areas, [])
        real_estate = [
            {"object_type": "Квартира", "total_area": "1500"}
        ]
        result = self._base_call(real_estate, cohort)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any(r.severity == "HIGH" for r in cr6_flags)
        assert any("relative mode" in r.explanation for r in cr6_flags)

    def test_cr6_relative_dwelling_medium_at_p95(self):
        """Dwelling area at 95th–99th percentile of cohort → MEDIUM (relative mode)."""
        # 100 peers 50-995 m2; declarant at 960 m2 (~96th percentile)
        areas = [float(i * 10) for i in range(5, 100)]  # 50-990
        cohort = self._cohort(areas, [])
        real_estate = [
            {"object_type": "Квартира", "total_area": "960"}
        ]
        result = self._base_call(real_estate, cohort)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any(r.severity == "MEDIUM" for r in cr6_flags)
        assert any("relative mode" in r.explanation for r in cr6_flags)

    def test_cr6_relative_dwelling_no_trigger_below_p95(self):
        """Dwelling area below 95th percentile of cohort → no CR6 trigger."""
        # Peers 100-990 m2; declarant at 300 m2 (~21st percentile)
        areas = [float(i * 10) for i in range(10, 100)]
        cohort = self._cohort(areas, [])
        real_estate = [
            {"object_type": "Квартира", "total_area": "300"}
        ]
        result = self._base_call(real_estate, cohort)
        assert "CR6" not in result.triggered_rules

    # ---- relative mode: agricultural ----

    def test_cr6_relative_agri_high_at_p99(self):
        """Agricultural area at 99th percentile of cohort → HIGH (relative mode)."""
        # 90 peers 1000-9900 m2; declarant at 50000 m2 (top 1%)
        agri = [float(i * 100) for i in range(10, 100)]
        cohort = self._cohort([], agri)
        real_estate = [
            {"object_type": "Земельна ділянка", "total_area": "50000"}
        ]
        result = self._base_call(real_estate, cohort)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any(r.severity == "HIGH" for r in cr6_flags)
        assert any("relative mode" in r.explanation for r in cr6_flags)

    def test_cr6_relative_agri_medium_at_p95(self):
        """Agricultural area at 95th–99th percentile of cohort → MEDIUM (relative mode)."""
        agri = [float(i * 100) for i in range(5, 100)]  # 500-9900 m2
        cohort = self._cohort([], agri)
        # 9600 m2 ≈ 96th percentile of the above distribution
        real_estate = [
            {"object_type": "Земельна ділянка", "total_area": "9600"}
        ]
        result = self._base_call(real_estate, cohort)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any(r.severity == "MEDIUM" for r in cr6_flags)
        assert any("relative mode" in r.explanation for r in cr6_flags)

    # ---- fallback: no cohort ----

    def test_cr6_absolute_fallback_when_no_cohort_stats(self):
        """Without cohort_stats, CR6 uses absolute thresholds [absolute mode]."""
        real_estate = [
            {"object_type": "Квартира", "total_area": "500"}
        ]
        result = self._base_call(real_estate, cohort_stats=None)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any("absolute mode" in r.explanation for r in cr6_flags)

    def test_cr6_absolute_fallback_when_cohort_too_small(self):
        """With fewer than 5 values in cohort, CR6 uses absolute thresholds."""
        cohort = self._cohort([100.0, 200.0, 300.0], [])  # only 3 values
        real_estate = [
            {"object_type": "Квартира", "total_area": "500"}
        ]
        result = self._base_call(real_estate, cohort)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any("absolute mode" in r.explanation for r in cr6_flags)

    def test_cr6_absolute_fallback_agri_when_no_agri_dist(self):
        """Cohort has dwelling data only; agri falls back to absolute thresholds."""
        areas = [float(i * 10) for i in range(10, 100)]
        cohort = self._cohort(areas, [])  # no agri distribution
        real_estate = [
            {"object_type": "Земельна ділянка", "total_area": "600000"}
        ]
        result = self._base_call(real_estate, cohort)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any("absolute mode" in r.explanation for r in cr6_flags)

    # ---- regression: absolute thresholds still fire without cohort ----

    def test_cr6_absolute_dwelling_high_no_cohort(self):
        """Absolute HIGH threshold (> 400 m2) still fires without cohort."""
        real_estate = [{"object_type": "Квартира", "total_area": "450"}]
        result = self._base_call(real_estate, cohort_stats=None)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any(r.severity == "HIGH" for r in cr6_flags)

    def test_cr6_absolute_dwelling_medium_no_cohort(self):
        """Absolute MEDIUM threshold (250–400 m2) still fires without cohort."""
        real_estate = [{"object_type": "Квартира", "total_area": "300"}]
        result = self._base_call(real_estate, cohort_stats=None)
        assert "CR6" in result.triggered_rules
        cr6_flags = [r for r in result.rule_results if r.rule_name == "CR6"]
        assert any(r.severity == "MEDIUM" for r in cr6_flags)

    def test_cr6_no_trigger_small_area_no_cohort(self):
        """Area below absolute thresholds does not trigger CR6 without cohort."""
        real_estate = [{"object_type": "Квартира", "total_area": "100"}]
        result = self._base_call(real_estate, cohort_stats=None)
        assert "CR6" not in result.triggered_rules


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
