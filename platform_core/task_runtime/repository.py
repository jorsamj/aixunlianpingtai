from __future__ import annotations

from ..performance_diagnostics import connect_sqlite, observe_connection

from contextlib import closing, contextmanager

import base64
from hashlib import sha256
import json
import sqlite3
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from filelock import FileLock, Timeout

from .claim_candidates import prepare_candidates, SEMANTIC_FIELDS, key as candidate_key

from .models import TaskKind, TaskLease, TaskPage, TaskRecord, TaskStatus, utc_now
from .process_control import ProcessIdentity
from .sqlite_busy import busy_timeout_ms, is_sqlite_busy, retry_busy
from .payload_publications import (
    VERSION_REF, PayloadPublicationError, PayloadPublicationIdentity,
    PayloadPublicationResult, PreparedPayloadPublication,
)
from ..gpu_resources import ensure_gpu_runtime_schema
from .inference_resources import InferenceResourceMethods, ensure_inference_runtime_schema


_SCHEMA_VERSION = 7
_INIT_LOCK_TIMEOUT = 30
# Bounded automatic recovery for ANNOTATION_FORMAL_BULK only. Reaching the cap
# leaves the task in a durable blocked stage that requires an explicit,
# re-verified operator resume; other TaskKinds keep their existing behaviour.
MAX_FORMAL_BULK_ATTEMPTS = 5


