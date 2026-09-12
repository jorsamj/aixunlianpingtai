# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: d18044d3d98231affc7488974e04623dab6d2b10
Frontend Runtime run:        34679069872
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.78
main.mjs cache:              42.25.83
NavigationStability:         422511
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34679069872` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **22 tests and passed 22/22**. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
app.js/global reload/request debt
→ proven dead app.js/runtime shell cleanup
→ cache-busting unification
→ zero-point lifecycle scan
→ semantic naming/dead-code cleanup
→ A800 RC
```

A800 RC remains deferred.

Read in order:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
docs/FRONTEND_OWNER_MAP_V42_25.md
```

## 3. Closed frontend ownership

### Training

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired mirrors: `trainingLabelSelected`, `trainSplitV3`, `train429Selected`, `train428AlgorithmId`, `train428Config`, `trainingDraftFromLegacyState`.

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

Legacy timers/shells/wrappers/adoption compatibility are retired.

### Navigation

All classic `setPage` owners are physically retired. Final owner:

```text
NavigationStability
  normalizeNavigationPage()
  PageRequestScope / epoch
  PollRegistry before/after
  waitForNavigationReady()
  beforeInvokeNavigation()
  performNavigation(page)
  persistNavigationState()
```

`main.mjs` provides exactly one actual page mutation/render owner:

```js
performNavigation: page => {
  state.page = page;
  render();
}
```

Permanent CI forbids classic `window.setPage=` owners in `static/app.js`.

## 4. Render / lifecycle debt already closed

Physically retired and permanently guarded:

```text
v42.7 render route-state alias mutation
oldRender429
previousRender61
render423Base
renderBase428 算法列表 branch
v42.2/v42.4 legacy 自动标注 route branches
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 自动标注 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper/timers
12 historical app.js versionBadge startup timers
main.mjs applyBuildVersion visible-version writer/timers
render426base page-render file-input beautification wrapper
modal426 modal file-input beautification wrapper
enhancePageV37 post-render normalization helper
baseRenderV37 duplicate versionInfo wrapper
baseModalV37 autofocus compatibility wrapper
v35/v36/V37 80/100/120ms startup render/version timers
bounded 100ms renderTop/cleanup startup timer
oldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver
transport.mode-only material summary page guard / off-page summary request leakage
legacy baseRender + RAF page normalization wrapper
#view post-render MutationObserver
#modalBody normalization MutationObserver
```

### R9 — version marker ownership consolidation

A Real Chrome baseline exposed delayed `v42.25.0-dev` overwrite. R9 separated internal build metadata from visible formal version display.

```text
product:    1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
validation: 36fd25c48a2251d1b4a85583921c00dd98bf33fb
run:        34664755130
Chrome:     15/15 PASS
```

### R10 — render426base page wrapper retirement

`render426base` was live: `测试发布 #predFile` depended on post-render `beautifyFileInputs426()`. Behavior was locked first, then page ownership moved to `cleanup(root)`.

```text
behavior baseline: 6b67497ae43a32edf343fc7dec49f7b3824c1088
product:           b9d25955c185aaabb4108f3d37cfecd9f876390a
validation:        0dacf581da4acb52312f75eb7e85e6b334e060db
run:               34665470320
Real Chrome:       16/16 PASS
```

### R11 — modal426 retirement

A generic modal behavior contract proved the old wrapper's file-input semantics before migration. After R10, the existing `#modalBody` MutationObserver already routes inserted modal nodes through `cleanup(root)`, and `cleanup(root)` owns `beautifyFileInputs426`.

Final topology:

```text
modal body mutation
→ modalBody MutationObserver
→ cleanup(addedNode)
→ beautifyFileInputs426(root)
```

Retired:

```text
const modal426=modal
requestAnimationFrame(()=>beautifyFileInputs426(layer||document))
```

R11 acceptance:

```text
behavior baseline: d2aa614870a52864e991502c2218134943afb14f
product:           8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1
validation:        9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1
run:               34665890699
frontend:          PASS
Real Chrome:       17/17 PASS
```

Permanent proof remains in:

```text
tests/frontend/file-input-beautification-owner.test.mjs
tests/browser/navigation-stability.spec.mjs
```

All R10/R11 one-shot baseline/migration helpers and workflows were deleted after acceptance.

