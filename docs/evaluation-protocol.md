# Walk-Forward Evaluation Protocol (Revised Design)

**Status:** Revised after architecture review on issue #6. Implementation is intentionally deferred until this design is re-approved. No evaluation code or performance results are claimed here.

## 1. Scope and boundary

Build a reproducible evaluation command that joins as-of CycleMark signals with forward outcome labels and reports whether the signal adds information beyond predeclared baselines.

Financial conclusions cannot precede evidence. The current BFS is a manually constructed, 40%-configured-coverage price sub-index with `scores_are_validated=false`. It may be evaluated as an exploratory continuous score, but it must never be described as a calibrated probability, a validated bottom probability, or a reliable buy/sell signal.

In scope:

- Join signal records to price observations by explicit signal date.
- Chronological walk-forward folds with target-date purging.
- Predeclared baselines, metrics, uncertainty, and a machine-readable report.
- Automated leakage guards, including a historical-reconstruction invariant.

Out of scope:

- Fitting a live model, tuning production thresholds, or publishing performance claims.
- Simulating a full portfolio with execution costs (separate protocol).
- Funding or sentiment features. Only fields already present in published records are evaluated.
- Converting a score into a market-state assignment; state thresholds are not approved.

## 2. Prerequisites and inputs

**Prerequisite — raw OHLCV snapshots.** Historical reconstruction relies on historical price data. The archive must record the source, time range, and a content fingerprint of the OHLCV data used, and must state explicitly that today's downloaded history is not a snapshot that was available at historical dates. Source revisions must be documented as a limitation. Without this provenance, reconstruction results are not reportable.

Signal inputs come from `data/signals/*.json` (excluding `history.json`, `latest.json`, and `revisions/`). Required fields:

| Field | Use |
| --- | --- |
| `date` | Signal date key |
| `bfs` | Evaluated exploratory continuous score (nullable) |
| `bos` | Secondary score (nullable, not evaluated until defined) |
| `state` | Present but not used for events in this protocol |
| `scores_are_validated` | Reported, never used to filter silently |

Label inputs come from `cyclemark.research.build_forward_labels(candles, horizon_days=365|548)`.

Join rules:

1. A signal is usable only if a finalized candle exists with the same UTC date. Gaps are excluded and counted, never forward-filled.
2. The signal's own close is the label entry price.
3. Records with `status` containing `historical_research_backfill` are a separate stratum. They are not original published decisions and must not be mixed into the primary published-signal result. Reconstruction samples are reported under their own stratum.

## 3. Fold construction

Folds are chronological. Random shuffling is prohibited. The training set grows forward (expanding window); there is no rolling training window.

Let `H` be the label horizon in calendar days (`365` or `548`) and `E = 365` the evaluation block length.

For fold `k`:

- `eval_start = anchor + k * E`, `eval_end = eval_start + E`.
- **Purge rule:** training samples must satisfy `label_target_observation_date < eval_start`. This is the only leakage boundary. No extra `H`-day embargo gap is applied before the evaluation block, and no embargo is applied after it (post-test data never enters training).
- Training set = signals whose label target observation date is observed and strictly earlier than `eval_start`. Any sample whose label is incomplete (target date not yet reached) is excluded from training and counted in coverage.
- **Coverage gate:** an evaluation fold is skipped unless at least 80% of the expected calendar dates in its window carry a usable signal. The 200-sample training minimum is only a mechanical floor, not evidence of 200 independent observations.
- A fold is also skipped if the training count is below the floor.
- If fewer than three valid evaluation folds exist for a horizon, the pooled conclusion for that horizon is `inconclusive`.

## 4. Leakage guards

The evaluation fails closed if any guard fails:

1. Feature columns are an explicit allow-list. Label columns (`forward_return_*`, `mfe_*`, `mae_*`, `target_*`, `target_observation_date`) must not appear in the feature matrix.
2. Every training signal's `label_target_observation_date` is strictly earlier than its fold's `eval_start`.
3. Normalizers, calibration, and any threshold selection are fit per fold on training rows only.
4. The report records a hash of the feature column list, horizon, fold boundaries, and source file fingerprints.
5. **Historical reconstruction invariant (required test):** given a candle series, compute the reconstruction BFS for every date `t` using only data up to `t`; then append candles strictly after `t` and recompute. The BFS for date `t` must be byte-identical. This catches future-leakage patterns such as computing ATH drawdown against the full series instead of the prefix up to `t`.
6. A unit test constructs a synthetic series where the label is a deterministic function of a forbidden column and asserts the evaluation cannot exploit it.

## 5. Metrics

The primary analysis is the association between the continuous BFS and forward returns. Do not fabricate market-state events; `state` is not approved as an event definition yet.

Per horizon and per fold:

