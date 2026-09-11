# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: bdfb7ae692a197486dc61ed9919c5e18ae1bf9f4
Frontend Runtime run:        34645250462
formal VERSION.txt:          42.24.0
frontend badge:              v42.25.0-dev
app.js cache:                42.25.54
main.mjs cache:              42.25.55
NavigationStability:         422508
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34645250462` passed syntax, permanent owner guards, all frontend unit tests and all Real Chrome runtime regressions. Branch HEAD may be newer because docs are synced after accepted code points. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
setPageReady414 startup-readiness migration
→ baseSetPage417 sidebar migration
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
```

Accepted milestones include:

```text
setupPagePolling shells       4cabbe84... / 34617573070
set423Base/setBase424         871b1c91... / 34618276191
V37 duplicate sidebar owner   f3eb6b36... / 34619698115
pre-v42.4 dead family         eb76e48a... / 34620286461
navigation persistence fix    cd92639a... / 34621453809
pre-v42.7 direct family       ceab780b... / 34644092284
v42.7 alias owner             bdfb7ae6... / 34645250462
```

## 4. Current setPage topology

Current classic/runtime chain:

```text
initial function setPage(...) → window.setPage=setPage
setPageReady414 async startup-readiness wrapper
baseSetPage417 mobile-sidebar wrapper
NavigationStability final module wrapper
```

Semantic alias normalization has moved to:

```text
NavigationStability.normalizeNavigationPage()
自动标注 → 自动标注及清洗
```

The final runtime normalizes the requested page before PageRequestScope, PollRegistry, guard, predecessor invocation and UI-state persistence. Real Chrome proves the legacy `自动标注` route still enters and persists the canonical `自动标注及清洗` page after the classic direct alias owner was removed.

Current remaining classic semantics:

```text
setPageReady414:
  if uiReady=false and __v53InitPromise exists, await startup init before actual navigation

baseSetPage417:
  close mobile sidebar/backdrop on navigation

NavigationStability:
  canonical page normalization
  navigation epoch
  PageRequestScope cancellation/alignment
  PollRegistry before/after navigation
  async completion fencing
  persistNavigationState()
```

Important runtime-order nuance: `baseSetPage417` is defined inside `installUsability417`; although its source block appears earlier, `window.installUsability417?.()` executes later, after `setPageReady414`, so the live capture chain remains readiness → sidebar → NavigationStability.

## 5. Permanent tests / guards

Main workflow owner guards + all `tests/frontend/*.test.mjs`.

Navigation contracts:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
  # historical filename; now also forbids v42.7 direct alias owner
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
legacy 自动标注 route canonicalizes and persists as 自动标注及清洗
```

Do not weaken these tests.

## 6. Next exact audit: startup readiness

Do not delete `setPageReady414` yet.

Current code semantics:

```js
const setPageReady414 = window.setPage;
window.setPage = async function(page) {
  if (!state.uiReady && window.__v53InitPromise) await window.__v53InitPromise;
  return setPageReady414(page);
};
```

Before migration:

```text
1. Add a Real Chrome contract for navigation requested while startup is not ready.
2. While __v53InitPromise is pending, the requested page must not render early.
3. After init resolves, the requested page must navigate exactly once.
4. Final state/localStorage must be the requested canonical page.
5. PageRequestScope / PollRegistry / persistence ordering must remain correct.
6. Migrate readiness into NavigationStability or a named readiness hook.
7. Run a double-owner equivalence phase.
8. Only then physically remove setPageReady414.
9. Keep baseSetPage417 untouched in this batch.
```

`tests/frontend/navigation-persistence.test.mjs` covers a generic async predecessor, but it does **not** replace the required browser-level startup readiness contract.

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
1. setPageReady414 readiness migration
2. baseSetPage417 sidebar migration
3. remaining renderer/setPage obsolete override closure
4. proven dead app.js + global reload/request debt
5. cache-busting unification
6. zero-point MutationObserver/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs
8. technical-debt zero-point scan
9. resume A800 RC
```

Every batch: live HEAD → liveness/semantic proof → deterministic regression → physical deletion → permanent guard → full frontend + Real Chrome → update all four handoff docs.

## 9. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
