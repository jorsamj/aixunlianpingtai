# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Cleanup map for the classic frontend before any later framework replacement.  
> Status authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`.

## 1. Runtime shape

```text
static/app.js historical shell
  → static/main.mjs
       ├── NavigationStability
       ├── PageRequestScope
       ├── PollRegistry
       ├── AlgorithmListRuntime
       ├── TrainingTaskRuntime
       ├── MaterialPaginationRuntime61
       ├── TrainingDraftRuntime
       ├── TrainingDraftControlsRuntime
       ├── TrainingSubmitRuntime
       ├── TrainingLabelRuntime
       └── AutoLabelPollRuntime
```

No new numbered override generation is allowed.

## 2. Current versions / latest acceptance

```text
app.js                         42.25.45
main.mjs                       42.25.50
navigation-stability          422504
poll-registry                 422508
training-draft-runtime        422516
TrainingDraftRuntime build    training-draft-runtime-422516
training-labels               422513
TrainingLabelRuntime build    module-422513
AutoLabelPollRuntime          422501 / auto-label-poll-422501
TrainingSubmitRuntime         training-submit-422504
TrainingTaskRuntime           training-task-runtime-422503
```

Latest full acceptance:

```text
commit  4a86f4b497abb024daa9927c7be54e75fcea3692
run     34610390049
syntax                                      PASS
retired-mirror guard                        PASS
network-owner guard                         PASS
TrainingDraft wrapper/owner guard           PASS
TrainingLabel canonical lifecycle guard     PASS
AutoLabel PollRegistry owner guard          PASS
retired legacy poll timer compatibility     PASS
frontend unit                               PASS
Real Chrome                                 PASS
```

The current branch may be ahead of this commit with documentation-only handoff commits. Treat `4a86f4...` as the latest fully exercised code acceptance point until a later code HEAD passes the same full workflow.

## 3. Training ownership audit: CLOSED

Canonical chain:

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /api/v12/projects/{project_id}/train/start
```

Retired training mirror/adapter surface:

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

TrainingDraftRuntime and TrainingLabelRuntime are wrapper-free. TrainingLabel is also timer-free/canonical-only. `.training-label-contract` belongs only to TrainingLabelRuntime; DraftRuntime must not generic-sync those controls.

## 4. AutoLabel polling audit: CLOSED

Final owner:

```text
renderOps427 label tab render complete
→ AutoLabelPollRuntime.activate(annotationTasks60)
→ PollRegistry(auto-label-v60)
→ refreshRows
→ active tasks only re-arm
```

Clean tab explicitly calls `AutoLabelPollRuntime.deactivate()`.

Physically retired:

```text
auto422Timer
ai60ListTimer
AutoLabelPollRuntime renderOps427 wrapper
__autoLabelPollRuntimeWrapped
originalRenderOps / wrappedRenderOps
100/400/1000ms rebind timers
```

The runtime itself contains no timer lifecycle owner; PollRegistry owns the managed one-shot.

## 5. Legacy poll timer compatibility audit: CLOSED

Physically retired from product runtime code:

```text
auto422Timer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
```

Removed compatibility layers:

- PollRegistry no longer adopts/clears those retired timer names;
- NavigationStability fallback no longer clears those retired names;
- v33 `setupPagePolling` wrapper that only created/cleared video/prelabel intervals is gone;
- unit tests no longer model these timers as live compatibility state.

Permanent CI prevents these names from returning to:

```text
static/app.js
static/modules/poll-registry.js
static/modules/navigation-stability.js
```

## 6. Current video polling owner

The current visible video page is the v42.4 path:

```text
renderVideo424
→ loadVideo424
→ render #video424Rows
→ state.video424Timer
→ PollRegistry(video-frames)
```

For refresh:

```text
PollRegistry managed one-shot (2000 ms)
→ refreshVideo424Delta
→ loadVideo424
→ patchVideoRows424 only
→ active task? re-arm : stop
```

