# Frontend Final-Owner Map — v42.25

## 2026-09-24 Training detail/log final-owner closure

Final product owner chain:

```text
TrainingTaskRuntime                list + task mutations
TrainingProgressStream             durable SSE/live task events
TrainingRecoveryRuntime            ONLY detail/log dialog visual owner
PollRegistryRuntime                detail fallback polling lifecycle
backend job detail/log endpoints   read-only enriched truth
```

Retired/forbidden as alternate owners: legacy `openTrainDetail423` renderer, legacy training run center, separate log modal renderer, private runtime CSS injector, raw timer loop. Success/failure semantics come from canonical `task_status`; an open detail receives SSE and performs one final canonical detail/log reconciliation at terminal transition. Detail polling must not dispatch queues, rebuild the jobs index, overwrite worker `job.json`, or archive algorithm versions.

Permanent evidence is documented in `docs/CODEX_HANDOFF_2026-09-24_TRAINING_DETAIL_LOGS.md`. Code baseline before documentation: `8e50195f76d0aa58ccf6082bdbd7c93029b528b7`; formal `VERSION.txt` remains `42.24.0`.


> Branch: `refactor/frontend-runtime-stabilization`  
> Status: PAUSED AUDIT — non-blocking technical-debt cleanup deferred by user request
> Latest fully accepted code point: `1c3fa7f2b5cb826c0998f249637241a59134f053` / run `34794630837`
> Real Chrome: PASS
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`

## Product closure — Deployment-test durable queue/progress truth CLOSED

The deployment-test business surface now preserves the same durable task truth as the unified v62 task API. Previously the v61 compatibility projection flattened a resource-waiting durable task back to persisted `QUEUED`, dropped queue/resource/worker metadata, and the final `benchPredictOne` loop only considered `QUEUED / RUNNING / CANCEL_REQUESTED` active. That combination could make a real `WAITING_RESOURCE` deployment test appear terminal or fail without showing why it was waiting.

Closed semantics:

```text
v61 business projection: delegates durable task fields to task_to_public()
compatibility aliases: id / progress / stage / result remain for the existing deployment surface
WAITING_RESOURCE: remains active and visible instead of being flattened to QUEUED
queue truth: resource_queue_position + resource_wait_reason are server-derived and visible
worker/progress truth: worker_id / phase / progress_percent come from durable public truth
active polling: after v61 creation, benchPredictOne reads /api/v62/projects/{project_id}/tasks/{task_id} while the task is active
terminal success: v61 is read once after SUCCEEDED to obtain deployment-specific result payload
frontend projection: PlatformCore.deployment.deploymentTaskView reuses taskPoller active/progress semantics
queue order / resource admission / worker claim / progress generation / process fencing: unchanged
```

Permanent guards include `tests/api/test_deployment_test_runtime.py`, `tests/frontend/deployment-runtime-source.test.mjs`, `tests/frontend/deployment-task-view.test.mjs`, `tests/unit/task_runtime/test_public_projection.py`, and `tests/unit/test_deployment_inference_process_fencing.py`. Release Regression now permanently runs the deployment business-projection contract and is triggered by the deployment task view/wiring guards. The frontend does not invent queue order or percentage; it only renders unified durable truth.

Evidence:

```text
valid RED head:             5748a89155e653a49c8a8c743cdd3de7a9fa67cf
valid RED run:              34794353496 (backend v61 QUEUED vs v62 WAITING_RESOURCE; final frontend unified-truth wiring RED)
focused/full GREEN run:     34794490531 PASS (API + frontend + public projection + deployment fencing + full frontend unit)
product commit:             0b800a54ae64507314a5f9199734759250691cb6
formal accepted clean HEAD: 1c3fa7f2b5cb826c0998f249637241a59134f053
Release Regression:         34794630826 PASS
Navigation Action Fencing:  34794630808 PASS (Real Chrome PASS)
Frontend Runtime:           34794630837 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All temporary deployment RED/migration helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Next product batch: **storage import polling owner / lifecycle-managed polling truth**. Storage import already preserves durable queue/progress display truth, but its action runtime still owns a direct `while + setTimeout(1200)` polling loop; that owner must be audited separately without mixing it into this deployment closure.

## Product closure — Cleaning frontend queue/progress truth CLOSED

Final clean-tab owner chain:

```text
/api/v47/projects/{project_id}/clean-tasks
→ v47 compatibility projection backed by durable MATERIAL_BATCH/CLEAN truth
→ PlatformCore.cleaning.cleanTaskView
→ cleanTaskView427 / cleanTaskRow427
→ refreshCleanOps427Delta
→ PollRegistry(clean-tasks-v47)
```

