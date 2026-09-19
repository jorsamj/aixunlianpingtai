# 畅联云算法训练平台 — 当前接手总览

> **新 AI / 新开发人员先读本文件。**  
> 目标：10 分钟内知道“当前在哪个分支、什么已经做完、什么绝对不能重做、下一步该做什么”。

更新时间：2026-09-19  
仓库：`jorsamj/aixunlianpingtai`  
正式版本：`VERSION.txt = 42.24.0`  
当前持续开发分支：`feature/external-algorithm-publishing`  
本轮产品实现基线：`ac1470c9049f7151fb6ae78daf6d21802ea6a263`  

> 本文提交本身可能继续推进分支 HEAD，所以 **不要把上面的实现 SHA 当成 checkout 目标**。接手时必须先读取远端最新 HEAD，从远端真实最新状态继续。

---

# 0. 接手第一分钟必须执行

不要先改代码。先确认真实状态：

```bash
git fetch origin
git switch feature/external-algorithm-publishing
git pull --ff-only
git status
git rev-parse HEAD
git rev-parse origin/feature/external-algorithm-publishing
cat VERSION.txt
```

然后再看：

```text
docs/PROJECT_HANDOFF_CURRENT.md
docs/BUG_AUDIT_2026-09-17.md
docs/CODEX_CURRENT_STATE.md
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/frontend-legacy-audit.md
docs/FRONTEND_OWNER_MAP_V42_25.md
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
docs/NODE_CONTROL_PLANE_V42_25.md
```

### 绝对约束

1. **不 merge `main`**，除非用户明确授权。
2. **不修改正式 `VERSION.txt`**，当前必须保持 `42.24.0`。
3. 不 tag。
4. 不 release。
5. 不为了测试通过删除测试、降低阈值、放宽断言、恢复 legacy owner。
6. Windows 开发 + NVIDIA Linux 生产必须同时兼容。
7. 任何“完成”必须有真实代码 + focused test + permanent guard；关键前端运行链路尽量有 Real Chrome。
8. A800 RC / genuine 10k ZIP 性能验收不要擅自恢复，除非用户重新要求。

当前 `main` 最近一次已验证仍为：

```text
2fe9394ccb10068d81cc2113879ac801c4831017
revert: keep external algorithm integration off main
```

如果接手时 `main` 不再是这个 SHA，先查是谁、为什么改，不要自动把 feature 内容合进去。

---


# 最新关闭：Canonical Annotation Schema v1

2026-09-19，YOLO / COCO / Pascal VOC 已共享的外部标注 evidence 已正式收敛为 **Canonical Annotation Schema v1**，CLOSED。

关键约束与实现：

- 新增 `platform_core/annotation_schema.py`，统一拥有 schema version、source format/status 校验、source object identity、normalized bbox、class catalog digest、稳定 source digest。
- Parser owner 未变化：YOLO / COCO / VOC 仍只负责各自格式发现与解析；Canonical Schema 不重写 parser。
- `ImportCandidateStore.annotation_source_evidence()` 不再自行拼接/计算 schema，而统一调用 canonical builder。
- v1 保持旧 evidence **字段集合与 source_digest 计算语义兼容**；历史已同步 annotation 不会因本次抽象层升级被整体误判为 CHANGED。
- source object identity 仍冻结 key 对应的 size / ETag / SHA256；bbox 继续使用 normalized `cx/cy/w/h`。
- consumer-side fencing 已补齐：
  - 构建 annotation delta 前验证 canonical evidence；
  - apply 到 AnnotationRepository 前再次验证 schema / digest；
  - source_format 与当前 durable rescan request 必须一致；
  - evidence object_key 与 delta object_key 必须一致；
  - 被篡改、损坏或错格式 task artifact fail closed。
- Canonical schema 仍与平台 AnnotationRepository truth 分离；它描述的是外部来源 evidence，不成为第二个 annotation owner。
- Frontend Impact Review：**无需 UI 修改**。公共 task/API 字段、状态枚举、mapping/quality/confirmation 结构均未变化；Real Chrome 回归通过。

最终代码 HEAD：`e262819dd7c4eb7a245e43eefc91bc452a4060fc`。

验收：

- Remote Material Import push：Ubuntu / Windows / API / Real Chrome success。
- Canonical schema builder/validator 在 Ubuntu + Windows contract 中通过。
- source_digest legacy compatibility 对 YOLO / COCO / VOC 均通过。
- Consumer-side tamper / format mismatch fencing 通过。
- Node Agent Executor、Remote Cleaning、Remote Training、Remote Conversion、Central Assignment、Portable Deployment、RKNN Board Runtime 等共享回归全部 success。
- 当前代码 HEAD 共 16 个相关 workflow：16 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：**

1. 复用现有 `platform_core/snapshots.py` / Snapshot V3，扩展 Dataset Snapshot / Revision，而不是新建第二套 snapshot。
2. 下一版 snapshot 要把训练使用的 canonical annotation schema/source truth 与现有 content SHA / annotation_hash / split / label_schema 一起冻结。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。

# 最新关闭：Remote storage_rescan Phase 2C — Pascal VOC Annotation Delta

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` 已完成 **Pascal VOC XML 标注增量同步**，Phase 2C CLOSED。至此 Phase 2 的 YOLO / COCO / Pascal VOC 三种 annotation delta 均进入同一 durable owner、同一 review/confirm/repository truth。

已关闭范围：

- Local 与 Agent 都支持 `import_format=images|yolo|coco|voc`；preflight、API schema、前端下拉、确认策略使用同一后端 truth。
- VOC 继续复用现有 `DetectionDatasetScanner`，没有新增 VOC Parser owner、TaskKind 或 AnnotationRepository。
- Agent 通过 execution-fenced broker + short-lived GET 读取真实 XML/image bytes；不访问中央 SQLite/NFS，不接收长期对象存储凭据。
- portable review 冻结 XML source object identity：object key / size / ETag / SHA256，并保存 split、external class catalog、normalized boxes、quality issues 与 per-image `source_digest`。
- 图片与标注 delta 分开：
  - 图片：`NEW/MISSING/CHANGED/UNCHANGED/INVALID/SKIPPED`
  - 标注：`ANNOTATION_NEW/CHANGED/REMOVED/UNCHANGED/CONFLICT/INVALID`
- XML 删除、XML 内容变化但图片未变、类别/bbox/split 变化都会进入 annotation delta。
- 外部 source evidence 与平台 AnnotationRepository truth 分离；review→confirm 间发生人工修改时 stale-write fencing fail closed，要求重新扫描。
- 新增图片继续由既有 MATERIAL_IMPORT indexer 建正式 Material/Annotation truth；rescan 只补 external provenance。
- VOC ambiguity fail closed：同一图片被多个 Pascal VOC XML 文档引用时拒绝。
- 用户确认复用统一的 label mapping / create_labels / quality acceptance / removal policy / conflict policy，并保持“先冻结 durable intent → 再创建标签 → 再 resume task”。
- Frontend Impact Review 同批完成：
  - “重新扫描 / 恢复”新增“图片 + Pascal VOC 标注”；
  - YOLO data.yaml 仍只在 YOLO 模式启用；
  - VOC 图片增量、标注增量、quality、label mapping、删除/冲突策略全部来自真实后端 task；
  - Real Chrome 覆盖 Agent VOC request → review truth → mapping → confirmation body。

最终代码 HEAD：`5a1c18c8fc18c783a95d55f4f6a3ad826ffef69a`。

最终验收：

- Remote Material Import push `35412658236`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35412660855`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor push `35412658140` / PR `35412660966`：success。
- Central Node Assignment push `35412658117` / PR `35412660834`：success。
- Task Runtime Truth `35412660757`：success。
- Remote Training Runtime push `35412658157` / PR `35412660756`：success。
- Remote Conversion Runtime push `35412658182` / PR `35412660808`：success。
- Remote Cleaning Runtime push `35412658119` / PR `35412660762`：success。
- Portable Deployment push `35412658228` / PR `35412660767`：success。
- Remote RKNN Board Runtime Protocol push `35412658162` / PR `35412660872`：success。
- Storage Cache Governance `35412660802`：success。
- 当前代码 HEAD 共 28 个相关 workflow：28 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：**

1. Canonical Annotation Schema v1：把当前 YOLO/COCO/VOC 已共享 evidence 正式版本化成平台 contract，不重写 Parser。
2. Dataset Snapshot / Revision：冻结素材、标注版本、split 和对象 SHA，保证训练可复现。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。
4. TensorRT / Sophon / Ascend 继续暂缓。

