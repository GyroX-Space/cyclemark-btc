# Backtesting Protocol

**Status:** Protocol specification. No performance results are claimed in this document.

## Objective

Determine whether CycleMark's daily outputs provide robust, incremental information about Bitcoin's forward return and downside-risk distribution. A visually compelling historical fit is not sufficient evidence.

## Baselines

At minimum, compare with:

1. Buy-and-hold BTC over the same evaluation interval.
2. A simple drawdown-based rule with predeclared thresholds.
3. A trend-only rule using a long-term moving average or momentum.
4. A naive unconditional historical distribution for the same horizon.

Use identical price sources, evaluation dates, and cost assumptions wherever possible.

## Labels and horizons

For signal date t:

- 12-month forward return: close at t + 365 calendar days divided by close at t, minus 1.
- 18-month forward return: close at t + 548 calendar days divided by close at t, minus 1.
- Adverse excursion: the minimum future price relative to the entry price over a predeclared horizon.

Define the price series, missing-day policy, horizon convention, and whether returns use close-to-close observations before running the evaluation. Do not label a signal using a future low and then imply the model knew that low at signal time.

## Chronological evaluation

- Split data by time, never randomly.
- Reserve a final untouched test interval.
- Use rolling walk-forward evaluation for model and threshold selection.
- Apply purging or embargo around overlapping 12- and 18-month labels.
- Fit normalizers, feature selection, calibration, and thresholds only on training data for each fold.
- Report the number of independent market-cycle observations; overlapping daily labels are not independent samples.

## Metrics

Report at least:

- Forward return distribution and median/quantiles.
- Probability and frequency of returns exceeding predeclared thresholds, if estimable.
- Frequency and magnitude of adverse excursions.
- Maximum drawdown for any simulated portfolio strategy.
- Tail-loss measures and time under water.
- Signal precision/recall or event-based metrics with explicit event definitions.
- State duration, transition count, and state-flip frequency.
- Calibration plots and proper scoring rules if probability forecasts are produced.
- Confidence intervals and sensitivity to assumptions.

## Trading simulation

If a strategy is simulated, specify execution delay, entry/exit timing, fees, spread, slippage, turnover, cash treatment, and position sizing. Do not assume execution at a price that was unavailable after the signal was generated.

A state index is not automatically a profitable trading strategy. Keep predictive evaluation and portfolio backtesting separate.

## Robustness checks

- Evaluate across distinct market regimes and cycles.
- Test reasonable variations in features and thresholds.
- Compare with simpler baselines.
- Include failed and false signals.
- Audit data revisions and point-in-time availability.
- Check for survivorship bias, data leakage, and selection bias.

## Publication rule

Do not publish claims such as "predicts bottoms," "X% accurate," or "beats buy-and-hold" without a reproducible experiment, a clearly defined sample, costs where relevant, uncertainty estimates, and links to code and data provenance.
