# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: f6e71c05d35b1a39b0b79e1b652cf901044c68bd
run:    34653776200
frontend:     PASS
Real Chrome:  PASS (12/12)
```

Current caches/builds:

```text
app.js                    42.25.56
main.mjs                  42.25.57
navigation-stability      422510
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

## 3. Accepted navigation-debt batches

```text
Batch A: setupPagePolling/jobPollTimer                  CLOSED
Batch B: set423Base + setBase424                       CLOSED
Batch C: duplicate V37 baseSetPage sidebar wrapper     CLOSED
Batch D: oldSetV39 + oldSet42 + set422Base             CLOSED
Batch E: navigation persistence moved to final runtime CLOSED
Batch F: v34/v35/v42.4 direct setPage family           CLOSED
Batch G: v42.7 direct auto-label alias owner           CLOSED
Batch H: setPageReady414 startup-readiness owner       CLOSED
Batch I: baseSetPage417 mobile-sidebar owner           CLOSED
```

Batch H evidence:

```text
old-owner browser baseline    0adc46fe... / 34652201043 PASS
double-owner equivalence      a618696e... / 34652478444 PASS
classic owner physically gone 1470bb9f... / 34652823778 PASS
```

Batch I evidence:

```text
named hook + classic owner    d6b9e459... / 34653340984 PASS
classic owner physically gone f6e71c05... / 34653776200 PASS
```

`beforeInvokeNavigation` now owns `toggleMobileSidebarV37(false)` at the same semantic point as V417: after readiness resolution and immediately before actual page mutation/render. Real Chrome still proves both `#sidebar.mobile-open` and `#sideBackdrop.show` are removed on navigation.

## 4. Current setPage topology

The chain is now reduced to:

```text
initial function setPage(p){ state.page=p; render(); }
→ NavigationStability final module owner
```

### Named semantic responsibility map

```text
normalizeNavigationPage
  自动标注 → 自动标注及清洗

NavigationStability readiness hook
  request/poll navigation intent first
  waitForNavigationReady()
  startup __v53InitPromise fencing

NavigationStability pre-invoke hook
  beforeInvokeNavigation()
  close mobile sidebar/backdrop

NavigationStability final lifecycle
  navigation epoch
  request-scope cancellation/alignment
  PollRegistry before/after navigation
  stale async fencing
  UI-state persistence

ui-state.js
  serialize/persist page, project, dataset, imageFilter
```

### Remaining classic setPage responsibility

The initial bootstrap function is not another lifecycle wrapper. It is the actual page-application predecessor currently captured by `NavigationStability`:

```js
function setPage(p){state.page=p;render()}
window.setPage=setPage;
```

Its live semantics are exactly:

```text
state.page = page
render() using the final classic render chain
```

Startup `window.__clInit` does not use this function. It loads data and calls `render()` directly, so startup itself does not block retirement of the bootstrap binding.

## 5. Remaining render alias fallback

v42.7 still contains a render-level normalization:

```js
render=function(){
  if(state.page==='自动标注') state.page='自动标注及清洗';
  ...
}
```

This is no longer a `setPage` owner. Treat it as render-chain debt later; do not mix it into bootstrap setPage migration unless a contract proves it is safe to remove with the same batch.

## 6. Next candidate — initial bootstrap `setPage`

Required migration sequence:

```text
1. Add named `performNavigation` / `applyPage` hook to NavigationStability.
2. Hook owns exactly one state.page mutation + one final classic render call.
3. NavigationStability must install window.setPage even when no predecessor exists.
4. During equivalence, when named apply hook is configured, classic predecessor must not also mutate/render.
5. Unit tests lock exact order and single-render behavior.
6. Real Chrome covers menu navigation, programmatic window.setPage, readiness, sidebar and persistence.
7. Physically delete bootstrap function/binding only after equivalence.
8. Permanent guard flips from “bootstrap must remain” to “bootstrap must not return”.
9. Remove one-shot migration artifacts and run final full suite.
```

The migration must not scatter `state.page=...; render()` into another numbered classic block. The actual apply action must have one named owner.

## 7. Remaining audit targets

```text
initial bootstrap setPage binding
render = ...
renderXXX412 / 417 / 423 / 424 / 425 / 427 / 428 / 429
loadAll()
loadRelated()
loadCore412()
MutationObserver
setInterval
setTimeout
window.fetch =
```

Each family must follow:

```text
live HEAD
→ exact liveness/reference proof
→ behavior contract
→ named semantic owner
→ double-owner proof
→ bounded physical deletion
→ permanent guard
→ full Real Chrome where relevant
→ docs sync
```

## 8. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. Retired training mirrors/fallbacks stay retired.
4. No mother-model class inheritance on first training.
5. Explicit false/zero training settings survive end-to-end.
6. Do not weaken duplicate-request/race/performance/browser tests.
7. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
8. AutoLabel remains PollRegistry-only.
9. Video/source/training polling direct ownership must not regress.
10. Frontend CI is not A800/CUDA acceptance.
11. Old setPage semantics may move into named runtimes only after behavior is locked.
12. Initial bootstrap `setPage` cannot be deleted until named runtime owns the actual single page mutation/render action.

## 9. Work order

```text
1. initial bootstrap setPage migration
2. remaining obsolete render layers
3. app.js dead code + global reload/request debt
4. cache-busting unification
5. zero-point observer/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. A800 RC
```
