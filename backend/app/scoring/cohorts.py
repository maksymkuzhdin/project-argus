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
    confidential_ratios: list[float] = field(default_factory=list)
    dwelling_areas: list[float] = field(default_factory=list)
    agri_areas: list[float] = field(default_factory=list)
    dwelling_areas_by_region: dict[str, list[float]] = field(default_factory=dict)
    agri_areas_by_region: dict[str, list[float]] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.incomes)

    def freeze(self) -> None:
        """Sort all arrays so percentile lookups are O(log n)."""
        self.incomes.sort()
        self.assets.sort()
        self.cash_ratios.sort()
        self.confidential_ratios.sort()
        self.dwelling_areas.sort()
        self.agri_areas.sort()
        for distribution in self.dwelling_areas_by_region.values():
            distribution.sort()
        for distribution in self.agri_areas_by_region.values():
            distribution.sort()


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

        conf = s.get("confidential_ratio")
        if conf is not None:
            stats.confidential_ratios.append(float(conf))

        dwelling_area = s.get("dwelling_area_m2")
        if dwelling_area is None:
            dwelling_area = s.get("dwelling_area")
        dwelling_f = float(dwelling_area) if dwelling_area is not None else None
        if dwelling_f is not None:
            stats.dwelling_areas.append(dwelling_f)

        agri_area = s.get("agri_area_m2")
        if agri_area is None:
            agri_area = s.get("agri_area")
        agri_f = float(agri_area) if agri_area is not None else None
        if agri_f is not None:
            stats.agri_areas.append(agri_f)

        region = str(s.get("primary_region") or "").strip().lower()
        if region:
            if dwelling_f is not None:
                stats.dwelling_areas_by_region.setdefault(region, []).append(dwelling_f)
            if agri_f is not None:
                stats.agri_areas_by_region.setdefault(region, []).append(agri_f)

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


def cohort_cash_ratio_outlier(
    cash_ratio: float | None,
    cohort: CohortStats | None,
    *,
    threshold_percentile: float = 0.90,
) -> CohortRuleResult:
    """Flag declarants whose cash ratio is far above their cohort peers.

    Parameters
    ----------
    cash_ratio:
        Ratio of cash to (cash + bank deposits).
    threshold_percentile:
        Percentile above which the ratio is flagged (default 90th).
    """
    rule = "cohort_cash_ratio_outlier"

    if cash_ratio is None or cohort is None or len(cohort.cash_ratios) < 5:
        return CohortRuleResult(rule, 0.0, False, "Insufficient cohort data.")

    ratio = float(cash_ratio)
    pct = compute_percentile_rank(ratio, cohort.cash_ratios)
    p90 = get_percentile_value(cohort.cash_ratios, threshold_percentile)

    if pct >= threshold_percentile:
        # Score scales from 0 at P90 to 1.0 at P99+
        score = min(1.0, (pct - threshold_percentile) / (1.0 - threshold_percentile))
        return CohortRuleResult(
            rule, round(score, 3), True,
            f"Cash ratio ({ratio:.1%}) at {pct:.0%} percentile "
            f"of cohort peers (P90 = {p90:.1%}).",
            percentile=round(pct, 3),
        )

    return CohortRuleResult(
        rule, 0.0, False,
        f"Cash ratio at {pct:.0%} percentile of cohort peers.",
        percentile=round(pct, 3),
    )


