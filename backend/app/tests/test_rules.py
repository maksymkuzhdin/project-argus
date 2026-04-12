from __future__ import annotations

import sys
import types
from decimal import Decimal

import pytest

if "scripts.train_layer3" not in sys.modules:
    scripts_pkg = types.ModuleType("scripts")
    train_layer3 = types.ModuleType("scripts.train_layer3")
    train_layer3.FEATURE_NAMES = []
    sys.modules.setdefault("scripts", scripts_pkg)
    sys.modules["scripts.train_layer3"] = train_layer3

from app.scoring.cohorts import CohortStats
from app.scoring.rules import (
    acquisition_income_mismatch,
    score_declaration,
    unexplained_wealth,
    unknown_value_frequency,
    zero_income_with_assets,
)


def _triggered_rule(result, rule_name: str):
    return next((r for r in result.rule_results if r.rule_name == rule_name and r.triggered), None)


def _cohort_with_confidential(confidential_ratios: list[float]) -> CohortStats:
    cohort = CohortStats(confidential_ratios=list(confidential_ratios))
    cohort.freeze()
    return cohort


class TestCR1CashToIncomeRatio:
    @pytest.mark.parametrize(
        ("ratio", "expected_severity"),
        [
            (3.2, "MEDIUM"),
            (5.2, "HIGH"),
            (10.5, "EXTREME"),
        ],
    )
    def test_fires_with_expected_severity_above_threshold(self, declaration_factory, ratio, expected_severity):
        income = Decimal("100000")
        payload = declaration_factory(
            total_income=income,
            cash_holdings=(income * Decimal(str(ratio))).quantize(Decimal("1")),
            bank_deposits=Decimal("1000000"),
        )

        result = score_declaration(**payload)

        cr1 = _triggered_rule(result, "CR1")
        assert cr1 is not None
        assert cr1.severity == expected_severity

    @pytest.mark.parametrize("ratio", [0.0, 2.99])
    def test_does_not_fire_below_threshold(self, declaration_factory, ratio):
        income = Decimal("100000")
        payload = declaration_factory(
            total_income=income,
            cash_holdings=(income * Decimal(str(ratio))).quantize(Decimal("1")),
            bank_deposits=Decimal("1000000"),
        )

        result = score_declaration(**payload)

        assert _triggered_rule(result, "CR1") is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"total_income": Decimal("0"), "cash_holdings": Decimal("50000")},
            {"total_income": None, "cash_holdings": Decimal("50000")},
            {"total_income": Decimal("100000"), "cash_holdings": None},
            {"total_income": Decimal("100000"), "cash_holdings": Decimal("50000"), "incomes": None, "monetary_assets": None, "real_estate": None, "vehicles": None},
        ],
    )
    def test_edge_cases_do_not_raise(self, declaration_factory, overrides):
        payload = declaration_factory(**overrides)

        result = score_declaration(**payload)

        assert result is not None