The browser does not compute queue order or progress. `status_text`, `progress`, processed/total/flagged counts, `resource_queue_position`, `resource_wait_reason`, and worker identity remain server-derived. `PollRegistry` is the sole clean-list timer owner; the historical recursive `setTimeout(...renderOps427...,2200)` is retired. `awaiting_confirmation` is terminal for list polling, and navigation/tab changes clear the timer.

Permanent guards: `tests/frontend/clean-task-view.test.mjs`, `tests/frontend/poll-registry.test.mjs`, and the v47 queue-field assertions in `tests/api/test_clean_unified_execution_truth.py`. Evidence: RED `cf3f2c4fec639903435379b3419dbaadad82c949` / run `34793075909`; GREEN `34793282831`; product `9f6f329393018623807cb4fea04707f3b5350676`; accepted `736b2acdbf2560be657011035de173cde67517d0`; Release `34793457861` PASS; Navigation `34793457872` PASS with Real Chrome; Frontend `34793457920` PASS with unit + full Real Chrome. `VERSION.txt` remains `42.24.0`.

Deployment-test durable queue/progress truth is CLOSED. Next owner audit: storage import polling owner / lifecycle-managed polling truth. No frontend queue simulation or alternate progress owner should be introduced.

## Product closure — Cleaning durable execution truth CLOSED

Final backend owner chain for cleaning execution:

```text
v47 manual clean / v55 upload-batch clean decision
→ prepare_material_batch / publish_prepared_material_batch
→ shared TaskRepository: MATERIAL_BATCH / CLEAN
→ materials worker registration
→ FencedTaskRepository + Scheduler / WorkerContext
→ durable result/checkpoint truth
→ v47 compatibility projection for legacy clean UI
```

The compatibility projection is display-only: an unconfirmed successful clean may appear as `awaiting_confirmation / review`, while the underlying durable task remains `SUCCEEDED / succeeded`. Legacy Web daemon workers and Web startup recovery are retired as execution owners. Queue/resource/progress metadata remains server/worker-derived. Permanent backend guard: `tests/api/test_clean_unified_execution_truth.py`; formal acceptance `3931a9a2d529845f9e698b22f62fe950a7a8b42f`, Release `34792673327` PASS, Navigation `34792673293` PASS with Real Chrome, Frontend `34792673296` PASS with unit + full Real Chrome. `VERSION.txt` remains `42.24.0`.

Following owner audit status: cleaning frontend row/poll truth and deployment-test durable queue/progress truth are CLOSED. Next: storage import polling owner / lifecycle-managed polling truth.

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

## Product closure — Video resource queue truth CLOSED

Final owner chain:

```text
/api/v33/projects/{project_id}/video-tasks
→ shared TaskRepository / task_to_public
→ _public_video_task
→ PlatformCore.video.normalizeVideoTask
→ videoTaskRow424
→ patchVideoRows424 / renderVideo424
→ PollRegistry(video-frames)
```

`resource_queue_position` and `resource_wait_reason` remain server-derived dynamic truth. `WAITING_RESOURCE` is a public active status and must continue polling. The v424 row displays `runtimeText`; it does not compute queue order locally. No alternate timer, frontend queue model, or shadow progress owner was introduced.

Permanent guard: `tests/frontend/video-tasks.test.mjs` executes the actual final row renderer and locks queued / waiting-resource visibility plus active-state polling semantics.

Evidence: RED `32284a8972faec46775144b8c47406e67edee014` / run `34789541200`; GREEN `34789628840`; product `c0fee2b7c8dfbf03481cbc6dfb1019f922293576`; accepted clean HEAD `cb81ca39016aea0fc53ed52090f0b0199d39109a`; Release `34789701814` PASS; Navigation `34789703315` PASS with Real Chrome; Frontend `34789704610` PASS with unit + full Real Chrome. `VERSION.txt` remains `42.24.0`.

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

## 1. Purpose

This map exists to delete historical frontend overrides without changing current behavior. Preserve live semantics, not version-era wrapper count. `static/app.js` remains a historical append-only chain; later assignments can shadow earlier layers or individual branches.

