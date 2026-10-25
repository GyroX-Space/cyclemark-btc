import pytest

from cyclemark.features import compute_provisional_bfs


def sample_prices():
    closes = [100.0 + i * 0.5 for i in range(220)]
    highs = [price * 1.02 for price in closes]
    lows = [price * 0.98 for price in closes]
    return closes, highs, lows


def test_provisional_bfs_uses_only_price_features_and_reports_coverage():
    closes, highs, lows = sample_prices()
    result = compute_provisional_bfs(closes=closes, highs=highs, lows=lows)
    assert 0 <= result["bfs"] <= 100
    assert result["bfs_status"] == "provisional_unvalidated"
    assert result["configured_weight_coverage_pct"] == 40.0
    assert result["dimension_scores"]["valuation_cost_basis"] is None
    assert result["dimension_scores"]["capitulation_panic"] is None
    assert result["dimension_scores"]["flows_market_structure"] is None
    assert "fear_greed_value" not in result["feature_values"]


def test_provisional_bfs_rejects_short_history():
    with pytest.raises(ValueError):
        compute_provisional_bfs(
            closes=[100.0] * 199,
            highs=[101.0] * 199,
            lows=[99.0] * 199,
        )


def test_provisional_bfs_rejects_non_positive_prices():
    closes, highs, lows = sample_prices()
    closes[-1] = 0
    with pytest.raises(ValueError):
        compute_provisional_bfs(closes=closes, highs=highs, lows=lows)


def test_provisional_bfs_rejects_misaligned_price_arrays():
    closes, highs, lows = sample_prices()
    with pytest.raises(ValueError, match="equal lengths"):
        compute_provisional_bfs(closes=closes, highs=highs[:-1], lows=lows)


def test_provisional_bfs_rejects_inconsistent_candles():
    closes, highs, lows = sample_prices()
    highs[-1] = closes[-1] - 1
    with pytest.raises(ValueError, match="low <= close <= high"):
        compute_provisional_bfs(closes=closes, highs=highs, lows=lows)
