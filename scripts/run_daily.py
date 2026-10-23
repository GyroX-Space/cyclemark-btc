"""Refresh public market context without inventing unvalidated signals."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cyclemark.archive import build_daily_record, write_json
from cyclemark.features import compute_provisional_bfs
from cyclemark.sources import DataSourceError, fetch_binance_daily_klines, fetch_fear_greed, utc_now

SIGNALS_DIR = ROOT / "data" / "signals"
MODEL_VERSION = "0.1.0"

def main() -> int:
    generated_at = utc_now()
    now = datetime.now(timezone.utc)
    candles = fetch_binance_daily_klines()
    finalized = [c for c in candles if datetime.fromtimestamp(c["close_time_ms"] / 1000, timezone.utc) < now]
    if len(finalized) < 200:
        raise DataSourceError("At least 200 finalized daily candles are required.")
    fear_greed = fetch_fear_greed()
    latest = finalized[-1]
    closes = [c["close"] for c in finalized]
    highs = [c["high"] for c in finalized]
    lows = [c["low"] for c in finalized]
    bfs_result = compute_provisional_bfs(
        closes=closes, highs=highs, lows=lows, fear_greed_value=fear_greed["value"]
    )
    sma_200 = sum(closes[-200:]) / 200
    high_window = finalized[-365:]
    high_365 = max(c["high"] for c in high_window)
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
    record = build_daily_record(
        as_of_date=datetime.fromtimestamp(latest["open_time_ms"] / 1000, timezone.utc).date(),
        generated_at_utc=generated_at, model_version=MODEL_VERSION,
        status="research_data_available_signals_not_yet_validated",
        market_data={"price": price_context, "fear_greed": fear_greed},
        sources={
            "price": {"name": "Binance public spot market API", "retrieved_at_utc": generated_at, "point_in_time_history_verified": False},
            "sentiment": {"name": "Alternative.me Crypto Fear & Greed Index", "retrieved_at_utc": fear_greed["retrieved_at_utc"]},
        },
        notes=[
            "BFS is provisional and uses only sentiment, cycle-position, and trend features; valuation and flow dimensions are missing.",
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
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(SIGNALS_DIR / "latest.json", record)
    write_json(SIGNALS_DIR / (record["date"] + ".json"), record)
    history_path = SIGNALS_DIR / "history.json"
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    history = [item for item in history if item.get("date") != record["date"]]
    history.append(record)
    history.sort(key=lambda item: item["date"])
    write_json(history_path, history)
    print(f"Updated CycleMark public data for {record['date']}")
    print(f"Price: USD {price:,.2f}")
    print(f"Fear & Greed: {fear_greed['value']} ({fear_greed['classification']})")
    print("Provisional BFS: " + str(bfs_result["bfs"]) + " (60% configured-weight coverage; not validated)")
    print("BOS and the composite state remain withheld pending model validation.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DataSourceError as exc:
        print(f"Daily refresh failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
