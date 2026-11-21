# P2B-4A-2B Payload 安全发布：连续开发交付记录

本轮从 `aabffa49479a9b40f3c35d6fcd2414bad09519ea` 接续。开始和推送前 fetch 的唯一远端分支为 `feature/external-algorithm-publishing`，远端仍为该 SHA；没有覆盖他人提交。VERSION 保持 **42.24.592**。没有操作 A800、4070、生产配置或生产数据。以下为本地 Windows / Python 3.12.7 的实际结果，不能替代准确最终 SHA 的 Linux CI。

原三份未提交设计文档原样保留，不加入本轮提交。本记录补充实际实施结果；旧设计中“暂停重构”“尚未实现”、逐列比较整行等描述，不代表当前实现。

## 1. 阶段提交与范围

| 阶段 | 提交 | 实际交付 |
|---|---|---|
| P2A 修正 | `fe8f2bc4d13786e1c9f7acb737ae9dd7daaab933` | 已发布事实只读确认先于执行租约检查；确认不恢复写权 |
| P2B | `42973b6a92127728c74b9f86f4b4e7591cc3f3f4` | 部署 READY 不可变发布；受控读取、不可变证据、准备子任务输入基础 |
| P2C | `525b19653b86437c413487a9916d47dfac6f4c9e` | 训练创建 / freeze / READY 正式业务迁移 |
| P2C 恢复修正 | `569425752d05841de383f6bb48c1e38f858d2ada` | 同 operation 不同提案仍冲突；显式恢复已验证的 READY 收据 |
| P3 | `f0b1488671380f43d10a58e2431468c818f802ae` | 执行输入锚点、训练和 checkpoint 参数、远程正式 Test 晚期门禁 |
| P4 / 删除 | `cee767ac4c8659a075bc697dc33260bc802200ba` | 有界 Claim、语义快照、增量索引、删除墓碑及历史证据保留；补充 P2A 空 owner 只读确认 |
| 最终恢复边界 | `5f36dc759d9c4fdf299c46ddd75a696f3dd94a38` | 已处理历史门禁消息不随时间中止收尾，消费者重放保护保留；清理脚本 EOF 空行 |
| 交付文档 | 本文所在提交 | 实测 JSON、功能保留台账、基准脚本末尾空行清理；最终准确 SHA 由 Git 报告提供 |

没有逐阶段推送或手动启动旧工作流；前述阶段先保存本地提交，最终正常推送。P2A 原 SHA 的 CI 没有在本轮重新查询，不能宣称其全部通过。

代码文件按职责分组：

- 存储 / 发布 / Claim：`task_runtime/{artifacts,payload_publications,preparation_publication,repository,fenced_repository,worker,claim_candidates}.py`、`task_node_assignments.py`。
- 部署：`deployment/scenario_preparation.py`；保留原任务对、创建身份、原图 / 模型校验和运行时入口。
- 训练：`remote_training_tasks.py`、`remote_training_inputs.py`、`training_prepare_child.py`、`training_tasks.py`、`training_hardened_tasks.py`、`training_execution_inputs.py`、`training_material_usage.py`、`train_worker.py`、`checkpoint_validation_worker.py`。
- Agent：`agent_execution.py`、`node_agent_executor_runtime.py`、`node_agent_training_runtime.py`、`training_history_gate.py`。
- `app.py` 仅训练初始 Payload 发布、删除协调 / 已删除身份过滤与保护。没有改前端。
- 定向测试、`tools/benchmark_claim_pipeline.py`、本文与实测 JSON、功能保留台账。唯一 CI 文件改动 `node-agent-executor.yml` 为新增 helper / 单元测试路径触发和原 Job 测试清单，未删断言或改变测试标准。

## 2. 发布、读取、幂等与失败边界

原链路为可变 Payload 文件 + 任务指针修改，准备 I/O 与领取 CAS 之间可发生原路径覆盖。新链路为：

`创建请求 → 不可变 child input → 真实 child lease → 证据 / Payload / 收据完整发布 → Repository BEGIN IMMEDIATE → 父子身份、租约、门禁及 expected_ref CAS → COMMIT → 执行读取`

