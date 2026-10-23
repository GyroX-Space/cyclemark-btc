# CycleMark Methodology

**Status:** Research proposal, version 0.1.0. Parameters are provisional and are not presented as validated predictive rules.

## 1. Design goals

CycleMark is designed to answer two distinct questions:

1. Is the market showing evidence consistent with a long-term bottoming process?
2. Does the estimated 12–18 month return/risk profile look attractive relative to alternatives?

These questions must remain separate. A low valuation can coexist with a deteriorating price trend; a recovering trend can coexist with unattractive entry risk.

## 2. Outputs

### Bottom Formation Score (BFS)

BFS is a composite score from 0 to 100. It summarizes evidence relevant to a potential bottoming process. It is not a probability unless a separate probability model is trained and calibrated.

### Buy Opportunity Score (BOS)

BOS is a composite score from 0 to 100 intended to summarize forward return potential against downside risk over 12- and 18-month horizons. A score is not itself a forecast probability. BOS should not be considered production-ready until its forward labels, model, calibration, and walk-forward performance are documented.

### Four market states

The following thresholds are initial engineering defaults only. They must be assessed with chronological out-of-sample testing and may change in a versioned release.

| State | Provisional rule | Color | Meaning |
|---|---|---|---|
| Opportunity | BFS >= 70 and BOS >= 65 | Green | Stronger joint evidence under provisional criteria; not a confirmed bottom. |
| Forming | BFS >= 50 and BOS >= 45 | Blue | Bottoming and opportunity evidence are jointly improving. |
| Risk | BFS < 30 and BOS < 30 | Slate | Evidence remains weak or risk is elevated. |
| Watch | Any other valid score combination | Amber | Conditions warrant monitoring; evidence is mixed or incomplete. |

Rules are evaluated in this order: Opportunity, Forming, Risk, then Watch. Missing scores must not be coerced to zero; missing inputs should produce an explicit insufficient-data result instead of a market state.

## 3. Feature dimensions

The initial conceptual framework has five dimensions:

| Dimension | Initial research weight | Example features |
|---|---:|---|
| Valuation and cost basis | 25% | MVRV Z-Score, price / realized price, Mayer Multiple |
| Capitulation and panic | 20% | Realized-loss percentiles, realized profit/loss dynamics, sentiment extremes |
| Cycle position | 20% | Drawdown from all-time high, time since major cycle events, historical cycle context |
| Trend and price structure | 20% | Price vs. 200-day moving average, 30/90-day momentum, stabilization measures |
| Flows and market structure | 15% | Funding rates, open interest relative to market size, spot/exchange flows |

These weights describe the proposed research design, not empirically proven optimal values. Feature availability and quality must be assessed before implementation.

## 4. Normalization and aggregation

Where appropriate, raw features should be converted to rolling historical percentiles using only data available as of the score timestamp. The direction of each feature must be explicitly defined: a higher raw value can indicate either greater risk or stronger opportunity depending on the feature.

A simple weighted composite is:

    DimensionScore = sum(weight_i * normalized_feature_i) / sum(available_weight_i)

Partial-weight renormalization is allowed only when the configured minimum feature coverage is met. Every score record must include coverage, missing features, input timestamps, and model version.

Normalization windows, feature directions, winsorization, and treatment of regime changes must be specified in code and tests. Any transformation that uses future observations is prohibited.

## 5. BOS research targets

Candidate forward labels include:

- Forward return after 365 calendar days.
- Forward return after 548 calendar days.
- Whether forward return exceeds 50% or 100%.
- Whether price experiences an adverse excursion of at least 30% or 50% after the signal.
- Return distribution and downside-tail measures.

The maximum adverse excursion from an entry is not the same statistic as traditional peak-to-trough maximum drawdown; reports must label these separately.

## 6. State stability

Daily scores can be noisy. A production implementation may use a predeclared persistence or hysteresis rule to reduce repeated state flips. Any such rule must use only information available at the time and must be included in backtests. State transitions must never be manually rewritten to make history look cleaner.

## 7. Daily audit record

Each published daily record should contain at least:

- Date and UTC generation timestamp
- State, BFS, BOS, and model version
- Feature and dimension scores
- Input source identifiers and availability timestamps
- Missing/stale feature flags and coverage
- State-change explanation
- Data revision and computation metadata

The project should preserve each published version rather than silently overwriting a past signal.

## 8. Validation requirements

Before public claims about predictive value, evaluate the framework using chronological train/validation/test splits and rolling walk-forward tests. Account for overlapping 12–18 month labels using purging or embargo methods. Compare against buy-and-hold, simple drawdown rules, and trend-only baselines.

Report performance across cycles, transaction costs, slippage, drawdowns, adverse excursions, tail losses, false signals, calibration, confidence intervals, and the effective number of independent cycle observations. Thousands of daily rows do not imply thousands of independent market cycles.

## 9. Change management

Every material change to features, weights, thresholds, data sources, or state logic requires a model version increment, a changelog entry, and a documented impact assessment. Historical outputs generated by an earlier version must remain identifiable.


## 10. Current prototype implementation

The current daily pipeline publishes a **provisional BFS only**. It uses three available dimensions and preserves their configured weights: capitulation/panic (20%), cycle position (20%), and trend/price structure (20%). The 40% valuation and flow dimensions remain unavailable. The available 60% weight is renormalized for this provisional score and explicitly recorded in the daily JSON output.

Current hand-specified transforms are deliberately simple and are not trained or calibrated:

- Capitulation/panic proxy: 100 minus the Alternative.me Fear & Greed value.
- Cycle-position proxy: the close-to-all-time-high drawdown scaled linearly from 0 to 80% drawdown and clipped to the 0–100 range.
- Trend/price structure: the mean of clipped linear transforms of price relative to the 200-day moving average and 30/90-day momentum, plus a simple comparison of the most recent 30-day low with the prior 30-day low.

These transforms are scaffolding for testing the data pipeline, not claims of statistical validity. The daily record marks BFS as provisional, records missing dimensions and feature values, and leaves BOS and the composite state unavailable. A future model version must replace or justify these transforms through predeclared walk-forward validation before production state labels are enabled.
