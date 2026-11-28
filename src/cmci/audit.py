"""Data quality reporting and look-ahead audit.

Two audit types are recorded in ``audit_jobs`` / ``audit_results``:

- ``quality``: coverage, release delay, revision and quality-status summary per
  indicator, plus warnings for active indicators without data.
- ``lookahead``: seeded random sampling of observations to verify
  ``available_time`` against ``release_time``, vintage/revision consistency, and
  reproducibility of every stored replay by recomputing its result hash.

Findings are append-only, so an independent reviewer can trace each result back
to the rule, entity, and parameters that produced it.
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .models import AuditJob, AuditResult
from .registry import NotFoundError, Registry, ValidationError
from .replay import ReplayService
from .timeutils import utc_now_iso

DEFAULT_OUTPUT_DIR = Path("data") / "cmci" / "audits"


@dataclass(frozen=True, slots=True)
class AuditRun:
    job: AuditJob
    results: tuple[AuditResult, ...]
    report: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Finding:
    severity: str
    rule_code: str
    entity_type: str
    entity_id: str
    detail: dict[str, Any]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} 不能为空")
    return value.strip()


class AuditService:
    """Produces traceable quality and look-ahead audit records."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.conn = registry.conn
        self.replay = ReplayService(registry)

    # ------------------------------------------------------------------ quality
    def run_quality_report(
        self,
        *,
        created_by: str,
        output_dir: Path | str | None = None,
        actor: str | None = None,
    ) -> AuditRun:
        indicators = self._indicator_quality()
        check_counts = self._quality_check_counts()
        findings: list[_Finding] = []

        for item in indicators:
            indicator_id = item["indicator_id"]
            if item["status"] == "active" and item["observation_count"] == 0:
                findings.append(
                    _Finding(
                        "warning",
                        "active_indicator_without_data",
                        "indicator",
                        indicator_id,
                        {"indicator_code": item["indicator_code"]},
                    )
                )
            if item["missing_release_time"]:
                findings.append(
                    _Finding(
                        "warning",
                        "missing_release_time",
                        "indicator",
                        indicator_id,
                        {
                            "indicator_code": item["indicator_code"],
                            "missing": item["missing_release_time"],
                        },
                    )
                )
            if item["non_normal_count"]:
                findings.append(
                    _Finding(
                        "warning",
                        "non_normal_quality",
                        "indicator",
                        indicator_id,
                        {
                            "indicator_code": item["indicator_code"],
                            "non_normal": item["non_normal_count"],
                        },
                    )
                )

        report = {
            "audit_type": "quality",
            "generated_at_utc": utc_now_iso(),
            "indicator_count": len(indicators),
            "indicators": indicators,
            "quality_check_total": sum(check_counts.values()),
            "quality_check_counts": dict(sorted(check_counts.items())),
            "summary": {
                "checked": len(indicators),
                "violations": 0,
                "warnings": len(findings),
            },
        }
        return self._persist(
            audit_type="quality",
            parameters={},
            checked_count=len(indicators),
            findings=findings,
            report=report,
            created_by=created_by,
            actor=actor,
            output_dir=output_dir,
        )

    # ------------------------------------------------------------------ look-ahead
    def run_lookahead_audit(
        self,
        *,
        created_by: str,
        sample_size: int | None = None,
        seed: int | None = None,
        output_dir: Path | str | None = None,
        actor: str | None = None,
    ) -> AuditRun:
        if sample_size is not None and sample_size <= 0:
            raise ValidationError("sample_size 必须为正整数")

        observations = self.conn.execute(
            "SELECT o.observation_id, o.indicator_id, o.release_time_utc, "
            "o.available_time_utc, o.vintage_time_utc, o.supersedes_observation_id, "
            "i.indicator_code "
            "FROM observations o JOIN indicators i ON i.indicator_id = o.indicator_id "
            "ORDER BY o.observation_id"
        ).fetchall()
        total = len(observations)
        effective_seed = seed
        if sample_size is not None and sample_size < total:
            if effective_seed is None:
                effective_seed = random.SystemRandom().randint(0, 2**31 - 1)
            rng = random.Random(effective_seed)
            sampled = rng.sample(observations, sample_size)
            sampled.sort(key=lambda row: row["observation_id"])
        else:
            sampled = observations

        findings: list[_Finding] = []
        for row in sampled:
            available = row["available_time_utc"]
            release = row["release_time_utc"]
            if available is None:
                findings.append(
                    _Finding(
                        "violation",
                        "missing_available_time",
                        "observation",
                        row["observation_id"],
                        {"indicator_code": row["indicator_code"]},
                    )
                )
            elif release is None:
                findings.append(
                    _Finding(
                        "warning",
                        "missing_release_time",
                        "observation",
                        row["observation_id"],
                        {
                            "indicator_code": row["indicator_code"],
                            "available_time_utc": available,
                        },
                    )
                )
            elif available < release:
                findings.append(
                    _Finding(
                        "violation",
                        "available_before_release",
                        "observation",
                        row["observation_id"],
                        {
                            "indicator_code": row["indicator_code"],
                            "release_time_utc": release,
                            "available_time_utc": available,
                        },
                    )
                )

        findings.extend(self._audit_revision_chain(observations))
        replay_checks, replay_findings = self._audit_replays()
        findings.extend(replay_findings)

        violation_count = sum(1 for item in findings if item.severity == "violation")
        warning_count = sum(1 for item in findings if item.severity == "warning")
        report = {
            "audit_type": "lookahead",
            "generated_at_utc": utc_now_iso(),
            "observation_total": total,
            "observation_sampled": len(sampled),
            "sample_size": sample_size,
            "seed_used": effective_seed,
            "replay_checks": replay_checks,
            "summary": {
                "checked": len(sampled) + len(replay_checks),
                "violations": violation_count,
                "warnings": warning_count,
            },
        }
        parameters = {
            "sample_size": sample_size,
            "seed": seed,
            "seed_used": effective_seed,
        }
        return self._persist(
            audit_type="lookahead",
            parameters=parameters,
            checked_count=len(sampled) + len(replay_checks),
            findings=findings,
            report=report,
            created_by=created_by,
            actor=actor,
            output_dir=output_dir,
        )

    # ------------------------------------------------------------------ queries
    def get_job(self, audit_job_id: str) -> AuditJob:
        row = self.conn.execute(
            "SELECT * FROM audit_jobs WHERE audit_job_id = ?", (audit_job_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"审计任务不存在: {audit_job_id}")
        return AuditJob(**dict(row))

    def list_jobs(
        self, *, audit_type: str | None = None, limit: int = 100
    ) -> list[AuditJob]:
        if audit_type is None:
            rows = self.conn.execute(
                "SELECT * FROM audit_jobs ORDER BY created_at_utc DESC, audit_job_id "
                "LIMIT ?",
                (int(limit),),
            ).fetchall()
        else:
            if audit_type not in {"quality", "lookahead"}:
                raise ValidationError(f"audit_type 取值非法: {audit_type!r}")
            rows = self.conn.execute(
                "SELECT * FROM audit_jobs WHERE audit_type = ? "
                "ORDER BY created_at_utc DESC, audit_job_id LIMIT ?",
                (audit_type, int(limit)),
            ).fetchall()
        return [AuditJob(**dict(row)) for row in rows]

    def list_results(self, audit_job_id: str) -> list[AuditResult]:
        self.get_job(audit_job_id)
        rows = self.conn.execute(
            "SELECT * FROM audit_results WHERE audit_job_id = ? "
            "ORDER BY severity, rule_code, audit_result_id",
            (audit_job_id,),
        ).fetchall()
        return [AuditResult(**dict(row)) for row in rows]

    def export_report(self, audit_job_id: str, target_path: Path | str) -> Path:
        job = self.get_job(audit_job_id)
        results = self.list_results(audit_job_id)
        payload = {
            "job": asdict(job),
            "report": json.loads(job.report_json),
            "results": [
                {
                    "audit_result_id": item.audit_result_id,
                    "severity": item.severity,
                    "rule_code": item.rule_code,
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "detail": json.loads(item.detail_json),
                    "created_at_utc": item.created_at_utc,
                }
                for item in results
            ],
        }
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return target

    # ------------------------------------------------------------------ internals
    def _indicator_quality(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT i.indicator_id, i.indicator_code, i.indicator_name, i.layer, i.status, "
            "COUNT(o.observation_id) AS observation_count, "
            "COUNT(DISTINCT o.observation_period_start) AS period_count, "
            "MIN(o.observation_period_start) AS earliest_period, "
            "MAX(o.observation_period_end) AS latest_period, "
            "COALESCE(SUM(CASE WHEN o.observation_id IS NOT NULL "
            "AND o.release_time_utc IS NULL THEN 1 ELSE 0 END), 0) "
            "AS missing_release_time, "
            "COALESCE(SUM(CASE WHEN o.observation_id IS NOT NULL "
            "AND o.quality_status <> 'normal' THEN 1 ELSE 0 END), 0) "
            "AS non_normal_count, "
            "COUNT(DISTINCT o.vintage_time_utc) AS vintage_count, "
            "COALESCE(SUM(CASE WHEN o.supersedes_observation_id IS NOT NULL THEN 1 ELSE 0 END), 0) "
            "AS revision_count, "
            "ROUND(AVG(julianday(o.available_time_utc) - julianday(o.release_time_utc)), 6) "
            "AS avg_release_delay_days, "
            "MAX(o.available_time_utc) AS latest_available "
            "FROM indicators i LEFT JOIN observations o ON o.indicator_id = i.indicator_id "
            "GROUP BY i.indicator_id ORDER BY i.layer, i.indicator_code"
        ).fetchall()
        return [dict(row) for row in rows]

    def _quality_check_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS total FROM data_quality_checks GROUP BY status"
        ).fetchall()
        return {row["status"]: int(row["total"]) for row in rows}

    def _audit_revision_chain(self, observations: Sequence[Any]) -> list[_Finding]:
        findings: list[_Finding] = []
        by_id = {row["observation_id"]: row for row in observations}
        for row in observations:
            previous_id = row["supersedes_observation_id"]
            if previous_id is None:
                continue
            previous = by_id.get(previous_id)
            if previous is None:
                findings.append(
                    _Finding(
                        "violation",
                        "missing_superseded_observation",
                        "observation",
                        row["observation_id"],
                        {"superseded_observation_id": previous_id},
                    )
                )
                continue
            if previous["vintage_time_utc"] >= row["vintage_time_utc"]:
                findings.append(
                    _Finding(
                        "violation",
                        "revision_vintage_order",
                        "observation",
                        row["observation_id"],
                        {
                            "indicator_code": row["indicator_code"],
                            "previous_vintage_time_utc": previous["vintage_time_utc"],
                            "vintage_time_utc": row["vintage_time_utc"],
                        },
                    )
                )
            revision = self.conn.execute(
                "SELECT COUNT(*) FROM observation_revisions WHERE observation_id = ?",
                (row["observation_id"],),
            ).fetchone()
            if not revision or int(revision[0]) == 0:
                findings.append(
                    _Finding(
                        "warning",
                        "missing_revision_record",
                        "observation",
                        row["observation_id"],
                        {"indicator_code": row["indicator_code"]},
                    )
                )
        return findings

    def _audit_replays(self) -> tuple[list[dict[str, Any]], list[_Finding]]:
        jobs = self.conn.execute(
            "SELECT r.replay_job_id, r.dataset_version_id, r.as_of_utc, "
            "r.replay_result_hash, r.row_count, r.snapshot_path, v.status AS version_status "
            "FROM replay_jobs r "
            "JOIN dataset_versions v ON v.dataset_version_id = r.dataset_version_id "
            "ORDER BY r.created_at_utc, r.replay_job_id"
        ).fetchall()
        checks: list[dict[str, Any]] = []
        findings: list[_Finding] = []
        for job in jobs:
            rows, recomputed = self.replay.preview(
                job["dataset_version_id"], as_of=job["as_of_utc"]
            )
            matches = recomputed == job["replay_result_hash"] and len(rows) == job["row_count"]
            checks.append(
                {
                    "replay_job_id": job["replay_job_id"],
                    "dataset_version_id": job["dataset_version_id"],
                    "version_status": job["version_status"],
                    "as_of_utc": job["as_of_utc"],
                    "row_count": job["row_count"],
                    "recomputed_row_count": len(rows),
                    "stored_hash": job["replay_result_hash"],
                    "recomputed_hash": recomputed,
                    "matches": matches,
                }
            )
            if not matches:
                severity = (
                    "warning"
                    if job["version_status"] in {"draft", "superseded"}
                    else "violation"
                )
                findings.append(
                    _Finding(
                        severity,
                        "replay_mismatch",
                        "replay_job",
                        job["replay_job_id"],
                        {
                            "stored_hash": job["replay_result_hash"],
                            "recomputed_hash": recomputed,
                            "stored_row_count": job["row_count"],
                            "recomputed_row_count": len(rows),
                        },
                    )
                )
            snapshot = job["snapshot_path"]
            if snapshot and not Path(snapshot).exists():
                findings.append(
                    _Finding(
                        "warning",
                        "replay_snapshot_missing",
                        "replay_job",
                        job["replay_job_id"],
                        {"snapshot_path": snapshot},
                    )
                )
        return checks, findings

    def _persist(
        self,
        *,
        audit_type: str,
        parameters: dict[str, Any],
        checked_count: int,
        findings: list[_Finding],
        report: dict[str, Any],
        created_by: str,
        actor: str | None,
        output_dir: Path | str | None = None,
    ) -> AuditRun:
        creator = _text("created_by", created_by)
        violations = sum(1 for item in findings if item.severity == "violation")
        warnings = sum(1 for item in findings if item.severity == "warning")
        report = {
            **report,
            "summary": {
                "checked": checked_count,
                "violations": violations,
                "warnings": warnings,
            },
        }
        job_id = _new_id("aud")
        now = utc_now_iso()
        target_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        report_path = target_dir / f"{job_id}.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        with self.conn:
            self.conn.execute(
                "INSERT INTO audit_jobs (audit_job_id, audit_type, parameters_json, "
                "checked_count, violation_count, warning_count, report_json, "
                "report_path, created_by, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    audit_type,
                    json.dumps(parameters, ensure_ascii=False, sort_keys=True),
                    checked_count,
                    violations,
                    warnings,
                    json.dumps(report, ensure_ascii=False, sort_keys=True),
                    str(report_path),
                    creator,
                    now,
                ),
            )
            for finding in findings:
                self.conn.execute(
                    "INSERT INTO audit_results (audit_result_id, audit_job_id, severity, "
                    "rule_code, entity_type, entity_id, detail_json, created_at_utc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _new_id("aur"),
                        job_id,
                        finding.severity,
                        finding.rule_code,
                        finding.entity_type,
                        finding.entity_id,
                        json.dumps(finding.detail, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
            self.conn.execute(
                "INSERT INTO operation_logs (entity_type, entity_id, action, actor, "
                "detail_json, created_at_utc) VALUES ('audit_job', ?, 'run', ?, ?, ?)",
                (
                    job_id,
                    _text("actor", actor or creator),
                    json.dumps(
                        {
                            "audit_type": audit_type,
                            "violations": violations,
                            "warnings": warnings,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                ),
            )
        return AuditRun(
            job=self.get_job(job_id),
            results=tuple(self.list_results(job_id)),
            report=report,
        )