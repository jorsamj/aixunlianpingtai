# W14｜20 万素材真实性能基线（2026-11-24）

> **性质**：隔离环境真实测量（临时数据目录、真实 Owner/Repository/ReaderView、无生产数据、无联网、无 GPU）。
> **不是生产 P50/P95**，不能替代现场验收。标识约定：`MEASURED`=本轮实测；`NOT VERIFIED`=无证据。
> 基线 SHA：`66ec7d70`（分支 `feature/external-algorithm-publishing`，工作区含其他并行未提交改动，见 §10）。
> 复现用例：[test_scale_200k_baseline.py](../../tests/performance/test_scale_200k_baseline.py)；逐项原始证据 JSON：[2026-11-24-scale-200k-baseline.json](2026-11-24-scale-200k-baseline.json)（`SCALE_PERF_REPORT` 输出，含每项 SQL/JSON/SHA256/字节/RSS）。

## 1. 结论摘要

1. **200k 规模测量全部真实执行**：素材 200,000 条 + 8 个真实 JPEG；正式 GT 40,000；算法 110 / 模型版本 1,100；任务 1,160；训练用量证据 200 个任务（500 条历史已用素材）；AI 候选 20,000 行；转换历史 1,000 个 job 记录；冻结选择清单 20,000 条。构建 109.17s（基线）/ 88.75s（优化后），**构建成本单独记录，不计入任何请求延迟**。
2. **热路径基线整体良好**（20 万素材）：素材库首屏 P50 11.59ms / P95 12.54ms；深翻页 offset≈199,950 P50 42.25ms；选材分页 P50 38～44ms；算法/模型/任务/报告列表 P50 ≤22.31ms；AI 候选分页 P50 47.66ms；无 N+1、无网络调用、读路径 0 次模型二进制打开。
3. **定位到 2 个真实冷路径代价**（均为既定设计、各有缓存/边界闸门）：
   - **20k 跨页筛选冻结**：`/selection-reference` 按 1,000 行/页枚举，20 页 × 每页固定开销（连接、ATTACH、revision 校验）导致基线冷冻结 1,738.64ms（含历史）/ 2,582.11ms（含历史排除）。
   - **组合筛选空交集 + 文件名 LIKE**：空交集最坏 597.16ms P50（20 万行有序扫描直到确认无行），文件名搜索 P50 63.00ms；位于 `material_repository.py`，**不在本轮最小整改允许文件内**，只记录基线，不改。
4. **最小整改（1 处生产代码）**：`training_material_picker_api.py` 冻结枚举页大小 1,000 → 5,000。20k 选中 20 页 → 4 页；仪器化全量复跑：含历史冻结 **1,738.64→801.74ms（-53.9%）**、含历史排除冻结 **2,582.11→1,443.32ms（-44.1%）**，SQL 语句 241→81 / 281→89；冻结数量与排除语义全部断言通过（20,000 / 19,500；40 个抽样已用 ID 在排除清单 0/40、含历史清单 40/40）。
5. 其余所有读路径在两次整轮测量中的差异均在运行间噪声范围（示例：首屏 P50 11.59→8.67ms、搜索 63.00→62.85ms），**未据此声称任何收益**。

## 2. 环境（MEASURED）

| 项 | 值 |
|---|---|
| OS | Windows 11 `10.0.26300`（`Windows-11-10.0.26300-SP0`） |
| CPU / 内存 | Intel Core Ultra 7 255H，16 逻辑处理器；33,752,997,888 B（31.4 GiB） |
| Python | 3.12.7 |
| SQLite | 3.45.3（WAL）；FastAPI 0.138.2；pytest 8.4.2；psutil 7.2.2 |
| 隔离 | pytest `tmp_path_factory` 临时目录；无生产数据 / 网络 / GPU / 模型二进制 |

**未测**：CPU 主频、磁盘型号与 IOPS、Windows Defender 实时扫描开关、跨重启冷缓存、真实 OSS/NAS/浏览器网络（见 §12）。

## 3. 数据规模与构建成本（MEASURED）

