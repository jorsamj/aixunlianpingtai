# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Cleanup map for the classic frontend before any later framework replacement.  
> Status authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`.

## 1. Runtime shape

```text
static/app.js historical shell
  → static/main.mjs
       ├── NavigationStability
       ├── PageRequestScope
       ├── PollRegistry
       ├── AlgorithmListRuntime
       ├── TrainingTaskRuntime
       ├── MaterialPaginationRuntime61
       ├── TrainingDraftRuntime
       ├── TrainingDraftControlsRuntime
       ├── TrainingSubmitRuntime
       ├── TrainingLabelRuntime
       └── AutoLabelPollRuntime
```

No new numbered override generation is allowed.

## 2. Current versions / latest acceptance

```text
app.js                         42.25.44
main.mjs                       42.25.49
training-draft-runtime         422516
TrainingDraftRuntime build     training-draft-runtime-422516
training-labels                422513
TrainingLabelRuntime build     module-422513
AutoLabelPollRuntime           422501 / auto-label-poll-422501
TrainingSubmitRuntime          training-submit-422504
TrainingTaskRuntime            training-task-runtime-422503
```

Latest full acceptance:

```text
commit  7dbe7414767ed2808d17cc61a85c4897054391b1
run     34609355389
syntax                               PASS
retired-mirror guard                 PASS
network-owner guard                  PASS
TrainingDraft wrapper/owner guard    PASS
TrainingLabel canonical lifecycle    PASS
AutoLabel PollRegistry owner guard   PASS
frontend unit                        PASS
Real Chrome                          PASS
```

## 3. Training ownership audit: CLOSED

Canonical chain:

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /api/v12/projects/{project_id}/train/start
```

Retired training mirror/adapter surface:

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

TrainingDraftRuntime and TrainingLabelRuntime are wrapper-free. TrainingLabel is also timer-free/canonical-only. `.training-label-contract` belongs only to TrainingLabelRuntime; DraftRuntime must not generic-sync those controls.

## 4. AutoLabel polling audit: CLOSED

Final owner:

```text
renderOps427 label tab render complete
→ AutoLabelPollRuntime.activate(annotationTasks60)
→ PollRegistry(auto-label-v60)
→ refreshRows
→ active tasks only re-arm
```

Clean tab explicitly calls `AutoLabelPollRuntime.deactivate()`.

Physically retired:

```text
auto422Timer (2500ms)
ai60ListTimer (1800ms)
AutoLabelPollRuntime renderOps427 wrapper
__autoLabelPollRuntimeWrapped
originalRenderOps / wrappedRenderOps
100/400/1000ms rebind timers
```

The runtime itself contains no `setTimeout/clearTimeout` lifecycle owner; PollRegistry is the timer owner. Runtime diagnostics are `classicWrapperOwner=false` and `timerOwner=false`.

Permanent CI requires `static/app.js` to stay free of `auto422Timer/ai60ListTimer`, requires explicit app → Runtime activate/deactivate handoff, and forbids renderer wrapping/rebind timers in the Runtime.

Real Chrome proves:

- `auto-label-v60` is managed by PollRegistry at 1800ms;
- task rows update without replacing the page root;
- active task polling continues;
- navigation away clears the managed key;
- no page errors.

## 5. Established page owners relevant to training

### Algorithm list
Stable visible renderer: `renderAlgorithms423 → renderAlg412`.
Training action: `startAlgorithmTraining429`.

### Training task page
Final owner is the 428-era task-center renderer assigned to `renderTraining423/424/425`; it shows active/history tasks and no create-training entry. Training starts from the algorithm list.

### Training tasks runtime
`TrainingTaskRuntime` owns focused jobs refresh/polling with 120 ms cross-source coalescing and force-fresh mutation refresh.

### Materials
`MaterialPaginationRuntime61` owns paged material loading; training/AI workflows request full pools explicitly.

### Navigation/request lifecycle
`NavigationStability`, `PageRequestScope`, and `PollRegistry` own stabilized navigation/request/poll lifecycle. Do not restore global render-repair loops.

## 6. Next polling debt: video / prelabel / setupPagePolling

Verified current v33 legacy chain:

```text
const _oldSetupPollV33 = setupPagePolling
setupPagePolling = function() {
  _oldSetupPollV33();
  clearInterval(window.__videoFramePollTimer);
  clearInterval(window.__prelabelPollTimer);
  if (state.page === '视频切帧') {
    window.__videoFramePollTimer = setInterval(refreshVideoTasksOnly, 2500);
  }
}
```

`refreshVideoTasksOnly()` is already a narrow updater:

```text
GET /api/v33/projects/{pid}/video-tasks
→ state.videoTasks
→ #videoTaskRows only
```

Therefore video polling should migrate to a named PollRegistry lifecycle owner rather than re-rendering the full page.

`__prelabelPollTimer` was found only as a clear in this wrapper during the first pass; no creation site was found in that pass. Re-audit before physically deleting the cleanup reference.

## 7. Render/override debt

Audit targets remain:

```text
setupPagePolling
render = ...
window.setPage = ...
renderXXX412 / 417 / 423 / 428 / 429
loadAll()
loadRelated()
loadCore412()
MutationObserver
setInterval
setTimeout
window.fetch =
```

Deletion rule: prove final owner → regression coverage → physical deletion → syntax/unit → Chrome where relevant.

## 8. Cache-busting debt

```text
styles/bootstrap                  42.24.0-style versions
app.js                            42.25.44
main.mjs                          42.25.49
training-draft.js                 422506
training-draft-runtime.js         422516
training-labels.js                422513
auto-label-poll-runtime.js        422501
```

Still not unified.

## 9. Current cleanup order

```text
1. migrate __videoFramePollTimer to PollRegistry / named video lifecycle owner
2. resolve prelabel legacy cleanup + old setupPagePolling layers
3. establish renderer/setPage final-owner table
4. remove proven dead app.js / global reload/request debt
5. unify cache-busting
6. zero-point observer/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs sync
8. technical-debt zero-point scan
9. resume A800 RC
```

## 10. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No retired training mirror/adapter may regain ownership.
4. No project-wide label catalog as task label truth source.
5. No mother-model class inheritance on first training.
6. Explicit false/zero training resource values must survive UI → draft → request.
7. Do not weaken duplicate-request/race/browser tests.
8. TrainingDraftRuntime and TrainingLabelRuntime remain wrapper-free.
9. AutoLabel polling remains PollRegistry-only; no legacy timer or renderer wrapper revival.
10. Frontend acceptance is not A800/CUDA acceptance.
