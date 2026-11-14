# VNext Independent Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the independently reproduced VNext evidence, navigation, polling, comparison, accessibility, A/B preview, missing-value, and visual hierarchy defects without adding a second owner.

**Architecture:** Keep `training_evaluation.py`, the existing evaluation image route, `TrainingRecoveryRuntime`, and the current quality-center renderer as the only owners. Add bounded immutable projections only at their read boundaries: snapshot identity indexing is keyed by project, snapshot digest, and file stat; training history is fetched on demand and merged into the currently open task cache while compact polling remains authoritative for live state.

**Tech Stack:** FastAPI/Python, SQLite, browser-native JavaScript/CSS, Node test runner, Playwright/Chrome, pytest.

---

### Task 1: Frozen evaluation identity

**Files:**
- Modify: `tests/api/test_evaluation_diagnostic_image.py`
- Modify: `app.py`

- [ ] Add the exact `foo` ID / `bar` stored-name collision as a failing API test, plus explicit-ID and unique historical stored-name controls.
- [ ] Run the focused tests and confirm the old route returns the wrong bytes.
- [ ] Resolve explicit IDs strictly; resolve legacy records by unique frozen `stored_name`; reject conflicting or ambiguous evidence before storage lookup.
- [ ] Re-run all diagnostic-image tests, including SHA drift, incomplete Snapshot, dimensions, and overlay-safe failures.

### Task 2: Strict class identity comparison

**Files:**
- Modify: `tests/unit/test_training_evaluation.py`
- Modify: `platform_core/training_evaluation.py`

- [ ] Add a failing comparison test with class IDs 0 and 1 sharing one display name and class 0 regressing from 0.9 to 0.1.
- [ ] Key current records by stable `class_id`; use label fallback only for unambiguous legacy records and make unresolved identities non-comparable.
- [ ] Re-run evaluation unit tests and verify the regressed class remains visible.

### Task 3: Compact polling and on-demand history

**Files:**
- Modify: `tests/unit/test_training_metrics_fd.py`
- Modify: `tests/frontend/training-recovery-runtime.test.mjs`
- Modify: `app.py`
- Modify: `platform_core/training_metrics.py`
- Modify: `static/modules/training-recovery-runtime.js`

- [ ] Add failing backend tests proving default job reads stay compact and a bounded history projection exposes a revision/cursor.
- [ ] Add failing runtime tests proving polling does not request history, history loads once per project/task/revision, and terminal tasks stop the timer.
- [ ] Extend the existing job endpoint with an optional history query and bounded incremental cursor; keep default polling compact.
- [ ] Load history on first relevant Tab, cache by project/task/revision, merge increments, and clear on project/task change.
- [ ] Benchmark 1000 Epoch + 720 sample rows before/after for bytes, SQLite history reads, Tab latency, and update delay.

### Task 4: Snapshot index reuse

**Files:**
- Modify: `tests/api/test_evaluation_diagnostic_image.py`
- Modify: `app.py`

- [ ] Add a failing 20k Snapshot test that counts JSON parses and verifies invalidation after file replacement.
- [ ] Add a process-local bounded cache of validated immutable Snapshot identity indexes keyed by project/path/stat/snapshot ID.
- [ ] Preserve per-response material lookup, storage retrieval, decode/dimension checks, and actual-byte SHA verification.
- [ ] Benchmark 24 gallery reads before/after and verify missing/changed Snapshots invalidate safely.

### Task 5: Navigation and quality comparison presentation

**Files:**
- Modify: `tests/frontend/quality-charts.test.mjs`
- Modify: `tests/browser/training-evaluation-diagnostics.spec.mjs`
- Modify: `static/app.js`

- [ ] Add failing tests for both scenario buttons reaching the existing quality-center detect Tab, missing-vs-zero deltas, and synchronized/independent A/B preview controls.
- [ ] Route both buttons through `质量中心` plus `setQualityCenterTab411('detect')`.
- [ ] Format only finite non-null deltas; keep actual zero as `0.0 pp`.
- [ ] Scope A/B controls to the active pair, add synchronized zoom/reset plus per-pane fullscreen, and retain each pane's own dimensions.

### Task 6: Accessible training Tabs

**Files:**
- Modify: `tests/frontend/training-recovery-runtime.test.mjs`
- Modify: `tests/browser/training-recovery.spec.mjs`
- Modify: `static/modules/training-recovery-runtime.js`
- Modify: `static/styles.css`

- [ ] Add failing tests for roving `tabindex`, ArrowLeft/ArrowRight/Home/End, `aria-controls`/`aria-labelledby`, focus preservation, and the mobile scroll affordance.
- [ ] Update the existing runtime in place without creating another component or poll owner.
- [ ] Verify mouse, keyboard, 375px, and reduced-motion behavior.

### Task 7: Limited visual hierarchy refinement

**Files:**
- Modify: `static/app.js`
- Modify: `static/modules/training-recovery-runtime.js`
- Modify: `static/styles.css`
- Modify: relevant browser fixtures only where needed for truthful states

- [ ] Promote the primary evaluation/training outcome, compact secondary metrics, and turn FP/FN/critical classes into direct evidence actions.
- [ ] Make the image the preview focal point, move coordinates into disclosure, and consolidate persistent controls.
- [ ] Reduce empty completed-state cards and group report outcome, epochs, stopping, evaluation, and acceptance without fabricating values.
- [ ] Capture real Chrome fixture screenshots for evaluation, errors, detail, report, comparison, and 375px.

### Task 8: Verification, documentation, and local commit

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/TECH_DEBT_CLOSURE_V42_25.md`
- Modify: `docs/CODEX_CURRENT_STATE.md`
- Modify: `docs/frontend-legacy-audit.md`
- Modify: `docs/FRONTEND_OWNER_MAP_V42_25.md`
- Modify: `docs/VNEXT_MODEL_QUALITY_2026_10_13.md`
- Modify: `docs/codex-handoff.md`

- [ ] Run affected Python/API tests, all Node frontend tests, real Chrome tests, necessary full regression, and `git diff --check`.
- [ ] Record benchmark numbers, fixture-only screenshot boundary, unresolved production OSS/history/GPU validation, and final owner map.
- [ ] Confirm `VERSION.txt` is unchanged and the worktree contains only scoped files.
- [ ] Create one local commit and verify HEAD/ahead-behind without pushing.
