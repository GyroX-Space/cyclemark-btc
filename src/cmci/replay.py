"""Historical replay by ``available_time``.

Given a dataset version and an as-of time ``T``, a replay returns only data
whose ``available_time`` was known at ``T``, choosing for every
(indicator, observation period) the latest vintage that was already available.
The result is written as a CSV snapshot and recorded in ``replay_jobs`` with a
deterministic hash, so identical inputs reproduce an identical snapshot.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DatasetVersion, ReplayJob
from .registry import NotFoundError, Registry, ValidationError
from .timeutils import TimeFormatError, to_utc_iso, utc_now_iso

DEFAULT_OUTPUT_DIR = Path("data") / "cmci" / "replays"

_ROW_FIELDS: tuple[str, ...] = (
    "dataset_version_id",
    "member_id",
    "usage_partition",
    "indicator_code",
    "indicator_id",
    "indicator_name",
    "layer",
    "observation_id",
    "observation_period_start",
    "observation_period_end",
    "release_time_utc",
    "available_time_utc",
    "vintage_time_utc",
    "value",
    "value_text",
    "unit",
    "quality_status",
    "source_id",
    "source_name",
)

_MEMBER_QUERY = """
SELECT m.member_id, m.usage_partition,
       o.indicator_id, o.observation_id, o.observation_period_start,
       o.observation_period_end, o.release_time_utc, o.available_time_utc,
       o.vintage_time_utc, o.value, o.value_text, o.unit, o.quality_status,
       o.source_id, i.indicator_code, i.indicator_name, i.layer,
       s.source_name
FROM dataset_members m
JOIN observations o ON o.indicator_id = m.indicator_id
JOIN indicators i ON i.indicator_id = o.indicator_id
JOIN data_sources s ON s.source_id = o.source_id
WHERE m.dataset_version_id = ?
  AND o.available_time_utc <= ?
  AND o.observation_period_start >= m.time_start
  AND o.observation_period_end <= m.time_end
ORDER BY i.indicator_code, o.observation_period_start, o.observation_period_end,
         o.vintage_time_utc DESC, o.created_at_utc DESC, o.observation_id DESC
