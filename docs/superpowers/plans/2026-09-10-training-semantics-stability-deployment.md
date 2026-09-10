# 42.25.0 Training Semantics, Stability and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 42.24.0 现有架构内收口外部标签、Ground Truth、训练、Worker、版本、部署和前端生命周期，使平台可继续进行 Windows 开发并面向 Linux/NVIDIA 生产验收。

**Architecture:** 保留现有 StorageManager、SQLite repositories、Durable Task、GPU Resource Manager 和分页架构。新增能力通过现有 repository/worker/service 边界接入；先统一后端语义和任务合同，再收口前端入口，避免在 `app.py`/`static/app.js` 增加新的 override 平行实现。

**Tech Stack:** Python 3、FastAPI、SQLite、Ultralytics/PyTorch、原生 ES Modules/JavaScript、现有 task runtime 和 storage providers。

---

## 执行规则

- 基线 `01636b6`，分支 `feat/42.25.0`，不修改或合并 `main`/`master`。
- Task 0 到 Task 19 严格顺序执行；每项独立 commit。
- 每项先检查现有唯一权威路径，只删除/迁移直接冲突的兼容 override，不另建平行实现。
- 最小检查：受影响 Python `py_compile`/import、JS `node --check`、合同或 SQL schema 检查；具体失败或核心数据安全才增加定向测试。
- 不运行整套 pytest，不运行预计超过 1–2 分钟的测试。

### Task 0: 权威路径审计与 42.25.0 边界清单

**Files:**
- Create: `docs/architecture/42.25-authoritative-paths.md`
- Inspect: `app.py`, `train_worker.py`, `task_worker.py`, `platform_core/**/*.py`, `static/app.js`, `static/main.mjs`, `static/modules/*.js`

- [ ] 记录外部导入、annotation、训练选择、split、preflight、子进程、版本、转换、检测、bootstrap/polling 的当前权威入口。
- [ ] 标明 `app.py` 和 `static/app.js` 中同名 override/兼容路径的调用关系、删除时机和禁止新增项。
- [ ] 记录 42.24.0 已有能力的复用点、Task 1–19 的落点与不可回退合同。
- [ ] 运行 `git diff --check`，提交 `docs: map 42.25 authoritative paths`。

### Task 1: 外部标签映射确认与样例预览

**Files:**
- Modify: `platform_core/storage/yolo_import.py`
- Modify: `platform_core/storage/import_candidates.py`
- Modify: `platform_core/storage/import_confirmation.py`
- Modify: `platform_core/storage/import_tasks.py`
- Modify: `platform_core/labels.py`
- Modify: `app.py`
- Modify: `static/modules/server-material-import.js`
- Modify: `static/modules/storage-import-progress.js`
- Modify: `static/app.js` only to remove/redirect the superseded import override
- Test only if needed: `tests/unit/storage/test_yolo_import.py`, `tests/integration/test_storage_import_worker.py`, `tests/frontend/server-material-import.test.mjs`

- [ ] Extend the durable candidate manifest with `import_id`, external class statistics, sample image/box references, mapping status and ignored status; keep formal annotation untouched during scan.
- [ ] Aggregate external class image/box counts in SQL/batches and expose paged sample preview endpoints without loading all candidates.
- [ ] Add mapping validation that accepts existing stable `label_id`, creates a validated new platform label, preserves external name, or ignores the class; duplicate external IDs are scoped by `import_id`.
- [ ] Make confirmation atomic: persist the mapping snapshot, then use TaskRepository's confirmation-to-queue transition; the Worker writes formal annotation only during indexing.
- [ ] Replace the current import confirmation UI with one authoritative mapping table and sample preview action; remove the superseded override path.
- [ ] Compile/check changed files and verify API-field consistency; commit `feat: confirm external labels before import`.

### Task 2: Durable 导入后标签重映射

**Files:**
- Create: `platform_core/label_remap_tasks.py`
- Modify: `platform_core/annotation_repository.py`
- Modify: `platform_core/storage/import_candidates.py`
- Modify: `platform_core/task_runtime/models.py`
- Modify: `task_worker.py`
- Modify: `app.py`
- Modify: `static/modules/storage.js`

- [ ] Store immutable import mapping provenance and expose an impact summary by `import_id`/external class.
- [ ] Add a durable, batched, checkpointed remap handler that updates platform annotation/label summaries without changing external files or image IDs.
- [ ] Add confirmation/audit APIs and UI with old/new mapping, affected images/annotations/boxes and task progress.
- [ ] Compile/check and commit `feat: remap imported labels durably`.

