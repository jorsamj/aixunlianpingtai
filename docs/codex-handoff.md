# Codex / 人工接管交接记录


## 2026-09-26 21:xx AI 人工审核大批量决策性能收口（最新）

- 写入前真实远端 HEAD：`e09e68d1bce4de9f3e115f7794e56b6ab404d5a2`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- `e09e68d...` 自身 20 个主要 GitHub Actions workflows 已全部 **completed success (20/20)**，没有 queued / in_progress / failure。
- 本轮开始时真实远端为 `f669fcc7103d635f257d0003756aa2590f54f7c4`；从交接参考 `f714e66e...` 到该 HEAD 仅继续了 Remote Cleaning projection guard 与文档封口，没有并发代码覆盖上一轮 Annotation / Training / Import 性能收口。

### 本次新关闭：AI 审核 decisions N+1

正式 `/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions` 之前存在两层逐图读取：

1. API 为每个 decision 调 `CandidateStore.get(image_id)` 校验 status；
2. `CandidateStore.apply_decisions()` 再为每个 decision 执行一次 `SELECT ... WHERE image_id=?`。

大批审核跨多页累计 decisions 时会形成 N 次/两层 SQLite 读取。

提交：

- `4bf3d64d411c33ca42b3dc8f19b24900a8410397` — `perf: batch AI review candidate decisions`
- `e09e68d1bce4de9f3e115f7794e56b6ab404d5a2` — `test: tighten AI review batch contracts`

现状：

- decisions 按 **200/批** 一次 `IN (...)` 读取；
- status 必须仍为 `success/empty` 的 fail-closed 校验进入同一个 `BEGIN IMMEDIATE` transaction；
- 任意后续 batch 含 missing/failed candidate 时整批 rollback，不会部分应用；
- 1001 条结构合同要求 **200/200/200/200/200/1 = 6 次** candidate read，永久禁止退回 scalar `SELECT ... image_id=?`；
- 不改变 Candidate→人工审核→durable Commit 架构，不新增 CandidateStore / runtime / polling owner。

### 标签重校验内存边界同步收口

`CandidateStore.remap_labels()` 仍必须在正式 Ground Truth commit 前对 current active canonical label fail-closed 重校验，这个产品/数据真相不能删除。

旧实现一次 `fetchall()` 全部 success/empty candidate；现在改为：

- `ordinal > ? ORDER BY ordinal LIMIT 200` keyset pagination；
- 1001 条为 6 个真实数据页；
- 最后一页不足 200 时直接结束，不再额外做空页 SELECT；
- 单 transaction 语义保持不变。

### 真实 CI 红灯与修复记录

`4bf3d64d...` 的 AI Annotation Recovery 曾出现真实 completed failure，已读取 Ubuntu/Windows job log，失败来自新加结构测试本身，而非生产语义回归：

1. “禁止 scalar get”探针安装后，测试末尾自己又调用 `store.get()` 验证 rollback，被自己的 guard 拦截；
2. keyset 1001/200 的循环原先还会做第 7 次空页探测，而测试要求严格 6 次。

`e09e68d...` 修复为：

- rollback 断言使用 `get_many([id])`，测试自身也遵守批读合同；
- 最后一页 `len(rows) < 200` 直接 break。

最终 `e09e68d...` 的 AI Annotation Recovery 及全部 20 个主要 workflows 均 completed success。

### 本轮继续审出的剩余 P1（证据已确认，尚未修改）

1. **AI 审核 reject/partial 的重复全候选扫描**
   - `_decide_annotation_candidates()` 当前即使 `label_mapping={}` 也会先 `store.label_summary()` 全扫候选；
   - 随后 `remap_labels()` 再扫 success/empty；
   - 纯“拒绝全部”不会写任何 Ground Truth，却仍执行标签重校验全扫。
   - 后续应只在确有 mapping 时读取 source label facts，并只对最终可能进入正式标注的候选做 canonical label revalidation；不能削弱 accept/commit 的 fail-closed 标签真相。

2. **Remote Material review 250k 行峰值内存**
   - `_MAX_REVIEW_ROWS = 250_000`；
   - `_read_review_rows()` 当前同时持有 `candidates[]`、`staged[]`、`seen set`，调用方还构造完整 `candidate_keys set`；
   - ImportCandidateStore 自身已经是 SQLite durable truth，当前整批 Python dict/list 会放大 20k~250k review 的峰值内存。
   - 后续应复用现有 ImportCandidateStore / RemoteMaterialStagingStore 做流式/批量落库，不得新建第二套 import owner；同时保留完整 archive/payload/hash/annotation coverage fail-closed 验证。

3. **训练 dataset materialization 本轮复核**
   - 新文件复制已经通过 `_HashingReader` 在 copy pass 同步计算 source SHA256；
   - 未发现“复制后再完整读取原图 hash 一遍”的退化；
   - 只有截断 JPEG 被实际修复后才计算修复后的 training hash，属于必要训练输入真相，不应删除。

### 验收边界仍保持诚实

结构测试与 20/20 CI 只能证明 owner / transaction / 批量复杂度 / fail-closed 合同，没有替代：

- 真实 20k / 50k 图片内容；
- 真实 OSS/S3 RTT；
- NVIDIA Linux；
- SQLite WAL contention；
- 峰值内存与真实磁盘 IOPS；
- 慢网络浏览器与长时间恢复。


## 2026-09-26 20:xx 本轮最终状态封口（最新）

- 写入前真实远端 HEAD：`c04c8961af8cc3810a20f1ea6399e6d1a296c390`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- 当前 HEAD 的 **20 个主要 GitHub Actions workflows 已全部 completed success**：
  - success = 20
  - failure = 0
  - queued = 0
  - in_progress = 0
- 因此本轮可以把当前 HEAD 记为 **CI 真绿**；后续若远端继续有并发提交，下一会话仍必须重新读真实 HEAD 和 checks，不能沿用本段 SHA 假设未来状态。

### Remote Cleaning Runtime 红灯已闭环

上一轮 `f714e66e...` 唯一 completed failure 的真实 job log：

`test_filtered_clean_confirmation_stays_inside_frozen_selection_and_exposes_provenance`

失败原因为：

`ValueError: material fields are not mutable: clean_task_id`

根因是正式 cleaning projection 已开始写 durable provenance，但 MaterialRepository 的 batch patch mutable-field guard 尚未允许这些正式字段。后续提交：

- `83d660e073f98f00ae79606391c6e97b7e96d1ad` — allow durable cleaning projection fields；
- `c04c8961af8cc3810a20f1ea6399e6d1a296c390` — record cleaning batch guard closure。

只允许正式 cleaning projection 字段，未知字段仍 fail-closed，没有为了 CI 放宽为任意字段可写。当前 HEAD 的 Remote Cleaning Runtime 已 completed success。

### 手工标注最终 owner 再确认

最终 canonical `saveAnnotationCore420` 当前保存后：

- 只更新当前 formal annotation / 当前 `state.images` 项；
- 只 patch 当前素材卡片；
- 如果从图片预览进入，只 patch 下层 preview overlay；
- 不调用 `loadAll()`；
- 不调用 `loadCore412()`；
- 不调用 `reloadMaterialPage61()`；
- 不重建整个数据集 gallery。

因此“画框 → 保存 → 继续下一张”当前没有已确认的全页刷新性能债。后续不要重复重写这个 owner。

### 本轮最终完成范围

最初三个重点性能债均已 CLOSED：

1. AI `load_task_images()`：全库扫描 → MaterialRepository indexed batch lookup，<=500/批。
2. AI `commit_candidate_decisions()`：逐图 Candidate/Annotation DB I/O → 200/批 formal GT + commit journal，保留 fencing/cancel/idempotency/crash recovery。
3. Training `_selected_project_images()`：逐图 AnnotationRepository.get → <=500/批 get_many，并有 1k/10k/20k 结构合同。

后续同一轮还完成并验证：

- AI canonical label 只能由用户明确选择 current code；display name / alias / 历史 alias 不自动映射。
- AI task create 素材与 reference annotation 均批量 indexed lookup。
- AI 详情 PollRegistry 单 owner，关闭 modal 会清理 polling；与列表 poll 不并行。
- 标签统一 / AI / 自动清洗高频进度统一 transform 更新，避免高频 width/layout。
- 标签统一完成后只刷新 label + 当前 material page + import review，不 broad bootstrap。
- 手工标注 GET/SAVE 单图 Material indexed lookup。
- 历史 Annotation 摘要迁移 500/批读写。
- Training scoped label projection 复用 frozen truth，不二次 Annotation N+1。
- Benchmark reuse / supplement Candidate Set Material+Annotation 批读。
- selected batch split 只 patch 选中 ID，不 full-table mutate。
- TrainingSubmitRuntime 显示真实创建阶段，并已推进模块 cache-bust key。
- 并发提交继续补齐：大上传后续 UI 限量、大清洗 selection durable 冻结、bulk ready 走 Material Batch、post-import review 批读、训练报告复用 frozen label counts、单素材编辑 indexed、训练质量读取 bounded、clean confirmation scoped writes。

