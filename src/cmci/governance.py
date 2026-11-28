"""Indicator governance and source license registration (first-batch rules).

Adds the non-schema parts of the data plan:
- source grade, measurement scope, proxy flag, coverage and license status per
  indicator;
- internal/commercial/redistribution/attribution/retention terms per source;
- actual coverage observed in the database, to be compared with the declared
  coverage status before research use.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .registry import NotFoundError, Registry, ValidationError
from .timeutils import utc_now_iso

SOURCE_GRADES = {"A", "B", "C"}
LICENSE_STATUSES = {"internal_research", "internal_and_commercial", "unknown", "restricted"}
COVERAGE_STATUSES = {
    "full_target_coverage",
    "partial_coverage",
    "unavailable",
    "unknown",
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _choice(name: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise ValidationError(f"{name} 取值非法: {value!r}，允许值: {', '.join(sorted(allowed))}")
    return value


def _bool(name: str, value: Any) -> int:
    if not isinstance(value, bool):
        raise ValidationError(f"{name} 必须是布尔值")
    return int(value)


@dataclass(frozen=True, slots=True)
class IndicatorGovernance:
    governance_id: str
    indicator_id: str
    source_grade: str
    measurement_scope: str
    proxy_flag: bool
    license_status: str
    coverage_status: str
    coverage_start_utc: str | None
    coverage_end_utc: str | None
    notes: str | None
    version: int
    created_at_utc: str
    actor: str


@dataclass(frozen=True, slots=True)
class SourceLicenseTerms:
    license_id: str
    source_id: str
    internal_research_allowed: bool
    commercial_use_allowed: bool
    redistribution_allowed: bool
    attribution_required: bool
    local_retention_allowed: bool
    terms_url: str | None
    notes: str | None
    version: int
    created_at_utc: str
    actor: str


class GovernanceService:
    """Append-only governance records on top of the registry."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.conn = registry.conn

    def register_indicator_governance(
        self,
        indicator_code: str,
        *,
        source_grade: str,
        measurement_scope: str,
        proxy_flag: bool,
        license_status: str,
        coverage_status: str,
        coverage_start: str | None = None,
        coverage_end: str | None = None,
        notes: str | None = None,
        actor: str = "system",
    ) -> IndicatorGovernance:
        indicator = self.registry.get_indicator(indicator_code)
        if not measurement_scope.strip():
            raise ValidationError("measurement_scope 不能为空")
        grade = _choice("source_grade", source_grade, SOURCE_GRADES)
        license_value = _choice("license_status", license_status, LICENSE_STATUSES)
        coverage_value = _choice("coverage_status", coverage_status, COVERAGE_STATUSES)
        previous = self.get_indicator_governance(indicator_code, missing_ok=True)
        version = previous.version + 1 if previous else 1

        governance_id = _new_id("gov")
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                "INSERT INTO indicator_governance (governance_id, indicator_id, source_grade, "
                "measurement_scope, proxy_flag, license_status, coverage_status, "
                "coverage_start_utc, coverage_end_utc, notes, version, created_at_utc, actor) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    governance_id,
                    indicator.indicator_id,
                    grade,
                    measurement_scope.strip(),
                    _bool("proxy_flag", proxy_flag),
                    license_value,
                    coverage_value,
                    coverage_start,
                    coverage_end,
                    notes,
                    version,
                    now,
                    actor,
                ),
            )
            self.registry._log(
                "indicator_governance",
                governance_id,
                "register",
                actor,
                {"indicator_code": indicator_code, "version": version},
            )
        return self.get_indicator_governance(indicator_code)

    def get_indicator_governance(
        self, indicator_code: str, *, missing_ok: bool = False
    ) -> IndicatorGovernance | None:
        indicator = self.registry.get_indicator(indicator_code)
        row = self.conn.execute(
            "SELECT * FROM indicator_governance WHERE indicator_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (indicator.indicator_id,),
        ).fetchone()
        if row is None:
            if missing_ok:
                return None
            raise NotFoundError(f"指标 {indicator_code} 尚未登记治理信息")
        return IndicatorGovernance(
            governance_id=row["governance_id"],
            indicator_id=row["indicator_id"],
            source_grade=row["source_grade"],
            measurement_scope=row["measurement_scope"],
            proxy_flag=bool(row["proxy_flag"]),
            license_status=row["license_status"],
            coverage_status=row["coverage_status"],
            coverage_start_utc=row["coverage_start_utc"],
            coverage_end_utc=row["coverage_end_utc"],
            notes=row["notes"],
            version=row["version"],
            created_at_utc=row["created_at_utc"],
            actor=row["actor"],
        )

    def register_source_license(
        self,
        source_id: str,
        *,
        internal_research_allowed: bool,
        commercial_use_allowed: bool,
        redistribution_allowed: bool,
        attribution_required: bool,
        local_retention_allowed: bool,
        terms_url: str | None = None,
        notes: str | None = None,
        actor: str = "system",
    ) -> SourceLicenseTerms:
        self.registry.get_source(source_id)
        previous = self.get_source_license(source_id, missing_ok=True)
        version = previous.version + 1 if previous else 1

        license_id = _new_id("lic")
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                "INSERT INTO source_license_terms (license_id, source_id, "
                "internal_research_allowed, commercial_use_allowed, redistribution_allowed, "
                "attribution_required, local_retention_allowed, terms_url, notes, version, "
                "created_at_utc, actor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    license_id,
                    source_id,
                    _bool("internal_research_allowed", internal_research_allowed),
                    _bool("commercial_use_allowed", commercial_use_allowed),
                    _bool("redistribution_allowed", redistribution_allowed),
                    _bool("attribution_required", attribution_required),
                    _bool("local_retention_allowed", local_retention_allowed),
                    terms_url,
                    notes,
                    version,
                    now,
                    actor,
                ),
            )
            self.registry._log(
                "source_license_terms",
                license_id,
                "register",
                actor,
                {"source_id": source_id, "version": version},
            )
        return self.get_source_license(source_id)

    def get_source_license(
        self, source_id: str, *, missing_ok: bool = False
    ) -> SourceLicenseTerms | None:
        row = self.conn.execute(
            "SELECT * FROM source_license_terms WHERE source_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        if row is None:
            if missing_ok:
                return None
            raise NotFoundError(f"数据源 {source_id} 尚未登记授权状态")
        return SourceLicenseTerms(
            license_id=row["license_id"],
            source_id=row["source_id"],
            internal_research_allowed=bool(row["internal_research_allowed"]),
            commercial_use_allowed=bool(row["commercial_use_allowed"]),
            redistribution_allowed=bool(row["redistribution_allowed"]),
            attribution_required=bool(row["attribution_required"]),
            local_retention_allowed=bool(row["local_retention_allowed"]),
            terms_url=row["terms_url"],
            notes=row["notes"],
            version=row["version"],
            created_at_utc=row["created_at_utc"],
            actor=row["actor"],
        )

    def actual_coverage(self, indicator_code: str) -> dict[str, Any]:
        indicator = self.registry.get_indicator(indicator_code)
        row = self.conn.execute(
            "SELECT COUNT(*) AS observations, MIN(observation_period_start) AS start_utc, "
            "MAX(observation_period_end) AS end_utc, COUNT(DISTINCT vintage_time_utc) AS vintages, "
            "COUNT(DISTINCT source_id) AS sources "
            "FROM observations WHERE indicator_id = ?",
            (indicator.indicator_id,),
        ).fetchone()
        declared = self.get_indicator_governance(indicator_code, missing_ok=True)
        return {
            "indicator_code": indicator_code,
            "layer": indicator.layer,
            "declared_coverage_status": declared.coverage_status if declared else "unknown",
            "coverage_start_utc": row["start_utc"],
            "coverage_end_utc": row["end_utc"],
            "observation_count": row["observations"],
            "vintage_count": row["vintages"],
            "source_count": row["sources"],
        }