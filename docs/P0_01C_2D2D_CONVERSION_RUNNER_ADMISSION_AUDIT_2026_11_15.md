# 畅联云算法训练平台｜2D-2D 正式模型转换 Runner 最小适配准入审计（仅方案、未接管）

日期：2026-11-15；长期开发分支：feature/external-algorithm-publishing。
审计性质：只读正式 Runner / Process Control / Supervisor 合同；不更改生产执行路径。生产 A800/双4070：NO-GO。

## 一、前置状态与闸口

- 本文引用的 2D-2C3B 最新功能基线：12824cbf6e57ad6e434e7789f356bb493ab53a6c；此前排队的 23 项 GitHub Actions **现已全部 completed/success（23/23）**，Node Agent Windows/Ubuntu/API 及真实 systemd E2E 均 PASS。
- 2D-2C3B 针对初次 CI 的两个可复现失败已做最小修复：取消后 HTTP 409 错误码断言；自然退出后的原始 journald 日志只读检索。新的 Ubuntu 真 systemd E2E 尚待执行。
- **CI 准入闸口已通过**：2D-2C3B Ubuntu/Windows/API、真实 nonroot Agent→root Supervisor→systemd E2E 已完成；允许下一步 **2D-2D1 独立受限适配开发与隔离测试**。生产配置及真实 MODEL_CONVERSION 接管仍需独立完整闭环验收和明确授权。
- 既有 CPU Supervisor 仅允许 supervisor-cpu-v1 / fixed-cpu-v1；中央授权不承认正式业务 conversion 资源键。无论隔离 E2E 是否成功，都**不能**将当前测试 profile 当作正式转换启动器。

## 二、已核实的正式 Runner 当前合同（代码事实）

### 2.1 任务、租约与数据流
- platform_core/node_agent_conversion_runtime.py 中 AgentConversionRunner.run() 只接受 MODEL_CONVERSION、schema_version=1、transport=object-storage-v1、target=onnx/rockchip。
- NodeExecutor 的中心权威仍是 tasks.attempt、原 worker_id、执行 lease、状态与结果确认；ExecutionLeaseMonitor 保持续租和取消 fence。不能引入第二套 attempt、任务 owner 或中央派单。
- 输入由带大小/SHA256 检查的下载合同进入 Agent 本地 workdir；RKNN INT8 还包含冻结校准样本与 snapshot 检查。Supervisor 不得直接信任任意 Agent 路径或临时环境变量。

### 2.2 原进程生命周期
- 现有执行路径为：_prepare_job → begin_process_launch 持久落盘/目录 fsync → assert_direct_remote_launch_permitted → launch_process(Popen) → persist_process_identity(PID/create_time/command_hash) → 轮询 poll 与心跳 → ProcessController.terminate_tree 核查后代 → 清除原 identity。
- 每个新任务前，_recover_persisted_processes() 会枚举未验证 launch intent 与旧身份；无法核验的启动或清理一律拒绝继续，而非继续启动第二进程。
- 该持久格式专属于 legacy PID，不可将 Supervisor 返回的 handle_id/JSON 放进 ProcessIdentity，也不可调用 ProcessController 去终止其他 UID 的受控 systemd workload。

### 2.3 日志、取消与结果
- legacy 使用 workdir/runtime.log 与 convert.log，通过 _forward_log_delta(文件 byte offset) 有界回传。Supervisor 用原 InvocationID 的 journald cursor；必须单独设计受控、可持久、重启后无重复/越界的日志桥。
- 取消、停机、lease fence 和异常均要求严格清理；Supervisor.stop 返回的 ACK、单一主 PID 退出或者 cgroup 仅看起来为空，均不足以签发可信 StopReceipt 或允许自动重派。
- 输出 ONNX 必须先 _verified_onnx（runtime_verified），RKNN 必须 _verified_rknn（converted_unverified）；其后本地 SHA256/长度 → prepare_result_upload → 不可覆写上传 → confirm_result_upload → begin_finalization → finish。Supervisor OS exit_code=0 **不能直接发布 SUCCEEDED**。

