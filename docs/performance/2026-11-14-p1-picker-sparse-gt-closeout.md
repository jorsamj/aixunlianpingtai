# P1｜20 万素材稀疏正式 GT 标签筛选精准优化结案（2026-11-14）

## 范围与版本

- 唯一开发分支：`feature/external-algorithm-publishing`
- 业务代码及回归验收 HEAD：`604da713bf1ab4b64afe8e95897b8b0f06e4284b`
- 最终 CI：[Training Material Picker #43546801407](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43546801407)，`contracts` 和 `real-chrome-picker` 均 **success**
- 对此 HEAD 的关联 GitHub Actions 检查时：**22/22 completed/success；失败 0、进行中 0**
- 本次修复只涉及查询局部逻辑、测试与工作流监听；未部署生产服务器、未修改生产数据库。

## 根因和改动

旧 SQL 以 `materials` 状态及排序索引驱动扫描，对每条素材通过正式 GT 的相关 `EXISTS` 检查标签。20 万素材且标签仅在末尾或完全无匹配时，候选查找明显变慢。正式 GT 已有索引 `ix_annotation_label_references_code(label_code,image_id)`，不需要新建索引。

在 `platform_core/training_material_picker_api.py` 增加**有界正式 GT 优先路径**：同一 SQLite 读事务中使用索引最多探测 257 条正式 GT，匹配数不超过 **256** 且请求为**单一目标、正样本、`count_mode='deferred'`、`include_payload=True`** 时，先找 GT ID，再关联素材。其余场景（常见标签、多标签、负样本、精确计数等）保持旧 SQL。保留原来源、文件名、时间、GT、历史使用、排序、分页和游标等全部条件。256 是保守阈值，不代表生产环境最优值。

## 最新成功 CI 实测

测试使用仓库真实 `MaterialRepository`、`AnnotationRepository`、SQLite 和**20 万条隔离合成素材元数据**，不是生产图像/真实 GT。

| 查询场景 | 先前隔离 P50 | 本轮最终隔离 P50 | 本轮 7 次最大值 |
|---|---:|---:|---:|
| 稀疏末尾正样本 | 43.451 ms | **3.157 ms** | 3.280 ms |
| 完全无匹配正样本 | 41.240 ms | **0.941 ms** | 1.740 ms |

P50 相较旧轮观测改善约 92.7% / 97.7%；两轮 CI runner 的环境可能不同，**不得当作生产提速保证**。历史筛选子集仅采样 7 次，测试键名 `p95_ms` 实际取最大值，**不是稳定 P95**。

同一次最新 CI 的**独立 SQL-only probe**（非完整 Python 角色分页）在 21 次采样中：稀疏材料优先 23.679ms vs GT 优先 0.168ms；无匹配材料优先 23.459ms vs GT 优先 0.028ms，素材 ID 和顺序一致。此 probe 专门对照两条 SQL，本轮真实业务耗时以表格上方为准。

## 回归范围

- 后端合同：**176 passed、2 skipped**。
- 20,000 张 HTTP 冻结选择到 Prepare Worker 隔离合同：**3 passed**。
- 200k SQLite 规模测试：**5 passed**；额外后端性能子集：**9 passed**。
- 追加旧/新查询结果等价、正反排序、分页/游标、来源/文件名及额外 GT 筛选、训练历史排除、常见标签回退等回归测试。
- Chrome Job：success；60 张模拟卡、20 次暖打开 P50 133.05ms / P95 175.3ms，暖态 Long Task 0；首次打开 217.5ms。Playwright 拦截网络/缩略图，**不代表真实生产端到端性能**。
- 一次新增测试夹具曾遗漏 NAS 来源所需的 `object_key`，导致新合同用例失败；已经修正测试数据，未放宽生产校验；最终 CI 全绿。

## 结论与后续

**P1 稀疏正式 GT 标签查询的隔离代码及专项 CI 验收通过，可以结案。** 当前不建议继续围绕本慢路径做无依据的大重构、迁移 MySQL、引入 Vue 或盲目添加索引。

生产页面、真实磁盘负载、真实 GT 分布、并发与网络尚未测量。20,000 张选择后创建训练任务及 Prepare Worker 身份对账（P0-06C）仍需独立验收；弹窗滚动问题不能由本次 CI 自动结案。任何生产部署、数据变更或 Worker 重启均须明确授权。

### 证据

- [最终成功 CI](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43546801407)
- [优化前 20 万素材性能报告](2026-11-14-p1-picker-200k-isolated-retest.md)
- [最终业务及回归提交](https://github.com/jorsamj/aixunlianpingtai/commit/604da713bf1ab4b64afe8e95897b8b0f06e4284b)
