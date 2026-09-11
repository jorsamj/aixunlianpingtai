# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
latest full frontend acceptance point: 8f292860f7f1b8e238a0c9435d15e25eaa63a202
Frontend Runtime run:     34613425419
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.46
main.mjs cache:           42.25.51
NavigationStability:      422504
PollRegistry:             422509
TrainingDraftRuntime:     422516 / training-draft-runtime-422516
TrainingLabelRuntime:     422513 / module-422513
TrainingSubmitRuntime:    training-submit-422504
TrainingTaskRuntime:      training-task-runtime-422503
AutoLabelPollRuntime:     422501 / auto-label-poll-422501
```

Run `34613425419` passed syntax, all permanent owner guards, all frontend unit tests and all Real Chrome runtime regressions. The branch may be ahead of the acceptance commit with documentation-only commits; verify HEAD before editing. Do not merge `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

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

TrainingDraftRuntime is wrapper-free and excludes `.training-label-contract` events from generic sync. TrainingLabelRuntime is wrapper-free, timer-free and canonical-only.

## 6. AutoLabel polling ownership: CLOSED

```text
renderOps427 label tab complete
→ AutoLabelPollRuntime.activate(state.annotationTasks60)
→ PollRegistry(auto-label-v60)
→ refreshRows()
→ active tasks only re-arm

clean tab
→ AutoLabelPollRuntime.deactivate()
```

Physically retired:

```text
auto422Timer
ai60ListTimer
AutoLabelPollRuntime renderOps427 wrapper
100/400/1000ms rebind timers
```

Permanent CI prevents these owners from returning.

## 7. Legacy poll timer compatibility: CLOSED

Physically retired from product runtime code:

```text
auto422Timer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
```

PollRegistry and NavigationStability no longer adopt/clear those names. The old v33 video/prelabel `setupPagePolling` wrapper is gone.

## 8. Video polling ownership: CLOSED

Video no longer depends on PollRegistry wrapping classic render/refresh functions.

Final lifecycle:

```text
renderVideo424
→ loadVideo424 + render rows
→ PollRegistryRuntime.replaceVideo424Timer()

PollRegistry(video-frames, one-shot 2000ms)
→ refreshVideo424Delta
→ loadVideo424 + patch rows only
→ PollRegistryRuntime.replaceVideo424Timer()
→ active task ? re-arm : stop
```

Physically retired:

```text
installVideo424CreationBridge
__pollRegistryVideoWrapped
originalRenderVideo424 / wrappedRenderVideo424
originalRefreshVideo424 / wrappedRefreshVideo424
registry.adopt('video-frames', ...)
classic setTimeout(refreshVideo424Delta, 2000)
classic clearTimeout(state.video424Timer)
```

Permanent CI `Video PollRegistry direct owner guard` requires exactly two explicit app handoffs and forbids wrapper/adoption compatibility.

Real Chrome verifies:

- managed `video-frames` one-shot;
- row-only patching and stable `#view`;
- navigation-away cleanup;
- no legacy video interval owner;
- no page errors.

## 9. Remaining PollRegistry bridge debt

Only two creation-bridge families remain:

```text
installPollingCreationBridge()
→ wraps setupPagePolling
→ replaces training-jobs interval

installSourceCreationBridge()
→ wraps renderSources422
→ replaces sources interval

rebindCreation()
```

Video bridge is CLOSED and must not return.

Target pattern for both remaining owners:

```text
classic renderer/action
→ explicit PollRegistry lifecycle handoff
→ PollRegistry owns timer creation/clear directly
```

not:

```text
classic function creates timer
→ PollRegistry wrapper clears/replaces it afterward
```

Next recommended order: source bridge first (narrow renderer and existing Chrome coverage), then training/setupPagePolling bridge.

## 10. Cache state

```text
styles/bootstrap               42.24.0-style versions
app.js                         42.25.46
main.mjs                       42.25.51
navigation-stability.js        422504
poll-registry.js               422509
training-draft-runtime.js      422516
training-labels.js             422513
auto-label-poll-runtime.js     422501
```

Cache-busting remains non-unified debt.

## 11. Current work order

```text
1. retire renderSources422 / source creation bridge through explicit lifecycle handoff
2. retire setupPagePolling / training creation bridge through explicit lifecycle handoff
3. establish renderer/setPage final-owner table and remove obsolete overrides
4. reduce proven dead app.js and global reload/request debt
5. unify cache-busting
6. zero-point MutationObserver/timer/fetch/render/setPage scan
7. semantic naming + deterministic-test cleanup + docs sync
8. zero-point debt scan
9. resume A800 RC
```

Every batch: prove owner → regression → physical deletion → syntax/unit → Real Chrome when behavior changes → update all three handoff docs.

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
- do not bump `VERSION.txt`, tag or release;
- do not restore retired training mirrors/adapter;
- do not restore TrainingDraft/TrainingLabel classic wrappers or timer fan-out;
- do not restore AutoLabel legacy timers/wrappers/rebind timers;
- do not restore `auto422Timer`, `__videoFramePollTimer`, `__prelabelPollTimer`, `_oldSetupPollV33`;
- do not restore PollRegistry video renderer wrappers/adoption;
- do not let DraftRuntime generic sync own `.training-label-contract` controls;
- do not add render-repair loops or a new numbered override generation;
- do not weaken duplicate-request/race/performance/browser tests;
- do not claim A800/CUDA acceptance from frontend CI.
