"""UTC time normalisation for CMCI.

All stored timestamps are ISO-8601 UTC text with a trailing ``Z`` so that
lexicographic ordering equals chronological ordering.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


class TimeFormatError(ValueError):
    """Raised when a timestamp cannot be interpreted."""


def to_utc_iso(value: str | date | datetime | None, *, field: str) -> str | None:
    """Normalise a date/datetime/ISO string to ``YYYY-MM-DDTHH:MM:SSZ``.

    Naive values are treated as UTC. ``None`` passes through unchanged.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise TimeFormatError(f"{field} 不能为空字符串")
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TimeFormatError(f"{field} 不是合法的 ISO-8601 时间: {value!r}") from exc
    else:
        raise TimeFormatError(f"{field} 类型不受支持: {type(value).__name__}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")