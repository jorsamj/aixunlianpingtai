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
> 上一批审计记录提交后 VERSION：`42.24.126`  
> 上一批审计记录提交后 VERSION：`42.24.127`  
> 上一批审计记录提交后 VERSION：`42.24.128`  
> 上一批审计记录提交后 VERSION：`42.24.129`  
> 上一批审计记录提交后 VERSION：`42.24.130`  
> 上一批审计记录提交后 VERSION：`42.24.131`  
> 上一批审计记录提交后 VERSION：`42.24.132`  
> 本批审计记录提交后 VERSION：`42.24.133`  
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


### AUDIT-037 — 已撤销：AI 中途介入设置并非当前 canonical Training Settings 可达入口

**状态：撤销，不计入确认问题**

最初根据 `openTrainSettings425()` / `saveTrainSettings425()` 中仍存在完整“AI 中途介入”控件，误判其为当前训练设置入口。

继续按最终浏览器调用链复核后确认：

- 当前算法卡最终训练入口为 `startAlgorithmTraining429`；
- 文件后部明确执行 `startAlgorithmTraining429 = openTrainingCreateCanonical429`；
- 同时把 `startAlgorithmTraining423` 也重定向到同一个 canonical 429 owner；
- 当前训练创建页“编辑全部训练参数”调用 `openTrainSettings429()`；
- `openTrainSettings429()` 实际调用 `openTrainSettings428()`，其中没有 AI 中途介入区域；
- `startAlgorithmTrainingLegacy423_2` 在当前生产静态代码中只有定义，没有其它调用；
- `openTrain425()` 只有 Legacy 定义以及上述 zero-reference Legacy wrapper 内部调用；
- `openTrainSettings425()` / `saveTrainSettings425()` 只存在于该旧 425 Modal 内部；
- `static/main.mjs`、当前 algorithm/training modules、index.html 均没有引用这些 425 Legacy 入口。

因此：

旧 425 AI intervention UI 当前属于 **zero-reference Legacy UI**，不能按生产可达 Bug 登记。

后端 / Schema 仍保留并强制关闭 AI intervention 字段，可作为后续 API/Legacy 清理债审查，但在没有新的真实可达证据前，不再声称“当前用户能配置后被静默丢弃”。

**结论：撤销，不修；编号保留，不复用。**




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


### AUDIT-040 — 第 21 个 Legacy Training Server 会静默物理删除最老服务器配置

**级别：中**  
**模块：Training Resource / Legacy Training Server Configuration**

**现象：**

当前“训练资源”页面仍提供：

- “训练服务器”；
- “接入服务器”；
- `quickAddServer()` / `saveServer()`。

保存调用：

`POST /api/train_servers`

后端：

`save_train_server()`

执行：

`servers.insert(0, item)`
→ `write_json(SERVERS_FILE, servers[:20])`

因此已有 20 条服务器配置时，第 21 条创建会正常返回成功，但最老一条服务器配置会被静默从持久化文件中删除。

**真实调用链：**

当前训练资源页
→ “接入服务器”
→ `saveServer()`
→ POST `/api/train_servers`
→ 新配置插入首位
→ `servers[:20]`
→ oldest server 被物理丢弃
→ 前端重新拉 `/api/training_options`，只看到剩余 20 条。

**为什么是 Bug / 套娃：**

这是把“UI/history 数量上限”错误实现成长期配置 owner 的物理 retention。

Training Server 是显式配置实体，删除应只通过明确 DELETE；新增另一条服务器不能隐式删除已有配置。

并且这些 legacy server 当前仍被 `/api/training_options` 消费，AUDIT-022 已确认它们仍能进入训练资源 target，因此这不是 zero-reference 配置。

**影响：**

- 第 21 个服务器创建时会无提示丢一条旧配置；
- 用户无法知道哪条服务器因新增被删除；
- training_options / 资源页目标集合会突然变化；
- 如果用户仍依赖旧资源做诊断或兼容任务，其配置会丢失；
- 无显式删除审计意图。

**为什么 CI 没发现：**

当前 training-server 前端测试只验证：

- `saveServer` 是唯一最终保存 owner；
- 保存后 scoped refresh `/api/training_options`；
- navigation race fencing。

没有 21+ server persistence / retention 测试。

**建议最小修复：**

结合 AUDIT-022 一起收口，不新增新的 Training Server owner。

- 不再使用 `servers[:20]` 做物理持久化裁剪；
- 若产品确实需要硬数量上限，应在 create 前明确 409，并告诉用户先显式删除；
- 如果 legacy server 最终只保留诊断用途，则先完成 canonical Training target fail-closed，再按 zero-reference / migration 规则退役；
- 显式 DELETE 仍是唯一删除入口。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖第 21 条 create 不得静默删除旧配置。

---


### AUDIT-041 — 质量中心“训练成功率”把最近 50 条终态窗口当成全量项目 KPI

**级别：中**  
**模块：Quality Center / Training history aggregation / bounded job index**

**现象：**

`v44_quality_center()` 计算项目级训练 KPI 时直接调用：

`jobs = list_jobs(project_id)`

然后：

`_training_success_rate_stats(jobs)`

生成：

- `train_success_rate`
- `train_success_count`
- `train_failure_count`
- `train_completed_count`

当前质量中心 UI 明确展示：

“训练成功率”
+
“X 成功 / Y 已结束”。

但 `list_jobs()` 不是全量历史 truth。

`sync_jobs_index()`
→ `_training_job_index_rows(..., history_limit=50)`
→ 保留全部 active
+
最近 50 条 terminal history。

**真实调用链：**

项目累计 100+ 条已结束 Training
→ `sync_jobs_index()`
→ index 只保留最近 50 条 terminal
→ `v44_quality_center()`
→ `list_jobs()`
→ `_training_success_rate_stats()`
→ 只对这 50 条计算成功率
→ UI 却显示成项目“训练成功率 / 成功数 / 已结束数”。

例如：

历史 100 条中 70 成功、30 失败；
最近 50 条恰好 45 成功、5 失败；

真实累计成功率 70%，质量中心会显示 90%，同时显示“45 成功 / 50 已结束”。

**为什么是 Bug / 套娃：**

bounded jobs index 的设计本身是正确的，它服务于：

- 当前 active 状态；
- 最近任务；
- 实时页面。

错误在于 Quality Center 把这个 bounded projection 当成项目级全量统计 truth。

与 AUDIT-013 同根，但这里影响的是全项目质量 KPI，而不是单算法训练次数。

**影响：**

- 累计训练成功率失真；
- 成功 / 失败 / 已结束数量失真；
- 项目训练稳定性趋势判断错误；
- 历史失败会随着新任务增加被窗口挤掉，KPI 会“自动变好”；
- 质量中心可能给管理者错误结论。

**为什么 CI 没发现：**

现有质量 / 训练报告测试主要覆盖小数量任务和单次报告，没有覆盖：

- 51+ terminal Training；
- 老失败任务被 history window 挤出；
- Quality Center KPI 必须保持全量累计真相。

**建议最小修复：**

不能把 `/jobs` 改成无限返回。

应和 AUDIT-013 一起提供项目级一次性 aggregate truth，例如 SQL / TaskRepository 聚合：

- terminal_training_count；
- success_count；
- failure_count；
- cancelled_count；

Quality Center 从 aggregate truth 计算 KPI，实时 jobs index 继续保持 bounded。

禁止 per-job N+1 读历史目录。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 100+ terminal Training 与 50-window 外失败任务。

---


### AUDIT-042 — Supplement Feedback 候选固定只暴露最新 500 条，501+ 时更老已确认反馈无法进入 Candidate Set

**级别：中～高**  
**模块：Online Feedback / Supplement Data / Candidate Set / Iteration**

**现象：**

补数据候选接口：

`GET /api/v63/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/supplement-data-candidates`

调用：

`list_confirmed_for_version(..., limit=500)`

repository 固定：

`ORDER BY confirmed_at DESC, id DESC LIMIT ?`

且 limit 最大强制为 500。

接口会返回：

- `total`
- `returned`
- `truncated = total > returned`

前端也会提示：

“候选超过 500 条，请先处理当前批次。”

但当前没有任何：

- cursor；
- page；
- offset；
- “加载更多 / 下一批”入口。

与此同时 Candidate Set 自身明确限制：

`1 <= candidates <= 500`

并且同一版本一旦冻结一个 `supplement_data_candidate_set`，再次冻结另一组会 409，不能覆盖。

**真实调用链：**

同一版本已有 700 条 confirmed feedback
→ list endpoint 只返回最新 500
→ 前端只能看到这固定 500 条
→ 更老 200 条不可见、不可勾选
→ 用户从当前 500 条中 freeze Candidate Set
→ version 写入唯一 `supplement_data_candidate_set`
→ 再次 freeze 第二组被拒绝。

即使用户暂时不 freeze、重新打开页面，repository 仍按同样排序返回同一最新 500 条，因此不存在“下一批 200 条”的实际路径。

**为什么是 Bug / 套娃：**

“Candidate Set 最多 500 条”可以是合法业务上限；

Bug 在于候选浏览 owner 把“最新 500 条”当成唯一可选择全集，导致用户无法从 501+ 条已确认反馈中选择任意 500 条。

这是 bounded query 被错误当成完整 selection truth。

**影响：**

- 第 501+ 条 confirmed feedback 永远无法进入该版本 Candidate Set；
- 较老但更有价值 / 已完成正式标注的反馈无法选择；
- UI 的“请先处理当前批次”具有误导性，因为当前没有下一批；
- 后续 Training supplement provenance 只能建立在被截断的可见集合上；
- 1k / 10k 在线反馈规模下会系统性遗漏历史候选。

**为什么 CI 没发现：**

现有测试覆盖：

- 单条 confirmed feedback；
- stale annotation；
- pending feedback exclusion；
- Candidate Set identity/provenance；

没有覆盖：

- 501+ confirmed feedback；
- 第 501 条是否可分页访问；
- 从非最新 500 中选择候选；
- truncated 后的继续处理流程。

**建议最小修复：**

不提高 Candidate Set 500 条上限，也不做无界 hydration。

最小方向：

- `list_confirmed_for_version` 提供稳定 cursor 分页；
- API 暴露 cursor / next_cursor；
- 前端支持受控翻页 / 加载更多，并允许跨页维护选择；
- freeze 仍最多 500 条，后端继续按 feedback_id + candidate_digest 做最终 CAS 核验；
- 禁止 per-feedback N+1，素材 / Annotation 继续批量读取。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 501+、跨页选择与固定 500 freeze 上限。

---


### AUDIT-043 — Quality Center 用 `versions[0]` 代替 `current_version_id`，非相邻 rollback 后会展示错误版本指标

**级别：中～高**  
**模块：Quality Center / Algorithm current-version projection / rollback read consistency**

**现象：**

`v44_quality_center()` 对每个算法直接：

`vers = a.get("versions") or []`
→ `v = vers[0] if vers else {}`

然后从该版本 report 计算：

- Precision；
- Recall；
- mAP50；
- algorithm score。

但 canonical Algorithm owner 已有明确：

`current_version_id`

并且 rollback 会修改这个指针。

**真实调用链：**

AlgorithmSqlStore 新版本归档时：

`sort_index = MIN(sort_index) - 1`

`read_all()` 又按：

`versions.sort_index ASC`

返回，所以新版本通常排在 `versions[0]`。

例如：

- v1：sort_index=0
- v2：sort_index=-1
- v3：sort_index=-2，current=v3

执行产品允许的非相邻 rollback：

v3 → v1

rollback owner：

- 删除当前 v3；
- `current_version_id = v1`；
- v2 作为历史版本继续保留。

此时 SQL read 顺序变为：

`versions = [v2, v1]`

但 current pointer 是：

`current_version_id = v1`

Quality Center 仍取 `versions[0] = v2`，因此展示 v2 的 Precision / Recall / mAP50，而不是当前已回退到的 v1。

**为什么是 Bug / 套娃：**

版本数组顺序只是展示/存储顺序，不是 current-version owner。

系统已经建立 canonical `current_version_id`，Quality Center 却重新用数组第一项推导“当前版本”，形成第二套 current-version truth。

这不是 Version Retirement / rollback owner 本身错误，而是读取端绕过该 owner。

**影响：**

- rollback 后质量中心算法指标可与算法详情当前版本不一致；
- 算法平均质量会被错误版本污染；
- 管理者可能认为回退已生效，但质量 KPI 仍显示中间历史版本；
- 多算法平均 Precision / Recall / mAP50 进一步失真；
- 指标缓存刷新也无法修复，因为错误来自版本选择逻辑。

**为什么 CI 没发现：**

rollback 测试覆盖 current pointer / 删除 / cleanup 合同；

Quality Center 测试没有覆盖：

- v1 → v2 → v3；
- 从 v3 非相邻回退到 v1；
- v2 保留但不再 current；
- Quality Center 必须按 `current_version_id` 取 report。

**建议最小修复：**

不要重排或重写版本 owner。

Quality Center 直接复用 canonical pointer：

- 读取 `current_version_id`；
- 从 `versions` 中按 id 精确找 current；
- pointer 无效时 fail-closed / 明确显示 current-version error；
- 不再用 `versions[0]` 推断当前版本。

同时横向检查其它当前可达页面是否仍把 `versions[0]` 当 current。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖非相邻 rollback 后 Quality Center 指标。

---


### AUDIT-044 — Storage Source PATCH 可在活动 MATERIAL_IMPORT / rescan 生命周期中停用或改坏运行依赖

**级别：高**  
**模块：Storage Source / MATERIAL_IMPORT / Rescan / Credential lifecycle**

**现象：**

AUDIT-016 已确认 DELETE 会忽略活动 Durable import/rescan 引用。

继续复核发现，即使不删除 Source，当前可达：

`PATCH /api/v61/storage-sources/{source_id}`

同样没有活动任务 reference fence，并允许直接修改：

- `enabled`
- `config`
- `credentials`
- `clear_credentials`

当前前端“存储配置”页真实提供：

- 编辑存储源；
- “停用 / 启用”；
- 修改 endpoint / bucket / prefix / root；
- 修改凭据。

**真实调用链：**

创建 Storage Import / rescan
→ request artifact 只冻结 `storage_source_id`
→ task 已 QUEUED / 等待 Worker claim
→ 用户点击“停用”，或 PATCH 清除 / 修改 credential / config
→ Source row 仍存在，但 live runtime 已改变
→ Worker `StorageImportHandler._source_and_provider()`
→ 重新读取 `StorageSourceRepository.get(source_id)`
→ 若 disabled：直接 `EnvironmentError("storage source is disabled")`
→ 若 config / credential 已变化：provider / health_check 按新配置执行，可能失败或指向不同后端。

Agent import 在确认后的 publish/indexing 路径中也会再次调用 `_source_and_provider()`，因此 scan 完成并不意味着后续阶段已经完全脱离 live Source。

**为什么是 Bug / 套娃：**

Durable MATERIAL_IMPORT 已经受理后，其运行依赖仍由可随时编辑的 live Storage Source owner 单方面控制。

Source 更新语义没有区分：

- “禁止新任务”；
- “破坏已经受理任务”。

这与 Service Node 停用应只阻止后续调度、保留已有 execution 的原则同类。

**影响：**

明确成立的窗口包括：

1. task 已创建但尚未 claim：停用 Source 后任务必然无法开始；
2. task retry / lease recovery：恢复时重新读取 live Source，旧任务可能无法恢复；
3. Agent review 完成后进入中央 publish/indexing：Source 被停用 / 清凭据后可失败；
4. config 被改到另一 bucket/root 时，冻结的 object_key 可能被解释到不同后端。

已经实例化 provider、正在进行的单次 I/O 是否会立即受 PATCH 影响取决于 provider 实现；本问题不依赖该窗口成立。

**为什么 CI 没发现：**

现有测试分别覆盖：

- StorageSourceRepository 可以 `enabled=False`；
- 存储源普通 edit；
- import/rescan 正常流程。

没有组合测试：

`active MATERIAL_IMPORT + source PATCH`

也没有要求 destructive PATCH 字段尊重 Durable task reference。

**建议最小修复：**

不要新增第二 Storage Import owner。

在 Storage Source PATCH owner 中区分安全字段与运行依赖字段：

- name 等纯展示字段可继续修改；
- `enabled true→false`、config、secret_ref / credential clear 或替换，在存在活动 / 待确认且仍可能恢复执行的 MATERIAL_IMPORT / rescan 引用时 fail-closed 409；
- 查询复用 canonical TaskRepository，并保持分页有界；
- terminal 后再允许破坏性修改；
- 如果未来需要在线 credential rotation，应设计原子验证/切换合同，而不是让当前任务无保护读取任意新凭据。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 queued / awaiting-confirmation→resume / retry 三个窗口。

---


### AUDIT-045 — Algorithm 综合报告无界扫描全部 job.json，Legacy 任务还会按当前 Annotation GT 反复重算历史标签统计

**级别：中～高**  
**模块：Algorithm Report / Training History / Annotation hydration / Performance**

**现象：**

当前算法卡“综合报告”按钮真实调用：

`GET /api/v49/projects/{project_id}/algorithms/{algorithm_id}/report`

该 endpoint 每次请求都会：

1. 遍历项目整个 `jobs/*/job.json`；
2. 对每个目录读取 JSON；
3. 再按 algorithm_id 过滤；
4. 对该算法每条历史 job 调 `_v49_job_label_counts()`。

现代 Training 若有有效 `snapshot_id` 且 Snapshot 带 `label_counts`，会直接读取冻结统计。

但 Legacy / 无 Snapshot 任务会回退到：

- 读取历史 job 中的 train image ids；
- 每 500 张调用 `read_annotations_many()`；
- 从**当前 AnnotationRepository**重新统计 boxes / labels。

**真实调用链：**

429 算法列表
→ “综合报告”
→ `algorithmReport429()`
→ v49 report
→ `jobs_dir.glob("*/job.json")`
→ 全项目 job 文件逐个读取
→ 命中算法的历史 job
→ `_v49_job_label_counts()`
→ 若无 snapshot label_counts
→ 当前 AnnotationRepository 批量读取并重新统计。

**为什么是 Bug / 技术债：**

这里同时有两个相互放大的问题：

1. **无界历史 hydration**
   - report 只属于一个 algorithm，却先扫描整个项目所有 job 目录；
   - 项目 10k / 20k 历史任务时，请求成本与全项目任务数线性增长。

2. **Legacy 历史统计不是冻结真相**
   - 旧 Training 的标签分布按今天的 AnnotationRepository 重算；
   - 用户后续统一标签、修改框、确认空样本后，过去“训练素材标签维度”会被重写；
   - 这不是当时训练真正看到的历史输入。

对于大量 legacy job，第二条还会把成本放大成：

`历史任务数 × 每任务素材批次数`

虽然每次 annotation 读取本身按 500 bounded，但 report 整体仍是无界 hydration。

**影响：**

- 1k / 10k / 20k 历史任务下综合报告首开显著变慢；
- 大量旧任务时可能造成高磁盘 I/O / SQLite 读取；
- 历史 label_counts 会随当前 GT 漂移；
- “累计参与训练的检测框数量”无法作为稳定审计数据；
- 页面把重算结果显示成“算法长期训练总结”，语义失真。

**为什么 CI 没发现：**

现有浏览器训练/质量报告测试主要验证页面流程和小数据集，没有：

- 1k / 10k / 20k jobs 规模测试；
- 一个算法只占项目少量 job 时的全项目扫描成本；
- legacy job 缺 snapshot 时历史 Annotation 变化后的报告不变性测试。

**建议最小修复：**

不新增第二 Training history owner。

- 为 Training history 提供按 `project_id + algorithm_id` 的可索引查询 / aggregate；
- summary / trend / duration / success / label counts 使用一次项目级或算法级 aggregate truth；
- 现代任务继续读取 frozen snapshot/report；
- legacy 任务若确实没有冻结 label truth，应明确标记“历史统计不可恢复 / legacy-derived”，不要静默拿当前 GT 冒充历史输入；
- 前端只需要最近明细时继续 bounded，例如最后 20 条，完整 aggregate 在后端一次计算；
- 禁止通过扫描所有 job 目录来服务单算法报告。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 10k job 索引成本，以及 legacy annotation 后改不应伪造历史训练 truth。

---


### AUDIT-046 — Training “自动转换”只选择厂商，目标芯片 / SoC 没有进入冻结合同

**级别：高**  
**模块：Training Settings / Auto Conversion / Deployment Target Identity**

**现象：**

当前 canonical Training Settings 的“达标后自动转换”只允许勾选：

- `ascend`
- `rockchip`
- `sophon`

前端最终只提交：

`auto_convert_targets: ["ascend"|"rockchip"|"sophon"]`

没有提交、冻结或让用户确认：

- Rockchip chip；
- Ascend soc_version；
- Sophon processor/chip；
- 对应 conversion resource identity。

但真正的转换 runtime 明确依赖这些目标硬件身份。

**真实调用链：**

Training Settings
→ `.ts428AutoConvert`
→ `auto_convert_targets`
→ Training 成功归档版本
→ `_v48_auto_convert_version()`

然后三种厂商采用三套不同策略：

1. **Rockchip**
   - 从第一个 ready resource 读取 supported_chips；
   - 只有恰好 1 个 chip 才允许自动转换；
   - 同时支持 RK3568 + RK3576 时直接记录 error 并跳过转换。
   - 现有回归测试还明确固定了“多芯片必须 fail-closed”。

2. **Ascend**
   - 读取 `detected_soc_versions / remote_health.soc_versions`；
   - 不让用户确认，直接使用 `socs[0]`；
   - 但 canonical `validate_target()` 明确要求 soc_version 必须与部署硬件一致。

3. **Sophon**
   - 直接硬编码：
     `params["chip"] = "bm1684x"`
   - Deployment Worker 也会把缺省 chip 当作 bm1684x。

**为什么是 Bug / 套娃：**

Training 侧把“厂商”误当成完整 conversion target identity。

真正转换 owner 对硬件 identity 的要求却比 Training request 更严格：

- Rockchip 选择不充分时 fail-closed；
- Ascend 选择不充分时 silent-first；
- Sophon 选择不充分时 hardcode-default。

同一个“自动转换”产品动作因此既不确定，也不一致。

**影响：**

- 常见同时支持 RK3568 / RK3576 的资源上，用户明明勾选“瑞芯微自动转换”，训练完成后却不会创建 RKNN job；
- Ascend 多 SoC 资源可能自动选择并非用户部署目标的第一个 soc_version；
- Sophon 非 BM1684X 目标无法通过 Training 设置表达，可能失败或生成错误目标产物；
- 自动转换 summary 只在训练完成后暴露 errors，用户创建训练时无法知道配置本身不可兑现；
- 产物 chipCode / computePlatform 身份可能与用户真实部署目标不一致；
- 若选中的 ready resource 是 legacy remote resource，还会继续进入 AUDIT-024 的第二 Conversion Runtime owner。

**为什么 CI 没发现：**

现有测试分别覆盖：

- Rockchip 单芯片成功；
- Rockchip 多芯片 fail-closed；

但没有前后端合同测试要求 Training UI 在开启 auto conversion 时必须冻结完整 target identity，也没有覆盖 Ascend 多 SoC / Sophon 非 BM1684X 的用户意图。

**建议最小修复：**

不要在 `_v48_auto_convert_version()` 里继续猜。

最小方向：

- Training Settings 开启某个自动转换目标时，选择并冻结 canonical `resource_id + target hardware identity`；
- Rockchip 明确选择 RK3568 或 RK3576；
- Ascend 明确选择 soc_version；
- Sophon 明确选择 processor/chip；
- 提交前按当前 Deploy Resource capability 做 fail-closed；
- Training request 只持有 immutable auto-conversion plan；
- 真正转换仍只调用 canonical Conversion owner，不新增第二 conversion runtime。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 Rockchip 双芯片、Ascend 多 SoC、Sophon 非 BM1684X，以及资源变化后的 fail-closed。

---


### AUDIT-047 — Model Config PUT 会原地覆盖 frozen secret_ref 的 Keyring 值，Queued AI task 凭据并未真正冻结

**级别：高**  
**模块：AI Annotation / Model Config / Secret Lifecycle / Durable Request Freeze**

**现象：**

Durable AI Annotation 在 submit 时已经正确冻结：

- `model_config_snapshot`
- `model_config_revision`
- `secret_ref`

并且 request.json 不保存真实 API key。

但：

`PUT /api/v35/model-configs/{config_id}`

如果用户填写新的 API Key，会复用旧配置的同一个：

`secret_ref("model-config", config_id)`

然后直接：

`_v35_secret_store().set(reference, api_key)`

也就是说 secret reference 不变，但 reference 指向的 secret value 被原地覆盖。

Worker 真正执行 frozen request 时：

`annotation_runtime.prepare_request(..., runtime=True)`

会从 frozen snapshot 取出 `secret_ref`，然后再次：

`KeyringSecretStore().get(reference)`

读取**执行时当前值**，而不是任务提交时的凭据版本。

**真实调用链：**

AI task submit
→ request.json 冻结 `secret_ref = xjalgo:model-config:model-1`
→ task QUEUED
→ 用户编辑同一个 Model Config 并更新 API Key
→ PUT v35
→ Keyring 同一个 reference 被覆盖
→ Worker 后续 claim task
→ frozen model_config_snapshot 仍是旧 URL/模型配置
→ Keyring lookup 得到新 API Key
→ 旧配置 + 新凭据组合执行。

**为什么是 Bug / 套娃：**

当前 freeze contract 只冻结了“secret pointer”，没有冻结“credential revision”。

对 Durable Task 来说，secret_ref 被当成 immutable input，但它指向的值实际上是 mutable global state。

因此“任务提交成功后执行输入被冻结”的合同并未成立。

**影响：**

- queued AI task 可能使用提交后才设置的新 API Key；
- 旧 endpoint / model snapshot 与新账号凭据组合，可能直接鉴权失败；
- 如果新旧 key 属于不同租户/账户，任务可能访问错误的配额或数据域；
- retry 结果依赖当前 Keyring，而不是原任务输入；
- 审计时无法从 task revision 证明实际使用的是哪一版 credential；
- AUDIT-018 的 delete 问题只是同一 secret lifecycle 缺口的另一种表现。

**为什么 CI 没发现：**

现有：

`test_runtime_uses_frozen_model_snapshot_even_after_live_config_changes`

只修改 live Model Config 的 URL / model_name。

测试中的 `FakeSecrets.get()` 始终固定返回同一个字符串，并没有模拟真实 PUT 对同一 secret_ref 做覆盖。

因此它证明了配置正文 snapshot 正确，却没有证明 credential value snapshot / revision 正确。

**建议最小修复：**

不要把真实 secret 写进 request.json。

最小方案：

- Secret Store 支持 immutable credential revision / versioned secret reference；
- submit 时冻结 `secret_ref + secret_revision`；
- Worker 必须按该 revision 读取；
- Model Config 更新 API Key 时创建新 revision，而不是覆盖旧 task 已引用的 value；
- active Durable task 引用的旧 revision 在 terminal 前不可 GC；
- delete / rotation / update 统一走同一个 secret reference owner。

如果当前 Keyring abstraction 暂时不支持 revision，至少应在有 active task 引用当前 secret_ref 时阻止 API Key 修改，不能静默替换。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 submit → rotate API key → queued task 仍使用提交时凭据 revision。

