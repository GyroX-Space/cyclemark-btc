"""Indicator dictionary, data-source registry, and source mapping.

All governance rules for P0-1 are enforced here and mirrored by database
constraints, so that direct SQL cannot bypass them.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any

from .constants import (
    INDICATOR_STATUS_TRANSITIONS,
    SOURCE_STATUS_TRANSITIONS,
    IndicatorStatus,
    Layer,
    SourceRole,
    SourceStatus,
    SourceType,
    UpdateMethod,
)
from .db import Database
from .models import (
    INDICATOR_COLUMNS,
    SOURCE_COLUMNS,
    DataSource,
    Indicator,
    IndicatorSourceLink,
    IndicatorVersion,
    OperationLog,
)
from .timeutils import TimeFormatError, to_utc_iso, utc_now_iso


class RegistryError(Exception):
    """Base class for CMCI registry errors."""


class ValidationError(RegistryError, ValueError):
    """A field violates a governance rule."""


class NotFoundError(RegistryError, LookupError):
    """The requested entity does not exist."""


class ConflictError(RegistryError):
    """The change conflicts with existing governance records."""


class StateTransitionError(RegistryError):
    """A status transition is not allowed."""


_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_TIMEZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-/]*$")

_INDICATOR_UPDATABLE = frozenset(INDICATOR_COLUMNS) - {
    "indicator_id",
    "indicator_code",
    "status",
    "version",
    "created_at_utc",
    "updated_at_utc",
}

_INSERT_INDICATOR_SQL = "INSERT INTO indicators ({}) VALUES ({})".format(
    ", ".join(INDICATOR_COLUMNS),
    ", ".join("?" for _ in INDICATOR_COLUMNS),
)
_UPDATE_INDICATOR_SQL = "UPDATE indicators SET {} WHERE indicator_id = ?".format(
    ", ".join(f"{column} = ?" for column in INDICATOR_COLUMNS if column != "indicator_id")
)
_SNAPSHOT_INDICATOR_SQL = (
    "INSERT INTO indicator_versions ({}, superseded_at_utc, change_reason, changed_by) "
    "VALUES ({})"
).format(
    ", ".join(INDICATOR_COLUMNS),
    ", ".join("?" for _ in range(len(INDICATOR_COLUMNS) + 3)),
)
_INSERT_SOURCE_SQL = "INSERT INTO data_sources ({}) VALUES ({})".format(
    ", ".join(SOURCE_COLUMNS),
    ", ".join("?" for _ in SOURCE_COLUMNS),
)
_UPDATE_SOURCE_SQL = "UPDATE data_sources SET {} WHERE source_id = ?".format(
    ", ".join(f"{column} = ?" for column in SOURCE_COLUMNS if column != "source_id")
)


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
    stripped = value.strip()
    return stripped or None


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


def _timestamp(name: str, value: Any) -> str | None:
    try:
        return to_utc_iso(value, field=name)
    except TimeFormatError as exc:
        raise ValidationError(str(exc)) from exc


class Registry:
    """Append-oriented registry with versioned indicator definitions."""

    def __init__(self, database: Database | str | None = None) -> None:
        if isinstance(database, Database):
            self.db = database
        else:
            self.db = Database(database or ":memory:")
        self.conn = self.db.conn

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ indicators
    def register_indicator(
        self,
        *,
        code: str,
        name: str,
        description: str,
        layer: Layer | str,
        category: str,
        unit: str,
        frequency: str,
        timezone: str,
        data_type: str,
        source_policy: str,
        update_method: UpdateMethod | str,
        revision_policy: str,
        quality_policy: str,
        sub_category: str | None = None,
        history_start: str | None = None,
        history_end: str | None = None,
        license_note: str | None = None,
        usage_partition_policy: str | None = None,
        partition_scope: str | None = None,
        partition_notes: str | None = None,
        status: IndicatorStatus | str = IndicatorStatus.CANDIDATE,
        actor: str = "system",
    ) -> Indicator:
        status_value = _choice("status", status, IndicatorStatus)
        if status_value != IndicatorStatus.CANDIDATE.value:
            raise ValidationError("新登记指标必须处于 candidate 状态；启用请调用 set_indicator_status")

        now = utc_now_iso()
        payload: dict[str, Any] = {
            "indicator_id": _new_id("ind"),
            "indicator_code": code,
            "indicator_name": name,
            "description": description,
            "layer": layer,
            "category": category,
            "sub_category": sub_category,
            "unit": unit,
            "frequency": frequency,
            "timezone": timezone,
            "data_type": data_type,
            "source_policy": source_policy,
            "update_method": update_method,
            "revision_policy": revision_policy,
            "history_start": history_start,
            "history_end": history_end,
            "quality_policy": quality_policy,
            "license_note": license_note,
            "usage_partition_policy": usage_partition_policy,
            "partition_scope": partition_scope,
            "partition_notes": partition_notes,
            "status": status_value,
            "version": 1,
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        values = self._normalize_indicator(payload)
        actor_value = _text("actor", actor)
        try:
            with self.conn:
                self.conn.execute(
                    _INSERT_INDICATOR_SQL, [values[column] for column in INDICATOR_COLUMNS]
                )
                self._log(
                    "indicator",
                    values["indicator_id"],
                    "register",
                    actor_value,
                    {"indicator_code": values["indicator_code"], "layer": values["layer"]},
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ConflictError(f"指标代码已存在: {code}") from exc
            raise ValidationError(f"指标登记失败，违反数据库约束: {exc}") from exc
        return self.get_indicator(code)

    def update_indicator(
        self,
        indicator_code: str,
        *,
        actor: str,
        reason: str,
        **changes: Any,
    ) -> Indicator:
        unknown = set(changes) - _INDICATOR_UPDATABLE
        if unknown:
            raise ValidationError(f"不可更新的字段: {', '.join(sorted(unknown))}")
        if not changes:
            raise ValidationError("没有需要更新的字段")

        row = self._indicator_row(indicator_code)
        if "layer" in changes and _choice("layer", changes["layer"], Layer) != row["layer"]:
            raise ValidationError("指标层级不可修改；层级变化请登记新指标")

        payload = {column: row[column] for column in INDICATOR_COLUMNS}
        payload.update(changes)
        values = self._normalize_indicator(payload)
        return self._persist_indicator_update(
            row,
            values,
            actor=_text("actor", actor),
            reason=_text("reason", reason),
            action="update",
            detail={"changed_fields": sorted(changes)},
        )

    def set_indicator_status(
        self,
        indicator_code: str,
        status: IndicatorStatus | str,
        *,
        actor: str,
        reason: str,
    ) -> Indicator:
        row = self._indicator_row(indicator_code)
        target = _choice("status", status, IndicatorStatus)
        allowed = INDICATOR_STATUS_TRANSITIONS.get(row["status"], frozenset())
        if target not in allowed:
            raise StateTransitionError(f"指标状态不允许从 {row['status']} 变更为 {target}")

        payload = {column: row[column] for column in INDICATOR_COLUMNS}
        payload["status"] = target
        values = self._normalize_indicator(payload)
        return self._persist_indicator_update(
            row,
            values,
            actor=_text("actor", actor),
            reason=_text("reason", reason),
            action="status_change",
            detail={"from": row["status"], "to": target},
        )

    def get_indicator(self, indicator_code: str) -> Indicator:
        return Indicator.from_row(self._indicator_row(indicator_code))

    def list_indicators(
        self,
        *,
        layer: Layer | str | None = None,
        status: IndicatorStatus | str | None = None,
    ) -> list[Indicator]:
        clauses: list[str] = []
        params: list[Any] = []
        if layer is not None:
            clauses.append("layer = ?")
            params.append(_choice("layer", layer, Layer))
        if status is not None:
            clauses.append("status = ?")
            params.append(_choice("status", status, IndicatorStatus))
        query = "SELECT * FROM indicators"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY layer, indicator_code"
        rows = self.conn.execute(query, params).fetchall()
        return [Indicator.from_row(row) for row in rows]

    def indicator_versions(self, indicator_code: str) -> list[IndicatorVersion]:
        row = self._indicator_row(indicator_code)
        rows = self.conn.execute(
            "SELECT * FROM indicator_versions WHERE indicator_id = ? ORDER BY version",
            (row["indicator_id"],),
        ).fetchall()
        return [
            IndicatorVersion(
                version=version_row["version"],
                superseded_at_utc=version_row["superseded_at_utc"],
                change_reason=version_row["change_reason"],
                changed_by=version_row["changed_by"],
                snapshot=Indicator.from_row(version_row),
            )
            for version_row in rows
        ]

    # ------------------------------------------------------------------ data sources
    def register_source(
        self,
        *,
        source_name: str,
        provider: str,
        source_type: SourceType | str,
        access_method: str,
        base_url: str | None = None,
        auth_type: str | None = None,
        license_type: str | None = None,
        update_frequency: str | None = None,
        historical_coverage: str | None = None,
        revision_support: bool = False,
        reliability_grade: str | None = None,
        status: SourceStatus | str = SourceStatus.PENDING_REVIEW,
        notes: str | None = None,
        actor: str = "system",
    ) -> DataSource:
        now = utc_now_iso()
        payload: dict[str, Any] = {
            "source_id": _new_id("src"),
            "source_name": source_name,
            "provider": provider,
            "source_type": source_type,
            "base_url": base_url,
            "access_method": access_method,
            "auth_type": auth_type,
            "license_type": license_type,
            "update_frequency": update_frequency,
            "historical_coverage": historical_coverage,
            "revision_support": revision_support,
            "reliability_grade": reliability_grade,
            "status": status,
            "notes": notes,
            "version": 1,
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        values = self._normalize_source(payload)
        with self.conn:
            self.conn.execute(_INSERT_SOURCE_SQL, [values[column] for column in SOURCE_COLUMNS])
            self._log(
                "data_source",
                values["source_id"],
                "register",
                _text("actor", actor),
                {"source_name": values["source_name"]},
            )
        return self.get_source(values["source_id"])

    def get_source(self, source_id: str) -> DataSource:
        row = self.conn.execute(
            "SELECT * FROM data_sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"数据源不存在: {source_id}")
        return DataSource.from_row(row)

    def list_sources(self, *, status: SourceStatus | str | None = None) -> list[DataSource]:
        if status is not None:
            rows = self.conn.execute(
                "SELECT * FROM data_sources WHERE status = ? ORDER BY source_name",
                (_choice("status", status, SourceStatus),),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM data_sources ORDER BY source_name"
            ).fetchall()
        return [DataSource.from_row(row) for row in rows]

    def set_source_status(
        self,
        source_id: str,
        status: SourceStatus | str,
        *,
        actor: str,
        reason: str,
    ) -> DataSource:
        row = self.conn.execute(
            "SELECT * FROM data_sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"数据源不存在: {source_id}")
        target = _choice("status", status, SourceStatus)
        allowed = SOURCE_STATUS_TRANSITIONS.get(row["status"], frozenset())
        if target not in allowed:
            raise StateTransitionError(f"数据源状态不允许从 {row['status']} 变更为 {target}")

        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                "UPDATE data_sources SET status = ?, version = ?, updated_at_utc = ? "
                "WHERE source_id = ?",
                (target, int(row["version"]) + 1, now, source_id),
            )
            self._log(
                "data_source",
                source_id,
                "status_change",
                _text("actor", actor),
                {"from": row["status"], "to": target, "reason": _text("reason", reason)},
            )
        return self.get_source(source_id)

    # ------------------------------------------------------------------ mappings
    def link_source(
        self,
        indicator_code: str,
        source_id: str,
        *,
        role: SourceRole | str = SourceRole.PRIMARY,
        effective_from: str | None = None,
        notes: str | None = None,
        actor: str = "system",
    ) -> IndicatorSourceLink:
        indicator = self.get_indicator(indicator_code)
        self.get_source(source_id)
        role_value = _choice("role", role, SourceRole)
        effective = _timestamp("effective_from", effective_from) or utc_now_iso()
        mapping_id = _new_id("map")
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO indicator_sources (mapping_id, indicator_id, source_id, role, "
                    "notes, effective_from_utc, effective_to_utc, created_at_utc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        mapping_id,
                        indicator.indicator_id,
                        source_id,
                        role_value,
                        _optional_text("notes", notes),
                        effective,
                        None,
                        utc_now_iso(),
                    ),
                )
                self._log(
                    "indicator_source",
                    mapping_id,
                    "link",
                    _text("actor", actor),
                    {
                        "indicator_code": indicator_code,
                        "source_id": source_id,
                        "role": role_value,
                    },
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ConflictError(
                    f"指标 {indicator_code} 已存在启用的主来源，请先关闭旧映射"
                ) from exc
            raise ValidationError(f"来源映射失败，违反数据库约束: {exc}") from exc
        return self._link_row(mapping_id)

    def close_source_link(
        self,
        mapping_id: str,
        *,
        effective_to: str | None = None,
        actor: str = "system",
    ) -> IndicatorSourceLink:
        row = self.conn.execute(
            "SELECT * FROM indicator_sources WHERE mapping_id = ?", (mapping_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"来源映射不存在: {mapping_id}")
        if row["effective_to_utc"] is not None:
            raise ConflictError(f"来源映射已关闭: {mapping_id}")

        closing = _timestamp("effective_to", effective_to) or utc_now_iso()
        if closing < row["effective_from_utc"]:
            raise ValidationError("effective_to 不能早于 effective_from")

        with self.conn:
            self.conn.execute(
                "UPDATE indicator_sources SET effective_to_utc = ? WHERE mapping_id = ?",
                (closing, mapping_id),
            )
            self._log(
                "indicator_source",
                mapping_id,
                "close",
                _text("actor", actor),
                {"effective_to_utc": closing},
            )
        return self._link_row(mapping_id)

    def list_indicator_sources(
        self, indicator_code: str, *, active_only: bool = False
    ) -> list[IndicatorSourceLink]:
        indicator = self.get_indicator(indicator_code)
        query = (
            "SELECT s.*, d.source_name AS source_name "
            "FROM indicator_sources s "
            "JOIN data_sources d ON d.source_id = s.source_id "
            "WHERE s.indicator_id = ?"
        )
        if active_only:
            query += " AND s.effective_to_utc IS NULL"
        query += " ORDER BY s.effective_from_utc, s.mapping_id"
        rows = self.conn.execute(query, (indicator.indicator_id,)).fetchall()
        return [self._link_from_row(row) for row in rows]

    # ------------------------------------------------------------------ audit log
    def list_operation_logs(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[OperationLog]:
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        query = "SELECT * FROM operation_logs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY log_id DESC LIMIT ?"
        params.append(int(limit))
        rows = self.conn.execute(query, params).fetchall()
        return [
            OperationLog(
                log_id=row["log_id"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                action=row["action"],
                actor=row["actor"],
                detail_json=row["detail_json"],
                created_at_utc=row["created_at_utc"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ internals
    def _indicator_row(self, indicator_code: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM indicators WHERE indicator_code = ?", (indicator_code,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"指标不存在: {indicator_code}")
        return row

    def _persist_indicator_update(
        self,
        row: sqlite3.Row,
        values: dict[str, Any],
        *,
        actor: str,
        reason: str,
        action: str,
        detail: dict[str, Any],
    ) -> Indicator:
        now = utc_now_iso()
        new_values = dict(values)
        new_values["version"] = int(row["version"]) + 1
        new_values["updated_at_utc"] = now

        snapshot_values = [row[column] for column in INDICATOR_COLUMNS]
        snapshot_values.extend([now, reason, actor])
        update_values = [
            new_values[column] for column in INDICATOR_COLUMNS if column != "indicator_id"
        ]
        update_values.append(row["indicator_id"])

        with self.conn:
            self.conn.execute(_SNAPSHOT_INDICATOR_SQL, snapshot_values)
            self.conn.execute(_UPDATE_INDICATOR_SQL, update_values)
            self._log("indicator", row["indicator_id"], action, actor, detail)
        return self.get_indicator(values["indicator_code"])

    def _normalize_indicator(self, payload: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {
            "indicator_id": _text("indicator_id", payload.get("indicator_id")),
        }
        code = _text("indicator_code", payload.get("indicator_code"))
        if not _CODE_RE.match(code):
            raise ValidationError(
                "indicator_code 必须字母开头，只包含字母、数字、下划线或点"
            )
        values["indicator_code"] = code
        values["indicator_name"] = _text("indicator_name", payload.get("indicator_name"))
        values["description"] = _text("description", payload.get("description"))
        values["layer"] = _choice("layer", payload.get("layer"), Layer)
        values["category"] = _text("category", payload.get("category"))
        values["sub_category"] = _optional_text("sub_category", payload.get("sub_category"))
        values["unit"] = _text("unit", payload.get("unit"))
        values["frequency"] = _text("frequency", payload.get("frequency"))
        timezone = _text("timezone", payload.get("timezone"))
        if not _TIMEZONE_RE.match(timezone):
            raise ValidationError(f"timezone 格式非法: {timezone!r}")
        values["timezone"] = timezone
        values["data_type"] = _text("data_type", payload.get("data_type"))
        values["source_policy"] = _text("source_policy", payload.get("source_policy"))
        values["update_method"] = _choice(
            "update_method", payload.get("update_method"), UpdateMethod
        )
        values["revision_policy"] = _text("revision_policy", payload.get("revision_policy"))
        values["history_start"] = _timestamp("history_start", payload.get("history_start"))
        values["history_end"] = _timestamp("history_end", payload.get("history_end"))
        values["quality_policy"] = _text("quality_policy", payload.get("quality_policy"))
        values["license_note"] = _optional_text("license_note", payload.get("license_note"))
        values["usage_partition_policy"] = _optional_text(
            "usage_partition_policy", payload.get("usage_partition_policy")
        )
        values["partition_scope"] = _optional_text(
            "partition_scope", payload.get("partition_scope")
        )
        values["partition_notes"] = _optional_text(
            "partition_notes", payload.get("partition_notes")
        )
        values["status"] = _choice("status", payload.get("status"), IndicatorStatus)
        values["version"] = int(payload.get("version", 1))
        values["created_at_utc"] = _timestamp(
            "created_at_utc", payload.get("created_at_utc")
        )
        values["updated_at_utc"] = _timestamp(
            "updated_at_utc", payload.get("updated_at_utc")
        )

        if values["layer"] == Layer.L5.value and not values["usage_partition_policy"]:
            raise ValidationError(
                "L5 指标必须登记 usage_partition_policy（允许用途及是否需要按研究任务分区）"
            )
        if (
            values["history_start"]
            and values["history_end"]
            and values["history_start"] > values["history_end"]
        ):
            raise ValidationError("history_start 不能晚于 history_end")
        return values

    def _normalize_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {
            "source_id": _text("source_id", payload.get("source_id")),
            "source_name": _text("source_name", payload.get("source_name")),
            "provider": _text("provider", payload.get("provider")),
            "source_type": _choice("source_type", payload.get("source_type"), SourceType),
            "base_url": _optional_text("base_url", payload.get("base_url")),
            "access_method": _text("access_method", payload.get("access_method")),
            "auth_type": _optional_text("auth_type", payload.get("auth_type")),
            "license_type": _optional_text("license_type", payload.get("license_type")),
            "update_frequency": _optional_text(
                "update_frequency", payload.get("update_frequency")
            ),
            "historical_coverage": _optional_text(
                "historical_coverage", payload.get("historical_coverage")
            ),
            "revision_support": 1 if payload.get("revision_support") else 0,
            "reliability_grade": _optional_text(
                "reliability_grade", payload.get("reliability_grade")
            ),
            "status": _choice("status", payload.get("status"), SourceStatus),
            "notes": _optional_text("notes", payload.get("notes")),
            "version": int(payload.get("version", 1)),
            "created_at_utc": _timestamp(
                "created_at_utc", payload.get("created_at_utc")
            ),
            "updated_at_utc": _timestamp(
                "updated_at_utc", payload.get("updated_at_utc")
            ),
        }
        return values

    def _link_row(self, mapping_id: str) -> IndicatorSourceLink:
        row = self.conn.execute(
            "SELECT s.*, d.source_name AS source_name "
            "FROM indicator_sources s "
            "JOIN data_sources d ON d.source_id = s.source_id "
            "WHERE s.mapping_id = ?",
            (mapping_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"来源映射不存在: {mapping_id}")
        return self._link_from_row(row)

    @staticmethod
    def _link_from_row(row: sqlite3.Row) -> IndicatorSourceLink:
        return IndicatorSourceLink(
            mapping_id=row["mapping_id"],
            indicator_id=row["indicator_id"],
            source_id=row["source_id"],
            role=row["role"],
            notes=row["notes"],
            effective_from_utc=row["effective_from_utc"],
            effective_to_utc=row["effective_to_utc"],
            created_at_utc=row["created_at_utc"],
            source_name=row["source_name"],
        )

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