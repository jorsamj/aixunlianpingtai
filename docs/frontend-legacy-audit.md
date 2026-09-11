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

## 2. Canonical training owner

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /api/v12/projects/{project_id}/train/start
```

Current versions:

```text
app.js                         42.25.43
main.mjs                       42.25.41
training-draft                 422506
training-draft-runtime         422512
TrainingDraftRuntime build     training-draft-runtime-422512
training-labels                422508
TrainingSubmitRuntime          training-submit-422504
TrainingTaskRuntime            training-task-runtime-422503
```

`TrainingSubmitRuntime` is the sole `/train/start` network owner.

## 3. Retired training mirror/adapter surface

Fully retired from active product training ownership:

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

The five state mirror names are CI-guarded in `static/app.js` and the three core training modules. Old names in tests are pollution fixtures only.

Missing draft initializes an empty canonical draft; no mirror recovery is permitted.

## 4. TrainingDraft wrapper audit

### Retired in the latest batch

Final classic functions already write canonical state directly, so these Runtime wrappers were removed:

```text
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
```

Their wrapper-only settings sampling implementation was also removed:

```text
settingsPatch
checkboxInput
normalizedCache
```

### Only remaining TrainingDraft wrapper

```text
startAlgorithmTraining429
```

`TrainingDraftRuntime` still wraps this one function because `static/app.js` has a historical start chain across 414/415/417/v3 layers. Current wrapper writes/reset canonical state before invoking that chain, then syncs afterward. `destroy()` restores the original.

Do not remove this final wrapper until the start chain is flattened or otherwise proved to have one direct canonical owner.

## 5. TrainingLabel wrapper/lifecycle audit

Canonical data ownership is already correct:

- current v3 materials: `trainingDraft.materialIds`;
- new labels: `trainingDraft.newLabelCodes`;
- no 428/429 mirror fallback.

Current `bindCurrentEntrypoints()` still names:

```text
startAlgorithmTraining429
startAlgorithmTraining423
openTrain428
openTrain425
refreshTrain429
refreshTrain428
trainCounts425
```

Current source audit shows:

```text
openTrain428      → no window function remains in current app.js
refreshTrain428   → no window function remains in current app.js
openTrain425      → exists in historical 425 task flow
trainCounts425    → exists in historical 425 flow
startAlgorithmTraining423 → still referenced by algorithm-card markup
startAlgorithmTraining429 → current layered start chain
refreshTrain429   → current training UI refresh
```

Therefore `openTrain428` and `refreshTrain428` are safe stale bind targets to remove first. Do not remove the other five until call-site/final-owner proof is complete.

TrainingLabel still uses:

```text
post-entrypoint refresh timers: 0 / 40 / 120 / 350 / 700 ms
rebind timers:                  100 / 400 / 1000 / 2500 ms
modal MutationObserver
```

These are active debt.

## 6. Other established owners

### Training tasks
`TrainingTaskRuntime` owns focused jobs refresh/polling with 120 ms cross-source coalescing and force-fresh mutation refresh.

### Materials
`MaterialPaginationRuntime61` owns paged material loading; training/AI workflows request full pools explicitly.

### Navigation/request lifecycle
`NavigationStability`, `PageRequestScope`, and `PollRegistry` own the stabilized navigation/request/poll lifecycle. Do not restore global render-repair loops.

## 7. Remaining timer/polling debt

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel rebind timers
TrainingLabel rebind/refresh timers
```

A timer is not closed merely because a newer runtime clears it later; obsolete creation should be physically removed.

## 8. Render/override debt

Audit targets remain:

```text
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

## 9. Cache-busting debt

Current values:

```text
styles/bootstrap                  42.24.0-style versions
app.js                            42.25.43
main.mjs                          42.25.41
training-draft.js                 422506
training-draft-runtime.js         422512
training-labels.js                422508
```

Still not unified.

## 10. Latest full acceptance

```text
commit  f8040aecb316e16fd0f746db9cfb17e3a830e0ab
run     34596430563
syntax                      PASS
retired-mirror guard        PASS
network-owner guard         PASS
frontend unit               PASS
Real Chrome                 PASS
```

This acceptance includes retirement of the three redundant TrainingDraft wrappers.

## 11. Current cleanup order

```text
1. remove TrainingLabel stale bind targets openTrain428 / refreshTrain428
2. flatten/prove startAlgorithmTraining429 and retire final Draft wrapper
3. reduce remaining TrainingLabel wrappers/timers/MutationObserver
4. retire old timer/polling owners
5. establish renderer/setPage final-owner table
6. remove proven dead app.js / global reload/request debt
7. unify cache-busting
8. zero-point observer/timer/fetch/render/setPage scan
9. semantic naming + deterministic tests + docs sync
10. technical-debt zero-point scan
11. resume A800 RC
```

## 12. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No retired training mirror/adapter may regain ownership.
4. No project-wide label catalog as task label truth source.
5. No mother-model class inheritance on first training.
6. Explicit false/zero training resource values must survive UI → draft → request.
7. Do not weaken duplicate-request/race/browser tests.
8. Do not remove the final start wrapper without owner proof.
9. Frontend acceptance is not A800/CUDA acceptance.
