# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
latest full frontend acceptance point: f8040aecb316e16fd0f746db9cfb17e3a830e0ab
Frontend Runtime run:     34596430563
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.43
main.mjs cache:           42.25.41
training-draft import:    422506
TrainingDraftRuntime import/build: 422512 / training-draft-runtime-422512
TrainingLabelRuntime import: 422508
TrainingSubmitRuntime:    training-submit-422504
```

Run `34596430563` passed syntax, permanent owner/mirror guards, all frontend unit tests and Real Chrome runtime regressions. Do not merge `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

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

- DraftRuntime `networkOwner=false`.
- SubmitRuntime `networkOwner=true` and is the sole `/train/start` owner.
- classic `static/app.js` direct `/train/start` paths are physically removed and CI-guarded.

## 6. Five training mirrors + legacy bootstrap are CLOSED

Retired from active `static/app.js` and core training modules:

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
```

Guarded files:

```text
static/app.js
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-labels.js
```

Tests may deliberately create these old names as pollution fixtures. Required behavior: runtime ignores them and does not read/write/delete them. A test reference is not a compatibility contract.

`trainingDraftFromLegacyState` is physically removed. Missing canonical state initializes `createTrainingDraft()`; never restore 428/429 fallback bootstrap.

## 7. TrainingDraftRuntime wrapper status

Current build: `training-draft-runtime-422512`.

Three redundant wrappers are now physically retired because final `app.js` already writes canonical state itself:

```text
confirmTrainMaterialPickerV3   CLOSED
setTrainSplitModeV3            CLOSED
saveTrainSettings428           CLOSED
```

The wrapper-only settings sampler (`settingsPatch`, `checkboxInput`, `normalizedCache`) was removed with them.

**Only one TrainingDraft classic wrapper remains:**

```text
startAlgorithmTraining429
```

It remains intentionally because the start path is still layered through historical 414/415/417/v3 overrides. Do not remove it until the final start owner chain is flattened/proven. `destroy()` still restores that single wrapped function.

## 8. TrainingLabelRuntime debt

TrainingLabel data ownership is canonical:

- v3 materials: `trainingDraft.materialIds`;
- selected labels: `trainingDraft.newLabelCodes`;
- no fallback to `train429Selected` / `train428AlgorithmId`.

Remaining lifecycle machinery includes:

```text
startAlgorithmTraining429
startAlgorithmTraining423
openTrain425
refreshTrain429
trainCounts425
post-entrypoint timers: 0 / 40 / 120 / 350 / 700 ms
rebind timers:          100 / 400 / 1000 / 2500 ms
modal MutationObserver
```

`openTrain428` and `refreshTrain428` no longer exist in current `static/app.js`; they are stale bind targets and should be physically removed from TrainingLabelRuntime next.

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
main.mjs                       42.25.41
training-draft.js              422506
training-draft-runtime.js      422512
training-labels.js             422508
```

Cache-busting remains non-unified debt.

## 11. Current work order

```text
1. remove stale TrainingLabel bind targets openTrain428 / refreshTrain428
2. flatten/prove the final startAlgorithmTraining429 owner chain; then retire the final TrainingDraft wrapper
3. reduce TrainingLabel wrappers/rebind timers/refresh timers/MutationObserver
4. retire auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
5. establish renderer/setPage owner table and remove obsolete override layers
6. reduce proven dead app.js code and global reload/request debt
7. unify cache-busting
8. zero-point observer/timer/fetch/render/setPage scan
9. semantic naming + deterministic-test cleanup + docs sync
10. zero-point debt scan
11. resume A800 RC
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
- do not restore the five retired mirrors or `trainingDraftFromLegacyState`;
- do not restore retired Draft wrappers for picker/split/settings;
- do not remove the remaining start wrapper without flattening/proving its historical chain;
- do not add render-repair loops or new numbered overrides;
- do not weaken owner/race/performance/browser tests;
- do not claim A800/CUDA acceptance from CI.
