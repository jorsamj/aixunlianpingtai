# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit:       cb81ca39016aea0fc53ed52090f0b0199d39109a
run:          34789704610
frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                  42.25.95
main.mjs                  42.25.92
visible formal version    42.24.0
internal UI build         42.25.0-dev
navigation-stability      422512
ui-state                  422500
poll-registry             422511
training-draft-runtime    422516
training-labels           422513
training-task-runtime     training-task-runtime-422503 (cache 422505)
auto-label-poll-runtime   422501
```

## Product closure — Video resource queue truth CLOSED

The live v424 video task page already reads `/api/v33/projects/{project_id}/video-tasks`, whose public projection is backed by the shared durable `TaskRepository`. `task_to_public()` dynamically exposes resource-scoped `resource_queue_position` / `resource_wait_reason`; a durable queued task in the `resource_waiting` phase is publicly projected as `WAITING_RESOURCE`. The frontend previously dropped that queue metadata and also failed to classify `WAITING_RESOURCE` as an active video task, so a genuinely resource-waiting task could lose timely managed polling and never show its real queue position/reason.

Closed semantics:

```text
QUEUED: remains active under PollRegistry and shows real resource_queue_position when available
WAITING_RESOURCE: remains active, shows “等待资源”, real queue position and resource wait reason
initial render + delta polling: both use the same v424 row projection and preserve runtimeText
progress: continues to come from durable server/worker truth; no frontend progress simulation
queue ordering / claim / queue_rank / resource fencing: unchanged
cancel / stale-worker / publish fencing: unchanged
```

The fix is intentionally narrow. `static/modules/video-tasks.js` now projects the existing durable queue metadata into `runtimeText` and treats public `WAITING_RESOURCE` as active; the final v424 `videoTaskRow424()` renders that view-model text. `PollRegistry` remains the sole video polling lifecycle owner. Permanent behavior guard: `tests/frontend/video-tasks.test.mjs`, which executes the real final row renderer and verifies both queued and waiting-resource behavior.

Evidence:

```text
final permanent RED commit: 32284a8972faec46775144b8c47406e67edee014
valid RED run:              34789541200 (242 total; 239 PASS; only 3 intended video truth assertions RED)
focused/full GREEN run:     34789628840 PASS
product/self-cleanup:       c0fee2b7c8dfbf03481cbc6dfb1019f922293576
formal clean HEAD:          cb81ca39016aea0fc53ed52090f0b0199d39109a
Release Regression:         34789701814 PASS
Navigation Action Fencing:  34789703315 PASS (Real Chrome PASS)
Frontend Runtime:           34789704610 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP processing acceptance was performed. One-shot product/gate migration assets were physically deleted before formal gate acceptance.

## Product closure — AI annotation polling queue metadata truth CLOSED

The durable v60 AI annotation backend/public projection already exposes real `resource_queue_position` and `resource_wait_reason`, and `annotationTaskView()` already turns that truth into `runtimeText`. Initial page rendering consumed `runtimeText`, but `AutoLabelPollRuntime` used a separate row renderer during polling refresh and omitted it. Result: a task could initially show `资源队列第 N 位` / resource wait reason and then lose that truthful metadata after the first managed poll refresh even though durable truth had not changed.

Closed semantics:

```text
initial render: durable status + progress + runtimeText
managed polling refresh: the same durable status + progress + runtimeText
QUEUED / WAITING_RESOURCE: resource queue position remains visible after every refresh
resource wait reason: remains visible when projected by annotationTaskView
no frontend queue simulation, no claim/order/resource-fencing changes
```

The fix is intentionally narrow: `static/modules/auto-label-poll-runtime.js` now renders existing `view.runtimeText` beside the status pill. No backend queue ordering, task claim, execution fencing, polling cadence, or progress semantics changed. Permanent behavior guard lives in `tests/frontend/auto-label-poll-runtime.test.mjs`; Release Regression path scope now includes both the polling runtime and its guard.

Evidence:

```text
valid RED commit:          186005b428f361e88553555b3a86013d206f11b3
valid RED run:             34788748122 (239 existing tests PASS; 1 intended queue-metadata assertion RED)
product commit:            ddb1168a8f3457fef3d875ceec79e618b75acee9
accepted clean code point: 2bc6f72fddd878a7e2d4802c5affd3d640f807e7
Release Regression:        34788824842 PASS
Navigation Action Fencing: 34788824910 PASS (Real Chrome PASS)
Frontend Runtime:          34788824849 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## Product closure — Plain image upload whole-task progress truth CLOSED

The final live ordinary-image upload owner is the storage61 `doUploadImages426` path posting to `/api/projects/{project_id}/images`. The endpoint is synchronous HTTP, but after browser request bytes are sent the server still performs temporary-file handling, image validation, selected-storage object write, SHA256 calculation and material record commit. Therefore browser `xhr.upload` byte completion is not whole-task completion.

Closed semantics:

```text
browser byte transfer: 0% -> 85%
byte transfer complete: hold at 85%, show “文件已上传，正在服务器入库”
server-side synchronous commit: no fabricated percentage animation
successful HTTP completion after material commit: 100%, show “服务器入库完成”
network/non-2xx failure: never claims terminal 100%
```

This batch deliberately does **not** invent a durable background task, fake queue, or fake server progress for a synchronous endpoint. Terminal 100% is fenced to the authoritative successful HTTP completion. Permanent behavior guard: `tests/frontend/image-upload-overall-progress.test.mjs`; Release Regression includes that test in its permanent path scope.

Evidence:

```text
valid RED commit:          03be0050644af80709bddb97321f1a4ec0b1528c
valid RED run:             34788264443 (237 existing tests PASS; 2 intended new assertions RED)
focused migration/GREEN:   34788320142 PASS
product commit:            259d76d753993f2dd10e1963ee1a9a13887209ad
accepted clean code point: bae90eae4b3768d365d20344c1f2db9a75795ac8
Release Regression:        34788383779 PASS
Navigation Action Fencing: 34788383742 PASS (Real Chrome PASS)
Frontend Runtime:          34788383772 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

