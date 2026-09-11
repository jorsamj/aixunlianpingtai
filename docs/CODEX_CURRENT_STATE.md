# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
current branch HEAD:       c831db74389fec2ed0b39e111de581cf6b2723e3 (docs-only handoff update)
latest full frontend acceptance point: 4a86f4b497abb024daa9927c7be54e75fcea3692
Frontend Runtime run:     34610390049
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.45
main.mjs cache:           42.25.50
NavigationStability:      422504
PollRegistry:             422508
TrainingDraftRuntime:     422516 / training-draft-runtime-422516
TrainingLabelRuntime:     422513 / module-422513
TrainingSubmitRuntime:    training-submit-422504
TrainingTaskRuntime:      training-task-runtime-422503
AutoLabelPollRuntime:     422501 / auto-label-poll-422501
```

Run `34610390049` passed syntax, every permanent owner guard, all frontend unit tests and all Real Chrome runtime regressions. Do not merge `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

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

Physically retired:

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

## 7. Legacy poll timer compatibility: CLOSED

The following compatibility names are physically retired from product runtime code:

```text
auto422Timer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
```

Also removed:

- PollRegistry adopt/clear compatibility for those names;
- NavigationStability fallback clearing for those names;
- the v33 `setupPagePolling` override whose only purpose was video/prelabel interval ownership;
- obsolete unit-test fixtures/expectations for those timers.

Permanent CI `Retired legacy poll timer compatibility guard` requires those tokens to remain absent from:

```text
static/app.js
static/modules/poll-registry.js
static/modules/navigation-stability.js
```

## 8. Current video polling owner: CLOSED for legacy interval

Current live owner is the v42.4 video lifecycle, not the retired v33 interval:

```text
renderVideo424 / refreshVideo424Delta
→ state.video424Timer
→ PollRegistry key video-frames
→ managed one-shot 2000 ms
→ active video task only re-arms
```

Real Chrome verifies:

- `video-frames` is PollRegistry-managed;
- only task rows are patched;
- `#view` stays stable;
- navigation away clears the key immediately;
- `__videoFramePollTimer` remains absent/null.

Do not reintroduce a second video interval owner.

## 9. Remaining polling/lifecycle debt

The next target is **not** another video runtime. PollRegistry still contains historical creation bridges that wrap legacy functions after those functions create timers:

```text
installPollingCreationBridge()
  → wraps setupPagePolling

installVideo424CreationBridge()
  → wraps renderVideo424
  → wraps refreshVideo424Delta

installSourceCreationBridge()
  → wraps renderSources422

rebindCreation()
```

Target architecture:

```text
page renderer/action
→ explicit lifecycle handoff
→ PollRegistry creates/clears managed timer
```

not:

```text
legacy function creates timer
→ PollRegistry wrapper observes/replaces it
```

The next cleanup must prove each owner separately before physical deletion. Do not blindly delete all bridges in one step.

## 10. Cache state

```text
styles/bootstrap               42.24.0-style versions
app.js                         42.25.45
main.mjs                       42.25.50
navigation-stability.js        422504
poll-registry.js               422508
training-draft-runtime.js      422516
training-labels.js             422513
auto-label-poll-runtime.js     422501
```

Cache-busting remains non-unified debt.

## 11. Current work order

```text
1. retire PollRegistry creation bridges + old setupPagePolling layers through explicit lifecycle handoff
2. establish renderer/setPage final-owner table and remove obsolete overrides
3. reduce proven dead app.js and global reload/request debt
4. unify cache-busting
5. zero-point MutationObserver/timer/fetch/render/setPage scan
6. semantic naming + deterministic-test cleanup + docs sync
7. zero-point debt scan
8. resume A800 RC
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
- do not restore AutoLabel legacy timers, renderer wrapping, or rebind timers;
- do not restore `auto422Timer`, `__videoFramePollTimer`, `__prelabelPollTimer`, or `_oldSetupPollV33` compatibility;
- do not let DraftRuntime generic sync own `.training-label-contract` controls;
- do not add render-repair loops or a new numbered override generation;
- do not weaken duplicate-request/race/performance/browser tests;
- do not claim A800/CUDA acceptance from frontend CI.
