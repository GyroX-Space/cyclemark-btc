-- CMCI schema, migration 3 (P0-3): research datasets and L5 partitions
-- Append-only tables reject UPDATE/DELETE through triggers at the bottom.
-- Dataset versions are immutable once sealed; partition changes require a new
-- version so that the original validation set cannot silently lose its
-- independent status.

CREATE TABLE IF NOT EXISTS research_projects (
    project_id     TEXT PRIMARY KEY,
    project_code   TEXT NOT NULL UNIQUE,
    project_name   TEXT NOT NULL,
    description    TEXT NOT NULL,
    owner          TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    created_at_utc TEXT NOT NULL,
    CHECK (length(trim(project_code)) > 0),
    CHECK (length(trim(project_name)) > 0),
    CHECK (length(trim(description)) > 0),
    CHECK (length(trim(owner)) > 0)
);

CREATE TABLE IF NOT EXISTS research_datasets (
    dataset_id         TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE RESTRICT,
    dataset_code       TEXT NOT NULL UNIQUE,
    dataset_name       TEXT NOT NULL,
    description        TEXT NOT NULL,
    current_version_no INTEGER NOT NULL DEFAULT 0 CHECK (current_version_no >= 0),
    status             TEXT NOT NULL CHECK (status IN ('draft', 'active', 'archived')),
    created_by         TEXT NOT NULL,
    created_at_utc     TEXT NOT NULL,
    CHECK (length(trim(dataset_code)) > 0),
    CHECK (length(trim(dataset_name)) > 0),
    CHECK (length(trim(description)) > 0)
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_version_id TEXT PRIMARY KEY,
    dataset_id         TEXT NOT NULL REFERENCES research_datasets(dataset_id) ON DELETE RESTRICT,
    version_no         INTEGER NOT NULL CHECK (version_no >= 1),
    time_start         TEXT NOT NULL,
    time_end           TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('draft', 'sealed', 'superseded')),
    sealed_at_utc      TEXT,
    superseded_at_utc  TEXT,
    replaces_version_id TEXT REFERENCES dataset_versions(dataset_version_id) ON DELETE RESTRICT,
    invalidates_independent_validation INTEGER NOT NULL DEFAULT 0
        CHECK (invalidates_independent_validation IN (0, 1)),
    change_reason      TEXT NOT NULL,
    partition_hash     TEXT NOT NULL DEFAULT '',
    created_by         TEXT NOT NULL,
    created_at_utc     TEXT NOT NULL,
    CHECK (time_start <= time_end),
    CHECK (status <> 'draft' OR (sealed_at_utc IS NULL AND superseded_at_utc IS NULL)),
    CHECK (status <> 'sealed' OR (sealed_at_utc IS NOT NULL AND superseded_at_utc IS NULL)),
    CHECK (status <> 'superseded'
           OR (sealed_at_utc IS NOT NULL AND superseded_at_utc IS NOT NULL)),
    CHECK (length(trim(change_reason)) > 0),
    UNIQUE (dataset_id, version_no)
);

CREATE TABLE IF NOT EXISTS dataset_members (
    member_id          TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id) ON DELETE RESTRICT,
    indicator_id       TEXT NOT NULL REFERENCES indicators(indicator_id) ON DELETE RESTRICT,
    usage_partition    TEXT NOT NULL
        CHECK (usage_partition IN ('training', 'identification', 'validation', 'not_applicable')),
    time_start         TEXT NOT NULL,
    time_end           TEXT NOT NULL,
    embargo_before     REAL NOT NULL DEFAULT 0 CHECK (embargo_before >= 0),
    embargo_after      REAL NOT NULL DEFAULT 0 CHECK (embargo_after >= 0),
    partition_version  INTEGER NOT NULL DEFAULT 1 CHECK (partition_version >= 1),
    notes              TEXT,
    created_by         TEXT NOT NULL,
    created_at_utc     TEXT NOT NULL,
    CHECK (time_start <= time_end),
    UNIQUE (dataset_version_id, indicator_id, usage_partition, time_start, time_end)
);

CREATE INDEX IF NOT EXISTS ix_research_datasets_project
    ON research_datasets (project_id, dataset_code);

CREATE INDEX IF NOT EXISTS ix_dataset_versions_dataset
    ON dataset_versions (dataset_id, version_no);

CREATE INDEX IF NOT EXISTS ix_dataset_members_version
    ON dataset_members (dataset_version_id, indicator_id);

-- Dataset versions: sealed content is frozen, superseded versions are final.
CREATE TRIGGER IF NOT EXISTS trg_dataset_versions_no_delete
BEFORE DELETE ON dataset_versions
BEGIN
    SELECT RAISE(ABORT, 'dataset_versions is append-only; create a new version');
END;

CREATE TRIGGER IF NOT EXISTS trg_dataset_versions_guard
BEFORE UPDATE ON dataset_versions
WHEN OLD.status = 'superseded'
  OR (OLD.status = 'sealed' AND NEW.status = 'draft')
  OR (OLD.status <> 'draft' AND (
        NEW.dataset_id <> OLD.dataset_id
     OR NEW.version_no <> OLD.version_no
     OR NEW.time_start <> OLD.time_start
     OR NEW.time_end <> OLD.time_end
     OR NEW.partition_hash <> OLD.partition_hash))
BEGIN
    SELECT RAISE(ABORT, 'sealed dataset version is immutable; create a new version');
END;

-- Dataset members are immutable partition records.
CREATE TRIGGER IF NOT EXISTS trg_dataset_members_no_update
BEFORE UPDATE ON dataset_members
BEGIN
    SELECT RAISE(ABORT, 'dataset_members is append-only; create a new dataset version');
END;

CREATE TRIGGER IF NOT EXISTS trg_dataset_members_no_delete
BEFORE DELETE ON dataset_members
BEGIN
    SELECT RAISE(ABORT, 'dataset_members is append-only; create a new dataset version');
END;

CREATE TRIGGER IF NOT EXISTS trg_dataset_members_sealed_insert
BEFORE INSERT ON dataset_members
WHEN (SELECT status FROM dataset_versions
      WHERE dataset_version_id = NEW.dataset_version_id) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'dataset version is sealed; create a new version');
END;

CREATE TRIGGER IF NOT EXISTS trg_dataset_members_l5_partition
BEFORE INSERT ON dataset_members
WHEN NEW.usage_partition = 'not_applicable'
     AND (SELECT layer FROM indicators WHERE indicator_id = NEW.indicator_id) = 'L5'
BEGIN
    SELECT RAISE(ABORT, 'L5 dataset member requires training/identification/validation partition');
END;