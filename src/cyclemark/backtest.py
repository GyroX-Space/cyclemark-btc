"""Small, dependency-free utilities for leakage-aware research evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class WalkForwardFold:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


def forward_return(prices: Sequence[float], index: int, horizon: int) -> float | None:
    """Return a future simple return, or None when the label is not observable."""
    if horizon <= 0:
        raise ValueError("horizon must be a positive integer.")
    if index < 0 or index >= len(prices):
        raise IndexError("index is outside the price series.")
    if index + horizon >= len(prices):
        return None
    start, end = prices[index], prices[index + horizon]
    if not isfinite(start) or not isfinite(end) or start <= 0 or end <= 0:
        raise ValueError("Prices must be finite and greater than zero.")
    return end / start - 1.0


def walk_forward_folds(
    sample_count: int,
    *,
    minimum_train_size: int,
    test_size: int,
    embargo: int,
) -> list[WalkForwardFold]:
    """Create expanding-window chronological folds with an embargo gap.

    The caller should set embargo to at least the maximum overlapping label
    horizon in observations. No random shuffling is performed.
    """
    if sample_count < 0 or minimum_train_size <= 0 or test_size <= 0 or embargo < 0:
        raise ValueError("Invalid walk-forward split parameters.")
    folds = []
    test_start = minimum_train_size + embargo
    while test_start < sample_count:
        train_end = test_start - embargo
        test_end = min(test_start + test_size, sample_count)
        if train_end < minimum_train_size:
            break
        folds.append(WalkForwardFold(
            train_indices=tuple(range(train_end)),
            test_indices=tuple(range(test_start, test_end)),
        ))
        test_start = test_end
    return folds


def summarize_forward_returns(returns: Sequence[float]) -> dict:
    """Summarize a sample without implying observations are independent."""
    clean = [float(value) for value in returns if isfinite(float(value))]
    if not clean:
        return {"sample_count": 0, "mean_return": None, "median_return": None,
                "positive_return_rate": None, "return_over_50pct_rate": None}
    ordered = sorted(clean)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "sample_count": len(clean),
        "mean_return": sum(clean) / len(clean),
        "median_return": median,
        "positive_return_rate": sum(value > 0 for value in clean) / len(clean),
        "return_over_50pct_rate": sum(value > 0.5 for value in clean) / len(clean),
        "warning": "Overlapping daily forward returns are not independent observations.",
    }
