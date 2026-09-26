# v42.25 技术债关闭总账

## 2026-09-26 晚间标注 / AI / 训练 / 素材性能债总账（最新）

状态：**IMPLEMENTED / LATEST CI PENDING**。

- 本节写入前远端 HEAD：`704a8cc25c280a3480b146d65b8aef367de08fa0`（docs-only）。
- 最新产品代码基线：`684c7653f00cb5781015c26bf288dcb4df030e85`。
- `VERSION.txt = 42.24.0`，禁止改成 42.25.0。
- 历史强绿基线：`07fef8c2c9f6d8a99e9c4632730e618bdc4947f7` 的 20/20 主要 workflows 已重新核实全部 completed success。
- 最新 `704a8cc2...` 的 20 个主要 workflows 当前仍 queued；queued/in_progress 不能记 PASS。

本轮已经关闭的核心性能债：

- AI task image resolution：全库 `load_images` → MaterialRepository `get_many <=500`。
- AI review commit：逐图 Candidate/Annotation I/O → 200/批 formal GT + commit journal，保留 fencing/cancel/idempotency/crash recovery。
- Training selected annotation：逐图 `AnnotationRepository.get` → `get_many <=500`；1k/10k/20k 结构合同已固定复杂度。
- Manual annotation GET/SAVE：单图操作不再全库扫描；保存后只 patch 当前素材卡与 preview，不全页刷新。
- AI label decision：中文名/alias/历史 alias 不再自动转 canonical code；只能由用户明确输入 current canonical code。
- AI detail/list polling：PollRegistry 单 owner；详情关闭清理，不再双 poll。
- Label remap / AI / cleaning 高频进度：使用字段级 patch + `transform: scaleX()`，不再整块 modal 重建或 width 高频布局写。
- Historical annotation summary migration：500/批 read + 500/批 projection patch。
- Training scoped projection / benchmark reuse / supplement candidate set / quality reads：复用 frozen truth 或批量 indexed lookup，不再二次 N+1 / 全库扫描。
- Selected batch split / single material edit / upload review / import review：改为 indexed/batched owner；不再为少量选择 full-table mutate / full-library load。
- Cleaning confirmation：冻结 selection 后 500/批 get_many + 500/批 patch_many；禁止恢复 full-table mutate。
- Training submit UX：提交期间显示真实 HTTP/create 阶段，durable task 创建后继续显示后端真实 phase/current_item；不伪造 snapshot/Ground Truth 阶段。

永久原则继续保持：

- AnnotationRepository 是唯一 formal Ground Truth owner；AI Candidate 与正式标注分离。
- canonical label 必须由用户明确决定；alias 只能用于搜索/历史审计。
- 不新增第二套 Upload / ZIP / Material Batch / Cleaning / Training / Poll runtime。
- 普通浏览器未上传到服务端的本地 File 字节，页面关闭后不能继续读取；禁止假宣传。

仍未关闭的只有：

1. 最新 HEAD 自身 20 个 workflows 的 terminal 结果；任何 completed failure 必须先读真实 job log。
2. 真实 20k/50k 图片、真实 OSS/S3 RTT、NVIDIA Linux、SQLite WAL contention、峰值内存与慢网络浏览器验收。现有自动化证明复杂度/owner/contract，不替代真实硬件吞吐验收。

## 2026-09-26 标签治理闭环增量（覆盖下方较早同日 pending 清单）

状态：**IMPLEMENTED / CI PENDING**。当前基线 HEAD：`6d2b8916edaaac35d1f47093d26792032cc7fc7c`，`VERSION.txt = 42.24.0`。

已进一步关闭：

- external-class review 的 search / 50-row pagination / cross-page state / bulk many-to-one mapping / final summary。
- external-label 真实样例证据：默认 8、最大 12，bbox overlay，短期 presign + class-fenced fallback。
- 多来源 canonical merge：最多 50 个 source labels 的 indexed union selection，仍复用 `REMAP_ANNOTATION_LABELS` durable owner。
- merge 仅在全成功时将 source labels 标记 `merged`；partial/failed 不退役，避免半合并 schema。
- canonical label 删除已改 soft-disable，不再重排其他 project class ids。
- AI candidate alias 自动解析已退休，只接受本次任务明确 canonical code。
- imported provenance 在 merge 后保持 source_* 不变，同时更新 canonical_label_id / canonical_project_class_id。
- 项目元数据保存与 merge finalization 使用一致 FileLock / atomic write 边界，避免并发损坏。

当前仅剩：

- 最新 HEAD 完整 CI 结果仍在等待；queued/in_progress 不能记 PASS。
- 真实 20k + OSS/S3 + NVIDIA 生产环境性能验收未做，现有 10k 自动化合同不能替代生产验收。
- 普通浏览器本地字节未上传完时关闭页面不能继续传输，这是浏览器安全模型边界。


> **状态：ACTIVE / 标签导入、Ground Truth 与训练 schema 技术债收口中**
> **当前分支：`feature/external-algorithm-publishing`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **本轮文档基线 HEAD：`60e31539454300f466b90924f4c15a7a3d3bd218`**
> **当前 CI：最新 HEAD checks 尚在 queued；不得把排队态表述为通过。下方历史 PASS 只证明对应历史 HEAD。**
> **更新日期：2026-09-26**


## 2026-09-26 — Label import / Ground Truth / training schema closure — IMPLEMENTED, CI PENDING

本批次没有新建第二套导入、清洗、标签统一或训练 runtime，而是在现有 durable owner 上收口。

### 已关闭的技术债

- **自动标签映射决策退休**：ZIP、storage import、rescan、AI annotation 均不再根据同名、中文名、alias、历史映射自动选择 canonical 标签。外部类只暴露事实，映射必须人工确认。
- **标签统一同步阻塞退休**：已使用标签不再通过同步 HTTP 全库扫描修改。全库统一复用 `MATERIAL_BATCH / REMAP_ANNOTATION_LABELS`，后端按标签索引冻结选择，Worker 分批执行，浏览器只显示任务进度。
- **confirmed_empty scope 漏写修复**：scope-only remap 会真正写入 AnnotationRepository。新增 `material_annotation_scopes` 索引，只索引 confirmed-empty 范围，避免与 annotated 正样本双计。
- **Annotation remap N-connection 热点**：同一 Worker batch 改为 `get_many` 预加载，不再对每张图单独打开查询连接。
- **导入来源不可追溯**：正式 box 现在持久化 external source class/name/import batch/source format/manual mapping provenance。
- **训练脏 schema 进入 YOLO**：训练 preflight 阻断 unmapped / deleted / inactive / temp / unknown 类别；标签读取按 500 条批量查询。
- **迭代 schema 变化不显式**：训练合同现在记录 retained/dropped labels、`label_schema_changed`、原因、`base_training_mode`，并明确 `strict_resume=false` / `optimizer_state_resumed=false`。

### 性能与 UI 合同

- 大量标签统一使用 durable task，显示真实 processed/total/succeeded/failed/progress；关闭弹窗不取消任务。
- ZIP/服务器/对象存储导入继续使用既有 durable background pipeline；确认动作不在 HTTP 请求里同步写万级素材。
- 普通浏览器上传继续分块提交；只有已经送达服务端的数据才能在页面关闭后继续处理，未上传完的本地文件字节不能由后台接管。
- 标签管理页只展示聚合统计，不为了统一标签把几万张素材 ID 注入 DOM。
- 任何新 UI 都必须复用现有 PollRegistry / material batch owner，不得再加递归 timer 或第二个 task state machine。

### 尚未关闭

- 大量 external classes 的映射审查 UI 仍需 search + pagination/virtualization + bulk mapping + final summary。
- 每个 external label 的 6–12 个真实样本 bbox crop / full-image lazy viewer 尚未补齐。
- Canonical label 删除仍应单独设计为 soft-disable 或 durable schema mutation；不得恢复同步全库 class-id rewrite。
- 最新 HEAD CI 尚未完成。只有全部必要 checks completed success 后，才可把本节状态从 CI PENDING 改成 CLOSED。

### 本批次提交

`7c356f2d` → `1aa2f995` → `fbca3349` → `68dd8319` → `27a4806e` → `029d15fe` → `60e31539`


## Product closure — Deployment-test durable queue/progress truth CLOSED

The deployment-test business surface now preserves the same durable task truth as the unified v62 task API. Previously the v61 compatibility projection flattened a resource-waiting durable task back to persisted `QUEUED`, dropped queue/resource/worker metadata, and the final `benchPredictOne` loop only considered `QUEUED / RUNNING / CANCEL_REQUESTED` active. That combination could make a real `WAITING_RESOURCE` deployment test appear terminal or fail without showing why it was waiting.

Closed semantics:

```text
v61 business projection: delegates durable task fields to task_to_public()
compatibility aliases: id / progress / stage / result remain for the existing deployment surface
WAITING_RESOURCE: remains active and visible instead of being flattened to QUEUED
queue truth: resource_queue_position + resource_wait_reason are server-derived and visible
worker/progress truth: worker_id / phase / progress_percent come from durable public truth
active polling: after v61 creation, benchPredictOne reads /api/v62/projects/{project_id}/tasks/{task_id} while the task is active
terminal success: v61 is read once after SUCCEEDED to obtain deployment-specific result payload
frontend projection: PlatformCore.deployment.deploymentTaskView reuses taskPoller active/progress semantics
queue order / resource admission / worker claim / progress generation / process fencing: unchanged
```

Permanent guards include `tests/api/test_deployment_test_runtime.py`, `tests/frontend/deployment-runtime-source.test.mjs`, `tests/frontend/deployment-task-view.test.mjs`, `tests/unit/task_runtime/test_public_projection.py`, and `tests/unit/test_deployment_inference_process_fencing.py`. Release Regression now permanently runs the deployment business-projection contract and is triggered by the deployment task view/wiring guards. The frontend does not invent queue order or percentage; it only renders unified durable truth.

Evidence:

```text
valid RED head:             5748a89155e653a49c8a8c743cdd3de7a9fa67cf
valid RED run:              34794353496 (backend v61 QUEUED vs v62 WAITING_RESOURCE; final frontend unified-truth wiring RED)
focused/full GREEN run:     34794490531 PASS (API + frontend + public projection + deployment fencing + full frontend unit)
product commit:             0b800a54ae64507314a5f9199734759250691cb6
formal accepted clean HEAD: 1c3fa7f2b5cb826c0998f249637241a59134f053
Release Regression:         34794630826 PASS
Navigation Action Fencing:  34794630808 PASS (Real Chrome PASS)
Frontend Runtime:           34794630837 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All temporary deployment RED/migration helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Next product batch: **storage import polling owner / lifecycle-managed polling truth**. Storage import already preserves durable queue/progress display truth, but its action runtime still owns a direct `while + setTimeout(1200)` polling loop; that owner must be audited separately without mixing it into this deployment closure.

## Product closure — Cleaning frontend queue/progress truth CLOSED

The final cleaning tab now subscribes to the durable v47 cleaning projection instead of flattening server truth into a generic local row. The backend already exposed `status_text`, `progress`, `processed_images`, `total_images`, `flagged_images`, `resource_queue_position`, `resource_wait_reason`, and worker identity; this batch makes the final visible clean-tab owner preserve those values through both initial rendering and managed refresh.

Closed semantics:

```text
status text: consume server status_text; WAITING_RESOURCE compatibility projection remains “等待资源” instead of being flattened to “排队中”
queue metadata: show real resource_queue_position + resource_wait_reason when present
progress: use server progress / processed_images / total_images only; no browser-simulated percentage
worker metadata: running rows may show the real worker_id supplied by the server
polling owner: PollRegistry owns clean-tasks-v47 as a page/tab-scoped 2200 ms one-shot
refresh owner: refreshCleanOps427Delta refreshes only the cleaning task list and patches clean rows
terminal truth: awaiting_confirmation is terminal for list polling; the clean timer is not re-armed
navigation/tab change: PollRegistry clears the clean timer; switching back to AI annotation also clears it immediately
legacy recursive setTimeout(renderOps427, 2200): retired
backend queue order / claim / progress generation / worker execution: unchanged
```

`static/modules/cleaning.js` now owns the pure `cleanTaskView()` / `isActiveCleanTask()` projection. `static/main.mjs` exposes those helpers through `PlatformCore.cleaning`. `static/modules/poll-registry.js` owns `clean-tasks-v47`, and the final v427 clean branch in `static/app.js` consumes that view-model. The v47 public compatibility contract permanently requires the queue metadata fields to exist; their values remain dynamic server truth (for example, an immediately queued task may legitimately report position `1`).

Permanent guards:

```text
tests/frontend/clean-task-view.test.mjs
  - waiting-resource status/queue/progress truth
  - running worker/progress truth
  - final app.js wiring consumes cleanTaskView + PollRegistry
  - retired direct recursive clean-list timer cannot return

