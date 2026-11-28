"""P0-1 acceptance tests: indicator dictionary, source registry, append-only rules."""

from __future__ import annotations

import sqlite3

import pytest

from cmci import Registry
from cmci.registry import ConflictError, NotFoundError, StateTransitionError, ValidationError


@pytest.fixture()
def registry() -> Registry:
    store = Registry(":memory:")
    try:
        yield store
    finally:
        store.close()


def indicator_payload(**overrides: object) -> dict:
    payload: dict = {
        "code": "btc_spot_close_usd",
        "name": "BTC spot close",
        "description": "Daily BTC close price in USD.",
        "layer": "L5",
        "category": "market_price",
        "unit": "USD",
        "frequency": "daily",
        "timezone": "UTC",
        "data_type": "numeric",
        "source_policy": "Binance market data only",
        "update_method": "api",
        "revision_policy": "append a new vintage on correction",
        "quality_policy": "reject non-positive values",
        "usage_partition_policy": "training / identification / validation per research task",
    }
    payload.update(overrides)
    return payload


def register(registry: Registry, **overrides: object):
    return registry.register_indicator(**indicator_payload(**overrides))


def make_source(registry: Registry, name: str = "Binance"):
    return registry.register_source(
        source_name=name,
        provider="Binance",
        source_type="api",
        access_method="public REST API",
        status="active",
    )


def test_register_l5_indicator_defaults_to_candidate(registry: Registry) -> None:
    indicator = register(registry)

    assert indicator.status == "candidate"
    assert indicator.version == 1
    assert indicator.layer == "L5"
    assert indicator.usage_partition_policy
    assert indicator.created_at_utc.endswith("Z")
    assert indicator.created_at_utc == indicator.updated_at_utc
    assert registry.get_indicator("btc_spot_close_usd").indicator_code == "btc_spot_close_usd"


def test_l1_indicator_does_not_require_partition_policy(registry: Registry) -> None:
    indicator = register(
        registry,
        code="us_cpi_yoy",
        layer="L1",
        category="inflation",
        frequency="monthly",
        usage_partition_policy=None,
    )

    assert indicator.usage_partition_policy is None


def test_l5_indicator_requires_partition_policy(registry: Registry) -> None:
    with pytest.raises(ValidationError):
        register(registry, usage_partition_policy=None)
    with pytest.raises(ValidationError):
        register(registry, usage_partition_policy="   ")


def test_duplicate_indicator_code_is_rejected(registry: Registry) -> None:
    register(registry)
    with pytest.raises(ConflictError):
        register(registry, name="Another name")


def test_registration_rejects_non_candidate_status(registry: Registry) -> None:
    with pytest.raises(ValidationError):
        register(registry, status="active")


def test_unknown_layer_is_rejected(registry: Registry) -> None:
    with pytest.raises(ValidationError):
        register(registry, layer="L7")


def test_history_window_order_is_enforced(registry: Registry) -> None:
    with pytest.raises(ValidationError):
        register(registry, history_start="2024-01-01", history_end="2023-01-01")

    indicator = register(registry, history_start="2020-01-01", history_end="2024-01-01")
    assert indicator.history_start == "2020-01-01T00:00:00Z"


def test_update_writes_version_snapshot(registry: Registry) -> None:
    register(registry)

    updated = registry.update_indicator(
        "btc_spot_close_usd",
        actor="analyst",
        reason="clarify unit wording",
        unit="US dollar",
    )

    assert updated.version == 2
    assert updated.unit == "US dollar"
    versions = registry.indicator_versions("btc_spot_close_usd")
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].snapshot.unit == "USD"
    assert versions[0].change_reason == "clarify unit wording"
    assert versions[0].changed_by == "analyst"


def test_update_rejects_layer_change_and_immutable_fields(registry: Registry) -> None:
    register(registry)

    with pytest.raises(ValidationError):
        registry.update_indicator(
            "btc_spot_close_usd", actor="analyst", reason="reclassify", layer="L4"
        )
    with pytest.raises(ValidationError):
        registry.update_indicator(
            "btc_spot_close_usd", actor="analyst", reason="rename", indicator_id="ind_other"
        )
    with pytest.raises(ValidationError):
        registry.update_indicator("btc_spot_close_usd", actor="analyst", reason="noop")


def test_update_requires_reason(registry: Registry) -> None:
    register(registry)
    with pytest.raises(ValidationError):
        registry.update_indicator("btc_spot_close_usd", actor="analyst", reason="   ", unit="x")


