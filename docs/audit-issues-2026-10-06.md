# 2026-10-06 前后端一致性 / 非法套娃 / 重复 Owner 审计问题清单

> 项目：畅联云算法训练平台  
> 仓库：`jorsamj/aixunlianpingtai`  
> 长期分支：`feature/external-algorithm-publishing`  
> 审计基线 HEAD：`3b5c073f9a2c9c532cbab6cfec3e899c5a4091a5`  
> 审计基线 VERSION：`42.24.109`  
> 本文档首批提交 VERSION：`42.24.110`  
> 续审计核验 HEAD：`0e03819fafe50a02bc57d1980ed0c62d97c95296`  
> 续审计核验 VERSION：`42.24.110`  
> 上一批审计记录提交后 VERSION：`42.24.111`  
> 上一批审计记录提交后 VERSION：`42.24.112`  
> 上一批审计记录提交后 VERSION：`42.24.113`  
> 上一批审计记录提交后 VERSION：`42.24.114`  
> 上一批审计记录提交后 VERSION：`42.24.115`  
> 上一批审计记录提交后 VERSION：`42.24.116`  
> 上一批审计记录提交后 VERSION：`42.24.117`  
> 上一批审计记录提交后 VERSION：`42.24.118`  
> 上一批审计记录提交后 VERSION：`42.24.119`  
> 上一批审计记录提交后 VERSION：`42.24.120`  
> 上一批审计记录提交后 VERSION：`42.24.121`  
> 上一批审计记录提交后 VERSION：`42.24.122`  
> 上一批审计记录提交后 VERSION：`42.24.123`  
> 上一批审计记录提交后 VERSION：`42.24.124`  
> 上一批审计记录提交后 VERSION：`42.24.125`  
> 本批审计记录提交后 VERSION：`42.24.126`  
> 审计阶段：**仅记录问题，尚未开始生产修复。**

## 1. 审计范围与原则

本轮不是重新设计架构，也不重新打开已经 CLOSED 的 Annotation Ground Truth、Training Picker、Dataset Revision、ModelArtifact、External Publish、Remote Staging GC 等主链。

本轮只继续检查：

- 当前真实 UI / API 可达 Bug；
- 前后端合同不一致；
- 非法 `include_router` 套娃；
- 重复 Owner / 第二状态源；
- Legacy Runtime 绕过 canonical owner；
- 重复 Poller / Modal / Router；
- 状态枚举漂移；
- 删除 / 取消 / 退役生命周期绕过；
- 1k / 10k / 20k 规模下的正确性与性能边界。

登记标准：

1. 必须先走真实调用链复核；
2. 当前 UI/API 可达并造成错误，登记生产 Bug；
3. zero-reference 旧代码只登记结构债，不夸大为生产 Bug；
4. compatibility alias 最终仍归 canonical owner 的，不误报；
5. 怀疑项证据不足时不编号；
6. 后续证据推翻时必须显式撤销。

## 2. 当前基线 CI

本轮开始时重新核验当前 HEAD：

- GitHub Actions workflows：`21 / 21 completed success`
- check-runs：`55 / 55 completed success`
- failure：`0`
- queued：`0`
- in_progress：`0`

当前没有 completed failure job log 可读取。

全绿不代表没有组合层 Bug；本轮已经确认多项“单 Router / 单 Runtime 测试通过，但真实 app composition 出错”的问题。

---

## 3. 已确认问题

### AUDIT-001 — `static/app.js` 重复定义 `ensureLabels()` / `quickAdd()`

**级别：低～中**  
**模块：前端 Legacy helper**

文件开头连续保留两套相同的：

- `ensureLabels()`
- `quickAdd()`

后定义覆盖前定义。

当前未证明会直接导致用户请求失败，但它是明确重复实现；未来维护只改其中一份时会产生行为漂移。

**最小修复方向：**

- 确认所有引用后保留唯一实现；
- 不新增第三套 helper；
- 增加 source guard，禁止相同全局 helper 再次重复定义。

---

### AUDIT-002 — 后端 Router 非法套娃 / 残缺 Agent Router 抢先匹配

**级别：高**  
**模块：FastAPI composition / Training Recovery / Service Node / Scheduler / Agent Executor**

`app.py` 已直接完整挂载：

`training_recovery_router(...完整 callbacks...)`

但：

`platform_core/material_batches.py`

内部又执行：

`root.include_router(training_recovery_router(get_project, task_repository, task_artifacts))`

因此真实生产装配为：

`app.py -> material_batch_router() -> training_recovery_router()`

随后 `app.py` 又第二次挂完整 `training_recovery_router()`。

第一套 Router 没有传入：

- `agent_execution_payload_resolver`
- result upload callbacks
- training model upload callbacks
- material scan callbacks
- cleaning selection callbacks

而 `material_batch_router()` 更早进入 FastAPI route table，因此存在先匹配真实请求的问题。

已经进一步确认：

Agent 节点执行：

`POST /api/v63/node-executor/.../assignments/{task_id}/start`

若命中第一套残缺 Router，会在 `start_execution()` 因：

`execution_payload_resolver is None`

直接返回：

`REMOTE_EXECUTION_PAYLOAD_UNAVAILABLE / HTTP 409`

material scan / cleaning selection / training model upload / result upload 等同样存在 `*_UNAVAILABLE` 409。

这不是结构债，而是当前生产装配错误。

**为什么 CI 没发现：**

已有测试主要验证独立 Router；即使存在 `test_runtime_router_app_mount.py`，它也只是统计 `app.py` 源码中直接出现一次 `app.include_router(training_recovery_router(...))`，没有展开 `material_batch_router()` 内部的嵌套路由。

**最小修复方向：**

- 从 `material_batch_router()` 中彻底移除 `training_recovery_router()`；
- 仅由 `app.py` 完整装配一次；
- 增加真实 app route table uniqueness / callback wiring regression test；
- 不新增第二 Scheduler / Agent executor owner。

---

### AUDIT-003 — `TrainReq.precision` OpenAPI Schema 与 runtime 不一致

**级别：中**  
**模块：Training API Schema**

Pydantic Schema：

`precision: Literal["auto", "fp16", "bf16", "fp32"]`

但 canonical runtime 只支持：

- auto
- fp16
- fp32

`bf16` 会 fail-closed。

当前 UI 没有暴露 BF16，但 OpenAPI / 第三方客户端会被误导。

**最小修复方向：**

让 Schema 与真实 runtime 一致；除非以后正式实现 BF16，否则不要在 API 合同宣称支持。

---

### AUDIT-004 — `TrainReq.gpu_policy` OpenAPI Schema 与 runtime 不一致

**级别：中**  
**模块：Training API Schema**

Schema 仍声明 `shared` 为合法值，但 `validate_train_request()` 明确拒绝 shared GPU policy。

当前 UI 仅提供：

- auto
- exclusive

因此 UI 暂时安全，但 API 合同错误。

**最小修复方向：**

收紧 Schema；不要让 OpenAPI 宣称 runtime 明确禁止的值。

---

### AUDIT-005 — 多层 Modal 下关闭上层 Modal 会误停底层 Storage Import polling

**级别：中～低**  
**模块：Modal / StorageImportProgressRuntime**

`closeModalCanonical420()` 关闭任意 top modal 时都会调用：

`window.beforeCloseStorageImport61?.()`

但 Storage Import hook 不接收当前 top modal，只检查 DOM 任意位置是否存在：

`#si61ImportShell`

只要底层 Storage Import Modal 仍存在，就会执行：

`StorageImportProgressRuntime.stop()`

因此：

1. 底层 Storage Import 正在 polling；
2. 上层打开另一个 Modal；
3. 用户只关闭上层 Modal；
4. 底层 polling 被误停。

后台 durable task 不会取消，但 UI 进度会停止刷新。

AI annotation 的 cleanup 已经按 `top` scope 处理，Storage Import 没有。

**最小修复方向：**

Storage Import cleanup 必须按正在关闭的 top layer scope 判断。

---

### AUDIT-006 — 前后端版本 / UI build / 静态资源 cache identity 多套真相

**级别：低～中**  
**模块：Version / diagnostics / static cache identity**

正式：

`VERSION.txt = 42.24.109`

但：

`static/main.mjs`

仍有：

`UI_BUILD_VERSION = '42.25.0-dev'`

同时 `static/index.html` 还分别引用：

- `app.js?v=42.25.283`
- `main.mjs?v=42.25.257`

后端 `/api/system/version` 则返回正式 `APP_VERSION`。

形成多套 build/version truth。

**影响：**

- 浏览器诊断版本错误；
- cache identity 与正式版本脱节；
- 自动化取证难以判断实际构建；
- 前后端版本展示互相矛盾。

**最小修复方向：**

建立单一正式 build/version source；不要再手工维护多套独立字符串。

---

### AUDIT-007 — `PlatformCore.modalStack` 是未接线的第二 Modal owner 空壳

**级别：低 / 结构债**  
**模块：Modal architecture**

`static/main.mjs` 创建并暴露：

`PlatformCore.modalStack`

但扫描生产模块后未发现真实使用。

当前实际 Modal owner 仍在 `static/app.js`：

- `dynamicModalStack`
- `modalStackCanonical424`
- `closeModalCore424`

目前因为 zero-reference，不构成运行时双状态源，但它是未来极易误接形成第二 Modal owner 的空壳。

**最小修复方向：**

确认生产 zero-reference 后删除 dead owner，不要继续向其中接新能力。

---

### AUDIT-008 — 旧 Annotation Owner 仍暴露为全局可调用写入口

**级别：中**  
**模块：Annotation / Label Governance**

当前 canonical：

`window.openAnnotation -> AnnotationWorkbench -> AnnotationRepository`

并且标签治理合同明确：

标签为空时必须让用户自行到标签管理创建，不允许系统替用户决定训练标签。

但 `static/app.js` 仍暴露：

- `window.openAnnotationLegacy_1`
- `openAnnotationLegacy_2`

旧实现中的 `ensureLabels()` 会在标签为空时自动创建：

- person
- helmet
- no_helmet

当前 canonical UI 没有主动引用这些 Legacy 名称，因此主流程正常情况下不会触发；但这些仍是浏览器全局可调用的写入口，可以绕过当前标签治理合同。

**最小修复方向：**