tests/frontend/poll-registry.test.mjs
  - clean-tasks-v47 one-shot lifecycle
  - re-arm only while active
  - stop at awaiting_confirmation
  - clear on navigation

tests/api/test_clean_unified_execution_truth.py
  - v47 public queue metadata fields are permanent
  - dynamic queue position is accepted as server truth, never forced to a frontend assumption
```

Evidence:

```text
valid RED commit:           cf3f2c4fec639903435379b3419dbaadad82c949
valid RED run:              34793075909 (245 frontend tests: 242 PASS; exactly 3 intended cleaning truth assertions RED)
focused/full GREEN run:     34793282831 PASS (focused cleaning contracts + full frontend unit + wiring guard)
product commit:             9f6f329393018623807cb4fea04707f3b5350676
formal accepted clean HEAD: 736b2acdbf2560be657011035de173cde67517d0
Release Regression:         34793457861 PASS
Navigation Action Fencing:  34793457872 PASS (Real Chrome PASS)
Frontend Runtime:           34793457920 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

The temporary frontend migration helper/workflow were physically deleted before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Deployment-test durable queue/progress truth is now CLOSED. Next product scope: **storage import polling owner / lifecycle-managed polling truth**. Genuine 10,000-image processing acceptance remains explicitly deferred.

## Product closure — Cleaning durable execution truth CLOSED

The active v47 manual-clean and v55 upload-batch clean entry points now publish one durable `MATERIAL_BATCH/CLEAN` task into the shared `TaskRepository`. The Web/API process no longer owns cleaning execution through legacy daemon threads, and Web startup no longer resurrects those retired workers. Real execution is owned by the registered `materials` worker through `FencedTaskRepository` / `Scheduler` truth.

Closed semantics:

```text
manual v47 create -> prepare + publish one MATERIAL_BATCH/CLEAN durable task
v55 upload-batch decision -> the deterministic clean_task_id points to that same durable task truth
real execution -> materials Scheduler / fenced WorkerContext, never Web daemon execution
prepare -> publish crash window -> reuse the already-frozen semantic request without treating its freeze-time repository_revision as a new user intent
FAILED retry -> same task id is re-queued through TaskRepository retry; no duplicate task identity
successful scan awaiting confirmation -> durable task remains SUCCEEDED/succeeded; v47 compatibility alone projects awaiting_confirmation/review
corrupt image with corrupt_check -> successful flagged cleaning finding for review
source content changed after indexing -> remains SOURCE_CONTENT_CHANGED storage-integrity failure, not disguised as image corruption
```

A real-worker defect was also closed: `MaterialBatchHandler` had called a private artifact validation method that does not exist on the real `FencedArtifactStore`, causing Scheduler execution to fail before processing any material. The handler now validates `project_id` as a safe single path component while preserving fenced artifact access. Corrupt findings are excluded from the hash/dedup index unless real `sha256` and `dhash` metrics exist.

Permanent guards include `tests/api/test_clean_unified_execution_truth.py`, `tests/api/test_upload_clean_flow.py`, `tests/unit/test_material_batch_public_truth.py`, and the Release Regression path/test scope. The final guard explicitly proves that reading the v47 compatibility result may show `awaiting_confirmation / review` while the underlying durable record remains `SUCCEEDED / succeeded`.

Evidence:

```text
valid RED commit:           3f41cdae0d4234bf5171f2aa80111513c223407c
valid RED run:              34790397474 (intended durable-clean execution assertions RED)
focused durable migration:  34792422835 PASS (4 durable contracts + 32 upload-clean regressions)
product commit:             f43631e16a51167cf75bb8e2ec545566f226609f
formal accepted clean HEAD: 3931a9a2d529845f9e698b22f62fe950a7a8b42f
Release Regression:         34792673327 PASS
Navigation Action Fencing:  34792673293 PASS (Real Chrome PASS)
Frontend Runtime:           34792673296 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All one-shot cleaning migration/diagnostic helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Following batch status: **cleaning frontend queue/progress truth is now CLOSED**. Current next product scope is the storage import / deployment-test queue and progress truth audit.

## Product closure — Plain image upload whole-task progress truth CLOSED

The final live ordinary-image upload owner is the storage61 `doUploadImages426` path posting to `/api/projects/{project_id}/images`. The endpoint is synchronous HTTP, but after browser request bytes are sent the server still performs temporary-file handling, image validation, selected-storage object write, SHA256 calculation and material record commit. Therefore browser `xhr.upload` byte completion is not whole-task completion.

Closed semantics:

```text
browser byte transfer: 0% -> 85%
byte transfer complete: hold at 85%, show “文件已上传，正在服务器入库”
server-side synchronous commit: no fabricated percentage animation
successful HTTP completion after material commit: 100%, show “服务器入库完成”
network/non-2xx failure: never claims terminal 100%
```

This batch deliberately does **not** invent a durable background task, fake queue, or fake server progress for a synchronous endpoint. Terminal 100% is fenced to the authoritative successful HTTP completion. Permanent behavior guard: `tests/frontend/image-upload-overall-progress.test.mjs`; Release Regression includes that test in its permanent path scope.

Evidence:

```text
valid RED commit:          03be0050644af80709bddb97321f1a4ec0b1528c
valid RED run:             34788264443 (237 existing tests PASS; 2 intended new assertions RED)
focused migration/GREEN:   34788320142 PASS
product commit:            259d76d753993f2dd10e1963ee1a9a13887209ad
accepted clean code point: bae90eae4b3768d365d20344c1f2db9a75795ac8
Release Regression:        34788383779 PASS
Navigation Action Fencing: 34788383742 PASS (Real Chrome PASS)
Frontend Runtime:          34788383772 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

The one-shot product migration workflow was removed in the product commit. No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## Product closure — Video resource queue truth CLOSED

The live v424 video task page already reads `/api/v33/projects/{project_id}/video-tasks`, whose public projection is backed by the shared durable `TaskRepository`. `task_to_public()` dynamically exposes resource-scoped `resource_queue_position` / `resource_wait_reason`; a durable queued task in the `resource_waiting` phase is publicly projected as `WAITING_RESOURCE`. The frontend previously dropped that queue metadata and also failed to classify `WAITING_RESOURCE` as an active video task, so a genuinely resource-waiting task could lose timely managed polling and never show its real queue position/reason.

Closed semantics:

```text
QUEUED: remains active under PollRegistry and shows real resource_queue_position when available
WAITING_RESOURCE: remains active, shows “等待资源”, real queue position and resource wait reason
initial render + delta polling: both use the same v424 row projection and preserve runtimeText
progress: continues to come from durable server/worker truth; no frontend progress simulation
queue ordering / claim / queue_rank / resource fencing: unchanged
cancel / stale-worker / publish fencing: unchanged
```

The fix is intentionally narrow. `static/modules/video-tasks.js` now projects the existing durable queue metadata into `runtimeText` and treats public `WAITING_RESOURCE` as active; the final v424 `videoTaskRow424()` renders that view-model text. `PollRegistry` remains the sole video polling lifecycle owner. Permanent behavior guard: `tests/frontend/video-tasks.test.mjs`, which executes the real final row renderer and verifies both queued and waiting-resource behavior.

Evidence:

```text
final permanent RED commit: 32284a8972faec46775144b8c47406e67edee014
valid RED run:              34789541200 (242 total; 239 PASS; only 3 intended video truth assertions RED)
focused/full GREEN run:     34789628840 PASS
product/self-cleanup:       c0fee2b7c8dfbf03481cbc6dfb1019f922293576
formal clean HEAD:          cb81ca39016aea0fc53ed52090f0b0199d39109a
Release Regression:         34789701814 PASS
Navigation Action Fencing:  34789703315 PASS (Real Chrome PASS)
Frontend Runtime:           34789704610 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP processing acceptance was performed. One-shot product/gate migration assets were physically deleted before formal gate acceptance.

## Product closure — AI annotation polling queue metadata truth CLOSED

The durable v60 AI annotation backend/public projection already exposes real `resource_queue_position` and `resource_wait_reason`, and `annotationTaskView()` already turns that truth into `runtimeText`. Initial page rendering consumed `runtimeText`, but `AutoLabelPollRuntime` used a separate row renderer during polling refresh and omitted it. Result: a task could initially show `资源队列第 N 位` / resource wait reason and then lose that truthful metadata after the first managed poll refresh even though durable truth had not changed.

Closed semantics:

```text
initial render: durable status + progress + runtimeText
managed polling refresh: the same durable status + progress + runtimeText
QUEUED / WAITING_RESOURCE: resource queue position remains visible after every refresh
resource wait reason: remains visible when projected by annotationTaskView
no frontend queue simulation, no claim/order/resource-fencing changes
```

The fix is intentionally narrow: `static/modules/auto-label-poll-runtime.js` now renders existing `view.runtimeText` beside the status pill. No backend queue ordering, task claim, execution fencing, polling cadence, or progress semantics changed. Permanent behavior guard lives in `tests/frontend/auto-label-poll-runtime.test.mjs`; Release Regression path scope now includes both the polling runtime and its guard.

Evidence:

```text
valid RED commit:          186005b428f361e88553555b3a86013d206f11b3
valid RED run:             34788748122 (239 existing tests PASS; 1 intended queue-metadata assertion RED)
product commit:            ddb1168a8f3457fef3d875ceec79e618b75acee9
accepted clean code point: 2bc6f72fddd878a7e2d4802c5affd3d640f807e7
Release Regression:        34788824842 PASS
Navigation Action Fencing: 34788824910 PASS (Real Chrome PASS)
Frontend Runtime:          34788824849 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## 0. 接手入口

按顺序阅读：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`
4. `docs/FRONTEND_OWNER_MAP_V42_25.md`

技术债清理主线已按用户要求暂停。剩余非阻断债务保持 OPEN/DEFERRED；只有真实功能、性能、数据完整性或发布验收问题才恢复对应清理。未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## Product mainline checkpoint — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.
- **ZIP 10k acceptance**: focused CI created a real ZIP with **10,000 image members** and passed the v19 create/scalability contract plus existing server-import/storage regressions. The permanent legacy unit guard was migrated, not weakened (`27654cba1fb3406567a40754904531c2b53aa53f`), and the permanent Chrome material/import contract was migrated to the real v19 sequence (`60305921402204e77b8e7ed4ec8e576d9f857c4b`): create → start → list polling → terminal done → labels/current paged-material scoped refresh, with an explicit assertion that no `/api/v18/` request or broad reload occurs. Final Frontend Runtime `34733035739` passed all frontend unit guards and Real Chrome **33/33 PASS (53.9s)**; Action Fencing `34733035761` PASS.
- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.95`; `main.mjs` cache remains `42.25.92`. No merge/tag/release.

**Video resource queue truth is CLOSED. Current next product scope: continue the horizontal real queue-position/progress audit across cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**

## 1. 永久退休 surface

