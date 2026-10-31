"""Unit tests for the Telegram daily notification formatter."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from notify_telegram import (
    bottom_indicator_label,
    build_message,
    parse_chat_ids,
)


def test_parse_chat_ids():
    assert parse_chat_ids("") == []
    assert parse_chat_ids("  ") == []
    assert parse_chat_ids("-1002197243810") == ["-1002197243810"]
    assert parse_chat_ids("6668296090,-1002197243810") == ["6668296090", "-1002197243810"]
    assert parse_chat_ids(" 6668296090 , -1002197243810 ") == ["6668296090", "-1002197243810"]


def _record(bfs: float) -> dict:
    return {
        "bfs": bfs,
        "score_coverage": {"configured_weight_coverage_pct": 40.0},
        "market_data": {"price": {"price_usd": 80154.09}},
        "date": "2026-10-25",
    }


def test_band_labels_cover_full_range():
    assert bottom_indicator_label(95).startswith("YES")
    assert bottom_indicator_label(80).startswith("YES")
    assert bottom_indicator_label(70).startswith("APPROACHING")
    assert bottom_indicator_label(55.72).startswith("NO")
    assert bottom_indicator_label(30).startswith("NO")
    assert bottom_indicator_label(5).startswith("NO")


def test_message_format_is_fixed_english():
    msg = build_message(_record(55.72))
    lines = msg.split("\n")
    assert lines[0] == "Cycle Bottom Indicator: NO — Neutral Zone"
    assert lines[1] == "(BFS 55.72/100 · daily close)"
    assert lines[2] == "BTC: $80,154.09 | 2026-10-25 UTC"
    assert len(lines) == 3
    assert "https://" not in msg
    assert msg.isascii() or "—" in msg  # only the em dash is non-ASCII


def test_message_reflects_score_changes():
    assert "APPROACHING" in build_message(_record(65.0))
    assert "Deep Value Zone" in build_message(_record(85.0))
