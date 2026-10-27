# 训练 SQLite 繁忙、租约与跨恢复计时专项

## 基线与授权

用户附件6070a42d及最新衔接指令共同构成正式需求：P0隔离SQLite锁冲突、保持原Lease/fencing/GPU独占；P1统一总历时、累计实际训练耗时、本次执行耗时及最终Worker身份。基线644a1d3be12fc241e842ea5d525dab172f104b6d / VERSION42.24.391，已fetch与远端相同，当前隔离工作树干净。前一ZIP专项已验收，不重建或回退；其他工作树、5944及两份训练模板测试保留。

仅开发/临时SQLite/隔离浏览器，不生产部署、数据库修改、任务重置、Checkpoint删除、真实GPU训练或全目录扫描。生产直接故障证据为2026-10-26 23:02:23北京时间任务train_fa14e58159b94241b63736fb的database is locked；实例续约与release_expired异常退出。实际生产锁持有者尚未确认。

## 已核验调用链与缺口

- task_worker使用AssignmentAwareFencedTaskRepository→FencedTaskRepository→TaskRepository，不能只修改旧兼容heartbeat。
- 原task_runtime/tasks.sqlite3由任务/实例Lease、Scheduler回收/claim、GPU资源、Web任务控制、节点分配及维护共享；与素材、Annotation独立数据库不能混为一谈。
- Scheduler._renew_lease把一次数据库繁忙视为丢租约并终止子进程；renew_instance只捕获PermissionError；serve_forever/run_once的_reap_before_claim异常可退出进程。
- SQLite连接timeout5/busy_timeout5000、FULL/WAL。现有fenced过期回收在BEGIN IMMEDIATE内调用进程检查；GPU准入callback在claim事务内读取payload。它们是代码上可复现的锁放大路径，尚不是生产实际锁持有者结论。
- ResourceTelemetry的monotonic起点仅属于一次进程，训练投影elapsed_seconds与列表“已用时间”混用；前端每秒直接加秒。resume_elapsed_seconds也是恢复执行段，不能冒充跨重启总历时。
- TaskRepository.finish清空worker_id，training_job_projection又直接以该值覆盖task_worker_id，故历史执行身份丢失。不得从日志或任务名推测Worker。

## 最小设计及任务

|阶段|工作|状态|
|---|---|---|
|A|现有事务、租约、计时与Worker合同审计/RED|已验收|
|B|统一有限SQLite繁忙处理；缩短已证实长事务；租约截止与主循环/实例隔离|已完成待验收|
|C|真实训练开始/执行段与结束持久合同，UTC投影与Worker历史|已完成待验收|
|D|列表总历时/详情三时间，原时钟与恢复UI复用|已完成待验收|
|E|必要故障注入/浏览器/审查、提交及准确SHA CI|进行中|

复用原连接、TaskRepository、WorkerContext、ProcessController、GPU原子准入、原训练job/metrics、原列表和PollRegistry。暂定统一忙处理只重试SQLITE_BUSY/SQLITE_LOCKED，限定次数/总预算/抖动，事务回滚及关闭；Lease重试不得越过最后已确认有效期，owner/generation改变立即fence，不伪造续约。过期进程检查/静态payload读取移出写事务，事务内仍核验相同任务修订与所有权；不确定继续保护资源。

总历时=首次真实训练开始至最终结束/当前UTC；累计训练=可信执行段去重之和；本次执行=当前Worker本次接管段。缺证据为未知，排队不计；旧进程秒数仅作为段证据，不能自动充当累计。字段和持久位置待原模型审计确定，不新增平行计时库。后续方案取舍及实际变更在本文件持续更新。

## 验收计划与未验证

使用临时数据库真实BEGIN IMMEDIATE注入短锁/长锁，验证续约预算、所有权变化/过期、GPU/run单执行、实例线程与主循环恢复；真正程序错误不得吞掉。训练时间用2小时执行+1小时中断+3小时恢复证明6/5/3小时，重复事件、多恢复、终态冻结、未知历史/时区/刷新由受影响Python/Node及必要Chrome覆盖。不重复运行全仓测试。

当前已实现以下最小修复，本地定向验收进行中，尚未提交或取得本次远端CI。生产4小时33分钟具体现场字段与真正锁持有者仍需用户授权的轻量定向证据，不执行生产扫描。

## 实际实现与取舍（2026-10-27）

