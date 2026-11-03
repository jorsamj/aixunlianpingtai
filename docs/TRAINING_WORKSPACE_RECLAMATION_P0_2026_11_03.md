# 训练任务临时 Bundle 回收 P0｜需求、方案、进度与验收（2026-11-03）

> 状态：**42.24.510 本地代码候选，生产未部署、正式数据未清理**。本文件描述可核验的开发结果，不代表 11-03 生产 503 已完成根因定位，也不代表磁盘已经释放。

## 1. 事故与可信度

- 用户现场：生产 `train_2eefb94e6efe48aeb9e555e4`（烟火判断）已为 `TRAINING/SUCCEEDED`，无 Worker 租约，历史 PID/PGID 未发现；`work/bundle` 约 **1.7 GiB**、28,738 文件；`evidence/bundle` 约 **163 MiB**，必须保留；`workspace-cleanup.json` 上次 `retryable/WORKSPACE_PREVIEW_STALE`，未成功分离。
- 11-03 12:33 北京时间人工清理 HTTP 503，旧 API 统一映射为 `TRAINING_WORKSPACE_RETRYABLE`，现场**没有异常 errno 和阶段**，不能认定根因一定是归档或 ENOSPC。
- 现场 `df` 报 196G 总量、180G 已用、7.4G 可用、约 97%；inode 12%，ext4 rw；这是用户当时的观测，**不是本轮开发期间重新读取的生产实时值**。
- 同一任务在训练/存储 Worker 都出现维护诊断警告；某次只读遍历遇到瞬时 `.tmp` 消失，不等于证据损坏。
- 隔离代码审查确认：旧 `_evidence_stamp` 把项目级 SQLite/WAL 元数据纳入任务一致性，其他算法正常写 WAL 可制造误报；但该条件是否导致本次特定生产回执仍待部署后诊断。

## 2. 不变量与产品要求

1. 唯一可信任务状态源仍为 `TaskRepository`；临时文件所有权仍来自既有 `workspace-lifecycle.json`、Snapshot、Manifest、`ArtifactStore`；不引入新任务状态库或新清理器。
2. 仅允许删除已证明归属本任务的 `work/bundle`，先原子分离为 `work/.bundle-reclaim`。原图、正式 GT、Shared Cache、模型权重、报告、Checkpoint、恢复依赖和证据目录都不是删除目标。
3. 只有终态、租约已释放、执行进程已退出、无活动消费者、模型/版本证明可信、证据已完成持久归档时可回收；异常一律拒绝删除。
4. 非本任务的数据库提交不得令本任务重复归档；当前任务 Snapshot、attempt、版本 ID、模型合同或文件身份变化必须阻止目录分离。
5. 归档中途失败、Worker 崩溃、手动 POST 超时不等于清理成功；重新检查后才能再次释放。
6. `deleted_logical_bytes` 是任务文件逻辑字节，不等于实际可用磁盘增长量；`physical_space_released` 无可靠测量时必须为 `null`。
7. 自动维护必须单任务跨进程串行、有限扫描、退避和错误分类；长归档不能独占报告图片读取锁。
8. 失败/取消且缺失可信 Manifest 的历史 Bundle 继续安全拒绝；后续需单独证明其早期准备阶段所有权与正式证据依赖，不得因为磁盘紧张跳过证明。

## 3. 42.24.510 实现映射

