import json
from urllib.parse import parse_qs, urlparse

import pytest

from cyclemark.backfill import backfill_funding_rates, funding_backfill_state_path
from cyclemark.sources import (
    DataSourceError,
    PaginationLimitError,
    iter_binance_funding_rate_pages,
)

STEP_MS = 8 * 3600 * 1000  # funding settles every eight hours
NOW = "2026-01-01T00:00:00Z"


def obs(timestamp, rate=0.0001, mark=95000.0):
    return {
        "funding_time_ms": timestamp,
        "funding_rate": rate,
        "mark_price": mark,
        "symbol": "BTCUSDT",
        "source": "binance_usdm_funding_rate_api",
        "schema_version": "1.0",
        "retrieved_at_utc": "2025-12-31T00:00:00Z",
    }


def page(start, count, **kwargs):
    return [obs(start + index * STEP_MS, **kwargs) for index in range(count)]


def scripted_fetch(pages, fail_after=None):
    """Replay fixed pages, applying the caller cursor and optional outage."""
    def fetch(*, start_time_ms, end_time_ms=None, max_pages=100):
        emitted = 0
        for raw in pages:
            rows = [row for row in raw if row["funding_time_ms"] >= start_time_ms]
            if end_time_ms is not None:
                rows = [row for row in rows if row["funding_time_ms"] <= end_time_ms]
            if not rows:
                continue
            if fail_after is not None and emitted >= fail_after:
                raise DataSourceError("scripted outage")
            emitted += 1
            yield rows
    return fetch


def run_backfill(tmp_path, fetch, **overrides):
    options = {
        "archive_path": tmp_path / "funding.json",
        "start_time_ms": 0,
        "fetch_pages": fetch,
        "clock": lambda: NOW,
        "log": lambda message: None,
    }
    options.update(overrides)
    return backfill_funding_rates(**options)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_backfill_persists_pages_and_completes(tmp_path):
    pages = [page(0, 3), page(3 * STEP_MS, 2)]
    result = run_backfill(tmp_path, scripted_fetch(pages))

    assert result["outcome"] == "completed"
    assert result["pages_completed_this_run"] == 2
    assert result["observations_yielded_this_run"] == 5

    rows = read_json(tmp_path / "funding.json")
    assert [row["funding_time_ms"] for row in rows] == [index * STEP_MS for index in range(5)]
    assert rows[0]["source"] == "binance_usdm_funding_rate_api"

    state = read_json(funding_backfill_state_path(tmp_path / "funding.json"))
    assert state["status"] == "complete"
    assert state["pages_completed"] == 2
    assert state["observations_yielded"] == 5
    assert state["requested_start_time_ms"] == 0
    assert state["requested_end_time_ms"] is None
    assert state["symbol"] == "BTCUSDT"
    assert state["source_endpoint"].endswith("/fapi/v1/fundingRate")
    assert state["point_in_time_reconstructed"] is False


def test_backfill_resumes_after_an_outage_without_duplicates(tmp_path):
    pages = [page(0, 3), page(3 * STEP_MS, 3)]
    with pytest.raises(DataSourceError, match="scripted outage"):
        run_backfill(tmp_path, scripted_fetch(pages, fail_after=1))

    archive = tmp_path / "funding.json"
    assert len(read_json(archive)) == 3
    state = read_json(funding_backfill_state_path(archive))
    # The cursor never advances past the archived data, so a crash between the
    # archive write and the state write re-fetches at most one page.
    assert state["next_cursor_time_ms"] == 2 * STEP_MS + 1
    assert state["status"] == "in_progress"

    result = run_backfill(tmp_path, scripted_fetch(pages))
    assert result["outcome"] == "completed"
    rows = read_json(archive)
    assert [row["funding_time_ms"] for row in rows] == [index * STEP_MS for index in range(6)]


def test_backfill_rerun_after_completion_is_idempotent(tmp_path):
    run_backfill(tmp_path, scripted_fetch([page(0, 2)]))
    before = (tmp_path / "funding.json").read_text(encoding="utf-8")

    def forbidden_fetch(**kwargs):
        raise AssertionError("A completed range must not trigger network calls.")

    result = run_backfill(tmp_path, forbidden_fetch)
    assert result["outcome"] == "already_complete"
    assert result["archive_observation_count"] == 2
    assert (tmp_path / "funding.json").read_text(encoding="utf-8") == before


