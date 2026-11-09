# 2026-11-09｜WeVisOne-VL HTTP 200 部分图片失败与逐图证据 P0

## 授权范围、准确基线

- 唯一分支：`feature/external-algorithm-publishing`；开始审计时远端 HEAD `4787faac8ba669aebd9f394d7b61c2a9d3065e91`，本地工作树无未提交改动。
- 本批应用版本从 `42.24.561` 更新到 `42.24.562`；属于源码开发版本标识变化，**不是生产部署或 Release**。
- 现场提供的汇总为 27 张失败，均 HTTP 200、`response_parse` / `MODEL_LABEL_NOT_ALLOWED`，9 条/18 条两种建议文案，原始模型标签、图片及服务日志暂不可得。**无法证明这 27 张的实际标签内容及根因分布**。
- 4070 双 4070/2B/Nginx 网关、正式 GT、模型服务与运行中任务均未访问或修改；没有切换 4B。

## 代码可确认的缺陷

1. 原 `_native_boxes()` 先检查 `ref` 标签是否在允许范围，**再**检查 `<box>none</box>`。在结构化 `boxes=[]` 或纯文本回包中，模型输出描述文字变化能把合法无目标图片判为 `MODEL_LABEL_NOT_ALLOWED`。
2. 原 `_label_mapping()` 按原字符串逐字比较；首尾空白、大小写、常见句末标点差异被错误拒绝，同时缺少这些规范化后的跨类别别名冲突检测。
3. 旧 `ProviderRequestError` 能携带错误码和基础请求信息，但缺少实际被拒标签、冻结允许标签、原生查询、解析路径和仅结构摘要；候选 `_failure_evidence()` 与前端 CSV 也没有这些字段。缺少上游 `request_id` 时，已有 `annotation_inference.call_with_policy` 生成的 `platform_request_id` 未提升为显式可见的图片级追踪字段。
4. 原候选失败重试会更新同一 `item_json`，当前错误仍可见，但此前失败诊断不会保留一份可浏览的有界历史。原 CandidateStore 已限制人工草稿/审核被生成重试覆盖，本批保留该机制。

## 本批改动及安全边界

- `wevisone_vision.py`：无目标标志先于标签映射判断；严格解析完整原生结构。**有实际框的未知标签仍失败**；`boxes=[]` 与原生实际框、`boxes>0` 与原生 `none` 均明确判协议矛盾。原有像素/归一化坐标与置信度验证未放宽。
- 仅规范化确定等价的字符串：首尾空白、末尾常见标点、Unicode `casefold()`。冻结正式标签仍独立于自然语言 query，归一化后的不同标签及别名冲突一律拒绝。**不使用包含匹配/语义猜测/硬编码泛人类同义词**。
- 返回未知有效框时记录 `returned_label`、`allowed_labels`、`configured_queries`、`label_match_status`、`parser_source`、`zero_box` 和 `response_summary`；响应摘要仅含结构计数、声明的坐标系和图像尺寸，不存储模型原始文本、图片 base64、完整 HTTP 请求体或凭据。文本截断并做敏感字符过滤。
- `annotation_inference` 已有同图内链路编号 `platform_request_id`，本批将其作为 `request_trace_id` 传入原 CandidateStore；第三方 request_id 不存在时仍保留空值，不伪造上游编号。API CandidateStore 现有逐图接口和原 CSV 导出页即可直接展示。
- `annotation_task_service` 原 CandidateStore 写入路径新增有界 `error_history`（此前最多 5 条），重试成功时仍保留失败证据；原“只补跑 failed，保留 success/empty、人工草稿、审核及正式 GT”逻辑未改。界面“重试此图”成功受理后沿用现有 ModalContentRuntime 所有权校验，关闭旧详情层后再进入同一任务详情轮询，避免弹窗嵌套，也不必整页刷新。
- `static/app.js` 同一失败明细区展示实际标签、冻结查询、允许标签、实例、内部追踪、HTTP 与形状摘要；CSV/JSON 导出字段对齐且 CSV 防公式注入，不增加新页面或二级弹窗。

## 标签协议的保守结论

如果模型返回自然语言 `standing human`，而冻结 `person` 查询是一个完整长句，**这不是可证明的纯显示等价**。没有响应中明确的正式代码、可验证的 query index 或人工明确配置的别名时，仍记 `MODEL_LABEL_NOT_ALLOWED`，在失败详情展示真实标签供确认。绝不自动把 human/person/tangzhe 互相归类。当前记录不足以证明 27 张真实失败中各有多少属于零框或标签同义文本。

## 回归测试与验收状态

- 模拟原生 ref/box、合法未知描述零框、结构化空框、未知标签有效框、矛盾的原生/结构化返回、格式/坐标错误、大小写/标点/空白、别名冲突、HTTP 200 非法 JSON、无上游 request ID、请求实例/诊断、原 CandidateStore 局部失败与差量重试、成功/人工草稿保护。
- Python 受控 5 组（WeVisOne Provider、原 AI Task Service、CandidateStore、Provider 请求元信息、v60 Annotation Task Runtime）**248/248 通过**；Node 前端完整合同集 **1579/1579 通过**（含重试弹窗单 Owner 回归）。另外扩大到 `tests/api/test_auto_label_candidates.py` 的探索运行得出 244 通过、1 失败（后续增加回归用例后总数已变化）：该失败测试仍期望已退役 v47 写接口返回 200，现正式返回 410，属于本批前已有的过期测试断言，本批**不恢复旧接口**。准确远端 CI 仍需单独核验。
- 本轮无真实 4070 回放或图像，因此不能宣称 27 张现场图片均成功。需要部署后的独立受控差量重试实测：备份任务和候选快照、确认失败集合、只补跑失败图、核对已成功和已审候选、检查每图字段与统计、再人工审核；不直接入正式 GT/负样本池。

## 修改文件与 CI

`VERSION.txt`、`platform_core/providers/wevisone_vision.py`、`platform_core/annotation_task_service.py`、`static/app.js`、`static/index.html`、`tests/unit/test_wevisone_provider.py`、`tests/unit/test_annotation_task_service.py`、`tests/frontend/wevisone-failure-evidence.test.mjs`，以及本记录、`AGENTS.md`、`docs/CODEX_CURRENT_STATE.md`。最终远端 commit SHA 及 CI 必须在推送后核对，不以此前 561 的历史 CI 代替。
