# P0｜超限跨筛选全选时防止早先逐项选择静默丢失

日期：2026-11-13  
唯一长期分支：`feature/external-algorithm-publishing`  
本轮代码基线：`b4ad738bfe440d440971a1590644bfeba0f148cb`，`VERSION.txt=42.24.592`，**37/37 GitHub Actions 成功**、Frontend Node **1663/1663**。

## 1. 已复现的最小缺陷

- 用户此前已在其他筛选中逐张选择了若干训练素材：`picker.selected.size > 0`。
- 用户执行「全选当前筛选」；当前筛选结果超过服务端单次显式 ID 上限 **50,000** 张。
- 为保留此前显式选择，前端的 `preferReference` 为 false，先请求 `/training-materials/bulk-selection`。
- 后端返回 `422`，detail 含“超过单次选择上限”；`resolveBulkSelection()` 自动回退 `freezeReference()`，即使早已有显式选择。
- `bulkAction()` 收到 `result.reference` 后执行 `picker.reference=result.reference;picker.selected.clear()`，因此先前其他筛选逐项选择的图片并不属于新冻结筛选，被**静默丢失**。此前没有明确拒绝或用户确认。
- 当前基线隔离函数实测：已有显式 1 项，60,000 张触发限额，依次发起 bulk-selection / selection-reference 两次调用并返回新 ref；随后清空显式选择的代码路径确定。

## 2. 最小修复及影响面

- 沿用原 `TrainingMaterialPickerRuntime`，在 `freezeReference()` 最前面检查 `picker.selected.size`：若仍有显式选择，则拒绝把它们替换为另一范围的冻结引用，提示“当前已有逐张选择，超限筛选结果无法安全合并；请先全部不选，再全选当前筛选范围”。
- 现有 `bulkAction()` 的异常分支保留原有选择、解除 loading，并显示可操作提示，不产生冻结引用，也不清空已有素材。
- `picker.selected.size===0` 的正常超限 fallback 不受影响；已知超过 2,000 的优先冻结、训练草稿、GT Summary、训练 Worker 都不变。
- 新增 Node 回归实际抽取 `resolveBulkSelection` 运行两个分支：有历史显式 ID 的 422 限额只发 1 次请求并拒绝，旧 ID 不变；空选材的超限仍发 2 次请求并正常返回冻结 ref。现有 Chrome 大范围冻结回归继续执行。
- 同步入口主资源 `static/index.html` 中 app.js/main.mjs/styles.css 的数字缓存键为 `42.25.605`，以及 `main.mjs` 的 picker 导入 `42.25.605`；更新相应的固定版本测试守卫，不削弱断言。`VERSION.txt` 不变。
- 此处选择 fail-closed，而不自行开发「冻结范围 + 显式 ID 联集」第二套存储/选择 Owner。需要该能力时必须单独设计原 Manifest 的安全并集合同和人工确认交互。

## 3. 现有真实代码链路审计（不重复巨量压测）

| 阶段 | 原有真实合同和已有隔离测试 | 正式现场待验 |
| --- | --- | --- |
| 冻结 | `selection-reference` 枚举服务端筛选结果，Manifest SQLite 保存去重 ID 数量和 SHA256 | 用户实际筛选、修订一致性、冻结耗时 |
| 页面摘要 | `selection-summary` 校验引用后按真实 GT 统计 `requested/matched/eligible/pending` 和 `positive_label_codes` | 真实 GT 数量、正标签、空标注/负样本归因 |
| 草稿和 POST | 前端 `trainSelectionRef`；POST `train_selection_ref` 与空 `train_image_ids`；服务端 `_explicit_training_split` 展开后存入 parent `payload.json` 与 `requested_split` | 用户确认 → 服务端任务 ID/实际引用计数一致 |
| Worker 准入 | `TrainingPrepareHandler.run` 先执行 `validate_payload_references`，再执行 `_freeze_request_contract`；Prepare 生成 `input-request-selection.json`、`input-freeze.json` 和 `selection_counts` | 真实任务 Prepare 后“选入/正式 GT 有效/待补审/历史或缺失移除”的逐段归因 |
| 现有测试 | `tests/api/test_training_request.py::test_frozen_20000_http_parent_reaches_real_prepare_worker_reference_guard` 参数化 20k、30k；另一小型正式 GT 测试覆盖完整 Prepare→Freeze；`tests/browser/training-material-picker-performance.spec.mjs` 覆盖大范围选择浏览器提交 | 这些测试不能冒充 20k/30k **真实正式 GT** 完整 Prepare 和生产耗时 |

