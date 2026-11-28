"""BTC halving-cycle historical table (task three).

Uses only registered observations. Macro fields stay empty until L1 is loaded;
market-structure fields are reported from their actual first availability, not
backfilled.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .registry import Registry

GENESIS = "2009-01-03T00:00:00Z"
DAILY = 365.0
MACRO_CODES = (
    ("US_10Y_YIELD", "us_10y"),
    ("US_10Y_REAL_YIELD", "us_10y_real"),
    ("USD_BROAD_INDEX", "usd_broad"),
    ("FED_BALANCE_SHEET", "fed_assets"),
    ("VIX", "vix"),
    ("HY_CREDIT_SPREAD", "hy_spread"),
)


@dataclass(frozen=True, slots=True)
class CycleRow:
    label: str
    start_utc: str
    end_utc: str
    days: int
    start_price: float | None
    end_price: float | None
    return_pct: float | None
    max_close: float | None
    max_drawdown_pct: float | None
    annualized_vol_pct: float | None
    price_at_halving: float | None
    price_30d: float | None
    price_90d: float | None
    price_180d: float | None
    price_365d: float | None
    issuance_before: float | None
    issuance_after: float | None
    issuance_change_pct: float | None
    stablecoin_supply_at_start: float | None
    stablecoin_supply_at_end: float | None
    etf_net_flow_in_cycle: float | None
    macro_start_json: str | None
    macro_end_json: str | None
    data_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "days": self.days,
            "start_price": self.start_price,
            "end_price": self.end_price,
            "return_pct": self.return_pct,
            "max_close": self.max_close,
            "max_drawdown_pct": self.max_drawdown_pct,
            "annualized_vol_pct": self.annualized_vol_pct,
            "price_at_halving": self.price_at_halving,
            "price_30d": self.price_30d,
            "price_90d": self.price_90d,
            "price_180d": self.price_180d,
            "price_365d": self.price_365d,
            "issuance_before": self.issuance_before,
            "issuance_after": self.issuance_after,
            "issuance_change_pct": self.issuance_change_pct,
            "stablecoin_supply_at_start": self.stablecoin_supply_at_start,
            "stablecoin_supply_at_end": self.stablecoin_supply_at_end,
            "etf_net_flow_in_cycle": self.etf_net_flow_in_cycle,
            "macro_start_json": self.macro_start_json,
            "macro_end_json": self.macro_end_json,
            "data_note": self.data_note,
        }


def _parse(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _within(points: list[tuple[date, float]], start: date, end: date) -> list[tuple[date, float]]:
    return [(day, value) for day, value in points if start <= day <= end]


def _first_on_or_after(points: list[tuple[date, float]], day: date) -> float | None:
    for stamp, value in points:
        if stamp >= day:
            return value if stamp - day <= timedelta(days=10) else None
    return None


def _at(points: list[tuple[date, float]], day: date) -> float | None:
    """Nearest value at or before day."""
    candidate = None
    for stamp, value in points:
        if stamp <= day:
            candidate = value
        else:
            break
    return candidate


def _stats(points: list[tuple[date, float]]) -> dict[str, float | None]:
    if not points:
        return {
            "start": None,
            "end": None,
            "return_pct": None,
            "max_close": None,
            "max_drawdown_pct": None,
            "annualized_vol_pct": None,
        }
    closes = [value for _, value in points]
    peak = closes[0]
    max_drawdown = 0.0
    for value in closes:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    vol = None
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
        vol = math.sqrt(variance) * math.sqrt(DAILY) * 100
    return {
        "start": closes[0],
        "end": closes[-1],
        "return_pct": (closes[-1] / closes[0] - 1.0) * 100,
        "max_close": max(closes),
        "max_drawdown_pct": max_drawdown * 100,
        "annualized_vol_pct": vol,
    }


class CycleTableService:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.conn = registry.conn

    def _series(self, code: str) -> list[tuple[date, float]]:
        indicator = self.registry.get_indicator(code)
        rows = self.conn.execute(
            "SELECT observation_period_start, value FROM observations "
            "WHERE indicator_id = ? AND value IS NOT NULL "
            "ORDER BY observation_period_start, vintage_time_utc",
            (indicator.indicator_id,),
        ).fetchall()
        latest: dict[str, float] = {}
        for row in rows:
            latest[row["observation_period_start"]] = float(row["value"])
        return sorted((_parse(stamp), value) for stamp, value in latest.items())

    def _halvings(self) -> list[tuple[date, int | None]]:
        rows = self.conn.execute(
            "SELECT event_effective_time_utc, event_name FROM known_future_events "
            "WHERE event_type = 'btc_halving' ORDER BY event_effective_time_utc"
        ).fetchall()
        events: list[tuple[date, int | None]] = []
        for row in rows:
            height = None
            name = row["event_name"] or ""
            for token in name.split():
                if token.isdigit():
                    height = int(token)
            events.append((_parse(row["event_effective_time_utc"]), height))
        return events

    def build(self) -> dict[str, Any]:
        prices = self._series("BTC_USD_OHLCV")
        issuance = self._series("BTC_ISSUANCE")
        stablecoins = self._series("STABLECOIN_TOTAL_SUPPLY")
        etf_flows = self._series("BTC_SPOT_ETF_NET_FLOW")
        macro_series = {label: self._series(code) for code, label in MACRO_CODES}
        halvings = self._halvings()
        if not prices:
            raise ValueError("BTC_USD_OHLCV 没有观测，无法建立周期表")

        boundaries = [(_parse(GENESIS), None)] + halvings
        rows: list[CycleRow] = []
        for index in range(len(boundaries) - 1):
            start, _ = boundaries[index]
            end, height = boundaries[index + 1]
            label = f"{end.year} halving (block {height})" if height else f"{end.year}"
            window = _within(prices, start, end)
            stats = _stats(window)
            notes: list[str] = []
            if stats["start"] is None:
                notes.append("价格数据早于首个可用观测")
            first_available = window[0][0] if window else None
            if first_available and first_available > start + timedelta(days=30):
                notes.append(f"价格始于 {first_available.isoformat()}")
            if not stablecoins:
                notes.append("稳定币供应缺失")
            if end.year >= 2024 and not etf_flows:
                notes.append("ETF 资金流缺失")

            price_halving = _at(prices, end)
            macro_start = _macro_json(macro_series, start)
            macro_end = _macro_json(macro_series, end)
            if macro_start is None:
                notes.append("周期起点无 L1 宏观数据")
            row = CycleRow(
                label=label,
                start_utc=start.isoformat() + "T00:00:00Z",
                end_utc=end.isoformat() + "T00:00:00Z",
                days=(end - start).days,
                start_price=stats["start"],
                end_price=stats["end"],
                return_pct=stats["return_pct"],
                max_close=stats["max_close"],
                max_drawdown_pct=stats["max_drawdown_pct"],
                annualized_vol_pct=stats["annualized_vol_pct"],
                price_at_halving=price_halving,
                price_30d=_first_on_or_after(prices, end + timedelta(days=30)),
                price_90d=_first_on_or_after(prices, end + timedelta(days=90)),
                price_180d=_first_on_or_after(prices, end + timedelta(days=180)),
                price_365d=_first_on_or_after(prices, end + timedelta(days=365)),
                issuance_before=_average(
                    _within(issuance, end - timedelta(days=30), end - timedelta(days=1))
                ),
                issuance_after=_average(
                    _within(issuance, end, end + timedelta(days=30))
                ),
                issuance_change_pct=_change(
                    _average(_within(issuance, end - timedelta(days=30), end - timedelta(days=1))),
                    _average(_within(issuance, end, end + timedelta(days=30))),
                ),
                stablecoin_supply_at_start=_at(stablecoins, start),
                stablecoin_supply_at_end=_at(stablecoins, end),
                etf_net_flow_in_cycle=(
                    sum(value for day, value in etf_flows if start <= day <= end)
                    if any(start <= day <= end for day, _ in etf_flows)
                    else None
                ),
                macro_start_json=macro_start,
                macro_end_json=macro_end,
                data_note="；".join(notes),
            )
            rows.append(row)

        current_start, _ = boundaries[-1]
        latest = prices[-1][0]
        window = _within(prices, current_start, latest)
        stats = _stats(window)
        current = CycleRow(
            label="current cycle (2024 halving)",
            start_utc=current_start.isoformat() + "T00:00:00Z",
            end_utc=latest.isoformat() + "T00:00:00Z",
            days=(latest - current_start).days,
            start_price=stats["start"],
            end_price=stats["end"],
            return_pct=stats["return_pct"],
            max_close=stats["max_close"],
            max_drawdown_pct=stats["max_drawdown_pct"],
            annualized_vol_pct=stats["annualized_vol_pct"],
            price_at_halving=_at(prices, current_start),
            price_30d=_first_on_or_after(prices, current_start + timedelta(days=30)),
            price_90d=_first_on_or_after(prices, current_start + timedelta(days=90)),
            price_180d=_first_on_or_after(prices, current_start + timedelta(days=180)),
            price_365d=_first_on_or_after(prices, current_start + timedelta(days=365)),
            issuance_before=_average(
                _within(issuance, current_start - timedelta(days=30), current_start - timedelta(days=1))
            ),
            issuance_after=_average(
                _within(issuance, current_start, min(current_start + timedelta(days=30), latest))
            ),
            issuance_change_pct=_change(
                _average(_within(issuance, current_start - timedelta(days=30), current_start - timedelta(days=1))),
                _average(_within(issuance, current_start, min(current_start + timedelta(days=30), latest))),
            ),
            stablecoin_supply_at_start=_at(stablecoins, current_start),
            stablecoin_supply_at_end=_at(stablecoins, latest),
            etf_net_flow_in_cycle=(
                sum(value for day, value in etf_flows if current_start <= day <= latest)
                if any(current_start <= day <= latest for day, _ in etf_flows)
                else None
            ),
            macro_start_json=_macro_json(macro_series, current_start),
            macro_end_json=_macro_json(macro_series, latest),
            data_note="进行中，尚未闭合",
        )
        rows.append(current)

        return {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sample_warning": (
                "4 个已闭合减半区间加 1 个进行中区间，属于事件聚类样本，"
                "不能当作多个独立宏观周期。"
            ),
            "macro_layer_status": "L1 未接入，宏观字段留空，待 FRED/ALFRED vintage 数据。",
            "cycles": [row.to_dict() for row in rows],
        }


def _average(points: list[tuple[date, float]]) -> float | None:
    if not points:
        return None
    return sum(value for _, value in points) / len(points)


def _change(before: float | None, after: float | None) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return (after / before - 1.0) * 100


def _macro_json(series_map: dict[str, list[tuple[date, float]]], day: date) -> str | None:
    values: dict[str, float] = {}
    for label, points in series_map.items():
        value = _at(points, day)
        if value is not None:
            values[label] = value
    return json.dumps(values, ensure_ascii=False) if values else None


def write_outputs(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "btc-cycle-table.json"
    csv_path = directory / "btc-cycle-table.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cycles = report["cycles"]
    columns = list(cycles[0].keys())
    lines = [",".join(columns)]
    for cycle in cycles:
        lines.append(",".join(_csv_cell(cycle[column]) for column in columns))
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, csv_path


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if "," in text or '"' in text:
        return '"' + text.replace('"', '""') + '"'
    return text