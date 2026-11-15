# P0-01C｜Ubuntu 22.04 systemd 兼容性与正式模型转换 Runner 接入前审计

日期：2026-11-15（Asia/Singapore）
唯一开发分支：`feature/external-algorithm-publishing`
上一轮已验收代码：`8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da`（23/23 CI SUCCESS）
本轮代码：`228c9f3092a66699b7d9210e8420858de4beed1b`（新 SHA CI 待最终核验）
总判定：**正式 MODEL_CONVERSION Runner 暂不接入；A800/4070 生产 NO-GO**。

## 一、systemd 确认的兼容性阻断

Ubuntu Jammy 22.04 的 systemd 是 249 系列（https://packages.ubuntu.com/jammy-updates/systemd）。
官方 systemd.service 文档明确 `ExitType=cgroup` 新增于 **v250**（https://www.freedesktop.org/software/systemd/man/262/systemd.service.html）。
现有固定 CPU-only Supervisor 后端采用 `ExitType=cgroup`、`RemainAfterExit=yes`、`Restart=no` 和 `InvocationID`/`ExecMainPID` 核验，因此仅在 Ubuntu 24.04 GitHub CI 测试通过不能证明 Ubuntu 22.04 可以运行，绝不能仅移除该选项降级模拟停机证明。

**本轮最小修复**：在真实 `FixedCpuSystemd()` 后端初始化时查询 PID1 管理器属性：`systemctl --system --no-pager show -p Version`；版本小于 250、未知、格式不可信、命令失败就拒绝初始化，且在任何 `systemd-run` 之前发生。读取实际管理器版本而非安装的 `systemctl --version`，避免软件包升级但管理器尚未重启的错误判断。严格解析测试覆盖 249/250/255、换行/恶意/无效响应和无任何启动动作；真实 Ubuntu systemd E2E 使用该真实检查。代码提交 `eaea72dc`，精确正则与换行修正 `228c9f30`。

该修复的目标是**不兼容即安全拒绝**，不是使 Ubuntu 22.04 兼容。若未来一定要在 22.04 接入，需设计不同于 `ExitType=cgroup` 的 v249 可靠完整后代停止证据机制，并在隔离 Ubuntu 22.04 实测，或通过正式批准的 OS/管理器升级路径验收。

## 二、正式模型转换实际执行合同

1. **中央唯一权威**：`platform_core/node_agent_executor_loop.py` 从中央 Node Executor 获取任务并开始原执行租约；任务 `tasks.attempt`、owner、lease 保留既有中央权威。当前 `os_supervisor_central_grants.py` 仅允许 `MODEL_CONVERSION` + 专用 CPU 测试资源键与 `fixed-cpu-v1`，不授权真正 ONNX/RKNN 业务 Worker。
2. **启动/崩溃恢复**：`node_agent_conversion_runtime.py` 用 `workdirs.begin_process_launch`、`launch_process`、`persist_process_identity` 的原 Popen 链路；`ProcessController.terminate_tree` 和启动意图记录共同管理异常/重复启动。`supervisor-required` 当前只拒绝 Popen，没有可运行的正式替代启动器。Windows 缺 Job Object 后代结束证据会保留 HOLD。
3. **运行/取消**：`ExecutionLeaseMonitor`、`_heartbeat`、`_assert_active` 和 `request_shutdown` 负责原 lease 续约、取消、停机。不能用一次 `inspect` 或 `poll()` 替代租约失效与安全清理。
4. **真实命令与资源**：原命令由节点本地 `ultralytics_python deployment_worker.py --job-dir` 产生，含受控工作目录、job.json、环境变量。当前 Supervisor 只允许运行固定短时 CPU 脚本，不接受任意可执行、cwd/env 或用户路径。`deployment_worker.py` 的 PT→ONNX 使用 Ultralytics `YOLO.export()`，尚没有系统层强制 CPU-only 和无 GPU 访问证明，**不能因为格式为 ONNX 就当作零 GPU 任务**。
5. **日志与产物**：原 Runner 使用 runtime.log 与 `_forward_log_delta` 文件偏移；Supervisor 使用按 InvocationID 过滤的 journald cursor，两者日志合同不同。ONNX 必须 runtime_verified/manifest/唯一文件，RKNN 仅 converted_unverified，需要后续板端硬件复核；结果上传须 SHA256、长度、不可覆写、prepare→upload→confirm→begin_finalization→finish，不能仅凭 OS exit=0 发布 SUCCEEDED。
6. **停机安全**：不能用 leader 退出、systemctl stop ACK、单个 PID 消失替代 cgroup 全后代与 SDK 设备使用的终止证明；无法核实即 UNKNOWN/HOLD，且保留中央旧 owner/GPU reservation。

## 三、为什么不在本轮直接接入真实转换

缺口包括：在目标 OS 上可运行的严格 OS 进程边界；最小、固定且可信的转换 profile；真实冻结数据/文件权限；可观察的 CPU/GPU 访问；进程关闭、日志分页和任务终态桥接；原任务执行 lease 的启动时再校验；以及各种崩溃窗口与 SDK 子进程实际 E2E。
强行替换 `launch_process` 可能绕过当前产物校验/取消流程，反而令原本可靠的 fail-closed 失效。本轮只做兼容性防护与接入前审计，不改 `node_agent_conversion_runtime.py`、中央 TaskRepository、前端或 Worker 部署。

## 四、下一轮最小验收顺序

1. 以本轮准确代码 SHA `228c9f3092a66699b7d9210e8420858de4beed1b` 的 Node Agent Windows/Ubuntu/API 与 Ubuntu 真 systemd E2E、Portable Deployment、全仓 CI 最终状态决定是否验收；当前仅代码已提交，不能先标 GREEN。
2. 在不访问生产的前提下设计明确的有限 CPU-only 模型转换 profile，先审计 `YOLO.export()` 是否可能触及 GPU，不接受 Agent 自定义可执行路径或任意 shell。
3. 在隔离宿主机验证原 lease 和同代重入、systemd v249 与 v250+ 差异、后代退出、取消竞态、日志/冻结输入/哈希确认、结果只发布一次。
4. 成功后再做一个隔离真实转换纵向切片；生产 A800/双4070 仍须显式授权，继续禁止自动恢复、自动重派、强推/合并 main/Release。
