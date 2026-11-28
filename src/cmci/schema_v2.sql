-- CMCI schema, migration 2 (P0-2): raw, normalized, ingestion, quality
-- Append-only tables reject UPDATE/DELETE through triggers at the bottom.

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id              TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL REFERENCES data_sources(source_id) ON DELETE RESTRICT,
    indicator_id        TEXT NOT NULL REFERENCES indicators(indicator_id) ON DELETE RESTRICT,
    start_time_utc      TEXT,
    end_time_utc        TEXT,
    execution_time_utc  TEXT NOT NULL,
    finished_at_utc     TEXT,
    records_received    INTEGER NOT NULL DEFAULT 0,
    records_inserted    INTEGER NOT NULL DEFAULT 0,
    records_updated     INTEGER NOT NULL DEFAULT 0,
    records_rejected    INTEGER NOT NULL DEFAULT 0,
    job_status          TEXT NOT NULL
        CHECK (job_status IN ('running', 'succeeded', 'failed', 'partial')),
    error_log           TEXT,
    actor               TEXT NOT NULL,
    created_at_utc      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_records (
    raw_record_id     TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL REFERENCES data_sources(source_id) ON DELETE RESTRICT,
    indicator_id      TEXT NOT NULL REFERENCES indicators(indicator_id) ON DELETE RESTRICT,
    job_id            TEXT NOT NULL REFERENCES ingestion_jobs(job_id) ON DELETE RESTRICT,
    batch_id          TEXT NOT NULL,
    received_at_utc   TEXT NOT NULL,
    source_release_time_utc TEXT,
    payload           TEXT,
    payload_path      TEXT,
    payload_format    TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    ingestion_status  TEXT NOT NULL CHECK (ingestion_status IN ('stored', 'rejected')),
    error_message     TEXT,
    created_at_utc    TEXT NOT NULL,
    CHECK (payload IS NOT NULL OR payload_path IS NOT NULL),
    UNIQUE (source_id, indicator_id, content_hash)
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id          TEXT PRIMARY KEY,
    indicator_id            TEXT NOT NULL REFERENCES indicators(indicator_id) ON DELETE RESTRICT,
    source_id               TEXT NOT NULL REFERENCES data_sources(source_id) ON DELETE RESTRICT,
    raw_record_id           TEXT REFERENCES raw_records(raw_record_id) ON DELETE RESTRICT,
    observation_period_start TEXT NOT NULL,
    observation_period_end   TEXT NOT NULL,
    release_time_utc        TEXT,
    available_time_utc      TEXT NOT NULL,
    vintage_time_utc        TEXT NOT NULL,
    value                   REAL,
    value_text              TEXT,
    unit                    TEXT NOT NULL,
    timezone                TEXT NOT NULL,
    quality_status          TEXT NOT NULL
        CHECK (quality_status IN ('normal', 'warning', 'degraded', 'unavailable', 'unknown')),
    time_precision_status   TEXT NOT NULL
        CHECK (time_precision_status IN ('exact', 'date_only', 'partial', 'unknown')),
    revision_id             TEXT NOT NULL,
    supersedes_observation_id TEXT REFERENCES observations(observation_id) ON DELETE RESTRICT,
    created_at_utc          TEXT NOT NULL,
    CHECK (observation_period_start <= observation_period_end),
    CHECK (release_time_utc IS NULL OR available_time_utc >= release_time_utc),
    CHECK (value IS NOT NULL OR value_text IS NOT NULL),
    UNIQUE (
        indicator_id, source_id,
        observation_period_start, observation_period_end, vintage_time_utc
    )
);

CREATE TABLE IF NOT EXISTS observation_revisions (
    revision_id            TEXT PRIMARY KEY,
    indicator_id           TEXT NOT NULL REFERENCES indicators(indicator_id) ON DELETE RESTRICT,
    observation_id         TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE RESTRICT,
    previous_observation_id TEXT REFERENCES observations(observation_id) ON DELETE RESTRICT,
    revision_reason        TEXT NOT NULL,
    revised_by             TEXT NOT NULL,
    created_at_utc         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_checks (
    check_id       TEXT PRIMARY KEY,
    observation_id TEXT,
    job_id         TEXT,
    indicator_id   TEXT NOT NULL,
    check_type     TEXT NOT NULL,
    status         TEXT NOT NULL
        CHECK (status IN ('normal', 'warning', 'degraded', 'unavailable', 'unknown')),
    message        TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_indicator
    ON ingestion_jobs (indicator_id, execution_time_utc);

CREATE INDEX IF NOT EXISTS ix_raw_records_job
    ON raw_records (job_id);

CREATE INDEX IF NOT EXISTS ix_observations_indicator_available
    ON observations (indicator_id, available_time_utc);

CREATE INDEX IF NOT EXISTS ix_observations_indicator_period
    ON observations (indicator_id, observation_period_start);

CREATE INDEX IF NOT EXISTS ix_observations_period_vintage
    ON observations (indicator_id, observation_period_start, vintage_time_utc);

CREATE INDEX IF NOT EXISTS ix_quality_checks_indicator
    ON data_quality_checks (indicator_id, created_at_utc);

CREATE TRIGGER IF NOT EXISTS trg_raw_records_no_update
BEFORE UPDATE ON raw_records
BEGIN
    SELECT RAISE(ABORT, 'raw_records is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_raw_records_no_delete
BEFORE DELETE ON raw_records
BEGIN
    SELECT RAISE(ABORT, 'raw_records is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_observations_no_update
BEFORE UPDATE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations is append-only; append a new vintage');
END;

CREATE TRIGGER IF NOT EXISTS trg_observations_no_delete
BEFORE DELETE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations is append-only; append a new vintage');
END;

CREATE TRIGGER IF NOT EXISTS trg_observation_revisions_no_update
BEFORE UPDATE ON observation_revisions
BEGIN
    SELECT RAISE(ABORT, 'observation_revisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_observation_revisions_no_delete
BEFORE DELETE ON observation_revisions
BEGIN
    SELECT RAISE(ABORT, 'observation_revisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_quality_checks_no_update
BEFORE UPDATE ON data_quality_checks
BEGIN
    SELECT RAISE(ABORT, 'data_quality_checks is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_quality_checks_no_delete
BEFORE DELETE ON data_quality_checks
BEGIN
    SELECT RAISE(ABORT, 'data_quality_checks is append-only');
END;