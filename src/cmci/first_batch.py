"""First real-data batch (D1-D5) and derived series.

Registers the agreed indicator universe together with governance metadata,
then ingests each batch through the existing append-only ingestion service.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import connectors
from .constants import Layer, UpdateMethod
from .governance import GovernanceService
from .importers import ColumnMapping
from .ingestion import IngestionResult, IngestionService
from .registry import Registry

TARGET_START = "2015-01-01"
L5_PARTITION_POLICY = (
    "L5 semantics require a usage partition (training / identification / validation) "
    "registered in research datasets; one window may not cross partitions."
)
L5_PARTITION_SCOPE = "market outcome observations used for model input or validation"


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    code: str
    name: str
    layer: Layer
    category: str
    unit: str
    frequency: str
    data_type: str
    description: str
    source_grade: str
    measurement_scope: str
    proxy_flag: bool
    license_status: str
    coverage_status: str
    coverage_start: str | None = None
    sub_category: str | None = None
    update_method: UpdateMethod = UpdateMethod.API


FRED_SERIES: dict[str, str] = {
    "FED_BALANCE_SHEET": "WALCL",
    "FED_FUNDS_RATE": "DFF",
    "US_10Y_YIELD": "DGS10",
    "US_10Y_REAL_YIELD": "DFII10",
    "USD_BROAD_INDEX": "DTWEXBGS",
    "VIX": "VIXCLS",
    "HY_CREDIT_SPREAD": "BAMLH0A0HYM2",
    "US_YIELD_CURVE_10Y2Y": "T10Y2Y",
    "US_CPI": "CPIAUCSL",
    "US_UNEMPLOYMENT": "UNRATE",
}

FRED_LABELS: dict[str, tuple[str, str, str]] = {
    "FED_BALANCE_SHEET": ("美联储总资产", "USD millions", "weekly"),
    "FED_FUNDS_RATE": ("联邦基金有效利率", "percent", "daily"),
    "US_10Y_YIELD": ("美国10年期国债收益率", "percent", "daily"),
    "US_10Y_REAL_YIELD": ("美国10年期实际利率", "percent", "daily"),
    "USD_BROAD_INDEX": ("美元广义指数", "index", "daily"),
    "VIX": ("VIX 波动率指数", "index", "daily"),
    "HY_CREDIT_SPREAD": ("高收益债信用利差", "percent", "daily"),
    "US_YIELD_CURVE_10Y2Y": ("10年期减2年期国债收益率", "percent", "daily"),
    "US_CPI": ("美国 CPI", "index", "monthly"),
    "US_UNEMPLOYMENT": ("美国失业率", "percent", "monthly"),
}

_INDICATORS: list[IndicatorSpec] = [
    *[
        IndicatorSpec(
            code=code,
            name=FRED_LABELS[code][0],
            layer=Layer.L1,
            category="macro",
            unit=FRED_LABELS[code][1],
            frequency=FRED_LABELS[code][2],
            data_type="numeric",
            description=f"FRED series {series_id}; historical vintages are preserved via ALFRED.",
            source_grade="A",
            measurement_scope=f"FRED series {series_id} as published by the source agency",
            proxy_flag=False,
            license_status="internal_research",
            coverage_status="full_target_coverage",
            coverage_start=TARGET_START,
            update_method=UpdateMethod.API,
        )
        for code, series_id in FRED_SERIES.items()
    ],
    # L2
    IndicatorSpec("BTC_CIRCULATING_SUPPLY", "BTC 流通供应量", Layer.L2, "btc_supply", "BTC", "daily", "numeric",
                  "Total coins in circulation from Blockchain.com.", "A", "network-wide BTC supply", False,
                  "internal_research", "full_target_coverage", TARGET_START),
    IndicatorSpec("BTC_ISSUANCE", "BTC 新增发行量", Layer.L2, "btc_supply", "BTC", "daily", "numeric",
                  "Daily change in circulating supply, derived within CMCI.", "A", "derived from BTC_CIRCULATING_SUPPLY",
                  False, "internal_research", "full_target_coverage", TARGET_START, update_method=UpdateMethod.MANUAL),
    IndicatorSpec("BTC_HASHRATE", "全网算力", Layer.L2, "btc_network", "hashes/s", "daily", "numeric",
                  "Network hash rate from Blockchain.com.", "A", "network-wide hash rate", False,
                  "internal_research", "full_target_coverage", TARGET_START),
    IndicatorSpec("BTC_DIFFICULTY", "挖矿难度", Layer.L2, "btc_network", "difficulty", "daily", "numeric",
                  "Mining difficulty from Blockchain.com.", "A", "network-wide difficulty", False,
                  "internal_research", "full_target_coverage", TARGET_START),
    IndicatorSpec("BTC_MINER_REVENUE", "矿工收入", Layer.L2, "btc_network", "USD", "daily", "numeric",
                  "Estimated miner revenue in USD from Blockchain.com.", "A", "network-wide miner revenue estimate",
                  False, "internal_research", "full_target_coverage", TARGET_START),
    IndicatorSpec("BTC_NETWORK_ACTIVITY", "链上交易数量", Layer.L2, "btc_network", "transactions", "daily", "numeric",
                  "Daily on-chain transaction count from Blockchain.com.", "B", "network-wide transaction count",
                  False, "internal_research", "full_target_coverage", TARGET_START),
    IndicatorSpec("BTC_UNIQUE_ADDRESSES", "活跃地址代理指标", Layer.L2, "btc_network", "addresses", "daily", "numeric",
                  "Unique addresses used per day; a proxy for activity, not user count.", "B",
                  "network-wide unique address proxy", True, "internal_research", "full_target_coverage", TARGET_START),
    # L3
    IndicatorSpec("BTC_NETWORK_USAGE", "BTC 网络使用活动", Layer.L3, "usage_proxy", "transactions", "daily", "numeric",
                  "On-chain usage proxy; not investment demand and not capital inflow.", "B",
                  "BTC network usage proxy", True, "internal_research", "partial_coverage", TARGET_START),
    IndicatorSpec("BTC_SEARCH_INTEREST", "Bitcoin 搜索热度", Layer.L3, "attention_proxy", "index", "weekly", "numeric",
                  "Relative search interest; attention proxy, not purchase intention.", "B",
                  "Google Trends relative index", True, "unknown", "unavailable", None, update_method=UpdateMethod.MANUAL),
    IndicatorSpec("ETH_NETWORK_USAGE", "ETH 网络使用活动", Layer.L3, "usage_proxy", "transactions", "daily", "numeric",
                  "Ethereum usage proxy; not investment demand and not capital inflow.", "B",
                  "ETH network usage proxy", True, "unknown", "unavailable", None, update_method=UpdateMethod.MANUAL),
    # L4
    IndicatorSpec("STABLECOIN_TOTAL_SUPPLY", "稳定币总供应量", Layer.L4, "stablecoin", "USD", "daily", "numeric",
                  "Sum of USD-pegged stablecoin circulating value from DefiLlama.", "A",
                  "all tracked pegged stablecoins, USD value", False, "internal_research", "partial_coverage", "2017-11-29"),
    IndicatorSpec("STABLECOIN_SUPPLY_CHANGE", "稳定币供应量变化", Layer.L4, "stablecoin", "USD", "daily", "numeric",
                  "Daily change in USD-pegged stablecoin supply, derived within CMCI.", "A",
                  "derived from STABLECOIN_TOTAL_SUPPLY", False, "internal_research", "partial_coverage",
                  "2017-11-30", update_method=UpdateMethod.MANUAL),
    IndicatorSpec("BTC_SPOT_ETF_NET_FLOW", "美国现货 BTC ETF 净流入", Layer.L4, "etf_flow", "USD", "trading_day", "numeric",
                  "Daily US spot Bitcoin ETF net flow; structurally new from 2024-01-11.", "A",
                  "US spot Bitcoin ETFs only", False, "internal_and_commercial", "partial_coverage", "2024-01-11"),
    IndicatorSpec("BTC_SPOT_ETF_AUM", "美国现货 BTC ETF 资产规模", Layer.L4, "etf_flow", "USD", "trading_day", "numeric",
                  "Combined total net assets of US spot Bitcoin ETFs.", "B",
                  "US spot Bitcoin ETFs only", False, "internal_and_commercial", "partial_coverage", "2024-01-11"),
    # L5
    IndicatorSpec("BTC_USD_OHLCV", "BTC/USD 日线 OHLCV", Layer.L5, "price", "USD", "daily", "numeric",
                  "Daily BTC/USD bar; exchange-derived close and OHLCV text.", "A",
                  "single-venue reference series, not a global index", False, "internal_research",
                  "full_target_coverage", TARGET_START),
    IndicatorSpec("ETH_USD_OHLCV", "ETH/USD 日线 OHLCV", Layer.L5, "price", "USD", "daily", "numeric",
                  "Daily ETH/USD bar; exchange-derived close and OHLCV text.", "A",
                  "single-venue reference series, not a global index", False, "internal_research",
                  "partial_coverage", "2015-08-07"),
    IndicatorSpec("BTC_VOLUME", "BTC 成交量", Layer.L5, "price", "BTC", "daily", "numeric",
                  "Daily venue volume for the reference BTC/USD pair.", "A",
                  "single-venue volume, not global volume", False, "internal_research", "full_target_coverage", TARGET_START),
    IndicatorSpec("BTC_RETURN", "BTC 日收益率", Layer.L5, "price", "ratio", "daily", "numeric",
                  "Daily close-to-close return derived within CMCI.", "A",
                  "derived from BTC_USD_OHLCV", False, "internal_research", "full_target_coverage",
                  TARGET_START, update_method=UpdateMethod.MANUAL),
    IndicatorSpec("BTC_REALIZED_VOL", "BTC 实现波动率", Layer.L5, "price", "ratio", "daily", "numeric",
                  "30-day realized volatility of daily log returns, annualized.", "A",
                  "derived from BTC_USD_OHLCV", False, "internal_research", "full_target_coverage",
                  TARGET_START, update_method=UpdateMethod.MANUAL),
    IndicatorSpec("BTC_DRAWDOWN", "BTC 回撤", Layer.L5, "price", "ratio", "daily", "numeric",
                  "Drawdown from the running maximum close, derived within CMCI.", "A",
                  "derived from BTC_USD_OHLCV", False, "internal_research", "full_target_coverage",
                  TARGET_START, update_method=UpdateMethod.MANUAL),
    IndicatorSpec("BTC_MARKET_DOMINANCE", "BTC 市场主导率", Layer.L5, "breadth", "percent", "daily", "numeric",
                  "BTC share of total crypto market value; source口径 pending.", "B",
                  "requires a defined full-market universe", False, "unknown", "unavailable", None,
                  update_method=UpdateMethod.MANUAL),
    IndicatorSpec("CRYPTO_MARKET_BREADTH", "Crypto 市场广度", Layer.L5, "breadth", "percent", "daily", "numeric",
                  "Share of tracked assets above trend; asset universe pending.", "B",
                  "requires a defined asset sample", False, "unknown", "unavailable", None,
                  update_method=UpdateMethod.MANUAL),
]

SPEC_BY_CODE: dict[str, IndicatorSpec] = {spec.code: spec for spec in _INDICATORS}

SOURCE_SPECS: dict[str, dict[str, Any]] = {
    "FRED": dict(source_name="FRED / ALFRED", provider="Federal Reserve Bank of St. Louis",
                 source_type="api", base_url="https://api.stlouisfed.org/fred",
                 access_method="REST API with free API key", auth_type="api_key",
                 license_type="FRED terms of use", update_frequency="daily",
                 historical_coverage="series dependent; back to 1960s for most series",
                 revision_support=True, reliability_grade="A",
                 notes="ALFRED vintages are mandatory; final revised values are not historical availability."),
    "BLOCKCHAIN": dict(source_name="Blockchain.com Charts", provider="Blockchain.com",
                       source_type="api", base_url="https://api.blockchain.info/charts",
                       access_method="public JSON charts", auth_type=None,
                       license_type="public charts, terms to review", update_frequency="daily",
                       historical_coverage="chart dependent; full BTC history",
                       revision_support=False, reliability_grade="B",
                       notes="Chart sampling may smooth values; availability dates are conservative."),
    "DEFILLAMA": dict(source_name="DefiLlama Stablecoins", provider="DefiLlama",
                      source_type="api", base_url="https://stablecoins.llama.fi",
                      access_method="public REST API", auth_type=None,
                      license_type="free API, terms to review", update_frequency="daily",
                      historical_coverage="stablecoin supply from 2017-11",
                      revision_support=True, reliability_grade="B",
                      notes="Supply is a stock; changes are not exchange inflows."),
    "TFTC": dict(source_name="TFTC Bitcoin ETF Tracker", provider="The Commoner / TFTC",
                 source_type="public_dataset", base_url="https://www.tftc.io/bitcoin-etf-flows",
                 access_method="public JSON", auth_type=None,
                 license_type="CC BY 4.0", update_frequency="each US trading session",
                 historical_coverage="2024-01-11 onwards", revision_support=True,
                 reliability_grade="A",
                 notes="Attribution required: The Commoner Bitcoin ETF Tracker by TFTC."),
    "YAHOO": dict(source_name="Yahoo Finance Chart", provider="Yahoo Finance",
                  source_type="api", base_url="https://query1.finance.yahoo.com",
                  access_method="public chart JSON", auth_type=None,
                  license_type="Yahoo terms; internal research only", update_frequency="daily",
                  historical_coverage="BTC-USD from 2014-09; ETH-USD from 2015-08",
                  revision_support=False, reliability_grade="B",
                  notes="Exchange-derived reference series, not a global index."),
    "KRAKEN": dict(source_name="Kraken OHLCVT", provider="Kraken",
                   source_type="file", base_url="https://support.kraken.com",
                   access_method="manual full-history OHLCVT export", auth_type=None,
                   license_type="Kraken terms; internal research only", update_frequency="manual",
                   historical_coverage="from each pair's first trade",
                   revision_support=False, reliability_grade="A",
                   notes="Single-venue volume; never label as global volume."),
    "DERIVED": dict(source_name="CMCI Derived Series", provider="CMCI",
                    source_type="manual", base_url=None,
                    access_method="computed inside CMCI", auth_type=None,
                    license_type="internal", update_frequency="daily",
                    historical_coverage="same as underlying series", revision_support=True,
                    reliability_grade="A",
                    notes="Deterministic transforms of registered series."),
}

LICENSE_SPECS: dict[str, dict[str, Any]] = {
    "FRED": dict(internal_research_allowed=True, commercial_use_allowed=False,
                 redistribution_allowed=False, attribution_required=True,
                 local_retention_allowed=True, terms_url="https://fred.stlouisfed.org/legal/"),
    "BLOCKCHAIN": dict(internal_research_allowed=True, commercial_use_allowed=False,
                       redistribution_allowed=False, attribution_required=True,
                       local_retention_allowed=True, terms_url="https://www.blockchain.com/legal/terms"),
    "DEFILLAMA": dict(internal_research_allowed=True, commercial_use_allowed=False,
                      redistribution_allowed=False, attribution_required=True,
                      local_retention_allowed=True, terms_url="https://defillama.com/terms"),
    "TFTC": dict(internal_research_allowed=True, commercial_use_allowed=True,
                 redistribution_allowed=True, attribution_required=True,
                 local_retention_allowed=True,
                 terms_url="https://creativecommons.org/licenses/by/4.0/"),
    "YAHOO": dict(internal_research_allowed=True, commercial_use_allowed=False,
                  redistribution_allowed=False, attribution_required=True,
                  local_retention_allowed=True, terms_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html"),
    "KRAKEN": dict(internal_research_allowed=True, commercial_use_allowed=False,
                   redistribution_allowed=False, attribution_required=True,
                   local_retention_allowed=True, terms_url="https://www.kraken.com/legal"),
    "DERIVED": dict(internal_research_allowed=True, commercial_use_allowed=False,
                    redistribution_allowed=False, attribution_required=False,
                    local_retention_allowed=True, terms_url=None),
}

MAPPING = ColumnMapping(
    period_start="period_start",
    period_end="period_end",
    value="value",
    value_text="value_text",
    available_time="available_time",
    available_time_precision="available_time_precision",
    available_time_method="available_time_method",
    vintage_time="vintage_time",
)


@dataclass
class BatchReport:
    batch: str
    results: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class FirstBatchService:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.conn = registry.conn
        self.ingestion = IngestionService(registry)
        self.governance = GovernanceService(registry)
        self.sources: dict[str, str] = {}

    # ------------------------------------------------------------ registration
    def ensure_registered(self, *, actor: str = "first-batch") -> None:
        for key, spec in SOURCE_SPECS.items():
            self.sources[key] = self._ensure_source(key, spec)
            terms = LICENSE_SPECS[key]
            if self.governance.get_source_license(self.sources[key], missing_ok=True) is None:
                self.governance.register_source_license(
                    self.sources[key], actor=actor, **terms
                )
        for spec in _INDICATORS:
            self._ensure_indicator(spec, actor=actor)
        self._seed_halvings()

    def _ensure_source(self, key: str, spec: dict[str, Any]) -> str:
        for source in self.registry.list_sources():
            if source.source_name == spec["source_name"]:
                return source.source_id
        source = self.registry.register_source(**spec)
        self.registry.set_source_status(
            source.source_id, "active", actor="first-batch", reason="first real-data batch"
        )
        return source.source_id

    def _ensure_indicator(self, spec: IndicatorSpec, *, actor: str) -> None:
        try:
            indicator = self.registry.get_indicator(spec.code)
        except LookupError:
            indicator = self.registry.register_indicator(
                code=spec.code,
                name=spec.name,
                description=spec.description,
                layer=spec.layer,
                category=spec.category,
                sub_category=spec.sub_category,
                unit=spec.unit,
                frequency=spec.frequency,
                timezone="UTC",
                data_type=spec.data_type,
                source_policy="registered primary source; see indicator_sources",
                update_method=spec.update_method,
                revision_policy="append new vintage; never overwrite",
                quality_policy="unit, release-time and interval checks",
                history_start=spec.coverage_start,
                usage_partition_policy=L5_PARTITION_POLICY if spec.layer == Layer.L5 else None,
                partition_scope=L5_PARTITION_SCOPE if spec.layer == Layer.L5 else None,
                actor=actor,
            )
            self.registry.set_indicator_status(
                indicator.indicator_code, "active", actor=actor, reason="first real-data batch"
            )
        if self.governance.get_indicator_governance(spec.code, missing_ok=True) is None:
            self.governance.register_indicator_governance(
                spec.code,
                source_grade=spec.source_grade,
                measurement_scope=spec.measurement_scope,
                proxy_flag=spec.proxy_flag,
                license_status=spec.license_status,
                coverage_status=spec.coverage_status,
                coverage_start=spec.coverage_start,
                notes=spec.description,
                actor=actor,
            )

    def _seed_halvings(self) -> None:
        halvings = [
            ("2012-11-28T15:24:38Z", 210000),
            ("2016-07-09T16:46:13Z", 420000),
            ("2020-05-11T19:23:48Z", 630000),
            ("2024-04-20T00:09:27Z", 840000),
        ]
        for event_time, height in halvings:
            event_id = f"evt_halving_{height}"
            if self.conn.execute(
                "SELECT 1 FROM known_future_events WHERE event_id = ?", (event_id,)
            ).fetchone():
                continue
            from .timeutils import utc_now_iso

            with self.conn:
                self.conn.execute(
                    "INSERT INTO known_future_events (event_id, event_type, event_name, "
                    "event_known_time_utc, event_effective_time_utc, event_source, "
                    "known_future_event, notes, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (
                        event_id,
                        "btc_halving",
                        f"BTC halving at block {height}",
                        "2009-01-03T00:00:00Z",
                        event_time,
                        "bitcoin_protocol",
                        "Protocol-scheduled supply event; known in advance.",
                        utc_now_iso(),
                    ),
                )

    def _link(self, code: str, source_key: str, *, role: str = "primary") -> None:
        source_id = self.sources[source_key]
        existing = self.registry.list_indicator_sources(code, active_only=True)
        if any(link.source_id == source_id for link in existing):
            return
        self.registry.link_source(code, source_id, role=role, actor="first-batch")

    # ------------------------------------------------------------------ runs
    def _ingest(
        self,
        code: str,
        source_key: str,
        rows: list[dict[str, Any]],
        *,
        batch: str,
        role: str = "primary",
    ) -> IngestionResult:
        self._link(code, source_key, role=role)
        return self.ingestion.ingest_rows(
            code,
            self.sources[source_key],
            rows,
            MAPPING,
            actor="first-batch",
            payload_format="json",
            batch_id=batch,
        )

    def run_d1_fred(self, api_key: str, *, sampling: str = "month_end") -> BatchReport:
        report = BatchReport("D1")
        for code, series_id in FRED_SERIES.items():
            try:
                vintages = connectors.fetch_fred_vintage_dates(series_id, api_key)
                selected = _sample_vintages(vintages, sampling)
                if not selected:
                    report.skipped.append(f"{code}: no vintages")
                    continue
                total = 0
                matrix = connectors.fetch_fred_vintage_matrix(series_id, api_key, selected)
                changed = connectors.fred_matrix_changed_rows(
                    matrix.data, series_id=series_id, vintage_dates=selected
                )
                for vintage, rows in changed.items():
                    result = self._ingest(code, "FRED", rows, batch=f"D1-{code}-{vintage}")
                    total += result.records_inserted
                time.sleep(0.5)
                report.results.append(
                    {"indicator": code, "vintages": len(selected), "inserted": total}
                )
            except Exception as exc:  # noqa: BLE001 - reported per indicator
                report.skipped.append(f"{code}: {exc}")
        return report

    def run_d2_kraken(
        self, *, btc_csv: str | Path | None = None, eth_csv: str | Path | None = None
    ) -> BatchReport:
        report = BatchReport("D2-Kraken")
        pairs = [
            ("BTC_USD_OHLCV", btc_csv, "BTC_VOLUME", "BTCUSD"),
            ("ETH_USD_OHLCV", eth_csv, None, "ETHUSD"),
        ]
        for code, path, volume_code, pair in pairs:
            if path is None:
                report.skipped.append(f"{code}: Kraken CSV not provided")
                continue
            close_rows, volume_rows = connectors.kraken_daily_ohlcvt(path, pair=pair)
            result = self._ingest(code, "KRAKEN", close_rows, batch=f"D2-{code}-kraken")
            report.results.append(
                {"indicator": code, "rows": result.records_inserted, "source": "Kraken"}
            )
            if volume_code:
                volume_result = self._ingest(
                    volume_code, "KRAKEN", volume_rows, batch=f"D2-{volume_code}-kraken"
                )
                report.results.append(
                    {"indicator": volume_code, "rows": volume_result.records_inserted}
                )
        return report

    def run_d2_yahoo(self, *, start: str = "2014-01-01") -> BatchReport:
        report = BatchReport("D2-Yahoo")
        for code, symbol in connectors.YAHOO_SYMBOLS.items():
            try:
                fetched = connectors.fetch_yahoo_daily(symbol, start=start)
                close_rows, volume_rows = connectors.yahoo_ohlcv_rows(fetched.data)
                result = self._ingest(code, "YAHOO", close_rows, batch=f"D2-{code}-yahoo")
                report.results.append(
                    {"indicator": code, "rows": result.records_inserted, "source": "Yahoo"}
                )
                if code == "BTC_USD_OHLCV":
                    volume_result = self._ingest(
                        "BTC_VOLUME", "YAHOO", volume_rows, batch="D2-BTC_VOLUME-yahoo"
                    )
                    report.results.append(
                        {"indicator": "BTC_VOLUME", "rows": volume_result.records_inserted}
                    )
            except Exception as exc:  # noqa: BLE001
                report.skipped.append(f"{code}: {exc}")
        return report

    def run_d3_blockchain(self) -> BatchReport:
        report = BatchReport("D3")
        for code, chart in connectors.BLOCKCHAIN_CHARTS.items():
            try:
                fetched = connectors.fetch_blockchain_chart(chart)
                rows = connectors.blockchain_rows(fetched.data)
                result = self._ingest(code, "BLOCKCHAIN", rows, batch=f"D3-{code}")
                report.results.append({"indicator": code, "rows": result.records_inserted})
                if code == "BTC_NETWORK_ACTIVITY":
                    # L3 usage proxy reuses the same on-chain series under an
                    # explicitly different interpretation boundary.
                    usage = self._ingest(
                        "BTC_NETWORK_USAGE", "BLOCKCHAIN", rows,
                        batch="D3-BTC_NETWORK_USAGE-proxy",
                    )
                    report.results.append(
                        {"indicator": "BTC_NETWORK_USAGE", "rows": usage.records_inserted}
                    )
            except Exception as exc:  # noqa: BLE001
                report.skipped.append(f"{code}: {exc}")
        return report

    def run_d4_stablecoins(self) -> BatchReport:
        report = BatchReport("D4")
        try:
            fetched = connectors.fetch_defillama_stablecoins()
            rows = connectors.defillama_total_rows(fetched.data)
            result = self._ingest(
                "STABLECOIN_TOTAL_SUPPLY", "DEFILLAMA", rows, batch="D4-stablecoins"
            )
            report.results.append(
                {"indicator": "STABLECOIN_TOTAL_SUPPLY", "rows": result.records_inserted}
            )
            change_rows = connectors.diff_rows(rows, name="STABLECOIN_SUPPLY_CHANGE")
            change = self._ingest(
                "STABLECOIN_SUPPLY_CHANGE", "DERIVED", change_rows, batch="D4-stablecoin-change"
            )
            report.results.append(
                {"indicator": "STABLECOIN_SUPPLY_CHANGE", "rows": change.records_inserted}
            )
        except Exception as exc:  # noqa: BLE001
            report.skipped.append(f"stablecoins: {exc}")
        return report

    def run_d5_etf(self) -> BatchReport:
        report = BatchReport("D5")
        try:
            fetched = connectors.fetch_tftc_flows()
            mapping = [
                ("BTC_SPOT_ETF_NET_FLOW", "netFlowUsd"),
                ("BTC_SPOT_ETF_AUM", "totalNetAssetsUsd"),
            ]
            for code, field in mapping:
                rows = connectors.tftc_rows(fetched.data, field=field)
                result = self._ingest(code, "TFTC", rows, batch=f"D5-{code}")
                report.results.append({"indicator": code, "rows": result.records_inserted})
        except Exception as exc:  # noqa: BLE001
            report.skipped.append(f"etf: {exc}")
        return report

    def run_derived(self) -> BatchReport:
        report = BatchReport("derived")
        try:
            base = self._base_rows("BTC_USD_OHLCV")
            if not base:
                report.skipped.append("BTC_USD_OHLCV: no observations")
                return report
            series = [
                ("BTC_RETURN", connectors.pct_change_rows(base, name="BTC_RETURN")),
                ("BTC_DRAWDOWN", connectors.drawdown_rows(base)),
                ("BTC_REALIZED_VOL", connectors.realized_vol_rows(base)),
            ]
            for code, rows in series:
                result = self._ingest(code, "DERIVED", rows, batch=f"derived-{code}")
                report.results.append({"indicator": code, "rows": result.records_inserted})
        except Exception as exc:  # noqa: BLE001
            report.skipped.append(f"derived: {exc}")

        try:
            supply = self._base_rows("BTC_CIRCULATING_SUPPLY")
            if supply:
                rows = connectors.diff_rows(supply, name="BTC_ISSUANCE")
                result = self._ingest("BTC_ISSUANCE", "DERIVED", rows, batch="derived-BTC_ISSUANCE")
                report.results.append(
                    {"indicator": "BTC_ISSUANCE", "rows": result.records_inserted}
                )
        except Exception as exc:  # noqa: BLE001
            report.skipped.append(f"issuance: {exc}")
        return report

    def _base_rows(self, code: str) -> list[dict[str, Any]]:
        indicator = self.registry.get_indicator(code)
        rows = self.conn.execute(
            "SELECT observation_period_start, observation_period_end, value, "
            "available_time_utc, available_time_method FROM observations "
            "WHERE indicator_id = ? ORDER BY observation_period_start, vintage_time_utc",
            (indicator.indicator_id,),
        ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest[row["observation_period_start"]] = {
                "period_start": row["observation_period_start"],
                "period_end": row["observation_period_end"],
                "value": row["value"],
                "available_time": row["available_time_utc"],
                "available_time_method": row["available_time_method"],
            }
        return [latest[key] for key in sorted(latest)]

    # --------------------------------------------------------------- coverage
    def coverage_report(self) -> list[dict[str, Any]]:
        return [self.governance.actual_coverage(spec.code) for spec in _INDICATORS]

    def reconcile_coverage(self, *, actor: str = "first-batch") -> list[str]:
        """Append a new governance version when declared coverage differs from data."""
        updated: list[str] = []
        for spec in _INDICATORS:
            actual = self.governance.actual_coverage(spec.code)
            start = actual["coverage_start_utc"]
            if not start:
                continue
            computed = (
                "full_target_coverage" if start[:10] <= "2015-01-08" else "partial_coverage"
            )
            current = self.governance.get_indicator_governance(spec.code, missing_ok=True)
            if (
                current
                and current.coverage_status == computed
                and (current.coverage_start_utc or "")[:10] == start[:10]
            ):
                continue
            self.governance.register_indicator_governance(
                spec.code,
                source_grade=spec.source_grade,
                measurement_scope=spec.measurement_scope,
                proxy_flag=spec.proxy_flag,
                license_status=spec.license_status,
                coverage_status=computed,
                coverage_start=start,
                coverage_end=actual["coverage_end_utc"],
                notes=spec.description,
                actor=actor,
            )
            updated.append(f"{spec.code}: {computed} from {start[:10]}")
        return updated


def _sample_vintages(vintages: list[str], sampling: str) -> list[str]:
    """Keep the last vintage date of each month unless full sampling is requested."""
    if sampling == "all":
        return list(vintages)
    selected: dict[str, str] = {}
    for vintage in vintages:
        selected[vintage[:7]] = vintage  # last date wins; dict preserves insertion order
    return [selected[key] for key in sorted(selected)]