# 最新关闭：Remote storage_rescan Phase 2B — COCO Annotation Delta

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` 在 Phase 2A YOLO 基础上完成 **COCO annotation JSON 增量同步**，Phase 2B CLOSED。没有新增 TaskKind、COCO Parser owner、AnnotationRepository 或第二套 rescan。

已关闭范围：

- 同一个“重新扫描 / 恢复”入口现在使用一套真实格式 truth：
  - 仅图片；
  - 图片 + YOLO 标注；
  - 图片 + COCO 标注；
  - 执行位置仍为中央 Worker / 远程 Agent。
- API `StorageRescanCreateReq`、Agent preflight、durable request、前端格式选项和 worker 能力声明统一支持 `images|yolo|coco`；`dataset_yaml` 仍严格只属于 YOLO。
- COCO 复用既有 `DetectionDatasetScanner`，不新写 parser。Local 与 Agent 都把证据落进同一个 task-owned `ImportCandidateStore`。
- Agent 继续只通过 execution-fenced broker / short-lived GET 读取 OSS/S3/MinIO；不访问中央 SQLite/NFS，也不接收长期对象存储凭据。
- COCO annotation source 会读取真实 JSON bytes，并冻结：
  - annotation JSON object key；
  - size / ETag / SHA256；
  - split；
  - external category id/name catalog；
  - normalized bbox / annotation status / issues；
  - per-image external `source_digest`。
- rescan 会保留**完整源图片 inventory**，包括没有被 COCO JSON 引用的图片，因此不会因为 annotation JSON 未引用某张图片就误判该图片 MISSING。
- 图片对象继续统一分类 `NEW/MISSING/CHANGED/UNCHANGED/INVALID/SKIPPED`；COCO 标注继续复用 Phase 2A 的 `ANNOTATION_NEW/CHANGED/REMOVED/UNCHANGED/CONFLICT/INVALID`。
- 平台人工 AnnotationRepository truth 与外部 COCO source evidence 分离：
  - JSON 变化不会直接覆盖人工标注；
  - JSON 删除某图标注进入 REMOVED/CONFLICT，由用户策略决定 clear/keep；
  - review 后平台标注又发生人工修改时，stale-write fencing fail closed，要求重新扫描。
- 新增图片仍只由既有 MATERIAL_IMPORT indexer 建正式 Material/Annotation truth；rescan 后续只补 `external_annotation` provenance / synced hash，不重复写第二套正式标注。
- COCO source ambiguity 永久 fail closed：
  - 同一 category id 映射不同名称 → 拒绝；
  - 同一图片跨多个 split → 拒绝；
  - 同一图片被多个 COCO annotation document 引用 → 拒绝；
  - 同一 COCO metadata 内重复引用同一 object key → 拒绝。
- COCO rescan 使用 `deduplicate_images=False`，保持 object-key identity；不同 key 即使内容 hash 相同，也不会因为普通素材去重语义被吞掉。
- 用户确认继续复用同一套 label mapping / create_labels / quality acceptance / removal policy / conflict policy，并保持“先冻结 durable intent → 再创建标签 → 再 resume task”的顺序。
- Frontend Impact Review 同批完成：
  - 前端新增“图片 + COCO 标注”；
  - YOLO data.yaml 输入只在 YOLO 模式启用；
  - 图片增量、标注增量、quality、external class mapping、删除/冲突策略都来自真实后端 task；
  - Real Chrome 覆盖 Agent COCO request → review truth → mapping → confirmation body。

最终代码 HEAD：`ac1470c9049f7151fb6ae78daf6d21802ea6a263`。

最终验收：

- Remote Material Import push `35411646993`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35411650317`：success。
- Node Agent Executor `35411650294`：success。
- Central Node Assignment `35411650355`：success。
- Task Runtime Truth `35411650324`：success。
- Remote Training Runtime `35411650292`：success。
- Remote Conversion Runtime `35411650281`：success。
- Remote Cleaning Runtime `35411650314`：API / Ubuntu / Windows / Real Chrome success。
- Portable Deployment `35411650458`：success。
- Remote RKNN Board Runtime Protocol `35411650309`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35411650330`：success。
- Training Input Integrity `35411650297`：success。
- 当前代码 HEAD 共 16 个相关 workflow：16 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**仍然 OPEN：**

1. `storage_rescan Phase 2C`：Pascal VOC XML annotation delta。
2. Canonical Annotation Schema versioning：正式版本化当前 YOLO/COCO/VOC 已共享的 evidence schema，不重写既有 Parser。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance。
4. TensorRT / Sophon / Ascend 继续暂缓。

# 最新关闭：Remote storage_rescan Phase 2A — YOLO Annotation Delta

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` 在 Phase 1 图片对象增量基础上完成 **YOLO 标注增量同步**，Phase 2A CLOSED。没有新增 TaskKind、Parser owner 或第二套 AnnotationRepository。

已关闭范围：

- 同一个“重新扫描 / 恢复”入口支持：
  - 扫描内容：仅图片 / 图片 + YOLO 标注；
  - 执行位置：中央 Worker / 远程 Agent；
  - YOLO 可显式选择 `data.yaml`，也可按现有规则自动发现。
- Local 与 Agent 使用同一请求 truth：`execution_mode + import_format + dataset_yaml`；Agent preflight 只暴露后端真实支持格式。
- Agent 继续复用现有 broker / short-lived GET / execution lease / generation fencing / server-confirm；不访问中央 SQLite/NFS，不接收长期对象存储凭据。
- YOLO review 不只保存归一化 bbox，还冻结外部来源身份：
  - label `.txt` object key / size / ETag / SHA256；
  - `data.yaml` object key / size / ETag / SHA256；
  - split；
  - external class catalog digest；
  - normalized boxes / quality issues；
  - per-image `source_digest`。
- 因此可识别“图片没变，但 label sidecar / data.yaml / split / class / bbox 变化”的真实 annotation delta。
- 统一分类：
  - `ANNOTATION_NEW`
  - `ANNOTATION_CHANGED`
  - `ANNOTATION_REMOVED`
  - `ANNOTATION_UNCHANGED`
  - `ANNOTATION_CONFLICT`
  - `ANNOTATION_INVALID`
- 平台人工标注 truth 与外部 YOLO source evidence 分离；历史素材没有可信 external baseline 时不会假装“已同步”，而按冲突/新增规则进入用户确认。
- 用户确认策略与后端完全一致：
  - 已有图片：是否同步新增/变化标注；
  - 外部标注删除：清空 / 保留；
  - 人工修改冲突：覆盖 / 保留；
  - external class → 平台标签 mapping/create_labels；
  - quality report acceptance。
- 新增图片仍走既有 MATERIAL_IMPORT indexing owner，并按冻结映射导入对应 YOLO 标注；UI 已明确写明这一语义。
- 新增图片完成 indexing 后会补正式 `external_annotation` provenance 和 `synced_annotation_hash`，不会被误标为“待复核”。
- 已有图片写入前增加 stale-annotation fencing：review 后如果平台标注又被人工修改，确认阶段 fail closed，要求重新扫描，不能覆盖用户的新修改。
- 新平台标签创建顺序已修正为：**先冻结 durable rescan intent → 再幂等创建标签 → 再 resume task**，避免确认冲突失败却提前产生标签副作用。
- Frontend Impact Review 同批完成：
  - 图片增量与标注增量分别展示；
  - 标注映射、质量、删除策略、冲突策略全部来自后端 task truth；
  - 修复 YOLO review 渲染的 `key is not defined`；
  - Phase 1 文案与 Phase 2A 正式 UI 文案统一；
  - Real Chrome 覆盖 Agent YOLO 请求、review 计数、mapping、冲突策略和确认 body。

最终代码 HEAD：`6505c51e1916a8aab5d506387b51d01e413b7775`。

最终验收：

- Remote Material Import push `35410155924`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35410158432`：API / Ubuntu / Windows / Real Chrome success。
- 父层 UI/确认顺序回归：
  - `9e8ada…` push Remote Material Import `35409879583` 全绿。
  - `c6ee2ab…` push/PR Remote Material Import 全绿。
- `VERSION.txt = 42.24.0` 未修改。

**仍然 OPEN：**

1. `storage_rescan Phase 2B`：COCO annotation JSON delta。
2. `storage_rescan Phase 2C`：Pascal VOC XML delta。
3. Canonical Annotation Schema versioning：把当前 YOLO/COCO/VOC 已共享的 evidence 正式版本化，不重写 Parser。
4. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance。

# 最新关闭：Remote MATERIAL_IMPORT Phase 2

2026-09-18，第四个真实跨机器 task kind 的第二阶段已 CLOSED。

已完成范围：

```text
MATERIAL_IMPORT
server_zip + execution_mode=agent
import_format=images | yolo
```

Phase 2 新增真实能力：

- Agent 复用 `YoloImportScanner` 解析 `data.yaml / images / labels`。
- review ZIP 新增 `yolo/annotations.jsonl`，包含 split、label sidecar、annotation status、normalized boxes、issues。
- 控制面在进入待确认前重新校验 classes / dataset_yaml / boxes / normalized 坐标 / candidate 覆盖完整性。
- task-owned ImportCandidateStore 保存 external classes 和 annotation evidence。
- 用户确认时冻结 `label_mapping/create_labels/quality acceptance`。
- local indexer 发布选中图片后，将 YOLO normalized boxes 转为像素坐标并写 AnnotationRepository。
- `confirmed_empty` 作为正式负样本写入；invalid/missing sidecar 不会擦除已有标注。
- Agent YOLO API 已作为支持能力，不再被旧测试当成 unimplemented。
- 永久 CI 增加源码 guard 和 Agent YOLO→label mapping→AnnotationRepository 端到端 integration。

最终验收：

- Remote Material Import `35311171823`：API / Ubuntu / Windows 全绿。
- 临时 draft PR #17 已关闭，未 merge。
- `VERSION.txt = 42.24.0` 未修改。

Phase 1 的 `import_format=images` 闭环和其验收 `35308672897` 继续有效，不重做。

# 最新关闭：Remote MATERIAL_IMPORT Phase 3 — staging object lifecycle / GC

2026-09-18 已完成 remote input/review staging object 治理：

- server-confirm 后写 durable cleanup ledger，等外层 result state durable 后再删除。
- AWAITING_CONFIRMATION 的 staging 对象由 storage Worker heartbeat hook 精确回收。
- FAILED/CANCELLED/BLOCKED 默认保留 7 天后再 GC。
- orphan generation 从 `remote-results/N/upload.json` 恢复 exact object ref。
- 删除前重新验证 task-owned prefix + storage source + size + SHA256。
- mismatch = CONFLICT，不删除；provider 故障 = PENDING，可重试。
- 不做 prefix list/delete；不触碰正式 MaterialRepository 目标对象。
- GC 使用现有 WorkerInstance renew hook，5 分钟节流、分页 cursor，无第二套 timer/scheduler。

验收：

- Remote Material Import `35312109805`：API / Ubuntu / Windows 全绿。
- Task Runtime Truth `35312109707`：Ubuntu / Windows 全绿。
- Storage Cache Governance `35312109834`：全绿。
- `VERSION.txt=42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_IMPORT Phase 4 — Agent storage_scan

