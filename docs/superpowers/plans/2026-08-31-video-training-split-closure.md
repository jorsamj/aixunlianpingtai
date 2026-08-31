# Video, Training Split, and Task Runtime Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one durable, cross-platform execution boundary for video extraction and training, with globally serialized resources, recoverable controls, leakage-safe train/validation/test snapshots, and equivalent local/remote behavior.

**Architecture:** First create the shared `platform_core.task_runtime` package consumed by this plan and the cleaning/annotation and conversion/deployment plans: SQLite WAL stores task summaries and leases, while payloads, results, checkpoints, and logs live under task-scoped relative artifact references. A standalone scheduler worker owns resource claims and child processes; FastAPI only validates, stores uploads/artifacts, enqueues, and reads state, so browser polling is never required for execution. Video and training are registered task handlers using the same repository, artifact, lease, cancellation, process-identity, and recovery contracts.

**Tech Stack:** Python 3.10-3.12, FastAPI, SQLite WAL, dataclasses/enums, pathlib, psutil, subprocess argv execution, FFmpeg/ffprobe, OpenCV, Ultralytics, PaddleDetection, pytest, Playwright.

---

## Current fault map and locked boundaries

The public runtime package in Tasks 1-4 is created first. Other implementation plans must import it; they must not create a second task database, scheduler, lease format, artifact store, or process registry.

- `app.py:7823-8049` keeps video tasks in per-project JSON and launches daemon threads. Restart loses the worker, the task is never reclaimed, and the API process performs extraction.
- `app.py:7895-7903` supports interval and requested FPS, while `app.py:8000-8009` exposes only `max_frames`; there is no exact `fixed_count` sampling contract.
- `app.py:7932-7938` calls `add_image_record` and then patches split for every frame. `app.py:1061-1105` writes a record and an empty annotation, and `platform_core/material_store.py:109-147` rewrites the full `images.json` for each mutation. One accepted frame therefore causes about three whole-index writes.
- `static/app.js:979-984`, `static/app.js:1093`, and the final renderer at `static/app.js:2500-2508` repeatedly fetch all tasks and rebuild rows or the whole page.
- `app.py:5433-5526` treats explicit IDs as filters over persisted split, random mode produces only train/validation, and `platform_core/snapshots.py:14-67` omits test, source provenance, content hashes, grouping, and actual ratios.
- `app.py:5596-5756` performs artifact loading, dataset copy, snapshot work, and queue dispatch in the request. `app.py:5857-6009` only scans one project's jobs and is invoked by web traffic, so resource exclusion is not global and a queue can stall without page polling.
- `app.py:6029-6093` controls a PID without validating create time or command identity. `remote_train_server.py:22,123-214,255-297` keeps only an in-memory process registry and cannot recover controls after restart.
- `paddle_worker.py:195-223` has Windows defaults and invokes a rendered command with `shell=True` on both operating systems.
- `app.py:5524`, `app.py:5881-5906`, and `remote_train_server.py:145-203` transport a Windows-rooted YAML and do not rebase it after Linux extraction; the submitted remote parameter set is also smaller than the local argv.
- `app.py:6360-6391` archives failed or stopped runs as versions, which can make strict-latest selection reject a later valid predecessor. The iteration base must mean the newest successful, verified, trainable version.

### Public file map

- Create `platform_core/task_runtime/__init__.py`: export only the stable shared contract.
- Create `platform_core/task_runtime/models.py`: fixed enums and immutable records/pages/leases.
- Create `platform_core/task_runtime/artifacts.py`: task-scoped relative artifact storage with traversal rejection and atomic JSON writes.
- Create `platform_core/task_runtime/repository.py`: SQLite WAL schema, cursor listing, atomic priority claims, global resource mutex, leases, cancel/finish/retry/recovery.
- Create `platform_core/task_runtime/process_control.py`: cross-platform process-group launch, identity validation, suspend/resume/terminate, and restart-safe inspection.
- Create `platform_core/task_runtime/worker.py`: `WorkerContext`, handler protocol, registry, checkpoint and cancellation helpers.
- Create `platform_core/task_runtime/scheduler.py`: lease loop, heartbeat, handler recovery, and resource-aware execution.
- Create `task_worker.py`: standalone scheduler process used on Windows and Linux.
- Create `platform_core/video_tasks.py`: request validation, deterministic sample planning, FFmpeg/OpenCV adapters, batched ingestion, checkpoints.
- Create `platform_core/training_splits.py`: two split modes, content/group leakage checks, snapshot manifest, portable dataset materialization.
- Create `platform_core/training_tasks.py`: local/remote normalized training spec and task handler.
- Create `platform_core/paddle_command.py`: tokenized Paddle command builder with no shell parsing.
- Modify `platform_core/material_store.py:92-147`: one batch upsert/patch transaction per video checkpoint.
- Modify `platform_core/snapshots.py:14-84`: train/validation/test provenance manifest and deterministic hash.
- Modify `platform_core/algorithms.py:10-100`: newest successful verified trainable base selection.
- Modify `app.py:4053-4197,5433-5756,5845-6100,6360-6400,7823-8049`: thin enqueue/read/control endpoints and legacy delegation.
- Modify `train_worker.py:320-590`: consume portable manifest and reserve test for final evaluation.
- Modify `paddle_worker.py:175-235`: argv execution with explicit runtime roots.
- Modify `remote_train_server.py:123-297`: enqueue into the same runtime, rebase manifest, recover by lease and process identity.
- Modify `launcher.py:313-380`: supervise the API and standalone task worker as sibling processes.
- Create `start_remote_server.sh`: NVIDIA Linux remote launch without batch commands.
- Modify `static/app.js:954-1093,2500-2508,3124-3139,3621-3721`: three split controls, video fixed count, incremental row patching, full controls.
- Create unit/API/browser/integration tests named in the tasks below.

## Locked shared contract

`TaskStatus` is exactly `QUEUED`, `RUNNING`, `AWAITING_CONFIRMATION`, `PARTIAL_SUCCESS`, `SUCCEEDED`, `CANCEL_REQUESTED`, `CANCELLED`, `FAILED`, `BLOCKED_BY_ENVIRONMENT`, and `BLOCKED_BY_HARDWARE`. `TaskKind` is exactly `CLEANING`, `AI_ANNOTATION`, `VIDEO_FRAMES`, `TRAINING`, `MODEL_CONVERSION`, and `DEPLOYMENT_TEST` until a separately reviewed schema migration adds a value.

`TaskRepository` exposes these signatures without route-specific arguments:

```python
create(record: TaskRecord) -> TaskRecord
get(task_id: str) -> TaskRecord | None
list(project_id=None, kinds=None, statuses=None, limit=50, cursor=None) -> TaskPage
claim_next(worker_id: str, kinds, capabilities, lease_seconds: int = 30) -> TaskLease | None
heartbeat(task_id: str, lease_token: str, progress=None, stage=None, current_item=None) -> TaskRecord
request_cancel(task_id: str) -> TaskRecord
finish(task_id: str, lease_token: str, status: TaskStatus, result_ref=None, error=None, accepted=None) -> TaskRecord
complete_review(task_id: str, status: TaskStatus, result_ref: str, accepted: bool, error=None) -> TaskRecord
retry(task_id: str) -> TaskRecord
release_expired(now=None) -> int
```

`WorkerContext` exposes `task`, `lease`, `repository`, `artifacts`, `cancel_requested()`, `load_checkpoint()`, and `save_checkpoint()`. `ArtifactStore` accepts `task_id` plus a relative path in `atomic_write_json`, `read_json`, `append_log`, and `artifact_path`; absolute paths, drive-qualified paths, `..`, and resolved escapes are rejected. SQLite stores summaries, resource keys, priorities, control stage, progress, lease data, and relative refs only; payload, result, checkpoint, and log bodies never enter SQLite.

Paused work remains `RUNNING` with `stage="paused"`, holds its resource lease, and is resumed by the scheduler. Stop moves through `CANCEL_REQUESTED` to `CANCELLED`. This preserves the fixed status enum and makes resource ownership unambiguous.

### Task 1: Lock enums, records, artifact references, and worker context

**Files:**
- Create: `platform_core/task_runtime/__init__.py`
- Create: `platform_core/task_runtime/models.py`
- Create: `platform_core/task_runtime/artifacts.py`
- Create: `platform_core/task_runtime/worker.py`
- Test: `tests/unit/task_runtime/test_contract.py`
- Test: `tests/unit/task_runtime/test_artifacts.py`

- [ ] **Step 1: Write the failing contract and traversal tests**

```python
# tests/unit/task_runtime/test_contract.py
from dataclasses import replace
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus

def test_public_status_and_kind_values_are_locked():
    assert [x.value for x in TaskStatus] == [
        "QUEUED", "RUNNING", "AWAITING_CONFIRMATION", "PARTIAL_SUCCESS",
        "SUCCEEDED", "CANCEL_REQUESTED", "CANCELLED", "FAILED",
        "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE",
    ]
    assert [x.value for x in TaskKind] == [
        "CLEANING", "AI_ANNOTATION", "VIDEO_FRAMES", "TRAINING",
        "MODEL_CONVERSION", "DEPLOYMENT_TEST",
    ]
    record = TaskRecord.new(
        task_id="t1", project_id="p1", kind=TaskKind.VIDEO_FRAMES,
        payload_ref="payload.json", resource_key="gpu:local:0", priority=7,
        required_capabilities=("opencv",),
    )
    assert replace(record, status=TaskStatus.RUNNING).priority == 7
```

