"""P0-5 acceptance tests: quality reporting, look-ahead audit, sampling, export."""

from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from cmci import (
    AuditService,
    ColumnMapping,
    IngestionService,
    Registry,
    ResearchDatasetService,
)
from cmci.registry import ValidationError

MAPPING = ColumnMapping(period_start="date", value="close", release_time="release")


@pytest.fixture()
def ctx(tmp_path: Path):
    registry = Registry(":memory:")
    indicator = registry.register_indicator(
        code="btc_spot_close_usd",
        name="BTC spot close",
        description="Daily BTC close in USD.",
        layer="L5",
        category="market_price",
        unit="USD",
        frequency="daily",
        timezone="UTC",
        data_type="numeric",
        source_policy="test source only",
        update_method="file",
        revision_policy="append new vintage",
        quality_policy="reject empty values",
        usage_partition_policy="training / identification / validation",
    )
    macro = registry.register_indicator(
        code="us_fed_balance_sheet",
        name="Fed balance sheet",
        description="Federal Reserve total assets.",
        layer="L1",
        category="central_bank",
        unit="USD",
        frequency="weekly",
        timezone="UTC",
        data_type="numeric",
        source_policy="test source only",
        update_method="file",
        revision_policy="vintage release",
        quality_policy="prefer vintage data",
    )
    for item in (indicator, macro):
        registry.set_indicator_status(
            item.indicator_code, "active", actor="tester", reason="acceptance"
        )
    source = registry.register_source(
        source_name="Test source",
        provider="Test provider",
        source_type="file",
        access_method="CSV",
        status="active",
    )
    registry.link_source(indicator.indicator_code, source.source_id, role="primary")
    registry.link_source(macro.indicator_code, source.source_id, role="primary")

    ingestion = IngestionService(registry, raw_dir=tmp_path / "raw")
    datasets = ResearchDatasetService(registry)
    datasets.create_project(
        project_code="rp_audit",
        project_name="Audit project",
        description="Audit acceptance project.",
        owner="tester",
    )
    datasets.create_dataset(
        "rp_audit",
        dataset_code="btc_audit",
        dataset_name="BTC audit",
        description="Audit dataset.",
        created_by="tester",
    )
    version = datasets.create_dataset_version(
        "btc_audit",
        time_start="2024-01-01",
        time_end="2024-12-31",
        change_reason="initial version",
        created_by="tester",
    )
    datasets.add_member(
        version.dataset_version_id,
        indicator_code=indicator.indicator_code,
        usage_partition="validation",
        time_start="2024-01-01",
        time_end="2024-01-31",
        actor="tester",
    )
    audit = AuditService(registry)
    try:
        yield {
            "registry": registry,
            "ingestion": ingestion,
            "datasets": datasets,
            "audit": audit,
            "indicator": indicator,
            "macro": macro,
            "source": source,
            "version": version,
            "tmp_path": tmp_path,
        }
    finally:
        registry.close()


def ingest_day(
    ctx, day: str, value: str, available: str, release: str | None = None
) -> None:
    path = ctx["tmp_path"] / f"prices-{day}-{available.replace(':', '')}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "close", "release"])
        writer.writerow([day, value, release if release is not None else day])
    ctx["ingestion"].ingest_file(
        ctx["indicator"].indicator_code,
        ctx["source"].source_id,
        path,
        MAPPING,
        available_time=available,
    )


