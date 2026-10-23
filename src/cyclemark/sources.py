"""Public data adapters with explicit timestamps and defensive validation."""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

class DataSourceError(RuntimeError):
    """Raised when a public data source cannot provide valid data."""

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _get_json(url: str, timeout: int = 20, retries: int = 3):
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": "CycleMark-BTC/0.1.0 research bot"})
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise DataSourceError(f"Unexpected HTTP status {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise DataSourceError(f"Unable to retrieve valid JSON from source: {last_error}")

def fetch_binance_daily_klines(start_time_ms: int | None = None) -> list[dict]:
    """Fetch BTCUSDT daily candles, retaining source close timestamps."""
    rows = []
    cursor = 0 if start_time_ms is None else start_time_ms
    while True:
        params = {"symbol": "BTCUSDT", "interval": "1d", "limit": 1000}
        if cursor is not None:
            params["startTime"] = cursor
        payload = _get_json("https://api.binance.com/api/v3/klines?" + urlencode(params))
        if not isinstance(payload, list):
            raise DataSourceError("Binance kline response was not a list.")
        if not payload:
            break
        for item in payload:
            if not isinstance(item, list) or len(item) < 7:
                raise DataSourceError("Malformed Binance kline record.")
            rows.append({
                "open_time_ms": int(item[0]), "open": float(item[1]),
                "high": float(item[2]), "low": float(item[3]),
                "close": float(item[4]), "volume": float(item[5]),
                "close_time_ms": int(item[6]), "source": "binance_spot_api",
            })
        next_cursor = int(payload[-1][6]) + 1
        if len(payload) < 1000 or (cursor is not None and next_cursor <= cursor):
            break
        cursor = next_cursor
        if len(rows) > 10000:
            raise DataSourceError("Unexpectedly large candle history; aborting.")
    rows.sort(key=lambda row: row["open_time_ms"])
    return list({row["open_time_ms"]: row for row in rows}.values())

def fetch_fear_greed() -> dict:
    """Fetch the latest Crypto Fear & Greed observation from Alternative.me."""
    payload = _get_json("https://api.alternative.me/fng/?limit=3&format=json")
    try:
        item = payload["data"][0]
        value = int(item["value"])
        timestamp = int(item["timestamp"])
        classification = str(item["value_classification"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DataSourceError(f"Malformed Fear & Greed response: {exc}") from exc
    if not 0 <= value <= 100:
        raise DataSourceError("Fear & Greed value is outside [0, 100].")
    return {
        "value": value, "classification": classification,
        "observation_timestamp_utc": datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z"),
        "retrieved_at_utc": utc_now(), "source": "alternative_me_fear_greed_api",
    }


def fetch_fear_greed_history() -> list[dict]:
    """Fetch the historical Alternative.me series for research backfill.

    Historical values are not assumed to have been available to CycleMark at
    their observation timestamps. Backfilled outputs must retain that caveat.
    """
    payload = _get_json("https://api.alternative.me/fng/?limit=0&format=json")
    raw = payload.get("data")
    if not isinstance(raw, list):
        raise DataSourceError("Fear & Greed history response did not contain a data list.")
    result = []
    for item in raw:
        try:
            value = int(item["value"])
            timestamp = int(item["timestamp"])
            classification = str(item["value_classification"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DataSourceError(f"Malformed Fear & Greed history row: {exc}") from exc
        if not 0 <= value <= 100:
            raise DataSourceError("Fear & Greed history value is outside [0, 100].")
        result.append({
            "value": value,
            "classification": classification,
            "observation_timestamp_utc": datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "alternative_me_fear_greed_api",
        })
    result.sort(key=lambda item: item["observation_timestamp_utc"])
    if not result:
        raise DataSourceError("Fear & Greed history is empty.")
    return result
