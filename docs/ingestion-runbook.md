# Ingestion Runbook

Operational guide for long-running NAZK ingestion campaigns.

## Objectives
- Run ingestion safely for multi-hour sessions.
- Resume after interruptions without losing progress.
- Capture enough telemetry to tune throughput and retry settings.

## Preconditions
- Python environment configured and dependencies installed.
- Raw storage path exists (`data/raw`).
- Separate state files per campaign to avoid cross-year mixing.

## Baseline Campaign Command

```bash
python scripts/run_ingestion.py \
  --year 2024 \
  --max-pages 1000 \
  --concurrency 3 \
  --page-delay 0.4 \
  --resume \
  --state-file data/crawl_state_2024_campaign_a.json
```

## Chunked Campaign Pattern

Use page chunks to keep checkpoints and operator control predictable:

```bash
python scripts/run_ingestion.py --year 2024 --max-pages 200 --resume --state-file data/crawl_state_2024_campaign_a.json
# repeat the same command for next chunk
```

This advances from `last_page + 1` automatically.

## Throughput and Reliability Targets
- Retry warning rate: less than 5% of requests.
- Error count growth: flat or very low after initial pages.
- Saved/fetched ratio: at least 90% once already-saved pages are skipped.
- Chunk runtime consistency: similar wall-clock duration per 200-page chunk.

If retry/error rates rise:
- Lower `--concurrency` from 3 to 2.
- Increase `--page-delay` from 0.4 to 0.8.
- Keep `--resume` and re-run later.

## Monitoring Checklist
- Watch console output for repeated page-level failures.
- Inspect state snapshot:

```bash
cat data/crawl_state_2024_campaign_a.json
```

Key fields:
- `last_page`
- `total_fetched`
- `total_saved`
- `total_skipped`
- `errors`
- `completed`

## Safe Stop / Resume
- Stop process with Ctrl+C.
- Resume with the same command and state file.
- Never manually decrement `last_page` unless you intentionally want replay.

## Post-Campaign Actions
1. Archive state file to `data/state_archive/` with timestamp.
2. Run persistence refresh cycle:
   - `python scripts/run_refresh_cycle.py --year 2024 --skip-ingestion --csv output/scores_2024_refresh.csv`
3. Verify API health:
   - `curl http://localhost:8000/health`
4. Spot-check dashboard and person timeline pages.
