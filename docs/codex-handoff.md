# Codex / 人工接管交接记录

## 2026-10-04 RKNN capability guard / remote transport 合同补齐（最新）

本节基线：

- 上游 HEAD：`069cee4fef28a9d2422a3f8530c57bc20b21d091`
- 上游 VERSION：`42.24.82`
- 本提交正式版本：`42.24.83`

`42.24.81` 已把产品 RKNN target_platform 纠正为 `RK3568 / RK3576`，但 remote transport 的错误文案、portable conversion 单测以及 `Remote Conversion Runtime` workflow source guard 仍残留旧的 RK3578 合同。

本提交只补齐同一 capability truth：

- `SUPPORTED_ROCKCHIP_CHIPS` 继续是唯一产品转换允许集合；
- remote conversion / board validation 错误消息只声明 RK3568 / RK3576；
- RK3578 与 RK3588 都作为产品合同负向样例 fail-closed；
- workflow 不再要求 UI / worker / browser tests 出现 RK3578，并明确防止 RK3578 / RK3588 被重新暴露成产品转换选项。

不修改 conversion UI owner、durable progress owner、ModelArtifact owner 或 external publication owner。


## 2026-10-04 RKNN 板端验收文案合同同步（最新）

本节基线：

- 上游：`c9e6d4046ab8b991e51f167790635900e46c7223`
- 上游 VERSION：`42.24.81`
- 本提交正式版本：`42.24.82`

`42.24.80` 的 Remote RKNN Board Runtime Protocol 最后一条 real-chrome 红灯不是板端逻辑失败，而是浏览器测试仍断言旧文案“RKNN 已转换，尚未完成瑞芯微实机 Runtime 验证”。

当前产品 UI 已明确改为：

- `转换完成 · 待板端验证`
- `RKNN 文件已生成；完成匹配芯片的 RKNNLite 实机推理后才升级为硬件已验证。`

本提交只同步浏览器验收合同，不回退新的 conversion record 信息层级，不放宽板端验证按钮、preflight、真实 task 进度和最终 hardware_verified 验收。


## 2026-10-04 RKNN 官方型号合同纠正 / Conversion capability truth（最新）

本节正式版本：

`42.24.81`

本节只纠正 `42.24.79 ~ 42.24.80` 中 RKNN 型号能力判断；这两版已经完成的“单一版本转换弹窗、型号下拉、durable progress 原位刷新、转换记录 UI、conversion state bridge”继续保留。

### 1. 纠正：RK3578 不是 RKNN-Toolkit2 官方 target_platform

重新核对 Rockchip 官方 RKNN-Toolkit2 支持平台和官方示例后确认：

- RK3566 / RK3568：支持；
- RK3576：支持；
- RK3588：官方支持，但当前产品合同仍不开放；
- `RK3578`：不是官方 RKNN-Toolkit2 target_platform。

因此此前把 RK3578 加入 Toolkit probe、Agent conversion、board runtime 和前端 canonical set 的改动从本节开始全部 supersede。

当前产品 canonical Rockchip 转换目标：

`RK3568 / RK3576`

### 2. capability truth 继续由真实资源探测驱动

版本转换弹窗仍然使用 SELECT，不恢复手工输入。

本地 RKNN 资源检测不再因为 `from rknn.api import RKNN` 成功就硬编码宣称支持一大串芯片，而是直接复用：

`platform_core.rknn_runtime.probe_rknn_toolkit()`

只有真实通过 `RKNN.config(target_platform=...)` 的当前产品目标才进入 `supported_chips`，前端下拉继续只显示该资源真实上报并且属于产品允许集合的型号。

### 3. fail-closed / regression

本提交同步收紧：

- `platform_core.conversion.SUPPORTED_ROCKCHIP_CHIPS`；
- portable Agent conversion；
- RKNN Toolkit capability probe；
- RKNNLite board SoC identity；
- 自动转换提示与 API fallback；
- external publish UI 文案；
- version conversion UI 支持顺序。

新增负向回归：`rk3578` 作为 Rockchip target 必须被 canonical validation / Agent conversion 拒绝；frontend source guard 禁止再次把 RK3578 放回型号下拉。

旧 handoff 中关于 RK3578 的章节保留作为历史审计记录，但从本节开始均视为已被 supersede。

## 2026-10-04 Conversion CI regression 收口（最新）

本节基线：

- 上游提交：`4ff884fd8fb1ff063f9cb2d092f46ac4dbe882c6`
- 上游 VERSION：`42.24.79`
- 本提交正式版本：`42.24.80`

`42.24.79` 首轮 CI 暴露两个与 conversion 变更直接相关的确定性回归：

1. 重写版本转换记录 renderer 时误覆盖了既有 `rememberVersionConversion428` 与 `window.versionConversionJob428` 状态桥接函数，导致 `openVersionConvert428()` 在真实浏览器中捕获 ReferenceError 后只显示 toast，无法打开“版本转换”弹窗。
2. 两条 frontend source guard 仍固化旧的 RK3568/RK3576 双芯片文案，以及错误地把“仅当原 history dialog 不存在时 fallback 打开版本转换弹窗”也视为重复弹窗。

本提交只恢复既有 conversion 状态桥接 owner，并把测试合同更新为当前真实语义：

- canonical Rockchip 集合：`RK3568 / RK3578 / RK3576`；
- 创建转换成功后优先原地刷新已有 history dialog；
- 只有 history root 不存在时允许 fallback modal；
- 不新增第二 conversion owner。

另一个 `material-workflows` 浏览器失败与本轮 conversion 路径无直接代码交集，已单独重跑失败 job 以区分偶发时序与真实回归；不通过放宽/删除测试处理。


## 2026-10-04 Conversion UX / RKNN capability truth 收口（最新）

本节基线：

- 上游绿基线：`257558bcf596f2474ff597230f94566d197d9dd0`
- 基线 VERSION：`42.24.78`
- 基线 workflows：29 / 29 completed success
- 本提交正式版本：`42.24.79`

上游 `42.24.78` 已确认 RKNN 板端验证只提升同一 canonical ModelArtifact metadata，并重新请求既有 external publication owner；本轮不建立第二 artifact identity。

本轮不修改 Annotation Ground Truth、Training Picker、Dataset Revision、Scheduler 或 ModelArtifact owner。

### 1. 转换型号不再要求用户手工猜写

版本转换继续由既有 `openVersionConvert428 → openNewConvert428 → submitConvert428` owner 负责，没有新增第二套 conversion UI/runtime。

Rockchip / Ascend / Sophon 的芯片字段改为选择式。Rockchip 型号只来自当前已检测转换资源的 `supported_chips`；资源没有上报能力时 fail-closed，不允许用户输入裸数字绕过能力检测。

当前 Rockchip canonical 支持顺序统一为：

`RK3568 / RK3578 / RK3576`

并同步到 core conversion validation、Agent conversion runtime、RKNN-Toolkit2 probe、board runtime detection 和前端校验。

### 2. 创建转换后不再重复弹第二个“版本转换”窗口

此前提交成功后会关闭创建弹窗，再重新调用 `modal('版本转换', ...)`，在已有版本转换弹窗上重复创建一层。

现在创建任务成功后：

创建弹窗关闭
→ 刷新原有版本转换弹窗 body
→ 继续由既有 PollRegistry owner 轮询

只有调用链不存在原 history dialog 时才 fallback 打开版本转换窗口。

### 3. 转换记录继续只读 durable conversion truth

后端 `_overlay_durable_deploy_job()` 已把 canonical `MODEL_CONVERSION` 的 `progress_percent / phase / WAITING_RESOURCE / worker / queue` truth 投影到部署 job。

前端不新增进度推算器，只展示该 canonical progress，并增加明确百分比、当前阶段、资源、精度、芯片和产物层级。

`BLOCKED_BY_HARDWARE` 的 RKNN 现在也能从版本转换记录直接进入板端验证，不会因为 durable status 投影而错误隐藏验证入口。

### 4. 回归边界

新增/加强回归覆盖：

- RK3578 Toolkit capability probe；
- RK3578 Agent conversion；
- RK3578 board identity detection；
- Rockchip 型号必须为 SELECT 且来自 resource capabilities；
- 转换提交后只保留一个版本转换 dialog；
- 任务创建后 37% canonical progress / stage 可立即显示；
- conversion source guard 防止恢复手工型号输入和重复 modal。

下一轮继续沿 external Weight reconciliation → artifact GC/reference truth 深审。



## 2026-10-03 Dataset Revision v2 / Source GT 身份 / 发布链复核（最新）

本节生产代码 cutoff：

`9c70c4939f3bd72596cc50139a43deb96f37fd80`

正式版本：

`42.24.74`

该 cutoff 已确认 GitHub Actions **23 / 23 workflow runs 全部 completed success**，failure / queued / in_progress 均为 0。

本交接提交本身只更新 `docs/codex-handoff.md` 并把正式版本最小 patch 递增到 `42.24.75`；不修改训练、调度、标注、发布、转换或存储生产逻辑。

### 1. CLOSED：Dataset Revision identity 纳入 Source Annotation identity

审计发现旧 `dataset_revision_schema_version = 1` 的 canonical identity 已包含：

- material content SHA256；
- training projection annotation_hash；
- annotation_scope；
- training_projection_digest；
- external annotation provenance；

但遗漏了已经在 Snapshot / input freeze 中持久化的：

`source_annotation_hash`

这会导致一种审计歧义：

Source Ground Truth 已变化，但本次训练 projection 恰好保持相同，则 Dataset Revision v1 可能保持不变。

`42.24.74` 已升级为：

`dataset_revision_schema_version = 2`

v2 canonical fields 显式加入：

`source_annotation_hash`

因此新的 Dataset Revision 同时绑定：

Source GT identity
→ Training Projection identity
→ material bytes
→ label schema
→ external annotation provenance

### 2. CLOSED：历史 Dataset Revision v1 保持兼容

没有直接修改 v1 identity 规则。

当前行为：

- 已存在且声明/推断为 v1 的 Dataset Revision：继续按 v1 字段重算和验证；
- 新 Snapshot：使用 v2；
- 没有 dataset_revision_id 的 legacy snapshot：确定性补齐当前 revision；
- `dataset_revision_document()` 按 snapshot 自己的 revision schema 生成文档；
- 历史 v1 不会因为升级到 v2 被误判 tampered。

新增回归明确验证：

- 只修改 `source_annotation_hash`、保持 `annotation_hash` 和 `training_projection_digest` 不变时，v2 Dataset Revision 必须变化；
- 历史 v1 revision ID 仍能通过 `ensure_dataset_revision()` 和 revision document 校验。

### 3. 训练结果 provenance 复核通过

训练完成链当前继续成立：

`snapshot_id`
→ `dataset_revision_id`
→ portable dataset manifest
→ verified model artifact
→ `model_sha256 + size_bytes + verified=True`
→ training lineage / evaluation truth
→ algorithm version

完成阶段会再次校验 portable bundle 的：

- snapshot_id；
- dataset_revision_id；

并阻止已有 task version 绑定到不同 snapshot / dataset revision。

因此最终算法版本不是只保存模型文件路径，而保留 Dataset Revision 与模型内容 SHA256 的可追溯关系。

### 4. 新畅联发布 / 转换 / OSS 复核结论

本轮继续审计以下链路：

训练成功原始模型
→ immutable artifact object key
→ OSS / configured model storage upload
→ size / SHA256 校验
→ stable public_url
→ URL Range GET probe
→ 创建/恢复新畅联 Version
→ 创建/同步 original Weight
→ ONNX / RKNN 转换权重追加到同一 Version

当前没有发现新的 P0/P1 owner 或准确性缺口。

已确认：

1. 原始模型必须先上传并得到可访问长期 URL，才创建远端 Version；
2. Version + original Weight 完成后才标 PUBLISHED；
3. 转换产物只追加 Weight，不重复创建 Version；
4. public_url 来自 StorageSource 的长期 public_base_url + immutable object_key，不使用临时 signed URL；
5. URL probe 使用 GET + Range，接受 200 / 206；
6. artifact object key 包含 project / algorithm / version / target / chip / SHA256，禁止内容不一致的同名覆盖；
7. original 通用模型允许空 chipCode，Rockchip/RKNN 继续要求真实 chipCode；
8. `blocked_by_hardware / converted_unverified` RKNN 当前合同是“转换产物已生成、板端验证状态另行保留”，仓库有显式回归允许其归档/追加 Weight；本轮不改变该既有合同。

### 5. 当前完整绿基线

生产代码：

- HEAD：`9c70c4939f3bd72596cc50139a43deb96f37fd80`
- VERSION：`42.24.74`
- workflows：23 / 23 success
- failure / queued / in_progress：0

上一轮 Training Picker GT 收口继续保持：

- list label filter → AnnotationRepository GT；
- filtered IDs → AnnotationRepository GT；
- bulk label selection → AnnotationRepository GT；
- test eligibility → annotated / confirmed_empty formal GT；
- MaterialRepository 不重新成为 Ground Truth owner。

### 6. 下一轮建议继续审计

从当前绿基线继续时，不重做已 CLOSED 项。

建议继续沿：

`conversion artifact identity`
→ `board validation result`
→ `external weight reconciliation`
→ `rollback/delete external version`
→ `local version rollback`
→ `artifact GC / orphan cleanup`

重点检查：

- RKNN 板端验证后是否只提升既有 artifact/weight 状态，不生成第二 artifact identity；
- 远端删除/回退是否与本地算法版本、训练成果、转换成果一致；
- GC 是否不会删除仍被算法版本 / publication / conversion 引用的不可变产物；
- 所有失败恢复继续 fail-closed / idempotent；
- 每个正式提交继续从远端真实 VERSION 最小 patch +1。


## 2026-10-03 Training Material Picker / Annotation GT 筛选最终收口（最新）

本节生产代码 cutoff：

`dcf63cf2e56f49834bc08b5377d5bc5b6826b9f5`

正式版本：

`42.24.72`

该 cutoff 已确认 GitHub Actions **22 / 22 workflow runs 全部 completed success**，对应 **57 / 57 check-runs success**，failure / queued / in_progress 均为 0。

本交接提交本身只更新 `docs/codex-handoff.md` 并把正式版本最小 patch 递增到 `42.24.73`；不修改训练、标注、导入、调度、发布或转换生产逻辑。

### 1. CLOSED：Training Picker summary / test bulk-selection 已改读 AnnotationRepository

`42.24.69` 已关闭上一节尚未完成的 Picker 辅助统计 owner：

- `selection-summary` 的 eligible / pending / box / label counts 直接来自 `AnnotationRepository.training_ground_truth_summary()`；
- test role 的 bulk-selection 不再使用 MaterialRepository 的 `annotated` 投影判断 Ground Truth；
- full-pool totals 同时按 Material revision + Annotation revision 缓存；
- Annotation summary 使用 normalized `annotation_label_references`，不逐图 hydration boxes JSON；
- 大选择集合用 SQLite TEMP table，保持 10k / 20k / 50k 线性级处理边界；
- permanent guard 明确禁止恢复 `m.annotated <> 0` 或 `filters["annotated"] = True` 作为训练 GT。

### 2. CLOSED：Picker 标签筛选也已切到正式 Annotation GT

`42.24.71 ~ 42.24.72` 继续关闭了此前仍残留的最后一个 Picker 真相缺口：

- 卡片列表 `GET /training-materials` 带 label filter 时，不再读取 MaterialRepository 的 `material_labels` 作为标签真相；
- `GET /training-materials/ids` 带 label filter 时，同样改读正式 Annotation GT；
- `POST /training-materials/bulk-selection` 的 filtered label selection 同样改读正式 Annotation GT；
- test role 无 label filter 时，继续使用正式 annotated / confirmed_empty GT eligibility；
- MaterialRepository 仍只负责素材 identity / processing status / query / cursor paging，不成为 Annotation Ground Truth owner。

当前 GT-aware Picker 查询采用：

`materials.sqlite3`
→ SQLite `ATTACH annotations.sqlite3`
→ indexed `annotation_label_references`
→ 同一 read transaction 内计算 total + cursor page

因此没有新增：

- Python 全量逐图 JSON 扫描；
- N+1 AnnotationRepository.get()；
- 第二套 picker paging owner；
- 第二套 Annotation GT owner。

### 3. CLOSED：陈旧 Material annotation projection 不再影响训练素材筛选

回归测试已显式构造“Material projection 与正式 AnnotationRepository 真相相反”的场景：

- Material 仍显示 `smoke`，但 Annotation GT 已变成 unannotated：Picker 必须排除；
- Material 未显示 `smoke`，但 Annotation GT 已正式 annotated smoke：Picker 必须纳入。

当前以下三个入口全部按正式 GT 得到一致集合：

1. paged material cards；
2. filtered IDs；
3. bulk selection。

`42.24.71` 的 backend contracts、frontend contracts 与 Real Chrome 均已验证生产逻辑通过；该 HEAD 唯一失败是初版 source guard 误把卡片返回字段 `"labels": labels` 当成 Material label filter。 `42.24.72` 已把 guard 收窄到实际 filtering owner，最终 22 / 22 workflows 全绿。

### 4. 当前训练准确性主链继续保持成立

本轮没有改动训练资源 T0/T1/T2、Scheduler、Trainer 或 split owner。

当前继续成立：

- AnnotationRepository 是唯一 Ground Truth owner；
- training material picker / selection summary / label filters 使用正式 GT；
- 训练创建后仍会再次按 image_id 回读 AnnotationRepository；
- Source GT 与 Training Projection 继续分离；
- `source_annotation_hash` 继续进入 input freeze；
- new-label train-positive reserve 继续在 split 阶段保护新增标签正样本；
- grouped / duplicate component 不拆分；
- 20k split 使用 bitset + predecessor arrays，不恢复 O(N²) tuple 状态；
- Trainer 不重新规划 Batch / Workers / Cache / Precision。

### 5. 本轮完整版本推进

- `42.24.52`：durable ZIP bounded annotation scope；
- `42.24.53`：unscoped structured negative fail-safe；
- `42.24.54`：durable import / label governance fence；
- `42.24.55 ~ 42.24.56`：rollback regression contract 修正；
- `42.24.57`：canonical label governance truth；
- `42.24.58`：formal annotation writes / delete restore governance fence；
- `42.24.59 ~ 42.24.62`：legacy metadata / confirmed-empty / cleaning fixture 合同对齐；
- `42.24.63`：storage import GT commit governance fence；
- `42.24.64`：online feedback 正式 GT 原子提升；
- `42.24.65`：AI annotation active-label truth；
- `42.24.66`：标签治理 usage / preview 改读 AnnotationRepository；
- `42.24.67`：whole-label unify selection freeze 改读 AnnotationRepository；
- `42.24.68`：上一轮交接 / source guard；
- `42.24.69`：Training Picker summary / test bulk 改读正式 GT；
- `42.24.70`：GT summary SQLite snapshot 稳定化；
- `42.24.71`：Picker label filters 改读 Annotation GT；
- `42.24.72`：Picker GT source guard 精确化，全量 CI 绿；
- `42.24.73`：本交接文档提交。

### 6. 后续继续审计方向

当前没有已知需要立即修复的 Picker Ground Truth P0/P1 缺口。

下一轮如继续主流程审计，建议按真实调用链继续检查：

`dataset snapshot / input freeze`
→ `Trainer result`
→ `新畅联 publish`
→ `ONNX / RKNN conversion`
→ `OSS archive / public_url`

重点仍保持：

- 前后端合同一致；
- 不新增第二 owner；
- 不把 Material projection 反升格为 GT；
- 1k / 10k / 20k 性能不退化；
- queued / in_progress 永远不当 success；
- 每个正式提交继续从远端真实 VERSION 最小 patch +1。


## 2026-10-03 Annotation GT 治理 / 标签统一候选冻结收口（最新）

本节生产代码 cutoff：

`b6375376854cb66aae6339f4b42057443198ff4b`

正式版本：

`42.24.67`

该 cutoff 已确认 GitHub Actions **28 / 28 workflow runs 全部 completed success**，对应 **74 / 74 check-runs success**，failure / queued / in_progress 均为 0。

本交接提交本身只增加永久 source guard、更新交接文档并把正式版本最小 patch 递增到 `42.24.68`；不重新设计训练、标注、导入或标签治理架构。

### 1. CLOSED：durable ZIP / structured import annotation_scope 真相

`42.24.52 ~ 42.24.53` 已关闭本地 durable ZIP 主链的 scope 缺口：

- YOLO / COCO / VOC 正式入库时，`annotation_scope` 只来自用户已经确认的 `label_mapping` target；
- 有框图片与 `confirmed_empty` 使用相同 bounded imported scope；
- 普通图片 ZIP 没有 sidecar 时保持 `unannotated`，不能伪造 `confirmed_empty`；
- 空 YOLO txt / VOC XML / COCO annotations 若没有任何已确认 platform schema，不得自动扩大成项目全部 active labels；
- active v19 importer 不再在缺少确认 mapping 时隐式 `ensure_label()` / 自动创建 `object`；
- 若结构化文件实际存在正标注却没有确认 scope，则 fail-closed。

### 2. CLOSED：label governance TOCTOU 与 GT 写入 fence

`42.24.54 ~ 42.24.65` 已把标签状态变化与正式 GT 写入纳入同一治理边界：

- 项目级 `label_governance_fence` 为跨进程 FileLock，并支持同一执行上下文可重入；
- 标签新增、改编码、软删除、别名记忆、标签统一退役共享同一 governance fence；
- AnnotationRepository 的正式 upsert / batch upsert / remap / dataset-delete restore 在写 GT 前重新校验当前 active canonical label；
- `active=false` 与 `status != active` 使用统一 active-label 语义；
- dataset-delete 尚未完成时的 annotation backup 继续计入标签引用真相，不能趁 live row 暂时删除时错误退役标签；
- storage import 在最终 GT commit 前重新验证 frozen mapping target；
- online feedback 将素材创建 + 正式 GT 提升做成可回滚事务；
- AI annotation label catalog 已统一复用 canonical active-label helper。

AnnotationRepository 仍是唯一 Ground Truth owner；这些 fence 没有引入第二个 annotation owner、第二个 label owner 或第二套 remap runtime。

### 3. CLOSED：标签管理 UI / API 引用统计改为 AnnotationRepository 真相

`42.24.66` 已关闭“后台按 GT 拒绝、页面却按 Material projection 显示 0 引用”的前后端不一致：

- `GET /api/v54/projects/{project_id}/label-schema` 的 usage / box / scope / affected 统计直接来自 `AnnotationRepository.label_reference_usage()`；
- `POST .../labels/unify/preview` 直接来自 `AnnotationRepository.label_reference_preview()`；
- 不再用 MaterialRepository 的 `material_labels / material_annotation_scopes` 作为标签治理引用真相；
- 聚合是 SQLite 索引级一次查询，不做逐图 JSON hydration。

### 4. CLOSED：whole-label unify 候选冻结改为 AnnotationRepository live reference snapshot

`42.24.67` 已关闭此前“Material projection 陈旧导致统一任务漏选正式 GT”的问题。

当前 whole-label unify 创建链：

`v54 source/target active 校验`
→ `label_governance_fence`
→ `AnnotationRepository.live_reference_snapshot(source_labels)`
→ 冻结 `annotation_revision + image_ids`
→ 释放 governance fence
→ 分批验证 Material identity
→ 写入现有 `BatchSelection`
→ durable `REMAP_ANNOTATION_LABELS`

当前 selection audit 明确保存：

