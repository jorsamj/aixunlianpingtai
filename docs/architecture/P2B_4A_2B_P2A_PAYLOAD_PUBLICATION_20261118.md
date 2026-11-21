# P2B-4A-2B-P2A：Repository Payload 安全发布事务

日期：2026-11-18。开发基线与远端核对：`4b4f750fbd90843e886a0ccce6e2d5bc51156e56`。唯一分支：feature/external-algorithm-publishing。VERSION保持42.24.592。三份原有未提交设计文档保留，不纳入提交。

## 实际新增接口

TaskRepository新增`publish_training_payload`、`publish_deployment_payload`，共享私有`_publish_payload`（锁外证据验证）和`_commit_payload_publication`（可重试SQLite事务）。FencedTaskRepository直接继承，不需要修改其执行/恢复实现。

```python
result = repository.publish_training_payload(
    parent_id,
    artifacts=artifact_store,
    publication=prepared_publication,
    child_task_id=child_lease.task.task_id,
    child_lease_token=child_lease.lease_token,
    child_attempt=child_lease.task.attempt,
    child_worker_id=child_lease.worker_id,
    child_payload_ref=child_lease.task.payload_ref,
)
# result: PayloadPublicationResult(outcome, task, operation_id)
```

部署入口参数相同。所有owner/input参数强制提供，无None兼容退化。接口只发布已经由P1准备好的文件，不在Repository重做文件存储或operation_id算法。ArtifactStore/FencedArtifactStore的P1接口无需修改。

## 证据与父子身份

锁外重新读取P1收据和版本，重算验证身份/op/ref/SHA/size，并比较传入descriptor与实际收据/文件提案；公开dataclass的类型本身不作为可信证据。沿用P1精确错误码，不将文件存在或收据存在当成数据库成功。

子任务输入必须为`read_payload_version()`可验证的不可变版本。训练输入必须是object并绑定training_task_id与project_id；部署输入必须绑定parent_task_id，其project_id若存在也要一致，数据库project始终必查。旧mutable payload.json/request.json即使读出的内容正确，也没有永久绑定的摘要承诺，**新入口拒绝**。本阶段不自动迁移子任务，也不复制legacy文件假装冻结。

事务内从当前父ID推导并校验child ID：训练trainprep_{parent_id}，部署{parent_id}-prepare；同时检查当前父子kind/project和child.payload_ref等于刚验证的输入ref。执行权必须同时满足child RUNNING、token/attempt/worker_id一致和有效lease。lease使用带时区时间解析并转换为UTC后比较事务获得writer后的固定now，不用ISO字符串字典序；无时区/无效/过期时间拒绝。

该证明依赖P1不可变存储的受控写入前提；不能抵御同OS账号的任意磁盘/SQLite篡改。新接口不接受“仅相同可变路径”的冻结证明，也不新增父子关系表。

## 准备门禁与激活字段

首次发布仅允许父QUEUED、attempt等于identity.expected_parent_attempt、ref等于identity.expected_payload_ref，同时必须保留实际已有门禁：

| 父域 | 必须的required_capabilities | 允许的准备stage |
|---|---|---|
| TRAINING | 单一training.input.ready | training_input_pending或queued（现有修复入口允许） |
| DEPLOYMENT_TEST | 单一deployment.input.pending | PREPARING_MODEL |

训练freeze不能带activation，只换ref/updated_at，原资源/caps/stage不动。READY必须完整提供resource_key、required_capabilities、stage=queued；不接受空能力或准备门禁/prepare能力。部署沿用deployment.runtime合同；训练具体业务intent与执行能力白名单由P2B决定，本轮不发明素材/模型参数结构。

READY引用与激活字段在同一UPDATE提交。不更新status、attempt、lease、worker、资源预约或Assignment；不自动增加执行代数，不进行GPU或训练副作用。未将父QUEUED单独当成足够发布条件。

## SQLite CAS时序

```text
锁外：P1已写文件/同步/收据
  -> 重新验证收据与版本
  -> 验证不可变child输入及真实父绑定
  -> 校验phase/允许激活字段、预序列化激活能力
BEGIN IMMEDIATE
  -> 读父、子当前行
  -> 重查推导的父子身份、项目、种类、child输入ref
  -> 检查child完整执行权与UTC租约
  -> ref==new_ref: 只确认ALREADY_APPLIED
  -> 否则检查expected_ref、父QUEUED/attempt/准备门禁
  -> 条件UPDATE ref+必要激活字段
  -> rowcount必须1
COMMIT
提交确认后才返回结果
```

SQL CAS包含task_id/project/kind/QUEUED/expected_ref/expected_attempt/当前gate caps/stage。writer排他期间子身份与租约检查到UPDATE之间不存在其他writer插入窗口。没有Schema变化、执行权新字段、第二Task Truth或新调度器。

Payload/收据/child文件读取、hash、大JSON解析均在writer外。事务内只有SQL、时间比较和现有Task行/小型capabilities的解析；不读文件、不fsync、不访问远程服务。私有事务方法复用retry_busy，仅重试事务，不重复文件准备。SQLite Busy保持sqlite3.OperationalError，可重试，不转换为父任务FAILED。

## 结果与失败语义

- APPLIED：CAS成功且commit返回成功；父ref与READY字段原子更新。
- ALREADY_APPLIED：当前ref等于本提案new_ref，仍验证原Task身份、收据/内容、child输入与**当前**完整执行权；不重复UPDATE、不重设资源/caps/stage。父已被Scheduler领取、attempt增加或已终态，不会因此被重置回QUEUED。
- CONFLICT/SUPERSEDED：当前ref既不是expected_ref也不是new_ref，抛PAYLOAD_PUBLICATION_EXPECTED_REF_CONFLICT。冲突通过稳定异常code表达，不返回成功结果，不用旧收据回退当前ref。