### Task 3: 统一 annotation_state 与 annotation_scope

**Files:**
- Modify: `platform_core/annotations.py`
- Modify: `platform_core/annotation_repository.py`
- Modify: `platform_core/storage/import_candidates.py`
- Modify: `platform_core/storage/import_tasks.py`
- Modify: `platform_core/material_repository.py`
- Modify: `app.py`
- Test only if needed: `tests/unit/test_annotations.py`, `tests/api/test_annotation_flow.py`

- [ ] Migrate repository schema/read normalization so `annotation_scope` is authoritative for annotated and confirmed-empty images; read legacy `confirmed_empty_scope` compatibly.
- [ ] Derive positive label IDs from valid boxes and reject inconsistent states/scopes.
- [ ] Apply YOLO TXT present/non-empty, present/empty and missing semantics exactly as the design specifies.
- [ ] Make manual/AI annotation writes preserve or explicitly update scope rather than inferring global completeness.
- [ ] Compile/check and commit `feat: model annotation ground truth scope`.

### Task 4: 先选素材，再聚合和冻结训练标签

**Files:**
- Create: `platform_core/training_labels.py`
- Modify: `platform_core/material_selection.py`
- Modify: `platform_core/annotation_repository.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `app.py`
- Modify: `static/modules/training.js`
- Modify: `static/app.js` to retire older training-submit overrides

- [ ] Add a server-side aggregation service over the frozen image selection returning platform label metadata, positive images, boxes, scope-covered images, legal per-label negatives and GT-incomplete images.
- [ ] Make the wizard freeze image selection before requesting available labels; do not return unrelated project labels.
- [ ] Require and persist `training_label_ids` plus immutable `training_label_schema_snapshot` at task creation.
- [ ] Keep `train_image_ids`/`test_image_ids` as the public selection contract and reject dataset-grouping fields.
- [ ] Compile/check contracts and commit `feat: derive training labels from selected materials`.

### Task 5: 任务级 YOLO 映射与按类别 GT 资格

**Files:**
- Modify: `platform_core/training_tasks.py`
- Modify: `platform_core/snapshots.py`
- Modify: `platform_core/training_splits.py`
- Modify: `train_worker.py`

- [ ] Build a deterministic continuous task-local class mapping from the frozen platform label snapshot.
- [ ] Filter boxes by selected label IDs and classify GT completeness per selected class using `annotation_scope`.
- [ ] Exclude images incomplete for every selected class; only write an empty TXT when scope covers every selected training label.
- [ ] Generate `data.yaml` names exclusively from the frozen snapshot and fail on any extra/missing class.
- [ ] Add one focused data-safety test if no existing test covers empty-after-filter behavior; compile/check and commit `fix: preserve class scoped ground truth in yolo snapshots`.

### Task 6: 封存 Split Manifest 与物理隔离 Test

**Files:**
- Modify: `platform_core/training_splits.py`
- Modify: `platform_core/snapshots.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `train_worker.py`

- [ ] Persist immutable Train/Validation/Test IDs and provenance once; never re-randomize on refresh/retry.
- [ ] Materialize only Train/Validation into the training runtime workspace and omit Test paths/GT from the training data.yaml and optimization inputs.
- [ ] Add a separate final-evaluation materialization path activated only after best.pt is final.
- [ ] Record access-stage evidence so quality gate, AI intervention, early stopping and best selection cannot read Test metrics/GT.
- [ ] Compile/check and commit `fix: seal test data until final evaluation`.

### Task 7: 正式训练 Preflight

