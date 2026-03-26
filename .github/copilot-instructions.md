# Project Guidelines

## Code Style
- Keep backend Python code type-annotated and explicit. Prefer small pure functions in parsing, features, and scoring modules.
- Preserve API response field names in snake_case to match parser and DB outputs.
- Avoid broad refactors unrelated to the task. Keep changes minimal and targeted.

## Architecture
- Backend-first workflow: ingestion -> normalization -> features -> scoring -> API -> frontend.
- Backend boundaries:
  - API routers in backend/app/api
  - Data extraction and cleaning in backend/app/normalization
  - Feature logic in backend/app/features
  - Scoring logic in backend/app/scoring
  - Pipeline orchestration in backend/app/services
- Frontend reads scored data from backend API and should not duplicate scoring logic.

## Build and Test
- Full stack (Docker):
  - docker compose up --build -d
  - docker compose down
- Backend local:
  - cd backend
  - pip install -r requirements.txt
  - uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
- Frontend local:
  - cd frontend
  - npm install
  - npm run dev
- Tests:
  - cd backend
  - pytest
- Migrations:
  - cd backend
  - alembic upgrade head

## Conventions
- Treat anomalies as review signals, not accusations. Keep language neutral.
- Preserve raw JSON as immutable source data. Never overwrite historical raw records.
- Prefer deterministic, explainable scoring outputs with clear rule-level explanations.
- Keep Decimal-safe handling for monetary values; avoid unnecessary float conversion.
- Respect dual API data paths: database-first, then raw-file fallback when DB is empty.

## Operational Notes
- Ingestion supports resumable crawling via scripts/run_ingestion.py with state files.
- NAZK ingestion throughput is intentionally rate-limited by config to reduce request failures.
- Confirm environment values before running services (.env and .env.example alignment).

## Project Docs
- API notes: docs/api-notes.md
- Data dictionary: docs/data-dictionary.md
- Legal guardrails: docs/legal-guardrails.md
- Scoring methodology: docs/scoring-methodology.md
- Roadmap: docs/roadmap.md
- Consolidated plan: ../project_argus_consolidated_plan.md

## General Instructions
- Please keep one consolidated file with all the project specifications: the goals, the timeline of the build, the existing features, and the next steps, etc. Do not create new markdown files after every action to describe what you just have done. Always keep one consolidated file that can be referred to by both humans and AI agents that would be comprehensive.