2026-09-18，`MATERIAL_IMPORT + mode=storage_scan + execution_mode=agent` 已完成真实跨机器闭环并 CLOSED。

当前真实能力：

- 前端“对象存储目录”只展示已启用 OSS / S3 / MinIO 存储源，真实提交 `storage_scan + execution_mode=agent + prefix + recursive + import_format/dataset_yaml`。
- 前端、专用任务 API、统一 PollRegistry 共享同一 task status / phase / execution_mode truth；刷新恢复仍保留 Agent 身份。
- canonical task status 优先于 stale stage；`AWAITING_CONFIRMATION` 不再错误显示“正在检查素材内容”。
- 控制面继续持有长期对象存储凭据；Agent **不接收 accessKey/accessSecret，也不访问中央 SQLite/NFS**。
- Agent 通过 execution lease fenced broker 分页获取 prefix 对象列表，并按需获取短期 GET contract。
- broker 和 Agent 双重约束 durable prefix；prefix 外对象、重复 cursor、超过 250000 个对象均 fail closed。
- Agent 每次读取对象都会重新校验 Content-Length / ETag，并在可用时校验 SHA256；YOLO 继续复用 `YoloImportScanner`。
- storage_scan review ZIP 为 metadata / annotation evidence only，不重新打包原始图片，避免大规模素材被“下载后再整包上传”。
- server-confirm 后控制面重新校验 review truth；用户确认后 local indexer 对原对象再次 `exists/stat`，校验 size / ETag / SHA256 后直接建立 MaterialRepository / AnnotationRepository truth，不复制原对象。
- Phase 3 GC 仍只删除 task-owned staging input/review exact refs，不会触碰 storage_scan 的正式源素材对象。
- classic `static/app.js` 新增永久 `node --check`；本轮发现并修复两条 dangling `=async function` 生产语法错误。
- Remote Material Import 专项已覆盖 API、Ubuntu、Windows、前端 Node contract 与 Real Chrome 真实页面流。

最终验收（代码 HEAD `639cded30a6a2fed67275f19450cb70b4e0a9128`）：

- Remote Material Import `35316129031`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35316128986`：全绿。
- Central Node Assignment `35316128928`：全绿。
- Portable Deployment `35316129051`：全绿。
- Remote Training Runtime `35316128920`：全绿。
- Remote Conversion Runtime `35316129033`：全绿。
- Task Runtime Truth `35316128916`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_IMPORT Phase 6 — COCO / Pascal VOC Agent server_zip

2026-09-18，COCO / Pascal VOC 的 **Agent server_zip** portable import 已完成真实闭环并 CLOSED。Phase 5 的 storage_scan annotation truth 继续复用，本批没有创建第二套 COCO/VOC 导入链。

真实闭环：

- `server_zip + execution_mode=agent + import_format=coco|voc` 与 images / YOLO 共用同一个 `MATERIAL_IMPORT` durable task、assignment / execution lease 和 object-storage-v1 transport。
- 控制面只接受安全相对 ZIP 路径；Agent ZIP 目标必须是已启用 OSS / S3 / MinIO，不允许把中央本地目录/NFS 当成远程共享盘。
- 中央端把原 ZIP 以 size/SHA256 证据暂存为 task-owned input object；Agent 只拿短期 GET，不获得长期对象存储凭据。
- Agent 继续使用既有安全 ZIP extraction，随后复用 `DetectionDatasetScanner` 解析 COCO / Pascal VOC。
- detection ZIP review 与 storage_scan 使用同一 candidate / normalized box / split / issue / external-class schema；ZIP 模式仅额外把用户确认后需要入库的 IMPORTABLE 图片作为 `files/...` payload 嵌入 task-owned review。
- review 上传继续走 generation-scoped immutable PUT；server-confirm 重新核对 review ZIP、候选图片 size/SHA256/尺寸、embedded payload、annotation coverage、class/box/issue 约束。
- 用户仍必须确认外部类别 → 平台标签映射；确认后 local Storage Worker 把已验证 payload 写入正式对象存储，并写现有 MaterialRepository / AnnotationRepository truth。
- `dataset_yaml` 仍只属于 YOLO；COCO/VOC ZIP 提交 dataset_yaml 会 fail closed。
- 产品“服务器 ZIP”新增执行位置：**中央 Worker / 远程 Agent**。中央 Worker 保持旧本地导入行为且不开放 COCO/VOC；切到远程 Agent 后目标存储改为 OSS/S3/MinIO，并开放 COCO/VOC。
- Agent ZIP 不允许 `import_format=auto`，用户必须明确选择 images / YOLO / COCO / VOC。
- Real Chrome 已覆盖：服务器 ZIP 默认中央 Worker → COCO 禁用 → 切换远程 Agent → 对象存储目标 → 选择 COCO → 提交真实 `execution_mode=agent` request → 等待确认。

最终验收（代码 HEAD `3f5c34ae587aee04971e8e5160073898f288cba4`）：

- Remote Material Import `35357183468`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35357183397`：全绿。
- Central Node Assignment `35357183504`：全绿。
- Task Runtime Truth `35357183682`：全绿。
- Portable Deployment `35357183477`：全绿。
- Remote Training Runtime `35357183476`：全绿。
- Remote Conversion Runtime `35357183564`：全绿。
- Remote Cleaning Runtime `35357183532`：全绿。
- Remote RKNN Board Runtime Protocol `35357183788`：API / Ubuntu / Windows / Real Chrome 全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_IMPORT Phase 5 — COCO / Pascal VOC

2026-09-18，COCO / Pascal VOC 已接入真实远程 `MATERIAL_IMPORT + storage_scan + Agent` 闭环并 CLOSED。

Phase 5 当时 CLOSED 的范围为 **对象存储目录的 Agent storage_scan**；Agent server_zip 已在上方 Phase 6 正式 CLOSED。

真实闭环：

- 新增项目数据库无关的 bounded `DetectionDatasetScanner`，只读取 brokered StorageProvider，写 task-owned ImportCandidateStore evidence，不在 Agent 侧创建平台标签、Material 或 Annotation。
- COCO 支持 categories / images / annotations、多 annotation JSON 与 train/val/test split 识别；外部 category id 原样保留到确认阶段。
- Pascal VOC 支持 XML object/bndbox、split 识别与稳定外部 class id；含 DOCTYPE / ENTITY 的 XML fail closed。
- 格式层使用真实图片尺寸归一化检测框；越界框可裁剪并记录 warning，无效框进入质量问题，不直接污染正式标注。
- 永久边界包含：最多 250000 个对象、5000000 个标注框、COCO JSON 单文件 64 MiB、VOC XML 单文件 2 MiB。
- Agent review ZIP 仍是 metadata / annotation evidence only，不重新打包对象存储中的原始图片。
- 控制面 server-confirm 后重新验证 candidate / class / box / split / issue evidence，生成 external class mapping suggestions。
- 用户必须确认外部类别 → 平台标签映射；确认后 local Storage Worker 再次 stat 原对象并验证 size / ETag / SHA256，再写正式 MaterialRepository / AnnotationRepository。
- 正式索引阶段沿用统一 annotation truth：normalized evidence 转回实际像素坐标；COCO/VOC 不走旧 `ensure_label + add_image_record` 直写逻辑。
- 前端“对象存储目录”已正式开放 **COCO 检测标注 / Pascal VOC 检测标注**；Phase 6 又开放了远程 Agent 的服务器 ZIP。中央 Worker 本地目录/本地 ZIP仍不开放 COCO/VOC；dataset YAML 仍只属于 YOLO。
- Real Chrome 已验证页面真实选择 COCO 并提交 `storage_scan + execution_mode=agent + import_format=coco`。

最终验收（代码 HEAD `9fb67096718e5ece1b72a2acf601662fe337e1d7`）：