## 4. 正式环境一次性只读取证矩阵（尚未执行）

现场必须先核对实际运行版本及任务状态，且仅选择**已经真实创建**、不需要启动新训练的任务进行验证；不要运行写入型压测、重启 Worker 或修改 GT。建议仅采集下列数字及匿名摘要，不导出实际素材 ID、图片或凭据：

| 对照证据 | 比对方法 | 例外解释 |
| --- | --- | --- |
| HTTP freeze 返回的 `selection_ref/count` | 与冻结 Manifest `meta.count`、当前 manifest `selection` 行数和 SHA256 进行比较 | 如果引用过期或文件缺失，记录失败原因，不重建 |
| 表单摘要 `requested_count/matched_count/selectable_count/eligible_count/pending_annotation_count/positive_label_codes` | 与同一次引用、同一上下文及修订对应，不用其他任务的摘要 | 清洗候选不等于 GT 有效素材，不能直接将 eligible_count 当成 freeze count |
| 父任务不可变请求 `payload.json`、`requested_split`、`train_selection_ref` | 比较冻住的原请求 ID 集与所持久化的原始选材 ID 集；记录匹配布尔值、数量和 SHA，而非原始 ID | Web 在创建时会把 ref 展开，前端 POST `train_image_ids=[]` 是正确合同 |
| `input-request-selection.json`、`input_selection_recheck` | 检查 Worker 实际读取原范围与是否因排队中素材失效而剔除；**缺失 ID 不自动补选** | 如果原选中 30,000，排队后素材变更，可有有据剔除；必须列出剔除数量 |
| Worker `selection_counts` 和 `input-freeze.json.selection` | 比较 `selected_train_count`、`effective_train_count`、`pending_annotation_count`、`test_count`；核对 Snapshot 和 `input_freeze_id` | `selected_train_count` 不必等于最终有效训练数；未标注不得自动当零框负样本 |
| Train/Val/Test 与历史版本资格 | 根据现有 input-freeze / manifest / history_admission 审核，不做 GT 投影重写 | 同 SHA 内容不能 Train/Test 泄漏；历史训练和版本资格不允许为了速度放宽 |

**性能测量原则**：每次只采既有真实请求链的浏览器 `PerformanceNavigationTiming`/Network（DNS/连接/TTFB/传输/JS/DOM），已有 `performance_measure`（`training.selection_summary`、`training.create.source_admission` 等）、SQLite 操作与 Worker 阶段时间。先收集少量真实样本的 P50/P95 及失败原因，不能将 30 秒 Initial connection 直接归因于数据库。无现场连接和记录前保持“生产未验收”。

## 5. 当前边界

- 本轮是源码/回归修复，非 A800/4070 部署或线上实测。
- 不迁库，不新增缓存 Owner，不复制/清理任何 GT 或训练数据。
- 本轮新代码 SHA 及其 CI：**提交后另核，以准确 SHA 为准**。

## 2026-11-13 本项结案复核

超限跨筛选保护提交 `6b6bf11b6928b548c9323018b08bc6f3356e69c0` 的准确 GitHub Actions **37/37 completed/success**，Frontend Node **1664/1664**；Training Material Picker 的 contracts/real-chrome-picker 均成功。上文“CI 待查”为该记录撰写时状态，以本段为最终结果。后续另开「批量操作中复选框并发」最小专项，不更改本轮 50,000 超限 fail-closed 合同；真实正式 GT 20k/30k 的生产 Worker 验收仍未完成。