### R12 — enhancePageV37 normalization helper retirement

Audit proved `enhancePageV37()` still owned table wrapping and “使用建议” cleanup, while `baseModalV37` also used it before autofocus. R12 locked modal table wrapping + autofocus in Real Chrome, then moved normalization into the later `cleanup(root)` owner.

```text
before:
  baseRenderV37/baseModalV37
  → requestAnimationFrame(enhancePageV37)
  → table wrapping / 使用建议 cleanup

after:
  cleanup(root)
  → table.table → .table-wrap
  → panel/history cleanup

baseRenderV37 → state.versionInfo write only
baseModalV37  → first editable field autofocus only
```

R12 acceptance:

```text
behavior baseline: 6ae19dc79abbf690371a71162c97a2df6322518b
product:           202a5a82b0cb4629423ee0c6812f649031234daa
validation:        60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29
run:               34666673017
frontend:          PASS
Real Chrome:       18/18 PASS
```

Permanent proof: `tests/frontend/post-render-normalization-owner.test.mjs` plus the browser contract `modal table wrapping and first-field focus survive normalization ownership`.

### R13 — baseRenderV37 retirement

R13 proved the remaining V37 render wrapper was only a duplicate formal-version write:

```text
baseRenderV37
→ state.versionInfo.version = 42.24.0
→ delegate

later V42 render owner
→ state.versionInfo.version = 42.24.0
→ oldRender42()
```

Because the later V42 owner writes the same value before delegating into the old chain, `baseRenderV37` was physically removed. `baseModalV37` was intentionally untouched. The V37 120ms startup timer also remains and is a separate lifecycle target.

```text
product:    928d2387d46a0472bd202bd4df84af8d1573b6c2
validation: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b
run:        34666985800
frontend:   PASS
Chrome:     18/18 PASS
```

### R14 — baseModalV37 retirement

R14 moved the only live V37 modal semantic — first editable-field autofocus — into the base `modal()` owner, then physically removed the `baseModalV37` compatibility wrapper. The focused modal contracts passed. The first full suite exposed an unrelated low-probability `/materials` request race in `training-task-performance` (17/18); rerunning the same run passed 18/18, so the failure was retained as lifecycle evidence rather than dismissed.

```text
product:             6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829
validation:          8593516eb796f10fb43cea748bcc42b479e0a02e
initial full run:    34667341153 → 17/18, then rerun 18/18
diagnostic repeat:   training performance 10/10 PASS; only GET /jobs observed
```

### R15 — legacy startup render timer retirement

The race audit identified three historical startup compatibility timers as unowned render wakeups: v35 80ms, v36 100ms and V37 120ms. They were physically removed. Final startup dispatch remains `queueMicrotask → final __clInit`. The separate bounded 100ms cleanup timer was later retired in R18 after final-render normalization ownership was proven.

```text
product:             280a31bf365b1a6646a57213dfa2dff97e10e0b5
focused acceptance:  startup readiness PASS + training performance 5/5 PASS
validation:          b6edea36296ab9548037457a124b4369776f6f5e
run:                 34667776611
frontend:            PASS
Real Chrome:         18/18 PASS
```

Permanent proof includes `tests/frontend/startup-render-owner.test.mjs` and the existing modal normalization/autofocus Chrome contract.

### R16 — event-owned ZIP completion + page-scoped material summary

R16 converted two asynchronous lifecycle guesses into explicit/scoped owners. The former body-wide ZIP review `MutationObserver` could fire after `pollImport411()` exposed `stage=导入完成` but before the final completion `resultHtml` write, so its persisted review action could be overwritten even though the DOM button and auto-open had already appeared. ZIP review is now invoked explicitly after the final successful completion state is written.

The second failure source was `refreshSummary61()`: its 250/1200ms startup timers only checked stale `transport.mode==='paged'`. Because final navigation no longer uses the early material-aware `setPage` wrapper, those timers could issue `/materials` after navigation to 训练任务. `refreshSummary61()` is now strictly gated by the live paged 数据集 page both before and after its requests.

```text
baseline:        540de6aef4ddbf82a6cf36994a31a73937abca73
baseline run:    34668429941 → 17/19
                 ZIP persisted review false
                 training-task unexpected /materials request
product:         12df27e2af9155e3a1b9f745e46605396e321815
focused run:     34668639496
                 ZIP completion PASS
                 training refresh isolation 5/5 PASS
validation:      540c0944f45030ea198af2be153c1505f71e62f0
full run:        34668702371
frontend:        PASS
Real Chrome:     19/19 PASS
```

