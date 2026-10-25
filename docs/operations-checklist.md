# Operations Readiness Checklist

Use this checklist before enabling unattended daily publication.

## Data pipeline

- [ ] Run the daily pipeline manually on the target AWS instance.
- [ ] Confirm the latest finalized candle is used, not an open daily candle.
- [ ] Verify source timestamps, timezone, data gaps, and API failure behavior.
- [ ] Confirm a source outage fails safely and does not fabricate a record.
- [ ] Verify the daily record contains a `data_quality` block and that core price fatal issues prevent publication.
- [ ] Confirm an optional-source failure (Fear & Greed, funding) is recorded as `unavailable` without blocking the price-only record.
- [ ] Review the first generated JSON record and commit diff.
- [ ] Confirm history contains one canonical record per date.

## Rerun and recovery semantics

- [ ] Rerunning a date with identical observations returns `unchanged` and must not rewrite the date file.
- [ ] Rerunning with materially different observations increments `revision` and archives the prior version under `data/signals/revisions/`.
- [ ] Confirm `latest.json` is written only after `history.json` is consistent.
- [ ] Confirm an interrupted run leaves the previous canonical record readable and does not half-publish a new one.
- [ ] Confirm a corrupted local funding archive is logged as `funding_archive.status=failed` without blocking the daily record.
- [ ] To force a rebuild, delete only the affected date file and rerun; do not delete history or revisions during normal recovery.

## GitHub publishing

- [ ] Use a dedicated, least-privilege GitHub credential.
- [ ] Confirm pushes work without credentials in command history or logs.
- [ ] Enable branch protection or a reviewed bot branch if required.
- [ ] Confirm test workflow passes on the default branch.
- [ ] Confirm Pages is enabled and deployment workflow succeeds.
- [ ] Confirm the published site can load both latest and history JSON.

## Monitoring

- [ ] Configure log rotation.
- [ ] Alert on non-zero job exit status.
- [ ] Alert when latest data becomes stale.
- [ ] Prevent overlapping scheduled runs.
- [ ] Document credential rotation and recovery steps.
- [ ] Keep a rollback procedure for bad code or data releases.

## Model readiness

- [ ] Implement and document all production features.
- [ ] Establish point-in-time availability and revision rules.
- [ ] Complete chronological walk-forward validation.
- [ ] Compare with predeclared baselines and include costs.
- [ ] Report uncertainty and independent-cycle sample size.
- [ ] Calibrate any probability outputs before using probability language.
- [ ] Obtain review before changing the dashboard from research-only to production states.