- `task_runtime/sqlite_busy.py`在原连接边界共享一个ContextVar预算，只识别SQLite BUSY/LOCKED；每次SQL等待最多100ms、抖动退避，普通调用总预算5秒，Lease以最后确认期限减250ms为限，次数按最短退避和剩余预算有界。没有延长业务租约或调大busy_timeout。非繁忙SQL错误原样传播；关闭连接回滚失败事务。
- 原WorkerContext序列化续约/绑定/结束/所有权检查，只有最外层重试耗尽才fence；owner/token/generation不匹配仍立即隔离。原训练两个handler不再直接绕过Context续约。实例Lease只在实际UPDATE成功后更新本地确认时间，过期实例不能自行复活；主循环忙冲突退避，实例确认失败停服务并保护精确子进程，不吞真正程序错误。
- Fenced过期进程检查移出写事务，原task/attempt/token/expiry/PID/create-time/hash重新匹配；新过期或不可检查进程继续保护。GPU payload读取移出claim写事务，正式AssignmentAware包装保留prepare，短事务内重读候选、资源和预留，原GPU/node准入与claim仍原子。
- 独立审查指出首次bind不确定窗口：子进程启动后只有本地PID可能不足以保护过期恢复。新增小型`process_start_gate.py`供原训练、断点续训、最终验证三个main复用；通过原任务数据库只读校验token/generation/PID/create-time/hash及有效期后才进入GPU/run业务。未登记到期退出，不建立调度器/新任务或状态库；父进程失败仍按原精确身份终止。
- 原job.json增加`first_started_at`、按generation去重的`training_attempts`，不修改任务库schema。首次真正训练回调记录UTC；原进度写入同时累计实际训练区间，正常训练结束关闭区间，暂停/继续排除暂停时间；AI续段和恢复仍用同一合同。原metrics.monotonic值保留为`current_process_elapsed_seconds`，不再冒充跨恢复历时。
- 原job短写锁避免并发丢失计时片段。暂停API先取该锁后暂停子进程并写入，避免冻结持锁回调。最终Worker来自持久attempt，历史成功成果仅在result.task_id及lineage.task_id双重匹配后复用execution.worker_id；不能确认仍未知。
- 总历时用首次真实开始→最终durable.finished_at/当前UTC；本次执行用本代次接管→最终任务结束/当前UTC（包含最终验证）；累计实际训练只加已记录训练片段。崩溃丢失结束、缺少早期generation时显示“已记录片段，非完整累计”，不把最后采样推算成完整实际训练。旧naive时间、created_at/排队时间不冒充真实首次开始。
- 前端沿原TrainingTaskRuntime/列表/Recovery/时钟。列表“总历时”、本地monotonic锚点避免后台节流漏秒；暂停时总历时继续，终态冻结。详情显示三时间、UTC首末时间和原执行节点。后端明确未知时前端不回退至旧恢复进程秒数。无新轮询或每秒持久化。

替代方案：全局增大SQLite超时不能保证租约安全；吞异常假续约会破坏fencing；新计时表/轮询会产生Owner重复，均不采用。旧任务无完整片段时无法无损还原累计耗时，保留未知/下界。未做破坏性迁移，也未改ZIP、素材、GT、模型、训练参数或调度优先级。

## RED/GREEN与问题闭合

- 第一组5项真实短锁、实例过期、事务内进程检查和主循环RED失败后GREEN；追加长锁到期/代次变化等保护。
- 独立复核4项（并发deadline、停止与claim竞争、128次上限过早截止、raw续约/绑定绕过）各有RED，修复后11项GREEN；实际AssignmentAware GPU payload测试先RED后GREEN。
- 嵌套assert busy新增RED（一次忙立刻fence），改为外层拥有重试后GREEN。
- 真子进程测试证明未绑定期间不进入训练、绑定后进入、未绑定到期失败，无GPU。
- 三时间最初3项RED后GREEN；新增暂停去重、缺代次/中断、验证期间本次执行继续增长。
- 旧projection两条elapsed断言确实失败；更新为总历时未知且原60/75秒仍准确保留在process字段，保留其余进度断言，未降低安全检查。
- 暂停真实子进程持.state.lock场景RED超时，锁顺序修复后GREEN。
- Chrome首次测试脚本错误使用旧tab选择器导致超时，修正为现有`data-training-tab=completed`，5/5通过；不是产品失败被隐藏。

## 本地验收回执（分批，不重复累计）

