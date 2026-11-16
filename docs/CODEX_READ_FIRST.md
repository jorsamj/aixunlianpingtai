> **2026-11-17 P1H–P1J 本地交付 / 准确收尾SHA CI待核对**：复用ModelAssets增量实现本地算法新增/基本编辑和写后GET核验；v62训练任务只读游标列表/详情、v44 finalized优先报告摘要（Val/Test独立），复杂报告回原Owner。新开关vue_algorithm_manage / vue_training_tasks / vue_training_report；旧默认保留。仅原算法POST/PUT，无新执行写端点/调度/GT/schema改动。Python41、Node76、Vue Chrome14及真实入口临时库/桌面平板已验；生产/硬件/完整离线安装未验。入口缓存610，VERSION保持。见[本轮合同、写入边界、证据及后端拆分建议](PRODUCTIZATION_P1H_P1J_20261117.md)。完成后停止。

> **2026-11-17 P1E–P1G 本地交付 / 准确修正SHA CI待核对**：模型资产/版本与转换历史只读页已接通，vue_model_assets opt-in；原v12/v42新增asset_view有界安全投影，复用AlgorithmSqlStore/ModelArtifact/历史及durable Owner，原默认响应/执行/GT不变。类型构建、Python36/Node73/Chrome11、真实入口临时库及桌面平板已验；未生产/SDK/数值/硬件/现场离线验收。版本号42.24.592保持，入口缓存609。见[本轮合同、入口、测试、证据与离线方式](PRODUCTIZATION_P1E_P1G_20261117.md)。本轮结束停止。

> **2026-11-17 P1B–P1D 本地完成 / 准确SHA CI待推送核验**：Vue正式字典CRUD及节点只读总览，默认旧页面；开关vue_catalog_manage / vue_service_nodes。复用原API/revision/operation_id/回执/导航，全局未知packet跨项目与刷新保留；原Repository/调度/后端业务不变。真实临时库入口验收、Node/Chrome及构建已验；未部署/真实SDK/离线现场。见[本轮交付、入口、证据和后端建议](PRODUCTIZATION_P1B_P1D_20261116.md)。

> **2026-11-16 P0/P1 精准收尾**：入口三资源统一缓存607，状态复用后端status/label；44项定向Node、3项Chrome及真实入口隔离冒烟通过。准确新SHA CI/上传制品推送后核对；真实离线部署未验证，不进入P2。见[收尾证据与离线打包方法](PRODUCTIZATION_P0_P1_CLOSEOUT_20261116.md)。

> **2026-11-16 产品化 P0/P1（本批精确 SHA CI 待核）**：用户已授权 Vue3/TS/Vite + Element Plus 厂商/芯片只读预览，原登录/API/导航/Task/GT Owner 保留。默认关闭，`?vue_catalog_preview=1` 可进入；已有GET新增 `observe_only` 避免SDK检测，旧管理完整保留。VERSION.txt 实际42.24.592保持，不按旧文档回退42.24.0。详见[本批范围、20域索引、测试与回退](PRODUCTIZATION_P0_P1_20261116.md)。未生产部署，历史“不改Vue”仅为旧阶段限制。

<!-- READ_FIRST_2026_09_25 -->
> ## 2026-09-25 最新入口
>
> 当前长期开发分支是 feature/external-algorithm-publishing。开始前必须先读取实时 GitHub HEAD；不要使用本文件旧的 refactor/frontend-runtime-stabilization 标题作为当前分支依据。
>
> 当前优先读取：
> 1. docs/CODEX_HANDOFF_2026-09-25_ANNOTATION_CLEANING.md
> 2. docs/PROJECT_HANDOFF_CURRENT.md
> 3. docs/CODEX_CURRENT_STATE.md
> 4. 再按下面历史顺序补背景
>
> VERSION.txt 仍必须保持 42.24.0。
>
# Codex Read First

This is the shortest entry point for continuing `jorsamj/aixunlianpingtai` on branch `refactor/frontend-runtime-stabilization`.

