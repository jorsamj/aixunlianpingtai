# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: bdfb7ae692a197486dc61ed9919c5e18ae1bf9f4
run:    34645250462
frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                    42.25.54
main.mjs                  42.25.55
navigation-stability      422508
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
```

Batch G migrated the real alias behavior first:

```text
自动标注 → 自动标注及清洗
```

Final semantic owner is now `normalizeNavigationPage()` inside `NavigationStability`. A double-owner phase passed before physical deletion; after removal, `bdfb7ae6... / run 34645250462` passed permanent guards, all frontend unit tests and Real Chrome.

Permanent navigation guards/tests:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
  # historical filename; semantics now also forbid v42.7 direct alias owner
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

## 4. Current setPage topology

The current classic/runtime chain is now:

```text
initial function setPage(...) → window.setPage=setPage
setPageReady414 async readiness wrapper
baseSetPage417 sidebar-close wrapper
NavigationStability final module wrapper
```

The v42.7 direct `window.setPage` route owner is gone. Do not reintroduce it.

### Semantic responsibility map

```text
normalizeNavigationPage
  自动标注 → 自动标注及清洗
  canonical page before request/poll/guard/predecessor/persistence

setPageReady414
  startup snapshot / uiReady fencing

baseSetPage417
  close mobile sidebar + backdrop

NavigationStability
  canonical route normalization
  navigation epoch
  request-scope cancellation/alignment
  PollRegistry before/after navigation
  stale async fencing
  async finalization only after Promise completion
  final UI-state persistence callback

ui-state.js
  serialize/persist page, project, dataset, imageFilter
  preserve unrelated historical localStorage keys
```

Real Chrome explicitly verifies legacy route normalization, sidebar close and selected-page persistence/reload restoration.

Runtime-order note: V417 wrapper source is inside `installUsability417`, and that installer is invoked later. Therefore live capture order remains `setPageReady414 → baseSetPage417 → NavigationStability`, despite the function definition appearing earlier in the file.

## 5. Remaining classic render alias fallback

v42.7 still contains a render-level normalization:

```js
render=function(){
  if(state.page==='自动标注') state.page='自动标注及清洗';
  ...
}
```

This is no longer a `setPage` owner. Treat it as **render-chain debt** and audit it later with the renderer family. Do not mix its removal into the readiness batch.

## 6. Next candidate — `setPageReady414`

Current behavior:

```text
if uiReady=false and __v53InitPromise exists
→ await startup initialization
→ invoke previous setPage exactly once
```

The existing module unit test proves generic asynchronous predecessor finalization ordering, but there is not yet a Real Chrome contract that specifically gates a user navigation request against the startup promise.

Required before deletion:

```text
1. Add browser startup-before-ready navigation contract.
2. Requested page must not render while startup gate is pending.
3. Resolve startup gate and prove one navigation to the requested page.
4. Prove canonical page persistence after completion.
5. Move readiness to named runtime/hook.
6. Double-owner equivalence: unit + Real Chrome.
7. Physically delete setPageReady414 only after equivalence.
8. Leave baseSetPage417 unchanged.
```

## 7. Remaining audit targets

```text
baseSetPage417
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
→ regression
→ bounded physical deletion
→ permanent guard
→ syntax/unit
→ Real Chrome where relevant
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
11. Old setPage semantics may be migrated to named runtimes, but behavior must be locked before removing the classic owner.

## 9. Work order

```text
1. setPageReady414 readiness migration
2. baseSetPage417 sidebar migration
3. remaining obsolete render/setPage layers
4. app.js dead code + global reload/request debt
5. cache-busting unification
6. zero-point observer/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs
8. technical-debt zero-point scan
9. A800 RC
```
