# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
latest full frontend acceptance point: 5ad08f03406e10dfd8c66a1455f068d503a77a4f
Frontend Runtime run:     34608378866
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.43
main.mjs cache:           42.25.48
training-draft import:    422506
TrainingDraftRuntime import/build: 422516 / training-draft-runtime-422516
TrainingLabelRuntime import/build: 422513 / module-422513
TrainingSubmitRuntime:    training-submit-422504
```

Run `34608378866` passed syntax, retired-mirror guard, canonical network-owner guard, TrainingDraft wrapper/owner-boundary guard, TrainingLabel canonical lifecycle guard, all frontend unit tests and Real Chrome runtime regressions. Do not merge `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

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

## 7. TrainingDraftRuntime is wrapper-free

Current build: `training-draft-runtime-422516`.

All classic mutation wrappers are physically retired. TrainingDraftRuntime no longer replaces, decorates, restores, or rebinds classic `app.js` functions.

Permanent owner boundary:

```text
.train429-create / .train-v3-picker generic form events → TrainingDraftRuntime
.training-label-contract events                         → TrainingLabelRuntime only
```

DraftRuntime explicitly returns false for `.training-label-contract` events before generic training-form sync. This prevents label checkbox click/change from triggering a second draft sync and DOM rebuild.

## 8. TrainingLabelRuntime is wrapper-free / timer-free / canonical-only

Current import/build: `422513 / module-422513`.

Canonical ownership:

- current training materials: `trainingDraft.materialIds`;
- selected task labels: `trainingDraft.newLabelCodes`.

All historical bind targets are retired:

```text
openTrain428
refreshTrain428
startAlgorithmTraining423
openTrain425
trainCounts425
startAlgorithmTraining429
refreshTrain429
```

Removed lifecycle debt:

```text
post-entrypoint refresh timer fan-out
rebind timers
legacy train425Selected fallback
legacy tr425AssetAlg / train423Asset lookup
legacy .train428-data / .train425-data host fallback
```

Current lifecycle:

```text
TrainingDraftRuntime.subscribe()
→ TrainingLabelRuntime
→ canonical data
→ microtask-coalesced refresh only when label set/host can change
```

For a pure `newLabelCodes` update, TrainingLabel only updates the count and does not rebuild the checkbox panel. Real Chrome specifically validates that unchecking a label does not detach the element being clicked and that a second training session resets label interaction correctly.

A modal MutationObserver remains only to restore the panel after the outer legacy modal DOM is redrawn. Do not replace this with polling/timer fan-out.

## 9. Polling / request ownership

Training task behavior is closed and must not regress:

- one in-flight `/jobs` refresh;
- 120 ms poll/manual coalescing;
- mutation refresh force-fresh;
- manual refresh re-arms PollRegistry;
- Chrome expects one `/jobs` GET per manual refresh.

Current next target is AutoLabel polling. Existing overlap still includes:

```text
legacy auto422Timer interval (2500 ms)
legacy v60 ai60ListTimer timeout
AutoLabelPollRuntime renderOps427 wrapper
AutoLabelPollRuntime 100/400/1000 ms rebind timers
PollRegistry auto-label-v60 one-shot polling
```

Goal: only `AutoLabelPollRuntime + PollRegistry` owns active v60 task polling. Obsolete creation must be physically removed, not merely cleared later.

Other remaining timer debt:

```text
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
```

## 10. Cache state

```text
styles/bootstrap               42.24.0-style versions
app.js                         42.25.43
main.mjs                       42.25.48
training-draft.js              422506
training-draft-runtime.js      422516
training-labels.js             422513
```

Cache-busting remains non-unified debt.

## 11. Current work order

```text
1. AutoLabel polling single-owner cleanup: retire auto422Timer / ai60ListTimer / renderOps427 wrapper / rebind timers
2. retire __videoFramePollTimer / prelabel / setupPagePolling
3. establish renderer/setPage owner table and remove obsolete override layers
4. reduce proven dead app.js code and global reload/request debt
5. unify cache-busting
6. zero-point observer/timer/fetch/render/setPage scan
7. semantic naming + deterministic-test cleanup + docs sync
8. zero-point debt scan
9. resume A800 RC
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
- do not restore TrainingLabel classic wrappers, timer fan-out, or 425 fallback reads;
- do not let DraftRuntime generic event sync own `.training-label-contract` controls;
- do not add render-repair loops or new numbered overrides;
- do not weaken owner/race/performance/browser tests;
- do not claim A800/CUDA acceptance from CI.
