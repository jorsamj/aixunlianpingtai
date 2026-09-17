# GPU Runtime Truth Phase 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Worker Runtime and GPU resource layer with stable node identity, node-scoped GPU telemetry, Worker-to-GPU visibility, and a read-only v62 runtime projection without changing scheduling semantics.

**Architecture:** Reuse `TaskRepository`, `worker_instances`, `WorkerInstanceService`, `GPUResourceManager`, and the existing v62 API. Apply an idempotent SQLite migration to the existing GPU inventory/samples tables, add only the Worker-GPU relationship table, and keep `gpu_reservations` unchanged for Phase 1B. Resolve node identity outside shared `DATA_DIR`, then pass it through the existing Worker lease and GPU refresh lifecycle.

**Tech Stack:** Python 3, FastAPI, SQLite, NVML/nvidia-smi/Torch probes, pytest.

---

### Task 1: Stable node identity and Worker ownership

**Files:**
- Create: `platform_core/node_identity.py`
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/task_runtime/worker_instances.py`
- Modify: `platform_core/task_runtime/__init__.py`
- Modify: `task_worker.py`
- Test: `tests/unit/task_runtime/test_gpu_runtime_truth.py`

- [x] Write focused failing tests for `MC_NODE_ID`, node-local persisted fallback, Worker `node_id`, and legacy Worker-row migration.
- [x] Verify the focused tests fail for missing Phase 1A behavior.
- [x] Implement cross-platform node identity resolution and extend the existing Worker lease/runtime row additively.
- [x] Re-run the focused tests.

### Task 2: Node-scoped GPU inventory and Worker visibility

**Files:**
- Modify: `platform_core/gpu_resources.py`
- Modify: `platform_core/task_runtime/repository.py`
- Test: `tests/unit/task_runtime/test_gpu_runtime_truth.py`

- [x] Add failing contracts proving two nodes can both own physical index 0, one node refresh cannot invalidate another, Worker logical indices follow `CUDA_VISIBLE_DEVICES`, stale metrics are not fresh, and Torch fallback has no fabricated telemetry.
- [x] Verify the new contracts fail against the global inventory implementation.
- [x] Add the idempotent inventory/sample migration and `worker_gpu_visibility` table; update only the current node and current Worker visibility during refresh.
- [x] Re-run focused contracts and existing GPU lifecycle tests.

### Task 3: Read-only GPU Runtime API

**Files:**
- Modify: `platform_core/gpu_resources.py`
- Modify: `app.py`
- Test: `tests/api/test_gpu_runtime_truth.py`
- Test: `tests/api/test_worker_runtime_truth.py`

- [x] Add a failing API contract for node-scoped nodes, Workers, GPUs, visibility, telemetry freshness, and no synthetic Windows GPU.
- [x] Verify the API contract fails because the endpoint/projection is absent.
- [x] Implement `GET /api/v62/gpu-runtime` as a read-only projection and retain the existing `/api/v62/gpu-resources` compatibility response.
- [x] Re-run the focused API tests.

### Task 4: Minimum verification and handoff

**Files:**
- Modify: `docs/CODEX_CURRENT_STATE.md`

- [x] Run only the focused unit/API tests plus existing Worker/GPU lifecycle guards.
- [x] Compile affected Python modules.
- [x] Update the handoff with `GPU Runtime Truth Phase 1A — IMPLEMENTED + BASIC TESTS; REAL MULTI-NODE NVIDIA ACCEPTANCE PENDING` and explicit Phase 1B boundaries.
- [ ] Run `git diff --check`, confirm `VERSION.txt` remains `42.24.0`, review the scoped diff, commit, push, and inspect directly triggered CI.
