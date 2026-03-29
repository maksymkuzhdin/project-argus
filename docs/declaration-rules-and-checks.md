# Ukraine-Focused Automated Declaration Checks (Draft Rulebook)

**Version:** 0.1 (for implementation prototype)  
**Scope:** Ukraine’s public e-declarations (post‑2021 form), using only fields that are publicly visible in JSON (no external registers).  
**Goal:** Prioritize corruption‑risk signals, keep technical/data‑quality issues separate.

## Implementation status in current codebase (March 2026)

This section reflects what is currently implemented in the backend scoring pipeline.

Scoring engine notes:
- Implemented weighted rule contributions using `rule_points = base_weight * severity_multiplier * confidence_multiplier`.
- Implemented separate aggregates in score payload: `corruption_risk_score`, `opacity_evasion_score`, `data_quality_score`, `raw_total_score`.
- `total_score` is native 0–100 scale using bounded nonlinear formula `100 * (1 - exp(-raw_total / 12))`.
- Cohort scoring (CR16) integrated directly into declaration-level scoring when cohort stats are available.
- Timeline scoring (CR5, BR2, BR4) integrated into timeline scorer with 0–100 output.

Rule status summary:

| Rule | Status | Notes |
|---|---|---|
| TQ1 | Implemented | Invalid/malformed/out-of-range owning dates in real estate and vehicles are flagged. |
| TQ2 | Implemented | Orphan/unresolved person ownership references are flagged via unresolved IDs/owners. |
| TQ3 | Implemented | Real-estate ownership-share totals are checked for >110% or implausibly low totals. |
| TQ4 | Implemented | Parse errors and extreme numeric outliers are flagged on income/monetary/real-estate fields. |
| TQ5 | Deferred | Requires reliable residence-country and stronger household-adult inference from profile/location data; not robust in current normalized schema. |
| CR1 | Implemented | Cash-to-income ratio with MEDIUM/HIGH/EXTREME thresholds (3x/5x/10x). |
| CR2 | Implemented | FX-cash dominance using FX share and FX-to-income thresholds. |
| CR3 | Implemented | Same-year acquisition-vs-income rule over real-estate + vehicle costs with one-off income mitigation. |
| CR4 | Implemented | Low-income year with multiple medium/high-value acquisitions. |
| CR5 | Implemented | Asset growth vs income growth comparison in timeline scorer; triggers on asset_growth ≥ 0.5 with income_growth ≤ 0.1. |
| CR6 | Partially implemented | Absolute area thresholds implemented (dwelling/agri area); cohort/region-relative logic is deferred. |
| CR7 | Implemented | Luxury vehicles + income and vehicles-per-adult thresholds are implemented. |
| CR8 | Implemented | Agri-asset without agri/rent income rule implemented using keyword classification. |
| CR9 | Implemented | Commercial/rentable assets with low rent/business income implemented. |
| CR10 | Implemented | Unknown valuations on major assets implemented with severity escalation. |
| CR11 | Partially implemented | Proxy ownership by spouse/child with low income implemented for detectable ownership links; limited by partial owner metadata in some asset types. |
| CR12 | Deferred | Robust per-person asset valuation is not reliable with current normalized ownership/value granularity (shared ownership and missing per-owner values). |
| CR13 | Implemented | Repeated family-no-info markers on key fields are flagged. |
| CR14 | Deferred | Requires cross-year asset identity tracking (appearance/disappearance with transaction matching), not currently modeled. |
| CR15 | Deferred | Requires reliable 3-year real-estate value time series in timeline model; not yet assembled in current timeline snapshots. |
| CR16 | Implemented | Cohort-relative outlier checks (income/wealth/cash) integrated directly into declaration-level scorer via optional cohort_stats parameter. |
| BR1 | Deferred | Corrected-declaration count is not present in current ingestion model. |
| BR2 | Implemented | Growth in share of unknown values over time computed in timeline layer; triggers on delta ≥ 0.3 with current share ≥ 0.5. |
| BR3 | Deferred | Cohort median of confidential markers not available in current online scoring path. |
| BR4 | Implemented | Role-change detection with post-promotion asset growth analysis in timeline scorer; triggers on role change + asset_growth ≥ 0.5. |

