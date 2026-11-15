# 畅联云算法训练平台｜2D-1：已有 ONNX 文件的 CPU-only 实际校验试点

日期：2026-11-15  
唯一开发分支：`feature/external-algorithm-publishing`  
本轮准确功能 SHA：`16397cc04566f0570f796fee7b1129d2ae771238`  
生产部署：**NO-GO**

## 1. 背景

2C-3 已有真实 CPU 固定脚本的 systemd 执行及崩溃身份恢复，Ubuntu 24.04 全仓 23/23 通过。Ubuntu 22.04 systemd 249 缺少 `ExitType=cgroup`，后续已增加运行中 manager 版本准入，代码 SHA `228c9f30` 已 23/23 CI 通过。

真正的模型转换不只是 `Popen`：原 Node Agent 转换 Runner 包含冻结输入、任务租约、进程身份、终态、取消、进度、校验后的产物、对象存储上传和中央 CAS finish。不得一次性替换或建立第二套任务所有权。

## 2. 本轮交付

### 2.1 严格受限的业务 preflight（不授予执行权）

`platform_core/os_supervisor_onnx_cpu_pilot.py` 是单独的准入校验组件：

- 接受原业务合同 `MODEL_CONVERSION` / `object-storage-v1` / `target=onnx`，拒绝额外命令、设备、校准或其他字段。
- 仅允许 **已有单文件 .onnx → ONNX Runtime CPU 校验/复用**，绝不执行 `.pt` / `.pth` 导出，也不涉及 RKNN/Ascend/Sophon/TensorRT 编译器。
- 暂限 `fp32`、`batch=1`、`opset=12`、静态输入、`dynamic=false`、`simplify=false` 和指定的有限 `input_size`，上限 64 MiB。
- 校验源文件目录（本地可信 workdir 的 `input/`）、符号链接、文件名、源大小、下载 SHA256 和原始 trace SHA256 均一致。
- 返回字段始终声明 `production_launch_allowed=false`、`hardware_verified=false`、`trusted_stop_receipt_available=false`。即使准入 PASS，也不能作为 Supervisor grant 或产物发布依据。
- 这是 **preflight**，不是可用于防 TOCTOU 的不可变打开文件句柄；后续真实受信任 OS 执行必须另行冻结文件描述符、重验实际读取字节，并遵守中央租约。

### 2.2 真实 ONNX CPU Runtime 验证（非模拟图）

`tests/integration/test_os_supervisor_onnx_cpu_pilot_live.py` 构建真实 ONNX Identity 图，在隔离 GitHub Ubuntu job 内直接执行仓库原 `deployment_worker.py --job-dir`。完成后检查 `job.json` 为 `done`、manifest 为 `runtime_verified`、`onnx_export` 实为 `reused_existing_onnx`、输出文件 SHA256 等于输入及 ONNX Runtime 实际加载的 Provider 仅为 `CPUExecutionProvider`。

GitHub workflow 在 Linux 节点独立安装 ONNX 与 onnxruntime，不干扰 Windows Node Agent 纯合同测试。测试仅证明已有 ONNX 的 **实际 CPU 运行**，不证明 CUDA 设备节点可访问权隔离，也不代表 Supervisor `systemd-run` 调用模型工作流；这些仍需独立 OS 集成。

## 3. 本轮 CI 和安全边界

本轮新准确功能 SHA `16397cc0` 已触发 GitHub 工作流，**当前状态：待最终验证**，不得提前写 GREEN。上轮 `228c9f30` 的 23/23 PASS 不可冒充新 SHA。

本轮不修改 `node_agent_conversion_runtime.py`、中央 `tasks.attempt` / lease / GPU reservation、Worker 授权、A800/双4070 生产环境，亦不开放 StopReceipt、自动重排或前端功能。

## 4. 下一步准入顺序

1. 核查新 SHA 的 Python 编译、Ubuntu/Windows Node Agent 合同与真实 ONNX Runtime CPU 测试；失败时定点修复，并保留实际日志证据。
2. 完成 CPU Pilot 的**真实 Supervisor OS profile**安全设计，输入不能由 Agent 任意指定路径/命令/env；由受信任本地根目录中的冻结对象及当前中央 execution lease 授权；必须保留 `tasks.attempt` 和同代重入限制。
3. 单独验证日志进度迁移、cgroup 全后代停止、取消、中断、重启、多节点竞争和上传/确认/终态 CAS。没有真实可信 StopReceipt 就继续 HOLD。
4. Ubuntu 22.04 的 systemd 249 可用性需要独立安全实现和**真实隔离主机测试**，不可凭 Ubuntu 24.04 CI 外推。
5. 整套集成完成后，再在用户授权下做有限非生产试验；不得先触碰 A800/双4070 的生产执行路径。

