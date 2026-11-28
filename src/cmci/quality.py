"""Basic data-quality checks required by requirements section 7.1.

Checks never modify or fill data; they only report status and reasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

_SEVERITY = {"normal": 0, "warning": 1, "degraded": 2, "unavailable": 3, "unknown": 0}

_FREQUENCY_MAX_GAP: dict[str, timedelta] = {
    "minute": timedelta(minutes=10),
    "minutely": timedelta(minutes=10),
    "hour": timedelta(hours=3),
    "hourly": timedelta(hours=3),
    "day": timedelta(days=4),
    "daily": timedelta(days=4),
    "week": timedelta(days=10),
    "weekly": timedelta(days=10),
    "month": timedelta(days=45),
    "monthly": timedelta(days=45),
    "quarter": timedelta(days=120),
    "quarterly": timedelta(days=120),
    "year": timedelta(days=400),
    "yearly": timedelta(days=400),
    "annual": timedelta(days=400),
}


@dataclass(frozen=True, slots=True)
class QualityIssue:
    check_type: str
    status: str
    message: str


def aggregate_status(issues: list[QualityIssue]) -> str:
    if not issues:
        return "normal"
    return max((issue.status for issue in issues), key=lambda status: _SEVERITY[status])


def expected_max_gap(frequency: str) -> timedelta | None:
    return _FREQUENCY_MAX_GAP.get(frequency.strip().lower())


def gap_issue(previous_end: str, current_start: str, frequency: str) -> QualityIssue | None:
    max_gap = expected_max_gap(frequency)
    if max_gap is None:
        return None
    previous = datetime.fromisoformat(previous_end.replace("Z", "+00:00"))
    current = datetime.fromisoformat(current_start.replace("Z", "+00:00"))
    actual = current - previous
    if actual > max_gap:
        return QualityIssue(
            "gap",
            "warning",
            f"距上一个观测间隔 {actual}，超过频率 {frequency} 的容差 {max_gap}",
        )
    return None


def unit_issue(unit: str, expected_unit: str) -> QualityIssue | None:
    if unit != expected_unit:
        return QualityIssue(
            "unit_mismatch",
            "warning",
            f"观测单位 {unit!r} 与指标字典单位 {expected_unit!r} 不一致",
        )
    return None


def release_time_issue(release_time: str | None) -> QualityIssue | None:
    if release_time is None:
        return QualityIssue(
            "release_time_missing",
            "warning",
            "缺少来源发布时间；available_time 依据系统接收时间，回放时可能高估可得性",
        )
    return None