def cohort_confidential_ratio_outlier(
    confidential_ratio: float | None,
    cohort: CohortStats | None,
    *,
    threshold_percentile: float = 0.85,
) -> CohortRuleResult:
    """Flag declarants whose confidential_ratio is far above their cohort peers.

    Parameters
    ----------
    confidential_ratio:
        Share of value fields marked as confidential or redacted.
    threshold_percentile:
        Percentile above which the ratio is flagged (default 85th).
    """
    rule = "cohort_confidential_ratio_outlier"

    if confidential_ratio is None or cohort is None or len(cohort.confidential_ratios) < 5:
        return CohortRuleResult(rule, 0.0, False, "Insufficient cohort data.")

    ratio = float(confidential_ratio)
    pct = compute_percentile_rank(ratio, cohort.confidential_ratios)
    p85 = get_percentile_value(cohort.confidential_ratios, threshold_percentile)

    if pct >= threshold_percentile:
        score = min(1.0, (pct - threshold_percentile) / (1.0 - threshold_percentile))
        return CohortRuleResult(
            rule, round(score, 3), True,
            f"Confidential density ({ratio:.1%}) at {pct:.0%} percentile "
            f"of cohort peers (P85 = {p85:.1%}).",
            percentile=round(pct, 3),
        )

    return CohortRuleResult(
        rule, 0.0, False,
        f"Confidential density at {pct:.0%} percentile of cohort peers.",
        percentile=round(pct, 3),
    )


def cohort_dwelling_area_outlier(
    dwelling_area_m2: float | None,
    cohort: CohortStats | None,
    *,
    threshold_percentile: float = 0.95,
) -> CohortRuleResult:
    """Flag declarants whose dwelling area is far above their cohort peers.

    Parameters
    ----------
    dwelling_area_m2:
        Total housing area in square meters.
    threshold_percentile:
        Percentile above which the area is flagged (default 95th).
    """
    rule = "cohort_dwelling_area_outlier"

    if dwelling_area_m2 is None or cohort is None or len(cohort.dwelling_areas) < 5:
        return CohortRuleResult(rule, 0.0, False, "Insufficient cohort data.")

    area = float(dwelling_area_m2)
    pct = compute_percentile_rank(area, cohort.dwelling_areas)
    p95 = get_percentile_value(cohort.dwelling_areas, threshold_percentile)

    if pct >= threshold_percentile:
        score = min(1.0, (pct - threshold_percentile) / (1.0 - threshold_percentile))
        return CohortRuleResult(
            rule, round(score, 3), True,
            f"Dwelling area ({area:.0f} m²) at {pct:.0%} percentile "
            f"of cohort peers (P95 = {p95:.0f} m²).",
            percentile=round(pct, 3),
        )

    return CohortRuleResult(
        rule, 0.0, False,
        f"Dwelling area at {pct:.0%} percentile of cohort peers.",
        percentile=round(pct, 3),
    )


def cohort_agri_area_outlier(
    agri_area_m2: float | None,
    cohort: CohortStats | None,
    *,
    threshold_percentile: float = 0.95,
) -> CohortRuleResult:
    """Flag declarants whose agricultural area is far above their cohort peers.

    Parameters
    ----------
    agri_area_m2:
        Total agricultural area in square meters.
    threshold_percentile:
        Percentile above which the area is flagged (default 95th).
    """
    rule = "cohort_agri_area_outlier"

    if agri_area_m2 is None or cohort is None or len(cohort.agri_areas) < 5:
        return CohortRuleResult(rule, 0.0, False, "Insufficient cohort data.")

    area = float(agri_area_m2)
    pct = compute_percentile_rank(area, cohort.agri_areas)
    p95 = get_percentile_value(cohort.agri_areas, threshold_percentile)

    if pct >= threshold_percentile:
        score = min(1.0, (pct - threshold_percentile) / (1.0 - threshold_percentile))
        return CohortRuleResult(
            rule, round(score, 3), True,
            f"Agricultural area ({area:.0f} m²) at {pct:.0%} percentile "
            f"of cohort peers (P95 = {p95:.0f} m²).",
            percentile=round(pct, 3),
        )

    return CohortRuleResult(
        rule, 0.0, False,
        f"Agricultural area at {pct:.0%} percentile of cohort peers.",
        percentile=round(pct, 3),
    )

# ---------------------------------------------------------------------------
# Combined Layer 2 scorer
# ---------------------------------------------------------------------------

