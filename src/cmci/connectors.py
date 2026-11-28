"""Free-source connectors for the first real-data batch (D1-D5).

Every connector returns canonical row dictionaries that the ingestion service
can store without further interpretation. Rows carry explicit availability
metadata so historical replay never uses a value before it existed.

Availability policy:
- FRED/ALFRED: end of the vintage date (date-only precision, historical vintage).
- Kraken/Yahoo daily bars: end of the following day (conservative lag).
- Blockchain.com daily charts: end of the following day (conservative lag).
- DefiLlama daily supply: end of the following day (conservative lag).
- TFTC ETF sessions: end of the second following day (conservative lag).
"""

from __future__ import annotations

import csv
import io
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

USER_AGENT = "CMCI-research/0.1 (+https://cyclemarket.predi.org)"
FRED_API = "https://api.stlouisfed.org/fred"


class ConnectorError(RuntimeError):
    """A source could not be read or returned an unusable payload."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    content: bytes
    data: Any
    fetched_at_utc: str


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    retries: int = 2,
) -> FetchResult:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read()
            return FetchResult(url, raw, json.loads(raw.decode("utf-8")), _now_iso())
        except Exception as exc:  # noqa: BLE001 - retried then surfaced
            last_error = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise ConnectorError(f"无法获取 {url}: {last_error}") from last_error


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_day(unix_seconds: int | float) -> date:
    return datetime.fromtimestamp(float(unix_seconds), tz=timezone.utc).date()


def _bounds(day: date) -> tuple[str, str]:
    return f"{day.isoformat()}T00:00:00Z", f"{day.isoformat()}T23:59:59Z"


def _day_plus(day: date, days: int) -> str:
    return f"{(day + timedelta(days=days)).isoformat()}T23:59:59Z"


def _row(
    period_start: str,
    period_end: str,
    value: Any,
    *,
    available_time: str,
    method: str = "conservative_lag",
    value_text: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "value_text": value_text,
        "available_time": available_time,
        "available_time_precision": "date",
        "available_time_method": method,
        "vintage_time": available_time,
    }
    return row


# ---------------------------------------------------------------------- FRED
def fetch_fred_observations(
    series_id: str,
    api_key: str,
    *,
    observation_start: str = "2014-01-01",
    realtime_start: str | None = None,
    realtime_end: str | None = None,
) -> FetchResult:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
    }
    if realtime_start:
        params["realtime_start"] = realtime_start
    if realtime_end:
        params["realtime_end"] = realtime_end
    return fetch_json(f"{FRED_API}/series/observations?{urllib.parse.urlencode(params)}")


def fetch_fred_vintage_dates(
    series_id: str, api_key: str, *, start: str = "2015-01-01"
) -> list[str]:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": start,
        "limit": 10000,
        "sort_order": "asc",
    }
    result = fetch_json(f"{FRED_API}/series/vintagedates?{urllib.parse.urlencode(params)}")
    return list(result.data.get("vintage_dates", []))


def fred_rows(observations: list[dict[str, Any]], *, vintage_date: str) -> list[dict[str, Any]]:
    """Rows for one vintage. The vintage date is the conservative availability date."""
    available = f"{vintage_date}T23:59:59Z"
    rows: list[dict[str, Any]] = []
    for record in observations:
        raw = record.get("value")
        if raw in (None, "", "."):
            continue
        day = date.fromisoformat(record["date"])
        start, end = _bounds(day)
        rows.append(
            _row(
                start,
                end,
                raw,
                available_time=available,
                method="historical_vintage",
            )
        )
    return rows


# -------------------------------------------------------------- Blockchain
BLOCKCHAIN_CHARTS = {
    "BTC_CIRCULATING_SUPPLY": "total-bitcoins",
    "BTC_HASHRATE": "hash-rate",
    "BTC_DIFFICULTY": "difficulty",
    "BTC_MINER_REVENUE": "miners-revenue",
    "BTC_NETWORK_ACTIVITY": "n-transactions",
    "BTC_UNIQUE_ADDRESSES": "n-unique-addresses",
}


def fetch_blockchain_chart(chart: str, *, coverage_start: str = "2015-01-01") -> FetchResult:
    params = {"format": "json", "timespan": "all", "sampled": "false"}
    # sampled=false returns the native series; most charts are already daily,
    # while total-bitcoins is per block and is collapsed to the last value/day.
    return fetch_json(
        f"https://api.blockchain.info/charts/{chart}?{urllib.parse.urlencode(params)}",
        timeout=180,
    )


def blockchain_rows(payload: dict[str, Any], *, coverage_start: str = "2015-01-01") -> list[dict[str, Any]]:
    values = payload.get("values")
    if not isinstance(values, list):
        raise ConnectorError("Blockchain.com 响应缺少 values")
    cutoff = date.fromisoformat(coverage_start)
    by_day: dict[date, float] = {}
    for point in values:
        day = _utc_day(point["x"])
        if day < cutoff:
            continue
        by_day[day] = point["y"]  # later points win; total-bitcoins is per block
    rows: list[dict[str, Any]] = []
    for day in sorted(by_day):
        start, end = _bounds(day)
        rows.append(_row(start, end, by_day[day], available_time=_day_plus(day, 1)))
    if not rows:
        raise ConnectorError("Blockchain.com 响应没有可用观测")
    return rows


# --------------------------------------------------------------- DefiLlama
def fetch_defillama_stablecoins() -> FetchResult:
    return fetch_json("https://stablecoins.llama.fi/stablecoincharts/all", timeout=120)


def defillama_total_rows(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point in payload:
        circulating = point.get("totalCirculatingUSD") or {}
        total = sum(float(value) for value in circulating.values() if value)
        if total <= 0:
            continue
        day = _utc_day(point["date"])
        start, end = _bounds(day)
        rows.append(_row(start, end, total, available_time=_day_plus(day, 1)))
    if not rows:
        raise ConnectorError("DefiLlama 响应没有稳定币供应数据")
    return rows


# ------------------------------------------------------------------- TFTC
def fetch_tftc_flows() -> FetchResult:
    return fetch_json("https://www.tftc.io/bitcoin-etf-flows/data.json", timeout=90)


def tftc_rows(payload: dict[str, Any], *, field: str) -> list[dict[str, Any]]:
    days = payload.get("days")
    if not isinstance(days, list):
        raise ConnectorError("TFTC 响应缺少 days")
    rows: list[dict[str, Any]] = []
    for item in days:
        raw = item.get(field)
        if raw is None:
            continue
        try:
            day = date.fromisoformat(item["date"])
        except (KeyError, ValueError) as exc:
            raise ConnectorError(f"TFTC 日期非法: {item!r}") from exc
        start, end = _bounds(day)
        rows.append(_row(start, end, raw, available_time=_day_plus(day, 2)))
    if not rows:
        raise ConnectorError(f"TFTC 响应没有 {field}")
    return rows


# ----------------------------------------------------------------- Yahoo
YAHOO_SYMBOLS = {"BTC_USD_OHLCV": "BTC-USD", "ETH_USD_OHLCV": "ETH-USD"}


def fetch_yahoo_daily(symbol: str, *, start: str = "2014-01-01") -> FetchResult:
    period1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.now(timezone.utc).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d&events=div%2Csplits"
    )
    return fetch_json(url, timeout=90)


def yahoo_ohlcv_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (close rows with OHLC text, volume rows)."""
    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        raise ConnectorError("Yahoo 响应缺少 chart.result")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    close_rows: list[dict[str, Any]] = []
    volume_rows: list[dict[str, Any]] = []
    for index, stamp in enumerate(timestamps):
        close = closes[index] if index < len(closes) else None
        if close is None:
            continue
        day = _utc_day(stamp)
        start, end = _bounds(day)
        available = _day_plus(day, 1)
        ohlc = {
            "open": opens[index] if index < len(opens) else None,
            "high": highs[index] if index < len(highs) else None,
            "low": lows[index] if index < len(lows) else None,
            "close": close,
            "volume": volumes[index] if index < len(volumes) else None,
            "source": "yahoo_chart",
        }
        close_rows.append(
            _row(start, end, close, available_time=available, value_text=json.dumps(ohlc))
        )
        volume = volumes[index] if index < len(volumes) else None
        if volume is not None:
            volume_rows.append(_row(start, end, volume, available_time=available))
    if not close_rows:
        raise ConnectorError("Yahoo 响应没有可用收盘价")
    return close_rows, volume_rows


