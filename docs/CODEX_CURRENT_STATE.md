# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                    refactor/frontend-runtime-stabilization
latest full code acceptance: f3eb6b360123dd688eea4dd0f29c05a9db5b4c05
Frontend Runtime run:      34619698115
formal VERSION.txt:        42.24.0
frontend badge:            v42.25.0-dev
app.js cache:              42.25.51
main.mjs cache:            42.25.53
NavigationStability:       422506
PollRegistry:              422511
TrainingDraftRuntime:      422516
TrainingLabelRuntime:      422513
TrainingSubmitRuntime:     training-submit-422504
TrainingTaskRuntime:       training-task-runtime-422503
AutoLabelPollRuntime:      422501
```

Run `34619698115` passed syntax, permanent owner guards, all frontend unit tests and Real Chrome. Branch HEAD may be newer because handoff docs are updated after accepted code points. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
pre-v42.4 dead setPage family proof/removal
→ remaining renderer/setPage obsolete layers
→ app.js/global reload/request debt
→ cache-busting unification
→ zero-point lifecycle scan
→ A800 RC
```

Read in order:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
docs/FRONTEND_OWNER_MAP_V42_25.md
```

## 3. Non-regression backend contracts

- snapshot schema v3 and duplicate/leakage protection;
- `confirmed_empty` negative-sample semantics;
- task-runtime lease/generation/process fencing;
- explicit `batch`, `workers`, `cache=false` end-to-end;
- first training uses task-scoped labels only;
- no mother-model class inheritance on first training;
- iteration inherits only latest successful artifact-verified trainable version;
- metrics SQLite connections close deterministically.

## 4. Closed frontend ownership

### Training submit

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired mirrors: `trainingLabelSelected`, `trainSplitV3`, `train429Selected`, `train428AlgorithmId`, `train428Config`, `trainingDraftFromLegacyState`.

### Training polling

```text
classic render call site
→ PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
→ TrainingTaskRuntime.refresh({render:true, source:'poll'})
→ focused /jobs refresh
```

Physically retired: `jobPollTimer`, `setupPagePolling`, PollRegistry training creation wrappers/adoption/rebind compatibility and NavigationStability timer fallback.

### AutoLabel / Video / Sources

```text
renderOps427 → AutoLabelPollRuntime → PollRegistry(auto-label-v60)
renderVideo424 / refreshVideo424Delta → PollRegistry(video-frames)
renderSources422 → PollRegistry(sources)
```

Legacy timer/wrapper owners are retired.

### Navigation wrapper cleanup

Physically retired and guarded:

```text
set423Base
setBase424
V37 baseSetPage mobile-sidebar wrapper
```

V417 is now the sole classic mobile-sidebar close owner:

```text
const baseSetPage417=window.setPage;
window.setPage=function(page){
  window.toggleMobileSidebarV37?.(false);
  return baseSetPage417?.(page)
};
```

`NavigationStability` remains the outer live navigation coordinator after `app.js`.

Real Chrome now explicitly proves final navigation closes `#sidebar.mobile-open` and `#sideBackdrop.show`.

## 5. Permanent guards / tests

Main frontend workflow includes all owner guards through `Retired pass-through setPage guard`, then runs all `tests/frontend/*.test.mjs`.

Sidebar debt is permanently guarded by:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
```

Browser behavior is guarded by:

```text
tests/browser/navigation-stability.spec.mjs
→ final navigation owner closes the mobile sidebar and backdrop
```

Do not restore early V37 navigation ownership.

## 6. Current setPage audit

Current static read after accepted sidebar cleanup shows **8 remaining historical `window.setPage=function...` assignments** (baseline was 10, then set423 removed, then V37 duplicate removed).

Do not infer liveness from version number alone. The key control-flow fact is that later direct assignments sever earlier wrapper chains.

Confirmed pre-v42.4 candidate family:

```text
oldSetV39
oldSet42
set422Base
```

Each currently appears only as a local base capture plus its own wrapper call. Later v42.4 performs:

```js
window.setPage=function(p){state.page=p;render()};
```

without calling the prior owner, so earlier wrappers are likely unreachable after full synchronous script load.

Before deletion, re-check exact references against live HEAD and prove any visible behavior needed today is owned later. Do not “restore” old semantics merely because the old wrapper contained them.

## 7. Wrappers that must NOT be swept into the next batch

```text
setPageReady414       startup snapshot/uiReady gate
baseSetPage417        current classic sidebar-close owner
NavigationStability   request epoch + PollRegistry navigation lifecycle
later live aliases / cache / persistence wrappers unless separately proven dead
```

## 8. Work order

```text
1. pre-v42.4 dead setPage family bounded deletion
2. remaining renderer/setPage obsolete override closure
3. proven dead app.js + global reload/request debt
4. cache-busting unification
5. zero-point MutationObserver/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. resume A800 RC
```

Every batch: current HEAD → reference/liveness proof → regression → physical deletion → permanent guard → full frontend + Real Chrome → update all four handoff docs.

## 9. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
