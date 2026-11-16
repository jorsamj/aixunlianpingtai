# 2D-2D2B2B-2B｜可信 YOLO PT→ONNX 真实 CPU/systemd 隔离验证（2026-11-16）

## 准入目标和基线

前一阶段代码 SHA cedd4198b903a4d09d6abad9012c1b19608bba1e，独立 CI 23/23 SUCCESS。上一阶段仅有中央重新授权与原 journal 单次 CAS，没有真正加载 PT 权重；已有 ORT/systemd 只证明现成 ONNX 图，不能误称完成 PT→ONNX 转换。

本次目标是在隔离 CI 内进行真正的 Ultralytics YOLO PT 加载、ONNX 导出及 ONNX Runtime 数值对照；独立隔离任务，不改生产调度与 Runner。

## 实际变更

1. platform_core/os_supervisor_pt_export_cpu_systemd_pilot.py：CI-only 独立真实 CPU 实验，仅在 explicit isolated_ci_only=True、Linux root、systemd>=250 才能调用；无中央 HTTP、SupervisorService、Node Agent、Runner 导入和生产开关。
2. 测试环境精确安装 torch 2.5.0+cpu、torchvision 0.20.0+cpu、Ultralytics 8.4.127、ONNX 1.19.0、ORT 1.22.1、NumPy 2.2.6；复制到 root-owned、不可被 Agent 写入的固定 CPU 虚拟环境。
3. 测试 PT 由固定 yolo11n.yaml 和 Ultralytics 的 model.save 在 CI 本地生成，无外部模型下载、不可接受 Agent 任意 PT。以 root-owned 0444 文件 SHA256/length 和只读 manifest 冻结输入。注意：哈希只能证明完整性，不能保证不可信 pickle 安全。
4. systemd 使用 DynamicUser=yes、DevicePolicy=closed、PrivateDevices=yes、PrivateNetwork=yes、ProtectSystem=strict、RestrictAddressFamilies=AF_UNIX、NoNewPrivileges、固定命令、固定 CPU 限额、内存及运行时间限制；单一随机单位；工作文件只读，输出仅写入独立 RuntimeDirectory；root-owned 一次性启动消耗标记防止重复派生。
5. 同单元执行可信 YOLO11n PT 加载→真实 ONNX 导出（batch1、imgsz32、opset12、非动态、非简化）→ ONNX checker→ORT CPUExecutionProvider。用固定 1x3x32x32 浮点输入比较 PyTorch/ORT 输出 shape、finite、max_abs、allclose(rtol=1e-3,atol=1e-3)；记录源与输出 SHA256、源尺寸、ORT 证据、systemd InvocationID、原 PID/cgroup 和自然退出。
6. tests/unit/test_os_supervisor_pt_export_cpu_systemd_pilot.py 验证不能启动的默认状态、固定命令及权限、非法 handle、返回证据篡改。tests/integration/test_os_supervisor_pt_export_cpu_systemd_live.py 验证真实 CPU 导出、无重复启动、输入被篡改/符号链接替换时拒绝。
7. 新的 .github/workflows/isolated-pt-export-cpu.yml 使用独立 Ubuntu 24.04 临时 GitHub VM。旧 Node Agent 工作流仅加入快速纯合同测试及语法检查，正式业务路径不受影响。

## 必须区分的验收结论

- 本阶段真实模型为随机初始化、来源受控的小型 YOLO11n，验证架构软件链与系统保护，不验证业务精度。
- 即使 CI PASS，也仅表明隔离 Ubuntu/systemd 与真实 PT→ONNX 软件工作流通过；中央 PT launch CAS **尚未连接该真实 systemd 执行器**，因此不能据此说受保护的真实业务转换已端到端打通。
- 不支持生产 PT 任意 pickle 加载，不具备可信 StopReceipt、断网/超时/取消生产恢复、完整 prepare/upload/confirm/finalize/finish 事务、Ubuntu22.04 systemd249、GPU 占用/多机调度现场证明。
- A800 和双4070 未修改部署、服务、业务任务或数据。生产仍 NO-GO；前端本轮无需修改。

## CI 状态

待按照新代码 SHA 的运行日志和现场输出填写，不能沿用前序 23/23。
