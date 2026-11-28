# 畅联云算法训练平台｜2026-11-13 性能治理最终接续快照

> 本文是新会话接续的最新状态快照，不代替历史专项原始证据、业务 UAT 或生产部署准入。
> 唯一开发与推送分支：`feature/external-algorithm-publishing`。
> 本文写入前远端 HEAD：`4b1f48327b1fd8d38ec1294692cf419405a900d3`（**文档提交，不是新代码发布**）；准确 HEAD 的 GitHub Actions **21/21 成功**。
> 最近一次有业务/测试代码改动的提交：`3aecc232b607913973a4ed53a30fbea870643d89`，其准确 CI **21/21 成功**。后续文档提交必须重新核对自身准确 SHA/CI。

## 一、最近 13C 工作的真实结果

| 轮次 | 内容与边界 | 证据 / 阶段判断 |
|---|---|---|
| 13C-04A | `app.js` 主文件边界只读审计 | 仅审计；不能机械拆大文件 |
| 13C-04B | 训练资源卡片纯展示抽离，保留同步桥接 | 源码见 `static/modules/training-resource-cards.js`；非全面首屏提速证明 |
| 13C-04C | 隔离 Chrome 启动/Profile/Coverage 采样框架 | 真实用户 P95 未获得；覆盖率不等于耗时 |
| 13C-04D | 质量中心场景算法实测延迟加载 | 隔离 Chrome 首屏解码 JS 约减 108 KB（约 3.4%），并非生产提速结论；代码/测试记录见 [专项](./2026-11-13-frontend-13c-04d-quality-detection-lazy.md) |
| 13C-04E | 组件检测 v40 从 `app.js` 迁出，首次打开按需 import | `app.js` 从 1,394,659 B 减至 1,386,275 B，缩减 8,384 B（约 0.60%）；原缓存、API、轮询、Owner 兼容；[专项](./2026-11-13-frontend-13c-04e-component-scan-lazy.md) |
| 13C-04F-01 | 部署转换 v39/v41 依赖只读审计 | v39 约 45.1 KB，v41 约 6.0 KB，含正式资源/任务/硬件兼容动作，**禁止整块拆**；[审计](./2026-11-13-frontend-13c-04f-deployment-conversion-readonly-audit.md) |
| 13C-04F-02 | 缩小 `conversion-workbench-ui.js` 的全局 DOM 观察器触发范围 | 代码 `3aecc232...`，精准 CI 21/21；前端 Node 1662/1662；Chrome 131+126+125=382；30 次无关 DOM 变更不增加所测转换根扫描，异步插入的转换列表、表单和源提示仍装饰；[专项](./2026-11-13-frontend-13c-04f-02-conversion-mutation-scope.md) |

### 关键提交和准确验收

- 13C-04D、E 交接代码/测试闭环提交：`c61e82d20d398652dad1724ba2af58df02db7b63`，准确 Actions **22/22**；后修历史 Online Feedback Chrome 测试异步初始化夹具，不改业务代码。
- 13C-04F-01 审计提交：`e4d0173ec36ac9aa586c27ba8683f5e344bcb0e2`，仅文档。
- 13C-04F-02 业务/测试提交：`3aecc232b607913973a4ed53a30fbea870643d89`，准确 Actions **21/21**，Frontend Runtime Stabilization **4/4 Jobs**（运行：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43435335641）。
- 13C-04F-02 收尾记录提交：`4b1f48327b1fd8d38ec1294692cf419405a900d3`，**文档本身的准确 Actions 21/21**（写本记录前再次查询）。
- GitHub 全绿代表代码/CI 的验证结论，**不等于** 20k/200k 正式 GT、真实训练 Worker、Safari、A800/4070 或生产用户 P95 验收。

## 二、明确未完成的业务现场验收

| 优先级 | 用户感知 / 风险 | 已有证据与尚欠证据 |
|---|---|---|
| **P0** | 训练任务创建时 20,000–30,000 张素材跨页全选后，确认是否真正进入训练草稿、最终 POST 和 Worker | 已有 `selection-reference`、`selection-summary`、`TrainingDraftRuntime`、`TrainingSubmitRuntime` 和 TRAINING_PREPARE 合同与多轮修复；**真实正式 GT 的端到端数量、标签、引用及 Worker 准入未验收**，不得因隔离 CI 全绿关闭 |
| **P0** | 20 万素材/历史混合角色筛选、深页、冻结引用性能 | 有部分后端分页/定向查询/前端去全库等待优化；仍缺真实请求链、Network、API 分段、SQLite/索引/锁等待、P50/P95；截图曾出现约 30 秒 Initial connection，**不能直接推断为 SQL 耗时** |
| **P1** | 报告打开慢、综合/单版本信息与图表、Tab 突缩及弹窗滚动卡住 | 已有减少重复渲染、弹窗焦点/滚动与报告 CSS 作用域治理；仍欠真实模型报告 P95、长内容、iPad Safari、真实报告指标/错误样本 UAT |
| **P1** | 素材库列表、切页、统计摘要、弹窗交互 | 分页数据与摘要异步解耦已有代码；真实 217k 素材量级需要以现行数据/当前部署现场实测，不能直接认定现行规模或实现 |
| **P2** | 其余 `app.js` 按需模块化 / `app.py` 收敛 / 引入 MySQL、Redis | 不按文件大小拆、也不因感觉卡立即迁库。先验证慢在网络/API/索引/锁、浏览器渲染还是长任务；保留现有数据库、事务、Worker、GT 合同 |

