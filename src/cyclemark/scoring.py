"""Transparent scoring primitives for the CycleMark research prototype.

These rules are provisional engineering defaults, not validated trading signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Mapping


class InsufficientDataError(ValueError):
    """Raised when a score cannot be computed with adequate data coverage."""


class MarketState(str, Enum):
    RISK = "risk"
    WATCH = "watch"
    FORMING = "forming"
    OPPORTUNITY = "opportunity"


@dataclass(frozen=True)
class Dimension:
    """A named composite dimension and its configured weight."""

    name: str
    weight: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Dimension name must not be empty.")
        if not isfinite(self.weight) or self.weight <= 0:
            raise ValueError("Dimension weight must be finite and greater than zero.")


def weighted_score(
    scores: Mapping[str, float | None],
    dimensions: Mapping[str, Dimension],
    *,
    minimum_coverage: float = 1.0,
) -> float:
    """Compute a weighted score from normalized 0–100 dimension scores.

    Missing dimensions are excluded only if the configured coverage requirement
    is met. The default requires complete coverage. Missing values are never
    silently interpreted as zero.
    """
    if not 0 < minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be in the interval (0, 1].")
    if not dimensions:
        raise InsufficientDataError("No dimensions are configured.")

    total_weight = sum(d.weight for d in dimensions.values())
    weighted_sum = 0.0
    available_weight = 0.0

    for key, dimension in dimensions.items():
        value = scores.get(key)
        if value is None:
            continue
        if not isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f"Score for {key!r} must be finite and within [0, 100].")
        weighted_sum += value * dimension.weight
        available_weight += dimension.weight

    coverage = available_weight / total_weight
    if available_weight == 0 or coverage < minimum_coverage:
        raise InsufficientDataError(
            f"Insufficient score coverage: {coverage:.1%}; "
            f"minimum required is {minimum_coverage:.1%}."
        )

    return round(weighted_sum / available_weight, 2)


def classify_state(bfs: float | None, bos: float | None) -> MarketState:
    """Map BFS and BOS to one of four provisional states.

    Evaluation priority: Opportunity, Forming, Risk, then Watch.
    Missing scores raise an explicit error rather than fabricating a state.
    """
    for name, value in (("BFS", bfs), ("BOS", bos)):
        if value is None:
            raise InsufficientDataError(f"{name} is unavailable; state cannot be classified.")
        if not isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be finite and within [0, 100].")

    assert bfs is not None and bos is not None

    if bfs >= 70 and bos >= 65:
        return MarketState.OPPORTUNITY
    if bfs >= 50 and bos >= 45:
        return MarketState.FORMING
    if bfs < 30 and bos < 30:
        return MarketState.RISK
    return MarketState.WATCH
