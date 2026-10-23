# CycleMark BTC

**BTC Cycle Intelligence — Know the cycle. Track every signal. Verify the history.**

CycleMark is an open-source research project for assessing Bitcoin's long-term market regime through a transparent, versioned framework. Core scores are computed by CycleMark from public raw market data wherever practical. Third-party calculated indicators are kept separate as optional context.

> **Research status:** Early-stage research foundation. The pipeline publishes public market context and a provisional BFS based only on price-derived features, with 40% configured-weight coverage. BFS is not validated; BOS and composite state are withheld. No historical signals are fabricated.

## Product goals

- Four daily market states: Risk, Watch, Forming, and Opportunity.
- Two complementary scores: Bottom Formation Score (BFS) and Buy Opportunity Score (BOS).
- A public state calendar with versioned daily records and explanations for state changes.
- Transparent methodology, data provenance, and missing-data handling.
- Clearly separated raw market inputs and third-party reference indicators.
- Reproducible walk-forward evaluation with transaction costs and documented failure cases.

## Current implementation

- Public BTC spot candle ingestion from the Binance market-data API.
- Price-only provisional BFS features: drawdown from observed all-time high, price vs. 200-day average, momentum, and price-low stabilization.
- Alternative.me Crypto Fear & Greed ingestion for auxiliary display only; it does not enter BFS.
- Daily market-context archive, JSON output, and a clearly labeled historical research backfill.
- Responsive English-language dashboard and historical calendar.
- Provisional scoring primitives and chronological backtesting utilities with tests.
- AWS Linux daily runner and deployment documentation.
- GitHub Actions test workflow and static-site deployment workflow.

The current data pipeline does not yet implement the complete raw-data-derived on-chain and derivatives feature set or a validated forward-return BOS model. BFS is a clearly marked heuristic research score, not a calibrated probability. The dashboard withholds BOS and composite state until the required model and validation work is complete.

## Data governance principle

**Core CycleMark calculations use public raw market observations wherever practical. Third-party calculated indicators are auxiliary context, not core scoring inputs.** Examples such as Fear & Greed, third-party MVRV, and third-party Mayer Multiple may be displayed with attribution, timestamps, and definitions, but must not influence BFS, BOS, or state assignment by default. Any exception requires explicit methodology documentation, a versioned change, and separate validation. If raw inputs needed for a feature are unavailable, mark the feature missing rather than silently substituting a third-party score.

Public availability alone does not make a metric raw data. Exchange OHLCV is a market observation; a sentiment index or provider-computed valuation ratio is a derived indicator.

## Four-state research framework

| State | Color | Interpretation |
|---|---|---|
| Risk | Slate | Evidence is insufficient or risk conditions remain elevated. |
| Watch | Amber | Some conditions warrant attention, but evidence is incomplete. |
| Forming | Blue | Multiple features are consistent with a potential bottoming process; a new low remains possible. |
| Opportunity | Green | Bottoming evidence and risk/reward criteria jointly meet validated rules; never a guarantee of a market bottom. |

These are product concepts, not currently active validated signals. State thresholds must be evaluated out of sample before production use.

## Scores

- **BFS — Bottom Formation Score (0–100):** Intended to summarize valuation, capitulation, cycle position, price structure, and market-structure evidence. Current prototype uses only price-derived cycle and trend features.
- **BOS — Buy Opportunity Score (0–100):** Intended to summarize the estimated forward return distribution relative to downside risk over 12- and 18-month horizons.

A score is not a probability unless a separate probability model is trained and calibrated.

## Documentation

- [Methodology](docs/methodology.md)
- [Data sources and governance](docs/data-sources.md)
- [Backtesting protocol](docs/backtesting.md)
- [AWS Linux daily deployment](docs/aws-deployment.md)
- [Static dashboard hosting](docs/site-hosting.md)

## Development

Python 3.11 or later is recommended.

    python -m pip install -e ".[dev]"
    pytest
    python scripts/backfill_history.py
    python scripts/run_daily.py

The daily script makes outbound HTTPS requests to public data APIs. Review provider terms and source availability before relying on it operationally.

## Public data and operational safety

1. Prefer public raw market observations for core calculations; isolate third-party derived indicators as context.
2. No look-ahead bias.
3. No fabricated or silently backfilled signals.
4. Every published state must be reproducible from versioned inputs and code.
5. Missing or stale inputs must be visible.
6. Historical records must preserve what was knowable at publication time.
7. Never commit credentials or redistribute data in violation of provider terms.
8. Performance claims require reproducible experiments, uncertainty estimates, and relevant costs.

## Disclaimer

CycleMark is an educational and research project, not investment advice, a recommendation to buy or sell, or a promise of future performance. Bitcoin is volatile and may result in substantial or total loss.

## License

Licensed under the MIT License. See [LICENSE](LICENSE).
