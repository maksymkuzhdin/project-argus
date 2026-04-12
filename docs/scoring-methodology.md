# Scoring Methodology

Project Argus uses a layered, explainable anomaly scoring system. The platform never labels a person as corrupt. Scores indicate review priority only.

## Score Scale

- Declaration score (`total_score`) uses a native **0.0–100.0** scale.
- Timeline score (`timeline_score.total_score`) also uses **0.0–100.0**.
- Rule-level contributions are weighted points, not percentages.
- Layer 2 cohort scores are normalized within each cohort before they are blended into the final dashboard ranking.

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

### Confidential-Value Density

The pipeline also exposes `confidential_ratio`, the share of tracked value fields marked as confidential or redacted. This is not a standalone score, but it is used as a cohort feature for opacity checks and future cohort-aware analysis.

## Layer 2 Cohort Ensemble

Layer 2 is a cohort-scoped ensemble, not a single global model. The recommended composition is:

- Isolation Forest for sparse, distribution-free anomaly isolation.
- A dense autoencoder for reconstruction-error anomalies across feature interactions.
- ECOD for fast, interpretable tail-probability outlier detection.

Practical scoring guidance:

- Train one set of models per cohort rather than across all declarations.
- Normalize model outputs within each cohort before blending them.
- Use a weighted blend such as `0.35 * IF + 0.40 * AE + 0.25 * ECOD` as a starting point.
- Promote a confidence tier when two or more models agree on a high anomaly score.
- Prefer a stratified training corpus of roughly 100k–200k declarations total, balanced across cohorts, years, and regions, instead of fitting on all 7M records.

## Implemented Rule Layers

### Declaration-Level Rules

- Data quality checks: `TQ1`, `TQ2`, `TQ3`, `TQ4`, `TQ5`
- Corruption and opacity checks: `CR1`, `CR2`, `CR3`, `CR4`, `CR6`, `CR7`, `CR8`, `CR9`, `CR10`, `CR11`, `CR12`, `CR13`
- Cohort outlier checks: `CR16` (when cohort stats are available)
- Cohort opacity check: `BR3` (when cohort stats are available)
- Cohort ensemble support: IF, AE, and ECOD outputs when the Layer 2 pipeline is enabled

### Timeline Rules

- Existing YOY rules: `yoy_income_change`, `yoy_asset_growth`, `foreign_cash_jump`
- Added timeline checks: `CR5`, `CR14`, `CR15`, `BR1`, `BR2`, `BR4`
- Interaction bonuses wired in scoring and explanations:
  - declaration: `CR1 + CR2`, `CR10 + CR13`, `CR11 + CR12`
  - timeline: `CR14 + no one-off income`, `CR6 + CR15`

Timeline scoring uses a weighted composite and the same bounded 0–100 mapping.

### Deferred Rules

Remaining deferred scope is primarily:

- Interaction bonus combinations not yet wired in scoring (`CR11 + CR12`, `CR14 + no one-off income`, `CR6 + CR15`).

CR6 currently supports both:
- cohort-relative thresholds when valid cohort distributions are available, and
- absolute fallback thresholds when cohort context is missing or too small.

The currently deferred part is additional interaction-bonus wiring, not base CR6 thresholding.

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

### Layer 3 (Reserved)

Additional experimental models remain deferred. The current plan is to keep Layer 2 limited to the three-model cohort ensemble above and use any future additions only as additive context, never as a replacement for deterministic explainable rules.
