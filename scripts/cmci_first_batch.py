"""Run the first real-data batch (D1-D6 prerequisites) and print a report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci.db import Database  # noqa: E402
from cmci.first_batch import FirstBatchService  # noqa: E402
from cmci.registry import Registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="CMCI first real-data batch")
    parser.add_argument("--db", default=str(ROOT / "data" / "cmci" / "cmci.db"))
    parser.add_argument(
        "--batches",
        default="d2,d3,d4,d5,derived",
        help="comma separated: d1,d2,d3,d4,d5,derived (d2 = Yahoo unless Kraken files are given)",
    )
    parser.add_argument("--fred-key", default=os.environ.get("FRED_API_KEY", ""))
    parser.add_argument("--fred-sampling", default="month_end", choices=["month_end", "all"])
    parser.add_argument("--kraken-btc", default=None)
    parser.add_argument("--kraken-eth", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    database = Database(args.db)
    registry = Registry(database)
    service = FirstBatchService(registry)
    service.ensure_registered()

    selected = {item.strip().lower() for item in args.batches.split(",") if item.strip()}
    report: dict[str, object] = {}

    if "d1" in selected:
        if not args.fred_key:
            report["D1"] = {"skipped": ["FRED_API_KEY not provided; ALFRED vintages unavailable"]}
        else:
            report["D1"] = service.run_d1_fred(
                args.fred_key, sampling=args.fred_sampling
            ).__dict__
    if "d2" in selected:
        if args.kraken_btc or args.kraken_eth:
            report["D2-Kraken"] = service.run_d2_kraken(
                btc_csv=args.kraken_btc, eth_csv=args.kraken_eth
            ).__dict__
        else:
            report["D2-Yahoo"] = service.run_d2_yahoo().__dict__
    if "d3" in selected:
        report["D3"] = service.run_d3_blockchain().__dict__
    if "d4" in selected:
        report["D4"] = service.run_d4_stablecoins().__dict__
    if "d5" in selected:
        report["D5"] = service.run_d5_etf().__dict__
    if "derived" in selected:
        report["derived"] = service.run_derived().__dict__

    report["coverage_reconciled"] = service.reconcile_coverage()
    report["coverage"] = service.coverage_report()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())