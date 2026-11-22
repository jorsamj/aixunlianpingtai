# 上传身份、确认闭环、ZIP 多任务与大规模删除收口（2026-11-22 第二轮）

本轮完成 A–E 五个工作包的连续开发，基线 `557e0317`。

## A｜图片上传身份与恢复

- 新增无 DOM 依赖的共享模块 `static/modules/material-upload-session.js`：
  - 账号 + 项目作用域 key：`material-upload-session:v2:{actorKey}:{projectId}`。
  - 有界本地索引：`material-upload-index:v1:{actorKey}:{projectId}`，最多 50 条，只存 request_id/batch_id/计数/状态/时间，不存文件、凭据、Blob。
  - 旧 key 只兼容读取；无 owner 的旧记录不归属当前账号、不展示。
- `MaterialUpload.vue`：
  - 未完成/未核实请求存在时禁止挂载可上传 Uppy，`再选一批` 不清除身份。
  - localStorage 写入失败时在第一个 POST 前中止；中途失败停止后续批次。
  - 日志/结果按 generation 防迟到响应覆盖；重复提交返回进行中，不产生第二个请求。
  - 新增 `owner` 与 `actorKey` 校验；回执仍核验 `project_id/request_id/batch_id`。
- 共享模块已用于 Vue 图片上传与任务中心；旧 `installMaterialUploadRuntime()` 仍保留原 Owner，未改造 legacy DOM。

## B｜上传后确认业务闭环

- 预览：`previewImage` 打开真实 content URL；缩略图失败时预览按钮仍保有可点击高度。
- 正样本：upload-intent `sample_type=positive` + `label_codes`，批次 decisions `ready`，随后跳转原标注入口并带 `material_id`。
- 清洗：decisions `clean`，服务端返回 `clean_task_id`，确认面板显示“查看清洗进度”。
- 负样本：分类读取、upload-intent `sample_type=negative` + `category_ids`，不写 GT。
- 稍后处理：`deferred` 持久化；刷新后确认按钮仍出现，任务中心显示待确认数量。
- 失败重试：按服务器证明的失败文件名重挂 Uppy；同名成功/失败时仍不猜测。
- AI：提供“AI 预标注（原工作台 · 本批次）”显式回退，带 `source_batch_id`。
- 确认面板使用注入的 Storage 适配器映射到账号/项目 key，原 `UploadConfirmationRuntime` 仍是决策 Owner。

## C｜统一上传任务中心

- 图片侧读取账号/项目索引中的多个会话，不再只看最后一个 localStorage session。
- 每个会话聚合服务器回执：成功、失败、待确认数量；`decision=pending` 才是待人工确认。
- 未核验/待确认行优先展示，不被有界索引截断静默丢弃。
- 操作：核验/继续（提升原会话到当前上传页）、继续上传确认、查看已入库素材、查看 ZIP 任务/标签确认、进入已导入批次。
- 仍无新增上传任务数据库；ZIP 使用 v19 列表，图片使用本机指针 + v55 回执。

## D｜ZIP 多任务、暂停续传与标签映射

- `ZipImport.vue`：
  - 安装前保存所有全局兼容函数；卸载恢复，不删除其他 Owner 注册项。
  - 挂载前销毁遗留 `ZipImportRuntime`；卸载清除 `window.ZipImportRuntime` 等。
  - 新增活动传输列表（upload_id / import_job_id 分开）。
  - 新增原生“暂停传输/继续传输”，继续使用原 upload session；任务列表支持暂停后重新选择原文件。
- 验证：
  - 3 个 ZIP 同时选择：3 个唯一 import_job_id、3 个唯一文件名、全部 done、各入库 1 张，无互相覆盖。
  - 48MB ZIP：暂停后继续，服务端返回同一 `upload_id`，最终只生成 1 个 import_job_id；刷新后可定位原任务。
  - 有标注 ZIP（fire/vehicle，两个类别）：人工把 vehicle 映射到 smoke，保留 3 个真实框，GT 标签为 fire/smoke，未自动新建标签。
  - 关闭视图不取消后台任务；模态关闭与取消任务分离。

## E｜501/2001 删除恢复

- 删除记录不再保存全部 image_ids；只保存 `plan_id/project_id/operation/mode/count` 与有界 FNV 双哈希摘要。
- 结果页大小按规模推导：≤5000 用 100，超过用 500；最大页数 `ceil(required/limit)+3`，上限 2000，取消固定 20 页。
- 身份核验：
  - `seen > required` 判范围外身份异常；
  - 覆盖不足/游标循环保持 UNKNOWN；
  - 同数量时用摘要检测 foreign/替换；
  - 只有服务端逐项状态可结案。
- 验证：501 张 6 页、2001 张 21 页（突破原 20 页），摘要匹配后清记录；无第二次 create。

## 证据

- `native-image-upload.spec.mjs`：5 张、65 张两批、混合失败、响应丢失、项目切换、未核验阻断、存储失败零 POST、双会话索引、其他账号/无主旧记录隐藏。
- `native-upload-confirmation.spec.mjs`：预览、正样本 intent/ready、清洗任务、负样本 intent、稍后刷新、AI 入口。
- `native-zip-advanced.spec.mjs`：多 ZIP、暂停续传同一 upload_id、两类别真实 GT。
- `material-delete-scale.spec.mjs`：501/2001 页数与摘要。
- 既有 101 张、四状态、PARTIAL_SUCCESS、跨页选择继续通过。

## 仍未验证

- 真实 GPU 训练、生产环境、20 万真实素材未执行。
- ZIP 外部标签映射只在小型有标注 ZIP 上验证；多 ZIP 标签确认按顺序自动切换未逐一截图。
- 图片确认中的 AI/智能质检仍为原工作台回退；未宣称原生 AI/质检页面。
- 图片恢复页面只处理当前账号/项目；跨浏览器迁移不自动归属。
- CI 结果以最终 SHA 为准。
