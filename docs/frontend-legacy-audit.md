# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit:       954e9dba9c891ecd5c7f21144cf00d8664c11620
run:          34670319479
frontend:     PASS
Real Chrome:  PASS (19/19)
```

Current caches/builds:

```text
app.js                    42.25.75
main.mjs                  42.25.80
visible formal version    42.24.0
internal UI build         42.25.0-dev
navigation-stability      422511
ui-state                  422500
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

No classic polling timer or creation-wrapper ownership may return.

### Navigation

`static/app.js` must contain zero classic `window.setPage=` assignments.

```text
NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page)
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistNavigationState
```

## 3. Render/lifecycle retirement completed so far

Physically retired and permanently guarded:

```text
v42.7 render route-state alias mutation
oldRender429
previousRender61
render423Base
renderBase428 算法列表 branch
v42.2/v42.4 legacy 自动标注 route branches
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper/timers
12 historical app.js delayed versionBadge startup writers
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
```

`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function.

## 4. R9 — visible version ownership consolidation

A failing Real Chrome baseline exposed a real asynchronous owner conflict. Final split:

```text
UI_BUILD_VERSION = 42.25.0-dev
  → document.documentElement.dataset.uiBuild only

static/index.html visible initial badge → v42.24.0
top412 / V412                         → visible top v42.24.0
nav426 / V426                         → visible footer v42.24.0
```

Accepted at:

```text
product:    1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
validation: 36fd25c48a2251d1b4a85583921c00dd98bf33fb
run:        34664755130
Real Chrome 15/15 PASS
```

## 5. R10/R11 — file-input lifecycle consolidation

### R10 page owner

The final `测试发布` page still emits ordinary `#predFile`, so `render426base` was proven live before migration. Page semantics moved to:

```text
render chain
→ cleanup(#view)
→ beautifyFileInputs426(root)
```

R10 acceptance:

```text
baseline:   6b67497ae43a32edf343fc7dec49f7b3824c1088
product:    b9d25955c185aaabb4108f3d37cfecd9f876390a
validation: 0dacf581da4acb52312f75eb7e85e6b334e060db
run:        34665470320
Chrome:     16/16 PASS
```

### R11 modal owner

A generic modal baseline locked native-file → platform filepicker behavior before retirement. After R10, `#modalBody` was already observed by the post-render cleanup MutationObserver, and `cleanup(root)` already invoked `beautifyFileInputs426`.

Final modal topology:

```text
modal innerHTML mutation
→ modalBody MutationObserver
→ cleanup(addedNode)
→ beautifyFileInputs426(root)
```

Retired:

```text
modal426
requestAnimationFrame(()=>beautifyFileInputs426(layer||document))
```

R11 acceptance:

```text
baseline:   d2aa614870a52864e991502c2218134943afb14f
product:    8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1
validation: 9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1
run:        34665890699
frontend:   PASS
Chrome:     17/17 PASS
```

All R10/R11 one-shot baseline/migration helpers/workflows were deleted after acceptance.

## 6. R12 — post-render normalization consolidation

`enhancePageV37()` was still live and owned table wrapping plus old “使用建议” panel removal. A permanent Chrome contract first locked modal table wrapping and first-field autofocus. Normalization then moved into the later cleanup owner:

```text
cleanup(root)
→ wrap table.table in .table-wrap when needed
→ remove historical guidance panels
→ existing file-input/placeholder/empty-state cleanup
```

`enhancePageV37` and its RAF callbacks are now absent. `baseRenderV37` remains only for `state.versionInfo` compatibility; `baseModalV37` remains only for modal autofocus.

```text
baseline:   6ae19dc79abbf690371a71162c97a2df6322518b
product:    202a5a82b0cb4629423ee0c6812f649031234daa
validation: 60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29
run:        34666673017
Chrome:     18/18 PASS
```

### R13 — duplicate V37 render version write

`baseRenderV37` was reduced by R12 to a single `state.versionInfo.version=42.24.0` write. A later V42 render owner writes the same formal version before delegating into the old render chain, so R13 removed the duplicate wrapper without moving any UI behavior.

```text
product:    928d2387d46a0472bd202bd4df84af8d1573b6c2
validation: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b
run:        34666985800
Chrome:     18/18 PASS
```

At R13, `baseModalV37` autofocus and the V37 120ms startup timer still remained; both were handled in the next two bounded batches.

### R14 — modal autofocus owner consolidation

The autofocus semantic moved into the base `modal()` function and `baseModalV37` was physically removed.

```text
product:    6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829
validation: 8593516eb796f10fb43cea748bcc42b479e0a02e
run:        34667341153
first pass: 17/18 due to training-task /materials race
rerun:      18/18 PASS
```

A dedicated diagnostic then repeated the focused training performance test 10 times. All 10 passed and each first refresh contained only `GET /jobs`, proving the training refresh owner itself was not issuing `/materials`.