| 项 | 代码 | 方案/状态 |
|---|---|---|
| P0-01 非本任务 WAL 误判 | `training_workspace_lifecycle.py`, `algorithm_sql_store.py` | **已编码**：任务文件 stat 与精确已验证版本 ID 分离；初始模型 SHA 核验，最终任务数据库保护事务内短暂取得算法版本数据库写门禁，读取同一任务版本身份并短暂原子分离，不对整个 WAL 采戳 |
| P0-02 归档复用 | `training_workspace_lifecycle.py` | **已编码**：`evidence/archive-proof.json` 绑定项目/任务/attempt/Snapshot、Manifest/Result SHA、成员列表；文件首次源/目标哈希校验后留下证明，完整证明时以身份/stat 快速复用，部分归档在无证明时通过 SHA 复用；唯一临时文件名、文件和目录 fsync、原子替换；证明持久化完成前不删除 Bundle |
| P0-03 失败诊断 | lifecycle、`training_recovery_api.py` | **已编码**：阶段、errno、异常类别、actor_kind、duration_ms、诊断 ID 写现有任务日志；409/503 不再一律误报不可重试；安全回执记录上次尝试时间、次数、退避与最新原因 |
| P0-04 读图竞争 | lifecycle、原 `TrainingEvidenceFileResponse` | **已编码**：重型复制/哈希只拿任务级维护锁，单文件原子替换和最终目录分离才拿原读图锁；已有图片响应仍在真实读图期间持锁，并验证 SHA |
| P0-05 前端未知结果 | `training-recovery-runtime.js` | **已编码**：POST 409/503/断网后保留“上次核验逻辑大小”并标为过期，禁用再次释放；必须成功执行新的 GET 后才允许明确确认 POST；切换任务仍按原 session/project fencing |
| P0-06 双 Worker | lifecycle、既有 `task_worker.py`/Scheduler | **已编码**：复用原 Worker 维护入口，新增每任务跨进程维护 FileLock，后台重型归档不得重复启动；忙锁正常跳过；重试指数退避至 1h、8 次持续 I/O 失败后暂停自动重型操作，人工明确重检可恢复 |
| P0-07 磁盘压力 | lifecycle | **已编码**：每次需要真实复制前要求系统剩余空间高于可配置预算加本文件字节；默认保留 2 GiB，环境项 `CHANG_LIAN_ARCHIVE_MIN_FREE_BYTES`；系统并发写入仍可能造成 ENOSPC，届时拒绝删除并给出分类 |
| P0-08 重复检查 | lifecycle | **已编码**：维护不再先单独全目录 `inspect` 后又执行 `cleanup`；候选任务先检查冷却回执，只有应执行者进入重 I/O |
| P0-09 早期失败无 Manifest | lifecycle | **仍待独立证明**：继续 `BUNDLE_MANIFEST_UNVERIFIED` fail-closed，不自动认领未知历史数据 |
| P0-10 双数据库跨域 | SQL Store、lifecycle | **已编码短锁**：任务 DB 保卫状态/消费者，版本 DB `BEGIN IMMEDIATE` 保卫版本身份，双锁只覆盖最终分离；真实高并发锁顺序/性能仍待 CI 与隔离验证 |
| P0-11 有界重试 | lifecycle | **已编码**：可重试原因与永久拒绝分开；持续 I/O 失败达预算后自动暂停，避免无限维护风暴，保持人工复核通道 |

## 4. 验收矩阵与实际证据

