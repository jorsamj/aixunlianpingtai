# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: f6e71c05d35b1a39b0b79e1b652cf901044c68bd
Frontend Runtime run:        34653776200
formal VERSION.txt:          42.24.0
frontend badge:              v42.25.0-dev
app.js cache:                42.25.56
main.mjs cache:              42.25.57
NavigationStability:         422510
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34653776200` passed syntax, permanent navigation/owner guards, all frontend unit tests and Real Chrome 12/12. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
initial bootstrap setPage capture/liveness migration
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
baseSetPage417 mobile-sidebar wrapper
```

Latest milestones:

```text
v42.7 alias owner             bdfb7ae6... / 34645250462
readiness owner retired       1470bb9f... / 34652823778
sidebar double-owner          d6b9e459... / 34653340984
sidebar owner retired         f6e71c05... / 34653776200
```

## 4. Current setPage topology

Current chain is now only:

```text
initial function setPage(p){ state.page=p; render(); } → window.setPage=setPage
→ NavigationStability final coordinator
```

Named `NavigationStability` owns:

```text
normalizeNavigationPage()
  自动标注 → 自动标注及清洗

waitForNavigationReady()
  !state.uiReady && window.__v53InitPromise
  → wait before actual page mutation/render

beforeInvokeNavigation()
  window.toggleMobileSidebarV37(false)
  → close #sidebar.mobile-open + #sideBackdrop.show

navigation lifecycle
  PageRequestScope navigation intent
  navigation epoch
  PollRegistry before/after
  async finalization
  persistNavigationState()
```

Current tested order:

```text
request:navigate
→ poll:before
→ readiness wait
→ beforeInvokeNavigation / sidebar cleanup
→ predecessor actual state.page mutation + render
→ request:align
→ poll:after
→ persistence
```

Real Chrome verifies readiness, sidebar/backdrop close, legacy alias normalization, stale request fencing and persistence/reload restoration.

## 5. Remaining classic setPage owner — initial bootstrap binding

Current code:

```js
function setPage(p){state.page=p;render()}
window.setPage=setPage;
```

This binding is still live because `NavigationStability` captures `window.setPage` as its predecessor. Its remaining semantic responsibility is only:

```text
state.page = requestedPage
render() using the final classic render chain
```

Important startup finding:

```text
window.__clInit does not call setPage().
It loads startup data, sets state.uiReady and calls render() directly.
```

Therefore startup bootstrap is not a reason to keep the binding. The actual migration target is to let `NavigationStability` own `window.setPage` even when no predecessor exists, with a named `performNavigation/applyPage` hook supplied by `main.mjs` for `state.page = page; render()`.

Do not physically delete the bootstrap function yet. First prove the named owner can perform the same single mutation/render without double-rendering.

## 6. Permanent tests / guards

Frontend navigation contracts:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

Current permanent guard requires bootstrap `setPage` to remain exactly until its own migration finishes. Once the named actual-navigation owner is proven and the bootstrap is deleted, this guard must flip to “bootstrap binding cannot return”.

Browser contracts:

```text
tests/browser/navigation-stability.spec.mjs
tests/browser/navigation-readiness.spec.mjs
```

Do not weaken them.

## 7. Next exact migration: initial bootstrap setPage

Required sequence:

```text
1. Extend NavigationStability with a named performNavigation/applyPage hook.
2. If the hook is provided, it becomes the sole actual mutation/render owner; do not also call the classic predecessor.
3. Keep current predecessor path temporarily as fallback only during equivalence testing.
4. Make NavigationStability install window.setPage even when no classic predecessor exists.
5. main.mjs supplies the actual state.page mutation + final render call.
6. Unit tests lock one render only and exact lifecycle ordering.
7. Real Chrome verifies menu/programmatic navigation, readiness, sidebar and persistence.
8. After equivalence, physically delete `function setPage... window.setPage=setPage` from app.js.
9. Flip permanent guard: bootstrap binding must be absent; named apply hook must exist.
10. Remove any temporary migration helper/workflow and rerun full frontend + Chrome.
```

A failed experiment must leave the branch on the previously accepted owner topology; do not leave half-migrated navigation code.

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
1. initial bootstrap setPage migration
2. remaining renderer/setPage obsolete override closure
3. proven dead app.js + global reload/request debt
4. cache-busting unification
5. zero-point MutationObserver/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. resume A800 RC
```

Every batch: live HEAD → liveness/semantic proof → deterministic regression → named semantic owner → double-owner proof → physical deletion → permanent guard → full frontend + Real Chrome → docs sync.

## 10. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