**Files:**
- Create: `platform_core/training_preflight.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `app.py`
- Modify: `static/modules/training.js`

- [ ] Produce a persisted preflight report containing selection/effective counts, per-label GT statistics, state/scope exclusions, split leakage, class mapping, files/SHA, RAM/SHM/disk/GPU and device/config decisions.
- [ ] Block zero-positive selected classes, class-schema mismatch, leakage, missing/changed files, invalid scope and insufficient hard resources with actionable error codes.
- [ ] Show the report before final enqueue and preserve it on task details.
- [ ] Compile/check and commit `feat: add authoritative training preflight`.

### Task 8: requested/effective/actual 参数端到端一致

**Files:**
- Modify: `platform_core/training_tasks.py`
- Modify: `platform_core/training_devices.py`
- Modify: `task_worker.py`
- Modify: `train_worker.py`
- Modify: `app.py`
- Modify: `static/modules/training.js`

- [ ] Define one normalized training config schema covering every listed Ultralytics parameter and reject unknown/conflicting values.
- [ ] Persist requested, effective and actual config plus adjustment reasons; construct argv only from effective config and capture actual device/runtime values.
- [ ] Display all three levels where they differ and never silently fall back from requested CUDA to CPU.
- [ ] Compile/check payload/argv contracts and commit `fix: keep training configuration consistent end to end`.

### Task 9: Host Resource Guard 与 RAM/SHM 保护

**Files:**
- Create: `platform_core/host_resources.py`
- Modify: `platform_core/gpu_resources.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `task_worker.py`
- Modify: `train_worker.py`

- [ ] Sample RAM, `/dev/shm`, CPU, disk and IO with cross-platform fallbacks; do not invent SHM on Windows.
- [ ] Extend existing auto-tuning with host-memory estimates for imgsz/batch/workers/cache/augmentation/prefetch and record every adjustment reason.
- [ ] Refuse/delay unsafe starts before Linux OOM killer intervention and record runtime peaks plus throughput diagnostics.
- [ ] Compile/check and commit `feat: guard host memory for training`.

### Task 10: SQLite 容错与训练子进程身份/孤儿治理

**Files:**
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/task_runtime/process_control.py`
- Modify: `platform_core/task_runtime/worker.py`
- Modify: `platform_core/task_runtime/worker_instances.py`
- Modify: `task_worker.py`
- Modify: `train_worker.py`

- [ ] Add bounded retry and actionable diagnostics for SQLite open/transaction errors without creating a fallback database or exiting the scheduler loop.
- [ ] Persist PID, process start time, task ID, cmdline fingerprint, process group/session, launch token and assigned GPU.
- [ ] Verify all identity fields before recovery/cancel/kill; never kill by stale PID alone.
- [ ] Reconcile verified orphan training processes by reattaching management or safely terminating; map user cancellation to CANCELLED after process-group exit and GPU release.
- [ ] Add one focused process-identity safety test because PID reuse is destructive; compile/check and commit `fix: recover workers without stale pid kills`.

### Task 11: EarlyStopping 与后处理恢复

**Files:**
- Modify: `platform_core/task_runtime/models.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `platform_core/reports.py`
- Modify: `task_worker.py`
- Modify: `train_worker.py`
- Modify: `app.py`

- [ ] Add explicit training/post-processing stages and treat valid Ultralytics EarlyStopping with best.pt as normal TRAIN_COMPLETED.
- [ ] Preserve best.pt/last.pt when validation/test/report/version generation fails and mark POST_PROCESSING_FAILED.
- [ ] Add a durable retry-post-processing action that reuses existing best.pt without retraining.
- [ ] Compile/check and commit `fix: recover post processing after completed training`.

### Task 12: 前端页面生命周期单一权威实现

**Files:**
- Create: `static/modules/page-lifecycle.js`
- Modify: `static/main.mjs`
- Modify: `static/modules/task-poller.js`
- Modify: `static/app.js`

- [ ] Introduce page enter/leave, request abort/token guard, polling start/stop, modal dispose and listener cleanup APIs.
- [ ] Route existing page entry through one bootstrap and remove duplicate DOMContentLoaded/loadAll/setInterval/window override paths as each caller migrates.
- [ ] Ensure stale requests, timers and Toasts cannot update a different page.
- [ ] Run `node --check` and commit `refactor: centralize frontend page lifecycle`.

### Task 13: 刷新、局部更新、页面稳定与任务标题

**Files:**
- Modify: `static/main.mjs`
- Modify: `static/modules/material-pagination-runtime.js`
- Modify: `static/modules/training.js`
- Modify: `static/modules/task-poller.js`
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Modify: `app.py`

- [ ] Make refresh load only current-page summaries/pages and cached resource discovery; remove full material/model/log loads from unrelated pages.
- [ ] Patch changed task fields and chart series in place using stable keys; preserve order, filters, pagination, tabs, expansions and scroll.
- [ ] Reserve thumbnail/skeleton dimensions and prevent whole-container replacement during polling.
- [ ] Use algorithm display_name/name/code as the task title and task ID as secondary metadata.
- [ ] Run JS syntax checks and commit `perf: stabilize page refresh and training updates`.

