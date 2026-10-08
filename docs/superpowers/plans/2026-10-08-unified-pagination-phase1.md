# Unified Pagination Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate repeated full training-compatibility evaluation during paging and ship the single reusable pagination UI on the training material surfaces.

**Architecture:** A bounded revision-keyed memoization wraps the existing compatibility evaluator without becoming training truth. Existing cursor consumers remain supported while page/page_size requests use the same repository filters and stable ordering. A pure pagination module renders controls and delegates page changes to each existing business runtime.

**Tech Stack:** Python 3, FastAPI, SQLite, vanilla ES modules, Node test runner, Playwright.

---

### Task 1: Lock the compatibility memoization contract

**Files:**
- Modify: `tests/api/test_training_material_selection_summary_api.py`
- Modify: `platform_core/training_compatibility.py`
- Modify: `platform_core/training_material_picker_api.py`

- [ ] **Step 1: Write failing tests for repeated pages and invalidation**

Add tests that instrument `evaluate_training_compatibility` and assert page 1, page 2, and a filtered page of the same request perform one expensive evaluation; then update AnnotationRepository and assert the next request performs a second evaluation.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest tests/api/test_training_material_selection_summary_api.py -k "compatibility and (cache or page)" -q`

Expected: failures show repeated evaluator calls or missing page metadata.

- [ ] **Step 3: Implement the bounded revision-keyed projection**

Add a private `@lru_cache(maxsize=8)` evaluator whose key contains canonical request JSON, algorithm JSON, Material revision, Annotation revision, and hashes of label/dataset metadata. Strip paging/filter fields before key construction. Expose a wrapper used only by the read API.

- [ ] **Step 4: Add page metadata while preserving cursor input**

Extend `compatibility_page` with optional `page` and `page_size`. Return `page`, `page_size`, `total`, `total_pages`, `has_previous`, `has_next`, and the legacy `next_cursor`. Reject invalid or out-of-range pages.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/api/test_training_material_selection_summary_api.py tests/unit/test_training_label_contract.py -q`

Expected: all selected tests pass and the cache test records one evaluation before mutation, two after mutation.

### Task 2: Add real page-number querying to MaterialRepository and picker API

**Files:**
- Modify: `tests/unit/test_material_repository.py`
- Modify: `tests/api/test_training_material_selection_summary_api.py`
- Modify: `platform_core/material_repository.py`
- Modify: `platform_core/training_material_picker_api.py`

- [ ] **Step 1: Write failing repository/API page tests**

