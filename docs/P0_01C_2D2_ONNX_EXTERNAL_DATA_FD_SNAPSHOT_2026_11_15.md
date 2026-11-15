# 畅联云算法训练平台｜2D-2A ONNX external_data 拒绝与 pinned-FD 隔离输入

> 2026-11-15 · 唯一开发分支 `feature/external-algorithm-publishing`  
> 本轮功能 SHA：`cee26a5c2a47d706ce35548d9b6840a4fd0a674b`；Windows 兼容修正 SHA：`bc67fb2a28692b56078348567599bc8cc8bdfc38`  
> 状态：**CPU Pilot 安全补强；Windows/全仓 CI 终态待核，生产继续 NO-GO**

## 一、风险、依据与范围

ONNX 的 `TensorProto` 可使用 `data_location=EXTERNAL` 与 `external_data` 指向模型文件以外的相对数据路径。只校验 `.onnx` 文件名、单个 SHA256、最外层 `graph.initializer` 不够：外部引用可能出现在节点 TENSOR 属性、GRAPH/GRAPHS 子图、SparseTensor 与训练相关 protobuf 子消息中。ONNX 默认按模型路径加载时可能解析这些外部数据；历史上亦出现 symlink traversal 安全公告（GHSA-p433-9wv8-28xj，受影响 1.19.1，1.21.0 修复）。

官方参考：
- https://onnx.ai/onnx/repo-docs/ExternalData.html
- https://github.com/onnx/onnx/security/advisories/GHSA-p433-9wv8-28xj

第二个风险是 TOCTOU：先计算文件 SHA256，随后正式 Worker 重新打开同名文件；两次操作中间文件内容可能已经被换掉。

本轮先修**受限 CPU 试点**，不修改生产模型上传、ONNX 全格式支持或 Node Agent 中央调度。

## 二、本轮真正实现

### 1. 全层 ONNX external_data 拒绝

`platform_core/os_supervisor_onnx_cpu_pilot.py` 通过 `onnx.load_model_from_string(model_bytes)` 在内存里解析 protobuf；其遍历基于 message `ListFields()`，不只遍历 `graph.initializer`。发现任一 `TensorProto` 的 `data_location=EXTERNAL` 或任一 `external_data` entry，立即 `CPU_ONNX_PILOT_ONNX_EXTERNAL_DATA_HOLD`。遇到缺失 ONNX parser、无有效 graph、错误 protobuf、嵌套深度或对象数量上限超过限额，也一律拒绝。

`onnx>=1.21,<2` 作为 Node Agent CI 测试解析依赖；正式 Node Agent 生产的 `legacy` 路径不要求此新 pilot 模块，也不会通过这项测试准入获得任何新权限。

### 2. 从同一个打开的文件描述符获取可核验字节

先限制受信任测试工作目录的 `input/`，再在单次打开后核验 `lstat`、`fstat` 的设备、inode、mtime/ctime、大小；使用 `O_NOFOLLOW`（可用时）拒绝符号链接，拒绝 `st_nlink != 1` 的硬链接；整个数据量限制 64 MiB；用实际读取的完整字节校验 SHA256，然后把**同一份 bytes**交给 ONNX parser。任何检测到的身份变化或摘要不匹配均为 HOLD。

### 3. 将验证过的字节用于实际隔离 Worker

新增 `materialize_cpu_pilot_snapshot()`，仅针对 CPU Pilot 的结果，在单独的快照目录独占创建 `verified.onnx`，采用 `O_EXCL`、`O_NOFOLLOW`（如 OS 支持）、完成字节复制并 fsync；不会从先前路径第二次读取文件。隔离真实 E2E 在原 source path 被替换后，仍调用**原有** `deployment_worker.py --job-dir` 处理这个经过核验的模型副本，最终核对 CPU Provider、ONNX manifest、SHA256 和执行结果。

### 4. 测试与 CI

