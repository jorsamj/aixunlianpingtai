> **2026-11-14｜P0-06C 明确延期；下一专项 P1 20 万素材选择器性能审计**：用户决定真实生产训练任务的 20k～30k 冻结引用→POST→Prepare→Snapshot→portable bundle→Worker 数据/GT 只读对账以后再做；当前 **P0-06C=DEFERRED/NOT VERIFIED**，不得自动接入 A800/4070、执行训练或标完成。P0-06B 正样本增强提交 `e625ace894ba` 的 Linux/Windows CSC 33/33 均已通过；本次核 CI 时全仓 **21/22 成功、1 项运行中、0 失败**，最终状态必须按准确 SHA 再查。下一步优先复用现有 Chrome 21 次选择器渲染/Long Task/请求计数与 200k 分页/20k–30k 冻结模拟测试，审计打开、筛选、翻页、批量确认的实际瓶颈，证据不足不改代码；不得重构 Vue/MySQL/Worker 或以隔离 P95 冒充生产 P95。范围和接续条件见 [专项接续决议](./2026-11-14-p0-06c-deferred-p1-picker-performance-next.md)。

> **2026-11-14｜P0-06B 正样本自动增强与 portable Worker 输入合同回归（新 SHA CI 待核）**：基线 `99d9bd9e387d` 的 Actions **22/22 成功**。延续 P0-06A，仅在既有 `tests/unit/test_training_robustness.py` 新增 person/smoke 多类别有框样本、Train/Val/Test 四图、Train 两原图生成四派生图、YOLO 坐标逐项对比、数据清单数量与哈希、远程训练包消费合同、确定性重建与篡改保护的 Python 回归；**不修改业务代码/GT/Worker/生产**。现有 20k 清单单测及 20k/30k 模拟浏览器测试已有证据，但真实 20k/30k 正式素材→Worker 现场数量对账仍未闭环。[专项记录](./2026-11-14-p0-06b-positive-augmentation-bundle-evidence.md)。准确新 SHA CI 待核。

> **2026-11-14｜P0-06A 训练素材冻结引用→小范围批选替换精准修复（新代码 CI 待核）**：已核实基线 `26c09c8ed808` 的 GitHub Actions **22/22 success**（Chrome 第一分片同 SHA 重跑通过）。源码发现从 22,015 张旧 `trainSelectionRef` 冻结切换到新的 <=2,000 张筛选批选时，旧 `picker.reference` 未清空，确认分支优先提交旧引用，导致新批量 ID 不入草稿。本次仅在新显式批量结果通过请求身份和全部修订核验后原子替换旧引用；追加实际 runtime 选材→确认→草稿回归。已完成只读审计：Server 清单 count/SHA256、Prepare selected/effective/pending/test 合同、Train-only CSC 派生图链；**20k 正式 GT 现场、不同分辨率自动生成与真实训练 Worker 验收仍未完成**。见 [P0-06A 专项](./2026-11-14-p0-06-selection-ref-replacement-and-train-input-audit.md)。准确新代码 SHA CI 待验。

> **2026-11-14｜P0 固定 GPU + AUTO 资源执行时决议（准确新 SHA CI 待核）**：基线 `ba051cb24f39` 审计确认：`AUTO+cuda:N` 提前冻结 Batch/Workers/Cache，GPU 暂忙可在正式调度前失败。本轮将既有延迟决议合同精准扩展至指定 GPU，覆盖准备阶段、节点级准入器、训练执行校验；不改手动配置、CPU、GT、GPU 预约身份/租约与生产环境。新增 GPU0/GPU1 等待→恢复预约、无遥测、误用延期标记回归。**准确代码 CI 和真实 GPU/GT 现场验收待核。** [专项记录](./2026-11-14-p0-pinned-gpu-auto-deferred-resource-resolution.md)。

