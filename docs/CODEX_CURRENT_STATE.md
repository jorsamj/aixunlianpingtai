# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: b83b2bf360b891265157e602f622d409d1d2332f
Frontend Runtime run:        34725907423
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.93
main.mjs cache:              42.25.89
NavigationStability:         422512
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34725907423` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after final R20n shadowed Model Config retirement. Browser navigation runs **33 tests and passed 33/33**. Permanent Action Fencing workflow `34725907404` is green; permanent Resource Discovery SQLite workflow `34700900542` remains green on Ubuntu and Windows. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
TECH-DEBT CLEANUP PAUSED BY USER REQUEST
→ resume only for real functional/performance/data-integrity/release-blocking evidence
→ Unified Task Progress + Durable Queue Runtime productionization (product work, when requested)
→ Navigation Action Fencing final scan DEFERRED unless a real stale-async defect appears
→ external algorithm catalog read-only boundary
→ separate Resource Lifecycle production soak / non-SQLite resource classes
→ ZIP 10k / training progress / GPU tuner / deployment artifact E2E
→ app.js/app.py normalization
→ backend regression
→ A800 RC
```

A800 RC remains deferred unless the next product/acceptance task explicitly resumes it.

### R20n — shadowed Model Config generations retirement CLOSED / 技术债主线暂停

Source-order 与删除前/后的同一套 M4 Real Chrome 合同证明：旧 v35 / v426 / v427 `openModelConfigModalV35 → saveModelConfigV35/saveModelConfig426/saveModelConfig427` generations 已被最终 M4 owner 覆盖，运行时不可达。R20n 仅物理删除这 3 套历史 modal/save generation；最终 `saveVisionModelM4`、`testModelConfigV35`、M4 capture/final activation、模型配置字段与 API 语义均保持不变。

```text
baseline + migration run: 34725790087
product:                  9acaa534e596464a1ebe129e435916ed7dd9cdf2
cleanup:                  fce8034a861e1f9c5c0d37568891717309845794
contract alignment / accepted HEAD: b83b2bf360b891265157e602f622d409d1d2332f
Frontend Runtime:         34725907423
full Real Chrome:         33/33 PASS
Navigation Action Fencing:34725907404 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:             42.25.93
main.mjs cache:           42.25.89
```

永久 source contract：`tests/frontend/shadowed-model-config-generations-r20n.test.mjs`；最终 M4 行为继续由 `tests/browser/navigation-action-fencing-r2.spec.mjs` 与现有 Action Fencing workflow 覆盖。一次性 R20n migration helper/workflow 已物理删除。

**按用户要求，从 R20n 起技术债清理主线 PAUSED。** 剩余 R20 global reload/request zero-point、stale-async final scan、cache-busting、历史 dead code、命名/结构归一化、Resource Lifecycle production soak 等均保持 OPEN/DEFERRED，不宣称 CLOSED；除非出现真实功能故障、明显性能问题、数据完整性风险或发布验收阻断，否则不得为了“代码更干净”继续展开技术债批次。

### R20m — shadowed v423 algorithm CRUD generation retirement CLOSED

Liveness/source-order audit found two generations sharing `openNewAlgorithm423` / `editAlgorithm423`. The early v423 generation owned `saveNewAlgorithm423` / `saveEditAlgorithm423` and broad `loadRelated()`, but later stable 414 assignments overwrite the entrypoints before any final algorithm UI action can invoke them. The existing CRUD Real Chrome contract passed **before** retirement, proving the stable 414 generation was already live.

R20m physically removed only the unreachable early create/edit generation. Final create/edit/delete continue to patch authoritative `state.algorithms` locally and remain broad-refresh free.

```text
baseline:                  243bcb1b17074848d91c2c9c64d47dbed54e5e9b
baseline + migration run: 34724242632
product:                   71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e
cleanup / acceptance:      40a87bf70402dccfc0387950b6856a561ce1ebe1
Frontend Runtime:          34724354775
full Real Chrome:          33/33 PASS
Action Fencing:            34724354790 PASS
formal VERSION.txt:        42.24.0 unchanged
app.js cache:              42.25.92
main.mjs cache:            42.25.89
```

