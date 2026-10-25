from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from cyclemark.sources import DataSourceError, fetch_fear_greed


class _Response:
    status = 200

    def __init__(self, payload: bytes = b'{"ok": true}'):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_get_json_retries_transient_errors_then_succeeds(monkeypatch):
    import cyclemark.sources as sources

    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError("temporary failure")
        return _Response()

    monkeypatch.setattr(sources, "urlopen", fake_urlopen)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert sources._get_json("https://example.invalid") == {"ok": True}
    assert calls["count"] == 2
    assert sleeps == [1.0]


def test_get_json_honors_bounded_retry_after(monkeypatch):
    import cyclemark.sources as sources

    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            headers = Message()
            headers["Retry-After"] = "7"
            raise HTTPError("https://example.invalid", 429, "rate limited", headers, None)
        return _Response()

    monkeypatch.setattr(sources, "urlopen", fake_urlopen)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert sources._get_json("https://example.invalid") == {"ok": True}
    assert sleeps == [7.0]


def test_get_json_does_not_retry_non_retryable_client_errors(monkeypatch):
    import cyclemark.sources as sources

    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise HTTPError("https://example.invalid", 404, "not found", Message(), None)

    monkeypatch.setattr(sources, "urlopen", fake_urlopen)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(DataSourceError, match="Non-retryable HTTP 404"):
        sources._get_json("https://example.invalid")
    assert calls["count"] == 1
    assert sleeps == []


def test_get_json_backoff_is_bounded(monkeypatch):
    import cyclemark.sources as sources

    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        raise URLError("down")

    monkeypatch.setattr(sources, "urlopen", fake_urlopen)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(DataSourceError, match="Unable to retrieve"):
        sources._get_json("https://example.invalid", retries=3)
    assert sleeps == [1.0, 2.0]


def test_candle_fetch_reports_duplicate_rows(monkeypatch):
    import cyclemark.sources as sources

    row = [0, "100", "110", "90", "105", "2", 86_399_999]
    monkeypatch.setattr(sources, "_get_json", lambda url: [row, row])

    rows, stats = sources.fetch_binance_daily_klines_with_stats()
    assert len(rows) == 1
    assert stats["duplicate_rows_dropped"] == 1
    assert stats["raw_rows"] == 2
    assert stats["pages"] == 1



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



def test_binance_funding_adapter_validates_and_sorts_raw_observations(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(
        sources,
        "_get_json",
        lambda url: [
            {"fundingTime": 2000, "fundingRate": "-0.0002", "markPrice": "95000"},
            {"fundingTime": 1000, "fundingRate": "0.0001", "markPrice": "94000"},
        ],
    )
    result = sources.fetch_binance_funding_rates()
    assert [row["funding_time_ms"] for row in result] == [1000, 2000]
    assert result[0]["funding_rate"] == pytest.approx(0.0001)
    assert result[1]["funding_rate"] == pytest.approx(-0.0002)
    assert result[0]["source"] == "binance_usdm_funding_rate_api"
    assert result[0]["retrieved_at_utc"].endswith("Z")


def test_binance_funding_adapter_paginates_when_start_time_is_supplied(monkeypatch):
    import cyclemark.sources as sources

    calls = []

    def fake_get_json(url):
        calls.append(url)
        if len(calls) == 1:
            return [
                {"fundingTime": timestamp, "fundingRate": "0.0001"}
                for timestamp in range(1000)
            ]
        return [{"fundingTime": 1000, "fundingRate": "-0.0001"}]

    monkeypatch.setattr(sources, "_get_json", fake_get_json)
    result = sources.fetch_binance_funding_rates(start_time_ms=0)
    assert len(calls) == 2
    assert len(result) == 1001
    assert result[-1]["funding_time_ms"] == 1000


def test_binance_funding_adapter_rejects_invalid_rates_and_time_ranges(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(
        sources,
        "_get_json",
        lambda url: [{"fundingTime": 1000, "fundingRate": "nan"}],
    )
    with pytest.raises(DataSourceError, match="finite"):
        sources.fetch_binance_funding_rates()

    with pytest.raises(ValueError, match="must not precede"):
        sources.fetch_binance_funding_rates(start_time_ms=2000, end_time_ms=1000)


def test_binance_funding_adapter_accepts_an_empty_page(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(sources, "_get_json", lambda url: [])
    assert sources.fetch_binance_funding_rates() == []
    assert sources.fetch_binance_funding_rates(start_time_ms=0) == []


def test_binance_funding_pagination_rejects_a_repeated_page(monkeypatch):
    import cyclemark.sources as sources

    page = [
        {"fundingTime": timestamp, "fundingRate": "0.0001"}
        for timestamp in range(1000)
    ]
    monkeypatch.setattr(sources, "_get_json", lambda url: page)

    with pytest.raises(DataSourceError, match="did not advance"):
        sources.fetch_binance_funding_rates(start_time_ms=0)


def test_binance_funding_pagination_has_a_safety_limit(monkeypatch):
    import cyclemark.sources as sources

    calls = {"count": 0}

    def fake_get_json(url):
        page = calls["count"]
        calls["count"] += 1
        return [
            {"fundingTime": page * 1000 + offset, "fundingRate": "0.0001"}
            for offset in range(1000)
        ]

    monkeypatch.setattr(sources, "_get_json", fake_get_json)
    with pytest.raises(DataSourceError, match="safety limit"):
        list(sources.iter_binance_funding_rate_pages(start_time_ms=0, max_pages=2))
    assert calls["count"] == 2


def test_binance_funding_adapter_rejects_malformed_records(monkeypatch):
    import cyclemark.sources as sources

    monkeypatch.setattr(sources, "_get_json", lambda url: [["not", "an", "object"]])
    with pytest.raises(DataSourceError, match="Malformed"):
        sources.fetch_binance_funding_rates()