- 仓库/fencing/GPU/node受影响10文件及当时busy文件：98 passed，0 failed，0 skipped。
- 受影响计时/projection/控制API/overlay及最终busy集合：44 passed，0 failed，0 skipped；后续暂停锁顺序单项GREEN，后续最终相关结果继续补记。
- 原Node runtime/visibility/recovery及新增两项：85 passed，0 failed，0 skipped；缓存引用变更后仅复核必要入口。
- 真Chrome原`training-task-performance.spec.mjs`完整5/5，通过现有隔离后端/受控API数据验证页面，不代表实际GPU训练或生产时长已核准。
- 此前纯13项与其他中间重复执行不累加作为最终总数；最终SHA CI待普通推送后记录，不能借644的21/55绿色。

## 接续与生产边界

生产任务train_fa14e58159b94241b63736fb只读证据尚未取得，本轮未改该任务或Checkpoint。不能断言它的实际首末时间、累计训练时长、最终Worker及锁持有者已被生产核准；4h33对应原单进程计时是代码上的解释，不是现场数据还原。上线前应独立授权只读获取该任务job/TaskRecord、任务限定日志与journal故障前后小窗口；不全盘扫描、不删WAL/SHM、不重置任务。

真实Linux systemd/GPU/NAS/OSS、生产锁持有事务及历史时间回填NOT VERIFIED。失败续约仍可能触发精确停训与后续原恢复，这是必要安全降级，不能为了“不崩溃”容许失效Worker继续持GPU。保留原5944、模板测试和其他工作树。完成代码不等于生产已修复，不部署。

### 提交前限定收尾

最终独立复审确认嵌套busy、绑定前启动、暂停状态锁及恢复验证计时4项闭合，无新交付阻断。GPU采样证据更新也经原Context.run_owned共享确认期限，不改变原SQL和准入。最终相关P0/计时/最终验证37/37、此前checkpoint/projection等55/55分别通过，0失败0跳过（集合重叠，不相加）；最后缓存及Owner守卫33/33通过。新增缓存初次复核发现旧guard两条精确缓存键未更新，原位同步后通过，无断言删除/跳过。

本轮VERSION一次递增42.24.392，main/app入口439；仅修改必要模块缓存和对应原守卫。提交前再次fetch长期分支仍644a1d3be12fc241e842ea5d525dab172f104b6d，无需合并/回退。新实现Commit及远端CI仍待下节补记。

## 远端CI接续（首推不能标绿）

实现提交`1c84424759a0cc53f0ab9fb6feea5a30b9416600`已普通推送长期分支。首轮50 Actions/133 Checks中已发现Frontend及Recovery/Visibility源码守卫失败：原Recovery workflow仍精确要求旧20261022a缓存，原Visibility guard仍精确要求“已用时间/开始时间”表头。仅同步原守卫至实际20261027-timing和“总历时/首次训练开始”，未删/跳过动态断言，也未扩大CI范围。对应Node守卫1/1和两个完整原bash guard退出0；本地首次用过长Windows-c命令截断执行，改为原脚本临时文件后完整执行通过。VERSION保持392，不二次递增。该实现SHA的完整CI与后续修正最终SHA仍继续核验，不能使用首推绿色结论。

### CI中追加发现与最小修正

- 实现SHA的Windows Remote Training准备测试发生`StopIteration`：旧节流fixture全局替换time.monotonic为4值序列，新增真实FileLock也会调用同一系统模块；改为只替换train_worker模块的time引用，原批1/批2不落盘/末批强制刷新断言全部保留。未改变训练节流业务。
- ZIP真实Chrome跨项目fixture用虚拟project-a/b，但读取实际所选项目的全局任务中心缓存，CI先前测试产生3条活动记录后导致期望精确job-b失败。仅该测试等待原启动完成，并为其虚拟项目使用空的同范围任务中心fixture，原生产Runtime/缓存/跨项目保护代码零改动。完整原14场景Chrome35.4秒全部通过；单场景先行也通过。不能把此测试夹具修正说成ZIP业务重做。
- 暂停/继续计时取实际OS操作完成的UTC时刻，不把后续SQLite确认等待算入训练；原控制/节流/计时17项通过，追加实际暂停时刻与滞后写入测试通过。
- 最新代次若尚未初始化Trainer记录，不得借前代Worker或本次开始时间；按durable.attempt严格匹配，缺少证据仍未知。计时/projection14/14通过，0失败0跳过。

以上均保留原安全及动态断言，VERSION392不重复递增。守卫修正`6e864290757be51b64585ea7d6e68589dc693f27`已推送，尚不足以覆盖本节新修正；后续最终SHA必须重新核验CI。