| 数据 | 规模 | 写入方式 | 构建耗时（基线 / 优化后） |
|---|---:|---|---:|
| 素材元数据 | 200,000（+8 真实小图） | `MaterialRepository.upsert_many`（1,000/批） | 32.28s / 24.59s |
| 正式 GT | 40,000 | `AnnotationRepository.upsert_many`（500/批） | 37.69s / 28.81s |
| 算法 / 模型版本 | 110 / 1,100 | `AlgorithmSqlStore.replace_all` | 0.05s / 0.07s |
| 训练任务 | 1,160（1,100 历史 + 60 可 claim） | `TaskRepository.create` | 29.02s / 26.23s |
| 训练用量证据 | 200 任务（25 任务训练 500 条 focus 素材） | `TrainingMaterialUsage.record_selected/record_execution` | 6.48s / 5.49s |
| AI 候选 | 20,000 行 | `CandidateStore.initialize/append_items` | 0.86s / 0.91s |
| 转换历史 | 1,000 个 `job.json` | 文件写入 | 2.13s / 2.08s |
| 报告/载荷产物 | 60 payload + 20 result | `ArtifactStore.atomic_write_json` | 0.61s / 0.54s |
| **合计** | — | — | **109.17s（基线）/ 88.75s、89.82s（整改后两次复跑）** |

DB 体积：`materials.sqlite3` 291,778,560 B（278.3 MiB）、`annotations.sqlite3` 17,092,608 B、`tasks.sqlite3` 3,108,864 B、`algorithms.sqlite3` 1,122,304 B、AI 候选 6,189,056 B。
构建差异来自文件系统缓存/杀毒扫描等环境噪声，不作为优化收益。两个 200k 测试整轮：基线 **4 passed in 150.96s**，整改后 **4 passed in 123.27s**（含构建）。

## 4. 测量口径（必须随数字一起引用）

- 素材库：直接调用真实端点函数 `app.list_materials_v61(...)`（Repository + ReaderView 全路径；**不含 HTTP 服务器/鉴权中间件**）；`响应字节`=响应 JSON 序列化字节数（不含 HTTP 头）。
- 选材/跨页选择：真实 `training_material_picker_router` + FastAPI `TestClient`（进程内，无网络）；字节=真实响应体。
- SQL 次数：包装 `sqlite3.connect` 统计 `connection.execute`（含 BEGIN/COMMIT 等），按"每次逻辑调用"折算；`cursor.execute` 未重复计入。SHA256=包装 `hashlib.sha256` 计数（`from hashlib import` 的模块级引用不计）。文件打开=包装 `builtins.open`/`io.open`。
- P50/P95：最近秩法；冷值=窗口前第 1 次调用；暖值默认 ≥11 样本（部分重查询 3～7 样本）。`RSS 峰值`=测量窗口内 10ms 采样的进程 RSS 峰值（psutil），非全进程高水位。
- **峰值内存（MEASURED）**：整改后证据轮全部测量窗口 RSS 峰值 **104.2～202.5 MiB**；最高为 AI 候选全量 20k 行（7.73 MB 响应，202.5 MiB），20k 冻结/摘要类 **115.5～127.0 MiB**，素材库分页/统计 **约 104～140 MiB**；未观察到随 200k 素材线性膨胀的进程驻留增长（每项测量独立窗口采样）。
- 所有 SQL/JSON/SHA256/文件/网络计数在测量窗口内收集；**冷值也带探针**，探针自身开销已计入该冷值（对 20k 冻结这类 2 万次 json 调用的路径有轻微放大；前后对比同口径）。
- 独立 A/B 微基准（§8.1）为无探针直接计时，用于复核优化收益方向。

## 5. 素材库读路径（MEASURED，200k）

`SQL/次、JSON/次、SHA256/次`为单次调用计数（两次整轮测量一致，仅列一次）。`基线 → 整改后`为两次独立整轮同命令结果。