- Remote Material Import `35318574008`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35318574014`：全绿。
- Central Node Assignment `35318574002`：全绿。
- Task Runtime Truth `35318573876`：全绿。
- Portable Deployment `35318573871`：全绿。
- Remote Training Runtime `35318573869`：全绿。
- Remote Conversion Runtime `35318573929`：全绿。
- Storage Cache Governance `35318573935`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_BATCH/CLEAN Phase 1 — Agent 清洗 / 去重

2026-09-18，远程清洗已按现有唯一 owner `TaskKind.MATERIAL_BATCH + operation=CLEAN` 完成真实 Agent 闭环并 CLOSED；**没有新增或恢复并行 `TaskKind.CLEANING` handler**。

真实闭环：

- 本地清洗默认行为保持不变；只有用户显式选择 `execution_mode=agent` 才进入远程节点链路。
- 后端 preflight 以真实 selection 校验素材与节点，不让前端自行猜测：所选素材必须有 `object_key + size + SHA256`，存储源必须是已启用 OSS / S3 / MinIO，且至少存在 online + agent + effective `cleaning` capability 节点。
- preflight 不可用时，Agent 选项在 UI 中禁用；绕过 UI 直接请求 Agent 也会 fail closed，并保证不会残留 durable task。
- prepare / publish / retry 全部从持久化 request 恢复执行方式；Agent CLEAN 使用 `agent.remote` capability，中央 Materials Worker 无法静默抢走远程任务。
- 控制面通过 execution-lease-fenced broker 分页暴露**冻结 selection 中的精确 material refs**；不是 prefix 扫描，未选中 image_id 无法读取。
- Agent 不读取中央 SQLite/NFS、不拿长期对象存储凭据；逐图取得短期 GET contract，并校验 size / SHA256 后进行本地分析。
- Agent 复用 `CleaningAnalysisRuntime` 做真实图片解码、尺寸、dHash、模糊度、亮度、熵等分析，只产出 task-owned metrics review evidence。
- 重复图 / 近重复图 / 阈值规则仍由控制面使用现有 `metric_issues + DurableHashIndex` 重新评估，Agent 不能自行决定正式删除结果。
- Agent review 经 immutable object upload + size/SHA256 server-confirm 后，控制面才把结果提交回现有 `selection.sqlite3 / clean_results` 与 MaterialRepository clean projection；没有第二套清洗结果库。
- durable `SUCCEEDED` 且尚未用户确认时，v47 兼容投影继续显示“待确认”；用户仍通过原有“建议删除 / 保留 → 确认应用清洗”流程完成最终变更。
- 产品弹窗新增“执行位置”：默认 **中央 Worker**；满足后端 preflight 时才允许选择 **远程清洗节点**。任务列表标识实际执行方式，远程阶段均映射为中文真实进度。
- 永久专项覆盖 Agent runtime、portable transport、assignment、API fail-closed、前端 Node contract 与 Real Chrome 执行位置选择。

最终验收（代码 HEAD `b41f784a3765e09a2184453e03e895a1cda0271d`）：

- Remote Cleaning Runtime `35324894972`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35324894991`：API / Ubuntu / Windows 全绿。
- Central Node Assignment `35324894963`：全绿。
- Task Runtime Truth `35324895005`：全绿。
- Portable Deployment `35324894993`：全绿。
- Remote Material Import `35324894988`：全绿。
- Remote Conversion Runtime `35324894962`：全绿。
- Remote Training Runtime `35324895079`：API / Ubuntu / Windows 全绿。
- `VERSION.txt = 42.24.0` 未修改。

2026-09-18 probe hardening（代码 HEAD `b20470c8f57ee99fcde3ff0da5f26a5be4b7124f`）：

- RKNN-Toolkit2 capability 从“版本阈值推断”收紧为真实 `RKNN.config(target_platform=...)` 探测。
- Remote Conversion Runtime `35344315905`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Remote RKNN Board Runtime Protocol `35344315931`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35344315955`、Central Node Assignment `35344316219`：全绿。
- Task Runtime Truth `35344315903`、Portable Deployment `35344315907`：全绿。
- Remote Training `35344315916`、Remote Material Import `35344315983`、Remote Cleaning `35344315908`：全绿。

# 最新关闭：Remote storage_rescan Phase 1 — 图片对象增量同步

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` owner 已扩展为真实 Remote Agent portable flow，**Phase 1（图片对象增量同步）CLOSED**。没有新增 TaskKind，也没有复制 storage_scan / import owner。

当前 CLOSED 边界：

- 前端“重新扫描 / 恢复”支持 **中央 Worker / 远程 Agent** 执行位置；远程选项只来自后端 preflight 的真实在线 effective `material-import` 节点。
- Agent rescan 使用显式 `intent=storage_rescan`。只有这个 intent 才允许扫描对象存储根范围；普通 `storage_scan` 仍要求显式 prefix，不能借 rescan 放宽目录边界。
- 控制面在 durable task 创建前冻结当前 MaterialRepository 的 source baseline 到 task-owned artifact；Agent 不访问中央 SQLite/NFS。
- 长期 OSS/S3/MinIO 凭据仍只在控制面。Agent 通过 execution-lease-fenced broker 分页列举对象，并按需拿短期 GET contract 做真实图片 decode / size / SHA256 / ETag 核验。
- rescan 是“对象身份核对”而不是素材去重：两个不同 object key 即使内容 SHA256 相同，也必须作为两个独立对象进入增量比较，不能被普通导入 dedup 逻辑吞掉。
- Agent review 经 immutable upload + size/SHA256 + server-confirm 后，中央端把当前清单与冻结 baseline 分类为：
  - `NEW`
  - `MISSING`
  - `CHANGED`
  - `UNCHANGED`
  - 以及 `INVALID / SKIPPED` 质量证据。
- `CHANGED` 同时比较 content SHA256、size 和 ETag；仅 ETag 变化也不会被误报为 UNCHANGED。
- 用户仍必须确认恢复策略：新增建索引、缺失标记 unavailable、变化更新；不会自动删除源对象或素材记录。
- 用户确认后 durable task 释放回现有中央 `storage.rescan` Worker owner 做正式 Repository commit；Agent 不直接写 MaterialRepository / AnnotationRepository。
- 对 Agent review 的二次防变更检查只做对象 `stat` identity（size + ETag + 可用 SHA 元数据），**不会在中央端重新下载整批图片再 decode/hash**；图片重 I/O 留在 Agent。
- 变化素材保留原有标注 truth，并设置需要复核；缺失素材只标记源不可用。
- UI 使用真实 task status / worker / resource_wait_reason / counts，刷新后继续恢复同一 durable task；Real Chrome 已覆盖 Remote Agent preflight → 创建 → review → 待确认链路。

Phase 1 最终代码 HEAD：`64dc87c6e295429f79adfc813093bff33ce61587`。

最终验收：

