"""Daily record schema helpers for the CycleMark public archive."""
from __future__ import annotations
import json
from math import isfinite
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

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
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)



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