## Mandatory read order

Before editing, read and reconcile these files against live GitHub HEAD:

1. `docs/CODEX_READ_FIRST.md`
2. `docs/CODEX_HANDOFF_2026-09-16_DEPLOYMENT_CANDIDATE.md`
3. `docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V2.md`
4. `docs/CODEX_HANDOFF_2026-09-16_GENERIC_QUEUE_EXACTNESS.md`
5. `docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V1.md`
6. `docs/CODEX_CURRENT_STATE.md`
7. `docs/CODEX_HANDOFF_2026-09-15_DISCOVERY_AND_ORPHAN_PROCESS_CLEANUP.md`
8. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_FINAL_VALIDATION_OOM.md`
9. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_TASK_VISIBILITY.md`
10. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_WORKER_ISOLATION.md`
11. `docs/TECH_DEBT_CLOSURE_V42_25.md`
12. `docs/frontend-legacy-audit.md`
13. `docs/FRONTEND_OWNER_MAP_V42_25.md`

`docs/CODEX_CURRENT_STATE.md` contains valuable historical closure detail, but historical branch/push snapshots inside that long-lived document may lag the live branch. Never trust an old SHA or `push pending` sentence over the actual remote branch. The newest dated deployment-candidate handoff above is the current resume pointer; live GitHub state still wins if newer commits exist.

## Current resume pointer — 2026-09-16

Runtime-validated clean baseline:

```text
cca721d13ead436c46ee4ffab0dbd06b3cbaeca5
```

Formal version remains:

```text
VERSION.txt = 42.24.0
```

The runtime baseline above has the latest Task Runtime Truth v1/v2 and Generic Durable Queue Exactness work already integrated and validated. Documentation-only commits may sit on top of that runtime baseline after this file is updated, so always verify the live branch before editing.

Do not reopen these 2026-09-16 closures merely because an older document contains a stale branch snapshot:

- Task Runtime Truth v1;
- Task Runtime Truth v2;
- Generic Durable Queue Exactness;
- Resource Discovery / Training Input Integrity closures already recorded in the dated handoffs/current-state history.

Durable task presentation invariants now include:

```text
task_status > compatibility status
phase > task_stage / stage
progress_percent > legacy progress
resource_queue_position may render as exact only when resource_queue_position_exact === true
```

The browser must not invent a durable percentage from counts and must not promote a candidate rank to an exact Worker/hardware queue position.

For the exact CI evidence, deployment-candidate boundary and remaining real-environment acceptance work, read:

`docs/CODEX_HANDOFF_2026-09-16_DEPLOYMENT_CANDIDATE.md`

## Non-negotiable repository constraints

- Do not merge `main`.
- Keep `VERSION.txt` exactly `42.24.0`.
- No tag, release or force push.
- Windows development + NVIDIA Linux production compatibility is mandatory.
- Do not delete/relax tests or lower thresholds to make CI pass.
- Do not restore retired legacy owners.
- Reuse existing TaskRepository, Scheduler, Worker Runtime, Worker heartbeat, PollRegistry and GPU admission/reservation truth; do not build parallel replacements.

## Current implemented stability batches

### GPU Runtime Truth Phase 1A

Implemented and pushed before the Worker-isolation batch. Real NVIDIA/A800/multi-node/MIG acceptance is still pending. Phase 1B has not started.

### Training Worker Isolation & Fast Dispatch

Implemented in the current branch. Read:

`docs/CODEX_HANDOFF_2026-09-15_TRAINING_WORKER_ISOLATION.md`

Key invariant:

```text
non-training work busy
!=
training Worker blocked
```

Compatibility `task_worker.py --roles all` supervises an isolated `training` child and a separate non-training background child. It must never regress to one serial all-handler Scheduler.

Default/auto resource discovery does not escalate to whole-machine recursive scanning when roots are omitted. Deep/full discovery requires explicit roots.

The dedicated Scheduler claim loop remains the existing implementation; default idle poll is `0.25s`. No second scheduler or queue was introduced.

### Resource Discovery Worker Ownership + Training Orphan Cleanup

Implemented in the current branch. Read this handoff before changing Worker/process cleanup behavior:

`docs/CODEX_HANDOFF_2026-09-15_DISCOVERY_AND_ORPHAN_PROCESS_CLEANUP.md`

Two real production defects are covered.

#### Resource discovery ownership

The isolated background Worker previously omitted the valid `discovery` role, so `RESOURCE_DISCOVERY` could remain permanently:

```text
QUEUED
worker_id = None
```

The current background group is:

```text
discovery
storage
materials
video
annotation
conversion
deployment-test
```

The training child remains `training` only.

#### Abrupt training-leader death / orphaned DataLoader processes

Real A800 evidence from historical task `99a99b479ecf` showed Linux OOM killed main PID `310980`, while DataLoader-like descendants remained alive as `PPID=1` and retained GPU/shared-memory resources. GPU admission correctly refused to start the next training because the memory usage was real; there was no evidence that admission itself was wrong.

`launch_process()` already owns a private POSIX session/process group per task. `ProcessController.terminate_tree()` now uses that private group to reap surviving descendants even when the exact main PID has already disappeared. Cleanup remains PID/create-time/command-hash fenced and does not use broad `pkill python` behavior.

Scheduler ordering remains fail-closed: terminal task state must not be published when process cleanup cannot be verified.

### Training Task Visibility Stability / Single Final Rendering Owner

Implemented in the current branch. Read:

`docs/CODEX_HANDOFF_2026-09-15_TRAINING_TASK_VISIBILITY.md`

Real user evidence was:

```text
TaskRepository = RUNNING
/jobs = task present
training process = advancing
UI = task temporarily disappears
later polling = task reappears
```

The concrete race was frontend ownership:

```text
legacy loadRelated()
  /api/projects/{project_id}
  -> state.jobs