- `reference_owner = annotation_repository`
- `annotation_revision`
- `source_labels`
- `target_label`

如果正式 GT 引用存在但对应 Material row 已丢失，创建任务直接以 `MATERIAL_REMAP_ORPHAN_ANNOTATION` fail-closed，要求先做标签完整性审计，不能静默漏掉该 GT。

并发情况下，freeze 后若又新增旧来源标签 GT，最终 retirement gate 仍会再次检查 AnnotationRepository 与 Material projection 都清零，因此不会错误 retire source label。

### 5. 当前已审计确认仍成立的训练准确性合同

训练主链继续保持上一节的 CLOSED 合同：

- training label contract 的 selected material label truth 直接读取 AnnotationRepository；
- 训练素材 hydration 会按 image_id 分批回读 AnnotationRepository，把 `annotation_state / annotation_scope / annotation_hash / boxes` 覆盖到 task-local row；
- Source GT 与 Training Projection 分离；
- `source_annotation_hash` 继续进入 input freeze；
- split 仍按正式 `annotated / confirmed_empty` 语义判断 Ground Truth；
- 新增标签 train-positive reserve 与 20k split 近线性内存实现没有被本轮改动回退；
- Trainer / Scheduler / resource planner 的 T0/T1/T2 owner 没有变化。

### 6. 当前仍需继续审计：Training Material Picker 的辅助统计 owner

这里**尚未标记 CLOSED，也不要草率改成 Python 全量扫描**。

已确认：

- picker 当前页卡片会批量读取 AnnotationRepository，所以单张卡片上的 `annotation_state / boxes / training_state` 是正式 GT；
- 但 `selection-summary`、`bulk-selection(role=test)`、部分标签筛选总数仍依赖 MaterialRepository 的 `annotated / material_labels` 投影；
- 最终训练创建链会再次回读 AnnotationRepository，因此目前更偏向“选择器统计/体验可能与最终真相短暂不一致”，而不是最终训练 GT 被污染；
- 这一块涉及 cursor / total / 10k~20k 性能与 workflow permanent guards，不能用逐页 Python 扫描或逐图 `get()` 修补。

下一会话继续时，优先设计 SQLite 索引级 GT summary / filter 合同，再决定是否把 picker 的 summary / test bulk-selection 切到 AnnotationRepository；必须保持 server paging、50k selection 上限和无 N+1。

### 7. 本轮版本推进

- `42.24.52`：durable import bounded annotation scope
- `42.24.53`：unscoped structured negative fail-safe
- `42.24.54`：durable import / label governance fence
- `42.24.55 ~ 42.24.56`：rollback regression contract 修正
- `42.24.57`：canonical label governance truth
- `42.24.58`：formal annotation writes + delete restore governance fence
- `42.24.59 ~ 42.24.62`：旧测试 / cleaning / confirmed-empty fixtures 对齐新 GT 合同
- `42.24.63`：storage import GT commit governance fence
- `42.24.64`：online feedback 正式 GT 原子提升
- `42.24.65`：AI annotation active-label truth
- `42.24.66`：v54 标签治理统计 / preview 改读 AnnotationRepository
- `42.24.67`：whole-label unify selection freeze 改读 AnnotationRepository
- `42.24.68`：本交接 / permanent source guard

后续每个正式提交继续从远端真实 `VERSION.txt` 最小 patch +1；不要重新固定版本，也不要把 UI build metadata 当正式平台版本。



## 2026-09-30 标注 Ground Truth / 训练投影 / Split 准确性收口（最新）

本节生产代码 cutoff：

`86e629f0293cee2a42f56d9978158880d79e653a`

该 cutoff 正式版本为 `42.24.50`。当前 HEAD 对应 GitHub Actions 已确认 **25 / 25 runs 全部 completed success**，failure / queued / in_progress 均为 0。

本交接文档提交本身不改生产逻辑，只更新文档与正式版本；`VERSION.txt` 按用户要求继续以最小 patch 递增到 `42.24.51`。

### 1. 不再重做：训练资源 T0 / T1 / T2 与训练前端 owner 已 CLOSED

上一节已经收口并保持成立：

- TRAINING / TRAINING_PREPARE / Scheduler / canonical resource planner owner 唯一；
- Remote 与 Local AUTO 都在 concrete GPU assignment 后冻结真实 resolved contract；
- Trainer 不再二次规划 Batch / Workers / Cache / Precision；
- live `runtime_resources` 已通过 fenced heartbeat 回到控制端；
- 前端训练任务页、HTTP refresh、polling、recovery、创建弹窗均已有 canonical owner；
- 多代历史 training renderer / refresh / log / classic form helper 已物理退役。

本轮 `42.24.39 ~ 42.24.50` 的新增工作不是重新设计上述链路，而是继续收口 **Annotation Ground Truth、训练投影和 split 准确性**。

### 2. CLOSED：AI 人工审核现在保存明确 annotation_scope

AI Candidate -> 人工审核 -> Commit 到正式 AnnotationRepository 时，正式 scope 不再靠“当前项目全部标签”隐式推断。

当前合同：

- review scope 优先来自 task request，缺失时读取 candidate manifest 的 labels；
- scope 会先经过本次 label mapping 映射到当前 canonical active label；
- mapping 后目标已失效则 fail-closed；
- 正式写入时持久化 `annotation_scope`；
- 非 overwrite 时：保留旧 GT scope，并与本次 review scope 做并集；
- overwrite 时：只替换**本次 review scope 内**的历史框，不得误删其他类别；
- 即使本次 AI 结果为空，只要用户确认了该 scope，也必须持久化“该 scope 已审核为空”的正式真相；
- overwrite 把某个 review scope 的旧框删空时，也必须实际写回 AnnotationRepository，不能因为最终没有 incoming box 就漏掉删除。

因此现在“AI 没检测到 fire”只代表已审核的 fire scope 为负，不再错误扩展成“所有平台标签都为负”。

### 3. CLOSED：结构化导入只对用户确认映射过的标签负责

YOLO / COCO / VOC 等结构化导入完成标签映射后：

- `annotation_scope` = 用户明确确认的 platform target labels；
- 不再把“项目当前所有 active labels”写成该导入图片的审核范围；
- 正样本与 `confirmed_empty` 都保存相同的 bounded imported scope；
- mapping target 在 commit 时若已不是 active label，任务 fail-closed；
- 结构化标注若没有任何已确认 platform scope，不允许伪造正式 annotated / confirmed_empty 真相。

例如项目有 `smoke / fire / helmet`，某次数据集只映射了 `smoke / fire`，则导入负样本 scope 只能是 `[smoke, fire]`，不能把 `helmet` 自动当成负样本。

### 4. CLOSED：人工标注显式冻结人工审核范围

手工标注保存已把 `annotation_scope` 作为 AnnotationRepository 正式字段传入：

- 正常有框保存：scope 与当前人工审核标签集合一致；
- “确认无目标”：同样保存明确 scope；
- API reload / Material projection 与正式 AnnotationRepository 保持一致。

这避免后续训练、清洗、统一标签时把“框为空”误读成“对任意未来标签都确认无目标”。

### 5. CLOSED：Source GT 与 Training Projection 已彻底分离

训练允许“图片继续参与，但某些标签本次训练不让模型知晓”。因此 task-local training projection 可能把 source GT 中被排除标签的框隐藏，甚至把本次训练视角投影成 synthetic negative。

现在正式区分：

- `annotation_state / boxes / annotation_hash`：当前训练投影视角；
- `source_annotation_state`：投影前真实 GT 状态；
- `source_annotation_hash`：投影前真实 AnnotationRepository identity；
- `source_labels`：投影前真实标签集合；
- `training_projection_policy / training_projection_digest`：本次训练投影证据。

关键规则：

- 第一次 projection 先冻结 source identity；
- 对已经投影过的 task-local row 再次 projection，不得把 synthetic negative 反过来当成 source GT；
- input freeze 必须继续携带 `source_annotation_hash`；
- online feedback / supplement provenance 校验优先比对 source annotation identity，而不是误拿训练投影 hash；
- training projection 永远不得反写 Material / AnnotationRepository Ground Truth。

因此“本次训练不选择 person”只影响本次训练输入，不会把素材库真实 person 标注删除或改成负样本。

### 6. CLOSED：本次新增训练标签必须在 train split 中有正样本

标签合同现在显式记录：

`requested_new_label_codes`

语义：

- 首次训练时，用户本次选中的标签都属于 new labels；
- 迭代训练时，只有本次相对 inherited schema 新增的标签属于 new labels；
- inherited-only label 不强制每次都必须有 train positive，但会保留质量 warning。

最初已增加 fail-closed gate：若 new label 最终只落在 validation/test，没有 train positive，则训练拒绝启动。

当前 HEAD 又进一步优化为**在 split 生成阶段主动保护 new-label positive component**：

- 在候选训练池中先为每个 required new label 找到正样本 component；
- 这些 component 被保留在 train，不参加 validation/test 抽取；
- 多标签同一 component 时优先用能覆盖更多尚未满足标签的 component；
- 仍然遵守 group / duplicate component 不可拆分约束，避免数据泄漏；
- 若 new label 的正样本根本不存在，或只存在于独立 test set，则明确 fail-closed；
- split manifest 记录 `required_train_labels` 与 `reserved_train_component_count`，便于审计。

结果：不会再出现“用户刚新增 smoke 标签，但唯一 smoke 正样本随机被划到 validation/test，导致模型训练阶段完全看不到 smoke”的情况。

### 7. CLOSED：20k 规模随机 split 内存已收口

旧 grouped split 为每个 reachable total 保存完整 selected-index tuple。大量 singleton component 时会形成接近二次增长的 Python tuple 状态，在 1 万～2 万素材规模下会放大训练前内存与延迟。

当前实现改为：

- Python integer bitset 保存 reachable totals；
- predecessor arrays 保存首次到达路径；
- 最终只对选中的 total 回溯 component；
- 仍保持 exact grouped subset semantics、目标比例选择规则和不可拆分 component 约束。

因此 split 计算的 Python-side 状态已改为受控的近线性内存，不再为每个 reachable total 复制整条索引 tuple。

### 8. CLOSED：清洗标注审计统一使用 canonical active-label 语义

`annotation_quality` 不再自己维护“disabled/inactive”简化判断，而是复用 canonical `active_label_options`。

现在以下标签都会被视为非 active：

- `merged`；
- `deleted`；
- `active=false` 的兼容历史数据；
- 其他 canonical helper 判定为非 active 的状态。

这与标签治理、训练 preflight、统一标签语义保持一致，避免清洗审计把已合并/删除标签继续当成有效类别。

### 9. 版本推进记录

本轮从上一生产 cutoff 后连续推进：

- `42.24.39`：AI review annotation scope；
- `42.24.40`：structured import annotation scope；
- `42.24.41`：manual annotation review scope；
- `42.24.42`：20k training split memory；
- `42.24.43`：source GT / training projection truth 分离；
- `42.24.44`：input freeze 携带 source annotation identity；
- `42.24.45`：new label train-positive gate；
- `42.24.46`：重复 training projection 保持 source GT；
- `42.24.47`：AI overwrite 按 review scope 替换；
- `42.24.48`：cleaning audit active-label truth；
- `42.24.49`：AI overwrite 删除到空也正式持久化；
- `42.24.50`：split 主动保留 new-label train positives；
- 本交接提交：`42.24.51`。

不要恢复任何“版本固定不动”的旧测试合同。

### 10. 当前 CI 真实边界

生产代码 cutoff：

`86e629f0293cee2a42f56d9978158880d79e653a`

当前该 HEAD 共触发 25 个 workflow runs，全部 completed success：

- Frontend Runtime Stabilization；
- Training Input Integrity（push + PR）；
- Training Create First Open；
- Remote Training Runtime（push + PR）；
- Node Agent Executor；
- Task Runtime Truth；
- GPU Runtime Truth；
- Label Normalization Contract（push + PR）；
- AI Annotation Recovery；
- Remote Material Import；
- Remote Cleaning Runtime；
- Remote Conversion Runtime；
- Remote RKNN Board Runtime Protocol；
- Central Node Assignment；
- Resource Discovery SQLite Stability；
- Online Feedback Runtime；
- Storage Cache Governance；
- External Algorithm Publish（push + PR）；
- External Algorithm Platform；
- ChangLian Login Auth；
- Portable Deployment；
- Video Frame Recovery。

当前 failure / queued / in_progress 均为 0。

### 11. 下一会话从这里继续

新会话第一步必须重新读取：

1. `origin/feature/external-algorithm-publishing` 当前真实 HEAD；
2. `VERSION.txt`；
3. 最近至少 20 commits；
4. 当前 HEAD GitHub Actions / check-runs；
5. 所有 completed failure 的真实 job log；
6. `docs/codex-handoff.md` 最顶部本节；
7. 本轮涉及的 AnnotationRepository / annotation_scope / training projection / split 代码与测试。

不要重新做已 CLOSED 的 T0 / T1 / T2。

后续优先继续检查主流程正确性与性能：

- 批量素材导入 -> 正式 annotation_scope 是否始终准确；
- 人工标注 / AI 标注 / AI 审核是否始终只写 AnnotationRepository 正式 GT；
- 标签统一 / merged label / cleaning audit 是否和 active-label canonical helper 一致；
- 训练 label contract -> projection -> split -> input freeze -> snapshot 是否前后一致；
- 首次训练与迭代训练的新标签正样本、继承标签、负样本语义是否正确；
- 1k / 10k / 20k 数据规模下 split、annotation read、freeze 的内存与延迟；
- 新畅联发布链、转换结果追加权重、OSS 归档继续保持既有 owner。

约束继续保持：

- 不 merge main；
- 不 tag；
- 不 release；
- 不 force push；
- 不新增第二套 planner / scheduler / TaskRepository / PollRegistry / TrainingTaskRuntime / Annotation Ground Truth owner；
- 不删除或放宽测试；
- queued / in_progress 不得写成 success；
- 每个正式提交继续最小 patch 递增版本号。



## 2026-09-30 训练资源真相 / Local AUTO / 前端 Owner / 版本治理最终收口（最新）

本节生产代码 cutoff：

`f9ed2e0857ab52938ba057e1a185d96a4fb30edd`

该 cutoff 的正式版本为 `42.24.37`，GitHub Actions 已确认 **21 / 21 workflows 全部 success**，failure / queued / in_progress 均为 0。

本交接文档提交后，`VERSION.txt` 继续按用户要求以最小 patch 递增到 `42.24.38`。后续每个正式提交继续递增 patch；不要再恢复“VERSION.txt 永远固定 42.24.0”的旧约束。

### 1. T0 CLOSED：训练资源只有一个 planner，Trainer 不得二次规划

正式 owner：

- TRAINING parent：用户可见训练生命周期真相；
- TRAINING_PREPARE：输入 / 标签 / snapshot / resource admission；
- Scheduler：节点 / GPU assignment；
- canonical planner：`platform_core.training_metrics.resolve_resources`；
- remote Agent：在真实节点 / 真实 GPU assignment 后调用同一个 canonical planner；
- local TrainingHandler：仅在需要 deferred AUTO 时，于 concrete assignment + reservation 后调用同一个 canonical planner；
- `train_worker.py`：只消费 frozen resolved contract，禁止再次决定 Batch / Workers / Cache / Precision。

远程链：

`Scheduler assignment -> Agent 真实 GPU identity -> canonical resolve_resources -> resolved-resources.json -> fenced heartbeat 投影控制端 -> Trainer spawn`

本地 AUTO 链：

`TRAINING_PREPARE resource admission -> Scheduler concrete GPU assignment/reservation -> TrainingHandler assignment fence -> canonical resolve_resources -> fenced resolved-resources.json -> Trainer spawn`

MANUAL 始终是硬约束；AUTO 请求值只是 preference，可安全向下决议。训练启动后不存在隐藏 OOM Batch retry / 第二 planner / Trainer runtime auto-replan。

### 2. T1 CLOSED：运行中实际 Runtime 资源实时回到控制端

Agent 在 Trainer 已启动并得到真实 runtime resource 后，通过现有 fenced execution heartbeat 投影：

- Batch；
- Workers；
- Cache；
- Precision；
- Device；
- node_id；
- execution_generation。

控制端要求 runtime truth 与 frozen resolved contract 完全一致；不一致返回 `REMOTE_RUNTIME_RESOURCES_MISMATCH`，不得静默继续。

控制端持久化：

- `resolved-resources.json`；
- `runtime-resources.json`。

训练详情 API 以 task-owned artifact 覆盖陈旧 worker snapshot；前端明确区分：

`requested_resources -> resolved_resources -> runtime_resources`

AUTO 允许 requested Batch 128 -> resolved Batch 32 -> runtime Batch 32；绝不能出现 resolved 32、Trainer 私自变成 16。

### 3. T2 CLOSED：Local AUTO 已改为具体 GPU assignment 后单次 freeze

旧债“本地 AUTO 在 scheduler 选定具体 GPU 前按保守 GPU 规划”已经关闭。

当前行为：

- Local TRAINING_PREPARE 对 scheduler-owned AUTO 不再提前生成最终 `resolved-resources.json`；
- prepare 只冻结 admission 证据与候选 GPU 范围；
- TrainingHandler 拿到具体 assignment 后，先验证：
  - assignment task / worker / lease；
  - GPU reservation task / lease；
  - assigned GPU UUID；
  - 当前真实 CUDA device UUID；
- 验证通过后才调用同一个 `training_metrics.resolve_resources`；
- resolved artifact 通过 fenced artifact store 发布，stale execution 不能覆盖新 generation；
- Scheduler 在 handler 执行期间有独立 lease-renewal heartbeat；GPU reservation 由 task heartbeat trigger 同步续期，因此 resolver 较慢时不会因为默认 lease 到期丢 reservation；
- GPU AUTO assignment 已按 idle / low-pressure / capacity 选择，不再简单被最小显存 GPU 永久限制吞吐。

这项优化没有新增第二 planner、第二 GPU reservation owner 或 Trainer runtime replan。

### 4. T2 CLOSED：训练前端只剩 canonical owner

当前唯一训练页面与运行时 owner：

- 页面导航：`main.mjs NavigationStability`；
- 页面 renderer：`TrainingTaskVisibilityRuntime.render()`；
- HTTP refresh / task mutation：`TrainingTaskRuntime`；
- polling / elapsed clock：`PollRegistry`；
- 训练详情 / 日志 / recovery：`TrainingRecoveryRuntime`；
- 创建弹窗：`openTrainingCreateCanonical429 -> openTrainingCreateDialog429 -> TrainingDraftRuntime`。

已物理退役并加 source guard 的历史实现包括：

- v423 / v424 / v425 多代 training task-list renderer；
- 旧 training create modal / submit alias；
- 多代 training log modal；
- `renderTrainingCompatibility`；
- `trainJobRowsHtml / updateTrainingJobTable / refreshJobsOnly`；
- PollRegistry 对 `refreshJobsOnly` 的 fallback；
- 早期 `stopJob / deleteJob / showLog / pollActiveLog`；
- `fillTrainLegacy / applyAlgLegacy / showLogLegacy`；
- 最后的 `curTarget / fillTrain / applyAlg` 经典训练表单 helper。

现行训练算法选择直接写入 `TrainingDraftRuntime.update({algorithmId})`，不再依赖旧 `#alg / #model / #epochs / #paddle_eval` DOM。

### 5. 前端首屏旧导航 repaint 已关闭

历史 `navs` 假导航库存已经没有消费者，但曾在启动时：

- 追加“检测台”；
- 追加“视频切帧”；
- 通过 `setTimeout(...renderNav(), 0)` 强制再绘制一次导航。

这套状态与 0ms repaint 已物理删除。最终菜单仍由 canonical navigation owner 渲染。

Real Chrome 回归已验证删除后首开、导航、训练任务页等行为正常。

### 6. 版本治理已可持续

当前规则：

- `VERSION.txt / backend APP_VERSION` = 正式平台版本；
- `static/main.mjs::UI_BUILD_VERSION = 42.25.0-dev` = UI build metadata，不是正式版本；
- cache-bust query 也不是正式版本号；
- workflow / 测试不再写死 `VERSION.txt == 42.24.0`；
- `platform_core.build_identity` 校验正式版本必须为三段 `MAJOR.MINOR.PATCH`，并禁止退回旧 floor；
- 顶部 version badge 与 sidebar footer 从 backend bootstrap `platform_version` 获取，不再静态写死。

本轮正式版本已经从 `42.24.0` 连续推进到 `42.24.37`；本交接提交继续到 `42.24.38`。

### 7. 当前 CI 真实边界

生产代码 cutoff `f9ed2e0857ab52938ba057e1a185d96a4fb30edd`：

- workflows：21；
- success：21；
- failure：0；
- queued：0；
- in_progress：0。

重点已确认 success：

- Frontend Runtime Stabilization：
  - Frontend unit tests success；
  - Real Chrome runtime regressions success；
- Remote Training Runtime success；
- Node Agent Executor success；
- Task Runtime Truth success；
- GPU Runtime Truth success；
- Central Node Assignment success；
- Training Input Integrity success；
- Label Normalization Contract success；
- Remote Conversion Runtime success；
- External Algorithm Publish success；
- External Algorithm Platform success；
- Remote Material Import success。

前几轮红灯均已定位为过期测试合同，而不是生产回归；最终 cutoff 已重新跑到全绿。

### 8. 仍需注意的边界

训练主链 T0 / T1 / T2 当前没有已知 correctness blocker。

仍然存在的工程现实：

- `static/app.js` 历史体积仍大，其他非训练页面还有 legacy helper；不要为了“清文件”做大规模重写；
- 继续遵守 owner-by-owner、先证明 zero-reference 再删除的方式；
- 不要重新引入第二 PollRegistry、第二 TrainingTaskRuntime、第二 planner、第二 scheduler 或第二 task owner；
- 不要把 UI build version 当正式版本；
- queued / in_progress 永远不能写成 success。

### 9. 后续优先级

1. 不再重做 T0 / T1 / T2；
2. 后续训练问题优先查 canonical task truth、assignment/reservation fence、TrainingTaskRuntime / PollRegistry；
3. 继续主流程质量时，优先训练准确性、素材导入、清洗、标注、AI 审核、新畅联发布链；
4. 老前端技术债只按真实调用链小步清理，不做大爆炸式重构；
5. 不 merge main、不 tag、不 release、不 force push。


## 2026-09-29 Platform Browser Runtime Contract（最新）

