# Project Argus — Tracking, Status & Architecture

**Last updated:** 2026-04-12

---

## Overall Project Scope

Project Argus is an open-source civic-tech platform that ingests Ukrainian public asset declarations from the NACP (National Agency on Corruption Prevention) API, normalizes them, computes transparent anomaly signals across multiple scoring layers, and presents results in a polished, neutral dashboard for journalists, watchdogs, and citizens.

---

## Architecture Overview

```
NACP API
  └─ scripts/run_ingestion.py          ← Bulk async ingestor (NEW: stratified, resumable)
       └─ data/raw/{year}/declaration_{id}.json
  └─ scripts/run_normalization.py       ← Normalise raw → DB rows
  └─ scripts/run_scoring.py            ← Anomaly scoring pipeline
  └─ scripts/run_persist.py            ← DB persistence
  └─ scripts/run_pipeline.py           ← Full pipeline runner
  └─ scripts/run_refresh_cycle.py      ← Scheduled refresh
backend/app/
  ├─ ingestion/
  │   ├─ client.py        ← Async NACP httpx client (semaphore, backoff)
  │   ├─ crawl_state.py   ← Legacy page-based crawl state (JSON)
  │   └─ save_raw.py      ← Idempotent raw JSON writer
  ├─ scoring/             ← Multi-layer anomaly scoring (L1-L3)
  ├─ services/pipeline.py ← Full pipeline with taxonomy normalisation
  └─ config.py            ← Pydantic settings (NACP base URL, concurrency, etc.)
frontend/                 ← Dashboard (Next.js)
data/
  ├─ raw/{year}/          ← Raw declaration JSON (one file per declaration)
  └─ checkpoints/         ← Bulk ingestion resumable checkpoints (NEW)
```

---

## Feature Status

### ✅ Bulk Ingestion — `scripts/run_ingestion.py` (2026-04-12)

Upgraded from a simple synchronous page crawler to a production-grade bulk ingestor targeting 50,000+ declarations.

**New capabilities:**

| Feature | Detail |
|---|---|
| **Stratified crawl** | `--strategy uniform` (all categories equally) or `targeted` (high-risk-first: national→regional→local) |
| **Async parallel fetch** | `asyncio` + `httpx.AsyncClient` with `asyncio.Semaphore` cap (`--concurrency`, default 5) |
| **Rate limiter** | Token-bucket RPS cap (`--rate-limit`, default 3 req/s) |
| **Exponential backoff** | On HTTP 429/503: waits `2^attempt` seconds, up to 5 retries, then skips + logs |
| **Resumable checkpoint** | `data/checkpoints/ingestion_checkpoint.json` — stores last category/page + fetched ID set; written every 100 fetches; deleted on clean completion |
| **Decoupled output** | Writes only to `data/raw/{year}/declaration_{id}.json`; no pipeline/scoring calls |
| **Idempotent** | Re-running skips declarations already on disk or in checkpoint set |
| **Progress reporting** | Every 500 declarations: fetched/skipped/failed counts + throughput + elapsed |
| **Dry-run mode** | `--dry-run` prints full crawl plan (categories, estimated counts, depth, ETA) without API calls |
| **Backward-compatible** | All existing CLI arguments (`--year`, `--max-pages`, `--concurrency`, `--resume`, `--state-file`, `--start-page`, `--page-delay`, `--max-docs`) preserved |

**CLI quick reference:**
```bash
# Preview crawl plan (no API calls)
python scripts/run_ingestion.py --strategy targeted --dry-run

# Targeted high-risk crawl, 2024 only, 100 pages/category
python scripts/run_ingestion.py --year 2024 --strategy targeted --max-pages 100

# Resume interrupted bulk run
python scripts/run_ingestion.py --resume --strategy targeted

# Full uniform crawl, low rate limit
python scripts/run_ingestion.py --strategy uniform --rate-limit 1.5 --max-pages 500
```

