"""BTC cycle table calculations."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from cmci.cycles import _at, _first_on_or_after, _stats, write_outputs


def test_price_stats_return_drawdown_and_volatility():
    start = date(2020, 1, 1)
    points = [
        (start, 100.0),
        (start + timedelta(days=1), 120.0),
        (start + timedelta(days=2), 60.0),
        (start + timedelta(days=3), 150.0),
    ]
    stats = _stats(points)
    assert stats["start"] == 100.0
    assert stats["end"] == 150.0
    assert stats["return_pct"] == pytest.approx(50.0)
    assert stats["max_close"] == 150.0
    assert stats["max_drawdown_pct"] == pytest.approx(-50.0)
    assert stats["annualized_vol_pct"] > 0


def test_first_on_or_after_rejects_distant_gaps():
    points = [(date(2014, 9, 17), 457.0)]
    assert _first_on_or_after(points, date(2012, 12, 28)) is None
    assert _first_on_or_after(points, date(2014, 9, 10)) == 457.0


def test_at_uses_latest_value_not_after_the_day():
    points = [(date(2020, 1, 1), 1.0), (date(2020, 2, 1), 2.0)]
    assert _at(points, date(2020, 1, 15)) == 1.0
    assert _at(points, date(2019, 12, 31)) is None


def test_write_outputs_creates_csv_and_json(tmp_path):
    report = {
        "cycles": [
            {
                "label": "cycle",
                "start_utc": "2020-01-01T00:00:00Z",
                "end_utc": "2021-01-01T00:00:00Z",
                "return_pct": 10.5,
                "data_note": "note, with comma",
            }
        ]
    }
    json_path, csv_path = write_outputs(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["cycles"][0]["label"] == "cycle"
    text = csv_path.read_text(encoding="utf-8")
    assert "note, with comma" in text
    assert text.startswith("label,start_utc,end_utc,return_pct,data_note")