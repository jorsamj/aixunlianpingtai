# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                    refactor/frontend-runtime-stabilization
latest full code acceptance: eb76e48adaafe3c71556918d42efc98cca5d8f2f
Frontend Runtime run:      34620286461
formal VERSION.txt:        42.24.0
frontend badge:            v42.25.0-dev
app.js cache:              42.25.52
main.mjs cache:            42.25.53
NavigationStability:       422506
PollRegistry:              422511
TrainingDraftRuntime:      422516
TrainingLabelRuntime:      422513
TrainingSubmitRuntime:     training-submit-422504
TrainingTaskRuntime:       training-task-runtime-422503
AutoLabelPollRuntime:      422501
```

Run `34620286461` passed syntax, permanent owner guards, all frontend unit tests and all Real Chrome runtime regressions. Branch HEAD may be newer because docs are synced after accepted code points. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
pre-v42.7 dead direct setPage assignments
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

## 3. Closed frontend ownership

### Training submit

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired mirrors: `trainingLabelSelected`, `trainSplitV3`, `train429Selected`, `train428AlgorithmId`, `train428Config`, `trainingDraftFromLegacyState`.

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

Legacy polling timers/shells/wrappers/adoption compatibility are retired.

### Navigation cleanup accepted

Physically retired and permanently guarded:

```text
set423Base
setBase424
V37 baseSetPage duplicate sidebar wrapper
oldSetV39
oldSet42
set422Base
```

Accepted runs:

```text
setupPagePolling shells       4cabbe84... / 34617573070
set423Base/setBase424         871b1c91... / 34618276191
V37 duplicate sidebar owner   f3eb6b36... / 34619698115
pre-v42.4 dead family         eb76e48a... / 34620286461
```

Current protected classic owners include:

```text
v42.7 direct route owner
setPageReady414     startup snapshot readiness
baseSetPage417      mobile sidebar close
NavigationStability outer runtime coordinator
```

## 4. Current setPage topology

Current static scan after `eb76e48a...` shows 7 `window.setPage=` assignments/bindings total:

```text
1. initial function setPage(...) → window.setPage=setPage
2. UI-state persistence direct assignment
3. v35 direct state.page/render assignment
4. v42.4 direct state.page/render assignment
5. v42.7 direct auto-label alias assignment
6. setPageReady414 async wrapper
7. baseSetPage417 sidebar-close wrapper
```

The final live predecessor chain begins at v42.7 because it directly overwrites `window.setPage` without calling the prior owner, then `setPageReady414` wraps that owner, then V417 wraps readiness, then `NavigationStability` wraps final classic routing.

Next candidate therefore is the direct-assignment family before v42.7. Do not delete it until initialization-time calls and persistence semantics are audited.

## 5. Permanent tests / guards

Main workflow owner guards + all `tests/frontend/*.test.mjs`.

SetPage static guards:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
```

Browser contract:

```text
tests/browser/navigation-stability.spec.mjs
→ final navigation owner closes the mobile sidebar and backdrop
```

Do not weaken these tests.

## 6. Next exact audit

For the pre-v42.7 direct assignments, prove all of:

```text
A. source order: persistence → v35 → v42.4 → v42.7
B. no synchronous initialization path requires an earlier assignment before v42.7 executes
C. no closure stores an earlier direct assignment for later invocation
D. current UI persistence is still handled by render/saveUiState lifecycle where required
E. current aliases/routes are defined by v42.7 or later
F. setPageReady414 and baseSetPage417 remain untouched
```

Only after that proof should the three earlier direct assignments be physically deleted in one bounded family.

## 7. Non-regression backend contracts

- snapshot schema v3 and duplicate/leakage protection;
- `confirmed_empty` negative-sample semantics;
- task-runtime lease/generation/process fencing;
- explicit `batch`, `workers`, `cache=false` end-to-end;
- first training uses task-scoped labels only;
- no mother-model class inheritance on first training;
- iteration inherits only latest successful artifact-verified trainable version;
- metrics SQLite connections close deterministically.

## 8. Work order

```text
1. pre-v42.7 dead direct setPage family
2. remaining renderer/setPage obsolete override closure
3. proven dead app.js + global reload/request debt
4. cache-busting unification
5. zero-point MutationObserver/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. resume A800 RC
```

Every batch: live HEAD → liveness proof → deterministic regression → physical deletion → permanent guard → full frontend + Real Chrome → update all four handoff docs.

## 9. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