- 平台核心浏览器流程同时支持 HTTP 与 HTTPS；核心业务不得以 secure context 为前提，HTTPS-only API 只能作为显式 capability-detected 增强能力；
- 唯一浏览器能力与客户端随机 ID owner 为 `static/browser-runtime.js` / `window.BrowserCapabilityRuntime`，提供 `capabilities()`、`has()`、`browserRandomHex()`、`createClientId()`；随机优先级固定为 `crypto.randomUUID -> crypto.getRandomValues -> timestamp + monotonic counter + 多段 random fallback`；
- 训练 task ID、手工标注框 ID、素材上传 durable request seed 与 UploadTaskCenter 本地 task ID 均复用该 owner；训练 ID 继续严格遵守 `^train_[0-9a-f]{16,32}$`，服务端 canonical generator/validator 不放宽；
- 静态审计共发现 6 个 secure-context-sensitive 直接使用点：4 个 `randomUUID`（训练、素材上传、两个标注定义）与 2 个 `navigator.clipboard`。4 个随机 ID 调用已收口；2 个剪贴板调用明确降级为手工复制，不影响核心流程；`getRandomValues` 继续作为 HTTP 主 fallback；
- `serviceWorker / getUserMedia / geolocation / Notification / showOpenFilePicker / showDirectoryPicker / SharedArrayBuffer` 在生产前端没有核心业务调用；runtime 只报告能力，不启用第二套业务流程；
- 浏览器到平台的登录、训练、标注、上传、任务轮询与 SSE 继续使用同源相对 URL；训练 SSE 为 `/api/v64/.../training-events`，不写死 `http/https/ws/wss`；
- mixed-content 收口：label-review 样例与普通远端素材 content 不再把浏览器直连/307 到 Provider 预签名地址；浏览器只访问同源 content route，由现有 StorageManager 在后端读取/缓存远端 HTTP、OSS 或其他 Provider；
- Cookie 合同保持：直连 HTTP `Secure=false`，直连 HTTPS `Secure=true`，反代 `X-Forwarded-Proto=https` 时 `Secure=true`；没有为了 HTTP 支持而降低 HTTPS Cookie 安全位；登录与 session redirect 不重写协议，HTTP/HTTPS 切换使用当前 origin；
- 永久合同：`tests/frontend/browser-runtime-compatibility.test.mjs`、`tests/unit/test_http_https_browser_contract.py`，并更新直接相关 training/material/annotation/cache guards 与 material content API tests；
- `VERSION.txt` 仍为 `42.24.0`，未修改。


## 2026-09-29 训练 Task ID canonical contract（最新）

- 根因：普通训练弹窗在 `crypto.randomUUID()` 不可用时仅执行一次 `Math.random().toString(16)`，生成的 suffix 可能不足 16 位；服务端却严格要求 `train_[0-9a-f]{16,32}`，同时服务端无请求 ID 时又生成裸 12 位 hex，形成前后端合同不一致；
- 当前唯一语义：所有训练 Task ID 均为 `train_` 前缀加 16～32 位 lowercase hex；后端继续 fail-closed，不放宽正则；
- 浏览器 canonical helper 优先 `crypto.randomUUID()`，其次 `crypto.getRandomValues()`，两者均不可用时拼接三个独立 32-bit `Math.random` 片段，最终统一生成 24 位 hex suffix，并用同一个 validator 自检；普通训练弹窗不再直接生成 ID；
- 服务端自动生成统一为 `train_` 加 24 位 UUID hex，不再产生裸 12 位 task ID；
- iteration action 原有固定幂等 ID 保持不变，但提交 owner 会用同一 validator 在 POST 前校验；历史 ID 不合法时明确提示“历史迭代任务 ID 格式异常”，不会向后端发送请求；
- 永久前端合同覆盖 randomUUID、getRandomValues、最终 fallback，以及 iteration 非法 ID 的无网络 fail-closed；服务端合同覆盖自动生成 ID 的 canonical 格式。


## 2026-09-29 标签完整性 Full Audit / 批量 Repair（最新）

本轮没有重做训练标签架构，也没有新增 TaskKind、Scheduler、Ground Truth 或轮询 owner。新增能力落在现有标签管理与 durable material-batch runtime：

- 本次生产 `9 张 / 0 框 / INCOMPLETE_MERGE` 的代码级根因已经关闭：`_active_project_labels()` 曾采用“仅排除 disabled/inactive”的错误判断，把 `merged` 也放入 current active 集合；历史 `confirmed_empty + scope_json=[]` 因而通过 empty-scope fallback 动态重新得到 merged labels。现在统一复用 canonical active helper，只有 `status == active` 且兼容字段 `active != false` 的标签能进入 fallback；merged/inactive/deleted/orphan 均不会被重新制造；
- Full Audit 对历史空 persisted scope 读取同一个 AnnotationRepository effective fallback；含真实 persisted merged scope 的记录仍会报告并可修复，但只由 fallback 生成的假 `INCOMPLETE_MERGE` 会直接消失；7-source fixture 覆盖 merged chain、一次 durable repair、修复后连续两次 Full Audit 为零；
- label-integrity repair admission 的 `active repair check -> current GT reread/freeze -> artifact prepare -> TaskRepository.create` 现在全部位于同一个项目级 FileLock critical section，关闭 check/create 竞争窗口；普通 MaterialBatch 不受该 gate 影响；
- worker 仍保留 digest CAS：digest 改变且任何本 task source 仍存在时继续 `ANNOTATION_CHANGED_DURING_REMAP`；如果重新只读当前 GT 后所有 task source 已不存在，则不写 Annotation、不覆盖当前 GT，记为 `noop_resolved` 并合并计入 `already_resolved`；
- UI 对 `ORPHAN_LABEL` 继续要求查看样例并手工选择；对已有治理链的 `INCOMPLETE_MERGE` 明确说明目标来自历史合并关系，不再提示用户重新猜语义。

- Full Audit operation：`AUDIT_LABEL_INTEGRITY`，继续使用 `TaskKind.MATERIAL_BATCH / MaterialBatchHandler / TaskRepository / ArtifactStore / Scheduler`；
- Full Audit 是项目级审计，创建与运行都不生成 `selection.sqlite3`，也不伪造 `FILTERED=全部素材`；
- 真相读取顺序固定为：`AnnotationRepository -> current label governance -> MaterialRepository projection`；
- `AnnotationRepository` schema v2 增加 owner 内部派生引用索引 `annotation_label_references`，索引 boxes 与所有 annotation state 的 `annotation_scope`，并由 SQLite triggers 覆盖 upsert/remap/delete/restore；Full Audit 会显式 reconcile SQLite + legacy `annotations/*.json`；
- `MaterialRepository` schema v4 将 annotated scope 也纳入 projection index，但它只用于对账和普通 unify selection，不充当 Annotation truth；
- 审计快照：task artifact `label-integrity.sqlite3`，包含 `audit_metadata / audit_summary / annotation_references / issues / issue_groups`，保存 annotation revision/fingerprint、material revision、governance fingerprint、affected IDs、box/scope counts 与 class-id distributions；
- 快照只用于 UI 与 repair candidate 范围，不是 repair authoritative truth；
- 标签完整性 UI 允许一次配置多组 `source -> active target`，只提交已配置项，并统一创建一个 `REMAP_ANNOTATION_LABELS` durable task；不会为每个 source 创建并发任务；
- 创建 Repair 时，服务端按 audit candidate IDs 重新读取当前 AnnotationRepository；按 `image_id` 聚合该图仍相关的全部 mappings，同一 image 只写一条 selection，并保存 `source_digest/expected_digest/mappings/target_canonical_identities/result_digest/planned_at/audit_task_id`；
- worker 对每个 image 一次应用全部 bbox/scope mappings、一次 CAS、一次 AnnotationRepository write；多个 source 指向同一 target 时 scope 由 owner 归一去重，随后同步 MaterialRepository projection；
- audit 后已经人工处理的记录计入 `already_resolved`，不会进入 selection，也不会被覆盖；
- target 必须在 repair 创建时仍为 active；worker 再次校验每个 target identity 与 annotation digest，变化即 fail-closed；
- 项目级 label-integrity repair gate 只阻止同项目第二个 active repair，不阻塞其他 MaterialBatch；外部人工并发仍以 `ANNOTATION_CHANGED_DURING_REMAP` 失败关闭；
- 普通 whole-label unify 自动退役 source 前，必须同时满足 AnnotationRepository boxes/scopes=0 与 MaterialRepository labels/scopes=0；任意一侧残留都阻止 `status=merged`；
- 标签管理页原位增加“标签完整性”，不新增一级菜单；Full Audit 和 repair 都复用既有 PollRegistry/material-batch task truth；训练创建弹窗没有增加 audit/repair UI；
- Full Audit 负责发现异常，样例预览辅助人工判断语义，系统永远不自动猜 ORPHAN_LABEL target；样例候选来自 audit artifact 的 affected image IDs，但展示时只读当前 AnnotationRepository，并只叠加 source label 的历史 bbox，图片继续复用现有素材缩略图/content owner；
- `INCOMPLETE_MERGE` 在 issues API 中由服务端沿历史 `merged_into` chain 解析到最终 active target，UI 可见并默认预填最终 target 与历史链；`ORPHAN_LABEL` 始终保持未选择，必须人工结合样例判断；
- 训练 fail-closed 提示会引导用户前往“标签管理 → 标签完整性”。

生产历史异常的安全处理顺序：

1. 在“标签管理 → 标签完整性”运行 Full Audit；
2. 一次性配置所有要处理的 source：ORPHAN_LABEL 由用户人工决定 target，INCOMPLETE_MERGE 默认使用历史 `merged_into` chain 的最终 active target；未配置项可留到下一轮；
3. 点击“统一创建后台修复”，服务端重新读取当前 GT，并报告 `candidate_images / still_requires_repair / already_resolved / mapping_count`；
4. 服务端按 image_id 聚合 mappings，一个 durable task 对每张图只做一次 expected-digest CAS/write，再同步 projection；
5. 完成后 UI 明确要求重新运行 Full Audit；旧 audit 视为过期，直到 Annotation truth、governance 与 material projection 对账清零。

`VERSION.txt` 未修改。未 merge main、未 tag、未 release、未 force push。


## 2026-09-29 训练标签创建交接补充（当前状态）

详细交接已刷新：

`docs/CODEX_HANDOFF_2026-09-29_TRAINING_CREATE_LABELS.md`

本轮已按用户最终要求收口：

- 正式标签统一后，新训练任务真正使用 canonical target，不让 merged source 重新进入 effective training schema；
- 训练创建弹窗不再承担素材标签历史审计；
- 首次训练不显示“上一版本继承”；
- 迭代训练保留“上一版本继承”，数据来自服务端 canonical preview；
- inherited labels 改为横向 pill/chip + flex-wrap，高级、紧凑、对称；
- “本次素材标签”保留但默认不自动选择；
- Training Material Picker 已收敛成单一 project-owned owner；
- 标签统一/新训练 session 会失效旧 selected-material summary，避免同一批素材继续显示统一前旧标签。

当前远端 HEAD 在本文补充提交前已推进到：
`b46fa8fd5557cef2cef81e38b2074940cb08277b`
（`docs: refresh training label handoff state`）

`VERSION.txt = 42.24.0`，未修改。

CI 边界：
- Label Normalization Contract：当前相关 HEAD 已有 completed / success；
- Training Input Integrity：当前相关 HEAD 已有 completed / success；
- Frontend Runtime Stabilization：交接时仍有最新 run 在执行；
- Training Create First Open：新会话必须重新读取最新 Ubuntu / Windows / Real Chrome 终态；
- queued / in_progress 不得写成 success。

新会话不要重新设计标签体系，也不要恢复 merge history audit 到训练弹窗；第一步先重读真实 HEAD / checks / failure logs。



## 2026-09-29 训练创建标签语义 / 弹窗简化与继承标签横排（最新）

详细交接见：

`docs/CODEX_HANDOFF_2026-09-29_TRAINING_CREATE_LABELS.md`

本节功能代码 cutoff：

`dccff9f72ccef03b5937cad7dd29dfe94de60b0b`

随后仅有测试 build/cache guard 对齐：

- `9918f15ff5088ce1652d1bc30b6adccea42f7d62`
- `ec4fca762f805442bcf55515292a730c37c79dd6`

`VERSION.txt = 42.24.0`，未修改。

### 用户最终产品要求

1. 正式标签统一后，新训练任务真正使用的 schema 只能是统一后的 canonical target；已 merged 的历史 source 不得重新进入模型训练。
2. 创建训练任务弹窗不承担素材标签历史审计；不展示 merge chain / merged_into / source history / dropped history。
3. 首次训练无上一版本，不显示继承区。
4. 迭代训练保留“上一版本继承”，由服务端返回 canonical inherited labels，自动继承、不可取消。
5. “上一版本继承”改为横向 pill/chip + flex-wrap，不再纵向堆叠；UI 紧凑、对称、有层次。
6. “本次素材标签”继续保留，但默认不选，由用户明确决定是否新增类别。
7. 前端只展示服务端真相，不再实现第二套历史 merge resolver。

### 当前实现真相

后端 `platform_core/training_label_tasks.py` 是训练标签最终 owner：

- previous verified version frozen `label_schema` 作为继承输入；
- current label governance 对历史 merged label 做 `source -> target` canonical 投影；
- 多 source 合一 target 时去重；
- inactive/missing 且无明确 merge target 时 fail-closed；
- effective schema = canonical inherited + 用户显式选择且由真实 selected training GT 证明的新标签；
- training class_id 重新连续为 `0..N-1`；
- canonical_project_class_id 独立保留；
- schema 变化时仅上一版本权重初始化，不 strict resume optimizer；
- 历史算法版本 schema 不修改。

因此：**正式“标签统一”成功、source 已退休为 merged 后，新训练任务实际训练 schema 只使用统一后的 canonical target。**

前端 `static/modules/training-labels.js` 当前：

- 不再拥有 `resolveInheritedGovernance / merged_into / mergedInherited / droppedInherited / governanceBlockedInherited / inherited_from_codes` 等历史审计；
- inherited preview 只调用服务端：
  `/api/v62/projects/{project_id}/training-labels/inherited`
- 迭代训练显示“上一版本继承”；
- inherited labels 为横向 `.training-label-base-list` flex-wrap pills；
- 本次素材标签默认不选；
- 已被继承的标签不会重复要求用户选择。

### 之前“统一后弹窗仍出现旧标签”的处理

排查不是只修一个 UI cache：

1. Training Material Picker 已收敛成单一 project-owned route：
   `0ae6b8def40884e5ec00e81b125034bd7fa3a808`
2. selected-material summary 的前端 cache 有 explicit invalidate；
3. 新训练 session 与标签 mutation/unify 完成后都会失效旧 summary；
4. Real Chrome 已有：
   `same selected materials reload canonical labels after a completed label unification`
5. 最终训练 schema 仍由 server-authoritative label contract 冻结，不信任浏览器 preview。

### 当前 UI 关键提交

- `de61947f...` — server owns training label inheritance
- `d55dac1c...` — simplify training label creation UI
- `d2eab79b...` — lock simple training label creation
- `34c2a3d1...` — align simplified label UI
- `b9ee4f60...` — expose canonical inherited labels
- `aff49e44...` — polish inherited training labels
- `dccff9f7...` — lock compact inherited training labels

### 当前 CI 边界

在 `dccff9f...` 上：

- Training Material Picker contracts：completed success；
- Training Create First Open Windows contract：completed success；
- Training Create Real Chrome / Ubuntu 当时仍未全部终态；
- Frontend Runtime Stabilization 的两个 failure 已确认只是 stale build/cache guard：
  - `main.mjs 42.25.252 -> 42.25.253`
  - `training-draft-runtime-422517 -> 422518`
- 已分别由 `9918f15f...`、`ec4fca76...` 精确对齐；没有删除/放宽测试。

文档提交会继续推进 HEAD。新会话开始时必须重新读取远端 HEAD / checks；queued/in_progress 不得当 success。



## 2026-09-28 最终主流程发布链跨阶段验收 CLOSED（最新）

- 本节代码 cutoff：`115b506f42bd730ff8694b64e6cbca3d72ae0416`（`test: stitch training and RKNN publish chain`）。
- `VERSION.txt = 42.24.0`，未修改。
- 本轮没有新增 Training / ModelArtifact / ExternalPublish / Conversion owner；只补跨阶段永久合同与 CI guard。
- 没有 merge main、tag、release、force push，没有删除/放宽已有测试。

### 1. 最终主流程代码 / CI 结论

当前主流程：

`素材 -> 清洗 -> 标签治理 -> 标注 -> 训练 -> 算法版本 -> 算法产物归档 -> 新畅联算法版本 + 原始权重 -> RKNN 转换 -> 转换权重追加`

在代码与自动化层已经 **CLOSED**。

此前各段已分别完成：
- 普通图片 1k / 10k / 20k 上传：durable chunk idempotency + ambiguous-response recovery；
- ZIP 10k genuine acceptance + 20k bounded contract；
- 导入 → AnnotationRepository Ground Truth；
- confirmed_empty / 人工标注；
- AI Candidate Review / durable Commit；
- 清洗 / 标签统一 / merged label iteration；
- Training Input Integrity / Training Handler / remote training；
- ModelArtifact 独立算法产物存储；
- External Algorithm Publish；
- Remote Conversion / RKNN board protocol。

### 2. 本轮补的最后一个跨阶段接缝

此前每个阶段已有大量单独合同，但缺少一个永久测试把“训练发布请求”和“转换晚到追加权重”通过**同一个 External Publish owner**串在一起。

新增：

`test_publish_owner_stitches_training_request_and_late_rknn_weight`

它真实复用当前代码 owner，验证：

1. 外部算法版本已具备成功训练模型；
2. `request_external_auto_publish_if_enabled(...)` 写下训练完成 publish request；
3. 现有 auto-publish owner 扫描该版本；
4. 原始模型先进入 canonical ModelArtifact storage；
5. 创建且只创建 1 个新畅联 algorithm version；
6. 创建原始 `best.pt` weight；
7. 后续 RK3568 转换产物到达；
8. `request_external_auto_publish_for_conversion_if_enabled(...)` 再次唤醒同一个 owner；
9. 再次自动发布时**不重复创建 algorithm version**；
10. 只追加第二个 RKNN weight；
11. 新 weight 的 `chipCode = RK3568`；
12. 原始 weight 与 RKNN weight 均绑定同一个远端 `algoVersionId`；
13. 完成后 `publication_requires_sync(...) = false`。

Training Handler 是否发出 publish request、Conversion finalize 是否发出 conversion publish request，仍分别由原有 integration / unit tests 锁定；本轮没有复制它们的实现。

### 3. 原始模型与转换模型发布语义再次确认

当前正式语义：

- 训练成功并成功 attach 本地算法版本后，才允许请求自动发布；
- 新畅联算法版本创建前，原始模型必须先满足 ModelArtifact 长期存储 / public URL 可交付；
- OSS / ModelArtifact 上传失败必须发生在远端 algorithm version 创建之前，避免“远端空版本”；
- 转换仍在运行时，不阻塞训练版本和原始权重先发布；
- RKNN 转换晚到后，通过同一 publication owner 对已发布版本追加 weight；
- `blocked_by_hardware` 但已真实产出 RKNN 文件的转换成果仍可以作为转换 weight 追加，硬件板端验证状态不抹掉已完成转换产物；
- `blocked_by_environment` 且没有成功转换产物时不会触发转换发布；
- RKNN 当前支持芯片身份保持 `RK3568 / RK3578 / RK3576`，未加入 RK3588；
- 多个具体 Rockchip 芯片的 artifact identity 包含 chip_code，同 SHA 也不会错误合并成一个芯片产物；
- 重复 publish / timeout recovery 均不得重复创建远端版本或权重。

### 4. 当前 cutoff 的真实 CI

对 `115b506f42bd730ff8694b64e6cbca3d72ae0416`：

- External Algorithm Publish push `36420891449`：success
  - backend contract：success，日志 `151 passed in 8.78s`
  - Real Chrome：success
- External Algorithm Publish PR `36420898112`：success
- Remote Training Runtime `36420897835`：success
  - API success
  - Ubuntu preparation success
  - Windows preparation success
  - Ultralytics loader contract success
- Remote Conversion Runtime `36420897768`：success
  - Ubuntu agent contract success
  - Windows agent contract success
  - control-plane success
  - Real Chrome success
- Remote RKNN Board Runtime Protocol `36420897750`：success
  - API / Ubuntu / Windows / Real Chrome 全 success
- Training Input Integrity `36420897845`：success
  - Ubuntu / Windows JPEG-cache integrity 均 success

因此，与最终发布链直接相关的当前 HEAD permanent gates 均为 completed / success。

### 5. 验收边界：不要把 CI 模拟客户端写成真实现场已联通

本节 CLOSED 指的是：
- 代码 owner；
- 持久化合同；
- 幂等 / fail-closed；
- 跨阶段 integration contract；
- Linux / Windows / Real Chrome 自动化。

它**不等于生产现场真实 OSS / 新畅联公网环境已经再次实网验收**。

真实现场仍依赖：
- 算法产物 OSS Endpoint / Bucket / AK/SK 权限；
- 长期 public URL 可访问；
- 新畅联登录 / token / OpenAPI 可访问；
- computePlatformId 与当前主数据一致；
- 生产 GPU / RKNN 转换节点在线。

如果现场 OSS 仍是 AccessDenied，代码会按当前合同 fail-closed，不会创建远端空版本；需要先修现场权限后再做真实发布 smoke test。

### 6. 当前主流程状态

截至本节 cutoff，既定 P0 主流程的**代码与永久自动化验收已经全部收口**。

后续不应再重构这些 CLOSED owner。接下来只做：
1. 部署最新已验收 HEAD；
2. 在生产配置真实算法产物 OSS；
3. 用一个可训练的新畅联视觉算法做一次真实 smoke：
   `训练成功 -> OSS 原始模型 -> 新畅联版本/原始权重 -> RK3568/RK3578 转换 -> 转换权重追加`；
4. 核对新畅联只读数据页能看到同一 version 下的原始 + 转换 weights；
5. 若现场失败，只按真实日志修环境或最小接缝，不重新设计主流程。



## 2026-09-28 主流程 P0：AI Candidate Review / Commit + 清洗 / 标签治理交叉验收 CLOSED（最新）

- 本节代码 cutoff：`5ee96747ee30cb165e2ec874b706bbac4f4b2e9c`（`ci: gate AI review to formal GT`）。
- `VERSION.txt = 42.24.0`，未修改。
- 没有新增第二套 AI Candidate、Annotation、Cleaning、Label Governance owner。

### 1. AI Candidate Review / Commit：CLOSED

正式语义仍是：
`AI 推理 -> CandidateStore -> AWAITING_CONFIRMATION -> 用户接受/拒绝/编辑 -> review_queued -> Worker Commit -> AnnotationRepository`

关键不变量：
- AI generation 只写 CandidateStore，不直接写 Ground Truth；
- provider 返回晚于 cancel / lease fence 时不得提交 candidate；
- 用户提交 decisions 后正式 annotation 仍保持不变，先进入 durable commit queue；
- 只有 Worker commit confirmed review 后才写正式 AnnotationRepository；
- 正式 AI 框带 `source=ai_candidate_confirmed` + `source_task_id`；
- candidate label 在 commit 前按当前 active canonical catalog 重新验证，失效标签 fail-closed；
- formal GT 与 candidate commit journal 分离，但 formal batch 成功后 journal 必须 catch-up，避免“GT 已写但任务被误标取消”；
- replay 通过 commit journal 幂等，不重复叠加 AI 框。

本轮补强：
- AI 图片解析原本已有 1k / 10k / 20k，`MaterialRepository.get_many <= 500`；
- review commit 的正式 GT + journal I/O 现扩到 1k / 10k / 20k，仍固定 `<= 200` / batch，并验证 replay 不重复写；
- `test_persistent_ai_annotation_e2e.py` 已正式纳入现有 `AI Annotation Recovery` API job，不再是“仓库里有测试但 CI 不执行”。

当前真实 CI：
- AI Annotation Recovery push `36419268460`：success
  - annotation-api-contract：success，`25 passed`（包含 persistent AI E2E）
  - recovery Ubuntu：success，`33 passed`
  - recovery Windows：success
- Frontend Runtime Stabilization `36419268463`：frontend success；browser-navigation success。
- browser-navigation 真实执行 `tests/browser/auto-label-polling.spec.mjs`；上一同生产代码 run 日志为 `76 passed`，当前 HEAD 也再次 success。

