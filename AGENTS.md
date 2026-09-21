# Repository Agent Handoff

## 2026-09-21 live override — OSS/新畅联第一批 Version/Weight 合同收口

当前工作仍在 `feature/external-algorithm-publishing`。远端紧急修复 `2ff431a7` 已先安全同步；该修复只隔离 keyring DBus 测试中的既有 Headless Secret fallback，不得重复修改生产 Keyring 逻辑。

OSS + 新畅联 durable publish 第一批只收紧 Version/Weight 合同：`versionNo` 来自本地 durable `version_no`；UNKNOWN 恢复必须同时匹配 `versionName + versionNo + 已绑定 analysisId`，product/analysis list 只作为查询路径；候选多条或字段不完整时置 UNKNOWN 并禁止 POST。Weight 创建五字段缺一不可；恢复严格匹配 `fileName + computePlatformId + 非空 chipCode`，远端有 `filePath` 时还要匹配长期 URL。Weight 前置字段在远端 Version 创建前检查，避免留下空 Version。`code=0` 是主合同，`code=200/SUCCESS` 继续保留为 legacy compatibility / OPEN。

最小验证：新增合同 15 passed（含 product/analysis 同 ID 去重与 FAILED 修复后重试）；直接影响回归 9 passed；AST/whitespace 检查通过。未跑全量 pytest、integration、浏览器或 Actions。第二批 OSS 尚未开始；开始前必须遵守设计稿的 prefix 单 owner 与第三批字段 owner/migration gate。

最高优先级细节见 `docs/CODEX_HANDOFF_2026-09-21.md` 顶部最新节；`VERSION.txt` 仍为 `42.24.0`。

## 2026-09-21 live override — cache-first page loading closed locally

当前长期分支是 `feature/external-algorithm-publishing`；接手时仍需先核对远端 HEAD。最新性能闭环提交：

- `9fff42df`：`/api/v53/bootstrap/snapshot` 普通缓存命中不再计算 project counts；authoritative rebuild 同一请求每项目只计算一次 counts 并替换 `_V53_BOOTSTRAP_SNAPSHOT`。标签管理 GET 改为 `MaterialRepository.label_usage()` 对既有 `label_counts` 做 SQLite 只读聚合，不再全量水合素材、逐图读 annotation 或在 GET 中 patch。
- `2e3a726b`：启动只消费一次预构建 snapshot；仅显式刷新使用 `refresh=true`。`extras412()` 不再重复 jobs/model_configs；算法、训练任务、数据集、服务节点继续由各自 runtime/PollRegistry 刷新。数据集 v61 当前 48 条先提交并绘制，状态 totals 后补；不加载全量素材。

浏览器同场景实测：冷启动 `10 requests / 2 snapshots / refresh=true / ~998ms` → fresh cache `4 / 1 / false / ~542ms`，snapshot 过期触发页面 owner SWR 时 `8 / 1 / false / ~353ms`；数据集 `6 requests / ~145ms` → `4 / ~27–30ms`；服务节点保持单一 `/api/v63/service-nodes`。定向 API 5/5、前端 12/12、Network/分页/导航 browser smoke 4/4 通过。未跑全量 pytest/integration，未等待 Actions，未 merge/tag/release/deploy，`VERSION.txt` 仍为 `42.24.0`。

本节与 `docs/CODEX_HANDOFF_2026-09-21.md` 顶部最新节优先于本文后面的历史 branch/NEXT。不要恢复普通导航的 broad snapshot refresh，也不要新增第二套 cache/polling/truth。

本仓库由 Codex、ChatGPT 和人工开发共同维护。开始修改前必须先读取实际分支/HEAD，不得只根据 README 或 `VERSION.txt` 推断开发状态。

## 必读顺序

1. `docs/TECH_DEBT_CLOSURE_V42_25.md` — 当前技术债关闭总账 / 第一权威来源。
2. `docs/CODEX_CURRENT_STATE.md` — 当前代码验收点、owner、下一批准确范围。
3. `docs/frontend-legacy-audit.md` — classic `static/app.js` override / owner 审计。
4. `docs/FRONTEND_OWNER_MAP_V42_25.md` — 前端 owner map。
5. 其余历史 handoff/spec；冲突时以实际代码 + 上述当前文档为准。

修改前确认 live branch/HEAD、`git diff main...HEAD` / `git log main..HEAD` 或等价 GitHub API。

## 当前开发状态

```text
stable branch:               main
active branch:               refactor/frontend-runtime-stabilization
latest full code acceptance: 60305921402204e77b8e7ed4ec8e576d9f857c4b
Frontend Runtime run:        34733035739
formal VERSION.txt:          42.24.0
frontend badge:              v42.24.0
app.js cache:                42.25.95
main.mjs cache:              42.25.92
NavigationStability:         422512
```

