# ZIP 导入记录安全与状态一致性专项

## 需求、基线与边界

用户授权修复 P0-1–5：活动任务删除保护、404 后状态未知、浏览器缓存收敛、Worker 状态写入/记录丢失诊断、清空历史与临时文件生命周期。只在开发和隔离数据中验证；不连接生产、不扫描生产素材、不部署。生产 Hat/Fall 两任务记录缺失的实际原因尚未确认，不据缺失推断成功、失败或人为删除。

基线：39a26e8c78cdd98ec2e1df0df7fa670157b5bb1d / VERSION42.24.390，已 fetch 与远端相同；当前隔离工作树干净且 detached，长期分支在另一工作树，保持其 WIP、5944 和两份模板测试不动。提交只正常快进推送至唯一长期分支。

## 已确认代码根因

- app.py 单条删除无状态校验；批量删除以快照状态判定并 rmtree(ignore_errors=True)，与 start/DB_COMMIT 未共用停止栅栏。
- v19_update_job 吞掉所有异常；Worker 两个异常分支再次读取 job.json，丢失时二次异常。
- UploadTaskCenter 查询失败只更新 detail；ZIP knownJobs 合并可恢复服务端列表中已不存在的 RUNNING。
- 完整目录删除连同 job.json/report 一起删除，失去轻量结果证据。

## 最小设计及实施计划

复用原 .stop.lock（可重入实例），起停、状态更新、终态清理在同一栅栏下。清空仅隐藏已确认终态，保留 job.json/原 report 引用；显式清理仅作用于本任务临时文件。提交后写状态失败不得回滚正式数据或误报成功，单任务独立诊断文件不作为成功权威。前端统一 UNKNOWN，保留历史进度、任务 ID、最后服务端时间；明确 404 错误码与退避，恢复真实服务端记录后清除异常。无素材/GT全量查询、无新任务系统。

- [x] 后端 RED：活动状态/DB_COMMIT/并发栅栏，终态审计及清理失败，写入失败/记录丢失和正式数据保护。
- [x] 后端修复及必要原导入/原子提交回归。
- [x] 前端 RED→GREEN：404、刷新、退避、恢复、并发任务隔离及清理结果一致。
- [x] 真实 Chrome 冒烟、受影响静态检查与审查。
- [ ] 版本、提交、安全推送和最终 SHA CI。

状态：已完成待验收。VERSION42.24.391；本地必要验收通过，提交和准确 SHA CI 待完成。

## 验收及接续

更新本文件保存实际命令、通过/失败、问题修复、提交及准确 CI。测试使用原 pytest/Node/Playwright 框架；不运行重复全仓测试。生产两任务只可后续按 project_id+job_id 定向核验，若无 ID 先读取轻量目录/服务日志，不按 ZIP 名扫描素材库。

## 实际实现与审查结论

- 原 .stop.lock 使用 FileLock 的可重入单例；v19_write_job/v19_update_job、起停、DB_COMMIT及终态清理共用原锁，锁文件不随清空历史删除。六类活动任务后端409；终态不接受迟到进度/旧分片状态覆盖。失败重试仅允许原已验证 start 路径显式恢复，已清空的历史不准重启。
- 清空仅处理实际终态，临时清理/归档失败明确503和 kept.reason，不以 ignore_errors=True 报成功。原 job.json/外置 report.json 归档至 import_jobs/.history/{job_id}，原项目+任务ID仍可查询；不另建正式素材或任务数据库。普通活动发现不解析归档JSON，原锁目录保留。查询单条解析/终态任务不计算全队列、不读完整报告或素材/GT库；历史无phase的running沿用原FIFO兼容性。
- report读取与归档共用原锁，job.json读取在原子归档竞争时有界重定位。保留原ZIP名称、ID、项目/批次、创建/完成时间、状态、实际计数及诊断，原已外置的imported_image_ids证据继续复用，不复制图片或GT。临时空间释放在明确清空终态历史或原正式取消时执行；未增加默认全库物理清理。
- 状态写入异常不再吞掉；初始读取/异常处理二次失败由最外层捕获、服务日志和每任务轻量 .diagnostics/{job_id}.json 留痕。诊断匹配具体 job.json 文件修订，旧记录显示UNKNOWN，后续成功写入新修订可恢复。只有明确Worker退出诊断才能让原FIFO排除死前驱，普通状态读取异常不擅自释放执行权。
- 正式提交前记录丢失使用原批事务回滚；正式提交完成后最终状态写失败保留素材、GT及报告，不误报done。诊断不能代替成功成果。执行与状态失败的主要证据不会被随后临时清理错误覆盖，secondary_error有界记录。
- 原UploadTaskCenter及ZIP Runtime统一UNKNOWN：保留历史百分比/最后服务器时间/任务ID，404退避60秒，其他核验异常15秒，手动查看可立即核验。刷新恢复的服务端RUNNING先验证；未知记录不因100行历史上限被自动丢弃。恢复的真实服务端状态优先，确认意图仍保护已提交任务不重复POST/start。
- 恢复归档证据会将另一标签页的旧RUNNING收敛至DONE，即使列表已隐藏该任务。批量DELETE兼容可选job_ids（最多200）确认浏览器终态记录，只清除服务器实际ack的ID；清理失败/活动/未知任务保留。旧任务列表同步禁用活动删除，只展示取消提示。
- 无新Owner、轮询、锁体系、图片库或GT DTO；没有修改上传协议、GT计算、训练或RKNN。

