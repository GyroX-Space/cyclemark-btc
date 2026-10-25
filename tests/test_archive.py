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



def test_merge_funding_observations_deduplicates_unchanged_rows_and_keeps_revisions():
    from cyclemark.archive import merge_funding_rate_observations

    first = {
        "funding_time_ms": 1000,
        "funding_rate": 0.0001,
        "mark_price": 95000.0,
        "retrieved_at_utc": "2026-01-01T00:00:00Z",
    }
    duplicate = {**first, "retrieved_at_utc": "2026-01-02T00:00:00Z"}
    revision = {**first, "funding_rate": 0.0002, "retrieved_at_utc": "2026-01-03T00:00:00Z"}
    later = {**first, "funding_time_ms": 2000}

    result = merge_funding_rate_observations([first], [duplicate, revision, later])
    assert len(result) == 3
    assert [row["funding_time_ms"] for row in result] == [1000, 1000, 2000]
    assert result[0]["retrieved_at_utc"] == "2026-01-01T00:00:00Z"