先证明全仓 / 当前 DOM / 当前缓存兼容 zero-reference，再正式退役旧 Annotation 写入口；不能保留两个 Annotation owner。

---

### AUDIT-009 — Paddle Training 前端允许选择，但 Durable Training 后端必定 409

**级别：高**  
**模块：Training Create / TrainingSubmitRuntime / Durable Training API**

后端：

`POST /api/v12/projects/{project_id}/train/start`

明确只支持：

`framework == "ultralytics"`

任何 Paddle：

`framework != "ultralytics"`

都会 HTTP 409。

但前端：

`readyTargets429()`

只判断：

`target.status === "ready"`

没有排除 `framework === "paddle"`。

`/api/training_options` 可以把 `local_paddle` 返回为：

`framework:"paddle", status:"ready"`

训练创建 Modal 会把 Paddle 显示为可选训练资源。

`TrainingSubmitRuntime` 没有 Paddle guard，并会真实构造：

`framework:"paddle"`

最终提交到只支持 Ultralytics 的 Durable Training endpoint。

**真实调用链：**

`/api/paddle_env/select`
→ `/api/training_options`
→ `state.targets`
→ `readyTargets429()`
→ `tr429Target`
→ `TrainingSubmitRuntime.submit()`
→ `buildTrainingEngineParameters()`
→ `framework:"paddle"`
→ `/api/v12/.../train/start`
→ 409

**最小修复方向：**

- 不新增第二 Paddle Training runtime；
- 当前 Durable Training create 只允许 Ultralytics-compatible target；
- Paddle 可以留在资源检测页，但明确“当前不可用于 Durable Training”；
- `TrainingSubmitRuntime` 再加 fail-closed guard，防止旧缓存 / DOM / 脚本绕过。

---

### AUDIT-010 — Training Settings Modal 重复插入同名高级参数控件

**级别：中**  
**模块：Training Settings Modal**

canonical 调用链：

`openTrainSettings429()`
→ `openTrainSettings428()`
→ 已渲染一套高级参数
→ `decorateTrainSettingsAdvanced415()`
→ `insertAdjacentHTML(...)`
→ 再插入第二套相同参数

至少以下 9 个 DOM id 明确重复两次：

- `ts428Lrf`
- `ts428Warmup`
- `ts428CloseMosaic`
- `ts428MultiScale`
- `ts428HsvH`
- `ts428HsvS`
- `ts428HsvV`
- `ts428Translate`
- `ts428Scale`

保存时：

`saveTrainSettings428()`

和：

`saveTrainSettingsCore428()`

又会重复读取这些 id，浏览器 `getElementById()` 只返回其中一份，导致用户编辑第二组可见控件时可能被第一组旧值覆盖。

**最小修复方向：**

- 保留 canonical base settings 已拥有的控件；
- decorator 只能补真正不存在的字段；
- 保存逻辑收口为一次读取、一次更新 TrainingDraft；
- 增加 DOM id uniqueness 回归测试。

---

### AUDIT-011 — 删除整个算法绕过 Algorithm Version Retirement / active-reference fence

**级别：高**  
**模块：Algorithm deletion / Version retirement / Durable Training / ModelArtifact**

当前 canonical 算法列表对本地算法提供“删除”按钮，即使该算法存在 active training。

前端：

`delAlgorithm()`
→ `DELETE /api/v12/projects/{pid}/algorithms/{algorithm_id}`

后端：

`v12_delete_algorithm()`

只调用：

`assert_algorithm_mutable(...)`

该 guard 只检查外部平台算法主数据只读，不检查活动 Training / Conversion / Deployment Test 引用。

随后：

`delete_algorithm_asset()`

直接删除算法记录；SQL 外键会 CASCADE 删除 algorithm_versions metadata。

而仓库已经存在正式的版本 retirement owner：

- `_algorithm_version_active_references()`
- `model_delivery_version_fence()`
- `delete_algorithm_version(... dependency_check / cleanup ...)`

整算法删除绕过了这套 canonical owner。

**影响：**

- 活动训练可以继续，但算法主记录已经不存在；
- 训练完成时归档找不到算法，成果无法形成版本；
- 已有版本 metadata 被 CASCADE；
- ModelArtifact / conversion / board validation / publication 等跨存储资产没有逐版本走正式 cleanup；
- 可能产生 orphan artifact / 孤儿记录；
- UI 与 Durable Task truth 分裂。

**最小修复方向：**

- 整算法删除必须复用 version retirement / dependency truth；
- 任一版本或算法存在 active Training / Conversion / Deployment Test 时 fail-closed；
- 删除空闲算法时逐版本走 canonical cleanup，再删 algorithm metadata；
- 需要算法级 fence 防 TOCTOU；
- 前端已知 active 时同步禁用删除，但后端 guard 才是最终真相。

---

### AUDIT-012 — 已撤销：AlgorithmListRuntime Durable 状态枚举漂移

**状态：撤销，不计入确认问题**

曾怀疑：

`AlgorithmListRuntime`

直接消费通用 Durable jobs 的：

- `WAITING_RESOURCE`
- `CANCEL_REQUESTED`

但其 active 状态集合只识别 legacy 小写值。

继续读取后发现：

`GET /api/projects/{pid}/jobs`

并不是通用 `/api/v62/.../tasks`，而是训练专用兼容投影。

后端 `enrich_job_runtime()` 会把：

- `WAITING_RESOURCE -> waiting`
- `CANCEL_REQUESTED -> running`
- paused stage -> `paused`

并保留 canonical `task_status`。

因此当前 AlgorithmListRuntime 的 active 判断在这个 endpoint 上可工作。

**结论：撤销，不修。**

---

### AUDIT-013 — 算法卡“训练次数”错误使用最近 50 条项目历史窗口

**级别：中**  
**模块：AlgorithmListRuntime / Training Job Index**

算法卡展示：

“训练次数 · 历史任务”

并支持“按训练次数排序”。

但当前训练次数来自：

`GET /api/projects/{pid}/jobs`
→ `jobs/index.json`
→ `_training_job_index_rows(..., history_limit=50)`

后端为了性能，正确地只保留：

- 全部 active task
- 项目最近 50 条 terminal history

前端却直接：

`trainingCount(id) = state.jobs.filter(job.algorithm_id === id).length`

把 bounded live/history index 当成全量累计训练次数。

当项目累计终态训练超过 50 条时：

- 老算法历史任务被新任务挤出；
- 真实训练 30 次可能显示 8 次；
- 甚至可能显示 0；
- “按训练次数排序”也错误。

**最小修复方向：**

不能把 `/jobs` 改成无限返回。

应保留 bounded jobs index 专门用于：

- active 状态；
- 最近任务；
- 实时 UI。

另增加项目级一次性聚合真相：

`algorithm_id -> total_training_count`

使用 SQL GROUP BY 或一次 O(N) 聚合；禁止 per-algorithm N+1 report 请求。

---

### AUDIT-014 — ZIP Import 单条 DELETE 可直接删除活动任务目录，绕过 Import Worker owner

**级别：高**  
**模块：ZIP Import / v19 lifecycle**

现代 ZIP Import 主链：

`POST /api/v19/.../import/jobs`
→ `POST /api/v19/.../import/jobs/{id}/start`
→ daemon `v19_import_worker()`

worker 持续依赖：

- `job_dir/source.zip`
- `job_dir/extracted`
- `job.json`

且持续调用：

- `v19_read_job()`
- `v19_update_job()`

后端批量清理：

`DELETE /api/v19/.../import/jobs`

已经正确只删除：

- done
- failed
- cancelled
- canceled

但单条：

`DELETE /api/v19/.../import/jobs/{job_id}`

没有任何 terminal guard，也不 cancel / join worker，直接：

`shutil.rmtree(v19_job_dir(...))`

因此 running / selecting / waiting-confirmation 任务都可被 API 直接从 worker 脚下删除。

**影响：**

- 活动任务记录消失但 worker 仍存活；
- source.zip / extracted 被删后 worker 异常；
- 后续状态写入面对不存在的 job；
- UI truth 与线程 truth 分裂；
- DB_COMMIT 边界存在生命周期竞态；
- DELETE 被错误地当成隐式 cancel。

现代 UploadTaskCenter 本身只提供“清空已结束”，反而进一步说明正确产品合同是 terminal-only cleanup。

**最小修复方向：**

- 单条 DELETE 和批量清理共用同一个 terminal guard；
- 非终态统一 409；
- 如果未来需要取消导入，新增的是 canonical cancel action，而不是让 DELETE 充当 cancel；
- worker 观察取消状态，进入 terminal 后才允许删除。

---


### AUDIT-015 — Service Node 停用会卡住 pre-start assignment

**级别：高**  
**模块：Service Node / CentralTaskAllocator / Agent assignment / GPU reservation**

**现象：** 节点 `enabled=true -> false` 只更新节点状态，不释放该节点尚未 start 的 `ASSIGNED / CLAIMED` assignment。已 RUNNING execution 可继续 heartbeat / upload / finalization / finish，disabled node 也确实不能 claim/start 新任务；Bug 只发生在 pre-start 窗口。

**真实调用链：** `PATCH /api/v63/service-nodes/{node_id}` → `ServiceNodeRepository.update(enabled=False)` → assignment 仍为 `ASSIGNED / CLAIMED` → claim/start 返回 `NODE_DISABLED` → `CentralTaskAllocator.assign_next()` 又因已有 active assignment 不再改派。CLAIMED 过期回收目前只在该节点再次进入 `claim_for_node()` 时发生，而 disabled node 已进不去。

**为什么是 Bug / 套娃：** Service Node owner 已停用，但 canonical assignment / GPU reservation truth 仍保持占用，两个生命周期发生分裂。

**影响：** Training / Material Import / Cleaning / Conversion / Deployment Test 可卡在原节点；其它健康节点不能接管；GPU reservation 可能持续占用。

**为什么 CI 没发现：** 已有测试覆盖“disable 后不能 claim 新任务”和“RUNNING 后 disable 仍可 finish”，未覆盖 ASSIGNED 与 CLAIMED-before-start。

**建议最小修复：** true→false 时只由 CentralTaskAllocator 释放 pre-start ASSIGNED/CLAIMED，并与 start transaction race-fence；RUNNING 不取消、不迁移；不新增第二 reservation owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 ASSIGNED / CLAIMED / RUNNING 三个窗口和跨节点重新分配。