| 场景 | cold ms | P50 ms | P95 ms | SQL/次 | JSON/次 | SHA256/次 | 响应字节 | 整改后 cold/P50/P95 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 首屏 50 条（reader_view） | 33.67 | 11.59 | 12.54 | 6 | 51 | 0 | 32,645 | 30.51 / 8.67 / 11.88 |
| 深翻页 page=4000（offset≈199,950） | 47.05 | 42.25 | 43.88 | 6 | 51 | 0 | 32,386 | 32.53 / 34.30 / 45.06 |
| 组合筛选（来源+状态+标签） | 569.42 | 11.76 | 17.89 | 6 | 51 | 0 | 31,971 | 553.53 / 8.22 / 50.09 |
| 组合筛选空交集（最坏） | 1,115.57 | 597.16 | 894.23 | 6 | 1 | 0 | 173 | 949.61 / 556.02 / 571.03 |
| 文件名搜索 `camera-0012` | 103.17 | 63.00 | 69.86 | 6 | 51 | 0 | 39,272 | 89.52 / 62.85 / 69.19 |
| 处理状态统计（cold→暖窗口） | 394.13 | 5.93 | 6.48 | 5 | 0 | 0 | — | 286.68 / 4.06 / 4.49 |
| 标注索引统计（cold→暖） | 568.75 | 5.45 | 5.47 | 3 | 0 | 0 | — | 529.14 / 6.10 / 6.56 |
| 标签引用统计 | 29.22 | 25.55 | 28.27 | 4 | 0 | 0 | — | 34.59 / 34.67 / 217.31* |
| 素材摘要 | 6.36 | 7.81 | 10.06 | 5 | 0 | 0 | — | 44.84* / 8.53 / 12.09 |
| 素材详情 reader_view | 13.34 | 36.97 | 57.51 | 5 | 4 | 0 | 1,107 | 14.03 / 11.66 / 13.88 |
| 缩略图冷（真实 JPEG ×4） | 405.09(首张最高) | 166.47 | 405.09 | 4→0 | 2→0 | 5 | 736-791 | 157.41(P95)/43.31(P50) |
| 缩略图暖缓存 | 70.98 | 12.02 | 15.40 | 0 | 1 | 2 | 736 | 18.71 / 11.55 / 13.10 |

\* 同代码路径两次运行间噪声（首查后统计有 revision 缓存；该行为未改动），不据此下结论。
读路径画像：**无 N+1**（SQL 次数与页大小无关，固定 6 条/首屏；详情 5 条）、**读路径 SHA256=0**；缩略图暖缓存每次仍有 **2 次 SHA256**（源文件校验 + 缓存身份推导，见 §8）。冷缩略图含缓存初始化、JPEG 解码/LANCZOS/编码与 5 次 SHA256。

## 6. 跨页选择 / 冻结引用（MEASURED，20,000 选中）

| 场景 | cold ms | P50 ms | P95 ms | SQL/次 | JSON/次 | SHA256/次 | 响应字节 | 整改后 cold/P50/P95 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 冻结 20k + 历史排除（19,500） | **2,582.11** | — | — | 281 | 20,039 | 5 | 133 | **1,443.32** |
| 冻结 20k + 包含历史（20,000） | **1,738.64** | — | — | 241 | 21 | 5 | 131 | **801.74** |
| 正式选择摘要（20k 引用） | 737.14 | 532.87 | 1,311.68 | 52 | 1,457 | 3 | 504 | 741.09 / 479.80 / 596.92 |
| 成员校验 100/20k | 32.32 | 37.35 | 40.37 | 14 | 4 | 2 | 1,311 | 33.67 / 35.01 / 44.53 |
| 选择并集重冻结 | 260.55 | 299.04 | 329.61 | 43 | 10 | 6 | 81 | 198.42 / 283.18 / 328.80 |
| 冻结清单服务端读取 20k | 19.80 | 17.31 | 18.21 | 3 | 2 | 1 | 160,000(估算 ID 字节) | 16.06 / 16.60 / 20.20 |
| 选材分页第 1 页（延迟计数） | 38.23 | 38.37 | 40.91 | 20 | 85 | 0 | 52,840 | 38.14 / 35.04 / 36.11 |
| 选材分页第 500 页 | 44.74 | 43.54 | 46.33 | 20 | 85 | 0 | 52,990 | 40.84 / 42.67 / 45.30 |

**语义断言（全部通过，整改前后一致）**：
- 历史排除语义：20,000 筛选 − 500 条该算法历史已用 = 冻结 **19,500**；抽样 40 个已用 ID 在排除清单 **0/40**，在含历史清单 **40/40**。
- 冻结数量 == 选择数量（含排除）：`count` 字段与 `read_selection` 服务端展开长度一致（20,000/19,500）。
- **不把 20k ID 传给前端**：冻结/摘要响应体 133/131/504 B（仅 `selection_ref`、计数、摘要标量）；`/bulk-selection` 超限走 **422 + 58 B** 保护（不返回 ID 数组）；服务端清单 20k 行只在后端读取。
- 手动排除/重新勾选路径：`selection-union` 以既有冻结引用重冻结（P50 283ms，count 20,000），未传 2 万 ID。
- 未跑真实训练、未写真实 GT（仅隔离 GT）。
- 摘要 20k 的 P50 479.80ms（P95 596.92ms）为**本轮最大的常规业务读路径**，主要成本：20k 临时表+GT 汇总 77ms + 正类证明 18～28ms + 往返 SQL；SQL 次数固定 52、无逐行查询。本文件内尝试的两种 SQL 改型均**无收益已回退**（见 §8）。