def score_declaration_l2(
    *,
    total_income: float | Decimal | None = None,
    total_assets: float | Decimal | None = None,
    cash_ratio: float | None = None,
    confidential_ratio: float | None = None,
    dwelling_area_m2: float | None = None,
    agri_area_m2: float | None = None,
    cohort: CohortStats | None = None,  # Deprecated fallback for backward compatibility
    # Multi-dimensional cohort support (Task 4a)
    year: int | None = None,
    sector: str | None = None,
    government_level: str | None = None,
    primary_region: str | None = None,
    cohort_resolver: "CohortFallbackResolver | None" = None,
) -> list[CohortRuleResult]:
    """Run all Layer 2 (cohort) scoring rules with optional multi-dimensional support.

    If cohort_resolver is provided, uses multi-dimensional cohorts with fallback chain.
    Otherwise, falls back to the legacy `cohort` parameter (deprecated).

    Parameters
    ----------
    total_income, total_assets, cash_ratio, confidential_ratio, dwelling_area_m2, agri_area_m2:
        Feature values to score.
    cohort:
        Deprecated. Legacy single CohortStats object.
    year, sector, government_level, primary_region:
        Cohort dimensions. Used with cohort_resolver.
    cohort_resolver:
        Optional CohortFallbackResolver for multi-dimensional cohort selection.

    Returns
    -------
    List of CohortRuleResult objects.
    """
    results = []
    
    # Determine which cohort to use for income/assets
    income_assets_cohort = None
    income_assets_key = None
    if cohort_resolver and year and sector and government_level:
        # Use multi-dimensional resolver (Task 4b)
        income_assets_key, _ = cohort_resolver.resolve_for_income_assets(
            year, sector, government_level
        )
        if income_assets_key:
            income_assets_cohort = cohort_resolver.get_cohort(income_assets_key)
    else:
        # Fall back to legacy cohort parameter
        income_assets_cohort = cohort
    
    # Determine which cohort to use for area features (region-sensitive)
    area_cohort = None
    area_key = None
    if cohort_resolver and year and sector and government_level:
        # Use region-sensitive resolution (Task 4b)
        area_key, _ = cohort_resolver.resolve_for_area(
            year, sector, government_level, primary_region
        )
        if area_key:
            area_cohort = cohort_resolver.get_cohort(area_key)
    else:
        area_cohort = cohort
    
    # Task 4c: Run all rules with optional cohort keys in explanation (4d)
    income_rule = cohort_income_outlier(total_income, income_assets_cohort)
    if income_assets_key and income_rule.triggered:
        # Append cohort key info to explanation
        income_rule.explanation += f" [cohort: {income_assets_key}]"
    results.append(income_rule)
    
    wealth_rule = cohort_wealth_outlier(total_assets, income_assets_cohort)
    if income_assets_key and wealth_rule.triggered:
        wealth_rule.explanation += f" [cohort: {income_assets_key}]"
    results.append(wealth_rule)
    
    # New rules
    cash_rule = cohort_cash_ratio_outlier(cash_ratio, income_assets_cohort)
    if income_assets_key and cash_rule.triggered:
        cash_rule.explanation += f" [cohort: {income_assets_key}]"
    results.append(cash_rule)
    
    conf_rule = cohort_confidential_ratio_outlier(confidential_ratio, income_assets_cohort)
    if income_assets_key and conf_rule.triggered:
        conf_rule.explanation += f" [cohort: {income_assets_key}]"
    results.append(conf_rule)
    
    dwelling_rule = cohort_dwelling_area_outlier(dwelling_area_m2, area_cohort)
    if area_key and dwelling_rule.triggered:
        dwelling_rule.explanation += f" [cohort: {area_key}]"
    results.append(dwelling_rule)
    
    agri_rule = cohort_agri_area_outlier(agri_area_m2, area_cohort)
    if area_key and agri_rule.triggered:
        agri_rule.explanation += f" [cohort: {area_key}]"
    results.append(agri_rule)
    
    return results


