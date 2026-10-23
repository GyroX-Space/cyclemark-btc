import pytest

from cyclemark.backtest import forward_return, summarize_forward_returns, walk_forward_folds


def test_forward_return_returns_none_when_future_label_is_missing():
    assert forward_return([100.0, 110.0, 120.0], 1, 2) is None


def test_forward_return_calculates_simple_return():
    assert forward_return([100.0, 120.0, 150.0], 0, 2) == pytest.approx(0.5)


def test_walk_forward_folds_are_chronological_with_embargo():
    folds = walk_forward_folds(
        30, minimum_train_size=10, test_size=5, embargo=3
    )
    assert folds
    for fold in folds:
        assert max(fold.train_indices) < min(fold.test_indices)
        assert min(fold.test_indices) - max(fold.train_indices) >= 4


def test_walk_forward_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        walk_forward_folds(100, minimum_train_size=0, test_size=10, embargo=1)


def test_return_summary_is_explicit_about_overlapping_samples():
    result = summarize_forward_returns([0.6, -0.1, 0.2])
    assert result["sample_count"] == 3
    assert result["return_over_50pct_rate"] == pytest.approx(1 / 3)
    assert "not independent" in result["warning"]
