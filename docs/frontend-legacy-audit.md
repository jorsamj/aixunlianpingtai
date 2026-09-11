# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 774df651c3f278c782029e64bfa3315b12622a9f
run:    34616465336

frontend:     PASS
Real Chrome:  PASS
```

Current caches:

```text
app.js                    42.25.48
main.mjs                  42.25.53
navigation-stability      422506
poll-registry             422511
training-draft-runtime    422516
training-labels           422513
auto-label-poll-runtime   422501
```

Branch HEAD may be ahead because handoff docs are updated after accepted code commits.

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
page lifecycle / remaining historical setupPagePolling handoff
→ replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
→ TrainingTaskRuntime.refresh({source:'poll'})
→ focused /jobs refresh
```

Physical retirement completed:

```text
jobPollTimer
classic setupPagePolling interval creation/clear
installPollingCreationBridge
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
NavigationStability jobPollTimer fallback
```

`setupPagePolling` remains only as two historical one-line handoff shells and is no longer a timer owner.

### AutoLabel

```text
renderOps427
→ AutoLabelPollRuntime
→ PollRegistry(auto-label-v60)
```

No AutoLabel classic timer/renderer wrapper/rebind timer remains.

### Video

```text
renderVideo424 / refreshVideo424Delta
→ explicit replaceVideo424Timer()
→ PollRegistry(video-frames)
```

No video PollRegistry renderer wrapper/adoption remains.

### Sources

```text
renderSources422
→ explicit replaceSourceTimer()
→ PollRegistry(sources, 2500ms managed interval)
→ refreshSources422
```

No source state timer or PollRegistry renderer wrapper/adoption remains.

## 3. Permanently retired timer / creation compatibility

```text
auto422Timer
ai60ListTimer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
source422Timer
jobPollTimer
installVideo424CreationBridge
installSourceCreationBridge
installPollingCreationBridge
__pollRegistryVideoWrapped
__pollRegistrySourceWrapped
__pollRegistryCreationWrapped
```

Do not recreate compatibility shims for these names.

## 4. Existing training polling contracts that must survive

- one in-flight `/jobs` refresh;
- 120ms poll/manual coalescing;
- mutation refresh force-fresh;
- manual refresh re-arms PollRegistry;
- Real Chrome expects one `/jobs` GET per manual refresh;
- page navigation clears `training-jobs`;
- no `loadAll()`-style full refresh may replace focused polling.

Permanent CI `Training PollRegistry direct owner guard` protects the timer ownership boundary.

## 5. Renderer / setPage override audit: NEXT

Initial zero-point read found **10 `window.setPage=function...` historical layers** in `static/app.js`. They are not equivalent; examples already observed include:

```text
plain state.page=p; render()
mobile-sidebar close wrapper
v39 deployment-cache invalidation
v42 page-family cache invalidation
v42.2 aliases: 新建算法/自动迭代 → 算法列表
v42.3 pure pass-through setPage wrapper
v42.4 direct state.page=p; render()
v42.7 自动标注 alias → 自动标注及清洗
later mobile-sidebar/version-era wrapper
```

The current app also has multiple `render=function...` generations and version-era `renderXXX` owners. Therefore no blanket deletion is allowed.

### Current confirmed deletion candidates

1. `setupPagePolling` two one-line shells: now only call `replaceTrainingJobTimer()` and contain no independent business semantics.
2. pure pass-through `window.setPage=function(p){set423Base(p)}`-style wrapper, after confirming no identity/metadata dependency.
3. historical render layers completely superseded by a later renderer and not referenced by another wrapper/action.

### Wrappers that may still carry real semantics

Do not remove until their behavior is relocated/proven:

```text
page aliasing
mobile sidebar close
navigation/request epoch coordination
PollRegistry before/after navigation
page-specific cache invalidation
localStorage UI-state persistence
```

`NavigationStability` currently wraps the final `window.setPage` and is part of the live navigation contract.

## 6. Required final-owner table

Before physical deletion, build a table with at least these columns:

```text
surface/page
current visible renderer
current action owner
current setPage/router dependency
historical wrappers in chain
independent semantics still required?
regression test proving owner
safe-to-delete layer
```

Minimum audit targets:

```text
render = ...
window.setPage = ...
setupPagePolling
renderXXX412 / 417 / 423 / 424 / 425 / 427 / 428 / 429
loadAll()
loadRelated()
loadCore412()
MutationObserver
setInterval
setTimeout
window.fetch =
```

Deletion sequence:

```text
prove final owner
→ deterministic regression
→ physical deletion
→ syntax/unit
→ Real Chrome where behavior changes
→ update all 3 handoff docs
```

## 7. Current permanent guards

```text
Retired training mirror guard
Canonical training network owner guard
TrainingDraft classic wrapper guard
TrainingLabel canonical lifecycle guard
AutoLabel PollRegistry owner guard
Retired legacy poll timer compatibility guard
Video PollRegistry direct owner guard
Source PollRegistry direct owner guard
Training PollRegistry direct owner guard
```

## 8. Work order

```text
1. build renderer/setPage final-owner table
2. delete setupPagePolling shells + first proven obsolete wrapper family
3. continue obsolete render/setPage physical deletion in bounded batches
4. remove proven dead app.js / global reload-request debt
5. unify cache-busting
6. zero-point observer/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs sync
8. technical-debt zero-point scan
9. resume A800 RC
```

## 9. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. Retired training mirrors/fallbacks stay retired.
4. No mother-model class inheritance on first training.
5. Explicit false/zero training settings survive end-to-end.
6. Do not weaken duplicate-request/race/performance/browser tests.
7. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
8. AutoLabel remains PollRegistry-only.
9. Video/source/training polling direct lifecycle ownership must not regress to wrappers.
10. Frontend CI is not A800/CUDA acceptance.
