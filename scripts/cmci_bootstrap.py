"""Create the local CMCI database and register the starting L1-L5 dictionary.

Run: python scripts/cmci_bootstrap.py [--db data/cmci/cmci.db]

The script is idempotent: existing indicators and sources are left unchanged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cmci import Registry  # noqa: E402
from cmci.registry import NotFoundError  # noqa: E402

DEFAULT_DB = ROOT / "data" / "cmci" / "cmci.db"

SOURCES: list[dict] = [
    {
        "key": "fred",
        "source_name": "FRED — Federal Reserve Economic Data",
        "provider": "Federal Reserve Bank of St. Louis",
        "source_type": "api",
        "base_url": "https://fred.stlouisfed.org",
        "access_method": "REST API",
        "auth_type": "api_key (environment only)",
        "license_type": "Public domain with attribution",
        "update_frequency": "series dependent",
        "historical_coverage": "series dependent, often 1950s onward",
        "revision_support": True,
        "reliability_grade": "A",
        "status": "active",
        "notes": "Macro series; releases and revisions are tracked per observation.",
    },
    {
        "key": "binance",
        "source_name": "Binance Market Data",
        "provider": "Binance",
        "source_type": "api",
        "base_url": "https://api.binance.com",
        "access_method": "public REST API",
        "auth_type": "none for public market data",
        "license_type": "Provider terms; no redistribution",
        "update_frequency": "daily and intraday",
        "historical_coverage": "exchange listing onward",
        "revision_support": False,
        "reliability_grade": "A",
        "status": "active",
        "notes": "Raw exchange observations only.",
    },
    {
        "key": "etf_disclosures",
        "source_name": "US Spot BTC ETF disclosures",
        "provider": "ETF issuers",
        "source_type": "file",
        "base_url": "https://www.sec.gov",
        "access_method": "CSV/JSON import from issuer disclosures",
        "auth_type": "none",
        "license_type": "Public disclosure",
        "update_frequency": "daily on trading days",
        "historical_coverage": "2024 onward",
        "revision_support": True,
        "reliability_grade": "B",
        "status": "active",
        "notes": "Flow figures must be reconciled across issuers.",
    },
    {
        "key": "onchain_public",
        "source_name": "Public on-chain aggregates",
        "provider": "Multiple public explorers",
        "source_type": "file",
        "base_path": None,
        "access_method": "CSV/JSON import",
        "auth_type": "none",
        "license_type": "Public data",
        "update_frequency": "daily",
        "historical_coverage": "chain genesis onward",
        "revision_support": False,
        "reliability_grade": "B",
        "status": "active",
        "notes": "Chain-tip reorgs may shift recent values; mark time precision.",
    },
    {
        "key": "manual",
        "source_name": "CMCI manual registration",
        "provider": "CMCI",
        "source_type": "manual",
        "base_url": None,
        "access_method": "manual entry",
        "auth_type": "none",
        "license_type": "Internal",
        "update_frequency": "as needed",
        "historical_coverage": "as recorded",
        "revision_support": True,
        "reliability_grade": "B",
        "status": "active",
        "notes": "Used for protocol events and curated reference values.",
    },
]

L5_POLICY = "training / identification / validation per research task; no cross-partition reuse"
L5_SCOPE = "register actual partition on dataset_members, not on the indicator"

INDICATORS: list[dict] = [
    {
        "code": "us_cpi_yoy",
        "name": "US CPI year-over-year",
        "description": "Consumer price index, all urban consumers, year-over-year percent change.",
        "layer": "L1",
        "category": "inflation",
        "sub_category": "headline_cpi",
        "unit": "percent",
        "frequency": "monthly",
        "timezone": "America/New_York",
        "data_type": "numeric",
        "source_policy": "FRED only; no vendor-computed inflation series",
        "update_method": "api",
        "revision_policy": "seasonal adjustment revisions; keep every vintage",
        "history_start": "1948-01-01",
        "quality_policy": "flag missing release_time; never fill gaps",
        "primary_source": "fred",
    },
    {
        "code": "fed_total_assets_usd",
        "name": "Federal Reserve total assets",
        "description": "Total assets of the Federal Reserve, weekly average, USD billions.",
        "layer": "L1",
        "category": "liquidity",
        "sub_category": "central_bank_balance_sheet",
        "unit": "USD billion",
        "frequency": "weekly",
        "timezone": "America/New_York",
        "data_type": "numeric",
        "source_policy": "FRED only",
        "update_method": "api",
        "revision_policy": "append vintage on revision",
        "history_start": "2002-12-18",
        "quality_policy": "detect level jumps attributed to source definition change",
        "primary_source": "fred",
    },
    {
        "code": "btc_new_issuance_btc",
        "name": "BTC new issuance",
        "description": "BTC issued per period, derived from protocol schedule and block height.",
        "layer": "L2",
        "category": "supply",
        "sub_category": "issuance",
        "unit": "BTC",
        "frequency": "daily",
        "timezone": "UTC",
        "data_type": "numeric",
        "source_policy": "protocol constants plus on-chain block heights",
        "update_method": "file",
        "revision_policy": "immutable for confirmed heights; new vintage for reorgs",
        "history_start": "2009-01-03",
        "quality_policy": "cross-check halving heights against known events",
        "primary_source": "onchain_public",
    },
    {
        "code": "crypto_retail_search_interest",
        "name": "Crypto retail search interest",
        "description": "Relative search interest for crypto terms as a demand-side attention proxy.",
        "layer": "L3",
        "category": "demand",
        "sub_category": "retail_attention",
        "unit": "index",
        "frequency": "weekly",
        "timezone": "UTC",
        "data_type": "numeric",
        "source_policy": "public search interest only; no survey substitution",
        "update_method": "file",
        "revision_policy": "append revision when the provider restates",
        "history_start": "2015-01-04",
        "quality_policy": "flag structural breaks from search methodology changes",
        "primary_source": "manual",
    },
    {
        "code": "btc_spot_etf_net_flow_usd",
        "name": "US spot BTC ETF net flow",
        "description": "Aggregated daily net creation/redemption flow across US spot BTC ETFs.",
        "layer": "L4",
        "category": "capital_flow",
        "sub_category": "etf",
        "unit": "USD",
        "frequency": "daily",
        "timezone": "America/New_York",
        "data_type": "numeric",
        "source_policy": "issuer disclosures only; no aggregator estimates",
        "update_method": "file",
        "revision_policy": "append revision when issuers restate",
        "history_start": "2024-01-11",
        "quality_policy": "flag days where issuer coverage is incomplete",
        "primary_source": "etf_disclosures",
    },
    {
        "code": "btc_spot_close_usd",
        "name": "BTC spot close",
        "description": "Daily BTC/USDT close price from the exchange market data API.",
        "layer": "L5",
        "category": "market_price",
        "sub_category": "spot",
        "unit": "USD",
        "frequency": "daily",
        "timezone": "UTC",
        "data_type": "numeric",
        "source_policy": "Binance market data only",
        "update_method": "api",
        "revision_policy": "append new vintage on correction; never overwrite",
        "history_start": "2017-08-17",
        "quality_policy": "reject non-positive prices and duplicate timestamps",
        "usage_partition_policy": L5_POLICY,
        "partition_scope": L5_SCOPE,
        "primary_source": "binance",
    },
    {
        "code": "btc_spot_volume_usd",
        "name": "BTC spot volume",
        "description": "Daily BTC/USDT quote volume from the exchange market data API.",
        "layer": "L5",
        "category": "market_activity",
        "sub_category": "spot",
        "unit": "USD",
        "frequency": "daily",
        "timezone": "UTC",
        "data_type": "numeric",
        "source_policy": "Binance market data only",
        "update_method": "api",
        "revision_policy": "append new vintage on correction",
        "history_start": "2017-08-17",
        "quality_policy": "flag zero-volume and outlier days",
        "usage_partition_policy": L5_POLICY,
        "partition_scope": L5_SCOPE,
        "primary_source": "binance",
    },
    {
        "code": "btc_dominance_pct",
        "name": "BTC dominance",
        "description": "BTC share of total crypto market capitalisation.",
        "layer": "L5",
        "category": "market_structure",
        "sub_category": "dominance",
        "unit": "percent",
        "frequency": "daily",
        "timezone": "UTC",
        "data_type": "numeric",
        "source_policy": "computed from raw market caps; no vendor index",
        "update_method": "file",
        "revision_policy": "append on restatement",
        "history_start": "2013-04-28",
        "quality_policy": "flag coverage gaps in constituent market caps",
        "usage_partition_policy": L5_POLICY,
        "partition_scope": L5_SCOPE,
        "primary_source": "onchain_public",
    },
    {
        "code": "btc_halving_block_height",
        "name": "BTC halving block height",
        "description": "Known future and historical halving block heights with protocol schedule.",
        "layer": "L2",
        "category": "supply_event",
        "sub_category": "halving",
        "unit": "block height",
        "frequency": "event",
        "timezone": "UTC",
        "data_type": "count",
        "source_policy": "protocol constants and public chain data",
        "update_method": "manual",
        "revision_policy": "append only after confirmation",
        "history_start": "2012-11-28",
        "quality_policy": "compare with known_future_events registry",
        "primary_source": "manual",
    },
]


def ensure_source(registry: Registry, spec: dict) -> str:
    payload = dict(spec)
    key = payload.pop("key")
    payload.pop("base_path", None)
    for source in registry.list_sources():
        if source.source_name == payload["source_name"]:
            return source.source_id
    created = registry.register_source(**payload)
    print(f"source  + {key}: {created.source_name}")
    return created.source_id


def ensure_indicator(registry: Registry, spec: dict, source_ids: dict[str, str]) -> bool:
    payload = dict(spec)
    source_key = payload.pop("primary_source")
    code = payload["code"]
    try:
        registry.get_indicator(code)
        print(f"indicator = {code}")
        return False
    except NotFoundError:
        pass
    indicator = registry.register_indicator(actor="cmci_bootstrap", **payload)
    registry.link_source(
        indicator.indicator_code,
        source_ids[source_key],
        actor="cmci_bootstrap",
        notes="initial primary source",
    )
    registry.set_indicator_status(
        indicator.indicator_code,
        "active",
        actor="cmci_bootstrap",
        reason="initial L1-L5 dictionary registration",
    )
    print(f"indicator + {indicator.indicator_code} ({indicator.layer})")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialise the CMCI database")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    args = parser.parse_args(argv)

    registry = Registry(args.db)
    try:
        source_ids = {spec["key"]: ensure_source(registry, spec) for spec in SOURCES}
        created = sum(
            ensure_indicator(registry, spec, source_ids) for spec in INDICATORS
        )
        indicators = registry.list_indicators()
        by_layer: dict[str, int] = {}
        for indicator in indicators:
            by_layer[indicator.layer] = by_layer.get(indicator.layer, 0) + 1
        summary = ", ".join(f"{layer}={count}" for layer, count in sorted(by_layer.items()))
        print(f"database: {args.db}")
        print(f"new indicators: {created}; total: {len(indicators)} ({summary})")
    finally:
        registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())