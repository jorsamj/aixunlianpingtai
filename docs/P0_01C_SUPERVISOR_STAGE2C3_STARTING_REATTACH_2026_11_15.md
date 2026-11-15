# 畅联云算法训练平台｜Supervisor 2C-3：STARTING 崩溃窗口的同一 OS 身份回查

> 日期：2026-11-15（Asia/Singapore）  
> 唯一长期开发分支：`feature/external-algorithm-publishing`  
> 首轮功能提交：`8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da`  
> 运行范围：**仅独立固定 CPU 测试单元，非生产，非 GPU**

## 1. 已复现的故障窗口

1. 中央已有原执行租约和唯一 `tasks.attempt`，OS journal `execution_intents` 在系统调用前经 SQLite FULL-sync 提交 `PREPARED→STARTING`；禁止再次发起同一任务的 launch。
2. `systemd-run` 实际创建 `changlian-os-<handle_id>.service`，固定 CPU 程序进入 RUNNING；Supervisor 进程在 `record_cpu_identity` 的事务提交前崩溃或被终止。
3. 以前 journal 剩下 `STARTING` 且没有 `cpu_unit_identities`，重启后 `cpu_identity()` 失败，inspect 只能 UNKNOWN/HOLD；不能证明原进程已停止，也不能再启动第二个 unit。

本阶段仅恢复**仍在运行且 OS 保护身份符合原登记边界**的固定 CPU systemd 服务登记，不扩展到原身份已消失、已终止、被 GC 或不明进程的可信停止。

## 2. 实际代码变更

- `platform_core/os_supervisor_journal.py`：新增 `starting_cpu_unit` 只读查询原 boot、任务 attempt 和持久记录的预留 unit；强制 state=STARTING、unit 与 handle 的确定性绑定、尚无任何 OS identity 记录。既有 `record_cpu_identity` 接纳 RUNNING 状态下完全一致的幂等写入，并拒绝不同 PID/InvocationID/cgroup；沿用本地 SQLite 事务和原 `event_seq`。
- `platform_core/os_supervisor_service.py`：仅 inspect 读取原 journal 失败时尝试上项 STARTING 查找；调用实际 `FixedCpuSystemd.snapshot(..., require_running=True)`，核对旧 unit、原 cgroup、`MainPID == ExecMainPID` 与既有保护属性，之后才将同一 InvocationID 写入原 journal 并用 `inspect` 再读 OS；不存在重新调用 `systemd-run` 的路径。
- `tests/unit/test_os_supervisor_cpu_journal.py`：验证 lost-write 后恢复同一 OS identity、幂等记录不重增事件、原 grant 重发不能再次启动、缺失 unit/变 boot/伪 PID/cgroup/保护降级/UNKNOWN 全部 HOLD。
- `tests/integration/test_os_supervisor_cpu_systemd_live.py`：真实 Linux root+systemd 上先完成原 CAS，再实际启动固定 CPU unit，刻意不写 InvocationID，构造新的 Supervisor + journal 重新打开并 inspect，验证同一真实 InvocationID 被识别并且不能二次启动。该测试以 `systemctl stop` 清理**仅随机生成的隔离测试 unit**。

## 3. CI 证据与准确口径

- 2C-2 基线：`f121d9bdee6f2fc3b5e918dc73bc6a15a3f5bc3b` 已证实 23/23 workflows 成功，包括历史前端失败 Job 的 attempt 2 成功。
- 本轮功能 SHA：[`8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da`](https://github.com/jorsamj/aixunlianpingtai/commit/8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da)。GitHub 同 SHA **23/23 次工作流最终成功**。[Node Agent push 43708219773](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708219773) Ubuntu 主合同 **565 passed / 2 skipped**，POSIX SIGKILL **2 passed**，cgroup **31 passed**，真实 systemd E2E **4 passed**；Windows 和 API Job 成功。Node Agent [PR run 43708221724](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708221724)、[Portable Deployment 43708221554](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708221554)、[Frontend Runtime Stabilization 43708219738](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708219738) 也均 completed/success。以上只表明本轮代码在隔离 CPU 系统级/可移植合同的验收完成，不代表生产 GPU 可信停机。
- 其它核对入口：[Node Agent PR run 43708221724](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708221724)、[Portable Deployment 43708221554](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708221554)。

## 4. 不可越过的生产准入

1. `start` 仍仅接受原中央 15 秒 Ed25519 CPU grant + journal CAS，**本轮 inspect 不签发 grant、不创建任务、不允许重复启动进程**。
2. 原系统运行方式默认 `legacy`，`supervisor-required` 仍阻止正式训练/转换/推理 Runner；不会触碰生产 A800 / 双4070、Worker、GPU runtime、素材或数据表。
3. 任何跨 boot、原 unit 被回收、已退出但无原 main PID、OS 属性不完整的场景继续 `UNKNOWN/HOLD`。即使 CPU-only 身份成功补写 RUNNING，也**不能**签发 StopReceipt 或解除原 `REMOTE_AGENT_STOP_UNVERIFIED` 阻断。
4. 该固定 CPU 使用 `ExitType=cgroup`、`RemainAfterExit` 等 systemd 250+ 机制；不能因为 GitHub 24.04 已通过就声称 A800/4070 Ubuntu 22.04 上可以部署。

## 5. 仍待开展

完成本 SHA Ubuntu/Windows/Portable/全仓 CI 核对；之后专项审核 OS 启动异常/日志缺失与短期授权过期的竞争、单独编制 Supervisor 真实硬件适配的安全设计，最后才考虑**一个非 GPU 模型转换 Runner**灰度接线。绝不可把单测、CPU E2E、远端 Agent 生产认证和自动恢复混为一谈。


## 6. 本阶段最终验收及交接

2C-3 准确代码 SHA `8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da` 的 **23/23 workflows 全部 success**（包括 Node Agent push/PR、Portable Deployment、Frontend Runtime Stabilization）。版本 `legacy` 默认不变，OS 信任范围仅固定 CPU，尚无真实业务 Runner 接线、可供中央资源释放的 StopReceipt 或生产 GPU 隔离凭据。请将这份功能提交作为下一轮的已验收代码基线，文档 HEAD 只记录结果，不能冒充重跑过业务代码的 CI。