The one-shot product migration workflow was removed in the product commit. No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## Product mainline checkpoint — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.
- **ZIP 10k acceptance**: focused CI created a real ZIP with **10,000 image members** and passed the v19 create/scalability contract plus existing server-import/storage regressions. The permanent legacy unit guard was migrated, not weakened (`27654cba1fb3406567a40754904531c2b53aa53f`), and the permanent Chrome material/import contract was migrated to the real v19 sequence (`60305921402204e77b8e7ed4ec8e576d9f857c4b`): create → start → list polling → terminal done → labels/current paged-material scoped refresh, with an explicit assertion that no `/api/v18/` request or broad reload occurs. Final Frontend Runtime `34733035739` passed all frontend unit guards and Real Chrome **33/33 PASS (53.9s)**; Action Fencing `34733035761` PASS.
- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.95`; `main.mjs` cache remains `42.25.92`. No merge/tag/release.

**Video resource queue truth is CLOSED. Current next product scope: continue the horizontal real queue-position/progress audit across cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**

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

R1 action fencing adds `NavigationStability.action(ownerPage) → token/isCurrent/commit` for mutation-completion ownership. R2 extends the same commit fence to the true final `saveVisionModelM4`, `testModelConfigV35`, `confirmClean429`, and v60 `completeAiReview60` owners. Clean confirmation now uses authoritative `deleted_ids + processed_ids` local patching instead of broad `loadRelated()`, and v60 AI review keeps the durable `taskApi(review.id)/decisions` + `commit:true` contract. R2 product `9f6df85b994f23b5408759fb64485b9477c75936`, cleanup/permanentization `3a8781dccf6704fe76d35d99c05b80590dc507c3`, full run `34721755310` **32/32**, permanent Action Fencing run `34721755316` PASS. R1 and R2 are closed; global stale-async zero-point is still not closed because upload/ZIP/deployment/timer-callback completion families remain for the final scan.

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
#modalBody normalization MutationObserver
base algorithm CRUD new/save/edit/saveEdit/view globals
v30 oldRenderAlgorithms wrapper
v39 oldViewAlgoV39 wrapper
v42.2 renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422 generation
shadowed v423 openNewAlgorithm423(async)/saveNewAlgorithm423/editAlgorithm423(old modal)/saveEditAlgorithm423 generation
legacy dataset-group select/new/save/edit/delete CRUD generation
oldSelectDataset persistence wrapper
currentDataset helper
two shadowed historical dataset-group render bodies
zero-reference uploadImages / autoSplit / buildYolo / checkDatasetQuality / setImageSplit owners
shadowed v35/v426/v427 Model Config modal/save generations
```

`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function.

R20k did **not** retire the live `doImportData` owner. It migrated only its successful completion refresh from broad `reload()` to labels + current paged materials. Acceptance: product `1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb`, validation `60775456f3d4c8a441ba58ce65106af114aeebb2` / run `34700127243`, cleanup `f51d44c089b6342398c14bd38c8669747adad48b` / run `34700252041`, Real Chrome **32/32**. Permanent contracts: `tests/frontend/v18-import-completion-scope.test.mjs` and `tests/browser/material-pagination-performance.spec.mjs`.

R20m physically retired the shadowed early v423 algorithm create/edit generation after source-order proof and a pre-retirement Real Chrome pass showed final CRUD already resolves to the later stable 414 owners. Baseline `243bcb1b17074848d91c2c9c64d47dbed54e5e9b`, migration run `34724242632`, product `71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e`, cleanup/final acceptance `40a87bf70402dccfc0387950b6856a561ce1ebe1` / run `34724354775`, Real Chrome **33/33**, Action Fencing `34724354790` PASS. `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs` permanently locks owner cardinality/absence; existing `algorithm-list-performance.spec.mjs` locks live CRUD behavior. Global R20 zero-point remains open.

R20l kept the live `refreshSourceImportTasksV36` owner but removed its terminal broad refresh. Real Chrome baseline proved the old terminal `loadRelated()` fan-out; completion now calls only `refreshLabels414(false)` plus `reloadMaterialPage61()` when still on 数据集. Active source-import polling cadence remains unchanged. Product `f260127d2d41281bc1d996a172e7d4290536f24c`, migration run `34723694735`, permanentization `b17bd0c33bfb99e5557fc245a89a6c4444a8257e`, cleanup/final acceptance `f8356bcf5ec1ea128fb38db2820df38146b48cfd` / run `34723808299`, Real Chrome **33/33**, Action Fencing `34723808298` PASS. Permanent contracts: `tests/frontend/source-import-completion-scope.test.mjs` and `tests/browser/source-import-completion-scope.spec.mjs`; one-shot migration artifacts are deleted. Global R20 zero-point remains open.

R20n retired the three shadowed Model Config modal/save generations (`saveModelConfigV35`, `saveModelConfig426`, `saveModelConfig427`) after source-order proof plus the same M4 Real Chrome contract passed before and after deletion. Final M4 `saveVisionModelM4` and `testModelConfigV35` remain authoritative and action-fenced. Product `9acaa534e596464a1ebe129e435916ed7dd9cdf2`, cleanup `fce8034a861e1f9c5c0d37568891717309845794`, final accepted HEAD `b83b2bf360b891265157e602f622d409d1d2332f` / Frontend Runtime `34725907423`, Real Chrome **33/33**, Action Fencing `34725907404` PASS; app cache `42.25.93`. One-shot migration artifacts are deleted. **Further non-blocking legacy cleanup is PAUSED by user request; remaining debt stays OPEN/DEFERRED unless it blocks real use, performance, data integrity or release acceptance.**

Cross-cutting checkpoint after R20k: Resource Discovery SQLite code-level lifecycle was accepted at product `8ba4e10db5958204aca3d87779711d8e95f5d83b`. Baseline run `34700801232` proved the two target failures before migration; permanent cross-platform workflow run `34700900542` passed Ubuntu + Windows; artifact cleanup `c6ac70b670a6297ccba065854779c10b8ca47cf3` passed Frontend Runtime `34700984963` with Real Chrome **32/32**. Production soak and non-SQLite resource classes remain outside this frontend audit and OPEN.

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

### R20b — model-version publish local state ownership

The final live 测试发布 `saveAssign` owner previously performed a successful version POST and then invoked global `reload()`. The backend already returns the authoritative created `version`, so the owner now patches `state.algorithms`, removes the matching pending model, clears transient assignment state and renders locally. The permanent browser request contract requires exactly one publish POST and forbids bootstrap/algorithms/pending/jobs/models/training-resource reload fan-out from this action.

```text
initial baseline:   b41340d4ee292f7e8e268f4bd59206efe072d690 / 34678815343 → 21/22
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
validation:         d18044d3d98231affc7488974e04623dab6d2b10 / 34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
```

The initial baseline failure was only an incorrect test assertion against modal text; the model name is rendered as a disabled input value. No product fix was hidden by that correction.

### R20c — training-server refresh ownership

`saveServer` is a proven-live final owner from the training-resource server connection flow. Its former `await reload()` reached the final `refreshCurrentPage413` binding, so a server POST caused a bootstrap snapshot plus 训练资源 extras. Because canonical training targets come from `/api/training_options`, R20c narrows the mutation to exactly the required refresh domain: POST `/api/train_servers`, GET `/api/training_options?project_id=...`, replace `state.targets`, local render. No bootstrap snapshot belongs to this mutation.

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14 / 34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
```

