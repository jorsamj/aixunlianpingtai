# 训练资源准入与安全 Requeue 收口（2026-11-25）

开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；运行期与生产未验收。

基线 aaeebd06c608ab58b2317767dacff2351556606b：用户已独立核验 22 个 PR workflow 全部 SUCCESS，P0-01C 正式结束。本轮实现 SHA 为 13a5cecf79d3ca677929e0f77c356cab19c56e0a；最终含文档 SHA 与一次性 CI 快照见交付消息。唯一分支 feature/external-algorithm-publishing，VERSION 42.24.592 保持。

## 根因与业务语义

历史问题仍存在：资源规划器未利用主机总容量区分理论容量与瞬时余量，RESOURCE_HOST_MEMORY_INSUFFICIENT 进入失败路径；中央虽已有 resource_requirements 和 resource_waiting/resource_wait_reason，但 Agent 没有退回合同。

|语义|本轮行为|
|---|---|
|TEMPORARILY_UNAVAILABLE|理论预算满足但当前余量不足，未启动训练退回 QUEUED/resource_waiting。原节点按 30/60/120/240/300 秒有界退避，其他合法节点可立即参与选择。|
|INCOMPATIBLE|当前节点有效理论预算不满足，考虑其他节点。主机 RAM 不兼容在容量/构建未改变时不重复领取；GPU 短缺退避后重新考虑节点当前其他可用卡。|
|UNKNOWN|缺失、不可靠或过期信息等待新报告，不伪造容量。离线不等于永久不兼容。|
|EXECUTION_FAILED|训练 Worker 已启动后的 OOM 或真实错误保留 FAILED/原停止证明；身份未知不得直接 requeue。|

不新增全局环境/硬件终态阻断捷径，筛选无法证明全体候选不兼容时继续 QUEUED 并保留原因。新分配后清除上一轮等待原因，原启动清理等待投影。

保留原 AUTO 决议算法与配置，不新增降参、CPU 回退、换模型或设备。manual 不降低 batch/workers/cache。原心跳补充有效 RAM 总量/可用量/采样时间，保留原主机字段与在线 TTL；真实主机可用量 0 不被较大 cgroup 余量覆盖，明显未来心跳不作为可信报告。

## 安全事务与回执

在原 v63 Node Executor router 新增 POST/GET /executions/{task_id}/resource-wait，复用原节点 token 认证与 HTTP Client；Agent 不访问中央数据库。

- 原 TaskRepository BEGIN IMMEDIATE 内核验当前 TRAINING/RUNNING、节点 worker、有效 lease/token、attempt、原 execution_started/RELEASED Assignment generation、slot 与 GPU/CPU。
- 严格核对原 no-launch evidence 的字段类型及摘要，中央 ProcessIdentity 任一字段存在即拒绝；Agent 同时检查本地启动边界、持久意图与身份。
- 双槽必须存在同节点/attempt/Assignment/GPU 的原 Hold。HELD 不得有冲突 proof；STOP_VERIFIED 必须匹配 NO_PROCESS_LAUNCHED 与重算 digest。Hold RELEASED、任务回 QUEUED/清 lease、等待原因和 Assignment 回执同事务提交；失败回滚。
- 回执复用 Assignment resolved_execution_config，保存请求摘要、attempt、GPU、slot、proof digest、retry_after 与节点容量证据；无新表/字段/attempt Owner。
- 完全相同的旧请求只读原回执，不修改已开始的新 attempt；异体重放冲突。CANCEL_REQUESTED 拒绝 requeue，取消竞争走原 CANCELLED 结算。
- 响应丢失后 GET 原 Assignment 回执，不借用当前其他 attempt 的状态。Agent 与双槽回收核对身份、slot、请求摘要、NO_PROCESS_LAUNCHED 和 digest，才释放本地容量。
- 回查持续不可用则 fenced，保留 resource-wait-request.json；不冒充成功、不以 FAILED 覆盖未知结果、不强制释放或无限重试。原请求可供后续核验/精确重放；失效 lease 或新 attempt 继续拒写。
- 双槽退回后进入单槽节点，新启动事务仅清理旧 RELEASED Hold，原 proof 留在 Assignment 回执；未释放 Hold 仍阻断启动。

