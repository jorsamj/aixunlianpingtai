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
latest full code acceptance: 210a9ad1f6271a8a8986db3f223f4813a6cce288
Frontend Runtime run:        34696729028
formal VERSION.txt:          42.24.0
frontend badge:              v42.24.0
app.js cache:                42.25.84
main.mjs cache:              42.25.88
NavigationStability:         422511
```

`34696729028` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。

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

R20g、R20h 已 CLOSED。R20h 已退休旧算法 CRUD 与 shadowed algorithm renderer generations；创建/编辑/删除现在由 414/423/429 稳定 owner 直接 patch authoritative `state.algorithms`，不得恢复 broad `reload()/loadAll()/loadRelated()`。

下一批继续审计剩余 global reload/request debt，优先从数据集 mutation 家族开始，但必须先证明 current renderer/action liveness：

```text
saveDataset / saveEditDataset / delDataset
uploadImages / doImportData / autoSplit / setImageSplit
stopJob / deleteJob
saveAssign
remaining loadAll().then(render) manual refresh handlers
```

规则：先建立 assignment/reference/liveness/semantic 表；确认 live mutation 后，先补永久浏览器请求合同，再改成 authoritative result + local state patch / scoped refresh。被 later owner 完全 shadowed 的 generation 才允许整组物理删除。不得回头重构已经 CLOSED 的 `setPage` / NavigationStability。

R20h 验收：

```text
product:          d58e690ffcc1523f213a65cfc0a57380ffdc571e
focused run:      34696508446 (frontend unit + focused Real Chrome PASS)
validation:       210a9ad1f6271a8a8986db3f223f4813a6cce288
validation run:   34696729028
frontend:         PASS
Real Chrome:      31/31 PASS
app.js cache:     42.25.84
main.mjs cache:   42.25.88
```

一次性 R20h migration helper/workflow 已物理删除；永久 guard 位于 `tests/frontend/legacy-algorithm-crud-owner.test.mjs`，CRUD Real Chrome 合同已并入永久执行的 `tests/browser/algorithm-list-performance.spec.mjs`。

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