- 稳定 operation 由 task / project / kind / phase / expected_ref / expected parent attempt / 固定业务意图规范化计算，不含随机 Worker 代数。SHA256 永久编码在 ref；新进程可独立读字节重算。收据固定同一提案，普通重新提案不同内容必须冲突，不能覆盖或随机换 op。
- 文件、JSON、SHA、fsync、收据读取在 Task writer 外。文件发布沿用 P1 私有临时文件、完整写入 / fsync / 验证、同文件系统无覆盖硬链接发布。不引入跨模块文件锁。
- `read_json()` 对合法新版本 / 证据 ref 分派到完整性验证；legacy ref 显式保持旧读取。新版本缺失、损坏或非法保留路径一律报错，不能回退 `payload.json`。
- Repository 新发布接口的 owner 参数仍为必填。首次修改必须满足真实 RUNNING child 的 token / attempt / worker / 有效 UTC lease，以及训练 `trainprep_{parent}` 或部署 `{parent}-prepare`、同 project / kind / immutable child input；父 QUEUED、attempt、原 ref 和准备门禁也在最终事务重查。
- 已提交结果确认先验证原版本 / 完整收据 / operation / 必要父子身份，当前父 ref 必须恰为该版本。允许 child 已结束、过期、被接管或已归档，允许 parent RUNNING / 终态；显式清空的 owner 值可用于确认。只返回 ALREADY_APPLIED，不 UPDATE、不续租、不恢复旧 Worker。superseded ref 不能用旧收据确认当前发布。
- 文件存在但收据缺失、收据存在但 DB 未提交，均不自动成为当前 Task。正常恢复明确核验既有收据及原输入，再以当前合法 child lease CAS。提交 ACK 不确定时保留精确错误，重试同 op 检查结果；不调用 legacy 失败逻辑回滚已确认 READY。
- 部署创建暂存 `scenario/request.json` 仍为原创建恢复协议；不可把暂存当执行版本。READY 后当前 Task 引用不可变版本，重复创建读实际当前 ref。
- 训练业务严格执行 freeze 再 READY。freeze 发布不可变 input-freeze、snapshot、dataset-revision，保持 pending 门禁；READY 必须引用已提交的 training.freeze。通用 Repository READY 能力不是业务跳过冻结的路径。
- 训练恢复复用收据中的固定提案，先验证原证据和远程对象。已保存 READY 不能因为新时间戳 / 资源描述重新提案而隐藏 op 冲突；既有证据 ref 也不因重建 created_at 被无意义替换。不可恢复的真实提案冲突报错，业务重新规划不能自动随机换 ID。

## 3. 执行输入与正式 Test 历史

`actual claimed TaskLease → anchor_execution → execution-inputs/v1/attempt-N.json → trainer/checkpoint CLI 参数 → read_execution_inputs → 原版本和证据验证 → 原历史独立性门禁`

锚点绑定 task / project / **实际** attempt、payload ref / digest、freeze / snapshot / revision ref 与身份、history admission、算法 / 基础模型身份。锚点只能在真实当前执行下写入；同 attempt 不可覆盖。进程收到执行 ref、attempt、anchor ref 后，即使当前 Task 已重试、改 ref 或逻辑删除，历史核验仍使用该执行的原版本，不读当前 Payload 替代历史。

`train_worker.py` 和 `checkpoint_validation_worker.py` 的两个 `assert_frozen_formal_test()` 实际调用入口都传递锚点参数。缺失、错误、损坏锚点或新任务企图降级 legacy 均拒绝。旧任务继续原可靠 legacy 路径。训练执行所写的可变 snapshot / bundle 等缓存仍由原流程拥有，但新历史判断以已验证不可变证据为锚点。

远程 Agent 不访问中央 SQLite。现有监控循环为训练 / checkpoint 的正式 Test 请求服务，通过现有认证 manifest 端点请求中央核验；中央检查当前 Assignment / Execution 所有权，验证原锚点和历史，再次检查执行权后响应。请求 / 响应绑定任务、代数、ref、snapshot、新 nonce 和短有效期，消息上限 8 KiB，不含凭据；超时或拒绝阻断评分。原结果接受时的中央门禁也保留，没有新建后台服务或调度器。

