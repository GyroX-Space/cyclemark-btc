from datetime import date, datetime, timedelta, timezone

from cyclemark.quality import summarize_candle_quality


def _candle(day: date, *, close: float = 100.0, open_offset_ms: int = 0) -> dict:
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    open_ms = int(midnight.timestamp() * 1000) + open_offset_ms
    return {
        "open_time_ms": open_ms,
        "close_time_ms": open_ms + 86_399_999,
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": 1.0, "source": "test_fixture",
    }


def _series(start: date, days: int) -> list[dict]:
    return [_candle(start + timedelta(days=offset)) for offset in range(days)]


NOW = datetime(2026, 1, 6, 2, 0, tzinfo=timezone.utc)


def test_clean_series_passes_and_reports_expected_days():
    result = summarize_candle_quality(_series(date(2026, 1, 1), 5), now_utc=NOW)
    assert result["fatal_issues"] == []
    assert result["finalized_candle_count"] == 5
    assert result["expected_calendar_days"] == 5
    assert result["missing_date_count"] == 0
    assert result["last_candle_date_utc"] == "2026-01-05"
    assert result["latest_candle_age_days"] == 1
    assert result["is_stale"] is False


def test_missing_calendar_date_fails_closed():
    candles = _series(date(2026, 1, 1), 5)
    del candles[2]
    result = summarize_candle_quality(candles, now_utc=NOW)
    assert result["missing_date_count"] == 1
    assert result["missing_dates_utc"] == ["2026-01-03"]
    assert any("missing calendar dates" in issue for issue in result["fatal_issues"])


def test_missing_dates_can_be_allowed_explicitly():
    candles = _series(date(2026, 1, 1), 5)
    del candles[2]
    result = summarize_candle_quality(candles, now_utc=NOW, max_missing_dates=1)
    assert result["missing_date_count"] == 1
    assert result["fatal_issues"] == []


def test_stale_series_fails_closed():
    result = summarize_candle_quality(
        _series(date(2026, 1, 1), 5), now_utc=datetime(2026, 1, 9, 2, 0, tzinfo=timezone.utc)
    )
    assert result["is_stale"] is True
    assert result["latest_candle_age_days"] == 4
    assert any("days old" in issue for issue in result["fatal_issues"])


def test_future_dated_candle_fails_closed():
    result = summarize_candle_quality(
        _series(date(2026, 1, 1), 5), now_utc=datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    )
    assert any("future" in issue for issue in result["fatal_issues"])


def test_timestamp_alignment_and_duplicates_fail_closed():
    candles = _series(date(2026, 1, 1), 4)
    candles.append(_candle(date(2026, 1, 4)))
    candles[1] = _candle(date(2026, 1, 2), open_offset_ms=3_600_000)
    candles[2]["close_time_ms"] = candles[2]["open_time_ms"] + 3_600_000
    result = summarize_candle_quality(candles, now_utc=NOW)
    assert result["duplicate_open_time_count"] == 1
    assert result["non_utc_midnight_open_time_count"] == 1
    assert result["irregular_close_time_count"] == 1
    assert len(result["fatal_issues"]) >= 3


def test_duplicates_dropped_at_fetch_are_reported_as_a_warning():
    result = summarize_candle_quality(
        _series(date(2026, 1, 1), 5),
        now_utc=NOW,
        fetch_stats={"duplicate_rows_dropped": 2},
    )
    assert result["fatal_issues"] == []
    assert any("were dropped" in warning for warning in result["warnings"])


def test_empty_series_is_fatal():
    result = summarize_candle_quality([], now_utc=NOW)
    assert result["finalized_candle_count"] == 0
    assert result["latest_candle_age_days"] is None
    assert result["fatal_issues"] == ["No finalized daily candles were available."]
