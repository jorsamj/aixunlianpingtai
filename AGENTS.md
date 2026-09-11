# Repository Agent Handoff

本仓库由 Codex、ChatGPT 和人工开发共同维护。开始修改前必须先读取实际分支/HEAD，不得只根据 README 或 `VERSION.txt` 推断开发状态。

## 必读顺序

1. `docs/TECH_DEBT_CLOSURE_V42_25.md` — **当前技术债关闭总账 / 第一权威来源**。
2. `docs/CODEX_CURRENT_STATE.md` — 当前代码验收点、owner、下一批准确工作范围。
3. `docs/frontend-legacy-audit.md` — classic `static/app.js` 的历史 override / owner 审计。
4. `docs/FRONTEND_OWNER_MAP_V42_25.md` — 前端 owner map。
5. `docs/codex-handoff.md`、`docs/codex-handoff-v42.25.md` — 历史上下文；冲突时以实际代码 + 当前总账为准。
6. `docs/superpowers/specs/2026-09-11-v42.25-training-data-contract-design.md`
7. `docs/superpowers/specs/2026-09-11-v42.25-task-runtime-fencing-design.md`
8. `docs/superpowers/specs/2026-09-11-training-resource-contract-fix.md`
9. `docs/superpowers/specs/2026-09-11-negative-sample-contract.md`
10. `docs/superpowers/specs/2026-09-11-training-label-contract.md`
11. `docs/superpowers/specs/2026-09-11-navigation-stability.md`

修改前确认 live branch/HEAD、`git diff main...HEAD` / `git log main..HEAD` 或等价 GitHub API。handoff 文档可能比分支 HEAD 少最后几个文档 commit。

## 当前开发状态

```text
stable branch:               main
active branch:               refactor/frontend-runtime-stabilization
latest full code acceptance: f6e71c05d35b1a39b0b79e1b652cf901044c68bd
Frontend Runtime run:        34653776200
formal VERSION.txt:          42.24.0
frontend badge:              v42.25.0-dev
app.js cache:                42.25.56
main.mjs cache:              42.25.57
NavigationStability:         422510
```

`34653776200` 已通过：syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome 12/12。

**当前仍是技术债优先阶段；A800 RC 暂缓。** 未取得用户明确授权，不得 merge `main`、修改正式 `VERSION.txt`、tag 或 release。

## 当前前端 owner 状态

### 训练

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /api/v12/projects/{project_id}/train/start
```

以下历史 mirror 已退休，不得恢复：

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

旧 timer、`setupPagePolling` shell、creation-wrapper/adoption compatibility 均已退休。

### Navigation

已物理退休：

```text
set423Base
setBase424
V37 duplicate baseSetPage wrapper
oldSetV39
oldSet42
set422Base
v34 persistence direct setPage
v35 plain direct setPage
v42.4 plain direct setPage
v42.7 direct auto-label alias setPage
setPageReady414 startup-readiness wrapper
baseSetPage417 mobile-sidebar wrapper
```

当前 live chain：

```text
initial bootstrap setPage binding
→ NavigationStability final coordinator
   ├─ normalizeNavigationPage()
   ├─ PageRequestScope / navigation epoch
   ├─ PollRegistry before/after
   ├─ waitForNavigationReady() / __v53InitPromise
   ├─ beforeInvokeNavigation() / mobile sidebar close
   └─ ui-state.js persistence
