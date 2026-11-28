-- CMCI schema, migration 5 (P0-5): quality and audit
-- Audit jobs and their findings are append-only so an independent reviewer can
-- reproduce and trace every result.

CREATE TABLE IF NOT EXISTS audit_jobs (
    audit_job_id     TEXT PRIMARY KEY,
    audit_type       TEXT NOT NULL CHECK (audit_type IN ('quality', 'lookahead')),
    parameters_json  TEXT NOT NULL,
    checked_count    INTEGER NOT NULL CHECK (checked_count >= 0),
    violation_count  INTEGER NOT NULL CHECK (violation_count >= 0),
    warning_count    INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
    report_json      TEXT NOT NULL,
    report_path      TEXT,
    created_by       TEXT NOT NULL,
    created_at_utc   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_results (
    audit_result_id TEXT PRIMARY KEY,
    audit_job_id    TEXT NOT NULL REFERENCES audit_jobs(audit_job_id) ON DELETE RESTRICT,
    severity        TEXT NOT NULL CHECK (severity IN ('violation', 'warning')),
    rule_code       TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    detail_json     TEXT NOT NULL,
    created_at_utc  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_audit_jobs_type_created
    ON audit_jobs (audit_type, created_at_utc);

CREATE INDEX IF NOT EXISTS ix_audit_results_job
    ON audit_results (audit_job_id, severity);

CREATE TRIGGER IF NOT EXISTS trg_audit_jobs_no_update
BEFORE UPDATE ON audit_jobs
BEGIN
    SELECT RAISE(ABORT, 'audit_jobs is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_jobs_no_delete
BEFORE DELETE ON audit_jobs
BEGIN
    SELECT RAISE(ABORT, 'audit_jobs is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_results_no_update
BEFORE UPDATE ON audit_results
BEGIN
    SELECT RAISE(ABORT, 'audit_results is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_results_no_delete
BEFORE DELETE ON audit_results
BEGIN
    SELECT RAISE(ABORT, 'audit_results is append-only');
END;