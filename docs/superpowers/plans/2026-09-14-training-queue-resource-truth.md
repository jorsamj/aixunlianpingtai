# Training Queue / Waiting Resource Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the training list distinguish a runnable queue from unavailable Worker/resources without changing durable task status or inventing an exact Scheduler rank.

**Architecture:** Extend the existing task-runtime public read projection with Worker lease/capability awareness, keep Scheduler admission reasons authoritative, and pass conservative proof metadata through the existing training job overlay. Keep the existing TrainingTaskRuntime and PollRegistry owners; only adjust their rendering of server-owned fields.

**Tech Stack:** Python, SQLite, FastAPI, JavaScript ES modules, Node test runner, pytest.

---

### Task 1: Specify the backend read projection

**Files:**
- Modify: `tests/unit/task_runtime/test_public_projection.py`
- Modify: `tests/api/test_training_unified_task_overlay.py`

- [ ] Add focused contracts creating real `worker_instances` leases for: no online Worker, no `TRAINING` task kind, missing required capability, compatible Worker recovery, preserved Scheduler admission reason, valid queued Worker, and remote routing exclusion.
- [ ] Assert durable `tasks.status` remains `QUEUED` and no GET-time projection changes `stage`.
- [ ] Assert `resource_pool_key`, `resource_pool_label`, and `resource_queue_position_exact` are server-derived.
- [ ] Run only these focused tests with a 120-second process timeout; expected initial result is failure on missing compatibility projection fields/behavior.

### Task 2: Add conservative Worker compatibility and queue proof

**Files:**
- Modify: `platform_core/task_runtime/worker_instances.py`
- Modify: `platform_core/task_runtime/public.py`
- Modify: `platform_core/task_runtime/__init__.py`

- [ ] Add a sanitized online-Worker snapshot helper that reuses the existing `worker_instances` table and expiry rule.
- [ ] Add a read-only training queue projection that evaluates `TRAINING` registration and capability supersets without writing task rows.
- [ ] Exclude `training:remote:*` from local Worker inference and return an explicit remote-routing-unavailable reason.
- [ ] Preserve the existing resource-scoped numeric position, but mark exactness true only when no compatible online Worker can also claim a queued training task under another resource key; uncertainty must produce `false`.
- [ ] Return backend-owned pool labels for CPU, GPU auto, concrete GPU index, and remote server requests.
- [ ] Do not change `TaskRepository.claim_next()`, Scheduler ordering/admission, or the `worker_instances` schema.

### Task 3: Wire the existing training runtime overlay

**Files:**
- Modify: `app.py`
- Modify: `tests/api/test_training_unified_task_overlay.py`

- [ ] Have `enrich_job_runtime()` consume the read-only training queue projection for queued durable training tasks.
- [ ] Map projected `WAITING_RESOURCE` to the existing legacy-compatible `waiting` UI value and projected `QUEUED` to `queued`.
- [ ] Pass through `resource_pool_key`, `resource_pool_label`, and `resource_queue_position_exact` without parsing them in the browser.
- [ ] Preserve running/terminal durable truth, worker identity, lease, progress, and existing GPU admission reason behavior.
- [ ] Run the focused backend tests; expected result is all focused cases passing without Scheduler or schema changes.

### Task 4: Render honest training queue metadata

**Files:**
- Modify: `static/modules/training-task-runtime.js`
- Modify: `tests/frontend/training-task-runtime.test.mjs`

- [ ] Change the visible `waiting` label from `等待中` to `等待资源`.
- [ ] Render the backend `resource_pool_label` for queued/waiting tasks.
- [ ] Render `队列第 N 位` only when `resource_queue_position_exact === true`.
- [ ] For a non-exact queued rank, render `排队中` without a number; for waiting resource, prioritize the backend reason and suppress rank emphasis.
- [ ] Keep the existing TrainingTaskRuntime refresh and PollRegistry one-shot lifecycle unchanged.
- [ ] Run only `node --test tests/frontend/training-task-runtime.test.mjs`; expected result is the focused rendering and existing refresh contracts passing.

### Task 5: Document and minimally verify the batch

**Files:**
- Modify: `docs/CODEX_CURRENT_STATE.md`
- Keep unchanged: `VERSION.txt`

- [ ] Record the implementation HEAD placeholder, queued/waiting decision source, resource-scoped rank limitation, exactness proof, compatible-pool definition, frontend fields, files, focused checks, and explicit GPU/remote boundaries.
- [ ] Run Python compilation for the affected modules and `node --check` for the affected JavaScript module.
- [ ] Run no full pytest, no Real Chrome suite, and no unrelated regression suite unless a focused failure provides a concrete signal.
- [ ] Confirm `VERSION.txt` is still `42.24.0`, the worktree contains no unrelated changes, and Scheduler claim semantics/Worker schema are unchanged.
- [ ] Commit the single scoped product batch on `refactor/frontend-runtime-stabilization`; do not merge `main`, tag, or release.

