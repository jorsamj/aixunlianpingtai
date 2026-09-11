# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
latest full frontend acceptance point: 7dbe7414767ed2808d17cc61a85c4897054391b1
Frontend Runtime run:     34609355389
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.44
main.mjs cache:           42.25.49
TrainingDraftRuntime:     422516 / training-draft-runtime-422516
TrainingLabelRuntime:     422513 / module-422513
TrainingSubmitRuntime:    training-submit-422504
TrainingTaskRuntime:      training-task-runtime-422503
AutoLabelPollRuntime:     422501 / auto-label-poll-422501
```

Run `34609355389` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Do not merge `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

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

## 3. Backend contracts that must not regress

- Snapshot schema v3 and SHA duplicate/leakage protection.
- `confirmed_empty` is the formal negative-sample contract.
- task-runtime lease/generation/process fencing and fenced artifact publication.
- explicit `batch`, `workers`, `cache=false` semantics survive end-to-end.
- first training uses task-scoped labels only; no mother-model class inheritance.
- iteration inherits only latest successful, artifact-verified, trainable version/schema.
- `training-metrics.sqlite3` connections close deterministically; FD regression remains mandatory.

Release gate: `.github/workflows/v42.25-release-regression.yml`.

## 4. Frontend runtime shape

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

No new numbered compatibility generation.

## 5. Canonical training ownership: CLOSED

Only truth source:

```text
state.trainingDraft
```

Owner chain:

```text
train-v3 UI
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

Permanently retired from active product ownership:

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

Tests may create those names only as pollution fixtures. Runtime must ignore them.

TrainingDraftRuntime is wrapper-free and excludes `.training-label-contract` events from generic sync. TrainingLabelRuntime is wrapper-free, timer-free and canonical-only. Pure label toggles update canonical state/count without replacing the checkbox DOM.

## 6. AutoLabel polling ownership: CLOSED

Final lifecycle:

```text
renderOps427 label tab complete
→ AutoLabelPollRuntime.activate(state.annotationTasks60)
→ PollRegistry key auto-label-v60
→ refreshRows()
→ only active tasks re-arm

clean tab
→ AutoLabelPollRuntime.deactivate()
```

Retired physically:

```text
auto422Timer
ai60ListTimer
AutoLabelPollRuntime renderOps427 wrapper
__autoLabelPollRuntimeWrapped
originalRenderOps / wrappedRenderOps
100/400/1000ms rebind timers
```

Runtime diagnostics:

```text
classicWrapperOwner=false
timerOwner=false
```

Permanent CI `AutoLabel PollRegistry owner guard` prevents those owners/timers from returning. Real Chrome verifies managed delay 1800, row-only refresh, stable `#view`, and immediate PollRegistry cleanup after navigation.

## 7. Polling / request ownership already closed

Training tasks:

- one in-flight `/jobs` refresh;
- 120 ms poll/manual coalescing;
- mutation refresh force-fresh;
- manual refresh re-arms PollRegistry;
- Chrome expects one `/jobs` GET per manual refresh.

AutoLabel: see section 6.

## 8. Next timer/lifecycle debt

Current next target is **video frame polling**, not AutoLabel.

Verified legacy shape:

```text
setupPagePolling v33 wrapper
→ clearInterval(window.__videoFramePollTimer)
→ if page === 视频切帧
   setInterval(refreshVideoTasksOnly, 2500)
```

`refreshVideoTasksOnly()` itself only updates `state.videoTasks` and `#videoTaskRows`, so the likely migration is a named/managed PollRegistry lifecycle owner rather than a page rewrite.

`__prelabelPollTimer` currently appears as a legacy clear in that v33 wrapper; no matching creation was found in the first audit pass. Re-check before deleting.

Other remaining lifecycle debt:

```text
old setupPagePolling layers
__videoFramePollTimer
prelabel legacy cleanup
```

## 9. Cache state

```text
styles/bootstrap               42.24.0-style versions
app.js                         42.25.44
main.mjs                       42.25.49
training-draft.js              422506
training-draft-runtime.js      422516
training-labels.js             422513
auto-label-poll-runtime.js     422501
```

Cache-busting remains non-unified debt.

## 10. Current work order

```text
1. retire __videoFramePollTimer into PollRegistry / named video lifecycle owner
2. resolve prelabel legacy cleanup + old setupPagePolling layers
3. establish renderer/setPage final-owner table and remove obsolete overrides
4. reduce proven dead app.js and global reload/request debt
5. unify cache-busting
6. zero-point MutationObserver/timer/fetch/render/setPage scan
7. semantic naming + deterministic-test cleanup + docs sync
8. zero-point debt scan
9. resume A800 RC
```

Every batch: prove owner → regression → physical deletion → syntax/unit → Real Chrome when behavior changes → update all three handoff docs.

## 11. A800 status

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

## 12. Do not do

- do not merge `main` without explicit authorization;
- do not restore retired training mirrors/adapter;
- do not restore TrainingDraft/TrainingLabel classic wrappers or timer fan-out;
- do not restore AutoLabel legacy timers, renderer wrapping, or rebind timers;
- do not let DraftRuntime generic sync own `.training-label-contract` controls;
- do not add render-repair loops or a new numbered override generation;
- do not weaken duplicate-request/race/performance/browser tests;
- do not claim A800/CUDA acceptance from frontend CI.
