# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                    refactor/frontend-runtime-stabilization
latest full code acceptance: ceab780b8f3d8314061d852bf2eccc8db9235f54
Frontend Runtime run:      34644092284
formal VERSION.txt:        42.24.0
frontend badge:            v42.25.0-dev
app.js cache:              42.25.53
main.mjs cache:            42.25.54
NavigationStability:       422507
UI state runtime:          422500
PollRegistry:              422511
TrainingDraftRuntime:      422516
TrainingLabelRuntime:      422513
TrainingSubmitRuntime:     training-submit-422504
TrainingTaskRuntime:       training-task-runtime-422503
AutoLabelPollRuntime:      422501
```

Run `34644092284` passed syntax, permanent owner guards, all frontend unit tests and all Real Chrome runtime regressions. Branch HEAD may be newer because docs are synced after accepted code points. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
remaining setPage semantic-chain consolidation
→ remaining renderer override owner audit
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
v34 persistence direct setPage
v35 plain direct setPage
v42.4 plain direct setPage
```

Accepted milestones include:

```text
setupPagePolling shells       4cabbe84... / 34617573070
set423Base/setBase424         871b1c91... / 34618276191
V37 duplicate sidebar owner   f3eb6b36... / 34619698115
pre-v42.4 dead family         eb76e48a... / 34620286461
navigation persistence fix    cd92639a... / 34621453809
pre-v42.7 direct family       ceab780b... / 34644092284
```

Current protected semantic owners:

```text
v42.7 direct route/alias owner
setPageReady414     startup snapshot readiness
baseSetPage417      mobile sidebar close
NavigationStability outer runtime coordinator
ui-state.js         semantic persistence owner
```

## 4. Current setPage topology

Current classic chain after the accepted pre-v42.7 cleanup is:

```text
initial function setPage(...) → window.setPage=setPage
v42.7 direct auto-label alias assignment
setPageReady414 async readiness wrapper
baseSetPage417 sidebar-close wrapper
NavigationStability final module wrapper
```

Important: the final live predecessor chain begins at v42.7 because that assignment discards the earlier direct `window.setPage` owners. The initial bootstrap binding is still physically present and must not be deleted until closure/liveness capture is audited.

Current real semantics:

```text
v42.7:
  自动标注 → 自动标注及清洗 alias

setPageReady414:
  if uiReady=false and __v53InitPromise exists, wait before navigation

baseSetPage417:
  close mobile sidebar/backdrop on navigation

NavigationStability:
  navigation epoch
  PageRequestScope align/cancel
  PollRegistry leave/enter
  async completion fencing
  persistNavigationState()

ui-state.js:
  persist current page/project/dataset/imageFilter while preserving unrelated keys
```

The v34 persistence `setPage` is gone. Real Chrome verifies: navigate to “数据集” → localStorage page becomes “数据集” → reload restores “数据集”.

## 5. Permanent tests / guards

Main workflow owner guards + all `tests/frontend/*.test.mjs`.

SetPage/navigation contracts:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
  # historical filename; current semantics guard all pre-v42.7 direct owners
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

Browser contract in `tests/browser/navigation-stability.spec.mjs` includes:

```text
stale delayed request cannot jump back
managed page polling stops on leave
final navigation closes mobile sidebar/backdrop
selected page persists and restores after reload
```

Do not weaken these tests.

## 6. Evidence for the last deletion batch

Before deleting v34/v35/v42.4 direct owners, a temporary Acorn AST audit proved:

```text
v34 persist → v35 plain       load-time immediate setPage calls = 0
v35 plain   → v42.4 plain     load-time immediate setPage calls = 0
v42.4 plain → v42.7 alias     load-time immediate setPage calls = 0
```

The temporary AST audit and migration helper/workflows were physically deleted after acceptance. Do not reintroduce them as permanent debt.

## 7. Next exact audit

Do not blanket-delete the remaining navigation layers. Build a semantic owner table for:

```text
A. initial bootstrap function setPage / window.setPage binding
B. v42.7 alias owner
C. setPageReady414 readiness wrapper
D. baseSetPage417 sidebar wrapper
E. NavigationStability final wrapper
```

For each candidate prove:

```text
1. source-order and capture/reference liveness
2. whether any historical closure stores that exact function for later invocation
3. which semantic behavior would be lost by deletion
4. whether that behavior can move into a named semantic runtime without changing timing
5. dedicated unit/browser contract exists before migration
6. only then physically remove one bounded owner
```

Alias, readiness and sidebar behavior are real product semantics. Their versioned wrappers may be technical debt, but the behaviors are not disposable.

## 8. Non-regression backend contracts

- snapshot schema v3 and duplicate/leakage protection;
- `confirmed_empty` negative-sample semantics;
- task-runtime lease/generation/process fencing;
- explicit `batch`, `workers`, `cache=false` end-to-end;
- first training uses task-scoped labels only;
- no mother-model class inheritance on first training;
- iteration inherits only latest successful artifact-verified trainable version;
- metrics SQLite connections close deterministically.

## 9. Work order

```text
1. remaining setPage semantic-chain consolidation
2. remaining renderer/setPage obsolete override closure
3. proven dead app.js + global reload/request debt
4. cache-busting unification
5. zero-point MutationObserver/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. resume A800 RC
```

Every batch: live HEAD → liveness proof → deterministic regression → physical deletion → permanent guard → full frontend + Real Chrome → update all four handoff docs.

## 10. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
