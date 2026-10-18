# 2026-10-18｜素材治理显示与算法列表性能专项进展

## 基线及边界

仓库 `jorsamj/aixunlianpingtai`，唯一长期分支 `feature/external-algorithm-publishing`。
本轮开发基线 `ff51ffda72d4e8c22e1b74a4f1ee347208318a46`。
正式 `VERSION.txt` 保持 `42.24.356`，入口静态资源 cache-bust 更新为 `42.25.390`，不是正式版本升级。
本轮只进行长期开发分支增量代码修复，不登录生产 A800，不触发素材真实删除，不改任何历史 GT、Snapshot、Test 或模型证据。

## 用户反馈及实现

| 编号 | 现象 | 本轮处理 | 边界 |
| --- | --- | --- | --- |
| P0-01 | 手机端重复问题组变成密集横线 | 问题组网格固定单列、明确最小行高（桌面 74px、窄屏 84px）及不压缩轨道；限制滚动高度；增强 Chrome 检查 | 真实手机 Safari/Chrome 仍待部署实测 |
| P0-02 | 2531 张被历史引用保护、删除计划 0 | 维持 `MULTIPLE_PROTECTED_REFERENCES` 安全拦截，直接展示不可删原因和核对入口 | 现场 2531/1041 需另行只读引用审计，不能强删 |
| P0-03 | duplicate_annotation_conflict 修复闭环 | 继续复用上一轮训练预检、原标注人工修正及本次输入排除，不新增 Owner | 生产冲突两条 Image ID 尚未核实 |
| P0-04 | F5 进入算法列表慢 | algorithms、jobs 并发启动但分阶段渲染：算法先显示，任务状态后更新；保留失败展示；延迟训练参数预热，仅空闲预热最多两项；增加 startup/refresh 计时 | 后端 SQL/Bootstrap/网络瓶颈尚需生产测量；尚不能承诺 2 秒 |
| P1-05 | 二十个近似“查看并处理”按钮 | 零删除预览统一为“返回待核对问题组”入口，不展开重复按钮墙 | 在问题组列表逐项核对 |
| P1-06 | SUCCEEDED 且 Worker ID 缺失显得未完成 | 终态与 Worker 证据分开展示；进度按总量限制；单列“实际删除索引”数 | 缺少执行节点证据仍真实提示，不伪造 |
| P1-07 | 手机治理弹窗布局混乱 | 给问题组列表独立滚动、紧凑分页、移动单列、清晰行高 | 全平台设计体系未重构 |
| P1-08 | “任务成功”等于“已删除”的误解 | 区分删除任务实际删除索引数量，0 可删时不会创建空任务 | 审计成功≠删除成功，旧审计本身仍可继续显示 |

## API、安全与架构

- 保留 `MaterialRepository`、`AnnotationRepository`、`MaterialBatch/DELETE_INDEX` 的原有真相与执行边界。
- `MULTIPLE_PROTECTED_REFERENCES`、`TRAINING_FAILED_NO_FREEZE`、冻结 Test/历史 Snapshot 继续阻止不安全索引删除；本轮不调整保护集合。
- 问题组 API 仍为现有只读 `/material-integrity/audits/{id}/groups`，首次和续页从 100 条改为 25 条，`next_cursor` 和跨页已选组语义不变。
- 算法列表仍使用原 algorithms/jobs 两个 API、原缓存与 Owner，不新增后台队列和外部平台自动同步。
- 列表的本次算法加载耗时、首屏更新耗时与总耗时可从 `AlgorithmListRuntime.state().timing` 查看；Bootstrap 计时可从 `PlatformCore.runtime.startupTiming` 查看。

## 变更文件及验收

- `static/app.js`：问题组、零删除入口、任务终态。
- `static/styles.css`：列表行高/布局/移动端。
- `static/modules/algorithm-list-runtime.js`：分阶段算法刷新、空闲预热、性能计时。
- `static/main.mjs`：启动计时与模块缓存版本。
- `static/index.html`：入口资源缓存版本。
- `tests/browser/material-integrity-governance.spec.mjs`：真实问题组行高，1366/390/375 视口和零删除返回。
- `tests/frontend/material-integrity.test.mjs`：终态与统一入口防回归。
- `tests/frontend/algorithm-list-runtime.test.mjs`：慢 Jobs 时算法先更新。
- `tests/frontend/version-marker-owner.test.mjs`：静态入口缓存版本与正式 VERSION 分离。

## 验证计划和未解决事项

- 推送后必须以最终 SHA 验证 Node、Python、真实 Chrome 和所有实际触发的 GitHub Actions/Jobs，未触发工作流单列。
- 生产网站此前 `103455` 张素材、`2531` 张受影响、`1041` 组、实际可删除 `0`，均为用户现场截图，尚未通过生产只读证据确认根因分布。
- 仍需生产现场只读核验 `0dcb43b6fa1c0678d1c4094c93403678aae9cbaac28419c2fbf4cfd9120c5e9e` 两条 Image ID 的具体 GT、冻结与 FAILED 引用关系。
- 后端算法列表的全量版本图读取、首次 Bootstrap 全局脚本下载及数据库锁争用均未在真实生产环境计时；继续作为性能专项后续风险。
- 本轮不宣称现场问题已修复或删除已成功，不部署生产。
