# 2026-11-09｜42.24.567 转换记录首次读取缓慢专项

## 现象与范围

- 用户点击算法版本“转换”后，长时间停留在“正在读取转换记录…”。
- 范围仅限原 `GET /api/v42/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/deployments` 的读取链路。不修改创建、停止、删除、产物、转换 Worker、任务持久化、生产数据，也不部署服务器。

## 代码证据与修复

1. 原端点先调用 `list_algorithms_internal(project_id)`，即使只需单一算法也会读取整个项目算法/版本数据。大项目历史评测、标签契约等字段可能显著增加读取成本。改用原已存在的 `list_algorithms_internal(project_id, algorithm_id=algorithm_id, summary_only=True)`；授权检查与算法/版本不存在时的 404 保持不变。
2. 原端点 `visible_version = dict(version)`，会把冻结评测 `evaluation`、标签契约 `label_contract` 等大型字段放入转换记录的 JSON 响应与浏览器缓存。改为明确保留转换页需要的 `id`、版本名、源模型名/路径、大小、状态、框架、创建时间、`model_metadata` 及在服务端从完整版本计算的 `conversion_defaults`。原存储记录和转换任务完全不变。
3. 原 `ConversionHistoryProjection` 的文件签名复用、页码/过滤、durable 运行中状态叠加均保持；前端既有缓存预览、请求超时、分页、轮询和“新建转换”按钮保持，不新增请求中心或缓存。

## 回归

- 扩展 `tests/api/test_dynamic_conversion_catalog.py`：确保定向单算法查询、分页过滤及转换默认参数保持，且版本响应不泄露大型评测/标签契约字段。
- 更新 `tests/api/test_rknn_board_validation.py` 的模拟函数签名，以继续验证 RKNN 硬件状态字段未变。
- 当前开发环境没有完整 FastAPI/pytest 依赖，采用 Python AST 独立加载真实端点函数的模拟调用验证：定向查询成功，模拟 1.5MB 的非转换字段不会进入响应。完整 API 测试待既有 GitHub CI 验证；不能以模拟测试当作 4070 实机性能结论。
- 前端原有转换分页、创建、缓存和导航回归保持不变，运行常规 `npm test`。

## 现场待核

部署后针对一个已有版本首次打开转换窗口，记录浏览器 Network 中 `/deployments` 的请求耗时、响应体大小和首屏时间；再验证筛选、分页、刷新、进行中任务和“新建转换”正常。若环境的文件系统或 SQLite 本身仍慢，需以接口耗时及 `stats` 证据开展独立诊断，不能声称该提交已经消除所有现场瓶颈。
