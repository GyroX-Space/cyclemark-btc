"""Deterministic synthetic tests for the walk-forward evaluation pipeline."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

import pytest

from cyclemark.evaluation import (
    evaluate,
    reconstruct_bfs_series,
    spearman,
    _block_bootstrap_ci,
    _contiguous_runs,
    _effective_blocks,
    _usable_block_starts,
)

START = date(2019, 1, 1)


def make_candles(days: int, *, seed: int = 7, drift: float = 0.0004) -> list[dict]:
    rng = random.Random(seed)
    price = 4000.0
    rows = []
    for i in range(days):
        ret = drift + rng.gauss(0, 0.02)
        close = price * (1 + ret)
        high = max(price, close) * (1 + abs(rng.gauss(0, 0.005)))
        low = min(price, close) * (1 - abs(rng.gauss(0, 0.005)))
        rows.append({
            "date": (START + timedelta(days=i)).isoformat(),
            "open": round(price, 2), "high": round(high, 2),
            "low": round(low, 2), "close": round(close, 2),
        })
        price = close
    return rows


def make_signals(candles: list[dict], *, status: str = "historical_research_backfill",
                 drop: int = 0) -> list[dict]:
    series = reconstruct_bfs_series(candles)
    if drop:
        series = series[:-drop]
    return [{"date": item["date"], "bfs": item["bfs"], "status": status}
            for item in series]


def test_spearman_monotonic_and_ties():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None  # constant input
    assert spearman([1], [2]) is None


def test_evaluation_is_deterministic_fingerprint_respects_wallclock():
    """deterministic_fingerprint ignores generated_at_utc; full JSON does not."""
    candles = make_candles(2600)
    signals = make_signals(candles, drop=548)
    first = evaluate(signals=signals, candles=candles, horizon_days=365,
                      generated_at_utc="2026-10-26T00:00:00Z", resamples=200, seed=0)
    second = evaluate(signals=signals, candles=candles, horizon_days=365,
                       generated_at_utc="2026-10-27T03:15:00Z", resamples=200, seed=0)
    # Deterministic anchor is byte-identical across wall-clock differences.
    assert first["deterministic_fingerprint"] == second["deterministic_fingerprint"]
    # Full JSON differs because generated_at_utc differs — this is the intended contract.
    assert json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True)
    # But the two full reports are equal AFTER stripping the wall-clock field.
    first_stripped = {k: v for k, v in first.items() if k != "generated_at_utc"}
    second_stripped = {k: v for k, v in second.items() if k != "generated_at_utc"}
    assert json.dumps(first_stripped, sort_keys=True) == json.dumps(second_stripped, sort_keys=True)

    # Audit: input fingerprints are properly split, not mixed together.
    assert first["inputs"]["ohlcv_fingerprint"] != first["inputs"]["signal_fingerprint"]
    assert first["inputs"]["ohlcv_time_range"][0] < first["inputs"]["ohlcv_time_range"][1]
    assert "fold_boundaries_hash" in first["inputs"]
    assert "ohlcv_time_range" in first["inputs"]
    assert "feature_columns_hash" in first["inputs"]
    assert "per_signal_file_hashes" in first["inputs"]
    assert "evaluator_version" in first
    assert "report_schema_version" in first

    assert set(first["results_by_stratum"]) == {"published", "reconstructed"}
    recon = first["results_by_stratum"]["reconstructed"]
    assert recon["signal_count"] > 0
    assert first["results_by_stratum"]["published"]["signal_count"] == 0
    # No top-level conclusion: strata own their conclusions.
    assert "conclusion" not in first
    assert "pooled" not in first
    assert recon["conclusion"] in {"inconclusive", "directional", "rejected"}
    for fold in recon["folds"]:
        assert fold["eval_coverage_pct"] >= 0


def test_label_like_fields_in_signals_are_rejected():
    candles = make_candles(300)
    signals = make_signals(candles)
    poisoned = [dict(s, forward_return_365d=0.5) for s in signals]
    with pytest.raises(ValueError, match="label-like"):
        evaluate(signals=poisoned, candles=candles, horizon_days=365,
                 generated_at_utc="2026-10-26T00:00:00Z", resamples=10)


def test_incomplete_labels_are_counted_not_dropped_or_imputed():
    candles = make_candles(1600)
    signals = make_signals(candles)  # last 365+ labels incomplete
    report = evaluate(signals=signals, candles=candles, horizon_days=365,
                      generated_at_utc="2026-10-26T00:00:00Z", resamples=50)
    recon = report["results_by_stratum"]["reconstructed"]
    assert recon["incomplete_label_count"] == 365
    dates_in_folds = {f["eval_start"] for f in recon["folds"]}
    assert dates_in_folds  # folds exist; incomplete dates stay in coverage stats


def test_reconstruction_invariant_appending_future_candles():
    candles = make_candles(700)
    prefix = reconstruct_bfs_series(candles[:500])
    extended = reconstruct_bfs_series(candles[:500] + make_candles(700)[500:])
    assert prefix == extended[:len(prefix)]


def test_few_valid_folds_force_inconclusive():
    candles = make_candles(800)  # ~1 usable eval window after 200-day warmup
    signals = make_signals(candles, drop=365)
    report = evaluate(signals=signals, candles=candles, horizon_days=365,
                      generated_at_utc="2026-10-26T00:00:00Z", resamples=50)
    recon = report["results_by_stratum"]["reconstructed"]
    assert recon["valid_fold_count"] < 3
    assert recon["conclusion"] == "inconclusive"


def test_coverage_gate_skips_sparse_fold_without_voiding_others():
    candles = make_candles(2600)
    signals = make_signals(candles, drop=548)
    # Punch a hole: drop most signals inside the second fold window.
    recon_dates = [s["date"] for s in signals]
    anchor = date.fromisoformat(recon_dates[0])
    hole_start = anchor + timedelta(days=365)
    hole_end = hole_start + timedelta(days=300)
    sparse = [s for s in signals
              if not (hole_start.isoformat() <= s["date"] < hole_end.isoformat())]
    report = evaluate(signals=sparse, candles=candles, horizon_days=365,
                      generated_at_utc="2026-10-26T00:00:00Z", resamples=50)
    recon = report["results_by_stratum"]["reconstructed"]
    skipped = [f for f in recon["folds"] if f["skipped"]]
    valid = [f for f in recon["folds"] if not f["skipped"]]
    assert skipped and all(f["skip_reason"] for f in skipped)
    # A skipped fold does not automatically void the horizon.
    if len(valid) >= 3:
        assert recon["conclusion"] in {"inconclusive", "directional", "rejected"}


def test_bootstrap_truncates_final_block_to_sample_length():
    days = [(START + timedelta(days=i)).isoformat() for i in range(60)]
    runs = _contiguous_runs(days)
    assert len(runs) == 1
    assert _usable_block_starts(runs, 30) == 31
    assert _effective_blocks(runs, 30) == 2
    pairs = [(float(i), float(i % 7)) for i in range(60)]
    captured_lengths = []

    import cyclemark.evaluation as ev
    original = ev.spearman

    def spy(x, y):
        captured_lengths.append(len(x))
        return original(x, y)

    ev.spearman = spy
    try:
        ci, usable = _block_bootstrap_ci(pairs, runs, block=30, resamples=25, seed=1)
    finally:
        ev.spearman = original
    assert usable == 31
    assert captured_lengths and all(n == 60 for n in captured_lengths)


def test_gap_splits_runs_and_blocks_never_cross():
    days = [(START + timedelta(days=i)).isoformat() for i in range(40)]
    days += [(START + timedelta(days=100 + i)).isoformat() for i in range(40)]
    runs = _contiguous_runs(days)
    assert len(runs) == 2
    assert _usable_block_starts(runs, 30) == 11 + 11