## 三、建议的正式适配模型（分阶段且最小改动）

1. **先做只读分类准入，不改 Runner 启动。** 对现有 _prepare_job 的命令、冻结输入、ULTRALYTICS export、ONNX Runtime、RKNN、calibration 和 Python 环境做 CPU/GPU/磁盘/网络权限审计。特别核验 YOLO.export 是否可能用 CUDA/加载 GPU 权重，不能因为输出 ONNX 就默认 CPU-only。
2. **受限、可信的转换 profile。** 由受保护 Supervisor / 受信任部署配置固定二进制、运行用户、工作根、输入快照 hash、输出目录、限制资源和可选参数；只允许中央授权中绑定的任务、attempt、lease/node/profile。Agent 只能传结构化有限字段和受保护 handle，不得传 shell、任意 argv/cwd/env/unit、签名密钥路径。
3. **增加独立的 SupervisedConversionHandle 适配层。** 提供 bounded status/poll、log page、request_stop、durable identity、重连同一原 OS handle。此层不是 Popen，不暴露 .pid/.kill；原训练/复核 Runner 不修改；Supervisor 不变成第二调度器。
4. **运行期 lease supervision。** 原 ExecutionLeaseMonitor 必须继续监测中央，发生取消/过期/失联要向受保护 Supervisor 发 stop 请求并等待**精确原执行边界的可信停机证据**；未知即 HOLD、保留中心 owner/GPU reservation，不可把异常吞掉后 finish 成功。
5. **完成之后才允许结果桥接。** 只有受保护原进程已核对自然终态、无遗留后代、原执行代数未变，才进入原 _verified_onnx/_verified_rknn + 上传确认事务。日志游标与业务日志偏移映射必须支持 Agent 重启、分页、零重复。
6. **专用 Linux 隔离 Agent 灰度**：先单一低风险转换 profile，分开验收成功、失败、取消、网络分区、续租失败、崩溃窗、重复 start、重启重连、冻结数据/产物 hash、upload confirm/finalization。默认仍 legacy，不启用 supervisor-required 生产配置。
7. **目标 OS 独立闸口**：当前 FixedCpuSystemd 依赖 ExitType=cgroup（systemd v250+）；Ubuntu 22.04 systemd249 不兼容。这不是通过删除属性或模拟终态可解决的，必须另定有真实后代停止证据的 v249 方案或经授权升级 OS 后重新验收。

## 四、接线边界及最小改动清单（未来实施，不代表本轮已修改）

| 模块 | 允许的后续变化 | 明确不允许 |
|---|---|---|
| os_supervisor_* 独立模块 | 真实、固定且可信的转换 profile / 只读运行态与日志 | 任意 shell、路径、Agent 自签名、第二调度 owner |
| node_agent_conversion_runtime.py | 最小选择 supervised handle 与原 lease/结果事务桥接 | 直接把 handle 冒充 Popen；绕过原 SHA/上传确认 |
| node_agent_executor_runtime.py | 需要时新建不同于 legacy PID 的 OS-handle 记录合同 | 修改既有 tasks.attempt、重用旧 PID schema 欺骗校验 |
| node_agent_supervisor_gate.py | 只有所有 stop/lease/结果 E2E 真通过后才允许专用能力选择 | supervisor-required 误当作可运行开关、失败 fallback |
| 训练/复核 Runner 与 app.py | 本阶段不修改 | 大重构、复制 CPU PoC 为 GPU 生产 |
| 生产 A800/双4070 | 本阶段不触碰 | 自动恢复、强制释放 GPU、生产服务重启 |

## 五、最小验收用例

