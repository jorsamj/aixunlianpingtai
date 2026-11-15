# 畅联云算法训练平台｜2D-2C3 中央网络授权、非 root Agent、root Supervisor 与真实 systemd 隔离联调

日期：2026-11-15。唯一开发分支 `feature/external-algorithm-publishing`。**生产 NO-GO**。

## 本轮实际范围

本轮没有把训练或模型转换 Runner 接进 Supervisor，没有新增中央调度器、GPU 权限或正式任务重派能力。所有新入口均只用于固定 CPU-only、`supervisor-cpu-v1`、`fixed-cpu-v1` 隔离试点，默认不启用。

1. `platform_core/os_supervisor_protocol.py` 与 `os_supervisor_service.py` 增加 `launch_challenge` 本地 Unix RPC：严格仅允许既有 `handle_id+execution_generation`，必须显式打开测试构造器的 `cpu_prelaunch_recheck_enabled`；root-owned journal 签发已登记 PREPARED OS handle 的新 15 秒 nonce。旧 `start` 在该模式下继续拒绝。
2. `platform_core/os_supervisor_cpu_network_pilot.py` 新增独立 **loopback-only** 测试客户端，不在 `node_agent.py` 与正式 Runner 中导入。实现中央真实 HTTP grant → Supervisor authorize_intent → launch_challenge → 中央再查原 task/attempt/lease/node 并签发新 grant → Supervisor start_rechecked。Agent 不能提供命令、cwd、env、unit、密钥路径或新的中央 owner。一次启动请求发生任何异常均禁止本实例再次 launch；不可据此宣称跨进程可靠恢复。
3. `tests/unit/test_os_supervisor_cpu_network_pilot.py`：Uvicorn TCP HTTP + Linux AF_UNIX/SO_PEERCRED 完整调用，受限 fake OS 后端；覆盖正常启动/日志/自然终态、原 start 被阻断、重复启动、初次登记后中央 CANCEL_REQUESTED 导致再次签发失败。
4. `tests/integration/test_os_supervisor_cpu_network_systemd_live.py`：专用 GitHub Ubuntu 24.04 root 运行器：真正非 root 独立 Agent 进程，经 loopback HTTP 中央 FastAPI、带原始 SO_PEERCRED 的 root Socket Supervisor、真实 PID1 systemd-run，运行固定短时 CPU worker；验证 InvocationID/cgroup 持久记录、journald 游标、自然退出、原 tasks.attempt/lease 未改和不重复启动。只清理该测试随机 unit。
5. 已更新现有 Node Agent Executor 工作流：不新建平行 CI 工作流；在现有 Windows/Ubuntu 合同和 Ubuntu 真实 systemd 测试基础上增加精确测试。

## GitHub 审计基线

启动前 HEAD：`64c729fc42195db1bb87e9f8ab2649647d25356c`；2D-2C2 功能 SHA `a44499662ee08cc30c35f7b40321443d4e21a734` 的全仓 23/23 SUCCESS。

本轮代码提交序列：
- `979431b1484cfde67c417fcdcc76141610d8dc89`：本地 post-intent launch_challenge RPC。
- `021972d898c4f3d924959053d2df7ce827b18a9a`：隔离 HTTP/Socket 客户端。
- `2c691dae0cc6424489195f36e43487ca934be737`：真实网络 + fake OS 行为测试。
- `4ba7801c84c6e5fb64772ce43bfb26835b3d2468`：纳入 Node Agent CI。
- `9b71b8b6385ad42b1b6320a89a53e78c40cd0522`：真实非 root Agent → 真实 systemd E2E。
- `c0599158df8678ec5f3f11658e11613529e3d997`：E2E 纳入原 CI。
- `db5e8fa409e36f9dc43db1366dec66beb3b3eaf7`：中央 HTTP grant 改用直连 127.0.0.1 的 HTTPConnection；禁用环境代理和外部重定向，避免携租约 token 的请求被转发。

**CI：对最终代码 SHA `db5e8fa409e36f9dc43db1366dec66beb3b3eaf7` 的最终运行结果尚未核准，不能声称 23/23 已通过。**

## 未解决与下一阶段