以下对象不得恢复为 truth source、bootstrap fallback、timer owner、polling shell、direct navigation owner、historical render owner 或 visible-version owner：

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
auto422Timer
ai60ListTimer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
source422Timer
jobPollTimer
setupPagePolling
installVideo424CreationBridge
installSourceCreationBridge
installPollingCreationBridge
__pollRegistryVideoWrapped
__pollRegistrySourceWrapped
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
set423Base
setBase424
baseSetPage
oldSetV39
oldSet42
set422Base
v34/v35/v42.4 direct window.setPage owners
v42.7 direct window.setPage auto-label alias owner
setPageReady414
baseSetPage417
initial bootstrap setPage/window.setPage owner
v42.7 render-level state.page 自动标注 → 自动标注及清洗 mutation
oldRender429
previousRender61
render423Base
renderBase428 shadowed 算法列表 branch
v42.2 render422 legacy 自动标注 route branch
v42.4 renderBase424 legacy 自动标注 route branch
renderBase424 shadowed 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 自动标注 self-refresh timeout/predicate
baseRender417 visible-version correction wrapper
baseRender417 120/600/1600ms version correction timers
12 historical app.js delayed versionBadge startup writers
main.mjs applyBuildVersion visible-version owner
main.mjs 80/500/1800/3600/8000ms visible-version writers
render426base page-render file-input beautification wrapper
render426base requestAnimationFrame page beautification callback
modal426 modal file-input beautification wrapper
modal426 requestAnimationFrame modal beautification callback
enhancePageV37 compatibility helper
requestAnimationFrame(enhancePageV37) page callback
enhancePageV37 modal normalization callback
baseRenderV37 duplicate versionInfo wrapper
baseModalV37 autofocus compatibility wrapper
v35/v36/V37 80/100/120ms startup render/version timers
bounded 100ms renderTop/cleanup startup timer
oldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver
transport.mode-only material summary page guard / off-page summary request leakage
legacy baseRender + RAF page normalization wrapper
#view post-render MutationObserver
#modalBody normalization MutationObserver
base algorithm CRUD `window.newAlgorithm/saveAlgorithm/editAlgorithm/saveEditAlgorithm/viewAlgorithm`
v30 `oldRenderAlgorithms` algorithm renderer wrapper
v39 `oldViewAlgoV39` algorithm detail wrapper
v42.2 `renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422` shadowed algorithm page generation
v423 shadowed `openNewAlgorithm423(async)/saveNewAlgorithm423/editAlgorithm423(old modal)/saveEditAlgorithm423` create/edit generation
shadowed Model Config v35/v426/v427 modal/save generations (`saveModelConfigV35/saveModelConfig426/saveModelConfig427`)
legacy dataset-group `selectDataset/newDataset/saveDataset/editDataset/saveEditDataset/delDataset`
`oldSelectDataset` persistence compatibility wrapper
legacy `currentDataset()` helper
two shadowed historical dataset-group render bodies
zero-reference dataset actions `uploadImages/autoSplit/buildYolo/checkDatasetQuality/setImageSplit`
```

## 2. 技术债状态

| 技术债 | 最终 owner / 目标 | 状态 |
|---|---|---|
| training 历史 mirror | `state.trainingDraft` | **CLOSED** |
| `/train/start` 多 owner / readiness | `TrainingSubmitRuntime` | **CLOSED** |
| `/jobs` 重复请求 race | `TrainingTaskRuntime` | **CLOSED** |
| metrics SQLite FD | deterministic close | **CLOSED** |
| training / AutoLabel / video / source polling | named runtime + `PollRegistry` | **CLOSED** |
| `setupPagePolling` / classic polling compatibility | direct managed owners | **CLOSED** |
| classic `setPage` owner family | `NavigationStability` | **CLOSED** |
| navigation alias/readiness/sidebar/apply/persistence | `NavigationStability` + `ui-state.js` | **CLOSED** |
| Navigation Action Fencing R1 — training-server/Paddle + targeted direct page writes | `NavigationStability.action` + epoch/token fence | **CLOSED (R1)** |
| Navigation Action Fencing R2 — final M4 model save/test + clean confirm + v60 AI review completion | live owner action fence before UI/state commit | **CLOSED (R2)** |
| Navigation Action Fencing remaining upload/deployment/timer/callback completions | final async-action zero-point | **OPEN / DEFERRED** |
| historical persisted `自动标注` alias | restore-boundary canonicalization | **CLOSED** |
| shadowed historical render generations/branches R2–R7 | bounded later render owners | **CLOSED** |
| legacy AutoLabel424 no-op self-refresh timer | `AutoLabelPollRuntime + PollRegistry` | **CLOSED** |
| visible version multi-owner / delayed writers | formal display owners + internal build metadata split | **CLOSED (R9)** |
| `render426base` page post-render wrapper | `cleanup(root)` page post-render owner | **CLOSED (R10)** |
| `modal426` modal post-render wrapper | `cleanup(root)` + `modalBody` MutationObserver | **CLOSED (R11)** |
| `enhancePageV37` post-render normalization helper | `cleanup(root)` table/panel normalization | **CLOSED (R12)** |
| `baseRenderV37` duplicate versionInfo wrapper | later `V42` render versionInfo owner | **CLOSED (R13)** |
| `baseModalV37` autofocus compatibility wrapper | base `modal()` autofocus | **CLOSED (R14)** |
| v35/v36/V37 startup render/version timers | final `queueMicrotask → __clInit` startup owner | **CLOSED (R15)** |
| body-wide ZIP review observer / persisted result race | `completeZipImportReview412` explicit completion owner | **CLOSED (R16)** |
| off-page material summary timer requests | page-scoped `refreshSummary61` | **CLOSED (R16)** |
| page normalization baseRender/RAF/view observer | final `PostRenderNormalizationRuntime.apply` | **CLOSED (R17)** |
| bounded 100ms startup cleanup timer | final `__clInit → render → PostRenderNormalizationRuntime` | **CLOSED (R18)** |
| `#modalBody` normalization observer | `ModalContentRuntime.replace` + synchronous `PostRenderNormalizationRuntime` | **CLOSED (R19)** |
| remaining historical render/post-render overrides | bounded semantic owners | **IN PROGRESS** |
| `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| algorithm version delete full reload | `AlgorithmListRuntime.refresh` (algorithms + jobs) | **CLOSED (R20a)** |
| model-version publish full reload | authoritative POST result + local state patch | **CLOSED (R20b)** |
| training-server create full reload | POST + training_options-only target refresh | **CLOSED (R20c)** |
| Paddle environment activation full reload | `refreshPaddleTrainingTargets20d` + training_options-only target refresh | **CLOSED (R20d)** |
| model-config / prompt-template mutation full reload + stale prompt UI | authoritative mutation result + local state patch | **CLOSED (R20e)** |
| model-config save/edit broad related refresh | M4 `saveVisionModelM4` authoritative result + local `state.modelConfigs` upsert | **CLOSED (R20f)** |
| resource-discovery SQLite init / manifest FD lifecycle | lock-safe single-owner init + deterministic close | **CODE-LEVEL CLOSED; production soak OPEN** |
| ZIP / server-storage import completion broad refresh | scoped labels + paged material refresh | **CLOSED (R20g)** |
| legacy algorithm CRUD + shadowed algorithm renderer generations | stable 414/423/429 owners + authoritative local `state.algorithms` patch | **CLOSED (R20h)** |
| legacy dataset-group CRUD + shadowed dataset render generations | final `renderDatasets424` route + bounded compatibility delegate | **CLOSED (R20i)** |
| zero-reference legacy dataset actions | physically retired, final `renderDatasets424` / import owners preserved | **CLOSED (R20j)** |
| live v18 `doImportData` success broad reload | labels + paged materials only | **CLOSED (R20k)** |
| source-import terminal completion broad refresh | labels + current paged materials only | **CLOSED (R20l)** |
| shadowed v35/v426/v427 Model Config generations | final M4 `saveVisionModelM4` + capture/final activation | **CLOSED (R20n)** |
| shadowed v423 algorithm create/edit broad-refresh generation | stable 414 authoritative local-state CRUD only | **CLOSED (R20m)** |
| global reload / duplicate request | scoped refresh / zero-point proof | **OPEN / PAUSED (R20)** |
| cache-busting | single strategy | **OPEN** |
| observer/timer/fetch/render lifecycle | explicit owner + destroy | **OPEN** |
| version-number business naming | semantic names | **OPEN** |
| A800 RC | acceptance runbook | **DEFERRED** |

### R20n — shadowed Model Config generations retirement CLOSED / 技术债主线暂停

Source-order 与删除前/后的同一套 M4 Real Chrome 合同证明：旧 v35 / v426 / v427 `openModelConfigModalV35 → saveModelConfigV35/saveModelConfig426/saveModelConfig427` generations 已被最终 M4 owner 覆盖，运行时不可达。R20n 仅物理删除这 3 套历史 modal/save generation；最终 `saveVisionModelM4`、`testModelConfigV35`、M4 capture/final activation、模型配置字段与 API 语义均保持不变。

```text
baseline + migration run: 34725790087
product:                  9acaa534e596464a1ebe129e435916ed7dd9cdf2
cleanup:                  fce8034a861e1f9c5c0d37568891717309845794
contract alignment / accepted HEAD: b83b2bf360b891265157e602f622d409d1d2332f
Frontend Runtime:         34725907423
full Real Chrome:         33/33 PASS
Navigation Action Fencing:34725907404 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

永久 source contract：`tests/frontend/shadowed-model-config-generations-r20n.test.mjs`；最终 M4 行为继续由 `tests/browser/navigation-action-fencing-r2.spec.mjs` 与现有 Action Fencing workflow 覆盖。一次性 R20n migration helper/workflow 已物理删除。

**按用户要求，从 R20n 起技术债清理主线 PAUSED。** 剩余 R20 global reload/request zero-point、stale-async final scan、cache-busting、历史 dead code、命名/结构归一化、Resource Lifecycle production soak 等均保持 OPEN/DEFERRED，不宣称 CLOSED；除非出现真实功能故障、明显性能问题、数据完整性风险或发布验收阻断，否则不得为了“代码更干净”继续展开技术债批次。

## 2.0a Navigation Action Fencing R1

### Navigation Action Fencing R1 — resource/Paddle mutation completion CLOSED

真实旧代码 baseline 已在 Real Chrome 证明：训练资源页慢 `POST /api/train_servers` 发出后，用户切到数据集并打开属于新页面的 modal；旧 POST 完成会执行 `closeModal()`，把新页面 modal 关闭并清掉 sentinel。该行为不是测试推断，而是浏览器复现。

```text
baseline / focused migration run: 34701875185
old Chrome failure: stale save completion closed or rewrote the new-page modal
product:            8269eb0cca84ea310f48ee13af34ab09dd1bfeff
follow-up:          01234ef186f3e57bef2d29ac19420952beef6c36
cleanup:            7fcfcaec0b088a851dbcd580ac226b3dd892fa83
Frontend Runtime:   34702374386
full Real Chrome:   32/32 PASS
permanent Action Fencing run: 34702374346 PASS
formal VERSION.txt: 42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
NavigationStability: 422512
```

R1 新增 `NavigationStability.action(ownerPage)`，通过 navigation epoch/token 暴露 `isCurrent()` / `commit()`；后台 mutation 可以完成，但 stale completion 不得再提交 modal、DOM、state 或 render side effect。`saveServer` 在 POST 后和 scoped `training_options` refresh 后都执行 stale fence。Paddle 手动/一键激活同样有 action fence；若用户仍在训练资源页，只做当前页 render + toast，不再冗余导航回自己。

R1 还将目标范围内的 direct page write 清零：训练资源、模型配置、部署转换、训练任务以及旧“新建算法/自动迭代 → 算法列表”renderer rewrite 不再通过 `state.page='xxx'; render()` 导航；需要跳页时统一走 `NavigationStability`/`window.setPage`。

永久合同：

```text
tests/frontend/navigation-action-fencing.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/browser/navigation-action-fencing.spec.mjs
.github/workflows/navigation-action-fencing.yml
```

一次性 R1 migration/follow-up helper 与 workflow 已物理删除。

**R1 边界已由 R2 继续收口。** R2 已关闭最终模型配置、清洗确认与 v60 AI review completion；图片/ZIP/XHR upload completion、deployment mutation、其他 timer/callback family 仍需 final scan，因此全局 stale-async zero-point 仍为 IN PROGRESS。

### Navigation Action Fencing R2 — final Model Config / clean / v60 AI completion CLOSED

真实 source-order/liveness 审计确认最终 owner 不是历史命名：模型配置保存由 `saveVisionModelM4` 负责；清洗确认最终为 `confirmClean429`，`confirmClean427` 仅兼容别名；AI 最终提交由 v60 `completeAiReview60(mode)` 负责，`confirmAiLabel427` 仅兼容到 `completeAiReview60('partial')`。

旧代码 Real Chrome baseline 真实复现了慢 mutation 完成后关闭/覆盖新页面 modal 的问题（M4 保存、最终清洗确认、v60 AI review completion）；模型连接测试 completion 同批通过 source contract 迁移并永久锁定。最终所有这些 owner 都在请求前捕获 `NavigationStability.action(state.page)`，并在 `await` 返回后、任何 state/DOM/modal/render/toast side effect 前检查 `action.isCurrent()`。

清洗确认不再 `loadRelated()` broad refresh，而是使用后端 authoritative `deleted_ids + processed_ids` 精确更新本地素材。v60 AI review 保持 durable `/api/v60/.../annotation-tasks/{id}/decisions` + `commit:true` 合同，只有当前 action 仍有效时才执行 `applyTaskResult/closeModal/toast/renderOps427`。

```text
baseline / migration run: 34721629224
product:                  9f6df85b994f23b5408759fb64485b9477c75936
cleanup / permanentize:   3a8781dccf6704fe76d35d99c05b80590dc507c3
Frontend Runtime:         34721755310
full Real Chrome:         32/32 PASS
permanent Action Fencing: 34721755316 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
NavigationStability:      422512
```

永久合同：

```text
tests/frontend/navigation-action-fencing-r2.test.mjs
tests/browser/navigation-action-fencing-r2.spec.mjs
.github/workflows/navigation-action-fencing.yml
```

R2 一次性 migration helper/workflow 已物理删除。**R2 本批 CLOSED；整个 Navigation Action Fencing final zero-point 仍未 CLOSED。**