> **2026-11-14｜P0 训练准备 GPU 可见设备索引修复（代码提交 CI 22/22 全绿）**：基线 `5791e5c86ed1` 上确认两处确定性 Bug：NVML 原始 `physical_index=0` 经 `or -1` 被误判不可用；自动保守 GPU 采样的物理 1 在缺失 `logical_cuda_index` 时被错映射为 `cuda:0`。复用既有调度器 `_cuda_index`，兼容零索引、双卡、`CUDA_VISIBLE_DEVICES` 数字/UUID 掩码并剔除不可见 GPU；新增 8 场景隔离 Python 回归。**只改训练准备选择及测试，不改 GPU 预约/Worker/GT/数据库/生产**。固定 GPU + AUTO 提前决议另列后续审计。专项记录见 [GPU 索引修复](./2026-11-14-p0-training-prepare-cuda-visible-index-fix.md)。修复代码 `bed687dde99f` 的准确 GitHub Actions **22/22 完成且成功**（两组远程训练 Windows/Ubuntu/Loader、前端 Chrome 4/4 Job 成功）；**生产实机、排队后自动资源重决议和正式 GT 仍未验收**。本次仅更新文档，文档新 SHA 的 CI 另核。

> **2026-11-13｜P0 批量请求与复选框竞争的最小保护（CI 待核）**：基线 `6b6bf11b6928b548c9323018b08bc6f3356e69c0` 已核准确 GitHub Actions **37/37 success**、Frontend Node **1664/1664**。进一步审计确定 `syncPickerActions()` 只锁定批量/确认按钮，`toggle()` 没有 `bulkPending` 守卫，批量等待时仍可勾选/取消，导致显式 ID 与冻结引用被并发改写。仅新增当前页复选框临时锁与迟到事件防护；原禁用策略不会被解锁；卡片重绘后续锁；新增 Node 真实函数分支回归、延迟 HTTP 的真实 Chrome 场景，沿原入口缓存数字合同改到 `42.25.606`。**不引入框架/二套状态、不动 GT/Worker/数据库、不做生产部署或巨量重复压测**。专项详见 [inflight-checkbox-guard](./2026-11-13-p0-training-picker-inflight-checkbox-guard.md)，准确新 SHA CI 待查。

> **2026-11-13｜P0 跨筛选批量全选超限的显式选择丢失保护（本轮 CI 待准确 SHA 核）**：基线 `b4ad738bfe440d440971a1590644bfeba0f148cb` 的完整 GitHub Actions **37/37 success**，Node **1663/1663**。继续只读检查时，发现已有逐项选择时对超过 50,000 张的「全选筛选结果」调用 bulk-selection 会收到 422，客户端随即自动冻结新范围并执行 `picker.selected.clear()`，将早先其他筛选中逐项选择的素材静默丢失。隔离调用复现：选中 1 项、超限 60,000 项，回退生成新的 selection_ref，旧选择会被覆盖。本轮仅在现有 `freezeReference()` 增加存在显式选择时的 fail-closed 守卫，提供清空并重新冻结的明确提示；无显式选择的正常大范围回退保持不变。新增真实函数分支 Node 回归与原入口 42.25.605 数字缓存合同同步；未修改 GT、训练 POST、Worker、SQLite/调度。**该修复仅防止越限选择丢失，不代表完成生产 20k/30k 素材+GT 全链路验收。** [专项记录](./2026-11-13-p0-training-selection-overcap-union-guard.md)。

> **2026-11-13｜P0 角色边界首次 CI 的缓存守卫补修（新 SHA 待核）**：业务提交 `34b75a1227061f6fd20636ecec7e009d17a1880e` 的 Frontend Runtime Stabilization/frontend **1663 项中 1652 通过、11 失败**。新增 `open(role)` 三角色回归及未知总数跨页选择回归均成功；11 项失败来自 main.mjs 缓存参数与 app.js/styles.css 入口同版本数字合同及原测试断言不一致。补修将三个主入口、训练选择器模块导入缓存统一为 `42.25.604`，仅同步精确版本断言，不放宽测试。准确补修 SHA/CI 待核。详见 [专项](./2026-11-13-p0-training-picker-freeze-role-boundary.md)；不改 GT/Worker/训练创建合同或生产环境。

