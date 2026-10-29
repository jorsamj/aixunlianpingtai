# 训练副本回收与异常证据审计（2026-10-29）

## 当前状态

基线远端 HEAD：4032774385f50fe94e575923e5decada53aebee5；VERSION：42.24.399。
用户已授权将本轮最小修复提交到 feature/external-algorithm-publishing；本次提交CI NOT VERIFIED，未部署。
原用户目录 HEAD ddc88a6d/VERSION42.21.1，在 wip/42.25-codex-interrupted；正式分支所在工作树与远端存在4/76分叉且有标注模块未提交改动。全部保留。当前隔离工作树从远端HEAD创建，不接管历史目录或其他会话文件。

## 已有能力及实施方案

原 TrainingWorkspaceLifecycle 是唯一回收Owner；TaskRepository、ArtifactStore、Snapshot和原评测接口继续承担原职责。
原训练工作台、负样本与四预设CSC已有实现，本轮不重建。原高级评测支持FP/FN/类别筛选、24张分页、框证据、置信度、复核与同基准对比；代码存在不等于本轮完成浏览器或生产验收。
先写失败回归，再修改唯一生命周期Owner，最后执行回收与图片API定向验证。

## 已确认并复现的缺陷

1. 回收归档只取 training_report.test_result.error_samples，而图片API接受 sample_evidence、error_samples、sample_outcomes；Top200之外的异常图片可能未保存。新增两个测试在旧代码因归档图片不存在失败。
2. 归档用Image ID匹配或文件名匹配，显式错误ID可被同名命中。旧代码对错误ID未拒绝，回归失败。
3. 自动维护在资格检查失败时直接跳过，缺少持久阻塞回执；归档阶段抛错也未记录具体阶段原因。旧代码回归取不到回执。
以上不代表生产图片不可见的唯一根因；没有生产日志、任务ID或文件调查，不能判断现场具体任务。

## 修改与回收规则

仅修改 platform_core/training_workspace_lifecycle.py：归档所有FP/FN异常outcome与已有sample_evidence，合并原error_samples；通过manifest索引避免逐样本全量匹配，按image_ref去重。显式ID不能回退同名，存在样本SHA时必须匹配manifest，再验证实际文件SHA。失败则保留bundle。
自动维护记录blocked/retryable及原因、时间、任务与范围；相同阻塞不重复写；回执写入使用原workspace-access锁，不覆盖已隔离删除回执。归档异常仅保存安全错误码或异常类型，不泄漏底层路径；诊断写入失败输出warning。重试继续使用原有轮转扫描，不增加调度器。
普通serve_forever启动即维护、终态唤醒、30秒兜底，默认每批4项，上限16。不是任务结束后固定30秒保证完成：任务总数、唤醒、模型校验和阻塞均会影响时间。--once只run_once，不执行常驻维护。实际生产启动方式未核验。
仅归属证明完整的本地终态任务可自动清理；成功/部分成功还要求模型SHA及正式版本归档证明；失败/取消需无恢复依赖。租约、进程身份不明、活动消费者、未知历史所有权都阻止删除。短DB栅栏重验及隔离删除机制保持。
原图、标注、Snapshot、训练参数、模型、Checkpoint、训练记录及共享cache均不在删除范围。CSC位于bundle内的临时副本随任务目录清理。逻辑删除字节有回执，physical_space_released为null，不能宣称物理磁盘释放。

## 恢复、共享缓存与远程边界

失败记录recoverable/checkpoint_available/checkpoints/recovery_action或runs内.pt仍保护整个bundle；可能长期占用，不能为达到清理目标直接撤销恢复合同。尚未证明任意历史Checkpoint都可在原图删除后仅凭Snapshot重建完整输入；本轮没有改变断点续训。
共享TrainingBundleCache独立管理，默认64GiB/30天，已有TTL/容量驱逐与访问保护；不在本地任务目录回收范围，空闲期间实际驱逐调用是否足够未验证。
remote_material_lifecycle是远端暂存对象治理Owner，保护正式模型与共享远端训练bundle。本轮不扩展本地清理资格至remote，不修改远端对象清理。远端训练结束后全部临时对象是否最终回收仍需专项运行证据。