Interaction-bonus status:
- Implemented: `CR1 + CR2`, `CR10 + CR13`.
- Deferred: `CR11 + CR12`, `CR14 + no one-off income`, `CR6 + CR15` (dependent on deferred rules).

Current reason for deferrals:
- Deferred rules depend on data not reliably present in the current normalized schema, or on timeline/cohort integrations that are not yet wired into the declaration-level scorer.

---

## 0. General conventions

- **Household** = declarant + all persons listed in step_2 (spouse, children, other family) for that declaration year.  
- **Year** = reporting year of the declaration (e.g., 2024).  
- **Income_Y** = total income of the household for year Y (UAH), sum of all `sizeIncome` in step_11 for all household members.  
- **Cash_Y** = total cash and liquid financial assets of the household for year Y (UAH equivalent), from step_12.  
- **Assets_Y** = rough total value of major assets (real estate, vehicles, cash) for year Y, wherever cost/value is available. For rules that depend on Assets_Y, this is allowed to be approximate.  
- When values are in foreign currency, convert to UAH using a static approximate annual average FX rate for the year (hardcode initial rates; refine later).  
- "Flag" means create a structured record with: `rule_id`, `severity`, `message`, and key numeric details.

Severity levels:
- **LOW** – unlikely to be direct corruption signal alone; useful context or data‑quality issue.  
- **MEDIUM** – may indicate concealment / unjustified assets; worth inclusion in risk score.  
- **HIGH** – strong direct corruption‑risk signal; should heavily influence risk score.

All thresholds below are **starting points tuned to Ukraine’s current income, price, and savings context**:
- Typical public‑sector salaries for doctors/teachers/local officials: ≈ 15k–35k UAH/month (180k–420k UAH/year).  
- New apartments in Kyiv: ≈ 30k–60k+ UAH/m² (often 50k–60k UAH/m² in central areas).  
- New apartments in regions: ≈ 20k–35k UAH/m² on average.

These imply that a modest official household realistically saves at most **10–30%** of income per year in normal conditions; larger wealth or cash piles are possible but uncommon.

---

## 1. Technical / data‑quality rules (separate from corruption risk)

### TQ1 – Invalid or impossible dates

- **Condition:** Any `owningDate`, `costDate`, or similar date field that:  
  - is later than 31.12 of the reporting year; **OR**  
  - is earlier than 1900; **OR**  
  - is clearly malformed (cannot parse).  
- **Severity:** LOW.  
- **Purpose:** Data sanity; used to down‑weight trust in numeric ratios that depend on those records.

### TQ2 – Orphan person/rights references

- **Condition:** Any `rightBelongs` / `person` id in asset sections that is not:  
  - the declarant id (usually "1"), and  
  - not present among step_2 persons, and  
  - not part of a clearly defined external person object.  
- **Severity:** LOW.  
- **Purpose:** Indicates messy data; may affect household‑level aggregation.

### TQ3 – Ownership shares sum > 100% or < 10%

- For each real estate object: sum all ownership shares where a percentage is specified.
- **Condition:**  
  - sum_percent > 110; **OR**  
  - 0 < sum_percent < 10 (and no usufruct/other explanation).  
- **Severity:** LOW.  
- **Purpose:** Technical inconsistency; treat as potential input error.

### TQ4 – Non‑parsable or extreme numeric values

- **Condition:** Any of `sizeIncome`, `sizeAssets`, `totalArea`, `costDate` not parsable as numbers, or:  
  - `totalArea` > 10,000,000 m²; **OR**  
  - `sizeIncome` or `sizeAssets` > 10,000,000,000 UAH (10 billion).  
- **Severity:** LOW.  
- **Purpose:** Clearly erroneous entries that would distort risk metrics.

### TQ5 – Sections likely mis‑marked as "not applicable"

- **Condition:**  
  - Household includes at least one adult and at least one income source in step_11 **AND**  
  - step_3 (real estate) is marked `isNotApplicable = 1` **AND**  
  - residence country is Ukraine.  
- **Severity:** LOW.  
- **Purpose:** Very unlikely a Ukrainian household has *no* dwelling; likely mis‑use of form.

> Implementation note: all TQ* rules should **not** add much to corruption‑risk score; instead, store as a separate `data_quality_score` and as multipliers on trust in other signals.

---

## 2. Strong corruption‑risk rules (core of main score)

### CR1 – Cash and liquid assets vs. annual income