TrainingTaskRuntime
  /api/projects/{project_id}/jobs
  -> state.jobs
```

plus legacy `renderTraining423/424/425` rendering the same table.

The current branch gives canonical training jobs and final training rows to the focused training runtime/visibility owner. Generic project refreshes cannot erase canonical `state.jobs`, and the visibility runtime does not create another timer. PollRegistry remains the sole training polling owner.

Non-terminal transitional states (`starting`, `pausing`, `resuming`, `stopping`, `cancel_requested`) remain visible and continue polling where appropriate.

Do not fix future visibility problems by increasing polling frequency, fabricating tasks in browser memory, adding another polling owner, or delayed DOM reinsertion.

### Training Final Validation OOM Hardening / Failure Truth

Implemented in the current branch. Read:

`docs/CODEX_HANDOFF_2026-09-15_TRAINING_FINAL_VALIDATION_OOM.md`

Real A800 evidence came from task `99a99b479ecf`:

```text
300/300 training epochs completed
best.pt / last.pt written
Ultralytics automatic final validation reached 5/7
Linux global host-memory OOM killed exact training PID 310980
TaskRepository = FAILED
```

This was host RAM/shared-memory pressure, not evidence of A800 VRAM exhaustion.

The current branch:

- bounds automatic DataLoader workers with `TRAINING_AUTO_MAX_DATALOADER_WORKERS` (default `2`);
- leaves manual worker settings explicit rather than silently rewriting them;
- keeps the existing Label Contract, Scheduler, Worker Runtime and strict completion handshake;
- preserves real process return code/signal and completion-handshake reason on child failure;
- writes structured `failure.json` evidence;
- can classify an evidenced `300/300 + checkpoint + final validation interrupted` case as a recoverable `final_validation` failure without converting it to success;
- does not infer OOM from `SIGKILL` alone;
- does not publish an official algorithm version from an unverified checkpoint.

Important boundary:

```text
recovery_action = revalidate_checkpoint
recovery_action_available = false
```

A real validation-only recovery task/API/button is not implemented yet. Do not claim it exists.

The historical task `99a99b479ecf` must remain historical `FAILED` truth. Do not manually rewrite it to success.

The same run also logged:

```text
[质量门禁] epoch=300 抽取=0张 map50=0.90642 decision=continue
```

That is a separate evidence-backed follow-up. The current batches do not claim to fix the `抽取=0张` behavior.

## Current acceptance work

These implementations are not fully `CLOSED` until production-shaped checks are completed.

### Resource Discovery Worker ownership

After deploying/restarting the normal supervisor:

```text
RESOURCE_DISCOVERY queued
-> background Worker claims it
-> task runs without a separately launched manual discovery Worker
```

Also verify training remains owned only by the training Worker.

### Training orphan process cleanup

On A800 use a short controlled training acceptance. For normal completion, failure/cancel, and a controlled abrupt leader termination where practical, verify:

```text
no task-owned DataLoader execution remains
-> no old task process group remains
-> GPU reservation releases after cleanup
-> nvidia-smi returns toward idle/baseline
-> queued next training proceeds automatically once admission is satisfied
```

Do not use broad `pkill python` as acceptance.

### Training Final Validation OOM Hardening

Verify on A800 after deploying the latest HEAD:

```text
resource_strategy=auto
-> resolved DataLoader workers <= configured safety cap (default 2)
-> training completes
-> automatic best.pt final validation completes
-> no new host-memory OOM for training PID
-> trusted completion handshake reaches terminal success / 100%
```

For a controlled external-kill failure, verify failure evidence exposes signal/returncode/stage/completion reason rather than stale progress text.

### Training Worker Isolation

Verify on A800:

```text
background material/annotation/video work active
+
Training Worker idle
+
GPU available
+
TRAINING queued
-> training independently claims in roughly 1–3 seconds
```

### Training Task Visibility

Verify in a real browser while real A800 training advances:

```text
/jobs continuously contains active task
+
manual refresh / polling / navigation / unrelated data refreshes
-> active row never disappears
```

Exercise pause/resume/stop transitions and confirm the task remains visible through transitional states.

## Still later / explicitly not started

GPU Runtime Truth Phase 1B remains separate:

- node-scoped `gpu_reservations`
- cross-node worker-slot identity/uniqueness migration
- full GPU assignment identity
- worker/server remote routing
- automatic cross-node GPU scheduling

The quality-gate evidence `[质量门禁] ... 抽取=0张` is also still open and should be handled as its own next batch after the current runtime fixes are accepted.

Do not silently combine Phase 1B with final-validation hardening, frontend visibility, Worker-isolation, process-cleanup, or discovery acceptance work.

## Acceptance wording

Until real production discovery acceptance is complete, use:

```text
Resource Discovery Worker Ownership
IMPLEMENTED + AUTOMATED REGRESSION
REAL PRODUCTION ACCEPTANCE: PENDING
```

Until real A800 process cleanup acceptance is complete, use:

```text
Training Orphan Process Cleanup
IMPLEMENTED + REAL SUBPROCESS REGRESSION
REAL A800 GPU-MEMORY / NEXT-TASK ACCEPTANCE: PENDING
```

Until real A800 final-validation acceptance is complete, use:

```text
Training Final Validation OOM Hardening
IMPLEMENTED + AUTOMATED REGRESSION
REAL A800 FINAL-VALIDATION ACCEPTANCE: PENDING
```

Until real A800 Worker-isolation acceptance is complete, use:

```text
Training Worker Isolation & Fast Dispatch
IMPLEMENTED + AUTOMATED REGRESSION
REAL A800 CONCURRENCY / 1-3s DISPATCH ACCEPTANCE: PENDING
```

Until real-browser/A800 visibility acceptance is complete, use:

```text
Training Task Visibility Stability
IMPLEMENTED + AUTOMATED REGRESSION
REAL BROWSER / A800 ACCEPTANCE: PENDING
```

Do not mark these P0 items `CLOSED` before their real acceptance is complete.