## Product mainline checkpoint — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.
- **ZIP 10k acceptance**: focused CI created a real ZIP with **10,000 image members** and passed the v19 create/scalability contract plus existing server-import/storage regressions. The permanent legacy unit guard was migrated, not weakened (`27654cba1fb3406567a40754904531c2b53aa53f`), and the permanent Chrome material/import contract was migrated to the real v19 sequence (`60305921402204e77b8e7ed4ec8e576d9f857c4b`): create → start → list polling → terminal done → labels/current paged-material scoped refresh, with an explicit assertion that no `/api/v18/` request or broad reload occurs. Final Frontend Runtime `34733035739` passed all frontend unit guards and Real Chrome **33/33 PASS (53.9s)**; Action Fencing `34733035761` PASS.
- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.96`; `main.mjs` cache is `42.25.93`. No merge/tag/release.

**Video resource queue truth, cleaning durable execution truth, and cleaning frontend queue/progress truth are CLOSED. Current next product scope: storage import polling owner / lifecycle-managed polling truth. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**

## 2. Runtime ownership

```text
static/app.js bounded classic render/page shell
→ static/main.mjs
   → PageRequestScope
   → PollRegistry
   → NavigationStability
   → named runtimes
```

Navigation ownership is already outside the classic `setPage` family. Further non-blocking cleanup is PAUSED; resume this audit only for real functional/performance/data-integrity/release-blocking evidence.

## 3. Closed owner batches

### Navigation / polling

```text
training/job polling compatibility              CLOSED
set423Base + setBase424                         CLOSED
V37 duplicate sidebar setPage                   CLOSED
oldSetV39 + oldSet42 + set422Base               CLOSED
v34/v35/v42.4 direct setPage family             CLOSED
v42.7 direct alias setPage                      CLOSED
setPageReady414                                 CLOSED
baseSetPage417                                  CLOSED
initial bootstrap setPage                       CLOSED
```

`static/app.js` contains zero classic `window.setPage=` assignments.

Navigation Action Fencing R1+R2 are accepted. `NavigationStability.action(ownerPage)` owns stale mutation commit checks for the migrated surfaces. R2 locks the true final model/config and review owners: `saveVisionModelM4`, `testModelConfigV35`, `confirmClean429` (`confirmClean427` compatibility alias), and v60 `completeAiReview60` (`confirmAiLabel427` compatibility alias). Clean confirmation is local-state-only from authoritative `deleted_ids + processed_ids`; v60 AI commit remains `taskApi(review.id)/decisions` with `commit:true`. Product `9f6df85b994f23b5408759fb64485b9477c75936`, cleanup/permanentization `3a8781dccf6704fe76d35d99c05b80590dc507c3`; permanent run `34721755316` PASS; full Real Chrome `34721755310` **32/32**. Overall async-action zero-point remains IN PROGRESS only for the remaining upload/ZIP/deployment/timer-callback completion families.

### Render / lifecycle

| Batch | Physically retired | Accepted code / run |
|---|---|---|
| R1 | v42.7 render-level auto-label alias mutation | `e35a29b0...` / `34656747269` |
| R2 | `oldRender429` | `0455eeef...` / `34659041402` |
| R3 | `previousRender61` | `69732d9e...` / `34659543452` |
| R4 | `render423Base` | `58ece59e...` / `34659775870` |
| R5 | shadowed `renderBase428` 算法列表 branch | `6be679b6...` / `34660269685` |
| R6 | v42.2 + v42.4 legacy `自动标注` render route branches | `66339fc0...` / `34663089996` |
| R7 | shadowed `renderBase424` 算法列表 / 数据集 / 训练任务 branches | `2d9bc0b3...` / `34663389819` |
| R8 | legacy `renderAutoLabel424` old-page 1.8s self-refresh timer/predicate | `70b6f755...` / `34663768606` |
| R9 | visible-version multi-owner chain: `baseRender417`, 12 app timers, main `applyBuildVersion` timers | `36fd25c4...` / `34664755130` |
| R10 | `render426base` page-render file-input beautification wrapper | `0dacf581...` / `34665470320` |
| R11 | `modal426` modal file-input beautification wrapper | `9bad939a...` / `34665890699` |
| R12 | `enhancePageV37` post-render normalization helper + RAF callbacks | `60d87751...` / `34666673017` |
| R13 | `baseRenderV37` duplicate versionInfo render wrapper | `43e31c7e...` / `34666985800` |
| R14 | `baseModalV37` autofocus compatibility wrapper | `8593516e...` / `34667341153` (rerun 18/18) |
| R15 | v35/v36/V37 80/100/120ms startup render/version timers | `b6edea36...` / `34667776611` |
| R16 | body-wide ZIP review observer + off-page material summary leakage | `540c0944...` / `34668702371` |
| R17 | page baseRender/RAF wrapper + `#view` normalization observer | `f5b8ff87...` / `34669152742` |
| R18 | bounded 100ms `renderTop/cleanup` startup wakeup | `954e9dba...` / `34670319479` |
| R19 | `#modalBody` normalization observer → explicit `ModalContentRuntime` | `f60d0009...` / `34670989473` |
| R20a | algorithm version deletion full reload → `AlgorithmListRuntime.refresh` | `103d630b...` / `34677761599` |
| R20b | model-version publish full reload → authoritative POST result + local state patch | `d18044d3...` / `34679069872` |
| R20c | training-server full reload → POST + training_options-only target refresh | `e3f23f59...` / `34681236515` |
| R20d | Paddle activation full reload → training_options-only target refresh | `a21846c3...` / `34681966242` |
| R20e | model-config/prompt full reload + stale prompt UI → authoritative local state ownership | `89327ded...` / `34684119911` |
| R20f | final M4 model-config save/edit broad `loadRelated` → authoritative saved item + local `modelConfigs` upsert | `94dbebb4...` / `34690924552` |
| R20g | ZIP + server-storage import completion broad refresh → scoped labels/material refresh | `a2f4cb40...` / `34693503185` (30/30) |
| R20g close | one-shot migration helper/workflow physical deletion | `6337f1a0...` / `34695825386` (30/30) |
| R20h | legacy algorithm CRUD + v30/v39/v42.2 shadowed algorithm generations retired; stable 414/423/429 local-state owners remain | `210a9ad1...` / `34696729028` (31/31) |
| R20i | legacy dataset-group CRUD + two shadowed dataset render generations + persistence wrapper retired; bounded delegate remains | `a7116811a...` / `34698983278` (31/31) |
| R20j | zero-reference dataset actions retired; live import and MaterialPagination owners preserved | `9c7a3497b9...` / `34699599796` (31/31) |
| R20k | live v18 import completion broad reload → labels + current paged materials only | `f51d44c089...` / `34700252041` (32/32) |
| R20l | live source-import terminal broad `loadRelated()` → labels + current paged materials only | `f8356bcf5e...` / `34723808299` (33/33) |
| R20m | shadowed v423 algorithm create/edit generation physically retired; stable 414 CRUD remains final | `40a87bf704...` / `34724354775` (33/33) |
| R20n | shadowed v35/v426/v427 Model Config modal/save generations retired; final M4 owner preserved | `b83b2bf360...` / `34725907423` (33/33) |