---


### AUDIT-048 — Quality Center / Training Data Quality 每次全量重读图片字节算 SHA1，20k 素材会产生巨量重复 I/O

**级别：中～高**  
**模块：Quality Center / Training Data Quality / MaterialRepository / Performance**

**现象：**

当前：

- `GET /api/v44/projects/{project_id}/quality-center`
- `POST /api/v44/projects/{project_id}/data-quality`

最终都走：

`_v44_dataset_quality()`

该函数已经通过 MaterialRepository 读取 material rows，row 中已经持有：

- `content_sha256`
- `size_bytes`

但随后仍对每一张 candidate 执行：

`resolve_material_path()`
→ `path.read_bytes()`
→ `hashlib.sha1(...).hexdigest()`

并再次通过文件 stat 统计容量。

**真实调用链：**

打开“质量中心”
→ GET v44 quality-center
→ `_v44_dataset_quality(project_id)`
→ load all materials
→ batch load AnnotationRepository
→ normalize boxes
→ 对全部素材逐张打开源文件、一次性 `read_bytes()`
→ SHA1
→ `compute_quality(candidates)`

训练创建窗口点击“查看数据质量”也会对本次显式选择的全部 image_ids 执行同一条路径。

**为什么是 Bug / 技术债：**

`compute_quality()` 对重复图判断只要求稳定的 `content_hash`，并不要求重新读取文件。

MaterialRepository 已经把内容摘要作为 canonical metadata：

`content_sha256 TEXT`

且有对应索引。

因此当前做法把已存在的 O(N) metadata 查询退化为：

O(全部图片字节数) 的磁盘 / 对象落地 I/O + hash CPU。

**规模影响：**

例如：

- 1k 张 × 1 MB ≈ 每次额外读 1 GB；
- 10k 张 × 1 MB ≈ 每次额外读 10 GB；
- 20k 张 × 1 MB ≈ 每次额外读 20 GB。

实际图片更大时线性增加。

而 Quality Center 是页面读取 API，不应在每次首次进入页面时重新校验所有源文件字节。

**影响：**

- 10k / 20k 素材项目打开质量中心明显变慢；
- Web worker / API 请求长时间占用磁盘和 CPU；
- 同时训练 / 清洗 / 导入时会争抢 I/O；
- 对对象存储或非本地 material，`resolve_material_path` 还可能产生额外准备成本；
- Python `read_bytes()` 会为整张图片分配内存，单张大图时增加瞬时内存压力；
- 用户每次重新打开质量页都会重复做同样工作。

**为什么 CI 没发现：**

现有质量计算测试主要验证指标值，没有 1k / 10k / 20k 的 I/O contract，也没有断言“已存在 content_sha256 时不得重新打开源图片”。

**建议最小修复：**

不改变 `compute_quality()` owner。

在 `_v44_dataset_quality()`：

- 优先使用 material row 的 `content_sha256` 作为 `content_hash`；
- 优先使用 `size_bytes` 统计容量；
- 仅对 legacy / 缺失 digest 的 row 做 bounded fallback hash，并回填 canonical metadata；
- 不要为质量页面再造第二套 hash cache；
- 后续若 Quality Center 仍需全项目统计，再考虑做 SQLite aggregate / revision cache，但不能用无界 DOM 或 N+1。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖已有 digest 不读源文件，以及 1k / 10k / 20k metadata-only 路径。

---


### AUDIT-049 — 被 Cleaning preempt 的任务无法记录“用户明确取消”，高优先级任务结束后会被自动复活

**级别：高**  
**模块：Cleaning / Preemption / Task cancellation / CentralTaskAllocator**

**现象：**

当前 CLEAN 抢占流程把被抢占任务 victim 改为：

`RUNNING -> CANCEL_REQUESTED(stage=preempting)`

并在 `task_preemptions` 中记录：

`WAITING_CANCEL`

设计意图是 victim 保存 checkpoint、结束当前 execution，等 incoming 高优先级清洗任务结束后自动恢复。

问题在于：如果用户在这个等待窗口里明确点击“停止” victim，当前 TaskRepository 没有记录“operator cancelled, do not resume”的独立意图。

**真实调用链：**

Clean A RUNNING
→ Clean B 以 `queue_policy=preempt` 提交
→ `CentralTaskAllocator.preempt_for(B)`
→ A = CANCEL_REQUESTED / preempting
→ task_preemptions(B,A) = WAITING_CANCEL

此时用户对 A 执行停止：
→ `TaskRepository.request_cancel(A)`

但 `request_cancel()` 只处理：

- QUEUED / AWAITING_CONFIRMATION -> CANCELLED
- RUNNING -> CANCEL_REQUESTED

A 已经是 CANCEL_REQUESTED 时不会写任何额外字段，只是原样返回。

Agent/Worker 随后确认取消：
→ A = CANCELLED

B 最终进入 SUCCEEDED / FAILED / CANCELLED 等 terminal
→ 下一次 allocator `assign_next()`
→ `_resume_ready_preemptions_in()`
→ 只看到：
   - preemption state = WAITING_CANCEL
   - victim status = CANCELLED
   - incoming terminal
→ 无条件把 A：
`CANCELLED -> QUEUED`
并设置：
`retry_of = task_id`

用户刚刚明确停止的 A 被自动重新启动。

**为什么是 Bug / 套娃：**

这里混淆了两种不同 cancellation owner intent：

1. scheduler preemption 的临时 cancel-for-resume；
2. 用户明确的永久 cancel。

二者最终都压缩成同一个 `CANCELLED` 状态，而 preemption recovery 没有可辨认的 owner intent。

**影响：**

- 用户明确停止的清洗任务可能重新进入队列；
- 可能再次占用 Agent / CPU / I/O；
- 大规模清洗可能在用户以为已停止后继续扫描；
- 自动恢复行为违反 UI“停止任务”的明确语义；
- 若用户反复停止，可能形成“停止后又回来”的难以解释状态。

**为什么 CI 没发现：**

现有：

`test_clean_preemption_cancels_recoverable_victim_then_requeues_it_after_preemptor_finishes`

只验证正常自动恢复路径：

preempt -> victim CANCELLED -> incoming finished -> victim QUEUED。

没有覆盖：

preempt -> 用户 stop victim -> incoming finished

也没有断言 operator cancel 必须压制 auto-resume。

**建议最小修复：**

不要新增第二 cancellation runtime。

在 canonical TaskRepository / preemption lineage 中保留明确 cancellation intent，例如：

- preemption cancel reason / generation；
- operator cancellation generation / terminal override；

当用户对 WAITING_CANCEL victim 明确 stop 时，应把对应 `task_preemptions` 标记 ABANDONED / DO_NOT_RESUME，或写 canonical terminal intent。

`_resume_ready_preemptions_in()` 只有在“最终 CANCELLED 确实属于该次 preemption cancel”时才允许 requeue。

同时增加竞态测试：

- preempt 后立即用户 stop；
- victim 已 CANCELLED 后、incoming 未结束前用户 stop；
- incoming cancelled/failed 后也不能复活 operator-cancelled victim。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-050 — Cleaning 详情绕过 canonical 分页结果接口，一次性 hydrate 全部清洗结果

**级别：中～高**  
**模块：Cleaning Review / MaterialBatch Results / Frontend Hydration / Performance**

**现象：**

canonical MaterialBatch 已经提供：

`GET /api/v62/projects/{project_id}/material-batches/{task_id}/results?cursor=&limit=`

并且：

- 只允许 CLEAN；
- `limit` 1~500；
- 按 `image_id` cursor 分页；
- 返回 `items + next_cursor`。

但当前最终 Cleaning 详情页没有复用这个 owner，而是调用：

`GET /api/v47/projects/{project_id}/clean-tasks/{task_id}/result`

该兼容 endpoint 内部通过：

`_v47_durable_clean_results()`

直接：

`SELECT ... FROM clean_results ... ORDER BY image_id`
→ `fetchall()`
→ JSON decode 全部 result_json
→ 对全部 image_id 一次 `MaterialRepository.get_many(...)`
→ enrich 全部 material / annotation metadata
→ 把整批 items 一次返回浏览器。

**真实调用链：**

用户打开一个大 CLEAN 任务详情
→ `cleanDetailCore429(id)`
→ GET v47 clean result
→ 后端一次读完整 clean_results
→ 一次 hydrate 全部 material rows
→ 浏览器一次解析完整 JSON
→ 过滤 failed / issues
→ 把全部 reviewItems 放入 `state.cleanImageReview429.items`
→ 最终 DOM 只显示前 60 张。

前端虽然有：

`CLEAN_IMAGE_REVIEW_BATCH_429 = 60`

并按“加载更多”每次显示 60 张，但这只是 DOM 分页，不是数据分页；首屏之前全部数据已经完成服务端读取、网络传输和客户端内存 hydration。

**为什么是 Bug / 套娃：**

当前 compatibility Cleaning read owner 绕过了已经存在的 canonical MaterialBatch cursor API。

这是典型的：

“UI 看起来分页”
≠
“后端 / 网络 / state 真正分页”。

而且 Annotation Audit 同一个详情页已经正确使用独立 cursor endpoint，说明当前产品本身已有分页模式。

**规模影响：**

CLEAN MaterialBatch 支持 FILTERED 大范围；explicit large selection 也支持到 100000 的特定操作边界，项目实际目标规模明确包含 1k / 10k / 20k。

20k 清洗结果时，打开详情会一次性发生：

- 20k SQLite result row fetch；
- 20k result_json decode；
- 20k material lookup / public projection；
- 大体积 JSON 序列化与网络传输；
- 浏览器保存全部 review items；
- 再对全部 items 做 filter / stats / issue option 聚合。

即使最终只显示 60 张，首屏成本仍与完整 task 大小线性增长。

**影响：**

- 10k / 20k 清洗任务详情首开明显变慢；
- Web API 线程/进程出现瞬时 CPU / 内存峰值；
- 大 JSON 响应增加网络和浏览器解析压力；
- 移动端/低内存浏览器更容易卡顿；
- 用户只是查看前 60 张，也要为全部结果付出成本；
- 和“禁止无界 hydration”的当前性能合同冲突。

**为什么 CI 没发现：**

现有 Cleaning 测试覆盖：

- durable create / run / confirm；
- 单条/小批 result；
- PollRegistry；
- upload-cleaning 性能；

但没有验证：

- v47 result endpoint 必须 bounded；
- 1k / 10k / 20k CLEAN 详情首次读取只拉一页；
- compatibility UI 必须复用 canonical v62 cursor results。

**建议最小修复：**

不要再造第二套 clean result store。

最小方向：

- Cleaning 详情直接复用 canonical `/material-batches/{task_id}/results`；
- 首屏 `limit=60~100`；
- summary / issue counts 如果需要全量，应在 Worker 完成时写 aggregate summary，或用 SQLite aggregate query，不应靠前端 hydrate 全量后统计；
- material enrichment 仅对当前页 image_ids 批量 `get_many`；
- “加载更多”使用 `next_cursor`；
- 删除确认集合继续绑定同一个 selection.sqlite3 / canonical clean result truth，不新增第二结果 owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 1k / 10k / 20k，断言 first-page DB row / material hydration 有界，并验证 next_cursor。

---


### AUDIT-051 — ZIP 导入完成复核页重新全量 hydrate 10k/20k 素材与标注，绕过 v19 已有 bounded preview

**级别：中～高**  
**模块：ZIP Import Review / MaterialRepository / AnnotationRepository / Frontend Hydration**

**现象：**

v19 ZIP 扫描阶段已经针对大包做了明确的规模收口：

- 10k / 20k ZIP 可识别；
- scan images 存外部 manifest；
- job detail 默认不携带全部 images；
- preview 有明确 `image_limit`；
- list 只返回 bounded preview。

但导入完成后的：

`GET /api/v52/projects/{project_id}/import/jobs/{job_id}/review`

又把完整导入范围一次性 hydrate 回来。

**真实调用链：**

导入报告中：
`report.imported_image_ids = [全部导入 image_id]`

用户打开“本次导入素材”
→ `showImportReview412(jobId)`
→ GET v52 review
→ 后端：
  - 读取全部 imported_image_ids；
  - `MaterialRepository.get_many(all ids)`；
  - 每 500 条 `read_annotations_many()`，直到全部标注读完；
  - 再遍历全部 boxes 重算 label_box_counts；
  - 返回完整 `image_ids + images + report + label_box_counts`
→ 前端把完整数组保存进：
  - `state.import412.image_ids`
  - `state.import412.images`
  - `state.import412Selected`
→ 最后 UI 只做：
`rows.slice(0, 180)`

所以 180 只是 DOM 截断，不是后端 / 网络 / state 分页。

**为什么是 Bug / 套娃：**

v19 主导入 owner 已经明确为 10k/20k 做了 bounded scan/read contract；v52 compatibility review 又重新创建了一条“全量 material + annotation hydration”旁路。

而且 import worker 的 report 已经维护：

`label_box_counts`

v52 review 仍通过读取全部 AnnotationRepository boxes 再计算一次，产生重复全量 I/O。

**规模影响：**

20k 导入完成后，用户只是打开复核弹窗就会：

- 一次 material get_many 20k；
- AnnotationRepository 按 500 批读取共 20k；
- Python 构造全部 images/annotation dictionaries；
- 全量 JSON 序列化与网络传输；
- 浏览器保存 20k image rows 和 20k selected IDs；
- 最终却只展示前 180 张。

这与仓库已有的 10k/20k bounded preview 测试目标直接冲突。

**影响：**

- 大 ZIP 导入完成后复核弹窗首开慢、内存峰值高；
- Web API 和浏览器都承担与整个导入包大小线性增长的成本；
- 移动端更容易卡顿；
- label_box_counts 重算造成额外 Annotation I/O；
- 10k/20k 导入前半段已经完成的性能优化在最终复核阶段失效。

**为什么 CI 没发现：**

现有：

- `test_v19_import_scalability.py` 明确覆盖 10k / 20k scan bounded preview；
- `zip-import-10k.test.mjs` 验证 picker 只显示 bounded preview；
- `test_v52_import_review_owner.py` 只验证 review 从 MaterialRepository 读取真实素材，不覆盖大规模分页。

没有测试要求 v52 review 在 10k/20k 时也必须 bounded。

**建议最小修复：**

不要新增第二 import review store。

最小方向：

- v52 review 增加 cursor / limit，按 imported_image_ids 的稳定顺序分页；
- 首屏 100~200 条即可；
- `image_ids` 全量选择语义不要通过把 20k IDs 全塞进浏览器来实现，可由 server-side selection scope / import batch identity 表达；
- label_box_counts 优先使用 import report 已冻结统计，不要再次扫描全部正式标注；
- 当前页只对当前 image_ids 批量读取 material / annotation；
- “全选 / 反选 / 批量清洗”需使用 batch scope + exclusions，而不是全量客户端 Set。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 10k / 20k review first-page bounded、next cursor、全选语义和无全量 annotation rescan。

---


### AUDIT-052 — ZIP 导入完成时 Label Schema 被两个 completion/review owner 重复刷新，当前浏览器 CI 已真实红灯

**级别：中～高**  
**模块：ZIP Import Completion / Import Review / Label Refresh / Frontend Runtime**

**现象：**

当前 Durable ZIP 导入完成后，同一个成功事件会对：

`GET /api/v12/projects/{project_id}/labels`

发起两次完全相同的请求。

当前 HEAD 的 `Frontend Runtime Stabilization / browser-navigation` 已真实失败：

`tests/browser/material-pagination-performance.spec.mjs`

用例：

`v19 background import completion uses scoped labels and material refresh without broad reload`

预期 labels GET 1 次，实际 2 次。

这不是 flaky，也不是测试时序误报；生产调用链中确实存在两个独立 refresh owner。

**真实调用链：**

Durable ZIP runtime：

`reconcile(...)`
→ `applyCompletion(job, reason)`
→ `window.completeZipImportReview412?.(id)`
→ `await window.refreshLabels414?.(false)`
→ 若当前页为“数据集”，`reloadMaterialPage61()`

同时：

`completeZipImportReview412(id)`
→ 绑定 review button
→ 280ms 后自动：
`window.showImportReview412(jobId)`
→ `await refreshLabels414(false)`
→ 再请求同一个：
`GET /api/v12/projects/{project_id}/labels`

因此一次成功 completion 会产生：

1. completion owner 的 labels refresh；
2. auto review owner 的 labels refresh。

两者没有共享 in-flight / freshness / completion generation。

**为什么是 Bug / 套娃：**

这里不是两个 Poller 常驻，而是同一个业务完成事件上叠了两个“标签刷新副作用 owner”。

`applyCompletion()` 已明确承担：

- review completion binding；
- quality invalidation；
- label refresh；
- material refresh；
- completion toast。

但它调用的 review owner 又在自动打开时无条件刷新 labels，形成 completion callback 套娃。

这与当前“一个 domain 一个明确 refresh owner、禁止重复 completion side effect”的前端运行时收口目标冲突。

**影响：**

- 每次 ZIP 导入成功至少多一次 labels API 往返；
- 标签较多时重复 JSON 解析、状态覆盖和 localStorage persist；
- completion 与 review 的并发时序更复杂，后续容易再叠加重复 material / review hydration；
- 当前 HEAD 的 `Frontend Runtime Stabilization` 已因此失败，不能报告 CI 全绿或可部署；
- 在 10k/20k 导入场景中，本问题会和 AUDIT-051 的 review 全量 hydration 叠加，进一步放大完成后首开成本。

**为什么现有测试之前没拦住：**

现有 `tests/frontend/import-refresh-owner.test.mjs` 主要做静态 owner 结构断言：

- `applyCompletion()` 必须刷新 labels/material；
- 禁止 broad `loadRelated/loadAll`。

但没有断言：

“同一次 completion + auto review 生命周期中，labels endpoint 只能请求一次”。

当前 Playwright browser test 才首次在真实运行时把两个 owner 同时执行出来并抓到重复 GET，所以现在 CI 已经明确暴露该问题。

**后续同 SHA rerun 证据修正：**

继续核对 `4b559a37e72d50f9ec2d84f8f05bdc018a395e9c` 的完整 Actions 历史后发现：

- 首次 `Frontend Runtime Stabilization` run：`browser-navigation` failure，真实抓到 labels GET 两次；
- 随后对**同一个 SHA** 的 workflow rerun：`browser-navigation` success；
- rerun 期间没有任何生产代码变化。

因此需要把“CI 红灯”拆成两个事实：

1. **生产 duplicate refresh 仍然是真实 Bug。** 源码调用链已经直接证明 completion owner 与 auto-review owner 都会执行 `refreshLabels414(false)`，所以 AUDIT-052 不撤销；
2. **当前 browser regression 本身具有时序窗口。** 首次运行能观察到第二次请求，rerun 可能在第二次 refresh 被计入断言前就结束，所以不能再表述为“该 case 每次稳定必红”。

修复时除了收敛唯一 refresh owner，还必须让浏览器回归测试确定性等待：

- completion side effects；
- 280ms auto review open；
- review hydration / labels refresh settle；

之后再断言同一次 completion 生命周期 labels GET 恰好一次。不能依赖当前偶发通过作为“问题已消失”的证据。

**建议最小修复：**

不要删除浏览器断言，也不要把期望从 1 次放宽成 2 次。

保留 Durable ZIP runtime 作为 completion side-effect canonical owner。

最小方向应是让 review 打开复用 completion 已刷新的 label truth，而不是无条件再次 GET，例如：

- `showImportReview412()` 只在 label cache 未加载/已过期时刷新；
- 或 completion 调用 review 时传入明确的“labels 已刷新”上下文；
- 如果用户稍后手动打开 review，则仍按 canonical freshness 规则决定是否刷新。

不要新建第二 label cache owner，也不要通过全局 broad reload 掩盖问题。

同时补回归测试覆盖：

- completion 自动打开 review：labels GET 恰好一次；
- 用户晚些时候手动打开 review：cache fresh 时不重复 GET；
- cache stale 时允许一次明确 refresh；
- completion 重复 reconcile 不重复执行 side effects。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-053 — Training Create 随机试验模式的数据划分百分比 UI 与 canonical Split runtime 语义不一致

**级别：中**  
**模块：Training Create / Dataset Split / Frontend Presentation / TrainingPrepare**

**现象：**

当前训练创建页在“从本次训练素材随机抽取试验集”模式下，把：

- `experiment_percent`
- `validation_percent`

都当成“占原始总素材池的绝对百分比”展示。

例如默认：

- 试验集 20%
- 验证集 20%

前端 `splitPresentation()` 计算：

`training = 100 - validation - experiment`

因此 UI 明确展示：

- 训练 60%
- 验证 20%
- 试验 20%

但 canonical 后端 `build_split_manifest()` 的真实合同不是这个语义。

**真实调用链：**

前端：

`splitState()`
→ `splitPresentation()`
→ `trainingSummaryHtml()` / `renderSplit()`

当前计算：

`experiment = s.experiment`

`validation = s.validation`

`training = 100 - validation - experiment`

提交：

`TrainingSubmitRuntime.submit()`
→ `buildTrainingStartPayload()`
→ `trainingDraftToRequest()`

提交同样的：

- `split_mode = random_test_from_training_pool`
- `experiment_percent`
- `validation_percent`

后端：

`_explicit_training_split()`
→ `SplitRequest`
→ TrainingPrepare
→ `build_split_manifest()`

canonical split 的顺序是：

1. 先从完整训练候选池按 `experiment_percent` 抽试验集；
2. 再从“扣除试验集后的剩余池”按 `validation_percent` 抽验证集；
3. 剩余才是训练集。

因此在 20% / 20% 时，理论比例约为：

- 试验：20%
- 验证：80% × 20% = 16%
- 训练：80% × 80% = 64%

这不是 UI 当前显示的 60% / 20% / 20%。

**现有后端回归证据：**

`tests/unit/test_training_splits.py`

`test_large_random_split_keeps_exact_component_counts_at_20k_scale`

对 20,000 张素材，明确断言：

- train = 12,800
- validation = 3,200
- test = 4,000

即：

- 训练 64%
- 验证 16%
- 试验 20%

所以后端语义是明确、稳定且已有测试保护的；当前漂移发生在前端 presentation。

**为什么是 Bug / 前后端不一致：**

训练页把“验证比例”展示成总池比例，但后端实际把它解释为：

“完成试验集留出以后，对剩余训练候选池再切验证集的比例”。

用户看到并确认的比例与最终 Snapshot 真实比例不同。

这个问题不会让数据泄漏，因为 canonical backend 仍正确做 split；但会让用户错误理解训练 / 验证 / 试验样本规模，尤其在调高试验比例时偏差会明显放大。

例如：

- experiment=50%
- validation=20%

UI 会显示：

- train 30%
- validation 20%
- test 50%

而后端真实目标约为：

- train 40%
- validation 10%
- test 50%

**影响：**

- Training Create 页面展示与最终冻结 Snapshot 不一致；
- 用户基于错误比例做训练数据规划；
- 数据量较小时可能错误判断训练集是否足够；
- 训练报告中的最终真实 counts 与创建页预期不符，容易被误认为后台“擅自改比例”；
- 1k / 10k / 20k 规模越大，绝对样本数量差异越明显。

**为什么 CI 没发现：**

后端 split tests 只保护 canonical split truth；

前端 Draft / Submit tests 主要确认：

- `experiment_percent` 原样提交；
- `validation_percent` 原样提交；
- split mode / material IDs 正确；

当前没有跨层测试断言：

“前端展示比例必须按后端 sequential split contract 计算”。

因此前后两边各自测试都能通过，但 presentation contract 仍漂移。

**建议最小修复：**

不要修改 canonical backend split 算法，也不要改变已有 20k 回归合同。

优先只修前端 presentation，使随机试验模式的展示遵循后端顺序：

- `test_ratio = experiment_percent`
- `remaining_ratio = 100 - test_ratio`
- `validation_ratio = remaining_ratio * validation_percent / 100`
- `training_ratio = remaining_ratio - validation_ratio`

同时把 UI 文案明确为：

“验证比例作用于扣除试验集后的剩余候选池”。

如果产品希望两个输入都代表“总池绝对比例”，那属于合同变更，需要迁移后端 SplitRequest 语义和所有历史/测试；本轮不建议这样做。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少增加前端 presentation 20/20 → 64/16/20，以及非默认比例的合同测试。

---


### AUDIT-054 — 固定 Benchmark 复用的前端 payload 与 TrainReq admission 合同互相冲突，真实浏览器路径会在创建阶段失败

**级别：高**  
**模块：Training Create / Benchmark Reuse / TrainingSubmitRuntime / SplitRequest / TRAINING_PREPARE**

**现象：**

当前训练创建页启用“复用当前固定评测基准”后，前端 `TrainingSubmitRuntime` 会：

- 保留 `split_mode = random_test_from_training_pool`；
- 删除 `test_image_ids`；
- 删除 `experiment_percent`；
- 写入 `benchmark_source_version_id`；
- 写入 `benchmark_scope_id`。

但 v12 Durable Training admission 在创建 TRAINING / TRAINING_PREPARE 任务之前，仍无条件调用：

`_explicit_training_split(payload)`

而随机试验模式的 canonical `SplitRequest` 明确要求：

`experiment_percent` 必须非空且 0 < value < 100。

因此真实浏览器 Benchmark reuse 请求会在 admission 阶段直接失败，后续 TrainingPrepare 的 Benchmark 解析/替换根本没有机会执行。

**真实调用链：**

前端：

`TrainingSubmitRuntime.submit()`
→ `benchmarkReuseContext(...)`
→ `buildTrainingStartPayload(...)`
→ 当 benchmarkContext 存在：
  - `delete payload.test_image_ids`
  - `delete payload.experiment_percent`
  - 写入 benchmark source/scope identity
→ `POST /api/v12/projects/{project_id}/train/start`

后端：

`v12_start_train()`
→ `validate_train_request(payload)`
→ `_enqueue_explicit_training()`
→ `_explicit_training_split(payload)`
→ `SplitRequest(mode=random_test_from_training_pool, experiment_percent=None, ...)`
→ `SplitRequest.__post_init__()`
→ 抛出：
`experiment_percent 必须大于 0 且小于 100`
→ HTTP 400。

也就是说：

浏览器认为“固定 Benchmark 已经取代随机试验集，所以删除 experiment_percent”；

admission owner 却仍要求先构造一份完整 random split request。

**已有测试之间的直接矛盾：**

前端：

`tests/frontend/training-submit.test.mjs`

Benchmark reuse 用例明确断言：

`Object.hasOwn(sent, 'experiment_percent') === false`

即测试保护“前端删除 experiment_percent”。

后端：

`tests/api/test_training_request.py`

`test_reusable_benchmark_...` 的成功路径 POST 则手工提交：

- `split_mode: random_test_from_training_pool`
- `validation_percent: 20`
- `experiment_percent: 20`
- benchmark source/scope

然后才断言 TrainingPrepare 最终把 frozen payload 改成：

- `split_mode = independent_test_set`
- benchmark test IDs
- effective training IDs。

所以两边各自测试都通过，但它们没有用“前端真实构造出来的 payload”做跨层测试。

**为什么是 Bug / 前后端不一致：**

这是明确的 contract split-brain：