```python
# tests/unit/task_runtime/test_artifacts.py
import pytest
from platform_core.task_runtime import ArtifactStore

def test_artifacts_are_atomic_and_task_relative(tmp_path):
    store = ArtifactStore(tmp_path)
    store.atomic_write_json("t1", "checkpoints/video.json", {"next_index": 31})
    assert store.read_json("t1", "checkpoints/video.json") == {"next_index": 31}
    store.append_log("t1", "logs/task.log", "frame batch committed\n")
    assert store.artifact_path("t1", "logs/task.log").read_text() == "frame batch committed\n"

@pytest.mark.parametrize("value", ["../escape.json", "/tmp/escape", r"C:\\escape.json"])
def test_artifact_store_rejects_escape(tmp_path, value):
    with pytest.raises(ValueError, match="relative task artifact"):
        ArtifactStore(tmp_path).artifact_path("t1", value)
```

- [ ] **Step 2: Run the tests and confirm the red state**

Run: `pytest tests/unit/task_runtime/test_contract.py tests/unit/task_runtime/test_artifacts.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'platform_core.task_runtime'`.

- [ ] **Step 3: Add the fixed types and exports**

```python
# platform_core/task_runtime/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    SUCCEEDED = "SUCCEEDED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    BLOCKED_BY_ENVIRONMENT = "BLOCKED_BY_ENVIRONMENT"
    BLOCKED_BY_HARDWARE = "BLOCKED_BY_HARDWARE"

class TaskKind(str, Enum):
    CLEANING = "CLEANING"
    AI_ANNOTATION = "AI_ANNOTATION"
    VIDEO_FRAMES = "VIDEO_FRAMES"
    TRAINING = "TRAINING"
    MODEL_CONVERSION = "MODEL_CONVERSION"
    DEPLOYMENT_TEST = "DEPLOYMENT_TEST"

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    project_id: str
    kind: TaskKind
    status: TaskStatus
    priority: int
    resource_key: str
    required_capabilities: tuple[str, ...]
    payload_ref: str
    result_ref: str | None = None
    log_ref: str = "logs/task.log"
    progress: float = 0.0
    stage: str = "queued"
    current_item: str | None = None
    attempt: int = 0
    retry_of: str | None = None
    error: str | None = None
    accepted: bool | None = None
    process_pid: int | None = None
    process_create_time: float | None = None
    process_command_hash: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    finished_at: str | None = None

    @classmethod
    def new(cls, task_id: str, project_id: str, kind: TaskKind, payload_ref: str,
            resource_key: str, priority: int = 50,
            required_capabilities: tuple[str, ...] = ()) -> "TaskRecord":
        return cls(task_id, project_id, kind, TaskStatus.QUEUED,
                   max(1, min(999, int(priority))), resource_key,
                   tuple(sorted(set(required_capabilities))), payload_ref)

@dataclass(frozen=True)
class TaskLease:
    task: TaskRecord
    lease_token: str
    worker_id: str
    expires_at: str

@dataclass(frozen=True)
class TaskPage:
    items: tuple[TaskRecord, ...]
    next_cursor: str | None
```

```python
# platform_core/task_runtime/worker.py
from dataclasses import dataclass
from typing import Protocol
from .artifacts import ArtifactStore
from .models import TaskLease, TaskRecord, TaskStatus

class RepositoryPort(Protocol):
    def get(self, task_id: str) -> TaskRecord | None: ...
    def heartbeat(self, task_id: str, lease_token: str, progress=None,
                  stage=None, current_item=None) -> TaskRecord: ...

@dataclass(frozen=True)
class WorkerContext:
    task: TaskRecord
    lease: TaskLease
    repository: RepositoryPort
    artifacts: ArtifactStore

    def cancel_requested(self) -> bool:
        current = self.repository.get(self.task.task_id)
        return current is not None and current.status == TaskStatus.CANCEL_REQUESTED

    def load_checkpoint(self) -> dict:
        return self.artifacts.read_json(
            self.task.task_id, "checkpoints/worker.json", default={}
        )

    def save_checkpoint(self, value: dict) -> None:
        self.artifacts.atomic_write_json(
            self.task.task_id, "checkpoints/worker.json", value
        )

class TaskHandler(Protocol):
    def run(self, context: WorkerContext) -> tuple[TaskStatus, str | None]: ...
    def recover(self, context: WorkerContext) -> tuple[TaskStatus, str | None]: ...
```

- [ ] **Step 4: Add the traversal-safe artifact store and package exports**

```python
# platform_core/task_runtime/artifacts.py
from __future__ import annotations
import json, os, tempfile
from pathlib import Path, PureWindowsPath

class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def artifact_path(self, task_id: str, relative_path: str) -> Path:
        raw = str(relative_path)
        candidate = Path(raw)
        windows = PureWindowsPath(raw)
        if candidate.is_absolute() or windows.is_absolute() or windows.drive or ".." in candidate.parts:
            raise ValueError("relative task artifact path required")
        task_root = (self.root / str(task_id)).resolve()
        resolved = (task_root / candidate).resolve()
        if resolved != task_root and task_root not in resolved.parents:
            raise ValueError("relative task artifact path required")
        return resolved

    def atomic_write_json(self, task_id: str, relative_path: str, value: dict) -> None:
        path = self.artifact_path(task_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def read_json(self, task_id: str, relative_path: str, default=None):
        path = self.artifact_path(task_id, relative_path)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def append_log(self, task_id: str, relative_path: str, text: str) -> None:
        path = self.artifact_path(task_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(text); stream.flush()
```

```python
# platform_core/task_runtime/__init__.py
from .artifacts import ArtifactStore
from .models import TaskKind, TaskLease, TaskPage, TaskRecord, TaskStatus
from .worker import TaskHandler, WorkerContext
__all__ = ["ArtifactStore", "TaskHandler", "TaskKind", "TaskLease",
           "TaskPage", "TaskRecord", "TaskStatus", "WorkerContext"]
```

- [ ] **Step 5: Run the green tests and commit**

Run: `pytest tests/unit/task_runtime/test_contract.py tests/unit/task_runtime/test_artifacts.py -q`

Expected: `5 passed`.

```bash
git add platform_core/task_runtime tests/unit/task_runtime
git commit -m "feat(runtime): lock shared task and artifact contracts"
```

### Task 2: Implement SQLite WAL repository, numeric priority, global mutex, and leases

**Files:**
- Create: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/task_runtime/__init__.py`
- Test: `tests/unit/task_runtime/test_repository.py`

- [ ] **Step 1: Write repository contract tests**

```python
from datetime import datetime, timedelta, timezone
from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository, TaskStatus

def add(repo, task_id, project, priority, resource="gpu:local:0", capability="cuda"):
    return repo.create(TaskRecord.new(task_id, project, TaskKind.TRAINING,
        "payload.json", resource, priority, (capability,)))

def test_wal_claim_is_global_low_number_first_and_fifo(tmp_path):
    repo = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repo, "late", "p1", 20); add(repo, "first", "p2", 3); add(repo, "second", "p3", 3)
    assert repo.journal_mode() == "wal"
    lease = repo.claim_next("w1", [TaskKind.TRAINING], {"cuda"}, 30)
    assert lease.task.task_id == "first"
    assert repo.claim_next("w2", [TaskKind.TRAINING], {"cuda"}, 30) is None
    repo.finish("first", lease.lease_token, TaskStatus.SUCCEEDED, "result.json")
    assert repo.claim_next("w2", [TaskKind.TRAINING], {"cuda"}, 30).task.task_id == "second"

def test_capability_cancel_retry_cursor_and_expired_lease(tmp_path):
    repo = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repo, "cpu-only", "p1", 1, "cpu:local", "opencv")
    assert repo.claim_next("gpu", [TaskKind.TRAINING], {"cuda"}) is None
    page = repo.list(project_id="p1", limit=1)
    assert page.items[0].task_id == "cpu-only"
    cancelled = repo.request_cancel("cpu-only")
    assert cancelled.status == TaskStatus.CANCELLED
    assert repo.retry("cpu-only").status == TaskStatus.QUEUED
    lease = repo.claim_next("cpu", [TaskKind.TRAINING], {"opencv"}, lease_seconds=1)
    future = datetime.now(timezone.utc) + timedelta(seconds=2)
    assert repo.release_expired(future) == 1
    assert repo.get(lease.task.task_id).status == TaskStatus.QUEUED
```

- [ ] **Step 2: Verify the repository tests fail**

Run: `pytest tests/unit/task_runtime/test_repository.py -q`

Expected: collection fails because `TaskRepository` is not exported.

- [ ] **Step 3: Create the WAL schema and deterministic row mapping**

```python
# platform_core/task_runtime/repository.py
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
 task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
 status TEXT NOT NULL, priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 999),
 resource_key TEXT NOT NULL, required_capabilities TEXT NOT NULL,
 payload_ref TEXT NOT NULL, result_ref TEXT, log_ref TEXT NOT NULL,
 progress REAL NOT NULL, stage TEXT NOT NULL, current_item TEXT,
 attempt INTEGER NOT NULL, retry_of TEXT, error TEXT, accepted INTEGER,
 process_pid INTEGER, process_create_time REAL, process_command_hash TEXT,
 worker_id TEXT, lease_token TEXT, lease_expires_at TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_claim
 ON tasks(status, priority, created_at, task_id);
CREATE INDEX IF NOT EXISTS idx_task_resource
 ON tasks(resource_key, status, lease_expires_at);
