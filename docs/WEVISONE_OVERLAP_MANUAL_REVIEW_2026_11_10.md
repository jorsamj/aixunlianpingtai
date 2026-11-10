# 42.24.571｜WeVisOne 跨标签重叠候选人工消歧专项

## 用户现场与根因

- 4070 新版 AI 自动标注 `191947137.jpg` 出现 `MODEL_LABEL_AMBIGUOUS`，错误为“跨标签目标框显著重叠”，追踪号 `93e5f306f57842269a4954306a7413b5`。
- 原有每标签原生请求可全部成功，但 `person` / `tangzhe` 框 IoU 大于 0.5 时，推理合并逻辑直接抛异常，导致整张图 `failed`；即使其他框有效也无法进入人工框编辑。
- 聚合后异常没有单个 HTTP 状态/请求 ID，因而不能把“HTTP 未记录”解释为 HTTP 失败；任务失败页原本还默认给出“检查服务配置后重试”，会误导用户。

## 本批修改（严格沿用现有链路）

1. `platform_core/annotation_inference.py`：全部原生标签请求成功后，跨标签 IoU > 0.5 仍保留双方候选框、其他无冲突框及原始逐标签结构化请求证据，不再把整张图直接判为模型请求失败。聚合结果标记 `manual_review_required`，保留最多 12 对冲突的标签、坐标、框序号和 IoU；**不自动选择 person 或 tangzhe**。
2. `platform_core/annotation_task_service.py`：在现有单图候选持久化中携带 `manual_review_required` 和有界冲突证据，保持正式 GT 零自动写入。
3. `platform_core/annotation_candidates.py`：在原 CandidateStore 内强制消歧。未保存人工草稿的冲突候选不可接受；仍有不同标签 IoU > 0.5 的草稿不能保存/接受；原批量“接受未提及”跳过尚未人工消歧的候选，其他图片正常按原审核策略处理。可拒绝冲突图片；没有第二套审核/GT 存储。
4. `static/app.js`：在已有三栏审核工作台的候选卡显示“跨标签重叠·待人工消歧”，初始不显示为已采用且禁用“采用”；原“编辑候选框”入口提示手动删除/修改错误框，修正保存后才可采用。
5. `static/modules/annotation-diagnostics.js`：现有“标注诊断”增加逐标签请求 ID、平台 trace、框数以及跨标签冲突对和 IoU。`app.py` 修正缺失 `created_at_epoch` 的历史错误诊断被错误判断为“30 天前过期”的问题，并在审核 API 返回具体的冲突原因。
6. `static/index.html` 与诊断动态导入 URL：仅递增所改动脚本的缓存键，避免新版本仍使用浏览器旧版审核与诊断代码。

## 范围与安全保证

- 只改已有 Provider 聚合/CandidateStore/AI 审核页面/诊断；原 per-label 调用有界并发、permit/RPM、失败重试以及 GT 人工提交保持。
- 真正的原生请求/解析失败仍作为 `failed`，不把失败结果伪装成安全空框；只在**所有标签均成功**、但局部框跨标签冲突时生成可人工编辑的候选。
- 不新增任务中心、缓存、校验服务、GT Owner，不更改训练逻辑，不操作生产数据或服务器。
- 历史已失败的图片需要使用原“失败图片差量重试”重新生成候选；本次代码不会重写旧任务记录。

## 验证记录

- Python 3.12 `py_compile`，Node `--check` 通过；`git diff --check` 通过。
- 在当前容器缺少 pytest/filelock/psutil 的情况下，用隔离模块依赖和**真实临时 SQLite CandidateStore** 核验：双标签返回、IoU 冲突证据、不可无草稿接受、批量接受跳过、未消歧草稿拒绝、修改后接受、GT 尚未提交；通过。
- Node 直接渲染原诊断组件，逐标签请求号、trace、冲突框编号、IoU 和人工审核提示断言通过。
- 已同步更新两个单元测试：`test_per_label_overlap_is_ambiguous_but_distinct_and_zero_boxes_are_safe`、`test_cross_label_candidate_requires_corrected_human_draft_before_accept`；完整 pytest/真实浏览器、4070 WeVisOne 2B 实机及准确 SHA GitHub Actions CI **待核，不宣称已通过**。


## 42.24.573｜审核工作台新增“有歧义”与批量保留标签（代码待 CI 验收）

- 原 with_boxes 筛选/其他调用者语义不变；新增 clean_boxes（仅无歧义有框）与 ambiguous（活跃且尚未提交 GT 的人工消歧候选）。原 CandidateStore、分页、筛选范围冻结、审核草稿与正式 GT Owner 均不替换；侧栏独立显示“有框·无歧义”“有歧义”及准确计数。
- “有歧义”当前页支持勾选多个候选，指定**一个实际存在的正式标签**，先预检再确认。与现有后端一致，只有不同标签目标框 IoU > 0.5 才归为冲突；每个冲突组必须恰好有一个目标保留框，且该框必须与组内每个待删框直接高度重叠。链式邻近框、多个同标签候选、缺失所选标签及多个不匹配冲突组**整张图跳过**，避免误删真实独立目标。
- 仅删除上述冲突组内的其他标签框；无冲突框原样保留。沿原草稿 PUT 端点单图 CAS、任务/源图/标签校验逐图保存，复用 request_id。保存成功后仍需单图核对并点击“采用”，不自动提交正式 GT、触碰训练/原始图片或历史失败候选。
- 批量只处理**当前页显式勾选**，不会暗中处理跨页或服务器“全部筛选结果”；后两者需先取消后重选。预检展示可处理张数、跳过张数和将删除框数；部分失败逐图报告，不把未知回执当成功。保存时禁止切筛选、翻页、退出及审核提交，避免误将另一页结果覆盖。
- 既有未成功的历史 MODEL_LABEL_AMBIGUOUS 图片仍需在原任务中差量重试生成候选；不能把失败图片自动当无框。
- 增 CandidateStore 单测与真实浏览器合同用例，前端 JS 完整语法解析和安全算法隔离用例已在代码操作环境通过；本轮 Python pytest、真实浏览器三视口、准确 SHA GitHub Actions、4070 实机与用户实际样本数据尚待验证，**未部署服务器**。