Real Chrome AI review 已锁定：
- 候选分页（54 条、24/page）；
- 映射搜索 / 平台标签映射；
- 显式新建 canonical label；
- 跨页编辑保持；
- 快速翻页旧响应不能覆盖新页；
- 框编辑；
- 全部接受；
- decisions payload `commit=true`；
- edited candidate boxes / labels 真正进入提交 payload。

因此：**AI Candidate Review / Commit = CLOSED。**

### 2. 清洗 / 标签统一交叉验收：CLOSED

清洗：
- CLEAN / MARK_CLEAN_SKIPPED 显式 selection 永久支持到 20,000 张；
- selection 独立落 `selection.sqlite3`，不把 20k ID 挤进普通显式 500-ID owner；
- cleaning scope 以正式 `annotation_state` 为真相，不以 box_count/annotated 派生字段猜；
- annotated / unannotated / confirmed_empty 可明确区分；
- 普通图片上传入口只允许把未标注素材送入图片质量清洗；带正式标注素材不会被上传清洗误处理；
- 远程清洗要求 portable storage + agent.remote，不能因没有合适远端节点静默 fallback 到本机；
- node busy / active durable task / queue truth 来自统一 TaskRepository；
- 单图分析 timeout 只失败该图，批次继续；
- CLEAN interrupted/running 行支持 durable retry / preemption recovery。

标签统一：
- `REMAP_ANNOTATION_LABELS` 是 durable MaterialBatch operation；
- worker 才修改正式 AnnotationRepository，创建任务时不直接改 GT；
- target label 在 worker 执行时重新确认 active；
- material 被删除、人工标注并发改变时 fail-closed，不覆盖新人工真相；
- GT 已提交但 selection 状态更新中断时可幂等恢复；
- confirmed_empty 的 annotation_scope 同步 remap；
- 多 source → target 是一个 durable task，全部成功后 source 才退休为 merged；
- 下一训练版本通过当前 label governance 折叠历史 merged labels，不复活旧标签。

当前 HEAD 真实门禁：
- Remote Cleaning Runtime `36419273140`
  - Ubuntu success
  - Windows success
  - API success
  - Real Chrome success
- Label Normalization Contract `36419273179`：success
- Training Input Integrity `36419273203`
  - JPEG/cache integrity Ubuntu success
  - JPEG/cache integrity Windows success

因此：**清洗 / 标签统一 / 训练输入交叉语义 = CLOSED。**

### 3. 下一步只剩最终主流程发布链验收

继续审计：
`素材 -> 清洗 -> 标签治理 -> 标注 -> 训练 -> 算法版本 -> OSS -> 新畅联 -> RKNN -> 转换权重追加`

原则：
- 优先复用当前 permanent workflows / API contracts / Real Chrome；
- 没有缺口就不再造重复 owner / 重复 E2E；
- 若缺的是跨阶段衔接，只补最小 integration contract；
- 所有结论以当前远端 HEAD + completed checks 为准。



## 2026-09-28 主流程 P0：批量图片上传 / ZIP 10k+20k / 导入 GT / 人工标注验收（最新）

- 本节代码验收 cutoff：`cdf10aa16fdf50991ee6fa76948704264ed50fbd`（`test: confirm ZIP labels in 10k acceptance`）。
- `VERSION.txt = 42.24.0`，未修改。
- 没有 merge main、tag、release、force push；没有删除/放宽测试；没有新建第二套 Upload / ZIP / Annotation owner。
- 后续接手必须重新读取远端 HEAD / checks，本节 cutoff 只是本轮验收基线。

### 1. 普通图片批量上传 1k / 10k / 20k：CLOSED

本轮补齐两个此前未真正闭环的边界：

1. **ambiguous chunk response 的安全恢复 / 幂等**
   - 仍复用现有 `UploadBatchStore`，没有新增第二套 session DB。
   - 每个浏览器 chunk 带稳定 `upload_request_id`。
   - 服务端先写 `PROCESSING` durable receipt，完成后原位转 `SUCCEEDED`；失败为 `FAILED`。
   - 相同 request ID + 相同 manifest：直接 replay 原 material IDs / failed truth。
   - 相同 request ID + 不同文件/目标：409 fail-closed。
   - 浏览器网络结果不明确时先查现有 `/api/v55/.../upload-batches/{id}`：
     - SUCCEEDED：恢复已提交结果；
     - PROCESSING：继续等待服务器真相；
     - 404：才用同一个 request ID 重发；
     - 不再盲目自动重传造成重复入库。

2. **20k 浏览器状态有界**
   - 分片仍保持 `64 files / 128 MiB`、严格顺序提交。
   - 1k / 10k / 20k 永久合同已加入；20k 为 313 个 chunk，单 chunk 最大 64。
   - 上传聚合状态只保留后续清洗决策需要的轻量 material 字段，不再把完整 server material 对象留在浏览器热状态。
   - DOM 批量预览仍按 96 条分页。

关键提交：
- `09362cb582d45d84fc41d219882b62722b609fdd` — backend upload request idempotency
- `b63af8d07808b8e1f972aa2599384d61e9ca33fa` — browser ambiguous recovery + 20k compact state
- `0432938ebda066e9bf669f89039de15290076c8e` — permanent upload gates on long-lived branch
- `2342a1b98dc7c659b7ff675918341fe31fe24c30` — Real Chrome test selects isolated project through bootstrap truth
- `745e965c34a6a84cc3a48b85404e53721ddde6d0` — canonical CLEAN recovery + current AnnotationRepository race owner

最终 CI：
- Material Upload Chunking：frontend Ubuntu / Windows、api-idempotency、real-chrome-upload 全 success。
- Material Upload Cleaning Performance：durable-api-flow、Ubuntu hot-path、Windows hot-path 全 success。
- durable-api-flow 日志：`38 passed`。
- 两个历史 400 根因已修：V47 clean compatibility 现在和 MaterialBatch 共用 `clean_options` canonicalization；真正改变 canonical option 仍 409 fail-closed。
- annotation-index 并发回归已从旧 `images.json/read_annotation` owner 迁到当前 `MaterialRepository + AnnotationRepository.get_many` owner。

### 2. ZIP 10k / 20k：CLOSED

当前正式链并非旧文档中的“不可续传大请求”，而是：

`8 MiB multipart parts -> concurrency=4 -> retries=2 -> fingerprint resume -> server merge -> verify/scan -> label confirmation -> background import`

永久 lower-cost gate：
- ZIP Import Durable Runtime 在当前长期分支 Ubuntu / Windows / backend-persistence / Real Chrome refresh 全 success。
- 新增 **20,000 图片 ZIP 扫描有界合同**：
  - `image_count = 20000`
  - 创建预览固定最多 500；
  - list 预览固定最多 300；
  - detail 可请求有界 preview；
  - 20k candidate manifest 外置；
  - hot `job.json < 64 KiB`，不内嵌 20k images。

genuine 10k 一次性完整验收：
- Workflow：`ZIP Processing 10k Acceptance`
- 最终 run：`36418333044`
- job：`genuine-10k-processing` = success
- 完整主链实际执行：
  1. 真实 multipart 创建；
  2. 首个分片落盘后用同 fingerprint 再次 create，确认恢复到同 `upload_id`；
  3. 全部分片提交；
  4. `/complete` 后台 server merge + verify + scan；
  5. YOLO 外部标签明确要求人工确认；
  6. acceptance 显式提交 `0 -> object`，没有自动映射；
  7. background import 完成；
  8. Material / Annotation / 文件 / manifest 全量核对。

实测关键值：
- `acceptance_passed = true`
- `multipart_resume_verified = true`
- `image_count = 10000`
- `report_imported_images = 10000`
- `material_total = 10000`
- `annotation_total = 10000`
- `annotation_boxes = 10000`
- `terminal_status = done`
- `terminal_progress = 100`
- `server_processing_seconds = 48.6`
- `images_per_second ~= 205.73`
- `rss_peak_mb ~= 196.44`
- `rss_growth_peak_mb ~= 79.31`
- `sqlite_lock_busy_incidents = 0`
- `poll_p95_ms ~= 4.18`
- `job_json_bytes = 2201`

前两次 genuine acceptance 红灯均为**旧验收脚本与当前产品合同脱节**，不是通过放宽生产规则解决：
- 第一次：统一畅联登录后旧脚本未启用现有 test-only auth harness，401；
- 第二次：当前标签治理禁止自动映射，旧脚本未提交外部 class 0 → canonical `object`，409；
- 最终脚本改为遵守当前认证测试契约和显式标签映射后，完整 10k 主链 success。

### 3. 导入 → Ground Truth：代码 / 自动化闭环

当前唯一正式标注真相继续是 `AnnotationRepository`：
- YOLO / COCO / VOC 导入经过用户确认的 label mapping 后，正式 annotation 批量写 `AnnotationRepository.upsert_many()`；
- material annotation summary 只是 projection；
- 正样本写 canonical label code + canonical project class_id；
- 空 sidecar / 明确负样本写 `confirmed_empty`；
- 没有有效正式标注的图片保持 `unannotated`，不会伪造 GT；
- 导入不会自动创建/选择标签。

`Remote Material Import` 在对应代码 cutoff 上：
- Ubuntu success
- Windows success
- API success（日志 `20 passed`）
- Real Chrome success

永久集成测试明确锁定：
- YOLO positive → annotated boxes；
- YOLO empty txt → confirmed_empty；
- 手工映射 external class → canonical platform label；
- COCO / VOC 同样写 AnnotationRepository，并保留 source provenance。

因此：**导入 → Ground Truth = CLOSED（自动化 / 代码层）**。

### 4. confirmed_empty / 人工标注：已有完整永久闭环，无需重复开发

现有 `tests/browser/material-workflows.spec.mjs` 已真实 Chrome 覆盖：
- 单图框绘制 / 移动 / resize / zoom / 删除 / 撤销；
- 保存后 API 回读；
- reload 后 thumbnail/source truth；
- dirty 关闭前保存，保存完成才关闭；
- 批量连续标注两张，逐张点击“确认无目标”；
- 两张 API 均回读 `annotation_state = confirmed_empty`；
- 上一张 / 下一张自动保存；
- late response 不得覆盖当前新图片；
- 1366×768 核心按钮可见；
- 20 次 open/close 稳定性。

后端同时有：
- `confirmed_empty` durable API contract；
- expected_version 并发冲突保护；
- AI provenance + manual edit 生成 mixed origin；
- 单图 GET/save 禁止扫描全量素材库。

该浏览器套件由 `Frontend Runtime Stabilization / browser-navigation` 永久执行，因此本轮不新增重复 owner/test。

### 5. 下一步 P0

继续按主流程顺序：
1. AI Candidate Review / Commit 全链审计与真实浏览器确认；
2. 清洗 / 标签统一最终交叉验收（避免和本轮 upload clean recovery 冲突）；
3. 最终 E2E：素材 → 清洗 → 标签治理 → 标注 → 训练 → 算法版本 → OSS → 新畅联 → RKNN → 转换权重追加。



## 2026-09-28 标签统一 → 迭代训练不复活旧标签：CI / Real Chrome 验收 CLOSED（最新）

- 本节验收代码 cutoff：`5b575dab8f8ea1177860031ea8dd4ee29e89a885`（`test: align training label browser build guard`）。
- `VERSION.txt = 42.24.0`，未修改。
- 该 cutoff 重新读取远端真实分支、最近提交、生产代码、测试与 workflow 后确认：本轮“标签统一成功后，下一算法版本仍复活历史旧标签”已经 **CLOSED**。
- 本节文档提交会产生新的 HEAD 与新一轮 CI；后续接手仍必须重新读取远端 HEAD / VERSION / checks，不能把本节 cutoff 当作未来最新 HEAD。
- 本轮没有 merge main、tag、release、force push，没有删除/放宽测试，没有修改历史算法版本 schema，也没有新增第二套 Training Label / Label Governance owner。

### 1. 真实根因与最终语义

历史算法版本 `previous_version.label_schema` 继续保持不可变；创建新的迭代训练任务时，后端唯一 Training Label Contract owner 会把历史 schema 投影到**当前 canonical label governance**：

- `active`：正常继承；
- `merged`：沿 `merged_into` 链解析到当前 active target，支持 merge chain；
- 多个历史标签合并到同一 target：去重，只保留一个 target class；
- `inactive` 且没有 `merged_into`：fail-closed，不猜；
- governance 中 missing：fail-closed，不猜；
- 合并/去重后训练 `class_id` 强制重新连续为 `0..N-1`。

后端当前明确返回并冻结：
- `inherited_label_codes`
- `retained_inherited_label_codes`
- `merged_inherited_label_codes`
- `dropped_inherited_label_codes`
- `effective_label_codes`
- `effective_label_schema`

只要 schema 因 merge 发生变化：
- `base_training_mode = previous_weights_init`
- `strict_resume = false`
- `optimizer_state_resumed = false`

即：继续使用上一成功版本权重初始化，但绝不 strict resume optimizer。

### 2. 前后端一致：浏览器只预览，服务器仍是唯一真相

当前前端：
- `state.labels` 继续只保存 active 标签，merged 老标签不会再次变成可选标签；
- `state.labelGovernance414` 保存完整 active / inactive / merged / `merged_into`；
- 训练弹窗标题为“上一版本继承（按当前标签治理）”；
- merge 会显示“历史版本保持不变；本次训练按已确认统一关系折叠：source → target”；
- inactive / missing 且无明确 merge target 会显示阻断提示，最终仍由服务器拒绝；
- 前端不拥有第二套训练 schema 规则。

当前静态资源真实 cache key：
- `app.js?v=42.25.263`
- `main.mjs?v=42.25.250`
- `training-labels.js?v=422566`
- `TrainingLabelRuntime.build = module-422566`

这些只是 cache-bust/build key，正式 `VERSION.txt` 仍是 `42.24.0`。

### 3. Ground Truth / governance / 历史版本集成验收

`tests/api/test_durable_label_remap.py::test_multi_source_label_unify_is_one_durable_task_and_retires_sources` 已锁定完整链路：

`fire + smoke -> person`
→ 正式 Annotation boxes / confirmed-empty scope 均改为 `person`
→ `fire.status = merged, merged_into = person`
→ `smoke.status = merged, merged_into = person`
→ active labels 只剩 `person`
→ 下一次 training label contract 从历史 `fire/smoke/person` 投影后只剩 `person`
→ 历史 V1 `label_schema` 保持原值不变。

单元测试同时锁定：
- merged 历史标签折叠到 canonical target；
- class_id 重新连续；
- previous weights init；
- strict resume = false；
- inactive without `merged_into` 必须拒绝。

### 4. Real Chrome 验收

`tests/browser/training-create-first-open.spec.mjs` 已包含真实用例：

`merged historical labels do not reappear in the next training dialog`

它真实打开训练弹窗并验证：
- 只显示 canonical `smoke`；
- 显示 `legacy_smoke → smoke`；
- 不再显示“继承 · 旧烟雾”；
- 类别数为 `1 类`。

最近一次该 workflow 实际触发在：
- SHA：`59fcab1a1dfd09ff280d46373fa38f05bde56a56`
- Run：`Training Create First Open #36408999348`
- `real-chrome`：completed / success
- 浏览器日志：`11 passed (27.5s)`
- Ubuntu contract：success
- Windows contract：success

随后 cutoff `5b575dab...` **只修改** `tests/browser/training-label-selector.spec.mjs` 的 build guard：
`module-422513 -> module-422566`，未修改生产标签继承逻辑或上述 Training Create spec，因此该 workflow 的 paths 没有再次触发。

### 5. 当前 cutoff 的 GitHub Actions 真相

对 `5b575dab8f8ea1177860031ea8dd4ee29e89a885` 重新读取 check-runs / workflow runs：

- Training Input Integrity：completed / success
- Label Normalization Contract：completed / success
- Frontend Runtime Stabilization：completed / success
  - frontend：success
  - browser-navigation：success
- Node Agent Executor：completed / success
  - Ubuntu contract：success
  - Windows contract：success
  - API：success

当前 HEAD **没有 completed failure**。

另外有 Remote Material Import / Portable Deployment / Remote Conversion Runtime 的 run 被 cancelled；不是本轮标签继承 failure，也没有据此宣布这些现场链路 VERIFIED。

### 6. 已复核历史红灯真实日志，不靠 workflow 名称猜

本轮最后两个相关红灯均已读取真实 job log：

1. `Frontend Runtime Stabilization / browser-navigation`（旧 SHA `59fcab1...`）：
   - Expected：`module-422513`
   - Received：`module-422566`
   - 属于测试 guard 落后于真实 build；
   - cutoff `5b575dab...` 精确对齐 guard 后，最新 Frontend Runtime 已 success；
   - 没有删除或放宽测试。

2. `Label Normalization Contract / contract`（旧 SHA `67ce9ec...`）：
   - 真实异常：`KeyError: 'platform_core/training_label_tasks.py'`
   - 原因是 required 已加入该文件，但 workflow 的 `bodies` 映射漏接；
   - `a566770d...` 补齐 source guard body 后，后续同 workflow 连续 success。

此前担心的 Node Agent Windows cancellation 时序旧红灯，在当前 cutoff 上已经真实重新通过，不需要为了历史 run 改 Node Agent。

### 7. 本问题最终验收结论

以下全部满足：
1. 标签统一后 source 为 merged 且有明确 `merged_into`；
2. Ground Truth 已统一到 target；
3. 历史算法版本 schema 不改；
4. 新版本 effective schema 不复活 merged 老标签；
5. 多历史标签合一 target 时只保留一个 class；
6. training class_id 连续 `0..N-1`；
7. 使用上一版本权重初始化；
8. 不 strict resume optimizer；
9. inactive / missing 无 merge target 时 fail-closed；
10. 前端训练弹窗与后端 contract 同一治理语义；
11. Real Chrome 已验证 merged 老标签不再以继承标签出现；
12. 当前最新代码 cutoff 相关 checks 无 failure。

因此：**标签统一 → 下一版本训练不复活旧标签 = CLOSED。**

### 8. 下一步

回到既定主流程 P0，不重构已 CLOSED 模块，按顺序继续：
1. 批量图片上传 1k / 10k / 20k：partial failure / resume / progress / UI truth / 内存与 IO 边界；
2. ZIP 10k / 20k：multipart / server merge / selected-tree / annotation parse / durable import；
3. 导入 → Ground Truth；
4. confirmed_empty / 人工标注；
5. AI Candidate Review / Commit；
6. 清洗 / 标签统一；
7. 最终 E2E：素材 → 清洗 → 标签治理 → 标注 → 训练 → 算法版本 → OSS → 新畅联 → RKNN → 转换权重追加。


## 2026-09-28 训练主链 / RK3578 / 新畅联发布唤醒收口，代码 cutoff 63/63 全绿（最新）

- 本节已验证代码 cutoff：`fcc8a3a75d9f6c94555de120ae08dc190849ee5c`（`fix: keep training core publish wake lightweight`）。
- `VERSION.txt = 42.24.0`，未修改。
- 该代码 cutoff 的 GitHub check 真相：**63 total / 63 success / 0 failure / 0 queued / 0 in_progress**。
- 本节文档提交会产生新的 HEAD 与新一轮 CI；后续接手仍必须重新读取远端真实 HEAD / VERSION / checks，不能把本节 cutoff 当作未来最新 HEAD。
- 本轮没有 merge main、tag、release、force push，没有删除/放宽测试，也没有新增第二套 Training / External Publish / Conversion owner。

### 1. CLOSED：训练创建与冻结主链审计未发现新的架构断层

本轮重新核对当前真正生效的 Durable Training 主链，继续保持：
- v12 Durable Training creation 为正式入口，Paddle 在 durable dataset/runtime 未完整前继续 fail-closed；
- external algorithm 训练资格仍以 authoritative detail 为准，只有 `status == 1 && analysisType == 1` 可训练；
- submit-time 冻结 effective split / Ground Truth / Snapshot / Dataset Revision / label contract / base checkpoint；
- Local / Remote 都使用 `resolve_frozen_training_base()` 与相同 frozen label schema；
- 迭代版本通过 `attach_version_if_current()` stale-base CAS，避免两个任务同时从同一旧版本分叉并静默覆盖；
- 新任务默认 `redact_excluded_objects_v2_preserve_selected`，历史 `redact_excluded_objects_v1` 继续支持 replay；
- `confirmed_empty` 仍是正式负样本；清洗完成不能自动等价为负样本；partial negative scope 不能被 YOLO 空 label 静默扩大为全部负类。

### 2. CLOSED：RK3578 从发布层贯通到 Durable/Agent 转换与实板验证合同

本轮发现并修复了多个原先各自写死 RK3568/RK3576 的断层。当前 canonical 产品芯片集合收口到：

`platform_core/conversion.py::SUPPORTED_ROCKCHIP_CHIPS = {"rk3568", "rk3578", "rk3576"}`

语义：
- 当前优先：RK3568、RK3578；
- RK3576 保持兼容，后续继续使用；
- **不新增 RK3588 产品支持**；相关单测 / workflow 继续把 RK3588 作为拒绝边界。

已对齐：
- external publish `chipCode` 规范化；
- Agent portable RKNN 参数校验；
- Agent 节点 capability / supported_chips 筛选；
- 自动转换目标选择；
- `deployment_worker.py`；
- RKNN board preflight；
- board evidence commit；
- fallback/local RKNN 目标下拉；
- Real Chrome / API / unit / workflow 永久 guards。

关键提交：
- `4b0499f33b67c2c733182fee18c87b5a2909f4c8` — `fix: normalize RK3578 external publish identity`
- `38288cb1798fabc1c84cdf6d5bb19b4f80a1c661` — `fix: carry RK3578 through remote RKNN contracts`
- `d5cbfab3afa1f67b20694d28eb9de0a834685f59` — `fix: unify RK3578 conversion product contract`

### 3. CLOSED：Durable Local / Remote Training 成功后立即唤醒现有新畅联 publisher

外部发布本身没有断链：`external_algorithm_publish` 的唯一 background owner 会定期恢复扫描所有：
- external / ChangLian algorithm；
- successful training status；
- `artifact_verified == true`；

并执行模型资产上传与发布同步。

真实缺口是：Durable Local / Remote Training 在算法版本 CAS commit 成功后没有立即 wake publisher，只能等待恢复扫描间隔。

现在：
- Local `TrainingHandler._finalize_completed_job()` 在版本 attach / idempotent recovery 成功后调用现有 `request_external_auto_publish_if_enabled()`；
- Remote `RemoteExecutionTransportService._commit_training_result()` 在新版本 attach 成功后、以及同 task/version 幂等恢复时调用同一 helper；
- helper 仍只负责 marker + wake，不拥有第二套发布实现；
- helper 失败返回 false，不把已经成功的训练错误降级为失败；30 秒恢复扫描仍是 durable fallback；
- Remote 已上传的 verified model artifacts 与 Local 后续 model artifact scanner 继续由既有 ModelArtifact owner 管理。

关键提交：
- `04da021ce82d5f257750b8f624e0dba0eec087d7` — `fix: wake external publisher after durable training commit`

### 4. CLOSED：训练核心不再被 external publish 重依赖污染

上述即时 wake 初版把 `external_publish_request` 顶层 import 进 `training_tasks.py`，导致 training core 的轻量 JPEG/cache workflow 间接加载 `model_artifacts -> pydantic`，Ubuntu/Windows 均真实失败。

