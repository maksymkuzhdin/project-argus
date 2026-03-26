# Project Argus

An open-source civic-tech platform that ingests Ukrainian public asset declarations, normalizes them, computes transparent anomaly signals, and presents results in a polished, neutral dashboard for journalists, watchdogs, and citizens.

> **Note:** Anomalies surfaced by this tool are not proof of illegality. They are statistical signals intended to help investigators prioritize further human review.

**→ [Quick Start Guide](QUICKSTART.md)** — 5 minutes to launch the dashboard locally or via Docker.

---

## Prerequisites

| Tool | Minimum version |
| ------ | --------------- |
| Docker | 24+ |
| Docker Compose | v2 |
| Node.js | 20+ |
| Python | 3.11+ |

---

## Quick Start (Docker Compose)

```bash
# 1. Clone and enter the repo
cd argus

# 2. Create your local env file
cp .env.example .env          # edit values if needed

# 3. Build and start all services
docker compose up --build -d

# 4. Verify
curl http://localhost:8000/health   # → {"status":"ok"}
open http://localhost:3000          # Next.js frontend
```

To stop everything:

```bash
docker compose down
```

To destroy the database volume too:

```bash
docker compose down -v
```

---

## Running Services Individually

### Database

Docker Compose starts Postgres automatically. To connect manually:

```bash
psql postgresql://argus:argus_local@localhost:5432/argus
```

### Backend (FastAPI)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> Set `DATABASE_URL=postgresql://argus:argus_local@localhost:5432/argus` in your shell or a local `.env` when running outside Docker.

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

The dev server starts on `http://localhost:3000`.

---

## Database Migrations (Alembic)

```bash
cd backend

# Create a new migration after changing models
alembic revision --autogenerate -m "describe change"

# Apply migrations
alembic upgrade head
```

In Docker, the backend now performs reconciliation + migrations automatically
on container start (`backend/start.sh`):

1. `python scripts/reconcile_db.py`
2. `alembic upgrade head`
3. start FastAPI

This keeps legacy and fresh databases aligned without manual patching.

---

## Bulk Ingestion (Resumable)

Use the ingestion CLI for long-running crawls. It supports retries,
page throttling, checkpointed crawl state, and resume mode.

```bash
python scripts/run_ingestion.py \
  --year 2024 \
  --max-pages 200 \
  --concurrency 3 \
  --page-delay 0.4 \
  --resume \
  --state-file data/crawl_state.json
```

Useful flags:

- `--resume`: continue from `last_page + 1` in the state file.
- `--max-docs N`: stop after saving `N` new declarations.
- `--start-page N`: override initial page for fresh runs.
- `--state-file PATH`: keep separate checkpoints for different campaigns.

Detailed operations guidance: `docs/ingestion-runbook.md`.

---

## Refresh Cycle (Ingest -> Persist -> Score Export)

Run a full refresh workflow with one command:

```bash
python scripts/run_refresh_cycle.py \
  --year 2024 \
  --skip-ingestion \
  --csv output/scores_refresh.csv
```

To include ingestion in the same run:

```bash
python scripts/run_refresh_cycle.py \
  --year 2024 \
  --ingest-pages 50 \
  --resume \
  --state-file data/crawl_state_refresh_2024.json \
  --csv output/scores_refresh.csv
```

---

## Testing

### Backend API Tests

```bash
cd backend
pytest app/tests -q
```

Includes unit tests for cash classification, income parsing, ML scoring, API endpoint integration, and database query paths. **129 tests** covering normalization, features, scoring, and API contracts.

### Frontend Quality & E2E Tests

```bash
cd frontend
npm run lint   # ESLint + TypeScript strict mode
npm run build  # Production build validation
npm run e2e    # Playwright end-to-end smoke tests (requires running backend)
```

E2E smoke tests exercise three key user journeys:
1. **Dashboard**: Load declarations list, search, pagination
2. **Declaration Detail**: View scores, rules, anomalies
3. **Person Timeline**: Multi-year changes and deltas

Tests are run automatically in CI (see `.github/workflows/ci.yml`) after backend tests pass.

---

## Repo Structure

```
argus/
  README.md
  .env.example
  docker-compose.yml
  /docs           — runbook, roadmap, API and methodology docs
  /data           — raw declarations & fixtures
  /backend        — Python FastAPI application
  /frontend       — Next.js + Tailwind CSS application
  /scripts        — CLI entry-point scripts
```

See [project_argus_consolidated_plan.md](../project_argus_consolidated_plan.md) for the full architecture and roadmap.

---

## License

MIT — see `LICENSE`.
