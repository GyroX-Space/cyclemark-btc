"""P0-3 acceptance tests: research datasets, dataset versions, L5 partitions."""

from __future__ import annotations

import sqlite3

import pytest

from cmci import PartitionConflictError, Registry, ResearchDatasetService
from cmci.registry import ConflictError, ValidationError


@pytest.fixture()
def ctx():
    registry = Registry(":memory:")
    price = registry.register_indicator(
        code="btc_spot_close_usd",
        name="BTC spot close",
        description="Daily BTC close in USD.",
        layer="L5",
        category="market_price",
        unit="USD",
        frequency="daily",
        timezone="UTC",
        data_type="numeric",
        source_policy="test source only",
        update_method="file",
        revision_policy="append new vintage",
        quality_policy="reject empty values",
        usage_partition_policy="training / identification / validation",
    )
    volatility = registry.register_indicator(
        code="btc_realized_vol_30d",
        name="BTC 30d realized volatility",
        description="Rolling 30-day realized volatility.",
        layer="L5",
        category="market_volatility",
        unit="ratio",
        frequency="daily",
        timezone="UTC",
        data_type="numeric",
        source_policy="test source only",
        update_method="file",
        revision_policy="append new vintage",
        quality_policy="reject negative values",
        usage_partition_policy="training / identification / validation",
    )
    macro = registry.register_indicator(
        code="us_fed_balance_sheet",
        name="Fed balance sheet",
        description="Federal Reserve total assets.",
        layer="L1",
        category="central_bank",
        unit="USD",
        frequency="weekly",
        timezone="UTC",
        data_type="numeric",
        source_policy="test source only",
        update_method="file",
        revision_policy="vintage release",
        quality_policy="prefer vintage data",
    )
    for indicator in (price, volatility, macro):
        registry.set_indicator_status(
            indicator.indicator_code, "active", actor="tester", reason="acceptance"
        )
    service = ResearchDatasetService(registry)
    service.create_project(
        project_code="rp_cycle_lab",
        project_name="Cycle lab",
        description="Acceptance research project.",
        owner="tester",
    )
    try:
        yield registry, service, price, volatility, macro
    finally:
        registry.close()


def make_version(
    service: ResearchDatasetService,
    dataset_code: str = "btc_cycle_lab",
    *,
    time_start: str = "2015-01-01",
    time_end: str = "2024-12-31",
):
    service.create_dataset(
        "rp_cycle_lab",
        dataset_code=dataset_code,
        dataset_name="BTC cycle lab",
        description="Acceptance dataset.",
        created_by="tester",
    )
    return service.create_dataset_version(
        dataset_code,
        time_start=time_start,
        time_end=time_end,
        change_reason="initial version",
        created_by="tester",
    )


def test_create_project_dataset_version_and_members(ctx) -> None:
    registry, service, price, volatility, macro = ctx
    version = make_version(service)

    assert version.version_no == 1
    assert version.status == "draft"
    assert version.time_start == "2015-01-01T00:00:00Z"
    assert service.get_dataset("btc_cycle_lab").current_version_no == 1

    first = service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="training",
        time_start="2015-01-01",
        time_end="2018-12-31",
        embargo_after=30,
        actor="tester",
    )
    second = service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="validation",
        time_start="2019-03-01",
        time_end="2024-12-31",
        embargo_before=30,
        actor="tester",
    )
    assert first.usage_partition == "training"
    assert first.embargo_after == 30.0
    assert second.embargo_before == 30.0
    assert len(service.list_members(version.dataset_version_id)) == 2
    assert service.check_partition_conflicts(version.dataset_version_id) == []

    logs = registry.list_operation_logs(entity_type="dataset_member")
    assert {log.action for log in logs} == {"add"}
    assert len(logs) == 2


def test_identification_validation_overlap_rejected(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="identification",
        time_start="2015-01-01",
        time_end="2020-12-31",
    )

    with pytest.raises(PartitionConflictError) as info:
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="validation",
            time_start="2020-06-01",
            time_end="2024-12-31",
        )

    conflict = info.value.conflicts[0]
    assert conflict.first_partition == "identification"
    assert conflict.second_partition == "validation"
    assert conflict.overlap_start == "2020-06-01T00:00:00Z"
    assert conflict.overlap_end == "2020-12-31T00:00:00Z"
    assert len(service.list_members(version.dataset_version_id)) == 1


