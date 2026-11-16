# 2D-2D2B2C-01｜中央 PT 授权 → 原 journal CAS → 真实 systemd 导出端到端隔离接线（2026-11-16）

## 目的与前置证据

已验收代码基线 3b81f10438f3ddb9865e66d30d10918ec5e80f5c：24/24 GitHub CI 最终成功，可信测试 YOLO11n PT→ONNX / CPU ONNX Runtime 一致性、root-owned systemd 隔离通过。上一轮 PT 中央签名 + journal CAS 与真实 CPU 导出器互相独立。本轮 **2C-01** 负责在非生产 CI 内首次将两者接成完整链路，不把它冒充业务真实模型输入和上线准入。

## 最小工程实现

1. 新增 platform_core/os_supervisor_pt_export_rechecked_bridge.py，仅提供 opt-in 的 CiOnlyPtExportRecheckedBridge，不被生产 API/Agent/SupervisorService 引入；原中央 issuer 继续使用现有 TaskRepository + ArtifactStore + ServiceNodeRepository 作为**唯一任务/lease/attempt 权威**。不新增队列、资源调度、Task、attempt 或租约。
2. 启动之前从**原有 ExecutionJournal SQLite 文件**取回唯一 execution_intents.handle_id、原 attempt/boot/node/worker/lease 和冻结 PT binding/challenge；拒绝过期 challenge、非 PREPARED 状态、签名不一致和已消耗 CAS。
3. 精确匹配专用 CI PT exporter 的常量：source.pt、source.onnx、input_size=32、batch=1、opset=12、dynamic=false、simplify=false；核验源文件 SHA256、长度和原冻结非可执行 manifest。中央授权不同参数时拒绝执行，绝不静默更改。
4. 仅使用 pinned Ultralytics 在 CI 内自行生成的可信 YOLO11n 权重；在独立中央签名验真后，将已校验 root-owned staging 原子移动到**原 journal 分配的 handle** 下，解决旧 CPU pilot 与中央 journal 各自分配 OS 身份导致不可追溯的问题；不能让 Agent 上传任意 pickle。
5. 验证新鲜的中央二次启动 Ed25519 grant，再由 PtExportJournal.claim_rechecked_launch 在同一原 journal 的 BEGIN IMMEDIATE 下做一次性 PREPARED→STARTING CAS；**只有成功 CAS 后** 才调用已验收的 fixed systemd CPU 工作负载，不允许任何 Agent 指定 argv/env/cwd。
6. 系统服务运行后核验完全相等的 unit_name、InvocationID、main PID、cgroup，回写原 journal 同一个 SQLite 文件内的 pt_export_unit_identities 表并更新 RUNNING。不会另建中央执行所有权；重新打开 journal 能读取原身份，不能重启第二实例。
7. 扩展原 ExecutionJournal 的固定 CPU identity/log/exit 接口 profile fence：PT handle 不能绕过独立 profile 的签名复核进入 legacy fixed-cpu-v1 的状态更新接口。
8. 新增独立隔离 systemd 真实端到端测试：中央原任务状态/lease、fresh launch grant、OS CAS、实际 YOLO11n PT→ONNX、产物 SHA/ONNX checker/ORT 数值、自然退出与 OS 身份重建；同时测试伪造签名、授权参数不匹配、中央租约撤销、系统启动失败后 CAS 已消费且不能重复启动。所有测试仅在 GitHub Ubuntu 24.04/systemd255（真实 root-owned sandbox）内。

## 完全不变的生产限制

- **只验证可信 CI 自生成的测试模型**。PT 文件是 pickle，来源不可信时禁止加载；不要把仅有 SHA256 的用户上传权重当成可信模型。
- 单元自然退出及 systemd 原身份回读**不是可信 StopReceipt**，也不是取消、超时、断电、失联后的原任务最终清理证明。
- **仍无**真实模型对象存储 staging/资格、中央 Agent 网络传输接入、普通 Runner 的 prepare/upload/confirm/finalize/finish、失联停止和自动恢复链路。
- 没有修改生产 AgentConversionRunner、app.py、SupervisorService、UI，不修改 A800/双4070 服务与业务数据，不启用 supervisor-required。
- Ubuntu22.04/systemd249 兼容性未证明，生产部署仍 NO-GO。

## 验收方法

新提交 SHA 的 GitHub Actions：独立 `isolated-pt-export-cpu.yml` 必须 11+ 原合同、完整真实 OS 导出和新增串联负向/成功测试通过，原 Node Agent、前端及全仓 CI 保持成功。实际日志、测试数量、真实 SHA 与失败证据需在 CI 结束后再回填。不能继承旧 commit 24/24 的结论。

## 下一步

2C-02 可信业务模型来源与固定转换资源合同，之后 2C-03 停止/取消/失联与 StopReceipt，2C-04 原上传发布事务、Ubuntu22.04 系统适配与受控生产灰度。任何生产环境操作需另外授权。
