#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${CYCLEMARK_DIR:-$HOME/cyclemark-btc}"
cd "$PROJECT_DIR"

# Prevent overlapping cron/systemd invocations on this host.
exec 9>"${TMPDIR:-/tmp}/cyclemark-daily-${USER:-cyclemark}.lock"
if ! flock -n 9; then
  echo "Another CycleMark daily run is already active; exiting."
  exit 0
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean; refusing to overwrite local changes."
  git status --short
  exit 1
fi

git pull --rebase origin main

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -e .
python scripts/run_daily.py

git add data/signals/
if git diff --cached --quiet; then
  echo "No signal archive changes to publish."
  exit 0
fi

git config user.name "${GIT_AUTHOR_NAME:-CycleMark Daily Bot}"
git config user.email "${GIT_AUTHOR_EMAIL:-cyclemark-bot@users.noreply.github.com}"
git commit -m "data: refresh daily BTC market context"
git push origin main