Permanent proof: `tests/frontend/lifecycle-event-ownership.test.mjs` plus the browser contract `ZIP import completion surfaces review action and auto-opens review`.

### R17 — final page normalization ownership

R17 removed the remaining page-side triple ownership (`baseRender` wrapper + page RAF cleanup + `#view` MutationObserver). Source-order proof showed the storage wrapper is the final `render` assignment in `static/app.js`, so page normalization now runs exactly once after the final render path through the named `PostRenderNormalizationRuntime`. Modal normalization remains independently owned by the `#modalBody` observer and was intentionally not changed in this batch.

```text
product:         4fc5d90a15ef2fc2dc22aa00f39967deba6f53f8
validation:      c3301d065fa820539873a4fa2f739992ef63f3d2
guard alignment: f5b8ff8789de0f51d2a03bcabe126191005ba24c
full run:        34669152742
frontend:        PASS (179/179)
Real Chrome:     19/19 PASS
```

The first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.

### R18 — bounded startup cleanup timer retirement

R18 retired the remaining readiness-bypassing `setTimeout(()=>{renderTop();cleanup(document);},100)` wakeup. Final startup already waits for the v53 snapshot/current-page refresh and then calls the final `render()`, while R17 made that final render the sole page-normalization dispatch. The modal observer was deliberately left untouched because post-open base-modal body mutations still depend on normalization.

```text
product:    1572fdf4fad6e0fe8d10b5253a236722e85b3495
validation: 954e9dba9c891ecd5c7f21144cf00d8664c11620
run:        34670319479
frontend:   PASS
Real Chrome: 19/19 PASS
```


### R19 — explicit modal content ownership

R19 retired the last active DOM normalization observer. A permanent Real Chrome baseline first locked a real post-open base-modal refresh path (后台导入任务 → 刷新). Modal content writes now go through `ModalContentRuntime.replace(root, html)`. When `root.id === 'modalBody'`, that owner synchronously invokes `PostRenderNormalizationRuntime.apply(root)`; preview/review rewrites also route through the same content replacement owner. `static/app.js` now contains zero active `MutationObserver` constructions.

```text
baseline:   6f5fac4313d23083c6bbe9e2a3b8a5284cd49583
product:    1bb210fbb10a7bee9f5b875d0dd6016187c1ef72
validation: f60d00096a0929a63d0370494ef1f1d489f54ca3
run:        34670989473
frontend:   PASS
Real Chrome: 20/20 PASS
```


### R20a — algorithm version deletion scoped refresh

R20 started the global `reload() → loadAll() → loadRelated()` request-debt migration with one proven-live mutation path. The algorithm version delete modal behavior was locked first. The final `delVersion` owner now performs the DELETE and delegates refresh to `AlgorithmListRuntime.refresh({render:true})`, which owns only algorithms + jobs. The browser contract permanently forbids the datasets/images/labels/training-environment/bootstrap request fan-out on this path while allowing unrelated background owners such as the import-job poll to run independently.

```text
baseline:   55f21733121d1280be66548ef4bb13c1c3810737
product:    22c552d27928375dd51081eb152dc25b1554ec18
validation: 103d630b24bd1aad77190149291c4c9f25e8ab75
run:        34677761599
frontend:   PASS
Real Chrome: 21/21 PASS
app.js:     42.25.77
main.mjs:   42.25.82
```

This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

### R20b — model publish authoritative state update

The final live `saveAssign` owner was proven reachable from 测试发布. Its POST already returns the authoritative created `version`, so R20b removes the redundant global reload after publish. On success the owner prepends the returned version to the selected algorithm, removes the published model from `state.pending`, clears `state.assigningModel`, closes the modal and renders locally. The publish action itself now owns exactly one POST and zero follow-up GETs.

```text
initial baseline:   b41340d4ee292f7e8e268f4bd59206efe072d690 / run 34678815343 → 21/22
                    failure was a test-DOM mismatch: model name is an input value, not modal text
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / focused run 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
focused migration:  34679011468 PASS
validation:         d18044d3d98231affc7488974e04623dab6d2b10
run:                34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
app.js:             42.25.78
main.mjs:            42.25.83
```