def insert_observation(ctx, **overrides) -> str:
    observation_id = overrides.get("observation_id", f"obs_{uuid.uuid4().hex[:12]}")
    payload = {
        "observation_id": observation_id,
        "indicator_id": ctx["indicator"].indicator_id,
        "source_id": ctx["source"].source_id,
        "raw_record_id": None,
        "observation_period_start": "2024-01-06T00:00:00Z",
        "observation_period_end": "2024-01-06T00:00:00Z",
        "release_time_utc": "2024-01-10T00:00:00Z",
        "available_time_utc": "2024-01-10T00:00:00Z",
        "vintage_time_utc": "2024-01-10T00:00:00Z",
        "value": 500.0,
        "value_text": None,
        "unit": "USD",
        "timezone": "UTC",
        "quality_status": "normal",
        "time_precision_status": "date_only",
        "revision_id": f"rev_{uuid.uuid4().hex[:12]}",
        "supersedes_observation_id": None,
        "created_at_utc": "2024-01-10T00:00:00Z",
    }
    payload.update(overrides)
    ctx["registry"].conn.execute(
        "INSERT INTO observations ({}) VALUES ({})".format(
            ", ".join(payload), ", ".join("?" for _ in payload)
        ),
        list(payload.values()),
    )
    return observation_id


def test_quality_report_summarises_indicators_and_checks(ctx) -> None:
    ingest_day(ctx, "2024-01-01", "100", "2024-01-05T00:00:00Z", release="2024-01-01")
    ingest_day(ctx, "2024-01-02", "110", "2024-01-04T00:00:00Z", release="2024-01-02")
    ctx["registry"].conn.execute(
        "INSERT INTO data_quality_checks (check_id, observation_id, job_id, indicator_id, "
        "check_type, status, message, created_at_utc) "
        "VALUES ('chk_manual', NULL, NULL, ?, 'unit', 'warning', 'unit mismatch', ?)",
        (ctx["indicator"].indicator_id, "2024-01-06T00:00:00Z"),
    )

    run = ctx["audit"].run_quality_report(
        created_by="tester", output_dir=ctx["tmp_path"] / "audits"
    )
    price = next(
        item
        for item in run.report["indicators"]
        if item["indicator_code"] == "btc_spot_close_usd"
    )
    assert price["observation_count"] == 2
    assert price["avg_release_delay_days"] == 3.0
    assert price["missing_release_time"] == 0
    assert price["vintage_count"] == 2
    assert run.report["quality_check_counts"] == {"warning": 1}
    assert run.job.violation_count == 0
    assert run.job.warning_count == 1
    assert any(
        result.rule_code == "active_indicator_without_data"
        and result.entity_id == ctx["macro"].indicator_id
        for result in run.results
    )
    assert Path(run.job.report_path).exists()

    jobs = ctx["audit"].list_jobs(audit_type="quality")
    assert jobs[0].audit_job_id == run.job.audit_job_id
    logs = ctx["registry"].list_operation_logs(entity_type="audit_job")
    assert logs[0].action == "run"


def test_lookahead_full_scan_clean_data(ctx) -> None:
    ingest_day(ctx, "2024-01-01", "100", "2024-01-05T00:00:00Z")
    ingest_day(ctx, "2024-01-02", "110", "2024-01-05T00:00:00Z")

    run = ctx["audit"].run_lookahead_audit(
        created_by="tester", output_dir=ctx["tmp_path"] / "audits"
    )
    assert run.job.checked_count == 2
    assert run.job.violation_count == 0
    assert run.job.warning_count == 0
    assert run.results == ()
    assert run.report["observation_sampled"] == 2
    assert run.report["seed_used"] is None


def test_lookahead_sampling_is_seeded_and_traceable(ctx) -> None:
    for day in ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"):
        ingest_day(ctx, day, "100", "2024-01-06T00:00:00Z")

    first = ctx["audit"].run_lookahead_audit(
        created_by="tester",
        sample_size=2,
        seed=42,
        output_dir=ctx["tmp_path"] / "audits",
    )
    second = ctx["audit"].run_lookahead_audit(
        created_by="tester",
        sample_size=2,
        seed=42,
        output_dir=ctx["tmp_path"] / "audits",
    )
    assert first.report["observation_sampled"] == 2
    assert first.report["seed_used"] == 42
    assert [item.entity_id for item in first.results] == [
        item.entity_id for item in second.results
    ]
    assert first.job.checked_count == second.job.checked_count

    with pytest.raises(ValidationError):
        ctx["audit"].run_lookahead_audit(created_by="tester", sample_size=0)