def test_training_identification_overlap_rejected(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="training",
        time_start="2015-01-01",
        time_end="2020-12-31",
    )
    with pytest.raises(PartitionConflictError):
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="identification",
            time_start="2020-12-01",
            time_end="2021-12-31",
        )


def test_embargo_gap_is_enforced(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="identification",
        time_start="2015-01-01",
        time_end="2020-12-31",
        embargo_after=30,
    )

    with pytest.raises(PartitionConflictError) as info:
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="validation",
            time_start="2021-01-01",
            time_end="2024-12-31",
        )
    conflict = info.value.conflicts[0]
    assert conflict.gap_days == 1.0
    assert conflict.required_embargo_days == 30.0

    accepted = service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="validation",
        time_start="2021-03-01",
        time_end="2024-12-31",
        embargo_before=10,
    )
    assert accepted.usage_partition == "validation"


def test_same_partition_multiple_windows_allowed(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    for start, end in (("2015-01-01", "2016-12-31"), ("2018-01-01", "2019-12-31")):
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="training",
            time_start=start,
            time_end=end,
        )
    assert len(service.list_members(version.dataset_version_id)) == 2
    assert service.check_partition_conflicts(version.dataset_version_id) == []


def test_different_indicators_do_not_conflict(ctx) -> None:
    _, service, price, volatility, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="identification",
        time_start="2015-01-01",
        time_end="2020-12-31",
    )
    service.add_member(
        version.dataset_version_id,
        indicator_code=volatility.indicator_code,
        usage_partition="validation",
        time_start="2015-01-01",
        time_end="2020-12-31",
    )
    assert service.check_partition_conflicts(version.dataset_version_id) == []


def test_l5_member_requires_three_way_partition(ctx) -> None:
    _, service, price, _, macro = ctx
    version = make_version(service)
    with pytest.raises(ValidationError, match="L5"):
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="not_applicable",
            time_start="2015-01-01",
            time_end="2016-12-31",
        )
    member = service.add_member(
        version.dataset_version_id,
        indicator_code=macro.indicator_code,
        usage_partition="not_applicable",
        time_start="2015-01-01",
        time_end="2016-12-31",
    )
    assert member.usage_partition == "not_applicable"


