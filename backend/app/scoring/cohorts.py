"""
Project Argus — Layer 2: Cohort-Based Statistical Scoring.

Compares each declarant's financial metrics to their peer group
(same post_type + declaration year) to detect statistical outliers.

Architecture:
    Pass 1: Build percentile distributions per cohort.
    Pass 2: Score each declaration relative to its cohort.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CohortKey(NamedTuple):
    """Grouping key for cohort-based analysis."""
    post_type: str
    year: int


@dataclass
class CohortStats:
    """Percentile distributions for a single cohort."""

    incomes: list[float] = field(default_factory=list)
    assets: list[float] = field(default_factory=list)
    cash_ratios: list[float] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.incomes)

    def freeze(self) -> None:
        """Sort all arrays so percentile lookups are O(log n)."""
        self.incomes.sort()
        self.assets.sort()
        self.cash_ratios.sort()


@dataclass
class CohortRuleResult:
    """Result from a single cohort scoring rule."""

    rule_name: str
    score: float
    triggered: bool
    explanation: str
    percentile: float | None = None


# ---------------------------------------------------------------------------
# Pass 1 — Build distributions
# ---------------------------------------------------------------------------

def build_cohort_distributions(
    summaries: list[dict[str, Any]],
    *,
    min_cohort_size: int = 5,
) -> dict[CohortKey, CohortStats]:
    """Build per-cohort statistical distributions from processed declarations.

    Parameters
    ----------
    summaries:
        List of dicts, each containing at minimum:
        ``post_type``, ``declaration_year``, ``total_income``,
        ``total_assets``, ``cash_ratio``.
    min_cohort_size:
        Cohorts smaller than this are dropped (too few for statistics).

    Returns
    -------
    Dictionary mapping ``CohortKey`` to frozen ``CohortStats``.
    """
    cohorts: dict[CohortKey, CohortStats] = {}

    for s in summaries:
        pt = s.get("post_type")
        yr = s.get("declaration_year")
        if not pt or not yr:
            continue

        key = CohortKey(post_type=str(pt), year=int(yr))
        if key not in cohorts:
            cohorts[key] = CohortStats()

        stats = cohorts[key]

        inc = s.get("total_income")
        if inc is not None:
            stats.incomes.append(float(inc))

        assets = s.get("total_assets")
        if assets is not None:
            stats.assets.append(float(assets))

        cr = s.get("cash_ratio")
        if cr is not None:
            stats.cash_ratios.append(float(cr))

    # Freeze (sort) and filter small cohorts
    result = {}
    for key, stats in cohorts.items():
        if stats.size >= min_cohort_size:
            stats.freeze()
            result[key] = stats
        else:
            logger.debug(
                "Cohort %s dropped: only %d members (min %d)",
                key, stats.size, min_cohort_size,
            )

    logger.info(
        "Built %d cohorts from %d declarations (%d dropped as too small).",
        len(result), len(summaries), len(cohorts) - len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Percentile computation
# ---------------------------------------------------------------------------

def compute_percentile_rank(value: float, distribution: list[float]) -> float:
    """Compute the percentile rank of *value* within a sorted *distribution*.

    Returns a float in [0.0, 1.0].  For example, 0.95 means the value
    is at the 95th percentile (higher than 95% of the distribution).
    """
    if not distribution:
        return 0.0
    pos = bisect.bisect_right(distribution, value)
    return pos / len(distribution)


def get_percentile_value(distribution: list[float], percentile: float) -> float:
    """Return the value at the given percentile in a sorted distribution."""
    if not distribution:
        return 0.0
    idx = int(len(distribution) * percentile)
    idx = min(idx, len(distribution) - 1)
    return distribution[idx]


# ---------------------------------------------------------------------------
# Pass 2 — Cohort scoring rules
# ---------------------------------------------------------------------------

def cohort_income_outlier(
    total_income: float | Decimal | None,
    cohort: CohortStats | None,
    *,
    threshold_percentile: float = 0.95,
) -> CohortRuleResult:
    """Flag declarants whose income is far above their cohort peers.

    Parameters
    ----------
    threshold_percentile:
        Percentile above which the income is flagged (default 95th).
    """
    rule = "cohort_income_outlier"

    if total_income is None or cohort is None or len(cohort.incomes) < 5:
        return CohortRuleResult(rule, 0.0, False, "Insufficient cohort data.")

    income = float(total_income)
    pct = compute_percentile_rank(income, cohort.incomes)
    p95 = get_percentile_value(cohort.incomes, threshold_percentile)

    if pct >= threshold_percentile:
        # Score scales from 0 at P95 to 1.0 at P99+
        score = min(1.0, (pct - threshold_percentile) / (1.0 - threshold_percentile))
        return CohortRuleResult(
            rule, round(score, 3), True,
            f"Income ({income:,.0f} UAH) is at the {pct:.0%} percentile "
            f"of cohort peers (P95 = {p95:,.0f} UAH).",
            percentile=round(pct, 3),
        )

    return CohortRuleResult(
        rule, 0.0, False,
        f"Income is at {pct:.0%} percentile of cohort peers.",
        percentile=round(pct, 3),
    )


def cohort_wealth_outlier(
    total_assets: float | Decimal | None,
    cohort: CohortStats | None,
    *,
    threshold_percentile: float = 0.95,
) -> CohortRuleResult:
    """Flag declarants whose total assets are far above their cohort peers."""
    rule = "cohort_wealth_outlier"

    if total_assets is None or cohort is None or len(cohort.assets) < 5:
        return CohortRuleResult(rule, 0.0, False, "Insufficient cohort data.")

    assets = float(total_assets)
    pct = compute_percentile_rank(assets, cohort.assets)
    p95 = get_percentile_value(cohort.assets, threshold_percentile)

    if pct >= threshold_percentile:
        score = min(1.0, (pct - threshold_percentile) / (1.0 - threshold_percentile))
        return CohortRuleResult(
            rule, round(score, 3), True,
            f"Assets ({assets:,.0f} UAH) at {pct:.0%} percentile "
            f"of cohort peers (P95 = {p95:,.0f} UAH).",
            percentile=round(pct, 3),
        )

    return CohortRuleResult(
        rule, 0.0, False,
        f"Assets at {pct:.0%} percentile of cohort peers.",
        percentile=round(pct, 3),
    )


# ---------------------------------------------------------------------------
# Combined Layer 2 scorer
# ---------------------------------------------------------------------------

def score_declaration_l2(
    *,
    total_income: float | Decimal | None,
    total_assets: float | Decimal | None,
    cohort: CohortStats | None,
) -> list[CohortRuleResult]:
    """Run all Layer 2 (cohort) scoring rules.

    Returns a list of rule results.  The caller is responsible for
    combining with Layer 1 scores.
    """
    return [
        cohort_income_outlier(total_income, cohort),
        cohort_wealth_outlier(total_assets, cohort),
    ]