> **2026-11-13｜P0 训练冻结引用的角色边界最小修复（准确新 SHA CI 待核）**：基于 `b1ac71b1df9eea2cf230bcba3371279e7fc8258b` 的只读源码复现：训练冻结约 22,015 张时，「增强原图」选择器错误继承 train selection_ref，后续分页以 `role=robustness` 调用 selection-membership；后端只接受 train/test，导致增强选材读取失败。修复将冻结引用限制为 train 角色；增加实际 open(role) Node 回归与相关静态缓存键。**不动**大规模训练冻结 Owner、GT、数据库、Worker、任务提交。注意 main.mjs 实际传入的默认 `admissionMode` 为 background（仅显式 MC_TRAIN_ADMISSION_MODE=synchronous 才同步），此前误读模块默认值已更正。未获得正式 GT 20k/30k 现场验收，不等于整体 P0 解决；[专项详见](./2026-11-13-p0-training-picker-freeze-role-boundary.md)。本记录由当前业务改动一起提交，准确新 SHA 的 GitHub CI 需另核。

# 畅联云算法训练平台｜前后端性能优化与渐进式模块化治理｜当前进度与接续任务书

## 最新进度（2026-11-13，覆盖下文历史阻断快照）

> **2026-11-13｜13C-04F 代码/CI 验收已关闭；新会话转入 P0 训练素材正式闭环**：写本次接续记录前的唯一长期分支 HEAD `4b1f48327b1fd8d38ec1294692cf419405a900d3`，该**仅文档**提交的准确 GitHub Actions **21/21 全部成功**；最近一次有业务/测试代码改动的提交 `3aecc232b607913973a4ed53a30fbea870643d89` 亦 **21/21 工作流成功**（前端单测 1662/1662、Chrome 382/382，包含转换监听 30 次无关 DOM 变化零新增所测全局扫描）。13C-04D 质量中心懒加载、04E 组件检测懒加载、04F-01 转换主逻辑只读审计、04F-02 MutationObserver 变更范围收敛都已按**代码与隔离测试**收尾，不能称真实生产 P95 或正式 GT 已验收。**下一会话优先 P0：20k–30k 训练素材冻结 → 草稿 → POST → TRAINING_PREPARE Worker 引用和正式 GT 数量/标签核验；其次 200k 素材性能、报告/弹窗 P95；暂不再拆 v39/v41 或改 Vue/MySQL/Redis。** 完整新进度快照：[PROJECT_NEXT_SESSION_HANDOFF_2026-11-13.md](./PROJECT_NEXT_SESSION_HANDOFF_2026-11-13.md)；可复制新会话提示词：[NEW_CHAT_PROMPT_2026-11-13.md](./NEW_CHAT_PROMPT_2026-11-13.md)。本次只补文档，不修改业务/测试代码、GT、数据库、Worker 或生产服务器。**本次新文档提交自己的准确 CI 应重新查询，不预写通过。**

> **2026-11-13｜13C-04F-02 CI 最终结论（准确代码 SHA `3aecc232b607913973a4ed53a30fbea870643d89`）**：最新业务/测试代码对应 **21/21 GitHub Actions 工作流成功，0 失败，0 未完成**；Frontend Runtime Stabilization 4/4 Job 成功（frontend 1662/1662 单测、Chrome 三分片合计 382 项成功：131+126+125）。Chrome 专项验证 30 次无关 childList 更新不触发新增全局转换根扫描，异步插入转换历史/编辑器/源加载提示仍能完成装饰。这证明局部 DOM 扫描治理与被测路径的回归通过，**不代表真实生产环境 P95 提速**。证据：[准确代码 CI](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43435335641)。目前 13C-04F-02 可按“代码与隔离 Chrome 验收完成”关闭；A800/4070、真实用户性能和后端系统现场验收继续保持未关闭。下一步先做性能指标对照，暂不拆 v39/v41 转换主逻辑。