Permanent source contract: `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`. Browser behavior remains covered by `tests/browser/algorithm-list-performance.spec.mjs`. One-shot R20m migration artifacts are physically deleted. **R20m CLOSED; global R20 zero-point remains IN PROGRESS.**

### R20l — source-import terminal completion scoped refresh CLOSED

Final liveness/source-order proof confirmed that `window.refreshSourceImportTasksV36()` is the live source-import polling owner. Its terminal branch used to call final broad `loadRelated()`, which fans out across project/datasets/full images/labels/algorithms/publish/test-models/model-configs/prompt-templates. Real Chrome baseline proved the fan-out before migration.

The terminal branch now owns only the domains actually changed by a completed source import:

```text
refreshLabels414(false)
+ if still on 数据集 → reloadMaterialPage61()
```

Active-task polling cadence and source-import API semantics are unchanged.

```text
baseline + migration run: 34723694735
product:                  f260127d2d41281bc1d996a172e7d4290536f24c
permanent Chrome guard:   b17bd0c33bfb99e5557fc245a89a6c4444a8257e
cleanup / acceptance:     f8356bcf5ec1ea128fb38db2820df38146b48cfd
Frontend Runtime:         34723808299
full Real Chrome:         33/33 PASS
Action Fencing:           34723808298 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:             42.25.91
main.mjs cache:           42.25.89
```

Permanent contracts: `tests/frontend/source-import-completion-scope.test.mjs`, `tests/browser/source-import-completion-scope.spec.mjs`, and the browser spec is explicitly listed in `.github/workflows/frontend-runtime-stabilization.yml`. One-shot R20l migration artifacts are physically deleted. **R20l is CLOSED; global R20 zero-point remains IN PROGRESS.**

### Navigation Action Fencing R1 — resource/Paddle mutation completion CLOSED

真实旧代码 baseline 已在 Real Chrome 证明：训练资源页慢 `POST /api/train_servers` 发出后，用户切到数据集并打开属于新页面的 modal；旧 POST 完成会执行 `closeModal()`，把新页面 modal 关闭并清掉 sentinel。该行为不是测试推断，而是浏览器复现。

```text
baseline / focused migration run: 34701875185
old Chrome failure: stale save completion closed or rewrote the new-page modal
product:            8269eb0cca84ea310f48ee13af34ab09dd1bfeff
follow-up:          01234ef186f3e57bef2d29ac19420952beef6c36
cleanup:            7fcfcaec0b088a851dbcd580ac226b3dd892fa83
Frontend Runtime:   34702374386
full Real Chrome:   32/32 PASS
permanent Action Fencing run: 34702374346 PASS
formal VERSION.txt: 42.24.0 unchanged
app.js cache:       42.25.88
main.mjs cache:     42.25.89
NavigationStability: 422512
```

R1 新增 `NavigationStability.action(ownerPage)`，通过 navigation epoch/token 暴露 `isCurrent()` / `commit()`；后台 mutation 可以完成，但 stale completion 不得再提交 modal、DOM、state 或 render side effect。`saveServer` 在 POST 后和 scoped `training_options` refresh 后都执行 stale fence。Paddle 手动/一键激活同样有 action fence；若用户仍在训练资源页，只做当前页 render + toast，不再冗余导航回自己。

R1 还将目标范围内的 direct page write 清零：训练资源、模型配置、部署转换、训练任务以及旧“新建算法/自动迭代 → 算法列表”renderer rewrite 不再通过 `state.page='xxx'; render()` 导航；需要跳页时统一走 `NavigationStability`/`window.setPage`。

永久合同：

```text
tests/frontend/navigation-action-fencing.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/browser/navigation-action-fencing.spec.mjs
.github/workflows/navigation-action-fencing.yml
```

一次性 R1 migration/follow-up helper 与 workflow 已物理删除。

**R1 已由 R2 继续收口。** R2 关闭最终 M4 模型保存/连接测试、最终清洗确认和 v60 AI review completion；upload/ZIP/deployment/timer-callback completion 仍留给 final scan，因此全局 stale-async zero-point 仍为 IN PROGRESS。

### Navigation Action Fencing R2 — final Model Config / clean / v60 AI completion CLOSED

最终 live owner：

