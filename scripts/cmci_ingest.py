"""Ingest a CSV/JSON/Excel file into the CMCI database.

Example:
    python scripts/cmci_ingest.py --indicator btc_spot_close_usd \
        --source src_xxxxxxxx --file data/inbox/btc_close.csv \
        --period-start date --value close

Column names default to the source header names; only --period-start and
--value are mandatory. The indicator must already be registered, enabled, and
linked to the source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci import ColumnMapping, IngestionService, Registry  # noqa: E402
from cmci.registry import RegistryError  # noqa: E402

DEFAULT_DB = ROOT / "data" / "cmci" / "cmci.db"
DEFAULT_RAW_DIR = ROOT / "data" / "cmci" / "raw"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest a file into CMCI")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--indicator", required=True, help="indicator_code")
    parser.add_argument("--source", required=True, help="source_id")
    parser.add_argument("--file", required=True, help="CSV/JSON/XLSX path")
    parser.add_argument("--period-start", required=True, help="period start column")
    parser.add_argument("--value", required=True, help="value column")
    parser.add_argument("--period-end")
    parser.add_argument("--release-time")
    parser.add_argument("--vintage-time")
    parser.add_argument("--unit")
    parser.add_argument("--timezone")
    parser.add_argument("--available-time", help="explicit system availability time")
    parser.add_argument("--actor", default="cmci_ingest")
    args = parser.parse_args(argv)

    mapping = ColumnMapping(
        period_start=args.period_start,
        value=args.value,
        period_end=args.period_end,
        release_time=args.release_time,
        vintage_time=args.vintage_time,
        unit=args.unit,
        timezone=args.timezone,
    )
    registry = Registry(args.db)
    try:
        service = IngestionService(registry, raw_dir=args.raw_dir)
        result = service.ingest_file(
            args.indicator,
            args.source,
            args.file,
            mapping,
            actor=args.actor,
            available_time=args.available_time,
        )
    except RegistryError as exc:
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 2
    finally:
        registry.close()

    print(f"job: {result.job_id} ({result.job_status})")
    print(
        f"received={result.records_received} inserted={result.records_inserted} "
        f"updated={result.records_updated} unchanged={result.records_unchanged} "
        f"rejected={result.records_rejected}"
    )
    if result.duplicate_payload:
        print("duplicate payload: existing raw record reused, no new observations")
    return 0 if result.job_status != "failed" else 3


if __name__ == "__main__":
    raise SystemExit(main())