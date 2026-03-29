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

from app.normalization.currency import to_uah
from app.scoring.cohorts import compute_percentile_rank, get_percentile_value


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


# ---------------------------------------------------------------------------
# Rule 1 — Unexplained wealth proxy
# ---------------------------------------------------------------------------

def unexplained_wealth(
    total_income: Decimal | None,
    total_assets: Decimal | None,
    *,
    threshold_ratio: float = 3.0,
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
    threshold: float = 0.8,
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
    threshold: float = 0.5,
    min_fields: int = 4,
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
    threshold_ratio: float = 1.5,
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
    min_assets: float = 100_000,
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
    threshold: float = 0.7,
    min_items: int = 3,
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
        if person_income >= Decimal("50000"):
            continue

        person_assets = assets_by_person.get(pid, Decimal(0))
        if person_assets <= 0:
            continue

        ratio = person_assets / declarant_assets
        if ratio > best_ratio:
            best_ratio = ratio
            best_pid = pid

    if best_pid is None or best_ratio < Decimal("2"):
        return RuleResult(rule, 0.0, False, "No major wealth concentration detected in low-income family members.")

    severity = "HIGH" if best_ratio >= Decimal("5") else "MEDIUM"
    relation = relation_by_id.get(best_pid, "family member")
    member_assets = assets_by_person.get(best_pid, Decimal(0))
    return _make_flag(
        rule_id=rule,
        category="corruption",
        severity=severity,
        base_weight=3,
        confidence=0.7,
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

    worst_year = None
    worst_count = 0
    for year, count in per_year.items():
        if count > worst_count:
            worst_count = count
            worst_year = year

    if worst_count >= 3:
        return _make_flag(
            rule_id=rule,
            category="opacity",
            severity="MEDIUM",
            base_weight=2,
            confidence=0.8,
            message=f"Detected {worst_count} declarations for {worst_year}, indicating repeated corrections.",
        )

    return RuleResult(rule, 0.0, False, "No significant correction pattern detected.")


def _cr15_real_estate_income_3y(timeline: Any) -> RuleResult:
    """CR15: high real-estate value relative to 3-year average income."""
    rule = "CR15"
    snaps = [
        s for s in getattr(timeline, "snapshots", [])
        if getattr(s, "declaration_type", 1) == 1
    ]
    if len(snaps) < 3:
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

    if best_ratio >= 15.0:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="HIGH",
            base_weight=4,
            confidence=0.8,
            message=(
                f"Real-estate value is {best_ratio:.1f}x 3-year average income "
                f"(window ending {best_end_year})."
            ),
        )

    return RuleResult(rule, 0.0, False, "No 3-year real-estate/income imbalance detected.")


def _cr14_asset_appearance_disappearance(change: Any) -> RuleResult:
    """CR14: major asset appears/disappears without matching one-off income."""
    rule = "CR14"
    one_off = getattr(change, "one_off_income_curr", None) or Decimal(0)

    appeared_n = getattr(change, "major_assets_appeared", 0) or 0
    appeared_val = getattr(change, "max_appeared_value", None)
    if appeared_n > 0 and appeared_val is not None and appeared_val >= Decimal("1000000"):
        if one_off < appeared_val * Decimal("0.5"):
            return _make_flag(
                rule_id=rule,
                category="corruption",
                severity="HIGH",
                base_weight=5,
                confidence=0.8,
                message=(
                    f"Major asset appearance detected ({appeared_n} new major assets, "
                    f"max {appeared_val:,.0f} UAH) without matching one-off income in {change.to_year}."
                ),
            )

    disappeared_n = getattr(change, "major_assets_disappeared", 0) or 0
    disappeared_val = getattr(change, "max_disappeared_value", None)
    if disappeared_n > 0 and disappeared_val is not None and disappeared_val >= Decimal("1000000"):
        if one_off < Decimal("300000"):
            sev = "HIGH" if disappeared_n >= 2 else "MEDIUM"
            return _make_flag(
                rule_id=rule,
                category="corruption",
                severity=sev,
                base_weight=5,
                confidence=0.7,
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
        if total_pct > 110.0 or (0.0 < total_pct < 10.0):
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
    for i in incomes:
        if i.get("amount_status") == "parse_error":
            parse_or_extreme += 1
        amt = i.get("amount")
        if amt is not None and Decimal(amt) > Decimal("10000000000"):
            parse_or_extreme += 1
    for m in monetary_assets:
        if m.get("amount_status") == "parse_error":
            parse_or_extreme += 1
        amt = m.get("amount")
        if amt is not None:
            uah = to_uah(amt, m.get("currency_code"))
            if uah is not None and uah > Decimal("10000000000"):
                parse_or_extreme += 1
    for r in real_estate:
        area = r.get("total_area")
        if area is not None and Decimal(area) > Decimal("10000000"):
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

    if inc_val is not None and cash_val is not None and inc_val >= Decimal("10000") and inc_val > 0:
        ratio = float(cash_val / inc_val)
        if ratio >= 10:
            flags.append(_make_flag(
                rule_id="CR1",
                category="corruption",
                severity="EXTREME",
                base_weight=5,
                confidence=1.0,
                message=f"Cash-to-income ratio is {ratio:.1f}x (>= 10x).",
            ))
        elif ratio >= 5:
            flags.append(_make_flag(
                rule_id="CR1",
                category="corruption",
                severity="HIGH",
                base_weight=5,
                confidence=1.0,
                message=f"Cash-to-income ratio is {ratio:.1f}x (>= 5x).",
            ))
        elif ratio >= 3:
            flags.append(_make_flag(
                rule_id="CR1",
                category="corruption",
                severity="MEDIUM",
                base_weight=5,
                confidence=1.0,
                message=f"Cash-to-income ratio is {ratio:.1f}x (>= 3x).",
            ))

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
        if fx_share >= 0.7 and fx_to_income >= 3:
            flags.append(_make_flag(
                rule_id="CR2",
                category="corruption",
                severity="HIGH",
                base_weight=4,
                confidence=1.0,
                message=f"FX cash dominates holdings ({fx_share:.0%}) and equals {fx_to_income:.1f}x annual income.",
            ))
        elif fx_share >= 0.5 and fx_to_income >= 1.5:
            flags.append(_make_flag(
                rule_id="CR2",
                category="corruption",
                severity="MEDIUM",
                base_weight=4,
                confidence=1.0,
                message=f"High FX-cash concentration ({fx_share:.0%}) with FX cash {fx_to_income:.1f}x income.",
            ))

    if inc_val is not None and inc_val > 0:
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
            if ratio >= 7:
                sev = "EXTREME"
            elif ratio >= 3:
                sev = "HIGH"
            elif ratio >= 2:
                sev = "MEDIUM"
            if sev and ratio > best_ratio:
                best_ratio = ratio
                best_cost = cost
                best_sev = sev

        if best_sev is not None and best_cost is not None:
            downgraded = False
            if one_off_income >= best_cost * Decimal("0.6"):
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
                base_weight=5,
                confidence=0.9,
                message=msg,
            ))

    if inc_val is not None and inc_val < Decimal("150000"):
        count_mid_hi = 0
        for r in real_estate:
            cost = r.get("cost_assessment")
            area = r.get("total_area")
            obj = str(r.get("object_type") or "").lower()
            if cost is not None and Decimal(cost) >= Decimal("500000"):
                count_mid_hi += 1
                continue
            if area is not None and Decimal(area) >= Decimal("10000") and cost is not None and Decimal(cost) >= Decimal("300000"):
                count_mid_hi += 1
                continue
            if "зем" in obj and area is not None and Decimal(area) >= Decimal("10000") and cost is not None and Decimal(cost) >= Decimal("300000"):
                count_mid_hi += 1
        for v in vehicles:
            cost = v.get("cost_date")
            if cost is not None and Decimal(cost) >= Decimal("300000"):
                count_mid_hi += 1
        if count_mid_hi >= 2:
            flags.append(_make_flag(
                rule_id="CR4",
                category="corruption",
                severity="HIGH",
                base_weight=4,
                confidence=0.9,
                message=f"Low-income year with {count_mid_hi} medium/high-value acquisitions.",
            ))

    dwelling_area = Decimal(0)
    agri_area = Decimal(0)
    for r in real_estate:
        area = r.get("total_area")
        if area is None:
            continue
        obj = str(r.get("object_type") or "").lower()
        if any(kw in obj for kw in ("кварт", "буд", "жит")):
            dwelling_area += Decimal(area)
        if "зем" in obj:
            agri_area += Decimal(area)
    # CR6 — Dwelling area: relative thresholds when cohort data is available,
    # otherwise fall back to absolute thresholds.
    _dwelling_dist = list(getattr(cohort_stats, "dwelling_areas", [])) if cohort_stats is not None else []
    if len(_dwelling_dist) >= 5 and dwelling_area > Decimal(0):
        _dw_pct = compute_percentile_rank(float(dwelling_area), _dwelling_dist)
        _dw_p95 = get_percentile_value(_dwelling_dist, 0.95)
        if _dw_pct >= 0.99:
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="HIGH",
                base_weight=3,
                confidence=0.8,
                message=(
                    f"Total dwelling area is {dwelling_area:,.0f} m2 "
                    f"({_dw_pct:.0%} percentile of cohort peers, P95 = {_dw_p95:,.0f} m2) "
                    f"[relative mode]."
                ),
            ))
        elif _dw_pct >= 0.95:
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="MEDIUM",
                base_weight=3,
                confidence=0.8,
                message=(
                    f"Total dwelling area is {dwelling_area:,.0f} m2 "
                    f"({_dw_pct:.0%} percentile of cohort peers, P95 = {_dw_p95:,.0f} m2) "
                    f"[relative mode]."
                ),
            ))
    else:
        if dwelling_area > Decimal("400"):
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="HIGH",
                base_weight=3,
                confidence=0.8,
                message=f"Total dwelling area is {dwelling_area:,.0f} m2 (> 400 m2) [absolute mode].",
            ))
        elif dwelling_area > Decimal("250"):
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="MEDIUM",
                base_weight=3,
                confidence=0.8,
                message=f"Total dwelling area is {dwelling_area:,.0f} m2 (> 250 m2) [absolute mode].",
            ))

    # CR6 — Agricultural area: relative thresholds when cohort data is available,
    # otherwise fall back to absolute thresholds.
    _agri_dist = list(getattr(cohort_stats, "agri_areas", [])) if cohort_stats is not None else []
    if len(_agri_dist) >= 5 and agri_area > Decimal(0):
        _ag_pct = compute_percentile_rank(float(agri_area), _agri_dist)
        _ag_p95 = get_percentile_value(_agri_dist, 0.95)
        if _ag_pct >= 0.99:
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="HIGH",
                base_weight=3,
                confidence=0.8,
                message=(
                    f"Agricultural land area is {agri_area:,.0f} m2 "
                    f"({_ag_pct:.0%} percentile of cohort peers, P95 = {_ag_p95:,.0f} m2) "
                    f"[relative mode]."
                ),
            ))
        elif _ag_pct >= 0.95:
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="MEDIUM",
                base_weight=3,
                confidence=0.8,
                message=(
                    f"Agricultural land area is {agri_area:,.0f} m2 "
                    f"({_ag_pct:.0%} percentile of cohort peers, P95 = {_ag_p95:,.0f} m2) "
                    f"[relative mode]."
                ),
            ))
    else:
        if agri_area > Decimal("500000"):
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="HIGH",
                base_weight=3,
                confidence=0.8,
                message=f"Agricultural land area is {agri_area:,.0f} m2 (> 50 ha) [absolute mode].",
            ))
        elif agri_area > Decimal("100000"):
            flags.append(_make_flag(
                rule_id="CR6",
                category="corruption",
                severity="MEDIUM",
                base_weight=3,
                confidence=0.8,
                message=f"Agricultural land area is {agri_area:,.0f} m2 (> 10 ha) [absolute mode].",
            ))

    luxury_count = 0
    for v in vehicles:
        brand_model = f"{v.get('brand') or ''} {v.get('model') or ''}".lower()
        if any(kw in brand_model for kw in (
            "bmw", "mercedes", "range rover", "porsche", "lexus", "audi", "tesla",
        )):
            luxury_count += 1

    if inc_val is not None:
        if luxury_count >= 2 and inc_val < Decimal("1000000"):
            flags.append(_make_flag(
                rule_id="CR7",
                category="corruption",
                severity="HIGH",
                base_weight=3,
                confidence=0.9,
                message=f"{luxury_count} luxury vehicles with household income below 1,000,000 UAH.",
            ))
        elif luxury_count >= 1 and inc_val < Decimal("600000"):
            flags.append(_make_flag(
                rule_id="CR7",
                category="corruption",
                severity="MEDIUM",
                base_weight=3,
                confidence=0.9,
                message="Luxury vehicle ownership with household income below 600,000 UAH.",
            ))

    child_markers = ("дит", "child", "син", "донь")
    adult_family = sum(1 for m in family_members if not _has_any_kw(m.get("relation"), child_markers))
    adults = max(1, 1 + adult_family)
    vehicles_per_adult = len(vehicles) / adults if adults else 0.0
    if vehicles_per_adult >= 3.5:
        flags.append(_make_flag(
            rule_id="CR7",
            category="corruption",
            severity="HIGH",
            base_weight=3,
            confidence=0.8,
            message=f"Vehicles per adult ratio is {vehicles_per_adult:.2f} (>= 3.5).",
        ))
    elif inc_val is not None and inc_val < Decimal("500000") and vehicles_per_adult >= 2.5:
        flags.append(_make_flag(
            rule_id="CR7",
            category="corruption",
            severity="MEDIUM",
            base_weight=3,
            confidence=0.8,
            message=f"Vehicles per adult ratio is {vehicles_per_adult:.2f} in a low-income household.",
        ))

    agri_machine = any(_has_any_kw(v.get("object_type"), ("тракт", "комбай", "harvest")) for v in vehicles)
    has_agri_assets = agri_area >= Decimal("100000") or agri_machine
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
            severity="HIGH" if agri_area >= Decimal("500000") else "MEDIUM",
            base_weight=3,
            confidence=0.8,
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
    rentable_objects = commercial_count + city_apartment_count
    if rentable_objects > 0 and rent_income < Decimal("30000"):
        flags.append(_make_flag(
            rule_id="CR9",
            category="corruption",
            severity="HIGH" if rentable_objects >= 3 else "MEDIUM",
            base_weight=3,
            confidence=0.7,
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
    if largest_dwelling_unknown or major_unknown_count >= 1:
        sev = "HIGH" if (major_unknown_count >= 2 or largest_dwelling_unknown and major_unknown_count >= 1) else "MEDIUM"
        flags.append(_make_flag(
            rule_id="CR10",
            category="opacity",
            severity=sev,
            base_weight=4,
            confidence=0.9,
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
            if (pct_v is not None and pct_v >= 99.0 and (is_main or (cost is not None and Decimal(cost) >= Decimal("500000")))):
                if income_by_person.get(pid, Decimal(0)) < Decimal("100000"):
                    major_proxy_detected = True
                    break
    if not major_proxy_detected:
        for m in monetary_assets:
            pid = str(m.get("person_ref") or "")
            rel = relation_by_id.get(pid, "").lower()
            if pid in relation_by_id and any(kw in rel for kw in ("друж", "чолов", "дит", "child", "син", "дон")):
                amt_uah = to_uah(m.get("amount"), m.get("currency_code"))
                if amt_uah is not None and amt_uah >= Decimal("500000") and income_by_person.get(pid, Decimal(0)) < Decimal("100000"):
                    major_proxy_detected = True
                    break
    if major_proxy_detected:
        flags.append(_make_flag(
            rule_id="CR11",
            category="corruption",
            severity="HIGH",
            base_weight=5,
            confidence=0.8,
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
    if family_no_info_count >= 3:
        flags.append(_make_flag(
            rule_id="CR13",
            category="opacity",
            severity="HIGH",
            base_weight=5,
            confidence=1.0,
            message=f"Family no-information markers appear {family_no_info_count} times on key asset fields.",
        ))

    # ------------------------------
    # CR16 — Cohort-relative outliers
    # ------------------------------
    if cohort_stats is not None:
        # Income outlier — top 1% of cohort
        if inc_val is not None and len(getattr(cohort_stats, 'incomes', [])) >= 5:
            pct = compute_percentile_rank(float(inc_val), cohort_stats.incomes)
            if pct >= 0.99:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="MEDIUM",
                    base_weight=3,
                    confidence=0.8,
                    message=f"Household income is at {pct:.0%} percentile of cohort peers.",
                ))

        # Wealth outlier — top 1% HIGH, top 5% MEDIUM
        if total_assets is not None and len(getattr(cohort_stats, 'assets', [])) >= 5:
            assets_float = float(total_assets)
            pct = compute_percentile_rank(assets_float, cohort_stats.assets)
            if pct >= 0.99:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="HIGH",
                    base_weight=3,
                    confidence=0.8,
                    message=f"Total assets at {pct:.0%} percentile of cohort peers (top 1%).",
                ))
            elif pct >= 0.95:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="MEDIUM",
                    base_weight=3,
                    confidence=0.8,
                    message=f"Total assets at {pct:.0%} percentile of cohort peers (top 5%).",
                ))

        # Cash outlier — top 1% with high FX share
        if cash_holdings is not None and len(getattr(cohort_stats, 'cash_ratios', [])) >= 5:
            cash_float = float(cash_holdings)
            cash_pct = compute_percentile_rank(
                cash_float / float(inc_val) if inc_val and inc_val > 0 else 0.0,
                cohort_stats.cash_ratios,
            )
            if cash_pct >= 0.99 and fx_share >= 0.5:
                flags.append(_make_flag(
                    rule_id="CR16",
                    category="corruption",
                    severity="HIGH",
                    base_weight=3,
                    confidence=0.8,
                    message=f"Cash-to-income ratio at {cash_pct:.0%} percentile with {fx_share:.0%} FX concentration.",
                ))

        # BR3: confidential marker density > 2x cohort median.
        conf_distribution = getattr(cohort_stats, "confidential_ratios", [])
        if len(conf_distribution) >= 5:
            decl_conf_ratio = _confidential_ratio_from_rows(incomes, monetary_assets, real_estate)
            cohort_median = get_percentile_value(conf_distribution, 0.5)
            if cohort_median > 0 and decl_conf_ratio > 2.0 * cohort_median:
                severity = "MEDIUM" if decl_conf_ratio > 3.0 * cohort_median else "LOW"
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

    # ------------------------------
    # Aggregation and weighted total
    # ------------------------------
    raw_corruption = sum(r.score for r in flags if r.category == "corruption")
    raw_opacity = sum(r.score for r in flags if r.category == "opacity")
    raw_quality = sum(r.score for r in flags if r.category == "data_quality")

    raw_quality_capped = min(2.0, raw_quality)

    if raw_corruption <= 0 and raw_opacity > 0:
        raw_opacity = min(raw_opacity, raw_corruption * 0.25)

    triggered_ids = {r.rule_name for r in flags}
    interaction_bonus = 0.0
    if "CR1" in triggered_ids and "CR2" in triggered_ids:
        interaction_bonus += 3.0
    if "CR10" in triggered_ids and "CR13" in triggered_ids:
        interaction_bonus += 3.0

    raw_total = raw_corruption + 0.5 * raw_opacity + 0.1 * raw_quality_capped + interaction_bonus
    overall_100 = 100.0 * (1.0 - math.exp(-raw_total / 12.0)) if raw_total > 0 else 0.0
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
    growth_threshold: float = 3.0,
    drop_threshold: float = 0.25,
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
    threshold_ratio: float = 3.0,
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
    threshold_uah: float = 200_000,
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

    ag = change.asset_growth
    ig = change.income_growth

    if ag is None:
        return RuleResult(rule, 0.0, False, "Insufficient asset data for growth comparison.")

    if ag >= 0.5 and (ig is None or ig <= 0.1):
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="HIGH",
            base_weight=5,
            confidence=0.9,
            message=(
                f"Assets grew {ag:.0%} year-over-year ({change.from_year}→{change.to_year}) "
                f"while income grew only {ig:.0%}." if ig is not None
                else f"Assets grew {ag:.0%} ({change.from_year}→{change.to_year}) with no income data."
            ),
        )

    if ag >= 0.2 and ig is not None and ig <= 0:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="MEDIUM",
            base_weight=5,
            confidence=0.8,
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

    delta = change.unknown_share_delta
    curr = change.unknown_share_curr

    if delta >= 0.3 and curr >= 0.5:
        return _make_flag(
            rule_id=rule,
            category="opacity",
            severity="MEDIUM",
            base_weight=2,
            confidence=0.9,
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

    if not change.role_changed:
        return RuleResult(rule, 0.0, False, "No role change detected.")

    ag = change.asset_growth
    if ag is None:
        return RuleResult(rule, 0.0, False, "Role changed but no asset data for comparison.")

    if ag >= 1.0:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="HIGH",
            base_weight=2,
            confidence=0.8,
            message=(
                f"Role changed ({change.from_year}→{change.to_year}) with "
                f"assets growing {ag:.0%} — major post-promotion wealth jump."
            ),
        )

    if ag >= 0.5:
        return _make_flag(
            rule_id=rule,
            category="corruption",
            severity="MEDIUM",
            base_weight=2,
            confidence=0.7,
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
    br1 = _br1_many_corrected(timeline)
    cr15 = _cr15_real_estate_income_3y(timeline)

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

    rules = [
        worst_income_rule, worst_asset_rule, worst_cash_rule,
        worst_cr5, worst_br2, worst_br4, worst_cr14,
        br1, cr15,
    ]
    triggered = [r.rule_name for r in rules if r.triggered]

    # Weighted aggregation for timeline (same approach as declaration scorer)
    raw_corruption = sum(
        r.score for r in rules
        if getattr(r, "category", None) == "corruption" or r.rule_name in {
            "yoy_income_change", "yoy_asset_growth", "foreign_cash_jump",
        }
    )
    raw_opacity = sum(r.score for r in rules if getattr(r, "category", None) == "opacity")

    raw_total = raw_corruption + 0.5 * raw_opacity
    overall_100 = 100.0 * (1.0 - math.exp(-raw_total / 12.0)) if raw_total > 0 else 0.0
    overall_100 = round(overall_100, 2)

    return TimelineScoringResult(
        total_score=overall_100,
        rule_results=rules,
        triggered_rules=triggered,
    )