### RED→GREEN及实际测试

以下为实际批次，重叠不累加为唯一总数：

|证据|实际结果|
|---|---|
|新增后端首轮RED|11失败：活动删除200、无栅栏、无审计、吞写错、迟到覆盖及初始记录丢失二次异常|
|首轮最小修复|11通过|
|后续原ZIP回归|首次22通过2失败：旧Windows路径字符串写错、旧清空要求删目录；原位修正路径及用户新证据保留合同，未删除测试或削弱安全断言|
|新增直接迟到写入RED|1失败15通过；补齐所有写入的原栅栏和终态保护|
|前端RED|缓存RUNNING、UNKNOWN展示、缺失缓存核验3失败；GREEN3通过；原源码签名守卫更新到按ack ID清理|
|持久状态写错/队列/归档规模|各自RED；GREEN。121条历史归档后活动轮询/FIFO不读取历史JSON；直接状态不访问素材/报告/其他任务|
|组合失败审查|持久状态写失败+临时目录清理失败RED；修复主要诊断被覆盖后GREEN2（含原持久失败场景）|
|最终必要Python批次|44通过，0失败0跳过；随后诊断优先级窄修复再定向2通过，其中1项重叠，总唯一场景45，不重复跑全仓|
|最终必要Node|101通过，0失败/取消/跳过（7个受影响文件）；缓存标识守卫漏同步一次失败后随真实入口修正|
|真实Chrome新增|2通过：404/刷新/退避/手动详情/恢复/无重复start；真实ZIP导入后跨标签页清空、历史证据/原图ID保留、旧RUNNING收敛及幂等本地清空|
|真实Chrome原回归|3通过：进度风暴指针事件及rekey；确认后旧状态不重弹/不重复POST；三个ZIP分别确认并各入库一次|
|独立只读审查|修复死前驱、历史反复解析、次级错误覆盖三个有证据问题后，无剩余Critical/Important；审查未冒充重新跑测试|

命令：Python使用原pytest，tests/api/test_v19_job_record_safety.py、test_v19_import_failure_rollback.py、test_v19_import_fifo.py、test_v19_import_report_externalization.py、test_v19_multipart_controls.py、test_v19_job_atomic_persistence.py。Node运行 upload-task-center、zip-import-durable-runtime、zip-record-missing、zip-multipart-upload、uppy-zip-adapter、zip-import-overall-progress、version-marker-owner。Chrome新增 zip-record-missing.spec.mjs 全部2项，原 zip-label-presentation 与 upload-task-center-performance 的上述3个定向场景。既有Material Annotation Atomicity工作流接入新增后端安全文件；不增加新工作流或全仓测试。

### 需求验收矩阵

|要求|代码/隔离证据|状态|
|---|---|---|
|P0-1/A/B 活动删除及提交竞争|六类409、同原停止栅栏竞争测试、原DB_COMMIT取消保护|已完成待验收|
|P0-2/E/F/G UNKNOWN与刷新恢复|Node+真实Chrome：404保留历史、60秒退避、刷新与恢复|已完成待验收|
|P0-3 缓存/原Owner统一|单一ZIP轮询；服务端优先、按服务器ack清空；跨标签页归档恢复Chrome|已完成待验收|
|P0-4/H 后台记录丢失及写错|真实小ZIP解析后丢失回滚；提交后写错保护GT；初始缺失、组合失败诊断|已完成待验收|
|P0-5/C/D 结果与临时生命周期|真实成功100%/计数；done/failed清空，running/selecting保留；报告归档及清理失败可重试|已完成待验收|
|I 多ZIP隔离|持久失败前驱不阻塞下一任务、原Chrome三个ZIP各一次|已完成待验收|
|J 性能及兼容|直接GET不扫素材/标注/报告或其他任务；121条历史不解析；Node原multipart/Uppy/进度，Python原提交和回滚|已完成待验收|

### 文件及版本

app.py原v19辅助函数/API/Worker、static/app.js旧列表、static/modules/upload-task-center.js与zip-import-runtime.js；入口main/index/zip-bootstrap只更新必要缓存。VERSION一次递增391，app/main438、任务中心66014、ZIP4226370，原styles436保持。上述定向测试与既有工作流、本文件和AGENTS/CURRENT_STATE入口一同提交。

## 风险、生产核验与下一步

1. 生产两个任务的记录为何缺失、正式素材/GT是否完整入库仍NOT VERIFIED；本修复不会重建生产历史、不自动恢复或重复导入。
2. 如有独立只读授权，先取得两个准确job_id（用户已有浏览器任务中心ID或既有请求日志），仅检查项目import_jobs/{id}/job.json、.history/{id}/job.json、.diagnostics/{id}.json及对应服务日志。若记录不可得就保留未知；禁止按ZIP名全库搜索素材/聚合GT。无原任务证据不能宣称导入完成。
3. 磁盘/权限持续故障可能同时阻止任务和诊断文件写入，此时只能保留服务错误日志并先修复存储；不可能承诺不可写介质持久化成功。原图/GT绝不据此删除。
4. 活动列表沿用原任务目录发现及原FIFO；保留小型锁目录，不反复解析已归档历史，未声称万级任务生产压测或全列表O(1)。正式历史证据只按ID读取，不新建无界历史列表。
5. 本地已验证不等于生产验收。正常推送后按准确SHA补CI；CI未通过前不建议生产部署。CI通过后仍由用户独立批准部署，生产旧事故仅可定向只读核验。
