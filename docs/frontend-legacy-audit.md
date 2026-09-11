# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: f3eb6b360123dd688eea4dd0f29c05a9db5b4c05
run:    34619698115

frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                    42.25.51
main.mjs                  42.25.53
navigation-stability      422506
poll-registry             422511
training-draft-runtime    422516
training-labels           422513
auto-label-poll-runtime   422501
```

Branch HEAD may be ahead because documentation commits follow accepted code commits.

## 2. Closed owner surfaces

### Training canonical state / submit

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired mirrors/fallbacks:

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

### Training polling

```text
classic render call site
→ replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
→ TrainingTaskRuntime.refresh({source:'poll'})
→ focused /jobs refresh
```

Retired: `jobPollTimer`, `setupPagePolling`, creation wrappers/adoption/rebind and NavigationStability fallback.

### AutoLabel / Video / Sources

```text
renderOps427 → AutoLabelPollRuntime → PollRegistry(auto-label-v60)
renderVideo424 / refreshVideo424Delta → PollRegistry(video-frames)
renderSources422 → PollRegistry(sources)
```

Legacy timer/renderer wrapper ownership is gone.

## 3. Navigation cleanup accepted so far

### Batch A — training polling shell

```text
setupPagePolling = 0
jobPollTimer      = 0
```

### Batch B — pass-through setPage family

Physically removed:

```text
set423Base
setBase424
```

### Batch C — duplicate mobile-sidebar setPage owner

The earlier V37 wrapper:

```text
const baseSetPage=window.setPage;
window.setPage=function(page){toggleMobileSidebarV37(false);baseSetPage(page)};
```

is physically gone.

The later V417 owner remains:

```text
const baseSetPage417=window.setPage;
window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};
```

Permanent static guard:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
```

Permanent browser behavior contract:

```text
tests/browser/navigation-stability.spec.mjs
→ final navigation owner closes the mobile sidebar and backdrop
```

## 4. Current setPage chain audit

Baseline before deletion contained 10 historical `window.setPage=function...` assignments. After accepted Batch B and C, current static read reports 8.

Important liveness rule: a wrapper can contain meaningful code yet still be dead if a later direct `window.setPage = ...` assignment discards it and no other reference retains it.

### Next candidate — pre-v42.4 dead family

Current exact reference reads show:

```text
oldSetV39   → declaration + own wrapper call only
oldSet42    → declaration + own wrapper call only
set422Base  → declaration + own wrapper call only
```

Their historical semantics were:

```text
oldSetV39  deployment-page deployLoaded invalidation
oldSet42   v42 page-family loaded invalidation
set422Base aliases 新建算法/自动迭代 → 算法列表
```

Then v42.4 directly assigns:

```text
window.setPage=function(p){state.page=p;render()};
```

without calling previous owner. This appears to sever all three wrappers from the final chain.

Before deletion, prove:

```text
1. no external/local references retain these wrappers
2. source order places v42.4 direct reset after them
3. current visible navigation contracts are covered by later router/render owners
4. deletion leaves syntax/unit/Real Chrome green
```

This is dead-code cleanup, not an instruction to reintroduce old invalidation/alias behavior.

## 5. Do-not-delete-yet navigation owners

```text
setPageReady414
  waits for __v53InitPromise when uiReady is false

baseSetPage417
  current classic mobile sidebar close owner

NavigationStability
  request epoch
  PageRequestScope navigation alignment
  PollRegistry before/after navigation
  stale async-owner protection
```

Later aliases/cache/persistence layers require their own liveness proof.

## 6. Existing training polling contracts that must survive

- one in-flight `/jobs` refresh;
- 120ms poll/manual coalescing;
- mutation refresh force-fresh;
- manual refresh re-arms PollRegistry;
- exactly one `/jobs` GET per manual refresh in Real Chrome;
- navigation clears `training-jobs`;
- no `loadAll()` replacement for focused polling.

## 7. Minimum audit targets after setPage cleanup

```text
render = ...
window.setPage = ...
renderXXX412 / 417 / 423 / 424 / 425 / 427 / 428 / 429
loadAll()
loadRelated()
loadCore412()
MutationObserver
setInterval
setTimeout
window.fetch =
```

For every family:

```text
prove final owner
→ identify independent semantics
→ deterministic regression
→ physical deletion
→ permanent guard
→ syntax/unit
→ Real Chrome when behavior/navigation changes
→ docs sync
```

## 8. Permanent non-regression rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. Retired training mirrors/fallbacks stay retired.
4. No mother-model class inheritance on first training.
5. Explicit false/zero training settings survive end-to-end.
6. Do not weaken duplicate-request/race/performance/browser tests.
7. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
8. AutoLabel remains PollRegistry-only.
9. Video/source/training polling ownership stays direct.
10. Frontend CI is not A800/CUDA acceptance.

## 9. Work order

```text
1. pre-v42.4 dead setPage family
2. remaining obsolete render/setPage layers
3. app.js dead code + global reload/request debt
4. cache-busting unification
5. zero-point observer/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. A800 RC
```
