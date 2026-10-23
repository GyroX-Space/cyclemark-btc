import json
from datetime import date

from cyclemark.archive import build_daily_record, write_json


def test_daily_record_explicitly_withholds_unvalidated_scores():
    record = build_daily_record(
        as_of_date=date(2026, 1, 2),
        generated_at_utc="2026-01-02T02:00:00Z",
        model_version="0.1.0",
        status="research_only",
        market_data={},
        sources={},
    )
    assert record["date"] == "2026-01-02"
    assert record["bfs"] is None
    assert record["bos"] is None
    assert record["state"] is None
    assert record["scores_are_validated"] is False


def test_write_json_creates_valid_json(tmp_path):
    target = tmp_path / "nested" / "record.json"
    write_json(target, {"status": "research_only", "value": 42})
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "status": "research_only", "value": 42
    }
    assert not target.with_suffix(".json.tmp").exists()