- **Definitions:**  
  - `Cash_Y` = sum of all cash and liquid financial assets (step_12) for household in year Y, converted to UAH.  
  - `Income_Y` as defined above.
- **Skip:** if `Income_Y < 10,000 UAH` (data unreliable) or if no cash data.
- **Ratios:**  
  - `R_cash_income = Cash_Y / Income_Y`.
- **Conditions & severities:**  
  - `R_cash_income` in [3, 5): flag **MEDIUM**.  
  - `R_cash_income` in [5, 10): flag **HIGH**.  
  - `R_cash_income ≥ 10`: flag **HIGH** + mark as **extreme**.  
- **Justification:** For typical public servants with 180k–420k UAH/year income, having > 5 years of full income sitting as cash (especially FX) is highly unusual and matches patterns highlighted in Ukraine and other countries’ systems (large cash hoards vs low salary).

### CR2 – Foreign‑currency cash dominance

- **Definitions:**  
  - `FX_cash_Y` = cash assets where currency is not UAH.  
  - `FX_share = FX_cash_Y / Cash_Y` (if Cash_Y > 0).  
  - `FX_to_income = FX_cash_Y / Income_Y`.
- **Conditions & severities:**  
  - `FX_share ≥ 0.7` **AND** `FX_to_income ≥ 3` → **HIGH**.  
  - `FX_share ≥ 0.5` **AND** `FX_to_income ≥ 1.5` → **MEDIUM**.  
- **Justification:** High FX cash holdings are a common form of storing illicit proceeds in Ukraine; post‑2016 declarations showed many officials with large USD/EUR cash piles vs low official income.

### CR3 – Single asset acquisition cost vs. income (same year)

- For each asset with an acquisition date in year Y and cost field (real estate or vehicle):  
  - `R_cost_income = asset_cost / Income_Y`.
- **Conditions (per asset) & severities:**  
  - `R_cost_income` in [2, 3): **MEDIUM** (context‑dependent).  
  - `R_cost_income` in [3, 7): **HIGH**.  
  - `R_cost_income ≥ 7`: **HIGH** + mark as **extreme**.  
- **Exceptions (mitigation):** downgrade by one level if there is a one‑off large income in step_11 (inheritance, sale of property) of similar size in same year.
- **Justification:** With average doctor/public wages ~200–400k UAH/year and property prices often 30k–60k UAH/m² in cities, a 2–3M UAH apartment can easily be > 7× annual income; legitimate but rare without inheritance or sale of another asset, and is a standard red flag for unjustified enrichment.

### CR4 – Multiple medium/high‑value acquisitions in a low‑income year

- **Definitions:**  
  - Consider a year “low‑income” for the household if `Income_Y` < 150,000 UAH (≈ 12,500 UAH/month) **OR** if household is in bottom 25% of incomes among same‑position cohort (if you compute cohorts later).  
  - “Medium/high‑value asset” =  
    - real estate with `cost_date_assessment ≥ 500,000 UAH`, or  
    - vehicle with `costDate ≥ 300,000 UAH`, or  
    - land with area ≥ 1 ha and value ≥ 300,000 UAH (if value known).
- **Condition:** In a low‑income year, household acquires **2 or more** medium/high‑value assets.  
- **Severity:** HIGH.  
- **Justification:** Very unlikely to be financed from current income; suggests undeclared income or previous non‑declared wealth.

### CR5 – Asset growth vs. income growth (multi‑year)

Requires ≥ 2 years for same person.

- **Definitions:**  
  - For each year Y, compute `Assets_Y` ≈ sum of known values of real estate, vehicles, and cash (ignore zeros / unknowns).  
  - For each consecutive pair Y-1 → Y:  
    - `dAssets = Assets_Y − Assets_{Y-1}`.  
    - `dIncome = Income_Y − Income_{Y-1}`.  
- **Conditions & severities:**  
  - If `Assets_{Y-1} > 0`, compute `asset_growth = dAssets / max(Assets_{Y-1}, 1)` and `income_growth = dIncome / max(Income_{Y-1}, 1)`.  
  - If `asset_growth ≥ 0.5` **AND** `income_growth ≤ 0.1` → **HIGH**.  
  - If `asset_growth ≥ 0.2` **AND** `income_growth ≤ 0` → **MEDIUM**.  
