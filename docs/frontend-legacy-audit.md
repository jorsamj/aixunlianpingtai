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
main.mjs                       42.25.48
training-draft                 422506
training-draft-runtime         422516
TrainingDraftRuntime build     training-draft-runtime-422516
training-labels                422513
TrainingLabelRuntime build     module-422513
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

TrainingDraftRuntime is completely wrapper-free. It does not replace, decorate, restore, or count mutations from classic `app.js` functions.

Permanent event-owner boundary:

```text
.train429-create / .train-v3-picker generic form events → TrainingDraftRuntime
.training-label-contract events                         → TrainingLabelRuntime only
```

DraftRuntime explicitly excludes `.training-label-contract` before generic event sync. This is mandatory because otherwise a label checkbox click can schedule `sync()`, notify LabelRuntime, and cause the element being clicked to be replaced.

Runtime diagnostics remain:

```text
networkOwner=false
classicWrapperOwner=false
```

## 5. TrainingLabel wrapper/lifecycle audit: CLOSED

Canonical ownership:

- materials: `trainingDraft.materialIds`;
- new labels: `trainingDraft.newLabelCodes`.

All historical TrainingLabel wrapper targets are retired:

```text
openTrain428
refreshTrain428
startAlgorithmTraining423
openTrain425
trainCounts425
startAlgorithmTraining429
refreshTrain429
```

Also removed:

```text
post-entrypoint refresh timers
rebind timers
legacy train425Selected fallback
legacy tr425AssetAlg/train423Asset lookup
legacy .train428-data/.train425-data host fallback
```

Current lifecycle is canonical subscription based:

```text
TrainingDraftRuntime.subscribe()
→ TrainingLabelRuntime
```

A pure `newLabelCodes` update does not rebuild the panel. The checkbox DOM remains stable during click/change; only the visible label count is updated. A MutationObserver remains solely for outer modal DOM replacement and is not a polling substitute.

Real Chrome covers first session toggle, final submit payload, and second-session reset.

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

## 7. Current AutoLabel polling overlap

Current code still has multiple lifecycle owners around the same page/task stream:

```text
legacy auto422Timer interval       2500 ms
legacy v60 ai60ListTimer timeout   app-owned
AutoLabelPollRuntime               renderOps427 wrapper
AutoLabelPollRuntime               100/400/1000 ms rebind timers
PollRegistry                       auto-label-v60 managed one-shot
```

Target state:

```text
AutoLabelPollRuntime + PollRegistry
```

Only active v60 annotation tasks should re-arm polling. Navigation away must clear the managed key immediately. Obsolete legacy timers/wrappers must be physically removed rather than being created and then cleared by Runtime.

Existing Real Chrome test already verifies:

- task rows refresh without replacing `#view`;
- `auto-label-v60` is PollRegistry-managed;
- navigation away clears the key.

## 8. Other remaining timer/polling debt

```text
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
```

A timer is not closed merely because a newer runtime clears it later; obsolete creation should be physically removed.

## 9. Render/override debt

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

## 10. Cache-busting debt

Current values:

```text
styles/bootstrap                  42.24.0-style versions
app.js                            42.25.43
main.mjs                          42.25.48
training-draft.js                 422506
training-draft-runtime.js         422516
training-labels.js                422513
```

Still not unified.

## 11. Latest full acceptance

```text
commit  5ad08f03406e10dfd8c66a1455f068d503a77a4f
run     34608378866
syntax                               PASS
retired-mirror guard                 PASS
network-owner guard                  PASS
TrainingDraft wrapper/owner guard    PASS
TrainingLabel canonical lifecycle    PASS
frontend unit                        PASS
Real Chrome                          PASS
```

This acceptance closes both TrainingDraft and TrainingLabel classic-wrapper/timer debt.

## 12. Current cleanup order

```text
1. AutoLabel polling single-owner cleanup
2. retire __videoFramePollTimer / prelabel / setupPagePolling
3. establish renderer/setPage final-owner table
4. remove proven dead app.js / global reload/request debt
5. unify cache-busting
6. zero-point observer/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs sync
8. technical-debt zero-point scan
9. resume A800 RC
```

## 13. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No retired training mirror/adapter may regain ownership.
4. No project-wide label catalog as task label truth source.
5. No mother-model class inheritance on first training.
6. Explicit false/zero training resource values must survive UI → draft → request.
7. Do not weaken duplicate-request/race/browser tests.
8. TrainingDraftRuntime and TrainingLabelRuntime must remain wrapper-free.
9. DraftRuntime must not generic-sync TrainingLabel-owned controls.
10. Frontend acceptance is not A800/CUDA acceptance.