# ============================================================================
# Multi-dimensional Cohort Infrastructure (Ukraine-specific taxonomy)
# ============================================================================

class MultiDimensionalCohortKey(NamedTuple):
    """Multi-dimensional cohort key with sector, government level, region."""
    year: int
    sector: str
    government_level: str
    region: str | None = None  # Optional, for area-based features


@dataclass
class AuditTrail:
    """Track fallback chain usage and normalization confidence."""
    declarant_id: str
    original_cohort_key: MultiDimensionalCohortKey
    used_cohort_key: str  # The key actually used (may have fallen back)
    reason: str = ""
    role_family_confidence: float = 1.0
    institution_family_confidence: float = 1.0
    feature_type: str = ""  # income, assets, dwelling_area, agri_area, etc.


def build_multi_dimensional_cohorts(
    summaries: list[dict[str, Any]],
    *,
    min_cohort_size: int = 30,
) -> dict[str, CohortStats]:
    """Build multi-dimensional cohort distributions (sector, government_level, region).

    This extends the basic (post_type, year) cohort building to support
    new normalized dimensions from TaxonomyNormalizer output.

    Parameters
    ----------
    summaries:
        List of dicts with (at minimum):
        ``year``, ``sector``, ``government_level``, ``primary_region``,
        ``total_income``, ``total_assets``, ``cash_ratio``,
        ``confidential_ratio``, ``dwelling_area_m2``, ``agri_area_m2``
    min_cohort_size:
        Cohorts with fewer members are dropped.

    Returns
    -------
    Dict mapping cohort key string (e.g., "2024_healthcare_central") to CohortStats.
    """
    cohorts: dict[str, CohortStats] = {}

    for s in summaries:
        year = s.get("year")
        sector = s.get("sector", "other")
        govt_level = s.get("government_level", "other")
        primary_region = s.get("primary_region")

        if not year:
            continue

        # Build cohort key (without region for income/assets metrics)
        key_income = f"{year}_{sector}_{govt_level}"
        if key_income not in cohorts:
            cohorts[key_income] = CohortStats()

        stats = cohorts[key_income]

        inc = s.get("total_income")
        if inc is not None:
            stats.incomes.append(float(inc))

        assets = s.get("total_assets")
        if assets is not None:
            stats.assets.append(float(assets))

        cr = s.get("cash_ratio")
        if cr is not None:
            stats.cash_ratios.append(float(cr))

        conf = s.get("confidential_ratio")
        if conf is not None:
            stats.confidential_ratios.append(float(conf))

        # Area metrics: also regional breakdowns
        dwelling_area = s.get("dwelling_area_m2") or s.get("dwelling_area")
        dwelling_f = float(dwelling_area) if dwelling_area is not None else None
        if dwelling_f is not None:
            stats.dwelling_areas.append(dwelling_f)

        agri_area = s.get("agri_area_m2") or s.get("agri_area")
        agri_f = float(agri_area) if agri_area is not None else None
        if agri_f is not None:
            stats.agri_areas.append(agri_f)

        # Regional breakdowns for area metrics
        region = str(primary_region or "").strip().lower()
        if region:
            if dwelling_f is not None:
                stats.dwelling_areas_by_region.setdefault(region, []).append(dwelling_f)
            if agri_f is not None:
                stats.agri_areas_by_region.setdefault(region, []).append(agri_f)

    # Freeze (sort) and filter small cohorts
    result = {}
    for key, stats in cohorts.items():
        if stats.size >= min_cohort_size:
            stats.freeze()
            result[key] = stats
        else:
            logger.debug(
                "Multi-dimensional cohort %s dropped: only %d members (min %d)",
                key, stats.size, min_cohort_size,
            )

    logger.info(
        "Built %d multi-dimensional cohorts from %d declarations (%d dropped as too small).",
        len(result), len(summaries), len(cohorts) - len(result),
    )
    return result


