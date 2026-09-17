# Training Task Auto-Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the visible training task list follow real batch backend status and progress automatically, while stopping all training polling for paused-only or terminal-only lists and after navigation away.

**Architecture:** Keep `GET /api/projects/{project_id}/jobs` and `TrainingTaskRuntime.refresh()` as the batch truth/read/patch path. Convert only the existing `training-jobs` PollRegistry entry from a fixed interval to a 2-second managed one-shot that re-arms from the latest state; PollRegistry alone creates, clears, and re-arms the timer.

**Tech Stack:** Browser ES modules, existing PollRegistry/TrainingTaskRuntime, Node.js built-in test runner, pytest/FastAPI unit contracts.

---

## File structure

- Modify `tests/frontend/poll-registry.test.mjs`: lock down one-shot lifecycle, dynamic-state re-arm, paused/terminal stop, navigation cleanup, and mutation/navigation reactivation.
- Modify `tests/frontend/training-task-runtime.test.mjs`: prove successive batch API responses replace stale status/progress/epoch/elapsed table output without a full-page render.
- Modify `static/modules/poll-registry.js`: make PollRegistry the sole training one-shot lifecycle owner.
- Modify `static/main.mjs`: bump only the PollRegistry module cache key so browsers load the corrected owner.
- Modify `docs/CODEX_CURRENT_STATE.md`: record the completed product behavior, truth source, lifecycle, files, tests, and explicit exclusions.

### Task 1: Add failing auto-refresh contracts

**Files:**
- Modify: `tests/frontend/poll-registry.test.mjs`
- Modify: `tests/frontend/training-task-runtime.test.mjs`

- [ ] **Step 1: Replace the interval contract with a failing one-shot lifecycle contract**

Change the training polling test to stub `setTimeout`/`clearTimeout`, return successive running then completed jobs through the existing refresh stub, and assert:

```js
assert.deepEqual(runtime.snapshot().find(row => row.key === 'training-jobs'), {
  key: 'training-jobs', owners: ['训练任务'], active: true, managed: true, delay: 2000,
});
await timeouts.get(firstTimer).callback();
assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), true);
state.jobs = [{id: 'j1', status: 'completed'}];
await timeouts.get(secondTimer).callback();
assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), false);
```

Add focused cases showing each of `done`, `finished`, `completed`, `failed`, `stopped`, `cancelled`, and `canceled` leaves no timer, paused-only leaves no timer, navigation to `检测台` clears the timer, and a training-page lifecycle callback can restore a timer after a resume refresh returns `running`.

- [ ] **Step 2: Add a failing successive-response table patch contract**

Use a minimal fake `.train428-page` DOM, call `TrainingTaskRuntime.refresh()` three times with backend responses for running Epoch 3/100 at 3%, running Epoch 4/100 at 4%, and completed Epoch 100/100 at 100%, then assert the table body changes accordingly and `window.updateTrainingJobTable`/full-page render is never invoked:

```js
assert.match(body.innerHTML, /3\/100 · 3%/);
assert.match(body.innerHTML, /4\/100 · 4%/);
assert.match(body.innerHTML, /已完成/);
assert.match(body.innerHTML, /100\/100 · 100%/);
assert.doesNotMatch(body.innerHTML, /训练中/);
assert.equal(fullRenders, 0);
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run:

```powershell
node --test tests/frontend/poll-registry.test.mjs tests/frontend/training-task-runtime.test.mjs
```

Expected: the new one-shot/lifecycle assertions fail against the existing fixed interval; unrelated existing assertions remain green.

- [ ] **Step 4: Commit the valid RED tests**

```powershell
git add tests/frontend/poll-registry.test.mjs tests/frontend/training-task-runtime.test.mjs
git commit -m "test(training): require truthful list auto refresh"
```

### Task 2: Implement PollRegistry-owned training one-shot

**Files:**
- Modify: `static/modules/poll-registry.js`
- Modify: `static/main.mjs`
- Test: `tests/frontend/poll-registry.test.mjs`
- Test: `tests/frontend/training-task-runtime.test.mjs`

- [ ] **Step 1: Define the dynamic polling predicate in PollRegistry**

Use only these re-arm states:

```js
const TRAINING_POLL_STATUSES = new Set(['queued', 'waiting', 'pending', 'running']);

