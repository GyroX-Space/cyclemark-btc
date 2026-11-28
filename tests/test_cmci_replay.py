"""P0-4 acceptance tests: historical replay by available_time, snapshots, export."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from cmci import (
    ColumnMapping,
    IngestionService,
    Registry,
    ReplayService,
    ResearchDatasetService,
)
from cmci.registry import NotFoundError, ValidationError

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
        project_code="rp_replay",
        project_name="Replay project",
        description="Replay acceptance project.",
        owner="tester",
    )
    datasets.create_dataset(
        "rp_replay",
        dataset_code="btc_cycle_lab",
        dataset_name="BTC cycle lab",
        description="Replay dataset.",
        created_by="tester",
    )
    version = datasets.create_dataset_version(
        "btc_cycle_lab",
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
    replay = ReplayService(registry)
    try:
        yield {
            "registry": registry,
            "ingestion": ingestion,
            "datasets": datasets,
            "replay": replay,
            "indicator": indicator,
            "macro": macro,
            "source": source,
            "version": version,
            "tmp_path": tmp_path,
        }
    finally:
        registry.close()


def ingest_day(ctx, day: str, value: str, available: str) -> None:
    path = ctx["tmp_path"] / f"prices-{day}-{available.replace(':', '')}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "close", "release"])
        writer.writerow([day, value, available])
    ctx["ingestion"].ingest_file(
        ctx["indicator"].indicator_code,
        ctx["source"].source_id,
        path,
        MAPPING,
        available_time=available,
    )


def seed_observations(ctx) -> None:
    ingest_day(ctx, "2024-01-01", "100", "2024-01-05T00:00:00Z")
    ingest_day(ctx, "2024-01-01", "110", "2024-03-05T00:00:00Z")  # revised vintage
    ingest_day(ctx, "2024-01-02", "200", "2024-02-05T00:00:00Z")
    ingest_day(ctx, "2024-02-10", "300", "2024-02-06T00:00:00Z")  # outside member window


def test_replay_only_uses_data_available_at_as_of(ctx) -> None:
    seed_observations(ctx)
    result = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-02-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )

    assert result.report["row_count"] == 2
    assert all(
        row["available_time_utc"] <= "2024-02-10T00:00:00Z" for row in result.rows
    )
    by_period = {row["observation_period_start"]: row for row in result.rows}
    assert set(by_period) == {"2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"}
    assert by_period["2024-01-01T00:00:00Z"]["value"] == 100.0
    assert by_period["2024-01-01T00:00:00Z"]["vintage_time_utc"] == "2024-01-05T00:00:00Z"
    assert by_period["2024-01-02T00:00:00Z"]["value"] == 200.0
    assert result.report["partition_counts"] == {"validation": 2}
    assert result.report["dataset_code"] == "btc_cycle_lab"
    assert result.report["version_no"] == 1


def test_replay_picks_latest_available_vintage(ctx) -> None:
    seed_observations(ctx)
    result = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-03-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    by_period = {row["observation_period_start"]: row for row in result.rows}
    assert by_period["2024-01-01T00:00:00Z"]["value"] == 110.0
    assert by_period["2024-01-01T00:00:00Z"]["vintage_time_utc"] == "2024-03-05T00:00:00Z"
    assert len(result.rows) == 2


def test_replay_before_any_release_returns_nothing(ctx) -> None:
    seed_observations(ctx)
    result = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-01-01T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    assert result.rows == ()
    assert result.job.row_count == 0
    assert result.report["members_without_data"][0]["indicator_code"] == "btc_spot_close_usd"
    assert Path(result.job.snapshot_path).exists()


def test_replay_respects_member_window(ctx) -> None:
    seed_observations(ctx)
    result = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-12-31T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    periods = {row["observation_period_start"] for row in result.rows}
    assert "2024-02-10T00:00:00Z" not in periods
    assert periods == {"2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"}


def test_snapshot_is_deterministic_and_exportable(ctx) -> None:
    seed_observations(ctx)
    first = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-03-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out-a",
    )
    second = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-03-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out-b",
    )

    assert first.job.replay_result_hash == second.job.replay_result_hash
    assert len(first.job.replay_result_hash) == 64
    first_path = Path(first.job.snapshot_path)
    second_path = Path(second.job.snapshot_path)
    assert first_path.read_text(encoding="utf-8") == second_path.read_text(
        encoding="utf-8"
    )

    with first_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert set(reader.fieldnames or []) >= {
        "observation_period_start",
        "release_time_utc",
        "available_time_utc",
        "vintage_time_utc",
        "source_id",
        "usage_partition",
        "dataset_version_id",
    }
    assert all(row["usage_partition"] == "validation" for row in rows)

    exported = ctx["replay"].export_snapshot(
        first.job.replay_job_id, ctx["tmp_path"] / "export" / "copy.csv"
    )
    assert exported.read_text(encoding="utf-8") == first_path.read_text(encoding="utf-8")


def test_known_future_events_are_returned_separately(ctx) -> None:
    seed_observations(ctx)
    conn = ctx["registry"].conn
    for event_id, known, effective in (
        ("evt_known", "2023-12-01T00:00:00Z", "2024-04-20T00:00:00Z"),
        ("evt_unknown", "2024-06-01T00:00:00Z", "2024-08-01T00:00:00Z"),
    ):
        conn.execute(
            "INSERT INTO known_future_events (event_id, event_type, event_name, "
            "event_known_time_utc, event_effective_time_utc, event_source, "
            "known_future_event, notes, created_at_utc) "
            "VALUES (?, 'halving', 'BTC halving', ?, ?, 'test', 1, NULL, ?)",
            (event_id, known, effective, known),
        )

    result = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-02-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    assert [event["event_id"] for event in result.known_future_events] == ["evt_known"]
    assert result.report["known_future_event_count"] == 1
    assert all(row["observation_id"] for row in result.rows)


def test_member_without_data_is_reported(ctx) -> None:
    seed_observations(ctx)
    ctx["datasets"].add_member(
        ctx["version"].dataset_version_id,
        indicator_code=ctx["macro"].indicator_code,
        usage_partition="not_applicable",
        time_start="2024-01-01",
        time_end="2024-01-31",
    )
    result = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-03-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    missing = [item["indicator_code"] for item in result.report["members_without_data"]]
    assert missing == ["us_fed_balance_sheet"]
    assert result.report["member_count"] == 2


def test_replay_sealed_version_and_version_selection(ctx) -> None:
    seed_observations(ctx)
    sealed = ctx["datasets"].seal_version(
        ctx["version"].dataset_version_id, actor="tester", reason="formal evaluation"
    )
    by_version = ctx["replay"].replay_dataset(
        "btc_cycle_lab",
        version_no=1,
        as_of="2024-03-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    assert by_version.report["version_no"] == 1
    assert by_version.job.dataset_version_id == sealed.dataset_version_id

    successor = ctx["datasets"].create_dataset_version(
        "btc_cycle_lab",
        time_start="2024-01-01",
        time_end="2024-12-31",
        change_reason="reuse after evaluation",
        created_by="tester",
        replaces_version_id=sealed.dataset_version_id,
    )
    latest = ctx["replay"].replay_dataset(
        "btc_cycle_lab",
        as_of="2024-03-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    assert latest.report["version_no"] == 2
    assert latest.job.dataset_version_id == successor.dataset_version_id
    assert latest.rows == ()


def test_replay_jobs_are_listed_and_append_only(ctx) -> None:
    seed_observations(ctx)
    result = ctx["replay"].replay(
        ctx["version"].dataset_version_id,
        as_of="2024-03-10T00:00:00Z",
        created_by="tester",
        output_dir=ctx["tmp_path"] / "out",
    )
    jobs = ctx["replay"].list_jobs(dataset_version_id=ctx["version"].dataset_version_id)
    assert [job.replay_job_id for job in jobs] == [result.job.replay_job_id]
    logs = ctx["registry"].list_operation_logs(entity_type="replay_job")
    assert logs[0].action == "replay"

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ctx["registry"].conn.execute(
            "UPDATE replay_jobs SET row_count = 99 WHERE replay_job_id = ?",
            (result.job.replay_job_id,),
        )


def test_invalid_inputs_are_rejected(ctx) -> None:
    with pytest.raises(ValidationError):
        ctx["replay"].replay(
            ctx["version"].dataset_version_id,
            as_of="not-a-time",
            created_by="tester",
            output_dir=ctx["tmp_path"] / "out",
        )
    with pytest.raises(NotFoundError):
        ctx["replay"].resolve_version("missing_dataset")
    with pytest.raises(NotFoundError):
        ctx["replay"].resolve_version("btc_cycle_lab", version_no=9)