### R20d — Paddle resource refresh ownership

The final late resource-runtime overrides of `detectPaddle` and `quickPaddleDetect` were proven live. Both previously ended in `loadAll()`, whose final binding includes a bootstrap snapshot. The new named helper `refreshPaddleTrainingTargets20d()` fetches only `/api/training_options?project_id=...` and replaces `state.targets`; manual and quick Paddle activation both delegate to it after their required POST sequence.

```text
baseline:                53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration run:     34681841986 stopped before commit because the generated unit file had invalid JS newline escaping
helper fix:              e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:                 d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:       34681905173 PASS
validation:              a21846c33d79612f9ab4a47e2a69195da29caa3b / 34681966242
frontend:                PASS
Real Chrome:             24/24 PASS
```

No product was committed by the failed first migration run. Permanent proof now locks select/test/detect payload semantics, canonical target refresh, and bootstrap=0.

### R20g — scoped import completion ownership

The final live ZIP completion path and server-storage confirmation path now avoid broad `loadRelated()` / `loadAll()` fan-out. Permanent owner tests require label refresh only when needed and paged material refresh only for the active 数据集 page. One-shot migration artifacts were physically removed after acceptance.

```text
product:          a67778fd9b60384dbfffa2156e99670d244dadc9
validation:       a2f4cb40abb6d70ad4faf89bde60c1ee39e4a179
validation run:   34693503185
Real Chrome:      30/30 PASS
artifact cleanup: 6337f1a0379c7e60fbbc459668090504c0b6095b
cleanup run:      34695825386
cleanup Chrome:   30/30 PASS
```

### R20h — algorithm CRUD / shadowed generation retirement

R20h removed the broad-reload algorithm CRUD generation and three later shadowed algorithm compatibility layers after proving final routing ownership. Current create/edit/delete mutations use stable 414/423 owners and patch authoritative `state.algorithms` locally.

```text
product:        d58e690ffcc1523f213a65cfc0a57380ffdc571e
focused run:    34696508446
validation:     210a9ad1f6271a8a8986db3f223f4813a6cce288
validation run: 34696729028
frontend:       PASS
Real Chrome:    31/31 PASS
```

Permanent proof:

```text
tests/frontend/legacy-algorithm-crud-owner.test.mjs
tests/browser/algorithm-list-performance.spec.mjs
```

Intentional survivors are explicit: base `renderAlgorithms()` is now only a bounded delegate to `renderAlgorithms423` because older global render maps still evaluate the symbol; the later `window.showReport` compatibility owner remains live because `viewAlgorithm423/versionRows423` still references it. One-shot R20h migration artifacts are physically deleted.

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
  table wrapping + page/modal file-input beautification

ModalContentRuntime.replace(root, html)
  explicit base-modal and modal-like content replacement
  applies normalization synchronously for #modalBody

base modal()
  modal first-editable-field autofocus

completeZipImportReview412
  explicit successful ZIP completion review owner

refreshSummary61
  material summary owner scoped to paged 数据集
