# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt status ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
validated runtime point:  2f858dabdeb4766a1283e3601c1ed25d7b6cc512
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.36
main.mjs cache:           42.25.38
```

Frontend Runtime Stabilization run `34590904476` completed `success` at the validated runtime point.

Do not merge this branch into `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

## 2. Current priority

**Do not move to A800 yet.** The user explicitly changed the work order to:

```text
close technical debt first
→ zero-point debt scan
→ then resume A800 RC
```

Before doing anything substantial, read:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
```

If those files disagree, `TECH_DEBT_CLOSURE_V42_25.md` wins for current debt status.

## 3. Backend contracts that must not regress

- Snapshot schema v3 and SHA duplicate/leakage protection.
- `confirmed_empty` is the formal negative-sample contract; an unannotated zero-box image is not automatically a valid negative.
- task-runtime lease/generation/process fencing and fenced artifact publication.
- explicit training resources cannot be silently increased; preserve requested `batch`, `workers`, and `cache=false` semantics.
- first training uses task-scoped labels only and must not inherit mother-model classes.
- iteration training inherits only the latest successful, artifact-verified, trainable version/schema.
- `training-metrics.sqlite3` uses short SQLite connections with deterministic close; the FD regression test must remain green.

Release gate remains `.github/workflows/v42.25-release-regression.yml`.

## 4. Frontend runtime shape

The frontend is still classic `static/app.js` plus named stabilization modules. Do not describe it as already migrated to Vue and do not add another numbered override generation.

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

New stabilization work should prefer named modules and explicit ownership.

## 5. Canonical training state and submit ownership

The canonical training source of truth is:

```text
state.trainingDraft
```

Current owner chain:

```text
train-v3 UI
  ↓
state.trainingDraft
  ↓
TrainingDraftRuntime
  ↓
TrainingSubmitRuntime
  ↓
POST /api/v12/projects/{project_id}/train/start
```

Important builds:

```text
TrainingDraftRuntime    training-draft-runtime-422509
TrainingSubmitRuntime   training-submit-422504
TrainingLabelRuntime    module-422507
TrainingTaskRuntime     training-task-runtime-422503
```

### Closed submit-owner debt

- `TrainingDraftRuntime.networkOwner=false` and must not intercept `/train/start`.
- `TrainingSubmitRuntime.networkOwner=true` is the single network owner.
- three historical `window.submitTrain429=async function...` implementations were physically removed from `static/app.js`.
- final `renderSplit()` and `refreshProjected417()` no longer control the submit button `disabled` state.
- submit readiness is owned by `TrainingSubmitRuntime.trainingSubmitReadiness()`.
- `lastStage` / `lastError` remain available for browser diagnostics.
- Real Chrome intentionally corrupts legacy mirrors and still requires the canonical request to be submitted correctly.

Do not restore old payload builders, fetch wrappers, or DOM readiness writers.

## 6. Training mirror status

Fully retired:

```text
state.trainingLabelSelected
state.trainSplitV3
```

Still present as migration debt:

```text
state.train429Selected
state.train428AlgorithmId
state.train428Config
```

These three **must not be treated as training submit truth sources**. They still have historical UI/helper reads in `static/app.js`, so remove them incrementally:

```text
identify actual read/write owner
→ migrate to trainingDraft / named runtime
→ unit proof
→ Real Chrome proof
→ physical retirement
```

Do not delete all three wholesale in one uncontrolled patch.

## 7. Training label compatibility debt

`TrainingLabelRuntime` is canonical-first, but still contains migration machinery:

```text
legacy entrypoint wrappers
[0,40,120,350,700] post-entrypoint refresh timers
[100,400,1000,2500] rebind timers
modal MutationObserver
legacy fallback reads when canonical draft does not yet exist
```

This is active technical debt. It is not the final architecture. Remove only after final entrypoints/renderer lifecycle are owned by named runtimes and browser coverage proves parity.

## 8. Polling / request ownership

Already closed:

### Training tasks

`TrainingTaskRuntime` owns `/jobs` refresh. It provides:

- one in-flight refresh;
- 120ms cross-source poll/manual freshness coalescing;
- mutation refresh always forced fresh;
- manual refresh re-arms PollRegistry;
- Real Chrome requires exactly one `/jobs` GET per manual refresh.

Do not relax this test to allow 1–2 requests.

### Remaining polling debt

Still audit and retire where safe:

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel / TrainingLabel rebind timers
```

A timer is not “closed” merely because another runtime later clears it; obsolete owners should be physically removed after proof.

## 9. `app.js` cleanup rule

`static/app.js` is still a large historical layered runtime. Continue reducing it, but only with:

```text
prove final owner
→ add/retain regression test
→ exact physical deletion
→ syntax + Node
→ Real Chrome
```

Do not perform broad blind string deletion.

High-value remaining scans:

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

Each surviving global owner/timer/wrapper needs a documented lifecycle.

## 10. Cache/version debt

Current static cache-busting is not unified:

```text
styles.css / material-pagination bootstrap: old 42.24.0-style versions
app.js: 42.25.36
main.mjs: 42.25.38
```

This remains open debt. Do not assume a server-side code update means browsers are running the same module set until cache versioning is unified or explicitly bumped.

## 11. Current work order

Continue in this order unless the user changes priority:

```text
1. migrate train429Selected / train428AlgorithmId / train428Config real owners
2. retire TrainingLabel / TrainingDraft compatibility wrappers and rebind timers where proven obsolete
3. retire auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
4. build final renderer/setPage owner table and remove obsolete override layers
5. reduce app.js proven dead code
6. eliminate remaining global reload / duplicate request paths
7. unify cache-busting
8. zero-point MutationObserver/timer/fetch/render/setPage scan
9. migrate version-number business names toward semantic names
10. deterministic-test cleanup + documentation sync
11. TECH_DEBT_CLOSURE_V42_25 zero-point scan
12. resume A800 RC
```

Every frontend runtime batch must end with syntax/Node and Real Chrome when behavior is affected, then update the debt ledger.

## 12. A800 status

A800 tooling/runbook already exists, but acceptance is deliberately **DEFERRED** until the current P0/P1 debt phase is complete.

When resumed, the acceptance sequence remains:

```text
preflight
→ first A800 short train (fire+smoke, device0, batch16, workers4, cache=false, epochs3–5)
→ verify-job
→ iteration train + verify
→ Worker lifecycle/fencing
→ only then consider v42.25 formal release
```

Frontend/CI success never counts as CUDA/A800 acceptance.

## 13. Do not do

- do not merge `main` without explicit authorization;
- do not add `train430/train431/...` override generations;
- do not restore global render-repair loops;
- do not let legacy mirrors regain training submit ownership;
- do not weaken duplicate-request tests;
- do not rebuild task labels from the project-wide label catalog;
- do not inherit mother-model classes on first training;
- do not claim technical debt CLOSED without evidence;
- do not claim A800/CUDA acceptance from CI.