def test_backfill_rejects_a_mismatched_range_unless_restarted(tmp_path):
    run_backfill(tmp_path, scripted_fetch([page(0, 2)]))
    with pytest.raises(ValueError, match="different range"):
        run_backfill(tmp_path, scripted_fetch([page(10 * STEP_MS, 1)]), start_time_ms=10 * STEP_MS)

    result = run_backfill(
        tmp_path, scripted_fetch([page(0, 2)]), start_time_ms=0, restart=True,
    )
    assert result["outcome"] == "completed"
    assert len(read_json(tmp_path / "funding.json")) == 2


def test_backfill_preserves_source_revisions_at_the_same_timestamp(tmp_path):
    archive = tmp_path / "funding.json"
    archive.write_text(json.dumps([obs(0, rate=0.0001)]), encoding="utf-8")

    result = run_backfill(tmp_path, scripted_fetch([page(0, 1, rate=0.0002)]))
    assert result["outcome"] == "completed"

    rows = read_json(archive)
    assert len(rows) == 2
    assert sorted(row["funding_rate"] for row in rows) == [0.0001, 0.0002]


def test_backfill_treats_the_page_budget_as_a_checkpoint(tmp_path):
    timeline = [obs(index * STEP_MS) for index in range(30)]

    def budgeted_fetch(*, start_time_ms, end_time_ms=None, max_pages=2):
        rows = [row for row in timeline if row["funding_time_ms"] >= start_time_ms]
        pages = [rows[index:index + 3] for index in range(0, len(rows), 3)]
        for index, rows_page in enumerate(pages):
            if index >= max_pages:
                raise PaginationLimitError(
                    f"Funding history exceeded the {max_pages}-page safety limit."
                )
            yield rows_page

    first = run_backfill(tmp_path, budgeted_fetch, max_pages=2)
    assert first["outcome"] == "incomplete"
    assert first["archive_observation_count"] == 6
    # The cursor advances to the last archived timestamp + 1.
    assert first["next_cursor_time_ms"] == 5 * STEP_MS + 1

    final = first
    for _ in range(4):
        final = run_backfill(tmp_path, budgeted_fetch, max_pages=2)
        if final["outcome"] == "completed":
            break
    assert final["outcome"] == "completed"
    rows = read_json(tmp_path / "funding.json")
    assert len(rows) == 30
    assert len({row["funding_time_ms"] for row in rows}) == 30


def test_backfill_wires_the_real_iterator_with_bounded_pages(monkeypatch, tmp_path):
    import cyclemark.sources as sources

    def fake_get_json(url):
        start = int(parse_qs(urlparse(url).query)["startTime"][0])
        return [
            {"fundingTime": start + index * STEP_MS, "fundingRate": "0.0001", "markPrice": "95000"}
            for index in range(3)
        ]

    monkeypatch.setattr(sources, "_get_json", fake_get_json)
    result = run_backfill(tmp_path, iter_binance_funding_rate_pages)
    assert result["outcome"] == "completed"
    rows = read_json(tmp_path / "funding.json")
    assert [row["funding_time_ms"] for row in rows] == [0, STEP_MS, 2 * STEP_MS]
    assert rows[0]["symbol"] == "BTCUSDT"


def test_backfill_validates_the_requested_range(tmp_path):
    with pytest.raises(ValueError, match="must not precede"):
        run_backfill(tmp_path, scripted_fetch([]), start_time_ms=2000, end_time_ms=1000)
    with pytest.raises(ValueError, match="non-negative"):
        run_backfill(tmp_path, scripted_fetch([]), start_time_ms=-1)
    with pytest.raises(ValueError, match="max_pages"):
        run_backfill(tmp_path, scripted_fetch([]), max_pages=0)


def test_backfill_rejects_corrupted_local_files(tmp_path):
    archive = tmp_path / "funding.json"
    archive.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON list"):
        run_backfill(tmp_path, scripted_fetch([page(0, 1)]))

    archive.unlink()
    funding_backfill_state_path(archive).write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        run_backfill(tmp_path, scripted_fetch([page(0, 1)]))

    funding_backfill_state_path(archive).write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing fields"):
        run_backfill(tmp_path, scripted_fetch([page(0, 1)]))
