"""Public data adapters with explicit timestamps and defensive validation."""
from __future__ import annotations
import json
from math import isfinite
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from typing import Iterator
from urllib.request import Request, urlopen

class DataSourceError(RuntimeError):
    """Raised when a public data source cannot provide valid data."""


class PaginationLimitError(DataSourceError):
    """Raised when a paginated source exhausts its bounded page budget.

    Distinct from other source failures so a caller (for example a resumable
    backfill) can treat the page budget as a checkpoint rather than a fault.
    """

# Transient failures are retried. Other 4xx responses fail immediately.
RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 60.0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _retry_after_seconds(exc: HTTPError) -> float | None:
    headers = getattr(exc, "headers", None)
    raw = headers.get("Retry-After") if headers is not None else None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not isfinite(value):
        return None
    return min(max(value, 0.0), MAX_RETRY_AFTER_SECONDS)


def _get_json(url: str, timeout: int = 20, retries: int = 3, base_delay: float = 1.0):
    """Retrieve JSON with bounded retries and source-aware backoff.

    Non-retryable HTTP client errors fail immediately. Retry-After is honored
    for rate-limited responses but capped so a hostile header cannot stall a run.
    """
    if retries < 1:
        raise ValueError("retries must be at least 1.")
    if timeout <= 0 or base_delay < 0:
        raise ValueError("timeout and base_delay must be positive and non-negative.")
    last_error: Exception | None = None
    for attempt in range(retries):
        delay = base_delay * (2 ** attempt)
        try:
            request = Request(url, headers={"User-Agent": "CycleMark-BTC/0.1.0 research bot"})
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise DataSourceError(f"Unexpected HTTP status {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_HTTP_STATUS:
                raise DataSourceError(
                    f"Non-retryable HTTP {exc.code} from source: {exc}"
                ) from exc
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                delay = retry_after
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt + 1 < retries:
            time.sleep(delay)
    raise DataSourceError(f"Unable to retrieve valid JSON from source: {last_error}")

CANDLE_PAGE_LIMIT = 1000
CANDLE_MAX_PAGES = 100
CANDLE_MAX_ROWS = 10000


def fetch_binance_daily_klines(start_time_ms: int | None = None) -> list[dict]:
    """Fetch BTCUSDT daily candles, retaining source close timestamps."""
    rows, _ = fetch_binance_daily_klines_with_stats(start_time_ms)
    return rows


def fetch_binance_daily_klines_with_stats(
    start_time_ms: int | None = None,
) -> tuple[list[dict], dict]:
    """Fetch daily candles and return a bounded request/quality summary.

    Duplicate timestamps are dropped and counted. A full page that does not
    advance the cursor is treated as a source error rather than silently
    returning an incomplete series.
    """
    if start_time_ms is not None and (not isinstance(start_time_ms, int) or start_time_ms < 0):
        raise ValueError("start_time_ms must be a non-negative integer.")
    rows: list[dict] = []
    cursor = 0 if start_time_ms is None else start_time_ms
    pages = 0
    while True:
        if pages >= CANDLE_MAX_PAGES:
            raise DataSourceError("Candle history exceeded the page safety limit.")
        params = {"symbol": "BTCUSDT", "interval": "1d", "limit": CANDLE_PAGE_LIMIT}
        if cursor is not None:
            params["startTime"] = cursor
        payload = _get_json("https://api.binance.com/api/v3/klines?" + urlencode(params))
        pages += 1
        if not isinstance(payload, list):
            raise DataSourceError("Binance kline response was not a list.")
        if not payload:
            break
        for item in payload:
            if not isinstance(item, list) or len(item) < 7:
                raise DataSourceError("Malformed Binance kline record.")
            try:
                row = {
                    "open_time_ms": int(item[0]), "open": float(item[1]),
                    "high": float(item[2]), "low": float(item[3]),
                    "close": float(item[4]), "volume": float(item[5]),
                    "close_time_ms": int(item[6]), "source": "binance_spot_api",
                }
            except (TypeError, ValueError) as exc:
                raise DataSourceError(f"Invalid numeric value in Binance candle: {exc}") from exc
            prices = (row["open"], row["high"], row["low"], row["close"])
            if any(not (value > 0 and value < float("inf")) for value in prices):
                raise DataSourceError("Binance candle prices must be finite and greater than zero.")
            if row["low"] > row["high"] or not row["low"] <= row["open"] <= row["high"] or not row["low"] <= row["close"] <= row["high"]:
                raise DataSourceError("Binance candle violates low/open/close/high bounds.")
            if not (row["volume"] >= 0 and row["volume"] < float("inf")):
                raise DataSourceError("Binance candle volume must be finite and non-negative.")
            if row["close_time_ms"] < row["open_time_ms"]:
                raise DataSourceError("Binance candle close time precedes open time.")
            rows.append(row)
        if len(rows) > CANDLE_MAX_ROWS:
            raise DataSourceError("Unexpectedly large candle history; aborting.")
        if len(payload) < CANDLE_PAGE_LIMIT:
            break
        next_cursor = int(payload[-1][6]) + 1
        if next_cursor <= cursor:
            raise DataSourceError("Binance candle pagination did not advance.")
        cursor = next_cursor

    unique: dict[int, dict] = {}
    duplicate_rows_dropped = 0
    for row in rows:
        if row["open_time_ms"] in unique:
            duplicate_rows_dropped += 1
        unique[row["open_time_ms"]] = row
    ordered = sorted(unique.values(), key=lambda row: row["open_time_ms"])
    stats = {
        "source": "binance_spot_api",
        "pages": pages,
        "raw_rows": len(rows),
        "duplicate_rows_dropped": duplicate_rows_dropped,
        "requested_start_time_ms": start_time_ms,
        "retrieved_at_utc": utc_now(),
    }
    return ordered, stats

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



FUNDING_ENDPOINT = "https://fapi.binance.com/fapi/v1/fundingRate"
FUNDING_SYMBOL = "BTCUSDT"
FUNDING_PAGE_LIMIT = 1000
FUNDING_MAX_PAGES = 100
FUNDING_SCHEMA_VERSION = "1.0"


def _validate_funding_time_range(start_time_ms: int | None, end_time_ms: int | None) -> None:
    if start_time_ms is not None and (not isinstance(start_time_ms, int) or start_time_ms < 0):
        raise ValueError("start_time_ms must be a non-negative integer.")
    if end_time_ms is not None and (not isinstance(end_time_ms, int) or end_time_ms < 0):
        raise ValueError("end_time_ms must be a non-negative integer.")
    if start_time_ms is not None and end_time_ms is not None and end_time_ms < start_time_ms:
        raise ValueError("end_time_ms must not precede start_time_ms.")


def _parse_funding_page(
    payload: list,
    *,
    seen_timestamps: set[int] | None = None,
) -> tuple[list[dict], list[int]]:
    """Validate one funding-rate page.

    Returns normalized observations and the raw page timestamps. Timestamps
    already present in ``seen_timestamps`` are not emitted again, but they still
    participate in cursor advancement.
    """
    if not isinstance(payload, list):
        raise DataSourceError("Binance funding-rate response was not a list.")
    observations: list[dict] = []
    page_timestamps: list[int] = []
    for item in payload:
        if not isinstance(item, dict):
            raise DataSourceError("Malformed Binance funding-rate record.")
        try:
            timestamp = int(item["fundingTime"])
            rate = float(item["fundingRate"])
            mark_raw = item.get("markPrice")
            mark_price = float(mark_raw) if mark_raw not in (None, "") else None
        except (KeyError, TypeError, ValueError) as exc:
            raise DataSourceError(f"Invalid Binance funding-rate field: {exc}") from exc
        if timestamp < 0 or not isfinite(rate):
            raise DataSourceError("Funding timestamp and rate must be finite and valid.")
        if mark_price is not None and (not isfinite(mark_price) or mark_price <= 0):
            raise DataSourceError("Funding mark price must be finite and greater than zero.")
        page_timestamps.append(timestamp)
        if seen_timestamps is not None:
            if timestamp in seen_timestamps:
                continue
            seen_timestamps.add(timestamp)
        observations.append({
            "funding_time_ms": timestamp,
            "funding_rate": rate,
            "mark_price": mark_price,
            "symbol": str(item.get("symbol") or FUNDING_SYMBOL),
            "source": "binance_usdm_funding_rate_api",
            "schema_version": FUNDING_SCHEMA_VERSION,
            "retrieved_at_utc": utc_now(),
        })
    observations.sort(key=lambda row: row["funding_time_ms"])
    return observations, page_timestamps


def fetch_binance_funding_rates(
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[dict]:
    """Fetch raw Binance USD-M BTCUSDT perpetual funding-rate observations.

    With no start time, fetch only the latest API page. When start_time_ms is
    supplied, paginate forward from that timestamp. Funding rates are exchange
    observations and are not by themselves a calibrated CycleMark signal.
    """
    _validate_funding_time_range(start_time_ms, end_time_ms)
    if start_time_ms is None:
        params = {"symbol": FUNDING_SYMBOL, "limit": FUNDING_PAGE_LIMIT}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        payload = _get_json(FUNDING_ENDPOINT + "?" + urlencode(params))
        observations, _ = _parse_funding_page(payload)
        return observations

    rows: list[dict] = []
    for page in iter_binance_funding_rate_pages(
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    ):
        rows.extend(page)
    rows.sort(key=lambda row: row["funding_time_ms"])
    return rows


def iter_binance_funding_rate_pages(
    *,
    start_time_ms: int,
    end_time_ms: int | None = None,
    max_pages: int = FUNDING_MAX_PAGES,
) -> Iterator[list[dict]]:
    """Yield validated funding pages in ascending time order.

    Each yielded page can be persisted immediately, which makes an interrupted
    historical backfill resumable. Pagination must advance strictly; repeats and
    unbounded histories are source errors.
    """
    _validate_funding_time_range(start_time_ms, end_time_ms)
    if not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer.")
    cursor = start_time_ms
    seen_timestamps: set[int] = set()
    for _ in range(max_pages):
        params = {"symbol": FUNDING_SYMBOL, "limit": FUNDING_PAGE_LIMIT, "startTime": cursor}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        payload = _get_json(FUNDING_ENDPOINT + "?" + urlencode(params))
        if not payload:
            return
        observations, page_timestamps = _parse_funding_page(
            payload, seen_timestamps=seen_timestamps
        )
        yield observations
        if len(payload) < FUNDING_PAGE_LIMIT:
            return
        next_cursor = max(page_timestamps) + 1
        if next_cursor <= cursor:
            raise DataSourceError("Binance funding pagination did not advance.")
        if end_time_ms is not None and next_cursor > end_time_ms:
            return
        cursor = next_cursor
    raise PaginationLimitError(
        f"Funding history exceeded the {max_pages}-page safety limit."
    )
