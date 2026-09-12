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
latest full code acceptance: c6ac70b670a6297ccba065854779c10b8ca47cf3
Frontend Runtime run:        34700984963
formal VERSION.txt:          42.24.0
frontend badge:              v42.24.0
app.js cache:                42.25.87
main.mjs cache:              42.25.88
NavigationStability:         422511
```

`34700984963` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 32/32。Resource Discovery SQLite 永久 workflow `34700900542` 已在 Ubuntu + Windows 双平台通过。

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

## 下一批准确范围：Navigation Action Fencing

R20g–R20k 已 CLOSED。Resource Discovery SQLite / FD 本批也已经完成 **代码级关闭**，但只覆盖 SQLite 初始化/连接生命周期，不等于整个 Resource Lifecycle Zero-Point 已关闭。

Resource Discovery SQLite 本批验收：

```text
baseline / migration run: 34700801232
old-code baseline:        2 failed / 2 passed
  - repeated schema/WAL initialization: FAILED as expected
  - _ModelManifest explicit close:      FAILED as expected (opened 6 / closed 0)
  - concurrent generation allocation:   PASS
  - Linux SQLite FD trend:               PASS
product:                  8ba4e10db5958204aca3d87779711d8e95f5d83b
post-migration focused:   6/6 PASS
permanent guard:          5b66ee03e5aaa3af3a2f18a9092f12e303f69937
permanent guard run:      34700900542
Ubuntu:                   PASS (includes /proc SQLite FD trend)
Windows:                  PASS (Linux-only FD test skipped by contract)
cleanup:                  c6ac70b670a6297ccba065854779c10b8ca47cf3
cleanup Frontend run:     34700984963
cleanup Real Chrome:      32/32 PASS
formal VERSION.txt:       42.24.0 unchanged
```

最终代码合同：

```text
DiscoveryCache schema/WAL initialization → FileLock single owner + PRAGMA user_version gate
ordinary DiscoveryCache connection       → no journal_mode transition; per-connection PRAGMA only
DiscoveryCache transactions              → deterministic closing + explicit commit/rollback
_ModelManifest connections/cursor        → deterministic closing
permanent cross-platform CI              → .github/workflows/resource-discovery-sqlite-stability.yml
permanent test                            → tests/unit/test_resource_discovery_sqlite_lifecycle.py
```

**仍 OPEN / NOT VERIFIED：** 30–60 分钟真实生产 soak；以及 ZIP/file/subprocess/socket/tempfile/directory iterator/mmap/GPU worker/thread/executor 等其他资源生命周期。本批不得被描述为整个 Resource Lifecycle Zero-Point CLOSED。

按用户授权，SQLite 代码级闭环到这里先停，不让生产 soak 阻塞主线。下一批切到 **Navigation Action Fencing**：审计 POST/PUT/DELETE、XHR upload、setTimeout 与业务 callback 的 stale completion，确保动作可在后台完成，但离开来源页后不得切页、重绘旧页、弹旧 modal 或改当前页 DOM。优先补 Real Chrome：A slow mutation → B/C navigation → mutation completes，最终页面必须保持用户最后选择。

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
1. Navigation Action Fencing / stale mutation UI side-effect zero-point
2. R20 final global reload/request zero-point
3. External Algorithm Catalog read-only boundary
4. Resource Lifecycle production soak + remaining non-SQLite resource classes
5. ZIP 10k / Training Progress v2 / GPU Performance Tuner / Deployment Artifact E2E
6. app.js / app.py normalization + cache-busting / semantic naming / deterministic cleanup
7. technical-debt final zero-point + backend regression
8. A800 RC only after acceptance gates
```

## 修改与交接要求

- 每批边界清晰，不混入无关重构。
- 旧测试锁定已确认错误旧语义时，应升级合同，不得回退正确代码。
- 未真实执行的测试写 `NOT VERIFIED`。
- 一次性 audit/migration helper/workflow 批次验收后必须物理删除。
- 每批完成后同步 AGENTS.md + 四份 docs 当前 handoff 文档。
