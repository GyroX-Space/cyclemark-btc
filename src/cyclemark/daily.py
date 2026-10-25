"""Daily research refresh orchestration with explicit failure boundaries.

Core price failures fail closed: no record is published. Optional feeds and the
optional funding archive are isolated so they cannot block price-only scoring.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cyclemark.archive import (
    build_daily_record,
    merge_funding_rate_observations,
    publish_daily_record,
    write_json,
)
from cyclemark.features import compute_provisional_bfs
from cyclemark.quality import summarize_candle_quality
from cyclemark.sources import (
    DataSourceError,
    fetch_binance_daily_klines_with_stats,
    fetch_binance_funding_rates,
    fetch_fear_greed,
    utc_now,
)

MODEL_VERSION = "0.1.1"
FUNDING_ARCHIVE_NAME = "binance_funding_rates.json"


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def run_daily_refresh(
    *,
    signals_dir: str | Path,
    market_dir: str | Path,
    now: datetime | None = None,
    generated_at_utc: str | None = None,
    fetch_candles: Callable[[], tuple[list[dict], dict]] | None = None,
    fetch_sentiment: Callable[[], dict] | None = None,
    fetch_funding: Callable[[], list[dict]] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Run one daily refresh and return the published record and diagnostics.

    Raises DataSourceError when core price data is unavailable or fails quality
    checks. Optional source failures are recorded in the record metadata and the
    run still publishes the price-only result.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    now = now.astimezone(timezone.utc)
    generated_at = generated_at_utc or utc_now()
    log = log or _log
    fetch_candles = fetch_candles or fetch_binance_daily_klines_with_stats
    fetch_sentiment = fetch_sentiment or fetch_fear_greed
    fetch_funding = fetch_funding or fetch_binance_funding_rates

    candles, fetch_stats = fetch_candles()
    finalized = [
        candle for candle in candles
        if datetime.fromtimestamp(candle["close_time_ms"] / 1000, timezone.utc) < now
    ]
    if len(finalized) < 200:
        raise DataSourceError("At least 200 finalized daily candles are required.")

    quality = summarize_candle_quality(finalized, now_utc=now, fetch_stats=fetch_stats)
    if quality["fatal_issues"]:
        raise DataSourceError(
            "Core price data failed quality checks: " + "; ".join(quality["fatal_issues"])
        )

    optional_sources: dict[str, dict] = {}
    fear_greed = None
    try:
        fear_greed = fetch_sentiment()
        optional_sources["fear_greed"] = {"status": "available"}
    except DataSourceError as exc:
        optional_sources["fear_greed"] = {"status": "unavailable", "error": str(exc)}
        log(f"Auxiliary Fear & Greed data unavailable: {exc}")

    funding_rates = None
    funding_source_status: dict = {"status": "unavailable"}
    try:
        funding_rates = fetch_funding()
        funding_source_status = (
            {"status": "available", "observations_retrieved": len(funding_rates)}
            if funding_rates else {"status": "empty"}
        )
    except DataSourceError as exc:
        funding_source_status = {"status": "unavailable", "error": str(exc)}
        log(f"Binance funding-rate data unavailable: {exc}")
    optional_sources["funding"] = funding_source_status

    latest = finalized[-1]
    closes = [candle["close"] for candle in finalized]
    highs = [candle["high"] for candle in finalized]
    lows = [candle["low"] for candle in finalized]
    bfs_result = compute_provisional_bfs(closes=closes, highs=highs, lows=lows)
    sma_200 = sum(closes[-200:]) / 200
    high_window = finalized[-365:]
    high_365 = max(candle["high"] for candle in high_window)
    price = latest["close"]
    price_context = {
        "symbol": "BTCUSDT", "price_usd": round(price, 2),
        "candle_date_utc": datetime.fromtimestamp(latest["open_time_ms"] / 1000, timezone.utc).date().isoformat(),
        "candle_close_time_utc": datetime.fromtimestamp(latest["close_time_ms"] / 1000, timezone.utc).isoformat().replace("+00:00", "Z"),
        "sma_200_usd": round(sma_200, 2),
        "price_vs_sma_200_pct": round((price / sma_200 - 1) * 100, 2),
        "drawdown_from_365d_high_pct": round((price / high_365 - 1) * 100, 2),
        "drawdown_from_all_time_high_pct": bfs_result["feature_values"]["drawdown_from_all_time_high_pct"],
        "momentum_30d_pct": round((closes[-1] / closes[-31] - 1) * 100, 2),
        "momentum_90d_pct": round((closes[-1] / closes[-91] - 1) * 100, 2),
        "price_source": "Binance public spot market API", "history_candles": len(finalized),
    }
    sources = {
        "price": {
            "name": "Binance public spot market API",
            "retrieved_at_utc": generated_at,
            "point_in_time_history_verified": False,
        },
    }
    market_data = {"price": price_context}
    if funding_rates:
        market_data["derivatives"] = {
            "latest_funding_rate": funding_rates[-1],
            "funding_observations_retrieved": len(funding_rates),
            "core_score_role": "research_archive_only_excluded_from_core_scores",
        }
        sources["derivatives_funding"] = {
            "name": "Binance USD-M BTCUSDT perpetual funding-rate API",
            "retrieved_at_utc": funding_rates[-1]["retrieved_at_utc"],
            "role": "raw_exchange_observation_archived_not_used_in_core_scores",
            "archive_path": f"data/market/{FUNDING_ARCHIVE_NAME}",
        }
    if fear_greed is not None:
        market_data["fear_greed"] = fear_greed
        sources["auxiliary_sentiment"] = {
            "name": "Alternative.me Crypto Fear & Greed Index",
            "retrieved_at_utc": fear_greed["retrieved_at_utc"],
            "role": "display_only_excluded_from_core_scores",
        }

    record = build_daily_record(
        as_of_date=datetime.fromtimestamp(latest["open_time_ms"] / 1000, timezone.utc).date(),
        generated_at_utc=generated_at, model_version=MODEL_VERSION,
        status="research_data_available_signals_not_yet_validated",
        market_data=market_data,
        sources=sources,
        notes=[
            "BFS is provisional and uses price-derived cycle-position and trend features only; three dimensions are missing.",
            "Third-party Fear & Greed is auxiliary display context and is excluded from BFS, BOS, and state assignment.",
            "Perpetual funding rates are archived as raw exchange observations for research and are not yet used in BFS, BOS, or state assignment.",
            "BOS and the composite state are withheld until the complete model and validation protocol are implemented.",
            "Historical point-in-time source revisions have not been reconstructed.",
            "This record is research context, not a validated trading signal.",
        ],
    )
    record["bfs"] = bfs_result["bfs"]
    record["bfs_status"] = bfs_result["bfs_status"]
    record["score_coverage"] = {"configured_weight_coverage_pct": bfs_result["configured_weight_coverage_pct"]}
    record["dimension_scores"] = bfs_result["dimension_scores"]
    record["feature_values"] = bfs_result["feature_values"]
    record["limitations"] = bfs_result["limitations"]
    record["data_quality"] = {
        "core_price": quality,
        "optional_sources": optional_sources,
    }

    publication = publish_daily_record(
        signals_dir, record, published_at_utc=generated_at
    )

    funding_archive: dict = {"status": "not_attempted"}
    if funding_rates:
        archive_path = Path(market_dir) / FUNDING_ARCHIVE_NAME
        try:
            existing = (
                json.loads(archive_path.read_text(encoding="utf-8"))
                if archive_path.exists() else []
            )
            if not isinstance(existing, list):
                raise ValueError("Funding archive must contain a JSON list.")
            merged = merge_funding_rate_observations(existing, funding_rates)
            write_json(archive_path, merged)
            funding_archive = {
                "status": "written",
                "observation_count": len(merged),
                "retrieved_observation_count": len(funding_rates),
            }
        except (OSError, ValueError) as exc:
            funding_archive = {"status": "failed", "error": str(exc)}
            log(f"Optional funding archive update failed without blocking the daily record: {exc}")

    return {
        "record": record,
        "publication": publication,
        "funding_archive": funding_archive,
        "quality": quality,
    }