- Browser owner 认为 Benchmark identity 已足够，不应再传随机试验比例；
- Admission owner 仍按随机 split schema 校验；
- Prepare owner 才真正知道如何把固定 Benchmark 转换成独立试验集。

由于 admission 在 Prepare 之前，当前真实 UI 功能会被前置校验挡死。

**影响：**

- 用户勾选“复用当前固定评测基准”后无法成功创建训练任务；
- 严格固定 Benchmark 的迭代训练主流程被 UI payload 直接破坏；
- 用户可能只能关闭复用、重新随机试验，失去版本间严格可比性；
- 容易误判为 Benchmark Scope、训练素材或服务器异常；
- 当前单元/API 测试均可能绿色，因为缺少真实前端 payload → API 的合同测试。

**为什么 CI 没发现：**

现有测试被分成两套：

1. 前端测试只验证浏览器 payload 形状，并把删除 `experiment_percent` 当成正确；
2. 后端测试自己构造一个不同的 payload，仍带 `experiment_percent`，所以 admission 能通过。

没有测试把 `TrainingSubmitRuntime.build/submit` 的 Benchmark payload 原样送入 v12 TrainReq/admission。

**建议最小修复：**

不能靠在前端随便补一个无意义的 20% 只为骗过 admission，也不应让 Benchmark 模式继续伪装成普通 random split。

应收敛单一合同，最小范围可选方向是：

- admission 在识别到完整且合法的 `benchmark_source_version_id + benchmark_scope_id` 时，允许 Benchmark-specific request 先以“训练候选 + validation ratio + benchmark identity”进入 Prepare；
- 由已有 TrainingPrepare canonical owner 解析固定 Benchmark、排除 benchmark test IDs，并冻结最终 `independent_test_set` SplitManifest；
- 前端与后端共享同一 Benchmark request contract。

不要新增第二 Split owner，也不要把固定 Benchmark test IDs 下发到浏览器。

回归测试必须新增真实跨层合同：

`TrainingSubmitRuntime Benchmark payload`
→ v12 start
→ 202
→ TrainingPrepare
→ frozen independent benchmark split。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-055 — 取消已 ASSIGNED / CLAIMED 但尚未 start 的任务不会释放 Node Assignment，可永久形成幽灵 GPU reservation

**级别：高**  
**模块：Central Scheduler / Agent Assignment / Task Cancellation / GPU Reservation**

**现象：**

Central Scheduler 给一个 QUEUED task 创建：

`task_node_assignments.state = ASSIGNED`

或者 Agent 已 claim 成：

`CLAIMED`

时，TaskRepository 中任务本身仍保持：

`QUEUED`

直到 Agent 调用 `start_execution()` 才原子转：

`QUEUED -> RUNNING`。

如果用户在这个窗口取消任务：

`TaskRepository.request_cancel(task_id)`

会把 QUEUED task 直接改为：

`CANCELLED`

但不会同步释放对应的 active Node Assignment。

结果 assignment 仍保持：

- ASSIGNED；或
- CLAIMED（lease 到期后又被 `claim_for_node()` 退回 ASSIGNED）。

没有通用清理逻辑把“task 已非 QUEUED/RUNNING，但 assignment 仍 active”的记录变为 RELEASED。

**真实调用链：**

调度：

`CentralTaskAllocator.assign_next()`
→ INSERT `task_node_assignments(... state='ASSIGNED' ...)`

Agent：

`claim_for_node()`
→ `ASSIGNED -> CLAIMED`
→ task 仍是 QUEUED。

此时用户停止：

`TaskRepository.request_cancel()`
→ 对 QUEUED：
`tasks.status = CANCELLED`
→ 清 task worker/lease
→ **没有调用 `CentralTaskAllocator.release()`**。

之后：

`claim_for_node()`

只会选择：

`assignment.state='ASSIGNED' AND task.status='QUEUED'`

所以 cancelled task 不会再被 Agent claim/start。

但是已有 assignment 也不会被释放。

CLAIMED lease 超时时：

`claim_for_node()` 只做：

`CLAIMED -> ASSIGNED`

不会检查 joined task 已经 CANCELLED。

**为什么是 Bug / 生命周期旁路：**

Node Assignment 是 Agent start 前的 GPU / node reservation truth。

当前取消只修改 TaskRepository truth，没有同步 retirement assignment truth。

更严重的是，占用计算本身没有 join task status：

`_node_active_work_count()`

直接统计所有：

`task_node_assignments WHERE state IN ('ASSIGNED','CLAIMED')`

`_assigned_gpu_ids()`

也直接读取所有 active assignment 的：

`resolved_execution_config.selected_gpu`

因此 cancelled task 的幽灵 assignment 会继续：

- 增加节点 active work count；
- 把对应 `cuda:N` 标成已占用；
- 阻止同 GPU 分配给后续真实任务。

**与 AUDIT-015 的区别：**

AUDIT-015 是：

节点 `enabled=false` 后，已 ASSIGNED/CLAIMED 的任务无法 start，且 assignment 不释放。

AUDIT-055 是：

**任务本身被用户取消** 后，task 已经明确成为 CANCELLED，但 assignment 生命周期仍没有跟随结束。

触发原因、正确 owner 和回归合同不同，不能合并成同一问题。

**影响：**

- 取消一个尚未 start 的训练任务后，该 GPU 可能永久显示为已预约；
- 单 GPU 节点可能因此再也拿不到新的训练任务；
- 多 GPU 节点会永久少一张可调度 GPU；
- active work count 长期偏大，节点打分失真；
- 只能依赖人工调用 assignment release 或数据库修复恢复；
- CLAIMED lease expiry 不能自愈，因为只会回退到 ASSIGNED。

**为什么 CI 没发现：**

现有 `tests/unit/test_task_node_assignments.py` 已覆盖：

- assignment / claim；
- CLAIMED lease 到期后可 reclaim；
- manual release；
- GPU distinct reservation；
- legacy worker fencing；
- concurrent assign；

但没有覆盖：

`assign/claim -> TaskRepository.request_cancel(QUEUED) -> assignment must RELEASE`

所以 Task 状态测试和 Assignment 测试各自都能通过，却缺少跨 owner cancellation contract。

**建议最小修复：**

不要让 TaskRepository 反向依赖 CentralTaskAllocator，避免制造新的双向 owner。

应在 canonical cancellation service / API owner 中，把：

- task cancel；
- pre-start assignment release

组成同一 lifecycle operation，或者给 assignment 层增加一个基于 task terminal truth 的 bounded reconciliation，在 scheduler/claim 前原子释放不再可执行的 active assignments。

关键合同：

- QUEUED + active ASSIGNED/CLAIMED 被 operator cancel 后，assignment 必须成为 RELEASED；
- 对应 selected GPU 立即可再次调度；
- RUNNING execution 仍由 execution lease/cancel handshake 管理，不能误释放正在运行的 task；
- generation / lease fencing 不能放宽。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 ASSIGNED-cancel、CLAIMED-cancel、GPU 可立即复用三个场景。

---


### AUDIT-056 — v63 线上反馈工作台把“最近 100 条混合历史”当成完整待复核队列，旧 pending_review 可永久从 UI 消失

**级别：中～高**  
**模块：Online Feedback / Review Queue / Frontend Workbench / Bounded Truth**

**现象：**

当前 v63 线上抽检 / 反馈工作台固定请求：

`GET /api/v63/projects/{project_id}/online-feedback?limit=100`

没有 cursor，也没有按 `status=pending_review` 单独获取活动待办。

后端 `OnlineFeedbackRepository.list()` 默认又是：

`ORDER BY created_at DESC, id DESC LIMIT ?`

即把：

- pending_review；
- confirmed；
- dismissed

三种状态混在同一个最近 N 条窗口里。

因此只要后续反馈持续产生，较老但仍未处理的 `pending_review` 可以被较新的 confirmed / dismissed / pending 记录一起挤出前 100。

**真实调用链：**

前端：

`loadOnlineFeedback63()`
→ `GET /api/v63/projects/{project_id}/online-feedback?limit=100`
→ `state.onlineFeedback63 = result.items`
→ `feedbackRows63()`
→ 只有当前这 100 条里的 `pending_review` 才渲染“复核”按钮。

页面摘要也只对这 100 条计算：

`待复核 rows.filter(item => item.status === 'pending_review').length 条`

后端：

`list_online_feedback(project_id, status="", limit=100)`
→ `OnlineFeedbackRepository.list(status="", limit=100)`
→ `SELECT * FROM online_feedback ORDER BY created_at DESC,id DESC LIMIT ?`

虽然 API 本身支持传：

`status=pending_review`

但当前工作台没有使用该 active queue filter，也没有消费 cursor。

**为什么是 Bug / bounded truth：**

线上反馈的 `pending_review` 不是普通历史展示，它是需要人工处理的活动工作队列。

“最近 100 条所有状态”只能作为 history preview，不能承担完整 active review truth。

当前一旦 pending 被窗口挤掉：

- 它仍在数据库里；
- 仍是 `pending_review`；
- 但工作台再也不展示它；
- 用户也没有分页 / 下一页 / 仅待复核过滤器去找它。

除非知道 feedback_id 并直接拼 detail URL，否则正常 UI 无法恢复处理。

**影响：**

- 101+ 条反馈后，旧待复核记录可能永久积压；
- UI 显示的“待复核 N 条”不是项目真实待办数量；
- 线上反馈无法按完整生命周期清空；
- confirmed feedback candidate、后续补数据链会漏掉长期未复核样本；
- 生产现场如果外部系统持续回传抽检，问题会随时间自然出现，不需要极端并发。

**与 AUDIT-042 的区别：**

AUDIT-042 是：

“已确认反馈进入 Supplement Candidate Set 时最多取 500 条”。

AUDIT-056 是：

“反馈还处于 pending_review 阶段时，人工审核工作台只看最近 100 条混合历史”。

前者是 Candidate 构建截断，后者是 active review queue 截断，生命周期阶段和正确 owner 不同。

**为什么 CI 没发现：**

现有前端逻辑把：

`limit=100`

视为正常列表加载，并只测试当前返回项的展示 / 复核操作。

缺少 101+ feedback 的合同测试：

- 100 条较新 confirmed/dismissed；
- 1 条更老 pending_review；
- 工作台仍必须能发现并处理这个 pending。

**建议最小修复：**

不要简单把 100 改成 1000 或无限。

应把 active review truth 和 terminal history 分离：

- pending_review：完整可分页工作队列，至少提供 cursor / next_cursor / total；
- confirmed / dismissed：普通历史分页；
- 工作台默认应优先加载完整 pending queue，再按需加载 terminal history；
- 摘要里的“待复核 N 条”应来自 aggregate / indexed count，而不是当前页面长度。

如果保留单一 endpoint，至少应支持：

- `status=pending_review&cursor=...&limit=...`
- 返回 `next_cursor` 与真实 total；
- 前端消费分页或提供明确“加载更多”。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 101+ mixed history 时旧 pending 仍可发现、可复核。

---


### AUDIT-057 — Label / Material Integrity 的“当前审计恢复”把 bounded generic MaterialBatch page 当 active truth，且专用 POST 无防重，可重复创建项目级 Full Audit

**级别：中～高**  
**模块：Label Integrity / Material Integrity / MaterialBatch / Polling / Bounded Active Truth**

**现象：**

当前有两套项目级 Full Audit：

- Label Integrity：`AUDIT_LABEL_INTEGRITY`
- Material Integrity：`AUDIT_MATERIAL_INTEGRITY`

它们的专用创建 endpoint 每次都会无条件创建新的 Durable `MATERIAL_BATCH`：

- `POST /api/v54/projects/{project_id}/labels/integrity/audits`
- `POST /api/v62/projects/{project_id}/material-integrity/audits`

后端没有：

- “同项目同 operation 已有 active audit”检查；
- idempotency key；
- canonical current-audit lookup。

前端恢复当前审计时，却不是按 operation 精确查询，而是在 generic MaterialBatch 的固定窗口里再筛 operation。

Label Integrity：

`GET /api/v62/projects/{project_id}/material-batches?active_only=true&limit=100`

然后：

`find(operation === 'AUDIT_LABEL_INTEGRITY')`

Material Integrity：

`GET /api/v62/projects/{project_id}/material-batches?limit=50`

然后：

`find(operation === 'AUDIT_MATERIAL_INTEGRITY')`

两处都不消费 `next_cursor`。

**真实调用链：**

Label Integrity：

`renderLabelManagement414()`
→ `resumeLabelIntegrity414()`
→ generic active MaterialBatch page 100
→ 未找到 audit 时页面仍显示“运行 Full Audit”
→ `startLabelIntegrityAudit414()`
→ 专用 POST
→ `create_label_integrity_audit()`
→ `repository.create()`

Material Integrity：

`openMaterialIntegrityAudit47()`
→ generic MaterialBatch page 50
→ 未找到 audit 时弹出“尚未运行素材完整性审计”
→ 用户点击“运行 Full Audit”
→ `startMaterialIntegrityAudit47()`
→ 专用 POST
→ `create_material_integrity_audit()`
→ `repository.create()`

两个 create owner 都没有查找已有 active audit。

**为什么是 Bug / bounded truth：**

generic MaterialBatch page 只是分页列表，不是“某个 operation 当前是否存在活动任务”的完整 truth。

如果一个项目同时有很多：

- CLEAN；
- AI_ANNOTATE；
- REMAP；
- DELETE；
- integrity repair；
- 其它 batch

现有 Full Audit 可以被挤出前 100 / 前 50。

此时 UI 会错误判断“没有当前审计”，而后端也不做第二道防重，于是同一项目会排入第二个、第三个相同 Full Audit。

这些审计本身都是全项目扫描，重复创建会放大 I/O 和 Worker 队列压力。

**影响：**

- 同一项目可能堆积重复 Full Audit；
- 用户看到的“当前审计”不是 canonical truth；
- 旧 audit 仍在运行/排队时，新 audit 又进入队列；
- 大量 MaterialBatch 活动任务时更容易触发；
- 项目级审计会重复扫描 AnnotationRepository / MaterialRepository；
- 可能延迟真正的清洗、AI 标注、标签统一等批任务；
- PollRegistry 只跟踪当前发现的 task_id，旧 audit 可能成为“后台孤立但仍运行”的任务。

**与 AUDIT-023 / AUDIT-021 的区别：**

AUDIT-023 是 Cleaning list 先取最近 100 个 MATERIAL_BATCH 再筛 CLEAN；

AUDIT-021 是 AI material-state 只看前 100 个 active task。

AUDIT-057 是：

**项目级 Integrity audit 的恢复与防重都错误依赖 bounded generic batch page，而专用创建 endpoint 又没有 active-audit fence，最终会真实创建重复 durable 任务。**

根因和生命周期后果不同。

**为什么 CI 没发现：**

现有测试分别验证：

- audit task 可以创建；
- generic MaterialBatch list 支持 cursor；
- audit 可以运行并产生结果；

但没有组合：

1. 先创建一个 active integrity audit；
2. 再创建 100+ / 50+ 其它 batch 把它挤出第一页；
3. 前端恢复不到；
4. 再次点击 Full Audit；
5. 后端是否拒绝重复 active audit。

**建议最小修复：**

不要把前端 limit 改成更大的固定数字。

应建立 operation-aware active truth，优先方向：

- 后端专用 create endpoint 在同一事务内检查同项目同 audit operation 的 active task；
- 若已有 active audit，返回该 task（幂等）或 409 + canonical task_id；
- 提供按 `operation` 查询 active batch 的精确 endpoint/filter；
- 前端恢复逻辑使用 operation-aware query，而不是 generic page 后 `find()`；
- terminal history 继续 cursor pagination，不与 active truth 混用。

不要新建第二套审计 runtime；仍然使用现有 `MATERIAL_BATCH` owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 101+ active batches / 51+ recent batches 时仍能发现已有 audit，且重复 POST 不会创建第二个 active Full Audit。

---


### AUDIT-058 — Material Integrity 结果页忽略 groups / items 的 next_cursor，101+ 问题组或单组 101+ 素材会从 UI 永久不可见

**级别：中～高**  
**模块：Material Integrity / Result Pagination / Dataset Quality / 1k-20k Scale**

**现象：**

Material Integrity 后端已经为大规模审计结果实现 cursor pagination：

问题组：

`GET /api/v62/projects/{project_id}/material-integrity/audits/{task_id}/groups?cursor=&limit=`

组内素材：

`GET /api/v62/projects/{project_id}/material-integrity/audits/{task_id}/groups/{group_key}/items?cursor=&limit=`

两者都：

- 最多允许 `limit=100`；
- 返回 `next_cursor`。

但当前前端固定：

- groups：`?limit=100`
- items：`?limit=100`

然后直接只用：

`body.items || []`

完全不读取、不保存、不消费 `next_cursor`。

**真实调用链：**

问题组页：

`openMaterialIntegrityAudit47()`
→ `GET .../groups?limit=100`
→ `state.materialIntegrityAudit47.groups = groups.items`
→ 只渲染这 100 个 group。

组详情页：

`openMaterialIntegrityGroup47(taskId, groupKey)`
→ `GET .../groups/{groupKey}/items?limit=100`
→ `state.materialIntegrityGroup47.items = body.items`
→ 只渲染这 100 张素材。

后端已经明确生成：

- `next_cursor` for groups；
- `next_cursor` for items；

前端没有任何“下一页 / 加载更多 / 自动翻页”处理。

**为什么是 Bug / bounded truth：**

Material Integrity 不是普通摘要列表。

它是用户处理以下真实数据问题的唯一工作台之一：

- DUPLICATE_IDENTICAL；
- DUPLICATE_ANNOTATION_CONFLICT；
- MATERIAL_OBJECT_MISSING；
- CONTENT_HASH_MISMATCH；
- INVALID_IMAGE。

如果审计结果超过一页，被截断的 group / material 不只是“历史没展示完”，而是用户根本无法：

- 查看；
- 进入标注；
- 删除；
- 保留；
- 人工判断冲突 Ground Truth。

也就是说，后端已经是 bounded/cursor contract，但 UI 又把第一页当 full truth。

**典型 10k / 20k 场景：**

1. 若存在 130 个不同重复/异常 group：
   - UI 只显示前 100；
   - 后 30 个 group 永久不可见。

2. 若一个重复 hash group 有 300 张相同图片：
   - UI 只展示前 100 张；
   - 后 200 张无法被选中、删除或人工比较。

3. 大批量导入后出现大量单条缺失/损坏素材时：
   - group 数量很容易超过 100；
   - 当前页面会错误给用户“已完整展示”的感觉。

**与 AUDIT-050 的区别：**

AUDIT-050 是 Cleaning Detail 仍走 v47 compatibility endpoint，一次 `fetchall()` 全量 hydrate 10k/20k 结果。

AUDIT-058 恰好相反：

后端已经正确分页，但 Material Integrity 前端完全不消费后续页，导致**结果丢失/不可操作**。

一个是无界 hydration，一个是 bounded page 被误当 full truth。

**与 AUDIT-057 的区别：**

AUDIT-057 是“当前 audit 的发现/恢复/防重”错误使用 bounded generic task page，可能重复创建 Full Audit。

AUDIT-058 是“某次已经完成的 audit 的结果展示/处理”只消费第一页。

生命周期阶段不同，应该分开修复和回归。

**为什么 CI 没发现：**

当前测试主要验证：

- groups endpoint 支持 cursor；
- items endpoint 支持 cursor；
- audit 能产生问题组；
- 前端能渲染第一页。

缺少浏览器级 101+ contract：

- 101+ issue groups；
- 单 group 101+ items；
- 用户必须能继续翻页并处理后续结果。

**建议最小修复：**

不要把 limit 提高到 1000 或无限。

保持现有后端 cursor contract，前端补单一分页 owner：

- groups 支持“加载更多”或自动分页；
- group items 支持“加载更多”；
- 保存各自 `next_cursor`；
- 切换 audit/group 时清理旧 cursor state；
- 删除/保留后只定向刷新当前 group，不做全量 broad reload。

对 10k/20k 场景，默认首屏仍保持 bounded 100，保证响应速度。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 101 groups 和 101 items 两种分页边界。

---


### AUDIT-059 — 标签统一任务恢复只看前 100 个 active MaterialBatch，且 remap 创建无 active-source 防重，可重复提交同一批标签统一

**级别：中～高**  
**模块：Label Unify / REMAP_ANNOTATION_LABELS / MaterialBatch / PollRegistry / Bounded Active Truth**

**现象：**

标签管理页面刷新/重新进入后，当前后台统一任务通过：

`GET /api/v62/projects/{project_id}/material-batches?active_only=true&limit=100`

恢复。

然后前端只在这 100 条里：

`find(activeLabelRemap414)`

其中 `activeLabelRemap414` 要求：

- operation = `REMAP_ANNOTATION_LABELS`
- `retire_sources_on_success === true`
- status 为 active。

前端不消费 `next_cursor`。

如果当前标签统一任务被其它 100+ active MaterialBatch 挤出第一页：

- 页面恢复不到它；
- banner 被清空；
- PollRegistry 无法重新 arm；
- 用户看到的界面会像“没有正在运行的标签统一任务”。

此时用户可以再次选择相同 source labels → target，并再次提交。

**真实调用链：**

页面恢复：

`renderLabelManagement414()`
→ `resumeLabelUnify414()`
→ generic active MaterialBatch page 100
→ `find(activeLabelRemap414)`
→ 未找到则 `renderLabelRemapBanner414(null)`

再次提交：

`startLabelUnify414()`
→ `POST /api/v54/projects/{project_id}/labels/unify`
→ `_v54_start_unify()`
→ `create_annotation_remap_by_labels(... retire_sources_on_success=True)`

后端 remap create：

- 校验来源/目标标签当前 active；
- 从 AnnotationRepository 冻结 live reference snapshot；
- 冻结 selection.sqlite3；
- 写 request/checkpoint；
- 构造 `MATERIAL_BATCH`；
- **直接 `repository.create(task)`**。

没有查找：

- 同项目；
- 同 operation；
- 同 source_labels；
- 同 target_label

是否已经存在 active remap。

**为什么是 Bug / bounded truth：**

当前 UI 的 active-task 恢复使用 bounded generic page，而 create owner 又没有 idempotency/fence。

这会把一个本来单一的标签治理事务拆成多个 durable remap：

1. 第一个 remap 仍 queued/running；
2. 页面因为第一页截断“忘记”它；
3. 用户再次提交相同标签；
4. 第二个 remap 再次冻结 selection/revision；
5. 两个任务进入同一个 materials resource queue。

因为来源标签只在完整成功后 retire，第二次提交发生时来源仍可能保持 active，所以 admission 不一定能拦住重复请求。

**可能结果：**

- 重复任务排队，占用 Worker/资源；
- 第二个任务在第一任务改完 AnnotationRepository 后因 revision/CAS 失败；
- 或第一任务完成退役 source 后，第二任务在执行阶段 fail-closed；
- UI 出现“刚创建的统一失败”，用户误以为第一次统一也失败；
- 大规模 remap 会重复构建 selection / checkpoint，增加磁盘和数据库 I/O；
- 多次刷新/重复点击可继续堆积更多重复 remap。

**与 AUDIT-057 的区别：**

AUDIT-057 是项目级 Label/Material Integrity Full Audit 的发现/防重问题。

AUDIT-059 是真正会修改 Ground Truth 和治理状态的 `REMAP_ANNOTATION_LABELS` 统一任务。

两者虽然都由 bounded generic MaterialBatch page 触发，但写入语义、风险和正确防重 key 不同：

- integrity audit：按 project + operation 防重；
- label remap：至少按 project + source label set + target + active lifecycle 防重。

**为什么 CI 没发现：**

现有测试保护：

- remap selection freeze；
- AnnotationRepository CAS；
- retirement 双清零；
- PollRegistry 单 owner；
- 大批量 remap 分批处理。

但缺少：

1. 100+ active MaterialBatch；
2. 一个 active `REMAP_ANNOTATION_LABELS` 被挤出第一页；
3. 页面刷新恢复；
4. 重复提交相同 source/target；
5. 后端必须返回已有 task 或拒绝重复创建。

**建议最小修复：**

不要把 `limit=100` 改成更大常数。

建议：

- 给 MaterialBatch list 增加 operation filter，或增加 operation-aware active query；
- `resumeLabelUnify414()` 按 `REMAP_ANNOTATION_LABELS` 精确恢复；
- remap create owner 在 publication 前检查同 project + canonical source set + target 的 active task；
- 如果是同一请求，返回已有 task（幂等）或明确 409 + task_id；
- 不创建第二个 Remap runtime，不改变现有 AnnotationRepository/CAS owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 101+ active batch 时 remap 仍可恢复，以及重复 source/target 不会创建第二个 active task。

---


### AUDIT-060 — 自动调度任务在 ASSIGNED / CLAIMED 后节点离线不会自动释放 assignment，QUEUED 任务可永久卡在失联节点

**级别：高**  
**模块：Central Scheduler / Service Node / Agent Assignment / Failure Recovery / GPU Reservation**

**现象：**

Central Scheduler 为一个自动调度的 QUEUED task 创建：

`task_node_assignments.state = ASSIGNED`

或者 Agent 已经 claim 成：

`CLAIMED`

但尚未调用 `start_execution()` 时，如果目标节点突然：

- 宕机；
- Agent 进程退出；
- 网络中断；
- 长时间不再 heartbeat；

当前 assignment 没有任何 stale-node reconciliation。

任务本身仍然是：

`QUEUED`

但因为存在 active assignment，后续 `assign_next()` 会永久把它排除在重新调度候选之外。

**真实调用链：**

初次自动分配：

`CentralTaskAllocator.assign_next()`
→ 只从 online nodes 里选择节点
→ INSERT：
`task_node_assignments(... state='ASSIGNED' ...)`

如果 Agent 已 claim：

`claim_for_node(node_id)`
→ `ASSIGNED -> CLAIMED`
→ 生成短期 assignment lease
→ task 仍保持 QUEUED。

节点随后失联。

CLAIMED lease 到期后，当前唯一自动处理是：

`claim_for_node(node_id)`

内部：

`CLAIMED -> ASSIGNED`

条件只看：

- 同 node_id；
- lease 已过期。

它不会：

- 检查 node heartbeat 是否已 stale；
- 把 assignment RELEASED；
- 让任务重新进入全局 allocator。

更关键的是：

`assign_next()`

候选 SQL 明确排除任何存在：

`assignment.state IN ('ASSIGNED','CLAIMED')`

的 QUEUED task。

因此该任务不会被分给其它仍在线节点。

**为什么是 Bug / 生命周期卡死：**

Node assignment 是“start_execution 之前的临时 reservation truth”，不应该比节点在线生命周期更持久。

当前它没有 TTL / stale-node retirement：

- CLAIMED 有 lease，但过期只退回 ASSIGNED；
- ASSIGNED 本身没有 expiration；
- allocator 不做 stale node cleanup；
- Service Node heartbeat stale 只影响“新任务是否能选这个节点”，不会清已有 assignment。

所以一个已经失联的节点可以永久持有一个尚未 start 的任务。

**与 AUDIT-015 的区别：**

AUDIT-015：

- 操作者把节点 `enabled=false`；
- 已 ASSIGNED / CLAIMED 任务 start 会 fail-closed；
- assignment 仍不释放。

AUDIT-060：