- Signal counts, usable joins, excluded dates, incomplete-label counts, coverage percentage, and estimated independent cycle count.
- Forward return quantiles (median, 10th, 90th) for the full sample and for **predeclared fixed BFS buckets** (e.g. `[0,20)`, `[20,40)`, ...). Buckets are declared in the report schema and must not be chosen after seeing results.
- Entry-relative MFE/MAE distributions. These are not portfolio drawdowns. The report notes that daily highs/lows cannot establish intrabar ordering, so MFE/MAE cannot be used as stop-loss / take-profit simulation evidence.
- Predeclared research hypothesis (for example "higher BFS is monotonically associated with higher 365-day forward return"). The test of this hypothesis is reported; thresholds are not selected post hoc.
- Event precision/recall/lift are deferred until a formal event definition is approved.

Aggregation across folds reports each fold, plus pooled estimates with the fold count. A pooled point estimate without fold dispersion is not reportable.

## 6. Baselines

All baselines are computed on the identical evaluation dates as BFS:

1. Unconditional forward-return distribution for the horizon.
2. ATH-drawdown-only rule (drawdown from the observed all-time high, computed prefix-only as of each signal date).
3. 200-day moving-average relative-position rule (price / 200-day MA, prefix-only).
4. BFS itself.

Buy-and-hold BTC may be reported as a reference return over the same interval, but it is not a strategy backtest: without explicit signal timing, position sizing, costs, and execution rules, it must not be presented as a comparable strategy result.

## 7. Statistical uncertainty

- Use fixed-seed block bootstrap, 2,000 resamples. Block length must be at least the label horizon `H` (365 or 548 days), so overlapping daily samples are not treated as independent.
- Report per-fold results alongside pooled estimates.
- If the number of effective independent blocks or cycles is fewer than 10, mark interval estimates as **weak / exploratory**. The report must not claim predictive ability is established in that case.
- If fewer than three valid folds exist, conclusion is `inconclusive` regardless of point estimates.

## 8. Backfill and reconstruction stratum

Historical reconstruction signals may be used for independent historical research, but they are not original published decisions.

- Published-signal and reconstructed-signal strata are reported separately and never pooled together as if they were one sample.
- Reconstruction uses only data available up to each date (enforced by the invariant in §4.5).
- The report states that reconstructed data was generated later and does not represent decisions actually issued at those dates.
- Source-revision limitations of historical price data are recorded in the report.

## 9. Missing labels

- Dates with incomplete labels are retained in coverage and exclusion-reason statistics.
- Result metrics for a horizon use only labels that have been fully observed.
- No imputation of future results and no silent deletion of incomplete-label dates.

## 10. Report format

A single JSON document with:

```json
{
  "report_schema_version": "1.1",
  "generated_at_utc": "...",
  "horizon_days": 365,
  "fold": {"block_days": 365, "min_train_samples": 200, "min_eval_coverage_pct": 80, "min_valid_folds": 3},
  "purge_rule": "training target_observation_date < eval_start",
  "inputs": {"ohlcv_fingerprint": "sha256", "signal_files": ["..."], "ohlcv_source": "...", "ohlcv_time_range": ["...", "..."]},
  "columns": {"features": ["bfs"], "labels": ["forward_return_365d", "mfe_365d", "mae_365d"]},
  "bfs_buckets": [0, 20, 40, 60, 80, 100],
  "bootstrap": {"resamples": 2000, "block_days": 365, "seed": 0},
  "strata": ["published", "reconstructed"],
  "folds": [
    {"index": 0, "eval_start": "...", "eval_end": "...", "train_count": 0, "eval_count": 0,
     "eval_coverage_pct": 0.0, "skipped": false, "skip_reason": null,
     "metrics": {}, "baselines": {}, "warnings": []}
  ],
  "pooled": {},
  "guard_results": {},
  "conclusion": "inconclusive | directional | rejected",
  "limitations": ["..."]
}
```

`conclusion` is derived by a predeclared rule, not by post-hoc judgement. Rule: `inconclusive` whenever any fold is skipped, fewer than three valid folds exist, fewer than 10 effective blocks, or the pooled confidence interval includes the baseline.

## 11. Determinism and CI

- Inputs are local files or fixtures; no live network calls during evaluation.
- Bootstrap seed is fixed and recorded.
- Output ordering is stable; the command is rerunnable and must reproduce byte-identical reports for identical inputs.
- A small synthetic fixture exercises the full pipeline in CI, including the §4.5 reconstruction invariant and the missing-label coverage stats.

## 12. Review decisions (settled)

The following are no longer open questions; implementation must follow them exactly:

1. Leakage: target-observation-date purge only; no extra embargo.
2. Folds: 365-day eval, expanding training, 80% coverage gate, <3 valid folds → inconclusive.
3. BFS is an unverified continuous exploratory score, not a probability.
4. Metrics: continuous score + fixed predeclared buckets + MFE/MAE; no state events.
5. Baselines: unconditional, ATH drawdown, 200-MA relative, BFS; buy-and-hold reference only.
6. Bootstrap: fixed seed, 2000 resamples, block ≥ horizon; <10 blocks → weak/exploratory.
7. Reconstruction stratum separate from published records.
8. Incomplete labels retained in stats; metrics use only observed labels.
