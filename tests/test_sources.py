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
