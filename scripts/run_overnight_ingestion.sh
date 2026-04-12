#!/usr/bin/env bash
set -euo pipefail
# Project Argus — Overnight Bulk Ingestion
# Run this from the repo root: bash scripts/run_overnight_ingestion.sh
# It will ingest up to 50,000 declarations from the NACP API (targeted strategy, 2024)
# and write raw JSON to data/raw/2024/.
# Estimated runtime: 6–8 hours at 3 req/s.
# If interrupted, re-run with --resume (the script handles this automatically).

LOG_FILE="data/ingestion_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/raw data/checkpoints
echo "Starting ingestion — logging to $LOG_FILE"
echo "Press Ctrl+C to interrupt. Re-run this script to resume automatically."
python scripts/run_ingestion.py \
  --strategy targeted \
  --year 2024 \
  --max-pages 50 \
  --concurrency 5 \
  --rate-limit 3 \
  --max-docs 50000 \
  --resume \
  2>&1 | tee "$LOG_FILE"
echo ""
echo "Ingestion complete. Check $LOG_FILE for details."
echo "Next step: run scripts/run_normalization.py --batch-size 1000"