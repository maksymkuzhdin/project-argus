#!/bin/sh
set -eu

cd /app
export PYTHONPATH=/app

python scripts/reconcile_db.py
alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
