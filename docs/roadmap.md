# Roadmap

This file tracks implementation-focused milestones. For the full strategic plan,
see `project_argus_consolidated_plan.md`.

Operational crawl guidance: `docs/ingestion-runbook.md`.
Release readiness checklist: `docs/release-checklist.md`.

## M1 - Data Pipeline Reliability

Status: In progress

Goals:
- Keep ingestion resumable across long-running campaigns.
- Ensure parse/sanitize logic handles placeholder-heavy records safely.
- Maintain successful persist + refresh cycle to Postgres.

Exit criteria:
- Ingestion runbook command succeeds for multiple consecutive chunks.
- `scripts/run_refresh_cycle.py` completes with DB persistence enabled.
- Backend test suite remains green.

## M2 - Scoring Completeness

Status: Complete

Goals:
- Keep deterministic Layer 1 and timeline scoring stable.
- Keep cohort Layer 2 integrated in offline scoring workflows with Isolation Forest, a dense autoencoder, and ECOD.
- Preserve explanation-first outputs for every triggered rule.
- Keep cohort-normalized scoring and confidence tiers visible in offline outputs.

Exit criteria:
- `scripts/run_scoring.py --layer2` executes without TODO/stub paths.
- Score explanations remain present in API and CSV exports.
- Cohort-scoped outputs are produced for the intended training sample size rather than a monolithic 7M-record fit.
- Documentation in `docs/scoring-methodology.md` matches implementation.
- Layer 1 scoring thresholds and weights are centralized in `backend/app/scoring/config.yml`.

## M3 - Frontend Quality Gate

Status: In progress

Goals:
- Keep dashboard, declaration, and person pages production-buildable.
- Enforce lint + build checks in CI.

Exit criteria:
- `frontend` passes `npm run lint` and `npm run build` locally.
- CI workflow validates backend tests and frontend quality checks.

## M4 - Integration Confidence

Status: In progress

Goals:
- Add database-backed API integration tests.
- Add frontend end-to-end smoke coverage for primary user journeys.

Exit criteria:
- One API integration test verifies DB query path. ✓ (test_api_db_integration.py)
- One UI smoke test covers dashboard -> declaration -> person flow. ✓ (e2e/smoke-tests.spec.ts)
- CI runs e2e suite after backend tests pass. ✓ (.github/workflows/ci.yml)

## M5 - Public Beta Readiness

Status: In progress

Goals:
- Finalize contributor-facing docs and licensing.
- Add release checklist for ingestion/scoring refresh and rollback.
- Confirm the public beta path uses low-cost hosted infrastructure rather than AWS.

Exit criteria:
- Root and frontend READMEs describe real project workflows.
- License file is present and referenced.
- Release checklist exists and is testable by a new contributor (`docs/release-checklist.md`).
- Contributor docs are reconciled against implementation status and setup flow.
- A read-only demo deployment path is documented for the current hosting target.