- **Justification:** World Bank and regional analyses explicitly flag “faster growth of assets than income” as a key indicator of unjustified assets, especially over short periods.

### CR6 – Household real estate footprint vs. role and region

- **Definitions (per year):**  
  - Sum `totalArea` of all land plots (m²) and of all dwellings (houses, apartments) owned by household.  
  - Classify by region (oblast) and by job category of declarant (e.g., judge, prosecutor, doctor, teacher, local executive, etc.).
- **Relative model (preferred):**  
  - When you have enough data, compute distributions **within each cohort** (job category × region).  
  - Flag top 10% in total real estate area as **MEDIUM**, top 5% as **HIGH**.
- **Absolute interim thresholds (before you have distributions):**  
  - For city‑based officials: dwellings (houses/apartments) with total area > 250 m² → **MEDIUM**; > 400 m² → **HIGH**.  
  - For any officials: agricultural land area > 10 ha (100,000 m²) → **MEDIUM**; > 50 ha → **HIGH**.  
- **Justification:** Given typical flat sizes (40–80 m²) and urban land scarcity, very large residential or agricultural holdings stand out strongly compared to normal public‑sector households.

### CR7 – Vehicles vs. income (luxury / quantity)

- **Luxury vehicle flag:**  
  - Maintain a (manually curated) list of luxury brands/models (e.g., BMW X5/X6/7‑series, Mercedes E/S/GLS, Range Rover, Porsche, Lexus LX/RX, etc.).  
  - If household owns **any** luxury vehicle and `Income_Y < 600,000 UAH` → **MEDIUM**.  
  - If **≥ 2** luxury vehicles and `Income_Y < 1,000,000 UAH` → **HIGH**.  
- **Vehicles per adult:**  
  - Estimate #adults = #household members with role not "child" (approx).  
  - If `vehicles / adults ≥ 2.5` with `Income_Y < 500,000 UAH` → **MEDIUM**.  
  - If `vehicles / adults ≥ 3.5` → **HIGH**.  
- **Justification:** Even in car‑heavy cultures, multiple high‑end cars for modestly paid officials are a known lifestyle‑vs‑income red flag.

### CR8 – Agricultural assets without corresponding agri income

- **Condition:**  
  - Household holds:  
    - ≥ 10 ha of agricultural land **OR**  
    - at least one significant agricultural machine (tractor, combine harvester, etc.),  
  - **AND** there is **no** income in step_11 classified as farm/agri business or rent.  
- **Severity:** MEDIUM (upgrade to HIGH if land ≥ 50 ha and still no agri/rent income).  
- **Justification:** Suggests undeclared business activity or rent income.

### CR9 – Commercial real estate without rent/business income

- **Condition:**  
  - Household owns:  
    - at least one non‑residential premises (commercial) **OR**  
    - ≥ 2 apartments in a major city (Kyiv, Lviv, Odesa, etc.),  
  - **AND** there is little or no rent/business income (e.g., rent income < 30,000 UAH/year).  
- **Severity:** MEDIUM; set to HIGH if there are ≥ 3 such rentable objects and still no rent.  
- **Justification:** Highly likely there is undeclared rental or business income.

### CR10 – "Unknown value" on high‑value assets

- **Condition:**  
  - Any main dwelling (house/apartment where household likely resides, or largest by area) with value field `[Не відомо]` or equivalent; **OR**  
  - ≥ 2 assets of types {house, apartment, large land plot, vehicle} in one year with `cost` or `valuation` unknown.  
- **Severities:**  
  - 1 such high‑value asset → **MEDIUM**.  
  - ≥ 2 such assets → **HIGH**.  
- **Justification:** Repeatedly hiding values for obvious major assets is consistent with deliberate opacity, not random error.

### CR11 – Spouse / child 100% owner of major assets (proxy pattern)

- **Condition:**  
  - A spouse or minor child holds 100% ownership in:  
    - a main dwelling or  
    - any luxury vehicle or  
    - large cash/deposit holdings (e.g. > 500,000 UAH),  
  - **AND** that family member has little/no independent income (e.g., `income_person < 100,000 UAH`).
- **Severity:** HIGH.  
- **Justification:** Classic proxy ownership scheme, widely documented in Ukraine and internationally.

### CR12 – Wealth concentration in non‑earning family members