### 现在剩余的不是代码结构债，而是环境验收

仍需在生产/预生产环境做：

- 真实 20k / 50k 图片内容；
- 真实 OSS / S3 RTT；
- NVIDIA Linux 节点；
- SQLite WAL contention；
- 峰值内存；
- 慢网络浏览器；
- 长时间任务恢复 / 浏览器刷新 / 断网恢复。

这些不能由结构合同冒充真机结果。

## 2026-09-26 20:xx 清洗合同红灯修复与最终 owner 审计（最新）

- 写入前真实远端 HEAD：`83d660e073f98f00ae79606391c6e97b7e96d1ad`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- 上一 HEAD `f714e66e...` 的 20 个主要 workflows 中，已返回 **15 success / 4 pending / 1 completed failure**。
- 唯一 completed failure 为 **Remote Cleaning Runtime / api**；同一 workflow 的 Real Chrome、Windows contract、Ubuntu contract 均 success。
- 真实失败日志：
  `test_filtered_clean_confirmation_stays_inside_frozen_selection_and_exposes_provenance`
  因 `MaterialRepository.patch_many()` 拒绝 `clean_task_id`，错误：
  `ValueError: material fields are not mutable: clean_task_id`。
- 根因不是 cleaning durable task / frozen selection / provenance 逻辑错误，而是 batch guard 的可写字段白名单没有跟上正式 cleaning projection 已使用的字段。

### 本次修复

提交：`83d660e073f98f00ae79606391c6e97b7e96d1ad`

只补齐正式 cleaning projection 已存在的 4 个字段：

- `clean_skipped`
- `clean_decision`
- `clean_decision_at`
- `clean_task_id`

继续保留 batch patch 的 fail-closed 边界：未知字段仍然必须抛出 `material fields are not mutable`，没有放宽为任意 Material payload 可写。

新增永久单测验证：

- 上述 cleaning projection 字段可以通过 `patch_many()` 持久化；
- `clean_task_id` 与 skip/decision provenance 可读回；
- 任意未知 projection field 仍被拒绝。

新 HEAD 的 20 个 workflows 在写入时刚重新触发，Remote Cleaning Runtime 为 queued；**不能把 `83d660e...` 写成全绿，必须等待 terminal。**

### 手工标注最终保存 hot path 再确认

最终 canonical owner `saveAnnotationCore420` 已再次核对：

- 保存 formal annotation 后只更新当前 `state.images` 单项；
- 只 patch 当前 Material card；
- 若从图片预览进入，仅 patch 下层 preview overlay；
- 不调用 `loadAll()`；
- 不调用 `loadCore412()`；
- 不调用 `reloadMaterialPage61()`；
- 不重建整页 dataset gallery。

因此“画框 → 保存”当前没有已确认的全页刷新性能债，不要再重复重写标注保存 owner。

### 并发会话最近继续补齐的同方向收口

本轮继续工作期间远端新增并已核对的提交：

- `805c6219...` — bound large upload follow-up UI。
- `6bc168b2...` — freeze large clean selections durably。
- `fdd49b00...` — route bulk ready through material batches。
- `e4d9a3d9...` — batch post-import review reads。
- `f671489e...` — use frozen training label counts in reports。
- `5e37969a...` — index single material edits。
- `1e52430e...` — keep import review batch-scoped。
- `dc97d56e...` — batch dataset and upload review reads。
- `1eaa0afb...` — bound selected training quality reads。
- `684c7653...` — scope cleaning confirmation writes。
- `704a8cc2...` / `f714e66e...` — documentation sync。

这些均沿用既有 Annotation / Material Batch / Cleaning / Training owner，没有发现新建第二套 runtime 的冲突。

### 当前剩余

1. 等待 `83d660e...` 自身 20 个主要 workflows terminal；任何 completed failure 继续先读真实 job log。
2. 真实 20k/50k 图片、OSS/S3 RTT、NVIDIA Linux、SQLite WAL contention、峰值内存和慢网络浏览器 profiling 仍属于生产/预生产验收。
3. 不再对“仅存在但无正式调用证据”的 legacy compatibility 函数做泛化清理。

## 2026-09-26 晚间最终性能审计进度（最新，覆盖下方同日旧状态）

- 本节写入前真实远端 HEAD：`704a8cc25c280a3480b146d65b8aef367de08fa0`（docs-only）。
- 最新产品代码基线：`684c7653f00cb5781015c26bf288dcb4df030e85`（`perf: scope cleaning confirmation writes`）。
- `704a8cc2...` 的父提交 `684c7653...` 已将清洗确认阶段改为冻结 selection 的 indexed get_many + patch_many；当前 handoff 不应再把该项列为待优化。
- `VERSION.txt = 42.24.0`，仍未修改。
- 未 merge main、未 tag、未 release、未 force push。
- 写入前 HEAD `704a8cc2...` 的 20 个主要 Actions 当前仍全部 queued，**不能把最新增量写成全绿**。
- 已完整 terminal 的强基线：
  - `0a2ff10ab45ea0f011ed4f8090a042b610410755`：20/20 主要 workflows completed success。
  - `07fef8c2c9f6d8a99e9c4632730e618bdc4947f7`：20/20 主要 workflows completed success。
- 因此本轮 Annotation / AI Annotation / Training Input / Node Agent / Label Normalization / Remote Runtime 等关键改造均已有完整绿基线，但最新增量仍必须等待其自身 terminal checks。

### 本轮最初三项性能债：全部 CLOSED

1. AI `load_task_images()` 不再 `load_images(project_id)` 全库扫；500/批 MaterialRepository indexed lookup。
2. AI `commit_candidate_decisions()` 不再逐图 Candidate/Annotation SQLite I/O；200/批 formal GT + commit journal，保留 fencing/cancel/idempotency/crash recovery。
3. `training_tasks._selected_project_images()` 不再逐图 AnnotationRepository.get；500/批 get_many，并有 1k/10k/20k 结构合同。

### 后续额外关闭的正式热路径

- 手工标注 GET / SAVE：单图 Material indexed lookup；前端保存后只 patch 当前素材卡与下层预览，不 loadAll、不全页重绘。
- AI 创建标签：只接受用户明确输入的 current canonical code；中文名 / alias / 历史 alias 不再自动转换。
- AI task create：选中素材存在性 + reference annotations 均 <=500/批，不再全库扫描。
- AI 详情 polling：PollRegistry 单 owner；modal close 清理；打开详情时暂停列表 poll，关闭/终态恢复。
- 标签统一 UI：字段级 patch + transform 进度，不再 850ms 整块替换 modal。
- 自动清洗详情进度：transform-only。
- 历史 Annotation 摘要迁移：500/批 Annotation read + 500/批 Material projection patch。
- Training scoped label projection：直接复用已冻结 selected rows，不再第二轮 Annotation N+1；有 20k 合同。
- Benchmark reuse / supplement Candidate Set：Material + Annotation 都批量读取。
- selected batch split：只 patch 选中 ID，不再 full-table mutate；filtered marked/unmarked Annotation 500/批。
- 标签统一完成后 refresh：只刷新 labels + 当前 material page + import review，不再 broad bootstrap/loadAll。
- TrainingSubmitRuntime：创建期间显示真实阶段；不伪造 durable task 创建后的 snapshot/Ground Truth 阶段。
- training-submit.js cache key 已推进，避免浏览器命中旧模块。
- 普通上传 / ZIP / Material Batch / PollRegistry 正式 owner 继续保持唯一。

### 并发会话已补齐且本轮已核对的性能收口

远端在本轮工作期间继续前进，已确认这些提交方向与当前架构一致，没有覆盖冲突：

- `805c6219...` — bound large upload follow-up UI。
- `6bc168b2...` — freeze large clean selections durably。
- `fdd49b00...` — route bulk ready through material batches。
- `e4d9a3d9...` — batch post-import review reads。
- `f671489e...` — use frozen training label counts in reports。
- `5e37969a...` — index single material edits。
- `1e52430e...` — keep import review batch-scoped。

这些均属于“复用正式 owner、去全扫/N+1/大 DOM”的同一收口方向，不要重新造第二套 runtime。

### 本轮最后新增的性能收口

1. **Dataset listing**
   - 旧：每个 dataset 都重新过滤全素材 + 每图 read_annotation，复杂度接近 dataset_count × image_count。
   - 新：一次遍历素材，Annotation <=500/批，单次聚合各 dataset images/annotated/boxes。
   - 提交：`dc97d56e5fd897e86146e3ce73926487573abfe0`。

2. **v55 upload batch enrichment**
   - 旧：为一个 upload batch 调 `load_images(project_id)` 全库。
   - 新：只按 batch items 的 image_id，<=500/批 MaterialRepository.get_many。
   - 1201 条结构测试验证 500/500/201。
   - 提交：`dc97d56e...`。

