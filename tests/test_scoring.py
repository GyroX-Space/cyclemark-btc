import pytest

from cyclemark.scoring import (
    Dimension,
    InsufficientDataError,
    MarketState,
    classify_state,
    weighted_score,
)


def test_weighted_score_uses_configured_weights():
    dimensions = {
        "valuation": Dimension("Valuation", 0.25),
        "trend": Dimension("Trend", 0.75),
    }
    assert weighted_score({"valuation": 80, "trend": 40}, dimensions) == 50.0


def test_weighted_score_rejects_missing_data_by_default():
    dimensions = {
        "valuation": Dimension("Valuation", 0.5),
        "trend": Dimension("Trend", 0.5),
    }
    with pytest.raises(InsufficientDataError):
        weighted_score({"valuation": 80, "trend": None}, dimensions)


def test_weighted_score_can_use_explicit_coverage_threshold():
    dimensions = {
        "valuation": Dimension("Valuation", 0.5),
        "trend": Dimension("Trend", 0.5),
    }
    assert weighted_score(
        {"valuation": 80, "trend": None},
        dimensions,
        minimum_coverage=0.5,
    ) == 80.0


@pytest.mark.parametrize(
    ("bfs", "bos", "expected"),
    [
        (75, 70, MarketState.OPPORTUNITY),
        (55, 50, MarketState.FORMING),
        (20, 25, MarketState.RISK),
        (45, 80, MarketState.WATCH),
    ],
)
def test_classify_state(bfs, bos, expected):
    assert classify_state(bfs, bos) is expected


@pytest.mark.parametrize("value", [-1, 101, float("nan"), float("inf")])
def test_classify_state_rejects_invalid_scores(value):
    with pytest.raises(ValueError):
        classify_state(value, 50)


def test_classify_state_refuses_missing_scores():
    with pytest.raises(InsufficientDataError):
        classify_state(None, 50)