## 2.0c R20m — shadowed v423 algorithm CRUD retirement

Source-order audit proved the early v423 create/edit generation is shadowed by the later stable 414 assignments. Its only `saveNewAlgorithm423` / `saveEditAlgorithm423` callsites lived inside those overwritten modal entrypoints. The existing algorithm CRUD Real Chrome test passed before deletion, proving current behavior did not depend on the old broad-refresh generation.

R20m physically removed that unreachable block and kept the stable 414/423/429 owners. No new runtime or refresh path was introduced.

```text
baseline:                  243bcb1b17074848d91c2c9c64d47dbed54e5e9b
baseline + migration run: 34724242632
product:                   71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e
cleanup / acceptance:      40a87bf70402dccfc0387950b6856a561ce1ebe1
Frontend Runtime:          34724354775
full Real Chrome:          33/33 PASS
Action Fencing:            34724354790 PASS
formal VERSION.txt:        42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

Permanent source contract: `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`; permanent behavior contract remains `tests/browser/algorithm-list-performance.spec.mjs`. One-shot migration helper/workflow are physically deleted. **R20m CLOSED; global R20 reload/request zero-point remains IN PROGRESS.**

## 2.0b R20l — source-import terminal scoped refresh

Source-order/liveness audit proved that `refreshSourceImportTasksV36()` remains the final live owner for address/server source-import task polling. On terminal completion it still invoked final `loadRelated()`, causing a real broad GET fan-out. The dedicated Real Chrome baseline intercepted the terminal source-import jobs response and proved those broad project/dataset/image/algorithm/publish/test-model/config requests before migration.

The terminal owner now refreshes only label schema plus the current paged material domain when the user is still on 数据集. Active polling stays at 1800ms and the source-import task API/UI is unchanged.

```text
baseline + migration run: 34723694735
product:                  f260127d2d41281bc1d996a172e7d4290536f24c
permanent Chrome guard:   b17bd0c33bfb99e5557fc245a89a6c4444a8257e
cleanup / acceptance:     f8356bcf5ec1ea128fb38db2820df38146b48cfd
Frontend Runtime:         34723808299
full Real Chrome:         33/33 PASS
Action Fencing:           34723808298 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

Permanent contracts: `tests/frontend/source-import-completion-scope.test.mjs` and `tests/browser/source-import-completion-scope.spec.mjs`; the Chrome contract is part of the permanent Frontend Runtime workflow. One-shot migration helper/workflow are physically deleted. **R20l CLOSED; global R20 reload/request zero-point stays IN PROGRESS.**

## 2.1 R20g — import completion scoped refresh

R20g 将最终 ZIP 导入完成与 server-storage 导入确认从 broad `loadRelated()/loadAll()` 收窄到真实受影响域：需要时刷新标签；只有当前处于数据集页面时刷新分页素材。永久测试锁定最终 owner 不再调用 broad refresh。一次性 migration helper/workflow 在验收后已物理删除。

```text
product:          a67778fd9b60384dbfffa2156e99670d244dadc9
validation:       a2f4cb40abb6d70ad4faf89bde60c1ee39e4a179
validation run:   34693503185
Real Chrome:      30/30 PASS
cleanup:          6337f1a0379c7e60fbbc459668090504c0b6095b
cleanup run:      34695825386
cleanup Chrome:   30/30 PASS
```

R20 仍未整体 CLOSED；下一批继续做 global reload/request zero-point 与 proven-dead runtime shell 清理。

## 2.2 R20h — legacy algorithm CRUD / shadowed renderer retirement

R20h 证明并物理退休最早算法 CRUD owner、v30 算法 renderer wrapper、v39 `viewAlgorithm` wrapper 与 v42.2 已被最终路由遮蔽的算法页面 generation。最终算法列表仍由 `renderAlgorithms423` 负责；创建/编辑/删除由 414/423 稳定 action 直接使用服务端 authoritative result 更新 `state.algorithms`，不再触发 broad reload。

保留边界：

```text
function renderAlgorithms() → 仅作为 bounded compatibility delegate 到 renderAlgorithms423
后代 window.showReport owner → 仍被 viewAlgorithm423/versionRows423 使用，未误删
```

永久合同：

```text
tests/frontend/legacy-algorithm-crud-owner.test.mjs
tests/browser/algorithm-list-performance.spec.mjs
```