R20/global reload debt remains **IN PROGRESS**; R20b closes only the live model-version publish path.

## 5. Current live render owners — do not delete without proof

```text
oldRender412
  算法列表 / 数据集 stable routing

renderBase428
  training-only route to renderTraining423

renderTraining423
  current training renderer
  directly activates PollRegistry training-jobs

renderBase427
  canonical 自动标注及清洗 route owner

renderBase424
  质量中心 / 视频切帧 route owner only

oldRenderV39
  deployment conversion/artifact/resource/plugin/component routes

render414Base
  标签管理 route; remains live

finalRender
  素材存储配置 final route owner
  final page normalization dispatch

PostRenderNormalizationRuntime.apply / cleanup(root)
  final-render page normalization
  table wrapping + file-input beautification

ModalContentRuntime.replace(root, html)
  explicit modal/preview/review content replacement
  applies PostRenderNormalizationRuntime synchronously for #modalBody

base modal()
  first editable modal field autofocus

completeZipImportReview412
  explicit successful ZIP completion review owner

refreshSummary61
  material summary owner; live only on paged 数据集
```

Still requiring independent liveness analysis:

```text
older base/global render generations still reachable through delegates
global reload / loadAll / loadRelated request ownership
```

`baseRender417`, `render426base`, `modal426`, `baseModalV37`, and the v35/v36/V37 startup render timers are permanently retired.

## 6. Permanent frontend/browser contracts

Frontend includes:

```text
render-alias-restore.test.mjs
render-owner-retirement.test.mjs
version-marker-owner.test.mjs
file-input-beautification-owner.test.mjs
post-render-normalization-owner.test.mjs
startup-render-owner.test.mjs
lifecycle-event-ownership.test.mjs
modal-content-owner.test.mjs
algorithm-version-refresh-owner.test.mjs
algorithm-version-publish-owner.test.mjs
navigation-stability.test.mjs
navigation-persistence.test.mjs
retired-sidebar-setpage-guard.test.mjs
retired-pre-v424-setpage-guard.test.mjs
auto-label-poll-runtime.test.mjs
```

`file-input-beautification-owner.test.mjs` now permanently requires:
- `render426base` absent;
- `modal426` absent;
- old page/modal RAF beautification callbacks absent;
- `cleanup(root)` calls `beautifyFileInputs426`;
- `#view` observer remains retired; page normalization must stay final-render-owned;
- `#modalBody` normalization observer is retired and must not return; modal content replacement must stay `ModalContentRuntime`-owned.

Real Chrome verifies navigation, readiness, stale-request fencing, managed polling, sidebar cleanup, current/historical auto-label canonicalization, persistence/reload, storage route, algorithm/training/material performance, formal-version stability, and page/modal file-input beautification. Current accepted suite: **22/22**; this includes `base modal post-open content refresh stays functional`, `algorithm version deletion uses focused refresh without full reload`, and the model-version publish authoritative-state/request-boundary contract.

Do not weaken these tests.

## 7. Required deletion sequence

For every remaining candidate:

```text
live HEAD
→ exact assignment/capture/source-order proof
→ page/modal coverage and liveness proof
→ browser/unit behavior contract where needed
→ semantic migration if live
→ double-owner equivalence if semantics move
→ physical deletion only when shadowed/dead or semantics have moved
→ permanent guard
→ full frontend + Real Chrome
→ delete one-shot migration helper/workflow
→ docs sync
```

## 8. Non-regression backend contracts

- snapshot schema v3 and duplicate/leakage protection;
- `confirmed_empty` negative-sample semantics;
- task-runtime lease/generation/process fencing;
- explicit `batch`, `workers`, `cache=false` end-to-end;
- first training uses task-scoped labels only;
- no mother-model class inheritance on first training;
- iteration inherits only latest successful artifact-verified trainable version;
- metrics SQLite connections close deterministically;
- trial/test images sent to model without GT leakage.

## 9. Work order

```text
1. continue R20 global reload / loadAll / loadRelated mutation-domain migration
2. proven dead app.js/runtime-shell cleanup
3. cache-busting unification
4. zero-point MutationObserver/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + dead-code cleanup
6. technical-debt zero-point scan
7. resume A800 RC
```

## 10. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.