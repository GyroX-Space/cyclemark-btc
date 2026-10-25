"""Backfill raw Binance USD-M BTCUSDT perpetual funding-rate observations.

The range is explicit and validated. Each invocation paginates at most
--max-pages API pages, persists every page before advancing the resume cursor,
and can be rerun safely after interruption. The archive records when CycleMark
retrieved each observation; it is not a point-in-time reconstruction of what
was knowable at each funding timestamp.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cyclemark.backfill import backfill_funding_rates
from cyclemark.sources import DataSourceError, FUNDING_MAX_PAGES

DEFAULT_ARCHIVE = ROOT / "data" / "market" / "binance_funding_rates.json"


def parse_time_arg(raw: str) -> int:
    """Parse an epoch-milliseconds integer or an ISO UTC date/datetime."""
    text = raw.strip()
    if text.isdigit():
        value = int(text)
    else:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Invalid timestamp {raw!r}: use epoch milliseconds or an ISO date."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        value = int(parsed.timestamp() * 1000)
    if value < 0:
        raise argparse.ArgumentTypeError("Timestamps must be non-negative.")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=parse_time_arg,
                        help="Range start: epoch milliseconds or ISO date (UTC).")
    parser.add_argument("--end", type=parse_time_arg, default=None,
                        help="Optional range end: epoch milliseconds or ISO date (UTC).")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE,
                        help="Funding observation archive path.")
    parser.add_argument("--max-pages", type=int, default=FUNDING_MAX_PAGES,
                        help="Maximum API pages per invocation (bounded pagination).")
    parser.add_argument("--restart", action="store_true",
                        help="Discard the saved resume cursor and re-scan the range.")
    args = parser.parse_args(argv)

    result = backfill_funding_rates(
        archive_path=args.archive,
        start_time_ms=args.start,
        end_time_ms=args.end,
        max_pages=args.max_pages,
        restart=args.restart,
    )
    print(f"Backfill outcome: {result['outcome']}")
    print(f"Pages this run: {result['pages_completed_this_run']} "
          f"({result['observations_yielded_this_run']} observations retrieved)")
    print(f"Archive observations: {result['archive_observation_count']}")
    if result["outcome"] == "incomplete":
        print("Page budget reached. Rerun the same command to resume from "
              f"cursor {result['next_cursor_time_ms']}.")
    print("Note: this archive is not point-in-time reconstructed; retrieval "
          "timestamps record when CycleMark collected each observation.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DataSourceError, ValueError) as exc:
        print(f"Funding backfill failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
