# 2026-10-06 前后端一致性 / 非法套娃 / 重复 Owner 审计问题清单

> 项目：畅联云算法训练平台  
> 仓库：`jorsamj/aixunlianpingtai`  
> 长期分支：`feature/external-algorithm-publishing`  
> 审计基线 HEAD：`3b5c073f9a2c9c532cbab6cfec3e899c5a4091a5`  
> 审计基线 VERSION：`42.24.109`  
> 本文档提交后 VERSION：`42.24.110`  
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

- GitHub Actions workflows：`23 / 23 completed success`
- check-runs：`61 / 61 completed success`
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

### Service Node 停用语义

已经确认“删除节点”有 busy guard。

下一步仍需确认：

- `enabled=false` 是否只阻止新调度；
- 已领取 assignment / lease 是否继续安全执行；
- heartbeat 是否仍可更新；
- disabled 节点是否还能 claim 新任务；
- finish / result upload 是否会因为 disabled 被错误拒绝；
- GPU reservation 是否仍由原 owner 正确释放。

证据未完成前，不编号。

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
10. 删除整个 Project / Dataset / Image 是否绕过当前 durable references；
11. 1k / 10k / 20k 下无界 hydration、N+1、O(N²)；
12. build/cache identity 统一。

---

## 6. 当前修复优先级

审计尚未全部完成，当前建议顺序：

1. **AUDIT-002** — Router 非法套娃 / 残缺 Agent Router
2. **AUDIT-011** — 整算法删除绕过 Version Retirement
3. **AUDIT-014** — ZIP active job 可被直接 DELETE
4. **AUDIT-009** — Paddle Training 前端可选、后端必失败
5. **AUDIT-010** — Training Settings 重复 DOM / 双参数 UI owner
6. **AUDIT-003 / AUDIT-004** — API Schema 与 runtime 漂移
7. **AUDIT-005** — Modal close scope
8. **AUDIT-013** — 训练次数统计 truth
9. **AUDIT-008** — Legacy Annotation 全局写入口
10. **AUDIT-006** — build/version truth
11. **AUDIT-001 / AUDIT-007** — 重复 helper / dead modalStack owner

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

- 从“Service Node 停用语义”开始；
- 发现疑点先复核；
- 确认后才新增 `AUDIT-015+`；
- 如果后续证据推翻已登记项，必须像 AUDIT-012 一样显式撤销；
- 当前仍以审计为主，不要直接大改生产代码。
