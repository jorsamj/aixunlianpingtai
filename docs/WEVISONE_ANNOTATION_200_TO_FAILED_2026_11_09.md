# WeVisOne-VL HTTP 200 → AI 自动标注失败专项｜2026-11-09

## 需求、边界和基线

- 仓库 `jorsamj/aixunlianpingtai`；唯一远端开发分支 `feature/external-algorithm-publishing`；本次代码起点 `039034ba2737766e46977d8e2e8c7454b6cca802`；`VERSION.txt=42.24.561`，不擅自变更正式版本。
- 4070 现场仍为 `42.24.543 / 9656ded4`，仅用户提供的日志证据：模型配置 `8d5cc70403d5`、任务 `ai6e467ea966ac083d64e2`，两张 4070 对应的 `18000/v1` 与 `18003/v1` 各返回 12 次 HTTP 200，任务 24/24 `failed`、0 `success`、0 `empty`、`error=null`。
- 模型实际样例：`480×480`、`coordinate_system=xyxy_pixel`、`bbox_xyxy=[230.88,168,250.08,199.68]`、`bbox_normalized=[0.481,0.35,0.521,0.416]`、`label=person`，无 score/confidence。
- 仅改现有 Provider、模型配置页面/API、AI Worker、CandidateStore、Task Scheduler 的极小边界和相应测试；不动 GPU/生产数据、正式 GT、已有任务或模型运行实例；不新建任务管理或缓存、不 merge/tag/release/deploy。

## 核对过的事实与根因边界

1. 已检查 `42.24.543` 同版 `wevisone_vision.py`、`auto_label.py`、`annotation_task_service.py` 源码：其已允许专用 Provider 在没有 confidence 时返回 `null/unavailable`。长期分支也一样。用上述样例和一致的 `480×480` 输入、`person` 冻结标签、`pixel/xyxy/top_left` 协议运行实际 `annotate_one`，生成了合法候选框。**无 confidence 不是已证实的 24 张失败原因**。
2. `AnnotationHandler.run()` 把 `run_ai_annotation()` 返回的 `WorkerOutcome.error` 丢掉，仅把 `(status,result_ref)` 交给 Scheduler；因此即便 Worker 保存了逐图错误，任务状态为 `FAILED` 时也可以显示 `error=null`。这是确定的源码缺陷。
3. 模型配置 `changeVisionProviderM4()` 隐藏整个高级设置；`saveVisionModelM4()` 强制 `pixel/xyxy/top_left`，后端 `_v35_normalize_adapter()` 又覆盖一次。与用户需要的可核验坐标合同相冲突。这是确定的配置缺陷。
4. 原服务在 Provider 对原生响应校验后输出原图像素框，但 `annotate_one()` 随后使用**配置的线协议**再次转换；如果历史冻结配置的坐标范围/顺序不是标准 `pixel/xyxy`，可能二次缩放、换轴或被拒。这是确定的可复现潜在链路缺陷，不代表已证明为所述历史任务全部失败的唯一原因。
5. `CandidateStore` 逐图已存 `error_code/error_stage/http_status/error`，前端有逐图诊断与原任务失败差量重试；未重复开发。24 张历史任务的**具体错误码仍需按原任务候选日志读取**。HTTP 200 只能证明 HTTP 请求完成，不能证明标签、协议、坐标和落库校验通过。

## 修复设计（保留 fail-closed）

- Provider：对响应的显式 `coordinate_system`/`coordinate_space`、顺序、原点、原图空间进行校验，与保存配置不一致返回 `MODEL_COORDINATE_CONTRACT_MISMATCH`；同时支持明示的 `normalized_01/normalized_1000` 和 `YXYX/bottom_left` 转成原始图像像素 XYXY。`bbox_xyxy` 在 `xyxy_pixel` 声明下优先，不拿 `bbox_normalized` 重复缩放。报告的宽高如与提交原图不符且无还原几何证据，拒绝并标明 `MODEL_COORDINATE_GEOMETRY_UNVERIFIED`。异常标签、越界、畸形响应继续失败；空框确认为 `empty`；不伪造 confidence。
- Worker：WeVisOne Provider 输出已是平台统一坐标，后续 schema 校验固定使用 `pixel/xyxy/top_left/original_input`，避免再次应用线协议变换。保留原冻结标签/别名和人工审核 GT 栅栏。
- 配置界面：WeVisOne 的坐标范围、XYXY/YXYX、左上/左下原点和图像空间与通用模型一样可见、可保存；专业提示强调须匹配真实回包。专用 API/chat 选项仍锁定，不混用模型聊天协议。真实样本验证继续独立进行。
- 任务：原 Scheduler 兼容 2 项返回，也可接收经清洗的 3 项 `(status,result_ref,error)`；原 AnnotationHandler 保留 WorkerOutcome 错误。CandidateStore 限量查询失败码分布，写入原 `generation.json`，任务详情投影 `generation_failure_codes`。`failed_count` 对已持久化的统计以 candidate 真值为准，避免失败重试成功后沿用旧 checkpoint 最大值。
- 恢复：沿用原任务的 `/retry` 及 `generation/retry-selection.json`，只针对失败/未处理素材；候选 ID、人工草稿、已成功候选、正式 GT 不改变。

## 验收与待证据

- 单测覆盖真实 480×480 无置信度成功、多框、空框、0～1 归一化、XYXY/YXYX、底左原点、配置不匹配、尺寸不匹配、越界、非法标签、畸形响应。
- Worker 批量覆盖全部成功、正常空框、部分失败、全部失败及统计/错误直方图；API 集成覆盖真实 Provider→Task→Candidate→人工确认才写正式 GT、任务顶层错误与逐图错误，且既有失败差量重试保护回归。
- 2026-11-09 本地限定回归：Python 单元/API/集成 272/272 通过；全量 Node 前端 1572/1572 通过；`node --check static/app.js`、Python 编译及 `git diff --check` 通过。未在本地安装/运行真实 Chrome，已将 WeVisOne 原生编辑器测试纳入既有 `Frontend Runtime Stabilization` Chrome 矩阵，将 Provider 单测纳入原 `AI Annotation Recovery` 合同矩阵。
- 代码改动之后需在**准确新 SHA** 上单独读取 CI 结果；本地未连接 4070 实机、不声称运行中系统已修好。
- **历史任务定因的剩余只读步骤**：在 4070 原任务详情打开「逐图失败诊断」，读取/导出 `error_code`、`error_stage`、`http_status`、`error`、`requested_labels` 和当时冻结的 `model_config_snapshot`。不要仅根据 24 次 HTTP 200 判定已经成功解析；没有逐图证据，不将猜测写成确定根因。未收到生产读取权限时不访问或修改任何现场数据。