R20n product: `9acaa534e596464a1ebe129e435916ed7dd9cdf2`; cleanup `fce8034a861e1f9c5c0d37568891717309845794`; final accepted contract `b83b2bf360b891265157e602f622d409d1d2332f` / Frontend Runtime `34725907423`; Real Chrome **33/33 passed**; Action Fencing `34725907404` PASS. The final M4 `openModelConfigModalV35 → saveVisionModelM4` owner, M4 capture/final activation and model-config API semantics remain unchanged. One-shot R20n migration artifacts are physically deleted. Further non-blocking owner cleanup is PAUSED by user request.

R20h product: `d58e690ffcc1523f213a65cfc0a57380ffdc571e`; focused run `34696508446`; validation `210a9ad1f6271a8a8986db3f223f4813a6cce288` / run `34696729028`; frontend PASS; Real Chrome **31/31 passed**. The bounded base `renderAlgorithms()` compatibility delegate remains until older global render maps are retired, and the later report compatibility owner remains live by contract. R20h one-shot migration artifacts were deleted.  

R20i product: `feeb98f441bb1fe5d0f8f409a1509c66606e59ef`; validation `11131ca30c17809e016807aa6c75b0bf203fa6f8` / run `34698850495`; cleanup `a7116811adb26ebe5f0f9e621bf23df1dd1f605f` / run `34698983278`; frontend PASS; Real Chrome **31/31 passed**. Final dataset routing remains `renderDatasets424`; one bounded `renderDatasets()` delegate remains for historical render-map symbol compatibility. The dataset-group CRUD family, `oldSelectDataset`, `currentDataset()` and both shadowed dataset-group render bodies are physically retired and permanently guarded.  

R20j product: `e6398f7d8ae665079c82d64217c434af4a73073c`; focused run `34699354229`; validation `693a2fa2c3d39378782ac2270a95924eff5ca5ec` / run `34699442423`; cleanup `9c7a3497b9acf69364d83e5cf778ec4139bdbc69` / run `34699599796`; frontend PASS; Real Chrome **31/31 passed**. Five globally zero-reference dataset actions were physically retired. `doImportData` is explicitly preserved as live and becomes R20k because its successful v18 import path still invokes broad `reload()`.  

R20k product: `1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb`; focused run `34700022284` (211/211 frontend unit, focused Chrome 2/2); validation `60775456f3d4c8a441ba58ce65106af114aeebb2` / run `34700127243`; cleanup `f51d44c089b6342398c14bd38c8669747adad48b` / run `34700252041`; frontend PASS; Real Chrome **32/32 passed**. `doImportData` remains the live v18 XHR owner, but its successful completion now refreshes only labels and the current paged material domain. One-shot R20k migration artifacts are physically deleted.  

