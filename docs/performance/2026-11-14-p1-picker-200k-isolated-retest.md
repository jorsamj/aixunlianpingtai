# P1-01｜20 万素材选择器隔离性能复测报告（2026-11-14）

- 唯一开发分支：`feature/external-algorithm-publishing`；开始基线：`15d3539203fff2fbf13f41668638c427e5dae8b6`
- **原代码与测试工作流的实际测试 SHA**：`99d9bd9e387d49e9e9149184fc72bdbf76e4818c`；GitHub Actions [Training Material Picker（Attempt 2）](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43538637750)，新复测后端 Job **132285763266**，结论 **success**。
- **代码一致性证明**：本次用 GitHub blob SHA 比较了测试 SHA 和当前审计基线的 `training-material-picker-runtime.js`、`training_material_picker_api.py`、`material_repository.py`、两份 200k 性能测试及选择器工作流 YAML，全部逐文件相同。两次提交之间的其他文档/测试变更不影响本轮测量对象。
- **测试性质**：隔离 GitHub Actions Ubuntu 24.04 / Python 3.12，真实项目 `MaterialRepository`、`AnnotationRepository` / SQLite 元数据和 FastAPI in-process 测试，按需生成假 ID/GT；**没有 A800/双4070 生产数据、20 万张图片解码、真网络或 GPU 训练**。
- 只读测试 + 本次文档记录；无业务代码修复、无生产服务/数据写操作。P0-06C 真实任务对账继续由用户决定是否恢复，当前仍 **DEFERRED / NOT VERIFIED**。

## 一、实测：20 万条素材的元数据分页

在 `tests/performance/test_material_workbench_200k.py` 的 20 万条 SQLite 元数据阶段，每种情境连续测 **21 次**。时间仅含当前 Python `repo.list_page()` 调用，不包含网络/浏览器：

| 查询 | 本次冷首查 ms | 本次 P50 ms | 本次 P95 ms | 先前 P95 ms |
|---|---:|---:|---:|---:|
| 首页（48 条） | 3.663 | 0.997 | **1.155** | 1.319 |
| 深页（接近最后，48 条） | 5.829 | 4.943 | **5.688** | 6.275 |
| 来源 + 标签筛选 | **40.817** | 1.148 | **1.376** | 1.342 |
| 文件名筛选 | **18.057** | 0.926 | **0.991** | 1.142 |

解释：深页的确有比首页更多的查询成本，但该隔离测试中未成为百毫秒级瓶颈。来源/标签、文件名筛选的**首查**显著慢于重复查询，后续缓存更快。该假数据集使用高度规则化的创建时间/文件名和小元数据，没有生产真实 GT、磁盘争用与多用户并发，因此不能外推生产 P95。

## 二、实测：20 万条素材的历史/目标筛选

在 `tests/performance/test_picker_history_filters_scale.py` 中，每项仅运行 **7 次**。源码把 `sorted(samples)[-1]` 写为 `p95_ms`，**实际上是 7 次最大值而非统计意义上的稳定 P95**；下表明确按“最大值”标注。

| 情境 | P50 ms | 7 次最大 ms | 前轮 7 次最大 ms |
|---|---:|---:|---:|
| 仅当前历史范围 `current_only` | 3.516 | **3.802** | 4.825 |
| 已使用 `used` | 4.442 | **4.504** | 5.965 |
| 待确认负样本 `pending_negative` | 7.510 | **7.854** | 9.230 |
| 目标极稀疏、最后才有正样本 `sparse_last_positive` | **43.451** | **43.949** | 52.845 |
| 目标没有匹配正样本 `no_match_positive` | **41.240** | **41.543** | 50.011 |

历史筛选 `EXPLAIN QUERY PLAN` 包含 `SCAN m` 与用 `training_usage_tokens` 主键/覆盖索引的关联查询，说明 SQLite 确实使用部分索引，但外层扫描仍需结合过滤条件测量；不能简单认定全库均已索引覆盖。GT 极稀疏/无结果时需更长的前向查找，当前是**最有证据的相对热点**，但 40–50ms 的单请求隔离耗时并不能证明需要重构。

## 三、API/Chrome 的补充证据

**相同复测后端 Job**的 in-process FastAPI，使用 **1,000 条合成素材、20 次暖请求**（不是 200k）：
- `role-page`：P95 **18.321ms**；冷首查 68.725ms；
- `page`：P95 **14.103ms**；
- `revision`：P95 **5.212ms**；
- `selection-summary`：P95 **11.772ms**。
这些 API 耗时涉及序列化等完整进程内处理，不能与上面单纯 SQLite 的 200k 毫秒数直接相加成生产页面耗时。

**同一测试代码的既有 Chrome 隔离运行**，成功 Job [132273676504](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43538637750)，每次 60 张模拟卡、10 张优先解码 192px 图片，首轮 219.1ms/1 次 71ms Long Task；暖打开 20 次 P50 **137.75ms**，P95 **151.2ms**，零暖态 Long Task。请求统计：页面 API 1 次、revision 20 次；**Chrome Job 结果来自前次执行，第二次仅重跑后端 contracts Job，并未重新采集 Chrome 样本**。Chrome 页面/缩略图由 Playwright 拦截，无真实网络/正式图片。

## 四、验收与执行建议

1. 本次重跑的 `contracts` Job **success**：后端 174 passed / 2 skipped；冻结 20k 到 Prepare Worker 合同 3 passed；隔离 200k 性能子集 **5 passed**；既有 `real-chrome-picker` Job 同源代码执行为 success。最终任务链路的生产数据对账仍延期。
2. **结论 A**：先不重构 `app.js`、不替换 Vue/React、不改数据库。常规前/深页元数据 SQL 在单机隔离场景无明显灾难性耗时；同环境浏览器温态 60 卡渲染无 Long Task。
3. **结论 B**：后续仅针对“稀疏/无匹配目标”和“冷首查来源/标签”补**更贴近真实分布**的隔离 SQL / GT 测试、查看 `EXPLAIN` 和计数/负样本历史 SQL 阶段；是否优化以可复现的明显时间收益为准。
4. **结论 C**：代码职责拆分可以另做维护性专项，首选把 picker 约 582 行、29k 字符 CSS 按需移到独立样式文件；但这本身没有得到性能收益证据。拆分时还要同步迁移现有 workflow 的 CSS 字符串 `grep` 守卫、保持首次打开样式/移动端滚动/冻结引用回归，不能为了小文件而制造 FOUC 或新增静态依赖。
5. 已知独立问题：此前 `e625ace8` 的全仓浏览器分片训练创建弹框滚轮断言失败，不属于本次 picker SQLite 性能测试；仍应单独复查，不能用本次成功给它结案。

**下轮推荐**：若要继续优化，先补**稀疏/无匹配筛选的真实索引执行计划及 200k 性能采样**，保留单一选择状态 Owner；再判断要不要只拆 CSS。用户延期的 P0-06C 不自动启动。
