# ZIP Cancellation, Label Review and Cache Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete safe pre-commit ZIP cancellation, redesign the label review workspace, fix startup readiness, and remove measured duplicate requests without adding a second state owner.

**Architecture:** Extend the existing v19 job and multipart state machines. The server remains authoritative; the browser sends one cancel intent and reconciles. UI and caching changes stay in the existing ZIP runtime, page request scope, and PollRegistry boundaries.

**Tech Stack:** FastAPI/Python, SQLite-backed repositories, vanilla ES modules, Node test runner, Playwright.

---

### Task 1: Establish failing cancellation contracts

**Files:**
- Modify: `tests/api/test_v19_multipart_controls.py`
- Modify: `tests/api/test_v19_import_failure_rollback.py`
- Modify: `tests/frontend/zip-import-durable-runtime.test.mjs`

- [ ] Add one API flow covering selecting/queued cancellation, idempotency and sibling isolation.
- [ ] Add one API flow proving DB_COMMIT refuses cancellation.
- [ ] Add one frontend flow proving one cancel action aborts only its own XHR and reconciles server truth.
- [ ] Run the focused tests and confirm the new assertions fail for the missing behavior.

### Task 2: Implement one server-side ZIP cancel service

**Files:**
- Modify: `app.py`
- Modify: `platform_core/zip_multipart.py` only if repository semantics are insufficient.

- [ ] Add a task-owned cleanup helper with an explicit file allowlist.
- [ ] Add an idempotent `/import/jobs/{job_id}/cancel` endpoint.
- [ ] Reuse multipart cancel for upload states and stop fencing for Worker states.
- [ ] Add cancellation checks to merge/verify/scan callbacks and guard terminal writes.
- [ ] Preserve `job.json`; reject DB_COMMIT/done cancellation.
- [ ] Run API/unit tests until green.

### Task 3: Use the unified cancel contract in the browser

**Files:**
- Modify: `static/modules/zip-import-runtime.js`
- Modify: `static/modules/upload-task-center.js` only if an action hook is missing.
- Modify: `tests/frontend/zip-import-durable-runtime.test.mjs`

- [ ] Route every non-terminal ZIP cancel button to the canonical endpoint.
- [ ] Abort only the selected upload controller and clear only that task's caches/Blob URLs.
- [ ] Keep “cancel all active” as a confirmed loop over independent server requests.
- [ ] Never render final success before server confirmation.
- [ ] Run focused frontend tests.

### Task 4: Fix startup readiness and duplicate reconciliation

**Files:**
- Modify: `tests/browser/zip-import-refresh-recovery.spec.mjs`
- Modify: `static/zip-import-bootstrap.mjs` only if the real UI needs an admission guard.
- Modify: `static/modules/zip-import-runtime.js`
- Modify: `tests/frontend/zip-import-durable-runtime.test.mjs`

- [ ] Make the browser fixture wait on the canonical init/project readiness.
- [ ] Reproduce the old failure and verify upload requests are emitted.
- [ ] Make `maybeStart` report whether it mutated server state.
- [ ] Skip the second list GET when reconciliation is observation-only.
- [ ] Record before/after request counts in the browser test output.

### Task 5: Redesign the label review workspace

**Files:**
- Modify: `static/modules/zip-import-runtime.js`
- Modify: `static/modules/label-mapping-review.js`
- Modify: `static/styles.css`
- Modify: `tests/frontend/zip-label-evidence-and-simple-training-ui.test.mjs`
- Modify: `tests/browser/zip-import-refresh-recovery.spec.mjs`

- [ ] Add semantic summary/header, mapping list, preview panel and sticky footer markup.
- [ ] Preserve real sample/box rendering and canonical label creation flow.
- [ ] Disable confirm until every source label has a valid mapping.
- [ ] Add responsive rules for 1366×768 and narrow screens.
- [ ] Run focused frontend and Playwright tests.

### Task 6: Verify cache invalidation and affected contracts

**Files:**
- Modify only proven duplicate request owners.
- Test: `tests/browser/page-loading-performance.spec.mjs`

- [ ] Run page A → B → A request inventory.
- [ ] If a duplicate is observed, repair it in the existing page owner and add one high-value assertion.
- [ ] Verify ZIP completion invalidates only materials/labels/quality and cancellation only its job state.
- [ ] Run ZIP, label normalization, training input integrity and navigation tests.

### Task 7: Final verification and handoff

- [ ] Run syntax checks and `git diff --check`.
- [ ] Run focused Node, pytest and Playwright suites with exact pass/fail counts.
- [ ] Inspect `git status`, `HEAD`, `VERSION.txt` and all diffs.
- [ ] Document completed stages, non-cancellable commit boundary, test evidence and push readiness.
- [ ] Do not push, deploy, merge main or modify production data.