- **Condition:**  
  - At least one non‑earning or low‑earning spouse/child (income < 50,000 UAH)  
  - whose asset value (known part) is > 2× the declarant’s individual asset value.  
- **Severity:** MEDIUM (upgrade to HIGH if factor ≥ 5×).  
- **Justification:** Indicates wealth shifted to relatives with no real economic basis.

### CR13 – Repeated "family member did not provide information" on key fields

- **Condition:**  
  - For any family member, there are:  
    - ≥ 3 instances in one year of key fields (owningDate, value, area) explicitly labelled "family member did not provide information" **OR** equivalent,  
    - especially on real estate or vehicles.  
- **Severity:** HIGH.  
- **Justification:** In Ukrainian context, activists and practitioners treat systematic non‑provision of family info as a strong deliberate evasion signal, not a random omission.

### CR14 – Time‑series pattern: sudden appearance/disappearance of big assets

Requires ≥ 2 years for same person.

- **Sudden appearance:**  
  - A new major asset appears (main dwelling, luxury car, or any asset valued ≥ 1,000,000 UAH) in year Y, with no matching one‑off income (inheritance, sale > 500,000 UAH) in step_11.  
  - **Severity:** HIGH.
- **Sudden disappearance:**  
  - A previously declared major asset disappears in year Y,  
  - **AND** there is no recorded sale/gift income or similar one‑off transaction ≥ 300,000 UAH.  
  - **Severity:** MEDIUM (HIGH if multiple major assets disappear this way).

### CR15 – High total real estate + low declared income over time

- **Definitions:**  
  - `RealEstate_value_Y` = sum of known values of dwellings + land.  
  - `Income_avg_3y` = average Income over 3 consecutive years.  
- **Condition:**  
  - For any 3‑year window, `RealEstate_value_end / Income_avg_3y ≥ 15`.  
- **Severity:** HIGH.  
- **Justification:** Having real estate worth 15+ years of average household income with no evidence of prior legitimate wealth is a standard high‑risk configuration for illicit enrichment, especially in a country where average wages are low.

### CR16 – Cohort‑relative outliers (once you have enough data)

For each job category × region × year cohort:

- **Income outliers:**  
  - Declarant’s household income in top 1% of cohort while holding a public role with regulated pay → **MEDIUM** (possible side incomes, conflict of interest).  
- **Wealth outliers:**  
  - Real estate area or Assets_Y in top 1% → **HIGH**; top 5% → **MEDIUM**.  
- **Cash outliers:**  
  - Cash_Y in top 1% → **HIGH** if also high FX share.

These percentile‑based rules should eventually replace some absolute thresholds.

---

## 3. Medium‑strength / behavioral rules

These are weaker individually, but useful in aggregate.

### BR1 – Many corrected declarations

- **Condition:**  
  - For a given reporting year, the person submits ≥ 3 corrected declarations.  
- **Severity:** MEDIUM.  
- **Justification:** Many corrections, especially after media coverage, are correlated with attempts to "fix" problematic declarations after the fact.

### BR2 – Growth in share of "unknown" values over time

- **Definitions:**  
  - For each year, compute `Unknown_share_Y = (# high‑value assets with unknown value) / (# high‑value assets total)`.  
- **Condition:**  
  - Unknown_share_Y − Unknown_share_{Y-1} ≥ 0.3 and Unknown_share_Y ≥ 0.5.  
- **Severity:** MEDIUM.  
- **Justification:** Trend towards hiding valuations is a behavioral evasion pattern.

### BR3 – Dense use of confidential markers beyond system defaults

- **Condition:**  
  - Within a year, number of `confidential` or equivalent redacted fields in non‑sensitive areas (e.g., descriptions, optional fields) is > 2× cohort median.  
- **Severity:** LOW–MEDIUM.  
- **Justification:** Might reflect real security concerns in some cases, but in aggregate can indicate intentional opacity.

### BR4 – Vehicles / real estate inconsistent with role change

- **Condition:**  
  - Major role promotion (e.g., into high‑risk post) followed within ≤ 2 years by significant jumps in assets (Assets growth ≥ 50%) and/or luxury purchases.  
- **Severity:** MEDIUM–HIGH depending on magnitude.  
- **Justification:** Classic narrative: "after getting position X, wealth suddenly explodes".

---

## 4. Implementing scores and weights (high‑level)

