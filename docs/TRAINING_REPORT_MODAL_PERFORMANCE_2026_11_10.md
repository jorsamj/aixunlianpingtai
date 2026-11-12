# 42.24.569｜训练报告读取与弹窗稳定性专项

## 需求与边界

- 2026-11-10，基线 `42.24.568` / `bb5cd95c`，唯一长期分支 `feature/external-algorithm-publishing`。
- 处理单任务报告打开慢、报告 Tab 换行缩小、异步内容与 Tab 切换导致报告弹窗高度和滚动范围变化。
- 不重建弹窗组件、不新增报告 API/缓存、不过滤真实历史指标，不动训练、GT、Worker、生产数据或实际部署。

## 代码确认及修复

1. 原 `v44_training_report` 每次调用无条件 `list_algorithms_internal(project_id)`，同时旧 `enrich_job_runtime` 缺算法名时也可全项目扫描。现复用 `AlgorithmSqlStore` 已有 `idx_versions_training_job`，只查询 `algorithm_id/version_id` 两列，按命中 owner 读取对应算法；明确指定算法 ID 时直接单算法查询；无索引命中的历史记录继续原全量后备；索引命中但 JSON 血缘不匹配时再次回退，保留身份冲突和多版本歧义 409。缺算法名回填同样改定向读取。
2. 原 `.modal-card.wide`、`.quality-workspace` 最终高度均可为 `auto`，Tab 切换会改变内容高度；报告 skeleton 与正式 HTML 现共用 `data-training-report-dialog` 标记，该弹窗在加载、切 Tab 和报错阶段使用固定 `86dvh` 的容器与单一内部滚动口，其他弹窗不变。
3. 报告四个 Tab 改为 `nowrap`、`flex:0 0 auto`、横向滚动；活动 pane 保留足够高度以维持 sticky 导航和滚动范围。移动端不再 `flex:1 1 40%` 自动压缩。
4. 既有 3/10/20 秒反馈、AbortController、关闭归属、重试和错误真实性保持原样；不简单拉长超时。
5. 版本与页面资源缓存键更新到 `42.24.569`，`reports.js` 两处 ES Module import 使用相同资源键，避免重复加载不同模块实例。

## 验证结果与开放项

- `python -m py_compile app.py platform_core/algorithm_sql_store.py tests/api/test_training_metric_credibility_report.py tests/api/test_training_report_indexed_lookup.py`：通过。
- Node 定向报告、弹窗、关闭归属、可信度回归：29/29 通过（包括新增布局与标记守卫）。
- Node 全量尝试：本工作环境缺少官方 Uppy/Annotorious npm 依赖，存在依赖缺失的失败；不能声称全量通过。
- 新增后端真实 SQL 索引/任务报告身份与旧历史回退测试；本环境没有 `pytest`、`fastapi`、`filelock`，未实际执行 Python API 测试。
- 实际 Chromium/移动 Safari 页面滚动、4070 报告 P50/P95、准确 SHA CI、生产数据与部署：**NOT VERIFIED**。

## 现场验收重点

1. 确认 4070 `/api/health` 版本与静态资源缓存键一致；不能用 42.24.543 验证 42.24.569 的改动。
2. 对已有、无模型产物和旧血缘报告分别读取，记录 Network 的响应时长/尺寸/状态；确认无错选历史版本、409 歧义仍阻断。
3. 桌面窄窗口、375px 移动布局连续在“概览/训练曲线/异常样本/数据与溯源”切换，测试滚轮、触屏、关闭与重开，不应弹窗居中缩小；其他普通弹窗不得受影响。
4. 如浏览器完整转圈超过 20 秒，采集实际运行 SHA、Network 瀑布、Performance 主线程长任务；不能把尚未确认的浏览器主线程堵塞归为服务器超时。