---

### AUDIT-016 — Storage Source DELETE 可破坏活动 Durable Import / Rescan

**级别：高**  
**模块：Storage Source / MATERIAL_IMPORT / Rescan / Credential lifecycle**

**现象：** `DELETE /api/v61/storage-sources/{source_id}` 只统计已落库 MaterialRepository 引用，不检查已创建但未完成的 Durable import/rescan；删除 source 后还会立即删除对应 credential secret。

**真实调用链：** 创建 scan/rescan → request 冻结 `storage_source_id` → task queued → 删除 Storage Source → source row + secret 被删 → `StorageImportHandler._source_and_provider()` 执行时重新 `sources.get(storage_source_id)` / 取 credential → FileNotFound / credential unavailable。

**为什么是 Bug / 套娃：** 删除 owner 只看“已导入完成的素材引用”，忽略“活动 Durable task 引用”，DELETE 成为破坏活动 task 依赖的旁路。

**影响：** queued/running import 或 rescan 可被用户删掉依赖；OSS/S3/MinIO 凭据提前销毁；Durable task truth 与 Storage Source lifecycle 分裂。

**为什么 CI 没发现：** 当前测试只验证 material reference guard 和正常 import/rescan，没有“创建任务后、Worker claim 前删除 source”。

**建议最小修复：** 删除前按 Durable Task truth 检查活动 MATERIAL_IMPORT/rescan 对 `storage_source_id` 的引用；活动引用 409；终态后再删 source/secret；查询保持分页有界。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-017 — Image 单删 / v46 批删绕过 canonical MaterialBatch 删除 owner

**级别：高**  
**模块：Material deletion / Active Training fence / AnnotationRepository delete protocol**

**现象：** 当前 `DELETE /api/projects/{project_id}/images/{image_id}` 与 `POST /api/v46/projects/{project_id}/images/batch-delete` 直接 unlink，并调用 `AnnotationRepository.remove()` / `MaterialRepository.remove()`。它们没有经过 modern MaterialBatch deletion owner。

**真实调用链：** 当前单删/批删 → 直接删除 Material/Annotation。canonical MaterialBatch 的 `DELETE_INDEX / DELETE_SOURCE` 则会在创建和每批执行前调用 `_assert_not_referenced_by_active_training()`，并执行 `prepare_delete → finalize_delete → material remove → complete_delete`，失败可 restore。

**为什么是 Bug / 套娃：** 已存在唯一 modern Material deletion owner，但旧 HTTP 写入口仍能直接修改同一 Material + Annotation truth，是当前可达的第二删除 owner。

**影响：** 活动 Training 引用素材可被删；本地源文件可提前物理删除；Annotation GT 删除绕过 crash-safe delete protocol。

**为什么 CI 没发现：** MaterialBatch 自身测试通过，但单图/v46 route 不调用该 owner，缺跨入口 owner consistency test。

**建议最小修复：** 单删和批删复用 canonical MaterialBatch delete primitive/owner；不复制第二套 training guard。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-018 — Model Config DELETE 会删除仍被 Durable AI task 引用的 secret

**级别：高**  
**模块：AI Annotation / Model Config / Secret lifecycle**

**现象：** Durable AI task submit 已正确冻结 `model_config_snapshot`、`model_config_revision` 和 `secret_ref`，但 runtime 仍需按 frozen `secret_ref` 到 Keyring 取真实 secret。`DELETE /api/v35/model-configs/{config_id}` 会直接删除 config 和 secret，完全不检查活动 AI task。

**真实调用链：** v60 annotation task create → request artifact 冻结 `model_config_snapshot.secret_ref` → task queued → 用户删 Model Config → Keyring secret 删除 → Worker `prepare_request(runtime=True)` → `KeyringSecretStore().get(secret_ref)` 为空 → `AI_MODEL_SECRET_UNAVAILABLE`。

**为什么是 Bug / 套娃：** config identity 已 snapshot 化，但 credential lifecycle 仍由 live config delete 单方面控制，Durable task 的冻结输入并不真正可恢复执行。

**影响：** queued / retry / recovery AI task 可因“删除配置”而失败。

**为什么 CI 没发现：** 现有测试验证 live config 修改不影响 frozen snapshot，但测试中的 Keyring 始终返回 frozen secret；没有删除 secret 的窗口测试。

**建议最小修复：** 活动 Durable AI task 引用该 `secret_ref` 时 delete 409；终态后再删 secret；绝不能把 secret 明文复制进 task artifact。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-019 — Dataset DELETE 可在 Training PREPARING 阶段删掉尚未冻结的素材

**级别：高**  
**模块：Dataset deletion / TRAINING_PREPARE / Dataset Revision input freeze**

**现象：** v12 Training submit 先创建 TRAINING + 独立 TRAINING_PREPARE；真正的 `resolve_training_selection() / freeze_training_inputs() / input-freeze.json` 由 Prepare Worker 随后建立。旧 Dataset DELETE 在这段窗口没有 active Training reference guard。

**真实调用链：** `POST /api/v12/.../train/start` → TRAINING accepted、PREPARE queued、尚无 input-freeze → `DELETE /api/projects/{project_id}/datasets/{dataset_id}` 删除 dataset 素材 → `TrainingPrepareHandler._freeze_request_contract()` → `_selected_project_images()` → 明确报“所选素材不存在”。

**为什么是 Bug / 套娃：** Dataset Revision 主链本身没问题；问题是旧 Dataset lifecycle owner 可在 canonical freeze owner 建立不可变输入前破坏已经受理的训练 selection。

**影响：** 用户看到训练创建成功，随后删除 dataset 会让准备任务失败；删除操作成为对活动 Training 的隐式破坏。

**为什么 CI 没发现：** 现有 freeze/Revision 测试关注 freeze 后不变性，没有覆盖“TRAINING 已受理但 PREPARE 尚未 freeze”的并发窗口。

**建议最小修复：** Dataset delete 复用 active-training reference truth；PREPARING/QUEUED/RUNNING/CANCEL_REQUESTED 且 selection 命中时 fail-closed；不改 Dataset Revision identity。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-020 — Training 单条 DELETE 会隐式取消活动任务，和批量删除合同相反

**级别：高**  
**模块：Training task lifecycle / frontend-backend consistency**

**现象：** 当前 queued/running/paused 行都显示“删除”；单删确认文案只说删除任务记录。但 `DELETE /api/v12/projects/{project_id}/jobs/{job_id}` 对 active Durable task 会调用 `v48_stop_job()` → `request_cancel()` / terminate process → 再 `rmtree(job_dir)`。批量删除却通过 `_purge_terminal_training_job_record()` 明确只清 terminal task。

**真实调用链：** `TrainingTaskRuntime.deleteTrain428()` → v12 DELETE → `v12_delete_job()` → active → `v48_stop_job()` → canonical cancel/process termination → remove job projection directory。

**为什么是 Bug / 套娃：** 同一页面同一“删除记录”语义存在两套生命周期合同：单删=隐式 cancel，批删=terminal-only cleanup；DELETE 抢了独立 stop/cancel action 的责任。

**影响：** 用户只想删记录却真实停止训练；单删与批删行为不可预测。

**为什么 CI 没发现：** stop 与 batch purge 分开测试，没有跨前端语义测试要求两种删除共享 terminal guard。

**建议最小修复：** 单删与批删共用 terminal purge guard；active task 409/前端禁用删除；取消只走明确 stop/cancel action。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-021 — Annotation material-state 把前 100 个 active task 当成全部真相

**级别：中**  
**模块：AI Annotation projection / performance correctness**

**现象：** `annotation_material_states()` 调用 `TaskRepository.list(..., limit=100)` 查询 AWAITING_CONFIRMATION/QUEUED/RUNNING/CANCEL_REQUESTED 的 AI_ANNOTATION + MATERIAL_BATCH。Repository 返回 `next_cursor`，但 endpoint 完全不继续读。

**真实调用链：** 查询最多 100 个 image ids → 只读取最近 100 个 active task → 忽略 next_cursor → 若目标 image 只存在第 101+ 个仍待审核/提交的任务 → 返回无 AI 状态。

**为什么是 Bug / 套娃：** 为性能做 bounded query 后，又把 bounded page 错当 canonical active truth；与 AUDIT-013 同类。

**影响：** >100 个待审核/提交 AI task 时，较老任务素材不显示 `awaiting_confirmation / committing`，用户可能重复发起 AI 标注或误判状态。

**为什么 CI 没发现：** 测试覆盖“请求最多100张”和“105条 terminal history 不挤掉 active task”，未覆盖 101+ 条同时 active review task。

**建议最小修复：** 不能无界 hydrate；应按 requested image ids 反向查 active candidate ownership，或做受控 cursor scan + 明确上限/索引；禁止 per-image N+1。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，需覆盖 101+ active review tasks。

---



### AUDIT-022 — Legacy Training Server 仍作为 ready target 展示，但 v12 Durable Training 不再按该服务器执行

**级别：高**  
**模块：Training Resource UI / training_options / Durable Training / CentralTaskAllocator**

**现象：**

`/api/training_options` 已经提供 canonical `cluster_scheduler`，但随后仍遍历 legacy `SERVERS_FILE`，把旧远程训练服务器按 `/api/remote/health` 的结果继续返回为 `type="server", status="ready", server_id=<legacy id>`。前端 `readyTargets429()` 只看 ready，因此旧服务器会真实进入训练创建弹窗。

**真实调用链：**

旧服务器 health 正常 → `/api/training_options` → `server:<id>` → TrainingSubmitRuntime → `target:"remote", server_id:"<legacy id>"` → v12 train/start → `_enqueue_explicit_training()`。

但 v12 只把 `server_id` 用来形成 `resource_key=training:remote:<id>`；CentralTaskAllocator 的真实节点亲和只认 `payload.scheduling.mode == "node"` 与 `scheduling.node_id`，不会按 legacy server_id 选节点。TrainingPrepare 还要求 canonical OSS/S3 可移植存储。

**为什么是 Bug / 套娃：**

UI 把“旧远程训练 HTTP 服务健康”误当成“当前 Durable Training 可执行目标”，但真实执行已经由 Service Node / Central Scheduler owner 接管。用户选择“服务器 A”并不能保证在服务器 A 执行。

**影响：**