最终审查另补已处理消息生命周期：监控循环看到同 nonce 已完成响应时只跳过重复授权，不因旧请求超过 60 秒中止收尾；消费者仍严格核验响应有效期，新 nonce 必须重新经中央核验。回归先真实复现过期错误，再证明旧已处理消息不停止监控且强制 nonce 碰撞也无法重放过期授权。

非 Payload 证据不是仅靠 Payload 名称就安全：新 freeze / snapshot / revision 使用内容地址 SHA、原内容身份算法、修订合同和 history admission 交叉验证。legacy 证据不自动迁移；缺失历史仍 fail closed，不能把无法证明的历史认定独立。

## 4. P4 扫描、公平性与最终事务

`Worker / Scheduler → Fenced OS observations → bounded readonly scan → capability / Payload / admission preparation → 单个最终 BEGIN IMMEDIATE → recovery 一次 → ≤32 语义重查和原准入 → GPU reservation + CAS / attempt+1 → COMMIT → advisory cursor`

- 原排序完整保留：priority ASC、queue_rank DESC、created_at ASC、task_id ASC。
- 页上限 64，总预算默认 256，允许比较 64 / 128 / 256，硬限制 64–512；准备最多 32。候选仅投影实际判断字段，SQL 按 Worker kinds 过滤，能力在准备前判断。无 OFFSET。
- Keyset 使用完整四键，拆成四个互斥、依次查询的范围，避免 OR 从队列开头过滤。对齐增量索引 `idx_task_claim_pipeline(status,priority,queue_rank DESC,created_at,task_id)`；旧索引保留。实测计划为索引搜索，无 TEMP B-TREE。
- 每次重新读取最多 64 条优先窗口，余预算从上次位置轮转，尾部后回绕一次；低预算也给轮转留下份额。准备配额对优先窗口 / 轮转分别预留，避免前面资源被阻塞时永远到不了后面。
- Cursor 按 repository 内 worker_id / kinds / capabilities 上下文隔离，非持久、非所有权。成功时停在实际领取候选；未领取时停在实际扫描位置；事务 / COMMIT 失败不推进。预取但未处理的页后半部不被跳过。
- 公平性是“每次优先窗口 + 后部最终可见”，**不承诺全局严格优先级**。窗口之外更优先的任务可能晚于轮转位置的可执行任务。新紧急任务或优先级提升会重新进入头部窗口；无永久快照。
- 可能刚过期的本地候选以有限只读预览纳入；最终恢复决定它能否真正变为 QUEUED。远程未确认停止不进入可抢占捷径。固定最终事务时间快照防止遍历时仅因时钟流逝把另一活跃资源当作空闲。
- 语义快照包括 task_id、project_id、kind、status、payload_ref、resource_key、required_capabilities、priority、queue_rank、created_at、attempt、stage、accepted、retry_of。progress、current_item、updated_at 等展示变化不自动拒绝 Claim。准备期间关键字段变化必须跳过旧候选。
- 原 PID / create_time / command_hash、未知进程检查阻断、GPU hold、远程 recovery_blocked_remote_agent_unverified、Assignment generation、lease token / attempt、原子 reservation 和 CAS 仍由原 Owner 实现。
- “单次 recovery”指 TaskRepository.claim_next 的最终事务。外层公开 recovery / OS 观察不是重复 SQL 的替代品，没有删除 Scheduler 安全入口。全局恢复扫描本身仍可能随 RUNNING / 过期记录增长，本轮没有把它改造成第二个协调器。
- 返回 / 物化候选数有硬上限；SQLite 对 kind 等残余条件的底层索引访问量、恢复 SQL 内部访问量、RSS 不宣称有相同常数上限。最终候选数上限也不等于任意第三方 admission 回调耗时上限。

## 5. 实际临时 SQLite 性能

同机同 Python / SQLite，隔离临时库；每个规模有相同排序与资源、全部缺能力，另设只有队尾可执行。单次样本、包含连接成本，不是生产 P95。原始逐项记录与 EXPLAIN 在 [实测 JSON](evidence/P2B_4A_2B_CLAIM_20261118.json)，脚本 `tools/benchmark_claim_pipeline.py` 可复现改后数据。

