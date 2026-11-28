"""Run L2/L4 -> L5 lead-lag relationship tests."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci.registry import Registry  # noqa: E402
from cmci.relationships import RelationshipService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="CMCI relationship tests (L2/L4 -> L5)")
    parser.add_argument("--db", default=str(ROOT / "data" / "cmci" / "cmci.db"))
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "cmci" / "relationships"))
    args = parser.parse_args()

    registry = Registry(args.db)
    try:
        report = RelationshipService(registry).build()
        directory = Path(args.output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "relationship-tests.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (directory / "relationship-tests.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(report["tests"][0].keys()))
            writer.writeheader()
            writer.writerows(report["tests"])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        registry.close()


if __name__ == "__main__":
    raise SystemExit(main())