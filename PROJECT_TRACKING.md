# Project Argus Tracking & Status
**Date:** 2026-04-12

## Overall Project Scope
Project Argus is an open-source civic-tech platform that ingests Ukrainian public asset declarations, normalizes them, computes transparent anomaly signals, and presents results in a polished, neutral dashboard for journalists, watchdogs, and citizens.

## Recent Features & Implementations

### Pipeline Taxonomy Integration (Current Status)
- ✅ **Integration tests completed & passing:** (`backend/tests/test_taxonomy_pipeline_integration.py`) covering all normalization and layer 3 integration steps.
- **RoleClusterer**: Auto-clusters raw job titles into semantic role families.
- **InstitutionNormalizer**: Fuzzy-matches institutions to canonical names.
- **TaxonomyMapper**: Maps post_type to sector and government_level via keyword extraction.
- **CohortKeyBuilder**: Builds multi-dimensional cohort keys with fallback hierarchy.
- **TaxonomyNormalizer**: Unified pipeline combining all normalization, utilized live in `process_declaration_full()`.
- **Diagnostics Tool**: CLI-based cohort analysis with argparse interface (`scripts/inspect_cohorts.py`).

### Verification & Testing 
- All 35 cohort taxonomy tests are passing.
- 100% backward compatible with existing (post_type, year) cohorts.
- Live integration within `backend/app/services/pipeline.py` returns normalized cohort tracking in declaration output.

## Known Limitations & Future Work
**Current MVP Limitations**:
- RoleClusterer uses hardcoded keywords (not ML-trained).
- InstitutionNormalizer seed list is static (~51 entries).
- No integration with external Ukrainian government registries.
- Multi-role declarations use primary role only.

**Future Enhancements** (out of scope for now):
- Machine learning clustering with periodic retraining.
- Manual curation UI for accepting/rejecting mappings.
- EDRPOU integration for exact institution matching.
- Hierarchical cohort fallback within sectors.
- Temporal stability analysis.

## Operational Notes
- Monitor normalization quality using `scripts/inspect_cohorts.py` monthly.
- Review low-confidence mappings and expand seed institutions as needed.
- Monitor fallback usage for cohorts that are too small.