```text
saveVisionModelM4
testModelConfigV35
confirmClean429  (confirmClean427 compatibility alias)
completeAiReview60(mode)  (confirmAiLabel427 compatibility alias)
```

所有 completion 在异步请求前捕获 `NavigationStability.action(state.page)`，在请求返回后、提交 state/DOM/modal/render/toast 前拒绝 stale action。`confirmClean429` 使用 authoritative `deleted_ids + processed_ids` 做 local patch，已移除 broad `loadRelated()`；v60 AI review 保持 `taskApi(review.id)/decisions` + `commit:true` durable contract。

```text
baseline / migration run: 34721629224
product:                  9f6df85b994f23b5408759fb64485b9477c75936
cleanup / permanentize:   3a8781dccf6704fe76d35d99c05b80590dc507c3
Frontend Runtime:         34721755310
full Real Chrome:         32/32 PASS
permanent Action Fencing: 34721755316 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:             42.25.90
main.mjs cache:           42.25.89
```

永久合同为 `tests/frontend/navigation-action-fencing-r2.test.mjs`、`tests/browser/navigation-action-fencing-r2.spec.mjs`，并已合并进唯一长期 `.github/workflows/navigation-action-fencing.yml`。一次性 R2 helper/workflow 已物理删除。

### R20g — import completion scoped refresh + mechanical close

The final ZIP-import completion owner and server-storage import confirmation no longer broaden into `loadRelated()` / `loadAll()`. They refresh only labels when required and the paged material domain when the user is actually on 数据集. The one-shot migration helper/workflow were physically deleted after full acceptance.

```text
product:            a67778fd9b60384dbfffa2156e99670d244dadc9
validation:         a2f4cb40abb6d70ad4faf89bde60c1ee39e4a179
validation run:     34693503185
validation Chrome:  30/30 PASS
artifact cleanup:   6337f1a0379c7e60fbbc459668090504c0b6095b
cleanup run:        34695825386
cleanup Chrome:     30/30 PASS
app.js cache:       42.25.83
main.mjs cache:     42.25.88
```

Current exact next scope is **R20 final global reload/request zero-point** plus proven-dead `app.js` runtime-shell deletion. Do not reopen classic `setPage` ownership.

### R20h — legacy algorithm CRUD / shadowed renderer retirement

The original algorithm CRUD generation (`newAlgorithm/saveAlgorithm/editAlgorithm/saveEditAlgorithm/viewAlgorithm`), v30 `oldRenderAlgorithms`, v39 `oldViewAlgoV39`, and the shadowed v42.2 algorithm page generation were physically retired after proving that the final algorithm route is owned by `renderAlgorithms423` and stable 414/423/429 actions. The bounded base `renderAlgorithms()` symbol remains only as a compatibility delegate to `renderAlgorithms423` until older global render maps are retired. The later report compatibility owner is intentionally preserved because `viewAlgorithm423/versionRows423` still uses it.

Stable mutations now remain:

```text
algorithm.create → openNewAlgorithm423 → saveNewAlgorithm414 → local state.algorithms prepend
editAlgorithm423 → saveEditAlgorithm414 → local state.algorithms replace
delAlgorithm → DELETE → local state.algorithms filter
```

All three paths are permanently guarded against `reload()/loadAll()/loadRelated()` fan-out. The permanent Real Chrome contract creates, edits and deletes through the UI and forbids broad project/dataset/image/job/label/algorithm/bootstrap refreshes while allowing unrelated runtime polling.

```text
product:          d58e690ffcc1523f213a65cfc0a57380ffdc571e
focused run:      34696508446
validation:       210a9ad1f6271a8a8986db3f223f4813a6cce288
validation run:   34696729028
frontend:         PASS
Real Chrome:      31/31 PASS
app.js cache:     42.25.84
main.mjs cache:   42.25.88
```

One-shot R20h migration artifacts are physically deleted. Current exact next scope remains **R20 final global reload/request zero-point**, starting with a liveness audit of dataset mutation owners.

### R20i — legacy dataset-group owner retirement

The final dataset route already bypasses the historical dataset-group pages and directly owns the page through `renderDatasets424`. R20i proved two old `renderDatasets` generations plus dataset-group CRUD and the later `oldSelectDataset` persistence wrapper were unreachable compatibility debt. They were physically removed; one bounded `renderDatasets() → renderDatasets424()` delegate remains only because older global render maps still eagerly reference the symbol.