- 正常启动→心跳→受限日志→自然退出→唯一已验证产物→prepare/upload/confirm/finalize/finish。
- 输入或校准快照篡改、源包变动、签名无效、旧 attempt、lease 轮换、中央取消：拒绝启动或阻断结果。
- 在挑战签发后但启动前取消；systemd 已启动但 ACK 丢失；Agent/Supervisor/中央断网；重启后同 handle 只观察不二次 spawn。
- 中断、子进程残留、SDK 设备句柄失联、无法签发 StopReceipt：UNKNOWN/HOLD，原 owner/lease/GPU reservation 保留。
- ONNX 的数值与运行时验证、RKNN 的 converted_unverified 区分、上传 digest 严格一致；不能凭退出码认定业务成功。
- 目标 Ubuntu 22.04/v249 要求真实隔离验证，不允许以 Ubuntu 24.04 v255 的结果替代。

## 六、当前决策

**2D-2C3B 已按精确 SHA 完成 23/23 CI 验收，可启动 2D-2D1 受限适配专项。正式 Runner 生产接管仍 NO-GO，不得绕过 legacy 进程租约、可信停止和结果事务。**
首次可证明成功的 root-owned OS 守护边界也不能直接推出 GPU 空闲/StopReceipt 信任。
在准确 2D-2C3B SHA 全绿之前，避免为了重复相同证据继续增加新 CI/PoC。


## 七、2D-2C3B 完整通过后准入更新（2026-11-15）

- 验收证据：`12824cbf6e57ad6e434e7789f356bb493ab53a6c`，全仓 23/23 SUCCESS；Node Agent 两轮 Ubuntu/Windows/API 均全绿，真正非 root Agent HTTP + root Supervisor + systemd E2E 在 Ubuntu 单独 PASS。见 `docs/P0_01C_2D2C3_REAL_HTTP_UNIX_SYSTEMD_LINK_2026_11_15.md`。
- **下一个实际开发单元（2D-2D1）**：先定义独立 `SupervisedConversionHandle` 与受限、受信任 CPU 输入 profile 的**适配合同及离线单元测试**；不触碰当前 `AgentConversionRunner.run()` 的实际 spawn、取消或结果发布路径，不增加业务前端功能。
- 2D-2D2 才根据 2D1 审计证据逐步接入真实 OS 执行，必须验证中央租约持续检查、原始唯一执行身份、StopReceipt 与原输出 SHA256/prepare/confirm/finalize/finish 完整链路。
- **Ubuntu 22.04/systemd249、GPU 隔离和可信停机依旧单独 NO-GO**。不能将 fixed-cpu-v1 的成功提升为 GPU training 或 production conversion 的授权。


## 八、2D-2D1 完成后的准入结论（2026-11-15）

- 2D-2D1 只读适配合同与输入 SHA256 预检已开发并在功能代码 SHA `aaaf108fccfc9a6cfd257e7bac98aaa02f029f41` 通过本 SHA 触发的 **22/22 CI 全绿**，含 Node Agent Windows/Ubuntu/API、真实系统 CPU+ORT 以及全部三组 Chrome。
- 本轮另由 Playwright 真 trace 定位并修复 Annotation first-history 空栈异常，已添加 100ms 快速首画真实浏览器回归，vendor patch 精确 SHA 与许可证保留，未修改 GT/审核 API。详见 `P0_01C_2D2D1_SUPERVISED_CONVERSION_READONLY_ADAPTER_2026_11_15.md`。
- **继续准入 2D-2D2 的隔离开发与测试，不准入生产启用。** 仍缺真实 CPU 转换执行命令信任边界、OS handle durable/reconnect、lease 持续监督、可信停止回执、正式业务结果确认与 Ubuntu 22.04/v249 支持；严禁因本次 CI 全绿而将生产 `supervisor-required` 打开。


## 九、2D-2D2A 完成、2D-2D2B 准入说明（2026-11-16）