| QUEUED 数 | 原物化行数 → 新 | 原 Claim ms → 新 | 原 writer ms → 新 | 新 candidate SQL / 总 SQL | BEGIN / recovery 原→新 |
|---|---|---|---|---|---|
| 1,000 | 1000 → 256 | 13.439 → 6.775 | 6.368 → 0.195 | 5 / 9 | 1/1 → 1/1 |
| 5,000 | 5000 → 256 | 40.830 → 9.995 | 29.590 → 0.579 | 5 / 9 | 1/1 → 1/1 |
| 10,000 | 10000 → 256 | 103.401 → 9.844 | 77.085 → 0.266 | 5 / 9 | 1/1 → 1/1 |
| 20,000 | 20000 → 256 | 215.235 → 6.890 | 177.301 → 0.228 | 5 / 9 | 1/1 → 1/1 |

原缺能力场景 candidate SQL 为 1、总 SQL 为 5，准备回调均 0；新方案用少量常数查询换有界行物化及锁外准备，并不是声称所有 SQL 数都减少。writer 获取等待原 0.010–0.023 ms，新默认 0.009–0.028 ms；没有在该无竞争微基准中证明生产锁等待改善。数据库连接数未单独计量，源码正常改后为 reader + final writer；不虚构连接或内存数据。

| 总预算 | 1k 队尾首次可见周期 | 5k | 10k | 20k |
|---|---|---|---|---|
| 64 | 31 | 156 | 312 | 624 |
| 128 | 15 | 78 | 156 | 312 |
| 256（选用） | 5 | 26 | 52 | 104 |

上述静态缺能力数据下，20k 的 104 次轮询按未改动的 250 ms 间隔约 26 秒，另加 Claim 工作时间；不是所有动态 / admission 拒绝场景的普适最大墙钟时间。资源拒绝还受最多 32 次准备 / 最终准入约束；测试证明后部仍会得到机会。64 的重访太慢，256 保持小批量并改善轮转，未盲目拉大到 512。

原队尾场景一次领取为 2 BEGIN / 2 recovery / 1 preparation；新每周期最多 1 BEGIN / 1 recovery。队尾未到达前 preparation=0，实际领取周期=1。基准 preparation 是计数回调，**不是实际文件 I/O**；实际 Payload I/O 不持 writer 由故障注入 / 另一 SQLite 连接获取 writer 的回归证明。全拒绝 1000 个可准备候选的新用例实际准备 32，只有一次最终 BEGIN。

## 6. 安全删除与兼容

本轮按已授权安全删除收尾增加最小 `task_tombstones`，并将 Task schema user_version 4 升至 5；保留现有列和索引，没有迁移生产库或改产品 VERSION。墓碑不是可调度任务、不能拥有 lease，也不进入 get/list；记录已删除身份、原 ref / attempt / 行证据，避免物理保留目录导致任务复活或同 ID 重建覆盖历史。

- 终态 / 项目 / kind 与活进程检查保持。最终 DB 事务归档并删除当前 Task 与 reservation；未执行 / 未引用的 legacy 文件继续原物理删除。
- 协议目录、已执行任务、已有 snapshot / model 历史证据保留，不自动 GC；`ArtifactStore.delete_task` 在任何递归删除前检查全部保留区，根 symlink / junction 拒绝。
- 逻辑删除后列表、详情、日志与原操作入口不再暴露该任务；模型 / 历史证据独立读取继续可用。API 保持 deleted_ids / failed 等合同，附加 `audit_retained_ids`。
- 文件清理异常发生在 DB 删除已成功之后时，返回“已删除、证据保留”，不冒充整个删除失败。保留目录不能被 index / maintenance 重新发现为当前任务。
- 同 task_id 不可重建，Repository 事务内外检查，训练创建与部署创建也先阻断。归档准备子任务仍可供 ALREADY_APPLIED 身份确认，不能获得写权限。
- history coverage 看到已删除、曾执行 / 未知 legacy 训练时，不能把项目判为空历史。已删除新任务不能无锚点降级 legacy Test 核验。

正式空间回收仍需引用追踪、用户保留期限、模型 / 报告引用和备份政策。本轮没有给“永久保留”冠以最终产品方案，没有承诺磁盘自动释放，也没有自动执行清理。

## 7. 定向验证的实际命令与结果