function trainingTaskNeedsPolling(task) {
  return TRAINING_POLL_STATUSES.has(String(task?.status || '').toLowerCase());
}
```

Paused remains visible through `TrainingTaskRuntime.ACTIVE_STATUSES`, but is deliberately excluded from polling.

- [ ] **Step 2: Replace the training interval with a managed one-shot**

Make `trainingOwners` contain only `训练任务`. In `replaceTrainingJobTimer()`, clear the existing key, require the training page, project id, and at least one dynamically changing task, then schedule:

```js
return registry.startTimeout('training-jobs', trainingOwner, async () => {
  const current = state();
  if (String(current.page || '') !== trainingOwner || !current.project?.id) return;
  try {
    if (typeof window.TrainingTaskRuntime?.refresh === 'function') {
      await window.TrainingTaskRuntime.refresh({render: true, source: 'poll'});
    } else if (typeof window.refreshJobsOnly === 'function') {
      await window.refreshJobsOnly();
    }
  } catch (_) {
    // Preserve last truthful state; an active last-known task may retry.
  } finally {
    replaceTrainingJobTimer();
  }
}, 2000);
```

Because `startTimeout()` unregisters before invoking the callback, the `finally` creates at most one replacement. Latest state controls whether a replacement exists.

- [ ] **Step 3: Keep reactivation owned by PollRegistry**

Add a scoped `afterNavigate(page)` method to the PollRegistry runtime:

```js
afterNavigate(page) {
  if (String(page || state().page || '') === trainingOwner) return replaceTrainingJobTimer();
  return null;
},
```

The existing navigation/action wrapper calls this after the resume mutation's forced refresh. PollRegistry then sees the refreshed `running`/queued state and creates the one-shot; `TrainingTaskRuntime` creates no timer.

- [ ] **Step 4: Bump the PollRegistry browser cache key**

Change the import in `static/main.mjs` from `poll-registry.js?v=422517` to `poll-registry.js?v=422518`. Do not change the formal version.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run:

```powershell
node --test tests/frontend/poll-registry.test.mjs tests/frontend/training-task-runtime.test.mjs
```

Expected: all focused tests pass.

- [ ] **Step 6: Run syntax checks and one existing backend truth regression**

Run:

```powershell
node --check static/modules/poll-registry.js
node --check static/modules/training-task-runtime.js
node --check static/main.mjs
python -m pytest tests/api/test_training_unified_task_overlay.py -q
```

Expected: syntax checks exit 0 and the existing training overlay regression passes.

- [ ] **Step 7: Commit the product change**

```powershell
git add static/modules/poll-registry.js static/main.mjs
git commit -m "fix(training): auto refresh truthful task progress"
```

### Task 3: Record and verify closure

**Files:**
- Modify: `docs/CODEX_CURRENT_STATE.md`

- [ ] **Step 1: Add the concise closure record**

Record the implementation HEAD, `/api/projects/{project_id}/jobs` truth source, 2-second PollRegistry one-shot lifecycle, paused/terminal/no-page stop behavior, core files, focused test results, and the exclusions: no GPU scheduling, pause/resume feature work, ETA redesign, detail refactor, backend training change, SSE, or Real Chrome.

- [ ] **Step 2: Run final minimum verification**

Run the focused frontend files, the existing backend overlay regression, syntax checks, `git diff --check`, `git status --short`, and confirm `VERSION.txt` is exactly `42.24.0`.

- [ ] **Step 3: Commit documentation**

```powershell
git add docs/CODEX_CURRENT_STATE.md docs/superpowers/plans/2026-09-14-training-task-auto-refresh.md
git commit -m "docs: record training task auto refresh"
```

- [ ] **Step 4: Re-check remote and publish without rewriting history**

Fetch origin, confirm no unexpected remote divergence, and push the long-lived branch normally. Do not merge main, rebase, force-push, tag, release, or change `VERSION.txt`.