Physically retired:

```text
selectDataset / newDataset / saveDataset / editDataset / saveEditDataset / delDataset
oldSelectDataset persistence wrapper
currentDataset helper
two historical dataset-group render bodies
```

```text
product:          feeb98f441bb1fe5d0f8f409a1509c66606e59ef
focused run:      34698742036
validation:       11131ca30c17809e016807aa6c75b0bf203fa6f8
validation run:   34698850495
validation Chrome: 31/31 PASS
cleanup:          a7116811adb26ebe5f0f9e621bf23df1dd1f605f
cleanup run:      34698983278
cleanup Chrome:   31/31 PASS
app.js cache:     42.25.85
```

Permanent proof: `tests/frontend/legacy-dataset-group-owner.test.mjs` plus the existing permanent material-pagination/navigation Chrome suite. One-shot R20i migration artifacts are physically deleted.

Current exact next scope: prove liveness/source order for the remaining old dataset action generation (`uploadImages/autoSplit/buildYolo/checkDatasetQuality/setImageSplit` and historical `importData/doImportData`), then migrate the confirmed-live `stopJob/deleteJob` broad reload path with a focused browser request contract.

### R20j — zero-reference legacy dataset action retirement

Source-wide assignment/reference audit proved five old dataset actions had exactly one assignment and zero call sites. They were physically removed without touching the final dataset route, MaterialPagination runtime or the live import flow.

Physically retired:

```text
uploadImages
autoSplit
buildYolo
checkDatasetQuality
setImageSplit
```

Important boundary: `doImportData` is **live** and intentionally preserved. The final v36 `importData` modal calls it; its success path still broad-refreshes through `await reload()` and is the next migration target.

```text
product:            e6398f7d8ae665079c82d64217c434af4a73073c
focused run:        34699354229
validation:         693a2fa2c3d39378782ac2270a95924eff5ca5ec
validation run:     34699442423
validation Chrome:  31/31 PASS
cleanup:            9c7a3497b9acf69364d83e5cf778ec4139bdbc69
cleanup run:        34699599796
cleanup Chrome:     31/31 PASS
app.js cache:       42.25.86
```

Permanent proof: `tests/frontend/legacy-dataset-action-shell.test.mjs`. R20j one-shot migration artifacts are physically deleted.

### R20k — live v18 import completion scoped refresh

The final v36 import modal still calls the unique live `doImportData` XHR owner. R20k preserved that UI/protocol owner and replaced only the success-path broad `await reload()` with `refreshLabels414(false)` plus `reloadMaterialPage61()` when the user is still on 数据集. The permanent browser contract performs a mocked ZIP upload and rejects project/dataset/image/job/algorithm/bootstrap fan-out.

```text
product:            1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb
focused run:        34700022284 (211/211 frontend unit; focused Chrome 2/2 PASS)
validation:         60775456f3d4c8a441ba58ce65106af114aeebb2
validation run:     34700127243
validation Chrome:  32/32 PASS
cleanup:            f51d44c089b6342398c14bd38c8669747adad48b
cleanup run:        34700252041
cleanup Chrome:     32/32 PASS
app.js cache:       42.25.87
```

Permanent proof: `tests/frontend/v18-import-completion-scope.test.mjs` and `tests/browser/material-pagination-performance.spec.mjs`. One-shot migration artifacts are physically deleted.

Current exact next scope was **Resource Discovery SQLite / FD lifecycle code-level closure**; that code-level slice is now closed below. The separate 30–60 minute production soak remains OPEN / NOT VERIFIED.

### Resource Discovery SQLite lifecycle — code-level CLOSED

A guarded baseline proved the two target defects before migration: reopening `DiscoveryCache` reran schema bootstrap/WAL work, and `_ModelManifest` opened 6 SQLite connections with 0 explicit closes. The same baseline already passed concurrent generation allocation and Linux FD trend, so the migration was kept narrowly scoped.

Migration result:

