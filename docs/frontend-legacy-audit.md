# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit:       210a9ad1f6271a8a8986db3f223f4813a6cce288
run:          34696729028
frontend:     PASS
Real Chrome:  PASS (31/31)
```

Current caches/builds:

```text
app.js                    42.25.84
main.mjs                  42.25.88
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
#modalBody normalization MutationObserver
base algorithm CRUD new/save/edit/saveEdit/view globals
v30 oldRenderAlgorithms wrapper
v39 oldViewAlgoV39 wrapper
v42.2 renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422 generation
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
