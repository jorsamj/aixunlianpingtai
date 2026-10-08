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


#### AUDIT-066 补充证据 — canonical v53 bootstrap 同样把全量 Training history scan 放进首屏读取链

后续继续复核当前最终首屏 owner 时确认：

`static/app.js -> loadCore412()`
→ `GET /api/v53/bootstrap/snapshot`
→ 命中 bootstrap 内存 snapshot 后仍调用 `_v53_snapshot_with_live_jobs()`
→ `_v53_live_jobs(project_id)`
→ `sync_jobs_index(project_id)`。

因此 AUDIT-066 不只影响训练任务页 `/api/projects/{project_id}/jobs`：当前 canonical 首屏 snapshot 为了覆盖 live Training 状态，也会执行同一个无界 `jobs/*/job.json` 历史扫描。

这意味着 1k / 10k / 20k Training history 会拖慢应用首次 `loadCore412()`、authoritative core refresh 与 bootstrap snapshot 的 live-jobs overlay。

Material/Annotation summary 在 v53 已正确使用 repository summary，没有重新全量 hydrate 素材；真正应修的是 AUDIT-066 已登记的 Training history read model。后续修复 `sync_jobs_index()` 时，必须同时让 `/jobs` 与 v53 bootstrap 复用同一个 bounded/incremental live Training projection，不能只优化训练任务页 endpoint。

该证据并入 AUDIT-066，不新增独立 AUDIT 编号。

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


### AUDIT-085 — 标签统一 REMAP 与 Training Prepare 没有整任务一致性 fence；训练可冻结“半旧标签、半新标签”Snapshot，甚至把已 remap 框投影成负样本

**级别：高**  
**模块：Label Unification / AnnotationRepository / Training Prepare / Snapshot / Training Accuracy**

**现象：**

当前标签统一：

`REMAP_ANNOTATION_LABELS`

是 Durable MaterialBatch，处理大范围数据时按：

`REMAP_BATCH_SIZE = 100`

逐批执行。

每一批内部：

`AnnotationRepository.remap_labels_if_digests(...)`

会：

- 获取 `label_governance_fence(project_path)`；
- 对该批 Annotation SQLite 执行 `BEGIN IMMEDIATE`；
- 原子更新这一批 100 张的 boxes/scope；
- COMMIT；
- 释放 governance fence；
- MaterialRepository projection 随后更新；
- 再进入下一批。

因此当前合同是：

**单个 100 张批次原子，但整个 1k/10k/20k 标签统一任务不是一个原子事务。**

已处理批次的正式 Annotation 真相会在任务尚未结束时对其他读者可见。

与此同时，来源标签只有在整个 remap：

- 所有选中素材处理完成；
- 没有 failed；
- AnnotationRepository / MaterialRepository 均确认没有来源引用；

之后才由：

`_retire_merged_source_labels()`

写成：

- `status = merged`
- `merged_into = target`

所以 remap 进行中，来源标签和目标标签通常都仍处于 active governance。

**Training Prepare 没有和 remap 共用整任务 fence：**

`TrainingPrepareHandler._freeze_request_contract()`

当前顺序：

1. `resolve_training_selection(project, split)`
2. `resolve_training_label_contract(...)`
3. `project_training_rows(...)`
4. `freeze_training_inputs(...)`
5. 写 `input-freeze.json`

其中：

`resolve_training_selection()`
→ `_selected_project_images()`

读取素材时：

- MaterialRepository 按 500 张一批 `get_many`；
- AnnotationRepository 又按 500 张一批 `get_many`；
- 没有项目级 read transaction；
- 没有 `label_governance_fence`；
- 没有“读取前 annotation revision / 读取后 revision 一致”校验；
- 也没有查询 active `REMAP_ANNOTATION_LABELS` MaterialBatch。

因此 Training Prepare 可以在 remap 第 N 批和第 N+1 批之间运行，并冻结当前可见的中间状态。

**真实可达场景：**

例如项目中：

- 10,000 张“抽烟”标注；
- 用户正在统一：
  `smoke_old -> smoking`
- remap 已处理 4,000 张，剩余 6,000 张尚未处理。

此时开始 Training Prepare。

AnnotationRepository 对 Training 的读取可能看到：

- 4,000 张已经是 `smoking`；
- 6,000 张仍是 `smoke_old`。

由于来源标签尚未退役，当前 label governance 同时认为：

- `smoke_old` active；
- `smoking` active。

Training 不会把这识别为“同一次统一任务的中间态”。

**更严重的是训练投影行为：**

`project_training_rows()`

只保留：

`effective_label_codes`

中的 boxes。

其它 label box 会进入：

`excluded_boxes`

如果一张 annotated 图片只剩 excluded boxes，代码会把本任务投影改成：

- `annotation_state = confirmed_empty`
- `boxes = []`
- `negative_origin = redacted_unselected_labels`

因此有三种危险结果：

1. **训练任务仍只选择旧标签 `smoke_old`**
   - 已 remap 为 `smoking` 的 4,000 张正样本不再属于 allowed code；
   - 这些目标框被排除；
   - 部分图片可被投影为 task-local negative；
   - 同一语义的大量正样本被错误变成负样本/无目标样本。

2. **训练任务只选择新标签 `smoking`**
   - 尚未 remap 的 6,000 张 `smoke_old` 框被排除；
   - 同样造成正样本丢失/负样本污染。

3. **旧标签和新标签都被选择**
   - 同一现实语义在本次 Snapshot 中暂时变成两个训练 class；
   - 模型会把“抽烟”学成两个类别，正是标签统一原本要消除的问题。

**为什么 Snapshot 自身不能自愈：**

一旦 `freeze_training_inputs()` 写出：

- `input_freeze_id`
- `snapshot_id`
- `dataset_revision_id`
- frozen images / boxes / label schema

后续 Training 会以这份 freeze 作为 durable truth。

即使 remap 随后全部完成并将 `smoke_old -> smoking` 正式退役，已经冻结的 Training Snapshot 不会自动重建。

因此这是“稳定冻结了一个业务中间态”，不是 transient UI 闪烁。

**为什么现有 digest / CAS 也不能防住：**

remap 自己有：

- source_digest；
- result_digest；
- `ANNOTATION_CHANGED_DURING_REMAP`；
- per-image CAS。

这些保护的是：

**remap 不覆盖并发 Annotation 写入。**

Training freeze 只是只读，不会改变 annotation digest，因此不会触发 remap CAS 冲突。

反过来 Training 也没有记录“我读的 10k AnnotationRepository 必须处于同一 repository revision”。

所以双方各自局部一致，但跨 owner 的 Snapshot 一致性没有建立。

**与已有 AUDIT 的区别：**

- AUDIT-031：标签 disable 会破坏 PREPARING inherited training label contract；
- AUDIT-032：canonical label code rename 破坏历史 lineage；
- AUDIT-059：label-unify recovery / duplicate remap task；
- AUDIT-085：**正在执行中的合法 remap 与 Training Prepare 并发，Training 冻结半完成标签变换的 Annotation truth。**

即使 031/032/059 全部修复，本问题仍存在。

**影响：**

- 同一语义被训练成两个 class；
- 正样本被过滤为 excluded boxes；
- 甚至被投影成 task-local confirmed_empty，直接污染正负样本；
- mAP / precision / recall 可能异常下降；
- 用户刚完成标签统一后看到的训练成果可能仍包含旧标签污染；
- Snapshot/dataset revision 看起来合法、可复现，但其业务语义来自中间态；
- 数据量越大、remap 时间越长，竞态窗口越大；
- 10k/20k 标签统一时尤其容易在“后台运行期间”创建训练任务触发。

**为什么现有测试没发现：**

现有测试分别保护：

- remap 100/500 批处理、digest CAS、retirement；
- Training label contract；
- Training input freeze；
- Snapshot reproducibility。

缺少跨 owner 并发测试：

1. 10k Annotation 中 remap 完成前 4k；
2. 暂停 remap；
3. 运行 Training Prepare；
4. 再继续 remap；
5. 断言 Training 不允许冻结混合 source/target truth。

**建议最小修复：**

不要把整个 20k remap 放进一个长 SQLite transaction，也不要新增第二 Annotation owner。

优先建立可恢复、可观测的 project-level label mutation fence：

1. `REMAP_ANNOTATION_LABELS` publish/run 时登记 active label-governance mutation：
   - project_id；
   - source labels；
   - target labels；
   - annotation revision / mutation generation；
2. Training Prepare 在冻结 label contract / Annotation truth 前：
   - 检查是否存在与所选素材/标签相关的 active remap；
   - 命中时 fail closed 或等待该 Durable Task terminal；
3. Training freeze 至少记录：
   - annotation repository revision；
   - label governance revision/generation；
4. 完成 500-chunk/多次读取后再次校验 revision：
   - 若期间发生变化则丢弃本次读取并重试；
   - 不能把跨 revision 的 rows 写进同一 Snapshot；
5. remap terminal 后再允许新的 Training Prepare 使用已经完成的 canonical merged label truth。

如果实现 revision-stable read，则必须同时覆盖：

- AnnotationRepository revision；
- label metadata/governance revision；

只检查其中一个仍可能得到 boxes 与 label schema 不一致。

**回归测试建议：**

至少覆盖：

- 10k source label，remap 40% 时并发 Training Prepare；
- Prepare 必须等待/409/重试，不能生成 mixed Snapshot；
- remap 完成后 Training Snapshot 只包含 target label；
- 不出现 source+target 两个 training class；
- 不把已 remap 正样本投影为 task-local negative；
- revision 在 Training 分段读取期间变化时必须检测并重新读取；
- remap FAILED/PARTIAL_SUCCESS 时 Training 必须明确 fail closed，不能猜测混合语义。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-086 — Cleaning confirm 在删除失败后仍把失败素材标成 processed/cleaned；用户明确要淘汰的坏图会被重新视为“已清洗可用”

**级别：高**  
**模块：Cleaning / Confirm / Material Lifecycle / Training Candidate Semantics**

**现象：**

当前 canonical Cleaning task 完成扫描后，用户通过：

`POST /api/v47/projects/{project_id}/clean-tasks/{task_id}/confirm`

确认清洗结果，并可提交：

`delete_ids`

删除被判定为重复、模糊或其它不希望保留的素材。

接口首先调用兼容删除 owner：

`v46_batch_delete_images(...)`

它可能返回：

- `deleted_images`
- `failed_items`

例如：

- 本地/远端 source 删除失败；
- 文件系统权限错误；
- source provider 临时错误；
- 标注文件删除失败。

这一部分会正确让响应最终：

`ok = not failed_items`

但是接口**不会在 failed_items 非空时停止 clean confirmation**。

后续它直接读取整个 Cleaning task 的 frozen selection：

`wanted = set(_v47_frozen_clean_selection_ids(task_id))`

然后重新查询所有当前仍存在于 MaterialRepository 的 `wanted`：

```python
existing_ids.extend(
    str(row.get('id'))
    for row in materials.get_many(...)
)
processed_ids = list(dict.fromkeys(existing_ids))
```

最后对所有仍存在的 `processed_ids` 统一写入：

```python
{
    'processing_status': 'processed',
    'cleaned_at': cleaned_at,
    'clean_task_id': task_id,
}
```

因此：

**删除失败的 image 因为仍然存在，恰好会进入 processed_ids。**

也就是说，用户明确选择“删除”的坏图：

1. 删除失败；
2. row 仍在 MaterialRepository；
3. 随后被 clean confirm 标成 `processed`；
4. `cleaned_at` 也被写入；
5. API 虽返回 `ok=false`，但数据语义已经被推进成“已清洗完成”。

**为什么会影响训练主流程：**

Training candidate 判定：

`_processed_training_candidate(row)`

当前只要满足任一：

- `processing_status == processed`
- 存在 `cleaned_at`
- `clean_skipped`

就认为该素材已完成处理。

因此一个本应被用户淘汰、但删除失败的 unannotated 素材会从：

“清洗结果中判定要删除”

变成：

“已清洗，可作为训练候选/待标注候选”。

后续用户可能：

- 再对它做 AI 标注；
- 人工标注；
- 选进训练任务；

从而把本应淘汰的低质量/重复/异常图片重新带回数据集主流程。

**真实可达场景：**

例如 Cleaning 扫描 10,000 张：

- 用户选择 500 张重复/模糊图删除；
- 其中 20 张因外部对象存储临时失败未删掉；
- `v46_batch_delete_images` 返回 480 deleted + 20 failed；
- confirm 继续执行；
- 20 张失败图片仍在 MaterialRepository；
- 因此进入 `processed_ids`；
- 被写成：
  `processing_status=processed, cleaned_at=<now>`；
- API 返回 `ok=false`，但这 20 张已经被永久标成“已清洗”。

用户下次打开训练选择器时，不容易再知道它们曾是“删除失败的清洗异常项”。

**为什么与 AUDIT-038 / AUDIT-017 不同：**

AUDIT-038：

- Cleaning confirm 缺少 execution-state guard；
- 运行中/非终态任务也可能被确认。

AUDIT-017：

- v46/image delete 绕过 canonical MaterialBatch deletion owner 与 active Training fence。

AUDIT-086：

- **即使 Cleaning 已正常完成，且删除动作确实尝试执行，删除失败的 item 仍被 confirm 错误推进成 processed/cleaned。**

这是确认结果状态机本身的问题。

**额外审计证据：**

接口已经把：

`delete_failures = len(failed_items)`

写入：

`clean_confirmation.json`

说明系统知道删除存在失败。

但 `processed_ids` 并没有排除：

- `failed_items[].id`
- 用户原始 `delete_ids` 中未成功删除的 IDs。

因此 confirmation artifact 同时可能表达：

- delete_failures > 0
- processed_ids 包含这些失败 ID

形成自相矛盾的 durable truth。

**影响：**

- 用户明确淘汰的坏图被重新标为已清洗；
- 低质量/重复样本可能重新进入 AI 标注、人工标注、训练候选；
- 数据清洗效果被悄悄削弱；
- 训练准确率可能因重复/模糊样本污染下降；
- API 返回失败，但一部分不可逆状态已写入，用户重试时语义更复杂；
- `clean_confirmation.json` 中 failure truth 与 MaterialRepository processed truth 不一致；
- 10k/20k 批量清洗下，只要外部存储偶发失败就容易出现。

**建议最小修复：**

不要新增第二 Cleaning owner。

确认阶段应按 item outcome 分开推进：

1. 成功删除的：
   - 已不存在，无需再标 processed；
2. 用户未选择删除、明确保留的：
   - 才允许写 `processing_status=processed / cleaned_at`；
3. 用户选择删除但删除失败的：
   - 必须保留 non-processed / needs_attention 状态；
   - 至少不能写 `cleaned_at`；
   - confirmation artifact 明确记录 retryable deletion failure；
4. `processed_ids` 应计算为：
   - frozen selection
   - 减去 requested delete_ids
   - 再与当前 MaterialRepository existence 做交集；
5. 删除失败项应允许后续只重试 deletion，而不是重新扫描整个 Cleaning task。

同时应与 AUDIT-017 收口到 canonical deletion owner，避免继续让 Cleaning confirm直接调用旧 v46 mutation。

**回归测试建议：**

至少覆盖：

- 10 个 delete_ids，8 成功、2 失败；
- 2 个失败 item 仍存在，但不得出现在 processed_ids；
- 失败 item 不得获得 `processing_status=processed` / `cleaned_at`；
- 未选择删除的保留项正常标 processed；
- clean_confirmation.json 的 delete_failures 与 MaterialRepository truth一致；
- failed deletion retry 成功后才完成对应生命周期；
- Training Picker 不把 deletion-failed item 当 clean-ready。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-087 — 停止 PREPARING Training 只取消父 TRAINING，不取消 TRAINING_PREPARE 子任务；用户已停止后仍可继续构建/归档/上传大批训练输入

**级别：中～高**  
**模块：Training Lifecycle / TRAINING_PREPARE / Cancellation / Remote Staging / Resource Consumption**

**现象：**

当前 Durable Training 创建时会建立两个任务：

1. 父任务：
   `TaskKind.TRAINING`
2. 输入准备子任务：
   `TaskKind.TRAINING_PREPARE`

子任务 ID 固定：

`trainprep_{training_task_id}`

父任务 payload 也明确记录：

`training_prepare_task_id`

训练创建后，父 TRAINING 先保持：

- status = QUEUED
- stage = training_input_pending
- required_capabilities = training.input.ready

直到 PREPARE 子任务完成输入冻结/构建后，才通过：

`activate_prepared_training()`

把父任务释放到真正训练队列。

**当前停止入口只取消父任务：**

前端 TrainingTaskRuntime 的 Stop：

`POST /api/v48/projects/{project_id}/jobs/{job_id}/stop`

后端 `v48_stop_job()` 对 Durable Training 只执行：

`shared_task_repository().request_cancel(job_id)`

即只取消父 `TRAINING`。

它没有：

- 读取 `training_prepare_task_id`；
- 查找对应 `TRAINING_PREPARE`；
- 对 PREPARE 子任务执行 request_cancel；
- 建立 parent-child cancellation propagation。

父任务仍在 QUEUED 时，`request_cancel()` 会立即把它改成：

`CANCELLED`

但 PREPARE 子任务如果已 RUNNING，会继续：

`RUNNING`

自己的 lease / heartbeat 完全不受父任务取消影响。

**安全边界：父任务不会被重新激活**

这一点当前实现是正确的，不应误报。

`TrainingPrepareHandler._target()`

会检查父任务：

- CANCELLED → `InterruptedError`
- 非 QUEUED → fail closed

最终：

`TaskRepository.activate_prepared_training()`

也在 `BEGIN IMMEDIATE` 事务内明确要求：

`current.status is TaskStatus.QUEUED`

因此 PREPARE 子任务不能把已取消父 TRAINING 重新变回可执行状态。

**真正的问题是：取消传播太晚，资源工作继续发生。**

PREPARE handler 并不是所有重型阶段都持续检查父任务。

当前 `_prepare_bundle()` 在“逐图片 source materialize”时会对每张调用：

`self._target(context, training_task.task_id)`

所以这一阶段取消响应相对及时。

但之后多个重型阶段没有父任务取消检查。

**本地训练路径：**

素材读取完成后：

1. `materialize_portable_dataset(...)`
   - 可处理 1k / 10k / 20k 图片；
   - progress callback 只 heartbeat PREPARE 子任务；
   - 不调用 `_target()` 检查父 TRAINING；
2. 写：
   - snapshot.json
   - dataset-revision.json
   - prepared-input.json
3. `_resolve_local_resources(...)`
4. 把父任务 payload 写成：
   `training_input_state = READY`
5. 最后才调用：
   `activate_prepared_training()`

如果用户在第 1～4 步期间停止父任务：

- 页面中的父 TRAINING 已经是 CANCELLED / stopped；
- PREPARE 子任务仍继续 CPU / 磁盘工作；
- 甚至可以把父 payload 写成 READY；
- 直到 `activate_prepared_training()` 才因为父任务不再 QUEUED 而失败。

父 canonical status 最终仍是 CANCELLED，但 artifact/payload lifecycle 已经继续向前推进。

**远程训练路径窗口更明显：**

bundle 准备完成后：

1. PREPARE 调一次：
   `self._target(...)`
2. `create_training_bundle_archive(...)`
3. `stage_training_bundle_object(...)`
   - 上传训练 ZIP 到 OSS/S3/MinIO
4. `_prepare_base_model(...)`
   - 可能再次读取/上传基础模型
5. 之后才再次：
   `self._target(...)`

如果用户在第 1 次检查之后停止训练：

- 父任务立即 CANCELLED；
- PREPARE 子任务仍继续压缩 bundle；
- 继续产生网络上传；
- 继续准备/上传 base model；
- 直到第 5 步才发现父任务已取消。

在 10k/20k 图片或慢 OSS/MinIO 下，这个窗口可能很长。

**Worker 本身也不会把父取消解释成子取消：**

Worker Scheduler 只看 PREPARE 子任务自己的状态。

只有当：

`context.task.status == CANCEL_REQUESTED`

时才走：

`_finish_cancel_if_safe()`

父 TRAINING 的 CANCELLED 并不会自动改变子 PREPARE 的状态。

当 PREPARE 之后某次 `_target()` 因父 CANCELLED 抛出 `InterruptedError` 时，由于子任务自己仍是 RUNNING，而不是 CANCEL_REQUESTED，Scheduler 会把这个 `InterruptedError` 当成普通异常：

`_finish_error_or_cancel(... TaskStatus.FAILED ...)`

因此一次正常用户“停止训练”还可能留下：

- 父 TRAINING = CANCELLED
- PREPARE 子任务 = FAILED

而不是 parent/child 一致的 cancelled lifecycle。

**影响：**

- 用户点击“停止”后，服务器 CPU / 磁盘仍可能继续处理大量训练数据；
- 远程训练仍可能继续上传大 ZIP / base model，产生 OSS 流量与 staging 对象；
- PREPARE Worker 槽位继续被占用，影响后续训练创建；
- 父任务页面已经显示停止，但后台仍有真实资源工作，用户感知与执行真相不一致；
- 本地路径可能在取消后继续写 snapshot / dataset revision / READY payload；
- 远程路径可能留下已上传但无人使用的 staging object，虽然后续可由现有 GC 清理，但属于无意义副作用；
- 子任务最终可能 FAILED，而父任务是 CANCELLED，审计与运维状态不一致；
- 20k 数据、慢磁盘、远程对象存储时浪费最明显。

**与已有问题的区别：**

- AUDIT-020：Training 单条 DELETE 会隐式取消 active Training，和批量 DELETE 合同冲突；
- AUDIT-019：Dataset DELETE 可破坏尚未 freeze 的 Training Prepare；
- AUDIT-087：用户明确执行合法 Stop 后，取消只到父 TRAINING，不传播到其输入准备子任务。

这是 parent-child cancellation contract 缺口，不是删除语义或输入依赖变化。

**为什么现有测试没发现：**

当前 tests 已保护：

- parent TRAINING 在 PREPARE 完成前不可被普通 Worker claim；
- prepare 成功后 activate parent；
- parent 已 CANCELLED 时 activate fail closed；
- source materialize 期间检查 parent status。

但缺少：

1. PREPARE 已 RUNNING；
2. 父 Training 被 stop；
3. 子 PREPARE 必须立即进入 CANCEL_REQUESTED/CANCELLED；
4. 后续 bundle/archive/upload 不得继续。

尤其缺少故障注入点：

- portable dataset materialization 中途 cancel；
- ZIP archive 中途 cancel；
- OSS upload 中途 cancel；
- base model staging 中途 cancel。

**建议最小修复：**

不要创建第二套 TrainingPrepare owner。

应把 parent-child cancellation 纳入现有 Training lifecycle service：

1. 停止父 TRAINING 时，如果：
   - `training_input_state == PREPARING`
   - 且 `training_prepare_task_id` 对应子任务仍 active
   - 同一 operation 内对 PREPARE 子任务也执行 request_cancel；
2. PREPARE handler 的长阶段要消费自身 canonical cancellation truth：
   - freeze contract；
   - materialize portable dataset；
   - archive；
   - object upload；
   - base model staging；
3. 对不能立即中断的 provider 上传：
   - 在完成后先检查 cancellation；
   - 不再发布 READY / activate parent；
   - staging 对象交给已有 Remote Staging GC / retirement owner，禁止再造一套清理机制；
4. parent/child race 必须明确：
   - prepare activate 事务先赢 → 父进入真实 Training 队列，再按普通 Training cancel；
   - parent cancel 先赢 → prepare 必须 cancel，不能继续 publish READY；
5. 子任务因父用户取消而退出时应收口为 CANCELLED，而不是 FAILED。

**回归测试建议：**

至少覆盖：

- PREPARE queued 时 stop parent → parent + child 都 CANCELLED；
- PREPARE running/materialize 时 stop → 后续图片停止处理；
- portable dataset materialization 中途 stop；
- remote archive/upload 中途 stop；
- stop 后不得继续上传 base model；
- stop 后父 payload 不得从 PREPARING 被发布为 READY；
- activate 与 cancel 并发只允许一个明确赢家；
- 20k 输入取消后 Worker 槽位可及时释放；
- staging cleanup 继续复用已有 GC owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-088 — UploadTaskCenter 重复维护一套过期 Durable 状态枚举；PARTIAL/BLOCKED/CANCEL_REQUESTED/AWAITING_CONFIRMATION 被错误判定，后台任务可永久停在“进行中”

**级别：中～高**  
**模块：Frontend Runtime / UploadTaskCenter / Durable Task Status / PollRegistry / Storage Import**

**现象：**

项目已经有 canonical 前端任务真相模块：

`static/modules/task-runtime-truth.js`

其中明确维护：

**ACTIVE：**

- ACCEPTED
- QUEUED
- WAITING_RESOURCE
- PREPARING
- RUNNING
- PAUSING
- PAUSED
- RESUMING
- STOPPING
- CANCEL_REQUESTED
- RETRYING

**TERMINAL / 不再自动运行：**

- AWAITING_CONFIRMATION
- PARTIAL_SUCCESS
- SUCCEEDED
- CANCELLED
- FAILED
- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE

并提供：

- `canonicalTaskStatus()`
- `isCanonicalTaskActive()`
- `isCanonicalTaskTerminal()`

StorageImportProgressRuntime 自己已经通过：

`task-poller.js -> task-runtime-truth.js`

消费这套 canonical truth。

但：

`static/modules/upload-task-center.js`

没有复用它。

该文件重新手写第二套状态 owner：

```js
const ACTIVE_STATUSES = new Set([
  'UPLOADING','MERGING','VALIDATING','SELECTING',
  'QUEUED','WAITING','WAITING_RESOURCE','RUNNING',
  'SCANNING','EXTRACTING','MAPPING_LABELS',
  'WRITING_ANNOTATIONS','INDEXING','FINALIZING'
]);

const TERMINAL_STATUSES = new Set([
  'DONE','SUCCEEDED','COMPLETED','FINISHED',
  'FAILED','CANCELLED','CANCELED','INTERRUPTED'
]);
```

这套列表已经与 canonical Durable Task 状态漂移。

**明确缺失：**

ACTIVE 漏掉：

- ACCEPTED
- PREPARING
- PAUSING
- PAUSED
- RESUMING
- STOPPING
- CANCEL_REQUESTED
- RETRYING

TERMINAL/结果态漏掉：

- AWAITING_CONFIRMATION
- PARTIAL_SUCCESS
- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE

**真实后果 1：PARTIAL_SUCCESS / BLOCKED_* 变成“既不 active，也不 terminal”**

UploadTaskCenter：

`isUploadTaskActive()`

只查自己的 ACTIVE_STATUSES。

`clearCompletedUploadTasks()`

只查自己的 TERMINAL_STATUSES。

所以当后台 Storage Import / ZIP / Durable upload row 刷到：

- PARTIAL_SUCCESS
- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE

时：

1. `isUploadTaskActive(row) == false`
2. Task Center 不再 poll；
3. `TERMINAL_STATUSES.has(status) == false`
4. “清空已结束”也不会删除它；
5. `statusPresentation()` 又没有这些状态映射；
6. 落入默认：
   `{label:'进行中', cls:'run'}`

于是后端明明已经：

- 部分完成；或
- 因环境/硬件阻塞终止；

前端任务中心却显示：

**“进行中”**

并且永远不再刷新。

Storage Import 后端已经真实使用 `PARTIAL_SUCCESS`：confirm 路径甚至明确把：

`TaskStatus.PARTIAL_SUCCESS`

列入可重复确认状态，所以这不是理论枚举。

Agent/remote Durable task 也可以合法进入 BLOCKED_BY_ENVIRONMENT / BLOCKED_BY_HARDWARE。

**真实后果 2：CANCEL_REQUESTED 会让后台轮询在取消过程中提前停掉**

canonical truth 明确把：

`CANCEL_REQUESTED`

视为 active。

这是正确的，因为 Worker 还需要：

- 终止进程/远端操作；
- 清理资源；
- 最终发布 CANCELLED。

但 UploadTaskCenter 的 ACTIVE_STATUSES 没有 CANCEL_REQUESTED。

如果某个已 handoff 到 Task Center 的 Durable task：

RUNNING  
→ CANCEL_REQUESTED

Task Center 一次 poll 取得 CANCEL_REQUESTED 后：

1. 更新 row；
2. 下一次 `arm()` 执行：
   `rows.some(isUploadTaskActive(...))`
3. 返回 false；
4. PollRegistry 不再启动下一次查询；
5. 后端随后发布的 CANCELLED 永远不会被该 Task Center 观察到。

而 CANCEL_REQUESTED 也不在 TERMINAL_STATUSES，所以 row：

- 不可清除；
- 默认显示“进行中”。

形成典型的“取消中状态让前端自己停止观察取消完成”的生命周期错误。

**真实后果 3：AWAITING_CONFIRMATION 没有特殊语义**

Storage Import 的合法流程：

RUNNING  
→ AWAITING_CONFIRMATION

focused runtime 使用 canonical truth，会正确停止常规 active polling，并显示：

“扫描完成，等待确认建立素材索引”。

但 UploadTaskCenter 自己：

- 不把 AWAITING_CONFIRMATION 当 active；
- 不把它当 terminal；
- `statusPresentation()` 也没有“待确认”；
- 默认显示“进行中”。

再叠加 AUDIT-067 中 Storage Import row 没有 reopen action，用户会看到一个语义错误且不可进入确认流程的 task center row。

**为什么是“重复 Owner”问题：**

这里不是单纯少写几个字符串。

项目已经有：

`task-runtime-truth.js`

作为 canonical browser-side task status owner。

UploadTaskCenter 又自己复制：

- active status set；
- terminal status set；
- alias；
- status presentation；

形成第二套 task-state truth。

后端状态扩展后，canonical module 已更新，而 UploadTaskCenter 没同步，最终漂移。

这正是当前审计目标中的：

**状态枚举漂移 / 重复 Owner / Runtime 不一致。**

**影响：**

- PARTIAL_SUCCESS 被显示为“进行中”；
- BLOCKED_* 被显示为“进行中”；
- CANCEL_REQUESTED 后 Task Center 可永久停止轮询，错过 CANCELLED；
- AWAITING_CONFIRMATION 状态展示错误；
- “清空已结束”无法清理部分合法终态；
- 本地 localStorage 会长期保留 zombie rows；
- MAX_ROWS=20 时这些 zombie row 还会挤掉其它任务，加重 AUDIT-067 的 active task 可发现性问题；
- 同一个 Durable task 在 focused modal 与 background Task Center 中可呈现不同状态。

**为什么现有测试没发现：**

UploadTaskCenter tests 主要覆盖：

- RUNNING/QUEUED 正常 polling；
- SUCCEEDED/FAILED/CANCELLED clear；
- pollOwner yield；
- ZIP reopen；
- localStorage persistence。

缺少 canonical status matrix contract：

`TaskStatus enum -> task-runtime-truth -> UploadTaskCenter`

尤其没有覆盖：

- CANCEL_REQUESTED -> CANCELLED 连续轮询；
- PARTIAL_SUCCESS；
- BLOCKED_BY_ENVIRONMENT；
- BLOCKED_BY_HARDWARE；
- AWAITING_CONFIRMATION。

**建议最小修复：**

不要继续补第三份字符串表。

UploadTaskCenter 应直接复用：

- `canonicalTaskStatus`
- `isCanonicalTaskActive`
- `isCanonicalTaskTerminal`

来自：

`task-runtime-truth.js`

同时仅保留上传阶段特有的 browser-only 状态：

- UPLOADING
- MERGING
- VALIDATING
- INTERRUPTED
- resumeRequired 等

这些状态应作为 UploadTaskCenter 自己的 transfer state，而不是复制 Durable Task state machine。

展示层也应明确：

- AWAITING_CONFIRMATION → 待确认
- PARTIAL_SUCCESS → 部分完成
- BLOCKED_* → 阻塞/失败类
- CANCEL_REQUESTED → 正在取消

并继续 poll CANCEL_REQUESTED，直到真正 terminal。

**回归测试建议：**

至少建立一张 canonical status contract table：

- QUEUED -> active/poll
- RUNNING -> active/poll
- CANCEL_REQUESTED -> active/poll
- CANCELLED -> terminal/clearable
- PARTIAL_SUCCESS -> terminal/clearable
- BLOCKED_BY_ENVIRONMENT -> terminal/clearable
- BLOCKED_BY_HARDWARE -> terminal/clearable
- AWAITING_CONFIRMATION -> 待确认、不可误显示“进行中”

另覆盖：

RUNNING  
→ CANCEL_REQUESTED  
→ CANCELLED

确保 Task Center 不会在中间状态停止 PollRegistry。

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

### AUDIT-089 — ZIP Import 活动轮询每秒重复全量扫描全部历史 job.json；单次 reconcile 还会调用列表两次，历史增长后形成持续 O(N) I/O / UI 热路径

**级别：中～高**  
**模块：ZIP Import / v19 Import Jobs / PollRegistry / UploadTaskCenter / Performance**

**现象：**

当前 ZIP Import 列表接口：

\`GET /api/v19/projects/{project_id}/import/jobs\`

不是 bounded active truth，也没有 cursor。

后端每次请求都会：

\`v19_import_jobs_dir(project_id).glob("*/job.json")\`

遍历项目下全部 ZIP Import 任务目录，并对每一条历史任务执行：

- \`read_json(job_file, {})\`；
- \`_v19_recover_multipart_finalize(project_id, job)\`；
- \`v19_public_job(...)\`；
- 最后全量排序并返回所有 jobs。

虽然 terminal job 的 \`image_limit\` 已经是 0，避免了图片预览 hydration，但**任务元数据本身仍然是全历史扫描、全历史返回**。

前端 canonical \`zip-import-runtime.js\` 又把该接口放在活动任务的高频 poll 路径上：

\`installZipImportRuntime(..., pollMs=1000)\`

只要：

\`activeZipJobs(jobs).length > 0\`

就会每约 1 秒：

\`arm() -> reconcile('poll')\`

而 \`reconcile()\` 的真实逻辑是：

1. 先 \`listZipJobs(project)\`；
2. 把返回的**全部历史 jobs**逐条 \`publishTaskCenterJob()\`；
3. 执行 \`maybeStart()\` / \`refreshKnown()\`；
4. 对任何非 bootstrap reconcile（包括每次 poll），再次：
   \`listZipJobs(project)\`。

所以有活动 ZIP 任务时，一次 1 秒 poll 最坏会做**两轮完整历史扫描**。

同时第一轮列表返回后，前端还会对每一个历史 job 调：

\`UploadTaskCenterRuntime.upsert(task)\`

而 \`upsert()\` 内部又包含：

- merge；
- sort；
- \`rows.slice(0, MAX_ROWS)\`；
- localStorage persist；
- render；
- PollRegistry re-arm。

因此累计 ZIP 历史越多，不只是服务器 I/O 线性增长，浏览器也会重复对大量早已终态的历史任务执行无意义的 task-center side effects。

**规模影响：**

当项目累计：

- 1k ZIP jobs；
- 10k ZIP jobs；
- 20k ZIP jobs；

即使当前只有 1 个活动导入，前端仍可能每秒触发约两次：

- 全目录 glob；
- 1k/10k/20k 次 job.json 读取；
- multipart finalize recovery 检查；
- public projection；
- 全量 JSON 响应；
- 全量历史 merge；
- 第一轮全量 UploadTaskCenter upsert。

这会形成与“累计历史数量”而不是“当前活动任务数量”绑定的持续热路径。

**与已有问题的区别：**

- AUDIT-051：ZIP 导入完成复核页重新全量 hydrate 10k/20k 素材与标注；
- AUDIT-061：completed multipart session 缺少 GC；
- AUDIT-062：ZIP Import daemon thread 缺少 crash recovery；
- AUDIT-066：Training jobs REST 全量扫描历史 job.json；
- AUDIT-074：v36 Source Import 列表全量历史扫描再截 100。

AUDIT-089 是 **v19 ZIP Import 自己的活动轮询列表路径**：

“只要当前还有一个 active ZIP job，就持续每秒扫描全部 ZIP 历史，并且一次 reconcile 还会 list 两次”。

生命周期 owner、API、前端 poller 都不同，不能并入上述条目。

**影响：**

- ZIP 历史越多，活动导入时 Web API latency 越高；
- 大量小文件读取造成 filesystem metadata / inode I/O 压力；
- 共享 Web 进程被持续占用，拖慢数据集、标签、训练等其它请求；
- 浏览器收到越来越大的 jobs JSON；
- UploadTaskCenter 对全历史逐条 upsert，造成不必要的排序、localStorage 写入和 DOM render；
- 多项目长期运行后，性能会随历史自然退化；
- 20k 历史下即使当前导入很小，也承担历史规模成本。

**为什么现有 CI 没发现：**

当前 ZIP runtime 测试主要验证：

- queue / start disposition；
- multipart upload / resume；
- PollRegistry 单 owner；
- completion side effect；
- browser upload 流程。

没有构造：

- 20,000 terminal ZIP job dirs；
- 1 个 active job；
- 持续 poll；
- 对 \`GET /import/jobs\` 的文件读取次数、返回大小、调用次数做规模约束。

因此功能测试可全绿，但生产历史增长后仍会退化。

**建议最小修复：**

不要新建第二套 ZIP owner。

继续保留 v19 ZIP runtime，但把“active truth”和“terminal history”分离：

1. 后端列表至少改成：
   - active jobs 全量返回；
   - terminal history bounded；
   - terminal history 使用 cursor / next_cursor；
2. 不要在高频 GET 中每次 glob + parse 全历史；
   - 建议 mutation-time 维护轻量 index；
   - 或把 startup/recovery 全量扫描移出高频请求；
3. \`reconcile('poll')\` 一次周期只获取一次 canonical list snapshot；
   - ambiguous/submitted 特例继续使用已有 targeted \`GET /jobs/{id}\`；
   - 不要同一 poll 再做第二次全量 list；
4. UploadTaskCenter 只 publish：
   - active jobs；
   - bounded recent terminal；
   并提供 batch reconcile，避免每个历史 job 单独 persist/render/re-arm；
5. “清空已结束”仍可走现有 terminal bulk delete，不需要靠返回全历史才能工作。

**回归测试建议：**

至少覆盖：

- 20,000 terminal ZIP jobs + 1 active；
- active poll 的后端 job.json read / hydrate 数量有明确上限；
- 一次 poll 不允许两次全量 list；
- active job 始终可见；
- terminal history cursor 可继续查看；
- UploadTaskCenter 单次 reconcile 不对 20k terminal rows 逐条 render/persist；
- 现有 multipart resume、label confirmation、queue ordering、completion 行为保持不变。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-090 — VideoFrameHandler 在最终 MaterialRepository commit 前已逐帧写对象存储与 AnnotationRepository；取消/异常可留下无 Material owner 的孤儿对象与孤儿 Annotation

**级别：高**  
**模块：Video Frames / Durable Task / StorageManager / AnnotationRepository / MaterialRepository / Cancellation Rollback**

**现象：**

当前 canonical Durable 视频切帧已经具备 execution fencing，并且最终 MaterialRepository 使用一次性：

\`materials_repository.upsert_many(records)\`

提交全部帧素材。

但在这次最终 commit 之前，handler 会对每一帧依次先执行持久化副作用：

1. \`manager.upload_object(...)\` 把 JPEG 写入素材存储；
2. 校验 SHA256；
3. \`annotation_repository.upsert(image_id, [], "unannotated")\` 写正式 Annotation Ground Truth；
4. 只把 Material record 暂存在进程内 \`records[]\`；
5. 全部帧循环完成后，才：
   \`materials_repository.upsert_many(records)\`。

也就是说对象存储与 AnnotationRepository 的写入不是和 MaterialRepository commit 同一个事务，也没有 compensating rollback owner。

**真实调用链：**

\`VideoFrameHandler.run()\`

→ \`extract_video(..., resume_existing=True)\`

→ 对 \`extraction.frames\` 循环：

\`manager.upload_object("default_local", object_key, extracted.path)\`

→ \`ensure_active()\`

→ \`annotation_repository.upsert(image_id, [], "unannotated")\`

→ \`records.append(material_record)\`

→ heartbeat

全部循环结束后才：

\`materials_repository.upsert_many(records)\`

→ 写 \`result.json\`

→ checkpoint committed。

如果以下任一事件发生在循环中：

- 用户取消；
- execution lease 丢失；
- 第 N 帧 upload 失败；
- SHA 校验失败；
- AnnotationRepository 写入失败；
- heartbeat/fencing 抛错；
- 进程异常但仍由 Worker 把任务归为失败/取消；

handler 会直接抛出异常。

当前 \`run()\` 没有：

- try/finally rollback；
- 已上传 object_key 集合清理；
- 已创建 Annotation image_id 集合清理；
- staged publish / commit marker；
- Material transaction abort 时的 compensating cleanup。

因此已经完成的前 N-1 帧副作用会保留。

**为什么是数据一致性 Bug：**

正常 Material truth 应当是：

\`MaterialRepository row\`
→ 对应 storage object
→ 对应 AnnotationRepository truth。

当前失败窗口会生成：

- storage object 已存在；
- AnnotationRepository 可能已有 \`unannotated\` row；
- MaterialRepository 不存在该 image_id；
- task 最终为 CANCELLED / FAILED；
- \`result.json\` 也不存在。

这种数据无法通过普通素材列表发现，但会永久占用存储和 Annotation GT 表。

后续 retry 使用确定性：

\`image_id = sha256(task_id:source_frame_index)[:16]\`

以及确定 object_key：

\`uploads/{image_id}.jpg\`

所以重试可能覆盖/复用这些半成品，但**用户不重试时孤儿会永久存在**；并且失败发生在哪一帧决定了残留规模。

**现有测试反而暴露了覆盖缺口：**

\`tests/unit/test_video_commit_fencing.py\`

已有：

\`test_video_commit_stops_before_second_upload_after_cancel\`

它验证：

- 第一次 upload 后触发 cancel；
- 第二次 upload 不会发生；
- MaterialRepository 仍为空；
- result.json 不存在。

但该测试 monkeypatch 的 \`upload_object()\` 只返回 \`ObjectMetadata\`，没有真的写对象，因此没有断言：

“第一次已经上传的对象必须被删除”。

而 cancel 又发生在第一次 upload 返回后紧接着的 \`ensure_active()\`，所以尚未进入 AnnotationRepository.upsert，也没有覆盖：

“已经写入 Annotation 后再取消必须 rollback”。

另一个 stale-execution fencing 测试同样只验证“不继续业务写”，不是“撤销 fencing 前已经完成的持久化副作用”。

所以当前 CI 保护了 **stop further writes**，但没有保护 **rollback earlier writes**。

**与已有 AUDIT-065 的区别：**

AUDIT-065 是终态 Durable Task 的长期 retention / artifact GC：

- 原视频输入；
- frames 目录；
- AI CandidateStore；
- MaterialBatch selection；
- Deployment Test predictions。

AUDIT-090 是**单次 VideoFrameHandler 事务在失败/取消时立即产生的跨 owner 半提交**：

- StorageManager 已写；
- AnnotationRepository 已写；
- MaterialRepository 尚未 commit。

前者是生命周期结束后的 retention policy；后者是业务事务原子性/rollback，不能靠“以后定期 GC”替代。

**影响：**

- 中途取消大型视频切帧后留下大量 orphan JPEG；
- AnnotationRepository 累积没有 Material owner 的 image_id；
- 项目磁盘/对象存储使用量与素材数量不一致；
- integrity/audit 工具可能看到 dangling annotation；
- 后续同 task retry 的结果依赖历史半成品，增加恢复复杂度；
- 若对象存储是 OSS/S3，会产生真实远端孤儿对象和费用；
- 任务 UI 显示“已取消/失败”，但实际业务副作用没有完全撤销。

**建议最小修复：**

不要新增第二套 Material 或 Annotation owner。

保留当前确定性 frame id 和最终 \`MaterialRepository.upsert_many\`，但增加明确的 publish transaction / compensating rollback：

1. 在 handler 内记录本 attempt 新创建的：
   - object_key；
   - image_id；
2. 只有最终 MaterialRepository commit + result.json 成功后才标记 committed；
3. 在 cancel / fencing / exception 且尚未 committed 时：
   - 删除本 attempt 新上传且没有正式 Material owner 的对象；
   - 删除本 attempt 新创建且没有正式 Material owner 的 Annotation；
4. 如果 retry 发现旧 attempt 遗留：
   - 先依据 deterministic id + Material truth 做 recovery；
   - 已有正式 Material 的绝不能误删；
5. rollback 必须 fail-closed：
   - cleanup 失败要记录明确 cleanup error / orphan evidence；
   - 不要把任务伪装成完全干净的 CANCELLED。

更理想的方向是把对象先写 task-scoped staging，再在最终 commit 后 promote；但本轮最小修复不要求重新设计 Storage owner。

**回归测试建议：**

至少增加：

- 第 1 帧真实 upload 后 cancel：object 被删除；
- Annotation upsert 后 cancel：Annotation 被删除；
- 第 N 帧 upload error：前 N-1 个 orphan 全清；
- stale execution / lease lost：已完成副作用 rollback；
- cleanup 只删除“本 attempt 且无 Material owner”的对象；
- retry 后成功时最终 Materials / objects / annotations 1:1；
- 1k 帧取消时 rollback 有 bounded/批量策略，不形成 O(N²)。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-091 — Remote Training 在算法版本 attach 前就正式登记 ModelArtifact；后续标签合同/版本冲突失败可留下“有模型产物、无算法版本”的半提交

**级别：高**  
**模块：Remote Training / ModelArtifact / Algorithm Version / Result Commit / Crash Consistency**

**现象：**

当前远程训练结果的 canonical commit：

\`RemoteExecutionTransportService._commit_training_result()\`

不是“先完整验证，再一次性发布版本与产物”。

真实顺序是：

1. 校验远程 result/model evidence；
2. 下载 primary model 到项目 \`models/\`；
3. 对 best / last 等模型逐个调用：
   \`ModelArtifactRuntime.register_verified_remote_artifact(...)\`；
4. ModelArtifactRepository 立即创建正式 artifact row，并标成：
   \`storage_status = UPLOADED\`；
5. 之后才继续构建 / 校验：
   - frozen label schema；
   - label contract；
   - snapshot label schema；
   - evaluation truth；
   - training lineage；
   - version payload；
6. 最后才调用：
   \`attach_version_if_current(...)\`
   把算法版本真正写入算法版本 truth。

因此 ModelArtifact 的正式发布发生在算法版本生命周期之前。

**已确认 ModelArtifact owner 不会替调用方补这个约束：**

\`ModelArtifactRuntime.register_verified_remote_artifact()\`

只验证：

- SHA256；
- size；
- storage_source；
- object evidence；
- artifact identity；

然后直接：

\`self.repository.upsert({... version_id ...})\`

并：

\`storage_status='UPLOADED'\`。

它不会检查：

“这个 algorithm_id/version_id 是否已经存在于 algorithms truth”。

所以 artifact row 可以合法存在于 ModelArtifactRepository，但对应 algorithm version 根本不存在。

**可达失败窗口 1 — 标签合同校验发生在 artifact 注册之后：**

artifact 注册完成后，代码才检查：

\`contract_codes != frozen_label_codes\`

→ 抛：

\`REMOTE_TRAINING_LABEL_CONTRACT_MISMATCH\`

以及：

\`snapshot_codes != frozen_label_codes\`

→ 抛：

\`REMOTE_TRAINING_LABEL_SNAPSHOT_MISMATCH\`。

这两个异常都会让本次 result commit 失败，但此前已经登记的 ModelArtifact 不会 rollback。

**可达失败窗口 2 — 多模型逐个注册不是原子提交：**

\`uploaded_models\` 被逐条：

\`register_verified_remote_artifact()\`

例如：

- best 注册成功；
- last 在 provider.stat / SHA / repository write 等任一步失败；

则 best 已经是正式 canonical ModelArtifact，last 未完成，算法版本也尚未 attach。

形成“同一个训练结果只提交了一部分模型产物”的状态。

**可达失败窗口 3 — 算法版本并发冲突发生在最后：**

所有 ModelArtifact、primary local model、evaluation/lineage 都准备后，最终：

\`attach_version_if_current(... expected_current_version_id=...)\`

仍可能因为并发版本推进抛：

\`ALGORITHM_VERSION_CONFLICT\`

并转换成：

\`REMOTE_TRAINING_BASE_VERSION_STALE\`。

此时：

- ModelArtifact rows 已存在；
- primary model 本地文件已存在；
- 但新算法版本没有 attach。

**额外本地半成品：**

primary model 在 artifact registration 之前已经下载并原子 rename 到：

\`projects/{project}/models/remote_<task>_g<generation>_<role>_<sha>.pt\`

如果后续 commit 失败，这个模型文件同样没有当前算法版本 owner。

文件名虽然是 deterministic、后续同 task recovery 可复用，但如果任务最终失败且不恢复，它就是无 version owner 的本地模型残留。

**为什么是 Bug / Owner 生命周期冲突：**

ModelArtifact 是 canonical 模型产物 owner，但它的记录应当从属于一个真实存在的算法版本 lifecycle。

当前 commit 顺序允许：

\`ModelArtifact(version_id=V) = UPLOADED\`

同时：

\`Algorithm.versions\` 中根本没有 \`V\`。

这会让：

- ModelArtifact inventory；
- external publication；
- conversion source discovery；
- rollback / retirement；
- artifact GC；

面对一个没有版本 owner 的正式产物。

这不是普通 task staging，而是 canonical ModelArtifactRepository 已经被写入。

**与 AUDIT-065 的区别：**

AUDIT-065 是 Durable Task terminal artifact / task-runtime 文件缺少统一 retention/GC。

AUDIT-091 是**业务 canonical owner 的事务半提交**：

- ModelArtifactRepository 已正式登记；
- algorithm version 尚未创建。

不能依赖未来 task artifact GC 解决，因为这些 rows 已经不是 task-runtime staging。

**与已 CLOSED ModelArtifact identity 的关系：**

本问题不要求重新设计 ModelArtifact identity。

现有 deterministic identity 是正确方向。

问题是 publication/commit ordering：

canonical ModelArtifact 被过早发布。

应修 commit lifecycle，不应新建第二套 artifact owner。

**现有测试为什么没发现：**

\`tests/unit/test_remote_execution_transport.py\`

happy-path 训练 commit 明确断言：

- \`len(model_artifacts.registered) == 2\`；
- algorithm version attach 成功；
- version 含正确 label schema / lineage / evaluation。

但当前没有测试：

- 在 artifact registration 之后故意制造 \`LABEL_CONTRACT_MISMATCH\`；
- 在第 2 个 model artifact registration 失败；
- 在所有 artifact 注册后让 \`attach_version_if_current()\` 抛 conflict；

并断言：

“ModelArtifactRepository 不得留下任何无版本 owner 的正式记录”。

现有 base-version-stale 测试是在 artifact registration **之前**就失败，因此覆盖不到这个窗口。

**影响：**

- 模型资产页可能出现对应版本不存在的 artifact；
- conversion / publication / retirement 查询可能拿到 dangling version_id；
- 部分 best/last 已登记、另一部分缺失；
- 本地 models 目录产生无 version owner 的模型文件；
- 远程训练 UI 显示 commit 失败，但模型资产 truth 已发生不可见副作用；
- retry / crash recovery 必须额外处理历史半提交，否则状态依赖失败发生位置；
- 长期运行可积累无法由正常算法版本删除链回收的 canonical artifact rows。

**建议最小修复：**

不要新增第二 ModelArtifact owner，也不要放宽既有版本冲突保护。

优先调整 remote training commit 为“验证阶段”和“发布阶段”：

1. 在任何 canonical ModelArtifact write 前完成所有纯校验：
   - frozen label schema；
   - label contract；
   - snapshot schema；
   - evaluation inputs；
   - lineage inputs；
   - base/current version fence；
   - 完整 best/last evidence；
2. 多模型 evidence 必须先全部验证成功，再进入 publication；
3. algorithm version + ModelArtifact 应由一个明确 commit owner 协调：
   - 要么先以 version delivery fence 保留版本生命周期，再批量登记 artifacts；
   - 要么提供 compensating rollback，任何后续异常删除本次 generation 新建的 artifact rows；
4. 只有 commit 全部完成后才触发 external auto publish；
5. primary local model 也必须：
   - task-scoped staging；
   - 或在 commit failure 时按 deterministic ownership 做 cleanup；
6. crash recovery 必须保持幂等：
   - 已 attach version + artifacts 时重新进入直接 reconcile；
   - 不得重复版本，不得重复 artifact，不得误删其他 generation。

**回归测试建议：**

至少增加：

- best 注册成功、last 注册失败 → 无半提交 artifact；
- artifact 全成功、label contract mismatch → 无 dangling artifact/version；
- artifact 全成功、snapshot mismatch → 无 dangling artifact/version；
- artifact 全成功、final attach conflict → artifact rollback 或明确可恢复 staging；
- primary local model 在失败路径不形成无 owner 文件；
- crash after version attach before task finish → recovery 幂等；
- retry generation 不删除上一代已经被真实 version 引用的 artifact。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-092 — Agent result confirm 先提交正式业务结果、后写 Task result receipt；receipt I/O 失败后 Agent 可把已成功发布的训练/转换任务终结为 FAILED

**级别：高**  
**模块：Agent Finalization / Durable Task / Remote Result Publication / Training / Conversion / Material Import / Cleaning**

**现象：**

当前 Agent portable result protocol 在：

\`AgentExecutionService.confirm_result_upload()\`

中先通过：

\`self.fenced.begin_finalization(...)\`

赢得 finalization gate。

随后会调用：

\`self.result_commit_handler(...)\`

把远程执行结果真正提交给业务 canonical owner。

按 task kind，这个 handler 可执行：

- TRAINING：算法版本 + ModelArtifact / lineage / evaluation；
- MODEL_CONVERSION：conversion job / artifact；
- MATERIAL_IMPORT：远程导入正式结果；
- MATERIAL_BATCH：远程清洗 review commit；
- DEPLOYMENT_TEST：RKNN board verification truth。

但**业务 commit 完成以后**，control plane 才继续写：

1. \`remote-results/{generation}/result.json\`；
2. \`remote-results/{generation}/upload.json\` 中：
   \`confirmed = true\` / \`result_ref\`。

也就是说：

**canonical 业务真相先落地，Durable Task 的“本次业务 commit 已成功”receipt 后落地。**

如果这两次 task artifact 写入中的任意一步发生 I/O 异常，业务 commit 已无法回滚，但 \`confirm_result_upload()\` 会向 Agent 返回失败。

**真实顺序：**

\`confirm_result_upload()\`

→ 校验 remote result object

→ \`fenced.begin_finalization()\`

→ task stage = \`finalizing_commit\`

→ \`result_commit_handler(...)\`

→ **正式业务 owner 已 commit**

→ \`artifacts.atomic_write_json(task_id, result_ref, result)\`

→ \`artifacts.atomic_write_json(task_id, state_ref, state{confirmed:true})\`

→ 返回 confirmed=true。

故障窗口明确存在于：

“业务 commit 已成功”

和：

“task result receipt 已 durable”

之间。

**为什么会真的变成 FAILED，而不是只卡住：**

\`begin_finalization()\` 只把：

\`stage = finalizing_commit\`

但 task 的 status 仍是：

\`RUNNING\`。

而 \`FencedTaskRepository.finish()\` 的终态更新条件仍是：

\`status IN ('RUNNING','CANCEL_REQUESTED')\`

没有禁止：

\`RUNNING + stage=finalizing_commit -> FAILED\`。

以远程训练 runner 为例：

\`NodeAgentTrainingRunner.run()\`

调用：

\`client.confirm_result_upload(...)\`

若这里因为 control-plane receipt 写盘失败抛异常，会进入通用 exception 分支：

→ \`_finish_best_effort(lease, "FAILED", error=...)\`

所以最终可形成：

- Algorithm Version 已经存在；
- ModelArtifact 已经存在；
- 外部发布请求甚至可能已经标记；
- 但 Durable TRAINING task 最终 status = FAILED。

其它 Agent runner / executor 的异常路径同样会 best-effort publish FAILED，因此不是训练专属风险。

**可达故障示例：**

业务 commit 成功后：

- task_runtime/artifacts 磁盘空间耗尽；
- atomic rename / fsync 失败；
- 权限变化；
- 临时文件创建失败；
- 文件系统只读；
- artifact store 短暂 I/O error；

都可以使 result receipt 写入失败。

这些故障与业务模型存储、算法版本文件可能位于不同目录/卷，因此“业务 commit 成功但 task artifact write 失败”完全可达。

**为什么是 Task truth / Business truth split-brain：**

当前 UI、重试入口、统计和恢复首先看 Durable Task status。

如果 task 被标为 FAILED，用户会自然认为：

“这次远程训练/转换没有产生可用结果”。

但 canonical 业务 owner 可能已经成功：

- Training version 已创建；
- Conversion job 已 done；
- Cleaning result 已应用；
- Material Import 已正式入库。

用户点击 retry 后可能再创建下一 generation，从而产生重复或冲突的业务结果。

**与 AUDIT-091 的区别：**

AUDIT-091 是：

**业务 commit 内部前半段失败**——ModelArtifact 已登记，但 Algorithm Version 还没 attach。

AUDIT-092 是：

**业务 commit 已完整成功**，但 Durable Task 的 post-commit receipt 写入失败，然后 Task 被错误终结为 FAILED。

一个是业务 owner 内部半提交；一个是 business commit 与 task terminal truth 之间的事务断裂。

两者修复点不同，不能合并。

**与 cancellation finalization fence 的关系：**

当前 \`begin_finalization()\` 已正确解决：

“取消和成功 commit 谁先赢”。

它会拒绝后来的 cancel，因此这个部分不用重做。

问题是 fence 只保护：

\`cancel vs commit\`

没有保护：

\`commit success vs task FAILED publication\`。

**影响：**

- 训练任务显示失败，但新算法版本实际上已经生成；
- 用户 retry 可再生成第二个版本/第二批业务副作用；
- Conversion 显示失败但 conversion job/artifact 已成功；
- 成功率统计被污染；
- 自动告警/运维看到假失败；
- external publication 与本地 task 状态可能互相矛盾；
- recovery 不能仅根据 task status 判断业务是否已提交；
- audit trail 无法回答“这个 FAILED task 是否其实已经发布结果”。

**现有测试缺口：**

当前测试主要覆盖：

- cancel 在 finalization 前赢；
- stale execution generation 被 fence；
- result object SHA/size；
- happy-path confirm → finish success；
- commit handler 直接抛错时不应发布成功。

但缺少关键 fault injection：

\`result_commit_handler 已返回成功\`

→ 下一次 \`ArtifactStore.atomic_write_json\` 抛异常

→ 系统必须**不能**把 task 作为普通 FAILED 处理。

也缺少 restart recovery：

“业务 owner 已有 deterministic committed version/job，但 task receipt 缺失”时，control plane 应重新构造 receipt 并完成正确终态。

**建议最小修复：**

不要新增第二 Task owner，也不要撤销现有 finalization fence。

应扩展 finalization contract，使“业务 commit 已发生”成为可恢复的 durable truth：

1. canonical commit handler 必须返回 deterministic commit identity；
2. commit owner 应提供：
   - \`reconcile_committed(task_id, generation)\`
   或等价幂等查询；
3. 一旦业务 commit 成功：
   - 后续 task receipt I/O 失败不能允许普通 \`finish(FAILED)\` 覆盖事实；
   - task 应进入明确 recovery state，例如 \`finalizing_commit_recovery\`；
4. Worker/Agent 重连后：
   - 先按 deterministic identity 查询 canonical business truth；
   - 若已 committed，补写 result receipt 并 finish SUCCEEDED/PARTIAL_SUCCESS；
   - 若明确未 committed，才允许 FAILED；
5. 如果需要 commit receipt，必须由现有 owner 协调，不要新建平行业务数据库；
6. 对 Training / Conversion / Cleaning / Material Import / Deployment Test 共用同一 finalization recovery contract。

**回归测试建议：**

至少增加：

- Training business commit 成功后，result.json write fault；
- upload-state confirmed write fault；
- task 不得最终变成普通 FAILED；
- restart 后能从 algorithm version / deterministic version id 恢复 success receipt；
- Conversion job 已 done + receipt fault → 恢复 SUCCEEDED；
- commit handler 真正失败时仍可 FAILED；
- cancel 在 begin_finalization 前仍然正确赢；
- stale generation 不得借 recovery 认领新 generation 的结果。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-093 — Agent 已完成 canonical commit 且 result receipt confirmed 后，最后 finish 前掉线会被 lease recovery 当普通 RUNNING 重置为 QUEUED；下一 generation 可重复执行已成功任务

**级别：高**  
**模块：Agent Lease Recovery / Finalization / Durable Task / Training / Conversion / Remote Result**

**现象：**

当前 Agent portable result lifecycle 的 happy path是：

1. execution RUNNING；
2. result upload prepare / upload；
3. \`confirm_result_upload()\`；
4. \`begin_finalization()\`；
5. \`finish(SUCCEEDED / PARTIAL_SUCCESS / AWAITING_CONFIRMATION)\`。

其中第 3 步已经：

- 调用 \`fenced.begin_finalization()\`；
- 执行 \`result_commit_handler\`；
- 提交 canonical 业务结果；
- 写 \`remote-results/{generation}/result.json\`；
- 写 \`upload.json { confirmed: true, result_ref: ... }\`。

所以在第 3 步返回成功之后，业务结果和 control-plane result receipt 都已经是 durable truth。

但 Task 本身此时仍然是：

- \`status = RUNNING\`
- \`stage = finalizing_commit\`
- 仍依赖 Agent 最后显式调用 \`finish(...)\` 才进入 SUCCEEDED。

如果 Agent 在这个极窄但真实的窗口：

\`confirm_result_upload success -> finish request\`

之间：

- 进程崩溃；
- 服务器断电；
- 网络断开；
- Agent 被 kill；
- finish HTTP 请求永久丢失；

execution lease 最终会过期。

**当前 lease recovery 没有 finalization-specific recovery：**

\`FencedTaskRepository._release_expired_in()\`

对所有：

\`status IN ('RUNNING','CANCEL_REQUESTED')\`

先判断中央可见 process identity。

Agent 远程执行通常没有 control-plane 本地 PID identity，因此：

\`_process_recovery_state(row) -> gone\`

随后普通 RUNNING 一律：

- \`next_status = QUEUED\`
- \`stage = recovered\`
- 清 worker / lease / process identity。

代码没有判断：

- \`stage == finalizing_commit\`；
- \`remote-results/{old_generation}/upload.json.confirmed == true\`；
- \`result_ref\` 已存在；
- canonical business commit identity 已存在。

**旧 generation 的 confirmed receipt 也不会在新 claim 前自动收尾：**

\`AgentExecutionService._confirmed_remote_result()\`

虽然能读取：

\`remote-results/{generation}/upload.json\`

但只在当前 execution 调用：

- \`begin_finalization()\`
- successful \`finish_execution()\`

时使用。

Task 被 requeue 后，下一次 claim 会：

- 创建新 lease；
- \`attempt / execution_generation +1\`。

旧 generation 的 confirmed receipt 不会自动迁移到新 generation，也没有 pre-claim reconcile 把旧结果 finish 成 success。

因此新的 Agent 会把它当作一个正常 QUEUED 任务重新执行。

**对远程训练尤其严重：**

假设 generation 1 已经：

- 训练完成；
- 模型上传完成；
- Algorithm Version 已创建；
- ModelArtifact 已登记；
- result receipt confirmed=true；

但 Agent 在 finish 前断电。

lease recovery：

\`generation 1 RUNNING/finalizing_commit -> QUEUED/recovered\`

下一次 Agent claim：

\`generation 2\`

会重新跑训练。

而 remote training version id 又包含 task/generation/snapshot identity，因此 generation 2 可以产生另一个版本，形成：

“同一个用户任务，因为最后 finish 丢失而又完整训练一遍”。

**对 Conversion / Cleaning / Material Import 同样成立：**

- Conversion：已存在 done job/artifact，却重新转换；
- Cleaning：已提交 review/结果，却重新跑清洗；
- Material Import：已提交远程结果后可能再次处理；
- Deployment Test：已验证结果仍可再次运行。

部分 owner 具有幂等保护，但**重复重计算、重复远端 I/O 和不同 generation 的业务 identity**仍会发生，不能依赖每个 handler 各自兜底。

**为什么不是 AUDIT-092：**

AUDIT-092 是：

business commit 已成功，但 post-commit receipt 写入失败，Agent随后可能把 Task 写成 FAILED。

AUDIT-093 是：

business commit + result receipt **都已经成功**，只缺最后 Task terminal finish；Agent 掉线后 lease recovery 把它重新变成 QUEUED，再执行下一 generation。

一个是“成功业务被标失败”，一个是“成功业务被重新执行”。

**现有测试缺口：**

\`tests/unit/test_agent_result_upload.py\`

已有 happy-path：

- confirm result；
- assert upload.json confirmed=true；
- begin_finalization；
- finish SUCCEEDED。

也有 conversion 用例：

- confirmed=true；
- begin_finalization；
- 断言 stage=finalizing_commit。

但没有继续模拟：

- 此时 Agent 消失；
- lease expires；
- \`release_expired()\`；
- Task 应根据 confirmed result 自动完成，而不是 requeue。

repository recovery 测试目前明确保护普通 RUNNING：

\`lease expires -> QUEUED / stage=recovered\`

没有 finalizing_commit 例外合同。

所以现有两套测试单独都绿色，但组合后正好暴露这个跨层缺口。

**影响：**

- 已成功远程训练再次完整训练，浪费数小时 GPU；
- 同 task 产生多个 generation / 多个模型版本；
- 外部发布可能对多个结果重复触发；
- Conversion 重复占用算力与对象存储；
- 用户看到任务从“正在归档”突然重新排队；
- 成功业务 side effect 与 Task attempt 次数无法一一对应；
- 重复执行会进一步放大 AUDIT-091 / AUDIT-092 的恢复复杂度；
- Agent/网络不稳定时问题会自然出现，不需要人工误操作。

**建议最小修复：**

不要取消统一 lease recovery，也不要新建第二 Scheduler。

应给 \`finalizing_commit\` 增加专门 recovery contract：

1. lease expiry 遇到 \`stage=finalizing_commit\` 时，禁止直接 requeue；
2. 先读取该 execution generation 的 durable result receipt；
3. 若：
   - \`upload.json.confirmed=true\`；
   - result_ref 存在；
   - business commit identity 可 reconcile；
   则由 control plane 直接补齐正确 terminal status；
4. 若 receipt 不完整但 canonical business owner 已 committed：
   - 进入 AUDIT-092 所述 finalization recovery；
   - 补 receipt 后终结；
5. 只有明确证明 business commit 未发生时，才允许重新 QUEUED；
6. recovery 必须保留原 generation identity，不能把旧成功结果认成新 generation；
7. Training 的 SUCCEEDED/PARTIAL_SUCCESS 应从 committed result truth恢复，不能猜测。

**回归测试建议：**

至少增加：

- confirm_result_upload 成功后、不调用 finish；
- 强制 lease expiry；
- Task 不得变 QUEUED；
- Training 应直接恢复 SUCCEEDED/PARTIAL_SUCCESS；
- Conversion 应恢复 SUCCEEDED；
- 新 Agent 不得 claim 第二 generation；
- confirmed receipt 缺失但 canonical business已 committed时进入 recovery而非重跑；
- ordinary RUNNING 任务 lease expiry 仍按现有规则 requeue；
- CANCEL_REQUESTED recovery 语义保持不变。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-094 — Generic Agent finalization owner 把 Training 专属文案写给 Conversion / Cleaning / Material Import / Deployment Test，业务页会直接展示错误“训练已完成”状态

**级别：中**  
**模块：Durable Task / Agent Finalization / Frontend Presentation / Status Contract**

**现象：**

\`TaskRepository.begin_finalization()\` 是所有 Agent portable task 共用的 finalization owner。

但进入 \`finalizing_commit\` 时，它无条件写：

\`current_item='训练已完成，正在归档已验证产物'\`

没有根据 \`TaskKind\` 区分：

- TRAINING；
- MODEL_CONVERSION；
- MATERIAL_IMPORT；
- MATERIAL_BATCH / Cleaning；
- DEPLOYMENT_TEST。

同一个 repository 的 \`request_cancel()\` 又在任何：

\`status=RUNNING && stage=finalizing_commit\`

场景统一抛：

\`训练已完成并正在归档，无法再停止\`

因此 generic lifecycle owner 泄漏了 Training 专属 presentation。

**为什么是前后端真实可见问题：**

这些字段不是内部 debug metadata。

例如 Storage Import 页面轮询当前 Durable task 后直接构造：

\`runtime = [mode, worker_id, resource_wait_reason, task.current_item || task.stage]\`

所以远程 Storage Import 在 result commit 阶段会显示：

**“训练已完成，正在归档已验证产物”**

即使当前用户做的是素材扫描/导入。

UploadTaskCenter 的 durable normalization 同样把：

\`task.current_item || task.message || task.error\`

作为 detail 展示。

其它统一任务投影也会保留 \`current_item\`，所以这个错误状态文本可以传播到任务中心和业务详情页。

**停止操作同样漂移：**

finalizing_commit 阶段本来正确地应该禁止取消，因为 canonical commit 已经开始。

但 Conversion / Cleaning / Material Import / Deployment Test 用户点停止后，得到的后端错误却是：

“训练已完成并正在归档，无法再停止”。

行为正确，业务类型和文案错误。

**为什么不是单纯美观问题：**

finalization 是故障排查最关键阶段之一。

错误文案会让现场人员误判：

- 素材导入为什么突然进入训练；
- 转换是不是错误触发了 Training；
- 清洗任务是不是被错误路由到训练 Worker；
- Deployment Test 是否串到了 Training runtime。

这会掩盖真实的 Agent finalization 状态，并增加运维误判。

**与 AUDIT-092 / AUDIT-093 的区别：**

- AUDIT-092：business commit 成功后 task receipt 写失败，可能假 FAILED；
- AUDIT-093：成功 finalization 在 finish 前掉线会被错误 requeue；
- AUDIT-094：即使生命周期没有失败，generic finalization 的**公共展示合同**也错误写成 Training 文案。

修复范围仅是 projection/presentation contract，不应和事务恢复改动混在一起。

**建议最小修复：**

不要在各前端页面重新维护一套 finalization 文案。

应由 canonical task projection / lifecycle owner 根据 TaskKind 生成中性或 kind-aware 文案，例如：

- 通用：\`执行已完成，正在归档已验证结果\`；
- 或按 kind：
  - Training：正在归档训练模型；
  - Conversion：正在归档转换产物；
  - Material Import：正在提交导入结果；
  - Cleaning：正在归档清洗结果；
  - Deployment Test：正在归档验证结果。

取消拒绝错误也应使用中性表达：

\`任务已进入结果提交阶段，无法再停止\`

避免前端再根据 kind 猜测。

**回归测试建议：**

至少增加：

- 每个 Agent TaskKind 调 \`begin_finalization()\`；
- public \`current_item\` 不出现错误的“训练”文案；
- Storage Import 页面显示正确 finalization 文案；
- Conversion finalizing 时 stop 返回非 Training 专属错误；
- Training 自身仍显示合理文案；
- finalization cancel fence 行为保持不变。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-095 — Storage Import CandidateStore 跨 retry / execution generation 复用且仅 INSERT OR IGNORE；失败 attempt 的旧候选与旧 hash/status 可污染下一次确认和正式索引

**级别：高**  
**模块：Storage Import / Remote MATERIAL_IMPORT / ImportCandidateStore / Retry / Generation Isolation / Data Accuracy**

**现象：**

当前 Storage Import 的 canonical 候选数据库固定为：

\`scan/candidates.sqlite3\`

即：

\`MANIFEST_REF = "scan/candidates.sqlite3"\`

它以 task_id 为作用域，不以 execution generation / scan attempt 为作用域。

而：

\`ImportCandidateStore.upsert_many()\`

名字虽然叫 upsert，真实 SQL 却是：

\`INSERT OR IGNORE INTO candidates (...)\`

因此它既不会：

- 删除上一 attempt 已存在、这次已经不存在的 object_key；
- 更新同 object_key 在新 attempt 中变化后的：
  - content_sha256；
  - size_bytes；
  - etag；
  - width / height；
  - status；
  - error；
  - duplicate truth。

CandidateStore 本身也没有：

- clear；
- reset；
- replace；
- purge；
- truncate；

之类用于 fresh scan 的 canonical reset API。

**Local Storage Import 同样复用这个旧真相：**

\`StorageImportHandler._scan_impl()\`

每次直接：

\`ImportCandidateStore(artifact_path(task_id, MANIFEST_REF))\`

然后继续向已有 DB 批量：

\`store.upsert_many(...)\`。

scan 开始前没有删除/替换现有 candidate snapshot。

取消路径甚至会先：

\`_flush_scan_batch(...)\`

把已完成的本批次正式写进 CandidateStore，再返回 CANCELLED。

而：

\`recover()\`

如果没有完整 \`SCAN_RESULT_REF\`，会再次调用：

\`_scan(context, request)\`

继续扫描到同一份旧 CandidateStore。

所以一次失败/崩溃/取消后重新执行时，候选真相不是“重新冻结当前存储扫描结果”，而是“在旧 attempt 上继续 INSERT OR IGNORE”。

**Remote MATERIAL_IMPORT 的跨 generation 问题更明确：**

每个 Agent generation 的 review archive 本身都带：

\`execution_generation\`

并且服务器会严格验证：

- archive SHA；
- candidate_count；
- task_id；
- project_id；
- generation；
- storage source；
- target prefix。

但验证完成以后：

\`commit_material_review_archive()\`

仍把这一 generation 的 rows 写入同一个：

\`scan/candidates.sqlite3\`

并调用：

\`candidate_store.upsert_many(current_generation_rows)\`。

与此形成鲜明对比的是：

\`RemoteMaterialStagingStore\`

对当前 generation 明确使用：

\`replace_many(...)\`

即 staging truth 是当前 generation snapshot，但 CandidateStore truth 却是跨 generation 累积。

**为什么旧数据会真正进入用户确认：**

这不是“数据库里多了几条没人用的历史行”。

\`ImportCandidateStore.selection_facts(keys=None)\`

默认明确执行：

\`INSERT INTO wanted SELECT object_key FROM candidates WHERE status='IMPORTABLE'\`

也就是把 CandidateStore 内**所有当前 IMPORTABLE 行**作为可确认集合。

\`confirm(selected_keys)\`

只检查：

- object_key 在 candidates 表存在；
- persisted status == IMPORTABLE。

它没有 attempt/generation 字段，无法区分：

“这个候选来自当前扫描”

还是：

“这是上一 generation 失败后遗留的旧候选”。

确认后：

\`pending_index_batch()\`

又直接读取：

\`WHERE selected=1 AND indexed=0\`

继续把这些旧候选送进正式 Material indexing。

所以旧 attempt truth 会穿透：

CandidateStore
→ 用户确认
→ selected
→ image_id assignment
→ pending index
→ MaterialRepository / AnnotationRepository。

**两个典型错误场景：**

场景 A — 旧对象已经消失：

generation 1 扫描：

- A.jpg
- B.jpg

随后失败。

generation 2 真实存储只剩：

- B.jpg
- C.jpg

当前实现最终 CandidateStore 仍可能是：

- A.jpg（旧）
- B.jpg
- C.jpg

用户默认“全部可导入”时，A 仍可进入 selection。

对 Remote Import，当前 generation 的 \`RemoteMaterialStagingStore\` 已经 replace 成 B/C，因此 A 甚至可能没有当前 staging evidence，造成确认后 indexing 中途失败。

场景 B — 同 key 内容已变化：

generation 1：

\`B.jpg sha=OLD, status=IMPORTABLE\`

generation 2：

\`B.jpg sha=NEW\`

由于：

\`INSERT OR IGNORE\`

新 row 被忽略。

CandidateStore 仍认为 B 是旧 SHA / 旧尺寸 / 旧状态。

于是：

- UI review 展示旧 truth；
- selection digest 计算旧 hash；
- 后续当前 generation staging / provider 内容却是新 truth；
- indexing 可能报 evidence mismatch，或把错误 metadata 固化进 Material。

**为什么这是主流程准确性问题：**

Storage Import 的 review/确认阶段本意是：

“用户确认本次扫描冻结出来的素材候选”。

但当前 retry / recovery 之后，用户看到的是：

“多个 attempt/generation 的候选并集，而且同 key 优先保留最早写入的旧元数据”。

这直接破坏了：

- 本次导入范围；
- 内容 hash；
- duplicate truth；
- invalid/importable classification；
- 标注质量与外部标签 summary；
- 最终入库准确性。

**与已有问题的区别：**

- AUDIT-067：Storage Import focused poller 切换任务时 owner handoff 丢失；
- AUDIT-092 / 093：Agent finalization 的 commit/receipt/lease recovery；
- AUDIT-051：ZIP review 全量 hydration；
- AUDIT-062：ZIP daemon crash recovery。

AUDIT-095 是 Storage Import 自己的**候选 snapshot generation isolation**问题。

不需要重新设计 CandidateStore owner；恰恰应该让现有 CandidateStore 成为单一、准确的“当前 scan snapshot” owner。

**现有测试缺口：**

\`tests/unit/test_remote_material_import.py\`

目前主要覆盖：

- 单一 generation archive build/commit；
- SHA / payload tampering；
- storage_scan metadata；
- YOLO/COCO/VOC annotation truth。

没有测试：

同一个：

\`task_id + MANIFEST_REF\`

连续提交：

- generation 1：A/B；
- generation 2：B/C；
- B 的 hash/status 在 generation 2 改变；

然后断言最终候选必须严格等于：

- B(current)
- C

且：

- A 已消失；
- B 使用 generation 2 metadata。

Local Storage Import 测试也没有覆盖：

“scan 部分写入 → crash/cancel → provider 内容变化 → fresh retry”。

**建议最小修复：**

不要新增第二 CandidateStore owner。

应把现有 CandidateStore 变成明确的 scan-generation snapshot：

1. Remote generation：
   - 先在 generation-scoped 临时 CandidateStore 构建；
   - 完整验证 candidates / annotations / quality；
   - 全部成功后原子 promote/replace 当前 \`MANIFEST_REF\`；
2. Local retry：
   - 区分“同 generation resume”与“fresh restart”；
   - fresh restart 必须重建 snapshot，不能和旧候选做 union；
3. 如果需要复用同一路径，提供明确：
   \`replace_snapshot(rows)\`
   或 atomic DB swap；
   不要把 \`INSERT OR IGNORE\` 当 upsert；
4. 一旦用户已经 confirmation：
   - 禁止静默替换其下层 CandidateStore；
   - 必须保持 confirmation → snapshot identity 不变；
5. RemoteMaterialStagingStore 与 CandidateStore 必须来自同一 generation identity；
6. selection digest 应绑定 snapshot/generation identity，而不仅是 object_key 集合。

**回归测试建议：**

至少增加：

- gen1=A/B，gen2=B/C → 最终候选严格 B/C；
- gen1 B old hash，gen2 B new hash → 最终必须 new；
- gen1 IMPORTABLE，gen2 INVALID → 最终必须 INVALID；
- gen1-only A 不得出现在默认 selection；
- Remote staging 与 CandidateStore keys/metadata 必须同 generation；
- Local partial scan crash 后 fresh retry 不保留消失对象；
- confirmation 后不得被新 generation 静默替换；
- 10k / 20k snapshot replace 使用 streaming / atomic swap，不能退化为全量 Python 内存复制或 O(N²)。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-096 — 【已撤销：重复 AUDIT-068】Training SSE / REST queue readiness 状态漂移

**状态：REVOKED / DUPLICATE OF AUDIT-068**  
**原级别：中～高**

本条在后续对 `AUDIT-068～098` 做全量标题与调用链去重时确认：

**AUDIT-096 与 AUDIT-068 是同一个真实问题，不应重复计数。**

AUDIT-068 已经完整记录：

- Training SSE 没有复用 canonical `training_queue_truth()`；
- HTTP/REST 对 QUEUED Training 可投影为 `WAITING_RESOURCE`；
- SSE 只做基础 `task_to_public`，可返回 `QUEUED`；
- 前端 realtime update 会把 HTTP 的 WAITING_RESOURCE 覆盖回 QUEUED。

AUDIT-096 后续补充的：

- stale `resource_wait_reason` 与 QUEUED 状态可形成矛盾组合；
- SSE 修复必须避免引入 AUDIT-064 所述 N+1 / 全量 queued hydration；

都应并入 **AUDIT-068 的修复与回归范围**，不再作为独立问题。

**处理方式：**

- 保留本编号作为审计历史，不删除记录；
- 本条不进入独立修复队列；
- 后续修复只处理 AUDIT-068；
- VERSION 已按审计记录规则继续递增。

---

### AUDIT-097 — Material Integrity 长扫描不校验 Material / Annotation revision 漂移，可提交混合世代结果却标记 snapshot_only=true

**级别：中～高**  
**模块：Material Integrity / Snapshot Consistency / MaterialRepository / AnnotationRepository / 10k-20k Scale**

**现象：**

当前 `AUDIT_MATERIAL_INTEGRITY` 启动时会记录：

- `material_revision = materials.current_revision()`
- `annotation_revision = annotations.current_revision()`
- `total = materials.summary()["total"]`

随后执行两类长扫描：

1. 从 MaterialRepository 查询重复 content hash，并批量读取 AnnotationRepository；
2. 通过 `materials.list_page(cursor=..., limit=BATCH_SIZE)` 分页扫描全部素材，再逐条 materialize / hash / decode 校验存储对象。

问题在于，这个流程并没有真正冻结 Material / Annotation truth。

`MaterialRepository.list_page()` 每一页都会单独：

`with closing(self._connect()) as database`

读取完即关闭 connection；后续页再重新打开新 connection。

因此 10k / 20k 素材的 Full Audit 会跨很多独立 SQLite read snapshot。审计期间发生的导入、删除、素材更新、标注修改可以被后续页看见，而早期页仍保留旧世代结果。

审计使用的 `material-integrity.sqlite3` 虽然从头到尾有自己的 `BEGIN IMMEDIATE`，但它只锁住**审计结果数据库**，并不能冻结：

- `materials.sqlite3`
- AnnotationRepository
- 外部存储对象

所以它不是业务 truth 的快照事务。

**最关键的不一致：**

Material Integrity 在开始时记录 revision，但完成前没有重新检查：

- `materials.current_revision()`
- `annotations.current_revision()`

是否仍等于开始值。

最终却写入：

`metadata = { material_revision, annotation_revision, snapshot_only: True }`

然后直接 COMMIT 并把 Durable Task 标为成功。

也就是说，元数据声明的是“某个 revision 的 snapshot”，实际内容可能是多个 revision 混合出来的结果。

**与 Label Integrity 的直接对比：**

现有 `run_label_integrity_audit()` 已经采用正确的 fail-closed 合同。

它在开始时冻结：

- annotation revision；
- AnnotationRepository fingerprint；
- material revision；
- governance fingerprint；

在提交结果前重新读取全部 truth identity。只要任一变化，就抛出：

`LABEL_INTEGRITY_TRUTH_CHANGED_DURING_AUDIT`

要求重跑，而不是发布一个混合世代的成功审计。

Material Integrity 当前缺少同等级 fence。

**真实可发生场景：**

例如一个 20k 素材项目执行 Material Integrity：

1. audit 开始，记录 material revision = 100；
2. 先扫描到 A/B 是重复素材，并读取当时的 Annotation；
3. 审计继续扫描存储对象；
4. 用户此时批量导入新素材、删除 A、修改 B 的标注，revision 变成 101/102；
5. 后续 `list_page()` 使用新 connection，看到新的 Material truth；
6. audit 最后仍以 revision=100 / snapshot_only=true 成功发布。

最终结果可能同时包含：

- 早期页面的旧素材/旧 Annotation 关系；
- 后期页面的新素材状态；
- 已经删除或已经改变的 duplicate group；
- 基于变化前后不同 object metadata 得出的 hash/decode evidence。

**为什么是 Bug：**

Material Integrity 是质量中心后续人工处理的证据来源，不是“近似统计”。

用户会根据它处理：

- `DUPLICATE_IDENTICAL`
- `DUPLICATE_ANNOTATION_CONFLICT`
- `MATERIAL_OBJECT_MISSING`
- `CONTENT_HASH_MISMATCH`
- `INVALID_IMAGE`

如果审计不是一个一致 truth generation，结果自身就可能互相矛盾。

更严重的是 metadata 会误导调用方认为结果严格对应某个 material/annotation revision。

**与 AUDIT-057 / AUDIT-058 的区别：**

- AUDIT-057：当前 Full Audit 的发现/恢复使用 bounded task page，且缺少 active dedupe；
- AUDIT-058：完成后的 groups/items 前端不消费 next_cursor；
- AUDIT-097：**单次 Full Audit 执行过程中没有 snapshot/revision fence，可能成功提交混合世代证据。**

三者分别属于 task lifecycle、结果分页和数据一致性，不能互相替代。

**影响：**

- 大项目审计耗时越长，撞上并发 mutation 的概率越高；
- duplicate conflict 可能出现 false positive / false negative；
- 已删除素材仍可能留在已完成 audit 中；
- 新增素材可能只参与后半段 object scan，却没参与前半段 duplicate analysis；
- Annotation 修改可能导致 duplicate classification 与最终详情 truth 不一致；
- 用户基于旧/混合结果做删除、保留、人工复核时容易误判；
- `snapshot_only=true` 和 revision metadata 失去可信度。

**现有测试为什么没发现：**

现有 `tests/api/test_material_integrity.py` 主要验证：

- audit 能创建和运行；
- duplicate annotation conflict 能生成；
- groups/items API 正常；
- Material delete 与 Training reference 等其它 fence。

没有覆盖：

`audit running -> material/annotation revision changes -> audit must not publish success`

而 Label Integrity 已经有明确 truth-change fail-closed 设计，说明这个一致性要求在项目里本身已有先例。

**建议最小修复：**

不要为 Material Integrity 新建第二套 snapshot owner，也不要持有一个 20k 素材全程的长时间 SQLite 写锁。

优先复用 Label Integrity 的 revision/fingerprint fence 模式：

1. audit 开始冻结：
   - material revision；
   - annotation revision；
   - 必要时 AnnotationRepository fingerprint；
2. 完成所有扫描、准备提交 `material-integrity.sqlite3` 前，再读取当前 identity；
3. 任一 truth generation 已变化：
   - 不发布 SUCCEEDED；
   - 返回明确 `MATERIAL_INTEGRITY_TRUTH_CHANGED_DURING_AUDIT`；
   - 提示重新运行；
4. 只有前后 identity 一致，才写 `snapshot_only=true` 并 COMMIT；
5. 对存储对象证据继续绑定 frozen material row 的：
   - storage_source_id；
   - object_key；
   - content_sha256 / etag；
   避免把 mutation 后对象状态误归到旧 row；
6. 不要通过阻塞所有 Material 写操作来“保证一致”，避免 Full Audit 变成 10k/20k 项目的长时间全局锁。

**回归测试建议：**

至少增加：

- Material revision 在 audit 中途变化 -> task 不得 SUCCEEDED；
- Annotation revision 在 duplicate analysis 后变化 -> task 不得发布 snapshot；
- 无 truth change -> 正常成功；
- fail 后 retry 能重建全新结果，不继承旧 audit rows；
- 20k 分页扫描保持 bounded 内存/连接使用；
- revision fence 不引入长时间 MaterialRepository writer lock。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-098 — MaterialBatch AI Candidate 写入缺少 execution commit fence；check_active 通过后失去 lease / 被取消的旧 Worker 仍可提交迟到候选

**级别：高**  
**模块：AI Annotation / MaterialBatch / CandidateStore / Worker Lease / Cancellation Fencing**

**现象：**

当前平台有两条使用同一个 CandidateStore 的 AI generation 路径：

1. 普通 `TaskKind.AI_ANNOTATION`；
2. MaterialBatch 的 `operation=AI_ANNOTATE`。

普通 AI Annotation 已经实现正确的 commit fence：

`store.write_session(commit_guard=lambda: _assert_generation_commit(context))`

CandidateStore 每次 SQLite append 会在同一个 `BEGIN IMMEDIATE -> write -> commit_guard -> COMMIT` 事务内重新证明：

- 当前 execution generation；
- Worker lease；
- cancellation / ownership。

因此“模型调用完成以后才失去 lease”的旧 Worker 无法把迟到结果提交进 Candidate truth。

但 MaterialBatch AI 使用的是：

`AnnotationBatch.process()`

流程为：

1. `check_active(...)`；
2. materialize / decode；
3. 再次 `check_active(...)`；
4. 调 provider `annotate_one(...)`；
5. provider 返回后再次 `check_active(...)`；
6. `self.store.append_items([item])`；
7. `manifest.transition([image_id], "succeeded")`。

第 6 步没有传 CandidateStore 已经提供的：

`commit_guard=`

所以第 5 步只是一次普通 heartbeat/check，不是数据库 commit fence。

**真实竞态窗口：**

`check_active()`

内部通过：

`context.repository.heartbeat(task_id, lease_token, ...)`

证明当下 lease 仍有效。

但 heartbeat 返回后，到 CandidateStore 真正 COMMIT 之间存在时间窗口：

- Candidate SQLite 等待 `BEGIN IMMEDIATE`；
- WAL / fsync；
- 磁盘抖动；
- 另一 review/read/write 连接竞争；
- Worker 网络/调度延迟。

CandidateStore SQLite connection timeout 本身可到 30 秒。

在这个窗口内，如果：

- 用户请求 cancel；
- Worker lease 到期；
- execution generation 被 recovery/retry 替换；
- 另一 Worker 已重新取得同一 task；

旧 Worker仍会继续执行：

`append_items([item])`

并 COMMIT 成功，因为这个事务没有再向 TaskRepository 验证 lease token。

之后它还可能继续执行：

`manifest.transition(..., "succeeded")`

进一步把 selection item 标成完成。

**为什么现有“provider 后再 check_active”仍不够：**

这是典型 TOCTOU：

`check -> ownership changes -> commit`

检查和提交不是同一个 fence。

而 CandidateStore 自身的 API 已经专门支持：

`append_items(..., commit_guard=...)`

和：

`write_session(commit_guard=...)`

其注释也明确说明：

“Candidate rows 在独立 SQLite 中，仅拿到 artifact path 不足以 fence 后续 SQLite commit；生产 AI annotation handler 应提供 WorkerContext-backed guard，防止 stale/late model output 在 lease loss 后提交。”

MaterialBatch AI 当前正好绕过了这个机制。

**普通 AI Annotation 已经证明正确合同：**

`annotation_task_service.py` 的 canonical generation 使用：

`with store.write_session(commit_guard=lambda: _assert_generation_commit(context)) as append_candidate:`

并在 provider 返回后：

- 先检查 cancel；
- 再进入带 commit_guard 的 CandidateStore transaction。

所以 AUDIT-098 不是要求设计新机制，而是 MaterialBatch adapter 没有复用已经存在的 fencing contract。

**现有测试缺口：**

`tests/unit/test_annotation_batch_cancel_fencing.py` 已覆盖：

1. materialize 期间 cancel -> 不调用 provider；
2. provider 调用期间 cancel -> provider 返回后 check_active 抛 InterruptedError，CandidateStore 不写。

但没有覆盖：

`provider 后 check_active 成功 -> append_items 开始/等待锁 -> 此时 cancel 或 lease loss -> COMMIT 必须失败`

所以当前测试能证明前两个窗口安全，却恰好漏掉 commit-time window。

**可能后果：**

- CANCEL_REQUESTED / CANCELLED 后 CandidateStore 仍出现新的 success/empty 候选；
- lease recovery 后旧 Worker 与新 Worker 对同一 image_id 竞争 upsert，后提交者覆盖前者；
- stale generation 的 provider 输出可能覆盖当前 generation 的候选；
- manifest item 可能被旧 Worker错误推进到 succeeded；
- 后续 retry 看到旧 success/empty candidate 时会按“已持久化，避免重复计费”直接跳过 inference，从而把迟到 stale candidate 当成有效恢复证据；
- CandidateStore truth、BatchSelection truth 与 TaskRepository execution generation 发生分裂。

**与 AUDIT-080 的区别：**

AUDIT-080 是：

`PARTIAL_SUCCESS -> retry`

被旧 review confirmation 短路，失败图片根本不重新推理。

AUDIT-098 是：

**正在 generation 的 Worker 已失去执行权后，仍可能把 provider result 写进 CandidateStore。**

一个是 retry phase 语义错误，一个是 commit fencing / stale Worker 并发错误。

**建议最小修复：**

不要新增第二 CandidateStore，也不要另造 AI runtime。

复用现有 CandidateStore fencing 能力：

1. MaterialBatch `AnnotationBatch` 接收一个 execution commit guard；
2. success/empty/failed candidate 的 `append_items` 都必须：
   `commit_guard=lambda: _check_active(context, ...)`；
3. guard 必须在 CandidateStore SQLite transaction 内、COMMIT 前执行；
4. BatchSelection 的 `running -> succeeded/failed` transition 也要有同等级 execution fence，避免 Candidate commit 安全后 selection transition 又出现第二个 TOCTOU；
5. cancellation control-flow 不能被转成普通 failed candidate；
6. 保留“candidate durability 后避免重复计费”的恢复语义，不要通过删除 CandidateStore 解决。

**回归测试建议：**

至少增加：

- provider 返回后第一次 check_active 成功；
- 在 CandidateStore transaction/commit_guard 时模拟 CANCEL_REQUESTED -> 无 candidate commit；
- 模拟 lease token 被替换 -> stale Worker 无 candidate commit；
- 新 generation 已提交 candidate 后，旧 Worker迟到不得覆盖；
- failed candidate 写入同样受 fence；
- Candidate commit 成功但 selection transition 前失去 lease时，旧 Worker不得推进 selection；
- 现有 materialize/inference cancellation 测试保持；
- 普通 AI_ANNOTATION 的 commit_guard 合同保持一致。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-099 — Storage Rescan 标注覆盖的冲突检查与 AnnotationRepository commit 分离；校验通过后人工保存仍可被迟到 Rescan 静默覆盖

**级别：高**  
**模块：Storage Rescan / AnnotationRepository / Optimistic Concurrency / Ground Truth**

**现象：**

当前 YOLO / COCO / VOC Storage Rescan 在应用外部标注时，已经有一层看起来正确的“平台标注已变化则拒绝覆盖”保护：

`StorageRescanHandler._apply_annotation_rescan()`

会先批量读取：

`current_annotations = annotations.get_many(material_ids)`

然后对准备写入的 `ANNOTATION_NEW / ANNOTATION_CHANGED / ANNOTATION_CONFLICT / ANNOTATION_REMOVED` 比较：

- review 时冻结的 `platform_annotation_hash`；
- review 时冻结的 `platform_annotation_state`；
- apply 时刚读取的 `current_hash`；
- apply 时刚读取的 `current_state`。

不一致时会抛：

`platform annotation changed after rescan review; create a new rescan`

这能阻止“用户在 review 完成以后、apply 开始以前已经改过标注”的普通 stale overwrite。

但冲突检查和真正 AnnotationRepository 写入不是同一个事务，也没有使用 AnnotationRepository 已提供的 `expected_version` 乐观锁。

真实顺序是：

1. `annotations.get_many(material_ids)`；
2. 比较 `content_digest / annotation_state`；
3. 构造 `annotation_rows`；
4. **中间没有任何 Annotation lock / CAS**；
5. `annotations.upsert_many(annotation_rows, return_rows=True)`。

而 `annotation_rows` 只包含：

- `image_id`
- `boxes`
- `annotation_state`

没有把第 1 步读到的：

`current_annotation.version`

作为：

`expected_version`

传给 `AnnotationRepository.upsert_many()`。

**AnnotationRepository 本身已经有正确能力：**

`AnnotationRepository.upsert_many()`

对每一行都支持可选：

`expected_version`

并在同一个 `BEGIN IMMEDIATE` 事务内重新读取当前 version；只要实际 version 与 expected 不同，就抛 `AnnotationConflictError`，拒绝 stale write。

Storage Rescan adapter 当前没有使用这项 canonical concurrency contract。

**真实竞态窗口：**

1. Rescan review 冻结平台标注 A，version=5；
2. 用户确认“外部标注变化 → 更新”；
3. Worker 进入 `_apply_annotation_rescan()`；
4. `get_many()` 读到 A/version=5，hash/state 校验通过；
5. 此时人工标注工作台保存新标注 B，AnnotationRepository 变为 version=6；
6. Rescan 继续执行 `upsert_many(annotation_rows)`；
7. 因为没有 `expected_version=5`，Repository 会正常把外部标注 C 写进去，并将 version 再加一；
8. 人工刚保存的 B 被静默覆盖。

所以当前保护仍然是典型：

`read/check -> concurrent manual write -> unconditional upsert`

TOCTOU。

**为什么是 Ground Truth Bug：**

AnnotationRepository 是当前唯一正式 Annotation Ground Truth owner。

人工标注保存已经依赖 version/CAS 防止 concurrent modification；Storage Rescan 作为另一个写入 adapter，却先在 owner 外做一次检查，然后不把检查到的 version 带进 owner transaction。

因此同一 Ground Truth 对不同写入口具有不同的并发安全等级。

这不是要求重做 Annotation GT 架构，而是 Rescan 没有复用已经 CLOSED 的 canonical optimistic-lock contract。

**现有测试为什么没有挡住：**

`tests/unit/storage/test_rescan_tasks.py` 已有：

`test_yolo_rescan_rejects_platform_annotation_edit_after_review`

该测试证明的是：

- review 后先修改平台 Annotation；
- 再进入 `_apply_annotation_rescan()`；
- 第一次 `get_many()` 就能看到新 digest；
- 因而 fail-closed。

它没有覆盖真正的竞态窗口：

`get_many/check 已经成功 -> 在 upsert_many commit 前人工修改 Annotation`

测试中也没有要求 Rescan 写入携带 `expected_version`。

所以当前测试保护的是“apply 前 stale”，不是“commit-time stale”。

**影响：**

- 人工标注员刚保存的框可能被后台 Storage Rescan 覆盖；
- `ANNOTATION_CONFLICT + overwrite` 场景风险尤其高，因为用户本来就授权覆盖旧冲突，但不等于授权覆盖确认后的新人工修改；
- 10k/20k rescan 分批 apply 时窗口长期存在，任务运行越久越容易和人工工作台并发；
- Annotation version 会正常递增，看起来像合法写入，事后很难从普通 UI 识别这是 lost update；
- MaterialRepository 的 Annotation projection 也会随后跟着 Rescan 新值更新，进一步掩盖人工写入被覆盖的事实；
- 训练若在之后冻结 Snapshot，会使用被迟到 Rescan 改写后的 Ground Truth。

**与已有问题的区别：**

- AUDIT-085：REMAP 与 Training Prepare 缺少整任务一致性 fence；
- AUDIT-097：Material Integrity 审计长扫描缺少 revision fence；
- AUDIT-098：MaterialBatch AI Candidate 缺 execution commit fence；
- AUDIT-099：**Storage Rescan 在写正式 Annotation Ground Truth 时缺少 AnnotationRepository commit-time version CAS。**

触发 owner、写入对象和修复机制都不同。

**建议最小修复：**

不要新增第二 Annotation owner，也不要给整个 Rescan 持有长时间 Annotation DB 锁。

直接复用现有 `AnnotationRepository.upsert_many(expected_version=...)`：

1. `get_many()` 读取 current Annotation 时同时保留 `version`；
2. 对每条真正要覆盖的 `annotation_rows` 写入：
   `expected_version=current_annotation.version`；
3. legacy / SQLite 不存在时使用 owner 已定义的 version=0 语义；
4. `upsert_many()` 在自己的 `BEGIN IMMEDIATE` 内做最终 CAS；
5. 任一行 version 已变化，应整批 rollback，并返回明确的 rescan conflict，要求重新 review；
6. 不要把冲突降级成“跳过该图后继续成功”，否则用户确认的 batch review truth 会被部分提交；
7. Material projection 继续由 AnnotationRepository 成功 commit 后统一更新，不新建 projection owner。

**回归测试建议：**

至少增加：

- review/apply 初始 version=5；
- 第一次 `get_many()` 返回后模拟人工保存到 version=6；
- Rescan `upsert_many` 必须抛 conflict，人工 version=6 内容保持不变；
- `ANNOTATION_CHANGED`、`ANNOTATION_CONFLICT overwrite`、`ANNOTATION_REMOVED clear` 都覆盖；
- 无并发修改时正常写入；
- 多行 batch 中任意一行 version 漂移时整批回滚；
- 现有 `test_yolo_rescan_rejects_platform_annotation_edit_after_review` 保持；
- 500 行 batch 下仍为单事务 CAS，不引入逐图 N+1 写事务。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-100 — 模型列表 API 为建立 model→training 映射每次全量扫描所有历史 job.json；训练/发布/部署页面随累计训练历史线性变慢

**级别：中～高**  
**模块：Model List / Training History / Page Extras / Filesystem Performance / 10k-20k Scale**

**现象：**

当前 `GET /api/projects/{project_id}/models` 直接调用 `list_models_internal(project_id)`。

这个函数为了给 `projects/{project_id}/models/*` 中的当前模型补 job_id、job_name、framework、config_path、family_key、num_classes、report_ready，会先构造 `model_to_job`。

构造方式是每次请求都执行 `for jf in jobs_dir.glob("*/job.json")`，遍历项目下**全部历史训练任务目录**；每个 job 都要 read_json、遍历 job.models、对模型路径做 Path.resolve，并写入 path/name 两套映射。之后才真正遍历当前 models 目录。

所以该接口成本不是“当前模型数量”，而是 **O(累计 Training history + 当前 model files)**。即使当前只有十几个模型，项目累计 1k / 10k / 20k 次训练后，每次请求仍重新读取所有历史 job.json。

**当前前端是常用入口：**

`static/app.js -> extras412()` 在进入训练任务、测试发布、部署转换、部署产物时都会加载 `/api/projects/{id}/models`；`refreshCurrentPage413()` 也会重新触发当前页 extras。

因此训练历史越长，这四个常用页面首开/刷新越慢。

**为什么不是 AUDIT-066：**

AUDIT-066 是 `GET /api/projects/{project_id}/jobs` 在返回 active + 最近 50 terminal 前多次全量扫描 Training job history。

AUDIT-100 是另一条独立 endpoint：`GET /api/projects/{project_id}/models` 为建立 model→job metadata 映射，再单独扫描全部历史 job.json。即使修完 AUDIT-066，模型 API 仍保留同量级 filesystem I/O。

进入“训练任务”页面时，jobs 与 models 还可能同时加载，因此同一批历史目录会在一次页面加载中被重复遍历。

**影响：**

- 训练历史越多，训练任务页仍会线性变慢；
- 测试发布、部署转换、部署产物被无关的全部 Training history 拖慢；
- 10k/20k 个小 job.json 产生大量 inode lookup、文件 open、JSON parse、path resolve；
- 机械盘、云盘、NFS/挂载盘环境更明显；
- 多标签页/多用户会重复做同一历史扫描；
- 当前模型数量很少也无法降低历史扫描成本。

**为什么现有测试没发现：**

现有 browser/frontend 性能测试主要保护请求次数、DOM 稳定和页面刷新行为，通常 mock `/models`，不会测服务器内部读取多少历史文件。

当前没有看到“20,000 terminal training job dirs + 少量 current models”条件下，对 GET /models 的 bounded file-read / repository-query 合同。

**建议最小修复：**

不要新增第二 Model owner，也不要把 history limit 改成更大的固定数。

1. 训练成功/模型归档时增量持久化 model→job provenance；
2. 或复用已有 ModelArtifact / algorithm version / bounded Training index 的 lineage；
3. GET /models 只读取当前模型及其直接 provenance；
4. legacy 无 provenance 模型如需兼容，只允许一次性或 bounded fallback，不得每个 GET 全历史 glob；
5. 如果与 AUDIT-066 共享增量 Training history index，只保留一个 canonical owner，不能再造第三套缓存。

**回归测试建议：**

- 20,000 terminal training job dirs + 10 current models；
- GET /models 的 job metadata 读取数量有明确上限；
- job_id/framework/report_ready 仍正确；
- legacy provenance fallback bounded；
- 训练任务页同时加载 jobs + models 时不再产生两轮全历史扫描；
- Windows / Linux 路径 identity 保持正确。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-101 — training_options 在请求线程内串行探测全部 Legacy Server 并递归扫描本地训练资源；单次页面 hydration 最坏可阻塞约 80 秒以上

**级别：高**  
**模块：Training Options / Training Create Hydration / Legacy Server Health / Paddle Resource Scan / Web Latency**

**现象：**

当前 `GET /api/training_options?project_id=...` 是训练页、训练资源页和训练创建 hydration 的公共配置入口。

这个 GET 在 Web 请求线程内同步完成多类重工作：

1. project models：调用 `list_models_internal(project_id)`，会触发 AUDIT-100 的全量 Training job history 扫描；
2. PaddleDetection：调用 `scan_paddledet_algorithms(pd_dir)`，递归扫描 configs 下的 yml；
3. Paddle weights：调用 `scan_paddle_weights(pd_dir)`，递归发现本地权重；
4. legacy Training Server：对 `SERVERS_FILE` 中每一条服务器顺序调用 `_remote_capabilities(server)`；
5. `_remote_capabilities()` 内同步执行 `requests.get(base_url + /api/remote/health, timeout=4)`。

第 4 项是最明显的阻塞源：循环没有并发、没有健康缓存、没有上一次 sampled_at truth。

AUDIT-040 已确认 legacy server 当前最多物理保留 20 条。因此 20 台不可达/超时服务器时，一次 training_options 理论上可连续等待接近 `20 × 4s = 80s`，还没算 DNS、连接建立、Paddle 扫描和模型历史 I/O。

**真实前端影响：**

`static/app.js -> extras412()` 在训练任务、训练资源、自动迭代页面都会请求 training_options。

`TrainingCreateHydrationRuntime` 也把它作为训练创建所需 common input；虽然该 runtime 已正确提供 5 分钟 TTL 和 in-flight 去重，但首次 hydration、缓存过期、force refresh 仍必须等待这一个后端请求完成。

训练资源保存/检测后也会再次刷新 training_options。

因此前端已有缓存只能减少请求次数，不能解决单次请求自身被外部网络和递归磁盘扫描阻塞的问题。

**为什么不是 AUDIT-022：**

AUDIT-022 关注的是 legacy server 被返回为 ready target，但 Durable Training 实际由 Central Scheduler/Service Node owner 执行，属于资源语义错误。

AUDIT-101 关注的是同一个 legacy compatibility 列表在**读取配置时同步做网络探测**，把外部服务器健康延迟直接放进用户页面关键路径。

即使后续只把 legacy server 标成诊断用途，只要 training_options 继续同步探测它们，首开卡顿仍存在。

**与 AUDIT-100 的关系：**

AUDIT-100 是 training_options 间接调用的其中一个 filesystem 放大器；AUDIT-101 是整个 Training Options 聚合接口的同步 I/O 设计问题，尤其是 N 台 legacy server 的串行远端请求。

**影响：**

- 训练任务/训练资源页面长时间 loading；
- 训练创建首次打开可能一直停在“正在读取训练资源”；
- 一台坏服务器增加约 4 秒尾延迟，多台线性叠加；
- Web worker/thread 被外部服务器故障拖住；
- 同时多个浏览器请求会重复向同一 legacy server 做 health GET，形成放大；
- Paddle 配置目录很大时再叠加递归 filesystem 扫描；
- 用户可能误判平台卡死并重复点击创建/刷新。

**现有安全点：**

TrainingCreateHydrationRuntime 的 5 分钟 TTL、project-scoped in-flight dedupe 和 AbortController 是正确的，不应回退或删除。这些只需要继续保留，问题应在后端 read model 收口。

**为什么现有测试没发现：**

现有 training hydration / training server frontend 测试主要验证 scoped refresh、TTL/in-flight、navigation fencing 和 payload，不会启动 20 个慢/不可达远端服务器测 API latency。

也没有看到“多 legacy server timeout + training_options 必须 bounded latency”的后端合同。

**建议最小修复：**

不要在 training_options 里新建另一套资源探测线程，也不要把 timeout 从 4 秒简单改成更小数字。

1. legacy remote health 应由已有 Resource Discovery / Service Node runtime 的后台采样 owner 维护 sampled truth；
2. training_options 只读取最近一次健康快照，不主动远程 GET；
3. stale snapshot 可以显示 UNKNOWN/STALE，并提供显式刷新，不阻塞普通页面 hydration；
4. Paddle 算法/权重发现也应读取 Resource Discovery cache，目录扫描只在显式 scan 或后台 discovery 执行；
5. project model 列表复用 AUDIT-100 修复后的直接 provenance/index；
6. Training Options GET 应成为 bounded read-only projection，不能做远端网络 I/O。

**回归测试建议：**

- 20 条 legacy server 配置，其中全部 health endpoint 超时，training_options 仍在固定短延迟内返回 cached/stale truth；
- 普通页面 hydration 不触发 requests.get(remote/health)；
- 显式资源刷新仍可更新 health snapshot；
- 大 PaddleDetection configs 目录不会在普通 training_options GET 中递归扫描；
- 5 分钟 frontend TTL/in-flight 去重合同保持；
- cluster_scheduler / Service Node 当前真实可用性仍正确展示。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-102 — Annotation GT commit 与 Material searchable projection 分属两个事务；并发合法写入可逆序投影，让素材页状态/标签倒退到旧版本

**级别：中～高**  
**模块：AnnotationRepository / MaterialRepository Projection / Concurrency / Material Pagination**

**现象：**

AnnotationRepository 已是正式 Annotation Ground Truth owner，MaterialRepository 内 annotation_state、annotation_scope、annotation_hash、annotated、box_count、labels 只是 searchable projection。

但 GT commit 与 Material projection 当前不是同一原子操作，也没有 projection generation / annotation version fence。

两条生产路径都存在相同窗口：

1. AnnotationRepository.upsert_many(project_material=True)：
   - 先在 annotations.sqlite3 中 BEGIN IMMEDIATE -> 写 GT -> COMMIT；
   - 事务释放后才调用 MaterialRepository.patch(projections)。

2. app 的 write_annotation / write_annotations_many：
   - 先用 project_material=False 写 canonical GT；
   - 得到 saved row 后构造 _v50_material_annotation_patch；
   - 再单独 material_store(project_id).patch(...)。

因此 Annotation DB 只保证 GT writer 的提交顺序，不能保证事务结束后的 Material side effect 顺序。

**真实竞态：**

同一 image 初始 version=5：

1. Writer A 提交 GT A -> version=6；
2. A 尚未 patch Material；
3. Writer B 基于 version=6 合法提交 GT B -> version=7；
4. B 先 patch Material -> projection=B；
5. A 后恢复执行，旧 projection A 再 patch；
6. 最终 AnnotationRepository=B/version7，但 MaterialRepository=A/version6 对应状态。

即使 A/B 都正确使用 expected_version，这个问题仍成立：它们可以是两个合法连续版本，只是 projection side effect 逆序完成。

**为什么不是无关缓存：**

v61 canonical Material API 直接使用 MaterialRepository：

- GET /api/v61/projects/{project_id}/materials
- GET /api/v61/projects/{project_id}/materials/ids

并支持 annotated / label / processing status / cursor 等过滤。

MaterialRepository._write_row() 还会同步重建 material_labels、material_annotation_scopes、annotated、box_count 等索引。

因此 stale projection 会真实影响：

- 素材页显示；
- 已标注/未标注筛选；
- label/scope 筛选与统计；
- 基于 /materials/ids?annotated=... 的批量选择和 AI target discovery。

**训练主链当前有安全缓冲：**

training_tasks::_selected_project_images() 在最终冻结训练输入前会再次从 AnnotationRepository 批量读取正式 GT，并覆盖 Material row 中的 annotation_state/scope/hash/boxes。

所以本问题不应表述为“训练一定使用旧 GT”；但训练前素材选择、AI 目标发现和其它只读 Material index 的 consumer 仍会看到漂移。

**现有测试缺口：**

test_annotation_repository_scope.py 覆盖单次写入后 GT 与 Material projection 一致；SQLite lifecycle 并发测试覆盖 repository 初始化/WAL/schema owner。

没有覆盖：

GT A commit -> GT B commit -> projection B -> projection A

这种两个合法 Annotation version 的 projection side effect 逆序。

**影响：**

- 素材页可显示旧 annotation_state / labels；
- annotated=false 可能重新包含已经正式标注的图片，导致重复 AI 标注；
- annotated=true / label filter 可能漏掉刚保存的素材；
- Material label/scope index 与 AnnotationRepository reference truth 不一致；
- 漂移已持久化进 SQLite，普通页面刷新不会自愈；
- 人工标注、AI Commit、Storage Rescan 等正式写入口并发越多，窗口越真实。

**与 AUDIT-099 的区别：**

AUDIT-099 是 Storage Rescan 在写 Annotation GT 本身时缺少 commit-time expected_version，可能产生 GT lost update。

AUDIT-102 是即使 GT 两次写入都完全合法，GT commit 后的 Material projection 仍可逆序，导致 derived index 落后于 canonical GT。

**建议最小修复：**

不要把 MaterialRepository 升格为第二 GT owner，也不要跨两个 SQLite 文件持长事务。

复用单一 projection primitive，增加单调 annotation_version：

1. Annotation commit 返回 canonical version；
2. Material projection 持久化 annotation_version；
3. MaterialRepository.patch_annotation_projection(...) 在同一 writer transaction 内仅允许当前 projection version < incoming version 时更新；
4. version 相等 + digest 相同幂等；
5. 当前 version > incoming version 时迟到旧 projection 必须 no-op；
6. payload、material_labels、material_annotation_scopes 同事务更新；
7. app manual write、AnnotationRepository direct projection、AI Commit、Storage Rescan 共用该 primitive；
8. 不新增第二 projection owner/poller。

**回归测试建议：**

至少覆盖 A(version6) / B(version7) GT 顺序提交后，让 B projection 先落盘、A 后到，最终 Material 必须保持 B；同时验证 annotated、label、scope indexes 不倒退，并保持 500-row batch bounded transaction。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-103 — system/recommendation 每次 GET 都同步启动 Python 并 import torch；首次训练创建把最多 8 秒 CUDA 探测放进表单打开关键路径

**级别：中～高**  
**模块：Training Create Hydration / System Recommendation / CUDA Probe / Web Latency**

**现象：**

当前 `GET /api/system/recommendation` 每次请求都会同步执行：

`subprocess.run([sys.executable, '-c', 'import json,torch; ...'], timeout=8)`

子进程需要完整启动 Python、import torch、调用 `torch.cuda.is_available()`，CUDA 可用时还会读取 `torch.cuda.get_device_name(0)`。

这虽然避免了损坏/缓慢的 CUDA runtime 直接冻结主 Web 进程，但普通 GET 本身仍会一直等待子进程结束；最坏到 8 秒 timeout 才返回“CUDA 探测超时”。

**真实前端关键路径：**

`TrainingCreateHydrationRuntime.start()` 在 `state.rec == null` 时把：

- `/api/training_options?project_id=...`；
- `/api/system/recommendation`；

并行放进训练创建 hydration。

现有 `tests/frontend/training-create-hydration.test.mjs` 还明确保护：首次训练打开会先显示 shell，必须等 options 和 recommendation 两个 promise 都完成后才调用 canonical `openTrainingForm()`。

因此 recommendation 不是后台装饰信息；首次训练创建实际会等待它。

前端已经有正确的缓存行为：一旦 `state.rec` 有值，后续内部打开不会再请求 recommendation。问题是**第一次请求本身做昂贵的实时硬件探测**。

**为什么不是 AUDIT-101：**

AUDIT-101 是 `/api/training_options` 在 GET 内串行探测 legacy remote servers、递归扫描 Paddle/模型资源，最坏可被外部网络拖到约 80 秒以上。

AUDIT-103 是另一个独立 endpoint：即使 training_options 完全优化成 bounded cache read，首次 TrainingCreateHydration 仍要等 `/api/system/recommendation` 的 Python+torch 子进程，最长约 8 秒。

**影响：**

- 首次打开训练创建弹窗会长期停在“正在准备训练配置”；
- Windows / CUDA runtime 初始化慢时尤为明显；
- 没有 GPU 的控制端也要为每次冷 recommendation 请求 import torch；
- 多浏览器/多用户同时首次进入训练时会并发启动多个 Python+torch 子进程；
- 子进程会额外占 CPU、内存和 DLL/动态库加载 I/O；
- 用户容易把“硬件推荐探测慢”误认为训练弹窗或训练资源接口卡死。

**现有安全点：**

- child process + timeout 的 fail-safe 方向是对的，不能改回 Web 进程内直接 import/probe；
- TrainingCreateHydrationRuntime 的 state cache / in-flight 行为也应保留；
- 问题在于把硬件发现放在同步 read endpoint，而不是已有 sampled/cached resource truth。

**为什么现有测试没发现：**

前端 hydration 测试只用可控 Promise mock recommendation，并验证并行等待/缓存，不会运行真实 Python+torch。

当前没有看到后端合同要求 `/api/system/recommendation`：

- 不启动新 Python 进程；
- 使用缓存硬件 truth；
- 在固定短延迟内返回。

**建议最小修复：**

不要简单把 8 秒 timeout 改成 1 秒，也不要在前端复制 GPU 探测逻辑。

1. GPU/CUDA 可用性由已有 Resource Discovery / Service Node / scheduler resource truth 的后台采样 owner维护；
2. `/api/system/recommendation` 只读取最近一次 sampled hardware snapshot 并计算 recommendation；
3. snapshot 缺失或 stale 时快速返回 `cuda=unconfirmed`，后台触发/提示显式资源扫描；
4. 本机控制端无 GPU 不应影响远程 scheduler-owned Training target；
5. 显式“重新检测资源”可以启动 Durable Resource Discovery，但普通训练创建 GET 不得等待 torch import。

**回归测试建议：**

- monkeypatch `subprocess.run` 为慢调用，普通 recommendation GET 不应直接触发它；
- 无缓存硬件 truth 时快速返回 unconfirmed recommendation；
- 后台 discovery 完成后 recommendation 能读取新 GPU truth；
- 首次 TrainingCreateHydration 不因 CUDA probe 阻塞 8 秒；
- 后续 `state.rec` 缓存复用合同保持；
- Windows CPU-only、Linux GPU、远程 scheduler 三种场景均覆盖。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-104 — Storage Rescan 正式 Annotation 提交与 task-owned applied marker 分离；GT 已成功后崩溃会在恢复时把自己的提交判成外部冲突并把任务置 FAILED

**级别：高**  
**模块：Storage Rescan / Annotation Ground Truth / Crash Recovery / Idempotency**

**现象：**

当前 Storage Rescan 的外部标注 apply 流程把“正式业务提交”和“任务自己已处理该 delta 的 checkpoint”分成了多个独立事务。

`StorageRescanHandler._apply_annotation_rescan()` 对每批最多 500 条 delta 的真实顺序是：

1. `store.pending_annotation_deltas(...)` 读取 `applied=0`；
2. 读取当前 Material / Annotation；
3. 校验 review 时冻结的 `platform_annotation_hash / state`；
4. `annotations.upsert_many(annotation_rows, return_rows=True)` —— **正式写 AnnotationRepository GT**；
5. `materials.patch(patches)` —— 写 external_annotation provenance / Material projection；
6. `store.mark_annotation_applied(batch)` —— 最后才把 task-owned manifest 中 delta 标成 `applied=1`；
7. `context.check(force=True)`。

这三个写入分别属于：

- AnnotationRepository SQLite；
- MaterialRepository SQLite；
- RescanCandidateStore task manifest SQLite。

它们之间没有原子 receipt。

**真实崩溃窗口：**

假设 review 时平台标注为 A，Rescan 确认要写外部标注 B。

1. Worker 读取 pending delta；
2. stale-review 校验通过；
3. `AnnotationRepository.upsert_many()` 已成功把正式 GT 从 A 写成 B；
4. 进程在 `mark_annotation_applied()` 前退出、机器重启、Worker 被杀或 Python 崩溃；
5. task manifest 中该 delta 仍是 `applied=0`；
6. Durable Task recovery 调 `StorageRescanHandler.recover()`；
7. `recover()` 对 storage_rescan 只是再次 `run(context)`；
8. accepted task 再次进入 `_apply_rescan() -> _apply_annotation_rescan()`；
9. 同一个 delta 再次被 `pending_annotation_deltas()` 取出；
10. 此时 `current_hash/current_state` 已经是本任务上一次成功写入的 B；
11. 但 delta 内冻结的 `platform_annotation_hash/state` 仍是 review 时的 A；
12. 代码命中：
   `platform annotation changed after rescan review; create a new rescan`；
13. `run()` 捕获 ValueError，写入 `STORAGE_RESCAN_CONFLICT`，最终返回 `TaskStatus.FAILED`。

结果是：

**任务报告 FAILED，但它已经修改了正式 Annotation Ground Truth。**

如果崩溃发生在 Annotation GT commit 之后、`materials.patch(patches)` 之前，还会形成：

- AnnotationRepository 已是 B；
- external_annotation provenance / Material projection 仍可能是旧值；
- recovery 又因为自己的 GT commit 与 review hash 不同而拒绝继续补齐。

**为什么是 Bug / crash consistency：**

Durable task 的 recover 合同要求 side effect 可以：

- 原子提交；或
- 通过 idempotency receipt 在重放时识别“这是自己已经完成的提交”。

当前 Rescan annotation path 两者都没有。

`applied=1` 本来承担 task checkpoint，但它发生在 canonical GT commit 之后，而且存放在另一个 SQLite 文件，因此存在不可避免的 crash gap。

**与 Material metadata reconcile 的对比：**

同一个 Storage Rescan 的 `MaterialRepository.reconcile_storage_batch()` 已经有更接近正确的幂等机制：

- 使用 `material_storage_audit`；
- key 包含 `task_id + image_id`；
- 重放时已存在 audit 的 material 不会再次应用。

Annotation path 没有等价的、与正式 GT 同 owner 提交的 operation receipt。

**与已有问题的区别：**

- AUDIT-099：在 stale check 通过后，另一个人工 writer 可以抢先修改 GT；Rescan 因缺少 commit-time `expected_version` 仍可能覆盖对方——这是并发 lost update。
- AUDIT-102：两个合法 GT version 的 Material projection side effect 可逆序——这是 derived projection monotonicity。
- AUDIT-104：**没有任何其他 writer 也会发生**；同一 Rescan 自己已经成功写 GT，但由于 applied marker 没和 GT 原子记录，崩溃恢复把自己的提交误认成外部变化并把任务置 FAILED。

三者触发条件和修复层不同。

**影响：**

- 正式 Annotation 已改变，但任务状态显示 FAILED；
- 用户可能认为失败后“没有生效”，再次创建 Rescan 或手工修改，造成二次变更；
- 崩溃发生在 GT commit 与 provenance patch 之间时，GT / Material provenance 可长期不一致；
- 10k / 20k rescan 以 500 条 batch 多次提交，批次数越多，暴露于 commit-marker crash window 的次数越多；
- 修复 AUDIT-099 时如果只简单加 `expected_version`，恢复重放反而会更稳定地冲突，因为旧 expected_version 已被本任务自己的首次 commit 消耗；
- Durable Task 的“失败/成功”语义不再代表业务 side effect 是否发生，影响审计与人工处置。

**现有测试为什么没发现：**

`tests/unit/storage/test_rescan_tasks.py` 已覆盖：

- stale platform annotation 在 apply 前被拒绝；
- YOLO / COCO / VOC delta 分类与正常 apply；
- remote rescan review；
- canonical evidence 防篡改。

但当前没有覆盖：

`Annotation GT commit 成功 -> 进程在 mark_annotation_applied 前退出 -> recover`

也没有“同一 task replay 必须识别已提交 Annotation side effect”的 idempotency 测试。

**建议最小修复：**

不要把 `mark_annotation_applied()` 简单提前到 GT commit 之前；那会把问题反转成：

`applied=1` 已写，但 GT 尚未写就崩溃，恢复将永远跳过真正业务提交。

应让 canonical Annotation owner 同时拥有一个可恢复的 idempotency receipt，最小方向：

1. 为 Rescan annotation apply 生成稳定 operation identity，例如：
   `task_id + object_key/image_id + confirmed source_digest/policy generation`；
2. AnnotationRepository 在**与 GT 写入同一个 SQLite transaction**中记录 operation receipt；
3. receipt 保存至少：
   - task_id / operation token；
   - image_id；
   - resulting annotation version；
   - resulting content_digest；
   - intended external source digest；
4. recovery 重新遇到 `applied=0` 时：
   - 若同 task receipt 存在，且当前 GT 仍匹配 receipt，视为“业务提交已完成”，只补齐缺失 Material provenance，然后安全地 `mark_annotation_applied`；
   - 若 receipt 存在但当前 GT 已被后续人工 version 改变，fail-closed，不能再覆盖；
   - 若 receipt 不存在，才走正常 review hash + expected_version CAS；
5. receipt 必须跟 Annotation GT 原子提交；如果只写 ArtifactStore / RescanCandidateStore，仍会重建同一个 crash gap；
6. 保持每批 <=500，不能引入逐图事务或 N+1；
7. 与 AUDIT-099 的 expected_version 修复一起设计，但不要新增第二 Annotation owner。

**回归测试建议：**

至少增加：

- GT commit 后、Material provenance 前模拟 crash；
- GT + provenance 后、mark_annotation_applied 前模拟 crash；
- recover 后任务可完成，且 GT 不重复增 version；
- same-task receipt + current GT match → idempotent resume；
- same-task receipt 存在但用户随后人工修改 GT → recover 必须拒绝覆盖用户新 version；
- 500-row batch 中部分已 receipt、部分未提交时可安全续跑；
- final task status 与真实 side effects 一致。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-105 — Detection Batch 恢复态遗漏 BLOCKED_BY_ENVIRONMENT / BLOCKED_BY_HARDWARE；后端已终止的部署测试刷新后会被前端重新显示成“运行中”

**级别：中～高**  
**模块：Quality Center / Deployment Test / Detection Batch / Durable Task Status Contract**

**现象：**

Deployment Test 使用 canonical Durable Task 状态机，Worker 可以真实把任务结束为：

- `BLOCKED_BY_HARDWARE`
- `BLOCKED_BY_ENVIRONMENT`

例如 `platform_core/deployment/inference_tasks.py::run_deployment_test()` 明确：

- 对 `.rknn / .om / .bmodel` 本地缺板端 Runtime 时抛 `HardwareUnavailableError`；
- 对不支持的 Runtime / runner 缺失时抛 `EnvironmentError`；
- `.engine` 执行失败也可转为 `HardwareUnavailableError`。

`Scheduler.run_once()` 又明确映射：

- HardwareUnavailableError -> `TaskStatus.BLOCKED_BY_HARDWARE`
- EnvironmentError -> `TaskStatus.BLOCKED_BY_ENVIRONMENT`

所以这两个状态对 Deployment Test 是真实生产 terminal truth。

但 Detection Batch 的后端摘要和前端恢复逻辑各自又维护了一套过期 terminal 枚举。

**后端漂移：**

`_public_detection_batch()` 计算 `completed_items` 时只认：

`SUCCEEDED / FAILED / CANCELLED`

因此一个模型侧已经：

`BLOCKED_BY_ENVIRONMENT`

或：

`BLOCKED_BY_HARDWARE`

的 item 不会被计入 completed。

`failed_items` 也只统计严格的 `FAILED`，blocked 没有任何独立计数。

但同一文件中的人工复核 endpoint 已经把 canonical terminal truth 写对了：

`review_detection_batch_item()`

的 `terminal` 集合明确包含：

- SUCCEEDED
- PARTIAL_SUCCESS
- FAILED
- CANCELLED
- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE

即同一个 Detection Batch owner 内部已经出现两套不同 terminal 定义。

**前端漂移：**

`static/app.js::batchFromDurable64()` 恢复历史批次时：

`pending = statuses.some(status => !['SUCCEEDED','FAILED','CANCELLED'].includes(status))`

随后：

`status = pending ? 'running' : failed ? 'failed' : 'done'`

所以 blocked task 会满足：

`pending === true`

最终恢复成：

**running**

这和后端 Durable Task 真相完全相反。

**真实用户链路：**

1. 用户在质量中心发起检测；
2. Deployment Test 因 Runtime/硬件不满足进入 BLOCKED_BY_ENVIRONMENT 或 BLOCKED_BY_HARDWARE；
3. 当前页面的 `benchPredictOne()` 通过 canonical task poller 能识别 terminal；因为不是 SUCCEEDED，会抛错，本次内存态行暂时显示 failed；
4. 用户刷新页面，或稍后从“历史检测批次”重新打开；
5. 后端 `_public_detection_batch()` 不把 blocked 算 completed；
6. 前端 `batchFromDurable64()` 又把 blocked 判为 pending；
7. 已经终止的检测重新显示为“运行中”。

因此这是一个稳定的“即时态与恢复态不一致”。

**为什么不是 AUDIT-088：**

AUDIT-088 是 UploadTaskCenter 复制了一套过期 Durable 状态枚举，影响 ZIP / Storage Import 等后台上传任务。

AUDIT-105 是 Quality Center Detection Batch 自己再次复制 terminal 集合，影响 Deployment Test 的服务器聚合与历史恢复。

两个 UI owner、API owner 和修复位置完全不同；修复 UploadTaskCenter 不会改变 `_public_detection_batch()` 或 `batchFromDurable64()`。

**影响：**

- 已 blocked 的检测历史永久显示“运行中”；
- 批次 `completed_items` 永远小于真实 terminal item 数；
- “X / N 张已完成”的历史摘要失真；
- blocked 不计 failed，用户看不到批次真实异常数量；
- 页面刷新前显示 failed，刷新后却变 running，形成明显前后端/恢复态漂移；
- 用户可能误认为 Worker 仍在执行，反复等待或重新发起检测；
- 批次完成度如果后续用于自动操作/按钮 enable 条件，会进一步把 terminal task 当 active。

**现有测试为什么没发现：**

当前：

- `tests/browser/quality-detection-workbench.spec.mjs`
- `tests/frontend/quality-detection-center.test.mjs`
- `tests/api/test_deployment_test_runtime.py`

均没有覆盖：

- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE
- PARTIAL_SUCCESS

的 Detection Batch 恢复投影。

现有测试主要覆盖成功/失败检测、A/B 模式、历史恢复与人工 review，但没有跨 canonical TaskStatus terminal set 做合同测试。

**建议最小修复：**

不要再给 Detection Batch 手写第三套 terminal 字符串表。

1. 后端 `_public_detection_batch()` 使用 canonical `TERMINAL_STATUSES` / 统一 public task status helper；
2. completed_items 应统计所有真正 terminal 状态；
3. blocked 可以：
   - 纳入 failed_items；或
   - 更清晰地新增 blocked_items；
   但不能算 running；
4. 前端 `batchFromDurable64()` 复用 `task-runtime-truth.js` 的：
   - canonicalTaskStatus
   - isCanonicalTaskActive
   - isCanonicalTaskTerminal
5. blocked row 显示明确“环境不可用 / 硬件不可用”，而不是统一伪装成普通 FAILED；
6. PARTIAL_SUCCESS 也必须按 canonical terminal 处理，避免下一轮再次漂移。

**回归测试建议：**

至少覆盖：

- 单侧 BLOCKED_BY_ENVIRONMENT；
- 单侧 BLOCKED_BY_HARDWARE；
- A 成功 + B blocked；
- 后端 completed_items 正确；
- blocked_items / failed presentation 正确；
- 页面刷新前后的 row status 一致；
- 从历史批次恢复后 blocked 不显示 running；
- canonical PARTIAL_SUCCESS terminal 合同也纳入测试。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-106 — Detection Batch 只持久化成功创建的 side，没有 batch-level expected sides；compare 第二侧在 Task 创建前失败后，刷新会把原本失败的图片恢复成完成

**级别：高**  
**模块：Quality Center / Detection Batch / Deployment Test Creation / Durable Recovery**

**现象：**

质量中心的 A/B compare 模式在浏览器里按图片串行创建两个独立 Deployment Test：

1. 先 `benchPredictOne(... side='A')`；
2. A 完成后再 `benchPredictOne(... side='B')`；
3. 任一侧抛错，当前内存态 row 进入 `failed`。

但服务端没有 Detection Batch header / manifest，也没有持久化：

- 本批次 mode 是 compare / a / b；
- 每个 item 的 expected_sides；
- 哪一侧在 Durable Task 创建前失败。

每个已成功创建的 Deployment Test request 只保存：

- batch_id；
- item_index；
- item_total；
- side；
- original_filename。

因此服务器只能知道“实际存在了哪些 task”，不知道“原本应该存在哪些 task”。

**真实可达失败链：**

compare 模式中 A 已经成功创建并完成后，B 的 `POST /deployment-tests` 在 `TaskRepository.create()` 之前有多个真实失败点：

- `_resolve_v61_test_model()` 找不到模型；
- Runtime / inference environment 解析失败；
- 输入/批次参数校验失败；
- remote execution staging 抛 `RemoteExecutionTransportError`；
- request artifact 写入失败；
- repository create 前的其它 I/O/环境错误。

尤其 remote staging 当前明确发生在：

`shared_task_repository().create(...)`

之前；失败时还会删除刚写的 input 文件并直接返回 PlatformError。

所以 B 可以做到：

**从未形成任何 Durable TaskRecord。**

此时浏览器当前页面知道这是 compare，并把图片标成 failed；但服务端历史中只剩一个成功的 A task。

**刷新后的错误恢复：**

`_public_detection_batch()` 只按真实存在的 task 分组：

`item["models"][side] = public_result`

如果只有 A，它无法知道 B 缺失是错误还是用户本来就选择 A-only。

随后：

- `completed_items` 只检查 `item["models"]` 中已经存在的模型；
- A=SUCCEEDED 时该 item 会被算作 completed；
- `failed_items` 也不会增加。

前端 `batchFromDurable64()` 同样只读取：

`item.models.A / item.models.B`

如果历史中只有成功 A：

- statuses = [SUCCEEDED]
- pending = false
- failed = false
- row.status = done

于是同一张 compare 图片：

**运行当时 = failed**  
**刷新/历史恢复后 = done**

B 侧只显示“—”，与合法的 A-only 检测无法区分。

**额外影响：人工复核也无法识别 compare 不完整：**

`review_detection_batch_item()` 只遍历当前能找到的 rows。

如果 compare 的 B 根本没有 TaskRecord，而 A 已 SUCCEEDED：

- 所有“现存 rows”都 terminal；
- 至少一个现存 row 成功；
- review endpoint 会允许人工核验。

也就是说一个本应是“A/B 对比失败”的 item，可以在刷新后被当成完整结果继续人工复核。

**为什么不是已有问题：**

- AUDIT-036：Detection Batch 用全项目 DEPLOYMENT_TEST bounded scan 代替 batch index，导致任务存在但扫描不到。
- AUDIT-105：任务已经存在且 terminal，但 BLOCKED_* 枚举被恢复层误判为 running。
- AUDIT-106：**目标 side 连 TaskRecord 都没有创建成功，而 batch intent 又从未 durable 化**。服务端根本不知道缺失 side 是异常还是设计如此。

修复 036/105 都不能恢复缺失的 compare intent。

**现有测试为什么没发现：**

`tests/browser/quality-detection-workbench.spec.mjs` 当前覆盖：

- compare A/B 都创建成功；
- A-only；
- B-only；
- 正常历史 batch 恢复；
- 人工 review。

它明确验证 compare 会发送 A、B 两次请求，但没有覆盖：

`A success -> B create request fails before task_id -> reload history`

前端/unit/API 测试也没有 `expected_sides` / batch manifest 合同。

**影响：**

- compare 的真实失败在刷新后变成“完成”；
- completed_items / failed_items 与真实用户意图不一致；
- 历史记录不再具备审计可信度；
- 缺失 B 无法与 A-only 区分；
- 不完整 compare item 可进入人工核验；
- 用户可能基于单侧结果误认为 A/B 对比已完成；
- 批量 1k/10k 图片时，任何局部 create/staging 失败都可能被历史恢复静默洗掉。

**建议最小修复：**

不要新增第二 Scheduler，也不要把 Detection Batch 做成另一套任务系统。

应增加单一、轻量的 batch intent owner：

1. 在创建第一条 side task 之前，先持久化 batch header/manifest；
2. 至少冻结：
   - batch_id；
   - mode = compare/a/b；
   - total item count；
   - 每 item expected_sides；
   - original_filename / stable item identity；
3. side task 创建成功后把 task_id 绑定到对应 item+side；
4. side 创建失败也要持久化 creation_failed/error，不能只留在浏览器内存；
5. `_public_detection_batch()` 按 manifest 聚合：
   - expected side 缺失不能算 complete；
   - compare 缺任一 side 必须显示 incomplete/failed；
6. review endpoint 必须按 expected_sides 校验完整性；
7. 前端恢复不能通过“现在有哪些 task”反推当初 mode；
8. manifest 只承担 batch aggregation intent，不成为 Deployment Test 执行 owner。

**回归测试建议：**

至少覆盖：

- compare：A SUCCEEDED，B 在 TaskRepository.create 前返回 4xx/5xx；
- 刷新后 item 仍为 failed/incomplete；
- completed_items 不增加为完整 compare；
- review 被拒绝；
- A-only 只有 A 时仍正确 done；
- B-only 只有 B 时仍正确 done；
- compare A+B 都成功时正常 done；
- 1k item 下 manifest/query bounded，不重新引入全项目 scan。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-107 — Quality Center “停止检测”只停止浏览器后续循环，不取消当前 Durable Deployment Test；GPU/Worker/板端任务会继续执行到终态

**级别：中～高**  
**模块：Quality Center / Detection Batch / Deployment Test Cancellation / Frontend Runtime**

**现象：**

质量中心批量检测运行期间，页面明确显示：

`停止检测`

按钮，并绑定：

`stopBenchBatch64()`

但当前实现只有：

`state.benchBatch64.cancelled = true`

没有记录当前正在等待的 Deployment Test task_id，也没有调用已经存在的 canonical 后端取消接口：

`POST /api/v61/projects/{project_id}/deployment-tests/{task_id}/cancel`

因此“停止检测”只会阻止后续 side / 后续图片继续创建，无法取消当前已经创建并正在执行的 Durable Task。

**真实调用链：**

`runBenchBatch64()`

对每张图片：

1. row 进入 running；
2. `await benchPredictOne(...)`；
3. `benchPredictOne()` 创建 Deployment Test；
4. 获得 task_id；
5. 调：
   `taskPoller.waitForTaskTerminal(... delay=900, maxAttempts=700)`
6. 一直等待该 task 成为 terminal；
7. await 返回后，外层代码才再次检查：
   `if (run.cancelled) break`。

所以用户在第 5 步点击“停止检测”时：

- 浏览器只修改一个本地 boolean；
- 当前 await 不会被中断；
- 当前 task 不会 request_cancel；
- Worker/GPU/远程板端任务继续运行；
- PollRegistry 继续轮询；
- 最多等当前 side 结束后才停止进入下一 side / 下一图片。

compare 模式尤其明显：

- A 正在运行时点停止：A 继续跑完，但 B 不再创建；
- B 正在运行时点停止：B 继续跑完；
- 单模型模式：当前检测仍完整跑完。

**后端其实已经有正确 lifecycle owner：**

`cancel_deployment_test()`

明确：

`shared_task_repository().request_cancel(task_id)`

Deployment Test Worker 又会在进程循环内检查：

`context.cancel_requested()`

并安全终止 bound process。

所以缺口不在后端能力，而在前端“停止”动作没有连接 canonical cancellation owner。

**为什么是 Bug / 前后端动作合同漂移：**

UI 文案是“停止检测”，不是“本张完成后停止后续图片”。

用户合理预期当前正在执行的推理也会停止。

而当前实际语义是：

“设置 stop-after-current 标记”。

不仅文案与行为不一致，还绕过了已有 Durable cancellation contract。

**资源影响：**

Deployment Test 最长轮询配置当前约为：

`700 × 900ms ≈ 10.5 分钟`

实际 Worker/远程任务可持续较长时间。

用户已经明确停止后，仍可能继续占用：

- GPU；
- deployment.runtime Worker；
- 远程板端执行资源；
- 进程/日志/输出 I/O；
- PollRegistry 网络请求。

在 1k/10k 图片批量检测中，停止动作通常就是为了立即释放资源；当前行为达不到目的。

**额外 UI 不一致：**

`stopBenchBatch64()` 本身也不调用 `summary64()` / render。

所以点击按钮后，当前 summary 不一定立即切换成“本次检测已停止”，而是继续显示运行态，直到当前 await 最终结束并进入 finally。

这进一步强化了“按钮点了但没有真正停止”的体验问题。

**现有测试为什么没发现：**

当前：

- `tests/browser/quality-detection-workbench.spec.mjs`
- `tests/frontend/quality-detection-center.test.mjs`

没有覆盖：

- stopBenchBatch64；
- “停止检测”按钮；
- Deployment Test cancel endpoint；
- RUNNING -> CANCEL_REQUESTED -> CANCELLED 的质量中心 UI。

浏览器验收只覆盖正常 compare / A-only / B-only 完成路径。

**建议最小修复：**

不要新增第二 cancel owner。

继续使用现有：

- TaskRepository.request_cancel；
- Deployment Test cancel API；
- canonical task poller。

前端只需要把当前执行身份纳入 batch runtime：

1. `benchPredictOne()` 创建 task 后立即把 task_id 写入当前 run/row/side；
2. `stopBenchBatch64()`：
   - 先设置 batch cancelled，阻止后续创建；
   - 若存在当前 active task_id，POST canonical cancel endpoint；
3. 继续通过 taskPoller 等待最终 CANCELLED，不要在 CANCEL_REQUESTED 时假装已经结束；
4. stop 操作应立即 rerender summary，显示“正在停止当前检测…”；
5. cancel API 失败时明确提示，并继续展示真实 Durable 状态；
6. compare 模式只取消当前 active side，不创建尚未开始的另一 side；
7. project switch / 页面卸载不要偷偷自动 cancel，除非产品明确要求；本问题只修显式用户 Stop。

**回归测试建议：**

至少覆盖：

- A running 时点击停止 -> 发 exactly one cancel POST；
- task 先 CANCEL_REQUESTED 后 CANCELLED，前端保持真实过渡；
- compare 模式 A 被取消后 B 不创建；
- B running 时停止只取消 B；
- A-only / B-only 同样取消当前 task；
- cancel API 失败时显示错误且不伪装“已停止”；
- 重复点击停止不重复 cancel；
- 已 terminal task 不再发 cancel。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-108 — Online Feedback confirm 在终态 CAS 前先写 Material/Annotation；并发 dismiss 可赢得 finalize，形成“反馈已忽略但正式真值已被写入”

**级别：高**  
**模块：Online Feedback / Human Review / Annotation Ground Truth / Concurrency**

**现象：**

当前线上抽检反馈的 Confirm 与 Dismiss 共用：

`OnlineFeedbackRepository.finalize()`

作为 feedback row 的终态 owner。

Repository 自身使用 `BEGIN IMMEDIATE`，单纯状态更新是串行的；但 Confirm 的业务副作用并不在这个终态事务内，而是发生在 finalize **之前**。

Confirm 的真实顺序：

1. `repository.get(feedback_id)`，确认当前是 `pending_review`；
2. 校验 prediction evidence；
3. 查找或创建 Material；
4. 对 `correct / false_positive`：
   - 调 `write_annotation()` 写正式 Annotation Ground Truth；
5. 更新 Material processing state / online_feedback_refs；
6. 最后才调用：
   `repository.finalize(... status='confirmed')`。

Dismiss 的顺序则很短：

1. `repository.get()` 看见 pending_review；
2. 直接：
   `repository.finalize(... status='dismissed')`。

因此两者之间存在真实竞态窗口。

**更关键的 Repository 行为：**

`OnlineFeedbackRepository.finalize()` 发现当前记录已经是任意 terminal 时：

`if current["status"] in TERMINAL_STATUSES: return current, True`

它不会验证：

“当前 terminal 是否等于本次调用想提交的 `status`”。

所以 Confirm 最后想提交 confirmed 时，如果 Dismiss 已先提交 dismissed，Confirm 不会冲突，而是把 dismissed 当成“幂等成功”。

**真实竞态：**

1. 浏览器 A 打开反馈并点击“确认”；
2. Confirm 读取到 pending_review；
3. Confirm 已把预测框写入 AnnotationRepository，或已把素材写成 confirmed_empty；
4. 在 Confirm 调 finalize 前，浏览器 B 仍基于旧页面点击“忽略”；
5. Dismiss 也曾读到 pending_review，并抢先 `finalize(status='dismissed')`；
6. Confirm 随后调用 `finalize(status='confirmed')`；
7. Repository 看到已经 terminal=dismissed，直接返回 `idempotent=True`；
8. Confirm API 也返回 `ok:true`，但返回的 feedback 实际是 dismissed。

最终状态：

- Online Feedback：**已忽略**
- Annotation Ground Truth：**已经被 Confirm 写入/修改**
- Material processing / online_feedback_refs：也可能已经按 Confirm 路径更新

这是明确的业务状态 split-brain。

**反向竞态也存在：**

Dismiss 先读取 pending_review 后，Confirm 抢先 finalize=confirmed；随后 Dismiss 调 finalize(dismissed) 时，同样会把 confirmed 当成 idempotent terminal 返回。

虽然这个方向不会撤销已经确认的 side effect，但 Dismiss API 仍可能返回 `ok:true`，即“用户点击忽略看似成功，实际上记录已确认”。

**为什么是高风险：**

线上反馈设计的核心合同是：

- pending_review：不修改正式训练真值；
- confirmed：人工确认后才允许写 Material / Annotation；
- dismissed：明确不进入正式真值链。

AUDIT-108 直接破坏这个合同：反馈最终是 dismissed，却仍可能产生正式 GT side effect。

这会影响后续：

- 训练 Snapshot；
- Supplement Feedback Candidate；
- Material processing_status；
- negative sample / confirmed_empty；
- label reference；
- 审计解释。

**为什么已有幂等保护不够：**

Confirm 当前对“GT 已经由同一次确认写入，但 finalize 失败后重试”有 matching-truth 恢复：

- existing annotated boxes 与 prediction 一致时承认；
- confirmed_empty 已存在时不重复写。

这能处理单线程 crash/retry，但不能区分：

- 同一次 Confirm 的恢复；
- 另一个 Dismiss 已经取得终态所有权。

缺的是 feedback lifecycle 的 commit ownership，不是 Annotation 内容幂等。

**现有测试为什么没发现：**

当前测试覆盖：

- normal confirm；
- confirm idempotency；
- existing matching/different truth；
- pending feedback 可 dismiss 且无 side effect；
- 标签 retirement 与 truth commit；
- browser confirm/dismiss 正常流程。

但没有覆盖：

`confirm side effect 已发生但 finalize 未执行 -> concurrent dismiss finalize -> confirm finalize`

也没有测试：

“finalize(desired=confirmed) 遇到 terminal=dismissed 必须冲突，而不是 idempotent”。

**建议最小修复：**

不要新增第二 Online Feedback owner。

最小方向应把“谁拥有本次终态提交权”前置冻结：

1. OnlineFeedbackRepository 增加明确的 review claim / transition，例如：
   `pending_review -> confirming`
   或带 generation/token 的 CAS；
2. Confirm 必须先原子取得 confirming ownership，之后才允许写 Material/Annotation；
3. Dismiss 只能从 `pending_review` 原子转 dismissed，不能跨过 confirming；
4. Confirm 完成业务副作用后再：
   `confirming -> confirmed`；
5. 如果业务副作用失败，明确回滚到 pending_review 或进入 recoverable confirming 状态；
6. `finalize()` 的“terminal 即幂等”必须校验 terminal 与 desired status 一致：
   - confirmed + desired confirmed -> idempotent；
   - dismissed + desired dismissed -> idempotent；
   - confirmed vs dismissed -> 409 conflict；
7. recovery 要用稳定 operation token，避免重复 GT 写入；
8. 不应通过在整个 Material/Annotation 操作期间持有 OnlineFeedback SQLite write lock 来解决，以免形成长事务和跨库死锁风险。

**回归测试建议：**

至少覆盖：

- Confirm 取得 ownership 后 Dismiss -> 409；
- Dismiss 先成功后 Confirm -> 409 且无 Material/Annotation side effect；
- Confirm 已写 GT、finalize 暂时失败后的 same-operation retry 可恢复为 confirmed；
- terminal confirmed 再 Confirm -> idempotent；
- terminal dismissed 再 Dismiss -> idempotent；
- terminal confirmed 再 Dismiss / terminal dismissed 再 Confirm -> 必须 conflict；
- correct / false_positive / needs_correction 三类反馈；
- 两线程/barrier 真实并发测试，不只顺序模拟。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-109 — Deployment Resource PATCH / DELETE 未冻结 Remote Conversion 依赖；已创建任务可在启动竞态中改投新服务器 / 新 API Key 或直接失败

**级别：高**  
**模块：Deployment Resource / Remote Conversion / SecretStore / Task Dependency Lifecycle**

**现象：**

v39 创建部署转换任务时，用户已经明确选择：

- `resource_id`；
- 远程转换服务器；
- 对应 API Key；
- 已检测通过的 target capability。

任务也会在 `job.json` 中保存：

- `resource_id`；
- `resource` snapshot。

但这个 snapshot 实际来自：

`_deploy_resource_public(resource)`

它会明确删除：

- `api_key`；
- `secret_ref`。

因此 `mode=remote` 的真实执行线程不能只依赖任务快照，而是在稍后进入：

`_sync_remote_deploy_job(project_id, job_id)`

时重新调用：

`_deploy_resource_by_id(job["resource_id"])`

并再次从当前 Deployment Resource / SecretStore 读取：

- 当前 `base_url`；
- 当前 `secret_ref`；
- 当前 API Key。

与此同时：

`PUT /api/v39/deploy/resources/{resource_id}`

和：

`DELETE /api/v39/deploy/resources/{resource_id}`

都没有检查该资源是否被 QUEUED / RUNNING remote conversion 引用。

DELETE 还会立即删除：

`SecretStore[secret_ref]`。

**真实可达竞态：**

创建 remote conversion：

1. API 校验当前资源为 ready；
2. 写入 job.json；
3. 创建 daemon thread：
   `threading.Thread(target=_sync_remote_deploy_job, ...).start()`；
4. HTTP 创建请求已经可以返回；
5. 线程随后才重新按 resource_id 读取 Deployment Resource。

在 3～5 之间，用户或另一个请求可以：

- PUT 同一个 resource，修改 base_url / kind / tool config / API Key；
- DELETE resource，并删除 secret_ref。

于是同一已创建 job 可能出现：

**PATCH 场景：**

- 创建时用户选择服务器 A / Key A；
- 线程实际开始前资源被改成服务器 B / Key B；
- job 最终把源模型上传给 B，而不是创建时已确认的 A。

**DELETE 场景：**

- job 已成功创建；
- resource 随即被删除；
- `_sync_remote_deploy_job()` 再取 resource 时直接 404；
- remote conversion 在真正启动前失败。

这说明“用户提交时确认的执行资源”不是 frozen task dependency。

**为什么不是 AUDIT-024：**

AUDIT-024 记录的是：

> Remote Conversion 仍使用 daemon thread，形成第二执行 owner / 缺少 Durable 生命周期。

AUDIT-109 记录的是另一个独立合同：

> 即使暂时保留现有 remote thread，Deployment Resource / credential 也没有按任务创建时冻结，PATCH/DELETE 可以改变或销毁已接受任务的执行依赖。

把 remote conversion 改成 Durable Task 以后，如果仍然只保存 resource_id 并在执行时读取 mutable resource，这个问题依然会存在。

**为什么不是 AUDIT-046：**

AUDIT-046 是 auto-convert 对 vendor/chip/resource identity 冻结不足。

AUDIT-109 是用户已经明确创建一条 v39 remote conversion 后，Deployment Resource CRUD 对该具体已接受任务缺少 dependency fence，并且 secret 会被 DELETE 立即销毁。

**影响：**

- 已创建任务可能实际发送到不同于创建时确认的远程服务器；
- API Key 可在任务创建后被无提示替换；
- 删除资源可让刚受理的转换任务启动失败；
- 审计记录中的 `job.resource` 与真实执行 endpoint / credential 可能不一致；
- 如果远程转换服务器属于不同安全域，可能把模型发送到错误目标；
- 用户会看到“任务创建成功”，随后却因配置 CRUD 竞态失败，难以定位；
- 前后端都无法准确解释“这个任务到底冻结了哪一个执行资源版本”。

**现有代码为什么没有自动保护：**

任务中的 `resource` 使用 public projection：

`_deploy_resource_public()`

会剥离 credential identity。

remote runner 又不是从 immutable task artifact 获取 frozen endpoint + secret version，而是执行时重新：

`_deploy_resource_by_id(resource_id)`。

Deployment Resource PUT/DELETE 也没有 active reference query / CAS / retirement fence。

**建议最小修复：**

不要新建第二套 Deployment Resource owner。

应让 remote conversion 在 admission 时冻结“可执行资源引用”：

1. 至少冻结：
   - resource_id；
   - resource revision / updated_at；
   - mode / kind；
   - base_url identity；
   - secret_ref + immutable secret version / credential snapshot reference；
   - detected target capability；
2. remote execution 只能使用该 frozen execution contract；
3. Deployment Resource PATCH：
   - 只影响后续新任务；
   - 不得静默改变已受理任务；
4. Deployment Resource DELETE：
   - 若仍有未终态任务依赖该 resource / secret version，必须 409 fail-closed；
   - 或执行资源进入 retired 状态，待引用归零后 GC；
5. 不要把明文 API Key 写入 job.json；
6. 后续把 AUDIT-024 的 remote thread 收口到 Durable Task 时，继续复用同一 frozen resource dependency，而不是重新 lookup mutable config。

**回归测试建议：**

至少覆盖：

- create remote conversion → 立即 PATCH resource：任务仍使用创建时冻结的 endpoint / credential identity；
- create → DELETE resource：DELETE 在 active dependency 存在时 409，任务不受影响；
- terminal 后允许资源退役 / 删除；
- API Key rotation 不影响旧任务，只影响新任务；
- job audit 能显示 frozen resource revision / identity，但不泄露 secret；
- 并发 create + PATCH / DELETE 使用明确 CAS/fence，不存在 TOCTOU。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-110 — 新畅联 Auto Sync 按项目重复拉取同一全局主数据，却共用单份 global cache；多项目可落入不同 digest 并把先同步项目判 stale

**级别：高**  
**模块：External Algorithm Auto Sync / Master Data Cache / Multi-project Reconciliation / Training Preflight**

**现象：**

当前新畅联主数据本质上是 provider-global truth，包括 Category Tree、Product listAll、Compute Platform listAll、Analysis listAll / getInfo。

ExternalPlatformRepository 也只维护一份全局缓存：

DATA_DIR/external_algorithm_platform/master-data-cache.json

但自动同步 owner ExternalAlgorithmAutoSyncReporter.run_once() 却按项目执行：

for project_id in self._project_ids(): service.sync(project_id=...)

而每一次 service.sync() 都重新从新畅联完整拉取：

1. client.category_tree()
2. client.products(status="")
3. client.compute_platforms()
4. analysis list / per-product summaries
5. 对每个 analysis 再读取 authoritative detail truth

所以本地有 N 个项目时，同一轮 08:00 / 12:00 / 15:00 自动同步会重复执行 N 次相同 provider master-data fetch。

**更严重的一致性问题：**

每个 service.sync(project_id) 都独立计算 master_data_digest，并在项目 mirror 前写入同一份全局 cache：

self.repository.save_cache(cache)

随后该项目算法被写入自己的 external_master_data_digest。

训练前置校验 assert_external_master_data_current() 又会比较：

- 当前项目算法自己的 external_master_data_digest
- 全局单份 cache 的 master_data_digest

因此只要 provider 数据在项目 A 与项目 B 两次 fetch 之间发生变化：

1. 项目 A 拉到 generation A / digest A；
2. global cache 写 digest A；
3. 项目 A mirror 写 digest A；
4. 项目 B 再次从 provider 拉取；
5. provider 此时已经更新，得到 digest B；
6. global cache 被覆盖成 digest B；
7. 项目 B mirror 写 digest B；
8. 自动同步结束后，项目 A 仍是 digest A；
9. 用户在项目 A 创建训练任务；
10. assert_external_master_data_current() 比较 A != global B；
11. 返回 EXTERNAL_MASTER_DATA_STALE / 409。

也就是说：

**一次“全部项目自动同步成功”之后，先同步的项目仍可能立即被系统自己判定为主数据过期。**

**并发手动同步还会进一步放大：**

当前 sync lock 是按 project_id 区分的 .sync-{project_id}.lock。

项目 A 与项目 B 可以同时执行 sync，但二者又共享同一个 master-data-cache.json 和同一 provider master-data generation truth。

文件级 repository lock 只能保证单次写文件不损坏，不能保证“global cache generation + 各项目 mirror”属于同一个同步世代。

因此跨项目并发 manual sync 也可能让 global cache、project A algorithm digest、project B algorithm digest 分别来自不同 provider generation。

**为什么是 Bug / Owner 边界错误：**

当前实现同时把 master data 当成 global cache truth，又把 master-data fetch executor 当成 project-scoped operation。

项目 mirror 确实应该是 project-scoped；但 provider master-data fetch / digest 应该是 generation-scoped/global，而不是每个项目各拉一遍。

**影响：**

- 多项目环境产生 O(project_count × provider_master_data) 的重复远端 I/O；
- analysis detail 本身是逐条 authoritative GET，项目数会进一步线性放大请求量；
- 新畅联接口更容易被限流、超时或触发保护；
- 自动同步整体耗时随项目数线性增长；
- provider 在一轮同步中发生正常更新时，不同项目得到不同 generation；
- 先同步项目会在同一轮结束后被训练 preflight 判 stale；
- 页面看到“同步成功”，训练创建却 409，形成明显业务状态矛盾；
- 跨项目并发 manual sync 也可能互相覆盖 global cache generation。

**与删除同步合同的关系：**

当前删除判断使用完整 products(status="")，不是分页窗口，这一点是安全的。

AUDIT-110 不是“分页误删”，而是：

同一全局 provider truth 被按 project 重复 fetch/commit，导致 cache generation 与 project mirrors 不能保证一致。

**建议最小修复：**

不要新增第二套 external platform cache。

应收敛为单一 generation owner：

1. 一轮 scheduled auto sync 只从新畅联抓取一次完整 master data；
2. 冻结 categories、products、analyses、compute platforms、master_data_digest、provider fetched_at / generation id；
3. 把这一个 frozen generation fan-out mirror 到所有项目；
4. 每个项目仍使用现有 project delivery fence / purge owner；
5. 所有项目 mirror 完成后，再把该 generation 标记为 current global cache；
6. 某项目 mirror 失败时记录 project-level failure，不能伪装成“global generation 已对所有项目生效”；
7. manual sync 必须明确是“使用 current global generation 重镜像项目”还是“刷新 global generation + fan-out”，不能让多个 project lock 并发刷新同一个 global generation；
8. 保留现有完整 product set 删除语义，不要改回分页 deletion truth。

**回归测试建议：**

至少覆盖：

- 20 个项目的一轮 auto sync：provider master-data endpoints 只调用一次 generation；
- provider 在项目 mirror 期间发生变化：本轮所有项目仍使用同一 frozen digest；
- auto sync 完成后所有项目算法 digest == current global cache digest；
- project B mirror 失败时 project A 不被错误回滚，global generation 状态可解释；
- 两个项目同时 manual sync 不得形成两个并发 global master-data generation；
- 1k product / 多 analysis 场景的 provider request count 不随 project_count 成倍增长。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-111 — Training Create 的 GET preflight 在 drift 时同步执行完整新畅联 reconciliation；打开训练弹窗可阻塞在全量远端 I/O，并触发本地 purge / mirror 写操作

**级别：高**  
**模块：Training Create / External Algorithm Preflight / ChangLian Reconciliation / HTTP Semantics / First-open Performance**

**现象：**

外部新畅联算法打开训练创建弹窗时，TrainingCreateHydrationRuntime 会把 external preflight 作为打开表单的前置条件。

当前 main.mjs 的真实装配为：

preflight: algorithmId => externalAlgorithmPlatformRuntime.preflightTraining(algorithmId, {request: api})

而 preflightTraining() 会发起：

GET /api/v63/external-algorithm-platform/training-preflight

trainingPreflightFresh() 的默认 freshness 只有 30 秒。

训练创建 start() 在 preflight 不新鲜时，会显示“正在准备训练配置”，然后同步等待：

Promise.all([hydrate(), preflight(aid)])

只有 preflight 返回后才真正 openTrainingForm()。

**后端的关键问题：**

training_preflight() 先实时读取：

- product_info(product_id)
- analyses(product_id)
- 每个 analysis 的 authoritative detail

然后比较本地与远端：

- analysis contract
- product name
- product code
- category id

只要发现 drifted=True，就直接在当前 GET 请求里同步调用：

self.sync(project_id=..., algorithms_path=..., sync_type="auto")

这个 sync 不是轻量刷新。

它会继续执行完整 provider reconciliation，包括：

1. category_tree
2. products(status="")
3. compute_platforms
4. 全量 analyses / analysis detail truth
5. removed external algorithm detection
6. 对远端已删除算法设置 delete-pending
7. local_purger.purge()
8. Durable Task cancel / terminal cleanup
9. ModelArtifact / publication / remote object cleanup
10. global cache commit
11. project algorithm mirror

所以一个名字、分类、Analysis 配置等普通 drift，就会把“打开训练弹窗”的 GET preflight升级成一次完整可写 reconciliation。

**为什么是 Bug：**

这里同时存在两个合同问题。

第一，关键交互路径被无界放大。

用户只是打开训练任务创建弹窗，但请求耗时可能取决于：

- 新畅联产品总量；
- analysis 总量；
- analysis detail N 次请求；
- 本地被删除算法的历史任务/模型数量；
- OSS / publication cleanup；
- provider 网络延迟。

训练弹窗因此会长时间停留在准备中。

第二，GET preflight 不是 read-only。

GET /training-preflight 在 drift 时会修改甚至删除本地状态。

它可以：

- 修改 global master-data cache；
- 修改 algorithms mirror；
- 标记 external_delete_pending；
- 请求取消 Durable Task；
- 删除 terminal task/artifact；
- 删除 ModelArtifact / publication / remote object。

这与 GET 的安全/idempotent读取语义不匹配，也意味着浏览器重试、预热、重复打开等“读操作”可能触发重 reconciliation。

**真实前端可达性：**

这不是孤立后端函数。

当前生产 bootstrap 明确把 ExternalAlgorithmPlatformRuntime.preflightTraining 注入 TrainingCreateHydrationRuntime。

对于外部新畅联算法：

- 30 秒内可能复用 preflight cache；
- 超过 30 秒、首次打开、cache 被清空、项目切换后都会重新 preflight；
- start() 必须等 preflight 成功才能打开真实训练表单；
- prewarm() 也可能提前触发该 GET。

因此问题直接位于训练创建用户主流程。

**与 AUDIT-110 的区别：**

AUDIT-110 是：

新畅联 provider-global master data 被 Auto Sync 按项目重复 fetch，导致 generation/digest 跨项目不一致。

AUDIT-111 是：

训练创建的单算法 GET preflight 在发现 drift 时，同步升级成完整 reconciliation，并把全量远端 I/O、purge 和 mirror 放进弹窗打开关键路径。

即使 AUDIT-110 修成单一 global generation，AUDIT-111 仍需解决 GET preflight 不应同步承担完整 mutation owner 的问题。

**影响：**

- 外部算法训练创建首开或 30 秒后重开明显变慢；
- provider 产品/Analysis 越多，preflight 延迟越大；
- 网络抖动可直接让训练弹窗“正在准备”长时间等待；
- 一个目标算法 drift 会导致无关产品也被完整拉取；
- GET 请求可能触发本地训练/转换任务取消和成果清理；
- 浏览器或代理对 GET 的安全重试语义与实际副作用冲突；
- prewarm 与用户实际点击可能把 reconciliation 放到意料之外的时间点；
- 训练创建的可用性被新畅联全局同步健康度直接绑死。

**建议最小修复：**

不要新增第二套 External Platform owner，也不要取消训练前实时资格核验。

应把“单算法训练资格检查”和“全局 reconciliation”分开：

1. training-preflight 只做 bounded、read-only 的单算法实时核验：
   - product detail
   - analysis list/detail
   - status==1
   - analysisType==1
   - 必要身份/合同对比
2. 如果发现 drift：
   - 返回明确 drift / sync_required truth；
   - 或提交/复用 canonical external sync operation；
   - 不在 GET 请求线程里直接 self.sync()
3. Training Create 可以：
   - 资格仍满足时用当前实时单算法 truth 打开表单；
   - 必须等待同步时显示独立、可恢复的同步任务状态；
4. 全局 cache / purge / mirror 继续由唯一 External Algorithm reconciliation owner 执行；
5. GET endpoint 必须保持无破坏性副作用；
6. preflight freshness 可保留，但不能拿 30 秒 cache 掩盖重型同步；
7. 和 AUDIT-110 一起收口时，drift 应触发单一 global generation，而不是在 Training Create 内复制同步 executor。

**回归测试建议：**

至少覆盖：

- external training first-open preflight 只访问目标 product / analyses，不触发 products 全量 listAll；
- drifted product 时 GET preflight 不调用 local_purger / cache commit / mirror mutation；
- 1k products 环境下 Training Create first-open provider request count 有固定上限；
- provider 正常但存在名称/分类 drift 时，弹窗不会同步等待全局 reconciliation；
- remote product inactive / 无 visual analysis 仍必须 fail-closed；
- 真正的 sync operation 完成后，再打开训练可读取新 mirror；
- GET preflight 重试不会产生删除/取消任务副作用。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-112 — Training preflight 的用户触发 drift sync 被错误记为 auto；可提前消费 08:00 / 12:00 / 15:00 正式自动同步时段并漏掉其它项目

**级别：高**  
**模块：External Algorithm Training Preflight / Auto Sync Schedule / Multi-project Reconciliation**

**现象：**

当前 training_preflight() 在发现外部算法 drift 后直接调用：

self.sync(..., sync_type="auto")

但这次同步并不是由 Auto Sync Reporter 的固定时段调度触发，而是用户打开训练创建流程时触发的 demand/preflight reconciliation。

与此同时 auto_sync_due() 判断 08:00 / 12:00 / 15:00 时段是否已经执行时，只看全局 sync history 中最近一条：

sync_type == "auto"

并明确采用以下语义：

- 最近 auto attempt 的 started_at / finished_at >= 当前 latest_due_slot
- 则本时段视为已经消费
- success 和 failure 都会消费该 slot，避免 provider 故障时 Worker heartbeat 持续轰击远端

因此 training preflight 写入的 auto history 会被正式调度器误认为：

“本时段的 scheduled auto sync 已经执行过”。

**真实竞态：**

例如 12:00 时段：

1. 12:00:00 到达新的自动同步 slot；
2. Worker Reporter 尚未来得及启动 scheduled run；
3. 用户在项目 A 打开一个外部算法训练弹窗；
4. preflight 发现该算法名称、分类或 Analysis contract 有 drift；
5. training_preflight() 同步执行 self.sync(..., sync_type="auto")；
6. 项目 A 的这次 demand sync 完成并 append_history(sync_type="auto")；
7. Worker heartbeat 随后调用 auto_sync_due()；
8. latest_auto 时间已经 >= 12:00；
9. auto_sync_due() 返回 False；
10. 正式 scheduled run 不再启动。

在当前多项目实现中，这尤其危险：

- preflight 只同步当前 project_id；
- 正式 Auto Sync Reporter 原本会遍历全部项目；
- 项目 A 的一次训练弹窗 preflight 可以让项目 B/C/D 在整个 12:00 时段都不再同步。

如果服务在某一 scheduled slot 到达后暂时没有 Worker heartbeat，用户先触发 preflight，同样可以稳定复现。

**失败也会消费时段：**

sync() 的异常路径同样 append_history(failed)，并保留 sync_type="auto"。

所以 preflight drift sync 即使失败，也可能使 auto_sync_due() 判断该 slot 已被消费。

这会出现：

- 用户训练弹窗 preflight 失败；
- scheduled reconciliation 也不再补跑；
- 其它项目直到下一个 15:00 / 次日 08:00 才有机会恢复。

**为什么不是 AUDIT-110：**

AUDIT-110 是 provider-global master data 被按项目重复 fetch，导致 global generation 与 project digest 漂移。

AUDIT-112 是 schedule identity 错误：

用户触发的 training preflight reconciliation 被标成 auto，污染 scheduled slot bookkeeping。

即使后续 AUDIT-110 收口成 single global generation，trigger_source / schedule-slot identity 仍必须准确区分，否则任意 demand refresh 仍可能错误消费 fixed schedule。

**为什么不是 AUDIT-111：**

AUDIT-111 是 GET training-preflight 在 drift 时同步执行完整 reconciliation，造成训练弹窗重型阻塞和 GET mutation。

AUDIT-112 是这次 reconciliation 被错误分类为 sync_type=auto 后，对 08:00 / 12:00 / 15:00 调度状态造成持久副作用。

两者修复点不同：

- 111 关注 read/preflight 与 mutation owner 分离；
- 112 关注 trigger identity 与 scheduled slot accounting。

**影响：**

- 训练弹窗行为可以改变后台自动同步调度；
- 多项目场景其它项目可能整整漏掉一个同步时段；
- preflight 失败也可能阻断本时段自动恢复；
- 运维看到“最近 auto sync”时实际可能是用户训练触发，不是 scheduled job；
- 同步历史的 trigger source 审计失真；
- 08:00 / 12:00 / 15:00 的固定 SLA 不再可信。

**建议最小修复：**

不要通过修改时间窗口或增加频率掩盖。

应明确分离：

- scheduled_auto
- manual
- training_preflight / demand_refresh

至少需要：

1. training preflight 不再写 sync_type="auto"；
2. scheduled slot 只能由真正持有 scheduled slot identity 的 Auto Sync Reporter 消费；
3. history 保存 trigger_source 和 schedule_slot_id；
4. auto_sync_due() 判断的不是“最近有一条 auto history”，而是“当前 slot_id 是否已有 scheduled attempt”；
5. demand/manual refresh 不得改变 scheduled slot 状态；
6. scheduled failure 是否消费 slot可以继续保留当前 anti-hammer 语义，但必须限定为该 scheduled execution 自己；
7. 与 AUDIT-110 收口时由 single global generation owner 持有 slot。

**回归测试建议：**

至少覆盖：

- 12:00 后 training preflight drift sync 完成，scheduled 12:00 run 仍然 due；
- preflight drift sync 失败，scheduled run 仍然 due；
- scheduled 12:00 success 后同 slot 不重复执行；
- scheduled 12:00 failure 后同 slot按既定 anti-hammer 策略不重复；
- manual sync 不消费 scheduled slot；
- 多项目场景 project A demand refresh 后 project B/C 仍被正式 scheduled generation 覆盖；
- history 能准确区分 scheduled / manual / training_preflight trigger。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-113 — “畅联云数据”手动刷新执行 Product→Version→Weight 全量 N+1 水合并一次性渲染完整 DOM；数据规模增长后请求数和页面成本无界

**级别：中～高**  
**模块：畅联云数据 / Provider Browser / Remote API Hydration / Frontend Performance**

**现象：**

当前“畅联云数据”页面设计为只读、手动刷新，这个产品方向本身正确；页面进入时不会自动请求远端。

但点击“手动刷新畅联云”后，前端会一次性构造完整远端对象树。

真实调用链：

1. 并行读取两组产品：
   - provider/products?status=1
   - provider/products?status=0
2. mergeProducts() 合并所有产品；
3. 对每一个 product，调用：
   - provider/versions/by-product/{productId}
4. 对该产品返回的每一个 version，再调用：
   - provider/weights/by-version/{versionId}
5. 等所有 product/version/weight 都完成后，才把完整 hydrated tree 写入 snapshot；
6. render() 通过：
   snapshot.products.map(productHtml).join("")
   一次性生成全部 Product、Version、Weight DOM。

mapLimit(products, 4) 和 mapLimit(versions, 4) 只限制并发度，并没有限制总工作量。

**请求复杂度：**

若远端有：

- P 个算法产品；
- 总计 V 个算法版本；

一次手动刷新大约需要：

2 + P + V

次平台 HTTP 请求。

例如：

- 1,000 个产品；
- 平均每个产品 5 个版本；

则一次刷新约：

2 + 1,000 + 5,000 = 6,002 次 HTTP 请求。

即使并发限制为 4，总请求数仍然线性增长，刷新完成时间会非常长。

**后端没有聚合：**

当前 provider proxy 只是逐条透传：

provider_versions_by_product()
→ client.version_list_by_product(product_id)

provider_weights_by_version()
→ client.weight_list_by_version(algo_version_id)

没有服务端 batch、cursor hydration 或按展开加载。

因此所有 N+1 都真实打到新畅联。

**前端还有第二层无界成本：**

所有请求完成后，snapshot 保存完整树：

products[]
  -> versions[]
     -> weights[]

随后 render() 一次性将全部：

- 产品 details；
- 版本 section；
- 权重卡片；
- 文件地址；
- 下载链接

拼成一个巨大 innerHTML。

即使 details 默认折叠，内部 DOM 仍然已经创建。

所以大规模下会同时产生：

- 大量远端 I/O；
- 大量 JS 对象；
- 大字符串拼接；
- 大量 DOM node；
- 浏览器 layout/style 成本；
- refresh 前长时间无增量结果。

**为什么是 Bug / 性能技术债：**

这个页面的目标只是“只读查看远端数据”，不要求一次刷新把整个新畅联数据库完整复制到浏览器。

当前结构把“浏览/查看”实现成一次全量递归 hydration。

它在小数据测试下可以工作，但没有 1k/10k 规模上限。

并且和主数据同步不同，这些版本/权重只是用户查看用途，不应该主动为未展开的产品产生远端请求。

**与 AUDIT-110 的区别：**

AUDIT-110 是后台 Auto Sync 对 provider-global master data 按项目重复拉取，并产生 digest generation 问题。

AUDIT-113 是“畅联云数据”只读页面自身的浏览策略：

一个用户手动刷新就会按 Product→Version→Weight 递归 N+1 拉取并完整渲染。

即使 AUDIT-110 完全修复，这个浏览页仍然会有独立的 N+1 / DOM 问题。

**影响：**

- 新畅联产品越多，手动刷新越慢；
- 大量版本/权重时可能需要成千上万次 provider 请求；
- 容易触发远端限流、网关超时或 Token 续期压力；
- Web 服务作为 proxy 会承受大量并发转发；
- 浏览器内存和 DOM 规模随远端历史数据持续增长；
- 用户只想看一个产品，也必须等待所有产品全部水合；
- 任意中间请求失败会使整个 refresh Promise 失败，已成功读取的数据也不会渐进展示；
- 在移动端或低性能终端更容易明显卡顿。

**建议最小修复：**

不要新增第二套远端数据缓存 owner，也不要把全部数据同步到本地数据库只为解决页面展示。

建议按浏览语义改成分层、按需读取：

1. 首屏只加载 Product 列表：
   - 分页或 cursor；
   - 显示产品基础信息；
2. 用户展开某 Product 时，再加载其 Version；
3. 用户展开某 Version 时，再加载其 Weight；
4. 每一层独立：
   - loading；
   - error；
   - retry；
   - cache TTL；
5. 已展开结果可做 bounded client cache；
6. 支持搜索/分页，不生成全部远端 DOM；
7. 若 provider 有 listAll，只把它用于确实需要全量 truth 的后台 reconciliation，不要用于普通浏览 UI；
8. 页面摘要如需全量 count，应使用 provider aggregate/count 字段或专用统计接口，而不是通过完整 hydration 得到。

**回归测试建议：**

至少覆盖：

- 1,000 products 首次刷新只产生 bounded Product 请求，不发 1,000 个 versions 请求；
- 未展开 Product 不请求 versions；
- 未展开 Version 不请求 weights；
- 展开一个 Product 只加载该 Product；
- 展开一个 Version 只加载该 Version weights；
- 10k products 时 DOM node 数与当前可见页面规模成比例；
- 单个 Product/Version 加载失败不使其它已加载数据消失；
- 重复展开在 TTL 内不重复请求。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-114 — “畅联云数据”停用算法状态过滤写成 status=0，但 canonical 新畅联合同以 status=2 表示 inactive；已下架产品会从只读页完全漏失

**级别：中～高**  
**模块：畅联云数据 / External Product Status / Frontend-Backend Contract**

**现象：**

当前“畅联云数据”页面刷新时固定请求两组产品：

- /provider/products?status=1
- /provider/products?status=0

并把两组 merge 后作为页面的完整产品集合。

也就是说，前端把：

- status=1 当启用；
- status=0 当停用。

但 canonical 后端同步合同已经明确采用：

- status=1：active；
- status=2：inactive / 下架。

platform_core/external_algorithm_platform.py 的删除同步注释明确写着：

status=2 means inactive; complete absence means deleted.

并且现有单元测试：

test_remote_status_two_is_retained_as_inactive_not_deleted

明确构造：

status: 2

并断言：

- external_active is False；
- external_status == "2"；
- 版本仍然保留；
- 不能把它当远端删除。

因此“畅联云数据”的 status=0 过滤与 canonical provider status contract 不一致。

**现有前端测试还把错误固化：**

tests/frontend/changlian-data-browser.test.mjs

当前 mock 和 URL 断言都明确要求：

/products?status=0

所以即使 provider 按真实合同返回 inactive status=2，测试仍会绿色，因为测试模拟的是错误状态值。

**真实影响：**

当新畅联存在：

productId=p1, status=2

时：

1. enabled 请求 status=1 不会返回 p1；
2. disabled 请求 status=0 也不会返回 p1；
3. mergeProducts() 根本拿不到 p1；
4. 页面不会请求 p1 的 versions；
5. 更不会请求这些 version 下的 weights；
6. 用户在“畅联云数据”里看不到这个已停用产品及其历史版本/权重。

但主数据同步却会正确保留该算法为：

external_active=False
external_status="2"

于是同一系统形成明显矛盾：

- 算法列表 / mirror truth 知道它“已下架”；
- 畅联云只读数据页却像它根本不存在。

**为什么是 Bug / 前后端不一致：**

“畅联云数据”页面的产品定位是：

只读查看远端算法产品、版本、转换结果。

停用/下架产品依然是远端真实数据，而且它们的历史版本、权重仍有审计价值。

status=2 不是 deleted。

只有完整 products(status="") 返回集合中完全缺失，才代表删除。

所以浏览页不能把 status=2 漏掉。

**影响：**

- 已下架算法从只读页消失；
- 用户无法查看其历史版本和权重/转换结果；
- 页面统计的“算法产品 / 版本 / 权重”数量偏小；
- 运维会误以为远端已经删除；
- 与算法列表中的“已下架”状态互相矛盾；
- 容易干扰排查外部删除同步、版本回退和发布历史。

**建议最小修复：**

不要在前端硬编码另一套 provider 状态枚举。

优先方向：

1. 如果 provider products(status="") 能返回完整 active + inactive 集合：
   - 浏览页直接使用这一完整只读集合；
2. 如果必须按状态拆：
   - 使用 canonical provider status 常量；
   - active=1；
   - inactive=2；
3. 不要把 status=0 继续当作“停用”的隐式本地约定；
4. 把 provider product status normalization 提取为单一共享合同；
5. UI 对 status=2 明确展示“已停用/已下架”，而不是删除；
6. 完整缺失与 inactive 必须继续严格区分。

**回归测试建议：**

至少覆盖：

- provider 返回 status=2 产品时，畅联云数据页可见；
- status=2 产品仍加载 versions / weights；
- 页面统计包含 inactive 产品；
- active=1 与 inactive=2 都正确展示；
- complete absence 才视为不存在；
- 前端测试不再断言错误的 status=0；
- 与 test_remote_status_two_is_retained_as_inactive_not_deleted 使用同一状态合同。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-115 — 已打开页面的本地会话失效后，业务 API 401 不触发统一登录跳转；前端可最长约 30 分钟保持“已登录外观”但所有操作持续失败

**级别：中**  
**模块：ChangLian Login / Frontend API Runtime / Session Expiry / Authentication UX**

**现象：**

当前登录体系有两条前端请求路径：

1. static/auth-session.js
   - GET /api/auth/session
   - 负责展示当前畅联云账号；
   - 每 30 分钟执行一次 session keepalive；
   - 如果该接口返回未认证，会跳转 /login。

2. static/app.js 的全局业务 api()
   - 承担算法、训练、素材、标注、存储、转换等绝大多数业务请求；
   - 对所有非 2xx 响应只解析错误并 throw；
   - 不识别 HTTP 401；
   - 不触发 auth-session refresh；
   - 不跳转登录页。

因此，如果页面已经打开后本地 session 在运行中失效：

- 业务 API 会立即开始返回 401；
- 但页面顶部仍保持原来的用户名和“已登录”外观；
- 用户点击任何功能只会得到普通错误提示；
- 只有下一次 30 分钟 keepalive 调用 /api/auth/session 时，页面才会被带回登录页。

**真实代码：**

static/auth-session.js：

SESSION_REFRESH_INTERVAL_MS = 30 * 60 * 1000

只有 hydrateAuthIdentity() 会在：

!response.ok || !body.authenticated

时：

window.location.replace('/login?next=%2F')

而 static/app.js 的全局 api() 逻辑是：

fetch
→ if !response.ok
→ 解析 message/detail/solution
→ throw Error

没有对 response.status === 401 做任何认证状态处理。

**真实可达场景：**

至少包括：

- local idle / hard expiry；
- 服务端主动改变 session policy；
- session 签名 key / session owner 发生受控轮换；
- 用户在另一个上下文完成退出或 cookie 被浏览器清理；
- 长时间打开页面后再恢复操作。

页面本身不会重新加载，因此服务端 middleware 对页面导航的 redirect 保护不会被触发。

下一次业务请求只会得到 API 401。

**现有测试为什么没发现：**

tests/browser/changlian-login-auth.spec.mjs 当前覆盖：

- 未登录访问根页面会跳登录；
- 登录成功；
- 刷新后保持登录；
- logout button；
- logout 后直接调用 protected API 得到 401；
- 受保护 data URL 跳登录。

但没有覆盖：

登录成功并保持当前 SPA 页面
→ session cookie 在后台失效/删除
→ 用户点击一个普通业务操作
→ 第一个 401 是否立即触发登录跳转。

tests/frontend/changlian-login-ui.test.mjs 还明确断言 30 分钟 keepalive 存在，但没有要求全局业务 request owner 处理 401。

**为什么是前后端状态漂移：**

服务端 truth 已经是：

AUTH_REQUIRED / 401。

但 SPA shell 在最长一个 keepalive 周期内仍显示：

- 原用户名；
- 原 session life；
- 正常业务按钮；
- 正常页面状态。

即前端 authentication state 没有在业务请求边界跟随后端 truth 收敛。

**影响：**

- 用户会连续看到“操作失败/请先登录”而不知道应该重新登录；
- 训练创建、标注保存、素材管理等操作可反复失败；
- 用户可能重复点击提交按钮，以为是业务 Bug；
- 已编辑但未保存的表单在最终跳登录时可能丢失；
- 现场容易误判为接口异常、训练异常或权限异常；
- session keepalive 最长 30 分钟，恢复延迟明显过大。

这不是认证绕过：

服务端依然正确拒绝 401。

问题是浏览器认证状态与服务端状态没有即时一致。

**建议最小修复：**

不要新增第二套 auth owner。

继续让 auth-session.js 作为唯一 browser session owner，并给全局 request runtime 一个轻量入口，例如：

- 任意受保护业务请求遇到 401 / AUTH_REQUIRED；
- 只触发一次 canonical auth-session invalidation；
- 清理 keepalive；
- 可记录当前安全 next path；
- 立即 replace 到 /login。

关键要求：

1. 不能把所有 401 都盲目吞掉；
2. 登录接口自身的 401/认证失败仍应在登录页展示错误；
3. Agent/machine endpoints 不经过 browser redirect owner；
4. 多个并发请求同时 401 时只执行一次跳转；
5. 跳转前避免重复 toast / mutation retry；
6. 不在 localStorage/sessionStorage 保存凭据。

**回归测试建议：**

至少覆盖：

- 登录后保持 SPA 页面，删除/使 session cookie 失效；
- 下一个普通业务 GET 返回 401 时立即跳 /login；
- mutation POST 返回 401 时也立即跳转且不自动重试 mutation；
- 5 个并发业务请求同时 401 只触发一次 auth invalidation；
- 普通 403/409/422 仍按业务错误展示，不跳登录；
- /api/auth/login 的登录失败仍留在登录页；
- Agent Bearer API 不被 browser auth runtime 接管。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-116 — AI 自动标注“参考已有标注/参考图”只保存 reference_image_ids，Durable Worker 推理完全不读取参考图；用户选择的视觉示例实际不生效

**级别：高**  
**模块：AI Annotation / Reference Images / Multimodal Prompt / Frontend-Backend Contract**

**现象：**

当前 AI 自动标注创建弹窗明确提供：

“参考已有标注（可选）”

并说明：

“参考图只用于视觉示例，不会自动添加或改变本次标签”。

用户可以从已标注素材中选择参考图片。

提交时前端明确发送：

reference_image_ids: [...state.ai429RefSelected]

所以从 UI 语义看，这些图片应作为视觉 few-shot / reference examples 参与模型判断。

**但后端真实执行链没有使用这些参考图。**

annotation_runtime.prepare_request() 只做：

- 读取 reference_image_ids；
- 去重；
- 将它们写回 prepared request。

后续没有：

- 校验这些 reference images 是否存在；
- materialize reference images；
- 读取 reference image bytes；
- 读取 reference image annotation；
- 构造 multimodal few-shot message；
- 把 reference images 交给 provider。

annotation_task_service.run_ai_annotation() 只加载：

runtime_request["image_ids"]

即真正待标注图片。

annotate_one() 对每张当前图片只执行：

provider.annotate(
  image_bytes=current_image_bytes,
  prompt=prompt,
  output_schema=...
)

没有 reference_image_ids，也没有 reference image bytes / annotations。

因此用户勾选 0 张、1 张或 20 张参考图，在其它输入完全相同时，当前模型请求内容完全相同。

**这是明确的前后端功能失效：**

前端把参考图作为 AI 标注创建流程中的正式功能暴露给用户；

后端 request schema 也接受并持久化 reference_image_ids；

但实际模型推理路径完全忽略这些 ID。

这不是“参考图效果不明显”，而是：

**参考图根本没有进入推理。**

**额外问题：提交时也不验证 reference image truth**

_v60 的 _annotation_create_payload() 会对主 image_ids：

- 分 500 条 material_store.get_many；
- 检查缺失；
- 缺失立即 400。

但 reference_image_ids 没有同样的存在性/项目归属/annotation-ready 校验。

这也侧面证明它们目前只是被保存的无效字段，而不是执行依赖。

**为什么 Prompt Template 冻结不是问题：**

现代 v60 Prompt Template 本身是安全的：

prepare_request(runtime=False) 会从服务端 Prompt Library 读取模板，写入：

- prompt_template_snapshot
- prompt_template_version_id

浏览器提交的 snapshot 会被剥离。

所以模板修改不会改变已排队任务。

AUDIT-116 针对的是另一条独立功能合同：

reference images 虽被 UI 和 request 暴露，但根本没有被 Durable AI runtime 消费。

**影响：**

- 用户以为参考图会帮助模型理解场景/目标外观，实际没有任何作用；
- 对烟火、抽烟、积水等视觉差异较大的业务，用户可能错误依赖参考图提高准确率；
- 调参和效果对比会被误导，因为“选参考图/不选参考图”模型输入完全一致；
- UI 增加了选择成本，却没有产生推理收益；
- 参考图相关状态、选择逻辑和 request 字段成为技术债；
- 后续评测时容易错误归因“多模态 few-shot 没效果”，实际上功能从未接通。

**建议最小修复：**

先明确产品合同，不要继续保留“看起来支持”的半功能。

如果要支持参考图：

1. admission 时验证每个 reference_image_id：
   - 同项目；
   - material 存在；
   - 文件可读取；
   - 必须具备已确认正式标注；
2. 冻结 reference identity / annotation revision，避免排队后参考内容漂移；
3. 在 Worker 侧 bounded materialize；
4. 将参考图片 + canonical annotation/labels 组成 provider-neutral reference examples；
5. Provider adapter 明确声明是否支持 multimodal reference/few-shot；
6. 不支持的 Provider：
   - UI 禁用参考图；
   - 或 admission 明确 422；
   - 不能静默忽略；
7. 对参考图数量、总像素/总 bytes 设置上限，避免单任务 prompt 爆炸；
8. 保持主 image 与 reference images 的语义分离，参考图不能直接写入候选结果。

如果当前阶段不准备支持视觉参考：

- 应暂时从 UI 删除“参考已有标注”选择；
- 同时删除无效 request field；
- 不能继续让用户以为它会影响推理。

**回归测试建议：**

至少覆盖：

- 选择 reference image 后 provider mock 能实际收到 reference content；
- 不选 reference 时不产生额外参考 payload；
- reference material 不存在时 admission fail-closed；
- reference annotation revision 在执行前变化时按冻结合同处理；
- 不支持 reference 的 provider 不得静默忽略；
- 10/20 张参考图时请求大小有明确上限；
- 选参考图与不选参考图的 provider request contract 必须可观察到差异。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---
### AUDIT-117 — AI 参考图选择会自动把参考素材标签写入本次 ai429Labels；与“标签必须用户显式决定”及当前 UI 文案直接冲突

**级别：高**  
**模块：AI Annotation / Reference Selection / Label Governance / Frontend Contract**

**现象：**

当前 AI 自动标注弹窗明确告诉用户：

- “必须显式填写至少一个当前有效标签 code”
- “参考图片也不会替你选择标签”
- “参考图只用于视觉示例，不会自动添加或改变本次标签”

但真实生产点击参考图后，前端会自动修改本次标签输入框。

真实调用链：

window.toggleRef429(id)
→ 更新 state.ai429RefSelected
→ syncReferenceLabels417()

syncReferenceLabels417() 会：

1. 读取已选择参考素材；
2. 通过 PlatformCore.materials.labelsFromReferences() 提取这些素材现有 labels；
3. 把这些 labels 写入 state.ai429ReferenceLabels417；
4. 直接执行：

input.value = manual_labels + reference_labels

即自动把参考素材标签加入：

#ai429Labels

批量参考图选择也同样会调用：

aiRefSelect412()
→ aiRefSelectCore412(mode)
→ syncReferenceLabels417()

所以单选和批量选择都存在同样行为。

**这不是展示辅助，而是实际改变提交 payload：**

submitAiLabel429() 最终读取：

document.getElementById('ai429Labels').value

经过 explicitCanonicalAiLabelText() 后写入：

labels_text

因此参考素材带出的标签会真正进入 AI task requested labels。

用户没有逐个确认这些标签，也没有显式点击“加入本次标签”。

**为什么是 Bug / 标签治理合同破坏：**

当前平台标签治理已经明确要求：

- AI 标注标签不得自动推断；
- 不根据中文名、alias、历史数据自动替用户选 canonical code；
- 用户必须显式决定本次 AI 标注允许哪些标签。

参考素材的既有标签只是历史 Ground Truth，不能自动变成新任务的 requested label scope。

尤其是参考图可能包含多个对象标签，而用户只想借它参考某一个视觉目标。

例如参考图标签：

person、smoke、phone

用户本次只想标：

smoke

选择该参考图后当前代码会自动把 person / smoke / phone 都写入本次 labels 输入框。

后端看到的将是用户没有主动决定过的完整标签集合。

**与 AUDIT-116 的区别：**

AUDIT-116 是：

reference_image_ids 虽提交，但 Worker 推理根本不使用参考图，视觉参考功能实际无效。

AUDIT-117 是：

参考图虽然没有进入模型推理，却反而在前端自动改变 requested labels。

因此当前最糟糕的实际效果是：

- 用户期待参考图片影响视觉推理；
- 实际图片没有进入模型；
- 参考图片却悄悄改变了模型允许识别的标签范围。

两者是独立问题，必须分别修复。

**额外 UI 自相矛盾：**

syncReferenceLabels417() 还会动态插入文案：

“参考素材带出标签”
“选择参考素材后，将自动带出对应标签”

而创建弹窗原始文案同时写着：

“参考图片也不会替你选择标签”
“参考图只用于视觉示例，不会自动添加或改变本次标签”

同一弹窗运行过程中会同时出现互相冲突的产品语义。

**影响：**

- AI task requested_labels 与用户真实意图不一致；
- 候选生成范围被扩大；
- Review scope 被扩大；
- overwrite=true 时可能扩大后续正式 Annotation 影响范围；
- 用户选择一个参考图可能无意中把多个历史标签加入本次任务；
- 训练前标签治理和审计链难以解释“这些标签是谁选择的”；
- UI 文案与真实提交 payload 不一致。

**建议最小修复：**

不要新增第二套 label owner。

参考图和标签选择必须彻底解耦：

1. toggleRef429 只维护 reference_image_ids；
2. 不得修改 ai429Labels；
3. 删除 syncReferenceLabels417 对输入框 value 的写入；
4. 如果希望展示参考素材有哪些标签：
   - 只能作为只读提示；
   - 不能写入 requested label scope；
5. 用户若想采用参考素材某个标签：
   - 必须显式点击/输入 canonical code；
6. submitAiLabel429 只提交用户显式决定的 labels_text；
7. 审计记录中区分：
   - reference images；
   - requested labels；
   二者不能互相隐式派生。

同时处理 AUDIT-116 时，也不要通过“让参考图标签自动控制 prompt”来代替真正的视觉 reference 支持。

**回归测试建议：**

至少覆盖：

- 用户先输入 smoke，再选择带 person/smoke/phone 的参考图，ai429Labels 仍严格等于 smoke；
- 取消/切换参考图不修改标签输入；
- 批量全选参考图不修改标签输入；
- 参考图标签可只读展示但不进入 submit payload；
- submit payload labels_text 只包含用户显式输入/选择的 canonical codes；
- UI 不再同时出现“不会自动添加”与“自动带出标签”的冲突文案。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-118 — 【已撤销：重复 AUDIT-068】Training SSE / REST queue truth 状态漂移

**状态：REVOKED / DUPLICATE OF AUDIT-068**  
**原级别：高**

后续对统一审计文档做去重时确认：

**AUDIT-118 与 AUDIT-068 是同一个真实问题，不应重复计数。**

AUDIT-068 已经完整记录：

- Training SSE 未复用 canonical `training_queue_truth()`；
- HTTP/REST 可把 persisted QUEUED 投影为 `WAITING_RESOURCE`；
- SSE 只做基础 `task_to_public(task)`，可能重新发出 `QUEUED`；
- 前端 `applyUpdate()` 会把 SSE status 写入 `task_status`；
- stale wait reason / queue metadata 可能与 QUEUED 状态混合；
- 修复时必须避免在 750ms realtime loop 里重新引入 AUDIT-064 的无界 queued hydration。

AUDIT-118 后续新增的 queue metadata 同步建议，归并进 **AUDIT-068** 的修复与回归范围，不再作为独立 issue。

**处理方式：**

- 保留本编号作为审计历史；
- 不删除本条后续原始证据；
- 本条不进入独立修复队列；
- 后续只修 AUDIT-068；
- VERSION 仍按正式审计记录规则递增。

---

#### 原始证据（AUDIT-118，已撤销）— Training SSE / REST queue truth 状态漂移

**级别：高**  
**模块：Training Task / SSE / REST Projection / Queue Truth / Frontend Runtime**

**现象：**

当前训练任务有两条同时生效的读路径：

1. REST：
   `GET /api/projects/{project_id}/jobs`
2. SSE：
   `GET /api/v64/projects/{project_id}/training-events`

两条路径都声称输出 canonical training display truth，但实际对 QUEUED Training 的资源状态解释不一致。

REST 的 `enrich_job_runtime()` 会：

`task_to_public(durable, repository)`

然后对 QUEUED Training 继续执行：

`training_queue_truth(durable, repository, ...)`

该 canonical projection 会根据真实 runtime 判断：

- 当前没有在线 Worker；
- 没有可执行 Training 的 Worker；
- Worker capability 不满足；
- `training:remote:...` 路由尚未建立；
- durable stage 已进入 resource_waiting；

并把展示状态投影为：

`WAITING_RESOURCE`

同时给出：

- resource_wait_reason；
- resource_queue_position；
- resource_queue_position_exact；
- resource_pool_key；
- resource_pool_label。

但 SSE 的 `_training_event_row()` 当前只调用：

`runtime = task_to_public(task)`

没有传 repository，也没有调用 `training_queue_truth()`。

因此对同一个 persisted `QUEUED` task：

- REST 可以返回 `WAITING_RESOURCE`；
- SSE 却返回基础 `QUEUED`。

**前端会真实覆盖 REST 状态：**

`training-progress-stream.js`

收到 `training.task` 后：

`applyUpdate(update)`

会把：

`update.status`

写入：

`task_status`

而统一状态读取：

`canonicalTaskStatus(task)`

明确优先：

`task.task_status ?? task.status`

所以即使页面刚通过 REST 得到：

`WAITING_RESOURCE`

只要初始 SSE event 到达，就会把 `task_status` 改回：

`QUEUED`

随后 `trainingDisplayStatus()` 会把它展示为：

“排队中”

而不是：

“等待资源”。

这不是只少了一个辅助字段，而是同一个 Durable Task 在两个 canonical read owner 中得到不同用户可见状态。

**典型可复现场景：**

场景 A — 没有在线 Worker：

- TaskRepository persisted status = QUEUED；
- REST `training_queue_truth()` → WAITING_RESOURCE / “当前没有在线 Worker”；
- SSE `task_to_public(task)` → QUEUED；
- 前端收到 SSE 后从“等待资源”切回“排队中”。

场景 B — 指定远程训练：

- resource_key = `training:remote:<server>`；
- REST 当前明确投影：
  `WAITING_RESOURCE`
  / “指定远程服务器的 Worker 路由尚未建立”；
- SSE 仍可发 `QUEUED`。

场景 C — capability 不匹配：

- 有在线 Worker，但不满足 requested capabilities；
- REST → WAITING_RESOURCE；
- SSE → QUEUED。

**额外前端不一致：**

SSE `applyUpdate()` 当前只更新：

- task_status；
- persisted_status；
- phase；
- progress；
- worker；
- lease；
- resource_wait_reason；
- 时间 / error 等。

它没有同步更新：

- resource_queue_position；
- resource_queue_position_exact；
- resource_pool_key；
- resource_pool_label。

因此发生漂移后可能形成混合状态：

- `task_status = QUEUED`（来自 SSE）；
- pool / queue metadata 仍是上一轮 REST 的 waiting truth；
- resource_wait_reason 因 nullish merge 还可能继续保留旧 reason。

也就是同一行可能同时携带：

“排队中” + 上一次“等待资源”的 metadata。

**为什么是 Bug / 前后端不一致：**

`_training_event_row()` 的注释明确写：

“Build the same canonical training display truth used by HTTP reads.”

但实现并没有走 HTTP read 使用的 queue projection。

因此当前存在两个训练状态解释 owner：

- REST owner：`training_queue_truth()`
- SSE owner：`effective_task_status()` / raw TaskRecord stage

这违反“同一个 durable truth 只做一次 canonical projection”的收口目标。

**影响：**

- 训练任务页状态可在“等待资源 / 排队中”之间闪烁；
- 用户无法准确判断任务到底只是排队，还是根本没有可执行资源；
- remote training 的“路由尚未建立”提示可能被实时流弱化；
- capability / Worker 配置问题可能被误认为普通排队；
- queue position / pool metadata 与状态可能互相矛盾；
- realtime coverage 完整后 PollRegistry 会让 SSE 成为主要更新源，错误状态可持续存在直到下一次 REST reconcile；
- 运维现场容易错误判断 Scheduler / Worker / GPU 是否正常。

**与已有问题的区别：**

- AUDIT-063：Central Scheduler 缺生产 assignment driver，是调度执行链问题；
- AUDIT-064：task public projection 为 exact queue truth 做无界 queued hydration，是性能问题；
- AUDIT-066：Training jobs REST 每次扫描全量 job history，是性能问题；
- AUDIT-118：REST 与 SSE 对**同一个 Training Task 的资源等待状态投影不一致**，属于 read-model contract split。

不需要重新设计 Scheduler 或 TrainingTaskRuntime。

**建议最小修复：**

不要在前端再补第二套资源判断。

应让 SSE 与 REST 共享同一个 Training public projection，例如：

1. 抽出单一 helper：
   - `task_to_public(...)`
   - 对 Training QUEUED 统一叠加 `training_queue_truth(...)`；
2. `enrich_job_runtime()` 与 `_training_event_row()` 都调用该 helper；
3. SSE event 同步携带并更新：
   - status；
   - resource_wait_reason；
   - resource_queue_position；
   - resource_queue_position_exact；
   - resource_pool_key；
   - resource_pool_label；
4. 不要让浏览器根据 Worker 数量自行重新推导 WAITING_RESOURCE；
5. 保留 persisted_status=QUEUED，展示状态与持久化状态继续分离。

同时要注意 AUDIT-064：不能为了 SSE 每 750ms projection 又重新引入全量 `queued_candidates()` hydration。queue truth 必须使用 bounded/indexed query 或共享一次 runtime snapshot。

**回归测试建议：**

至少覆盖：

- persisted QUEUED + no online Worker：
  REST 与 SSE 都必须 WAITING_RESOURCE；
- remote resource key：
  REST 与 SSE reason 完全一致；
- capability mismatch：
  REST 与 SSE status/reason 一致；
- resource 可用：
  两边都为 QUEUED；
- SSE applyUpdate 后：
  task_status / pool / queue position / wait reason 同步更新，不保留混合旧 truth；
- REST reconcile → SSE event 不得把 waiting 行重新改回 queued；
- 100 active Training SSE 仍保持 bounded；
- 1k/10k/20k 全局 queued task 下不能因 realtime projection 退化为 O(N) 每 750ms 扫描。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-119 — Training SSE 每 750ms 在签名比较前无条件读取最多 100 个 active job.json；无状态变化也持续产生高频磁盘 I/O

**级别：中～高**  
**模块：Training Realtime / SSE / job.json / Performance / 1k-20k Scale**

**现象：**

当前 v64 Training realtime endpoint：

`GET /api/v64/projects/{project_id}/training-events`

的 event loop 固定：

`await asyncio.sleep(0.75)`

即每个连接约每秒 1.33 次循环。

每一轮都会先调用：

`_training_event_rows(project_id, repository)`

该函数读取最多 100 个 active Durable Training task，然后逐个调用：

`_training_event_row(project_id, task)`。

而 `_training_event_row()` 对每个 task 都执行：

`job_file = ... / "jobs" / task.task_id / "job.json"`

`worker_job = read_json(job_file, {}) if job_file.exists() else {}`

当前 `read_json()` 没有 cache / mtime gate / revision gate，真实实现就是：

- `path.exists()`
- `path.read_text(encoding="utf-8")`
- `json.loads(...)`

之后才构造 display row。

SSE 的去重：

`_training_event_signature(row)`

是在 **job.json 已经读取和解析完成以后** 才比较。

因此即使：

- TaskRecord 没有变化；
- worker progress 没有变化；
- browser 最终不会收到任何 training.task event；

服务器仍然会每 750ms 对所有 active task 重新读取并解析 job.json。

**规模影响：**

单个浏览器连接、100 个 active Training 时：

- 100 个 job.json / 0.75 秒；
- 约 133 次文件读取与 JSON parse / 秒。

多个用户同时打开训练任务页时，成本按连接数线性叠加：

- 3 个浏览器：约 400 次 job.json read / 秒；
- 5 个浏览器：约 667 次 / 秒。

这还不包括：

- TaskRepository list query；
- terminal disappearance lookup；
- Worker/queue truth 后续修复可能引入的额外 projection 成本。

在：

- HDD；
- NFS / 网络挂载；
- 大量并发训练；
- job.json 逐渐包含更多 runtime 字段；

场景下会形成持续 metadata I/O 与 JSON parse 压力。

**为什么是独立问题：**

AUDIT-066 已记录：

`GET /api/projects/{project_id}/jobs`

会在一次 REST refresh 中扫描全历史 job 目录，再截断为 active + recent 50。

AUDIT-119 不同：

- 不扫描 terminal history；
- 只针对 active task；
- 但频率是 750ms；
- 即使没有任何状态变化也持续读盘；
- 每个 SSE client 都会独立重复同样工作。

所以一个是：

“bounded 输出前做 unbounded history hydration”

另一个是：

“bounded active set 的高频重复 filesystem hydration”。

两者会同时存在。

**与 AUDIT-068 的关系：**

AUDIT-068 要求 SSE 与 REST 共享 canonical queue truth。

修 AUDIT-068 时如果直接在每个 `_training_event_row()` 再做：

- Worker runtime lookup；
- queue candidates hydration；
- resource projection；

会进一步放大本条热路径。

因此 realtime projection 必须以“单轮共享 snapshot + 变更驱动/mtime gate”为边界，不能变成 per-task N+1。

**影响：**

- Web 进程长期持续小文件读取；
- active task 越多，realtime 开销线性增加；
- 多个浏览器/大屏同时打开时重复放大；
- 服务器 CPU 消耗在重复 JSON decode；
- 磁盘/NFS latency 可能反过来拖慢 SSE loop；
- 训练任务页 realtime 本意是减少 polling，却可能用更高频文件读取换来网络少发 event；
- 100 active task 下已经足以形成稳定后台负载，不需要 10k history 才触发。

**现有测试缺口：**

当前 realtime tests 主要验证：

- event 内容；
- stream coverage；
- terminal reconcile；
- reconnect / fallback；
- display revision 防旧数据覆盖。

没有规模合同断言：

- 100 active task；
- 连续多个 750ms cycle；
- 没有任何 runtime change；
- job.json file read count 必须接近 0 / bounded，而不是每轮 100 次。

也没有多 client SSE 的共享 hydration 测试。

**建议最小修复：**

不要新增第二 Training progress owner。

保留：

- TaskRepository = lifecycle truth；
- worker job.json = worker progress compatibility/artifact；

但 realtime read 应增加明确的 change gate：

1. event loop 先读取 bounded TaskRecord metadata；
2. 只有 worker progress identity 变化时才读取对应 job.json，例如：
   - durable display/progress revision；
   - worker progress revision；
   - persisted mtime/size token；
   - 或 canonical task-owned lightweight progress store；
3. 同一轮多个字段 projection 共享一次 runtime snapshot；
4. 多 SSE client 如可行应共享 project-level read snapshot，而不是每连接独立全量 hydrate；
5. terminal final read 仍允许一次强制 hydrate；
6. 不要靠把 750ms 改成更大的固定间隔来掩盖结构问题。

**回归测试建议：**

至少覆盖：

- 100 active Training；
- 10 个连续 realtime cycles 无变化；
- job.json 实际读取次数有明确 bounded 上限；
- 单个 task progress revision 变化时只 hydrate 该 task；
- terminal task 仍能发送最后一次完整 truth；
- 多 client 不应线性重复相同 filesystem hydration；
- 修 AUDIT-068 后 Worker/queue projection 也不能产生 per-task N+1；
- 1k/10k/20k terminal history 不影响 SSE active-loop 成本。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-120 — Page Visibility 只暂停 Training poll；AI / Video / Cleaning / Source 在隐藏标签页仍持续高频请求，后台客户端会长期制造无效 API 负载

**级别：中**  
**模块：PollRegistry / Page Visibility / AI Annotation / Video Frames / Cleaning / Source Collection / Frontend Performance**

**现象：**

当前统一 `PollRegistryRuntime` 已监听：

`document.visibilitychange`

但进入：

`document.visibilityState === 'hidden'`

时只清理：

- `training-jobs`
- `training-clock`

其它当前页面 owner 的轮询没有一起暂停。

已确认至少存在：

- AI 自动标注：约 1800ms；失败重试约 4000ms；
- Video Frames：约 2000ms；
- Cleaning：约 2200ms；
- Source：约 2500ms。

这些 timer 都依赖“当前 state.page / tab owner 仍匹配”，而浏览器标签页隐藏并不会改变这些 state，所以仍满足 owner 条件。

**真实调用链：**

PollRegistry：

`onVisibilityChange()`

当前逻辑：

```js
if (doc?.visibilityState === 'hidden') {
  registry.clear('training-jobs');
  registry.clear('training-clock');
  return;
}
```

没有清：

- `video-frames`
- `clean-tasks-v47`
- `sources`
- AI 的 managed poll key。

Video：

`replaceVideo424Timer()`
→ active task 时 `startTimeout(..., 2000)`
→ refresh 后重新 arm。

Cleaning：

`replaceCleanTaskTimer()`
→ active clean 时 `startTimeout(..., 2200)`
→ refresh 后重新 arm。

Source：

`replaceSourceTimer()`
→ 只要页面仍是“素材接入”
→ `startInterval(..., 2500)`

它甚至不要求存在 active task，因此隐藏标签页可以长期固定请求。

AI：

`AutoLabelPollRuntime.schedule()`
→ active annotation task
→ `startTimeout(..., pollDelay=1800)`
→ `refreshRows()`
→ 成功后再次 `schedule()`；
→ 失败后 `retryDelay=4000`。

该 runtime 没有任何：

- `document.visibilityState`
- `document.hidden`

判断。

**为什么是 Bug / 生命周期不一致：**

同一个 PollRegistry 已经明确把“页面不可见时暂停高频实时请求”作为 Training 的运行时合同，但该 visibility lifecycle 没有覆盖同 registry 下的其它 domain owner。

浏览器自身可能对后台 timer 做 throttling，但这不能作为应用层 polling owner：

- 停止请求；
- 立即恢复；
- 首次可见时强制 reconcile；

的可靠合同。

不同浏览器、前台/后台时长、节电策略下节流行为也不同。

**额外恢复不一致：**

标签页重新 visible 后：

`resyncVisiblePage()`

显式支持：

- Training；
- Video；
- Cleaning；
- Source。

但没有 AI label tab 分支。

也就是说，即使后续把 AI timer 在 hidden 时清掉，当前统一恢复 owner 也不会自动重新拉取 AI truth；AI 的 visibility lifecycle 目前完全不在 canonical PollRegistry 管理范围内。

**影响：**

- 用户切到其它浏览器标签后，后台页面仍持续打 API；
- 多个管理终端 / 大屏 / 长期开着的浏览器会线性放大请求；
- Source 页面可在完全无业务变化时长期每 2.5 秒请求；
- active AI / Video / Cleaning 持续造成数据库查询、task projection、JSON 解析与 DOM state work；
- 与 AUDIT-064、AUDIT-066、AUDIT-089、AUDIT-119 等后端热路径叠加后，单个“没人看的浏览器标签”也可持续触发昂贵请求；
- 移动端/笔记本增加网络与电量消耗；
- AI 页重新可见时缺少统一 immediate reconcile，可能短时间继续展示后台期间的旧状态。

**与已有问题的区别：**

- AUDIT-064：后端 task public projection 的 queue hydration 无界；
- AUDIT-089：ZIP polling endpoint 内部扫描历史 job；
- AUDIT-119：Training SSE 750ms 高频读取 active job.json；
- AUDIT-120：浏览器页面已经不可见时，多个前端 poll owner 仍继续触发这些请求。

本条是前端 polling lifecycle / visibility owner 问题，不重复后端单请求成本问题。

**建议最小修复：**

不要给每个模块再加各自一套 visibility listener。

继续让：

`PollRegistryRuntime`

作为唯一页面 polling lifecycle owner。

建议：

1. hidden 时统一 pause 所有 **UI-only realtime poll**：
   - training-jobs / clock；
   - video-frames；
   - clean-tasks-v47；
   - sources；
   - auto-label managed key；
2. Durable Worker / Server-side task 继续后台执行，浏览器只停止读侧 polling；
3. visible 时按当前 page + tab 做一次 immediate scoped reconcile；
4. reconcile 完成后由各 canonical owner 重新 arm timer；
5. AutoLabelPollRuntime 提供明确的 visibility pause/resume hook，或由 PollRegistry 调其 activate/deactivate；不要新增第二 document listener；
6. 不要暂停必须承担用户可见通知语义的 server-side automation；这里只处理浏览器 UI polling。

**回归测试建议：**

至少覆盖：

- Video active → hidden：timer 清除，无新 GET；
- Cleaning active → hidden：timer 清除；
- Source page → hidden：2.5s interval 清除；
- AI active → hidden：1.8s timer 清除；
- visible 后当前 owner 立即只 refresh 一次；
- visible 后只重启当前 page/tab 对应 poll；
- hidden/visible 连续切换不会产生重复 timer；
- Training 现有 visibility 合同保持；
- Durable task 在隐藏期间继续在服务器执行，重新可见后能恢复最新状态。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-121 — waitForTaskTerminal 把一次状态读取失败直接当成等待流程失败；后台 Durable Task 仍运行，前端却可误报失败并继续创建后续任务

**级别：高**  
**模块：Task Poller / Durable Task Read Path / Quality Center / AI Review / RKNN Verification / Frontend Runtime**

**现象：**

当前通用前端 helper：

`static/modules/task-poller.js`

中的：

`waitForTaskTerminal()`

用于等待 Durable Task 从 active 状态进入真实 terminal。

但它对轮询读取异常的处理是：

```js
try {
  task = await load(task);
  onUpdate(task);
  if (isTaskActive(task)) scheduleNext();
  else settle('resolve', task);
} catch (error) {
  onError(error);
  settle('reject', error);
}
```

也就是说：

**任何一次 `load()` 失败，都会立刻结束整个 terminal waiter。**

没有：

- retryable transport error 判断；
- 5xx retry；
- 短暂断网恢复；
- consecutive failure budget；
- backoff；
- “状态暂时未知”语义；
- 重新按 task_id reconcile。

这与 Durable Task 本身的生命周期完全无关。

后台任务可能仍处于：

- QUEUED；
- WAITING_RESOURCE；
- RUNNING；
- CANCEL_REQUESTED；

但浏览器已经停止等待。

**真实生产调用 1 — Quality Center Deployment Test：**

当前 canonical：

`window.benchPredictOne()`

会：

1. POST 创建：
   `/api/v61/projects/{project_id}/deployment-tests`
2. 得到真实 Durable `taskId`
3. 调：
   `waitForTaskTerminal(... delay=900, maxAttempts=700)`
4. `load()` 每轮 GET：
   `/api/v62/projects/{project_id}/tasks/{taskId}`

如果任意一次 GET 因：

- 短时网络抖动；
- 网关 502/503；
- Web worker 瞬时重启；
- 浏览器临时连接失败；

抛错，waiter 立即 reject。

上层 `runBenchBatch64()` 的 catch 随即：

- `row.status='failed'`
- 写入 error；
- `run.failed += 1`
- 继续下一图片 / 下一 side。

但该 Deployment Test：

**没有被 cancel。**

因此会形成：

- UI 报“该图片检测失败”；
- 原 Durable task 仍继续占用 GPU / Worker / Agent；
- batch 又继续创建新 Deployment Test；
- 同一批检测资源可出现不必要重叠；
- 原任务后续成功，当前 batch row 仍保留前端假失败。

这与 AUDIT-107 不同：

- AUDIT-107：用户主动点击“停止检测”时未 cancel 当前 task；
- AUDIT-121：用户什么都没做，只是一次**读侧网络错误**，前端就放弃等待并把业务标成 failed。

**真实生产调用 2 — AI 任务详情：**

`showAiTask60()`

打开详情后：

`waitForTaskTerminal(... delay=1600)`

任何一次 task detail GET 失败都会直接进入外层 catch：

- toast error；
- detail waiter 结束；
- list poller 被重新激活。

后台 AI task 仍可能正常运行。

因此用户看到的错误不是任务真实 failure，只是状态读取 failure。

**真实生产调用 3 — AI Review Commit：**

用户确认候选后：

`POST .../decisions`

如果后端返回：

`queued_for_commit=true`

说明：

**人工审核决定已经正式接受，后台正在把候选写入 AnnotationRepository。**

前端随后用：

`waitForTaskTerminal(... delay=700)`

等待 commit task terminal。

如果此时单次 GET 失败：

- waiter reject；
- 外层 catch 直接 toast error；
- 前端停止跟踪；
- 后台 Commit 仍继续；
- 用户容易误以为“审核入库失败”。

如果用户因此重复操作，还会增加重复提交/状态困惑风险。

**真实生产调用 4 — RKNN 实机验证：**

`submitRknnHardwareVerify()`

创建 hardware-test 后：

`waitForTaskTerminal(... delay=900, maxAttempts=700)`

一旦读取失败就进入 catch，并把状态区域显示为 error。

真实板端 Agent task 仍可能继续执行并最终 SUCCEEDED。

因此“读取链故障”和“板端验收失败”被错误折叠为同一 UX 结果。

**为什么是 Bug / 前后端合同漂移：**

Durable Task 的真实终态只能由：

- canonical TaskRepository；
- Worker / Agent execution；
- finalization；

决定。

浏览器 GET 失败只能说明：

“当前无法读取 task truth”。

它不能推导：

“task 已失败”。

当前 helper 把：

`read failure`

错误提升成：

`terminal waiter failure`

而多个业务调用方又把 waiter reject 当成本次业务操作失败，破坏了 Durable Task 的容错价值。

**影响：**

- 短时网络抖动导致前端假失败；
- Quality Center 可能继续创建后续 GPU/Agent task，与仍运行的旧 task 重叠；
- AI Review 已经入库中的任务被显示成失败/异常；
- RKNN 实机任务继续跑但 UI 提前退出；
- 用户可能重复点击重试/重新创建任务；
- 状态页和后台真实 TaskRepository 长时间不一致；
- 生产环境反向代理、Wi-Fi、移动网络下更容易触发；
- Durable Worker 的 lease/recovery 正确也无法弥补前端读侧一次性失败。

**为什么现有测试没发现：**

当前 task-poller tests/调用方测试主要覆盖：

- active → terminal；
- timeout attempt limit；
- PollRegistry owner clear / AbortError；
- 正常任务完成。

缺少：

- 第 N 次 GET 抛一次 retryable network error；
- 下一次 GET 恢复；
- waiter 必须继续；
- Quality Center 不得把读失败记为模型检测失败；
- 已接受 AI review 不得因为 status GET 失败被当成 commit failure。

**建议最小修复：**

不要在各业务页面各自造 retry loop。

继续让：

`waitForTaskTerminal()`

作为统一 terminal waiter owner，但增加“读侧错误 ≠ 业务终态”的合同。

建议：

1. 区分 error 类型：
   - AbortError / PollRegistry clear：立即结束，保持当前正确行为；
   - 401/session expiry：交给统一登录/session owner（同时关联 AUDIT-115）；
   - 404 task genuinely missing：明确 terminal read error，可 fail；
   - network / fetch failure / 502 / 503 / 504：视为 retryable；
2. retryable error：
   - 调 `onError` 展示“状态读取暂时失败，正在重试”；
   - 保留 last known task；
   - bounded exponential/backoff 或固定短延迟；
   - 设置 consecutive failure budget / total deadline；
3. retry budget 用尽后：
   - 返回“状态未知 / 无法确认”错误；
   - **不能把 Durable Task 自己标成 FAILED**；
4. Quality Center：
   - waiter 读失败时不能把 row 当模型推理 failed；
   - 在 task truth 未确认前不能继续创建会冲突的后续 side/task；
   - 应按 task_id reconcile 后再决定；
5. AI Review：
   - decisions 已 accepted 后，poll error 只代表“入库状态暂时未知”；
   - 不允许把它文案化成“审核提交失败”；
6. RKNN Verify：
   - 区分 “board task FAILED” 与 “无法读取 board task”。

不要通过无限重试掩盖真实故障，必须 bounded。

**回归测试建议：**

至少覆盖：

- active task → 第 2 次 load network error → 第 3 次恢复 RUNNING → 最终 SUCCEEDED；
- 502/503/504 可 bounded retry；
- 404 明确失败；
- PollRegistry clear 仍立即 AbortError；
- retry budget 耗尽返回 status unknown，不篡改 task status；
- Quality Center 单次 GET 失败不增加 `run.failed`，不创建下一 side；
- AI review commit 单次读取失败后可继续等到 SUCCEEDED；
- RKNN verify 单次读取失败后仍可得到最终验收成功；
- 重连期间不得创建重复 task。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-122 — Quality Center 批量检测没有 navigation owner；离开页面后可继续创建 Deployment Test，或在 GET 已 in-flight 时永久卡住 batch

**级别：高**  
**模块：Quality Center / Navigation Stability / PollRegistry / PageRequestScope / Deployment Test Lifecycle**

**现象：**

当前 `runBenchBatch64()` 是浏览器内长生命周期 async workflow。每张图片会创建 Durable Deployment Test，再通过 `waitForTaskTerminal()` 等待终态；compare 模式继续创建第二 side，之后进入下一张。

但该 batch 没有绑定 NavigationStability action/token、page epoch 或 navigation cancel flag。

导航真实链为：

`NavigationStability.setPage(nextPage)`
→ `pollRegistry.beforeNavigate(requested)`
→ `registry.leave(nextPage)`

Deployment Test waiter 的 owner 是“质量中心”，因此离页时会清理当前仍在等待的 one-shot timer，并通过 `onClear` 让 waiter reject `AbortError`。

**分支 A — 导航发生在 polling timer 尚未触发时：**

`runBenchBatch64()` 的内层 catch 不区分 AbortError，会：

- 把当前 row 标成 failed；
- 写入 error；
- `run.failed += 1`；
- 然后继续 batch loop。

它不会设置 `run.cancelled=true`，也不检查当前页面是否仍是质量中心。

于是下一 side / 下一图片会继续执行 `benchPredictOne()`，再次：

`POST /api/v61/projects/{project_id}/deployment-tests`

即：

**用户已经离开质量中心，浏览器仍可能继续创建新的 GPU / Worker / Agent 检测任务。**

同时 `PollRegistry.startTimeout()` 注册时只保存 ownerPages，不验证“当前页面是否仍属于 owner”。由于 `registry.leave()` 已经在本次导航开始时执行过，导航后新注册的 waiter 不会被刚才那次 leave 清掉，因此可以在其它页面继续 polling。

**分支 B — 导航发生在 task GET 已经 in-flight 时：**

PollRegistry one-shot callback 开始时会先从 registry 删除自己的 entry，再执行 callback。

如果此时导航，`PageRequestScope.navigate()` 会 abort 旧页面 GET。对导航导致失效的 GET，PageRequestScope 为避免旧页面 catch/toast，会返回永不 settle 的 `NEVER`。

于是：

- `load()` 永不 resolve/reject；
- waiter 永不 settle；
- 当前 poll entry 又已从 registry 删除；
- navigation 无法再通过 `onClear` 终止它；
- `runBenchBatch64()` 永久卡在当前 await；
- `run.running` 可长期保持 true。

所以同一导航动作存在两个真实竞态结果：

1. timer pending → AbortError → batch 错误地继续在别页创建后续 task；
2. GET in-flight → NEVER → batch 永久悬挂。

**为什么是 Bug / Owner 缺失：**

PollRegistry 只拥有“单次 terminal waiter timer”，不能替代整个 Detection Batch workflow owner；PageRequestScope 只防旧 GET 回写，也不会阻止后续 POST side effect。

当前“页面已离开”和“batch 是否仍允许创建新的 Durable Task”完全解耦。

**与已有问题的区别：**

- AUDIT-107：用户显式点“停止检测”时不 cancel 当前 Durable task；
- AUDIT-121：仍在当前页面时，单次状态读取错误被误当业务失败；
- AUDIT-122：页面导航没有终止 batch workflow，导致 off-page task creation 或永久悬挂。

**影响：**

- 离开质量中心后仍继续创建 Deployment Test；
- 当前 task 未 cancel、下一 task 又创建，资源可重叠；
- 当前 row 被错误标 failed；
- 其它页面后台继续出现质量中心 polling；
- 大批量任务可在用户不可见状态持续执行；
- in-flight 导航竞态可让 batch 永久保持 running；
- 用户回到质量中心后可能看到 stale batch 状态并再次启动任务。

**建议最小修复：**

不要新增第二 Deployment Test owner。

1. batch 创建时冻结 project_id、navigation epoch、run generation；
2. 每次 side/task 创建前检查 owner token 仍 current；
3. 页面离开时把本地 batch workflow 标记为 aborted，禁止后续 task creation；
4. navigation AbortError 不能计为模型检测 failed；
5. terminal waiter 增加独立 generation/abort signal，导航时必须能 settle，不能被 PageRequestScope 的 NEVER 永久悬挂；
6. PollRegistry 可增加可选 owner-current guard，避免在已经离开 owner page 后注册 UI-only timer；
7. 当前已创建 Durable task 是否自动 cancel，应与 AUDIT-107 的显式 Stop 语义分开定义；无论是否 cancel，都必须停止创建后续 task。

不要把 POST 纳入通用 GET PageRequestScope 自动 abort，因为 POST 是否已被服务器接受存在不确定性，容易制造重复提交。

**回归测试建议：**

至少覆盖：

- timer pending 时导航离页：waiter Abort，但 batch 不标模型失败、不创建下一 task；
- GET in-flight 时导航：waiter settle AbortError，`run.running` 最终 false；
- 导航后不得注册新的 Deployment Test waiter；
- 导航后 Deployment Test POST 数量不再增加；
- project switch 同样终止旧项目 batch workflow；
- AUDIT-107 显式 Stop 与 AUDIT-121 transient read retry 合同保持独立且正确。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-123 — PageRequestScope 用 NEVER 吞掉导航 abort；GET 调用方的 finally / single-flight 清理永不执行，可永久卡死 loading=true 与 refreshPromise

**级别：高**  
**模块：PageRequestScope / Navigation / Async Cleanup / Storage Sources / Online Feedback / Frontend Runtime**

**现象：**

当前 `PageRequestScope.fetch()` 会自动接管同源 API 的 GET/HEAD。

页面导航时：

`PageRequestScope.navigate()`

会 abort 当前 controller，并递增 page generation。

对于这种“因为页面导航而失效”的 GET，catch 并不是 reject AbortError，而是：

```js
if (isAbortError(error) && (controller.signal.aborted || !this.isCurrent(generation, page))) {
  this.abortedRequests += 1;
  return NEVER;
}
```

其中：

`const NEVER = new Promise(() => {})`

即 Promise 永远不会 resolve / reject。

设计意图是避免旧 app.js 调用方 catch 后弹出“请求失败” toast，但副作用是：

**任何依赖 await 后 finally / promise.finally 做运行时清理的调用方都会永久停在 await。**

**明确可复现 1 — Storage Sources：**

`loadStorageSources61()` 当前：

1. 如果 `state.storageSourcesLoading61` 为 true，直接返回已有 snapshot；
2. 否则设置：
   `state.storageSourcesLoading61=true`
3. await：
   `api('/api/v61/storage-sources')`
4. 仅在 `finally`：
   `state.storageSourcesLoading61=false`

如果用户在第 3 步 GET in-flight 时切换页面：

- PageRequestScope abort GET；
- fetch 返回 NEVER；
- `api()` 永远不返回；
- `loadStorageSources61()` 永远不进入 finally；
- `storageSourcesLoading61` 永久保持 true。

之后用户重新进入“存储配置”：

`loadStorageSources61()`

第一句命中：

`if(state.storageSourcesLoading61) return state.storageSources61`

因此不会再发任何 GET。

如果这是首次加载：

- 页面可能长期只看到空/旧 snapshot；
- “刷新”也无法恢复，因为 loading flag 仍是 true。

只有整页 reload / 手工重置 state 才能恢复。

**明确可复现 2 — Online Feedback：**

`loadOnlineFeedback63()` 用：

- `state.onlineFeedback63RefreshPromise`
- `state.onlineFeedback63RefreshProjectId`

实现 single-flight。

它创建：

`task = api(...).then(...).catch(...).finally(...)`

并且只有在 `.finally()` 中清：

- `onlineFeedback63RefreshPromise=null`
- `onlineFeedback63RefreshProjectId=''`

如果导航期间该 GET 被转成 NEVER：

- then 不执行；
- catch 不执行；
- finally 也永远不执行；
- 同项目再次打开质量中心时：
  `if(refreshPromise && refreshProjectId===projectId) return refreshPromise`
- 返回的仍是同一个 NEVER。

于是这个项目的“线上抽检 / 反馈”读取可以永久失去刷新能力，直到页面重载或别的路径覆盖该 state。

**补充证据 — Upload Task Center 这个跨页面全局 owner 也会被 page scope 误伤：**

安装顺序已确认：

`installPageRequestScope()`

先于：

`installUploadTaskCenter()`

执行。

所以 Upload Task Center 的默认：

`fetchImpl = globalThis.fetch`

实际捕获的是已经被 PageRequestScope 包装后的 fetch。

Task Center 本身明确是跨页面 owner：

- pollOwners 覆盖几乎所有主页面；
- visibility 自己管理 hidden/visible；
- active ZIP / Storage Import 应在用户切到其它业务页面后继续显示进度。

但 `PageRequestScope.navigate()` 会在任何页面导航时 abort 当前 controller，不区分：

- 页面局部 GET；
- 跨页面全局 Task Center GET。

如果导航恰好发生在：

`poll()`
→ `Promise.all(active.map(refreshDurable))`
→ `fetchImpl(row.serverUrl)`

期间，则 refreshDurable 的 GET 会被转成 NEVER。

结果：

- refreshDurable 永不返回；
- Promise.all 永不 settle；
- `poll()` 永远到不了末尾 `arm()`；
- one-shot PollRegistry callback 开始时当前 entry 已移除；
- Task Center 的后台自动刷新可永久停止。

它只有在后续：

- 新任务 upsert；
- visibility change；
- project switch；
- 手工 runtime.refresh

等其它事件重新触发 `arm()` 时才可能恢复。

这证明 PageRequestScope 当前不仅会毒化页面局部 loading flag，还会破坏本应跨页面存活的全局 owner。

修复时应明确区分：

- page-scoped request；
- app-global/background owner request。

Upload Task Center 的 Durable status GET 不应被普通页面导航取消。

**为什么是系统性问题：**

问题不属于 Storage Sources 或 Online Feedback 单一模块，而是 PageRequestScope 对“导航失效请求”的统一语义。

所有类似模式都有风险：

- `loading=true; try { await GET } finally { loading=false }`
- `refreshPromise = GET.finally(()=>refreshPromise=null)`
- UI button disabled → await GET → finally enable；
- modal hydration state → await GET → finally clear；
- long-running workflow 中 await GET。

只要该 GET 在导航时 in-flight，就可能永远没有清理机会。

AUDIT-122 已展示同一 NEVER 语义在 Quality Center terminal waiter 中会让整个 batch 永久悬挂；AUDIT-123 记录的是更基础的：

**普通 GET single-flight / loading owner 被永久毒化。**

**为什么这是 Bug：**

“旧页面结果不能回写新页面”是正确要求。

但实现不应通过一个永不 settle 的 Promise 来保证。

一个异步调用一旦永不 settle：

- finally 不执行；
- resource/owner 不释放；
- single-flight 槽位不释放；
- 调用者没有任何机会识别 navigation cancellation。

这等价于把“取消”变成“永久 pending”，破坏正常 JavaScript async lifecycle。

**影响：**

- 页面切换时容易产生永久 loading flag；
- single-flight promise 永久占位；
- 回到原页面后无法重新请求；
- 用户点击刷新无效；
- 旧数据/空数据长期显示；
- 运行中的按钮、loading 动画、局部状态可能无法复位；
- 长时间使用单页应用时问题会累积；
- 只有整页刷新才能恢复，容易被误判为后端接口失效。

**建议最小修复：**

不要删除 NavigationStability / PageRequestScope，也不要允许旧请求回写。

应把“导航取消”改成**可 settle 的取消语义**。

最小方向：

1. GET 因 navigation abort 时 reject 一个明确的：
   - AbortError；或
   - `NavigationSupersededError`
2. 保证 caller 的：
   - catch；
   - finally；
   - single-flight cleanup
   一定可以执行；
3. 为避免 legacy catch/toast：
   - 在统一 `safe()` / UI action guard 中识别 navigation-abort 并静默；
   - 或调用方在 catch 前用 NavigationStability token 判断是否仍 current；
4. 不要在 fetch 底层用 NEVER 阻断 Promise settlement；
5. 所有 loading/single-flight owner 都应在 finally 释放；
6. 对 stale response 继续使用 generation guard，禁止旧页面 mutation。

**回归测试建议：**

至少覆盖：

- Storage Sources GET in-flight → 导航 → finally 执行，loading=false；
- 返回存储配置后可以重新 GET；
- Online Feedback GET in-flight → 导航 → refreshPromise 清空；
- 返回同项目可重新加载；
- navigation abort 不弹业务失败 toast；
- stale response 不写入新页面；
- multiple rapid navigation 不留下 pending Promise；
- PageRequestScope stats 仍记录 abortedRequests；
- AUDIT-122 的 terminal waiter 也必须能收到可识别 AbortError，不再永久挂起。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-124 — Component Scan 在 RKNN 后处理完成前提前发布 status=done；前端可停止轮询并缓存缺失 RKNN-Toolkit2 的“伪终态”5 分钟

**级别：中～高**  
**模块：Component Scan / RKNN-Toolkit2 / Backend Completion Semantics / Frontend Polling / Cache Consistency**

**现象：**

当前 v40/v41 组件检测实际存在两阶段执行：

第一阶段是原始 v40：

`_v40_run_component_scan(scan_id)`

第二阶段 v41 又保存旧函数并重新定义同名函数：

```python
_v41_old_component_scan = _v40_run_component_scan

def _v40_run_component_scan(scan_id):
    _v41_old_component_scan(scan_id)
    ...
    # 再检测 RKNN-Toolkit2
    comps.append(...)
    caps.append(...)
    scan.update(...)
    _v40_scan_write(scan_id, scan)
```

问题在于旧 v40 实现结束时已经执行：

- `scan.update(status="done", progress=100, stage="检测完成", ...)`
- `_v40_scan_write(scan_id, scan)`

而 `_v40_scan_write()` 在：

`status == "done"`

时还会立即覆盖：

`latest.json`

所以系统在 **RKNN-Toolkit2 尚未检测之前**，已经向 API 和 latest snapshot 发布了一次完整终态 `done`。

随后 wrapper 才继续：

- 检查 local Rockchip resource；
- 检查 remote Rockchip resource；
- 调 `_detect_local_deploy_resource()` / `_detect_remote_deploy_resource()`；
- 生成 `rknn_toolkit2` component；
- 生成“瑞芯微 RKNN” capability；
- 重算 summary；
- 再次写同一个 status=done。

**真实前端竞态：**

组件检测页面每约 650ms：

`pollComponentScanV40(id)`

读取：

`GET /api/v40/system/components/scan/{id}`

只要某一轮恰好落在：

“旧 v40 已写 done”
→
“v41 RKNN 后处理尚未写回”

这个窗口，前端就会读取到：

- status = done；
- progress = 100；
- stage = 检测完成；
- 但 components 中没有 `rknn_toolkit2`；
- capabilities 中没有最终“瑞芯微 RKNN”结果；
- summary 也是未包含该项的旧统计。

前端看到 `done` 后立即：

- 不再 arm 下一轮 poll；
- 启用“重新检测”按钮；
- toast “组件检测完成”。

因此后端稍后虽然把完整 RKNN 结果写回同一 scan JSON，当前页面也不会再读取。

**5 分钟缓存会继续放大：**

前端 `COMPONENT_SCAN_CACHE_TTL_MS = 5*60*1000`。

一旦前端在竞态窗口缓存了第一次 done snapshot：

`persistComponentScanCacheV40()`

再次进入组件检测页时：

```js
const cacheFresh =
  !!state.componentScan &&
  !componentScanActive() &&
  loadedAt ... < 5min

if (cacheFresh) {
  clearComponentScanPollV40();
  return true;
}
```

也就是说，虽然服务器上的：

- scan JSON；
- latest.json

已经被 wrapper 补成完整 RKNN 结果，浏览器仍可以在 5 分钟内持续显示旧的“伪终态”。

**为什么是 Bug / 前后端终态合同破坏：**

`done` 应代表：

“该 scan 的所有 canonical 检测阶段已经结束，结果不会再变化。”

当前却存在：

`done -> components/capabilities/summary 继续变化`

即 terminal record 仍被后续业务逻辑修改。

这会破坏：

- 前端停止轮询条件；
- latest snapshot 的原子性；
- terminal cache 合法性；
- 用户对“检测完成”的理解。

这是典型的“终态过早发布”，不是普通展示延迟。

**影响：**

- Rockchip 用户可能看到“检测完成”，却缺少 RKNN-Toolkit2 检测项；
- “瑞芯微 RKNN” capability 可暂时缺失；
- summary 总数 / ready / missing 统计可能少一项；
- 用户可能误以为 RKNN 资源未纳入组件检测；
- 再次进入页面仍因 5 分钟 terminal cache 显示旧结果；
- 自动截图/验收测试如果在第一次 done 时抓取，也会得到不完整 truth；
- latest.json 短时间内对其它消费者同样暴露中间终态。

**为什么 CI 不容易发现：**

单元/接口测试通常：

- 调 scan；
- 等线程完全结束；
- 最后读取 JSON。

这样只能看到 wrapper 第二次写入后的最终结果。

缺少合同测试去观察：

- 第一次出现 status=done 的那一刻；
- 后续是否还能发生内容变化。

只要测试不在两个阶段之间采样，就捕捉不到竞态。

**建议最小修复：**

不要新增第二 Component Scan owner，也不要让前端针对 RKNN 特判多轮 done。

应统一后端完成语义：

1. 原始 v40 scan 核心不要自行最终 `status=done`；
2. 把基础检测拆成“running 阶段结果”，由最外层 canonical runner 在所有扩展检测完成后一次性：
   - 计算最终 components；
   - capabilities；
   - summary；
   - atlas；
   - RKNN；
   - 写 `status=done`；
3. `latest.json` 只能在真正最终终态时发布一次；
4. 如果暂时保留 wrapper，旧阶段完成时最多写：
   - status=running；
   - stage=检查 RKNN-Toolkit2；
   - progress < 100；
5. terminal record 写出后禁止再修改业务结果。

前端无需增加额外 workaround；只要后端 `done` 恢复真正终态语义，现有 650ms polling + 5min terminal cache 就可以继续成立。

**回归测试建议：**

至少覆盖：

- scan 从 queued/running 到 done 过程中第一次观察到 done 时，已经包含 `rknn_toolkit2`；
- 第一次 done 之后 scan content/revision 不再变化；
- latest.json 只发布最终完整 snapshot；
- local RKNN ready；
- remote RKNN ready；
- RKNN missing；
- 前端读到 done 后停止 polling时结果必须完整；
- terminal cache 5 分钟内复用的必须是真正最终 snapshot。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-125 — Component Scan 可并发启动且 latest.json 无 generation fence；较老慢任务后完成会把“最新组件检测”倒退成旧快照

**级别：中～高**  
**模块：Component Scan / Concurrency / latest.json / Generation Fencing / Frontend Cache**

**现象：**

当前 POST /api/v40/system/components/scan 每次调用都会无条件创建新的 scan_id、写 queued JSON、创建 daemon thread 并启动。COMPONENT_SCAN_THREADS 只是保存线程引用，没有 active scan single-flight、generation、CAS 或 canonical current_scan_id。

_v40_scan_write(scan_id, data) 只要看到 status=done，就无条件覆盖 COMPONENT_SCAN_DIR/latest.json；它不比较 created_at、generation、scan_id 或“最后一次用户请求”。

因此 latest 的真实语义是“最后完成并写盘的 scan”，而不是“最后创建的 scan”。

**真实竞态：**

- Scan A 先创建，但远程资源/工具探测较慢；
- Scan B 后创建，却更快完成；
- B 先写 latest.json = B；
- A 随后完成，又无条件写 latest.json = A；
- GET /api/v40/system/components/latest 最终返回更早创建的 A。

组件扫描包含 Python module probe、subprocess version check、npu-smi、本地/远程 Deploy Resource 探测和 RKNN-Toolkit2 检测，耗时天然不保证按创建顺序完成。前端只禁用当前页面按钮，无法阻止第二浏览器、第二标签页、刷新后重复启动或直接 API 调用，所以并发真实可达。

**与 AUDIT-124 的区别：**

AUDIT-124 是单个 scan 内部 v40→v41 两阶段过早发布 done；AUDIT-125 是不同 scan 之间没有 generation fence。即使 124 修完、每个 scan 只写一次最终 done，125 仍然存在。

**影响：**

- “最新检测”可以倒退成旧环境快照；
- 新旧扫描结果在多管理端下互相覆盖；
- 前端 terminal cache TTL 5 分钟会继续放大旧 latest；
- 多个并发 scan 重复执行 SDK、subprocess 和远程探测，产生额外资源消耗；
- 用户刚重新检测完成，刷新后却可能看到较老结果。

**建议最小修复：**

不要新增第二 Component Scan runtime。start 时生成单调 generation/sequence，并记录 canonical latest_requested_generation。每个 scan 的历史 JSON可以正常完成，但只有 generation 仍等于当前 latest requested generation 的 scan 才能更新 latest.json。更早 generation 后完成只能作为历史记录，不能覆盖 latest。若产品只允许一个系统检测同时运行，也可以在 active scan 时复用现有 scan 或返回明确 active scan id，但不能只靠前端按钮 disabled。

同时与 AUDIT-124 一起保证：单个 scan 只有最终完整结果才能首次发布 status=done。

**回归测试建议：**

- A 先创建、B 后创建、B 先完成、A 后完成，latest 必须仍是 B；
- A/B 历史详情都可读取；
- 多标签页同时 POST 不让 latest 逆序；
- failed 旧 scan 不影响新 scan latest；
- RKNN 后处理完成后才允许该 generation 发布 done；
- 5 分钟前端 cache 只能缓存 generation 当前的最终 snapshot。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-126 — Component Scan 失败任务不会成为 latest truth；缓存过期或换客户端后会回退展示更早成功快照，失败原因也未进入前端持久化快照

**级别：中～高**  
**模块：Component Scan / latest.json / Failure Truth / Frontend Cache / Multi-client Consistency**

**现象：**

当前 Component Scan 每个 scan 都会写：

`component_scans/{scan_id}.json`

但：

`_v40_scan_write(scan_id, data)`

只有在：

`data.status == "done"`

时才覆盖：

`component_scans/latest.json`。

扫描异常时：

`_v40_run_component_scan()`

会把当前 scan 更新为：

- `status="failed"`
- `stage="检测失败"`
- `error=<异常>`
- `message=<异常>`

然后同样调用：

`_v40_scan_write(scan_id, scan)`

但因为状态不是 done，这次失败不会进入 `latest.json`。

因此后端所谓：

`GET /api/v40/system/components/latest`

实际不是“最后一次检测”，而是“最后一次成功完成的检测”。

**真实可达链：**

假设：

1. Scan A 成功：
   - `A.status=done`
   - `latest.json=A`
2. 环境随后发生变化，用户重新检测；
3. Scan B 在 Python / SDK / subprocess / 远程资源探测阶段抛异常：
   - `B.status=failed`
   - `B.json` 正确保存失败；
   - `latest.json` 仍保持 A；
4. 当前页面轮询 B 时暂时能拿到 B；
5. 但其它浏览器 / 其它管理端首次打开组件检测页时，只会请求：
   - `GET /api/v40/system/components/latest`
   - 因而直接看到旧的 A；
6. 当前浏览器本地 terminal cache 超过 5 分钟以后，再进入页面也会重新读取 latest，于是从 B 倒退回 A。

前端当前入口：

`renderComponentCheckV40()`

明确：

- terminal snapshot 5 分钟内直接复用；
- cache 不新鲜时只请求 `/api/v40/system/components/latest`；
- 没有“latest failed scan id / current scan id”恢复接口。

所以这个 stale truth 不是理论问题，而是页面恢复的真实唯一服务器来源。

**前端还会进一步丢失失败原因：**

`componentCacheShapeV40()`

只持久化：

- id
- status
- stage
- progress
- summary
- components
- capabilities
- atlas
- created_at
- updated_at

没有保存：

- `error`
- `message`

因此即使当前浏览器刚刚轮询到 failed：

- reload 后恢复出来的本地 snapshot 也只有 `status=failed`；
- 具体失败原因已被 cache shape 丢掉；
- `componentBodyHtml()` 本身也没有稳定渲染 scan-level error。

最终用户可能只看到一份不完整组件列表，随后在 cache 过期后又被旧成功 latest 覆盖。

**为什么与 AUDIT-124 / 125 不重复：**

- AUDIT-124：单个 scan 在 RKNN 后处理结束前过早发布 done；
- AUDIT-125：两个并发 scan 没有 generation fence，旧 scan 后完成可覆盖新 scan；
- AUDIT-126：**最新 scan 自己失败时，失败根本不会成为 latest truth，页面恢复会回退到更早成功记录。**

即使修完 124/125：

- 每个 scan 都只在最终时刻发布；
- generation 也严格单调；

只要 failed 不更新 current/latest，126 仍然存在。

**影响：**

- 用户刚执行的失败检测无法成为系统当前真相；
- 第二浏览器 / 第二管理端会立即看到旧成功结果；
- 同浏览器 cache 过期后也会回退到旧成功；
- 环境已损坏、远端资源异常或扫描 runtime 自身失败时，页面可能继续展示“之前满足”的能力快照；
- 运维人员可能据旧结果误判训练 / ONNX / RKNN / Ascend 等能力仍然可用；
- 故障排查时 scan-level error/message 不能稳定跨刷新保留；
- 与 AUDIT-125 并存时，“latest”的语义同时受到完成顺序和失败过滤两种漂移影响。

**现有测试缺口：**

当前：

`tests/browser/component-scan-performance.spec.mjs`

只覆盖：

- running progress；
- 页面离开后停止 polling；
- terminal `done` snapshot 复用。

`tests/frontend/component-scan-performance.test.mjs`

只覆盖：

- stable DOM；
- PollRegistry；
- 5 分钟 terminal cache；
- cache shape 不保存 secret。

没有覆盖：

`success A -> failed B -> reopen / new client / cache TTL expiry`

也没有断言：

- failed 必须成为最新 attempt；
- error/message 必须可恢复；
- 旧 success 不能覆盖最新 failed。

**建议最小修复：**

不要新增第二 Component Scan owner。

与 AUDIT-125 的 generation fence 一起收口 current/latest 语义：

1. 区分：
   - `latest_attempt` / canonical current truth；
   - 如确有产品需要，可另保留 `latest_success` 作为历史参考；
2. 当前 `/components/latest` 应返回“最新请求 generation 的最终状态”，包括：
   - done
   - failed；
3. 只有当前 latest requested generation 可以更新 canonical latest attempt；
4. failed 也必须持久化：
   - error
   - message
   - finished_at；
5. 前端安全 cache shape 应保留可展示的失败信息；
6. 页面为 failed 提供明确错误态，不应静默复用旧 success；
7. 不能通过“failed 时继续保留旧 latest”来维持绿色能力展示。

**回归测试建议：**

至少增加：

- A success，B failed → `GET /latest` 必须返回 B；
- 新浏览器首次打开必须看到 B failed，不得看到 A；
- B failed 后 5 分钟 cache 过期仍返回 B；
- failed cache round-trip 后 error/message 仍可展示；
- A 比 B 晚结束时，在 generation fence 下也不得覆盖 B；
- C 新成功后 latest 才允许从 B failed 前进到 C success。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-127 — v53 Bootstrap 的 force=true 可与现有预加载线程并发运行且共享全局 status/snapshot；旧线程晚到可把新 bootstrap 从 ready 倒退回 running/failed 并触发 503

**级别：高**  
**模块：Startup Bootstrap / Snapshot / Concurrency / Generation Fencing / First Paint**

**现象：**

当前 canonical 启动预加载 owner：

`_v53_start_bootstrap(preferred_project_id="", force=False)`

虽然持有：

`_V53_BOOTSTRAP_LOCK`

但该锁只保护“是否创建线程”这一瞬间。

当已有线程仍存活时：

`if _V53_BOOTSTRAP_THREAD and _V53_BOOTSTRAP_THREAD.is_alive() and not force: return`

也就是说：

**只要请求传 `force=true`，就会故意绕过已有线程 single-flight，再启动一条新的 bootstrap daemon thread。**

随后：

`_V53_BOOTSTRAP_THREAD = threading.Thread(...)`

还会把全局 thread handle 直接替换成新线程。

旧线程并没有停止，也没有 generation / cancellation / superseded 标记。

**两个线程共享同一套可写全局真相：**

所有 bootstrap worker 都直接修改：

- `_V53_BOOTSTRAP_STATUS`
- `_V53_BOOTSTRAP_SNAPSHOT`

而且没有：

- generation；
- request sequence；
- compare-and-swap；
- “仅最新请求可发布” fence。

`_v53_set_bootstrap()` 每次直接：

`_V53_BOOTSTRAP_STATUS.update(... status="running" / "ready" ...)`

worker 成功时又无条件：

- `_V53_BOOTSTRAP_SNAPSHOT = snap`
- `_V53_BOOTSTRAP_STATUS.update(status="ready", ...)`

worker 异常时无条件：

- `_V53_BOOTSTRAP_STATUS.update(status="failed", ...)`

**真实竞态：**

1. Startup Bootstrap A 正在执行；
2. API 调用：
   `POST /api/v53/bootstrap/start {"force": true}`
   启动 B；
3. B 更快完成：
   - 发布 Snapshot B；
   - status = ready；
4. A 此时仍在执行；
5. A 下一次调用 `_v53_set_bootstrap(...)`：
   - 直接把共享 status 从 ready 改回 running；
6. 如果 A 最后失败：
   - 又把 status 改成 failed；
7. 此后普通：
   `GET /api/v53/bootstrap/snapshot`
   看到全局 status 非 ready，可返回 503：
   `平台数据仍在启动预加载`。

也存在反向情况：

- 最新的 B 失败；
- 更旧的 A 随后成功；
- 系统最终又显示 ready，
- 从而隐藏最新一次 force bootstrap 的失败。

因此当前 truth 是：

“最后一个写共享 dict 的线程”

而不是：

“最新一次 bootstrap request 的 generation”。

**为什么前端函数本身不能兜底：**

前端已有：

`loadStartupSnapshot413(force=true)`

会调用：

`POST /api/v53/bootstrap/start`
`{force:true}`

随后：

`waitReady()`

轮询的也是同一个共享 `/bootstrap/status`。

虽然当前普通首次初始化使用 `force=false`，但 force 已是公开 API / canonical 前端能力；第二客户端、调试/恢复调用或后续页面复用都能触发。

服务端不能依赖“现在没有常用按钮调用 force”来保证 single-flight。

**与其它 generation 问题的区别：**

AUDIT-125 是 Component Scan 多 scan 之间 latest.json 缺 generation fence。

AUDIT-127 是平台首屏 Bootstrap 自身的全局：

- status；
- snapshot；
- first-paint readiness

缺 generation fence。

它直接影响整个平台初始化可用性，owner 和修复位置不同。

**影响：**

- 已 ready 的平台可被旧 bootstrap 线程重新打回 running；
- 旧线程异常可把新成功 bootstrap 改成 failed；
- `/bootstrap/snapshot` 可从正常响应退化成 503；
- 首屏可能重新进入“平台数据仍在启动预加载”；
- 新旧线程可互相覆盖 snapshot；
- force 恢复操作的成功/失败结果不具备稳定语义；
- 全局 `_V53_BOOTSTRAP_THREAD` 只指向新线程，旧线程成为不可追踪的并发 writer。

**现有测试缺口：**

当前 bootstrap tests 主要覆盖：

- 项目选择；
- label mutation 后 snapshot truth；
- algorithm revision overlay；
- platform version/build identity。

没有覆盖：

- A running → force B；
- B 先 ready，A 后 progress；
- B ready，A 后 failed；
- B failed，A 后 ready；
- latest generation only publication。

**建议最小修复：**

不要新增第二 Bootstrap owner。

在现有 v53 owner 内增加明确 generation / single-flight 语义：

1. 每次 start 分配单调 generation；
2. global 保存 current requested generation；
3. worker 的：
   - progress；
   - ready；
   - failed；
   - snapshot publish
   都必须携带 generation；
4. 只有仍等于 current generation 的 worker 能修改 canonical status/snapshot；
5. 被 supersede 的旧线程可以自然结束，但只能丢弃其 publication；
6. 如果产品根本不需要并发 force，可直接在已有线程 active 时复用当前 thread/status，而不是启动第二条；
7. `waitReady()` 应观察对应 generation，而不是任意全局 writer 的状态。

**回归测试建议：**

至少覆盖：

- A running，force B，B ready，A 后 progress → status 必须仍 ready(B)；
- B ready，A 后 failed → snapshot/status 仍为 B；
- B failed，A 后 ready → 最新 B 的 failed 不能被 A 隐藏；
- 旧 generation 不得覆盖 snapshot；
- 普通非 force 启动保持 single-flight；
- 多客户端并发 start 时 canonical generation 单调且可观察。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-128 — Resource Discovery 已复用 canonical active truth，但终态展示仍只识别 FAILED/CANCELLED；BLOCKED_BY_ENVIRONMENT 会停止轮询却继续显示“运行中”样式且隐藏失败原因

**级别：中**  
**模块：Training Resources / Resource Discovery / Durable Task Status Projection / Frontend Consistency**

**现象：**

`static/modules/resource-discovery.js`

已经正确复用：

- `canonicalTaskStatus()`
- `canonicalTaskPhase()`
- `isCanonicalTaskActive()`

因此 Resource Discovery 不再维护第二套 active-status owner。

但该页面的**终态 presentation**仍然重新手写了一套不完整判断：

`terminalMessage`

只在：

- `FAILED`
- `CANCELLED`

时生成。

状态 pill class 也只特殊识别：

- SUCCEEDED / PARTIAL_SUCCESS → ok
- FAILED → err
- CANCELLED → warn
- 其它全部 → run

因此合法 Durable terminal：

- `BLOCKED_BY_ENVIRONMENT`
- `BLOCKED_BY_HARDWARE`

会进入以下矛盾状态：

1. `isCanonicalTaskActive(task) == false`
2. PollRegistry 不再继续轮询；
3. 页面不展示 indeterminate progress；
4. 但状态 pill 仍使用 `run` 样式；
5. 文本直接显示技术枚举 `BLOCKED_BY_ENVIRONMENT`；
6. `terminalMessage == ''`；
7. 后端 `task.error` 和可操作失败说明不显示。

也就是：

**任务已经 terminal，前端视觉/文案却仍按“运行中/普通状态”投影。**

**BLOCKED_BY_ENVIRONMENT 是真实可达状态：**

统一 Scheduler 对 handler 异常明确分类：

- `HardwareUnavailableError -> BLOCKED_BY_HARDWARE`
- `EnvironmentError -> BLOCKED_BY_ENVIRONMENT`

Python 3 中 `EnvironmentError` 是 `OSError` 的兼容别名。

Resource Discovery 本身包含真实 I/O：

- 显式目录扫描；
- task-local SQLite manifest；
- cache publication；
- Python executable probe；
- artifact path / directory creation；
- 本地文件系统读取。

这些路径出现 OSError 时，Scheduler 可以合法把任务结束为：

`BLOCKED_BY_ENVIRONMENT`。

所以这不是只存在于通用枚举里的理论状态。

**真实调用链：**

Backend：

ResourceDiscoveryHandler
→ 文件系统 / 本地运行环境异常
→ `EnvironmentError/OSError`
→ Scheduler `_finish_error_or_cancel(... BLOCKED_BY_ENVIRONMENT ...)`
→ Durable task terminal。

Frontend：

`pollTask()`
→ 收到 BLOCKED_BY_ENVIRONMENT
→ `isCanonicalTaskActive(task) == false`
→ 停止下一次 PollRegistry timeout
→ `progressBody(task,...)`
→ 不进入 FAILED/CANCELLED failure branch
→ pill class 落入 `run`
→ 不显示 `discoveryFailureMessage(task)`。

**为什么与 AUDIT-088 / AUDIT-105 不重复：**

- AUDIT-088：UploadTaskCenter 自己维护过期 active/terminal 状态集合，导致部分终态被误判；
- AUDIT-105：Detection Batch 前端 terminal enum 漏 BLOCKED，影响批次生命周期；
- AUDIT-128：Resource Discovery **active 判断已经正确**，但独立的 terminal presentation 仍漂移，导致“停止轮询但显示为运行态且无错误原因”。

owner、页面和具体后果都不同。

**影响：**

- 训练资源检测已经因环境问题终止，但用户看不到明确失败态；
- 页面不再轮询，状态不会自行变化，用户容易误以为“还在处理”；
- 真正的 `task.error` 被隐藏，排查 Python 环境、路径权限、磁盘/文件系统问题更困难；
- 资源检测是训练创建前的重要诊断入口，错误状态会误导用户继续尝试训练；
- canonical Durable status truth 与页面视觉/文案 truth 不一致。

**现有测试缺口：**

`tests/frontend/resource-discovery-runtime-truth.test.mjs`

当前明确覆盖：

- failed；
- cancelled；
- permission error；
- canonical active truth；
- PollRegistry owner。

但没有覆盖：

- BLOCKED_BY_ENVIRONMENT；
- BLOCKED_BY_HARDWARE；
- blocked terminal pill class；
- blocked error copy。

测试名称虽然写“failed cancelled and permission states”，实际没有 blocked 合同。

**建议最小修复：**

不要新增新的状态集合。

Resource Discovery presentation 应直接基于 canonical terminal truth，或至少统一一个：

`isFailureTerminal(status)`

覆盖：

- FAILED
- BLOCKED_BY_ENVIRONMENT
- BLOCKED_BY_HARDWARE

并：

1. blocked 状态使用 error/warn terminal 样式，不得使用 run；
2. 显示 `task.error` 的安全可操作摘要；
3. 根据 blocked type 给出：
   - 环境不可用；
   - 硬件不可用；
   的中文说明；
4. PollRegistry 停止语义保持现状；
5. 不把 BLOCKED 状态重新归为 active。

**回归测试建议：**

至少增加：

- BLOCKED_BY_ENVIRONMENT → active=false、pill 非 run、展示环境失败说明；
- BLOCKED_BY_HARDWARE → active=false、pill 非 run、展示硬件失败说明；
- FAILED / CANCELLED 现有 copy 保持；
- SUCCEEDED / PARTIAL_SUCCESS 仍是 success；
- blocked terminal 后不得重新 arm polling。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-129 — AI Durable Task 只冻结 label code，Worker 执行时重新读取 live project label catalog；排队期间标签停用/治理可让已受理任务失败或改变 Prompt/class_id 语义

**级别：高**  
**模块：AI Annotation / Durable Request Freeze / Label Governance / Prompt Truth / Candidate Identity**

**现象：**

现代 v60 AI Annotation 在提交时已经正确冻结：

- model_config_snapshot；
- model_config_revision；
- prompt_template_snapshot；
- prompt_template_version_id。

但标签合同没有按同样方式冻结。

`annotation_runtime.prepare_request(..., runtime=False)`

在 Web admission 时会：

1. 读取当前项目 `meta.json`；
2. 根据当前 label catalog 验证用户显式提交的 label code；
3. 最终 request 只保存：
   `"labels": ["fire", ...]`

不会保存：

- class_id；
- display_name_zh；
- aliases；
- label catalog revision；
- schema snapshot / digest。

随后 Worker 真正执行时：

`prepare_request(..., runtime=True)`

**再次读取当前项目 `meta.json`**，重新执行：

`catalog = [item for item in label_catalog(project) if item["code"] in labels]`

再生成：

- `label_catalog`
- `label_ids`
- `label_aliases`

并把这份 execution-time catalog 用于 Prompt 和候选结果语义。

因此 Durable Task 的 label schema 不是 submit-time frozen truth，而是执行时 live truth。

**真实失败场景：**

1. 用户创建 AI task，显式选择：
   `fire`
2. admission 验证通过，task 已进入 Durable QUEUED；
3. 在 Worker claim 前，用户进行标签治理：
   - 停用 fire；
   - retirement；
   - 合并到其它 canonical label；
4. Worker 执行 `runtime=True`；
5. `label_catalog(project)` 只返回当前 active labels；
6. `fire` 已不存在于 available_codes；
7. 触发：
   `AI 标注标签必须显式使用当前标签库中的英文编码...`
8. 已经受理成功的 Durable AI task 直接 FAILED。

这不是用户提交无效，而是**提交成功之后的 live schema 变化回写到旧任务执行合同**。

**即使 code 仍存在，也可能改变执行语义：**

如果排队期间只修改：

- display_name_zh；
- aliases；
- label metadata/order；

Worker 会使用修改后的 catalog 构造：

- Prompt 的 `labels_json`；
- `label_aliases`；
- `label_ids/class_id`。

因此同一个 request.json 中虽然 `labels=["fire"]` 没变：

- 模型看到的中文/别名提示可以变；
- candidate label normalization 可以变；
- class_id 投影也依赖 execution-time catalog。

任务结果不再能仅凭 request artifact 重放。

**为什么是前后端/冻结合同 Bug：**

当前代码注释明确宣称：

`Freeze public task input at submit`

而 Model Config / Prompt Template 也确实执行了 snapshot。

但 label schema 是模型推理输入的一部分，却没有冻结。

这造成一个 Durable request 同时包含：

- frozen model；
- frozen prompt template；
- **live label catalog**。

冻结边界不一致。

**与已有问题的区别：**

- AUDIT-031：Label disable 可破坏 Training PREPARING 的 inherited training label contract；
- AUDIT-085：Annotation REMAP 与 Training Prepare 之间缺 label-governance fence；
- AUDIT-116：AI reference_image_ids 没进入模型视觉推理；
- AUDIT-117：前端参考图错误自动改变 requested labels。

AUDIT-129 是：

**AI Durable Task 已经合法受理后，Worker 又重新解析 live label schema。**

即使用户从不使用参考图、Training 完全不参与，这个问题仍成立。

**影响：**

- queued/waiting AI task 可因后续标签停用而失败；
- 同一 task retry 时间不同可能得到不同 Prompt；
- label aliases/display 修改可改变模型识别行为；
- candidate class_id/label normalization 依赖执行时 schema；
- 审计无法证明某个 AI 候选实际使用的是提交时哪一版标签字典；
- 大量 AI task 排队时，后台标签统一/治理会批量影响已受理任务；
- 与 10k/20k 标签治理后台任务并发时尤其难以解释和复现。

**现有测试缺口：**

`tests/unit/test_annotation_runtime.py`

已经覆盖：

- submit 冻结 Model Config snapshot/revision；
- live Model Config 修改后仍使用 frozen snapshot；
- snapshot tamper fail-closed；
- reference images 不替用户选 labels。

但没有覆盖：

- submit 后标签停用；
- submit 后 display/alias 修改；
- submit 后 label order/class_id 变化；
- retry 使用同一 frozen label schema。

**建议最小修复：**

不要新增第二 Label owner。

应在现有 annotation_runtime freeze owner 中，把任务所需 label schema 一并冻结，例如：

1. submit 时为 requested labels 冻结最小 catalog：
   - canonical code；
   - canonical class identity；
   - display_name_zh；
   - aliases；
2. 保存 `label_schema_snapshot` + digest/revision；
3. Worker runtime 优先且只使用 frozen snapshot 构造：
   - Prompt；
   - label_ids；
   - label_aliases；
4. live project schema 只用于 admission：
   - 新任务是否允许创建；
   - 不得回写旧 Durable task；
5. Candidate → Review → Commit 时仍必须映射到**当前 canonical AnnotationRepository label truth**：
   - 如果 frozen label 在 commit 时已被 retirement/merge，应该进入明确 review/remap/fail-closed 合同；
   - 不能静默把旧 class_id 直接写进正式 GT；
6. 不要把整个项目 label schema 全量复制到每个 task，只冻结 requested labels 的最小稳定 identity。

**回归测试建议：**

至少增加：

- submit fire → live fire disabled → queued task 仍按 frozen inference schema运行，或在 commit/review 阶段以明确治理合同处理，不能在 Worker 启动时随机失败；
- submit 后 display_name/aliases 修改 → runtime Prompt 仍等于 submit-time snapshot；
- submit 后 unrelated labels 增删不影响 task；
- retry 仍复用同一 label schema digest；
- candidate commit 时 retired/merged label fail-closed 或显式 remap，不能绕过 canonical label governance；
- snapshot tamper 必须拒绝。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-130 — 当前 Quality Center Deployment Test 与 RKNN 实机验证对 UploadFile 使用无上限 await file.read()；超大伪图片可一次性进入 Web 进程内存并导致 OOM/服务退出

**级别：高**  
**模块：Quality Center / Deployment Test / RKNN Hardware Verification / Upload Safety / Web Stability**

**现象：**

当前两个仍由正式前端直接调用的图片验证入口：

- `POST /api/v61/projects/{project_id}/deployment-tests`
- `POST /api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests`

都采用：

`input_path.write_bytes(await file.read())`

也就是先把整个 multipart 文件一次性读成 Python bytes，再写磁盘。

当前应用没有：

- 全局 request body size limit；
- 这两个 endpoint 自己的 max image bytes；
- 基于 `UploadFile.size` 的 admission guard；
- streaming copy + bounded byte counter。

前端 file input 也只有：

`accept="image/*"`

没有大小限制。

因此文件扩展名/浏览器 MIME 不能形成安全边界。

**真实生产调用链：**

Quality Center：

`runDeploymentTest(...)`
→ FormData append(file)
→ `POST /api/v61/.../deployment-tests`
→ FastAPI UploadFile
→ `await file.read()`
→ 整个文件进入 Web 进程内存
→ `Path.write_bytes(...)`。

RKNN 实机验收：

`submitRknnHardwareVerify()`
→ FormData append(file)
→ `POST /api/v39/.../hardware-tests`
→ `await file.read()`
→ 整体内存化
→ 写入 predictions/task directory。

两个入口都在当前 `static/app.js` 中有真实用户动作，不是已退役 Legacy API。

**为什么是稳定性 Bug：**

FastAPI `UploadFile` 的价值之一是底层可以 spool 到临时文件，避免大 body 全量常驻内存。

但调用：

`await file.read()`

会重新把整个内容读入 bytes。

例如一个被命名成：

`huge.jpg`

的数百 MB / 数 GB 文件，即使最终根本不是合法图片，也会在任何真正的图像解析/推理校验之前先占用同等量级的 Python heap。

并发两个或多个请求会线性放大。

**额外问题：**

v61 Deployment Test 还在文件已经整体写入：

`predictions/{task_id}/input.*`

之后才校验：

- detection_batch_id；
- detection_item_index；
- detection_item_total；
- detection_side。

因此批次参数非法时：

- API 返回 400；
- 但 prediction_dir/input file 已经创建；
- 没有 task row 可供后续 retention owner 清理。

这会形成 pre-task orphan artifact。

该点不是 AUDIT-130 成立的前提，但会放大超大文件磁盘占用。

**影响：**

- 单个误选超大文件可显著抬高 Web RSS；
- 多个并发请求可触发 OOM killer / Python 进程退出；
- Web 与 Worker 若共享机器，会拖累训练任务控制面；
- 无效文件也会先消耗全部上传内存和磁盘 I/O；
- v61 参数错误可留下没有 Durable task identity 的 orphan prediction file；
- Quality Center 批量测试场景会自然提高并发/连续调用概率。

**与已有问题的区别：**

- AUDIT-036：Detection Batch 结果索引/扫描复杂度；
- AUDIT-065：已经创建的 Durable Task 缺 terminal artifact retention/GC；
- AUDIT-107/121/122：Quality Center 任务取消、等待、导航 lifecycle。

AUDIT-130 是**任务创建前上传体的内存 admission / streaming 问题**。

即使实现 terminal GC，本问题仍会在 TaskRecord 创建以前发生。

**现有测试缺口：**

当前 Deployment Test / RKNN verification 测试主要覆盖：

- 模型/板卡合同；
- Durable task 创建；
- inference/receipt；
- artifact identity；
- version fence。

没有覆盖：

- 100MB/1GB 伪图片；
- request memory bound；
- chunked streaming；
- 上传超过上限时 413；
- 参数校验失败后不留 prediction orphan。

**建议最小修复：**

不要新增新的上传 owner。

两个当前入口统一复用一个 bounded UploadFile streaming helper：

1. 在写磁盘时按固定 chunk 读取；
2. 累计 bytes，超过明确 image upload limit：
   - 立即停止；
   - 删除 partial file；
   - 返回 413；
3. 如果 `UploadFile.size` 可用，先做 early reject，但不能只信该字段；
4. 参数/identity 校验尽量前移到落盘前；
5. 落盘成功后再做真实图片 decode/格式校验；
6. TaskRecord 创建失败时清理该 task pre-stage directory；
7. 前端同步展示允许的最大图片大小，只做 UX 提示，后端仍是最终边界。

旧 Legacy import API 的全量 read 可在退役/清理阶段另行处理，不应阻塞当前两个正式入口先修。

**回归测试建议：**

至少覆盖：

- 超限文件返回 413，Web 进程不全量 hydrate body；
- streaming helper 的峰值读取 chunk bounded；
- partial upload 自动删除；
- 合法小图 v61 正常创建 Durable task；
- 合法小图 v39 正常创建硬件验证 task；
- detection batch 参数非法时不创建 prediction input orphan；
- 多请求并发时每请求内存占用不随文件总大小线性增长。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-131 — Video Task 上传虽按 1MiB 流式写盘，但没有文件大小/磁盘配额边界，且 TaskRecord 在完整上传后才创建；断连/写盘失败会留下无 owner 的 partial artifact

**级别：高**  
**模块：Video Frames / Durable Task Admission / Upload Lifecycle / Disk Safety / Artifact Ownership**

**现象：**

当前正式 Video Task 创建入口：

`POST /api/v33/projects/{project_id}/video-tasks`

已经避免了 `await video.read()` 全量内存化，采用：

`while True -> await video.read(1024 * 1024) -> fp.write(chunk)`

所以它没有 AUDIT-130 的大文件 OOM 问题。

但这里仍缺两个关键 lifecycle 边界：

1. **没有任何最大视频大小 / 项目配额 / 剩余磁盘 admission；**
2. **TaskRecord 在整个视频完全写完之后才创建。**

真实顺序是：

- 生成 task_id；
- 直接建立：
  `task_runtime/artifacts/<task_id>/inputs/<filename>`
- 流式写完整视频；
- 检查非空；
- 写 `payload.json`；
- 最后才：
  `TaskRepository.create(TaskRecord.new(...))`

因此上传阶段产生的文件在 Durable Task truth 建立以前就已经存在。

**真实失败场景：**

场景 A — 客户端断开：

- 上传已写入数 GB；
- `await video.read(...)` 抛异常/请求取消；
- 当前代码没有 try/finally cleanup；
- endpoint 没有 TaskRecord；
- partial video 留在 task artifact root。

场景 B — 磁盘写满 / OSError：

- `fp.write(chunk)` 中途失败；
- partial file 已经存在；
- TaskRepository 尚未有对应 task；
- 没有 terminal task 可供 retention/GC owner处理。

场景 C — 合法但超大视频：

- 当前没有 byte limit；
- 客户端可持续写到磁盘耗尽；
- 即使最终任务成功创建，控制面磁盘已可能被单个任务占满。

**为什么 AUDIT-065 不能覆盖：**

AUDIT-065 是：

**已经存在 Durable Task 的 terminal artifact 缺统一 retention/GC。**

AUDIT-131 发生在：

**TaskRecord 创建以前。**

partial artifact 没有数据库 task identity，因此基于 terminal status 的 GC 根本看不到它。

ArtifactStore 当前只有：

`delete_task(task_id)`

这种“已知 task_id 删除”能力，没有 orphan artifact root reconciliation。

**影响：**

- 断线上传可永久残留大文件；
- 重复断连会累积无 TaskRecord 的孤儿目录；
- 恶意或误选超大视频可耗尽控制面磁盘；
- 磁盘耗尽会影响：
  - TaskRepository SQLite；
  - Annotation/Material 数据；
  - Training artifacts；
  - Web/Worker 日志；
- 用户 UI 中没有对应任务记录，无法主动删除这些 partial files；
- 运维只能人工查文件系统。

**现有测试缺口：**

`tests/api/test_video_tasks.py`

当前只覆盖：

- 小视频成功流式落盘并创建 QUEUED Durable task；
- list/cancel 使用持久化 repository。

没有覆盖：

- 上传超过大小限制；
- client disconnect；
- write OSError / ENOSPC；
- TaskRepository.create 失败后的 upload artifact rollback；
- orphan task artifact reconciliation。

**建议最小修复：**

不要新增第二上传 owner。

在现有 v33 create owner 内：

1. 定义明确的最大视频上传 bytes，或项目级可配置 quota；
2. chunk 写盘时累计字节数，超过上限立即：
   - 停止读取；
   - 删除当前 task artifact root；
   - 返回 413；
3. 上传阶段使用 try/finally / rollback：
   - 只要 TaskRecord 尚未成功 publish，异常就删除 pre-task artifact；
4. TaskRepository.create 失败时同样 rollback；
5. 如需支持很大视频，应采用显式 multipart/resumable upload owner，而不是无限单请求流；
6. 增加统一 orphan artifact reconciliation：
   - artifact root 存在；
   - TaskRepository 无 task_id；
   - 超过安全 grace period；
   - 才允许 GC；
   - 不得误删仍在进行的 staged upload。

**回归测试建议：**

至少覆盖：

- 超限视频返回 413 且 artifact root 不存在；
- 模拟 upload read exception 后 partial file 被清理；
- 模拟 fp.write ENOSPC 后 partial file 被清理；
- 模拟 TaskRepository.create 失败后 payload/video 均 rollback；
- 合法小视频仍按 1MiB bounded streaming 创建任务；
- orphan GC 只清超过 grace period 且数据库无 task row 的目录；
- 并发上传不互相误删。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-132 — 普通图片批量上传在 async endpoint 中使用 threading.local 作为 batch owner；并发请求可互相覆盖 batch context，导致串批、提前 commit 或跨请求 rollback 删除对方素材

**级别：严重 / 高**  
**模块：Plain Image Upload / Batch Atomicity / Async Concurrency / MaterialRepository / Storage Rollback**

**现象：**

普通图片上传：

`POST /api/projects/{project_id}/images`

是：

`async def upload_images(...)`

但它用：

`_IMAGE_BATCH_CTX = threading.local()`

保存当前批次。

请求进入后：

`_v50_begin_image_batch(project_id)`

直接执行：

`_IMAGE_BATCH_CTX.batch = {...}`

后续所有：

- `_v50_active_image_batch()`
- `_v50_storage_manager()`
- `_v50_annotation_repository()`
- `_v50_queue_image_patch()`
- `_v50_end_image_batch()`

都从这个 thread-local 读取当前 batch。

**问题在于：threading.local 只能隔离 OS thread，不能隔离同一 event-loop thread 上的 async coroutine。**

而 `upload_images()` 在 batch 已建立以后，明确执行：

`await file.seek(0)`

所以请求 A 可以在 batch 生命周期中让出事件循环，请求 B 随后在同一线程执行并覆盖：

`_IMAGE_BATCH_CTX.batch`。

**真实竞态示例：**

同一项目并发 Upload A / Upload B：

1. A：
   `_v50_begin_image_batch()`
   → thread-local = batch A
2. A：
   `await file.seek(0)`
   → coroutine suspend
3. B：
   `_v50_begin_image_batch()`
   → **同一 thread-local 被改成 batch B**
4. B 也在 seek / I/O 处让出；
5. A 恢复；
6. A 调 `add_image_record()`；
7. `_v50_active_image_batch(project_id)` 看到的是 **batch B**；
8. A 的 material/annotation deferred truth 被写入 B 的 batch buffer。

之后任何一边调用：

`_v50_end_image_batch(save=True/False)`

都会操作“当时 thread-local 指向的那一个 batch”，而不是调用方自己的 request batch。

**可能后果：**

- A 的记录被 B commit；
- A 提前把 B 的 buffered records 一起 commit；
- B 恢复后发现 batch 已被 A 清成 None，于是后续图片直接绕过 batch，单条写入；
- A/B response 的 uploaded 列表与真正 commit owner 分离；
- upload_request receipt 与真实 material commit 不再同事务语义；
- 更严重的是异常 rollback：
  `_v50_end_image_batch(save=False)`
  会调用：
  `_v50_cleanup_buffered_image_batch_files(... records)`
  并删除 batch 中的 source objects / annotations；
- 如果 batch 里混入另一个请求的图片，**一个请求失败可能删除另一个请求已经上传的素材文件。**

这是数据正确性问题，不只是性能问题。

**为什么项目锁没有保护普通上传：**

v19 ZIP import 使用：

`_v50_project_import_lock(project_id)`

并在同步 Worker 中调用 batch owner。

Online Feedback confirm 是同步 endpoint，batch 内没有 async yield。

但普通：

`upload_images()`

没有包在 project import lock 内，且自身是 async。

因此不能用“其它调用方安全”来证明该入口安全。

**为什么前端 64 files/chunk 不能避免：**

前端把大批上传拆成 64-file chunk 只限制单请求规模。

用户：

- 多浏览器标签页；
- 多客户端；
- 网络重试；
- 前端并发 chunk；
- API 直接调用

都可以产生并发请求。

而且较大的 UploadFile 更可能被 Starlette spool 到磁盘，`await file.seek()` 需要 threadpool I/O，更容易真实让出 event loop。

**现有 rollback 本身是正确的，但 owner 隔离错误：**

`_v50_end_image_batch(save=False)`

会正确尝试删除：

- Storage source object；
- AnnotationRepository row；
- annotation file。

问题不是 cleanup 缺失，而是：

**cleanup 可能拿到别的请求的 batch。**

这比简单 orphan 更危险。

**现有测试缺口：**

当前上传测试覆盖：

- batch SQLite 性能；
- upload_request_id 幂等 replay；
- manifest reuse conflict；
- partial failure；
- Storage upload；
- 前端 64-file chunk。

没有覆盖：

- 两个 async `/images` 请求交错；
- coroutine/task-local isolation；
- A failure 不得 rollback B；
- A/B receipt 必须只包含自己的 image ids。

**建议最小修复：**

不要新增第二 Material owner。

应把 batch context 从：

`threading.local()`

改为真正的 request/task-local owner，例如：

- `contextvars.ContextVar`，且使用 token set/reset；
- 或更直接：把 explicit batch object 作为参数沿调用链传递。

关键合同：

1. 每个请求拥有唯一 batch identity；
2. async await 前后 batch identity 不变；
3. batch end 只能 commit/rollback 自己的 records；
4. ContextVar 必须在 finally 中按 token reset，防止 context 泄漏；
5. v19 同步 Worker / Online Feedback 继续复用同一个 canonical batch abstraction；
6. 不允许新增平行 MaterialRepository 写 owner。

**回归测试建议：**

至少增加确定性交错测试：

- A begin → suspend；
- B begin → suspend；
- A add/commit；
- B add/commit；
- 最终 A/B 各自只拥有自己的 image；
- A rollback + B success → B source object/material/annotation 全部仍存在；
- B rollback + A success 同理；
- 两个 upload_request_id receipt 不串 image ids；
- Local storage 与 remote storage provider 都保持 isolation；
- 64-file chunk 并发时无串批。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-133 — 普通图片 upload_request 收据先持久化 PROCESSING，但没有 lease/heartbeat/过期恢复；Web 崩溃可让同一请求 ID 永久不可重试，并产生“素材已提交但收据仍处理中”分裂真相

**级别：高**  
**模块：Plain Image Upload / Idempotency Receipt / Crash Consistency / Recovery**

**现象：**

普通图片上传支持 upload_request_id 用于网络异常后的幂等恢复。

当前顺序是：

1. begin_upload_request()；
2. 立即把 JSON receipt 持久化为 upload_request_status = PROCESSING；
3. 才开始图片解析、Storage upload、batch commit；
4. 所有素材 commit 成功后 complete_upload_request() -> SUCCEEDED；
5. 普通 Python Exception 时 fail_upload_request() -> FAILED。

但 PROCESSING receipt 没有 owner/process identity、lease_expires_at、heartbeat、generation、attempt、stale timeout、startup reconciliation 或 takeover/resume API。

所以 PROCESSING 不是 durable running truth，只是一枚不会自动恢复的静态 JSON 状态。

**真实 crash 窗口：**

场景 A：receipt 已创建、material commit 前进程退出。receipt 会永久停留 PROCESSING；部分 source objects 可能已上传，而请求内 rollback 已没有机会执行。

场景 B 更严重：当前成功顺序明确是 _v50_end_image_batch(save=True) 完成 MaterialRepository / AnnotationRepository commit，之后才 complete_upload_request(... SUCCEEDED)。如果进程恰好在两者之间退出，素材已经正式存在，但 receipt 仍然 PROCESSING。

同一 request_id 重试时，upload_images() 对既有 PROCESSING 只返回 UPLOAD_REQUEST_IN_PROGRESS / 409，不会 replay 已提交素材，也不会接管旧 attempt。

**前端无法恢复：**

recoverMaterialUploadRequest() 只会轮询 GET /api/v55/projects/{project_id}/upload-batches/{request_id}。状态如果一直 PROCESSING，达到 maxPolls 后只会提示“服务器仍在处理当前批次，结果尚未确认；请勿重复选择上传”。

但服务器此时可能已经没有任何 request coroutine、Worker 或 lease 在处理它。

v55 当前只有 receipt GET 和后续 decisions，没有 stale PROCESSING recovery owner。

**用户重新选择上传还会放大重复风险：**

正常 UI 每次新的上传动作都会生成新的随机 request seed。如果旧 crash 已发生在 material commit 之后，用户重新选择相同图片会使用新 request_id 并再次创建素材记录，而旧 receipt 仍永久 PROCESSING。

因此当前幂等机制在最需要它的进程级故障场景失效。

**与 AUDIT-131 / 132 的区别：**

- AUDIT-131：Video pre-task upload 无大小边界且异常会留下无 task orphan；
- AUDIT-132：普通图片 async 请求共享 threading.local batch，导致并发串批；
- AUDIT-133：即使单请求、batch isolation 完全正确，只要 Web 在 receipt PROCESSING 生命周期中退出，幂等恢复仍永久卡死。

**影响：**

- 上传进度永久显示服务器处理中；
- 相同 request_id 无法重试；
- 用户无法确认服务器到底有没有完成入库；
- crash 前已上传的对象可能成为 orphan；
- crash 后已正式 commit 的 materials 可能被再次上传成重复素材；
- 清洗决策 API 对 PROCESSING 明确返回 409，上传→清洗链无法继续；
- 服务重启本应是可恢复场景，但当前 receipt 没有恢复 owner。

**现有测试缺口：**

现有测试覆盖成功 replay、manifest 冲突、partial per-file failure、receipt SUCCEEDED 查询，但没有覆盖 begin PROCESSING 后进程死亡、material commit 后 receipt complete 前故障、stale PROCESSING startup recovery 或 takeover/reconciliation。

**建议最小修复：**

不要为普通上传另造第二套 Durable Task。继续使用 UploadBatchStore，但 PROCESSING 必须具备可恢复状态机：

1. receipt 增加 attempt/generation、owner_instance_id、heartbeat_at/lease_expires_at；
2. 上传过程中按 bounded cadence heartbeat；
3. GET/retry/startup 发现 PROCESSING lease 过期时执行 reconciliation；
4. materials 已全部 commit 时，根据 request-owned evidence 完成 SUCCEEDED；
5. 尚未 commit 时清理该 attempt 的 staged objects，再允许新 attempt；
6. material commit 与 receipt completion 之间增加可恢复 commit marker/journal；
7. takeover 必须 generation fenced，不能两个 request 同时继续；
8. 前端 recovery 观察 recovered/taken_over 状态，而不是无限轮询静态 PROCESSING。

如果暂时不实现 lease，至少也必须让 PROCESSING 带 started_at，并在确认无活跃 owner 后提供 stale fail/retry/reconcile；不能永久 409。

**回归测试建议：**

- receipt PROCESSING → crash before material commit → restart 可清理并重试；
- material commit 成功 → crash before receipt SUCCEEDED → restart 返回原 image ids，不重复创建；
- stale PROCESSING 不得永久 409；
- live PROCESSING 仍拒绝第二 owner；
- takeover generation 防并发；
- Local / OSS storage 均不留下不可追踪 staged object。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-134 — 普通图片上传没有 Storage Source revision/fence；上传中 PATCH/DELETE 存储源后，缓存 provider 可继续写旧位置，但最终 Material 只引用新/已删除 source_id，导致刚上传素材立即不可读

**级别：高**  
**模块：Plain Image Upload / Storage Source Lifecycle / Material Identity / Concurrency**

**现象：**

普通图片 upload_images() 在一个 batch 内复用 _v50_storage_manager(project_id)。StorageManager 又会在首次 provider_for(source_id) 后把真实 provider 缓存在 self._providers。

也就是说一旦本批次开始向某个 Local/OSS/S3 source 写入，后续文件可以继续使用创建时的旧 root / bucket / endpoint / credentials。

与此同时，PATCH /api/v61/storage-sources/{source_id} 与 DELETE /api/v61/storage-sources/{source_id} 没有和普通 /images 上传建立任何 source revision/fence。

普通上传也不是 Durable Task，现有针对 Storage Import/Rescan 的 active dependency 保护看不到它。

**真实竞态 A — PATCH：**

1. Upload A 选择 source S，root/bucket = OLD；
2. batch 内 StorageManager 创建并缓存 OLD provider；
3. 管理员把同一个 source_id S PATCH 到 NEW root/bucket/endpoint；
4. Upload A 仍可通过 cached provider 继续把对象写到 OLD；
5. add_image_record 最终只保存 storage_source_id = S 与 object_key；
6. 后续读取素材时新 StorageManager 按当前 S 配置解析到 NEW；
7. NEW 下没有该 object_key，于是刚成功上传的素材立即 SOURCE_OBJECT_NOT_FOUND / unavailable。

更危险的是，如果 NEW 下碰巧存在同 object_key，完整性校验会因 SHA 不一致 fail-closed；也就是说 identity 已经发生漂移。

**真实竞态 B — DELETE：**

如果 source 在 provider 已缓存后被 DELETE：

- 当前上传仍可能继续向旧 provider 写；
- batch commit 不会再次确认 source_id 仍存在；
- Material row 仍可保存 storage_source_id=S；
- 后续任何 materialize/open_reader 都无法再 resolve S。

因此 API 可能返回 uploaded_count 成功，但素材马上不可预览、不可标注、不可训练。

**rollback 也会受影响：**

_v50_cleanup_buffered_image_batch_files() rollback 时不是复用原 batch 的 cached provider，而是重新调用 storage_manager(project_id)。

如果 source 已 PATCH，它会按 NEW provider 删除相同 object_key，而真正上传对象在 OLD；如果 source 已 DELETE，cleanup 直接找不到 provider。

结果可能同时出现：

- OLD 位置留下 orphan object；
- cleanup 报错；
- 或错误尝试操作 NEW 位置同 key 对象。

**为什么与 AUDIT-016 / AUDIT-044 不重复：**

- AUDIT-016：Storage Source DELETE 可破坏活动 Storage Import/Rescan；
- AUDIT-044：Storage Source PATCH 可破坏活动 Import/Rescan dependency；
- AUDIT-134：普通图片 /images 上传是 request-scoped 非 Durable 流程，provider 被 request 内缓存，现有 Durable reference 检查无法观察它。

即使修完 016/044，只保护 Material Import/Rescan task，普通上传 race 仍然存在。

**影响：**

- 上传接口返回成功但素材立即不可读；
- Local root / OSS bucket 切换时最容易出现；
- 批量上传中一部分文件可能写 OLD，一部分在配置变化后失败，形成难以解释的混合结果；
- rollback 可能无法清理旧 provider 对象；
- MaterialRepository 中 source identity 不再能唯一重建真实内容位置；
- 用户后续在标注、清洗、训练阶段才发现源文件不可用。

**现有测试缺口：**

tests/api/test_storage_upload.py 只覆盖选定 storage source 正常上传、disabled source、scan；tests/api/test_upload_batch_performance_truth.py 只覆盖 batch/receipt 性能和幂等。没有覆盖上传进行中 PATCH/DELETE source。

**建议最小修复：**

不要新增第二 Storage owner。应让普通上传也参与 canonical Storage Source lifecycle fence：

1. 上传 admission 时冻结 source_id + immutable source revision/config digest；
2. 从第一字节写入到 Material batch commit 期间，对该 revision 持有 reference/lease；
3. PATCH/DELETE 遇到 active upload reference 时明确 409，或创建新 revision 而不是原地改写；
4. batch commit 前再次确认 source revision 未变化；
5. rollback 必须使用本 attempt 冻结的 provider/revision 删除自己写入的对象，不能重新按 live source_id 解析；
6. receipt/recovery 也应记录 source revision，和 AUDIT-133 的 crash recovery 共用同一 frozen evidence。

**回归测试建议：**

- Upload A 使用 OLD source，处理中 PATCH 到 NEW 必须被 fence 或 A 明确失败且 OLD 对象清理；
- 上传中 DELETE source 必须 409，不能生成 dangling Material；
- rollback 始终删除原 frozen provider 下对象；
- source revision 改变后不得把 OLD object 记录成 NEW source truth；
- Local / OSS / S3 都覆盖；
- 与并发上传 AUDIT-132 修复组合测试。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-135 — “测试发布”仍使用同步 /api/v12/predict 作为第二推理 Runtime；直接在 Web 请求内执行 subprocess 并绕过 Durable DEPLOYMENT_TEST / Scheduler / 取消与资源治理

**级别：高**  
**模块：Test Publish / Model Test / Inference Runtime / DEPLOYMENT_TEST / Scheduler / Resource Governance**

**现象：**

当前平台已经有一条 canonical 模型检测主链：

`质量中心 / 检测台`
→ Durable `DEPLOYMENT_TEST`
→ TaskRepository
→ Scheduler / Worker / Agent
→ 可轮询、可取消、可恢复、可记录历史结果。

当前最终前端的 `window.benchPredictOne` 也已经覆盖旧实现，走持久化 Deployment Test。

但“测试发布”页面仍保留另一条完全独立的同步推理 Runtime。

当前菜单/页面仍真实可达“测试发布”，v63 最终：

`renderTest = window.renderTest = renderTestCanonical63`

仍调用：

`window.renderTestCore30()`

而 `renderTestCore30()` 明确渲染：

`模型测试`

以及：

`<button ... onclick="predict()">开始测试</button>`

v63 最终 `window.predict` 又继续调用：

`window.predictCore30()`

最终请求：

`POST /api/v12/projects/{project_id}/predict`

因此这不是零引用 Legacy helper，而是当前 UI 仍能直接进入的第二推理 owner。

**后端真实调用链：**

`v12_predict_image()`

先直接：

`in_path.write_bytes(await file.read())`

随后：

`python_path = resolve_inference_python(...)`

→ `run_predict_by_env(...)`

而 `run_predict_by_env()` 直接在 Web 请求生命周期里执行：

`subprocess.run(..., timeout=600)`

也就是说，一个“开始测试”HTTP 请求可以由 Web 进程同步持有真实模型推理子进程最长约 10 分钟。

整个路径没有创建：

- TaskRecord；
- DEPLOYMENT_TEST；
- Scheduler admission；
- resource reservation；
- Agent assignment；
- queue position；
- WAITING_RESOURCE truth；
- cancellation lifecycle；
- execution generation / lease；
- Durable result/recovery history。

**为什么是重复 Runtime / 生命周期旁路：**

当前同一种“模型检测”行为实际有两套执行合同：

1. 质量中心 / 检测台：
   - canonical Durable DEPLOYMENT_TEST；
   - 受 Scheduler、资源、TaskRepository、Worker lifecycle 管理。

2. 测试发布 / 模型测试：
   - Web request 直接 subprocess；
   - 不进入任何 Durable execution owner。

所以即使 Scheduler 已经认为 GPU 被训练或 Deployment Test 占用，“测试发布”仍可以直接启动另一个真实推理进程。

这与当前“一个 domain 一个 canonical runtime owner”的收口目标直接冲突。

**额外风险：**

该同步接口还使用：

`await file.read()`

无上限把测试图片一次性读入 Web 进程内存。

这与 AUDIT-130 的上传内存问题表现相似，但不是同一个问题：

- AUDIT-130：canonical Quality Center Deployment Test / RKNN 板端验证入口自身缺少上传大小上限；
- AUDIT-135：整个“测试发布”仍保留第二套同步推理 owner，绕过 Durable execution；无界 read 只是这条旁路附带的额外风险。

**影响：**

- 同一个模型在“检测台”和“测试发布”拥有完全不同的排队/资源/失败/恢复语义；
- 多个用户可通过“测试发布”同时直接启动推理 subprocess，绕过 GPU reservation；
- 训练 / 转换 / Deployment Test 与同步 predict 可真实争抢 CPU/GPU/显存；
- 页面关闭、浏览器断线、代理超时都没有 Durable task 可供恢复；
- 用户无法停止已经进入 subprocess 的测试；
- Web worker/request 可被最长 600 秒真实推理占用；
- 没有 canonical task history，故障后很难审计“任务到底执行到哪一步”；
- 正式算法版本的 online feedback evidence 也可以由这条不受 Durable runtime 管理的推理路径产生；
- 大图片还可通过无界 `await file.read()` 放大 Web 进程内存压力。

**为什么现有测试没有拦住：**

当前 Deployment Test 相关回归主要保护：

- v61 Durable task create；
- Worker runtime；
- detection batch；
- Quality Center polling/result。

但“测试发布”保留的是较早的 `predictCore30` 兼容层。

后续 v63 为了线上反馈，又显式把：

`window.predict`

绑定回：

`predictCore30`

因此质量中心主链已经 Durable 化，并不代表“测试发布”也已完成迁移。

缺少一个跨页面合同测试：

“所有当前可达的真实模型推理入口都必须创建 canonical DEPLOYMENT_TEST，不允许直接 subprocess。”

**建议最小修复：**

不要新增第三套推理 owner，也不要重新设计 Deployment Test。

直接让“测试发布”的单模型测试复用当前 canonical Deployment Test runtime：

1. “开始测试”调用统一的 Deployment Test create；
2. 使用现有 PollRegistry / task detail / result renderer 等待结果；
3. 单模型和检测台共享同一 Scheduler / Resource / cancellation contract；
4. online feedback evidence 从 canonical Deployment Test result/evidence 生成；
5. 对 `/api/v12/projects/{project_id}/predict`：
   - 先证明外部 zero-reference；
   - 若无外部兼容需求，退役/410；
   - 若必须保留兼容，则只能作为“创建 Durable Deployment Test”的 adapter，不能再直接执行 subprocess；
6. 上传大小/流式处理与 AUDIT-130 一起收口，不能把无界 read 带进新入口。

**回归测试建议：**

至少增加：

- “测试发布 → 开始测试”必须创建 Durable DEPLOYMENT_TEST；
- 当前 UI 不再直接请求 `/api/v12/.../predict` 执行推理；
- 测试发布与质量中心并发时共享同一个资源/Scheduler 真相；
- GPU 已被占用时，两边都进入同一 WAITING_RESOURCE / queue 语义；
- 单模型测试可取消；
- 刷新/重连后可恢复同一个 task；
- Web/Worker 重启后 canonical result 仍可恢复；
- 正式算法版本测试仍能生成合法 online feedback evidence；
- 兼容 predict endpoint 不得直接 spawn subprocess；
- 大图片遵守明确 size limit / bounded streaming。

**进一步确认的事件循环阻塞证据：**

该接口本身声明为：

`async def v12_predict_image(...)`

但在 coroutine 内直接同步调用：

`run_predict_by_env(...)`
→ `subprocess.run(..., timeout=600)`

中间没有：

- `run_in_threadpool`；
- `asyncio.to_thread`；
- executor；
- Durable Worker handoff。

因此问题不只是“一个请求占住一个普通工作线程”。在常见 Uvicorn/ASGI 运行方式下，这段同步 subprocess 会阻塞承载该 async route 的 event loop，直到推理结束、失败或 600 秒 timeout。

这意味着一次较慢的“测试发布 → 开始测试”就可能同时拖慢同一 worker 上的：

- task polling；
- 登录/session API；
- 素材/标注读取；
- 训练任务刷新；
- 其它 async 上传/网络请求。

所以 AUDIT-135 修复时不能只把 `subprocess.run` 换成 threadpool 就算收口。threadpool 只能缓解 event-loop starvation，仍然保留第二套非 Durable 推理 owner。正确方向仍是统一迁移到 canonical `DEPLOYMENT_TEST`。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-136 — /api/v16/inference_envs 每次 GET 都重新启动 Python 子进程 import Ultralytics/ppdet/paddlex；测试发布/检测台/质量中心页面刷新会反复触发重型 Runtime 探测

**级别：中～高**  
**模块：Inference Environment / Test Publish / Quality Center / Detection Bench / Runtime Discovery / Performance**

**现象：**

当前：

`GET /api/v16/inference_envs`

直接调用：

`inference_env_items()`

而其默认参数是：

`probe_modules=True`

每次请求都会重新执行真实模块探测。

Ultralytics 路径：

`_module_available(sys.executable, "ultralytics")`

内部直接：

`subprocess.run([python_path, "-c", "import ultralytics ..."], timeout=20)`

如果配置了 Paddle 环境，还会继续：

`_module_available(py, "ppdet")`

以及：

`_module_available(py, "paddlex")`

因此一次普通 GET 最多会启动多个新的 Python 解释器，并真实 import 深度学习框架。

当前函数没有：

- TTL cache；
- last verified snapshot；
- in-flight single-flight；
- generation；
- 显式 force refresh 参数；
- 与已有 Resource Discovery verified truth 的复用。

**当前前端真实调用范围：**

最终页面 extras：

`extras412(pageOverride)`

对：

- 测试发布；
- 部署测试；
- 检测台；
- 质量中心

都会同时加载：

`/api/v12/projects/{id}/test_models`

和：

`/api/v16/inference_envs`

另外：

`refreshTestPageDataV3()`

会再次调用 `extras412('测试发布')`。

质量中心切换到模型检测时，也会通过当前 focused page extras 重新读取推理环境。

训练资源刷新链中：

`refreshTrainingResourceTruthV3()`

同样直接请求：

`/api/v16/inference_envs`。

因此这不是仅在“组件检测”按钮下显式运行的重操作，而是普通页面 hydration / refresh 的一部分。

**为什么是性能 Bug：**

“读取当前已选择、已验证的推理环境状态”本应是轻量 read truth。

当前实现却把 read API 和真实 capability probe 绑定在一起：

`GET page truth`
→ spawn python
→ import torch/ultralytics
→ 可能再 spawn Paddle probes
→ 才返回页面状态。

Ultralytics / Paddle 在 CPU 机器、机械盘、冷文件缓存或依赖较多环境下，Python 启动和框架 import 本身就可能明显耗时并占用 CPU/RAM。

并发打开多个页面/浏览器时，还可能同时产生多组探测进程。

**与已有问题的区别：**

- AUDIT-101：`training_options` 会串行探测 legacy training server/resource；
- AUDIT-103：`/api/system/recommendation` GET 会启动 Python/torch probe；
- AUDIT-136：`/api/v16/inference_envs` 为页面展示环境状态，每个 GET 重新 import Ultralytics/ppdet/paddlex。

三个 endpoint 的触发链和正确 owner 不同，不能依赖修复其中一个自动解决另外两个。

**影响：**

- “测试发布 / 检测台 / 质量中心”首开和手动刷新延迟被放大；
- 页面看似只刷新模型列表，后台实际重复启动深度学习 Python；
- 多浏览器并发会产生 probe storm；
- GPU/CPU 内存紧张机器上可能与真实训练/推理竞争资源；
- Paddle 环境存在时单请求可能连续执行多个最长 20 秒的模块探测；
- Web threadpool 会被这些同步 GET 占用；
- 用户容易把页面慢误认为模型检测、Scheduler 或网络异常；
- 与 AUDIT-135 的同步 Test Publish 推理并存时，“打开页面”和“点击测试”都会产生额外进程成本。

**为什么现有收口没有覆盖：**

已有 Resource Discovery 已经把“主动扫描/探测”设计成明确 runtime，但 v16 inference env 仍保留早期“GET 时现查”的兼容逻辑。

`get_active_ultralytics_env()` 本身已经是轻量的已选择环境读取，并明确注释：

“Read-only callers must never launch a probe”。

但 `inference_env_items()` 随后又对该 read projection 之外重新执行 `_module_available`，导致 read-only API 仍然有真实 probe side effect。

**建议最小修复：**

不要新增第二套 Runtime Discovery owner。

应把 v16 endpoint 收敛成轻量投影：

1. 默认 GET 只读取：
   - selected environment；
   - 最近一次 verified capability snapshot；
   - 文件/path 是否仍存在等低成本检查；
2. 真正 import probe 只由已有显式 Resource Discovery /“重新检测环境”动作触发；
3. 若短期仍需 v16 自检：
   - 至少加入 bounded TTL；
   - 同一 python_path + environment revision 使用 single-flight；
   - 支持 `force=true` 明确刷新；
4. 配置变更时 invalidate cache；
5. 不要把“页面刷新”当 capability scan trigger；
6. 结果必须带 verified_at / stale 状态，让 UI 区分“上次验证可用”与“刚刚实时探测”。

**回归测试建议：**

至少增加：

- 连续 100 次 GET /api/v16/inference_envs 不应启动 100 个 Python probe；
- 相同 environment revision 在 TTL 内只 probe 一次；
- 并发 20 个 GET single-flight；
- 显式 force / Resource Discovery 才重新 probe；
- Paddle 环境 ppdet/paddlex 不在普通页面 GET 上重复 import；
- 测试发布/质量中心切页不触发 probe storm；
- environment path/config 变化后 cache 正确失效；
- API 返回的 verified/stale truth 与实际最近一次检测一致。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-137 — “测试发布 → 导出包”仍直接执行第二套 ONNX / Paddle Inference 转换 Runtime；绕过 canonical MODEL_CONVERSION / ModelArtifact / Scheduler

**级别：高**  
**模块：Test Publish / Model Export / ONNX / Paddle Inference / MODEL_CONVERSION / ModelArtifact**

**现象：**

当前“测试发布”页的“待发布/可导出模型”仍真实渲染：

`导出包`

按钮。

最终前端 owner 已从旧 v30 覆盖为：

`window.openExportModel`
→ `window.submitExportModel`
→ `POST /api/v32/projects/{project_id}/model-export`

但 v32 后端并不是 canonical Conversion adapter，而只是：

`return v30_export_model_package(project_id, payload)`

再直接进入：

`_do_export_model_package()`。

当用户选择：

`ultralytics_onnx`

时：

`_do_export_model_package()`
→ `_try_export_ultralytics_onnx()`
→ 生成临时 `export_onnx.py`
→ `subprocess.run(..., timeout=900)`
→ `YOLO(...).export(format="onnx", ...)`

当用户选择：

`paddledet_infer`

时：

`_try_export_paddledet_infer()`
→ 直接调用 PaddleDetection `tools/export_model.py`
→ `subprocess.run(..., timeout=900)`。

所以“导出包”不是简单复制已有 canonical 产物，而是在 Web API 路径中再次真实执行模型转换。

**为什么是重复 Conversion owner：**

平台已经存在 canonical：

`MODEL_CONVERSION`
→ conversion task / Worker / Agent
→ Resource / Scheduler
→ ModelArtifact identity
→ 外部发布/权重追加
→ 转换结果审计。

但 Test Publish 的 v32 export 路径：

- 不创建 MODEL_CONVERSION Durable Task；
- 不进入 Scheduler / Agent；
- 不使用 conversion resource admission；
- 不冻结 canonical conversion artifact identity；
- 不登记 ModelArtifact；
- 不参与 vendor/chip mapping；
- 不参与外部算法版本权重追加；
- 没有统一 cancel / retry / recovery；
- 直接把转换结果写进：
  `projects/{project}/exports/export_.../converted/`
  或 `inference_model/`
  然后压进 ZIP。

因此同一个 `.pt -> .onnx` 实际存在两套生产转换合同。

**实际副作用：**

`_try_export_ultralytics_onnx()` 甚至会同时扫描：

- export work dir；
- `model_path.parent`

下最近的 `*.onnx`

再复制到 export ZIP。

转换结果只是包内文件，没有 canonical artifact_id / source model hash + conversion config identity。

Paddle 路径同样只把 export_model 输出放入导出工作目录。

这意味着用户可以拿到一个“转换成功”的 ONNX/Paddle Inference 包，但平台的：

- 部署转换列表；
- ModelArtifact；
- 算法版本交付链；
- 新畅联权重记录

完全不知道这份产物存在。

**与已有问题区别：**

- AUDIT-024：Remote Conversion 的 daemon thread 绕过 canonical Durable MODEL_CONVERSION；
- AUDIT-137：当前“测试发布”UI 仍提供另一条 request-scoped model-export 转换路径。

即使修完 Remote Conversion daemon，Test Publish 这条 Web export 仍会独立执行 ONNX/Paddle conversion。

**影响：**

- 同一个源模型、相同目标格式可能得到两个没有统一 identity 的转换结果；
- 转换参数、环境、opset、dynamic/simplify 等与 canonical artifact lineage 分裂；
- 用户下载的 ONNX 可能无法在平台部署产物页找到；
- 外部发布不会追加这份权重；
- 多个用户可并发启动最长 900 秒转换，不受 Scheduler 资源治理；
- Web threadpool 可被长转换长期占用；
- 没有统一停止按钮、崩溃恢复和任务历史；
- exports 目录还会继续留下源模型副本、转换文件、日志和 ZIP；
- 后续如果用户把该包重新导入，会形成“平台外生成、平台内再识别”的循环技术债。

**建议最小修复：**

不要新增第三套 Conversion owner。

保留“导出包”作为 packaging UI，但把“生成新模型格式”与“打包已有资产”分开：

1. `platform_package / paddledet_weight / sophon_prepare` 可以继续是轻量打包；
2. `ultralytics_onnx / paddledet_infer` 若目标文件不存在：
   - 创建 canonical MODEL_CONVERSION；
   - 等待/链接其 ModelArtifact；
   - 转换完成后再把 canonical artifact 复制/引用进 export ZIP；
3. 如果相同 source identity + conversion config 已有 canonical artifact，直接复用；
4. v32 endpoint 不再直接调用任何真实模型转换 subprocess；
5. packaging 结果记录所引用的 artifact_id / sha256 / conversion task identity；
6. “导出包”取消/失败不影响 canonical artifact；
7. 不允许 exports ZIP 成为第二产物真相。

**回归测试建议：**

- Test Publish 选择 ONNX 后只创建/复用 canonical MODEL_CONVERSION；
- v32 model-export 不直接执行 `YOLO.export` / `export_model.py`；
- 相同 config 复用已有 ModelArtifact；
- 转换中的导出遵守 Scheduler / Resource truth；
- 转换失败后 export 不伪装成 canonical success；
- export metadata 包含 artifact_id + sha256；
- 新畅联发布仍只消费 canonical ModelArtifact；
- 1k 次导出不会制造 1k 份重复 ONNX conversion truth。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-138 — “测试发布 → 发布为算法版本”手工归属路径无训练/产物验证证据即写死 SUCCEEDED + artifact_verified=true；外部算法可被自动发布 worker 当成合格版本推送新畅联

**级别：高**  
**模块：Test Publish / Algorithm Version Attach / ModelArtifact Eligibility / External Publication / ChangLian**

**现象：**

当前“测试发布”页的“待发布/可导出模型”仍提供：

`归属算法`

按钮。

最终前端：

`window.assignVersion(...)`
→ 弹窗文案“发布为算法版本”
→ `window.saveAssign(...)`
→ `POST /api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions`

请求只提交：

- model_name；
- model_source='project'；
- version_name；
- remark；
- job_id（可能为空）。

后端 `v12_assign_version()` 的真实行为是：

1. 找到模型文件；
2. `shutil.copy2(model_path, version_file)`；
3. 尝试生成 job_report；
4. 直接构造 Algorithm Version；
5. 无条件写入：
   - `training_status = "SUCCEEDED"`
   - `artifact_verified = True`
6. `attach_algorithm_version(...)`；
7. 立即返回。

该路径没有在 attach 前执行：

- Durable Training terminal-success 校验；
- job_id 与 model 文件归属校验；
- frozen training lineage / snapshot 校验；
- ModelArtifact canonical verification owner；
- source SHA256 / immutable identity 验证；
- External Publish eligibility service；
- external algorithm mutation guard。

尤其是：

`v12_update_algorithm()`

会调用：

`assert_algorithm_mutable(...)`

但：

`v12_assign_version()`

没有调用该 guard。

前端算法下拉又直接使用：

`state.algorithms.map(...)`

并未排除 external / CHANG_LIAN 算法。

因此这个兼容入口可以把项目里的本地模型手工挂到外部同步算法上。

**为什么 `artifact_verified=true` 不是 harmless UI 字段：**

External Publication 的正式 publish gate 明确写的是：

`training_status in SUCCESSFUL_VERSION_STATUSES`

且：

`artifact_verified is True`

否则拒绝并提示：

“仅训练成功且模型产物已通过完整性校验的版本可以发布。”

也就是说这两个字段本来就是发布资格真相。

但手工归属接口没有完成这些验证，却直接把两个资格字段写成通过。

**后台会自动把这种版本捞起来：**

`ExternalAlgorithmPublishService.run_auto_publish_once()`

会遍历外部畅联算法的所有 versions。

只要：

- `training_status` 成功；
- `artifact_verified is True`

就会进入自动发布候选。

即使版本没有：

`external_publish_requested_at`

worker 也会主动：

`update_algorithm_version(..., {"external_publish_requested_at": utc_now()})`

然后根据 publication 状态继续：

`self.publish(..., automatic=True)`。

router 启动的 canonical auto-publish worker 默认每 30 秒做 recovery scan。

所以这不是“手工归属后只是本地展示”。

当外部发布配置开启时，它会进入真实新畅联发布链。

**发布阶段后续会做 SHA256，不代表前置资格正确：**

需要区分两个不同合同：

1. `discover_artifacts()`
   确实会在发布阶段重新读取 `stored_path` 并计算 SHA256；
2. `_upload_artifact()`
   也会通过 canonical ModelArtifact storage owner 做上传/复用。

因此不能说“最终外部上传完全没有 hash”。

真正的 Bug 是：

**一个没有训练成功证据、没有 canonical verification owner 判定过的手工版本，被提前伪装成“训练成功 + 已验证”，从而获得进入发布链的资格。**

后续重新 hash 只能证明“现在这个文件内容是什么”，不能证明：

- 它来自成功训练；
- 它属于 payload.job_id；
- 它通过了平台定义的 artifact verification；
- 它有合法 training lineage；
- 它应该被自动发布到该外部算法版本。

**更明显的错误场景：**

场景 A — 任意项目模型：

- 项目 models/ 下存在一个 .pt；
- 用户在“测试发布”点“归属算法”；
- 不提供真实成功训练 job；
- 后端仍写：
  `training_status=SUCCEEDED`
  `artifact_verified=true`。

场景 B — job_id 与模型不匹配：

- payload.job_id 指向 Training A；
- model_name 实际来自 Training B 或手工拷入；
- 当前接口不会证明二者 identity 一致；
- report 可能来自 A；
- version_file 来自 B；
- 版本仍被标记成功且已验证。

场景 C — 外部畅联算法：

- 下拉选择一个同步自畅联的 external algorithm；
- 当前 assign route 不执行 `assert_algorithm_mutable`；
- 本地模型被 attach 成该算法版本；
- auto-publish worker 后续可把它当合格版本同步到远端。

**为什么是 CLOSED 合同的新真实破坏：**

ModelArtifact identity 与 External Publication 主链本身不需要重新设计。

问题恰恰是这个旧 v12 手工 attach 入口绕开了它们的 eligibility contract。

自动训练版本路径已经更严格：

训练完成 attach 后还会：

- 写入真实 training lineage / snapshot；
- 使用训练 job 的 artifact verification truth；
- 执行 auto conversion；
- 显式 `request_external_auto_publish_if_enabled(...)`。

而手工 Test Publish attach 直接写成功/已验证。

这是同一个 Algorithm Version domain 的第二条资格 owner。

**影响：**

- 非训练模型可伪装为“训练成功版本”；
- job report 与真实 model 文件可能串线；
- External ChangLian 算法可被旧兼容入口绕过 mutation guard；
- auto-publish 可把本不应发布的模型推到远端；
- 外部版本/权重与平台训练 lineage 不一致；
- 后续回退、转换、评测都会把这个伪成功版本当正式版本；
- 审计记录无法回答“谁验证了 artifact_verified=true”。

**建议最小修复：**

不要新增第二 ModelArtifact 或 External Publish owner。

1. `v12_assign_version()` 不得自行写：
   `training_status=SUCCEEDED`
   `artifact_verified=true`；
2. 若“归属算法”只允许真实训练产物：
   - 必须要求 job_id；
   - 校验 Durable Training terminal status；
   - 校验 model identity / sha 属于该 job；
   - 复用 canonical artifact verification truth；
3. 若产品确实允许导入第三方预训练模型：
   - 使用独立 provenance，例如 `IMPORTED_VERIFIED`；
   - 经过明确 ModelArtifact verify/import owner；
   - 不伪装成 training SUCCEEDED；
4. external / CHANG_LIAN 算法必须执行已有：
   `assert_algorithm_mutable`
   或明确的 external version creation policy；
5. auto-publish eligibility 必须来自 canonical verified artifact/training provenance，而不是兼容 endpoint 可直接写的布尔字段；
6. job report、model SHA、artifact identity、version lineage 必须互相绑定；
7. 当前 Test Publish “发布为算法版本”应复用已有正式 attach/version service，不再直接拼 version dict。

**回归测试建议：**

- 无 job_id 的普通项目模型不能被标成 training SUCCEEDED；
- job_id 与 model 不匹配时 fail-closed；
- 未验证 artifact 不能写 `artifact_verified=true`；
- external algorithm 不可通过 v12 assign 绕过 mutability guard；
- 手工 imported model 不会被 auto-publish worker误判为训练成功版本；
- 合法 Training output 仍可 attach；
- 合法 imported/pretrained flow 有明确 provenance + verification；
- auto-publish 只消费 canonical eligibility truth；
- 版本 report/model SHA/lineage 必须一致。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-139 — 正确的 Training Version CAS 已实现并有并发单测，但生产归档仍调用普通 attach；两个基于同一旧版本的训练都可成功并互相覆盖 current_version_id

**级别：高**  
**模块：Training Completion / Algorithm Version / Iteration Lineage / current_version_id / Concurrency**

**现象：**

当前算法版本存储层已经明确实现：

`AlgorithmSqlStore.attach_version_if_current(...)`

它的业务合同就是：

“训练完成归档时，只有训练创建时冻结的 base version 仍然是当前版本，才允许把新版本挂上去。”

实现中使用：

`BEGIN IMMEDIATE`

并在同一事务内读取：

`algorithms.current_version_id`

然后比较：

`expected_current_version_id`

如果当前版本已经变化，则抛：

`ALGORITHM_VERSION_CONFLICT`

首训场景同样受保护：创建任务时没有 base version，而归档时如果已经出现任何版本，也会拒绝旧首训任务覆盖当前版本。

**更关键的是，现有单元测试已经把正确合同写得非常清楚：**

`test_atomic_training_attach_...`

构造两个并发 Training completion，都基于：

`base_version_id = v1`

并发调用：

`attach_version_if_current(..., expected_current_version_id="v1")`

测试明确要求：

- 只能一个 `ok`；
- 另一个必须 `ALGORITHM_VERSION_CONFLICT`；
- 最终只能新增一个 child version；
- `current_version_id` 必须指向该唯一 child。

还测试了：

- 同一个 training task retry 必须幂等；
- 首训任务在归档前已经出现版本时必须拒绝。

所以“训练版本 CAS”不是未来设计，而是当前仓库已经实现、已有测试保护的 canonical contract。

**但生产 Training completion 没有接上它：**

当前：

`_v48_archive_training_version(project_id, job)`

在完成：

- artifact_verified 检查；
- 模型复制；
- SHA256；
- training_lineage；
- evaluation；
- base_version_id 记录

之后，最终仍调用：

`attach_algorithm_version(...)`

而不是：

`attach_version_if_current(...)`

普通 `attach_version()` 虽然也使用 SQLite `BEGIN IMMEDIATE`，但它只保证单次写入事务完整。

它**不会比较 frozen base 与当前 current_version_id**。

其行为是：

1. 插入新 version；
2. 无条件：
   `UPDATE algorithms SET current_version_id = new_version_id`。

所以两个任务会串行写成功，而不是一成一拒。

**真实并发场景：**

初始：

`current_version_id = v1`

用户几乎同时创建：

- Training A，base=v1；
- Training B，base=v1。

两者都合法启动，因为任务创建时 v1 确实是当前版本。

若 A 先完成：

- A 归档 v2；
- current_version_id = v2。

随后 B 完成。

正确合同应当是：

- B 的 frozen base=v1 已过期；
- 保留 B 的训练结果用于审计；
- 但不得自动把 B 作为新的 current version；
- 返回/记录 `ALGORITHM_VERSION_CONFLICT`。

当前生产实现却会：

- 普通 attach B 为 v3；
- 无条件 current_version_id = v3。

于是 B 直接覆盖了 A，形成：

`v1 -> A(v2)`

随后又被一个**同样基于 v1、而不是基于 v2**的 sibling：

`B(v3)`

取代。

这不是合法的串行迭代链，而是 sibling result 覆盖 current pointer。

**首训也有同类问题：**

算法最初没有版本时，同时创建两个首训任务。

正确 `attach_version_if_current(expected_current_version_id=None)` 会保证：

- 第一个归档成功；
- 第二个发现当前已经存在版本并冲突。

当前普通 attach 则两者都能成功，后完成者成为 current。

**额外的版本编号漂移：**

归档前代码还在事务外读取：

`algo.get("versions")`

并计算：

`version_no = len(versions)+1`。

两个并发任务读取同一旧快照时，可以都计算出同一个 version_no。

`algorithm_versions` 当前没有 `(algorithm_id, version_no)` 唯一约束。

因此 sibling versions 不仅 lineage 冲突，还可能出现重复业务 version_no。

手工 v12 “发布为算法版本”也采用相同的事务外：

`len(algo.get("versions", []))+1`

所以该编号问题会被兼容入口进一步放大。

**为什么是 Runtime 装配 Bug，不是重新设计 Training Picker：**

Training 创建阶段已经冻结：

- `base_version_id`；
- training lineage；
- Dataset Snapshot / Revision。

SQL store 也已经提供正确 CAS owner。

缺口仅在 completion 归档最后一步仍装配到旧：

`attach_algorithm_version`

而不是 canonical：

`attach_version_if_current`。

不需要改 Training Picker、Dataset Revision 或重新设计算法版本体系。

**影响：**

- 同一算法并发训练结果可以互相覆盖 current version；
- “当前版本的下一次迭代”可能从错误 sibling 开始；
- UI 看到的当前版本取决于完成时序，而不是合法 lineage；
- auto conversion 会对两个 sibling 都可能启动；
- external auto publish 也可能把两个不合法 sibling 当正式版本推送；
- rollback/version history 中会出现非线性 lineage；
- version_no 可能重复；
- 用户难以判断哪个版本真正继承了哪个版本；
- 已有 CAS 单测绿色却无法保护生产，因为生产没有调用该方法。

**建议最小修复：**

不要新增第二 Algorithm Version owner。

1. `_v48_archive_training_version()` 必须改用已有：
   `attach_version_if_current()`；
2. `expected_current_version_id` 使用任务创建时冻结的：
   `base_version_id`；
3. 首训明确传 `None`，复用已有“当前不得已经出现版本”的合同；
4. 同 task retry 继续复用已有 training_job_id 幂等逻辑；
5. 如果发生 `ALGORITHM_VERSION_CONFLICT`：
   - 不删除已训练模型/报告；
   - 标记“训练成功但版本归档冲突/需人工处理”；
   - 不 auto convert；
   - 不 auto publish；
6. version_no 也应在同一事务/owner 内原子分配，或使用已有稳定时间/identity；不能在外部用旧 `len()+1` 快照计算；
7. 手工版本 attach 与 Training attach 应明确分离 provenance，但都不能产生重复业务版本身份。

**回归测试建议：**

除现有 SQL store 单测外，必须增加生产 wiring 测试：

- 两个 Durable Training 都 frozen base=v1；
- A 先完成并归档；
- B 后完成；
- B 必须得到 `ALGORITHM_VERSION_CONFLICT`；
- current 必须仍是 A；
- B 不触发 auto conversion / external publish；
- 两个并发首训只能一个成为首版本；
- retry 同一 Training task 仍幂等；
- version_no 不重复；
- crash/recovery 后 CAS 语义不丢失。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-140 — Training 版本归档先持久化 auto_version_id、后创建自动转换任务；进程在中间崩溃后 recovery 会永久跳过用户已请求的自动转换

**级别：高**  
**模块：Training Completion / Algorithm Version Archive / Auto Conversion / Crash Recovery / Delivery Lifecycle**

**现象：**

当前训练成功后的版本归档顺序是：

`_v48_archive_training_version()`

1. 复制训练产物并构造 Algorithm Version；
2. `attach_algorithm_version(...)`；
3. 立即：
   `job["auto_version_id"] = version_id`
   并写回：
   `jobs/{job_id}/job.json`；
4. 然后才调用：
   `_v48_auto_convert_version(...)`；
5. 自动转换函数逐个创建 MODEL_CONVERSION job；
6. 再把 summary 写入：
   `version.auto_conversion`
   与：
   `job.auto_conversion`；
7. 最后才请求 external auto publish。

但该函数入口第一条幂等判断是：

`if not job or job.get("auto_version_id") or job.get("never_started"): return None`

所以 `auto_version_id` 实际被同时当成：

“版本已经 attach”

和：

“整个版本交付后处理都已经完成”

两个不同生命周期阶段的完成标志。

**真实 crash window：**

如果进程在步骤 3 之后、步骤 4 之前退出：

- Algorithm Version 已存在；
- job.json 已有 `auto_version_id`；
- 用户创建训练时提交的 `auto_convert_targets` 仍在 job；
- 但一个 MODEL_CONVERSION 都还没有创建。

服务重启后，训练任务再次被 hydrate / recovery 时：

`_v48_archive_training_version()`

看到：

`job.auto_version_id`

立即返回。

因此已经请求的自动转换不会再次创建。

**多目标时还有 partial window：**

例如用户请求：

- rockchip；
- ascend；
- sophon。

`_v48_auto_convert_version()` 是逐个调用：

`v39_create_deploy_job(...)`

如果：

- 第一个 conversion job 已创建；
- 进程在第二个/第三个创建前崩溃；

重启后同样因为 `auto_version_id` 已存在而跳过整个 auto conversion。

最终只完成部分目标，但没有 recovery owner 自动补齐缺失目标。

**第三个窗口：**

即使所有 conversion jobs 都已经创建，如果进程在：

`_v48_auto_convert_version()`

返回以后、但在：

`update_algorithm_version(... {"auto_conversion": summary})`

之前崩溃，则：

- Conversion Task 实际已经存在；
- Algorithm Version 没有 `auto_conversion` journal；
- job.json 也没有 summary；
- recovery 仍因 `auto_version_id` 直接返回。

后续 UI /审计无法可靠回答：

“这个版本自动创建过哪些转换任务”。

**为什么 external publish 不是同一个问题：**

External Publication 有独立的：

`ExternalAlgorithmPublishService.run_auto_publish_once()`

会周期性扫描成功且已验证的外部算法版本，即使缺少 `external_publish_requested_at` 也能补请求并继续 reconcile。

因此 external publish 具有独立恢复 owner。

当前自动转换没有发现同类：

- version delivery reconciler；
- requested-target journal；
- missing-target recovery；
- idempotent ensure-conversion owner。

当前 `app.py` 中 `_v48_auto_convert_version()` 只有：

- 函数定义；
- `_v48_archive_training_version()` 这一处调用。

`auto_conversion` 也只在该归档尾部写入。

**为什么不是 AUDIT-046：**

AUDIT-046 是：

自动转换请求只冻结 vendor，没有冻结芯片 / SoC / resource identity。

AUDIT-140 是：

即使用户请求本身合法，Training completion 在版本 attach 与 conversion creation 之间缺少 crash-consistent lifecycle journal，崩溃后会永久漏执行全部或部分自动转换。

两者分别是“请求身份冻结”和“后处理恢复”。

**影响：**

- 训练任务显示成功、算法版本已经生成，但用户勾选的自动转换可能完全没有任务；
- 多目标转换可能只创建一部分；
- 重启后无法自动补齐；
- Algorithm Version 的 `auto_conversion` metadata 与真实 conversion jobs 可能分裂；
- 用户只能人工发现后再手动补转换；
- 外部发布可能先继续推进，而原计划的芯片转换交付缺失；
- “训练成功 → 自动转换”主流程不满足 crash recovery / exactly-once-or-idempotent-delivery 合同。

**建议最小修复：**

不要新增第二 Conversion owner。

应把版本后处理变成明确的可恢复状态机 / journal，至少区分：

- version_attached；
- auto_conversion_pending；
- auto_conversion_reconciling；
- auto_conversion_completed / partial / failed；
- external_publish_requested。

最小实现方向：

1. 版本 attach 时把用户请求的 `auto_convert_targets` 冻结到 version delivery metadata；
2. 不要用 `auto_version_id` 作为整个后处理完成标志；
3. 提供 idempotent：
   `ensure_auto_conversions(version_id)`；
4. 对每个 target 用 canonical source version identity 查找已有 active/terminal conversion，再决定：
   - 复用；
   - 补建；
   - 记录失败；
5. startup/recovery 或 version-delivery reconciler 对 pending/partial 自动补齐；
6. conversion job 创建与 version.auto_conversion journal 之间必须可重放；
7. 修复 AUDIT-139 后，只有 CAS attach 成功的版本才能进入后处理。

**回归测试建议：**

至少注入以下 crash points：

- version attach 后、auto conversion 前崩溃；
- 第 1/3 个 target 创建后崩溃；
- 全部 conversion 创建后、summary patch 前崩溃；
- summary patch 后、external publish request 前崩溃。

重启后必须满足：

- 请求目标最终全部可追踪；
- 不重复创建相同 conversion；
- 已有 conversion 被复用；
- version.auto_conversion 与真实 jobs 一致；
- 未通过 version CAS 的 sibling training 不进入自动转换。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-141 — “同一待发布模型只能归属一次”仅做事务外 used_model_keys 检查；并发请求可把同一个 model_key 同时挂到多个算法版本

**级别：高**  
**模块：Test Publish / Pending Models / Algorithm Version Attach / Concurrency / Model Ownership**

**现象：**

当前产品已经明确表达一个 invariant：

**一个待发布模型只能归属到一个算法版本。**

证据有两处：

1. `GET /api/v12/projects/{project_id}/publish/pending`

会调用：

`used_model_keys(project_id)`

只返回：

`model_key not in used`

的模型。

2. `POST /api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions`

在 attach 前再次执行：

`if model_key in used_model_keys(project_id):`

并明确返回：

“该模型已经归属到算法版本中”。

但该约束只存在于应用层事务外 read-check-write。

真实顺序是：

1. 请求 A 读取 algorithms/version snapshot；
2. 请求 A 计算 `used_model_keys`，模型 M 尚未使用；
3. 请求 B 同时读取；
4. 请求 B 也判断 M 尚未使用；
5. A 复制 M 到自己的 version dir；
6. B 复制 M 到另一个 version dir；
7. A `attach_algorithm_version` 成功；
8. B `attach_algorithm_version` 也成功。

**数据库不会阻止第二次 attach：**

当前 `algorithm_versions` 表只有：

- `id TEXT PRIMARY KEY`；

以及普通索引：

- algorithm_id；
- training_job_id；
- external_algo_version_id。

`model_key` 并不是独立 SQL column，只保存在：

`payload_json`

里。

因此不存在：

- `UNIQUE(model_key)`；
- project-scoped model ownership claim；
- compare-and-set；
- reservation row。

两个请求使用不同随机 version_id 时，数据库完全允许两次 INSERT。

**这不是理论上的双击问题：**

即使单浏览器以后加按钮 disabled，也无法保护：

- 两个浏览器；
- 两个用户；
- API 重试；
- 双节点 Web 实例；
- 慢请求期间另一请求进入。

正确约束必须在 canonical persistence owner 内原子实现，不能依赖前端 single-flight。

**与 AUDIT-138 的区别：**

AUDIT-138 是：

手工“发布为算法版本”无真实训练/产物验证证据却写死 SUCCEEDED + artifact_verified，并可进入外部发布。

AUDIT-141 是：

即使暂不讨论版本资格是否合法，同一个 source `model_key` 的“只能归属一次”约束本身也没有原子性，并发时会产生多个版本引用同一来源模型。

**影响：**

- 同一个项目模型可同时成为两个算法的正式版本；
- `publish/pending` 之后只会看到“已使用”，却无法说明哪个归属才是合法 owner；
- 两个版本都可能继续：
  - 自动转换；
  - 质量评测；
  - 外部发布；
- 同一训练产物可能被发布为多个算法/分析能力；
- 删除/回退其中一个版本不会自然修复另一个重复归属；
- 审计 lineage 从源模型开始就出现一对多歧义；
- 并发请求还会各自复制一份模型文件，造成额外重复存储。

**建议最小修复：**

不要新增第二套模型 registry。

应在现有 `AlgorithmSqlStore` / version attach owner 内原子实现 model ownership：

1. 把需要唯一约束的 canonical `model_key` 提升为可索引字段，或增加同库 ownership table；
2. 在同一个 SQLite transaction 中：
   - claim model_key；
   - insert version；
   - update current pointer；
3. project scope 下 model_key 已被其他 version claim 时返回明确 409；
4. 同一个幂等 operation/task retry 应返回已有 version，而不是冲突；
5. 文件复制最好在最终 claim 前使用 staging，claim 失败后清理临时副本；
6. `publish/pending` 继续作为 read projection，不承担并发正确性 owner。

如果未来产品允许“同一二进制模型属于多个算法”，应显式改变产品合同，并用 artifact identity / provenance 表达复用；不能一边提示“只能归属一次”，一边在竞态下静默允许重复。

**回归测试建议：**

至少增加：

- 两个线程同时把同一个 `project::model.pt` 归属到不同算法；
- 必须只有一个成功；
- 另一个明确 409；
- 最终数据库只存在一个 model_key owner；
- 同一请求重试幂等；
- 两 Web 实例共享 SQLite 时仍成立；
- claim 失败不留下 orphan version dir；
- pending list 与最终 owner 一致；
- concurrent attach 不产生重复 auto conversion / external publish。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-142 — 同一 Training task 并发归档时 SQL 幂等会返回已存在版本，但上层仍继续使用自己生成的随机 version_id，导致 job/current delivery identity 指向不存在版本

**级别：高**  
**模块：Training Completion / Version Archive / Idempotency / Version Identity / Auto Conversion / External Publish**

**现象：**

当前 `AlgorithmSqlStore.attach_version()` 已经为同一训练任务提供幂等逻辑。

attach 时会提取：

`task_id = version.task_id / job_id / training_job_id`

在 SQLite transaction 内先查询：

`SELECT * FROM algorithm_versions WHERE algorithm_id=? AND training_job_id=? LIMIT 1`

如果已经存在，则：

`return self._version_from_row(duplicate)`

也就是说：

**同一个 Training task 即使重复调用 attach，并且本次新生成了不同 version_id，canonical store 仍会返回第一次已经成功归档的真实 version。**

`attach_version_if_current()` 也保留了同样的“duplicate training_job_id 先于 base conflict 处理”的幂等合同。

**但生产归档调用方没有使用返回版本的真实 ID：**

`_v48_archive_training_version()`

会先在函数外生成：

`version_id = uuid.uuid4().hex[:12]`

然后构造 version 并调用：

`version = attach_algorithm_version(..., version)`

如果发生并发归档：

- 调用 A 用随机 ID `version-A`；
- 调用 B 用随机 ID `version-B`；
- A 先在 SQL 中插入；
- B 进入 SQL 后通过 `training_job_id` 查到 A；
- B 的 `attach_algorithm_version()` 返回的 `version` 实际是 A 的记录：
  `version["id"] == version-A`。

但 B 回到调用方后没有改用：

`version["id"]`

而是继续使用自己之前生成的局部：

`version_id == version-B`。

当前后续代码明确是：

`job["auto_version_id"] = version_id`

随后：

`update_algorithm_version(..., version_id, {"auto_conversion": ...})`

再随后：

`request_external_auto_publish_if_enabled(..., version_id=version_id)`。

所以底层已经正确实现的幂等返回，在上层立即被错误的 stale local identity 破坏。

**真实并发结果：**

同一个成功 Training task 的两个归档调用同时进入：

1. A、B 都在函数开头看不到 `job.auto_version_id`；
2. 两边都读取到尚未归档的 algorithm snapshot；
3. A 生成 `version-A`，B 生成 `version-B`；
4. A SQL attach 成功；
5. B SQL attach 检测同 training_job_id，返回 `version-A`；
6. B 却写：
   `job.auto_version_id = version-B`；
7. B 还会基于返回的真实 `version-A` 去执行自动转换，因此可能重复创建 conversion；
8. B 随后尝试：
   `update_algorithm_version(..., version-B, ...)`；
9. `version-B` 根本没有写入 SQL，patch 会失败；
10. B 后面的 external publish request 同样可能使用不存在的 `version-B`。

最危险的是第 6 步已经可能把错误 ID 落进：

`jobs/{task_id}/job.json`。

以后恢复时函数入口看到：

`job.auto_version_id`

会直接返回，形成持久化错误身份。

**为什么现有 SQL 幂等测试仍然全绿：**

存储层单测已经明确验证：

- 第一次 attach task `train-retry` 得到 v2；
- 第二次 attach 同一 task、即使传 `v2-different-generated-id`；
- 返回值仍必须是 v2；
- 数据库里只保留一个 training_job_id 版本。

这个 store 合同本身是正确的。

缺的是生产 wiring 测试：

`_v48_archive_training_version()`

必须使用 attach 返回的 canonical ID，而不是继续相信调用前生成的 tentative ID。

**与已有问题区别：**

- AUDIT-139：两个**不同 Training task**基于同一旧 base 都能普通 attach，缺少 CAS；
- AUDIT-140：一个已 attach version 的后处理在 auto conversion 前崩溃，恢复被 `auto_version_id` 短路；
- AUDIT-142：同一个 Training task **并发/重入归档**时，store 已幂等返回已有版本，但 caller 不采用返回 identity，反而写入不存在的随机 ID。

三者分别对应：

- sibling CAS；
- post-attach crash journal；
- same-task idempotent identity propagation。

**影响：**

- job.json 的 `auto_version_id` 可指向数据库不存在的版本；
- Training 任务与 Algorithm Version 的 lineage 断裂；
- 自动转换可能被重复创建；
- conversion summary patch 可能打到不存在版本并失败；
- external auto publish request 可能引用不存在版本；
- 后续 recovery 因错误 `auto_version_id` 误判“已归档”，无法自愈；
- UI 从 job 与 algorithms 两个来源读取时可能出现“任务显示版本 ID，但算法版本页找不到”的前后端真相分裂。

**建议最小修复：**

不要修改 store 的幂等合同；它目前是正确的。

生产 caller 必须把 attach 返回值当 canonical truth：

1. attach 后立即：
   `canonical_version_id = str(version["id"])`；
2. 后续所有：
   - job.auto_version_id；
   - auto_conversion patch；
   - external publish request；
   - conversion source version identity；
   都必须只用 canonical_version_id；
3. 修 AUDIT-139 时改用 `attach_version_if_current()` 也必须遵守同样规则；
4. 同一 task 的并发归档后处理需要 single-flight / idempotent delivery reconciliation，避免两个 caller 同时创建 conversion；
5. 若 job.json 已存在错误 auto_version_id，恢复时应按 training_job_id 反查 canonical version 并修复，而不是直接 short-circuit。

**回归测试建议：**

至少增加生产级并发测试：

- 同一个 Training job 同时进入两次 `_v48_archive_training_version()`；
- 两次预生成不同 version_id；
- SQL 最终只有一个 version；
- 两个 caller 都必须收敛到同一个 canonical version id；
- job.auto_version_id 必须等于 SQL version id；
- conversion 每个 target 最多一个；
- external publish 只请求 canonical version；
- crash 后按 training_job_id 能恢复正确 identity；
- 不允许 stale tentative version_id 进入任何 durable metadata。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-143 — 项目详情 GET 为统计已标注图片/框数逐素材调用 AnnotationRepository.get；20k 素材形成 N+1 Ground Truth 热路径，且被 loadRelated 高频触发

**级别：中～高**  
**模块：Project Summary / Annotation Ground Truth / Frontend loadRelated / Performance**

**现象：**

当前项目详情：

`GET /api/projects/{project_id}`

返回的核心统计只有：

- images；
- annotated_images；
- boxes；
- jobs；
- models。

但为了计算 `annotated_images` 与 `boxes`，当前实现先：

`images = load_images(project_id)`

随后对项目内每一张素材执行：

`read_annotation(project_id, img["id"])`

而 `read_annotation()` 又是：

`_v50_annotation_repository(project_id).get(image_id)`

因此 N 张素材会产生 N 次单条 Ground Truth lookup。

仓库其实已经存在 canonical bounded batch API：

`read_annotations_many(project_id, image_ids)`

→ `AnnotationRepository.get_many(ids)`

并限制单批最多 500 个 image id，但项目详情没有使用批量读取或 repository aggregate。

**为什么这是生产热路径，而不是低频管理接口：**

前端 `loadRelated()` 首先请求：

`/api/projects/${pid}`

而 `loadRelated()` 不只在首开调用。当前真实调用点包括：

- `loadAll()`；
- 项目切换；
- 新增 / 编辑 / 删除标签后；
- 图片上传后；
- 批量移动数据用途后；
- 数据集操作后；
- Cleaning confirm 后；
- ZIP 导入完成后；
- 其它 mutation 后的页面 refresh。

所以一个 10k / 20k 素材项目，每次这些常见操作完成后的“刷新相关数据”，都会重新走一次全项目逐图 Annotation lookup。

**与 AUDIT-066 的区别：**

AUDIT-066 是 Training jobs REST 在返回 bounded history 前多次扫描全部历史 `jobs/*/job.json`。

AUDIT-143 是 Project Summary 为两个 Annotation 统计值逐素材读取 canonical Ground Truth。

两者会在同一个 `GET /api/projects/{project_id}` 中叠加，因为该接口还会调用：

`sync_jobs_index(project_id)`。

所以项目越大、训练历史越长，`loadRelated()` 的固定刷新成本会同时受到：

- 素材总量；
- Annotation 总量；
- Training 历史总量

三者放大。

**影响：**

- 1k / 10k / 20k 素材规模下项目切换、上传完成、标签修改、清洗确认后的 UI 刷新持续变慢；
- 大项目会产生大量重复 SQLite/GT 单条读取与 Python 对象构造；
- Web 请求线程被项目级统计占用，用户会把普通 mutation 误认为“保存很慢”；
- 前端虽然只需要几个 summary 数字，却付出完整项目 GT hydration 成本；
- 与 AUDIT-066 同时存在时，项目详情接口成为素材历史和训练历史双线性增长的热点。

**为什么现有批量能力没有保护住：**

当前代码已经明确提供：

`read_annotations_many(...)`

且注释为：

“Bounded formal Ground Truth read through the canonical repository owner.”

说明平台已经认可 bounded batch read 作为正式 Ground Truth 读取方式。

但 `read_project()` 仍保留旧的逐图 `read_annotation()` 循环，没有接入该 canonical batch/aggregate 能力。

**建议最小修复：**

不要新增第二套 Annotation 统计 owner，也不要把 MaterialRepository 的兼容投影反过来当 Ground Truth。

优先继续由 AnnotationRepository 提供 canonical summary，例如：

- repository aggregate：annotated image count + total box count；
- 或暂时按 500 image ids 分批 `get_many()`，避免 N 次单条 lookup。

同时：

1. 项目详情只读取真正需要的 summary，不 hydrate 每张 annotation；
2. `sync_jobs_index()` 的历史扫描按 AUDIT-066 独立收口；
3. 前端现有 `loadRelated()` 行为可保持，不应靠减少刷新来掩盖后端 O(N)；
4. 增加 1k / 10k / 20k contract，明确 repository query/read 次数有上界，不能随图片数按单条调用线性增长。

**回归测试建议：**

至少覆盖：

- 20,000 materials，项目详情返回 images / annotated_images / boxes 正确；
- 禁止调用 20,000 次 `AnnotationRepository.get`；
- canonical `get_many` 分批次数 bounded，或单次 aggregate；
- confirmed_empty 不计入 annotated boxes，但其 Ground Truth 状态不被破坏；
- 项目无 Annotation、部分 Annotation、全量 Annotation 三种统计一致；
- 与大量 Training history 并存时，不把 AUDIT-066 的全历史扫描重新引入 aggregate 修复。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-144 — Dataset Summary 把 confirmed_empty 正式负样本统计成“未标注”，总览会把已完成 Ground Truth 的数据集误判为未标注/混合

**级别：高**  
**模块：Dataset Summary / Annotation Ground Truth / Dashboard / confirmed_empty**

**现象：**

当前：

`GET /api/projects/{project_id}/datasets`

为了计算每个 dataset 的：

- images；
- annotated_images；
- boxes；

会读取正式 AnnotationRepository，然后使用：

`count = len(annotation.get("boxes") or [])`

并且只有：

`if count: row["annotated_images"] += 1`

才把图片计入“已标注”。

这意味着：

`annotation_state = confirmed_empty`

且 boxes=[] 的正式负样本，虽然已经经过用户明确“确认无目标”，仍被 dataset summary 统计成：

`annotated_images += 0`

即“未标注”。

**为什么与 canonical Ground Truth 合同冲突：**

当前 Annotation canonical summary 已明确：

`annotated = state in {"annotated", "confirmed_empty"}`

同时正式保存链：

`_v50_material_annotation_patch()`

对：

- annotated；
- confirmed_empty

都会设置：

- `processing_status = processed`；
- `annotated_at`；
- 正式 AnnotationRepository truth。

训练判断 `is_training_ground_truth(...)` 也会把 confirmed_empty 当作正式 Ground Truth。

所以平台当前存在两套“已标注”语义：

1. Annotation / Material / Training：confirmed_empty = 已完成正式真值；
2. Dataset Summary：只有 box_count > 0 才算已标注。

这不是展示措辞差异，而是同一个业务事实在不同接口中相互矛盾。

**真实用户可见影响：**

前端总览直接聚合：

`datasets[].annotated_images`

并按：

- annotated == images → “全标注”；
- annotated > 0 → “混合”；
- 否则 → “未标注”

给数据集分类。

因此例如一个数据集：

- 100 张图片；
- 80 张正常 bbox 标注；
- 20 张 confirmed_empty；

真实 Ground Truth 完成度是 100/100。

当前 summary 却显示：

- images = 100；
- annotated_images = 80；
- boxes = 正框数量；

然后把数据集归类成“混合”。

更极端地，一个正式负样本数据集：

- 100 张 confirmed_empty；
- 0 个框；

会显示：

- annotated_images = 0；
- 数据集 = “未标注”。

用户会被误导为这些图片还需要人工标注，甚至可能重复进入标注/清洗流程。

**与 AUDIT-143 的区别：**

AUDIT-143 是：

`GET /api/projects/{project_id}`

逐素材单条读取 Annotation 的 N+1 性能问题。

AUDIT-144 是：

`GET /api/projects/{project_id}/datasets`

对 confirmed_empty 的**统计语义错误**。

即使把 AUDIT-143 的 N+1 全部优化掉，AUDIT-144 仍然存在。

**建议最小修复：**

不要用“有无 boxes”推断正式标注状态。

Dataset Summary 应按 canonical Annotation state 统计：

- `annotated` → 已完成；
- `confirmed_empty` → 已完成；
- `unannotated` → 未完成。

同时保留：

- boxes = 实际 bbox 数量；
- confirmed_empty 不增加 boxes。

建议明确拆出：

- ground_truth_images / annotated_images（包含 confirmed_empty）；
- positive_annotated_images（如业务真的需要“有框图片数”）；
- confirmed_empty_images。

不要通过把 confirmed_empty 伪造一个框来解决。

**回归测试建议：**

至少覆盖：

- 1 annotated + 1 confirmed_empty → annotated_images=2；
- 100 confirmed_empty → dataset 不得显示“未标注”；
- confirmed_empty 的 boxes 仍为 0；
- AnnotationRepository / Material projection / Dataset Summary 三者状态一致；
- 总览“全标注 / 混合 / 未标注”分类使用正式 GT 完成度。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-145 — Dataset List 每次全量读取全部 Material + 全部 Annotation 后才聚合统计；loadRelated 高频触发，20k 素材形成项目级 O(N) Ground Truth hydration

**级别：中～高**  
**模块：Dataset List / AnnotationRepository / MaterialRepository / Frontend loadRelated / Performance**

**现象：**

当前：

`GET /api/projects/{project_id}/datasets`

虽然最终通常只返回几个 dataset summary，但实现会先：

`images = load_images(project_id)`

即全量 hydrate 项目所有 Material。

随后收集全部 image ids，再按 500 一批执行：

`read_annotations_many(project_id, batch_ids)`

把项目全部正式 Annotation 读入一个 Python dict：

`annotations: Dict[str, Dict[str, Any]]`

最后才在 Python 中遍历所有 images，按 dataset_id 聚合：

- images；
- annotated_images；
- boxes。

因此 20,000 张素材时，一次 dataset list 至少包含：

- 全量 Material payload hydration；
- 40 批 AnnotationRepository.get_many；
- 20k Python row 遍历；
- 20k Annotation object 驻留/聚合。

这不是分页读取，因为 endpoint 最终返回的是小型聚合结果，却先把全部明细读进内存。

**为什么是生产热路径：**

前端 `loadRelated()` 会请求：

`/api/projects/{pid}/datasets`

而 `loadRelated()` 会在多类常规 mutation 后执行，包括项目加载、标签变化、导入/上传相关刷新等。

因此项目素材规模扩大以后，“只是刷新几个 dataset 数字”会持续支付全项目 Material + Ground Truth hydration 成本。

**与 AUDIT-143 的区别：**

AUDIT-143：

- Project Detail；
- 每张图片逐条 AnnotationRepository.get；
- 典型 N+1。

AUDIT-145：

- Dataset List；
- 虽然 Annotation 已按 500 批量读取；
- 但仍然为一个小型 aggregate **全量读取 1k/10k/20k 明细**。

所以把单条 get 改成 get_many 并不能解决这类 aggregate endpoint 的规模问题。

**影响：**

- 10k/20k 项目下总览、项目加载、mutation 后刷新越来越慢；
- Web 进程产生不必要的 JSON decode / Python dict / Annotation object 内存压力；
- 与 AUDIT-143、AUDIT-066、AUDIT-100 同时被 `loadRelated()` 触发时，页面刷新成本叠加；
- dataset 数量即使只有 1～3 个，也要扫描整个项目；
- 高并发用户同时打开项目时会放大 SQLite read 和 Python GC 压力。

**建议最小修复：**

不要新增第二套 Ground Truth owner。

应继续由 canonical repositories 提供 aggregate truth，但 aggregate 必须在存储层完成，而不是 hydrate 全量对象：

1. MaterialRepository 对 dataset_id 建立可查询/索引化字段，或提供按 dataset group count；
2. AnnotationRepository 提供按 material/dataset scope 的正式 GT aggregate；
3. confirmed_empty / annotated 的统计语义按 AUDIT-144 统一；
4. endpoint 只返回 aggregate rows，不构造 20k Annotation dict；
5. 如果短期需要批处理过渡，也要 streaming/bounded，不得把全部 annotations 常驻 Python 内存。

不要简单把 500 批改成 1000/5000；那只减少调用次数，不改变全量 hydration。

**回归测试建议：**

至少增加：

- 20,000 materials + 多 dataset；
- dataset list 聚合结果准确；
- AnnotationRepository 明细 hydration 次数有明确上界，最好为 aggregate query；
- 不构造 20k annotation Python dict；
- confirmed_empty 计入 GT 完成度但 boxes=0；
- endpoint latency/work 不随“每张 annotation 对象读取”线性增长。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-146 — Quality Center / 训练素材质量只按“有框”计算标注完整度，confirmed_empty 正式负样本被当成未标注并错误拉低质量分

**级别：高**  
**模块：Quality Center / Training Data Quality / Annotation Ground Truth / confirmed_empty / Quality Score**

**现象：**

当前：

`_v44_dataset_quality(project_id, req)`

已经从 canonical AnnotationRepository 批量取得每张图片的正式 Annotation：

`ann = annotations.get(image_id) or {}`

并读取/清洗：

`ann["boxes"]`

但构造交给：

`compute_quality(candidates)`

的 candidate row 时，只写入：

- boxes；
- valid_box_count；
- invalid_box_count；
- split；
- material fields；

没有把 canonical：

`annotation_state`

显式带给 quality owner。

而 `platform_core/quality.py::compute_quality()` 当前统计：

`if boxes: annotated_images += 1`

完全不判断：

- annotated；
- confirmed_empty；
- unannotated。

所以：

`confirmed_empty + boxes=[]`

会被 Quality Center 当成“未标注”。

**为什么是准确性 Bug：**

平台 canonical Ground Truth 已明确：

`confirmed_empty`

是人工确认的正式负样本：

- AnnotationRepository 正式保存；
- Material projection 标为 `annotated=true`；
- `processing_status=processed`；
- Training Picker 标为 `training_state=trainable`；
- 训练 Ground Truth 判定允许进入训练。

但 Quality Center 又把同一张图当成：

“没有标注”。

于是同一个素材在：

- Training Picker：可训练正式 GT；
- Material 页面：已标注/已处理；
- Quality Center：未标注；

三条主链出现直接冲突。

**对质量分的直接影响：**

`compute_quality()` 的：

`annotation_completeness`

权重为 20%，计算公式：

`annotated_images / image_count * 100`

假设本次训练素材：

- 80 张带目标 bbox；
- 20 张人工 confirmed_empty 负样本；

真实 GT 完成度应为：

100 / 100。

当前却计算：

80 / 100 = 80%。

因此综合质量分被无依据拉低。

同时 API 返回的：

`quality.annotated_images`

也会显示 80，而不是正式 GT 100。

**真实用户可达路径：**

当前前端：

`trainDataQuality424()`

和后续训练素材质量入口会：

`POST /api/v44/projects/{project_id}/data-quality`

并把：

`q.annotated_images`

直接展示为“已标注”。

Quality Center：

`GET /api/v44/projects/{project_id}/quality-center`

同样调用：

`_v44_dataset_quality(project_id)`

并展示：

- 已标注；
- 数据质量；
- 标注完整度雷达；
- overall score。

因此这是当前 UI 可见的错误，不是只存在于内部辅助函数。

**与 AUDIT-144 的区别：**

AUDIT-144 是：

Dataset List 的 `annotated_images` / “全标注、混合、未标注”分类错误。

AUDIT-146 是：

Quality owner 的 `annotation_completeness` 和 overall quality score 错误。

两者虽然根因都涉及 confirmed_empty，但修复 owner、影响指标和回归合同不同。

**建议最小修复：**

不要重新设计 Quality Center。

应让 `_v44_dataset_quality()` 把 canonical Annotation state 明确传给 `compute_quality()`，例如 candidate row 带：

`annotation_state = ann["annotation_state"]`

然后 quality 统计区分：

- ground_truth_images：annotated + confirmed_empty；
- positive_annotated_images：有有效 bbox；
- confirmed_empty_images：正式负样本。

`annotation_completeness` 应以 Ground Truth 完成度计算，而不是“有框率”。

box_validity / label_balance 仍只基于真实 bbox，不应给 confirmed_empty 伪造框。

**回归测试建议：**

至少覆盖：

- 80 annotated + 20 confirmed_empty → annotation completeness = 100%；
- annotated_images/ground_truth_images = 100；
- box_count 仍只统计真实 bbox；
- 20 confirmed_empty 不生成任何 label count；
- Training Picker 与 Quality Center 对同一批素材的 GT eligibility 一致；
- 纯 unannotated 素材仍正确降低 completeness。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-147 — Training Picker 把任意 confirmed_empty scope 都标成可训练，但最终 Snapshot 要求负样本覆盖本次全部标签；新增标签后会出现“选择器可选、提交必失败”

**级别：高**  
**模块：Training Picker / confirmed_empty / Annotation Scope / Training Input Freeze / Frontend-Backend Contract**

**现象：**

当前现代 Training Picker 对正式负样本的可训练判断只看：

`annotation_state == confirmed_empty`

以及“存在至少一个 scope reference”。

单行 projection：

`_public_picker_material()`

直接返回：

`annotated = annotation_state in {"annotated", "confirmed_empty"}`

以及：

`training_state = "trainable"`

只要 state 是 confirmed_empty，就不再验证：

`annotation_scope`

是否覆盖本次训练实际冻结的标签 schema。

Picker 的 Ground Truth SQL 同样只要求：

`annotation_state='confirmed_empty' AND scope_ref=1`

即只要该负样本曾经确认过至少一个标签，就进入 `require_ground_truth` 结果。

Selection Summary 的：

- eligible_count；
- eligible_total；

又来自：

`AnnotationRepository.training_ground_truth_summary()`

其中 confirmed_empty eligibility 同样是：

`MAX(... confirmed_empty AND scope_ref=1) = 1`

没有按当前训练标签 schema 做完整覆盖检查。

**但最终训练合同更严格，而且是正确的：**

`freeze_training_inputs()`

默认使用：

`_label_schema(project)`

冻结当前全部 active label schema。

随后：

`build_snapshot()`
→ `_lock_scope_to_schema()`

对 confirmed_empty 明确规定：

- scope 含 `*` → 展开为本次全部 schema；
- 否则必须覆盖 `schema_codes` 的每一个标签；
- 少任何一个都会 fail-closed：

`负样本 {image_id} 未确认本次算法的全部标签`

这样做是正确的，因为 YOLO 的空 label 文件语义是：

“本次训练的所有类别在该图片中均不存在”。

Partial negative scope 不能静默投影为所有类别的背景。

**真实可复现场景：**

1. 项目初始只有标签：
   `smoke`
2. 用户对图片 A 执行“确认无目标”；
3. AnnotationRepository 冻结：
   `annotation_state = confirmed_empty`
   `annotation_scope = ["smoke"]`
4. 后续项目新增标签：
   `fire`
5. 当前 active training schema 变为：
   `["smoke", "fire"]`
6. 打开现代 Training Picker；
7. 图片 A 仍被显示：
   `training_state = trainable`
8. Selection Summary 仍把 A 计入：
   `eligible_count / eligible_total`
9. 用户正常选择 A 并提交训练；
10. Training Freeze 执行：
    `_lock_scope_to_schema(...)`
11. 发现：
    `fire` 不在旧负样本 scope；
12. 创建/准备阶段失败。

所以前端和后端对同一素材给出相反结论：

- Picker：可训练；
- Snapshot：不可作为本次 schema 的负样本。

**为什么这不是训练准确性漏洞：**

最终 Snapshot 已经 fail-closed，所以不会把未确认的 `fire` 静默训练成背景。

因此这里不是数据污染，而是：

**训练创建前后的 eligibility contract 不一致。**

这仍然是高优先级主流程 Bug，因为用户在选择器中得到的是明确错误的“可训练”反馈。

**现有测试缺口：**

`tests/api/test_training_material_picker_api.py`

已经覆盖：

- confirmed_empty 能被当前页正式读取；
- confirmed_empty 可以成为 GT；
- selection summary 的 eligible_count；

但测试中的 confirmed_empty 没有构造：

“scope 只包含旧标签 A，同时当前项目 active schema 已扩展为 A+B”。

而 Picker Router 当前只接收：

- get_project；
- data_dir；

实际 eligibility 逻辑没有把 project active label schema 纳入计算。

另一方面：

`tests/api/test_training_ground_truth_gate.py`

已经保护最终 Snapshot 的严格合同：

confirmed_empty scope 必须覆盖当前 frozen schema。

所以两套测试各自是绿的，但跨层契约仍漂移。

**与已有问题的区别：**

- AUDIT-031：标签停用可能破坏 PREPARING 中的 inherited training contract；
- AUDIT-129：AI Annotation task 创建后标签 catalog 未冻结；
- AUDIT-144 / 146：confirmed_empty 被 Dataset/Quality 错算成未标注；
- AUDIT-147：Training Picker **反过来过度乐观**，把 partial-scope confirmed_empty 直接判为本次训练可用。

触发点和修复 owner 均不同。

**建议最小修复：**

不要放宽最终 Snapshot 的 fail-closed 合同。

应让 Training Picker 的 eligibility 与最终冻结使用同一套负样本 scope 规则。

最小方向：

1. Picker 获取当前训练标签 schema identity；
2. confirmed_empty 只有在：
   - scope = `*`；或
   - scope 覆盖本次全部 schema codes
   时，才显示 `trainable`；
3. Selection Summary 的：
   - eligible_count；
   - eligible_total；
   - pending_annotation_count
   使用同一个 schema-aware eligibility；
4. partial-scope confirmed_empty 应显示明确状态，例如：
   “负样本范围需重新确认：新增标签 fire 未确认”；
5. 如果 Training Create 支持显式 label contract/subset schema，则 Picker 必须按**本次实际 frozen schema**计算，而不是硬编码全项目标签；
6. 不要通过把旧 scope 自动扩成新标签来修复，那会制造未经人工确认的负样本。

**回归测试建议：**

至少增加：

- project schema=[smoke]，scope=[smoke] → trainable；
- 后续 schema=[smoke,fire]，旧 scope=[smoke] → Picker 不得 trainable；
- 同场景 eligible_count/eligible_total 不得把该图片算入；
- scope=["*"] → 对扩展后的 schema 仍可按既有 wildcard 合同展开；
- scope=[smoke,fire] → 可训练；
- Picker eligibility 与 `freeze_training_inputs()` 对同一图片/同一 schema 必须一致；
- 不得放宽 Snapshot 的 missing-scope 拒绝测试。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-148 — annotated partial-scope 正样本可穿透 Training Snapshot；未审核类别会被检测训练隐式当成背景，且 selected-label 投影还能伪造负样本 scope

**级别：高**  
**模块：Annotation Scope / AI Review / Structured Import / Training Label Contract / Training Projection / Snapshot / Training Accuracy**

**现象：**

当前 Annotation Ground Truth 已经把：

`annotation_scope`

作为“这张图实际确认过哪些 canonical 标签”的正式真相保存。

这不是单纯的展示/provenance 字段。

canonical AI Review 在：

`annotation_task_service._canonical_review_scope()`

中甚至明确写明：

> Resolve the labels this human-confirmed AI task actually reviewed.

AI 候选人工确认后，`commit_candidate_decisions()` 会把本次 `review_scope` 与已有 scope 合并，再写入 AnnotationRepository。

因此如果本次 AI 任务只审核：

`["smoke"]`

即使最终图片有 smoke 正框，它的正式 GT 也可以合法是：

```text
annotation_state = annotated
annotation_scope = ["smoke"]
boxes = [smoke ...]
```

结构化 COCO / VOC / YOLO 导入同样会把用户确认的：

`label_mapping.values()`

冻结成 `import_scope`，所以“项目已有 smoke + fire，但这批外部数据只确认 smoke”也是当前真实可达状态。

人工标注工作台与这两条路径不同：当前手工保存会把当时全部 active labels 写入 scope，因此手工全量审核通常不会触发本问题。

**真正的训练漏洞：**

`snapshots._lock_scope_to_schema()`

当前只对：

`state == confirmed_empty`

执行“scope 必须覆盖本次全部 schema codes”的 fail-closed。

对于任何：

`state != confirmed_empty`

包括正式 `annotated` 正样本，代码在检查 box label 没超出 schema 后直接：

`return raw_scope`

完全没有验证：

`schema_codes - annotation_scope`

是否为空。

所以：

```text
frozen schema = ["smoke", "fire"]

image A:
annotation_state = annotated
annotation_scope = ["smoke"]
boxes = [smoke]
```

会被 Snapshot 正常接受。

但目标检测训练文件只会写 smoke 框。

对 YOLO / 常规 object detection loss 来说，图片中没有标注出来的 `fire` 不会被理解成“这个类别尚未审核”，而会参与背景学习；如果图里真实存在 fire，就形成未经确认的 false negative。

即使图里恰好没有 fire，系统也没有任何 Ground Truth 证据证明 fire 已被确认不存在。

**Training selected-label projection 还有第二个更危险的同根路径：**

`training_label_tasks.project_training_rows()`

在 source state 为 `annotated` 时：

1. 如果仍有 selected_boxes：
   - 保留正框；
   - scope 只做：
     `(raw_scope ∩ allowed) ∪ selected_box_labels`
   - 仍不检查 allowed schema 是否被 scope 完整覆盖。
2. 如果所有正框都属于本次未选择标签：
   - `selected_boxes = []`
   - `excluded_boxes != []`
   - 代码会把该图片直接投影成：
     `annotation_state = confirmed_empty`
   - 并强行设置：
     `annotation_scope = sorted(allowed)`

这会制造一个更明确的假负样本。

例如：

```text
项目标签: smoke, fire

正式 GT:
scope = ["smoke"]
boxes = [smoke]

本次训练只选择 fire
```

当前 task-local projection 会：

- 删除/遮盖 smoke 区域；
- 把图片改成 confirmed_empty；
- 自动写：
  `scope = ["fire"]`

但用户从来没有确认过：

`fire 不存在`

也没有任何 AI/人工审核覆盖 fire。

这与“不能自动扩展 confirmed_empty scope”的既定安全合同直接冲突。

**真实调用链：**

路径 A — AI 自动标注：

`POST /api/v60/.../annotation-tasks`
→ AI Candidate
→ 人工 Review
→ `commit_confirmed_review()`
→ `_canonical_review_scope()`
→ `commit_candidate_decisions()`
→ `write_formal_annotations()`
→ AnnotationRepository partial `annotation_scope`
→ Training Create
→ `project_training_rows()`
→ `build_snapshot()`
→ `_lock_scope_to_schema()`
→ annotated partial scope 被接受
→ dataset materialization
→ YOLO label file
→ Training loss

路径 B — 当前结构化导入：

COCO / VOC / YOLO
→ 用户 label mapping
→ `_v18_confirmed_import_scope()`
→ `add_image_record(... annotation_scope=import_scope)`
→ AnnotationRepository
→ Training Create
→ 同上。

**为什么这是 Bug，而不是允许“每张图只标一个类”的产品选择：**

`annotation_scope` 已经被正式定义成“实际审核范围”。

如果系统希望把一张图片用于 `smoke + fire` 的 detection loss，则该图片必须有证据证明：

- smoke 已审核；
- fire 也已审核。

否则 label file 中缺失 fire 的语义无法表达“unknown / not reviewed”。

当前训练格式没有 per-class unknown mask。

因此把 partial-scope positive 直接送进多类别 loss，会把：

“fire 未审核”

错误压缩成：

“fire 不存在”。

这是训练 Ground Truth 语义损失，而不是单纯 UI 状态问题。

**用户真实可达场景：**

场景 1 — AI 单标签审核后进入多标签训练：

1. 项目已有：
   `smoke`
   `fire`
2. 用户创建 AI 标注任务，只显式选择：
   `smoke`
3. AI 在图片 A 发现 smoke；
4. 用户人工确认候选；
5. 正式 GT：
   `annotated + scope=["smoke"] + smoke box`
6. 创建 smoke + fire 训练；
7. Picker 把 A 当正式 annotated 素材；
8. Training projection 保留 smoke box；
9. Snapshot 不检查缺少 fire scope；
10. 训练真实开始；
11. fire 未审核区域被隐式当背景。

场景 2 — selected-label 投影伪造负样本：

1. 同一张 A 只审核 smoke；
2. 本次训练有效 schema 只包含 fire；
3. smoke box 被列入 excluded_boxes；
4. `project_training_rows()` 把 A 改成 confirmed_empty；
5. 自动生成：
   `scope=["fire"]`
6. Snapshot 因为 scope 已被伪造完整而通过；
7. A 作为 fire 负样本进入训练。

场景 3 — 外部数据导入：

1. 项目已有 smoke + fire；
2. 导入一批只映射/确认 smoke 的 COCO/VOC/YOLO 数据；
3. 导入结果保留：
   `annotation_scope=["smoke"]`
4. 后续 smoke + fire 训练仍可接受这些 annotated 图片；
5. 未审核 fire 被训练成背景。

**影响：**

- 多标签目标检测可能产生系统性 false negative；
- 新增/继承标签后，旧 partial-scope 正样本会污染新类别；
- 单标签 AI 审核数据混入多标签训练时，准确率可能被悄悄拉低；
- selected-label 训练可把“只审核了被排除标签”的正样本伪造成另一个类别的正式负样本；
- Snapshot 仍会成功，所以不像 AUDIT-147 那样 fail-closed；
- 用户看到训练成功，也很难从任务状态发现 Ground Truth 已被错误解释。

这是训练准确性主链问题。

**和已有 AUDIT 的区别：**

- AUDIT-085：标签 REMAP 与 Training Prepare 并发导致 mixed-generation projection；
- AUDIT-129：AI task 没冻结 live label catalog；
- AUDIT-144 / 146：confirmed_empty 的统计/质量展示错误；
- AUDIT-147：partial-scope **confirmed_empty** 被 Picker 错判可训练，但最终 Snapshot 会正确拒绝，因此不会污染训练；
- AUDIT-148：partial-scope **annotated 正样本** 在 Snapshot 仍被接受，并且 selected-label projection 还能主动伪造新负样本 scope，最终会真实进入 loss。

所以 148 不是 147 的重复。

147 是：

`Picker eligibility 漂移 → 提交失败`

148 是：

`Ground Truth scope 丢失 → Snapshot 仍成功 → 真实训练污染`

**现有测试为什么没有发现：**

`tests/unit/test_snapshots.py`

当前开头的 deterministic snapshot 测试反而明确固定了旧行为：

- schema 同时包含：
  `fire + smoke`
- train 图片只有 fire box；
- 其 inferred `annotation_scope=["fire"]`
- 测试要求 Snapshot 成功。

因此测试只验证：

“box label 属于 schema”

没有验证：

“图片 scope 覆盖 schema”。

另一方面：

`test_confirmed_empty_scope_is_locked_in_snapshot`

已经覆盖 confirmed_empty 的 scope 锁定，但没有给 annotated positive 做对应的 completeness test。

AI Review 测试又主要验证：

- review scope 被正确持久化；
- partial review 合并；
- Candidate → formal GT；

这些测试本身是对的，却没有继续串到 Training Snapshot，因而没有发现 partial scope 在训练层失去语义。

**建议最小修复方向：**

不要新增第二套 Annotation owner，也不要自动替用户扩 scope。

正确方向应继续复用：

AnnotationRepository
→ frozen training label contract
→ Snapshot

这条 canonical owner 链。

最小原则：

1. 对任何会进入普通 detection label file 的图片，不论：
   - annotated；
   - confirmed_empty；
   都必须证明 `annotation_scope` 覆盖本次 frozen effective schema；
2. `scope=["*"]` 继续按既有 wildcard 语义处理；
3. annotated partial scope：
   - 如果本次 effective schema 是其 scope 的子集，可以训练；
   - 如果 effective schema 含未审核标签，必须 fail-closed / 标成需补充审核；
4. `project_training_rows()` 不得因为：
   “所有现有正框都被排除”
   就自动把 source annotated 图片的 scope 改成全部 allowed labels；
5. 若 source scope 并未覆盖 allowed schema，则不能投影成 task-local confirmed_empty；
6. 不要自动把旧 scope 从：
   `["smoke"]`
   扩成：
   `["smoke","fire"]`；
7. Training Picker / selection summary 也应复用同一个 schema-aware scope eligibility，避免修完 Snapshot 后再次出现前端可选、后端拒绝；
8. 不要通过“忽略 annotation_scope”或“只要有任意正框就认为整图全类别已标完”来修。

**应新增回归测试：**

至少覆盖：

- schema=[smoke]，annotated scope=[smoke] + smoke box → 可训练；
- schema=[smoke,fire]，annotated scope=[smoke] + smoke box → 不得进入 Snapshot；
- schema=[smoke,fire]，annotated scope=[smoke,fire] + smoke box → 可训练，fire 的缺框才是有证据的负信息；
- scope=["*"] + 正框 → 按 wildcard 合同可训练；
- AI Review 只审核 smoke，训练 smoke+fire → Picker/Snapshot 均不得把该图片当完整 GT；
- AI Review 只审核 smoke，训练 schema 仅 smoke → 可训练；
- source annotated scope=[smoke] + smoke box，本次 selected schema=[fire] → 不得投影成 confirmed_empty scope=[fire]；
- structured import 只确认 smoke mapping，后续 smoke+fire 训练 → 不得静默进入 loss；
- 手工标注工作台写入完整 active scope 后，多标签训练保持可用；
- 不得放宽 AUDIT-147 对 confirmed_empty partial scope 的既有 fail-closed 测试。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-149 — Dataset DELETE 与 AI Review/Commit 没有共享生命周期 fence；并发提交可让删除半完成，或在 Material 删除后重新制造 orphan Annotation

**级别：高**  
**模块：Dataset lifecycle / AnnotationRepository / AI Candidate Review / Ground Truth Commit / MaterialRepository**

**现象：**

当前：

`DELETE /api/projects/{project_id}/datasets/{dataset_id}`

已经实现了较完整的可恢复删除：

- 对目标 dataset 加 coordination lock；
- 给 Material rows 写 delete claim；
- 把 AnnotationRepository 当前 GT 做 `prepare_delete()` backup；
- 把本地文件移动到 staging；
- 再执行 `finalize_delete()`；
- 删除 Material rows 与 dataset metadata；
- 失败时依赖 journal 做恢复。

但这个 Dataset delete coordination lock **不是 Annotation Ground Truth 的写 fence**。

canonical AI 人工审核提交走：

`commit_candidate_decisions()`
→ `write_formal_annotations()`
→ `app.write_annotations_many()`
→ `AnnotationRepository.upsert_many()`

这条链既：

- 不拿 Dataset delete lock；
- 不检查目标 image_id 对应 Material 仍存在；
- 也不检查该 image_id 是否正处于 dataset delete claim / delete backup 生命周期。

`AnnotationRepository.prepare_delete()` 当前只是持久化 backup，并不会阻止后续 `upsert_many()`。

因此 Dataset DELETE 与 AI Review/Commit 可真实并发。

**真实调用链 / 竞态 A — staging 期间 AI Commit：**

1. 用户对某批素材完成 AI 候选推理，任务进入人工审核；
2. 这些素材属于可删除的非 default dataset；
3. 用户/另一个操作触发 Dataset DELETE；
4. DELETE：
   - claim Material rows；
   - `prepare_delete(token, image_ids)` 备份当前 GT；
   - 释放 dataset coordination lock 后开始文件 staging；
5. 在 staging 期间，AI Review 点击“确认入库”；
6. `commit_candidate_decisions()` 正常调用 `AnnotationRepository.upsert_many()`；
7. 同一个 image_id 的 `content_digest` 发生变化；
8. Dataset DELETE 随后进入 `finalize_delete(token)`；
9. `finalize_delete()` 检测：
   `backup.content_digest <> annotations.content_digest`
   后抛出冲突。

问题在于 Dataset DELETE 的这一段 finalize 路径没有把这种并发 annotation conflict 纳入正常 rollback 分支。

当前显式 rollback 只覆盖“文件 staging 失败”。

因此该请求可以在：

- 文件已经被移到 staging；
- Material rows 仍带 delete claim；
- annotation backup/journal 仍存在；

的半删除状态异常退出，之后只能依赖后续 recovery 触发修复。

**真实调用链 / 竞态 B — finalize 后 AI Commit：**

更窄但语义更严重的窗口是：

1. Dataset DELETE 已完成：
   `AnnotationRepository.finalize_delete(token)`
   并删除目标 GT；
2. Material rows 也在 finalize 阶段从 MaterialRepository 移除；
3. Dataset metadata 尚未完成最终移除/cleanup；
4. AI Review/Commit 此时执行；
5. `AnnotationRepository.upsert_many()` 不验证 Material owner 是否存在，因此可重新插入相同 image_id 的正式 GT；
6. Material projection `MaterialRepository.patch()` 对已不存在的 Material 不会重新建立 Material identity；
7. Dataset DELETE 继续完成 metadata 删除并返回成功。

最终可留下：

`AnnotationRepository 有正式 GT`
但
`MaterialRepository 没有该 image_id`

即 orphan Annotation Ground Truth。

**为什么生产真实可达：**

现代 AI 标注的 canonical 主链本身就是：

AI Candidate
→ 人工 Review
→ Commit
→ AnnotationRepository。

Dataset 页面仍提供非 default dataset 的 DELETE。

AI review task 冻结的是 image IDs / Candidate truth，不会因为 Dataset delete 开始而自动取消或失效。

所以不需要依赖 legacy prelabel runtime，也不需要直接调用内部函数。

只要：

- AI task 已经对一批 Material 产出 Candidate；
- 这些 Material 属于随后被删除的数据集；
- Dataset DELETE 与人工 Commit 时间重叠；

即可进入竞态。

**影响：**

- Dataset 删除请求可能异常停在半删除 journal；
- 文件可能已经进入 staging，但 Material/Annotation truth 尚未完成一致恢复；
- AI task 可以在 Dataset 已删除后重新制造 orphan Annotation；
- Annotation summary / label reference / integrity audit 可能统计到无 Material owner 的 GT；
- 后续标签治理、Training preflight、Material Integrity 会看到分裂真相；
- 用户可能看到“数据集删除成功”，但后台 GT 已被另一个合法操作重新写回。

**和已有 AUDIT 的区别：**

- AUDIT-019：Dataset DELETE 与 **TRAINING_PREPARE** 缺少 active selection fence，导致尚未 freeze 的训练素材被删；
- AUDIT-084：MaterialBatch DELETE_SOURCE 与 **Training admission** 是单向 TOCTOU；
- AUDIT-090：VideoFrameHandler 自己先写 Annotation/对象、后写 Material，取消/异常可留下孤儿；
- AUDIT-102：合法 Annotation 写之间的 GT commit 与 Material projection 可逆序；
- AUDIT-149：Dataset DELETE 自己的 delete transaction/journal 与 **AI Review formal GT commit** 不共享 lifecycle fence，导致删除半提交或删后 GT 复活。

所以 149 是独立的 deletion-vs-annotation writer race，不是 019/084/090/102 的重复。

**现有测试为什么没有发现：**

现有 Dataset deletion 测试主要覆盖：

- 文件 staging 失败后的 rollback；
- delete journal recovery；
- Annotation backup/finalize/restore；
- dataset write admission；
- Training PREPARING dependency。

AnnotationRepository delete 测试也验证了：

- backup digest conflict 会 fail-closed；
- newer GT 不会被旧 delete token 静默删除。

这些单组件测试本身正确。

缺失的是跨 owner 并发测试：

`Dataset DELETE prepare/staging/finalize`
与
`AI Review → AnnotationRepository.upsert_many`

交错执行。

特别没有覆盖：

- prepare_delete 后 annotation digest 改变时 Dataset DELETE 是否完整 rollback；
- finalize_delete 后、metadata cleanup 前 annotation 再写入；
- AI Commit 是否必须验证 Material identity 仍存在。

**建议最小修复方向：**

不要新增第二 Annotation owner，也不要让 Dataset delete 直接管理 AI task internals。

应复用现有 canonical owners，补一个共享生命周期 fence / delete claim contract：

1. Dataset DELETE 对 claim 的 image_ids 建立可被 AnnotationRepository formal write 检查的 deletion fence；
2. 所有正式 Annotation 写 owner：
   - 手工标注；
   - AI Review Commit；
   - Storage Import/Rescan；
   在 commit 前必须 fail-closed 检查 image_id 仍有 Material owner，且不处于 active delete claim；
3. 或将 Material existence + delete claim 作为 AnnotationRepository formal-write admission 的统一 guard，但不要新增第二 GT repository；
4. Dataset delete finalize 遇到 Annotation conflict 时必须走明确 rollback/recovery 状态，而不是从 staging 状态裸异常退出；
5. 删除成功后不得允许旧 AI review task 把已删除 image_id 重新写成正式 GT；
6. 不要靠“前端隐藏删除按钮”解决，后端必须有 fence；
7. 不要自动把 AI task 判成功并丢弃用户审核结果；应返回明确 conflict，要求刷新素材范围。

**应新增回归测试：**

至少覆盖：

- Dataset delete `prepare_delete` 后，AI Commit 修改同 image_id → delete fail-closed 且 Material/文件/GT 全部一致恢复；
- Dataset delete 已 finalize Material/GT 后，旧 AI Commit → formal annotation write 被拒绝，不得创建 orphan Annotation；
- AI Commit 先完成，Dataset delete 后开始 → delete 可基于最新 GT 正常备份并完成；
- Dataset delete 先完成，AI review 页面晚点提交 → 返回明确 409/业务冲突；
- 手工 Annotation save 与 Dataset delete 的相同竞态也走同一 guard；
- Storage Rescan / structured import formal Annotation write 不得绕过同一 deletion fence；
- crash recovery 后 delete claim 清理完成，正常 Annotation 写恢复可用；
- 不放宽现有 AnnotationRepository digest conflict fail-closed 测试。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-150 — Training Submit readiness 忽略服务端 eligible_count；全是“已清洗待标注”素材也可创建任务，TRAINING_PREPARE 随后必失败

**级别：中高**  
**模块：Training Create / TrainingMaterialSummaryRuntime / TrainingSubmitRuntime / TRAINING_PREPARE / Selection Truth**

**现象：**

当前训练创建页面已经有一套服务端权威素材摘要：

`POST /api/v62/projects/{project_id}/training-materials/selection-summary`

它会对当前 draft 中用户实际选中的 image_ids 返回：

- `selectable_count`
- `eligible_count`
- `pending_annotation_count`
- `label_codes`
- `eligible_total`

前端 `TrainingMaterialSummaryRuntime` 也已经消费这份真相，并在创建弹窗里显示：

`可直接训练 X / 待标注 Y`

因此页面在提交之前其实已经知道：

> 本轮是否至少存在一张可进入监督训练的正式 Ground Truth 素材。

但真正控制“开始训练”按钮的：

`trainingSubmitReadiness()`

目前只检查：

- algorithmId；
- benchmark loading/error；
- `materialIds.length >= 2`；
- iteration base 是否 blocked；
- submitting 状态。

它完全不读取：

`TrainingMaterialSummaryRuntime.summaryFor(...).eligible_count`

也不要求 server summary 已完成。

所以只要用户勾了至少 2 张素材，即使全部都是：

`processed + unannotated`

按钮也会显示可提交。

**后端 canonical 合同却明确不同：**

`resolve_training_selection()`

允许“已清洗待标注素材”保留为 task intent：

- 它们进入 `pending_annotation_image_ids`；
- 不会被伪造成空 YOLO label；
- 不会进入当前 effective supervised train set。

但是它明确要求：

`effective_train`

至少有 1 张正式 GT。

如果全部所选素材都只是 pending annotation，则固定抛出：

> 已清洗未标注素材可以选入训练任务，但本轮没有任何正式标注素材可用于监督训练；请先完成至少一部分人工标注或 AI 标注审核确认

因此：

```text
UI readiness: 可提交
server selection-summary: eligible_count = 0
POST /train/start: 202 已受理
TRAINING_PREPARE: 必失败
```

**真实调用链：**

用户在 canonical Training Material Picker 选择 2+ 张已清洗未标注素材  
→ `TrainingMaterialSummaryRuntime.refresh()`  
→ server summary 已返回：
`eligible_count=0`
`pending_annotation_count=N`  
→ 创建弹窗也显示“可直接训练 0 / 待标注 N”  
→ `TrainingSubmitRuntime.updateReadiness()`  
→ `trainingSubmitReadiness()` 只看 `materialIds.length >= 2`  
→ “开始训练”仍启用  
→ `POST /api/v12/projects/{project_id}/train/start`  
→ `_enqueue_explicit_training()`  
→ 先创建父 `TRAINING`  
→ 再创建 `TRAINING_PREPARE`  
→ 返回 HTTP 202  
→ 前端关闭训练弹窗并提示“训练任务已进入后台队列”  
→ Prepare Worker  
→ `resolve_training_selection()`  
→ `effective_train=[]`  
→ 必然失败。

**为什么这是 Bug：**

“已清洗未标注素材可被选择”本身不是 Bug。

这是当前有意设计：

- 用户可以提前把待标注素材纳入 task intent；
- 系统会把它们保留在 `pending_annotation_image_ids`；
- 但绝不能把它们当负样本；
- 当前真正训练只消费 formal GT。

Bug 是：

> 前端明明已经从 canonical backend 拿到 `eligible_count=0`，却没有把这份真相接入唯一 Submit readiness owner。

因此这是明确的跨层 admission drift。

用户得到的是“任务受理成功”的交互，然后后台立即进入一个本来在提交前就能确定的失败。

**用户真实可达场景：**

1. 导入一批图片；
2. 完成清洗，素材变为 processed；
3. 尚未人工标注，也未完成 AI 候选审核；
4. 创建训练任务；
5. 选择 2 张或更多这些素材；
6. 页面显示：
   `可直接训练 0 / 待标注 N`
7. 但“开始训练”按钮仍可点击；
8. 点击后弹窗关闭、任务中心出现任务；
9. TRAINING_PREPARE 随后失败。

同样适用于：

- 100 张 pending-only；
- 1k / 10k / 20k pending-only；
- 迭代训练已有 inherited labels，但本次所选图片没有任何 formal GT。

即使存在上一版本继承标签，也不能凭空把未标注图片变成监督训练数据，所以后端仍会拒绝 effective_train 为空。

**影响：**

- 制造“假成功创建 → 后台秒失败”的用户体验；
- 用户容易误以为 Worker/GPU/资源调度故障；
- 产生无意义 TRAINING + TRAINING_PREPARE Durable Task 历史；
- 任务中心、CI/运维统计会累积本可在前端 admission 阶段避免的失败；
- 大规模项目中可能重复创建多个注定失败的 Prepare；
- 页面展示的 `eligible_count` 与唯一 submit owner 实际 admission 互相矛盾。

**和已有 AUDIT 的区别：**

- AUDIT-053 / 054：split/benchmark 请求合同不一致；
- AUDIT-147：partial-scope confirmed_empty 被 Picker 计为 eligible，但 Snapshot 最终拒绝；
- AUDIT-148：partial-scope annotated 正样本错误穿透 Snapshot，真实污染训练；
- AUDIT-150：即使 `eligible_count=0` 本身完全计算正确，Submit readiness 仍忽略它，让 pending-only selection 创建一个必失败的 Prepare。

所以 150 不是 147 的延伸。

147 是“eligible truth 算错”。

150 是“eligible truth 已算对，但提交 owner 不消费”。

**现有测试为什么没有发现：**

`tests/frontend/training-submit.test.mjs`

当前测试甚至明确写：

`submit readiness depends only on canonical draft, base and submitting state`

并固定：

- 默认 2 张 material → ready=true；
- 1 张 material → ready=false。

测试没有提供任何：

- material summary；
- eligible_count；
- pending_annotation_count。

所以它只验证“选了几张”，没有验证“这些素材是否至少有一张可用于监督训练”。

另一方面：

`tests/frontend/training-material-summary-runtime.test.mjs`

只验证 summary runtime：

- 请求 selection-summary；
- 显示 pending_annotation_count；
- 显示“可直接训练 / 待标注”。

两套测试各自都绿，但没有跨模块合同测试：

`TrainingMaterialSummaryRuntime → TrainingSubmitRuntime readiness`。

后端 resolve_training_selection 的 fail-closed 逻辑本身是正确的，不应放宽。

**建议最小修复方向：**

不要把 pending 素材禁止选择，也不要把未标注素材自动当负样本。

最小方向应是：

1. 继续保留 TrainingMaterialSummaryRuntime 作为当前 selected-material summary owner；
2. TrainingSubmitRuntime readiness 必须消费与当前 selection signature 匹配的 server summary；
3. summary 尚未 ready 时：
   - submit 应暂时不可用；
   - 显示“正在核验本次训练素材”；
4. `eligible_count <= 0` 时：
   - 禁止提交；
   - 明确提示“至少需要 1 张正式标注/确认负样本素材”；
5. `eligible_count > 0` 且同时存在 pending annotation 时：
   - 仍允许提交；
   - pending 素材继续按现合同保留，不进入当前监督 Snapshot；
6. 不要在浏览器自行重新判断 annotation_state；
7. 不新增第二套 selection owner；
8. 后端 `resolve_training_selection()` 的 fail-closed 保持不变，作为最终防线。

**应新增回归测试：**

至少覆盖：

- 2 张 processed + unannotated，summary eligible_count=0 → submit disabled；
- 10k pending-only → submit disabled，不创建 Durable Task；
- 1 张 formal GT + N 张 pending，eligible_count=1 → submit allowed；
- summary 仍 loading / selection signature stale → submit disabled；
- 切换选中素材后旧 summary 不得继续解锁按钮；
- inherited labels 存在但 selected materials eligible_count=0 → 仍不得提交；
- eligible_count>0 的正常首次训练/迭代训练保持可提交；
- 后端 pending-only 仍继续 fail-closed，不放宽 resolve_training_selection。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-151 — Training Create 不提交用户看到的 baseVersionId；弹窗打开后 current version 前进时可静默改用新版本继承标签/权重

**级别：高**  
**模块：Training Create / Iteration Base / Inherited Labels / Admission CAS / Training Lineage**

**现象：**

当前训练创建弹窗明确维护 `trainingDraft.baseVersionId`，并用它展示“上一版本继承”标签和当前迭代基础版本。TrainingLabelRuntime 的继承标签预览也会请求 `/api/v62/projects/{project_id}/training-labels/inherited?...&base_version_id={draft.baseVersionId}`。

但最终构造训练请求的 `trainingDraftToRequest()` 没有把 `baseVersionId` 放进 POST payload；当前 `TrainReq` 也没有 `base_version_id` / `expected_current_version_id` 这样的 admission CAS 字段。因此用户看到并确认的 base identity 在浏览器→后端边界被丢失。

后端 `POST /api/v12/projects/{project_id}/train/start` → `_enqueue_explicit_training()` 会重新读取 live algorithm，并直接以 `resolve_current_version_id(asset_algorithm)` 作为 `reference_version_id`。`_algorithm_version_reference_fence(... require_current=True)` 只能保证后端受理过程中这个 live current 不再变化，不能证明它等于用户打开弹窗时看到的版本。后续 `resolve_training_label_contract()` 又通过 `_iteration_base()` / `choose_algorithm_iteration_base()` 按当前算法状态选择实际 base。

**真实调用链：**

用户 A 在 current=v1 时打开训练弹窗 → draft.baseVersionId=v1 → UI 展示 v1 inherited labels → 期间用户 B/另一任务把 current 推进到 v2 → A 浏览器尚未刷新 algorithms state → A 点击开始训练 → `TrainingDraftRuntime.sync()` 仍基于浏览器 stale state 得到 v1 → `trainingDraftToRequest()` 丢弃 baseVersionId → server 读取 live current=v2 → 请求不会因 v1 已过期而 409 → Prepare 按 v2 继承 label schema / verified weights 并冻结 lineage。

首次训练同样存在：用户打开弹窗时无版本，以为是 mother-model first run；提交前另一个任务先生成 v1；请求没有“expected no base”的 CAS，后端可静默把它改成基于 v1 的 iteration。

**为什么是 Bug：**

它改变的不只是展示，而是训练真实语义：inherited labels、effective label schema、base model weights、requested-new-label 判定和 lineage 都可能与用户确认时不同。当前代码冻结的是“服务器受理时的 current”，不是“用户确认时的 expected base”。

**用户真实可达场景：**

并发训练、自动迭代、另一个客户端完成训练、回退/版本推进都可能在训练弹窗打开到点击提交之间改变 current version。无需 legacy path，也无需内部 API。

**影响：**

- 用户看到 v1 标签却真实按 v2 训练；
- 首训可静默变迭代；
- 新增标签在 v1/v2 下可能从 new 变 inherited；
- 权重初始化来源发生变化；
- lineage 虽记录实际 base，却无法证明该 base 是用户确认的版本；
- 并发越多越容易发生。

**和已有 AUDIT 的区别：**

- AUDIT-139 是训练已经冻结 base 后，在 completion/attach 阶段对 current_version_id 做 CAS，防止两个 child 都覆盖 current；
- AUDIT-151 是更早的 create admission：用户确认的 expected base 根本没有进入请求，任务一开始就可能选择另一个 base。

即使最终归档 CAS 完全正确，也无法知道“实际冻结的 v2 并不是用户提交时看到的 v1”。

**现有测试为什么没有发现：**

`training-draft.js` 测试验证 draft 内存在 baseVersionId，但 `trainingDraftToRequest()` 测试没有要求该身份进入 request。后端 version fence / completion CAS 测试验证 live-current 原子性和 finalization stale protection，却没有覆盖 browser expected v1 vs server live v2 的 admission mismatch。Inherited-label preview 测试也没有把 preview identity 串到 train/start。

**建议最小修复方向：**

不要新增第二套 iteration-base owner。继续由现有 `choose_algorithm_iteration_base / resolve_training_label_contract` 作为实际 base 解析 owner，但补 admission expectation：

1. Training Draft 请求显式提交 `expected_base_version_id`（或等价 CAS 字段）；
2. 首训也要显式表达 expected no-base；
3. `_enqueue_explicit_training()` 在现有 algorithm-version fence 内比较 browser expected base 与 canonical current；
4. 不一致直接 409，要求刷新并重新确认继承标签；
5. 比较成功后才允许创建 TRAINING / TRAINING_PREPARE；
6. frozen payload / label contract / lineage 继续记录这个同一 base；
7. Benchmark reuse 自己的 version/scope 校验不能替代通用 base CAS；
8. 不要靠前端定时刷新掩盖，后端必须 CAS。

**应新增回归测试：**

- expected v1 + server current v1 → 可创建；
- expected v1 + server current v2 → 409，且不创建 TRAINING/PREPARE；
- expected no-base + server no-base → 首训可创建；
- expected no-base + server 已有 v1 → 409，不得静默变迭代；
- expected v1 + server rollback 到其它版本 → 409；
- inherited preview v1 后 current 变 v2，再提交必须拒绝；
- Benchmark reuse 同时通过 benchmark identity 与通用 base CAS；
- idempotent task replay 必须保持同一 expected base identity；
- completion CAS 现有测试继续保留。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-152 — CLEAN retry 保留旧 succeeded 结果却不校验当前素材 hash；Storage Rescan 换内容后可把旧清洗判断应用到新图片

**级别：高**  
**模块：Cleaning / MaterialBatch Retry / Storage Rescan / Material Identity / Training Candidate Accuracy**

**现象：**

canonical CLEAN MaterialBatch 的 retry 语义是 resume：`context.task.retry_of` 时只把 `failed/running` selection row 复位为 pending，已 `succeeded` 的 row 保持 succeeded。对应 `clean_results` 也继续保留；`clean_batch()` 只有在 row 被重新处理时才 materialize 当前素材并计算/验证新 SHA。

这在“同一个 material_id 的内容不可变”时是合理的 crash recovery。但当前 Storage Import/Rescan 明确允许对相同 `(storage_source_id, object_key)` 复用原 material_id，并在 indexing 时覆盖该 Material 的 `content_sha256 / size_bytes / etag / width / height`。因此 Material identity 并不保证 content generation immutable。

**真实调用链：**

1. CLEAN 对 image A(H1) 扫描成功，`selection.state=succeeded`，`clean_results.metrics.sha256=H1`；同批其它图片失败，所以任务成为 PARTIAL_SUCCESS/failed compat。
2. 外部对象同 source/key 内容变化为 H2；用户执行 canonical Storage Rescan，系统复用 A 的原 material_id，并把 MaterialRepository 的 content_sha256 等更新为 H2。
3. 用户对失败清洗重试。生产 UI/上传批次路径是真实可达的：v47 将 PARTIAL_SUCCESS 映射成 `failed / 部分失败，请重试`；上传批次使用确定性 clean_task_id，失败后再次保存决策时 `_v62_publish_clean_compat()` 会对同一 Durable task 调 `repository.retry(task_id)`。
4. MaterialBatch Handler 看到 retry_of，只复位 failed/running；A 仍 succeeded，因此不会重新进入 `clean_batch()`，也不会比较 H1 与当前 H2。
5. 最终详情仍把旧 A 的 clean_results 作为当前清洗结果；`_v47_durable_clean_results()` 只把 live Material 的 URL/annotation 信息叠到旧 result 上，不校验 result.metrics.sha256。
6. 用户确认清洗时，`v47_confirm_clean()` 同样不核对 source hash：用户按旧结果选择 delete_ids 可删除现在的 H2；而 frozen selection 中仍存在的图片都会被标记 `processing_status=processed / cleaned_at`。

**影响：**

- 旧 H1 的模糊/亮度/损坏/重复判断可被错误应用到新 H2；
- H1 被判坏图时，用户可能删除已经换成正常内容的 H2；
- H1 被判正常时，H2 即使已损坏也可能直接被确认 processed；
- near/exact duplicate 的旧关系也可能与当前素材内容不一致；
- Training Picker 后续会把 `processed` 当清洗完成，导致未经当前内容清洗的数据进入训练候选；
- 状态、task generation 都可能完全正常，因此问题很难从任务状态察觉。

**和已有 AUDIT 的区别：**

- AUDIT-086：清洗确认时删除失败项仍被错误标记 processed/cleaned；
- AUDIT-095：Storage Import CandidateStore 跨 retry generation 保留旧 candidate/hash；
- AUDIT-097：Material Integrity 长扫描缺 revision fence；
- AUDIT-152：Cleaning 自己的 succeeded result 被 resume 语义永久保留，而同 material_id 的 content generation 可被 Rescan 更新，导致旧清洗证据作用到新内容。

**现有测试为什么没有发现：**

Cleaning recovery 测试主要验证 succeeded row 不重复执行、failed row 可重试，这恰好固定了当前 resume 行为；Storage Rescan 测试则验证同 storage reference 可以更新现有 material metadata。两边没有跨模块测试“CLEAN partial success → rescan same material to new hash → retry/confirm”。Remote Cleaning 的 generation commit 反而会逐项比较 source_sha256，但本地 retry 没有对应 fence。

**建议最小修复方向：**

不要取消 resume，也不要新增第二 Cleaning owner。应把 CLEAN 成功证据绑定 source generation：

1. clean_results 已有 metrics.sha256，可把它作为 succeeded result 的 source identity；
2. retry 开始时，对所有 succeeded rows 批量比较 result source_sha256 与当前 Material content_sha256；
3. hash 已变化的 row 必须重置 pending，并清理该 row 旧 clean_result/hash-index contribution 后重新分析；
4. confirm 前再次做最终 hash fence，避免 scan/retry 完成后到人工确认之间又发生 Rescan；
5. delete_ids 只允许删除与当前 content hash 一致的 reviewed result；
6. 未变化的 succeeded row 继续复用，保持大批量 retry 性能；
7. Remote Cleaning 与 Local Cleaning 应复用同一 source-evidence 语义，不另造结果 owner。

**应新增回归测试：**

- H1 succeeded + H2 failed → material H1→H3 rescan → retry 时 H1 row 必须重新扫描；
- 未变化 succeeded row retry 时不得重复分析；
- result H1、current H2 时 confirm 必须 409/要求重新清洗，不得 mark processed；
- stale result 的 delete_ids 不得删除新 H2；
- same source/key rescan 更新 content_sha256 后，clean_result_task_id 不得被当成当前内容有效证据；
- 10k/20k retry 校验必须批量化，不能逐条 N+1。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-153 — CLEAN PARTIAL_SUCCESS 明确提示“请重试”，但 canonical 清洗页面没有 retry 入口；用户只能重新创建整批任务

**级别：中高**  
**模块：Cleaning UI / MaterialBatch Retry / Partial Success / Frontend-Backend Contract**

**现象：**

canonical CLEAN MaterialBatch 后端已经实现 item-level retry：`POST /api/v62/projects/{project_id}/material-batches/{task_id}/retry` 允许 `FAILED / PARTIAL_SUCCESS / CANCELLED / BLOCKED_*` 重新排队；CLEAN retry 时只把 `failed/running` selection rows 重置为 pending，已 succeeded rows 保持不动。

v47 清洗兼容投影也明确把 Durable `PARTIAL_SUCCESS` 映射成：

- `status = failed`
- `status_text = 部分失败，请重试`

说明产品合同本身要求用户对部分失败任务执行 retry。

但当前 canonical 清洗页面没有暴露这一动作。

`cleanTaskRow427()` 的操作列只有：

- 始终显示“详情”；
- `status==='awaiting_confirmation'` 时额外显示“审计结果”。

FAILED / PARTIAL_SUCCESS 没有“重试”按钮。

`showCleanTaskProgress429()` / 清洗详情同样没有 retry 动作。

仓库虽然已经存在 `window.retryMaterialBatch62()`，会调用 canonical MaterialBatch retry endpoint，但清洗 UI 没有任何引用把它接到用户操作。

**真实调用链：**

1. 用户创建 1k/10k CLEAN；
2. 大多数图片成功，少量图片因对象存储瞬断、分析超时、临时 I/O 等失败；
3. Durable task 结束为 PARTIAL_SUCCESS；
4. 清洗列表显示“部分失败，请重试”；
5. 用户打开任务行或详情；
6. 页面只有“详情/关闭”，没有 retry；
7. 用户无法使用后端已经实现的失败项增量恢复；
8. 实际只能重新创建一个新的整批 CLEAN，导致已成功素材再次被读取和分析。

**影响：**

- 临时错误无法从正常 UI 恢复；
- 少量失败会迫使 1k/10k/20k 整批重扫；
- 重复对象读取、图片解码、dHash/模糊/亮度等计算；
- 远程 Agent Cleaning 同样失去 item-level resume 的用户入口；
- 状态文案“请重试”与操作能力矛盾；
- 用户容易误判系统卡住或只能删除任务重来；
- 新建整批任务增加重复历史、日志和结果存储。

**和已有 AUDIT 的区别：**

- AUDIT-038：确认接口缺少运行状态 guard；
- AUDIT-049：Cleaning preempt/cancel 语义；
- AUDIT-050：详情全量 hydrate；
- AUDIT-086：删除失败后仍推进 processed；
- AUDIT-152：retry 复用旧 succeeded result 时未绑定当前 content hash；
- AUDIT-153：即使 retry 本身存在，canonical 清洗 UI 根本没有把 retry action 暴露给用户。

所以 153 是 frontend action owner 缺失，不是 152 的 retry data-integrity 问题。

**建议最小修复方向：**

不要新增第二 Cleaning retry owner，直接复用现有 MaterialBatch runtime/endpoint：

1. Cleaning view 增加统一 `canRetry`；
2. 对后端允许重试的 FAILED / PARTIAL_SUCCESS / CANCELLED / BLOCKED 状态显示“重试失败项”；
3. 点击后调用同一 task_id 的 canonical `/material-batches/{task_id}/retry`；
4. 不新建第二 CLEAN task；
5. retry 后继续由 PollRegistry 接管轮询；
6. succeeded rows 保持 resume 语义，数据一致性同时按 AUDIT-152 加 hash fence；
7. SUCCEEDED / awaiting_confirmation / done 不显示 retry；
8. status text 与 canRetry 由同一 helper/后端 truth 驱动，避免再维护重复枚举。

**应新增回归测试：**

- PARTIAL_SUCCESS → 页面显示“重试失败项”；
- 点击后只调用 canonical retry endpoint；
- 同一 task_id 从 terminal 回 QUEUED/RUNNING；
- succeeded rows 不重跑，仅 failed/running rows重试；
- FAILED/CANCELLED/BLOCKED 的按钮 eligibility 与后端一致；
- SUCCEEDED/awaiting_confirmation 不显示 retry；
- 10k 中 2 项失败时 UI retry 不重新创建任务；
- retry 后仅一个 PollRegistry owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-154 — External auto-publish 每 30 秒无界重扫全部成功版本并重新 SHA256 全部交付文件；版本/转换历史增长后形成常驻磁盘 I/O 放大器

**级别：中高**  
**模块：External Publish / Recovery Worker / Artifact Discovery / Filesystem I/O / Scale**

**现象：**

`external_algorithm_publish_router()` 启动常驻 auto-publish worker。没有显式 wake 时仍每 30 秒执行 recovery scan。

`run_auto_publish_once()` 会遍历：全部项目 → 全部 EXTERNAL/CHANGLIAN 算法 → 该算法全部训练成功且 artifact_verified 的历史版本。这个本地扫描没有 cursor、dirty set、generation watermark 或 batch budget。

对每一个候选版本都会调用 `publication_requires_sync()`。对于已经 `PUBLISHED` 的正常版本，它继续调用 `discover_artifacts()`；后者会：

- 扫描项目 `deploy/jobs/*/job.json`；
- 扫描 `deployment/jobs/*/job.json`；
- 对每个 job 做 algorithm/version identity 过滤；
- 读取 original model；
- 读取所有成功 conversion output；
- 对每个实际文件执行 `_sha256(path)` 全文件哈希；
- 再查询 artifact mapping / ModelArtifact / public_url truth。

因此即使系统完全没有新训练、没有新转换、远端也没有 drift，已发布历史仍会每轮重新做目录扫描和大文件哈希。

代码虽然给 **远端 reconciliation** 设置了 `DEFAULT_REMOTE_RECONCILE_BATCH` budget，但这个 budget 只限制 provider 远端对账，不限制前面的全项目/全版本本地 discovery + SHA256。

**真实生产可达：**

只要外部平台模式开启、auto publish ready，router worker 就常驻执行；不需要用户点击页面。训练成功版本和转换产物正是平台长期累积的数据，因此该路径会随正常使用持续放大。

例如一个项目累计 200 个已发布版本，每版 original + ONNX + RKNN；即使 30 秒内没有任何变化，worker 仍会反复定位这些版本的 conversion job，并重新读取/哈希数百个模型文件。多个项目时继续线性叠加。

**影响：**

- 大模型/PT/ONNX/RKNN 文件被周期性全量读取，产生持续磁盘带宽和 page-cache 压力；
- 与 Training / Conversion / Material Import 争抢 I/O；
- SATA/机械盘/网络盘环境更明显；
- deploy job history 增长后 `_conversion_jobs()` 对每个版本重复扫描同一目录，形成 versions × jobs 的放大；
- worker 一轮耗时越长，发布新版本的响应延迟也会被旧历史扫描拖慢；
- 多项目长期运行时后台成本与“是否有新发布工作”脱钩。

**和已有 AUDIT 的区别：**

- AUDIT-110：新畅联主数据 auto-sync 按项目重复拉同一全局 master data；
- AUDIT-111：Training GET preflight 把完整 reconciliation 放进用户关键路径；
- AUDIT-119：Training SSE 无变化也高频读 job.json；
- AUDIT-154：External Publish 自己的 30 秒 recovery worker 对全部已发布历史反复做本地 conversion discovery + 大文件 SHA256。

**建议最小修复方向：**

不拆分 External Publish owner，也不要取消 recovery scan。应增加可恢复的 dirty/revision truth：

1. Training completion / Conversion completion 继续通过现有 request marker/wake event 标记具体 version dirty；
2. 正常运行优先处理 dirty publication/version queue；
3. recovery scan 只做轻量 metadata/index 检查，并有明确 batch/cursor budget；
4. ModelArtifact 已有 sha256/size identity 时不要周期性重新读取整个文件；只在 source metadata/revision 变化或完整性复核时重算；
5. conversion job 应有按 algorithm_id+version_id 可索引的 canonical artifact lookup，避免每个 version 重扫整棵 deploy/jobs；
6. 远端 reconcile budget 与本地 discovery budget 都要 bounded；
7. crash recovery 仍可最终覆盖全部历史，但分批推进，不能每 30 秒全量 O(history)。

**应新增回归测试：**

- 100/1k published versions 无变化时单轮只做 bounded recovery page；
- PUBLISHED 且 artifact revision 未变时不得重新打开模型文件计算 SHA256；
- 一个新 conversion 完成只 dirty 对应 version；
- recovery cursor 跨轮最终覆盖历史；
- 新 publish request 不被大历史扫描长期饿死；
- 多项目规模下单轮 filesystem reads 有明确上限。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-155 — Durable MATERIAL_IMPORT 已实现安全取消，但服务器目录/ZIP/对象存储导入 UI 完全没有取消入口；大任务只能后台跑到底

**级别：中高**  
**模块：Storage Import / MATERIAL_IMPORT / Cancellation / UploadTaskCenter / Frontend-Backend Contract**

**现象：**

当前 `StorageImportHandler` 是 Durable `TaskKind.MATERIAL_IMPORT`，并且在真实执行链中多次主动检查 `context.cancel_requested()`：扫描对象、解包、远程 publisher、候选绑定、标签映射、Annotation/Material commit 前后、索引循环等都具备安全停止点。

平台还已经提供统一 canonical API：

`POST /api/v62/projects/{project_id}/tasks/{task_id}/cancel`

会进入 `TaskRepository.request_cancel()`，必要时还会安全终止已登记的本地进程。

但当前服务器素材导入 UI 没有把这套能力暴露给用户。

`serverImportView()` 只返回 `active / canConfirm / terminal`，没有 `canCancel`。

`renderImportTask()` 只会渲染：

- 进度/状态；
- 待确认时“确认建立索引”；
- 失败信息。

没有“取消任务/停止导入”。

`StorageImportProgressRuntime` 只负责 track/stop polling；`stop()` 只是停止浏览器轮询并 handoff 到 UploadTaskCenter，不会取消后台 Durable Task。

`UploadTaskCenter` 当前对 storage-import 也只展示任务状态，没有 cancel action。

**真实调用链：**

用户启动 server ZIP / directory scan / remote storage scan → 创建 Durable MATERIAL_IMPORT → 弹窗开始轮询 → 用户发现路径/格式/范围选错，或任务耗时过长 → 关闭弹窗只停止 focused polling → UploadTaskCenter 继续显示后台任务 → 页面没有任何 cancel 按钮 → Worker 仍继续扫描/下载/解包/检查/等待确认。

即使任务正在 `QUEUED / WAITING_RESOURCE / RUNNING`，用户也无法通过正常产品入口调用系统已经存在的 canonical cancel。

**影响：**

- 10k/20k 对象存储扫描选错后无法停止；
- 大 ZIP 解包/远程 Agent 导入会继续消耗网络、磁盘、CPU；
- 错误任务会继续占用 Storage/Agent 队列和资源；
- 用户关闭弹窗容易误以为已经停止；
- 后端大量 cancellation checkpoints 实际失去产品价值；
- 运维只能手工调用 API 或等待任务自然结束。

**和已有 AUDIT 的区别：**

- AUDIT-067：Storage Import focused poller handoff/owner 问题；
- AUDIT-075/092/093/095：Agent/Import retry、finalization、generation correctness；
- AUDIT-153：Cleaning 后端已有 retry，但 UI 没有 retry；
- AUDIT-155：MATERIAL_IMPORT 后端已有 cancel，并且 Worker 已实现 cancellation checkpoints，但 UI 没有 cancel。

**建议最小修复方向：**

不要新增 Storage Import cancel owner。直接复用统一 Durable Task cancel：

1. `serverImportView()` 增加基于 canonical task truth 的 `canCancel`；
2. QUEUED / WAITING_RESOURCE / RUNNING / CANCEL_REQUESTED 前的可取消状态显示“取消任务”；
3. 点击调用 `/api/v62/projects/{project_id}/tasks/{task_id}/cancel`；
4. StorageImportProgressRuntime 继续只负责 polling，不自己改 task 状态；
5. UploadTaskCenter 对 storage-import active task也可暴露同一 cancel action，方便关闭弹窗后仍可停止；
6. AWAITING_CONFIRMATION 是否允许 cancel 应与 TaskRepository 合同统一决定；
7. 已终态不显示 cancel；
8. cancel 后继续轮询到 CANCELLED，不要点击后立即从 UI 隐藏。

**应新增回归测试：**

- QUEUED storage import 显示 cancel，点击后进入 CANCELLED；
- RUNNING directory scan cancel 后停止后续对象读取；
- server ZIP extracting cancel 后不继续扫描/建立索引；
- Agent storage scan cancel 传播到 Durable task/assignment；
- 关闭弹窗只 handoff polling，不应等价于 cancel；
- UploadTaskCenter 可取消仍 active 的 storage-import；
- terminal task 不显示取消；
- cancel 期间不产生第二 poller/第二 task owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-156 — 成功 Conversion 行仍显示“删除”，但后端明确禁止删除任何已产生成果的转换记录；点击稳定 409

**级别：中**  
**模块：Deployment Conversion UI / Conversion Lifecycle / ModelArtifact / Action Eligibility**

**现象：**

当前部署转换页面 `jobRow(j)` 用：

`const isRun=['queued','waiting_resource','running'].includes(j.status)`

然后对所有 `!isRun` 的任务统一渲染：

`删除 -> deleteDeployJob(job_id)`

因此一个正常成功的 `status='done'` Conversion 行会同时出现：

- 日志；
- 下载部署包；
- 删除。

但后端 `DELETE /api/v39/projects/{project_id}/deploy/jobs/{job_id}` 对成功转换有明确且更严格的生命周期合同：

`if status in SUCCESSFUL_CONVERSION_STATUSES: raise CONVERSION_JOB_DELIVERY_IMMUTABLE (409)`

原因是成功 Conversion 的 job/output 已成为算法版本交付链、ModelArtifact 和发布映射的可审计组成部分，不能单独删除；需要通过算法版本删除/回退 owner 统一退役。

因此 UI 的成功任务“删除”按钮是一个必失败动作。

**真实调用链：**

用户完成 ONNX/RKNN 转换 → job.status=done → 页面 `jobRow()` 认为 `isRun=false` → 显示“下载部署包”同时也显示“删除” → 用户点击删除 → `DELETE /deploy/jobs/{id}` → backend 检测 successful conversion → HTTP 409 `CONVERSION_JOB_DELIVERY_IMMUTABLE`。

**影响：**

- 用户看到系统提供一个实际上永远不能成功的操作；
- 容易误以为删除功能或权限异常；
- 对 RKNN/ONNX 成功产物尤其常见；
- 页面与已经收口的 ModelArtifact / Version lifecycle 合同冲突；
- 后续若 UI 重试删除，仍只会重复 409。

**和已有 AUDIT 的区别：**

- AUDIT-025：Conversion 最近 100 条被当完整历史；
- AUDIT-109：Deploy Resource PATCH/DELETE 可破坏活动 Conversion；
- AUDIT-137：测试发布另走第二套转换 Runtime；
- AUDIT-156：canonical Conversion 页面 action eligibility 与 canonical DELETE lifecycle 直接不一致。

**建议最小修复方向：**

不要放宽后端成功成果不可单删的保护。只修前端动作合同：

1. 把 Conversion action eligibility 抽到统一 helper；
2. `done / successful delivery` 不显示“删除”；
3. 成功任务只保留日志、下载、板端验证/验收等合法动作；
4. `failed / stopped / blocked` 且无 canonical artifact reference 时才允许显示删除；
5. 如果后端因 artifact reference 仍拒绝删除，前端应能展示准确原因，但不要预先声称可删；
6. 不要用 `!isRun` 代替 `canDelete`。

**应新增回归测试：**

- status=done → 有下载、无删除；
- successful RKNN/ONNX → DELETE 不被 UI 触发；
- failed 且无 artifact refs → 显示删除并可成功；
- stopped → 按后端合同显示删除；
- blocked_by_hardware 若已有交付产物/引用时不得错误显示可删；
- queued/running/waiting_resource → 只显示停止，不显示删除。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-157 — AI Candidate 不绑定 source content hash；Storage Rescan 换图后旧候选可被人工确认并写成新图片的正式 Ground Truth

**级别：高**  
**模块：AI Annotation / CandidateStore / Storage Rescan / Human Review / AnnotationRepository / Ground Truth Accuracy**

**现象：**

canonical AI 标注生成阶段会：

`load_task_images()`
→ 从 MaterialRepository 读取当前 material row
→ `StorageManager.materialize()`
→ 对当时真实图片内容调用模型
→ 把候选结果写入 CandidateStore。

但 CandidateStore 当前保存的 item 只有：

- image_id；
- filename / url；
- width / height；
- boxes；
- provider / model / request_id / raw_response_hash 等。

它**没有保存生成候选时的 source content identity**：

- 没有 `content_sha256`；
- 没有 content generation；
- 没有 storage revision；
- 没有可在 review commit 时比较的 Material hash。

而当前 Storage Rescan 明确允许：

相同 `material_id`
→ 相同 `storage_source_id + object_key`
→ 内容从 H1 变成 H2
→ 原 material_id 不变
→ MaterialRepository 覆盖：
`content_sha256 / size_bytes / etag / width / height`

并只把 Material 标成：

`needs_review=true`
`annotation_needs_review=true`
`annotation_review_reason=SOURCE_CONTENT_CHANGED`

这个标记不会让旧 CandidateStore 失效，也不会阻止旧 AI Review Commit。

**真实调用链：**

1. 图片 A 当前内容为 H1；
2. 用户创建 canonical AI 标注任务；
3. `load_task_images()` materialize H1；
4. 模型基于 H1 产生候选框；
5. CandidateStore 只保存 image_id/boxes，不保存 H1 hash；
6. 任务进入人工审核；
7. 在用户点击确认前，外部对象被替换为 H2；
8. 用户执行 Storage Rescan；
9. 系统复用 A 的原 material_id，并把 MaterialRepository 的 hash/尺寸更新成 H2；
10. 旧 AI review 页面仍持有 H1 候选；
11. 用户点击确认；
12. `commit_candidate_decisions()` 只读取当前 AnnotationRepository version 作为 `expected_version`；
13. `write_formal_annotations()` / `AnnotationRepository.upsert_many()` 只做 Annotation version CAS 与标签状态校验；
14. 没有任何 Material `content_sha256` 比较；
15. H1 的框被正式写到当前 H2 的 image_id 上。

如果 H2 的尺寸也发生变化，旧 candidate box 仍可能携带按 H1 尺寸解析出的像素坐标；commit 路径同样没有重新基于 H2 内容/尺寸做“候选属于当前 source generation”的证明。

**为什么这是 Ground Truth Bug：**

AnnotationRepository 的 image_id identity 当前不是 immutable-content identity。

Storage Rescan 已经明确允许同一 image_id 的真实图片内容发生代际变化。

因此 AI candidate 仅绑定 image_id 不足以证明：

> 当前正在人工确认的候选，仍然来自这张素材现在的内容。

`expected_version` 只能防止：

“标注 A 被另一个标注写覆盖”。

它不能防止：

“图片内容从 H1 变 H2，但 Annotation version 没变化”。

所以这是两个不同的 revision domain。

**用户真实可达场景：**

- 对象存储图片被上游替换；
- 用户执行平台已有 Storage Rescan；
- AI 任务已经生成候选但尚未人工确认；
- 用户随后在正常 AI Review 页面确认候选。

不需要 legacy API，也不需要内部调用。

**影响：**

- H1 的框可正式落到 H2；
- 目标位置/类别可能完全错误；
- H2 尺寸变化时坐标语义进一步失真；
- Material 虽曾标记 `annotation_needs_review`，AI Commit 又会把新的正式 annotation projection 写回，容易让用户误以为已经重新审核；
- 后续 Training Picker / Snapshot 会把这些错误 GT 当正式标注；
- 训练准确率可能出现难以解释的系统性噪声；
- 任务状态、Annotation version、Candidate journal 都可能完全正常，因此不容易被发现。

**和已有 AUDIT 的区别：**

- AUDIT-099：Storage Rescan 与**人工 Annotation 保存**的并发 TOCTOU，重点是 Rescan 校验与 Annotation commit 不原子；
- AUDIT-129：AI task 没冻结 live label catalog；
- AUDIT-148：partial-scope annotated 正样本进入训练；
- AUDIT-149：Dataset DELETE 与 AI formal commit 的生命周期 race；
- AUDIT-152：Cleaning succeeded result 未绑定当前素材 hash；
- AUDIT-157：AI Candidate 本身未绑定生成时 source hash，导致“旧图片推理结果 → 新图片正式 GT”。

所以 157 是 candidate evidence 与 material content generation 的身份缺失，不是 Annotation version race。

**现有测试为什么没有发现：**

AI tests 主要覆盖：

- immutable image_id order；
- CandidateStore crash recovery；
- provider result 不重复计费；
- label mapping / review scope；
- Annotation expected_version；
- Candidate commit journal；
- stale worker generation fence。

Storage Rescan tests 则验证：

- 同 storage reference 可更新原 Material 的 content hash；
- CHANGED 时标记 annotation_needs_review。

缺失跨模块测试：

`AI candidate generated on H1 → rescan same material to H2 → human review commit`

因此两边单测都可通过，但组合后 Ground Truth 错绑内容。

**建议最小修复方向：**

不要新增第二 CandidateStore，也不要让 Rescan 删除 AI task。

继续复用现有 canonical owners，给 Candidate evidence 加 source-generation fence：

1. AI generation 时为每个 candidate item 冻结：
   `source_content_sha256`
   （必要时同时记录 width/height）；
2. 人工 review commit 前批量读取当前 MaterialRepository rows；
3. 当前 `content_sha256` 与 candidate source hash 不一致：
   - fail-closed；
   - 该 image_id 不得写入正式 Annotation；
   - UI 明确提示“素材内容已变化，请重新执行 AI 标注/重新审核”；
4. Material 不存在时同样 fail-closed；
5. 已 accepted 的旧 candidate 不得因为 image_id 一样继续复用；
6. retry/recovery 也必须检查旧 candidate source hash；
7. 不要自动把旧框按新尺寸缩放后继续提交，这不能证明 H2 与 H1 是同一视觉内容；
8. Annotation `expected_version` 继续保留，它解决的是另一个并发维度。

**应新增回归测试：**

至少覆盖：

- H1 candidate + current H1 → 正常 commit；
- H1 candidate + Rescan H2 → commit 409/业务冲突，不写 GT；
- H1 candidate + H2 尺寸变化 → 不得自动缩放并提交；
- Material 已删除 → review commit 不得创建孤儿 GT；
- 200 条 batch review 中只有部分 hash 变化 → 变化项 fail-closed，行为需明确且可恢复；
- retry/recover 读取旧 CandidateStore 时也校验 source hash；
- unchanged Material 不引入额外逐图片 N+1，必须批量校验；
- Annotation expected_version 的既有并发测试继续保留。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-158 — Service Node Token 轮换会立即切断 RUNNING Agent；合法 execution lease 也无法 heartbeat / 上传结果 / finalize

**级别：高**  
**模块：Service Node / Agent Authentication / Token Lifecycle / Durable Execution / Remote Training & Conversion & Cleaning & Import**

**现象：**

当前服务节点页面对所有节点直接提供：

`轮换 Token`

按钮。

前端提示也明确写着：

> 旧 Token 会立即失效。

后端：

`ServiceNodeRepository.rotate_token(node_id)`

会直接：

- 生成新 token；
- 覆盖 `service_nodes.token_hash`；
- `token_version + 1`；
- 不检查该节点当前是否存在：
  - ASSIGNED；
  - CLAIMED；
  - RUNNING；
  - CANCEL_REQUESTED；
  - 正在 finalization 的 Durable Task。

旧 token 随即失效。

**问题在于 RUNNING Agent 的 execution lease 并不能独立完成任务。**

所有运行期控制面请求仍先用当前 node token 认证：

`heartbeat_execution()`
→ `_owned_execution()`
→ `_authenticate_node()`
→ `ServiceNodeRepository.authenticate()`
→ 校验当前 `token_hash`

同样路径还覆盖：

- append_log；
- material scan broker；
- cleaning selection broker；
- training model upload；
- result upload prepare；
- result upload confirm；
- begin_finalization；
- finish_execution。

因此节点 N 已经合法持有：

- execution_lease_token；
- execution_generation；
- worker_id；

也不能在 node token 被轮换后继续完成当前 execution。

**真实调用链：**

1. Agent 使用 token T1 正常在线；
2. Remote Training / Conversion / Cleaning / MATERIAL_IMPORT / Deployment Test 已进入 RUNNING；
3. Agent 持有合法 execution lease；
4. 管理员进入当前正式“服务节点”页面；
5. 节点卡片即使展示“执行中任务”仍然显示“轮换 Token”；
6. 用户点击轮换；
7. `POST /api/v63/service-nodes/{node_id}/rotate-token`；
8. 后端立即把 token_hash 从 T1 替换成 T2；
9. Agent 进程仍配置 T1；
10. 下一次 heartbeat / log / result upload / finalize 请求：
    `authenticate(T1)`
    → 401 `INVALID_NODE_TOKEN`；
11. RUNNING task 无法续租；
12. execution lease 最终过期；
13. Durable recovery 按当前 task 状态做 reclaim/requeue/cancel。

如果 Agent 在失去控制面连接前已经完成昂贵计算、甚至已上传部分业务产物，这会进入重复执行/半提交恢复复杂路径。

**为什么“停用节点仍允许 RUNNING 完成”不能保护：**

当前 `_owned_execution()` 特意使用：

`require_enabled=False`

所以管理员停用节点后，已有 RUNNING execution 可以继续 heartbeat/finalize。

这是合理的 drain 语义。

但 `require_enabled=False` 并没有绕过 token authentication。

因此：

- Disable：允许现有任务自然完成；
- Rotate Token：立即把现有任务踢断。

两个管理动作的生命周期语义不一致。

**用户真实可达场景：**

现代 Service Node UI：

`static/modules/service-node-runtime.js`

每个节点卡片都直接渲染：

`data-node-action="rotate"`

点击后调用：

`rotateToken(nodeId)`
→ POST `/rotate-token`

UI 没有根据：

`node.durable_tasks`

禁用该按钮，也没有要求先 drain。

后端同样没有 active task guard。

所以这是当前生产真实可达管理动作，不是内部 API。

**影响：**

- Remote Training 可中途失去 heartbeat；
- Remote Conversion / Cleaning / Import / Deployment Test 可在结果提交阶段断开；
- 已完成计算但尚未 finalize 的任务可能被 lease recovery 重新执行；
- 用户会看到节点突然 offline / task 回队列，而原因只是管理员轮换凭据；
- 大模型/训练/转换等长任务可能浪费数小时计算；
- 如果已存在 result upload / canonical commit，可能与 AUDIT-092/093 的恢复窗口叠加，形成重复业务副作用；
- CANCEL_REQUESTED task 也可能因 Agent 无法 finish CANCELLED 而只能等 lease recovery。

**和已有 AUDIT 的区别：**

- AUDIT-055/060/070：assignment / node offline / GPU reservation 生命周期；
- AUDIT-075：Agent start 对永久错误仍重试；
- AUDIT-076/077：Service Node DELETE 没完整保护 assignment / Agent RUNNING；
- AUDIT-092/093：result commit/receipt/final finish 的 crash window；
- AUDIT-158：**Service Node credential rotation 本身**在合法 RUNNING execution 生命周期中立即撤销认证能力。

即使 092/093 全部修好，只要 rotation 仍会让旧 Agent 401，本问题仍独立存在。

**现有测试为什么没有发现：**

`tests/api/test_service_node_api.py`

当前明确验证：

- rotate token 成功；
- replacement != old token；
- old token 下一次 heartbeat 返回 401。

这个测试只覆盖 idle node 的安全性。

没有覆盖：

- node 上存在 RUNNING task；
- node 上存在 CLAIMED assignment；
- node 已 disabled 但仍在 drain RUNNING task；
- result upload/finalization 正在进行。

Agent execution tests 又默认 token 在整个 execution 生命周期不变化。

所以两个测试集各自通过，却没有交叉验证 token lifecycle 与 execution lifecycle。

**建议最小修复方向：**

不要新增第二套 Agent auth owner。

最小安全方向优先是 **drain-before-rotate**：

1. rotate-token 后端在同一 repository truth 中检查：
   - active ASSIGNED / CLAIMED；
   - RUNNING / CANCEL_REQUESTED Agent task；
   - 必要时 finalization 状态；
2. 只要有 active execution/assignment：
   - 返回 409；
   - 明确提示“请先停用节点并等待现有任务结束，再轮换 Token”；
3. 前端根据 canonical active truth：
   - 有执行中任务时禁用轮换；
   - 仅做 UX，不能替代后端 guard；
4. 节点 disabled 但仍有 RUNNING drainage 时同样禁止 rotate；
5. terminal 后 rotate 正常使 T1 失效、T2 生效；
6. 不要让旧 token 对新 claim/start 保持无限 grace。

如果未来确实需要无中断 rotate，可设计 versioned/grace token，仅允许旧 token 完成**已经冻结 generation 的 execution**，新 assignment 必须使用 T2；但这比当前最小修复复杂，不应先造第二套 token owner。

**应新增回归测试：**

至少覆盖：

- idle node rotate → 成功，T1 401，T2 heartbeat 成功；
- RUNNING Agent task → rotate 409，T1 仍可 heartbeat/finalize；
- CANCEL_REQUESTED task → rotate 409，直到 CANCELLED；
- disabled + RUNNING drainage → rotate 仍 409；
- ASSIGNED / CLAIMED pre-start assignment → rotation 不得把 assignment 静默遗弃；
- task terminal 后 rotate → 成功；
- rotate 失败不得改变 token_version/token_hash；
- UI 在 active task 时展示明确 drain 提示，但后端仍是最终 fence。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-159 — 总览 quality-overview 每 60 秒同步做全项目 Ground Truth N+1 + 500 图全字节/OpenCV 质检；20k 项目进入页面即触发重型 Web 热路径

**级别：中高**  
**模块：Dashboard / Quality Overview / Annotation Ground Truth / Image Hygiene / Performance**

**现象：**

当前总览页不是只消费已缓存的 summary。

canonical dashboard render：

`renderDashboardCanonical422()`
→ `refreshDashboardExtras422()`
→ `GET /api/v42/projects/{project_id}/quality-overview`

且前端只设置：

`DASHBOARD422_EXTRAS_TTL_MS = 60 * 1000`

也就是同一客户端超过 60 秒再次触发总览 extras 时，会重新执行整个后端聚合。

后端 `v42_quality_overview()` 在 Web 请求线程内同步做：

1. 对每个 dataset 调用 `dataset_quality_report()`；
2. 对每个 dataset 调用 `_v42_hygiene_report(..., 500)`；
3. 再逐算法读取 latest job metrics 与 online audit。

其中 `dataset_quality_report()`：

- 先 `load_images(project_id)` 全量 hydrate 项目素材；
- 再筛 dataset；
- 对每张图片逐条：
  `read_annotation(project_id, img["id"])`
  → AnnotationRepository.get；
- 再逐框 normalize / 聚合。

单个 20k dataset 就是约 20,000 次单条 Ground Truth lookup。

`_v42_hygiene_report()` 又：

- 再次 `load_images(project_id)`；
- 截取该 dataset 最多 500 张；
- 对每张：
  - `Path.read_bytes()` 全量读入内存并重新 SHA256；
  - `cv2.imread()` 再次解码；
  - 灰度转换；
  - Laplacian；
  - mean brightness。

因此“打开总览”会同步触发磁盘、SQLite、图片解码的组合重活。

**规模放大：**

单 dataset 20k：

- 全项目 Material hydration；
- 20k 次 Annotation 单条读取；
- 再次全项目 Material hydration；
- 500 张图片全字节 read + OpenCV decode。

多 dataset 更糟：

`for d in datasets`

会让：

- `load_images(project_id)` 按 dataset 数重复；
- 每个 dataset 各自最多再重读 500 张图片。

最终 endpoint 只返回很小的 dashboard summary，却先做大量明细工作。

**为什么是生产真实热路径：**

前端当前正式总览 owner 直接调用该 endpoint。

不是 legacy-only helper，也不是 zero-reference。

调用发生在：

`renderDashboardCanonical422()`

并且 60 秒 cache 仅存在于浏览器内：

- 新客户端；
- 刷新页面；
- cache 过期后重进总览；
- 多用户同时打开；

都会各自重新击中重型后端计算。

后端没有持久化 quality snapshot / revision cache，也没有 Durable quality worker owner。

**和已有 AUDIT 的区别：**

- AUDIT-048：Quality Center / Training Data Quality 的图片 hash/I/O 热路径；
- AUDIT-143：`GET /api/projects/{project_id}` 项目详情逐素材 AnnotationRepository.get；
- AUDIT-145：Dataset List 为小型聚合全量 hydrate Material + Annotation；
- AUDIT-159：当前**总览专用 `quality-overview`** 独立再次执行 Ground Truth N+1 + 图片字节质检，而且被 dashboard 60 秒 TTL 触发。

即使 143/145 修复，159 endpoint 仍然保留自己的全量/N+1/图片 I/O。

即使 048 修复 Quality Center，也不会自动改变 `_v42_hygiene_report()` 这套独立实现。

**影响：**

- 1k/10k/20k 项目打开总览越来越慢；
- Web 请求线程长时间占用；
- SQLite Ground Truth read 压力；
- 图片源在对象存储/缓存场景下可能额外放大 materialize/本地 I/O；
- 多用户总览访问可叠加 CPU、磁盘和 Python GC 压力；
- 用户会把“首页卡顿”误认为整个平台不稳定；
- Dashboard 本来只需要几个 KPI，却承担接近完整质量扫描成本。

**现有测试为什么没有发现：**

现有 dashboard tests 主要验证：

- extras 能加载；
- cache TTL；
- 页面 KPI 渲染。

Quality tests 主要验证计算结果值。

没有 1k / 10k / 20k workload contract，未断言：

- quality-overview 不得调用 20k 次单条 Annotation read；
- 不得在普通 GET 中重读 500 张图片字节；
- 多 dataset 不得重复全项目 load_images；
- dashboard 轻量读取必须有 bounded work。

**建议最小修复方向：**

不要通过把 TTL 从 60 秒改成 5 分钟来掩盖后端 O(N)。

应复用现有 canonical owner：

1. Ground Truth 统计由 AnnotationRepository aggregate/batched truth 提供；
2. Material dataset counts 由 MaterialRepository aggregate 提供；
3. 图片 hygiene 不应在 dashboard GET 里现场重新算：
   - 复用 Cleaning / Material Integrity 已有结果；
   - 或由单一 background quality snapshot owner 按 Material revision 更新；
4. Dashboard GET 只组合轻量 snapshot/aggregate；
5. 不新增第二套“质量真相”与 Cleaning/Integrity 竞争；
6. 如果短期过渡，至少：
   - Annotation get_many bounded；
   - 不重复 load_images；
   - 优先复用 `content_sha256`；
   - 不对普通 dashboard GET 做全图片 decode。

**应新增回归测试：**

- 20k materials 总览质量 summary 正确；
- 禁止 20k 次 AnnotationRepository.get；
- 多 dataset 不重复全量 Material hydration；
- dashboard GET 不重新 `read_bytes`/OpenCV decode 500 张源图；
- Material/Annotation revision 未变化时重复 GET 为 bounded cached/aggregate work；
- revision 变化后 summary 能更新；
- confirmed_empty 语义继续按正式 Ground Truth 统计；
- 不能通过简单延长前端 TTL 让性能测试通过。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-160 — Material Integrity 部分扫描失败仍无条件 SUCCEEDED；结果页不显示 scan_failures，可把未完整核验的 Full Audit 展示成“未发现异常”

**级别：高**  
**模块：Material Integrity / Durable Task Status / Audit Completeness / Storage I/O / Quality Truth**

**现象：**

当前 `_run_material_integrity_audit()` 在逐素材核验过程中已经区分两类结果：

1. 可以形成正式问题证据的异常：
   - INVALID_IMAGE；
   - CONTENT_HASH_MISMATCH；
   - MATERIAL_OBJECT_MISSING；
   这些会写入 issue_items。
2. 无法完成本次核验的运行时/存储错误：
   - 未归类 StorageError；
   - provider/runtime 异常；
   - 其它 Exception；
   这些不会生成“素材有问题”的证据，而是：
   `scan_failures += 1`。

checkpoint 也明确把它投影为：
- succeeded = processed - scan_failures；
- failed = scan_failures。

但任务结尾无论 `scan_failures` 是 0、1 还是 1000，都执行：

`append_task_log(... TaskStatus.SUCCEEDED)`
`return TaskStatus.SUCCEEDED, RESULT_REF`

result.json 虽然包含：

`"scan_failures": scan_failures`

但 Durable terminal status 仍是 SUCCEEDED。

**前端进一步丢失这份不完整性真相：**

当前素材页：

`openMaterialIntegrityAudit47()`

只按 task.status 判断：

- QUEUED / WAITING_RESOURCE / RUNNING / CANCEL_REQUESTED → 进行中；
- status != SUCCEEDED → “最近一次审计未完成”；
- SUCCEEDED → 直接加载问题组并展示审计结果。

SUCCEEDED 页面只显示：

- 已核验素材 = result.scanned_images；
- 受影响素材；
- 问题组。

完全没有显示：

`result.scan_failures`

并且 groups 为空时直接显示：

> 未发现重复或异常素材

所以：

```text
20,000 张素材
19,800 张真实核验完成
200 张 provider/runtime 读取失败
0 个已确认异常 issue group
```

当前可以得到：

`TaskStatus.SUCCEEDED`

并在 UI 显示：

`已核验素材 20000`
`未发现重复或异常素材`

但真实情况是：

> 有 200 张根本没有完成完整性判断。

**真实调用链：**

用户在“数据集 → 重复与异常素材”点击：
`运行 Full Audit`
→ `POST /api/v62/.../material-integrity/audits`
→ Durable MATERIAL_BATCH / AUDIT_MATERIAL_INTEGRITY
→ `_run_material_integrity_audit()`
→ StorageManager.materialize / CleaningAnalysisRuntime
→ 部分不可分类错误：
`scan_failures += 1`
→ result.json 写入 scan_failures
→ task 仍 SUCCEEDED
→ 用户再次打开“重复与异常素材”
→ 前端只看到 SUCCEEDED
→ 不展示 scan_failures
→ 可能显示“未发现重复或异常素材”。

**为什么这是 Bug：**

Material Integrity 是“Full Audit”的证据 owner。

这里的 scan failure 不是：

“已核验后确认没有问题”。

而是：

“本轮没有得到足够证据判断这一张素材”。

把两者压缩成 SUCCEEDED，会破坏审计完整性语义。

尤其该页面后续还允许用户基于审计结果：

- 查看重复；
- 删除素材；
- 保留某一 Ground Truth；
- 判断项目是否已清理干净。

因此“审计完整完成”和“部分无法检查”必须严格区分。

**和已有 AUDIT 的区别：**

- AUDIT-057：Full Audit active-task 恢复/防重问题；
- AUDIT-058：结果分页后续页不可见；
- AUDIT-097：长扫描不校验 Material/Annotation revision，可能形成 mixed-generation snapshot；
- AUDIT-160：即使 repository revision 完全稳定，部分素材发生不可判定读取失败时，任务仍被标成 SUCCEEDED，且 UI 隐藏 scan_failures。

097 是“扫描到的是不同世代”。

160 是“有些素材根本没扫描成功却宣称 Full Audit 成功”。

**影响：**

- Full Audit 可产生假“全绿”；
- 存储源临时错误/权限问题/远端抖动可能被掩盖；
- 用户可能基于不完整审计继续训练或清理；
- 20k 数据中少量失败很难人工发现；
- 运维只看 task status 会认为审计成功；
- 重新审计的必要性不会被 UI 提示。

**现有测试为什么没有发现：**

现有 Material Integrity 测试主要验证：

- 重复图片分组；
- annotation conflict；
- invalid image；
- missing object/hash mismatch；
- cursor pagination；
- background task creation。

这些都属于“可以形成明确 issue_type”的业务异常。

缺少测试：

- provider 抛未知 StorageError；
- analysis runtime 发生非 ImageDecodeError；
- scan_failures > 0 的 terminal status；
- 前端对不完整审计的展示。

因此 result 中虽然已有 scan_failures 字段，但 status/UI 从未消费它。

**建议最小修复方向：**

不要把未知读取失败伪造成某个素材质量问题。

应保留两类真相：

1. 已确认素材异常 → issue group；
2. 本轮未能完成核验 → audit scan failure。

最小方向：

- `scan_failures == 0` → SUCCEEDED；
- `0 < scan_failures < processed` → PARTIAL_SUCCESS（或已有等价“不完整”终态）；
- 全部/关键阶段无法扫描 → FAILED；
- public result 暴露 scan_failures / succeeded；
- UI 对 PARTIAL_SUCCESS 显示：
  “审计部分完成，N 张未能核验，请修复环境后重试”；
- groups 为空但 scan_failures > 0 时绝不能显示“未发现异常”；
- retry 应只重试未完成项或明确重新发起完整 audit，但不能把旧 partial 当 complete truth；
- 不新增第二套 Material Integrity owner。

**应新增回归测试：**

- 100 张全部可扫描 → SUCCEEDED；
- 99 成功 + 1 未知 provider error → 非 SUCCEEDED / PARTIAL_SUCCESS；
- 0 成功 + 全部运行时失败 → FAILED；
- known missing object 仍形成 MATERIAL_OBJECT_MISSING，不计为未知 scan failure；
- PARTIAL_SUCCESS 页面明确显示失败数量；
- groups=0 + scan_failures>0 不得显示“未发现重复或异常素材”；
- retry/re-run 后全部成功才能升级为 SUCCEEDED；
- 与 AUDIT-097 revision fence 同时成立，不得用忽略 scan failures 的方式规避 revision 校验。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-161 — “无需清洗”仍有同步 v52 mutation 旁路；10k/20k 整个筛选集可绕过 canonical MARK_CLEAN_SKIPPED Durable owner

**级别：中高**  
**模块：Materials / Cleaning Decision / MaterialBatch / Frontend Owner / 1k-20k Scale**

**现象：**

平台已经存在 canonical 素材批处理 owner：

`MATERIAL_BATCH + MARK_CLEAN_SKIPPED`

它具备：

- selection freeze；
- repository revision；
- Durable Task；
- 500/批处理；
- Task Center；
- progress / cancel / retry；
- 大 explicit selection 上限 100000。

当前批量“无需清洗”弹窗与导入复核也已经优先走：

`window.runMaterialBatch62('MARK_CLEAN_SKIPPED', ...)`

但当前正式素材页仍保留另一套生产 mutation owner：

`window.markReady412()`
→ `POST /api/v52/projects/{project_id}/images/mark-ready`
→ `v52_mark_ready()`
→ `MaterialRepository.get_many(ids)`
→ `MaterialRepository.patch_many(... batch_size=500)`

这是同步 HTTP mutation，不创建 MaterialBatch。

**真实生产入口至少有三条：**

1. 未处理素材卡片：
   “无需清洗”
2. 图片详情：
   “无需清洗”
3. 未处理素材页顶部：
   “当前素材无需清洗”

并且 `window.markReady412` 只有这一个定义，后续 runtime 没有覆盖它。

因此不是 zero-reference legacy。

**大规模问题：**

顶部“当前素材无需清洗”执行：

`markReady412(dataRows412().map(x => x.id))`

而 `dataRows412()` 返回的是当前筛选条件下的**全部素材**，分页只发生在后续：

`renderData412Cards()`
→ `all.slice(pageStart, pageEnd)`

所以：

- 页面虽然一次只渲染一页；
- 但按钮会把整个 10k/20k filter result 的 IDs 一次塞进同步 POST。

这绕过了项目已经专门为 1k/10k/20k 设计的 Durable MaterialBatch。

**两个 owner 写的业务字段本质相同：**

canonical batch：

`mark_ready(row, decided_at)`

写：

- processing_status=processed；
- clean_skipped=true；
- clean_decision=skipped；
- clean_decision_at；
- updated_at。

v52 direct endpoint 又独立手写同一套字段。

因此这是明确的 duplicate mutation owner，而不是查询辅助函数。

**用户真实可达场景：**

1. 导入 20,000 张未处理素材；
2. 进入“数据集 → 未处理”；
3. 页面只显示分页；
4. 点击顶部“当前素材无需清洗”；
5. 浏览器实际收集整个 dataRows412；
6. 一个同步 HTTP 请求携带全部 IDs；
7. 后端在 Web request 生命周期内直接 patch 全部 Material rows；
8. 没有后台任务卡片、真实进度、取消或重试。

同一用户若改走“批量无需清洗”弹窗，则又会进入完全不同的 Durable owner。

**影响：**

- 同一业务动作两套生命周期；
- 10k/20k 同步 mutation 造成 Web 请求卡顿/超时风险；
- 请求中断时用户无法从 Task Center 判断真实完成范围；
- 没有 durable item-level failed truth / retry；
- 没有统一 selection freeze / repository revision evidence；
- 单张、顶部批量、导入复核的审计与运行行为不一致；
- 后续若 canonical MARK_CLEAN_SKIPPED 增加 lifecycle guard，v52 旁路仍会绕过；
- 继续形成“修 canonical owner 但旧按钮仍能绕过”的技术债。

**和已有 AUDIT 的区别：**

- AUDIT-038/086/152/153：Cleaning scan/confirm/retry 语义；
- AUDIT-057 等：MaterialBatch active discovery；
- AUDIT-161：已经存在 canonical `MARK_CLEAN_SKIPPED` owner 后，当前素材 UI 仍直接调用同步 v52 mutation，形成第二 owner 和 20k 旁路。

**现有测试为什么没有发现：**

前端测试分别验证：

- MaterialBatch runtime 可执行 MARK_CLEAN_SKIPPED；
- 素材页存在“无需清洗”操作；
- direct v52 endpoint 能正确修改字段。

没有 contract test 强制：

> 所有生产“无需清洗”入口必须只经过 canonical MaterialBatch owner。

也没有 20k 浏览器测试断言：

顶部“当前素材无需清洗”不得一次同步 POST 20k image_ids 到 v52 direct endpoint。

**建议最小修复方向：**

不要新增第三套 owner。

1. 把 `markReady412()` 改成 canonical MaterialBatch adapter：
   - 单张也可创建 MARK_CLEAN_SKIPPED；
   - 批量直接复用 runMaterialBatch62；
2. v52 direct `images/mark-ready`：
   - 若无其它外部合同依赖，应 retire/410；
   - 若暂时兼容，至少不得再被生产 UI 调用；
3. 顶部整个筛选集操作应使用 FILTERED selection，避免先在浏览器构建 20k IDs；
4. Task Center / PollRegistry 继续复用现有 MaterialBatch owner；
5. 不要通过给 v52 加更大 body limit/更长 timeout 来“修性能”。

**应新增回归测试：**

- 单张“无需清洗”只创建 MARK_CLEAN_SKIPPED task；
- 卡片/详情/顶部/导入复核全部走同一 owner；
- 20k filtered 操作浏览器不构建/POST 20k explicit IDs；
- v52 direct endpoint 不再被当前静态生产代码引用；
- MaterialBatch success 后 UI 状态正确刷新；
- partial/failure 有 Task Center truth；
- 不能用 fallback 到 direct endpoint 掩盖 MaterialBatch runtime 未加载。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-162 — Label Integrity “创建后台修复”在返回 202 前同步冻结全部候选；20k 异常标签会把重型 GT 规划压在 Web 请求线程

**级别：中高**  
**模块：Label Integrity / Repair Admission / MaterialBatch / 1k-20k Scale / Request Latency**

**现象：**

标签完整性页面把修复动作描述为：

> 创建一个 durable repair task

前端用户点击确认后：

`POST /api/v54/projects/{project_id}/labels/integrity/audits/{audit_task_id}/repairs`

预期是快速受理，再由 MaterialBatch Worker 后台完成。

但后端 `create_orphan_repair()` 在真正：

`repository.create(task)`

之前同步调用：

`_freeze_orphan_repair()`

而这个函数已经完成了大规模重活：

1. 从审计 SQLite：
   `SELECT DISTINCT image_id ...`
   并 `.fetchall()` 全部 repair candidates；
2. 把全部 candidate IDs 构造成 Python list；
3. 每 500 张调用：
   `AnnotationRepository.get_many()`；
4. 对每一张：
   - 重建 reference map；
   - 找 relevant mappings；
   - 计算 `record_digest`；
   - 调 `plan_label_mappings()`；
   - 生成完整 per-image repair plan JSON；
5. 所有 plan 先累计到：
   `frozen: list[tuple[str,str]]`
   内存列表；
6. 再创建 selection.sqlite3；
7. 一次 executemany 把全部 frozen plan 写入 selection；
8. 写 request/checkpoint；
9. 最后才 `repository.create(task)` 并返回 202。

因此 Durable Worker 只后台执行“已经全部 freeze 完的 repair”，而最重的 repair admission/freeze 仍是同步 HTTP 工作。

**真实规模：**

用户项目目标明确包含：

- 1k；
- 10k；
- 20k 素材。

历史标签统一/迁移正是可能波及大量图片的场景。

如果 Full Audit 找到 20k 张都引用历史 source label，则一次“统一创建后台修复”会在 API 请求里：

- fetchall 20k IDs；
- batch-read 20k Annotation GT；
- 对 20k records 做 plan/digest；
- 在 Python 内持有 20k plan JSON；
- 再写 20k selection rows。

用户看到的会是：

点击“确认创建后台修复”
→ 按钮/Modal 长时间等待 POST 返回
→ Durable Task 甚至还没正式创建。

**为什么这是 Bug：**

项目已经明确把大批量标签治理收口到 Durable MaterialBatch，目的就是：

- 页面快速受理；
- 后台执行；
- 可观察进度；
- 可取消/恢复；
- 避免大规模 Web request 阻塞。

当前实现只把第二阶段 remap 放到了 Worker，第一阶段的 20k freeze 仍同步执行，破坏了同一产品合同。

**和已有 AUDIT 的区别：**

- AUDIT-057：Label/Material Integrity active audit 发现与防重；
- AUDIT-058：Material Integrity 结果分页；
- AUDIT-059：标签统一 active task bounded discovery / 防重；
- AUDIT-097：Material Integrity revision consistency；
- AUDIT-162：Label Integrity repair 的**创建请求本身**同步执行全量候选 freeze/plan，导致“后台任务”在真正入队前仍有 O(N) Web 热路径。

**影响：**

- 10k/20k repair 创建弹窗长时间 loading；
- Web worker 被占用；
- 反向代理/浏览器超时后用户不知道任务究竟是否已创建；
- 超时重试可能导致重复 admission 竞争；
- Python 同时保留大量 plan JSON，增加内存峰值；
- Task Center 在 freeze 完成前看不到任何任务，无法展示真实进度。

**现有测试为什么没有发现：**

现有 Label Integrity repair 测试主要验证：

- mapping 合法性；
- active repair 防重；
- source digest CAS；
- 同一 image 聚合一次写；
- 目标标签身份冻结；
- retry/fail-closed。

测试数据量很小。

没有 1k/10k/20k contract，未断言：

- POST repairs 的工作量必须 bounded；
- TaskRecord 必须在大规模 freeze 前可见；
- 不允许 `.fetchall()` 全候选并把所有 plan 先堆入 Python list；
- 创建阶段需要可观测进度。

**建议最小修复方向：**

不要新增第二 repair owner。

继续用 MATERIAL_BATCH / AnnotationRepository canonical owner，但把生命周期拆清：

1. POST 只做 bounded validation：
   - mappings；
   - audit identity；
   - active repair guard；
   - 必要的轻量 revision token；
2. 快速创建 Durable repair/preparation task；
3. Worker 内按 cursor/500 批：
   - 重新读取当前 GT；
   - freeze source digest；
   - 生成 plan；
   - 增量写 selection.sqlite3；
4. freeze 完成后写 frozen marker，再进入 remap execution；
5. preparation 期间支持真实 progress/cancel；
6. 不要持有 20k plan 的 Python list；
7. 如果仍需 create-time CAS，冻结 revision/token，而不是同步复制所有 records。

**应新增回归测试：**

- 20k candidates 的 POST admission 不做 20k GT hydration；
- task 在 preparation 开始前已可从 Task Center 查询；
- selection freeze 使用 bounded batches；
- cancellation during preparation 不留下可执行的半冻结 selection；
- retry/recovery 可继续/重建 freeze；
- source digest CAS 与 label governance fence 继续保留；
- 不能通过延长 HTTP timeout 让性能测试通过。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-163 — 训练任务详情仍调用旧 trainingReport425；同一训练存在两个 Report Owner，旧“补充弱标签数据”直接改 legacy split，却不会进入现代 Training Picker / Iteration Candidate Set

**级别：高**  
**模块：Training Report / Training Recovery / Iteration Decision / Training Picker / Material Split / Duplicate Owner**

**现象：**

当前同一个正式训练任务存在两套仍真实可达的报告入口：

1. 算法版本页：
   `openVersionReport429()` → `openJobReport429()`
2. 训练任务详情：
   `TrainingRecoveryRuntime` 中 `[data-training-report-task]` → `window.trainingReport425()`

`window.trainingReport425` 又被绑定到旧 `trainingReportCore425`。

因此这不是 zero-reference legacy code；现代 Training Recovery 详情页仍主动调用它。

两套 Report Owner 不只是 UI 样式不同。旧 `trainingReport425` 在存在 weak labels 且旧 job 里 `quality_gate.auto_supplement=true` 时，会展示：

`补充弱标签数据`

点击后调用：

`supplementTrain424(job_id)`
→ `POST /api/v44/projects/{project_id}/jobs/{job_id}/supplement`

而该后端会：

- 从 live `load_images(project_id)` 遍历素材；
- 对每张 `split=unassigned` 素材重新读取 live Annotation；
- 只要标注标签与旧训练报告 weak_labels 相交，就加入候选；
- 最多取 `supplement_count`；
- 直接把 MaterialRepository 的 `split` 改成 `train`；
- 在 job.json 记录 `supplemented_image_ids`；
- 返回 `changed=N`；
- 前端提示“已补充 N 张到训练集”。

**但现代训练主链已经不再以 Material.split=train 作为下一轮训练输入 owner。**

当前 Training Create 已收口为：

`TrainingMaterialPickerRuntime`
→ 用户显式选择 image_id
→ `TrainingDraft.materialIds`
→ server selection-summary / eligible truth
→ TRAINING_PREPARE
→ frozen Snapshot / Dataset Revision。

所以旧 `/supplement` 把素材改成 `split=train`，并不会自动把这些 image_ids 注入下一次 Training Draft，也不会自动成为下一轮 frozen Snapshot。

与此同时，当前版本页已经有另一套正式迭代流程：

`iteration_decision`
→ 用户确认 next action
→ persistent `confirmed_iteration_action`
→ supplement candidate/adoption 证据
→ 后续 Training Create。

旧 report 的 `/v44/.../supplement` 完全绕过这套现代 iteration decision / Candidate Set / adoption truth。

**真实调用链：**

训练任务完成并形成版本
→ 用户进入“训练任务”
→ 打开训练任务详情
→ `TrainingRecoveryRuntime` 显示“查看训练报告”
→ 点击
→ `window.trainingReport425(task_id)`
→ 旧 report 根据 `weak_labels` 和 `auto_supplement` 显示“补充弱标签数据”
→ 用户点击
→ `POST /api/v44/.../supplement`
→ live 扫描 Annotation
→ Material.split 从 `unassigned` 改成 `train`
→ toast：`已补充 N 张到训练集`
→ 下一次现代 Training Create 并不会自动带上这些 image_ids。

同一个 task 如果从算法版本页打开报告，则走 `openJobReport429()`，没有这个旧补充动作，并且版本独立评测页面使用新的 persistent iteration decision。

所以用户从两个现行入口打开“训练报告”，不仅看到不同 UI，还得到不同可执行业务动作。

**为什么是 Bug / 重复 Owner：**

平台已经明确收口：Training Picker / Draft / Snapshot 是训练输入 owner；现代 iteration decision 是版本后续动作 truth。

旧 report 仍能直接把 Material.split 当作“补充到训练集”的 owner，相当于又恢复了一套 split-based training-input semantics。

但 split 已经不是当前训练 selection truth，于是产生：

- UI 宣称操作成功；
- MaterialRepository 的 split 真被改了；
- 现代下一轮训练却没有获得这些素材；
- job.json 还记录 `supplemented_image_ids`，形成第三份看似“已采用”的事实；
- 用户可能误以为已经补数据并直接继续训练。

这是典型的旧 Owner 仍通过现代入口存活，并对当前主链产生真实副作用。

**影响：**

- “补充成功”与下一轮真实训练输入不一致；
- 用户可能基于错误前提继续训练；
- Material.split 被无意义改写，影响仍读取 legacy split 的其它兼容页面/统计；
- 同一训练报告入口行为不一致；
- weak-label 后续动作绕过 persistent iteration decision / Candidate Set / adoption audit；
- live Annotation 在点击时重新读取，也不再绑定原版本的 frozen Snapshot / Dataset Revision。

**和已有 AUDIT 的区别：**

- AUDIT-042：Supplement Feedback Candidate 只暴露最近 500 条，讨论的是 modern feedback candidate bounded truth；
- AUDIT-045：算法综合报告扫描全部 job history 的性能；
- AUDIT-135：测试发布存在第二套同步推理 Runtime；
- AUDIT-151：训练创建时 baseVersion admission CAS 缺失；
- AUDIT-163：现代 Training Recovery 仍把用户导向旧 Training Report owner，并暴露已经脱离当前 Training Picker / Iteration truth 的 legacy supplement mutation。

所以本条不是 report 性能，也不是 candidate pagination，而是当前可达的重复 Report / Training-input Owner。

**现有测试为什么没有发现：**

TrainingRecoveryRuntime 测试主要验证：

- 详情打开；
- recovery/status/log；
- “查看训练报告”按钮可点击。

但没有断言它必须委托给当前 canonical report owner。

旧 v44 supplement 测试若存在，只会验证：

- weak label 能筛出素材；
- split 被改成 train；
- job 记录 supplemented_image_ids。

它不会验证：

`supplemented_image_ids` 是否真正进入下一次 TrainingDraft / Snapshot。

新的版本迭代决策测试又单独验证 `iteration_decision / confirmed_iteration_action`，没有检查旧 report 仍可绕过它。

**建议最小修复方向：**

不要再设计第三套报告。

1. TrainingRecoveryRuntime 的“查看训练报告”统一委托当前 canonical `openJobReport429`（或其抽出的唯一 Report Runtime）；
2. 旧 `trainingReport425/trainingReportCore425` 从生产入口物理退役或 410 adapter；
3. 旧 `/api/v44/.../supplement` 不得再通过 `split=train` 表示“进入下一轮训练”；
4. weak-label 补数据必须复用当前版本的 iteration decision / Candidate Set / adoption owner；
5. 真正选择到下一轮训练时，必须转成明确 image_ids 并进入 TrainingDraft / Snapshot；
6. 不要通过让现代 Training Picker重新默认选择所有 `split=train` 来兼容旧语义，这会重新引入第二套 selection owner；
7. 如果 legacy endpoint 需要暂时保留，只能返回明确 410/迁移提示，不能继续修改 Material.split。

**应新增回归测试：**

- Training Recovery 详情点击“查看训练报告”与算法版本页使用同一 report owner；
- 当前生产 bundle 中 `trainingReport425` 不再由 TrainingRecoveryRuntime 调用；
- weak-label 后续动作只能进入 persistent iteration decision / Candidate Set；
- legacy `/v44/.../supplement` 不得继续把 Material.split 直接改成 train；
- 选择补充素材后，下一轮 TrainingDraft 明确包含被用户确认采用的 image_ids；
- 未确认采用的 weak-label candidate 不得进入 Snapshot；
- 同一训练从任务详情和版本页打开报告，业务动作集合一致。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-164 — Training UI 仅按 RUNNING 显示“暂停”；准备/后处理/Remote Agent 阶段没有中央 ProcessIdentity，点击暂停稳定 400/409

**级别：中高**  
**模块：Training Task Actions / Pause-Resume / Durable Task Stage / Remote Agent / Process Identity / Frontend Eligibility**

**现象：**

canonical 训练任务页由 `TrainingTaskVisibilityRuntime` 渲染。

其单任务操作当前判断非常宽：

`taskActions(job)`
→ `trainingDisplayStatus(job) === 'running'`
→ 直接显示：
`<button onclick="pauseTrain428(id)">暂停</button>`

批量操作的 `trainingBatchActionEligible(job, 'pause')` 也同样只判断：

`status === 'running'`。

但 Durable Training 的 `RUNNING` 不是“本地 Trainer 子进程现在一定可 suspend”的同义词。

当前同一 RUNNING 生命周期包含：

- device_admission
- preparing_materials
- materializing
- starting_trainer
- trainer_startup
- training
- finalizing
- final_validation
- recovering_checkpoint
- cleaning_training_process
- finalizing_commit
- 以及 Remote Agent execution。

这些阶段已经被同一个前端 `STAGE_LABELS` 明确识别。

**后端 pause 合同却更严格：**

`POST /api/v48/projects/{project_id}/jobs/{job_id}/pause`

对 Durable task 要求：

1. `durable.status is RUNNING`；
2. `durable.stage != paused`；
3. `_durable_process_identity(durable)` 必须取得：
   - process_pid；
   - process_create_time；
   - process_command_hash；
4. `ProcessController.suspend_tree(identity)` 成功。

如果 process identity 尚未登记，直接：

`400 训练进程身份尚未登记`。

如果 PID 已退出/身份变化，则：

`409 训练进程身份校验失败`。

所以前端 eligibility 和后端实际可暂停条件不是一个合同。

**真实用户可达场景 A — 本地训练启动前：**

1. Durable TRAINING Worker 已领取任务，task_status=RUNNING；
2. 当前 stage 仍是 device_admission / materializing / starting_trainer；
3. Trainer subprocess 尚未登记完整 ProcessIdentity；
4. 训练任务页显示状态“训练中/运行中”，并渲染“暂停”；
5. 用户点击；
6. 后端 `_durable_process_identity()` 直接 400。

**真实用户可达场景 B — 本地训练后处理：**

1. Trainer subprocess 已结束；
2. Durable Task 仍 RUNNING，进入 finalizing / final_validation / finalizing_commit；
3. 页面仍按 status=running 显示“暂停”；
4. ProcessController 对已经退出的 PID 校验失败；
5. 用户得到 409。

**真实用户可达场景 C — Remote Agent Training：**

1. 中央 TaskRepository 通过 Agent execution 把 TRAINING 置为 RUNNING；
2. 真正训练进程在远端 Agent 节点；
3. 中央 Durable task 不具备可由本机 ProcessController suspend 的本地 Trainer ProcessIdentity；
4. canonical Training UI 仍显示“暂停”；
5. 点击稳定失败。

**为什么是 Bug：**

暂停不是纯 status transition，而是一个具备执行能力前置条件的动作。

前端把：

`RUNNING == pauseable`

当成 eligibility truth，后端则实际要求：

`RUNNING + local suspendable process identity + correct phase`。

这是明确 action-contract drift。

而且当前系统已经有：

- canonical task phase；
- process identity；
- execution mode / worker / Agent truth。

不需要再造第二套 owner，只是 UI 没消费现有能力信息。

**影响：**

- 用户在训练启动/收尾阶段看到无法执行的“暂停”；
- Remote Agent Training 全程可能出现无效暂停按钮；
- 批量暂停会把不可暂停任务纳入 eligible 集合，产生逐项失败；
- 用户容易误判为训练进程异常或权限问题；
- action eligibility 与 Durable lifecycle 漂移。

**和已有 AUDIT 的区别：**

- AUDIT-075：Agent start 对 retryable/non-retryable 错误分类不消费；
- AUDIT-087：停止 PREPARING parent 没同步取消 TRAINING_PREPARE child；
- AUDIT-088：UploadTaskCenter 状态枚举漂移；
- AUDIT-093：Agent canonical commit 后 lease recovery 可重复执行；
- AUDIT-164：当前 Training Task 页面把所有 RUNNING 都声明为可暂停，但实际只有存在正确本地 ProcessIdentity 的 training phase 可暂停。

所以本条不是 Agent lease，也不是 stop/cancel lifecycle，而是 pause action eligibility。

**现有测试为什么没有发现：**

`training-task-runtime` / visibility 测试主要按 display status 验证按钮：

- running → pause；
- paused → resume；
- queued → stop。

没有加入：

- task stage；
- process_pid/create_time/command_hash；
- execution mode / Agent worker identity。

后端 pause 测试又单独验证 process identity/fail-closed。

两边测试都能通过，但没有跨层测试：

`前端显示 pause` ⇒ `后端当前一定可 pause`。

**建议最小修复方向：**

不要放宽后端 ProcessIdentity fail-closed。

正确方向：

1. 把 pause capability 作为 canonical task public truth 的显式 action/capability，或让前端基于现有 phase + execution truth 判断；
2. 只有中央本地 Trainer 进程已登记且处于真正 training/paused transition 可控阶段时显示 pause；
3. Remote Agent Training 若当前协议没有远程 suspend/resume，就不要展示暂停/继续；
4. preparing/finalizing/final_validation 等阶段只保留“停止/取消”中后端真正支持的动作；
5. 批量 pause eligibility 必须复用同一个 capability owner；
6. 不要通过捕获 400 后 toast 来当正常交互。

**应新增回归测试：**

- RUNNING + stage=training + valid local process identity → pause visible/accepted；
- RUNNING + device_admission，无 process identity → pause hidden/disabled；
- RUNNING + starting_trainer，无 process identity → pause hidden/disabled；
- RUNNING + finalizing，process 已退出 → pause hidden/disabled；
- Remote Agent RUNNING，无 remote pause capability → pause hidden/disabled；
- PAUSED + valid local process → resume visible；
- batch pause 只挑选真正 pauseable tasks；
- 后端 process identity fail-closed 保持不变。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-165 — Training Submit 只要求选中 ≥2 张素材；默认随机三路划分至少需要 3 个可拆分 component，任务可 202 受理后在 PREPARE 必失败

**级别：中高**  
**模块：Training Create / Split Admission / Duplicate-Group Leakage Guard / Training Submit / TRAINING_PREPARE**

**现象：**

当前前端 `trainingSubmitReadiness()` 对训练素材的最小条件只有：

`(draft.materialIds || []).length >= 2`。

只要其它条件满足，2 张素材即可启用“开始训练”。

但默认 `random_test_from_training_pool` 模式的 canonical backend 不是简单按图片数量切比例，而是先按不可拆分 component 分组，再依次产生 test 与 validation，最终要求 train / validation / test 三个集合都非空。

`build_split_manifest()` 当前流程：

1. `_deduplicate_selected()` 去重；
2. `_component_keys()` 按内容重复、视频/组关系等形成不可拆分 component；
3. 第一次 `_select_grouped(... min_remaining_groups=2)` 划 test；
4. 第二次 `_select_grouped(... min_remaining_groups=1)` 划 validation；
5. 最后显式要求 train / validation / test 全部非空。

`_select_grouped()` 又明确：

`if len(grouped) <= min_remaining_groups: raise ValueError('按不可拆分数据组件分组后组数不足，无法避免数据泄漏')`。

因此默认随机模式至少需要 3 个可拆分 component，而不是“2 张图片”。

**真实用户可达场景 A — 两张合法正式 GT：**

1. 用户选择 2 张已清洗、正式标注且互不重复的图片；
2. server selection-summary 可得到 `eligible_count=2`；
3. 前端 readiness 因 `materialIds.length >= 2` 显示可提交；
4. `/train/start` 先创建 TRAINING + TRAINING_PREPARE 并返回 202；
5. Prepare 进入 `build_split_manifest()`；
6. 默认随机 test split 看到仅 2 个 component，而 `min_remaining_groups=2`；
7. 必然失败：`按不可拆分数据组件分组后组数不足，无法避免数据泄漏`。

**真实用户可达场景 B — 图片数足够但 component 不足：**

例如选择 10 张正式 GT，但它们全部来自同一视频/同一 duplicate group，canonical leakage guard 会把它们视为 1 个不可拆分 component。

前端仍按 10 张计数并允许提交，Prepare 仍必失败。

**独立试验集模式也存在同类结构性缺口：**

`independent_test_set` 虽要求至少选择 1 张 testMaterial，但训练池仍需至少 2 个可拆分 component 才能再拆 train/validation。前端只检查 train material 数和 test 是否非空，不检查 component truth。

**为什么这是 Bug：**

后端 fail-closed 是正确的，不能为了让 2 张数据通过而放宽 leakage guard。

问题是前端 admission 只使用图片数量，完全没有消费 canonical split feasibility。于是一个在提交时已经可以确定不可能成功的请求，仍被包装成“任务已进入后台队列”。

**影响：**

- 2 张素材的默认训练稳定“创建成功→Prepare 失败”；
- 3+ 图片但 duplicate/video/group component 过少时同样失败；
- 用户容易把错误归因于 Worker/GPU；
- Task Center 累积本可预防的失败任务；
- 修复 AUDIT-150 后，即使 `eligible_count>0`，仍会留下这一层假 admission。

**和已有 AUDIT 的区别：**

- AUDIT-053：随机 split 的 UI 百分比显示与后端实际比例不一致；
- AUDIT-150：全部是 pending-only，`eligible_count=0` 仍允许提交；
- AUDIT-165：素材全部可以是正式 GT、`eligible_count>0`，但按 canonical component/leakage 规则结构上无法生成三路 split，前端仍允许提交。

**现有测试为什么没有发现：**

`training-submit` 前端测试只固定：

- 2 张 material → ready=true；
- 1 张 material → ready=false。

它没有调用 server split feasibility，也没有 duplicate/video/group component 数据。

后端 `training_splits` 测试则单独验证：

- component 不足时必须 fail-closed；
- train/validation/test 不得泄漏；
- 大规模 grouped split 正确。

两边都绿，但没有跨层合同测试：

`UI ready=true` ⇒ `canonical split admission 至少结构上可行`。

**建议最小修复方向：**

不要在浏览器重新实现 `_component_keys/_select_grouped`，避免第二套 split owner。

建议复用后端 canonical split planner，增加一个 bounded preflight / readiness projection：

1. 基于当前 selection + split_mode + percentages + selected labels 计算 split feasibility；
2. 返回至少：`split_feasible / reason / effective_component_count`；
3. 前端 Submit readiness 只消费这份 server truth；
4. 默认随机模式 component 不足时禁用提交并提示“当前素材无法安全拆分训练/验证/试验集”；
5. independent_test_set 同样校验 train pool 的 validation split 与 test leakage；
6. Prepare 中现有 fail-closed 保持不变作为最终防线；
7. 不要简单把最小前端数量改成 3，因为 20 张同组素材仍可能只有 1 个 component。

**应新增回归测试：**

- random 模式，2 张独立正式 GT → submit disabled / preflight infeasible；
- random 模式，3 张三个独立 component → 可提交；
- random 模式，10 张但只有 2 个 component → 不得提交；
- independent 模式，train pool 只有 1 个 component + test 非空 → 不得提交；
- duplicate/video/group relation 与 Prepare 使用同一 component semantics；
- pending-only 继续由 AUDIT-150 的 eligible gate 拦截；
- backend split leakage fail-closed 不放宽。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-166 — 非 Agent INT8 转换在创建 Durable Task 前全量 materialize 校准候选；calibration_count=100 也可同步触发 20k 素材 I/O

**级别：中高**  
**模块：Model Conversion / INT8 Calibration / Admission Performance / StorageManager / Durable Task Lifecycle**

**现象：**

当前版本转换弹窗的正式入口 `submitConvert428()` 会 POST `/api/v39/projects/{project_id}/deploy/jobs`。对于非 Agent 的 Rockchip / Sophon INT8（代码还覆盖 TensorRT INT8 分支），后端在真正创建 `MODEL_CONVERSION` Durable Task 之前同步调用 `_deploy_prepare_calibration()`。

`_deploy_prepare_calibration()` 当前顺序是：

1. `images = load_images(project_id)` 全量读取项目素材；
2. 遍历全部 dataset/split 命中的素材；
3. 对每一张先调用 `resolve_material_path()`；
4. `resolve_material_path()` 实际进入 `StorageManager.materialize()`，可能校验本地文件、命中/填充缓存，或访问 OSS/S3/MinIO；
5. 所有命中项都 materialize 完后才执行 `selected = selected[:limit]`；
6. 只复制最终前 `calibration_count` 张到 task calibration 目录；
7. 再对复制结果逐文件 SHA256；
8. 最后才 `_write_deploy_job()` / `shared_task_repository().create(...)`。

因此用户即使填写 `calibration_count=100`，若所选 dataset/split 有 20,000 张，创建请求仍可能先对 20,000 张执行 materialize，再只使用前 100 张。

**真实调用链：**

`算法版本 → 新建版本转换 → INT8 → 开始转换`
→ `submitConvert428()`
→ `POST /api/v39/.../deploy/jobs`
→ `v39_create_deploy_job()`
→ `_v39_create_deploy_job_under_version_fence()`
→ `_deploy_prepare_calibration()`
→ `load_images()` 全项目 hydration
→ 对全部命中项 `resolve_material_path()` / `StorageManager.materialize()`
→ 最后 slice `calibration_count`
→ copy + SHA256
→ 才创建 conversion job / Durable Task。

前端此时只显示按钮文案“正在创建转换任务…”。在整个校准准备阶段 Task Center 没有 task identity，无法显示真实进度，也无法取消。

**为什么是 Bug：**

`calibration_count` 本来就是明确的数量边界，但实现把 limit 放在昂贵 I/O 之后，导致 bounded request 退化成 O(全部命中素材)。同时项目已经把转换执行收口到 Durable `MODEL_CONVERSION`，重型校准准备却仍留在同步 Web admission。

**用户真实可达场景：**

- 20k 素材项目，dataset/split 命中 15k；
- 选择本机/非 Agent Rockchip 或 Sophon INT8；
- 校准数量保持默认 100；
- 点击开始转换；
- 浏览器长时间等待 POST；对象存储素材还可能产生大量远程读取/缓存 I/O；
- Durable conversion task 在这些操作结束前不可见。

**影响：**

- 1k/10k/20k 项目创建 INT8 转换明显变慢；
- 对象存储场景可能放大为大量网络 I/O；
- Web 请求超时后用户无法知道是否创建成功；
- 重试点击可能重复校准准备；
- 无 Task Center 进度/取消；
- calibration_count 的产品边界不具备性能约束意义。

**和已有 AUDIT 的区别：**

- AUDIT-109：Deployment Resource PATCH/DELETE 可破坏已创建 Remote Conversion；
- AUDIT-137：测试发布仍存在第二套导出/转换 Runtime；
- AUDIT-154：External auto-publish 周期性重 SHA256 历史交付文件；
- AUDIT-166：canonical v39 转换创建本身在 Durable Task 入队前，为有限数量 INT8 校准图无界 materialize 全部匹配素材。

**现有测试为什么没有发现：**

现有转换测试主要验证 target/resource/芯片/精度参数、校准产物可用性和转换结果；没有 1k/10k/20k admission contract，也没有断言 `calibration_count=N` 时 `materialize()` 调用最多为 N（或有小幅 bounded overfetch），更没有要求 Durable Task 在重型校准准备前已经可见。

**建议最小修复方向：**

不要新增第二套 Conversion owner。

1. 校准候选选择必须先在 MaterialRepository 层按 dataset/split 做 bounded cursor/limit；
2. 只对最终选中的 N 张执行 `materialize()`；
3. 更稳妥的是先快速创建 Durable conversion/preparation task，再由 Worker 完成校准 staging；
4. preparation 阶段复用同一 task identity、progress/cancel/recovery；
5. Agent 的 portable calibration snapshot owner 继续保留，不要再造第三套；
6. 不要用更长 HTTP timeout 掩盖。

**应新增回归测试：**

- 20k 匹配素材 + calibration_count=100，materialize 次数必须有界于 100（或明确 bounded batch）；
- 对象存储 provider 不得为未入选校准集的素材触发 reader/cache I/O；
- 校准准备期间任务可查询进度/取消（若迁入 Worker）；
- calibration_count=1000 同样受边界约束；
- dataset/split 无匹配素材仍明确失败；
- Agent Rockchip portable calibration 现有合同不回退。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-167 — INT8 Conversion 校准集仍以 live Material.split 选图；现代版本真实 train/val/test 在 Snapshot，量化可选错数据或误报空集

**级别：高**  
**模块：Model Conversion / INT8 Calibration / Training Snapshot / Dataset Revision / Model Accuracy / Lineage**

**现象：**

现代 Training 主链已经把一次训练的真实数据角色冻结在 task-local Snapshot / Dataset Revision：

- Snapshot 保存 `ids.train / ids.validation / ids.test`；
- Algorithm Version 保存 `snapshot_id`、`dataset_revision_id`、`training_lineage`；
- Training bundle 按 Snapshot role 写入 `dataset/images/train|validation` 和 evaluation test；
- 训练流程不会把这些 task-local role 回写成全局 `Material.split`。

但当前版本转换的 INT8 校准集完全没有读取 source version 的 Snapshot/Dataset Revision。

非 Agent `_deploy_prepare_calibration()` 按 live MaterialRepository：

`dataset_id == payload.dataset_id`
且
`material.split == payload.calibration_split`

筛选校准图。

Agent RKNN 的 `build_rknn_calibration_snapshot()` 也使用同一语义：遍历 live MaterialRepository，按 `dataset_id + split` 取前 N 张。

所以当前 conversion calibration 的“train/val/test”实际上是 legacy/live Material.split，而不是被转换模型自己的 frozen training split。

**真实调用链：**

用户完成现代 exact-material Training
→ TRAINING_PREPARE 构建 SplitManifest
→ Snapshot 冻结 train/validation/test image IDs
→ Dataset Revision 持久化
→ Algorithm Version 保存 snapshot_id/dataset_revision_id
→ 用户在该版本点“新建版本转换”
→ 选择 INT8 + calibration_split=train
→ `POST /api/v39/.../deploy/jobs`
→ local/remote `_deploy_prepare_calibration()` 或 Agent `build_rknn_calibration_snapshot()`
→ 忽略 source version snapshot identity
→ 重新从 live Material.split 选择校准图片。

**真实用户可达场景 A — 现代训练素材仍 unassigned：**

1. 用户通过 Training Picker 显式选择 1000 张素材；
2. Snapshot 成功划分 train/validation/test；
3. MaterialRepository 中这些素材并没有被回写 `split=train`；
4. 用户对该版本创建 RKNN/Sophon INT8；
5. UI 默认选择 `calibration_split=train`；
6. 当前校准 selector 找不到该版本真正的 train IDs；
7. 可能返回“INT8 转换需要校准图片，但当前选择的数据集/分组没有可用图片”。

**真实用户可达场景 B — live split 有旧数据：**

1. 项目历史兼容流程/旧 supplement 曾把另一批素材写成 `split=train`；
2. 新版本实际通过 Training Picker 用的是完全不同的一批 frozen image IDs；
3. 创建 INT8 转换时 calibration selector 却选旧 `split=train` 数据；
4. calibration snapshot/hash 本身可以完全稳定、转换也可以成功；
5. 但量化校准数据与 source model 的真实训练/验证数据血缘无关。

**为什么是 Bug：**

INT8 calibration 会直接影响量化 scale/zero-point 和最终模型精度。当前代码已经有 source version 的 immutable Snapshot/Dataset Revision owner，却重新用 live Material.split 推导“训练集”，形成第二套数据角色 truth。

这不是要求校准集必须机械等于训练集；用户当然可以显式选择其它代表性 calibration set。问题是 UI/后端当前把 `train/val/test` 命名成 source-model 数据分组，却实际读取另一个 legacy live 字段，而且没有记录这种偏离。

**影响：**

- 现代训练版本可能无法创建默认 INT8 校准；
- 可静默使用与 source model 无关的历史素材做量化；
- 同一 Algorithm Version 在不同时间转换可能因 live Material.split 变化而得到不同校准集合；
- calibration_snapshot 可稳定证明“用了哪些图”，但不能证明“这些图为何属于该版本 train”；
- RKNN/Sophon INT8 精度和可复现性受影响；
- 删除/移动/旧 supplement 对 Material.split 的变更可改变后续 conversion 结果。

**和已有 AUDIT 的区别：**

- AUDIT-163：旧 Training Report 的 supplement 错把 Material.split=train 当作“进入下一轮训练”，但现代 Training Picker 不消费它；
- AUDIT-166：校准准备的性能/生命周期问题——先全量 materialize 再 limit；
- AUDIT-167：canonical Conversion 本身仍把 Material.split 当 source model 的 train/val/test owner，忽略已经存在的 version Snapshot/Dataset Revision，影响量化准确性与血缘。

**现有测试为什么没有发现：**

当前 conversion calibration 测试通常构造带 `split=train` 的 Material rows，因此会正常取到图片。Training Snapshot 测试又单独验证 exact IDs / Dataset Revision。缺少跨层测试：

`source Algorithm Version.snapshot_id`
→ `INT8 calibration selection`

必须保持同一数据血缘。

也没有测试现代 Training 完成后 Material.split 仍 unassigned 时，版本 INT8 转换是否能从 Snapshot 找到正确校准候选。

**建议最小修复方向：**

不要把现代 Training role 回写到 Material.split，也不要新增第三套 Calibration owner。

1. 对 algorithm-version conversion，默认 calibration source 应优先绑定该 source version 的 `snapshot_id / dataset_revision_id`；
2. `train / validation / test` 从 frozen Snapshot role IDs 读取；
3. 校准条目继续按当前 Material/storage identity 做 SHA/size 可用性校验，内容变化 fail-closed；
4. 若产品允许用户选择“当前数据集任意 live 素材”作为自定义校准集，应显式命名成 custom/live calibration，而不是冒充 source version train split；
5. conversion job 记录 calibration source type + source snapshot/dataset_revision identity + item hashes；
6. Agent/local/remote 共用同一 calibration-selection contract；
7. 不通过重新让 Material.split 成为 Training owner来兼容。

**应新增回归测试：**

- source version Snapshot train IDs 与 Material.split 全 unassigned，INT8 仍能从版本 Snapshot 构建校准集；
- live Material.split=train 指向其它图片时，不得替换 source version frozen train IDs；
- validation/test 选择与 Snapshot roles 一致；
- source material hash 改变后 calibration fail-closed；
- custom/live calibration 若支持，必须显式标记 source_type，不能伪装 version split；
- Agent RKNN 与 local/Sophon 使用相同 version lineage semantics；
- AUDIT-166 的 bounded materialization 同时保持。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-168 — Agent RKNN INT8 已受理后校准对象仍可被 MaterialBatch DELETE_SOURCE 删除；active dependency fence 只保护 Training

**级别：高**  
**模块：Agent MODEL_CONVERSION / RKNN INT8 Calibration / MaterialBatch DELETE_SOURCE / Lifecycle Dependency Fence**

**现象：**

Agent Rockchip INT8 conversion 在创建时会生成 durable calibration snapshot，冻结每张校准素材的 `image_id / storage_source_id / object_key / size_bytes / sha256`，并把它嵌入 `remote_execution.conversion.calibration`。

但这些 calibration bytes 并没有在任务创建时复制到 conversion-owned staging。真正给 Agent 生成执行 payload 时，`_resolve_conversion_execution_payload()` 才逐项调用 `_download_contract()`，重新访问对应 storage source/object。

与此同时，canonical MaterialBatch `DELETE_INDEX / DELETE_SOURCE` 的依赖保护只有 `_assert_not_referenced_by_active_training()`：它只枚举 `TaskKind.TRAINING` 的 QUEUED/RUNNING/CANCEL_REQUESTED，完全不检查活动 `MODEL_CONVERSION` 的 calibration snapshot。

因此校准对象已经被 conversion request 冻结，并不等于被 lifecycle pin。

**真实调用链：**

用户创建 Agent RKNN INT8 conversion
→ `build_rknn_calibration_snapshot()` 验证 object size/SHA 并冻结 refs
→ `stage_model_conversion(... calibration_snapshot=...)`
→ 创建 `MODEL_CONVERSION` Durable Task
→ task 进入 QUEUED / WAITING_RESOURCE

并发用户对校准素材执行 canonical `DELETE_SOURCE`
→ `create_batch()`
→ `_assert_not_referenced_by_active_training()`
→ 因只扫描 TRAINING，检查通过
→ Worker `_delete_sources()` 删除 provider object

之后 Agent conversion 被分配
→ `_resolve_conversion_execution_payload()`
→ calibration item `_download_contract()`
→ storage source/object 已不存在
→ 已受理 conversion 才失败。

即使删除发生在 conversion RUNNING 前几秒，同样没有共享 reservation/fence。

**为什么是 Bug：**

calibration snapshot 已经是 `MODEL_CONVERSION` 的 frozen execution input。任何会物理删除这些 bytes 的 owner 都必须尊重该 active dependency。当前删除 owner只认识 Training，导致同一 Material 的生命周期依赖按 task kind 分裂。

Hash 校验只能发现“对象没了/变了”，不能防止一个合法平台操作在已受理任务之后主动破坏 frozen input。

**用户真实可达场景：**

1. 从 OSS/S3 素材中选择/生成 RKNN INT8 校准集；
2. Agent 节点忙，conversion 长时间排队；
3. 用户在素材治理中执行“删除源文件”；
4. MaterialBatch deletion 正常受理，因为这些 image_ids 不被 active Training 引用；
5. conversion 轮到执行时才报对象不可用。

**影响：**

- 已受理 Agent conversion 可被后续正常素材操作破坏；
- Queue 等待越久风险越高；
- 用户看到的失败会被误判为 Agent/OSS 网络问题；
- retry 若对象已物理删除无法恢复；
- calibration snapshot 的“durable frozen input”语义不完整。

**和已有 AUDIT 的区别：**

- AUDIT-084：DELETE_SOURCE 与 **Training** 的 fence 还是单向 TOCTOU；
- AUDIT-109：Deployment Resource 修改/删除可破坏 Remote Conversion；
- AUDIT-167：校准集选择使用错误的 live Material.split；
- AUDIT-168：即使校准 image IDs/hash 已正确冻结，**active Agent conversion 对这些 object bytes 没有 deletion dependency fence**。

**现有测试为什么没有发现：**

MaterialBatch deletion 测试重点验证 active Training reference；Agent conversion tests 验证 calibration snapshot/hash/download contract。没有跨 owner 并发测试：

`MODEL_CONVERSION calibration refs`
vs
`DELETE_SOURCE physical deletion`。

**建议最小修复方向：**

不要给 Conversion 再造一套 Material deletion owner。

1. canonical Material deletion dependency checker 扩展成通用 active-task input reference owner；
2. 识别至少 TRAINING frozen image IDs 和 MODEL_CONVERSION calibration image/object refs；
3. DELETE_SOURCE/DELETE_INDEX publish 与每批执行前都 fail-closed；
4. 更稳妥可在 conversion 生命周期建立 durable input pin/reservation，由同一 deletion owner查询；
5. conversion terminal/cancel 后释放 pin；
6. 若未来 calibration bytes 改为 conversion-owned staging，则 deletion fence 可只 pin staging lifecycle，不必长期锁 Material source；
7. 不要通过“Agent start 时发现 404 后自动换校准图”修，这会破坏 snapshot identity。

**应新增回归测试：**

- Agent INT8 conversion QUEUED 且 calibration image 命中 DELETE_SOURCE → 409；
- RUNNING conversion 同样禁止物理删除；
- conversion CANCELLED/SUCCEEDED/FAILED 后按 retention 合同可删除；
- 非 calibration Material 不被误锁；
- DELETE_INDEX 若会让 execution resolve 失去 source metadata，也走同一 dependency contract；
- hash/object identity 不允许自动换图；
- AUDIT-084 的 Training deletion tests 继续保持。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-169 — 算法产物 OSS 配置可在活动 Remote Training / Agent Conversion 中原地变更；正式模型上传与远程下载仍解析 live StorageSource

**级别：高**  
**模块：ModelArtifact Storage / Remote Training / Agent Conversion / Storage Credential Lifecycle / Durable Input-Output Contract**

**现象：**

当前“存储配置 → 算法与转换结果存储”是真实生产入口。前端 `ModelArtifactRuntime.saveModelConfig()` 直接：

`PUT /api/v64/model-artifacts/oss-config`

后端 route 直接调用：

`ModelArtifactService.save_artifact_oss_config(payload)`。

该方法对固定专用 source `ARTIFACT_OSS_SOURCE_ID`：

- 原地更新 endpoint；
- 原地更新 bucket；
- 原地更新 public_base_url；
- 原地更新 root_prefix 对应的 ModelArtifact config；
- 如填写新 AccessKey，则对同一个 `secret_ref` 原地 `credentials.set(...)`。

整个保存路径没有检查活动 TRAINING / MODEL_CONVERSION Durable Task。

**Remote Training 的正式模型上传目标没有在任务创建时冻结。**

Agent 训练完成后才调用：

`prepare_training_model_uploads()`
→ `_training_model_storage_ref()`
→ `self.model_artifacts.repository.config()`
→ 读取当时 live `storage_source_id`
→ `self.storage_sources_factory().get(source_id)`
→ 再按 live endpoint/bucket/credential 构造 provider 和 object_key。

也就是说，`best.pt / last.pt` 等正式 ModelArtifact 的目标 storage identity 是训练结束时才决定，而不是任务受理时冻结。

`confirm_training_model_uploads()` 又会再次调用 `_training_model_storage_ref()`，因此 prepare 与 confirm 之间如果配置再次变化，甚至可能用不同 live storage truth 校验。

**Agent Conversion 也依赖 live StorageSource。**

Portable MODEL_CONVERSION request 虽冻结 source model/calibration 的 `storage_source_id/object_key/sha256/size`，但真正 assignment/start 时 `_download_contract()` 会调用：

`_source_provider()`
→ `storage_sources_factory().get(source_id)`
→ `storage_credentials_factory().get(source.secret_ref)`。

所以专用 artifact source 的 endpoint/bucket/credential 被 v64 配置页原地修改后，旧 task 中相同 object_key 会被解释到新的 live provider。

**真实用户可达场景 A — Remote Training 静默改上传目标：**

1. 训练任务 T 创建时算法产物 OSS 指向 Bucket A；
2. Agent 已开始训练，运行数小时；
3. 管理员在“算法与转换结果存储”把 Endpoint/Bucket 改为 B；
4. T 完成后请求上传 best.pt / last.pt；
5. `_training_model_storage_ref()` 此时读取新配置 B；
6. 正式模型被归档到 B，而不是任务受理时用户预期的 A。

若 B 权限/网络不通，则训练主体已经成功，最终模型归档阶段才失败。

**真实用户可达场景 B — 凭据原地轮换：**

1. Remote Training / Agent Conversion 已 QUEUED 或 RUNNING；
2. 用户在 v64 页面填写新的 AccessKey；
3. `save_artifact_oss_config()` 对旧 `secret_ref` 原地覆盖凭据；
4. 活动 task 后续生成 signed GET/PUT 或确认对象时直接使用新凭据；
5. 权限范围不同即可让旧任务中途失败。

**真实用户可达场景 C — Agent Conversion source 被重新解释：**

1. conversion request 已冻结 `source.storage_source_id=S, object_key=K, sha256=H`；
2. S 的 endpoint/bucket 被原地改到另一 Bucket；
3. assignment 时 `_download_contract()` 用 S 的新 provider 对 K 做 stat；
4. 若 K 不存在则 task 失败；若新 Bucket 恰好存在同 key 但 hash 不同则 fail-closed；
5. 即使 hash guard 能阻止读错内容，也不能阻止一个合法配置修改破坏已受理 task。

**为什么是 Bug：**

Durable task 的核心合同是：任务一旦受理，其不可变执行输入和必要输出依赖必须可恢复。当前 source/object identity 部分冻结了，但 provider identity（endpoint/bucket/credential）仍由 live config owner单方面控制。

尤其 Remote Training 的正式模型上传更严重：连输出 storage source/root 都是训练结束后才 late-bind，任务 lineage 无法证明创建时约定的归档目的地。

**影响：**

- 长时 Remote Training 可在最后归档阶段才因存储配置变化失败；
- 同一任务创建时与完成时的模型存储位置可不一致；
- Agent Conversion queued/running 可因正常配置编辑失效；
- credential rotation 没有 old-generation pin；
- retry/recovery 结果取决于“此刻配置”，而不是原 task durable contract；
- 运维很难从失败日志解释为何训练本体已完成但模型不存在。

**和已有 AUDIT 的区别：**

- AUDIT-044：普通 Storage Source PATCH 破坏 active MATERIAL_IMPORT / rescan；
- AUDIT-047：AI Model Config secret_ref 指向的 Keyring 值被 PUT 原地覆盖；
- AUDIT-158：Service Node token rotation 破坏 RUNNING Agent heartbeat/result；
- AUDIT-168：Material DELETE_SOURCE 删除 Agent INT8 calibration object；
- AUDIT-169：专用 ModelArtifact storage config/credential 作为 Remote Training/Conversion 的 live provider/output 依赖，没有冻结或 lifecycle fence。

所以 169 不是 044 的重复：入口是 v64 专用算法产物配置，受影响 task kinds 与业务副作用也不同；Remote Training 还存在正式模型上传目标 late-binding。

**现有测试为什么没有发现：**

ModelArtifact tests 验证保存配置、健康检查、上传/归档；Remote Training tests 验证模型对象上传证据；Agent Conversion tests 验证 source hash 与 portable download。缺少组合测试：

`active remote task + PUT /api/v64/model-artifacts/oss-config`。

也没有断言 Remote Training create 时必须冻结 artifact storage generation/revision，或 prepare/confirm 必须使用同一 storage identity。

**建议最小修复方向：**

不要复制 secret 明文进 task artifact，也不要新增第二 ModelArtifact owner。

建议：

1. 给专用 artifact storage 配置增加 revision/generation identity；
2. Remote Training / MODEL_CONVERSION admission 冻结所依赖的 storage source identity + config revision + secret revision reference；
3. 对活动 task，破坏性配置变更（endpoint/bucket/source/credential/root）要么 409，要么通过 generation pin 让旧 task 继续读旧 provider generation；
4. Remote Training 的正式 model upload target 必须在 task/remote execution contract 中冻结，不能完成后重新从全局 config 选择；
5. prepare_training_model_uploads 与 confirm_training_model_uploads 必须使用同一 frozen target；
6. credential rotation 若要在线支持，应保留旧 secret generation 到所有引用 task terminal；
7. public_base_url 等纯发布展示字段如可安全独立变更，应与执行 provider 字段区分；
8. 不要用 hash mismatch 当 lifecycle fence；hash 只能做内容验证，不能替代依赖 pin。

**应新增回归测试：**

- Remote Training 创建于 artifact storage A，运行中改为 B → 要么配置更新 409，要么该 task 仍严格上传 A；
- Remote Training prepare 与 confirm 之间改配置 → 不得改变 storage_ref；
- active Agent Conversion source provider config 改变 → 受 lifecycle fence；
- credential rotation 保留 old generation 或明确阻止；
- terminal task 后允许按产品策略切换配置；
- 新任务使用新 storage generation，旧任务继续使用旧 generation；
- 不把 AccessKey 明文写入 request artifacts。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-170 — Storage Source PATCH 先改 Keyring、后更新 SQLite；后半段失败时 HTTP 报错但凭据已永久变更/删除

**级别：高**  
**模块：Storage Source / SecretCredentialStore / PATCH Transaction / Credential Consistency**

**现象：**

`PATCH /api/v61/storage-sources/{source_id}` 当前把一个用户操作拆成两个不同 owner 的非原子写入：

1. 先根据 `credentials / clear_credentials` 直接调用 `storage_credentials().set()` 或 `delete()`；
2. 再调用 `StorageSourceRepository.update()` 更新 `name / config / secret_ref / enabled`。

如果第 2 步失败，第 1 步没有 rollback。

StorageSource 表的 `name` 有 `UNIQUE` 约束，而 `update()` 直接执行 SQL UPDATE。因此一个完全正常的 UI 操作就可以制造失败：编辑存储源 A，把名称改成已存在的 B，同时输入新的 AccessKey/Token。后端会先覆盖 A 当前 `secret_ref` 对应的 Keyring，再因 name UNIQUE 冲突在 SQLite UPDATE 失败。

更严重的是 route 只捕获 `ValueError`，SQLite `IntegrityError` 还可能直接变成 500；无论返回 409/500，Secret mutation 都已经提交。

**真实调用链：**

存储配置页 → `openStorageSource61()` → 用户同时编辑名称/Endpoint/凭据 → `saveStorageSource61()` → 单次 PATCH payload 同时包含 name/config/credentials → `update_storage_source()` → `storage_credentials().set(reference, credentials)` 或 `delete(reference)` → `StorageSourceRepository.update()` → SQLite UNIQUE/其它后半段错误 → 请求失败 → Keyring 不回滚。

**用户真实可达场景：**

- A 已配置旧 AccessKey；
- B 已存在同名 source；
- 编辑 A，将名称误填为 B 的名称，同时轮换 AccessKey；
- 点击“保存”；
- 页面提示保存失败；
- A 的 SQLite row 仍保持旧名称和旧 `secret_ref`；
- 但这个 `secret_ref` 对应的真实凭据已经被新 AccessKey 覆盖。

`clear_credentials=true` 时更直接：Keyring secret 可先被删除，随后 source UPDATE 失败；row 仍指向原 secret_ref，但 secret 已不存在，合法 source 会在一次失败保存后立即失效。

如果原 source 之前没有 secret_ref，失败更新还会留下无法从 source row 回收的 orphan secret。

**为什么是 Bug：**

同一个 PATCH 的对外语义应是“保存成功才生效”。当前却允许 HTTP 失败但 secret truth 已变化，形成 UI/SQLite/Keyring 三方不一致。这不是 live config 可修改本身的问题，而是单请求事务边界错误。

**影响：**

- 用户看到保存失败，但后续 Import/CLEAN/AI/Training materialization 可能突然改用新凭据；
- `clear_credentials` 失败可让原本可用的存储源立即不可用；
- 新 secret 可能成为 orphan；
- 运维排查非常困难，因为 StorageSource row 的 `updated_at/config/name` 看起来没有变；
- 活动任务还可能把这种“失败保存后的隐式凭据变化”误判成外部存储故障。

**和已有 AUDIT 的区别：**

- AUDIT-044：破坏性 Storage Source PATCH 缺少活动 MATERIAL_IMPORT/rescan 生命周期 fence；
- AUDIT-169：算法产物专用 OSS 配置可在 Remote Training/Agent Conversion 中原地变化；
- AUDIT-170：单次 Storage Source PATCH 自身不是原子的——即使没有任何活动任务，只要后半段 Source row 更新失败，Secret truth 也已经改变。

因此 170 是 write-transaction consistency，不是 active-reference lifecycle 的重复。

**现有测试为什么没有发现：**

现有测试覆盖了 source create/test、wrong credential 脱敏、default_local 不可删除、rescan portable contract，但没有组合验证：

`credential mutation succeeded → repository.update failed → secret must rollback`。

也没有测试 duplicate name + credential rotation / clear_credentials 的失败原子性。

**建议最小修复方向：**

不要新增第二 Secret owner。继续使用现有 `SecretCredentialStore + StorageSourceRepository`，但为 PATCH 建立可恢复提交顺序：

1. 先完整验证所有 Source row 变更，包括 name uniqueness、default constraints、config schema；
2. 对旧 credential 做可恢复快照，或先写临时 secret/version；
3. SQLite row 与 secret pointer 成功提交后再原子切换 secret；
4. 任一步失败必须恢复原 credential / 删除临时 secret；
5. `clear_credentials` 同样只能在 source row commit 成功后正式删除旧 secret；
6. 对 `sqlite3.IntegrityError` 返回明确 409，不要冒泡 500；
7. 不要通过前端禁止同时编辑名称和凭据来掩盖，后端必须保证原子语义。

**应新增回归测试：**

- duplicate name + new credentials → PATCH 失败，旧 credential 保持不变；
- duplicate name + clear_credentials → PATCH 失败，旧 credential 仍可读取；
- source row 更新成功 + secret set 失败 → source row 不得半提交；
- 原 source 无 secret 时失败 PATCH 不留下 orphan secret；
- 成功轮换后 row.secret_ref 与 Keyring 新值一致；
- 并发两个 PATCH 至少有明确 CAS/序列化结果，不得相互回滚覆盖。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-171 — Training Create 的 task_id 幂等检查存在并发 TOCTOU；两个同 ID 请求可让失败请求覆盖已创建任务的 immutable payload.json

**级别：高**  
**模块：Training Create / Client Task ID / Idempotency / ArtifactStore / TaskRepository / TRAINING_PREPARE**

**现象：**

Training Create 已经实现了顺序重放保护：浏览器提交固定 `task_id`，后端计算 `request_identity`；如果 TaskRepository 已有同 ID TRAINING，会读取原 payload 中的 request_identity，相同请求返回 idempotent 202，不同请求返回 409。

这条顺序路径本身正确。

但当前实现是典型 check-then-act：

`shared_task_repository().get(task_id)`
→ 若不存在，离开检查阶段
→ 进入 `_algorithm_version_reference_fence(...)`
→ `atomic_write_json(task_id, 'payload.json', request_payload)`
→ `TaskRepository.create(...)`。

`_algorithm_version_reference_fence` 只序列化/校验算法 current version，不重新检查 task_id，也不锁 task-owned artifact。

因此两个**并发**的同 task_id 请求 A/B 即使 payload 不同，也都可能在最前面的 `get()` 时看到不存在。

**真实竞态：**

1. A、B 使用相同 `train_xxx` task_id，request_identity 分别为 A/B；
2. A 执行 `get(task_id)` → None；
3. B 执行 `get(task_id)` → None；
4. A 先进入 algorithm-version fence；
5. A 写 `artifacts/<task_id>/payload.json = payload A`；
6. A `TaskRepository.create()` 成功，task row 已引用这个 `payload.json`；
7. A 离开 fence；
8. B 因同算法 fence 串行，随后进入；它不会重新做 task existence/request_identity CAS；
9. B 直接把同一路径 `payload.json` 原子替换成 payload B；
10. B 再调用 `TaskRepository.create()`；SQLite 主键冲突，B 请求失败；
11. 但 A 的正式 TRAINING task row 仍存在，并且它引用的 `payload_ref='payload.json'` 已经被失败的 B 请求改成 payload B。

所以最终出现：

- TaskRepository identity/created_at/resource_key/priority 来自 A；
- task-owned payload / request_identity / selected material / labels / resource request 等可能来自 B；
- B 的 HTTP 请求失败，但它已经改变 A 的不可变训练输入；
- TRAINING_PREPARE 随后读取的是被覆盖后的 B payload。

**为什么算法版本 fence 不能保护：**

它反而只把两个 caller 串行到“先写 artifact、后 INSERT task”这一段，却没有在锁内重新执行 task-id CAS。B 在等待 fence 前已经通过了旧的 existence check，因此拿到 fence 后仍会覆写 artifact。

**用户真实可达场景：**

- 浏览器/反向代理对同一 POST 做并发重试；
- 用户双击/两个前端事件同时提交同一弹窗固定 task_id；
- 同一 iteration draft task_id 在两个标签页同时提交；
- 第一次网络超时期间用户修改了参数/素材后再次触发相同 task_id 的请求，而第一次实际上仍在服务端执行。

普通前端通常会用 `submitting` 降低双击概率，但网络/代理/多标签页/程序化客户端并不受前端单实例变量保护。后端既然把 task_id 定义为 idempotency key，就必须对并发重放也成立。

**影响：**

- 已创建训练任务的 immutable request 可被一个最终 409/500 的请求篡改；
- selected material、split、labels、epochs/resource 参数可能与创建响应/用户意图不同；
- `request_identity` 本身也被覆盖，后续真正的 A 重放会被错误判为 conflicting request，而 B 重放反而可能被视为原请求；
- TRAINING_PREPARE、Snapshot、lineage、资源解析可能消费与 task row 不一致的输入；
- job.json 后续又按 A caller 本地变量写入，可能与 payload B 再形成第三份分裂真相。

这是训练准确性与任务不可变性问题。

**和已有 AUDIT 的区别：**

- AUDIT-151：用户看到的 baseVersionId 没进入请求，属于 iteration-base admission CAS 缺失；
- AUDIT-139/142：训练完成归档阶段的 version/same-task 并发 identity；
- AUDIT-171：训练**创建阶段** client task_id 的并发 idempotency TOCTOU，失败请求可以覆盖已创建 task 的 payload artifact。

没有现有 AUDIT 覆盖这个 request artifact overwrite race。

**现有测试为什么没有发现：**

当前代码明确实现了 sequential idempotency 分支，因此单线程测试很容易全部通过：

- 第一次 create；
- 第二次相同 payload → idempotent；
- 第二次不同 payload → 409。

但缺少一个 barrier/concurrency test：两个 caller 必须都在 `get(task_id)==None` 后再继续。TaskRepository 的 SQLite PRIMARY KEY 只能保证两条 task row 不会同时存在，不能保护已经在 INSERT 之前写入的 ArtifactStore 文件。

**建议最小修复方向：**

不要新增第二套 Training create owner。最小方向是在现有 create admission 上建立 task-id 级原子 fence：

1. 对 client task_id 使用 task-owned FileLock / repository transactional idempotency owner；
2. 在锁内重新读取现有 task；
3. 若存在，比较持久化 request_identity 后只做 idempotent-return / 409；
4. 若不存在，先准备临时 payload artifact，不得直接覆盖正式路径；
5. Task row 与 payload identity 必须作为同一 create protocol 发布；
6. 只有 INSERT 成功后才能把临时 artifact 原子 promote 为该 task 的正式 immutable payload，或让 repository create 同时校验 artifact digest；
7. create 主键冲突时不得留下/覆盖任何已有 task artifact；
8. prepare child 的创建也应只基于已经成功绑定的 parent request identity。

不要依赖前端 `submitting` 防并发，也不要简单在 UNIQUE error 后把 payload 写回——那仍会和已启动 Worker 竞态。

**应新增回归测试：**

- 同 task_id + 相同 payload 两个并发 create → 只创建一个 task，payload identity 一致，两边得到同一任务/幂等结果；
- 同 task_id + 不同 payload，并发 barrier 让两边先通过 precheck → 一个成功，一个 409，成功 task 的 payload 必须保持成功 caller 的内容；
- loser 在 winner INSERT 后、自己 artifact write 前恢复 → 不得覆盖；
- loser 已生成临时 artifact 后 winner 完成 → loser cleanup 不得删除 winner artifact；
- parent TRAINING 与 TRAINING_PREPARE 最终绑定同一 request identity；
- job.json/request payload/frozen input 的 algorithm/material/resource truth 不分裂；
- 顺序相同请求重放仍保持现有 idempotent 202；
- 顺序不同请求重放仍保持 409。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-172 — 父 TRAINING 已创建但 TRAINING_PREPARE child 创建失败后不可通过同 task_id 重试恢复；idempotent create 永久跳过缺失 child

**级别：高**  
**模块：Training Create / TRAINING_PREPARE / Parent-Child Lifecycle / Idempotency / Crash Recovery**

**现象：**

`_enqueue_explicit_training()` 当前先创建父 `TRAINING`，然后再创建确定性 child：

`prepare_task_id = 'trainprep_' + task_id`

真实顺序是：

1. 写父 task `payload.json`；
2. `TaskRepository.create(TRAINING)`；
3. 写 child `payload.json`；
4. `TaskRepository.create(TRAINING_PREPARE)`。

如果第 3/4 步抛异常，代码会调用：

`fail_queued_precondition(parent, 'TRAINING_PREP_TASK_CREATE_FAILED: ...', status=BLOCKED_BY_ENVIRONMENT, stage='training_input_preparation_failed')`

然后把异常继续抛给请求方。

此时父 TRAINING 已经正式存在，但 PREPARE child 可能完全不存在。

**恢复漏洞：**

浏览器/调用方按同一 task_id、同一 payload 重试 `/train/start` 时，函数最前面的 idempotency 分支发现父 TRAINING 已存在且 `request_identity` 相同，就立即返回 202：

`return {'ok': True, 'task': existing_task, 'idempotent': True}`

它在这里直接 return，不再检查：

- `training_prepare_task_id` 对应 child 是否存在；
- child 是否处于可恢复状态；
- 父任务是否正是 `training_input_preparation_failed`；
- child payload 是否已经写好但 row 缺失。

因此一次 parent-create / child-create 中间故障会把同 task_id 固化成“父任务存在、准备任务缺失”的永久半创建状态。

**真实调用链：**

训练弹窗提交固定 task_id
→ `_enqueue_explicit_training()`
→ parent `TaskRepository.create()` 成功
→ child artifact write / child repository INSERT 因磁盘、SQLite busy/IO、异常等失败
→ parent 变 `BLOCKED_BY_ENVIRONMENT + training_input_preparation_failed`
→ HTTP 请求失败
→ 用户/代理重放同 task_id
→ existing parent + same request_identity
→ idempotent 202 直接返回
→ 不补 `trainprep_<task_id>`
→ Scheduler 永远没有 TRAINING_PREPARE 可领取
→ parent 永远无法进入 READY/真正训练。

**为什么现有 recovery 不会兜底：**

`training_recovery_api.py` 的 checkpoint recovery 面向训练后段失败，`RECOVERABLE_FAILURE_STAGES` 只包括 `final_validation / post_training` 等可复用 checkpoint 场景。

当前 `training_recovery_tasks.py` 也没有发现“扫描 parent TRAINING 并 ensure 对应 TRAINING_PREPARE child”的 owner。

Scheduler 只能领取已经存在的 child row，不能凭 parent payload 自行创造缺失 child。

所以这是 create protocol 的缺口，不是普通 Worker retry。

**用户真实可达场景：**

- 创建训练时 SQLite/磁盘在 parent 成功后瞬时失败；
- child task log/artifact 创建异常；
- 进程在 parent create 和 child create 之间崩溃/被杀；
- 网络看到第一次请求失败后，浏览器使用固定 task_id 安全重试。

固定 task_id 本来就是为了让网络重放安全；当前恰好在最需要 idempotent recovery 的半提交点无法恢复。

**影响：**

- 用户重试得到 202/idempotent，但任务实际上没有任何 PREPARE worker 会执行；
- 父任务永久 BLOCKED_BY_ENVIRONMENT；
- 用户只能放弃 task_id、重新开一个新训练，产生垃圾父任务；
- 任务中心可显示已受理/失败，但真正缺失的是 parent-child lifecycle，而不是训练数据/GPU；
- 自动化客户端可能不断重放同 task_id，却永远无法恢复。

**和已有 AUDIT 的区别：**

- AUDIT-087：用户取消 PREPARING parent 时没有同步取消已经存在的 TRAINING_PREPARE child；
- AUDIT-140：训练完成归档后 auto-conversion child 的 crash window；
- AUDIT-171：并发同 task_id create 可覆盖 parent immutable payload；
- AUDIT-172：parent 已成功、PREPARE child **尚未创建/创建失败** 的半提交状态无法被 idempotent replay 修复。

这是相反方向的 parent-child 缺失问题，不是 087/140/171 的重复。

**现有测试为什么没有发现：**

现有 Training Prepare 集成测试覆盖：

- child 已存在后 Worker 成功/失败；
- Prepare 失败会把 parent 标成 BLOCKED；
- remote preparation 各种输入/存储异常。

Training create/idempotency 测试主要覆盖正常 parent+child 创建和顺序重放。

缺少 fault-injection 测试：

`parent create succeeds → child create raises → same task_id POST replay`。

**建议最小修复方向：**

不要新增第二套 Training Prepare owner。让 Training Create 的 idempotent path具备 `ensure child` 语义：

1. existing parent + same request_identity 时，先读取 parent payload 中 frozen `training_prepare_task_id`；
2. 如果 parent 仍在 PREPARING/prepare-failed 且 child 缺失，幂等地补建同一个确定性 child；
3. child 已存在则验证 project/kind/payload identity 一致，不重复创建；
4. parent-child create 最好通过显式 journal / ensure operation 收口，而不是“parent INSERT 后裸 create child”；
5. 进程启动/bootstrap 可以额外扫描合法半创建 parent 做 reconciliation，但不能成为第二 owner；
6. 补建成功后应把 parent 从 create-precondition BLOCKED 恢复到 `training_input_pending`，让正常 Prepare handler继续；
7. 不能把所有 `BLOCKED_BY_ENVIRONMENT` 都自动重试，只对有确定性 `TRAINING_PREP_TASK_CREATE_FAILED` + child 缺失证据的 create half-commit 做恢复。

**应新增回归测试：**

- parent create 成功、child create 注入失败 → parent BLOCKED、child 不存在；
- 相同 task_id/payload 重放 → child 被补建且只存在 1 个；
- 补建后 parent 可继续 PREPARE→READY；
- child payload 已写但 row 缺失 → replay 安全补 row；
- child row 已存在 → replay 只返回幂等，不重复；
- child ID 被其它 kind/project 占用 → 明确 409，不篡改；
- 不同 request_identity 重放仍按现合同 409；
- 进程在 parent/child 间崩溃后 reconciliation 能恢复。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-173 — Storage Rescan 更新同 material_id 的图片内容时不会失效既有正式 GT；旧图片 Annotation 可继续挂在新内容上并进入训练

**级别：高**  
**模块：Storage Rescan / Material Identity / Annotation Ground Truth / Training Accuracy**

**现象：**

当前 canonical Storage Rescan 明确允许对同一：

`storage_source_id + object_key`

保留原 `material_id`，但在内容变化时按默认策略：

`changed = update`

更新 MaterialRepository 中的：

- `content_sha256`
- `size_bytes`
- `etag`
- `width / height`

`StorageRescanHandler._classify_rescan_row()` 会把 hash / size / etag 任一变化归类为 `CHANGED`，而 `_apply_rescan()` 会：

`materials.reconcile_storage_batch(...)`

把这个 CHANGED 对象的新内容身份正式写回原 material_id。

问题是：

> 内容 identity 的更新与 Annotation Ground Truth 的有效性没有建立绑定。

对于：

`import_format = images`

`_apply_annotation_rescan()` 直接返回，不会触碰 AnnotationRepository。

因此一张原本：

```text
material_id = A
content_sha256 = H1
AnnotationRepository[A] = smoke boxes for H1
```

在对象存储相同 key 被替换为另一张图 H2 后，用户执行默认 Rescan：

```text
material_id = A
content_sha256 = H2
AnnotationRepository[A] 仍是 H1 的 smoke boxes
```

正式 GT 会继续被视为 A 的有效标注。

结构化 YOLO / COCO / VOC Rescan 也没有自动解决这个问题。

内容变化分类 `CHANGED` 与 annotation delta 是两套独立策略：

- `changed = update`
- `annotation_removed = keep`（默认）
- `annotation_conflicts = keep`（默认）

因此即使外部新内容已经没有旧 annotation，或 annotation 进入 conflict，默认策略仍可能更新图片字节但保留旧平台 GT。

**真实调用链：**

当前 Storage Source 页面  
→ 创建：

`POST /api/v61/projects/{project_id}/storage-sources/{source_id}/rescan`

→ Rescan scan/review  
→ 用户确认默认 policy：

`changed=update`

→ `StorageRescanHandler._apply_rescan()`  
→ `CHANGED` object 重新校验 source bytes  
→ invalidate old content cache  
→ `MaterialRepository.reconcile_storage_batch()`  
→ 原 material_id 被更新为新 `content_sha256 / size / etag / dimensions`  
→ 对 images-only rescan：annotation reconcile 不运行  
→ 对 structured rescan：annotation policy 独立处理，默认 keep 可继续保留旧 GT  
→ 后续 Training Picker / Snapshot 仍按同 image_id 读取 AnnotationRepository  
→ 旧图片框可被用于新图片训练。

**用户真实可达场景：**

1. OSS 中 `camera/a.jpg` 原来是图片 H1；
2. 平台已导入为 material A，并完成人工/AI 正式标注；
3. 外部系统用同 object_key 覆盖成完全不同图片 H2；
4. 用户在平台执行“重新扫描”；
5. 系统识别 CHANGED；
6. 用户采用默认“内容变化=更新”；
7. Material A 更新为 H2；
8. 原 AnnotationRepository[A] 没有被失效；
9. 训练时 H2 仍携带 H1 的旧框/旧标签。

**为什么这是 Ground Truth Bug：**

Annotation Ground Truth 语义必须至少绑定：

`image identity + content identity`

只绑定稳定 material_id 不够。

Rescan 明确允许 stable material_id 指向新的 content hash，因此旧 GT 不能继续被默认当作同一图片的已确认事实。

否则：

- 框坐标可能完全落在错误目标上；
- 图片尺寸改变后旧坐标甚至可能越界/语义错误；
- confirmed_empty 也可能错误迁移到新内容；
- 新内容真实含 fire，但旧 H1 是 confirmed_empty，会被当成负样本；
- Training Snapshot 本身无法发现，因为它只看到“正式 Annotation + 当前 Material”。

**和已有 AUDIT 的区别：**

- AUDIT-099：Rescan 要**写新 Annotation**时，stale check 与 commit 分离，可能覆盖并发人工修改；
- AUDIT-104：Rescan 已成功写 GT 后 crash，applied marker 未原子提交导致恢复误判失败；
- AUDIT-152：CLEAN retry 把 H1 的清洗结果复用到 H2；
- AUDIT-157：AI Candidate 在 H1 生成，H2 后仍可人工确认写入；
- AUDIT-173：**已经正式存在于 AnnotationRepository 的 H1 Ground Truth，在 Rescan 把 material 内容更新为 H2 时没有失效。**

这是更底层的 material-content / formal-GT identity 绑定缺失。

**现有测试为什么没有发现：**

现有 Rescan 测试重点覆盖：

- CHANGED / MISSING / NEW 分类；
- content hash 再校验；
- structured annotation changed/conflict/removed policy；
- Annotation CAS；
- crash recovery。

这些测试通常分别验证：

“Material 内容更新正确”

和

“Annotation policy 正确”。

没有组合测试：

`same material_id + content hash H1→H2 + 现有正式 GT`

并断言旧 GT 必须进入 stale/review 状态，不能继续被训练读取。

**建议最小修复方向：**

不要新增第二 Annotation owner，也不要简单删除所有标注。

建议在现有 canonical owners 上补 content identity contract：

1. 正式 Annotation 记录应能关联其确认时的 `source_content_sha256`（或等价 immutable content revision）；
2. Rescan 对 CHANGED material commit 前必须检查当前正式 GT；
3. 若 GT 绑定旧 hash：
   - 不得继续当作当前内容的正式训练 GT；
   - 应转为明确 stale / needs_review，或由 canonical AnnotationRepository 提供 invalidate-for-content-change 操作；
4. structured rescan 只有在用户明确确认新的外部 annotation 且新 annotation 与 H2 identity 绑定后，才能用新 GT 替换旧 GT；
5. confirmed_empty 同样必须失效，不能自动迁移；
6. Material searchable projection 必须与 Annotation owner 同步更新，避免 UI 仍显示“已标注”；
7. Training Picker / Snapshot 应 fail-closed 拒绝 content hash 与 GT revision 不匹配的行；
8. 不要通过“material_id 永远不变所以 annotation 也不变”来继续掩盖内容替换。

**应新增回归测试：**

至少覆盖：

- images rescan：H1 annotated → same key H2 changed/update → H1 GT 不得继续作为正式 current GT；
- H1 confirmed_empty → H2 → 不得继续作为新图负样本；
- dimensions 改变 → 旧 box 不得继续进入 Snapshot；
- structured rescan 有新 annotation 且用户确认 → 新 GT 绑定 H2 后可训练；
- structured rescan annotation_removed=keep 时，内容已 H1→H2 → “keep”不能等于“旧 GT 仍可训练”，只能保留为历史/stale evidence；
- unchanged hash H1→H1 → 原 GT 保持有效；
- Training Picker / Snapshot 对 GT-content mismatch fail-closed；
- Material projection 与 AnnotationRepository stale 状态一致。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-174 — Source Import 终态局部刷新可被旧 Material page in-flight 去重吞掉；导入成功后当前素材页继续显示导入前旧快照，且 CI 已真实红灯

**级别：中高**  
**模块：Source Import / Material Pagination / Completion Refresh / Request Coalescing / Frontend Runtime**

**现象：**

当前 v36 “地址读取” Source Import 完成后，`refreshSourceImportTasksV36()` 的终态分支已经刻意避免 broad reload，并只做：

- `refreshLabels414(false)`
- 当前在“数据集”页时 `reloadMaterialPage61()`

这个设计方向本身是对的。

但 canonical Material Pagination Runtime 的：

`loadMaterialPage61()`

会按：

```text
[projectId, filterSignature, cursor, page]
```

生成 `flightKey`，并执行：

```text
if (pageLoadFlight && pageLoadFlightKey === flightKey) {
    return pageLoadFlight
}
```

也就是说，同一页同一筛选只要已经有请求在 flight，后续“刷新”不会建立新 generation，也不会等待旧请求结束后再强制 refetch，而是直接复用旧 Promise。

`reloadMaterialPage61()` 虽然语义叫 reload，但当前仅：

- invalidate full-pool cache；
- `loadMaterialPage61({reset:true})`；

它没有让当前 page flight 失效，也没有 `force` / refresh generation。

因此 Source Import completion 的局部刷新可能被**导入完成前已经启动的旧 Material GET**吞掉。

**当前 HEAD 已有真实 CI failure：**

GitHub Actions：

`Frontend Runtime Stabilization / browser-navigation`

run:

`37643621523`

job:

`112868578169`

失败用例：

`tests/browser/source-import-completion-scope.spec.mjs`

真实断言：

> terminal source import did not refresh the current paged material domain

结果：

```text
Expected: > 0
Received: 0
materialGets = 0
```

同时该测试的：

`labelGets > 0`

通过，说明终态 completion 分支已经执行；缺失的是当前分页素材域的新 GET。

**真实调用链：**

数据集页已有分页素材加载  
→ `loadMaterialPage61()` 发起旧 `/api/v61/.../materials` 请求  
→ `pageLoadFlight` 保持 active  
→ v36 Source Import 任务从 queued/running 进入 done  
→ `refreshSourceImportTasksV36()` 命中 terminal branch  
→ `refreshLabels414(false)` 正常发新请求  
→ `reloadMaterialPage61()`  
→ reset 后得到与旧 flight 相同的 `flightKey`  
→ `loadMaterialPage61()` 直接 `return pageLoadFlight`  
→ **没有发新的 /materials GET**  
→ 旧 flight 返回的是导入完成前的素材列表  
→ 页面继续显示旧结果。

**为什么这不是普通请求去重：**

请求 coalescing 只在多个调用要求“同一时刻的同一份数据”时安全。

Source Import completion 是明确的 mutation boundary：

> 后端素材域刚刚发生了变化。

completion 之后的 refresh 必须建立一个比 mutation 更新的 read generation。

当前 key 只包含“查询条件”，不包含：

- mutation generation；
- material repository revision；
- force-refresh epoch；
- completion token。

因此它错误地把：

“导入前读”

和

“导入后必须重新读”

当成同一请求。

**用户真实可达场景：**

1. 用户打开数据集页；
2. 当前分页素材请求尚未完成；
3. 后台地址读取任务恰好完成；
4. 页面轮询读到 `done`；
5. completion owner 触发局部刷新；
6. 刷新被旧 flight 合并；
7. 用户看到任务“导入完成”，但当前素材列表里没有新增图片；
8. 只有后续手动刷新、切页或其它事件再次触发 Material GET 后才出现。

大项目、对象存储延迟、网络慢时窗口更明显。

**影响：**

- “任务已完成”与素材页可见真相不一致；
- 用户可能误以为导入失败或重复导入；
- 导入后立即进行清洗/标注时看不到新素材；
- CI timing window 会间歇性红灯；
- rerun 绿不能证明源码没有问题，因为竞态取决于旧 flight 是否已在 completion 前结束。

**和已有 AUDIT 的区别：**

- AUDIT-052：ZIP completion 对 Label Schema 有两个 owner，导致重复 GET；
- AUDIT-067：Storage Import focused/background pollOwner handoff 丢失；
- AUDIT-120：非当前页面 poller/visibility 生命周期；
- AUDIT-143/159：页面刷新造成重型读取；
- AUDIT-174：completion owner 已正确选择“局部素材刷新”，但 canonical Material Pagination 的 in-flight coalescing 缺 mutation generation，使这个刷新本身被旧读吞掉。

**现有测试为什么有时通过：**

用例已经正确锁定：

- 不允许 broad project reload；
- labels 必须刷新；
- current paged materials 必须刷新。

它是否红灯取决于 completion 时刻是否仍存在相同 `pageLoadFlight`。

如果旧素材请求先结束：

- `pageLoadFlight=null`
- completion 会发新 GET
- 测试通过。

如果旧请求仍在：

- completion 复用旧 Promise
- `materialGets=0`
- 测试失败。

这正是竞态测试应暴露的生产 bug，不应通过延长 sleep 或放宽断言修测试。

**建议最小修复方向：**

不要恢复 broad `loadRelated()`，也不要新增第二 Material page owner。

继续复用 `MaterialPaginationRuntime61`，补明确的 mutation-aware refresh 语义：

1. `reloadMaterialPage61()` / runtime.refresh({force:true}) 必须能创建新的 read generation；
2. force refresh 不得直接复用 mutation 前的同-key `pageLoadFlight`；
3. 可选择：
   - bump refresh epoch 并纳入 flight key；或
   - 让旧 serial stale，再启动新 flight；或
   - 等旧 flight settle 后立即执行一次强制 refetch；
4. completion 刷新只继续读取当前分页域和 summary，不允许退回全项目 hydrate；
5. stale old flight 即使晚返回，也不得覆盖 force refresh 的新 generation；
6. ZIP Import / Storage Import / AI Commit / Label Remap 等 mutation completion 若调用同一个 reload owner，也应自动继承同一修复，而不是每个业务各造一套 workaround。

**应新增/保留回归测试：**

至少覆盖：

- page material GET 仍 in-flight 时 Source Import terminal → 必须出现 completion 后新 material GET；
- old flight 晚于 new force refresh 返回 → old result 不得覆盖新页；
- old flight 已完成 → completion 只发 bounded material GET，不 broad reload；
- labels + materials 均局部刷新；
- Source Import completion 不触发 project/datasets/images/algorithms/publish/model-config broad fan-out；
- ZIP/Storage Import/AI Commit 调用 `reloadMaterialPage61()` 时也具备 force freshness；
- 不放宽当前 `source-import-completion-scope.spec.mjs` 断言。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-175 — 算法版本删除/回退先破坏性删除新畅联远端 Version、后提交本地版本事务；中间崩溃/本地 commit 失败后 auto-publish 会把用户刚删除的远端版本重新发布

**级别：高**  
**模块：Algorithm Version Retirement / ChangLian Remote Delete / External Publication / Saga Recovery / Auto Publish**

**现象：**

当前本地算法版本删除与回退都在 `model_delivery_version_fence` 内按以下顺序执行：

1. dependency check；
2. `publish_service.delete_version_for_rollback()`；
3. 新畅联 `version_remove()` 真正删除远端 Version；
4. publication（若存在）尝试 patch 为 `DELETED`；
5. 才执行本地 `AlgorithmSqlStore.delete_version_with_operation()` 或 `rollback_version()`，并在这个阶段才持久化本地 version operation journal。

因此远端 destructive action 与本地 durable delete/rollback intent 之间存在 crash window。

**关键恢复语义目前方向相反：**

`publication_requires_sync()` 对 status != `PUBLISHED`（除 BLOCKED_CONFIG）返回 true。

`auto_retry_due()` 对 `DELETED` 立即返回 true。

所以如果：

- 新畅联删除成功；
- publication 已标成 `DELETED`；
- 本地 version transaction 随后失败或进程崩溃；

那么本地算法版本仍然存在，下一轮 `run_auto_publish_once()` 会把这个版本视为“需要发布”，再次调用 `publish(... automatic=True)`，从而把用户刚删除的远端 Version 重建。

如果进程更早崩溃在：

`client.version_remove()` 成功
→ publication 还没 patch DELETED

之间，本地 publication 仍是 `PUBLISHED`。后续 `reconcile_published_remote()` 发现 `external_algo_version_id` 已不在远端版本列表，会把 publication 降为 `PENDING / REMOTE_VERSION_MISSING`；随后同一个 auto-publish owner仍会重新发布。

所以两种 crash 点最终都倾向：

> 恢复“发布”，而不是恢复用户的“删除/回退”。

**真实调用链：**

`DELETE .../versions/{version_id}`
或
`POST .../versions/{target}/rollback`
→ `model_delivery_version_fence`
→ `delete_algorithm_version()/rollback_algorithm_version()`
→ dependency_check
→ `delete_version_for_rollback()`
→ `client.version_remove([external_version_id])`
→ remote Version 已永久删除
→ （crash / AlgorithmSqlStore commit error）
→ local algorithm version/current pointer 仍保留
→ 无 durable delete-intent journal
→ auto publisher 扫到该 local successful version
→ publication DELETED/PENDING 或后续 remote reconcile 降级
→ `publication_requires_sync=true`
→ `publish(... automatic=True)`
→ 远端 Version 被重新创建。

**现有异常处理为什么不够：**

正常 Python exception 路径已经会抛：

- `ALGORITHM_DELETE_LOCAL_COMMIT_FAILED_AFTER_REMOTE_DELETE`
- `ALGORITHM_ROLLBACK_LOCAL_COMMIT_FAILED_AFTER_REMOTE_DELETE`

并提示联系运维。

但这只是同步请求错误文案，不是 durable recovery state。

而且真正的进程 crash / kill -9 发生时，catch 根本不会运行；version operation 又是在 remote delete **之后**才写，因此重启后没有任何 durable intent 能告诉系统：

> 这个 local version 正处于“远端已删、待完成本地 retirement”。

**为什么现有 reconciliation 不能修：**

- External master-data sync 只会在外部 Product 整体消失时 purge local external algorithm，不会因某一个发布版本缺失而继续本地 version retirement；
- External publication remote reconciliation 的明确目标是“修复发布映射”，远端 Version missing 时会降为 PENDING，交回 publish owner；
- auto-publish 对 DELETED/PENDING local publication 都会重新同步，只要 local algorithm version 仍存在且成功可发布。

因此现有 recovery owner会“复活远端版本”，而不是完成删除 saga。

**用户真实可达场景：**

1. 一个外部算法 current=v2，v1 为历史版本；
2. v1/v2 已发布到新畅联；
3. 用户删除 v1，或从 v2 回退 v1（产品合同要求删除 current v2）；
4. 新畅联 version_remove 成功；
5. 服务器在本地 AlgorithmSqlStore transaction 前崩溃，或本地事务因磁盘/SQLite I/O 失败；
6. 重启后本地仍认为被删版本存在；
7. auto-publish 再次创建远端版本；
8. 用户看到“删除/回退失败”，但远端版本过一会又出现，且可能获得新的 external_algo_version_id / Weight IDs。

**影响：**

- 删除/回退用户意图不具备 crash consistency；
- 远端版本可能被自动复活；
- remote/local version identity 发生新一轮重绑定；
- Weight 映射可能全部重新创建；
- 审计上无法证明一次 delete 是否最终被尊重；
- 运维重试可能再次执行 remote delete，增加歧义；
- 回退场景尤其危险：local current 仍可能指向本应被删除的 current version。

**和已有 AUDIT 的区别：**

- AUDIT-091/092/093：Remote Training / Agent result finalization 的半提交与恢复；
- AUDIT-139：训练完成 attach current_version_id 的 CAS；
- AUDIT-154：auto-publish 的无界扫描/磁盘 I/O；
- AUDIT-175：版本 retirement saga 中 **remote destructive delete 发生在 durable local delete intent 之前**，且现有 auto-publish reconciliation 会执行相反动作——重新发布。

**现有测试为什么没有发现：**

当前测试主要覆盖：

- remote delete 失败时不得只删本地；
- ambiguous remote identity fail-closed；
- local transaction 抛异常时返回明确错误；
- publication remote drift 后能够自动 repair/re-publish；
- rollback/delete dependency fences。

缺少 fault-injection 组合：

`remote version_remove success → crash/local commit failure → process restart → auto-publish/reconcile`

以及最终必须保持“删除意图”的断言。

**建议最小修复方向：**

不要新增第二套 publication owner。

应在现有 algorithm version operation / publication owner上把 retirement 做成 durable saga：

1. 在调用 remote `version_remove` 前，先原子持久化 `delete_pending / rollback_pending` operation，冻结 algorithm/version/external_version identity 和 expected current；
2. publication/auto-publish 必须把 active retirement intent 当硬 fence，禁止重新发布；
3. remote delete 成功后持久化 `remote_deleted` phase；
4. 再提交本地 AlgorithmSqlStore delete/rollback；
5. 重启/startup/retry 根据 phase 查询远端 exact identity：
   - 已删 → 继续本地 retirement；
   - 仍在 → 幂等重试 remote delete；
   - ambiguous → fail-closed 等人工处理；
6. operation 完成后再允许清理 publication/model artifacts；
7. 不要用“把 auto-publish 关掉”作为修复，也不要新增第二 reconciliation runtime。

**应新增回归测试：**

- remote delete 成功后、本地 commit 前 crash → 重启后不得 auto-republish；
- publication 已 DELETED、本地版本仍在 → active retirement intent 阻止 auto publish；
- publication 仍 PUBLISHED、remote 实际已缺失 → reconciliation 不得降 PENDING 后重新发布，应继续 retirement；
- local commit transient fail → retry saga 幂等完成；
- rollback current v2→v1 的同一 fault window；
- remote delete 未真正成功 → 不得提交本地 retirement；
- ambiguous external identity → 保持 fail-closed；
- retirement 完成后 publication/model artifact cleanup 仍由现有 owner执行。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-176 — 算法版本 retirement 不检查 Online Feedback pending_review 引用；版本删除后持久化人工待复核反馈永久无法 Confirm

**级别：高**  
**模块：Algorithm Version Retirement / Online Feedback / Human Review / Prediction Evidence / Lifecycle Dependency**

**现象：**

当前 Online Feedback 是持久化人工审核工作流。OnlineFeedbackRepository 明确保存 status、algorithm_id、version_id、model_sha256、prediction_id，并为 `(algorithm_id, version_id, created_at)` 建立索引。

用户将正式算法版本的真实 Deployment Test 提交抽检后，feedback 进入 `pending_review`，等待人工 Confirm / Dismiss。

但当前算法版本 DELETE / rollback 的 `_algorithm_version_active_references()` 只验证 active TRAINING、MODEL_CONVERSION、DEPLOYMENT_TEST，完全没有检查 OnlineFeedbackRepository 中 `status='pending_review'` 对目标 algorithm/version 的引用。因此版本可以在人工反馈尚未处理时被正常删除。

**删除后为什么这条 feedback 无法继续 Confirm：**

`confirm_online_feedback()` 每次确认都会调用 `_online_prediction_evidence(project_id, staged['prediction_id'])`。该函数明确执行 `_algorithm_version_for_action(project_id, evidence['algorithm_id'], evidence['version_id'])`，随后重新计算 `_online_feedback_version_model_sha256(version)` 并要求与 evidence/model SHA 一致。

一旦版本已被 DELETE / rollback retirement 删除，`_algorithm_version_for_action()` 找不到 version，Confirm 返回 404/409；feedback 仍保持 `pending_review`。Dismiss 不依赖 live version，因此用户最终只能忽略，不能把已经提交的正确/误检证据提升为正式素材/GT。

**真实调用链：**

Quality Center 正式算法版本检测成功
→ `POST /api/v64/.../deployment-tests/{task_id}/feedback-evidence`
→ 冻结 prediction evidence：algorithm_id/version_id/model_sha256/input_sha256
→ `POST /api/v63/.../online-feedback`
→ OnlineFeedbackRepository.stage()
→ status=pending_review
→ 用户暂未处理
→ 另一个用户 DELETE 历史版本，或 rollback 删除当前版本
→ version dependency check 看不到 pending feedback
→ 算法版本及专属模型产物成功 retirement
→ feedback 仍出现在待复核工作台
→ 用户点击确认
→ `_online_prediction_evidence()` 重新要求 version 存在
→ 稳定失败。

**为什么这是生命周期 Bug：**

系统同时建立了两个互相矛盾的合同：

1. Online Feedback 把 `pending_review` 当作需要人工处理的 durable business queue；
2. Confirm 又要求来源 algorithm version 仍是可验证的正式版本。

既然确认阶段依赖 version 生命周期，那么 pending feedback 就必须是版本 retirement 的 active dependency；或者 feedback staging 时必须把后续确认所需的不可变证据完整冻结，使 Confirm 不再依赖 live version。当前两者都没有做到。

**更早的同类窗口：**

完成的 Deployment Test 在用户点击“提交抽检反馈”前也可能被版本删除，随后 feedback-evidence promotion 因版本不存在而无法执行。这个阶段仍可解释为“历史检测尚未进入人工反馈工作流”。但已经成功 stage 成 pending_review 的反馈不同：平台已经接受并持久化了用户的复核任务，之后再由版本 retirement 把它变成不可处理待办，属于明确 lifecycle drift。

**影响：**

- pending_review 可永久卡死；
- 工作台持续显示复核按钮，但 Confirm 稳定失败；
- 用户只能 Dismiss 合法反馈，造成反馈样本丢失；
- confirmed feedback / supplement candidate 数据闭环被截断；
- 版本删除成功与人工审核队列真相不一致；
- 历史 prediction evidence 仍在磁盘，却因为 live version metadata 被删而无法使用。

**和已有 AUDIT 的区别：**

- AUDIT-056：最近 100 条 bounded history 会把旧 pending_review 挤出 UI；
- AUDIT-108：Confirm 与 Dismiss 并发时终态 CAS 和 Material/Annotation side effect 不原子；
- AUDIT-135：旧同步 predict 是第二推理 Runtime；
- AUDIT-175：external version retirement 的 remote-delete/local-delete saga crash consistency；
- AUDIT-176：版本 retirement 没把已经存在的 pending human-review feedback 当 active dependency，导致 durable feedback 被删除来源版本后永久无法 Confirm。

**现有测试为什么没有发现：**

Online Feedback 测试覆盖 evidence identity/model SHA、stage/confirm/dismiss、Material/Annotation promotion、幂等与并发；版本 retirement 测试覆盖 active Training、Conversion、Deployment Test、external deletion 与 cleanup。缺少跨 owner 测试：`pending_review feedback → delete/rollback source version → confirm`。

**建议最小修复方向：**

不要新增第二 Online Feedback owner。两种可接受方向必须择一并保持单一合同：

1. **Lifecycle pin（最小）**：在 `_algorithm_version_active_references()` 中通过 OnlineFeedbackRepository 查询目标 version 的 pending_review；存在时禁止 delete/rollback，并返回明确引用数量/原因。confirmed/dismissed 不必永久 pin。
2. **Immutable evidence self-containment（更彻底）**：staging 时冻结后续 Confirm 所需的正式 model identity / label contract 等不可变证据，使 Confirm 不再依赖 live version，但仍保持完整 fail-closed 校验。

不要通过“Confirm 找不到版本时跳过 SHA 校验”来修，这会放宽现有安全合同。

**应新增回归测试：**

- pending_review 引用 v1 → DELETE v1 返回 409；
- current v2 有 pending_review → rollback 删除 v2 返回 409；
- Dismiss pending 后 → version 可删除；
- Confirm pending 后 → version 可按现有 retention policy 删除；
- unrelated version 的 pending feedback 不阻塞目标 version；
- pending feedback 数量很大时使用 indexed existence/count query，不全表 hydrate；
- 若采用 immutable evidence 方案，version 删除后 Confirm 仍完整验证 frozen model/evidence identity；
- 保留现有 model SHA fail-closed 测试。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-177 — 标签删除/改编码/合并不检查 Online Feedback pending_review；待复核预测使用历史标签后可永久无法 Confirm

**级别：高**  
**模块：Label Governance / Online Feedback / Human Review / Label Identity / Lifecycle Dependency**

**现象：**

Online Feedback 的 prediction evidence 会冻结检测结果中的 label 文本，但 Confirm 并不是按冻结时标签合同直接提交。

`confirm_online_feedback()` 在 label_governance_fence 内重新读取当前项目标签，并通过 `_online_feedback_prediction_boxes(current_project, evidence)` 把 prediction label 重新映射到当前 canonical class。

该映射只构造：

- 当前 active label 的 `code -> item`；
- 当前 active label 的 `display_name -> item`；

不读取 inactive/merged source label，也不根据 `merged_into` 把历史 code 自动解析到新 canonical label。

与此同时，当前标签 DELETE / code rename / label unify retirement 的引用保护主要检查 AnnotationRepository 正式 GT。Online Feedback 中尚未 Confirm 的 `pending_review` 不在 AnnotationRepository，因此不会阻止标签生命周期变更。

**真实可达场景 1 — 软删除：**

1. 项目有 active label `smoke`；
2. 正式算法版本检测出 smoke；
3. 用户把结果提交 Online Feedback，形成 `pending_review`；
4. 当前项目没有任何正式 AnnotationRepository 行再引用 smoke；
5. 用户在标签管理删除 smoke；
6. DELETE 因 `label_reference_preview()` 为 0 而成功，把 smoke 置 inactive；
7. 用户回到反馈工作台点击 Confirm；
8. `_online_feedback_prediction_boxes()` 只看 active labels，找不到 smoke；
9. 返回“预测标签 smoke 无法唯一映射到当前项目标签”；
10. feedback 仍 pending_review，只能 Dismiss。

**真实可达场景 2 — code rename：**

当旧 code 没有正式 GT 引用时，`v12_update_label()` 允许直接把 code 改名。Pending feedback 仍保存旧 prediction label；代码不会自动把旧 code 冻结成 alias，也不会在 Confirm 时按历史 label identity 解析，因此同样可能永久失败。

**真实可达场景 3 — 标签统一/merged：**

当 source label 被 REMAP 后退役为 merged，当前 active catalog 只保留 target。Feedback evidence 若仍使用旧 source code，Confirm 的 mapping 不消费 `merged_into`，所以即使平台已经知道 source→target 的 canonical merge 关系，也可能拒绝这条历史 feedback。

**为什么是 Bug：**

`pending_review` 是平台已经接受的 durable 人工审核工作项。既然 Confirm 明确要求 prediction label 能映射到当前 canonical 标签，那么标签治理就必须：

- 把 pending feedback 当 active lifecycle dependency；或
- 在 stage 时冻结可审计的 canonical label identity / merge-resolution contract，并在 Confirm 时按受控迁移处理。

当前 Label Governance 与 Online Feedback 之间没有这层合同。

**影响：**

- 待复核反馈会在标签治理后变成无法确认的死任务；
- 用户只能 Dismiss 本来有效的线上样本；
- correct feedback 无法提升为正式 GT；
- supplement candidate / 自动迭代数据闭环丢样本；
- 标签统一明明有 merged_into 真相，Online Feedback 却无法复用；
- 工作台持续显示“复核”按钮，但操作稳定 409。

**和已有 AUDIT 的区别：**

- AUDIT-031：标签停用可破坏 TRAINING_PREPARE 尚未冻结的继承标签合同；
- AUDIT-085：Label Remap 与 Training Prepare 的 mixed-generation 投影；
- AUDIT-108：Online Feedback Confirm/Dismiss 并发终态与副作用不原子；
- AUDIT-129：AI Annotation task 没冻结 live label catalog；
- AUDIT-176：算法版本 retirement 删除 Online Feedback 的 live version 依赖；
- AUDIT-177：Label Governance 改变 Online Feedback 的 live label identity 依赖。

**现有测试为什么没有发现：**

标签治理测试主要检查正式 Annotation/confirmed_empty 引用、class_id 稳定与 merge；Online Feedback 测试主要在标签库不变的前提下做 stage/confirm/dismiss。缺少：`pending feedback → delete/rename/merge source label → confirm` 的跨 owner 测试。

**建议最小修复方向：**

不要让 Online Feedback 自己维护第二套标签库。

可选方向：

1. pending feedback lifecycle pin：Label DELETE / code rename / source retirement 前 indexed 查询 pending feedback 的 frozen detection labels，存在引用则 409；
2. 或在 feedback stage 时冻结 canonical project class identity，并在 Label Remap owner 完成 source→target 后提供统一的历史 identity resolver；
3. Confirm 继续 fail-closed，不能“找不到 label 就忽略框”；
4. merged source 若允许自动迁移，必须复用 canonical merged_into/label governance owner，不能靠字符串猜测；
5. display_name 修改不应破坏以 canonical code 冻结的 feedback。

**应新增回归测试：**

- pending correct feedback 使用 smoke → delete smoke 应阻止，或有明确安全迁移；
- pending feedback → direct code rename → Confirm 仍可按明确合同完成，或 rename 被阻止；
- pending feedback source smoke → remap smoke→smoking → Confirm 使用 canonical merge resolution；
- unrelated label 变更不阻塞 feedback；
- dismissed/confirmed feedback 不必永久 pin active label；
- 大量 feedback 使用 indexed/bounded reference query，不全表 hydrate；
- ambiguous historical alias/merge 必须 fail-closed。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-178 — Storage Source 破坏性 PATCH 只按 Import/Rescan 思路治理；已受理 Cleaning / AI Annotation / TRAINING_PREPARE 仍会在执行期读取 live Source/Secret

**级别：高**  
**模块：Storage Source / Material Read Dependency / Cleaning / AI Annotation / TRAINING_PREPARE / Credential lifecycle**

**现象：**

已有 AUDIT-044 已确认 Storage Source PATCH 会破坏活动 MATERIAL_IMPORT / rescan，因为这两类任务只冻结 `storage_source_id`，Worker 执行时重新读取 live Source。

继续横向审计发现，相同的可变运行依赖并不只存在于 Import/Rescan。当前至少三条现代主链都在任务已经受理之后，才通过 `StorageManager` 解析素材所引用的 live Storage Source：

- canonical CLEAN MaterialBatch；
- canonical AI Annotation MaterialBatch；
- TRAINING_PREPARE 冷路径素材校验 / bundle materialization。

`PATCH /api/v61/storage-sources/{source_id}` 当前本身没有任何 active-task dependency guard，并允许立即修改：

- `enabled`；
- `config`（endpoint / bucket / prefix / local root 等）；
- credentials；
- `clear_credentials`。

更关键的是 `StorageManager.provider_for(source_id)` 的语义：

1. 第一次访问某 source 时才 `StorageSourceRepository.get(source_id)`；
2. 再按当时的 `secret_ref` 读取 Keyring；
3. 创建 provider；
4. 之后只在该 `StorageManager` 实例内缓存 provider。

因此“Durable Task 已创建”并不等于“存储读取依赖已冻结”。

**真实调用链 A — Cleaning：**

`POST /api/v47/.../clean-tasks`
→ canonical MATERIAL_BATCH operation=CLEAN
→ Worker 创建 `StorageManager`
→ `clean_batch()`
→ 每张尚无成功 clean_result 的素材调用 `manager.materialize(material)`
→ `provider_for(storage_source_id)`
→ 首次命中该 source 时读取 live Source + live Keyring credential。

如果任务 QUEUED / WAITING_RESOURCE 时用户在“存储配置”修改 endpoint、停用 source 或清 credential，任务开始后会直接按新配置运行；这不是创建时用户提交任务所对应的依赖。

对于一个 CLEAN selection 跨多个 storage source 的情况，provider 又是按 source 懒加载的：source A 已初始化、source B 尚未初始化时发生 PATCH，可形成同一任务内 A 使用旧配置、B 使用新配置的 mixed dependency。

**真实调用链 B — AI Annotation：**

`POST /api/v60/.../annotation-tasks`
→ MATERIAL_BATCH / AI_ANNOTATE
→ `AnnotationBatch.__init__()` 创建 `StorageManager`
→ `AnnotationBatch.process()`
→ `self.manager.materialize(image)`
→ 首次访问 source 时读取 live Source/secret
→ 再调用视觉 Provider。

所以已经排队的 AI 任务可因为之后的 Storage Source credential/config 修改而失败；若一个 task 跨多个 source，同样可能使用不同世代的 source 配置。

这与 AI Model Config 的 secret freeze 是两件事：模型 Provider credential 即使冻结，**输入图片存储 credential** 仍是 live 的。

**真实调用链 C — TRAINING_PREPARE：**

Training Create
→ 父 TRAINING + TRAINING_PREPARE
→ submit-time 只冻结 Material row / content_sha256 / selection identity，不复制全部源文件字节
→ Prepare Worker 冷路径创建 `StorageManager(credentials=SecretCredentialStore(...))`
→ 对 frozen images 逐张 `storage.materialize(row)`
→ provider 首次创建时读取 live Storage Source / Keyring
→ 校验 `resolved.content_sha256 == frozen_sha256`
→ 构建 portable dataset bundle。

content SHA fence 能防止“读到了不同图片内容”，但不能让被修改/清掉的 credential、endpoint、bucket 自动恢复。

因此在 bundle cache miss / prepared bundle 不存在的正常路径上：

- task 创建后 source 被 disabled；
- credential 被 clear / rotate；
- endpoint / bucket / root 被改错；

都会让本来已合法受理的 PREPARE 后续失败。

**为什么是 Bug / 生命周期旁路：**

Storage Source 已经是素材的 canonical storage owner，但 PATCH owner 当前只把“配置可编辑”当普通 CRUD，没有建立：

`active material consumer -> source configuration generation`

这个生命周期合同。

对于 Durable Task，受理后至少要满足二者之一：

1. 运行依赖已冻结到可恢复的 generation；或
2. destructive config mutation 会被所有仍可能读取该 Source 的活动任务 fence。

当前两者都没有。

而 `StorageManager` 的 task-local provider cache 又让变更语义变得时序相关：

- provider 已初始化：可能继续用旧配置；
- provider 尚未初始化：会吃新配置；
- retry/recover 新建 manager：一定重新读 live 配置。

这会让同一 Durable request 的结果依赖“PATCH 发生在第几张图之前”，违反可重放性。

**用户真实可达场景：**

场景 1：

1. 用户从 OSS 素材创建 10k 张 CLEAN；
2. 任务处于 QUEUED；
3. 用户到“存储配置”更新 AK/SK 或勾选停用；
4. CLEAN 被 Worker 领取；
5. 第一张 materialize 就按新配置读源，可能失败。

场景 2：

1. AI Annotation 已创建并排队；
2. 用户认为修改 Storage Source 只影响以后导入；
3. 清除 credential；
4. AI Worker 开始 materialize 输入图；
5. 候选生成产生批量 failed items / PARTIAL_SUCCESS。

场景 3：

1. Training Create 已返回 202，TRAINING_PREPARE 在后台；
2. Snapshot/input-freeze 已记录 frozen SHA；
3. 用户编辑素材存储源 endpoint/bucket；
4. Prepare 在 bundle cache miss 时 materialize；
5. 读取失败，训练任务从“已受理”变成 preparation failure。

场景 4：

一个任务同时引用 source A / B：处理完 A 后用户修改 B；后半批首次访问 B 时使用新配置，形成同一 task mixed-generation storage dependency。

**影响：**

- 已受理 CLEAN / AI / Training Prepare 可被无关的存储配置操作中途破坏；
- retry / recover 结果可能与第一次 execution 不同；
- 任务失败会被误判成图片、模型或 Worker 故障；
- 10k/20k 长任务窗口更明显；
- 一个任务可混用不同世代的 Source 配置；
- Training 的 frozen content identity 虽能 fail-closed，却无法保证依赖可恢复，因此仍会造成不必要且不可预期的 Prepare failure。

**和已有 AUDIT 的区别：**

- AUDIT-016：Storage Source DELETE 忽略活动 MATERIAL_IMPORT / rescan；
- AUDIT-044：Storage Source PATCH 破坏 **MATERIAL_IMPORT / rescan** 自己的 source lifecycle；
- AUDIT-047：AI Model Config PUT 原地覆盖的是 **模型 Provider** 的 secret；
- AUDIT-169：算法/转换产物 OSS 配置在 Remote Training / Agent Conversion 中可变；
- AUDIT-170：Storage Source PATCH 内部是 **Keyring 先写、SQLite 后写** 的原子性问题；
- AUDIT-178：已经入库的 Material 被 **Cleaning / AI Annotation / TRAINING_PREPARE** 消费时，素材读取依赖仍由 live Storage Source/secret 控制。

因此 178 不是 044 的重复：044 的 task owner 是 Import/Rescan，178 的 task owner 是已存在 Material 的下游消费者，而且 Training/AI/Cleaning 的失败阶段、恢复语义和用户影响不同。

**现有测试为什么没有发现：**

现有测试分别验证：

- Storage Source CRUD / credential 更新；
- Cleaning 正常 materialize；
- AI Annotation 对 storage-backed image 正常推理；
- TRAINING_PREPARE 能按 frozen SHA materialize；
- source content hash 改变时 Training fail-closed。

但没有组合测试：

`Durable Task 已受理 -> Storage Source destructive PATCH -> Worker 首次/后续 provider_for()`。

也没有覆盖跨多个 source 的 lazy provider initialization 世代混合。

**建议最小修复方向：**

不要新增第二 Storage owner，也不要给 Cleaning/AI/Training 各做一套 source snapshot。

应在现有 Storage Source lifecycle 上建立统一 material-consumer dependency fence：

1. 纯展示字段（例如 name）可继续在线修改；
2. `enabled true→false`、config、credential replace/clear 属于 destructive runtime dependency mutation；
3. 修改前查询所有仍可能 materialize 该 source 的 active Durable Task，包括至少：
   - MATERIAL_IMPORT / rescan（延续 AUDIT-044）；
   - MATERIAL_BATCH CLEAN；
   - MATERIAL_BATCH AI_ANNOTATE；
   - TRAINING_PREPARE / 仍未完成 bundle materialization 的 Training；
4. 有引用时 fail-closed 409，或未来实现明确的 immutable source generation / version pin；
5. retry/recover 必须继续使用原 task 已验证的 source generation，而不是任意 live config；
6. 不要靠把 credential 复制进普通 task payload 明文解决；secret 仍应由 Secret owner 管理，但要有 immutable generation/ref contract；
7. provider 已初始化的进程与尚未初始化的 provider 必须看到同一 generation 语义。

**应新增回归测试：**

- QUEUED CLEAN 引用 source S，PATCH S config/disable/clear credential → 409；
- RUNNING CLEAN 尚未初始化第二 source，PATCH 第二 source → 409；
- QUEUED AI_ANNOTATE 引用 S，credential rotate/clear → 409；
- RUNNING AI 跨 source 时不得混用两个 config generations；
- TRAINING_PREPARE 在 bundle cache miss 且引用 S 时，destructive PATCH → 409；
- TRAINING_PREPARE 已完成 portable bundle、不再读取 source 后，可按明确 pin 生命周期允许修改；
- terminal task 后允许正常修改；
- name-only PATCH 不被误阻止；
- retry/recover 保持原 source generation；
- AUDIT-170 的 Keyring/SQLite 原子性回归测试继续独立保留。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-179 — 训练报告“模型辅助错误归因”在单个 HTTP 请求内串行执行最多 30 次 VLM 推理；最长可占用约 90 分钟且无 Durable lifecycle

**级别：中高**  
**模块：Training Report / AI Error Cause Analysis / VLM / Web Request Lifecycle / Durable Task / Performance**

**现象：**

当前训练报告仍真实展示：

`模型辅助分析原因`

按钮。

前端：

`runAiCause425(job_id)`

会直接同步等待：

`POST /api/v45/projects/{project_id}/jobs/{job_id}/error-cause-analysis`

请求完成。

后端 `v45_error_cause_analysis()` 在一个普通 FastAPI 同步请求中：

1. 取最多 30 个 error samples；
2. 对每张图片逐张调用 `_v35_call_model()`；
3. 所有调用是串行执行；
4. 每张 `requests.post(..., timeout=180)`；
5. 只有整个 for-loop 完成后，才一次性把：
   `report['ai_error_analysis']`
   写回 `job.json`。

因此最坏情况下：

`30 × 180 秒 ≈ 5400 秒 ≈ 90 分钟`

都被压在一个 HTTP 请求生命周期内。

**真实调用链：**

Training Task 详情  
→ `trainingReport425(id)`  
→ 当前 report UI 显示“模型辅助分析原因”  
→ `openAiCause425(id)`  
→ 用户可选择 1~30 张，默认 12 张  
→ `runAiCause425(id)`  
→ POST v45 error-cause-analysis  
→ `v45_error_cause_analysis()`  
→ for error sample  
→ `_v35_call_model()`  
→ `requests.post(... timeout=180)`  
→ 下一张  
→ 全部结束后写 `job.json`  
→ 浏览器才收到响应。

**为什么是 Bug / 生命周期旁路：**

这已经不是普通轻量同步查询，而是多次外部 AI 推理的长任务。

平台已经为 AI Annotation / MaterialBatch / Deployment Test / Training 建立 Durable Task 生命周期，但这里仍把多项昂贵外部推理塞在 Web request 中，形成独立的非 Durable 执行 owner。

当前没有：

- task_id；
- queue；
- progress；
- cancellation；
- lease；
- retry generation；
- checkpoint；
- per-image durable result；
- crash recovery；
- browser refresh recovery。

所以同一类“多图片 AI 工作”在这里重新出现第二种生命周期。

**用户真实可达场景：**

1. 训练完成后打开训练报告；
2. 报告存在 error_samples；
3. 已配置视觉模型；
4. 点击“模型辅助分析原因”；
5. 输入 30；
6. VLM 每张耗时几十秒，或某些请求接近 timeout；
7. 页面长时间卡在一个请求上，没有真实进度，也不能安全停止。

这不是 legacy-only endpoint：当前 `trainingReportCore425` 仍直接渲染这个按钮并调用 v45。

**影响：**

- 单个请求可能持续数分钟到约 90 分钟；
- 长时间占用 Web worker/thread 与连接；
- 反向代理 / 浏览器 / 网络超时可让用户得到失败体验，但服务端仍可能继续执行；
- 服务重启会丢失本轮全部未提交结果；
- 前 1~29 张已经消耗的模型调用费用/时间不会形成 durable checkpoint；
- 用户刷新页面无法知道是否仍在运行；
- 重复点击可并发重复发起同一批昂贵推理；
- 最终只在循环结束后写 job，无法逐项恢复。

**和已有 AUDIT 的区别：**

- AUDIT-047：Model Config secret freeze；
- AUDIT-069/083：AI 图片池/Candidate Review 的 10k 性能；
- AUDIT-116/117/129：AI Annotation reference/label contract；
- AUDIT-163：训练报告仍调用 legacy supplement，形成第二套 iteration/data owner；
- AUDIT-179：训练报告中的多图片 VLM 错误归因本身是**同步 Web 长任务 owner**，缺失 Durable lifecycle。

因此即使修复 163 的 supplement，179 仍然独立存在。

**现有测试为什么没有发现：**

现有报告/UI 测试主要验证：

- 按钮存在；
- request payload；
- report 持久化；
- 单次模型调用返回结构。

没有覆盖：

- 12/30 张真实串行耗时；
- 单图 180 秒 timeout 累加；
- 浏览器 disconnect；
- 服务进程重启；
- 重复点击；
- 中途取消；
- 第 N 张失败后的 checkpoint/retry。

**建议最小修复方向：**

不要新增第二 AI Runtime。

应复用现有 Durable Task / PollRegistry 基础设施：

1. 把“错误原因分析”建成明确的 Durable task kind/operation，或纳入已有合适的 AI batch owner；
2. request 只负责创建任务并快速返回 202；
3. 冻结：
   - job/version identity；
   - error sample IDs；
   - model config identity/secret generation；
   - prompt contract；
4. per-image 结果增量持久化；
5. 支持进度、取消、retry/recover；
6. 前端复用统一 Task poll truth，不自己造 timer；
7. 完成后再由单一 report owner原子关联分析结果；
8. 同一 job + 同一分析输入应支持 idempotency，避免重复计费。

**应新增回归测试：**

- 30 个样本创建请求快速 202，不串行等待模型；
- per-image progress 可恢复；
- 第 5 张失败后 retry 不重复前 4 张已确认结果；
- cancel 后不再发起后续 VLM 请求；
- Worker crash/restart 可继续；
- browser refresh 可恢复任务；
- 重复点击同一 input 不产生重复昂贵执行；
- report 只关联 completed/verified 分析结果；
- 单个 provider timeout 不把 Web 请求占用累计到整批任务结束。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-180 — 训练报告错误样本预览用 live bounded state.images 按 filename 查找，未绑定 frozen Snapshot；预览结果取决于当前分页/改名/删除

**级别：中**  
**模块：Training Report / Error Samples / Snapshot Traceability / Frontend bounded truth / Material Pagination**

**现象：**

当前真实训练详情仍通过：

`TrainingRecoveryRuntime → window.trainingReport425 → trainingReportCore425`

展示训练报告。

报告里的错误样本来自训练完成时的 `report.error_samples`，这些错误本质上属于当次 frozen training Snapshot / Dataset Revision。

但前端生成错误样本卡片时不是按 Snapshot identity 读取图片，而是：

`const im=(state.images||[]).find(x=>x.filename===e.image)`

找到时用：

`<img src="${im.url}">`

找不到就直接显示：

`无预览`。

现代素材页已经服务端分页，startup snapshot 也不再携带全量 images。当前 `state.images` 只是浏览器此刻持有的一小页 live Material rows，而不是训练快照素材真相。

**真实调用链：**

训练完成  
→ frozen Snapshot / Dataset Revision 保留本次 train/val/test identity  
→ training report 记录 error_samples  
→ 用户从训练任务详情点击“训练报告”  
→ `trainingReport425(id)`  
→ GET v44 job report  
→ `trainingReportCore425`  
→ 对每个 error sample：
`state.images.find(filename)`
→ 找不到则“无预览”。

**用户真实可达场景：**

场景 1：

1. 项目 20k 素材；
2. 当前素材分页只持有约 48 条；
3. 某训练错误样本来自第 5000 张；
4. 用户直接从“训练任务”打开报告；
5. `state.images` 当前页不含它；
6. 错误样本稳定显示“无预览”。

场景 2：

1. 打开报告时某错误样本刚好在 current material page；
2. 用户切换素材页/搜索/刷新，`state.images` 被另一页替换；
3. 再打开相同训练报告；
4. 同一份 frozen report 的预览从“有图”变成“无预览”。

场景 3：

1. 训练后用户重命名原素材；
2. report.error_samples 仍保存训练时 filename；
3. live Material filename 已变化；
4. filename lookup 失败。

场景 4：

1. 原 live Material 后续被删除；
2. frozen training Snapshot / portable bundle 仍可能保留当时训练证据；
3. report UI 只查 live Material，因此无法展示历史错误样本。

**为什么是 Bug / bounded truth 漂移：**

训练报告属于**历史训练证据**，错误样本必须绑定：

- snapshot_id；
- image_id / snapshot item identity；
- 或可复现的 frozen artifact path。

当前却重新把：

`live browser state.images + filename`

当成错误样本图片 owner。

这同时违反：

1. bounded truth：一页 Material 不能代表全项目；
2. historical truth：live Material 不能代表旧训练 Snapshot；
3. identity：filename 不是稳定 image identity。

**影响：**

- 大项目报告大量显示“无预览”；
- 同一报告的展示结果随浏览器分页变化；
- 素材改名后历史报告失去图片；
- 素材删除后即使 Snapshot 仍有证据也无法追溯；
- 用户进行错误原因分析/数据补充时缺少关键视觉证据；
- 容易误以为训练报告本身没有保存错误样本。

**和已有 AUDIT 的区别：**

- AUDIT-048/159：质量页图片 I/O 性能；
- AUDIT-145：Dataset list 全量 hydration；
- AUDIT-163：训练详情调用 legacy report owner，并提供错误的 supplement 数据入口；
- AUDIT-179：报告里的 VLM 错误归因是同步长任务；
- AUDIT-180：报告**错误样本图片 identity / preview owner**错误使用 live bounded `state.images`，与 frozen training Snapshot 脱节。

即使 163 把 Report owner 统一，新的 canonical Report 仍必须解决 180 的 snapshot-bound preview identity，不能只换 UI。

**现有测试为什么没有发现：**

现有报告测试通常：

- 构造 report/error_samples；
- 验证文本与指标；
- 或测试少量 `state.images` 恰好包含目标图片。

没有覆盖：

- 20k 项目、当前页只有 48 条；
- error sample 不在当前页；
- 同一报告在分页切换前后；
- training 后 Material rename；
- training 后 live Material delete；
- Snapshot 中图片仍存在但 live row 不存在。

**建议最小修复方向：**

不要让 Report 自己全量 hydrate MaterialRepository。

正确方向：

1. report error sample 生成时保存稳定 image identity，优先 image_id / snapshot item id，而不是只有 filename；
2. report/version metadata 关联 snapshot_id；
3. 提供按：
   `snapshot_id + image_id`
   读取历史预览的 canonical endpoint，或安全读取已冻结 portable snapshot artifact；
4. 报告 UI 直接消费 frozen preview URL；
5. live Material 仍存在时可作为辅助 metadata，但不能作为唯一图片 owner；
6. 不要为修预览调用 `ensureFullPool()`，否则会把功能 Bug 变成 20k 全量性能 Bug；
7. snapshot 已按 retention policy 不可用时，应明确显示“历史快照已归档/不可用”，而不是因分页未命中显示“无预览”。

**应新增回归测试：**

- 20k project + current material page 48 条，error sample 不在当前页 → 仍可预览；
- 切换 Material page 不改变同一 report preview；
- Material rename 后旧 report 仍按 frozen identity 预览；
- live Material delete 后，如果 Snapshot retained，report 仍能预览；
- 同 filename 不同 image_id 时不串图；
- snapshot identity mismatch fail-closed；
- 不得通过全量加载 live materials 修复；
- version report / task report 使用同一历史 preview owner。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-181 — Logout 只删除浏览器 Cookie、不撤销服务端签名会话；退出前 Cookie 可被 replay，并通过滚动续期一直存活到 30 天 hard expiry

**级别：高**  
**模块：ChangLian Login / Logout / Signed Session / Session Revocation / Authentication Lifecycle**

**现象：**

当前畅联云登录体系使用：

`SignedSessionManager`

签发 HttpOnly 的：

`mc_changlian_session`

Cookie。

Session claim 内已经包含随机：

`jti`

以及：

- `iat`
- `created_at`
- `exp`
- `hard_exp`

默认生命周期为：

- idle TTL：7 天；
- absolute TTL：30 天；
- renew window：24 小时。

但是当前 `SignedSessionManager.verify()` 只验证：

1. HMAC signature；
2. username；
3. `exp`；
4. `hard_exp`。

它完全没有：

- server-side session ledger；
- revoked jti store；
- blacklist；
- logout generation；
- per-user session generation；
- revoke API。

虽然 token 中已经生成 `jti`，但 verify/renew 都不读取任何撤销状态。

**Logout 当前真实行为：**

`POST /api/auth/logout`

仅执行：

`response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")`

它：

- 不接收/解析当前 session claim；
- 不记录当前 jti 已撤销；
- 不撤销 session family；
- 不通知 SignedSessionManager；
- 也没有可见的上游 logout/revoke 动作。

因此 logout 的真实语义只是：

> 告诉当前浏览器删除自己的 Cookie。

并不是：

> 让服务端拒绝这次已退出的 session。

**真实复现链：**

1. 用户登录；
2. 得到 Cookie C；
3. 浏览器测试/攻击者/代理在 logout 前复制 C；
4. 用户点击“退出登录”；
5. 当前浏览器收到 Set-Cookie delete，页面回登录页；
6. 但服务端没有保存任何 C.jti 的 revoke truth；
7. 使用保存的 C 再请求任意受保护 API；
8. middleware：
   `_CHANGLIAN_AUTH_SESSIONS.verify(C)`
9. HMAC/exp/hard_exp 仍合法；
10. 请求继续通过。

**滚动续期使窗口更长：**

这不是简单“最多再活 7 天”。

`GET /api/auth/session`

对仍有效 token 会调用：

`SignedSessionManager.renew(claims)`

renew 会重新 issue 一个新 token，保留原：

`created_at / hard_exp`

但生成新的：

`jti`

和新的 idle `exp`。

因为 logout 没有撤销旧 jti，也没有撤销整个 session lineage，所以退出前复制的 C 只要在其当前 idle expiry 前被使用，就可以通过正常 session refresh 获得 C2、C3……，一直续到原 session 的 30 天 absolute hard expiry。

所以 logout 后已复制会话的实际可用窗口可接近：

`30 天 absolute lifetime`

而不是“当前浏览器已立即退出”。

**为什么是 Bug：**

用户明确点击“退出登录”时，安全语义应至少是：

> 当前这一个登录会话不能再用于访问受保护资源。

当前实现只完成 browser-side credential removal，没有完成 server-side session invalidation。

对于自包含 signed-cookie session，如果产品选择不支持服务端 revoke，则“退出登录”本质上只能防止当前浏览器继续发送 token，无法撤销已泄露/复制的 bearer credential。

当前代码已经专门生成 `jti`，但完全没有消费，说明 session identity 已存在，却缺少 lifecycle owner。

**用户真实可达场景：**

场景 1 — 多标签页/自动化工具保存 Cookie：

用户在一个浏览器退出，但另一个持有旧 Cookie 的客户端仍可继续访问。

场景 2 — Cookie 被代理/调试工具/恶意扩展/已控制设备复制：

用户发现风险后点击退出，以为会话已终止，但复制 Cookie 仍有效。

场景 3 — session refresh：

保存的旧 Cookie 在 7 天 idle expiry 前访问 `/api/auth/session`，可获得新的滚动 token，并持续到 30 天 hard expiry。

**影响：**

- Logout 不具备服务端撤销能力；
- 被复制的 session 在用户主动退出后仍能访问平台；
- 用户无法通过“退出登录”终止已泄露 session；
- rolling renewal 会扩大风险窗口；
- 审计上“用户已退出”与“该 session 仍可认证”同时成立；
- 后续若增加更敏感的模型删除、发布、存储凭据操作，风险进一步增大。

**和已有 AUDIT 的区别：**

- AUDIT-115：一个**已经失效**的 session 返回 401 后，前端普通业务 API 不会立即跳回登录页；
- AUDIT-181：用户主动 logout 后，原 session 在**服务端实际上没有失效**，旧 Cookie replay 仍会被 verify 接受。

115 是：

`invalid session -> frontend UX 不同步`

181 是：

`logout -> session 根本没有被 invalidated`

根因与修复点完全不同。

**现有测试为什么没有发现：**

`tests/browser/changlian-login-auth.spec.mjs`

当前会：

1. 登录；
2. 读取并确认 session Cookie 存在；
3. 点击 logout；
4. 通过同一 browser context 请求 protected API；
5. 断言 401。

这个测试只能证明：

> 浏览器成功删除了 Cookie。

它没有：

- 保存 logout 前 Cookie value；
- logout 后手工恢复同一个 Cookie；
- replay 到 protected API；
- 验证旧 jti 已被拒绝。

Unit test 主要验证签名、expiry、rolling renew，也没有 revocation test。

**建议最小修复方向：**

不要把畅联云密码/上游 token 存浏览器，也不要为了 logout 把整个 auth 体系改成另一套。

最小方向可以继续保留 signed-cookie session，但补一个唯一的 server-side revoke truth：

1. 使用现有 `jti` 作为 session identity；
2. logout 时读取当前 Cookie/claims；
3. 原子记录当前 jti / session family 已撤销，至少保留到 hard_exp；
4. `verify()` 在 HMAC/expiry 后检查 revoke truth；
5. rolling renew 应保持可追踪的 session family，不能通过生成新 jti 绕过旧会话 logout；
6. logout 后任何旧 token / renewed descendant 都必须拒绝；
7. revoke store 要有按 hard_exp 的 GC，不能形成无界 blacklist；
8. 若上游畅联登录接口有正式 logout/revoke 能力，再额外调用；但上游能力不能替代本平台本地 session 撤销；
9. logout endpoint 应保持幂等。

如果不希望维护逐 jti blacklist，也可以采用：

`session_family_id + revoked_at / generation`

等 bounded session ledger，但不要新增第二套认证 owner。

**应新增回归测试：**

- 登录拿 Cookie C → logout → 恢复 C → protected API 必须 401；
- C 在 renew window 内 → logout → C 不得换取 C2；
- 已经产生 C2 后 logout session family → C 与 C2 均失效；
- logout 幂等；
- revoke 记录到 hard_exp 后可 GC；
- 两个独立登录 session：退出 A 不误杀 B（如果产品定义支持多会话）；
- session key rotation / expiry 现有测试继续保持；
- 当前浏览器 logout 后 Cookie 仍正常删除；
- 不把 password/upstream token 放进 browser storage。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-182 — “批量清洗 / 批量无需清洗”把当前 48 条 Material page 当成全部未处理素材；全选范围随分页变化，10k/20k 只能逐页操作

**级别：中高**  
**模块：Material Pagination / Batch Cleaning / MARK_CLEAN_SKIPPED / Frontend bounded truth / Selection Scope**

**现象：**

现代素材页已经由 server-side Material Pagination 接管。

当前 `state.images` 不再代表整个项目 / 整个筛选结果，而只代表当前 Material page。

但是未处理素材页顶部仍真实插入两个生产按钮：

- `批量清洗 → openBatch414('clean')`
- `批量无需清洗 → openBatch414('ready')`

这两个入口都**不传 image_ids**。

而 `openBatch414(mode, ids=null)` 在没有显式 ids 时直接：

`const candidates = state.images || []`

随后：

1. 从这一页中过滤：
   - 非 annotation_index_pending；
   - 未 processed；
   - 未 annotated；
2. 把这些当前页 rows 存入：
   `state.batch414Rows`
3. 默认全选：
   `state.batch414Selected = new Set(rows.map(...))`
4. 弹窗显示：
   `共 N 张未处理素材 · 已选 N`
5. “全选”也只重新选择：
   `state.batch414Rows`
6. 提交时只把这些 ID 交给：
   - CLEAN；
   - canonical MATERIAL_BATCH + MARK_CLEAN_SKIPPED。

所以后端 Durable owner虽然可以处理大范围任务，但前端根本没有把整个当前 filter/scope 交给它。

**真实调用链：**

数据集 → 未处理素材  
→ MaterialPaginationRuntime 只加载当前 page（当前默认约 48 条）  
→ `decorateDatasetControls414()`  
→ 页面顶部显示“批量清洗 / 批量无需清洗”  
→ 点击 `openBatch414('clean'|'ready')`  
→ `ids=null`  
→ `candidates=state.images`  
→ 当前页 N 条  
→ 弹窗宣称“共 N 张未处理素材”  
→ “全选”只全选这一页  
→ `confirmBatch414()`
→ CLEAN 或 MARK_CLEAN_SKIPPED 只收到当前页 IDs。

**用户真实可达场景：**

项目有 10,000 张未处理素材。

当前 page size 48。

用户进入“未处理素材”，看到顶部“批量清洗”。

点击后弹窗显示：

`共 48 张未处理素材 · 已选 48`

用户点“开始清洗”。

最终只创建一个 48 张的 CLEAN task。

其余 9,952 张完全不在 selection 中。

翻到第 2 页再点相同按钮，又只处理第 2 页。

如果当前页还叠加搜索/标签等 filter，批量范围又随当前浏览器页状态变化。

**为什么是 Bug / bounded truth 漂移：**

“当前页选择”本身可以是一种合法产品动作，但当前 UI：

- 按钮叫“批量清洗 / 批量无需清洗”；
- 弹窗写“共 N 张未处理素材”；
- 有“全选 / 反选”；

却没有任何“仅当前页”的语义提示。

更重要的是平台已经建立：

- server-side Material filter；
- MaterialSelectionSpec；
- FILTERED scope；
- Durable MaterialBatch；

正是为了 1k/10k/20k 不在浏览器维护全量 ID。

当前 UI 仍把 bounded page list 重新当成 batch truth，绕过了这些能力。

**影响：**

- 10k/20k 批量清洗退化成逐页 48 张操作；
- 用户会误以为“全选”覆盖所有未处理素材；
- 多页项目很容易只清洗第一页后就创建 Training；
- 其它页仍是 unprocessed，但用户以为已经完成批量治理；
- “无需清洗”同样只推进当前页；
- 浏览器换页后同一按钮含义变化；
- 后端已有 FILTERED 大范围能力无法被真实产品入口使用。

**和已有 AUDIT 的区别：**

- AUDIT-050：Cleaning 详情读取时全量 hydrate 结果；
- AUDIT-051：ZIP Import Review 曾把 10k/20k 全量 hydrate 到浏览器；
- AUDIT-161：“无需清洗”存在同步 v52 mutation 旁路，形成第二 mutation owner；
- AUDIT-182：即使走 canonical Durable MaterialBatch，**前端 batch selection 本身仍被当前 Material page 截断**。

161 解决“谁执行 mutation”。

182 解决“用户的批量范围到底是谁”。

两者都需要修，但不是同一问题。

**现有测试为什么没有发现：**

当前测试主要覆盖：

- MaterialPagination 只加载 bounded page；
- CLEAN MaterialBatch 可以接受 selected/FILTERED selection；
- MARK_CLEAN_SKIPPED Durable owner；
- 当前页多选和最近上传批次。

没有跨模块测试：

`server total > page size`
→ 顶部“批量清洗”
→ 应表达 current filter 全量 scope，而不是只传当前 page IDs。

也没有断言：

- UI 文案如果仅当前页，必须明确“当前页”；
- “全选”不能把 bounded page 冒充全量 filter。

**建议最小修复方向：**

不要重新全量 hydrate 10k/20k image IDs。

应直接复用现有 canonical MaterialSelectionSpec / FILTERED owner：

1. 顶部“批量清洗 / 批量无需清洗”默认表达当前 server-side filter scope；
2. 将当前 dataset/tab/filter 条件转换成 FILTERED selection_spec；
3. 后端冻结 selection.sqlite3；
4. 若用户只想处理当前页，提供明确的“当前页”动作；
5. 当前显式勾选模式继续使用 SELECTED IDs；
6. 弹窗显示服务端 aggregate total，而不是 `state.batch414Rows.length`；
7. “全选”应表示“当前筛选结果全选”，并使用 scope + exclusions / selection token，不在浏览器创建 20k Set；
8. recent-upload batch 的显式 IDs 语义保持不变。

**应新增回归测试：**

- 10k unprocessed、page size=48，顶部批量清洗 → task selection total=10k；
- 10k unprocessed、点击“仅当前页” → total=48；
- filter 后 1,200 条 → FILTERED task total=1,200；
- 显式勾选 7 张 → SELECTED total=7；
- MARK_CLEAN_SKIPPED 同样遵守 scope；
- 翻页不改变已创建 FILTERED selection；
- 前端不得为了“全选”请求/保存 10k image IDs；
- recent-upload explicit batch 继续只处理本批 IDs。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---


### AUDIT-183 — Material 多选 Set 支持跨页累积，但“批量标注 / 清洗已选 / 已选无需清洗”重新只在当前页找 row；已选 ID 会被静默丢弃

**级别：高**  
**模块：Material Pagination / Cross-page Selection / Manual Annotation / Cleaning / MARK_CLEAN_SKIPPED / Frontend bounded truth**

**现象：**

现代素材页的显式多选状态由：

`state.data412Selected`

维护。

这个 Set 明确可以跨页累计：

- `selectAll412()` 只把当前页 IDs 加入 Set，不清空原选择；
- `setData412/toggleData412` 直接增删全局 Set；
- 翻页不会清空 Set；
- 顶部 `已选 N 张` 显示 Set 总数；
- `batchDelete412()` 会直接把完整 Set 传给 canonical DELETE_INDEX，因此跨页选择本身是现有产品语义，不是偶然残留。

但同一批量模式下另外三个真实动作没有直接消费这个 ID truth。

**路径 A — 批量标注：**

`openBatchAnnotation417()`

先取全部 selected IDs，然后执行：

`filter(id => (state.images || []).some(...id... && ready417(x)))`

所以只有**当前 Material page**中仍有 row 的 ID 会留下。

前一页已选择但当前页不可见的 ID 被静默删除。

后续 `annotationQueue414` 也只保存这个截断后的集合。

**路径 B — 清洗已选：**

`openSelectedClean417()`

虽然把完整 selected IDs 传给：

`openBatch414('clean', ids)`

但 `openBatch414` 在 ids 非空时只构造：

`candidates = recentUploadedMaterials61 + state.images`

再通过 allowed IDs 过滤 rows。

因此：

- 当前页 selected 能找到；
- recent upload cache 中 selected 能找到；
- 之前页 selected 如果不在这两个 bounded pools 中，就直接消失。

最终 CLEAN task 收到的是截断后的 `state.batch414Selected`。

**路径 C — 已选无需清洗：**

`openSelectedReady417()`
→ `openBatch414('ready', ids)`

与路径 B 完全相同，最终 MARK_CLEAN_SKIPPED 也只收到当前 bounded candidate pool 中能重新 join 到 row 的 IDs。

**真实用户场景：**

项目有 500 张素材，page size 约 48。

1. 用户进入批量模式；
2. 第 1 页点击“全选当前” → selected=48；
3. 翻第 2 页；
4. 再“全选当前” → selected=96；
5. 页面顶部正确显示：
   `已选 96 张`；
6. 用户点击“清洗已选”。

此时 `openSelectedClean417` 确实读取 96 IDs。

但 `openBatch414(ids)` 只能从当前第 2 页 `state.images` 找 row。

第 1 页的 48 个 ID 会被静默丢弃。

弹窗会显示大约：

`共 48 张未处理素材 · 已选 48`

而不是提示“其中 48 张无法解析”。

批量标注同样会把前页选择静默过滤掉。

**为什么是 Bug：**

这里不是“仅当前页批量”的产品语义。

系统已经明确保留跨页 Set，并且删除动作正确消费完整 Set。

因此：

`data412Selected`

是跨页 selection truth。

后续动作把它重新与 bounded `state.images` 做 inner join，相当于：

`global selected IDs ∩ current visible page`

然后无提示地执行。

这会造成 UI 选择数量与实际业务 side effect 不一致。

**影响：**

- 用户认为已选 96/500 张，实际只处理当前页；
- 清洗任务 scope 小于用户选择；
- “无需清洗”只推进部分 selected material；
- 批量人工标注队列丢失前页素材；
- 删除动作能处理完整跨页 selection，而清洗/标注不能，形成同一批量 UI 内部合同漂移；
- 用户必须手工逐页重复操作，且很难察觉哪些 ID 被漏掉。

**和已有 AUDIT 的区别：**

- AUDIT-182：未显式多选时，顶部“批量清洗 / 批量无需清洗”把当前 page 冒充整个未处理范围；
- AUDIT-183：用户已经建立一个**明确的跨页 selected ID Set**，但动作执行前又用 bounded page metadata 把这个真实 selection 截断。

182 是默认 batch scope 错。

183 是 explicit selection truth 在 action handoff 时丢失。

同时 183 还影响“批量标注”，范围超过 182。

**现有测试为什么没有发现：**

现有素材页测试通常覆盖：

- 当前页勾选；
- 当前页全选/反选；
- selected count；
- 单页批量删除/清洗；
- MaterialPagination page load。

缺少真实序列：

`page1 select → page2 select → action`

并断言 action 接收到两个页面的全部 IDs。

**建议最小修复方向：**

不要为了找 metadata 再全量 hydrate Material。

1. selected IDs 本身已经是 canonical browser selection intent；
2. CLEAN / MARK_CLEAN_SKIPPED 应直接把 selected IDs 交给 MaterialBatch SELECTED scope；
3. 如果弹窗需要 filename/thumbnail，只对当前可见页展示 preview，或通过 bounded batch lookup 按选中 IDs 分页取 metadata；
4. 批量标注需要一个能按 selected IDs 分页解析 Annotation Workbench queue 的 owner，而不是依赖 `state.images`；
5. 找不到/已删除的 selected ID 必须显式报告 conflict，不得静默过滤；
6. selection count 与最终 task frozen selection total 必须一致。

**应新增回归测试：**

- page1 选 48 + page2 选 48 → CLEAN frozen selection=96；
- 同样场景 MARK_CLEAN_SKIPPED=96；
- processed 跨页 selected → annotation queue=全部 IDs；
- 其中一个 ID 已删除 → 明确 conflict/缺失提示，不静默变 95；
- batchDelete 现有跨页行为保持；
- 不允许修复方案全量 hydrate 10k/20k Material rows。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。

---

### AUDIT-184 — Training SSE 增量签名遗漏 loss/mAP/LR/吞吐率等真实训练遥测；进度/epoch 不变时实时页可持续展示旧指标

**级别：中**  
**模块：Training SSE / Training Job Projection / TrainingTaskRuntime / Realtime vs REST truth**

**现象：**

当前 v64 `GET /api/v64/projects/{project_id}/training-events` 每 750ms 调用 `_training_event_rows()`；`_training_event_row()` 通过 `build_training_display_progress(worker_job, runtime)` 构造具有正式业务含义的训练进度，同时将完整 `worker_job['training_progress']` 放进 SSE row。

但是 `_training_event_signature(row)` 的比较字段只包括 durable status/stage/progress、current item、worker、reason、updated_at、epoch/batch、elapsed/ETA、telemetry_source 等，遗漏：

- `row.training_progress.losses`（box/cls/dfl loss）；
- `row.training_progress.metrics`（mAP50 / mAP50-95）；
- `row.training_progress.learning_rates`；
- `row.training_display_progress.throughput`；
- 整个业务展示用的 `training_progress` 子对象的语义版本/摘要。

签名相同则 `event_stream` 不发送 `training.task`。即使这次读取到的新 `job.json` 里的指标发生改变，服务端依旧静默丢掉指标变化。

**真实调用链：**

训练 Worker 持续写 `job.json.training_progress` 的损失、指标或吞吐率 → SSE loop 读取 worker_job → `build_training_display_progress()` 得到新 throughput，`_training_event_row()` 复制新 training_progress → `_training_event_signature()` 不包含上述数值，且 durable task 的 `updated_at` 可以不随 job.json 的单独遥测变化而更新 → 签名与前一轮相同 → SSE 没有发包 → `TrainingProgressStreamRuntime.applyUpdate()` 不会执行 → 前端 `trainingProgressView()` 继续显示旧的 box/cls/dfl loss、mAP、LR、img/s。

当前现代训练页确实调用 `trainingProgressView(job)`，它消费 `display.throughput`、`progress.losses`、`progress.metrics`、`progress.learning_rates`，不是没人读取的冗余字段。

同时 `training-progress-stream.js` 在 `training.ready` 覆盖当前 active job IDs 时调用 `setTrainingRealtimeActive(true)`，会让 canonical `PollRegistry` 降低/关闭 REST 补偿轮询，所以被过滤的指标更新不保证由下一次 REST 及时纠正。

**用户真实可达场景：**

一项 RUNNING 训练在同一 epoch/batch、相同总体进度（或进度按两位小数取整未变化）下更新了训练 loss、评估 mAP、学习率或 img/s；Durable task 本身没有新的生命周期 heartbeat。SSE 虽然已读取到新的遥测值，却因旧签名完全相同而不派发 `training.task`。若期间没有其它已列入签名的字段变动，该任务行指标就停留在上一次事件。

**影响：**

- 训练详情中的 loss/mAP/LR/吞吐率可延迟刷新或与 REST 真相不一致；
- 用户误判模型收敛或训练运行速度；
- “实时流已连接”不能证明“训练遥测也实时”；
- 有 Worker 遥测变更、但没有 epoch/batch/progress 变更的阶段更明显。

**和已有 AUDIT 的区别：**

- AUDIT-068：SSE 没复用 `training_queue_truth()`，是 QUEUED/WAITING_RESOURCE 的状态漂移；
- AUDIT-119：SSE 每 750ms 对全部 active `job.json` 无条件读取，属于昂贵 I/O；
- AUDIT-120：隐藏页面仍高频轮询；
- AUDIT-184：**数据已经被 SSE loop 读取并投影出来，但变化检测遗漏当前 UI 真正使用的遥测字段，导致不发送更新**。不能以增加读取频率修补。

**现有测试为什么没发现：**

`tests/api/test_training_event_stream.py` 只验证签名在 `progress_percent` 与 `updated_at` 改变时会改变，没有测试只改变 loss/metrics/LR/throughput。`tests/frontend/training-progress-stream.test.mjs` 直接调用 `applyUpdate()` 检查完整 payload 能更新 UI，但没有覆盖后端签名筛选会不会阻止 payload 发出，因此前后端各自测试通过仍可漏报。

**建议最小修复方向：**

继续复用唯一 `build_training_display_progress()` 和 SSE owner，不新增轮询或第二训练进度 owner。为事件签名增加**稳定且有界的业务遥测摘要**：只包含当前 UI 使用的关键 loss、mAP、LR、throughput 数值以及必要的 phase_progress；对无变化的值保持去重。不能把每轮都会递增的 `display_revision` 直接加入签名，否则会把 750ms 的空读变为 750ms 的无变化广播，加剧 AUDIT-119。应与 AUDIT-068、119 合并考虑共用 source revision/一次投影缓存。

**应新增回归测试：**

- 固定 status/epoch/batch/progress/updated_at，仅改变 box_loss → `_training_event_signature` 不同；
- 仅改变 cls_loss、dfl_loss、mAP、LR → 分别触发新 SSE signature；
- 仅改变 throughput → 触发签名变化且前端 `trainingProgressView` 更新；
- 完全相同的遥测 → 不重复发送；
- display_revision 自增但业务数据完全没变化 → 不增加无意义事件；
- SSE covered=true、REST fallback suppressed 时新指标仍能传播；
- 不回退 AUDIT-068 的 status/reason truth，也不引入每客户端更多 `job.json` 读取。

**是否需要 VERSION：** 是。  
**是否需要新增回归测试：** 是。


**2026-10-08 复核补充（QUALIFIED，非撤销）：**

现代 `TrainingRecoveryRuntime` 在详情打开且任务 active 时，会用自己的 canonical `training-task-detail` PollRegistry timer 每 1.5 秒执行 `refreshOpenDetail()`，其中 `readJob()` 提供 REST 遥测，因此该机制能**缓解**本 AUDIT 对“打开详情”场景的可见延迟。本问题不是“详情必然永久不更新”，而是 SSE 作为训练增量公共流漏掉有意义的指标变化；若详情 REST 正常，它最多体现为 SSE 及时性缺口，可能由下一轮 1.5 秒 REST 刷新纠正。原记录中“持续展示旧指标”应理解为没有其它签名字段触发、且未收到成功 REST 补偿期间的 SSE 缺口，不应夸大为正常详情页必然永久卡死。此补充与下一条 AUDIT-186 的高频日志轮询性能问题相互独立。

---

### AUDIT-185 — Training 批量 mutation 部分成功时无条件清空整个 selection，失败/跳过 ID 丢失

**严重级别：中；模块：TrainingTaskVisibilityRuntime / TrainingTaskRuntime.batchAction / Batch Mutation。**

**现象与真实调用链：** canonical `static/modules/training-task-visibility-runtime.js` 的 `runBatchAction` 传递 `selectedIds` 给 `TrainingTaskRuntime.batchAction(action, ids)`。后者调用 v48 pause/resume/stop 或 batch-delete endpoint，可返回 `{succeeded,failed,skipped,failures[]}`；但是 UI 只判断 `!result.cancelled && (result.succeeded || 0) > 0` 就执行 `selectedIds.clear(); batchMode=false`，不读取失败 ID。即使 A 成功、B 409、C 跳过，A/B/C 全部失选。

**真实可达场景：** 用户选择三个不同执行阶段的训练任务批量暂停/停止；提交时其中一个任务已终态或缺 ProcessIdentity，另一任务操作成功。对 DELETE，后端已专门返回 `skipped_active/missing/failures`，同样有部分成功路径。当前训练任务页由 `TrainingTaskVisibilityRuntime` 负责渲染和事件绑定，不是 legacy zero-reference。

**影响：** 失败和跳过的 ID 被清空，无法直接重试；只显示成功/失败计数而失去对应选择，需重新查找勾选，批量业务结果与 UI selection 不一致。

**为什么不重复：** AUDIT-020 指单条 DELETE 对活动任务的隐式取消；AUDIT-164 指暂停 eligibility/ProcessIdentity 不匹配；AUDIT-183 指素材跨页选中 ID 在 mutation 前被截断。AUDIT-185 是训练批量 mutation 返回部分成功之后的 UI reconciliation 丢失，不同 owner 与时间点。

**现有测试缺口：** `batchAction` 的 backend failure 计数与当前 UI 清空逻辑分别测试，缺少端到端“一成功、一失败、一跳过”的 retained selection 测试。

**建议最小修复：** 不做第二批量 Owner。让现有 `batchAction` 返回 item-level succeeded/failed/skipped ID（已有 failures[]，需完善剩余 ID）；全成功才退出批量模式。部分成功只移除真实成功 ID，保留失败/跳过 ID，并在刷新后重新确认 eligibility；不要从当前 bounded jobs page 猜测结果。

**应新增回归：** A 成功、B 409、C skipped → B/C 仍选中；batch delete 的 skipped_active/missing 保留并提示；全部成功才清空；全部失败、用户取消、刷新失败不丢失败 ID；50 条分页边界仍正确处理 selection。

**是否需要 VERSION：是。是否需要回归测试：是。**

---

### AUDIT-186 — 训练详情即使只看概览，也每 1.5 秒无条件读取并回传最多 12 万字符日志；活动任务详情产生持续 I/O 与带宽放大

**严重级别：中高。模块：TrainingRecoveryRuntime / PollRegistry / Training Log REST / Performance / Read-Only Owner。**

**现象及真实调用链：** canonical `static/modules/training-recovery-runtime.js` 的 `scheduleDetailRefresh()` 在 active 任务详情打开时每 1500ms 调用 `refreshOpenDetail({includeRecovery:false})`。该函数无条件执行 `Promise.all([readJob(taskId), recoveryPromise, readLog(taskId)])`，没有区分用户查看概览还是展开 `[data-training-tech-log]`。`readLog()` 始终 GET `/api/projects/{project_id}/jobs/{job_id}/log`。

后端 `job_log()` 在每次 GET 都调用 `_tail_training_log_text(train.log)`，并为 Durable task 再调用 `_tail_training_log_text(task.log_ref)`。每个文件会读取最多 `4 * 120000 + 4` 字节再解码；最终 response 可达 120000 字符。日志没有变化时依旧重复执行这两次尾部 I/O、文本合并及完整响应，不存在 ETag/增量 cursor/变化签名。

**生产可达场景：** 用户打开正在执行的训练任务“详情”，默认 overview 未打开日志区；只要保持详情，PollRegistry 会每 1.5 秒重读 job 和完整日志。若 log 已累计到长文本，单个客户端可持续收到同样的 120k 字符；多个运维用户同时看任务时，磁盘 I/O 与传输按连接数放大。远程训练还可能在日志读取前触发 `sync_remote_job()`，扩大 Web 请求成本。

**为什么是 Bug：** 详情概览需要状态/进度，但不需要在日志区未展开时不断读取大文本。当前 canonical `TrainingRecoveryRuntime` 已经区分 `openFocus`、`[data-training-tech-log]`，却没有把展开状态用于日志读取 admission；这是同一前端 owner 内的额外无效请求，不是日志 retention 的正常成本。

**影响：** 活动训练详情产生不必要的 1.5s 日志请求；累计大日志导致磁盘重复 seek/read、JSON/字符串构造与网络带宽放大；多用户同时查看时加重 Web 线程和 I/O；用户只是观察训练进度也承担日志全文传输成本。

**和已有 AUDIT 区别：** AUDIT-066 是训练列表历史全扫描；AUDIT-119 是 SSE 对最多 100 个 active job.json 的 750ms 读取；AUDIT-179 是训练报告 30 次同步 VLM；AUDIT-184 是 SSE telemetry signature 缺漏。AUDIT-186 则是独立的**详情 REST 日志传输**无条件 1.5s 刷新、无需展开也请求，修复点位于详情 readLog gate / bounded delta，不是 SSE。

**现有测试为何漏掉：** 详情测试主要检查任务状态与日志能展示、定时器能工作，没有断言 overview 阶段 `readLog` 调用次数为 0，也没有 1.5s × 多轮相同日志时只增量拉取变化的 I/O contract；单请求日志读取本身已有 120k 上限，容易误以为高频使用也安全。

**建议最小修复：** 保留现有唯一 TrainingRecoveryRuntime、PollRegistry 和 job log endpoint。概览刷新只请求 `readJob()`；仅用户展开技术日志且详情仍打开时按明确频率获取日志。日志增量能力可复用原 endpoint 补 ETag/offset/last-modified/有限尾部协议，不新增第二日志 Owner。避免每 1.5s 反复下载同一 120k 文本；切换任务/关闭详情清理原 timer。

**需新增回归测试：** active 训练仅打开 overview 轮询 5 次 → `readJob` 更新但 `readLog` 调用 0 次；展开日志才读取；日志不变 5 个周期不重复整段传输；日志追加只得到有界增量；关闭日志/切换任务/关闭 modal 停止日志请求；多客户端/大日志量 I/O 与传输受限；训练 status/ETA 的 1.5s 更新不受影响。

**是否需要 VERSION：是。是否需要新增回归测试：是。**

---


---

## 2026-10-08 审计覆盖及修复路线图（阶段性收口）

> 目的：为下一阶段集中修复建立可执行优先级；**只整理审计，不代表已修复，不改变生产代码，也不宣布可部署。**  
> 分类基线：远端 c0ca1f4e2f369bd07505f83f866742401884d09b / VERSION 42.24.280 / 最新 AUDIT-186。  
> 后续并发提交必须重新读取 HEAD、AUDIT 尾部并更新分级；本小节不是后续新 AUDIT 的编号起点。

### A. 去重与状态

- 历史编号 AUDIT-001～AUDIT-186，连续且无重复编号，共 186 条。
- 显式撤销（不计待修）：AUDIT-012、AUDIT-037、AUDIT-096、AUDIT-118，共 4 条；其中 096/118 均与 068 重复。故**有效审计条目 182 条**。
- AUDIT-001、AUDIT-007 为低优先级结构债，当前不应当成已经证明影响用户行为的生产 Bug；不因旧命名/zero-reference 而增记。
- 本次抽查候选 CLEAN retry、删除与训练竞争、Agent auto-allocation 缺口、Central allocator 20k 全扫描均已有 AUDIT-152/084/063/079；没有新的独立可登记问题，不重用编号。
- P0～P3 是**修复顺序的初步影响分级，不是原始严重级别的替换**。P0 表示部署前需修复或通过严格隔离证明生产不可达；部分场景有触发前置条件。

### B. P0～P3 待修分级（互斥分组、每条只出现一次）

| 分类 | 条数 | 处理定位 |
|---|---:|---|
| P0 — 数据准确性 / 正式 GT / 不可逆数据与安全 | 58 | 阻断误训练、错误版本继承、GT 污染、不可逆删除、鉴权凭据风险 |
| P1 — Durable 生命周期 / Agent / 无法恢复 | 44 | 稳定恢复、取消/lease/claim/finalization fence、节点依赖及资源 |
| P2 — 前后端与 API 合同 | 51 | 防假成功、错误按钮状态、遗漏任务、SSE/REST 投影漂移 |
| P3 — 大规模性能与可证明的结构债 | 29 | 有界分页、消除 10k/20k 热路径全量 I/O、历史 metadata GC |
| **有效合计** | **182** | 排除 4 个撤销编号 |

**P0（58）：** AUDIT-008、AUDIT-011、AUDIT-014、AUDIT-016、AUDIT-017、AUDIT-018、AUDIT-019、AUDIT-028、AUDIT-029、AUDIT-031、AUDIT-032、AUDIT-034、AUDIT-035、AUDIT-038、AUDIT-040、AUDIT-042、AUDIT-044、AUDIT-046、AUDIT-047、AUDIT-062、AUDIT-072、AUDIT-080、AUDIT-082、AUDIT-084、AUDIT-085、AUDIT-086、AUDIT-090、AUDIT-091、AUDIT-095、AUDIT-098、AUDIT-099、AUDIT-102、AUDIT-108、AUDIT-110、AUDIT-117、AUDIT-129、AUDIT-132、AUDIT-134、AUDIT-137、AUDIT-138、AUDIT-139、AUDIT-141、AUDIT-142、AUDIT-148、AUDIT-149、AUDIT-151、AUDIT-152、AUDIT-157、AUDIT-167、AUDIT-169、AUDIT-170、AUDIT-171、AUDIT-173、AUDIT-175、AUDIT-176、AUDIT-177、AUDIT-178、AUDIT-181。

**P1（44）：** AUDIT-002、AUDIT-015、AUDIT-020、AUDIT-024、AUDIT-026、AUDIT-027、AUDIT-039、AUDIT-049、AUDIT-055、AUDIT-060、AUDIT-063、AUDIT-065、AUDIT-067、AUDIT-070、AUDIT-071、AUDIT-075、AUDIT-076、AUDIT-077、AUDIT-087、AUDIT-092、AUDIT-093、AUDIT-097、AUDIT-104、AUDIT-106、AUDIT-107、AUDIT-109、AUDIT-111、AUDIT-112、AUDIT-121、AUDIT-122、AUDIT-123、AUDIT-125、AUDIT-127、AUDIT-130、AUDIT-131、AUDIT-133、AUDIT-135、AUDIT-140、AUDIT-158、AUDIT-160、AUDIT-164、AUDIT-168、AUDIT-172、AUDIT-179。

**P2（51）：** AUDIT-003、AUDIT-004、AUDIT-005、AUDIT-006、AUDIT-009、AUDIT-010、AUDIT-013、AUDIT-021、AUDIT-022、AUDIT-023、AUDIT-025、AUDIT-030、AUDIT-033、AUDIT-036、AUDIT-041、AUDIT-043、AUDIT-052、AUDIT-053、AUDIT-054、AUDIT-056、AUDIT-057、AUDIT-058、AUDIT-059、AUDIT-068、AUDIT-074、AUDIT-078、AUDIT-081、AUDIT-088、AUDIT-094、AUDIT-105、AUDIT-114、AUDIT-115、AUDIT-116、AUDIT-124、AUDIT-126、AUDIT-128、AUDIT-144、AUDIT-146、AUDIT-147、AUDIT-150、AUDIT-153、AUDIT-155、AUDIT-156、AUDIT-163、AUDIT-165、AUDIT-174、AUDIT-180、AUDIT-182、AUDIT-183、AUDIT-184、AUDIT-185。

**P3（29）：** AUDIT-001、AUDIT-007、AUDIT-045、AUDIT-048、AUDIT-050、AUDIT-051、AUDIT-061、AUDIT-064、AUDIT-066、AUDIT-069、AUDIT-073、AUDIT-079、AUDIT-083、AUDIT-089、AUDIT-100、AUDIT-101、AUDIT-103、AUDIT-113、AUDIT-119、AUDIT-120、AUDIT-136、AUDIT-143、AUDIT-145、AUDIT-154、AUDIT-159、AUDIT-161、AUDIT-162、AUDIT-166、AUDIT-186。

### C. 按 Canonical Owner 合并修复，按次序验收

1. **R0 正式 Ground Truth / Material 内容代际及删除 fence（P0）：** 017、019、084、085、090、098、099、102、108、148、149、152、157、173。复用 AnnotationRepository + MaterialRepository；source hash/content-generation、review/snapshot/delete 共享不可逆写入栅栏；严禁新增第二份 Annotation owner。统一测试图片内容 H1 到 H2 Rescan、candidate/clean/GT、并发 Commit/Delete、已确认负样本。
2. **R1 Training Admission → Snapshot → Version CAS（P0）：** 031、032、046、053、054、072、085、129、139、141、142、147、148、150、151、165、167。提交 readiness 与 Snapshot 同口径；正/负样本 scope 不做伪扩展；selected-label projection 不得制造负样本；冻结 baseVersionId/权重/标签，版本归档 CAS 与同 task 幂等同验收。
3. **R2 Import / Source / Secret / Algorithm retirement（P0/P1）：** 011、014、016、018、044、047、062、071、080、082、095、132～134、169～171、175～178、181。统一引用/凭据/对象存储的任务依赖 fence，避免 source/secret 变更及删除期间产生半提交；ZIP、v36、普通 Upload 的既有 owner 整合时禁止增加 Runtime；修复 logout 服务端撤销。
4. **R3 Agent / Assignment / GPU / Execution（P1）：** 049、055、060、063、070、075～079、092、093、158、168。中央 allocator 必须有自动调用 owner，Node assignment→execution handoff 不丢 GPU 排他占用；完整覆盖 node offline、token rotation、lease expiration、result receipt 与 finish 的 crash recovery。不得让 terminal business commit 被同 task 新 generation 重放。
5. **R4 UI / SSE / REST / 任务详情（P2）：** 005、021、023、025、030、033、036、056～059、067、068、081、088、094、105、115、121～128、144、146、150、153、155、156、163、164、174、180、182～185。每页确立唯一 PollRegistry/Modal/selection truth；REST/SSE status 归一并覆盖缺失状态，跨页选择保持；前端不可对已知必失败动作报告可提交。
6. **R5 1k/10k/20k 有界性能（P3，部分问题依赖 R0～R4）：** 045、048、050、051、064、066、069、073、079、083、089、100、101、103、111、113、119、120、136、143、145、154、159、162、166、179、186。重点消灭全量 fetchall 后截断、N+1 GT、循环重 SHA/读日志/探测硬件、每次 Poll 刷新全局历史、Web 请求线程串行 VLM；使用现有 Owner 的 bounded SQL/异步 Durable，不以新增缓存第二份 truth 掩盖成本。

同一 AUDIT 可作为不同修复批次的回归依赖，**不表示重复登记问题**。业务代码变更应采用独立的修复提交，不要一次性修改全部模块。

### D. T1～T7 覆盖证据与证据边界

| 范围 | 源码核验与审计条目 | 尚未提供的运行证据 |
|---|---|---|
| T1 Training Accuracy | training_tasks.py、training_splits.py、material_batches.py；031/032/085/139/142/147～151/165/167 | 真实训练端到端 + 组合型 label/scope/权重 CAS 矩阵 |
| T2 Retry/Recover | TaskRepository.retry、MaterialBatch retry/selection、AI Candidate；080/095/098/152/172 | 模拟断电/恢复、源 hash 变化、跨 generation receipt 重放 |
| T3 Agent | task_node_assignments.py、agent_execution.py、fenced_repository.py、node_agent_executor_loop.py；049/055/060/063/070/075～079/092/093/158 | 双 GPU/多节点真实注入故障、节点离线及重连 |
| T4 Frontend Owners | 静态入口与 Runtime 调用证据来自 005/067/088/120/123/163/182～185；本轮未全量浏览器复跑 | 最新 HEAD 的 Real Chrome 页面/Modal/导航长时间运行 |
| T5 DELETE/PATCH | material_batches.py 删除方检查；011/016～020/084/090/109/149/168～178 | 并发事务/OSS/Keyring 真实故障注入 |
| T6 1k/10k/20k | allocator assign_next fetchall；064/079/100/143/145/154/159/162/166/186 | 1k/10k/20k 实际 p50/p95、磁盘读写、内存和带宽基准 |
| T7 SSE/REST | 068/094/105/119/128/184/186；Training SSE signature 与详情轮询已单独登记 | SSE 断连/重连/慢客户端与 REST 连续状态一致性 E2E |

**覆盖结论：** 主要高风险模块具备可追溯的静态源码和入口级审计线索；**不能认定所有分支组合、运行时竞态和性能上限已被完整验证**。当前仅有 GitHub Actions / check-runs 通过，尚无本节提出的真实环境故障注入与规模验收结果。

### E. 发布阻断与验收门禁

- **必须优先修复或隔离全部实际可达 P0**，尤其 085/084/108/132/138/139/142/148/149/151/152/157/170/171/173/175/181；每个问题补回归并确认并发/fail-closed。
- Agent/远程生产环境不能在 055/060/063/070/092/093/158 等关键 P1 未修时宣称资源安全/自动恢复可靠；涉及源数据依赖的 168/169/178 也属于真实 Agent 部署阻断。
- 对 147/150/165 的 Training 表单准入使用同一 server authoritative preview 与 Prepare 真相；禁止靠“接收后后台失败”替代 admission。
- 部署前必须有目标 HEAD 的所有 Actions/check-runs completed-success、目标硬件回归、素材/算法版本完整性测试、Keyring/OSS 演练；queued/in_progress/cancelled 一律不算通过。
- CI 全绿不是修复证据；本阶段禁止 merge main、tag、release、生产部署及降低断言。

**状态：AUDIT PHASE — REGISTERED / REPAIR NOT STARTED；Stage-1 Repair Roadmap READY；不是“全仓无 Bug”结论。**

**本次文档收口提交版本：42.24.281；未新增 AUDIT 编号，未修改任何生产源文件或测试。**


## 2026-10-08 修复日志 — AUDIT-148 首批准确性栅栏（42.24.282）

**状态：FIX IMPLEMENTED / CI PENDING / E2E PENDING（不宣布 CLOSED）。**

- 修复 platform_core/snapshots.py 的共享 Snapshot scope gate：annotated 正样本和 confirmed_empty 负样本均要求本次 schema 全部标签已审核；不自动把 scope 扩成全部标签，缺口 fail-closed；旧负样本错误语义保留。
- 修复 platform_core/training_label_tasks.py 当前 canonical 训练标签投影：从原始已确认 scope 检查 task schema，不能把只有 smoke 审核证据的图片删掉 smoke 框、再伪造成 fire 已确认负样本。完整 scope 下现有 redaction 行为保留；原有全量 GT 不变。
- 新增 legacy 和 Durable Snapshot 回归，以及仅部分审核但投影后产生正样本/伪负样本的回归；更新历史测试中隐含的多类 partial scope 假设。
- **范围：** 只处理 AUDIT-148 中的训练 projection / Snapshot 主链；Picker/admission 提前预检、多模块 1k-20k 及真实 GPU 训练 E2E 尚未证明，后续仍需验收。与 R0 Material content-generation / 删除 fence 是独立待修问题。
- 约束：没有新增 Annotation Owner，没有修改生产 GT，没有合并 main / tag / release；VERSION 42.24.281 → 42.24.282。


### 2026-10-08 AUDIT-148 CI 失败与回归修正（42.24.283）

- 前一提交 42.24.282 在 Training Input Integrity / Label Normalization Contract 的已完成日志中发现相同 3 个失败：test_input_freeze_reserves_new_label_positive_in_train_split、test_projection_turns_only_unselected_labels_into_task_negative_without_mutating_source、test_task_filtered_negative_materializes_as_empty_yolo_label。
- 根因：旧测试构造 annotated 图片时仅冻结盒子类别的 scope，却用多类别 schema 训练或把未选中类别变成空负样本；新安全栅栏正确拒绝了没有复核证据的输入。
- 仅修正上述测试的正式审核前置条件，明确给每张图片添加其训练场景已审核的类别 scope。保留全部既有 split、原图不变、遮挡区域、负样本生成、导出文件和版本身份断言；不移除测试、不放宽生产 scope gate。
- 42.24.282 阶段观察到 CI 红灯，因此未宣称修复验收；42.24.283 需重新核验目标 HEAD 的完整 Actions/check-runs。AUDIT-148 仍为 FIX IMPLEMENTED / CI PENDING / E2E PENDING。


## 2026-10-08 修复日志 — AUDIT-152 清洗证据源内容 identity fence（42.24.284）

**状态：FIX IMPLEMENTED / CI PENDING / CONCURRENT RESCAN E2E PENDING（不宣布 CLOSED）。**

- 清洗结果冻结 source_content_sha256；合法 corrupt finding 也记录解码之前已校验的 content hash。旧历史结果从 metrics.sha256 兼容读取；无法提供可验证源 hash 的结果禁止确认。
- MaterialBatch CLEAN retry 保留源内容不变的成功行；以 500 条为单位比较已成功清洗行的 source hash 和当前 MaterialRepository hash。变化/丢失/无证据的成功行在**同一 selection SQLite 事务**中重置 pending，并清理旧 clean_results、exact/near-duplicate index 和 flagged counter；随后重做分析。
- Worker crash recovery 对已经持久化结果但未完成 selection 的行同样核对 hash，防止内容已换而恢复复用。
- v47 清洗确认前按冻结 selection 批量核对**所有**选中行必须 succeeded 且 source SHA 匹配；有任一失败、缺失、hash 变化时返回 409，不删除任何图片、不标记 processed。delete_ids 不得超出冻结范围。
- 新增 API 回归：清洗完成后模拟同 material_id 的 H1→H2 内容更新，确认全部接受或请求删除均 409；未经扫描不得确认。
- **剩余界限：** 这是确认动作的前置 evidence fence；尚未在 MaterialStore 与外部 Storage Rescan 上建立跨数据库/对象存储的原子 compare-and-swap。确认校验与实际 DELETE/patch 之间如果发生 concurrent Rescan，仍需 R0 共享生命周期协调锁/不可逆写入 fence。不能宣称 AUDIT-152 完全 CLOSED。
- 不引入第二 Cleaning/Annotation Owner，不更改 VERSION 主/次段、不合并 main、不删除或放宽既有回归。


### 2026-10-08 AUDIT-152 retry regression extension（42.24.285）

- 针对同一 Durable selection 的 succeeded 行加入独立 SQLite 回归：H1→H2 的旧成功行转 pending、result/LSH hash/bands 一并删除；未变化行继续 succeeded 并保留 result/index；历史无来源 SHA 的 success 也 fail closed 重扫。
- 同时断言 clean_flagged 汇总回零、selection counters 正确、重复 retry 不重置稳定行，覆盖 AUDIT-152 的退化性能约束。
- 原有 CI 结果只对 42.24.284 HEAD 有效；本次提交后以 42.24.285 为唯一验收目标，仍未完成并发 Rescan 的跨仓原子 fence。


## 2026-10-08 修复日志 — AUDIT-157 AI Candidate 内容身份证据栅栏（42.24.286）

**状态：FIX IMPLEMENTED / CI PENDING / CONCURRENT MATERIAL CAS PENDING（尚未 CLOSED）。**

- 普通 AI_ANNOTATION Worker 的 load_task_images 在 StorageManager.materialize 真实校验后，将 source_content_sha256 绑定到 worker 读取的素材代际；CandidateStore 继续作为唯一候选 owner，在 success/empty item_json 内冻结证据。
- MaterialBatch AI_ANNOTATE 生成路径同样将本次 materialize verified SHA 冻结进 Candidate item。crash/retry 只复用与当前 MaterialRepository SHA 一致的已有成功候选；不引入额外 Candidate owner。
- 正式人工确认写入前按 **不超过 200 条**读取当前 MaterialRepository source SHA；H1 候选遇 H2 素材、已删素材或没有可信 hash 的历史候选，均 fail closed，禁止将旧框写成新 Ground Truth；Annotation expected_version CAS 保留。
- 新增 unit 验证：旧 SHA、新 SHA、缺失 SHA、素材缺失的拒绝，以及生成时冻结 hash；现有 1k/10k/20k 候选提交测试使用合成但明确的 source-hash 身份校验，不通过跳过正式入库 guard 换绿。
- 边界：当前属于在正式 GT 写入之前的 evidence fence，Material 内容在批量 SHA 校验后到 AnnotationRepository transaction 中发生并发 Rescan 的 TOCTOU 窗口，需 AUDIT-099/149/173 共用跨 Owner 事务协调；尚不宣称所有竞态 CLOSED。
- VERSION 42.24.285 → 42.24.286；不合并 main、不发布生产、不新增第二 Annotation/Candidate Owner。


### 2026-10-08 AUDIT-157 回归测试辅助函数修正（42.24.287）

- 在 42.24.286 提交后的自查中，发现 tests/unit/test_annotation_task_service.py 的 _seed_verified_candidates() 意外递归调用自身，无法执行回归。此次仅把该调用改回 CandidateStore.append_items；不更改 production fail-closed guard。
- 42.24.286 因自检发现测试辅助问题，不作为 CI 验收基线；所有验证改以 42.24.287 当前 HEAD 为准。继续要求 completed-success 后才能记录 CI PASS。
