"""Ingestion service: raw capture -> normalized observations -> quality checks.

Rules enforced here:
- raw payloads are stored once and never overwritten (content hash dedupe);
- observations are append-only; corrections become new vintages;
- available_time is set by the system (or explicitly by the caller), never by
  the source row;
- a source must be registered for the indicator before it can be ingested.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import quality
from .constants import IndicatorStatus
from .importers import ColumnMapping, detect_format, map_rows, read_rows
from .models import Indicator
from .registry import Registry, RegistryError
from .timeutils import TimeFormatError, to_utc_iso, utc_now_iso

_NUMERIC_DATA_TYPES = {"numeric", "count", "ratio", "percent", "percentage"}
_AVAILABLE_PRECISIONS = {"second", "minute", "date", "unknown"}
_AVAILABLE_METHODS = {
    "official_release",
    "historical_vintage",
    "conservative_lag",
    "manual_confirmed",
    "unknown",
}

_OBSERVATION_COLUMNS = (
    "observation_id",
    "indicator_id",
    "source_id",
    "raw_record_id",
    "observation_period_start",
    "observation_period_end",
    "release_time_utc",
    "available_time_utc",
    "available_time_precision",
    "available_time_method",
    "ingested_at_utc",
    "vintage_time_utc",
    "value",
    "value_text",
    "unit",
    "timezone",
    "quality_status",
    "time_precision_status",
    "revision_id",
    "supersedes_observation_id",
    "created_at_utc",
)

_INSERT_OBSERVATION_SQL = "INSERT INTO observations ({}) VALUES ({})".format(
    ", ".join(_OBSERVATION_COLUMNS),
    ", ".join("?" for _ in _OBSERVATION_COLUMNS),
)


class IngestionError(RegistryError, ValueError):
    """The ingestion request violates a governance rule or cannot be parsed."""


@dataclass(frozen=True, slots=True)
class IngestionResult:
    job_id: str
    raw_record_id: str | None
    duplicate_payload: bool
    records_received: int
    records_inserted: int
    records_updated: int
    records_rejected: int
    records_unchanged: int
    job_status: str


@dataclass(frozen=True, slots=True)
class _PreparedRow:
    row_number: int
    period_start: str
    period_end: str
    release_time: str | None
    available_time: str
    available_precision: str
    available_method: str
    vintage_time: str
    value: float | None
    value_text: str | None
    unit: str
    timezone: str
    time_precision: str


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IngestionService:
    """Couples the indicator registry with raw and normalized storage."""

    def __init__(self, registry: Registry, *, raw_dir: Path | str | None = None) -> None:
        self.registry = registry
        self.conn = registry.conn
        self.raw_dir = Path(raw_dir) if raw_dir is not None else None

    # ------------------------------------------------------------------ entry points
    def ingest_file(
        self,
        indicator_code: str,
        source_id: str,
        path: str | Path,
        mapping: ColumnMapping,
        *,
        actor: str = "system",
        available_time: str | None = None,
        vintage_time: str | None = None,
        batch_id: str | None = None,
        revision_reason: str = "value changed on re-ingestion",
    ) -> IngestionResult:
        file_path = Path(path)
        fmt = detect_format(file_path)
        data = file_path.read_bytes()
        rows = read_rows(data, fmt)
        return self.ingest_rows(
            indicator_code,
            source_id,
            rows,
            mapping,
            actor=actor,
            payload_format=fmt,
            raw_bytes=data,
            available_time=available_time,
            vintage_time=vintage_time,
            batch_id=batch_id or f"{file_path.stem}-{_new_id('batch')}",
            revision_reason=revision_reason,
        )

    def ingest_api_json(
        self,
        indicator_code: str,
        source_id: str,
        *,
        url: str,
        mapping: ColumnMapping,
        records_path: str | None = None,
        headers: dict[str, str] | None = None,
        fetcher: Callable[[str, dict[str, str] | None], tuple[bytes, Any]] | None = None,
        actor: str = "system",
        available_time: str | None = None,
        vintage_time: str | None = None,
        batch_id: str | None = None,
        revision_reason: str = "value changed on re-ingestion",
    ) -> IngestionResult:
        fetch = fetcher or fetch_json
        raw_bytes, payload = fetch(url, headers)
        rows = extract_records(payload, records_path)
        return self.ingest_rows(
            indicator_code,
            source_id,
            rows,
            mapping,
            actor=actor,
            payload_format="json",
            raw_bytes=raw_bytes,
            available_time=available_time,
            vintage_time=vintage_time,
            batch_id=batch_id or f"api-{_new_id('batch')}",
            revision_reason=revision_reason,
            source_release_time=None,
        )

    # ------------------------------------------------------------------ core
    def ingest_rows(
        self,
        indicator_code: str,
        source_id: str,
        rows: list[dict[str, Any]],
        mapping: ColumnMapping,
        *,
        actor: str = "system",
        payload_format: str = "json",
        raw_bytes: bytes | None = None,
        available_time: str | None = None,
        vintage_time: str | None = None,
        batch_id: str | None = None,
        revision_reason: str = "value changed on re-ingestion",
        source_release_time: str | None = None,
    ) -> IngestionResult:
        indicator = self.registry.get_indicator(indicator_code)
        if indicator.status != IndicatorStatus.ACTIVE.value:
            raise IngestionError(
                f"指标 {indicator_code} 当前状态为 {indicator.status}，只有启用的指标可以接入数据"
            )
        self._assert_source_registered(indicator, source_id)
        self.registry.get_source(source_id)

        mapped = map_rows(rows, mapping)
        if not mapped:
            raise IngestionError("没有可接入的数据行")

        now = utc_now_iso()
        available = to_utc_iso(available_time, field="available_time") or now
        default_vintage = to_utc_iso(vintage_time, field="vintage_time") or available
        batch = batch_id or _new_id("batch")

        prepared: list[_PreparedRow] = []
        row_errors: list[dict[str, Any]] = []
        for index, row in enumerate(mapped, start=1):
            try:
                prepared.append(
                    self._prepare_row(
                        indicator,
                        row,
                        row_number=index,
                        available=available,
                        default_vintage=default_vintage,
                    )
                )
            except (ValueError, TimeFormatError) as exc:
                row_errors.append({"row": index, "error": str(exc)})

        job_id = _new_id("job")
        self._create_job(
            job_id,
            indicator,
            source_id,
            prepared=prepared,
            records_received=len(mapped),
            actor=actor,
            now=now,
        )

        payload_bytes = raw_bytes if raw_bytes is not None else _rows_to_bytes(rows)
        content_hash = _sha256(payload_bytes)
        duplicate = self.conn.execute(
            "SELECT raw_record_id FROM raw_records "
            "WHERE source_id = ? AND indicator_id = ? AND content_hash = ?",
            (source_id, indicator.indicator_id, content_hash),
        ).fetchone()
        if duplicate is not None:
            job_status = "succeeded" if not row_errors else "partial"
            self._finish_job(
                job_id,
                job_status=job_status,
                inserted=0,
                updated=0,
                rejected=len(row_errors),
                errors=row_errors,
            )
            return IngestionResult(
                job_id=job_id,
                raw_record_id=duplicate["raw_record_id"],
                duplicate_payload=True,
                records_received=len(mapped),
                records_inserted=0,
                records_updated=0,
                records_rejected=len(row_errors),
                records_unchanged=0,
                job_status=job_status,
            )

        raw_record_id = _new_id("raw")
        payload_text, payload_path = self._store_raw_payload(
            raw_record_id, batch, payload_format, raw_bytes, rows
        )
        release_times = [row.release_time for row in prepared if row.release_time]
        raw_release = source_release_time or (min(release_times) if release_times else None)

        with self.conn:
            self.conn.execute(
                "INSERT INTO raw_records (raw_record_id, source_id, indicator_id, job_id, batch_id, "
                "received_at_utc, source_release_time_utc, payload, payload_path, payload_format, "
                "content_hash, ingestion_status, error_message, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'stored', NULL, ?)",
                (
                    raw_record_id,
                    source_id,
                    indicator.indicator_id,
                    job_id,
                    batch,
                    now,
                    raw_release,
                    payload_text,
                    payload_path,
                    payload_format,
                    content_hash,
                    now,
                ),
            )

        inserted = updated = unchanged = 0
        for prepared_row in prepared:
            outcome = self._store_observation(
                indicator,
                source_id,
                raw_record_id,
                prepared_row,
                job_id=job_id,
                actor=actor,
                revision_reason=revision_reason,
            )
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            elif outcome == "unchanged":
                unchanged += 1
            else:
                row_errors.append(
                    {
                        "row": prepared_row.row_number,
                        "error": "同一 vintage 已存在不同取值，拒绝覆盖",
                    }
                )

        if row_errors and inserted + updated == 0:
            job_status = "failed"
        elif row_errors:
            job_status = "partial"
        else:
            job_status = "succeeded"

        self._finish_job(
            job_id,
            job_status=job_status,
            inserted=inserted,
            updated=updated,
            rejected=len(row_errors),
            errors=row_errors,
        )
        return IngestionResult(
            job_id=job_id,
            raw_record_id=raw_record_id,
            duplicate_payload=False,
            records_received=len(mapped),
            records_inserted=inserted,
            records_updated=updated,
            records_rejected=len(row_errors),
            records_unchanged=unchanged,
            job_status=job_status,
        )

    # ------------------------------------------------------------------ rows
    def _prepare_row(
        self,
        indicator: Indicator,
        row: dict[str, Any],
        *,
        row_number: int,
        available: str,
        default_vintage: str,
    ) -> _PreparedRow:
        start_raw = row.get("period_start")
        if start_raw is None or not str(start_raw).strip():
            raise ValueError("observation_period_start 为空")
        start_text = str(start_raw).strip()
        precision = "exact" if ("T" in start_text or ":" in start_text) else "date_only"
        start = to_utc_iso(start_text, field="observation_period_start")
        assert start is not None

        if row.get("period_end") not in (None, ""):
            end_raw = str(row["period_end"]).strip()
            end = to_utc_iso(end_raw, field="observation_period_end")
            if "T" in end_raw or ":" in end_raw:
                precision = "exact"
        else:
            end = start
        assert end is not None
        if end < start:
            raise ValueError("observation_period_end 不能早于 start")

        release = None
        if row.get("release_time") not in (None, ""):
            release = to_utc_iso(str(row["release_time"]).strip(), field="release_time")
        time_precision = precision if release is not None else "partial"

        vintage = default_vintage
        if row.get("vintage_time") not in (None, ""):
            vintage = to_utc_iso(str(row["vintage_time"]).strip(), field="vintage_time") or vintage

        row_available = available
        if row.get("available_time") not in (None, ""):
            row_available = (
                to_utc_iso(str(row["available_time"]).strip(), field="available_time")
                or available
            )
        available_precision = row.get("available_time_precision")
        if available_precision in (None, ""):
            available_precision = "second" if ":" in row_available else "date"
        if available_precision not in _AVAILABLE_PRECISIONS:
            raise ValueError(f"available_time_precision 非法: {available_precision!r}")
        available_method = row.get("available_time_method")
        if available_method in (None, ""):
            available_method = "unknown"
        if available_method not in _AVAILABLE_METHODS:
            raise ValueError(f"available_time_method 非法: {available_method!r}")

        value, value_text = _parse_value(indicator, row.get("value"))
        if row.get("value_text") not in (None, ""):
            value_text = str(row["value_text"])
        unit = row.get("unit")
        unit = str(unit).strip() if unit not in (None, "") else indicator.unit
        tz = row.get("timezone")
        tz = str(tz).strip() if tz not in (None, "") else indicator.timezone

        return _PreparedRow(
            row_number=row_number,
            period_start=start,
            period_end=end,
            release_time=release,
            available_time=row_available,
            available_precision=available_precision,
            available_method=available_method,
            vintage_time=vintage,
            value=value,
            value_text=value_text,
            unit=unit,
            timezone=tz,
            time_precision=time_precision,
        )

    def _store_observation(
        self,
        indicator: Indicator,
        source_id: str,
        raw_record_id: str,
        row: _PreparedRow,
        *,
        job_id: str,
        actor: str,
        revision_reason: str,
    ) -> str:
        previous = self.conn.execute(
            "SELECT * FROM observations WHERE indicator_id = ? AND source_id = ? "
            "AND observation_period_start = ? AND observation_period_end = ? "
            "ORDER BY vintage_time_utc DESC LIMIT 1",
            (indicator.indicator_id, source_id, row.period_start, row.period_end),
        ).fetchone()

        if previous is not None:
            if previous["vintage_time_utc"] == row.vintage_time:
                if (
                    previous["value"] == row.value
                    and previous["value_text"] == row.value_text
                    and previous["unit"] == row.unit
                ):
                    return "unchanged"
                return "rejected"
            if (
                previous["value"] == row.value
                and previous["value_text"] == row.value_text
                and previous["unit"] == row.unit
            ):
                return "unchanged"

        issues = self._quality_issues(indicator, source_id, row)
        status = quality.aggregate_status(issues)

        observation_id = _new_id("obs")
        revision_id = _new_id("rev")
        now = utc_now_iso()
        values = {
            "observation_id": observation_id,
            "indicator_id": indicator.indicator_id,
            "source_id": source_id,
            "raw_record_id": raw_record_id,
            "observation_period_start": row.period_start,
            "observation_period_end": row.period_end,
            "release_time_utc": row.release_time,
            "available_time_utc": row.available_time,
            "available_time_precision": row.available_precision,
            "available_time_method": row.available_method,
            "ingested_at_utc": now,
            "vintage_time_utc": row.vintage_time,
            "value": row.value,
            "value_text": row.value_text,
            "unit": row.unit,
            "timezone": row.timezone,
            "quality_status": status,
            "time_precision_status": row.time_precision,
            "revision_id": revision_id,
            "supersedes_observation_id": previous["observation_id"] if previous else None,
            "created_at_utc": now,
        }

        with self.conn:
            self.conn.execute(
                _INSERT_OBSERVATION_SQL, [values[column] for column in _OBSERVATION_COLUMNS]
            )
            self.conn.execute(
                "INSERT INTO observation_revisions (revision_id, indicator_id, observation_id, "
                "previous_observation_id, revision_reason, revised_by, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    revision_id,
                    indicator.indicator_id,
                    observation_id,
                    previous["observation_id"] if previous else None,
                    revision_reason if previous else "initial ingestion",
                    actor,
                    now,
                ),
            )
            for issue in issues:
                self.conn.execute(
                    "INSERT INTO data_quality_checks (check_id, observation_id, job_id, "
                    "indicator_id, check_type, status, message, created_at_utc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _new_id("chk"),
                        observation_id,
                        job_id,
                        indicator.indicator_id,
                        issue.check_type,
                        issue.status,
                        issue.message,
                        now,
                    ),
                )
        return "updated" if previous is not None else "inserted"

    def _quality_issues(
        self, indicator: Indicator, source_id: str, row: _PreparedRow
    ) -> list[quality.QualityIssue]:
        issues: list[quality.QualityIssue] = []
        unit_issue = quality.unit_issue(row.unit, indicator.unit)
        if unit_issue:
            issues.append(unit_issue)
        release_issue = quality.release_time_issue(row.release_time)
        if release_issue:
            issues.append(release_issue)

        previous_period = self.conn.execute(
            "SELECT observation_period_end FROM observations "
            "WHERE indicator_id = ? AND source_id = ? AND observation_period_end < ? "
            "ORDER BY observation_period_end DESC LIMIT 1",
            (indicator.indicator_id, source_id, row.period_start),
        ).fetchone()
        if previous_period is not None:
            gap = quality.gap_issue(
                previous_period["observation_period_end"], row.period_start, indicator.frequency
            )
            if gap:
                issues.append(gap)
        return issues

    # ------------------------------------------------------------------ storage helpers
    def _store_raw_payload(
        self,
        raw_record_id: str,
        batch_id: str,
        payload_format: str,
        raw_bytes: bytes | None,
        rows: list[dict[str, Any]],
    ) -> tuple[str | None, str | None]:
        if raw_bytes is None:
            return _rows_to_text(rows), None

        try:
            decoded: str | None = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            decoded = None

        if payload_format == "xlsx" or decoded is None:
            if self.raw_dir is None:
                raise IngestionError("二进制原始文件必须配置 raw_dir 才能保存")
            target = self.raw_dir / batch_id / f"{raw_record_id}.{payload_format}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw_bytes)
            return None, str(target)
        return decoded, None

    def _assert_source_registered(self, indicator: Indicator, source_id: str) -> None:
        links = self.registry.list_indicator_sources(indicator.indicator_code, active_only=True)
        if not any(link.source_id == source_id for link in links):
            raise IngestionError(
                f"数据源 {source_id} 未登记为指标 {indicator.indicator_code} 的启用来源；"
                "来源切换请先关闭旧映射并登记新映射"
            )

    def _create_job(
        self,
        job_id: str,
        indicator: Indicator,
        source_id: str,
        *,
        prepared: list[_PreparedRow],
        records_received: int,
        actor: str,
        now: str,
    ) -> None:
        start = min((row.period_start for row in prepared), default=None)
        end = max((row.period_end for row in prepared), default=None)
        with self.conn:
            self.conn.execute(
                "INSERT INTO ingestion_jobs (job_id, source_id, indicator_id, start_time_utc, "
                "end_time_utc, execution_time_utc, finished_at_utc, records_received, "
                "records_inserted, records_updated, records_rejected, job_status, error_log, "
                "actor, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 0, 0, 0, 'running', NULL, ?, ?)",
                (
                    job_id,
                    source_id,
                    indicator.indicator_id,
                    start,
                    end,
                    now,
                    records_received,
                    actor,
                    now,
                ),
            )

    def _finish_job(
        self,
        job_id: str,
        *,
        job_status: str,
        inserted: int,
        updated: int,
        rejected: int,
        errors: list[dict[str, Any]],
    ) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE ingestion_jobs SET finished_at_utc = ?, records_inserted = ?, "
                "records_updated = ?, records_rejected = ?, job_status = ?, error_log = ? "
                "WHERE job_id = ?",
                (
                    utc_now_iso(),
                    inserted,
                    updated,
                    rejected,
                    job_status,
                    json.dumps(errors, ensure_ascii=False) if errors else None,
                    job_id,
                ),
            )


def _parse_value(indicator: Indicator, raw: Any) -> tuple[float | None, str | None]:
    if raw is None:
        raise ValueError("观测值为空")
    text = str(raw).strip()
    if not text:
        raise ValueError("观测值为空")

    if indicator.data_type.strip().lower() in _NUMERIC_DATA_TYPES:
        cleaned = text.replace(",", "").replace(" ", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
        try:
            return float(cleaned), None
        except ValueError as exc:
            raise ValueError(f"观测值不是数值: {raw!r}") from exc
    return None, text


def _rows_to_text(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)


def _rows_to_bytes(rows: list[dict[str, Any]]) -> bytes:
    return _rows_to_text(rows).encode("utf-8")


def fetch_json(
    url: str, headers: dict[str, str] | None = None, *, timeout: float = 30.0
) -> tuple[bytes, Any]:
    """Minimal JSON fetch used by the API ingestion framework."""
    from urllib.request import Request, urlopen

    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit source URL
        raw = response.read()
    return raw, json.loads(raw.decode("utf-8"))


def extract_records(payload: Any, records_path: str | None = None) -> list[dict[str, Any]]:
    node = payload
    if records_path:
        for part in records_path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise IngestionError(f"响应中不存在路径: {records_path}")
            node = node[part]
    elif isinstance(node, dict) and isinstance(node.get("data"), list):
        node = node["data"]
    if not isinstance(node, list) or not all(isinstance(item, dict) for item in node):
        raise IngestionError("API 响应不是对象数组")
    return node