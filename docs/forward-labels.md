# Forward Outcome Labels

**Status:** Research utility only. These outputs are targets for historical evaluation, not live features or published forecasts.

## Purpose

The research module constructs forward outcome labels from daily OHLC observations while preserving rows whose future outcomes are not yet observable. It supports the proposed 365- and 548-calendar-day horizons and adverse-excursion analysis.

## Label conventions

For a signal date (t) and horizon (h):

1. The target calendar date is (t+h) calendar days.
2. The target observation is the first available daily candle on or after that calendar date.
3. Forward return is target close divided by signal-date close, minus one.
4. Maximum adverse excursion is the minimum low strictly after the signal date through the target observation, divided by the signal-date close, minus one.
5. Maximum favorable excursion is the maximum high over the same future window, divided by the signal-date close, minus one.
6. Adverse-threshold flags identify whether the entry-relative adverse excursion reaches a predeclared loss threshold.

Excursion percentages are entry-relative statistics. They are not traditional peak-to-trough portfolio maximum drawdown and must not be described as such.

## Missing data and validation

- Dates must be canonical ISO calendar dates in strictly increasing order.
- Dates, closes, highs, and lows must have matching lengths.
- Prices must be finite, positive, and satisfy low <= close <= high.
- Horizons must be positive integer calendar-day counts.
- If the target observation has not yet occurred, the horizon label is null. Rows are not silently dropped.
- The target observation date is recorded because gaps in the source series can move the realized target beyond the nominal calendar date.

The current implementation uses the first available observation on or after the target date. This convention must remain fixed across model comparisons, or any change must be versioned and documented.

## Leakage boundary

Forward labels necessarily use future prices. They must be stored and consumed only in research/evaluation code. They must never be passed into live feature construction, normalization, threshold selection at the signal timestamp, or the daily BFS/BOS calculation.

For 365- and 548-day labels, daily samples overlap heavily. Walk-forward evaluation must use a purging/embargo design aligned to the longest label horizon, and reports must not treat every daily row as an independent market-cycle observation.

## Current limitations

This module does not fit a model, select thresholds, estimate calibrated probabilities, simulate a portfolio, or establish predictive value. It is a reproducible label-construction primitive for later walk-forward evaluation. Any performance claim requires a complete evaluation against predeclared baselines, uncertainty estimates, and realistic execution assumptions.
