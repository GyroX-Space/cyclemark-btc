"""Daily record schema helpers for the CycleMark public archive."""
from __future__ import annotations
import json
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