`34730512607` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 33/33。Navigation Action Fencing 永久 workflow `34730512602` 全绿；Resource Discovery SQLite 永久 workflow `34700900542` 继续保持 Ubuntu + Windows 双平台通过。

**技术债清理主线已按用户要求暂停；后续优先真实功能、性能、数据完整性与生产验收。A800 RC 是否推进由后续任务决定。** 未取得用户明确授权，不得 merge `main`、修改正式 `VERSION.txt`、tag 或 release。

## 当前前端 owner 状态

### Training

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /api/v12/projects/{project_id}/train/start
```

历史 mirror `trainingLabelSelected / trainSplitV3 / train429Selected / train428AlgorithmId / train428Config / trainingDraftFromLegacyState` 已退休，不得恢复。

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

旧 timer、`setupPagePolling` shell、creation-wrapper/adoption compatibility 均已退休。

### Navigation — CLOSED

`static/app.js` 的 classic `setPage` owner family 已清零。以下均已物理退休：

```text
set423Base / setBase424
V37 duplicate baseSetPage
oldSetV39 / oldSet42 / set422Base
v34/v35/v42.4 direct setPage
v42.7 direct alias setPage
setPageReady414
baseSetPage417
initial bootstrap function setPage(p){state.page=p;render()} / window.setPage=setPage
```

最终 owner：

```text
NavigationStability
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry before/after
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page): state.page=page; render()
  → persistNavigationState
```

永久 CI 禁止 `static/app.js` 再出现 `window.setPage=` classic owner。Real Chrome 已验证 inline 菜单与 programmatic `window.setPage`、readiness、sidebar、polling、alias、persistence 均正常。

## 当前边界：技术债清理 PAUSED

除非出现真实功能故障、明显性能问题、数据完整性风险或发布验收阻断，不再继续 dead-code / zero-point / 命名 / cache-busting 类清理。剩余债务保留为 OPEN/DEFERRED，不影响当前功能使用时不主动扩展。

### 当前产品主线 — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.
- **ZIP 10k acceptance**: focused CI created a real ZIP with **10,000 image members** and passed the v19 create/scalability contract plus existing server-import/storage regressions. The permanent legacy unit guard was migrated, not weakened (`27654cba1fb3406567a40754904531c2b53aa53f`), and the permanent Chrome material/import contract was migrated to the real v19 sequence (`60305921402204e77b8e7ed4ec8e576d9f857c4b`): create → start → list polling → terminal done → labels/current paged-material scoped refresh, with an explicit assertion that no `/api/v18/` request or broad reload occurs. Final Frontend Runtime `34733035739` passed all frontend unit guards and Real Chrome **33/33 PASS (53.9s)**; Action Fencing `34733035761` PASS.
- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.95`; `main.mjs` cache remains `42.25.92`. No merge/tag/release.

**Current next product scope: ZIP 10k processing-phase scalability audit. The UI/background-state amplification is closed, but this does not yet prove that importing 10,000 valid images with annotations is fast enough. Benchmark the real worker path and inspect per-image image decode/copy, AnnotationRepository writes, progress cadence, v50 buffered material commit, label/project writes and finalization. Optimize only measured hotspots; preserve YOLO/COCO/VOC semantics, project serialization, data integrity and cross-platform behavior.**

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
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

永久 source contract：`tests/frontend/shadowed-model-config-generations-r20n.test.mjs`；最终 M4 行为继续由 `tests/browser/navigation-action-fencing-r2.spec.mjs` 与现有 Action Fencing workflow 覆盖。一次性 R20n migration helper/workflow 已物理删除。

**按用户要求，从 R20n 起技术债清理主线 PAUSED。** 剩余 R20 global reload/request zero-point、stale-async final scan、cache-busting、历史 dead code、命名/结构归一化、Resource Lifecycle production soak 等均保持 OPEN/DEFERRED，不宣称 CLOSED；除非出现真实功能故障、明显性能问题、数据完整性风险或发布验收阻断，否则不得为了“代码更干净”继续展开技术债批次。

### R20m — shadowed v423 algorithm CRUD generation retirement CLOSED

Source-order + Real Chrome 已证明旧 v423 create/edit generation 从运行时不可达：删除前 `algorithm-list-performance.spec.mjs` 已完整通过，真实 UI 一直解析到后面的 stable 414 owner。R20m 因此没有“迁移 broad refresh”，而是物理删除旧 `openNewAlgorithm423(async) / saveNewAlgorithm423 / editAlgorithm423(old modal) / saveEditAlgorithm423` generation；后面的 `saveNewAlgorithm414 / saveEditAlgorithm414` authoritative local-state owner 保持不变。

