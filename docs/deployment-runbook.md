# Deployment Runbook (Pre-Beta)

This runbook defines a safe, repeatable deployment flow for Project Argus before public beta.

## 1. Preconditions

- All checks in [docs/release-checklist.md](docs/release-checklist.md) are complete.
- Branch is up to date with `main` and CI is green.
- Database backup has been taken and restore path is known.

## 2. Staging Deployment Flow

1. Build backend and frontend artifacts from the target commit.
2. Apply database migrations in staging:
   - `cd backend`
   - `alembic upgrade head`
3. Start backend and frontend services.
4. Run smoke checks:
   - `GET /health`
   - `GET /api/declarations?limit=5`
   - `GET /api/persons/{known_uid}`
5. Run quick timeline sanity command:
   - `python scripts/run_timeline.py --top 5`

## 3. Production Deployment Flow

1. Confirm staging validation succeeded.
2. Announce maintenance/deploy window.
3. Apply migrations in production (`alembic upgrade head`).
4. Deploy backend, then frontend.
5. Execute production smoke checks (same as staging).
6. Monitor logs and error rates for 30 minutes.

## 4. Rollback Triggers

Rollback if any of these occur:

- API health endpoint fails for more than 5 minutes.
- Error rate spikes and does not recover after retry/restart.
- Timeline/declaration endpoints return schema-breaking responses.
- Migration introduces data corruption or blocking query failures.

## 5. Rollback Steps

1. Roll back application deployment to previous known-good release.
2. If migration is reversible and required, run:
   - `cd backend`
   - `alembic downgrade -1`
3. Restore DB backup if downgrade is insufficient.
4. Re-run smoke checks on restored version.
5. Record incident notes and root cause before next deploy attempt.

## 6. Post-Deploy Verification

- Confirm dashboard loads and returns sorted results.
- Confirm declaration detail includes rule explanations.
- Confirm person timeline includes `timeline_score` and `triggered_rules`.
- Capture a short deploy summary in release notes.
