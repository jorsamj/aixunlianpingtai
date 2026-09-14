# Worker Runtime Truth Implementation Plan

> Execute only this batch. Do not extend into worker readiness admission, task claim fencing, training 503 responses, or frontend behavior.

**Goal:** Extend the existing durable `worker_instances` lease record so the backend can query the actual runtime identity and registration of workers, including an expiry-derived online state.

**Architecture:** Keep `worker_instances`, `WorkerInstanceService`, the existing worker registry, and the existing lease renewal thread as the only sources of worker truth. Add nullable/defaulted SQLite columns through additive migration, persist the values produced by the running worker and its actual registry registration, and expose a sanitized read-only API.

**Tech Stack:** Python, SQLite, FastAPI, pytest.

---

### Task 1: Specify the durable query behavior with focused tests

**Files:**
- Create: `tests/unit/task_runtime/test_worker_runtime_truth.py`
- Create: `tests/api/test_worker_runtime_truth.py`

1. Add a unit test that acquires an existing worker lease with hostname, build ID, actual roles/task kinds/capabilities, then asserts `list_runtime()` returns those values plus timestamps and `online=True`.
2. Add a unit test that evaluates the same durable row after `expires_at` and asserts `online=False`, without consulting PID liveness.
3. Add a small API test proving the read-only endpoint exposes the sanitized durable runtime row.
4. Run only the new focused tests and confirm they fail because the new metadata/query/API do not exist yet.

### Task 2: Extend the existing durable schema and service

**Files:**
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/task_runtime/worker_instances.py`

1. Add `hostname`, `build_id`, `roles`, `task_kinds`, and `capabilities` to the fresh `worker_instances` schema with safe defaults.
2. Add constructor-time additive `ALTER TABLE` migrations for installations with the old table. Do not remove or rebuild the table.
3. Extend `WorkerInstanceService.acquire()` to persist normalized registration metadata in the same durable lease row.
4. Add `WorkerInstanceService.list_runtime()` returning sanitized records. Compute `online` exclusively from the current UTC time and `expires_at`; do not use PID liveness.
5. Run the focused runtime truth unit tests.

### Task 3: Wire actual worker registration and expose the query API

**Files:**
- Modify: `task_worker.py`
- Modify: `app.py`

1. Pass the running worker's resolved build ID, hostname, expanded roles, registered handler task kinds, and registered capabilities into the existing lease acquisition.
2. Add a read-only endpoint at `GET /api/v62/workers` backed by `WorkerInstanceService.list_runtime()`.
3. Run the focused unit/API tests.

### Task 4: Close the batch and verify only affected surfaces

**Files:**
- Modify: `docs/CODEX_CURRENT_STATE.md`

1. Record Worker Runtime Truth closure, durable sources, expiry-based online rule, query API, modified files, test results, and explicit deferred items.
2. Confirm `VERSION.txt` remains `42.24.0`.
3. Run Python compilation/import checks for the affected modules and the focused pytest files only.
4. Review the diff for scope leakage and ensure no task claim, training admission, training frontend, workflow, version, tag, or release change exists.
5. Commit the completed batch and report the final commit SHA.