- Remote Material Import `35408027919`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35408027776`：API / Ubuntu / Windows success。
- Central Node Assignment `35408027804`：success。
- Task Runtime Truth `35408027769`：success。
- Portable Deployment `35408027802`：success。
- Remote Training Runtime `35408027815`：success。
- Remote Conversion Runtime `35408027785`：success。
- Remote Cleaning Runtime `35408027775`：API / Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35408027782`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35408027828`：success。
- `VERSION.txt = 42.24.0` 未修改。

**仍然 OPEN：**

1. `storage_rescan Phase 2`：YOLO `.txt / data.yaml`、COCO annotation JSON、Pascal VOC XML 的新增/删除/替换和增量 AnnotationRepository 更新。
2. Canonical Annotation Schema：把现有 YOLO / COCO / VOC review evidence 正式版本化，而不是重写已有 Parser。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 仍未发生；软件 CI 不能替代现场 NPU 验收。

# 最新关闭：Remote MODEL_CONVERSION Phase 2 — Rockchip RKNN

2026-09-18，远程 Rockchip RKNN 转换已完成真实 Agent 闭环并 CLOSED。

当前 CLOSED 范围：

- 远程目标为 `target=rockchip`，当前 portable Agent 正式支持 **RK3568 / RK3576**。
- 早先 handoff 中的“RK3578”已纠正：Rockchip 官方 RKNN-Toolkit2 当前支持平台列出 RK3576 Series，而不是 RK3578。若现场设备铭牌/采购型号确实写 RK3578，必须先读取真实 SoC compatible / 芯片信息再映射，平台不得直接把 RK3578 当 RK3576。
- 当前远程 RKNN 只关闭 **FP16、batch=1、静态输入**；INT8 calibration transport 尚未关闭，不允许假装支持。

真实闭环：

- 服务节点新增细粒度 `conversion.rknn` capability；通用 `conversion` 继续服务已 CLOSED 的 ONNX，二者不能互相冒充。
- Node Agent 只有在真实 Python 环境可导入 `rknn.api.RKNN`，并且至少一个目标芯片通过真实 `RKNN.config(target_platform=...)` 探测后才上报 `conversion.rknn`。
- heartbeat runtime 持久化 `rknn_toolkit2.available/version/supported_chips`；控制面只把 online + agent + effective `conversion.rknn` + probe 可用的节点作为 Rockchip 资源。
- Toolkit capability 不再按版本号猜测：Node Agent 会在节点本机真实调用 `RKNN.config(target_platform='rk3568'/'rk3576')`，只有实际 config probe 成功的芯片才进入 `supported_chips`；`conversion.rknn` 至少有一个支持目标时才可上报。
- MODEL_CONVERSION 调度按目标细分 capability：Agent ONNX → `conversion`，Agent Rockchip → `conversion.rknn`。
- portable contract 只接受 RK3568 / RK3576、FP16、batch=1、静态 shape，并保留 mean / rknn_std 等 RKNN 参数；不支持的芯片/INT8/dynamic/batch>1 在任务持久化前 fail closed。
- Agent 下载 verified model object 后在节点本地执行现有 `deployment_worker.py` + RKNN-Toolkit2，生成唯一非空 `.rknn`。
- RKNN 成功状态必须是 `converted_unverified`；Agent 不得把“成功转换”伪装成“板端硬件已验证”。
- 输出重新计算 size/SHA256，经 generation-scoped immutable PUT、server-confirm 后，控制面重新下载并复核，再写回既有：
  - `deploy/jobs/<task>/artifacts/model_<chip>.rknn`
  - `manifest.json`
  - `job.json`
- RKNN job 明确写 `runtime_verified=false`、`hardware_verified=false`、`validation_status=converted_unverified`，产品提示“等待目标板 Runtime 实机验证”。
- 前端部署转换已补齐 RK3576 选项，并只根据后端 resource truth 暴露可用 RKNN Agent，不在无真实 RKNN 节点时假装可用。
- Real Chrome 已覆盖 RKNN Agent 资源配置/展示与 Rockchip 芯片选项。

最终验收（代码 HEAD `5a02aa5ba03e94cc731bfd0e62437c57738efab1`）：

- Remote Conversion Runtime `35330889750`：control-plane / Ubuntu Agent / Windows Agent / Real Chrome 全绿。
- Node Agent Executor `35330889657`：全绿。
- Central Node Assignment `35330889375`：全绿。
- Task Runtime Truth `35330889784`：全绿。
- Portable Deployment `35330889497`：全绿。
- Remote Material Import `35330889535`：全绿。
- Remote Training Runtime `35330889384`：全绿。
- Remote Cleaning Runtime `35330889291`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Rockchip 板端 Runtime 验证协议 / 产品闭环

2026-09-18，Rockchip RKNN 板端 Runtime 验证的软件协议、Agent runner、控制面提交和产品入口已完成闭环并 CLOSED。

当前真实能力：

- 服务节点新增独立 `deployment-test.rknn` capability，不从普通 `deployment-test` 或 `conversion.rknn` 推断板卡 Runtime 可用。
- Node Agent 仅在 Linux arm64/aarch64 上读取 `/proc/device-tree/compatible`，真实识别 RK3568/RK3566 family 或 RK3576，并且当前 Python 可导入 `rknnlite.api.RKNNLite` 后才上报该 capability。
- heartbeat runtime 持久化 `rknn_board.available/chip/architecture/compatible/rknn_lite_version`；控制面只允许芯片完全匹配的 online Agent 接受板端任务。
- 板端验证复用既有 `DEPLOYMENT_TEST` durable truth；任务仍受 assignment lease / execution lease / generation fencing 约束，Agent 不访问中央 SQLite/NFS。
- 控制面在创建任务前重新校验原 RKNN conversion manifest 与 `.rknn` 文件 size/SHA256，随后把模型和测试图以 portable object contract 送到匹配板端节点。
- 节点真实执行 `predict_rknn_lite_runner.py`：
  - `RKNNLite.load_rknn`
  - `RKNNLite.init_runtime`
  - 图片预处理
  - 至少一次 `RKNNLite.inference`
  - 回传 `inference_ms / output_count / output_shapes`
- Agent runner 明确只做 **hardware runtime verification**，不把“能跑一次”冒充为检测准确率验收，也不解析模型特定 YOLO 输出。
- result 继续走本地 hash → immutable upload → server-confirm；控制面在最终提交前再次确认 conversion job/chip/model SHA256 未变化。
- 只有 runtime evidence 满足 `engine=rknn-lite2 + runtime_format=rknn + chip match + output_count>0` 后，原 conversion `manifest.json/job.json` 才允许写：
  - `runtime_verified=true`
  - `hardware_verified=true`
  - `validation_status=hardware_verified`
- 部署中心对 `rockchip + converted_unverified` 任务展示“板端验证”；用户上传测试图后轮询真实 durable task，成功后刷新为“实机已验证”，并展示芯片、推理耗时和输出数量；已验证任务不重复显示验证按钮。
- Real Chrome 已覆盖：未验证 RKNN 任务 → 板端验证入口 → 上传图片 → durable task success → UI 刷新 `hardware_verified` 状态。

软件闭环最终验收（代码 HEAD `05c7b93339414ac028214fd3d046dfdf7977c0a1`）：

- Remote RKNN Board Runtime Protocol `35335720990`：API / Ubuntu / Windows / Real Chrome 全绿。
- Remote Conversion Runtime `35335720906`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35335720915`：全绿。
- Central Node Assignment `35335720909`：全绿。
- Task Runtime Truth `35335720969`：全绿。
- Portable Deployment `35335720910`：全绿。
- Remote Material Import `35335720921`：全绿。
- Remote Training Runtime `35335720913`：全绿。
- Remote Cleaning Runtime `35335721027`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

**重要边界：以上是软件协议/产品闭环验收，不等于你们手上的真实 RK3568 / RK3576 设备已经完成硬件验收。** CI 没有真实 Rockchip NPU 板卡；实际设备接入 Agent 后仍需至少执行一次真实板端任务，才能对该具体模型写入 `hardware_verified=true`。

# 最新关闭：Rockchip RKNN INT8 calibration portable transport

2026-09-18，Remote RKNN INT8 calibration 已完成真实 portable Agent 闭环并 CLOSED。

当前真实能力：

- Rockchip Agent 资源通过后端 `supported_precisions` 暴露真实可用精度；当前远程 RKNN 正式支持 **FP16 / INT8**，不再由前端自行猜测。
- 用户选择 INT8 时必须明确校准数据集、split 与图片数量；创建任务前控制面冻结 calibration snapshot。
- snapshot 持久化：
  - dataset_id / split
  - MaterialRepository revision
  - 精确 image_id / storage_source_id / object_key
  - size_bytes / SHA256 / ETag
  - requested_count / item_count
- calibration image 必须来自可 portable 的 OSS / S3 / MinIO；本地路径、缺 SHA256/size、对象内容变化都会在 durable task 创建前 fail closed。
- Agent start payload 不包含控制面本地目录、SQLite/NFS 或长期对象存储凭据；每张校准图只获得短期 GET contract。
- Agent 逐张下载并校验 size / SHA256，写入本次 generation workdir 的 calibration 目录。
- Agent 再校验 `calibration_snapshot + calibration_count + 实际文件数` 一致后，才允许启动 node-local `deployment_worker.py`。
- `deployment_worker.py` 从冻结图片生成 `rknn_dataset.txt`，真实执行 RKNN-Toolkit2 INT8 build；没有真实校准图片时拒绝转换。
- INT8 输出仍走既有 generation-scoped immutable upload → size/SHA256 → server-confirm → deployment job commit，不产生第二套 RKNN 产物 truth。
- INT8 与 FP16 的转换结果都保持 `converted_unverified / hardware_verified=false`；必须经过已 CLOSED 的匹配 Rockchip 板端 RKNNLite 任务后才能升级为 `hardware_verified=true`。
- 部署中心已正式开放 RKNN Agent INT8：仅资源 truth 包含 `int8` 时可选；UI 展示校准数据集、分组、数量，并真实提交到后端。
- Real Chrome 已覆盖：选择 Rockchip Agent → INT8 → 校准数据集/split/count → 创建 durable conversion task。

最终验收（代码 HEAD `314757c1601420640acedc074e9aeb795e8a2097`）：

- Remote Conversion Runtime `35340943761`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Remote RKNN Board Runtime Protocol `35340943851`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35340943850`：全绿。
- Central Node Assignment `35340943861`：全绿。
- Task Runtime Truth `35340943758`：全绿。
- Portable Deployment `35340943913`：全绿。
- Remote Material Import `35340943781`：全绿。
- Remote Training Runtime `35340943764`：全绿。
- Remote Cleaning Runtime `35340943815`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Rockchip 实机接入软件工具链

2026-09-18，Rockchip 板端 Node Agent 的安装、严格预检和服务节点产品入口已完成软件闭环并 CLOSED。

当前真实能力：

- `node_agent.py` 新增严格 `--doctor`：请求的任一 capability 无法真实上报时返回非零，并输出 `doctor.ready / issues`；原有 `--check` 语义不变。
- 新增 `tools/install_rockchip_agent.sh`：仅 Linux/systemd；安装前执行 strict doctor；默认只启用 `deployment-test.rknn`。
- Agent Token 不进入安装命令或 systemd `ExecStart`；只保存到 root-owned、`0600` 的 EnvironmentFile。
- `ExecStartPre` 在每次服务启动前再次 doctor；SoC/RKNNLite 环境失效时不会假装上线。
- 服务节点页面新增 `conversion.rknn → 瑞芯微 RKNN 转换`、`deployment-test.rknn → 瑞芯微板端验证` 中文标签。
- 新增 Rockchip 板端快捷预设，一键选择远程 Agent + `deployment-test.rknn`。
- 节点卡片显示真实 `rknn_board.chip / RKNNLite version` 与 RKNN-Toolkit2 runtime truth。
- 一次性 Token 弹窗针对板端节点额外展示 strict doctor 与 systemd 安装命令；生成的 systemd 安装命令不包含 Token。
- 普通 Linux/Windows Agent 启动方式保持兼容。
- 当前工具链仍只认真实 RK3568/RK3566 family 或 RK3576；现场若写“RK3578”，必须先读取真实 `/proc/device-tree/compatible`。

最终软件验收（代码 HEAD `b8caf7753994988d5161321c2536ae75e64d3252`）：

- Service Node UI `35342366446`：Ubuntu / Windows contract + Real Chrome 全绿。
- Remote RKNN Board Runtime Protocol `35342366573`：API / Ubuntu / Windows / Real Chrome 全绿。
- Remote Conversion Runtime `35342369723`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35342369838`：API / Ubuntu / Windows 全绿。
- Central Node Assignment `35342369780`：API / Ubuntu / Windows 全绿。
- Remote Training Runtime `35342369831`：API / Ubuntu / Windows 全绿。
- Remote Material Import `35342369794`：API / Ubuntu / Windows / Real Chrome 全绿。
- Task Runtime Truth `35342369798`：全绿。
- Portable Deployment `35342369765`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

