# Ukraine-Specific Cohort Taxonomy

**Status**: MVP (Minimum Viable Product)
**Last Updated**: April 2026
**Audience**: Data scientists, ML engineers, scoring system maintainers

## Executive Summary

This document describes the **Ukraine-specific cohort taxonomy** for Project Argus Layer 2 (cohort-based statistical scoring). The system normalizes messy free-text job titles and institution names into structured semantic dimensions, enabling robust percentile-based outlier detection while respecting Ukrainian government structure and e-declaration conventions.

### Key Principles

1. **Ukraine-specific**: Separates central vs. local government, judiciary, law enforcement, state enterprises—avoiding Western assumptions.
2. **Respect raw data**: Raw title/institution names preserved for debugging and future manual curation.
3. **Automatic normalization with confidence scoring**: Keyword clustering and fuzzy matching with explicit confidence thresholds; low-confidence mappings flagged for review.
4. **Fallback hierarchy**: When a cohort is too small, gracefully degrade to coarser groupings (year+sector+govt_level → year+sector → year → global).
5. **Backward compatible**: Existing `(post_type, year)` cohorts remain functional; new dimensions are additive.

---

## Architecture

### Components

#### 1. **RoleClusterer** (`backend/app/scoring/cohort_taxonomy.py`)

Clusters raw Ukrainian job titles (`work_post` field) into semantic role families via keyword matching.

**Predefined clusters** (based on Ukrainian terminology):
- `physician`: Лікар, Хірург, Кардіолог, Стоматолог, etc.
- `nurse_paramedic`: Медсестра, Фельдшер, Акушерка, etc.
- `technician`: Техпрацівник, Залізничник, Електрик, etc.
- `manager`: Директор, Начальник, Голова, Завідувач, etc.
- `judge_prosecutor`: Суддя, Прокурор, Слідчий, Адвокат, etc.
- `teacher`: Вчитель, Викладач, Профессор, Педагог, etc.
- `engineer`: Інженер, Програміст, Архітектор, etc.
- `administrative`: Референт, Спеціаліст, Консультант, Бухгалтер, etc.
- `security`: Офіцер,態, Комбат, Спецназ, etc.
- `other`: Unmatched titles

**Method**: TF-IDF-like keyword analysis (MVP uses simple keyword matching; can be extended with ML).

#### 2. **InstitutionNormalizer** (`backend/app/scoring/cohort_taxonomy.py`)

Fuzzy-matches raw institution names (`work_place`, `source_name`) against a seed canonical list, or extracts institution type from keywords.

**Matching strategy**:
1. **Fuzzy matching**: Compare raw name against seed canonical names + aliases (Levenshtein distance + keyword overlap).
   - Score ≥ 0.75 → use canonical name with high confidence
   - Score ≥ 0.60 → use canonical name with medium confidence
   - Score < 0.60 → fall through to keyword extraction

2. **Keyword extraction**: If no fuzzy match, extract institution type from keywords (e.g., "ЛІКАРНЯ" → healthcare, "СУД" → judiciary).

3. **Fallback to unknown**: If neither strategy works, mark as `institution_type="unknown"` for manual review.

**Institution types** (aligned with Ukrainian institutional structure):
- `judiciary`: Courts, prosecutors, legal
- `healthcare`: Hospitals, clinics, health authorities
- `education`: Schools, universities, colleges
- `local_government`: Councils, mayors' offices, village/district/regional authorities
- `central_government`: Ministries, state agencies, parliament offices
- `state_enterprise`: State-owned or communal enterprises (railways, energy, post, etc.)
- `law_enforcement`: Police, border guard, security
- `security`: SBU, National Guard, intelligence
- `defense`: Military ministries, General Staff
- `media_culture`: National TV/radio, cultural institutions, theaters, museums
- `science`: Academia, research institutes, National Academy of Sciences
- `agriculture`: Agricultural ministries and agencies
- `unknown`: Could not be classified

#### 3. **TaxonomyMapper** (`backend/app/scoring/cohort_taxonomy.py`)

Maps `post_type` (semi-structured field from e-declaration) → `sector` and `government_level` via keyword matching.

