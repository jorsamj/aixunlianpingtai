# VNext Final Differential Test Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identify every remaining Windows Python and Real Chrome failure, reproduce grouped failures at `ede115e4` and baseline `30f83c48` under matched conditions, fix only proven VNext regressions, and produce release-gate evidence without pushing or changing `VERSION.txt`.

**Architecture:** Preserve the current VNext worktree and create a separate detached baseline worktree at `30f83c48`. Capture machine-readable failure artifacts, group failures by the earliest shared cause, and run the smallest representative/complete groups on both revisions. Browser reruns retain Playwright traces, console/network evidence, and failure screenshots; any product change follows red-green TDD in the current worktree only.

**Tech Stack:** Git worktrees, Python/pytest, Node.js 24, Playwright/Chrome, PowerShell, existing repository test fixtures.

---

### Task 1: Freeze environment and create the baseline workspace

**Files:**
- Create: clean managed worktree at commit `30f83c48bab39b9b8aca07f95b8481a3fbb672ec`
- Verify: `VERSION.txt`, `package-lock.json`, `requirements.txt`, Python/Node/Chrome versions

- [x] **Step 1: Record current repository and runtime identity**

Run:

```powershell
git status --short
git rev-parse HEAD
git rev-parse origin/feature/external-algorithm-publishing
python --version
python -m pip --version
node --version
npx playwright --version
```

Expected: current HEAD is `ede115e4...`, the worktree is clean before audit documentation, and `VERSION.txt` remains `42.24.355`.

- [x] **Step 2: Create a detached clean baseline worktree**

Use the Codex native worktree tool with ref `30f83c48bab39b9b8aca07f95b8481a3fbb672ec`; do not switch or reset the VNext worktree.

- [x] **Step 3: Verify matched dependencies without mutating lock files**

Run the same Python executable, Node 24 executable, environment variables, pytest command line, Playwright config, and browser channel in both worktrees. Reuse installed dependencies when lock files match; otherwise record the dependency delta before installing anything.

### Task 2: Capture all current failure evidence

**Files:**
- Create outside Git: pytest JUnit/log artifacts and Playwright result/trace artifacts
- Inspect: `pytest.ini`, `playwright.config.mjs`, failing test files

- [x] **Step 1: Re-run Windows full pytest with durable reports**

Run:

```powershell
python -m pytest -q --tb=long --junitxml=<artifact-dir>/vnext-pytest.xml *> <artifact-dir>/vnext-pytest.log
```

Expected: a complete list of node IDs, assertion messages, stacks, skips, and collection/runtime conditions. Do not infer the previous 64 failures from summary text.

- [x] **Step 2: Parse and group Python failures**

Group by shared first failing frame and prerequisite: source contract mismatch, missing optional/runtime dependency, Windows path/process semantics, port/service dependency, fixture state, nondeterminism, or product defect. Keep every failing node ID mapped to exactly one primary root cause.

- [x] **Step 3: Re-run full Chrome with trace and screenshot retention**

Run:

```powershell
npx playwright test --trace=retain-on-failure
```

Expected: exact failing titles plus Playwright error, console errors, request failures/responses, trace ZIP, and failure screenshot for each failure.

- [x] **Step 4: Check isolation and randomness**

Run each Chrome failure alone twice and once in its original file/order. Record whether it is deterministic, order-dependent, port/state-dependent, or fixed by an existing VNext change.

### Task 3: Differential baseline reproduction

**Files:**
- Modify: none in baseline worktree
- Read: current failure tests and their production call paths

- [x] **Step 1: Run one representative per Python root-cause group on baseline**

Use the exact node IDs and flags from Task 2. If baseline and VNext differ, run all members of that group on both revisions to rule out accidental grouping.

- [x] **Step 2: Run all deterministic Chrome failures on baseline**

Use the same Playwright worker count, server settings, browser channel, trace setting, and environment. Run isolated twice when either revision changes outcome.

- [x] **Step 3: Compare source and fixture deltas**

For every new-only failure, inspect:

```powershell
git diff 30f83c48..ede115e4 -- <test-file> <production-files>
```

Expected: evidence identifies whether VNext changed production behavior, changed the test contract, or merely exposed shared environment/state.

### Task 4: Apply only necessary fixes

**Files:**
- Modify: only files directly proven by Task 3
- Test: the exact reproducer before and after each fix

- [x] **Step 1: Establish a red regression test for each VNext defect**

Run the existing failing test or add one minimal test that fails on `ede115e4` for the proven root cause. Do not delete, skip, loosen, or extend timeouts.

- [x] **Step 2: Implement one minimal fix per confirmed cause**

Preserve the canonical evaluation, training runtime, navigation, modal, and reporting owners. If an old fixture contradicts a documented formal API contract, update only the fixture and retain the business assertion.

- [x] **Step 3: Verify red-green and neighboring regressions**

Run the exact failing node, its containing file, and the relevant focused suite. Revert/restore the fix locally when practical to prove the regression test detects the defect.

### Task 5: Revalidate VNext business contracts and performance math

**Files:**
- Test: existing evaluation image, training evaluation, training metrics, frontend quality, training recovery, and browser diagnostic suites
- Update: current handoff/audit documents with measured evidence

- [x] **Step 1: Run the existing focused contract suites**

Verify frozen-image collision/recovery/SHA, same-image overlays, canonical scenario navigation, compact-poll epoch merge, duplicate-label class regression, and missing-versus-zero report delta.

- [x] **Step 2: Recompute the 1000 Epoch / 720 resource benchmark**

Report both comparable formulas:

```text
old minute = poll_count * full_payload
new minute = one_full_history_load + poll_count * compact_payload
```

Also report the steady-state minute after history is cached, SQLite reads per poll, first history-load cost, and maximum new-Epoch observation delay.

### Task 6: Final verification, documentation, and local commit

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/CODEX_CURRENT_STATE.md`
- Modify: `docs/FRONTEND_OWNER_MAP_V42_25.md`
- Modify: `docs/TECH_DEBT_CLOSURE_V42_25.md`
- Modify: `docs/VNEXT_MODEL_QUALITY_2026_10_13.md`
- Modify: `docs/codex-handoff.md`
- Modify: `docs/frontend-legacy-audit.md`

- [x] **Step 1: Run final affected and broad verification**

Run fresh focused Python, Node 24 frontend, focused Chrome, full pytest when feasible, and full Chrome. Read the full output and retain exact failure totals.

- [x] **Step 2: Audit repository boundaries**

Run:

```powershell
git diff --check
git diff -- VERSION.txt
git status --short
git rev-list --left-right --count origin/feature/external-algorithm-publishing...HEAD
```

Expected: no VERSION change, no push/merge/deploy, and only intentional files.

- [x] **Step 3: Commit locally only when evidence is complete**

Use one local commit for proven minimal fixes and the differential audit record. Do not push. Final report must enumerate every failure, grouped counts, baseline/current outcomes, remaining unverified production/OSS/GPU/Linux boundaries, final HEAD, and clean/dirty status.
