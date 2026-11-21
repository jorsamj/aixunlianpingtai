# 训练标签审核范围适配与补审闭环设计

## 背景与根因

训练 Snapshot 在 AUDIT-148 后会要求每张正式 Ground Truth 的 `annotation_scope` 覆盖本次训练的 `effective_label_codes`。这是防止未审核类别被错误当成背景的正确安全规则，必须继续 fail-closed。

现有标签 Full Audit 负责标签治理、引用、合并身份和 Material 投影一致性，不掌握某一次训练最终继承与新增后的标签合同。因此 Full Audit 通过、但某些历史部分审核素材不适配本次训练，并不矛盾。

现有 Training Picker 和 Selection Summary 只按通用 Ground Truth 状态判断可训练，不按本次 `effective_label_codes` 判断；提交入口也不消费训练适配结论。结果是页面显示可训练、任务成功创建、TRAINING_PREPARE 才在第一张异常素材处失败。

标签统一已经通过 AnnotationRepository 将 source box 与 source scope 显式映射到治理关系指定的 target，并使用 digest/CAS。合并只能迁移已有审核证据，不能补齐从未审核的其他类别。`person`、`people` 只有存在明确 `merged_into` 时才合并，禁止按名称猜测。

## 方案选择

### 方案 A：放宽 Snapshot 或自动把 scope 扩成当前标签

拒绝。该方案会制造未经人工确认的负样本，直接破坏训练准确性和 AUDIT-148 安全边界。

### 方案 B：把训练适配规则加入项目 Full Audit

拒绝。部分审核素材对某个单标签任务可能完全合法，只有绑定具体训练标签合同才知道是否存在缺口。把它定义为全项目错误会混淆职责并制造大量误报。

### 方案 C：共享服务端训练适配判定，并扩展现有选择、提交、Prepare 与任务详情链路

采用。训练标签合同仍由 `resolve_training_label_contract()` 解析；逐素材判定与 `project_training_rows()` 共用一个规则函数；前端复用现有 TrainingMaterialSummaryRuntime、TrainingSubmitRuntime、训练弹窗和任务详情 Runtime。补审仍经 AnnotationRepository 单次 CAS 提交。

## Canonical Owner 与职责

- AnnotationRepository：正式 boxes、state、scope、version、digest 的唯一 Owner。
- Label Governance：active/merged/retired 标签身份与 `merged_into` 的唯一 Owner。
- `resolve_training_label_contract()`：本次 `effective_label_codes` 的唯一 Owner。
- 训练适配判定：放在训练标签模块的无状态共享函数中，由预检和 Prepare 同时调用；不保存第二份 GT。
- Dataset Snapshot/Input Freeze：最终训练输入与 fail-closed 校验 Owner，不放宽。
- TaskRepository/ArtifactStore：Prepare 后出现状态漂移时，保留失败任务及分页问题证据；不新增任务状态机。
- 现有前端 Runtime：现有摘要、提交和任务详情 Runtime 消费新增字段；不新增 Poller、Modal Manager 或全局状态 Owner。

## 服务端训练适配合同

新增共享的逐素材判定结果：

- `compatible`：素材可按当前训练标签合同进入投影与 Snapshot。
- `issue_type`：`missing_annotation`、`partial_review_scope`、`stale_ground_truth`、`invalid_label_reference`、`material_unavailable` 等稳定类型。
- `image_id`、`filename`、`dataset_id`、`dataset_name`。
- `annotation_state`、`annotation_version`、`annotation_scope`。
- `required_label_codes`、`missing_label_codes`，不得截断。
- 当前 Material `content_sha256` 与正式 annotation digest，仅用于身份核验和审计，不向前端泄露存储凭据。
- 现有 thumbnail/content URL 与人工标注入口参数。

逐素材 scope 规则与 `project_training_rows()` 共用：

1. `annotated` 与 `confirmed_empty` 都必须覆盖全部 effective labels。
2. 历史 `*` 仅按既有兼容语义读取；新补审永不写入 `*`。
3. legacy annotated 且没有显式 scope 时，只能以现有正框标签作为最低限度证据，不能推断其他类别不存在。
4. Material 内容已变化、来源不可用、删除中或标注需要重新审核时不可兼容。
5. 停用、悬空或未映射标签继续由现有标签治理规则 fail-closed。

## API 与分页

扩展现有训练素材 API，而不是建立新审计系统：

- `POST /api/v62/projects/{project_id}/training-materials/compatibility`
  - 接收当前训练草稿中解析标签合同所需的最小字段、选中素材 ID、搜索词、问题类型、游标和页大小。
  - 服务端重新读取算法、标签治理、MaterialRepository 与 AnnotationRepository。
  - 返回 effective labels、问题总数/分类统计、当前页问题、下一游标，以及 Material/Annotation revision。
  - 单页最多 100，Repository 查询以 500 条为上限批处理；不在浏览器加载全部 bbox 或全部问题 DOM。
- 训练正式提交前，在 `_enqueue_explicit_training()` 创建任何 Durable Task 之前调用同一预检；发现问题返回结构化 409，不创建必然失败的任务。
- TRAINING_PREPARE 再次调用同一判定。如果预检后数据漂移，Prepare 把完整问题按页写入该训练任务现有 ArtifactStore，再让任务真实失败。
- 扩展现有 training task/recovery API 暴露问题摘要与分页页码；任务详情 Runtime 只在用户展开问题时读取页面，不新增轮询器。

