# AWS Linux Daily Deployment

This guide runs the CycleMark refresh once daily on an AWS Linux host and pushes generated public data to GitHub. It does not publish to X.

## Prerequisites

- An AWS Linux instance with Python 3.11+, Git, and outbound HTTPS access.
- Repository write access.
- A dedicated deployment identity. Prefer a GitHub fine-grained token limited to this repository and Contents read/write, or a dedicated SSH deploy key with write access.
- A credential rotation and backup plan.

Never place credentials in source files, shell scripts, command-line arguments, committed environment files, or logs.

## Clone the repository

Run as a dedicated, unprivileged Linux user:

    git clone https://github.com/GyroX-Space/cyclemark-btc.git "$HOME/cyclemark-btc"
    cd "$HOME/cyclemark-btc"

Configure a secure credential store or an SSH deploy key. Do not embed a token in the remote URL.

## Manual test

    python3 --version
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"
    pytest
    python scripts/backfill_history.py
    python scripts/run_daily.py
    git status --short

Run the historical backfill once before the first daily run if you want a calendar of provisional research records. Backfilled records are not historical published decisions and are not point-in-time validated. Review the generated data before enabling automatic pushes. The current pipeline publishes a provisional price-only BFS based on 40% of configured dimension weight. Third-party Fear & Greed data is auxiliary display context and does not contribute to the score. It intentionally withholds BOS and the composite state until the full model is implemented and validated.

## Schedule the daily job

Example: run at 02:20 UTC daily. Confirm the server timezone before using cron.

    crontab -e

Add the following line, replacing the home path if necessary:

    20 2 * * * CYCLEMARK_DIR=/home/ubuntu/cyclemark-btc bash /home/ubuntu/cyclemark-btc/scripts/run_daily.sh >> /home/ubuntu/cyclemark-btc/daily.log 2>&1

Ensure cron can access Git credentials and Python. Rotate logs and alert on non-zero exit status or stale latest data. A systemd timer explicitly configured for UTC is another option.

## Safe operation

- The daily script uses `flock` to prevent overlapping runs; ensure `flock` is available on the host.
- Keep the repository working tree clean before the scheduled job; the script intentionally refuses to overwrite local changes.
- Review generated changes during the initial observation period.
- Restrict the server account and repository credential to minimum required permissions.
- Never commit credentials, prohibited raw data, or private server configuration.
- If a core price API fails or core data fails quality checks, the job exits non-zero without publishing a record.
- Optional source failures (Fear & Greed, funding) do not block the price-only record; check `data_quality.optional_sources` before assuming data is complete.
- Consider a separate bot branch and reviewed pull requests if branch protection is enabled.

## Rerun and recovery

- Rerun the same date safely. Identical content is reported as `unchanged` and the date file is not rewritten.
- Materially different content increments `revision`, preserves `first_published_at_utc`, and archives the previous version under `data/signals/revisions/`.
- Writes are atomic (temporary file, flush, fsync, then replace), and `latest.json` is written after `history.json` so an interrupted run cannot expose an inconsistent newest record.
- If a run is interrupted, inspect `data/signals/` for the expected date and rerun. Do not hand-edit `history.json`, `latest.json`, or revision files; rerun the pipeline instead.
- If the local funding archive is corrupted, the daily record still publishes and the log reports `funding_archive.status=failed`. Repair the archive separately before relying on funding history.

## Current limitations

The first pipeline fetches public BTC spot candles and the Alternative.me Fear & Greed observation. It does not yet implement the complete on-chain and derivatives feature set, a validated BOS model, or a production market state. Those outputs remain unavailable rather than invented. Static-site hosting and the editorial calendar must be configured and verified separately.