```

Real Chrome 已锁定：
- stale previous-page request 不得跳回旧页面；
- 页面离开后 managed polling 停止；
- 最终导航关闭 mobile sidebar/backdrop；
- 页面选择持久化并在 reload 后恢复；
- legacy `自动标注` canonicalize 为 `自动标注及清洗`；
- 启动 snapshot pending 时，导航意图可建立但页面不得提前切换；
- snapshot ready 后只完成实际导航并持久化请求页。

### 下一批准确范围

只处理初始 bootstrap `setPage`：

```js
function setPage(p){state.page=p;render()}
window.setPage=setPage;
```

已确认：`NavigationStability` 当前仍 capture 它作为 actual page mutation/render predecessor；`window.__clInit` 启动流程不依赖它，而是直接 `render()`。

迁移规则：

```text
1. NavigationStability 新增 named performNavigation/applyPage hook。
2. main.mjs 通过 hook 明确执行 state.page=page + final render()。
3. configured named hook 与 classic predecessor 不得同时 mutate/render，必须保持一次 render。
4. runtime 在没有 classic predecessor 时仍必须安装 window.setPage。
5. unit + Real Chrome 双 owner 等价后才能删除 bootstrap function/binding。
6. 删除后永久 guard 必须反转为 bootstrap binding 不得回归。
```

## 不得回退的核心合同

- Windows 开发与 NVIDIA Linux 生产必须共用跨平台代码；禁止写死盘符、反斜杠路径、Windows-only shell/process 流程。
- 已有素材、标注、算法版本不得因升级被清空、移动或重新编号。
- AnnotationRepository 是 Ground Truth authority；MaterialRepository 标注字段只是 searchable projection。
- `unannotated`、`annotated`、`confirmed_empty` 语义不同；`confirmed_empty` 是合法负样本。
- `annotation_scope` 属于 Ground Truth / Training Snapshot 合同，不得只保存 boxes。
- 普通 0 框保存不得静默创建负样本，必须显式“确认无目标”。
- `confirmed_empty` 即使 `box_count=0` 仍属于正式已标注素材。
- 项目标签库只是业务标签目录，不等于某算法 label schema。
- 首次训练标签只能来自本次精确已选素材并由用户明确选择；不得继承母模型类别。
- 版本迭代必须继承上一成功、可训练版本 `label_schema`；新标签只能明确追加。
- 历史版本缺 `label_schema` 时只能从该版本训练任务 `snapshot.json` 恢复；无法恢复必须 fail closed。
- 算法 `class_id` 是 task/model-local：首次连续 `0..N-1`，迭代旧 ID 不重排，新类别只能追加。
- Train / Validation / Test 按不可拆分 Component 划分，并保留 leakage guard。
- same SHA + same normalized GT：训练时 canonicalize，不删除素材记录。
- same SHA + different normalized GT：必须 `duplicate_annotation_conflict`。
- Training Snapshot v3 保留 annotation state/scope/hash 和 duplicate exclusion audit。
- 试验/评测图片送入模型时必须是不带 GT 的原图；任何 ground truth 不得泄漏给模型推理路径。
- Task Runtime 旧 execution 在 lease/generation 失效后不得 finish、发布 artifact 或与新 execution 并发占同一资源。
- 进程恢复必须 PID + create_time + command hash 证明身份；无法证明 fail closed。
- 显式正整数 `batch` 是 Auto 资源策略硬上限；`batch=-1` 才是明确自动。
- `cache=false` 是权威关闭；Auto 不得改成 disk/ram。
- Auto 不得增加用户指定 workers；`workers=0` 必须保持单进程加载。
- `state.page` 是当前页面唯一权威；页面切换推进 navigation epoch。
- 异步操作在 `await` 后若 navigation epoch 已变化，必须视为 stale，不得覆盖当前 `#view`。
- 页面级轮询必须随生命周期清理；后台刷新优先局部 DOM，不得周期性全页重绘破坏表单/滚动/选择状态。
- 不得通过降低/删除 duplicate-request、race、performance、Real Chrome 测试来换绿灯。

## v42.25 主要实现位置

训练数据 / snapshot：
- `platform_core/training_splits.py`
- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`

负样本：
- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`
- `platform_core/training_tasks.py`
- `static/modules/annotation.js`
- `static/modules/negative-samples.js`

训练标签 / submit：
- `platform_core/training_label_tasks.py`
- `static/modules/training-labels.js`
- `static/modules/training-draft.js`
- `static/modules/training-draft-runtime.js`
- `static/modules/training-submit.js`

导航 / polling：
- `static/modules/navigation-stability.js`
- `static/modules/ui-state.js`
- `static/modules/page-request-scope.js`
- `static/modules/poll-registry.js`
- `static/main.mjs`

Task Runtime fencing：
- `platform_core/task_runtime/fenced_repository.py`
- `platform_core/task_runtime/process_control.py`
- `platform_core/task_runtime/worker.py`
- `platform_core/task_runtime/scheduler.py`
- `platform_core/deployment/conversion_tasks.py`
- `task_worker.py`

## 当前后续优先级

```text
1. initial bootstrap setPage migration
2. remaining renderer override owner audit / obsolete layer deletion
3. proven dead app.js + global reload/request debt
4. cache-busting unification
5. MutationObserver/timer/fetch/render/setPage zero-point scan
6. semantic naming + deterministic tests + docs
7. technical-debt zero-point scan
8. resume A800 RC
```

## 修改与交接要求

- 每批修改保持边界清晰，不混入无关重构。
- 代码修改必须补对应回归；旧测试锁定已确认错误的旧语义时，应升级合同而不是回退正确代码。
- 测试没有真实执行时必须写 `NOT VERIFIED`，不能把“新增测试文件”当作“测试通过”。
- 一次性 audit / migration helper / workflow 在批次验收后必须物理删除。
- 每批完成后同步：`TECH_DEBT_CLOSURE_V42_25.md`、`CODEX_CURRENT_STATE.md`、`frontend-legacy-audit.md`、`AGENTS.md`。