R20m baseline `243bcb1b17074848d91c2c9c64d47dbed54e5e9b` / migration run `34724242632`; product `71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e`; cleanup/final acceptance `40a87bf70402dccfc0387950b6856a561ce1ebe1` / Frontend Runtime `34724354775`; frontend PASS; Real Chrome **33/33 passed**; Action Fencing `34724354790` PASS. The early v423 algorithm create/edit generation was proven shadowed and physically deleted; stable 414 authoritative local-state CRUD remains the only final create/edit owner. Permanent source contract: `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`; browser behavior remains covered by `tests/browser/algorithm-list-performance.spec.mjs`. One-shot R20m migration artifacts are physically deleted.

R20l product: `f260127d2d41281bc1d996a172e7d4290536f24c`; baseline/migration run `34723694735`; permanent Chrome guard `b17bd0c33bfb99e5557fc245a89a6c4444a8257e`; cleanup/final acceptance `f8356bcf5ec1ea128fb38db2820df38146b48cfd` / Frontend Runtime `34723808299`; frontend PASS; Real Chrome **33/33 passed**; Action Fencing `34723808298` PASS. The final live `refreshSourceImportTasksV36()` terminal branch no longer calls broad `loadRelated()`; it refreshes only labels and the current paged material domain. Active polling cadence/API semantics are unchanged. One-shot R20l migration artifacts are physically deleted.

Cross-cutting P0 checkpoint: Resource Discovery SQLite lifecycle product `8ba4e10db5958204aca3d87779711d8e95f5d83b`; permanent Linux/Windows guard `5b66ee03e5aaa3af3a2f18a9092f12e303f69937` / run `34700900542`; cleanup `c6ac70b670a6297ccba065854779c10b8ca47cf3` / Frontend Runtime `34700984963` with Real Chrome **32/32 passed**. This is not a new frontend owner batch and does not close the broader resource-lifecycle soak gate.  

R10 product: `b9d25955c185aaabb4108f3d37cfecd9f876390a`.  
R11 baseline: `d2aa614870a52864e991502c2218134943afb14f`.  
R11 product: `8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1`.  
R11 final acceptance increased the browser suite to 17 tests; **17/17 passed**.  
R12 baseline: `6ae19dc79abbf690371a71162c97a2df6322518b`.  
R12 product: `202a5a82b0cb4629423ee0c6812f649031234daa`.  
R12 final acceptance increased the browser suite to 18 tests; **18/18 passed**.  
R13 product: `928d2387d46a0472bd202bd4df84af8d1573b6c2`.  
R13 validation: `43e31c7e683fbda4b9c36a3d35188262b6a9ff1b` / run `34666985800`; **18/18 passed**.  
R14 product: `6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829`; validation `8593516eb796f10fb43cea748bcc42b479e0a02e`. The first full pass exposed a lifecycle race at 17/18; rerunning the same run passed 18/18.  
R15 product: `280a31bf365b1a6646a57213dfa2dff97e10e0b5`; validation `b6edea36296ab9548037457a124b4369776f6f5e` / run `34667776611`; focused training performance 5/5 and final Real Chrome **18/18 passed**.  
R16 baseline: `540de6aef4ddbf82a6cf36994a31a73937abca73` / run `34668429941` exposed ZIP persisted-review loss and the remaining training-page `/materials` race. R16 product: `12df27e2af9155e3a1b9f745e46605396e321815`; focused run `34668639496` passed ZIP completion and training isolation 5/5; validation `540c0944f45030ea198af2be153c1505f71e62f0` / run `34668702371`; Real Chrome **19/19 passed**. All R16 one-shot migration artifacts were removed.  
R17 product: `4fc5d90a15ef2fc2dc22aa00f39967deba6f53f8`; validation `c3301d065fa820539873a4fa2f739992ef63f3d2`; guard alignment `f5b8ff8789de0f51d2a03bcabe126191005ba24c` / run `34669152742`; frontend **179/179 passed**, Real Chrome **19/19 passed**. The early page normalization wrapper, RAF cleanup and `#view` observer are permanently retired; `#modalBody` remains independent.

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

### R20b — model-version publish owner

The final live `saveAssign` owner now treats the version POST response as the authoritative mutation result. It updates the selected algorithm's `versions`, removes the published model from `state.pending`, clears `state.assigningModel`, closes the modal and locally renders. No global reload or follow-up GET belongs to this action.

```text
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / focused run 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
focused migration:  34679011468 PASS
validation:         d18044d3d98231affc7488974e04623dab6d2b10
run:                34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
```

