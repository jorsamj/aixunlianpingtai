# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
latest full frontend acceptance point: 52fe8f7ff822ef9d39a993d8f62edb5269b863a3
Frontend Runtime run:     34598219623
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.43
main.mjs cache:           42.25.44
training-draft import:    422506
TrainingDraftRuntime import/build: 422513 / training-draft-runtime-422513
TrainingLabelRuntime import/build: 422510 / module-422510
TrainingSubmitRuntime:    training-submit-422504
```

Run `34598219623` passed syntax, retired-mirror guard, canonical network-owner guard, permanent TrainingDraft wrapper-free guard, all frontend unit tests and Real Chrome runtime regressions. Do not merge `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

## 2. Current priority

```text
close remaining frontend/runtime technical debt
→ zero-point debt scan
→ resume A800 RC
```

Read before editing:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
```

If documents disagree, `TECH_DEBT_CLOSURE_V42_25.md` wins.

## 3. Non-regression backend contracts

- Snapshot schema v3 and SHA duplicate/leakage protection.
- `confirmed_empty` is the formal negative-sample contract.
- task-runtime lease/generation/process fencing and fenced artifact publication.
- explicit `batch`, `workers`, `cache=false` semantics must survive end-to-end.
- first training uses task-scoped labels only; no mother-model class inheritance.
- iteration inherits only the latest successful, artifact-verified, trainable version/schema.
- `training-metrics.sqlite3` connections close deterministically; FD regression remains mandatory.

Release gate: `.github/workflows/v42.25-release-regression.yml`.

## 4. Frontend runtime shape

The frontend remains classic `static/app.js` plus named modules; it is not Vue.

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

Do not add another numbered compatibility generation.

## 5. Canonical training ownership

Only truth source:

```text
state.trainingDraft
```

Owner chain:

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

- DraftRuntime `networkOwner=false`, `classicWrapperOwner=false`.
- SubmitRuntime `networkOwner=true` and is the sole `/train/start` owner.
- classic `static/app.js` direct `/train/start` paths are physically removed and CI-guarded.

## 6. Training mirrors + legacy bootstrap are CLOSED

Retired from active `static/app.js` and core training modules:

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

Tests may deliberately create old names as pollution fixtures. Runtime must ignore them and must not read/write/delete them. A test reference is not a compatibility contract.

## 7. TrainingDraftRuntime is now wrapper-free

Current build: `training-draft-runtime-422513`.

All classic mutation wrappers are physically retired:

```text
confirmTrainMaterialPickerV3   CLOSED
setTrainSplitModeV3            CLOSED
saveTrainSettings428           CLOSED
startAlgorithmTraining429      CLOSED as Runtime wrapper
```

Also removed:

```text
settingsPatch
checkboxInput
normalizedCache
directMutationFor
wrapLegacyMutation
mutationWrappers
directWrites
wrapper restoration in destroy()
```

The visible stable algorithm renderer calls `startAlgorithmTraining429`; the app-owned 429 start path performs the canonical draft reset before opening the training modal. TrainingDraftRuntime no longer rewrites any classic function.

Permanent CI guard forbids reintroducing `startAlgorithmTraining429`, `wrapLegacyMutation`, `directMutationFor`, `mutationWrappers`, or `__trainingDraftMutationWrapped` into `training-draft-runtime.js`.

## 8. TrainingLabelRuntime status

Current import/build: `422510 / module-422510`.

Canonical data ownership is correct for the current v3 path:

- current training materials: `trainingDraft.materialIds`;
- selected task labels: `trainingDraft.newLabelCodes`.

Retired bind targets:

```text
openTrain428
refreshTrain428
startAlgorithmTraining423
openTrain425
trainCounts425
```

The 423/425 targets were removed only after source tests proved the final stable algorithm renderer uses start429 and the final training task renderer no longer exposes 425 create UI.

Only two TrainingLabel wrappers remain:

```text
startAlgorithmTraining429
refreshTrain429
```

Remaining lifecycle debt:

```text
post-entrypoint refresh timers: 0 / 40 / 120 / 350 / 700 ms
rebind timers:                  100 / 400 / 1000 / 2500 ms
modal MutationObserver
legacy 425 fallback reads in TrainingLabel helper paths
```

Next target is to make TrainingLabelRuntime wrapper-free and canonical-only, removing 425 fallback state/DOM lookup and the timer fan-out without regressing label refresh in Real Chrome.

## 9. Polling / request ownership

Training task behavior is closed and must not regress:

- one in-flight `/jobs` refresh;
- 120 ms poll/manual coalescing;
- mutation refresh force-fresh;
- manual refresh re-arms PollRegistry;
- Chrome expects one `/jobs` GET per manual refresh.

Remaining timer debt:

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel rebind timers
TrainingLabel rebind/refresh timers
```

## 10. Cache state

```text
styles/bootstrap               42.24.0-style versions
app.js                         42.25.43
main.mjs                       42.25.44
training-draft.js              422506
training-draft-runtime.js      422513
training-labels.js             422510
```

Cache-busting remains non-unified debt.

## 11. Current work order

```text
1. make TrainingLabelRuntime wrapper-free + canonical-only; remove 425 fallbacks and timer fan-out
2. reduce/replace remaining TrainingLabel MutationObserver lifecycle if proven unnecessary
3. retire auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
4. establish renderer/setPage owner table and remove obsolete override layers
5. reduce proven dead app.js code and global reload/request debt
6. unify cache-busting
7. zero-point observer/timer/fetch/render/setPage scan
8. semantic naming + deterministic-test cleanup + docs sync
9. zero-point debt scan
10. resume A800 RC
```

Every runtime batch: prove owner → test → physical deletion → syntax/unit → Real Chrome when behavior changes → update docs.

## 12. A800 status

A800 acceptance is **DEFERRED** until current P0/P1 debt is closed.

When resumed:

```text
preflight
→ first A800 short train (fire+smoke, device0, batch16, workers4, cache=false, epochs3–5)
→ verify-job
→ iteration train + verify
→ Worker lifecycle/fencing
→ only then consider formal v42.25 release
```

Frontend CI is not CUDA/A800 acceptance.

## 13. Do not do

- do not merge `main` without explicit authorization;
- do not restore retired mirrors or `trainingDraftFromLegacyState`;
- do not restore any TrainingDraft classic mutation wrapper;
- do not restore removed TrainingLabel 428/423/425 binds;
- do not add render-repair loops or new numbered overrides;
- do not weaken owner/race/performance/browser tests;
- do not claim A800/CUDA acceptance from CI.
