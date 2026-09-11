# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 05abf71d067d4b1e08a2bdeeb9d7787e9fc06dd4
run:    34655960701
frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                    42.25.57
main.mjs                  42.25.59
navigation-stability      422511
ui-state                  422500
poll-registry             422511
training-draft-runtime    422516
training-labels           422513
auto-label-poll-runtime   422501
```

## 2. Closed owner surfaces

### Training

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired training mirrors/fallbacks stay retired.

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

No classic timer or creation-wrapper ownership may return.

### Navigation — classic owner family zero-point CLOSED

Accepted batches:

```text
setupPagePolling/jobPollTimer                              CLOSED
set423Base + setBase424                                   CLOSED
duplicate V37 baseSetPage sidebar wrapper                 CLOSED
oldSetV39 + oldSet42 + set422Base                         CLOSED
navigation persistence → named runtime                    CLOSED
v34/v35/v42.4 direct setPage family                       CLOSED
v42.7 direct auto-label alias owner                       CLOSED
setPageReady414 startup readiness                         CLOSED
baseSetPage417 sidebar close                              CLOSED
initial bootstrap setPage mutation/render owner           CLOSED
```

Latest evidence:

```text
sidebar final                 f6e71c05... / 34653776200 PASS
named actual-owner equivalence 04b6982e... / 34655575856 PASS
bootstrap final               05abf71d... / 34655960701 PASS
```

`static/app.js` must now contain **zero** classic `window.setPage=` assignments. Permanent CI enforces this.

## 3. Final navigation topology

```text
NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page)
       state.page = page
       render()
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistNavigationState
```

`NavigationStability` installs global `window.setPage` even without a predecessor. When `performNavigation` is configured, no classic predecessor is invoked. Unit tests explicitly prove one named apply / one render / zero classic calls.

The following remain permanent browser contracts: menu navigation, programmatic `window.setPage`, startup readiness, sidebar/backdrop close, stale request fencing, PollRegistry stop-on-leave, alias canonicalization and persistence/reload.

## 4. Current target — classic render override family

The next debt is the historical `render` capture/override chain, not navigation.

Known live/debt areas:

```text
base/global render() shell
render = function(...) historical overrides
const old/finalRender = render capture layers
v42.7 render-level 自动标注 → 自动标注及清洗 fallback
renderXXX412 / 417 / 423 / 424 / 425 / 427 / 428 / 429
NavigationStability PAGE_RENDERERS ownership guards
startup __clInit direct render()
refresh handlers that call render() directly
```

Known render-level alias fallback:

```js
render=function(){
  if(state.page==='自动标注') state.page='自动标注及清洗';
  ...
}
```

Navigation already canonicalizes aliases before `performNavigation`, so this fallback is a candidate for retirement. However startup and refresh paths can call `render()` directly; its liveness must be proven before deletion.

## 5. Audit method for render family

For every candidate generation:

```text
live HEAD
→ enumerate exact assignment/capture/reference topology
→ identify final live owner vs fully shadowed generation
→ lock real semantic behavior
→ migrate semantic ownership if needed
→ double-owner equivalence where semantics move
→ bounded physical deletion
→ permanent guard
→ frontend + Real Chrome
→ docs sync
```

Do not delete by version suffix alone. Do not add a global render-repair loop. Prefer page-scoped/semantic render owners and local DOM refreshes over periodic whole-page repaint.

## 6. Remaining technical-debt targets

```text
render override generations
loadAll / loadRelated / loadCore412 ownership
proven dead app.js code
global reload / duplicate requests
cache-busting heterogeneity
MutationObserver / setInterval / setTimeout / fetch lifecycle
version-number business naming
final zero-point scan
```

## 7. Non-negotiable rules

1. No new numbered compatibility generation.
2. Retired training mirrors/fallbacks stay retired.
3. Classic `setPage` ownership must remain zero in `app.js`.
4. No mother-model class inheritance on first training.
5. Explicit false/zero training settings survive end-to-end.
6. Trial/test inference must never receive GT labels.
7. Do not weaken duplicate-request/race/performance/Real Chrome tests.
8. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
9. AutoLabel remains PollRegistry-only.
10. Video/source/training polling direct ownership must not regress.
11. Frontend CI is not A800/CUDA acceptance.

## 8. Work order

```text
1. render override owner audit / obsolete generation deletion
2. app.js dead code + global reload/request debt
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```
