# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt status ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
latest full frontend acceptance point: f45f88f8f64a71a1adaa68e359b6f193297fb6a1
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.42
main.mjs cache:           42.25.39
TrainingDraftRuntime import cache: 422510
```

Frontend Runtime Stabilization run `34594071998` completed `success` at the acceptance point: syntax + permanent guards + frontend unit tests + Real Chrome all green.

Do not merge this branch into `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

## 2. Current priority

**Do not move to A800 yet.** Current work order:

```text
close technical debt first
→ zero-point debt scan
→ then resume A800 RC
```

Read in this order before editing:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
```

If documents disagree, `TECH_DEBT_CLOSURE_V42_25.md` wins.

## 3. Backend contracts that must not regress

- Snapshot schema v3 and SHA duplicate/leakage protection.
- `confirmed_empty` is the formal negative-sample contract; an unannotated zero-box image is not automatically a valid negative.
- task-runtime lease/generation/process fencing and fenced artifact publication.
- explicit training resources cannot be silently increased; preserve requested `batch`, `workers`, and `cache=false` semantics.
- first training uses task-scoped labels only and must not inherit mother-model classes.
- iteration training inherits only the latest successful, artifact-verified, trainable version/schema.
- `training-metrics.sqlite3` uses short SQLite connections with deterministic close; FD regression tests must remain green.

Release gate remains `.github/workflows/v42.25-release-regression.yml`.

## 4. Frontend runtime shape

The frontend remains classic `static/app.js` plus named stabilization modules. Do not describe it as Vue and do not add a new numbered override generation.

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

Canonical source of truth:

```text
state.trainingDraft
```

Owner chain:

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

Current key builds/imports:

```text
TrainingDraftRuntime    module import cache 422510
TrainingSubmitRuntime   training-submit-422504
TrainingLabelRuntime    module-422507
TrainingTaskRuntime     training-task-runtime-422503
```

### Closed submit-owner debt

- `TrainingDraftRuntime.networkOwner=false`; it must not intercept `/train/start`.
- `TrainingSubmitRuntime.networkOwner=true` is the single network owner.
- all classic `static/app.js` direct `/train/start` paths are physically removed.
- submit readiness is owned by `TrainingSubmitRuntime.trainingSubmitReadiness()`.
- `lastStage / lastError` are retained for browser diagnostics.
- permanent CI fails if `/train/start` reappears in `static/app.js`.

Do not restore old payload builders, fetch wrappers, or DOM readiness writers.

## 6. Training mirror status

Fully retired from active `static/app.js` and permanently guarded:

```text
state.trainingLabelSelected
state.trainSplitV3
state.train429Selected
```

`train429Selected` was replaced end-to-end in the active v3 material flow by:

```text
TrainingDraftRuntime.materialIds()
TrainingDraftRuntime.setMaterialIds(ids)
TrainingDraftRuntime.toggleMaterialId(id)
→ state.trainingDraft.materialIds
```

This covers picker selected state, toggle, select-all/invert, count, label summary, quality checks, projected split counts, and wrapper reset behavior. Run `34594071998` proves Node + Real Chrome parity.

Still present as migration debt:

```text
state.train428AlgorithmId
state.train428Config
```

They must not own submit behavior. Final 429 start/target/engine writers have already been migrated away. Remaining work is mainly old 428 settings/UI fallback and historical blocks:

```text
classify active compatibility read/write
→ migrate active fallback to trainingDraft
→ prove unreachable historical blocks
→ physically delete
→ syntax/Node + Real Chrome
```

Do not delete all remaining 428 code wholesale.

## 7. TrainingDraft / TrainingLabel compatibility debt

`TrainingDraftRuntime` is canonical-first. It still has bounded compatibility behavior for final classic entrypoints and initial bootstrap when canonical state does not yet exist.

`TrainingLabelRuntime` is also canonical-first but still contains migration machinery:

```text
legacy entrypoint wrappers
post-entrypoint refresh timers
rebind timers
modal MutationObserver
legacy bootstrap fallback before canonical draft exists
```

These are active technical debt, not final architecture. Remove them after final entrypoints/renderer lifecycle are owned by named runtimes and browser coverage proves parity.

## 8. Polling / request ownership

Closed training-task behavior:

- one in-flight `/jobs` refresh;
- 120ms cross-source poll/manual freshness coalescing;
- mutation refresh forced fresh;
- manual refresh re-arms PollRegistry;
- Real Chrome requires exactly one `/jobs` GET per manual refresh.

Do not relax this test.

Remaining polling/timer debt:

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel / TrainingLabel rebind timers
```

A timer is not closed merely because another runtime later clears it; obsolete creation must be physically removed after proof.

## 9. `app.js` cleanup rule

Continue reducing `static/app.js` only with:

```text
prove final owner
→ add/retain regression test
→ exact physical deletion
→ syntax + Node
→ Real Chrome
```

Do not perform broad blind deletion.

High-value scans remain:

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

## 10. Cache/version debt

Current static cache-busting is still not unified:

```text
styles.css / material-pagination bootstrap: 42.24.0-style versions
app.js: 42.25.42
main.mjs: 42.25.39
TrainingDraftRuntime import: 422510
```

This remains open debt. A server-side code update does not guarantee browsers are running the same module set unless the affected outer and nested cache versions are bumped.

## 11. Current work order

```text
1. finish train428AlgorithmId / train428Config compatibility and old 428 settings/UI cleanup
2. retire TrainingDraft/TrainingLabel compatibility wrappers and rebind timers where proven obsolete
3. retire auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
4. establish renderer/setPage owner table and remove obsolete override layers
5. reduce app.js proven dead code
6. eliminate global reload/duplicate-request debt
7. unify cache-busting
8. zero-point MutationObserver/timer/fetch/render/setPage scan
9. migrate version-number business names toward semantic names
10. deterministic-test cleanup + documentation sync
11. TECH_DEBT_CLOSURE_V42_25 zero-point scan
12. resume A800 RC
```

Every frontend runtime batch must end with syntax/Node and Real Chrome when behavior is affected, then update the debt ledger.

## 12. A800 status

A800 tooling/runbook exists, but acceptance is deliberately **DEFERRED** until the current P0/P1 debt phase is complete.

When resumed:

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
- do not reintroduce `train429Selected` to active `static/app.js`;
- do not weaken duplicate-request tests;
- do not rebuild task labels from the project-wide label catalog;
- do not inherit mother-model classes on first training;
- do not claim technical debt CLOSED without evidence;
- do not claim A800/CUDA acceptance from CI.