You can implement two parallel scores:

1. **corruption_risk_score** – sum of weighted CR* and BR* flags.  
2. **data_quality_score** – sum of weighted TQ* flags.

Initial weighting suggestion (relative, not absolute points):

- HIGH severity (CR1–CR3, CR5, CR7 luxury, CR10 multi‑unknown, CR11, CR13, CR14 appearance, CR15, cohort top 1%) → weight 3–4.  
- MEDIUM severity (others in CR*, BR2–BR4) → weight 1–2.  
- LOW severity (TQ*, BR3) → weight 0–1 into a separate `data_quality_score` only.

Later, you can calibrate these weights empirically by:

- Looking at known scandal cases vs. random officials.  
- Adjusting thresholds so that known corrupt profiles sit in top X% of `corruption_risk_score` while not flooding the top with obvious typos.

---

## 5. Notes on future Tier‑2 checks (registries)

The above rules assume only declaration JSON. Once you have access to property, vehicle, company or court registers, you can add Tier‑2 rules like:

- Undeclared real estate or vehicles found in registries.  
- Mismatches between registered and declared areas/ownership shares.  
- Company ownership or procurement conflicts (spouse company winning tenders from declarant’s body).  
- Foreign real estate or accounts from international data exchanges.

These will likely be among the strongest signals, but they are outside the scope of this initial declaration‑only rulebook.

---

## 6. Overall risk score calculation logic

The scoring system should rank declarations for further investigation rather than try to determine guilt. This follows international risk-based verification practice: multiple indicators are combined, weighted, and used to prioritize the highest-risk cases for human review.

### 6.1 Three parallel scores

Maintain three separate scores:

1. **corruption_risk_score**  
   Built from direct unjustified-wealth and concealment indicators such as cash-to-income mismatch, unexplained acquisitions, proxy ownership, abnormal wealth growth, and large unknown-value assets.

2. **opacity_evasion_score**  
   Built from indicators that are not proof of corruption by themselves but often reflect concealment behavior: repeated "family member did not provide information," repeated corrections, rising share of unknown values, sudden disappearance of major assets, etc.

3. **data_quality_score**  
   Built from purely technical issues such as malformed dates, broken numeric fields, ownership-share arithmetic, and orphan person IDs.

**Use these separately.** The public ranking should be driven mainly by `corruption_risk_score`, moderately adjusted by `opacity_evasion_score`, and minimally affected by `data_quality_score`.

### 6.2 Rule contribution formula

For each triggered rule, compute a contribution:

```text
rule_points = base_weight * severity_multiplier * confidence_multiplier
```

Where:

- `base_weight` = how important the rule is in principle.
- `severity_multiplier` = how strong the observed case is.
- `confidence_multiplier` = how reliable the underlying data is.

Suggested starting values:

#### Base weight

- `5` = strongest direct corruption signals, e.g. CR1, CR3, CR5, CR11, CR13, CR14, CR15.
- `4` = strong but slightly less direct signals, e.g. CR2, CR4, CR10.
- `3` = meaningful but more contextual signals, e.g. CR6, CR7, CR8, CR9, CR12, CR16.
- `2` = behavioral/secondary indicators, e.g. BR1, BR2, BR4.
- `1` = weak opacity signals, e.g. BR3.
- `0` or separate-only = pure technical/data-quality indicators, e.g. TQ1–TQ5.

#### Severity multiplier

- `1.0` = medium case.
- `1.5` = high case.
- `2.0` = extreme case.

Example:
- `Cash / Income = 4.2x` may trigger CR1 at MEDIUM → multiplier `1.0`.
- `Cash / Income = 8.5x` may trigger CR1 at HIGH → multiplier `1.5`.
- `Cash / Income = 14x` may trigger CR1 at EXTREME → multiplier `2.0`.

#### Confidence multiplier

- `1.0` = high confidence, data is complete and rule is directly observed.
- `0.7` = medium confidence, some fields are missing/unknown but signal still meaningful.
- `0.4` = low confidence, rule depends on inferred or partial information.

Example:
- Spouse owns a luxury car and spouse income is explicitly shown as near zero → `1.0`.
- Spouse owns major asset but income fields are incomplete or partly redacted → `0.7`.

### 6.3 Interaction bonuses