3. **训练素材数据质量**
   - 正式 UI `trainQuality429` 会传明确 image_ids。
   - 旧：即使只选 100 张，也先 load_images(project_id) 全库；Annotation 逐图；每个 box 的 normalize 还会重复 get_project。
   - 新：明确 image_ids / snapshot 时只 indexed 读取指定素材；Annotation <=500/批；质量检查复用已加载 project_state，不再每框重复 get_project。
   - 1201 张结构测试验证 Material 500/500/201、Annotation 500/500/201、project truth 只读一次。
   - 提交：`1eaa0afbf16a972c8106b0f57f787eadd58e7d37`。


4. **清洗确认阶段**
   - 正式清洗 owner 已是 MATERIAL_BATCH durable task，selection 在创建时冻结。
   - 旧确认路径仍用 MaterialRepository.mutate() 全表扫描，只为更新冻结 selection 的 processed/cleaned_at/clean_task_id。
   - 新：冻结 ID 500/批 indexed get_many，确认仍存在后使用 patch_many(batch_size=500)；被删除/已不存在素材不进入 processed_ids。
   - 1201 条合同验证 500/500/201，并永久禁止 full-table mutate。
   - 提交：`684c7653f00cb5781015c26bf288dcb4df030e85`。

### 并发会话晚间新增收口（已核对）

- `dc97d56e...`：dataset listing 与 upload review 改为批量 Annotation/Material 读取。
- `1eaa0afb...`：训练素材质量读取限制在明确 selection/snapshot，Material/Annotation <=500/批，并复用 project truth。
- `684c7653...`：清洗确认不再 full-table mutate；冻结 ID 500/批 get_many 后 500/批 patch_many。
- 手工标注最终保存 owner 已再次核对：保存后只 patch 当前 material card 与下层 preview overlay，不调用 loadAll / loadCore / reloadMaterialPage，不存在已确认的保存后全页刷新债。
- 这些新增改动与本轮既有 owner/runtime 一致，没有新建第二套 Annotation / Cleaning / Training / Import owner。

### 手工标注最终 hot-path 结论

- pointermove 只改当前 active box DOM + requestAnimationFrame 合帧。
- pointerup 才写 dirty/history/sidebar。
- saveAnnotationCore420 保存后：
  - 只更新 formal AnnotationRepository；
  - 更新当前 state.images 单项；
  - patch 当前 material card；
  - 如从预览进入，只 patch 下层预览 overlay；
  - 不 loadAll / 不 reloadMaterialPage / 不重建整个 gallery。
- 因此“画框拖动 + 保存”当前不再存在已确认的全页高频刷新债。

### 仍未完成的只有两类

1. **最新 HEAD 自身 CI terminal**
   - `1eaa0afb...` 当前 20 个 workflows 仍 queued。
   - 任何 completed failure 必须先读真实 job log，不能用旧绿基线替代最新结果。

2. **真实环境 profiling**
   - 真实 20k/50k 图片内容；
   - 真实 OSS/S3 RTT；
   - NVIDIA Linux 节点；
   - SQLite WAL contention / 峰值内存 / 解码吞吐；
   - 浏览器实际大批选择与慢网络。
   - 当前自动化证明的是复杂度/owner/contract，不冒充真实硬件吞吐验收。

## 2026-09-26 标注 / AI / 训练 / 素材性能二次收口（最新）

- 本节产品代码基线 HEAD：`8443bd384cc9ee9fd6c92e8b36f78fe6aefefbbf`。
- `VERSION.txt` 仍为 `42.24.0`；未 merge main、未 tag、未 release、未 force push。
- 当前 HEAD 的 Actions 仍大量 queued，**不能写成全绿**。
- 可确认的历史全绿基线：`0a2ff10ab45ea0f011ed4f8090a042b610410755` 的 20 个主要 workflows 全部 completed success，包括 Windows Node Agent Executor。
- `07fef8c2...` 已确认 Label Normalization、AI Annotation Recovery、Node Agent Executor、Training Input Integrity 等关键合同 completed success；仍有部分远程 workflows 排队。

### 本段新增关闭项

1. **AI 创建标签决策回退 — CLOSED**
   - 正式 `submitAiLabel429()` 曾把中文显示名和 alias 自动换成 canonical code，违反“用户明确决定 canonical label”的产品合同。
   - 现前端仅接受当前有效 `label.code`；中文名、别名、历史 alias 不再转换。
   - 后端 `_v47_parse_label_text(..., catalog)` 继续 fail-closed，只接受 current canonical code。
   - AI 创建任务的素材存在性检查改为 MaterialRepository `get_many <= 500`；参考标注也改为 AnnotationRepository `get_many <= 500`，不再全库扫描 / 逐图读取。
   - 提交：`cd4937c85fa9351167da592105a83536b884119e`。

2. **Windows Agent fencing 测试竞态 — CLOSED**
   - completed failure 真实日志显示 Ubuntu 同合同通过、Windows 仅“运行中 fencing”测试 marker 未出现。
   - 根因是测试按第 6 次 heartbeat fencing，Windows Python 子进程可能尚未写 `started.marker`。
   - 测试改为 worker 已证明启动后再模拟 generation lost；保留 kill / no stale finish / no publish 全部断言。
   - `0a2ff10a...` 后 Node Agent Windows/Ubuntu 均成功。
   - 提交：`0a2ff10ab45ea0f011ed4f8090a042b610410755`。

3. **AI 详情重复轮询 + modal 泄漏 — CLOSED**
   - AI 任务列表继续由 AutoLabelPollRuntime + PollRegistry 管理。
   - AI 详情不再拥有独立 `createTaskPoller(setTimeout)`；统一改为 `waitForTaskTerminal + PollRegistry`。
   - 打开详情暂停列表 poll；关弹窗/终态清理详情 poll 并恢复列表 poll。
   - 永久 source guard 已改为要求新 owner，禁止恢复旧 `createTaskPoller`。
   - 提交：`9fa3ea5b...`，合同修正：`07fef8c2...`。

4. **高频进度 DOM / layout 写放大 — CLOSED**
   - AI 详情、AI 列表 fallback、标签统一、自动清洗详情均改为 `transform: scaleX()`。
   - 标签统一 850ms poll 不再整块 `ModalContentRuntime.replace()`，只 patch stage/pct/current_item/succeeded/failed KPI。
   - 上传正式 runtime 之前已经是 rAF + transform。
   - 提交：`9fa3ea5b...`、`07fef8c2...`、`37110f071ea33f77df1411722cd7f675d173da20`。

5. **手工标注单图 GET / SAVE 全库扫描 — CLOSED**
   - `GET /annotations/{image_id}` 和保存标注不再 `load_images(project_id)` 扫全素材库。
   - 改为单 ID indexed `MaterialRepository.get_many()`；保存后 fresh material projection 也按 ID 读取。
   - 正式 AnnotationRepository 写入 owner 不变。
   - 提交：`f2946ad2c997b61d65e5f3f9ed439d5eb1608afb`。

6. **训练标签 scoped projection 二次 N+1 — CLOSED**
   - `_selected_project_images()` 已冻结正式 annotation truth 后，`_scoped_selected_project_images()` 不再重新逐图构造 AnnotationRepository 查询。
   - 直接复用 frozen row 的 annotation_state / annotation_scope / boxes。
   - 新增 20,000 行合同，若再次构造第二 AnnotationRepository 会直接失败。
   - 提交：`f2946ad2...`。

7. **训练 Benchmark / Candidate Set Material N+1 — CLOSED**
   - `_training_reusable_benchmark()` 与 `_training_supplement_candidate_set()` 的 Material truth 由逐 ID `.get()` 改为 `get_many()` + by-id map。
   - Annotation 继续批量读取。
   - 提交：`c82af336b9089615da0126b60e2739ba78bce80e`。

8. **批量移动 selected 素材全表 mutate — CLOSED**
   - `/api/v20/.../images/batch_split` 的 `scope=selected` 不再调用兼容型 `MaterialRepository.mutate()` 全表读取。
   - 改为只对明确选中 ID 做 indexed `patch()`。
   - `filtered + marked/unmarked` 仍需扫匹配范围，但 Annotation facts 改为 500/批 `get_many()`，不再逐图开连接。
   - 提交：`1cd5acfa74119f34cd978dd5d8a03b60024ca0cc`。

9. **训练创建“按钮无反应”体验 — CLOSED**
   - 继续复用唯一 `TrainingSubmitRuntime`，不新增 modal/runtime。
   - “开始训练”提交期间显示真实创建阶段：
     `读取训练配置 → 核验算法版本/主数据 → 核验训练资源/引擎/设备 → 整理训练素材与参数 → 服务端核验并创建持久任务`。
   - 不提前伪造“冻结 Ground Truth / 生成 Snapshot”进度；这些在 durable training task 创建后仍由后端真实 `phase/current_item` 展示。
   - 创建成功后现有 TrainingTaskRuntime 继续展示 `校验训练素材 / 准备训练数据 / 等待训练资源 / 验证训练设备 / 启动训练进程 / 训练中` 等 server truth。
   - 提交：`8443bd384cc9ee9fd6c92e8b36f78fe6aefefbbf`。

