# 2C-03｜受保护 PT 转换取消、停止、失联恢复与部署准入（2026-11-16）

## 已核实基线

- 唯一长期开发分支：`feature/external-algorithm-publishing`；禁止在 main 开发、强推、生产试错。
- 2C-02 官方 YOLO11n 固定来源真实 PT→ONNX：功能提交 `373466e8b1b34b9276ffdf06ac339426b65fbf81`，官方 systemd CI 10/10、安全合同 29/29、全仓 24/24；这不是任意上传 PT 的授权。
- 当前原中央 MODEL_CONVERSION Runner 的任务租约、日志、取消、prepare/upload/confirm/finalize/finish 是业务权威。Supervisor 的固定 CPU pilot 仍是**CI-only**，未接入正式 Runner 或正式发布。
- Ubuntu 22.04/systemd 249 不支持 `ExitType=cgroup`；现有 `FixedCpuSystemd` 有意禁止 249，不能以简单移除该属性绕过，因为其自然退出证据依赖该语义。
- 以前的 `tools/poc/linux_cgroup_poc.py` / `linux_stop_receipt_bridge.py` 已有 249 用户管理器上的真实内核观察和模拟中央挑战，但其 HMAC 测试证据**不是**受生产中央信任的 StopReceipt。

## 2C-03A 本轮精确改动

- 新增 `platform_core/os_supervisor_pt_stop_observation.py`：**仅 GitHub-hosted CI、显式 opt-in**，从 `PtExportJournal.verified_pt_identity` 读取原始 unit/InvocationID/cgroup/mainPID/bootID。
- 系统调用前先验证 journal 内目标名称、原任务身份和 boot，再验证 systemd 中原始活跃进程身份；不接受 Agent 自定义 unit/PID。
- 在停止前只读固定原始 `cgroup.events` FD，必须先读到 `populated=1`；之后请求原 unit 停止并在原始 FD 观察 `populated=0`。旧 FD 失效、单位重绑定或未观察到 0 只能返回 UNKNOWN/HOLD。
- 观察成功仅返回 `LOCAL_EMPTY_OBSERVED_NO_RECEIPT`，**永远** `trusted_stop_receipt_available=false`、`central_recovery_allowed=false`、`result_publish_allowed=false`。
- `PtExportJournal.verified_pt_identity` 增加只读 boot_id 证明字段；未改变原工作流调度、中央签名或任务状态。
- 新增 23 项纯安全/假内核负面合同与 Ubuntu 24.04 固定 CPU 真实 stop 单独集成；Ubuntu 22.04 真实 cgroup stop 复用现成 POC。
- 核查过程中发现并修复 unit 在本地验证之前传给 backend.inspect 的拒绝顺序问题（提交 `6984897501994aac06ff5016fc26a7f9adee9243`）。
- CI 状态：**当前仍待最终复核**。本文件不得把队列、早期失败或中间测试写成 PASS。

## 2C-03A 已完成的真实 CI 证据（已核对 2026-11-16）

- 代码 `09a042d535aa0520acea4d3c0d7892c037163dda` 在 GitHub Actions 同 head SHA 的 23/23 个工作流 **completed/success**；不能代替 2C-03B 之后的新代码 CI。
- <https://github.com/jorsamj/aixunlianpingtai/actions/runs/43800970138> Ubuntu22.04/systemd 249：23/23 合同及真实用户 cgroup kernel-to-memory CAS PoC 成功。此 PoC 见证由同一测试上下文模拟，不是生产独立 StopReceipt。
- 同一次 Ubuntu24.04：23/23 合同通过；真实系统级 systemd stop 在发出停止请求前打开原始 `cgroup.events` 并订阅内核事件；真实检查结果 `original_cgroup_became_empty=True`、`state=LOCAL_EMPTY_OBSERVED_NO_RECEIPT`；实际集成测试 1/1 成功。
- 2C-03A 判定：**PASS（仅隔离停止观察边界）**。没有签发受生产信任的 StopReceipt。

## 2C-03B Ed25519 测试见证与中央一次性 CAS（开发中）