## 7. 算法库 / 模型版本 / 任务 / 报告 / 转换历史 / AI 候选（MEASURED）

| 场景 | cold ms | P50 ms | P95 ms | SQL/次 | JSON/次 | 响应字节 | 整改后 P50（对照） |
|---|---:|---:|---:|---:|---:|---:|---:|
| 算法启动摘要（110，摘要模式） | 11.82 | 10.28 | 15.19 | 11 | 0 | 39,720 | 11.26 |
| 模型资产列表第 6 页 | 11.55 | 12.22 | 13.35 | 15 | 0 | 4,376 | 12.56 |
| 算法摘要全量（110×10 版本，summary） | 25.76 | 22.31 | 23.71 | 10 | 1,210 | 785,070 | 22.34 |
| 模型版本列表 / 详情 | 5.18 / 4.52 | 5.24 / 4.41 | 5.50 / 5.71 | 12 / 8 | 30 / 8 | 11,598 / 1,941 | 4.41 / 3.98 |
| 算法库卡片（统计投影） | 6.08 | 6.16 | 7.17 | 13 | 10 | 7,031 | 5.85 |
| 训练任务列表第 1 页 / 深游标页 | 6.01 / 6.81 | 6.45 / 6.31 | 6.90 / 7.58 | 3 / 3 | 50 / 51 | 6,688 | 6.26 / 6.22 |
| 任务摘要 / 详情投影 | 2.58 / 11.85 | 1.64 / 3.74 | 2.01 / 4.31 | 0 | 1 / 2 | 627 / 840 | 1.45 / 3.97 |
| 训练报告读取（1 任务） | 4.19 | 4.26 | 4.77 | 0 | 2 | 3,170 | 4.37 |
| **转换历史冷扫描 1,000 文件** | **4,673.97** | — | — | 0 | 1,000 | 4,969 | 5,918.01（I/O 噪声） |
| 转换历史暖缓存深页 | 3.94 | 3.94 | 4.36 | 0 | 0 | 4,964 | 3.74 |
| AI 候选分页（20k 行） | 15.81 | 47.66 | 75.25 | 14 | 51 | 19,389 | 14.54 |
| AI 候选摘要 / 统计 / 标签汇总 | 92.42 / 38.39 / 231.17 | 82.78 / 67.75 / 63.41 | 136.35 / 188.66 / 111.50 | 13 / 19 / 13 | 1 | 129 / 148 / 52 | 40.04 / 32.27 / 65.14 |
| AI 候选全量 20k 行（兼容接口） | 262.13 | 324.12 | 329.05 | 113 | 20,001 | 7,734,000 | 251.53 |

- **不读模型二进制、不逐条访问 OSS**：模型版本读取 + 全量摘要 + 转换历史查询探针窗口内 `model_binary_opens=0`、`network_calls=0`、`file_opens=0`（25 SQL、1,210 JSON）。
- 算法/版本/任务/报告/转换历史路径均**无 N+1**（SQL 次数固定）；`转换历史`冷页成本来自 1,000 个 `job.json` 的 stat+parse（**非 SQL**），暖缓存 3.94ms。
- `AI 候选全量 20k`（7.73 MB 响应）为兼容接口最坏情况；生产消费者应使用 `iter_items`（代码注释已声明 all_items 仅兼容）。

## 8. 瓶颈定位证据与最小整改

### 8.1 冻结枚举页大小（保留的整改）

- 证据：`/selection-reference` 的 `ids()` 生成器以 `limit=1000` 调 `_gt_material_filter_page`；20k 选中需 20 页，每页固定成本=新连接 + `ATTACH annotation_gt` + 6～8 条 revision/校验 SQL + 游标查询准备。同进程 A/B（同一 200k 世界、无探针、交替执行）：
  - 页循环 include_history：**764.02ms（20 页）→ 398.86ms（4 页）**；
  - 页循环历史排除：**1,280.56ms（20 页）→ 825.53ms（4 页）**；
  - 完整"上下文+页枚举+冻结写入"等价路径：include_history **725.75→631.48ms（-13%）**、排除 **1,948.71→1,233.46ms（-37%）**。
