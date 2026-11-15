# 畅联云算法训练平台｜2D-2C1 中央执行租约启动前复核

2026-11-15。唯一分支 feature/external-algorithm-publishing。生产 NO-GO。

## 发现的实际缺口
原 claim_cpu_launch() 只核对初始 intent 的签名授权，未在 OS spawn 之前重新查询中央 tasks.attempt / 租约。若初始签名到 systemd 启动之间任务取消、lease 被轮换或节点被禁用，旧授权仍可能在有效期内通过。不能称作完整中央权威接管。

## 本次独立 CPU 试点合同
扩展本机 protected ExecutionJournal 的 cpu_launch_challenges 表，不新建中央调度器：
1. 已保存 PREPARED intent 后，issue_cpu_launch_challenge() 为既有 handle + task_attempt 生成单一持久 nonce，15 秒过期。重复调用在有效期内返回同一 nonce；过期后 HOLD，不创造第二 OS handle。
2. 中央复用现有 CentralExecutionGrantIssuer.issue()，从原 TaskRepository 与 service_nodes 实时读取当前 tasks.attempt、worker_id、lease_token、lease_expires_at、节点 enabled/heartbeat/capability 和固定 CPU profile，然后签署新 nonce。原 lease/token 与中央所有权不改。
3. claim_cpu_launch_rechecked() 仅接收与登记授权不同、对同一受保护 handle 挑战有效的中央签名，要求中央签发时间不早于新挑战、与 OS 验证时间差不超过三秒；绑定原 task、attempt、node、lease 摘要、boot、fixed-cpu-v1、CPU_ONLY。单次 SQLite BEGIN IMMEDIATE 将 PREPARED 转为 STARTING，重复启动拒绝。
4. 合同 CI 覆盖成功、重启重放、取消/attempt 变更/租约轮换或失效/节点禁用、旧签名或伪造签名、错误 handle 与过期。未接入 SupervisorService 的 start RPC，也不接正式业务模型转换。

## 严格边界
本轮仅为中央与受保护本机 journal 之间的隔离合同验证。启动前另取中央授权可以缩小旧授权窗口，但签名发出后仍有短暂取消竞态；还需真实网络往返、运行中的租约持续监督、失联后取消与完整停止证据。不要称为零竞态或生产可恢复。
未引入第二套任务 owner、分配代数、GPU reservation、正式 MODEL_CONVERSION Runner、业务 API 生产开关、前端重构或 StopReceipt；legacy 保持原状。Ubuntu 22.04 的 systemd249 尚未通过兼容性认证；A800/双4070 完全未操作。

## 下一步
准确代码 SHA 的 Windows/Ubuntu/API/全仓 CI 终态审计；后续在独立 CPU 测试链路使用这份授权，验证真实网络时序、OS launch、取消、日志和结果 SHA，正式接线仍需单独准入。