```text
product:        d58e690ffcc1523f213a65cfc0a57380ffdc571e
focused run:    34696508446
validation:     210a9ad1f6271a8a8986db3f223f4813a6cce288
validation run: 34696729028
frontend:       PASS
Real Chrome:    31/31 PASS
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

一次性 migration helper/workflow 已物理删除。R20 尚未整体 CLOSED；下一批继续对 dataset/job/publish 等 mutation 做 liveness + request zero-point。

## 2.3 R20i — legacy dataset-group owner retirement

R20i 证明最终数据集路由已经直接执行 `renderDatasets424()`，不会再回落到两代旧 dataset-group renderer。旧分组 CRUD 与后续 `oldSelectDataset` persistence wrapper 因此是不可达 compatibility debt，已物理退休。为兼容仍会 eager-reference `renderDatasets` symbol 的旧 global render map，只保留一个 bounded delegate：

```text
function renderDatasets() → window.renderDatasets424?.()
final 数据集 route → renderDatasets424()
```

永久 guard 禁止旧 `select/new/save/edit/delete dataset` owner、`oldSelectDataset`、`currentDataset()` 回归。

```text
product:          feeb98f441bb1fe5d0f8f409a1509c66606e59ef
focused run:      34698742036
validation:       11131ca30c17809e016807aa6c75b0bf203fa6f8
validation run:   34698850495
Real Chrome:      31/31 PASS
cleanup:          a7116811adb26ebe5f0f9e621bf23df1dd1f605f
cleanup run:      34698983278
cleanup Chrome:   31/31 PASS
app.js cache:                42.25.95
```

R20 仍未整体 CLOSED。下一批先完成 legacy dataset action generation 的 liveness/source-order 证明，再处理 proven-dead action shell；`stopJob/deleteJob` 已确认仍被当前训练页调用，属于 live mutation，后续必须以 scoped jobs refresh/local patch 方式迁移，不能直接删除。

## 2.4 R20j — zero-reference legacy dataset actions

R20j 对旧 dataset action generation 做了全局 assignment/reference proof。以下函数在当前 `static/app.js` 中均只有一个 assignment、且调用形式为 0，因此属于 proven-dead action shell，并已物理删除：

```text
window.uploadImages
window.autoSplit
window.buildYolo
window.checkDatasetQuality
window.setImageSplit
```

边界刻意保留：`window.doImportData` 只有一个 owner，但最终 v36 `importData()` 仍真实调用它，因此它不是 dead code。其 v18 XHR 成功路径中的 `await reload()` 留给 R20k 做 scoped refresh。

```text
product:            e6398f7d8ae665079c82d64217c434af4a73073c
focused run:        34699354229
validation:         693a2fa2c3d39378782ac2270a95924eff5ca5ec
validation run:     34699442423
Real Chrome:        31/31 PASS
cleanup:            9c7a3497b9acf69364d83e5cf778ec4139bdbc69
cleanup run:        34699599796
cleanup Chrome:     31/31 PASS
app.js cache:                42.25.95
```

永久 guard：`tests/frontend/legacy-dataset-action-shell.test.mjs`。一次性 R20j migration helper/workflow 已物理删除。R20 尚未整体 CLOSED；下一批 R20k 先迁 live `doImportData`，之后再处理 `stopJob/deleteJob`。

## 2.5 R20k — live v18 import completion scoped refresh

R20k 保留最终 v36 `importData()` → 唯一 `doImportData()` → v18 XHR 的真实 owner，只迁移成功后的刷新边界：`await reload()` 已替换为 `refreshLabels414(false)`，且仅在用户仍处于数据集页时调用 `reloadMaterialPage61()`。导入进度、结果卡、警告和 toast 语义保持不变。

永久 Real Chrome 合同真实走 file input + v18 POST mock，并禁止 projects/datasets/images/jobs/algorithms/publish/test_models/bootstrap 等 broad fan-out。

```text
product:            1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb
focused run:        34700022284
focused frontend:   211/211 PASS
focused Chrome:     2/2 PASS
validation:         60775456f3d4c8a441ba58ce65106af114aeebb2
validation run:     34700127243
validation Chrome:  32/32 PASS
cleanup:            f51d44c089b6342398c14bd38c8669747adad48b
cleanup run:        34700252041
cleanup Chrome:     32/32 PASS
app.js cache:                42.25.95
```

永久合同：`tests/frontend/v18-import-completion-scope.test.mjs` + `tests/browser/material-pagination-performance.spec.mjs`。一次性 helper/workflow 已物理删除。

R20 尚未整体 CLOSED；根据用户授权，先切换到 P0 Resource Discovery SQLite / FD lifecycle。代码级并发与 deterministic close 可在 CI 闭环，但 30–60 分钟生产 soak 未执行前仍标记 NOT VERIFIED。

## 2.6 Resource Discovery SQLite / FD lifecycle — code-level closure

本批只关闭 Resource Discovery 的 SQLite 初始化与连接生命周期，不扩张为整个 Resource Lifecycle Zero-Point。

旧代码 baseline 在真正迁移前得到可复现红线：

```text
run: 34700801232
4 tests collected
reopen cache schema/WAL bootstrap      FAILED（重复 executescript）
_ModelManifest explicit close          FAILED（opened 6 / closed 0）
concurrent init + generation allocation PASS
Linux SQLite FD trend                   PASS
baseline total                          2 failed / 2 passed
```

迁移后：

```text
DiscoveryCache schema/WAL → FileLock single-owner + PRAGMA user_version gate
ordinary connection       → 不再执行 PRAGMA journal_mode=WAL
transaction               → closing(connection) + explicit commit/rollback
_ModelManifest            → closing(connection/cursor)
focused regression        → 6/6 PASS
```

永久验收：

```text
product:                 8ba4e10db5958204aca3d87779711d8e95f5d83b
permanent guard commit:  5b66ee03e5aaa3af3a2f18a9092f12e303f69937
permanent workflow:      .github/workflows/resource-discovery-sqlite-stability.yml
permanent run:           34700900542
Ubuntu:                  PASS（含 /proc SQLite FD trend）
Windows:                 PASS（Linux-only FD test 按合同 skip）
cleanup:                 c6ac70b670a6297ccba065854779c10b8ca47cf3
cleanup Frontend run:    34700984963
cleanup Real Chrome:     32/32 PASS
formal VERSION.txt:      42.24.0 unchanged
```

永久测试：`tests/unit/test_resource_discovery_sqlite_lifecycle.py`。一次性 migration helper/workflow 已物理删除。

**仍 OPEN / NOT VERIFIED：** 30–60 分钟真实生产 soak；file/ZIP handle、subprocess pipe、socket、tempfile、directory iterator、mmap、Torch/GPU worker process、worker lock/stale PID、thread/executor 等其他资源类。故整个 Resource Lifecycle Zero-Point 仍不得标 CLOSED。

按用户授权，下一主线切到 **Navigation Action Fencing**；生产 soak 单独列为后续验收，不阻塞当前代码主线。

## 3. Canonical owners

### Training

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

### Navigation

```text
window.setPage = NavigationStability.stableSetPage
  → normalizeNavigationPage()
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady()
  → beforeInvokeNavigation()
  → performNavigation(page)
       state.page = page
       render()
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistUiState()
```

`static/app.js` must contain zero classic `window.setPage=` owners.

### Visible version / build metadata — R9 final split

```text
formal VERSION.txt                    42.24.0
static/index.html initial badge       v42.24.0
top visible badge owner               top412 / V412 = 42.24.0
sidebar visible footer owner          nav426 / V426 = 42.24.0
internal UI build metadata            UI_BUILD_VERSION = 42.25.0-dev
internal metadata sink                document.documentElement.dataset.uiBuild
```

`UI_BUILD_VERSION` is not a user-visible version owner.

### File-input beautification — R10/R11 final owner

```text
page render
→ final render owner
→ PostRenderNormalizationRuntime.apply(#view)
→ cleanup(#view)
   → window.beautifyFileInputs426?.(root)

modal content write
→ ModalContentRuntime.replace(root, html)
→ if root.id === 'modalBody': PostRenderNormalizationRuntime.apply(root)
→ cleanup(root)
   → window.beautifyFileInputs426?.(root)
```

`render426base` 与 `modal426` 均已物理退休。文件选择器美化不再依赖两个历史 RAF compatibility wrapper。

## 4. Current live render / post-render owners

Confirmed live; do not remove as whole wrappers without a new semantic migration proof:

```text
oldRender412      → 算法列表 / 数据集
renderBase428     → 训练任务
renderTraining423 → 当前训练页 + direct PollRegistry activation
renderBase427     → 自动标注及清洗
renderBase424     → 质量中心 / 视频切帧
oldRenderV39      → deployment conversion/artifact/resource/plugin/component
render414Base     → 标签管理
finalRender       → 素材存储配置 + final page normalization dispatch
PostRenderNormalizationRuntime.apply / cleanup(root)
                  → page normalization + table/file-input cleanup
ModalContentRuntime.replace(root, html)
                  → explicit modal/preview/review content + #modalBody normalization
base modal()       → modal first-editable-field autofocus
completeZipImportReview412 → explicit successful ZIP completion review
refreshSummary61           → paged 数据集-only material summary requests
```

Remaining audit candidates:

```text
older base/global render generations still reachable through delegates
global reload / loadAll / loadRelated request ownership
```

`baseRender417`、`render426base`、`modal426` 均已退休，不再是 live audit candidate。

## 5. Current cache/build facts

```text
app.js cache                     42.25.82
main.mjs cache                   42.25.87
visible formal version           42.24.0
internal UI build metadata       42.25.0-dev
navigation-stability.js          422511
ui-state.js                      422500
poll-registry.js                 422511
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
material-pagination-runtime.js   422206
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

Cache-busting 仍未统一；这与 visible version ownership 是不同技术债。

## 6. 永久合同

Frontend：

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/version-marker-owner.test.mjs
tests/frontend/file-input-beautification-owner.test.mjs
tests/frontend/post-render-normalization-owner.test.mjs
tests/frontend/startup-render-owner.test.mjs
tests/frontend/lifecycle-event-ownership.test.mjs
tests/frontend/algorithm-version-refresh-owner.test.mjs
tests/frontend/algorithm-version-publish-owner.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/frontend/paddle-resource-refresh-owner.test.mjs
tests/frontend/model-config-prompt-refresh-owner.test.mjs
tests/frontend/model-config-save-refresh-owner.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
```

R9 永久要求：

- `baseRender417` 不得回归；
- classic delayed `versionBadge` startup writers 不得回归；
- `main.mjs` 不得通过 `UI_BUILD_VERSION` 写 `#versionBadge` 或 `.nav-footer b`；
- `applyBuildVersion` 不得回归；
- 初始可见版本必须是 `v42.24.0`；
- internal UI build metadata 可保留 `42.25.0-dev`，但只能作为内部 metadata。

R10/R11 永久要求：

- `render426base` 不得回归；
- `modal426` 不得回归；
- 两个历史 `requestAnimationFrame(...beautifyFileInputs426...)` callback 不得回归；
- `cleanup(root)` 必须继续调用 `window.beautifyFileInputs426?.(root)`；
- `#view` cleanup observer 已在 R17 退休，不得回归；页面 cleanup 必须保持 final-render-owned；
- `#modalBody` normalization observer 已在 R19 退休，不得回归；modal replacement 必须由 `ModalContentRuntime` 显式拥有；
- `测试发布` 的 `#predFile` 必须继续获得 `native-file426 + filepicker426` 行为；
- 动态 modal 中普通 file input 必须继续获得同等 filepicker 行为。

Browser：

Real Chrome 当前锁定 stale request fencing、managed polling、sidebar、页面持久化、legacy alias、AutoLabel polling、素材存储、算法/训练/素材性能路径、formal version 稳定性，以及 page/modal 文件选择器美化行为。

R12 永久要求：

- `enhancePageV37` 不得回归；
- `requestAnimationFrame(enhancePageV37)` 不得回归；
- `cleanup(root)` 必须继续统一处理 `table.table → .table-wrap`；
- `cleanup(root)` 必须继续移除“使用建议”等历史提示 panel；
- `baseRenderV37` 已在 R13 退休，不得回归；
- later `V42` render 继续承担 render-path formal `state.versionInfo.version=42.24.0`；
- `baseModalV37` 已在 R14 退休；首个可编辑字段 autofocus 由 base `modal()` 唯一承担；
- v35/v36/V37 的 80/100/120ms startup render/version timer 已在 R15 退休；
- startup dispatch 必须继续由 `queueMicrotask(()=>{if(window.__clInit)window.__clInit()})` 与 final `__clInit` 路径承担；
- bounded `setTimeout(()=>{renderTop();cleanup(document);},100)` 已在 R18 退休，不得回归；startup/page normalization 均由 readiness-aware final render owner 承担。

当前验收：run `34690924552`，frontend PASS，Real Chrome **28/28 passed**。

### R16 — event-owned ZIP completion + page-scoped material summary

R16 converted two asynchronous lifecycle guesses into explicit/scoped owners. The former body-wide ZIP review `MutationObserver` could fire after `pollImport411()` exposed `stage=导入完成` but before the final completion `resultHtml` write, so its persisted review action could be overwritten even though the DOM button and auto-open had already appeared. ZIP review is now invoked explicitly after the final successful completion state is written.

The second failure source was `refreshSummary61()`: its 250/1200ms startup timers only checked stale `transport.mode==='paged'`. Because final navigation no longer uses the early material-aware `setPage` wrapper, those timers could issue `/materials` after navigation to 训练任务. `refreshSummary61()` is now strictly gated by the live paged 数据集 page both before and after its requests.

```text
baseline:        540de6aef4ddbf82a6cf36994a31a73937abca73
baseline run:    34668429941 → 17/19
                 ZIP persisted review false
                 training-task unexpected /materials request
product:         12df27e2af9155e3a1b9f745e46605396e321815
focused run:     34668639496
                 ZIP completion PASS
                 training refresh isolation 5/5 PASS
validation:      540c0944f45030ea198af2be153c1505f71e62f0
full run:        34668702371
frontend:        PASS
Real Chrome:     19/19 PASS
```

Permanent proof: `tests/frontend/lifecycle-event-ownership.test.mjs` plus the browser contract `ZIP import completion surfaces review action and auto-opens review`.

### R17 — final page normalization ownership

R17 removed the remaining page-side triple ownership (`baseRender` wrapper + page RAF cleanup + `#view` MutationObserver). Source-order proof showed the storage wrapper is the final `render` assignment in `static/app.js`, so page normalization now runs exactly once after the final render path through the named `PostRenderNormalizationRuntime`. Modal normalization remains independently owned by the `#modalBody` observer and was intentionally not changed in this batch.

```text
product:         4fc5d90a15ef2fc2dc22aa00f39967deba6f53f8
validation:      c3301d065fa820539873a4fa2f739992ef63f3d2
guard alignment: f5b8ff8789de0f51d2a03bcabe126191005ba24c
full run:        34669152742
frontend:        PASS (179/179)
Real Chrome:     19/19 PASS
```

The first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.

### R18 — bounded startup cleanup timer retirement

R18 retired the remaining readiness-bypassing `setTimeout(()=>{renderTop();cleanup(document);},100)` wakeup. Final startup already waits for the v53 snapshot/current-page refresh and then calls the final `render()`, while R17 made that final render the sole page-normalization dispatch. The modal observer was deliberately left untouched because post-open base-modal body mutations still depend on normalization.

```text
product:    1572fdf4fad6e0fe8d10b5253a236722e85b3495
validation: 954e9dba9c891ecd5c7f21144cf00d8664c11620
run:        34670319479
frontend:   PASS
Real Chrome: 19/19 PASS
```


### R19 — explicit modal content ownership

R19 retired the last active DOM normalization observer. A permanent Real Chrome baseline first locked a real post-open base-modal refresh path (后台导入任务 → 刷新). Modal content writes now go through `ModalContentRuntime.replace(root, html)`. When `root.id === 'modalBody'`, that owner synchronously invokes `PostRenderNormalizationRuntime.apply(root)`; preview/review rewrites also route through the same content replacement owner. `static/app.js` now contains zero active `MutationObserver` constructions.

```text
baseline:   6f5fac4313d23083c6bbe9e2a3b8a5284cd49583
product:    1bb210fbb10a7bee9f5b875d0dd6016187c1ef72
validation: f60d00096a0929a63d0370494ef1f1d489f54ca3
run:        34670989473
frontend:   PASS
Real Chrome: 20/20 PASS
```


### R20a — algorithm version deletion scoped refresh

R20 started the global `reload() → loadAll() → loadRelated()` request-debt migration with one proven-live mutation path. The algorithm version delete modal behavior was locked first. The final `delVersion` owner now performs the DELETE and delegates refresh to `AlgorithmListRuntime.refresh({render:true})`, which owns only algorithms + jobs. The browser contract permanently forbids the datasets/images/labels/training-environment/bootstrap request fan-out on this path while allowing unrelated background owners such as the import-job poll to run independently.

```text
baseline:   55f21733121d1280be66548ef4bb13c1c3810737
product:    22c552d27928375dd51081eb152dc25b1554ec18
validation: 103d630b24bd1aad77190149291c4c9f25e8ab75
run:        34677761599
frontend:   PASS
Real Chrome: 21/21 PASS
app.js:     42.25.77
main.mjs:   42.25.82
```

This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

### R20b — model-version publish authoritative state update

The final live 测试发布 `saveAssign` owner no longer calls global `reload()` after a successful version publish. The API response's `version` is authoritative: it is inserted into the selected algorithm state, the matching pending model is removed, transient assignment state is cleared, and the current page is rendered locally. The publish action is permanently guarded as one POST with no reload GET fan-out.

```text
initial baseline:   b41340d4ee292f7e8e268f4bd59206efe072d690 / 34678815343 → 21/22
                    test assertion mismatch only: disabled input value was checked as modal text
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / focused 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
focused migration:  34679011468 PASS
validation:         d18044d3d98231affc7488974e04623dab6d2b10
full run:           34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
app.js:             42.25.78
main.mjs:            42.25.83
```

R20 remains **IN PROGRESS** for other live mutation owners.

### R20c — training-server scoped target refresh

训练资源页的最终 `saveServer` owner 已证明 live。R20c 前，服务器保存成功后调用全局 `reload()`；当前 `reload()` 已重绑到 `refreshCurrentPage413`，因此该动作会重新请求 bootstrap snapshot，再加载训练资源页 extras。后端 `/api/train_servers` POST 只返回 server item，而规范化 `state.targets` 必须来自 `/api/training_options`，所以不能做不可靠的纯本地拼装。

R20c 将该 mutation 收敛为：POST `/api/train_servers` → GET `/api/training_options?project_id=...` → 更新 `state.targets` → 本地 render。永久 Chrome 合同要求该动作 bootstrap snapshot 请求为 0。

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14
full run:           34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
app.js:             42.25.79
main.mjs:            42.25.84
```

R20 remains **IN PROGRESS** for other proven-live mutation owners.

### R20d — Paddle environment activation scoped refresh

最终资源运行时中的 `detectPaddle` 与 `quickPaddleDetect` 已证明 live。R20d 前，两条成功路径都会调用当前 `loadAll()`，从而重新请求 bootstrap snapshot。由于规范化训练资源仍必须由 `/api/training_options` 构造，R20d 新增 `refreshPaddleTrainingTargets20d()`，两条激活路径保留各自必要 POST，仅以 training_options GET 更新 `state.targets` 并本地 render；永久 Chrome 合同要求 bootstrap=0。

```text
baseline:                53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration run:     34681841986 STOPPED before product commit
                         generated unit JS syntax error caused by helper string escaping
helper-generator fix:    e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:                 d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:       34681905173 PASS
validation:              a21846c33d79612f9ab4a47e2a69195da29caa3b
full run:                34681966242
frontend:                PASS
Real Chrome:             24/24 PASS
app.js:                  42.25.80
main.mjs:                42.25.85
```

首轮失败发生在 product commit 之前，没有接受或落库产品代码。R20 下一步应做剩余全量刷新 owner 的 zero-point 审计：将 live mutation、用户显式“完整刷新”与 shadowed/dead code 分开证明。

## 7. Recent render/lifecycle acceptance history

```text
alias restore-boundary fix
  e35a29b0... / 34656747269 PASS

oldRender429 retirement
  0455eeef... / 34659041402 PASS

previousRender61 retirement
  69732d9e... / 34659543452 PASS

render423Base retirement
  58ece59e... / 34659775870 PASS

renderBase428 algorithm branch retirement
  6be679b6... / 34660269685 PASS

legacy 自动标注 render route retirement
  66339fc0... / 34663089996
  Chrome 14/14 PASS

renderBase424 shadowed route retirement
  2d9bc0b3... / 34663389819
  Chrome 14/14 PASS

legacy AutoLabel424 self-refresh timer retirement
  70b6f755... / 34663768606
  Chrome 14/14 PASS

R9 version-marker final validation
  36fd25c48a2251d1b4a85583921c00dd98bf33fb / 34664755130
  frontend PASS / Real Chrome 15/15 PASS

R10 file-input page-owner behavior baseline
  6b67497ae43a32edf343fc7dec49f7b3824c1088
  focused Chrome PASS

R10 product
  b9d25955c185aaabb4108f3d37cfecd9f876390a

R10 final validation
  0dacf581da4acb52312f75eb7e85e6b334e060db / 34665470320
  frontend PASS / Real Chrome 16/16 PASS

R11 modal file-input behavior baseline
  d2aa614870a52864e991502c2218134943afb14f
  focused Chrome PASS

R11 product
  8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1

R11 final validation
  9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1 / 34665890699
  frontend PASS / Real Chrome 17/17 PASS

R12 post-render normalization behavior baseline
  6ae19dc79abbf690371a71162c97a2df6322518b
  focused Chrome PASS

R12 product
  202a5a82b0cb4629423ee0c6812f649031234daa

R12 final validation
  60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29 / 34666673017
  frontend PASS / Real Chrome 18/18 PASS

R13 product
  928d2387d46a0472bd202bd4df84af8d1573b6c2

R13 final validation
  43e31c7e683fbda4b9c36a3d35188262b6a9ff1b / 34666985800
  frontend PASS / Real Chrome 18/18 PASS

R14 baseModalV37 retirement
  product 6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829
  validation 8593516eb796f10fb43cea748bcc42b479e0a02e / 34667341153
  first full pass 17/18 due to training-task /materials race; rerun 18/18 PASS
  focused race diagnostic 10/10 PASS with only GET /jobs on first refresh

R15 startup render timer retirement
  product 280a31bf365b1a6646a57213dfa2dff97e10e0b5
  focused startup readiness PASS + training performance 5/5 PASS
  validation b6edea36296ab9548037457a124b4369776f6f5e / 34667776611
  frontend PASS / Real Chrome 18/18 PASS
```

所有对应一次性 baseline/migration helper/workflow 均已在验收后物理删除；永久 tests 保留。

## 8. 下一批：global reload / request ownership audit

R17–R19 已把 active normalization observers 清零。R20a–R20d 依次关闭算法版本删除、模型发布、训练服务器接入和 Paddle 激活的宽刷新；R20e 关闭模型配置删除与提示词 mutation 宽刷新并修复 stale UI；R20f 又关闭最终 M4 模型配置保存/编辑的 `loadRelated()` fan-out。R20 下一步做 final-owner zero-point 审计，只将 proven-live mutation 计为剩余请求债；用户显式完整刷新、shadowed/dead code，以及 capture/final-activation 恢复链必须分开处理。

`oldRenderV39` 与 `render414Base` 已确认 live，不得因为版本号旧就直接删。

执行规则：

1. 先证明 exact source order、capture/reference 和 page/modal coverage；
2. 对 live 语义先补 unit/Chrome；
3. 只删除 fully shadowed generation/branch，或先迁移 live 语义再删除；
4. 语义迁移必须先有行为合同；
5. 每刀 full frontend + Real Chrome；
6. 不允许通过放宽测试换取删除成功。

## 9. 后续顺序

```text
A. continue R20 global reload / loadAll / loadRelated mutation-domain migration
B. proven dead app.js/runtime-shell cleanup
C. cache-busting unification
D. MutationObserver/timer/fetch/render/setPage zero-point scan
E. semantic naming + deterministic test cleanup
F. technical-debt zero-point scan
G. A800 RC
```

## 10. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。

### R20e — 模型配置 / 提示词 mutation local ownership

R20e 的 source-order audit 证明三条 mutation 仍为最终可达 owner：删除模型配置、保存/编辑提示词模板、删除提示词模板。旧实现均在 mutation 成功后执行 `loadAll()`。其中提示词路径存在真实状态同步错误：当前模型配置页的 loadAll extras 会重载 `modelConfigs`，但不会重载 `promptTemplates`，因此 POST/DELETE 成功后页面仍显示旧提示词状态。

```text
baseline:             afa2bfcb474cc9970129723af5589ab74a26eca7
baseline run:         34683803977 → 1/3 PASS
                       prompt save：成功后新模板未出现在页面
                       prompt delete：成功后旧模板仍留在页面
first migration run:  34683969019 → unit 3/4；仅 wiring guard 转义错误；未提交产品
guard fix:            becabf102d10520db52fdac9af1d5238357aa3f3
focused run:          34684037005 → unit 4/4 + Chrome 3/3 PASS
product:              febece523b462692cc857431cb901fc5a863d091
validation:           89327ded9da924753f5f900fc3b79e6df353927f
full run:             34684119911
frontend:             PASS
Real Chrome:          27/27 PASS
```

最终 owner：

```text
deleteModelConfigV35     → DELETE → state.modelConfigs local filter → render
savePromptTemplateV35    → POST/PUT authoritative item → state.promptTemplates local upsert → render
deletePromptTemplateV35  → DELETE → state.promptTemplates local filter → render
```

三条永久 Chrome 合同均要求 action 期间 bootstrap=0、model-config GET=0、prompt-template GET=0。R20 mutation refresh debt 继续 **IN PROGRESS**，下一批必须做剩余 `reload/loadAll/loadRelated` 的 final-owner zero-point audit；历史 shadowed code 和用户显式“完整刷新”按钮不得误计为 mutation debt。

附带诊断：full run 中 resource-discovery cache 初始化曾记录一次 `sqlite3.OperationalError: database is locked`，但 27/27 Chrome 全部通过。该问题单独列入 resource-discovery 并发技术债，不影响 R20e 验收结论。


### R20f — 最终 M4 模型配置保存/编辑 local ownership

R20f 最初按文本 source order 锁定 `saveModelConfig427`，但临时 Real Chrome runtime diagnostic 证明可见 modal 实际由 M4 capture/final-activation 机制恢复：M4 先保存 `window.__m4OpenModelConfig`，后续 427 compatibility 虽然文本上重写了 `openModelConfigModalV35`，文件尾的 M4 final activation 又恢复 captured owner。因此真正 live 的保存动作是 `saveVisionModelM4`。

旧 live owner 在 POST/PUT 成功后调用 `loadRelated()`，会继续请求 project、datasets、materials、labels、algorithms、pending/test models、model configs、prompt templates 等一整套相关数据。最终 owner 改为直接接收后端 sanitized authoritative item，按 `id` upsert 到 `state.modelConfigs` 并本地 render。

```text
baseline:             dddcd3f1eecf27c5b7447a16939e53473ff1d745
readiness alignment:  da3f3cee7565b75f0a2de926dfdbdb42f7b30ab9
runtime diagnostic:   34690682894
product:              c9b7ab44192d38c37753643ee790fc2e089c8598
validation:           94dbebb43d83b1d522ea4e3f6522154417f3e985
full run:             34690924552
frontend:             PASS
Real Chrome:          28/28 PASS
app.js:               42.25.82
main.mjs:             42.25.87
formal VERSION.txt:   42.24.0
```

永久 owner guard：`tests/frontend/model-config-save-refresh-owner.test.mjs`。永久 Chrome 合同要求保存后立即可见且 mutation-owned broad GET fan-out 为零。R20f 还新增一条审计规则：**不能仅以“最后一个文本定义”认定最终 owner；必须同时检查 capture alias、restore 和 final activation。**

R20/global reload debt 仍为 **IN PROGRESS**，下一步进入剩余 `reload/loadAll/loadRelated/loadCore412` 的 final-owner zero-point audit。


<!-- V42_25_ZIP_P1_ANNOTATION_SQLITE_ATOMICITY_20260913 -->
## 2026-09-13 — ZIP Processing P1 + Annotation SQLite Dataset Delete Atomicity

### ZIP Processing P1 — CLOSED

- 目标：量化并移除 1,000/10,000 图 ZIP 实际处理阶段的逐图放大，不改变导入语义。
- 同一 GitHub Actions runner、1,000 张真实 JPEG + YOLO txt 的前后基准（run `34733781003`, job `103661376150`）：
  - `get_project`: `2002 -> 1`
  - `material_patch`: `2000 -> 0`
  - `MaterialRepository` 初始化：`4002 -> 2002`
  - annotation 初始化 / upsert：保持 `2000`，本批未跨越 annotation 事务边界
  - wall time：`11.2115s -> 10.0417s`，同 runner 约 `1.116x`（约 11.6%）
  - 导入 1000 图、1000 框、最终 material/annotation 计数完全一致。
- 产品提交：`6fb34ebd07f5c6f460c58e3360825dbab49fea44` (`perf(import): remove per-image ZIP processing amplification`)。
- P1 明确只消除了重复 project `meta.json` 读取和 batch 内无效 material projection；没有用放宽断言换性能。

### Annotation SQLite Dataset Delete Atomicity — CLOSED

- 审计确认旧 dataset-delete journal 仍以 `annotations/{image_id}.json` 为删除/恢复对象，但当前标注真值已经是 `annotations.sqlite3`；成功删除数据集此前会留下 orphan SQLite annotation，异常恢复也无法覆盖当前 GT。
- 新架构不恢复 per-image JSON shadow，也不把 10k 完整 boxes 塞进 JSON journal；`AnnotationRepository` 增加 SQLite 内部 durable delete backup：`annotation_delete_backup`。
- 删除协议：`prepare_delete(token, ids)` 持久备份 -> 物理文件 staging -> material finalize -> annotation `finalize_delete(token)`；失败/恢复使用 `restore_delete(token)`，成功清理使用 `complete_delete(token)`。
- `finalize_delete` 只删除 `content_digest` 仍与备份一致的 annotation；并发标注变化时拒绝 stale delete。`restore_delete` 使用不覆盖已有新行的恢复语义。
- v50 buffered image batch 被拒绝时，同时清理真实 SQLite annotation，避免 orphan GT。
- Windows 文件锁回归改为锁真实上传图片文件，仍要求 409 + 数据集/material/annotation 完整保留；不再依赖不存在的 per-image JSON。
- 迁移 run `34734781793`：旧代码新合同 RED；两个历史 JSON-shaped guards RED；迁移后原子性组 `14 passed`，annotation/ZIP 回归 `7 passed`，正式 `VERSION.txt=42.24.0`。
- 产品提交：`e79eaa60ac18cbd5b78ad6df7bdb109643127871` (`fix(annotations): make dataset deletion atomic with SQLite truth`)。
- 永久化/一次性脚手架清理：`da676db7994c69b06b0084e000c5812d1206f87d`；长期 workflow：`Material Annotation Atomicity`。
- cleaned HEAD 长期验收：
  - Material Annotation Atomicity `34734901591`: PASS
  - Navigation Action Fencing `34734901538`: PASS
  - Frontend Runtime Stabilization `34734901543`: frontend PASS；Real Chrome `33/33 passed (1.0m)`
- 正式 `VERSION.txt` 仍为 `42.24.0`；未 merge main、未 tag、未 release。

### 下一主线

- ZIP Processing P2：先量化剩余 annotation 热点。P1 后 1,000 张 YOLO 仍有 `2000` 次 AnnotationRepository 初始化/upsert（初始 `unannotated` + 最终真实 annotation 各一次）。
- P2 必须先建立事务/失败回滚/负样本语义基线，再决定是否做单图双写折叠、连接复用或批量 annotation commit；禁止为了速度破坏标注真值和 dataset-delete 原子性。

<!-- ZIP-P2AB-2026-09-13 -->
## 2026-09-13 — ZIP Processing P2a / P2b verified checkpoint

状态：**P2a CLOSED；P2b（YOLO）CLOSED。COCO/VOC 同类双写仍 OPEN，后续按 P2c 单独建基线，不把 P2b 泛化为全格式完成。**

### P2a — annotation connection amplification

- 成功迁移 run：`34735300276`，job `103665544357`。
- 产品提交：`6e03e5467e4797b6b935f693953d20c16276c89d` — `perf(import): reduce annotation connection amplification`。
- 永久化 checkpoint：`cb0ff301c034813151703b320e593f8e54875cdb`。
- 1000 张 YOLO 同路径：annotation SQLite connections `6000 -> 2001`；follow-up `get()` `2000 -> 0`；`AnnotationRepository` 初始化 `2000 -> 1`；wall `9.4311s -> 7.6136s`，约 `1.239x`。
- annotation upsert 数量仍为 `2000`，因此 P2a 明确没有通过推迟/删除 durable annotation write 来换性能。

### P2b — YOLO final annotation single durable write

- 热点 profiler run：`34737776295`，job `103672131158`。1000 张下 `annotation_upsert_many` 是主要热点；图片解码与 SHA256 不是主因。
- RED + 迁移 + 同 runner 前后 benchmark run：`34737932595`，job `103672530091`。
- 旧代码基线：P2b 新合同 `3 failed, 1 passed`；失败准确覆盖 `annotation_builder` 不存在与 YOLO `40 != 20` 双写。
- 产品提交：`2be7dd8d1dc7d275fe71f8e0c17604febdf6368c` — `perf(import): write final YOLO annotation once`。
- 永久化/一次性脚手架清理：`d2cda6cab9b9c3b3427cb5f63c833c052f3a069e` — `test(import): permanentize ZIP Processing P2b`。
- 1000 张同 runner：`write_annotation 2000 -> 1000`；`annotation_upsert_many 2000 -> 1000`；annotation connections `2001 -> 1001`；wall `8.097123s -> 6.218626s`，`1.302x`，耗时下降约 `23.2%`。
- 结果不变：`report_imported_images=1000`、`report_boxes=1000`、`material_total=1000`、`material_boxes=1000`、`annotation_total=1000`、`annotation_annotated=1000`。
- 语义护栏：结构化 YOLO 在 `add_image_record()` 返回前直接持久化最终 GT；普通上传仍立即持久化 `unannotated`；空最终 GT 仍为 `confirmed_empty`；dataset-delete / v50 batch rollback 原子性合同继续保留。
- focused contracts：`10 passed`；annotation/material/import regressions：`17 passed`。

### Cleaned HEAD permanent gates

- Material Annotation Atomicity：run `34738062791` PASS，P2b 永久合同已纳入。
- Navigation Action Fencing：run `34738062810` PASS。
- Frontend Runtime Stabilization：run `34738062795` PASS；Real Chrome `33/33 passed`（53.5s）。
- 一次性 P2b profiler/migration workflow + helper 已物理删除；永久测试 `tests/api/test_zip_processing_p2b_single_final_annotation.py` 保留。
- 正式 `VERSION.txt` 仍严格为 `42.24.0`；未 merge `main`、未 tag、未 release。

### Next measured candidate

当前源码确认 `_v18_import_coco()` 与 `_v18_import_voc()` 仍存在 `add_image_record()` 后再 `write_annotation()` 的双 durable write 结构。下一批若继续，应作为 **P2c COCO/VOC structured-import single-write** 独立建立 RED、原子性合同与真实 benchmark；不要直接复用 YOLO 结论。

## ZIP Processing P2c — COCO/VOC structured-import single-write CLOSED

P2c is CLOSED with independent COCO and VOC RED → migration → GREEN → permanent-guard evidence; the YOLO P2b conclusion was not assumed to apply automatically.

```text
baseline + migration run: 34742240350
old COCO RED:             6 images -> 12 annotation upserts
old VOC RED:              6 images -> 12 annotation upserts
product:                  02ce1845d36dfa59e69e2a600d03a31b4da05d13
permanentization/cleanup: 233248847797023bc98bf0974490430139be3641

1000 COCO before:
  annotation writes/upserts: 2000
  annotation connections:    2001
  wall:                      13.599580s
  throughput:                73.532 images/s

1000 COCO after:
  annotation writes/upserts: 1000
  annotation connections:    1001
  wall:                      6.922337s
  throughput:                144.460 images/s
  wall speedup:              1.9646x

1000 VOC before:
  annotation writes/upserts: 2000
  annotation connections:    2001
  wall:                      10.693482s
  throughput:                93.515 images/s

1000 VOC after:
  annotation writes/upserts: 1000
  annotation connections:    1001
  wall:                      10.427986s
  throughput:                95.896 images/s
  wall speedup:              1.0255x
```

Both formats preserve `1000 material / 1000 annotation / 1000 boxes` truth. COCO and VOC now create the image record with the final annotation builder, so structured import no longer persists a temporary `unannotated` row and then rewrites the final GT. Plain image upload still retains immediate durable `unannotated` semantics; mixed structured imports retain `annotated` and `confirmed_empty` state/version contracts.

Permanent cleaned-head gates on `233248847797023bc98bf0974490430139be3641`:

```text
Material Annotation Atomicity: 34742373484 PASS
  atomicity/import contracts: 22 passed
  annotation/ZIP regressions:  7 passed

Navigation Action Fencing:     34742373492 PASS

Frontend Runtime Stabilization:34742373480 PASS
  Real Chrome:                 33/33 PASS (1.1m)
```

One-shot P2c migration workflow, migration helper and profiler were physically deleted after permanentization. The permanent P2c contract remains under `tests/api/test_zip_processing_p2c_structured_single_final_annotation.py` and `Material Annotation Atomicity`.

Post-P2c profiler decision: no new P2d is justified at this checkpoint. After single-write, COCO/VOC have one annotation upsert per image, one storage upload per image, one dataset-writable check per image, `get_project=1`, and one buffered material mutate; the remaining dominant timings are necessary per-image storage/annotation work rather than a newly demonstrated duplicate fan-out. Do not create P2d without new measured evidence.

**NEXT:** genuine 10,000-image processing-phase acceptance. Full 10k processing acceptance remains OPEN until wall time, throughput, resource/FD/SQLite behavior, progress cadence, rollback/recovery and final material/annotation/box truth are measured on a real annotated dataset.

Formal `VERSION.txt` remains `42.24.0`. No merge to `main`, no tag, no release. Technical-debt mainline remains PAUSED; A800 RC remains DEFERRED.

## 2026-09-13 — Durable task cancel→resume fencing CLOSED

A real control-plane race was proven: after `request_cancel()` had persisted `CANCEL_REQUESTED` + `stage=cancelling`, a stale/late explicit resume path could still call `TaskRepository.set_stage(..., "training")` because `set_stage()` accepted both `RUNNING` and `CANCEL_REQUESTED`. This violated monotonic durable task truth.

- RED contract: `a7d70f7b3106d32c62f01c45de89e8a4c3fb0807`; Release Regression `34748866897` failed only the new cancel→resume fencing contract while the rest of runtime contracts remained green.
- Product fix: `7cab9413185d0bfbc8052d978685ee7a2e8b46d0` — `set_stage()` now accepts only persisted `RUNNING`; `CANCEL_REQUESTED` remains `cancelling` until worker/lease convergence to a terminal state.
- Focused migration GREEN: `34749215356` PASS.
- Permanent guard/cleanup: `dfa9623ad75eab9d7e0945cd45051688492e87f8`; permanent repository race contract retained, real v48 durable training pause→resume→stop API regression added, late resume after stop must be rejected, temporary migration helper/workflow removed.
- Cleaned HEAD gates: Release Regression `34749914123` PASS; Frontend Runtime `34749914114` PASS including Real Chrome; Navigation Action Fencing `34749914211` PASS including Real Chrome stale-mutation contract.
- Release boundary unchanged: `VERSION.txt = 42.24.0`; no merge/tag/release; A800 RC remains deferred.

<!-- deployment-inference-process-fencing-closed-2026-09-13 -->
## Deployment test inference process fencing — CLOSED (2026-09-13)

Deployment-test subprocesses are now part of the durable execution fence instead of being invisible raw `subprocess.Popen` children. The runner is launched through the shared cross-platform process controller, binds exact `PID + create_time + command_hash` to the durable task, terminates the exact process tree on user cancellation or execution/lease fencing, and re-checks the current execution generation before result persistence.

Evidence:
- valid RED: GitHub Actions `34752083670` — real runner PID existed while durable `process_pid` was `None`;
- product: `97efe23ce2d587027150032f71906f03a75fcc51` (`fix(deployment): fence inference runner process`);
- focused GREEN: `34752147610`;
- permanentization: `fbbacad583a8f5ad50b27b1fcb6624b31255658e`;
- cleaned v42.25 Release Regression: `34752225736` PASS (runtime + training-data);
- cleaned Navigation Action Fencing: `34752225727` PASS including Real Chrome stale-mutation;
- cleaned Frontend Runtime Stabilization: `34752225677` PASS including Real Chrome runtime regressions;
- one-shot deployment process-fencing workflow removed during permanentization;
- formal `VERSION.txt` remains `42.24.0`; no merge/tag/release.

Genuine 10k processing acceptance and A800 RC remain deferred and are not closed by this batch.

<!-- RUNTIME-PROD-CLOSURES-2026-09-13-B -->
## 2026-09-13 — runtime productization closures: video publish + AI annotation cancellation

### Video frame publish cancellation / stale-execution fencing — CLOSED

- Valid RED run: `34752569787`. Old worker continued frame publication after durable cancellation and uploaded `3/3` frames after execution fencing/lease loss.
- Product: `8d267ae86a0a3030aa7faff8d4eccb9a1882b1d9` (`fix(video): fence frame publishing cancellation`). Every publish-side effect is guarded by cancellation/current-execution checks; late stale workers cannot continue material/result publication. Commit-phase progress now continues through the prior 90% plateau toward 97%/98%.
- Focused GREEN: `34752658173`.
- Permanentization: `22378473e077749ee5dc9de80ee9993daf28be64`; permanent contracts include `tests/unit/test_video_commit_fencing.py` plus the real video-worker integration path.
- Annotation integration was aligned with the already-authoritative SQLite truth (`annotations.sqlite3` / `AnnotationRepository`): no per-image JSON shadow was restored. Alignment/accepted HEAD: `cf81fd8b756d902cc6f9168f5f14d6357c806055`.
- Cleaned-head gates: Release `34752863299` PASS; Navigation Action Fencing `34752863247` PASS; Frontend Runtime `34752863225` PASS including Real Chrome.

### AI annotation in-flight cancellation side-effect fencing — CLOSED

- Valid RED run: `34753095270`. Cancellation during materialization still allowed one model inference call; cancellation during an in-flight model call still persisted the returned candidate.
- Product: `a1dabee5d867b19c9815c525e01793692db8b0a5` (`fix(annotation): fence cancellation around inference`). The worker re-proves cancellation/current execution immediately before provider inference and again after inference returns but before candidate/manifest writes. `InterruptedError` / lease-loss `PermissionError` remain control flow and are not converted into failed AI candidates.
- Focused GREEN: `34753193608`.
- Permanentization: `0d1c51f4caa25e1d653a32a5a790e792631126ca`.
- Existing candidate guards were migrated to current stronger truth in `3f6a63362a850049ebe6358d12eecf7d984ae79e`: failed provider generations do not inflate human `unreviewed` count, and unsafe task ids are rejected at `CandidateStore` construction by `ArtifactStore` before any candidate DB path is created.
- Cleaned-head gates on `3f6a63362a85...`: Release `34753389416` PASS; Navigation Action Fencing `34753389436` PASS including Real Chrome stale-mutation; Frontend Runtime `34753389399` PASS including full Real Chrome runtime regressions.

Release boundary remains unchanged: formal `VERSION.txt` is `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.

<!-- STORAGE-SCAN-CANCEL-CLOSURE-2026-09-13 -->
## 2026-09-13 — external storage scan cancellation fencing CLOSED

- Real bug: if Stop was requested while the final remote image read/decode was in flight, old `StorageImportHandler._scan_impl` had no later loop iteration to observe cancellation. It could open the same remote object again for missing SHA256, flush the candidate manifest, publish `scan/result.json`, and finish as `AWAITING_CONFIRMATION`.
- Permanent RED: `tests/unit/storage/test_import_scan_cancel_fencing.py`; valid RED run `34753661080` proved old code returned `AWAITING_CONFIRMATION` instead of `CANCELLED`.
- Product: `2ca557ed0bd72851948ad778163bf47d590b5a54` (`fix(storage): fence scan cancellation after remote reads`). Remote hashing now checks cancellation per chunk; inspection re-checks after image decode before follow-up I/O and after hashing; cancellation propagates rather than becoming INVALID/FAILED; `_scan_impl` refuses to append the in-flight cancelled object and returns `CANCELLED` while preserving only already-completed pending work.
- Migration run `34753741408` PASS: old-product RED, precise migration, syntax, focused GREEN, real storage-import worker/candidate/YOLO regressions, and formal version boundary all passed.
- Permanentization: `da54910048fd88f6cadeef34d130eba94af34303`; one-shot RED/migration workflows and helper were physically deleted. Release Regression permanently covers the cancellation contract, real storage import worker, import candidates, and YOLO import.
- Cleaned-head gates: Release `34753845097` PASS; Navigation Action Fencing `34753845073` PASS including Real Chrome stale-mutation; Frontend Runtime `34753845116` PASS including full Real Chrome runtime regressions.
- Formal `VERSION.txt` remains `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.

<!-- V42.25_STORAGE_INDEX_CANCEL_CLOSURE_20260913 -->
## 2026-09-13 Storage indexing cancellation fencing — CLOSED

- 真实缺口：素材导入确认后的 indexing 以批次处理；取消在 preflight 查询期间成为 durable truth 时，旧 Worker 仍可能继续 `materials.upsert_many(...)` / annotation / candidate outcome 写入，形成“任务最终 CANCELLED，但业务数据已继续提交”。
- 永久合同：`tests/integration/test_storage_index_cancel_fencing.py` 走真实 `scan -> AWAITING_CONFIRMATION -> confirm -> indexing`，在 material preflight 返回时注入 `CANCEL_REQUESTED`，要求最终 `CANCELLED`、material count 保持 0、candidate 保持未 indexed、不得发布 final result。
- RED/GREEN：`34755117132`；产品修复 `fe951e32aa2d7b840bfd9c975d500d0f0d200c9d`；永久化 `f9b11e691dd2e9daf0d6da2d3ef4f14c0b6d0909`。
- 修复边界：confirmation/ID assignment/preflight 后及 material、annotation、candidate outcome、mark-indexed 等不可逆写入前均重新读取 cancellation durable truth；不改变扫描、SHA 去重、YOLO label mapping 与确认语义。
- cleaned-head 正式门：Release Regression `34755481707` PASS；Navigation Action Fencing + Real Chrome `34755481732` PASS；Frontend Runtime + Real Chrome `34755481693` PASS（33 browser tests PASS）。accepted HEAD：`6cf54ac3b98a97a8be4c60a46d008e2a6bb499a1`。
- Release gate 同步关闭测试路径漂移：conversion / training resource contract 指回真实测试路径，并新增永久 path-integrity guard，workflow 中所有显式 `tests/*.py` 路径必须真实存在后才允许进入 pytest。
- 正式版本边界不变：`VERSION.txt = 42.24.0`；未 merge main、未 tag、未 release；A800 / genuine 10k acceptance 继续 defer。

<!-- STORAGE_IMPORT_PROGRESS_TRUTH_CLOSED_20260913 -->
## Storage import progress truth closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Product fix: `855abb7fe6fc2c759a85acf6c578dc5f8b62b10d` (`fix(storage): make import progress monotonic across confirmation`).
- Permanentization head: `030afa30c3e076cb6fac2c9234711b2f7d0c0cc6`.
- RED→GREEN migration run: `34755980730` PASS. Legacy behavior was proven RED before migration.
- Durable progress contract: material-import `AWAITING_CONFIRMATION` is a partial-task milestone with a 50% floor, not terminal 100%; confirmation/resume uses `MAX(existing_progress, 50)` and therefore never regresses a higher durable value.
- Confirmed indexing emits real monotonic `progress_percent` from the durable 50% floor toward 99% according to `indexed_at_least / selected_count`; only terminal success reaches 100%.
- Permanent tests: `tests/unit/task_runtime/test_material_import_progress_phases.py` and `tests/integration/test_storage_import_progress_truth.py` are included in the formal Release Regression gate.
- Cleaned-head Release Regression `34756082473`: PASS (`runtime-contracts` + `training-data-contracts`, including release-path guard).
- Cleaned-head Navigation Action Fencing `34756082427`: PASS.
- Cleaned-head Frontend Runtime Stabilization `34756082419`: PASS; `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were removed before the cleaned-head gates.
- Formal version boundary remains `VERSION.txt = 42.24.0`; no merge, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

<!-- TRAINING_REALTIME_PROGRESS_CLOSED_20260913 -->
## Normal training realtime progress closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Permanent RED contract commit: `474771da05c9652a1aa7103b737918ebe1011ffa`.
- Successful RED→GREEN migration run: `34756786009` PASS; legacy epoch-only behavior was proven RED before migration.
- Product fix: `16a1f76ebdc704bfbbcd7f96ce7a2b234f4017e7` (`fix(training): publish realtime batch progress`).
- Permanentization / cleaned product head: `65736aefd0b5961c3f6a7b3e45907937a9988973`.
- Progress contract: preparation owns 0..20; active normal training advances 20..90 using epoch + real train-batch completion; batch publication is throttled to about 4 Hz with mandatory final-batch flush; durable task progress remains monotonic.
- `job.json` publication is same-directory atomic replace so higher-frequency batch updates cannot expose a partially-written JSON file to the task handler.
- Durable `current_item` now carries `Epoch X/Y · Batch A/B` when batch truth is available; completed-epoch metrics remain authoritative and are not fabricated by batch callbacks.
- The normal model and the OOM-recreated model both attach the realtime batch callback. AI continuation is intentionally excluded from this closure and tracked as a separate follow-up batch.
- Permanent formal contracts include `tests/unit/test_training_realtime_progress.py`, `tests/unit/test_training_progress_v2.py`, and `tests/api/test_training_unified_task_overlay.py`.
- Cleaned-head Release Regression `34756946382`: PASS (`runtime-contracts` + `training-data-contracts`, release-path guard included).
- Cleaned-head Navigation Action Fencing `34756946390`: PASS; Real Chrome stale-mutation contract executed and passed.
- Cleaned-head Frontend Runtime Stabilization `34756946384`: PASS; full `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were deleted in the permanentization commit before cleaned-head gates.
- Formal version boundary remains `VERSION.txt = 42.24.0`; no merge, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## 2026-09-13 — AI continuation realtime progress CLOSED

- RED contract commit: `084923474bdb0627756560c40f1b1a23a0543c14`.
- RED→GREEN workflow: `34757329068` — legacy RED proven, focused continuation GREEN, training runtime regressions PASS, formal version boundary PASS.
- Product commit: `57c698ad318110e9e825a7e80e7a1ad9be073369`.
- Permanentized clean HEAD: `c354d60e319b6fa195d70e175185c3b9cabec792`; one-shot migration helper/workflow removed.
- Release Regression `34758049699`: runtime-contracts PASS and training-data-contracts PASS; permanent `tests/unit/test_training_ai_continuation_progress.py` is in the release gate.
- Navigation Action Fencing `34758049728`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34758049698`: frontend unit PASS and full Real Chrome runtime regressions PASS.
- Durable/UI truth: normal training remains 20..90; AI continuation advances 90..95 with cumulative Epoch/Batch truth instead of resetting to 1/N; continuation YOLO instances rebind epoch, batch, resource and device callbacks; 95..100 remains reserved for artifact verification/final evaluation.
- `VERSION.txt` remains exactly `42.24.0`; no main merge, tag, release, or A800 RC was performed.

## 2026-09-13 — Deployment queued resource-position truth CLOSED

- RED contract commit: `11b39b96ee28107e222bf9204ffd5f986e72e9fc`.
- RED→GREEN workflow: `34758458780` — legacy RED proven, focused deployment GREEN, syntax/diff checks PASS, formal version boundary PASS.
- Product commit: `46cc645ac6d47e0b02a3440c2a3000062b19ba05`; precise product diff is one `static/app.js` queue-meta condition replacement only.
- One-shot migration assets removed by `f1e6dad93adee5a8ead763294c5d4aa6b27d147f`.
- Permanentized clean HEAD: `caaeae70098fce7a90a5cd2fbfce481b6f84c332`; Release trigger boundary now includes `static/app.js` and the permanent conversion queue-truth frontend contract.
- Release Regression `34758615703`: runtime-contracts PASS and training-data-contracts PASS.
- Navigation Action Fencing `34758615733`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34758615696`: frontend unit tests PASS, including `conversion-unified-task-truth.test.mjs`, and full Real Chrome runtime regressions PASS.
- Queue semantics remain server-owned and resource-scoped. Both `queued` and `waiting_resource` deployment conversion rows now display the live durable `resource_queue_position`; `resource_wait_reason` remains shown only for `waiting_resource`. Existing 1.8s full polling and backend ordering/claim semantics were not changed.
- `VERSION.txt` remains exactly `42.24.0`; migration helper/workflow are physically absent; no main merge, tag, release, or A800 RC was performed.

## 2026-09-14 — ZIP whole-task progress monotonicity CLOSED

- Permanent RED contract commit: `ee0e944ff654869c99c115d38b537e55acafd23f` (`tests/frontend/zip-import-overall-progress.test.mjs`).
- First migration run `34764744365`: legacy RED was proven; GREEN intentionally remained open because the first mapper had a floating-point edge (`95 -> 95.9`) and the source contract was too syntactically narrow for the existing equivalent upload expression.
- Successful RED→GREEN run: `34785810840` — legacy RED PASS, precise migration PASS, focused GREEN PASS, full frontend unit regression PASS, formal version boundary PASS.
- Product commit: `4140a8fa17eb949c26f3c2ec9e5b2b1d3e615f50`; product diff is limited to `static/app.js` (+2/-1): add the processing-to-whole-task mapper and consume it from active v19 ZIP polling.
- One-shot migration helper/workflow were physically removed before permanentization.
- Permanentized clean HEAD: `c6c28b9ed6bf2bfbe3a6cefbde9cdf2609dc2c46`; Release trigger boundary includes the permanent ZIP whole-task progress frontend contract.
- Release Regression `34786028127`: runtime-contracts PASS and training-data-contracts PASS.
- Navigation Action Fencing `34786028132`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34786028178`: frontend unit tests PASS (including ZIP whole-task progress contract) and full Real Chrome runtime regressions PASS.
- Active v19 ZIP UI truth is now one monotonic whole-task scale: browser upload `0..35`, upload/validation baseline `38`, backend processing phase projected to `38..99`, terminal success only `100`. Raw backend phase progress is no longer allowed to overwrite the whole-task percentage and cause `38 -> 8` regressions.
- Backend v19 processing phase semantics were not changed; this closure fixes the frontend projection boundary only.
- `VERSION.txt` remains exactly `42.24.0`; no main merge, tag, release, A800 RC, or genuine 10k acceptance was performed.



<!-- LABEL_GOVERNANCE_BATCH_IMPORT_CLOSURE_20260926 -->
## 2026-09-26 — Manual label governance + background import performance closure

Status: **PRODUCT CODE CLOSED / LATEST CI STILL VERIFYING** on `feature/external-algorithm-publishing`.

### Product contracts now permanent

- External labels are factual input only. No exact-name, alias, historical mapping, AI/semantic or LLM path may auto-select a canonical label.
- Historical canonical labels can be merged many-to-one only after explicit user source selection and explicit target selection.
- The merge runs through the existing durable `MATERIAL_BATCH / REMAP_ANNOTATION_LABELS` owner, including `confirmed_empty` scope, digest fencing, retry/idempotency and source retirement only on complete success.
- Formal import annotations preserve source taxonomy provenance separately from canonical/project/training class IDs.
- Training preflight rejects non-current/non-canonical/temp/unmapped labels; schema changes are explicit and use previous weights as initialization, not strict optimizer-state resume.
- Label usage/remap selection uses normalized SQLite indexes. Legacy full-library scan on label rename/delete has been retired from the hot path.
- Formal multipart ZIP completion is now background merge/scan with durable `merging/validating` truth and read-triggered recovery after refresh/restart.
- Label-management refresh rediscovers active schema-unify tasks from durable Material Batch truth and reuses the single `annotation-label-remap` PollRegistry owner.

### Important commits in this closure window

- `7c356f2d...` — manual import label mapping.
- `1aa2f995...` / `3334385c...` — durable historical label unification foundation / multi-source unification.
- `429e6dcd...` — multi-label merge review UI.
- `68dd8319...` — import label provenance.
- `27a4806e...` — canonical training label preflight / schema-change truth.
- `029d15fe...` — retired automatic label suggestion paths.
- `60e31539...` — confirmed-empty scope index correction.
- `487f5bef...` / `2fd81dcd...` — permanent manual-choice / source guards.
- `2f6ec3cf...` — background multipart ZIP finalization.
- `041544f5...` / `7a8d2426...` / `0ab13ae4...` — durable label-unify refresh recovery and persisted/public task-state boundary fix.

### Real failure evidence handled

- A completed contract failure on `041544f5...` showed `TaskStatus.WAITING_RESOURCE` was incorrectly treated as a persisted enum. The durable enum has no such value; `WAITING_RESOURCE` is a public runtime projection. `0ab13ae4...` fixes the list query to use only persisted `QUEUED/RUNNING/CANCEL_REQUESTED` states and leaves public projection ownership unchanged.
- Earlier completed failures around retired `mapping_suggestions`, stale browser auto-preselection expectations, and provenance assertions were fixed from their actual job logs; tests were updated to the new manual-choice product contract rather than weakening production behavior.

### Verification boundary

- `VERSION.txt` remains exactly `42.24.0`.
- No main merge, tag or release.
- At this documentation point, current-head Actions are not all terminal; **do not mark latest CI PASS until every required check is completed successfully**.
- Genuine 20k production import/unification and real object-storage environment acceptance remain not verified.
- The legacy direct non-multipart v19 upload endpoint still performs synchronous post-upload scan for compatibility. The formal browser owner does not use it. Treat it as a compatibility migration item, not as a second preferred import runtime.
