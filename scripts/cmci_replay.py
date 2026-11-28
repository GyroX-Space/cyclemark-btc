"""Replay a CMCI research dataset as of a historical instant.

Example:
    python scripts/cmci_replay.py --dataset btc_cycle_lab --as-of 2024-03-10

Only data whose ``available_time`` was already known at the as-of time is
returned. The result is written as a CSV snapshot and recorded in
``replay_jobs`` with a deterministic hash.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci import Registry, ReplayService  # noqa: E402
from cmci.registry import RegistryError  # noqa: E402

DEFAULT_DB = ROOT / "data" / "cmci" / "cmci.db"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "cmci" / "replays"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a CMCI dataset as of a time")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--dataset", required=True, help="dataset_code")
    parser.add_argument("--as-of", required=True, help="ISO-8601 UTC instant")
    parser.add_argument("--version", type=int, help="dataset version; default latest")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--created-by", default="cmci_replay")
    args = parser.parse_args(argv)

    registry = Registry(args.db)
    try:
        service = ReplayService(registry)
        result = service.replay_dataset(
            args.dataset,
            as_of=args.as_of,
            version_no=args.version,
            created_by=args.created_by,
            output_dir=args.output_dir,
        )
    except RegistryError as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 2
    finally:
        registry.close()

    report = result.report
    print(f"job: {result.job.replay_job_id}")
    print(f"dataset: {report['dataset_code']} v{report['version_no']}")
    print(f"as_of: {report['as_of_utc']}")
    print(f"rows: {report['row_count']}  hash: {report['replay_result_hash']}")
    print(f"snapshot: {result.job.snapshot_path}")
    missing = report["members_without_data"]
    if missing:
        print(f"members without data: {len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())