- 改动（唯一生产代码修改，6 行含注释）：

```diff
-                    result=_gt_material_filter_page(repository,annotations,limit=1000,cursor=cursor or None,
+                    # Wider server-side pages amortize the per-page connection,
+                    # ATTACH and revision-check cost of a filtered freeze. A 20k
+                    # selection drops from 20 pages to 4 without changing the
+                    # filtered row order or the frozen identity set.
+                    result=_gt_material_filter_page(repository,annotations,limit=5000,cursor=cursor or None,
```

- 复跑（同命令、同 200k 构建、同口径）：含历史冻结 **1,738.64→801.74ms（-53.9%）**、SQL 241→81；含排除冻结 **2,582.11→1,443.32ms（-44.1%）**、SQL 281→89；冻结数量、排除语义、响应字节全部不变。收益来自批量（页数）而非 SQL/索引语义。**第三次证据轮**（原始 JSON 见文档头）：含历史冻结 744.56ms、含排除冻结 1,183.31ms、SQL 81/89，与上轮一致（慢路径剩余成本为历史排除 anti-join 的 2 万次关系 token 计算，非分页开销）。

### 8.2 已尝试但回退的改型（无一保留）

| 想法 | 基线 → 结果 | 结论 | 原因 |
|---|---|---|---|
| `_selection_summary` 用 `json_each(?)` 派生表替换 TEMP 表 | 249.44 → 283.67ms P50 | **revert** | 3 条查询各自解析 2 万个 JSON 元素，更慢 |
| `_selection_summary` 去掉 COUNT/SUM 聚合、由 processed 行推导 | 249.44 → 283.67ms P50 | **revert** | 无收益（原聚合预热了临时表页，去掉反而更慢）；字段逐项等价已验证 |

### 8.3 未整改的真实代价（越界/下轮候选，本轮只记录）

- **组合筛选空交集**：20 万规模暖 P50 597ms / P95 894ms（确认无行需有序扫描完筛选池）；`EXPLAIN QUERY PLAN`=`SCAN materials USING INDEX ix_materials_created`。
- **文件名 LIKE 搜索**：P50 63ms；同为索引有序扫描 + LIKE，无 FTS。
- **统计冷值**：处理状态统计 cold 394ms、标注索引统计 cold 569ms（均为 20 万行聚合/`json_extract`）；两者按 revision 缓存，暖值 4～6ms。
- 上述查询位于 `material_repository.py`（本轮允许文件之外）；任何索引/FTS/投影改动都会影响写放大或契约，**不作为"最小整改"实施**。

## 9. SQLite 并发（MEASURED，9 线程混合读写）

9 线程 × 固定轮次：3×任务 claim+心跳+完成、2×素材查询、2×批量审核写（50 行/批）、1×20k 冻结选择读取、1×模型版本归档写、1×算法读。

| 指标 | 基线 | 整改后 |
|---|---:|---:|
| 窗口 | 1,892.89ms | 2,146.91ms |
| SQL 总数 / 单条最长 | 4,677 / 718.70ms | 4,679 / 658.99ms |
| 最长事务 | 722.58ms | 662.20ms |
| 事务 >100ms | 2 | 3 |
| **SQLITE_BUSY/写锁错误** | **0** | **0** |
| 未捕获错误 | **0** | **0** |
| claim（含心跳+完成） | P50 119.46～132.16ms | P50 130.12～141.47ms |
| 批量审核写 50 行 | P50 94.24ms / P95 290.98ms | P50 90.79ms / P95 135.97ms |
| 素材分页读（争用下） | P50 13.84ms / P95 567.61ms / max 915.05ms | P50 13.53ms / P95 567.32ms / max 727.46ms |
| 20k 冻结读取 | P50 35.25ms | P50 32.54ms |
| 模型版本归档写 | P50 14.08ms | P50 16.23ms |
| 算法读 | P50 30.75ms | P50 33.47ms |

- 所有写事务均为短事务（仓库层 `BEGIN IMMEDIATE`→`COMMIT`）；最长 660～720ms 出现在批写与 claim 竞争下的排队/fsync 组合，未出现无界重试、未出现 `database is locked`（`busy_timeout=30s` 吸收）。
- 测量窗口内 `network_calls=0`（无事务中网络调用）；读路径 SHA256 计数为 0（除选择冻结/缩略图显式校验）。
- **未测**：锁等待单独分离（以语句最长耗时与事务最长耗时作为上界）、跨进程并发、WAL checkpoint 阻塞、真实 Worker 背景负载。

