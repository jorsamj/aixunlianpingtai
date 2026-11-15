# P0-01C｜Supervisor 2C-2 固定 CPU 退出终态与持久证据（2026-11-15）

**性质：独立 CPU-only OS 执行边界逐步完善，不是正式 Runner 适配，不是可上线安全恢复。**

## 1. 开发缘由与冻结边界

2C-1 已解决挑战容量与日志游标；2B 通过原签名 grant、SQLite CAS、固定 systemd CPU 程序、单次启动实现 RUNNING，但自然退出时 inspect 只能得到 UNKNOWN/HOLD。现在限定补齐自然退出状态核验和原本 journal 中的 EXITED 终态，不新增中央 Scheduler、Owner、Task Attempt 或 GPU 回收权限。

唯一开发分支：`feature/external-algorithm-publishing`。生产 A800、双4070 均未操作。原 `legacy` 模式、`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、中央自动派单 OFF、StopReceipt 禁用保持不变。

## 2. 本次代码范围和安全策略

1. `platform_core/os_supervisor_cpu_systemd.py`：固定测试程序依旧硬编码、无可配置 shell/cwd/env/GPU。systemd 增加 `ExitType=cgroup`、`RemainAfterExit=yes`、`Restart=no`；核对 unit/InvocationID/原 main PID、systemd 进程终态、原 cgroup 边界和 ExecMainCode/ExecMainStatus/Result 一致性。不允许 `systemctl stop` ACK、仅 leader 退出、不同 InvocationID、被回收的 transient unit、残留服务状态伪造 `EXITED`。由于 `ExitType=cgroup` 依赖 systemd 250+，该 CPU-only 候选不能视作 Ubuntu 22.04 生产适配。
2. `platform_core/os_supervisor_journal.py`：在原 root-only FULL-sync SQLite 中追加 `cpu_terminal_evidence`，仅同任务、原 `tasks.attempt`、原 boot、持久 InvocationID、原进程身份匹配且 `RUNNING` 时，单事务写入不可重置 `EXITED` 和退出证据；重复同证据幂等，跨代、换身份、UNKNOWN 均拒绝。
3. `platform_core/os_supervisor_service.py`：inspect 优先查实际 systemd；只在严格成功时记录终态并返回退出码，系统证据丢失仍 HOLD；Supervisor 重启仅从原 journal 读取已持久登记的 CPU 终态。
4. 测试：覆盖原单元回归、凭据不一致、仍在运行、unit identity 串线及真实 Ubuntu 24.04 固定 CPU 程序自然结束 25 秒后的同代终态、持久重读、防二次启动。已有 Ubuntu 真 systemd 启停测试仍保留。

## 3. 精确代码/CI 证据

- 前一完成的 2C-1 代码 SHA：`40bc388adc05ba3be05a7b986c0c89b1e3d0e423`，历史 23/23 workflows SUCCESS。
- 本轮首次功能 SHA：`6511cba9ca4e9d8a5f4ab5c2fa371ac04d6ce35f`，旧 FakeSystemd 缺新属性导致部分新约束单测 RED；不是 OS 真实启停验收结果。
- 修正单元测试 fake 的提交：`f121d9bdee6f2fc3b5e918dc73bc6a15a3f5bc3b`。该 SHA [Node Agent Executor 43706279911](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706279911) Ubuntu/Windows/API 三 Job 完成 SUCCESS；Ubuntu 563 passed/2 skipped + 2 POSIX + 31 cgroup + 3 项**真实系统级 systemd E2E PASS**，Windows 560 passed/5 skipped + 30 cgroup/1 skipped，API 24 PASS。同 SHA [Portable Deployment 43706279826](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706279826) Ubuntu/Windows/API 全成功。**2C-2 核心 CPU-only 代码和 CI 正式 GREEN；不代表 GPU 可信停机、真实 Runner 或仓库所有工作流已绿。**

## 4. 必须保留的剩余风险

- 没有实际 A800/4070 上的 GPU 设备访问强制隔离，也没有受保护 StopReceipt、中央可信自动恢复、原租约实时 recheck 或真实训练/转换/复核任务接线。
- systemd 执行终态是**固定、短时、不生成后代的 CPU 测试程序**的证据。虽然 `ExitType=cgroup` 比单个 leader 退出更严格，仍不能替代真实多后代、GPU/CUDA/SDK、网络分区的生产安全验收。
- 同一原任务如果在 `STARTING` 已 spawn 但未登记 InvocationID，仍必须 HOLD，不得第二次启动。
- 原业务 UI、远程计算 Runner、task owner、数据层和部署脚本未修改；生产部署仍须单独授权。

## 5. 下一动作

2C-2 核心 Node Agent 和 Portable Deployment 已按准确 SHA 验收通过；下一步优先核实独立前端失败 Job 的定向重跑终态，之后再审核 STARTING 崩溃窗口与实际 Runner 适配。随后继续异常恢复窗口、信任材料管理及首个非 GPU 转换 Runner 隔离适配，不能先改生产执行开关。


## 6. 仓库级 CI 非核心失败单独追踪

准确功能 SHA `f121d9bdee6f2fc3b5e918dc73bc6a15a3f5bc3b` 的 [Frontend Runtime Stabilization run 43706274712](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706274712) 初次完成结果包含 **browser-navigation (1) FAILED**，根因为已在历史前端分支复现的 `tests/browser/annotorious-poc.spec.mjs:42` 创建 `createAnnotation` 事件等待 5 秒超时；该分片 130 个浏览器用例通过、1 个失败。该测试不调用本轮 Supervisor 的 CPU 执行逻辑。本轮没有为此修改 Annotorious 或前端测试，已在同 SHA 的失败 Job 上发起一次定向 rerun。**重跑仍需以 GitHub 最终状态为准，不预判 GREEN。**


## 7. 2C-2 全仓同 SHA 最终验收补录（2026-11-15）

功能代码 `f121d9bdee6f2fc3b5e918dc73bc6a15a3f5bc3b` 对应 **23/23 GitHub workflow runs 全部 SUCCESS**。历史 Frontend Runtime Stabilization [run 43706274712](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706274712) 的 browser-navigation (1) 初次失败在 GitHub Actions **run_attempt=2** 的定向 Job 重跑通过；故上一段关于“重跑待核实”的记录仅为历史执行过程，不代表最终状态。该 SHA 是 2C-2 版本的完成基线，不替代后续 2C-3 新代码 CI。