## 图片查看与现有分析入口

原API仍按冻结评测/Snapshot测试成员、Image ID、源SHA与评测字节SHA校验；使用有效work/bundle、evidence/bundle和可信素材回源，禁止同名替代。无需改API语义。
新增集成测试使用规范化图像（不同于原素材像素），仅在sample_outcomes记录漏检，真实调用清理前后的原API，确认清理后返回归档中的相同字节，原素材保持存在。
原API已有Snapshot缺失、身份歧义、SHA不一致、原图缺失等错误分类与可信缩略图派生测试；本轮没有改缩略图或前端并发策略。历史已经缺失的证据无法由本次修复补回。全部正确outcome不长期复制，未保留正确样本的查看仍依赖可信原素材。
沿用现有高级评测的异常筛选、GT/预测框与复核入口；没有向训练集添加冻结Test图片，没有新评测引擎。

## 性能审计

本轮没有采集真实HTTP接口耗时，也没有访问生产环境。登录、算法、素材、设备探测、训练提交实际耗时及重复请求均NOT VERIFIED，不宣称提速比例。
可确认归档查找由逐样本扫描manifest改为一次建索引，但这只是算法复杂度变化，不是生产计时结果。上一轮性能专项保持唯一依据，不重复实施。

## 定向测试

基线：python -m pytest tests/unit/test_training_workspace_lifecycle.py -q，23 passed/1 skipped。
RED：新增归档outcomes、sample_evidence、显式ID与阻塞回执4项，4 failed（预期失败）。
最终：python -m pytest tests/unit/test_training_workspace_lifecycle.py tests/api/test_evaluation_diagnostic_image.py -q --basetemp=C:/Users/jorsam/AppData/Local/Temp/evidence-final-1029，70 passed/1 skipped，6.75s。skip为Windows软链接权限；已有FastAPI生命周期弃用告警。
覆盖原成功/失败/取消/运行保护、恢复与消费者、隔离删除重试、Snapshot/哈希/回源、图片格式、缩略图身份及新增清理后预览；没有GPU训练、全站压测、全仓测试或新浏览器验收。git diff --check通过。

## 文件与交付边界

后端：platform_core/training_workspace_lifecycle.py。
测试：tests/unit/test_training_workspace_lifecycle.py、tests/api/test_evaluation_diagnostic_image.py。
文档：本报告、AGENTS.md及四份当前handoff。
前端及数据库：无变更；VERSION保持基线，本轮未发布。
本地定向修复具备代码审查条件，尚不具备生产验收结论。提交后应核准准确SHA的相关CI，不能继承旧HEAD绿色。

## 尚未完成与生产建议

没有列出生产实际残留任务或磁盘释放量；没有验证生产Worker启动参数、节点失联、OSS/NAS可用性或现场UI。恢复依赖永久保护的到期/用户放弃策略、远端缓存最终回收保证尚未解决，不能把本轮称为所有临时副本最终回收已验收。
部署评审前应在获授权环境只读核对有限任务：成功、不可恢复失败、可恢复失败、取消各一，记录所有权/租约/PID身份/阻塞回执与归档覆盖；通过隔离演练后再计划发布。不要对历史未知所有权目录批量删除，不直接在生产执行清理。

## 开发分支提交复核

2026-10-29用户授权提交开发分支。提交前fetch确认远端仍为40327743；定向回收与评测图片API测试重新执行70 passed/1 skipped（6.19s），diff检查通过。沿用既有Remote Training Runtime工作流，无CI范围变更。最终推送SHA及远端CI以交付回执为准，不继承基线绿色。

提交前独立差异审查未发现阻断问题；审查发现诊断retryable回执无candidate字段且目录被外部移除时的KeyError边界，新增测试先RED后补字段保护。最终重新执行同两文件：71 passed/1 skipped（7.48s，basetemp=evidence-push-final-1029）。此前70项为上一轮真实结果，最终以71项为准。