Cover first, middle, final, zero-result and page-overflow cases with stable `created_at,id` ordering. Assert an existing cursor request remains unchanged.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/unit/test_material_repository.py tests/api/test_training_material_selection_summary_api.py -k "page_number or cursor_compatibility" -q`

Expected: page arguments or response metadata are missing.

- [ ] **Step 3: Implement optional page/page_size paths**

Use the existing `_filters` SQL builder. The page path adds `LIMIT ? OFFSET ?`; the cursor path keeps the current keyset predicate. Both return the same canonical rows and authoritative count.

- [ ] **Step 4: Verify repository/API GREEN**

Run: `python -m pytest tests/unit/test_material_repository.py tests/api/test_training_material_selection_summary_api.py -q`

Expected: all tests pass, including legacy cursor tests.

### Task 3: Build the single pagination UI component

**Files:**
- Create: `static/modules/pagination.js`
- Create: `tests/frontend/pagination.test.mjs`
- Modify: `static/main.mjs`
- Modify: `static/styles.css`

- [ ] **Step 1: Write failing pure-component tests**

Test zero/one/two/100+ pages, ellipsis layout, integer validation, out-of-range errors, loading/disabled semantics, page-size changes, Enter submission, and two independent mounted instances.

- [ ] **Step 2: Run tests and confirm RED**

Run: `node --test tests/frontend/pagination.test.mjs`

Expected: module-not-found or missing export failure.

- [ ] **Step 3: Implement pure normalization/token/render functions and mount**

Export `normalizePagination`, `paginationTokens`, `renderPagination`, and `mountPagination`. The mount accepts callbacks and never imports or calls a business API.

- [ ] **Step 4: Install one public owner and shared styles**

Expose the module as `window.PlatformCore.pagination` from `main.mjs`. Add responsive `.platform-pagination` styles with focus-visible, disabled and loading states.

- [ ] **Step 5: Run component tests and JS syntax checks**

Run: `node --test tests/frontend/pagination.test.mjs && node --check static/modules/pagination.js && node --check static/main.mjs`

Expected: all pass with no syntax errors.

### Task 4: Migrate training picker and compatibility modal

**Files:**
- Modify: `tests/frontend/training-material-picker-runtime.test.mjs`
- Modify: `tests/frontend/training-material-summary-runtime.test.mjs`
- Modify: `static/modules/training-material-picker-runtime.js`
- Modify: `static/modules/training-material-summary-runtime.js`

- [ ] **Step 1: Write failing integration-contract tests**

Assert both runtimes call the shared pagination owner, send page/page_size, reset to page 1 on filters, expose authoritative total/total_pages, and retain AbortController/sequence stale-response protection.

- [ ] **Step 2: Run tests and confirm RED**

Run: `node --test tests/frontend/training-material-picker-runtime.test.mjs tests/frontend/training-material-summary-runtime.test.mjs`

Expected: shared component and page query assertions fail.

- [ ] **Step 3: Update business runtimes**

Replace hand-built previous/next markup with `PlatformCore.pagination.mount`. Keep rows, selection, cache and requests owned by their current runtimes. Search/label/issue filters reset page to 1; page-size changes do likewise.

- [ ] **Step 4: Verify focused frontend GREEN**

Run: `node --test tests/frontend/pagination.test.mjs tests/frontend/training-material-picker-runtime.test.mjs tests/frontend/training-material-summary-runtime.test.mjs tests/frontend/training-submit.test.mjs`

Expected: all pass.

### Task 5: Performance and browser evidence

**Files:**
- Create: `tests/api/test_training_compatibility_paging_performance.py`
- Modify: `tests/browser/training-material-picker-performance.spec.mjs`
- Modify: `tests/browser/training-label-selector.spec.mjs`

- [ ] **Step 1: Add 1k/10k/20k bounded-I/O tests**

Generate lightweight canonical records and assert the first compatibility calculation uses batched reads while repeated page/filter requests do not increase full-evaluation or Material/Annotation batch-read counters.

- [ ] **Step 2: Run performance tests**

Run: `python -m pytest tests/api/test_training_compatibility_paging_performance.py -q`

Expected: three sizes pass without returning complete issue arrays to the client.

- [ ] **Step 3: Add representative browser smoke**

Verify numeric page click, direct page input, Enter, loading disable, filter reset, and a stale earlier response not replacing the latest page.

- [ ] **Step 4: Run focused Playwright**

Run: `npx playwright test tests/browser/training-material-picker-performance.spec.mjs tests/browser/training-label-selector.spec.mjs`

Expected: selected browser cases pass.

### Task 6: Version, documentation, commit, push and exact-HEAD CI

**Files:**
- Modify: `VERSION.txt`
- Modify: `AGENTS.md`
- Modify: `docs/codex-handoff.md`
- Modify: `docs/CODEX_CURRENT_STATE.md`
- Modify: `docs/PROJECT_HANDOFF_CURRENT.md`
- Modify: `docs/TECH_DEBT_CLOSURE_V42_25.md`

- [ ] **Step 1: Record implementation truth and remaining phases**

Set VERSION to `42.24.303`. Document actual test results, the cache invalidation contract, page/cursor compatibility, and that high-frequency/remaining platform lists continue in phases 2 and 3.

- [ ] **Step 2: Run final focused verification**

Run the directly affected Python and frontend suites, Python compile/import checks, JavaScript syntax checks, and `git diff --check`.

- [ ] **Step 3: Commit and push**

Commit message: `feat: unify training pagination`

Push non-force to `feature/external-algorithm-publishing` after rechecking its remote parent.

- [ ] **Step 4: Verify exact HEAD**

Wait for every workflow and check-run on the pushed SHA to reach a terminal state. Treat queued, in_progress, cancelled and failure as not passing; inspect any related failure logs.
