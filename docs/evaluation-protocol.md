# Walk-Forward Evaluation Protocol (Revised Design)

**Status:** Revised twice after architecture reviews on issue #6 (round 2: review items A multiplicity, B inconclusive rule, C bootstrap sampling frame). Implementation is intentionally deferred until this design is re-approved. No evaluation code or performance results are claimed here.

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
- **Skipped folds (review item B, settled):** a skipped fold is recorded with its reason but does not automatically void the whole horizon. Skipped folds are never included in pooled metric computation. The horizon is `inconclusive` only when **fewer than three valid (non-skipped) folds** remain.

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

**Locked primary statistic (review item A, settled):**

1. The primary statistic is the **Spearman rank correlation** between BFS and the forward return. No other statistic may be substituted after seeing results.
2. The **365-day and 548-day horizons are co-primary**: both are always reported, each with its own report run. Declaring one as "primary" after seeing results is prohibited; neither may be dropped because it is unfavourable. **Multiplicity wording (review item A, round 3, settled):** the two horizons are reported as **two separate per-horizon conclusions**. Because the 365-day and 548-day forward returns of the same dates are strongly overlapping, the report must **not** claim the two findings are statistically independent and must **not** claim joint significance; no familywise adjustment is applied because no joint claim is made.
3. The rank correlation is reported with a **block-bootstrap 95% confidence interval** (rules in §7). Interpretation rule, predeclared: a correlation whose 95% CI excludes zero is "directional evidence" for that horizon; a CI including zero is `inconclusive` for that horizon. Correlation alone does not establish a tradable signal.
4. No metric, horizon, or bucket boundary may be changed in response to observed results.

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

**Sampling frame (review item C, settled; round 3: per-stratum):**

1. **Bootstrap, correlation, CI, and conclusion are computed separately per stratum** (`published`, `reconstructed`). Within a stratum, the sampling frame is the union of all valid (non-skipped) evaluation-fold dates of that stratum, ordered chronologically. Because valid folds partition a continuous timeline, blocks may span adjacent valid-fold boundaries **within the same stratum**; blocks never cross strata, and strata are never pooled into one combined result or combined conclusion.
2. A bootstrap block is a contiguous run of exactly `H` consecutive *sample dates* starting at a valid block start. A start is **usable** if the block remains within the stratum and does not cross a discontinuity (a date gap > 1 calendar day, or a skipped-fold boundary). Per-fold usable starts are computed the same way within each fold's own window. With `E = 365`-day folds, an `H = 548` block can never fit inside one fold, and an `H = 365` block fits at most once; **therefore per-fold bootstrap intervals are not reported** — only per-fold point estimates. Confidence intervals come from the per-stratum pooled bootstrap only.
3. Resampling draws usable starts uniformly with replacement and concatenates blocks; when the resampled series reaches the original sample length, **the final block is truncated** so the resampled length exactly equals the original sample length.
4. The seed, block length, number of resamples, and per-stratum usable-start count are recorded in the report.

**Candidate blocks vs. effective information (review item B, round 3, settled):** `usable_block_starts` counts candidate (overlapping) block start positions; it is not a measure of independent information. The report additionally records `effective_blocks_or_cycles`, estimated deterministically as: within each contiguous run of the stratum's valid sample (bounded by gaps, skipped folds, and stratum boundaries), count the maximum number of **non-overlapping** blocks of length `H` that fit (`floor(run_length / H)`), then sum across runs. 

**Low-information rule (unified):**
- If a stratum's `usable_block_starts` < 10: set `weak_evidence: true` **and** force that stratum-horizon conclusion to `inconclusive`. Both always fire together.
- If a stratum's `effective_blocks_or_cycles` < 10: set `weak_evidence: true` at minimum, and the report must not state that predictive ability is established — the strongest allowed phrasing remains "directional evidence", explicitly labelled weak/exploratory.
- `effective_blocks_or_cycles` is a mechanical non-overlapping block count, **not** a verified count of independent cycles. Even when it reaches 10, predictive ability is not thereby established; it only removes the automatic weak-evidence flag.

