# P0-01C 最终定向收口（2026-11-25）

开发状态：`FUNCTIONAL_COMPLETE`；验收状态：`CI_PENDING`。运行期测试未在本机执行，不代表 CI 或生产验收通过。

- 起始 SHA：`8d2c7fe9486f547c6758491e8997f68959aa9707`。
- 实现 SHA：`b8c61ec6d0218ee1958aee82ec9aeafec015b9e7`。最终交付 SHA（含文档）及准确 CI 快照见交付消息。
- 唯一目录/分支：`D:\lab\p2b2-backend` / `feature/external-algorithm-publishing`；VERSION 保持 `42.24.592`。

## 根因与最小修改

A. `AgentExecutionService._settle_single_slot_recovery` 原查询可取得其他节点 Assignment，活跃任务 CAS 未绑定 worker。现于原 `BEGIN IMMEDIATE` 内读取当前 Assignment，核验 node、generation、attempt、slot、GPU/CPU 与已登记 ProcessIdentity；身份登记和终态 CAS 均绑定 `agent:<node_id>`。正式元数据缺失/损坏、generation=0、GPU 缺失不得冒充 legacy。真实 pre-marker legacy 和 CPU 保留，终态重复恢复不覆盖原状态。`recover_execution` 严格拒绝布尔/字符串 PID、非正/非有限创建时间和非 SHA256 command hash。

B. 训练/转换 `_execution_record` 原先因缺 ProcessIdentity 直接拒绝启动前失败结算。现使用原持久启动意图、持久身份和内存启动边界区分已启动、证明未启动、身份未知；不生成假 PID。身份未知时 `_finish_best_effort` 不调用 finish。双槽未启动仍必须有同身份 Hold、NO_PROCESS_LAUNCHED 类型、重新计算匹配的 proof digest 和 RELEASED 状态；原业务错误保留。

C. `node_agent_settlement` 不再把正式 Assignment 的缺失 state 当作 RELEASED；核验本地与中央 slot，中央 slot=2 时缺 Hold 必须拒绝。`execution_status` 原有三次独立数据库读取可能拼接不同 attempt 的 Task/Identity/Assignment/Hold，现全部在一个只读事务快照内读取。未重写 Coordinator、Repository 或执行循环。

D. 嵌套取消用例在下载失败时设置原 monitor 的 cancel 事件，明确进入通用异常内的取消分支，断言只提交一次 CANCELLED 且中央仍 RUNNING 时 fenced。finish 响应丢失用例参数化完整回查、回查不可用、坏 digest：完整证明允许成功，其余 fenced 并保留本地身份和停止证据；所有分支均保留 finished_at、attempt、ProcessIdentity、Hold、真实 proof digest、FAILED/CANCELLED 不可覆盖和单行数量断言，Runner 只提交一次 SUCCEEDED。

## 验证边界

- 仅读取用户指定的三个失败 Ubuntu Job 日志：139152499828、139152500653、139152501868；没有读取成功 Job 日志。
- 本机允许的源码检查、九个修改 Python 文件 `python -m py_compile`、`git diff --check` 已通过。
- 未运行 pytest、测试函数、运行期自检、浏览器、Docker/WSL、服务或构建。
- 既有测试文件补充真实 SQLite 跨节点/worker/旧 attempt 拒绝和资源逐行不变、正式元数据/ProcessIdentity 校验、GPU/CPU/legacy 幂等、缺失 Assignment state/slot/Hold、双槽真实 no-launch proof、训练/转换未知启动禁止 finish。复用现有 CI，没有新 workflow。
- 基线 8d2c7fe9 的用户已核事实为 22 个 PR workflow 中 19 SUCCESS / 3 FAILURE；不能用于验收新提交。
- 推送后仅按最终 SHA 查询一次 CI，未完成如实报告 CI_PENDING，不轮询、取消或重跑 Actions。
- 四份保护文档开工哈希均与用户基线一致，收尾再次核对；不修改或提交这些文档，保留其未跟踪状态。

## 未验证与下一步

运行期修复效果、准确最终 SHA 的 CI 和独立 GPT 审计尚未验收。无已知源码阻断；如 CI 失败，后续只分析实际失败 Job。本轮结束后停止，交 GPT 独立审计。

未访问 A800/4070/生产，无部署、正式数据/权重写入、双槽启用、supervisor-required、PostgreSQL 切换、Vue/UI 或其他迁移。唯一 Owner、lease/attempt/fencing、legacy Runner 和现有 API 保留。
