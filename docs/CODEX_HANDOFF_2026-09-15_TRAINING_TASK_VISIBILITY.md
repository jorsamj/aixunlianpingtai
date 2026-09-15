# Codex Handoff — Training Task Visibility Stability / Single Final Rendering Owner

> Branch: `refactor/frontend-runtime-stabilization`
>
> Live GitHub HEAD always outranks stale SHA text in older documents. Read `docs/CODEX_READ_FIRST.md` first.

## 1. User-observed production symptom

A real A800 training task continued running and advancing in durable truth, while the browser training-task page temporarily lost the row and later showed it again.

Evidence at the time of the incident:

```text
TaskRepository: RUNNING
/jobs API: same task present and advancing
training process: alive
browser UI: row temporarily absent
later refresh/poll: row reappeared
```

Therefore this was not treated as backend task loss.

## 2. Concrete frontend ownership race found

Two different frontend paths were writing the same `state.jobs` truth:

```text
legacy loadRelated()
  GET /api/projects/{project_id}
  -> state.jobs = info.jobs

TrainingTaskRuntime
  GET /api/projects/{project_id}/jobs
  -> state.jobs = canonical training list
```

The training page also still had legacy `renderTraining423/424/425` full-table rendering while `TrainingTaskRuntime` patched the same table after focused refresh.

That meant a generic/legacy refresh could temporarily replace newer canonical training jobs with an older project aggregate, and a legacy render could then redraw the table without a still-running task. The next focused `/jobs` poll corrected the page, which matched the real symptom exactly.

## 3. Implemented fix

### 3.1 New final visibility owner

Added:

```text
static/modules/training-task-visibility-runtime.js
```

It is loaded after `static/main.mjs`, so the existing `TrainingTaskRuntime`, `PollRegistry`, navigation fencing and classic app functions are already installed.

The new runtime does not create another timer, queue or backend truth source.

Its responsibilities are narrowly limited to frontend training-list ownership:

```text
canonical jobs write path
+ final task-row rendering
+ tab classification
+ legacy loadRelated fencing
```

### 3.2 Generic `loadRelated()` can no longer own training jobs

After the visibility runtime is installed:

- On the training page, `loadRelated()` is routed to the canonical focused `/jobs` refresh.
- On other pages, legacy `loadRelated()` may still refresh datasets, labels, images, algorithms, models and other project data, but its `state.jobs` side effect is discarded/restored.
- Project-navigation request fencing remains owned by the existing `PageRequestScope`; no second request-scope implementation was added.

Result:

```text
state.jobs after runtime installation
= TrainingTaskRuntime-owned canonical training list
```

A generic project refresh can no longer remove a RUNNING task from browser state.

### 3.3 Training page has one final row-render owner

Legacy render functions remain only as shell compatibility when `.train428-page` does not yet exist.

The final task rows, active/history counts and tab state are rendered by `TrainingTaskVisibilityRuntime` from the current canonical `state.jobs`.

The runtime overrides the public `renderTraining423/424/425` entrypoints so later legacy calls cannot replace the final task rows with stale project-aggregate data.

`TrainingTaskRuntime.refresh()` is wrapped so normal PollRegistry refreshes fetch canonical `/jobs` truth without letting the older internal patch become the final DOM result. The visibility runtime then performs the final render.

The visibility runtime contains no `setTimeout` or `setInterval`; PollRegistry remains the only polling owner.

### 3.4 Entering the training page performs an immediate canonical refresh

A full training-page render now immediately requests canonical `/jobs` truth instead of waiting for the next two-second poll.

This reduces the initial navigation window where a project aggregate could otherwise be displayed before focused training truth arrives.

### 3.5 Transitional states stay visible

The active training classification now includes:

```text
queued
waiting
pending
starting
running
pausing
paused
resuming
stopping
cancel_requested
```

This prevents a non-terminal task from moving to history or disappearing merely because it is between stable states.

Terminal/history classification includes the established terminal variants such as completed/succeeded/failed/stopped/cancelled and blocked terminal states.

## 4. PollRegistry continuation fix

Modified:

```text
static/modules/poll-registry.js
```

Training polling now continues through transitional dynamic states:

```text
starting
pausing
resuming
stopping
cancel_requested
```

`paused` remains intentionally non-polling by itself, preserving the existing paused-only no-timer contract.

No second polling owner was introduced.

## 5. Browser wiring

Modified:

```text
static/index.html
```

The visibility runtime is loaded after the existing main runtime:

```html
<script type="module" src="/static/main.mjs?v=42.25.99"></script>
<script type="module" src="/static/modules/training-task-visibility-runtime.js?v=422523"></script>
```

Formal visible product version remains `42.24.0`.

## 6. Permanent regression coverage

Added:

```text
tests/frontend/training-task-visibility-runtime.test.mjs
.github/workflows/training-task-visibility.yml
```

Focused contracts prove:

1. generic `loadRelated()` cannot erase canonical training jobs;
2. `loadRelated()` on the training page routes to focused canonical `/jobs` refresh;
3. transitional non-terminal states stay in the active tab;
4. legacy training render entrypoints cannot replace final task rows;
5. later canonical refresh remains final render truth;
6. existing TrainingTaskRuntime and PollRegistry regressions still run together with this batch;
7. the visibility runtime cannot introduce its own `setTimeout` / `setInterval` polling loop.

Do not weaken these guards to restore project-aggregate ownership of `state.jobs`.

## 7. Files changed in this batch

```text
static/modules/training-task-visibility-runtime.js
static/modules/poll-registry.js
static/index.html
tests/frontend/training-task-visibility-runtime.test.mjs
.github/workflows/training-task-visibility.yml
docs/CODEX_HANDOFF_2026-09-15_TRAINING_TASK_VISIBILITY.md
docs/CODEX_READ_FIRST.md
```

## 8. Explicit non-scope

This batch does NOT change:

```text
TaskRepository
training backend status semantics
Training Finalization & Queue Handoff
Scheduler claim ordering
GPU reservation behavior
GPU Runtime Truth Phase 1B
remote routing
GPU automatic scheduling
training model/process execution
```

It also does not attempt to recover deleted historical jobs or fabricate RUNNING tasks in browser memory.

## 9. Acceptance boundary

Automated tests and GitHub Actions prove the frontend ownership/fencing contracts, but the exact original production race should still be observed after deployment in a real browser while a real training task runs.

Manual acceptance:

1. Start a real training task and leave the training-task page open.
2. Let several `/jobs` polls occur while progress advances.
3. Use the global refresh button and training-page refresh.
4. Navigate to another page and back.
5. Trigger unrelated project data refreshes such as datasets/material operations.
6. Confirm the same active training row never disappears while `/jobs` continues to contain it.
7. Exercise pause/resume/stop transitions and confirm the task remains visible throughout transitional states.

Until this real-browser observation is completed, use:

```text
Training Task Visibility Stability
IMPLEMENTED + AUTOMATED REGRESSION
REAL BROWSER / A800 ACCEPTANCE: PENDING
```

Do not write `CLOSED` before real-browser acceptance.

## 10. Next work after acceptance

Keep the sequence narrow:

```text
1. Finish real A800 acceptance for Training Worker Isolation & Fast Dispatch
2. Finish real-browser/A800 acceptance for Training Task Visibility Stability
3. Fix only evidence-backed regressions, if any
4. Then consider GPU Runtime Truth Phase 1B when the user explicitly asks
```

GPU Runtime Truth Phase 1B remains separate and still includes node-scoped reservations, worker-slot identity migration, full GPU assignment identity, remote worker/server routing and automatic cross-node GPU scheduling.
