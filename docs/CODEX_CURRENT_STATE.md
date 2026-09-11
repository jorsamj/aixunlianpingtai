# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                    refactor/frontend-runtime-stabilization
latest full code acceptance: 774df651c3f278c782029e64bfa3315b12622a9f
Frontend Runtime run:      34616465336
formal VERSION.txt:        42.24.0
frontend badge:            v42.25.0-dev
app.js cache:              42.25.48
main.mjs cache:            42.25.53
NavigationStability:       422506
PollRegistry:              422511
TrainingDraftRuntime:      422516
TrainingLabelRuntime:      422513
TrainingSubmitRuntime:     training-submit-422504
TrainingTaskRuntime:       training-task-runtime-422503
AutoLabelPollRuntime:      422501
```

Run `34616465336` passed syntax, every permanent owner guard including `Training PollRegistry direct owner guard`, all frontend unit tests and all Real Chrome runtime regressions. Branch HEAD may be newer because handoff docs are updated after the accepted code point. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
renderer/setPage final-owner table
→ obsolete override physical deletion
→ remaining frontend/runtime debt
→ zero-point debt scan
→ resume A800 RC
```

Read:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
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
page lifecycle / historical setupPagePolling handoff
→ PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
→ TrainingTaskRuntime.refresh({render:true, source:'poll'})
→ focused /jobs refresh
```

Physically retired:

```text
jobPollTimer
installPollingCreationBridge
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
NavigationStability training timer fallback
classic setupPagePolling setInterval/clearInterval owner
```

`setupPagePolling` 这个历史函数名目前仍有两个一行 handoff 入口，但不再创建 timer。下一批 owner-table 清理中可删除这些空壳，前提是所有调用链先证明由直接 lifecycle owner 覆盖。

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

Training guard enforces zero `jobPollTimer` references in product runtime files and forbids PollRegistry training wrapper/adoption/rebind compatibility from returning.

## 7. Next exact task: renderer / setPage owner map

Polling creation bridges are CLOSED. Do not create another polling runtime.

`static/app.js` still contains a long historical override chain. Current audit has already found multiple `window.setPage=function...` layers and multiple `render=function...` layers, including pure pass-through wrappers and version-era page aliases.

Next execution order:

```text
1. map final visible page → final renderer → final action owner
2. map each setPage wrapper and identify independent semantics
3. mark pure pass-through / superseded layers
4. delete one owner family at a time with regression coverage
5. run syntax + unit + Real Chrome after behavior changes
6. update all three handoff docs after each accepted batch
```

First candidates to prove/delete:

```text
two setupPagePolling one-line handoff shells
pure pass-through setPage wrappers
fully superseded render layers with no live callers
```

Do not blindly collapse all `setPage` generations. Some wrappers still carry page aliases, deployment cache invalidation, mobile sidebar behavior or version-era routing.

## 8. Work order

```text
1. renderer/setPage final-owner table
2. obsolete override physical deletion
3. proven dead app.js + global reload/request debt
4. cache-busting unification
5. zero-point MutationObserver/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. resume A800 RC
```

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