## 三、下一会话推荐的唯一第一步

**任务：P0 训练素材冻结引用→创建草稿→训练任务创建→Worker 的可追溯正确性和耗时专项；先只读再最小修复。**

1. 从 GitHub **重新拉取远端 HEAD、`VERSION.txt`、准确 SHA CI**，与上述历史基线区分；同步阅读原 [当前台账](./FRONTEND_GOVERNANCE_CURRENT.md)、`docs/TRAIN_PICKER_UNKNOWN_TOTAL_BULK_P0_2026_11_11.md`、`docs/TRAIN_PICKER_BULK_AND_INHERIT_LOAD_2026_11_09.md` 和 `docs/TRAIN_FROZEN_SELECTION_CONFIRM_P0_2026_11_10.md`。
2. 只读审查从筛选全选、`selection-reference` 服务器冻结、摘要中数量/正标签、草稿 `selection_ref` 持久、提交 payload、`TRAINING_PREPARE` Worker 正式 GT 再校验的逐段代码/数据合同。检查相同 request_id 与引用身份、项目/算法/版本/修订绑定、跨页/切换筛选/选标签时失效、一键全选与逐项选择的差异、Train/Val/Test 独立和负样本池准入。
3. 先列有界验收矩阵及采集方案：冻结前后数量/标签、UI 已选身份、POST JSON（脱敏）、数据库任务引用（只读）、Worker Prepare 真值与 P50/P95 各段计时。**不重复进行巨量无意义压测**。无现场访问权限时仅做源码审计/CI 定向模拟，明确实机未验；不可伪造 20k 正式 GT 结论。
4. 如发现实际可复现根因，单点最小修复 + 定向测试（Node/API/Chrome）+ 完整准确 SHA CI + 进度更新。否则交付真实证据缺口与可执行的只读现场验收步骤，先不改代码。
5. P0 真实链路证据补齐后，转向 P1 **报告打开 P95 与弹窗滚动/Tab 稳定性**；不要未经审计直接开始 13C-04G 或大范围 `app.js` / `app.py` 重构。

## 四、不可突破的边界与权限

- 仅允许开发、提交、推送 `feature/external-algorithm-publishing`；先校验 HEAD、必要时比对并行提交，正常非强制快进；**禁止 merge main / force push / 创建 Release**。
- **A800 与双 RTX4070 是生产/内网服务器**，任何实际部署、重启、打断训练、改库、删文件、清理 GT、执行生产写入测试前必须取得用户明确授权；不能假设代码 HEAD 已部署。
- 4070 历史业务数据目录 `/var/lib/changlian-4070/data`；程序 `/opt/changlian-4070/current`；Web 健康端口 `18010`；系统账户 `changlian4070`。**历史信息不是现场当前状态**；访问前应仅只读核对且取得相应访问方式。
- 不建第二套路由、Store、训练提交、冻结引用、任务调度/Worker、GT 或缓存 owner；不转 Vue/React；不迁 SQLite/MySQL/Redis 或更改事务语义，除非独立审计取得充分证据和单独许可。
- 所有完成状态必须分清：源码提交、准确 CI、隔离 Chrome、真实 GT 训练 UAT、生产部署五个层次。原任务书 A～E 与 T01～T10 仍持续有效。

## 五、入口与后续记录

- **当前总台账**：[`FRONTEND_GOVERNANCE_CURRENT.md`](./FRONTEND_GOVERNANCE_CURRENT.md)
- **新会话可直接复制的提示词**：[`NEW_CHAT_PROMPT_2026-11-13.md`](./NEW_CHAT_PROMPT_2026-11-13.md)
- **历史通用总账**：`docs/CODEX_CURRENT_STATE.md`、`docs/PROJECT_HANDOFF_CURRENT.md`（顶部新状态优先，下方旧条目是历史快照，绝不可当成最新阻断）
- 所有验收数字都绑定上述准确提交 SHA；**新会话开始必须重新核 HEAD 和 CI**。
