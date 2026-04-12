import pytest

from app.scoring.cohorts import (
    CohortStats,
    cohort_cash_ratio_outlier,
    cohort_confidential_ratio_outlier,
    cohort_dwelling_area_outlier,
    cohort_vehicle_count_outlier,
    score_declaration_l2,
)


def make_cohort(
    *,
    cash_ratios=None,
    confidential_ratios=None,
    dwelling_regions=None,
    vehicle_counts=None,
):
    cohort = CohortStats(
        cash_ratios=list(cash_ratios or []),
        confidential_ratios=list(confidential_ratios or []),
        vehicle_counts=list(vehicle_counts or []),
    )
    if dwelling_regions:
        cohort.dwelling_areas_by_region = {
            region: list(values) for region, values in dwelling_regions.items()
        }
    cohort.freeze()
    return cohort


class TestCohortCashRatioOutlier:
    @pytest.mark.parametrize(
        ("cash_ratio", "expected_severity"),
        [
            (0.72, "MEDIUM"),
            (0.87, "HIGH"),
        ],
    )
    def test_triggers_above_p90_plus_margin(self, cash_ratio, expected_severity):
        cohort = make_cohort(cash_ratios=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50])

        result = cohort_cash_ratio_outlier(cash_ratio, cohort)

        assert result.triggered
        assert result.severity == expected_severity

    def test_returns_false_below_threshold(self):
        cohort = make_cohort(cash_ratios=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50])

        result = cohort_cash_ratio_outlier(0.69, cohort)

        assert not result.triggered

    def test_returns_false_without_data(self):
        result = cohort_cash_ratio_outlier(0.90, None)

        assert not result.triggered


class TestCohortConfidentialRatioOutlier:
    @pytest.mark.parametrize(
        ("confidential_ratio", "expected_severity"),
        [
            (0.52, "MEDIUM"),
            (0.62, "HIGH"),
        ],
    )
    def test_triggers_above_p75(self, confidential_ratio, expected_severity):
        cohort = make_cohort(confidential_ratios=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50])

        result = cohort_confidential_ratio_outlier(confidential_ratio, cohort)

        assert result.triggered
        assert result.severity == expected_severity

    def test_returns_false_below_threshold(self):
        cohort = make_cohort(confidential_ratios=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50])

        result = cohort_confidential_ratio_outlier(0.39, cohort)

        assert not result.triggered

    def test_returns_false_without_data(self):
        result = cohort_confidential_ratio_outlier(0.50, make_cohort())

        assert not result.triggered


class TestCohortDwellingAreaOutlier:
    @pytest.mark.parametrize(
        ("dwelling_area_m2", "expected_severity"),
        [
            (300.0, "HIGH"),
            (285.0, "MEDIUM"),
        ],
    )
    def test_triggers_using_regional_distribution(self, dwelling_area_m2, expected_severity):
        cohort = make_cohort(
            dwelling_regions={
                "kyiv": [100.0 + i * 10.0 for i in range(20)],
            }
        )

        result = cohort_dwelling_area_outlier(dwelling_area_m2, cohort, primary_region="Kyiv")

        assert result.triggered
        assert result.severity == expected_severity

    def test_returns_false_below_threshold(self):
        cohort = make_cohort(
            dwelling_regions={
                "kyiv": [100.0 + i * 10.0 for i in range(20)],
            }
        )

        result = cohort_dwelling_area_outlier(270.0, cohort, primary_region="Kyiv")

        assert not result.triggered

    def test_returns_false_without_regional_data(self):
        cohort = make_cohort(
            dwelling_regions={
                "kyiv": [100.0 + i * 10.0 for i in range(20)],
            }
        )

        result = cohort_dwelling_area_outlier(300.0, cohort, primary_region="Lviv")

        assert not result.triggered


class TestCohortVehicleCountOutlier:
    def test_triggers_above_p90(self):
        cohort = make_cohort(vehicle_counts=[0, 0, 1, 1, 1, 2, 2, 3, 4, 5])

        result = cohort_vehicle_count_outlier(6, cohort)

        assert result.triggered
        assert result.severity == "MEDIUM"

    def test_returns_false_below_threshold(self):
        cohort = make_cohort(vehicle_counts=[0, 0, 1, 1, 1, 2, 2, 3, 4, 5])

        result = cohort_vehicle_count_outlier(4, cohort)

        assert not result.triggered

    def test_returns_false_without_data(self):
        result = cohort_vehicle_count_outlier(6, None)

        assert not result.triggered


class TestLayer2ScoringWiring:
    def test_score_declaration_l2_includes_new_rules(self):
        cohort = make_cohort(
            cash_ratios=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
            confidential_ratios=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
            dwelling_regions={
                "kyiv": [100.0 + i * 10.0 for i in range(20)],
            },
            vehicle_counts=[0, 0, 1, 1, 1, 2, 2, 3, 4, 5],
        )

        results = score_declaration_l2(
            cash_ratio=0.87,
            confidential_ratio=0.62,
            dwelling_area_m2=300.0,
            vehicle_count=6,
            cohort=cohort,
            primary_region="Kyiv",
        )

        by_name = {result.rule_name: result for result in results}

        assert by_name["cohort_cash_ratio_outlier"].triggered
        assert by_name["cohort_cash_ratio_outlier"].severity == "HIGH"
        assert by_name["cohort_confidential_ratio_outlier"].triggered
        assert by_name["cohort_confidential_ratio_outlier"].severity == "HIGH"
        assert by_name["cohort_dwelling_area_outlier"].triggered
        assert by_name["cohort_dwelling_area_outlier"].severity == "HIGH"
        assert by_name["cohort_vehicle_count_outlier"].triggered
        assert by_name["cohort_vehicle_count_outlier"].severity == "MEDIUM"


class TestLayer2RuleStubs:
    @pytest.mark.parametrize(
        "rule_name",
        [
            "cohort_cash_ratio_outlier",
            "cohort_confidential_ratio_outlier",
            "cohort_dwelling_area_outlier",
            "cohort_vehicle_count_outlier",
        ],
    )
    def test_new_rule_stub_present_in_output(self, rule_name):
        results = score_declaration_l2(
            cash_ratio=0.0,
            confidential_ratio=0.0,
            dwelling_area_m2=0.0,
            vehicle_count=0,
            cohort=None,
            primary_region="Kyiv",
        )

        by_name = {result.rule_name: result for result in results}

        assert rule_name in by_name
