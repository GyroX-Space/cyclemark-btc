import pytest

from cyclemark.research import build_forward_labels


def test_forward_labels_use_first_observation_on_or_after_calendar_horizon():
    labels = build_forward_labels(
        dates=["2020-01-01", "2020-06-01", "2021-01-01", "2021-06-01"],
        closes=[100.0, 105.0, 130.0, 140.0],
        highs=[102.0, 110.0, 135.0, 145.0],
        lows=[95.0, 90.0, 80.0, 120.0],
        horizons_days=(365,),
    )

    one_year = labels[0]["horizons"]["365"]
    assert one_year["target_calendar_date"] == "2020-12-31"
    assert one_year["target_observation_date"] == "2021-01-01"
    assert one_year["forward_return"] == pytest.approx(0.30)
    assert one_year["max_adverse_excursion_pct"] == pytest.approx(-20.0)
    assert one_year["max_favorable_excursion_pct"] == pytest.approx(35.0)
    assert one_year["adverse_threshold_events"]["adverse_30pct_or_worse"] is False


def test_forward_labels_preserve_rows_with_unobservable_future_targets():
    labels = build_forward_labels(
        dates=["2024-01-01", "2024-06-01"],
        closes=[100.0, 110.0],
        highs=[105.0, 115.0],
        lows=[95.0, 105.0],
        horizons_days=(365,),
    )
    assert len(labels) == 2
    assert labels[0]["horizons"]["365"] is None
    assert labels[1]["horizons"]["365"] is None


def test_forward_labels_reject_non_chronological_dates():
    with pytest.raises(ValueError, match="strictly increasing"):
        build_forward_labels(
            dates=["2024-01-02", "2024-01-01"],
            closes=[100.0, 101.0],
            highs=[102.0, 103.0],
            lows=[98.0, 99.0],
            horizons_days=(1,),
        )


def test_forward_labels_reject_invalid_candles():
    with pytest.raises(ValueError, match="low <= close <= high"):
        build_forward_labels(
            dates=["2024-01-01"],
            closes=[105.0],
            highs=[103.0],
            lows=[99.0],
            horizons_days=(1,),
        )


def test_forward_labels_reject_duplicate_or_nonpositive_horizons():
    base = {
        "dates": ["2024-01-01"],
        "closes": [100.0],
        "highs": [101.0],
        "lows": [99.0],
    }
    with pytest.raises(ValueError, match="unique"):
        build_forward_labels(**base, horizons_days=(365, 365))
    with pytest.raises(ValueError, match="positive integer"):
        build_forward_labels(**base, horizons_days=(0,))
