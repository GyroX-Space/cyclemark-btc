"""Run a CMCI quality report or look-ahead audit.

Examples:
    python scripts/cmci_audit.py --type quality
    python scripts/cmci_audit.py --type lookahead --sample 500 --seed 7

Findings are stored in ``audit_jobs`` / ``audit_results`` and a JSON report is
written to the audit output directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci import AuditService, Registry  # noqa: E402
from cmci.registry import RegistryError  # noqa: E402

DEFAULT_DB = ROOT / "data" / "cmci" / "cmci.db"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "cmci" / "audits"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a CMCI audit")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--type", required=True, choices=("quality", "lookahead"))
    parser.add_argument("--sample", type=int, help="observation sample size")
    parser.add_argument("--seed", type=int, help="sampling seed for reproducibility")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--created-by", default="cmci_audit")
    args = parser.parse_args(argv)

    registry = Registry(args.db)
    try:
        service = AuditService(registry)
        if args.type == "quality":
            run = service.run_quality_report(
                created_by=args.created_by, output_dir=args.output_dir
            )
        else:
            run = service.run_lookahead_audit(
                created_by=args.created_by,
                sample_size=args.sample,
                seed=args.seed,
                output_dir=args.output_dir,
            )
    except RegistryError as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2
    finally:
        registry.close()

    print(f"job: {run.job.audit_job_id} ({run.job.audit_type})")
    print(
        f"checked={run.job.checked_count} violations={run.job.violation_count} "
        f"warnings={run.job.warning_count}"
    )
    print(f"report: {run.job.report_path}")
    return 0 if run.job.violation_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())