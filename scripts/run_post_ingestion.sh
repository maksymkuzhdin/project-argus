#!/usr/bin/env bash
set -euo pipefail
# Project Argus — Post-Ingestion Pipeline
# Run this after run_overnight_ingestion.sh completes.
# Normalizes, processes, and scores all raw declarations in data/raw/.

echo "=== Step 1: Normalization ==="
python scripts/run_normalization.py --batch-size 1000
echo "=== Step 2: Pipeline + Feature Extraction ==="
python scripts/run_pipeline.py --batch-size 1000
echo "=== Step 3: Scoring ==="
python scripts/run_scoring.py --batch-size 1000
echo "=== Step 4: Cohort Quality Report ==="
python scripts/inspect_cohorts.py --report
echo "=== All done. Check output/ for results. ==="