| 场景 | 新增/既有测试 | 当前结论 |
|---|---|---|
| 无关 WAL 写入仍可回收 | `test_unrelated_project_wal_write_during_archive_does_not_reject_cleanup` | 代码和测试已新增；**Python 未运行** |
| 当前训练模型版本撤回/替换拒绝 | `test_current_training_version_changed_during_archive_remains_protected`、原模型 SHA 门禁测试 | 已新增；**Python 未运行** |
| 已归档文件复用、断点恢复 | `test_stale_final_gate_reuses_previously_verified_archive`、`test_interrupted_partial_archive_reuses_verified_files_on_retry` | 已新增；**Python 未运行** |
| 低空间拒绝 + 503 阶段诊断 | `test_archive_disk_pressure_is_safe_and_diagnostic`、`test_workspace_api_reports_archive_oserror_stage_without_private_paths` | 已新增；**Python 未运行** |
| 原子分离后删除被中断 | 原 `test_delete_interruption_can_retry_without_retouching_originals`，本轮修正归档从 `work/.bundle-reclaim/manifest.json` 读取 | 已修复崩溃恢复路径；**Python 未运行** |
| 非法磁盘预留配置 | `test_archive_space_invalid_config_fails_closed` | 已新增；**Python 未运行** |
| 双 Worker 单重型归档、报告读锁可用 | `test_two_maintenance_workers_archive_once_and_report_reader_lock_stays_free` | 已新增；**Python 未运行** |
| 前端 503、重新 GET、禁止重复 POST | `tests/frontend/training-recovery-runtime.test.mjs` | **本地 Node 通过**（定向 34/34；与版本标记合计 42/42） |
| 前端其余不依赖供应商包的测试 | `tests/frontend` 中排除五个依赖缺失 Uppy/Annotorious 的测试文件 | **本地 184 个测试文件，1,462/1,462 通过**；非全量前端验收 |
| Python 语法 | `python -m py_compile` 三个后端模块及测试文件 | **通过**，但这不是后端业务执行测试 |
| Python pytest/FastAPI 单测 | `tests/unit/test_training_workspace_lifecycle.py` 和 API 故障注入 | **未运行**：当前执行环境没有 `pytest` 和 `fastapi` 依赖 |
| 完整 `npm test` | 项目原前端测试入口 | **未通过环境装载**：当前无 `@uppy/core` / `@annotorious/annotorious` 等 node_modules，不能推断测试失败或整体通过 |
| 1万～3万文件、两 Worker 进程、真实 Chrome、完整 GitHub CI | 原专项 CI / 隔离规模测试 | **待准确 SHA 触发并核验**，不得推断已达性能 SLA |
| 11-03 生产 503、97% 与 1.7 GiB | 仅由用户提供只读现场证据 | **根因及实际释放量待经批准的生产复测**，本轮没有访问或清理生产 |

## 5. 生产发布与安全回收步骤（本轮不执行）

1. 核对精确 GitHub 提交 CI、关键 Python/Node/Chrome 回归、预发布模拟磁盘压力与模型版本撤回；若失败先在开发分支修复。
2. 在批准维护窗口前只读检查 `df -h`、`df -i`、任务状态/lease/PID、模型证据、Manifest、Bundle/证据占用、归档完成凭据；单独记录现场日志诊断 ID。
3. 经批准部署代码后，优先单个已完成任务调用原 GET `/workspace` 核验资格。只有在最新结果 `eligible=true` 且证据完整时，才由明确的操作人确认 POST `/workspace/cleanup`。
4. 回收后检查 `work/bundle` 与 `.bundle-reclaim` 不存在，`evidence/bundle`、`outputs/`、`result.json`、正式 GT/原图仍可访问；报告误检/漏检图片经过身份及哈希验证。
5. 记录 `deleted_logical_bytes`、真实 `du` 和前后 `df`，不能将 1.7 GiB 直接报告为文件系统净增空间；记录 Web/Worker 心跳、I/O 和下一轮维护日志。
6. 如果再次出现 409/503，收集安全诊断 ID、阶段、errno、回执；不使用手动 `rm -rf`、不修改状态为成功、不跳过归档证明。

## 6. 未完成、回滚和边界

- `archive-proof.json` 是在原 ArtifactStore 中的可丢弃归档加速证据，不是新的任务状态数据库。若更换旧版代码，旧版本可忽略此证明；**不得人工删正式证据来回滚**。
- 不涉及正式 Schema 修改、任务恢复语义变更、共享缓存或远端 OSS 删除；保留未知历史 Bundle 拒绝策略。
- 无法从用户现有 503 HTTP 状态反推出精确 OSError；此次分类用于下次产生可诊断证据。
- 跨数据库最终双锁的真实高并发顺序、万级归档统计、进程级崩溃语义、极低空间环境、真实 Chrome/生产功能须继续验收；没有这些证据之前只能说开发候选，不得宣称全 P0 生产关闭。
- 本轮不触碰 `/data/platform-data`、生产服务或任务副本；发布/真实清理必须另外批准。

## 7. 提交记录

- 开发起点：本地原 `5406872`，GitHub 同树等价 HEAD `eaef1e2106e5f555d21012c4cfba6941d483a593` / `42.24.509`。只有长期分支 `feature/external-algorithm-publishing` 被允许更新。
- 当前目标：`42.24.510`，具体 GitHub 新 SHA、CI 结果、实际性能数值以推送与复核结果为准；不得引用旧 SHA 的绿灯。
