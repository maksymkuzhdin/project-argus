"""
Project Argus — Deterministic anomaly scoring rules (Layer 1).

Each rule takes parsed declaration data and returns a ``RuleResult``
with a numeric score contribution, a trigger flag, and a neutral-language
explanation.

Rules implemented (single-declaration analysis):
    1. unexplained_wealth  — total assets vs total declared income
    2. cash_to_bank_ratio  — cash proportions that exceed a threshold
    3. unknown_value_freq  — fraction of fields marked unknown/confidential
    4. acquisition_income_mismatch — real-estate cost vs declared income

Rules deferred (require multi-year timeline):
    - year_over_year_growth
    - foreign_cash_jumps
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RuleResult:
    """Output of a single scoring rule."""

    rule_name: str
    score: float  # 0.0–1.0 contribution
    triggered: bool
    explanation: str


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
    """Aggregate scoring result across all rules."""

    total_score: float
    rule_results: list[RuleResult] = field(default_factory=list)
    triggered_rules: list[str] = field(default_factory=list)

    @property
    def explanation_summary(self) -> str:
        if not self.triggered_rules:
            return "No anomaly signals detected."
        lines = [f"• {r.explanation}" for r in self.rule_results if r.triggered]
        return "\n".join(lines)


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
) -> ScoringResult:
    """Run all Layer 1 scoring rules and return an aggregate result.

    Each input should be pre-computed from the parsed declaration data.
    All monetary values should be in the same currency.

    Returns
    -------
    A ``ScoringResult`` with the composite score capped at ``1.0``.
    """
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
    total = min(1.0, sum(r.score for r in rules))

    return ScoringResult(
        total_score=round(total, 3),
        rule_results=rules,
        triggered_rules=triggered,
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
# Timeline composite scorer
# ---------------------------------------------------------------------------

@dataclass
class TimelineScoringResult:
    """Scoring result for a multi-year person timeline."""

    total_score: float
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

    Uses the worst-case year-over-year change across all consecutive pairs.
    """
    from app.normalization.assemble_timeline import PersonTimeline as TL

    if not timeline.changes:
        return TimelineScoringResult(total_score=0.0)

    # Find the change pair with the worst income and asset signals
    worst_income_rule = RuleResult("yoy_income_change", 0.0, False, "No changes to assess.")
    worst_asset_rule = RuleResult("yoy_asset_growth", 0.0, False, "No changes to assess.")
    worst_cash_rule = RuleResult("foreign_cash_jump", 0.0, False, "No changes to assess.")

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

    rules = [worst_income_rule, worst_asset_rule, worst_cash_rule]
    triggered = [r.rule_name for r in rules if r.triggered]
    total = min(1.0, sum(r.score for r in rules))

    return TimelineScoringResult(
        total_score=round(total, 3),
        rule_results=rules,
        triggered_rules=triggered,
    )