以下命令均使用 `D:/python/python.exe -m pytest`，`-q --disable-warnings --tb=short`；未运行全仓 pytest 或全仓浏览器。没有执行真实 GPU 训练 / 推理 / 上传。

| 直接相关参数 | 结果 |
|---|---|
| `tests/unit/task_runtime/test_repository.py tests/unit/task_runtime/test_scheduler.py tests/unit/task_runtime/test_fencing.py tests/unit/task_runtime/test_gpu_recovery_fencing.py tests/unit/task_runtime/test_resource_fencing.py` | 152 passed, 1 skipped；之后增加的 3 个排序 / 回绕 / 拒绝预算用例分别 2 passed、1 passed |
| `tests/unit/task_runtime/test_artifacts.py tests/unit/task_runtime/test_connection_lifecycle.py tests/unit/task_runtime/test_sqlite_busy_recovery.py tests/unit/test_training_material_usage.py tests/unit/test_training_history_gate.py tests/unit/test_agent_execution.py tests/unit/test_node_agent_training_runtime.py tests/unit/test_node_agent_executor_runtime.py` | 151 passed, 5 skipped；之后新增大证据用例 1 passed |
| `tests/unit/test_task_node_assignments.py` | 73 passed |
| `tests/api/test_training_request.py tests/integration/test_remote_training_prepare_task.py tests/api/test_detection_creation_recovery.py tests/api/test_training_unified_task_overlay.py` | 首次联合 123 passed、1 failed；失败为新部署测试错误假定共享队列只有本项目；其他 107 个训练 / 恢复 / 删除用例通过 |
| `tests/api/test_detection_creation_recovery.py`（修正测试队列隔离后） | 17 passed，保留原创建 / READY / 不重复执行 / 摘要损坏不降级断言 |
| `tests/unit/task_runtime/test_artifacts.py -k large_frozen` | 1 passed：20,000 合成证据行 4,740,010 bytes，Payload 限制 1 KiB 仍能存证和独立重读 |
| `tests/unit/task_runtime/test_repository.py -k 'stable_task_id_tie or wrap_rediscovers'` | 2 passed，queue_rank DESC / 相同排序键 task_id 稳定顺序、跨周期回绕 |
| `tests/unit/task_runtime/test_repository.py -k denied_candidates_use` | 1 passed，1000 候选中最多准备 32，Payload 准备期间另一连接可获取 writer，最终只有 1 BEGIN |
| `tests/unit/test_training_history_gate.py tests/unit/test_node_agent_training_runtime.py`（最终门禁修正） | 45 passed, 1 skipped；随后最终 helper 文件单独重跑 10 passed |
| `tools/benchmark_claim_pipeline.py --budgets 64,128,256 --output <临时证据路径>` | 完成 24 组规模 / 场景 / 预算采样，全部队尾最终领取，无生产访问 |

六个 skip 是当前 Windows 运行环境下的能力 / 平台相关用例，不能写成 Linux 验证通过。上述结果为多次定向命令组合，不声称存在单次全仓绿色运行。

阶段内红→绿证据：优先窗口被无关 kind 占满的回归先实际失败，SQL 下推类型过滤后随 152 项通过；严格提案校验曾暴露 created_at 重建产生证据 ref 分歧，改为恢复原不可变证据后训练准备全体通过；共享临时队列测试问题独立修正，不改业务来让测试通过。

训练端到端用例实际执行真实准备 Handler、freeze→READY 发布、真实 parent claim、执行锚点和原历史门禁，并在当前 ref / attempt 改变及删除后仍核验原历史；另覆盖 READY 文件 / 收据已发布但 DB 未提交后的新 Worker 恢复、旧 Worker 无首次提交权、无重复模型上传。部署端到端用例从 HTTP 创建进入真实 child Handler、READY 后 canonical parent claim、不可重复执行和新版本篡改阻断；模型 / transport 使用隔离替身，不是硬件端到端。

P1 / P2A 既有定向用例继续覆盖 no-replace 跨进程竞争、版本与收据故障、进程退出留下孤立版本、文件 / hash / fsync 不占 Task writer、CAS 冲突、租约失权、提交 ACK 不确定等边界。普通测试不是掉电持久性实验。