### R20c — training-server target refresh owner

The live `saveServer` mutation no longer invokes global `reload()`. The server POST result is not sufficient to construct canonical training targets, so the owner performs the one required domain refresh: `/api/training_options?project_id=...`. `state.targets` is then replaced and the page rendered locally. The request contract forbids a bootstrap snapshot from this action.

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14
run:                34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
```

### R20d — Paddle environment activation owner

The final `detectPaddle` / `quickPaddleDetect` owners now delegate their post-activation state refresh to `refreshPaddleTrainingTargets20d()`. Required Paddle POSTs remain unchanged; the only follow-up GET is `/api/training_options?project_id=...`, which replaces `state.targets`. A bootstrap snapshot is forbidden by the permanent browser contract.

```text
baseline:            53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration:     34681841986 stopped pre-commit on generated-unit escaping syntax error
helper fix:          e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:             d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:   34681905173 PASS
validation:          a21846c33d79612f9ab4a47e2a69195da29caa3b
run:                 34681966242
frontend:            PASS
Real Chrome:         24/24 PASS
```

## 4. Current final navigation owner

```text
window.setPage = NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page)
       state.page = page
       render()
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistNavigationState
```

Historical localStorage `自动标注` values canonicalize to `自动标注及清洗` before render and are written back canonically.

## 5. Current visible owner map

| Surface | Current live owner | Required semantics | Proof |
|---|---|---|---|
| Navigation coordination | `NavigationStability` | request epoch, readiness, sidebar cleanup, actual apply, persistence | unit + Real Chrome |
| Training submit | `TrainingSubmitRuntime` | sole `/train/start`, canonical draft/readiness | unit + Chrome |
| Training jobs request | `TrainingTaskRuntime` | focused `/jobs`, coalescing, force-fresh mutation | unit + browser performance |
| Training jobs timer | `PollRegistry(training-jobs)` + `renderTraining423` activation | managed cadence + navigation cleanup | unit + Chrome |
| AutoLabel route | `renderBase427 → renderOps427()` | canonical `自动标注及清洗` | unit + Chrome |
| AutoLabel polling | `AutoLabelPollRuntime + PollRegistry` | explicit activate/deactivate | unit + Chrome |
| Video | `PollRegistry(video-frames)` | managed one-shot row patch | unit + Chrome |
| Sources | `PollRegistry(sources)` | managed interval | unit + Chrome |
| Data/material route | `oldRender412 → renderDatasets424()` | stable outer data route | unit + browser performance |
| Algorithm list route | `oldRender412 → renderAlgorithms423()` | sole outer algorithm route | browser performance + guard |
| Algorithm version delete refresh | `delVersion → AlgorithmListRuntime.refresh` | DELETE + algorithms/jobs scoped refresh; no global reload fan-out | unit + Chrome request contract |
| Model-version publish | final `saveAssign` → authoritative POST result | one POST; local algorithm-version + pending-state patch; zero reload GETs | unit + Chrome request contract |
| Training-server creation | final `saveServer` → training_options scoped refresh | POST server + GET training_options; replace targets; bootstrap=0 | unit + Chrome request contract |
| Model-config deletion | `deleteModelConfigV35` | DELETE + local `state.modelConfigs` removal; no follow-up GET | unit + Chrome request contract |
| Model-config save/edit | M4 final activation → `openModelConfigModalV35` → `saveVisionModelM4` | POST/PUT authoritative item + local `state.modelConfigs` upsert; zero broad follow-up GETs | unit + Chrome request contract |
| Prompt-template save/edit | `savePromptTemplateV35` | authoritative POST/PUT item + local upsert; no follow-up GET | unit + Chrome request contract |
| Prompt-template deletion | `deletePromptTemplateV35` | DELETE + local `state.promptTemplates` removal; no follow-up GET | unit + Chrome request contract |
| Paddle environment activation | final `detectPaddle` / `quickPaddleDetect` → `refreshPaddleTrainingTargets20d` | required POSTs + one training_options GET per activation; bootstrap=0 | unit + Chrome request contract |
| Training task page route | `renderBase428 → renderTraining423()` | training-only route | browser performance + guard |
| Quality center route | `renderBase424 → renderQualityCenter424()` | live route retained | guard |
| Video slicing route | `renderBase424 → renderVideo424()` | live route retained | guard |
| Deployment routes | `oldRenderV39` | conversion/artifact/resource/plugin/component | liveness audit |
| Label management route | `render414Base` | label management | liveness audit |
| Storage configuration route | `finalRender` | `renderStorageSources61()` + final page normalization dispatch | dedicated Chrome contract |
| Page post-render normalization | `finalRender` → `PostRenderNormalizationRuntime.apply` → `cleanup(root)` | exactly one final-render cleanup; no view observer/RAF wrapper | unit + Chrome |
| Modal content + normalization | `ModalContentRuntime.replace` → `PostRenderNormalizationRuntime.apply` for `#modalBody` | explicit replacement, table wrapping + dynamic modal file-input beautification | unit + Chrome |
| Render-path formal versionInfo | later `V42` render owner | `state.versionInfo.version = 42.24.0` before delegate | unit + Chrome |
| Modal autofocus | base `modal()` | first editable modal field autofocus | Chrome + unit guard |
| Visible top version | `top412 / V412` | formal `v42.24.0` | unit + Chrome |
| Visible sidebar version | `nav426 / V426` | formal `v42.24.0` | unit + Chrome |
| ZIP completion review | `completeZipImportReview412` | persistent review action + one auto-open after successful completion | unit + Chrome |
| Material summary | `refreshSummary61` | requests only while current page is paged 数据集 | unit + browser performance |
| Internal UI build metadata | `UI_BUILD_VERSION` → `document.documentElement.dataset.uiBuild` | `42.25.0-dev`, non-visible | unit guard |

