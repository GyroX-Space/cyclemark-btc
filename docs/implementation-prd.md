# CycleMark Engineering PRD and Delivery Acceptance

**Document status:** Implementation and acceptance specification, version 1.0  
**Audience:** CycleMark maintainers and any engineer assisting with infrastructure or data engineering  
**Product language:** All public repository content, code comments intended for public readers, dashboard text, and documentation must be English.

## 1. Product objective

Deliver an auditable daily Bitcoin cycle-research system that ingests public market observations, computes CycleMark's own features and scores, preserves versioned daily records, exposes a public English dashboard, and can run unattended on an AWS Linux host.

CycleMark is a research product. It must not claim predictive validity until the defined validation protocol has passed and its results are reproducible.

## 2. Non-negotiable data policy

1. Core BFS, BOS, and market-state calculations must use public raw market observations wherever practical.
2. Exchange OHLCV, public trades, exchange-published funding/open-interest/liquidation observations, and reproducible blockchain observations can be core inputs when timestamped and quality-checked.
3. Third-party calculated indicators (including Fear & Greed, provider-computed MVRV, realized price, Mayer Multiple, and other composite scores) are auxiliary display context by default. They must not affect BFS, BOS, or state assignment.
4. Missing raw data must be marked unavailable. Do not substitute a third-party calculated indicator to conceal a missing feature.
5. Any exception to the policy requires an explicit documented rationale, model-version change, and independent validation.
6. Every daily output must expose data provenance, observation and retrieval timestamps, missing features, model version, and validation status.
7. Public-facing strings and documentation must remain English-only.

## 3. Current baseline and limitations

The repository currently includes a public Binance daily-candle adapter, optional Alternative.me Fear & Greed context, provisional price-derived BFS scaffolding, JSON archive utilities, a static calendar dashboard, AWS daily-run scripts, basic walk-forward utilities, tests, and GitHub Actions workflow definitions.

The current BFS uses only cycle-position and trend/price-structure features and reports 40% configured-weight coverage. It is not calibrated or validated. BOS and official state assignment are withheld. The existing historical backfill is research data, not a reconstruction of originally published point-in-time decisions.

Do not present the current baseline as a completed predictive product.

## 4. Work packages

### WP1 — Data contracts and ingestion reliability

- Define a normalized raw-observation contract with asset, venue, interval, observation time, availability time, retrieval time, unit, source, revision status, and quality flags.
- Validate OHLCV chronology, duplicate timestamps, gaps, impossible high/low relationships, non-positive prices, and incomplete candles.
- Add bounded retries, rate-limit handling, clear errors, and source-health metadata.
- Store raw observations separately from features and scores. Preserve source snapshots when terms permit.
- Add source-adapter tests using deterministic fixtures; routine tests must not depend on live APIs.

**Acceptance criteria**
- Malformed or stale data cannot silently produce a published score.
- Each score's source observations can be traced to a source and timestamp.
- Missing or failed optional auxiliary feeds do not block core price-only calculations.
- Required core feed failure results in a non-zero job exit and no falsely fresh record.

### WP2 — Core raw-market feature set

Implement features from raw observations, not vendor-computed indicators:

- **Price structure:** drawdown from observed ATH, price versus rolling averages, momentum, realized volatility, drawdown duration, stabilization and volume anomalies.
- **Derivatives structure:** funding, open interest, basis, liquidations, and cross-venue aggregates from public exchange endpoints where available. Record venue coverage and avoid treating a single venue as the whole market.
- **On-chain structure:** define reproducible features from blockchain observations and a documented node/indexing method. If exact point-in-time reconstruction or reliable raw sourcing is unavailable, keep the dimension unavailable rather than substituting a vendor metric.
- **Valuation/cost basis:** only implement a metric such as realized value or MVRV if CycleMark can derive the necessary components from its documented raw observations and reproduce the calculation independently.
- **Capitulation:** derive from price, trades, volume, and reproducible on-chain spending/realized-flow observations. Third-party sentiment indices remain display-only.

**Acceptance criteria**
- Every feature has a written formula, direction, unit, lookback window, missing-data policy, and tests.
- Rolling normalizations use only observations available at the score timestamp.
- Feature coverage is explicit; scores are withheld when configured minimum coverage is not met.
- The model does not silently use third-party derived metrics.

### WP3 — BFS, BOS, and state governance