**重要边界：这次 CLOSED 的是“实机接入的软件工具链”，不是你们手上某一台真实 Rockchip 板卡已经通过硬件验收。**

**当前主线：Rockchip 真实板卡 acceptance。**

下一步需要一台真实 RK3568 / RK3576（或先识别实际 SoC 的设备）运行本仓库 Node Agent。软件侧只继续做验收辅助：doctor → 节点 ONLINE/effective `deployment-test.rknn` → 选择一个 `converted_unverified` RKNN 模型 → 真板执行 RKNNLite inference → 只有成功后该具体模型才写 `hardware_verified=true`。CI、mock 或 x86 runner 都不能替代这一步。

# 最新关闭：Remote MODEL_CONVERSION / ONNX Runtime

2026-09-18，第三个真实跨机器 task kind 已 CLOSED：`MODEL_CONVERSION` 的 **ONNX** 目标。

当前 Agent 真实执行能力：

```text
deployment-test
training
conversion（当前只闭环 ONNX）
```

完整闭环：

- 部署资源新增显式 `mode=agent`；状态直接来自 Service Node Registry。
- 只有在线、enabled、allowed+reported 后形成 effective `conversion` 的 Agent 节点才可用。
- Agent ONNX 任务使用 portable verified model object，不把控制面 `stored_path/job_dir/worker_path/python_path` 发到节点执行。
- durable task 使用 Agent-only Worker capability fence，legacy local ConversionHandler 不会与中央 assignment 抢同一任务。
- Agent 下载模型并校验 Content-Length / size / SHA256。
- 节点本地调用本机 `deployment_worker.py` 与本机 Python；真实 ONNX export 后由 ONNX Runtime 做 runtime verification。
- subprocess 继续使用 persisted ProcessIdentity；cancel / lease loss / Agent shutdown 精确终止进程树。
- runner cleanup 不安全时动态撤销 conversion capability；没有 runner/effective capability 时在 `start_execution` **之前** fail closed。
- 输出本地计算 hash/size → prepare → generation-scoped immutable PUT → confirm。
- server-side finalization gate 后，控制面重新下载 ONNX 并再次校验 hash/size。
- 已验证 ONNX 写回原有 `deploy/jobs/<task>/artifacts/model.onnx`、`manifest.json` 和 `job.json`，部署中心现有产物列表/下载继续可用。
- 显式 Agent staging 失败禁止静默回退本机。
- TensorRT / RKNN / Sophon / Ascend 等厂商转换**尚未因为 ONNX closure 自动变成远程可用**。

最终验收：

- Remote Conversion Runtime `35306100598`：control-plane / Ubuntu / Windows 全绿。
- Node Agent Executor `35306100599`：API / Ubuntu / Windows 全绿。
- Central Node Assignment `35306100621`：API / Ubuntu / Windows 全绿。
- Portable Deployment `35306100612`：production API / Ubuntu / Windows 全绿。
- Remote Training Runtime `35306100615`：production API / Ubuntu / Windows 全绿。
- 临时 draft PR #15 已关闭，未 merge。
- `VERSION.txt` 仍为 `42.24.0`。

**当前主线：Remote MATERIAL_IMPORT Runtime。**

优先把大 ZIP / 图片素材导入从控制面重 IO 中拆到素材导入 Agent：安全解包、格式识别、标签转换/基础清洗、对象存储上传都在节点完成；中央端只在 server-confirm 后提交 MaterialRepository metadata。绝不能让远程素材节点直接访问中央 SQLite/NFS。

# 最新关闭：Remote TRAINING Runtime

2026-09-18，第二个真实跨机器 task kind 已 CLOSED：`TRAINING`。

当前 Agent **真实可执行**：

```text
deployment-test
training
```

其中 `training` 不是静态虚报：若 Agent 启动恢复时无法安全处理遗留训练进程，`AgentTrainingRunner.ready=false`，heartbeat 会动态移除 training capability。

完整闭环：

- remote train 创建同一个 durable TRAINING task，并创建独立 `TRAINING_PREPARE` 后台任务。
- prep Worker 锁定 split/snapshot，生成/复用 verified portable bundle。
- bundle 安全 ZIP 归档，持久化 SHA256 / size / member_count / snapshot_id，上传 OSS/S3/MinIO 后服务端再次校验。
- `target=remote` 在 READY 前不会回退本机 Worker。
- 首次官方模型只保存 allow-listed reference；算法迭代继续强制使用最新可训练上一版本，并转为 verified model object。
- Agent 下载并校验 bundle / object model，使用节点本地 `train_worker.py` 和节点本地 Python 启动真实 subprocess。
- heartbeat / progress / bounded logs 回到中央 execution truth。
- cancel / fence / Agent shutdown 终止精确进程树；进程树清理不可证明时 fail closed。
- best / last 作为独立 immutable model objects 上传并确认。
- training result 为 manifest-only bundle，不重复塞模型二进制。
- result/model 全部 server-confirm 后才允许 finalization，并写回统一 ModelArtifact / 算法版本 truth。
- Agent runtime 仍不打开中央 SQLite、不依赖 NFS。
- 已修复 portable 参数缺失时 `None` 未回退默认值导致 `int(None)` 的真实执行问题。

最终验收：

- Remote Training Runtime `35303815439`：Ubuntu / Windows / API 全绿。
- Node Agent Executor `35303815460`：Ubuntu / Windows / API 全绿。
- Central Node Assignment `35303815499`：Ubuntu / Windows / API 全绿。
- Portable Deployment `35303815438`：Ubuntu / Windows / production API 全绿。
- 临时 draft PR #14 已关闭，未 merge。
- `VERSION.txt` 仍为 `42.24.0`。

**当前主线：Remote MODEL_CONVERSION Runtime。**

现有 conversion handler 仍带中央 `job_dir / worker_path / python_path`，不能直接远程执行。下一步要把输入改为 verified model object，转换工具/SDK 由节点本地 capability 决定，输出走 generation-scoped immutable upload + server confirm；不能退回共享 SQLite/NFS。

# 最新关闭：服务节点控制面 + 中央分配 + Executor 控制协议 + Remote Portability

2026-09-18 已完成并验收：

- 服务节点 registry / heartbeat / 一次性 Agent Token / Windows+Linux 本机资源探测。
- 服务节点管理 UI，包含 CPU / RAM / disk / GPU / VRAM / Torch / CUDA / Worker / durable task 状态。
- 中央 durable task → node assignment truth。
- active assignment partial unique fence + legacy Worker `CENTRAL_NODE_ASSIGNED` 自抢保护。
- HTTP Agent Executor 控制协议：claim / start / heartbeat / log / begin-finalization / finish。
- Node Token、Assignment Lease Token、Execution Lease Token + generation 三层 fencing。
- Agent-side database-free HTTP client / isolated workdir / lease monitor。
- Remote portability gate：`agent` 节点只有遇到显式、版本化 portable contract 才允许调度；legacy path-bound task 不会误发远程。
- Scheduler 仅持久化 sanitized remote contract 元数据，不保存任务携带的 signed URL / credential / 中央路径。
- 生产 `app.py` 已正式、且只挂载一次 `training_recovery_router`；service-node / scheduler / executor 不再只存在于 focused test。
- Portability gate 验收：Central `35290891091`、Agent `35290891208`，均 API / Ubuntu / Windows 全绿。
- Production mount 验收：Central `35291195275`、Agent `35291195262`，均 API / Ubuntu / Windows 全绿。

权威设计：

`docs/NODE_CONTROL_PLANE_V42_25.md`

**下一步主线：第一个真正 portable 的远程 task kind。优先部署测试。**
需要复用已有模型资产统一 OSS/S3/MinIO 存储，建立远程输入/输出 transport，让 `node_agent.py` 真正 claim → start → 本机执行 → heartbeat/log/cancel → 上传结果 → finish。训练/素材的大文件仍不得退回共享 SQLite/NFS。

# 最新关闭：Portable Deployment Transport + Hash-bound Result Publication

2026-09-18 已进一步完成：

- 部署测试 durable task 可保存 version-1 `object-storage-v1` portable contract。
- 输入与项目模型通过统一 OSS / S3 / MinIO 模型资产和对象存储传输；官方模型保持 allow-listed reference。
- Agent start payload 不包含中央 `input_path / model_path / runner_path / python_path`。
- 输出 PUT 不在 start 阶段签发；Agent 必须先在本机计算结果 SHA256 + size，再通过 `result-upload/prepare` 申请短期 PUT。
- S3 / OSS presign 会绑定 Content-Length、SHA256 metadata 和禁止覆盖条件。
- 结果对象按 execution generation 隔离，旧代 PUT 无法占用新代结果 key。
- `result-upload/confirm` 由控制面 stat 并验证 size/hash；通过后再走 finalization 原子闸门。
- cancel 与 result publication 不能同时获胜。
- `finish(SUCCEEDED)` 不信任 Agent 自报 result_ref，强制使用当前 generation 的 server-confirmed result。
- signed URL 从不进入 Scheduler truth 或 durable result state。

