from datetime import datetime, timezone

import pytest

from cyclemark.sources import DataSourceError, fetch_fear_greed


def test_fear_greed_rejects_out_of_range_value(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(
        sources,
        "_get_json",
        lambda url: {"data": [{"value": "101", "timestamp": "1700000000", "value_classification": "Extreme Greed"}]},
    )
    with pytest.raises(DataSourceError):
        fetch_fear_greed()


def test_fear_greed_normalizes_timestamp(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(
        sources,
        "_get_json",
        lambda url: {"data": [{"value": "12", "timestamp": "1700000000", "value_classification": "Extreme Fear"}]},
    )
    result = fetch_fear_greed()
    assert result["value"] == 12
    assert result["classification"] == "Extreme Fear"
    assert result["observation_timestamp_utc"].endswith("Z")
    assert result["source"] == "alternative_me_fear_greed_api"


def test_fear_greed_history_sorts_observations(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(
        sources,
        "_get_json",
        lambda url: {"data": [
            {"value": "40", "timestamp": "1700086400", "value_classification": "Fear"},
            {"value": "20", "timestamp": "1700000000", "value_classification": "Extreme Fear"},
        ]},
    )
    result = sources.fetch_fear_greed_history()
    assert [item["value"] for item in result] == [20, 40]


def test_binance_candle_adapter_returns_validated_public_ohlcv(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(
        sources,
        "_get_json",
        lambda url: [[0, "100", "110", "90", "105", "2", 86399999]],
    )
    result = sources.fetch_binance_daily_klines()
    assert len(result) == 1
    assert result[0]["open"] == 100
    assert result[0]["high"] == 110
    assert result[0]["low"] == 90
    assert result[0]["close"] == 105
    assert result[0]["volume"] == 2


def test_binance_candle_adapter_rejects_invalid_ohlcv(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(
        sources,
        "_get_json",
        lambda url: [[0, "120", "110", "90", "105", "2", 86399999]],
    )
    with pytest.raises(DataSourceError, match="bounds"):
        sources.fetch_binance_daily_klines()