- 选服务器 A，实际可调度到其它 Agent；
- 旧服务器健康但无 Service Node Agent 时仍会显示可用；
- 未配置 portable OSS/S3 时会在 preparation 阶段失败；
- 资源选择名称与真实执行节点不一致。

**为什么 CI 没发现：**

scheduler target 测试把 legacy server 列表置空；remote training API 测试反而明确验证“不需要 legacy server_id”，没有覆盖 legacy ready target 必须从当前 Durable Training UI fail-closed。

**建议最小修复：**

不恢复旧 direct remote training runtime。Training Create 只暴露 scheduler-owned remote target；legacy server 若保留只用于资源诊断。TrainingSubmit 对 `type=server && !scheduler_owned` fail-closed。未来指定节点必须走 canonical Service Node scheduling。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-023 — Cleaning 列表先截断 100 条 MATERIAL_BATCH 再筛 CLEAN，会丢活动清洗任务

**级别：中**  
**模块：Cleaning compatibility projection / PollRegistry / MaterialBatch**

**现象：**

`GET /api/v47/projects/{project_id}/clean-tasks` 最终调用 `_v47_list_durable_clean_tasks()`。该函数先执行 `TaskRepository.list(kinds={MATERIAL_BATCH}, limit=100)`，然后才读取 request 并筛 `operation == CLEAN`，且忽略 `next_cursor`。

TaskRepository 按 `created_at DESC, task_id DESC` 排序，所以这不是“最近 100 个清洗任务”，而是“最近 100 个所有 MaterialBatch 中恰好属于 CLEAN 的任务”。

**真实调用链：**

较老 CLEAN 仍 RUNNING / AWAITING_CONFIRMATION → 后续出现 100+ 个其它 MaterialBatch → CLEAN 被挤到第 101+ → v47 list 不再返回 → `refreshCleanOps427Delta()` 用该列表覆盖 `state.clean427` → PollRegistry 也根据当前列表决定是否继续 clean polling。

**为什么是 Bug / 套娃：**

bounded history 被放在 operation 过滤之前，又被兼容层当成完整 Cleaning truth。

**影响：**

- 活动清洗任务可从页面消失；
- 待确认清洗任务可能不可见；
- active clean 消失后页面可能停止 clean polling；
- Durable Task truth 与 UI truth 分裂。

**为什么 CI 没发现：**

现有测试覆盖 durable create/run/result/confirm 与 PollRegistry owner，但没有 100+ mixed MaterialBatch、active CLEAN 位于第 101+ 的组合。

**建议最小修复：**

禁止无界 hydration，也禁止 per-task N+1。优先让 canonical task query 可按 MaterialBatch operation 做可索引过滤；至少保证全部 active CLEAN 不会被 history window 截掉，terminal history 再独立 bounded。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，覆盖 100+ mixed MaterialBatch。

---


### AUDIT-024 — Remote Conversion 仍由 daemon thread 执行，绕过 canonical Durable MODEL_CONVERSION owner

**级别：高**  
**模块：Model Conversion / Deploy Resource / Durable Task Runtime / Recovery**

**现象：**

同一个：

`POST /api/v39/projects/{project_id}/deploy/jobs`

根据 Deploy Resource 的 mode 分成两套执行 owner：

- `mode=local` / `mode=agent`：写 `request.json`，创建 `TaskKind.MODEL_CONVERSION`，由 Durable Worker lease / heartbeat / recovery / cancellation 驱动；
- `mode=remote`：不创建 TaskRecord，直接启动 `threading.Thread(target=_sync_remote_deploy_job, daemon=True)`，状态只写 `job.json`。

当前前端仍允许用户新增“远程转换服务器”，检测 ready 后可直接在版本转换弹窗中选择，因此这不是 dead code。

**真实调用链：**

Deploy Resource `mode=remote`
→ `v39_create_deploy_job()`
→ `_v39_create_deploy_job_under_version_fence()`
→ 写 `job.json`
→ `threading.Thread(..., daemon=True).start()`
→ `_sync_remote_deploy_job()`
→ HTTP 调远端转换服务并轮询。

而 local/agent：
→ `shared_task_repository().create(TaskRecord.new(... TaskKind.MODEL_CONVERSION ...))`
→ canonical ConversionHandler
→ lease / heartbeat / process fencing / recover。

**为什么是 Bug / 套娃：**

同一种 MODEL_CONVERSION 存在两个 active runtime owner：

1. canonical Durable Task owner；
2. legacy in-process remote thread owner。

remote thread 没有：

- durable lease；
- Worker heartbeat；
- claim/reclaim；
- lease-loss fencing；
- crash/restart recovery；
- Central Scheduler / Worker visibility。

**额外确认的删除竞态：**

`_sync_remote_deploy_job()` 在线程进入 `try:` 之前先执行：

`_deploy_resource_by_id(job["resource_id"])`

而：

`DELETE /api/v39/deploy/resources/{resource_id}`

没有任何 active conversion reference guard，并会立即删除 secret。

如果资源在“job 已创建 / daemon thread 尚未完成 live resource lookup”窗口被删除：

- lookup 直接抛错；
- 因异常发生在 `try` 之前，线程自己的 failure/finally 逻辑都不会执行；
- job.json 可能继续保持 `queued`；
- `DEPLOY_REMOTE_THREADS` 也可能残留旧 entry。

即使线程已开始运行，平台进程重启也不会自动重建该 daemon thread，remote conversion 没有 Durable recovery owner 接管。

**影响：**

- 平台重启会让 remote conversion 丢执行者；
- 任务可能永久卡 queued/running；
- Stop 只能靠原线程观察 `cancel_requested`，重启后没有线程处理；
- Deploy Resource / API key 删除可破坏活动任务；
- remote conversion 无法享受当前已经实现的 conversion lease fencing / recovery；
- UI、job.json 与 Shared Task Repository truth 分裂。

**为什么 CI 没发现：**

现有 conversion unified truth / recovery / process fencing 测试都围绕 `TaskKind.MODEL_CONVERSION` canonical path；远程 Deploy Resource 测试主要覆盖资源检测/UI 展示，没有验证 remote mode 也必须创建 Durable Task。

**建议最小修复：**

不要新增第三套 remote runtime。

- remote resource 也统一创建 `TaskKind.MODEL_CONVERSION`；
- remote HTTP transport 只是 ConversionHandler 的一种 execution adapter；
- request artifact 冻结 remote resource snapshot + secret_ref identity；
- active task 期间 Deploy Resource / secret delete fail-closed；
- cancellation / restart recovery 全部复用 canonical TaskRepository；
- 退役 `DEPLOY_REMOTE_THREADS` 作为执行 owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 remote create → TaskRecord、restart recovery、delete resource fence、cancel、lease-loss / retry。

---


### AUDIT-025 — Deployment Conversion 最近 100 条窗口被当成完整任务 / 产物真相

**级别：中～高**  
**模块：Conversion task list / Deployment artifacts / Algorithm version deployments / Polling**

**现象：**

`v39_list_deploy_jobs(project_id)` 会扫描全部 `deploy/jobs/*/job.json`，按 `created_at` 倒序后直接：

`return {"items": rows[:100]}`

没有 cursor，也没有“active 全保留 + terminal history bounded”的语义。

这个 bounded 100 条窗口随后被多处当作完整真相：

1. `GET /api/v39/projects/{project_id}/deploy/jobs`：部署转换任务页；
2. 前端 `pollDeployJobs()`：整体覆盖 `state.deployJobs`，并按当前列表是否仍有 active job 决定是否继续 polling；
3. `v39_list_deploy_artifacts()`：直接遍历 `v39_list_deploy_jobs()["items"]` 构造部署产物；
4. `v423_version_deployments()`：同样遍历这 100 条，再按 algorithm/version 过滤版本转换历史。

**真实调用链：**

一个较老的 conversion 仍 RUNNING / WAITING_RESOURCE
→ 项目后续创建 100+ 个更新的 conversion job
→ 旧 active job 排到第 101+
→ `v39_list_deploy_jobs()` 不再返回
→ 前端任务页看不到它
→ 如果当前 100 条里没有其它 active，`armDeployPollV39()` 会停止 deploy polling。

对已完成历史也是同样：

某旧算法版本存在有效 ONNX/RKNN/TensorRT/OM/BMODEL conversion
→ 项目后来累计 100+ 个更新 conversion
→ 该 job 被窗口挤出
→ `/deploy/artifacts` 不再列出其产物
→ `/v42/.../versions/{version_id}/deployments` 也返回空或不完整。

**为什么是 Bug / 套娃：**

“最近 100 条任务列表”本来只是 UI history window，却被复用成：

- active execution visibility truth；
- artifact discovery truth；
- per-version conversion history truth。

bounded projection 反过来覆盖了 canonical lifecycle / artifact truth。

**影响：**

- 长时间运行的老 conversion 可从任务页消失；
- 页面可能提前停止 polling；
- 老版本已完成转换产物从“部署产物”页消失；
- 算法版本详情会误显示“暂无部署产物”；
- 用户可能重复发起转换；
- 已存在的 ModelArtifact / conversion files 并未真正删除，但 UI/API projection 丢失。

**为什么 CI 没发现：**

现有 conversion UI / API 测试主要覆盖少量 job；没有覆盖：

- 101+ conversion jobs；
- active job 位于第 101+；
- 老版本 conversion 位于第 101+；
- artifact/version projection 仍必须完整。

**建议最小修复：**

不要把 job list 改成一次性无界返回。

- active conversion 必须独立全量保留或按 Durable Task truth 合并；
- terminal history 用 cursor 分页；
- version deployments 应按 `algorithm_id + version_id` 定向查询，而不是先截全项目 100 条再过滤；
- deployment artifacts 应从 canonical ModelArtifact / conversion artifact index 查询，不依赖 UI history window；
- PollRegistry 只能根据完整 active truth 决定是否停止。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 101+ jobs 与 active/history/artifact/version 四条 projection。

---


### AUDIT-026 — 当前“素材接入”仍由 daemon thread 采集，绕过 Durable MATERIAL_IMPORT owner

**级别：高**  
**模块：素材接入 / Source Collection / Auto Scheduler / Durable Import**

**现象：**

当前最终可达的“素材接入”页面仍直接使用：

- `GET/POST/PUT/DELETE /api/v42/projects/{project_id}/sources`
- `POST /api/v42/projects/{project_id}/sources/{source_id}/collect`