没有通过给轻量 workflow 额外安装 pydantic 来掩盖依赖污染。

当前修复：
- `training_tasks.py` 顶层保持轻量；
- 新增内部 lazy delegate `_request_external_publish_after_training()`；
- 只有训练正式完成、算法版本已提交之后才加载 external publish helper；
- 本地 recovery integration test 仍能 monkeypatch wrapper 验证调用次数 / algorithm_id / version_id；
- Ubuntu + Windows `jpeg-cache-integrity` 均重新 completed success。

关键提交：
- `fcc8a3a75d9f6c94555de120ae08dc190849ee5c` — `fix: keep training core publish wake lightweight`

### 5. 当前验证边界与下一步

代码 cutoff `fcc8a3a7`：**63/63 checks success**，包括本轮真实暴露过的：
- RK3578 control-plane / conversion contracts；
- remote training contracts；
- Ubuntu / Windows JPEG-cache integrity；
- Real Chrome；
- API / unit / recovery / transport contracts。

仍未宣称真实环境 VERIFIED：
- Linux/NVIDIA GPU 真实训练；
- 正式 OSS；
- 新畅联生产接口真实版本/权重创建；
- RK3568/RK3578 实板转换与推理。

下一步按既定主流程继续，不重构已 CLOSED 模块：
1. 批量图片上传 1k/10k/20k 与 partial failure / resume / UI truth；
2. ZIP 10k/20k 与服务端 progress / selected-tree / annotation parse；
3. confirmed_empty / 人工标注；
4. AI Candidate Review / Commit；
5. 数据清洗与标签统一；
6. 真实 OSS / 新畅联 / Linux GPU / RKNN 实板现场验收。

原则继续是：**查真实 bug -> 修最小根因 -> 前端/后端/Worker/Durable truth 一致 -> 永久测试。**


## 2026-09-28 标签保存 page-scoped 主流程收口 / Browser 红灯关闭 / 代码 cutoff 59/59 全绿（最新）

- 本节已验证代码 cutoff：`5954a7919608930aff5472206d492a277fa9cd54`（`test: lock nonblocking scoped refresh contracts`）。
- `VERSION.txt = 42.24.0`，未修改。
- 该代码 cutoff 的 GitHub check 真相：**59 total / 59 success / 0 failure / 0 queued / 0 in_progress**。
- `Frontend Runtime Stabilization / frontend`：completed success。
- `Frontend Runtime Stabilization / browser-navigation`：completed success。
- 本节之后的文档提交会产生新的 HEAD 和新一轮 CI；因此接手时仍必须重新读取远端真实 HEAD / VERSION / checks，不能把本节 cutoff 当成未来最新 HEAD。
- 本轮没有 merge main、tag、release、force push，没有删除/放宽测试，也没有恢复 retired owner。

### 1. CLOSED：标签管理编辑保存后 Modal 不关闭

真实根因不是 5 秒 timeout 太短，而是 `window.saveLabel414` 在标签 PUT/POST 已成功后，仍同步：

`await refreshLabels414(true) -> closeModal()`

其中 `/api/v54/projects/{project_id}/label-schema` 是标签使用统计/管理页派生 truth；它慢时会把已经成功的保存操作和 Modal 关闭一起拖住。

当前正确语义已收口为：

`mutation API success -> authoritative label items -> patch label truth -> close modal -> page-local render -> background usage refresh`

具体：
- PUT 原本已返回 canonical `items`；POST 标签创建现在也统一返回 canonical `items`。
- `applyLabelMutation414(result, classId)` 只用服务端返回的 canonical label items 更新 `state.labels`，并在 usage 已加载时按 class_id patch 对应 identity 字段。
- 只有服务端 mutation 成功且返回可用 authoritative target 时才关闭 Modal。
- API 400/409/500 或 mutation truth 不完整时，Modal 保持打开并显示真实错误。
- `refreshLabels414(true)` 改为 Modal 关闭后的后台 usage refresh；它失败只提示“标签已保存，但使用统计刷新失败”，不会把成功保存伪装成失败。
- create/edit 仍然 page-scoped，**没有重新加载完整 material pool**。

永久 Browser 合同已经加强：测试会主动卡住 `/api/v54/.../label-schema` usage refresh；编辑保存仍必须先关闭 Modal、更新标签行，然后测试才释放 usage 请求。因此不是加 timeout 或放宽测试。

关键提交：
- `f73b0aaaea580afeda257930529699d1104d5311` — `fix: make label save truth page-scoped`
- `5954a7919608930aff5472206d492a277fa9cd54` — `test: lock nonblocking scoped refresh contracts`

### 2. CLOSED：Source Import terminal scoped refresh 串行阻塞

同一轮 Browser 还暴露出 source-import terminal completion 偶发拿不到 paged Material refresh。

真实代码原来串行：

`await refreshLabels414(false) -> await reloadMaterialPage61()`

标签 schema 请求慢/失败会延迟甚至阻断当前数据集的 paged material refresh。

现在 terminal owner `window.refreshSourceImportTasksV36` 保持唯一 PollRegistry 生命周期，并只启动两个局部 refresh：
- `refreshLabels414(false)`
- 当前仍在“数据集”页面时的 `reloadMaterialPage61()`

两者通过 `Promise.allSettled` 并发、互不阻塞；仍禁止 broad `loadRelated()` / full project reload。

永久 source contract 明确锁定：
- PollRegistry owner 不变；
- 只刷新 labels + current paged materials；
- 两个 scoped refresh 不允许重新串行 await；
- 不恢复完整项目/完整素材池刷新。

### 3. CLOSED：标签统一跨 UI scope bridge 与旧 source guard

并发到达的 `b9522d961ee0dbde2d832aac51a8f0aac94cbb32` 已将标签统一进度所需的 canonical helper 显式桥接到 `window`：
- `window.armImportRemap414`
- `window.importRemapProgress414`
- `window.renderLabelRemapBanner414`
- `window.drawLabel414`

本轮没有回退该修复。旧 frontend source guard 已升级为锁定新的唯一公开 bridge，而不是要求旧 lexical 直调。因此 Candidate/Annotation/ZIP/Training owner 均未新增第二套。

### 4. 当前真正生效的 owner / truth

- 标签管理浏览器 owner：`renderLabelManagement414` + `window.saveLabel414`。
- 标签 mutation 后的 identity truth：POST/PUT 返回的 canonical `items`。
- 标签 usage/statistics：`/api/v54/projects/{project_id}/label-schema`，属于保存后的派生 refresh，不再控制保存成功与否。
- Source Import terminal lifecycle：`window.refreshSourceImportTasksV36` + PollRegistry key `source-import-v36`。
- 当前 Material 列表：v61 paged material owner；终态只 refresh 当前页域。
- 历史标签统一：Durable Material Batch `REMAP_ANNOTATION_LABELS` owner，跨页面恢复继续读取 durable task truth。

### 5. CI / 验证边界

代码 cutoff `5954a7919608930aff5472206d492a277fa9cd54`：
- **59/59 checks success**；
- Frontend unit 全通过；
- Real Chrome `browser-navigation` 全通过；
- Label Normalization backend/frontend/source guards 全通过；
- 没有 queued / in_progress / completed failure。

这证明 GitHub Actions 所覆盖的代码、API、frontend contracts、Real Chrome regression 已通过。

仍未宣称真实环境 VERIFIED：
- Linux/NVIDIA GPU 真实训练；
- 正式 OSS；
- 新畅联生产接口；
- Rockchip RK3568/RK3578 实板转换/推理。

没有现场证据时继续标记 OPEN。

### 6. 下一步

当前 Browser blocker 已关闭。接下来按既定 P0 顺序继续**主流程准确性审计，不重构已 CLOSED 模块**：

1. 训练创建唯一 Durable owner；
2. submit-time Ground Truth / Snapshot / label contract / base checkpoint freeze；
3. `redact_excluded_objects_v2_preserve_selected` 默认与 v1 legacy replay；
4. 迭代算法上一成功版本标签继承 + 用户显式选择新标签；
5. Local / Remote frozen truth 一致；
6. training success/failure durable truth；
7. 训练成功后的新畅联版本/原始权重发布，以及转换后追加权重；
8. 再审批量上传、ZIP 1k/10k/20k、confirmed_empty、人工标注、AI Review、清洗、标签统一、转换发布。

原则仍是：**查真实 bug -> 修最小根因 -> 前后端/Worker/Durable truth 一致 -> 永久测试。**



## 2026-09-28 当前真实接管点：AI 标注闭环 / 训练标签投影 / CI 仅剩 1 个 Browser 红灯（最高优先级）

- 本节代码状态 cutoff：`ce383fcc1af6ee5420860a42e65181a594545c5e`。
- `VERSION.txt = 42.24.0`，未修改。
- 该代码 cutoff 的 GitHub check 真相：**58 total / 57 success / 1 failure / 0 queued / 0 in_progress**。
- 唯一失败 check：`Frontend Runtime Stabilization / browser-navigation`，job `108840375284`。
- 本节文档提交会把分支 HEAD 再向前推进；新会话第一步仍必须重新读取远端真实 HEAD / VERSION / 最近 commits / 当前 Actions，不能把上述 cutoff 当成最新 HEAD。
- 继续遵守：不 merge main、不 tag、不 release、不 force push、不删除或放宽测试、不恢复退役 owner、不写死 Windows 路径。

### 1. 已完成：新畅联同步与 ZIP 导入性能 / 进度单一真相源

从 `13b4180c` 到 `e9bc23f6` 已完成：

- 新畅联 Manual / Auto sync 收口到单一 operation truth。
- 外部分析方式列表支持 `analysis_list_all()` 一次读取 summary index，能证明 product ownership 时消除 product→analyses N+1；不能证明时回退原有 per-product list。
- **训练资格真相仍以每个 analysis 的 detail/getInfo 为准**，即 `status == 1 && analysisType == 1`；listAll 只做索引优化，不能覆盖 authoritative detail。
- ZIP 选择性导入不再“先全量 extract 再复制 selected tree”，只写用户选择的 image member，同时保留 annotation/config member，减少一次完整磁盘写放大。
- ZIP merge/verify/scan/extract/annotation/db-commit 的展示进度收口为服务端 `zip_display_progress`；真实 bytes / entries / counters / ETA 从服务端发布。
- 浏览器侧旧固定百分比估算器已退役为历史兼容，当前 job 优先读取服务端 canonical projection。
- VERIFY 与 SCAN 已拆开，避免“验证/扫描”阶段进度含义混在一起。

关键提交：
- `13b4180c` — unify external sync operation truth
- `a13af3b8` — remove external analysis summary N+1
- `2724e0f6` — eliminate duplicate ZIP selected-tree copy
- `161f6104` — server-owned ZIP phase progress
- `a20a28b5` — retire browser ZIP progress estimators
- `e9bc23f6` — separate ZIP verify and scan progress truth

### 2. 已完成：AI 标注 canonical owner、模型配置冻结与显式标签选择

当前 AI 标注正式流程仍是：

`AI inference -> CandidateStore -> AWAITING_CONFIRMATION -> 人工审核/编辑/接受/拒绝 -> Commit -> AnnotationRepository Ground Truth`

本轮进一步收口：

- v60 创建任务与 Material Batch 共用 worker-safe `platform_core.annotation_runtime` owner。
- 模型配置在 submit-time 冻结：`model_config_id / model_name / provider / config revision / secret_ref` 等任务输入持久化；**secret value 不进入 request.json**，Worker 执行时才按 secret reference 解析。
- 普通用户只从“模型配置”选择正式视觉模型；不再暴露临时 endpoint/provider 执行入口。
- AI 标签必须由用户**显式填写/选择当前有效 canonical label code**；中文名、alias、历史 alias、参考图片都不能自动替用户决定标签。
- 参考图片只作为视觉 example，不能读取其 bbox 后自动扩张本次 labels。
- AI Review commit 关闭 cancellation gap：正式 Ground Truth 写入后，commit journal catch-up 不再被刚到达的 cancel 截断，避免“GT 已写但 journal 未记”的半提交。
- AI Review 正式写入携带 `expected_version`，通过 AnnotationRepository CAS 防止审核提交覆盖并发人工标注修改。
- CandidateStore / formal AnnotationRepository 继续是两个明确 durable owner，不新增第二套 Ground Truth 存储。

关键提交：
- `8f521207` — freeze canonical AI annotation model configuration
- `5893e697` — require explicit AI annotation labels
- `07db5297` — lock AI review and explicit training labels
- `3de7e799` — close AI review commit cancellation gap
- `4a340260` — fence AI review against concurrent annotation edits
- `ce383fcc` — align AI recovery guard with journal catch-up

### 3. 已完成：训练“未选标签对象”投影升级为 v2，避免误伤已选目标

此前训练允许同一张图片继续参与，但本次未选择的 label 不进入本次算法类别。为避免未选对象仍作为正样本泄漏，训练 bundle 会对 excluded object 做像素 redaction。

本轮发现一个准确性边界：若“未选标签的大框”覆盖“已选标签的小框”，v1 直接涂抹大框会把已选目标像素也抹掉，但 YOLO positive label 仍保留，形成“有标签、没目标像素”的矛盾训练真相。

当前已升级：

- canonical policy：`redact_excluded_objects_v2_preserve_selected`。
- 先 redaction 未选对象，再从原图恢复所有 selected positive rectangle 的像素。
- 因此未选择的标签不会被本次训练知晓，同时尽量不破坏已选择类别的正样本视觉证据。
- 历史 `redact_excluded_objects_v1` 仍可 replay，不能破坏旧 frozen task。
- projection digest / manifest / source guard 已同步锁定 v2 与 legacy v1 compatibility。

关键提交：
- `e41ce7bf` — preserve selected targets during label redaction
- `90960c85` — lock redaction v2 and legacy replay

### 4. 前一批 CI 红灯已大幅清空

在 `161f6104` 后处理过的真实问题/合同包括：

- 旧 training stop path 的 retired queue lock / training runtime 合同。
- External Algorithm SQL unchanged sync 不应因 sync metadata 改变而 bump master-data revision。
- Training bundle cache publication 必须保持“算法版本 attach 完成后再 publish verified”语义。
- ZIP progress/source guards、external publish/platform guards、remote training guards 等历史 source literal 已与 canonical owner 对齐。
- 这些工作已经反映在当前 cutoff：**57/58 checks success**，不再是上一轮的 13 个 completed failures。

不要重新修已经消失的旧红灯；新会话必须以当前 live check-runs 为准。

### 5. 当前唯一 OPEN：标签管理“编辑标签”保存后 Modal 未关闭

真实失败日志：

- Workflow/job：`Frontend Runtime Stabilization / browser-navigation`，job `108840375284`。
- Playwright：**76 tests -> 75 passed / 1 failed**。
- 失败 case：
  `tests/browser/material-workflows.spec.mjs:518`
  `label management create and edit stay page-scoped without loading the full material pool`
- 失败断言位置约 line 577：
  点击“编辑标签 -> 保存”后，`getByRole('dialog', { name: '编辑标签' })` 在 5 秒内仍 visible。
- 该 case 的目的还包括：标签管理 create/edit 必须 page-scoped，不能为了保存标签重新加载 full material pool。

下一会话处理原则：

1. **先 focused reproduce / 读真实 network + browser state**，确认保存 API 是否成功、是否 4xx/409、是否成功但 UI 没 close、是否 authoritative refresh 卡住。
2. 不要先把 timeout 从 5s 调大。
3. 不要为了关 modal 恢复 full material mode / 全量素材 refresh。
4. 保存成功后应关闭 modal，并只 patch/refresh 标签管理所需的小范围 truth。
5. 保存失败必须留在 modal 并显示真实 error，不能“假关闭”。
6. 修完后先跑该 focused browser case，再跑 `browser-navigation`，最后重新看当前 HEAD 的全部 check-runs。

### 6. 下一会话优先级

P0-1：关闭上面的唯一 browser 红灯，保证标签管理 page-scoped create/edit 主流程稳定。

P0-2：重新确认最新 HEAD 所有 completed checks；只有当前 HEAD 全部 success 才能写“CI 全绿”。

P0-3：做一轮主流程回归审计，重点不是重构，而是防止近期 AI/标签投影改动破坏：
- 批量上传 / ZIP 导入；
- 无目标/confirmed_empty；
- 手工标注；
- AI Candidate review + commit；
- 数据清洗；
- 训练创建、输入冻结、迭代标签继承、显式标签选择；
- External ChangLian 同步/发布。

P1：在 CI 稳定后再做真实环境验收：Linux/NVIDIA GPU、真实 OSS、新畅联生产接口、Rockchip 转换/实板。没有现场证据不得写成 VERIFIED。

### 7. 不得破坏的长期产品合同

- `VERSION.txt` 必须保持 `42.24.0`。
- 训练创建唯一 Durable owner；Local/Remote 必须使用 frozen Ground Truth/Snapshot/base checkpoint/label contract。
- 用户决定标签；导入和 AI 都不得自动映射/自动替用户选 canonical label。
- `confirmed_empty` 是正式负样本。
- AI 不能直接写正式标注；必须 Candidate -> 人工确认 -> Commit。
- AnnotationRepository / CandidateStore / ZIP / TrainingSubmit / PollRegistry 不新增第二 owner。
- 新畅联训练资格必须实时 authoritative detail 验证。
- 外部删除 -> 本地同步删除（包括训练成果），不得仅显示“已下架”。
- 前端 progress 不自造假百分比；优先服务端 durable truth。
- queued / in_progress 不算 success；历史 HEAD 的绿灯不能替代当前 HEAD。


## 2026-09-28 训练 Progress 单一真相源 / Bootstrap Algorithm Revision 收口（最新）

- 本节开发起点真实 HEAD：`4dbf804e7bd27d8c9086dc130e781ea0ed3b18fe`。
- 本节写文档前真实代码 HEAD：`c2cdb926f6d9e298d03cfef78626100da507f5b5`。
- `VERSION.txt = 42.24.0`，未修改。
- 最新 HEAD 共有 **114 个 check，114 个全部 queued，0 completed**。因此当前只能确认代码/合同已提交，**绝不能写成 CI 已通过**。
- 本轮未 merge main、未 tag、未 release、未 force push，也没有删除或放宽训练准确性/标签/快照/泄漏测试。

### 1. P0：训练 Progress 已从多套真相收口为一个服务端展示投影

当前根因已经重新从真实代码确认：

- Worker `train_worker.py` 持有真实 epoch / batch / elapsed / ETA / throughput；
- Durable Task 持有 QUEUED / WAITING_RESOURCE / TRAINING / EVALUATING / FINALIZING / terminal 生命周期；
- 旧 HTTP `enrich_job_runtime()` 每次 GET 又扫 log、`_infer_epoch_from_log()`、重新计算 percent / elapsed / ETA；
- SSE 原来只发 Durable Task；
- Browser stream 原来又从 `current_item` 字符串解析 epoch/batch；
- HTTP refresh 会整批覆盖 SSE state。

这会导致同一训练同时被多套 owner 计算，出现百分比、耗时和 ETA 来回跳。

当前新增 canonical：

`training_display_progress`

字段包括：

- `revision`
- `updated_at`
- `status`
- `phase`
- `phase_progress`
- `overall_progress`
- `current_epoch / total_epochs`
- `current_batch / total_batches`
- `elapsed_seconds / eta_seconds`
- `throughput`
- `message`
- `telemetry_source`

所有权规则：

- Worker telemetry 只负责真实训练 epoch/batch/timing/throughput；
- Durable Task 只负责 lifecycle/status/phase/resource；
- 服务端只在 `platform_core/training_job_projection.py` 合并一次；
- HTTP 与 SSE 均发布同一 projection；
- live Durable job 禁止再走 log inference；
- `_infer_epoch_from_log()` 仅保留 historical pre-Durable compatibility/recovery；
- 训练 epoch 已完成但 Durable 尚在 evaluation/finalization 时，100% 保留给 terminal success；
- 不再让浏览器通过 `current_item` 猜 epoch/batch。

另外修了一个自查出的边界：

Durable heartbeat 可能比最新 worker `job.json` 落后一个心跳窗口，所以 HTTP 在 lifecycle overlay 之前会冻结 `worker_progress_truth`，展示投影明确从冻结的 Worker telemetry 读取训练数据，防止旧 heartbeat 覆盖刚写入的 batch 进度。

提交：

- `28410c1d` — canonical training display projection；
- `7ec5b3cb` — lifecycle overlay 前冻结 Worker telemetry；
- `9473b2de` — 对齐永久测试/source guard。

永久合同：

- HTTP refresh 用 display revision 拒绝覆盖更晚的 SSE；
- SSE 也拒绝旧 revision；
- `trainingProgressView()` 优先读取 canonical display；
- live Durable branch 中 source guard 禁止 `_job_log_text()` / `_infer_epoch_from_log()`；
- browser stream source guard 禁止重新出现 `applyProgressCounters` 字符串解析。

### 2. 已读取 completed failure 的真实日志，并修复失效 fixture/guard

上一批 completed failure 不是统一一种原因，已经逐个读真实 job log：

1. `Remote Training Runtime`
   - `tests/api/test_training_request.py` 使用 `hashlib` 但测试文件漏 import；
   - 修复测试 import，不改生产合同。

2. `External Algorithm Platform`
   - 旧 source guard 仍要求 compatibility `/api/projects/.../train/start` 自己再做一套 external refresh / local gate；
   - 当前正确架构是 compatibility URL 只委托 canonical v12 Durable owner；
   - 测试已改为：compatibility route 必须只 delegate，不能重新拥有第二套 gate；v12 + canonical enqueue 继续强制实时 external truth gate。

3. Browser `training-label-selector`
   - 旧 fixture 仍假设首次训练新标签默认勾选；
   - 当前产品合同是：首次训练/new labels 默认全部不选，用户必须显式勾选；
   - 测试改为显式勾 fire，smoke 保持未选；重新打开未形成真实版本的首训弹窗仍默认不选。

4. Browser `material-workflows`
   - 旧断言仍锁 `openBatch414`；
   - 当前 canonical upload runtime 使用 `openRecentUploadBatch414("ready")`，只作用于本次上传素材；
   - 测试已绑定 canonical owner，不回退旧全局批量入口。

这些修改不是为了放宽测试，而是把已经过时、要求多 owner / 自动选标签 / 旧入口的 fixture 改成当前产品合同。

### 3. P0：Bootstrap stale algorithm cache 已改为 SQL revision 驱动

现场问题：

新畅联同步已经把算法写入 `AlgorithmSqlStore`，当前算法 API 能看到；
但 F5 后 `/api/v53/bootstrap/snapshot` 仍返回进程启动时的旧 `algorithms`；
随后 AlgorithmListRuntime 再请求 v12 算法 API，新算法才“过一会又出现”。

真实根因：

`_v53_snapshot_with_live_jobs()` 以前只 overlay `jobs`，没有 overlay `algorithms`。

当前修复：

- `AlgorithmSqlStore` schema 升到 **v4**（这不是产品 VERSION）；
- 增加持久 `algorithm_revision`；
- 每一个成功的真实算法图写事务只 bump 一次：
  - create / patch / delete algorithm；
  - attach / patch / rollback / delete version；
  - version operation；
  - external sync；
  - full replace；
- external sync 如果全部 unchanged，不 bump revision；
- `platform_core.algorithms.algorithm_store_revision()` 成为统一 revision reader；
- Bootstrap snapshot 保存 `algorithm_revision`；
- snapshot 请求时：
  - cached revision == SQL revision → 继续走缓存；
  - revision 不一致 → **只 reload algorithms overlay**；
  - 不重跑材料、标注、模型配置、完整 bootstrap；
