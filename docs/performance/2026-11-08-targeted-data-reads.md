# 2026-11-08｜数据获取专项：定向预检、任务摘要与推荐配置

## 范围与真值边界

依据《畅联云训练素材与加载治理》Word 及数据获取后续排查，本轮在长期分支做**小范围、可回退的非 UI 修复**。不得改动生产数据库/GT、任务状态、训练资格、正式同步计划、已有缓存/请求中心。现有 27,530 张素材冻结批选/游标查询已单独优化，不能重复实现一套。

## 已落实

1. **新畅联训练预检**：按目标算法 ID 从现有 `AlgorithmSqlStore.read_one()` 定向获取，仍实时向新畅联核实产品/视觉分析状态。检测到分析方式、产品编码或分类的训练契约漂移时返回 `EXTERNAL_ALGORITHM_SYNC_REQUIRED`（HTTP 409），引导用户使用原“平台对接”同步入口；绝不在预检里启动 `sync_type=auto` 全量同步。仅名称变化可保留明确的 `drift_fields` 诊断，不伪造本地同步结果。
2. **算法列表旁路任务读取**：旧 `/api/projects/{project_id}/jobs` 默认完整返回，独立报表及既有消费者的契约不变。新增显式 `summary_only=true`，复用已有 `_v53_job_summary` 投影，不触碰原索引/任务证据。算法列表运行时调用摘要视图，先绘算法卡片，待任务请求完成再补状态。该变更主要减少**返回体与浏览器 JSON 解析量**，不能声称解决服务端全量任务遍历。
3. **训练推荐配置**：`/api/system/recommendation` 默认快速返回 `unverified_fallback`，不运行同步的 8 秒 `torch` 子进程检测，不根据 Web 机器是否有 CUDA 推断真实训练 Worker。设备建议为 `auto`，并注明 Worker 准入才是最终依据；返回 `cuda=null`、`worker_verified=false`。需要诊断 Web 本机 GPU 时可显式传 `probe_local_cuda=true`，并标记 `web_runtime`，同样不冒充 Worker。
4. **训练创建资源与推荐解耦**：`hydrate()` 仅等待实际 `training_options`，推荐读取独立异步完成/失败，任何推荐失败都不影响资源就绪。保留原页面作用域取消、重试、状态诊断。

## 回归与观察

- `node --test tests/frontend/algorithm-list-runtime.test.mjs tests/frontend/training-create-hydration.test.mjs`：32/32 通过（本地）。
- 其余可独立运行的前端用例：排除需要本地 `node_modules` 的 Annotorious/Uppy/ZIP 三组依赖用例后，197 个测试文件共 **1536/1536 通过**。未排除的全量命令因容器没有安装官方 `@annotorious/annotorious`、`@uppy/core` 等依赖而报错；这是环境阻断，不能记录为全量绿灯。
- `python -m compileall -q ...` 与 `git diff --check`：通过（本地）。
- 使用 Python AST 直接抽取纯函数做了轻量契约冒烟检查：默认推荐不会探测 Web CUDA，`jobs` 摘要不会修改完整任务记录；不等同于 FastAPI 集成验收。
- 后端新增/修改的 pytest 回归包括：漂移预检不得调用全量同步且算法修订号不变；`jobs?summary_only=true` 不污染完整报告；推荐默认不触发 CUDA 进程。当前执行容器缺失 FastAPI、pytest，后端用例尚未实际运行，**必须由 CI/具备依赖的环境验证**。
- 部署/生产性能验收**未执行**。应按接口记录 `Server-Timing`、响应字节、P50/P95、长任务数量，并比较冷/热启动；不得将本地 Node 通过等同于生产合格。

## 尚未声称解决的独立瓶颈

- `/api/v12/projects/{project_id}/algorithms` 仍构建完整版本图；部分 SQLite `payload_json` 内含巨大的 `evaluation`、`label_contract`。直接删字段可能破坏报告和训练表单，后续须新增契约明确的列表专用投影，并完善单算法按需详情/浏览器回归。
- `/jobs` 摘要请求仍调用原 `sync_jobs_index(read_only=True)`；隔离了响应大对象，但服务端历史任务查询/持久投影的实际耗时需要量测后定向优化。
- 大规模素材分页、OSS 缩略图、真实 20 万素材的跨机器延迟未做生产测量；不能宣称全部达标。

## 发布约束

仅提交到 `feature/external-algorithm-publishing`；禁止合入 main、release、force push。此轮不自动部署到 A800 / 4070，不修改生产数据及后台任务。
