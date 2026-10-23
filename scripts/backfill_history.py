"""Backfill provisional price-only research context."""
from __future__ import annotations
import bisect
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cyclemark.archive import build_daily_record, write_json
from cyclemark.features import compute_provisional_bfs
from cyclemark.sources import DataSourceError, fetch_binance_daily_klines, fetch_fear_greed_history, utc_now

SIGNALS_DIR = ROOT / "data" / "signals"
MODEL_VERSION = "0.1.1"


def main() -> int:
    generated_at = utc_now()
    candles = fetch_binance_daily_klines()
    try:
        sentiment = fetch_fear_greed_history()
    except DataSourceError as exc:
        sentiment = []
        print(f"Auxiliary sentiment history unavailable: {exc}", file=sys.stderr)
    sentiment_times = [
        datetime.fromisoformat(item["observation_timestamp_utc"].replace("Z", "+00:00")).timestamp()
        for item in sentiment
    ]
    records = []
    for index, candle in enumerate(candles):
        close_time = datetime.fromtimestamp(candle["close_time_ms"] / 1000, timezone.utc)
        if close_time >= datetime.now(timezone.utc) or index < 199:
            continue
        sentiment_index = bisect.bisect_right(sentiment_times, close_time.timestamp()) - 1
        observation = sentiment[sentiment_index] if sentiment_index >= 0 else None
        window = candles[:index + 1]
        closes = [item["close"] for item in window]
        highs = [item["high"] for item in window]
        lows = [item["low"] for item in window]
        bfs = compute_provisional_bfs(closes=closes, highs=highs, lows=lows)
        day = datetime.fromtimestamp(candle["open_time_ms"] / 1000, timezone.utc).date()
        market_data = {
            "price": {
                "symbol": "BTCUSDT", "price_usd": round(candle["close"], 2),
                "candle_date_utc": day.isoformat(),
                "price_source": "Binance public spot market API",
            },
        }
        sources = {
            "price": {"name": "Binance public spot market API", "point_in_time_history_verified": False},
        }
        if observation is not None:
            market_data["fear_greed"] = observation
            sources["auxiliary_sentiment"] = {
                "name": "Alternative.me Crypto Fear & Greed Index",
                "point_in_time_history_verified": False,
                "role": "display_only_excluded_from_core_scores",
            }
        record = build_daily_record(
            as_of_date=day, generated_at_utc=generated_at, model_version=MODEL_VERSION,
            status="historical_research_backfill_not_point_in_time",
            market_data=market_data, sources=sources,
            notes=[
                "Historical research backfill, not an originally published CycleMark decision.",
                "Historical source availability and revisions have not been reconstructed.",
                "Core BFS uses price-derived cycle-position and trend features only.",
                "Third-party sentiment is auxiliary display context and does not enter core scores.",
                "BOS and composite state are unavailable.",
            ],
        )
        record["bfs"] = bfs["bfs"]
        record["bfs_status"] = bfs["bfs_status"]
        record["score_coverage"] = {"configured_weight_coverage_pct": bfs["configured_weight_coverage_pct"]}
        record["dimension_scores"] = bfs["dimension_scores"]
        record["feature_values"] = bfs["feature_values"]
        record["limitations"] = bfs["limitations"]
        records.append(record)

    if not records:
        raise DataSourceError("No historical records could be generated.")
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(SIGNALS_DIR / "history.json", records)
    write_json(SIGNALS_DIR / "latest.json", records[-1])
    print(f"Backfilled {len(records)} provisional historical research records.")
    print("These records are not historical published decisions and are not point-in-time validated.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DataSourceError as exc:
        print("Backfill failed safely: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