"""

class TaskRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def journal_mode(self) -> str:
        with self._connect() as db:
            return str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def create(self, record: TaskRecord) -> TaskRecord:
        values = _to_values(record)
        with self._connect() as db:
            columns = ",".join(values)
            marks = ",".join("?" for _ in values)
            db.execute(f"INSERT INTO tasks ({columns}) VALUES ({marks})", tuple(values.values()))
        return self.get(record.task_id)  # type: ignore[return-value]

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return _from_row(row) if row else None
```

The same file must define `_to_values`/`_from_row` using enum `.value`, JSON arrays only for `required_capabilities`, ISO-8601 UTC timestamps, `accepted` as nullable integer, and all `TaskRecord` fields. It must not add payload or result JSON columns. `complete_review` must atomically permit only `AWAITING_CONFIRMATION -> SUCCEEDED|PARTIAL_SUCCESS`, clear any lease, persist `accepted` and `finished_at`, be idempotent for the same `result_ref/status/accepted`, and reject conflicting repeated review writes.

- [ ] **Step 4: Implement atomic global claim, heartbeat, finish, cancel, retry, listing, and expiry**

```python
def claim_next(self, worker_id, kinds, capabilities, lease_seconds=30):
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=max(1, int(lease_seconds)))
    kind_values = tuple(x.value if isinstance(x, TaskKind) else str(x) for x in kinds)
    capability_set = set(capabilities)
    with self._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        self._release_expired_in(db, now.isoformat())
        marks = ",".join("?" for _ in kind_values)
        rows = db.execute(
            f"SELECT * FROM tasks t WHERE t.status='QUEUED' AND t.kind IN ({marks}) "
            "AND NOT EXISTS (SELECT 1 FROM tasks active WHERE active.resource_key=t.resource_key "
            "AND active.status IN ('RUNNING','CANCEL_REQUESTED') "
            "AND active.lease_expires_at>?) ORDER BY t.priority ASC,t.created_at ASC,t.task_id ASC",
            (*kind_values, now.isoformat()),
        ).fetchall()
        row = next((r for r in rows if set(json.loads(r["required_capabilities"])) <= capability_set), None)
        if row is None:
            db.execute("COMMIT"); return None
        token = secrets.token_urlsafe(24)
        db.execute(
            "UPDATE tasks SET status='RUNNING',stage='starting',worker_id=?,lease_token=?,"
            "lease_expires_at=?,attempt=attempt+1,updated_at=? WHERE task_id=? AND status='QUEUED'",
            (worker_id, token, expires.isoformat(), now.isoformat(), row["task_id"]),
        )
        db.execute("COMMIT")
    task = self.get(row["task_id"])
    return TaskLease(task=task, lease_token=token, worker_id=worker_id,
                     expires_at=expires.isoformat())
```

Implement the remaining locked signatures with `BEGIN IMMEDIATE` and lease-token comparison. `request_cancel` changes `QUEUED` directly to `CANCELLED`, changes `RUNNING` to `CANCEL_REQUESTED`, and returns terminal tasks unchanged. `finish` accepts only `AWAITING_CONFIRMATION`, `PARTIAL_SUCCESS`, `SUCCEEDED`, `CANCELLED`, `FAILED`, `BLOCKED_BY_ENVIRONMENT`, or `BLOCKED_BY_HARDWARE`; clears lease fields and persists only `result_ref`, `error`, and `accepted`. `retry` accepts terminal/block statuses, clears result/error/process identity, and preserves original numeric priority. `release_expired` returns `RUNNING` and `CANCEL_REQUESTED` records to `QUEUED`, increments no attempt, and writes `stage="lease_recovered"`. `list` orders by `(created_at DESC, task_id DESC)` and encodes that pair as URL-safe base64 JSON in `next_cursor`.

- [ ] **Step 5: Export, run concurrency coverage, and commit**

Add `TaskRepository` to `platform_core/task_runtime/__init__.py`, then run:

Run: `pytest tests/unit/task_runtime/test_repository.py -q`

Expected: `2 passed`.

Run: `pytest tests/unit/task_runtime -q`

Expected: all task runtime tests pass and no `database is locked` error appears.

```bash
git add platform_core/task_runtime tests/unit/task_runtime
git commit -m "feat(runtime): add WAL repository priority claims and leases"
```

### Task 3: Add verified cross-platform process control

**Files:**
- Create: `platform_core/task_runtime/process_control.py`
- Modify: `platform_core/task_runtime/models.py`
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/task_runtime/__init__.py`
- Test: `tests/unit/task_runtime/test_process_control.py`

- [ ] **Step 1: Write identity, argv, suspend/resume, and tree-stop tests**

```python
import hashlib, os, subprocess, sys, time
from platform_core.task_runtime.process_control import (
    inspect_identity, process_matches, spawn_managed, suspend_tree,
    resume_tree, terminate_tree,
)

def test_spawn_records_pid_create_time_and_command_hash(tmp_path):
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    proc, identity = spawn_managed(argv, tmp_path, os.environ.copy())
    try:
        assert identity.pid == proc.pid
        assert identity.create_time > 0
        assert identity.command_hash == hashlib.sha256(
            "\0".join(argv).encode("utf-8")
        ).hexdigest()
        assert process_matches(identity)
        suspend_tree(identity); assert inspect_identity(identity).status == "stopped"
        resume_tree(identity); assert inspect_identity(identity).status in {"running", "sleeping"}
    finally:
        terminate_tree(identity, timeout=3)
    assert not process_matches(identity)

def test_reused_pid_is_rejected(monkeypatch):
    from platform_core.task_runtime.models import ProcessIdentity
    identity = ProcessIdentity(4312, 100.0, "abc")
    class FakeProcess:
        def create_time(self): return 101.0
    monkeypatch.setattr("psutil.Process", lambda pid: FakeProcess())
    assert process_matches(identity) is False
```

- [ ] **Step 2: Run the tests and observe the missing module**

Run: `pytest tests/unit/task_runtime/test_process_control.py -q`

Expected: collection fails with `No module named 'platform_core.task_runtime.process_control'`.

- [ ] **Step 3: Implement process identity and managed process groups**

```python
# append to platform_core/task_runtime/models.py
@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    create_time: float
    command_hash: str
```

```python
# platform_core/task_runtime/process_control.py
from __future__ import annotations
import hashlib, os, signal, subprocess, time
from pathlib import Path
import psutil
from .models import ProcessIdentity

def command_hash(argv: list[str]) -> str:
    return hashlib.sha256("\0".join(map(str, argv)).encode("utf-8")).hexdigest()

def spawn_managed(argv: list[str], cwd: Path, env: dict[str, str], stdout=None):
    if not argv or any(not isinstance(x, str) for x in argv):
        raise ValueError("managed process requires a non-empty argv list")
    kwargs = {"cwd": str(Path(cwd)), "env": env, "stdout": stdout,
              "stderr": subprocess.STDOUT, "shell": False}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, **kwargs)
    identity = ProcessIdentity(proc.pid, psutil.Process(proc.pid).create_time(), command_hash(argv))
    return proc, identity

def process_matches(identity: ProcessIdentity) -> bool:
    try:
        return abs(psutil.Process(identity.pid).create_time() - identity.create_time) < 0.01
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

def inspect_identity(identity: ProcessIdentity):
    if not process_matches(identity):
        raise ProcessLookupError("recorded process identity no longer exists")
    return psutil.Process(identity.pid)

def _tree(identity: ProcessIdentity):
    root = inspect_identity(identity)
    return root, root.children(recursive=True)

def suspend_tree(identity: ProcessIdentity) -> None:
    root, children = _tree(identity)
    for child in children + [root]: child.suspend()

def resume_tree(identity: ProcessIdentity) -> None:
    root, children = _tree(identity)
    for child in children + [root]: child.resume()

def terminate_tree(identity: ProcessIdentity, timeout: float = 8.0) -> None:
    if not process_matches(identity): return
    root, children = _tree(identity)
    if os.name != "nt":
        try: os.killpg(os.getpgid(identity.pid), signal.SIGTERM)
        except ProcessLookupError: return
    else:
        for child in reversed(children): child.terminate()
        root.terminate()
    _, alive = psutil.wait_procs(children + [root], timeout=timeout)
    for proc in alive: proc.kill()
```

- [ ] **Step 4: Persist the complete identity through repository heartbeats**

Add `set_process_identity(task_id, lease_token, identity)` to `TaskRepository`; perform an atomic update guarded by both task ID and lease token and write `process_pid`, `process_create_time`, and `process_command_hash`. Add `_from_row` mapping for all three fields and export `ProcessIdentity` plus process-control functions.

```python
def set_process_identity(self, task_id, lease_token, identity):
    now = utc_now()
    with self._connect() as db:
        changed = db.execute(
            "UPDATE tasks SET process_pid=?,process_create_time=?,process_command_hash=?,updated_at=? "
            "WHERE task_id=? AND lease_token=?",
            (identity.pid, identity.create_time, identity.command_hash,
             now, task_id, lease_token),
        ).rowcount
    if changed != 1:
        raise PermissionError("task lease does not own process identity")
    return self.get(task_id)
```

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/unit/task_runtime/test_process_control.py tests/unit/task_runtime/test_repository.py -q`

Expected: `4 passed`, including actual child cleanup on the current operating system.

```bash
git add platform_core/task_runtime tests/unit/task_runtime
git commit -m "feat(runtime): verify and control cross-platform process trees"
```

### Task 4: Run scheduling in a standalone lease worker, independent of FastAPI and browser polling

**Files:**
- Create: `platform_core/task_runtime/scheduler.py`
- Create: `platform_core/runtime_paths.py`
- Create: `task_worker.py`
- Modify: `launcher.py:313-380`
- Modify: `platform_core/task_runtime/__init__.py`
- Test: `tests/unit/task_runtime/test_scheduler.py`
- Test: `tests/integration/test_task_worker_without_web.py`

- [ ] **Step 1: Write scheduler recovery and no-web tests**

```python
# tests/unit/task_runtime/test_scheduler.py
from platform_core.task_runtime import (
    ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus,
)

class RecordingHandler:
    def __init__(self): self.calls = []
    def run(self, context):
        self.calls.append(("run", context.task.task_id))
        context.save_checkpoint({"committed": 4})
        return TaskStatus.SUCCEEDED, "result.json"
    def recover(self, context):
        self.calls.append(("recover", context.load_checkpoint()["committed"]))
        return TaskStatus.SUCCEEDED, "result.json"

def test_scheduler_claims_without_api_request_and_finishes(tmp_path):
    repo = TaskRepository(tmp_path / "tasks.sqlite3")
    store = ArtifactStore(tmp_path / "artifacts")
    task = TaskRecord.new("v1", "p1", TaskKind.VIDEO_FRAMES, "payload.json", "cpu:video", 4, ("opencv",))
    repo.create(task); store.atomic_write_json("v1", "payload.json", {"video": "inputs/a.mp4"})
    handler = RecordingHandler()
    scheduler = Scheduler(repo, store, "worker-1", {TaskKind.VIDEO_FRAMES: handler}, {"opencv"})
    assert scheduler.run_once() is True
    assert repo.get("v1").status == TaskStatus.SUCCEEDED
    assert handler.calls == [("run", "v1")]

def test_expired_attempt_uses_recover(tmp_path):
    repo = TaskRepository(tmp_path / "tasks.sqlite3"); store = ArtifactStore(tmp_path / "artifacts")
    task = TaskRecord.new("v2", "p1", TaskKind.VIDEO_FRAMES, "payload.json", "cpu:video")
    repo.create(task); store.atomic_write_json("v2", "checkpoints/worker.json", {"committed": 9})
    first = repo.claim_next("dead", [TaskKind.VIDEO_FRAMES], set(), 1)
    repo.release_expired("2999-01-01T00:00:00+00:00")
    handler = RecordingHandler()
    Scheduler(repo, store, "worker-2", {TaskKind.VIDEO_FRAMES: handler}, set()).run_once()
    assert handler.calls == [("recover", 9)]
```

```python
# tests/integration/test_task_worker_without_web.py
def test_worker_process_completes_task_when_no_http_server_runs(tmp_path, task_worker_process):
    repo, artifacts = task_worker_process(tmp_path, kinds=["VIDEO_FRAMES"], capabilities=["opencv"])
    artifacts.atomic_write_json("t1", "payload.json", {"probe_only": True})
    repo.create(video_probe_record("t1", "p1"))
    assert wait_for(lambda: repo.get("t1").status.value == "SUCCEEDED", timeout=5)
```

- [ ] **Step 2: Run the red tests**

Run: `pytest tests/unit/task_runtime/test_scheduler.py tests/integration/test_task_worker_without_web.py -q`

Expected: collection fails because `Scheduler` and the task worker fixture do not exist.

- [ ] **Step 3: Implement one-claim scheduling with heartbeat and recovery dispatch**

```python
# platform_core/task_runtime/scheduler.py
from __future__ import annotations
import threading, time
from .models import TaskKind, TaskStatus
from .worker import WorkerContext

class Scheduler:
    def __init__(self, repository, artifacts, worker_id, handlers, capabilities,
                 lease_seconds=30, poll_seconds=0.25):
        self.repository = repository; self.artifacts = artifacts
        self.worker_id = worker_id; self.handlers = dict(handlers)
        self.capabilities = set(capabilities); self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds

    def run_once(self) -> bool:
        self.repository.release_expired()
        lease = self.repository.claim_next(
            self.worker_id, tuple(self.handlers), self.capabilities, self.lease_seconds
        )
        if lease is None: return False
        context = WorkerContext(lease.task, lease, self.repository, self.artifacts)
        handler = self.handlers[lease.task.kind]
        try:
            recovered = lease.task.attempt > 1 or bool(context.load_checkpoint())
            status, result_ref = handler.recover(context) if recovered else handler.run(context)
            current = self.repository.get(lease.task.task_id)
            if current and current.status == TaskStatus.CANCEL_REQUESTED:
                status, result_ref = TaskStatus.CANCELLED, None
            self.repository.finish(lease.task.task_id, lease.lease_token, status, result_ref)
        except EnvironmentError as error:
            self.repository.finish(lease.task.task_id, lease.lease_token,
                TaskStatus.BLOCKED_BY_ENVIRONMENT, error=str(error))
        except Exception as error:
            self.repository.finish(lease.task.task_id, lease.lease_token,
                TaskStatus.FAILED, error=f"{type(error).__name__}: {error}")
        return True

    def serve_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            if not self.run_once(): stop.wait(self.poll_seconds)
```

Each long-running handler calls `heartbeat` at least every 10 seconds; `Scheduler` also starts a lease-renewal thread before handler invocation and stops it in `finally`, so a training process that emits no progress cannot lose a live lease.

- [ ] **Step 4: Add the standalone entrypoint and sibling-process supervision**

```python
# platform_core/runtime_paths.py
from __future__ import annotations
import os
from pathlib import Path

def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    configured = explicit or os.environ.get("MC_TRAIN_DATA_DIR") or os.environ.get("MC_DATA_DIR") or "data"
    return Path(configured).expanduser().resolve()

# task_worker.py
from __future__ import annotations
import argparse, os, socket, uuid
from platform_core.runtime_paths import resolve_data_dir
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskRepository
from platform_core.video_tasks import VideoFrameHandler
from platform_core.training_tasks import TrainingHandler

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")
    args = parser.parse_args(argv)
    data = resolve_data_dir(args.data_dir)
    repo = TaskRepository(data / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data / "task_runtime" / "artifacts")
    handlers = {**VideoFrameHandler.registry(data), **TrainingHandler.registry(data)}
    capabilities = VideoFrameHandler.capabilities() | TrainingHandler.capabilities()
    Scheduler(repo, artifacts, args.worker_id, handlers, capabilities).serve_forever()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

At `launcher.py:342-380`, resolve the same data root with `resolve_data_dir()` and start `worker_proc = subprocess.Popen([str(py), "task_worker.py", "--data-dir", str(data_dir)], cwd=str(BASE_DIR), env=env, shell=False)` before Uvicorn. In every return/exception/keyboard branch, terminate both children with the process-control helper and fail startup if either exits unexpectedly. Do not import `app.py` in `task_worker.py`.

- [ ] **Step 5: Run the worker tests and commit**

Run: `pytest tests/unit/task_runtime/test_scheduler.py tests/integration/test_task_worker_without_web.py -q`

Expected: `3 passed`; the integration test never starts Uvicorn or calls an HTTP route.

```bash
git add platform_core/task_runtime task_worker.py launcher.py tests/unit/task_runtime tests/integration/test_task_worker_without_web.py
git commit -m "feat(runtime): schedule durable tasks outside the web process"
```

### Task 5: Define interval, FPS, and exact-count video sampling with FFmpeg/OpenCV parity

**Files:**
- Create: `platform_core/video_tasks.py`
- Test: `tests/unit/test_video_sampling.py`
- Test: `tests/integration/test_video_backend_parity.py`

- [ ] **Step 1: Write deterministic sampling and backend-fallback tests**

```python
from platform_core.video_tasks import SamplingMode, VideoSampleRequest, plan_indices

def test_interval_sampling_uses_source_timeline():
    req = VideoSampleRequest(SamplingMode.INTERVAL, interval_seconds=2.0)
    assert plan_indices(total_frames=301, source_fps=30.0, request=req) == [0, 60, 120, 180, 240, 300]

def test_fps_sampling_is_even_and_never_exceeds_source_fps():
    req = VideoSampleRequest(SamplingMode.FPS, extract_fps=2.0)
    assert plan_indices(61, 30.0, req) == [0, 15, 30, 45, 60]

def test_fixed_count_is_exact_unique_and_includes_endpoints():
    req = VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=7)
    indices = plan_indices(101, 25.0, req)
    assert indices == [0, 17, 33, 50, 67, 83, 100]

def test_fixed_count_caps_at_available_frames():
    req = VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=9)
    assert plan_indices(3, 25.0, req) == [0, 1, 2]
```

```python
# tests/integration/test_video_backend_parity.py
def test_ffmpeg_and_opencv_emit_the_same_indices(real_short_video, tmp_path):
    request = VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=5)
    ff = extract_with_ffmpeg(real_short_video, tmp_path / "ff", request)
    cv = extract_with_opencv(real_short_video, tmp_path / "cv", request)
    assert [x.frame_index for x in ff] == [x.frame_index for x in cv]
    assert len(ff) == len(cv) == 5

def test_auto_backend_falls_back_only_when_ffmpeg_is_unavailable(real_short_video, tmp_path, monkeypatch):
    monkeypatch.setattr("platform_core.video_tasks.ffmpeg_available", lambda: False)
    out = extract_video(real_short_video, tmp_path, VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=3), backend="auto")
    assert len(out) == 3
    assert {x.backend for x in out} == {"opencv"}
```

- [ ] **Step 2: Run the red tests**

Run: `pytest tests/unit/test_video_sampling.py tests/integration/test_video_backend_parity.py -q`

Expected: collection fails because `platform_core.video_tasks` does not exist.

- [ ] **Step 3: Implement the validated request and one canonical index planner**

```python
# platform_core/video_tasks.py
from dataclasses import dataclass
from enum import Enum
import math

class SamplingMode(str, Enum):
    INTERVAL = "interval"
    FPS = "fps"
    FIXED_COUNT = "fixed_count"

@dataclass(frozen=True)
class VideoSampleRequest:
    mode: SamplingMode
    interval_seconds: float | None = None
    extract_fps: float | None = None
    fixed_count: int | None = None
    max_frames: int | None = None

    def validate(self, source_fps: float | None = None) -> None:
        supplied = sum(x is not None for x in (self.interval_seconds, self.extract_fps, self.fixed_count))
        if supplied != 1:
            raise ValueError("exactly one video sampling value is required")
        if self.mode == SamplingMode.INTERVAL and not (self.interval_seconds and self.interval_seconds > 0):
            raise ValueError("interval_seconds must be greater than zero")
        if self.mode == SamplingMode.FPS and not (self.extract_fps and self.extract_fps > 0):
            raise ValueError("extract_fps must be greater than zero")
        if source_fps and self.extract_fps and self.extract_fps > source_fps:
            raise ValueError("extract_fps cannot exceed source fps")
        if self.mode == SamplingMode.FIXED_COUNT and not (self.fixed_count and self.fixed_count > 0):
            raise ValueError("fixed_count must be a positive integer")

def plan_indices(total_frames: int, source_fps: float, request: VideoSampleRequest) -> list[int]:
    request.validate(source_fps)
    if total_frames <= 0: return []
    if request.mode == SamplingMode.INTERVAL:
        step = max(1, round(source_fps * request.interval_seconds))
        indices = list(range(0, total_frames, step))
    elif request.mode == SamplingMode.FPS:
        step = max(1, round(source_fps / request.extract_fps))
        indices = list(range(0, total_frames, step))
    else:
        count = min(total_frames, int(request.fixed_count))
        indices = sorted({round(i * (total_frames - 1) / max(1, count - 1)) for i in range(count)})
    return indices[:request.max_frames] if request.max_frames else indices
```

- [ ] **Step 4: Implement FFprobe metadata and adapter parity**

Use `subprocess.run([...], shell=False, check=True)` for `ffprobe` JSON and `ffmpeg -vf select=... -vsync 0`; use the same `plan_indices` output for OpenCV `CAP_PROP_POS_FRAMES`. Both adapters return `ExtractedFrame(frame_index, time_seconds, path, backend, sha256)` and write files under the handler's task artifact directory. `backend="auto"` chooses FFmpeg when both executables are present and falls back to OpenCV only for unavailable executables; a corrupt video is a task failure, not a fallback trigger.

```python
@dataclass(frozen=True)
class ExtractedFrame:
    frame_index: int
    time_seconds: float
    path: Path
    backend: str
    sha256: str

def extract_with_opencv(video, output, request):
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened(): raise ValueError("video cannot be opened")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    indices = plan_indices(total, fps, request); frames = []
    output.mkdir(parents=True, exist_ok=True)
    for index in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index); ok, image = cap.read()
        if not ok: raise ValueError(f"frame {index} cannot be decoded")
        path = output / f"frame-{index:012d}.jpg"
        if not cv2.imwrite(str(path), image): raise OSError(f"frame {index} cannot be written")
        frames.append(ExtractedFrame(index, index / fps, path, "opencv", sha256_file(path)))
    cap.release(); return frames
```

- [ ] **Step 5: Run unit and real-backend tests, then commit**

Run: `pytest tests/unit/test_video_sampling.py -q`

Expected: `4 passed`.

Run: `pytest tests/integration/test_video_backend_parity.py -q`

Expected on a host with FFmpeg and OpenCV: `2 passed`; otherwise the parity case is explicitly skipped with `ffmpeg executable unavailable`, while the fallback case passes.

```bash
git add platform_core/video_tasks.py tests/unit/test_video_sampling.py tests/integration/test_video_backend_parity.py
git commit -m "feat(video): add deterministic interval fps and fixed-count sampling"
```

### Task 6: Batch video ingestion, checkpointed recovery, thin APIs, and incremental UI updates

**Files:**
- Modify: `platform_core/material_store.py:92-147`
- Modify: `platform_core/video_tasks.py`
- Modify: `app.py:7823-8049`
- Modify: `static/app.js:954-1093,2500-2508`
- Test: `tests/unit/test_material_store.py`
- Test: `tests/api/test_video_tasks.py`
- Test: `tests/browser/video-tasks.spec.mjs`

- [ ] **Step 1: Write batch-write, crash-recovery, and API-contract tests**

```python
# append to tests/unit/test_material_store.py
def test_upsert_many_commits_one_revision(tmp_path):
    store = MaterialStore(tmp_path / "images.json")
    before = store.read().revision
    rows = store.upsert_many([{"id": f"f{i}", "split": "unassigned"} for i in range(64)])
    assert len(rows) == 64
    assert store.read().revision == before + 1
```

```python
# tests/api/test_video_tasks.py
def test_create_video_task_enqueues_fixed_count_without_thread(client, seeded_project, sample_video, app_module):
    response = client.post(
        f"/api/v33/projects/{seeded_project['id']}/video-tasks",
        files={"video": ("clip.mp4", sample_video, "video/mp4")},
        data={"mode": "fixed_count", "fixed_count": "11", "dataset_id": "default", "split": "unassigned"},
    )
    assert response.status_code == 202
    task = response.json()
    assert task["kind"] == "VIDEO_FRAMES"
    assert task["status"] == "QUEUED"
    assert app_module._v33_task_lock is None

def test_video_handler_recovers_after_committed_batch(tmp_path, video_context, crash_after_first_batch):
    first = VideoFrameHandler(batch_size=8)
    with pytest.raises(SimulatedCrash): first.run(video_context)
    assert video_context.load_checkpoint()["committed_indices"] == list(range(8))
    status, result_ref = VideoFrameHandler(batch_size=8).recover(video_context)
    result = video_context.artifacts.read_json(video_context.task.task_id, result_ref)
    assert status == TaskStatus.SUCCEEDED
    assert result["inserted_count"] == result["requested_count"]
    assert len({x["content_sha256"] for x in result["frames"]}) == result["inserted_count"]
```

```javascript
// tests/browser/video-tasks.spec.mjs
test('video task supports all modes and patches only changed rows', async ({page}) => {
  await seedVideoTasks(page, [{task_id:'v1', status:'RUNNING', updated_at:'a'}]);
  await page.goto('/'); await openVideoPage(page);
  await expect(page.getByLabel('切帧方式')).toContainText('固定抽取张数');
  await page.getByLabel('切帧方式').selectOption('fixed_count');
  await expect(page.getByLabel('固定张数')).toBeVisible();
  await publishTaskDelta(page, {task_id:'v1', status:'SUCCEEDED', progress:100, updated_at:'b'});
  await expect(page.locator('[data-task-id="v1"]')).toHaveAttribute('data-updated-at', 'b');
  expect(await page.evaluate(() => window.__videoFullRenderCount)).toBe(1);
});
```

- [ ] **Step 2: Run tests and confirm failures at the old per-frame path**

Run: `pytest tests/unit/test_material_store.py::test_upsert_many_commits_one_revision tests/api/test_video_tasks.py -q`

Expected: failure because `upsert_many` and durable video task enqueue/recovery are absent.

- [ ] **Step 3: Add one-transaction material batch ingestion**

```python
# append inside MaterialStore at platform_core/material_store.py:132
def upsert_many(self, records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    incoming = [dict(record) for record in records]
    def apply(rows):
        by_id = {str(row.get("id")): row for row in rows}
        changed = []
        for record in incoming:
            image_id = str(record["id"])
            if image_id in by_id: by_id[image_id].update(record)
            else: rows.append(record); by_id[image_id] = record
            changed.append(dict(by_id[image_id]))
        return changed
    return self.mutate(apply)
```

In `VideoFrameHandler`, stage decoded files in `artifacts/<task_id>/staging/`, compute their final material records including `video_task_id`, `frame_index`, `frame_time_seconds`, `content_sha256`, `source_type="video_frame"`, dataset, and split before one `upsert_many` call. Write empty annotation files in the same task batch, call `upsert_many` once, then atomically write `checkpoints/worker.json` with committed indices and material IDs. On recovery, trust only committed IDs present in `images.json`, delete uncommitted staging files, and resume at the first missing planned index. Check cancellation between decode batches and finish `CANCELLED` without deleting already committed frames.

```python
def _commit_batch(self, context, frames, payload, checkpoint):
    records = [self._material_record(context, frame, payload) for frame in frames]
    for record in records:
        self._write_empty_annotation(context.task.project_id, record["id"])
    committed = self.material_store(context.task.project_id).upsert_many(records)
    checkpoint["committed_indices"].extend(x["frame_index"] for x in committed)
    checkpoint["material_ids"].extend(x["id"] for x in committed)
    context.save_checkpoint(checkpoint)
    context.repository.heartbeat(
        context.task.task_id, context.lease.lease_token,
        progress=100 * len(checkpoint["committed_indices"]) / checkpoint["planned_count"],
        stage="extracting", current_item=str(checkpoint["committed_indices"][-1]),
    )
```

- [ ] **Step 4: Replace the video daemon route with artifact-first enqueue and shared reads**

At `app.py:7823-8049`, remove `_v33_task_lock`, JSON task helpers, `_v33_run_video_frame_task`, and thread creation. Keep upload streaming in the request, write it to the task artifact `inputs/<safe filename>`, atomically write this payload, and call `TaskRepository.create`; return HTTP 202.

```python
payload = {
    "schema_version": 1, "video_ref": f"inputs/{filename}",
    "mode": mode, "interval_seconds": interval_seconds if mode == "interval" else None,
    "extract_fps": extract_fps if mode == "fps" else None,
    "fixed_count": fixed_count if mode == "fixed_count" else None,
    "max_frames": max_frames or None, "dataset_id": dataset_id or "default",
    "split": split or "unassigned", "backend": backend or "auto",
}
artifacts.atomic_write_json(task_id, "payload.json", payload)
record = repository.create(TaskRecord.new(
    task_id, project_id, TaskKind.VIDEO_FRAMES, "payload.json",
    resource_key="cpu:video", priority=priority,
    required_capabilities=("ffmpeg_or_opencv",),
))
return JSONResponse(status_code=202, content=task_to_api(record))
```

`GET /video-tasks` accepts `cursor` and `updated_after`; `GET /video-tasks/{id}` uses `TaskRepository.get`; stop calls `request_cancel`; add pause/resume endpoints that call scheduler control, keep status `RUNNING`, and persist stage `paused`/`extracting`. The API never calls `Scheduler.run_once`.

- [ ] **Step 5: Patch only changed video rows and expose full controls**

At `static/app.js:2500-2508`, render a stable `<tr data-task-id data-updated-at>` once. Replace recursive whole-page `renderVideo424()` polling with `fetchVideoTaskDelta(cursor)` and `patchVideoRow(task)`. The form submits exactly one of interval, FPS, or fixed count. Show pause for `RUNNING`, continue for `RUNNING` plus `stage==='paused'`, stop for queued/running/cancel-requested, and retry for terminal failures.

```javascript
async function fetchVideoTaskDelta(){
  const r=await api(`/api/v33/projects/${pid()}/video-tasks?cursor=${encodeURIComponent(state.videoCursor||'')}`);
  for(const task of r.items||[]) patchVideoRow(task);
  state.videoCursor=r.next_cursor||state.videoCursor;
  if((r.items||[]).some(t=>!isTerminalTask(t))) scheduleVideoDelta();
}
function patchVideoRow(task){
  const old=document.querySelector(`[data-task-id="${CSS.escape(task.task_id)}"]`);
  const next=videoTaskRow424(task);
  if(!old) document.getElementById('videoTaskRows').insertAdjacentHTML('afterbegin',next);
  else if(old.dataset.updatedAt!==task.updated_at) old.outerHTML=next;
}
```

- [ ] **Step 6: Run video tests and commit**

Run: `pytest tests/unit/test_material_store.py::test_upsert_many_commits_one_revision tests/api/test_video_tasks.py -q`

Expected: `3 passed`; the recovery result contains no duplicate frame IDs and material revision advances once per committed batch.

Run: `npx playwright test tests/browser/video-tasks.spec.mjs --reporter=line`

Expected: `1 passed`, with `window.__videoFullRenderCount === 1` after state deltas.

```bash
git add platform_core/material_store.py platform_core/video_tasks.py app.py static/app.js tests/unit/test_material_store.py tests/api/test_video_tasks.py tests/browser/video-tasks.spec.mjs
git commit -m "feat(video): batch durable frame ingestion and incremental task UI"
```

### Task 7: Define leakage-safe train/validation/test modes and traceable snapshots

**Files:**
- Create: `platform_core/training_splits.py`
- Modify: `platform_core/snapshots.py:14-84`
- Modify: `tests/unit/test_snapshots.py`
- Create: `tests/unit/test_training_splits.py`

- [ ] **Step 1: Write independent-dataset, random-percent, leakage, and provenance tests**

```python
from platform_core.training_splits import SplitMode, SplitRequest, build_split_manifest

def image(image_id, dataset, content_hash, group, source="upload"):
    return {"id": image_id, "dataset_id": dataset, "content_sha256": content_hash,
            "group_id": group, "source_type": source, "processing_status": "processed",
            "stored_name": f"{image_id}.jpg", "boxes": []}

def test_mode_a_uses_independent_test_and_derives_validation_from_training_pool():
    rows = [image(str(i), "train-ds", f"h{i}", f"g{i}") for i in range(10)]
    rows += [image("test", "test-ds", "ht", "gt")]
    req = SplitRequest(mode=SplitMode.INDEPENDENT_TEST_SET,
        train_dataset_ids=("train-ds",), test_dataset_ids=("test-ds",), validation_percent=20)
    manifest = build_split_manifest(rows, req, seed=19)
    assert manifest.counts == {"train": 8, "validation": 2, "test": 1, "total": 11}
    assert manifest.requested["test_source"] == "independent_dataset"

def test_mode_b_draws_test_first_then_validation_without_leakage():
    rows = [image(str(i), "source", f"h{i}", f"g{i}") for i in range(20)]
    req = SplitRequest(mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_dataset_ids=("source",), experiment_percent=25, validation_percent=20)
    manifest = build_split_manifest(rows, req, seed=42)
    assert manifest.counts == {"train": 12, "validation": 3, "test": 5, "total": 20}
    assert manifest.requested["test_source"] == "random_from_training_pool"
    assert not set(manifest.ids["train"]) & set(manifest.ids["validation"])
    assert not set(manifest.ids["test"]) & (set(manifest.ids["train"]) | set(manifest.ids["validation"]))

def test_content_hash_or_group_crossing_splits_is_rejected():
    rows = [image("a", "train", "same", "video-1"), image("b", "test", "same", "video-2")]
    req = SplitRequest(mode=SplitMode.INDEPENDENT_TEST_SET,
        train_dataset_ids=("train",), test_dataset_ids=("test",), validation_percent=20)
    with pytest.raises(ValueError, match="content hash leakage"): build_split_manifest(rows, req, 1)
```

- [ ] **Step 2: Run the split tests and verify the red state**

Run: `pytest tests/unit/test_training_splits.py tests/unit/test_snapshots.py -q`

Expected: collection fails because `training_splits` and the three-way snapshot signature are absent.

- [ ] **Step 3: Implement the explicit two-mode contract**

```python
# platform_core/training_splits.py
class SplitMode(str, Enum):
    INDEPENDENT_TEST_SET = "independent_test_set"
    RANDOM_TEST_FROM_TRAINING_POOL = "random_test_from_training_pool"

@dataclass(frozen=True)
class SplitRequest:
    mode: SplitMode
    train_dataset_ids: tuple[str, ...]
    test_dataset_ids: tuple[str, ...] = ()
    experiment_percent: float | None = None
    validation_percent: float = 20.0

def _group_key(row):
    return str(row.get("group_id") or row.get("video_task_id") or row.get("source_group_id") or row["id"])

def _random_group_split(rows, percent, seed, field_name):
    if not 0 < float(percent) < 100: raise ValueError(f"{field_name} must be between 0 and 100")
    groups = defaultdict(list)
    for row in rows: groups[_group_key(row)].append(row)
    keys = sorted(groups); random.Random(seed).shuffle(keys)
    target = max(1, round(len(rows) * float(percent) / 100))
    validation, training = [], []
    for key in keys:
        bucket = groups[key]
        (validation if len(validation) < target else training).extend(bucket)
    return training, validation
```

For mode A, select the training pool from `train_dataset_ids`, select test only from the independent `test_dataset_ids`, then derive validation from the training pool using `validation_percent`. For mode B, first draw whole groups for test from the training pool using `experiment_percent` and `test_seed`; only then draw validation from the remaining pool using `validation_percent` and a distinct `validation_seed`. Reject any dataset ID reused between the mode-A training and test selectors. Before returning, reject overlap by image ID, normalized resolved file identity, `content_sha256`, and `_group_key`. Require at least one item in train, validation, and test. Store both seeds, the requested percentages, the source mode, actual ratios, and every selected image/group in the manifest so the exact split is reproducible.

- [ ] **Step 4: Replace the snapshot payload with complete provenance**

```python
# replacement signature in platform_core/snapshots.py
def build_snapshot(images, split_manifest, label_schema, seed):
    by_id = {str(x["id"]): x for x in images}
    records = []
    for role in ("train", "validation", "test"):
        for image_id in split_manifest.ids[role]:
            row = by_id[image_id]
            records.append({
                "image_id": image_id, "role": role,
                "dataset_id": str(row.get("dataset_id") or "default"),
                "source_type": str(row.get("source_type") or "unknown"),
                "source_ref": str(row.get("source_ref") or row.get("video_task_id") or ""),
                "group_id": split_manifest.groups[image_id],
                "content_sha256": split_manifest.content_hashes[image_id],
                "annotation_hash": annotation_hash(row),
                "stored_name": str(row["stored_name"]),
            })
    payload = {
        "schema_version": 2, "test_seed": int(split_manifest.test_seed),
        "validation_seed": int(split_manifest.validation_seed), "mode": split_manifest.mode.value,
        "requested": split_manifest.requested, "counts": split_manifest.counts,
        "actual_ratios": split_manifest.actual_ratios,
        "ids": split_manifest.ids, "label_schema": stable_schema(label_schema),
        "images": records,
    }
    return {"snapshot_id": hashlib.sha256(_canonical(payload).encode()).hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat(), **payload}
```

Compute missing content hashes by streaming the actual upload once during preparation and persist them back through one material-store batch. The snapshot hash includes role, source, group, content, annotation, requested mode/percent, counts, ratios, seed, and schema; it excludes only `created_at`.

- [ ] **Step 5: Run split/snapshot tests and commit**

Run: `pytest tests/unit/test_training_splits.py tests/unit/test_snapshots.py -q`

Expected: all tests pass; repeated input plus seed yields the same snapshot ID, and changing test membership changes it.

```bash
git add platform_core/training_splits.py platform_core/snapshots.py tests/unit/test_training_splits.py tests/unit/test_snapshots.py
git commit -m "feat(training): lock leakage-safe three-way snapshot semantics"
```

### Task 8: Enqueue training preparation and expose the two split modes in the final UI

**Files:**
- Create: `platform_core/training_tasks.py`
- Modify: `app.py:4053-4197,5433-5756,5845-6009`
- Modify: `static/app.js:3124-3139,3621-3721`
- Modify: `tests/api/test_training_request.py`
- Modify: `tests/frontend/training.test.mjs`
- Modify: `tests/browser/training-quality-reports.spec.mjs:65-213`

- [ ] **Step 1: Write the final API and UI projection tests**

```python
# append to tests/api/test_training_request.py
def test_training_route_enqueues_mode_a_without_copy_or_dispatch(client, seeded_project, monkeypatch):
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues",
        lambda *args: (_ for _ in ()).throw(AssertionError("web route dispatched work")))
    monkeypatch.setattr(app_module, "shutil", None)
    body = valid_training_request(seeded_project) | {
        "split_mode": "independent_test_set", "train_dataset_ids": ["train-ds"],
        "test_dataset_ids": ["test-ds"], "validation_percent": 20,
        "experiment_percent": None,
    }
    response = client.post(f"/api/v12/projects/{seeded_project['id']}/train/start", json=body)
    assert response.status_code == 202
    task = response.json()["task"]
    assert task["kind"] == "TRAINING" and task["status"] == "QUEUED"

def test_training_route_enqueues_mode_b_with_arbitrary_valid_percent(client, seeded_project):
    for value in (1, 12.5, 37, 99):
        body = valid_training_request(seeded_project) | {
            "split_mode": "random_test_from_training_pool", "train_dataset_ids": ["source"],
            "test_dataset_ids": [], "experiment_percent": value,
            "validation_percent": 20,
        }
        assert client.post(f"/api/v12/projects/{seeded_project['id']}/train/start", json=body).status_code == 202
```

```javascript
// append to tests/frontend/training.test.mjs
test('final training payload keeps three roles and never auto-selects hidden test rows', () => {
  const payload = buildTrainingPayload({
    splitMode:'independent_test_set', trainDatasetIds:['a'], testDatasetIds:['c'],
    validationPercent:20
  });
  assert.deepEqual(payload.train_dataset_ids, ['a']);
  assert.deepEqual(payload.test_dataset_ids, ['c']);
  assert.equal(payload.validation_percent, 20);
  assert.equal('selected_image_ids' in payload, false);
});
```

- [ ] **Step 2: Run the red API and frontend tests**

Run: `pytest tests/api/test_training_request.py -q && node --test tests/frontend/training.test.mjs`

Expected: old route returns 200 after synchronous preparation/dispatch, and final JS payload lacks the three dataset roles.

- [ ] **Step 3: Change `TrainReq` to the explicit split contract and make the route artifact-first**

At `app.py:4053-4197`, add these fields and validation. Do not accept `selected_image_ids` or infer roles from persisted `image.split` in this product route.

```python
class TrainReq(BaseModel):
    split_mode: Literal["independent_test_set", "random_test_from_training_pool"]
    train_dataset_ids: List[str]
    test_dataset_ids: List[str] = []
    experiment_percent: Optional[float] = None
    validation_percent: float = Field(default=20, gt=0, lt=100)
    queue_priority: int = Field(default=50, ge=1, le=999)
    # retain the existing model, optimizer, augmentation, target, and resource fields

def validate_split_request(payload: TrainReq):
    if not payload.train_dataset_ids: raise HTTPException(400, "training dataset is required")
    if payload.split_mode == "independent_test_set" and not payload.test_dataset_ids:
        raise HTTPException(400, "independent test dataset is required")
    if set(payload.train_dataset_ids) & set(payload.test_dataset_ids):
        raise HTTPException(400, "training and test datasets must be disjoint")
    if payload.split_mode == "random_test_from_training_pool" and not (
        payload.experiment_percent is not None and 0 < payload.experiment_percent < 100
    ):
        raise HTTPException(400, "experiment_percent must be between 0 and 100")
```

At `app.py:5596-5756`, validate only cheap request facts and algorithm existence, write `payload.json`, and `TaskRepository.create` with `resource_key` derived from the selected local GPU or remote server. Return 202. Move checkpoint loading, content hashing, split construction, file copy/link, YAML generation, environment probe, zip/upload, and process spawn to `TrainingHandler.run`.

```python
artifacts.atomic_write_json(task_id, "payload.json", payload.dict())
record = TaskRecord.new(task_id, project_id, TaskKind.TRAINING, "payload.json",
    resource_key=training_resource_key(payload), priority=payload.queue_priority,
    required_capabilities=training_capabilities(payload))
repository.create(record)
return JSONResponse(status_code=202, content={"ok": True, "task": task_to_api(record)})
```

- [ ] **Step 4: Implement preparation stages in `TrainingHandler`**

```python
class TrainingHandler:
    def run(self, context):
        payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref)
        context.repository.heartbeat(context.task.task_id, context.lease.lease_token, 2, "hashing")
        manifest = build_split_manifest(load_project_images(context.task.project_id), split_request(payload), payload["seed"])
        snapshot = build_snapshot(load_project_images(context.task.project_id), manifest,
                                  load_label_schema(context.task.project_id), payload["seed"])
        context.artifacts.atomic_write_json(context.task.task_id, "snapshot.json", snapshot)
        context.save_checkpoint({"snapshot_id": snapshot["snapshot_id"], "stage": "snapshot_ready"})
        dataset_root = materialize_portable_dataset(context, snapshot)
        context.repository.heartbeat(context.task.task_id, context.lease.lease_token, 15, "starting_trainer")
        return self._run_selected_target(context, payload, dataset_root)

    def recover(self, context):
        checkpoint = context.load_checkpoint()
        if checkpoint.get("process_identity"):
            return self._reattach_or_reconcile(context, checkpoint)
        return self.run(context)
```

`materialize_portable_dataset` writes to task artifacts, never to mutable project `dataset`/`paddle_dataset`, and is idempotent by snapshot ID. Handler finish writes `result.json` with snapshot ref/ID, base version ID, counts, actual ratios, report ref, verified model refs, target, normalized parameter hash, and timing.

- [ ] **Step 5: Replace the final UI override with role-based dataset selection**

At the last definitions in `static/app.js:3621-3721`, render and submit:

```javascript
function buildTrainingPayload(form){
  const mode=form.querySelector('[name="split_mode"]:checked').value;
  return {...readTrainingParameters(form), split_mode:mode,
    train_dataset_ids:selectedDatasetIds('train'),
    test_dataset_ids:mode==='independent_test_set'?selectedDatasetIds('test'):[],
    experiment_percent:mode==='random_test_from_training_pool'?Number(form.experiment_percent.value):null,
    validation_percent:Number(form.validation_percent.value)};
}
```

Mode A shows a training-pool multi-select plus an independent test-dataset multi-select. Mode B shows a training-pool multi-select plus an unrestricted test percentage with `min="0.1" max="99.9" step="0.1"`. Both modes keep `validation_percent` in the collapsed advanced section with a default of 20%; validation is always derived only from the non-test training pool. The summary shows requested and projected counts/ratios for all three roles, test source, test percentage, and both seeds. Remove the final auto-selection of all processed image IDs and label all validation data consistently as `验证集`; test is `试验集（仅最终评估）`.

- [ ] **Step 6: Run API, frontend, and browser tests; commit**

Run: `pytest tests/api/test_training_request.py -q && node --test tests/frontend/training.test.mjs`

Expected: all selected tests pass, every create response is 202, and no dispatcher mock is called.

Run: `npx playwright test tests/browser/training-quality-reports.spec.mjs --reporter=line`

Expected: browser test passes for both modes and shows train/validation/test counts before confirmation.

```bash
git add platform_core/training_tasks.py app.py static/app.js tests/api/test_training_request.py tests/frontend/training.test.mjs tests/browser/training-quality-reports.spec.mjs
git commit -m "feat(training): enqueue explicit three-role split requests"
```

### Task 9: Materialize portable datasets and keep test out of training decisions

**Files:**
- Modify: `platform_core/training_tasks.py`
- Modify: `train_worker.py:320-590`
- Create: `tests/unit/test_portable_dataset.py`
- Modify: `tests/e2e/test_real_yolo_training.py:29-119`

- [ ] **Step 1: Write portable manifest and evaluation-order tests**

```python
def test_materialized_yaml_is_relative_and_relocatable(tmp_path):
    source = seeded_snapshot(tmp_path / "source")
    bundle = materialize_portable_dataset(fake_context(tmp_path), source)
    data = yaml.safe_load((bundle / "data.yaml").read_text())
    assert data["path"] == "."
    assert data["train"] == "images/train"
    assert data["val"] == "images/validation"
    assert data["test"] == "images/test"
    moved = tmp_path / "linux-received"; shutil.move(bundle, moved)
    assert resolve_dataset_yaml(moved / "manifest.json") == moved / "data.yaml"

def test_test_split_runs_once_after_model_selection(monkeypatch, worker_args):
    calls = []
    fake = FakeYolo(on_val=lambda split: calls.append(split))
    run_training(worker_args, yolo_factory=lambda _: fake)
    assert calls.count("test") == 1
    assert calls[-1] == "test"
    assert all(split == "val" for split in calls[:-1])
```

- [ ] **Step 2: Run and observe absolute YAML and test-order failures**

Run: `pytest tests/unit/test_portable_dataset.py -q`

Expected: tests fail because current YAML embeds an absolute Windows snapshot path and has no manifest resolver.

- [ ] **Step 3: Write a relative manifest and YAML with verified members**

```python
manifest = {
  "schema_version": 1, "snapshot_ref": "snapshot.json", "data_yaml_ref": "dataset/data.yaml",
  "splits": {role: [
    {"image_ref": f"dataset/images/{role}/{row['stored_name']}",
     "label_ref": f"dataset/labels/{role}/{Path(row['stored_name']).stem}.txt",
     "content_sha256": row["content_sha256"], "image_id": row["image_id"]}
    for row in records_by_role[role]] for role in ("train", "validation", "test")},
}
yaml_value = {"path": ".", "train": "images/train", "val": "images/validation",
              "test": "images/test", "names": class_names}
```

Resolve every ref against the manifest parent using the ArtifactStore traversal rule. On receipt or recovery, verify each content hash before trainer launch. Use `shutil.copy2` on cross-device paths and hard links only when source and destination are on the same filesystem; never store the resolved absolute result in payload or result.

- [ ] **Step 4: Make validation the only training-time evaluation and test final-only**

At `train_worker.py:320-363,484-575`, retain validation for epoch gates, early stopping, threshold decisions, error analysis tuning, and best-checkpoint selection. Invoke `best_model.val(..., split="test")` exactly once after a verified best artifact exists. If test is empty, write `test_status="not_requested"`; if supplied test fails, finish `PARTIAL_SUCCESS` with the verified model plus an explicit test error rather than marking the model fully successful.

```python
test_result = {"status": "not_requested", "metrics": {}}
if manifest["splits"]["test"]:
    try:
        metrics = best_model.val(data=args.data, split="test", verbose=False)
        test_result = {"status": "succeeded", "metrics": build_report_from_metrics(metrics, best_model.names)["metrics"]}
    except Exception as error:
        test_result = {"status": "failed", "error": str(error)}
update_job(job_file, test_result=test_result)
```

- [ ] **Step 5: Run unit and real YOLO acceptance; commit**

Run: `pytest tests/unit/test_portable_dataset.py -q`

Expected: tests pass after moving the dataset tree to a different root.

Run: `pytest tests/e2e/test_real_yolo_training.py -m real_training -q`

Expected: `1 passed`; output records validation metrics during training and one final test result.

```bash
git add platform_core/training_tasks.py train_worker.py tests/unit/test_portable_dataset.py tests/e2e/test_real_yolo_training.py
git commit -m "feat(training): materialize relocatable snapshots and isolate final test"
```

### Task 10: Select the newest successful verified trainable version

**Files:**
- Modify: `platform_core/algorithms.py:10-100`
- Modify: `app.py:5530-5594,6360-6400`
- Modify: `tests/unit/test_algorithms.py:27-104`
- Modify: `tests/api/test_training_request.py`

- [ ] **Step 1: Write failed-newer and verified-success selection tests**

```python
def test_latest_trainable_ignores_failed_and_cancelled_attempts(tmp_path):
    good = tmp_path / "good.pt"; good.write_bytes(b"weights")
    versions = [
        {"id":"failed-newer", "training_status":"FAILED", "created_at":"2026-08-31T12:00:00Z", "stored_path":""},
        {"id":"cancelled", "training_status":"CANCELLED", "created_at":"2026-08-31T11:00:00Z", "stored_path":""},
        {"id":"good", "training_status":"SUCCEEDED", "artifact_verified":True,
         "trainable":True, "created_at":"2026-08-31T10:00:00Z", "stored_path":str(good)},
    ]
    selected = choose_iteration_base(versions, "mother.pt", strict_latest=True,
                                     artifact_validator=lambda path: True)
    assert selected["base_version_id"] == "good"
```

- [ ] **Step 2: Run the focused red test**

Run: `pytest tests/unit/test_algorithms.py::test_latest_trainable_ignores_failed_and_cancelled_attempts -q`

Expected: fails because strict-latest selects `failed-newer` and raises `ITERATION_BASE_UNAVAILABLE`.

- [ ] **Step 3: Filter iteration candidates by completed delivery semantics**

```python
def is_trainable_version(version, framework):
    return (
        str(version.get("training_status")) in {"SUCCEEDED", "PARTIAL_SUCCESS"}
        and version.get("artifact_verified") is True
        and version.get("trainable") is True
        and str(version.get("framework") or framework) == framework
    )

eligible = [v for v in versions if is_trainable_version(v, framework)]
ordered = sorted(eligible, key=version_order_key, reverse=True)
```

`strict_latest=True` now means newest eligible successful trainable version, not newest attempt. If no eligible version exists but attempts exist, return `ITERATION_BASE_UNAVAILABLE`; use the mother model only when the algorithm has never had an attempt. At `app.py:6360-6400`, create an algorithm version only for `SUCCEEDED` or model-valid `PARTIAL_SUCCESS`; store `framework`, `trainable`, `artifact_verified`, snapshot ID, result ref, and task ID. Failed/cancelled/blocked attempts remain task history and never enter `versions`.

- [ ] **Step 4: Run algorithm and request tests; commit**

Run: `pytest tests/unit/test_algorithms.py tests/api/test_training_request.py -q`

Expected: all tests pass; a newer failed task does not poison iteration, while a corrupt newest successful trainable version fails closed.

```bash
git add platform_core/algorithms.py app.py tests/unit/test_algorithms.py tests/api/test_training_request.py
git commit -m "fix(training): iterate from newest successful trainable version"
```

### Task 11: Make Paddle and remote NVIDIA execution use the same snapshot and argv contract

**Files:**
- Create: `platform_core/paddle_command.py`
- Modify: `paddle_worker.py:175-235`
- Modify: `remote_train_server.py:123-297`
- Modify: `platform_core/training_tasks.py`
- Create: `tests/unit/test_paddle_command.py`
- Create: `tests/integration/test_remote_training_manifest.py`

- [ ] **Step 1: Write argv and relocated-manifest tests**

```python
def test_paddle_command_is_argv_and_preserves_spaces(tmp_path):
    command = build_paddle_command(
        python=tmp_path / "python executable",
        script=tmp_path / "tools" / "train.py",
        config=tmp_path / "configs" / "det model.yml",
        overrides={"epoch": 2, "use_gpu": False},
    )
    assert isinstance(command, list)
    assert str(tmp_path / "configs" / "det model.yml") in command
    assert all("shell=" not in part for part in command)

def test_remote_bundle_rebases_only_relative_manifest_refs(tmp_path):
    received = tmp_path / "received"
    manifest = seed_portable_bundle(received)
    resolved = resolve_remote_training_bundle(received / "manifest.json")
    assert resolved.data_yaml == received / "dataset" / "data.yaml"
    assert resolved.snapshot == received / "snapshot.json"
    assert not any(":" in ref or ref.startswith(("/", "\\")) for ref in manifest_refs(manifest))
```

- [ ] **Step 2: Run the red tests**

Run: `pytest tests/unit/test_paddle_command.py tests/integration/test_remote_training_manifest.py -q`

Expected: imports fail because the normalized Paddle builder and remote bundle resolver do not exist.

- [ ] **Step 3: Implement tokenized Paddle and identical local/remote specs**

```python
def build_paddle_command(*, python, script, config, overrides):
    command = [str(Path(python)), "-u", str(Path(script)), "-c", str(Path(config))]
    for key, value in sorted(overrides.items()):
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        command.extend(["-o", f"{key}={rendered}"])
    return command
```

`paddle_worker.py` passes this list to `launch_process(..., shell=False)` and receives all roots through task payload/artifact refs; remove `D:\\...` defaults and rendered shell strings. `TrainingSpec.to_dict()` is the only local/remote parameter serializer. The remote server authenticates the request, extracts into a task-scoped directory, resolves only manifest-relative refs, verifies every content SHA256, and submits the same normalized spec to its local scheduler. It never accepts a client-supplied absolute YAML path.

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/unit/test_paddle_command.py tests/integration/test_remote_training_manifest.py -q`

Expected: all tests pass on Windows; the relocation test uses a directory containing spaces.

```bash
git add platform_core/paddle_command.py platform_core/training_tasks.py paddle_worker.py remote_train_server.py tests/unit/test_paddle_command.py tests/integration/test_remote_training_manifest.py
git commit -m "fix(training): unify local remote and paddle execution contracts"
```

### Task 12: Persist train controls, remove polling dispatch, and enforce cross-platform source rules

**Files:**
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/task_runtime/process_control.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `app.py:5845-6100`
- Create: `start_remote_server.sh`
- Create: `tests/integration/test_training_controls_recovery.py`
- Create: `tests/unit/test_cross_platform_source.py`

- [ ] **Step 1: Write durable control and source-scan tests**

```python
def test_pause_resume_stop_survive_api_restart(training_harness):
    task_id = training_harness.start_long_training(priority=20)
    identity = training_harness.wait_for_process(task_id)
    training_harness.pause(task_id)
    training_harness.restart_api_only()
    assert training_harness.task(task_id).stage == "paused"
    assert training_harness.process(identity).is_suspended()
    training_harness.resume(task_id)
    training_harness.stop(task_id)
    assert training_harness.wait(task_id).status is TaskStatus.CANCELLED
    assert not training_harness.process(identity).exists()

def test_business_sources_have_no_windows_only_execution(repo_root):
    violations = scan_cross_platform_sources(repo_root, include=[
        "platform_core/**/*.py", "task_worker.py", "train_worker.py",
        "paddle_worker.py", "remote_train_server.py",
    ])
    assert violations == []
```

- [ ] **Step 2: Run the red tests**

Run: `pytest tests/integration/test_training_controls_recovery.py tests/unit/test_cross_platform_source.py -q`

Expected: control recovery or the source scan fails on PID-only control, `shell=True`, drive literals, backslash path construction, or Windows-only command strings.

- [ ] **Step 3: Add guarded control transitions and eliminate web-triggered dispatch**

```python
def control_training_task(repository, controller, task_id, action):
    task = repository.get(task_id)
    if task is None:
        raise KeyError(task_id)
    identity = ProcessIdentity(task.process_pid, task.process_create_time, task.process_command_hash)
    if action == "pause":
        controller.suspend(identity); return repository.update_stage(task_id, "paused")
    if action == "resume":
        controller.resume(identity); return repository.update_stage(task_id, "training")
    if action == "stop":
        repository.request_cancel(task_id); controller.terminate_tree(identity); return task_id
    if action == "promote":
        return repository.update_priority(task_id, 1)
    raise ValueError("unsupported training control")
```

Every control validates PID, create time, and command hash before acting. A paused task remains `RUNNING/stage=paused`, renews its lease, and holds its resource until resume/stop; the UI states this explicitly. Remove `_v48_dispatch_training_queues()` calls from GET/list/poll routes. The standalone scheduler alone claims globally by `resource_key`, so tasks from different projects cannot start on the same GPU. `start_remote_server.sh` uses `exec "$PYTHON" -m uvicorn ...` with quoted environment-derived paths and no Windows syntax.

- [ ] **Step 4: Run controls, static scan, full training regression, and commit**

Run: `pytest tests/integration/test_training_controls_recovery.py tests/unit/test_cross_platform_source.py tests/api/test_training_request.py tests/unit/test_algorithms.py -q`

Expected: all tests pass; restarting only the API neither loses the task nor starts a duplicate process.

```bash
git add platform_core/task_runtime platform_core/training_tasks.py app.py start_remote_server.sh tests/integration/test_training_controls_recovery.py tests/unit/test_cross_platform_source.py
git commit -m "fix(training): persist controls and enforce cross-platform workers"
```