def test_lookahead_flags_missing_release_time(ctx) -> None:
    path = ctx["tmp_path"] / "no-release.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "close"])
        writer.writerow(["2024-01-01", "100"])
    ctx["ingestion"].ingest_file(
        ctx["indicator"].indicator_code,
        ctx["source"].source_id,
        path,
        ColumnMapping(period_start="date", value="close"),
        available_time="2024-01-05T00:00:00Z",
    )

    run = ctx["audit"].run_lookahead_audit(
        created_by="tester", output_dir=ctx["tmp_path"] / "audits"
    )
    assert run.job.violation_count == 0
    assert run.job.warning_count == 1
    assert run.results[0].rule_code == "missing_release_time"


def test_lookahead_detects_revision_vintage_order(ctx) -> None:
    ingest_day(ctx, "2024-01-01", "100", "2024-01-05T00:00:00Z")
    ingest_day(ctx, "2024-01-01", "110", "2024-03-05T00:00:00Z")
    rows = ctx["registry"].conn.execute(
        "SELECT observation_id, vintage_time_utc FROM observations "
        "WHERE indicator_id = ? ORDER BY vintage_time_utc DESC",
        (ctx["indicator"].indicator_id,),
    ).fetchall()
    newest_id = rows[0]["observation_id"]
    insert_observation(
        ctx,
        observation_period_start="2024-01-01T00:00:00Z",
        observation_period_end="2024-01-01T00:00:00Z",
        release_time_utc=None,
        available_time_utc="2024-02-01T00:00:00Z",
        vintage_time_utc="2024-02-01T00:00:00Z",
        supersedes_observation_id=newest_id,
        created_at_utc="2024-02-01T00:00:00Z",
    )

    run = ctx["audit"].run_lookahead_audit(
        created_by="tester", output_dir=ctx["tmp_path"] / "audits"
    )
    rules = {result.rule_code for result in run.results}
    assert "revision_vintage_order" in rules
    assert "missing_revision_record" in rules
    assert run.job.violation_count == 1


def test_lookahead_verifies_replay_and_detects_backfill(ctx) -> None:
    ingest_day(ctx, "2024-01-01", "100", "2024-01-05T00:00:00Z")
    ctx["datasets"].seal_version(
        ctx["version"].dataset_version_id, actor="tester", reason="formal evaluation"
    )
    ctx["audit"].replay.replay(
        ctx["version"].dataset_version_id,
        as_of="2024-02-01T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "replays",
    )

    clean = ctx["audit"].run_lookahead_audit(
        created_by="tester", output_dir=ctx["tmp_path"] / "audits"
    )
    assert clean.report["replay_checks"][0]["matches"] is True
    assert clean.job.violation_count == 0

    # A backfilled observation with an old available_time changes the historical
    # result even though the dataset version is sealed.
    insert_observation(ctx)
    drift = ctx["audit"].run_lookahead_audit(
        created_by="tester", output_dir=ctx["tmp_path"] / "audits"
    )
    assert drift.report["replay_checks"][0]["matches"] is False
    violations = [result for result in drift.results if result.severity == "violation"]
    assert [result.rule_code for result in violations] == ["replay_mismatch"]


def test_audit_report_export_and_append_only(ctx) -> None:
    ingest_day(ctx, "2024-01-01", "100", "2024-01-05T00:00:00Z")
    run = ctx["audit"].run_quality_report(
        created_by="tester", output_dir=ctx["tmp_path"] / "audits"
    )
    exported = ctx["audit"].export_report(
        run.job.audit_job_id, ctx["tmp_path"] / "export" / "audit.json"
    )
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["job"]["audit_job_id"] == run.job.audit_job_id
    assert payload["report"]["audit_type"] == "quality"
    assert payload["results"]
    assert payload["results"][0]["severity"] == "warning"

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ctx["registry"].conn.execute(
            "UPDATE audit_jobs SET violation_count = 1 WHERE audit_job_id = ?",
            (run.job.audit_job_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ctx["registry"].conn.execute("DELETE FROM audit_results")