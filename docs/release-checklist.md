# Release Checklist

Use this checklist before any scoring/data refresh release. It is written to be executable by a new contributor.

## 1. Preflight

- [ ] Confirm working tree is clean: `git status --short`
- [ ] Confirm backend tests pass:
  - `cd backend`
  - `python -m pytest app/tests -q`
- [ ] Confirm frontend quality checks pass:
  - `cd frontend`
  - `npm run lint`
  - `npm run build`

## 2. Data Refresh Run

- [ ] Run ingestion or ensure fresh raw data exists under `data/raw/<year>/`.
- [ ] Run refresh cycle from repository root:
  - `python scripts/run_refresh_cycle.py`
- [ ] Confirm output artifacts are generated in `output/`.

## 3. Layer 2 and Timeline Sanity

- [ ] Run cohort-enabled scoring:
  - `python scripts/run_scoring.py --layer2`
- [ ] Run timeline report sanity check:
  - `python scripts/run_timeline.py --top 10`
- [ ] Verify rule explanations are present in score outputs (API/CSV).

## 4. API Verification

- [ ] Start backend service and check health endpoint responds.
- [ ] Verify dashboard list endpoint returns data:
  - `GET /api/declarations`
- [ ] Verify declaration detail includes `rule_details`.
- [ ] Verify person timeline endpoint returns `timeline_score` and `triggered_rules`.

## 5. Rollback-Safe Gate

- [ ] Database backup completed (if using DB path).
- [ ] If schema changes are included, confirm migration revision and downgrade path are documented.
- [ ] Keep previous score export available until new run is validated.

## 6. Release Decision

- [ ] Update relevant docs for any scoring/rule changes.
- [ ] Summarize what changed (rules, thresholds, docs, tests) in commit/PR notes.
- [ ] Tag release only after all checks above pass.

## Notes

- If any checklist item fails, stop and fix before proceeding.
- This checklist is intentionally operational; it does not publish beta by itself.
- Deployment sequence and rollback detail live in `docs/deployment-runbook.md`.
