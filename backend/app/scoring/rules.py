"""Project Argus scoring rules.

This module implements deterministic declaration scoring and timeline scoring,
including:

- data-quality checks (TQ*),
- corruption/opacity checks (CR*/BR*) at declaration level,
- timeline rules for multi-year behavior,
- optional cohort-aware checks when cohort stats are provided.

For the canonical implementation matrix and deferred items, see
``docs/declaration-rules-and-checks.md``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.config import settings
from app.normalization.currency import to_uah
from app.scoring import layer3 as layer3_inference
from app.scoring.cohorts import compute_percentile_rank, get_percentile_value, score_declaration_l2
from app.scoring.tuning import config_value, load_scoring_config


SCORING_CONFIG = load_scoring_config()


def _cfg(*path: str, default: Any) -> Any:
    return config_value(SCORING_CONFIG, *path, default=default)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RuleResult:
    """Output of a single scoring rule."""

    rule_name: str
    score: float
    triggered: bool
    explanation: str
    category: str | None = None
    severity: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Rule 1 — Unexplained wealth proxy
# ---------------------------------------------------------------------------

def unexplained_wealth(
    total_income: Decimal | None,
    total_assets: Decimal | None,
    *,
    threshold_ratio: float = _cfg(
        "layer1", "legacy", "unexplained_wealth", "threshold_ratio", default=3.0
    ),
) -> RuleResult:
    """Flag when total declared assets significantly exceed total income.

    Parameters
    ----------
    total_income:
        Sum of all step_11 income entries (in a common currency).
    total_assets:
        Sum of all step_12 monetary assets + step_3 cost assessments.
    threshold_ratio:
        Assets-to-income ratio above which the rule triggers.
    """
    rule = "unexplained_wealth"

    if total_income is None or total_assets is None:
        return RuleResult(rule, 0.0, False, "Insufficient data to assess.")

    if total_income <= 0:
        if total_assets > 0:
            return RuleResult(
                rule, 1.0, True,
                f"Declared assets ({total_assets:,.0f}) with zero or negative income."
            )
        return RuleResult(rule, 0.0, False, "No income and no assets declared.")

    ratio = float(total_assets / total_income)
    if ratio > threshold_ratio:
        score = min(1.0, (ratio - threshold_ratio) / threshold_ratio)
        return RuleResult(
            rule, round(score, 3), True,
            f"Asset-to-income ratio is {ratio:.1f}x "
            f"(assets {total_assets:,.0f} vs income {total_income:,.0f}), "
            f"exceeding {threshold_ratio}x threshold."
        )

    return RuleResult(
        rule, 0.0, False,
        f"Asset-to-income ratio is {ratio:.1f}x, within normal range."
    )


# ---------------------------------------------------------------------------
# Rule 2 — Cash-to-bank ratio
# ---------------------------------------------------------------------------

def cash_to_bank_ratio(
    cash_holdings: Decimal | None,
    bank_deposits: Decimal | None,
    *,
    threshold: float = _cfg(
        "layer1", "legacy", "cash_to_bank_ratio", "threshold", default=0.8
    ),
) -> RuleResult:
    """Flag when cash holdings dominate financial assets.

    Parameters
    ----------
    cash_holdings:
        Total cash from step_12 items where objectType indicates cash.
    bank_deposits:
        Total from step_12 items where objectType indicates bank deposits,
        or from step_17 bank accounts.
    threshold:
        Cash share above which the rule triggers.
    """
    rule = "cash_to_bank_ratio"

    if cash_holdings is None and bank_deposits is None:
        return RuleResult(rule, 0.0, False, "No monetary assets declared.")

    cash = cash_holdings or Decimal(0)
    bank = bank_deposits or Decimal(0)
    total = cash + bank

    if total <= 0:
        return RuleResult(rule, 0.0, False, "No monetary assets declared.")

    ratio = float(cash / total)
    if ratio > threshold:
        score = min(1.0, (ratio - threshold) / (1.0 - threshold))
        return RuleResult(
            rule, round(score, 3), True,
            f"Cash is {ratio:.0%} of total monetary assets "
            f"(cash {cash:,.0f} vs bank {bank:,.0f}), "
            f"exceeding {threshold:.0%} threshold."
        )

    return RuleResult(
        rule, 0.0, False,
        f"Cash is {ratio:.0%} of total monetary assets, within normal range."
    )


# ---------------------------------------------------------------------------
# Rule 3 — Unknown / unavailable value frequency
# ---------------------------------------------------------------------------

def unknown_value_frequency(
    total_fields: int,
    unknown_fields: int,
    *,
    threshold: float = _cfg(
        "layer1", "legacy", "unknown_value_frequency", "threshold", default=0.5
    ),
    min_fields: int = _cfg(
        "layer1", "legacy", "unknown_value_frequency", "min_fields", default=4
    ),
) -> RuleResult:
    """Flag when too many declaration fields use placeholder values.

    Parameters
    ----------
    total_fields:
        Total number of checked value fields.
    unknown_fields:
        Number of fields with status ``unknown``, ``family_no_info``,
        or ``confidential`` (beyond standard PII redaction).
    threshold:
        Fraction above which the rule triggers (default raised to 0.5
        because 30–40% placeholder rates are common in legitimate
        Ukrainian declarations).
    min_fields:
        Minimum number of value fields required for the rule to fire.
        Prevents declarations with very few fields (e.g. 2 of 2 unknown)
        from receiving disproportionately high scores.
    """
    rule = "unknown_value_frequency"

    if total_fields < min_fields:
        return RuleResult(
            rule, 0.0, False,
            f"Too few value fields ({total_fields}) for reliable assessment."
        )

    freq = unknown_fields / total_fields
    if freq > threshold:
        score = min(1.0, (freq - threshold) / (1.0 - threshold))
        return RuleResult(
            rule, round(score, 3), True,
            f"{unknown_fields} of {total_fields} value fields "
            f"({freq:.0%}) are marked unknown or unavailable, "
            f"exceeding {threshold:.0%} threshold."
        )

    return RuleResult(
        rule, 0.0, False,
        f"{freq:.0%} of value fields are unknown, within normal range."
    )


# ---------------------------------------------------------------------------
# Rule 4 — Large acquisition vs declared income mismatch
# ---------------------------------------------------------------------------

def acquisition_income_mismatch(
    largest_acquisition_cost: Decimal | None,
    total_income: Decimal | None,
    *,
    threshold_ratio: float = _cfg(
        "layer1", "legacy", "acquisition_income_mismatch", "threshold_ratio", default=1.5
    ),
) -> RuleResult:
    """Flag when a single real-estate acquisition exceeds declared income.

    Parameters
    ----------
    largest_acquisition_cost:
        The highest ``cost_date_assessment`` from step_3 entries.
    total_income:
        Sum of all step_11 income entries.
    threshold_ratio:
        Cost-to-income ratio above which the rule triggers.
    """
    rule = "acquisition_income_mismatch"

    if largest_acquisition_cost is None or total_income is None:
        return RuleResult(rule, 0.0, False, "Insufficient data to assess.")

    if total_income <= 0:
        if largest_acquisition_cost > 0:
            return RuleResult(
                rule, 1.0, True,
                f"Acquisition cost ({largest_acquisition_cost:,.0f}) "
                f"with zero or negative income."
            )
        return RuleResult(rule, 0.0, False, "No income and no acquisitions.")

    ratio = float(largest_acquisition_cost / total_income)
    if ratio > threshold_ratio:
        score = min(1.0, (ratio - threshold_ratio) / threshold_ratio)
        return RuleResult(
            rule, round(score, 3), True,
            f"Largest acquisition ({largest_acquisition_cost:,.0f}) "
            f"is {ratio:.1f}x total income ({total_income:,.0f}), "
            f"exceeding {threshold_ratio}x threshold."
        )

    return RuleResult(
        rule, 0.0, False,
        f"Largest acquisition is {ratio:.1f}x income, within normal range."
    )


# ---------------------------------------------------------------------------
# Rule 5 — Zero income with significant assets
# ---------------------------------------------------------------------------

def zero_income_with_assets(
    total_income: Decimal | None,
    total_assets: Decimal | None,
    *,
    min_assets: float = _cfg(
        "layer1", "legacy", "zero_income_with_assets", "min_assets", default=100_000
    ),
) -> RuleResult:
    """Flag declarants reporting zero/no income but holding significant assets.

    Unlike ``unexplained_wealth`` (which checks ratios), this catches
    the specific case of *exactly* zero declared income with non-trivial
    assets — an arithmetically implausible combination.

    Parameters
    ----------
    min_assets:
        Minimum asset value (UAH) to consider "significant."
    """
    rule = "zero_income_with_assets"

    if total_income is None or total_assets is None:
        return RuleResult(rule, 0.0, False, "Insufficient data to assess.")

    if total_income > 0:
        return RuleResult(rule, 0.0, False, "Declared income is non-zero.")

    if total_assets >= Decimal(str(min_assets)):
        score = min(1.0, float(total_assets) / (min_assets * 10))
        return RuleResult(
            rule, round(score, 3), True,
            f"Zero declared income but {total_assets:,.0f} UAH in assets — "
            f"no income source to explain asset holdings."
        )

    return RuleResult(
        rule, 0.0, False,
        "Assets below significance threshold for zero-income check."
    )


# ---------------------------------------------------------------------------
# Rule 6 — Family member asset concentration
# ---------------------------------------------------------------------------

def family_asset_concentration(
    declarant_items: int,
    family_items: int,
    total_items: int,
    *,
    threshold: float = _cfg(
        "layer1", "legacy", "family_asset_concentration", "threshold", default=0.7
    ),
    min_items: int = _cfg(
        "layer1", "legacy", "family_asset_concentration", "min_items", default=3
    ),
) -> RuleResult:
    """Flag when assets are disproportionately registered to family members.

    A common evasion pattern is registering assets (real estate, vehicles,
    bank accounts) to family members while keeping the declarant's name clean.

    Parameters
    ----------
    declarant_items:
        Number of ownership items attributed to the declarant.
    family_items:
        Number of ownership items attributed to family members.
    total_items:
        Total ownership items across all persons.
    threshold:
        Family share above which the rule triggers.
    min_items:
        Minimum total items required (prevents noise on tiny declarations).
    """
    rule = "family_asset_concentration"

    if total_items < min_items:
        return RuleResult(
            rule, 0.0, False,
            f"Too few ownership items ({total_items}) for reliable assessment."
        )

    family_share = family_items / total_items
    if family_share > threshold:
        score = min(1.0, (family_share - threshold) / (1.0 - threshold))
        return RuleResult(
            rule, round(score, 3), True,
            f"{family_items} of {total_items} assets ({family_share:.0%}) "
            f"are registered to family members, exceeding {threshold:.0%} threshold."
        )

    return RuleResult(
        rule, 0.0, False,
        f"Family asset share ({family_share:.0%}) is within normal range."
    )


# ---------------------------------------------------------------------------
# Composite scorer
# ---------------------------------------------------------------------------

@dataclass
class ScoringResult:
    """Aggregate scoring result across all rules.

    ``total_score`` is on a native 0–100 scale.
    """

    total_score: float  # 0–100 scale
    rule_results: list[RuleResult] = field(default_factory=list)
    triggered_rules: list[str] = field(default_factory=list)
    corruption_risk_score: float = 0.0
    opacity_evasion_score: float = 0.0
    data_quality_score: float = 0.0
    raw_total_score: float = 0.0

    @property
    def explanation_summary(self) -> str:
        if not self.triggered_rules:
            return "No anomaly signals detected."
        lines = [f"• {r.explanation}" for r in self.rule_results if r.triggered]
        return "\n".join(lines)


def _severity_multiplier(severity: str) -> float:
    table = {
        "LOW": 0.5,
        "MEDIUM": 1.0,
        "HIGH": 1.5,
        "EXTREME": 2.0,
    }
    return table.get(severity.upper(), 1.0)


def _make_flag(
    *,
    rule_id: str,
    category: str,
    severity: str,
    base_weight: float,
    confidence: float,
    message: str,
) -> RuleResult:
    points = base_weight * _severity_multiplier(severity) * confidence
    return RuleResult(
        rule_name=rule_id,
        score=round(points, 3),
        triggered=True,
        explanation=message,
        category=category,
        severity=severity,
        confidence=round(confidence, 2),
    )


def _normalize_region_key(region: Any) -> str | None:
    if region is None:
        return None
    region_key = str(region).strip().lower()
    return region_key or None


def _score_cr6_area(
    *,
    area_label: str,
    area_value: Decimal,
    cohort_stats: Any | None,
    global_distribution: list[float],
    region_distribution: list[float] | None,
    region_name: str | None,
    relative_min_samples: int,
    relative_high_pct: float,
    relative_medium_pct: float,
    absolute_high_area: Decimal,
    absolute_medium_area: Decimal,
    base_weight: float,
    confidence: float,
) -> RuleResult | None:
    if area_value <= 0:
        return None

    if cohort_stats is not None:
        relative_distribution: list[float] | None = None
        relative_source = None
        if region_distribution and len(region_distribution) >= relative_min_samples:
            relative_distribution = region_distribution
            relative_source = f"region cohort '{region_name}'" if region_name else "region cohort"
        elif len(global_distribution) >= relative_min_samples:
            relative_distribution = global_distribution
            relative_source = "global cohort"

        if relative_distribution is not None:
            percentile = compute_percentile_rank(float(area_value), relative_distribution)
            p95 = get_percentile_value(relative_distribution, 0.95)
            if percentile >= relative_high_pct or percentile >= relative_medium_pct:
                severity = "HIGH" if percentile >= relative_high_pct else "MEDIUM"
                return _make_flag(
                    rule_id="CR6",
                    category="corruption",
                    severity=severity,
                    base_weight=base_weight,
                    confidence=confidence,
                    message=(
                        f"CR6 mode: relative; source: {relative_source}. "
                        f"{area_label} area is {area_value:,.0f} m2 "
                        f"({percentile:.0%} percentile of cohort peers, P95 = {p95:,.0f} m2) [relative mode]."
                    ),
                )
            return None

        if area_value > absolute_high_area:
            return _make_flag(
                rule_id="CR6",
                category="corruption",
                severity="HIGH",
                base_weight=base_weight,
                confidence=confidence,
                message=(
                    "CR6 mode: absolute fallback (missing or sparse relative distribution). "
                    f"{area_label} area is {area_value:,.0f} m2 (> {absolute_high_area} m2) [absolute mode]."
                ),
            )
        if area_value > absolute_medium_area:
            return _make_flag(
                rule_id="CR6",
                category="corruption",
                severity="MEDIUM",
                base_weight=base_weight,
                confidence=confidence,
                message=(
                    "CR6 mode: absolute fallback (missing or sparse relative distribution). "
                    f"{area_label} area is {area_value:,.0f} m2 (> {absolute_medium_area} m2) [absolute mode]."
                ),
            )
        return None

    if area_value > absolute_high_area:
        return _make_flag(
            rule_id="CR6",
            category="corruption",
            severity="HIGH",
            base_weight=base_weight,
            confidence=confidence,
            message=(
                "CR6 mode: absolute fallback (missing cohort stats). "
                f"{area_label} area is {area_value:,.0f} m2 (> {absolute_high_area} m2) [absolute mode]."
            ),
        )
    if area_value > absolute_medium_area:
        return _make_flag(
            rule_id="CR6",
            category="corruption",
            severity="MEDIUM",
            base_weight=base_weight,
            confidence=confidence,
            message=(
                "CR6 mode: absolute fallback (missing cohort stats). "
                f"{area_label} area is {area_value:,.0f} m2 (> {absolute_medium_area} m2) [absolute mode]."
            ),
        )
    return None


_YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")


def _extract_year(raw_date: Any) -> int | None:
    if raw_date is None:
        return None
    s = str(raw_date).strip()
    if not s:
        return None
    m = _YEAR_RE.search(s)
    if not m:
        return None
    try:
        year = int(m.group(1))
    except ValueError:
        return None
    if year < 1900 or year > 2100:
        return None
    return year


def _is_cash_asset(asset_type: Any) -> bool:
    s = str(asset_type or "").lower()
    return "готів" in s


def _has_any_kw(value: Any, keywords: tuple[str, ...]) -> bool:
    s = str(value or "").lower()
    return any(kw in s for kw in keywords)


def _asset_totals_by_person(
    real_estate: list[dict[str, Any]],
    monetary_assets: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """Approximate per-person asset totals using ownership and known values."""
    totals: dict[str, Decimal] = {}

    for r in real_estate:
        owner = r.get("right_belongs_raw") or r.get("right_belongs_resolved")
        if owner is None:
            continue
        value = r.get("cost_assessment")
        if value is None:
            continue
        try:
            value_dec = Decimal(str(value))
        except Exception:
            continue

        pct_raw = str(r.get("percent_ownership") or "").replace(",", ".").strip()
        pct = Decimal("1")
        if pct_raw:
            try:
                pct = Decimal(pct_raw) / Decimal("100")
            except Exception:
                pct = Decimal("1")
        if pct <= 0:
            continue
        if pct > 1:
            pct = Decimal("1")

        key = str(owner)
        totals[key] = totals.get(key, Decimal(0)) + (value_dec * pct)

    for m in monetary_assets:
        owner = m.get("person_ref")
        if owner is None:
            continue
        amt_uah = to_uah(m.get("amount"), m.get("currency_code"))
        if amt_uah is None:
            continue
        key = str(owner)
        totals[key] = totals.get(key, Decimal(0)) + amt_uah

    return totals


def _is_ukraine_residence(raw_declaration: dict[str, Any] | None) -> bool:
    if not isinstance(raw_declaration, dict):
        return False
    step1 = ((raw_declaration.get("data") or {}).get("step_1") or {}).get("data") or {}
    country = step1.get("country")
    if country is None:
        return False
    s = str(country).strip().lower()
    return s in {"1", "ua", "ukr", "ukraine", "україна"}


def _step3_not_applicable(raw_declaration: dict[str, Any] | None) -> bool:
    if not isinstance(raw_declaration, dict):
        return False
    step3 = ((raw_declaration.get("data") or {}).get("step_3") or {})
    return step3.get("isNotApplicable") == 1


def _has_positive_income(incomes: list[dict[str, Any]]) -> bool:
    for i in incomes:
        amt = i.get("amount")
        if amt is None:
            continue
        try:
            if Decimal(str(amt)) > 0:
                return True
        except Exception:
            continue
    return False


def _confidential_ratio_from_rows(
    incomes: list[dict[str, Any]],
    monetary_assets: list[dict[str, Any]],
    real_estate: list[dict[str, Any]],
) -> float:
    status_fields = (
        "amount_status",
        "total_area_status",
        "cost_assessment_status",
        "organization_status",
    )
    confidential_statuses = {"confidential", "redacted_other"}
    total = 0
    confidential = 0

    for rows in (incomes, monetary_assets, real_estate):
        for row in rows:
            for sf in status_fields:
                if sf in row:
                    total += 1
                    if str(row.get(sf) or "") in confidential_statuses:
                        confidential += 1

    if total == 0:
        return 0.0
    return confidential / total


def _cr12_wealth_concentration(
    *,
    relation_by_id: dict[str, str],
    income_by_person: dict[str, Decimal],
    assets_by_person: dict[str, Decimal],
) -> RuleResult:
    """CR12: low-income spouse/child with outsized asset ownership."""
    rule = "CR12"
    cr12_cfg = SCORING_CONFIG.get("layer1", {}).get("corruption", {}).get("cr12_wealth_concentration", {})
    cr12_minimum_income = Decimal(str(cr12_cfg.get("minimum_income", 50000)))
    cr12_ratio_minimum = Decimal(str(cr12_cfg.get("ratio_minimum", 2.0)))
    cr12_ratio_high = Decimal(str(cr12_cfg.get("ratio_high", 5.0)))
    cr12_base_weight = float(cr12_cfg.get("base_weight", 3.0))
    cr12_confidence = float(cr12_cfg.get("confidence", 0.7))

    declarant_assets = assets_by_person.get("1", Decimal(0))
    if declarant_assets <= 0:
        return RuleResult(rule, 0.0, False, "Insufficient declarant asset baseline for comparison.")

    best_ratio = Decimal(0)
    best_pid = None
    child_or_spouse = ("друж", "чолов", "дит", "child", "син", "дон")

    for pid, rel in relation_by_id.items():
        rel_l = str(rel or "").lower()
        if not any(kw in rel_l for kw in child_or_spouse):
            continue

        person_income = income_by_person.get(pid, Decimal(0))
        if person_income >= cr12_minimum_income:
            continue

        person_assets = assets_by_person.get(pid, Decimal(0))
        if person_assets <= 0:
            continue

        ratio = person_assets / declarant_assets
        if ratio > best_ratio:
            best_ratio = ratio
            best_pid = pid

    if best_pid is None or best_ratio < cr12_ratio_minimum:
        return RuleResult(rule, 0.0, False, "No major wealth concentration detected in low-income family members.")

    severity = "HIGH" if best_ratio >= cr12_ratio_high else "MEDIUM"
    relation = relation_by_id.get(best_pid, "family member")
    member_assets = assets_by_person.get(best_pid, Decimal(0))
    return _make_flag(
        rule_id=rule,
        category="corruption",
        severity=severity,
        base_weight=cr12_base_weight,
        confidence=cr12_confidence,
        message=(
            f"{relation} holds {member_assets:,.0f} UAH in known assets, "
            f"{float(best_ratio):.1f}x declarant-held assets, with low independent income."
        ),
    )


def _br1_many_corrected(timeline: Any) -> RuleResult:
    """BR1: repeated declarations in the same year (correction proxy)."""
    rule = "BR1"
    per_year = getattr(timeline, "declarations_per_year", {}) or {}
    if not per_year:
        return RuleResult(rule, 0.0, False, "No per-year declaration counts available.")

    minimum_declarations_per_year = int(
        _cfg("layer1", "timeline", "br1_many_corrected", "minimum_declarations_per_year", default=3)
    )
    base_weight = float(_cfg("layer1", "timeline", "br1_many_corrected", "base_weight", default=2.0))
    confidence = float(_cfg("layer1", "timeline", "br1_many_corrected", "confidence", default=0.8))

    worst_year = None
    worst_count = 0
    for year, count in per_year.items():
        if count > worst_count:
            worst_count = count
            worst_year = year

    if worst_count >= minimum_declarations_per_year:
        return _make_flag(
            rule_id=rule,
            category="opacity",
            severity="MEDIUM",
            base_weight=base_weight,
            confidence=confidence,
            message=f"Detected {worst_count} declarations for {worst_year}, indicating repeated corrections.",
        )

    return RuleResult(rule, 0.0, False, "No significant correction pattern detected.")


def _cr15_real_estate_income_3y(timeline: Any) -> RuleResult:
    """CR15: high real-estate value relative to 3-year average income."""
    rule = "CR15"
    minimum_snapshots = int(
        _cfg("layer1", "timeline", "cr15_real_estate_income_3y", "minimum_snapshots", default=3)
    )
    trigger_ratio = float(
        _cfg("layer1", "timeline", "cr15_real_estate_income_3y", "trigger_ratio", default=15.0)
    )
    base_weight = float(_cfg("layer1", "timeline", "cr15_real_estate_income_3y", "base_weight", default=4.0))
    confidence = float(_cfg("layer1", "timeline", "cr15_real_estate_income_3y", "confidence", default=0.8))
    snaps = [
        s for s in getattr(timeline, "snapshots", [])
        if getattr(s, "declaration_type", 1) == 1
    ]
    if len(snaps) < minimum_snapshots:
        return RuleResult(rule, 0.0, False, "Need at least 3 annual snapshots for CR15.")

    best_ratio = 0.0
    best_end_year = None
    for i in range(len(snaps) - 2):
        window = snaps[i:i + 3]
        incomes: list[Decimal] = []
        for s in window:
            inc = getattr(s, "total_income", None)
            if inc is not None and inc > 0:
                incomes.append(inc)
        if len(incomes) < 3:
            continue

        end_re = getattr(window[2], "total_real_estate", None)
        if end_re is None or end_re <= 0:
            continue

        avg_income = sum(incomes) / Decimal(len(incomes))
        if avg_income <= 0:
            continue

        ratio = float(end_re / avg_income)
        if ratio > best_ratio:
            best_ratio = ratio
            best_end_year = getattr(window[2], "declaration_year", None)

    if best_ratio >= trigger_ratio:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="HIGH",
            base_weight=base_weight,
            confidence=confidence,
            message=(
                f"Real-estate value is {best_ratio:.1f}x 3-year average income "
                f"(window ending {best_end_year})."
            ),
        )

    return RuleResult(rule, 0.0, False, "No 3-year real-estate/income imbalance detected.")


def _cr14_asset_appearance_disappearance(change: Any) -> RuleResult:
    """CR14: major asset appears/disappears without matching one-off income."""
    rule = "CR14"
    appearance_value_min = Decimal(str(
        _cfg("layer1", "timeline", "cr14_asset_appearance_disappearance", "appearance_value_min", default=1_000_000)
    ))
    appearance_one_off_fraction = Decimal(str(
        _cfg("layer1", "timeline", "cr14_asset_appearance_disappearance", "appearance_one_off_fraction", default=0.5)
    ))
    disappearance_value_min = Decimal(str(
        _cfg("layer1", "timeline", "cr14_asset_appearance_disappearance", "disappearance_value_min", default=1_000_000)
    ))
    disappearance_one_off_income_min = Decimal(str(
        _cfg("layer1", "timeline", "cr14_asset_appearance_disappearance", "disappearance_one_off_income_min", default=300_000)
    ))
    base_weight = float(_cfg("layer1", "timeline", "cr14_asset_appearance_disappearance", "base_weight", default=5.0))
    confidence_appearance = float(_cfg("layer1", "timeline", "cr14_asset_appearance_disappearance", "confidence_appearance", default=0.8))
    confidence_disappearance = float(_cfg("layer1", "timeline", "cr14_asset_appearance_disappearance", "confidence_disappearance", default=0.7))
    one_off = getattr(change, "one_off_income_curr", None) or Decimal(0)

    appeared_n = getattr(change, "major_assets_appeared", 0) or 0
    appeared_val = getattr(change, "max_appeared_value", None)
    if appeared_n > 0 and appeared_val is not None and appeared_val >= appearance_value_min:
        if one_off < appeared_val * appearance_one_off_fraction:
            return _make_flag(
                rule_id=rule,
                category="corruption",
                severity="HIGH",
                base_weight=base_weight,
                confidence=confidence_appearance,
                message=(
                    f"Major asset appearance detected ({appeared_n} new major assets, "
                    f"max {appeared_val:,.0f} UAH) without matching one-off income in {change.to_year}."
                ),
            )

    disappeared_n = getattr(change, "major_assets_disappeared", 0) or 0
    disappeared_val = getattr(change, "max_disappeared_value", None)
    if disappeared_n > 0 and disappeared_val is not None and disappeared_val >= disappearance_value_min:
        if one_off < disappearance_one_off_income_min:
            sev = "HIGH" if disappeared_n >= 2 else "MEDIUM"
            return _make_flag(
                rule_id=rule,
                category="corruption",
                severity=sev,
                base_weight=base_weight,
                confidence=confidence_disappearance,
                message=(
                    f"Major asset disappearance detected ({disappeared_n} assets, "
                    f"max {disappeared_val:,.0f} UAH) without sale/gift-like one-off income in {change.to_year}."
                ),
            )

    return RuleResult(rule, 0.0, False, "No major asset appearance/disappearance anomaly detected.")


def _legacy_score_declaration(
    *,
    total_income: Decimal | None = None,
    total_assets: Decimal | None = None,
    cash_holdings: Decimal | None = None,
    bank_deposits: Decimal | None = None,
    total_value_fields: int = 0,
    unknown_value_fields: int = 0,
    largest_acquisition_cost: Decimal | None = None,
    ownership_declarant: int = 0,
    ownership_family: int = 0,
    ownership_total: int = 0,
) -> ScoringResult:
    rules = [
        unexplained_wealth(total_income, total_assets),
        cash_to_bank_ratio(cash_holdings, bank_deposits),
        unknown_value_frequency(total_value_fields, unknown_value_fields),
        acquisition_income_mismatch(largest_acquisition_cost, total_income),
        zero_income_with_assets(total_income, total_assets),
        family_asset_concentration(
            ownership_declarant, ownership_family, ownership_total,
        ),
    ]

    triggered = [r.rule_name for r in rules if r.triggered]
    raw_total = sum(r.score for r in rules)
    overall_100 = 100.0 * (1.0 - math.exp(-raw_total / 12.0)) if raw_total > 0 else 0.0
    overall_100 = round(overall_100, 2)

    return ScoringResult(
        total_score=overall_100,
        rule_results=rules,
        triggered_rules=triggered,
        corruption_risk_score=round(raw_total, 3),
    )


def score_declaration(
    *,
    total_income: Decimal | None = None,
    total_assets: Decimal | None = None,
    cash_holdings: Decimal | None = None,
    bank_deposits: Decimal | None = None,
    total_value_fields: int = 0,
    unknown_value_fields: int = 0,
    largest_acquisition_cost: Decimal | None = None,
    ownership_declarant: int = 0,
    ownership_family: int = 0,
    ownership_total: int = 0,
    incomes: list[dict[str, Any]] | None = None,
    monetary_assets: list[dict[str, Any]] | None = None,
    real_estate: list[dict[str, Any]] | None = None,
    vehicles: list[dict[str, Any]] | None = None,
    family_members: list[dict[str, Any]] | None = None,
    declaration_year: int | None = None,
    raw_declaration: dict[str, Any] | None = None,
    cohort_stats: Any | None = None,
    cohort_resolver: Any | None = None,
    declaration_sector: str | None = None,
    declaration_gov_level: str | None = None,
    declaration_region: str | None = None,
    cohort_key_used: str | None = None,
) -> ScoringResult:
    """Run all Layer 1 scoring rules and return an aggregate result.

    Each input should be pre-computed from the parsed declaration data.
    All monetary values should be in the same currency.

    Parameters
    ----------
    cohort_stats:
        Optional ``CohortStats`` from ``app.scoring.cohorts``. When provided,
        CR16 cohort-relative outlier rules are evaluated and folded into
        the corruption-risk score.
    cohort_resolver, declaration_sector, declaration_gov_level, declaration_region, cohort_key_used:
        Optional taxonomy-aware cohort inputs used to evaluate the Layer 2
        cohort rules from ``app.scoring.cohorts.score_declaration_l2``.

    Returns
    -------
    A ``ScoringResult`` with the composite score on a 0–100 scale.
    """
    # Backward-compatible path used by older tests/callers.
    if incomes is None and monetary_assets is None and real_estate is None and vehicles is None:
        return _legacy_score_declaration(
            total_income=total_income,
            total_assets=total_assets,
            cash_holdings=cash_holdings,
            bank_deposits=bank_deposits,
            total_value_fields=total_value_fields,
            unknown_value_fields=unknown_value_fields,
            largest_acquisition_cost=largest_acquisition_cost,
            ownership_declarant=ownership_declarant,
            ownership_family=ownership_family,
            ownership_total=ownership_total,
        )

    incomes = incomes or []
    monetary_assets = monetary_assets or []
    real_estate = real_estate or []
    vehicles = vehicles or []
    family_members = family_members or []

    layer1_cfg = SCORING_CONFIG.get("layer1", {}) if isinstance(SCORING_CONFIG, dict) else {}
    aggregation_cfg = layer1_cfg.get("aggregation", {}) if isinstance(layer1_cfg, dict) else {}
    interaction_bonuses = aggregation_cfg.get("interaction_bonuses", {}) if isinstance(aggregation_cfg, dict) else {}
    corruption_cfg = layer1_cfg.get("corruption", {}) if isinstance(layer1_cfg, dict) else {}
    data_quality_cfg = layer1_cfg.get("data_quality", {}) if isinstance(layer1_cfg, dict) else {}

    cr1_cfg = corruption_cfg.get("cr1_cash_to_income", {})
    cr2_cfg = corruption_cfg.get("cr2_fx_cash", {})
    cr3_cfg = corruption_cfg.get("cr3_acquisition_income", {})
    cr4_cfg = corruption_cfg.get("cr4_low_income_acquisitions", {})
    cr6_dwelling_cfg = corruption_cfg.get("cr6_dwelling_area", {})
    cr6_agri_cfg = corruption_cfg.get("cr6_agricultural_area", {})
    cr7_cfg = corruption_cfg.get("cr7_luxury_vehicles", {})
    cr8_cfg = corruption_cfg.get("cr8_agri_assets", {})
    cr9_cfg = corruption_cfg.get("cr9_rentable_assets", {})
    cr10_cfg = corruption_cfg.get("cr10_unknown_valuations", {})
    cr11_cfg = corruption_cfg.get("cr11_family_major_owner", {})
    cr13_cfg = corruption_cfg.get("cr13_family_no_info", {})

    cr16_cfg = layer1_cfg.get("timeline", {}).get("cr16_cohort_outliers", {}) if isinstance(layer1_cfg, dict) else {}
    cr16_cfg = cr16_cfg if isinstance(cr16_cfg, dict) else {}

    flags: list[RuleResult] = []

    # ------------------------------
    # Technical/data-quality checks
    # ------------------------------
    bad_dates = 0
    for r in real_estate:
        y = _extract_year(r.get("owning_date"))
        if r.get("owning_date") and (y is None or y < 1900 or (declaration_year and y > declaration_year)):
            bad_dates += 1
    for v in vehicles:
        y = _extract_year(v.get("owning_date"))
        if v.get("owning_date") and (y is None or y < 1900 or (declaration_year and y > declaration_year)):
            bad_dates += 1
    if bad_dates > 0:
        flags.append(_make_flag(
            rule_id="TQ1",
            category="data_quality",
            severity="LOW",
            base_weight=1,
            confidence=1.0,
            message=f"Found {bad_dates} invalid or out-of-range owning dates.",
        ))

    family_ids = {str(m.get("member_id")) for m in family_members if m.get("member_id") is not None}
    known_person_ids = {"1"} | family_ids

    orphan_refs = 0
    for r in real_estate:
        rr = str(r.get("right_belongs_resolved") or "")
        if rr.startswith("unknown:"):
            orphan_refs += 1
    for i in incomes:
        pr = i.get("person_ref")
        if pr is not None and str(pr) not in known_person_ids:
            orphan_refs += 1
    for m in monetary_assets:
        pr = m.get("person_ref")
        if pr is not None and str(pr) not in known_person_ids:
            orphan_refs += 1
    if orphan_refs > 0:
        flags.append(_make_flag(
            rule_id="TQ2",
            category="data_quality",
            severity="LOW",
            base_weight=1,
            confidence=1.0,
            message=f"Found {orphan_refs} unresolved ownership/person references.",
        ))

    share_issue = 0
    by_asset: dict[str, float] = {}
    tq3_max_total_share = float(data_quality_cfg.get("ownership_share_total_max", 110.0))
    tq3_min_total_share = float(data_quality_cfg.get("ownership_share_total_min", 10.0))
    for r in real_estate:
        key = f"{r.get('raw_iteration')}|{r.get('object_type')}|{r.get('city')}|{r.get('district')}"
        pct_raw = str(r.get("percent_ownership") or "").replace(",", ".").strip()
        if not pct_raw:
            continue
        try:
            pct_val = float(pct_raw)
        except ValueError:
            continue
        by_asset[key] = by_asset.get(key, 0.0) + pct_val
    for total_pct in by_asset.values():
        if total_pct > tq3_max_total_share or (0.0 < total_pct < tq3_min_total_share):
            share_issue += 1
    if share_issue > 0:
        flags.append(_make_flag(
            rule_id="TQ3",
            category="data_quality",
            severity="LOW",
            base_weight=1,
            confidence=0.8,
            message=f"Found {share_issue} properties with implausible ownership-share totals.",
        ))

    parse_or_extreme = 0
    tq4_extreme_value_max = Decimal(str(data_quality_cfg.get("extreme_numeric_value_max", 10000000000)))
    tq4_extreme_area_max = Decimal(str(data_quality_cfg.get("extreme_area_value_max", 10000000)))
    for i in incomes:
        if i.get("amount_status") == "parse_error":
            parse_or_extreme += 1
        amt = i.get("amount")
        if amt is not None and Decimal(amt) > tq4_extreme_value_max:
            parse_or_extreme += 1
    for m in monetary_assets:
        if m.get("amount_status") == "parse_error":
            parse_or_extreme += 1
        amt = m.get("amount")
        if amt is not None:
            uah = to_uah(amt, m.get("currency_code"))
            if uah is not None and uah > tq4_extreme_value_max:
                parse_or_extreme += 1
    for r in real_estate:
        area = r.get("total_area")
        if area is not None and Decimal(area) > tq4_extreme_area_max:
            parse_or_extreme += 1
        if r.get("total_area_status") == "parse_error" or r.get("cost_assessment_status") == "parse_error":
            parse_or_extreme += 1
    if parse_or_extreme > 0:
        flags.append(_make_flag(
            rule_id="TQ4",
            category="data_quality",
            severity="LOW",
            base_weight=1,
            confidence=1.0,
            message=f"Found {parse_or_extreme} non-parsable or extreme numeric values.",
        ))

    # TQ5: likely-misused step_3 not-applicable marker.
    if _step3_not_applicable(raw_declaration) and _is_ukraine_residence(raw_declaration):
        has_income = _has_positive_income(incomes)
        child_markers = ("дит", "child", "син", "дон")
        adult_family = sum(1 for m in family_members if not _has_any_kw(m.get("relation"), child_markers))
        adults = 1 + max(0, adult_family)
        if adults >= 1 and has_income:
            flags.append(_make_flag(
                rule_id="TQ5",
                category="data_quality",
                severity="LOW",
                base_weight=1,
                confidence=0.6,
                message="Step 3 is marked not applicable for a Ukraine-resident household with adults and declared income.",
            ))

    # ------------------------------
    # Corruption-risk checks
    # ------------------------------
    legacy_cash_rule = cash_to_bank_ratio(cash_holdings, bank_deposits)
    if legacy_cash_rule.triggered:
        flags.append(RuleResult(
            rule_name=legacy_cash_rule.rule_name,
            score=legacy_cash_rule.score,
            triggered=True,
            explanation=legacy_cash_rule.explanation,
            category="corruption",
            severity="MEDIUM",
            confidence=1.0,
        ))

    inc_val = Decimal(total_income) if total_income is not None else None
    cash_val = Decimal(cash_holdings) if cash_holdings is not None else None

    cr1_income_min = Decimal(str(cr1_cfg.get("income_min", 10000)))
    cr1_extreme_ratio = float(cr1_cfg.get("extreme_ratio", 10.0))
    cr1_high_ratio = float(cr1_cfg.get("high_ratio", 5.0))
    cr1_medium_ratio = float(cr1_cfg.get("medium_ratio", 3.0))
    cr1_base_weight = float(cr1_cfg.get("base_weight", 5.0))

    if inc_val is not None and cash_val is not None and inc_val >= cr1_income_min and inc_val > 0:
        ratio = float(cash_val / inc_val)
        if ratio >= cr1_extreme_ratio:
            flags.append(_make_flag(
                rule_id="CR1",
                category="corruption",
                severity="EXTREME",
                base_weight=cr1_base_weight,
                confidence=1.0,
                message=f"Cash-to-income ratio is {ratio:.1f}x (>= {cr1_extreme_ratio:g}x).",
            ))
        elif ratio >= cr1_high_ratio:
            flags.append(_make_flag(
                rule_id="CR1",
                category="corruption",
                severity="HIGH",
                base_weight=cr1_base_weight,
                confidence=1.0,
                message=f"Cash-to-income ratio is {ratio:.1f}x (>= {cr1_high_ratio:g}x).",
            ))
        elif ratio >= cr1_medium_ratio:
            flags.append(_make_flag(
                rule_id="CR1",
                category="corruption",
                severity="MEDIUM",
                base_weight=cr1_base_weight,
                confidence=1.0,
                message=f"Cash-to-income ratio is {ratio:.1f}x (>= {cr1_medium_ratio:g}x).",
            ))

    cr2_fx_share_high = float(cr2_cfg.get("fx_share_high", 0.7))
    cr2_fx_share_medium = float(cr2_cfg.get("fx_share_medium", 0.5))
    cr2_fx_to_income_high = float(cr2_cfg.get("fx_to_income_high", 3.0))
    cr2_fx_to_income_medium = float(cr2_cfg.get("fx_to_income_medium", 1.5))
    cr2_base_weight = float(cr2_cfg.get("base_weight", 4.0))

    fx_cash = Decimal(0)
    total_cash_detected = Decimal(0)
    for m in monetary_assets:
        if not _is_cash_asset(m.get("asset_type")):
            continue
        uah = to_uah(m.get("amount"), m.get("currency_code"))
        if uah is None:
            continue
        total_cash_detected += uah
        if (m.get("currency_code") or "").upper() != "UAH":
            fx_cash += uah
    fx_share = float(fx_cash / total_cash_detected) if total_cash_detected > 0 else 0.0
    if inc_val is not None and inc_val > 0 and total_cash_detected > 0:
        fx_to_income = float(fx_cash / inc_val)
        if fx_share >= cr2_fx_share_high and fx_to_income >= cr2_fx_to_income_high:
            flags.append(_make_flag(
                rule_id="CR2",
                category="corruption",
                severity="HIGH",
                base_weight=cr2_base_weight,
                confidence=1.0,
                message=f"FX cash dominates holdings ({fx_share:.0%}) and equals {fx_to_income:.1f}x annual income.",
            ))
        elif fx_share >= cr2_fx_share_medium and fx_to_income >= cr2_fx_to_income_medium:
            flags.append(_make_flag(
                rule_id="CR2",
                category="corruption",
                severity="MEDIUM",
                base_weight=cr2_base_weight,
                confidence=1.0,
                message=f"High FX-cash concentration ({fx_share:.0%}) with FX cash {fx_to_income:.1f}x income.",
            ))

    if inc_val is not None and inc_val > 0:
        cr3_extreme_ratio = float(cr3_cfg.get("extreme_ratio", 7.0))
        cr3_high_ratio = float(cr3_cfg.get("high_ratio", 3.0))
        cr3_medium_ratio = float(cr3_cfg.get("medium_ratio", 2.0))
        cr3_one_off_fraction = Decimal(str(cr3_cfg.get("one_off_income_fraction", 0.6)))
        cr3_base_weight = float(cr3_cfg.get("base_weight", 5.0))
        acq_costs: list[Decimal] = []
        for r in real_estate:
            c = r.get("cost_assessment")
            if c is None:
                continue
            y = _extract_year(r.get("owning_date"))
            if declaration_year is None or y == declaration_year:
                acq_costs.append(Decimal(c))
        for v in vehicles:
            c = v.get("cost_date")
            if c is None:
                continue
            y = _extract_year(v.get("owning_date"))
            if declaration_year is None or y == declaration_year:
                acq_costs.append(Decimal(c))

        one_off_income = Decimal(0)
        for i in incomes:
            text = f"{i.get('income_type') or ''} {i.get('source_type') or ''} {i.get('income_type_other') or ''}".lower()
            if any(kw in text for kw in ("спад", "inherit", "sale", "продаж", "gift", "дар")):
                amt = i.get("amount")
                if amt is not None:
                    one_off_income += Decimal(amt)

        best_ratio = 0.0
        best_cost = None
        best_sev = None
        for cost in acq_costs:
            ratio = float(cost / inc_val)
            sev = None
            if ratio >= cr3_extreme_ratio:
                sev = "EXTREME"
            elif ratio >= cr3_high_ratio:
                sev = "HIGH"
            elif ratio >= cr3_medium_ratio:
                sev = "MEDIUM"
            if sev and ratio > best_ratio:
                best_ratio = ratio
                best_cost = cost
                best_sev = sev

        if best_sev is not None and best_cost is not None:
            downgraded = False
            if one_off_income >= best_cost * cr3_one_off_fraction:
                downgraded = True
                if best_sev == "EXTREME":
                    best_sev = "HIGH"
                elif best_sev == "HIGH":
                    best_sev = "MEDIUM"
            msg = f"Largest same-year acquisition is {best_cost:,.0f} UAH ({best_ratio:.1f}x income)."
            if downgraded:
                msg += " Severity reduced due to matching one-off income signal."
            flags.append(_make_flag(
                rule_id="CR3",
                category="corruption",
                severity=best_sev,
                base_weight=cr3_base_weight,
                confidence=0.9,
                message=msg,
            ))

    cr4_income_max = Decimal(str(cr4_cfg.get("income_max", 150000)))
    cr4_property_cost_high = Decimal(str(cr4_cfg.get("property_cost_high", 500000)))
    cr4_property_area_high = Decimal(str(cr4_cfg.get("property_area_high", 10000)))
    cr4_property_cost_area_high = Decimal(str(cr4_cfg.get("property_cost_area_high", 300000)))
    cr4_vehicle_cost_high = Decimal(str(cr4_cfg.get("vehicle_cost_high", 300000)))
    cr4_minimum_count = int(cr4_cfg.get("minimum_count", 2))
    cr4_base_weight = float(cr4_cfg.get("base_weight", 4.0))

    if inc_val is not None and inc_val < cr4_income_max:
        count_mid_hi = 0
        for r in real_estate:
            cost = r.get("cost_assessment")
            area = r.get("total_area")
            obj = str(r.get("object_type") or "").lower()
            if cost is not None and Decimal(cost) >= cr4_property_cost_high:
                count_mid_hi += 1
                continue
            if area is not None and Decimal(area) >= cr4_property_area_high and cost is not None and Decimal(cost) >= cr4_property_cost_area_high:
                count_mid_hi += 1
                continue
            if "зем" in obj and area is not None and Decimal(area) >= cr4_property_area_high and cost is not None and Decimal(cost) >= cr4_property_cost_area_high:
                count_mid_hi += 1
        for v in vehicles:
            cost = v.get("cost_date")
            if cost is not None and Decimal(cost) >= cr4_vehicle_cost_high:
                count_mid_hi += 1
        if count_mid_hi >= cr4_minimum_count:
            flags.append(_make_flag(
                rule_id="CR4",
                category="corruption",
                severity="HIGH",
                base_weight=cr4_base_weight,
                confidence=0.9,
                message=f"Low-income year with {count_mid_hi} medium/high-value acquisitions.",
            ))

    dwelling_area = Decimal(0)
    agri_area = Decimal(0)
    real_estate_regions: set[str] = set()
    for r in real_estate:
        area = r.get("total_area")
        if area is None:
            continue
        obj = str(r.get("object_type") or "").lower()
        region_key = _normalize_region_key(r.get("region"))
        if region_key:
            real_estate_regions.add(region_key)
        if any(kw in obj for kw in ("кварт", "буд", "жит")):
            dwelling_area += Decimal(area)
        if "зем" in obj:
            agri_area += Decimal(area)

    cr6_dwelling_min_samples = int(cr6_dwelling_cfg.get("relative", {}).get("min_samples", 5))
    cr6_dwelling_high_pct = float(cr6_dwelling_cfg.get("relative", {}).get("high_percentile", 0.99))
    cr6_dwelling_medium_pct = float(cr6_dwelling_cfg.get("relative", {}).get("medium_percentile", 0.95))
    cr6_dwelling_high_area = Decimal(str(cr6_dwelling_cfg.get("absolute", {}).get("high_area", 400)))
    cr6_dwelling_medium_area = Decimal(str(cr6_dwelling_cfg.get("absolute", {}).get("medium_area", 250)))
    cr6_dwelling_base_weight = float(cr6_dwelling_cfg.get("base_weight", 3.0))
    cr6_dwelling_confidence = float(cr6_dwelling_cfg.get("confidence", 0.8))

    cr6_agri_min_samples = int(cr6_agri_cfg.get("relative", {}).get("min_samples", 5))
    cr6_agri_high_pct = float(cr6_agri_cfg.get("relative", {}).get("high_percentile", 0.99))
    cr6_agri_medium_pct = float(cr6_agri_cfg.get("relative", {}).get("medium_percentile", 0.95))
    cr6_agri_high_area = Decimal(str(cr6_agri_cfg.get("absolute", {}).get("high_area", 500000)))
    cr6_agri_medium_area = Decimal(str(cr6_agri_cfg.get("absolute", {}).get("medium_area", 100000)))
    cr6_agri_base_weight = float(cr6_agri_cfg.get("base_weight", 3.0))
    cr6_agri_confidence = float(cr6_agri_cfg.get("confidence", 0.8))

    region_name = next(iter(real_estate_regions)) if len(real_estate_regions) == 1 else None
    dwelling_region_distribution: list[float] | None = None
    agri_region_distribution: list[float] | None = None
    if cohort_stats is not None and region_name:
        dwelling_region_distribution = list(
            (getattr(cohort_stats, "dwelling_areas_by_region", {}) or {}).get(region_name, [])
        )
        agri_region_distribution = list(
            (getattr(cohort_stats, "agri_areas_by_region", {}) or {}).get(region_name, [])
        )

    _dwelling_dist = list(getattr(cohort_stats, "dwelling_areas", [])) if cohort_stats is not None else []
    _agri_dist = list(getattr(cohort_stats, "agri_areas", [])) if cohort_stats is not None else []

    cr6_dwelling = _score_cr6_area(
        area_label="Total dwelling",
        area_value=dwelling_area,
        cohort_stats=cohort_stats,
        global_distribution=_dwelling_dist,
        region_distribution=dwelling_region_distribution,
        region_name=region_name,
        relative_min_samples=cr6_dwelling_min_samples,
        relative_high_pct=cr6_dwelling_high_pct,
        relative_medium_pct=cr6_dwelling_medium_pct,
        absolute_high_area=cr6_dwelling_high_area,
        absolute_medium_area=cr6_dwelling_medium_area,
        base_weight=cr6_dwelling_base_weight,
        confidence=cr6_dwelling_confidence,
    )
    if cr6_dwelling is not None:
        flags.append(cr6_dwelling)

    cr6_agri = _score_cr6_area(
        area_label="Agricultural land",
        area_value=agri_area,
        cohort_stats=cohort_stats,
        global_distribution=_agri_dist,
        region_distribution=agri_region_distribution,
        region_name=region_name,
        relative_min_samples=cr6_agri_min_samples,
        relative_high_pct=cr6_agri_high_pct,
        relative_medium_pct=cr6_agri_medium_pct,
        absolute_high_area=cr6_agri_high_area,
        absolute_medium_area=cr6_agri_medium_area,
        base_weight=cr6_agri_base_weight,
        confidence=cr6_agri_confidence,
    )
    if cr6_agri is not None:
        flags.append(cr6_agri)

    cr7_income_high_cutoff = Decimal(str(cr7_cfg.get("income_high_cutoff", 1000000)))
    cr7_income_medium_cutoff = Decimal(str(cr7_cfg.get("income_medium_cutoff", 600000)))
    cr7_vehicle_count_high = int(cr7_cfg.get("vehicle_count_high", 2))
    cr7_vehicle_count_medium = int(cr7_cfg.get("vehicle_count_medium", 1))
    cr7_vehicles_per_adult_high = float(cr7_cfg.get("vehicles_per_adult_high", 3.5))
    cr7_vehicles_per_adult_medium = float(cr7_cfg.get("vehicles_per_adult_medium", 2.5))
    cr7_low_income_cutoff = Decimal(str(cr7_cfg.get("low_income_cutoff_for_vehicle_density", 500000)))
    cr7_base_weight = float(cr7_cfg.get("base_weight", 3.0))
    cr7_confidence_income = float(cr7_cfg.get("confidence_income", 0.9))
    cr7_confidence_density = float(cr7_cfg.get("confidence_density", 0.8))

    luxury_count = 0
    for v in vehicles:
        brand_model = f"{v.get('brand') or ''} {v.get('model') or ''}".lower()
        if any(kw in brand_model for kw in (
            "bmw", "mercedes", "range rover", "porsche", "lexus", "audi", "tesla",
        )):
            luxury_count += 1

    if inc_val is not None:
        if luxury_count >= cr7_vehicle_count_high and inc_val < cr7_income_high_cutoff:
            flags.append(_make_flag(
                rule_id="CR7",
                category="corruption",
                severity="HIGH",
                base_weight=cr7_base_weight,
                confidence=cr7_confidence_income,
                message=f"{luxury_count} luxury vehicles with household income below {cr7_income_high_cutoff:,.0f} UAH.",
            ))
        elif luxury_count >= cr7_vehicle_count_medium and inc_val < cr7_income_medium_cutoff:
            flags.append(_make_flag(
                rule_id="CR7",
                category="corruption",
                severity="MEDIUM",
                base_weight=cr7_base_weight,
                confidence=cr7_confidence_income,
                message=f"Luxury vehicle ownership with household income below {cr7_income_medium_cutoff:,.0f} UAH.",
            ))

    child_markers = ("дит", "child", "син", "донь")
    adult_family = sum(1 for m in family_members if not _has_any_kw(m.get("relation"), child_markers))
    adults = max(1, 1 + adult_family)
    vehicles_per_adult = len(vehicles) / adults if adults else 0.0
    if vehicles_per_adult >= cr7_vehicles_per_adult_high:
        flags.append(_make_flag(
            rule_id="CR7",
            category="corruption",
            severity="HIGH",
            base_weight=cr7_base_weight,
            confidence=cr7_confidence_density,
            message=f"Vehicles per adult ratio is {vehicles_per_adult:.2f} (>= {cr7_vehicles_per_adult_high:g}).",
        ))
    elif inc_val is not None and inc_val < cr7_low_income_cutoff and vehicles_per_adult >= cr7_vehicles_per_adult_medium:
        flags.append(_make_flag(
            rule_id="CR7",
            category="corruption",
            severity="MEDIUM",
            base_weight=cr7_base_weight,
            confidence=cr7_confidence_density,
            message=f"Vehicles per adult ratio is {vehicles_per_adult:.2f} in a low-income household.",
        ))

    agri_machine = any(_has_any_kw(v.get("object_type"), ("тракт", "комбай", "harvest")) for v in vehicles)
    cr8_agri_area_min = Decimal(str(cr8_cfg.get("agri_area_min", 100000)))
    cr8_agri_area_high = Decimal(str(cr8_cfg.get("agri_area_high", 500000)))
    cr8_base_weight = float(cr8_cfg.get("base_weight", 3.0))
    cr8_confidence = float(cr8_cfg.get("confidence", 0.8))

    has_agri_assets = agri_area >= cr8_agri_area_min or agri_machine
    agri_income = Decimal(0)
    for i in incomes:
        txt = f"{i.get('income_type') or ''} {i.get('source_type') or ''} {i.get('income_type_other') or ''}".lower()
        if any(kw in txt for kw in ("агро", "ферм", "сг", "оренд", "rent")):
            amt = i.get("amount")
            if amt is not None:
                agri_income += Decimal(amt)
    if has_agri_assets and agri_income == 0:
        flags.append(_make_flag(
            rule_id="CR8",
            category="corruption",
            severity="HIGH" if agri_area >= cr8_agri_area_high else "MEDIUM",
            base_weight=cr8_base_weight,
            confidence=cr8_confidence,
            message="Agricultural assets detected without corresponding agri/rent income.",
        ))

    major_city_names = ("київ", "kyiv", "льв", "lviv", "одес", "odesa", "харк", "khark")
    commercial_count = 0
    city_apartment_count = 0
    for r in real_estate:
        obj = str(r.get("object_type") or "").lower()
        city = str(r.get("city") or "").lower()
        if any(kw in obj for kw in ("нежит", "офіс", "магаз", "комер")):
            commercial_count += 1
        if "кварт" in obj and any(c in city for c in major_city_names):
            city_apartment_count += 1
    rent_income = Decimal(0)
    for i in incomes:
        txt = f"{i.get('income_type') or ''} {i.get('source_type') or ''} {i.get('income_type_other') or ''}".lower()
        if any(kw in txt for kw in ("оренд", "rent", "бізнес", "business", "підприєм")):
            amt = i.get("amount")
            if amt is not None:
                rent_income += Decimal(amt)
    cr9_low_rent_income = Decimal(str(cr9_cfg.get("low_rent_income", 30000)))
    cr9_high_object_count = int(cr9_cfg.get("high_object_count", 3))
    cr9_base_weight = float(cr9_cfg.get("base_weight", 3.0))
    cr9_confidence = float(cr9_cfg.get("confidence", 0.7))

    rentable_objects = commercial_count + city_apartment_count
    if rentable_objects > 0 and rent_income < cr9_low_rent_income:
        flags.append(_make_flag(
            rule_id="CR9",
            category="corruption",
            severity="HIGH" if rentable_objects >= cr9_high_object_count else "MEDIUM",
            base_weight=cr9_base_weight,
            confidence=cr9_confidence,
            message=f"{rentable_objects} potentially rentable objects with low/no rent-business income.",
        ))

    major_unknown_count = 0
    largest_dwelling_unknown = False
    largest_dwelling_area = Decimal(0)
    for r in real_estate:
        obj = str(r.get("object_type") or "").lower()
        status = str(r.get("cost_assessment_status") or "")
        if any(kw in obj for kw in ("кварт", "буд", "жит", "зем")) and status in {"unknown", "family_no_info", "confidential", "redacted_other"}:
            major_unknown_count += 1
        area = r.get("total_area")
        if area is not None and any(kw in obj for kw in ("кварт", "буд", "жит")):
            area_d = Decimal(area)
            if area_d > largest_dwelling_area:
                largest_dwelling_area = area_d
                largest_dwelling_unknown = status in {"unknown", "family_no_info", "confidential", "redacted_other"}
    cr10_high_major_unknown_count = int(cr10_cfg.get("high_major_unknown_count", 2))
    cr10_base_weight = float(cr10_cfg.get("base_weight", 4.0))
    cr10_confidence = float(cr10_cfg.get("confidence", 0.9))

    if largest_dwelling_unknown or major_unknown_count >= 1:
        sev = "HIGH" if (major_unknown_count >= cr10_high_major_unknown_count or largest_dwelling_unknown and major_unknown_count >= 1) else "MEDIUM"
        flags.append(_make_flag(
            rule_id="CR10",
            category="opacity",
            severity=sev,
            base_weight=cr10_base_weight,
            confidence=cr10_confidence,
            message="Unknown valuations detected on major assets.",
        ))

    # CR11: spouse/child major ownership with low independent income.
    relation_by_id: dict[str, str] = {str(m.get("member_id")): str(m.get("relation") or "") for m in family_members}
    income_by_person: dict[str, Decimal] = {}
    for i in incomes:
        pr = i.get("person_ref")
        amt = i.get("amount")
        if pr is None or amt is None:
            continue
        k = str(pr)
        income_by_person[k] = income_by_person.get(k, Decimal(0)) + Decimal(amt)

    cr11_major_ownership_percent = float(cr11_cfg.get("major_ownership_percent", 99.0))
    cr11_major_asset_cost_min = Decimal(str(cr11_cfg.get("major_asset_cost_min", 500000)))
    cr11_income_max = Decimal(str(cr11_cfg.get("income_max", 100000)))
    cr11_monetary_asset_min = Decimal(str(cr11_cfg.get("monetary_asset_min", 500000)))
    cr11_base_weight = float(cr11_cfg.get("base_weight", 5.0))
    cr11_confidence = float(cr11_cfg.get("confidence", 0.8))

    major_proxy_detected = False
    for r in real_estate:
        pid = str(r.get("right_belongs_raw") or "")
        rel = relation_by_id.get(pid, "").lower()
        if pid in relation_by_id and any(kw in rel for kw in ("друж", "чолов", "дит", "child", "син", "дон")):
            pct = str(r.get("percent_ownership") or "").replace(",", ".")
            try:
                pct_v = float(pct)
            except ValueError:
                pct_v = None
            obj = str(r.get("object_type") or "").lower()
            is_main = any(kw in obj for kw in ("кварт", "буд", "жит"))
            cost = r.get("cost_assessment")
            if (pct_v is not None and pct_v >= cr11_major_ownership_percent and (is_main or (cost is not None and Decimal(cost) >= cr11_major_asset_cost_min))):
                if income_by_person.get(pid, Decimal(0)) < cr11_income_max:
                    major_proxy_detected = True
                    break
    if not major_proxy_detected:
        for m in monetary_assets:
            pid = str(m.get("person_ref") or "")
            rel = relation_by_id.get(pid, "").lower()
            if pid in relation_by_id and any(kw in rel for kw in ("друж", "чолов", "дит", "child", "син", "дон")):
                amt_uah = to_uah(m.get("amount"), m.get("currency_code"))
                if amt_uah is not None and amt_uah >= cr11_monetary_asset_min and income_by_person.get(pid, Decimal(0)) < cr11_income_max:
                    major_proxy_detected = True
                    break
    if major_proxy_detected:
        flags.append(_make_flag(
            rule_id="CR11",
            category="corruption",
            severity="HIGH",
            base_weight=cr11_base_weight,
            confidence=cr11_confidence,
            message="Spouse/child appears as major asset owner with low independent income.",
        ))

    assets_by_person = _asset_totals_by_person(real_estate, monetary_assets)
    cr12 = _cr12_wealth_concentration(
        relation_by_id=relation_by_id,
        income_by_person=income_by_person,
        assets_by_person=assets_by_person,
    )
    if cr12.triggered:
        flags.append(cr12)

    # CR13: repeated family-no-info on key fields.
    family_no_info_count = 0
    for r in real_estate:
        pid = str(r.get("right_belongs_raw") or "")
        if pid in family_ids:
            if r.get("cost_assessment_status") == "family_no_info":
                family_no_info_count += 1
            if r.get("total_area_status") == "family_no_info":
                family_no_info_count += 1
    for m in monetary_assets:
        pid = str(m.get("person_ref") or "")
        if pid in family_ids:
            if m.get("amount_status") == "family_no_info":
                family_no_info_count += 1
            if m.get("organization_status") == "family_no_info":
                family_no_info_count += 1
    cr13_minimum_count = int(cr13_cfg.get("minimum_count", 3))
    cr13_base_weight = float(cr13_cfg.get("base_weight", 5.0))
    cr13_confidence = float(cr13_cfg.get("confidence", 1.0))
    if family_no_info_count >= cr13_minimum_count:
        flags.append(_make_flag(
            rule_id="CR13",
            category="opacity",
            severity="HIGH",
            base_weight=cr13_base_weight,
            confidence=cr13_confidence,
            message=f"Family no-information markers appear {family_no_info_count} times on key asset fields.",
        ))

    # ------------------------------
    # CR16 — Cohort-relative outliers
    # ------------------------------
    if cohort_stats is not None:
        cr16_min_samples = int(cr16_cfg.get("minimum_samples", 5))
        cr16_income_high_pct = float(cr16_cfg.get("income_percentile_high", 0.99))
        cr16_assets_high_pct = float(cr16_cfg.get("assets_percentile_high", 0.99))
        cr16_assets_medium_pct = float(cr16_cfg.get("assets_percentile_medium", 0.95))
        cr16_cash_high_pct = float(cr16_cfg.get("cash_percentile_high", 0.99))
        cr16_cash_fx_share_min = float(cr16_cfg.get("cash_fx_share_min", 0.5))
        cr16_confidential_min_samples = int(cr16_cfg.get("confidential_min_samples", 5))
        cr16_confidential_ratio_multiplier = float(cr16_cfg.get("confidential_ratio_multiplier", 2.0))
        cr16_confidential_ratio_high_multiplier = float(cr16_cfg.get("confidential_ratio_high_multiplier", 3.0))
        cr16_base_weight = float(cr16_cfg.get("base_weight", 3.0))
        cr16_confidence = float(cr16_cfg.get("confidence", 0.8))

        # Income outlier — top 1% of cohort
        if inc_val is not None and len(getattr(cohort_stats, 'incomes', [])) >= cr16_min_samples:
            pct = compute_percentile_rank(float(inc_val), cohort_stats.incomes)
            if pct >= cr16_income_high_pct:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="MEDIUM",
                    base_weight=cr16_base_weight,
                    confidence=cr16_confidence,
                    message=f"Household income is at {pct:.0%} percentile of cohort peers.",
                ))

        # Wealth outlier — top 1% HIGH, top 5% MEDIUM
        if total_assets is not None and len(getattr(cohort_stats, 'assets', [])) >= cr16_min_samples:
            assets_float = float(total_assets)
            pct = compute_percentile_rank(assets_float, cohort_stats.assets)
            if pct >= cr16_assets_high_pct:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="HIGH",
                    base_weight=cr16_base_weight,
                    confidence=cr16_confidence,
                    message=f"Total assets at {pct:.0%} percentile of cohort peers (top 1%).",
                ))
            elif pct >= cr16_assets_medium_pct:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="MEDIUM",
                    base_weight=cr16_base_weight,
                    confidence=cr16_confidence,
                    message=f"Total assets at {pct:.0%} percentile of cohort peers (top 5%).",
                ))

        # Cash outlier — top 1% with high FX share
        if cash_holdings is not None and len(getattr(cohort_stats, 'cash_ratios', [])) >= cr16_min_samples:
            cash_float = float(cash_holdings)
            cash_pct = compute_percentile_rank(
                cash_float / float(inc_val) if inc_val and inc_val > 0 else 0.0,
                cohort_stats.cash_ratios,
            )
            if cash_pct >= cr16_cash_high_pct and fx_share >= cr16_cash_fx_share_min:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="HIGH",
                    base_weight=cr16_base_weight,
                    confidence=cr16_confidence,
                    message=f"Cash-to-income ratio at {cash_pct:.0%} percentile with {fx_share:.0%} FX concentration.",
                ))

        # BR3: confidential marker density > 2x cohort median.
        conf_distribution = getattr(cohort_stats, "confidential_ratios", [])
        if len(conf_distribution) >= cr16_confidential_min_samples:
            decl_conf_ratio = _confidential_ratio_from_rows(incomes, monetary_assets, real_estate)
            cohort_median = get_percentile_value(conf_distribution, 0.5)
            if cohort_median > 0 and decl_conf_ratio > cr16_confidential_ratio_multiplier * cohort_median:
                severity = "MEDIUM" if decl_conf_ratio > cr16_confidential_ratio_high_multiplier * cohort_median else "LOW"
                flags.append(_make_flag(
                    rule_id="BR3",
                    category="opacity",
                    severity=severity,
                    base_weight=1,
                    confidence=0.7,
                    message=(
                        f"Confidential marker density ({decl_conf_ratio:.0%}) exceeds 2x cohort median "
                        f"({cohort_median:.0%})."
                    ),
                ))

    layer2_rules = score_declaration_l2(
        total_income=total_income,
        total_assets=total_assets,
        cash_ratio=cash_holdings / (cash_holdings + bank_deposits) if cash_holdings is not None and bank_deposits is not None and (cash_holdings + bank_deposits) > 0 else None,
        confidential_ratio=_confidential_ratio_from_rows(incomes, monetary_assets, real_estate),
        dwelling_area_m2=dwelling_area if dwelling_area > 0 else None,
        agri_area_m2=agri_area if agri_area > 0 else None,
        cohort=cohort_stats,
        year=declaration_year,
        sector=declaration_sector,
        government_level=declaration_gov_level,
        primary_region=declaration_region,
        cohort_resolver=cohort_resolver,
        fallback_cohort_key=cohort_key_used,
    )
    for layer2_rule in layer2_rules:
        if not layer2_rule.triggered:
            continue
        if layer2_rule.rule_name not in {
            "cohort_cash_ratio_outlier",
            "cohort_confidential_ratio_outlier",
            "cohort_dwelling_area_outlier",
            "cohort_agri_area_outlier",
        }:
            continue
        flags.append(RuleResult(
            rule_name=layer2_rule.rule_name,
            score=layer2_rule.score,
            triggered=True,
            explanation=layer2_rule.explanation,
            category="opacity" if layer2_rule.rule_name == "cohort_confidential_ratio_outlier" else "corruption",
            severity="MEDIUM",
            confidence=1.0,
        ))

    if getattr(settings, "layer3_enabled", False) and getattr(settings, "layer3_model_path", ""):
        try:
            feature_map = layer3_inference.build_feature_vector(
                total_income=total_income,
                total_assets=total_assets,
                cash_holdings=cash_holdings,
                bank_deposits=bank_deposits,
                total_value_fields=total_value_fields,
                unknown_value_fields=unknown_value_fields,
                ownership_declarant=ownership_declarant,
                ownership_family=ownership_family,
                ownership_total=ownership_total,
                declaration_year=declaration_year,
                incomes_count=len(incomes),
                real_estate_count=len(real_estate),
                vehicles_count=len(vehicles),
                monetary_count=len(monetary_assets),
                confidential_ratio=_confidential_ratio_from_rows(incomes, monetary_assets, real_estate),
            )
            layer3_result = layer3_inference.infer_anomaly(
                feature_map=feature_map,
                model_path=str(getattr(settings, "layer3_model_path", "")),
                sector=declaration_sector,
                government_level=declaration_gov_level,
            )
        except Exception:
            layer3_result = None

        if layer3_result is not None and layer3_result.anomaly_score >= float(getattr(settings, "layer3_trigger_threshold", 0.72)):
            max_points = float(getattr(settings, "layer3_max_points", 10.0))
            flags.append(RuleResult(
                rule_name="ML1",
                score=round(min(max_points, layer3_result.anomaly_score * max_points), 3),
                triggered=True,
                explanation=(
                    f"Layer 3 anomaly score {layer3_result.anomaly_score:.0%} "
                    f"exceeded trigger threshold {float(getattr(settings, 'layer3_trigger_threshold', 0.72)):.0%}."
                ),
                category="corruption",
                severity="MEDIUM",
                confidence=layer3_result.confidence,
                metadata={
                    "anomaly_score": layer3_result.anomaly_score,
                    "confidence": layer3_result.confidence,
                    "percentile": layer3_result.percentile,
                    "top_deviations": layer3_result.top_deviations,
                },
            ))

    triggered_ids = {r.rule_name for r in flags}
    if "CR11" in triggered_ids and "CR12" in triggered_ids:
        flags.append(_make_flag(
            rule_id="IB_CR11_CR12",
            category="corruption",
            severity="MEDIUM",
            base_weight=float(interaction_bonuses.get("cr11_cr12", 3.0)),
            confidence=1.0,
            message="Interaction bonus applied for CR11 + CR12 (proxy ownership with wealth concentration).",
        ))

    # ------------------------------
    # Aggregation and weighted total
    # ------------------------------
    raw_total_divisor = float(aggregation_cfg.get("raw_total_divisor", 12.0))
    corruption_to_opacity_weight = float(aggregation_cfg.get("corruption_to_opacity_weight", 0.5))
    quality_to_total_weight = float(aggregation_cfg.get("quality_to_total_weight", 0.1))
    quality_cap = float(aggregation_cfg.get("quality_cap", 2.0))
    opacity_cap_when_no_corruption_ratio = float(aggregation_cfg.get("opacity_cap_when_no_corruption_ratio", 0.25))
    interaction_bonuses = aggregation_cfg.get("interaction_bonuses", {}) if isinstance(aggregation_cfg, dict) else {}

    raw_corruption = sum(r.score for r in flags if r.category == "corruption")
    raw_opacity = sum(r.score for r in flags if r.category == "opacity")
    raw_quality = sum(r.score for r in flags if r.category == "data_quality")

    raw_quality_capped = min(quality_cap, raw_quality)

    if raw_corruption <= 0 and raw_opacity > 0:
        raw_opacity = min(raw_opacity, raw_corruption * opacity_cap_when_no_corruption_ratio)

    interaction_bonus = 0.0
    if "CR1" in triggered_ids and "CR2" in triggered_ids:
        interaction_bonus += float(interaction_bonuses.get("cr1_cr2", 3.0))
    if "CR10" in triggered_ids and "CR13" in triggered_ids:
        interaction_bonus += float(interaction_bonuses.get("cr10_cr13", 3.0))

    raw_total = raw_corruption + corruption_to_opacity_weight * raw_opacity + quality_to_total_weight * raw_quality_capped + interaction_bonus
    overall_100 = 100.0 * (1.0 - math.exp(-raw_total / raw_total_divisor)) if raw_total > 0 else 0.0
    overall_100 = round(overall_100, 2)

    triggered: list[str] = []
    seen_rules: set[str] = set()
    for r in flags:
        if r.triggered and r.rule_name not in seen_rules:
            triggered.append(r.rule_name)
            seen_rules.add(r.rule_name)

    return ScoringResult(
        total_score=overall_100,
        rule_results=flags,
        triggered_rules=triggered,
        corruption_risk_score=round(raw_corruption, 3),
        opacity_evasion_score=round(raw_opacity, 3),
        data_quality_score=round(raw_quality_capped, 3),
        raw_total_score=round(raw_total, 3),
    )


# ---------------------------------------------------------------------------
# Layer 1 — Temporal rules (require multi-year timeline)
# ---------------------------------------------------------------------------

def year_over_year_income_change(
    prev_income: Decimal | None,
    curr_income: Decimal | None,
    *,
    growth_threshold: float = _cfg(
        "layer1", "timeline", "yoy_income_change", "growth_threshold", default=3.0
    ),
    drop_threshold: float = _cfg(
        "layer1", "timeline", "yoy_income_change", "drop_threshold", default=0.25
    ),
) -> RuleResult:
    """Flag abnormal year-over-year income changes.

    Triggers on both large unexplained growth (>3x) AND large unexplained
    drops (<25% of prior year), either of which can be a signal worth review.
    """
    rule = "yoy_income_change"

    if prev_income is None or curr_income is None:
        return RuleResult(rule, 0.0, False, "Insufficient data for year-over-year comparison.")

    if prev_income <= 0:
        if curr_income > 0:
            return RuleResult(
                rule, 0.5, True,
                f"Income appeared ({curr_income:,.0f}) from zero — check for prior-year gaps."
            )
        return RuleResult(rule, 0.0, False, "No income in either year.")

    ratio = float(curr_income / prev_income)

    if ratio > growth_threshold:
        score = min(1.0, (ratio - growth_threshold) / growth_threshold)
        return RuleResult(
            rule, round(score, 3), True,
            f"Income grew {ratio:.1f}x year-over-year "
            f"({prev_income:,.0f} → {curr_income:,.0f})."
        )

    if ratio < drop_threshold:
        score = round(min(1.0, (drop_threshold - ratio) / drop_threshold), 3)
        return RuleResult(
            rule, score, True,
            f"Income dropped to {ratio:.0%} of prior year "
            f"({prev_income:,.0f} → {curr_income:,.0f})."
        )

    return RuleResult(
        rule, 0.0, False,
        f"Income changed {ratio:.1f}x year-over-year, within normal range."
    )


def year_over_year_asset_growth(
    prev_assets: Decimal | None,
    curr_assets: Decimal | None,
    prev_income: Decimal | None,
    *,
    threshold_ratio: float = _cfg(
        "layer1", "timeline", "yoy_asset_growth", "threshold_ratio", default=3.0
    ),
) -> RuleResult:
    """Flag unexplained growth in monetary assets relative to prior year.

    Compares asset increase to declared income: if assets grew far more than
    income can explain, that is the anomaly signal.
    """
    rule = "yoy_asset_growth"

    if prev_assets is None or curr_assets is None:
        return RuleResult(rule, 0.0, False, "Insufficient data for year-over-year comparison.")

    if prev_assets <= 0 and curr_assets <= 0:
        return RuleResult(rule, 0.0, False, "No monetary assets in either year.")

    asset_delta = curr_assets - prev_assets
    if asset_delta <= 0:
        return RuleResult(
            rule, 0.0, False,
            f"Monetary assets did not grow ({prev_assets:,.0f} → {curr_assets:,.0f})."
        )

    # If income is known, compare delta to income
    if prev_income is not None and prev_income > 0:
        excess = asset_delta - prev_income
        if excess > 0:
            ratio = float(asset_delta / prev_income)
            if ratio > threshold_ratio:
                score = min(1.0, (ratio - threshold_ratio) / threshold_ratio)
                return RuleResult(
                    rule, round(score, 3), True,
                    f"Monetary assets grew by {asset_delta:,.0f}, which is {ratio:.1f}x "
                    f"declared income ({prev_income:,.0f}) — unexplained accumulation."
                )
        return RuleResult(
            rule, 0.0, False,
            f"Asset growth of {asset_delta:,.0f} is consistent with declared income."
        )

    # No income to compare — flag if assets grew more than 3x
    if prev_assets > 0:
        ratio = float(curr_assets / prev_assets)
        if ratio > threshold_ratio:
            score = min(1.0, (ratio - threshold_ratio) / threshold_ratio)
            return RuleResult(
                rule, round(score, 3), True,
                f"Monetary assets grew {ratio:.1f}x ({prev_assets:,.0f} → {curr_assets:,.0f}) "
                f"with no declared income to explain the increase."
            )

    return RuleResult(rule, 0.0, False, "Asset growth within observable range.")


def foreign_cash_jump(
    prev_cash: Decimal | None,
    curr_cash: Decimal | None,
    *,
    threshold_uah: float = _cfg(
        "layer1", "timeline", "foreign_cash_jump", "threshold_uah", default=200_000
    ),
) -> RuleResult:
    """Flag sudden large increases in cash holdings.

    A large absolute cash increase with no corresponding movement in bank
    deposits is a liquidity anomaly worth flagging.
    """
    rule = "foreign_cash_jump"

    if prev_cash is None or curr_cash is None:
        return RuleResult(rule, 0.0, False, "Cash data unavailable for comparison.")

    delta = curr_cash - prev_cash
    if delta <= 0:
        return RuleResult(rule, 0.0, False, "Cash holdings did not increase year-over-year.")

    if float(delta) > threshold_uah:
        score = min(1.0, float(delta) / (threshold_uah * 5))
        return RuleResult(
            rule, round(score, 3), True,
            f"Cash holdings increased by {delta:,.0f} UAH year-over-year "
            f"(from {prev_cash:,.0f} to {curr_cash:,.0f})."
        )

    return RuleResult(
        rule, 0.0, False,
        f"Cash increase of {delta:,.0f} UAH is below the threshold."
    )


# ---------------------------------------------------------------------------
# CR5 — Asset growth vs income growth (timeline rule)
# ---------------------------------------------------------------------------

def cr5_asset_vs_income_growth(change: Any) -> RuleResult:
    """CR5: Flag when assets grow significantly faster than income.

    Parameters
    ----------
    change:
        A ``YOYChange`` with ``asset_growth`` and ``income_growth``.
    """
    rule = "CR5"

    high_asset_growth = float(
        _cfg("layer1", "timeline", "cr5_asset_vs_income_growth", "high_asset_growth", default=0.5)
    )
    high_income_growth_max = float(
        _cfg("layer1", "timeline", "cr5_asset_vs_income_growth", "high_income_growth_max", default=0.1)
    )
    medium_asset_growth = float(
        _cfg("layer1", "timeline", "cr5_asset_vs_income_growth", "medium_asset_growth", default=0.2)
    )
    medium_income_growth_max = float(
        _cfg("layer1", "timeline", "cr5_asset_vs_income_growth", "medium_income_growth_max", default=0.0)
    )
    base_weight = float(_cfg("layer1", "timeline", "cr5_asset_vs_income_growth", "base_weight", default=5.0))
    confidence_high = float(_cfg("layer1", "timeline", "cr5_asset_vs_income_growth", "confidence_high", default=0.9))
    confidence_medium = float(_cfg("layer1", "timeline", "cr5_asset_vs_income_growth", "confidence_medium", default=0.8))

    ag = change.asset_growth
    ig = change.income_growth

    if ag is None:
        return RuleResult(rule, 0.0, False, "Insufficient asset data for growth comparison.")

    if ag >= high_asset_growth and (ig is None or ig <= high_income_growth_max):
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="HIGH",
            base_weight=base_weight,
            confidence=confidence_high,
            message=(
                f"Assets grew {ag:.0%} year-over-year ({change.from_year}→{change.to_year}) "
                f"while income grew only {ig:.0%}." if ig is not None
                else f"Assets grew {ag:.0%} ({change.from_year}→{change.to_year}) with no income data."
            ),
        )

    if ag >= medium_asset_growth and ig is not None and ig <= medium_income_growth_max:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="MEDIUM",
            base_weight=base_weight,
            confidence=confidence_medium,
            message=(
                f"Assets grew {ag:.0%} ({change.from_year}→{change.to_year}) "
                f"while income declined by {ig:.0%}."
            ),
        )

    return RuleResult(rule, 0.0, False, "Asset and income growth within normal range.")


# ---------------------------------------------------------------------------
# BR2 — Growth in share of unknown values over time (timeline rule)
# ---------------------------------------------------------------------------

def br2_unknown_share_growth(change: Any) -> RuleResult:
    """BR2: Flag when the share of unknown/hidden values increases over time.

    Parameters
    ----------
    change:
        A ``YOYChange`` with ``unknown_share_prev``, ``unknown_share_curr``,
        ``unknown_share_delta``.
    """
    rule = "BR2"

    delta_threshold = float(
        _cfg("layer1", "timeline", "br2_unknown_share_growth", "delta_threshold", default=0.3)
    )
    current_threshold = float(
        _cfg("layer1", "timeline", "br2_unknown_share_growth", "current_threshold", default=0.5)
    )
    base_weight = float(_cfg("layer1", "timeline", "br2_unknown_share_growth", "base_weight", default=2.0))
    confidence = float(_cfg("layer1", "timeline", "br2_unknown_share_growth", "confidence", default=0.9))

    delta = change.unknown_share_delta
    curr = change.unknown_share_curr

    if delta >= delta_threshold and curr >= current_threshold:
        return _make_flag(
            rule_id=rule,
            category="opacity",
            severity="MEDIUM",
            base_weight=base_weight,
            confidence=confidence,
            message=(
                f"Unknown-value share rose from {change.unknown_share_prev:.0%} "
                f"to {curr:.0%} ({change.from_year}→{change.to_year}) — "
                f"increasing opacity trend."
            ),
        )

    return RuleResult(rule, 0.0, False, "Unknown-value share trend within normal range.")


# ---------------------------------------------------------------------------
# BR4 — Role change followed by wealth jump (timeline rule)
# ---------------------------------------------------------------------------

def br4_role_change_wealth_jump(change: Any) -> RuleResult:
    """BR4: Flag when a role change is followed by significant asset growth.

    Parameters
    ----------
    change:
        A ``YOYChange`` with ``role_changed`` and ``asset_growth``.
    """
    rule = "BR4"

    high_asset_growth = float(
        _cfg("layer1", "timeline", "br4_role_change_wealth_jump", "high_asset_growth", default=1.0)
    )
    medium_asset_growth = float(
        _cfg("layer1", "timeline", "br4_role_change_wealth_jump", "medium_asset_growth", default=0.5)
    )
    base_weight = float(_cfg("layer1", "timeline", "br4_role_change_wealth_jump", "base_weight", default=2.0))
    confidence_high = float(_cfg("layer1", "timeline", "br4_role_change_wealth_jump", "confidence_high", default=0.8))
    confidence_medium = float(_cfg("layer1", "timeline", "br4_role_change_wealth_jump", "confidence_medium", default=0.7))

    if not change.role_changed:
        return RuleResult(rule, 0.0, False, "No role change detected.")

    ag = change.asset_growth
    if ag is None:
        return RuleResult(rule, 0.0, False, "Role changed but no asset data for comparison.")

    if ag >= high_asset_growth:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="HIGH",
            base_weight=base_weight,
            confidence=confidence_high,
            message=(
                f"Role changed ({change.from_year}→{change.to_year}) with "
                f"assets growing {ag:.0%} — major post-promotion wealth jump."
            ),
        )

    if ag >= medium_asset_growth:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="MEDIUM",
            base_weight=base_weight,
            confidence=confidence_medium,
            message=(
                f"Role changed ({change.from_year}→{change.to_year}) with "
                f"assets growing {ag:.0%} — significant post-promotion wealth increase."
            ),
        )

    return RuleResult(rule, 0.0, False, "Role changed but asset growth within normal range.")


# ---------------------------------------------------------------------------
# Timeline composite scorer
# ---------------------------------------------------------------------------

@dataclass
class TimelineScoringResult:
    """Scoring result for a multi-year person timeline.

    ``total_score`` is on a native 0–100 scale.
    """

    total_score: float  # 0–100 scale
    rule_results: list[RuleResult] = field(default_factory=list)
    triggered_rules: list[str] = field(default_factory=list)

    @property
    def explanation_summary(self) -> str:
        if not self.triggered_rules:
            return "No temporal anomaly signals detected."
        lines = [f"• {r.explanation}" for r in self.rule_results if r.triggered]
        return "\n".join(lines)


def score_timeline(timeline: "PersonTimeline") -> TimelineScoringResult:
    """Run temporal scoring rules against a PersonTimeline.

    Evaluates the worst-case year-over-year change across all consecutive
    pairs and also runs CR5, BR2, and BR4 rules.

    Returns a ``TimelineScoringResult`` on a 0–100 scale.
    """
    from app.normalization.assemble_timeline import PersonTimeline as TL

    layer1_cfg = SCORING_CONFIG.get("layer1", {}) if isinstance(SCORING_CONFIG, dict) else {}
    aggregation_cfg = layer1_cfg.get("aggregation", {}) if isinstance(layer1_cfg, dict) else {}

    if (
        not timeline.changes
        and not getattr(timeline, "snapshots", None)
        and not (getattr(timeline, "declarations_per_year", None) or {})
    ):
        return TimelineScoringResult(total_score=0.0)

    # --- Existing YOY rules (worst-case across all pairs) ---
    worst_income_rule = RuleResult("yoy_income_change", 0.0, False, "No changes to assess.")
    worst_asset_rule = RuleResult("yoy_asset_growth", 0.0, False, "No changes to assess.")
    worst_cash_rule = RuleResult("foreign_cash_jump", 0.0, False, "No changes to assess.")

    # --- New timeline rules (CR5, BR2, BR4) —  worst-case across all pairs ---
    worst_cr5 = RuleResult("CR5", 0.0, False, "No changes to assess.")
    worst_br2 = RuleResult("BR2", 0.0, False, "No changes to assess.")
    worst_br4 = RuleResult("BR4", 0.0, False, "No changes to assess.")
    worst_cr14 = RuleResult("CR14", 0.0, False, "No changes to assess.")
    worst_cr6 = RuleResult("CR6", 0.0, False, "No real-estate footprint data to assess.")
    br1 = _br1_many_corrected(timeline)
    cr15 = _cr15_real_estate_income_3y(timeline)

    interaction_bonuses = aggregation_cfg.get("interaction_bonuses", {}) if isinstance(aggregation_cfg, dict) else {}
    cr14_bonus_threshold = Decimal(str(interaction_bonuses.get("cr14_no_one_off_fraction", 0.5)))
    cr14_bonus_triggered = False

    cohort_stats = getattr(timeline, "cohort_stats", None)
    timeline_snapshots = list(getattr(timeline, "snapshots", []) or [])

    for change in timeline.changes:
        ir = year_over_year_income_change(change.income_prev, change.income_curr)
        if ir.score > worst_income_rule.score:
            worst_income_rule = ir

        ar = year_over_year_asset_growth(
            change.monetary_prev, change.monetary_curr, change.income_prev
        )
        if ar.score > worst_asset_rule.score:
            worst_asset_rule = ar

        cr = foreign_cash_jump(change.cash_prev, change.cash_curr)
        if cr.score > worst_cash_rule.score:
            worst_cash_rule = cr

        # CR5
        c5 = cr5_asset_vs_income_growth(change)
        if c5.score > worst_cr5.score:
            worst_cr5 = c5

        # BR2
        b2 = br2_unknown_share_growth(change)
        if b2.score > worst_br2.score:
            worst_br2 = b2

        # BR4
        b4 = br4_role_change_wealth_jump(change)
        if b4.score > worst_br4.score:
            worst_br4 = b4

        # CR14
        c14 = _cr14_asset_appearance_disappearance(change)
        if c14.score > worst_cr14.score:
            worst_cr14 = c14
        if c14.triggered:
            appeared_value = None
            if getattr(change, "major_assets_appeared", 0) and getattr(change, "max_appeared_value", None) is not None:
                appeared_value = Decimal(str(change.max_appeared_value))
            elif getattr(change, "major_assets_disappeared", 0) and getattr(change, "max_disappeared_value", None) is not None:
                appeared_value = Decimal(str(change.max_disappeared_value))
            one_off_income = getattr(change, "one_off_income_curr", Decimal(0)) or Decimal(0)
            if appeared_value is not None and one_off_income < appeared_value * cr14_bonus_threshold:
                cr14_bonus_triggered = True

    for snapshot in timeline_snapshots:
        dwelling_area = getattr(snapshot, "dwelling_area", None)
        agri_area = getattr(snapshot, "agri_area", None)
        if dwelling_area is None and agri_area is None:
            continue
        region_name = _normalize_region_key(getattr(snapshot, "region", None))
        dwelling_dist = list(getattr(cohort_stats, "dwelling_areas", [])) if cohort_stats is not None else []
        agri_dist = list(getattr(cohort_stats, "agri_areas", [])) if cohort_stats is not None else []
        dwelling_region_dist = None
        agri_region_dist = None
        if cohort_stats is not None and region_name:
            dwelling_region_dist = list((getattr(cohort_stats, "dwelling_areas_by_region", {}) or {}).get(region_name, []))
            agri_region_dist = list((getattr(cohort_stats, "agri_areas_by_region", {}) or {}).get(region_name, []))

        if dwelling_area is not None:
            cr6_d = _score_cr6_area(
                area_label="Total dwelling",
                area_value=Decimal(str(dwelling_area)),
                cohort_stats=cohort_stats,
                global_distribution=dwelling_dist,
                region_distribution=dwelling_region_dist,
                region_name=region_name,
                relative_min_samples=int(_cfg("layer1", "corruption", "cr6_dwelling_area", "relative", "min_samples", default=5)),
                relative_high_pct=float(_cfg("layer1", "corruption", "cr6_dwelling_area", "relative", "high_percentile", default=0.99)),
                relative_medium_pct=float(_cfg("layer1", "corruption", "cr6_dwelling_area", "relative", "medium_percentile", default=0.95)),
                absolute_high_area=Decimal(str(_cfg("layer1", "corruption", "cr6_dwelling_area", "absolute", "high_area", default=400))),
                absolute_medium_area=Decimal(str(_cfg("layer1", "corruption", "cr6_dwelling_area", "absolute", "medium_area", default=250))),
                base_weight=float(_cfg("layer1", "corruption", "cr6_dwelling_area", "base_weight", default=3.0)),
                confidence=float(_cfg("layer1", "corruption", "cr6_dwelling_area", "confidence", default=0.8)),
            )
            if cr6_d is not None and cr6_d.score > worst_cr6.score:
                worst_cr6 = cr6_d

        if agri_area is not None:
            cr6_a = _score_cr6_area(
                area_label="Agricultural land",
                area_value=Decimal(str(agri_area)),
                cohort_stats=cohort_stats,
                global_distribution=agri_dist,
                region_distribution=agri_region_dist,
                region_name=region_name,
                relative_min_samples=int(_cfg("layer1", "corruption", "cr6_agricultural_area", "relative", "min_samples", default=5)),
                relative_high_pct=float(_cfg("layer1", "corruption", "cr6_agricultural_area", "relative", "high_percentile", default=0.99)),
                relative_medium_pct=float(_cfg("layer1", "corruption", "cr6_agricultural_area", "relative", "medium_percentile", default=0.95)),
                absolute_high_area=Decimal(str(_cfg("layer1", "corruption", "cr6_agricultural_area", "absolute", "high_area", default=500000))),
                absolute_medium_area=Decimal(str(_cfg("layer1", "corruption", "cr6_agricultural_area", "absolute", "medium_area", default=100000))),
                base_weight=float(_cfg("layer1", "corruption", "cr6_agricultural_area", "base_weight", default=3.0)),
                confidence=float(_cfg("layer1", "corruption", "cr6_agricultural_area", "confidence", default=0.8)),
            )
            if cr6_a is not None and cr6_a.score > worst_cr6.score:
                worst_cr6 = cr6_a

    rules = [
        worst_income_rule, worst_asset_rule, worst_cash_rule,
        worst_cr5, worst_br2, worst_br4, worst_cr14, worst_cr6,
        br1, cr15,
    ]

    if worst_cr14.triggered and cr14_bonus_triggered:
        rules.append(_make_flag(
            rule_id="IB_CR14_NO_ONE_OFF",
            category="corruption",
            severity="MEDIUM",
            base_weight=float(interaction_bonuses.get("cr14_no_one_off", 2.0)),
            confidence=1.0,
            message="CR14 triggered without matching one-off income of at least 50% of the asset value.",
        ))
    if worst_cr6.triggered and cr15.triggered:
        rules.append(_make_flag(
            rule_id="IB_CR6_CR15",
            category="corruption",
            severity="MEDIUM",
            base_weight=float(interaction_bonuses.get("cr6_cr15", 2.0)),
            confidence=1.0,
            message="Interaction bonus applied for CR6 + CR15 (large real-estate footprint with low income).",
        ))

    triggered = [r.rule_name for r in rules if r.triggered]

    # Weighted aggregation for timeline (same approach as declaration scorer)
    raw_total_divisor = float(aggregation_cfg.get("raw_total_divisor", 12.0))
    corruption_to_opacity_weight = float(aggregation_cfg.get("corruption_to_opacity_weight", 0.5))

    raw_corruption = sum(
        r.score for r in rules
        if getattr(r, "category", None) == "corruption" or r.rule_name in {
            "yoy_income_change", "yoy_asset_growth", "foreign_cash_jump",
        }
    )
    raw_opacity = sum(r.score for r in rules if getattr(r, "category", None) == "opacity")

    raw_total = raw_corruption + corruption_to_opacity_weight * raw_opacity
    overall_100 = 100.0 * (1.0 - math.exp(-raw_total / raw_total_divisor)) if raw_total > 0 else 0.0
    overall_100 = round(overall_100, 2)

    return TimelineScoringResult(
        total_score=overall_100,
        rule_results=rules,
        triggered_rules=triggered,
    )