**Sector mapping** (from post_type keywords):
- `healthcare` ← keywords: МЕДИК, ОХОРОНА ЗДОРОВ'Я, etc.
- `judiciary` ← keywords: СУД, ПРОКУРАТУР, etc.
- `education` ← keywords: ОСВІТ, ШКОЛ, ВИКЛАДАЧ, etc.
- `local_government` ← keywords: МІСЦЕВОМ САМОВРЯД, РАДА, etc.
- `central_government` ← keywords: ЦЕНТР, ДЕРЖАВН, МІНІСТЕРСТВ, etc.
- `security_defense` ← keywords: БЕЗПЕК, ОБОРОН, ПОЛІЦ, ВІЙСЬКОВ, etc.
- `state_enterprise` ← keywords: ПІДПРИЄМСТВ, КОМУНАЛЬН, etc.
- `media_culture` ← keywords: МЕДІА, ТЕЛЕ, РАДІО, КУЛЬТУР, etc.
- `science` ← keywords: НАУК, ДОСЛІД, ІНСТИТУТ, etc.
- `agriculture` ← keywords: АГР, СІЛЬСЬК, etc.
- `other` ← no match

**Government level mapping** (from post_type + post_category):
- `local` ← keywords: МІСЦЕВОМ САМОВРЯД, СЕЛИЩ, СІЛЬСЬК, РАЙОНН, ОБЛАСН
- `central` ← keywords: ЦЕНТР, ДЕРЖАВН, МІНІСТЕРСТВ, ВЕРХОВН
- `state_enterprise` ← keywords: КОМУНАЛЬН, ДЕРЖАВН ПІДПРИЄМСТВ
- `commission` ← keywords: ВЛК, ЛЛК, МСЕК (review/examination commissions)
- `other` ← no match

#### 4. **CohortKeyBuilder** (`backend/app/scoring/cohort_taxonomy.py`)

Builds multi-dimensional cohort keys and manages fallback hierarchy.

**Primary cohort dimensions**:
- `year`: Declaration year (int)
- `sector`: Normalized sector (string)
- `government_level`: Normalized government level (string)
- `region` (optional): Primary region, used only for area-based features

**Cohort key formats**:

*For income/assets/cash/confidentiality features*:
```
cohort_key = f"{year}_{sector}_{government_level}"
e.g., "2024_healthcare_central", "2023_local_government_central"
```

*For dwelling/agricultural area* (region-sensitive):
```
cohort_key = f"{year}_{sector}_{government_level}_{region}" (if region available)
e.g., "2024_healthcare_central_kyiv"
```

#### 5. **CohortFallbackResolver** (`backend/app/scoring/cohorts.py`)

Implements fallback hierarchy when a cohort has fewer than `min_cohort_size` declarations.

**Fallback chain** (for income/assets):
```
1. year + sector + government_level     ← Primary (finest granularity)
2. year + sector                        ← Drop government_level
3. year                                 ← Drop sector
4. global                               ← All declarations pooled
```

**Fallback chain** (for area-based features, region-sensitive):
```
1. year + sector + government_level + region    ← Primary (with region)
2. year + sector + government_level            ← Drop region
3. year + sector                               ← Drop government_level
4. year                                        ← Drop sector
5. global                                      ← All declarations pooled
```

**Configuration**:
- `min_cohort_size` (default 30): minimum declarations required before fallback
- Configurable per feature type (e.g., 30 for income, 50 for area)

---

## Configuration

### `backend/app/scoring/cohort_taxonomy.yaml`

YAML configuration file with three sections:

#### 1. Seed Institution List

```yaml
institutions:
  - canonical_name: "Верховний Суд України"
    aliases: ["Верховний суд", "ВСУ"]
    institution_type: "judiciary"
    edrpou: ""  # optional Ukrainian business ID
```

Add new institutions as needed. The normalizer will fuzzy-match raw names against this list.

#### 2. Sector Keyword Mappings

```yaml
sector_keywords:
  healthcare:
    - ["МЕДИК", "ЛІКАР", "ОХОРОНА ЗДОРОВ'Я"]
  judiciary:
    - ["СУД", "ПРОКУРАТУР"]
  ...
```

#### 3. Government Level Keyword Mappings

```yaml
government_level_keywords:
  local:
    - ["МІСЦЕВОМ САМОВРЯД", "СЕЛИЩ"]
  central:
    - ["ЦЕНТР", "ДЕРЖАВН"]
  ...
```

#### 4. Cohort Configuration

```yaml
cohort_configuration:
  min_cohort_size: 30
  min_mapping_confidence: 0.60
  max_edit_distance: 5
  min_overlap_score: 0.3
```

---

## Usage

### 1. Normalize a Single Declaration Profile