```text
baseline:                  243bcb1b17074848d91c2c9c64d47dbed54e5e9b
baseline + migration run: 34724242632
product:                   71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e
cleanup / acceptance:      40a87bf70402dccfc0387950b6856a561ce1ebe1
Frontend Runtime:          34724354775
full Real Chrome:          33/33 PASS
Navigation Action Fencing: 34724354790 PASS
formal VERSION.txt:        42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

永久 source contract：`tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`；行为合同复用现有 `tests/browser/algorithm-list-performance.spec.mjs`。一次性 migration helper/workflow 已物理删除。**R20m CLOSED；R20 全局 reload/request zero-point 仍为 IN PROGRESS。**

### R20l — source-import terminal completion scoped refresh CLOSED

最终 live `refreshSourceImportTasksV36()` 在地址读取任务进入 terminal 状态后，已从 broad `loadRelated()` 改为只刷新标签 schema 和当前可见的数据集分页素材。任务 active 期间的 1.8s polling cadence、source-import API 和任务列表 UI 均保持不变。

```text
baseline + migration run: 34723694735
product:                  f260127d2d41281bc1d996a172e7d4290536f24c
permanent Chrome guard:   b17bd0c33bfb99e5557fc245a89a6c4444a8257e
cleanup / acceptance:     f8356bcf5ec1ea128fb38db2820df38146b48cfd
Frontend Runtime:         34723808299
full Real Chrome:         33/33 PASS
Navigation Action Fencing:34723808298 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

永久合同：`tests/frontend/source-import-completion-scope.test.mjs` + `tests/browser/source-import-completion-scope.spec.mjs`；browser spec 已进入唯一长期 `Frontend Runtime Stabilization` Chrome 清单。一次性 R20l migration helper/workflow 已物理删除。**这只关闭 source-import terminal completion；R20 全局 reload/request zero-point 仍为 IN PROGRESS。**

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
app.js cache:                42.25.95
main.mjs cache:              42.25.92
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

**边界：Navigation Action Fencing R1 + R2 已 CLOSED，但全局 stale-async zero-point 仍为 IN PROGRESS。** R2 已关闭最终 M4 Model Config、清洗确认和 v60 AI review completion；upload/ZIP/deployment/timer-callback completion family 仍留给 final scan，不能宣称 stale async UI side effect 全局为 0。

Resource Discovery SQLite 仍保持 **CODE-LEVEL CLOSED / production soak OPEN**；30–60 分钟生产 soak 和非 SQLite resource classes 不因本批改变状态。

## 不得回退的核心合同

- Windows 开发与 NVIDIA Linux 生产必须共用跨平台代码；禁止写死盘符/Windows-only shell/process。
- 已有素材、标注、算法版本不得因升级清空、移动或重新编号。
- AnnotationRepository 是 GT authority；`unannotated` / `annotated` / `confirmed_empty` 语义必须保持。
- 0 框普通保存不得静默变负样本；负样本必须显式确认。
- 首训标签只能来自本次精确素材与用户明确选择；不得继承母模型类别。
- 迭代只继承上一成功且 artifact-verified 的 trainable version；label schema 旧 ID 不重排。
- Train/Validation/Test 按不可拆分 Component 划分并保留 leakage guard。
- 试验/评测图片送模型时不得携带任何 GT。
- Task Runtime 必须保持 lease/generation/PID-create_time-command-hash fencing。
- `batch`、`workers=0`、`cache=false` 等显式用户参数不可被 Auto 偷改。
- `state.page` 是当前页面 authority；stale async completion 不得覆盖当前页面。
- 页面 polling 必须有 lifecycle cleanup；优先局部 DOM 更新，禁止周期性全页重绘破坏交互状态。
- 不得通过降低/删除 duplicate-request、race、performance、Real Chrome 测试换绿灯。

## 当前后续优先级

```text
1. 技术债清理 PAUSED；仅在真实功能/性能/数据/发布阻断时恢复
2. Unified Task Progress + Durable Queue Runtime productionization（按后续产品任务推进）
3. Navigation Action Fencing final scan — DEFERRED，除非出现真实 stale-async 故障
4. External Algorithm Catalog read-only boundary
5. Resource Lifecycle production soak + remaining non-SQLite resource classes
6. ZIP 10k / Training Progress v2 / GPU Performance Tuner / Deployment Artifact E2E
7. app.js / app.py normalization + cache-busting / semantic naming / deterministic cleanup
8. technical-debt final zero-point + backend regression
9. A800 RC only after acceptance gates
```

## 修改与交接要求

- 每批边界清晰，不混入无关重构。
- 旧测试锁定已确认错误旧语义时，应升级合同，不得回退正确代码。
- 未真实执行的测试写 `NOT VERIFIED`。
- 一次性 audit/migration helper/workflow 批次验收后必须物理删除。
- 每批完成后同步 AGENTS.md + 四份 docs 当前 handoff 文档。
