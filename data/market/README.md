# Raw Market Data Archive

This directory stores public raw market observations used for reproducible research. Files here are source archives, not validated signals or investment recommendations.

## Binance perpetual funding rates

- File: `binance_funding_rates.json`
- Source: Binance USD-M BTCUSDT perpetual funding-rate public API
- Observation key: `funding_time_ms`
- Main values: `funding_rate` and optional `mark_price`
- Retrieval metadata: `retrieved_at_utc`
- Updates: the daily runner retrieves the latest API page and merges it into the archive

Unchanged observations are deduplicated. If the source returns a different funding rate or mark price for an existing funding timestamp, the changed observation is retained as a separate row instead of silently overwriting the prior record.

The archive starts with observations collected after deployment unless a separate historical backfill is run. Historical point-in-time availability and source revisions are not independently verified. Funding rates are excluded from BFS, BOS, and market-state assignment until the feature definition and evaluation are explicitly approved and tested.
