# Scoring Methodology

Project Argus uses a layered anomaly scoring system. Every score is transparent and explainable; no profile is ever labelled "corrupt." Scores range from **0.0** (no anomaly signals) to **1.0** (maximum anomaly concentration).

## Composite Score

The composite score is the **sum of all individual rule scores, capped at 1.0**.  Each rule contributes independently and is designed so that a single mild flag does not dominate the total.

## Layer 1 — Deterministic Heuristics

These rules run on a single declaration and require no cross-person or historical context.

### Rule 1: `unexplained_wealth`

| Parameter | Default |
|-----------|---------|
| `threshold_ratio` | 3.0 |

**Logic:** Compares total declared assets (monetary assets + real estate cost assessments) against total declared income.

- If `total_assets / total_income > threshold_ratio`, the rule triggers.
- Score contribution: `min(1.0, (ratio - threshold) / threshold)` — scales linearly from the threshold up to 2x the threshold.
- Special case: assets declared with zero or negative income yields a score of 1.0.

**Rationale:** A large gap between declared income and declared wealth may indicate income sources not captured in the declaration.

### Rule 2: `cash_to_bank_ratio`

| Parameter | Default |
|-----------|---------|
| `threshold` | 0.80 |

**Logic:** Calculates cash as a share of total liquid monetary assets (cash + bank deposits).  Excludes non-liquid monetary items (crypto, loans, etc.).

- If `cash / (cash + bank) > threshold`, the rule triggers.
- Score contribution: `min(1.0, (ratio - threshold) / (1.0 - threshold))`.

**Rationale:** An unusually high proportion of cash relative to banked assets may indicate preference for less-traceable wealth storage.

### Rule 3: `unknown_value_frequency`

| Parameter | Default |
|-----------|---------|
| `threshold` | 0.30 |

**Logic:** Counts how many value fields across income, monetary assets, and real estate carry a placeholder status (unknown, confidential, family_no_info) rather than an actual numeric value.

- If `unknown_fields / total_fields > threshold`, the rule triggers.
- Score contribution: `min(1.0, (freq - threshold) / (1.0 - threshold))`.

**Rationale:** Excessive use of "unknown" or "confidential" placeholders in value fields — beyond standard PII redaction — reduces the transparency of a declaration.

### Rule 4: `acquisition_income_mismatch`

| Parameter | Default |
|-----------|---------|
| `threshold_ratio` | 1.5 |

**Logic:** Compares the single largest real estate cost assessment against total declared income.

- If `largest_acquisition / total_income > threshold_ratio`, the rule triggers.
- Score contribution: `min(1.0, (ratio - threshold) / threshold)`.
- Special case: acquisition with zero/negative income yields 1.0.

**Rationale:** A single property purchase that significantly exceeds annual declared income may warrant review.

## Layer 2 — Statistical Cohort Analysis (Implemented)

Layer 2 adds role/year cohort context on top of deterministic rules.

### Rule 5: `cohort_income_outlier`

Compares declaration income to cohort percentile boundaries (same post type and year).

### Rule 6: `cohort_wealth_outlier`

Compares declaration monetary/wealth totals to cohort percentile boundaries.

These rules are additive context signals and do not replace deterministic flags.

## Multi-year Timeline Rules (Implemented)

These rules operate on person timelines across declarations.

### Rule 7: `yoy_income_change`

Flags abrupt year-over-year income spikes/drops.

### Rule 8: `yoy_asset_growth`

Flags unusually large year-over-year monetary growth relative to prior baseline.

### Rule 9: `foreign_cash_jump`

Flags sudden growth in cash holdings suggestive of unusual liquidity shifts.

## Layer 3 — Unsupervised ML

*Not yet implemented.* Planned features:

- Isolation Forest for multivariate outlier detection across all computed features.
- Optional autoencoder for reconstruction-error-based anomaly scoring.
- ML signals will supplement, not replace, deterministic and statistical layers.