```text
DiscoveryCache._initialize
→ FileLock(<db>.init.lock)
→ PRAGMA user_version schema gate
→ WAL transition only during single-owner first initialization

DiscoveryCache._connect
→ foreign_keys + busy_timeout only
→ no repeated journal_mode transition

_ModelManifest
→ closing(connection)
→ transaction context only for commit/rollback
→ closing(cursor) for streamed rows
```

Acceptance:

```text
baseline/migration run: 34700801232
old baseline:           2 failed / 2 passed
post-migration focused: 6/6 PASS
product:                8ba4e10db5958204aca3d87779711d8e95f5d83b
permanent CI commit:    5b66ee03e5aaa3af3a2f18a9092f12e303f69937
permanent CI run:       34700900542
Ubuntu:                 PASS
Windows:                PASS
cleanup:                c6ac70b670a6297ccba065854779c10b8ca47cf3
cleanup Frontend run:   34700984963
Real Chrome:            32/32 PASS
```

Permanent proof: `tests/unit/test_resource_discovery_sqlite_lifecycle.py` + `.github/workflows/resource-discovery-sqlite-stability.yml`. One-shot migration artifacts are physically deleted.

**Boundary:** 30–60 minute production soak is still NOT VERIFIED. ZIP/file/subprocess/socket/tempfile/directory iterator/mmap/GPU worker/thread/executor lifecycle is outside this batch. The whole Resource Lifecycle Zero-Point therefore remains OPEN.

Current exact next scope: **Navigation Action Fencing**. Audit stale POST/PUT/DELETE, XHR upload and timer/callback completions so a business mutation may finish after navigation but cannot switch page, render the departed page, open an old modal, or mutate the current-page DOM.

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

### R20c — training-server scoped target refresh

The final live `saveServer` owner is still reached from 训练资源 → 接入服务器. Before R20c it POSTed `/api/train_servers` and then called global `reload()`, whose current final binding is `refreshCurrentPage413`: bootstrap snapshot plus current-page extras. On 训练资源 that meant an unnecessary bootstrap snapshot in addition to `/api/training_options`.

The backend POST returns only the saved server item, while canonical `state.targets` is built by `/api/training_options`. R20c therefore keeps the necessary normalization request but removes the bootstrap fan-out: POST server → GET training_options → replace `state.targets` → local render. The permanent Chrome contract requires bootstrap=0 on this action.

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / run 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14
run:                34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
app.js:             42.25.79
main.mjs:            42.25.84
```

R20/global reload debt remains **IN PROGRESS**; R20c closes only training-server creation refresh ownership.

### R20d — Paddle environment activation scoped target refresh

The final live `detectPaddle` and `quickPaddleDetect` owners are both reached from 训练资源. Before R20d, both successful activation paths called the final `loadAll()` binding after their Paddle POSTs, causing a bootstrap snapshot before the page-specific resource extras. `/api/paddle_env/select` returns the active environment, but canonical training-resource targets still come from `/api/training_options`, so the safe minimal refresh remains a training-options fetch rather than a hand-built local target.

R20d introduces `refreshPaddleTrainingTargets20d()`: manual activation now runs select POST → test POST → training_options GET → replace `state.targets` → local render; quick activation runs detect POST → select POST → training_options GET → replace targets → local render. The permanent Chrome contract requires bootstrap=0 for both actions.

```text
baseline:                    53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration attempt:     34681841986 STOPPED before product commit
                             generated unit had a JS syntax error from Python string escaping
helper-generator fix:        e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:                     d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:           34681905173 PASS
validation:                  a21846c33d79612f9ab4a47e2a69195da29caa3b
full run:                    34681966242
frontend:                    PASS
Real Chrome:                 24/24 PASS
app.js:                      42.25.80
main.mjs:                    42.25.85
```

The failed first migration run did not commit product code; it exposed only the new unit generator escaping defect. R20 remains **IN PROGRESS** pending a zero-point audit of any other proven-live mutation full-refresh owners.

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
training-server-refresh-owner.test.mjs
paddle-resource-refresh-owner.test.mjs
model-config-save-refresh-owner.test.mjs
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

Real Chrome verifies navigation, readiness, stale-request fencing, managed polling, sidebar cleanup, current/historical auto-label canonicalization, persistence/reload, storage route, algorithm/training/material performance, formal-version stability, page/modal file-input beautification, and R20 scoped mutation ownership. Current accepted suite: **28/28** in run `34690924552`; this includes algorithm-version delete focused refresh, model-version publish authoritative-state ownership, training-server/Paddle scoped refresh, model-config/prompt local mutation ownership, and final M4 model-config save/edit local ownership.

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

### R20e — model configuration / prompt mutation local ownership

The zero-point audit found three still-live mutation success paths in 模型配置: `deleteModelConfigV35`, `savePromptTemplateV35`, and `deletePromptTemplateV35`. All three used global `loadAll()` after mutation. The prompt paths also exposed a real correctness bug: the current model-page extras reload model configs but not prompt templates, so a successful prompt save/delete left the visible prompt list stale.

```text
baseline:             afa2bfcb474cc9970129723af5589ab74a26eca7
baseline run:         34683803977 → 1/3 PASS
                       model-config delete PASS
                       prompt save failed to appear immediately
                       prompt delete failed to disappear immediately
