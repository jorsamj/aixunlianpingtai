# 2D-2D2A｜中央租约与受保护 OS 执行观察联动（2026-11-16）

代码仓库：jorsamj/aixunlianpingtai
唯一长期开发分支：feature/external-algorithm-publishing
前置已验证代码 SHA：aaaf108fccfc9a6cfd257e7bac98aaa02f029f41（22/22 GitHub Actions SUCCESS）。
前置文档 HEAD：0a654a3f4418703c027790c7a3042802e9089d0e（仅文档，不改变已验代码）。

## 审计决定

当前平台已有：
1. 中央任务的 tasks.attempt、worker_id、lease_token、heartbeat、cancel_requested 以及原 NodeExecutorClient / ExecutionLeaseMonitor。
2. Supervisor root-owned SQLite journal 的同 attempt 唯一 OS handle、启动前 CAS、真实 systemd InvocationID/MainPID/ControlGroup 持久身份、终态与原 InvocationID 日志读取；重连走原 inspect，UNKNOWN 不允许重启。
3. 独立的固定 CPU / ONNX Runtime systemd 隔离测试，以及 2D-2D1 模型冻结 SHA256、只读 SupervisedConversionHandle。

**不得再建立第二套调度所有权、Heartbeat Worker、任务代数或 OS 执行真相。** 真正缺少的是运行中两个信任域的逐次关联：中央租约是否仍有效与 OS 观察是否仍对应原任务。且现有 StopReceipt、正式转换结果事务和 Ubuntu 22.04/systemd249 兼容性尚未满足。

## 本次受控实现（2D-2D2A）

- 新增 platform_core/os_supervisor_conversion_lease_guard.py，只读 SupervisedConversionLeaseGuard，不导入到生产 Agent、Runner、app.py 或设备部署入口。
- 构建时必须使用**同一个 RemoteExecutionLease 对象**、已绑定的 SupervisedConversionHandle、现成 ExecutionLeaseMonitor；对 task/attempt/node/worker/lease SHA256/OS generation 进行身份核对。拒绝改写原任务代数、跨节点/跨 lease 重绑。
- 只复用现有 ExecutionLeaseMonitor.beat()，**不调用 start() 启动后台续租线程**。拒绝带 legacy 进程 kill 回调的 monitor，避免失效回调绕过 Supervisor 可信停止能力。
- 每次 OS observe_once 或 read_log_page 前，均执行中央心跳：仅明确 cancel_requested=false 且 task.status=RUNNING 时继续；如果回执带 task_id/worker_id/attempt/generation，也必须和原租约一致。网络失败、租约撤销/超时、任务取消、服务器返回异常、未知/冲突状态均不可调用下一步 OS RPC，整个 Guard 实例永久 HOLD。
- 已通过中央心跳后，仅允许原 Supervisor 的只读 inspect/log。OS UNKNOWN、通信断开或格式错误立刻永久 HOLD。OS EXITED + exit_code=0 **仅表示 OS 退出**；返回诊断 LeaseBoundOsSnapshot，其 business publish/auto reassign/production launch/trusted StopReceipt 均为 false。
- request_stop / publish_result 明确拒绝；没有 CPU 模型执行入口、无任意命令、无外部 URL、无中央结果 finalization 或 task.release。
- 新增独立合同测试，覆盖正常 RUNNING/EXITED、取消、HTTP 错误、状态缺失或伪造、跨任务/代数/节点/租约、原回调/后台线程禁入、OS UNKNOWN/断链、每页日志重验证、永久 HOLD 不重试。

## 为什么这轮不改前端

这个模块不参与正式任务派发或监控，用户在 UI 中无法安全操作它；没有 StopReceipt 时不应增加“安全停止”“可迁移”或“启用 Supervisor”假入口。原模型转换页面继续以中央任务状态为准。发现现有前端问题仍按单点复现修复，不以这项底层治理为由重构页面。

## 阶段性验收与 NO-GO

- 原 legacy Runner（包括下载、执行、日志、续租、取消、哈希确认、prepare/upload/confirm/finish）全部保持不变。此模块不能用于直接替换或包裹生产转换 Runner，也不能赋予中央自动重派依据。
- 中央租约失效后只读观察会停止；**不能保证原 systemd 进程已经停下**。必须等到受信任 Supervisor 停止流程、StopReceipt 和原任务提交事务完成，才能讨论生产启用。它不是“运行中的 GPU 模型转换安全托管”。
- A800、双4070 不触碰、不重启、不部署；Ubuntu 22.04/systemd249 仍 NO-GO。不合并 main、不打 Release/tag、不 force push。
- 代码与现有 Node Agent Windows/Ubuntu/API 工作流接入验证。最终准确 SHA 的 GitHub Actions 必须重新核对；此文档初始版本不能预先声明 CI 全绿。

## 下一最小阶段（2D-2D2B）

在独立 CI-only root-owned CPU sandbox 中，审计并补齐：执行前再次读取当前中央租约、受限 ONNX 业务 worker profile 的不可变输入证据、实际 OS handle 原身份日志及重连、失败/中断后的可信停止和结果事务。真实 MODEL_CONVERSION 不能直接复用 fixed-cpu-v1 签名授权，也不能将原 ONNX 推理 PoC 视为 PT→ONNX 业务转换。待可信停止与事务闭环验收后，再评估生产开关及页面可见状态。
