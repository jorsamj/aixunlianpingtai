# Repository Agent Handoff

本仓库由 Codex、ChatGPT 和人工开发共同维护。开始修改前，先确认当前分支并读取对应交接文档，不要只根据 README 的正式版本号推断开发状态。

## 必读顺序

1. `docs/codex-handoff.md` — v42.24 及更早历史、产品约束、已知未验证事项。
2. `docs/codex-handoff-v42.25.md` — 当前 `refactor/v42.25-runtime` 增量接管状态。
3. `docs/superpowers/specs/2026-09-11-v42.25-training-data-contract-design.md` — v42.25 第一批训练数据合同设计。
4. `docs/superpowers/specs/2026-09-11-v42.25-task-runtime-fencing-design.md` — 第二批 Task Runtime fencing 设计。
5. `docs/superpowers/specs/2026-09-11-training-resource-contract-fix.md` — 2026-09-11 真实 A800 训练暴露的 batch/cache 参数覆盖事故与修复合同。
6. 对当前工作先执行 `git diff main...HEAD` / `git log main..HEAD`，不要假设 handoff 已覆盖最后一个 commit。

## 当前开发状态

- 稳定主分支：`main`
- 当前 v42.25 开发分支：`refactor/v42.25-runtime`
- v42.25 基线：`main@01636b61780361dde91c12ac2732f46d2289b6be`
- README / VERSION 仍是 `42.24.0`，因为 v42.25 尚未正式发布。
- v42.25 第一批训练数据合同已实现。
- v42.25 第二批 Task Runtime fencing 已实现，并通过定向 Linux GitHub Actions；**FULL REGRESSION NOT VERIFIED / A800 REAL TRAINING NOT VERIFIED**。
- 训练资源参数覆盖修复已通过定向 Linux CI，但修复后的 A800 实际训练仍需重新验证。
- 未完成真实环境验证前不要合并 main，也不要把 v42.25 描述成生产已验收。

## 不得回退的核心合同

- 训练任务继续按精确 `train_image_ids / test_image_ids` 工作，不恢复“数据集分组”作为训练合同。
- Windows 开发与 NVIDIA Linux 生产必须共用跨平台代码，禁止写死盘符、反斜杠路径或 Windows-only shell 流程。
- 已有素材、标注、算法版本不得因升级被清空、移动或重新编号。
- AnnotationRepository 是 Ground Truth authority；MaterialRepository 中标注字段只是 searchable projection。
- `unannotated`、`annotated`、`confirmed_empty` 是不同语义；`confirmed_empty` 是合法负样本。
- `annotation_scope` 属于 Ground Truth 与 Training Snapshot 合同，不得只保存 boxes。
- same SHA + same normalized GT：训练时 canonicalize，不删除素材记录。
- same SHA + different normalized GT：必须 `duplicate_annotation_conflict`，不得 keep-first / keep-latest / 随机选择。
- Train / Validation / Test 必须按不可拆分 Component 划分，并保留最终 leakage guard。
- 有稳定 label/code 时，重复标注语义优先使用稳定 code，不把历史 class_id 当永久身份。
- Training Snapshot v3 必须保留 annotation state/scope/hash 和 duplicate exclusion audit。
- Task Runtime 的旧 execution 在 lease/generation 失效后不得继续 finish、发布正式 artifact 或与新 execution 并发占同一资源。
- 进程恢复必须用 PID + create_time + command hash 证明身份；无法证明时 fail closed。
- 显式正整数 `batch` 是 Auto 资源策略的硬上限：Auto 只可安全下调，不得上调。
- `batch=-1` 才表示用户明确委托平台自动选择 batch。
- `cache=false` 是权威关闭，Auto 不得隐式改成 disk/ram。
- Auto 不得增加用户指定的 DataLoader workers；`workers=0` 必须保持单进程加载。

## v42.25 主要实现位置

训练数据合同：

- `platform_core/training_splits.py`
- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`

Task Runtime fencing：

- `platform_core/task_runtime/fenced_repository.py`
- `platform_core/task_runtime/process_control.py`
- `platform_core/task_runtime/worker.py`
- `platform_core/task_runtime/scheduler.py`
- `platform_core/deployment/conversion_tasks.py`
- `task_worker.py`

训练资源合同：

- `platform_core/training_metrics.py`
- `tests/unit/test_training_resource_contract.py`

## 当前后续优先级

1. 用 A800 对修复后的训练资源合同做真实重跑，确认 `batch=16/workers=4/cache=false` 最终传入 Ultralytics 仍为 `16/4/false`。
2. 若仍出现 `Pin memory thread exited unexpectedly`，再单独检查 kernel/cgroup OOM、`/dev/shm`、DataLoader worker/pinned memory，不得用全平台强制 `workers=0` 掩盖问题。
3. 收口算法级 label schema。当前训练 Snapshot 仍从项目全部 active labels 构造 schema，因此 `nc` 可能包含与当前算法无关的项目标签。正确方向是算法/训练任务锁定 stable label codes，而不是按当前批次中“出现过的框”猜类别。
4. 下一大批做生产安全：`/data` 静态暴露、CORS、SSRF、训练服务器 SecretStore。

## 修改与交接要求

- 每批修改保持边界清晰，不把无关重构混入同一批。
- 代码修改同时补对应回归测试。
- 测试没有真实执行时必须明确写 `NOT VERIFIED`，不能用“测试文件已新增”代替“测试已通过”。
- 完成一批后同步更新当前 handoff；新架构决策写入 `docs/superpowers/specs/`，实施步骤可写入 `docs/superpowers/plans/`。
- 若旧测试锁定的是已经确认错误的旧语义，先更新测试合同，不要为了绿灯回退正确行为。