手动采集：

`v42_collect()`

创建一条 JSON `collection_runs` 记录后，直接：

`threading.Thread(target=_v42_run_collect, daemon=True).start()`

自动采集则由另一个进程内：

`threading.Thread(target=_v42_source_scheduler_loop, daemon=True)`

每 20 秒扫描一次 Source。

整个链没有进入当前已经存在的 Durable `MATERIAL_IMPORT` owner。

**真实调用链：**

当前素材接入页面
→ `runSourceNow422()`
→ v42 source collect
→ collection_runs JSON = queued
→ daemon thread
→ 直接 folder / RTSP / HTTP JSON 拉取
→ `add_image_record()` 写素材。

自动模式：
→ startup 启动 daemon scheduler
→ `_v42_source_scheduler_once()`
→ `v42_collect()`
→ 再启动采集 daemon thread。

**为什么是 Bug / 套娃：**

同一种“外部素材采集 / 导入”存在两套 active execution owner：

1. canonical Storage Import / MATERIAL_IMPORT Durable Task；
2. v42 Source Collection daemon-thread runtime。

v42 runtime 没有：

- TaskRepository；
- Worker lease；
- heartbeat；
- claim/reclaim；
- crash recovery；
- canonical cancel；
- Central Scheduler / Service Node capability；
-统一 Material Import 审计链。

**重启后的确定性故障：**

如果平台在 collection run 为 `queued` 或 `running` 时重启：

- daemon worker 线程消失；
- `collection_runs` JSON 仍保留 queued/running；
- startup 只会重启 source scheduler，不会恢复具体 collection worker；
- `_v42_source_due()` 又看到该 source 的 last run 仍为 queued/running，于是返回 false；
- 该自动 Source 可能长期不再调度，除非人工修改/清理历史状态。

**影响：**

- 平台重启会丢正在采集的 Source task；
- 自动 Source 可永久卡成“运行中/排队中”；
- 没有可靠取消与恢复；
- 当前 Service Node / capability / storage import 调度完全绕过；
- Source Collection 与 Storage Import 形成重复 Owner；
- 状态只保存在 bounded JSON history，无法提供 durable execution truth。

**删除 Source 的边界：**

已启动 run 使用的是创建时传入的 source dict 快照，因此删除 Source 不一定中断当前线程；但它也意味着 Source lifecycle 与 collection lifecycle 没有 canonical reference fence，删除后历史 run 仍可能继续写素材。根问题仍是第二 Runtime owner。

**为什么 CI 没发现：**

现有 Source / Storage tests 主要覆盖 Storage Source Repository、v36 guard、Storage Import 等；没有覆盖当前 v42 Source Collection 的：

- restart recovery；
- stale queued/running；
- Durable Task ownership；
- auto scheduler 与 active run 的恢复。

**建议最小修复：**

不要再造新的 collection scheduler。

- v42 Source 只保留业务配置；
- “立即采集”和自动调度都创建 canonical `MATERIAL_IMPORT` / 统一 Import task；
- folder / RTSP / HTTP JSON 作为 Import source adapter；
- 自动周期只负责提交 Durable task，不自己执行素材采集；
- restart/cancel/retry/Service Node 调度全部复用 TaskRepository；
- 迁移时要处理现存 queued/running collection_runs 的 stale recovery。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 manual collect、auto collect、restart、stale running、cancel/retry、Source delete。

---


### AUDIT-027 — collection_runs 最近 100 条是运行状态唯一存储，active run 可被新任务物理挤掉

**级别：高**  
**模块：素材接入 / Collection Run State / Auto Scheduler / Concurrency**

**现象：**

创建 v42 Source Collection run 时：

`rows.insert(0, run)`
→ `_v42_save(project_id, "collection_runs", rows[:100])`

也就是说项目只持久化最近 100 条 collection run。

这不是单纯 UI history window，因为运行中的 daemon worker 更新状态时也是：

`_v42_collect_status()`
→ 重新读取 `collection_runs`
→ 找到相同 run_id 才更新
→ 再写回整个 JSON。

而 Source 调度判断同样依赖：

`_v42_source_last_run()`
→ 只从这份 bounded `collection_runs` 中找该 source 的最后一次 run。

**真实故障链：**

一个较老 collection run 仍 RUNNING
→ 项目其它 Source 又创建 100+ 个更新 run
→ 老 run 被 `rows[:100]` 物理丢弃
→ 原 daemon worker 继续执行，但后续 `_v42_collect_status(run_id,...)` 已找不到自己
→ progress / done / failed 状态全部无法再落库。

若该 run 属于 auto Source：

→ `_v42_source_last_run(source_id)` 也看不到这个 active run
→ `_v42_source_due()` 不再命中“last run queued/running”保护
→ scheduler 可能再次为同一 Source 启动新的 collection thread。

**为什么是 Bug / 套娃：**

一个 bounded history JSON 同时承担：

- active execution state；
- worker progress sink；
- scheduler mutual exclusion；
- recent history。

历史保留策略可以直接删除正在运行的状态 owner。

**影响：**

- 正在采集的任务从状态存储中消失；
- worker 完成/失败无法回写；
- UI runtime_status 与真实线程状态分裂；
- auto Source 可能并发重复采集；
- 同一图片来源可能重复入库；
- source cadence 也会因 last run 丢失提前触发。

**为什么 CI 没发现：**

当前没有覆盖 v42 collection 101+ runs 的测试，也没有“老 active run 被 history truncation 挤掉”的 scheduler concurrency test。

**建议最小修复：**

根修仍应随 AUDIT-026 收口到 Durable Import owner。

在迁移完成前至少必须：

- active run 绝不能被 history trimming 删除；
- terminal history 与 active state 分离；
- scheduler mutual exclusion 不能依赖 bounded history；
- 状态更新找不到 active run 时必须 fail-closed / 记录严重错误，不能静默成功。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 101+ runs、active run retention、重复调度防护。

---


### AUDIT-028 — 第 101 个素材源创建会静默物理删除最老 Source 配置

**级别：中～高**  
**模块：素材接入 / Source Configuration Persistence**

**现象：**

`v42_create_source()` 当前：

`rows.insert(0, item)`
→ `_v42_save(project_id, "sources", rows[:100])`

这不是 UI 分页，而是直接把 `sources.json` 持久化成最多 100 条。

因此项目已有 100 个 Source 时，再创建第 101 个：

- API 正常返回创建成功；
- 新 Source 被保留；
- 最老 Source 被静默从持久化配置中删除。

没有：

- 409；
- warning；
- archive；
- explicit delete；
- reference/lifecycle check。

**真实调用链：**

100 个现存 Source
→ 当前“素材接入”页面点击“新增素材源”
→ POST v42 sources
→ insert new source
→ save `rows[:100]`
→ oldest source 从 source config truth 消失。

若被挤掉 Source 为 auto：

→ startup/source scheduler 后续再也扫描不到它
→ 自动采集永久停止。

若它当时已有运行中的 collection：

→ 旧 daemon thread 仍可能按 source snapshot 继续本次采集
→ Source 配置和运行任务进一步分裂。

**为什么是 Bug / 套娃：**

“保留最近 100 条”这种 history retention 被错误用于长期配置 owner。

Source 是配置实体，不应因新增另一条配置而被隐式删除。

**影响：**

- 第 101 个 Source 会导致数据丢失；
- 自动采集配置可无提示消失；
- UI 只看到“新增成功”，用户无法知道另一条 Source 被删；
- running collection 可失去所属 Source 配置；
- 删除没有审计意图，难以追踪。

**为什么 CI 没发现：**

当前 Source UI/API 没有 100+ source persistence contract test。

**建议最小修复：**

- Source 配置不得用 `rows[:100]` 做物理 retention；
- 若产品真有数量上限，应在 create 前明确 409 并给出可操作提示；
- 更合理的是持久化全部 Source，UI 做分页/搜索；
- Source 删除只能走显式 DELETE owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖第 101 个 create 不得静默删除旧配置。

---


### AUDIT-029 — 第 101 个 Model Config 会静默删除最老配置并遗留 Keyring Secret

**级别：中～高**  
**模块：Model Config / Secret Lifecycle / AI Annotation Configuration**

**现象：**

当前正式“模型配置”页面使用：

`GET/POST/PUT/DELETE /api/v35/model-configs`

创建配置时：

`items.insert(0, item)`
→ `_v35_save_items(MODEL_CONFIGS_FILE, items[:100])`

因此第 101 个模型配置创建时，最老配置会被直接从 `MODEL_CONFIGS_FILE` 物理截断。

这不是前端分页，而是配置 owner 数据本身被删。

**额外 secret 泄漏：**

显式：

`DELETE /api/v35/model-configs/{config_id}`

会找到 removed config，并：

`_v35_secret_store().delete(secret_ref)`

但 create-time `items[:100]` 截断完全没有经过 DELETE owner。

所以被第 101 个配置挤掉的旧配置若带 API Key：

- config row 消失；
- Keyring secret 不删除；
- 形成不可从正常 UI 管理的 orphan secret。

**真实调用链：**

100 个 Model Config
→ 当前“模型配置”页新增第 101 个
→ POST v35 model-configs
→ 新 secret 先写 Keyring（若有）
→ new item 插到列表首位
→ save `items[:100]`
→ oldest config 静默丢失
→ oldest secret 仍留在 Keyring。

**为什么是 Bug / 套娃：**

长期配置实体被错误套用 history retention；同时 secret lifecycle 只有显式 DELETE 才能完成，截断路径绕过了 canonical secret cleanup。

**影响：**

- 模型配置无提示丢失；
- 默认 AI 模型可能被挤掉；
- 用户创建新配置却导致另一条配置消失；
- Keyring 出现 orphan secret；
- 后续 secret 审计 / rotation 无法通过配置列表定位该凭据；
- 若旧配置仍被其它持久化业务引用，UI 已经无法编辑/查看它。

**为什么 CI 没发现：**

现有 Model Config / secret tests 覆盖 create、sanitize、explicit delete 等，不覆盖第 101 个 config 的 persistence 与 secret cleanup。

**建议最小修复：**

- Model Config 不得用 `items[:100]` 做物理 retention；
- 若确有数量上限，create 前明确 409，不能隐式删除其它配置；
- UI 列表做分页/搜索即可；
- 所有配置删除必须只走显式 delete lifecycle，并处理 active durable reference（AUDIT-018）。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 101st create、old config retention、old secret retention/cleanup 语义。

