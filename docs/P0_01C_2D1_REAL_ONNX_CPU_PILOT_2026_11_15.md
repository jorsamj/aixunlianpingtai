# 畅联云算法训练平台｜2D-1：已有 ONNX 文件的 CPU-only 实际校验试点

日期：2026-11-15  
唯一开发分支：`feature/external-algorithm-publishing`  
本轮准确代码 SHA：`4bd8d6e2701d5d597006a44c31942ab5d32224d2`（首轮 `16397cc0` 的具体拒绝码异常包装已定点修复）  
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

本轮修复 SHA `4bd8d6e2701d5d597006a44c31942ab5d32224d2` 的 [Node Agent push run 43712286657](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43712286657) 的 Ubuntu、Windows、API 三 Job 均 SUCCESS：Ubuntu 主合同 **591 passed/2 skipped**，**真实 ONNX CPU Runtime 1/1 PASS**，真实 systemd E2E **4/4 PASS**。该**准确代码 SHA 全仓 23 次 GitHub Actions 全部 completed/success**，另有 [Node Agent PR run 43712291447](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43712291447)、[Portable Deployment 43712291391](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43712291391)、[Frontend Runtime Stabilization 43712286650](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43712286650) 均在第一次运行完成 SUCCESS。上轮 `228c9f30` 的 23/23 PASS 不可冒充新 SHA。

本轮不修改 `node_agent_conversion_runtime.py`、中央 `tasks.attempt` / lease / GPU reservation、Worker 授权、A800/双4070 生产环境，亦不开放 StopReceipt、自动重排或前端功能。

## 4. 下一步准入顺序

1. 核查新 SHA 的 Python 编译、Ubuntu/Windows Node Agent 合同与真实 ONNX Runtime CPU 测试；失败时定点修复，并保留实际日志证据。
2. 完成 CPU Pilot 的**真实 Supervisor OS profile**安全设计，输入不能由 Agent 任意指定路径/命令/env；由受信任本地根目录中的冻结对象及当前中央 execution lease 授权；必须保留 `tasks.attempt` 和同代重入限制。
3. 单独验证日志进度迁移、cgroup 全后代停止、取消、中断、重启、多节点竞争和上传/确认/终态 CAS。没有真实可信 StopReceipt 就继续 HOLD。
4. Ubuntu 22.04 的 systemd 249 可用性需要独立安全实现和**真实隔离主机测试**，不可凭 Ubuntu 24.04 CI 外推。
5. 整套集成完成后，再在用户授权下做有限非生产试验；不得先触碰 A800/双4070 的生产执行路径。


## 5. 首轮 RED 与修复记录、不可跳过的安全准入

- 首轮代码 `16397cc04566f0570f796fee7b1129d2ae771238` 的 Ubuntu Node Agent 主合同为 **590 passed / 2 skipped / 1 failed**。失败是边界文件拒绝时将 `CPU_ONNX_PILOT_FILE_BOUNDARY_HOLD` 包装成通用 `CPU_ONNX_PILOT_FILE_UNAVAILABLE_HOLD`；由于 `GrantRejected` 继承 `PermissionError/OSError`，被宽泛的 `except OSError` 捕获。即使安全上仍拒绝，也丢失了准确错误码。已在 `4bd8d6e2` 精准补 `except GrantRejected: raise`，测试均保留，没有关闭断言。
- 目前只校验文件名、工作区、文件大小、SHA256，不解析所有 ONNX graph/subgraph 的 `external_data` 引用，也没有冻结文件描述符和完整的防 TOCTOU 保障。这些缺口在下一次正式 Supervisor OS profile 接线前 **必须单独实现并做负例实测**；不得仅凭文件 preflight 通过就认定安全可启动。
- 此前的真实 ONNX 模型 CPU 运行已通过，但它使用标准非特权 GitHub subprocess，**不是**经 root-owned Supervisor 接管执行、也不是可信 OS cgroup StopReceipt。CPU Provider 验证不等于完全阻止系统 GPU 设备节点访问。

## 6. 准确 SHA 最终验收与下一阶段

- **功能 SHA `4bd8d6e2701d5d597006a44c31942ab5d32224d2` 对应 23/23 Actions workflow runs 完成并全部 success**，本轮无待定/失败项；初次 `16397cc0` 的文件拒绝码 RED 保留在第 5 节历史记录，不能混淆两次 SHA。
- 真实 ONNX CPU 校验执行只是**现有业务 Worker 在隔离 CI 的 smoke test**。它没有经独立 root-owned Supervisor 的 CPU profile 运行，也没有进行正式对象存储上传/中央 finish，更不具备可信 StopReceipt。
- 下一步应优先封堵 ONNX 图的 `external_data` / 嵌套子图、不可变文件描述符与 TOCTOU 问题，然后设计**仅受信任 job 根目录+受签名 grant 与原 task attempt/lease**的 Supervisor profile，验证取消、日志、OS 后代退出、发布/恢复 CAS。Ubuntu 22.04 systemd 249 仍需单独兼容设计和真实系统验收；A800/双4070 生产 NO-GO。
