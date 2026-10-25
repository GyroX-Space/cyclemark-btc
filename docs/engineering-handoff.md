# Engineering Handoff and Work Queue

**Audience:** Engineering contributors working with the CycleMark research and architecture owner through GitHub  
**Status:** Living handoff document; update it when scope, acceptance criteria, or deployment status changes  
**Language policy:** All repository code, UI, issues, pull requests, documentation, logs committed to the repository, and user-facing product text must be English. Chat outside GitHub may use other languages.

## 1. Working agreement

- GitHub is the source of truth for requirements, implementation discussion, review, decisions, and acceptance.
- Every engineering task must have an issue with scope, acceptance criteria, test expectations, and dependencies.
- Use a feature branch and pull request for changes. Do not push directly to `main`.
- Link each PR to its issue using `Closes #N` when it fully resolves that issue.
- Do not silently change financial definitions. Any change to feature meaning, thresholds, horizon, state transition, data source, or score weighting requires a documented rationale and review.
- Keep live features, research labels, historical reconstruction, and third-party auxiliary context in separate fields and code paths.
- Never put API keys, AWS credentials, private keys, account identifiers, or other secrets into GitHub issues, commits, logs, fixtures, or chat. Use the approved secret manager or the deployment operator's local environment.
- Do not claim that a model predicts bottoms, that BOS is validated, or that a state is actionable until the agreed evaluation gates are met.

## 2. Current project status

CycleMark is an early-stage BTC cycle research system. The current BFS implementation is provisional and uses price-derived features only. Its reported 40% coverage means only two of the five intended conceptual dimensions are currently represented; the available weights are renormalized for the provisional score. This score is not a calibrated probability and has not demonstrated predictive validity.

BOS and formal market-state assignment remain withheld pending feature completion and out-of-sample evaluation. Fear & Greed is auxiliary display context only and must not enter core BFS/BOS/state calculations.

### Current review items

