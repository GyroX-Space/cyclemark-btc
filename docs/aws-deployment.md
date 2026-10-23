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
    python scripts/run_daily.py
    git status --short

Review the generated data before enabling automatic pushes. This initial pipeline intentionally withholds BFS, BOS, and a composite state until the full model is implemented and validated.

## Schedule the daily job

Example: run at 02:20 UTC daily. Confirm the server timezone before using cron.

    crontab -e

Add the following line, replacing the home path if necessary:

    20 2 * * * CYCLEMARK_DIR=/home/ubuntu/cyclemark-btc /home/ubuntu/cyclemark-btc/scripts/run_daily.sh >> /home/ubuntu/cyclemark-btc/daily.log 2>&1

Ensure cron can access Git credentials and Python. Rotate logs and alert on non-zero exit status or stale latest data. A systemd timer explicitly configured for UTC is another option.

## Safe operation

- Prevent overlapping runs.
- Review generated changes during the initial observation period.
- Restrict the server account and repository credential to minimum required permissions.
- Never commit credentials, prohibited raw data, or private server configuration.
- If an API fails, the job must fail without pushing a fabricated signal.
- Consider a separate bot branch and reviewed pull requests if branch protection is enabled.

## Current limitations

The first pipeline fetches public BTC spot candles and the Alternative.me Fear & Greed observation. It does not yet implement the complete on-chain and derivatives feature set, a validated BOS model, or a production market state. Those outputs remain unavailable rather than invented. Static-site hosting and the editorial calendar must be configured and verified separately.