## 10. 修改文件与 git 状态

- 新增：`tests/performance/test_scale_200k_baseline.py`（`RUN_SCALE_PERF=1` 门控，默认 CI 不构建 200k；可用 `SCALE_MATERIALS` 缩小规模）。
- 修改：`platform_core/training_material_picker_api.py`（仅 §8.1 一处批量页大小 + 注释）。
- 文档：本文件。
- **未执行任何 git 写操作（无 add/commit/push）**。工作区存在其他并行任务的未提交改动（`app.py`、`platform_core/online_feedback.py`、`platform_core/hard_sample_mining.py`、`tests/api/test_online_feedback.py`、`tests/unit/test_online_feedback.py`、`docs/architecture/W15_W16_*.md` 及若干未跟踪文档），**非本轮改动、未触碰**。
- 未改：VERSION、app.py、保护文档、conversion/model_artifacts/online_feedback、frontend、node_agent。

## 11. 复现命令与准确输出

```powershell
# 1) 200k 真实测量（构建 + 4 项测量，约 2～2.5 分钟）
$env:RUN_SCALE_PERF='1'
python -m pytest -q tests/performance/test_scale_200k_baseline.py -rs
# 基线（整改前）：4 passed, 8 warnings in 150.96s
# 整改后：      4 passed, 8 warnings in 123.27s
# 证据轮（写 docs/performance/*.json）：4 passed, 8 warnings in 120.84s
# 可选：$env:SCALE_PERF_REPORT='<path>.json' 输出逐项原始 JSON；$env:SCALE_MATERIALS='50000' 缩小规模

# 2) 既有性能用例回归（本机 201.73s；200k 用例默认门控跳过）
python -m pytest tests/performance -q
# 35 passed, 12 skipped, 8 warnings in 201.73s  ← 新增 4 项在未设 RUN_SCALE_PERF 时被跳过

# 3) 改动文件编译
python -m py_compile tests/performance/test_scale_200k_baseline.py platform_core/training_material_picker_api.py
# exit 0

# 4) 定向回归
python -m pytest -q tests/api/test_training_material_picker_api.py tests/api/test_training_material_selection_summary_api.py `
  tests/api/test_platform_performance_diagnostics.py tests/unit/test_training_selection_reference.py `
  tests/unit/test_training_material_picker_history_sql.py
# 99 passed, 2 failed（失败为本机既有环境问题，见下）
python -m pytest -q tests/api/test_training_request.py tests/api/test_material_selection_atomicity.py
# 79 passed
```

**既有本机失败（与本次改动无关，已用回退法证实）**：`tests/unit/test_training_material_picker_history_sql.py` 2 项在本机报
`sqlite3.OperationalError: unable to open database: file:///C:/...tasks.sqlite3?mode=ro`；
把本轮改动临时回退后同一命令**同样 2 failed**，恢复改动后仅这两项失败，故判定为环境/既有问题，未改测试规避。

## 12. 未验证 / NOT VERIFIED（不得当作已通过）

1. 生产 P50/P95/P99、真实生产数据分布与多用户并发（本报告全部为隔离测量）。
2. 真实 OSS/NAS/远程对象存储 I/O、限流、慢节点；真实浏览器网络（DNS/TCP/TLS/弱网）与前端渲染。
3. 真实 HTTP 服务进程/鉴权中间件/反代开销（素材库为端点函数直调；选材为进程内 TestClient）。
4. 真实图片规格（大图/EXIF/损坏图）与缩略图真实解码耗时；本轮仅 8 个 320×240 真实 JPEG。
5. 真实训练/GPU、模型转换、模型二进制解析与发布链路（本轮 0 次模型二进制打开、0 网络）。
6. 跨进程 SQLite 并发、WAL checkpoint 阻塞、锁等待的独立分离统计。
7. 重启后 OS 冷缓存、Windows Defender 扫描影响分离、1M 规模。
8. CPU/内存限制容器、Linux CI 环境下的绝对毫秒数（P50/P95 仅对本机有效）。
9. 冻结 20k 的"摘要/预检"之外的真实训练提交链路（本轮未跑训练、未写真实 GT）。