"""


@dataclass(frozen=True, slots=True)
class ReplayResult:
    job: ReplayJob
    rows: tuple[dict[str, Any], ...]
    known_future_events: tuple[dict[str, Any], ...]
    report: dict[str, Any]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _row_hash(rows: tuple[dict[str, Any], ...]) -> str:
    canonical = sorted(
        (
            str(row["indicator_id"]),
            row["observation_period_start"],
            row["observation_period_end"],
            row["vintage_time_utc"],
            "" if row["value"] is None else repr(row["value"]),
            row["value_text"] or "",
            str(row["source_id"]),
        )
        for row in rows
    )
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReplayService:
    """Reconstructs what was known at a historical point in time."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.conn = registry.conn

    # ------------------------------------------------------------------ versions
    def resolve_version(
        self, dataset_code: str, version_no: int | None = None
    ) -> DatasetVersion:
        if version_no is None:
            row = self.conn.execute(
                "SELECT v.* FROM dataset_versions v "
                "JOIN research_datasets d ON d.dataset_id = v.dataset_id "
                "WHERE d.dataset_code = ? ORDER BY v.version_no DESC LIMIT 1",
                (dataset_code,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT v.* FROM dataset_versions v "
                "JOIN research_datasets d ON d.dataset_id = v.dataset_id "
                "WHERE d.dataset_code = ? AND v.version_no = ?",
                (dataset_code, int(version_no)),
            ).fetchone()
        if row is None:
            target = f"{dataset_code} v{version_no}" if version_no else dataset_code
            raise NotFoundError(f"数据集版本不存在: {target}")
        payload = dict(row)
        payload["invalidates_independent_validation"] = bool(
            payload["invalidates_independent_validation"]
        )
        return DatasetVersion(**payload)

    # ------------------------------------------------------------------ replay
    def preview(
        self, dataset_version_id: str, *, as_of: str
    ) -> tuple[tuple[dict[str, Any], ...], str]:
        """Compute a replay result without persisting a job.

        Used by the audit service to verify that a stored replay is reproducible.
        """
        self.resolve_version_by_id(dataset_version_id)
        try:
            as_of_utc = to_utc_iso(as_of, field="as_of")
        except TimeFormatError as exc:
            raise ValidationError(str(exc)) from exc
        assert as_of_utc is not None
        rows = self._collect_rows(dataset_version_id, as_of_utc)
        return rows, _row_hash(rows)

    def replay(
        self,
        dataset_version_id: str,
        *,
        as_of: str,
        created_by: str,
        output_dir: Path | str | None = None,
        actor: str | None = None,
    ) -> ReplayResult:
        version = self.resolve_version_by_id(dataset_version_id)
        try:
            as_of_utc = to_utc_iso(as_of, field="as_of")
        except TimeFormatError as exc:
            raise ValidationError(str(exc)) from exc
        assert as_of_utc is not None

        rows = self._collect_rows(dataset_version_id, as_of_utc)
        known_events = self._known_future_events(as_of_utc)
        result_hash = _row_hash(rows)

        dataset_code = self._dataset_code(version.dataset_id)
        report = self._build_report(
            dataset_code=dataset_code,
            dataset_version_id=dataset_version_id,
            version_no=version.version_no,
            as_of_utc=as_of_utc,
            rows=rows,
            result_hash=result_hash,
            known_future_events=known_events,
        )

        job_id = _new_id("rpj")
        target_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = target_dir / f"{job_id}.csv"
        self._write_snapshot(snapshot_path, rows)

        parameters = {
            "dataset_version_id": dataset_version_id,
            "as_of_utc": as_of_utc,
            "member_count": len(self._members(dataset_version_id)),
        }
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                "INSERT INTO replay_jobs (replay_job_id, dataset_version_id, as_of_utc, "
                "replay_result_hash, row_count, snapshot_path, parameters_json, "
                "report_json, created_by, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    dataset_version_id,
                    as_of_utc,
                    result_hash,
                    len(rows),
                    str(snapshot_path),
                    json.dumps(parameters, ensure_ascii=False, sort_keys=True),
                    json.dumps(report, ensure_ascii=False, sort_keys=True),
                    created_by,
                    now,
                ),
            )
            self._log(
                "replay_job",
                job_id,
                "replay",
                actor or created_by,
                {
                    "dataset_version_id": dataset_version_id,
                    "as_of_utc": as_of_utc,
                    "row_count": len(rows),
                    "replay_result_hash": result_hash,
                },
            )
        job = self.get_job(job_id)
        return ReplayResult(
            job=job,
            rows=rows,
            known_future_events=known_events,
            report=report,
        )

    def replay_dataset(
        self,
        dataset_code: str,
        *,
        as_of: str,
        created_by: str,
        version_no: int | None = None,
        output_dir: Path | str | None = None,
        actor: str | None = None,
    ) -> ReplayResult:
        version = self.resolve_version(dataset_code, version_no)
        return self.replay(
            version.dataset_version_id,
            as_of=as_of,
            created_by=created_by,
            output_dir=output_dir,
            actor=actor,
        )

    # ------------------------------------------------------------------ jobs
    def get_job(self, replay_job_id: str) -> ReplayJob:
        row = self.conn.execute(
            "SELECT * FROM replay_jobs WHERE replay_job_id = ?", (replay_job_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"回放任务不存在: {replay_job_id}")
        return ReplayJob(**dict(row))

    def list_jobs(
        self, *, dataset_version_id: str | None = None, limit: int = 100
    ) -> list[ReplayJob]:
        if dataset_version_id is None:
            rows = self.conn.execute(
                "SELECT * FROM replay_jobs ORDER BY created_at_utc DESC, replay_job_id LIMIT ?",
                (int(limit),),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM replay_jobs WHERE dataset_version_id = ? "
                "ORDER BY created_at_utc DESC, replay_job_id LIMIT ?",
                (dataset_version_id, int(limit)),
            ).fetchall()
        return [ReplayJob(**dict(row)) for row in rows]

    def export_snapshot(
        self, replay_job_id: str, target_path: Path | str
    ) -> Path:
        job = self.get_job(replay_job_id)
        if not job.snapshot_path:
            raise NotFoundError(f"回放任务没有快照文件: {replay_job_id}")
        source = Path(job.snapshot_path)
        if not source.exists():
            raise NotFoundError(f"回放快照文件不存在: {source}")
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target

    # ------------------------------------------------------------------ internals
    def resolve_version_by_id(self, dataset_version_id: str) -> DatasetVersion:
        row = self.conn.execute(
            "SELECT * FROM dataset_versions WHERE dataset_version_id = ?",
            (dataset_version_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"数据集版本不存在: {dataset_version_id}")
        payload = dict(row)
        payload["invalidates_independent_validation"] = bool(
            payload["invalidates_independent_validation"]
        )
        return DatasetVersion(**payload)

    def _members(self, dataset_version_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT m.*, i.indicator_code, i.indicator_name, i.layer "
            "FROM dataset_members m JOIN indicators i ON i.indicator_id = m.indicator_id "
            "WHERE m.dataset_version_id = ? ORDER BY i.indicator_code, m.time_start",
            (dataset_version_id,),
        ).fetchall()

    def _collect_rows(
        self, dataset_version_id: str, as_of_utc: str
    ) -> tuple[dict[str, Any], ...]:
        candidates = self.conn.execute(
            _MEMBER_QUERY, (dataset_version_id, as_of_utc)
        ).fetchall()
        seen: set[tuple[str, str, str, str]] = set()
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            key = (
                candidate["member_id"],
                candidate["indicator_id"],
                candidate["observation_period_start"],
                candidate["observation_period_end"],
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "dataset_version_id": dataset_version_id,
                    "member_id": candidate["member_id"],
                    "usage_partition": candidate["usage_partition"],
                    "indicator_code": candidate["indicator_code"],
                    "indicator_id": candidate["indicator_id"],
                    "indicator_name": candidate["indicator_name"],
                    "layer": candidate["layer"],
                    "observation_id": candidate["observation_id"],
                    "observation_period_start": candidate["observation_period_start"],
                    "observation_period_end": candidate["observation_period_end"],
                    "release_time_utc": candidate["release_time_utc"],
                    "available_time_utc": candidate["available_time_utc"],
                    "vintage_time_utc": candidate["vintage_time_utc"],
                    "value": candidate["value"],
                    "value_text": candidate["value_text"],
                    "unit": candidate["unit"],
                    "quality_status": candidate["quality_status"],
                    "source_id": candidate["source_id"],
                    "source_name": candidate["source_name"],
                }
            )
        return tuple(rows)

    def _known_future_events(self, as_of_utc: str) -> tuple[dict[str, Any], ...]:
        rows = self.conn.execute(
            "SELECT event_id, event_type, event_name, event_known_time_utc, "
            "event_effective_time_utc, event_source "
            "FROM known_future_events WHERE event_known_time_utc <= ? "
            "ORDER BY event_effective_time_utc, event_id",
            (as_of_utc,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def _dataset_code(self, dataset_id: str) -> str:
        row = self.conn.execute(
            "SELECT dataset_code FROM research_datasets WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"研究数据集不存在: {dataset_id}")
        return row["dataset_code"]

    def _build_report(
        self,
        *,
        dataset_code: str,
        dataset_version_id: str,
        version_no: int,
        as_of_utc: str,
        rows: tuple[dict[str, Any], ...],
        result_hash: str,
        known_future_events: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        members = self._members(dataset_version_id)
        covered = {row["member_id"] for row in rows}
        partition_counts: dict[str, int] = {}
        indicator_counts: dict[str, int] = {}
        for row in rows:
            partition_counts[row["usage_partition"]] = (
                partition_counts.get(row["usage_partition"], 0) + 1
            )
            indicator_counts[row["indicator_code"]] = (
                indicator_counts.get(row["indicator_code"], 0) + 1
            )
        return {
            "dataset_code": dataset_code,
            "dataset_version_id": dataset_version_id,
            "version_no": version_no,
            "as_of_utc": as_of_utc,
            "row_count": len(rows),
            "replay_result_hash": result_hash,
            "partition_counts": dict(sorted(partition_counts.items())),
            "indicator_counts": dict(sorted(indicator_counts.items())),
            "member_count": len(members),
            "members_without_data": [
                {
                    "member_id": member["member_id"],
                    "indicator_code": member["indicator_code"],
                    "usage_partition": member["usage_partition"],
                }
                for member in members
                if member["member_id"] not in covered
            ],
            "known_future_event_count": len(known_future_events),
        }

    @staticmethod
    def _write_snapshot(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(_ROW_FIELDS))
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row[field] for field in _ROW_FIELDS})

    def _log(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        self.conn.execute(
            "INSERT INTO operation_logs "
            "(entity_type, entity_id, action, actor, detail_json, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entity_type,
                entity_id,
                action,
                actor,
                json.dumps(detail, ensure_ascii=False, sort_keys=True),
                utc_now_iso(),
            ),
        )