### owner / compatibility 审计结论

- 手工标注 pointer runtime 是最终 interaction owner；旧 mouse layer 有永久 owner guards，当前不是第二公开 owner。
- ZIP 正式浏览器 owner 为 ZipImportRuntime。legacy v19 polling 由 bootstrap claim/sentinel 接管，当前没有与正式 runtime 并行轮询。
- `pollAnnotationIndex412()` 目前仅有定义、无正式调用，不能因函数存在就当成当前高频性能债。
- v12 auto_split / dataset build 当前正式前端没有调用证据，暂不对兼容导出路径做无依据重构。
- 正式“编辑数据”当前只走 v47 名称编辑；旧 v12 dataset-id mutation 分支没有当前 UI owner 证据。

### 仍未完成 / 不得误报

- 最新 `8443bd38...` Actions 尚未 terminal，不能称当前 HEAD CI 全绿。
- 真实 20k 图片内容、真实 OSS/S3 RTT、真实 NVIDIA Linux 节点的吞吐、峰值内存、SQLite WAL contention 仍需要生产/预生产环境验收。
- 浏览器尚未发送到服务端的本地 File 字节，页面关闭后无法继续上传；不要为此制造假后台。
- 后续只继续处理**有正式调用证据**的 P1/P2；不要为了清理“旧函数名字”破坏 compatibility facade。

### 本段提交序列

`cd4937c8` → `0a2ff10a` → `9fa3ea5b` → `f2946ad2` → `c82af336` → `07fef8c2` → `37110f07` → `1cd5acfa` → `8443bd38`

## 2026-09-26 标注 / AI 审核 / 训练读取性能收口（最新，覆盖下方同日旧状态）

- 本轮重新审计时真实远端 HEAD 为 `3b3b20dd4caee5b9c10eff68d8fb4da7d45e3385`，不是交接提示中的旧 SHA；正式 `VERSION.txt` 再次确认仍为 `42.24.0`。
- 本节产品代码基线 HEAD：`1b11d808cd0bfa0d3d1c02fa809ea0371e4c9b04`。未 merge `main`、未 tag、未 release、未 force push。
- 最新 HEAD Actions 在文档写入时仍有 queued/in_progress；**不得把未结束 checks 写成 PASS**。

### 本轮真实故障与处理

1. **Label Normalization Contract 真实红灯已处理**
   - 起始 HEAD 的 completed failure 真实日志显示：标签管理后台任务状态读取失败时，错误 banner 的“重试”按钮直接调用 `renderLabelManagement414({force:true})`，触发唯一 page owner 永久 guard。
   - 已改为 `retryLabelManagement414()`，只刷新标签数据、重画当前视图并恢复 durable unify task，不重新取得页面 render ownership。
   - 后续该合同在 `4619b387...` 对应 run 中已 completed success。

2. **AI Annotation Recovery 的 completed failure 已按真实日志处理**
   - `4619b387...` 的 Ubuntu/Windows recovery-contract 都失败在新增性能测试，不是生产 Candidate/Commit API：focused worker 单测故意不安装 FastAPI，而测试用 `monkeypatch.setattr("app...")` 意外导入完整 `app.py`，报 `ModuleNotFoundError: fastapi`。
   - `89e4262936a9f9c6689bc5a83e877bb52d8a9590` 改为向 `sys.modules` 注入轻量 fake `app` Module，只提供运行时 late-bound 的 `material_store/storage_manager`；没有为了 CI 给 focused worker job 增加 Web 依赖，也没有降低测试标准。
   - 最新 AI Annotation Recovery 仍需等新 HEAD terminal 结果后才能宣称 GREEN。

### 已关闭的真实性能债

1. **AI 标注任务取图全库扫描 — CLOSED**
   - 旧：`load_task_images()` 为选中的少量 image_id 调 `load_images(project_id)`，项目 100k 素材时仍可能全库扫描。
   - 新：复用正式 `MaterialRepository` owner，按最多 500 ID 调 `get_many()`，只 materialize 本任务冻结选择，保持输入顺序并 fail-closed 检查缺失素材。
   - 提交：`8b1e5e081c24ccb80ac507886cc0588e3796a3fd`。

2. **训练创建逐图读取 AnnotationRepository — CLOSED**
   - 旧：`training_tasks._selected_project_images()` 对每张素材单独 `annotations.get()`。
   - 新：最多 500 ID/批 `AnnotationRepository.get_many()`，仍严格保持训练选择原始顺序和正式 Ground Truth。
   - 永久测试显式禁止回退到 per-image `.get()`。
   - 提交：`8b1e5e081c24ccb80ac507886cc0588e3796a3fd`。

3. **AI 人工审核 Commit 的逐图 DB I/O — CLOSED**
   - `commit_candidate_decisions()` 现在以 200 张为有界批次：
     - Candidate commit journal 批量读；
     - 正式 AnnotationRepository 批量读；
     - 正式 Ground Truth 批量写；
     - Candidate commit journal 单批事务写。
   - CandidateStore 与 AnnotationRepository 仍是两个独立 durable owner；没有伪造跨 SQLite 原子事务。
   - cancellation/fencing/idempotent replay/crash recovery 保留。若进程在 formal GT durable 后、journal durable 前退出，replay 通过 `source_task_id + candidate_id` 识别已落地任务框，幂等修复 projection 后再写 journal。
   - 1001 张合同覆盖 200/200/200/200/200/1 批次以及 replay 不重复 formal write。
   - 提交：`4619b3878f050c4dc62513e801872aac4c584f1a`。

4. **历史 Annotation 摘要迁移 N 次连接 + 巨型 patch — CLOSED**
   - 旧 `_v52_annotation_index_worker()` 对每张旧素材调用一次 `read_annotation()`，最后把全部 Material projection patch 一次性堆在内存。
   - 新：500 张/批 `AnnotationRepository.get_many()` + 500 张/批 `MaterialRepository.patch()`，仍由原后台 migration owner 负责。
   - 1201 张永久合同验证 500/500/201，且显式禁止 per-image `read_annotation()`。
   - 提交：`17d48f066fa3802ca32700e2560f2fb5265379d2`。

### 1k / 10k / 20k 结构性能合同

`1b11d808cd0bfa0d3d1c02fa809ea0371e4c9b04` 把本轮两个关键 batch lookup 固定为 1,000 / 10,000 / 20,000 三档：

- AI task image lookup：单批最多 500，总调用数必须为 `ceil(N/500)`，不能调用全库 `load_images()`。
- Training selected annotation lookup：单批最多 500，总调用数必须为 `ceil(N/500)`，不能调用 per-image `AnnotationRepository.get()`。
- 这是结构/复杂度合同，不用共享 CI runner 的偶然秒数做脆弱阈值。
- 现有仓库另已有：
  - 10k ZIP 实际 synthetic archive scan + bounded hot job state；
  - 10k Training Material Picker Real Chrome/server pagination 合同；
  - 可选 `RUN_MATERIAL_SCALE=1` 的 100k / 500k / 1M MaterialRepository scale acceptance。

**边界声明**：这些自动化不能替代真实 20k 图片内容、真实 OSS/S3 RTT、真实 NVIDIA 生产节点的吞吐/内存/WAL contention 验收。

### 手工标注 owner / UI hot path 审计

本轮没有重写标注工作台，因为正式实现已经满足目标：

- canonical interaction owner 是 `Pointer based annotation editing is the canonical interaction owner.` 对应 pointer runtime。
- `pointermove` 只修改当前 active box 的 DOM 样式，并用 `requestAnimationFrame` 合帧；不 `drawBoxes()`、不 `markDirty()`、不刷新 inspector。
- `pointerup` 才一次性提交 dirty/history/box diff/sidebar。
- final `drawBoxes()` 是增量 DOM patch，不是删除后全量重建。
- `AnnotationWorkbench` 已有 stale-request token、cache、inflight dedupe、prefetch、dirty save。
- 旧 mouse 实现仍存在于历史 classic layer，但 final public owner/source guards 已证明它不是第二个公开 owner；**不得因为“旧函数还在文件里”就未经 owner 证明直接删除 compatibility layer**。

现有永久保护包括：
`annotation-action-owner-retirement.test.mjs`、`annotation-runtime-source.test.mjs`、`dataset-annotation-public-owner.test.mjs`、`annotation-workbench.test.mjs`。

### 普通上传 / ZIP owner 审计

