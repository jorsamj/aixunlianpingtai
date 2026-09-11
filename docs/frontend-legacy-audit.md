# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: ceab780b8f3d8314061d852bf2eccc8db9235f54
run:    34644092284
frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                    42.25.53
main.mjs                  42.25.54
navigation-stability      422507
ui-state                   422500
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
```

Batch F had explicit AST liveness proof before deletion:

```text
v34 persist → v35 plain       load-time immediate setPage calls = 0
v35 plain   → v42.4 plain     load-time immediate setPage calls = 0
v42.4 plain → v42.7 alias     load-time immediate setPage calls = 0
```

After physical deletion, `ceab780b... / run 34644092284` passed full frontend guards/unit and Real Chrome.

Permanent navigation guards/tests:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
  # filename is historical; semantics now guard all pre-v42.7 direct owners
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

## 4. Current setPage topology

The current classic/runtime chain is now bounded to:

```text
initial function setPage(...) → window.setPage=setPage
v42.7 direct auto-label alias
setPageReady414 async readiness wrapper
baseSetPage417 sidebar-close wrapper
NavigationStability final module wrapper
```

The three earlier direct assignments are gone. Do not reintroduce them.

### Semantic responsibility map

```text
v42.7 alias owner
  自动标注 → 自动标注及清洗

setPageReady414
  startup snapshot / uiReady fencing

baseSetPage417
  close mobile sidebar + backdrop

NavigationStability
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

Real Chrome explicitly verifies both sidebar close and selected-page persistence/reload restoration.

## 5. Navigation persistence incident fixed during cleanup

While preparing Batch F, a new Real Chrome contract found a real bug:

```text
visual page = 数据集
localStorage page = 算法列表
reload => wrong restored page
```

Root cause: the old v34 `saveUiState()` semantics lived under a historical render/setPage chain that later final renderers bypassed.

Final fix:

```text
NavigationStability finalizes actual page
→ persistNavigationState(currentState)
→ persistUiState() in static/modules/ui-state.js
```

For Promise-based readiness navigation, final align / PollRegistry afterNavigate / persistence happen only after the navigation Promise resolves.

## 6. Next candidate — remaining semantic setPage chain

Do **not** delete by version number. Audit these individually:

```text
initial bootstrap function setPage / window.setPage binding
v42.7 alias owner
setPageReady414 readiness wrapper
baseSetPage417 sidebar wrapper
NavigationStability final wrapper
```

Required questions before deletion/migration:

```text
1. Which closures captured the initial bootstrap function before v42.7?
2. Are any such closures still reachable after full script/module initialization?
3. Can alias normalization move into a named route-normalization function/runtime?
4. Can readiness move into NavigationStability without changing __v53InitPromise timing?
5. Can sidebar close move into final navigation runtime while preserving mobile behavior?
6. Is each semantic migration protected by focused unit + Real Chrome before classic code is deleted?
```

Treat alias/readiness/sidebar as real behavior, not dead code.

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
11. Old setPage semantics may be migrated to named runtimes, but behavior must be locked before removing the classic owner.

## 9. Work order

```text
1. remaining setPage semantic-chain consolidation
2. remaining obsolete render/setPage layers
3. app.js dead code + global reload/request debt
4. cache-busting unification
5. zero-point observer/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. A800 RC
```
