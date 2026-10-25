"""Per-run data-quality assessment for core market observations."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

MS_PER_DAY = 86_400_000
DAILY_CLOSE_OFFSET_MS = 86_399_999
MAX_REPORTED_MISSING_DATES = 120


def _utc_date(timestamp_ms: int) -> date:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).date()


def summarize_candle_quality(
    candles: list[dict],
    *,
    now_utc: datetime,
    fetch_stats: dict | None = None,
    max_missing_dates: int = 0,
    stale_after_days: int = 1,
) -> dict:
    """Summarize whether a finalized daily candle series is safe to score.

    Any fatal issue means the daily score must not be published. Duplicate
    timestamps, non-UTC-midnight opens, irregular close offsets, unexpected
    calendar gaps, and stale or future-dated observations are all treated as
    fatal because they make the feature window ambiguous.
    """
    if not isinstance(now_utc, datetime) or now_utc.tzinfo is None:
        raise ValueError("now_utc must be a timezone-aware datetime.")
    if not isinstance(candles, list):
        raise ValueError("candles must be a list.")
    if max_missing_dates < 0 or stale_after_days < 0:
        raise ValueError("Quality thresholds must be non-negative.")

    now = now_utc.astimezone(timezone.utc)
    stats = dict(fetch_stats or {})
    fatal: list[str] = []
    warnings: list[str] = []

    if not candles:
        fatal.append("No finalized daily candles were available.")
        return _result(
            now=now, candles=[], stats=stats, dates=[],
            expected_days=0, missing=[], duplicates=0,
            non_midnight=0, irregular_close=0, age=None,
            stale=False, fatal=fatal, warnings=warnings,
        )

    opens = [int(item["open_time_ms"]) for item in candles]
    closes = [int(item["close_time_ms"]) for item in candles]
    duplicates = len(opens) - len(set(opens))
    if duplicates:
        fatal.append(f"{duplicates} duplicate open timestamps were present in the finalized series.")
    if any(right <= left for left, right in zip(opens, opens[1:])):
        fatal.append("Finalized candle open timestamps are not strictly increasing.")

    non_midnight = sum(1 for value in opens if value % MS_PER_DAY != 0)
    if non_midnight:
        fatal.append(f"{non_midnight} candles do not open at UTC midnight.")
    irregular_close = sum(
        1 for open_ms, close_ms in zip(opens, closes)
        if close_ms - open_ms != DAILY_CLOSE_OFFSET_MS
    )
    if irregular_close:
        fatal.append(f"{irregular_close} candles have an irregular close-time offset.")

    dates = [_utc_date(value) for value in opens]
    first_date, last_date = dates[0], dates[-1]
    expected_days = (last_date - first_date).days + 1
    observed_dates = set(dates)
    missing: list[str] = []
    cursor = first_date
    while cursor <= last_date:
        if cursor not in observed_dates:
            missing.append(cursor.isoformat())
        cursor += timedelta(days=1)
    if len(missing) > max_missing_dates:
        fatal.append(
            f"{len(missing)} missing calendar dates exceed the allowed maximum "
            f"of {max_missing_dates}."
        )

    age = (now.date() - last_date).days
    is_stale = age > stale_after_days
    if age < 0:
        fatal.append("The latest finalized candle is dated in the future.")
    elif is_stale:
        fatal.append(
            f"The latest finalized candle is {age} days old; "
            f"maximum allowed is {stale_after_days}."
        )

    dropped_at_fetch = int(stats.get("duplicate_rows_dropped", 0) or 0)
    if dropped_at_fetch:
        warnings.append(
            f"{dropped_at_fetch} duplicate rows were dropped while assembling the series."
        )

    return _result(
        now=now, candles=candles, stats=stats, dates=dates,
        expected_days=expected_days, missing=missing, duplicates=duplicates,
        non_midnight=non_midnight, irregular_close=irregular_close, age=age,
        stale=is_stale, fatal=fatal, warnings=warnings,
    )


def _result(
    *,
    now: datetime,
    candles: list[dict],
    stats: dict,
    dates: list[date],
    expected_days: int,
    missing: list[str],
    duplicates: int,
    non_midnight: int,
    irregular_close: int,
    age: int | None,
    stale: bool,
    fatal: list[str],
    warnings: list[str],
) -> dict:
    return {
        "assessed_at_utc": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "finalized_candle_count": len(candles),
        "first_candle_date_utc": dates[0].isoformat() if dates else None,
        "last_candle_date_utc": dates[-1].isoformat() if dates else None,
        "expected_calendar_days": expected_days,
        "missing_date_count": len(missing),
        "missing_dates_utc": missing[:MAX_REPORTED_MISSING_DATES],
        "missing_dates_truncated": len(missing) > MAX_REPORTED_MISSING_DATES,
        "duplicate_open_time_count": duplicates,
        "non_utc_midnight_open_time_count": non_midnight,
        "irregular_close_time_count": irregular_close,
        "latest_candle_age_days": age,
        "is_stale": stale,
        "source_fetch": stats,
        "warnings": warnings,
        "fatal_issues": fatal,
    }
