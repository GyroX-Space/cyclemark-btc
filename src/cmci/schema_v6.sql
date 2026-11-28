-- CMCI schema, migration 6 (first real data batch):
-- ingested_at provenance, availability precision/method, indicator governance,
-- and per-source license terms. Append-only, version-per-row.

ALTER TABLE observations ADD COLUMN ingested_at_utc TEXT NOT NULL DEFAULT '';
ALTER TABLE observations ADD COLUMN available_time_precision TEXT NOT NULL DEFAULT 'unknown'
    CHECK (available_time_precision IN ('second', 'minute', 'date', 'unknown'));
ALTER TABLE observations ADD COLUMN available_time_method TEXT NOT NULL DEFAULT 'unknown'
    CHECK (available_time_method IN (
        'official_release', 'historical_vintage', 'conservative_lag',
        'manual_confirmed', 'unknown'
    ));

CREATE TABLE IF NOT EXISTS indicator_governance (
    governance_id        TEXT PRIMARY KEY,
    indicator_id         TEXT NOT NULL REFERENCES indicators(indicator_id) ON DELETE RESTRICT,
    source_grade         TEXT NOT NULL CHECK (source_grade IN ('A', 'B', 'C')),
    measurement_scope    TEXT NOT NULL,
    proxy_flag           INTEGER NOT NULL CHECK (proxy_flag IN (0, 1)),
    license_status       TEXT NOT NULL CHECK (license_status IN (
        'internal_research', 'internal_and_commercial', 'unknown', 'restricted'
    )),
    coverage_status      TEXT NOT NULL CHECK (coverage_status IN (
        'full_target_coverage', 'partial_coverage', 'unavailable', 'unknown'
    )),
    coverage_start_utc   TEXT,
    coverage_end_utc     TEXT,
    notes                TEXT,
    version              INTEGER NOT NULL,
    created_at_utc       TEXT NOT NULL,
    actor                TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_indicator_governance_indicator
    ON indicator_governance (indicator_id, version DESC);

CREATE TABLE IF NOT EXISTS source_license_terms (
    license_id                 TEXT PRIMARY KEY,
    source_id                  TEXT NOT NULL REFERENCES data_sources(source_id) ON DELETE RESTRICT,
    internal_research_allowed  INTEGER NOT NULL CHECK (internal_research_allowed IN (0, 1)),
    commercial_use_allowed     INTEGER NOT NULL CHECK (commercial_use_allowed IN (0, 1)),
    redistribution_allowed     INTEGER NOT NULL CHECK (redistribution_allowed IN (0, 1)),
    attribution_required       INTEGER NOT NULL CHECK (attribution_required IN (0, 1)),
    local_retention_allowed    INTEGER NOT NULL CHECK (local_retention_allowed IN (0, 1)),
    terms_url                  TEXT,
    notes                      TEXT,
    version                    INTEGER NOT NULL,
    created_at_utc             TEXT NOT NULL,
    actor                      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_source_license_terms_source
    ON source_license_terms (source_id, version DESC);

CREATE TRIGGER IF NOT EXISTS trg_indicator_governance_no_update
BEFORE UPDATE ON indicator_governance
BEGIN
    SELECT RAISE(ABORT, 'indicator_governance is append-only; append a new version');
END;

CREATE TRIGGER IF NOT EXISTS trg_indicator_governance_no_delete
BEFORE DELETE ON indicator_governance
BEGIN
    SELECT RAISE(ABORT, 'indicator_governance is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_license_terms_no_update
BEFORE UPDATE ON source_license_terms
BEGIN
    SELECT RAISE(ABORT, 'source_license_terms is append-only; append a new version');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_license_terms_no_delete
BEFORE DELETE ON source_license_terms
BEGIN
    SELECT RAISE(ABORT, 'source_license_terms is append-only');
END;