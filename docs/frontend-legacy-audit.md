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
main.mjs                       42.25.44
training-draft                 422506
training-draft-runtime         422513
TrainingDraftRuntime build     training-draft-runtime-422513
training-labels                422510
TrainingLabelRuntime build     module-422510
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

Missing draft initializes an empty canonical draft; no mirror recovery is permitted.

## 4. TrainingDraft wrapper audit: CLOSED

TrainingDraftRuntime is now completely wrapper-free. It does not replace, decorate, restore, or count mutations from classic `app.js` functions.

Retired wrapper targets:

```text
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
startAlgorithmTraining429
```

Retired wrapper infrastructure:

```text
settingsPatch
checkboxInput
normalizedCache
directMutationFor
wrapLegacyMutation
mutationWrappers
directWrites
destroy() wrapper restoration
```

Runtime diagnostics explicitly expose:

```text
networkOwner=false
classicWrapperOwner=false
```

The current stable algorithm cards call `startAlgorithmTraining429`; the app-owned 429 start path performs the canonical reset before rendering the training modal. A permanent CI guard prevents classic wrapper ownership from returning to TrainingDraftRuntime.

## 5. TrainingLabel wrapper/lifecycle audit

Canonical current-v3 ownership:

- materials: `trainingDraft.materialIds`;
- new labels: `trainingDraft.newLabelCodes`.

Removed TrainingLabel bind targets:

```text
openTrain428
refreshTrain428
startAlgorithmTraining423
openTrain425
trainCounts425
```

The 423/425 removal is backed by source-order reachability tests:

- current stable `renderAlg412` cards call `startAlgorithmTraining429`;
- final training-task renderer does not expose `openTrain425()` or a create-training button;
- historical 423/425 calls occur only before those final owners.

Only remaining wrappers:

```text
startAlgorithmTraining429
refreshTrain429
```

Remaining TrainingLabel lifecycle debt:

```text
post-entrypoint refresh timers: 0 / 40 / 120 / 350 / 700 ms
rebind timers:                  100 / 400 / 1000 / 2500 ms
modal MutationObserver
legacy train425Selected fallback
legacy tr425AssetAlg/train423Asset lookup
legacy .train428-data/.train425-data host fallback
```

Next cleanup should make TrainingLabelRuntime wrapper-free and canonical-only. Do not simply delete refresh behavior: material-picker completion must still update the label contract in Real Chrome.

## 6. Established page owners relevant to training

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
main.mjs                          42.25.44
training-draft.js                 422506
training-draft-runtime.js         422513
training-labels.js                422510
```

Still not unified.

## 10. Latest full acceptance

```text
commit  52fe8f7ff822ef9d39a993d8f62edb5269b863a3
run     34598219623
syntax                          PASS
retired-mirror guard            PASS
network-owner guard             PASS
TrainingDraft wrapper-free guard PASS
frontend unit                   PASS
Real Chrome                     PASS
```

This acceptance includes full retirement of TrainingDraftRuntime classic mutation wrappers.

## 11. Current cleanup order

```text
1. make TrainingLabelRuntime wrapper-free + canonical-only; remove 425 fallbacks and timer fan-out
2. reduce/remove its MutationObserver if a simpler deterministic lifecycle owner is proven
3. retire old timer/polling owners
4. establish renderer/setPage final-owner table
5. remove proven dead app.js / global reload/request debt
6. unify cache-busting
7. zero-point observer/timer/fetch/render/setPage scan
8. semantic naming + deterministic tests + docs sync
9. technical-debt zero-point scan
10. resume A800 RC
```

## 12. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No retired training mirror/adapter may regain ownership.
4. No project-wide label catalog as task label truth source.
5. No mother-model class inheritance on first training.
6. Explicit false/zero training resource values must survive UI → draft → request.
7. Do not weaken duplicate-request/race/browser tests.
8. TrainingDraftRuntime must remain wrapper-free.
9. Frontend acceptance is not A800/CUDA acceptance.