---


### AUDIT-030 — Video Tasks 前端只消费第一页 50 条，把 cursor page 当完整 active truth

**级别：中**  
**模块：Video Frames / Frontend Pagination / PollRegistry**

**现象：**

后端：

`GET /api/v33/projects/{project_id}/video-tasks`

已经是正确的 Durable Task cursor API：

- 默认 `limit=50`
- 最大 100
- 返回 `next_cursor`

但最终前端 `refreshVideo424Delta()` 只请求该 endpoint 的第一页，读取 `response.items` 后直接覆盖 `state.video424`，完全不处理 `next_cursor`。

**真实调用链：**

项目存在 51+ 个 VIDEO_FRAMES task
→ 一个较老 active task 排在第 51+
→ 后端第一页只返回最新 50 条
→ 前端把第一页覆盖成全部 `state.video424`
→ active task 从页面消失。

PollRegistry 的 `replaceVideo424Timer()` 又只看当前 `state.video424` 是否存在 active task。

如果最新 50 条全部 terminal，但第 51+ 条仍 QUEUED / RUNNING / CANCEL_REQUESTED：

→ 前端判断“没有 active video task”
→ 停止 `video-frames` polling
→ 该任务之后即使进度变化也不会自动重新出现。

**为什么是 Bug / 套娃：**

后端已经把“分页”与“任务真相”边界设计正确，但前端 compatibility page 把单页 projection 当全量 active truth。

**影响：**

- 第 51+ 个 active 视频切帧任务从 UI 消失；
- 轮询可能提前停止；
- 用户可能重复创建任务；
- 老任务历史无法通过当前页面继续浏览；
- 后端 Durable Task 仍真实运行，UI 与 TaskRepository 分裂。

**为什么 CI 没发现：**

现有 video API/frontend/browser tests 覆盖 create/list/stop、row patching、性能，但没有：

- 51+ tasks；
- `next_cursor` 消费；
- active task 位于第二页；
- 第一页全 terminal、第二页仍 active 的 polling 场景。

**建议最小修复：**

不要无界一次性 hydrate 全历史。

- active VIDEO_FRAMES 必须单独完整保留；
- terminal history 使用 cursor 分页；
- 前端页面可分页/加载更多；
- PollRegistry 是否继续轮询只能基于完整 active truth，不能只看第一页 history。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖第二页 active task 与 polling continuity。

---


### AUDIT-031 — Label 停用可在 Training PREPARING 阶段破坏尚未冻结的继承标签合同

**级别：高**  
**模块：Label Governance / Durable Training / TRAINING_PREPARE / Iteration**

**现象：**

v12 Training 创建时先受理：

- `TRAINING`
- `TRAINING_PREPARE`

但此时还没有冻结 `effective_label_schema / label_contract`。

真正的标签合同是在 TrainingPrepare Worker 的：

`_freeze_request_contract()`

里实时调用：

`resolve_training_label_contract()`

后才写进 `input-freeze.json`。

与此同时：

`DELETE /api/v12/projects/{project_id}/labels/{class_id}`

只检查当前 AnnotationRepository 是否仍引用该标签。若当前素材已没有该标签的正式框 / confirmed_empty scope，就允许把标签 soft-delete 为 inactive。

**真实调用链：**

迭代训练提交
→ 上一算法版本 `label_schema` 含 inherited label A
→ Training / TRAINING_PREPARE 已创建，但 label contract 尚未冻结
→ 当前素材已无 A 引用
→ 用户在标签管理停用 A
→ label delete 成功，A 变 inactive
→ TrainingPrepare 执行
→ `resolve_training_label_contract()`
→ `_resolve_inherited_label_governance()`
→ 发现上一版本标签 A 当前 inactive 且无 `merged_into`
→ 明确 fail-closed
→ 已受理 Training preparation 失败。

**为什么是 Bug / 套娃：**

Label delete owner 只看“当前 Annotation truth 是否引用”，没有看“已受理但尚未 freeze 的 Training contract 是否引用”。

因此标签生命周期可以在 Training 输入冻结前破坏已经受理的迭代任务。

**影响：**

- 用户看到训练任务创建成功，随后停用一个“当前无素材”的历史标签，会把任务打失败；
- 迭代继承标签合同与 Label Governance truth 发生 TOCTOU；
- PREPARING Training 不能保证提交时看到的继承标签仍可冻结；
- 问题只发生在 freeze 前，freeze 完成后的历史 schema 本身仍是不可变的。

**为什么 CI 没发现：**

现有 label governance 测试覆盖：

- 有 AnnotationRepository 引用时禁止删除；
- governance lock 重检；
- soft delete 保留 class_id。

现有 Training 测试覆盖 label contract / inherited schema，但没有：

`Training accepted -> label inactive -> TRAINING_PREPARE freeze`

这个跨 owner 并发窗口。

**建议最小修复：**

不要把重型 label contract 解析重新塞回前端弹窗。

优先在 canonical label mutation owner 增加 active Training pre-freeze reference fence：

- 检查 PREPARING / QUEUED 且尚未形成 `input-freeze.json` 的 Training；
- 若其 previous-version inherited schema / requested labels 引用目标 code，则停用 409；
- freeze 完成后由 frozen contract 自己持有历史 truth；
- 查询必须 cursor / indexed，禁止无界扫描。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 inherited label、PREPARING、freeze 后三个窗口。

---

### AUDIT-032 — 直接修改 Label code 会破坏历史算法版本的迭代继承链

**级别：高**  
**模块：Label Governance / Algorithm Version lineage / Iteration Training**

**现象：**

当前标签管理 UI 明确允许编辑英文标签编码，并调用：

`PUT /api/v12/projects/{project_id}/labels/{class_id}`

后端只在旧 code 仍被当前 AnnotationRepository 引用时阻止改名。

如果当前已经没有素材引用，接口会直接：

`labels[class_id] = new_code`

并把当前 `label_meta[class_id].code` 更新为 new_code。

它不会保留：

- old_code governance row；
- `status=merged`；
- `merged_into=new_code`；
- 历史算法版本引用迁移记录。

**真实调用链：**

历史算法版本 `label_schema = [old_code, ...]`
→ 当前素材已不再引用 old_code
→ 标签管理把 old_code 改成 new_code
→ PUT 成功
→ 当前 project governance 中 old_code 彻底消失
→ 下一次从历史版本迭代
→ `resolve_training_label_contract()`
→ `_resolve_inherited_label_governance()`
→ `governance.get(old_code) is None`
→ 明确报“上一算法版本标签 old_code 已不在当前项目标签治理中”
→ 迭代无法继续。

**为什么是 Bug / 套娃：**

算法版本的历史 `label_schema` 是不可变 lineage truth，但 Label code rename owner 只尊重当前 Annotation truth，没有尊重历史 version reference。

这不是单纯显示名修改，而是在改 canonical identity。

**影响：**

- 一个看似合法的标签改名可以永久阻断旧版本迭代；
- 历史版本仍保存 old_code，但当前 governance 无法解释 old_code 到 new_code 的关系；
- 用户只能人工恢复旧标签或另做统一，形成不可预期维护成本；
- 和当前“统一标签必须显式产生 merged_into”治理合同不一致。

**为什么 CI 没发现：**

现有测试只证明：

- old_code 有当前标注引用时 rename 必须 409；
- lock 后会重新检查 AnnotationRepository。

没有测试：

`old_code 无当前标注引用，但仍被 algorithm version label_schema 引用`

这一 lineage 场景。

**建议最小修复：**

不要允许 canonical code 在存在历史 version 引用时被裸改名。

最小方向二选一：

1. 历史版本仍引用 old_code 时，普通 PUT code rename 直接 409，提示走“统一标签”；或
2. code rename 本身升级为正式治理迁移，保留 old_code 为 `merged -> new_code` 的 lineage edge。

优先方案 1，避免把普通编辑接口变成第二套标签迁移 owner。

显示名 / 颜色 / 快捷键等非 identity 字段仍可正常修改。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖历史 version 引用、无 annotation 引用、普通 rename 必须 fail-closed。

---


### AUDIT-033 — AI Annotation 任务列表只消费第一页 50 条，active task 可消失并停止轮询

**级别：中～高**  
**模块：AI Annotation / Task Pagination / AutoLabelPollRuntime / PollRegistry**

**现象：**

后端 `GET /api/v60/projects/{project_id}/annotation-tasks` 已提供 cursor 分页，返回 `items + next_cursor`。

但当前最终 AI 标注页面固定请求 `?limit=50`，随后直接用 `response.items` 覆盖 `state.annotationTasks60`，完全不消费 `next_cursor`。

独立 `AutoLabelPollRuntime` 的默认 loader 也再次固定请求 `/annotation-tasks?limit=50`，并且 `activate()/schedule()` 只依据这 50 条中是否存在 active task 决定是否继续轮询。

**真实调用链：**

项目存在 51+ 个 AI_ANNOTATION task
→ 较老 QUEUED / RUNNING / CANCEL_REQUESTED task 位于第 51+
→ 页面刷新只拿最新 50 条
→ active task 从 `state.annotationTasks60` 和任务表消失。

如果前 50 条都已终态：

→ `hasActiveAutoLabelTask(firstPage) == false`
→ `AutoLabelPollRuntime.schedule()` 不再注册 `auto-label-v60`
→ 第 51+ 个 active task 后续状态变化不会被页面自动发现。

**为什么是 Bug / 套娃：**

后端 cursor API 只是 bounded history projection；前端却把单页同时当成：

- 完整任务列表；
- active-task truth；
- polling lifecycle truth。

**影响：**

- 第 51+ 个 active AI 标注任务从 UI 消失；
- 自动轮询可能提前停止；
- 用户可能误以为任务不存在并重复创建；
- 较老 AWAITING_CONFIRMATION 任务也可能不再出现在任务表；
- Durable Task 仍真实存在，但 UI / PollRegistry 看不到它。

**为什么 CI 没发现：**

现有 frontend/browser 测试明确验证当前 `?limit=50` 行为，主要覆盖少量 active task 的 row patching / PollRegistry；没有覆盖：

- 51+ annotation tasks；
- task-list `next_cursor`；
- active task 位于第二页；
- 第一页全 terminal、第二页仍 active。

