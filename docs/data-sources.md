# Data Sources and Provenance

**Status:** Source registry proposal. No source is considered integrated until ingestion, licensing, timestamps, and quality checks are implemented.

## Governing principle

**Core CycleMark scores must be calculated from public raw market observations wherever practical. Third-party calculated indicators are auxiliary display context and are excluded from BFS, BOS, and state assignment by default.**

Publicly accessible does not mean raw. Exchange-published OHLCV is a raw market observation. A provider-computed sentiment index, valuation ratio, or composite score is a derived indicator even if it is free to access.

If a core feature cannot be derived from accessible raw inputs, mark it unavailable. Do not quietly replace it with a third-party metric. Any proposed exception must be explicitly documented, versioned, and validated before it can affect core scores.

## Candidate sources

| Data category | Candidate source | Intended use | Core scoring policy |
|---|---|---|---|
| BTC daily OHLCV | Exchange market-data APIs; cross-check with other public exchanges where practical | Price, returns, moving averages, drawdown, volatility | Core input; document exchange coverage and limitations |
| Spot trade data | Public exchange trade or aggregate-trade endpoints | Volume profile, realized market activity, liquidity proxies | Core input only after robust definitions and quality checks |
| On-chain raw observations | Public blockchain data and reproducible node-derived metrics | UTXO age/spending, realized value components, supply and transfer measures | Prefer reproducible raw observations; document node/indexing assumptions |
| Derivatives market observations | Binance USD-M Futures funding-rate endpoint; additional public exchange APIs to be evaluated | Raw exchange funding-rate observations with funding timestamps and optional mark price | Funding adapter and daily raw-observation archive implemented for research ingestion; not yet included in BFS/BOS. Require venue coverage, point-in-time handling, and cross-venue caveats before scoring |
| Third-party sentiment | Alternative.me Crypto Fear & Greed Index | Optional reference panel in the dashboard | Auxiliary display only; excluded from core scores |
| Third-party on-chain/valuation indicators | Glassnode MVRV, realized price, Mayer Multiple, or similar metrics | Optional reference panel when access permits | Auxiliary display only; excluded from core scores by default |

Candidate source documentation:
- Binance Spot API: https://github.com/binance/binance-spot-api-docs
- Binance USD-M Futures API: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
- Coin Metrics API: https://docs.coinmetrics.io/api/v4/
- Glassnode API documentation: https://docs.glassnode.com/
- Alternative.me Fear & Greed API: https://alternative.me/crypto/fear-and-greed-index/

These links are starting points, not confirmation that all data can be redistributed freely. A third-party provider may be useful for comparison or quality assurance without being a core model input.

## Required data contract

Every observation should contain enough metadata to distinguish when it describes the market from when it became available to the model. Recommended fields:

- Metric
- Asset
- Observation date
- Availability timestamp in UTC
- Retrieval timestamp in UTC
- Value and unit
- Source and source version
- Raw observation vs. derived indicator classification
- Missing-data flag
- Revision flag
- License or terms reference

For historical simulation, use the value that was actually available at the simulated decision time. If historical availability or revisions cannot be reconstructed, flag the limitation and exclude the feature from claims requiring point-in-time accuracy.

## Data quality rules

1. Never silently forward-fill a missing value for a signal-critical feature.
2. Track source outages, stale observations, changes in units, and schema changes.
3. Validate timestamps and duplicate observations.
4. Preserve raw source snapshots when permitted by applicable terms.
5. Store raw inputs separately from CycleMark-derived features and scores.
6. Do not publish proprietary data in violation of provider terms.
7. Clearly distinguish observed values, estimates, third-party derived indicators, and unavailable data.
8. Never use a third-party indicator to manually override a CycleMark state.

## Core quality gates and optional-source isolation

Every daily run writes a `data_quality` block into the published record:

- `data_quality.core_price` summarizes the finalized candle series, including candle count, first and last dates, expected calendar days, missing dates (truncated), duplicate open timestamps, non-UTC-midnight opens, irregular close offsets, latest candle age, and explicit `fatal_issues` and `warnings`.
- `data_quality.optional_sources` records whether each optional feed was `available`, `empty`, or `unavailable`, including an error string when retrieval failed.

The following core conditions fail closed: fewer than 200 finalized candles, an empty series, duplicate or non-increasing open timestamps, opens that are not UTC midnight, irregular close offsets, calendar gaps beyond the allowed threshold, a latest candle older than the staleness window, or a future-dated candle. When a fatal core issue occurs, no daily record is published.

Optional sources are isolated. A Fear & Greed or funding-rate failure is recorded as `unavailable` and the price-only record still publishes. A corrupted or unreadable local funding archive is logged as a non-blocking `funding_archive.status=failed`. Optional data must never be silently substituted for a core input.

## Idempotent publication and revisions

Publishing is deterministic on content: retrieval and generated timestamps are excluded from the fingerprint, so a rerun with identical observations is reported as `unchanged` and does not rewrite the date file. A material change for the same date increments `revision`, preserves `first_published_at_utc`, and archives the previous published version under `data/signals/revisions/<date>-r<revision>.json`. History holds one canonical record per date; `latest.json` is written last so an interrupted run cannot expose an inconsistent newest record.

## Historical research backfill

The daily runner archives the latest Binance USD-M BTCUSDT perpetual funding-rate page in `data/market/binance_funding_rates.json`, deduplicating unchanged observations while preserving changed values at the same timestamp as separate records. Funding data is not yet a core scoring input.

A resumable historical backfill fills the same archive for an explicit range:

    python scripts/backfill_funding.py --start 2019-09-01 --end 2024-01-01

- The range is explicit and validated; `--start` and `--end` accept epoch milliseconds or an ISO UTC date.
- Endpoint limits: the funding API returns at most 1000 observations per page, and BTCUSDT perpetual funding settles every eight hours (three observations per day). Each invocation paginates at most `--max-pages` pages (default 100), which bounds one run to roughly ninety years of funding history in API-page terms; larger ranges simply require rerunning the command.
- Resume: every page is merged and written to the archive before the resume cursor advances in `binance_funding_rates.backfill-state.json`, so an interrupted run loses at most the in-flight page and reruns deduplicate the overlap. Reaching the page budget reports `incomplete`, not an error; rerun the same command to continue. A completed range reruns as `already_complete` without network calls; use `--restart` to re-scan a range.
- Provenance: each observation keeps `funding_time_ms`, `funding_rate`, optional `mark_price`, `symbol`, `source`, `schema_version`, and `retrieved_at_utc`. The state file records the requested range, cursor, page/observation counts, and timestamps.
- Caveat: this dataset is **not** point-in-time reconstructed. `retrieved_at_utc` records when CycleMark collected an observation, not when the value was first knowable, and historical source revisions are not independently verified.

The one-time price backfill script can build a provisional daily research archive from available public price history. It may attach historical third-party sentiment observations as auxiliary context, but those observations must not enter the core score. Backfilled outputs are not original CycleMark decisions. Historical source availability and revisions are not point-in-time verified, so the dashboard must label them as research backfill rather than validated historical states.