- 节点没有被显式 disabled；
- 只是现实中的宕机 / Agent 退出 / 心跳过期；
- 自动调度也不会回收 assignment 或迁移到其它健康节点。

这是更常见的故障恢复路径，触发源和自动恢复合同不同。

**与 AUDIT-055 的区别：**

AUDIT-055：

- task 自己被 operator cancel；
- task 已变 CANCELLED，但 assignment 仍 active，形成幽灵 reservation。

AUDIT-060：

- task 仍是合法 QUEUED；
- node 已失联；
- assignment 继续阻止 task 在其它节点重新调度。

一个是 task lifecycle retirement 缺失，一个是 node failure recovery 缺失。

**影响：**

- 自动训练任务可永久停留在“等待资源/已分配但不执行”；
- 自动转换、部署测试、素材导入、清洗等 Agent task 同样可能受影响；
- 单节点故障后，即使其它兼容节点在线也不会接管；
- 对训练任务，原 selected GPU reservation 仍保留在 assignment truth；
- 节点恢复前任务只能靠人工调用 assignment release 才能迁移；
- 生产多节点环境下会把暂时故障放大成永久任务阻塞。

**为什么 CI 没发现：**

当前 assignment tests 已覆盖：

- 只选择 online node；
- claim lease 到期后可重新 claim；
- manual release；
- 多 GPU reservation；
- node capability / strict affinity；
- concurrent assignment 唯一性。

但没有组合测试：

1. auto task 被分配到 node A；
2. A 的 heartbeat 变 stale；
3. node B 仍在线且 capability 兼容；
4. assignment 超过合理 TTL；
5. scheduler 应释放 A 的 reservation；
6. 同一 task 应可自动迁移到 B。

**建议最小修复：**

不要新建第二 Scheduler。

应在现有 `CentralTaskAllocator` 内增加 assignment reconciliation，保持一个 owner：

- 在 `assign_next()` / claim 调度事务前，扫描 active ASSIGNED/CLAIMED；
- joined task 必须仍是 QUEUED；
- joined node 必须仍 enabled 且 heartbeat fresh；
- CLAIMED 还要考虑 claim lease；
- 对 auto-affinity task：节点 stale 超过明确 grace period 后 RELEASED，并允许重新分配；
- 对用户手工 strict node affinity：可 RELEASED reservation，但 task 继续 QUEUED 等指定节点恢复，不能 spill 到其它节点；
- release 必须记录明确 reason，例如 `node_heartbeat_stale_before_start`。

不要影响已经 RUNNING 的 execution；RUNNING 继续由 execution lease/generation fencing 恢复。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，至少覆盖 ASSIGNED stale-node、CLAIMED stale-node、auto reassign、strict-affinity 不 spill 四个场景。

---


### AUDIT-061 — ZIP multipart completed session 永不 GC，终态 Import Job 删除也不清理，形成无界 orphan upload metadata

**级别：中**  
**模块：ZIP Multipart / Import Job Cleanup / Filesystem Lifecycle / Long-running Storage Hygiene**

**现象：**

浏览器大 ZIP 上传使用：

`ZipMultipartRepository`

分片合并成功后：

`assemble(upload_id, destination)`

会：

- 把合并后的 ZIP 写到 Import Job 自己的 `source.zip`；
- 删除 `import_uploads/{upload_id}/parts`；
- 把 multipart meta 标成：
  - `status = completed`
  - `expires_at = None`
- 永久保留：
  `import_uploads/{upload_id}/upload.json`

multipart GC 的实现又明确：

`status == completed -> _expired() == False`

因此 completed upload session 永远不会被 GC。

与此同时，Import Job 的终态清理：

`DELETE /api/v19/projects/{project_id}/import/jobs`

只：

`shutil.rmtree(job_file.parent)`

单任务 DELETE 也只删：

`v19_job_dir(project_id, job_id)`

两处都不会删除：

`project/import_uploads/{upload_id}`

所以成功 multipart import 的 upload metadata 会永久孤立。

**真实调用链：**

上传：

`create_or_resume()`
→ `import_uploads/{upload_id}/upload.json`
→ 多个 `parts/*.part`

完成：

`POST .../uploads/{upload_id}/complete`
→ `_v19_finalize_multipart_upload()`
→ `repository.assemble(upload_id, job_dir/source.zip)`
→ meta:
`status='completed'`
`expires_at=None`
→ 删除 parts
→ 保留 upload.json。

GC：

`cleanup_expired_if_due()`
→ `_expired(meta)`
→ 如果 `status == completed`：
`return False`

永久跳过。

后续：

`create_or_resume()`

只会复用：

`existing.get('status') != 'completed'`

所以 completed session 也不会用于断点续传复用。

终态 job 删除：

只清 job directory，不触碰 multipart repository。

**为什么是 Bug / 生命周期泄漏：**

completed upload metadata 在完成合并后仅用于短期幂等/恢复。

一旦对应 Import Job 已进入终态并被用户清理：

- source ZIP 已被删除；
- job.json 已被删除；
- session 不再可 resume；
- create_or_resume 也不会复用它；
- 但 upload metadata 永久存在。

这是典型的 owner 生命周期不闭环：

`Import Job` 被删除，
`Multipart Upload Session` 却没有跟随 retirement。

**影响：**

- 每次成功 multipart ZIP 导入永久多一个目录 + upload.json；
- 长期运行后 `import_uploads` 目录数量无界增长；
- 项目备份、目录扫描、迁移、磁盘 inode 使用持续增加；
- 用户执行“清空已完成导入记录”时并没有真正清干净相关上传元数据；
- 1k/10k 次导入后会形成明显的目录/元数据技术债。

分片本身会在 assemble 后删除，所以这不是大文件容量泄漏；主要是**无界 orphan metadata / inode 生命周期问题**。

**与 AUDIT-014 的区别：**

AUDIT-014 是：

单个 ZIP Import Job DELETE 可以删除仍在活动中的 job directory，破坏正在执行的 Worker。

AUDIT-061 是：

成功完成后的 multipart session 在终态 job retirement 后反而**永远不被删除**。

一个是删得太早，一个是永远不删。

**为什么 CI 没发现：**

现有 multipart 测试重点验证：

- create/resume；
- 分片重试；
- assemble；
- incomplete TTL GC；
- completed upload 不被“上传阶段 GC”误删。

但没有跨 owner lifecycle 测试：

1. multipart 完成；
2. import job 完成；
3. terminal job 被清理；
4. 对应 completed multipart metadata 应一起 retirement。

**建议最小修复：**

不要让普通上传 TTL GC 直接无条件删除 completed sessions，因为 finalize/recovery 的短窗口仍需要它们。

正确方向是建立显式 retirement：

- 当 Import Job 达到终态并超过安全保留期，或用户明确删除终态 job 时；
- 由 Import Job cleanup owner 调用 multipart repository 的显式 `retire(upload_id)`；
- 仅允许删除 `status=completed` 且对应 job 已终态/不存在的 session；
- 活动 `merging/validating/selecting/running` 绝不能被清；
- 可增加 bounded orphan reconciliation，处理历史遗留 completed session。

不要引入第二套 ZIP owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，覆盖 terminal job delete/clear 后 completed multipart session 被 retirement，同时活动 finalize session不被删除。

---


### AUDIT-062 — 正式 ZIP Import 仍由 daemon thread 执行且没有 crash recovery；进程重启可永久卡 running，并留下已写 Annotation / 素材文件但未提交 MaterialRepository 的半成品

**级别：高**  
**模块：ZIP Import / Crash Consistency / Annotation Ground Truth / MaterialRepository / Runtime Durability**

**现象：**

v19 ZIP 上传完成、标签映射确认后，正式导入通过：

`threading.Thread(target=v19_import_worker, daemon=True)`

执行。

这一步没有进入 Durable Task runtime，也没有 lease / heartbeat / generation / startup recovery。

更严重的是，导入过程不是“全部只写内存，最后一次原子落盘”。

当前 batch 机制是：

- MaterialRepository record 暂存在当前线程的 `_IMAGE_BATCH_CTX.batch`；
- 但每张图片的物理素材对象会立即写入 storage；
- 对结构化导入，正式 AnnotationRepository Ground Truth 也会立即 `write_annotation()`；
- 只有最终 `_v50_end_image_batch(save=True)` 才把 buffered MaterialRepository rows 一次提交。

正常 Python exception 时，代码会调用：

`_v50_end_image_batch(save=False)`

删除已写素材文件和 AnnotationRepository rows。

但如果 Web 进程被 kill / 宕机 / 容器重启：

- in-memory batch 直接消失；
- except/finally cleanup 不会执行；
- job.json 保持 `status=running`；
- 已写物理素材 / AnnotationRepository 副作用可能遗留；
- MaterialRepository 尚未有对应 row。

**真实调用链：**

开始：

`POST /api/v19/projects/{project_id}/import/jobs/{job_id}/start`
→ `v19_update_job(status='running')`
→ daemon：
`v19_import_worker(...)`

Worker：

`_v50_begin_image_batch(project_id)`

每张图片：

`add_image(...)`

在 active batch 下：

1. 先写 storage object/source file；
2. 把 material record 放进：
   `batch["records"]`
3. structured annotation path 直接：
   `write_annotation(...)`
   → 正式 AnnotationRepository 已持久化。

最终：

`_v50_end_image_batch(save=True)`
→ MaterialRepository `upsert_many(records)`

正常失败：

`_v50_end_image_batch(save=False)`
→ `_v50_cleanup_buffered_image_batch_files()`
→ 删除 source file
→ 删除 AnnotationRepository rows。

进程级 crash 时第 4 步和 rollback 都不会发生。

**重启后也无法自动恢复：**

当前只有：

`_v19_recover_multipart_finalize()`

它只处理：

- `merging`
- `validating`

并且只在 import job list/detail GET 时触发。

对正式 import 的：

`status=running`

没有任何：

`_v19_recover_import`

或 startup reconciliation。

再次调用 `/start` 时：

`if job.get("status") == "running": return v19_public_job(...)`

也不会创建新 worker。

所以重启后任务可以永久显示 running，但实际上已经没有线程。

**为什么是 Bug / 生命周期与 Ground Truth 一致性问题：**

这不仅是“进度卡住”。

结构化 ZIP 导入在最终 MaterialRepository commit 之前已经写了正式 Annotation GT 和物理素材。

因此 crash 可能产生：

- AnnotationRepository 有 image_id；
- MaterialRepository 没有该 image_id；
- storage object 已存在；
- import job 永久 running；
- 后续同一 ZIP 重试又可能生成新 image_id / 重复物理对象。

这直接破坏 Annotation / Material 的跨 owner consistency。

**与现有 CLOSED Annotation GT 合同的关系：**

AnnotationRepository 仍然是唯一正式 GT owner，本问题不是新建第二 Annotation owner。

问题在于 ZIP runtime 对 AnnotationRepository 的写入事务边界不具备进程级 crash durability：

“Annotation 已提交”与“Material batch 最终提交”之间存在不可恢复窗口。

这是 CLOSED 架构之外的真实 crash-consistency Bug。

**与 AUDIT-014 的区别：**

AUDIT-014：

用户主动 DELETE 活动 ZIP job，直接删 job directory，破坏仍在运行的 daemon Worker。

AUDIT-062：

即使用户什么都不做，只要 Web 进程崩溃/重启，daemon Worker 消失且没有 recovery，同时可能留下半提交 GT / storage side effects。

**与 AUDIT-061 的区别：**

AUDIT-061 是终态完成后 multipart upload metadata 不 retirement 的长期小文件泄漏。

AUDIT-062 是正式导入执行阶段的 crash consistency / durable runtime 缺失，严重度更高。

**影响：**

- ZIP 导入任务可永久卡在 running；
- 正式 AnnotationRepository 出现 dangling image_id；
- 物理素材文件 / OSS 对象可能孤立；
- MaterialRepository 与 Annotation GT 数量不一致；
- 重试可能产生重复素材或额外孤儿；
- 10k/20k 大导入执行时间更长，进程重启窗口更大；
- 生产滚动部署、服务异常退出都会触发，而不仅是极端故障。

**为什么 CI 没发现：**

现有 ZIP tests 主要覆盖：

- multipart resume；
- background finalize；
- bounded preview；
- 10k 前端 contract；
- 正常异常时 rollback；
- 页面恢复/polling。

但没有真正的“进程在第 N 张结构化素材写完 Annotation 后被 kill”故障注入测试。

普通 exception 测试会执行 Python rollback，所以看不出进程级 crash 的问题。

**建议最小修复：**

不要新建第二 ZIP owner。

应把当前 v19 ZIP job 的执行状态提升为真正可恢复的单一 runtime contract，最小方向：

1. 正式 import 至少要有 persisted execution generation / checkpoint；
2. 启动时对 `running` job 做 reconciliation，不能把 job.json 的 running 当活线程真相；
3. 将“本次 job 已创建的 image_id / storage object / annotation identity”持久化成 rollback journal，而不是只放 ThreadLocal；
4. crash 后：
   - 要么从安全 checkpoint 重放；
   - 要么先按 journal 完整清理本 generation 副作用，再回到 retryable 状态；
5. 最终 MaterialRepository commit 与 Annotation/material side effects 要有明确 commit marker；
6. 已提交完成的 generation 必须幂等，避免重启重复导入。

如果可以复用现有 Durable MATERIAL_IMPORT 的 task/lease/checkpoint 能力，应优先收敛到已有 canonical owner，而不是再创造另一套 scheduler/runtime。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是，必须增加 kill/restart 故障注入：结构化 ZIP 在中途持久化 Annotation 后崩溃，重启后不得永久 running，也不得留下 orphan GT/storage。

---


### AUDIT-063 — Central Scheduler 只有手工 `allocate-next` API，没有生产调度驱动；Agent loop 只 claim 已存在 assignment，远程 Durable Task 缺少自动 assignment owner

**级别：高**  
**模块：Central Scheduler / Service Node / Agent Executor / Remote Training / Remote Conversion / Remote Cleaning / Remote Material Import**

**现象：**

当前 `CentralTaskAllocator.assign_next()` 是 Service Node / Agent 执行前唯一会创建：

`task_node_assignments.state = ASSIGNED`

的 owner。

但是当前生产代码中，它只通过：

`POST /api/v63/scheduler/allocate-next`

暴露为一个显式 HTTP API。

实际 Node Agent executor loop 每隔约 2 秒只调用：

`POST .../assignments/claim`

对应后端：

`AgentExecutionService.claim_assignment()`
→ `CentralTaskAllocator.claim_for_node(node_id)`

它只会 claim **已经存在的 ASSIGNED assignment**，不会调用 `assign_next()` 创建 assignment。

对当前生产文件的调用审计没有找到任何自动调用 `/api/v63/scheduler/allocate-next` / `assign_next()` 的 owner：

- `app.py`：无 `assign_next()` 调用；
- `node_agent.py`：无 allocate-next；
- `node_agent_executor_loop.py`：仅 claim；
- `node_agent_executor_runtime.py`：仅调用 assignments/claim 与 start；
- `service_nodes.py`：无 allocate-next；
- `task_worker.py`：无 allocate-next；
- `launcher.py`、`start.ps1`、`start.bat`、远端启动脚本：无 allocate-next。

所以当前 repo 内没有发现“持续把 QUEUED Durable Task 转成 Node Assignment”的生产调度 tick。

**真实调用链：**

存在的 allocation owner：

`CentralTaskAllocator.assign_next()`
→ 选择 eligible node / GPU
→ INSERT `task_node_assignments(... state='ASSIGNED' ...)`

仅暴露：

`central_scheduler_router()`
→ `POST /api/v63/scheduler/allocate-next`
→ `allocator().assign_next()`

Agent 真实 loop：

`NodeAgentExecutorLoop.run_once()`
→ `client.claim_assignment()`
→ `POST /api/v63/node-executor/{node_id}/assignments/claim`
→ `AgentExecutionService.claim_assignment()`
→ `allocator.claim_for_node(node_id)`
→ 只 SELECT：
`state='ASSIGNED' AND task.status='QUEUED'`

没有 assignment 时直接：

`claimed = false`

然后等待下一轮 polling。

因此 Agent 自身不会触发分配。

**测试为何看起来正常：**

当前测试把 allocation 步骤手工补上了。

`tests/api/test_central_scheduler_api.py`：

直接调用：

`POST /api/v63/scheduler/allocate-next`

再检查 assignments。

`tests/api/test_agent_executor_api.py`：

在 Agent claim 前显式：

`service.allocator.assign_next()`

然后才：

`POST .../assignments/claim`

所以测试验证的是：

“已经有人创建 assignment 后，Agent claim/start 能工作”。

没有验证：

“真实生产 Node Agent + Worker 启动后，无人工 HTTP 调用也能自动把 QUEUED task 分配给 Agent”。

**为什么是 Bug / owner 缺失：**

Central Scheduler 当前有完整的：

- eligible node；
- capability；
- connection_mode；
- GPU reservation；
- strict affinity；
- preemption；
- assignment generation；

但缺少生产中的**驱动 owner**。

这会导致：

QUEUED remote-capable task
→ 永远没有 ASSIGNED row
→ Agent 每轮 claim 都拿不到任务
→ task 持续 QUEUED。

更危险的是 TRAINING：

`AssignmentAwareFencedTaskRepository`

只会拒绝“已经存在 active assignment”的 task。

如果 remote Training 还没 assignment，local Worker 仍可能看到它。

而 `NodeScopedGPUResourceManager.admit()` 对：

`resource_key.startswith('training:remote:')`

明确直接：

`return True, None`

所以 local Worker 并不会因为 remote resource key 被 admission 拒绝。

随后 local Training handler 又明确：

如果：

`payload.target != 'local'`

则抛：

`remote training requires a configured NVIDIA training worker`

因此在没有自动 assignment owner 时，存在：

- remote task 长期排队；或
- local Worker 先 claim 后将 remote training 打成环境失败

两种错误结果。

**影响：**

- Remote Training 可能无法自动进入 Agent；
- Remote Conversion / Cleaning / Material Import / Deployment Test 等依赖 Central Assignment 的 Agent task 可能长期 QUEUED；
- Agent 心跳在线、capability 正常也不代表会拿到任务；
- 用户可能看到“服务节点在线、任务已创建”，但节点永远没有执行；
- remote Training 还可能被 local Worker 抢 claim 并错误终止；
- 现有 assignment / Agent API 测试会全部绿色，却不能证明生产自动调度闭环。

**与 AUDIT-015 / 055 / 060 的区别：**

- AUDIT-015：已经 ASSIGNED/CLAIMED 后节点被 disable；
- AUDIT-055：已经 ASSIGNED/CLAIMED 后 task 被用户取消；
- AUDIT-060：已经 ASSIGNED/CLAIMED 后节点离线；

AUDIT-063 发生得更早：

**task 还没有 assignment，根本没有生产 owner 自动执行 `assign_next()`。**

这是 Central Scheduler 驱动层缺口，不是 assignment retirement 缺口。

**建议最小修复：**

不要新建第二 Scheduler。

必须复用现有：

`CentralTaskAllocator.assign_next()`

作为唯一 assignment owner，只补一个明确且单例的生产驱动。

可选最小方向：

- 由现有 Worker/Service Node control-plane heartbeat owner 在一次 heartbeat tick 中 bounded 调用 `assign_next()`；
- 或在 Agent claim 前，由中央端原子尝试 allocation，再 claim 当前 node；
- 必须有跨进程单 owner / lock，避免多个 Web/Worker 进程同时形成新的 scheduler loop；
- 每轮分配要 bounded，不允许无界 while 把所有任务一次扫完；
- allocation 失败不能影响 Agent heartbeat；
- 仍保留现有 assignment generation / lease / node capability / GPU reservation fencing。

同时必须给 local Worker 增加 remote-task admission fence：

- 有 `task_node_connection_mode(task) == 'agent'` 或 portable `remote_execution` 的 task；
- 在没有 central assignment 时也不能被 local Worker claim。

否则即使补上 scheduler tick，仍存在 local Worker 与 allocation 的抢占竞态。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

至少增加一个真正的 production-shape 集成测试：

1. 创建在线 Agent node；
2. 创建一个需要 Agent 的 QUEUED task；
3. **测试代码不得手工调用 `assign_next()` / allocate-next**；
4. 启动真实 scheduler/Agent loop；
5. task 必须自动形成 ASSIGNED → CLAIMED → RUNNING；
6. remote Training 在 assignment 形成前不得被 local Worker claim。

---


### AUDIT-064 — 分页任务列表内部仍无界 hydrate 全部 QUEUED Durable Task，并对每个可见 queued task 重复扫描；active polling 将其放大为 O(page × total_queued) 热路径

**级别：中～高**  
**模块：Task Runtime Public Projection / Queue Position / AI Annotation / Video Tasks / Unified Task List / Training List / 1k-20k Performance**

**现象：**

当前多个任务列表 API 在对外只返回 50 / 100 条分页记录时，为了计算：

- `resource_queue_position`
- `resource_queue_position_exact`

会先调用：

`TaskRepository.queued_candidates()`

该函数不是 bounded page，也不是 aggregate/index query，而是：

```sql
SELECT * FROM tasks
 WHERE status='QUEUED'
 ORDER BY priority ASC, queue_rank DESC, created_at ASC, task_id ASC
```

随后直接：

`fetchall()`

并把**整个 Task Runtime 数据库中的全部 QUEUED task**转换成 Python `TaskRecord` tuple。

然后，对列表页里的每个可见 queued 非训练任务：

`task_to_public()`
→ `resource_queue_position()`
→ `_non_training_queue_position_exact()`

后者又会对这份全量 `queued_candidates` 做：

- compatible Worker capability 过滤；
- claimable candidate 全量 list comprehension；
- cross-resource 扫描；
- task_id position 扫描。

CPU Training 的 `training_queue_truth()` 在满足 exactness 条件时也会对相同全量候选做类似扫描。

所以对一个返回 `P` 条 queued task 的列表，内部复杂度接近：

`O(total_queued hydration + P × total_queued scan)`

而不是 API 表面上的 `O(P)`。

**真实调用链：**

统一任务列表：

`GET /api/v62/projects/{project_id}/tasks?limit<=100`

→ `repository.list(... limit=P)`（本身是 bounded cursor page）

→ `worker_runtime = WorkerInstanceService(...).list_runtime()`

→ **`queued_candidates = repository.queued_candidates()`（全库全部 QUEUED）**

→ 对 page.items 每条：

`task_to_public(... queued_candidates=queued_candidates)`

→ queued 非 Training：

`_non_training_queue_position_exact()`

→ `claimable = [candidate for candidate in candidates if _worker_can_claim(...)]`

→ 再做 cross-resource / position scan。

同样模式存在于：

- `GET /api/v60/.../annotation-tasks?limit=50`
- `GET /api/v33/.../video-tasks?limit=50`
- `GET /api/projects/{project_id}/jobs`
- 其它调用 `task_to_public(... repository)` 的详情/批量 projection。

**active polling 会持续放大：**

AI Annotation 当前真实 Poll Runtime：

`static/modules/auto-label-poll-runtime.js`

只要当前页面存在 active AI task：

`requestTasks()`
→ `GET /api/v60/.../annotation-tasks?limit=50`

默认每：

**1800 ms**

重新执行一次。

浏览器回归测试：

`tests/browser/auto-label-polling.spec.mjs`

也明确断言：

`auto-label-v60` PollRegistry delay = `1800`。

Video Tasks：

`PollRegistry.replaceVideo424Timer()`

active 时约每：

**2000 ms**

调用：

`refreshVideo424Delta()`
→ `GET /api/v33/.../video-tasks`

Training Jobs 在 active 且未走 realtime 时也是约 2 秒轮询。

因此：

“列表 API 页大小只有 50 / 100”

并不能限制服务器真实工作量。

例如项目/平台累计 20,000 个 QUEUED Durable Task 时：

AI 页面一次 50 条 refresh 至少会：

- hydrate 20,000 个 TaskRecord；
- 对可见 queued task 做多次 20,000 级 Python capability / resource scan；
- 约每 1.8 秒重复一次。

这会把一个 bounded UI page 变成持续高频的全队列扫描。

**为什么是 Bug / bounded truth 性能问题：**

这里不是“为了正确性必须返回完整 active truth”的合理全量读取。

队列顺序已经有更高效的 SQL owner：

`resource_queue_position(task_id)`

通过 resource-scoped `COUNT(*)` 计算位置。

问题只出在“证明 exactness”时，把整个 QUEUED task 集 hydrate 到 Python，再对每条页面记录重复扫描。

更重要的是：

`queued_candidates()` 没有 project_id / kind / worker capability / resource_key 范围，

所以一个项目的 50 条列表会读取：

**所有项目的全部 QUEUED Durable Task**。

这违反当前 1k / 10k / 20k 性能审计原则：

- bounded page 不能在内部退化为 full hydration；
- 高频 poll 不能每次全量扫描；
- 禁止 O(page × global queue) 热路径。

**影响：**

- 1k / 10k / 20k queued task 时任务中心、AI 标注页、视频切帧页响应显著变慢；
- active task polling 会持续重复触发 CPU / SQLite / Python 对象分配；
- 多项目情况下，一个项目的页面性能会被其他项目的 queued task 数量拖慢；
- Worker queue 越繁忙，查看进度页面反而越重；
- 可能导致 Web event loop / request worker 被 queue projection 占用，从而进一步拖慢心跳、轮询和操作响应；
- 现有 API 分页表面上看是 bounded，容易掩盖真实热路径。

**为什么现有 CI 没发现：**

当前 `tests/unit/task_runtime/test_public_projection.py` 主要验证：

- queue position 是否正确；
- CPU dedicated Worker 时 exact=true；
- 多 Worker / cross-resource 时 exact=false；
- running task 不显示 queue position。

`tests/api/test_unified_task_runtime.py` 也只验证少量任务的 position / promote truth。

没有 1k / 10k / 20k queued task 的性能合同，也没有断言：

“返回 50 条列表时，不得 hydrate 全部 queued rows”。

因此小数据测试全部通过。

**建议最小修复：**

不要删除 `resource_queue_position_exact`，也不要简单把 queued_candidates 加一个更大的 LIMIT。

正确方向是保持现有 TaskRepository / Scheduler owner，不新建第二套队列真相：

1. `resource_queue_position` 继续使用 SQL/indexed aggregate；
2. exactness proof 改成 SQL existence / count 查询，只查询当前 task 相关：
   - compatible Worker 数量；
   - 是否存在该 Worker 可 claim 的其它 resource_key；
   - 当前 task 在真实 claim order 中的位置；
3. 如果 exactness 无法低成本证明，继续 fail-closed 返回：
   `resource_queue_position_exact=false`，
   而不是为了展示一个 exact 标志扫描整个队列；
4. 列表 projection 不应调用无界 `queued_candidates()`；
5. 如果确实需要 candidate set，应提供受 project/kind/capability/resource 约束且可 cursor 的 query，而不是全库 `fetchall()`。

**回归测试建议：**

至少增加：

- 20,000 个 QUEUED tasks + list limit=50；
- 断言 projection 查询不会 SELECT / hydrate 全队列；
- 多项目 queue 不应影响单项目列表复杂度；
- AI 1.8s poll 路径在 20k queue 下仍只执行 bounded/indexed queries；
- exactness 仍保持原 fail-closed correctness 合同。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-065 — Durable Task 缺少统一 terminal retention / artifact GC owner；AI 候选、MaterialBatch selection、Video 原始文件与 frames、Deployment Test predictions 可长期无界占盘

