"""Daily record schema helpers for the CycleMark public archive."""
from __future__ import annotations
import hashlib
import json
import os
from math import isfinite
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

# Keys that change on every retrieval without changing the published decision.
VOLATILE_TIMESTAMP_KEYS = frozenset({
    "generated_at_utc",
    "retrieved_at_utc",
    "assessed_at_utc",
    "revised_at_utc",
    "first_published_at_utc",
})
PUBLICATION_BOOKKEEPING_KEYS = frozenset({"revision", "previous_revision"})

def build_daily_record(*, as_of_date: date, generated_at_utc: str, model_version: str,
                       status: str, market_data: dict[str, Any], sources: dict[str, Any],
                       notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "date": as_of_date.isoformat(),
        "generated_at_utc": generated_at_utc, "model_version": model_version,
        "status": status, "state": None, "bfs": None, "bos": None,
        "scores_are_validated": False, "market_data": market_data,
        "sources": sources, "notes": notes or [],
    }

def write_json(path: str | Path, payload: Any) -> None:
    """Write JSON atomically, flushing the file before replacement."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    _fsync_directory(target.parent)


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory fsync; not supported on every platform."""
    try:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except (OSError, AttributeError):
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_volatile(item)
            for key, item in value.items()
            if key not in VOLATILE_TIMESTAMP_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def record_content_fingerprint(record: dict) -> str:
    """Hash the substantive content of a published record.

    Retrieval timestamps and publication bookkeeping are excluded so that a
    rerun with identical observations is recognized as unchanged.
    """
    if not isinstance(record, dict):
        raise ValueError("Daily record must be an object.")
    payload = _strip_volatile(record)
    for key in PUBLICATION_BOOKKEEPING_KEYS:
        payload.pop(key, None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def publish_daily_record(
    signals_dir: str | Path,
    record: dict,
    *,
    published_at_utc: str,
) -> dict:
    """Publish a daily record idempotently with immutable revisions.

    An identical rerun leaves the existing record untouched. A materially
    different rerun for the same date archives the previous revision under
    ``revisions/`` before publishing the new canonical record. History keeps one
    canonical entry per date; revisions preserve what was previously published.
    """
    if not isinstance(record, dict):
        raise ValueError("Daily record must be an object.")
    record_date = record.get("date")
    if not isinstance(record_date, str) or not record_date:
        raise ValueError("Daily record must contain an ISO date string.")

    signals = Path(signals_dir)
    date_path = signals / f"{record_date}.json"
    history_path = signals / "history.json"
    revisions_dir = signals / "revisions"

    history: list[dict] = []
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
            raise ValueError("Signal history must be a list of records.")

    existing: dict | None = None
    if date_path.exists():
        existing = json.loads(date_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise ValueError(f"Existing record for {record_date} must be an object.")

    if existing is not None and (
        record_content_fingerprint(existing) == record_content_fingerprint(record)
    ):
        canonical = existing
        outcome = "unchanged"
    else:
        revision = 1 if existing is None else int(existing.get("revision", 1)) + 1
        canonical = dict(record)
        canonical["revision"] = revision
        canonical["first_published_at_utc"] = (
            existing.get("first_published_at_utc", published_at_utc)
            if existing is not None else published_at_utc
        )
        if existing is not None:
            previous = int(existing.get("revision", 1))
            write_json(revisions_dir / f"{record_date}-r{previous}.json", existing)
        write_json(date_path, canonical)
        outcome = "published" if existing is None else "revised"

    updated_history = [item for item in history if item.get("date") != record_date]
    updated_history.append(canonical)
    updated_history.sort(key=lambda item: str(item.get("date", "")))
    write_json(history_path, updated_history)

    # Latest is written last so an interrupted run cannot publish a newest
    # record before history is consistent.
    latest = updated_history[-1]
    latest_path = signals / "latest.json"
    if not latest_path.exists() or json.loads(latest_path.read_text(encoding="utf-8")) != latest:
        write_json(latest_path, latest)

    return {
        "outcome": outcome,
        "date": record_date,
        "revision": int(canonical.get("revision", 1)),
    }




def merge_funding_rate_observations(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge raw funding observations without duplicating unchanged records.

    A changed rate or mark price at the same funding timestamp is preserved as
    a separate observation so that source revisions are not silently erased.
    """
    if not isinstance(existing, list) or not isinstance(incoming, list):
        raise ValueError("Funding observation archives must be lists.")
    merged: dict[tuple[int, float, float | None], dict] = {}
    for item in [*existing, *incoming]:
        if not isinstance(item, dict):
            raise ValueError("Funding observation archive contains a non-object row.")
        try:
            timestamp = int(item["funding_time_ms"])
            rate = float(item["funding_rate"])
            mark_raw = item.get("mark_price")
            mark_price = float(mark_raw) if mark_raw is not None else None
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Malformed funding observation archive row: {exc}") from exc
        if timestamp < 0 or not isfinite(rate):
            raise ValueError("Funding timestamps and rates must be finite and valid.")
        if mark_price is not None and (not isfinite(mark_price) or mark_price <= 0):
            raise ValueError("Funding mark prices must be finite and greater than zero.")
        key = (timestamp, rate, mark_price)
        if key not in merged:
            merged[key] = dict(item)
    return sorted(merged.values(), key=lambda row: (
        int(row["funding_time_ms"]), float(row["funding_rate"]),
        float(row["mark_price"]) if row.get("mark_price") is not None else 0.0,
    ))
