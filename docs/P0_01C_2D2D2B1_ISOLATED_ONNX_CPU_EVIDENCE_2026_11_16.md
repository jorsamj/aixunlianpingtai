# 2D-2D2B1｜真实 ONNX CPU 执行联合证据（2026-11-16）

## 范围和原则

本专项承接已在准确代码 SHA `5aa7af6b38672647de7599f41823853ff8c2e22a` 验收通过的 2D-2D2A。唯一分支 `feature/external-algorithm-publishing`。**不修改生产 Agent、原转换 Runner、中央任务、任务数据库、GPU 及前端**，不部署 A800/4070，不增加一个新的调度器或执行代数。

针对 2D-2D2B，首先完成可独立验证的 CPU 模型**推理/检验**联合证据，仍未进行 PT→ONNX 导出。它是独立的受保护运行验证，不是正式 MODEL_CONVERSION 接管；不授权生产打开 `supervisor-required`。

## 现有组件与差距

已有 `IsolatedOnnxOrtSystemdPilot` 可在 root-owned、受保护、固定 Python/ONNXRuntime 的 systemd 单元读取真实 ONNX 并执行 CPUExecutionProvider；`FixedCpuSystemd` 可核实原 InvocationID/MainPID/cgroup 的自然退出，并按精确原 InvocationID 查询 journald。此前相关证据分别在集成测试中验证，缺少共同核验的数据合同。原始冻结 ONNX SHA256、受限根目录和输出测试 oracle 必须与同一次 OS 运行证据关联，而不是仅看退出码。

## 实际改动

- 新增 `platform_core/os_supervisor_onnx_cpu_evidence.py`，唯一公开函数 `verify_isolated_onnx_cpu_evidence`；明确只接收 CI 固定 ONNX 验证 profile 的 `FrozenOnnxInput`、`VerifiedOnnxBytes`、root-owned `StagedOnnxCpuPilot`、根侧首次 OS snapshot、原 `FixedCpuSystemd` 实例与独立输出哈希 oracle。
- 对 SHA256/长度/来源上界、固定 stage handle 及 /run 目录、原 unit/InvocationID/MainPID/cgroup、root 返回的保护标志进行严格一致性检查；异常先 HOLD、不触碰 OS。
- 不信任 Agent 提供的终态字符串；调用已有 `verified_natural_exit` 从原 OS 校验同一个 systemd execution、cgroup 和 exit_code。只接受 `exit_code=0` 且 unit_result=success、ExitType=cgroup 真证据；并强制 `trusted_stop_receipt_available=False`。
- 从已有 `FixedCpuSystemd.read_log_page` 取原 InvocationID 对应 journald，最多 8 页、每页 8192 字节，必须每次游标推进且最终返回空页；防止重游标、分页不完整与巨大输出被当成成功。
- 对单条 `changlian-onnx-ort-result` 证据再做原模型 SHA256、CPUExecutionProvider、ONNX Runtime 固定版本、固定 [1,3,32,32] shape 和独立输入输出哈希比对。此输出 oracle 仅用于 **Identity ONNX CI 固定测试模型**；**不能**由不可信 Agent 的任意值来代表生产模型精度验证。
- 返回只读 `IsolatedCpuOnnxEvidence`，记录 task_attempt、source SHA256、original unit/InvocationID/MainPID、输入输出 SHA256，但 `model_was_converted` / `central_lease_verified` / `business_result_verified` / `trusted_stop_receipt_available` / `automatic_reassignment_allowed` / `result_publish_allowed` / `production_launch_allowed` 全部明确 False。结构不是签名、不是中央结果事务、不是可信停机回执。
- 新增 `tests/unit/test_os_supervisor_onnx_cpu_evidence.py` 覆盖正常执行、跨输入身份、原 OS 身份篡改、终态伪造、stop ACK 冒充、游标重复、分页过量、非 CPU/provider 或推理摘要不一致等。接入原 Node Agent Windows/Ubuntu CI。
- 扩展原真实 Ubuntu root CI `test_os_supervisor_onnx_cpu_ort_systemd_pilot_live.py`：运行真实 Identity ONNX → real ORT CPU → natural terminal → 重新构建 root backend → 通过联合证据合同；CI 任务租约对象为**明确隔离测试元数据**，不是中央签发的授权。

## 安全禁区与不足

1. 当前 `fixed-cpu-v1` 中央签名合同**不能直接授权**这个 ORT profile；这次根侧 CI 运行与原中央租约尚未形成原子启动合同。不能宣称真实 MODEL_CONVERSION 的中央联动已完结。
2. 不能因为有证明自然退出，就宣称对被取消、崩溃、网络隔离的进程有 StopReceipt；现有受保护 systemd249/Ubuntu22.04 兼容问题尚未解决。
3. 已有 ORT worker 是**执行现成 ONNX 推理检查**，不是把 PT 权重转换为 ONNX，更不是任意 YOLO/RKNN/GPU 的正式结果审核。必须在后续实施可信固定的 PT→ONNX profile、结果分离验证、中央 prepare/upload/confirm/finalize/finish 才可能进入生产准入。
4. 没有必要增加前端可点击开关；前端任务状态仍来自唯一中央任务权威。若后续要展示执行边界诊断，必须保证真实业务 API 可区分 HOLD、原 OS identity 和已验证的停机证据。

