"""Build the first CMCI-CORE-2015 dataset, replay it, and audit it (D6)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci import AuditService, Registry, ReplayService, ResearchDatasetService  # noqa: E402
from cmci.first_batch import FRED_SERIES  # noqa: E402

DEFAULT_DB = ROOT / "data" / "cmci" / "cmci.db"
PROJECT_CODE = "cmci"
DATASET_CODE = "CMCI-CORE-2015"

L1_MEMBERS = list(FRED_SERIES)
L2_MEMBERS = [
    "BTC_CIRCULATING_SUPPLY",
    "BTC_ISSUANCE",
    "BTC_HASHRATE",
    "BTC_DIFFICULTY",
    "BTC_MINER_REVENUE",
    "BTC_NETWORK_ACTIVITY",
    "BTC_UNIQUE_ADDRESSES",
    "BTC_NETWORK_USAGE",
]
L4_MEMBERS = [
    "STABLECOIN_TOTAL_SUPPLY",
    "STABLECOIN_SUPPLY_CHANGE",
    "BTC_SPOT_ETF_NET_FLOW",
    "BTC_SPOT_ETF_AUM",
]

PARTITIONS = [
    ("training", "2015-01-01T00:00:00Z", "2019-09-30T23:59:59Z"),
    ("identification", "2020-01-01T00:00:00Z", "2022-09-30T23:59:59Z"),
    ("validation", "2023-01-01T00:00:00Z", "2026-11-28T23:59:59Z"),
]

L5_PLAN = {
    "BTC_USD_OHLCV": {"training", "identification", "validation"},
    "BTC_VOLUME": {"training", "identification", "validation"},
    "BTC_RETURN": {"training", "identification", "validation"},
    "BTC_REALIZED_VOL": {"identification", "validation"},
    "BTC_DRAWDOWN": {"validation"},
    "ETH_USD_OHLCV": {"identification", "validation"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CMCI-CORE-2015 v1")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--report", default=str(ROOT / "data" / "cmci" / "core-build-report.json"))
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--new-version", action="store_true")
    args = parser.parse_args()

    registry = Registry(args.db)
    try:
        service = ResearchDatasetService(registry)
        try:
            service.get_project(PROJECT_CODE)
        except LookupError:
            service.create_project(
                project_code=PROJECT_CODE,
                project_name="Crypto Market Cycle Intelligence",
                description="CMCI research datasets",
                owner="predi",
            )
        try:
            service.get_dataset(DATASET_CODE)
        except LookupError:
            service.create_dataset(
                PROJECT_CODE,
                dataset_code=DATASET_CODE,
                dataset_name="CMCI core research dataset, 2015+",
                description="First real-data core dataset: L1-L5 indicators with usage partitions.",
                created_by="cmci",
            )

        versions = service.list_versions(DATASET_CODE)
        if versions and versions[-1].status == "sealed" and not args.new_version:
            version = versions[-1]
        else:
            version = service.create_dataset_version(
                DATASET_CODE,
                time_start="2015-01-01T00:00:00Z",
                time_end="2026-11-28T23:59:59Z",
                change_reason=(
                    "Add L1 FRED/ALFRED vintage series to the sealed core dataset."
                    if args.new_version
                    else "First real-data batch: D2-D5 ingested; D1 FRED/ALFRED pending API key."
                ),
                created_by="cmci",
            )

        if version.status == "draft":
            _add_members(service, version.dataset_version_id)
            version = service.seal_version(
                version.dataset_version_id,
                actor="cmci",
                reason="D6 first seal after D2-D5 ingestion",
            )

        replay_results = []
        replay_service = ReplayService(registry)
        for as_of in ("2018-06-01T00:00:00Z", "2021-06-01T00:00:00Z", "2024-06-01T00:00:00Z"):
            result = replay_service.replay_dataset(
                DATASET_CODE,
                as_of=as_of,
                created_by="cmci-d6",
                output_dir=str(ROOT / "data" / "cmci" / "replays"),
            )
            replay_results.append(
                {
                    "as_of": as_of,
                    "job_id": result.job.replay_job_id,
                    "rows": result.report["row_count"],
                    "hash": result.report["replay_result_hash"],
                    "members_without_data": result.report["members_without_data"],
                }
            )

        audit_results = []
        if not args.skip_audit:
            audit = AuditService(registry)
            quality = audit.run_quality_report(
                created_by="cmci-d6",
                output_dir=str(ROOT / "data" / "cmci" / "audits"),
            )
            lookahead = audit.run_lookahead_audit(
                created_by="cmci-d6",
                sample_size=500,
                seed=7,
                output_dir=str(ROOT / "data" / "cmci" / "audits"),
            )
            audit_results = [
                {
                    "type": quality.job.audit_type,
                    "checked": quality.job.checked_count,
                    "violations": quality.job.violation_count,
                    "warnings": quality.job.warning_count,
                    "report": quality.job.report_path,
                },
                {
                    "type": lookahead.job.audit_type,
                    "checked": lookahead.job.checked_count,
                    "violations": lookahead.job.violation_count,
                    "warnings": lookahead.job.warning_count,
                    "report": lookahead.job.report_path,
                },
            ]

        report = {
            "dataset": DATASET_CODE,
            "version": version.version_no,
            "status": version.status,
            "partition_hash": version.partition_hash,
            "replays": replay_results,
            "audits": audit_results,
        }
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(item["violations"] == 0 for item in audit_results) else 1
    finally:
        registry.close()


def _add_members(
    service: ResearchDatasetService, version_id: str, *, actor: str = "cmci"
) -> None:
    code_by_id = {
        indicator.indicator_id: indicator.indicator_code
        for indicator in service.registry.list_indicators()
    }
    existing = {
        (code_by_id.get(member.indicator_id, member.indicator_id), member.usage_partition)
        for member in service.list_members(version_id)
    }

    def add(indicator_code: str, partition: str, start: str, end: str, notes: str) -> None:
        if (indicator_code, partition) in existing:
            return
        service.add_member(
            version_id,
            indicator_code=indicator_code,
            usage_partition=partition,
            time_start=start,
            time_end=end,
            embargo_before=90 if partition != "training" else 0,
            embargo_after=90 if partition != "validation" else 0,
            notes=notes,
            actor=actor,
        )

    for code in L1_MEMBERS:
        add(code, "not_applicable", "2015-01-01T00:00:00Z", "2026-11-28T23:59:59Z",
            "L1 macro and financial conditions")
    for code in L2_MEMBERS:
        add(code, "not_applicable", "2015-01-01T00:00:00Z", "2026-11-28T23:59:59Z",
            "L2 supply and network series")
    for code in L4_MEMBERS:
        start = "2024-01-11T00:00:00Z" if "ETF" in code else "2017-11-29T00:00:00Z"
        add(code, "not_applicable", start, "2026-11-28T23:59:59Z",
            "L4 capital transmission series")
    for code, partitions in L5_PLAN.items():
        for name, start, end in PARTITIONS:
            if name in partitions:
                add(code, name, start, end, "L5 market observation partition")


if __name__ == "__main__":
    raise SystemExit(main())