- Version feature transformations, weights, thresholds, and data-source definitions.
- Keep BFS (bottom-formation evidence) distinct from BOS (forward return/risk assessment).
- Do not call either score a probability unless a separate model has been calibrated as a probability model.
- Keep the four proposed states (Risk, Watch, Forming, Opportunity) disabled until the state rules pass the agreed validation gates.
- Add explanations that identify which inputs materially changed the score or state.

**Acceptance criteria**
- Scores are deterministic for fixed versioned inputs and code.
- Missing inputs are never coerced to zero.
- State output remains unavailable if required scores or coverage are missing.
- Changes to model rules create a new version and preserve prior published records.

### WP4 — Historical evaluation

- Build forward labels for 365-day and 548-day returns, threshold outcomes, and adverse excursion measures.
- Use chronological walk-forward evaluation and purge/embargo overlapping labels appropriately.
- Compare against buy-and-hold, drawdown-only, and trend-only baselines.
- Include realistic fees, slippage, delayed execution, and clearly stated entry/exit assumptions.
- Report return distributions, downside risk, adverse excursions, false positives/negatives, timing lead, state stability, uncertainty, calibration where applicable, and results by cycle.
- Treat daily overlapping labels as dependent observations; quantify the limited number of independent cycles.

**Acceptance criteria**
- A clean run reproduces the published report from pinned data and model versions.
- No future data leaks into features, normalization, thresholds, or state transitions.
- No predictive claims are published before out-of-sample evaluation and uncertainty review.
- If evidence is weak or independent cycle count is inadequate, the result explicitly says so.

### WP5 — Dashboard and immutable history

- Publish the latest market context, BFS status/coverage, and auxiliary reference indicators separately.
- Display a daily calendar. Selecting a date must show the exact stored record, its provenance, missing dimensions, model version, and whether it was an original publication or research backfill.
- Never label backfilled research rows as original historical decisions.
- Show BOS and official states as unavailable until validation gates pass.
- Preserve historical records or append immutable versions; do not silently rewrite a prior published decision after source revisions.

**Acceptance criteria**
- Dashboard works on desktop and mobile, with accessible text labels and a clear timezone.
- Empty, missing, stale, and malformed data states are handled visibly.
- All user-facing text remains English.
- Static-site deployment succeeds from a clean GitHub Actions run.

### WP6 — AWS operations and security

- Use a dedicated Linux user, isolated virtual environment, pinned/reproducible dependencies, and least-privilege GitHub push credentials.
- Store secrets in the host's secret store or environment configuration, never in repository files or logs.
- Add lock protection against overlapping runs, structured logs, clear exit codes, and alerting or a documented operator check for failures.
- Make daily writes atomic; do not publish incomplete records.
- Document timezone, schedule, recovery, backfill, rollback, and credential rotation.
- Verify actual AWS execution with a dry run and a successful live daily run.

**Acceptance criteria**
- A clean host can be provisioned from the runbook.
- One manual run and at least two scheduled runs complete successfully and push only intended data changes.
- Failed jobs leave a clear error and do not mark stale data as current.
- No credentials are present in git history, generated artifacts, or logs.

## 5. Release gates

Do not declare the product production-ready until all gates pass:

1. **Data gate:** required core feeds are stable, documented, timestamped, and tested.
2. **Calculation gate:** feature formulas and score outputs are deterministic and fully tested.
3. **Leakage gate:** chronological validation demonstrates no look-ahead or label leakage.
4. **Evidence gate:** out-of-sample results are reviewed, uncertainty and failure cases disclosed, and claims are proportionate to evidence.
5. **UI gate:** dashboard accurately distinguishes validated results, provisional scores, auxiliary indicators, and unavailable fields.
6. **Operations gate:** AWS schedule, GitHub publishing, error handling, and recovery are verified in the actual environment.
7. **Security gate:** least privilege and secret-handling checks pass.

## 6. Work split

The coding assistant can implement repository code, tests, documentation, dashboard changes, and workflow configuration through repository access. Human operator involvement is required for actions that depend on private AWS access, private credentials, paid-data entitlements, or decisions about acceptable operational risk.

An engineer should be assigned only to unresolved environment-dependent tasks or specialized raw blockchain indexing if the chosen deployment requires a dedicated Bitcoin node/indexer. They should not replace the raw-data-first policy with vendor-derived metrics merely to shorten implementation time.

## 7. Required handoff evidence

For each release candidate, retain:
- Commit SHA and model version.
- Test and CI result links.
- Source-health report and data coverage.
- Backtest command, configuration, data version, and generated report.
- AWS run logs with secrets redacted.
- Dashboard URL and deployment run.
- Known limitations and explicit go/no-go decision.