所有本轮修改 Python 及新 scanner / benchmark 经 `py_compile`；唯一变更 Workflow 经 YAML 解析。最终执行 `git diff --check`、完整范围复核和暂存差异核查。基准脚本 EOF 空行检查项已清理，不留格式错误到最终树。

## 8. 功能保留与验收边界

| 合同 | 结论 / 证据 |
|---|---|
| 原导航 / 页面 / 按钮 / 前端参数和选择 | 源码保持一致；没有改 static / Vue，不重复浏览器验收 |
| 原 Task kind / status / 优先方向 / queue_rank / 重试取消 | 保留；Repository / Scheduler / API 定向回归 |
| Task / GPU / Assignment / Execution Owner | 原 Owner；最终事务原子，Assignment 与 Execution Lease 分离；73 项 Assignment 回归 |
| 训练 freeze / 标签 / GT / 素材身份 / 模型 SHA | 原安全检查保留，新文件是证据传输与版本协议；训练 API / prepare 回归 |
| 部署原图、模型、创建 UNKNOWN 恢复 | 保留原协议；17 项 API / 真实 Handler 回归 |
| Formal Test 晚期历史门禁 | 新执行按原锚点核验，远程经中央；未确认历史阻断 |
| legacy checkpoint / result / log 写入 | 保持原可变合同，未全量改成不可变 |
| 删除用户体验 | 当前任务消失，历史证据保留；已删除 ID 不可重用，附加保留列表；13 项相关 API 测试包含原批删合同 |

Windows 本地验证包括 NTFS 硬链接、独占创建、实际 fsync 调用、重启重读 / 故障注入和多进程竞争。Linux 代码沿用 P1 已声明的本地文件系统检查与目录 fsync，**本轮未在本地 Linux 执行**；其当前实现必须以准确最终 SHA 的 CI 结果为准。不支持网络共享 / 不支持硬链接后端静默降级；Windows 不承诺严格掉电目录持久化。同权限任意进程直接改文件不属于 Python API 可强制防御边界，验证会检测内容破坏。

待独立审计的边界：真实 A800 / 4070 / 多节点网络分区 / 掉电均未测；静态微基准不代表生产尾延迟；动态公平性没有墙钟 SLA；全局恢复仍是原扫描；自动 GC / 空间策略未启用；固定提案冲突的重新规划需显式业务处理；旧进程必须升级后才能使用新发布合同，不允许仍运行可覆盖保留区的外部任意写者。

本地验证通过 ≠ 提交推送成功 ≠ CI 通过 ≠ 专项最终验收通过。本记录提交时 CI 尚未查询。遵循根 AGENTS 的异步 CI 规则，最终推送后只查询准确新 SHA 的实际工作流一次，不手动重启、重复触发或把旧 SHA 成功结果迁移到新 SHA；未完成必须报告未验收。最终是否关闭由准确 SHA CI 与 ChatGPT 独立审计决定。

## 9. 回退与协作

不直接降级覆盖已版本化 ref。需要回退时停止新执行接入，正常 revert 相关代码提交并保留版本文件、收据、锚点和墓碑；旧实现不能读取协议 ref 时必须先采取兼容读取方案，不能随意把 DB ref 指回可变文件。新增索引和墓碑不自动删除。没有在生产演练回退。

实际委派使用 gpt-6.1-sol：部署入口盘点及新端到端用例；训练实际读取 / CLI 参数和小型门禁 helper；Claim / 删除只读盘点与基准脚本。主模型决定事务、所有权、保留语义、最终方案，逐项检查实际 Diff 并统一测试、提交和推送。基准 Agent 后续触及额度后主模型接管，修复并验证分页 / kind 窗口问题；不把额度中断计作 Agent 完成交付。没有让多个 Agent 改同一文件，没有让子 Agent 提交 / 推送。复用已完成审计与测试，未运行全仓测试。

最后另委派 gpt-6.1-sol 对 aabffa49..cee767ac 的 scanner / CAS / anchor / Agent 门禁作只读审查（已知已处理消息过期问题由主模型先行修复，不重复分析）；结果未发现其他已确认可操作问题。该审查没有编辑、执行测试或提交，不替代 ChatGPT 独立验收。

本轮完成后等待统一独立复核；不自动开展下一专项。
