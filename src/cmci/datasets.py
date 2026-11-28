"""Research datasets, dataset versions, and L5 usage partitions.

Governance rules enforced here (mirrored by SQLite constraints/triggers):

- members of one dataset version are immutable; partition changes require a
  new dataset version;
- within one dataset version, two members of the same indicator that carry
  different usage partitions must be time-disjoint and honour the registered
  embargo;
- an L5 indicator member must use training / identification / validation;
- once a version is sealed, its partition hash is frozen and the version can
  only be superseded by a new version; the replacement is flagged as
  invalidating the original independent validation status.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from .constants import DatasetVersionStatus, Layer, UsagePartition
from .models import DatasetMember, DatasetVersion, ResearchDataset, ResearchProject
from .registry import ConflictError, NotFoundError, Registry, ValidationError
from .timeutils import TimeFormatError, to_utc_iso, utc_now_iso

_SECONDS_PER_DAY = 86400.0


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} 不能为空")
    return value.strip()


def _optional_text(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{name} 必须是文本")
    return value.strip() or None


def _choice(name: str, value: Any, enum_cls: type) -> str:
    if isinstance(value, enum_cls):
        return value.value
    if isinstance(value, str):
        try:
            return enum_cls(value).value
        except ValueError:
            allowed = ", ".join(member.value for member in enum_cls)
            raise ValidationError(f"{name} 取值非法: {value!r}，允许值: {allowed}") from None
    raise ValidationError(f"{name} 取值非法: {value!r}")


def _timestamp(name: str, value: Any, *, required: bool = True) -> str | None:
    try:
        normalised = to_utc_iso(value, field=name)
    except TimeFormatError as exc:
        raise ValidationError(str(exc)) from exc
    if normalised is None and required:
        raise ValidationError(f"{name} 不能为空")
    return normalised


def _days(name: str, value: Any) -> float:
    try:
        days = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} 必须是数字（天）") from None
    if days < 0:
        raise ValidationError(f"{name} 不能为负")
    return days


def _parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class PartitionConflict:
    """A pair of same-indicator members whose partition windows are not safe."""

    indicator_id: str
    first_member_id: str
    second_member_id: str
    first_partition: str
    second_partition: str
    overlap_start: str | None
    overlap_end: str | None
    gap_days: float | None
    required_embargo_days: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PartitionConflictError(ConflictError):
    """Raised when a member would create a partition overlap or embargo breach."""

    def __init__(self, conflicts: Sequence[PartitionConflict]) -> None:
        self.conflicts = list(conflicts)
        summary = "；".join(conflict.message for conflict in self.conflicts)
        super().__init__(f"分区冲突: {summary}")


class ResearchDatasetService:
    """Manages research projects, datasets, versions, and partition members."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.conn = registry.conn

    # ------------------------------------------------------------------ projects
    def create_project(
        self,
        *,
        project_code: str,
        project_name: str,
        description: str,
        owner: str,
        actor: str = "system",
    ) -> ResearchProject:
        project_id = _new_id("prj")
        actor_value = _text("actor", actor)
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO research_projects (project_id, project_code, project_name, "
                    "description, owner, status, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        _text("project_code", project_code),
                        _text("project_name", project_name),
                        _text("description", description),
                        _text("owner", owner),
                        "active",
                        utc_now_iso(),
                    ),
                )
                self._log(
                    "research_project",
                    project_id,
                    "create",
                    actor_value,
                    {"project_code": project_code},
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ConflictError(f"研究项目代码已存在: {project_code}") from exc
            raise ValidationError(f"研究项目创建失败: {exc}") from exc
        return self.get_project(project_code)

    def get_project(self, project_code: str) -> ResearchProject:
        row = self.conn.execute(
            "SELECT * FROM research_projects WHERE project_code = ?", (project_code,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"研究项目不存在: {project_code}")
        return ResearchProject(**dict(row))

    def list_projects(self, *, status: str | None = None) -> list[ResearchProject]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM research_projects ORDER BY project_code"
            ).fetchall()
        else:
            if status not in {"active", "archived"}:
                raise ValidationError(f"status 取值非法: {status!r}")
            rows = self.conn.execute(
                "SELECT * FROM research_projects WHERE status = ? ORDER BY project_code",
                (status,),
            ).fetchall()
        return [ResearchProject(**dict(row)) for row in rows]

    # ------------------------------------------------------------------ datasets
    def create_dataset(
        self,
        project_code: str,
        *,
        dataset_code: str,
        dataset_name: str,
        description: str,
        created_by: str,
        actor: str | None = None,
    ) -> ResearchDataset:
        project = self.get_project(project_code)
        dataset_id = _new_id("ds")
        actor_value = _text("actor", actor or created_by)
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO research_datasets (dataset_id, project_id, dataset_code, "
                    "dataset_name, description, current_version_no, status, created_by, "
                    "created_at_utc) VALUES (?, ?, ?, ?, ?, 0, 'draft', ?, ?)",
                    (
                        dataset_id,
                        project.project_id,
                        _text("dataset_code", dataset_code),
                        _text("dataset_name", dataset_name),
                        _text("description", description),
                        _text("created_by", created_by),
                        utc_now_iso(),
                    ),
                )
                self._log(
                    "research_dataset",
                    dataset_id,
                    "create",
                    actor_value,
                    {"dataset_code": dataset_code, "project_code": project_code},
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ConflictError(f"研究数据集代码已存在: {dataset_code}") from exc
            raise ValidationError(f"研究数据集创建失败: {exc}") from exc
        return self.get_dataset(dataset_code)

    def get_dataset(self, dataset_code: str) -> ResearchDataset:
        row = self.conn.execute(
            "SELECT * FROM research_datasets WHERE dataset_code = ?", (dataset_code,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"研究数据集不存在: {dataset_code}")
        return ResearchDataset(**dict(row))

    def list_datasets(
        self, *, project_code: str | None = None, status: str | None = None
    ) -> list[ResearchDataset]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_code is not None:
            clauses.append("p.project_code = ?")
            params.append(project_code)
        if status is not None:
            if status not in {"draft", "active", "archived"}:
                raise ValidationError(f"status 取值非法: {status!r}")
            clauses.append("d.status = ?")
            params.append(status)
        query = (
            "SELECT d.* FROM research_datasets d "
            "JOIN research_projects p ON p.project_id = d.project_id"
        )
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY d.dataset_code"
        rows = self.conn.execute(query, params).fetchall()
        return [ResearchDataset(**dict(row)) for row in rows]

    # ------------------------------------------------------------------ versions
    def create_dataset_version(
        self,
        dataset_code: str,
        *,
        time_start: str,
        time_end: str,
        change_reason: str,
        created_by: str,
        replaces_version_id: str | None = None,
        actor: str | None = None,
    ) -> DatasetVersion:
        dataset = self.get_dataset(dataset_code)
        start = _timestamp("time_start", time_start)
        end = _timestamp("time_end", time_end)
        assert start is not None and end is not None
        if start > end:
            raise ValidationError("time_start 不能晚于 time_end")

        replaced: sqlite3.Row | None = None
        if replaces_version_id is not None:
            replaced = self._version_row(replaces_version_id)
            if replaced["dataset_id"] != dataset.dataset_id:
                raise ValidationError("被替换的版本不属于该数据集")
            if replaced["status"] == DatasetVersionStatus.DRAFT.value:
                raise ValidationError("不能用新版本替换草稿版本；请直接在草稿上登记成员")
            if replaced["status"] == DatasetVersionStatus.SUPERSEDED.value:
                raise ValidationError("被替换的版本已失效，不能再次替换")

        version_no = int(dataset.current_version_no) + 1
        version_id = _new_id("dsv")
        now = utc_now_iso()
        actor_value = _text("actor", actor or created_by)
        invalidates = replaced is not None
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO dataset_versions (dataset_version_id, dataset_id, version_no, "
                    "time_start, time_end, status, sealed_at_utc, superseded_at_utc, "
                    "replaces_version_id, invalidates_independent_validation, change_reason, "
                    "partition_hash, created_by, created_at_utc) "
                    "VALUES (?, ?, ?, ?, ?, 'draft', NULL, NULL, ?, ?, ?, '', ?, ?)",
                    (
                        version_id,
                        dataset.dataset_id,
                        version_no,
                        start,
                        end,
                        replaces_version_id,
                        1 if invalidates else 0,
                        _text("change_reason", change_reason),
                        _text("created_by", created_by),
                        now,
                    ),
                )
                if replaced is not None:
                    self.conn.execute(
                        "UPDATE dataset_versions SET status = 'superseded', "
                        "superseded_at_utc = ? WHERE dataset_version_id = ?",
                        (now, replaces_version_id),
                    )
                self.conn.execute(
                    "UPDATE research_datasets SET current_version_no = ? WHERE dataset_id = ?",
                    (version_no, dataset.dataset_id),
                )
                self._log(
                    "dataset_version",
                    version_id,
                    "create",
                    actor_value,
                    {
                        "dataset_code": dataset_code,
                        "version_no": version_no,
                        "replaces_version_id": replaces_version_id,
                        "invalidates_independent_validation": invalidates,
                    },
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"数据集版本创建失败: {exc}") from exc
        return self.get_version(version_id)

    def get_version(self, dataset_version_id: str) -> DatasetVersion:
        row = self._version_row(dataset_version_id)
        payload = dict(row)
        payload["invalidates_independent_validation"] = bool(
            payload["invalidates_independent_validation"]
        )
        return DatasetVersion(**payload)

    def list_versions(self, dataset_code: str) -> list[DatasetVersion]:
        dataset = self.get_dataset(dataset_code)
        rows = self.conn.execute(
            "SELECT * FROM dataset_versions WHERE dataset_id = ? ORDER BY version_no",
            (dataset.dataset_id,),
        ).fetchall()
        return [
            DatasetVersion(
                **{
                    **dict(row),
                    "invalidates_independent_validation": bool(
                        row["invalidates_independent_validation"]
                    ),
                }
            )
            for row in rows
        ]

    def seal_version(
        self, dataset_version_id: str, *, actor: str, reason: str
    ) -> DatasetVersion:
        version = self.get_version(dataset_version_id)
        if version.status != DatasetVersionStatus.DRAFT.value:
            raise ConflictError(f"数据集版本已封存，无法重复封存: {dataset_version_id}")
        members = self.list_members(dataset_version_id)
        if not members:
            raise ValidationError("数据集版本至少需要登记一个成员后才能封存")
        conflicts = self.check_partition_conflicts(dataset_version_id)
        if conflicts:
            raise PartitionConflictError(conflicts)

        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                "UPDATE dataset_versions SET status = 'sealed', sealed_at_utc = ?, "
                "partition_hash = ? WHERE dataset_version_id = ?",
                (now, _partition_hash(members), dataset_version_id),
            )
            self.conn.execute(
                "UPDATE research_datasets SET status = 'active' "
                "WHERE dataset_id = ? AND status = 'draft'",
                (version.dataset_id,),
            )
            self._log(
                "dataset_version",
                dataset_version_id,
                "seal",
                _text("actor", actor),
                {"reason": _text("reason", reason), "members": len(members)},
            )
        return self.get_version(dataset_version_id)

    # ------------------------------------------------------------------ members
    def add_member(
        self,
        dataset_version_id: str,
        *,
        indicator_code: str,
        usage_partition: UsagePartition | str,
        time_start: str,
        time_end: str,
        embargo_before: float = 0,
        embargo_after: float = 0,
        notes: str | None = None,
        actor: str = "system",
    ) -> DatasetMember:
        version = self.get_version(dataset_version_id)
        if version.status != DatasetVersionStatus.DRAFT.value:
            raise ConflictError(
                "数据集版本已封存，不能新增成员；请创建新的数据集版本"
            )
        indicator = self.registry.get_indicator(indicator_code)
        partition = _choice("usage_partition", usage_partition, UsagePartition)
        if indicator.layer == Layer.L5.value and partition == UsagePartition.NOT_APPLICABLE.value:
            raise ValidationError("L5 指标成员必须登记 training / identification / validation 分区")

        start = _timestamp("time_start", time_start)
        end = _timestamp("time_end", time_end)
        assert start is not None and end is not None
        if start > end:
            raise ValidationError("time_start 不能晚于 time_end")
        if start < version.time_start or end > version.time_end:
            raise ValidationError(
                "成员时间窗口必须位于数据集版本时间范围内 "
                f"[{version.time_start}, {version.time_end}]"
            )
        before = _days("embargo_before", embargo_before)
        after = _days("embargo_after", embargo_after)

        member_id = _new_id("dsm")
        candidate = DatasetMember(
            member_id=member_id,
            dataset_version_id=dataset_version_id,
            indicator_id=indicator.indicator_id,
            usage_partition=partition,
            time_start=start,
            time_end=end,
            embargo_before=before,
            embargo_after=after,
            partition_version=1,
            notes=_optional_text("notes", notes),
            created_by=_text("actor", actor),
            created_at_utc=utc_now_iso(),
        )
        conflicts = _detect_conflicts([*self.list_members(dataset_version_id), candidate])
        if conflicts:
            raise PartitionConflictError(conflicts)

        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO dataset_members (member_id, dataset_version_id, indicator_id, "
                    "usage_partition, time_start, time_end, embargo_before, embargo_after, "
                    "partition_version, notes, created_by, created_at_utc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        member_id,
                        dataset_version_id,
                        indicator.indicator_id,
                        partition,
                        start,
                        end,
                        before,
                        after,
                        1,
                        candidate.notes,
                        candidate.created_by,
                        candidate.created_at_utc,
                    ),
                )
                self._log(
                    "dataset_member",
                    member_id,
                    "add",
                    candidate.created_by,
                    {
                        "dataset_version_id": dataset_version_id,
                        "indicator_code": indicator_code,
                        "usage_partition": partition,
                        "time_start": start,
                        "time_end": end,
                        "embargo_before": before,
                        "embargo_after": after,
                    },
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ConflictError("同一数据集版本已登记相同指标、分区与时间窗口的成员") from exc
            raise ValidationError(f"数据集成员登记失败: {exc}") from exc
        return self._member_row(member_id)

    def list_members(self, dataset_version_id: str) -> list[DatasetMember]:
        rows = self.conn.execute(
            "SELECT * FROM dataset_members WHERE dataset_version_id = ? "
            "ORDER BY indicator_id, time_start, usage_partition",
            (dataset_version_id,),
        ).fetchall()
        return [DatasetMember(**dict(row)) for row in rows]

    def check_partition_conflicts(
        self, dataset_version_id: str
    ) -> list[PartitionConflict]:
        return _detect_conflicts(self.list_members(dataset_version_id))

    # ------------------------------------------------------------------ internals
    def _version_row(self, dataset_version_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM dataset_versions WHERE dataset_version_id = ?",
            (dataset_version_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"数据集版本不存在: {dataset_version_id}")
        return row

    def _member_row(self, member_id: str) -> DatasetMember:
        row = self.conn.execute(
            "SELECT * FROM dataset_members WHERE member_id = ?", (member_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"数据集成员不存在: {member_id}")
        return DatasetMember(**dict(row))

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


def _partition_hash(members: Sequence[DatasetMember]) -> str:
    canonical = sorted(
        (
            member.indicator_id,
            member.usage_partition,
            member.time_start,
            member.time_end,
            member.embargo_before,
            member.embargo_after,
        )
        for member in members
    )
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _detect_conflicts(members: Sequence[DatasetMember]) -> list[PartitionConflict]:
    """Return partition conflicts for one dataset version.

    Two members of the same indicator with different usage partitions must be
    time-disjoint; when they are adjacent, the gap must cover the registered
    embargo on both sides: ``max(earlier.embargo_after, later.embargo_before)``.
    """
    by_indicator: dict[str, list[DatasetMember]] = {}
    for member in members:
        by_indicator.setdefault(member.indicator_id, []).append(member)

    conflicts: list[PartitionConflict] = []
    for indicator_id, group in by_indicator.items():
        ordered = sorted(group, key=lambda item: (item.time_start, item.time_end))
        for index, first in enumerate(ordered):
            first_start = _parse_utc(first.time_start)
            first_end = _parse_utc(first.time_end)
            for second in ordered[index + 1 :]:
                if first.usage_partition == second.usage_partition:
                    continue
                second_start = _parse_utc(second.time_start)
                second_end = _parse_utc(second.time_end)
                required = max(first.embargo_after, second.embargo_before)
                if first_end < second_start:
                    gap_days = (second_start - first_end).total_seconds() / _SECONDS_PER_DAY
                    if gap_days >= required:
                        continue
                    conflicts.append(
                        PartitionConflict(
                            indicator_id=indicator_id,
                            first_member_id=first.member_id,
                            second_member_id=second.member_id,
                            first_partition=first.usage_partition,
                            second_partition=second.usage_partition,
                            overlap_start=None,
                            overlap_end=None,
                            gap_days=round(gap_days, 6),
                            required_embargo_days=required,
                            message=(
                                f"{first.usage_partition} 与 {second.usage_partition} 间隔 "
                                f"{gap_days:.2f} 天，小于所需隔离期 {required:g} 天"
                            ),
                        )
                    )
                    continue
                overlap_start = max(first_start, second_start)
                overlap_end = min(first_end, second_end)
                if overlap_start <= overlap_end:
                    conflicts.append(
                        PartitionConflict(
                            indicator_id=indicator_id,
                            first_member_id=first.member_id,
                            second_member_id=second.member_id,
                            first_partition=first.usage_partition,
                            second_partition=second.usage_partition,
                            overlap_start=overlap_start.isoformat().replace("+00:00", "Z"),
                            overlap_end=overlap_end.isoformat().replace("+00:00", "Z"),
                            gap_days=None,
                            required_embargo_days=required,
                            message=(
                                f"{first.usage_partition} 与 {second.usage_partition} 时间窗口重叠: "
                                f"{overlap_start.date()} ~ {overlap_end.date()}"
                            ),
                        )
                    )
    return conflicts