first migration run:  34683969019 → unit 3/4; wiring guard escaping only; no product commit
guard fix:            becabf102d10520db52fdac9af1d5238357aa3f3
focused run:          34684037005 → unit 4/4 + Real Chrome 3/3 PASS
product:              febece523b462692cc857431cb901fc5a863d091
validation:           89327ded9da924753f5f900fc3b79e6df353927f
full run:             34684119911
frontend:             PASS
Real Chrome:          27/27 PASS
app.js:               42.25.81
main.mjs:             42.25.86
formal VERSION.txt:   42.24.0
```

Final mutation ownership:

```text
deleteModelConfigV35
  → DELETE model config
  → local state.modelConfigs filter
  → local render

savePromptTemplateV35
  → authoritative POST/PUT response
  → local state.promptTemplates upsert
  → local render

deletePromptTemplateV35
  → DELETE prompt template
  → local state.promptTemplates filter
  → local render
```

Permanent request contracts require zero bootstrap, model-config GET, or prompt-template GET fan-out from these actions. R20/global mutation refresh debt remains **IN PROGRESS** until the next source-order zero-point audit proves no additional live mutation success owner still uses global refresh.

The full R20e Chrome run also logged one non-fatal `sqlite3.OperationalError: database is locked` while initializing the resource-discovery cache. All 27 browser contracts still passed. Treat that as a separate resource-discovery concurrency diagnostic, not as an R20e acceptance failure.


### R20f — live M4 model-config save local ownership

R20f closed the remaining broad refresh on the visible model-configuration save/edit path. The first static source-order audit targeted `saveModelConfig427`, but a temporary Real Chrome runtime diagnostic proved that function is shadowed in the actual UI. M4 first captures its modal owner in `window.__m4OpenModelConfig`; a later compatibility layer textually redefines `openModelConfigModalV35`; the file-tail **M4 final activation** then restores `window.openModelConfigModalV35 = window.__m4OpenModelConfig`. Therefore the final visible save button calls `saveVisionModelM4`, not `saveModelConfig427`.

Before migration, `saveVisionModelM4` performed POST/PUT and then `loadRelated()`, producing the full project/datasets/materials/labels/algorithms/model-config request fan-out. It now treats the sanitized POST/PUT response as authoritative, upserts it into `state.modelConfigs`, closes the modal and renders locally with zero mutation-owned follow-up GETs.

```text
baseline:              dddcd3f1eecf27c5b7447a16939e53473ff1d745
readiness alignment:   da3f3cee7565b75f0a2de926dfdbdb42f7b30ab9
runtime diagnostic:    34690682894 → proved final M4 save owner + broad loadRelated fan-out
product:               c9b7ab44192d38c37753643ee790fc2e089c8598
validation:            94dbebb43d83b1d522ea4e3f6522154417f3e985
full run:              34690924552
frontend:              PASS
Real Chrome:           28/28 PASS
app.js:                42.25.82
main.mjs:              42.25.87
formal VERSION.txt:    42.24.0
```

Permanent proof is `tests/frontend/model-config-save-refresh-owner.test.mjs` plus the Chrome contract `model config save appears immediately without broad related refresh`. Future ownership audits must inspect capture/restore/final-activation semantics in addition to textual assignment order. R20/global mutation refresh debt remains **IN PROGRESS** pending the final-owner zero-point audit.
