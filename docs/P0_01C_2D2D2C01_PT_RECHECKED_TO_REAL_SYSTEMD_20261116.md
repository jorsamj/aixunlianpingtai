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

## 2C-01 真实隔离端到端验收证据（代码 SHA 27875df1）

**准确原始代码 SHA：27875df1fabfa2bb10dd62d9c08c53ebc181980a**。GitHub CI 真实 isolated-pt-export-cpu workflow run：
https://github.com/jorsamj/aixunlianpingtai/actions/runs/43790234946 —— **SUCCESS**。

- 快速 CPU/security 合同 **16 passed**，包括 CI-only bridge 默认关闭/无业务上传参数、原导出器不可自定义任意 argv/env。
- 真正 systemd / Ubuntu24.04 / CPU 运行 **8 passed**，包括旧固定 PT demo 3 项和新增中央授权 + journal 一次性 CAS + 真实 YOLO11n PT→ONNX 的完整 E2E 5 项。
- 新增一体化 E2E 样本独立日志：CENTRAL_CAS_REAL_PT_EXPORT_PROOF；CPUExecutionProvider；固定输入 [1,3,32,32]；输出 [1,84,21]；**max_abs_error=1.52587890625e-05**；ONNX 产物 SHA256 **d12bf3a9d429859cdbddb741fd86e62c091e8f0e48d84950219f53baab211a9b**；大小 **10,506,760 bytes**；opset12；ONNX checker 通过。
- 反例实测均成功：签名篡改、中央冻结尺寸640不匹配 CI 固定导出32、中央租约取消/轮换不能签发、注入 systemd 启动失败后旧 journal 保留 STARTING/CAS 且不可二次启动。PT handle 不能由旧 fixed CPU identity API 转换为 RUNNING。
- 同一提交的第一组 Node Agent Executor：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43790234920 ，Ubuntu **851 passed/2 skipped**；Windows **846 passed/7 skipped**；Windows portable cgroup **30 passed/1 skipped**；API 全部成功。

以上为可复核的实际日志，不是源代码推测。全仓其他 CI 要以最终准确 SHA 工作流终态回填，**不能仅凭以上结果宣称全仓已完成**。

### 工程约束

此阶段的 CiOnlyPtExportRecheckedBridge 仍须 `isolated_ci_only=True` 与原测试 journal，并未接入中央生产 API/Agent/SupervisorService。该桥不接收业务上传的任意 PT、用户命令或环境变量；测试工作负载仅接受由已固定 Ultralytics YAML 在可信 CI 内生成的 PT。普通转换任务、AgentConversionRunner、正式生产发布均不经过桥。

即便单个真实 OS unit 结束，**没有可信停止回执、没有受控失败后新 attempt 的中央恢复权、没有结果 upload/finalize/finish**。新 E2E 的成功也不解决 Ubuntu22.04 systemd249 与 A800/双4070 现场差异。生产仍 NO-GO，未修改任何生产服务器。

## 2C-01 全仓最终验收（2026-11-16）

**最终功能代码 SHA：27875df1fabfa2bb10dd62d9c08c53ebc181980a。** 以此 SHA 查询 GitHub Actions 的 head_sha 列表确认：**24/24 workflows completed/success，失败 0，运行中/排队 0**。不借用 2C-01 之前的基线 24/24。

- 真实中央授权 → 原 journal CAS → 受保护 systemd → YOLO11n PT→ONNX：
  https://github.com/jorsamj/aixunlianpingtai/actions/runs/43790234946 ；**8/8 Ubuntu systemd 集成测试成功、16/16 快速安全合同测试成功**。新连接器的真实最大数值误差为 **1.52587890625e-05**。
- 第一组 Node Agent Executor：
  https://github.com/jorsamj/aixunlianpingtai/actions/runs/43790234920 ；Ubuntu **851 passed、2 skipped**；Windows **846 passed、7 skipped**；portable cgroup **30 passed、1 skipped**；API 工作流成功。
- 第二组 Node Agent、远程训练、远程转换、远程素材、算法发布、资源调度、RKNN 和 AI 标注等原有工作流均以同一代码 SHA 完成成功。
- 前端完整工作流：
  https://github.com/jorsamj/aixunlianpingtai/actions/runs/43790235000 ；frontend 构建与单测成功，Chrome 三组分别为 **128 passed、130 passed、125 passed**，共 **383 passed**，均首次成功。本轮未改任何前端业务文件。

### 2C-01 最终工程判定

**PASS：** 在隔离的可信小 PT 用例中，中央 task/attempt/lease/source、独立挑战与新鲜签名、原 root-owned journal 单次 CAS、同一 OS handle、非 root systemd 真实执行、实际 ONNX 产物与 ORT 数值校验、真实身份持久落盘和反例拒绝均已接线并完成测试。

**仍 NO-GO：** 业务真实 PT 模型的来源可信性与受控下载 staging、生产中央 HTTP/Agent 接口接线、取消/StopReceipt/失联处理及中央恢复、原 publish 上传事务、Ubuntu22.04/systemd249 或生产 GPU 场景。Pilot 明确只能在 CI 信任条件下运行，不能据此替换正式模型转换 Runner。

下一步按既定渐进方案进入 **2C-02：可信实际业务权重来源和冻结输入合同**，优先做只读审计、输入可信边界及无副作用预检；保留原生产 Runner，禁止未授权部署和切换。