```

Still under audit:

```text
older base/global render generations reached through delegates
global reload / loadAll / loadRelated request ownership
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
tests/frontend/modal-content-owner.test.mjs
tests/frontend/algorithm-version-refresh-owner.test.mjs
tests/frontend/algorithm-version-publish-owner.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/frontend/paddle-resource-refresh-owner.test.mjs
tests/frontend/model-config-save-refresh-owner.test.mjs
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
#view observer remains retired; #modalBody normalization observer is retired; ModalContentRuntime owns modal content replacement
测试发布 #predFile receives native-file426 + filepicker426
ordinary modal file input receives equivalent filepicker behavior
```

Current accepted Real Chrome suite: **28/28** in run `34690924552`.

## 9. Remaining technical-debt targets

```text
loadAll / loadRelated / loadCore412 ownership
global reload / duplicate requests
proven dead app.js/runtime shell
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
1. continue R20 global reload/request mutation-domain migration
2. app.js dead code/runtime-shell cleanup
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```

### R20e — live model-config / prompt mutation refresh retirement

The next source-order audit found three genuinely live mutation owners in the final 模型配置 surface. The old prompt save/delete path was not merely expensive: because model-page extras reload model configs but not prompt templates, its global refresh left prompt UI stale.

```text
baseline:             afa2bfcb474cc9970129723af5589ab74a26eca7 / 34683803977 → 1/3 PASS
first migration run:  34683969019 → unit 3/4, over-escaped wiring assertion only; no product commit
guard fix:            becabf102d10520db52fdac9af1d5238357aa3f3
focused:              34684037005 → unit 4/4 + Chrome 3/3 PASS
product:              febece523b462692cc857431cb901fc5a863d091
validation:           89327ded9da924753f5f900fc3b79e6df353927f / 34684119911
frontend:             PASS
Real Chrome:          27/27 PASS
```

Live mutation topology is now local/authoritative: model-config delete filters `state.modelConfigs`; prompt save upserts the POST/PUT result into `state.promptTemplates`; prompt delete filters that collection. None of these actions may issue bootstrap/model-config/prompt-template follow-up GETs.

The full run also emitted one non-fatal resource-discovery SQLite `database is locked` during cache initialization. Keep that as a separate concurrency audit target.


### R20f — final M4 model-config save ownership

The first R20f source-only audit selected `saveModelConfig427`, but runtime evidence showed that the visible modal is restored to the earlier M4 implementation by a capture/final-activation chain:

```text
M4 openModelConfigModalV35
→ window.__m4OpenModelConfig capture
→ later 427 compatibility overwrite
→ file-tail M4 final activation
→ openModelConfigModalV35 = __m4OpenModelConfig
→ saveVisionModelM4
```

The old live M4 save owner POSTed/PUT the model configuration and then called `loadRelated()`. The accepted owner now upserts the authoritative saved item directly into `state.modelConfigs` and renders locally; no bootstrap/project/dataset/material/label/algorithm/model-config GET fan-out belongs to the mutation.

```text
baseline:            dddcd3f1eecf27c5b7447a16939e53473ff1d745
readiness alignment: da3f3cee7565b75f0a2de926dfdbdb42f7b30ab9
diagnostic run:      34690682894
product:             c9b7ab44192d38c37753643ee790fc2e089c8598
validation:          94dbebb43d83b1d522ea4e3f6522154417f3e985 / 34690924552
frontend:            PASS
Real Chrome:         28/28 PASS
```

Audit rule added by R20f: **textual last assignment is insufficient when a runtime capture/restore or final-activation layer exists**. Inspect capture aliases and end-of-file restorations before classifying a function as final/live. R20 remains **IN PROGRESS** for the remaining global-refresh zero-point audit.

## R20i — legacy dataset-group owner retirement

Source-order audit proved the late final route executes `renderDatasets424()` directly. Two older dataset-group page bodies and their CRUD/persistence helpers were therefore physically unreachable. R20i removed them while retaining one bounded `renderDatasets() → renderDatasets424()` delegate for historical render-map symbol compatibility.

```text
product:          feeb98f441bb1fe5d0f8f409a1509c66606e59ef
validation:       11131ca30c17809e016807aa6c75b0bf203fa6f8
validation run:   34698850495
cleanup:          a7116811adb26ebe5f0f9e621bf23df1dd1f605f
cleanup run:      34698983278
frontend:         PASS
Real Chrome:      31/31 PASS
app.js cache:                42.25.95
```

Permanent proof: `tests/frontend/legacy-dataset-group-owner.test.mjs`. Next audit target is the remaining legacy dataset action block; do not conflate it with live `renderDatasets424` / MaterialPagination behavior.

## R20j — zero-reference legacy dataset actions

The current-source liveness audit found exactly one assignment and no caller for each of `uploadImages`, `autoSplit`, `buildYolo`, `checkDatasetQuality` and `setImageSplit`. They were physically removed and permanently guarded. The audit deliberately excluded `doImportData`: final v36 `importData()` still calls that unique v18 XHR owner.

```text
product:            e6398f7d8ae665079c82d64217c434af4a73073c
focused run:        34699354229
validation:         693a2fa2c3d39378782ac2270a95924eff5ca5ec
validation run:     34699442423
cleanup:            9c7a3497b9acf69364d83e5cf778ec4139bdbc69
cleanup run:        34699599796
frontend:           PASS
Real Chrome:        31/31 PASS
app.js cache:                42.25.95
```

Permanent proof: `tests/frontend/legacy-dataset-action-shell.test.mjs`. Next audit/migration target: live `doImportData` completion request scope; do not delete it as historical shell.



<!-- V42_25_ZIP_P1_ANNOTATION_SQLITE_ATOMICITY_20260913 -->
## 2026-09-13 — ZIP Processing P1 + Annotation SQLite Dataset Delete Atomicity

### ZIP Processing P1 — CLOSED

- 目标：量化并移除 1,000/10,000 图 ZIP 实际处理阶段的逐图放大，不改变导入语义。
- 同一 GitHub Actions runner、1,000 张真实 JPEG + YOLO txt 的前后基准（run `34733781003`, job `103661376150`）：
  - `get_project`: `2002 -> 1`
  - `material_patch`: `2000 -> 0`
  - `MaterialRepository` 初始化：`4002 -> 2002`
  - annotation 初始化 / upsert：保持 `2000`，本批未跨越 annotation 事务边界
  - wall time：`11.2115s -> 10.0417s`，同 runner 约 `1.116x`（约 11.6%）
  - 导入 1000 图、1000 框、最终 material/annotation 计数完全一致。
- 产品提交：`6fb34ebd07f5c6f460c58e3360825dbab49fea44` (`perf(import): remove per-image ZIP processing amplification`)。
- P1 明确只消除了重复 project `meta.json` 读取和 batch 内无效 material projection；没有用放宽断言换性能。

### Annotation SQLite Dataset Delete Atomicity — CLOSED

- 审计确认旧 dataset-delete journal 仍以 `annotations/{image_id}.json` 为删除/恢复对象，但当前标注真值已经是 `annotations.sqlite3`；成功删除数据集此前会留下 orphan SQLite annotation，异常恢复也无法覆盖当前 GT。
- 新架构不恢复 per-image JSON shadow，也不把 10k 完整 boxes 塞进 JSON journal；`AnnotationRepository` 增加 SQLite 内部 durable delete backup：`annotation_delete_backup`。
- 删除协议：`prepare_delete(token, ids)` 持久备份 -> 物理文件 staging -> material finalize -> annotation `finalize_delete(token)`；失败/恢复使用 `restore_delete(token)`，成功清理使用 `complete_delete(token)`。
- `finalize_delete` 只删除 `content_digest` 仍与备份一致的 annotation；并发标注变化时拒绝 stale delete。`restore_delete` 使用不覆盖已有新行的恢复语义。
- v50 buffered image batch 被拒绝时，同时清理真实 SQLite annotation，避免 orphan GT。
- Windows 文件锁回归改为锁真实上传图片文件，仍要求 409 + 数据集/material/annotation 完整保留；不再依赖不存在的 per-image JSON。
- 迁移 run `34734781793`：旧代码新合同 RED；两个历史 JSON-shaped guards RED；迁移后原子性组 `14 passed`，annotation/ZIP 回归 `7 passed`，正式 `VERSION.txt=42.24.0`。
- 产品提交：`e79eaa60ac18cbd5b78ad6df7bdb109643127871` (`fix(annotations): make dataset deletion atomic with SQLite truth`)。
- 永久化/一次性脚手架清理：`da676db7994c69b06b0084e000c5812d1206f87d`；长期 workflow：`Material Annotation Atomicity`。
- cleaned HEAD 长期验收：
  - Material Annotation Atomicity `34734901591`: PASS
  - Navigation Action Fencing `34734901538`: PASS
  - Frontend Runtime Stabilization `34734901543`: frontend PASS；Real Chrome `33/33 passed (1.0m)`
- 正式 `VERSION.txt` 仍为 `42.24.0`；未 merge main、未 tag、未 release。

### 下一主线

- ZIP Processing P2：先量化剩余 annotation 热点。P1 后 1,000 张 YOLO 仍有 `2000` 次 AnnotationRepository 初始化/upsert（初始 `unannotated` + 最终真实 annotation 各一次）。
- P2 必须先建立事务/失败回滚/负样本语义基线，再决定是否做单图双写折叠、连接复用或批量 annotation commit；禁止为了速度破坏标注真值和 dataset-delete 原子性。

<!-- ZIP-P2AB-2026-09-13 -->
## 2026-09-13 — ZIP Processing P2a / P2b verified checkpoint

状态：**P2a CLOSED；P2b（YOLO）CLOSED。COCO/VOC 同类双写仍 OPEN，后续按 P2c 单独建基线，不把 P2b 泛化为全格式完成。**

### P2a — annotation connection amplification

- 成功迁移 run：`34735300276`，job `103665544357`。
- 产品提交：`6e03e5467e4797b6b935f693953d20c16276c89d` — `perf(import): reduce annotation connection amplification`。
- 永久化 checkpoint：`cb0ff301c034813151703b320e593f8e54875cdb`。
- 1000 张 YOLO 同路径：annotation SQLite connections `6000 -> 2001`；follow-up `get()` `2000 -> 0`；`AnnotationRepository` 初始化 `2000 -> 1`；wall `9.4311s -> 7.6136s`，约 `1.239x`。
- annotation upsert 数量仍为 `2000`，因此 P2a 明确没有通过推迟/删除 durable annotation write 来换性能。

### P2b — YOLO final annotation single durable write

- 热点 profiler run：`34737776295`，job `103672131158`。1000 张下 `annotation_upsert_many` 是主要热点；图片解码与 SHA256 不是主因。
- RED + 迁移 + 同 runner 前后 benchmark run：`34737932595`，job `103672530091`。
- 旧代码基线：P2b 新合同 `3 failed, 1 passed`；失败准确覆盖 `annotation_builder` 不存在与 YOLO `40 != 20` 双写。
- 产品提交：`2be7dd8d1dc7d275fe71f8e0c17604febdf6368c` — `perf(import): write final YOLO annotation once`。
- 永久化/一次性脚手架清理：`d2cda6cab9b9c3b3427cb5f63c833c052f3a069e` — `test(import): permanentize ZIP Processing P2b`。
- 1000 张同 runner：`write_annotation 2000 -> 1000`；`annotation_upsert_many 2000 -> 1000`；annotation connections `2001 -> 1001`；wall `8.097123s -> 6.218626s`，`1.302x`，耗时下降约 `23.2%`。
- 结果不变：`report_imported_images=1000`、`report_boxes=1000`、`material_total=1000`、`material_boxes=1000`、`annotation_total=1000`、`annotation_annotated=1000`。
- 语义护栏：结构化 YOLO 在 `add_image_record()` 返回前直接持久化最终 GT；普通上传仍立即持久化 `unannotated`；空最终 GT 仍为 `confirmed_empty`；dataset-delete / v50 batch rollback 原子性合同继续保留。
- focused contracts：`10 passed`；annotation/material/import regressions：`17 passed`。

### Cleaned HEAD permanent gates

- Material Annotation Atomicity：run `34738062791` PASS，P2b 永久合同已纳入。
- Navigation Action Fencing：run `34738062810` PASS。
- Frontend Runtime Stabilization：run `34738062795` PASS；Real Chrome `33/33 passed`（53.5s）。
- 一次性 P2b profiler/migration workflow + helper 已物理删除；永久测试 `tests/api/test_zip_processing_p2b_single_final_annotation.py` 保留。
- 正式 `VERSION.txt` 仍严格为 `42.24.0`；未 merge `main`、未 tag、未 release。

### Next measured candidate

当前源码确认 `_v18_import_coco()` 与 `_v18_import_voc()` 仍存在 `add_image_record()` 后再 `write_annotation()` 的双 durable write 结构。下一批若继续，应作为 **P2c COCO/VOC structured-import single-write** 独立建立 RED、原子性合同与真实 benchmark；不要直接复用 YOLO 结论。

## ZIP Processing P2c — COCO/VOC structured-import single-write CLOSED

P2c is CLOSED with independent COCO and VOC RED → migration → GREEN → permanent-guard evidence; the YOLO P2b conclusion was not assumed to apply automatically.

```text
baseline + migration run: 34742240350
old COCO RED:             6 images -> 12 annotation upserts
old VOC RED:              6 images -> 12 annotation upserts
product:                  02ce1845d36dfa59e69e2a600d03a31b4da05d13
permanentization/cleanup: 233248847797023bc98bf0974490430139be3641