## 定向验证

原 API 用例补充单/双槽原子退回、重复/异体请求、另一节点新 attempt 后旧请求不改资源、取消/旧 attempt/错误节点/lease/Assignment/GPU、已启动身份、未知或类型伪装 proof、缺 Hold 拒绝后的数据库逐行不变。

原 HTTP Runner E2E 增加临时不足、响应丢失、回查失败保留证据与取消竞争；原 Worker 失败用例增加启动后 OOM，断言 FAILED 且无 requeue 回执。既有硬准入/资源决议/双槽回收测试增加资源分型、其他节点选择、精确 proof 才释放。原 Node Agent Executor contract Job 增加执行已有 test_w7a_hard_admission.py，无新 workflow。

本机仅源码/静态检查、15 个修改 Python 文件的 python -m py_compile、git diff --check 通过；未运行 pytest、测试函数、自检服务、浏览器、构建、Docker/WSL 或 GPU。运行期断言全部待 GitHub-hosted CI，不宣称测试通过。

job.json 检查：train_worker 的 --execution-attempt 仍取 TaskRuntime attempt；training_timing.update_job_record 在原共享锁内以 _superseded_by_newer_attempt 拒绝旧 generation 写入。可退回分支尚未启动训练 Worker，身份未知不可退回，未发现本轮需修改该栅栏的缺陷，因此保持源码与原守卫。

前端未改：原 TrainingTasks 详情和 training_job_projection 已展示 resource_wait_reason，等待与失败沿原状态区分，无布局/入口调整。四份保护文档开工及收尾哈希匹配用户基线，保留未跟踪状态。

## 交付边界

最终 SHA 正常推送后核验远端，只查询一次 CI，不轮询、取消或重跑。暂无已知源码阻断；准确 SHA CI、运行期效果和 GPT 独立审计待完成。网络持续不可用的保守 fenced 边界见上文，不提供强制释放入口。

未访问 A800/4070、生产服务/数据/权重，未启用双槽、自动清理、supervisor-required 或 PostgreSQL 切换；无 Vue/UI 整体迁移。完成后停止，交 GPT 独立审计。

## 2026-11-25 持久资源等待请求的重启恢复（A）

实现 dd8ee530924e79b87ed876d309b4dc0017d650bc；以用户已验收的 21fb70de 为基线，仅补之前未直接消费 resource-wait-request.json 的缺口。开发 FUNCTIONAL_COMPLETE / 本轮验收 CI_PENDING。

原 Workdir 严格核验路径、请求结构、原 TRAINING 执行元数据、节点/Assignment/attempt/GPU/slot 与 no-launch 摘要；存在进程身份、启动意图或冲突停止证据即拒绝。通用 cleanup 不再删除未结算请求。凭据仅留原受保护请求文件，不进入恢复错误文本、普通日志或交付记录。

原 NodeRecoveryCoordinator 先查原 Assignment 回执；中央任务进入其他 attempt 时仍核验该原回执。只有明确 RESOURCE_WAIT_RECEIPT_NOT_FOUND/404 才精确重放原请求，由原中央事务判断节点、有效 lease、attempt 与取消竞争；不改已验收中央合同。重放响应丢失后再读原回执；中央不可用进入原 retryable/有界重查机制。损坏、冲突、取消或身份未知永久 fail-closed，证据保留。

仅当 resource_wait_receipt_error 完整验证成功后先清理对应旧 slot intent，再按请求摘要删除原请求；新 Assignment intent 保留。单/双槽与重启容量在原 BoundedExecutionSlots 一致核验。原 Runner 的成功/已确认取消路径经同一 Workdir 清除原请求，避免被新 cleanup 保护误判为未结算。

现有恢复测试增加真实 Workdir 的单/双槽回执、新 attempt、精确重放/响应丢失、中央不可用后同实例恢复、取消及损坏/错误节点/GPU/启动/坏 proof 拒绝、cleanup 证据保护和容量一致性。语法/定向静态检查通过，运行期测试未本机执行，交现有 CI；不宣称通过。
