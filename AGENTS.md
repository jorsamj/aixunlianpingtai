# Repository Agent Handoff

本仓库由 Codex、ChatGPT 和人工开发共同维护。开始修改前，先确认当前分支并读取对应交接文档，不要只根据 README 的正式版本号推断开发状态。

## 必读顺序

1. `docs/codex-handoff.md` — v42.24 及更早历史、产品约束、已知未验证事项。
2. `docs/codex-handoff-v42.25.md` — 当前 `refactor/v42.25-runtime` 增量接管状态。
3. `docs/superpowers/specs/2026-09-11-v42.25-training-data-contract-design.md` — v42.25 第一批训练数据合同设计。
4. 对当前工作先执行 `git diff main...HEAD` / `git log main..HEAD`，不要假设 handoff 已覆盖最后一个 commit。

## 当前开发状态

- 稳定主分支：`main`
- 当前 v42.25 开发分支：`refactor/v42.25-runtime`
- v42.25 基线：`main@01636b61780361dde91c12ac2732f46d2289b6be`
- README / VERSION 仍是 `42.24.0`，因为 v42.25 尚未正式发布。
- v42.25 第一批已实现，但 **FULL REGRESSION NOT VERIFIED / A800 REAL TRAINING NOT VERIFIED**。
- 未完成验证前不要合并 main，也不要把 v42.25 描述成生产已验收。

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

## v42.25 第一批主要实现位置

- `platform_core/training_splits.py`
- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`

测试：

- `tests/unit/test_training_components.py`
- `tests/unit/test_annotation_repository_scope.py`
- `tests/unit/test_training_splits.py`
- `tests/unit/test_snapshots.py`

## 接下来优先级

下一批优先做 **Task Runtime fencing / lease-loss duplicate execution prevention**，不要先继续加 UI 功能。

重点：

- lease_lost / cancel signal；
- execution generation / fencing token；
- heartbeat/checkpoint/finish 校验当前 generation；
- lease 丢失后终止整个 child process tree；
- expired task recovery 前验证 PID + create_time + command hash；
- Training / Conversion 统一 ProcessController 语义；
- 禁止旧 Worker 失租后继续发布 artifact 或 finish task。

详细边界见 `docs/codex-handoff-v42.25.md` 和 v42.25 design spec。

## 修改与交接要求

- 每批修改保持边界清晰，不把无关重构混入同一批。
- 代码修改同时补对应回归测试。
- 测试没有真实执行时必须明确写 `NOT VERIFIED`，不能用“测试文件已新增”代替“测试已通过”。
- 完成一批后同步更新当前 handoff；新架构决策写入 `docs/superpowers/specs/`，实施步骤可写入 `docs/superpowers/plans/`。
- 若旧测试锁定的是已经确认错误的旧语义，先更新测试合同，不要为了绿灯回退正确行为。
