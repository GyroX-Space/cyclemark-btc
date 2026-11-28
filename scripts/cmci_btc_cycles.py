"""Build the BTC halving-cycle table from registered observations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci.cycles import CycleTableService, write_outputs  # noqa: E402
from cmci.registry import Registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="CMCI BTC cycle table")
    parser.add_argument("--db", default=str(ROOT / "data" / "cmci" / "cmci.db"))
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "cmci" / "cycles"))
    args = parser.parse_args()

    registry = Registry(args.db)
    try:
        report = CycleTableService(registry).build()
        json_path, csv_path = write_outputs(report, args.output_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\njson={json_path}\ncsv={csv_path}")
        return 0
    finally:
        registry.close()


if __name__ == "__main__":
    raise SystemExit(main())