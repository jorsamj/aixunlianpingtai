# Algorithm, Training Task, and Advanced Navigation UI Implementation Plan

> Execute this plan in the current worktree with focused tests only. Keep all pushes until the complete batch, documentation, screenshots, and diff review are finished.

**Goal:** Establish one formal navigation owner, one algorithm-list UI owner, and a strict task-truth/presentation split while delivering the approved enterprise list UI without new framework dependencies.

**Architecture:** `renderNav` owns menu DOM; `AlgorithmListRuntime` owns the algorithm page and consumes a read-only provider from the external platform truth owner; `TrainingTaskRuntime` owns task truth/actions while `TrainingTaskVisibilityRuntime` owns only view state and keyed DOM patches. Compatibility entry points delegate directly to final owners.

**Stack:** Existing HTML, CSS, JavaScript ES modules, Node test runner, Playwright, existing FastAPI application and browser fixtures.

---

## Task 1: Lock repository architecture constraints

**Files:**
- Modify: `AGENTS.md`
- Test: focused source assertion added with navigation owner tests

1. Add a failing source assertion that requires the project-level one-owner/one-truth/no-nesting rule.
2. Add the approved concise constraint to `AGENTS.md`, including permitted compatibility behavior (`normalize / redirect / delegate`) and UI hierarchy (`Page → Surface → Content`).
3. Run only the new assertion and confirm it passes.

## Task 2: Make `renderNav` the sole menu owner

**Files:**
- Modify: `static/app.js`
- Modify: `static/modules/service-node-runtime.js`
- Modify: `static/main.mjs` or asset references only when cache keys require it
- Test: focused navigation frontend/browser spec

1. Add failing focused assertions for `训练资源` advanced visibility, exactly one `服务节点`, visibility-only collapse, route preservation, restored active highlight, and no ServiceNodeRuntime injector/observer.
2. Move `训练资源` from the ordinary algorithm group to the formal advanced group in `renderNav`; update only the canonical breadcrumb group label if required.
3. Delete ServiceNodeRuntime menu injection, its navigation observer, injection calls, and injected-node cleanup. Retain its page/business runtime unchanged.
4. Verify training creation still reads authoritative targets/resources while advanced navigation is collapsed.
5. Run JS syntax and only the focused navigation cases.

## Task 3: Specify pure algorithm-list view behavior with failing tests

**Files:**
- Modify: `tests/frontend/algorithm-list-runtime.test.mjs`
- Modify: `tests/frontend/external-algorithm-platform.test.mjs`
- Add/modify: focused algorithm browser spec

1. Add failing pure tests for:
   - no category filter: local algorithms remain visible;
   - applied category: only a real matching `external_category_id` passes;
   - no name/industry/tag inference;
   - draft category changes do not affect applied filters until confirm;
   - cancel restores the applied set;
   - arbitrary-depth path search and three-pane navigation;
   - sort and pagination as view state;
   - keyed patch preserves unchanged algorithm rows.
2. Add failing ownership assertions requiring legacy renderers to be delegates only and forbidding external algorithm-list DOM decorators/observers.
3. Run these tests and record the expected failures before production edits.

## Task 4: Make `AlgorithmListRuntime` the sole algorithm page UI owner

**Files:**
- Modify: `static/modules/algorithm-list-runtime.js`
- Modify: `static/app.js`
- Modify: `static/main.mjs`
- Modify: `static/modules/external-algorithm-platform.js`
- Modify: `static/styles.css`

1. Extend AlgorithmListRuntime view state with query, source, industry, type, status, applied/draft categories, sort, and pagination without copying algorithm truth.
2. Add one provider registration point for external category truth, source/status matching, sync action, and training eligibility.
3. Move shell, filter, sort, cascader presentation, table rows, More menu, pagination, skeleton/empty/error region, and keyed row patching into AlgorithmListRuntime.
4. Keep category hierarchy/path derivation pure and based only on provider categories. Persist only recent-use category IDs as a UI preference.
5. Convert `renderAlgorithms423` and `renderAlg412` to direct calls into AlgorithmListRuntime; remove their old DOM/filter/patch bodies.
6. Remove external runtime's algorithm-list decorator, MutationObserver dependence, injected filters/category bar/sync button, and list-card mutations. Expose read-only truth/actions instead.
7. Keep all algorithm business actions and training eligibility enforcement routed to existing owners.
8. Add shared semantic list-page CSS tokens and flat PageHeader/QueryFilter/DataTable/Cascader/Pagination styles.
9. Advance only the necessary module/cache keys.
10. Run the focused pure and browser algorithm-list cases until passing.