Candidate Review 自身的候选分页测试属于另一个 endpoint，不能覆盖任务列表分页。

**建议最小修复：**

不要无界一次性 hydrate 全任务历史。

- active AI_ANNOTATION task 必须独立完整保留；
- terminal history 使用 cursor 分页 / 加载更多；
- AutoLabelPollRuntime 是否继续轮询只能基于完整 active truth；
- 页面 history 与 active execution truth 分离，但仍共享 canonical TaskRepository owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖第 51+ 个 active task 与 polling continuity。

---


### AUDIT-034 — 第 201 个 Prompt Template 会静默物理删除最老模板

**级别：中**  
**模块：Prompt Template / Model Config UI / AI Annotation Configuration**

**现象：**

当前正式“模型配置”页面直接维护：

`GET/POST/PUT/DELETE /api/v35/prompt-templates`

创建模板时：

`items.insert(0, item)`
→ `_v35_save_items(PROMPT_LIBRARY_FILE, items[:200])`

因此已有 200 个 Prompt Template 时，再创建第 201 个：

- API 正常返回创建成功；
- 新模板被保存；
- 最老模板被静默从 `PROMPT_LIBRARY_FILE` 物理删除。

这不是前端分页，也没有显式删除意图。

**当前影响边界：**

modern AI Annotation 在任务创建时会冻结实际 prompt / template snapshot，因此已经受理的 Durable AI task 不会因为旧模板被截断而换 prompt 或直接失败。

问题发生在长期配置 owner 本身：

- 老模板从模型配置页消失；
- 后续新任务无法再选择该模板；
- 依赖该模板 ID 的其它配置/历史 UI 可能失去可解析对象；
- 用户只看到“新增成功”，不知道另一条配置同时被删除。

**为什么是 Bug / 套娃：**

长期配置实体被错误套用了“只保留最近 N 条”的 history retention 逻辑。

Prompt Template 的删除已经有显式 DELETE owner；create-time truncation绕过了该 lifecycle。

**为什么 CI 没发现：**

现有 Prompt Template 测试关注校验、版本化、render/preview 与正常 CRUD，没有第 201 个 template 的持久化合同测试。

**建议最小修复：**

- Prompt Template 不得用 `items[:200]` 做物理 retention；
- UI 如需性能优化应做分页 / 搜索；
- 如果产品真要硬上限，应在 create 前明确 409 并提示用户清理，不能隐式删除最老配置；
- 配置删除只走显式 DELETE owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖第 201 个 create 不得静默删除旧模板。

---


### AUDIT-035 — Algorithm Blueprint 第 201 条创建会静默丢失最老蓝图，与 Algorithm Asset 分裂

**级别：中**  
**模块：Algorithm Blueprint / New Algorithm UI / Algorithm metadata projection**

**现象：**

当前“新建算法”页面真实调用：

`POST /api/v42/projects/{project_id}/algorithm-blueprints`

后端先调用 `v12_create_algorithm(...)` 创建正式 Algorithm Asset，再创建 blueprint，并执行：

`blueprints.insert(0, item)`
→ `_v42_save(..., blueprints[:200])`

因此第 201 个 blueprint 会把最老 blueprint 从持久化 truth 中静默删除，但对应 Algorithm Asset 不会同步删除。

**真实调用链：**

已有 200 个 Blueprint
→ 新建第 201 个算法
→ Algorithm Asset 创建成功
→ 新 blueprint 创建成功
→ `blueprints[:200]`
→ oldest blueprint 被物理丢弃
→ oldest Algorithm Asset 仍存在。

当前前端仍读取 `state.v42.blueprints` 用于：

- Dashboard blueprint 统计；
- Algorithm list 的 labels / industry 辅助信息；
- algorithm type / industry fallback；
- 新建算法相关展示。

**为什么是 Bug / 套娃：**

Algorithm Asset 与 Blueprint 是两个持久化实体，但 Blueprint owner 用 history retention 隐式删除长期配置，且没有同步 lifecycle / 审计动作。

**影响：**

- 老算法对应的 labels/focus_scenes/negative_scenes 等蓝图元数据无提示丢失；
- Dashboard blueprint 数量失真；
- Algorithm list 部分辅助元数据退化；
- Algorithm Asset 与 Blueprint 关系被破坏；
- 用户无法知道创建新算法导致另一算法蓝图被删。

**为什么 CI 没发现：**

现有新建算法/UI 测试没有 201+ blueprint persistence contract，也没有 Algorithm Asset ↔ Blueprint retention consistency test。

**建议最小修复：**

Blueprint 不得用 `[:200]` 做物理 retention；若它仍是正式业务实体，应持久化全部并由 UI 分页。若未来确认可完全归并到 Algorithm Asset，需另做显式迁移，不能靠截断隐式退役。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-036 — Detection Batch 用全项目 DEPLOYMENT_TEST 扫描上限代替 batch index，1k/10k 规模会截断批次真相

**级别：中～高**  
**模块：检测台 / Detection Batch / DEPLOYMENT_TEST / 性能与历史真相**

**现象：**

Detection Batch 并没有独立 batch index，而是每次从整个项目的 `TaskKind.DEPLOYMENT_TEST` 里按时间倒序扫描 request artifact，再判断：

`request.detection_batch.batch_id`

当前固定上限：

- 批次列表：`scan_limit=1500`
- 指定批次详情：`scan_limit=5000`
- 单图人工复核：`scan_limit=5000`

后端创建接口却允许：

`detection_item_total <= 100000`

且 A/B 对比模式每张图会创建 A、B 两个 DEPLOYMENT_TEST task。

**真实调用链：**

1,000 张图 A/B 对比
→ 约 2,000 个 DEPLOYMENT_TEST task
→ `GET /api/v64/.../detection-batches`
→ 只扫描最近 1,500 个 task
→ 当前批次只能聚合出约 750 张图对应的两侧结果，或形成不完整 side 集合
→ summary 的 `created_items/completed_items/failed_items` 与真实批次不一致。

更大批次：

2,500+ 张图 A/B
→ 超过 5,000 task
→ 指定 `batch_id` 的详情 / review 仍只扫描最近 5,000 条
→ 同一批次后半部分任务不可见。

历史场景：

某旧 batch 的 task 整体被后续 5,000+ 个 DEPLOYMENT_TEST 推出窗口
→ 按明确 batch_id 查询
→ 扫描不到任何 row
→ API 返回 404“检测批次不存在”
→ 但 Durable Task / artifacts 仍真实存在。

**为什么是 Bug / 套娃：**

`scan_limit` 本来是保护读性能的 bounded scan，却被当作 Detection Batch 的身份索引和完整聚合 truth。

这不是单纯“历史只显示最近 N 条”，因为：

- 指定 batch ID 的 detail 也受同一全项目窗口限制；
- review 写入依赖这次扫描结果；
- 同一个大批次本身就可能超过扫描上限；
- API 明确允许远大于该上限的 batch size。

**影响：**

- 1k 图 A/B 批量检测的列表摘要已经可能不完整；
- 大批次详情丢部分图片/模型侧；
- 人工复核可能找不到真实存在的 item；
- 老批次按 ID 查询可误 404；
- 用户可能误认为检测丢失或重复发起测试；
- 10k/20k 规模下顺序扫描大量 request/result artifact 也会形成明显 I/O 放大。

**为什么 CI 没发现：**

当前测试主要使用小批次，没有覆盖：

- 1,000 图 / 2,000 task；
- 单 batch 超过 1,500 / 5,000 task；
- 旧 batch 位于第 5,001+ 个 Deployment Test；
- review 在窗口外 item 上仍需工作。

**建议最小修复：**

不要把 `scan_limit` 简单改成无界。

建立一次写入、可索引的 batch ownership truth，例如 canonical batch_id/item_index/side 索引表或 TaskRepository 可查询 metadata index：

- batch list 按 batch entity 分页；
- batch detail 按 `batch_id` 定向查；
- review 按 `batch_id + item_index` 定向查；
- active task 仍由原 TaskRepository owner；
- 禁止为每个图片 N+1 扫全项目任务。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 1k、5k+ task、旧 batch 定向查询和 review。

---


### AUDIT-037 — Training Settings 仍提供“AI 中途介入”，但 canonical submit 与后端都会静默强制关闭

**级别：中～高**  
**模块：Training Settings / TrainingSubmitRuntime / TrainReq**

**现象：**

当前训练设置弹窗仍真实展示完整“AI 中途介入”配置，包括：

- 启用开关；
- 介入 Epoch；
- AI 模型；
- 每次抽样数；
- 可追加轮数；
- 最大介入次数；
- 自动执行 / 只给建议。

`saveTrainSettings425()` 还会真实校验：

- 开启后必须填写介入轮次；
- 开启后必须选择 AI 模型；

并把配置写入 `state.train425Config`。

但 canonical：

`buildTrainingEngineParameters()`

直接硬编码：

`ai_intervention_enabled: false`

并完全不提交其它 AI 介入字段。

后端 `validate_train_request()` 又再次无条件执行：

- `payload.ai_intervention_enabled = False`
- `payload.ai_intervention_epochs = []`
- `payload.ai_model_config_id = ""`

**真实调用链：**

用户打开训练设置
→ 勾选“AI 中途介入”
→ 选择模型 / Epoch / 自动执行
→ 前端保存成功
→ TrainingSubmitRuntime build payload
→ 强制 `ai_intervention_enabled=false`
→ v12 Training 创建成功
→ 训练从未执行用户刚配置的 AI 介入。

即使第三方直接调用 API 带上 AI 介入字段：
→ Pydantic 接受
→ `validate_train_request()`
→ 静默改为关闭。

**为什么是 Bug / 套娃：**

这是明确的 UI / API / runtime 合同分裂：

- UI 宣称支持并要求用户配置；
- Schema 仍公开这些字段；
- canonical submit 静默丢弃；
- backend runtime 静默覆盖。

它不会 fail-fast，用户只能在训练结束后发现功能从未生效。

**影响：**

- 用户以为 AI 会在指定 Epoch 介入，实际不会；
- 用户选的模型 / 轮次 / 行为模式全部无效；
- 训练结果与界面承诺不一致；
- 排查时 payload / job truth 也无法解释用户曾开启过该功能；
- 属于高误导性的 silent no-op。

