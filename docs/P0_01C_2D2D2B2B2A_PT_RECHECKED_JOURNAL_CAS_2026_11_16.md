# 2D-2D2B2B-2A｜PT→ONNX 中央启动复核与原 journal 一次性 CAS（2026-11-16）

## 本阶段范围

基于上轮已验收的 PT 专用中央 admission 签名（代码 SHA 208231675582076937096aba1a3970d2ec111140，CI 23/23），**新增 PT 专用“受保护启动前复核合同”**，没有改变生产执行入口。

本阶段故意拆为 2A「中央复核 + root-owned journal 一次性 CAS」和 2B「可信小 PT 的真实 CPU/systemd 导出」，禁止拿 2A 充当 2B 的真实转换验收。

## 实际设计与实现

- 新增 platform_core/os_supervisor_pt_export_launch.py，接收既有 ExecutionJournal 实例作为唯一 OS intent 存储；沿用同一 root-only 目录、SQLite FULL synchronous、execution_intents 表及 UNIQUE(task_id,task_attempt)。旧 fixed-cpu-v1 与新 PT 不能对同一任务执行代数各保留一个 handle。
- PT admission challenge 与 PT bound evidence 仅作为**同一 root-owned journal 文件内的附属证明表**，不新增中央 tasks、attempt、owner、任务队列、自动恢复机制。每任务最多四个活跃 admission challenge，每节点/全局设限；失效 nonce 不刷新为可重试启动。
- 中央 launch 签发调用前一阶段同一 CentralPtExportAdmissionIssuer.issue：重新读取原任务状态、tasks.attempt、node、lease、中央任务文件中的 PT source SHA256/size/params/manifest，拒绝已取消/lease 轮换/节点停用/不匹配模型；再使用**不同 purpose + domain** 的 Ed25519 签名，绑定原签名 digest、唯一 handle、fresh challenge 和全部冻结模型证据。
- root journal 验证中央新签名和原冻结证据逐字段相等、nonce 未过期、签发时间不早于挑战且 3 秒内有效，完成 PREPARED→STARTING 的唯一持久 CAS。旧授权、旧挑战、重放、新旧 attempt 混用一律 HOLD。
- **接口不能启动 systemd**：claim_rechecked_launch 返回 state=UNKNOWN、launch_authorized=false、os_executor_connected=false，不返回可被 Agent 用来执行的任意 argv/unit/env/cwd。此处的 STARTING 仅表示已消耗原唯一启动窗口，必须在后续真实受保护执行器接入与终态验证后才能声明计算运行。无停止回执、结果发布及自动恢复权。
- 生产中央 API、SupervisorService、AgentConversionRunner、node_agent.py、app.py、前端、GPU 与生产配置均无修改。本轮没有调用 A800 或双4070，也不启用 supervisor-required。

## 负向测试

新增 tests/unit/test_os_supervisor_pt_export_launch.py，覆盖：
1. 中央真实 TaskRepository/ArtifactStore/ServiceNodeRepository 签名及 journal 重启重连，相同任务同代数只允许一个 OS handle；旧固定 CPU 与 PT 注册双向冲突。
2. 状态取消、attempt 变化、lease 轮换、节点禁用、模型源哈希变更，均无法取得有效新 launch grant 或无法 claim。
3. 参数、manifest、boot、worker、nonce、task attempt 篡改及错误签名公钥均 fail closed；旧 admission 签名不能冒充新 launch。
4. 过期挑战不可刷新、CAS 后的重复请求不重新启动，journal state 持久化。
5. 现有 Node Agent CI Ubuntu/Windows/API、既有 CPU systemd/ORT 与 Chrome 回归，须按新 SHA 单独核对；不能继承此前绿色结果。

## 下一阶段必要工程与验收

**2D-2D2B2B-2B** 才开始真正可信小 PT→ONNX 执行。要先设计 root-owned 只读 staging/模型 provenance、独立不可自定义的非 root workload、固定可信 Python/Ultralytics 安装、无网络及 GPU 权限、严格 systemd 资源限制、真正导出 ONNX + ORT 输出数值一致性，以及 systemd 真实退出/失败注入。注意 PT 是潜在 pickle，SHA256 只证明未被修改。先在隔离 Ubuntu systemd >=250 环境证明，不在生产服务器试验。

在 StopReceipt、取消及失联处理、日志持久重连、原 prepare/upload/confirm/finalize/finish、Ubuntu 22.04/systemd249 兼容和 GPU 权限实证完成前，生产接管与中央自动恢复仍 **NO-GO**。

## CI 状态

待新功能 SHA 工作流真实结束后回填，不能预先填写“全部成功”。

## 交叉 profile 隔离补充审计

在功能提交后的交叉入口审计发现：原 FixedCPU 的 issue_cpu_launch_challenge / claim_cpu_launch_rechecked / starting_cpu_unit 原本只依赖 execution_intents 的 task/attempt/boot/state，不显式区分该行最初由 fixed-cpu-v1 还是新 PT profile 登记。虽然原中央资源键与签名目的不同，仍应从 OS 边界防止通过改动中心资源字段将 PT handle 用旧 CPU 入口处理。

本轮补充在原 ExecutionJournal 内添加小型 profile fence：只在 PT 证据表存在时检查同 handle 是否已被 PT 绑定，发现即 CPU_PT_HANDLE_PROFILE_MISMATCH_HOLD；旧单 profile journal 没有此表时逻辑不变。PT handle 亦不能经由旧 starting_cpu_unit 提取固定 CPU unit。测试新增明确断言。

同时 PT one-shot CAS 事务内另存 launch_grant_digest / claimed_at 到同一 root-owned SQLite 的 pt_export_claims 附表，重启后可追查究竟哪份 fresh grant 消耗启动窗口；不改变原 tasks.attempt 或 execution_intents 唯一约束。

这仍然不是可信 StopReceipt，也未启动任何 PT 模型导出进程。修正后的 CI 必须以新 SHA 单独核验。