1000 COCO before:
  annotation writes/upserts: 2000
  annotation connections:    2001
  wall:                      13.599580s
  throughput:                73.532 images/s

1000 COCO after:
  annotation writes/upserts: 1000
  annotation connections:    1001
  wall:                      6.922337s
  throughput:                144.460 images/s
  wall speedup:              1.9646x

1000 VOC before:
  annotation writes/upserts: 2000
  annotation connections:    2001
  wall:                      10.693482s
  throughput:                93.515 images/s

1000 VOC after:
  annotation writes/upserts: 1000
  annotation connections:    1001
  wall:                      10.427986s
  throughput:                95.896 images/s
  wall speedup:              1.0255x
```

Both formats preserve `1000 material / 1000 annotation / 1000 boxes` truth. COCO and VOC now create the image record with the final annotation builder, so structured import no longer persists a temporary `unannotated` row and then rewrites the final GT. Plain image upload still retains immediate durable `unannotated` semantics; mixed structured imports retain `annotated` and `confirmed_empty` state/version contracts.

Permanent cleaned-head gates on `233248847797023bc98bf0974490430139be3641`:

```text
Material Annotation Atomicity: 34742373484 PASS
  atomicity/import contracts: 22 passed
  annotation/ZIP regressions:  7 passed

Navigation Action Fencing:     34742373492 PASS

