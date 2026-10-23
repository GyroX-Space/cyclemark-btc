"""CycleMark BTC research framework."""

from .scoring import (
    Dimension,
    InsufficientDataError,
    MarketState,
    classify_state,
    weighted_score,
)

__all__ = [
    "Dimension",
    "InsufficientDataError",
    "MarketState",
    "classify_state",
    "weighted_score",
]

__version__ = "0.1.0"