def admission_preparer(admission):
    return getattr(admission, "prepare", None) or getattr(getattr(admission, "__self__", None), "prepare_admission", None)

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS execution_resource_holds (
    task_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    assignment_generation INTEGER NOT NULL,
    execution_attempt INTEGER NOT NULL,
    gpu_uuid TEXT NOT NULL,
    state TEXT NOT NULL,
    proof_sha256 TEXT,
    updated_at TEXT NOT NULL
);
"""


TERMINAL_STATUSES = {
    TaskStatus.PARTIAL_SUCCESS,
    TaskStatus.SUCCEEDED,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED_BY_ENVIRONMENT,
    TaskStatus.BLOCKED_BY_HARDWARE,
}


def _iso(value: datetime | str | None = None) -> str:
    if value is None:
        return utc_now()
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _to_values(record: TaskRecord) -> dict:
    values = asdict(record)
    values["kind"] = record.kind.value
    values["status"] = record.status.value
    values["required_capabilities"] = json.dumps(
        list(record.required_capabilities),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    values["accepted"] = None if record.accepted is None else int(record.accepted)
    return values


def _annotation_search_fields(request: dict) -> tuple[str, str, str]:
    """Only searchable, non-secret columns derived from the immutable request."""
    return (
        str(request.get("task_name") or "AI自动标注任务"),
        str(request.get("model_config_name") or ""),
        str(request.get("model_config_id") or ""),
    )


def _from_row(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        task_id=str(row["task_id"]),
        project_id=str(row["project_id"]),
        kind=TaskKind(str(row["kind"])),
        status=TaskStatus(str(row["status"])),
        priority=int(row["priority"]),
        resource_key=str(row["resource_key"]),
        required_capabilities=tuple(json.loads(row["required_capabilities"] or "[]")),
        payload_ref=str(row["payload_ref"]),
        result_ref=row["result_ref"],
        log_ref=str(row["log_ref"]),
        progress=float(row["progress"]),
        stage=str(row["stage"]),
        current_item=row["current_item"],
        attempt=int(row["attempt"]),
        retry_of=row["retry_of"],
        error=row["error"],
        accepted=None if row["accepted"] is None else bool(row["accepted"]),
        process_pid=row["process_pid"],
        process_create_time=row["process_create_time"],
        process_command_hash=row["process_command_hash"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=row["finished_at"],
        resource_wait_reason=row["resource_wait_reason"],
        queue_rank=int(row["queue_rank"] or 0),
        worker_id=row["worker_id"],
        lease_expires_at=row["lease_expires_at"],
    )


def _encode_cursor(created_at: str, task_id: str) -> str:
    raw = json.dumps([created_at, task_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        return str(value[0]), str(value[1])
    except Exception as error:
        raise ValueError("invalid task cursor") from error


def _add_column_if_missing(
    database: sqlite3.Connection,
    table: str,
    columns: set[str],
    name: str,
    definition: str,
) -> None:
    if name in columns:
        return
    try:
        database.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    except sqlite3.OperationalError:
        refreshed = {
            str(row[1])
            for row in database.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if name not in refreshed:
            raise
        columns.update(refreshed)
        return
    columns.add(name)


class TaskRepository(InferenceResourceMethods):
    # Non-empty claim_next performs expiry recovery inside its claim transaction.
    # Subclasses replacing that contract must explicitly opt out.
    claim_recovers_expired = True

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._claim_cursors = {}
        self._claim_cursor_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        database = connect_sqlite(self.path, timeout=5, isolation_level=None)
        database.row_factory = sqlite3.Row
        database.execute(f"PRAGMA busy_timeout={busy_timeout_ms()}")
        database.execute("PRAGMA synchronous=FULL")
        return observe_connection(database)

    def _read_schema_version_fast(self) -> int | None:
        if not self.path.is_file():
            return None
        try:
            with closing(
                sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
            ) as database:
                database.execute("PRAGMA busy_timeout=250")
                return int(database.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.Error:
            return None

    def _initialize(self) -> None:
        if self._read_schema_version_fast() == _SCHEMA_VERSION:
            return
        lock = FileLock(
            str(self.path.resolve()) + ".init.lock",
            timeout=_INIT_LOCK_TIMEOUT,
        )
        with lock:
            with closing(self._connect()) as database:
                version = int(database.execute("PRAGMA user_version").fetchone()[0])
                if version == _SCHEMA_VERSION:
                    return
                if version > _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"task repository schema {version} is newer than supported {_SCHEMA_VERSION}"
                    )
                mode = str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                if mode != "wal":
                    mode = str(database.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                if mode != "wal":
                    raise RuntimeError(
                        f"task repository requires WAL mode, got {mode}"
                    )
                database.executescript(SCHEMA)
                # NOTE: executescript is not a single transaction; the schema
                # statements may commit independently. Recovery therefore relies
                # on every statement being idempotent and on user_version only
                # advancing after all migration work succeeds.
                if version <= 6:
                    # Schema-6 databases have every prior table but no execution
                    # resource holds. This migration is idempotent and runs only
                    # inside the existing initialization lock before user_version
                    # advances to 7.
                    database.execute(
                        "CREATE TABLE IF NOT EXISTS execution_resource_holds ("
                        "task_id TEXT PRIMARY KEY,node_id TEXT NOT NULL,"
                        "assignment_generation INTEGER NOT NULL,execution_attempt INTEGER NOT NULL,"
                        "gpu_uuid TEXT NOT NULL,state TEXT NOT NULL,"
                        "proof_sha256 TEXT,updated_at TEXT NOT NULL)"
                    )
                columns = {
                    str(row[1])
                    for row in database.execute("PRAGMA table_info(tasks)").fetchall()
                }
                _add_column_if_missing(
                    database, "tasks", columns, "queue_rank", "INTEGER NOT NULL DEFAULT 0"
                )
                _add_column_if_missing(
                    database, "tasks", columns, "resource_wait_reason", "TEXT"
                )
                for name, definition in (
                    ("annotation_name", "TEXT"),
                    ("annotation_model_name", "TEXT"),
                    ("annotation_model_id", "TEXT"),
                    ("annotation_search_ready", "INTEGER NOT NULL DEFAULT 0"),
                ):
                    _add_column_if_missing(database, "tasks", columns, name, definition)
                database.execute(
                    "CREATE INDEX IF NOT EXISTS idx_task_annotation_search_pending "
                    "ON tasks(project_id, kind, annotation_search_ready, created_at)"
                )
                worker_columns = {
                    str(row[1])
                    for row in database.execute(
                        "PRAGMA table_info(worker_instances)"
                    ).fetchall()
                }
                additive_worker_columns = (
                    ("node_id", "TEXT NOT NULL DEFAULT 'legacy-unscoped'"),
                    ("hostname", "TEXT NOT NULL DEFAULT ''"),
                    ("build_id", "TEXT NOT NULL DEFAULT ''"),
                    ("roles", "TEXT NOT NULL DEFAULT '[]'"),
                    ("task_kinds", "TEXT NOT NULL DEFAULT '[]'"),
                    ("capabilities", "TEXT NOT NULL DEFAULT '[]'"),
                )
                for name, definition in additive_worker_columns:
                    _add_column_if_missing(
                        database, "worker_instances", worker_columns, name, definition
                    )
                database.execute('CREATE INDEX IF NOT EXISTS idx_task_claim_pipeline ON tasks(status,priority,queue_rank DESC,created_at,task_id)')
                ensure_gpu_runtime_schema(database)
                ensure_inference_runtime_schema(database)
                database.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def journal_mode(self) -> str:
        with closing(self._connect()) as database:
            return str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def create(self, record: TaskRecord, *, artifacts=None) -> TaskRecord:
        from .artifacts import ArtifactStore
        from .task_logs import create_task_log

        if self.is_deleted(record.task_id):
            raise ValueError('TASK_ID_RETIRED: deleted task identities cannot be reused')
        # Persist the real artifact before exposing its reference in a task row.
        artifact_store = artifacts or ArtifactStore(self.path.parent / "artifacts")
        create_task_log(artifact_store, record.task_id, record.log_ref)
        values = _to_values(record)
        if record.kind is TaskKind.AI_ANNOTATION:
            # Freeze search metadata with the task row; future model edits must
            # never rewrite the name/model originally selected by the user.
            try:
                request = artifact_store.read_json(record.task_id, record.payload_ref)
                if isinstance(request, dict):
                    name, model, model_id = _annotation_search_fields(request)
                    values.update(annotation_name=name, annotation_model_name=model,
                                  annotation_model_id=model_id, annotation_search_ready=1)
            except (OSError, ValueError):
                # Preserve original creation semantics if an artifact is
                # temporarily unavailable. The bounded backfill can recover it.
                pass
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            if database.execute('SELECT 1 FROM task_tombstones WHERE task_id=?',(record.task_id,)).fetchone():
                raise ValueError('TASK_ID_RETIRED: deleted task identities cannot be reused')
            database.execute(
                f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
            row = database.execute("SELECT * FROM tasks WHERE task_id=?", (record.task_id,)).fetchone()
            if row is None:
                raise RuntimeError("task insert did not persist")
            # Resolve the return value before publishing the row. A failed read
            # must roll back rather than report failure for a claimable task.
            created = _from_row(row)
            database.commit()
        return created

    @retry_busy
    def create_deployment_pair(self, parent: TaskRecord, child: TaskRecord) -> TaskRecord:
        """Publish one detection plus its preparation atomically in the original queue."""
        from .artifacts import ArtifactStore
        from .task_logs import create_task_log
        if (parent.kind is not TaskKind.DEPLOYMENT_TEST or child.kind is not TaskKind.DEPLOYMENT_PREPARE
                or child.task_id != parent.task_id + "-prepare" or child.project_id != parent.project_id):
            raise ValueError("invalid deployment preparation pair")
        artifacts = ArtifactStore(self.path.parent / "artifacts")
        for record in (parent, child):
            create_task_log(artifacts, record.task_id, record.log_ref)
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            for record in (parent, child):
                if database.execute('SELECT 1 FROM task_tombstones WHERE task_id=?',(record.task_id,)).fetchone():
                    raise ValueError('TASK_ID_RETIRED: deleted task identities cannot be reused')
                values = _to_values(record)
                database.execute(f"INSERT INTO tasks ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
            database.commit()
        return parent

    @retry_busy
    def settle_deployment_preparation(self, parent_id, child_lease, *, error=None, prepared_ref=None):
        """Only the associated live preparation generation can release/fail its queued parent."""
        if child_lease.task.task_id != str(parent_id) + "-prepare":
            raise PermissionError("deployment preparation association mismatch")
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            now = utc_now()
            child = database.execute("SELECT * FROM tasks WHERE task_id=?", (child_lease.task.task_id,)).fetchone()
            if (child is None or child["kind"] != TaskKind.DEPLOYMENT_PREPARE.value
                    or child["status"] != 'RUNNING' or child["lease_token"] != child_lease.lease_token
                    or child["attempt"] != child_lease.task.attempt or not child["lease_expires_at"]
                    or child["lease_expires_at"] <= now):
                raise PermissionError("deployment preparation execution is fenced")
            parent = database.execute("SELECT * FROM tasks WHERE task_id=?", (str(parent_id),)).fetchone()
            if parent is None or parent["kind"] != 'DEPLOYMENT_TEST' or parent["project_id"] != child["project_id"]:
                raise PermissionError("deployment preparation parent mismatch")
            self._reject_legacy_payload_mutation(parent["payload_ref"])
            if parent["status"] != 'QUEUED':
                raise InterruptedError("deployment parent is no longer queued")
            if error is None:
                if prepared_ref != f"scenario/prepared-{child_lease.task.attempt}.json":
                    raise ValueError("invalid prepared deployment reference")
                database.execute("UPDATE tasks SET required_capabilities=?,payload_ref=?,stage='queued',updated_at=? WHERE task_id=?",
                                 (json.dumps(['deployment.runtime']), prepared_ref, now, str(parent_id)))
            else:
                database.execute("UPDATE tasks SET status='FAILED',stage='preparation_failed',error=?,finished_at=?,updated_at=? WHERE task_id=?",
                                 (str(error)[:8000], now, now, str(parent_id)))
            database.commit()

    @staticmethod
    def _reject_legacy_payload_mutation(payload_ref):
        if VERSION_REF.fullmatch(str(payload_ref)):
            raise PayloadPublicationError("PAYLOAD_PUBLICATION_PARENT_NOT_ELIGIBLE",
                                          "versioned parents require the strict publication interface")

    def bind_preparation_input(self, lease, parent_id, proposal, artifacts):
        """Explicit owned upgrade of deterministic legacy child associations."""
        kind = lease.task.kind
        expected_id = f"trainprep_{parent_id}" if kind is TaskKind.TRAINING_PREPARE else f"{parent_id}-prepare"
        parent_kind = TaskKind.TRAINING if kind is TaskKind.TRAINING_PREPARE else TaskKind.DEPLOYMENT_TEST
        if kind not in {TaskKind.TRAINING_PREPARE, TaskKind.DEPLOYMENT_PREPARE} or lease.task.task_id != expected_id:
            raise PermissionError("preparation association mismatch")
        verified = artifacts.payload_reader.read_payload_publication_receipt(expected_id, proposal.operation_id, identity=proposal.identity)
        if verified != proposal or proposal.identity.data['phase'] != 'create':
            raise PermissionError("preparation association proposal mismatch")
        expected = ({'schema_version':2,'training_task_id':parent_id,'project_id':lease.task.project_id}
                    if kind is TaskKind.TRAINING_PREPARE else {'parent_task_id':parent_id})
        if verified.version.data != expected:
            raise PermissionError("preparation association content mismatch")
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            parent=database.execute("SELECT * FROM tasks WHERE task_id=?",(parent_id,)).fetchone()
            if parent is None or parent['kind']!=parent_kind.value or parent['project_id']!=lease.task.project_id:
                raise PermissionError("preparation project mismatch")
            changed=database.execute("""UPDATE tasks SET payload_ref=? WHERE task_id=? AND project_id=?
                AND kind=? AND status='RUNNING' AND lease_token=? AND attempt=? AND worker_id=?
                AND lease_expires_at>? AND payload_ref=?""",(proposal.version.payload_ref,expected_id,
                lease.task.project_id,kind.value,lease.lease_token,lease.task.attempt,lease.worker_id,
                utc_now(),lease.task.payload_ref)).rowcount
            if changed!=1:
                raise PermissionError("preparation input binding is fenced")
            if (parent_kind is TaskKind.TRAINING and parent['status']=='QUEUED'
                    and not VERSION_REF.fullmatch(parent['payload_ref'])):
                # Explicit owned migration of old unprepared requests. Never
                # rewind a RUNNING parent or change an execution's resources.
                database.execute("UPDATE tasks SET required_capabilities=?,stage='training_input_pending' WHERE task_id=?",
                    (json.dumps(['training.input.ready']),parent_id))
            row=database.execute("SELECT * FROM tasks WHERE task_id=?",(expected_id,)).fetchone()
            database.commit()
        return _from_row(row)

    def publish_training_payload(self, parent_id, *, artifacts, publication,
                                 child_task_id, child_lease_token, child_attempt,
                                 child_worker_id, child_payload_ref) -> PayloadPublicationResult:
        return self._publish_payload(parent_id, TaskKind.TRAINING, TaskKind.TRAINING_PREPARE,
            artifacts=artifacts, publication=publication, child_task_id=child_task_id,
            child_lease_token=child_lease_token, child_attempt=child_attempt,
            child_worker_id=child_worker_id, child_payload_ref=child_payload_ref)

    def publish_deployment_payload(self, parent_id, *, artifacts, publication,
                                   child_task_id, child_lease_token, child_attempt,
                                   child_worker_id, child_payload_ref) -> PayloadPublicationResult:
        return self._publish_payload(parent_id, TaskKind.DEPLOYMENT_TEST, TaskKind.DEPLOYMENT_PREPARE,
            artifacts=artifacts, publication=publication, child_task_id=child_task_id,
            child_lease_token=child_lease_token, child_attempt=child_attempt,
            child_worker_id=child_worker_id, child_payload_ref=child_payload_ref)

    def _publish_payload(self, parent_id, parent_kind, child_kind, *, artifacts, publication,
                         child_task_id, child_lease_token, child_attempt, child_worker_id, child_payload_ref):
        # All filesystem reads, hashing and potentially large JSON parsing are
        # outside the retryable writer transaction. A descriptor is not trusted
        # merely because it is an instance of a public dataclass.
        if not isinstance(publication, PreparedPayloadPublication):
            raise PayloadPublicationError("PUBLICATION_INVALID_RECEIPT", "prepared proposal required")
        identity = publication.identity
        if not isinstance(identity, PayloadPublicationIdentity):
            raise PayloadPublicationError("PUBLICATION_INVALID_IDENTITY", "typed publication identity required")
        fields = identity.data
        phases = {"training.freeze", "training.ready"} if parent_kind is TaskKind.TRAINING else {"deployment.ready"}
        if fields["task_id"] != parent_id or fields["parent_kind"] != parent_kind.value or fields["phase"] not in phases:
            raise PayloadPublicationError("PAYLOAD_PUBLICATION_IDENTITY_MISMATCH", "parent identity or phase mismatch")
        expected_child = f"trainprep_{parent_id}" if parent_kind is TaskKind.TRAINING else f"{parent_id}-prepare"
        if child_task_id != expected_child:
            raise PayloadPublicationError("PAYLOAD_PUBLICATION_PARENT_CHILD_MISMATCH", "associated preparation child required")
        # Preserve P1's precise file/receipt/integrity error codes.
        reader = getattr(artifacts, "payload_reader", artifacts)
        verified = reader.read_payload_publication_receipt(parent_id, identity.operation_id, identity=identity)
        if verified != publication:
            raise PayloadPublicationError("PUBLICATION_OPERATION_CONFLICT", "proposal differs from the immutable receipt")
        try:
            child_input = reader.read_payload_version(child_task_id, child_payload_ref).data
        except PayloadPublicationError as error:
            raise PayloadPublicationError("PAYLOAD_PUBLICATION_CONTENT_MISMATCH", "immutable verified child input required") from error
        binding = "training_task_id" if parent_kind is TaskKind.TRAINING else "parent_task_id"
        if (not isinstance(child_input, dict) or child_input.get(binding) != parent_id
                or (parent_kind is TaskKind.TRAINING and child_input.get("project_id") != fields["project_id"])
                or ("project_id" in child_input and child_input["project_id"] != fields["project_id"])):
            raise PayloadPublicationError("PAYLOAD_PUBLICATION_PARENT_CHILD_MISMATCH", "child input binds another parent/project")
        activation = verified.metadata["activation"]
        if fields["phase"] == "training.freeze":
            if activation:
                raise PayloadPublicationError("PAYLOAD_PUBLICATION_PARENT_NOT_ELIGIBLE", "freeze cannot activate the parent")
        else:
            capabilities = activation.get("required_capabilities", [])
            if (set(activation) != {"resource_key", "required_capabilities", "stage"}
                    or activation["stage"] != "queued" or not capabilities
                    or {"training.input.ready", "deployment.input.pending", "training.prepare", "deployment.prepare"}.intersection(capabilities)
                    or (parent_kind is TaskKind.DEPLOYMENT_TEST and capabilities != ["deployment.runtime"])):
                raise PayloadPublicationError("PAYLOAD_PUBLICATION_PARENT_NOT_ELIGIBLE", "READY requires complete execution activation")
        capabilities_json = json.dumps(sorted(set(activation.get("required_capabilities", []))), separators=(",", ":"))
        confirmed = self._confirm_payload_publication(fields, verified.version.payload_ref, identity.operation_id,
                                                       parent_kind, child_kind, child_task_id)
        if confirmed is not None:
            return confirmed
        if (not isinstance(child_lease_token, str) or not child_lease_token
                or type(child_attempt) is not int or child_attempt < 1
                or not isinstance(child_worker_id, str) or not child_worker_id):
            raise PayloadPublicationError("PAYLOAD_PUBLICATION_LEASE_INVALID", "complete execution ownership required")
        assert_active = getattr(artifacts, "assert_publication_execution", None)
        if callable(assert_active):
            assert_active()
        return self._commit_payload_publication(fields, verified.version.payload_ref, identity.operation_id,
            parent_kind, child_kind, child_task_id, child_lease_token, child_attempt,
            child_worker_id, child_payload_ref, activation, capabilities_json)

    @retry_busy
    def _confirm_payload_publication(self, fields, new_ref, operation_id, parent_kind, child_kind, child_id):
        # One read snapshot. No writer reservation, UPDATE, lease revival or
        # inference of history from an orphan receipt.
        with closing(self._connect()) as database:
            row = database.execute("""SELECT parent.* FROM tasks parent JOIN (
                    SELECT task_id,kind,project_id FROM tasks WHERE task_id=?
                    UNION ALL SELECT task_id,kind,project_id FROM task_tombstones WHERE task_id=?
                ) child ON child.kind=? AND child.project_id=parent.project_id
                WHERE parent.task_id=? AND parent.project_id=? AND parent.kind=? AND parent.payload_ref=?""",
                (child_id, child_id, child_kind.value, fields["task_id"], fields["project_id"], parent_kind.value, new_ref)).fetchone()
        return None if row is None else PayloadPublicationResult("ALREADY_APPLIED", _from_row(row), operation_id)

    @retry_busy
    def _commit_payload_publication(self, fields, new_ref, operation_id, parent_kind, child_kind,
                                    child_id, token, attempt, worker_id, child_ref, activation, capabilities_json):
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc)
            parent = database.execute("SELECT * FROM tasks WHERE task_id=?", (fields["task_id"],)).fetchone()
            child = database.execute("SELECT * FROM tasks WHERE task_id=?", (child_id,)).fetchone()
            if child is None and parent is not None and parent['payload_ref']==new_ref:
                child=database.execute('SELECT task_id,kind,project_id FROM task_tombstones WHERE task_id=?',(child_id,)).fetchone()
            if parent is None or parent["kind"] != parent_kind.value or parent["project_id"] != fields["project_id"]:
                raise PayloadPublicationError("PAYLOAD_PUBLICATION_IDENTITY_MISMATCH", "current parent identity mismatch")
            expected_child = f"trainprep_{parent['task_id']}" if parent_kind is TaskKind.TRAINING else f"{parent['task_id']}-prepare"
            if (child is None or child["task_id"] != expected_child or child["kind"] != child_kind.value
                    or child["project_id"] != parent["project_id"]):
                raise PayloadPublicationError("PAYLOAD_PUBLICATION_PARENT_CHILD_MISMATCH", "current child identity mismatch")
            if parent["payload_ref"] == new_ref:
                # Parent may already be RUNNING/terminal with a higher attempt.
                # Confirmation never re-applies activation or changes ownership.
                outcome = "ALREADY_APPLIED"
            else:
                if child["payload_ref"] != child_ref:
                    raise PayloadPublicationError("PAYLOAD_PUBLICATION_CONTENT_MISMATCH", "child input reference changed")
                try:
                    expires = datetime.fromisoformat(str(child["lease_expires_at"]).replace("Z", "+00:00"))
                    valid_time = expires.tzinfo is not None and expires.astimezone(timezone.utc) > now
                except (ValueError, TypeError, OverflowError):
                    valid_time = False
                if (child["status"] != "RUNNING" or child["lease_token"] != token or child["attempt"] != attempt
                        or child["worker_id"] != worker_id or not valid_time):
                    raise PayloadPublicationError("PAYLOAD_PUBLICATION_LEASE_INVALID", "preparation execution is fenced")
                if parent["payload_ref"] != fields["expected_payload_ref"]:
                    raise PayloadPublicationError("PAYLOAD_PUBLICATION_EXPECTED_REF_CONFLICT", "current reference superseded this proposal")
                pending = "training.input.ready" if parent_kind is TaskKind.TRAINING else "deployment.input.pending"
                stages = {"training_input_pending", "queued"} if parent_kind is TaskKind.TRAINING else {"PREPARING_MODEL"}
                if (parent["status"] != "QUEUED" or parent["attempt"] != fields["expected_parent_attempt"]
                        or json.loads(parent["required_capabilities"]) != [pending] or parent["stage"] not in stages):
                    raise PayloadPublicationError("PAYLOAD_PUBLICATION_PARENT_NOT_ELIGIBLE", "parent no longer has its preparation gate")
                updates = "payload_ref=?,updated_at=?"
                parameters = [new_ref, now.isoformat()]
                if activation:
                    updates += ",resource_key=?,required_capabilities=?,stage=?"
                    parameters.extend([activation["resource_key"], capabilities_json, activation["stage"]])
                parameters.extend([fields["task_id"], fields["project_id"], parent_kind.value,
                                   fields["expected_payload_ref"], fields["expected_parent_attempt"],
                                   parent["required_capabilities"], parent["stage"]])
                changed = database.execute(f"""UPDATE tasks SET {updates}
                    WHERE task_id=? AND project_id=? AND kind=? AND status='QUEUED'
                      AND payload_ref=? AND attempt=? AND required_capabilities=? AND stage=?""", parameters).rowcount
                if changed != 1:
                    raise PayloadPublicationError("PAYLOAD_PUBLICATION_EXPECTED_REF_CONFLICT", "conditional publication lost")
                parent = database.execute("SELECT * FROM tasks WHERE task_id=?", (fields["task_id"],)).fetchone()
                outcome = "APPLIED"
            result = PayloadPublicationResult(outcome, _from_row(parent), operation_id)
            try:
                database.commit()
            except sqlite3.Error as error:
                if is_sqlite_busy(error):
                    raise
                raise PayloadPublicationError("PAYLOAD_PUBLICATION_COMMIT_FAILED", "commit not confirmed; retry the same operation to inspect its outcome") from error
        return result

    def get(self, task_id: str) -> TaskRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
        return _from_row(row) if row is not None else None

    @retry_busy
    def set_annotation_statistics(self, task_id: str, counts: dict[str, int], *, only_if_absent: bool = False) -> None:
        """Persist one genuine CandidateStore/commit journal snapshot, never synthetic zeroes."""
        keys = ("total", "success", "empty", "failed", "accepted", "rejected",
                "unreviewed", "boxes", "gt_committed")
        if set(counts) != set(keys) or any(type(counts[key]) is not int or counts[key] < 0 for key in keys):
            raise ValueError("invalid annotation statistics")
        if counts["total"] != counts["success"] + counts["empty"] + counts["failed"]:
            raise ValueError("annotation generation totals do not reconcile")
        if counts["success"] + counts["empty"] != counts["accepted"] + counts["rejected"] + counts["unreviewed"]:
            raise ValueError("annotation review totals do not reconcile")
        if counts["gt_committed"] > counts["accepted"]:
            raise ValueError("formal GT journal exceeds accepted candidates")
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            task = database.execute("SELECT project_id,kind FROM tasks WHERE task_id=?", (str(task_id),)).fetchone()
            if task is None or task["kind"] != TaskKind.AI_ANNOTATION.value:
                raise ValueError("annotation statistics require an existing AI task")
            conflict = ("DO NOTHING" if only_if_absent else
                        "DO UPDATE SET counts_json=excluded.counts_json,synced_at=excluded.synced_at")
            database.execute(
                "INSERT INTO annotation_task_statistics(task_id,project_id,counts_json,synced_at) VALUES (?,?,?,?) "
                f"ON CONFLICT(task_id) {conflict}",
                (str(task_id), task["project_id"], json.dumps(counts, sort_keys=True), utc_now()),
            )
            database.commit()

    def annotation_statistics_many(self, project_id: str, task_ids: Iterable[str]) -> dict[str, dict]:
        ids = list(dict.fromkeys(str(task_id) for task_id in task_ids if str(task_id)))
        if not ids:
            return {}
        if len(ids) > 100:
            raise ValueError("annotation statistics lookup limited to one task page")
        with closing(self._connect()) as database:
            rows = database.execute(
                f"SELECT task_id,counts_json,synced_at FROM annotation_task_statistics "
                f"WHERE project_id=? AND task_id IN ({','.join('?' for _ in ids)})",
                (str(project_id), *ids),
            ).fetchall()
        return {str(row["task_id"]): {"counts": json.loads(row["counts_json"]),
                                      "synced_at": row["synced_at"]} for row in rows}

    @contextmanager
    def source_reclamation_guard(self):
        """No-wait final source detach gate against all task create/retry/claim writes."""
        with closing(self._connect()) as database:
            database.execute("PRAGMA busy_timeout=0")
            database.execute("BEGIN IMMEDIATE")
            try:
                active = database.execute(
                    "SELECT task_id FROM tasks WHERE status NOT IN ('SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED')"
                ).fetchall()
                if active:
                    raise RuntimeError("ACTIVE_TASK")
                yield database
                database.commit()
            except BaseException:
                database.rollback()
                raise

    @contextmanager
    def training_workspace_guard(self, task_id: str):
        """Serialize a short workspace detach against create/claim/retry commits.

        File deletion must happen after leaving this transaction. This adds no
        task state or schema: the original tasks table remains authoritative.
        """
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                row = database.execute("SELECT * FROM tasks WHERE task_id=?", (str(task_id),)).fetchone()
                if row is None:
                    raise KeyError(task_id)
                task = _from_row(row)
                active = database.execute(
                    """SELECT * FROM tasks WHERE project_id=? AND task_id<>?
                       AND kind IN ('TRAINING','TRAINING_PREPARE','DEPLOYMENT_TEST')
                       AND status NOT IN ('SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED')""",
                    (task.project_id, task.task_id),
                ).fetchall()
                yield task, tuple(_from_row(item) for item in active)
                database.commit()
            except BaseException:
                database.rollback()
                raise

    def resource_queue_position(self, task_id: str) -> int | None:
        """Return the truthful ordering position among queued peers sharing a resource key.

        This is intentionally resource-scoped rather than a fake global queue position:
        different worker roles/capabilities may consume independent queues concurrently.
        """
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT task_id,status,priority,queue_rank,resource_key,created_at FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if str(row["status"]) != TaskStatus.QUEUED.value:
                return None
            ahead = database.execute(
                """
                SELECT COUNT(*) FROM tasks
                 WHERE status='QUEUED' AND resource_key=? AND task_id<>?
                   AND (
                        priority < ?
                        OR (priority = ? AND queue_rank > ?)
                        OR (priority = ? AND queue_rank = ? AND created_at < ?)
                        OR (priority = ? AND queue_rank = ? AND created_at = ? AND task_id < ?)
                   )
                """,
                (
                    str(row["resource_key"]), str(row["task_id"]),
                    int(row["priority"]),
                    int(row["priority"]), int(row["queue_rank"] or 0),
                    int(row["priority"]), int(row["queue_rank"] or 0), str(row["created_at"]),
                    int(row["priority"]), int(row["queue_rank"] or 0), str(row["created_at"]), str(row["task_id"]),
                ),
            ).fetchone()[0]
        return int(ahead) + 1

    def resource_queue_positions(self, task_ids: Iterable[str]) -> dict[str, int | None]:
        """Read at most 100 resource ranks in one statement's SQLite snapshot.

        Missing IDs raise KeyError; non-queued IDs map to None, like the scalar API.
        All projects remain part of each resource queue. No window SQL is required.
        """
        from itertools import islice

        values = list(islice(iter(task_ids), 101))
        if len(values) > 100:
            raise ValueError("resource queue positions accept at most 100 task IDs")
        ids = list(dict.fromkeys(str(value) for value in values))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with closing(self._connect()) as database:
            rows = database.execute(
                f"""
                SELECT t.task_id,
                       CASE WHEN t.status='QUEUED' THEN 1 + (
                           SELECT COUNT(*) FROM tasks AS peer
                            WHERE peer.status='QUEUED' AND peer.resource_key=t.resource_key
                              AND (
                                  peer.priority < t.priority
                                  OR (peer.priority=t.priority AND peer.queue_rank>t.queue_rank)
                                  OR (peer.priority=t.priority AND peer.queue_rank=t.queue_rank
                                      AND peer.created_at<t.created_at)
                                  OR (peer.priority=t.priority AND peer.queue_rank=t.queue_rank
                                      AND peer.created_at=t.created_at AND peer.task_id<t.task_id)
                              )
                       ) ELSE NULL END AS position
                  FROM tasks AS t WHERE t.task_id IN ({placeholders})
                """, ids,
            ).fetchall()
        positions = {str(row["task_id"]): row["position"] for row in rows}
        for task_id in ids:
            if task_id not in positions:
                raise KeyError(task_id)
        return {task_id: positions[task_id] for task_id in ids}

    def queued_candidates(self) -> tuple[TaskRecord, ...]:
        """Return the current durable claim-order candidates for read projections.

        This does not apply Worker capability or admission rules. Callers may use
        the rows to prove a narrower view, but must not treat them as a second
        Scheduler or mutate queue state from a GET path.
        """
        with closing(self._connect()) as database:
            rows = database.execute(
                """
                SELECT * FROM tasks
                 WHERE status='QUEUED'
                 ORDER BY priority ASC, queue_rank DESC, created_at ASC, task_id ASC
                """
            ).fetchall()
        return tuple(_from_row(row) for row in rows)

    def list(
        self,
        project_id: str | None = None,
        kinds: Iterable[TaskKind | str] | None = None,
        statuses: Iterable[TaskStatus | str] | None = None,
        limit: int = 50,
        cursor: str | None = None,
        annotation_query: str = "",
        task_query: str = "",
    ) -> TaskPage:
        bounded_limit = max(1, min(100, int(limit)))
        clauses: list[str] = []
        parameters: list[object] = []
        if project_id is not None:
            clauses.append("project_id=?")
            parameters.append(str(project_id))
        if kinds:
            values = [item.value if isinstance(item, TaskKind) else str(item) for item in kinds]
            clauses.append(f"kind IN ({','.join('?' for _ in values)})")
            parameters.extend(values)
        if statuses:
            values = [item.value if isinstance(item, TaskStatus) else str(item) for item in statuses]
            clauses.append(f"status IN ({','.join('?' for _ in values)})")
            parameters.extend(values)
        if annotation_query:
            escaped = (str(annotation_query).casefold().replace("\\", "\\\\")
                       .replace("%", "\\%").replace("_", "\\_"))
            pattern = f"%{escaped}%"
            clauses.append("(LOWER(task_id) LIKE ? ESCAPE '\\' OR "
                           "LOWER(COALESCE(annotation_name,'')) LIKE ? ESCAPE '\\' OR "
                           "LOWER(COALESCE(annotation_model_name,'')) LIKE ? ESCAPE '\\' OR "
                           "LOWER(COALESCE(annotation_model_id,'')) LIKE ? ESCAPE '\\')")
            parameters.extend([pattern] * 4)
        if task_query:
            escaped=str(task_query)[:120].lower().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            clauses.append("(LOWER(task_id) LIKE ? ESCAPE '\\' OR LOWER(stage) LIKE ? ESCAPE '\\')")
            parameters.extend(['%'+escaped+'%']*2)
        if cursor:
            created_at, task_id = _decode_cursor(cursor)
            clauses.append("(created_at < ? OR (created_at = ? AND task_id < ?))")
            parameters.extend([created_at, created_at, task_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as database:
            rows = database.execute(
                f"SELECT * FROM tasks {where} ORDER BY created_at DESC, task_id DESC LIMIT ?",
                (*parameters, bounded_limit + 1),
            ).fetchall()
        has_more = len(rows) > bounded_limit
        visible = rows[:bounded_limit]
        next_cursor = None
        if has_more and visible:
            next_cursor = _encode_cursor(visible[-1]["created_at"], visible[-1]["task_id"])
        return TaskPage(tuple(_from_row(row) for row in visible), next_cursor)

    def annotation_search_progress(self, project_id: str) -> dict[str, int]:
        """Index readiness is project-scoped; never return partial search as complete."""
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT COUNT(*) AS total, "
                "COALESCE(SUM(CASE WHEN annotation_search_ready=0 THEN 1 ELSE 0 END),0) AS pending, "
                "COALESCE(SUM(CASE WHEN annotation_search_ready=2 THEN 1 ELSE 0 END),0) AS failed "
                "FROM tasks WHERE project_id=? AND kind=?",
                (project_id, TaskKind.AI_ANNOTATION.value),
            ).fetchone()
        return {key: int(row[key]) for key in ("total", "pending", "failed")}

    @retry_busy
    def backfill_annotation_search_batch(self, project_id: str, artifacts=None, *, limit: int = 100) -> int:
        """Read at most one batch of legacy requests; never scan artifacts on list GET."""
        from .artifacts import ArtifactStore

        store = artifacts or ArtifactStore(self.path.parent / "artifacts")
        with closing(self._connect()) as database:
            rows = database.execute(
                "SELECT task_id,payload_ref FROM tasks "
                "WHERE project_id=? AND kind=? AND annotation_search_ready=0 "
                "ORDER BY created_at DESC,task_id DESC LIMIT ?",
                (project_id, TaskKind.AI_ANNOTATION.value, max(1, min(200, int(limit)))),
            ).fetchall()
        if not rows:
            return 0
        metadata = []
        for row in rows:
            try:
                request = store.read_json(str(row["task_id"]), str(row["payload_ref"]))
                if not isinstance(request, dict):
                    raise ValueError("missing or malformed task request")
                name, model, model_id = _annotation_search_fields(request)
                metadata.append((name, model, model_id, 1, row["task_id"], project_id))
            except (OSError, ValueError):
                metadata.append((None, None, None, 2, row["task_id"], project_id))
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            database.executemany(
                "UPDATE tasks SET annotation_name=?,annotation_model_name=?,annotation_model_id=?,"
                "annotation_search_ready=? WHERE task_id=? AND project_id=? AND annotation_search_ready=0",
                metadata,
            )
            database.commit()
        return len(rows)

    @retry_busy
    def retry_failed_annotation_search(self, project_id: str) -> int:
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            changed = database.execute(
                "UPDATE tasks SET annotation_search_ready=0 WHERE project_id=? AND kind=? "
                "AND annotation_search_ready=2",
                (project_id, TaskKind.AI_ANNOTATION.value),
            ).rowcount
            database.commit()
        return int(changed)

    def formal_bulk_execution_snapshot(self, task_id: str):
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT tasks.*, formal_bulk_execution.cancel_requested,
                          formal_bulk_execution.reconciliation
                     FROM tasks LEFT JOIN formal_bulk_execution USING (task_id)
                    WHERE task_id=? AND kind='ANNOTATION_FORMAL_BULK'""", (task_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            ledger = json.loads(row["reconciliation"] or "{}")
        except (TypeError, ValueError):
            ledger = {"state": "blocked", "committed_images_proven": False,
                      "blocked_code": "FORMAL_BULK_LEDGER_CORRUPT",
                      "blocked_reason": "持久对账证据无法解析"}
        if not isinstance(ledger, dict):
            ledger = {"state": "blocked", "committed_images_proven": False,
                      "blocked_code": "FORMAL_BULK_LEDGER_CORRUPT",
                      "blocked_reason": "持久对账证据格式不正确"}
        return _from_row(row), bool(row["cancel_requested"]), ledger

    def _formal_bulk_lock(self, task_id: str, *, timeout: float = 5) -> FileLock:
        path = self.path.resolve()
        identity = sha256(task_id.encode("utf-8")).hexdigest()
        return FileLock(str(path.with_name(f"{path.name}.formal-{identity}.lock")), timeout=timeout)

    def _formal_bulk_blocked(self, database, task_id: str):
        """Return the durable block ledger, or None when there is no block.

        An unparsable ledger is treated as a BLOCK, never as "no block":
        corrupted evidence must fail closed instead of triggering automatic
        re-claims.
        """
        row = database.execute(
            "SELECT reconciliation, cancel_requested FROM formal_bulk_execution WHERE task_id=?",
            (str(task_id),),
        ).fetchone()
        if row is None:
            return None
        try:
            ledger = json.loads(row["reconciliation"] or "{}")
        except (TypeError, ValueError):
            ledger = {"blocked_code": "FORMAL_BULK_LEDGER_CORRUPT",
                      "blocked_reason": "持久对账证据无法解析"}
        if not isinstance(ledger, dict):
            ledger = {"blocked_code": "FORMAL_BULK_LEDGER_CORRUPT",
                      "blocked_reason": "持久对账证据格式不正确"}
        if ledger.get("state") != "blocked" and ledger.get("blocked_code") != "FORMAL_BULK_LEDGER_CORRUPT":
            return None
        ledger = dict(ledger)
        ledger["state"] = "blocked"
        ledger["_cancel_requested"] = bool(row["cancel_requested"])
        return ledger

    def _requeue_expired_formal_bulk(self, database, row, now: str) -> int:
        task_id = row["task_id"]
        attempt = int(row["attempt"] or 0)
        # A durable evidence block must never be undone by the automatic
        # reaper, otherwise a permanent conflict would be re-claimed forever.
        # Exception: a cancelled blocked execution still needs the Worker's
        # read-only cancellation reconciliation, so it may be requeued without
        # clearing the block marker, strictly bounded by the attempt cap.
        blocked = self._formal_bulk_blocked(database, task_id)
        if blocked is not None:
            corrupt = str(blocked.get("blocked_code") or "") == "FORMAL_BULK_LEDGER_CORRUPT"
            if (blocked.get("_cancel_requested") and not corrupt
                    and attempt < MAX_FORMAL_BULK_ATTEMPTS):
                try:
                    with self._formal_bulk_lock(task_id, timeout=0):
                        return database.execute(
                            """UPDATE tasks SET status='QUEUED', stage='cancel_reconcile_queued',
                                   worker_id=NULL, lease_token=NULL, lease_expires_at=NULL, updated_at=?
                                 WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED')
                                   AND lease_expires_at<=?""",
                            (now, task_id, now),
                        ).rowcount
                except Timeout:
                    return 0
            database.execute(
                "UPDATE tasks SET stage=?, updated_at=? "
                "WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED')",
                ("formal_bulk_attempt_limit" if attempt >= MAX_FORMAL_BULK_ATTEMPTS
                 else "formal_bulk_blocked", now, task_id),
            )
            return 0
        if attempt >= MAX_FORMAL_BULK_ATTEMPTS:
            database.execute(
                """INSERT INTO formal_bulk_execution(task_id, reconciliation) VALUES (?,?)
                   ON CONFLICT(task_id) DO UPDATE SET reconciliation=excluded.reconciliation""",
                (task_id, json.dumps({
                    "state": "blocked",
                    "committed_images_proven": False,
                    "blocked_code": "FORMAL_BULK_ATTEMPT_LIMIT",
                    "blocked_reason": f"自动重领达到上限 {MAX_FORMAL_BULK_ATTEMPTS}，需要人工核验",
                    "blocked_at": now,
                }, sort_keys=True)),
            )
            database.execute(
                "UPDATE tasks SET stage='formal_bulk_attempt_limit', updated_at=? "
                "WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED')",
                (now, task_id),
            )
            return 0
        # The caller holds the SQLite writer. Never wait for a per-task lock here:
        # the GT owner takes that lock before starting its short validation txn.
        try:
            with self._formal_bulk_lock(task_id, timeout=0):
                return database.execute(
                    """UPDATE tasks SET status='QUEUED', stage='recovered', worker_id=NULL,
                           lease_token=NULL, lease_expires_at=NULL, updated_at=?
                         WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED')
                           AND lease_expires_at<=?""",
                    (now, task_id, now),
                ).rowcount
        except Timeout:
            return 0

    def resume_blocked_formal_bulk(self, task_id: str, expected_attempt: int) -> None:
        """Release a durable evidence block after an operator re-verified facts.

        This never publishes SUCCEEDED and never writes GT. It only moves the
        task back to QUEUED so the normal Worker re-audits the same operation.
        Kept on the base repository because the HTTP control plane uses the
        plain ``TaskRepository``.
        """
        task_id = str(task_id)
        with self._formal_bulk_lock(task_id), closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT kind, status, attempt FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            if row is None or str(row["kind"]) != TaskKind.ANNOTATION_FORMAL_BULK.value:
                raise KeyError(task_id)
            if (str(row["status"]) not in {"RUNNING", "CANCEL_REQUESTED"}
                    or int(row["attempt"]) != int(expected_attempt)):
                raise PermissionError("formal bulk task is not in a recoverable blocked state")
            ledger = database.execute(
                "SELECT reconciliation FROM formal_bulk_execution WHERE task_id=?", (task_id,),
            ).fetchone()
            try:
                evidence = json.loads(ledger["reconciliation"] or "{}") if ledger is not None else {}
            except (TypeError, ValueError) as error:
                raise PermissionError("formal bulk block ledger is corrupt") from error
            if not isinstance(evidence, dict) or evidence.get("state") != "blocked":
                raise PermissionError("formal bulk block marker is missing")
            if str(evidence.get("blocked_code") or "") == "FORMAL_BULK_LEDGER_CORRUPT":
                raise PermissionError("formal bulk block ledger is corrupt")
            evidence.update(state="resumed", resumed_at=utc_now())
            now = utc_now()
            database.execute(
                "UPDATE formal_bulk_execution SET reconciliation=? WHERE task_id=?",
                (json.dumps(evidence, sort_keys=True), task_id),
            )
            database.execute(
                """UPDATE tasks SET status='QUEUED', stage='recovery_queued',
                          worker_id=NULL, lease_token=NULL, lease_expires_at=NULL,
                          process_pid=NULL, process_create_time=NULL, process_command_hash=NULL,
                          updated_at=?
                    WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED') AND attempt=?""",
                (now, task_id, int(expected_attempt)),
            )
            database.commit()

    def _release_expired_in(self, database: sqlite3.Connection, now: str) -> int:
        # Lease expiry fences writes but cannot prove a remote Agent stopped
        # computing after a network partition. Keep its durable owner until
        # remote process death has been independently verified.
        database.execute(
            """
            UPDATE tasks
               SET stage='recovery_blocked_remote_agent_unverified',
                   resource_wait_reason='REMOTE_AGENT_STOP_UNVERIFIED: remote execution may still be running',
                   updated_at=?
             WHERE status IN ('RUNNING','CANCEL_REQUESTED')
               AND worker_id LIKE 'agent:%'
               AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
               AND stage<>'recovery_blocked_remote_agent_unverified'
            """,
            (now, now),
        )
        count = database.execute(
            """
            UPDATE tasks
               SET status=CASE WHEN status='CANCEL_REQUESTED' THEN 'CANCELLED' ELSE 'QUEUED' END,
                   stage=CASE
                       WHEN status='CANCEL_REQUESTED' THEN 'cancelled'
                       WHEN kind='MATERIAL_IMPORT' AND accepted=1 AND stage='indexing'
                           THEN 'indexing_queued'
                       ELSE 'recovered'
                   END,
                   finished_at=CASE WHEN status='CANCEL_REQUESTED' THEN ? ELSE finished_at END,
                   worker_id=NULL,
                   lease_token=NULL, lease_expires_at=NULL, updated_at=?
             WHERE status IN ('RUNNING','CANCEL_REQUESTED')
               AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
               AND (worker_id IS NULL OR worker_id NOT LIKE 'agent:%')
               AND kind<>'ANNOTATION_FORMAL_BULK'
            """,
            (now, now, now),
        ).rowcount
        # Retain GPU evidence for unverified remote owners. The fenced
        # repository additionally extends held reservations exclusively.
        database.execute(
            """
            DELETE FROM gpu_reservations
             WHERE expires_at<=?
               AND task_id NOT IN (
                   SELECT task_id FROM tasks
                    WHERE status IN ('RUNNING','CANCEL_REQUESTED')
                      AND stage='recovery_blocked_remote_agent_unverified'
               )
            """,
            (now,),
        )
        for row in database.execute(
            """SELECT task_id FROM tasks WHERE kind='ANNOTATION_FORMAL_BULK'
                 AND status IN ('RUNNING','CANCEL_REQUESTED') AND lease_expires_at<=?
                 AND (worker_id IS NULL OR worker_id NOT LIKE 'agent:%') AND process_pid IS NULL""", (now,),
        ).fetchall():
            count += self._requeue_expired_formal_bulk(database, row, now)
        return count

    def is_deleted(self, task_id, *, project_id=None):
        with closing(self._connect()) as database:
            row=database.execute('SELECT project_id FROM task_tombstones WHERE task_id=?',(str(task_id),)).fetchone()
        return row is not None and (project_id is None or row['project_id']==str(project_id))

    def deleted_task_identity(self, task_id):
        """Explicit audit lookup; never returned as a schedulable current Task."""
        with closing(self._connect()) as database:
            row=database.execute('SELECT task_id,project_id,kind,payload_ref,attempt FROM task_tombstones WHERE task_id=?',
                                 (str(task_id),)).fetchone()
        return dict(row) if row is not None else None

    def deleted_task_ids(self, task_ids, *, project_id):
        identities=list(dict.fromkeys(str(value) for value in task_ids))
        result=set()
        with closing(self._connect()) as database:
            for start in range(0,len(identities),500):
                batch=identities[start:start+500]
                placeholders=','.join('?' for _ in batch)
                result.update(str(row[0]) for row in database.execute(
                    f'SELECT task_id FROM task_tombstones WHERE project_id=? AND task_id IN ({placeholders})',
                    (str(project_id),*batch)))
        return result

    def record_legacy_deletion(self, task_id, project_id):
        with closing(self._connect()) as database:
            database.execute('BEGIN IMMEDIATE')
            if database.execute('SELECT 1 FROM tasks WHERE task_id=?',(str(task_id),)).fetchone():
                raise ValueError('task appeared during legacy deletion; reload its state')
            database.execute("INSERT OR IGNORE INTO task_tombstones(task_id,project_id,kind,deleted_at) VALUES (?,?,'TRAINING',?)",
                (str(task_id),str(project_id),utc_now()))
            row=database.execute('SELECT project_id FROM task_tombstones WHERE task_id=?',(str(task_id),)).fetchone()
            if row['project_id']!=str(project_id):
                raise ValueError('task project mismatch')
            database.commit()

    def delete_terminal(
        self,
        task_id: str,
        *,
        project_id: str | None = None,
        kind: TaskKind | str | None = None,
    ) -> bool:
        """Permanently delete one terminal durable task.

        This is intentionally stricter than cancellation. Active/queued/review
        tasks must never disappear from durable truth through a cleanup API.
        """
        expected_kind = kind.value if isinstance(kind, TaskKind) else (str(kind) if kind is not None else None)
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                return False
            if project_id is not None and str(row["project_id"]) != str(project_id):
                database.rollback()
                raise ValueError("task project mismatch")
            if expected_kind is not None and str(row["kind"]) != expected_kind:
                database.rollback()
                raise ValueError("task kind mismatch")
            status = TaskStatus(str(row["status"]))
            if status not in TERMINAL_STATUSES:
                database.rollback()
                raise ValueError("only terminal tasks can be deleted")
            database.execute("INSERT INTO task_tombstones(task_id,project_id,kind,payload_ref,attempt,deleted_at,task_json) VALUES (?,?,?,?,?,?,?)",
                (row['task_id'],row['project_id'],row['kind'],row['payload_ref'],row['attempt'],utc_now(),json.dumps(dict(row))))
            database.execute("DELETE FROM gpu_reservations WHERE task_id=?", (str(task_id),))
            changed = database.execute(
                "DELETE FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).rowcount
            database.commit()
        return changed == 1

    @retry_busy
    def release_expired(self, now: datetime | str | None = None) -> int:
        now_text = _iso(now)
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            count = self._release_expired_in(database, now_text)
            database.commit()
        return count

    @retry_busy
    def claim_next(self, worker_id: str, kinds: Iterable[TaskKind | str], capabilities: Iterable[str],
                   lease_seconds: int = 30, admission=None, *, candidate_budget: int = 256) -> TaskLease | None:
        kind_values=tuple(item.value if isinstance(item,TaskKind) else str(item) for item in kinds)
        if not kind_values:
            return None
        available=set(capabilities)
        context_key=(str(worker_id),kind_values,tuple(sorted(available)))
        with self._claim_cursor_lock:
            cursor=self._claim_cursors.get(context_key)
        prepare=admission_preparer(admission)
        # No writer lock, artifact I/O or payload preparation in this connection.
        with closing(self._connect()) as reader:
            candidates,next_cursor=prepare_candidates(reader,kind_values,available,prepare,cursor,
                                                      utc_now(),candidate_budget)
        token=uuid.uuid4().hex
        claimed=None
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            now=datetime.now(timezone.utc)
            now_text=now.isoformat()
            expires_at=(now+timedelta(seconds=max(1,int(lease_seconds)))).isoformat()
            self._release_expired_in(database,now_text)
            for candidate,prepared in candidates:
                current = database.execute("SELECT * FROM tasks WHERE task_id=? AND status='QUEUED'", (candidate["task_id"],)).fetchone()
                if current is None or any(current[key] != candidate[key] for key in (
                    *SEMANTIC_FIELDS,
                )):
                    continue
                delegated = admission is not None and current["kind"] == "TRAINING" and not str(current["resource_key"]).startswith("training:remote:")
                # A delegated local training admission policy may reason about
                # GPU capacity, but it cannot overrule an unverified remote
                # execution's still-owned resource key.
                if delegated and database.execute(
                    """SELECT 1 FROM tasks WHERE resource_key=?
                         AND status IN ('RUNNING','CANCEL_REQUESTED')
                         AND stage='recovery_blocked_remote_agent_unverified'
                         LIMIT 1""",
                    (current["resource_key"],),
                ).fetchone():
                    continue
                if not delegated and database.execute(
                    """SELECT 1 FROM tasks WHERE resource_key=?
                         AND status IN ('RUNNING','CANCEL_REQUESTED')
                         AND (lease_expires_at>?
                              OR stage='recovery_blocked_remote_agent_unverified')
                         LIMIT 1""",
                    (current["resource_key"], now_text),
                ).fetchone():
                    continue
                admitted = dict(current)
                if callable(prepare):
                    admitted["_gpu_payload_prepared"] = True
                    admitted["_gpu_payload"] = prepared
                if admission is not None:
                    allowed, reason = admission(database, admitted, worker_id, token, expires_at, now_text)
                    if not allowed:
                        database.execute("UPDATE tasks SET stage='resource_waiting', resource_wait_reason=?, updated_at=? "
                                         "WHERE task_id=? AND (stage<>'resource_waiting' OR resource_wait_reason IS NOT ?)",
                                         (reason, now_text, candidate["task_id"], reason))
                        continue
                changed = database.execute(
                    """
                    UPDATE tasks
                       SET status='RUNNING',
                           stage=CASE
                               WHEN kind='MATERIAL_IMPORT' AND accepted=1 AND stage='indexing_queued'
                                   THEN 'indexing'
                               ELSE 'running'
                           END,
                           worker_id=?, lease_token=?,
                           lease_expires_at=?, attempt=attempt+1, updated_at=?, finished_at=NULL, resource_wait_reason=NULL
                     WHERE task_id=? AND status='QUEUED'
                    """,
                    (worker_id, token, expires_at, now_text, current["task_id"]),
                ).rowcount
                if changed != 1:
                    continue
                row = database.execute(
                    "SELECT * FROM tasks WHERE task_id=?",
                    (current["task_id"],),
                ).fetchone()
                claimed = (row, expires_at, candidate_key(candidate))
                break
            database.commit()
        with self._claim_cursor_lock:
            self._claim_cursors[context_key]=claimed[2] if claimed else next_cursor
        if claimed:
            return TaskLease(_from_row(claimed[0]),token,str(worker_id),claimed[1])
        return None

    def heartbeat(
        self,
        task_id: str,
        lease_token: str,
        progress=None,
        stage=None,
        current_item=None,
    ) -> TaskRecord:
        updates = ["updated_at=?", "lease_expires_at=?"]
        now = datetime.now(timezone.utc)
        parameters: list[object] = [now.isoformat(), (now + timedelta(seconds=30)).isoformat()]
        if progress is not None:
            updates.append("progress=MAX(progress, ?)")
            parameters.append(max(0.0, min(100.0, float(progress))))
        if stage is not None:
            stage_value = str(stage)
            updates.append(
                "stage=CASE WHEN stage IN ('paused','cancelling') AND stage<>? "
                "THEN stage ELSE ? END"
            )
            parameters.extend([stage_value, stage_value])
        if current_item is not None:
            updates.append("current_item=?")
            parameters.append(str(current_item))
        # Generic local Worker heartbeat remains backward compatible, but a
        # remote Agent may never refresh an expired execution or overwrite an
        # unverified-stop safety hold. HTTP Agents normally use the stricter
        # FencedTaskRepository; this closes the plain repository bypass.
        parameters.extend([str(task_id), str(lease_token), now.isoformat()])
        with closing(self._connect()) as database:
            changed = database.execute(
                f"UPDATE tasks SET {','.join(updates)} "
                """WHERE task_id=? AND lease_token=?
                     AND status IN ('RUNNING','CANCEL_REQUESTED')
                     AND (
                         worker_id IS NULL OR worker_id NOT LIKE 'agent:%'
                         OR (
                             lease_expires_at IS NOT NULL
                             AND lease_expires_at>?
                             AND stage<>'recovery_blocked_remote_agent_unverified'
                         )
                     )""",
                parameters,
            ).rowcount
        if changed != 1:
            raise PermissionError("task lease does not own heartbeat")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def bind_process(
        self,
        task_id: str,
        lease_token: str,
        identity: ProcessIdentity,
    ) -> TaskRecord:
        now = utc_now()
        with closing(self._connect()) as database:
            changed = database.execute(
                """
                UPDATE tasks SET process_pid=?, process_create_time=?,
                    process_command_hash=?, updated_at=?
                 WHERE task_id=? AND lease_token=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                """,
                (
                    int(identity.pid),
                    float(identity.create_time),
                    str(identity.command_hash),
                    now,
                    str(task_id),
                    str(lease_token),
                ),
            ).rowcount
        if changed != 1:
            raise PermissionError("task lease does not own process identity")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def set_stage(self, task_id: str, stage: str) -> TaskRecord:
        value = str(stage or "").strip()
        if not value:
            raise ValueError("task stage cannot be empty")
        now = utc_now()
        with closing(self._connect()) as database:
            changed = database.execute(
                """UPDATE tasks SET stage=?, updated_at=?
                     WHERE task_id=? AND status='RUNNING'
                       AND stage<>'recovery_blocked_remote_agent_unverified'""",
                (value, now, str(task_id)),
            ).rowcount
        if changed != 1:
            raise ValueError("only running tasks can change stage")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def activate_prepared_training(
        self,
        task_id: str,
        *,
        resource_key: str,
        required_capabilities: tuple[str, ...],
        preparation_task_id: str | None = None,
        preparation_lease_token: str | None = None,
        preparation_execution_generation: int | None = None,
    ) -> TaskRecord:
        """Release one prepared TRAINING parent to the canonical scheduler.

        TRAINING parents are admitted durably before their input contract is
        frozen.  Until the TRAINING_PREPARE child succeeds they deliberately
        advertise an unclaimable capability.  This transition is the single
        fence that makes the parent claimable without creating a second task.
        """
        now = utc_now()
        capabilities_json = json.dumps(
            list(tuple(sorted(set(required_capabilities)))),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            self._assert_preparation_execution_owner(
                database,
                preparation_task_id=preparation_task_id,
                preparation_lease_token=preparation_lease_token,
                preparation_execution_generation=preparation_execution_generation,
                now=now,
            )
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            if current.kind is not TaskKind.TRAINING:
                database.rollback()
                raise ValueError("only TRAINING tasks can be activated after preparation")
            self._reject_legacy_payload_mutation(current.payload_ref)
            if current.status is not TaskStatus.QUEUED:
                database.rollback()
                raise ValueError("training task is no longer queued")
            database.execute(
                """
                UPDATE tasks
                   SET resource_key=?, required_capabilities=?, stage='queued',
                       progress=MAX(progress, 1.0), current_item=NULL,
                       resource_wait_reason=NULL, updated_at=?
                 WHERE task_id=? AND status='QUEUED'
                """,
                (str(resource_key), capabilities_json, now, str(task_id)),
            )
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            database.commit()
        return _from_row(row)

    @staticmethod
    def _assert_preparation_execution_owner(
        database,
        *,
        preparation_task_id: str | None,
        preparation_lease_token: str | None,
        preparation_execution_generation: int | None,
        now: str,
    ) -> None:
        """Fence a parent mutation to one live TRAINING_PREPARE generation.

        The check runs in the same IMMEDIATE transaction as the parent update,
        so a reclaimed preparation task cannot race a stale Worker between the
        ownership check and publication.
        """
        supplied = (
            preparation_task_id is not None,
            preparation_lease_token is not None,
            preparation_execution_generation is not None,
        )
        if not any(supplied):
            return
        if not all(supplied):
            raise ValueError("preparation execution owner requires task, lease and generation")
        row = database.execute(
            "SELECT kind, status, lease_token, lease_expires_at, attempt FROM tasks WHERE task_id=?",
            (str(preparation_task_id),),
        ).fetchone()
        owned = (
            row is not None
            and str(row["kind"]) == TaskKind.TRAINING_PREPARE.value
            and str(row["status"]) == TaskStatus.RUNNING.value
            and str(row["lease_token"] or "") == str(preparation_lease_token)
            and int(row["attempt"]) == int(preparation_execution_generation)
            and bool(row["lease_expires_at"])
            and str(row["lease_expires_at"]) > str(now)
        )
        if not owned:
            raise PermissionError("preparation execution does not own parent mutation")

    def begin_finalization(
        self,
        task_id: str,
        lease_token: str,
        *,
        execution_generation: int | None = None,
    ) -> TaskRecord:
        """Atomically choose successful commit over a competing cancellation.

        A cancellation already persisted as ``CANCEL_REQUESTED`` wins. Once the
        owned execution enters ``finalizing_commit``, later stop requests are
        rejected so a committed algorithm version can never belong to a task
        subsequently published as cancelled.
        """
        now = utc_now()
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            if current.status is TaskStatus.CANCEL_REQUESTED:
                database.rollback()
                raise InterruptedError("task cancellation won before finalization")
            owned = (
                current.status is TaskStatus.RUNNING
                and str(row["lease_token"] or "") == str(lease_token)
                and (
                    execution_generation is None
                    or int(row["attempt"]) == int(execution_generation)
                )
            )
            if owned and str(row["worker_id"] or "").startswith("agent:") and (
                not row["lease_expires_at"]
                or str(row["lease_expires_at"]) <= now
                or current.stage == "recovery_blocked_remote_agent_unverified"
            ):
                owned = False
            if not owned:
                database.rollback()
                raise PermissionError("task execution does not own finalization")
            if execution_generation is not None and (
                not row["lease_expires_at"] or str(row["lease_expires_at"]) <= now
            ):
                database.rollback()
                raise PermissionError("task execution lease expired before finalization")
            if current.stage != "finalizing_commit":
                database.execute(
                    """
                    UPDATE tasks SET stage='finalizing_commit',
                        current_item='训练已完成，正在归档已验证产物',
                        updated_at=? WHERE task_id=?
                    """,
                    (now, str(task_id)),
                )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def promote(self, task_id: str) -> TaskRecord:
        now = utc_now()
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT status, resource_key FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            if str(row["status"]) != TaskStatus.QUEUED.value:
                database.rollback()
                raise ValueError("only queued tasks can be promoted")
            peers = database.execute(
                "SELECT MIN(priority), MAX(queue_rank) FROM tasks WHERE resource_key=? AND status='QUEUED'",
                (str(row["resource_key"]),),
            ).fetchone()
            minimum = int(peers[0] if peers and peers[0] is not None else 50)
            maximum_rank = int(peers[1] if peers and peers[1] is not None else 0)
            priority = max(1, minimum - 1)
            rank = maximum_rank + 1 if priority == minimum else 0
            database.execute(
                "UPDATE tasks SET priority=?, queue_rank=?, updated_at=? WHERE task_id=?",
                (priority, rank, now, str(task_id)),
            )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def request_cancel(self, task_id: str) -> TaskRecord:
        result = self._request_cancel(task_id)
        if result is not None:
            return result
        with self._formal_bulk_lock(str(task_id)):
            return self._request_cancel(task_id, formal_bulk_locked=True)

    def _request_cancel(self, task_id: str, *, formal_bulk_locked: bool = False) -> TaskRecord | None:
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                """SELECT t.status, t.stage, t.kind, t.attempt, f.active_batch
                     FROM tasks t LEFT JOIN formal_bulk_execution f USING (task_id)
                    WHERE t.task_id=?""",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            if row["kind"] == TaskKind.ANNOTATION_FORMAL_BULK.value and not formal_bulk_locked:
                database.rollback()
                return None
            now = utc_now()
            status = TaskStatus(row["status"])
            if status is TaskStatus.RUNNING and str(row["stage"]) == "finalizing_commit":
                database.rollback()
                raise ValueError("训练已完成并正在归档，无法再停止")
            if row["kind"] == TaskKind.ANNOTATION_FORMAL_BULK.value:
                if (status is TaskStatus.QUEUED and int(row["attempt"] or 0) == 0
                        and row["active_batch"] is None):
                    # Never claimed and never admitted to the GT barrier: no
                    # worker can have written GT for this execution, so the
                    # zero-write cancellation is provable without a Worker.
                    evidence = {
                        "state": "cancelled",
                        "committed_images": 0,
                        "committed_images_proven": True,
                        "completed_batches": 0,
                        "cancelled_at": now,
                        "zero_gt_proof": "queued_attempt_zero_no_active_batch",
                    }
                    database.execute(
                        """INSERT INTO formal_bulk_execution(task_id, cancel_requested, reconciliation)
                           VALUES (?,1,?)
                           ON CONFLICT(task_id) DO UPDATE SET cancel_requested=1,
                               reconciliation=excluded.reconciliation""",
                        (str(task_id), json.dumps(evidence, sort_keys=True)),
                    )
                    database.execute(
                        """UPDATE tasks SET status='CANCELLED', stage='cancelled', finished_at=?,
                               updated_at=?, progress=0.0, worker_id=NULL, lease_token=NULL,
                               lease_expires_at=NULL WHERE task_id=?""",
                        (now, now, str(task_id)),
                    )
                elif status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
                    database.execute(
                        """INSERT INTO formal_bulk_execution(task_id, cancel_requested) VALUES (?,1)
                           ON CONFLICT(task_id) DO UPDATE SET cancel_requested=1""", (str(task_id),),
                    )
                    database.execute(
                        """UPDATE tasks SET status=CASE WHEN status='RUNNING' THEN 'CANCEL_REQUESTED'
                                                       ELSE status END, stage='cancelling', updated_at=?
                             WHERE task_id=?""", (now, str(task_id)),
                    )
            elif status is TaskStatus.QUEUED or status is TaskStatus.AWAITING_CONFIRMATION:
                database.execute(
                    """
                    UPDATE tasks SET status='CANCELLED', stage='cancelled', accepted=COALESCE(accepted,0),
                        finished_at=?, updated_at=?, worker_id=NULL, lease_token=NULL,
                        lease_expires_at=NULL WHERE task_id=?
                    """,
                    (now, now, str(task_id)),
                )
            elif status is TaskStatus.RUNNING:
                database.execute(
                    """UPDATE tasks
                          SET status='CANCEL_REQUESTED',
                              stage=CASE
                                  WHEN stage='recovery_blocked_remote_agent_unverified'
                                      THEN stage
                                  ELSE 'cancelling'
                              END,
                              updated_at=?
                        WHERE task_id=?""",
                    (now, str(task_id)),
                )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def settle_stranded_training_preparations(self, *, limit: int = 20) -> int:
        """Settle unclaimable parents whose preparation child has finished.

        This runs in the original Worker maintenance loop. The joined state is
        rechecked under a write transaction, so an in-flight activation or
        cancellation cannot be overwritten by a stale read.
        """
        now = utc_now()
        with closing(self._connect()) as database:
            rows = database.execute(
                """
                SELECT parent.task_id, child.status AS child_status, child.error AS child_error
                  FROM tasks AS parent
                  JOIN tasks AS child ON child.task_id='trainprep_' || parent.task_id
                   AND child.kind='TRAINING_PREPARE' AND child.project_id=parent.project_id
                 WHERE parent.kind='TRAINING' AND parent.status='QUEUED'
                   AND parent.required_capabilities='["training.input.ready"]'
                   AND child.status IN ('SUCCEEDED','FAILED','CANCELLED',
                       'BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE')
                 ORDER BY parent.created_at ASC LIMIT ?
                """,
                (max(1, min(50, int(limit))),),
            ).fetchall()
            if not rows:
                return 0
            database.execute("BEGIN IMMEDIATE")
            settled = 0
            for row in rows:
                cancelled = row["child_status"] == "CANCELLED"
                status = (
                    "CANCELLED" if cancelled else
                    row["child_status"] if row["child_status"] in {
                        "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE",
                    } else "FAILED"
                )
                reason = (
                    "TRAINING_PREPARATION_CANCELLED: 训练输入准备已取消"
                    if cancelled else
                    "TRAINING_PREPARATION_INCOMPLETE: 准备子任务已结束但训练未就绪；"
                    + str(row["child_error"] or row["child_status"] or "")[:400]
                )
                settled += database.execute(
                    """UPDATE tasks SET status=?,stage=?,error=?,finished_at=?,updated_at=?
                       WHERE task_id=? AND status='QUEUED'
                         AND required_capabilities='["training.input.ready"]'
                         AND EXISTS (SELECT 1 FROM tasks AS child
                            WHERE child.task_id='trainprep_' || tasks.task_id
                              AND child.project_id=tasks.project_id
                              AND child.kind='TRAINING_PREPARE' AND child.status=?)""",
                    (status, "cancelled" if cancelled else "training_input_preparation_failed",
                     reason, now, now, row["task_id"], row["child_status"]),
                ).rowcount
            database.commit()
        return settled

    def fail_queued_precondition(
        self,
        task_id: str,
        error: str,
        *,
        status: TaskStatus = TaskStatus.BLOCKED_BY_ENVIRONMENT,
        stage: str = "precondition_failed",
        preparation_task_id: str | None = None,
        preparation_lease_token: str | None = None,
        preparation_execution_generation: int | None = None,
    ) -> TaskRecord:
        """Fail a task that never acquired an execution lease.

        This is intentionally limited to QUEUED tasks so a preparation worker
        cannot overwrite a RUNNING/CANCELLED execution owned elsewhere.
        """
        if status not in {
            TaskStatus.FAILED,
            TaskStatus.BLOCKED_BY_ENVIRONMENT,
            TaskStatus.BLOCKED_BY_HARDWARE,
        }:
            raise ValueError("queued precondition failure requires a terminal failure status")
        now = utc_now()
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            self._assert_preparation_execution_owner(
                database,
                preparation_task_id=preparation_task_id,
                preparation_lease_token=preparation_lease_token,
                preparation_execution_generation=preparation_execution_generation,
                now=now,
            )
            changed = database.execute(
                """
                UPDATE tasks
                   SET status=?, stage=?, error=?, finished_at=?, updated_at=?,
                       worker_id=NULL, lease_token=NULL, lease_expires_at=NULL
                 WHERE task_id=? AND status='QUEUED' AND kind<>'ANNOTATION_FORMAL_BULK'
                """,
                (
                    status.value,
                    str(stage or "precondition_failed"),
                    str(error or "")[:8000],
                    now,
                    now,
                    str(task_id),
                ),
            ).rowcount
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            database.commit()
        if row is None:
            raise KeyError(task_id)
        result = _from_row(row)
        if changed != 1 and result.status is TaskStatus.QUEUED:
            raise RuntimeError("queued task precondition state changed concurrently")
        return result

    def finish(
        self,
        task_id: str,
        lease_token: str,
        status: TaskStatus,
        result_ref: str | None = None,
        error: str | None = None,
        accepted: bool | None = None,
    ) -> TaskRecord:
        if status not in TERMINAL_STATUSES | {TaskStatus.AWAITING_CONFIRMATION}:
            raise ValueError("invalid worker finish status")
        now = utc_now()
        finished_at = None if status is TaskStatus.AWAITING_CONFIRMATION else now
        stage = "awaiting_confirmation" if status is TaskStatus.AWAITING_CONFIRMATION else status.value.lower()
        progress = 100.0 if status in {
            TaskStatus.AWAITING_CONFIRMATION,
            TaskStatus.PARTIAL_SUCCESS,
            TaskStatus.SUCCEEDED,
        } else None
        with closing(self._connect()) as database:
            changed = database.execute(
                """
                UPDATE tasks SET status=?, result_ref=?, error=?, accepted=?, stage=?,
                    progress=CASE
                        WHEN ?='AWAITING_CONFIRMATION' AND (
                            kind='AI_ANNOTATION'
                            OR (kind='MATERIAL_BATCH' AND stage='AI_ANNOTATION')
                        ) THEN MAX(progress, 70.0)
                        WHEN ?='AWAITING_CONFIRMATION' AND kind='MATERIAL_IMPORT'
                            THEN MAX(progress, 50.0)
                        ELSE COALESCE(?, progress)
                    END,
                    finished_at=?, updated_at=?,
                    worker_id=NULL, lease_token=NULL, lease_expires_at=NULL
                 WHERE task_id=? AND lease_token=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                   AND kind<>'ANNOTATION_FORMAL_BULK'
                   AND (
                       worker_id IS NULL OR worker_id NOT LIKE 'agent:%'
                       OR (
                           lease_expires_at IS NOT NULL
                           AND lease_expires_at>?
                           AND stage<>'recovery_blocked_remote_agent_unverified'
                       )
                   )
                """,
                (
                    status.value,
                    result_ref,
                    error,
                    None if accepted is None else int(accepted),
                    stage,
                    status.value,
                    status.value,
                    progress,
                    finished_at,
                    now,
                    str(task_id),
                    str(lease_token),
                    now,
                ),
            ).rowcount
        if changed != 1:
            raise PermissionError("task lease does not own finish")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def complete_review(
        self,
        task_id: str,
        status: TaskStatus,
        result_ref: str,
        accepted: bool,
        error: str | None = None,
    ) -> TaskRecord:
        if status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
            raise ValueError("review must finish as success or partial success")
        now = utc_now()
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            if current.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
                if (
                    current.status is status
                    and current.result_ref == result_ref
                    and current.accepted is bool(accepted)
                    and current.error == error
                ):
                    database.commit()
                    return current
                database.rollback()
                raise ValueError("conflicting review completion")
            if current.status is not TaskStatus.AWAITING_CONFIRMATION:
                database.rollback()
                raise ValueError("task is not awaiting confirmation")
            database.execute(
                """
                UPDATE tasks SET status=?, result_ref=?, accepted=?, error=?, progress=100,
                    stage=?, finished_at=?, updated_at=? WHERE task_id=?
                """,
                (
                    status.value,
                    result_ref,
                    int(accepted),
                    error,
                    status.value.lower(),
                    now,
                    now,
                    str(task_id),
                ),
            )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def resume_after_confirmation(
        self,
        task_id: str,
        *,
        required_capabilities: tuple[str, ...] | None = None,
    ) -> TaskRecord:
        now = utc_now()
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            if current.kind is not TaskKind.MATERIAL_IMPORT:
                database.rollback()
                raise ValueError("only material import tasks can resume after confirmation")
            if current.accepted is False:
                database.rollback()
                raise ValueError("task cannot resume after confirmation")
            if current.status is TaskStatus.AWAITING_CONFIRMATION:
                capabilities_json = (
                    json.dumps(
                        list(required_capabilities),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    if required_capabilities is not None
                    else json.dumps(
                        list(current.required_capabilities),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                database.execute(
                    """
                    UPDATE tasks SET status='QUEUED', stage='indexing_queued', progress=MAX(progress, 50.0),
                        current_item=NULL, error=NULL, accepted=1, finished_at=NULL,
                        required_capabilities=?, updated_at=?, worker_id=NULL,
                        lease_token=NULL, lease_expires_at=NULL
                     WHERE task_id=? AND status='AWAITING_CONFIRMATION'
                    """,
                    (capabilities_json, now, str(task_id)),
                )
                row = database.execute(
                    "SELECT * FROM tasks WHERE task_id=?",
                    (str(task_id),),
                ).fetchone()
                database.commit()
                return _from_row(row)
            if current.accepted is True and (
                (current.status is TaskStatus.QUEUED and current.stage == "indexing_queued")
                or (current.status is TaskStatus.RUNNING and current.stage == "indexing")
                or current.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}
            ):
                if (
                    required_capabilities is not None
                    and current.status is TaskStatus.QUEUED
                    and current.stage == "indexing_queued"
                    and tuple(current.required_capabilities) != tuple(required_capabilities)
                ):
                    capabilities_json = json.dumps(
                        list(required_capabilities),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    database.execute(
                        """
                        UPDATE tasks SET required_capabilities=?, updated_at=?
                         WHERE task_id=? AND status='QUEUED' AND stage='indexing_queued'
                        """,
                        (capabilities_json, now, str(task_id)),
                    )
                    row = database.execute(
                        "SELECT * FROM tasks WHERE task_id=?",
                        (str(task_id),),
                    ).fetchone()
                    database.commit()
                    return _from_row(row)
                database.commit()
                return current
            database.rollback()
            raise ValueError("task cannot resume after confirmation")

    def resume_after_review_confirmation(
        self,
        task_id: str,
        *,
        required_capabilities: tuple[str, ...] | None = None,
    ) -> TaskRecord:
        now = utc_now()
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            if current.kind not in {TaskKind.AI_ANNOTATION, TaskKind.MATERIAL_BATCH}:
                database.rollback()
                raise ValueError("only AI annotation review tasks can resume after confirmation")
            if current.accepted is False:
                database.rollback()
                raise ValueError("task cannot resume after rejected review")
            capabilities = tuple(required_capabilities or current.required_capabilities)
            capabilities_json = json.dumps(
                list(capabilities), ensure_ascii=False, separators=(",", ":"),
            )
            if current.status is TaskStatus.AWAITING_CONFIRMATION:
                database.execute(
                    """
                    UPDATE tasks SET status='QUEUED', stage='review_queued', progress=70,
                        current_item=NULL, error=NULL, accepted=1, finished_at=NULL,
                        required_capabilities=?, updated_at=?, worker_id=NULL,
                        lease_token=NULL, lease_expires_at=NULL
                     WHERE task_id=? AND status='AWAITING_CONFIRMATION'
                    """,
                    (capabilities_json, now, str(task_id)),
                )
                row = database.execute(
                    "SELECT * FROM tasks WHERE task_id=?",
                    (str(task_id),),
                ).fetchone()
                database.commit()
                return _from_row(row)
            if current.accepted is True and (
                (current.status is TaskStatus.QUEUED and current.stage == "review_queued")
                or (current.status is TaskStatus.RUNNING and current.stage == "APPLYING_REVIEW")
                or current.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}
            ):
                database.commit()
                return current
            database.rollback()
            raise ValueError("task cannot resume after review confirmation")

    def retry(self, task_id: str) -> TaskRecord:
        now = utc_now()
        terminal_values = tuple(status.value for status in TERMINAL_STATUSES)
        placeholders = ",".join("?" for _ in terminal_values)
        with closing(self._connect()) as database:
            changed = database.execute(
                f"""
                UPDATE tasks SET status='QUEUED', stage='queued', progress=0,
                    current_item=NULL, retry_of=task_id, error=NULL, accepted=NULL,
                    result_ref=NULL, worker_id=NULL, lease_token=NULL,
                    lease_expires_at=NULL, process_pid=NULL, process_create_time=NULL,
                    process_command_hash=NULL, finished_at=NULL, updated_at=?
                 WHERE task_id=? AND status IN ({placeholders}) AND kind<>'ANNOTATION_FORMAL_BULK'
                """,
                (now, str(task_id), *terminal_values),
            ).rowcount
        if changed != 1:
            raise ValueError("only terminal tasks can be retried")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def resume_annotation_generation(self, task_id: str, *, generation_progress: float = 0) -> TaskRecord:
        """Requeue an unfinished AI generation without changing its candidate owner.

        This is intentionally not the generic retry() path: the original task ID,
        frozen request, per-image SQLite candidates and review history survive.
        """
        now = utc_now()
        eligible = (
            TaskStatus.AWAITING_CONFIRMATION.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.FAILED.value,
            TaskStatus.BLOCKED_BY_ENVIRONMENT.value,
            TaskStatus.BLOCKED_BY_HARDWARE.value,
        )
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT * FROM tasks WHERE task_id=?", (str(task_id),)).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            cancellation_marker = current.status is TaskStatus.CANCELLED and current.accepted is False
            if current.kind is not TaskKind.AI_ANNOTATION or current.status.value not in eligible or (current.accepted is not None and not cancellation_marker):
                database.rollback()
                raise ValueError("only unfinished, unreviewed AI generation can resume")
            database.execute(
                """UPDATE tasks SET status='QUEUED', stage='annotation_retry_queued',
                    current_item=NULL, error=NULL, result_ref=NULL, accepted=NULL, finished_at=NULL,
                    progress=?,
                    worker_id=NULL, lease_token=NULL, lease_expires_at=NULL,
                    process_pid=NULL, process_create_time=NULL, process_command_hash=NULL,
                    updated_at=? WHERE task_id=?""",
                (max(0.0, min(70.0, float(generation_progress))), now, str(task_id)),
            )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def recover_annotation_candidates_for_review(self, task_id: str) -> TaskRecord:
        """Expose existing durable candidates from a cancelled/failed AI task."""
        now = utc_now()
        allowed = (
            TaskStatus.CANCELLED.value, TaskStatus.FAILED.value,
            TaskStatus.BLOCKED_BY_ENVIRONMENT.value, TaskStatus.BLOCKED_BY_HARDWARE.value,
        )
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT * FROM tasks WHERE task_id=?", (str(task_id),)).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            cancellation_marker = current.status is TaskStatus.CANCELLED and current.accepted is False
            if current.kind is not TaskKind.AI_ANNOTATION or current.status.value not in allowed or (current.accepted is not None and not cancellation_marker):
                database.rollback()
                raise ValueError("task has no recoverable AI generation review")
            database.execute(
                """UPDATE tasks SET status='AWAITING_CONFIRMATION', stage='awaiting_confirmation',
                    result_ref='candidates/manifest.json', accepted=NULL, progress=MAX(progress,70),
                    error=NULL, finished_at=NULL, updated_at=? WHERE task_id=?""",
                (now, str(task_id)),
            )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result