> **2026-11-13｜13C-04F-02 转换展示 DOM 观察范围优化**：在保持原转换逻辑/弹窗/任务 Owner 不动的前提下，仅筛选 `MutationObserver` 的相关 DOM 记录，避免普通素材和训练页 childList 更新触发三次全局转换节点查询；新增 Chrome 30 次非转换 DOM 变化及异步转换弹窗装饰回归。待本轮准确 SHA 的 CI 证明通过后才能结项；尚未有生产 P95 结果。见 [本轮记录](./2026-11-13-frontend-13c-04f-02-conversion-mutation-scope.md)。

> **2026-11-13｜13C-04F-01 部署转换只读审计（不改业务代码）**：基线 `549df056161c515f38a7984be4e59f848f15a154` 的 GitHub Actions **23/23 工作流成功**。v39 块约 **45.1 KB**，仍提供正式部署资源 Owner、缓存、转换任务操作及 RKNN 板端验收，**不允许整段提取**；v41 约 **6.0 KB**，涉及缓存失效与 SDK 安装，暂无明确收益。更可控的候选是启动时加载的 `static/modules/conversion-workbench-ui.js`（17,862 B），其中全局 `MutationObserver(document.documentElement,{childList:true,subtree:true})` 在非转换页面也会观察 DOM 更改；仅确认潜在额外工作量，未测得 P95 或卡顿根因。下一步 13C-04F-02 先 Chrome 测量，再评估显式展示挂载和按需加载；**不得直接改动 v39/v428 转换提交、安全恢复、资源状态与硬件验收**。详见 [13C-04F-01 只读审计报告](./2026-11-13-frontend-13c-04f-deployment-conversion-readonly-audit.md)。

> **2026-11-13｜13C-04D → 13C-04E 更新（旧记录保留为历史快照）**：唯一长期分支 `feature/external-algorithm-publishing`；本轮最后业务/测试代码提交 `c61e82d20d398652dad1724ba2af58df02db7b63`。13C-04D 质量中心场景实测改为按需加载，准确代码 `5f19d231` 的 Frontend Runtime Stabilization 4/4 Job 成功，隔离 Chrome 首屏解码 JS 约减 108 KB（3.4%，不等于生产提速）。13C-04E 将组件检测 v40 从经典 `static/app.js` 迁出并首次进入按需 import，原 Owner、API、缓存、PollRegistry 保留；`app.js` 从 1,394,659 B 减至 1,386,275 B，减少 8,384 B（0.60%）。`a58bda75` Frontend Runtime Stabilization 4/4 Job 成功、单测 1661/1661 和 Chrome 3/3 分片成功。历史 Online Feedback Runtime 两项 Chrome 失败在 13C-04D 基线已存在，`c61e82d` 只修测试等待异步 Workbench 就绪，准确提交对应两组 Online Feedback Runtime 均成功。已核验 `c61e82d20d398652dad1724ba2af58df02db7b63` 准确提交对应全仓 GitHub Actions **22/22 工作流成功**（其中 Frontend Runtime Stabilization 4/4 Job、两组 Online Feedback Runtime 均成功）；验证不代表生产现场达标。原 A～E / T01～T10、正式 GT 20k/200k、A800/4070、Safari 和离线部署现场验收仍未关闭。下一轮仅审计 13C-04F 部署转换代码依赖，不允许整块迁移或扩大业务范围。

### 13C-04E 准确阶段证据

- 13C-04E 代码：`ab30f40bc7b6b19f07c2a7cd2d7d47e7b74fc368`；CI 保护守卫校正：`5faab63795712013010e031f51c93df795e7c883`；静态缓存与 Owner 测试断言校正：`a58bda7524521ec168a3548b0c0bbf2b2ba36f66`；线上反馈异步测试就绪修复：`c61e82d20d398652dad1724ba2af58df02db7b63`。
- [13C-04E 前端 4/4 Job 通过](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43426627830)；前端最新代码提交的主回归 [见本次 CI](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43428159022)；原生平台启动、素材冻结、Worker、真实设备速度不因这些自动化结果认定已验收。`c61e82d` 的准确 [Frontend CI](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43428159022) 及 [Online Feedback CI](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43428159103) 已取得成功结论；**代码提交全仓 22/22 成功**。
- 组件检测只是首个真正从 `app.js` 迁出的低频功能，收益为源码首屏减少 8,384 B；还没有同 CI 环境下首屏 JavaScript 解码/P95 的新增稳定对照数据。下一轮 13C-04F 先对部署转换 v39 建跨区域调用矩阵：它约 45 KB，至少有 `loadDeployData`、`refreshDeployResourcesV39` 和多个转换/部署动作被其他区域引用，**不能整体直接拆**。