def test_direct_sql_cannot_bypass_l5_partition_rule(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    with pytest.raises(sqlite3.IntegrityError, match="L5 dataset member"):
        service.conn.execute(
            "INSERT INTO dataset_members (member_id, dataset_version_id, indicator_id, "
            "usage_partition, time_start, time_end, embargo_before, embargo_after, "
            "partition_version, notes, created_by, created_at_utc) "
            "VALUES ('dsm_direct', ?, ?, 'not_applicable', ?, ?, 0, 0, 1, NULL, 'tester', ?)",
            (
                version.dataset_version_id,
                price.indicator_id,
                "2015-01-01T00:00:00Z",
                "2016-12-31T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )


def test_member_window_must_stay_inside_version(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service, time_start="2018-01-01", time_end="2022-12-31")
    with pytest.raises(ValidationError, match="时间范围"):
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="training",
            time_start="2017-01-01",
            time_end="2019-12-31",
        )


def test_sealed_version_blocks_new_members(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="validation",
        time_start="2020-01-01",
        time_end="2024-12-31",
    )
    sealed = service.seal_version(
        version.dataset_version_id, actor="tester", reason="formal evaluation"
    )
    assert sealed.status == "sealed"
    assert sealed.sealed_at_utc
    assert len(sealed.partition_hash) == 64

    with pytest.raises(ConflictError, match="已封存"):
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="training",
            time_start="2015-01-01",
            time_end="2019-12-31",
        )

    with pytest.raises(sqlite3.IntegrityError, match="sealed"):
        service.conn.execute(
            "INSERT INTO dataset_members (member_id, dataset_version_id, indicator_id, "
            "usage_partition, time_start, time_end, embargo_before, embargo_after, "
            "partition_version, notes, created_by, created_at_utc) "
            "VALUES ('dsm_late', ?, ?, 'training', ?, ?, 0, 0, 1, NULL, 'tester', ?)",
            (
                version.dataset_version_id,
                price.indicator_id,
                "2015-01-01T00:00:00Z",
                "2016-12-31T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )


def test_sealed_version_cannot_be_reopened(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="validation",
        time_start="2020-01-01",
        time_end="2024-12-31",
    )
    service.seal_version(version.dataset_version_id, actor="tester", reason="formal evaluation")

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        service.conn.execute(
            "UPDATE dataset_versions SET status = 'draft', sealed_at_utc = NULL "
            "WHERE dataset_version_id = ?",
            (version.dataset_version_id,),
        )


def test_successor_version_invalidates_original_validation(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="validation",
        time_start="2020-01-01",
        time_end="2024-12-31",
    )
    sealed = service.seal_version(
        version.dataset_version_id, actor="tester", reason="formal evaluation"
    )

    successor = service.create_dataset_version(
        "btc_cycle_lab",
        time_start="2015-01-01",
        time_end="2024-12-31",
        change_reason="rebalance partitions after formal evaluation",
        created_by="tester",
        replaces_version_id=version.dataset_version_id,
    )

    assert successor.version_no == 2
    assert successor.status == "draft"
    assert successor.replaces_version_id == version.dataset_version_id
    assert successor.invalidates_independent_validation is True
    old = service.get_version(version.dataset_version_id)
    assert old.status == "superseded"
    assert old.sealed_at_utc == sealed.sealed_at_utc
    assert old.partition_hash == sealed.partition_hash

    with pytest.raises(ValidationError, match="草稿"):
        service.create_dataset_version(
            "btc_cycle_lab",
            time_start="2015-01-01",
            time_end="2024-12-31",
            change_reason="invalid replace",
            created_by="tester",
            replaces_version_id=successor.dataset_version_id,
        )

    # The successor still needs its own members and can register a different partition.
    service.add_member(
        successor.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="training",
        time_start="2020-01-01",
        time_end="2024-12-31",
    )
    assert service.check_partition_conflicts(successor.dataset_version_id) == []


def test_partition_hash_is_deterministic(ctx) -> None:
    _, service, price, _, _ = ctx
    hashes = []
    for code in ("hash_a", "hash_b"):
        service.create_dataset(
            "rp_cycle_lab",
            dataset_code=code,
            dataset_name=code,
            description="hash test",
            created_by="tester",
        )
        version = service.create_dataset_version(
            code,
            time_start="2018-01-01",
            time_end="2022-12-31",
            change_reason="initial version",
            created_by="tester",
        )
        service.add_member(
            version.dataset_version_id,
            indicator_code=price.indicator_code,
            usage_partition="training",
            time_start="2018-01-01",
            time_end="2019-12-31",
        )
        sealed = service.seal_version(
            version.dataset_version_id, actor="tester", reason="seal"
        )
        hashes.append(sealed.partition_hash)
    assert hashes[0] == hashes[1]


def test_seal_without_members_is_rejected(ctx) -> None:
    _, service, _, _, _ = ctx
    version = make_version(service)
    with pytest.raises(ValidationError, match="至少需要登记一个成员"):
        service.seal_version(version.dataset_version_id, actor="tester", reason="empty")


def test_members_are_append_only(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    member = service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="training",
        time_start="2015-01-01",
        time_end="2016-12-31",
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        service.conn.execute(
            "UPDATE dataset_members SET notes = 'edited' WHERE member_id = ?",
            (member.member_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        service.conn.execute(
            "DELETE FROM dataset_members WHERE member_id = ?", (member.member_id,)
        )


def test_conflict_check_detects_direct_sql_overlap(ctx) -> None:
    _, service, price, _, _ = ctx
    version = make_version(service)
    service.add_member(
        version.dataset_version_id,
        indicator_code=price.indicator_code,
        usage_partition="identification",
        time_start="2015-01-01",
        time_end="2020-12-31",
    )
    # Bypass the service to prove the audit check is independent of insertion path.
    service.conn.execute(
        "INSERT INTO dataset_members (member_id, dataset_version_id, indicator_id, "
        "usage_partition, time_start, time_end, embargo_before, embargo_after, "
        "partition_version, notes, created_by, created_at_utc) "
        "VALUES ('dsm_audit', ?, ?, 'validation', ?, ?, 0, 0, 1, NULL, 'tester', ?)",
        (
            version.dataset_version_id,
            price.indicator_id,
            "2020-01-01T00:00:00Z",
            "2024-12-31T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conflicts = service.check_partition_conflicts(version.dataset_version_id)
    assert len(conflicts) == 1
    with pytest.raises(PartitionConflictError):
        service.seal_version(version.dataset_version_id, actor="tester", reason="audit")