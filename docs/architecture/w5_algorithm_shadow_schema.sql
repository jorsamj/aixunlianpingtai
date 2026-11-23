-- W5 U1 algorithm-domain read-only shadow (isolated PostgreSQL only)
CREATE SCHEMA IF NOT EXISTS w5_shadow;

CREATE TABLE IF NOT EXISTS w5_shadow.algorithm_snapshot (
    project_id TEXT PRIMARY KEY,
    algorithm_revision BIGINT NOT NULL,
    snapshot_digest CHAR(64) NOT NULL,
    contract_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    algorithm_count INTEGER NOT NULL,
    version_count INTEGER NOT NULL,
    analysis_count INTEGER NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS w5_shadow.algorithm_row (
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('algorithm','version','analysis')),
    natural_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY(project_id, kind, natural_key)
);

CREATE INDEX IF NOT EXISTS idx_w5_shadow_row_project_kind
    ON w5_shadow.algorithm_row(project_id, kind, natural_key);