- 已新增独立 platform_core/os_supervisor_conversion_lease_guard.py，复用既有 ExecutionLeaseMonitor.beat()，把原中央租约与只读 OS handle 观察逐次绑定；拒绝取消、撤销、状态未知、失联与跨任务代数。永久 HOLD 仅限本 Guard 实例；**未改变原 AgentConversionRunner 的生产调用链**。
- 功能代码 SHA 5aa7af6b38672647de7599f41823853ff8c2e22a：本 SHA **23/23 GitHub Actions success**。Node Agent Ubuntu 685 passed / 2 skipped，Windows 680 passed / 7 skipped；三 Chrome shard 128/130/125 passed，远程转换与训练也成功。详见 docs/P0_01C_2D2D2A_LEASE_BOUND_OS_OBSERVATION_2026_11_16.md。
- **准入下一步仅限 2D-2D2B 隔离设计/开发**：实际 CPU 模型转换可信命令、OS-side root profile、唯一执行身份重连、租约失效的可信停机及原结果 prepare/upload/confirm/finish 需逐项证明。GPU 设备约束、Ubuntu 22.04/systemd249 兼容与生产部署为独立 NO-GO；无新的生产启用授权。不得重复造独立调度器或第二套 attempt。


## 十、2D-2D2B1 CPU-only 原 OS 证据联调完成（2026-11-16）

- 新模块 platform_core/os_supervisor_onnx_cpu_evidence.py 通过类型/输入哈希限制、原 InvocationID/MainPID/cgroup、真实自然退出、最多 8 页原 journald cursor 和独立 CPU Identity ONNX 输出 oracle 联合检查；失败全部 HOLD。**不是新的执行器或可信 StopReceipt**。
- 准确功能代码 SHA 4495a44fb44f6ed6903b20cd1f659263bf3aa32b：**GitHub Actions 23/23 success**，真实 Ubuntu ORT/systemd 两项、Node Agent Ubuntu/Windows/API、远程训练转换和 Chrome 三分片均成功。首轮 test-double 的 InvocationID 判断职责错误已在测试代码中修复，生产系统未改。
- 下一阶段只允许 2D-2D2B2 在隔离环境设计**真正受中央短期授权的受限 CPU 转换 profile**；必须先划清 PT→ONNX 导出与现有 ONNX→ORT 推理校验的不同合同。不能复用 fixed-cpu-v1 生产签名授权去执行真实转换命令。可信 stopped/exited 证明、任务 lease 生命周期/输出确认、Ubuntu 22.04/systemd249 和 GPU 安全仍分别 NO-GO。
- 本轮未改生产应用、原 Runner、前端页面、GPU 设备、中央调度与 A800/双4070 服务器。


## 十一、2D-2D2B2A 完成后的准入结论（2026-11-16）

- 功能代码 SHA d5e0dc56326d962a49861bb89e6ce93992d8589f，**本 SHA GitHub Actions 23/23 completed/success**；Node Agent Ubuntu 791 passed / 2 skipped，Windows 786 passed / 7 skipped；远程训练/转换、真实 CPU systemd、Chrome 三分片均全绿。
- 新增 platform_core/os_supervisor_cpu_pt_export_admission.py 和配套合同测试，在不调用执行器的前提下按原 RemoteExecutionLease 固定 PT 源哈希、长度、task attempt、node/worker/lease 摘要和严格 CPU 导出参数。下载凭据与地址不进入冻结清单；**PT 是潜在 pickle，不解包、不执行**。旧 fixed-cpu-v1 签名不能用于 PT→ONNX；任何启动与发布仍 HOLD。
- **2D-2D2B2A 的开发+隔离 CI 可关闭，但不代表 2D-2D2B2 的真实 CPU 转换受保护启动已经完成**。下一步 2B2B 需复用同一中央 authority 的 profile-specific grant、root-owned journal one-shot CAS、真实小模型 PT→ONNX systemd 隔离导出；再论证停机证据及结果上传/确认，不新增第二调度器或新代数。
- 不改生产 AgentConversionRunner、Node Agent 执行入口、app.py、前端、GPU、在线中央任务与数据；A800、双4070 均无部署重启。生产 supervisor-required、自动恢复、GPU/Ubuntu22.04-v249 仍为 NO-GO。