## 6. R9 version ownership

Retired:

```text
baseRender417 render correction wrapper
baseRender417 120/600/1600ms correction timers
12 app.js delayed versionBadge startup timers
main.mjs applyBuildVersion()
main.mjs 80/500/1800/3600/8000ms visible version writes
```

Retained semantic owners:

```text
static/index.html initial visible badge → v42.24.0
top412 / V412                         → top badge v42.24.0
nav426 / V426                         → sidebar footer v42.24.0
UI_BUILD_VERSION                      → internal dataset metadata only
```

## 7. R10/R11 file-input ownership

### R10 page path

Pre-R10:

```text
render426base
→ previous render chain
→ requestAnimationFrame
→ beautifyFileInputs426(#view)
```

Final page ownership:

```text
final render chain
→ PostRenderNormalizationRuntime.apply(#view)
→ cleanup(#view)
→ beautifyFileInputs426(root)
```

### R11 modal path

Pre-R11:

```text
modal426
→ previous modal owner
→ requestAnimationFrame
→ beautifyFileInputs426(layer || document)
```

R11 interim modal ownership (superseded by R19):

```text
modalBody DOM mutation
→ MutationObserver
→ cleanup(addedNode)
→ beautifyFileInputs426(root)
```

R19 final ownership is explicit `ModalContentRuntime.replace` with synchronous normalization for `#modalBody`.

Physically retired:

```text
render426base
modal426
both dedicated file-input beautification RAF callbacks
```

Retained:

```text
beautifyFileInputs426 implementation/export
cleanup(root)
PostRenderNormalizationRuntime final-render page dispatch
ModalContentRuntime explicit replacement owner
```

The observer lifecycle was closed in R19; current behavior is locked by permanent unit + Chrome contracts.

## 8. R12 post-render normalization ownership

Pre-R12:

```text
baseRenderV37 / baseModalV37
→ requestAnimationFrame(enhancePageV37)
→ wrap page/modal tables
→ remove 使用建议 panel
```

Final normalization owner:

```text
cleanup(root)
→ wrap table.table in .table-wrap
→ remove historical guidance panels
→ existing file-input / empty-state / placeholder cleanup
```

Retired:

```text
enhancePageV37
requestAnimationFrame(enhancePageV37)
modal enhancePageV37 callback
```

Retained for separate proof:

```text
baseRenderV37 → state.versionInfo write only
baseModalV37  → first editable modal field autofocus only
```

## 9. Render topology — confirmed live / retired

### Confirmed live

```text
oldRender412      算法列表 / 数据集
renderBase428     训练任务
renderTraining423 current training renderer + PollRegistry activation
renderBase427     自动标注及清洗
renderBase424     质量中心 / 视频切帧
oldRenderV39      deployment routes
render414Base     标签管理 route
finalRender       素材存储配置 + final page normalization dispatch
PostRenderNormalizationRuntime.apply / cleanup(root)
                  page normalization + table/file-input cleanup
ModalContentRuntime.replace(root, html)
                  explicit modal/preview/review replacement + #modalBody normalization
base modal()       first editable modal field autofocus
```

### Physically retired

