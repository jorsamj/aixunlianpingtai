# P2B-3B 任务读取性能（2026-11-18）

起点/远端：9c257079d1b861ecd9418635828dbc8d42620ccb；feature/external-algorithm-publishing，VERSION 42.24.592保持。隔离副本干净，其他工作树/诊断工具保留。实际交付提交以本文件所属Git提交及最终交付SHA为准；本地代码完成与准确SHA CI、生产验收分开报告。

## 精确审计与最小设计

| 问题 | 当前证据/影响 | 本轮决定 | 风险 |
|---|---|---|---|
| 位置N+1 | task_to_public对每个QUEUED调用scalar，分别连接、SELECT任务和COUNT；普通列表、单任务、app各业务投影均有调用 | 已确认并修复普通v62列表：新增resource_queue_positions，单语句批量读取 | 仍为每个ID的相关COUNT，未宣称消除库内所有重复扫描；索引与Schema不变 |
| 全局候选 | queued_candidates全量TaskRecord；public exact/training truth与app训练/转换投影使用完整跨项目证据 | 暂缓精简；本轮保留原返回类型、全局排序及全量范围 | 轻量投影需新内部类型及各调用者合同，截断会破坏跨资源领取证明 |
| Worker读取 | list_runtime还调用load_node_cache_reports，队列证明只需要online/task_kinds/capabilities | 暂缓窄投影；公共Worker响应及material_cache不改 | 需另行验证可选窄读取与原API兼容，不引入跨请求缓存 |

P2B-3A已经跳过不需要精确性证据的Worker/候选读取，本轮不重复改写。源码调用方搜索覆盖task_to_public、scalar位置与queued_candidates；其他调用方继续原接口。现有PerformanceDiagnostics/observe_connection提供可选连接与SQL观测，v62详情有端点分类，列表不新增诊断协议。现有idx_task_resource(resource_key,status,lease_expires_at)、任务主键用于本查询；SQLite 3.45.3 EXPLAIN显示主键搜索t、相关子查询使用idx_task_resource，无全表peer扫描。没有使用窗口函数，无新增SQLite特性门槛。

## 实施和功能保护

- repository.py增加批量只读接口：最多消费101个输入以判断100条上限，去重、绑定参数，空集合不连接；缺任务KeyError，非QUEUED映射None。原scalar接口保持原样。任务不存在、并发非排队和未知投影证据不冒充位置。
- 一个SELECT内相关COUNT沿用priority升序、queue_rank降序、created_at升序、task_id升序，在同resource_key的全项目QUEUED集合计算位置。单条SQLite语句使用同一读快照；没有分块或逐ID连接。
- public.py仅task_to_public新增可选queue_positions映射；未传仍调用原scalar。None证据仍保守不证明exact，原_non_training_queue_position_exact/training_queue_truth不改。
- query_api.py在普通页批量读QUEUED位置并传原投影；reader_view、详情、Session/项目检查/URL/JSON/游标和排序不改。没有第二Owner、调度器或缓存。
- 修改文件：以上3源码、tests/unit/task_runtime/test_repository.py、tests/api/test_core_productization_views.py、本专项及功能保护台账。无app.py/Worker/Agent/Supervisor/GPU/GT/执行状态写逻辑/Schema/前端改动。

## 真实SQLite前后证据

同两份临时库含100/1000 QUEUED，另各25/250混合RUNNING/CANCELLED/FAILED；多项目、4资源、7优先级、5种queue_rank、相同created_at。采用原真实Repository/Router端点函数、kind=TRAINING、limit=100；鉴权和HTTP传输开销未纳入计时，不能称完整网络请求延迟。每场景前后各3次，全部样本均保留，表中耗时取中位数。

| 排队总数 / 返回条数 | 连接数 前→后 | SQL 前→后 | 端点总耗时ms 前→后 | 独立完整候选查询ms 前→后 | 返回JSON |
|---|---|---|---|---|---|
| 100 / 66 | 67 → 2 | 133 → 2 | 93.56 → 3.64 | 2.25 → 2.19 | 40466，SHA256一致 |
| 1000 / 100 | 101 → 2 | 201 → 2 | 145.08 → 8.77 | 12.77 → 12.65 | 61439，SHA256一致 |

SQL为_connect返回后set_trace_callback实际观察到的语句数，不包括_connect内部两条PRAGMA；按每连接两条PRAGMA计完整数量分别为267→6、403→6。队列证据耗时单独测量，未计入该TRAINING页（P2B-3A本就跳过该读取），本轮未优化完整候选成本；其波动不算收益。响应按完整排序JSON摘要与字节数核对相同，无缩减字段。原始3次结果、脚本及执行计划在本机delivery-evidence/p2b3b/{measure.py,before.json,after.json,plan.txt}，库仅合成测试数据，不提交数据库。没有生产P95或硬件性能声明。

## 定向验证

最终一次命令：`python -m pytest -q --confcutdir=tests/api tests/api/test_core_productization_views.py tests/unit/task_runtime/test_repository.py tests/unit/task_runtime/test_public_projection.py --disable-warnings --tb=short`：54 passed，8项既有on_event警告，不累计先前重复执行。新批量测试先因接口不存在失败；首次实施脚本因Windows默认GBK未落盘，纠正为UTF-8；新增测试误用cancel名称已修为原request_cancel，未改生产取消逻辑或既有断言。

覆盖原完整投影HTTP/权限/隔离、P2B-3A9场景、禁止scalar逐任务读取、空/重复/超量/缺失ID、非QUEUED、取消后位置、同时间/优先级/queue_rank及跨项目排序。并发用例在SELECT执行进度回调中使用另一SQLite连接提交优先级变化，本批结果保持原快照，后续查询反映变化，验证一个连接/一个语句。仅位置批次具有统一快照；页内容、Worker和全局候选间仍是原有独立读取，不宣称完整请求跨源原子或Worker下一执行顺序。

Python编译及git diff --check通过。没有全仓测试/浏览器/GPU/真实服务器操作。性能证据从原真实SQL取得，不用Mock耗时；Worker替身仅用于隔离正确性合同。

## 遗留与回退

候选对象构造和Worker素材缓存读取仍有成本，后续如获授权可单独设计精简只读投影；调度性能须独立证据和授权，本轮不修改领取/租约/fencing。单任务及其他业务列表仍使用原scalar，未扩大迁移。真实生产规模和并发长时负载未测。准确SHA Actions推送后一次查询，RUNNING/PENDING不算成功；不轮询/重跑。

回退：对本专项提交普通git revert并正常推送唯一分支；无Schema、业务数据迁移或回滚步骤。完成后停止。

协作：低成本子Agent gpt-6.1-sol只读审计候选及Worker调用边界；主模型独立审查实际源码与Diff，负责批量设计/实现/验证/Git，未让Agent修改或推送。
