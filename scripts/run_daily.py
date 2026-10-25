"""Refresh public market context without inventing unvalidated signals."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cyclemark.daily import run_daily_refresh
from cyclemark.sources import DataSourceError

SIGNALS_DIR = ROOT / "data" / "signals"
MARKET_DIR = ROOT / "data" / "market"


def main() -> int:
    result = run_daily_refresh(signals_dir=SIGNALS_DIR, market_dir=MARKET_DIR)
    record = result["record"]
    publication = result["publication"]
    print(
        f"Daily refresh {publication['outcome']} for {record['date']} "
        f"(revision {publication['revision']})"
    )
    print(f"Price: USD {record['market_data']['price']['price_usd']:,.2f}")
    print(f"Provisional BFS: {record['bfs']} "
          f"({record['score_coverage']['configured_weight_coverage_pct']}% configured-weight coverage; not validated)")
    archive = result["funding_archive"]
    if archive["status"] == "written":
        print(f"Funding archive observations: {archive['observation_count']} "
              f"({archive['retrieved_observation_count']} retrieved this run); excluded from scores")
    elif archive["status"] == "failed":
        print(f"Funding archive was not updated: {archive['error']}", file=sys.stderr)
    print("BOS and the composite state remain withheld pending model validation.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DataSourceError, ValueError) as exc:
        print(f"Daily refresh failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