- 并发读写使用前后 revision probe；若连续写导致无法取得稳定窗口，不会把潜在旧 rows 标成最新 revision；
- 全局 bootstrap cache 只允许发布与当前 SQL revision 一致、且不倒退的 algorithm overlay。

提交：

- `d5f69ac9` — SQL revision + Bootstrap algorithm overlay + 同步按钮 selector；
- `c2cdb926` — 并发写期间禁止错误发布 falsely-fresh revision。

永久测试已覆盖：

- read-only 查询不 bump revision；
- create / patch / attach version revision 单调递增；
- external unchanged sync 不 bump；
- ready Bootstrap 缓存旧算法后，新建算法，下一次 snapshot 立即出现；
- Bootstrap algorithm invalidation 不允许通过重新调用完整 `_v53_build_snapshot()` 解决。

### 4. 算法列表“同步畅联云”按钮 selector 明确 bug 已修

AlgorithmListRuntime 实际按钮：

`data-algorithm-sync`

旧 `syncNow()` 却找：

`data-external-list-sync`

所以请求可能发出，但算法列表按钮不会 disabled / 变成“正在同步…”。

现在 `external-algorithm-platform.js` 已统一绑定：

`[data-algorithm-sync]`

并增加 frontend source contract，禁止旧 selector 重新出现。

### 5. 当前 CI 真相

文档写入前 HEAD：`c2cdb926f6d9e298d03cfef78626100da507f5b5`。

GitHub 当前对该 HEAD 返回：

- check total：114；
- queued：114；
- in_progress：0；
- completed：0；
- success：0；
- failure：0。

这表示 **runner backlog / 排队**，不是 success。

后续 Agent 必须继续：

- 一旦出现 completed failure，读取该 run 的真实 job log；
- 不能根据历史 failure 继续猜；
- 不能为了绿灯删除/放宽测试。

### 6. 下一步继续顺序

当前继续优先级：

1. **新畅联 Sync Operation 单一 owner**
   - Manual / Auto 共用 operation；
   - operation_id / trigger_source / started_at / phase / processed/total / errors / result；
   - 用户重复点同步应打开/读取当前 operation，不创建第二个；
   - 开始减少 product → analyses → detail 的 N+1 外部请求。

2. **ZIP Import 真实 phase/counter/ETA + 性能**
   - UPLOAD / MERGE / VERIFY / EXTRACT / SCAN / ANNOTATION_PARSE / DB_COMMIT；
   - bounded parallel readers + single batched DB writer；
   - 排查重复完整 I/O。

3. **AI 标注 canonical owner**
   - 普通用户统一从模型配置选择；
   - task submit 冻结 model_config_id / model_name / provider / config revision；
   - 退役旧 renderer。

本轮原则仍然是：

**唯一 owner → 持久 revision → fail-closed → 删除旧推断/旧 selector → 永久测试。**

## 2026-09-28 训练基础权重冻结 / 本地远程版本原子提交闭环（最新）

- 本节写入前真实代码 HEAD：`a384675928d9874d4c92c7abb18332eea022ec32`。
- `VERSION.txt = 42.24.0`，未修改。
- 当前最近 100 个分支 GitHub Actions 仍全部为 **queued**；该 HEAD 的 `Remote Training Runtime`、`Training Input Integrity` 等尚无 completed 结果，因此**不能宣称当前 HEAD 全绿**。
- 本轮继续遵守：不 merge main、不 tag、不 release、不 force push、不删除测试、不为 CI 放宽训练准确性/数据血缘规则。

### 1. 训练基础模型现在和标签/Snapshot 一样在 submit-time 冻结

此前标签合同已经 server-authoritative 冻结，但 local worker / Remote Prepare 在真正执行时仍会重新读取算法当前版本，再选择“当时最新”的基础权重。

这会产生严重错位：

- 任务创建时继承 v3 的 label schema；
- 排队期间算法产生 v4；
- worker 启动时却重新选 v4 权重；
- 最终可能出现 v3 schema + v4 checkpoint 的类别错位。

当前已统一冻结完整 base model contract：

- `base_model_contract_schema_version = 1`
- `framework`
- `base_training_mode`
- `base_version_id / base_version_name`
- `base_model_kind`
- `base_model_reference`
- `base_model_sha256`
- `base_model_size_bytes`
- `base_selection_reason`

规则：

- 迭代训练：submit-time 冻结当前 verified version 的确切 checkpoint path/SHA256/size；
- 首训：冻结 `mother_model_init` 和精确 mother-model reference；
- 排队后新增版本不能改变本任务 base；
- checkpoint 文件丢失、size/SHA 改变、framework/suffix 不匹配均 fail-closed；
- 历史 pre-contract task 才保留兼容重选逻辑。

Local 与 Remote Prepare 均调用同一 `resolve_frozen_training_base(payload)`。

相关提交：

- `575e3cbb`：submit-time 冻结 base identity；
- `19dcab3a`：local worker 使用 frozen base；
- `38c487ff`：queued payload/job 持久化 base identity；
- `befbe198`：Remote Prepare 使用 frozen base；
- `7e3a2fd2`：versioned base contract；
- `c8a23009` / `1b73cc79`：永久测试及真实 continue-training fixture。

`input_freeze_id` 包含完整 label contract，因此不同 base SHA 的任务即使 dataset `snapshot_id` 相同，`input_freeze_id` 也不同；永久测试：`test_input_freeze_identity_changes_when_frozen_base_model_changes`。

### 2. Durable Paddle 假能力已 fail-closed

审计确认：

- 生产 `TrainingHandler.run()` 只真正支持 Ultralytics；
- 当前 Durable bundle 是 YOLO data.yaml；
- 历史 `paddle_worker.py` 需要独立 COCO dataset/train-json/val-json/PaddleDetection config；
- 但 production worker 曾广播 `training.paddle`，会造成“创建成功、执行阶段才失败”的假能力。

当前：

- v12 Durable Training 在算法/素材 IO 之前拒绝 `framework != ultralytics`，直接 409；
- production worker capability 仅广播 `training.ultralytics`；
- `paddle_worker.py` 保留，不删除，但在真正建立同一套 Durable COCO Snapshot / completion contract 前，不允许主流程宣称 Paddle 可训练。

提交：`82b5105d`、`06e714d9`、`4d11c59f`、`5921f8be`、`3830f86b`。

### 3. 成功算法版本从诞生时就带完整 frozen label lineage

此前 local `base.TrainingHandler` 先 `attach_version()`，随后 LabelContract handler 再二次 patch label schema，存在“版本已成功落库、标签合同尚未补齐”的 crash window。

当前 local finalization 在第一次正式创建版本时就原子携带：

- `label_schema`
- `label_codes`
- 完整 `label_contract`

来源严格为：

- `snapshot.json.label_schema`
- `input-freeze.json.label_contract`

不重新读当前项目 catalog，不信任前端请求重算。

`_persist_version_contract()` 只作为恢复/兼容 backfill，并且：

- 保留完整 frozen base reference/SHA/size 等 lineage；
- 改为 `update_algorithm_version(algorithm_id, version_id, patch)` 的目标版本事务 patch；
- 禁止再用 `save_algorithms(path, algorithms)` 全量替换算法图，避免并发 attach 被旧 graph 覆盖。

提交：

- `d9bc1432`：版本初次 attach 即写 frozen label contract；
- `27a851dd`：原子 lineage 回归；
- `ab00308a` / `04b9c030`：backfill 保留完整 frozen lineage；
- `4e6a10a8` / `8d433c14`：backfill 只 patch 目标版本，CI 禁止全图覆盖。

### 4. Remote Agent 成功版本现在与本机保存同一份标签血缘

此前 Remote Prepare 虽然复用 frozen Snapshot，但 `remote_execution.training` 没有携带 label lineage；远程结果 commit 创建算法版本时也没有 `label_schema / label_contract`。

当前：

1. Remote Prepare 把控制端 frozen `label_schema / label_codes / label_contract` 放入 execution contract；
2. Agent 不拥有/修改标签决策；
3. Remote commit 再次校验：
   - execution label schema vs control-plane snapshot；
   - label_contract.effective_label_codes vs frozen schema；
4. 任一不一致直接 409；
5. 远程成功版本与本机一样原子保存完整 frozen label lineage。

提交：

- `01f97771`：remote execution contract 携带 frozen lineage；
- `3396af69`：remote version commit 持久化 frozen lineage；
- `d0934f47` / `b67c5549`：Prepare/Result 永久测试；
- `14336166`：Remote Training CI guard。

### 5. 本机/远程迭代版本提交现在有 stale-base fence

已先补应用层规则：

- 同 task_id 已有版本 → crash recovery 幂等复用，不重复 attach；
- 当前版本已从 frozen base v1 变成 v2 → 基于 v1 的旧任务结果不能晋升为新的 current version；
- 首训任务创建后若算法已经产生第一个版本 → 旧首训不能覆盖它。

提交：

- `4c18a2a3`：local stale-base / same-task recovery fence；
- `acd1aae2`：stale、首训竞争、同 task 恢复测试；
- `5f522076`：CI 永久 guard。

随后继续发现 check-then-attach 仍有 TOCTOU：

两个任务都基于 v1，同时进入 finalization 时可能都在 v1 尚未变化前通过应用层检查。

当前已把真正权威 fence 下沉到 `AlgorithmSqlStore`：

`attach_version_if_current(..., expected_current_version_id=...)`

在同一个 SQLite `BEGIN IMMEDIATE` 事务内：

1. 先按 `training_job_id` 查同 task 幂等版本；
2. 再比较 frozen base/current；
3. 首训要求无 current 且版本表为空；
4. legacy pointer 为空时，迭代只允许 frozen base 仍实际存在；
5. 插入版本；
6. 更新 `current_version_id`；
7. commit。

因此两个同时基于 v1 的训练，只能有一个成功晋升；后一个在事务内看到 current 已变化并报 `ALGORITHM_VERSION_CONFLICT`。

Local / Remote 均使用该 CAS owner；Remote 转成 `REMOTE_TRAINING_BASE_VERSION_STALE`，Local 显式转成 `TRAINING_BASE_VERSION_STALE`。

相关提交：

- `2f622f46`：AlgorithmSqlStore 原子 compare-and-attach；
- `5f546e2c`：公开训练版本 CAS wrapper；
- `5c900854`：local finalization 使用 CAS；
- `45ef07de`：remote commit 使用 CAS；
- `d5c71c52`：真实双线程并发 CAS、同 task 幂等、legacy 首训冲突测试；
- `e8a2a506`：现有 Remote Training Runtime 触发/compile/pytest 覆盖 SQL CAS owner；
- `2880bcc9` / `26bc55a6`：Local race 错误语义与格式收尾；
- `a3846759`：Remote commit 测试重新绑定真实 CAS owner，避免 monkeypatch 旧 owner 形成假保护。

### 6. 当前下一步

1. 每次继续前重新读取远端 HEAD；
2. 当前 Actions 仍是 runner backlog，必须等 completed 后读取真实结果；
3. 任何 completed failure 先读 job log，再修真实错误，禁止放宽 production contract；
4. 当前训练 P0 静态审计已重点收口：
   - 单 Durable creation owner；
   - frozen Ground Truth / Snapshot；
   - explicit new-label selection；
   - excluded-object redaction；
   - canonical/training class namespace；
   - frozen base checkpoint；
   - local/remote label lineage；
   - unsupported Paddle fail-fast；
   - local/remote stale-base CAS；
5. 下一步继续审训练主链剩余高风险：任务创建幂等键、成功/失败状态真相、资源 AUTO 决策与实际 runtime 一致性、训练完成后的外部发布链；随后再转批量素材导入/空素材。



## 2026-09-28 训练创建单 Owner / 标签选择前后端一致性补充（最新）

- 本节写入前真实代码 HEAD：`254fbb2f0964f52e0f4b5dfaca75a72a229cd0f3`。
- `VERSION.txt = 42.24.0`，未修改。
- 当前 GitHub Actions runner 仍处于明显 backlog：最近 100 个分支 run 全部为 `queued`；该 HEAD 的 `Training Input Integrity`、`Remote Training Runtime`、`Frontend Runtime Stabilization` 均尚未得到 completed 结果。**queued / in_progress 不算通过，因此本轮 P0 仍不得宣称全绿。**
- 本轮继续遵守：不 merge main、不 tag、不 release、不 force push、不删除测试、不为测试放宽生产准确性规则。

### 1. 训练创建现在只有一个 Durable owner

审计发现同一产品曾同时保留：

- `/api/v12/projects/{project_id}/train/start`
- `/api/projects/{project_id}/train/start`
- v12 内部还残留一段不带 `split_mode` 即进入旧 `build_yolo_dataset_v44()` 的同步创建分支。

这会允许 direct POST 绕过 submit-time label freeze / Snapshot / Ground Truth 合同，属于真实 P0。

当前已收口：

- v12 不带 `split_mode` 直接 409，明确要求 Durable Training；
- 现代前端 `training-submit.js` 本来就提交 `split_mode`，主 UI 不受影响；
- 旧无版本 URL 现在只是兼容别名：`return v12_start_train(project_id, payload)`；
- 已物理删除约 29KB 重复旧训练创建实现和 v12 不可达旧同步分支，不保留第二套 owner；
- v42 历史自动迭代写入口已经由现有 `_legacy_iteration_write_disabled()` 禁用，不作为当前生产写入口。

关键提交：

- `39dbcbcf`：v12 旧无 split 路径 fail-closed；
- `de824ef3`：永久 API 测试锁定 legacy bypass 必须失败；
- `58655aed`：CI guard 锁定 Durable-only v12；
- `4d9d3142`：退役重复 legacy training creation owner；
- `ecbf2e1e`：旧 URL 必须委托 Durable owner；
- `9db4aca8`：CI guard 强制单 Durable owner。

### 2. 真实 YOLO E2E 已迁到生产 Durable handler

旧 `tests/e2e/test_real_yolo_training.py` 仍使用无 `split_mode` 的旧同步 job 语义。

当前已改为：

1. v12 提交 `train_labels + split_mode + train_image_ids + test_image_ids`；
2. 返回 202 Durable Task；
3. 测试通过 `resolve_worker_registration(DATA_DIR, {"training"})` 获取实际生产 training handler；
4. Scheduler 执行真实 CPU 训练；
5. 最后同时核对模型产物与 `input-freeze.json` 中冻结的 label schema。

提交：`3914f0c7 test: move real yolo e2e onto durable training owner`。

### 3. 三层 class_id 身份现在真正分离

发现 P0：新增 label 进入 task schema 时曾丢掉 project canonical class identity，只留下连续 training class_id。

当前规则：

`source_class_id != canonical_project_class_id != training class_id`

例如项目：

- fire canonical = 1
- smoke canonical = 7

本轮 YOLO：

- fire training = 0，canonical_project_class_id = 1
- smoke training = 1，canonical_project_class_id = 7

修复 / 测试：

- `176a9f52 fix: preserve canonical class identity in task schema`
- `4962de4a test: lock canonical and training class namespaces`

以后禁止直接把 canonical 1/7 当 YOLO class id，也禁止训练压号时丢失 canonical 溯源。

### 4. 新增类别必须存在正式正样本，负样本 scope 不能制造新类

进一步发现：`confirmed_empty.annotation_scope` 之前也会进入“可新增标签”证据，导致只有某类别负样本、没有任何正 bbox 时，用户仍可能把该类别加入 schema。

当前已调整：

- 新类别必须至少由已选 **effective training pool** 中一个正式 positive bbox 证明；
- `confirmed_empty.annotation_scope` 仍可用于已有/inherited 类别的负样本语义和 dangling-label preflight；
- 但它不能把一个全新类别加入本轮算法。

修复 / 测试：

- `6f91bc19 fix: require positive evidence for newly added labels`
- `ba204cf2 test: block negative-only evidence from adding classes`

### 5. 前端不再替用户自动选择新增标签

前端审计发现三个与服务器新合同不一致的点：

1. 首次训练会默认把全部可选标签自动勾上；
2. 本地 fallback 会把 `annotation_scope` 也展示为“本次素材可新增标签”；
3. 当前项目 catalog 若停用上一版本 inherited label，前端会把它从继承预览删除，而服务器正确语义是继续保留 previous verified schema。

当前统一为：

- 首次训练：新增标签默认 **一个都不自动选择**；
- 迭代训练：previous-version inherited labels 自动保留且不可取消；
- 新增标签永远由用户显式勾选；
- 可新增标签只来自正式 positive bbox，不来自 `confirmed_empty` scope；
- 当前 catalog 只决定“新标签是否可选”，不能静默删除 inherited output identity；
- 前端 active-label admission 与后端一致：`active !== false && status == active`。

提交：

- `6d643531 fix: align client label choices with frozen server schema`
- `d1441323 test: require explicit client-side new-label choice`
- `8f486303 fix: mirror server active-label admission in client`
- `21216f1e test: reject inactive labels in client additions`

大批量路径也已核对：`training_material_picker_api.py::_selection_summary` 的 `label_codes` 来自 `material_labels`（正式 bbox 标签）；负样本 scope 单独存在 `material_annotation_scopes`，因此 10k/20k 服务端摘要不会把负样本 scope 混成新增类别。

### 6. Projection / bundle cache 身份补强

新增永久测试证明：同一源图、同一 label schema，只要 `training_projection_digest` 不同，`snapshot_id` 和 `dataset_revision_id` 必须不同，避免不同 excluded-object redaction 投影命中同一个 bundle cache。

提交：`a7145989 test: bind projection digest to training cache identity`。

### 7. CI guard 已跟随 canonical owner，不保留死代码凑 grep

退役旧训练 owner 后，旧 workflow source guard 中两项会必然假红：

- `runtime_stop_policy="target_only"` 原来查 `app.py`，真实 Durable owner 在 `platform_core/training_tasks.py`；
- external master-data preflight 的精确出现次数从旧重复 owner 的 3 次变成真实单 owner 下 2 次。

当前已正确把 guard 指向生产 owner，没有为了 grep 重新塞死代码：

- `254fbb2f ci: point training guards at canonical durable owner`

同时已静态自检 `Training Input Integrity` 的 16 条固定 source guard：当前 HEAD **16/16 命中**。

### 8. 当前状态 / 下一步

已知旧红灯的 completed-success 证据仍有效：

- `Training Input Integrity` push `36367518722`：SUCCESS；
- `Training Input Integrity` PR `36367522023`：SUCCESS；
- `Remote Training Runtime` PR `36367522000`：SUCCESS。

但这些是本轮 P0 后续代码之前的结果，**不能替代最新 HEAD 验证**。

接手顺序：

1. 每次继续前重新读取远端 HEAD；
2. 优先等 / 读取当前 HEAD 最新 `Training Input Integrity`、`Remote Training Runtime`、`Frontend Runtime Stabilization`；
3. 任何 completed failure 必须先读取真实 job log，再修；
4. 只有当前代码头相关 workflow completed success，才能将本轮迭代标签 P0 标 CLOSED；
5. 之后再按主流程优先级继续：训练整体一致性 → 批量导入/空素材 → 手工标注 → 数据清洗 → 新畅联。



## 2026-09-28 迭代标签 Server-Authoritative 闭环 / 未选目标防错误负监督（最新）

- 本节写入前真实代码 HEAD：`d1807fd4284181b38d8d47df2b67859c4a0b84f8`。
- `VERSION.txt = 42.24.0`，未修改。
- 本轮未 merge main、未 tag、未 release、未 force push；没有新增第二套 Training / Snapshot / Annotation / Picker owner。
- 当前 GitHub Actions runner 存在明显 backlog：本节写入时该 HEAD 的 `Training Input Integrity` push/PR 与 `Remote Training Runtime` PR 仍为 **queued**，因此**当前不能声称全绿**。

### 1. 上一轮两个真实 CI 红灯已经按正确方式 CLOSED

最初交接里的两个 completed failure 都只通过修正旧 fixture/测试合同收口，没有放宽生产规则：

- `Training Input Integrity`
  - 旧 split / snapshot fixture 补齐正式 Ground Truth 与 processed truth；
  - Snapshot 不重复拥有 processing admission，`processing_status` 准入仍归 `build_split_manifest()/resolve_training_selection()`。
- `Remote Training Runtime`
  - 旧 API fixture 不再提交不存在的假素材 ID；
  - continue/supplement 等 fixture 按当前真实 material truth / leakage guard 建数据。

已确认的 completed-success 证据：

- `Training Input Integrity` push run `36367518722`：SUCCESS；
- `Training Input Integrity` PR run `36367522023`：SUCCESS；
- `Remote Training Runtime` PR run `36367522000`：SUCCESS，四个 job 全部 success。

相关 fixture 提交：

- `09be82b1`：split fixture 对齐正式 annotation truth；
- `be3c0db8`：durable training API fixture 使用真实 material truth；
- `f0cf9146`：snapshot fixture 对齐正式 training truth；
- `27fd522d`：processing admission 保持由 split boundary 单一 owner 负责。

### 2. 迭代标签合同现在由服务器在 submit-time 冻结

此前前端已有：

- `inheritedLabelCodes`
- `newLabelCodes`
- `effectiveLabelCodes`
- `train_labels`

但 Durable Training 的 `freeze_training_inputs()` 仍取项目全部 active labels，前后端不一致。

当前已改为：

1. `/api/v12/projects/{project_id}/train/start` 在任务入队前由服务器读取真实算法/版本、真实已选训练素材标注与用户提交的 `train_labels`；
2. 上一 verified/current version 的 frozen `label_schema` 作为 inherited schema；
3. 用户显式选择且确实存在于**服务器最终 effective training pool** 的新标签才允许追加；
4. 固定评测保留图 / `test_image_ids` 中单独出现的标签不能借原始请求绕过，不能扩充训练 schema；
5. 最终 schema 重新压成连续 training class_id `0..N-1`，canonical identity 继续保留；
6. `label_contract`、投影后的正式 GT、最终 schema 一起进入 `input-freeze.json`，并参与 freeze digest；
7. Worker 新任务优先读取 frozen `label_contract`，排队后项目标签/标注变化不能重算本任务 schema；
8. pre-freeze 历史任务才走兼容重算路径。

关键提交：

- `dd753397`：保留迭代 schema 与 excluded-label truth；
- `48054e44`：freeze label projection，并在训练副本物化阶段处理 excluded object；
- `ff53a2f4`：projection evidence 绑定 Snapshot / Dataset Revision identity；
- `2f6a80d0`：submit-time 冻结 server-authoritative label contract；
- `d8c75968` / `fe1a6e3e`：新标签只从真实 training candidates / server-resolved effective split 取证；
- `a37d8a81` / `d1807fd4`：上一 verified schema 的 inherited label 即使后来被项目 catalog 停用，也不会静默删类/重排；只有 inherited code 可作为稳定历史身份继续使用，其他 dangling/停用/未映射 label 仍 fail-closed。

### 3. 未选择的新标签：禁止“删 box + 原图继续训练”的错误负监督

旧 `training_label_tasks.py` 已存在 task projection owner，但旧实现会：

- 删除未选类别 bbox；
- 如果图片只剩未选类别，则直接投影成 `confirmed_empty`；
- 原图目标仍可见，YOLO empty target 会把它当背景监督风险。

当前已收口为现有 owner 内的 `redact_excluded_objects_v1`，没有新建第二套训练 runtime：