def test_status_transitions(registry: Registry) -> None:
    register(registry)

    active = registry.set_indicator_status(
        "btc_spot_close_usd", "active", actor="reviewer", reason="dictionary approved"
    )
    assert active.status == "active"

    with pytest.raises(StateTransitionError):
        registry.set_indicator_status(
            "btc_spot_close_usd", "candidate", actor="reviewer", reason="revert"
        )

    disabled = registry.set_indicator_status(
        "btc_spot_close_usd", "disabled", actor="reviewer", reason="source retired"
    )
    assert disabled.status == "disabled"
    assert disabled.version == 3


def test_source_registration_and_mapping(registry: Registry) -> None:
    register(registry)
    source = make_source(registry)

    link = registry.link_source("btc_spot_close_usd", source.source_id, role="primary")
    assert link.source_name == "Binance"
    assert link.effective_to_utc is None

    active_links = registry.list_indicator_sources("btc_spot_close_usd", active_only=True)
    assert [item.mapping_id for item in active_links] == [link.mapping_id]


def test_only_one_active_primary_source(registry: Registry) -> None:
    register(registry)
    first = make_source(registry, "Binance")
    second = make_source(registry, "Coinbase")

    registry.link_source("btc_spot_close_usd", first.source_id, role="primary")
    with pytest.raises(ConflictError):
        registry.link_source("btc_spot_close_usd", second.source_id, role="primary")

    secondary = registry.link_source("btc_spot_close_usd", second.source_id, role="secondary")
    assert secondary.role == "secondary"


def test_closing_primary_allows_new_primary(registry: Registry) -> None:
    register(registry)
    first = make_source(registry, "Binance")
    second = make_source(registry, "Coinbase")

    link = registry.link_source("btc_spot_close_usd", first.source_id, role="primary")
    closed = registry.close_source_link(link.mapping_id, actor="analyst")
    assert closed.effective_to_utc is not None

    with pytest.raises(ConflictError):
        registry.close_source_link(link.mapping_id, actor="analyst")

    replacement = registry.link_source("btc_spot_close_usd", second.source_id, role="primary")
    assert replacement.effective_to_utc is None


def test_unknown_indicator_raises_not_found(registry: Registry) -> None:
    with pytest.raises(NotFoundError):
        registry.get_indicator("missing_indicator")


def test_list_filters_by_layer_and_status(registry: Registry) -> None:
    register(registry)
    register(
        registry,
        code="us_cpi_yoy",
        layer="L1",
        category="inflation",
        frequency="monthly",
        usage_partition_policy=None,
    )
    registry.set_indicator_status(
        "us_cpi_yoy", "active", actor="reviewer", reason="approved"
    )

    assert [item.indicator_code for item in registry.list_indicators(layer="L1")] == [
        "us_cpi_yoy"
    ]
    assert [item.indicator_code for item in registry.list_indicators(status="candidate")] == [
        "btc_spot_close_usd"
    ]


def test_indicator_versions_are_append_only(registry: Registry) -> None:
    register(registry)
    registry.update_indicator("btc_spot_close_usd", actor="analyst", reason="fix", unit="USD ")

    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute(
            "UPDATE indicator_versions SET change_reason = 'rewritten' WHERE version = 1"
        )
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute("DELETE FROM indicator_versions WHERE version = 1")


def test_operation_logs_are_append_only(registry: Registry) -> None:
    register(registry)

    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute("UPDATE operation_logs SET actor = 'someone_else'")
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute("DELETE FROM operation_logs")


def test_operation_log_records_governance_actions(registry: Registry) -> None:
    register(registry)

    entries = registry.list_operation_logs(entity_type="indicator")
    assert entries
    assert entries[0].action == "register"
    assert entries[0].actor == "system"


def test_database_check_blocks_l5_without_policy(registry: Registry) -> None:
    now = "2026-01-01T00:00:00Z"
    with pytest.raises(sqlite3.IntegrityError):
        registry.conn.execute(
            "INSERT INTO indicators (indicator_id, indicator_code, indicator_name, description, "
            "layer, category, unit, frequency, timezone, data_type, source_policy, update_method, "
            "revision_policy, quality_policy, status, version, created_at_utc, updated_at_utc) "
            "VALUES ('ind_x', 'l5_without_policy', 'x', 'x', 'L5', 'c', 'u', 'daily', 'UTC', "
            "'numeric', 'p', 'api', 'r', 'q', 'candidate', 1, ?, ?)",
            (now, now),
        )