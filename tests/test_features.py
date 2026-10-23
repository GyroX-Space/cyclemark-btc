import pytest

from cyclemark.features import compute_provisional_bfs


def sample_prices():
    closes = [100.0 + i * 0.5 for i in range(220)]
    highs = [price * 1.02 for price in closes]
    lows = [price * 0.98 for price in closes]
    return closes, highs, lows


def test_provisional_bfs_reports_partial_coverage():
    closes, highs, lows = sample_prices()
    result = compute_provisional_bfs(
        closes=closes, highs=highs, lows=lows, fear_greed_value=25
    )
    assert 0 <= result["bfs"] <= 100
    assert result["bfs_status"] == "provisional_unvalidated"
    assert result["configured_weight_coverage_pct"] == 60.0
    assert result["dimension_scores"]["valuation_cost_basis"] is None
    assert result["dimension_scores"]["flows_market_structure"] is None


def test_provisional_bfs_rejects_short_history():
    with pytest.raises(ValueError):
        compute_provisional_bfs(
            closes=[100.0] * 199,
            highs=[101.0] * 199,
            lows=[99.0] * 199,
            fear_greed_value=50,
        )


def test_provisional_bfs_rejects_invalid_sentiment():
    closes, highs, lows = sample_prices()
    with pytest.raises(ValueError):
        compute_provisional_bfs(
            closes=closes, highs=highs, lows=lows, fear_greed_value=101
        )
