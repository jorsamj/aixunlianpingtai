# 畅联云算法训练平台｜P0-01C 2D-2B1：root-owned ONNX 冻结输入与真实 systemd CPU 沙箱

日期：2026-11-15（Asia/Singapore）  
唯一长期开发分支：`feature/external-algorithm-publishing`  
首版功能 SHA：`c865fbdb457221444c643a377272a85ae45b668f`；当前修复代码 SHA：`5ff0d81ed7e0c6c7e3247fc0f7707738548bbb74`  
状态：**隔离 CI 的 root/systemd 功能验证已通过；准确 SHA 全仓 CI 待终态；生产继续 NO-GO**

## 1. 背景与为什么不直接改正式 Runner

上一轮 2D-2A 已能从单个 fd 读取已冻结的 ONNX 字节，拒绝深层 `external_data`、pin 文件 SHA256，并从该份字节生成本地工作副本。但普通 CI 下生成的副本与业务 Runner 同 UID 时仍可被替换。这不足以在真实计算服务中建立受保护的输入。

当前 `os_supervisor_authorization.py`、`os_supervisor_journal.py` 的签名合同只支持 `fixed-cpu-v1`；`SupervisorService` 只允许该固定测试 profile，且正式业务 Runner 的默认 `legacy` 和 `supervisor-required` 禁用行为都不能改变。因此本轮实现的是**独立于 Agent RPC 的最小 OS 输入保护实验**，避免在权限链路不完整时接入真正 ONNX/训练任务。

## 2. 实际提交

新增 `platform_core/os_supervisor_onnx_cpu_systemd_pilot.py`：

1. **默认彻底拒绝**：只有隔离 CI root 显式构建 `IsolatedOnnxCpuSystemdPilot(isolated_ci_only=True)` 时才可启动；必须 Linux root、可信 /run 和 systemd PID1 v250+。该类从未注册到 Node Agent、SupervisorService、中央调度 API、生产任务工作器。
2. **root-owned bytes**：接受原 CPU 预检的受限模型 bytes，但不信任其结果布尔值；在 root 端重新解析 `onnx.load_model_from_string` + external-data 拒绝；系统自己生成随机 ID，不接受 Agent 可指定的路径/程序/环境/单元名。
3. **OS 持有输入**：`/run/changlian-os-onnx-pilot-<token>` root-owned 模式 0755；`verified.onnx`、`evidence.json` root-owned 模式 0444、文件创建 `O_EXCL`/可用时 `O_NOFOLLOW`，创建后读取并核验 inode、owner、大小、SHA256 和 mode。
4. **固定 systemd profile**：`systemd-run --system` 创建 `changlian-os-<token>.service`，仅执行内置 Python 标准库读取 `verified.onnx` 并对照 `evidence.json` 检查 SHA256；`DynamicUser/PrivateDevices/DevicePolicy=closed/PrivateNetwork/ProtectSystem=strict/ReadOnlyPaths` 和固定 CPU/内存/任务数量/运行时限；unit 属性由 root 生成，没有 Agent 提供的命令字符串。
5. **真实 OS 结果**：使用原 `FixedCpuSystemd.snapshot/inspect/read_log_page/verified_natural_exit` 检查原 InvocationID、cgroup 和 ExecMainPID、日志与自然退出码。服务不会因此获得“可信远程停机”的资格，`trusted_stop_receipt_available=false`。

新增单元测试 `tests/unit/test_os_supervisor_onnx_cpu_systemd_pilot.py` 与真实 CI E2E `tests/integration/test_os_supervisor_onnx_cpu_systemd_pilot_live.py`；Node Agent 工作流 Ubuntu 使用 `sudo` 和真实 systemd 启动，实际切换为 `nobody` 用户尝试覆写 root-owned 文件必须失败（非 Python 字符串模拟）。E2E 仅清理该次随机 CI unit 和目录。

## 3. 准确验收与未越过的边界

