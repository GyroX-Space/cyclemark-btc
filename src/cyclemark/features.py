"""Provisional price-only feature scoring for research inspection.

Third-party calculated indicators are not core scoring inputs. These
hand-specified transforms are engineering scaffolding, not calibrated predictors.
"""
from __future__ import annotations

from math import isfinite


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def compute_provisional_bfs(
    *,
    closes: list[float],
    highs: list[float],
    lows: list[float],
) -> dict:
    """Calculate provisional BFS from price-derived features only.

    Valuation, capitulation, and flow dimensions are unavailable. Third-party
    sentiment or valuation indicators must not be passed into this function.
    """
    if len(closes) < 200 or len(highs) < 200 or len(lows) < 200:
        raise ValueError("At least 200 daily observations are required.")
    if any(not isfinite(x) or x <= 0 for x in closes + highs + lows):
        raise ValueError("Price observations must be finite and greater than zero.")

    latest = closes[-1]
    sma_200 = sum(closes[-200:]) / 200
    all_time_high = max(highs)
    drawdown_ath = (latest / all_time_high - 1.0) * 100.0
    momentum_30 = (latest / closes[-31] - 1.0) * 100.0
    momentum_90 = (latest / closes[-91] - 1.0) * 100.0
    price_vs_sma = (latest / sma_200 - 1.0) * 100.0

    cycle_score = clamp((-drawdown_ath) / 80.0 * 100.0)
    sma_score = clamp(50.0 + price_vs_sma * 2.0)
    momentum_30_score = clamp(50.0 + momentum_30 * 1.5)
    momentum_90_score = clamp(50.0 + momentum_90)
    recent_low = min(lows[-30:])
    prior_low = min(lows[-60:-30])
    stabilization_score = 75.0 if recent_low >= prior_low else 25.0
    trend_score = (
        sma_score + momentum_30_score + momentum_90_score + stabilization_score
    ) / 4.0

    # Only cycle-position and trend dimensions are currently available (40%).
    available_weight = 0.20 + 0.20
    bfs = (cycle_score * 0.20 + trend_score * 0.20) / available_weight

    return {
        "bfs": round(bfs, 2),
        "bfs_status": "provisional_unvalidated",
        "available_weight": available_weight,
        "configured_weight_coverage_pct": round(available_weight * 100, 1),
        "dimension_scores": {
            "valuation_cost_basis": None,
            "capitulation_panic": None,
            "cycle_position": round(cycle_score, 2),
            "trend_price_structure": round(trend_score, 2),
            "flows_market_structure": None,
        },
        "feature_values": {
            "drawdown_from_all_time_high_pct": round(drawdown_ath, 2),
            "price_vs_sma_200_pct": round(price_vs_sma, 2),
            "momentum_30d_pct": round(momentum_30, 2),
            "momentum_90d_pct": round(momentum_90, 2),
            "recent_30d_low_usd": round(recent_low, 2),
            "prior_30d_low_usd": round(prior_low, 2),
        },
        "limitations": [
            "Valuation, capitulation, and flows dimensions are unavailable in core scoring.",
            "Third-party calculated indicators are auxiliary context only and are excluded from BFS.",
            "Feature transforms are hand-specified and not calibrated.",
            "BOS and the composite market state remain unavailable.",
        ],
    }
