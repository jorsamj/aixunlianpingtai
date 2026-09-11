# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                    refactor/frontend-runtime-stabilization
latest full code acceptance: b74124b974ee12c3bf113fc7a4a336cb706e81f6
Frontend Runtime run:      34614368651
formal VERSION.txt:        42.24.0
frontend badge:            v42.25.0-dev
app.js cache:              42.25.47
main.mjs cache:            42.25.52
NavigationStability:       422505
PollRegistry:              422510
TrainingDraftRuntime:      422516
TrainingLabelRuntime:      422513
TrainingSubmitRuntime:     training-submit-422504
TrainingTaskRuntime:       training-task-runtime-422503
AutoLabelPollRuntime:      422501
```

Run `34614368651` passed syntax, all permanent owner guards, all frontend unit tests and all Real Chrome runtime regressions. Branch HEAD may be newer due to docs-only commits. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
finish remaining frontend/runtime debt
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

Physically retired:

```text
source422Timer
installSourceCreationBridge
__pollRegistrySourceWrapped
originalRenderSources / wrappedRenderSources
registry.adopt('sources', ...)
NavigationStability source timer fallback
```

Real Chrome verifies source managed polling and navigation cleanup.

## 5. Permanently retired timer compatibility

```text
auto422Timer
ai60ListTimer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
source422Timer
```

Do not restore compatibility code for these names.

## 6. Only remaining PollRegistry creation bridge

One bridge family remains:

```text
installPollingCreationBridge()
→ wraps setupPagePolling
→ legacy setupPagePolling creates state.jobPollTimer
→ PollRegistry replaces it with training-jobs managed interval
```

Target:

```text
classic page lifecycle
→ explicit PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry(training-jobs) owns timer directly
```

Then remove:

```text
state.jobPollTimer compatibility
installPollingCreationBridge
originalSetupPagePolling / wrappedSetupPagePolling
__pollRegistryCreationWrapped
registry.adopt('training-jobs', ...)
legacy setupPagePolling interval creation
```

Be careful: `app.js` contains multiple historical `setupPagePolling` generations and many `render(...); setupPagePolling()` calls. Close the polling owner first; do not combine with broad render deletion.

## 7. Permanent CI guards currently active

```text
Retired training mirror guard
Canonical training network owner guard
TrainingDraft classic wrapper guard
TrainingLabel canonical lifecycle guard
AutoLabel PollRegistry owner guard
Retired legacy poll timer compatibility guard
Video PollRegistry direct owner guard
Source PollRegistry direct owner guard
```

## 8. Work order

```text
1. close setupPagePolling / training-jobs creation bridge
2. build renderer/setPage final-owner table and physically delete obsolete layers
3. remove proven dead app.js and global reload/request debt
4. unify cache-busting
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
