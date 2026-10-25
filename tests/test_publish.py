import json

import pytest

from cyclemark.archive import publish_daily_record, record_content_fingerprint


def _record(date: str = "2026-01-02", *, price: float = 100.0,
            generated_at: str = "2026-01-02T02:00:00Z",
            retrieved_at: str = "2026-01-02T02:00:00Z") -> dict:
    return {
        "schema_version": "1.0",
        "date": date,
        "generated_at_utc": generated_at,
        "model_version": "0.1.1",
        "status": "research_only",
        "state": None,
        "bfs": 50.0,
        "bos": None,
        "scores_are_validated": False,
        "market_data": {"price": {"price_usd": price, "source": "test"}},
        "sources": {"price": {"name": "test", "retrieved_at_utc": retrieved_at}},
        "notes": ["research context only"],
    }


def test_first_publication_writes_date_history_and_latest(tmp_path):
    result = publish_daily_record(tmp_path, _record(), published_at_utc="2026-01-02T02:00:00Z")
    assert result["outcome"] == "published"
    assert result["revision"] == 1

    record = json.loads((tmp_path / "2026-01-02.json").read_text(encoding="utf-8"))
    assert record["revision"] == 1
    assert record["first_published_at_utc"] == "2026-01-02T02:00:00Z"
    history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(history) == 1
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-01-02"


def test_identical_rerun_is_unchanged_and_does_not_duplicate_history(tmp_path):
    publish_daily_record(tmp_path, _record(), published_at_utc="2026-01-02T02:00:00Z")
    original = (tmp_path / "2026-01-02.json").read_text(encoding="utf-8")

    rerun = _record(generated_at="2026-01-03T09:00:00Z", retrieved_at="2026-01-03T09:00:00Z")
    result = publish_daily_record(tmp_path, rerun, published_at_utc="2026-01-03T09:00:00Z")

    assert result["outcome"] == "unchanged"
    assert (tmp_path / "2026-01-02.json").read_text(encoding="utf-8") == original
    history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(history) == 1
    assert not (tmp_path / "revisions").exists()


def test_material_change_creates_an_immutable_revision(tmp_path):
    publish_daily_record(tmp_path, _record(price=100.0), published_at_utc="2026-01-02T02:00:00Z")
    original = json.loads((tmp_path / "2026-01-02.json").read_text(encoding="utf-8"))

    result = publish_daily_record(
        tmp_path, _record(price=101.0, generated_at="2026-01-02T09:00:00Z"),
        published_at_utc="2026-01-02T09:00:00Z",
    )

    assert result["outcome"] == "revised"
    assert result["revision"] == 2
    archived = json.loads((tmp_path / "revisions" / "2026-01-02-r1.json").read_text(encoding="utf-8"))
    assert archived == original
    canonical = json.loads((tmp_path / "2026-01-02.json").read_text(encoding="utf-8"))
    assert canonical["revision"] == 2
    assert canonical["first_published_at_utc"] == "2026-01-02T02:00:00Z"
    assert canonical["market_data"]["price"]["price_usd"] == 101.0
    history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(history) == 1
    assert history[0]["revision"] == 2


def test_history_keeps_one_canonical_entry_per_date(tmp_path):
    publish_daily_record(tmp_path, _record("2026-01-01", price=90.0), published_at_utc="2026-01-01T02:00:00Z")
    publish_daily_record(tmp_path, _record("2026-01-02", price=100.0), published_at_utc="2026-01-02T02:00:00Z")
    publish_daily_record(tmp_path, _record("2026-01-02", price=102.0), published_at_utc="2026-01-02T09:00:00Z")

    history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [item["date"] for item in history] == ["2026-01-01", "2026-01-02"]
    assert history[-1]["market_data"]["price"]["price_usd"] == 102.0
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-01-02"


def test_fingerprint_ignores_volatile_timestamps_and_bookkeeping():
    first = _record(generated_at="2026-01-02T02:00:00Z", retrieved_at="2026-01-02T02:00:00Z")
    second = _record(generated_at="2026-02-01T02:00:00Z", retrieved_at="2026-02-01T02:00:00Z")
    second["revision"] = 3
    second["first_published_at_utc"] = "2026-01-02T02:00:00Z"
    assert record_content_fingerprint(first) == record_content_fingerprint(second)


def test_corrupt_existing_record_is_rejected(tmp_path):
    (tmp_path / "2026-01-02.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        publish_daily_record(tmp_path, _record(), published_at_utc="2026-01-02T02:00:00Z")
