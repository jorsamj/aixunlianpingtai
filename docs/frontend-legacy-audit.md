# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: eb76e48adaafe3c71556918d42efc98cca5d8f2f
run:    34620286461
frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                    42.25.52
main.mjs                  42.25.53
navigation-stability      422506
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
Batch A: setupPagePolling/jobPollTimer                CLOSED
Batch B: set423Base + setBase424                     CLOSED
Batch C: duplicate V37 baseSetPage sidebar wrapper   CLOSED
Batch D: oldSetV39 + oldSet42 + set422Base           CLOSED
```

Batch D was proven dead by source-order/reference guards: each base token had exactly declaration + self-wrapper call, then v42.4 synchronously replaced `window.setPage` without invoking the previous owner. Acceptance `eb76e48a... / run 34620286461` passed full Real Chrome.

Permanent static guards:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
```

## 4. Current setPage topology

Current `static/app.js` scan shows 7 remaining `window.setPage=` assignments/bindings:

```text
initial function binding
UI-state persistence direct assignment
v35 direct state.page/render
v42.4 direct state.page/render
v42.7 direct auto-label alias
setPageReady414 async readiness wrapper
baseSetPage417 sidebar-close wrapper
```

The likely final live chain begins at v42.7 because that assignment discards the previous `window.setPage`; `setPageReady414` then wraps v42.7 and V417 wraps readiness. `NavigationStability` wraps the final classic owner after module load.

## 5. Next candidate — pre-v42.7 dead direct assignments

Potentially dead after full synchronous script initialization:

```text
UI-state persistence direct assignment
v35 direct state.page/render assignment
v42.4 direct state.page/render assignment
```

Do not delete merely because v42.7 overwrites them. Before deletion prove:

```text
1. source order is earlier-direct-assignments → v42.7 reset
2. no immediate synchronous setPage call between those assignments depends on their temporary behavior
3. no closure retains the older assigned functions
4. current persistence requirements are satisfied elsewhere
5. current navigation aliases/routes remain covered by v42.7/later owners
6. setPageReady414, baseSetPage417 and NavigationStability remain untouched
```

If a prior direct assignment is used during initialization, split the family further instead of broad deletion.

## 6. Protected navigation contracts

```text
setPageReady414
  wait for __v53InitPromise while uiReady=false

baseSetPage417
  close mobile sidebar/backdrop

NavigationStability
  request epoch
  PageRequestScope alignment
  PollRegistry leave/enter
  stale async-owner protection
```

Real Chrome explicitly verifies sidebar/backdrop close after final navigation.

## 7. Remaining audit targets

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

## 9. Work order

```text
1. pre-v42.7 dead direct setPage family
2. remaining obsolete render/setPage layers
3. app.js dead code + global reload/request debt
4. cache-busting unification
5. zero-point observer/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. A800 RC
```
