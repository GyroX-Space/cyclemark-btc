#!/usr/bin/env python
"""Run the walk-forward evaluation and write a JSON report (research only).

Reads daily candles from a local JSON file (list of {date|open_time_ms, open,
high, low, close}) and signal records from a directory of daily JSON files.
No network access.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cyclemark.evaluation import evaluate
from cyclemark.sources import utc_now


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candles", required=True, help="Path to candles JSON file.")
    parser.add_argument("--signals", required=True, help="Directory of signal JSON files.")
    parser.add_argument("--horizon", type=int, required=True, choices=(365, 548))
    parser.add_argument("--out", required=True, help="Output report path.")
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    candles = _load_json(Path(args.candles))
    signals_dir = Path(args.signals)
    signal_files = sorted(
        p for p in signals_dir.glob("*.json")
        if p.name not in {"history.json", "latest.json"} and p.parent.name != "revisions"
    )
    signals = [_load_json(p) for p in signal_files]

    report = evaluate(
        signals=signals,
        candles=candles,
        horizon_days=args.horizon,
        generated_at_utc=utc_now(),
        resamples=args.resamples,
        seed=args.seed,
        signal_files=[p.name for p in signal_files],
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for stratum, result in report["results_by_stratum"].items():
        print(f"{stratum}: conclusion={result['conclusion']} "
              f"valid_folds={result['valid_fold_count']} "
              f"usable_starts={result['usable_block_starts']} "
              f"effective={result['effective_blocks_or_cycles']} "
              f"weak_evidence={result['weak_evidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
