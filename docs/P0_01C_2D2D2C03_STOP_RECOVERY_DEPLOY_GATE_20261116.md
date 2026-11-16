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

## 2C-03B Ed25519 测试见证与中央一次性 CAS（隔离试验 PASS）

- 新增 `tools/poc/pt_stop_receipt_ed25519_contract.py`，独立的 Ed25519 域分离测试签名/验签合同，封闭 payload 字段、任务/boot/invocation/cgroup/时间顺序和布尔证据，测试-only 显式许可。
- 复用已有 `central_stop_recovery_contract.py` 的内存 SQLite 原始 tasks.attempt、lease 与资源占用事务 CAS；不新增调度器、生产数据表或生产恢复 API。
- 新增 `tests/unit/test_pt_stop_receipt_ed25519_contract.py` 验证错签、篡改、错误任务代数、租约轮换、过期挑战及重放必须拒绝；跨平台测试由 `central-stop-recovery-isolated.yml` 触发。
- 原 `linux_stop_receipt_bridge.py` 增加 `--ed25519-test-only` 独立模式；实际 Ubuntu22.04 cgroup 内核证据验证后，使用共同驻留在测试进程的测试私钥签名并提交到**纯内存**中央 CAS；旧 HMAC 测试路径保留。
- 真实内核+测试签名专项在 `agent-kernel-stop-poc.yml` 新增 step；原 249 CPU 工作流与额外跨平台验证完成前，不得宣布 2C-03B PASS。
- 此签名**只证明测试密钥持有权**，绝不证明签名者是隔离 root Supervisor。测试签名仅可由内存 CAS 消费，不允许作为正式 StopReceipt 或恢复/资源释放授权。生产仍 NO-GO。

## 2C-03C 中央原任务签名停止授权与 root journal 一次性意图（已提交、待验收）

- 新增 `platform_core/os_supervisor_pt_stop_grant.py`：独立 STOP 域的 Ed25519 中央试验签名，默认关闭。只读取**原 TaskRepository** 的 MODEL_CONVERSION、原 `tasks.attempt`、原 worker、原 lease；仅当 `CANCEL_REQUESTED`，或 `RUNNING` 且 `recovery_blocked_remote_agent_unverified` 并已过租约有效期时签发。普通运行中的任务不能随意获得 STOP 授权。
- 授权完整绑定任务、执行代数、节点/worker、原 lease SHA256、boot、OS handle、unit、InvocationID、cgroup、主 PID、一次性挑战、停止原因和短时 TTL。Root 只认可原 journal 中的身份，不接受 Agent 任意 unit/PID。
- `PtExportJournal` 原 protected SQLite 增加两张**附属证据表** `pt_export_stop_challenges`、`pt_export_stop_claims`，均通过原 execution_intents.handle_id 关联，单次 nonce、一张停止意图、签名校验后 `BEGIN IMMEDIATE` CAS；不增加中央调度器、第二任务表或任务执行代数。
- 新增 `tests/unit/test_os_supervisor_pt_stop_grant.py`，覆盖正常运行不得停、真实取消、原租约超时、签名伪造、错误任务/代数/boot、租约/worker 改动、重复停止、原 journal 重开和挑战超时等。
- **特别注意**：这阶段只完成 `STOP_INTENT_CLAIMED_OS_UNVERIFIED` 的持久意图，不真正执行 stop，也不签发 StopReceipt。返回 `os_stopped=false`、`trusted_stop_receipt_available=false`、`central_recovery_allowed=false`。与 2C-03A 内核观察器联动、原执行后代全部停止证明和恢复消费事务仍需独立验收。
- 功能提交 `b7caab7cff38f8ebab50b76c102cd3fae1ff358c` 起，陆续增加 root journal、测试和微小修复； CI 工作流更新提交 `bd5229a19d4333c0e375a1693b187657f1e0b434`。**尚无最终 CI PASS，继续 NO-GO**。
- CI：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43808456054>（原官方 PT CPU systemd 隔离工作流，包含新增 STOP 合同测试）。

## 2C-03C-联调：原中央签名→root CAS→真实 cgroup 停止（已提交、待 CI）

- 新增 `tests/integration/test_os_supervisor_pt_stop_central_bridge_live.py`：复用原 `TaskRepository` / `PtExportJournal` / `CiOnlyPtExportRecheckedBridge` 的签名启动身份，**只用已存在的固定 25 秒 CPU worker 作为 OS 执行替身**，不将 PT 反序列化和停止安全混在一个不稳定测试里。
- 测试原中央 `CANCEL_REQUESTED` → 新 STOP 签名 → 原 root journal stop challenge/claim 单次消费 → 原 `InvocationID`+cgroup 的 systemd 真实停止 → 原始 `cgroup.events` 内核空进程证据；复用同一任务代数和原 lease，无第二次启动。
- 预期整个链路仍 `trusted_stop_receipt_available=false`、`central_recovery_allowed=false`，中央原任务保留 `CANCEL_REQUESTED`，journal 暂维持 `RUNNING` 待后续可信终态证明；不能误认为已经完成生产恢复。
- CI 工作流 <https://github.com/jorsamj/aixunlianpingtai/actions/runs/43808785894>，Ubuntu24.04 隔离主机。**验收结果待实际终态，禁止提前标 PASS**。
- 尚未覆盖 Ubuntu22.04 上的真实 PT systemd 执行（249 无 `ExitType=cgroup`）、生产级 root 保密签名和独立中央 StopReceipt 验签；这些仍是生产硬门槛。

