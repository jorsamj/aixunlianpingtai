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
app.js                         42.25.46
main.mjs                       42.25.51
navigation-stability          422504
poll-registry                 422509
training-draft-runtime        422516
TrainingDraftRuntime build    training-draft-runtime-422516
training-labels               422513
TrainingLabelRuntime build    module-422513
AutoLabelPollRuntime          422501 / auto-label-poll-422501
TrainingSubmitRuntime         training-submit-422504
TrainingTaskRuntime           training-task-runtime-422503
```

Latest full acceptance:

```text
commit  8f292860f7f1b8e238a0c9435d15e25eaa63a202
run     34613425419
syntax                                      PASS
retired-mirror guard                        PASS
network-owner guard                         PASS
TrainingDraft wrapper/owner guard           PASS
TrainingLabel canonical lifecycle guard     PASS
AutoLabel PollRegistry owner guard          PASS
retired legacy poll timer compatibility     PASS
Video PollRegistry direct owner guard       PASS
frontend unit                               PASS
Real Chrome                                 PASS
```

The branch may be ahead with documentation-only commits; use the code acceptance point above until a later code HEAD passes the same workflow.

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

TrainingDraftRuntime and TrainingLabelRuntime are wrapper-free. TrainingLabel is also timer-free/canonical-only. `.training-label-contract` belongs only to TrainingLabelRuntime.

## 4. AutoLabel polling audit: CLOSED

```text
renderOps427 label tab complete
→ AutoLabelPollRuntime.activate(annotationTasks60)
→ PollRegistry(auto-label-v60)
→ refreshRows
→ active tasks only re-arm
```

Clean tab explicitly calls `AutoLabelPollRuntime.deactivate()`.

Retired:

```text
auto422Timer
ai60ListTimer
AutoLabelPollRuntime renderOps427 wrapper
rebind timers
```

## 5. Legacy timer compatibility audit: CLOSED

Permanently retired:

```text
auto422Timer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
```

PollRegistry and NavigationStability no longer adopt/clear these names.

## 6. Video polling audit: CLOSED

Video is now explicit, wrapper-free lifecycle ownership:

```text
renderVideo424
→ loadVideo424 + render rows
→ PollRegistryRuntime.replaceVideo424Timer()

PollRegistry(video-frames, managed one-shot 2000ms)
→ refreshVideo424Delta
→ loadVideo424 + patchVideoRows424
→ PollRegistryRuntime.replaceVideo424Timer()
→ active task ? re-arm : stop
```

Physically retired from PollRegistry:

```text
installVideo424CreationBridge
__pollRegistryVideoWrapped
originalRenderVideo424 / wrappedRenderVideo424
originalRefreshVideo424 / wrappedRefreshVideo424
registry.adopt('video-frames', ...)
video wrapper restoration in destroy()
```

Physically retired from classic app video lifecycle:

```text
setTimeout(refreshVideo424Delta, 2000)
clearTimeout(state.video424Timer)
```

Permanent CI requires exactly two explicit app handoffs and forbids reintroducing wrapper/adoption compatibility. Real Chrome proves managed polling, row-only patching, stable `#view`, and navigation cleanup.

## 7. Established owners that must not regress

### Algorithm list
Stable visible renderer: `renderAlgorithms423 → renderAlg412`.
Training action: `startAlgorithmTraining429`.

### Training tasks
`TrainingTaskRuntime` owns focused jobs refresh with 120 ms poll/manual coalescing and force-fresh mutation refresh.

### Materials
`MaterialPaginationRuntime61` owns paged material loading; training/AI flows explicitly request full pools.

### Navigation/request lifecycle
`NavigationStability`, `PageRequestScope`, and `PollRegistry` own stabilized navigation/request/poll lifecycle.

## 8. Remaining PollRegistry bridge debt

Only two creation bridges remain:

```text
installPollingCreationBridge()
→ wraps setupPagePolling
→ replaces training-jobs timer

installSourceCreationBridge()
→ wraps renderSources422
→ replaces sources timer

rebindCreation()
```

Video bridge is closed and must not return.

Current compatibility pattern:

```text
classic function creates timer
→ PollRegistry wrapper runs afterward
→ clears/replaces legacy timer
```

Target pattern:

```text
classic renderer/action
→ explicit PollRegistry lifecycle handoff
→ PollRegistry directly owns timer
```

Recommended next order:

1. source bridge first: narrow renderer, existing browser regression;
2. training/setupPagePolling bridge second: broader legacy render coupling.

## 9. Render/override debt after bridge cleanup

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

## 10. Cache-busting debt

```text
styles/bootstrap                  42.24.0-style versions
app.js                            42.25.46
main.mjs                          42.25.51
navigation-stability.js           422504
poll-registry.js                  422509
training-draft-runtime.js         422516
training-labels.js                422513
auto-label-poll-runtime.js        422501
```

Still not unified.

## 11. Current cleanup order

```text
1. retire source creation bridge through explicit lifecycle handoff
2. retire training/setupPagePolling bridge through explicit lifecycle handoff
3. establish renderer/setPage final-owner table
4. remove proven dead app.js / global reload/request debt
5. unify cache-busting
6. zero-point observer/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs sync
8. technical-debt zero-point scan
9. resume A800 RC
```

## 12. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No retired training mirror/adapter may regain ownership.
4. No mother-model class inheritance on first training.
5. Explicit false/zero training resource values survive UI → draft → request.
6. Do not weaken duplicate-request/race/browser tests.
7. TrainingDraftRuntime and TrainingLabelRuntime remain wrapper-free.
8. AutoLabel polling remains PollRegistry-only.
9. Retired timer names remain absent.
10. PollRegistry video renderer wrapping/adoption must not return.
11. Frontend acceptance is not A800/CUDA acceptance.
