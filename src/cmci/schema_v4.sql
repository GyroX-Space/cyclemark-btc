-- CMCI schema, migration 4 (P0-4): historical replay
-- A replay job records the exact as-of time, dataset version, parameters, and
-- a deterministic result hash so the same inputs can be reproduced later.

CREATE TABLE IF NOT EXISTS replay_jobs (
    replay_job_id      TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id) ON DELETE RESTRICT,
    as_of_utc          TEXT NOT NULL,
    replay_result_hash TEXT NOT NULL,
    row_count          INTEGER NOT NULL CHECK (row_count >= 0),
    snapshot_path      TEXT,
    parameters_json    TEXT NOT NULL,
    report_json        TEXT NOT NULL,
    created_by         TEXT NOT NULL,
    created_at_utc     TEXT NOT NULL,
    CHECK (length(replay_result_hash) = 64)
);

CREATE INDEX IF NOT EXISTS ix_replay_jobs_version_asof
    ON replay_jobs (dataset_version_id, as_of_utc);

CREATE INDEX IF NOT EXISTS ix_observations_available_vintage
    ON observations (available_time_utc, vintage_time_utc);

CREATE TRIGGER IF NOT EXISTS trg_replay_jobs_no_update
BEFORE UPDATE ON replay_jobs
BEGIN
    SELECT RAISE(ABORT, 'replay_jobs is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_replay_jobs_no_delete
BEFORE DELETE ON replay_jobs
BEGIN
    SELECT RAISE(ABORT, 'replay_jobs is append-only');
END;