## 2C-03C2 停止授权不可绕过（已提交、待 CI）

- 审计发现前一版 2C-03C 真实停止联调直接调用 `IsolatedPtStopObserver.request_and_observe`，虽有 CI-only 禁用门槛，却未在**执行停止前**强制读取中央签名停止意图，属于潜在的授权绕过接口。现已新增 `CiOnlyPtStopRecheckedBridge`，禁止这条联调通过未授权直达 systemd。
- 同一 `PtExportJournal` 受保护 SQLite 中新增 `pt_export_stop_observation_claims`，外键仍关联**原** `execution_intents.handle_id`，不创建第二调度器。检查原签名 STOP claim 的 InvocationID、PID、原 boot/unit、年龄（12 秒上限），然后在 `BEGIN IMMEDIATE` 中唯一领取 OS probe。任意一次进程崩溃/超时之后**不得自动二次 stop**，状态保持 UNKNOWN/HOLD。
- `tests/unit/test_os_supervisor_pt_stop_grant.py` 新增：无中央签名不得领取、原 OS 身份变化不得领取、boot 更改拒绝、签名时间过期拒绝、相同 handle 重放、root journal 重启后重放均拒绝；对应真实 systemd 联调改为通过 `CiOnlyPtStopRecheckedBridge` 启动。
- 联调断言也已纠正：`CiOnlyPtExportRecheckedBridge.start` 不提供 `ActiveState/SubState`，必须经 OS backend 的 live `inspect` 获取，避免错误字段导致假失败。
- 关键提交 `26c8b7a15a2a43c396db20d968658642d9e382a4`（状态接口测试修正）、`d09ed5c5f5955c7545f78c8dd3210d6121064286`（原 journal OS probe CAS）、`153d7b4f308d67f5b46da408bc9d070191270ef7`（CI-only 止损桥）及后续集成/负面测试。由于真实停止 CI 仍在队列中，2C-03C2 **未验收**，禁止修改部署准入结论。
- **仍缺的关键证据**：已停止后代进程跨 cgroup 的存活核验、签名者 root 私钥隔离、真实生产 StopReceipt、原中央数据库的消费事务、Agent 失联/重启重入控制、systemd249 上真实 PT→ONNX 生产级隔离以及正式 Runner 接管。

## 2C-03C3 轻量验收与原租约竞争防护（2026-11-16）

- 原慢速 Ubuntu24.04 workflow 在合同测试之前下载 CPU PyTorch、Ultralytics 和 ONNX，无法快速反馈停止授权错误。新增 `.github/workflows/pt-stop-grant-fast-contract.yml`：Ubuntu22.04/Windows、无模型/GPU/systemd、仅测试原 TaskRepository→STOP 签名→root OS journal 的关键合同，快速验证 2C-03C 类代码；**不替代真实 systemd 联调**。
- 对原有拒绝用例进行安全修正：中央签名者只能读取**当前中央租约**，不能仅因租约已轮换就由签名者拒绝；需要 root journal 将当前签名中的 lease SHA256 与**原 OS 启动的 lease SHA256**比较并拒绝旧身份停止。本次增加了“当前租约能签名、原 root CAS 必须拒绝”的真实跨库测试，防止错误测试假设遮蔽安全边界。
- 额外加入争抢同一 OS stop probe 的双线程 CAS 与不同任务 attempt 拒绝测试，要求不同时签发两份停止执行资格。
- 代码提交 `0f9b0b01c29bab111d2b1d677710533fab35eec5`（租约轮换语义修正）及 `5dc2b08f81c6f76092d7e5860c23747c5725e84d`（并发/代数安全合同）；轻量 CI 最新运行：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43811499594>。
- 最新慢速真实 PT systemd/STOP 联调追踪：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43810072981>。上述 CI 截至本次更新仍处于排队/未验收，**不得宣称 2C-03C 通过**。

## 2C-03C4 快速 CI 首轮缺陷闭环（2026-11-16）