class TestCR2FxCashToIncome:
    @pytest.fixture(autouse=True)
    def patch_to_uah(self, monkeypatch):
        monkeypatch.setattr(
            "app.scoring.rules.to_uah",
            lambda amount, _currency: Decimal(str(amount)) if amount is not None else None,
        )

    @pytest.mark.parametrize(
        ("fx_cash", "uah_cash", "income", "expected_severity"),
        [
            (Decimal("420"), Decimal("80"), Decimal("100"), "HIGH"),
            (Decimal("180"), Decimal("120"), Decimal("90"), "MEDIUM"),
        ],
    )
    def test_fires_with_expected_severity_above_threshold(
        self,
        declaration_factory,
        fx_cash,
        uah_cash,
        income,
        expected_severity,
    ):
        payload = declaration_factory(
            total_income=income,
            monetary_assets=[
                {"asset_type": "Готівка", "amount": fx_cash, "currency_code": "USD", "person_ref": "1"},
                {"asset_type": "Готівка", "amount": uah_cash, "currency_code": "UAH", "person_ref": "1"},
            ],
        )

        result = score_declaration(**payload)

        cr2 = _triggered_rule(result, "CR2")
        assert cr2 is not None
        assert cr2.severity == expected_severity

    @pytest.mark.parametrize(
        ("fx_cash", "uah_cash", "income"),
        [
            (Decimal("120"), Decimal("180"), Decimal("100")),
            (Decimal("40"), Decimal("40"), Decimal("100")),
        ],
    )
    def test_does_not_fire_below_threshold(self, declaration_factory, fx_cash, uah_cash, income):
        payload = declaration_factory(
            total_income=income,
            monetary_assets=[
                {"asset_type": "Готівка", "amount": fx_cash, "currency_code": "USD", "person_ref": "1"},
                {"asset_type": "Готівка", "amount": uah_cash, "currency_code": "UAH", "person_ref": "1"},
            ],
        )

        result = score_declaration(**payload)

        assert _triggered_rule(result, "CR2") is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"total_income": Decimal("0"), "monetary_assets": [{"asset_type": "Готівка", "amount": Decimal("300"), "currency_code": "USD"}]},
            {"total_income": None, "monetary_assets": [{"asset_type": "Готівка", "amount": Decimal("300"), "currency_code": "USD"}]},
            {"monetary_assets": [{"asset_type": "Готівка", "amount": None, "currency_code": "USD"}]},
            {"monetary_assets": [{"asset_type": None, "amount": Decimal("200"), "currency_code": None}]},
        ],
    )
    def test_edge_cases_do_not_raise(self, declaration_factory, overrides):
        payload = declaration_factory(**overrides)

        result = score_declaration(**payload)

        assert result is not None


class TestCR3AcquisitionIncomeRatio:
    @pytest.mark.parametrize(
        ("ratio", "expected_severity"),
        [
            (2.2, "MEDIUM"),
            (3.2, "HIGH"),
            (7.2, "EXTREME"),
        ],
    )
    def test_fires_with_expected_severity_above_threshold(self, declaration_factory, ratio, expected_severity):
        income = Decimal("100000")
        cost = (income * Decimal(str(ratio))).quantize(Decimal("1"))
        payload = declaration_factory(
            total_income=income,
            real_estate=[{"cost_assessment": cost, "owning_date": "2024"}],
            declaration_year=2024,
        )

        result = score_declaration(**payload)

        cr3 = _triggered_rule(result, "CR3")
        assert cr3 is not None
        assert cr3.severity == expected_severity

    @pytest.mark.parametrize("ratio", [0.0, 1.99])
    def test_does_not_fire_below_threshold(self, declaration_factory, ratio):
        income = Decimal("100000")
        cost = (income * Decimal(str(ratio))).quantize(Decimal("1"))
        payload = declaration_factory(
            total_income=income,
            real_estate=[{"cost_assessment": cost, "owning_date": "2024"}],
            declaration_year=2024,
        )

        result = score_declaration(**payload)

        assert _triggered_rule(result, "CR3") is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"total_income": Decimal("0"), "real_estate": [{"cost_assessment": Decimal("300000"), "owning_date": "2024"}]},
            {"total_income": None, "real_estate": [{"cost_assessment": Decimal("300000"), "owning_date": "2024"}]},
            {"real_estate": [{"cost_assessment": None, "owning_date": "2024"}]},
            {"real_estate": [{"cost_assessment": Decimal("300000"), "owning_date": None}]},
        ],
    )
    def test_edge_cases_do_not_raise(self, declaration_factory, overrides):
        payload = declaration_factory(**overrides)

        result = score_declaration(**payload)

        assert result is not None


class TestBR1UnexplainedWealth:
    @pytest.mark.parametrize(
        ("income", "assets", "triggered"),
        [
            (Decimal("100000"), Decimal("350000"), True),
            (Decimal("100000"), Decimal("299000"), False),
        ],
    )
    def test_threshold_boundary_cases(self, income, assets, triggered):
        result = unexplained_wealth(income, assets)

        assert result.triggered is triggered

    @pytest.mark.parametrize(
        "income,assets",
        [
            (Decimal("0"), Decimal("500000")),
            (None, Decimal("500000")),
            (Decimal("100000"), None),
        ],
    )
    def test_edge_cases_do_not_raise(self, income, assets):
        result = unexplained_wealth(income, assets)

        assert result is not None