- 普通图片正式前端：64 文件 / chunk、单 chunk <=128MiB、严格顺序提交、XHR transfer progress、服务器确认计数、Task Center；高频进度使用 rAF + `transform: scaleX()`。
- 普通图片后端：一个 HTTP chunk 内复用 StorageManager，UploadFile stream 直接送最终存储，不先复制临时文件再二次拷贝；`_v50_begin_image_batch -> _v50_end_image_batch` 保持一次 batch repository truth，不回退到每图 SQLite transaction；SHA 在存储 copy 时计算，不做落盘后二次全文件 rehash。
- ZIP 正式浏览器 owner：multipart session、默认 8MiB part、最大并发 4、retry=2、内容采样 fingerprint、resume、server merge/validate、durable job、PollRegistry 单 owner。
- legacy direct v19 helper 仍为 compatibility surface；正式浏览器入口由 `ZipImportRuntime` 永久 guard 约束，不应另造第二套 runtime。
- storage import `INDEX_BATCH_SIZE=50` 当前是正式持久合同且每批已经使用 repository batch API。本轮没有在缺少 profiler 证据时武断改成 500，避免无依据扩大 crash/rollback 粒度。

### 本轮提交

- `8b1e5e08` — batch AI task image lookup + training annotation lookup；修 label-management retry owner。
- `4619b387` — batch AI review commit persistence。
- `17d48f06` — batch historical annotation-summary migration。
- `89e42629` — keep focused AI recovery performance test independent from FastAPI/web app imports。
- `1b11d808` — 1k / 10k / 20k annotation batch-boundary contracts。

### 仍需继续

- 等最新 HEAD 所有 required Actions terminal；任何 completed failure 先读真实 job log再处理。
- 真实 20k 图片、真实 OSS/S3、NVIDIA Linux 生产节点做吞吐/内存/WAL/RTT profiling；自动化结构合同不能冒充真机验收。
- 继续审计 AI/label-remap/training 的用户可见 stage/count/success/failed，禁止只有转圈或高频全页 refresh。
- 不新增第二套 Annotation/Candidate/Upload/ZIP/Training/Poll owner。

## 2026-09-26 最新标签治理收口状态（本节覆盖下方同日旧记录）

- 当前远端 HEAD：`6d2b8916edaaac35d1f47093d26792032cc7fc7c`；正式 `VERSION.txt` 仍为 `42.24.0`。
- 未 merge `main`、未 tag、未 release、未 force push。
- 当前 Actions 仍主要处于 queued；queued/in_progress 不算 PASS。上一轮真实 completed failure 是旧测试继续 import 已退休的 `suggest_label_code`，已由 `19621913...` 按新规则修复；`6d2b8916...` 另补齐多标签 merge 所需 `FileLock` import。

### 已完成且不得重复造第二套 runtime

1. **外部标签永远由用户决定**
   - ZIP、服务器导入、对象存储导入、storage rescan 默认全部未选择。
   - exact name / 中文名 / alias / 历史映射 / AI 语义均不得自动选择 canonical 标签。
   - AI annotation 的任务标签输入和模型 candidate 返回都只接受明确 canonical code；alias 仅用于搜索、历史来源和审计。

2. **大规模 external-label 审核 UI 已完成**
   - 共享 `label-mapping-review` owner；10k external classes 采用 50 条分页，不一次渲染 10k DOM。
   - 支持外部标签搜索、canonical 标签搜索、跨页保留人工映射、勾选多个 external labels 后批量映射到一个 canonical。
   - 提交前保留 mapped / unmapped / 图片数 / 框数 / target 汇总；任一外部标签未人工映射都不能正式提交。

3. **真实样例证据查看器已完成**
   - 每个 external class 默认 8、最多 12 个真实样例，显示真实 bbox overlay。
   - 对象存储优先 5 分钟短期 preview URL，失败时走同源且 class-fenced 的 content route。
   - 样例只提供证据，不做推荐。

4. **历史素材标签支持多来源一次统一**
   - 正式 owner 仍是 `MATERIAL_BATCH / REMAP_ANNOTATION_LABELS`，没有第二套 scheduler。
   - `POST /api/v54/projects/{project_id}/labels/unify/preview` 通过 SQLite 标签索引计算去重影响范围。
   - `POST /api/v54/projects/{project_id}/labels/unify` 一次最多 50 个来源标签统一到一个 canonical target；例如 `smoke + smoking + 吸烟 -> 抽烟`。
   - 前端提供来源多选、搜索、真实影响 loading、人工目标选择；任务创建后窗口可关闭，后台继续。
   - 全任务成功后来源标签才标记 `merged`，记录 `merged_into / merged_at` 并退出 active label；PARTIAL_SUCCESS / FAILED 不退役来源标签。

5. **Ground Truth / provenance 一致性**
   - confirmed_empty scope-only remap 已能真实落库，并有 `material_annotation_scopes` 索引。
   - remap 使用批量 `get_many` + digest fencing，不覆盖并发人工标注。
   - imported box 保留不可变的 `source_class_id / source_label_name / import_batch_id / source_format`。
   - 历史 merge 后会更新当前 `canonical_label_id / canonical_project_class_id`，来源 provenance 不改。

6. **训练前 canonical schema 防线已完成**
   - 未映射、deleted/inactive、`class_x / unknown / temp_*` 等标签直接阻断训练。
   - 训练导出只按最终 canonical schema 重新生成连续 `0..N-1`，source_class_id 永不作为 training class_id。
   - schema 结构变化记录 `label_schema_changed`；当前架构使用上一版本权重初始化，`strict_resume=false`、`optimizer_state_resumed=false`。

7. **已关闭的性能/技术债**
   - 已使用标签改编码不再同步 O(N) 扫全库，统一必须走 durable batch。
   - 未使用 canonical 标签删除改为 soft-disable，保留原 project class_id；不会重排其他标签。
   - 多标签 merge 的项目元数据写入使用文件锁 + 原子写，避免 worker 与前端元数据写入互相踩坏文件。
   - 普通上传维持分块 + 批量 repository commit；ZIP / server / object-storage 处理维持后台 durable pipeline。

### 仍未宣称完成的只有真实环境验收

- 当前 HEAD 的完整 CI 仍需等 completed 结果；出现红灯必须先读真实 job log。
- 10k 有自动化合同，但**真实 20k 素材、真实 OSS/S3 网络、NVIDIA 生产节点**的吞吐、峰值内存、WAL contention、对象存储 RTT 尚需部署环境验收。
- 浏览器尚未上传到服务器的本地文件字节，在页面关闭后无法继续传输；这是浏览器安全边界，不得为此另造假后台。

### 本轮新增关键提交

- `530f0d64` — align remote/v19 label audit contracts
- `fb48bb65` — strip stale label target hints
- `a8b2b910` → `954493b9` → `4e64400a` — scalable shared label review + state preservation
- `608b3991` → `c6d534db` — bounded real sample evidence + UI
- `3334385c` → `429e6dcd` — durable multi-source historical label merge + review UI
- `19621913` — exact canonical AI candidate truth + canonical provenance update
- `6d2b8916` — import project metadata FileLock required by merge finalization


## 2026-09-26 当前接管状态（以下内容覆盖后续历史状态段）

- 当前工作分支：`feature/external-algorithm-publishing`
- 本轮文档基线 HEAD：`60e31539454300f466b90924f4c15a7a3d3bd218`
- 正式版本：`VERSION.txt = 42.24.0`，本轮未修改版本、未 merge `main`、未 tag、未 release、未 force push。
- 当前主题：**大批量素材导入、外部标签人工映射、历史标签统一、Annotation Ground Truth、训练标签 preflight 与相关性能/技术债收口。**
- 重要产品规则：系统只提供外部标签事实和操作工具，**不自动推荐、不自动预选、不根据同名/中文名/alias/历史映射替用户决定 canonical 标签**。
- 当前 CI 状态（文档写入时）：最新 HEAD checks 仍在排队；较早 `27a4806e...` 已有部分 checks success，但不能代表当前 HEAD 全绿。只有 completed failure 出现后才根据真实 job log 修复。

### 本轮已实现

1. **导入标签映射改为人工决定**
   - ZIP、服务器素材导入、存储源重扫均默认“未选择”。
   - 后端确认不再用 exact name / alias / `target_label_code` 兜底。
   - 文件标签合法也不会隐式创建平台标签；新 canonical 标签必须由用户显式创建后再映射。
   - 已退休 `mapping_suggestions` / `suggest_label_code` 自动决策路径；外部类别只通过 `external_label_facts` 暴露事实。
   - AI 自动标注标签输入也只接受当前标签库里的明确 canonical 英文编码，不根据中文名、别名或历史映射自动解析。

2. **历史标签统一改为 durable 后台任务**
   - 正式 owner 仍是既有 `MATERIAL_BATCH / REMAP_ANNOTATION_LABELS`，没有新建第二套 scheduler/runtime。
   - 新接口：`POST /api/v54/projects/{project_id}/labels/{class_id}/unify`。
   - 后端按索引直接冻结“所有引用该标签的素材”，浏览器不再提交几万条 image_id。
   - 标签管理页增加“统一标签”，目标标签默认空白，由用户选择。
   - UI 展示正样本图片、confirmed_empty 负样本范围、标注框、受影响素材；任务有真实进度，窗口可关闭，后台继续执行。
   - 与导入后标签统一复用同一个 `annotation-label-remap` polling owner，避免第二套轮询技术债。