- 单元：普通已有 ONNX、自定义参数拒绝、初始化权重、嵌套 GRAPH、TENSOR 属性、SparseTensor、training graph 的外部数据、无效 protobuf、硬链接、源文件校验后被替换、独占 snapshot 拒复写。
- 真实集成：CI 在 Ubuntu 24.04 上运行 `deployment_worker.py` 和 ONNX Runtime CPU Provider；原源路径验证后被替换，实际 Worker 使用冻结输入副本，而非原文件。
- [功能 SHA `cee26a5c` Node Agent push CI](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43714250767)：Ubuntu 主合同 **599 passed，2 skipped**；真实 ONNX CPU `1 passed`；原真实 systemd E2E `4 passed`。首次记录时 Windows、PR 和全仓其它工作流仍进行中，需严格基于同 SHA 的最终 GitHub 状态收尾。

## 三、不可越过的剩余边界

1. **尚未实现 OS 级只读不可变数据隔离**：快照文件与本地 CI 进程通常属于同一 UID，另一个同 UID 进程仍可能修改/删除/替换文件；当前机制只保证原路径替换不影响从已验证 bytes 构建的副本，不能声称彻底消除 TOCTOU。正式 Supervisor profile 需要 root-owned 受保护的冻结输入根目录、只读挂载或同等级内核隔离及实际并发攻击测试。
2. **ONNX protobuf 解析仍属资源敏感操作**：本轮限制模型文件字节、消息数量与深度，但这些限制在 protobuf 首轮解析后执行；正式生产还需资源限额、parser 隔离/超时，避免恶意模型耗尽宿主机 CPU/RAM。
3. **没有真实 GPU 或多后代停机证据**，不能从 `CPUExecutionProvider` 推导出 GPU 设备节点无法访问或 SDK 的所有后代均停止。
4. **没有正式中央 execution lease 重验、生产 Runner、日志进度对接、结果 prepare/upload/confirm/finish 事务链路**。`CpuOnnxPilotPreflight.production_launch_allowed=False`、`trusted_stop_receipt_available=False` 保留。
5. Ubuntu 22.04 systemd 249 仍不支持当前 `ExitType=cgroup` 固定测试后端；不得直接部署 A800/双4070 或将 GitHub 24.04 E2E 外推生产。

## 四、下一阶段：2D-2B 受保护 OS profile 设计准入

- 在独立 Supervisor 本地审计可信工作目录、root 权限、固定可执行、只读模型快照、OS resource limits、进程组/全后代退出、失败及取消的证据合同。
- 在独立非生产 Linux 环境使用有真实 GPU 设备节点的隔离条件证明 **CPU-only 对 GPU 访问为不可用**，而不仅设置 `CUDA_VISIBLE_DEVICES=-1`。
- 复用中央 `tasks.attempt`、当前执行租约、原签名 grant，严格拒绝未授权的工作目录与任意命令。
- 接通真实业务日志、产物 manifest 验证与对象存储上传/确认/中央 finish；错误和失联保持 HOLD，自动恢复及 StopReceipt 仍不上线。
- 完成再做独立准入和可回退灰度，未经用户授权不触碰 A800/双4070。


## 五、首轮 CI Windows RED 的实际原因与定点修复

- 初稿准确 SHA `cee26a5c2a47d706ce35548d9b6840a4fd0a674b` 的 Ubuntu Node Agent 主合同 **599 passed / 2 skipped**，真 ONNX CPU **1 passed**，真 systemd **4 passed**，均成功。但 Windows Node Agent 主合同在修改模型文件后的负例中因 `lstat()/CRT fstat()` 文件元数据不同而首先报 `FILE_IDENTITY_CHANGED_HOLD`，未进入预期 `ONNX_EXTERNAL_DATA_HOLD`；Windows 两个 workflow Node Agent 失败，不能称首版全绿。
- 已有最小修复 [`bc67fb2a28692b56078348567599bc8cc8bdfc38`](https://github.com/jorsamj/aixunlianpingtai/commit/bc67fb2a28692b56078348567599bc8cc8bdfc38)：Linux 继续比较设备、inode、文件大小、mtime、ctime 的连续性；Windows 在一个固定已打开 FD 上只用长度和完整 SHA256 比对进行内容准入，避免 CRT 文件状态快照差异。Windows 仍不获得生产运行、调度或 StopReceipt 权限。
- **新修复代码 SHA CI 待结束**，不得把之前的 Ubuntu 成绩或首轮 Windows RED 混淆成当前全仓验收结论。
