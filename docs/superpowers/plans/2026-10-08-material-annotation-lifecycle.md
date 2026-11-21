# Material / Annotation 生命周期修复实施计划

1. 先写确定性失败测试，复现正式 GT commit 与 Dataset DELETE / Rescan 的交错。
2. 在 MaterialRepository 增加共享可重入生命周期栅栏和正式写 admission；让 Dataset DELETE、Rescan content commit 与正式 Annotation 写共用。
3. 将 AI candidate 的 source hash、人工页面 source hash 带到最终 commit-time admission；保留 expected_version 与标签治理检查。
4. 写 AUDIT-102 逆序投影测试，再实现唯一单调 `patch_annotation_projections` 原语并迁移 AnnotationRepository/app/remap/rescan。
5. 运行直接相关 Python/API/前端测试与语法检查，递增 VERSION，同步审计/交接文档，提交并推送。
6. 对精确远端 HEAD 等待全部 Actions/check-runs 终态；失败只修本批相关项。网络或真实环境不可用时明确记录，不伪造通过。