3. **confirmed_empty / Ground Truth 边界修复**
   - 修复旧 durable remap 只在 changed_boxes > 0 时写 AnnotationRepository，导致 confirmed_empty scope-only 变化不落库的问题。
   - MaterialRepository schema 升至 2，增加 `material_annotation_scopes` 索引；只索引 `confirmed_empty` 负样本 scope，不与正样本重复计数。
   - scope migration 和后续写入均保持索引一致。
   - 并发人工标注变化继续由 digest fencing 阻断，后台统一不会覆盖更新后的人工 Ground Truth。

4. **标签编辑 O(N) 同步扫描技术债关闭**
   - 已使用 canonical 标签不再允许在 HTTP 请求里同步遍历全部素材/标注改编码。
   - 使用中的标签如需合并/统一，必须走 durable “统一标签”后台任务。
   - `AnnotationRepository.remap_labels_if_digests` 预加载改成批量 `get_many`，减少重复 SQLite 连接。

5. **导入来源溯源补齐**
   - 正式导入框保留：`import_batch_id`、`source_format`、`source_class_id`、`source_label_name`、`canonical_label_id`、`canonical_project_class_id`、`mapping_method=manual`、`confirmed_at`。
   - `source_class_id` 只表示外部数据集来源类别，绝不当训练 class_id。
   - 训练导出仍根据本次有效 canonical schema 重新生成连续 `0..N-1`。

6. **Training Label Schema Preflight**
   - 所选正式素材存在未映射、已删除、已停用标签时直接拒绝训练。
   - `class_0 / cls0 / unknown / unmapped / temp_*` 等临时/未知标签即使误入标签库也禁止正式训练。
   - 训练前标签读取按 500 条批量读取 AnnotationRepository，不再逐图片开 SQLite 连接。
   - 上一版本中已删除/停用标签会从本次 schema 剔除并重新连续编号。
   - 合同明确记录 `label_schema_changed`、原因、retained/dropped inherited labels、`base_training_mode`。
   - 当前训练架构是“上一版本权重初始化”，不是 optimizer/trainer state strict resume；合同固定 `strict_resume=false`、`optimizer_state_resumed=false`。

### 本轮关键提交

- `7c356f2dab057eec432e130c3dbeae1039915de1` — require manual import label mapping
- `1aa2f995a068fbc918ceb2f61faf64008d2bf810` — durable whole-label unification
- `fbca33498a1eba1064dcbec6f0fa8f4eaf2ad587` — label-unification progress UI
- `68dd831969f32612b265d679dc22905d38dc89f4` — import label provenance
- `27a4806ed49caeb23fa389c93b69bbdf4e80311b` — canonical training label preflight
- `029d15fe69e8d594b8598b642a75dcfa0c2e50d1` — retire automatic label suggestion paths
- `60e31539454300f466b90924f4c15a7a3d3bd218` — confirmed-empty scope index correctness

### 大批量性能现状

- 浏览器普通多图上传：已有分块上传与批量 repository commit；不做每图片 DB commit / 上传后再次 SHA256。
- ZIP：已有 multipart + durable background job + 10k contract，关闭页面后**已上传到服务器的数据**继续处理；浏览器尚未上传完的本地文件字节无法在页面关闭后继续，这是浏览器安全模型边界。
- 服务器/对象存储导入：扫描、解析、确认后 indexing 均为 durable Worker 后台任务，HTTP 确认不承担万级正式写入。
- 标签统一：按 SQLite 标签索引冻结范围，Worker 分批修改；页面显示真实 loading/progress，可后台运行。
- 训练标签 preflight：AnnotationRepository 每批最多 500 条读取，避免 N 次连接。
- 不得把“代码支持 10k”写成“真实 20k/生产环境已验收”；真实 20k、OSS/S3、NVIDIA/A800 仍需实机验收。

### 仍需继续收口（不要重复造 runtime）

- 导入确认页的**外部标签审查 UI**仍需进一步规模化：标签搜索、分页/虚拟列表、批量将多个外部标签映射到一个 canonical、提交前映射汇总。
- 代表样本查看器仍缺：每个外部标签建议只加载 6–12 个真实 bbox crop / 原图，lazy-load；它是证据查看器，不是推荐器。
- Canonical 标签“删除”仍是结构性高风险操作，旧删除路径还会检查/重排 class_id；后续应单独做 soft-disable 或 durable schema mutation，不能和普通 label edit 混在一个同步 HTTP 路径里。
- CI 最新 HEAD 尚未跑完。任何 completed failure 必须看真实 log 后再修；queued/in_progress 不算通过。

## 历史状态（以下为早期记录，仅保留审计，不代表当前分支）


- 工作分支：`feat/windows-p0`
- 稳定主分支：`main`
- Codex WIP 接管起点：`f42313f`
- 当前版本：`42.24.0`
- 当前阶段：**功能代码与发布元数据已收口；本轮仅做 Windows 工作树差异核对，等待真实环境验收**
- 合并要求：在 Windows 前端、后端回归、Playwright、真实对象存储验证完成前，不合并 `main`。

## 不得回退的产品约束

1. 训练素材是一个统一素材池，不恢复“训练数据集分组”作为训练合同。
2. 训练任务按精确素材 ID 工作，保留 `train_image_ids` / `test_image_ids` 合同。
3. 标签是业务筛选维度；Local/OSS/S3/Remote 只是物理存储位置。
4. 外部试验/评测素材推理时，Ground Truth 只能隐藏用于评分，不能喂给模型。
5. Windows 开发与 NVIDIA Linux 生产都必须支持，禁止写死 Windows 路径或 Windows-only 命令。
6. 已有素材、标注、算法版本不能因升级被清空、移动或重新编号。

## v42.22.x 已完成主体

- Local / 阿里云 OSS / S3-MinIO / Remote Material Server 存储 Provider。
- `StorageManager` 统一解析本地和远程素材。
- Secret 与普通配置分离；前端编辑存储源留空密钥不会清掉原密钥。
- OSS 配置 Prefix 后的分页 marker 已修复。
- 外部已有素材扫描只建索引，不把整个源复制到本地。
- `MaterialRepository` 使用 SQLite + WAL，支持来源、状态、标签 OR、游标分页。
- 老 `images.json` 可迁移，素材 ID 保持不变。
- 外部历史素材即使 `stored_name=""`，读取时也生成稳定 `<image_id>.<ext>` 工作文件名；`object_key` 不变。
- SHA256 内容缓存与 Training Worker 的远程素材 materialize 已接入。
- 外部素材默认删除索引，不默认删源文件；批量删除源文件要求 `delete_source=true` + `confirmation=DELETE_SOURCE`。

## v42.22.3：主素材页性能收口

新增：
- `static/material-pagination-bootstrap.js`
- `static/modules/material-pagination-runtime.js`
- `tests/frontend/material-pagination-runtime.test.mjs`

实现：
- 普通页面/素材页面不再刷新即把全部素材塞进浏览器。
- 数据集页默认 48 张一页，使用 `/api/v61/projects/{id}/materials` cursor pagination。
- 搜索、来源、处理状态、标签 OR、已标注/未标注改为服务端筛选。
- “清洗当前素材 / 当前素材无需清洗”通过 `/materials/ids` 分页只读取 ID。
- 分页模式的摘要用服务端 total；总标注框没有 aggregate API 时明确显示“当前页标注框”。
- 为保证正确性，训练、自动标注/清洗、质量中心、测试发布、部署测试、自动迭代暂时仍进入 full material mode，避免这些旧流程只看到第一页。

## v42.22.3：`mutate()` 写放大止血

`MaterialRepository.mutate()` 已从：

- 读取全表
- DELETE 全表
- 全量重写

改成：

- callback 仍读取全表以兼容旧调用；
- 只写真正变化/新增的 rows；
- 只删除真正删除的 IDs；
- 无变化不 bump revision。

这显著降低 WAL 写放大，但 legacy callback 仍可能全表读取，不能宣称所有百万行热路径已经完成 set-based 改造。

## v42.22.4：超大 ID 与扫描进度收口

新增：
- `platform_core/material_repository_batch.py`
- `tests/unit/test_material_repository_batch.py`
- `static/modules/storage-import-progress.js`
- `tests/frontend/storage-import-progress.test.mjs`

### 大 ID 防护

`MaterialRepository` 的大批量 ID 操作安装 500 ID/批保护：

- `get_many()`：分块 SELECT；
- `remove()`：单事务、分块 SELECT/DELETE；
- legacy `mutate()`：大量删除时分块 DELETE。

目的：避免 1 万 / 10 万 ID 选择时生成超大 `IN (?, ?, ...)` 并撞 SQLite variable limit。

新增测试覆盖：
- 2200 ID `get_many`；
- 1800 ID `remove`；
- 1300 条 legacy mutate 删除。

### 对象存储扫描进度

扫描对象总数未知时，不再显示不可证明的 0% / 37% 等百分比。

运行中展示 Worker 真实返回内容，例如：

