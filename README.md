# CycleMark BTC

**BTC Cycle Intelligence — Know the cycle. Track every signal. Verify the history.**

CycleMark is an open research project for assessing Bitcoin's long-term market regime through a transparent, versioned framework. It combines a composite model with third-party context and a public daily history of its states.

> **Research status:** Early-stage research foundation. Scores, weights, thresholds, and state rules are provisional and have not been validated as predictive. This initial release publishes neither live scores nor verified historical signals.

## What CycleMark aims to provide

- **Four daily market states:** Risk, Watch, Forming, and Opportunity.
- **Two complementary scores:** Bottom Formation Score (BFS) and Buy Opportunity Score (BOS).
- **A public state calendar:** One versioned record per date, with explanations for state changes.
- **Transparent methodology:** Feature definitions, weighting, data provenance, and missing-data handling.
- **Third-party context:** Sentiment, on-chain valuation, and market-structure indicators.
- **Reproducible evaluation:** Walk-forward testing, explicit transaction-cost assumptions, and documented failure cases.

## Four-state model

| State | Color | Interpretation |
|---|---|---|
| **Risk** | Slate | Evidence is insufficient or risk conditions remain elevated. |
| **Watch** | Amber | Some conditions warrant attention, but evidence is incomplete. |
| **Forming** | Blue | Multiple features are consistent with a potential bottoming process; a new low remains possible. |
| **Opportunity** | Green | Bottoming evidence and the risk/reward assessment jointly meet provisional criteria. This is not confirmation of a market bottom. |

State colors are a compact summary, not a probability forecast or an instruction to trade. Provisional thresholds must be evaluated out of sample before being treated as validated.

## Scores

- **BFS — Bottom Formation Score (0–100):** Summarizes valuation, capitulation, cycle position, price structure, and market-structure evidence relevant to bottom formation.
- **BOS — Buy Opportunity Score (0–100):** Intended to summarize the estimated forward return distribution relative to downside risk over 12- and 18-month horizons.

A score of 70 does **not** mean a 70% probability. Probability claims require separately trained and calibrated models.

## Project status

This repository starts with a research specification and a small, testable scoring foundation. It intentionally contains no fabricated current readings, invented historical states, or unverified backtest claims.

- [Methodology](docs/methodology.md)
- [Data sources and governance](docs/data-sources.md)
- [Backtesting protocol](docs/backtesting.md)

## Development

Python 3.11 or later is recommended. Install the package and development dependencies with:

    python -m pip install -e ".[dev]"

Run tests with:

    pytest

## Principles

1. No look-ahead bias.
2. No fabricated or silently backfilled signals.
3. Every published state must be reproducible from versioned inputs and code.
4. Missing or stale inputs must be visible.
5. Historical records must preserve what was knowable at the time.
6. Research performance must include drawdowns, adverse excursions, costs, and uncertainty—not only headline returns.

## Disclaimer

CycleMark is an educational and research project, not investment advice, a recommendation to buy or sell, or a promise of future performance. Bitcoin is volatile and may result in substantial or total loss. Users are responsible for their own decisions.

## License

A license will be selected before the first stable release. Until then, do not assume that a particular open-source license applies.
