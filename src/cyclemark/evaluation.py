"""Walk-forward evaluation of the provisional BFS per docs/evaluation-protocol.md.

Research-only. The report never claims validated predictive ability; the
strongest allowed finding is per-stratum, per-horizon "directional evidence".
No live network access; inputs are in-memory records and candle series.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date
from math import floor, isfinite
from typing import Any, Sequence

from .features import compute_provisional_bfs
from .research import build_forward_labels

EVAL_BLOCK_DAYS = 365
MIN_TRAIN_SAMPLES = 200
MIN_EVAL_COVERAGE = 0.80
MIN_VALID_FOLDS = 3
MIN_USABLE_BLOCK_STARTS = 10
MIN_EFFECTIVE_BLOCKS = 10
BFS_BUCKETS = (0, 20, 40, 60, 80, 100)
DEFAULT_RESAMPLES = 2000
DEFAULT_SEED = 0

FEATURE_ALLOW_LIST = frozenset({"date", "bfs", "status", "scores_are_validated"})
FORBIDDEN_TOKENS = ("forward_return", "mfe", "mae", "target")


def _iso(ts_ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()


def normalize_candles(candles: Sequence[dict]) -> list[dict]:
    """Normalize candle dicts to sorted {date, open, high, low, close} rows."""
    rows: list[dict] = []
    for item in candles:
        if not isinstance(item, dict):
            raise ValueError("Candles must be objects.")
        day = item.get("date")
        if day is None and "open_time_ms" in item:
            day = _iso(int(item["open_time_ms"]))
        if not isinstance(day, str):
            raise ValueError("Candle rows must carry a date or open_time_ms.")
        try:
            parsed = date.fromisoformat(day)
        except ValueError as exc:
            raise ValueError(f"Invalid candle date: {day!r}") from exc
        row = {
            "date": parsed.isoformat(),
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
        }
        if any(not isfinite(v) or v <= 0 for v in (row["open"], row["high"], row["low"], row["close"])):
            raise ValueError("Candle prices must be finite and greater than zero.")
        if row["low"] > row["high"] or not row["low"] <= row["close"] <= row["high"]:
            raise ValueError("Each candle must satisfy low <= close <= high.")
        rows.append(row)
    rows.sort(key=lambda r: r["date"])
    if any(b["date"] <= a["date"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Candle dates must be unique.")
    return rows


def reconstruct_bfs_series(candles: Sequence[dict]) -> list[dict]:
    """Prefix-only BFS per date; date t never uses data after t.

    The reconstruction invariant test appends later candles and requires every
    earlier (date, bfs) pair to remain byte-identical.
    """
    rows = normalize_candles(candles)
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    out: list[dict] = []
    for end in range(200, len(rows) + 1):
        score = compute_provisional_bfs(
            closes=closes[:end], highs=highs[:end], lows=lows[:end]
        )
        out.append({"date": rows[end - 1]["date"], "bfs": score["bfs"]})
    return out


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("Spearman inputs must have equal lengths.")
    n = len(x)
    if n < 2:
        return None
    rx, ry = _ranks([float(v) for v in x]), _ranks([float(v) for v in y])
    mx, my = sum(rx) / n, sum(ry) / n
    dx = [v - mx for v in rx]
    dy = [v - my for v in ry]
    sxx = sum(v * v for v in dx)
    syy = sum(v * v for v in dy)
    if sxx == 0.0 or syy == 0.0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / (sxx * syy) ** 0.5


def _quantile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    pos = (len(sorted_vals) - 1) * q
    lo = floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _contiguous_runs(dates: list[str]) -> list[list[str]]:
    runs: list[list[str]] = []
    current: list[str] = []
    for value in dates:
        day = date.fromisoformat(value)
        if current and (day - date.fromisoformat(current[-1])).days != 1:
            runs.append(current)
            current = []
        current.append(value)
    if current:
        runs.append(current)
    return runs


def _usable_block_starts(runs: list[list[str]], block: int) -> int:
    return sum(max(0, len(run) - block + 1) for run in runs)


def _effective_blocks(runs: list[list[str]], block: int) -> int:
    return sum(len(run) // block for run in runs)


def _block_bootstrap_ci(
    pairs: list[tuple[float, float]],
    runs: list[list[str]],
    *,
    block: int,
    resamples: int,
    seed: int,
) -> tuple[list[float | None], int]:
    """Percentile 95% CI of Spearman via contiguous-block bootstrap."""
    by_date = {d: p for d, p in zip([d for run in runs for d in run], pairs)}
    starts: list[tuple[int, int]] = []  # (run_index, offset)
    for ri, run in enumerate(runs):
        for offset in range(0, len(run) - block + 1):
            starts.append((ri, offset))
    usable = len(starts)
    if usable < 1 or len(pairs) < 2:
        return [None, None], usable
    rng = random.Random(seed)
    n = len(pairs)
    stats: list[float] = []
    for _ in range(resamples):
        picked: list[tuple[float, float]] = []
        while len(picked) < n:
            ri, offset = rng.choice(starts)
            run = runs[ri]
            for value in run[offset : offset + block]:
                picked.append(by_date[value])
                if len(picked) == n:  # truncate final block to sample length
                    break
        rho = spearman([a for a, _ in picked], [b for _, b in picked])
        if rho is not None:
            stats.append(rho)
    stats.sort()
    if len(stats) < 20:
        return [None, None], usable
    return [_quantile(stats, 0.025), _quantile(stats, 0.975)], usable


def _bucket_summary(rows: list[dict]) -> list[dict]:
    out = []
    for lo, hi in zip(BFS_BUCKETS, BFS_BUCKETS[1:]):
        vals = sorted(r["forward_return"] for r in rows if lo <= r["bfs"] < hi)
        out.append({
            "bucket": [lo, hi],
            "count": len(vals),
            "forward_return_median": _quantile(vals, 0.5),
        })
    return out


def _baseline_values(candles: list[dict]) -> dict[str, dict]:
    """Prefix-only baseline feature values per date."""
    by_date: dict[str, dict] = {}
    closes = [r["close"] for r in candles]
    highs = [r["high"] for r in candles]
    for i, row in enumerate(candles):
        entry: dict[str, float] = {"drawdown_from_ath": closes[i] / max(highs[: i + 1]) - 1.0}
        if i >= 199:
            entry["price_vs_sma_200"] = closes[i] / (sum(closes[i - 199 : i + 1]) / 200) - 1.0
        by_date[candles[i]["date"]] = entry
    return by_date


def evaluate(
    *,
    signals: Sequence[dict],
    candles: Sequence[dict],
    horizon_days: int,
    generated_at_utc: str,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    signal_files: Sequence[str] | dict[str, Any] = (),
    ohlcv_source: str = "local_input",
) -> dict:
    """Run one horizon's evaluation. Raises ValueError on invalid input."""
    if horizon_days not in (365, 548):
        raise ValueError("horizon_days must be 365 or 548.")
    rows = normalize_candles(candles)

    # Leakage guard: only allow-listed signal fields are read.
    for record in signals:
        if not isinstance(record, dict):
            raise ValueError("Signal records must be objects.")
        extra = set(record) - FEATURE_ALLOW_LIST - {
            "schema_version", "generated_at_utc", "model_version", "state", "bos",
            "market_data", "sources", "notes", "revision", "first_published_at_utc",
            "data_quality",
        }
        forbidden = [k for k in extra if any(t in k for t in FORBIDDEN_TOKENS)]
        if forbidden:
            raise ValueError(f"Signal record contains label-like fields: {forbidden}")

    if len(rows) < horizon_days + 200:
        raise ValueError("Not enough candles for the requested horizon.")

    labels = build_forward_labels(
        dates=[r["date"] for r in rows],
        closes=[r["close"] for r in rows],
        highs=[r["high"] for r in rows],
        lows=[r["low"] for r in rows],
        horizons_days=[horizon_days],
    )
    label_by_date = {item["signal_date"]: item["horizons"][str(horizon_days)] for item in labels}
    candle_dates = {r["date"] for r in rows}
    baselines = _baseline_values(rows)

    per_stratum: dict[str, list[dict]] = {"published": [], "reconstructed": []}
    excluded_no_candle = 0  # counted inside per-stratum loop below
    excluded_no_bfs = 0

    for record in signals:
        day = record.get("date")
        if not isinstance(day, str) or day not in candle_dates:
            excluded_no_candle += 1
            continue
        bfs = record.get("bfs")
        if bfs is None or not isfinite(float(bfs)):
            excluded_no_bfs += 1
            continue
        status = str(record.get("status") or "")
        stratum = "reconstructed" if "historical_research_backfill" in status else "published"
        label = label_by_date.get(day)
        entry = {
            "date": day,
            "bfs": float(bfs),
            "label_complete": label is not None,
            "forward_return": label["forward_return"] if label else None,
            "mfe_pct": label["max_favorable_excursion_pct"] if label else None,
            "mae_pct": label["max_adverse_excursion_pct"] if label else None,
            "target_observation_date": label["target_observation_date"] if label else None,
        }
        per_stratum[stratum].append(entry)

    for stratum_rows in per_stratum.values():
        stratum_rows.sort(key=lambda r: r["date"])

    results_by_stratum: dict[str, dict] = {}
    for stratum, srows in per_stratum.items():
        complete = [r for r in srows if r["label_complete"]]
        incomplete_count = len(srows) - len(complete)
        anchor = date.fromisoformat(srows[0]["date"]) if srows else None
        last_day = date.fromisoformat(srows[-1]["date"]) if srows else None

        folds: list[dict] = []
        valid_fold_dates: list[str] = []
        if anchor is not None and last_day is not None:
            from datetime import timedelta
            k = 0
            while True:
                eval_start = anchor + timedelta(days=EVAL_BLOCK_DAYS * k)
                eval_end = eval_start + timedelta(days=EVAL_BLOCK_DAYS)
                if eval_start > last_day:
                    break
                train = [r for r in complete
                         if r["target_observation_date"] < eval_start.isoformat()]
                eval_rows = [r for r in srows
                             if eval_start.isoformat() <= r["date"] < eval_end.isoformat()]
                eval_complete = [r for r in eval_rows if r["label_complete"]]
                expected_days = (eval_end - eval_start).days
                coverage = len(eval_rows) / expected_days if expected_days else 0.0
                fold = {
                    "index": k,
                    "eval_start": eval_start.isoformat(),
                    "eval_end": eval_end.isoformat(),
                    "train_count": len(train),
                    "eval_count": len(eval_rows),
                    "eval_complete_label_count": len(eval_complete),
                    "eval_coverage_pct": round(coverage * 100, 2),
                    "skipped": False,
                    "skip_reason": None,
                    "metrics": None,
                }
                if coverage < MIN_EVAL_COVERAGE:
                    fold["skipped"] = True
                    fold["skip_reason"] = "coverage_below_80pct"
                elif len(train) < MIN_TRAIN_SAMPLES:
                    fold["skipped"] = True
                    fold["skip_reason"] = "train_below_min_samples"
                else:
                    xs = [r["bfs"] for r in eval_complete]
                    ys = [r["forward_return"] for r in eval_complete]
                    rho = spearman(xs, ys)
                    base = baselines
                    ath_rho = spearman(
                        [base[r["date"]]["drawdown_from_ath"] for r in eval_complete], ys)
                    sma_pairs = [r for r in eval_complete
                                 if "price_vs_sma_200" in base[r["date"]]]
                    sma_rho = spearman(
                        [base[r["date"]]["price_vs_sma_200"] for r in sma_pairs],
                        [r["forward_return"] for r in sma_pairs]) if len(sma_pairs) >= 2 else None
                    ret_sorted = sorted(ys)
                    fold["metrics"] = {
                        "spearman_bfs_forward_return": rho,
                        "forward_return_quantiles": {
                            "p10": _quantile(ret_sorted, 0.10),
                            "median": _quantile(ret_sorted, 0.50),
                            "p90": _quantile(ret_sorted, 0.90),
                        },
                        "bfs_buckets": _bucket_summary(eval_complete),
                        "baselines": {
                            "unconditional_median_forward_return": _quantile(ret_sorted, 0.50),
                            "ath_drawdown_spearman": ath_rho,
                            "sma200_relative_spearman": sma_rho,
                        },
                    }
                    valid_fold_dates.extend(r["date"] for r in eval_complete)
                folds.append(fold)
                k += 1

        valid_folds = [f for f in folds if not f["skipped"]]
        valid_set = set(valid_fold_dates)
        pair_by_date = {r["date"]: (r["bfs"], r["forward_return"]) for r in complete
                        if r["date"] in valid_set}
        runs = _contiguous_runs(sorted(valid_set))
        usable = _usable_block_starts(runs, horizon_days)
        effective = _effective_blocks(runs, horizon_days)
        pooled_pairs = [pair_by_date[d] for run in runs for d in run]
        pooled_rho = spearman([a for a, _ in pooled_pairs], [b for _, b in pooled_pairs]) \
            if len(pooled_pairs) >= 2 else None
        ci, usable = _block_bootstrap_ci(
            pooled_pairs, runs, block=horizon_days, resamples=resamples, seed=seed)
        weak = usable < MIN_USABLE_BLOCK_STARTS or effective < MIN_EFFECTIVE_BLOCKS
        if len(valid_folds) < MIN_VALID_FOLDS or usable < MIN_USABLE_BLOCK_STARTS:
            conclusion = "inconclusive"
        elif ci[0] is None or ci[0] <= 0 <= ci[1]:
            conclusion = "inconclusive"
        elif pooled_rho is not None and pooled_rho > 0:
            conclusion = "directional"
        else:
            conclusion = "rejected"
        results_by_stratum[stratum] = {
            "signal_count": len(srows),
            "incomplete_label_count": incomplete_count,
            "valid_fold_count": len(valid_folds),
            "usable_block_starts": usable,
            "effective_blocks_or_cycles": effective,
            "weak_evidence": weak,
            "pooled_spearman": pooled_rho,
            "spearman_ci_95": ci,
            "conclusion": conclusion,
            "folds": folds,
        }

    # Audit fingerprints — each covers exactly one input category so reviewers
    # can locate which input changed across runs. Nothing is mixed together.
    def _hash(obj: Any) -> str:
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    ohlcv_fingerprint = _hash(rows)
    signal_fingerprint = _hash(signals)
    signal_files_input = signal_files  # preserve original type for per-file hashes
    # Per-file hashes: either the caller supplied {name: content_bytes_or_dict}
    # or we derive hashes from the resolved signal records.
    per_signal_file_hashes: dict[str, str] = {}
    if isinstance(signal_files_dict := signal_files_input, dict):
        for name, content in signal_files_dict.items():
            if isinstance(content, (bytes, bytearray)):
                per_signal_file_hashes[name] = hashlib.sha256(content).hexdigest()
            else:
                per_signal_file_hashes[name] = _hash(content)
    else:
        for idx, record in enumerate(signals):
            per_signal_file_hashes[f"signal[{idx}]"] = _hash(record)
    feature_columns = ["bfs"]
    feature_columns_hash = _hash(feature_columns)
    fold_boundaries: list[dict] = []
    for stratum, result in results_by_stratum.items():
        for fold in result.get("folds", []):
            fold_boundaries.append({
                "stratum": stratum,
                "index": fold["index"],
                "eval_start": fold["eval_start"],
                "eval_end": fold["eval_end"],
                "skipped": fold["skipped"],
                "skip_reason": fold["skip_reason"],
            })
    ohlcv_dates = [r["date"] for r in rows]
    EVALUATOR_VERSION = "0.1.1"  # bump whenever the algorithm or audit contract changes
    # Deterministic anchor — excludes generated_at_utc (wall-clock) and
    # bootstrap noise that varies with resample count, so that two runs with
    # identical inputs and fixed seed compare equal on this field.
    deterministic_fingerprint = _hash({
        "evaluator_version": EVALUATOR_VERSION,
        "report_schema_version": "1.2",
        "ohlcv_fingerprint": ohlcv_fingerprint,
        "signal_fingerprint": signal_fingerprint,
        "per_signal_file_hashes": per_signal_file_hashes,
        "feature_columns_hash": feature_columns_hash,
        "horizon_days": horizon_days,
        "seed": seed,
        "resamples": resamples,
        "fold_boundaries": fold_boundaries,
        "feature_columns": feature_columns,
        "conclusions": {s: r["conclusion"] for s, r in results_by_stratum.items()},
    })
    return {
        "report_schema_version": "1.2",
        "evaluator_version": EVALUATOR_VERSION,
        "generated_at_utc": generated_at_utc,
        "deterministic_fingerprint": deterministic_fingerprint,
        "horizon_days": horizon_days,
        "co_primary_horizons": [365, 548],
        "primary_statistic": "spearman",
        "multiplicity": "per_horizon_conclusions_no_independence_or_joint_claim",
        "fold": {"block_days": EVAL_BLOCK_DAYS, "min_train_samples": MIN_TRAIN_SAMPLES,
                 "min_eval_coverage_pct": 80, "min_valid_folds": MIN_VALID_FOLDS},
        "purge_rule": "training target_observation_date < eval_start",
        "inputs": {
            "ohlcv_fingerprint": ohlcv_fingerprint,
            "signal_fingerprint": signal_fingerprint,
            "per_signal_file_hashes": per_signal_file_hashes,
            "feature_columns_hash": feature_columns_hash,
            "signal_files": list(signal_files_input) if isinstance(signal_files_input, dict) else list(signal_files_input),
            "ohlcv_source": ohlcv_source,
            "ohlcv_time_range": [ohlcv_dates[0], ohlcv_dates[-1]] if ohlcv_dates else None,
            "fold_boundaries_hash": _hash(fold_boundaries),
        },
        "columns": {"features": feature_columns,
                    "feature_columns_hash": feature_columns_hash,
                    "labels": [f"forward_return_{horizon_days}d"]},
        "coverage": {"excluded_no_candle": excluded_no_candle,
                     "excluded_no_bfs": excluded_no_bfs},
        "bfs_buckets": list(BFS_BUCKETS),
        "bootstrap": {"resamples": resamples, "block_days": horizon_days, "seed": seed,
                      "frame": "per_stratum_pooled_valid_eval_sample",
                      "per_fold_intervals": "not_reported",
                      "truncation": "final_block_truncated_to_sample_length"},
        "results_by_stratum": results_by_stratum,
        "limitations": [
            "BFS is a provisional, unvalidated price sub-index with 40% configured coverage.",
            "Entry-relative MFE/MAE cannot establish intrabar ordering; not stop/take-profit evidence.",
            "Reconstructed stratum uses history retrieved later; not contemporaneously published signals.",
            "Historical price data may have been revised by the source.",
            "effective_blocks_or_cycles is a mechanical non-overlapping block count, not verified independent cycles.",
            "No joint or independence claim is made across horizons or strata.",
            "deterministic_fingerprint excludes generated_at_utc so wall-clock differences do not break reruns.",
        ],
    }
