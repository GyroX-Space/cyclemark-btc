import json
from datetime import date, datetime, timedelta, timezone

import pytest

from cyclemark.daily import run_daily_refresh
from cyclemark.sources import DataSourceError

NOW = datetime(2026, 1, 6, 2, 0, tzinfo=timezone.utc)
GENERATED_AT = "2026-01-06T02:00:00Z"


def _candles(*, end: date = date(2026, 1, 5), days: int = 260, last_close: float = 60_000.0) -> list[dict]:
    start = end - timedelta(days=days - 1)
    step = (last_close - 30_000.0) / max(days - 1, 1)
    rows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        open_ms = int(midnight.timestamp() * 1000)
        close = 30_000.0 + step * offset
        rows.append({
            "open_time_ms": open_ms,
            "close_time_ms": open_ms + 86_399_999,
            "open": close, "high": close + 100.0, "low": close - 100.0,
            "close": close, "volume": 10.0, "source": "test_fixture",
        })
    return rows


def _stats(**overrides) -> dict:
    stats = {
        "source": "test_fixture", "pages": 1, "raw_rows": 260,
        "duplicate_rows_dropped": 0, "requested_start_time_ms": None,
        "retrieved_at_utc": "2026-01-06T02:00:00Z",
    }
    stats.update(overrides)
    return stats


def _unavailable(message: str):
    def _raise():
        raise DataSourceError(message)
    return _raise


def _base_kwargs(tmp_path, **overrides):
    kwargs = {
        "signals_dir": tmp_path / "signals",
        "market_dir": tmp_path / "market",
        "now": NOW,
        "generated_at_utc": GENERATED_AT,
        "fetch_candles": lambda: (_candles(), _stats()),
        "fetch_sentiment": _unavailable("sentiment feed down"),
        "fetch_funding": _unavailable("funding feed down"),
    }
    kwargs.update(overrides)
    return kwargs


def test_optional_feed_failures_do_not_block_price_only_publication(tmp_path):
    result = run_daily_refresh(**_base_kwargs(tmp_path))

    assert result["publication"]["outcome"] == "published"
    record = result["record"]
    assert record["bfs"] is not None
    optional = record["data_quality"]["optional_sources"]
    assert optional["fear_greed"]["status"] == "unavailable"
    assert "sentiment feed down" in optional["fear_greed"]["error"]
    assert optional["funding"]["status"] == "unavailable"
    assert (tmp_path / "signals" / "2026-01-05.json").exists()


def test_core_price_failure_writes_no_record(tmp_path):
    kwargs = _base_kwargs(tmp_path, fetch_candles=_unavailable("price feed down"))
    with pytest.raises(DataSourceError, match="price feed down"):
        run_daily_refresh(**kwargs)
    assert not (tmp_path / "signals").exists()


def test_stale_core_data_fails_closed_without_publication(tmp_path):
    kwargs = _base_kwargs(tmp_path, now=datetime(2026, 1, 9, 2, 0, tzinfo=timezone.utc))
    with pytest.raises(DataSourceError, match="quality checks"):
        run_daily_refresh(**kwargs)
    assert not (tmp_path / "signals").exists()


def test_calendar_gap_in_core_data_fails_closed(tmp_path):
    candles = _candles()
    del candles[-40]
    kwargs = _base_kwargs(tmp_path, fetch_candles=lambda: (candles, _stats()))
    with pytest.raises(DataSourceError, match="missing calendar dates"):
        run_daily_refresh(**kwargs)
    assert not (tmp_path / "signals").exists()


def test_identical_rerun_is_idempotent(tmp_path):
    kwargs = _base_kwargs(tmp_path)
    first = run_daily_refresh(**kwargs)
    second = run_daily_refresh(**kwargs)

    assert first["publication"]["outcome"] == "published"
    assert second["publication"]["outcome"] == "unchanged"
    history = json.loads((tmp_path / "signals" / "history.json").read_text(encoding="utf-8"))
    assert len(history) == 1


def test_corrupt_funding_archive_does_not_block_publication(tmp_path):
    market = tmp_path / "market"
    market.mkdir(parents=True)
    (market / "binance_funding_rates.json").write_text("{not json", encoding="utf-8")
    funding = [{
        "funding_time_ms": 1_700_000_000_000, "funding_rate": 0.0001,
        "mark_price": 60_000.0, "symbol": "BTCUSDT",
        "source": "binance_usdm_funding_rate_api", "schema_version": "1.0",
        "retrieved_at_utc": GENERATED_AT,
    }]
    kwargs = _base_kwargs(tmp_path, fetch_funding=lambda: funding)
    result = run_daily_refresh(**kwargs)

    assert result["publication"]["outcome"] == "published"
    assert result["funding_archive"]["status"] == "failed"
    assert (tmp_path / "signals" / "2026-01-05.json").exists()


def test_funding_archive_is_written_after_signal_publication(tmp_path):
    funding = [{
        "funding_time_ms": 1_700_000_000_000, "funding_rate": 0.0001,
        "mark_price": 60_000.0, "symbol": "BTCUSDT",
        "source": "binance_usdm_funding_rate_api", "schema_version": "1.0",
        "retrieved_at_utc": GENERATED_AT,
    }]
    result = run_daily_refresh(**_base_kwargs(tmp_path, fetch_funding=lambda: funding))

    assert result["funding_archive"]["status"] == "written"
    archived = json.loads(
        (tmp_path / "market" / "binance_funding_rates.json").read_text(encoding="utf-8")
    )
    assert len(archived) == 1
    assert result["record"]["market_data"]["derivatives"]["funding_observations_retrieved"] == 1