Add bonus points when multiple red flags reinforce each other. This is important because combinations are often more meaningful than isolated issues.

Suggested interaction bonuses:

- **Cash + FX concentration**  
  If CR1 and CR2 both trigger, add `+3` bonus points.

- **Proxy ownership + low family income**  
  If CR11 and CR12 both trigger, add `+3` bonus points.

- **Asset appearance + no matching one-off income**  
  If CR14 triggers and there is no step_11 one-off inflow of at least 50% of the asset value, add `+2` bonus points.

- **Unknown values + family non-disclosure**  
  If CR10 and CR13 both trigger, add `+3` bonus points.

- **Large real estate portfolio + low income**  
  If CR6 and CR15 both trigger, add `+2` bonus points.

These bonuses should be capped so they do not overwhelm the base rule system.

### 6.4 Caps and anti-noise protections

Add the following caps:

- **Technical cap**: total contribution from TQ* rules should be capped at `2` points into any public-facing overall score.
- **Behavioral cap**: BR* rules should not exceed `25%` of the total raw score unless at least one CR* rule is also triggered.
- **Single-family cap**: multiple near-duplicate technical issues on the same asset should be deduplicated or capped.

This prevents a declaration with many harmless formatting problems from outranking a declaration with a few strong corruption signals.

### 6.5 Raw score construction

Suggested raw-score logic:

```text
raw_corruption = sum(CR rule_points)
raw_opacity = sum(BR rule_points + selected opacity-related CR rule_points)
raw_quality = sum(TQ rule_points)

raw_total = raw_corruption + 0.5 * raw_opacity + 0.1 * raw_quality + interaction_bonuses
```

This reflects the desired balance:

- direct corruption signals dominate,
- opacity/evasion matters but less,
- technical noise matters only a little.

Equivalent interpretation:

- roughly **70% weight** on direct corruption-risk rules,
- roughly **20% weight** on opacity/evasion rules,
- roughly **10% weight** on technical/data-quality issues.

### 6.6 Convert raw score to 0–100

Do **not** map raw score to 0–100 with a simple linear scaling based on arbitrary min/max values. Instead use one of these two approaches:

#### Preferred: percentile-based cohort ranking

For each year, and ideally for each cohort (job category × region), compute the empirical distribution of `raw_total`.

Then assign:

- Top 1% → `90–100`
- Top 5% → `75–89`
- Top 10% → `60–74`
- Top 25% → `40–59`
- Remaining → below `40`

This is the most robust public-facing score because it reflects how unusual a declaration is relative to peers.

#### Interim: bounded nonlinear score

If you do not yet have enough data for percentiles, use:

```text
overall_score = 100 * (1 - exp(-raw_total / 12))
```

This has good behavior:

- small raw scores stay low,
- strong cases rise quickly,
- extremely large raw scores do not explode beyond 100.

In the current implementation, scores are rounded to 2 decimals.

### 6.7 Recommended public labels

Display both numeric score and label:

- `0–19` → Low risk
- `20–39` → Mild anomalies
- `40–59` → Moderate risk
- `60–74` → High risk
- `75–89` → Very high risk
- `90–100` → Extreme priority

Also display separate badges:

- `Opacity: low / medium / high`
- `Data quality: low / medium / high`

This avoids misleading users into thinking that a high score caused by bad data equals strong corruption evidence.

### 6.8 Minimum trigger logic

To avoid false positives, apply minimum trigger rules:

- Do not classify a declaration above `Moderate risk` unless at least **one** CR* rule is triggered.
- Do not classify a declaration above `High risk` unless either:  
  - at least **two** CR* rules are triggered, or  
  - one CR* rule is HIGH/EXTREME and at least one BR* or opacity rule also triggers.
- If only TQ* rules trigger, cap overall label at `Mild anomalies`.

### 6.9 Explanations for users

For every scored declaration, generate:

- overall score,
- top 3–5 triggered rules by point contribution,
- short plain-language explanation,
- separate opacity and data-quality summaries.

Example:

```text
Overall risk: 82 (Very high)
Main reasons:
1. Household cash equals 8.4x annual income.
2. Spouse owns 100% of major real estate with minimal independent income.
3. Two major assets have unknown valuation and family information is repeatedly withheld.
Opacity: High
Data quality: Low
```

This is critical because investigators and journalists need interpretable reasons, not just a black-box number.
