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
- 确认后从 `AUDIT-052` 起继续编号；
- 如果后续证据推翻已登记项，必须像 AUDIT-012 一样显式撤销；
- 当前仍以审计为主，不要直接大改生产代码。