预检结论通过 revision 和请求签名绑定当前训练草稿。Material、Annotation、标签或算法版本变化后，前端结论立即失效并重新请求；正式提交永远重新计算，不信任浏览器的 `effective_label_codes` 或兼容布尔值。

## 人工标注与补审提交

标注工作台显示：已有框、已审核标签、本次训练待审核标签。保存分为两种明确动作：

### 普通保存

- 保存 boxes 修改。
- 保留提交开始时 AnnotationRepository 中的合法 `annotation_scope`。
- 不把项目全部 active 标签写入 scope，不写 `*`。
- 新画框本身保存在 boxes 中；只有用户执行审核确认时，所选类别才作为新增 scope 证据。

### 保存并确认审核

- 待审核标签默认不选。
- 用户逐项选择；允许显式全选，也允许只确认一部分。
- 请求提交 `reviewed_label_codes`、`expected_version`、打开工作台时看到的 Material `content_sha256`，以及 boxes/state。
- 后端只允许确认当前 active canonical 标签，并仅做 `existing_scope ∪ reviewed_label_codes`；不接受 `*`，不接收浏览器提供的最终 scope。
- 所选标签如在图片中存在目标，用户必须已经补齐对应框。系统不能可靠证明“图片里绝对没有漏框”，因此界面给出强提示并要求显式确认；AI 未检出不构成自动证据。
- boxes 与新增 scope 在同一次 AnnotationRepository upsert/CAS 中提交。

提交前后核验：

1. image 仍存在、未处于删除声明状态、来源可用。
2. 当前 content SHA 与打开工作台时一致。
3. expected annotation version 一致。
4. 标签治理状态仍有效；AnnotationRepository 现有 label governance fence 保留。
5. 保存后再次读取 Material generation；如并发 Rescan 已发生则返回冲突，并保留 `annotation_needs_review` 的 fail-closed 状态，Snapshot 仍不能使用过期 GT。

本批不以猜测方式批量改写历史 scope。历史记录若仅能看到“人工保存后覆盖全部 active labels”，但没有当时逐类复核证据，则只能在训练适配页面标记为“历史完整 scope，来源证据不足”，不自动缩小或扩大；真实生产数据的进一步治理另行只读评估。

## 前端体验

训练创建弹窗保持轻量：显示“可参与 / 需补审 / 其他异常”摘要，问题存在时禁用提交，并提供“查看问题素材”。问题抽屉/现有 Modal 支持：

- 搜索 filename/image_id。
- 按异常类型筛选。
- 游标分页与总数统计。
- 缩略图、dataset、annotation state、已审核/要求/缺失标签。
- “去补审”：打开现有人工标注工作台并带入本次 required/missing labels。
- “排除本次训练”：只从当前 TrainingDraft 的 materialIds/testMaterialIds 移除，不删除、不修改正式 Material 或 Ground Truth；随后重新做适配、标签合同与 Split 准入检查。

补审成功后失效现有摘要并重新读取服务端真相。只有当前草稿的适配结果已就绪且问题数为零，TrainingSubmitRuntime 才允许提交。

## 历史与源头入口

- 结构化 YOLO/COCO/VOC 导入继续只记录导入文件真实覆盖的标签范围，不扩大到项目全部标签。
- AI Candidate 继续只把任务实际 review scope 经人工确认后写入正式 GT；AI 未检出不扩 scope。
- 标签合并继续同步映射 boxes 与现有 scope，并保留 digest/CAS；不生成其他类别证据。
- Full Audit 页面补充职责说明：通过表示标签治理/引用一致，不表示任意训练标签合同均适配；训练创建处提供任务特定检查。

## 错误与恢复

- 预检发现问题：HTTP 409 返回稳定错误码、摘要和问题入口，不创建任务。
- 预检后发生漂移：Prepare 真实失败，任务详情展示冻结时发现的全部问题页及 revisions，不假成功。
- CAS、内容代际或标签治理冲突：补审不覆盖新数据，提示刷新图片重新审核。
- 修复或排除后：重新解析 label contract、重新验证兼容性、重新计算 Split；不得沿用旧通过结论。

## 最小验证范围

按用户简化测试要求，只增加和运行直接相关验证：

1. Full Audit 通过但训练适配能列出 partial scope 与全部缺失标签。
2. source→target 合并迁移已有 scope，其他缺失标签不被补齐；`person/people` 独立与显式合并均按治理关系处理。
3. 普通保存保留 scope；明确确认只增加所选标签；CAS、内容 SHA、删除/标签变化冲突均 fail-closed。
4. 补审后素材恢复兼容，排除只改当前草稿并触发重新检查。
5. 提交前问题不创建任务；Prepare 漂移失败时任务 artifact 与分页详情可读。
6. Snapshot/AUDIT-148 既有相关测试继续通过。
7. Python/JavaScript 语法检查、相关 API 正常请求与典型错误请求、前端主要操作测试。

不进行大规模压测、真实 GPU、Rockchip、OSS/畅联云 E2E 或全仓测试；实现中继续使用批量查询和有界分页，避免 N+1 与无界 DOM。

