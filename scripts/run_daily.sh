#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${CYCLEMARK_DIR:-$HOME/simon/cyclemark-btc}"
if [[ ! -d "$PROJECT_DIR/.git" ]]; then
  echo "CycleMark project not found at $PROJECT_DIR. Set CYCLEMARK_DIR or clone the repo there." >&2
  exit 1
fi
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

# Run the daily refresh and capture its full stdout + exit code.
DAILY_OUTPUT="$(python scripts/run_daily.py 2>&1)"
DAILY_EXIT=$?
echo "$DAILY_OUTPUT"

# Build a run marker that is ALWAYS written — so every cron trigger leaves
# a trace in the repo, even when the data files don't change.
RUN_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_HOST="$(hostname)"
HEAD_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
RUN_OUTCOME="success"
[[ $DAILY_EXIT -ne 0 ]] && RUN_OUTCOME="failed"

# Try to extract date / revision / BFS from the Python output (best-effort regex).
RECORD_DATE="null"; REVISION="null"; PRICE="null"; BFS_VAL="null"; COVERAGE="null"
if [[ $DAILY_OUTPUT =~ Daily\ refresh\ (unchanged|published)\ for\ ([0-9]{4}-[0-9]{2}-[0-9]{2})\ \(revision\ ([0-9]+)\) ]]; then
  RECORD_DATE="${BASH_REMATCH[2]}"
  REVISION="${BASH_REMATCH[3]}"
fi
if [[ $DAILY_OUTPUT =~ Price:\ USD\ ([0-9,]+\.[0-9]{2}) ]]; then
  PRICE="${BASH_REMATCH[1]//,/}"
fi
if [[ $DAILY_OUTPUT =~ Provisional\ BFS:\ ([0-9]+\.[0-9]+) ]]; then
  BFS_VAL="${BASH_REMATCH[1]}"
fi
if [[ $DAILY_OUTPUT =~ \(([0-9]+\.[0-9]+)%\ configured-weight\ coverage ]]; then
  COVERAGE="${BASH_REMATCH[1]}"
fi

mkdir -p data
cat > data/last_run.json <<MARKER
{
  "run_at_utc": "${RUN_AT_UTC}",
  "host": "${RUN_HOST}",
  "repo_commit": "${HEAD_COMMIT}",
  "exit_code": ${DAILY_EXIT},
  "outcome": "${RUN_OUTCOME}",
  "record_date": ${RECORD_DATE},
  "revision": ${REVISION},
  "price_usd": ${PRICE},
  "bfs": ${BFS_VAL},
  "configured_weight_coverage_pct": ${COVERAGE}
}
MARKER

git add data/signals data/last_run.json
if [[ -d data/market ]]; then
  git add data/market
fi

# Always commit + push — the last_run.json marker guarantees a diff every run.
git config user.name "${GIT_AUTHOR_NAME:-CycleMark Daily Bot}"
git config user.email "${GIT_AUTHOR_EMAIL:-cyclemark-bot@users.noreply.github.com}"
git commit -m "data: refresh daily BTC market context" || true
git push origin main || { echo "Push failed (non-fatal); marker written locally." >&2; }

exit $DAILY_EXIT
