-- CMCI core schema, migration 1 (P0-1)
-- Time columns are ISO-8601 UTC text: YYYY-MM-DDTHH:MM:SSZ
-- Append-only tables reject UPDATE/DELETE through triggers at the bottom.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version        INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL,
    description    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_sources (
    source_id           TEXT PRIMARY KEY,
    source_name         TEXT NOT NULL,
    provider            TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    base_url            TEXT,
    access_method       TEXT NOT NULL,
    auth_type           TEXT,
    license_type        TEXT,
    update_frequency    TEXT,
    historical_coverage TEXT,
    revision_support    INTEGER NOT NULL DEFAULT 0 CHECK (revision_support IN (0, 1)),
    reliability_grade   TEXT,
    status              TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'pending_review')),
    notes               TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    created_at_utc      TEXT NOT NULL,
    updated_at_utc      TEXT NOT NULL,
    CHECK (length(trim(source_name)) > 0),
    CHECK (length(trim(provider)) > 0),
    CHECK (length(trim(source_type)) > 0),
    CHECK (length(trim(access_method)) > 0)
);

CREATE TABLE IF NOT EXISTS indicators (
    indicator_id           TEXT PRIMARY KEY,
    indicator_code         TEXT NOT NULL UNIQUE,
    indicator_name         TEXT NOT NULL,
    description            TEXT NOT NULL,
    layer                  TEXT NOT NULL CHECK (layer IN ('L1', 'L2', 'L3', 'L4', 'L5')),
    category               TEXT NOT NULL,
    sub_category           TEXT,
    unit                   TEXT NOT NULL,
    frequency              TEXT NOT NULL,
    timezone               TEXT NOT NULL,
    data_type              TEXT NOT NULL,
    source_policy          TEXT NOT NULL,
    update_method          TEXT NOT NULL CHECK (update_method IN ('api', 'file', 'manual')),
    revision_policy        TEXT NOT NULL,
    history_start          TEXT,
    history_end            TEXT,
    quality_policy         TEXT NOT NULL,
    license_note           TEXT,
    usage_partition_policy TEXT,
    partition_scope        TEXT,
    partition_notes        TEXT,
    status                 TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'disabled')),
    version                INTEGER NOT NULL DEFAULT 1,
    created_at_utc         TEXT NOT NULL,
    updated_at_utc         TEXT NOT NULL,
    CHECK (length(trim(indicator_code)) > 0),
    CHECK (length(trim(indicator_name)) > 0),
    CHECK (length(trim(description)) > 0),
    CHECK (length(trim(category)) > 0),
    CHECK (length(trim(unit)) > 0),
    CHECK (length(trim(frequency)) > 0),
    CHECK (length(trim(timezone)) > 0),
    CHECK (length(trim(data_type)) > 0),
    CHECK (length(trim(source_policy)) > 0),
    CHECK (length(trim(revision_policy)) > 0),
    CHECK (length(trim(quality_policy)) > 0),
    CHECK (
        layer <> 'L5'
        OR (usage_partition_policy IS NOT NULL AND length(trim(usage_partition_policy)) > 0)
    ),
    CHECK (history_start IS NULL OR history_end IS NULL OR history_start <= history_end)
);

CREATE TABLE IF NOT EXISTS indicator_versions (
    indicator_id           TEXT NOT NULL,
    version                INTEGER NOT NULL,
    indicator_code         TEXT NOT NULL,
    indicator_name         TEXT NOT NULL,
    description            TEXT NOT NULL,
    layer                  TEXT NOT NULL,
    category               TEXT NOT NULL,
    sub_category           TEXT,
    unit                   TEXT NOT NULL,
    frequency              TEXT NOT NULL,
    timezone               TEXT NOT NULL,
    data_type              TEXT NOT NULL,
    source_policy          TEXT NOT NULL,
    update_method          TEXT NOT NULL,
    revision_policy        TEXT NOT NULL,
    history_start          TEXT,
    history_end            TEXT,
    quality_policy         TEXT NOT NULL,
    license_note           TEXT,
    usage_partition_policy TEXT,
    partition_scope        TEXT,
    partition_notes        TEXT,
    status                 TEXT NOT NULL,
    created_at_utc         TEXT NOT NULL,
    updated_at_utc         TEXT NOT NULL,
    superseded_at_utc      TEXT NOT NULL,
    change_reason          TEXT NOT NULL,
    changed_by             TEXT NOT NULL,
    PRIMARY KEY (indicator_id, version)
);

CREATE TABLE IF NOT EXISTS indicator_sources (
    mapping_id        TEXT PRIMARY KEY,
    indicator_id      TEXT NOT NULL REFERENCES indicators(indicator_id) ON DELETE RESTRICT,
    source_id         TEXT NOT NULL REFERENCES data_sources(source_id) ON DELETE RESTRICT,
    role              TEXT NOT NULL CHECK (role IN ('primary', 'secondary')),
    notes             TEXT,
    effective_from_utc TEXT NOT NULL,
    effective_to_utc   TEXT,
    created_at_utc     TEXT NOT NULL,
    CHECK (effective_to_utc IS NULL OR effective_to_utc >= effective_from_utc)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_indicator_sources_active_primary
    ON indicator_sources (indicator_id)
    WHERE role = 'primary' AND effective_to_utc IS NULL;

CREATE INDEX IF NOT EXISTS ix_indicator_sources_indicator
    ON indicator_sources (indicator_id);

CREATE TABLE IF NOT EXISTS known_future_events (
    event_id                TEXT PRIMARY KEY,
    event_type              TEXT NOT NULL,
    event_name              TEXT NOT NULL,
    event_known_time_utc    TEXT NOT NULL,
    event_effective_time_utc TEXT NOT NULL,
    event_source            TEXT NOT NULL,
    known_future_event      INTEGER NOT NULL DEFAULT 1 CHECK (known_future_event = 1),
    notes                   TEXT,
    created_at_utc          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_logs (
    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    action         TEXT NOT NULL,
    actor          TEXT NOT NULL,
    detail_json    TEXT NOT NULL DEFAULT '{}',
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_operation_logs_entity
    ON operation_logs (entity_type, entity_id, log_id);

CREATE INDEX IF NOT EXISTS ix_indicators_layer_status
    ON indicators (layer, status);

-- Append-only enforcement (requirement 8).
CREATE TRIGGER IF NOT EXISTS trg_indicator_versions_no_update
BEFORE UPDATE ON indicator_versions
BEGIN
    SELECT RAISE(ABORT, 'indicator_versions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_indicator_versions_no_delete
BEFORE DELETE ON indicator_versions
BEGIN
    SELECT RAISE(ABORT, 'indicator_versions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_operation_logs_no_update
BEFORE UPDATE ON operation_logs
BEGIN
    SELECT RAISE(ABORT, 'operation_logs is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_operation_logs_no_delete
BEFORE DELETE ON operation_logs
BEGIN
    SELECT RAISE(ABORT, 'operation_logs is append-only');
END;