Real Chrome proves:

- `video-frames` is managed by PollRegistry;
- rows patch without replacing `#view`;
- navigation away clears the managed key;
- the retired `__videoFramePollTimer` is absent/null.

Do not create a second video polling owner.

## 7. Training task / materials / navigation owners already established

### Algorithm list
Stable visible renderer: `renderAlgorithms423 → renderAlg412`.
Training action: `startAlgorithmTraining429`.

### Training task page
Final owner is the 428-era task-center renderer assigned to `renderTraining423/424/425`; training starts from the algorithm list.

### Training tasks runtime
`TrainingTaskRuntime` owns focused jobs refresh/polling with 120 ms cross-source coalescing and force-fresh mutation refresh.

### Materials
`MaterialPaginationRuntime61` owns paged material loading; training/AI workflows request full pools explicitly.

### Navigation/request lifecycle
`NavigationStability`, `PageRequestScope`, and `PollRegistry` own stabilized navigation/request/poll lifecycle. Do not restore global render-repair loops.

## 8. Remaining PollRegistry bridge debt

PollRegistry still contains compatibility creation bridges:

```text
installPollingCreationBridge()
  → wraps setupPagePolling

installVideo424CreationBridge()
  → wraps renderVideo424
  → wraps refreshVideo424Delta

installSourceCreationBridge()
  → wraps renderSources422

rebindCreation()
```

Current pattern:

```text
legacy function creates timer
→ PollRegistry wrapper runs afterward
→ clears/replaces/adopts legacy timer
```

Target pattern:

```text
page renderer/action
→ explicit lifecycle handoff
→ PollRegistry creates/clears managed timer directly
```

Deletion rule for this batch:

1. prove final renderer/action owner;
2. add or reuse deterministic regression;
3. make the renderer/action call explicit managed lifecycle;
4. remove matching wrapper bridge and restoration path;
5. syntax + focused unit + full frontend + Real Chrome;
6. update all three handoff docs.

Do not delete all three bridges blindly: training, video and source polling have different lifecycle semantics.

## 9. Render/override debt after bridge cleanup

Audit targets remain:

```text
setupPagePolling
render = ...
window.setPage = ...
renderXXX412 / 417 / 423 / 428 / 429
loadAll()
loadRelated()
loadCore412()
MutationObserver
setInterval
setTimeout
window.fetch =
```

Deletion rule remains: prove final owner → regression coverage → physical deletion → syntax/unit → Chrome where relevant.

## 10. Cache-busting debt

```text
styles/bootstrap                  42.24.0-style versions
app.js                            42.25.45
main.mjs                          42.25.50
navigation-stability.js           422504
poll-registry.js                  422508
training-draft-runtime.js         422516
training-labels.js                422513
auto-label-poll-runtime.js        422501
```

Still not unified.

## 11. Current cleanup order

```text
1. retire PollRegistry creation bridges / old setupPagePolling through explicit lifecycle handoff
2. establish renderer/setPage final-owner table
3. remove proven dead app.js / global reload/request debt
4. unify cache-busting
5. zero-point observer/timer/fetch/render/setPage scan
6. semantic naming + deterministic tests + docs sync
7. technical-debt zero-point scan
8. resume A800 RC
```

## 12. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No retired training mirror/adapter may regain ownership.
4. No project-wide label catalog as task label truth source.
5. No mother-model class inheritance on first training.
6. Explicit false/zero training resource values must survive UI → draft → request.
7. Do not weaken duplicate-request/race/browser tests.
8. TrainingDraftRuntime and TrainingLabelRuntime remain wrapper-free.
9. AutoLabel polling remains PollRegistry-only; no legacy timer or renderer wrapper revival.
10. `auto422Timer`, `__videoFramePollTimer`, `__prelabelPollTimer`, `_oldSetupPollV33` remain permanently retired.
11. Frontend acceptance is not A800/CUDA acceptance.