## 验收闸口

本次代码及真实 root/systemd E2E 需以**本轮准确提交 SHA** 完成 GitHub CI。未见所有结果前不宣称全绿。禁止通过 skip、增大超时或放松 root/系统权限来使其通过。生产 A800/双4070 完全不操作。

## 下一个阶段

2D-2D2B2：明确由可信中央生成、root 侧受保护的 CPU-only 真实模型转换 profile（区别于原 `fixed-cpu-v1`）；先证明单次 OS handle 持久身份、启动前中央授权重检和取消后的真实停机证明，再逐步桥接原上传/结果事务。未经独立硬件/OS 验收不得接管 GPU 转换、自动重派或生产部署。


## 首轮 CI 审计修正（2026-11-16）

提交 `62e1d747c6550a7fbaa9871824e4a893e00ea6d9` 的首次 Ubuntu 合同测试给出 **729 passed / 2 skipped、1 failed**。失败仅为新增模拟 OS 的负向测试对“替换成合法格式的 InvocationID”的期望不正确：调用应进入原 root/systemd backend，由其检查是否等于真实 InvocationID，而不能凭 `[0-9a-f]{32}` 格式直接判断身份。修复针对 CI test double：替换合法但不属于原 OS 的 InvocationID 必须由 FakeRootOS 返回 `CPU_SYSTEMD_INVOCATION_REPLACED_HOLD`；该用例断言**确实触发精确原单位核验、且不读取任何日志、不签发业务结果**。其余明显非法的字段仍要求在调用 OS 前拒绝。生产 root backend 原有 `inspect(unit, expected_invocation)` 已执行真实比对，**没有修改或放宽任何业务安全校验**。新 SHA 必须再次单独验收。


## 最终 GitHub Actions 验收记录（2026-11-16）

**准确代码 SHA：4495a44fb44f6ed6903b20cd1f659263bf3aa32b。**
已按此 SHA 调取 GitHub Actions 结果，**23/23 个工作流全部 completed/success，失败 0、取消 0、排队 0、运行中 0**；没有复用上阶段成功记录。

- Node Agent Executor 主工作流：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43773436439 —— Ubuntu、Windows、API 三个 Job 全 SUCCESS；另一次同 SHA 工作流 https://github.com/jorsamj/aixunlianpingtai/actions/runs/43773430818 同样全绿。
- Ubuntu 合同 730 passed / 2 skipped；Windows 合同 725 passed / 7 skipped。新增 OS 身份、冻结模型、日志游标、自然退出、CPU ORT 输出 oracle 等正反用例纳入上述合同。
- Ubuntu **真实 ONNX Runtime CPU/systemd：2 passed**，包括真实 Identity ONNX 推理与联合证据核查（根侧再开 backend、调用原 InvocationID 的真实自然退出及日志核验）；原 root systemd 生命周期 4 passed，非 root Agent → HTTP → root Unix Supervisor → systemd 1 passed。
- 远程模型转换业务回归：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43773436563 —— SUCCESS；远程训练：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43773436451 —— SUCCESS；其余工作流全部成功。
- 前端：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43773430821 —— frontend + Chrome 三组全部通过：shard 1 为 **128 passed**，shard 2 为 **130 passed**，shard 3 为 **125 passed**。本轮无前端页面或资源修改。

### 初次失败与最终修复

首轮 SHA 62e1d747c6550a7fbaa9871824e4a893e00ea6d9 的 Ubuntu 单测出现 1 failed / 729 passed / 2 skipped。原因：测试桩错误假定另一个**格式有效**的 InvocationID 应直接在本地拒绝。真实系统只有 root-owned systemd 后端才能证明是否为原 InvocationID，不能靠正则格式识别身份。
修复 SHA 4495a44f 在**测试桩**中模拟真实后端的 InvocationID 比对和 HOLD，测试仍要求不读取他人日志。没有修改生产代码权限、没有跳过负向测试。该 SHA 的真实 E2E 和全仓 CI 已完整通过。

### 阶段关闭判定

**2D-2D2B1：隔离 root-owned 固定 CPU ONNX 推理联合证据验收 PASS。** 可进入下一阶段 2D-2D2B2 的隔离研发，**但正式业务转换、可信停机与自动恢复仍 NO-GO**。

这不是 PT→ONNX 模型转换，也不是受中央授权的真实生产任务。CI 中用于关联冻结模型的 RemoteExecutionLease 仅为显式测试夹具；返回的 central_lease_verified、business_result_verified、model_was_converted、trusted_stop_receipt_available、automatic_reassignment_allowed、result_publish_allowed、production_launch_allowed 均为 false。未完成真正受保护 profile + 启动前中央 regrant + durable handle + 可信 stop + 原始结果上传事务前，禁止开启 supervisor-required 或进行线上 A800/双4070 改动。
