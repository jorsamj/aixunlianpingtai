# Codex / 人工接管交接记录

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
