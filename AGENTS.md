# Repository Agent Handoff

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
latest full code acceptance: 9c7a3497b9acf69364d83e5cf778ec4139bdbc69
Frontend Runtime run:        34699599796
formal VERSION.txt:          42.24.0
frontend badge:              v42.24.0
app.js cache:                42.25.86
main.mjs cache:              42.25.88
NavigationStability:         422511
```

`34699599796` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。

**仍是技术债优先阶段；A800 RC 暂缓。** 未取得用户明确授权，不得 merge `main`、修改正式 `VERSION.txt`、tag 或 release。

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

## 下一批准确范围：R20 final zero-point

R20g、R20h、R20i、R20j 已 CLOSED。R20j 通过全局引用证明物理退休了 5 个 zero-reference dataset action owner：`uploadImages / autoSplit / buildYolo / checkDatasetQuality / setImageSplit`。最终 `renderDatasets424 + MaterialPaginationRuntime61` 与 live import owner 均未误删。

下一批准确目标是 **R20k：live v18 `doImportData` completion scoped refresh**。它是当前最终 v36 import UI 仍会调用的真实 owner，成功路径现在仍执行 `await reload()`，不得按 dead shell 删除。

```text
final renderDatasets424
→ importData()（最终 v36 modal owner）
→ doImportData()（唯一 live v18 XHR owner）
→ POST /api/v18/projects/{project}/datasets/{dataset}/import
→ 当前：await reload()   ← R20k 目标

目标语义：
→ 导入成功结果/进度 UI 保持不变
→ refreshLabels414(false)
→ 仅当 state.page === '数据集' 时 reloadMaterialPage61()
→ 禁止 loadAll/loadRelated/reload bootstrap fan-out
```

R20k 必须先加 permanent unit/request contract，并把 Real Chrome 导入成功测试并入现有 `material-pagination-performance.spec.mjs`，避免修改永久 workflow。之后再处理 live `stopJob/deleteJob` broad reload。

R20j 验收：

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
main.mjs cache:     42.25.88
```

永久 guard：`tests/frontend/legacy-dataset-action-shell.test.mjs`。一次性 R20j migration helper/workflow 已物理删除。

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
1. R20 final global reload/request zero-point
2. proven-dead app.js/runtime shell cleanup
3. stale async action fencing / lifecycle zero-point
4. cache-busting unification
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. unified task progress + durable queue productionization
8. resume A800 RC only after the above acceptance gates
```

## 修改与交接要求

- 每批边界清晰，不混入无关重构。
- 旧测试锁定已确认错误旧语义时，应升级合同，不得回退正确代码。
- 未真实执行的测试写 `NOT VERIFIED`。
- 一次性 audit/migration helper/workflow 批次验收后必须物理删除。
- 每批完成后同步 AGENTS.md + 四份 docs 当前 handoff 文档。
