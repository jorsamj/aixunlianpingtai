# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: 1470bb9f0dd19e1be5d0695cd7f4de21173dd944
Frontend Runtime run:        34652823778
formal VERSION.txt:          42.24.0
frontend badge:              v42.25.0-dev
app.js cache:                42.25.55
main.mjs cache:              42.25.56
NavigationStability:         422509
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34652823778` passed syntax, permanent owner guards, all frontend unit tests and Real Chrome 12/12. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
baseSetPage417 sidebar migration
→ initial bootstrap setPage liveness audit
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
V37 duplicate baseSetPage sidebar wrapper
oldSetV39
oldSet42
set422Base
v34 persistence direct setPage
v35 plain direct setPage
v42.4 plain direct setPage
v42.7 direct auto-label alias setPage
setPageReady414 startup-readiness wrapper
```

Latest milestones:

```text
pre-v42.7 direct family       ceab780b... / 34644092284
v42.7 alias owner             bdfb7ae6... / 34645250462
readiness baseline            0adc46fe... / 34652201043
readiness double-owner        a618696e... / 34652478444
readiness owner retired       1470bb9f... / 34652823778
```

## 4. Current setPage topology

Current classic/runtime chain:

```text
initial function setPage(...) → window.setPage=setPage
baseSetPage417 mobile-sidebar wrapper
NavigationStability final module wrapper
```

Named `NavigationStability` now owns:

```text
normalizeNavigationPage()
  自动标注 → 自动标注及清洗

waitForNavigationReady()
  !state.uiReady && window.__v53InitPromise
  → wait before actual page mutation/render

navigation lifecycle
  PageRequestScope navigation intent
  navigation epoch
  PollRegistry before/after
  async finalization
  persistNavigationState()
```

Important readiness ordering is permanently tested:

```text
request:navigate
→ poll:before
→ readiness wait
→ predecessor/classic page mutation
→ request:align
→ poll:after
→ persistence
```

Real Chrome `tests/browser/navigation-readiness.spec.mjs` delays `/api/v53/bootstrap/snapshot`, proves `state.page` does not change early, then proves the requested page renders/persists only after startup resolves.

## 5. Remaining classic setPage semantic owner

### `baseSetPage417`

Current code semantics:

```js
const baseSetPage417=window.setPage;
window.setPage=function(page){
  window.toggleMobileSidebarV37?.(false);
  return baseSetPage417?.(page);
};
```

It closes `#sidebar.mobile-open` and `#sideBackdrop.show` before invoking the predecessor. Existing Real Chrome already checks navigation closes both.

Do not delete it yet. First move this exact behavior into a named NavigationStability before-navigation hook, run a double-owner phase, then physically delete the classic wrapper.

The initial bootstrap `function setPage(...) → window.setPage=setPage` remains out of scope until the sidebar wrapper is closed and its capture/liveness is audited separately.

## 6. Permanent tests / guards

Frontend navigation contracts:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

Browser contracts:

```text
tests/browser/navigation-stability.spec.mjs
tests/browser/navigation-readiness.spec.mjs
```

Do not weaken them.

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
1. baseSetPage417 sidebar migration
2. initial bootstrap setPage capture/liveness audit
3. remaining renderer/setPage obsolete override closure
4. proven dead app.js + global reload/request debt
5. cache-busting unification
6. zero-point MutationObserver/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs
8. technical-debt zero-point scan
9. resume A800 RC
```

Every batch: live HEAD → liveness/semantic proof → deterministic regression → named semantic owner → double-owner proof → physical deletion → permanent guard → full frontend + Real Chrome → docs sync.

## 9. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