class TestBR2AssetIncomeMismatch:
    @pytest.mark.parametrize(
        ("cost", "income", "triggered"),
        [
            (Decimal("160000"), Decimal("100000"), True),
            (Decimal("149000"), Decimal("100000"), False),
        ],
    )
    def test_threshold_boundary_cases(self, cost, income, triggered):
        result = acquisition_income_mismatch(cost, income)

        assert result.triggered is triggered

    @pytest.mark.parametrize(
        "cost,income",
        [
            (Decimal("100000"), Decimal("0")),
            (None, Decimal("100000")),
            (Decimal("100000"), None),
        ],
    )
    def test_edge_cases_do_not_raise(self, cost, income):
        result = acquisition_income_mismatch(cost, income)

        assert result is not None


class TestBR3ZeroIncomeWithAssets:
    @pytest.mark.parametrize(
        ("income", "assets", "triggered"),
        [
            (Decimal("0"), Decimal("120000"), True),
            (Decimal("0"), Decimal("99000"), False),
            (Decimal("1000"), Decimal("500000"), False),
        ],
    )
    def test_threshold_boundary_cases(self, income, assets, triggered):
        result = zero_income_with_assets(income, assets)

        assert result.triggered is triggered

    @pytest.mark.parametrize(
        "income,assets",
        [
            (None, Decimal("100000")),
            (Decimal("0"), None),
        ],
    )
    def test_edge_cases_do_not_raise(self, income, assets):
        result = zero_income_with_assets(income, assets)

        assert result is not None


class TestTQ1UnknownValueFields:
    @pytest.mark.parametrize(
        ("total_fields", "unknown_fields", "triggered"),
        [
            (10, 6, True),
            (10, 5, False),
            (3, 3, False),
        ],
    )
    def test_threshold_boundary_cases(self, total_fields, unknown_fields, triggered):
        result = unknown_value_frequency(total_fields, unknown_fields)

        assert result.triggered is triggered

    @pytest.mark.parametrize(
        "total_fields,unknown_fields",
        [
            (0, 0),
            (10, 0),
            (10, 10),
        ],
    )
    def test_edge_cases_do_not_raise(self, total_fields, unknown_fields):
        result = unknown_value_frequency(total_fields, unknown_fields)

        assert result is not None


class TestTQ2ConfidentialFieldsRatio:
    @pytest.mark.parametrize(
        ("incomes", "expected_severity"),
        [
            ([{"amount_status": "confidential"}, {"amount_status": "ok"}, {"amount_status": "ok"}, {"amount_status": "ok"}], "LOW"),
            ([{"amount_status": "confidential"}, {"amount_status": "confidential"}, {"amount_status": "ok"}, {"amount_status": "ok"}], "MEDIUM"),
        ],
    )
    def test_fires_with_expected_severity_above_threshold(self, declaration_factory, incomes, expected_severity):
        cohort = _cohort_with_confidential([0.05, 0.08, 0.10, 0.12, 0.15])
        payload = declaration_factory(
            incomes=incomes,
            cohort_stats=cohort,
        )

        result = score_declaration(**payload)

        br3 = _triggered_rule(result, "BR3")
        assert br3 is not None
        assert br3.severity == expected_severity

    def test_does_not_fire_below_threshold(self, declaration_factory):
        cohort = _cohort_with_confidential([0.05, 0.08, 0.10, 0.12, 0.15])
        payload = declaration_factory(
            incomes=[
                {"amount_status": "confidential"},
                {"amount_status": "ok"},
                {"amount_status": "ok"},
                {"amount_status": "ok"},
                {"amount_status": "ok"},
            ],
            cohort_stats=cohort,
        )

        result = score_declaration(**payload)

        assert _triggered_rule(result, "BR3") is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"incomes": [{"amount_status": None}, {}], "cohort_stats": _cohort_with_confidential([0.05, 0.08, 0.10, 0.12, 0.15])},
            {"incomes": [{"amount_status": "confidential"}], "cohort_stats": None},
            {"incomes": [], "cohort_stats": _cohort_with_confidential([0.05, 0.08, 0.10, 0.12, 0.15])},
        ],
    )
    def test_edge_cases_do_not_raise(self, declaration_factory, overrides):
        payload = declaration_factory(**overrides)

        result = score_declaration(**payload)

        assert result is not None
