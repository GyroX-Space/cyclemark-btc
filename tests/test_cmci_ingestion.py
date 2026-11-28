"""P0-2 acceptance tests: raw capture, normalization, revisions, quality, API."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from cmci import ColumnMapping, IngestionService, Registry
from cmci.importers import ImportFailure
from cmci.ingestion import IngestionError

AVAILABLE = "2024-01-05T00:00:00Z"


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
    registry.set_indicator_status(
        indicator.indicator_code, "active", actor="tester", reason="acceptance"
    )
    source = registry.register_source(
        source_name="Test source",
        provider="Test provider",
        source_type="file",
        access_method="CSV",
        status="active",
    )
    registry.link_source(indicator.indicator_code, source.source_id, role="primary")
    service = IngestionService(registry, raw_dir=tmp_path / "raw")
    try:
        yield registry, service, indicator, source
    finally:
        registry.close()


MAPPING = ColumnMapping(period_start="date", value="close", release_time="release")


def write_csv(path: Path, rows: list[list[str]], header: list[str] | None = None) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header or ["date", "close", "release"])
        writer.writerows(rows)
    return path


def fetch_all(registry: Registry, table: str, where: str = "1=1") -> list[sqlite3.Row]:
    return registry.conn.execute(f"SELECT * FROM {table} WHERE {where}").fetchall()


def test_csv_ingestion_stores_raw_and_observations(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    path = write_csv(
        tmp_path / "prices.csv",
        [
            ["2024-01-01", "42000", "2024-01-02"],
            ["2024-01-02", "42500", "2024-01-03"],
            ["2024-01-03", "43000", "2024-01-04"],
        ],
    )

    result = service.ingest_file(
        indicator.indicator_code, source.source_id, path, MAPPING, available_time=AVAILABLE
    )

    assert result.job_status == "succeeded"
    assert result.records_received == 3
    assert result.records_inserted == 3
    assert result.records_updated == 0
    assert result.duplicate_payload is False

    raw = fetch_all(registry, "raw_records")
    assert len(raw) == 1
    assert raw[0]["payload_format"] == "csv"
    assert raw[0]["content_hash"]

    observations = fetch_all(
        registry, "observations", f"indicator_id = '{indicator.indicator_id}'"
    )
    assert len(observations) == 3
    assert {row["available_time_utc"] for row in observations} == {AVAILABLE}
    assert {row["quality_status"] for row in observations} == {"normal"}
    assert all(row["supersedes_observation_id"] is None for row in observations)

    jobs = fetch_all(registry, "ingestion_jobs")
    assert jobs[0]["job_status"] == "succeeded"
    assert jobs[0]["records_inserted"] == 3
    assert jobs[0]["actor"] == "system"


def test_duplicate_payload_is_not_reingested(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    path = write_csv(tmp_path / "prices.csv", [["2024-01-01", "42000", "2024-01-02"]])

    first = service.ingest_file(
        indicator.indicator_code, source.source_id, path, MAPPING, available_time=AVAILABLE
    )
    second = service.ingest_file(
        indicator.indicator_code, source.source_id, path, MAPPING, available_time=AVAILABLE
    )

    assert first.records_inserted == 1
    assert second.duplicate_payload is True
    assert second.records_inserted == 0
    assert len(fetch_all(registry, "raw_records")) == 1
    assert len(fetch_all(registry, "observations")) == 1


def test_revision_appends_new_vintage(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    first = write_csv(tmp_path / "v1.csv", [["2024-01-01", "42000", "2024-01-02"]])
    second = write_csv(tmp_path / "v2.csv", [["2024-01-01", "42100", "2024-01-02"]])

    service.ingest_file(
        indicator.indicator_code, source.source_id, first, MAPPING, available_time=AVAILABLE
    )
    result = service.ingest_file(
        indicator.indicator_code,
        source.source_id,
        second,
        MAPPING,
        available_time="2024-01-06T00:00:00Z",
    )

    assert result.records_updated == 1
    observations = sorted(
        fetch_all(registry, "observations"), key=lambda row: row["vintage_time_utc"]
    )
    assert len(observations) == 2
    old, new = observations
    assert old["value"] == pytest.approx(42000.0)
    assert new["value"] == pytest.approx(42100.0)
    assert new["supersedes_observation_id"] == old["observation_id"]
    assert new["revision_id"] != old["revision_id"]

    revisions = fetch_all(registry, "observation_revisions")
    assert len(revisions) == 2
    assert revisions[-1]["previous_observation_id"] == old["observation_id"]


def test_unchanged_values_are_not_rewritten(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    first = write_csv(tmp_path / "a.csv", [["2024-01-01", "42000", "2024-01-02"]])
    changed_payload = write_csv(
        tmp_path / "b.csv",
        [["2024-01-01", "42000", "2024-01-02"]],
        header=["date", "close", "release", "note"],
    )
    # add a note column value so the raw payload hash differs
    changed_payload.write_text(
        "date,close,release,note\n2024-01-01,42000,2024-01-02,unchanged\n", encoding="utf-8"
    )

    service.ingest_file(
        indicator.indicator_code, source.source_id, first, MAPPING, available_time=AVAILABLE
    )
    result = service.ingest_file(
        indicator.indicator_code,
        source.source_id,
        changed_payload,
        MAPPING,
        available_time="2024-01-06T00:00:00Z",
    )

    assert result.records_unchanged == 1
    assert result.records_inserted == 0
    assert result.records_updated == 0
    assert len(fetch_all(registry, "observations")) == 1


def test_unregistered_source_is_rejected(ctx, tmp_path: Path) -> None:
    registry, service, indicator, _source = ctx
    other = registry.register_source(
        source_name="Other source",
        provider="Other provider",
        source_type="api",
        access_method="REST",
        status="active",
    )
    path = write_csv(tmp_path / "p.csv", [["2024-01-01", "1", "2024-01-02"]])

    with pytest.raises(IngestionError):
        service.ingest_file(
            indicator.indicator_code, other.source_id, path, MAPPING, available_time=AVAILABLE
        )


def test_inactive_indicator_is_rejected(ctx, tmp_path: Path) -> None:
    registry, service, _indicator, source = ctx
    candidate = registry.register_indicator(
        code="candidate_metric",
        name="Candidate",
        description="Not yet approved.",
        layer="L1",
        category="macro",
        unit="index",
        frequency="monthly",
        timezone="UTC",
        data_type="numeric",
        source_policy="test",
        update_method="file",
        revision_policy="append",
        quality_policy="none",
    )
    registry.link_source(candidate.indicator_code, source.source_id, role="primary")
    path = write_csv(tmp_path / "p.csv", [["2024-01-01", "1", "2024-01-02"]])

    with pytest.raises(IngestionError):
        service.ingest_file(
            candidate.indicator_code, source.source_id, path, MAPPING, available_time=AVAILABLE
        )


def test_json_import(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps(
            [
                {"period": "2024-02-01", "v": 44000, "release": "2024-02-02"},
                {"period": "2024-02-02", "v": 44500, "release": "2024-02-03"},
            ]
        ),
        encoding="utf-8",
    )
    mapping = ColumnMapping(period_start="period", value="v", release_time="release")

    result = service.ingest_file(
        indicator.indicator_code,
        source.source_id,
        path,
        mapping,
        available_time="2024-03-01T00:00:00Z",
    )

    assert result.records_inserted == 2
    assert fetch_all(registry, "raw_records")[0]["payload_format"] == "json"


def test_excel_import(ctx, tmp_path: Path) -> None:
    from datetime import datetime

    from openpyxl import Workbook

    registry, service, indicator, source = ctx
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["date", "close", "release"])
    sheet.append([datetime(2024, 3, 1), 45000, datetime(2024, 3, 2)])
    path = tmp_path / "prices.xlsx"
    workbook.save(path)

    result = service.ingest_file(
        indicator.indicator_code,
        source.source_id,
        path,
        MAPPING,
        available_time="2024-12-31T00:00:00Z",
    )

    assert result.records_inserted == 1
    raw = fetch_all(registry, "raw_records")[0]
    assert raw["payload_format"] == "xlsx"
    assert raw["payload_path"]
    assert Path(raw["payload_path"]).exists()


def test_invalid_values_are_rejected_not_filled(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    path = write_csv(
        tmp_path / "bad.csv",
        [["2024-01-01", "42000", "2024-01-02"], ["2024-01-02", "", "2024-01-03"]],
    )

    result = service.ingest_file(
        indicator.indicator_code, source.source_id, path, MAPPING, available_time=AVAILABLE
    )

    assert result.records_inserted == 1
    assert result.records_rejected == 1
    assert result.job_status == "partial"
    jobs = fetch_all(registry, "ingestion_jobs")
    assert json.loads(jobs[0]["error_log"])[0]["row"] == 2


def test_gap_produces_warning_quality_status(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    path = write_csv(
        tmp_path / "gap.csv",
        [["2024-01-01", "42000", "2024-01-02"], ["2024-02-15", "43000", "2024-02-16"]],
    )

    service.ingest_file(
        indicator.indicator_code, source.source_id, path, MAPPING, available_time="2024-03-01T00:00:00Z"
    )

    checks = fetch_all(registry, "data_quality_checks")
    assert any(check["check_type"] == "gap" for check in checks)
    statuses = {row["quality_status"] for row in fetch_all(registry, "observations")}
    assert "warning" in statuses


def test_api_framework_ingests_json_payload(ctx) -> None:
    _registry, service, indicator, source = ctx
    mapping = ColumnMapping(period_start="period", value="v", release_time="release")

    def fake_fetcher(url: str, headers: dict[str, str] | None):
        payload = {
            "data": [
                {"period": "2024-04-01", "v": 46000, "release": "2024-04-02"},
            ]
        }
        return json.dumps(payload).encode("utf-8"), payload

    result = service.ingest_api_json(
        indicator.indicator_code,
        source.source_id,
        url="https://example.test/prices",
        mapping=mapping,
        available_time="2024-05-01T00:00:00Z",
        fetcher=fake_fetcher,
    )

    assert result.records_inserted == 1
    assert result.job_status == "succeeded"


def test_missing_column_raises_import_failure(ctx, tmp_path: Path) -> None:
    _registry, service, indicator, source = ctx
    path = write_csv(tmp_path / "p.csv", [["2024-01-01", "1"]], header=["date", "value"])
    mapping = ColumnMapping(period_start="date", value="close")

    with pytest.raises(ImportFailure):
        service.ingest_file(
            indicator.indicator_code, source.source_id, path, mapping, available_time=AVAILABLE
        )


def test_raw_and_normalized_tables_are_append_only(ctx, tmp_path: Path) -> None:
    registry, service, indicator, source = ctx
    path = write_csv(tmp_path / "p.csv", [["2024-01-01", "1", "2024-01-02"]])
    service.ingest_file(
        indicator.indicator_code, source.source_id, path, MAPPING, available_time=AVAILABLE
    )

    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute("UPDATE raw_records SET payload = 'rewritten'")
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute("DELETE FROM raw_records")
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute("UPDATE observations SET value = 0")
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute("DELETE FROM observations")