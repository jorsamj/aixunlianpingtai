# Material / Annotation 共享生命周期与单调投影设计

## 范围

本设计只关闭 AUDIT-149、AUDIT-157/173 的剩余 TOCTOU 与 AUDIT-102。AnnotationRepository 继续是唯一 Ground Truth Owner；MaterialRepository 继续只持有素材身份和可重建的 Annotation 搜索投影。

## 共享串行边界

在现有 project 目录内增加一个跨进程、可重入的短 FileLock，作为 Material 内容/删除生命周期与正式 Annotation commit 的协调栅栏。它不保存业务状态，不是新的 Repository 或 Runtime。

锁顺序固定为：label governance fence → material/annotation lifecycle fence → 单个 SQLite writer transaction。文件搬移、OSS I/O、模型推理均不得在 SQLite writer transaction 中执行。

正式 Annotation 写入在该栅栏内一次性证明：Material 存在、没有 dataset delete claim、来源可用、调用方冻结的 content SHA（如有）与当前代际一致、Annotation expected_version CAS 成功、标签仍 active。GT 提交后的 Material 投影仍在栅栏内更新。

Dataset DELETE 只在 claim+Annotation backup 和 Material/Annotation finalize 两个短阶段持有栅栏；文件 staging 在栅栏外执行。claim 是阶段间的持久阻断证据。Storage Rescan 的 Material H1→H2 commit 也持有同一栅栏，因此它与正式 GT commit 必然有确定先后顺序。

## 单调 Material 投影

Material payload 增加派生字段 `annotation_version`。唯一投影原语由 MaterialRepository 提供，并在同一 Material SQLite writer transaction 内更新 payload、material_labels、material_annotation_scopes 与索引：

- incoming version 大于 stored version：接受；
- 相等且 annotation digest 相同：幂等 no-op；
- 相等但 digest 不同：fail closed；
- incoming version 小于 stored version：迟到旧投影 no-op。

AnnotationRepository 的 upsert/remap 和 app 的人工/AI 写入不再使用无版本通用 patch 写 Annotation 投影。

## 兼容与恢复

历史 Material 没有 `annotation_version` 时按 0 处理；不改写历史 Ground Truth。批量上限保持 500，AI review 保持 200。跨两个 SQLite 不建立长事务；若进程恰在 GT commit 后、投影前崩溃，GT 仍是权威，幂等重放可以补齐投影。

## 验证

使用 Event/barrier 测试固定以下交错：delete claim 前后人工/AI commit、H1 校验后 H2 rescan、AI 旧候选、合法 v6/v7 投影逆序、同版本幂等与 digest 冲突、label remap/Rescan 入口，以及 AUDIT-148/099/098 相关回归。性能只做有界查询与简单规模检查，不在本 P0 批次扩张成压力平台。
