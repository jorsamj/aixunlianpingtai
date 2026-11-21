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


## 真实代码提交与 CI 证据（2026-11-16）

- **真实功能验收代码 SHA：3b81f10438f3ddb9865e66d30d10918ec5e80f5c**（POSIX 命令路径、专用 journal 证据读取、动态用户输出目录清理、跨平台固定合同均已修正）。
- 该 SHA 的独立真实 PT/systemd 工作流：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43783700467 ，**SUCCESS**，11 个快速安全合同 **11/11 passed**，三个真实 Linux/systemd 集成 **3/3 passed**。
- 证据来自 **Ubuntu 24.04、systemd 255**，Torch 2.5.0+cpu、Ultralytics 8.4.127、ONNX 1.19.0、ONNX Runtime 1.22.1、NumPy 2.2.6；不是 mock、现成 ONNX Identity 图，也不是外部下载 PT。
- 随机初始化的可信 CI YOLO11n 模型源码 SHA256：e3dfbfc1b8aa7ded97c0235495752a0fd43c51a6536c489db701048045fb2106；实际 ONNX SHA256：2d39a84297d552ac3b6754a4155cc0073cee4a67180b9e8ee54814c817df07b5；大小 10,506,760 bytes；opset12；输入 [1,3,32,32]；输出 [1,84,21]。
- **同张量 PyTorch→ONNX Runtime 最大绝对差：2.288818359375e-05**，全部数值在 rtol=1e-3, atol=1e-3 下通过；ORT provider=CPUExecutionProvider，ONNX checker、无 external data、完整产物 SHA256/长度均通过。
- 记录了原始 systemd InvocationID、CPU cgroup/main PID、成功自然退出与重建 client 后复核；直接重放单位启动拒绝，篡改输入/PT 符号链接替换均拒绝。**正常退出不等于用于中央自动恢复的可信 StopReceipt**。
- 同 SHA Node Agent Executor：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43783699942 ，Ubuntu **846 passed / 2 skipped**、Windows **841 passed / 7 skipped**，API PASS；Windows portable cgroup 30 passed / 1 skipped。第二组 Node Agent、远程训练/转换等后端工作流也通过。
- 同 SHA 的 Frontend Runtime Stabilization：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43783699967 ，初次 3/3 浏览器分片的第 3 组在训练任务弹窗 1920×1080 wheel-scroll 断言失败：**124 passed / 1 failed**；其他分片及 frontend PASS。此失败与本轮 PT 模块没有代码修改依赖，**但全仓初次 CI 只能记为 23/24 SUCCESS、1 failure**；已单独重跑该失败 Job，结果须以新 attempt 实际状态核对，不能先宣称 24/24。

### 缺口仍然必须明确

此阶段只对**CI 自身生成、来源可信的测试权重**实现了隔离 systemd PT→ONNX 真实转换。PT 专用中央 challenge/lease/recheck/journal CAS **尚未与本探针连接为一个不可绕过的端到端受保护业务执行器**；真实模型输入下载与对象存储、Runner 生命周期、取消/超时/失联、日志重连、可信 StopReceipt、结果 prepare/upload/confirm/finalize/finish、CPU↔GPU 真实调度、Ubuntu 22.04/systemd249 及 A800/双4070 生产验证仍不可宣称完成。未授权任何生产部署、重启或任务数据修改。

## 最终重跑验收与本阶段结论（2026-11-16）

### 准确的 GitHub Actions 终态

- 本阶段**功能代码 SHA**：3b81f10438f3ddb9865e66d30d10918ec5e80f5c。
- 已按此 SHA 的 GitHub Actions head_sha 独立查询：**24/24 workflows completed / success；0 failure；0 pending**。其中包含专用 PT 导出、两组 Node Agent、远程训练/转换、素材、RKNN、浏览器等工作流。
- 唯一曾失败的 Frontend Runtime Stabilization 工作流 https://github.com/jorsamj/aixunlianpingtai/actions/runs/43783699967 首次执行在浏览器分组 3 的训练创建弹窗 1920×1080 滚轮测试断言处失败，分组初次 **124 passed、1 failed**；其余分组和前端构建成功。该失败 Job 单独重跑（GitHub run_attempt=2，job_id=133029333027），**125 passed（7.5m），结论 success**；整个 workflow 终态 success。**没有为这项测试修改前端业务代码，历史首次失败证据保留，不称为“首次 24/24”。**
- 真实隔离 PT→ONNX 验收：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43783700467 ：**3/3** Ubuntu systemd 真实集成、**11/11** 安全合同通过，实际 PT→ONNX 与 ORT CPU 数值验证通过（最大绝对误差 2.288818359375e-05）；带原 systemd 单元/InvocationID，自然退出；源文件哈希、大小、ONNX 数据结构及 SHA256 校验通过。
- 跨平台 Node Agent 验收：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43783699942 ：Ubuntu **846 passed/2 skipped**、Windows **841 passed/7 skipped**、API 与 OS CPU 隔离测试成功。

### 阶段验收及生产禁用界限

**2D-2D2B2B-2B 的独立可信 PT 导出 pilot、源输入篡改拒绝、ONNX Runtime 一致性及相应回归测试：PASS。**

**正式业务端到端受保护转换：未完成、NO-GO。** 中央 PT admission/launch CAS 尚未与此可信 PT systemd pilot 整合为不可绕过的完整业务执行器；未知来源 PT pickle 无法仅凭 SHA256 证明可信；尚缺业务真实模型来源与对象存储、租约中断/超时/取消/失联、可信 StopReceipt、持久日志重连以及原始 prepare/upload/confirm/finalize/finish 事务完整验证。CI Ubuntu 24.04/systemd255 的成功不能替代 Ubuntu 22.04/systemd249、A800 或双4070 的实际兼容与生产验收。

全过程仅修改允许的唯一长期开发分支；**没有部署/重启 A800 与双4070，没有改生产任务和数据，也没有切换任何正式转换执行开关。**
