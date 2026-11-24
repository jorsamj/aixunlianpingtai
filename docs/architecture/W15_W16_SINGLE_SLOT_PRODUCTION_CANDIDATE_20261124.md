# W15/W16 单槽生产候选与离线升级预检（2026-11-24）

> 状态标签：`SINGLE_SLOT_CANDIDATE_EVIDENCE_RECORDED` /
> `REAL_GPU_UAT_NOT_VERIFIED` / `REAL_HARDWARE_INFERENCE_NOT_VERIFIED` /
> `PRODUCTION_DUAL_SLOT_DISABLED` / `A800_PREFLIGHT_REQUIRED` /
> `A800_PRODUCTION_UPGRADE_NOT_EXECUTED` / `OFFLINE_INSTALL_NOT_VERIFIED`
>
> 本文件只记录可在隔离环境复现的证据与明确未验证边界。**未对 A800、4070、任何生产服务、
> 生产数据库/素材/GT/模型执行任何操作；未升级、未部署、未启用双槽。**

## 1. 候选身份

| 项 | 值 |
|---|---|
| 唯一开发分支 | `feature/external-algorithm-publishing` |
| 记录时远端 HEAD | 由 `git ls-remote origin refs/heads/feature/external-algorithm-publishing` 确认；本文档随提交推送后以该提交为候选 |
| VERSION.txt | `42.24.592`（本轮未修改） |
| 双槽开关 | 生产默认关闭（见 §3） |
| 生产升级工具 | `tools/production_upgrade.py`（预检 + 受控备份 + 回滚） |

候选定义：本轮链路提交全部通过 CI 后，以该分支**最终推送 SHA** 作为单槽生产候选；
不以“CI 全绿”等同生产部署安全，现场仍需按 §6/§7 逐项 UAT。

## 2. 本轮与单槽候选相关的已交付能力

- **M0**：修复 `list_process_identities()` 恢复元数据回归（历史缺失/新双槽损坏区分，
  不降级安全标准）。
- **M1**：恢复身份合同收口——`mark_started` 原子绑定、原始槽位合同持久化与
  `_dual_hold_verified()` 按合同判定、Stop Proof 前后置核验（含 schema-6/7 legacy 兼容）、
  可恢复清理（intent 先清、唯一执行证据留存、幂等收敛）。
- **生产缺陷修复**：`execution_status` 的 SQL NULL 不再被投影成字符串 `"None"`
  （否则真实 Agent 崩溃恢复必然 fail-closed）。
- **M2**：真实 `node_agent.py` OS 进程 SIGKILL → 新 Agent → 中央 HTTP 对账 → Stop Proof →
  Hold RELEASED → 清理 → 新任务准入的正式 E2E（POSIX 全链路走 Linux CI；Windows 变体为
  fail-closed 合同）。Windows 不提供 POSIX 证明时不计为通过。
- **W9**：真实可执行 PT/ONNX 比较（坐标还原、匹配 IoU、动态输入 fail-closed、runtime 版本）、
  不可变 Model Source Manifest + digest（跨远端/归档/板端写回校验）。
- **W10**：算法级负样本池接入训练选择、首次纯负样本/新类别纯负样本 typed admission code、
  11 条真实 SQLite 端到端闭环测试。
- **W8/M7（本轮部分）**：Worker 外部 SIGKILL 隔离、双槽 fencing、能力撤销后恢复安全、
  `execution_status.execution_slots` 诊断字段；双槽 reap 单飞锁修复并发竞态。
- **W16**：生产升级的受控备份/回滚能力（控制面 SQLite 一致快照、manifest digest、
  quick_check、有界与空间预检、显式 acknowledge、pre-rollback 安全快照、原子替换、
  启动后校验）；媒体/任务 artifacts 显式不在备份范围。
- **默认单槽不变量**：`node_agent.py` 双槽需 `DSH_AGENT_EXECUTION_SLOTS=2` 本地显式 opt-in，
  中央需节点 `allowed ∩ reported` 同时含 `execution-slots:2`；新增回归测试锁定默认单槽。

## 3. 默认值（生产候选口径）

| 项 | 生产默认 | 证据 |
|---|---|---|
| Agent 执行槽 | 1 | `node_agent.py::_build_executor` 仅 env opt-in 才 `max_slots=2`；测试 `test_dual_slot_execution_is_explicit_opt_in_and_defaults_to_one_slot` |
| 中央双槽授权 | 无（节点能力默认空列表） | `service_nodes.py` 默认 allowed/reported；`_execution_slots_for_worker` 需显式能力 |
| 双槽故障语义 | 缺 Hold 一律拒绝释放（不因节点降级放行） | `_dual_hold_verified()` + 原始槽位合同测试 |
| 远程训练停证 | 单槽远程 finish 无中央停证（既有边界） | 双槽才有 Hold/Stop Proof 合同；单槽依赖 Agent 本地 `terminate_tree` |

## 4. 单槽基线验收矩阵（隔离环境）