**NACP post_category taxonomy used:**

| Code | Label | Risk Tier |
|---:|---|:---:|
| 1 | National officials (President/PM/Cabinet) | HIGH |
| 2 | Parliament members (Verkhovna Rada) | HIGH |
| 3 | Judges (Supreme & appellate courts) | HIGH |
| 4 | Prosecutors & senior law enforcement | HIGH |
| 8 | National bank & financial regulators | HIGH |
| 9 | Military & security service leaders | HIGH |
| 5 | Regional officials (oblast/raion heads) | MED |
| 6 | Local officials (city/village mayors) | MED |
| 7 | State enterprise executives | MED |
| 10 | Other public officials | LOW |
| 0 | Uncategorised / legacy records | LOW |

**Dependencies used:** `httpx>=0.27` (already in `backend/requirements.txt`), `asyncio` (stdlib).

---

### ✅ Pipeline Taxonomy Integration (2026-04-12)

- **Integration tests completed & passing:** (`backend/tests/test_taxonomy_pipeline_integration.py`) — all 35 cohort taxonomy tests passing.
- **RoleClusterer**: Auto-clusters raw job titles into semantic role families.
- **InstitutionNormalizer**: Fuzzy-matches institutions to canonical names (~51 entries).
- **TaxonomyMapper**: Maps post_type → sector and government_level via keyword extraction.
- **CohortKeyBuilder**: Multi-dimensional cohort keys with fallback hierarchy.
- **TaxonomyNormalizer**: Unified pipeline combining all normalization, live in `process_declaration_full()`.
- **Diagnostics Tool**: `scripts/inspect_cohorts.py` — CLI-based cohort analysis.

### ✅ Anomaly Scoring (Multi-Layer)

- **Layer 1 (Rule-based):** Hard-coded rule set (CR/BR series) covering income, assets, real estate, vehicles, cash.
- **Layer 2 (Cohort stats):** Percentile-based outlier detection by (post_type, year) cohort.
- **Layer 3 (ML):** Optional unsupervised model (`layer3_enabled` in config).
- **0–100 composite score** with per-rule explanations.
- **Timeline rules:** CR5, BR2, BR4 for year-over-year anomaly detection.
- **Scoring diagnostics:** `scripts/evaluate_scoring.py`, `scripts/evaluate_layer3.py`.

### ✅ EDRPOU / Prozorro Cross-Reference

- Real estate CR15 data integrated into year-over-year change cards on the person timeline page.
- Triggered rule explanations enriched with metadata.

---

## Known Limitations & Future Work

**Current MVP limitations:**
- `RoleClusterer` uses hardcoded keywords (not ML-trained).
- `InstitutionNormalizer` seed list is static.
- No integration with external Ukrainian government registries beyond NACP.
- Multi-role declarations use primary role only.
- `post_category` mapping relies on NACP integer codes — verify these codes against latest NACP API documentation before large-scale runs.

**Future Enhancements (out of current scope):**
- Machine-learning clustering with periodic retraining.
- Manual curation UI for accepting/rejecting taxonomy mappings.
- EDRPOU integration for exact institution matching.
- Hierarchical cohort fallback within sectors.
- Temporal stability analysis.
- Distributed ingestion across multiple workers.

---

## Operational Notes

- **Ingestion:** Run `python scripts/run_ingestion.py --dry-run` before starting a new bulk crawl to verify the plan.
- **Resuming:** Always pass `--resume` to continue interrupted runs; checkpoint is at `data/checkpoints/ingestion_checkpoint.json`.
- **Rate limits:** NACP API responds to high traffic with 429s. Default `--rate-limit 3` is conservative; reduce to `1.5` if seeing frequent retries.
- **Normalization quality:** Monitor using `scripts/inspect_cohorts.py` monthly; expand seed institutions as needed.
- **Fallback tracking:** Monitor fallback usage for cohorts that are too small.
