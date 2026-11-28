# CMCI — Crypto Market Cycle Intelligence

CMCI is the main research program of this repository. It studies how global macro-financial conditions, Crypto's endogenous supply and demand, capital allocation and transmission, and observable market behaviour interact across market cycles.

CMCI is a research and environment-awareness system, **not** a trading strategy. It never emits buy, sell, open, or close instructions, and no single CMCI state label may be used as the sole basis for a trading decision.

## Status

**Phase 1 — data foundation.** Frozen scope, non-frozen conclusions.

Phase 1 delivers exactly three tasks:

1. L1–L5 indicator base table and data governance (indicator dictionary, source registry, raw/normalized storage, `available_time` replay, independent look-ahead audit).
2. Global-finance / Crypto relationship research (common driver, capital competition, capital transmission — each with a reproducible test and a verdict of holds / does not hold / insufficient evidence).
3. BTC halving-cycle historical base table, including an assessment of whether the effective independent sample can be expanded.

L6 (cycle-state model), cycle-transition detection, CCE synthesis, and live inference are explicitly **out of scope** in Phase 1.

## Documents

- [CMCI project charter v0.1](docs/cmci-project-charter-v0.1.md) — positioning, L1–L6 architecture, L5 three-way partition rules, hard anti-circularity rules, Phase 1 acceptance.
- [CMCI-DATA-01 requirements v0.1](docs/cmci-data-01-requirements.md) — research data infrastructure requirements (P0).
- [CMCI technical design v0.1](docs/cmci-technical-design-v0.1.md) — storage, time governance, versioning, replay, audit design.
- [CycleMark BTC sub-product brief](docs/cyclemark-product.md).

## Repository layout

| Path | Role |
|---|---|
| `src/cmci/` | CMCI main line — research data infrastructure (active development) |
| `src/cyclemark/` | CycleMark BTC — existing sub-product, code and behaviour unchanged |
| `scripts/` | Operational entry points for both products |
| `web/`, `data/` | CycleMark public dashboard and published market context |
| `docs/` | CMCI specifications and CycleMark documentation |

## Phase 1 delivery batches

| Batch | Scope | Status |
|---|---|---|
| P0-1 | Data model, indicator dictionary, data-source registry, indicator↔source mapping, time-field and L5 partition fields | done |
| P0-2 | Raw + normalized data, CSV/Excel/JSON import, API ingestion framework, append-only revisions, basic quality checks | done |
| P0-3 | Research datasets and L5 partitions, conflict checks, embargo, validation-zone locking | done |
| P0-4 | Historical replay by `available_time`, snapshots, replay reports, export | done |
| P0-5 | Quality reporting, look-ahead audit, random sampling, audit reports, operation logs | done |

## Development

Python 3.11 or later is required.

    python -m pip install -e ".[dev]"
    pytest
    python scripts/cmci_bootstrap.py

`scripts/cmci_bootstrap.py` creates the local CMCI database at `data/cmci/cmci.db` and registers a representative L1–L5 starting dictionary. Historical replay of a registered dataset:

    python scripts/cmci_replay.py --dataset <dataset_code> --as-of 2024-03-10

Only observations whose `available_time` was known at the as-of instant are returned; each replay writes a CSV snapshot and a hashed `replay_jobs` record.

Quality and look-ahead audits:

    python scripts/cmci_audit.py --type quality
    python scripts/cmci_audit.py --type lookahead --sample 500 --seed 7

Audit findings are persisted in `audit_jobs` / `audit_results`, with a JSON report per run.

CycleMark BTC continues to run unchanged:

    python scripts/backfill_history.py
    python scripts/run_daily.py

## Governance principles

1. No look-ahead: a historical decision may only use data whose `available_time` was already known at that time.
2. Append-only history: raw data is never overwritten in place; corrections are new versions.
3. Purpose isolation: L5 `training` / `identification` / `validation` partitions are registered up front and cannot be reused silently.
4. L6 never feeds back into L1–L4 driver identification.
5. Missing data is never silently filled or treated as zero.
6. Every published state must be reproducible from versioned inputs and code.
7. Never commit credentials or redistribute data in violation of provider terms.

## Disclaimer

CMCI and CycleMark are educational and research projects, not investment advice, a recommendation to buy or sell, or a promise of future performance. Bitcoin is volatile and may result in substantial or total loss.

## License

Licensed under the MIT License. See [LICENSE](LICENSE).