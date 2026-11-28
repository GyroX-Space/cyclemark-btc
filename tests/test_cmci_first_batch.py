"""First real-data batch: connectors, provenance, governance."""

from __future__ import annotations

import json
import sqlite3

import pytest

from cmci import connectors
from cmci.first_batch import FirstBatchService
from cmci.governance import GovernanceService
from cmci.importers import ColumnMapping
from cmci.ingestion import IngestionService
from cmci.registry import Registry

MAPPING = ColumnMapping(
    period_start="period_start",
    period_end="period_end",
    value="value",
    value_text="value_text",
    available_time="available_time",
    available_time_precision="available_time_precision",
    available_time_method="available_time_method",
    vintage_time="vintage_time",
)


def test_first_batch_registers_governance_and_licenses():
    registry = Registry(":memory:")
    service = FirstBatchService(registry)
    service.ensure_registered()

    governance = GovernanceService(registry)
    gov = governance.get_indicator_governance("BTC_USD_OHLCV")
    assert gov.source_grade == "A"
    assert gov.coverage_status == "full_target_coverage"
    assert registry.get_indicator("VIX").layer == "L1"
    assert registry.get_indicator("BTC_USD_OHLCV").usage_partition_policy

    tftc = governance.get_source_license(service.sources["TFTC"])
    assert tftc.attribution_required is True
    assert tftc.commercial_use_allowed is True

    fred = governance.get_source_license(service.sources["FRED"])
    assert fred.commercial_use_allowed is False
    assert fred.redistribution_allowed is False


def test_observation_provenance_is_per_row():
    registry = Registry(":memory:")
    service = FirstBatchService(registry)
    service.ensure_registered()
    ingestion = IngestionService(registry)
    registry.link_source("BTC_USD_OHLCV", service.sources["YAHOO"], actor="test")

    rows = [
        {
            "period_start": "2018-01-01",
            "period_end": "2018-01-01",
            "value": 100,
            "available_time": "2018-01-02T23:59:59Z",
            "available_time_precision": "date",
            "available_time_method": "conservative_lag",
            "vintage_time": "2018-01-02T23:59:59Z",
        },
        {
            "period_start": "2018-01-02",
            "period_end": "2018-01-02",
            "value": 101,
            "available_time": "2018-01-03T23:59:59Z",
            "available_time_precision": "date",
            "available_time_method": "conservative_lag",
            "vintage_time": "2018-01-03T23:59:59Z",
        },
    ]
    ingestion.ingest_rows(
        "BTC_USD_OHLCV", service.sources["YAHOO"], rows, MAPPING, actor="test"
    )
    stored = registry.conn.execute(
        "SELECT observation_period_start, available_time_utc, available_time_precision, "
        "available_time_method, ingested_at_utc FROM observations "
        "ORDER BY observation_period_start"
    ).fetchall()
    assert [row["available_time_utc"] for row in stored] == [
        "2018-01-02T23:59:59Z",
        "2018-01-03T23:59:59Z",
    ]
    assert all(row["available_time_precision"] == "date" for row in stored)
    assert all(row["available_time_method"] == "conservative_lag" for row in stored)
    assert all(row["ingested_at_utc"] for row in stored)


def test_blockchain_rows_collapse_to_one_value_per_day():
    payload = {
        "values": [
            {"x": 1420070400, "y": 1.0},  # 2015-01-01
            {"x": 1420074000, "y": 2.0},
            {"x": 1420156800, "y": 3.0},  # 2015-01-02
        ]
    }
    rows = connectors.blockchain_rows(payload)
    assert len(rows) == 2
    assert rows[0]["value"] == 2.0
    assert rows[0]["available_time"] == "2015-01-02T23:59:59Z"
    assert rows[1]["value"] == 3.0


def test_defillama_and_tftc_rows():
    llama = [
        {"date": "1511913600", "totalCirculatingUSD": {"peggedUSD": 100.0, "peggedEUR": 5.0}},
        {"date": "1512000000", "totalCirculatingUSD": {"peggedUSD": 110.0}},
    ]
    rows = connectors.defillama_total_rows(llama)
    assert [row["value"] for row in rows] == [105.0, 110.0]
    assert rows[0]["available_time_method"] == "conservative_lag"

    tftc = {
        "days": [
            {"date": "2024-01-11", "netFlowUsd": 123.0, "totalNetAssetsUsd": 456.0},
            {"date": "2024-01-12", "netFlowUsd": -50.0, "totalNetAssetsUsd": None},
        ]
    }
    flow_rows = connectors.tftc_rows(tftc, field="netFlowUsd")
    assert len(flow_rows) == 2
    assert flow_rows[0]["available_time"] == "2024-01-13T23:59:59Z"
    aum_rows = connectors.tftc_rows(tftc, field="totalNetAssetsUsd")
    assert len(aum_rows) == 1


def test_yahoo_rows_and_derived_series():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1420070400, 1420156800, 1420243200],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1, 2, 3],
                                "high": [2, 3, 4],
                                "low": [0.5, 1.5, 2.5],
                                "close": [1, 2, 4],
                                "volume": [10, 20, 30],
                            }
                        ]
                    },
                }
            ]
        }
    }
    closes, volumes = connectors.yahoo_ohlcv_rows(payload)
    assert len(closes) == 3 and len(volumes) == 3
    assert json.loads(closes[0]["value_text"])["open"] == 1

    returns = connectors.pct_change_rows(closes, name="returns")
    assert returns[0]["value"] == pytest.approx(1.0)
    drawdowns = connectors.drawdown_rows(closes)
    assert drawdowns[1]["value"] == pytest.approx(0.0)
    assert drawdowns[2]["value"] == pytest.approx(0.0)


def test_kraken_csv_is_aggregated_to_daily(tmp_path):
    csv_path = tmp_path / "BTCUSD_1h.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,vwap,volume,count\n"
        "1420070400,100,110,90,105,100,1.5,10\n"
        "1420074000,105,120,100,115,110,2.5,20\n"
        "1420156800,115,125,110,120,118,1.0,5\n",
        encoding="utf-8",
    )
    closes, volumes = connectors.kraken_daily_ohlcvt(csv_path, pair="BTCUSD")
    assert len(closes) == 2
    assert closes[0]["value"] == 115.0
    assert volumes[0]["value"] == 4.0
    assert json.loads(closes[0]["value_text"])["high"] == 120.0


def test_fred_rows_use_vintage_availability():
    observations = [
        {"date": "2015-01-01", "value": "1.5"},
        {"date": "2015-01-02", "value": "."},
    ]
    rows = connectors.fred_rows(observations, vintage_date="2015-03-01")
    assert len(rows) == 1
    assert rows[0]["available_time"] == "2015-03-01T23:59:59Z"
    assert rows[0]["available_time_method"] == "historical_vintage"


def test_governance_records_are_append_only():
    registry = Registry(":memory:")
    service = FirstBatchService(registry)
    service.ensure_registered()
    governance = GovernanceService(registry)
    gov = governance.get_indicator_governance("BTC_USD_OHLCV")
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute(
            "UPDATE indicator_governance SET source_grade = 'C' WHERE governance_id = ?",
            (gov.governance_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute(
            "DELETE FROM indicator_governance WHERE governance_id = ?", (gov.governance_id,)
        )