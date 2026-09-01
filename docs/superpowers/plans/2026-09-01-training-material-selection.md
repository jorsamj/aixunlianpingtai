# Training Material Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace dataset-level training selection with exact per-image selection while retaining durable background training, reproducible validation/test splits, and leakage protection.

**Architecture:** The browser builds an explicit material-ID request. `platform_core.training_splits` validates and splits only those IDs, and the durable `TrainingHandler` persists the resulting immutable snapshot. Existing task scheduling and training execution remain unchanged.

**Tech Stack:** Vanilla JavaScript ES modules, FastAPI/Pydantic, Python dataclasses, SQLite-backed task runtime, Node test runner, pytest.

---

### Task 1: Material split contract

**Files:**
- Modify: `platform_core/training_splits.py`
- Test: `tests/unit/test_training_splits.py`

- [ ] Add failing tests proving random mode uses only `train_image_ids`, independent mode uses disjoint `train_image_ids` and `test_image_ids`, and unrequested images never enter a manifest.
- [ ] Run `pytest tests/unit/test_training_splits.py -q` and confirm failures refer to the missing material-ID contract.
- [ ] Replace dataset fields in `SplitRequest` with material ID fields and select rows by exact ID.
- [ ] Run `pytest tests/unit/test_training_splits.py -q` and confirm all split tests pass.

### Task 2: Durable API and Worker payload

**Files:**
- Modify: `app.py`
- Modify: `platform_core/training_tasks.py`
- Test: `tests/api/test_training_request.py`
- Test: `tests/integration/test_training_task_worker.py`

- [ ] Add failing API tests that submit material IDs and verify persisted payloads contain exact selections, plus rejection tests for empty and overlapping selections.
- [ ] Add a failing Worker test proving a non-selected image from the same legacy dataset cannot enter the snapshot.
- [ ] Run the targeted API and integration tests and confirm the expected contract failures.
- [ ] Add `test_image_ids`, validate the material split request, persist schema version 3, and construct the Worker `SplitRequest` from image IDs.
- [ ] Run the targeted tests and confirm they pass.

### Task 3: Browser payload builder

**Files:**
- Modify: `static/modules/training.js`
- Test: `tests/frontend/training.test.mjs`

- [ ] Add failing tests for exact train/test image IDs, deduplication, empty selection, overlap rejection, and random mode dropping independent test IDs.
- [ ] Run `node --test tests/frontend/training.test.mjs` and confirm the new tests fail for dataset-based output.
- [ ] Update `buildTrainingPayload` to emit `train_image_ids` and `test_image_ids` and remove legacy dataset fields.
- [ ] Run the frontend test and confirm it passes.

### Task 4: Material picker UI

**Files:**
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Test: `tests/frontend/training.test.mjs`

- [ ] Add source assertions for default-empty material selection, role-aware picker controls, OR label filtering, pagination, select-filtered, select-all, invert-filtered, and clear-all actions.
- [ ] Run the frontend test and confirm it fails against the current Durable v2 dataset checkboxes.
- [ ] Replace the final split override with a role-aware, paginated material picker and submit the exact selected IDs.
- [ ] Run the frontend test and the complete Node test suite.

### Task 5: End-to-end verification

**Files:**
- Test: `tests/api/test_training_request.py`
- Test: `tests/integration/test_training_task_worker.py`

- [ ] Run the complete Python test suite and confirm no regressions.
- [ ] Create a real durable training request against the running service using a small exact material selection.
- [ ] Verify `payload.json`, `snapshot.json`, task status, and job detail contain only the selected IDs and consistent counts.
- [ ] Restart the service, verify version/static assets, and confirm the platform is ready on port 8012.

