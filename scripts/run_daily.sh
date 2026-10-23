#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="${CYCLEMARK_DIR:-$HOME/cyclemark-btc}"
cd "$PROJECT_DIR"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree is dirty; refusing to overwrite local changes."
  exit 1
fi
git pull --rebase origin main
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python scripts/run_daily.py
git add data/signals/
if git diff --cached --quiet; then
  echo 'No signal archive changes to publish.'
  exit 0
fi
git config user.name "${GIT_AUTHOR_NAME:-CycleMark Daily Bot}"
git config user.email "${GIT_AUTHOR_EMAIL:-cyclemark-bot@users.noreply.github.com}"
git commit -m "data: refresh daily BTC market context"
git push origin main