- [代码 SHA](https://github.com/jorsamj/aixunlianpingtai/commit/c865fbdb457221444c643a377272a85ae45b668f) 对应 [Node Agent push](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43716594457) 的 Ubuntu Step `P0-01C 2D-2B1 root-owned ONNX inside true systemd CPU unit` 已成功。其它 Windows、全仓 23 次 Actions 仍需核实，不得提前宣称全绿。
- **没有执行 ONNX Runtime 的图推理**：systemd 只读取真实 ONNX bytes、计算摘要并输出日志。真实 ORT CPU Provider 测试位于 2D-1 的独立普通 Worker E2E，尚未通过 root systemd unit 跑 ORT 模型。
- `/run` 位于易失 OS 启动周期；该试验不具备重启后独立输入恢复，**没有完整的中央 lease 绑定、任务结果回传、取消/全后代 SDK 设备退出证据**。即使 root-owned 文件对非 root 不可写，同特权 root 仍能改写；它不是不可变硬件安全存储。
- Ubuntu 22.04 systemd 249 不支持此固定 cgroup ExitType；**GitHub Ubuntu 24.04 测试绝不可当成 A800/4070 生产兼容性认证**。
- `PrivateDevices=yes` 与 `DevicePolicy=closed` 是进程隔离约束，但 GitHub 宿主没有真实 GPU 设备，**还不能声称 GPU 设备节点访问已做真实负例验证**。

## 4. 下一步实施顺序（2D-2B2）

1. **先以此准确代码 SHA 补齐全仓 CI 终态**；历史 2D-2A 前端 Annotorious 单 Job 已定向重跑，需核实其最终结果。
2. 确认固定 CPU 服务能以受信任的**固定 Python/ORT 安装包路径**执行已冻结 ONNX 模型，不允许自定义 shell/executable/cwd/env；在真实 Linux systemd 单元中完成 CPUExecutionProvider 推理。用专属低权限 worker/固定安装工件与日志/退出码联合验收，而不是复制普通 Worker 的 Popen。
3. 再复用原中央 `tasks.attempt`、同一 lease/challenge/签名身份，建立任务输入绑定与受信任进程日志/取消/终态；OS 只能提供安全观察，不能成为新任务 owner。
4. 必须真正验证 cgroup 后代、失联、异常、短时授权过期、GPU 设备隔离、OOM、产物 SHA256 和原对象存储上传 CAS 语义；证据不足仍 `UNKNOWN/HOLD`，StopReceipt 禁止开放。
5. 正式接线与 Ubuntu 22.04 兼容性必须各自独立准入；**未经授权不部署 A800/双4070，不触碰生产文件、数据库或服务**。


## 5. 真实 CI 初版 RED 与定点修复

- 初版 `c865fbdb` 在真实 Ubuntu 24.04 root/systemd 的新增 **root-owned ONNX model + DynamicUser** 测试已成功；文件非特权修改拒绝、systemd unit 原日志/identity/自然终态均验证。Windows `tests/unit/test_os_supervisor_onnx_cpu_systemd_pilot.py::test_fixed_root_owned_cpu_systemd_only` 失败，原因为 `build_fixed_onnx_cpu_argv` 内 Linux 路径被 Windows 的 `pathlib.Path` 重新格式化成 Windows 分隔符；没有修改生产业务代码，没有错误开放 GPU/任务执行权限。
- [`5ff0d81ed7e0c6c7e3247fc0f7707738548bbb74`](https://github.com/jorsamj/aixunlianpingtai/commit/5ff0d81ed7e0c6c7e3247fc0f7707738548bbb74) 将 `ReadOnlyPaths` 的 systemd 单元值固定为 POSIX `/run/changlian-os-onnx-pilot-<handle>`，保留单元测试和真 systemd E2E。**需要新的同 SHA Node Agent Windows、Ubuntu 和所有工作流最终 CI，不能把初版 Windows RED 忽略。**
- 上一阶段 2D-2A 功能 SHA `bc67fb2a` 23/23 CI **已最终全绿**（Annotorious 前端失败 Job 定向重跑在 attempt 2 成功）。
