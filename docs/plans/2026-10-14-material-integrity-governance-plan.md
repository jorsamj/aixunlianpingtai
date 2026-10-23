# Material Integrity Governance Implementation Plan

> **For Codex:** Use the approved user specification as the design authority. Execute with test-driven development and verification checkpoints.

**Goal:** Generate and execute complete, frozen, safe deduplication plans through the existing material batch runtime.

**Architecture:** Add server-side plan preparation beside material integrity audit artifacts. Plan execution freezes its delete selection into the existing `BatchSelection` schema and publishes a normal `DELETE_INDEX` MaterialBatch. Extend the current audit UI; do not add another task owner.

**Tech Stack:** FastAPI, SQLite artifacts, existing task runtime, browser ES modules, Node/Pytest/Playwright.

---

### Task 1: Frozen plan contract

- Add failing API tests for identical duplicates, conflicts, protected references, anomalies, stale revisions, and selections larger than 500.
- Implement plan schema, deterministic keeper scoring, protection discovery, confirmation credential, and paginated preview.

### Task 2: Durable execution

- Add failing worker/API tests proving revalidation, atomic publication, `DELETE_INDEX`, retry safety, and shared-source preservation.
- Freeze plan delete IDs into the existing batch selection and publish through the existing repository/worker.

### Task 3: Existing UI extension

- Add failing frontend tests for global preview/confirm, filter scope, manual decisions, pagination, and cache invalidation.
- Extend the existing integrity modal and `MaterialBatchRuntime62`; keep per-group image/GT review.

### Task 4: Scale, browser acceptance, and commit

- Verify 5→1, 10 groups, >100 groups, >500 deletions, stale plan, protected references, conflict groups, cancellation/retry, and cross-storage safety.
- Exercise preview, confirmation, progress, and result in a real browser.
- Run focused then broader Node/Python/Playwright suites, update handoff docs, and create a separate local commit.

## Completion evidence

- Governance API/worker: 11 passed, including 5→1, 501 deletions, 120 groups over two API pages, stale revisions, confirmation credential, idempotent execute, protected references and keeper drift after queueing.
- Existing MaterialBatch regression slice: 19 passed.
- Frontend suite: 970/970 passed.
- Real Chrome: 1/1 passed with 1366×768 screenshot, exact SAFE_ALL request, preview, confirmation, background progress and terminal invalidation.
- Production history, real OSS and production-scale wall-clock performance remain NOT VERIFIED and must not be inferred from local fixtures.