- 源 AnnotationRepository 永远不改；
- task projection 冻结 `training_excluded_boxes`；
- 同时冻结 `training_projection_policy` 和 deterministic `training_projection_digest`；
- train / validation 的**任务本地副本**在源 SHA256 校验完成后，把 excluded bbox 对应像素区域做确定性遮除；
- 遮除完成后重新计算 training content SHA256；
- 只有 excluded object 已从 train/validation pixels 移除后，该 task-local image 才允许成为本轮 schema 的空 target；
- independent test/evaluation 图不做像素遮除，只按 frozen effective schema 评分；
- Snapshot / Dataset Revision / bundle manifest 都记录 projection evidence，避免不同标签投影错误命中同一 bundle cache。

这是一种针对标准 Ultralytics YOLO TXT 数据合同的保守兼容方案：当前普通 YOLO detection dataset 没有可直接表达“这个 bbox 区域完全忽略 loss”的标准 TXT ignore-region 合同，所以**不能把可见但未标注的新类别目标留在训练图里**。task-local redaction 不修改源图，不等价宣称为原生 ignore loss。

永久规则已写入：

- `docs/superpowers/specs/2026-09-11-negative-sample-contract.md`
- `.github/workflows/training-input-integrity.yml`

CI source guard 现在明确：

- 必须存在 `redact_excluded_objects_v1`；
- 必须存在 projection digest / materializer redaction；
- 禁止重新出现 `negative_origin="filtered_by_training_labels"` 的旧“可见目标 + empty label”语义。

### 4. 当前永久测试覆盖

已补 / 调整：

- direct POST 不带首训显式标签 → 409；
- direct POST 选择不在已选训练素材中的标签 → 409；
- 有效显式标签 → `input-freeze.json` 只冻结对应 schema；
- test/evaluation-only label 不能成为新训练 label；
- inherited schema + 显式新增 label 连续重编号；
- schema change 保持 `strict_resume=false`、`optimizer_state_resumed=false`，只用上一版本权重初始化；
- 上一版本 inherited label 在项目 catalog 后续停用后仍保持 class identity；
- 混合 selected/unselected bbox 会保留 excluded-box projection evidence；
- 只有 unselected bbox 的图片必须在任务副本中真实遮除对应像素，测试直接读取物化后的 JPEG 像素证明目标区域被移除；
- Snapshot 持久化 redaction origin / policy / digest / excluded count；
- bundle manifest 记录 redaction policy、digest、redacted object count 和变化后的 training content hash。

### 5. 当前真实 CI 状态与下一步

本节写入时最新代码 HEAD `d1807fd4` 的相关新一轮 Actions **仍 queued**，queued / in_progress 不能算 success。

下一接手动作固定：

1. 重新读取远端 HEAD，不能假定仍是 `d1807fd4`；
2. 读取该 HEAD 最新 `Training Input Integrity` 与 `Remote Training Runtime`；
3. 任何 completed failure 必须先读真实 job log，再修真实问题；
4. 两个 workflow completed success 后，才能把本轮标签 P0 标 CLOSED；
5. 然后再继续系统审计：训练 → 批量导入/空素材 → 手工标注 → 清洗 → 新畅联，重点查假成功、状态漂移、N+1/全量扫描、错误负样本、schema 漂移、网络超时重复写、删除不同步和前后端事实不一致。



## 2026-09-28 主流程交接 / CI 红灯与迭代标签合同审计（最新）

- 本节写入前真实分支 HEAD：`c74a747cb4704f5d6e3b7498ac065cb3a5671267`。
- `VERSION.txt = 42.24.0`，未修改。
- 本轮未 merge main、未 tag、未 release、未 force push；未新增第二套 AnnotationRepository / Training runtime / Picker / Label owner。
- 当前主流程优先级仍是：**训练准确性与稳定性 > 批量素材导入 / 空素材 > 手工标注 > 数据清洗 > 新畅联对接**。

### 1. 当前已收口的主流程事实

当前长期分支已经具备：

- 已清洗但未标注素材可作为“训练候选”被用户选择，但不会伪装成 Ground Truth；
- 正式监督训练只接受 `annotated` / `confirmed_empty`；
- `confirmed_empty` 是明确负样本，普通 `unannotated` 绝不能静默导出为空 YOLO 标签；
- `include_empty` 历史兼容参数不能重新绕过 Ground Truth 合同；
- 训练候选、有效监督素材、待标注素材通过 `TrainingSelectionResolution` 分层保存；
- `input-freeze.json` 在任务提交时冻结本轮正式训练真相，排队期间标注/标签变化不能静默篡改已经创建的任务；
- 本机 / 远程训练都复用同一冻结真相，素材真正物化时再次核对 SHA256；
- training class_id 与平台 canonical class_id 分离，训练导出连续 `0..N-1`，并保留 `canonical_project_class_id` 做溯源；
- 手工标注保存通过 AnnotationRepository 现有 `version` 做 optimistic concurrency，stale writer 返回 409，不能静默覆盖别人最新标注；
- 大批量训练素材读取保持 500/批；已清洗待标注素材不会被制造成负样本。

### 2. 当前 CI 真实状态：18 success / 2 completed failure

当前 HEAD 的 20 个主要 GitHub Actions workflow：

- **success = 18**
- **failure = 2**
- queued / in_progress = 0

两个 completed failure 已读取真实 job log，不能把当前 HEAD 宣称为全绿。

#### 2.1 Training Input Integrity — FAILED

Workflow run：`36363187396`

失败 job：

- Ubuntu：`108744311440`
- Windows：`108744311683`

两边是同一类失败：旧 `tests/unit/test_training_splits.py` fixture 仍在制造缺少当前正式 `annotation_state / processing truth` 的旧样本；新的 `build_split_manifest()` 会 fail-closed：

`ValueError: train 集包含未处理素材 ...`

当前失败覆盖包括 split mode、group leakage、confirmed_empty compatibility 等 6 个旧测试。

**接手要求：优先更新测试 fixture / 合同，使其构造真实的正式 GT / 已处理素材；不得为了让旧测试通过而重新放宽生产 Ground Truth 规则。**

#### 2.2 Remote Training Runtime — FAILED

Workflow run：`36363187284`

其中：

- `ultralytics-loader-contract`：SUCCESS
- Ubuntu `preparation-contract`：SUCCESS
- Windows `preparation-contract`：SUCCESS
- `api`：FAILURE（job `108744311377`）

真实日志显示 8 个旧 API 用例与当前提交时训练输入校验不一致，典型包括：

- 直接提交不存在的假素材 ID：`train-a / train-b / test-a`、`one / two / three`，现在正确返回 409 “所选素材不存在”；
- continue-training fixture 中素材没有满足“已清洗候选 / 正式 GT”新合同，正确 fail-closed；
- supplement candidate set 仅两张素材却要求安全拆分 train / validation / test，当前因不可拆分组件数量不足正确 409。

**接手要求同样是修测试数据和期望，不允许通过删除 submit-time preflight、放宽 leakage guard、允许不存在素材等方式追求 CI 绿灯。**

### 3. 用户刚确认的“迭代训练 + 标签选择”产品语义

用户要求后续重点核对并最终实现：

1. 算法已有版本时，新训练属于迭代训练，必须从该算法**当前/上一有效版本**权重继续，而不是重新从母模型开始；
2. 上一版本已有标签/schema 需要继承；
3. 本轮选择训练图片后，图片里出现的“新增标签”由用户显式决定是否加入本轮算法；
4. 用户没有选择某个图片携带的新标签时，**图片本身仍可参与训练**；
5. 但该未选择标签不应成为本轮算法的新增类别，本轮算法不能因为素材里出现它就自动扩充 schema；
6. 系统禁止替用户自动选择、同义词推荐或隐式映射标签。

本轮只做了代码审计，**没有改这部分生产实现**。

### 4. 迭代权重 / 标签继承：当前做到什么程度

#### 已有 / 基本正确

后端基础模型选择：

- `platform_core/algorithms.py::choose_algorithm_iteration_base()`
- `app.py::_v54_iteration_base(..., strict_latest=True)`

当前行为是：算法已有可训练版本后，迭代训练使用 current / verified version；如果该版本不可用，会 fail-closed，**不会静默回退母模型**。

前端训练草稿：

- `static/modules/training-draft.js::trainingInheritanceFromAlgorithm()`
- `static/modules/training-labels.js::resolveClientTrainingLabels()`

当前已经区分：

- `inheritedLabelCodes`：上一版本 schema，前端显示为“继承”，不可作为本轮新增标签取消；
- `newLabelCodes`：本轮已选素材带出的新增标签，用户可勾选 / 不勾选；
- `effectiveLabelCodes = inherited + new selected`；
- schema 变化时前端语义已经是“上一版本权重初始化”，而不是严格 optimizer resume。

`trainingDraftToRequest()` 会把用户本轮新增标签选择提交为：

`train_labels: normalized.newLabelCodes`

#### 仍未闭环 — P0

**Durable Training 后端目前没有真正使用 `payload.train_labels` 来裁剪本轮冻结的 label schema。**

当前：

- `platform_core/training_tasks.py::freeze_training_inputs()`
- 仍直接调用 `_label_schema(project)`
- `_label_schema(project)` 会取项目全部 active labels

因此现在存在前后端不一致：

- 前端让用户选择“本轮新增标签”；
- 请求也提交了 `train_labels`；
- 但后端冻结 Snapshot 时仍可能把项目全部 active labels 放进本轮 `label_schema`。

此外旧 `app.py::build_yolo_dataset_v44()` 的 `train_labels` 主要是**筛选图片**，不是“从参与图片中剔除未选标签的训练框”。

所以用户刚描述的：

> 图片可以继续参与训练，但没有选中的新增标签，本轮算法不应自动知晓 / 扩充为类别

**目前还没有 server-authoritative 闭环。**

### 5. 下一会话实现迭代标签前必须特别注意的技术语义

不要简单地“把未选标签的框从 YOLO txt 删除”就宣布完成。

原因：标准目标检测训练里，如果图片上真实存在某目标，但把它的 box 删除，模型可能把该区域当背景，从而受到负向监督。这与“本轮算法不知道该标签”并不完全等价。

因此下一会话应先基于现有产品语义设计一个**不会污染旧类准确率**的 server-authoritative 合同，再实现。至少要确认：

- inherited schema 必须来自当前 verified version 的 frozen `label_schema`，不能只相信前端；
- 本轮新增 schema 只能来自用户显式提交的 `train_labels`，并验证它确实来自已选素材/current active canonical labels；
- 未选择的新标签不能进入 `data.yaml names` / 本轮 training class IDs；
- 同一图片若含未选择类别，如何处理该目标区域必须有明确训练语义，不能把“忽略类别”误做成“明确背景”；
- schema 变化继续保持 `strict_resume=false`、optimizer state 不续接，只用上一版本权重初始化；
- 后端必须有永久测试，证明绕过前端直接 POST 也不能偷偷扩大 label schema。

### 6. 新会话执行顺序

1. **重新读取远端真实 HEAD、VERSION、最近 commits 和当前 CI；不要直接把本节 SHA 当作最新。**
2. 第一优先级：修复上述两个 workflow 的旧 fixture / 测试合同，保持生产 Ground Truth / submit freeze / leakage guard 不放宽；跑到 completed success 后再继续。
3. 第二优先级：完成“上一版本标签继承 + 本轮显式新增标签”的后端权威合同，并解决“参与图片里未选类别”的 YOLO 监督语义。
4. 然后继续主流程审计：
   - 批量素材导入 / 空标注语义；
   - 手工标注；
   - 数据清洗确认与删除保护；
   - 新畅联训练成功 → original 权重 → conversion 权重追加 → 删除/同步闭环。
5. 最后做真实生产验证：
   - NVIDIA Linux；
   - 20k / 50k 图片；
   - OSS/S3 RTT；
   - SQLite WAL 峰值；
   - 内存 / 磁盘 IOPS；
   - 长浏览器会话。
6. queued / in_progress 永远不能算 success；任何 completed failure 必须先读真实 job log再处理。



## 2026-09-28 主流程准确性 / 已清洗未标注训练候选语义收口（最新）

- 本节写入前真实代码 HEAD：`f7d6ce10bd575f2eaa7fde51fdc775077b6b47f2`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- 用户最终确认的产品语义：
  - **已清洗但未标注的素材，训练任务创建时必须允许选择**；
  - **可选择 != 已成为 Ground Truth**；
  - 未标注素材不能被静默写成空 YOLO 标签，否则会把未知目标误训练成负样本，直接伤准确率；
  - 独立试验集仍必须具备正式 Ground Truth。
- 本轮没有新增第二套 AnnotationRepository / Training runtime / Picker owner；全部沿用现有正式 owner。

### 1. 训练选择与 Ground Truth 分层 — CLOSED

当前链路已经拆成三层真相：

1. **训练候选池**：`processing_status=processed` 的已清洗/已处理素材可进入 Picker；
2. **本轮有效监督训练集**：只有正式 `annotated` / `confirmed_empty` Ground Truth；
3. **待标注候选**：已清洗但 `unannotated` 的素材会保留在任务选择意图中，但不会进入本轮 Snapshot。

训练提交新增 `TrainingSelectionResolution`：

- `selected_train_image_ids`：用户实际选择的已清洗训练候选；
- `effective_train_image_ids`：本轮真正进入监督训练的正式 GT；
- `pending_annotation_image_ids`：已清洗待标注候选；
- `input-freeze.json` 只冻结 effective Ground Truth；
- pending IDs 同时写入任务 payload / job truth，不能丢失；
- 若全部选择均未标注，则在 Web 提交阶段明确 409，不能制造一个必然失败的训练队列任务；
- 独立试验素材含未标注时直接 fail-closed。

示例：

- 用户选择 10,000 张已清洗素材；
- 其中 2,000 张已有正式 GT；
- 当前训练 Snapshot = 2,000 张；
- pending annotation = 8,000 张；
- 8,000 张仍保留在该任务选择记录内，但**不生成空标签，不参与本轮监督训练**。

### 2. Picker / 前端 / API 语义统一 — CLOSED

`platform_core/training_material_picker_api.py`：

- 列表与普通批量选择从 `annotated=true` 改为 `processing_status=processed`；
- 独立试验集 bulk selection 继续要求 `annotated=true`；
- selection summary 新增：
  - `selectable_count / selectable_total`
  - `eligible_count / eligible_total`
  - `pending_annotation_count / pending_annotation_total`
- `eligible` 仍表示可直接监督训练的正式 GT，不偷换语义。

前端：

- 已清洗未标注卡片显示“已清洗 · 待标注”；
- 训练候选可勾选；
- 独立试验集同一素材禁用并显示“试验集必须已标注”；
- 创建页显示“可直接训练 X / 待标注 Y”；
- 成功创建任务后提示“本轮有效 X 张 · 待标注 Y 张已保留”。

### 3. 训练准确性相关同时收口

本轮及紧邻提交已确认：

- 清洗完成不再自动等同 `confirmed_empty`；
- legacy `include_empty` 不能把 `unannotated` 重新绕回空标签训练；
- active project class_id 与 training class_id 已隔离，训练导出重新压成连续 `0..N-1`，并保留 `canonical_project_class_id` 溯源；
- 训练输入已经在**提交时**冻结 `input-freeze.json`，排队期间标注/标签变化不会篡改已经创建的任务；
- 手工标注保存已经使用 AnnotationRepository 现有 `version` 做 optimistic concurrency， stale writer 返回 409，不能静默覆盖；
- 训练所选素材读取已经 500/批；固定 Benchmark reservation 读取也改为 500/批，避免大批量 SQLite IN 变量上限风险。

### 4. 永久测试

新增/更新覆盖：

- 已清洗未标注训练素材可出现在 Picker；
- train role 可选、test role 禁用；
- 选择 7 张（6 正式 GT + 1 待标注）：
  - selected=7
  - effective=6
  - pending=1
  - pending 不进入 `input-freeze.images`
  - pending 不进入本轮 `train_image_ids`
- 全 pending 在入队前 fail-closed；
- 独立 test pending fail-closed；
- 1001 张 training MaterialRepository 读取保持 500/500/1；
- 手工标注 stale-write 409；
- training class_id 连续化。

### 5. CI 当前真实状态

本节写入前，多次关键代码 SHA 的 20 个主 workflows 均仍处于 GitHub runner `queued`，尚未得到 completed 结果。

因此当前只能写：

- **代码已提交；**
- **CI 待验证；**
- **queued != success；**
- 当前没有 completed failure 可读取日志；
- 后续若出现 completed failure，必须先读真实 job log，再修，不允许为了 CI 放宽生产 Ground Truth / Snapshot / concurrency 合同。

### 6. 下一步主流程优先级

1. 等待 / 重新读取最新 HEAD 的 CI；先处理任何 completed failure。
2. 在真实 NVIDIA Linux 节点验证：
   - GPU assignment / reservation；
   - auto batch + CUDA OOM 降档；
   - 训练 Snapshot 与实际 dataset manifest 一致；
   - 训练完成模型、外部发布、转换追加权重闭环。
3. 用真实 20k / 50k 素材做大批量验证：
   - Picker 首开 / 批量选择；
   - SQLite WAL 峰值；
   - OSS/S3 RTT；
   - 训练准备时内存、磁盘 IOPS。
4. pending annotation 素材如要真正进入下一轮监督训练，继续走现有：
   - 手工标注；或
   - AI Candidate -> 人工审核 -> Commit Ground Truth；
   - 不新增“AI 自动直接入库”捷径。


## 2026-09-27 AI 大批审核 / Recovery 与训练大文件 I/O 收口（最新）

- 写入前真实代码 HEAD：`7a04c91df48a09453146f086feb0ff6dde807033`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- `7a04c91d...` 自身 **20 个主要 GitHub Actions workflows 全部 completed success (20/20)**：
  - success = 20
  - failure = 0
  - queued = 0
  - in_progress = 0
- 本轮没有新增 CandidateStore / AnnotationRepository / Training runtime / PollRegistry / modal owner；只在现有正式 owner 内收掉连接、全表读取和大文件重复 I/O。

### 1. AI 生成 CandidateStore 每图重复 SQLite connect — CLOSED

提交：

`469fdcec201edbf62934e1dc0c46f3855e90c6c9` — `perf: reuse AI candidate writer connection`

旧正式 `run_ai_annotation()` 每生成一张图就：

`store.append_items([item])`

而一次 append 内部会先 `_ready()` 打开 SQLite，再重新 `_connect()` 做正式写入；10k AI 候选会产生大量重复 connect / PRAGMA / schema 检查。

现在：

- `CandidateStore.write_session()` 在一次 AI generation loop 内复用一条 writer connection；
- **仍然每张图独立**：
  - `BEGIN IMMEDIATE`
  - generation fencing guard
  - `COMMIT`
- checkpoint 仍在 candidate commit 后写入；
- 没有为了性能改成“200 张一起 commit”，因此已付费 provider 调用在崩溃后仍可逐图恢复，不能因批量事务回滚而重复调用 AI；
- 1001 张永久合同要求：
  - connection = 2（一次 ready + 一条长生命周期 writer）
  - commit = 1001
  - fencing guard = 1001。

### 2. AI generation recovery 全表 fetchall — CLOSED

提交：

- `1e7e3b2e062deb495bf12dd7574b92987535bccd` — `perf: page AI recovery prefix reads`
- `dba0e8dd6f1d32115ca2c612f66e951b2a2145d9` — `test: keep AI recovery paging exact`

旧 `generation_prefix()`：

`SELECT image_id,status FROM candidates ORDER BY ordinal`
→ `fetchall()`

20k/100k recovery 会一次把完整候选 projection 搬进 Python。

现在：

- 先 `COUNT(*)` 获取 durable stored_total；
- 若 `stored_total > immutable task input`，立即 fail-closed；
- 再按 ordinal **500/批** keyset 读取；
- 20,000 candidate 固定：
  - 1 次 COUNT truth
  - 40 个真实数据页
- 原顺序、status 合法性、candidate 数量上限均保持 fail-closed。

#### 真实 CI 红灯记录

`1e7e3b2e...` 的 AI Annotation Recovery 在 Ubuntu / Windows 都出现真实 completed failure。

已读取真实 job log，失败均为新 20k 结构合同：

- expected page reads = 40
- actual page reads = 41

原因不是 candidate truth 错误，而是 20,000 恰好被 500 整除时，旧分页循环还做第 41 次空页 SELECT。

没有为了 40 次断言直接“最后一页强行 break”，因为那会丢失“store 比 immutable input 多行”的 overrun 检查。

`dba0e8dd...` 改为先 COUNT 真相，再只读取 stored_total 对应的真实数据页，并补：

`test_generation_prefix_rejects_more_rows_than_immutable_input`

保证性能合同与 fail-closed recovery 同时成立。

### 3. AI review / Commit iterator 每页重复 SQLite connection — CLOSED

提交：

`8240eafb905f8f184b2a42718656fabbb9aeb722` — `perf: reuse AI candidate read connections`

旧：

- `iter_items()`
- `iter_accepted_items()`

每 200 candidate page 都重新打开一次 SQLite connection。

这会影响：

- review 首屏所需 `label_summary()` 全候选统计；
- accepted candidate durable Commit 流。

现在：

- keyset page 仍保持 200；
- 同一次 iterator 只复用一条 read connection；
- 10,001 rows 固定 51 个 bounded page query；
- 每个 iterator connection = 2（一次 ready + 一条长生命周期 read）；
- candidate 内容、decision、accepted truth 均未缓存或改变。

`8240eafb...` 的 AI Annotation Recovery 已 completed success；最新 `7a04c91d...` 上 AI Annotation Recovery 同样 completed success，Ubuntu/Windows recovery fencing contracts 均 success。

### 4. 远程 Agent 训练失败日志整文件 read_text — CLOSED

提交：

`75b5d36ea2cc3cb54e29d64f18147a432e99df26` — `perf: bound remote training failure logs`

旧失败 fallback：

`runtime_log.read_text(...)[-6000:]`

即使最终只展示 6000 字符，也会先把整个长期训练日志读进内存。

现在：

- `_tail_log_text()` 只 seek/read 文件尾部有界字节；
- 错误优先级保持：
  `job.error → job.message → bounded runtime log tail`；
- 不改变训练成功/失败判定。

`75b5d36e...` 自身 **20/20 workflows 全绿**，其中 Remote Training Runtime success。

### 5. 本地训练模型官方 outputs：copy 后再次 full hash — CLOSED

提交：

`90ad87c597ecf8cbbe8a5a483e0a550fb3dba9cb` — `perf: hash training models during archive copy`

旧 finalization：

`shutil.copy2(source, destination)`
→ `_sha256(destination)`

对几十/几百 MiB `.pt` 产生额外完整磁盘读取。

现在：

- `_copy2_with_sha256()` 在 source→official task output 的 copy pass 同步计算：
  - exact written SHA256
  - exact written size
- `copystat()` 保留原 `copy2` 文件元数据语义；
- result `verified_models[]` 绑定实际写入 destination 的证据；
- finalization winner、恢复覆盖 outputs、算法版本归档语义不变。

`90ad87c5...` 自身 **20/20 workflows 全绿**，Training Input Integrity 与 Remote Training Runtime 均 success。

### 6. Remote Training result ZIP：解压后再次 full hash embedded model — CLOSED

提交：

`cfec5f362a18038800c8ae69c2102a894fb2fa29` — `perf: hash remote training models during extract`

旧 verifier：

- ZIP 解压 `models/*.pt` 写盘；
- 再 `_sha256(path)` 整文件读取；
- 与 manifest expected SHA 比对。