Frontend Runtime Stabilization:34742373480 PASS
  Real Chrome:                 33/33 PASS (1.1m)
```

One-shot P2c migration workflow, migration helper and profiler were physically deleted after permanentization. The permanent P2c contract remains under `tests/api/test_zip_processing_p2c_structured_single_final_annotation.py` and `Material Annotation Atomicity`.

Post-P2c profiler decision: no new P2d is justified at this checkpoint. After single-write, COCO/VOC have one annotation upsert per image, one storage upload per image, one dataset-writable check per image, `get_project=1`, and one buffered material mutate; the remaining dominant timings are necessary per-image storage/annotation work rather than a newly demonstrated duplicate fan-out. Do not create P2d without new measured evidence.

**NEXT:** genuine 10,000-image processing-phase acceptance. Full 10k processing acceptance remains OPEN until wall time, throughput, resource/FD/SQLite behavior, progress cadence, rollback/recovery and final material/annotation/box truth are measured on a real annotated dataset.

Formal `VERSION.txt` remains `42.24.0`. No merge to `main`, no tag, no release. Technical-debt mainline remains PAUSED; A800 RC remains DEFERRED.

### 2026-09-13 cross-layer guard — durable cancel/resume truth CLOSED

Frontend/API control semantics are now fenced by durable server truth: ordinary v48 resume already rejects non-`RUNNING+paused`; the repository additionally rejects `set_stage()` once persisted status is `CANCEL_REQUESTED`, closing the concurrent stop/resume race rather than relying on the browser or an earlier API read. Real API regression is permanently included in `v42.25 Release Regression`; product `7cab9413185d0bfbc8052d978685ee7a2e8b46d0`, permanentization `dfa9623ad75eab9d7e0945cd45051688492e87f8`, Release `34749914123` PASS, Frontend Real Chrome `34749914114` PASS, Navigation Real Chrome `34749914211` PASS.

<!-- deployment-inference-process-fencing-closed-2026-09-13 -->
## Deployment test inference process fencing — CLOSED (2026-09-13)

Deployment-test subprocesses are now part of the durable execution fence instead of being invisible raw `subprocess.Popen` children. The runner is launched through the shared cross-platform process controller, binds exact `PID + create_time + command_hash` to the durable task, terminates the exact process tree on user cancellation or execution/lease fencing, and re-checks the current execution generation before result persistence.

Evidence:
- valid RED: GitHub Actions `34752083670` — real runner PID existed while durable `process_pid` was `None`;
- product: `97efe23ce2d587027150032f71906f03a75fcc51` (`fix(deployment): fence inference runner process`);
- focused GREEN: `34752147610`;
- permanentization: `fbbacad583a8f5ad50b27b1fcb6624b31255658e`;
- cleaned v42.25 Release Regression: `34752225736` PASS (runtime + training-data);
- cleaned Navigation Action Fencing: `34752225727` PASS including Real Chrome stale-mutation;
- cleaned Frontend Runtime Stabilization: `34752225677` PASS including Real Chrome runtime regressions;
- one-shot deployment process-fencing workflow removed during permanentization;
- formal `VERSION.txt` remains `42.24.0`; no merge/tag/release.

Genuine 10k processing acceptance and A800 RC remain deferred and are not closed by this batch.

<!-- RUNTIME-PROD-CLOSURES-2026-09-13-B -->
## 2026-09-13 — runtime productization closures: video publish + AI annotation cancellation

### Video frame publish cancellation / stale-execution fencing — CLOSED

- Valid RED run: `34752569787`. Old worker continued frame publication after durable cancellation and uploaded `3/3` frames after execution fencing/lease loss.
- Product: `8d267ae86a0a3030aa7faff8d4eccb9a1882b1d9` (`fix(video): fence frame publishing cancellation`). Every publish-side effect is guarded by cancellation/current-execution checks; late stale workers cannot continue material/result publication. Commit-phase progress now continues through the prior 90% plateau toward 97%/98%.
- Focused GREEN: `34752658173`.
- Permanentization: `22378473e077749ee5dc9de80ee9993daf28be64`; permanent contracts include `tests/unit/test_video_commit_fencing.py` plus the real video-worker integration path.
- Annotation integration was aligned with the already-authoritative SQLite truth (`annotations.sqlite3` / `AnnotationRepository`): no per-image JSON shadow was restored. Alignment/accepted HEAD: `cf81fd8b756d902cc6f9168f5f14d6357c806055`.
- Cleaned-head gates: Release `34752863299` PASS; Navigation Action Fencing `34752863247` PASS; Frontend Runtime `34752863225` PASS including Real Chrome.

### AI annotation in-flight cancellation side-effect fencing — CLOSED

- Valid RED run: `34753095270`. Cancellation during materialization still allowed one model inference call; cancellation during an in-flight model call still persisted the returned candidate.
- Product: `a1dabee5d867b19c9815c525e01793692db8b0a5` (`fix(annotation): fence cancellation around inference`). The worker re-proves cancellation/current execution immediately before provider inference and again after inference returns but before candidate/manifest writes. `InterruptedError` / lease-loss `PermissionError` remain control flow and are not converted into failed AI candidates.
- Focused GREEN: `34753193608`.
- Permanentization: `0d1c51f4caa25e1d653a32a5a790e792631126ca`.
- Existing candidate guards were migrated to current stronger truth in `3f6a63362a850049ebe6358d12eecf7d984ae79e`: failed provider generations do not inflate human `unreviewed` count, and unsafe task ids are rejected at `CandidateStore` construction by `ArtifactStore` before any candidate DB path is created.
- Cleaned-head gates on `3f6a63362a85...`: Release `34753389416` PASS; Navigation Action Fencing `34753389436` PASS including Real Chrome stale-mutation; Frontend Runtime `34753389399` PASS including full Real Chrome runtime regressions.

Release boundary remains unchanged: formal `VERSION.txt` is `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.

