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
| Derivatives market observations | Public exchange APIs | Funding rates, open interest, liquidations, basis | Core input only with venue coverage, timestamps, and cross-venue caveats |
| Third-party sentiment | Alternative.me Crypto Fear & Greed Index | Optional reference panel in the dashboard | Auxiliary display only; excluded from core scores |
| Third-party on-chain/valuation indicators | Glassnode MVRV, realized price, Mayer Multiple, or similar metrics | Optional reference panel when access permits | Auxiliary display only; excluded from core scores by default |

Candidate source documentation:
- Binance Spot API: https://github.com/binance/binance-spot-api-docs
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

## Historical research backfill

The one-time backfill script can build a provisional daily research archive from available public price history. It may attach historical third-party sentiment observations as auxiliary context, but those observations must not enter the core score. Backfilled outputs are not original CycleMark decisions. Historical source availability and revisions are not point-in-time verified, so the dashboard must label them as research backfill rather than validated historical states.
