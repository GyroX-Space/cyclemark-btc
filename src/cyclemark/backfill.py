"""Resumable historical backfill for raw Binance funding-rate observations.

The archive file remains a plain list of raw observations so the daily runner
can keep merging into it. A sidecar state file records the resume cursor and
provenance. The archive is written before the state on every page, so a crash
can only leave the state cursor at or behind the archived data; reruns then
re-fetch at most one page and deduplication absorbs the overlap.

This dataset is not point-in-time reconstructed: retrieval timestamps show when
CycleMark collected each observation, not when the value was first knowable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Iterator

from cyclemark.archive import merge_funding_rate_observations, write_json
from cyclemark.sources import (
    FUNDING_ENDPOINT,
    FUNDING_MAX_PAGES,
    FUNDING_PAGE_LIMIT,
    FUNDING_SYMBOL,
    PaginationLimitError,
    iter_binance_funding_rate_pages,
    utc_now,
)

STATE_SUFFIX = ".backfill-state.json"
BACKFILL_SCHEMA_VERSION = "1.0"


def funding_backfill_state_path(archive_path: str | Path) -> Path:
    path = Path(archive_path)
    return path.with_name(path.stem + STATE_SUFFIX)


def _read_archive(archive_path: Path) -> list:
    if not archive_path.exists():
        return []
    payload = json.loads(archive_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Funding archive must contain a JSON list.")
    return payload


def _read_state(state_path: Path) -> dict | None:
    if not state_path.exists():
        return None
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Backfill state file must contain a JSON object.")
    required = {
        "requested_start_time_ms", "requested_end_time_ms",
        "next_cursor_time_ms", "status", "pages_completed",
        "observations_yielded", "started_at_utc",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"Backfill state file is missing fields: {', '.join(missing)}.")
    return payload


def _validate_range(start_time_ms: int, end_time_ms: int | None) -> None:
    if not isinstance(start_time_ms, int) or start_time_ms < 0:
        raise ValueError("start_time_ms must be a non-negative integer.")
    if end_time_ms is not None and (not isinstance(end_time_ms, int) or end_time_ms < 0):
        raise ValueError("end_time_ms must be a non-negative integer.")
    if end_time_ms is not None and end_time_ms < start_time_ms:
        raise ValueError("end_time_ms must not precede start_time_ms.")


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def backfill_funding_rates(
    *,
    archive_path: str | Path,
    start_time_ms: int,
    end_time_ms: int | None = None,
    max_pages: int = FUNDING_MAX_PAGES,
    restart: bool = False,
    fetch_pages: Callable[..., Iterator[list[dict]]] | None = None,
    clock: Callable[[], str] = utc_now,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Backfill raw funding observations for an explicit time range.

    Pagination is bounded by ``max_pages`` per invocation. Reaching the budget
    is not a failure: the run reports ``incomplete`` and a rerun resumes from
    the saved cursor. A source fault raises DataSourceError after persisting
    all completed pages. A completed range reruns as ``already_complete``
    without network calls; pass ``restart=True`` to re-scan the range.
    """
    _validate_range(start_time_ms, end_time_ms)
    if not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer.")
    log = log or _log
    archive = Path(archive_path)
    state_path = funding_backfill_state_path(archive)
    fetch_pages = fetch_pages or iter_binance_funding_rate_pages

    state = None if restart else _read_state(state_path)
    if state is not None:
        same_range = (
            state.get("requested_start_time_ms") == start_time_ms
            and state.get("requested_end_time_ms") == end_time_ms
        )
        if not same_range:
            raise ValueError(
                "A backfill state file already exists for a different range "
                f"(start={state.get('requested_start_time_ms')}, "
                f"end={state.get('requested_end_time_ms')}). "
                "Pass restart=True to discard the saved cursor and re-scan."
            )
        if state.get("status") == "complete":
            return {
                "outcome": "already_complete",
                "pages_completed_this_run": 0,
                "observations_yielded_this_run": 0,
                "archive_observation_count": len(_read_archive(archive)),
                "state_path": str(state_path),
                "archive_path": str(archive),
            }
        cursor = int(state["next_cursor_time_ms"])
        log(f"Resuming funding backfill from cursor {cursor}.")
    else:
        cursor = start_time_ms
        state = {
            "schema_version": BACKFILL_SCHEMA_VERSION,
            "source_endpoint": FUNDING_ENDPOINT,
            "symbol": FUNDING_SYMBOL,
            "page_limit": FUNDING_PAGE_LIMIT,
            "requested_start_time_ms": start_time_ms,
            "requested_end_time_ms": end_time_ms,
            "next_cursor_time_ms": cursor,
            "status": "in_progress",
            "pages_completed": 0,
            "observations_yielded": 0,
            "started_at_utc": clock(),
            "completed_at_utc": None,
            "point_in_time_reconstructed": False,
        }

    rows = _read_archive(archive)
    pages_this_run = 0
    yielded_this_run = 0
    outcome = "completed"
    try:
        for page in fetch_pages(
            start_time_ms=cursor,
            end_time_ms=end_time_ms,
            max_pages=max_pages,
        ):
            if not page:
                continue
            rows = merge_funding_rate_observations(rows, page)
            write_json(archive, rows)
            cursor = max(int(item["funding_time_ms"]) for item in page) + 1
            pages_this_run += 1
            yielded_this_run += len(page)
            state.update({
                "next_cursor_time_ms": cursor,
                "pages_completed": int(state["pages_completed"]) + 1,
                "observations_yielded": int(state["observations_yielded"]) + len(page),
                "updated_at_utc": clock(),
            })
            write_json(state_path, state)
            log(f"Backfilled page {state['pages_completed']}: archive holds {len(rows)} observations.")
    except PaginationLimitError:
        outcome = "incomplete"
        log(f"Page budget of {max_pages} reached; rerun the same command to resume.")

    if outcome == "completed":
        state.update({
            "status": "complete",
            "completed_at_utc": clock(),
            "updated_at_utc": clock(),
        })
        write_json(state_path, state)

    return {
        "outcome": outcome,
        "pages_completed_this_run": pages_this_run,
        "observations_yielded_this_run": yielded_this_run,
        "archive_observation_count": len(rows),
        "next_cursor_time_ms": None if outcome == "completed" else cursor,
        "state_path": str(state_path),
        "archive_path": str(archive),
    }