class CohortFallbackResolver:
    """Resolve cohort keys using fallback hierarchy when cohort is too small.

    Supports two fallback chains:
      - Income/assets: year+sector+government_level → year+sector → year → global
      - Area (region-sensitive): year+sector+government_level+region → year+sector+government_level → ...
    """

    def __init__(self, cohort_stats: dict[str, CohortStats], min_cohort_size: int = 30):
        """Initialize resolver with built cohorts.

        Parameters
        ----------
        cohort_stats:
            Dict of cohort_key → CohortStats (from build_multi_dimensional_cohorts)
        min_cohort_size:
            Threshold for considering a cohort "too small"
        """
        self.cohort_stats = cohort_stats
        self.min_cohort_size = min_cohort_size
        self.fallback_log: list[AuditTrail] = []

    def resolve_for_income_assets(
        self,
        year: int,
        sector: str,
        government_level: str,
    ) -> tuple[str | None, list[str]]:
        """Resolve cohort key for income/assets features using fallback chain.

        Parameters
        ----------
        year, sector, government_level:
            Cohort dimensions

        Returns
        -------
        (selected_cohort_key, fallback_chain)
            selected_cohort_key: The key to use (or None if no cohort found)
            fallback_chain: List of keys tried in order
        """
        chain = [
            f"{year}_{sector}_{government_level}",
            f"{year}_{sector}",
            f"{year}",
            "global",
        ]

        for key in chain:
            stats = self.cohort_stats.get(key)
            if stats and stats.size >= self.min_cohort_size:
                return key, chain
            # If key is "global", always use it as final fallback even if small
            if key == "global":
                return key, chain

        return None, chain

    def resolve_for_area(
        self,
        year: int,
        sector: str,
        government_level: str,
        primary_region: str | None = None,
    ) -> tuple[str | None, list[str]]:
        """Resolve cohort key for area features using region-sensitive fallback chain.

        Parameters
        ----------
        year, sector, government_level, primary_region:
            Cohort dimensions

        Returns
        -------
        (selected_cohort_key, fallback_chain)
        """
        chain = []
        if primary_region and primary_region.strip():
            region_lower = primary_region.lower().strip()
            chain.append(f"{year}_{sector}_{government_level}_{region_lower}")

        chain.extend([
            f"{year}_{sector}_{government_level}",
            f"{year}_{sector}",
            f"{year}",
            "global",
        ])

        for key in chain:
            stats = self.cohort_stats.get(key)
            if stats and stats.size >= self.min_cohort_size:
                return key, chain
            if key == "global":
                return key, chain

        return None, chain

    def get_cohort(self, cohort_key: str) -> CohortStats | None:
        """Retrieve CohortStats for a given key (including synthetic "global" key)."""
        if cohort_key == "global":
            # Return a synthetic global cohort with all data
            return self._build_global_cohort()
        return self.cohort_stats.get(cohort_key)

    def _build_global_cohort(self) -> CohortStats | None:
        """Build synthetic global cohort from all existing cohorts."""
        if not self.cohort_stats:
            return None

        global_stats = CohortStats()
        for stats in self.cohort_stats.values():
            global_stats.incomes.extend(stats.incomes)
            global_stats.assets.extend(stats.assets)
            global_stats.cash_ratios.extend(stats.cash_ratios)
            global_stats.confidential_ratios.extend(stats.confidential_ratios)
            global_stats.dwelling_areas.extend(stats.dwelling_areas)
            global_stats.agri_areas.extend(stats.agri_areas)

            for region, values in stats.dwelling_areas_by_region.items():
                global_stats.dwelling_areas_by_region.setdefault(region, []).extend(values)
            for region, values in stats.agri_areas_by_region.items():
                global_stats.agri_areas_by_region.setdefault(region, []).extend(values)

        if global_stats.size > 0:
            global_stats.freeze()
            return global_stats

        return None

    def log_fallback(self, trail: AuditTrail) -> None:
        """Log a fallback usage for auditing."""
        self.fallback_log.append(trail)
