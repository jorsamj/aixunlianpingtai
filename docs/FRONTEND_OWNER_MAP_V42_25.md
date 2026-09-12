# Frontend Final-Owner Map — v42.25

> Branch: `refactor/frontend-runtime-stabilization`  
> Status: ACTIVE AUDIT  
> Latest fully accepted code point: `f8356bcf5ec1ea128fb38db2820df38146b48cfd` / run `34723808299`
> Real Chrome: 33/33 passed
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`

## 1. Purpose

This map exists to delete historical frontend overrides without changing current behavior. Preserve live semantics, not version-era wrapper count. `static/app.js` remains a historical append-only chain; later assignments can shadow earlier layers or individual branches.

## 2. Runtime ownership

```text
static/app.js bounded classic render/page shell
→ static/main.mjs
   → PageRequestScope
   → PollRegistry
   → NavigationStability
   → named runtimes
```

Navigation ownership is already outside the classic `setPage` family. Current cleanup target is the remaining render/post-render chain and lifecycle debt.

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

R20h product: `d58e690ffcc1523f213a65cfc0a57380ffdc571e`; focused run `34696508446`; validation `210a9ad1f6271a8a8986db3f223f4813a6cce288` / run `34696729028`; frontend PASS; Real Chrome **31/31 passed**. The bounded base `renderAlgorithms()` compatibility delegate remains until older global render maps are retired, and the later report compatibility owner remains live by contract. R20h one-shot migration artifacts were deleted.  

R20i product: `feeb98f441bb1fe5d0f8f409a1509c66606e59ef`; validation `11131ca30c17809e016807aa6c75b0bf203fa6f8` / run `34698850495`; cleanup `a7116811adb26ebe5f0f9e621bf23df1dd1f605f` / run `34698983278`; frontend PASS; Real Chrome **31/31 passed**. Final dataset routing remains `renderDatasets424`; one bounded `renderDatasets()` delegate remains for historical render-map symbol compatibility. The dataset-group CRUD family, `oldSelectDataset`, `currentDataset()` and both shadowed dataset-group render bodies are physically retired and permanently guarded.  

R20j product: `e6398f7d8ae665079c82d64217c434af4a73073c`; focused run `34699354229`; validation `693a2fa2c3d39378782ac2270a95924eff5ca5ec` / run `34699442423`; cleanup `9c7a3497b9acf69364d83e5cf778ec4139bdbc69` / run `34699599796`; frontend PASS; Real Chrome **31/31 passed**. Five globally zero-reference dataset actions were physically retired. `doImportData` is explicitly preserved as live and becomes R20k because its successful v18 import path still invokes broad `reload()`.  

R20k product: `1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb`; focused run `34700022284` (211/211 frontend unit, focused Chrome 2/2); validation `60775456f3d4c8a441ba58ce65106af114aeebb2` / run `34700127243`; cleanup `f51d44c089b6342398c14bd38c8669747adad48b` / run `34700252041`; frontend PASS; Real Chrome **32/32 passed**. `doImportData` remains the live v18 XHR owner, but its successful completion now refreshes only labels and the current paged material domain. One-shot R20k migration artifacts are physically deleted.  

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