`SCANNING · 已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg`

- QUEUED：显示“已进入扫描队列”；
- FINALIZING：显示“正在整理扫描结果”；
- 关闭弹窗只停止浏览器轮询，不停止 durable worker task；
- 成功后同时展示 scanned/importable/duplicates/failed。

## v42.23.0：持久素材导入与本机资源发现

### Durable server-local import

- 每个 `MATERIAL_IMPORT` 任务使用独立 SQLite candidate manifest，扫描结果 JSON 只保留汇总和 manifest 引用；兼容读取旧版小型 candidates JSON。
- `TaskRepository.resume_after_confirmation()` 原子执行 `AWAITING_CONFIRMATION → QUEUED`，清理旧 lease/worker 信息并以 `indexing_queued` 重新交给 Worker；重复确认保持幂等。
- Local 目录使用流式扫描，不再为每页重复 `list(rglob()) + sorted()`；候选依靠 UNIQUE/INSERT OR IGNORE 支持 Worker 恢复与安全重跑。
- 重复判断同时覆盖 `storage_source_id + object_key` 与 `content_sha256`，批量查询已有哈希，避免逐对象 N+1。
- indexing 由 Worker 分批读取 manifest、分批写 `MaterialRepository`、保存候选状态；HTTP 确认请求不再同步写入大批量素材。
- 服务器 ZIP 使用允许导入根目录内的相对路径，先校验 member、数量、单文件/总大小、压缩比、路径逃逸、符号链接和磁盘空间，再解压到 `.import-staging/<task_id>`；默认不覆盖非空目标目录。
- 前端提供存储浏览、Local 目录和服务器 ZIP 三种导入入口，显示真实计数和当前对象；关闭弹窗只终止浏览器轮询，不取消后台任务。

### NVIDIA launcher 保护

- Linux 启动策略在现有 `torch.cuda.is_available() == True` 时复用当前 CUDA PyTorch，不进入 Windows CPU Torch bootstrap。
- 此结论有策略/回归代码证据，但本轮没有连接 Linux/NVIDIA 主机，因此不能记为真机通过。

### Ultralytics 环境发现与全机模型扫描

- 环境探测只验证候选 Python 中的 Python/Ultralytics/Torch/TorchVision/CUDA/GPU，不依赖任何具体 `.pt` 文件。
- 快速候选覆盖当前解释器、PATH、Conda、venv/.venv、AppData、Program Files、已保存环境；每个候选均通过子进程真实 import 探测，多环境完整返回并优先推荐可用 CUDA 环境。
- 全机发现使用 durable `RESOURCE_DISCOVERY` task，Windows 动态枚举本地磁盘，Linux 枚举合理本地挂载点；跳过虚拟/网络文件系统并记录权限失败和真实扫描计数。
- 环境与模型结果使用持久发现缓存；GET 只读取缓存，不会因刷新页面重新触发全机扫描。模型扫描支持指定目录与全机后台模式、稳定分页和显式重新检测。
- `ModelResolver` 按环境目录、Ultralytics `weights_dir`、扫描缓存、项目模型目录、平台缓存、当前目录解析；官方 YOLO 名称找不到时返回 missing/downloadable，不把环境标为 failed。
- 前端已接入一键检测、深度检测、全机模型扫描、真实进度和显式环境选择；未自动选择第一条环境。

## v42.24.0：标注导入、持久批处理与 GPU 资源合同

- YOLO 导入支持 `import_format=yolo`、相对 `dataset_yaml`、`names` 类别解析和确认阶段 `label_mapping/create_labels/accept_quality_report`；正式标注写入 `annotated`，合法空标签写入 `confirmed_empty`，确认时冻结选择并在索引阶段复核内容哈希。
- `/api/v62/projects/{project_id}/material-batches` 提供估算、创建、状态、取消、失败重试、日志和清洗结果分页。删除索引、删除源文件、无需清洗、`CLEAN` 与 `AI_ANNOTATE` 共用不可变 SQLite 选择 manifest；`CLEAN` 只扫描并待复核，AI Worker 持久化候选后进入现有审核接口。
- 存储源重扫描接口为 `/api/v61/projects/{project_id}/storage-sources/{source_id}/rescans` 与对应 status/confirm/cancel；先持久化 `NEW/MISSING/CHANGED/UNCHANGED` 清单，再按确认策略更新索引，仍不全量复制外部素材。
- 训练工作包只含独立复制文件并拒绝链接/reparse point。任务、分配记录、Worker argv、job/result 贯穿 `requested_device / assigned_device / actual_device`；GPU Resource Manager 负责可见设备校验、显存 reservation、admission 和租约 fencing，自动策略记录最终 batch/workers/cache、原因、GPU/CPU/IO 样本、epoch 时长与吞吐。
- 默认 Worker 对同一数据目录、主机、角色和 slot 实施单实例保护；有意并行必须显式命名 `--worker-slot`/`--training-slot`。启动 bootstrap 改为计数和当前页的有界读取，不再在刷新时加载完整素材池或阻塞等待资源全盘扫描。
- 兼容边界：既有 v61 素材/存储导入 API、精确图片 ID 训练合同和旧任务读取保持不变；本轮没有改写历史 API 版本号，也不把 Paddle 或远程训练描述为已纳入本机 Ultralytics Worker。

## 当前未验证 / 不得误报完成

v42.24.0 本轮未执行实际启动、浏览器 E2E 或自动化测试，只做 Windows 工作树发布差异核对。以下均为 **NOT VERIFIED**：真实 20k 数据集重跑、真实付费 AI、真实 OSS/S3/Remote 标注导入、A800 多 GPU 调度/共享/资源参数/吞吐。不得宣称百万规模端到端已验证；历史 Windows 测试证据也不能替代这些真实环境验收。

### 1. v42.23.0 最终回归与最新 UI 浏览器 E2E

用户明确要求本轮代码完成后不再运行测试、直接提交，因此没有执行 v42.23.0 最终全量 pytest、前端 Node 或 Playwright 回归。以下流程仍需最小人工验收：
- 素材页刷新不再全量加载；
- 未处理/已处理、搜索、标签 OR、来源、标注状态筛选；
- 上一页/下一页；
- 当前筛选批量清洗/无需清洗；
- 上传和标注保存后的当前页刷新；
- 从数据页进入训练后完整素材池恢复；
- 训练全选/反选和 exact image ID 不受分页影响；
- 自动标注、质量、测试发布、部署测试不只看到第一页；
- 对象存储扫描期间不再出现假百分比。
- 一键检测不因缺少 `yolo11n.pt` 失败；多环境展示、显式选择和缓存刷新行为正确。
- 全机资源扫描任务关闭弹窗后仍继续，返回后可恢复进度与分页结果。

### 2. 高频 legacy `mutate()` 仍有全表读取

目前已经消除“全表重写”和“大 ID SQL 参数”风险，但 `app.py` 中部分旧 callback 仍会读取全表，例如 split、自动划分、清洗确认、AI/导入决策、训练补充素材。

这些应在真实回归稳定后逐个改成 set-based `patch / remove / upsert`。不要在无法完整回归时对巨大 `app.py` 做整文件盲改。

### 3. 专用工作流仍有 full material mode

训练/自动标注/质量/测试发布/部署测试/自动迭代目前优先保证正确性，仍会加载完整素材池。

后续如确实需要百万规模，应把这些选择器继续改成服务端分页 + `/materials/ids`，而不是牺牲 exact image ID 正确性。

### 4. 真实 MinIO / OSS 未验证

仓库有真实 MinIO 验收代码，但环境变量未配置时会 SKIP。测试存在不等于真实验证通过。

必须实测上传、预览、cache miss/hit、混合训练、索引删除、显式源删除。

### 5. NVIDIA Linux 尚未验收

- Headless Linux Keyring/SecretStore 需要实测保存、重启、读取和脱敏。
- 启动器策略测试证明 Linux 分支不会调用 `_run_install`，也不会访问 CPU PyTorch index；这只是 mock/subprocess-policy 证据，不是 NVIDIA 机器启动验收。
- 真实 NVIDIA CUDA 启动：未验证

### 6. 全机深度扫描未实跑

- Windows 多磁盘和 Linux 多挂载点的代码路径已经实现，但本轮未在真实全机范围执行。
- 权限拒绝、长时间扫描、取消/恢复、超大模型结果分页仍需真实机器操作确认。
- 最新资源发现 UI 没有执行浏览器 E2E，不能记录为已通过。

## NVIDIA Launcher Safety Plan：本轮回归证据