```python
from app.scoring.cohort_taxonomy import create_normalizer_from_config

# Load config and create normalizer
normalizer = create_normalizer_from_config(
    "backend/app/scoring/cohort_taxonomy.yaml"
)

# Normalize a profile
norm = normalizer.normalize(
    work_post="Лікар хірург",
    work_place="Київська обласна лікарня",
    post_type="Посада в органах охорони здоров'я",
    post_category="п'ята категорія",
)

# Access results
print(f"Role family: {norm.role_family}")
print(f"Sector: {norm.sector}")
print(f"Government level: {norm.government_level}")
print(f"Institution type: {norm.institution_family}")
print(f"Role confidence: {norm.role_family_confidence}")
```

### 2. Build Multi-Dimensional Cohorts

```python
from app.scoring.cohorts import build_multi_dimensional_cohorts

summaries = [...]  # List of dicts with normalized fields
cohorts = build_multi_dimensional_cohorts(
    summaries,
    min_cohort_size=30,
)

# Access cohort stats
stats = cohorts["2024_healthcare_central"]
print(f"Cohort size: {stats.size}")
print(f"Incomes percentiles: {stats.incomes}")  # Sorted
```

### 3. Resolve Cohort Keys with Fallback

```python
from app.scoring.cohorts import CohortFallbackResolver

resolver = CohortFallbackResolver(cohorts, min_cohort_size=30)

# For income feature: try full key, then fallback
key, chain = resolver.resolve_for_income_assets(
    year=2024,
    sector="healthcare",
    government_level="central",
)

cohort = resolver.get_cohort(key)
if cohort:
    pct_rank = compute_percentile_rank(income=100000, distribution=cohort.incomes)
```

### 4. Run Diagnostics

```bash
python scripts/inspect_cohorts.py \
    --data data/crawl_state_smoke.json \
    --config backend/app/scoring/cohort_taxonomy.yaml \
    --min-cohort-size 30 \
    --output output/cohort_inspection.json \
    --markdown output/cohort_inspection.md
```

**Output**:
- JSON report: Detailed statistics, low-confidence mappings, sparsity analysis
- Markdown report: Human-readable summary with recommendations
- Console output: Quick summary with key metrics

**Key metrics**:
- **Cohort sparsity**: % of dimension combinations with no data
- **Fallback rates**: % of declarations requiring fallback chain
- **Confidence distribution**: Role family and institution family confidence scores
- **Low-confidence mappings**: Titles/institutions below 0.6 confidence (manual review queue)

---

## Extending the Taxonomy

### Adding a New Role Cluster

1. Edit `RoleClusterer.ROLE_CLUSTERS` in `backend/app/scoring/cohort_taxonomy.py`:

```python
ROLE_CLUSTERS = {
    ...
    "new_role": [
        "KEYWORD1", "KEYWORD2", "KEYWORD3",  # Ukrainian keywords
    ],
    ...
}
```

2. Add test cases in `backend/app/tests/test_cohort_taxonomy.py`:

```python
def test_cluster_new_role(self, clusterer):
    result = clusterer.cluster("Посада з ключовим словом KEYWORD1")
    assert result.role_family == "new_role"
```

3. Run tests: `pytest backend/app/tests/test_cohort_taxonomy.py::TestRoleClusterer::test_cluster_new_role`

### Adding a New Institution

1. Edit `backend/app/scoring/cohort_taxonomy.yaml`:

```yaml
institutions:
  - canonical_name: "New Institution Name"
    aliases: ["Abbreviation", "Alternative name"]
    institution_type: "appropriate_type"
    edrpou: "12345678"  # if available
```

2. Re-run diagnostics to verify the new institution is being matched.

### Refining Keyword Mappings

1. Run diagnostics to identify low-confidence mappings:

```bash
python scripts/inspect_cohorts.py --data data/crawl_state_campaign_2024_5k.json
```

2. Review the JSON report:
   - Look at `low_confidence_summary` and `role_family_stats.*.low_confidence_titles`
   - Note the most common unmatched titles

3. Add new keywords to `cohort_taxonomy.yaml` or `RoleClusterer.ROLE_CLUSTERS`

4. Re-run diagnostics to assess improvement

---

## Known Limitations & Future Work

### Current Limitations

1. **Manual role clustering keywords**: RoleClusterer uses hardcoded keyword lists, not ML-based clustering. This is intentional (MVP simplicity) but limits scalability.
   - **Mitigation**: Diagnostics script flags unmatched titles; can be reviewed and added to ROLE_CLUSTERS iteratively.

