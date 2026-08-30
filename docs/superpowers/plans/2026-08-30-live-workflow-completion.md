# Live Workflow Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the remaining differences between the live Windows UI and the required training, AI labeling, navigation, and conversion workflows.

**Architecture:** Add missing configuration data to the prepared startup snapshot, then apply a final frontend compatibility layer after all legacy render layers are defined. Keep vendor conversion fail-closed and improve its route to resource configuration.

**Tech Stack:** FastAPI, vanilla JavaScript ES modules, Node test runner, Playwright, pytest.

---

### Task 1: Bootstrap model configurations

**Files:**
- Modify: `app.py`
- Test: `tests/api/test_model_configs.py`

- [ ] Add a failing API test that creates a default model configuration, reads `/api/v53/bootstrap/snapshot`, and expects `model_configs` with no plaintext API key.
- [ ] Run `pytest tests/api/test_model_configs.py -q` and confirm the new assertion fails because the field is missing.
- [ ] Add sanitized model configuration items to `_v53_build_snapshot`.
- [ ] Apply `snapshot.model_configs` to `state.modelConfigs` in `static/app.js`.
- [ ] Re-run the focused API test and confirm it passes.

### Task 2: Truthful training initialization

**Files:**
- Modify: `static/app.js`
- Test: `tests/browser/training-quality-reports.spec.mjs`

- [ ] Change the browser test to require `0 张` immediately after opening a training task.
- [ ] Add an assertion that a versioned algorithm never displays `YOLO11n 目标检测`, including before latest-version reconciliation completes.
- [ ] Run the focused browser test and confirm both assertions fail against the current UI.
- [ ] Initialize `state.train429Selected` as an empty set.
- [ ] Lock the iterative engine from the newest version already present in the algorithm response, show a loading/reconciliation state, and replace it only with the authoritative API response.
- [ ] Re-run the focused browser test and confirm it passes.

### Task 3: Module cache and AI reference performance

**Files:**
- Modify: `static/main.mjs`
- Modify: `static/index.html`
- Modify: `static/app.js`
- Test: `tests/browser/model-and-conversion.spec.mjs`

- [ ] Add a test that loads the real page twice and requires `window.PlatformCore.materials.labelDisplay` to be available without module errors.
- [ ] Add a test that selects a reference image and expects the input and translated chips to update without replacing the reference grid root.
- [ ] Run the focused browser test and confirm the current implementation fails.
- [ ] Add one shared version query to all child imports in `main.mjs` and bump the module URL in `index.html`.
- [ ] Limit the initial reference grid and update the selected card in place before recomputing labels.
- [ ] Re-run the focused browser test and confirm it passes.

### Task 4: Mobile navigation and deployment-resource entry

**Files:**
- Modify: `static/app.js`
- Test: `tests/browser/core-actions.spec.mjs`
- Test: `tests/browser/model-and-conversion.spec.mjs`

- [ ] Add a narrow-viewport browser assertion that navigation removes the drawer overlay before a main-page action is clicked.
- [ ] Add a conversion-dialog assertion for a direct `配置部署资源` action when no compatible vendor resource is ready.
- [ ] Run both focused specs and confirm the assertions fail.
- [ ] Wrap final `setPage` behavior to close the mobile drawer after navigation.
- [ ] Add the deployment-resource action to the vendor conversion empty state and route it to `部署资源`.
- [ ] Re-run both focused specs and confirm they pass.

### Task 5: Full verification

**Files:**
- Verify only.

- [ ] Run `python -m pytest -q`.
- [ ] Run `npm test`.
- [ ] Run the full browser suite.
- [ ] Reload `http://127.0.0.1:8012/` and manually verify training, AI model visibility, reference labels, navigation, and conversion empty-state routing.
- [ ] Run `git diff --check`, inspect `git status --short`, and commit only source/tests/docs; leave the local `yolo11n.pt` binary untracked.

