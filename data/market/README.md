# Raw Market Data Archive

This directory stores public raw market observations used for reproducible research. Files here are source archives, not validated signals or investment recommendations.

## Binance perpetual funding rates

- File: `binance_funding_rates.json`
- Source: Binance USD-M BTCUSDT perpetual funding-rate public API
- Observation key: `funding_time_ms`
- Main values: `funding_rate` and optional `mark_price`
- Retrieval metadata: `retrieved_at_utc`
- Updates: the daily runner retrieves the latest API page and merges it into the archive; `scripts/backfill_funding.py` backfills historical ranges

Unchanged observations are deduplicated. If the source returns a different funding rate or mark price for an existing funding timestamp, the changed observation is retained as a separate row instead of silently overwriting the prior record.

Historical ranges are filled by `python scripts/backfill_funding.py --start <date-or-ms> [--end <date-or-ms>]`. The backfill is resumable: each page is archived before the cursor in `binance_funding_rates.backfill-state.json` advances, reaching the per-invocation page budget is a checkpoint rather than an error, and a completed range reruns without network calls. Do not hand-edit the archive or state file; rerun the command (with `--restart` to re-scan a range) instead.

Historical point-in-time availability and source revisions are not independently verified. Funding rates are excluded from BFS, BOS, and market-state assignment until the feature definition and evaluation are explicitly approved and tested.