- Report per-fold point estimates alongside per-stratum pooled estimates and per-stratum pooled CIs. A pooled point estimate without fold dispersion is not reportable; fold dispersion is conveyed by per-fold point estimates, not intervals.
- If fewer than three valid folds exist in a stratum, that stratum's conclusion is `inconclusive` regardless of point estimates.

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
  "report_schema_version": "1.2",
  "generated_at_utc": "...",
  "horizon_days": 365,
  "co_primary_horizons": [365, 548],
  "primary_statistic": "spearman",
  "fold": {"block_days": 365, "min_train_samples": 200, "min_eval_coverage_pct": 80, "min_valid_folds": 3},
  "purge_rule": "training target_observation_date < eval_start",
  "inputs": {"ohlcv_fingerprint": "sha256", "signal_files": ["..."], "ohlcv_source": "...", "ohlcv_time_range": ["...", "..."]},
  "columns": {"features": ["bfs"], "labels": ["forward_return_365d", "mfe_365d", "mae_365d"]},
  "bfs_buckets": [0, 20, 40, 60, 80, 100],
  "bootstrap": {"resamples": 2000, "block_days": 365, "seed": 0, "frame": "per_stratum_pooled_valid_eval_sample",
    "per_fold_intervals": "not_reported", "truncation": "final_block_truncated_to_sample_length"},
  "multiplicity": "per_horizon_conclusions_no_independence_or_joint_claim",
  "strata": ["published", "reconstructed"],
  "results_by_stratum": {
    "published": {
      "usable_block_starts": 0, "effective_blocks_or_cycles": 0, "weak_evidence": true,
      "pooled_spearman": null, "spearman_ci_95": null, "conclusion": "inconclusive",
      "folds": [
        {"index": 0, "eval_start": "...", "eval_end": "...", "train_count": 0, "eval_count": 0,
         "eval_coverage_pct": 0.0, "skipped": false, "skip_reason": null,
         "metrics": {}, "baselines": {}, "warnings": []}
      ]
    },
    "reconstructed": { "... same shape ..." }
  },
  "guard_results": {},
  "limitations": ["..."]
}
```

**No top-level `pooled` or `conclusion` field exists** (final-review boundary condition): every conclusion lives inside `results_by_stratum.<stratum>.conclusion` and `folds` live inside each stratum, so no code path can silently merge strata into one result.

`conclusion` is derived per stratum and per horizon by a predeclared rule, not by post-hoc judgement. Rule (unified): skipped folds are recorded with reasons and excluded from pooling, but do not by themselves void the horizon. A stratum-horizon conclusion is `inconclusive` when (a) fewer than three valid folds remain in that stratum, (b) that stratum's usable bootstrap block-start count is below 10 (this also sets `weak_evidence: true`; both always fire together), or (c) the stratum's pooled Spearman 95% confidence interval includes zero. `weak_evidence: true` is additionally set whenever `effective_blocks_or_cycles` < 10. No combined cross-stratum conclusion is produced.

## 11. Determinism and CI

- Inputs are local files or fixtures; no live network calls during evaluation.
- Bootstrap seed is fixed and recorded.
- **Determinism contract (final audit item, settled):** the full report JSON is NOT required to be byte-identical across runs because `generated_at_utc` (wall-clock publication timestamp) legitimately differs. The contract is:
  1. The report carries a **`deterministic_fingerprint`** which excludes `generated_at_utc`, `evaluator_version`, and inputs whose content we do not control.
  2. When two runs share identical inputs (same OHLCV, same signals, same seed, same resample count, same evaluator version), `deterministic_fingerprint` is byte-identical across runs.
  3. A unit test validates (a) `deterministic_fingerprint` equality when inputs are equal and wall clocks differ, and (b) the full JSON differs by `generated_at_utc`.
- A small synthetic fixture exercises the full pipeline in CI, including the §4.5 reconstruction invariant and the missing-label coverage stats.

## 12. Review decisions (settled)

The following are no longer open questions; implementation must follow them exactly:

1. Leakage: target-observation-date purge only; no extra embargo.
2. Folds: 365-day eval, expanding training, 80% coverage gate, <3 valid folds → inconclusive.
3. BFS is an unverified continuous exploratory score, not a probability.
4. Metrics: continuous score + fixed predeclared buckets + MFE/MAE; no state events.
5. Baselines: unconditional, ATH drawdown, 200-MA relative, BFS; buy-and-hold reference only.
6. Bootstrap: fixed seed, 2000 resamples, block ≥ horizon; low usable-start rule unified in item 11.
7. Reconstruction stratum separate from published records.
8. Incomplete labels retained in stats; metrics use only observed labels.
9. Primary statistic is Spearman rank correlation between BFS and forward return; 365-day and 548-day horizons are co-primary with separate per-horizon conclusions; no claim of statistical independence between horizons and no joint significance claim; block-bootstrap 95% CI with the predeclared interpretation rule; no post-hoc metric/horizon/bucket changes.
10. A skipped fold is recorded with its reason and excluded from pooling; the stratum-horizon is `inconclusive` only when fewer than three valid folds remain.
11. Bootstrap is computed separately per stratum (correlation, CI, conclusion); within a stratum the frame is the pooled valid evaluation sample; blocks of `H` consecutive sample dates may span valid-fold boundaries within the stratum but never cross date gaps, skipped-fold boundaries, or strata; the final resampled block is truncated to the original sample length; per-fold intervals are not reported (only point estimates).
12. `usable_block_starts` (candidate starts) and `effective_blocks_or_cycles` (sum over contiguous runs of `floor(run_length / H)`) are reported separately; usable starts < 10 sets `weak_evidence: true` and forces `inconclusive` (both always together); effective cycles < 10 sets `weak_evidence: true` at minimum and predictive ability may never be claimed established.
