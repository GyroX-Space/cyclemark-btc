# Data Sources and Provenance

**Status:** Source registry proposal. No source is considered integrated until ingestion, licensing, timestamps, and quality checks are implemented.

## Candidate sources

| Data category | Candidate source | Intended use | Important caveats |
|---|---|---|---|
| BTC daily OHLCV | Coin Metrics community/API data or exchange market data | Price, returns, moving averages, drawdown, volatility | Verify asset definition, exchange coverage, timezone, gaps, and terms of use. |
| On-chain valuation | Glassnode metrics such as MVRV, realized price, and Puell Multiple | Valuation and cycle context | Some metrics may require a paid plan; access and redistribution terms vary. |
| Sentiment | Alternative.me Crypto Fear & Greed Index | Sentiment context | Preserve original observation date and source attribution; verify terms before republishing values. |
| Derivatives | Exchange APIs or licensed market-data providers | Funding, open interest, liquidations | Exchange-specific coverage and methodology may not represent the whole market. |
| Spot and exchange flows | A licensed provider or a reproducible public source | Market-structure context | Definitions, wallet labels, revisions, and coverage may change. |

Candidate source documentation:
- Coin Metrics API: https://docs.coinmetrics.io/api/v4/
- Glassnode API documentation: https://docs.glassnode.com/
- Alternative.me Fear & Greed API: https://alternative.me/crypto/fear-and-greed-index/

These links are starting points, not confirmation that all data can be redistributed freely.

## Required data contract

Every observation should contain enough metadata to distinguish when it describes the market from when it became available to the model. Recommended fields:

- Metric
- Asset
- Observation date
- Availability timestamp in UTC
- Retrieval timestamp in UTC
- Value and unit
- Source and source version
- Missing-data flag
- Revision flag
- License or terms reference

For historical simulation, use the value that was actually available at the simulated decision time. If historical availability or revisions cannot be reconstructed, flag the limitation and exclude the feature from claims requiring point-in-time accuracy.

## Data quality rules

1. Never silently forward-fill a missing value for a signal-critical feature.
2. Track source outages, stale observations, changes in units, and schema changes.
3. Validate timestamps and duplicate observations.
4. Preserve raw source snapshots when permitted by applicable terms.
5. Record transformations and normalized outputs separately from raw inputs.
6. Do not publish proprietary data in violation of provider terms.
7. Clearly distinguish observed values, estimates, and unavailable data.

## Third-party indicators are context, not authority

CycleMark's state is determined by its own documented model. Third-party indicators must not be used to manually override a state. Any third-party signal used as a model feature must be declared in the methodology and evaluated for incremental value.

## Initial release policy

Until ingestion and validation are implemented, the application should show an explicit unavailable/not-yet-computed state. Do not substitute fabricated values or illustrative history for live data.
