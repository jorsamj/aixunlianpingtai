# 畅联云算法训练平台｜2D-2C2 隔离 CPU Supervisor 启动入口消费新鲜中央授权

日期 2026-11-15。唯一开发分支 feature/external-algorithm-publishing。生产 NO-GO。

## 内容
延续 2D-2C1 的后登记 nonce + 中央重新核验原 tasks.attempt/lease 签名：
- 在原受限 Supervisor Unix Socket 协议增加 start_rechecked，严格只接受已有 handle_id、execution_generation 和 launch_envelope；拒绝 shell、路径、env、unit、可执行文件和其它字段。
- SupervisorService 新增仅构造器显式开启的 cpu_prelaunch_recheck_enabled，默认 False。生产 CLI 不暴露此选项，原 legacy 路径不受影响。显式开启后拒绝旧 start 绕过新鲜授权。
- 开启时先 journal.claim_cpu_launch_rechecked()，同一 PREPARED→STARTING CAS，再调用现有固定 CPU systemd 后端并保存原 InvocationID/cgroup/PID。缺失、无效签名、重复请求或启动后 ACK 遗失继续 UNKNOWN/HOLD，永不自动第二次 spawn。
- 使用真实 TaskRepository + ServiceNodeRepository 签名的新 nonce，隔离 fake CPU OS 后端验证 Supervisor dispatch 真实消费该授权、阻断旧启动与重放。与现有 Ubuntu 真 systemd/ORT 分别回归。

## 不可外推
这个独立 RPC 尚未有 Node Agent 的正式调用链，也没有生产的中央网络往返、lease 持续监督、StopReceipt、对象存储上传/最终 CAS、真实 GPU ACL 或 22.04 systemd249 认证。现有 CLI 没有开关接入 start_rechecked。不能将 test-only 功能称为正式模型转换服务或授权生产 supervisor-required。生产 A800/4070 未操作。

## 下一步
准确代码 SHA 通过 Windows/Ubuntu/API/全仓 CI 后，才设计真实中央网络往返和固定 CPU 真实 systemd 联合 E2E；再对接原转换 Runner 的日志/取消/结果闭环，严格保留中央 task owner 与原 lease。

## Exact implementation and CI checkpoint
Functional commit a44499662ee08cc30c35f7b40321443d4e21a734:
- Node Agent push run https://github.com/jorsamj/aixunlianpingtai/actions/runs/43721646308: Ubuntu, Windows and API SUCCESS. Ubuntu contract 620 passed, 2 skipped; real protected systemd + ORT E2E 2 passed.
- Node Agent second run https://github.com/jorsamj/aixunlianpingtai/actions/runs/43721651031: Ubuntu, Windows and API SUCCESS. Windows contract 617 passed, 5 skipped.
- Full repository 23 workflow checkpoint: 22 SUCCESS, Frontend Runtime Stabilization still IN PROGRESS. Do not mark full CI GREEN until the accurate SHA and run have a terminal success.
- This new action is constructor-only opt-in; no production CLI registration, Node Agent Runner, GPU or model-conversion launch. Even when true in isolated tests, old start is rejected. No trusted StopReceipt.
