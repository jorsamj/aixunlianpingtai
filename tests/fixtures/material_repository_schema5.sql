-- Genuine schema5 DDL from 71f5d221eb722678afa2ebf40209fc331e3f1a33 platform_core/material_repository.py
-- SHA256 of original _SCHEMA: a0b80fbfe1b1904a2a00e67aee6f6f8b76f05f85017fcbc6738ecc451995fa9d

CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL DEFAULT '',
    storage_source_id TEXT NOT NULL DEFAULT 'default_local',
    storage_type TEXT NOT NULL DEFAULT 'local',
    object_key TEXT NOT NULL,
    content_sha256 TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    etag TEXT NOT NULL DEFAULT '',
    processing_status TEXT NOT NULL DEFAULT 'pending_decision',
    box_count INTEGER NOT NULL DEFAULT 0,
    annotated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_materials_source ON materials(storage_source_id, created_at, id);
CREATE INDEX IF NOT EXISTS ix_materials_reference ON materials(storage_source_id, object_key);
CREATE INDEX IF NOT EXISTS ix_materials_status ON materials(processing_status, created_at, id);
CREATE INDEX IF NOT EXISTS ix_materials_filename ON materials(filename COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_materials_created ON materials(created_at, id);
CREATE INDEX IF NOT EXISTS ix_materials_content_sha256 ON materials(content_sha256) WHERE content_sha256 <> '';
CREATE INDEX IF NOT EXISTS ix_materials_content_sha256_normalized ON materials(lower(trim(content_sha256))) WHERE content_sha256 <> '';
CREATE TABLE IF NOT EXISTS material_labels (
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    label_code TEXT NOT NULL,
    box_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(material_id, label_code)
);
CREATE INDEX IF NOT EXISTS ix_material_labels_code ON material_labels(label_code, material_id);
CREATE TABLE IF NOT EXISTS material_annotation_scopes (
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    label_code TEXT NOT NULL,
    PRIMARY KEY(material_id, label_code)
);
CREATE INDEX IF NOT EXISTS ix_material_annotation_scopes_code
    ON material_annotation_scopes(label_code, material_id);
CREATE TABLE IF NOT EXISTS material_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO material_meta(key, value) VALUES ('revision', '0');
CREATE TABLE IF NOT EXISTS material_migrations (
    source TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    imported_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_storage_audit (
    task_id TEXT NOT NULL, image_id TEXT NOT NULL, action TEXT NOT NULL,
    old_sha256 TEXT NOT NULL, new_sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL,
    PRIMARY KEY(task_id,image_id)
);
CREATE TABLE IF NOT EXISTS material_retirements (
    task_id TEXT NOT NULL, image_id TEXT NOT NULL, actor_id TEXT NOT NULL,
    storage_source_id TEXT NOT NULL, object_key TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL, annotation_json TEXT NOT NULL, retired_at TEXT NOT NULL,
    reclamation_state TEXT NOT NULL DEFAULT 'DEFERRED_SAFETY_UNVERIFIED',
    reclaimed_bytes INTEGER NOT NULL DEFAULT 0 CHECK(reclaimed_bytes=0),
    PRIMARY KEY(task_id,image_id)
);
CREATE INDEX IF NOT EXISTS ix_material_retirements_source
    ON material_retirements(storage_source_id,object_key);
CREATE TABLE IF NOT EXISTS material_cleanup_deferred (
    cleanup_id TEXT PRIMARY KEY, image_id TEXT NOT NULL, owner TEXT NOT NULL,
    payload_json TEXT NOT NULL, last_error TEXT NOT NULL, recorded_at TEXT NOT NULL,
    reclamation_state TEXT NOT NULL DEFAULT 'DEFERRED_SAFETY_UNVERIFIED'
);

PRAGMA user_version=5;