```text
oldRender429
previousRender61
render423Base
renderBase428 算法列表 branch
v42.2/v42.4 legacy 自动标注 route branches
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy old-page timer/predicate
baseRender417 visible-version wrapper/timers
historical visible-version delayed writers
render426base page-render wrapper
modal426 modal wrapper
enhancePageV37 normalization helper/RAF callbacks
baseRenderV37 duplicate versionInfo wrapper
baseModalV37 autofocus compatibility wrapper
v35/v36/V37 80/100/120ms startup render/version timers
oldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver
transport.mode-only material summary page guard / off-page summary request leakage
legacy baseRender + RAF page normalization wrapper
#view post-render MutationObserver
#modalBody normalization MutationObserver
bounded 100ms renderTop/cleanup startup timer
```

## 10. Remaining render/lifecycle audit targets

Independent proof is still required for:

```text
older base/global render generations still reachable through delegates
global reload / loadAll / loadRelated request ownership
```

`oldRenderV39`, `render414Base`, `renderBase424`, `renderBase427`, `renderBase428`, `oldRender412`, and `finalRender` are confirmed live and are not whole-wrapper deletion candidates without semantic migration proof.

## 11. Permanent proof currently active

Frontend:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
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
tests/frontend/navigation-stability.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
```

Browser suite includes permanent contracts:

```text
file input beautification survives page render lifecycle ownership
modal file input beautification survives modal lifecycle ownership
modal table wrapping and first-field focus survive normalization ownership
base modal post-open content refresh stays functional
algorithm version deletion uses focused refresh without full reload
model config save appears immediately without broad related refresh
```

Current accepted Real Chrome suite: **28/28** in run `34690924552`.

## 12. Per-batch checklist

```text
live HEAD
→ exact reference/liveness/source-order proof
→ deterministic regression or browser contract
→ bounded semantic migration/deletion
→ permanent guard
→ syntax/focused unit
→ full frontend
→ Real Chrome
→ delete temporary migration artifacts
→ sync all four handoff docs
```

## 13. Release boundary

No `main` merge, `VERSION.txt` bump, tag/release or A800 acceptance claim is authorized. A800 RC remains deferred until current P0/P1 debt and zero-point scan are complete.

### R20e — model configuration mutation owners

```text
deleteModelConfigV35
  → DELETE
  → filter state.modelConfigs
  → render

savePromptTemplateV35
  → POST/PUT returns authoritative template
  → upsert state.promptTemplates
  → render

deletePromptTemplateV35
  → DELETE
  → filter state.promptTemplates
  → render
```

Acceptance chain:

```text
baseline:             afa2bfcb474cc9970129723af5589ab74a26eca7 / 34683803977 → 1/3 PASS, exposed stale prompt UI
first migration run:  34683969019 → product not committed; generated wiring assertion escaped incorrectly
guard fix:            becabf102d10520db52fdac9af1d5238357aa3f3
focused:              34684037005 → unit 4/4 + Chrome 3/3 PASS
product:              febece523b462692cc857431cb901fc5a863d091
validation:           89327ded9da924753f5f900fc3b79e6df353927f
full run:             34684119911
frontend:             PASS
Real Chrome:          27/27 PASS
```

These mutation owners now have zero bootstrap/model-config/prompt-template follow-up GET fan-out. R20 remains open only pending final zero-point proof across the remaining source-order `reload/loadAll/loadRelated` sites.


### R20f — M4 capture/final-activation model-config save owner

The final model-configuration modal cannot be identified by textual assignment order alone. M4 captures its modal function in `window.__m4OpenModelConfig`, a later compatibility layer overwrites the public name, and the file-tail M4 final activation restores the captured function. The visible save button therefore reaches `saveVisionModelM4`.

```text
__m4OpenModelConfig capture
→ later compatibility override
→ M4 final activation restore
→ saveVisionModelM4
→ POST/PUT /api/v35/model-configs[...]
→ authoritative saved item
→ local state.modelConfigs upsert
→ local render
```

Accepted at product `c9b7ab44192d38c37753643ee790fc2e089c8598`, validation `94dbebb43d83b1d522ea4e3f6522154417f3e985`, run `34690924552` with frontend PASS and Real Chrome **28/28**. The permanent owner guard checks the M4 capture + final activation chain and forbids `loadRelated/loadAll` inside the live save owner.


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

### 2026-09-13 training control truth boundary — CLOSED

`v48_pause_job` / `v48_resume_job` / `v48_stop_job` remain API control owners, but task lifecycle truth is owned by the durable repository. `TaskRepository.set_stage()` is now valid only for persisted `RUNNING`; `CANCEL_REQUESTED + cancelling` cannot be resumed by a stale control request. The permanent v48 API regression proves normal pause→resume still works and stop→late-resume is rejected. Product `7cab9413185d0bfbc8052d978685ee7a2e8b46d0`; permanentization `dfa9623ad75eab9d7e0945cd45051688492e87f8`; cleaned gates `34749914123` / `34749914114` / `34749914211` all PASS.

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

