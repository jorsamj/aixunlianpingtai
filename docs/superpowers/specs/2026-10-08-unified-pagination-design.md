# 训练兼容性性能与统一分页设计

## 目标与边界

本改造解决两个已确认问题：训练兼容性问题列表翻页会重复计算完整 selection；平台传统结果集列表的分页交互和后端能力不一致。改造不改变 AnnotationRepository、MaterialRepository、TaskRepository、Dataset Snapshot 或业务页面 Runtime 的所有权，也不把分页组件变成业务缓存、API client 或全局 Page Manager。

最终训练受理和 Input Freeze 继续重新执行 task-specific、schema-aware、fail-closed 校验。分页优化只复用可由 canonical revision 完整失效的读取投影，不成为训练真值。

## 方案选择

采用“修订键控的有界派生投影 + 渐进式页码合同 + 单一无状态 UI 组件”。

未选择前端全量缓存，因为 20,000 张素材会扩大浏览器内存并产生过期真值；未选择为分页建立独立数据库，因为会形成第二状态 Owner；未强制废弃 cursor，因为现有顺序遍历、批处理和兼容调用仍适合 keyset pagination。

## 训练兼容性数据流

1. API 先由现有 compatibility payload provider 解析最终训练请求。
2. 从 MaterialRepository、AnnotationRepository 读取当前 revision，并对规范化训练请求、算法、`meta.json` 和 `datasets.json` 建立确定性摘要。
3. 摘要与 revision 共同形成有界 LRU 派生投影键。页码、page_size、cursor、query、issue_type 不进入昂贵计算键。
4. 首次请求执行现有 `resolve_training_selection → resolve_training_label_contract → evaluate_selection_compatibility`，保留完整 issue count、类型统计和问题详情。
5. 同一选择集的翻页和筛选只对缓存中的派生 issues 做过滤和切片，不重新读取完整 Material/Annotation。
6. Material、Annotation、标签 schema、算法、数据集名称或选择集变化都会改变 revision/摘要，使旧投影不可命中。缓存固定上限，进程重启后允许安全重算。
7. 最终训练任务不消费该缓存；AUDIT-148 Snapshot gate、正式 Input Freeze 与提交期生命周期 fence 保持不变。

缓存是可丢弃的读取加速层，不持久化业务状态，不具备写入或决定训练资格的权力。

## 后端分页合同

新增页码能力的接口同时返回：

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0,
  "total_pages": 1,
  "has_previous": false,
  "has_next": false,
  "next_cursor": null
}
```

`page` 和 `page_size` 由服务端验证。总数为零时 `total_pages` 仍为 1，当前页为 1，两个方向均不可用。超过末页返回 422，不静默返回错误页。兼容接口继续接受原 `cursor + limit`，并返回 `next_cursor`；新 UI 不循环请求前面页面来模拟随机跳转。

MaterialRepository 继续拥有稳定排序和筛选 SQL，顺序固定为 `created_at, id`。随机页码使用同一过滤 SQL 的有界 OFFSET 查询；cursor 路径保持 keyset 查询。不会把全部素材加载到 Python 或浏览器。

## 唯一分页 UI 组件

新增 `static/modules/pagination.js`，提供纯函数和一个轻量 mount API：

- 规范化 `page/pageSize/total/totalPages/loading/error`；
- 生成包含首尾页、当前页邻域和省略号的页码 token；
- 渲染上一页、下一页、数字页码、跳页输入、总数/总页数及可选 page-size；
- 验证空值、非整数、负数和越界输入并显示明确错误；
- Enter 与按钮触发同一跳转回调；
- loading 时阻止重复请求，disabled 使用真实 HTML 属性；
- 提供 aria-label、aria-current 和可见 focus 样式。

组件只发出 `onPageChange(page)` / `onPageSizeChange(size)`，不访问业务 API，不持有业务 rows，不建立 Poller。业务 Runtime 继续负责请求序号、AbortController、导航 epoch、错误恢复和列表状态。

## 分阶段接入

### 第一批：训练主链

- 训练兼容性问题列表：复用修订键控投影，支持真实随机页码。
- 训练素材选择器：后端增加 page/page_size，UI 使用公共组件。
- 训练任务详情中的兼容性 artifact 页：使用公共组件；artifact 自身已是 immutable paged truth。
- 数据集素材分页底层页码合同作为后续高频页面迁移基础。

### 第二批：高频核心页面

- 数据集素材列表、训练任务列表。
- 人工标注队列、AI 标注候选/审核。
- 清洗结果与重复素材、导入记录/失败明细。
- 模型产物与转换任务。

优先给当前只有 cursor 的 API 增加兼容 page 参数，再接 UI。已经按稳定 offset/page 查询的接口只增加统一响应适配。

### 第三批：其余真实结果集

- 标签 Full Audit、Material Integrity Audit。
- 平台同步记录、质量中心批量结果。
- Agent/资源执行记录、审计/操作历史。
- ZIP/外部标签映射中确实需要分页的结果集。

逐个入口记录 owner、数据规模、服务端查询和接入状态。不能证明是传统结果集分页的入口不机械迁移。

## 明确排除

- 图片上一张/下一张、轮播图：它们是当前工作对象导航，不是结果集页码。
- 人工标注逐图工作台：保留连续标注语义；若存在独立素材队列，只改队列。
- 实时日志、SSE 追尾、任务进度流：保留追加/追尾语义。
- 清洗确认中的渐进式图片复核：在后端结果仍为单个冻结确认集合时，不把“加载更多”伪装成随机页码；若已有权威 total 和随机查询 API，则在第二批迁移。

## 并发与错误处理

每个业务 Runtime 使用单调 request sequence 和 AbortController。旧请求晚返回时不得提交 rows、page 或 total。筛选/搜索改变时 page 重置为 1；删除导致当前页越界时，使用服务端 total_pages 调整后重新请求一次。弹窗关闭或页面切换时 abort，组件只反映所属 Runtime 的 loading/error。

## 验证

- Python：缓存命中、各 revision/schema/selection 失效、page 边界、cursor 兼容、1k/10k/20k I/O 计数。
- JavaScript：页码 token、跳页输入、disabled/loading、page-size、两个组件实例隔离。
- API：正常随机页与典型越界请求。
- 浏览器：训练选择器和兼容性问题弹窗的页码/筛选/快速切页冒烟。
- 每批执行相关测试、语法/导入、`git diff --check`，推送后核验精确 HEAD Actions/check-runs。

真实生产 OSS、GPU、Agent/RKNN 和部署数据量继续标记 `PENDING USER UAT`。