- 真实 CI `43811499594` 初次在 20 项成功后失败：`test_non_cancelled_live_lease_cannot_get_signed_stop` 预期 `CENTRAL_STOP_REASON`，但实际被包装为 `CENTRAL_LOOKUP_UNVERIFIED`。原因已核实：`GrantRejected(PermissionError)` 属于 `OSError`，新 STOP issuer 的宽泛异常处理捕获了其自身安全拒绝。
- 修复 `platform_core/os_supervisor_pt_stop_grant.py`：显式 `except GrantRejected: raise` 优先于通用 `OSError/sqlite3.Error`，确保拒绝取消不成立、任务/lease 不匹配等条件能传递原始 HOLD 机器码；不会导致错停放行。
- 修复提交 `b4195341038ce91be1df5ec6c015123bfbedbe51`，复测 <https://github.com/jorsamj/aixunlianpingtai/actions/runs/43811735889>：**Ubuntu22.04 51/51 单元合同已成功**；Windows 截至核查仍排队，真实 Ubuntu24.04 systemd 停止专项仍未终态。**不得将部分成功当作全流程 PASS**。
- 部署准备独立文档 `docs/DEPLOYMENT_TWO_TRACK_READINESS_20261116.md`：业务原 Runner 的可部署轨道与未完成的 Supervisor 轨道严格分开；A800/4070 现场只读核查仍未执行，禁止未经授权操作生产。

## 2C-03D 临时 root 进程签名的原 cgroup 停止见证（隔离开发，尚未验收）

- 在原 2C-03C 的中央 STOP 预授权和一次性 OS probe CAS 之后，新增 `platform_core/os_supervisor_pt_stop_root_witness_ci.py`：签发者必须在 GitHub-hosted Linux disposable VM 的 root 进程中执行，且强制 `isolated_ci_only=True`；内部临时生成 Ed25519 密钥，不允许 Agent 提供私钥、系统进程身份或“已停止”的 JSON 成功标记。
- 真正调用 `CiOnlyPtStopRecheckedBridge.stop_original_after_central_cas`，使用 `IsolatedPtStopObserver` 原始 FD 的 `populated 1→0` 事件及单调时间戳；仅在 root journal 原始 STOP grant/OS probe 唯一消费记录仍与任务 attempt、lease 摘要、boot、unit、InvocationID、主 PID 完全一致，且 `LOCAL_EMPTY_OBSERVED_NO_RECEIPT` 成立时签发隔离测试见证。
- 此签名绑定事先给出的测试中央 challenge_id、nonce 和原执行身份；验证者需提供**独立来源**的原任务/OS 身份和原挑战，并验签、核对签名 TTL。无授权/跨世代/错密钥/篡改/过期/重复 stop/无 `populated=0` 必须 fail closed。
- `platform_core/os_supervisor_pt_stop_observation.py` 为原 FD 成功观察新增 `empty_observed_monotonic_ns`，不改变原先的 `trusted_stop_receipt_available=false` 与 `central_recovery_allowed=false` 语义。
- 新增 root-only 合同与 Windows 纯验签单测 `tests/unit/test_os_supervisor_pt_stop_root_witness_ci.py`；Ubuntu24.04 systemd 真实集成 `tests/integration/test_os_supervisor_pt_stop_central_bridge_live.py` 将直接调用 root 见证签发，不接受 Agent 自述停止结果。
- **重大限制**：这里的 root 私钥只存在于 CI 进程内，未持久化、未与生产中央系统建立独立公钥注册和身份确认；验证者可以在同一 CI 主机拿到测试公钥。此结果只是 root 对 CI cgroup 观察的一次签名，**不是**生产可信 StopReceipt。生产仍缺可信密钥封装/轮换/撤销、原中央数据库一次性消费、后代进程逃逸核验、systemd249 安全执行及 Runner 全链路。
- 此段的新 CI 尚未跑完，**不得标为 PASS**；Ubuntu22.04 之前的 51/51 STOP grant 单测只能作为旧版本参考，不能代替新 SHA 的验收。

## 2C-03D1 验签测试必须采用原始独立身份（待 CI）

- 独立安全审计发现，初版 CI root witness 的成功测试使用 `expected_original={key: signed_payload[key]}`，形成了**验证期望值取自被验证消息**的循环论证。签名只能说明测试私钥持有者，不能因此认定原中央任务、lease 和 OS 实例已经独立核实。
- 测试现已改为在签发之前分别读取既有 `TaskRepository.tasks`、原 `ExecutionJournal.execution_intents`、`pt_export_unit_identities` 和原 STOP claim，独立计算真实 lease SHA256 并构造验证范围。伪造的合法二次签名（改变 worker_id）也必须因独立作用域不匹配而拒绝。
- 该修复仍然**不能替代生产中央先前注册的可信 boot/InvocationID 公钥和中央签发的持久 challenge**：临时 root 见证使用 CI 常量 challenge_id/nonce，尚无原中央挑战表与一次性消费事务。生产接入必须先补齐这些事实，不能依据 CI 中同一个 root journal 自证独立信任。
- 以上变更仅限隔离集成/单元测试，**没有启用生产停止、任务恢复或 GPU 释放**，待新 SHA 专项 CI 验收。

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
- 2C-03B 签名/内存 CAS 跨平台成功（Ubuntu 69 + Windows 69）：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43807294738>
- 2C-03B Ubuntu249 真实内核/Ed25519 模拟中央 CAS 成功，77 项合同 + 真实 kernel：<https://github.com/jorsamj/aixunlianpingtai/actions/runs/43807711658>
