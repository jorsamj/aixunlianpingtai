
CREATE TABLE IF NOT EXISTS formal_bulk_execution (
    task_id TEXT PRIMARY KEY,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    active_batch TEXT,
    reconciliation TEXT
);
CREATE TABLE IF NOT EXISTS task_tombstones (
    task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
    payload_ref TEXT, attempt INTEGER NOT NULL DEFAULT 0, deleted_at TEXT NOT NULL,
    task_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_tombstone_project ON task_tombstones(project_id,task_id);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 999),
    queue_rank INTEGER NOT NULL DEFAULT 0,
    resource_key TEXT NOT NULL,
    required_capabilities TEXT NOT NULL,
    payload_ref TEXT NOT NULL,
    result_ref TEXT,
    log_ref TEXT NOT NULL,
    progress REAL NOT NULL,
    stage TEXT NOT NULL,
    current_item TEXT,
    attempt INTEGER NOT NULL,
    retry_of TEXT,
    error TEXT,
    accepted INTEGER,
    process_pid INTEGER,
    process_create_time REAL,
    process_command_hash TEXT,
    worker_id TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    annotation_name TEXT,
    annotation_model_name TEXT,
    annotation_model_id TEXT,
    annotation_search_ready INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_task_claim
    ON tasks(status, priority, created_at, task_id);
CREATE INDEX IF NOT EXISTS idx_task_resource
    ON tasks(resource_key, status, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_task_project_list
    ON tasks(project_id, created_at DESC, task_id DESC);
CREATE TABLE IF NOT EXISTS annotation_task_statistics (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    project_id TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_instances (
    instance_key TEXT PRIMARY KEY,
    owner_token TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    node_id TEXT NOT NULL DEFAULT 'legacy-unscoped',
    pid INTEGER NOT NULL,
    hostname TEXT NOT NULL DEFAULT '',
    build_id TEXT NOT NULL DEFAULT '',
    roles TEXT NOT NULL DEFAULT '[]',
    task_kinds TEXT NOT NULL DEFAULT '[]',
    capabilities TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_worker_instances_expiry
    ON worker_instances(expires_at);
