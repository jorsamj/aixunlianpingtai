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


## 2026-10-12｜P0 审计修复：类别指标与逐图框证据使用相同的匹配规则

- 复核 HEAD 76407cf 发现：类别 TP/FP/FN 使用置信度优先的一对一匹配，逐图问题框却使用 IoU 全局优先；重叠目标可能导致类别指标报告 FN/FP、但问题图片没有错误，直接影响困难样本定位。
- 修正 `evaluate_blind_detection` 逐图匹配为与 `_match_flags` 相同的「置信度降序、同类且 IoU>=0.5、选择未匹配 GT 中最大 IoU」；不改变 mAP 统计、不读预测阶段的隐藏 GT、不新增 Owner。
- 添加双重叠 GT + 两个预测框的对抗性回归，要求类别 TP1/FP1/FN1 与逐图证据一致，匹配标志一致。
- 该修复只代表已提交源代码和测试；精确新 HEAD Actions 未达到 completed/success 前绝不可写作 CI 通过。真实 GPU、2,982/2,338/283 张评测数据和 20k 压力 UAT 未完成；不部署生产。


## 2026-10-12｜P0 图片优先与失效证据保护（第二批）

- 代码复核确认原问题图片列表使用占位图标+文件名，未加载真实缩略图。改为每页至多 24 张，只读复用原冻结测试图片 API，浏览器按需 lazy-load，失败展示“图片不可预览”。不缓存业务事实，不使用伪造缩略图。
- 原图失效时同时隐藏 SVG 的 GT/预测框，禁止脱离实际图片展示看似真实的证据；按原始图片 bounds 展示的有效图层维持不变。
- Chrome 回归增加缩略图路由身份与图片不可访问时的降级/图层隐藏；20k 样本浏览器/真实存储源性能验收待 CI 和现场验证。

## 2026-10-12｜P0 后续核验：阈值可见、真实缩略图、评分匹配一致性（CI 待跑）

- 最新分支已提交 P0 三类定向修复：置信度优先一对一 GT/预测匹配统一类别 TP/FP/FN 与逐图框证据；问题图片卡片改为真实冻结 Test 只读缩略图，不可读时不伪造图；原图失败时隐藏 GT/预测 SVG 防止脱离图片显示假证据。
- 版本独立评测总体指标直接显示 `protocol.operating_conf` 与 `protocol.matching_iou`，区分 mAP 与固定阈值 TP/FP/FN；历史无可确认协议 mode 时显示「未记录」，不得暗填 0.25/0.5。
- 增加真实重叠目标评分一致性单元测试、Chrome 缩略图及 409 失效保护、评测阈值和历史降级断言；static app/style cache key 更新。版本 42.24.350 不变。
- P0 判定仍 BLOCKED：对应精确 HEAD Actions 若 queued/in_progress/failed 不算成功；真实 3 组业务 Test 素材、真 GPU/Storage、1k/10k/20k 压力仍未完成现场验收。P1 不得在这个 P0 门槛通过前当作已实现；未合并 main/tag/release/生产部署。


## 2026-10-12｜P0 图片预览 20k 性能与冻结身份最小修复（CI 待验）

- 复核只读图片预览接口发现：`image_id in test_ids` 在 20k Test IDs 的 tuple 内执行 20k 次，形成 O(N²)；随后单次 API `MaterialRepository.get_many(test_ids)` 反复读取最多 20k 材料，图片卡片 24 张会倍增 DB 压力，老 SQLite 还可能因 IN 占位符过多失败。
- 保持原 Snapshot/Material/Storage Owner，不建索引缓存第二真相：先用 Test ID set 做快照成员校验；要求 Snapshot 内 Test 身份完整、不可重复。V3 snapshot `stored_name` 完备时，仅将唯一名称对应的冻结 image_id 发给现有 `get_many`；历史无名 snapshot 退化为 500 ID 分批读取，继续执行原素材 SHA256 和身份校验。
- API 回归新增 20,002 Test IDs 的精确单素材读取，以及 1,203 历史无名 Test IDs 的 500 分批读取，保留已有跨版本/非法路径/摘要漂移用例。此处 20k 是结构与调用计数测试，不代表真 OSS/真 GPU/真 20k 性能压测已通过。
- HEAD 最终 Actions completed/success 与现场 UAT 仍待核验；P1 仍未进入，禁止 main/tag/release/生产部署。

