# P2B-4A-1A Scheduler 重复恢复优化（2026-11-18）

基线与fetch远端均为5ac4001617d9261cfecef96ae7ca77627b05f131，唯一feature/external-algorithm-publishing，隔离副本起点干净。VERSION保持42.24.592。上轮只读审计未授权删除恢复；本轮用户明确授权在claim内完整恢复、保留空Handler与旧Repository兼容的条件下跳过外层恢复。本记录取代上轮对该方案尚无证明的暂缓结论，不删除历史证据。

## 最小实现与调用关系

- repository.py：TaskRepository增加类属性claim_recovers_expired=True，声明非空kind的claim_next执行事务内恢复。未来覆盖claim_next但不履行该合同的子类必须显式设False。
- scheduler.py：_reap_before_claim先执行原reap_expired_processes；仅当handlers非空且能力标记严格为True时跳过release_expired。无标记/False或空handlers仍原样调用公开恢复。不使用truthy判定，不捕获异常，不引入缓存/全局状态。
- tests/unit/task_runtime/test_scheduler.py：新增覆盖TaskRepository、Fenced、AssignmentAware三种真实SQLite仓库，有/无handlers时无匹配候选仍恢复过期任务，随后匹配Handler正常重新领取、attempt递增并完成；无标记旧实现验证reap→release→claim顺序。原断言保留。

之前：reap → release(观察+恢复事务) → AssignmentAware.claim → Fenced观察 → TaskRepository初始恢复事务 → payload读取 → 候选后恢复/状态资源复核/原子领取。
之后（正常非空handlers能力路径）：reap → AssignmentAware.claim → Fenced观察 → TaskRepository初始恢复事务 → payload读取 → 候选后恢复/状态资源复核/原子领取。空handlers/旧实现保持之前路径。

实际初始化审计：生产task_worker.py:210使用:113创建的AssignmentAwareFencedTaskRepository，两层claim均super到TaskRepository。其余tools/verify_smart_material_audit_task.py和测试使用TaskRepository/Fenced或app.shared_task_repository(TaskRepository)。未发现覆盖claim但不执行super的实际子类；tests/unit/test_launcher_workers.py有Scheduler(None,..,{})构造，但并非有效运行仓库，不改变其构造合同。

Fenced/AssignmentAware代码完全未改。保留事务外OS观察、_PROCESS_OBSERVATIONS完整身份键、PID/create_time/hash检查与terminate_tree，保留Agent stop-unverified和alive/unknown资源hold及GPU独占、attempt/token fencing。初始与payload后事务恢复和BEGIN IMMEDIATE均未修改。优化只省去外层公开恢复，未删除claim内观察或二次复核。空Handler特别保留公开恢复，因为空kinds claim会提前返回。

## 实测

仓库外delivery-evidence/p2b4a1a含measure.py、before.json、after.json及逐次SQL。相同脚本与场景：每组前后各3次独立临时SQLite WAL，真实生产AssignmentAware仓库，idle为空库，claim为一条DEPLOYMENT_TEST和立即成功的测试Handler。无生产、GPU训练、外部Agent。耗时为完整run_once，不是单独claim_next或生产P95；SQL Trace挂在_connect返回后，排除连接内部PRAGMA。

计数key：connect=Repository连接，reap=回收调用，release=公开恢复调用，observe=事务外观察，in_transaction_recovery=事务内恢复，sql=可追踪SQL，begin=BEGIN IMMEDIATE。

| 场景 | 前计数 | 后计数 | run_once毫秒中位数 |
|---|---|---|---|
| idle | {'connect': 5, 'reap': 1, 'release': 1, 'observe': 2, 'in_transaction_recovery': 2, 'sql': 12, 'begin': 2} | {'connect': 3, 'reap': 1, 'release': 0, 'observe': 1, 'in_transaction_recovery': 1, 'sql': 7, 'begin': 1} | 17.92 → 10.97 |
| claim | {'connect': 11, 'reap': 1, 'release': 1, 'observe': 2, 'in_transaction_recovery': 3, 'sql': 34, 'begin': 3} | {'connect': 9, 'reap': 1, 'release': 0, 'observe': 1, 'in_transaction_recovery': 2, 'sql': 29, 'begin': 2} | 37.66 → 44.08 |

每次计数均一致。正常空闲少2连接/5条SQL/1次写事务，正常领取同样少2/5/1；reaper仍1次，进程观察仍1次，初始恢复保留1次，领取额外保留候选后恢复1次。领取耗时中位数变差，样本小且有文件/线程波动，不能宣称领取延迟改善。未测生产锁等待分布，不把少一次写事务等同生产竞争收益。

## 验证与交付边界

测试先在原实现复现“外层release仍1次”失败，再最小实施。

`python -m pytest -q --confcutdir=tests/unit/task_runtime tests/unit/task_runtime/test_scheduler.py tests/unit/task_runtime/test_repository.py tests/unit/task_runtime/test_fencing.py tests/unit/task_runtime/test_resource_fencing.py tests/unit/task_runtime/test_gpu_recovery_fencing.py tests/unit/task_runtime/test_sqlite_busy_recovery.py --disable-warnings --tb=short`：67 passed，0失败/跳过，16.41s。

随后仅补强新测试中的真实重新领取/attempt=2完成断言，复跑受影响文件：`python -m pytest -q --confcutdir=tests/unit/task_runtime tests/unit/task_runtime/test_scheduler.py --disable-warnings --tb=short`：11 passed，0失败/跳过，1.61s；不将重复用例累计为78项。原安全测试覆盖PID复用、活进程GPU保留、Agent未确认停止、SQLite Busy恢复/闭锁。没有修改Worker启动路径，不跑启动集成或全仓/浏览器。

py_compile（scheduler/repository/对应测试）及git diff --check通过。原菜单、页面、按钮、业务操作链路源码不变，不接触A800/4070/生产数据。准确提交SHA和CI状态见最终交付；运行中不宣称验收通过，不降低断言/强推/合并/发Release。完成后停止。

回退：普通git revert本专项提交并正常推送；无Schema或业务数据迁移。候选payload后的恢复仍保留，其他扫描优化/候选分页不在本轮。未来覆盖claim的子类能力声明需评审，不能继承标记后静默失去恢复。

协作：gpt-6.1-sol只读核对Scheduler初始化与仓库类型；主模型独立复核实际Diff、实现、测试/Trace及Git交付。
