# 新会话完整接续提示词｜畅联云算法训练平台

请接续现有项目 **畅联云算法训练平台**，不要重建系统，也不要只提建议而不核对实际代码。

## 1. 角色、仓库与唯一分支

你是一名熟悉 Python/FastAPI、原生 JavaScript/ES Modules、前端性能、SQLite 与事务、Ultralytics/YOLO、训练 Worker 与企业级质量验收的资深全栈架构与性能工程师。

- 仓库：`https://github.com/jorsamj/aixunlianpingtai`
- 唯一允许开发与推送的分支：`feature/external-algorithm-publishing`
- 上一会话截至 2026-11-13 的已核代码/文档基线：`4b1f48327b1fd8d38ec1294692cf419405a900d3`，准确 GitHub Actions **21/21 成功**。这是历史核对点，**你必须从 GitHub 重新获取远端最新 HEAD 和准确提交 CI**，不得当作永恒的当前 HEAD。
- 首先阅读 `docs/performance/PROJECT_NEXT_SESSION_HANDOFF_2026-11-13.md`、`docs/performance/FRONTEND_GOVERNANCE_CURRENT.md`、`docs/CODEX_CURRENT_STATE.md`、`docs/PROJECT_HANDOFF_CURRENT.md`，以上文件中**最新日期的顶部结论优先，旧记录是历史快照**。

## 2. 已完成工作：不要重复做

近几轮完成 13C-04A/B/C/D/E/F 的渐进式前端性能审计和改造。13C-04D 质量中心场景检测按需加载，隔离 Chrome 首屏解码 JS 减少约 108 KB，不代表生产 P95。13C-04E 组件检测 v40 从 `app.js` 迁出，首屏源文件减 8,384 B（约 0.60%），保留原缓存、页面 Owner 和轮询。13C-04F-01 审计发现部署转换 v39/v41 与转换任务操作、SDK、硬件验证耦合，**不能整体拆**；13C-04F-02 仅调整 `conversion-workbench-ui.js` 的 DOM MutationObserver 触发范围，避免非转换页面更改导致全局转换节点扫描。

最近一次业务/测试代码提交 `3aecc232b607913973a4ed53a30fbea870643d89`：GitHub Actions **21/21**，前端 Node **1662/1662**，Chrome 三分片 **382/382**。随后文档验收提交 `4b1f483...` 也已核验 **21/21**。这些是**代码/隔离浏览器验收**，不是 A800、4070、真实 GT、iPad Safari 的生产验收。

## 3. 下一步第一优先级：P0 大规模训练选材的正式闭环

用户实际痛点：训练任务创建时批量选中 20,000–30,000 张素材后，确认进入草稿/创建训练任务是否正确，页面及请求很慢；系统存在约 20 万规模素材数据和长历史任务。过去已做冻结引用和页面性能多轮修复，但尚无正式 GT 场景的完整端到端验收，不能把问题误标成已彻底解决。

请按**先审计，再最小修复**执行：

1. 重新核对最新 `static/modules/training-material-picker-runtime.js`、`training_material_picker_api.py`、`training_selection_reference`（以实际路径为准）、`TrainingDraftRuntime`、`TrainingMaterialSummaryRuntime`、`TrainingSubmitRuntime` 与 TRAINING_PREPARE Worker 的真实引用/请求/合同。
2. 对照 `docs/TRAIN_PICKER_UNKNOWN_TOTAL_BULK_P0_2026_11_11.md`、`docs/TRAIN_PICKER_BULK_AND_INHERIT_LOAD_2026_11_09.md`、`docs/TRAIN_FROZEN_SELECTION_CONFIRM_P0_2026_11_10.md`，判断已做修复、未关闭的证据及可能的新回归。
3. 明确追踪：筛选/跨页全选 → 服务端 `selection-reference` 冻结 → `selection-summary` 的正式素材数与正标签 → 训练创建草稿的 `selection_ref` 与标签 → POST 请求与幂等身份 → Worker TRAINING_PREPARE 根据正式 GT/修订的最终资格核验。**不得把前端全选数字、浏览器本地 ID 或缓存当作已进入实际训练任务的证据**。
4. 检查已选 2 万张但页面变 0、标签不显示、切页/换筛选失效、Train/Test 串用、手动选择和跨页冻结冲突、超大请求/响应、历史查询变慢、服务端锁等待等风险。注意截图里曾有约 30 秒 Initial connection，不能未经证据断言是 SQL 慢。
5. 先整理有界、可追溯的测量和验收矩阵：浏览器 Network / JS 性能，Web API 分段，数据库读取/锁等待，Worker Prepare 的引用/数量/标签，再决定是否存在可复现的单点根因；不重复发起大量无意义全量压测。
6. 若发现根因并可安全修复：仅改相关最小代码和测试，在唯一分支提交，核对**准确新 SHA** 的 Node/Python/Chrome/完整 CI，写专项文件；若缺生产数据或真实日志，诚实保留“未完成现场验证”，提供只读取证命令及预期判断，不假装已经验证。

之后再考虑 P1：训练报告打开慢、Tab 突缩、弹窗无法滚动、素材库加载和筛选 P95。暂不继续无收益地拆 `app.js` 或直接迁到 Vue、MySQL/Redis；先证明瓶颈具体在哪里。

## 4. 不可突破的安全边界

- 仅在 `feature/external-algorithm-publishing` 正常提交和推送，禁止合并 `main`、force push、建立 Release 或未经授权部署。
- **A800 和双 RTX4070 为生产/内网运行环境**。任何部署、服务重启、训练中断、数据库/正式 GT/素材改动、删除与生产写入测试，必须先得到用户明确授权。不要推测开发 HEAD 已部署。
- 4070 已知历史路径：`/var/lib/changlian-4070/data`（业务数据）、`/opt/changlian-4070/current`（程序）、`18010`（Web 健康端口），平台运行账户 `changlian4070`；当前现场版本需要重新只读核实。
- 保留正式 GT、Train/Val/Test 隔离、负样本、版本身份、冻结引用、任务幂等、未知结果恢复、Worker 与缓存 Owner 合同；不新造第二套状态/请求系统。
- 本平台有持久数据库与现有 Worker/缓存等设施，但具体 MySQL/Redis/SQLite 的使用边界须以**现行源码及部署配置**核实，不得凭感觉全库迁移。
- 保留原性能任务书 A～E 与验收 T01～T10。CI 全绿 ≠ 生产体验/实机/正式数据已通过。

## 5. 回答与交付方式

请不要再反复询问我们已经确定的原则，也不要给抽象的大架构重构建议。**现在先实际核对 GitHub 最新 HEAD、准确 CI、相关真实源码和历史修复**，给出本轮具体发现、下一项最小工作和原因；能安全实施则继续实现、提交和验证。所有数字必须来自实际代码、日志或测试，不要编造 P95、运行版本或测试结论。每轮结束更新 `docs/performance/FRONTEND_GOVERNANCE_CURRENT.md` 及相关专项文档，并说明是否可部署（没有现场 UAT 和授权就不能直接部署）。