# ----------------------------------------------------------------- Kraken
def kraken_daily_ohlcvt(
    path: str | Path, *, pair: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse a Kraken OHLCVT CSV export into daily close and volume rows.

    Kraken exports one row per interval; this aggregates to UTC days using the
    first open, highest high, lowest low, last close and summed volume.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    buckets: dict[date, dict[str, Any]] = {}
    for raw in reader:
        if not raw or not raw[0].strip():
            continue
        try:
            stamp = int(float(raw[0]))
            if stamp > 10_000_000_000:  # milliseconds or microseconds
                stamp = stamp // 1000
                if stamp > 10_000_000_000:
                    stamp //= 1000
            open_, high, low, close = (float(raw[i]) for i in range(1, 5))
            volume = float(raw[6])
            trades = int(float(raw[7])) if len(raw) > 7 else 0
        except (ValueError, IndexError):
            continue  # header or malformed row
        day = _utc_day(stamp)
        bucket = buckets.get(day)
        if bucket is None:
            buckets[day] = {
                "open": open_, "high": high, "low": low, "close": close,
                "volume": volume, "trades": trades,
            }
        else:
            bucket["high"] = max(bucket["high"], high)
            bucket["low"] = min(bucket["low"], low)
            bucket["close"] = close
            bucket["volume"] += volume
            bucket["trades"] += trades

    close_rows: list[dict[str, Any]] = []
    volume_rows: list[dict[str, Any]] = []
    for day in sorted(buckets):
        bucket = buckets[day]
        start, end = _bounds(day)
        available = _day_plus(day, 1)
        payload = {"pair": pair, "interval": "daily", **bucket, "source": "kraken_ohlcvt"}
        close_rows.append(
            _row(start, end, bucket["close"], available_time=available,
                 value_text=json.dumps(payload))
        )
        volume_rows.append(_row(start, end, bucket["volume"], available_time=available))
    if not close_rows:
        raise ConnectorError(f"Kraken 文件没有可用数据: {path}")
    return close_rows, volume_rows


# ------------------------------------------------------------- derived rows
def pct_change_rows(rows: list[dict[str, Any]], *, name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    previous: float | None = None
    for row in rows:
        value = float(row["value"])
        if previous not in (None, 0):
            out.append(
                _row(
                    row["period_start"], row["period_end"], value / previous - 1.0,
                    available_time=row["available_time"],
                    method=row.get("available_time_method", "conservative_lag"),
                )
            )
        previous = value
    if not out:
        raise ConnectorError(f"{name} 无法计算变化率")
    return out


def diff_rows(rows: list[dict[str, Any]], *, name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    previous: float | None = None
    for row in rows:
        value = float(row["value"])
        if previous is not None:
            out.append(
                _row(
                    row["period_start"], row["period_end"], value - previous,
                    available_time=row["available_time"],
                    method=row.get("available_time_method", "conservative_lag"),
                )
            )
        previous = value
    if not out:
        raise ConnectorError(f"{name} 无法计算差分")
    return out


def drawdown_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    peak: float | None = None
    for row in rows:
        value = float(row["value"])
        peak = value if peak is None else max(peak, value)
        out.append(
            _row(
                row["period_start"], row["period_end"], value / peak - 1.0,
                available_time=row["available_time"],
                method=row.get("available_time_method", "conservative_lag"),
            )
        )
    return out


def realized_vol_rows(rows: list[dict[str, Any]], *, window: int = 30) -> list[dict[str, Any]]:
    closes = [float(row["value"]) for row in rows]
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    out: list[dict[str, Any]] = []
    for index in range(window, len(returns) + 1):
        sample = returns[index - window:index]
        mean = sum(sample) / window
        variance = sum((value - mean) ** 2 for value in sample) / (window - 1)
        source_row = rows[index]
        out.append(
            _row(
                source_row["period_start"], source_row["period_end"], math.sqrt(variance) * math.sqrt(365),
                available_time=source_row["available_time"],
                method=source_row.get("available_time_method", "conservative_lag"),
            )
        )
    if not out:
        raise ConnectorError("行情长度不足以计算 30 日实现波动率")
    return out


def fetch_with_retry(
    fetch: Callable[[], FetchResult], *, attempts: int = 3, pause: float = 3.0
) -> FetchResult:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < attempts - 1:
                time.sleep(pause * (attempt + 1))
    raise ConnectorError(str(last))