### R15 — startup render timer retirement

Three historical startup compatibility wakeups were removed:

```text
v35  80ms  versionInfo + render
v36 100ms  versionInfo + render
V37 120ms  versionInfo + render
```

Final startup remains owned by `queueMicrotask → final __clInit`. The separate 100ms `renderTop(); cleanup(document)` wakeup was later retired in R18 after final-render normalization ownership was proven.

```text
product:    280a31bf365b1a6646a57213dfa2dff97e10e0b5
focused:    startup readiness PASS; training performance 5/5 PASS
validation: b6edea36296ab9548037457a124b4369776f6f5e
run:        34667776611
frontend:   PASS
Chrome:     18/18 PASS
```

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



## 7. Current live render topology

Confirmed live; do not delete as whole layers without new proof:

```text
oldRender412
  算法列表 / 数据集 stable routing

renderBase428
  训练任务 routing only

renderTraining423
  current training renderer
  directly owns PollRegistry.replaceTrainingJobTimer()

renderBase427
  canonical 自动标注及清洗 route owner

renderBase424
  质量中心 / 视频切帧 route owner only

oldRenderV39
  deployment conversion/artifact/resource/plugin/component routes

render414Base
  标签管理 route

finalRender
  素材存储配置 final route owner + final page normalization dispatch

PostRenderNormalizationRuntime.apply / cleanup(root)
  final-render page normalization
  modal observer normalization target
  table wrapping + page/modal file-input beautification

base modal()
  modal first-editable-field autofocus

completeZipImportReview412
  explicit successful ZIP completion review owner

refreshSummary61
  material summary owner scoped to paged 数据集
```

Still under audit:

```text
modalBody MutationObserver lifecycle
older base/global render generations reached through delegates
```

`baseRender417`, `render426base`, `modal426`, `enhancePageV37`, `baseRenderV37`, `baseModalV37`, and the v35/v36/V37 startup render timers are CLOSED and must not return.

## 8. Permanent contracts

Frontend includes:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/version-marker-owner.test.mjs
tests/frontend/file-input-beautification-owner.test.mjs
tests/frontend/post-render-normalization-owner.test.mjs
tests/frontend/startup-render-owner.test.mjs
tests/frontend/lifecycle-event-ownership.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
```

Current file-input ownership contract requires:

```text
render426base absent
modal426 absent
old page/modal RAF beautification callbacks absent
cleanup(root) invokes window.beautifyFileInputs426?.(root)
#view observer remains retired; modalBody observer remains until explicit modal lifecycle migration
测试发布 #predFile receives native-file426 + filepicker426
ordinary modal file input receives equivalent filepicker behavior
```

Current accepted Real Chrome suite: **19/19** in run `34670319479`.

## 9. Remaining technical-debt targets

```text
modal observer lifecycle audit
loadAll / loadRelated / loadCore412 ownership
proven dead app.js code
global reload / duplicate requests
cache-busting heterogeneity
MutationObserver / setInterval / setTimeout / fetch lifecycle
version-number business naming
final zero-point scan
```

## 10. Audit method

For every candidate:

```text
live HEAD
→ exact assignment/capture/reference topology
→ identify live owner vs shadowed generation/branch
→ lock real semantic behavior
→ migrate semantic ownership if needed
→ double-owner equivalence where semantics move
→ bounded physical deletion
→ permanent guard
→ frontend + Real Chrome
→ delete temporary migration artifacts
→ docs sync
```

Do not delete by version suffix alone. Do not add a global render-repair loop. Prefer semantic/page-scoped owners and explicit lifecycle cleanup.

## 11. Non-negotiable rules

1. No new numbered compatibility generation.
2. Retired training mirrors/fallbacks stay retired.
3. Classic `setPage` ownership remains zero in `app.js`.
4. `state.page==='自动标注'` remains zero in `app.js`.
5. Render must not resume route-state alias mutation.
6. Legacy AutoLabel route/timer owners stay absent.
7. `renderBase428` remains training-only unless semantics move first.
8. `renderBase424` remains quality/video-only unless semantics move first.
9. AutoLabel remains PollRegistry-only.
10. `baseRender417`, `render426base`, `modal426`, `baseModalV37`, legacy startup render timers, and delayed visible-version writers stay retired.
11. Internal build metadata must never become a visible formal-version owner.
12. File-input page/modal behavior must stay covered while cleanup/observer lifecycle is refactored.
13. No mother-model class inheritance on first training.
14. Explicit false/zero training settings survive end-to-end.
15. Trial/test inference never receives GT labels.
16. Do not weaken duplicate-request/race/performance/Real Chrome tests.
17. Frontend CI is not A800/CUDA acceptance.

## 12. Work order

```text
1. modalBody MutationObserver lifecycle audit
2. app.js dead code + global reload/request debt
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```