- CPU grant 重新签发后到 OS spawn 仍有短暂取消竞态；尚未实现运行中中央 lease 持续监督和可信停止回执。
- 此客户端仅允许 loopback HTTP，证明网络序列与根本权限隔离，并非跨真实节点 TLS、断网重连或生产 Agent 接管。
- Ubuntu 22.04 systemd249 仍由原 FixedCpuSystemd 安全拒绝；本轮 E2E 仅使用 Ubuntu 24.04 manager>=250，不声称 22.04 兼容。
- 仍无真实模型转换的受限 profile/日志偏移兼容/取消 StopReceipt/结果上传 SHA→confirm→finalization 闭环；`supervisor-required` 生产不可打开。
- 还缺测试：停止请求与中央租约失效发生在启动后的处理、Agent/OS 断线与重启后重连、StopReceipt、系统级 GPU ACL。不要把固定 CPU 自然退出当作正式计算节点可重派的可信停止。

生产 A800、双4070 服务、数据、GPU、部署配置均未操作。不得开自动任务重派、自动恢复或强制释放 GPU reservation；不合并 main、不创建 Release。


## 2026-11-15 2D-2C3B CI 实证驱动修复（尚待最终 CI）

此前功能 SHA `db5e8fa409e36f9dc43db1366dec66beb3b3eaf7` 的 CI 首次显示：
- Node Agent Ubuntu `contract`：622 passed / 2 skipped / 1 failed。失败为取消后中央已返回 409，实际 `CPU_CENTRAL_GRANT_HTTP_HOLD`，但测试断言误要求 `CPU_CENTRAL_GRANT_UNAVAILABLE_HOLD`。已调整精确断言，不修改正式中央业务授权。
- Node Agent `api`：真实非 root Agent → HTTP → root Unix → systemd 自然终态后调用 `read_log` 失败 `SUPERVISOR_LOG_UNAVAILABLE_HOLD`。根因 `ExecutionJournal.cpu_identity()` **只允许 RUNNING**；在自然退出后 `record_cpu_exit` 已将原 OS handle 提升为 EXITED。**这是实际读日志合同缺口**，不是偶发超时。
- 本轮在原受保护 journal 独立增加 `cpu_log_identity()`：RUNNING 只读同一持久 InvocationID；EXITED 必须验证同 boot、原 InvocationID/主 PID 与持久 `cpu_terminal_evidence` 精确吻合，才允许访问原 journald；其余 UNKNOWN/重启 boot/不一致仍 HOLD。原 `cpu_identity()` 保持 RUNNING-only，`stop`、启动、中央重派权限完全不变。
- 增加回归：自然终态之后旧日志仍可读取；已停止而 UNKNOWN 不得读取；原中央取消的 HTTP 拒绝码匹配真实语义。
- 修正 CI：不再在 `api` Job 中额外重复跑一次 root systemd 测试；单次受保护 E2E 在 Linux `contract` Job 单独运行。无新增工作流。

本轮修复提交：
- `cbff1846942f83818117d4f8269bf147ae3f698d`：受保护 Journal 的已验终态日志只读身份。
- `a28d705310d82f2497e2064acfa2b67a22eb8194`：`read_log` 改用只读身份校验。
- `c4a55d918f59eb7861b93f8623da5f911bf46870`：取消拒绝码断言。
- `38c5e998bce60a4cfe4b2efda6f9bacdd1c3e40c`：EXITED/UNKNOWN 日志回归。
- `12824cbf6e57ad6e434e7789f356bb493ab53a6c`：Linux Contract 只运行一次 root systemd E2E。

**验收基线为 `12824cbf6e57ad6e434e7789f356bb493ab53a6c`，23 项全仓及 Windows/Ubuntu/API 终态尚未验收，仍不可宣称 23/23 或 Supervisor 已可生产接管。**

### 不可误用的边界
本次日志只读权限只证明 CPU-only、同一可信 systemd InvocationID 的自然终态日志证据；不允许据此授予 StopReceipt、释放 GPU、重新分派、发布模型转换结果或自动恢复。Ubuntu 22.04 systemd249、启动后中央取消竞态/租约持续监督仍是未解决生产阻断。