> 截至 2026-11-13；唯一开发/推送分支 `feature/external-algorithm-publishing`；写入本文档之前核验远端 HEAD 为 `a0997c98d30dc4d9d63ba91092e7b27a23185ced`。
>
> 本文档为【当前进度单一入口】。原《性能优化与渐进式模块化治理专项任务书》A～E 任务包、P0/P1/P2 问题和 T01～T10 验收合同仍有效；不得因本进度文档删除原验收条件。本文档写入后 HEAD 将产生新的**仅文档提交**，不是代码版本前进或业务功能验收。

## 1. 本轮边界与准确状态

- **代码已提交不等于 CI 已通过；CI 全绿不等于生产部署通过；模拟 Chrome/隔离 SQLite 不等于真实 20k/200k 正式 GT、内网、Safari 或训练 Worker 验收。**
- **最终 CI 更正（2026-11-13）：** 13C-03 Chrome 浏览器三个分片全部通过，但 Frontend Runtime Stabilization 的 `frontend` 单元测试失败：`tests/frontend/lazy-advanced-evaluation-owner.test.mjs:39` 仍断言 `main.mjs?v=42.25.599`，真实 `static/index.html` 已统一为 `42.25.600`。本轮属于既有静态缓存键守卫遗漏同步，未取得业务运行时失败证据。**必须先仅纠正该测试并验证新 SHA 全绿，再做 13C-04。**\n\n- 13C-03 最新代码提交：`a0997c98d30dc4d9d63ba91092e7b27a23185ced`，见 https://github.com/jorsamj/aixunlianpingtai/commit/a0997c98d30dc4d9d63ba91092e7b27a23185ced ；截至本次查询：**36/37 工作流成功、1 失败（2026-11-13 最终结果；Frontend Runtime Stabilization 单元测试旧缓存键断言；禁止部署）**。实时以 https://github.com/jorsamj/aixunlianpingtai/actions/runs/43401136199 为准。
- 未获取 A800/双 4070 的生产部署授权；未进行生产重启、训练中断、GT/索引/数据库修改、部署或 Release。不能用 GitHub Actions 结论代替授权。
- 后续仍采用最小专项流程：准确 HEAD → 读真实代码与失败日志 → 精准修复 → 定向 Node/Python/Chrome → 准确 SHA CI → 文档归档。避免无意义重跑全量 20k/30k/200k 压测。

## 2. 前期 A～E 任务包完成情况（只写已证实的边界）

| 任务包 | 当前阶段 | 代码/回归已覆盖 | 尚需现场/发布验收 |
|---|---|---|---|
| A 诊断与基线 | 部分完成 | 调用链/慢路径审计，部分前后端定向回归及 Server-Timing；已清点启动静态 import | 同一操作 ID 的浏览器/网络/API/SQL/P50/P95 分段真实数据 |
| B 选材与冻结正确性 | 主要代码合同已覆盖 | 2万选择器冻结引用、Worker 准入/角色/深页扫描优化、Train/Test 隔离回归及 Chrome 合成规模流程 | 真实 20k/30k 正式 GT 的 Prepare→任务创建闭环，200k 混合历史筛选、并发与锁等待 |
| C 报告、素材库、弹窗 | 多轮精准修复已完成且部分准确 CI 通过 | 报告重复渲染与隐藏内容优化、素材分页不等待统计、弹窗租约/焦点/作用域与 Chrome 回归 | 用户真实报告 P95、桌面/iPad Safari 100次弹窗与长内容滚动现场回归 |
| D 渐进模块化 | 后端试点+前端分轮推进 | 后端 Paddle 配置解析提取；13A 页面/Owner 治理；13B 弹窗；13C 三个独立功能延迟加载 | 13C-03 准确 CI；app.js 主文件真实模块边界与执行成本；勿假设总加载提速 |
| E 交付与发布 | CI/文档逐提交实施 | 原准确 SHA 自动化工作流与专项记录 | 生产批准、离线安装包全资源、A800/4070 端到端和现场性能与回滚演练 |