**级别：中～高**  
**模块：Task Runtime / ArtifactStore / AI Annotation / MaterialBatch / Video Frames / Deployment Test / Storage Retention**

**现象：**

当前 Durable Task Runtime 有：

`ArtifactStore.delete_task(task_id)`

和：

`TaskRepository.delete_terminal(task_id)`

两个底层能力。

但是生产代码里真正把二者组成完整生命周期删除的，目前明确只有 Training 专用路径：

`_purge_terminal_training_job_record()`

→ `shared_task_repository().delete_terminal(... kind=TRAINING)`

→ `shared_task_artifacts().delete_task(job_id)`

→ `shutil.rmtree(job_dir)`

其它主要 Durable Task owner：

- AI Annotation；
- MaterialBatch / Cleaning / Integrity Audit / Label Remap；
- Video Frames；
- Deployment Test；

没有统一：

- terminal delete API；
- retention policy；
- background GC；
- 按 finished_at / age 的 prune；
- artifact archive/retire owner。

Worker startup、Worker supervisor、Task Runtime Scheduler、Web startup 中也没有发现 terminal task artifact GC。

因此 terminal Durable Task 会永久保留 task row / task artifact 目录，除非某个业务模块额外手工清理。

**这不是“小 JSON 累积”：**

1. **AI Annotation**

`CandidateStore`

直接写：

`task_runtime/artifacts/<task_id>/candidates/items.sqlite3`

其中持久化：

- 每张图的候选状态；
- boxes；
- item_json；
- review/commit metadata；
- manifest。

大批量 AI 标注任务会形成真实 SQLite 文件。

2. **MaterialBatch / Cleaning / Integrity / Label Remap**

创建时写：

`selection.sqlite3`

并冻结完整素材 selection。

1k / 10k / 20k 素材批处理会持续形成每任务独立 selection DB、checkpoint、result/audit artifacts。

3. **Video Frames**

创建任务时原始视频直接上传到：

`task_runtime/artifacts/<task_id>/inputs/<filename>`

Worker 又把抽帧中间结果写到：

`task_runtime/artifacts/<task_id>/frames/`

成功后：

`VideoFrameHandler.run()`

只写 `result.json` / checkpoint 并返回 `SUCCEEDED`。

没有删除：

- 原始上传视频；
- task-local frames 目录。

虽然最终正式素材已通过 StorageManager 写入 MaterialRepository 对应存储，但任务临时输入和抽帧副本仍保留。

4. **Deployment Test**

测试图片与结果图不是写在 ArtifactStore，而是：

`projects/<project_id>/predictions/<task_id>/input.*`

`projects/<project_id>/predictions/<task_id>/result.jpg`

Durable task 自身另有：

`task_runtime/artifacts/<task_id>/request.json`
及 log/result artifacts。

当前 API 只有：

- create；
- get；
- cancel；
- feedback evidence promotion；

没有 terminal delete / retention owner，因此 predictions 目录也会长期累积。

**为什么是 Bug / 技术债：**

当前 Durable Task 已经成为：

- Training；
- AI Annotation；
- Cleaning；
- Material Import；
- Video；
- Deployment Test；
- Integrity Audit；

等主链共同依赖的统一 Runtime owner。

但“任务执行 owner”已经统一，“任务终态数据保留 owner”却没有统一。

结果是：

`TaskRepository`

和：

`ArtifactStore`

生命周期不对称：

创建任务时统一创建 Durable truth + artifacts；

终态后除了 Training 外没有统一 retire contract。

长期运行时磁盘占用只增不减。

**影响：**

- AI 大批量标注会留下大量 candidate SQLite；
- 清洗 / Integrity / Remap 会留下 selection/result DB；
- 视频切帧会重复保留原视频 + frames + 正式素材副本；
- Deployment Test 高频测试会持续生成 predictions/<task_id>；
- 运行数月后 `/data/platform-data` 可被 terminal task artifacts 持续吃满；
- 磁盘满后会反向影响：
  - SQLite commit；
  - training artifact；
  - Material upload；
  - Remote staging；
  - log / checkpoint；
  - Worker heartbeat/恢复；
- 用户没有统一界面或后台机制清掉这些历史 artifacts。

**为什么不能简单“任务成功就删”：**

部分 terminal artifacts 仍有审计/恢复价值：

- AI review candidate；
- Material Integrity 审计结果；
- Deployment Test evidence；
- Video task result metadata；
- Training lineage。

所以正确方案不是每个 handler `finally: rmtree(...)`。

必须有明确 retention owner：

- 哪些 artifact 要长期留；
- 哪些只用于执行临时态；
- terminal 后立即可删哪些；
- 哪些按 N 天保留；
- 哪些被版本/反馈/审计引用时必须 pin；
- 删除 task row 前如何保证下游引用已解除。

**建议最小修复：**

不要在每个模块新增一套 GC。

复用现有：

`TaskRepository`
+
`ArtifactStore`

增加单一 Task Retention owner，例如：

- terminal task retention policy；
- bounded GC scan；
- pinned/referenced task protection；
- artifact-size accounting；
- project/global retention quota。

最低限度应做到：

1. terminal task 按 kind 定义 retention：
   - transient execution artifacts；
   - audit/evidence artifacts；
   - pinned lineage artifacts；
2. Video 成功后立即删除可重建的：
   - 原始 task-local source video；
   - task-local frames；
   前提是正式 MaterialRepository 已 commit 且 result evidence 已校验；
3. Deployment Test：
   - feedback evidence 已 promotion 后，predictions 可进入 shorter retention；
   - 未 promotion 的历史测试按 age GC；
4. AI Candidate：
   - AWAITING_CONFIRMATION 必须 pin；
   - SUCCEEDED/CANCELLED/FAILED terminal 后按 retention；
5. MaterialBatch：
   - active/retryable task 必须 pin；
   - terminal 且无后续审计引用后按 retention；
6. GC 必须 bounded / cursor 化，不能一次扫全目录；
7. task row / artifact / auxiliary directory 必须原子或 journal 化 retirement，避免“删 row 留文件”或“删文件留可点击记录”。

**回归测试建议：**

至少覆盖：

