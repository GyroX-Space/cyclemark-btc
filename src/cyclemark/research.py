"""Research-only forward outcome labels for chronological evaluation.

These labels intentionally use future observations and must never be supplied as
features to a live scoring pipeline. Dates are UTC calendar dates in ISO format.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, timedelta
from math import isfinite
from typing import Sequence


def _parse_dates(dates: Sequence[str]) -> list[date]:
    parsed: list[date] = []
    for value in dates:
        if not isinstance(value, str):
            raise ValueError("Dates must be ISO-8601 YYYY-MM-DD strings.")
        try:
            item = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO calendar date: {value!r}") from exc
        if item.isoformat() != value:
            raise ValueError(f"Dates must use canonical YYYY-MM-DD format: {value!r}")
        parsed.append(item)
    if any(right <= left for left, right in zip(parsed, parsed[1:])):
        raise ValueError("Dates must be strictly increasing and unique.")
    return parsed


def build_forward_labels(
    *,
    dates: Sequence[str],
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    horizons_days: Sequence[int] = (365, 548),
    adverse_thresholds: Sequence[float] = (0.30, 0.50),
) -> list[dict]:
    """Build calendar-horizon outcomes for research; never use as live features.

    For each signal date and horizon, the target close is the first observed
    close on or after signal_date + horizon_days. Excursion statistics use
    bars strictly after the signal date and through that target observation.
    Missing future labels are represented by None rather than dropped rows.

    max_adverse_excursion_pct is the minimum future low relative to the
    signal-date close, expressed as a percentage return (normally <= 0).
    max_favorable_excursion_pct is the maximum future high on the same basis.
    These are entry-relative excursions, not peak-to-trough portfolio drawdown.
    """
    parsed_dates = _parse_dates(dates)
    count = len(parsed_dates)
    if not (len(closes) == len(highs) == len(lows) == count):
        raise ValueError("Dates, closes, highs, and lows must have equal lengths.")
    if not count:
        raise ValueError("At least one observation is required.")
    if not horizons_days:
        raise ValueError("At least one horizon is required.")
    if any(not isinstance(h, int) or isinstance(h, bool) or h <= 0 for h in horizons_days):
        raise ValueError("Horizon values must be positive integer calendar days.")
    if len(set(horizons_days)) != len(horizons_days):
        raise ValueError("Horizon values must be unique.")
    if any(not isfinite(float(v)) or float(v) <= 0 for values in (closes, highs, lows) for v in values):
        raise ValueError("OHLC price values must be finite and greater than zero.")
    if any(float(low) > float(high) or not float(low) <= float(close) <= float(high)
           for close, high, low in zip(closes, highs, lows)):
        raise ValueError("Each candle must satisfy low <= close <= high.")
    if not adverse_thresholds:
        raise ValueError("At least one adverse threshold is required.")
    if any(not isfinite(float(t)) or not 0 < float(t) < 1 for t in adverse_thresholds):
        raise ValueError("Adverse thresholds must be finite fractions between zero and one.")
    if len(set(adverse_thresholds)) != len(adverse_thresholds):
        raise ValueError("Adverse thresholds must be unique.")

    results: list[dict] = []
    for i, signal_date in enumerate(parsed_dates):
        horizon_labels: dict[str, dict | None] = {}
        for horizon in horizons_days:
            target_date = signal_date + timedelta(days=horizon)
            candidate = bisect_left(parsed_dates, target_date, lo=i + 1)
            target_index = candidate if candidate < count else None
            if target_index is None:
                horizon_labels[str(horizon)] = None
                continue

            entry = float(closes[i])
            future_lows = [float(v) for v in lows[i + 1 : target_index + 1]]
            future_highs = [float(v) for v in highs[i + 1 : target_index + 1]]
            adverse = min(future_lows) / entry - 1.0
            favorable = max(future_highs) / entry - 1.0
            forward_return = float(closes[target_index]) / entry - 1.0
            threshold_flags = {
                f"adverse_{int(round(threshold * 100))}pct_or_worse": adverse <= -threshold
                for threshold in adverse_thresholds
            }
            horizon_labels[str(horizon)] = {
                "target_calendar_date": target_date.isoformat(),
                "target_observation_date": parsed_dates[target_index].isoformat(),
                "forward_return": round(forward_return, 8),
                "max_adverse_excursion_pct": round(adverse * 100.0, 8),
                "max_favorable_excursion_pct": round(favorable * 100.0, 8),
                "adverse_threshold_events": threshold_flags,
                "label_window_observation_count": target_index - i,
            }
        results.append({
            "signal_date": signal_date.isoformat(),
            "labels_are_research_only": True,
            "horizons": horizon_labels,
        })
    return results