## 3. 可追溯的最近各轮提交与 CI

| 轮次 | 代码/修订提交 | 内容 | 准确 CI |
|---|---|---|---|
| 13B-01 | `143fa906982e59761fc50c8d6e812dc2a2f588b0` | 报告专用 CSS 仅作用于报告弹窗，避免其他弹窗布局被污染 | 36/36 成功 |
| 13B-02 | `1cd5136cc0ddbdbb8cab8520c8d0eccc53d2198d` | annotation save 迟到时检查 ModalContentRuntime owner，避免误关复用的新弹窗 | 41/41 成功 |
| 13B-03 | `51c88621fc07f9e636754b87ce9be6d0c5459862` → `a740338dd124402f0a0d1a6284cdff8edf93b5c4` | 集中关闭恢复最外层焦点、取消存储导入轮询；纠正过窄的浏览器焦点断言 | 前一个提交 40/41，修订后 21/21 成功 |
| 13C-01 | `bd0e5fbedbf9a8c55eef8d8442e61fdb3be0795f` | 旧素材兼容迁移页（约 15 KB）延迟 import、导航租约和错误重试 | 37/37 成功 |
| 13C-02 | `77c49b67cf0aad298b0e0cd7dcedd7f224aa1da8` | 高级评测独立模块（约 31 KB）按质量中心页签延迟加载 | 37/37 成功 |
| 13C-03 | `a0997c98d30dc4d9d63ba91092e7b27a23185ced` | 畅联云数据浏览器独立模块（约 24 KB）按进入页面加载；手动刷新合同不变 | **36/37 工作流成功、1 失败（2026-11-13 最终结果；Frontend Runtime Stabilization 单元测试旧缓存键断言；禁止部署）** |

专项原始记录：
- [13B-01](./2026-11-13-frontend-13b-modal-scope.md) / [13B-02](./2026-11-13-frontend-13b-async-close-owner.md) / [13B-03](./2026-11-13-frontend-13b-bulk-close-focus.md)
- [13C-01](./2026-11-13-frontend-13c-01-lazy-legacy-material.md) / [13C-02](./2026-11-13-frontend-13c-02-lazy-advanced-evaluation.md) / [13C-03](./2026-11-13-frontend-13c-03-lazy-changlian-data.md)

## 4. 未闭环问题：必须区分“消除某段冗余”与“真实用户体验达标”

1. **训练素材 20k/200k 规模**：冻结→草稿→POST→Worker 引用的代码与合成浏览器回归不能代替正式 GT 环境里 2 万张准确进入训练并完成 Prepare；保持 P0 现场验收。
2. **慢查询与素材库**：角色/历史筛选、分页与摘要解耦已有精准修复，仍需真实索引规模、磁盘/SQLite 锁等待/网络分析；原用户报告“卡顿”不应因一轮 CI 而无条件关闭。
3. **报告与弹窗**：report charts 复用、CSS/Modal owner 恢复已在自动化覆盖；报告信息完整性、真实大报表耗时、iPad Safari、长弹窗开关100次需独立验收。
4. **前端大型主文件**：`static/app.js` 在 `a0997c98d30dc4d9d63ba91092e7b27a23185ced` 实际为约 **1,295,305 字节、10,568 行**，混合全局经典脚本/业务 owner；`main.mjs` 有大量静态 import。此前三次懒加载合计移出了约 15+31+24 KB 的非关键页面模块，不意味着主文件已瘦身，也不意味着全站 P95 已改善。
5. **后端单体**：`app.py` / 核心业务模块仍应保留正确性/事务先决条件后做渐进抽取；不得为模块化改变 SQLite 模型、Worker 协议或 GT。
6. **生产离线**：4070 的真实数据目录 `/var/lib/changlian-4070/data`，程序 `/opt/changlian-4070/current`，Web 健康端口 `18010`；生产现行版本须现场只读核验，不能假设开发 HEAD 已部署；A800 同理。

