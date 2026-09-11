# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 4cabbe84d7af37cc7cdf11aa2e8dc00db9be3386
run:    34617573070

frontend:     PASS
Real Chrome:  PASS
```

Current caches:

```text
app.js                    42.25.49
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
classic render call site
→ replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
→ TrainingTaskRuntime.refresh({source:'poll'})
→ focused /jobs refresh
```

Physical retirement completed:

```text
jobPollTimer
setupPagePolling
classic setupPagePolling interval creation/clear
installPollingCreationBridge
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
NavigationStability jobPollTimer fallback
```

Permanent CI now rejects `setupPagePolling` and `jobPollTimer` in active product runtime.

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
setupPagePolling
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

Permanent CI `Training PollRegistry direct owner guard` protects this boundary.

## 5. Renderer / setPage override audit: ACTIVE

The owner map is now maintained in `docs/FRONTEND_OWNER_MAP_V42_25.md`.

Baseline audit before the first deletion batch found:

```text
10 historical window.setPage=function... assignments
22 historical render=function... assignments
2 setupPagePolling shells
```

After Batch A:

```text
setupPagePolling active references = 0
jobPollTimer active references      = 0
training polling handoff            = direct replaceTrainingJobTimer()
```

### Current next proven candidate

v42.3 contains a pure forwarding layer:

```text
const set423Base=window.setPage;
window.setPage=function(p){set423Base(p)};
try{setPage=window.setPage}catch(e){}
```

Current search found `set423Base` only in that declaration+forwarding wrapper. The immediately following v42.4 generation resets `window.setPage` directly:

```text
const setBase424=window.setPage;
window.setPage=function(p){state.page=p;render()};
try{setPage=window.setPage}catch(e){}
```

`setBase424` currently has no use beyond its declaration. Before removal, re-run those reference checks against current HEAD. If still true, this is a bounded dead-wrapper family suitable for the next guarded deletion.

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

`NavigationStability` wraps the final classic `window.setPage` and remains part of the live navigation contract.

## 6. Required final-owner proof per deletion

For every wrapper family:

```text
current final owner
all references to wrapper/base variable
independent semantics of the layer
regression that proves surviving behavior
physical deletion
syntax + focused unit
Real Chrome if behavior/navigation changes
docs sync
```

Minimum audit targets remain:

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
1. remove first proven pure-pass-through setPage family
2. continue obsolete render/setPage physical deletion in bounded batches
3. remove proven dead app.js / global reload-request debt
4. unify cache-busting
5. zero-point observer/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs sync
7. technical-debt zero-point scan
8. resume A800 RC
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
