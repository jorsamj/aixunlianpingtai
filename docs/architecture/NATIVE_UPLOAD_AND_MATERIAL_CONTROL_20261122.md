# 原生 Vue 上传与素材/训练控制收口（2026-11-22）

本轮在既有 FastAPI、SQLite、TaskRuntime、Uppy 6.0.5 离线发行版和原上传运行时之上，完成：

- E2 素材删除：结果游标、逐项状态、冻结范围身份、跨页选择。
- E3 训练操作：停止 UNKNOWN 对账、恢复 truth 身份绑定、隔离 FastAPI 联调。
- 普通图片上传：独立 `/app/` 入口，复用原 request_id 分批与恢复合同。
- ZIP 数据集：独立 `/app/` 入口，复用 `ZipImportRuntime` 分片/暂停/恢复/标签确认 Owner。
- 统一上传任务：图片回执与 ZIP 导入任务分栏展示，严格区分传输、后台处理与正式入库。

## 合同与身份

| 链路 | 权威身份 | 说明 |
| --- | --- | --- |
| 素材删除 | `plan_id == task_id` | estimate 返回 `selection_spec`；results 的 `cursor` 为 image_id keyset |
| 图片上传 | `upload_request_id == batch_id` | 64 张 / 128 MiB 分批；响应丢失按原 request_id GET 回执，不重传未确认批次 |
| ZIP 上传 | `upload_id`（分片会话） | 合并完成后由服务器返回 `import_job_id`；二者不得互相冒充 |
| 训练停止 | 原 `task_id` | POST cancel 只记录停止意图；CANCEL_REQUESTED 不是 CANCELLED |
| 训练恢复 | 原 `task_id` + attempt | 仅服务端 truth 允许的 `revalidate_checkpoint`，不新建任务 |

素材删除结果只信任服务端逐项状态：`pending` / `running` / `succeeded` / `failed`。
只有 `succeeded` 会从页面选择中移除；`pending`/`running` 不得当作失败。
出现范围外 ID、重复 cursor、游标不前进、覆盖数量不足或状态冲突时保留原计划身份，不清理本地状态。

## 原生入口

- `/app/#/projects/{pid}/materials`：新增“上传图片（原生）”“ZIP 数据集（原生）”“上传任务”；原“上传素材”入口保留。
- `/app/#/projects/{pid}/materials/upload`：Uppy Dashboard + 原 `MaterialUploadRuntime` 纯函数（分批、request_id、恢复、XHR 进度）。
- `/app/#/projects/{pid}/materials/zip`：Uppy Dashboard + 原 `mountUppyZipAdapter` + 原 `installZipImportRuntime`；模态宿主仅提供 DOM/CSS 适配。
- `/app/#/projects/{pid}/materials/tasks`：图片回执与 ZIP 任务统一列表，按当前项目身份读取，最多 50 条 ZIP / 16 个本机 request_id。

## 真实证据

- `tests/browser/material-delete-pagination.spec.mjs`：101 张、3 页选择、刷新恢复、estimate 冻结范围、2 页 results（第二页携带 cursor）。
- `tests/browser/material-delete-result-evidence.spec.mjs`：pending / running / failed / PARTIAL_SUCCESS、重复 cursor、范围外 ID、选择只移除成功项。
- `frontend/tests/training-tasks-native.spec.ts`：迟到 recovery truth、停止 5xx 对账、恢复 POST 5xx 不重试、CANCEL_REQUESTED 与 CANCELLED 分离。
- `tests/api/test_training_control_vue_contract.py`：真实 TaskRepository SQLite + 真实 recovery router；可信 checkpoint 哈希、202 受理、原 task_id/retry_of/attempt、重复 POST 409、未知/跨项目 404。
- `tests/browser/native-image-upload.spec.mjs`：5 张成功、混合失败、响应丢失恢复、65 张两批、项目切换隔离、无 CDN。
- `tests/browser/native-zip-import.spec.mjs`：原生 Uppy、upload_id/job_id、文件夹确认、真实后台导入 2 张、无 GT。
- `tests/browser/native-upload-task-center.spec.mjs`：图片回执 / ZIP 任务同页、项目切换、跳转 ZIP 任务。

## 未验证 / 安全边界

- 未操作生产、A800、4070；未启动真实 GPU 训练。
- 训练停止/恢复的浏览器证据为 Mock 路由 + 隔离 FastAPI；真实进程终止由既有 `test_unified_task_process_cancel.py` 覆盖，本轮未重跑长时间训练。
- ZIP 原生入口已验证单 ZIP、原始文件夹确认与后台导入；多 ZIP 并发、暂停/续传、外部标签逐项映射仍由既有 legacy ZIP 测试覆盖，尚未在原生入口逐项重验。
- 图片上传的“同名文件成功与失败混合”仍沿用原 Uppy 名称匹配，未新增身份算法。
- 图片确认决策 UI 复用原 `installUploadConfirmationRuntime`（DOM 适配），不是重写 GT/清洗/负样本 Owner。