- 新增 `tools/poc/pt_stop_receipt_ed25519_contract.py`，独立的 Ed25519 域分离测试签名/验签合同，封闭 payload 字段、任务/boot/invocation/cgroup/时间顺序和布尔证据，测试-only 显式许可。
- 复用已有 `central_stop_recovery_contract.py` 的内存 SQLite 原始 tasks.attempt、lease 与资源占用事务 CAS；不新增调度器、生产数据表或生产恢复 API。
- 新增 `tests/unit/test_pt_stop_receipt_ed25519_contract.py` 验证错签、篡改、错误任务代数、租约轮换、过期挑战及重放必须拒绝；跨平台测试由 `central-stop-recovery-isolated.yml` 触发。
- 原 `linux_stop_receipt_bridge.py` 增加 `--ed25519-test-only` 独立模式；实际 Ubuntu22.04 cgroup 内核证据验证后，使用共同驻留在测试进程的测试私钥签名并提交到**纯内存**中央 CAS；旧 HMAC 测试路径保留。
- 真实内核+测试签名专项在 `agent-kernel-stop-poc.yml` 新增 step；原 249 CPU 工作流与额外跨平台验证完成前，不得宣布 2C-03B PASS。
- 此签名**只证明测试密钥持有权**，绝不证明签名者是隔离 root Supervisor。测试签名仅可由内存 CAS 消费，不允许作为正式 StopReceipt 或恢复/资源释放授权。生产仍 NO-GO。

## 上生产前仍必须完成（硬门槛）

1. **中央原任务取消授权**：不可凭 Agent 自述“取消”就释放资源；签名授权需绑定 task_id、原 `tasks.attempt`、原 lease、node、boot、原 OS unit/InvocationID、请求时间/有效期及一次性 nonce；源任务/租约撤销要中央原有 API 核验，禁止第二调度器。
2. **受保护 OS 停止原子性**：停止意图在 root-owned 原 journal 持久化且 CAS 单次消费，重试仅幂等检查，绝不重启同一代数；支持 SIGTERM→超时 SIGKILL 的 cgroup 级终止、孙进程、重试并发、Agent/ Supervisor 崩溃和系统重启。
3. **可信 StopReceipt**：以 root-owned 受保护签名密钥签发；绑定停止请求、原始任务及执行身份、内核停止观察顺序、主进程及子进程身份、boot、systemd manager/cgroup 类型、证据摘要；中央独立验签、只消费一次、事务式 CAS 释放资源；任何未知状态维持 HOLD。
4. **Ubuntu22.04/systemd249 安全适配**：不得用 `ExitType=cgroup`；需使用实机验证的等价后代进程终止证明，并核对 manager PID1 的真实版本、系统服务安全属性、GPU/CPU 资源隔离。自然退出和已停止不得混淆。不得修改旧 250+ 行为来掩盖兼容缺失。
5. **正式 Runner 原生命周期接管**：保留原 download SHA/size、日志、取消、结果 prepare/upload/confirm/finalize/finish；结果上传和最终状态仅在原中央 lease 和签名可信来源仍有效时可进行；必须先证明旧/新进程互斥和一键回退。
6. **业务 PT 信任来源**：官方固定白名单之外，平台自训练 checkpoint 必须能由原可信训练作业的来源签名证明，不得把用户任意上传 PT 直接以特权解释执行。
7. **部署/发布验收**：隔离 Ubuntu22.04 和 Ubuntu24.04 正反例、服务进程残留/僵尸、租约撤销、网络断开、重复停止、OS 重启、多节点、前端取消状态、数据持久化、24/24 全仓 CI；人工授权后再灰度生产，确保有回滚且业务无任务。

## 生产判定

**NO-GO**：本阶段的本地停止观察器尚未成为中央可信 StopReceipt；249 的真实 PT 受保护转换、正式 AgentConversionRunner 接管、上传/发布、生产审计均未完成。本轮不改变 A800/双 4070、生产 Worker/Agent、前端和生产数据，也不调整既有 Runner 开关。紧急业务部署如不依赖新 Supervisor，应单独以原 Runner 的现有 CI/部署合同验收，不得宣称这个新受保护路径已上线。

## 本轮 CI 链接

- 2C-02 已验收：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43793371849>
- 2C-03A 首轮根因已修正（早期文件依赖不足与非法 unit 验证顺序）：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43800361441>
- 2C-03A 首轮 24.04 真实停止测试 UNKNOWN（正确拒绝假停止证明）：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43800546470>
- 2C-03A 修复版 Ubuntu22.04/Ubuntu24.04 均成功：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43800970138>
- 2C-03B 签名/内存 CAS 跨平台待验：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43807294738>
- 2C-03B Ubuntu249 真实内核/Ed25519 模拟中央 CAS 最新待验：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43807711658>（较早运行被 GitHub 同工作流并发策略取消，不算测试失败）
