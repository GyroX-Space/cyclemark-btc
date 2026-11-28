"""Immutable records returned by the CMCI registry."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

INDICATOR_COLUMNS: tuple[str, ...] = (
    "indicator_id",
    "indicator_code",
    "indicator_name",
    "description",
    "layer",
    "category",
    "sub_category",
    "unit",
    "frequency",
    "timezone",
    "data_type",
    "source_policy",
    "update_method",
    "revision_policy",
    "history_start",
    "history_end",
    "quality_policy",
    "license_note",
    "usage_partition_policy",
    "partition_scope",
    "partition_notes",
    "status",
    "version",
    "created_at_utc",
    "updated_at_utc",
)

SOURCE_COLUMNS: tuple[str, ...] = (
    "source_id",
    "source_name",
    "provider",
    "source_type",
    "base_url",
    "access_method",
    "auth_type",
    "license_type",
    "update_frequency",
    "historical_coverage",
    "revision_support",
    "reliability_grade",
    "status",
    "notes",
    "version",
    "created_at_utc",
    "updated_at_utc",
)


def _row_to_kwargs(row: sqlite3.Row, columns: tuple[str, ...]) -> dict:
    return {column: row[column] for column in columns}


@dataclass(frozen=True, slots=True)
class Indicator:
    indicator_id: str
    indicator_code: str
    indicator_name: str
    description: str
    layer: str
    category: str
    sub_category: str | None
    unit: str
    frequency: str
    timezone: str
    data_type: str
    source_policy: str
    update_method: str
    revision_policy: str
    history_start: str | None
    history_end: str | None
    quality_policy: str
    license_note: str | None
    usage_partition_policy: str | None
    partition_scope: str | None
    partition_notes: str | None
    status: str
    version: int
    created_at_utc: str
    updated_at_utc: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Indicator":
        return cls(**_row_to_kwargs(row, INDICATOR_COLUMNS))


@dataclass(frozen=True, slots=True)
class DataSource:
    source_id: str
    source_name: str
    provider: str
    source_type: str
    base_url: str | None
    access_method: str
    auth_type: str | None
    license_type: str | None
    update_frequency: str | None
    historical_coverage: str | None
    revision_support: int
    reliability_grade: str | None
    status: str
    notes: str | None
    version: int
    created_at_utc: str
    updated_at_utc: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DataSource":
        return cls(**_row_to_kwargs(row, SOURCE_COLUMNS))


@dataclass(frozen=True, slots=True)
class IndicatorVersion:
    """A superseded indicator definition kept for audit."""

    version: int
    superseded_at_utc: str
    change_reason: str
    changed_by: str
    snapshot: Indicator


@dataclass(frozen=True, slots=True)
class IndicatorSourceLink:
    mapping_id: str
    indicator_id: str
    source_id: str
    role: str
    notes: str | None
    effective_from_utc: str
    effective_to_utc: str | None
    created_at_utc: str
    source_name: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchProject:
    project_id: str
    project_code: str
    project_name: str
    description: str
    owner: str
    status: str
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class ResearchDataset:
    dataset_id: str
    project_id: str
    dataset_code: str
    dataset_name: str
    description: str
    current_version_no: int
    status: str
    created_by: str
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    dataset_version_id: str
    dataset_id: str
    version_no: int
    time_start: str
    time_end: str
    status: str
    sealed_at_utc: str | None
    superseded_at_utc: str | None
    replaces_version_id: str | None
    invalidates_independent_validation: bool
    change_reason: str
    partition_hash: str
    created_by: str
    created_at_utc: str

    @property
    def is_sealed(self) -> bool:
        return self.status != "draft"


@dataclass(frozen=True, slots=True)
class DatasetMember:
    member_id: str
    dataset_version_id: str
    indicator_id: str
    usage_partition: str
    time_start: str
    time_end: str
    embargo_before: float
    embargo_after: float
    partition_version: int
    notes: str | None
    created_by: str
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class OperationLog:
    log_id: int
    entity_type: str
    entity_id: str
    action: str
    actor: str
    detail_json: str
    created_at_utc: str