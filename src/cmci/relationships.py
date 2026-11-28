"""Lead-lag relationship tests between L2/L4 drivers and L5 BTC returns.

Scope note: L1 is not loaded yet, so this module explicitly cannot test
"common driver" or "capital competition". It tests the supply channel (L2) and
the capital-transmission channel (L4) only.

Method:
- weekly aggregation from daily observations;
- Spearman rank correlation at lags 0..4 weeks (driver leads return);
- Fisher-z p-values, Benjamini-Hochberg q-values across all tests;
- circular block bootstrap confidence intervals (block = 4 weeks);
- best lag chosen on the identification period (< 2023), then checked on the
  validation period (>= 2023) for sign consistency;
- conclusions allowed: supports / does not support / insufficient evidence.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .registry import Registry

SPLIT_DATE = date(2023, 1, 1)
MAX_LAG = 4
MIN_PAIRS = 100
MIN_VALIDATION = 50
Q_THRESHOLD = 0.10
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 4


@dataclass(frozen=True, slots=True)
class DriverSpec:
    code: str
    label: str
    channel: str
    aggregation: str  # sum / mean / last
    transform: str  # level / log_change


DRIVERS: tuple[DriverSpec, ...] = (
    DriverSpec("BTC_ISSUANCE", "BTC 新增发行量", "L2 供给", "sum", "level"),
    DriverSpec("BTC_HASHRATE", "全网算力", "L2 供给", "mean", "log_change"),
    DriverSpec("BTC_MINER_REVENUE", "矿工收入", "L2 供给", "mean", "log_change"),
    DriverSpec("STABLECOIN_TOTAL_SUPPLY", "稳定币总供应", "L4 资金传导", "last", "log_change"),
    DriverSpec("BTC_SPOT_ETF_NET_FLOW", "现货 ETF 净流入", "L4 资金传导", "sum", "level"),
    DriverSpec("BTC_SPOT_ETF_AUM", "现货 ETF 资产规模", "L4 资金传导", "last", "log_change"),
    DriverSpec("US_10Y_REAL_YIELD", "美国10年期实际利率", "L1 宏观", "mean", "diff"),
    DriverSpec("USD_BROAD_INDEX", "美元广义指数", "L1 宏观", "last", "log_change"),
    DriverSpec("FED_BALANCE_SHEET", "美联储总资产", "L1 宏观", "last", "log_change"),
    DriverSpec("VIX", "VIX 波动率", "L1 宏观", "mean", "log_change"),
    DriverSpec("HY_CREDIT_SPREAD", "高收益债信用利差", "L1 宏观", "mean", "diff"),
)

CAVEATS: dict[str, str] = {
    "BTC_ISSUANCE": "效应量很小；发行量由协议规则决定，不能解释为可交易信号。",
    "BTC_HASHRATE": "算力是慢变量，未发现稳定领先关系。",
    "BTC_MINER_REVENUE": "矿工收入由价格与手续费驱动，同期相关主要反映反向因果，不是领先驱动证据。",
    "STABLECOIN_TOTAL_SUPPLY": "供应是存量，变化不等于资金进入交易所或买入 BTC。",
    "BTC_SPOT_ETF_NET_FLOW": "仅覆盖 2024 年后，全部落在验证期，无法完成独立识别。",
    "BTC_SPOT_ETF_AUM": "覆盖期过短，且 AUM 随价格机械变化。",
    "US_10Y_REAL_YIELD": "宏观变量与风险资产存在共同驱动和内生性，不能直接解释为因果。",
    "USD_BROAD_INDEX": "美元与风险资产可能同受宏观因素驱动，相关不等于传导。",
    "FED_BALANCE_SHEET": "资产负债表是慢变量，且与政策预期高度相关。",
    "VIX": "波动率与收益存在同期反向的机械关系，不是独立驱动。",
    "HY_CREDIT_SPREAD": "历史版本仅 2023 年后可得，识别期样本不足。",
}


# ------------------------------------------------------------------ statistics
def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for offset in range(position, end + 1):
            ranks[order[offset]] = average
        position = end + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx = _rank(xs)
    ry = _rank(ys)
    mean_x = sum(rx) / len(rx)
    mean_y = sum(ry) / len(ry)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    denominator = math.sqrt(
        sum((a - mean_x) ** 2 for a in rx) * sum((b - mean_y) ** 2 for b in ry)
    )
    if denominator == 0:
        return None
    return max(-1.0, min(1.0, numerator / denominator))


def fisher_p_value(r: float, n: int) -> float:
    if n <= 3:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    z = math.atanh(r) * math.sqrt(n - 3)
    return 2.0 * (1.0 - _normal_cdf(abs(z)))


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def block_bootstrap_ci(
    xs: list[float],
    ys: list[float],
    *,
    reps: int = BOOTSTRAP_REPS,
    block: int = BOOTSTRAP_BLOCK,
    seed: int = 42,
) -> tuple[float | None, float | None]:
    n = len(xs)
    if n < block * 2:
        return None, None
    rng = random.Random(seed)
    samples: list[float] = []
    block_count = math.ceil(n / block)
    for _ in range(reps):
        indexes: list[int] = []
        for _ in range(block_count):
            start = rng.randrange(n)
            for offset in range(block):
                indexes.append((start + offset) % n)
        sample_x = [xs[index] for index in indexes[:n]]
        sample_y = [ys[index] for index in indexes[:n]]
        value = spearman(sample_x, sample_y)
        if value is not None:
            samples.append(value)
    if not samples:
        return None, None
    samples.sort()
    low = samples[int(0.025 * (len(samples) - 1))]
    high = samples[int(0.975 * (len(samples) - 1))]
    return low, high


def bh_qvalues(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = sorted(range(m), key=lambda index: p_values[index])
    q_values = [1.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        index = order[rank]
        candidate = p_values[index] * m / (rank + 1)
        running = min(running, candidate)
        q_values[index] = min(1.0, running)
    return q_values


# ------------------------------------------------------------------ data prep
def _parse_day(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _week_key(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso[0], iso[1]


class RelationshipService:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.conn = registry.conn

    def _daily(self, code: str) -> list[tuple[date, float]]:
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
        return sorted((_parse_day(day), value) for day, value in latest.items())

    def weekly_returns(self) -> dict[tuple[int, int], tuple[date, float]]:
        prices = self._daily("BTC_USD_OHLCV")
        weekly: dict[tuple[int, int], tuple[date, float]] = {}
        for day, close in prices:
            weekly[_week_key(day)] = (day, close)  # last close of the week wins
        ordered = sorted(weekly.items(), key=lambda item: item[0])
        result: dict[tuple[int, int], tuple[date, float]] = {}
        previous: float | None = None
        for key, (day, close) in ordered:
            if previous is not None and previous > 0:
                result[key] = (day, close / previous - 1.0)
            previous = close
        return result

    def weekly_driver(self, spec: DriverSpec) -> dict[tuple[int, int], tuple[date, float]]:
        daily = self._daily(spec.code)
        buckets: dict[tuple[int, int], list[tuple[date, float]]] = {}
        for day, value in daily:
            buckets.setdefault(_week_key(day), []).append((day, value))
        weekly: dict[tuple[int, int], tuple[date, float]] = {}
        for key, points in buckets.items():
            points.sort()
            values = [value for _, value in points]
            if spec.aggregation == "sum":
                aggregate = sum(values)
            elif spec.aggregation == "mean":
                aggregate = sum(values) / len(values)
            else:
                aggregate = values[-1]
            weekly[key] = (points[-1][0], aggregate)
        ordered = sorted(weekly.items(), key=lambda item: item[0])
        if spec.transform == "level":
            return dict(ordered)
        transformed: dict[tuple[int, int], tuple[date, float]] = {}
        previous: float | None = None
        for key, (day, value) in ordered:
            if previous is not None:
                if spec.transform == "diff":
                    transformed[key] = (day, value - previous)
                elif previous > 0 and value > 0:
                    transformed[key] = (day, math.log(value / previous))
            previous = value
        return transformed

    # ------------------------------------------------------------------ tests
    def build(self) -> dict[str, Any]:
        returns = self.weekly_returns()
        rows: list[dict[str, Any]] = []
        pair_lists: dict[tuple[str, int], list[tuple[date, float, float]]] = {}
        for spec in DRIVERS:
            driver = self.weekly_driver(spec)
            for lag in range(MAX_LAG + 1):
                pairs: list[tuple[date, float, float]] = []
                for key, (day, value) in sorted(driver.items()):
                    target_key = _week_key(day + timedelta(days=7 * lag))
                    if target_key not in returns:
                        continue
                    target_day, target_value = returns[target_key]
                    pairs.append((target_day, value, target_value))
                if len(pairs) < 10:
                    continue
                pair_lists[(spec.code, lag)] = pairs
                xs = [pair[1] for pair in pairs]
                ys = [pair[2] for pair in pairs]
                r = spearman(xs, ys)
                if r is None:
                    continue
                p = fisher_p_value(r, len(pairs))
                low, high = block_bootstrap_ci(xs, ys)
                rows.append(
                    {
                        "driver": spec.code,
                        "label": spec.label,
                        "channel": spec.channel,
                        "lag_weeks": lag,
                        "n_pairs": len(pairs),
                        "spearman_r": r,
                        "p_value": p,
                        "ci_low": low,
                        "ci_high": high,
                        "last_week": max(pair[0] for pair in pairs).isoformat(),
                    }
                )

        q_values = bh_qvalues([row["p_value"] for row in rows])
        for row, q in zip(rows, q_values):
            row["q_value"] = q

        for row in rows:
            pairs = pair_lists[(row["driver"], row["lag_weeks"])]
            row["identification_r"], row["identification_n"] = _subset_correlation(
                pairs, lambda day: day < SPLIT_DATE
            )
            row["validation_r"], row["validation_n"] = _subset_correlation(
                pairs, lambda day: day >= SPLIT_DATE
            )

        selected: list[dict[str, Any]] = []
        for spec in DRIVERS:
            candidates = [
                row for row in rows
                if row["driver"] == spec.code and row["identification_n"] >= 30
            ]
            if not candidates:
                selected.append(_insufficient(spec, "识别期样本不足"))
                continue
            best = max(candidates, key=lambda row: abs(row["identification_r"] or 0.0))
            validation_r = best["validation_r"]
            validation_n = best["validation_n"]
            if best["n_pairs"] < MIN_PAIRS or validation_n < MIN_VALIDATION:
                conclusion = "证据不足"
                reason = "有效样本不足"
            elif best["q_value"] >= Q_THRESHOLD:
                conclusion = "证据不足"
                reason = "多重检验后不显著"
            elif best["ci_low"] is None or best["ci_high"] is None:
                conclusion = "证据不足"
                reason = "置信区间无法估计"
            elif best["ci_low"] <= 0 <= best["ci_high"]:
                conclusion = "证据不足"
                reason = "bootstrap 区间跨零"
            elif validation_r is None:
                conclusion = "证据不足"
                reason = "验证期样本不足"
            elif validation_r * best["identification_r"] < 0:
                conclusion = "不成立"
                reason = "验证期方向相反"
            else:
                conclusion = "成立"
                reason = "识别期显著且验证期方向一致"
            selected.append(
                {
                    "driver": spec.code,
                    "label": spec.label,
                    "channel": spec.channel,
                    "best_lag_weeks": best["lag_weeks"],
                    "identification_r": best["identification_r"],
                    "identification_n": best["identification_n"],
                    "validation_r": validation_r,
                    "validation_n": validation_n,
                    "spearman_r": best["spearman_r"],
                    "q_value": best["q_value"],
                    "ci_low": best["ci_low"],
                    "ci_high": best["ci_high"],
                    "n_pairs": best["n_pairs"],
                    "conclusion": conclusion,
                    "reason": reason,
                    "caveat": CAVEATS[spec.code],
                }
            )

        return {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": (
                "检验 L1 宏观条件、L2 供给与 L4 资金传导到 BTC 收益的关系；"
                "共同驱动与资本竞争尚未与股票、配置数据区分。"
            ),
            "method": {
                "frequency": "weekly",
                "max_lag_weeks": MAX_LAG,
                "split": SPLIT_DATE.isoformat(),
                "min_pairs": MIN_PAIRS,
                "bootstrap_reps": BOOTSTRAP_REPS,
                "bootstrap_block_weeks": BOOTSTRAP_BLOCK,
                "q_threshold": Q_THRESHOLD,
                "multiple_testing": "Benjamini-Hochberg",
            },
            "sample_warning": (
                "周度重叠样本存在序列相关；bootstrap 已按 4 周区块处理，"
                "但独立周期数量仍只有 4 个减半区间，结论属于探索性。"
            ),
            "tests": rows,
            "conclusions": selected,
        }


def _subset_correlation(
    pairs: list[tuple[date, float, float]],
    predicate: Callable[[date], bool],
) -> tuple[float | None, int]:
    subset = [pair for pair in pairs if predicate(pair[0])]
    if len(subset) < 10:
        return None, len(subset)
    return spearman([pair[1] for pair in subset], [pair[2] for pair in subset]), len(subset)


def _insufficient(spec: DriverSpec, reason: str) -> dict[str, Any]:
    return {
        "driver": spec.code,
        "label": spec.label,
        "channel": spec.channel,
        "best_lag_weeks": None,
        "identification_r": None,
        "identification_n": 0,
        "validation_r": None,
        "validation_n": 0,
        "spearman_r": None,
        "q_value": None,
        "ci_low": None,
        "ci_high": None,
        "n_pairs": 0,
        "conclusion": "证据不足",
        "reason": reason,
        "caveat": CAVEATS[spec.code],
    }