验收：

- Portable transport：`35292400487` 全绿。
- Hash-bound result publication：Agent `35295427105`、Portable `35295427110`、Central `35295427100` 全绿。
- CI 临时 PR #11 / #12 均已关闭，未 merge。
- `VERSION.txt` 始终保持 `42.24.0`。

# 最新关闭：Agent-side Real Deployment Runtime

2026-09-18 已完成第一个真实跨机器 task kind：

- `node_agent.py` 已接入 database-free `NodeExecutorClient`。
- 仅上报当前 build 真正可执行的 `deployment-test` 远程能力，不虚报 training/conversion。
- 单并发 executor loop 真实 claim → start → dispatch。
- 输入与对象模型下载后逐字节校验 size/SHA256；官方模型只接受 allow-list reference。
- 推理使用节点本地 Python 与节点本地 runner，不解释控制面绝对路径。
- heartbeat/cancel/lease fencing 真实作用于节点本地 subprocess。
- cancel、lease loss、Agent shutdown 均通过 ProcessIdentity 终止精确进程树。
- 结果执行本地 hash → prepare → generation-scoped PUT → confirm → finalization → finish。
- workdir 在终态/fence 后清理。
- Agent executor 只在首次控制面 heartbeat 成功后启动。
- `node_agent.py` / executor loop / entrypoint 测试已进入永久 CI。

最新验收：

- Node Agent Executor `35297453169`：API / Ubuntu / Windows 全绿。
- Portable Deployment `35297453136`：production API / Ubuntu / Windows 全绿。
- `VERSION.txt` 仍为 `42.24.0`。

> 上述 Agent Deployment Runtime 段落是 2026-09-18 当时的关闭快照；Remote TRAINING 此后已按本文件更上方“最新关闭”完成。当前主线以最上方为准。


# 1. 产品定位

产品：**畅联云算法训练平台**。

当前优先目标不是做一个好看的 Demo，而是形成真实可用链路：

```text
素材导入
→ 数据清洗 / 标注
→ 训练配置
→ durable training task
→ 模型版本
→ 模型转换
→ 部署/发布
→ 线上算法回流
→ 评测
→ 低准确率算法再次迭代
```

当前主要算法框架：

```text
Ultralytics / YOLO
Paddle（兼容扩展）
OpenCV 等辅助能力
```

长期生产架构目标：

```text
Web / API
Scheduler
Training Worker
AI Label Worker
Video Worker
Model Conversion Worker
Deployment Test Worker
Publish Worker
```

Windows 负责开发、页面、普通 CPU 测试、素材/标注、视频切帧、小规模训练、ONNX 等；正式 GPU 训练/转换统一考虑 NVIDIA Linux。

---

# 2. 当前数据 owner / truth

这是最容易被新接手者弄乱的部分。

## 2.1 算法资产

**当前 authoritative store：SQL。**

主文件：

```text
platform_core/algorithm_sql_store.py
platform_core/algorithms.py
```

项目级存储目前为：

```text
algorithms.sqlite3
```

旧：

```text
algorithms.json
```

仅作为历史迁移源；首次迁移会保留：

```text
algorithms.json.pre-sql-migration-backup
```

### 重要：普通 CRUD 已经是 row-level SQL

不要再做一次“把 create/update/delete/version attach 从全量 replace 改为 SQL CRUD”的重复工作。

当前普通 owner 已经调用：

```text
AlgorithmSqlStore.create_algorithm
AlgorithmSqlStore.patch_algorithm
AlgorithmSqlStore.delete_algorithm
AlgorithmSqlStore.attach_version
AlgorithmSqlStore.patch_version
AlgorithmSqlStore.rollback_version
AlgorithmSqlStore.delete_version_with_operation
```

外部平台镜像也调用：

```text
AlgorithmSqlStore.sync_external_algorithms
```

`save_algorithms()` 仍保留用于兼容路径/测试，不代表主业务仍把 JSON 当数据库。

## 2.2 Durable Task

任务真实状态以后端 TaskRepository / durable task runtime 为准。

前端不能自己“猜”任务已经结束、排队第几名或剩余百分比。

当前已关闭的核心任务 truth 包括：

```text
Training
AI annotation
material batch
storage scan/import
server ZIP import
resource discovery
video processing
deployment tests
```

公共 task projection 的 authoritative 字段优先级参见 `docs/CODEX_CURRENT_STATE.md`。

## 2.3 上传任务用户可见 owner

现在统一是：

```text
static/modules/upload-task-center.js
```

右下角显示：

```text
普通图片上传
ZIP 分片上传
ZIP 合并/校验
后台导入
标签映射
标注写入
素材索引
```

旧单任务 `zipImportDurableDock` 只保留兼容/详情 owner；当统一 Task Center 存在时应保持隐藏，不能再恢复第二套可见浮窗。

---

# 3. ZIP 上传 / 标签导入当前实现

这是 2026-09-17 最新重点批次。

## 3.1 ZIP 网络上传

主文件：

```text
static/modules/zip-import-runtime.js
platform_core/zip_multipart.py
app.py
```

当前：

```text
part size:        8 MiB
max concurrency:  4
part retries:      2
```

服务器每个 part 独立持久化，最终 assemble：

```text
确认所有 part 完整
→ 合并
→ 精确检查 assembled bytes
→ 计算完整 ZIP SHA256
→ 标记 multipart completed
→ 清理 parts 目录
```

浏览器续传 fingerprint 已不再只用 filename/size/mtime，而加入文件头/中/尾采样内容摘要，降低误复用另一个 ZIP 分片的风险。

### 刷新时

如果刷新发生在 browser File 还在上传的阶段：

```text
任务状态显示：上传已暂停，等待继续
```

用户重新选择同一个 ZIP 后，浏览器重新计算 fingerprint，服务器返回已完成 parts，仅继续缺失部分。

不能在刷新后继续显示“正在传输字节”，因为浏览器已经没有原 File stream。

## 3.2 ZIP 整体进度

必须区分：

- 网络上传百分比；
- 整个 ZIP 导入任务百分比。

当前整体进度：

```text
网络上传：       0 → 35
服务器合并：     36
ZIP 校验：       37
等待后台导入：   38
后台任务：       38 → 99
全部完成：       100
```

实际网络上传百分比继续显示在文本详情。

禁止恢复“上传 100%，然后后台又退回 8%”的旧表现。

## 3.3 YOLO 标签映射 / 索引

主文件：

```text
platform_core/storage/import_tasks.py
```

标签确认后 durable 阶段包含：

```text
mapping_labels
writing_annotations
indexing
```

当前索引事务批次：

```text
INDEX_BATCH_SIZE = 50
```

不要再改回 500 张一个大批次。用户之前 500 张转换时长时间无反馈，核心原因之一就是一个超大的落库批次。

---

# 4. 训练任务当前实现

## 4.1 创建训练

训练弹窗必须直接带：

```text
算法名称
本次训练任务 ID
```

任务 ID 格式：

```text
train_<16~32 hex>
```

前端唯一网络 owner：

```text
TrainingSubmitRuntime
static/modules/training-submit.js
```

后端：

```text
/api/v12/projects/{project_id}/train/start
```

同一个 planned task ID 如果因为响应丢失被再次 POST：

- 同项目；
- 已存在 task kind = TRAINING；

则返回已有 task，不能创建第二个训练任务。

## 4.2 迭代训练

已有算法继续训练时，必须基于该算法**当前/最新成功、产物完整性已验证、框架匹配**的模型版本。

禁止因为上一轮失败就悄悄回到母算法重新训练。

相关：

```text
platform_core/algorithms.py
choose_algorithm_iteration_base()
resolve_current_version_id()
```

## 4.3 用户对训练弹窗的明确偏好

不要重新加回：

```text
预计时长
训练完成后通知
大量提示性废话
标签缩略图
标签右侧 xx 张
```

需要：

```text
算法名称默认带入
任务 ID
数据质量按钮
本次训练标签选择
训练摘要：轮次 / imgsz / batch / 阶段检查 / 转换等
```

---

# 5. 新畅联平台交互

## 5.1 Domain 关系

当前按：

```text
品目
→ 产品
→ 分析方式
→ 算法版本
→ 权重文件
→ 算力环境
```

外部算法主数据同步到本平台后：

```text
source_type = EXTERNAL
provider_type = CHANG_LIAN
master_data_readonly = true
```

本地已有算法不能因此消失。

外部产品从远端消失时：

```text
external_active = false
```

保留历史训练/版本，只阻止新训练。

多分析方式产品创建训练时必须明确绑定本次 `external_analysis_id`。

## 5.2 当前认证事实

现在不是最终 production canonical signing。

当前明确：

```text
/internal/auth/test-sign
→ /internal/auth/token
→ Bearer Token
```

UI/API 明确暴露：

```text
auth_mode = test_sign_bridge
```