### Task 14: 算法版本 current 指针与回退

**Files:**
- Modify: `platform_core/algorithms.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `platform_core/deployment/conversion_tasks.py`
- Modify: `app.py`
- Modify: `static/modules/algorithms.js`

- [ ] Persist `current_version_id` and immutable parent/version metadata with backward-compatible default selection.
- [ ] Add atomic rollback that changes only the current pointer and audits the prior/current version.
- [ ] Make default detection, continuation training and conversion use current_version_id; new descendants keep the rolled-back parent.
- [ ] Compile/check and commit `feat: add non destructive algorithm version rollback`.

### Task 15: 部署转换能力中心

**Files:**
- Create: `platform_core/deployment/capabilities.py`
- Modify: `platform_core/conversion.py`
- Modify: `app.py`
- Modify: `static/modules/algorithms.js`
- Modify: `static/app.js`

- [ ] Model per-platform environment/default configuration for ONNX, TensorRT, Atlas, RKNN and Sophon without flattening platform-specific fields.
- [ ] Implement real cached probes for Python/SDK/toolkit/version/commands and explicit missing-component results.
- [ ] Reframe the existing deployment-conversion page as capability/configuration only.
- [ ] Compile/check and commit `feat: manage conversion capabilities`.

### Task 16: 从算法版本发起 Durable Conversion

**Files:**
- Modify: `platform_core/deployment/conversion_tasks.py`
- Modify: `deployment_worker.py`
- Modify: `app.py`
- Modify: `static/modules/algorithms.js`

- [ ] Add version-scoped conversion actions that resolve immutable source model/labels and capability config.
- [ ] Enqueue a durable conversion task with stdout/stderr/exit/tool version/config/SHA/size and never execute conversion in HTTP.
- [ ] Expose version conversion history and accurate environment-blocked errors.
- [ ] Compile/check and commit `feat: convert algorithm versions durably`.

### Task 17: 部署产物统一管理

**Files:**
- Create: `platform_core/deployment/artifacts.py`
- Modify: `platform_core/deployment/conversion_tasks.py`
- Modify: `app.py`
- Modify: `static/app.js`

- [ ] Persist primary versus auxiliary artifacts, immutable source/version/config/tool metadata and SHA256.
- [ ] Implement paged artifact records with conversion and board-verification statuses kept separate.
- [ ] Make the deployment-artifacts page emphasize the deployable file and expose logs/manifests as auxiliary files.
- [ ] Compile/check and commit `feat: centralize deployment artifacts`.

### Task 18: 删除测试发布并收口检测台

**Files:**
- Modify: `static/index.html`
- Modify: `static/main.mjs`
- Modify: `static/app.js`
- Modify: `platform_core/deployment/inference_tasks.py`
- Modify: `app.py`

- [ ] Remove Test Publish menu/route/page/polling/Toast/Promise/listeners and server calls rather than hiding the menu.
- [ ] Place Detection Console under algorithm management with algorithm/current-or-history version, image/video, confidence/IoU, boxes/classes/confidence and real timing.
- [ ] Keep runtime/hardware failures explicit for unsupported formats.
- [ ] Run JS/Python syntax checks and commit `refactor: consolidate model validation in detection console`.

### Task 19: 收口、版本与发布开发分支

**Files:**
- Modify: `VERSION.txt`
- Modify: `README.md`
- Modify: `docs/codex-handoff.md`
- Modify: cache/version constants in `static/index.html`, `static/main.mjs`, `static/app.js`

- [ ] 优先检查实现本身，仅对本轮受影响的 Python/JavaScript 执行编译、构建或语法检查；不编写低价值测试，不重复运行已经通过且不能提供新信息的检查。
- [ ] 只有编译/构建出现具体失败、仓库规则强制要求或存在明确数据安全风险时，才增加最小必要定向检查；单项检查预计长时间运行时先停止，不自行扩大测试范围。
- [ ] 编译/构建通过且没有具体失败信号后立即停止验证；将当前环境无法确认的能力列为 `NOT VERIFIED`，说明原因，并给出最小手动验证步骤、预期结果和注意事项。
- [ ] Set version/cache identifiers to 42.25.0 and update handoff/release notes.
- [ ] Commit `release: prepare version 42.25.0`, push only `feat/42.25.0`, report all task SHAs and Linux/A800 minimum acceptance steps.
