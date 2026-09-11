# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                    refactor/frontend-runtime-stabilization
latest full code acceptance: 4cabbe84d7af37cc7cdf11aa2e8dc00db9be3386
Frontend Runtime run:      34617573070
formal VERSION.txt:        42.24.0
frontend badge:            v42.25.0-dev
app.js cache:              42.25.49
main.mjs cache:            42.25.53
NavigationStability:       422506
PollRegistry:              422511
TrainingDraftRuntime:      422516
TrainingLabelRuntime:      422513
TrainingSubmitRuntime:     training-submit-422504
TrainingTaskRuntime:       training-task-runtime-422503
AutoLabelPollRuntime:      422501
```

Run `34617573070` passed syntax, every permanent owner guard, all frontend unit tests and all Real Chrome runtime regressions. `setupPagePolling` is now physically absent from active `static/app.js`. Branch HEAD may be newer because handoff docs are updated after the accepted code point. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
pure pass-through setPage wrapper proof/removal
→ remaining renderer/setPage obsolete layers
→ remaining frontend/runtime debt
→ zero-point debt scan
→ resume A800 RC
```

Read:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
docs/FRONTEND_OWNER_MAP_V42_25.md
```

## 3. Non-regression backend contracts

- snapshot schema v3 and duplicate/leakage protection;
- `confirmed_empty` negative-sample semantics;
- task-runtime lease/generation/process fencing;
- explicit `batch`, `workers`, `cache=false` end-to-end;
- first training uses task-scoped labels only;
- no mother-model class inheritance on first training;
- iteration inherits only latest successful artifact-verified trainable version;
- metrics SQLite connections close deterministically.

## 4. Closed frontend ownership

### Training submit

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired mirrors: `trainingLabelSelected`, `trainSplitV3`, `train429Selected`, `train428AlgorithmId`, `train428Config`, `trainingDraftFromLegacyState`.

### Training task polling

```text
classic render call site
→ PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
→ TrainingTaskRuntime.refresh({render:true, source:'poll'})
→ focused /jobs refresh
```

Physically retired:

```text
jobPollTimer
setupPagePolling
installPollingCreationBridge
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
NavigationStability training timer fallback
classic training polling setInterval/clearInterval owner
```

Permanent `Training PollRegistry direct owner guard` now rejects any `setupPagePolling` or `jobPollTimer` reintroduction.

### AutoLabel

```text
renderOps427
→ AutoLabelPollRuntime.activate/deactivate
→ PollRegistry(auto-label-v60)
```

Legacy AutoLabel timers/wrappers/rebind timers are gone.

### Video

```text
renderVideo424 / refreshVideo424Delta
→ explicit replaceVideo424Timer()
→ PollRegistry(video-frames)
```

PollRegistry no longer wraps/adopts video renderer timers.

### Sources

```text
renderSources422
→ renderSourceRows422
→ explicit replaceSourceTimer()
→ PollRegistry(sources, 2500ms)
→ refreshSources422
```

`source422Timer` and all source wrapper/adoption compatibility are retired.

## 5. Permanently retired timer / wrapper compatibility

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

Do not restore compatibility code for these names.

## 6. Permanent CI guards currently active

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

## 7. Renderer / setPage owner-map state

`docs/FRONTEND_OWNER_MAP_V42_25.md` records the current routing chain. Audit baseline before Batch A found:

```text
window.setPage=function...   10 historical assignments
render=function...           22 historical assignments
setupPagePolling             2 shells / 9 search excerpts
```

After Batch A:

```text
setupPagePolling             0 active references
training polling handoff     direct replaceTrainingJobTimer() calls
```

First next deletion candidate is the v42.3 pure pass-through wrapper:

```text
const set423Base=window.setPage;
window.setPage=function(p){set423Base(p)};
try{setPage=window.setPage}catch(e){}
```

Current search shows `set423Base` has exactly one match (declaration + use in the same wrapper). The immediately following v42.4 code resets `window.setPage` directly. `setBase424` itself also currently has exactly one declaration match and no business use. Prove this against the current HEAD before editing; then delete only this bounded family and run navigation regressions.

Do not blindly collapse wrappers that still own page aliases, deployment cache invalidation, mobile sidebar behavior, UI persistence or NavigationStability semantics.

## 8. Work order

```text
1. remove first proven pure-pass-through setPage family
2. continue renderer/setPage obsolete override closure in bounded batches
3. proven dead app.js + global reload/request debt
4. cache-busting unification
5. zero-point MutationObserver/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. resume A800 RC
```

Every batch: verify current HEAD → prove owner → regression → physical deletion → syntax/unit → Real Chrome where behavior changes → update all four handoff docs.

## 9. A800 status

**DEFERRED** until current P0/P1 technical debt is closed.

When resumed:

```text
preflight
→ first short A800 train
→ verify-job
→ iteration + verify
→ worker lifecycle/fencing
→ only then formal release consideration
```

Frontend CI is not CUDA/A800 acceptance.
