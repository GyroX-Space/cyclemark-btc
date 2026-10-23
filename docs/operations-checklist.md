# Operations Readiness Checklist

Use this checklist before enabling unattended daily publication.

## Data pipeline

- [ ] Run the daily pipeline manually on the target AWS instance.
- [ ] Confirm the latest finalized candle is used, not an open daily candle.
- [ ] Verify source timestamps, timezone, data gaps, and API failure behavior.
- [ ] Confirm a source outage fails safely and does not fabricate a record.
- [ ] Review the first generated JSON record and commit diff.
- [ ] Confirm history contains one canonical record per date.

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
