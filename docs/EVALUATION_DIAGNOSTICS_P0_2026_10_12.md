# 畅联云算法训练平台｜独立评测 P0 诊断优化 2026-10-12

## 已确认需求来源

- 人形 2,982 张：mAP50=63.6%，Recall=64.0%，FP=3,623，FN=4,491。应检查高错误图片，不要默认分类为数据不足。
- 烟火 2,338 张：fire1 Recall=70.4%、mAP50=70.9%，smoke1 Recall=83.0%、mAP50=83.5%。优先针对 fire1 诊断。
- 安全帽 283 张：No_helmet 的 TP=0、FP=0、FN=85，helmet TP=195/FN=164。应核查标签/阈值/标注/类别映射，而非直接补样。
- 评测阈值从 `protocol.operating_conf` 与 `matching_iou` 读取（当前默认 0.25/0.5），不能把 `mAP50` 和固定阈值 TP 当成同一口径。

## P0 修改范围

1. Canonical `evaluate_blind_detection` 中先对所有测试图片推理，再读取隐藏 Ground Truth；匹配 TP/FP/FN 后收集问题图和框证据。错误样本只持久化严重程度前 200，`error_sample_count` 保存完整图片总数（旧实现等于截断数量）。Top 200 之外不生成大量框级 JSON，兼容 20k 规模内存；框明细单图上限各 120，出现截断须提示。
2. `build_evaluation_truth` 对框坐标、有限值、图片 basename、分类及置信度进行规范化，不传源盘绝对路径；保留受限字段，旧格式兼容。诊断是模型指标不足的证据，不自动宣称夜间/遮挡或数据不足。
3. `build_iteration_decision` 若任何存在 GT 的类别 `TP=0 && FN>0`，产生 `review_required`、`critical_class_zero_true_positives`、`inspect_class_mapping`、`inspect_prediction_threshold`、`review_fp_fn_samples`。普通弱类别保留既有 `needs_data`，但先审阅 FP/FN、标注和训练覆盖，再决定补样，`automatic_execution=false`。
4. `list_algorithms_internal` 给历史冻结评测提供只读 `evaluation_class_advisory`，不修改旧 `decision_id` 或数据库，不抹去旧确认；前端在历史 critical 情况提示先核查，不误把旧补样建议当作确定原因。
5. 只读预览 `GET /api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/images/{image_name}`：要求算法版本、冻结评测问题图片名单、64位 Snapshot ID、Snapshot 内 test IDs 和 material hash 一致、唯一文件名。任何缺失/漂移 404/409，使用已有 StorageManager，响应 no-store；不发起修复或训练任务。
6. 既有 `openVersionEvaluation429` 展示类别诊断、24 张/页可排序的问题图片；详情 GT/预测框/TP/FP/FN，图层独立开关、手机优先和旧版无框说明。继续复用既有 modal/algorithm version/iteration-action，不新增状态所有者。

## 既有 Owner 不变

- 训练冻结：Snapshot、Dataset Revision、测试集 GT 隐藏边界均不改动。
- 标注：MaterialRepository、AnnotationRepository、CandidateStore 依旧独立唯一负责，不把 Test Split 直接变为训练素材。
- 迭代动作仍需确认。此批不做自动困难样本挖掘、不改模型底座、重训练策略或接入生成模型，避免无证据人工合成导致测试集泄漏。
- 下一批 P1 应优先从**非测试**素材挖掘已确认场景，并经人工审核/标注/续训；历史已经参与诊断的测试图片不得被作为原测试集保持不变的同时直接加入训练。

## 测试

- 后端评测真实 IoU/FP/FN 匹配及排名 >200 保留完整计数。
- 安全帽真实类别 TP0/FN85 触发 critical，烟火只有 fire1 被识别为 weak。
- API 拒绝非 Test、恶意路径、缺失 Snapshot、哈希漂移、重复文件名。
- Chrome 展示 real-image 请求、GT/预测框分别开关、历史证据缺失的降级提示。
- Workflow：`Remote Training Runtime` API + unit；`Frontend Runtime Stabilization` browser + Node tests。
- 注：无需且不允许把 283/2,338/2,982 张生产测试图推到 CI。真实测试数据和长期 Worker 压力通过现场验收，不要把 Mock 当作真机成功。

## 上线阻断与限制

版本 `42.24.350` 不变，只有长期开发分支。本改动没有进行任何生产部署。CI 状态以**最终 SHA** 对应运行的 completed/success 为准；排队中的运行不是通过。真实素材存储在不同 Storage Source 或历史 Snapshot 不可验证时，图片详情将显示无法预览而不是伪造截图。真正的弱样本归因需要人工复核和足够的场景/标注证据，当前只提供类别异常与错误框定位。