## 5. 下一轮任务：13C-03 结束后先做 13C-04（app.js 主文件边界）

### 5.1 进入条件
- 必须先精准修复 `a0997c98d30dc4d9d63ba91092e7b27a23185ced` 已确认的 `tests/frontend/lazy-advanced-evaluation-owner.test.mjs:39` 静态缓存键断言，并核对修复后准确 SHA 的完整 CI；其他失败仍按 job/line 修复，**不得在红 CI 上叠加下一轮**。
- 复核远端开发分支 HEAD、已有 Owner 表/ES Modules、原任务书 T01～T10 要求。
- 不启动 20k/200k 全链路反复压测，仅对候选拆分区域做必要的 Chrome/单测/小型性能验证。

### 5.2 先审计（不立即拆整文件）
- 按 **入口/Renderer、数据获取、状态、异步取消、DOM/事件、上传/训练/标注/报告** 建立 `app.js` 调用矩阵；识别 `window.*` 内联回调、动态全局调用、同名多次覆盖和 `main.mjs` 启动先后依赖。
- 用实际 Chrome Performance/Coverage 区分下载、解析、执行、渲染、网络；保存一份首屏与一次目标页进入的证据，不以源码行数当 P95 结论。
- 只选 **一个无需改 GT、冻结 selection_ref、训练提交、Worker 协议的展示/只读组件** 做首个 `app.js` 剥离试点；旧全局入口委托至新模块，确保兼容已有业务和离线部署。
- 拆分前建立兼容回归：初次打开/重复打开/离开/再进入/异常/多窗口／原功能合同；通过后才允许实际迁移与删除旧实现。
- 如果某片段跨多个经典全局内部变量强耦合、缺稳定 owner，则只交依赖图和拆分计划，不强行迁移。

### 5.3 禁止项和交付门槛
- 不直接转 Vue/React、不引新全局 Store、不重写 Modal Manager/训练/标注、不新建后端服务、不迁数据库、不合并 `main`、不 force push、不创建 Release。
- 交付：职责/调用/加载依赖图，拆分前后源码与 Chrome 请求/长任务取证，一项可逆、易回滚的最小代码迁移，相关定向单测/真实 Chrome/准确 CI，`docs/CODEX_CURRENT_STATE.md`、`docs/PROJECT_HANDOFF_CURRENT.md` 和本台账同步更新。
- 所有 A800/双 4070 部署、服务重启、训练中断、数据修改必须先获得明确批准；仅文档提交不产生上述授权。

## 6. 保留的验收矩阵 T01～T10

| 编号 | 继续有效的硬约束 | 当前判定 |
|---|---|---|
| T01 | 单页60张交互、长任务 | 定向优化/自动化覆盖，现场 P95 待验 |
| T02 | 2万张跨页筛选全选与冻结引用 | 浏览器模拟/引用合同已覆盖，现场待验 |
| T03 | 2万正式GT→训练创建→Worker | **真实全链路未验** |
| T04 | 20万混合历史筛选/深页 | **真实P95/锁等待未验** |
| T05 | Train/Test 同 SHA 隔离、版本身份 | 现有严格合同继续保留 |
| T06 | 综合/单版本报告真实指标、图表和错例 | 自动化修复，现场真实性/速度待验 |
| T07 | 弹窗连续开关100次、焦点/滚动 | Chrome 定向回归通过，现场100次待验 |
| T08 | 并发旧响应、任务变更、请求所有权 | 定向所有权保护/回归，现场待验 |
| T09 | 桌面、手机、iPad Safari | Chrome 部分覆盖，Safari 待验 |
| T10 | A800/4070 离线资源/发布准入 | **未获部署授权，未验收** |

> 将本文档作为新会话接续入口时，始终重新读取原始任务书与最新 CI；本文历史快照不得充当实时状态。