新增Repository错误码区分IDENTITY_MISMATCH、PARENT_CHILD_MISMATCH、LEASE_INVALID、PARENT_NOT_ELIGIBLE、CONTENT_MISMATCH、EXPECTED_REF_CONFLICT、COMMIT_FAILED（均PAYLOAD_PUBLICATION_前缀）。收据/文件/同op内容冲突继续复用P1错误码，例如PUBLICATION_OPERATION_CONFLICT与PAYLOAD_INTEGRITY_ERROR，不发明第二套算法。

commit失败不返回APPLIED；非Busy SQLite提交错误报COMMIT_FAILED，明确“提交未确认”，不能绝对断言数据库没有提交。重试相同op读取当前ref确认结果；Busy仍交由原有有界重试机制。没有提交后另开get连接作为成功条件，避免把后续查询失败误认为提交未发生。

## 并发、崩溃与恢复

隔离SQLite并发实测：两份不同op提案对同一expected_ref竞争，恰好1个APPLIED、1个EXPECTED_REF_CONFLICT。相同op不同内容由P1在文件收据层冲突；descriptor与已持久提案不同也拒绝。

文件成功/收据失败或版本损坏：锁外拒绝，不打开Task写连接。文件及收据成功但事务尚未提交：仅为提案，合法新Worker可在重新取得child lease后复用。

已覆盖commit前失败与真实commit后模拟回执丢失：前者父ref保持原值、文件收据保留，重试APPLIED；后者数据库已切换但方法报提交未确认，重试ALREADY_APPLIED。没有根据孤立版本或收据自动恢复Task。

child租约失效、被取消、owner变更时旧Worker被拒绝，即使父ref已是new_ref也不能借幂等免除fencing。新Worker接管同一child后，在其新token/attempt/worker_id下可以APPLIED或确认ALREADY_APPLIED。父首次发布前取消/进入运行或终态不得首次发布。

训练freeze→READY串行发布通过；READY后再次提交旧freeze为冲突，不回指旧ref。正式训练/部署发布流程尚未迁移，本轮只验证接口事务，不声称生产已有这些流程。

## 旧接口兼容与强制接入门槛

activate_prepared_training/settle_deployment_preparation继续服务legacy父ref，未删除原方法、未收紧legacy可选owner兼容合同。仅新增一个事务内保护：父ref已是P1版本格式时旧接口拒绝，防止freeze后从无owner旧接口激活，或部署旧接口将新ref替换回mutable prepared-{attempt}.json。

旧训练Fenced回归及legacy部署settlement实测通过。旧接口的未迁移路径仍具有既有局限；新接口不调用旧接口作为回退。

**P2B/P2C正式接入前强制事项**：训练/部署child输入要用不可变版本；调用者必须传完整lease/input与稳定intent；父的所有准备写者必须统一走新协议，避免旧进程同路径覆盖；READY业务证据及intent白名单由各业务Owner确定。P2A不是滚动混跑旧文件覆盖写者的迁移方案，也没有启用Claim新Pipeline。

## 实际验证

```powershell
python -m pytest -q --confcutdir=tests/unit tests/unit/task_runtime/test_repository.py --tb=short
python -m pytest -q --confcutdir=tests/unit tests/unit/task_runtime/test_fencing.py -k "not payload_p1" --tb=short
python -m py_compile platform_core/task_runtime/repository.py platform_core/task_runtime/payload_publications.py tests/unit/task_runtime/test_repository.py
git diff --check
```

Repository原回归26项与P2A新增48项，合计74项；Fenced既有受影响回归13项（排除未修改的P1存储29项）。数量以提交前最终实际执行输出为准，不累计中间重复运行。测试均临时数据库/产物目录，无生产连接。没有运行全仓pytest，没有访问A800/4070。

测试覆盖三种正常phase、身份/项目/kind/child内容/输入ref变化、完整owner及缺参拒绝、UTC过期、父子取消、gate/attempt/ref冲突、并发、commit失败/回执丢失、worker接管、已领取父幂等、冻结后READY、旧接口保护/兼容，以及文件验证/序列化在writer外。P1文件写/fsync失败机制继续复用，不在P2A重复运行未改动的存储全套。

CI由现有包含test_repository.py的自动工作流执行，工作流文件未修改、不手工重跑。推送后仅核对准确新SHA并按AGENTS.md异步规则报告当次状态；RUNNING/QUEUED/PENDING均未验收。

## 已知限制及阶段状态

本地事务测试仅Windows；Linux P2A由新SHA CI另外验收，P1的Linux烟测不能冒充本轮事务验证。未进行掉电或生产环境实验。

训练remote_training_tasks与部署scenario_preparation仍使用旧业务流程，历史执行Payload锚点、非Payload证据历史恢复、删除/空间回收均未完成；旧有生产stale Payload风险不能宣布全链路解决。版本目录继续按P1保留，无自动GC。

本阶段只交付P2A两个严格事务入口及legacy防旁路保护；不改Scheduler/Claim/Agent/Supervisor/GT/生产配置，不开始P2B/P2C/P3/P4。提交推送后仍须GPT结合实际Diff、执行权、事务语义和准确SHA CI独立验收。

协作：主模型负责实现、事务与fencing判断、真实Diff复核及测试/Git；gpt-6.1-sol仅只读核对既有gate/旁路并审阅新核心，没有修改/运行测试/提交；主模型独立核查，未重复全仓审计。