## Task 5: Specify training task view behavior with failing tests

**Files:**
- Modify: `tests/frontend/training-task-visibility-runtime.test.mjs`
- Modify: `tests/frontend/training-task-runtime.test.mjs` only for truth/action coverage
- Modify: `tests/browser/training-task-performance.spec.mjs`

1. Add failing tests for status buckets/counts derived from current jobs, search/algorithm/priority filters, pagination, and reset.
2. Assert visibility state never writes `state.jobs`, never fetches/polls, and never stores derived count truth.
3. Assert the normal table has exactly the approved ten columns and no checkbox column; batch selection appears only in temporary mode.
4. Assert shell identity survives jobs-only refresh and progress updates patch the scoped row/cell.
5. Run only these focused tests and record expected failures before production edits.

## Task 6: Upgrade the training task presentation owner

**Files:**
- Modify: `static/modules/training-task-visibility-runtime.js`
- Modify: `static/modules/training-task-runtime.js` only where row presentation/action grouping belongs to its existing exported renderer contract
- Modify: `static/styles.css`
- Modify: module/cache references as required

1. Build a single flat PageHeader, status-tab row, QueryFilter surface, table surface, and pagination in TrainingTaskVisibilityRuntime.
2. Derive all tab counts on every render from the runtime's current `state().jobs` snapshot.
3. Keep filters, sort/page, and batch selection private transient view state.
4. Preserve the existing keyed row map, progress-cell patch, clock tick, and jobs-only refresh adapter.
5. Group actions by actual status and move lower-frequency/destructive actions into More without changing endpoints or eligibility.
6. Render first-empty skeleton and regional refresh error while preserving stale data.
7. Run the focused training runtime and browser cases until passing.

## Task 7: Focused integrated browser acceptance

**Files:**
- Add/modify focused specs under `tests/browser/`

1. Run navigation flow: expand → training resources → collapse → preserve page → reopen/highlight → ordinary page → collapse/reopen; repeat for service nodes and reload uniqueness.
2. Run algorithm flow: entry/revisit, search/source/status, cascader path navigation/draft/cancel/confirm/search/clear, sort, pagination, training action, and reload.
3. Run training flow: status tabs/counts, search/algorithm/priority, query/reset, running scoped update, detail/log, supported actions, revisit cache, and batch enter/exit.
4. Re-run the four existing focused annotation P0 cases only if affected asset delivery changed.
5. Run JS syntax checks for every changed JS/MJS file.

## Task 8: Capture actual product screenshots

**Files:**
- Add: `docs/screenshots/2026-09-23-algorithm-list-default.png`
- Add: `docs/screenshots/2026-09-23-algorithm-category-cascader.png`
- Add: `docs/screenshots/2026-09-23-training-tasks-default.png`
- Add: `docs/screenshots/2026-09-23-training-tasks-multi-status.png`

1. Start only the focused local application fixture required by the browser specs.
2. Capture actual routed pages, not a static mock.
3. Inspect all four images for clipping, duplicate menu entries, stale legacy IA, nested-card regressions, missing state labels, and incorrect active navigation.

## Task 9: Update handoff truth and verify delivery

**Files:**
- Modify: `docs/CODEX_HANDOFF_2026-09-23.md`
- Modify: `docs/CODEX_CURRENT_STATE.md`
- Modify: `docs/PROJECT_HANDOFF_CURRENT.md` if its current-state sections are active

1. Record owner boundaries, no-framework decision, category semantics, navigation IA, focused results, screenshots, P0 closure, CLOSED/STALE TEST/OPEN, and the new candidate SHA without claiming full green or production acceptance.
2. Review the complete diff from remote baseline; confirm `VERSION.txt` is exactly `42.24.0`, no dependency/framework additions, no main merge, tag, or release.
3. Run the final focused verification set once.
4. Commit the complete implementation and docs coherently.
5. Fetch origin, require the long-lived branch to remain at the expected remote head, require local history to be a direct fast-forward, and push without force.
6. Read the remote head back and report both UI areas, navigation changes, tests, screenshots, commits, VERSION, and remaining confirmed production blockers.