<!-- STORAGE-SCAN-CANCEL-CLOSURE-2026-09-13 -->
## 2026-09-13 — external storage scan cancellation fencing CLOSED

- Real bug: if Stop was requested while the final remote image read/decode was in flight, old `StorageImportHandler._scan_impl` had no later loop iteration to observe cancellation. It could open the same remote object again for missing SHA256, flush the candidate manifest, publish `scan/result.json`, and finish as `AWAITING_CONFIRMATION`.
- Permanent RED: `tests/unit/storage/test_import_scan_cancel_fencing.py`; valid RED run `34753661080` proved old code returned `AWAITING_CONFIRMATION` instead of `CANCELLED`.
- Product: `2ca557ed0bd72851948ad778163bf47d590b5a54` (`fix(storage): fence scan cancellation after remote reads`). Remote hashing now checks cancellation per chunk; inspection re-checks after image decode before follow-up I/O and after hashing; cancellation propagates rather than becoming INVALID/FAILED; `_scan_impl` refuses to append the in-flight cancelled object and returns `CANCELLED` while preserving only already-completed pending work.
- Migration run `34753741408` PASS: old-product RED, precise migration, syntax, focused GREEN, real storage-import worker/candidate/YOLO regressions, and formal version boundary all passed.
- Permanentization: `da54910048fd88f6cadeef34d130eba94af34303`; one-shot RED/migration workflows and helper were physically deleted. Release Regression permanently covers the cancellation contract, real storage import worker, import candidates, and YOLO import.
- Cleaned-head gates: Release `34753845097` PASS; Navigation Action Fencing `34753845073` PASS including Real Chrome stale-mutation; Frontend Runtime `34753845116` PASS including full Real Chrome runtime regressions.
- Formal `VERSION.txt` remains `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.

<!-- V42.25_STORAGE_INDEX_CANCEL_CLOSURE_20260913 -->
## 2026-09-13 Storage indexing cancellation fencing — CLOSED

- 真实缺口：素材导入确认后的 indexing 以批次处理；取消在 preflight 查询期间成为 durable truth 时，旧 Worker 仍可能继续 `materials.upsert_many(...)` / annotation / candidate outcome 写入，形成“任务最终 CANCELLED，但业务数据已继续提交”。
- 永久合同：`tests/integration/test_storage_index_cancel_fencing.py` 走真实 `scan -> AWAITING_CONFIRMATION -> confirm -> indexing`，在 material preflight 返回时注入 `CANCEL_REQUESTED`，要求最终 `CANCELLED`、material count 保持 0、candidate 保持未 indexed、不得发布 final result。
- RED/GREEN：`34755117132`；产品修复 `fe951e32aa2d7b840bfd9c975d500d0f0d200c9d`；永久化 `f9b11e691dd2e9daf0d6da2d3ef4f14c0b6d0909`。
- 修复边界：confirmation/ID assignment/preflight 后及 material、annotation、candidate outcome、mark-indexed 等不可逆写入前均重新读取 cancellation durable truth；不改变扫描、SHA 去重、YOLO label mapping 与确认语义。
- cleaned-head 正式门：Release Regression `34755481707` PASS；Navigation Action Fencing + Real Chrome `34755481732` PASS；Frontend Runtime + Real Chrome `34755481693` PASS（33 browser tests PASS）。accepted HEAD：`6cf54ac3b98a97a8be4c60a46d008e2a6bb499a1`。
- Release gate 同步关闭测试路径漂移：conversion / training resource contract 指回真实测试路径，并新增永久 path-integrity guard，workflow 中所有显式 `tests/*.py` 路径必须真实存在后才允许进入 pytest。
- 正式版本边界不变：`VERSION.txt = 42.24.0`；未 merge main、未 tag、未 release；A800 / genuine 10k acceptance 继续 defer。

<!-- STORAGE_IMPORT_PROGRESS_TRUTH_CLOSED_20260913 -->
## Storage import progress truth closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Product fix: `855abb7fe6fc2c759a85acf6c578dc5f8b62b10d` (`fix(storage): make import progress monotonic across confirmation`).
- Permanentization head: `030afa30c3e076cb6fac2c9234711b2f7d0c0cc6`.
- RED→GREEN migration run: `34755980730` PASS. Legacy behavior was proven RED before migration.
- Durable progress contract: material-import `AWAITING_CONFIRMATION` is a partial-task milestone with a 50% floor, not terminal 100%; confirmation/resume uses `MAX(existing_progress, 50)` and therefore never regresses a higher durable value.
- Confirmed indexing emits real monotonic `progress_percent` from the durable 50% floor toward 99% according to `indexed_at_least / selected_count`; only terminal success reaches 100%.
- Permanent tests: `tests/unit/task_runtime/test_material_import_progress_phases.py` and `tests/integration/test_storage_import_progress_truth.py` are included in the formal Release Regression gate.
- Cleaned-head Release Regression `34756082473`: PASS (`runtime-contracts` + `training-data-contracts`, including release-path guard).
- Cleaned-head Navigation Action Fencing `34756082427`: PASS.
- Cleaned-head Frontend Runtime Stabilization `34756082419`: PASS; `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were removed before the cleaned-head gates.
- Formal version boundary remains `VERSION.txt = 42.24.0`; no merge, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

<!-- TRAINING_REALTIME_PROGRESS_CLOSED_20260913 -->
## Normal training realtime progress closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Permanent RED contract commit: `474771da05c9652a1aa7103b737918ebe1011ffa`.
- Successful RED→GREEN migration run: `34756786009` PASS; legacy epoch-only behavior was proven RED before migration.
- Product fix: `16a1f76ebdc704bfbbcd7f96ce7a2b234f4017e7` (`fix(training): publish realtime batch progress`).
- Permanentization / cleaned product head: `65736aefd0b5961c3f6a7b3e45907937a9988973`.
- Progress contract: preparation owns 0..20; active normal training advances 20..90 using epoch + real train-batch completion; batch publication is throttled to about 4 Hz with mandatory final-batch flush; durable task progress remains monotonic.
- `job.json` publication is same-directory atomic replace so higher-frequency batch updates cannot expose a partially-written JSON file to the task handler.
- Durable `current_item` now carries `Epoch X/Y · Batch A/B` when batch truth is available; completed-epoch metrics remain authoritative and are not fabricated by batch callbacks.
- The normal model and the OOM-recreated model both attach the realtime batch callback. AI continuation is intentionally excluded from this closure and tracked as a separate follow-up batch.
- Permanent formal contracts include `tests/unit/test_training_realtime_progress.py`, `tests/unit/test_training_progress_v2.py`, and `tests/api/test_training_unified_task_overlay.py`.
- Cleaned-head Release Regression `34756946382`: PASS (`runtime-contracts` + `training-data-contracts`, release-path guard included).
- Cleaned-head Navigation Action Fencing `34756946390`: PASS; Real Chrome stale-mutation contract executed and passed.
- Cleaned-head Frontend Runtime Stabilization `34756946384`: PASS; full `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were deleted in the permanentization commit before cleaned-head gates.
- Formal version boundary remains `VERSION.txt = 42.24.0`; no merge, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

### 2026-09-13 — AI continuation realtime progress CLOSED

- RED contract commit: `084923474bdb0627756560c40f1b1a23a0543c14`.
- RED→GREEN workflow: `34757329068` — legacy RED proven, focused continuation GREEN, training runtime regressions PASS, formal version boundary PASS.
- Product commit: `57c698ad318110e9e825a7e80e7a1ad9be073369`.
- Permanentized clean HEAD: `c354d60e319b6fa195d70e175185c3b9cabec792`; one-shot migration helper/workflow removed.
- Release Regression `34758049699`: runtime-contracts PASS and training-data-contracts PASS; permanent `tests/unit/test_training_ai_continuation_progress.py` is in the release gate.
- Navigation Action Fencing `34758049728`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34758049698`: frontend unit PASS and full Real Chrome runtime regressions PASS.
- Durable/UI truth: normal training remains 20..90; AI continuation advances 90..95 with cumulative Epoch/Batch truth instead of resetting to 1/N; continuation YOLO instances rebind epoch, batch, resource and device callbacks; 95..100 remains reserved for artifact verification/final evaluation.
- `VERSION.txt` remains exactly `42.24.0`; no main merge, tag, release, or A800 RC was performed.

### 2026-09-13 — Deployment queued resource-position truth CLOSED

- RED contract commit: `11b39b96ee28107e222bf9204ffd5f986e72e9fc`.
- RED→GREEN workflow: `34758458780` — legacy RED proven, focused deployment GREEN, syntax/diff checks PASS, formal version boundary PASS.
- Product commit: `46cc645ac6d47e0b02a3440c2a3000062b19ba05`; precise product diff is one `static/app.js` queue-meta condition replacement only.
- One-shot migration assets removed by `f1e6dad93adee5a8ead763294c5d4aa6b27d147f`.
- Permanentized clean HEAD: `caaeae70098fce7a90a5cd2fbfce481b6f84c332`; Release trigger boundary now includes `static/app.js` and the permanent conversion queue-truth frontend contract.
- Release Regression `34758615703`: runtime-contracts PASS and training-data-contracts PASS.
- Navigation Action Fencing `34758615733`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34758615696`: frontend unit tests PASS, including `conversion-unified-task-truth.test.mjs`, and full Real Chrome runtime regressions PASS.
- Queue semantics remain server-owned and resource-scoped. Both `queued` and `waiting_resource` deployment conversion rows now display the live durable `resource_queue_position`; `resource_wait_reason` remains shown only for `waiting_resource`. Existing 1.8s full polling and backend ordering/claim semantics were not changed.
- `VERSION.txt` remains exactly `42.24.0`; migration helper/workflow are physically absent; no main merge, tag, release, or A800 RC was performed.

### 2026-09-14 — ZIP whole-task progress monotonicity CLOSED

- Permanent RED contract commit: `ee0e944ff654869c99c115d38b537e55acafd23f` (`tests/frontend/zip-import-overall-progress.test.mjs`).
- First migration run `34764744365`: legacy RED was proven; GREEN intentionally remained open because the first mapper had a floating-point edge (`95 -> 95.9`) and the source contract was too syntactically narrow for the existing equivalent upload expression.
- Successful RED→GREEN run: `34785810840` — legacy RED PASS, precise migration PASS, focused GREEN PASS, full frontend unit regression PASS, formal version boundary PASS.
- Product commit: `4140a8fa17eb949c26f3c2ec9e5b2b1d3e615f50`; product diff is limited to `static/app.js` (+2/-1): add the processing-to-whole-task mapper and consume it from active v19 ZIP polling.
- One-shot migration helper/workflow were physically removed before permanentization.
- Permanentized clean HEAD: `c6c28b9ed6bf2bfbe3a6cefbde9cdf2609dc2c46`; Release trigger boundary includes the permanent ZIP whole-task progress frontend contract.
- Release Regression `34786028127`: runtime-contracts PASS and training-data-contracts PASS.
- Navigation Action Fencing `34786028132`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34786028178`: frontend unit tests PASS (including ZIP whole-task progress contract) and full Real Chrome runtime regressions PASS.
- Active v19 ZIP UI truth is now one monotonic whole-task scale: browser upload `0..35`, upload/validation baseline `38`, backend processing phase projected to `38..99`, terminal success only `100`. Raw backend phase progress is no longer allowed to overwrite the whole-task percentage and cause `38 -> 8` regressions.
- Backend v19 processing phase semantics were not changed; this closure fixes the frontend projection boundary only.
- `VERSION.txt` remains exactly `42.24.0`; no main merge, tag, release, A800 RC, or genuine 10k acceptance was performed.