后续不能把这个事实改写成“正式签名已经确认”。

## 5.3 发布

已经实现 Phase 2：

```text
训练版本/转换产物
→ artifact index / object storage
→ stable download gateway
→ 新畅联创建算法版本
→ 新畅联创建权重
→ 保存 remote IDs
```

核心原则：

- 发布失败不能破坏本地已验证模型；
- 有 idempotence / retry / UNKNOWN 处理；
- HTTP timeout 后不能盲目重复创建远端对象。

详细见：

```text
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
```

---

# 6. 2026-09-17 BUG 审计结论

完整记录：

```text
docs/BUG_AUDIT_2026-09-17.md
```

本轮已经修复并进入永久测试：

```text
FIX-01 Linux 无 Keyring backend 导致 config 500
FIX-02 ZIP 整体进度 100 → 0/8 倒退
FIX-03 multipart 上传途中刷新后假装仍在上传
FIX-04 multipart fingerprint 元数据碰撞风险
FIX-05 Real Chrome 仍验证退休的单任务 dock
```

永久 workflow 最新本轮验收：

```text
ZIP Import Durable Runtime
Run ID: 35213047885
```

该 run：

```text
Ubuntu contracts                 PASS
Windows contracts                PASS
backend persistence              PASS
SecretStore contracts            PASS
multipart contracts              PASS
bounded 10k hot-state            PASS
Real Chrome refresh recovery     PASS
```

---

# 7. 当前 OPEN 项目

这部分不能在汇报里包装成“已完成”。

## CLOSED — Headless Linux Secret 持久化

状态：**CLOSED（代码与永久合同完成；真实生产主机仍需部署验收）**。

当前 SecretStore 已形成三层安全策略，禁止明文 JSON 回退：

```text
1. 环境变量只读注入（优先）
   MC_CHANGLIAN_ACCESS_KEY
   MC_CHANGLIAN_ACCESS_SECRET

2. 系统 Keyring
   Windows Credential Locker / Linux SecretService 等可用 backend

3. Headless Linux 加密文件 fallback
   MC_SECRET_MASTER_KEY
   → Fernet 加密
   → <data_dir>/secure/secrets.enc.json
```

`MC_SECRET_MASTER_KEY` 是服务器主密钥，必须由部署环境/Secret Manager 注入，不能写进仓库、普通 JSON 或前端。

配置页面会明确显示当前凭据后端：

```text
环境变量 / 系统密钥环 / 服务器加密文件 / 不可用
```

如果安全 backend 不可用，真实 Secret 写入继续 fail-closed，不会降级为明文保存。

相关主文件：

```text
platform_core/secrets.py
static/modules/external-algorithm-platform.js
requirements.txt
```

永久测试覆盖环境变量优先级、加密文件 round-trip、密文不包含明文 Secret、backend public state 和无 backend 安全降级。

## CLOSED — Multipart session TTL / GC

状态：**CLOSED**。

未完成 ZIP multipart session 现在包含：

```text
created_at
updated_at
expires_at
```

当前项目策略：

```text
默认 TTL：24 小时
每成功写入一个 part：刷新 updated_at / expires_at
completed session：不参与过期 GC
```

右下角 UploadTaskCenter 会轮询 v19 导入任务列表；该服务端入口会调用：

```text
cleanup_expired_if_due(interval_seconds=60)
```

因此正常使用平台时最多每 60 秒尝试一次 GC，而不是每次页面轮询都扫描磁盘。GC 记录：

```text
removed_uploads
released_bytes
last_run_at
```

新建/恢复 multipart session 时也会执行过期清理兜底。

## P1 — 真实 500 张 ZIP benchmark

代码结构已优化，但尚未用用户原先那个真实场景重新量化。

部署后必须拆阶段测：

```text
network
merge
validation
extract
format parse
annotation write
material index
total
```

## P1 — 新畅联 live contract 最终确认

仍需要真实环境确认：

```text
production canonical signature
filePath
chipCode
algoVersionId response
weight remote final state
remote commit recovery
```

## P2 — UploadTaskCenter 常驻 project switch interval

当前仍有：

```text
setInterval(switchProject, 1500)
```

后续应由 NavigationStability / project owner 主动通知，不应该长期轮询项目 ID。

## P2 — 外部平台 auto-sync 在 Web 进程 daemon thread

单进程能工作，FileLock 能避免同目录同时 sync；但多 API worker / 多机后应迁到现有 Scheduler/Worker。

不要因此新造第二套 scheduler。

## 架构演进 — PostgreSQL

当前 algorithm SQL 是 per-project SQLite。

它是当前单机/开发可用方案，不代表适合 NFS 多机器中央事务数据库。

未来保留 Repository abstraction，新增 PostgreSQL backend；不要把 SQLite over NFS 当最终答案。

---

# 8. 当前最重要代码索引

## 算法 / SQL

```text
platform_core/algorithm_sql_store.py
platform_core/algorithms.py
tests/unit/test_algorithm_sql_store.py
tests/unit/test_algorithms.py
.github/workflows/algorithm-sql-store.yml
```

## 上传 / 导入

```text
platform_core/zip_multipart.py
platform_core/storage/import_tasks.py
static/modules/zip-import-runtime.js
static/modules/upload-task-center.js
static/modules/storage-import-progress.js
static/zip-import-bootstrap.mjs
app.py
```

测试：

```text
tests/unit/test_zip_multipart.py
tests/unit/test_secrets.py
tests/frontend/zip-import-durable-runtime.test.mjs
tests/frontend/zip-multipart-upload.test.mjs
tests/frontend/upload-task-center.test.mjs
tests/frontend/storage-import-progress.test.mjs
tests/browser/zip-import-refresh-recovery.spec.mjs
tests/api/test_v19_job_atomic_persistence.py
tests/api/test_v19_import_scalability.py
```

永久 CI：

```text
.github/workflows/zip-import-durable-runtime.yml
```

## 训练

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-submit.js
static/modules/training-task-runtime.js
static/modules/training-task-visibility-runtime.js
platform_core/algorithms.py
app.py
```

永久 CI：

```text
.github/workflows/training-task-visibility.yml
```

## 新畅联

```text
platform_core/external_algorithm_platform.py
platform_core/external_algorithm_publish.py
static/modules/external-algorithm-platform.js
static/modules/external-algorithm-publish.js
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
```

## Secret

```text
platform_core/secrets.py
tests/unit/test_secrets.py
```

---

# 9. 不要重复的 CLOSED 工作

除非你找到新的、可复现证据，否则不要重新开启：

```text
training mirror fields
/train/start single owner
/jobs duplicate race
training metrics SQLite FD leak
training / AutoLabel / video / source polling owner
setupPagePolling legacy timer cleanup
classic setPage owner cleanup
Task Runtime Truth
Worker Runtime Truth
Training Queue Readiness Truth
Training Bundle Snapshot Cache
algorithm JSON → SQL migration
algorithm row-level CRUD migration
external algorithm mirror preserving local algorithms
external inactive preservation
external multi-analysis training binding
external publish Phase 2 base implementation
ZIP durable runtime owner
ZIP resumable multipart base implementation
training planned task id identity
```

如果某个 CLOSED 项目现在失败：

1. 先给出复现；
2. 找 regression commit；
3. 修 regression；
4. 不要把旧架构整体重写一遍。

---

# 10. 推荐下一批实际工作

如果用户没有重新指定其他方向，建议按：

```text
1. Headless Linux SecretStore 正式方案
2. Multipart session TTL / GC
3. 真实 500 张 ZIP 分阶段 benchmark + 性能热点优化
4. 新畅联 live API 最终合同验证
5. UploadTaskCenter 去除 project-switch 常驻 interval
6. External auto-sync 迁入现有 durable scheduler/worker
7. 多机前再做 PostgreSQL Repository backend
```

其中第 3 项必须用真实 ZIP，不能根据单元测试估算“优化了多少倍”。

---

# 11. 每次交付最低检查

至少：

```bash
cat VERSION.txt
git status
git rev-parse HEAD
git diff --check
```

按涉及模块跑 focused tests。

上传链路至少确认：

```text
Ubuntu contract
Windows contract
backend persistence
Real Chrome refresh recovery
```

训练链路至少确认：

```text
TrainingSubmitRuntime 单 owner
planned task ID = backend durable task ID
刷新后任务可见
重复提交幂等
```

算法 SQL 至少确认：

```text
legacy JSON 迁移不丢 ID
本地算法不被 external sync 删除
row-level CRUD
version current pointer
rollback/delete transaction
```

最后再确认：

```text
main 未被误改
VERSION.txt 仍为 42.24.0
无临时 one-shot helper/workflow 残留
```

---

# 12. 给下一位 AI 的一句话

**不要从头重构。先读取远端真实 HEAD 和本文件，从当前已验证 owner / SQL / durable task / upload runtime 上继续，把 OPEN 项逐个关闭；任何“性能更快”必须用真实阶段数据证明，任何“可恢复”必须经过刷新/中断测试证明。**


## CLOSED — Training label filter task-derived negatives

2026-09-17 product rule: selected materials stay in the training task. The training label checkbox defines the positive schema. If all source boxes are excluded by that schema, the task projection becomes an auditable background sample (`negative_origin=filtered_by_training_labels`) without mutating source annotations. Mixed-label images retain selected boxes. Explicit `确认无目标` remains distinct.
