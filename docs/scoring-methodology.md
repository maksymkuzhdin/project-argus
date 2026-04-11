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
- Interaction bonuses wired in scoring and explanations:
  - declaration: `CR1 + CR2`, `CR10 + CR13`, `CR11 + CR12`
  - timeline: `CR14 + no one-off income`, `CR6 + CR15`

Timeline scoring uses a weighted composite and the same bounded 0–100 mapping.

### Deferred Rules

Remaining deferred scope is primarily ML additions and optional calibration refinements.

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

## CR6 Threshold Mode Selection

CR6 now uses a deterministic two-mode selector:

- **Relative mode (preferred):** uses cohort distributions when available and valid.
  - Region-relative first (same post_type/year cohort, matching primary region).
  - Falls back to post/year cohort-wide distribution if region sample is not valid.
  - Validity checks are explicit: minimum sample size and minimum variation.
  - Severity mapping: top 10% = MEDIUM, top 5% = HIGH.
- **Absolute fallback mode:** keeps existing fixed thresholds when relative inputs are missing/sparse/unreliable.
  - Dwellings: > 250 m2 MEDIUM, > 400 m2 HIGH.
  - Agricultural land: > 10 ha MEDIUM, > 50 ha HIGH.

CR6 explanations now include the mode used (`relative` or `absolute fallback`) and the source/reason used for threshold selection.

## Layer 3 (ML)

Unsupervised ML is still deferred. Planned additions remain:

- Isolation Forest
- Optional autoencoder
- ML as additive context, never a replacement for deterministic explainable rules