**为什么 CI 没发现：**

现有测试把“v42.8 起 AI 中途介入禁用”视为 backend 行为，但没有前端合同测试要求：

“既然后端永久禁用，该配置区不得继续作为可用能力展示”。

**建议最小修复：**

当前不要重新实现第二套 AI Training runtime。

最小修复应 fail-closed：

- 从当前 Training Settings 移除 / 禁用“AI 中途介入”可编辑区，并明确当前未开放；
- TrainReq Schema 同步移除或正式标记 retired 字段；
- canonical submit 不再保留伪配置；
- 若未来重新上线，必须重新走一个明确的 Training runtime contract，而不是恢复旧 v42 旁路。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖当前设置 UI 不得呈现可提交的 AI intervention，以及 API 不再宣称支持已退役能力。

---


### AUDIT-038 — Cleaning confirm 缺少状态 guard，可提前确认仍在运行的 CLEAN

**级别：高**  
**模块：Cleaning / MaterialBatch lifecycle / Confirmation**

**现象：** v47 clean confirm 只验证 task 属于 CLEAN 兼容列表，没有验证 Durable Task 当前状态。QUEUED / RUNNING / CANCEL_REQUESTED 也能进入 confirmation。

**真实调用链：** RUNNING CLEAN → 提前调用 confirm → 读取当时已有的部分 clean_results → 可删除部分问题图 → 读取冻结 selection → 把 selection 中所有仍存在素材批量写成 processing_status=processed、cleaned_at、clean_task_id → 写 clean_confirmation.json → 原 Worker 仍继续执行剩余图片。

**为什么是 Bug / 套娃：** Confirmation owner 应只消费稳定的执行结果，但当前没有 execution-state fence，material truth 可与仍在运行的 CLEAN execution 并发提交。

**影响：** 未清洗完素材可提前显示已处理；只删除到部分已发现问题；后续 Worker 新结果与已确认 truth 分裂；重复确认也缺少明确状态幂等边界。

**为什么 CI 没发现：** 测试覆盖正常 SUCCEEDED → awaiting_confirmation → confirm 和 frozen selection，没有 QUEUED/RUNNING/CANCEL_REQUESTED confirm 负向用例。

**建议最小修复：** confirm 仅允许 canonical AWAITING_CONFIRMATION；其它状态 409；confirmation 与 task 状态转换共享 lifecycle fence；素材删除继续复用 canonical Material deletion owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-039 — Clean stop endpoint 可取消任意 MATERIAL_BATCH，未校验 operation=CLEAN

**级别：中**  
**模块：Cleaning / MaterialBatch cancel owner**

**现象：** POST /api/v47/projects/{project_id}/clean-tasks/{task_id}/stop 只校验 task 存在、project 相同、kind=MATERIAL_BATCH，随后直接 request_cancel(task_id)，没有校验 request operation。

**真实调用链：** 同项目 REMAP / DELETE / AI_ANNOTATE 等任意 MATERIAL_BATCH task_id → 调 clean-specific stop endpoint → kind 检查通过 → 该非 CLEAN 批任务被取消。

**为什么是 Bug / 套娃：** operation-specific Cleaning facade 获得了整个 MATERIAL_BATCH kind 的取消权限，越过自己的 owner scope。

**影响：** 标签统一、删除、AI batch 等任务可被错误 clean endpoint 停止；API path 与实际被修改对象不一致。

**为什么 CI 没发现：** 没有“非 CLEAN MATERIAL_BATCH + clean stop endpoint”负向测试。

**建议最小修复：** stop 前读取 canonical material batch request，operation 不是 CLEAN 时 404/409；通用取消继续只由 v62 canonical task cancel owner 负责。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

## 4. 已复核安全 / 不应误报的部分

### Annotation 正式保存合同

当前前端提交与后端一致：

- boxes
- annotation_state
- expected_version

并且：

- confirmed_empty 正式进入 Ground Truth；
- concurrent modification fail-closed；
- 标签失效 fail-closed；
- AnnotationRepository 仍是唯一 GT owner。

### AI Annotation

当前 Candidate → Review → Decisions → Commit 主链没有发现 AI 直接写正式 AnnotationRepository 的旁路。

旧：

- `/api/v33`
- `/api/v35`

direct prelabel write/create endpoint 已通过 `_reject_legacy_direct_prelabel()` 固定 409。

### 旧 v42 自动迭代

policy 创建/修改、旧 feedback 写入和 run 入口已经走 `_legacy_iteration_write_disabled()` 返回 410。

历史函数仍存在，但当前不可启动，不登记生产 Bug。

### ZIP 双 Poller

旧 app.js fallback polling 在 600ms 后才尝试启动。

现代 `zip-import-bootstrap.mjs` 安装时会：

1. 清掉已存在的 `state.importPollTimer`；
2. 将该槽位置为 sentinel `-1`；
3. 阻止 legacy `startImportPolling()` 再创建 interval。

因此正常 bootstrap 下没有两个常驻 ZIP polling owner。

### Cleaning 双 Poller

最终 `showTaskProgress427()` 对 clean 会转到 `showCleanTaskProgress429()`，由 PollRegistry 管理。

旧 `showTaskProgressCore427()` 的原生递归 timer 对当前 clean/AI 正常入口不可达。

### Conversion 删除

`v39_delete_deploy_job()` 已同时保护：

- running / queued / waiting_resource / cancel_requested / stopping 等 active 状态；
- successful conversion；
- canonical ModelArtifact reference。

当前没发现绕 ModelArtifact owner 的删除旁路。

### Service Node 删除

`ServiceNodeRepository.delete()` 已检查：

- live workers；
- RUNNING / CANCEL_REQUESTED tasks。

存在时返回：

`SERVICE_NODE_BUSY / 409`

因此“删除节点”当前没有发现和 AUDIT-014 同类的直接生命周期绕过。

另外已确认：节点停用后，已经进入 RUNNING 的 execution 仍可继续 heartbeat / logs / result upload / finalization / finish；这一部分安全。pre-start ASSIGNED / CLAIMED 的停用缺口单独登记为 AUDIT-015。

### ModelArtifact / External Publish storage owner

External publication 不再持久化第二套 legacy storage truth。

ModelArtifactRuntime 仍是 canonical 模型产物 owner。

### RKNN 产品芯片

当前仍只开放：

- RK3568
- RK3576

没有把 RK3578 / RK3588 意外重新开放。

---

## 5. 当前仍在复核、尚未编号

### 其它待继续项

1. 真实 FastAPI route table 全局 uniqueness；
2. Router factory 内部 nested include 横向审计；
3. Training request 全字段前后端合同；
4. Annotation / AI review overwrite scope；
5. Storage Import 单任务 lifecycle；
6. MaterialBatch / Cleaning cancel / confirmation；
7. Agent claim/start/upload/finalization/finish 组合测试；
8. 全局可写 Legacy opener / save / delete / confirm；
9. 页面状态枚举是否存在其它 legacy/canonical 漂移；
10. 其它 deletion/retirement API 是否仍绕过 durable references；
11. 1k / 10k / 20k 下无界 hydration、N+1、O(N²)；
12. build/cache identity 统一。

---

## 6. 当前修复优先级

审计尚未全部完成，当前建议顺序：

1. **AUDIT-002** — Router 非法套娃 / 27 组重复 method+path / 残缺 Agent Router
2. **AUDIT-011** — 整算法删除绕过 Version Retirement
3. **AUDIT-017** — Image 删除绕过 MaterialBatch / active Training fence
4. **AUDIT-015** — Service Node disable 卡死 pre-start assignment / GPU reservation
5. **AUDIT-014** — ZIP active job 可被直接 DELETE
6. **AUDIT-020** — Training 单删隐式 cancel，和批删合同冲突
7. **AUDIT-016** — Storage Source 删除破坏活动 import/rescan
8. **AUDIT-019** — Dataset delete 破坏 Training PREPARING pre-freeze selection
9. **AUDIT-018** — Model Config delete 提前销毁 Durable AI task secret
10. **AUDIT-009** — Paddle Training 前端可选、后端必失败
11. **AUDIT-010** — Training Settings 重复 DOM / 双参数 UI owner
12. **AUDIT-021** — AI material-state 只看前 100 个 active task
13. **AUDIT-003 / AUDIT-004** — API Schema 与 runtime 漂移
14. **AUDIT-005** — Modal close scope
15. **AUDIT-013** — 训练次数统计 truth
16. **AUDIT-008** — Legacy Annotation 全局写入口
17. **AUDIT-006** — build/version truth
18. **AUDIT-001 / AUDIT-007** — 重复 helper / dead modalStack owner

修复前仍应完成剩余高风险审计，避免同一 owner 附近还有第二条旁路。

---

## 7. 后续修复硬规则

继续遵守：

- 不 merge main；
- 不 tag；
- 不 release；
- 不 force push；
- 不删除测试；
- 不放宽测试；
- queued / in_progress 不能算 success；
- 每个正式 commit `VERSION.txt` 最小 patch +1；
- 不写死 Windows 路径；
- 不重新设计已 CLOSED 架构；
- 不新增第二 Annotation GT；
- 不新增第二 TrainingTaskRuntime；
- 不新增第二 Scheduler；
- 不新增第二 Resource Planner；
- 不新增第二 GPU reservation owner；
- 不新增第二 CandidateStore；
- 不新增第二 ZIP owner；
- 不新增第二 ModelArtifact owner；
- 不新增第二 publication owner；
- 不新增第二 conversion artifact identity；
- 不新增第二 staging GC owner；
- 删除 Legacy owner 前必须证明 zero-reference；
- 性能继续按 1k / 10k / 20k 检查；
- 禁止 N+1 / O(N²) / 无界 hydration / 无界远端 reconciliation。

---

## 8. 新会话恢复方式

新会话应先重新读取远端真实 HEAD / VERSION / Actions / check-runs，再读取本文档。

不能把本文档中的 HEAD 当作当前真实 HEAD。

继续审计时：

- Service Node 停用语义已确认并登记 AUDIT-015；后续从剩余 T1～T8 审计点继续；
- 发现疑点先复核；
- 确认后从 `AUDIT-040` 起继续编号；
- 如果后续证据推翻已登记项，必须像 AUDIT-012 一样显式撤销；
- 当前仍以审计为主，不要直接大改生产代码。