- [PR #1 — Add leakage-aware forward outcome labels](https://github.com/GyroX-Space/cyclemark-btc/pull/1): research-only labels for 365/548 calendar-day horizons, adverse/favorable excursions, missing-target preservation, and leakage documentation.
- [PR #2 — Add Binance perpetual funding-rate data adapter](https://github.com/GyroX-Space/cyclemark-btc/pull/2): raw funding-rate adapter, validation, daily archive integration, provenance, and tests. Funding remains excluded from core scores.

These PRs are not considered deployed until merged and verified in the target runtime. CI passing does not prove AWS scheduling, source availability, data integrity over time, or predictive value.

## 3. Priority order

### P0 — Review and stabilize current data changes

**Owner:** Engineering contributor  
**Architecture/research reviewer:** CycleMark architecture owner

Tasks:
1. Review PR #1 and PR #2 for correctness, test coverage, API pagination assumptions, and archive behavior.
2. Verify that all files are English-only and no secrets are present.
3. Confirm GitHub Actions tests pass on the final PR commits.
4. Merge only after review; record merge SHA in the relevant issue or this document.
5. On a clean Linux environment, install from the repository and run unit tests before touching production.
6. Confirm the daily runner still succeeds when the optional Fear & Greed or funding endpoint is unavailable.

Acceptance:
- CI green on the final commit.
- No credentials or generated local files accidentally committed.
- A missing optional feed does not stop raw-price BFS generation.
- The funding archive is committed only when it exists and is valid.
- Any observed defect has a regression test.

### P1 — Harden the daily data pipeline

**Owner:** Engineering contributor  
**Architecture/research reviewer:** CycleMark architecture owner

Tasks:
1. Add a data-quality report for each run: expected versus observed candles, duplicate timestamps, gaps, stale responses, and source errors.
2. Validate that the latest daily candle is finalized and timestamps are normalized consistently to UTC.
3. Make archive writes atomic (write temporary file, fsync if appropriate, then replace) to avoid partial JSON on interruption.
4. Define explicit retry/backoff and timeout behavior for transient API failures; avoid unbounded retries.
5. Add an idempotency test: rerunning a date must not duplicate the same daily signal record or corrupt prior history.
6. Add tests for funding endpoint empty pages, repeated pages, malformed records, and maximum-page safety.
7. Document what happens if a daily job fails and how an operator can safely rerun it.

Acceptance:
- A single source outage is visible in logs and metadata.
- Core price-derived output remains available when only optional sources fail.
- Invalid core price data fails closed; it must not silently emit a plausible-looking score.
- Re-running the same date is deterministic and does not duplicate history.
- Unit tests cover failure and recovery paths.

### P2 — Point-in-time raw derivatives dataset

**Owner:** Engineering contributor  
**Architecture/research reviewer:** CycleMark architecture owner

Tasks:
1. Preserve exchange event timestamp separately from retrieval timestamp.
2. Preserve source/venue, instrument, endpoint, and schema version.
3. Store funding rates as raw observations; do not infer sentiment or add weights in this task.
4. Add a reproducible historical backfill command with explicit start/end timestamps, pagination tests, rate-limit handling, and resume behavior.
5. Make clear that an exchange's historical endpoint does not prove the data was available to CycleMark at the historical signal time.
6. Do not add open interest, liquidation, or basis sources until the same provenance and validation requirements are specified.

Acceptance:
- Backfill can resume safely without duplicating identical observations.
- API pagination is bounded and tested.
- Changed observations at the same event timestamp are preserved as revisions or documented source updates, not silently overwritten.
- Every row has event time, retrieval time, source, instrument, and normalized numeric values.
- Dataset limitations are documented, including venue coverage and historical point-in-time caveats.
- No funding-derived feature enters BFS/BOS/state without a separate reviewed research change.

### P3 — Research evaluation and BOS specification

**Owner:** Architecture/research owner defines methodology; engineering implements reviewed protocol  
**Do not independently invent financial rules in implementation.**

Tasks:
1. Keep forward labels separate from live feature generation.
2. Add chronological walk-forward evaluation with purging/embargo based on the longest label horizon.
3. Compare against simple predeclared baselines, including buy-and-hold and transparent price-only rules.
4. Include forward returns, adverse/favorable excursion, downside risk, event precision/recall where applicable, and uncertainty intervals.
5. Account for overlapping daily samples; do not treat every day as an independent market-cycle event.
6. Record data availability, survivorship/revision caveats, thresholds, score version, and all evaluation settings.
7. Produce a reproducible report before proposing BOS thresholds or market-state transitions.

Acceptance:
- No random train/test split for time-series claims.
- No future-derived field leaks into features or threshold selection.
- Baselines and metrics are fixed before looking at final holdout results.
- Results can be regenerated from a documented command and versioned inputs.
- If evidence is insufficient, the result says "inconclusive"; it does not force a successful model.
- BOS/state remains unpublished or explicitly marked experimental until review approves evidence.

### P4 — AWS deployment verification (requires environment access)

**Owner:** User's deployment engineer  
**Architecture/research reviewer:** CycleMark architecture owner via GitHub

Tasks:
1. Follow [AWS deployment guide](aws-deployment.md) on a clean host or staging environment.
2. Confirm Python version, repository path, permissions, `flock`, timezone, cron/service configuration, and outbound HTTPS access.
3. Run the backfill and daily job manually first; inspect JSON output and git diff before enabling a schedule.
4. Verify push permissions use the least-privilege method approved by the repository owner.
5. Enable scheduled execution only after a successful manual run.
6. Add an alerting method for repeated failures, stale data, and failed pushes.
7. Verify the GitHub Pages site only after the workflow and repository Pages settings are confirmed.

Acceptance:
- Evidence in the issue: sanitized command output, run timestamp (UTC), latest signal date, archive row counts, commit SHA, and Actions status.
- No secret values in screenshots, terminal output, issues, or commits.
- A simulated optional-source outage does not prevent price-only output.
- A simulated invalid core candle prevents publication of a new score.
- The operator can explain how to stop, rerun, and recover the daily job.

**Human access required:** The engineer must run commands inside the user's AWS environment. Do not share AWS keys or private tokens with the architecture owner. Share only sanitized logs and outcomes through GitHub.

## 4. Data and financial governance

- Raw observations are not automatically features; features are not automatically useful predictors.
- Every feature must specify formula, units, directionality hypothesis, timestamp availability, missing-data policy, outlier handling, and version.
- Any normalization must be fitted using only information available at the signal timestamp.
- Historical backfills must not be presented as the original live signal history unless point-in-time data and the exact historical code/configuration are available.
- Score coverage, missing dimensions, and data-quality warnings must be displayed alongside a score.
- A score is not a probability unless calibrated and validated as one.
- Keep auxiliary third-party indicators out of core scoring unless a separate decision explicitly changes that policy.
- Never change the methodology solely because it improves a retrospective chart.

## 5. PR checklist

Every implementation PR should include:
- [ ] Linked issue and scope summary.
- [ ] English-only public text and UI.
- [ ] Tests for normal, invalid, missing, and failure inputs as relevant.
- [ ] No secrets or private user data.
- [ ] Source provenance and timestamp semantics for data changes.
- [ ] Financial definition documented for feature/scoring changes.
- [ ] Leakage check for all historical research code.
- [ ] Limitations stated honestly.
- [ ] CI passed on the final commit.
- [ ] Deployment-only claims separated from locally or CI-verified claims.

## 6. Communication protocol

Use GitHub Issues for tasks, blockers, questions, and acceptance evidence. Use PR review comments for line-specific implementation questions. When a decision affects financial meaning, record it in a linked design/methodology document before merging.

When blocked, the engineer should comment on the issue with:
1. What was attempted.
2. Sanitized error or evidence.
3. The smallest decision or access needed.
4. Options and recommendation.
5. Whether the block affects data integrity, score publication, or only optional context.

The architecture/research owner will respond in the issue or PR thread so the decision remains discoverable and auditable.

## 7. Do not do yet

- Do not add funding rates, Fear & Greed, or any third-party composite index to core scoring without a reviewed feature specification and evaluation.
- Do not publish BOS as validated.
- Do not assign market states such as Opportunity based only on hand-picked thresholds or retrospective visual fit.
- Do not enable unattended production scheduling before the manual-run acceptance checklist passes.
- Do not claim the project is production-ready solely because CI passes.