- Video SUCCEEDED 后 transient input/frames 能按策略 retire；
- AI AWAITING_CONFIRMATION 不得被 GC；
- terminal AI task 超过 retention 后 candidate DB 可清；
- MaterialBatch retry window 内不得被清；
- Deployment Test promoted evidence 不被错误删除；
- 10k terminal tasks GC 使用 bounded page，不 full-scan；
- Training 现有专用删除语义保持不回退。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-066 — 训练任务页 GET 在返回 bounded history 前会多次全量扫描所有 jobs/*/job.json；轮询下形成与累计历史线性增长的热路径

**级别：中～高**  
**模块：Training Task List / sync_jobs_index / Legacy Queue Dispatch / Polling / Performance**

**现象：**

当前 canonical 训练任务页真实数据源：

`GET /api/projects/{project_id}/jobs`

看起来最终只保留：

- 全部 active Training；
- 最近 50 条 terminal history。

这个 bounded 输出由：

`_training_job_index_rows(..., history_limit=50)`

保证。

但真正请求链在“截断前”做了多次全量历史扫描：

```
list_jobs(project_id)
  -> sync_jobs_index(project_id)
  -> _v48_dispatch_training_queues(project_id)
  -> sync_jobs_index(project_id)
  -> read jobs/index.json
```

**第一次 `sync_jobs_index()`：**

直接遍历：

`jobs_dir.iterdir()`

对项目下每个任务目录：

`jobs/<task_id>/job.json`

逐个：

- read_json；
- enrich_job_runtime；
- durable task lookup；
- runtime/public truth projection。

扫描完**全部历史 job**之后，才：

`_training_job_index_rows(jobs)`

把 terminal history 截到 50。

**中间 `_v48_dispatch_training_queues()`：**

又遍历：

`_v48_all_job_files(project_id)`

即项目所有 job.json。

对每个 job：

- read_json；
- 调 `_durable_training_task(...)` 判断是不是 modern Durable task；
- modern Durable task 虽然随后 `continue`，但文件和 TaskRepository lookup 已发生；
- legacy queued/running job 继续参与 dispatch。

**第二次 `sync_jobs_index()`：**

dispatch 后又重复执行一次完整 job 目录扫描与 enrich。

所以一次：

`GET /jobs`

最坏至少会对全部 Training job history 做：

- 两次完整 filesystem directory scan；
- 两轮 job.json parse；
- 多轮 TaskRepository get / public projection；
- 加上一轮 legacy dispatch 全量扫描。

最终却只输出：

“全部 active + 最近 50 terminal”。

**前端会周期性触发这个路径：**

`TrainingTaskRuntime.refresh()`

直接：

`fetch('/api/projects/<pid>/jobs')`

当前 PollRegistry：

- realtime stream coverage 完整时，仍会做较低频 reconcile；
- realtime coverage 不完整 / SSE 异常时，fallback 约每 **2 秒**刷新一次；
- 手动刷新、页面进入、mutation 后也会触发 refresh。

因此累计历史 job 数量越多：

`GET /jobs`

耗时越高。

尤其当项目累计达到：

1k / 10k / 20k Training history

时，页面每次刷新仍然扫描这些历史目录，即使 UI 实际只需要：

- active task；
- 最近 50 terminal。

**为什么是 Bug / bounded truth 性能问题：**

`_training_job_index_rows(history_limit=50)`

本身设计是正确的：

它明确说明：

“Retain every live task plus a bounded terminal history”。

问题在于：

bounded projection 只发生在**最后一步**。

前面的 truth hydration 仍是无界的。

这和 AUDIT-064 不同：

- AUDIT-064：TaskRepository public projection 为 queue exactness 无界 hydrate 全部 QUEUED task；
- AUDIT-066：Training jobs REST 每次从 filesystem 无界读取全部历史 job.json，再构造最近窗口。

两条路径会叠加：

`list_jobs()`
→ 全量 job filesystem scan
+
`repository.queued_candidates()`
→ 全量 queued TaskRecord hydration。

**影响：**

- 训练历史越多，训练任务页首开越慢；
- active polling 会持续产生大量磁盘 I/O / JSON parse；
- SSD/HDD 较慢、NFS/挂载盘场景更明显；
- 10k/20k job 目录时，Web 请求线程可能长期被目录遍历占用；
- API latency 增高会拖慢：
  - 页面状态刷新；
  - pause/stop 后刷新；
  - recovery hydration；
  - 其它共享 Web 请求；
- filesystem 上大量小文件还会形成 inode / metadata I/O 压力。

**现有测试为什么没发现：**

当前：

`tests/browser/training-task-performance.spec.mjs`

主要验证：

- 一次手动 refresh 只产生一个 `GET /jobs`；
- 页面 shell / row 不被不必要重建；
- mutation 后 refresh 次数正确。

它把 `GET /jobs` 本身 mock 掉了。

所以“浏览器只发 1 次请求”是绿色的，但服务器这一请求内部可能做 20k history scan。

`test_training_startup_performance_contract.py`

关注训练启动性能，不覆盖 task-list history hydration。

目前没有：

- 1k / 10k / 20k job history；
- `GET /jobs` bounded filesystem work；
- query count / file read count；

的后端规模合同。

**建议最小修复：**

不要新增第二套 Training task owner。

应继续以：

- TaskRepository 作为现代 Durable task truth；
- job.json 作为 worker/job compatibility/detail artifact；

但训练任务列表不能每次重建全量 index。

建议最小方向：

1. modern Durable Training：
   - active / recent terminal 直接由 TaskRepository cursor/indexed query 获取；
   - 只对最终要展示的 task ids hydrate 对应 job.json；
2. legacy job：
   - 保留一个明确 bounded compatibility index；
   - 不在每个 GET 中重新 glob 全历史；
3. `sync_jobs_index()` 改为 mutation-time / worker-finalization-time 增量维护；
4. 若仍需启动修复扫描：
   - 只在 startup/recovery owner 做；
   - bounded/cursor；
   - 不放进高频 GET；
5. `_v48_dispatch_training_queues()` 只扫描真正 legacy queued/running candidates，不应遍历所有 modern terminal history；
6. 保留现有“全部 active + 最近 50 terminal”UI语义，不要通过扩大 history limit 解决。

**回归测试建议：**

至少增加：

- 20,000 terminal training job dirs + 3 active；
- GET /jobs 只 hydrate 3 active + bounded recent terminal；
- file read count / repository query count 有明确上限；
- active polling 不触发全量 filesystem scan；
- legacy queued job 仍能正常 dispatch；
- modern Durable jobs 不再经过 legacy全历史 dispatch scan；
- 现有前端单请求/稳定 DOM 合同保持。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-067 — Storage Import focused poller 切换到第二个任务时未 handoff 旧 active task；UploadTaskCenter 保留 stale pollOwner，旧任务可停止所有前端刷新并卡在待确认

**级别：高**  
**模块：Storage Import / PollRegistry / UploadTaskCenter / MATERIAL_IMPORT / Multi-task lifecycle**

**现象：**

当前 v61 Storage Import 有两层前端 owner：

1. modal 内 focused owner：

`StorageImportProgressRuntime`

2. modal 关闭后的后台 owner：

`UploadTaskCenterRuntime`

正常 handoff 设计是：

focused runtime 跟踪任务时：

`pollOwner='storage-import-progress'`

关闭 focused modal：

`stop({handoff:true})`

→ 再次 `publishTaskCenter(last, '')`

→ UploadTaskCenter 行的 `pollOwner` 清空

→ Task Center 接管 durable polling。

这个单任务场景是正确的。

但切换到第二个 Storage Import 时：

`StorageImportProgressRuntime.track(taskId)`

第一句是：

`stop({handoff:false})`

然后才把：

`trackedTaskId = newTaskId`

并开始新任务 polling。

如果旧任务仍 active：

- 旧任务此前已被 `publishTaskCenter()` 写入 UploadTaskCenter；
- 其 row 带：
  `pollOwner='storage-import-progress'`；
- `stop({handoff:false})` 只清 focused PollRegistry / trackedTaskId；
- 不会把旧 row 重新 upsert 为 `pollOwner=''`；
- focused runtime 随后转而跟踪新 task；
- 旧 task 的 Task Center row 仍错误声明 focused owner 正在负责。

而 UploadTaskCenter 自己的 polling 明确跳过：

`if (!row?.serverUrl || row?.pollOwner || !isUploadTaskActive(row)) return row`

以及：

`rows.filter(row => isUploadTaskActive(row) && row.serverUrl && !row.pollOwner)`

因此旧 task：

**focused owner 已经离开，background owner 又因为 stale pollOwner 不接管。**

形成 owner vacuum。

**真实可达链：**

当前 Storage Import modal 的 scan / server ZIP / object storage / local directory 创建按钮，在任务 active 时没有统一 single-flight guard。

用户可以：

1. 创建 Storage Import A；
2. A 仍 QUEUED / RUNNING；
3. 再次创建 Storage Import B；
4. `pollTask(B)`;
5. `StorageImportProgressRuntime.track(B)`;
6. 内部：
   `stop({handoff:false})`;
7. A focused polling 被停掉；
8. A Task Center row 仍保留：
   `pollOwner='storage-import-progress'`;
9. UploadTaskCenter 不会 poll A；
10. B 正常成为当前 focused task。

A 的 Durable Worker 仍会继续执行，但浏览器不再自动读取其状态。

**为什么待确认任务尤其危险：**

Storage Import scan 完成后可以进入：

`AWAITING_CONFIRMATION`

并要求用户显式：

`POST /api/v61/projects/{project_id}/storage-imports/{task_id}/confirm`

当前 UI 的确认按钮只由：

`renderStorageImportTask61(task)`

渲染：

`确认建立索引`

所以用户必须重新进入对应 task 的 detail/review 才能：

- 完成标签映射；
- 接受质量问题；
- 点击确认建立索引。

但当前 UploadTaskCenter：

`renderUploadTaskCenterRow()`

只有：

`kind === 'zip'`

才：

- 加 `utc-reopenable`；
- role=button；
- tabindex；
- click handler；
- 调 `ZipImportRuntime.openTask(id)`。

`kind='storage-import'`

没有 reopen handler。

与此同时 Storage Import modal 自己只用：

`localStorage taskKey -> 一个 task_id`

保存最近一次任务。

新任务 B 创建后：

`saveTask(B)`

会覆盖旧任务 A 的恢复 pointer。

所以当 A 后续进入 AWAITING_CONFIRMATION：

- focused runtime 不跟；
- Task Center 不跟；
- Task Center 不能点击重开；
- localStorage 已只记 B；
- 后端又没有项目级 `GET /storage-imports` list endpoint。

A 仍存在于 TaskRepository，但用户正常 UI 已无法发现/确认它。

**为什么不是 AUDIT-005：**

AUDIT-005 是：

多层 Modal 关闭上层时错误执行 Storage Import cleanup，导致底层 poll 被误停。

AUDIT-067 是另一条 owner handoff：

**同一个 Storage Import focused runtime 从 task A 切换到 task B 时，旧 task A 没有交还给 UploadTaskCenter。**

即使修完 modal scope，AUDIT-067 仍然存在。

**额外放大器：**

UploadTaskCenter 只持久化：

`MAX_ROWS = 20`

并在：

`upsert()`

中：

`rows = rows.slice(0, MAX_ROWS)`

所以大量并发/近期上传任务时，老 Storage Import 还可能被本地 task center history 直接挤掉。

这不是本问题成立的前提，但会进一步降低恢复能力。

**影响：**

- 多个并发 Storage Import 时旧任务停止前端自动刷新；
- 用户看到 B 正常运行，却不知道 A 已完成/失败/待确认；
- A 进入 AWAITING_CONFIRMATION 后无法从任务中心点击进入；
- 已扫描的大批素材可能长期卡在“等待确认”，无法建立正式索引；
- 用户可能误以为任务丢失，重复创建新的 Import；
- 重复扫描、远端 I/O、对象存储读取被放大；
- Durable task truth 与前端 owner/poller truth 分裂。

**现有测试为什么没发现：**

`storage-import-progress.test.mjs`

覆盖：

- 单 task track；
- PollRegistry one-shot；
- stop() 默认 handoff 给 task center；
- lightweight progress；
- terminal detail render。

但没有覆盖：

`track(A active) -> track(B active)`

以及旧 A 的：

`pollOwner`

是否被清空。

测试甚至明确断言源码存在：

`stop({handoff:false})`

但没有验证它只应该用于“同 task 重绑定”，不能吞掉不同 task 的 owner handoff。

`upload-task-center.test.mjs`

也只验证：

- row.pollOwner 时 task center yield；
- ZIP reopen；
- terminal cleanup；

没有覆盖 Storage Import 多任务 owner transfer。

**建议最小修复：**

不要新增第三个 poller。

继续保留：

- StorageImportProgressRuntime = focused owner；
- UploadTaskCenterRuntime = background owner；
- PollRegistry = timer owner。

只修 owner transfer：

1. `track(newTaskId)` 前：
   - 若当前 `trackedTaskId` 非空；
   - 且与 newTaskId 不同；
   - 且 currentTask 仍 active；
   - 必须 `stop({handoff:true})`；
2. 只有“同一个 task 重新绑定/重绘”才能：
   `stop({handoff:false})`；
3. UploadTaskCenter 为 `kind='storage-import'` 增加 reopen action：
   - 调 canonical storage import modal/detail；
   - 从 task id GET current Durable truth；
   - AWAITING_CONFIRMATION 时恢复映射/质量确认 UI；
4. Storage Import 后端增加 project-scoped cursor list：
   - 只列 MATERIAL_IMPORT；
   - active 全可发现；
   - terminal history bounded/cursor；
   - 不再只依赖 localStorage 单 task pointer；
5. Task Center MAX_ROWS 不能让 active durable task 被 terminal/recent history 挤掉：
   - active 全保留；
   - terminal history bounded。

**回归测试建议：**

至少增加：

- track A(active) → track B(active)；
- A 必须被 upsert 成 `pollOwner=''`；
- Task Center 接管 A polling；
- B 仍由 focused runtime poll；
- A 进入 AWAITING_CONFIRMATION 后 Task Center 可点击重开；
- localStorage 只记录 B 时仍能从后端 list 找到 A；
- 21+ task center rows 时 active storage-import 不被挤掉；
- modal close / project switch 仍保持单一 PollRegistry owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-068 — Training SSE 未复用 canonical training_queue_truth；同一 QUEUED 任务可在 HTTP 中显示 WAITING_RESOURCE、随后被实时流覆盖回 QUEUED

**级别：中～高**  
**模块：Training Task / SSE / Queue Truth / Frontend Runtime / 前后端一致性**

**现象：**

当前训练任务页同时存在两条读取链：

1. canonical HTTP 列表：

`GET /api/projects/{project_id}/jobs`

2. v64 实时流：

`GET /api/v64/projects/{project_id}/training-events`

HTTP 列表在 `enrich_job_runtime()` 中会对 Durable Training task 调用：

`task_to_public(durable, repository)`

并且当任务仍为 QUEUED 时继续调用：

`training_queue_truth(durable, repository, ...)`

所以当：

- 没有在线 Worker；
- 在线 Worker 不支持所需 capability；
- remote target 的 Worker 路由尚未建立；
- 或任务明确处于 resource_waiting；

HTTP 会把该任务投影为：

`status = WAITING_RESOURCE`

并补齐：

- `resource_wait_reason`
- `resource_queue_position`
- `resource_pool_key`
- `resource_pool_label`

这是当前 canonical Training queue presentation truth。

但 SSE 的 `_training_event_row()` 只做：

`runtime = task_to_public(task)`

没有传 repository，也没有调用 `training_queue_truth()`。

因此对于 persisted status 仍为 QUEUED、stage 又没有被持久化为 `resource_waiting` 的任务，SSE 会发：

`status = QUEUED`

即使同一个任务刚刚在 HTTP 列表里被正确显示成：

`WAITING_RESOURCE`。

**真实前端覆盖链：**

`training-progress-stream.js`

收到 `training.task` 后：

`applyUpdate(update)`

会直接写：

`task_status = String(update.status ...).toUpperCase()`

因此一个 HTTP 已 hydrate 成：

- `task_status = WAITING_RESOURCE`
- UI = “等待资源”

的任务，下一条 SSE 只要携带：

- `status = QUEUED`

就会把前端 `task_status` 覆盖回 QUEUED。

`resource_wait_reason` 因为前端用了 nullish fallback，可能仍保留旧 reason，于是同一行甚至可能形成：

- 状态：排队中；
- 原因：当前没有在线 Worker / 指定远程服务器路由尚未建立；

这种自相矛盾的组合。

同时 `training.ready` 的 coverage 只按 task_id 判断。只要 active task id 都在 SSE 返回的前 100 内，PollRegistry 会认为 realtime coverage 完整并降低 HTTP fallback 频率，所以这个错误状态不一定会立即被 canonical GET 修回来。

**为什么是前后端不一致 / duplicate projection owner：**

HTTP 和 SSE 都声称在输出“canonical training display truth”，但两者的 queue readiness projection 不同：

- HTTP：TaskRepository + Worker runtime + `training_queue_truth()`
- SSE：仅 `task_to_public(task)`

也就是说同一个 Training task 有两个不同的 queue presentation owner。

尤其 AUDIT-063 已经确认 remote scheduler 路由存在生产驱动缺口；在这种情况下，remote QUEUED task 更容易长期处于“应该显示 WAITING_RESOURCE”的状态，因此这里不是纯展示边角问题。

**影响：**

- 训练任务页“排队中 / 等待资源”状态可来回跳；
- remote training 可从“等待远程路由”被实时流改回普通排队；
- 没有在线 Worker 时页面可能误导用户为正常队列等待；
- resource_wait_reason 与 task_status 可互相矛盾；
- 排序会变化：`visibleTrainingJobs()` 对 waiting 和 queued 使用不同 rank；
- 停止/批量操作虽然目前都允许 queued/waiting，但运维判断、资源排障和任务优先级观察会失真；
- HTTP 与 SSE 之间缺乏单一 queue truth owner，后续继续扩字段时容易再次漂移。

**现有测试为什么没发现：**

`tests/frontend/training-progress-stream.test.mjs`

当前只覆盖：

- RUNNING progress update；
- unknown task reconcile；
- terminal reconcile；
- stream error fallback；
- display revision 防旧数据覆盖。

该测试中没有：

- WAITING_RESOURCE；
- resource_wait_reason；
- QUEUED → WAITING_RESOURCE queue projection；

因此没有覆盖：

`HTTP WAITING_RESOURCE row -> SSE QUEUED event -> UI must remain canonical waiting truth`

的跨读取链合同。

后端也缺少测试断言：

`_training_event_row()`

对 QUEUED Training 必须与 `enrich_job_runtime()` 使用相同的 `training_queue_truth()`。

**建议最小修复：**

不要在浏览器再实现一份 Worker readiness 判定，也不要新增第三套 queue projection。

应让 SSE 复用 canonical backend truth：

- `_training_event_rows()` 已经持有 repository；
- 对每个 Training task 构造 event row 时传入 repository / worker_runtime / bounded queued candidate context；
- QUEUED Training 与 HTTP 一样调用 `training_queue_truth()`；
- SSE 与 HTTP 共用同一 projection helper；
- 不要通过前端“如果已有 WAITING_RESOURCE 就拒绝 QUEUED”来掩盖后端漂移，否则真实 queue 状态变化也可能无法更新。

同时应避免为了修这个问题在 750ms SSE 循环里重新引入 AUDIT-064 的全量 queued hydration；Worker runtime / queue context 应按一次 event-loop iteration bounded/shared 复用，而不是每 task N+1。

**回归测试建议：**

至少覆盖：

- 无在线 Worker：HTTP 与 SSE 都返回 WAITING_RESOURCE；
- remote resource key：HTTP 与 SSE 都保留相同 wait reason；
- capability 不匹配：两条读取链一致；
- Worker 恢复可用后 WAITING_RESOURCE → QUEUED/RUNNING 正常转换；
- 前端收到 SSE 后不会把 canonical waiting row错误覆盖回 queued；
- 100 个 active stream 周期内 Worker runtime / queue hydration 不出现 per-task N+1。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-069 — 打开 canonical AI 自动标注创建弹窗会无条件全量 hydrate 项目素材；20k 项目连“只标刚上传的一小批”也先走旧 /images 全量路径

**级别：中～高**  
**模块：AI Annotation / Material Pagination / Dataset Scale / 1k-20k Performance**

**现象：**

当前数据集主页面已经正确切到 v61 server-side pagination：

`GET /api/v61/projects/{project_id}/materials?limit=48&cursor=...`

v53 bootstrap 也只返回 material/annotation summary，不再把全项目素材塞进首屏。

训练素材 picker 也已经由 `TrainingMaterialPickerRuntime` 通过：

`GET /api/v62/projects/{project_id}/training-materials`

做 server-side cursor pagination。

但是 canonical AI 自动标注创建入口仍明确绕回旧全量素材接口：

```js
window.createAiLabel429=async function createAiLabelCanonical429(opts={}){
  await window.MaterialPaginationRuntime61?.ensureFullPool?.();
  const result=window.createAiLabelCore429?.(opts);
  ...
}
```

`ensureFullPool61()`
→ `loadFullPool61()`
→ `GET /api/projects/{project_id}/images`

这个旧接口不是分页接口。

**旧 /images 的真实成本：**

`list_images(project_id)` 会：

1. `load_images(project_id)` 全量读取项目 Material；
2. 若任一图片缺 annotation_summary_at，触发历史 annotation index 调度；
3. 遍历全部图片并执行 `public_material(project_id, img)`；
4. 补 box_count / annotated / labels / annotation_preview / split / processing_status；
5. 缺 `size_bytes` 的图片还会通过 StorageManager/provider 做对象 `stat()`；
6. 汇总 size_patches 后可能回写 MaterialStore；
7. 最终把完整 public material 数组序列化并发送到浏览器。

所以 20k 素材项目打开 AI 创建弹窗时，会把 20k material rows 全量 hydrate + serialize + network transfer + browser parse。

**更严重的是：即使调用者已经明确给了小范围 IDs，也照样全量读取。**

例如上传完成后的快捷动作会调用：

`createAiLabel427({image_ids: ...})`

而 `createAiLabel427` 已指向 canonical `createAiLabel429`。

canonical wrapper 在查看 `opts.image_ids` 之前就无条件执行：

`ensureFullPool()`。

因此：

“刚上传 100 张，只对这 100 张做 AI 标注”

也会先加载项目全部 20k 素材。

**为什么当前代码这样做：**

旧 `createAiLabelCore429(opts)` 默认范围依赖：

```js
const ids=opts.image_ids?.length
  ? opts.image_ids
  : (state.images||[]).filter(x=>!x.annotated).map(x=>x.id)
```

参考素材 UI `refs429()` 也直接从 `state.images` 筛已标注图片。

分页后为了不把“当前 48 张”误当全项目，canonical wrapper 选择了“打开弹窗前恢复 full pool”。

这保住了正确性，但把 Material Pagination 的性能收益在 AI 主流程重新抵消。

**为什么是 Bug / 技术债：**

当前平台已经明确以 1k / 10k / 20k 作为素材规模合同。

`MaterialPaginationRuntime` 也明确让 canonical 页面导航不全量 hydrate。

AI Create 是高频主流程，不能仅因为全量加载发生在“用户点击创建”边界，就允许每次创建前做 `O(total_materials)` hydration。

Durable AI Task 最终真正需要的是：

- target image IDs；
- reference image IDs；
- labels；
- frozen model/prompt config。

浏览器不需要持有全项目完整 Material public rows。

**现有后端已经有更轻的能力：**

v61 已提供：

`GET /api/v61/projects/{project_id}/materials/ids`

支持 cursor / limit / query / storage source / processing status / labels / annotated。

参考素材也可以通过：

`GET /api/v61/.../materials?annotated=true&limit=...`

分页读取。

因此没有必要退回旧 `/images` 全量 API。

**影响：**

- 10k/20k 项目打开“创建 AI 标注任务”明显变慢；
- 浏览器内存瞬时增加；
- Web 端承担全量 Material projection；
- JSON 序列化与网络响应显著变大；
- 对象存储历史素材缺 size_bytes 时还可能触发大量 stat；
- “上传完成 → 一键 AI 标注”这种本应 O(batch) 的快捷动作也被项目总规模拖慢；
- 10 秒 fullPool cache 只能降低短时间重复打开，不能消除首次/过期后的全量成本；
- 创建任务前的同步等待与 Durable Worker 后台化目标相违背。

**现有测试为什么没发现：**

`tests/frontend/material-pagination-runtime.test.mjs` 当前只验证：

- canonical 页面 navigation 不 full hydration；
- `ensureFullPool` lazy；
- 10 秒 cache；
- single-flight；
- AI wrapper 中存在 `ensureFullPool()`。

也就是说现有测试把“延迟到用户动作再全量 hydrate”当作当前合同，却没有 10k/20k AI-create 性能约束，更没有要求：

“传入明确 image_ids 时不得读取全项目”。

**建议最小修复：**

不要改 CandidateStore / Durable AI 主链。

只移除 AI Create 对 full `state.images` 的依赖：

1. **显式 `opts.image_ids` 场景**
   - 直接使用这些 ids；
   - 不得调用 `ensureFullPool()`；
   - 需要摘要时只 batch get 这批 metadata。

2. **默认“全部未标注素材”场景**
   - 使用 v61 `/materials/ids?annotated=false` cursor 读取 ID-only truth；
   - 或由后端 selection owner 冻结 scope，避免 20k IDs 全量塞进浏览器。

3. **参考素材**
   - 独立 server-side page；
   - `annotated=true` + query + labels；
   - 首屏只取固定 40/60 张；
   - 搜索/筛选走 server query；
   - 不依赖全项目 `state.images`。

4. `ensureFullPool()`
   - 继续作为 compatibility escape hatch；
   - AI Create 不再调用。

**回归测试建议：**

至少增加：

- 20,000 materials 打开 AI Create，不请求旧 `/api/projects/{id}/images`；
- reference 首屏 metadata 有固定上限；
- 默认全未标注 scope 只走 ID cursor / server selection；
- `createAiLabel429({image_ids:[100 ids]})` 不读取另外 19,900 rows；
- “上传完成 → AI 标注”保持 O(batch)；
- Durable request 的 image selection truth 仍完整、可追溯。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-070 — Agent Training 在 execution start 后释放 GPU assignment reservation；RUNNING 训练不再占用 selected GPU，第二个 exclusive 任务可再次被分配到同一张卡

**级别：高**  
**模块：Central Scheduler / Agent Training / GPU Reservation / exclusive policy / Resource Truth**

**现象：**

Central Scheduler 在给 Training 分配节点时，会通过：

`_assigned_gpu_ids(database, node_id)`

排除已经被占用的 GPU。

但该函数只读取：

`task_node_assignments.state IN ('ASSIGNED','CLAIMED')`

里的 `resolved_execution_config.selected_gpu / selected_device`。

Agent 真正调用：

`AgentExecutionService.start_execution()`

完成 `QUEUED -> RUNNING` 后，又会在同一个事务中把当前 assignment 改成：

`state='RELEASED'`

并记录：

`release_reason='execution_started'`

从这一刻开始：

- Task 仍然是 RUNNING；
- Agent Training 仍然真实占用此前选定的 GPU；
- 但该 GPU 已经从 `_assigned_gpu_ids()` 的 reservation truth 中消失。

`_node_active_work_count()` 虽然会把 RUNNING Agent task 计入节点 busy count，但它只影响节点评分，不会告诉 `_selected_gpu()` “哪一张 GPU 已被运行中的训练占用”。

因此后续 `assign_next()` 对同一节点再次执行：

`_selected_gpu(node, assigned_gpu_ids=...)`

时，运行中任务所使用的 `cuda:N` 不在 excluded set 里。

**真实危险窗口：**

单 GPU Agent 节点：

1. Training A 被分配到 `cuda:0`；
2. Agent claim + start；
3. A 进入 RUNNING；
4. assignment A 立刻 RELEASED；
5. heartbeat 仍可能报告 `cuda:0` free VRAM >= 10% 且 utilization < 85%；
6. Training B 进入 allocator；
7. `_assigned_gpu_ids()` 返回空集；
8. `_gpu_is_training_candidate()` 仍认为 `cuda:0` 可用；
9. B 再次被分配到 `cuda:0`。

这不是纯理论窗口。GPU 利用率在：

- 数据加载；
- epoch 间隙；
- validation；
- CPU / I/O 等待；

都可能低于当前 85% 阈值；显存也完全可能保留超过 10% 空闲。

Telemetry 只能做 capacity / health signal，不能替代 exclusive reservation identity。

**与当前 GPU policy 的冲突：**

Agent Training 只允许：

- `auto`
- `exclusive`

并明确拒绝 shared。

本地 Worker 的 `GPUResourceManager` 会通过 `gpu_reservations` 对整个 RUNNING lease 保存 reservation，且 exclusive 会阻止同卡并发。

但 remote / Agent Training 的 `resource_key=training:remote:...` 会绕过本地 GPUResourceManager，GPU 独占责任实际落在 Central Scheduler。

当前 Central Scheduler 的 reservation 只活到 execution start，因此 Agent 路径与本地路径的 exclusive 合同并不一致。

**影响：**

- 两个 remote Training 可被安排到同一物理 GPU；
- exclusive 语义失效；
- VRAM OOM / CUDA allocation failure；
- 后启动任务可能挤占先运行任务资源；
- AUTO batch/workers/cache 是按错误的并发证据计算，可能出现资源决议与真实运行态不一致；
- `concurrent_reservations` 只统计 node active 数量，不能修复具体 GPU identity 冲突；
- 双 GPU 节点也可能重复选择正在运行的优质 GPU，而不是空闲的另一张卡；
- 训练速度、稳定性和 RESOURCE_RUNTIME_MISMATCH 排障都会受到干扰。

**为什么现有测试没发现：**

`tests/unit/test_task_node_assignments.py` 已覆盖：

- 两个仍处于 assignment 阶段的任务不能占同一 GPU；
- 指定 GPU 已被 active assignment 占用时继续排队；
- 外部 GPU utilization 过高时不分配；
- 多 GPU best-GPU 选择。

但这些测试都没有覆盖：

`assignment -> Agent start_execution -> assignment RELEASED + task RUNNING -> 再 assign 第二个 Training`

所以只证明了“启动前 reservation”，没有证明“运行期 reservation”。

`tests/unit/test_node_agent_training_runtime.py` 也验证了 selected GPU identity 和 exclusive 参数会传入 Agent，但没有把它与第二个 Central Scheduler assignment 串起来。

**建议最小修复：**

不要新增另一套 GPU scheduler。

应让 canonical Central Scheduler 的 GPU reservation identity 覆盖完整执行生命周期：

- ASSIGNED / CLAIMED 阶段继续使用当前 assignment snapshot；
- RUNNING / CANCEL_REQUESTED 的 Agent Training 也必须被 `_assigned_gpu_ids()` 纳入；
- 运行期 GPU identity 必须按 task + execution_generation 绑定，不能仅凭最新 heartbeat 猜；
- terminal / fenced generation 后再释放对应 GPU reservation；
- `exclusive` 必须硬阻止同一物理 GPU UUID / selected device 被第二个训练占用；
- multi-GPU 节点应允许第二个任务选择真正未占用的另一张卡；
- 不要把 utilization 阈值当作 exclusive ownership 替代品。

可以复用已经冻结在 assignment / Agent execution resource-resolution 中的 GPU UUID、device 与 generation，避免再造第二个 owner。

**回归测试建议：**

至少增加：

- 单 GPU：A start_execution 后，B 仍不得被分配到同一 GPU；
- 双 GPU：A 在 cuda:0 RUNNING 时，B 必须选择 cuda:1；
- A terminal 后，cuda:0 可重新分配；
- A CANCEL_REQUESTED 期间仍保持 reservation；
- stale/fenced generation 不得永久占卡；
- heartbeat utilization 很低、free VRAM 很高时，exclusive reservation 仍然生效；
- auto/exclusive 两种当前允许策略都不得隐式退化为 shared。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-071 — 当前“地址 / URL 读取导入”仍由 v36 daemon thread 直接写素材；绕过 canonical MATERIAL_IMPORT，进程重启可留下永久 running 与部分入库

**级别：高**  
**模块：Material Import / Source Import / Durable Task / Runtime Owner / Crash Consistency**

**现象：**

当前前端最终生效的 `window.importData` 只有一处定义，其中“地址读取”页签仍直接调用：

`POST /api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/jobs`

并由独立 PollRegistry：

`source-import-v36`

每 1.8 秒轮询 v36 JSON job。

这不是已经退役的兼容代码。

后端 `v36_start_source_import_job()` 创建的也不是 Durable Task，而只是：

`source_import_tasks/<job_id>.json`

随后直接启动：

`threading.Thread(target=_v36_run_source_import, ..., daemon=True)`

整个 v36 source-import 区段没有：

- `TaskRecord`
- `TaskKind.MATERIAL_IMPORT`
- Durable Task repository
- lease / generation fencing
- cancel
- retry
- crash recovery

worker 内则直接：

- 下载 / 解压来源；
- `add_image_record()` 正式写素材；
- `material_store(project_id).patch(...)` 修改 split；
- 最后才把独立 JSON job 改为 done。

**真实 crash-consistency 问题：**

如果进程在导入 N 张中的第 K 张后退出：

- 前 K 张已经正式进入素材库；
- daemon thread 消失；
- v36 job 仍可能永久保持 `running`；
- startup 没有恢复扫描；
- GET job list 也不会像 Durable Worker 一样 reclaim / retry；
- 用户没有 stop / cancel / resume 操作；
- 再次点击导入会创建第二个独立线程，造成重复执行风险。

这与平台已经收口的 canonical MATERIAL_IMPORT 生命周期不同，也形成了第二套 Material Import execution owner。

**为什么 AUDIT-026 不能覆盖：**

AUDIT-026 是 v42 Source Collection：

- source scheduler / collect run；
- 另一套 collection_runs 历史；
- 另一条定时采集链。

本条是当前数据集导入弹窗直接暴露给用户的 **v36 地址 / URL 导入**，入口、job store、worker 和产品交互均独立存在，因此是另一条真实旁路。

**影响：**

- 服务重启可留下永久 running；
- 部分素材已入库但任务显示未完成；
- 用户重试无法判断哪些素材已提交；
- 同一导入可能重复执行；
- 无统一取消语义；
- 无 Worker / Agent capability、资源调度与 execution generation；
- Material Import 的监控、审计、任务中心和 retention 不能覆盖这条链；
- 后续再修导入性能 / 幂等时必须维护两套 owner。

**现有前端为何仍可触发：**

`static/app.js` 中当前 `window.importData` 会渲染：

- “上传压缩包”
- “地址读取”

“地址读取”的“开始导入”直接绑定 `startSourceImportV36()`，后者 POST v36 endpoint。

代码中没有后续第二个 `window.importData=` 覆盖它。

**建议最小修复：**

不要再造第三套 Source Import runtime。

将 v36 当前 UI 的“地址 / URL 读取”提交统一进入现有 canonical MATERIAL_IMPORT / Material Import owner：

- source location 作为冻结 request payload；
- 下载 / 扫描 / 导入阶段由 durable worker 执行；
- 复用 cancellation、retry、lease、generation、progress、Task Center；
- 未标注图片可以直接走正式 import；
- 检测到标注的数据仍保持现有 fail-closed：必须先进入标签映射确认，不自动映射；
- v36 endpoint 如需兼容，只做 adapter / 410 / redirect 到 canonical owner，不能继续启动 daemon worker。

迁移时必须保留 URL / 本机路径的产品能力，不能简单删除“地址读取”。

**回归测试建议：**

至少覆盖：

- 地址单图 / 目录 / URL ZIP 都创建 canonical Durable Task；
- worker 中途退出后任务可恢复或明确失败，不永久 running；
- partial side effects 重试不重复入库；
- cancellation 生效；
- 带标注来源仍要求标签映射确认；
- 前端只存在一个 Material Import poll / task truth owner；
- 1k / 10k / 20k 地址导入不依赖独立 JSON job 全量历史。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-072 — v36 Source Import 用“项目导入前后全量 ID 差集”猜本任务 imported_ids；并发导入的新素材会被误归属并被错误改写 split

**级别：高**  
**模块：Material Import / Dataset Split / Concurrency / Data Correctness**

**现象：**

`_v36_run_source_import()` 没有保存“本任务实际成功写入的 material IDs”，而是：

1. 启动时：
   `before_ids = {id for id in load_images(project_id)}`
2. 自己执行下载 / 图片写入；
3. 完成后再次：
   `after = load_images(project_id)`
4. 用：
   `imported_ids = [id for id in after if id not in before_ids]`
   推断“本任务导入的素材”。

这个差集是 **整个 project 的时间窗口差集**，不是 task ownership truth。

因此只要 v36 运行期间另一个合法入口也向同一项目加入素材，例如：

- ZIP Material Import；
- 普通多图上传；
- 视频抽帧；
- Source Collection；
- 其他并行地址导入；

这些并发新增的 image id 同样不在 `before_ids` 中，会被 v36 当成自己的 `imported_ids`。

随后 v36 会把整组 guessed IDs 交给：

`_v36_apply_split_policy(...)`

并执行：

`material_store(project_id).patch(patches)`

直接修改 split。

**真实数据污染：**

当前 UI 默认 split policy 是：

`annotated_train_unannotated_test`

所以一个与 v36 无关的并发素材，可能被：

- 有框：重分到 train / val；
- 暂时还没写完 annotation：误判为 unannotated，直接改成 test。

如果用户选择 ratio，则所有被误归属的并发素材都会按 v36 的 ratio 重新切 train / val / test。

也就是说，任务 A 可以修改任务 B 刚刚导入素材的 dataset split。

这违反了 Dataset Revision / Material Import 已经收口的“任务只能提交自己冻结/拥有的数据”边界。

**为什么 AUDIT-071 不能完全覆盖：**

AUDIT-071 是 execution owner / crash recovery 问题。

本条即使把 daemon thread 换成 Durable Task，如果仍保留“before/after 全项目差集”算法，数据污染仍然存在，因此需要单独记录。

**影响：**

- 并发导入时 split 被跨任务篡改；
- 标注尚未完成投影的素材可能被误判无标注并放入 test；
- 训练集 / 验证集 / 试验集边界失真；
- 后续训练 Dataset Revision 可冻结到错误 split；
- 问题具有时序性，单任务测试难复现；
- 20k 大批量导入时间窗口更长，发生概率更高。

**建议最小修复：**

不要再通过 project snapshot 差集推断 ownership。

canonical import owner 必须在每次成功写 material 时直接累计本任务的真实 ID：

- `add_image_record()` 返回的 id 立即进入 task-owned result / checkpoint；
- split 只能作用于该 task-owned ID 集；
- retry / resume 复用同一 task ledger；
- 其他任务新增的素材永远不能进入当前任务的 split patch；
- 最终 report 也应从 task ledger 计算，而不是重新扫描全项目猜测。

迁移 AUDIT-071 到 Durable MATERIAL_IMPORT 时，应顺便删除 before/after project-diff 机制，而不是原样搬过去。

**回归测试建议：**

至少覆盖：

- v36/新 canonical source import 与 ZIP import 同时运行；
- A 导入期间 B 新增素材，A 的 result IDs 不包含 B；
- A split patch 绝不修改 B 的 split；
- B annotation 尚未提交完成时也不能被 A 判成 unannotated；
- 两个 Source Import 并发时各自 ledger 完全隔离；
- retry/resume 后 task-owned IDs 不重复、不串任务。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-073 — v36 split 计算在遍历每张项目素材时重复构造 set(imported_ids)；大批量导入退化为 O(project_images × imported_images)

**级别：中～高**  
**模块：Source Import / Dataset Split / Performance / 10k–20k Scale**

**现象：**

`_v36_apply_split_policy()` 当前先读取整个项目：

`images = load_images(project_id)`

随后构造本任务 image map 时写成：

`{x.get("id"): x for x in images if x.get("id") in set(imported_ids)}`

这里的 `set(imported_ids)` 位于 comprehension 条件内部。

Python 会对 **每一条 project image** 再执行一次集合构造，而不是自动把它提升到循环外。

因此复杂度不是预期的：

`O(project_images + imported_images)`

而是近似：

`O(project_images × imported_images)`

并伴随大量临时 set 分配 / 回收。

**20k 场景：**

例如：

- 项目已有 / 最终约 20,000 张；
- 本次地址导入约 20,000 张；

这一行理论上会反复处理约 4 亿次 imported-id 元素来重建集合，尚未计入：

- 前置 `load_images()`；
- `_v36_run_source_import()` 的 before/after 两次全量项目读取；
- 对每个 imported id 的 annotation 判断；
- 最后的 material patch。

这会直接把 split finalize 阶段变成 CPU / allocator 热点，表现为任务长时间停在：

“正在分类训练/评测/试验集”。

**现有测试缺口：**

`tests/api/test_v36_source_import_guard.py` 当前只用 1 张图片验证：

- annotated directory/ZIP fail-closed；
- plain image directory 仍可导入。

前端/browser 测试主要验证：

- PollRegistry owner；
- terminal completion 只做 scoped refresh；
- 不 broad reload。

没有 1k / 10k / 20k split finalize 性能合同，因此该 O(N×M) 路径没有被发现。

**与 AUDIT-071 / 072 的关系：**

- AUDIT-071：v36 是独立 daemon execution owner；
- AUDIT-072：before/after project diff 会把并发任务素材误归属；
- 本条：即使 ownership 已修正，只要保留当前 comprehension 写法，大批量 split 仍会出现独立的算法复杂度问题。

因此不是重复问题。

**建议最小修复：**

在迁移到 canonical Material Import owner 时：

- task-owned IDs 本身应已有稳定集合 / ledger；
- 如仍需要过滤 project rows，至少先：
  `imported_id_set = set(imported_ids)`
  只构造一次；
- 更优的是直接按 task-owned IDs 做 indexed MaterialRepository 查询，不先全量 `load_images(project_id)`；
- annotation state 也应批量读取，不做逐 ID 文件 / repository N+1；
- split patch 继续使用 bulk patch。

**回归测试建议：**

至少增加：

- 1k / 10k / 20k imported IDs 的 split finalize；
- 断言不会为每张 project image 重建 imported-id set；
- 大项目、小批导入应与项目总历史近似解耦；
- 大批导入应使用 batch/indexed annotation state；
- 性能测试不能只测 1 张 happy path。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-074 — v36 Source Import 列表先全量读取全部历史 JSON、再截最新 100；旧 active task 可从前端消失并让 PollRegistry 提前停轮询

**级别：中～高**  
**模块：Source Import / Active Task Truth / Polling / History Scale**

**现象：**

v36 job list 当前实现为：

`_v36_load_source_jobs(project_id)`

先：

- `glob("*.json")`
- 对全部历史 job 做 `stat()`
- 按 mtime 排序
- 对全部文件逐个 `read_json()`

然后 endpoint 才：

`return {"items": items[:100]}`

也就是：

- 服务端请求成本随累计历史线性增长；
- 返回给浏览器的 active truth 却只剩“最近更新的 100 条”。

前端 `refreshSourceImportTasksV36()` 随后直接以这 100 条判断：

`state.sourceImportTasks.some(t => ['queued','running'].includes(...))`

如果没有，就：

- clear `SOURCE_IMPORT_POLL_KEY_V36`
- 当成全部任务已 terminal
- 执行完成后的 labels/material scoped refresh。

**旧 active task 消失场景：**

v36 大目录导入在“正在解析目录 / 正在写素材”阶段没有逐图片持续刷新 job mtime。

如果它运行较久，同时产生 100 个 mtime 更新更晚的 source-import job，则这个仍真实 running 的旧任务可以被挤到第 101 条以后：

- backend 不返回它；
- 前端任务表看不到它；
- 前端判断当前没有 queued/running；
- PollRegistry 停止主动轮询；
- 用户得到“当前导入都结束”的错误视图。

这与“最新 100 历史”作为“全部 active truth”混用了两个不同语义。

**额外性能问题：**

即便 endpoint 最终只返回 100 条，它仍在每次 GET 前把全部历史 JSON 文件排序并读完。

因此历史达到 1k / 10k 后，1.8 秒轮询会反复做：

- directory glob；
- N 次 stat；
- N 次 JSON read / parse；
- N log N 排序。

截断并没有限制服务端工作量。

**影响：**

- 旧 running source import 从 UI 消失；
- PollRegistry 提前停止；
- active task 状态不可观测；
- terminal refresh 可在真实导入仍运行时触发；
- 历史越多，轮询接口越慢；
- 结合 AUDIT-071 的 daemon owner，用户也没有统一任务中心可以找回这条任务。

**建议最小修复：**

AUDIT-071 迁移到 canonical Durable MATERIAL_IMPORT 后，应直接复用：

- status-indexed active query；
- cursor-paged terminal history；
- active tasks 永远完整返回或独立查询；
- browser 不从 bounded terminal page 推断“是否还有 active”。

如果 v36 兼容 endpoint 暂时保留，也至少需要：

- active 与 history 分开读取；
- active 不受 100 条上限影响；
- terminal history 使用真正分页 / cursor；
- 不得每 1.8 秒全量扫描整个 JSON 历史目录。

**回归测试建议：**

至少覆盖：

- 1 个旧 running + 100/200 个更新更晚 terminal job，旧 running 仍必须可见；
- browser 不得因 bounded history 缺失 active 而停 PollRegistry；
- 1k / 10k 历史时 list 请求只读取 bounded page / indexed active truth；
- active 完成后才触发 terminal scoped refresh。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-075 — Agent start 对不可恢复的任务 payload / 执行合同错误仍按临时错误循环重试；任务可永久停在 QUEUED

**级别：高**  
**模块：Node Agent / AgentExecution / Task Assignment / Durable Task Lifecycle / Retry Semantics**

**现象：**

Agent HTTP 客户端已经明确提供：

`NodeExecutorHTTPError.retryable`

并把 transport failure、408 / 425 / 429、5xx 标记为可重试；普通 4xx 默认不可重试。

但 `NodeAgentExecutorLoop.run_once()` 在：

`client.start_execution(task_id, assignment_token)`

失败时，对所有 `NodeExecutorHTTPError` 统一：

```python
except NodeExecutorHTTPError as error:
    self._set_error(f"{error.code}: {error}")
    return True
```

完全没有读取 `error.retryable`。

因此临时网络错误和任务自身永久损坏被使用同一 lease-expiry 重试策略。

**真实永久错误路径：**

`AgentExecutionService.start_execution()` 在真正执行 `QUEUED -> RUNNING` 之前读取 task-owned payload。

至少以下错误发生时 task 仍保持 QUEUED：

- `TASK_PAYLOAD_UNAVAILABLE`：request artifact 缺失、无法读取或 JSON 损坏；
- `REMOTE_EXECUTION_PAYLOAD_INVALID`：远程 request / resolver 结果不是 object；
- 其它由冻结 request 本身导致、等待或换 Agent 也不会自动恢复的 contract error。

现有测试 `test_missing_payload_never_transitions_task_to_running` 已直接证明：

- start 返回 `TASK_PAYLOAD_UNAVAILABLE`；
- task 仍是 `TaskStatus.QUEUED`。

测试只保护“坏 payload 不得进入 RUNNING”，没有定义它应如何结束生命周期。

**真实循环：**

1. assignment：ASSIGNED；
2. Agent claim：ASSIGNED -> CLAIMED；
3. start_execution 读取坏 request.json；
4. 返回不可重试 4xx；
5. task 仍 QUEUED；
6. assignment 仍 CLAIMED；
7. claim lease 到期后 `claim_for_node()` 自动 CLAIMED -> ASSIGNED；
8. 后续再次 claim / start；
9. 相同永久错误再次发生。

没有 owner：

- 把 task 转为 FAILED / BLOCKED；
- 持久化稳定 task-level error；
- 终止该任务的自动调度。

所以一个已经无法执行的 Durable Task 可以无限显示“排队中”。

**为什么不是正常 lease retry：**

对于以下情况等待 lease expiry 是合理的：

- Agent runner 暂时不 ready；
- capability heartbeat race；
- 网络故障；
- 控制面 5xx。

当前代码也明确把 stale / temporarily unsupported runtime 留给 lease expiry 恢复。

但 payload 丢失 / 损坏属于 task-owned permanent precondition failure；重新 claim 同一任务不会修复 request artifact。

更关键的是：代码已经拥有 `retryable` 分类信号，但 executor 没消费它，说明错误分类与 retry lifecycle 已脱节。

**影响：**

- UI 长期显示 QUEUED，而任务实际永远不可执行；
- assignment 周期性 CLAIMED / ASSIGNED，产生无意义调度；
- 用户正常 task detail 看不到稳定根因，只可能在 Agent last_error 中短暂看到；
- claim/start API、日志、调度机会被持续消耗；
- 排障容易被误判为 GPU 忙或 Agent 不在线；
- 后续新增 permanent 4xx contract error 会自动继承同一错误生命周期。

**与既有问题的区别：**

- AUDIT-055：取消 pre-start task 后 assignment 不释放；
- AUDIT-060：node offline 后 assignment 不迁移；
- AUDIT-063：Central Scheduler 缺生产 allocation driver；
- AUDIT-070：RUNNING Agent Training 的 GPU reservation 被过早释放。

本条是：

**assignment 已成功 claim，但 execution start 因不可恢复的 task-owned request/payload 错误失败后，没有 terminal/block lifecycle。**

**建议最小修复：**

不要让 Agent 直接写中央 TaskRepository，也不要增加第二 retry scheduler。

由 control-plane canonical execution owner 分类 start failure：

1. transient / retryable：
   - transport；
   - 408 / 425 / 429 / 5xx；
   - heartbeat / capability 等可恢复 race；
   - 保持 lease expiry / reassignment。

2. permanent task-owned precondition：
   - payload missing / corrupt；
   - frozen remote execution contract invalid；
   - 明确不可恢复 request schema error；
   - 原子：
     - fail/block QUEUED task；
     - 持久化稳定 error code/message；
     - release active assignment；
     - 停止自动 claim retry。

不能简单把所有 4xx 都 terminal；可能因平台配置/升级恢复的错误必须显式保留 retryable 分类。

**回归测试建议：**

至少覆盖：

- payload artifact 缺失：CLAIMED -> start -> BLOCKED/FAILED + assignment RELEASED；
- payload JSON 损坏同样 fail-closed；
- invalid frozen remote request 不再无限 QUEUED；
- transport timeout / 5xx 仍可重试；
- capability 暂时撤销仍可恢复；
- permanent failure 后不会再次 claim 同 task；
- public task truth 展示稳定错误；
- execution generation / lease fencing 不放宽。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-076 — Service Node 删除未检查 ASSIGNED / CLAIMED；可删除仍持有 pre-start assignment 的离线节点并永久留下悬空任务绑定

**级别：高**  
**模块：Service Node / Central Scheduler / Node Assignment / DELETE Lifecycle / GPU Reservation**

**现象：**

`ServiceNodeRepository.delete(node_id)` 当前只检查：

1. 当前节点是否还有未过期 `worker_instances`；
2. 是否存在通过这些 worker_id 关联的 `RUNNING / CANCEL_REQUESTED` task。

满足任一条件才返回：

`SERVICE_NODE_BUSY / 409`。

但 Central Scheduler 在 Agent 真正 start 之前，任务仍保持：

`TaskStatus.QUEUED`

同时通过独立表保存：

- `task_node_assignments.state = ASSIGNED`；
- 或 `CLAIMED`。

Service Node DELETE 完全没有查询这张 assignment 表。

**更关键的是数据库没有外键保护：**

`task_node_assignments.node_id TEXT NOT NULL`

没有：

`REFERENCES service_nodes(node_id)`

所以：

`DELETE FROM service_nodes WHERE node_id=?`

不会因为 active assignment 而失败，也不会级联 release。

**真实可达场景：**

1. Training / Conversion / Cleaning 等 Durable Task 仍是 QUEUED；
2. Central Scheduler 已为它创建：
   `ASSIGNED -> node-A`；
3. node-A 随后离线，worker lease 过期；
4. 当前没有 RUNNING task；
5. operator 删除 node-A；
6. `ServiceNodeRepository.delete()` 认为：
   - live_workers = 0；
   - active_tasks = 0；
7. service_nodes 中 node-A 被删除；
8. `task_node_assignments` 中：
   `task_id -> node-A, state=ASSIGNED/CLAIMED`
   仍然存在。

**为什么任务不会自动换节点：**

`CentralTaskAllocator.assign_next()` 只选择：

```sql
WHERE task.status='QUEUED'
AND NOT EXISTS (
  SELECT 1 FROM task_node_assignments
  WHERE assignment.task_id=task.task_id
    AND assignment.state IN ('ASSIGNED','CLAIMED')
)
```

因此只要这条悬空 assignment 仍 active：

- task 虽然 QUEUED；
- 即使 node-B 在线且能力完全匹配；
- allocator 也不会给它创建新 assignment。

原 node-A 已经被删除，不可能再 heartbeat / claim。

最终形成：

**QUEUED task + active assignment 指向不存在的 node。**

**与 AUDIT-060 的区别：**

AUDIT-060 是：

- 节点仍存在但 OFFLINE；
- active assignment 不自动 release / reassign。

AUDIT-076 是更强的 DELETE lifecycle bypass：

- operator 已把节点实体永久删除；
- assignment 仍保留为 active；
- task 仍被 `NOT EXISTS active assignment` fence 排除。

即使未来修复一般 offline reassignment，本条 DELETE 如果不纳入同一 retirement contract，仍可能制造 dangling assignment。

**与之前“Service Node 删除安全”结论的修正：**

此前审计确认：

- live Worker 会阻止删除；
- RUNNING / CANCEL_REQUESTED execution 不应被直接删除节点破坏。

这部分仍成立。

但该结论没有覆盖：

**QUEUED + ASSIGNED/CLAIMED 的 pre-start 生命周期。**

因此“Service Node 删除当前没有生命周期绕过”的旧结论需要收窄；本条即为新发现的 pre-start 删除旁路。

**影响：**

- QUEUED Training 可永久不再调度；
- 预留的 GPU / node assignment truth 成为孤儿；
- 任务页面长期表现为排队/等待资源，但没有可执行节点 owner；
- 新节点即使资源充足也不能接手；
- operator 只能知道 task_id 后手工调用 assignment release 或直接修数据库；
- node assignment history 与 service node inventory 出现 referential drift；
- 批量删除/重建节点时可能积累多个 dangling assignment；
- 与 AUDIT-055 / 060 / 063 叠加时，Agent 调度可出现非常难排查的“队列永远不动”。

**现有测试缺口：**

`tests/unit/test_service_nodes.py` 当前 DELETE 只验证：

- live worker -> SERVICE_NODE_BUSY；
- worker release 后可以删除。

没有覆盖：

- node 有 ASSIGNED task；
- node 有 CLAIMED task；
- node 已离线但 assignment 仍 active；
- DELETE 后 task 是否能重新分配。

assignment 测试与 service-node 测试分开，因此跨 owner retirement contract 没有被保护。

**建议最小修复：**

不要通过给 assignment 表随意加 `ON DELETE CASCADE` 解决，因为静默删除 reservation 会丢失 release reason / audit lineage。

Service Node retirement 应由一个明确 lifecycle owner 原子处理：

1. DELETE 前检查 active `ASSIGNED / CLAIMED`；
2. 如果仍 active：
   - 默认 409 SERVICE_NODE_BUSY；
   - 或明确执行受审计的 assignment release/requeue 流程后再删；
3. release 必须写：
   - released_at；
   - release_reason，例如 `node_deleted`；
4. task 保持 QUEUED 后，应允许 canonical scheduler 重新选择其他 eligible node；
5. strict manual node affinity 的 task：
   - 不能静默 spill 到其他机器；
   - 应转为明确 WAITING_RESOURCE / BLOCKED，并提示指定节点已删除；
6. DELETE 与 concurrent claim/start 必须在同一数据库事务/fence 下避免 race。

**回归测试建议：**

至少覆盖：

- ASSIGNED task 时删除 node -> 409；
- CLAIMED task 时删除 node -> 409；
- 显式 retirement/release 后删除成功；
- 自动可迁移 task release 后可分配到 node-B；
- strict requested_node_id 指向已删除节点时不 spill；
- DELETE 与 claim/start 并发时不能产生 dangling active assignment；
- assignment history 保留 release_reason；
- 现有 RUNNING execution 保护不回退。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-077 — Service Node DELETE 的 RUNNING 保护只识别 worker_instances；Agent execution 使用 agent:<node_id>，运行中的远程任务也可被直接删节点

**级别：严重**  
**模块：Service Node / Agent Execution / RUNNING Lifecycle / Authentication / DELETE Fence**

**现象：**

`ServiceNodeRepository.delete()` 当前用于阻止删除“有运行任务的节点”的 SQL 是：

```sql
SELECT COUNT(*) FROM tasks
 WHERE status IN ('RUNNING','CANCEL_REQUESTED')
   AND worker_id IN (
       SELECT worker_id FROM worker_instances WHERE node_id=?
   )
```

这条保护只对注册在 `worker_instances` 的 Worker 成立。

但真正的 Node Agent execution 在 `AgentExecutionService.start_execution()` 中明确写入：

`worker_id = f"agent:{node_id}"`

现有测试 `test_agent_start_is_single_atomic_queued_to_running_transition` 也明确断言：

`task.worker_id == "agent:gpu-agent"`

Node Agent 通过 `service_nodes` heartbeat / token 体系工作，并不把 `agent:<node_id>` 注册成 `worker_instances.worker_id`。

所以一个真实 RUNNING Agent task 不会被 DELETE 的 `active_tasks` 查询命中。

**更严重的是：节点在线也不是 DELETE fence。**

`ServiceNodeRepository.delete()` 没有检查：

- `service_nodes.last_heartbeat_at`；
- `reachable / online`；
- Agent execution 的 `worker_id = agent:<node_id>`。

只要：

- 没有 legacy/local live worker；
- `worker_instances` 子查询找不到匹配 RUNNING task；

就会执行：

`DELETE FROM service_nodes WHERE node_id=?`

因此即使：

- Agent 正在持续 heartbeat；
- Training / Conversion / Cleaning / Deployment Test 已经 RUNNING；

operator 仍可能直接删掉这个 Service Node。

**删除后的真实破坏链：**

Agent execution 的后续接口都会先执行：

`_authenticate_node(node_id, node_token, ...)`

包括：

- execution heartbeat；
- logs；
- material scan/read；
- cleaning selection；
- training model upload；
- result upload；
- begin-finalization；
- finish。

节点实体被删除后：

`ServiceNodeRepository.authenticate/get_public`

无法再找到 node。

所以仍在运行的 Agent 会失去控制面认证，后续：

- heartbeat 失败；
- result upload 失败；
- finalization 失败；
- finish 失败。

任务在数据库里却已经是 RUNNING，直到 execution lease 过期后才可能被 recovery 转回 QUEUED。

对于 Training，还可能出现远端训练进程已经真正开始、但控制面节点身份被删掉的执行裂脑窗口。

**为什么 AUDIT-076 不能覆盖：**

AUDIT-076 是：

- task 仍 QUEUED；
- assignment = ASSIGNED / CLAIMED；
- 删除节点留下 dangling pre-start assignment。

AUDIT-077 是：

- assignment 已在 start 时 RELEASED；
- task 已正式 RUNNING；
- DELETE 的 RUNNING protection 因 worker identity 模型不一致而完全漏掉 Agent execution。

两个生命周期阶段不同：

- 076 修 assignment retirement；
- 077 必须修 RUNNING execution -> node identity 的 canonical reference fence。

仅修 active assignment DELETE fence 不能保护已经 start 的 Agent task，因为 start 后 assignment 已按当前设计 RELEASED。

**影响：**

- 正在训练的远程 GPU 节点可被直接删除；
- 正在转换 / 清洗 / 检测的 Agent 任务同样受影响；
- Agent 后续 heartbeat/log/result/finalization 全部失去认证；
- 已完成的远端结果可能无法提交；
- Training 可能浪费数小时 GPU 计算；
- execution lease 过期后任务可能重排，再次执行同一工作；
- 对带外部副作用的任务会放大重复执行风险；
- 页面“删除节点成功”与后台仍有 RUNNING task 的事实矛盾；
- Service Node retirement 与 Agent execution ownership 完全没有统一引用检查。

**为什么现有测试没发现：**

当前 Service Node DELETE 测试只覆盖：

`test_delete_is_blocked_while_node_has_a_live_worker`

即：

- 创建 `worker_instances` lease；
- DELETE -> SERVICE_NODE_BUSY；
- release worker 后 DELETE success。

Agent execution 测试单独确认：

- RUNNING；
- `worker_id = agent:<node_id>`；
- assignment 在 execution_started 后 RELEASED。

但没有跨层测试：

`Agent start RUNNING -> ServiceNodeRepository.delete(node_id) -> 必须 409`

所以两套各自测试都绿，identity contract 仍断裂。

**建议最小修复：**

不要伪造一条 `worker_instances` 记录来让 Agent 迁就 legacy Worker 模型。

Service Node retirement 应直接使用 canonical execution identity：

1. DELETE 前检查：
   - live `worker_instances`；
   - active ASSIGNED / CLAIMED（AUDIT-076）；
   - `tasks.status IN (RUNNING,CANCEL_REQUESTED)` 且：
     `worker_id = 'agent:' || node_id`；
2. 有任何 active Agent execution 时返回：
   `SERVICE_NODE_BUSY / 409`；
3. 如未来支持“强制下线”：
   - 必须先走 canonical cancel/fence；
   - 等 execution terminal 或 lease ownership明确释放后才能删除；
4. token rotation / node disable 可以有独立语义，但 DELETE 不得成为隐式 execution cancel；
5. 同一事务中 recheck，避免 DELETE 与 start_execution 并发穿透。

如果未来引入统一 execution-node relation，也应由一个 canonical relation owner替代字符串拼接，但本轮不需要重构整个架构。

**回归测试建议：**

至少覆盖：

- Agent Training RUNNING -> DELETE node = 409；
- Agent Conversion RUNNING -> 409；
- Agent Cleaning / Deployment Test RUNNING -> 409；
- CANCEL_REQUESTED -> 409；
- execution terminal 后允许删除；
- node 在线但无 active task 可按产品合同删除/或要求先 disable；
- DELETE 与 start_execution 并发时不能删掉刚进入 RUNNING 的节点；
- 不破坏 legacy live worker 现有保护；
- 不依赖 active assignment，因为 RUNNING 时 assignment 已 RELEASED。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-078 — Service Node 的 durable_tasks 投影只认 worker_instances；Agent RUNNING task 在节点页被显示为“0 个执行中任务”

**级别：高**  
**模块：Service Node / Runtime Projection / Agent Execution / Frontend Truth / Operations UI**

**现象：**

`ServiceNodeRepository._runtime_projection()` 先调用：

`WorkerInstanceService(...).list_runtime()`

再构造：

`worker_to_node[worker_id] = node_id`

只有当 `worker_to_node` 非空时，才查询 RUNNING / CANCEL_REQUESTED tasks，并通过：

`node_id = worker_to_node.get(task.worker_id)`

把 task 投影到某个 Service Node。

这个模型只能识别 `worker_instances` owner。

但 Agent execution 的 canonical worker identity 是：

`worker_id = "agent:<node_id>"`

它来自 `AgentExecutionService.start_execution()`，并不注册到 `worker_instances`。

因此真实 RUNNING Agent task 在 `_runtime_projection()` 中无法找到 node_id，最终不会进入：

`node.durable_tasks`。

**前端确实直接使用这个字段：**

`static/modules/service-node-runtime.js`

节点详情：

`taskRows(node)`

只读取：

`node.durable_tasks`

为空时直接显示：

“当前无执行中的持久任务”。

页面顶部汇总：

```js
const tasks = nodes.reduce(
  (sum, node) => sum + (node?.durable_tasks?.length || 0),
  0
)
```

并显示：

“执行中任务 0”。

所以这不是仅影响一个内部 API 字段，而是用户可见的真实状态错误。

**与 AUDIT-077 的关系：**

AUDIT-077 和本条暴露了同一个 identity split 的两个不同后果：

- AUDIT-077：DELETE fence 用 `worker_instances` 判断 active task，导致 RUNNING Agent execution 挡不住删除；
- AUDIT-078：页面 runtime projection 同样用 `worker_instances` 映射 task，导致 RUNNING Agent execution 在 UI 中不可见。

只修 DELETE SQL 不能修节点页观测；只修页面也不能修 DELETE lifecycle，因此分别登记。

**用户可见场景：**

1. node-A 在线；
2. Agent Training 成功 start；
3. task：
   - status=RUNNING；
   - worker_id=agent:node-A；
4. Service Node GET/list；
5. `workers_by_node` 没有 `agent:node-A`；
6. `durable_tasks=[]`；
7. 页面显示：
   - “当前无执行中的持久任务”；
   - 顶部“执行中任务 0”；
8. 同一个页面仍提供“删除”按钮。

更误导的是删除确认文案写着：

“运行中的 Worker/任务存在时服务器会拒绝删除。”

但 AUDIT-077 已证明 Agent RUNNING task 实际不会被该 DELETE fence识别。

所以 UI 同时：

- 看不到真实任务；
- 又向 operator 提供错误的删除安全预期。

**影响：**

- 训练实际在跑，节点页却显示无任务；
- 运维人员可能错误判断节点空闲；
- 顶部执行中任务统计失真；
- 用户可能在任务运行时执行编辑/删除/维护操作；
- GPU / CPU 资源占用与任务列表不一致；
- 故障排查无法从节点页关联到 task_id；
- 结合 AUDIT-077，可直接提高误删运行节点的概率；
- 多节点环境下负载观察、调度判断与真实 execution ownership 分裂。

**为什么现有测试没发现：**

`tests/unit/test_service_nodes.py` 当前没有针对：

- `durable_tasks`；
- `worker_id=agent:<node_id>`；
- Agent RUNNING task -> node projection

的合同测试。

Agent execution tests 单独验证 canonical worker_id；

Service Node tests 单独验证 worker/runtime registry；

前端 tests 只按 API 返回的 `durable_tasks` 渲染，没有验证后端是否会把 Agent task 填进去。

**建议最小修复：**

不要为了页面显示去伪造 `worker_instances`。

应让 Service Node runtime projection 同时识别两种 canonical execution identity：

1. legacy/local Worker：
   - 继续通过 `worker_instances.worker_id -> node_id`；
2. Agent execution：
   - 对 RUNNING / CANCEL_REQUESTED task 的：
     `worker_id LIKE 'agent:%'`
   - 按严格 canonical parser 解析 node_id；
   - 必须确认对应 service_nodes entity 存在；
   - 再投影到同一个 `durable_tasks` 结果。

更长期可以抽成一个共享“task execution node identity” helper，让：

- Service Node page；
- DELETE fence；
- scheduler/diagnostics

复用同一身份解析，避免再次复制字符串规则。

但不要创建第二套 task truth；TaskRepository 仍是 Durable Task owner。

**回归测试建议：**

至少覆盖：

- Agent Training RUNNING -> node.durable_tasks 包含 task；
- Agent Conversion / Cleaning / Deployment Test 同样可见；
- CANCEL_REQUESTED 仍显示；
- terminal task 不显示；
- legacy/local Worker projection保持；
- 顶部执行中任务计数包含 Agent；
- 节点详情不再错误显示“当前无执行中的持久任务”；
- malformed `agent:` worker_id 不得错误映射任意 node；
- deleted/missing node 不产生伪造 projection。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-079 — CentralTaskAllocator.assign_next 每分配 1 个任务先 fetchall 全部 QUEUED，并对不匹配候选重复读取 request artifact；10k/20k 队列形成调度 O(N) + N×文件 I/O 热点

**级别：中～高**  
**模块：Central Scheduler / Queue Scale / Artifact Hydration / N+1 / Performance**

**现象：**

`CentralTaskAllocator.assign_next()` 的第一步是：

```sql
SELECT task.* FROM tasks task
 WHERE task.status='QUEUED'
   AND NOT EXISTS (...active assignment...)
 ORDER BY ...
```

随后直接：

`.fetchall()`

即每次只想分配 **1 个 task**，却先把全局所有尚未 assignment 的 QUEUED TaskRecord 一次性 hydrate 到 Python。

接着按顺序逐个 candidate 做 eligibility 计算。

对于每一个无法立即分配的候选，会调用多组 helper：

- `task_node_capability(task, artifacts)`
- `task_remote_execution_contract(task, artifacts)`
- `task_node_connection_mode(task, artifacts)`
- `task_requested_node_id(task, artifacts)`
  - 内部再调用 `task_scheduling()`
- Training 还会调用 `_requested_training_device(task, artifacts)`

这些 helper 各自独立执行：

`artifacts.read_json(task.task_id, task.payload_ref, ...)`

也就是说同一个 candidate 的同一个 request artifact，单次 assign 尝试可能被重复读取/解析多次。

**最差场景：**

假设队列里有 20,000 个 QUEUED task，而当前：

- 对应 capability 没有 online node；
- manual affinity 指向 offline node；
- GPU device 不满足；
- remote execution contract 与 node connection mode 不匹配。

`assign_next()` 会：

1. 一次性 fetchall 20,000 TaskRecord；
2. 从队首开始逐个检查；
3. 对大量 candidate 多次打开/解析 request JSON；
4. 对 candidate 反复执行 online-node / ranking SQL 与资源判断；
5. 最终可能只得到：
   `None`。

即“没有任务能运行”反而是最昂贵的调度请求之一。

**为什么属于独立 Bug / 性能债：**

AUDIT-064 是：

- public task list 为 queue position 全量 hydrate QUEUED task；
- 属于 API/UI projection 热路径。

AUDIT-079 是：

- **scheduler 自己的 allocation 热路径**；
- 每成功分配 1 个任务，或每次证明“当前无任务可分配”，都可能扫描全队列。

两个 owner 和修复点不同。

另外这也不同于 AUDIT-063：

- AUDIT-063 是 production allocation driver 缺失；
- AUDIT-079 是 allocator 本身的规模复杂度。

未来补上 production driver 后，如果直接高频调用当前 `assign_next()`，本问题会被放大。

**额外 N+1 / 重复 I/O：**

当前 task scheduling metadata 没有一次解析后复用。

例如 Training candidate 可在同一轮中重复读取 payload 来获得：

- remote_execution；
- scheduling.mode/node_id；
- connection mode requirement；
- requested_device。

这不是 5 个不同 truth owner，而是同一个 immutable/frozen request 的重复 hydration。

1k / 10k / 20k 队列下会制造大量：

- filesystem open/stat/read；
- JSON decode；
- SQLite query；
- Python object allocation。

**影响：**

- queued task 累积后 scheduler allocation latency 线性升高；
- 无可用节点时尤其慢；
- 20k 队列可形成明显 Web/API 阻塞；
- production allocator driver 补齐后可能持续占用控制面线程；
- SQLite transaction `BEGIN IMMEDIATE` 覆盖整段扫描，长时间持有写事务；
- assignment / claim / operator scheduler API 更容易互相等待；
- 文件系统在慢盘/NFS环境下放大；
- 任务越多，调度吞吐反而下降。

**事务放大：**

`assign_next()` 在开始全量 SELECT 之前已经：

`BEGIN IMMEDIATE`

之后才：

- fetchall；
- artifact reads；
- node queries；
- ranking；
- 最终 INSERT assignment / commit。

所以外部文件 I/O 也发生在一个 IMMEDIATE transaction 生命周期里。

这会把“读取 20k request metadata”的时间变成 SQLite 写锁占用时间。

**现有测试为什么没发现：**

`tests/unit/test_task_node_assignments.py` 有大量：

- assign；
- claim；
- GPU selection；
- preemption；
- affinity；
- capability；
- race

功能测试，但没有：

- 1,000；
- 10,000；
- 20,000

QUEUED task 的 allocator scale contract。

也没有断言：

- 每次 assign 最大读取多少 TaskRecord；
- 同一个 payload 最多 read_json 几次；
- 无 eligible node 时 SQL / file read 上限；
- transaction 内不能做无界文件 hydration。

**建议最小修复：**

不要新增第二 Scheduler，也不要把 eligibility 复制到别处。

保持 `CentralTaskAllocator` 为唯一 assignment owner，但把 selection 做成 bounded/indexed pipeline：

1. SQL 先按：
   - status；
   - active assignment absence；
   - kind / capability 可预索引字段；
   - priority/order
   做 bounded candidate window；
2. 一次只取有限 candidate，例如 50/100，必要时 cursor 向后推进；
3. 同一 candidate 的 payload 在一次 allocation cycle 内只解析一次，构造成 scheduling snapshot；
4. 能持久化/索引的稳定 scheduling metadata，应在 task admission 时冻结，不要每次从 JSON 重算；
5. 不要在 `BEGIN IMMEDIATE` 内做大规模 filesystem I/O：
   - 先 bounded read/preflight；
   - 最终 assignment 时再用短事务 recheck task/node/generation；
6. 保留 deterministic priority / affinity / GPU fencing；
7. 没有 eligible node 时应 bounded 返回，而不是扫描整个全局队列。

**回归测试建议：**

至少增加：

- 20,000 queued + 1 eligible：bounded candidate hydration；
- 20,000 queued + 0 eligible：仍有明确 query/read 上限；
- 单 candidate request artifact 单 allocation cycle 只读取一次；
- transaction duration 不包含无界 artifact scan；
- strict priority / manual affinity 不改变；
- GPU reservation / capability / connection-mode filtering 不回退；
- concurrent allocator 仍只能创建一个 active assignment。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-080 — AI MaterialBatch 的 PARTIAL_SUCCESS“重试”会被旧 review confirmation 短路回 Commit；失败图片不会重新推理，重试语义实际失效

**级别：高**  
**模块：AI Annotation / MaterialBatch / Retry / Review Confirmation / Candidate Commit**

**现象：**

当前 AI 自动标注的 MaterialBatch 路径使用：

`operation = AI_ANNOTATE`

生成阶段允许部分图片失败。只要至少有成功或 empty 候选，`AnnotationBatch.finish()` 会进入 `AWAITING_CONFIRMATION`，保留成功、empty、failed 的 CandidateStore truth。

用户确认后写入：

`review/confirmation.json`

且：

`accepted = true`

随后 Worker 调用 `commit_confirmed_review(context)` 将人工确认候选写入正式 AnnotationRepository。

如果 generation 仍有 failed candidate，commit 会返回：

`TaskStatus.PARTIAL_SUCCESS`

因为当前代码明确按：

`PARTIAL_SUCCESS if result["review"].get("failed") else SUCCEEDED`

结束任务。

**前后端都明确允许此状态“重试”：**

前端 `annotationTaskView()` 的 `canRetry` 包含 `PARTIAL_SUCCESS`，任务列表真实显示“重试”按钮。

后端：

`POST /api/v60/projects/{project_id}/annotation-tasks/{task_id}/retry`

对 `TaskKind.MATERIAL_BATCH` 也允许 `PARTIAL_SUCCESS`，随后执行：

`TaskRepository.retry(task_id)`

该 retry 复用原 task_id 与原 artifacts，只把 Durable Task 重置为 QUEUED，不会删除旧：

`review/confirmation.json`。

**真实错误链：**

MaterialBatch handler 再次运行时，在任何 failed-row retry / AI provider generation 之前先执行：

```python
if operation is BatchOperation.AI_ANNOTATE:
    confirmation = context.artifacts.read_json(
        context.task.task_id,
        "review/confirmation.json",
        default=None,
    )
    if isinstance(confirmation, dict) and confirmation.get("accepted") is True:
        return commit_confirmed_review(context)
```

因此：

1. 首轮部分图片生成失败；
2. 用户审核成功结果并确认；
3. 正式标注入库；
4. task = PARTIAL_SUCCESS；
5. UI 显示“重试”；
6. 用户点击 retry；
7. repository 把同 task_id 改回 QUEUED；
8. Worker 重新进入 MaterialBatch；
9. 旧 confirmation 仍是 accepted=true；
10. handler 立即再次进入 Commit；
11. 失败图片不会重新调用模型；
12. task 很可能再次回到同一个 PARTIAL_SUCCESS。

即当前“重试”实际是重放已确认 Commit 阶段，而不是重试失败 work item。

**为什么是独立 Bug：**

即使 Candidate commit journal 能避免正式 GT 重复写入，用户真正要恢复的是失败图片的 AI generation。

当前 retry lifecycle phase 错误地被旧 confirmation 锁在 Commit 阶段，导致 provider 临时错误、限流、单图失败无法通过“重试”恢复。

**影响：**

- PARTIAL_SUCCESS 后“重试”无法恢复失败图片；
- failed_count 无法通过此操作下降；
- 用户可能反复点击重试但始终部分成功；
- task attempt 增长，却没有新的 inference；
- 已确认 Commit 被重复进入，产生不必要的 GT 校验 / journal / heartbeat 成本；
- UI 文案与后端真实执行语义不一致；
- 运维日志看似“又执行一次”，实际没有重新跑失败图片。

**为什么现有测试没发现：**

现有测试分别覆盖 generation partial、review confirmation、PARTIAL_SUCCESS 可重试、TaskRepository retry 和 commit recovery，但没有完整组合：

`generation 部分失败 -> confirm -> PARTIAL_SUCCESS -> retry`

并断言失败图片真的再次进入 provider inference。

**建议最小修复：**

不要新增第二套 AI task owner，也不要删除 CandidateStore commit journal。

应明确区分 retry phase：

1. `AI_ANNOTATE + PARTIAL_SUCCESS` 的“重试失败图片”只重置 generation failed rows；
2. 旧 `review/confirmation.json` 不得继续短路新的 generation retry，可归档旧 confirmation 或记录明确 retry phase；
3. succeeded / empty / 已提交 GT 的 work item 不重复推理；
4. 新失败项重试成功后重新进入 AWAITING_CONFIRMATION；
5. 如果产品还需要“重试 Commit”，应提供独立、明确的 commit-recovery action，不与“AI 重试”共用一个按钮/endpoint；
6. 不能简单删除整个 task artifacts，以免破坏已提交 GT lineage 和审计证据。

**回归测试建议：**

至少覆盖：

- 10 张中 2 张 provider failure -> review/confirm -> PARTIAL_SUCCESS；
- 点击重试后 provider 只再次收到这 2 张；
- 原 8 张不重复推理；
- 旧 confirmation 不再短路 generation retry；
- 重试成功后进入新的 review；
- 再确认后可最终 SUCCEEDED；
- commit journal 仍保证正式 AnnotationRepository 不重复写；
- confirmation 前 CANCELLED/FAILED 的 generation retry 行为不回退。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-081 — AI 任务前端对 SUCCEEDED 一律显示“重试”，但后端禁止成功的 MaterialBatch 重试；点击按钮稳定返回 409

**级别：中**  
**模块：AI Annotation / Frontend Action Eligibility / MaterialBatch / API Contract**

**现象：**

AI 自动标注任务列表与详情都使用：

`annotationTaskView(task)`

决定是否显示“重试”。

当前前端逻辑是：

```js
canRetry: new Set([
  'PARTIAL_SUCCESS',
  'SUCCEEDED',
  'CANCELLED',
  'FAILED',
  'BLOCKED_BY_ENVIRONMENT',
  'BLOCKED_BY_HARDWARE'
]).has(status)
```

它完全不区分任务类型。

而 v60 public task 已明确返回：

`kind = task.kind.value`

所以前端实际上有能力区分：

- `AI_ANNOTATION`
- `MATERIAL_BATCH`

但当前没有使用该字段。

**后端合同与前端不同：**

`POST /api/v60/projects/{project_id}/annotation-tasks/{task_id}/retry`

对普通 `AI_ANNOTATION` 允许：

- CANCELLED
- FAILED
- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE
- PARTIAL_SUCCESS
- SUCCEEDED

并创建新的 task_id。

但对 `MATERIAL_BATCH` 明确只允许：

- CANCELLED
- FAILED
- PARTIAL_SUCCESS
- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE

`SUCCEEDED` 不在允许集合中。

因此成功的 MaterialBatch AI 标注任务：

1. API 返回 `kind=MATERIAL_BATCH`；
2. status = `SUCCEEDED`；
3. 前端 `canRetry=true`；
4. 列表和详情真实显示“重试”按钮；
5. 用户点击后 `retryAiTask60()` 直接 POST retry endpoint；
6. 后端进入 MaterialBatch 分支；
7. 返回 409：
   “只有未完成的批处理任务可以重试”。

这是稳定可复现的前后端 action-contract 漂移。

**为什么与 AUDIT-080 不同：**

AUDIT-080 是：

- MaterialBatch = PARTIAL_SUCCESS；
- 前后端都允许 retry；
- 但 retry lifecycle 被旧 confirmation 错误短路到 Commit。

AUDIT-081 是：

- MaterialBatch = SUCCEEDED；
- 前端错误宣称可 retry；
- 后端明确禁止；
- 用户点击后稳定 409。

一个是 retry 执行语义错误，一个是 action eligibility 漂移，修复点不同。

**影响：**

- 成功任务页面显示一个必失败按钮；
- 用户会认为系统支持“重新跑一次成功任务”，实际不支持；
- 每次点击都产生无意义 409 和 toast；
- UI 能力提示与 API 合同不一致；
- 以后如果 MaterialBatch / standalone AI 的 retry policy继续分化，单一 status-only eligibility 会继续出错。

**为什么现有测试没发现：**

前端 view test 只按 status 验证 `canRetry`，没有加入 `kind` 维度。

后端 API test 则分别验证不同 task kind 的允许状态。

缺少跨层合同：

`kind + status -> frontend action -> endpoint result`

所以两边各自测试都可以绿色。

**建议最小修复：**

不要放宽后端去允许成功 MaterialBatch 重试来迎合错误按钮。

应让 frontend action eligibility 与 canonical API policy一致：

- `AI_ANNOTATION + SUCCEEDED`：按现有后端合同可显示 retry；
- `MATERIAL_BATCH + SUCCEEDED`：不显示 retry；
- `MATERIAL_BATCH + PARTIAL_SUCCESS`：保留 retry，但要同时修 AUDIT-080 的 phase semantics；
- eligibility helper 明确消费 `task.kind`，不要只看 status。

更稳妥的方向是把 task kind/status action capability 投影为后端字段，前端只消费 capability，但本轮最小修复不需要重构整个 API。

**回归测试建议：**

至少覆盖：

- AI_ANNOTATION + SUCCEEDED -> retry button visible；
- MATERIAL_BATCH + SUCCEEDED -> retry button hidden；
- MATERIAL_BATCH + PARTIAL_SUCCESS -> retry button visible；
- 点击可见按钮时后端不返回“当前状态禁止重试”；
- 列表与详情使用同一 eligibility helper。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-082 — AI 候选分页审核的“采用已选择”会把所有未访问页候选静默拒绝；看第一页即可终结其余 1k/10k 候选审核

**级别：高**  
**模块：AI Annotation / Candidate Review / Pagination / Ground Truth Confirmation / Frontend-Backend Contract**

**现象：**

当前 v60 AI 候选结果后端已经正确提供分页：

`GET /api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates?limit=...&cursor=...`

返回：

- `items`
- `next_cursor`
- `total`

前端审核工作台也按 24 张一页加载：

`review.limit = 24`

`loadReviewPage(offset)`

但“采用已选择”最终提交语义与分页浏览状态冲突。

每次访问一页时，前端只把**当前页**非 failed 候选加入：

`review.decisions`

并默认：

`accepted = item.accepted === false ? false : true`

也就是说第一次打开审核页时，当前首屏最多 24 张会进入 decisions；其它尚未访问的页不会进入 decisions。

用户随后点击：

“采用已选择”

触发：

`completeAiReview60('partial')`

前端构造：

```js
decisions = [...review.decisions]
body = {
  decisions,
  reject_unmentioned: true,
  accept_unmentioned: false,
  commit: true,
  ...
}
```

后端收到后先应用显式 decisions，再执行：

`store.decide_unmentioned(False, exclude=decided_ids)`

而 `CandidateStore.decide_unmentioned()` 是一条**全库 UPDATE**：

```sql
UPDATE candidates
SET accepted = 0
WHERE status IN ('success','empty')
  AND image_id NOT IN (SELECT image_id FROM excluded)
```

所以所有：

- 未访问页；
- 未加载到浏览器；
- 用户从未看到；
- 用户从未作出人工判断；

的 reviewable candidates 会被一次性写成 rejected。

随后 summary 中 `unreviewed=0`，且 `commit=true`，任务继续进入正式 Commit / terminal lifecycle，用户失去继续审核这些未看候选的机会。

**真实可达场景：**

例如一个任务有 1,000 张候选：

1. 用户打开审核；
2. 前端只 GET 第 1 页 24 张；
3. 这 24 张默认进入 decisions=true；
4. 用户查看首屏后点击“采用已选择”；
5. payload 只显式包含这 24 张；
6. 后端把其余约 976 张 reviewable candidate 全部 `accepted=false`；
7. `unreviewed=0`；
8. 任务进入 Commit；
9. 976 张未看候选不再处于待审核状态。

在 10k/20k 场景中后果同样成立，只是被静默拒绝的数量更大。

**为什么是 Bug，而不是“全部拒绝未选项”的正常语义：**

页面同时提供了明确的全局操作：

- “全部拒绝”
- “全部接受”

而中间按钮文案是：

“采用已选择”

用户合理理解是：

“提交我已经选择/审核的候选”。

分页 UI 又明确显示：

- 当前页；
- 上一页 / 下一页；
- “本页全选 / 本页全不选”。

在这种交互下，未访问页并不能等同于“用户明确未选择”。

当前实现把：

**not loaded / not reviewed**

错误折叠成：

**explicitly rejected**。

这破坏了 AI Candidate → Human Review → Commit 的人工确认语义。

**额外问题：默认第一页本身也被隐式选中：**

`loadReviewPage()` 对每个非 failed item 在没有既有 decision 时默认写入 true。

因此用户甚至不需要逐张点击“采用”；只打开第一页再点“采用已选择”，当前页默认接受、其余所有页默认拒绝。

这与“AI 不得未经人工确认直接进入 Ground Truth”的产品合同非常接近边界风险：至少人工确认范围并没有覆盖被默认接受/拒绝的整批候选。

**影响：**

- 大任务绝大多数候选可在用户未查看时被永久拒绝；
- AI 标注召回率被人为大幅降低；
- 训练 Ground Truth 会缺失本可使用的候选标注；
- 用户以为只提交已选项，实际提交了“全局拒绝其余项”；
- 任务一旦进入 commit/terminal，未审核项无法继续原任务审核；
- 1k/10k/20k 越大，误拒绝比例越高；
- 数据集质量问题可能被误归因于模型“不准/漏检”，实际上是审核 UI 生命周期造成的数据丢失。

**与现有分页设计的关系：**

后端 `read_page()` 本身是正确的，问题不在 cursor pagination。

问题是：

- frontend local decisions 只代表 visited pages；
- backend `reject_unmentioned` 却解释为 entire candidate store；
- 两者 scope 不一致。

这属于典型的“分页 selection scope 与全局 mutation scope 漂移”。

**为什么现有测试没发现：**

现有 CandidateStore tests 可单独证明：

`decide_unmentioned(False)`

能正确拒绝所有未提及项。

前端 review tests则通常验证：

- 可分页；
- 当前页选择；
- accept/reject controls；
- decisions payload。

但缺少真实跨页合同：

- 1000 candidates；
- 只访问第 1 页；
- 点击“采用已选择”；
- 第 2～N 页必须仍是 unreviewed，而不是 rejected。

**建议最小修复：**

不要取消 CandidateStore 分页，也不要把 10k/20k 候选全部塞进浏览器。

应把三种意图明确拆开：

1. **全部接受**
   - 可以继续使用 server-side `accept_unmentioned=true`；
2. **全部拒绝**
   - 可以继续使用 server-side `reject_unmentioned=true`；
3. **采用已选择**
   - 只能提交显式 visited/selected decisions；
   - 未提及候选必须保持 `accepted IS NULL / unreviewed`；
   - `commit` 只能在 `summary.unreviewed == 0` 时真正终结审核；
   - 如果仍有未审核项，应返回当前 summary 并让用户继续分页审核。

如果产品希望支持“采用这些，其他全部拒绝”，必须使用明确文案：

“采用已选择并拒绝其余全部”

并二次确认总数量，不能让“未访问”隐式等于“拒绝”。

同时建议 front-end 不要在首次加载每个候选时自动写 `decision=true`；UI 可视觉预选，但只有用户明确批量/单项动作后才进入显式 decision truth，避免人工确认范围含糊。

**回归测试建议：**

至少覆盖：

- 1,000 candidates，只访问第一页 24 张；
- “采用已选择”后第 25～1000 张仍 `unreviewed`；
- task 仍保持 AWAITING_CONFIRMATION；
- 翻页继续审核后才能最终 commit；
- “全部接受”仍可 server-side 一次接受所有 reviewable；
- “全部拒绝”仍可 server-side 一次拒绝所有 reviewable；
- visited-page explicit reject/accept 精确生效；
- 10k/20k 下不做全量浏览器 hydration。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-083 — AI Candidate 审核首屏虽只取 24 条，但为 label_summary 全量解码整个 CandidateStore；10k/20k 首开仍是 O(N) 热路径

**级别：中～高**  
**模块：AI Annotation / Candidate Review / Pagination / Label Summary / 1k-20k Performance**

**现象：**

v60 Candidate API 表面已经实现正确分页：

`CandidateStore.read_page(cursor, limit)`

当前前端审核工作台固定：

`limit = 24`

所以打开审核时正文只需要 24 个 candidate。

但后端：

`get_annotation_candidates()`

在第一页 `cursor in {None, "", "0"}` 时额外执行：

`store.label_summary()`

而 `label_summary()` 不是 SQL aggregate，也不是维护好的 summary index。

它内部直接：

`for item in self.iter_items()`

`iter_items()` 每次按 200 条分页读取：

`SELECT * FROM candidates WHERE ordinal>? ORDER BY ordinal LIMIT 200`

随后对**全部 Candidate rows**执行 `_decode(row)`，再逐个遍历：

`item["boxes"]`

统计 label / boxes / images。

因此：

**打开第一页 24 张 ≠ 只读取 24 张。**

实际是：

- 24 张用于 page body；
- 再把整个 1k / 10k / 20k CandidateStore 全部读取并 JSON decode 一遍，用来生成 label summary。

**真实首开链：**

前端：

`reviewAiLabel427(id)`

→ `loadReviewPage(0)`

→ `GET .../candidates?limit=24&cursor=0`

后端：

1. `store.read_page(limit=24)`
2. batch hydrate 当前页缺失 material metadata；
3. 因为 cursor=0：
   `response["label_summary"] = store.label_summary()`
4. `label_summary()`
   → `iter_items()`
   → 全 CandidateStore scan + decode；
5. 首屏响应必须等待该全量统计完成后才能返回。

所以 Candidate pagination 只限制了返回 body，不限制首屏服务器 work。

**提交审核时还有第二轮全量扫描：**

当 decision request 需要正常 label revalidation 时：

`_decide_annotation_candidates()`

会调用：

`store.remap_labels(mapping, label_ids)`

即使 mapping 为空，只要不是“纯全部拒绝且无 mapping”的特殊分支，它仍会：

- BEGIN IMMEDIATE；
- 按 200 条遍历全部 success/empty candidate；
- decode 每行 boxes；
- 校验 label/class_id；
- 必要时写回。

随后 response/confirmation 路径又会调用 `store.label_summary()`。

因此大 CandidateStore 的一次人工审核可能形成多次 O(N) candidate decode。

**为什么是性能 Bug / 技术债：**

CandidateStore 已经有：

- SQLite durable store；
- ordinal pagination；
- `boxes_count`；
- `summary()` 的 SQL GROUP BY；

说明当前设计本身已经在往 bounded/indexed review truth 收口。

但 `label_summary()` 仍沿用“扫描所有 item JSON”的计算方式，把 20k 数据规模成本重新塞回首屏。

这与 AUDIT-069 不同：

- AUDIT-069：打开 AI Create 时全量 hydrate 项目 Material；
- AUDIT-083：AI generation 完成后，打开 Candidate Review 首屏时全量扫描 CandidateStore。

两个生命周期阶段、存储 owner、修复位置均不同。

**影响：**

- 10k/20k AI 候选任务审核弹窗首开明显变慢；
- SQLite 需要多轮 200-row scan；
- 每行 boxes JSON 都被 decode；
- 大量检测框时 CPU 与内存分配成本进一步放大；
- 用户只想看第一页也要支付全任务统计成本；
- 多次关闭/重开 review 会重复扫描；
- 决策提交阶段还可能再次全量 revalidation + label summary；
- AI generation 已后台完成，但人工审核首屏仍可能表现为“卡”。

**为什么现有测试没发现：**

当前 tests 主要验证：

- CandidateStore 分页正确；
- page limit/cursor；
- label_summary 内容正确；
- commit/review semantics。

但缺少：

- 20,000 candidates；
- 首屏 `GET candidates?limit=24&cursor=0`；
- candidate decode / row scan count 上限；
- label summary 是否通过持久化 aggregate/index 获取；

的规模合同。

所以“返回只有 24 条”会让分页测试绿色，但内部仍扫描 20k。

**建议最小修复：**

不要取消 CandidateStore，也不要把 label mapping summary 挪到浏览器全量计算。

继续以 CandidateStore 为唯一候选 truth，增加**同库内的增量 summary/index**：

1. Candidate append/update 时维护：
   - label → boxes count；
   - label → image count；
   - 必要的 candidate revision；
2. `label_summary()` 直接读取 aggregate table，不再 decode 全 candidates；
3. edit/remap 时在同一 SQLite transaction 更新 aggregate，保证 summary 与 candidate truth 一致；
4. 如果不想新增 aggregate table，至少建立一次 generation-finish summary artifact，并用 revision 校验失效，而不是每次首屏重算；
5. 正式 Commit 前全量 label revalidation 可以保留其安全语义，但它应属于 mutation/finalization 路径，不应污染只读首屏 GET；
6. 规模测试应明确首屏读取量与 candidate total 解耦。

**回归测试建议：**

至少覆盖：

- 20,000 candidates + limit=24 首屏；
- API response body仍只有 24；
- label summary准确；
- 首屏不得调用 `iter_items()` 全量 decode；
- edit/remap 后 aggregate summary同步正确；
- reopen review 不重复扫描 20k；
- final commit 的 label revalidation safety 不被削弱。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-084 — MaterialBatch DELETE_SOURCE 的 Training fence 是单向 TOCTOU；新训练可在检查后创建，源文件先被删、后续索引删除才被阻止

**级别：高**  
**模块：MaterialBatch / DELETE_SOURCE / Training Prepare / Lifecycle Fence / Physical Storage**

**现象：**

canonical MaterialBatch 删除已经比旧 v46/v47 旁路安全：创建 DELETE_INDEX / DELETE_SOURCE 时会调用：

`_assert_not_referenced_by_active_training(...)`

Worker 每批处理前也再次检查活动 `TaskKind.TRAINING`。

但当前 fence 只有：

**删除方查询“现在是否已经有训练引用”**

训练创建方并不会反向查询：

**这些素材是否正在被 DELETE_INDEX / DELETE_SOURCE task 占用。**

两边也没有共享 material-lifecycle lock / deletion reservation。

因此这是一个典型 check-then-act TOCTOU。

**DELETE_SOURCE 的真实危险顺序：**

MaterialBatch worker：

1. `manifest.rows()` 取本批素材；
2. `_assert_not_referenced_by_active_training(project, ids, ...)`
3. 当时没有 Training → 检查通过；
4. `manifest.transition(ids, "running")`
5. 进入 `_delete_sources(...)`
6. 对每个素材调用远端/本地：
   `provider.delete(object_key)`
7. 标记：
   `source_deleted=1`
8. 最后才调用：
   `_delete_index_rows(...)`
9. `_delete_index_rows()` 对每个 image 再次调用 active-training fence；
10. 才删除 AnnotationRepository / MaterialRepository identity。

问题在第 2 与第 6 步之间。

**训练创建是可并发进入的：**

当前 `_enqueue_explicit_training()`：

- 解析 split；
- 构造 `requested_split.train_image_ids/test_image_ids`；
- 直接建立 `TaskKind.TRAINING(QUEUED)`；
- 再建立 `TRAINING_PREPARE`；

但没有查询 active MaterialBatch DELETE task，也没有 acquisition/reservation 与删除方互斥。

因此可达时序是：

A. DELETE_SOURCE batch-level fence 通过；  
B. 用户在这之后提交 Training，Training task 成功进入 QUEUED/PREPARING；  
C. DELETE_SOURCE 执行 `provider.delete(object_key)`，物理源文件被删除；  
D. 删除方随后进入 `_delete_index_rows()`；  
E. 第二次 Training fence 此时终于看见 B 创建的 TRAINING；  
F. index/annotation delete 被拒绝；  
G. MaterialRepository 记录仍存在，但其 source object 已经不存在；  
H. Training PREPARE / 后续训练仍引用这条素材。

这不是理论上的“最后一条 SQL 竞态”：`provider.delete()` 可能是 OSS / 网络存储 I/O，批级检查到物理删除之间的窗口可以明显放大。

**失败后的状态尤其危险：**

当 `_delete_index_rows()` 因新 Training reference 抛错时，外层会把 deletable rows 标为 failed。

但此前：

- 物理 source object 已经删除；
- `selection.source_deleted=1` 已持久化；
- MaterialRepository row 仍存在；
- AnnotationRepository 也仍可能存在；
- Training task 已经是 canonical active truth。

于是系统会出现：

**索引/GT 看起来还在，真实文件已经不在。**

这会破坏后续：

- Training input source availability；
- 质量检查；
- 图片预览；
- 再扫描/重试；
- source availability truth。

**DELETE_INDEX 也存在较小 TOCTOU：**

DELETE_INDEX 在 batch-level fence 后，`_delete_index_rows()` 每 image 再检查一次，所以窗口更小。

但 check 与 `prepare_delete/finalize_delete/materials.remove_many` 仍不在与 Training admission 共享的事务/fence 中。

核心根因仍是：

**删除 owner 与训练 admission owner 没有双向 material lifecycle reservation。**

**与现有 AUDIT 的区别：**

- AUDIT-017：旧 image delete / v46 deletion 绕过 canonical MaterialBatch 与 active Training fence；
- AUDIT-019：Dataset delete 可破坏 PREPARING Training；
- AUDIT-084：即使走 canonical MaterialBatch DELETE_SOURCE，现有 active-Training check 仍存在并发竞态，而且会出现“source 已删、index 因新训练而保留”的半删除状态。

所以不能用“已经有 active training check”判定该链闭环。

**影响：**

- 训练创建成功后，素材物理文件仍可能被并发删除；
- Material/Annotation truth 与真实 source object 分裂；
- TRAINING_PREPARE 或真正训练阶段可能因源文件不存在失败；
- DELETE_SOURCE task 自身可能 PARTIAL/FAILED，但不可逆 source deletion 已发生；
- 重试需要依赖“object missing after previous attempt”恢复逻辑，但无法恢复被训练需要的原文件；
- OSS / 远程 source 的删除延迟会扩大竞态窗口；
- 用户层面表现可能是“训练刚创建成功，稍后突然数据源丢失”。

**为什么现有测试没发现：**

当前删除测试主要覆盖：

- 删除前已有 active Training → 409；
- source delete retry / missing object 幂等；
- shared object protection；
- annotation/material two-phase delete；
- worker cancellation/recovery。

缺少并发合同：

1. DELETE_SOURCE 通过第一次 Training fence；
2. 暂停在 provider.delete 前；
3. 并发创建 Training；
4. 恢复 delete；
5. 验证源文件不能被删，或者 Training admission 必须被拒绝/等待。

**建议最小修复：**

不要再加第三套 Material owner。

需要建立一个**双向 lifecycle fence**，可复用现有 Durable Task truth：

1. DELETE_INDEX / DELETE_SOURCE publish 后，对 frozen selection 建立 durable deletion reservation；
2. Training admission 在创建 TRAINING task 前，检查其 requested image IDs 是否命中 active deletion reservation；
3. 如果命中：
   - 409 明确提示素材正在删除；或
   - 等待删除终态后重新解析 selection；
4. 删除 Worker 在不可逆 `provider.delete()` 前必须在同一 canonical fence 下确认没有 Training reservation；
5. Training task 一旦 admission 成功，对素材引用也必须让删除方稳定可见，直到 Training terminal / freeze contract允许释放；
6. 不要依赖“多检查几次”缩小窗口；必须让 check + ownership acquisition 具备原子/可串行化语义。

如果暂时无法引入 material-level reservation table，至少应先让 Training admission 查询 active DELETE MaterialBatch selection.sqlite3，并在删除任务 active 时 fail closed；但长期仍需解决 check-to-provider.delete 的原子性。

**回归测试建议：**

至少覆盖：

- DELETE_SOURCE fence pass 后并发 Training admission；
- Training 创建成功则 provider.delete 必须不得发生；
- provider delete ownership已获得时，新 Training admission必须被拒绝；
- DELETE_INDEX 同样不能与新 Training freeze交叉；
- source_deleted=1 时不能留下 active Training reference；
- OSS provider 慢调用下仍保持合同；
- cancel/retry 不遗留永久 deletion reservation。

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

### Service Node 生命周期

已确认的安全部分：

- legacy/local `worker_instances` 仍存活时会阻止节点 DELETE；
- 节点只是 disabled、但实体仍存在时，已经进入 RUNNING 的 Agent execution 仍允许 heartbeat / logs / result upload / finalization / finish。

后续审计又确认两条 DELETE 缺口：

- **AUDIT-076**：QUEUED + ASSIGNED/CLAIMED 时 DELETE 不检查 assignment，可留下 dangling pre-start binding；
- **AUDIT-077**：RUNNING Agent task 使用 `worker_id=agent:<node_id>`，不在 `worker_instances` 中，DELETE 的 active-task 查询无法识别，可直接删除正在执行任务的节点。

因此 Service Node DELETE 当前不能再视为安全闭环。

节点停用导致 pre-start assignment 卡住的问题仍单独登记为 AUDIT-015 / AUDIT-060。

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
- 确认后从 `AUDIT-052` 起继续编号；
- 如果后续证据推翻已登记项，必须像 AUDIT-012 一样显式撤销；
- 当前仍以审计为主，不要直接大改生产代码。
