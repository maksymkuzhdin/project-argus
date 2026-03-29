# Scoring Methodology

Project Argus uses a layered, explainable anomaly scoring system. The platform never labels a person as corrupt. Scores indicate review priority only.

## Score Scale

- Declaration score (`total_score`) uses a native **0.0–100.0** scale.
- Timeline score (`timeline_score.total_score`) also uses **0.0–100.0**.
- Rule-level contributions are weighted points, not percentages.

## Aggregation Model

For declaration scoring, rules contribute weighted points:

`rule_points = base_weight * severity_multiplier * confidence`

Raw aggregates are separated by category:

- `corruption_risk_score`
- `opacity_evasion_score`
- `data_quality_score`

Then combined into a bounded overall score:

`raw_total = corruption + 0.5 * opacity + 0.1 * capped_data_quality + interaction_bonus`

`total_score = 100 * (1 - exp(-raw_total / 12))`

`data_quality_score` is capped to reduce technical-noise dominance.

## Implemented Rule Layers

### Declaration-Level Rules

- Data quality checks: `TQ1`, `TQ2`, `TQ3`, `TQ4`, `TQ5`
- Corruption and opacity checks: `CR1`, `CR2`, `CR3`, `CR4`, `CR6`, `CR7`, `CR8`, `CR9`, `CR10`, `CR11`, `CR12`, `CR13`
- Cohort outlier checks: `CR16` (when cohort stats are available)
- Cohort opacity check: `BR3` (when cohort stats are available)

### Timeline Rules

- Existing YOY rules: `yoy_income_change`, `yoy_asset_growth`, `foreign_cash_jump`
- Added timeline checks: `CR5`, `CR14`, `CR15`, `BR1`, `BR2`, `BR4`

Timeline scoring uses a weighted composite and the same bounded 0–100 mapping.

### Deferred Rules

Remaining deferred scope is primarily:

- CR6 cohort/region-relative thresholds (absolute thresholds are implemented; relative refinement is pending).

## Interaction Bonus Combinations

The following combinations add extra points when both component rules are triggered simultaneously, reflecting compounding risk signals:

| Combination | Bonus | Layer | Description |
|---|---|---|---|
| CR1 + CR2 | +3.0 | Declaration | High cash-to-income ratio with significant foreign-currency cash holdings |
| CR10 + CR13 | +3.0 | Declaration | Unknown-value major assets with family-member opacity markers |
| CR11 + CR12 | +2.0 | Declaration | Proxy ownership via low-income family member with disproportionate asset concentration |
| CR14 + zero one-off income | +2.0 | Timeline | Major asset appearance/disappearance with literally zero one-off income |
| CR6 + CR15 | +2.0 | Cross-layer | Excessive real-estate area combined with real-estate value far exceeding 3-year income |

Each triggered interaction bonus emits a dedicated `RuleResult` (with `rule_name` prefixed `IX_`) that appears in `rule_results`, `triggered_rules`, and `explanation_summary` for full transparency.

## Explanation Contract

Each triggered rule provides:

- `rule_name`
- `score`
- `triggered`
- `explanation`
- `category` (when available)
- `severity` (when available)
- `confidence` (when available)

This keeps outputs transparent for API consumers and UI rendering.

## Layer 3 (ML)

Unsupervised ML is still deferred. Planned additions remain:

- Isolation Forest
- Optional autoencoder
- ML as additive context, never a replacement for deterministic explainable rules
