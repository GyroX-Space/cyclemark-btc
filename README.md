# CycleMark BTC

**BTC Cycle Intelligence — Know the cycle. Track every signal. Verify the history.**

CycleMark is an open-source research project for assessing Bitcoin's long-term market regime through a transparent, versioned framework. It combines a composite model with third-party context and a public daily history of its states.

> **Research status:** Early-stage research foundation. The pipeline publishes public market context and a provisional BFS with 60% configured-weight coverage. BFS is not validated; BOS and composite state are withheld. No historical signals are fabricated.

## Product goals

- Four daily market states: Risk, Watch, Forming, and Opportunity.
- Two complementary scores: Bottom Formation Score (BFS) and Buy Opportunity Score (BOS).
- A public state calendar with versioned daily records and explanations for state changes.
- Transparent methodology, data provenance, and missing-data handling.
- Third-party sentiment, on-chain valuation, and market-structure context.
- Reproducible walk-forward evaluation with transaction costs and documented failure cases.

## Current implementation

- Public BTC spot candle ingestion from the Binance market-data API.
- Crypto Fear & Greed ingestion from Alternative.me.
- Daily market-context archive, provisional BFS calculation, and JSON output.
- Responsive English-language dashboard and historical calendar.
- Provisional scoring primitives and chronological backtesting utilities with tests.
- AWS Linux daily runner and deployment documentation.
- GitHub Actions test workflow and static-site deployment workflow.

The current data pipeline does **not** yet implement the complete on-chain and derivatives feature set or a validated forward-return BOS model. BFS is a clearly marked heuristic research score, not a calibrated probability. The dashboard withholds BOS and composite state until the required model and validation work is complete.

## Four-state research framework

| State | Color | Interpretation |
|---|---|---|
| Risk | Slate | Evidence is insufficient or risk conditions remain elevated. |
| Watch | Amber | Some conditions warrant attention, but evidence is incomplete. |
| Forming | Blue | Multiple features are consistent with a potential bottoming process; a new low remains possible. |
| Opportunity | Green | Bottoming evidence and risk/reward criteria jointly meet validated rules; never a guarantee of a market bottom. |

These are product concepts, not currently active validated signals. State thresholds must be evaluated out of sample before production use.

## Scores

- **BFS — Bottom Formation Score (0–100):** Summarizes valuation, capitulation, cycle position, price structure, and market-structure evidence.
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
    python scripts/run_daily.py

The daily script makes outbound HTTPS requests to public data APIs. Review provider terms and source availability before relying on it operationally.

## Public data and operational safety

1. No look-ahead bias.
2. No fabricated or silently backfilled signals.
3. Every published state must be reproducible from versioned inputs and code.
4. Missing or stale inputs must be visible.
5. Historical records must preserve what was knowable at publication time.
6. Never commit credentials or redistribute data in violation of provider terms.
7. Performance claims require reproducible experiments, uncertainty estimates, and relevant costs.

## Disclaimer

CycleMark is an educational and research project, not investment advice, a recommendation to buy or sell, or a promise of future performance. Bitcoin is volatile and may result in substantial or total loss.

## License

Licensed under the MIT License. See [LICENSE](LICENSE).