现在：

- 每个 ZIP member 在**解压写盘同一 pass**同步记录 `(written_size, sha256)`；
- embedded model 按这份 extraction evidence 与 manifest expected size/SHA fail-closed；
- outer result ZIP 的 expected SHA/size 校验继续保留；
- tampered model / undeclared member / generation identity 合同均未放宽；
- separate-object-v1 行为不变。

Remote Training Runtime 的 Ubuntu/Windows
`Remote training publication and model asset contracts`
均真实运行 `tests/unit/test_remote_training_results.py` 并 success。

### 7. Primary model lineage / evaluation 又一次 full hash — CLOSED

提交：

`7a04c91df48a09453146f086feb0ff6dde807033` — `perf: reuse archived training model evidence`

旧：

官方 outputs 已经有 `verified_models[].sha256 / size_bytes` 后，
创建 training lineage / evaluation 前又：

`model_sha256 = _sha256(primary)`

现在：

- primary ref 从 `best_model_ref / last_model_ref / verified_models[0]` 确定；
- SHA/size 直接复用**刚完成官方 outputs 归档时绑定的 verified evidence**；
- lineage、evaluation、算法版本共用同一份 artifact truth；
- 不再把主模型整文件再读一次。

最新 `7a04c91d...`：

- AI Annotation Recovery success；
- Training Input Integrity success；
- Remote Training Runtime success；
- Windows/Ubuntu Remote Training publication/model contracts success；
- Windows/Ubuntu durable preparation/integration success；
- **全部 20 个主要 workflows completed success**。

### 本轮明确保留、不盲目优化的边界

1. `CandidateStore.label_summary()` 仍需要遍历候选 JSON 才能得到真实 per-label box/image 统计。当前已经是 bounded pages + 单 read connection；在没有 profiling 证明它仍是主瓶颈前，不新增第二套 label-stat owner。
2. ModelArtifact `discover_version_artifacts()` 会重新 hash 当前本地模型/转换产物。这承担“训练结束后文件是否被替换”的当前内容身份校验，并用于 content-addressed artifact_id/Object Key，不能直接用历史 SHA 绕过。
3. `ensure_uploaded()` 不会再次 hash 本地模型；它使用 discovery SHA，并通过 provider stat / server-visible SHA/size 校验上传对象。
4. StorageProvider 的 per-object `exists()+stat()`、COCO 多 JSON decoded documents 内存项继续按上一节 handoff 约束：没有真实 OSS/S3 RTT / 峰值内存 profiling 前，不扩展新 bulk protocol 或流式 JSON parser。
5. 自动化结构合同与 CI 不替代真实 20k/50k 图片、NVIDIA Linux、OSS RTT、SQLite WAL contention、峰值 RSS、真实大模型文件 I/O profiling。



## 2026-09-27 23:xx Annotation source identity 批量化与 SHA fencing 收口（最新）

- 写入前真实远端 HEAD：`df5f00351576233c27e18ddead5c0b18adc35384`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- 当前 HEAD 自身 **20 个主要 GitHub Actions workflows 全部 completed success (20/20)**。
- Remote Material Import 子项全部 success：
  - Ubuntu contract；
  - Windows contract；
  - API；
  - Real Chrome。

### 1. COCO / VOC annotation source identity 逐文件 SQLite 往返 — CLOSED

提交：

- `0286415213d107a240556f6862e7929e23a6cb68` — `perf: batch detection source identity`
- `6d52f51259b99b829263a15af5ebcb9cf5ff87b5` — `test: align detection source batch mock`

旧 `DetectionDatasetScanner._read_annotation_source()` 每个 COCO JSON / VOC XML 都执行：

`inventory_for_keys([key])`
→ 读取并 hash 文件
→ `inventory_many([single])`

VOC 允许最多 250,000 个 XML，因此即使内容读取本身必须逐文件，SQLite 仍会形成明显 N+1。

现在：

- expected dataset_objects identity 按 **500 key/批** 读取；
- 每个文件仍逐文件读取、逐文件计算真实 SHA；
- 每个文件仍逐项校验：
  - object 是否存在于冻结 inventory；
  - listed size 与实际 size；
  - listed SHA（若存在）与实际 SHA；
- verified identity 只缓存轻量 dict，按 **500/批** 写回原 ImportCandidateStore；
- 不缓存 500 份大 JSON/XML 字节，不把 DB N+1 换成大内存；
- 1001 个 source 的结构合同固定：
  - read：`500 / 500 / 1`
  - write：`500 / 500 / 1`

#### 真实 CI 红灯记录

`028641...` 的 Remote Material Import / Ubuntu contract 曾 completed failure。

已读取真实 job log：

- 126 tests passed；
- 1 test failed；
- 失败来自上一批结构测试自己的 monkeypatch：
  `read_voc(key, maximum)`
  没有接受新生产调用传入的
  `expected_inventory=` / `identity_sink=` kwargs；
- 不是生产 source identity 逻辑失败。

`6d52f512...` 只修：

- 测试 mock 接受 `**kwargs`；
- 恢复 size mismatch 的原错误文案 `annotation source size changed while being read`。

没有为了 CI 降低生产校验。

### 2. YOLO label TXT source identity N+1 + 同尺寸换内容漏洞 — CLOSED

提交：

`df5f00351576233c27e18ddead5c0b18adc35384` — `perf: batch YOLO label source identity`

旧 `YoloImportScanner._record_text_identity()`：

- 每个 label TXT：
  - `inventory_for_keys([label])`
  - 读完 TXT 计算 SHA
  - `inventory_many([single])`
- 同时只校验 listed size；
- 若已有可信 SHA，但文件被替换成“同尺寸不同内容”，旧实现会用新 SHA 覆盖旧 evidence，而不是 fail-closed。

现在：

- `scan_annotations()` 原本就一次读取最多 100 张 image 的 label-option inventory；
- 该查询现在同时带回 `size_bytes / etag / sha256`；
- label TXT 直接复用这个 page-scoped expected inventory，不再 scalar `inventory_for_keys([label])`；
- verified label identities 在当前 100-image page 末尾一次 `inventory_many()`；
- 201 个 label TXT 的永久合同固定为：
  `100 / 100 / 1` 三次 identity write；
- YAML / dataset-list TXT 保留原兼容 scalar owner，不重写 prepare 架构。

同时新增更严格 source fencing：

- 若 dataset_objects 已有 SHA；
- 实际 TXT 与 listed size 相同但 SHA 不同；
- 必须抛 `YOLO_SOURCE_CHANGED`；
- 禁止静默覆盖旧 source evidence。

因此本项不仅收掉 SQLite N+1，还补齐了 YOLO annotation source identity 的 same-size content-change 防篡改真相。

### 当前导入链路性能状态

已确认 CLOSED：

- Remote review 250k 行不再保留 candidates/staged 双大列表；
- Remote staging 流式 executemany + late-invalid rollback；
- Remote YOLO/COCO/VOC manifest 500/批；
- 本地 COCO/VOC manifest + annotation state 500/批；
- COCO/VOC source identity expected/readback 500/批；
- YOLO label TXT identity 复用 100-image page；
- confirmed label mapping 仍全部由用户人工决定；
- Candidate/Annotation/Import owner 没有新增第二套。

### 暂不修改的已审计项

`platform_core/storage/import_tasks.py` 的 Agent publication / storage_scan source verification 仍可能对每个对象执行 `exists() + stat()`。

但当前 `StorageProvider` 正式协议只有 scalar：

- `exists(object_key)`
- `stat(object_key)`
- `list_objects(...)`

S3/OSS/Remote provider 没有通用 batch-stat 接口。为了消灭表面 N+1 而新增第二套 storage batch protocol，会扩大协议面并影响多 provider 行为；当前先不改。后续只有在真实 OSS/S3 RTT profiling 证明这是主要瓶颈时，再设计统一、可测试的 provider bulk metadata contract。

同样，COCO 多 JSON 会保留 decoded `documents[]`，属于潜在峰值内存项；目前单 JSON 有 64MiB 上限，尚无真实 profiling 证明需要引入流式 JSON parser，因此不在本轮盲目重构。



## 2026-09-27 22:xx 导入大批量内存与 Annotation SQLite 事务收口（最新）

- 写入前真实远端 HEAD：`19e986e6a8409523782cd0450ccba47452e8dbba`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- 当前 HEAD 自身 **20 个主要 GitHub Actions workflows 全部 completed success (20/20)**。
- 其中 Remote Material Import：
  - API success；
  - Real Chrome success；
  - Windows contract success；
  - Ubuntu contract success。
- 本节只记录本轮真实完成内容；结构测试仍不能替代真实 20k/50k、OSS/S3 RTT、峰值内存和 NVIDIA Linux profiling。

### 1. Remote Material review 250k 行 Python 大列表 — CLOSED

并发提交：

`0241d70458ec63ed80ebb2a83c05711dc5b43a2d` — `perf: stream remote material review truth`

旧控制面：

- `_read_review_rows()` 同时保留完整 `candidates[]`；
- 另保留完整 `staged[]`；
- 另有 `seen set`；
- YOLO/COCO/VOC 调用方再构造完整 `candidate_keys set`；
- `RemoteMaterialStagingStore.replace_many()` 又先构造 `values[]`。

最大 review 合同允许 `_MAX_REVIEW_ROWS = 250_000`，因此 20k~250k 导入会被多份 Python dict/list 放大峰值内存。

现在：

- 已验证 candidate truth 写入临时 `verified-review.jsonl`；
- `ImportCandidateStore.upsert_many()` 直接流式消费 generator；
- `RemoteMaterialStagingStore.replace_many()` 改为流式 `executemany`；
- staging 后段坏 row 时整 transaction rollback，旧 staging truth 保留；
- 只保留 annotation coverage 所需的 candidate key set，不再同时保留两份大 dict list；
- archive/payload SHA、尺寸、图片合法性、target prefix、storage identity、annotation coverage 均保持 fail-closed；
- 没有新增第二套 ImportCandidateStore / staging owner / import runtime。

新增 **10,001 行**结构合同，明确 candidate/staging 输入必须是 generator，不得退回 list/tuple。

### 2. Remote YOLO / COCO / VOC annotation manifest 每图事务 — CLOSED

提交：

`a76566b6eddb29ae8b4cf2652386c255854f99c4` — `perf: batch remote annotation manifests`

旧：

- boxes/issues/state 已经有 bounded flush；
- 但每张图仍 `store.manifest_many([single])`；
- 20k annotation image 就产生约 20k 个 dataset_manifest SQLite transaction。

现在：

- manifest row 并入已有 annotation flush；
- 顺序保持 **manifest first → annotation update**；
- YOLO 与 COCO/VOC 共用同样批量边界；
- 1001 张永久合同固定为 `500 / 500 / 1` 三次 manifest transaction；
- box/issue 内存仍有 5000 条上限，不把“N+1 修复”换成“大内存 batch”。

Remote Material Import 在该方向后续 HEAD 上已全绿。

### 3. 本地 COCO / Pascal VOC scanner 每图 manifest + annotation transaction — CLOSED

提交：

`19e986e6a8409523782cd0450ccba47452e8dbba` — `perf: batch COCO VOC annotation writes`

旧 `DetectionDatasetScanner`：

每张 COCO/VOC image 都执行：

`manifest_many([row])`
+
`annotation_batch([state], boxes, issues)`

即大数据集仍是 O(N) SQLite transaction。

现在复用原 `ImportCandidateStore`，增加私有 bounded flush：

- manifest rows：最多 500 image/批；
- annotation states：最多 500 image/批；
- box + issue：达到 5000 即提前 flush；
- manifest 仍先于 annotation batch 持久化；
- candidate、split、external class、confirmed_empty、source provenance、label mapping 规则均未改变；
- 没有新增 scanner owner/store/runtime。

1001 张 COCO 与 VOC 结构合同均验证：

`500 / 500 / 1`

Windows + Ubuntu 的 `Agent material and transport contracts` 都 completed success，当前 HEAD 总体 20/20 success。

### 当前下一项 P1：annotation source identity 逐文件 SQLite 往返

源码已确认但尚未修改：

1. `DetectionDatasetScanner._read_annotation_source()`
   - 每个 COCO JSON / VOC XML：
     - `inventory_for_keys([key])`
     - 读字节并计算 SHA
     - `inventory_many([single])`
   - VOC 最多允许 250,000 XML，因此会形成明显逐文件 DB 往返。

2. `YoloImportScanner._record_text_identity()`
   - 每个 dataset TXT / label TXT 同样做单 key inventory read + 单 row identity write。

下一步只能在保持以下真相的前提下批量化：

- 读取前/读取后 size/hash/source identity fencing；
- 文本对象变化必须 fail-closed；
- 已验证 SHA 必须进入现有 `dataset_objects` owner；
- 不因为性能去掉 annotation source evidence；
- 不新增第二套 source-identity store。

建议做法是复用 scanner 当前已有的 100/500 key page：批读 expected inventory、读取后把 verified identity 放入 bounded sink，再通过现有 `inventory_many()` 批量写回。



## 2026-09-26 21:xx AI 审核拒绝路径重复全扫收口（最新）

- 写入前真实远端 HEAD：`64015907bb115479b9297cdc1171a4fa54a1cdcd`。
- `VERSION.txt = 42.24.0`，未修改；未 merge main、未 tag、未 release、未 force push。
- `64015907...` 自身 20 个主要 GitHub Actions workflows 已全部 **completed success (20/20)**。

### 本次关闭

提交：`64015907bb115479b9297cdc1171a4fa54a1cdcd` — `perf: skip rejected AI label scans`

正式 `_decide_annotation_candidates()` 之前即使没有任何 `label_mapping`，也会先调用一次 `CandidateStore.label_summary()` 全扫候选；随后 `remap_labels()` 又扫描全部 success/empty candidate。纯“拒绝全部”最终不会有任何 Candidate 进入正式 Ground Truth，但仍承担两次不必要的大候选扫描。

现在：

- `label_mapping={}` 时不再为了“验证不存在的 mapping source”预先调用 `label_summary()`；
- 纯 `reject_unmentioned=true`、无 mapping、显式 decisions 也全部为 reject 时，不再调用 `remap_labels()`；
- 1001 个候选的 reject-all 永久合同会把 `label_summary/remap_labels` 设为 forbidden，确保不会退回全扫；
- accept / partial accept / 有 mapping 的路径继续保留 current active canonical label 的 fail-closed 重校验；
- accept + 无 mapping 仍只在最终响应需要 `label_summary` 时读取一次，不再多一次 preflight 全扫；
- Candidate→人工审核→durable Commit、fencing、正式 AnnotationRepository owner 均未改变。

因此本项只移除“不可能进入 Ground Truth”的拒绝路径冗余读取，没有放宽标签真实性校验。

### 当前下一项 P1

Remote Material review 仍允许最多 `250,000` 行，当前 `_read_review_rows()` 同时保留 `candidates[] + staged[] + seen set`，YOLO/COCO/VOC 调用方还再构造完整 `candidate_keys set`。下一步只在现有 `ImportCandidateStore + RemoteMaterialStagingStore` owner 内把已验证 review truth 改为临时 JSONL + 流式 SQLite 消费；不新增 import runtime / scheduler / store owner，并保留 payload/hash/annotation coverage 的 fail-closed 验证。



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

## 2026-09-29 — 训练快速受理、后台 Prepare、素材完整性与资源合同收口

当前基线分支仍为 `feature/external-algorithm-publishing`，`VERSION.txt = 42.24.0` 未修改。本节记录本轮代码与 targeted tests 的真实状态；GitHub Actions 在提交后仍须以最新 HEAD 的 terminal check 为准。

### 训练正式生命周期

- `POST /train/start` 只做轻量结构校验、算法身份冻结和 durable admission，返回一个正式 `TRAINING` parent；selection、标签合同、snapshot、bundle、duplicate gate 与资源决议不再阻塞创建请求。
- 本地与远程训练统一由现有 Task runtime 中的 `TRAINING_PREPARE` / `TrainingPrepareHandler` 后台准备。Parent 在 prepare 成功前保持不可领取；成功后由 `TaskRepository.activate_prepared_training()` 原子切换到正式训练 capability。
- 一个 submit 只创建一个可见 `TRAINING` parent。`TRAINING_PREPARE` 是内部 child，不进入训练任务主列表；前端 optimistic row 只临时补显示，刷新后由 durable parent 接管。
- Parent 冻结 `asset_algorithm_id / asset_algorithm_name / source version`。历史算法已删除时显示“已删除算法”，不回退为未命名，也不由前端猜字段。
- `train_worker.py` 不再二次执行资源规划，只消费 prepare 阶段已经写入的 `resolved-resources.json`。因此 MANUAL 非法资源在 Trainer process 启动前失败；AUTO 可按后端预算安全下调并把 requested/resolved/runtime 三层事实分别持久化。

### 素材完整性与删除安全

- 没有新增 repository 或 task runtime。项目级素材完整性复用唯一 `TaskKind.MATERIAL_BATCH`、`MaterialBatchHandler`、`TaskRepository`、artifact store 与 polling owner，操作名为 `AUDIT_MATERIAL_INTEGRITY`；它有专用 project-audit prepare 分支，不伪造普通素材 selection。
- `material-integrity.sqlite3` 是诊断快照，不是第二业务真相。表为 `audit_metadata`、`issue_groups`、`issue_items`，保存 revisions、问题组、受影响 image IDs 与诊断详情；详情 API 展示时重新从现有 `AnnotationRepository` / 素材读取 owner 获取当前框与图片。
- 当前问题类型：`DUPLICATE_IDENTICAL`、`DUPLICATE_ANNOTATION_CONFLICT`、`MATERIAL_OBJECT_MISSING`、`CONTENT_HASH_MISMATCH`、`INVALID_IMAGE`。重复候选使用现有 content hash 索引，Ground Truth 差异由 `AnnotationRepository` digest 判断；不在页面打开时重新全库 SHA256。
- 删除继续走现有 durable `DELETE_INDEX / DELETE_SOURCE`。删除前在 HTTP admission 与 Worker 真正执行前都复核 active TRAINING 的 selection/input freeze；命中时 fail-closed。`DELETE_INDEX` 同步移除 Annotation/Material 索引但不误删共享物理对象；`DELETE_SOURCE` 遇到共享 object key 会拒绝。
- UI 只落在“数据集/素材管理”的“重复与异常素材”，展示真实图片、bbox、标签、文件名和来源，并提供进入标注、单删、批量删、保留一条删除其他。系统不自动判断哪份 Ground Truth 正确。

### 资源与失败展示合同

- AUTO UI 只显示 Batch/Workers/Precision 自动与 GPU 自动调度；MANUAL 提供 recommendation、可证实的安全范围、`使用推荐值` 和即时超预算提示。提示不替代后台 authoritative validation。
- 后端 `training_recovery_truth` 输出唯一 `primary_error_code / primary_stage / primary_message`，并把原始错误、process return code、completion handshake、checkpoint/recovery 作为 `secondary_diagnostics`/技术证据。
- 失败详情默认只显示一个用户可理解的主因；二级诊断折叠在“查看技术详情”，工程日志继续单独折叠。前端不再根据一串原始异常自行决定最终主因。

### Owner 自查

- Training submit：仍为 `TrainingSubmitRuntime`。
- Training durable state：仍为 `TaskRepository` + 正式 `TRAINING` parent。
- Training prepare：唯一实现为 `TrainingPrepareHandler`；旧 `RemoteTrainingPrepareHandler` 仅保留 import alias，不是第二实现。
- Training execution：仍沿用既有 `TrainingHandler` 继承链。
- Material/Annotation：仍为现有 `MaterialRepository` / `AnnotationRepository`。
- Material audit/delete：仍为 `MaterialBatchHandler`。
- Polling：仍为 `PollRegistryRuntime`，未新增 `setInterval` 或第二 poll registry。
- Resource planning：仍为现有 training metrics/resource resolver；Trainer 只消费 frozen resolution。

### Targeted verification

- Frontend runtime：最终直接相关组合 `100 passed`（Draft、资源 UI、失败详情、提交幂等、任务 runtime/可见性与 cache-owner guard）；素材完整性最小合同另有 `2 passed`。
- Backend/API/unit：`68 passed`（训练受理、任务可见性、素材完整性、资源与 recovery contract）。
- Training Prepare integration：`3 passed`。
- `node --check` 已覆盖本轮修改的 `static/app.js` 与相关 training modules；`git diff --check` 通过。
- 尚未执行生产大数据 smoke、真实 GPU 资源压测或全站 browser E2E；这些不能由 targeted contract tests 替代。

## 2026-09-29 — Durable Training CI 合同收口

本节只记录 `5b84ab2267c29e5a075168d60ea46ca7729cddc2` 后 15 个 completed failure 的定向收口。`VERSION.txt` 继续保持 `42.24.0`；未扩展业务功能，未恢复旧 OOM retry，也未放宽 `TRAINING_PREPARE_REQUIRED`。

### Stale tests / guards

- cache guard 对齐既有生产引用，不再次 bump：`styles.css?v=42.24.45`、`material-upload-bootstrap.mjs?v=422533`、`material-upload-runtime.js?v=422543`。
- 旧“同卡 OOM 后降低 Batch 重试”文案合同已由正式 AUTO/MANUAL 合同替代：AUTO 的最终资源以后端 prepare 解析为准；MANUAL 展示推荐值与安全范围，超预算在 Trainer 启动前失败。
- browser fixture 中的 `Batch=2` 来自 fixture 明确给出的 CPU recommendation/default；旧用例误改已退役的高级配置 Batch/Workers 控件。用例现改为操作唯一正式 MANUAL owner，并验证用户输入 `16/4` 进入 Draft；生产 recommendation 逻辑未修改。
- Remote Training integration 不再直接运行 `TrainingHandler`：先创建 `TRAINING` parent 与 `TRAINING_PREPARE` child，确认 input state 为 `READY` 且 input-freeze、snapshot、resolved-resources artifacts 存在后，才允许 Trainer 执行。
- Remote Training、Training Input Integrity、Training Recovery 与 External Algorithm workflow 的永久 guard 已从旧函数名/旧位置更新为当前正式 owner/行为合同。

### Production regressions fixed

- 历史训练任务名称投影按 `asset_algorithm_name` → legacy `algorithm_name` → repository lookup 的顺序解析。只有兼容历史 ID 时才查 repository；项目/算法已删除的 404 降级为“已删除算法”，不再破坏整个任务列表；没有任何算法身份时才显示“未命名算法”。其他 HTTP 异常仍然抛出。
- `/train/start` 不再同步访问畅联远端接口。外部算法 realtime preflight、当前主数据校验与 analysis eligibility 由唯一 `TrainingPrepareHandler` 在后台、Worker 启动前执行；canonical `PlatformError` 会保留 error code/message 并使 parent 在 `training_input_preparation_failed` 阶段失败。

### Targeted verification

- External Algorithm Platform + Algorithm SQL Store：`100 passed`。
- Training job visibility：`11 passed`。
- Durable prepare / training worker integration：`7 passed`。
- Training request API：`36 passed`。
- Training recovery detail/API：`10 passed`（另 `7 deselected`）。
- Frontend cache + submit contracts：`22 passed`；recovery/task detail：`43 passed`。
- 单个 training dialog Real Chrome 合同：`1 passed`。
- 最新 HEAD 的 GitHub Actions 必须全部 terminal 且 failure/queued/in_progress/cancelled 均为 0 后，才能标记可部署。
