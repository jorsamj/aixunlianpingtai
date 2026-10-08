# 全平台结果集分页清单

更新时间：2026-10-08。本文以真实 final owner 为准，区分传统结果集分页、已有 cursor/load-more 结果集和不应机械替换的逐项工作流。

## Phase 1 已接入

| 业务入口 | Final owner | 后端合同 | 状态 |
|---|---|---|---|
| 训练素材选择 | `TrainingMaterialPickerRuntime` | v62 `page/page_size` + legacy `cursor/limit` | 已接入共享分页 |
| 训练创建兼容性问题 | `TrainingMaterialSummaryRuntime` | v62 authoritative totals + revision-keyed projection | 已接入共享分页 |
| 训练任务 input issues | `TrainingRecoveryRuntime` | Artifact manifest `page/limit` | 已接入共享分页 |

## Phase 2 高频结果集（待独立批次）

| 入口 | 当前 owner / 现状 | 迁移判断 |
|---|---|---|
| 数据集素材/筛选结果 | `MaterialPaginationRuntime`，cursor 上下页 | 需要后端 numbered page + 共享组件 |
| 训练任务/历史任务 | `TrainingTaskRuntime`，当前页面级分页需复核 | 若存在真实分段结果则迁移；不能对已全量小列表假分页 |
| AI 标注候选/审核图片 | AI review final runtime，手写分页 | 需要共享组件并确认 CandidateStore authoritative total |
| 数据清洗问题/重复素材 | Cleaning runtimes，部分 load-more/手写页 | 传统结果集迁移；逐图审核导航排除 |
| ZIP/批量导入记录与失败明细 | ZIP import final runtime，手写 review pager | 结果集迁移；上传进度流排除 |
| 模型/转换任务 | model/conversion runtimes，任务卡片列表 | 有真实分页的列表迁移；少量静态选择器不假分页 |
| 人工标注素材队列 | Annotation workbench | 队列列表迁移；画布上一张/下一张保留 |

## Phase 3 其他结果集（待独立批次）

| 入口 | 当前形态 | 迁移判断 |
|---|---|---|
| 标签 Full Audit / 样例 | label audit/review | 问题清单迁移；“换一批”抽样不是页码 |
| Material Integrity Audit | audit artifact pages | 真实结果清单迁移 |
| 平台对接同步/版本结果 | external platform runtime | 真实历史记录迁移 |
| 质量中心批量检测结果 | quality runtime | 批量结果迁移 |
| Agent/资源执行记录 | service/resource runtimes | 执行历史迁移；实时 telemetry/log 排除 |
| 系统审计/操作历史 | 对应 audit API/runtime | 存在 authoritative total 时迁移 |
| 项目/算法版本历史 | `AlgorithmListRuntime` | 版本/历史结果若分页则迁移；主算法小列表不造假分页 |
| 存储扫描异常/素材 | storage source/import runtimes | 持久化结果清单迁移；实时扫描 progress 排除 |

## 明确排除

- 标注画布、清洗工作台的上一张/下一张：这是逐图工作流导航，不是传统结果集分页。
- 轮播图、预览切换：不是查询结果页。
- 实时日志、进度流、SSE task stream：需要增量/尾随语义，页码会破坏实时合同。
- “换一批”随机抽样：不是稳定排序的第 N 页。
- 固定且很小的枚举/配置选择器：不应为了视觉统一制造假分页。

## 永久合同

- `static/modules/pagination.js` 只负责 UI 状态与合法翻页事件，不读取业务 API、不保存业务 rows、不创建 poller。
- 业务 runtime 保持自身列表 truth；后端 total/total_pages 必须权威，排序必须带唯一 tie-breaker。
- Cursor consumer 可继续使用；随机页需求必须由后端真实支持，禁止循环前置 cursor 或浏览器全量 `slice()`。
- 搜索/筛选变更回第 1 页；AbortController/sequence fence 防止旧响应覆盖；越界由服务端拒绝或显式调整后重新请求。