- `python -m py_compile launcher.py`：通过。
- `python -m pytest tests/unit/test_launcher_torch_policy.py tests/unit/test_launcher_workers.py -q --basetemp .pytest-task3-targeted-basetemp -p no:cacheprovider`：`29 passed, 5 warnings in 0.22s`。其中 Linux policy tests 覆盖所有 Linux 路径：`_run_install` 调用数为零，且从不使用 CPU index；该结论仅限策略测试。
- 同一组测试还覆盖 Windows pinned CPU bootstrap 及安装后 probe；均通过。此轮未以脚本入口执行 `launcher.py`，没有调用 pip，也没有改变本机 Torch。
- 第一次以正常 Windows 权限运行 `python -m pytest -q`：`1 failed, 354 passed, 4 skipped, 20 warnings in 179.82s`。唯一失败是 `tests/api/test_storage_upload.py::test_upload_to_selected_storage_source_enters_unified_pool`：清洗任务在 10 秒阈值后仍为 `running`。可复跑诊断命令为 `python -m pytest tests/api/test_storage_upload.py::test_upload_to_selected_storage_source_enters_unified_pool -q`；连续单独执行 3 次均通过，耗时分别为 `0.62s`、`0.56s`、`0.55s`。未复现确定性前序依赖或根因，也没有因此改代码。
- 第二次相同正常 Windows 权限 `python -m pytest -q`：`355 passed, 4 skipped, 20 warnings in 69.09s`（exit 0）。第一次的暂态超时仍是回归观察项，不能表述为“已修复”。
- 受限会话使用默认 Windows Temp 时，pytest 枚举 `%LOCALAPPDATA%\\Temp\\pytest-of-<user>` 报 `PermissionError [WinError 5]`。强制工作树 D: `--basetemp` 后，既有 `test_legacy_dataset_delete_refuses_remote_materials` 以 `Path.replace()` 在 C:/D: 跨卷报 `WinError 17`。两者均为测试环境诊断，不计为产品失败。
- 本轮未连接 Ubuntu 或 A800/NVIDIA 主机；不能把上述单测或 Windows 回归当成真实 Linux/CUDA 启动验证。真实 NVIDIA CUDA 启动：未验证

## 测试状态

Codex 额度耗尽前报告过：`318 passed, 4 skipped`，但那是人工接管前的版本，不能覆盖 42.22.1~42.23.0。

历史 v42.23.0 证据与 v42.24.0 本轮验证范围必须分开：

- v42.24.0：仅发布差异核对；未运行实际启动、自动化测试或浏览器 E2E
- 代码提交到 `feat/windows-p0`：是
- 静态审查：已做
- NVIDIA Launcher 定向测试：`29 passed`（策略测试；非真机 CUDA）
- v42.23.0 最终后端回归：按用户要求未运行
- v42.23.0 前端 Node 回归：按用户要求未运行
- v42.23.0 Playwright / 最新资源发现 UI E2E：按用户要求未运行
- 全量后端回归：第二轮 `355 passed, 4 skipped, 20 warnings`；第一次曾出现一次未复现的清洗任务 10 秒超时，仍待后续观察
- 真实 MinIO：待执行
- 真实 OSS：待执行
- NVIDIA Linux / CUDA 启动：未验证

GitHub 当前没有 CI status，不能把“测试代码已写”表述成“已经通过”。

## 后续最小验收顺序

1. `git checkout feat/windows-p0`
2. `git pull --ff-only origin feat/windows-p0`
3. 确认 `VERSION.txt = 42.24.0`
4. 先跑定向测试：
   - `tests/unit/test_material_repository.py`
   - `tests/unit/test_material_repository_batch.py`
   - `tests/api/test_material_storage_deletion.py`
   - `tests/unit/storage/test_optional_providers.py`
   - `tests/integration/test_storage_import_worker.py`
   - frontend storage/pagination/progress tests
5. 再跑 Playwright 素材库、存储源、训练选择主流程。
6. 通过后再跑全量后端回归。
7. 只修真实失败，不重新设计已稳定模块。
8. 真实 MinIO/OSS环境没有配置时必须报告 `SKIPPED / NOT VERIFIED`。
9. 全部完成后才讨论合并 `main`。


## 2026-09-26 — 批量导入与标签治理闭环（当前分支）

当前基线：`feature/external-algorithm-publishing`。本节只记录已经落到生产代码/永久测试的合同；GitHub Actions 的 queued/in_progress 不记为通过。正式版本仍保持 `VERSION.txt = 42.24.0`，未 merge main、未 tag、未 release。

### 已完成

- **导入标签完全由用户决定**：ZIP、存储源导入/重扫、Remote Agent review 均只返回外部 `class_id/name/image_count/box_count` 等事实；不再用 exact code、中文名、alias、历史映射或 `target_label_code` 自动预选。新建平台标签也必须由用户显式创建，创建后仍需手工选择并确认映射。
- **统一的手工 mapping review**：外部标签按唯一类别展示，支持平台标签搜索、分页/过滤、批量将多个外部标签映射到一个 canonical label、真实样例证据查看；样例只帮助判断，不给推荐结论。
- **已有历史素材可多标签统一**：标签管理支持一次选择多个来源标签（例如 `smoke/smoking/吸烟`）统一到用户手工选择的目标 canonical label；先用索引计算真实去重影响范围，再创建一个 durable `MATERIAL_BATCH / REMAP_ANNOTATION_LABELS`，不在 HTTP 请求内同步遍历几万张素材。
- **Ground Truth 边界完整**：remap 同时处理 bbox label 和 `confirmed_empty.annotation_scope`；并发人工修改使用 digest fencing，失败关闭而不是覆盖新标注。完整成功后来源 canonical label 标记为 `merged`，部分失败时不退役来源标签。
- **标签索引/性能**：`material_labels` 与 `material_annotation_scopes` 支持正样本和负样本范围的 indexed selection/usage；已使用标签改编码/停用不再 `load_images()` 全库扫描。Annotation remap 批处理改为批量读取，避免每图重复开连接。
- **来源审计保留**：正式导入框保留 `import_batch_id/source_task_id/source_format/source_class_id/source_label_name/canonical_label_id/canonical_project_class_id/mapping_method=manual/confirmed_at`。来源 class ID 与 canonical/project/training class ID 明确分离。
- **训练标签 preflight**：训练只接受当前有效 canonical label；dangling/deleted/inactive/unmapped/`class_x`/`unknown`/`temp_*` 会阻断创建。所选 AnnotationRepository 以 500 条批读，避免大选择逐图连接。
- **Schema change 真相**：canonical add/remove/merge 会记录 `label_schema_changed` 和原因；上一版本存在时使用 previous weights init，`strict_resume=false`、`optimizer_state_resumed=false`。仅外部名字手工归一到既有 canonical label 不属于 schema 变化。
- **大 ZIP 正式 UI 链路后台化**：multipart 分片完成后，`/import/uploads/{upload_id}/complete` 立即以 202 返回 durable `merging/validating` 状态；服务器后台继续合并 ZIP、扫描图片/标注/外部类别。刷新/重新进入时 GET/list 会恢复中断的 finalize；前端复用原有 `merging/validating` loading/progress，不新增 UI owner。
- **标签统一刷新恢复**：Material Batch 增加项目级只读 active list（底层复用 `TaskRepository.list` 索引）。标签管理刷新后只恢复 `retire_sources_on_success=true` 的历史 schema-unify 任务，显示轻量进度 banner，并继续复用唯一 `annotation-label-remap` PollRegistry owner；不会把导入审核 remap 串到标签管理。
- **兼容/owner guard**：没有创建第二套 remap scheduler、AnnotationRepository 或 polling runtime；既有 durable Material Batch、TaskRepository、PollRegistry 仍是唯一正式 owner。

### 本轮关闭的性能技术债

1. 已使用标签改编码时同步全库遍历 annotations：**CLOSED**，改为索引判断并要求走 durable 统一。
2. 标签停用/删除检查同步全库扫描：**CLOSED**，改为 normalized label/scope index。
3. confirmed_empty 只有 scope 时历史 remap 不落 Ground Truth：**CLOSED**。
4. annotation remap 每图单独 `get()`：**CLOSED**，改为 bounded `get_many()`。
5. 正式 multipart ZIP 上传完成后 HTTP 同步 merge+scan：**CLOSED**，改为 restart-recoverable background finalize。
6. 标签统一关闭窗口后虽后台继续、刷新却看不到进度：**CLOSED**，改为 durable task discovery + 同一 poll owner 恢复。

### 已知兼容边界 / 仍需验证

- 老的 direct `POST /api/v19/.../import/jobs`（非 multipart）仍是兼容入口：它在上传字节接收完成后同步扫描 ZIP。正式浏览器 runtime 已使用 multipart durable 链，不走该路径；如未来外部 API 客户端也要承载 20k+，应单独迁移/退役此兼容入口，不能再复制一套 worker。
- 当前正式 multipart 后台化新增永久 API 测试，但本节写入时最新 HEAD 的 GitHub Actions 仍有 queued/in_progress；不得写成“全量 CI 已通过”。
- 本轮没有真实跑 20,000 张生产数据、真实 OSS/S3 带标注 20k 导入，也没有 NVIDIA/A800 真机验收。已有 10k acceptance/合同测试不能替代这些真实环境验收。
- 继续只修 completed failure 的真实 job log；queued/in_progress 不视为失败也不视为通过。