| 能力 | 代码/测试证据 | 本地结果 | 边界 |
|---|---|---|---|
| 原有本地训练 | `training-tasks` 系列测试；`tests/integration/test_training_task_worker.py` | 通过（隔离 tmp 数据） | 未在真实 20k 素材/GPU 上跑 |
| 原远程单槽训练 | `remote-training-runtime.yml` 套件；`test_node_agent_training_runtime.py` | 通过（test-double worker/transfer） | 真实 ultralytics CPU 训练未在本轮 CI 路由内 |
| 原单槽转换 | `remote-conversion-runtime.yml` 套件；W9 转换/数值/Manifest 测试 | 通过（合成/真实 ONNX+ORT；本机真实 PT→ONNX 比较 4 passed） | 真实厂商芯片/板端 NOT_VERIFIED |
| 历史任务与 DB schema | schema-6/7 fixture 迁移、`v42.25-release-regression.yml` | 通过 | 生产历史库未拷贝验证 |
| 默认单槽与双槽关闭 | §3 不变量测试 | 通过 | 生产节点配置未核对 |
| 离线安装 | 仅有“源码 + 离线前端资源包”证据 | **NOT VERIFIED** | 无 Python wheels/系统库/SDK 完整离线包；断网安装未验 |
| 依赖检查 | `requirements*.txt`、`remote_web_requirements.txt`、CI 依赖安装步骤 | 部分 | 目标机依赖版本/系统库未核对 |
| 升级预检 | `tools/production_upgrade.py --target <SHA>`（分支/工作区/空闲任务/服务健康/快进/py_compile 守卫） | 通过（单测） | 未在真实 systemd 主机执行 |
| 备份 | `--backup-dir` 一致备份 + manifest 校验 | 通过（单测，含 WAL 一致性） | 真实生产库容量/高并发未验 |
| 回滚 | `--rollback --apply --acknowledge-data-restore`（dry-run 默认） | 通过（mock systemd，未触真实服务） | 未在真实服务器执行；不删除备份后新建的库 |
| A800/4070 环境差异 | `docs/A800_LEGACY_PLATFORM_RELEASE_CANDIDATE_20261116.md`、4070 离线部署合同文档 | 仅文档 | **未操作任何真实节点**；A800 预检必需 |

## 5. 可复现命令（隔离环境）

```bash
# 单槽/恢复/双槽合同（Windows 可跑，POSIX-only 用例自动 skip）
python -m pytest -q tests/unit/test_agent_execution.py tests/unit/test_node_agent_entrypoint.py \
  tests/unit/test_node_agent_recovery.py tests/unit/test_node_agent_execution_slots.py \
  tests/unit/test_node_agent_executor_loop.py
# 真实 HTTP / 真实子进程 E2E（CPU；无 GPU）
python -m pytest -q tests/integration/test_agent_dual_slot_http_e2e.py \
  tests/integration/test_formal_training_runner_http_e2e.py
# 真实 Agent OS 进程崩溃恢复（全链路仅 Linux；Windows 跑 fail-closed 变体）
python -m pytest -q tests/integration/test_real_node_agent_sigkill_recovery.py -rs
python -m pytest -q tests/integration/test_real_node_agent_restart_fail_closed.py
# 升级工具（Linux 语义；Windows 上 POSIX 模式用例 skip）
python -m pytest -q tests/unit/test_production_upgrade.py tests/unit/test_deployment_upgrade_safety.py
python tools/production_upgrade.py --target <40位SHA>            # 默认 dry-run
python tools/production_upgrade.py --backup-only --backup-dir /data/backups/pre --target <SHA>
python tools/production_upgrade.py --rollback --backup-dir /data/backups/pre   # dry-run 校验
```

## 6. 明确未验证（不得宣称通过）

- `REAL_GPU_UAT_NOT_VERIFIED`：真实双卡 UAT 未执行（清单
  `docs/architecture/W7B_GPU_UAT_CHECKLIST_20261123.md` 保持未执行）。
- `REAL_HARDWARE_INFERENCE_NOT_VERIFIED`：RKNN/BMODEL/TensorRT 等板端推理未执行。
- `A800_PREFLIGHT_REQUIRED`、`A800_PRODUCTION_UPGRADE_NOT_EXECUTED`：未接触 A800/4070。
- `PRODUCTION_DUAL_SLOT_DISABLED`：生产双槽保持关闭；本轮不改生产配置。
- `OFFLINE_INSTALL_NOT_VERIFIED`：完整离线安装包/断网安装未验证。
- 真实 20 万级素材、长稳、P95 性能：未在生产数据/主机测量。
- 真实 Linux POSIX SIGKILL 全链路：以 GitHub Actions Linux job 实跑结果为准；
  在对应 job green 之前保持 `REAL_OS_SIGKILL_RECOVERY_NOT_VERIFIED`。

## 7. 建议的现场 UAT 顺序（需单独授权，本轮不执行）

1. 目标机只读预检：`tools/production_upgrade.py --target <候选SHA>`（dry-run）。
2. `--backup-only --backup-dir <安全路径>` 并 `verify_data_backup` 通过。
3. 单槽基线：本地训练、远程单槽训练、单槽转换各 1 个任务；检查任务/报告/Hold/日志。
4. 升级作业窗口：`--apply --backup-dir ...`；失败按 `STOPPED` 输出定位，不自动二次回滚。
5. 如需回滚：先 `--rollback ...`（dry-run）→ `--apply --acknowledge-data-restore`。
6. 双槽仅在独立授权节点按 W7-B 清单验证；验证前生产保持关闭。
