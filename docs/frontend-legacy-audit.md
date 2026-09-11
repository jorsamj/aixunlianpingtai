# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: b74124b974ee12c3bf113fc7a4a336cb706e81f6
run:    34614368651

frontend:     PASS
Real Chrome:  PASS
```

Current caches:

```text
app.js                    42.25.47
main.mjs                  42.25.52
navigation-stability      422505
poll-registry             422510
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

Source cleanup physically removed:

```text
source422Timer
classic source interval creation/clear
installSourceCreationBridge
__pollRegistrySourceWrapped
originalRenderSources / wrappedRenderSources
registry.adopt('sources', ...)
NavigationStability source-timer fallback
```

Real Chrome proves source polling starts on the page and stops on navigation.

## 3. Permanently retired timer compatibility

```text
auto422Timer
ai60ListTimer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
source422Timer
```

Do not recreate compatibility shims for these names.

## 4. Only remaining PollRegistry creation bridge

```text
installPollingCreationBridge()
→ wraps setupPagePolling
→ setupPagePolling creates state.jobPollTimer
→ replaceTrainingJobTimer() replaces it
```

This is the next cleanup target.

Desired shape:

```text
page lifecycle
→ explicit replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
```

Expected physical retirement after proof:

```text
jobPollTimer state compatibility
installPollingCreationBridge
originalSetupPagePolling / wrappedSetupPagePolling
__pollRegistryCreationWrapped
registry.adopt('training-jobs', ...)
classic setupPagePolling interval creation
```

`TrainingTaskRuntime` remains the request owner; PollRegistry remains the timer owner.

## 5. Existing training polling contracts that must survive

- one in-flight `/jobs` refresh;
- 120ms poll/manual coalescing;
- mutation refresh force-fresh;
- manual refresh re-arms PollRegistry;
- Real Chrome expects one `/jobs` GET per manual refresh;
- page navigation clears `training-jobs`.

Do not replace focused refresh with `loadAll()`.

## 6. After the training bridge

Build a renderer/setPage owner table before deleting historical layers. Audit at minimum:

```text
render = ...
window.setPage = ...
setupPagePolling
renderXXX412 / 417 / 423 / 428 / 429
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

## 7. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. Retired training mirrors/fallbacks stay retired.
4. No mother-model class inheritance on first training.
5. Explicit false/zero training settings survive end-to-end.
6. Do not weaken duplicate-request/race/performance/browser tests.
7. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
8. AutoLabel remains PollRegistry-only.
9. Video/source direct lifecycle handoffs must not regress to wrappers.
10. Frontend CI is not A800/CUDA acceptance.