2. **Seed institution list is static**: InstitutionNormalizer relies on a hardcoded list of ~50-100 canonical institutions.
   - **Mitigation**: Fuzzy matching + keyword extraction for unmapped institutions. Diagnostics tool reports unresolved institutions for manual curation.

3. **No integration with external registries**: Could integrate with official Ukrainian government registries (EDRPOU, court registries, etc.), but out of scope for MVP.
   - **Future work**: Add optional EDRPOU lookup if needed.

4. **Region only for area features**: `primary_region` used only in dwelling/agri area cohorts, not as a general dimension.
   - **Rationale**: Regional variation more important for land/housing than for income/assets (Ukrainian wealth more evenly distributed by sector than by region).

5. **Multi-role declarations not handled**: Some officials list multiple concurrent positions; MVP uses primary role only.
   - **Future work**: Support role combinations or multi-label cohorts.

### Future Enhancements

- **Machine learning clustering**: Retrain RoleClusterer on new declarations periodically; use hierarchical clustering or DBSCAN for automatic discovery.
- **Manual curation interface**: UI for accepting/rejecting low-confidence mappings, with feedback loop to improve keyword lists.
- **Integration with government registries**: Use EDRPOU codes for exact institution matching where available.
- **Hierarchical cohort dimensions**: Support fallback within sector (e.g., specific hospital → general healthcare → global).
- **Temporal stability analysis**: Track cohort shifts over time; flag when role distributions or institution names change significantly.

---

## Testing

### Run All Cohort Taxonomy Tests

```bash
pytest backend/app/tests/test_cohort_taxonomy.py -v
```

Key test suites:
- **TestRoleClusterer**: Consistency, accuracy on Ukrainian titles
- **TestInstitutionNormalizer**: Fuzzy matching, type extraction
- **TestTaxonomyMapper**: Sector and government_level mapping
- **TestCohortKeyBuilder**: Key construction and fallback chains
- **TestEndToEndUkrainianDeclarations**: Synthetic central ministry officials, local council members, judges
- **TestBackwardCompatibility**: Existing (post_type, year) cohorts still work

### Backward Compatibility

Existing scoring pipeline should continue working without changes:
```python
from app.scoring.cohorts import build_cohort_distributions, score_declaration_l2

# Old code still works
cohorts = build_cohort_distributions(summaries)  # Returns (post_type, year) cohorts
results = score_declaration_l2(income, assets, cohort)
```

---

## Audit Trail & Debugging

### Preserve Raw Values for Auditing

Every normalization stores raw input alongside normalized output:

```python
norm = normalizer.normalize(
    work_post="Лікар-кардіолог в гірській лікарні",
    ...
)

# Raw values preserved
assert norm.work_post_raw == "Лікар-кардіолог в гірській лікарні"

# Normalized values
assert norm.role_family == "physician"

# Confidence for manual review
assert 0.6 <= norm.role_family_confidence <= 1.0
```

### Fallback Chain Logging

The CohortFallbackResolver logs all fallback usage:

```python
resolver = CohortFallbackResolver(cohorts)

key, chain = resolver.resolve_for_income_assets(
    year=2024,
    sector="healthcare",
    government_level="central",
)

# Log for auditing
for trail in resolver.fallback_log:
    print(f"Declarant {trail.declarant_id}: used {trail.used_cohort_key} "
          f"instead of {trail.original_cohort_key}")
```

---

## References & Related Code

- **Main module**: `backend/app/scoring/cohort_taxonomy.py`
- **Configuration**: `backend/app/scoring/cohort_taxonomy.yaml`
- **Cohort building & scoring**: `backend/app/scoring/cohorts.py` (extended with multi-dimensional support)
- **Diagnostics tool**: `scripts/inspect_cohorts.py`
- **Tests**: `backend/app/tests/test_cohort_taxonomy.py`
- **Existing cohort docs**: `backend/app/scoring/cohorts.py` (docstrings)

---

## Contact & Support

For questions, issues, or enhancement requests regarding the cohort taxonomy:

1. Check existing issues and diagnostics output
2. Run `scripts/inspect_cohorts.py` to diagnose mapping quality
3. Review low-confidence mappings in unresolved review queue
4. Extend keyword lists in `cohort_taxonomy.yaml` or `RoleClusterer.ROLE_CLUSTERS`

---

**Last updated**: April 2026
**Version**: 1.0 (MVP)
