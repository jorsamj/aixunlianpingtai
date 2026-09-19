# 畅联云算法训练平台 — Node Control Plane / Central Assignment

更新时间：2026-09-19  
分支：`feature/external-algorithm-publishing`  
正式版本：`VERSION.txt = 42.24.0`

> 本文记录服务节点控制面与中央任务→节点分配的当前真实边界。接手时仍必须先读取远端最新 HEAD，不能把本文中的 SHA 当作固定 checkout 目标。

## 0. 最新关闭：Reusable Fixed Benchmark Training v1

2026-09-19，current version 的 `bundle_verified` Benchmark 已能安全复用到下一轮 Durable TRAINING，CLOSED。

控制面边界：

- 不新增 TaskKind / Benchmark scheduler / second training owner；训练仍由现有 Durable TRAINING、Central Scheduler、assignment/execution lease、generation fencing 与 server-confirm 管理。
- 浏览器只拿 source version / scope / snapshot / count / binding metadata，不拿 exact Test image IDs。
- submit 只绑定 source version + scope；控制面重新验证 current-version、Evaluation、scope、Snapshot 与 Test truth 后，服务端解析 exact test cohort 并冻结 independent split。
- 固定 Test cohort 与用户训练候选冲突时，服务端复用 training split 的 component relation truth 自动保留 exact / duplicate-content / group-video-session 等关联样本，避免隐藏 Benchmark 泄漏进 train/validation。
- 最终 Dataset Revision / Snapshot 只反映有效训练候选与固定 Test cohort；audit 只公开 selected/reserved/effective counts，不把隐藏 Test identities下发浏览器。
- Frontend 使用“训练候选素材”语义，明确固定评测素材由系统自动保留；Real Chrome 覆盖 browser-blind submit。
- Agent 权限不变：无中央 SQLite/NFS、无长期对象存储凭据、无 benchmark 决策权限。

实现 HEAD：
- `39f05792f5f6a25c74539d7c7dba1cfabff4e34d`
- `b22fcf66b8e598fa83cfa2fef47c2ce7c555318b`

验收：
- `39f05792...`：30/30 workflows success。
- `b22fcf66...`：25/25 workflows success。
- Training Input Integrity `35439895596`：Ubuntu / Windows success。
- Remote Training Runtime `35439898019`：API / Ubuntu / Windows success。
- Training Create First Open `35439895675`：Ubuntu / Windows / Real Chrome success。
- `VERSION.txt = 42.24.0` unchanged。

**OPEN：**真实 RK3568 / RK3576 板卡 acceptance；独立 Benchmark Registry/主动重评 owner 尚未引入；受控自动迭代策略仍保持独立后续阶段。

## 0. 最新关闭：Evaluation Benchmark Scope v1

2026-09-19，Evaluation 的严格可比性已绑定 Snapshot + 实际 verified Test Bundle，CLOSED。

控制面边界：

- 不新增 TaskKind / Scheduler owner / Evaluation DB；Benchmark Scope 随 Algorithm Version evaluation 持久化。
- Snapshot v3 冻结 test cohort、source content SHA、annotation hash/state 与 label schema。
- `snapshot_truth` 只表示固定 Snapshot Ground Truth，不足以做严格 before/after。
- `bundle_verified` 额外验证 task-owned Dataset Manifest 的 exact test IDs、source SHA、实际 materialized test image SHA、hidden label SHA 与 `training_input_policy`，形成 `evaluation_input_digest`。
- strict comparison 仅在两边：
  - Evaluation succeeded；
  - scope_id 相同；
  - 都是 `bundle_verified`；
  - `evaluation_protocol_id` 相同；
  时成立。
- Evaluation Protocol 正式 versioned：`evaluation_protocol_version=1`。
- Local training：Durable result → whitelist `dataset_manifest_ref` → Algorithm Version archive。
- Remote training：Agent 仍只做 portable execution；server-confirm 在中央端读取目标 TRAINING task 的 Snapshot + Bundle Manifest，生成同一 Benchmark Scope。
- Agent 不读取中央 SQLite/NFS，也没有收到新的长期凭据或 benchmark 决策权限。
- Frontend 只消费 persisted evaluation truth，展示“已校验 Test Bundle / 仅 Snapshot truth”和 strict/descriptive reason。

- Acceptance code HEAD：`ac8ac782632c3d63cb7ed6a8c807a826451abb5e`。
- Current-head shared regression：23 workflows / 23 success / 0 failure / 0 pending。
- Remote Training Runtime push `35436884535`：API + Ubuntu + Windows success。
- Remote Training Runtime PR `35436887856`：API + Ubuntu + Windows success。
- Parent `6c2c7c92d733176a24438c22cea570bc4786b5a8` 的 Algorithm SQL Store `35436643513`：contracts + Real Chrome lineage success。
- Parent `6c2c7c92d733176a24438c22cea570bc4786b5a8` 的 Training Task Visibility `35436643535`：Unified training job overlay truth + Real Chrome success。
- `VERSION.txt = 42.24.0` unchanged。

**OPEN：**真实 RK3568 / RK3576 板卡 acceptance。未来若做固定 Benchmark 的跨 Snapshot 主动重评，必须继续复用现有 Durable Evaluation/Training truth，不能由前端或第二套 owner 自行计算。

## 0. 最新关闭：Feedback Adoption → Iteration Outcome / Effectiveness v1

2026-09-19，feedback adoption 已形成 Algorithm Version persisted effectiveness truth，CLOSED。

控制面边界：

- 不新增 durable TaskKind / Scheduler owner；effectiveness 是版本归档阶段的派生长期 truth。
- 输入严格限定为 persisted source/new Evaluation + new training lineage supplement provenance。
- source version 使用 `training_lineage.base.version_id`，必须与 supplement provenance source version 一致，防止 provenance 自证。
- deterministic outcome 保存 candidate_set/adoption/action/source-new evaluation identities、总体 metrics delta 和 source weak-label effects。
- Evaluation 不完整或失败时保存 `not_comparable`，不伪造 improvement。
- `descriptive_only=true`、`automatic_execution=false`，不会从效果结果直接 enqueue TRAINING。
- Algorithm SQL Store 保持唯一 Algorithm Version owner；新字段 SQL round-trip 已覆盖。
- 前端版本“独立评测”只消费 persisted outcome，不从 raw feedback / draft / job 推导效果。
- UI 同屏展示 adopted feedback count、mAP50/Recall delta、弱标签变化和 Outcome/Candidate Set/Adoption provenance。

Acceptance code/test HEAD：`c26b7449b06697fcac52979e9bb8483138ebbbab`。

- Current-head shared regression at `c26b7449b06697fcac52979e9bb8483138ebbbab`: 17 workflows / 17 success / 0 failure / 0 pending.
- Algorithm SQL Store `35432975461`: contracts + Real Chrome lineage success. This run covers the Effectiveness implementation code; later commits only fixed unrelated browser test project setup.
- Online Feedback Runtime push `35433393053`: Ubuntu / Windows / Real Chrome success.
- Online Feedback Runtime PR `35433395739`: Ubuntu / Windows / Real Chrome success.
- Remote Training `35433395670`, Node Agent `35433395713`, Material Import `35433395706`, Cleaning `35433395720`, Conversion `35433395702`, RKNN `35433395700`, Portable Deployment `35433395671`, Central Assignment `35433395650`, Task Runtime Truth `35433395684` all success.
- `VERSION.txt = 42.24.0` unchanged.

**NEXT：Evaluation Benchmark Scope v1。**
利用 Snapshot 的 test image IDs、content SHA256、annotation hash 冻结 benchmark identity；严格 before/after comparison 必须绑定同一 benchmark truth。当前 v1 仍保持描述性，不宣称因果。

Rockchip physical-board acceptance 继续独立 OPEN。

## 0. 最新关闭：Supplement Candidate Set → Dataset Revision / Snapshot / Training Lineage v1

2026-09-19，Feedback Candidate 已进入现有 Durable TRAINING lineage，CLOSED。

- Candidate Set 仍由 Algorithm Version 持有，不新增 task/database owner。
- 训练提交只有在本次真实选择素材与 Candidate Set 相交时才携带 candidate_set_id；Candidate Set 不会自动 TRAINING。
- Control Plane 在 enqueue 前重新读取 Material/Annotation truth；content SHA、annotation hash/state 变化 fail closed。
- Snapshot 以最终实际 records 计算 adopted subset，而不是记录未使用 feedback。
- Dataset Revision / Snapshot 共同冻结 candidate_set_id、adoption_id、adopted feedback/material IDs 和 bounded candidate identity。
- Dataset Revision immutable ID 纳入 supplement provenance。
- Local Worker 与 Remote Agent 复用同一 provenance；Remote prepare → portable contract → Agent → server-confirm → Algorithm Version lineage 不产生第二套 identity。
- Agent 无权访问 Candidate Set DB/中央 SQLite，也不自行决定采用哪些 feedback。
- Algorithm Version 的 training_lineage 长期保存 supplement provenance。
- 前端 confirmed action / Candidate Set 恢复全部来自 version persisted truth；已冻结 Candidate Set 直接恢复 Dataset，不重新 review。
- 训练 base 仍是唯一 current verified version，因此 Candidate Set source version 与实际迭代 base owner 一致。

Acceptance code HEAD：`49becaf398403b76e4209ed35ca18aaa8ef860a1`。

- 18 workflows：18 success / 0 failure / 0 pending。
- Algorithm SQL Store `35431356487`：contracts + Real Chrome lineage success。
- Online Feedback push `35431356518`、PR `35431359456`：Ubuntu / Windows / Real Chrome success。
- Remote Training `35431359366`：API / Ubuntu / Windows success。
- Node Agent `35431359353`、Training Input Integrity `35431359267`、Material/Cleaning/Conversion/RKNN/Portable Deployment/Central Assignment/Task Runtime 均 success。
- `VERSION.txt = 42.24.0`。

**NEXT：Feedback Adoption → Iteration Outcome / Effectiveness v1。**
只从 persisted evaluations + supplement provenance 计算前后效果，不自动触发下一轮训练。真实 Rockchip 板卡 acceptance 继续独立 OPEN。

## 0. 最新关闭：Feedback → Supplement Data Candidate v1

2026-09-19，confirmed online feedback 已接入现有 supplement_data 数据草稿，CLOSED。

- 只查询当前 algorithm/version 的 confirmed feedback。
- Candidate truth 由后端基于 MaterialRepository + AnnotationRepository 生成；前端只消费 `eligible/reason_codes/candidate_digest`。
- needs_correction 未完成正式标注时不可冻结。
- freeze 使用 feedback_id + candidate_digest 二次校验，素材/标注变化 fail closed。
- candidate set 作为 Algorithm Version 长期 truth 持久化，单版本 immutable：同 set 幂等，不同 set 冲突。
- 不新建数据库 owner、不创建 Dataset Revision/Snapshot、不创建 TRAINING。
- 前端复用数据集页，Real Chrome 覆盖 review → freeze → dataset。
- Central Scheduler / Agent / Training owners 均未改变。

Acceptance HEAD：`a54e0e735b27bde400b205fe1d07ede03903a973`。

- Online Feedback Runtime push `35428464451`：Ubuntu / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35428467030`：Ubuntu / Windows contract / Real Chrome 全部 success。
- 当前 code HEAD `a54e0e735b27bde400b205fe1d07ede03903a973`：17 个相关 workflows，0 failure / 0 pending；Node Agent Executor API / Ubuntu / Windows 也全部 success。
- `VERSION.txt = 42.24.0` 未修改。

**NEXT：Candidate Set → Dataset Revision / Snapshot / Training Lineage v1。**
训练提交前重新验证冻结素材/标注 identity；只有实际进入训练选择的 feedback 子集才能进入 Revision/Snapshot/Lineage。

## 0. 最新关闭：Online Algorithm Sampling / Feedback v1

2026-09-19，线上抽检与外部回流已接入 reviewed feedback owner，CLOSED。

- feedback durable truth 为 `pending_review / confirmed / dismissed`。
- 测试发布预测与 external intake 都冻结 algorithm/version/model SHA/input SHA/source evidence。
- external intake 只 stage review，不直接写 Material/Annotation/Dataset Revision/Training。
- confirm 后才复用现有 MaterialRepository / AnnotationRepository：
  - correct → 仅在不覆盖不同正式标注时确认 prediction truth；
  - false_positive → 必须用户明确确认全标签负样本；
  - needs_correction → 保留人工修正，不自动把错误预测写入 truth。
- dismiss 无素材、标注、revision、training 副作用。
- legacy v42 automatic feedback/iteration write 已退役。
- 没有新增 Scheduler/Training owner；后续 Dataset Revision、Snapshot、TRAINING 仍走已 CLOSED 的中央链。
- Frontend 全部使用 v63 reviewed contract，Real Chrome 覆盖提交、复核、忽略与 external intake。

Acceptance HEAD：`7a1ade605b6a55e1fe9027a86dc6756af795456b`。

- Online Feedback Runtime push `35427702717`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35427704825`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Product code HEAD `05ba04f132e746ac3bd96b05790f0b526acd0236` 的其他共享 workflows 均 success；当时唯一红项是 Online Feedback Runtime，根因仅为 focused CI 缺少 OpenCV 依赖和测试使用了不存在的 MaterialRepository.list()，均已在 acceptance HEAD 修正。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：Feedback → Supplement Data Candidate / Dataset Revision Candidate v1。**

确认后的 feedback 只能先形成冻结候选/补数据草稿，用户再次确认素材范围后才能进入既有 Dataset Revision → Snapshot → Durable TRAINING 链。不得引入自动回炉 owner。

## 0. 最新关闭：Iteration Decision → Confirmed Action v1

2026-09-19，版本级迭代决策已接到显式用户确认后的正式产品动作，CLOSED。

- `confirmed_iteration_action v1` 继续由 Algorithm Version 长期持有；没有新增 scheduler/task/database owner。
- 只有 current version + exact persisted decision ID 可以确认动作；同 action 重试幂等，冲突 action fail closed。
- `needs_data` 只生成弱标签/问题样本补数据 draft，不直接改 Dataset Revision。
- `continue_training` 生成确定性的 Durable TRAINING task ID，并将 action/decision/evaluation/version/revision/snapshot identity 传入既有训练链；Central Scheduler / lease / generation / server-confirm 语义不变。
- `ready_for_business_validation` 生成带 model/revision/snapshot identity 的 validation entry，不旁路现有测试发布/部署 owner。
- `review_required` 生成 version-owned manual review entry，记录 reason codes / recommended actions，不自动执行。
- 新训练 lineage 携带 confirmed action identity，下一版本可追溯到确认来源。
- `automatic_execution=false` 保持不变；确认继续训练后，只有用户真正提交训练表单才创建/恢复固定 Durable TRAINING task。
- Frontend 使用版本 persisted truth。刷新后“已确认动作”仍可恢复继续处理，不依赖瞬时 JS state；Real Chrome 已覆盖 confirm → refresh → resume。

验收：

- Product code HEAD `d422fc21b3394edd71567a81bc34316d1172c652` shared regressions: 0 pending / 0 shared failure.
- Latest acceptance HEAD `4076f8adb376c24e32db78cf3bd15f83182ebcb4`: Algorithm SQL Store run `35424317881` contracts + Real Chrome success.
- Remote Training Runtime PR `35424280734`: API / Ubuntu / Windows success.
- Node Agent Executor PR `35424280790`: API / Ubuntu / Windows success.
- Remote Material Import PR `35424280896`: API / Ubuntu / Windows / Real Chrome success.
- Remote Cleaning Runtime PR `35424280779`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime PR `35424280823`: control-plane / Ubuntu / Windows / Real Chrome success.
- Portable Deployment `35424280766`, Central Node Assignment `35424280780`, Task Runtime Truth `35424280794`, Training Input Integrity `35424280757`, Remote RKNN Board Runtime Protocol `35424280702`, Storage Cache Governance `35424280744` all success.
- `VERSION.txt = 42.24.0` remains unchanged.

**下一主线：Online Algorithm Sampling / Feedback v1。**
生产端抽检/人工反馈只作为 reviewable intake，确认后复用现有 Material/Annotation → Dataset Revision → TRAINING → Evaluation → Decision → Confirmed Action 控制面；禁止另建自动回炉 owner。Rockchip 真实板卡 acceptance 独立 OPEN。

## 0. 最新关闭：Training Evaluation / Iteration Decision v1

2026-09-19，现有 Durable TRAINING → Algorithm Version 控制面已补齐正式独立评测后的迭代决策，CLOSED。

- Evaluation 与 Iteration Decision 都由算法版本长期持有，不新增 task owner / DB owner。
- decision 使用 server-confirm/归档后的版本 truth：evaluation_id、dataset revision、snapshot、model SHA、总体/标签级指标、FP/FN、weak labels。
- 决策复用原 TRAINING quality gate：
  - `review_required`
  - `needs_data`
  - `continue_training`
  - `ready_for_business_validation`
- 原 `eval_metric / continue_threshold / stop_threshold` 语义保持不变；没有第二套前端阈值。
- decision_id 确定性生成，weak label 严重程度顺序保留。
- `automatic_execution=false`、`requires_confirmation=true`；Central Scheduler 不会因为 decision 自动派发另一条 TRAINING。
- Algorithm SQL Store 保持 decision round-trip；历史 job 清理不影响版本决策。
- Frontend Impact Review 已完成：算法版本“独立评测”读取 persisted decision，显示决策/阈值/建议动作/FP-FN 信号，不自行推算，也不重取历史 job。
- Real Chrome 已覆盖版本 → 独立评测 → 迭代决策。

最终代码验收 HEAD：`d11d0e16998e7630bbc5811a937ba3c21395548e`。

- 17 workflow 全部 success，0 failure / 0 pending。
- Algorithm SQL Store `35422469494`：contracts + Real Chrome success。
- Remote Training Runtime `35422469499`：Windows / Ubuntu + API success。
- Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、Remote RKNN Board Runtime Protocol 等共享回归全部 success。
- `VERSION.txt = 42.24.0`。

**下一主线：Iteration Decision → Confirmed Action v1。**
决策只负责产生 truth，下一阶段才把它接到用户确认后的补数据草稿、继续训练草稿、业务验证入口；所有后续 Durable TRAINING 仍走现有 Scheduler / lease / generation / server-confirm owner，不得新造自动回炉 owner。Rockchip 真实板卡 acceptance 继续独立 OPEN。

## 0. 最新关闭：Training Lineage / Algorithm Version Provenance v1

2026-09-19，训练结果到算法版本的可追溯链已进入正式控制面 truth，CLOSED。

- Local TRAINING 与 Remote Agent TRAINING 都写同一 `training_lineage v1`。
- lineage 持久化 task / snapshot / dataset revision / base version / model / execution / device / GPU / requested+actual params / verified artifacts / outcome。
- Remote Agent lineage 使用 server-confirm 后的 execution generation、node/worker、模型 artifact truth，不信任前端推算。
- lineage builder 采用字段 allow-list；对象存储 signed URL、secret、长期凭据不会进入版本。
- Algorithm SQL Store 保持 lineage round-trip；版本成为训练 provenance 的长期 owner，而不是依赖 transient job。
- Dataset Revision 与 Snapshot 仍保持原 owner；lineage 只引用其 immutable identity，不复制 snapshot 数据。
- Frontend Impact Review 已完成：稳定算法版本 renderer 读取 persisted `training_lineage`，显示“训练溯源”；Real Chrome 证明无需历史 job refetch。

最终验收 HEAD：`c6c7289b3a13d20053e1a8aed44525a4901f5059`。

- 当前代码 HEAD `c6c7289b3a13d20053e1a8aed44525a4901f5059`：21 个相关 workflow，21 success / 0 failure / 0 pending。
- Training Input Integrity、Remote Training Runtime、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、Remote RKNN Board Runtime Protocol 均 success。
- Algorithm SQL Store / Training Task Visibility / External Algorithm Platform / Publish 等共享回归 success。
- Real Chrome 已验证算法版本“训练溯源”来自持久化版本 truth，点击查看不会重新请求历史 job。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：**在同一 Durable TRAINING owner 后增加正式 Evaluation truth 和自动迭代决策；不得创建第二套训练/版本 owner。真实 Rockchip 板卡 acceptance 继续独立 OPEN。

## 0. 最新关闭：Dataset Snapshot / Revision v1

2026-09-19，Snapshot V3 已扩展 Dataset Revision v1，训练输入身份正式进入中央控制面与 Remote TRAINING contract。

- Dataset Revision 与 split assignment 分离；同一数据 truth 可对应多个不同 Snapshot。
- revision 冻结 content SHA、storage object、平台 annotation hash/state、Canonical Annotation external provenance 和 label schema。
- Snapshot V3 同时携带 revision id 与 snapshot id。
- remote training contract v2 强制 revision SHA256；Agent 在训练前校验 bundle snapshot/revision，generation fencing 保持不变。
- server-confirm、model artifact、算法版本、durable job 均传递 revision id。
- Agent 不读取中央 SQLite/NFS；revision 仍通过 portable bundle/contract 传递。
- legacy portable snapshot 兼容保留，但新 contract 不允许缺失 revision。
- Frontend Impact Review 已完成，训练运行中心显示真实“数据版本 / 训练快照”，Real Chrome 通过。

最终验收 HEAD：`5e330fd3de9a958c2eac1ad1f18c11cf81b381b6`。

- Training Task Visibility push `35415738121`：visibility-contracts + Real Chrome success。
- 父代码 HEAD `5e2a0959a3a822f5725f684bd9351350b150a6b1`：Remote Training、Training Input Integrity、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、RKNN Board Runtime 等共享回归 success。
- Dataset Revision / Snapshot focused unit、API、frontend identity/cache tests success。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：** Training Lineage / Algorithm Version Provenance；随后自动评测和训练迭代闭环。真实 Rockchip 板卡验收继续独立 OPEN。

## 0. 最新关闭：Canonical Annotation Schema v1

2026-09-19，YOLO / COCO / Pascal VOC 的 task-owned review evidence 已正式进入统一 Canonical Annotation Schema v1。

- Parser 不变；schema 层只规范共享 evidence。
- v1 字段与旧 source_digest 语义兼容，防止历史同步标注被全量误判为变化。
- source identity、class catalog、normalized bbox、split、annotation status 统一进入稳定 digest。
- delta build 与 apply 两端均执行 canonical validation；artifact tamper、format/object mismatch fail closed。
- Agent 与中央边界不变；Agent 不访问中央 SQLite/NFS，也没有新 owner。
- Frontend Impact Review 结论：public contract 不变，无需 UI 修改；Real Chrome 已验证未回归。

最终代码 HEAD：`e262819dd7c4eb7a245e43eefc91bc452a4060fc`。

验收：

- Remote Material Import push：Ubuntu / Windows / API / Real Chrome success。
- Canonical schema builder/validator 在 Ubuntu + Windows contract 中通过。
- source_digest legacy compatibility 对 YOLO / COCO / VOC 均通过。
- Consumer-side tamper / format mismatch fencing 通过。
- Node Agent Executor、Remote Cleaning、Remote Training、Remote Conversion、Central Assignment、Portable Deployment、RKNN Board Runtime 等共享回归全部 success。
- 当前代码 HEAD 共 16 个相关 workflow：16 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：**在现有 Snapshot V3 上实现 Dataset Snapshot / Revision 与 Canonical Annotation Schema 的冻结集成。

## 0. 最新关闭：Remote storage_rescan Phase 2C — Pascal VOC annotation delta

2026-09-19，`MATERIAL_IMPORT + mode=storage_rescan` 已完成 Pascal VOC XML 增量同步，仍复用 Central Scheduler / assignment lease / execution lease / generation fencing / server-confirm / local Repository commit，没有第二套 VOC owner。

控制面与 Agent 边界：

- durable request / preflight / frontend 统一支持 `images|yolo|coco|voc`。
- Agent 通过 broker list + short-lived GET 读取 XML/image，冻结 XML key/size/ETag/SHA256、split、class catalog、normalized boxes 与 source digest；长期凭据和中央 SQLite/NFS 不下发。
- server-confirm 后中央端复用 task-owned ImportCandidateStore / RescanCandidateStore 生成 image delta 与 annotation delta。
- VOC 与 YOLO/COCO 使用同一 `ANNOTATION_NEW/CHANGED/REMOVED/UNCHANGED/CONFLICT/INVALID` 状态集合。
- 外部 evidence 与 AnnotationRepository truth 分离；review→confirm 间平台人工标注变化继续由 stale-write fencing 拒绝覆盖。
- 新增图片仍只由既有 MATERIAL_IMPORT indexer 写正式 truth；rescan 只记录 external provenance。
- 同一图片被多个 VOC XML 引用时 fail closed。
- 用户确认、mapping、quality、removed/conflict policy、标签创建顺序与 YOLO/COCO 共用同一逻辑。
- Frontend Impact Review 已完成，Real Chrome 验证 Agent VOC 产品链。

最终代码 HEAD：`5a1c18c8fc18c783a95d55f4f6a3ad826ffef69a`。

验收：

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

**OPEN：**

1. Canonical Annotation Schema v1 contract/versioning。
2. Dataset Snapshot / Revision。
3. Rockchip 用户真实板卡 acceptance。
4. TensorRT / Sophon / Ascend 继续暂缓。

## 0. 最新关闭：Remote storage_rescan Phase 2B — COCO annotation delta

2026-09-19，`MATERIAL_IMPORT + mode=storage_rescan` 已在同一 durable owner 上完成 COCO annotation JSON 增量同步。Phase 2A YOLO 继续成立，没有新增 TaskKind 或并行 annotation owner。

控制面 / Agent 边界：

- request / preflight / frontend / Worker 共用 `import_format=images|yolo|coco` truth；`dataset_yaml` 仍只允许 YOLO。
- COCO 复用现有 `DetectionDatasetScanner`，Local 和 Agent 均写 task-owned ImportCandidateStore。
- Agent 只通过 broker + short-lived GET 读取对象存储，冻结真实 COCO JSON size/ETag/SHA256、split、class catalog、normalized boxes 和 issue evidence。
- 完整图片 inventory 会保留 JSON 未引用的源图片，避免错误 MISSING。
- server-confirm 后中央端基于 frozen Material baseline + current AnnotationRepository truth 生成 annotation delta；Agent 不直接写正式 Repository。
- annotation JSON 删除/变化不会自动覆盖人工标注；用户必须确认 removed / conflict 策略。
- review 后平台人工标注变化由 stale-write fencing 拒绝覆盖。
- 新增图片仍走原 MATERIAL_IMPORT indexing owner；rescan 只补 external provenance。
- 同图跨 split、同图多 COCO document、同一 metadata 重复 object key、category id/name 冲突均 fail closed。
- rescan 关闭普通 import 的 content-dedup 语义，确保不同 object key 都保留独立 identity。
- durable confirmation 在标签创建之前冻结。
- UI 的执行位置、格式、图片/标注计数、mapping、quality、删除/冲突策略全部来自真实后端；Real Chrome 已覆盖 COCO Agent flow。

最终代码 HEAD：`ac1470c9049f7151fb6ae78daf6d21802ea6a263`。

验收：

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
- 当前代码 HEAD 16/16 相关 workflow success。
- `VERSION.txt = 42.24.0`。

**下一阶段：** Phase 2C Pascal VOC XML delta → Canonical Annotation Schema versioning。继续复用 DetectionDatasetScanner / ImportCandidateStore / AnnotationRepository，不得新造平行 owner。

## 0. 最新关闭：Remote storage_rescan Phase 2A — YOLO annotation delta

2026-09-19，`MATERIAL_IMPORT + mode=storage_rescan` 已在同一 durable owner 上增加 YOLO annotation delta，并完成前后端闭环。

控制面 / Agent 边界：

- request truth：`execution_mode=local|agent`、`import_format=images|yolo`、可选 `dataset_yaml`。
- Agent 仍使用 `intent=storage_rescan` 才可 root-scope；普通 storage_scan prefix 约束不放宽。
- Agent 扫描真实图片、`.txt`、`data.yaml`，并冻结 source object size/ETag/SHA256、split、class catalog、normalized bbox 和 issue evidence。
- review archive 经 immutable upload + server-confirm 后，中央 task store 形成 per-image source digest；Agent 不写中央 Repository。
- 中央将 source evidence 与冻结 Material baseline、当前 AnnotationRepository truth 比较，产生 `ANNOTATION_NEW/CHANGED/REMOVED/UNCHANGED/CONFLICT/INVALID`。
- 用户确认后同一个 task 切回 `storage.rescan` central worker commit。
- external source provenance 与正式平台 annotation truth 分离；应用成功后记录 source digest + synced platform annotation hash。
- stale platform annotation fencing：review 后发生人工编辑则拒绝 stale overwrite。
- 新增图片仍由原 MATERIAL_IMPORT indexer 负责图片+YOLO GT，之后只补 provenance；不复制 indexing owner。
- durable confirmation 在 label creation 之前冻结，保证失败重试没有提前标签副作用。
- UI 的执行位置、支持格式、图片计数、标注计数、mapping、quality、删除/冲突策略与后端字段一一对应。
- Real Chrome 已覆盖 Agent YOLO rescan。

最终代码 HEAD：`6505c51e1916a8aab5d506387b51d01e413b7775`。

验收：

- Remote Material Import push `35410155924`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35410158432`：API / Ubuntu / Windows / Real Chrome success。
- 父层 UI/确认顺序回归：
  - `9e8ada…` push Remote Material Import `35409879583` 全绿。
  - `c6ee2ab…` push/PR Remote Material Import 全绿。
- `VERSION.txt = 42.24.0` 未修改。

**下一阶段：** Phase 2B COCO JSON delta → Phase 2C VOC XML delta → Canonical Annotation Schema versioning。不得新造并行 parser / annotation owner。

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 2 — Agent YOLO review + label mapping + AnnotationRepository

2026-09-18，`MATERIAL_IMPORT` 的第二阶段已 CLOSED。Phase 1 的图片 ZIP 跨机器导入保持成立，Phase 2 在同一个 portable review/finalization 框架上新增真实 YOLO 数据集解析：

```text
server_zip + execution_mode=agent + import_format=yolo
```

当前真实链路：

```text
控制面选择服务器 YOLO ZIP + OSS/S3/MinIO 目标存储
→ source ZIP immutable staging(size/SHA256)
→ Agent 下载并安全解包
→ 复用 YoloImportScanner 解析 data.yaml / images / labels
→ Agent 校验图片解码、尺寸、SHA256、同包重复
→ 解析 normalized YOLO boxes / confirmed-empty / invalid sidecar / issue evidence
→ review ZIP:
   meta.json
   review.jsonl
   yolo/annotations.jsonl
   files/<selected candidate bytes>
→ generation-scoped immutable result PUT/confirm
→ 控制面重新下载 review ZIP 并验证：
   task/project/generation/source/prefix/dataset_yaml/classes
   每个 candidate 的 SHA256/size/dimensions
   每条 annotation 的 object key/split/status/box_count
   每个 box 的 line/class/normalized cx/cy/w/h
→ task-owned ImportCandidateStore 保存 external classes + annotation evidence
→ API 对外暴露 quality/external_classes
→ 用户确认 object selection + label_mapping/create_labels + quality acceptance
→ 同一 task 原子恢复为 QUEUED/indexing_queued + storage.import
→ local indexer 发布最终选中图片到目标对象存储并再次验证 SHA256/size
→ external class_id 按冻结 confirmation.label_mapping 映射平台 label code/class_id
→ normalized YOLO boxes 转像素坐标
→ 写 MaterialRepository + AnnotationRepository
→ confirmed_empty 保留为空标注真相
→ finish(SUCCEEDED)
```

关键边界：

- Agent 不打开中央 MaterialRepository / AnnotationRepository / TaskRepository / SQLite，不依赖共享 NFS。
- Agent 不持有 OSS/S3 长期凭据；仍只使用短期 transport contract。
- YOLO annotation evidence 必须先被控制面 server-confirm，再允许用户确认。
- 用户 label mapping 是 durable confirmation truth；indexer 不重新猜标签名称。
- 平台标签在 index 时必须仍为 active；若已失效则 fail closed，不能静默改标签。
- 缺失/invalid sidecar 不得擦除已有正式 annotation。
- `confirmed_empty` 会写正式 AnnotationRepository，不等同于“未标注”。
- 图片对象先完成发布与 hash/size 验证，再提交 Material/Annotation truth。
- Phase 1 的图片模式继续可用；YOLO 支持不是通过旧测试放宽，而是新增真实 Agent parser/review/commit/index 闭环。
- Windows/Linux 仍使用安全相对路径与同一 review bundle contract。

Phase 2 永久验收：

- Remote Material Import `35311171823`
  - production API：success
  - Ubuntu 24.04 contract + Agent→indexer annotation integration：success
  - Windows latest contract + Agent→indexer annotation integration：success
- 临时 draft PR #17 已关闭，**未 merge**。
- 正式 `VERSION.txt` 仍为 `42.24.0`。

Phase 1 历史验收保持：

- Remote Material Import `35308672897`
- Node Agent Executor `35308672844`
- Portable Deployment `35308672842`
- Central Node Assignment `35308672962`

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 3 — staging object lifecycle / GC

2026-09-18，远程素材导入临时对象生命周期已 CLOSED。

治理范围只包含 Agent MATERIAL_IMPORT 的 task-owned staging 对象：

- source ZIP：`remote-execution/<project>/<task>/material-input/...`
- generation-scoped review ZIP：`remote-execution/<project>/<task>/material-review/generation-N/...`

不会触碰正式目标素材对象。

真实策略：

- server-confirm review 成功后，控制面先把 review ZIP、candidate/annotation truth 写入 task artifact。
- result commit 阶段只写 durable cleanup ledger，**不在 result.json/upload-state 落盘前删除远端对象**，避免崩溃后 confirm 重试失去 review。
- task 进入 `AWAITING_CONFIRMATION` 后，storage Worker 的既有 WorkerInstance renew hook 执行精确 cleanup。
- cleanup 前重新验证 exact storage_source_id / object_key / size / SHA256 / task-owned prefix。
- size/hash 不匹配时标记 `CONFLICT`，拒绝删除。
- 对象不存在按幂等 `ABSENT` 完成。
- provider 删除失败记 `PENDING`，不反向把已 server-confirm 的导入任务标失败。
- FAILED/CANCELLED/BLOCKED 等未完成 Agent task 默认保留 7 天（`MC_REMOTE_MATERIAL_STAGING_RETENTION_SECONDS` 可配置）后再回收。
- orphan generation 的精确 review ref 从 task-owned `remote-results/N/upload.json` 恢复，不通过 key 推测。
- GC 每 5 分钟由 `storage` Worker heartbeat hook 节流运行，一次最多分页扫描 100 个任务并持久化 cursor。
- 不新增 timer/scheduler，不在 training-only Worker 读取存储凭据。
- GC 实现禁止 `list_objects` / prefix delete；只执行 exact `provider.delete(key)`。
- cleanup ledger 路径：`remote-material/staging-cleanup.json`。

永久验收：

- Remote Material Import `35312109805`：API / Ubuntu / Windows success。
- Task Runtime Truth `35312109707`：Ubuntu / Windows success。
- Storage Cache Governance `35312109834`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 4 — Agent storage_scan

2026-09-18，Agent `storage_scan` 已 CLOSED：

- 产品入口：素材存储配置 → 对象存储目录；只接受 OSS / S3 / MinIO，显式 `execution_mode=agent`。
- 控制面保存长期凭据，仅通过 execution-fenced broker 提供受 prefix 约束的分页 list 与短期 object GET contract。
- Agent 不接收长期对象存储密钥，不打开中央 SQLite，不依赖 NFS。
- Agent 端 provider 对 list/read 再做 durable prefix、cursor、对象数量、size、ETag、SHA256 约束。
- images / YOLO 均可在对象存储 prefix 上真实 review；YOLO 复用 `YoloImportScanner`。
- review ZIP 只保存 metadata / annotation evidence，原始图片继续留在正式对象存储，不重复上传。
- 控制面 server-confirm review 后才允许 `AWAITING_CONFIRMATION`；用户确认后 local indexer 再次验证原对象 size / ETag / SHA256 并写 MaterialRepository / AnnotationRepository。
- canonical task status 优先于 stale stage，前端、任务 API、PollRegistry 的远程状态语义一致。
- Phase 3 exact-ref GC 与正式 storage_scan 源对象完全隔离。
- classic `static/app.js` 进入永久语法 guard，Real Chrome 覆盖真实 storage_scan 提交流程。

永久验收（代码 HEAD `639cded30a6a2fed67275f19450cb70b4e0a9128`）：

- Remote Material Import `35316129031`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35316128986`：success。
- Central Node Assignment `35316128928`：success。
- Task Runtime Truth `35316128916`：success。
- Portable Deployment `35316129051`、Remote Training `35316128920`、Remote Conversion `35316129033`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 6 — COCO / Pascal VOC Agent server_zip

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

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 5 — COCO / Pascal VOC

2026-09-18，COCO / Pascal VOC 的远程 annotation 格式已 CLOSED，范围为 **Agent storage_scan**：

- `DetectionDatasetScanner` 只消费 brokered provider，不读取中央 SQLite/NFS，也不直接写正式项目数据。
- COCO 保留外部 category id/name，解析 images/annotations/categories 与 split；VOC 解析 object/bndbox 并为外部标签生成稳定 class id。
- 原始对象不重新打包；review archive 只携带 candidate + normalized box + split + issue + class mapping evidence。
- server-confirm 对 review schema、candidate coverage、class、normalized box、issue、prefix 再做 fail-closed 校验。
- 用户确认外部类别到平台标签映射后，local indexer 再次校验原对象 size / ETag / SHA256，并写 MaterialRepository / AnnotationRepository。
- XML DOCTYPE / ENTITY 拒绝；对象/标注文件/标注框均有明确上限。
- Phase 5 产品 UI 先只在“对象存储目录”Agent 模式开放 COCO/VOC；Phase 6 已进一步开放远程 Agent server_zip。本地目录与中央 Worker server_zip 仍不误宣称支持。
- dataset_yaml 继续只允许 YOLO。
- Integration 永久覆盖 COCO 与 VOC 从 review → mapping confirmation → local indexing → AnnotationRepository；Real Chrome 覆盖 COCO 实际提交。

永久验收（代码 HEAD `9fb67096718e5ece1b72a2acf601662fe337e1d7`）：

- Remote Material Import `35318574008`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35318574014`、Central Node Assignment `35318574002`：success。
- Task Runtime Truth `35318573876`、Storage Cache Governance `35318573935`：success。
- Portable Deployment `35318573871`、Remote Training `35318573869`、Remote Conversion `35318573929`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote MATERIAL_BATCH/CLEAN Phase 1 — Agent 清洗 / 去重

2026-09-18，Remote CLEAN 已 CLOSED，且继续保持现有唯一 durable owner：`TaskKind.MATERIAL_BATCH + operation=CLEAN`。

- 不存在并行 `TaskKind.CLEANING` handler；本地与远程共享同一 request / selection / result truth。
- local 为默认执行方式；只有显式 `execution_mode=agent` 才要求 `agent.remote`，避免中央 Materials Worker 静默抢任务。
- 后端 preflight 按真实选择范围检查 durable object evidence、OSS/S3/MinIO 存储可移植性与 online cleaning Agent；UI 只消费该 truth。
- Agent 通过 execution-fenced exact-selection broker 分页取选中素材，并按 image_id 获取短期 GET；未选素材读取直接拒绝。
- Agent 无中央 SQLite/NFS、无长期对象存储密钥，仅执行真实图像 metrics 分析。
- 控制面重新执行 `metric_issues + DurableHashIndex`，并把 verified review 提交回既有 `clean_results` 与 MaterialRepository projection。
- 用户确认/删除/保留流程不变；未确认的 durable success 继续投影为“待确认”。
- 前端新增执行位置选择、远程阶段中文状态和实际执行方式标识。
- Remote Cleaning workflow 永久覆盖 API、Ubuntu、Windows、前端 contract 与 Real Chrome。

永久验收（代码 HEAD `b41f784a3765e09a2184453e03e895a1cda0271d`）：

- Remote Cleaning `35324894972`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35324894991`：success。
- Central Node Assignment `35324894963`：success。
- Task Runtime Truth `35324895005`：success。
- Portable Deployment `35324894993`：success。
- Remote Material Import `35324894988`：success。
- Remote Training `35324895079`、Remote Conversion `35324894962`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote storage_rescan Phase 1 — image-object reconciliation

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` 已完成 Remote Agent Phase 1，仍复用 Central Scheduler / assignment lease / execution lease / generation fencing / server-confirm，没有第二套 rescan owner。

控制面与 Agent 边界：

- durable request 显式携带 `execution_mode=agent` 与 `intent=storage_rescan`。
- 根范围扫描只对 `storage_rescan` intent 开放；普通 remote `storage_scan` 继续强制 prefix。
- 创建任务时控制面冻结 MaterialRepository baseline 到 task artifact；Agent 永远不打开中央 SQLite/NFS。
- Agent 只通过 broker list + 短期 GET 做全源图片读取、decode、SHA256、size、ETag 证据；长期对象存储凭据不下发。
- server-confirm 后中央端基于 frozen baseline 分类 `NEW/MISSING/CHANGED/UNCHANGED`，并保留 `INVALID/SKIPPED`。
- 同 SHA 不同 object key 在 rescan 中保持独立对象身份，不套用普通素材导入的内容去重语义。
- 用户确认后任务切回现有 `storage.rescan` local worker 做 Repository commit；Central Scheduler 不会再次把 accepted MATERIAL_IMPORT 分配给 Agent。
- Agent review 后的中央防变更复核使用 provider `stat` 的 size/ETag/可用 SHA，不重新下载图片正文，因此 heavy I/O 仍在 Agent。
- 前端执行位置、可用节点、任务状态、等待原因、增量计数全部来自后端 truth；Real Chrome 已覆盖。

Phase 1 最终代码 HEAD：`64dc87c6e295429f79adfc813093bff33ce61587`。

验收：

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
- `VERSION.txt` 仍为 `42.24.0`。

**OPEN：**

1. storage_rescan Phase 2 annotation delta：YOLO sidecar/data.yaml、COCO JSON、VOC XML。
2. Canonical Annotation Schema versioning / adapter convergence。
3. 用户真实 RK3568 / RK3576 板卡 hardware acceptance。
4. TensorRT / Sophon / Ascend 继续暂缓。

## 0. 最新关闭：Remote MODEL_CONVERSION Phase 2 — Rockchip RKNN

2026-09-18，Rockchip RKNN Agent conversion 已 CLOSED。

- 细粒度 capability：ONNX 继续使用 `conversion`；RKNN 使用 `conversion.rknn`。
- Node Agent 通过真实 RKNN-Toolkit2 import + `RKNN.config(target_platform=...)` 探测后才上报 `conversion.rknn`；runtime truth 的 `supported_chips` 只包含节点本机实际通过 config probe 的目标。
- 控制面仅把 online + agent + effective `conversion.rknn` + probe available 的节点作为 Rockchip 转换资源。
- portable Agent 当前严格支持 RK3568 / RK3576，FP16、batch=1、静态 shape；INT8 未关闭。
- RKNN 输出由节点本地 RKNN-Toolkit2 真转换，Agent 只接受唯一非空 `.rknn`。
- Agent/result transport 继续使用 execution generation、immutable PUT、size/SHA256、server-confirm fencing。
- 控制面 commit 后将 `.rknn` 写回既有 deployment job artifacts；不会产生另一套厂商产物 truth。
- 转换成功只记为 `converted_unverified`，`hardware_verified=false`；没有板端 Runtime 验证就不能升级为已验证。
- 前端已同步 RK3576，资源是否可用完全来自后端 effective capability/probe truth。
- “RK3578”不作为 RKNN target：官方 Toolkit 当前列出的是 RK3576。现场若有“3578”设备，必须先做真实 SoC 识别。

永久验收（代码 HEAD `5a02aa5ba03e94cc731bfd0e62437c57738efab1`）：

- Remote Conversion Runtime `35330889750`：control-plane / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35330889657`、Central Node Assignment `35330889375`：success。
- Task Runtime Truth `35330889784`、Portable Deployment `35330889497`：success。
- Remote Material Import `35330889535`、Remote Training `35330889384`、Remote Cleaning `35330889291`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Rockchip RKNN 板端 Runtime 验证协议 / 产品闭环

2026-09-18，RKNN 板端验证的软件链路已 CLOSED：

- 新增细粒度 `deployment-test.rknn` capability。
- Agent 只有真实识别 Linux arm64/aarch64 的 RK3568/RK3566 family 或 RK3576，并可导入 RKNNLite 后才会上报能力。
- heartbeat 发布 `rknn_board` runtime truth，调度要求 target chip 与节点真实 SoC 完全匹配。
- 复用现有 `DEPLOYMENT_TEST` durable task，不新增板端验证数据库/第二套任务真相。
- RKNN 模型与测试图通过 portable verified object contract 下发；Agent 不打开中央 SQLite/NFS。
- 节点真实调用 `RKNNLite.load_rknn → init_runtime → inference`，回传推理耗时、输出数量和输出 shape。
- server-confirm 前后均校验原 conversion artifact 的 size/SHA256，模型在任务期间发生变化则 fail closed。
- 只有可信板端 runtime evidence 才能把原 conversion job/manifest 改成 `hardware_verified=true`。
- 产品部署中心已增加“板端验证”入口和验证成功状态展示；Real Chrome 覆盖完整页面流。

永久软件验收（代码 HEAD `05c7b93339414ac028214fd3d046dfdf7977c0a1`）：

- Remote RKNN Board Runtime Protocol `35335720990`：API / Ubuntu / Windows / Real Chrome success。
- Remote Conversion Runtime `35335720906`：success。
- Node Agent Executor `35335720915`、Central Node Assignment `35335720909`：success。
- Task Runtime Truth `35335720969`、Portable Deployment `35335720910`：success。
- Remote Material Import `35335720921`、Remote Training `35335720913`、Remote Cleaning `35335721027`：success。
- `VERSION.txt` 仍为 `42.24.0`。

**仍然 OPEN：**

1. 真实 RK3568 / RK3576 实物设备接入后的硬件 acceptance；CI 不含真实 NPU 板卡，不能把协议测试冒充成现场实机验收。
2. RKNN INT8 calibration portable transport。
3. 如果未来需要 COCO/VOC Agent server_zip，再按真实 portable transport 单独闭环。
4. TensorRT / Sophon / Ascend 暂不推进。

## 0. 最新关闭：Rockchip RKNN INT8 calibration portable transport

2026-09-18，RKNN INT8 Agent calibration 已 CLOSED：

- Rockchip Agent 资源通过统一后端 truth 暴露 `supported_precisions=["fp16","int8"]`；前端不自行推断。
- 创建 INT8 任务前冻结 calibration snapshot，绑定 dataset/split/MaterialRepository revision 与精确 object refs。
- calibration item 必须携带稳定 object_key / size / SHA256；只允许 OSS/S3/MinIO portable 对象，控制面本地路径不进入 Agent contract。
- Agent start 时为每张冻结校准图签发短期 GET，下载后逐张校验 hash/size；snapshot/count/实际文件数不一致直接 fail closed。
- 节点本地 `deployment_worker.py` 生成 `rknn_dataset.txt`，真实交给 RKNN-Toolkit2 执行 INT8 build。
- output publication、generation fencing、server-confirm 与 deployment job artifact truth 完全复用已 CLOSED 的 RKNN FP16 链路。
- INT8 成功仍是 `converted_unverified`，必须经过真实匹配板卡 RKNNLite task 才能设置 `hardware_verified=true`。
- 产品 UI 已加入 INT8 校准数据集 / split / count，并按 resource `supported_precisions` 动态启用。
- Remote Conversion 专项永久覆盖 calibration snapshot、Agent 下载/校验、API 无残留失败以及 Real Chrome INT8 提交。

永久验收（代码 HEAD `314757c1601420640acedc074e9aeb795e8a2097`）：

- Remote Conversion Runtime `35340943761`：control-plane / Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35340943851`：success。
- Node Agent Executor `35340943850`、Central Node Assignment `35340943861`：success。
- Task Runtime Truth `35340943758`、Portable Deployment `35340943913`：success。
- Remote Material Import `35340943781`、Remote Training `35340943764`、Remote Cleaning `35340943815`：success。
- `VERSION.txt` 仍为 `42.24.0`。

**仍然 OPEN：**

1. 真实用户自有 RK3568 / RK3576 板卡现场 acceptance；CI 只证明软件协议。
2. 若现场所谓“RK3578”设备存在，必须先读取真实 SoC compatible，再决定映射，不能直接当 RK3576。
3. COCO/VOC Agent server_zip 已于 Phase 6 CLOSED；不要重新实现平行导入链。
4. TensorRT / Sophon / Ascend 暂不推进。

## 0. 最新关闭：Rockchip 实机接入软件工具链

2026-09-18，Rockchip 板端 Agent onboarding 软件链路已 CLOSED：

- `node_agent.py --doctor` 对请求 capability 做 strict fail-closed 预检；失败返回非零并输出具体 issue。
- 新增 Linux/systemd 安装器 `tools/install_rockchip_agent.sh`，安装与每次服务启动前都执行 doctor。
- Token 使用 root-owned `0600` EnvironmentFile；不进入 `ExecStart` / process argv。
- 默认板端 capability 为 `deployment-test.rknn`，不把板端节点误配置为 RKNN 转换节点。
- 服务节点 UI 增加 Rockchip 板端快捷预设、RKNN capability 中文标签、真实 SoC/RKNNLite/RKNN-Toolkit2 runtime 展示。
- 一次性 Token 弹窗提供 doctor 与 systemd 安装命令；systemd 命令不回显 Token。
- 普通 Agent/Linux/Windows 路径保持兼容。
- Real Chrome 覆盖：创建 Rockchip 板端节点 → 快捷预设 → 保存一次性 Token → doctor/systemd 命令展示。

永久验收（代码 HEAD `b8caf7753994988d5161321c2536ae75e64d3252`）：

- Service Node UI `35342366446`：Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35342366573`：API / Ubuntu / Windows / Real Chrome success。
- Remote Conversion Runtime `35342369723`、Node Agent Executor `35342369838`、Central Node Assignment `35342369780`：success。
- Remote Training `35342369831`、Remote Material Import `35342369794`：success。
- Task Runtime Truth `35342369798`、Portable Deployment `35342369765`：success。
- `VERSION.txt` 仍为 `42.24.0`。

**仍然 OPEN：**

1. 用户真实 RK3568 / RK3576 板卡的现场 hardware acceptance。
2. 若设备被销售/标注为“RK3578”，先读取真实 SoC compatible，不能直接映射为 RK3576。
3. COCO/VOC Agent server_zip 已于 Phase 6 CLOSED；不要重新实现平行导入链。
4. TensorRT / Sophon / Ascend 暂不推进。

2026-09-18 capability probe hardening 已完成（HEAD `b20470c8f57ee99fcde3ff0da5f26a5be4b7124f`）：不再依赖 Toolkit 版本号猜测 RK3576 支持，而是实际执行目标平台 config probe。Remote Conversion `35344315905`、RKNN Board `35344315931`、Agent Executor `35344315955`、Central Assignment `35344316219`、Portable Deployment `35344315907` 均全绿。

**下一主线：Rockchip 真实板卡 acceptance。**

必须复用已 CLOSED 的 `deployment-test.rknn` durable truth。只有真实板卡 Agent ONLINE 且 effective capability 为 `deployment-test.rknn`，并成功执行目标 `.rknn` 的 RKNNLite inference 后，具体 conversion job 才允许写 `hardware_verified=true`。软件 CI 不能代替现场 NPU 验收。

## 0. 最新关闭：Remote MODEL_CONVERSION / ONNX Runtime

2026-09-18，`MODEL_CONVERSION` 已成为继 `DEPLOYMENT_TEST`、`TRAINING` 之后第三个真实跨机器 portable task kind。当前 CLOSED 范围明确为 **ONNX**；TensorRT / RKNN / Sophon / Ascend 等厂商 SDK 目标仍按节点真实环境单独实现，不能借 ONNX closure 宣称远程可用。

核心文件：

- `platform_core/node_agent_conversion_runtime.py`
- `platform_core/node_agent_executor_loop.py`
- `platform_core/remote_execution_transport.py`
- `platform_core/task_node_assignments.py`
- `deployment_worker.py`
- `node_agent.py`
- `tests/unit/test_node_agent_conversion_runtime.py`
- `tests/api/test_conversion_portable_contract.py`
- `.github/workflows/remote-conversion-runtime.yml`

当前真实链路：

```text
部署中心选择显式 mode=agent 的 ONNX 转换资源
→ 资源状态来自 ServiceNodeRegistry
→ 只有 fresh / enabled / effective conversion Agent 才 ready
→ 输入必须是 verified model asset / immutable object reference
→ 创建 MODEL_CONVERSION durable task(execution_mode=agent)
→ legacy conversion Worker 因 agent.remote capability fence 无法自抢
→ Central Scheduler 只分配给 Agent connection_mode
→ Agent claim / start 获得当前 execution generation
→ start payload 仅包含 signed object download + portable params
→ 节点本地下载源模型并校验 size/SHA256
→ 节点本地 Python + 节点本地 deployment_worker.py
→ 真实 subprocess 执行 Ultralytics ONNX export
→ deployment_worker 使用 ONNX Runtime 做真实 runtime verification
→ heartbeat / bounded logs / progress
→ cancel / lease loss / Agent shutdown：精确终止 ProcessIdentity 进程树
→ 本地 ONNX 重新计算 SHA256 + size
→ result-upload/prepare
→ generation-scoped immutable PUT
→ result-upload/confirm
→ server-side finalization fence
→ 控制面从对象存储重新下载并复核 size/SHA256
→ 写回 deploy/jobs/<task>/artifacts/model.onnx + manifest.json + job.json
→ finish(SUCCEEDED)
→ deployment center 继续使用原有产物列表/下载 truth
→ 清理 Agent execution workdir
```

关键边界：

- Agent conversion runtime 不打开中央 SQLite，不依赖 NFS，也不执行控制面的 `job_dir / worker_path / python_path`。
- 节点只使用本机 `deployment_worker.py` 和本机 Ultralytics Python。
- start 前会再次检查“当前 Agent 是否仍有对应 runner + effective capability”；如果 runner 未注册、恢复不安全或 capability 已撤销，**不会调用 start_execution**，只让 assignment lease 失效/重分配。
- Agent 启动会清理 persisted conversion ProcessIdentity；清理无法证明时 runner `ready=false`，heartbeat 动态撤销 `conversion`。
- 源模型下载严格校验 Content-Length / size / SHA256。
- 远程成功只接受 `job.status=done + runtime_verified=true + validation_status=runtime_verified + manifest runtime_verified`。
- Agent 输出必须唯一且非空的 `.onnx`；未通过 runtime verification 不允许上传成功结果。
- 输出 PUT 继续绑定 Content-Length + SHA256 metadata + no-overwrite，并按 execution generation 隔离。
- server-side conversion commit 再次下载对象并校验 hash/size，防止“对象存储成功但部署中心没有产物”的半闭环。
- 已验证 ONNX 最终落回既有部署产物目录，因此现有产物列表、下载、打包逻辑继续使用同一 truth。
- 产品不会自动把所有 ONNX 转换迁移到 Agent；只有用户显式选择 `mode=agent` 资源才走远程。
- `mode=agent` 资源没有在线 effective `conversion` 服务节点时显示不可用，创建时也会再次检查。
- portable staging 对 Agent 资源失败时 fail closed，禁止静默回退 local。
- 当前 remote conversion CLOSED 仅包含 ONNX；厂商转换目标仍保持原真实边界。

最终永久验收：

- Remote Conversion Runtime `35306100598`
  - control-plane：success
  - Ubuntu 24.04 Agent：success
  - Windows latest Agent：success
- Node Agent Executor `35306100599`
  - API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Central Node Assignment `35306100621`
  - API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Portable Deployment `35306100612`
  - production API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Remote Training Runtime `35306100615`
  - production API：success
  - Ubuntu 24.04：success
  - Windows latest：success

临时 draft PR #15 仅用于读取 PR-triggered Actions，已关闭，**未 merge**。  
当前 formal `VERSION.txt` 仍为 `42.24.0`。

**下一主线：Remote MATERIAL_IMPORT Runtime。**

目标：把素材导入节点做成第四个真实 portable task kind，优先覆盖“ZIP / 图片批量导入 → 解包/解析 → 标签格式识别/转换 → 清洗前置检查 → 上传配置的 OSS/S3/MinIO → 中央 MaterialRepository 只提交已验证 metadata/object refs”。不能让远程节点直接打开中央 `images.sqlite3` / `annotations.sqlite3`，也不能依赖共享 NFS。

## 0.1. 最新关闭：Remote TRAINING Runtime

2026-09-18，`TRAINING` 已成为继 `DEPLOYMENT_TEST` 之后第二个真实跨机器 portable task kind。  
这不是旧 `remote_train_server.py` 的 ZIP 上传旁路，也不要求远端节点访问控制面 SQLite / NFS。

核心文件：

- `platform_core/remote_training_tasks.py`
- `platform_core/remote_training_transport.py`
- `platform_core/remote_training_results.py`
- `platform_core/node_agent_training_runtime.py`
- `platform_core/node_agent_executor_loop.py`
- `platform_core/agent_execution.py`
- `node_agent.py`

当前真实链路：

```text
POST /api/v12/.../train/start(target=remote)
→ 创建目标 TRAINING(QUEUED, remote_input_state=PREPARING)
→ 创建独立 TRAINING_PREPARE durable task
→ training-prep Worker 锁定 split / snapshot
→ 生成或复用 verified portable training bundle
→ 安全 ZIP 归档 + SHA256 / size / member_count / snapshot_id
→ 上传 OSS / S3 / MinIO，并再次验证服务端对象证据
→ 首次母模型使用 allow-listed official reference；
  迭代训练强制使用最新可训练上一版本并转为 verified model asset
→ 目标 TRAINING payload 原子升级为 READY + remote_execution
→ Central Scheduler 只把 target=remote TRAINING 分给 Agent node
→ Agent claim / start，获得唯一 execution generation
→ 下载并验证 bundle / base model
→ 节点本地 Python + 节点本地 train_worker.py 启动真实 subprocess
→ heartbeat / bounded log / progress
→ cancel / lease loss / Agent shutdown：按 ProcessIdentity 精确终止进程树
→ 训练自然结束后仍先证明 DataLoader/子进程树清理完成
→ best / last 本地重新计算 SHA256 + size
→ training-models/prepare → generation-scoped immutable PUT → confirm
→ 生成 manifest-only training result bundle
→ result prepare / PUT / confirm
→ server-side finalization gate
→ verified model assets 写回 ModelArtifactService / 算法版本 truth
→ finish(SUCCEEDED / PARTIAL_SUCCESS)
→ 清理 execution workdir
```

关键边界：

- `TRAINING_PREPARE` 是独立 background Worker，不占 GPU training Worker。
- 明确 `target=remote` 的训练在 portable contract 未 READY 前既不能发给 Agent，也不能回退本机节点。
- portable bundle 解包拒绝绝对路径、`..`、反斜杠逃逸、symlink、重复成员和超出 durable evidence 的展开。
- Agent training runtime 不 import 中央 `TaskRepository`、不打开 `tasks.sqlite3`、不要求共享 NFS。
- 远程 Agent 不接受控制面 `python_path / runner_path / stored_path` 作为本机路径。
- 当前远程训练执行器为 Ultralytics；Paddle remote training 尚未宣称 CLOSED。
- success / cancel / fence / shutdown 前都要求本机进程树状态可证明；清理无法验证时 fail closed，并保留 process identity 供恢复。
- process identity 持久化不包含 Node / Assignment / Execution secret。
- Agent 当前实现能力为 `deployment-test + training`；`training` 只有在 `AgentTrainingRunner.ready` 时才进入 heartbeat 的 effective capabilities。
- 若启动恢复发现旧训练进程无法安全终止，Agent 会动态撤销 `training` capability，而不是继续领取新训练。
- 结果与模型对象均按 execution generation / immutable key 隔离；旧 generation 不能覆盖新代。
- finalization 之前必须完成 server-confirmed 模型与结果校验；Agent 自报路径不是模型 truth。
- 修复了一个真实 Agent 参数缺省问题：portable params 中缺失/显式 `None` 现在正确回退默认值，不再触发 `int(None)` 导致训练在 subprocess 启动前失败。

最终永久验收（当前实现 HEAD 的 PR-triggered validation）：

- Remote Training Runtime `35303815439`
  - Ubuntu 24.04：success
  - Windows latest：success
  - production API：success
- Node Agent Executor `35303815460`
  - Ubuntu 24.04：success
  - Windows latest：success
  - API：success
- Central Node Assignment `35303815499`
  - Ubuntu 24.04：success
  - Windows latest：success
  - API：success
- Portable Deployment `35303815438`
  - Ubuntu 24.04：success
  - Windows latest：success
  - production API：success

临时 draft PR #14 仅用于验证，已关闭，**未 merge**。

当前 formal `VERSION.txt` 仍为 `42.24.0`。

**下一主线：Remote MODEL_CONVERSION Runtime。**

现有 conversion handler 仍包含中央 `job_dir / worker_path / python_path` 等 path-bound 语义，不能直接发到远端 Agent。下一阶段应沿用已关闭的 portable execution 框架：

1. 输入模型必须来自 verified model asset / object reference。
2. 转换工具与 Python/SDK 路径由节点本地 capability/runtime 决定，禁止复制中央绝对路径。
3. Agent-side conversion subprocess 继续受 execution lease / cancel / exact process-tree fencing。
4. 转换输出先本地 hash/size，再 immutable object upload + server confirm。
5. server-confirmed conversion asset 完成后才允许 finalization。
6. Windows 可支持其真实可运行的转换；需要 NVIDIA/Linux/厂商 SDK 的目标按节点 capability 精确调度，不伪装跨平台可用。

## 1. 已关闭：服务节点控制面

已实现真实服务节点 registry + Agent heartbeat，不是页面模拟数据。

核心文件：

- `platform_core/service_nodes.py`
- `platform_core/node_agent_runtime.py`
- `node_agent.py`
- `static/modules/service-node-runtime.js`
- `static/service-node-bootstrap.mjs`
- `static/service-nodes.css`

节点支持：

- 新增 / 编辑 / 删除 / 启用 / 禁用。
- 一次性 Agent Token；数据库只保存 hash。
- Bearer Token heartbeat 鉴权。
- `ONLINE / OFFLINE / DISABLED / NEVER_CONNECTED`。
- allowed / reported / effective capabilities 分离。
- CPU、内存、磁盘、GPU、显存、温度、利用率、Torch、CUDA、Agent 进程资源。
- Worker / durable task 投影。
- Windows / Linux 跨平台 Agent 本机探测。
- `nvidia-smi` 通过 `shell=False` 调用。

用户级节点能力：

`training`、`material-import`、`cleaning`、`annotation`、`video`、`conversion`、`deployment-test`、`model-upload`。

服务节点后端 focused CI 已通过；服务节点 UI 的 frontend + Real Chrome CI 已通过。

## 2. 已关闭：中央 durable task → node assignment

核心文件：

- `platform_core/task_node_assignments.py`
- `platform_core/training_recovery_api.py`
- `task_worker.py`
- `tests/unit/test_task_node_assignments.py`
- `tests/api/test_central_scheduler_api.py`
- `.github/workflows/central-node-assignment.yml`

中央 assignment 是控制面 truth，但**不是第二套 task 状态机**。

表：

`task_node_assignments`

关键约束：

- `(task_id, generation)` 主键。
- 对 `ASSIGNED / CLAIMED` 建 partial unique index，保证一个 task 同时最多一个 active assignment。
- 调度事务使用 `BEGIN IMMEDIATE`。
- schema 初始化发生在调度事务之前，禁止在 `BEGIN IMMEDIATE` 后执行 `executescript()`，避免 SQLite 隐式提交破坏原子性。
- resolved execution config 会持久化 node、capability、device、GPU、build、runtime snapshot。
- TRAINING 优先按可用显存，其次 RAM / CPU，并对节点现有 active assignment 施加高权重负载惩罚。
- MATERIAL_BATCH 根据真实 operation 映射到 cleaning / annotation / material-import。

当前中央调度 API：

- `GET /api/v63/scheduler/assignments`
- `POST /api/v63/scheduler/allocate-next`
- `POST /api/v63/scheduler/assignments/{task_id}/release`

中央 assignment 已经从现有单一 additive runtime-router 集成点挂入，不新增第二个 `app.py` route owner。

## 3. 已关闭：旧 Worker 自抢 fencing

`task_worker.py` 已改为：

`AssignmentAwareFencedTaskRepository`

当 queued task 已存在 active central assignment 时，legacy Worker 的 `claim_next()` 必须拒绝自抢，并保留：

`CENTRAL_NODE_ASSIGNED: waiting for Agent execution on node <node_id>`

assignment 释放后，旧 Worker 可恢复正常 claim。

这保证了迁移期不会出现：

- Central Scheduler 已把任务分给 A 节点；
- 旧 Worker 又从共享 SQLite 把同一任务抢走；

这种双执行竞争。

## 4. CI 验收

Central Node Assignment permanent workflow：

`.github/workflows/central-node-assignment.yml`

验证 run：

`35288111906`

结果：

- API：success
- Ubuntu 24.04 contract：success
- Windows latest contract：success

覆盖：

- 在线 / stale / disabled / capability mismatch 节点选择。
- TRAINING 最优节点和多 GPU 选择。
- execution snapshot 持久化。
- MATERIAL_BATCH capability 映射。
- 并发 `allocate-next` 只产生一个 active assignment。
- assignment claim / lease expiry reclaim。
- release 后 generation + 1。
- central assignment 对 legacy Worker 的永久 fencing。
- schema script 不在 assignment transaction 内执行。
- Scheduler API allocate/list/release。
- `VERSION.txt == 42.24.0`。
- `git diff --check`。

用于读取 PR-triggered Actions 详情的临时草稿 PR 已关闭，未 merge `main`。

## 5. 当前明确不做的假方案

不要让远端 Agent 直接运行现有 `task_worker.py` 去访问控制面的 SQLite / NFS，然后把它称为“多机调度”。

原因：

- SQLite over NFS 不是最终可靠控制面。
- 会把 DB 文件锁、artifact 路径、进程恢复、租约边界扩散到远端节点。
- 中央控制面无法稳定成为唯一任务 truth。

因此远端执行必须通过后续 HTTP Agent executor protocol。

## 6. 已关闭：HTTP Agent Executor Control Protocol

控制面已经把“中央 assignment”安全转换成唯一真实 execution lease，不要求远端 Agent 访问中央 SQLite / NFS。

核心文件：

- `platform_core/agent_execution.py`
- `platform_core/service_nodes.py`
- `platform_core/training_recovery_api.py`
- `tests/unit/test_agent_execution.py`
- `tests/api/test_agent_executor_api.py`
- `.github/workflows/node-agent-executor.yml`

已实现协议：

```text
Task QUEUED
→ CentralTaskAllocator 选择 node
→ Agent 用 Node Token claim 自己的 assignment
→ 控制面签发 Assignment Lease Token
→ Agent start
→ 控制面在 BEGIN IMMEDIATE 内再次验证：
   Node Token / enabled / heartbeat / capability / Assignment Lease
→ 唯一 QUEUED → RUNNING
→ tasks.attempt + 1 作为 execution generation
→ 签发 Execution Lease Token
→ assignment RELEASED(reason=execution_started)
→ Agent heartbeat / log / begin-finalization / finish
→ 中央 TaskRepository 继续作为唯一任务 truth
```

三个 token / fence 的职责不可混用：

1. **Node Token**：证明请求来自哪个已登记服务节点；支持 rotate，旧 token 立即失效。
2. **Assignment Lease Token**：只允许该节点启动这一条已 claim assignment；不能重复 start。
3. **Execution Lease Token + generation**：只允许当前执行代 heartbeat / log / finalization / finish；旧 generation 永久失效。

关键生产语义：

- start 的 `QUEUED → RUNNING` 与 assignment 释放在同一个 `BEGIN IMMEDIATE` 事务。
- Node Token 在 start 事务内再次对照最新 `token_hash`，堵住“前置鉴权后刚好 rotate”的并发窗口。
- 启动前必须先证明 task payload 可读；payload 缺失/损坏时 task 仍保持 QUEUED。
- 节点 disabled 后不再 claim/start 新任务，但已有有效 execution 仍可 heartbeat/finish，避免只能等 lease 超时。
- RUNNING task 的 cancellation truth 仍由中央 TaskRepository 决定；`CANCEL_REQUESTED` 只能 finish 为 `CANCELLED`。
- `begin_finalization` 沿用现有 finalization/cancel 原子语义。
- remote log 只能追加到 task 自己的服务端 `log_ref`，单次 64 KiB 限制，并受 execution fence。
- 控制面不会接受远端 PID 作为本机进程 PID；远端进程树后续由 Agent 本机负责终止。
- start 响应明确声明：
  - `shared_sqlite_required = false`
  - `shared_nfs_required = false`
  - 大型 artifact 使用后续 object-storage transport。

控制面 API：

- `POST /api/v63/node-executor/{node_id}/assignments/claim`
- `POST /api/v63/node-executor/{node_id}/assignments/{task_id}/start`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/heartbeat`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/logs`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/begin-finalization`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/finish`

永久 CI：

`.github/workflows/node-agent-executor.yml`

验证 run：

`35288805083`

结果：

- API：success
- Ubuntu 24.04 contract：success
- Windows latest contract：success

覆盖了单次原子 start、错误/重复 assignment token、跨节点冒领、disabled 节点收尾、取消优先、finalization、remote log、lease expiry 后 generation fencing、Node Token rotate race、payload 缺失不启动、非法 generation 422、以及 VERSION / source guards。

临时 CI 草稿 PR #7 已关闭，未 merge。

## 7. 已关闭：Remote Portability Gate + Production Runtime Mount

为防止“中央绝对路径任务被误发到远程 Agent”，中央调度现在区分：

- `connection_mode=local`：允许现有 legacy/path-bound task，适用于控制面与 Worker 共机或明确共享本地运行环境。
- `connection_mode=agent`：只有任务显式携带版本化 `remote_execution` portable contract 才能成为调度候选。

当前 contract：

```json
{
  "version": 1,
  "task_kind": "<TaskKind.value>",
  "transport": "object-storage-v1 | agent-artifact-v1"
}
```

关键约束：

- 不根据旧 payload 中的路径“猜测”任务是否可远程执行；无 contract 一律 fail closed。
- contract 的 `version`、`task_kind`、`transport` 必须全部匹配。
- Scheduler 的 `resolved_execution_config.remote_execution` 只保存白名单字段，不复制 signed URL、凭据、中央绝对路径或任意嵌套数据。
- legacy task 在只有 agent 节点时保持 `QUEUED`，不会制造一个必失败的远程 assignment。
- local 节点仍保持旧任务兼容能力。
- HTTP Agent executor 测试任务已经显式使用 portable contract，避免测试绕过真实生产语义。

Portability gate 验收：

- Central Node Assignment run `35290891091`：API / Ubuntu / Windows 全绿。
- Node Agent Executor run `35290891208`：API / Ubuntu / Windows 全绿。

同时修复了一个实际生产挂载缺口：此前 v62/v63 runtime 子路由只在 focused test 中直接实例化，生产 `app.py` 没有挂载组合 router。现在生产 app 只挂载一次：

```python
app.include_router(training_recovery_router(
    get_project, shared_task_repository, shared_task_artifacts,
))
```

由 `platform_core/training_recovery_api.py` 继续单一拥有：

- training recovery
- training material picker
- service nodes
- central scheduler
- node executor

新增 AST 永久契约，禁止漏挂载、重复挂载或把 v63 子路由重新散落到 `app.py`。

Production mount 验收：

- Central Node Assignment run `35291195275`：API / Ubuntu / Windows 全绿。
- Node Agent Executor run `35291195262`：API / Ubuntu / Windows 全绿。
- 临时 CI PR #9 / #10 均已关闭，未 merge。

## 8. 已关闭：Portable Deployment Transport

部署测试已经成为第一个具备真实 portable transport contract 的 task kind。

当前 durable task 只保存对象存储引用和完整性证据，不保存临时签名 URL：

- 测试图片：`storage_source_id / object_key / sha256 / size_bytes / content_type`
- 项目模型：复用统一 `ModelArtifactService` 的 OSS / S3 / MinIO 资产。
- 官方模型：仅保存 allow-listed model reference。
- 输出：只保存 durable storage ref；Agent start 不再收到中央 `input_path / model_path / runner_path / python_path`。

`start` 仅为输入/模型生成短期 GET；输出使用 `prepare-after-local-hash-v1`，不在 start 阶段提前签 PUT。

验收：

- Portable Deployment run `35292400487`：production API / Ubuntu / Windows 全绿。
- 同批 Agent run `35292068629`、Central run `35292068610` 全绿。
- 临时 CI PR #11 已关闭，未 merge。

## 9. 已关闭：Hash-bound Remote Result Publication

远程部署测试的结果发布已经进入 execution fencing，不再接受“Agent 上传一个文件后直接说成功”。

真实链路：

```text
Agent 本地推理完成
→ Agent 本地计算 output SHA256 + size
→ POST result-upload/prepare
→ 控制面验证 Node Token + Execution Lease + generation
→ 控制面生成 generation-scoped object key
→ 签发绑定 Content-Length + SHA256 metadata + 禁止覆盖的短期 PUT
→ Agent PUT
→ POST result-upload/confirm
→ 控制面 stat 对象并核对 size + SHA256 metadata
→ durable finalization transaction 原子决定 cancellation 或 commit
→ 写 remote-results/<generation>/result.json
→ /finish(SUCCEEDED) 强制使用服务端 confirmed result_ref
```

关键 fencing：

- 实际结果 key 为 `.../output/generation-N/result.jpg`，旧 generation 的 signed PUT 不会占用新 generation 的对象。
- S3 / MinIO 签名绑定 `Content-Type`、`Content-Length`、`x-amz-meta-sha256`、`If-None-Match: *`。
- OSS 签名绑定 `Content-Type`、`Content-Length`、`x-oss-meta-sha256`、`x-oss-forbid-overwrite: true`。
- signed PUT URL 只返回给当前 Agent，不写 Scheduler truth，也不写 durable upload state。
- `remote-results/<generation>/upload.json` 只保存 hash / size / storage ref / node / generation。
- 已上传但 confirm 前断线时，只要对象现有 size/hash 完全一致，prepare 可幂等恢复；冲突对象 fail closed。
- confirm 时对象缺少 SHA256 metadata、size 不符、hash 不符均禁止成功。
- confirm 在对象验证后复用 `begin_finalization()` 的数据库事务作为 commit gate，cancel 与 result publication 不能同时获胜。
- portable deployment 未 confirm 前禁止 `begin-finalization`，也禁止 `finish(SUCCEEDED/PARTIAL_SUCCESS)`。
- Agent 自报的 `result_ref` 不可信；成功 finish 强制使用当前 generation 的服务端 confirmed result_ref。

新增控制面 API：

- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/result-upload/prepare`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/result-upload/confirm`

验收：

- Node Agent Executor run `35295427105`：API / Ubuntu / Windows 全绿。
- Portable Deployment run `35295427110`：production API / Ubuntu / Windows 全绿。
- Central Node Assignment run `35295427100`：API / Ubuntu / Windows 全绿。
- 临时 CI PR #12 已关闭，未 merge。

## 10. 已关闭：Agent-side Real Deployment Runtime

远程部署测试现在已经真正由 `node_agent.py` 在服务节点本机执行，不再只是控制面协议或模拟 handler。

核心文件：

- `platform_core/node_agent_executor_runtime.py`
- `platform_core/node_agent_deployment_runtime.py`
- `platform_core/node_agent_executor_loop.py`
- `node_agent.py`
- `tests/unit/test_node_agent_deployment_runtime.py`
- `tests/unit/test_node_agent_executor_loop.py`
- `tests/unit/test_node_agent_entrypoint.py`

真实链路：

```text
Node Agent heartbeat ONLINE
→ 单并发 executor loop claim assignment
→ /start 获取 Execution Lease + sanitized portable payload
→ task-local workdir
→ 下载输入 / 项目模型并校验 size + SHA256
→ 官方模型仅允许 allow-list reference
→ 使用节点本地 Python + 节点本地 runner
→ 启动真实 subprocess
→ ExecutionLeaseMonitor 周期 heartbeat / cancel / fence
→ cancel / lease 丢失 / Agent shutdown 时按 ProcessIdentity 精确终止进程树
→ 本地结果计算 SHA256 + size
→ result-upload/prepare
→ generation-scoped PUT
→ result-upload/confirm
→ begin-finalization
→ finish(SUCCEEDED)
→ 清理 task-local workdir
```

关键边界：

- Agent runtime / executor loop 不 import 中央 `TaskRepository`、不打开 `tasks.sqlite3`、不依赖共享 NFS。
- `node_agent.py` 只向控制面上报当前 build **真实可执行** 的远程能力；当前只开放 `deployment-test`，不会虚报 training / conversion。
- executor 只有在首次 heartbeat 成功后才启动；Agent 尚未被控制面确认在线时不会抢任务。
- 当前 executor 单并发，避免同一 Agent build 在资源隔离尚未扩展前并行抢多个部署测试。
- 输入/模型下载逐块验证长度和 SHA256；临时文件完成验证后才原子替换。
- 节点 runner 必须位于 Agent runtime root，禁止把控制面 `runner_path/python_path` 当成远端路径。
- lease/cancel/shutdown 都会终止精确子进程树；stale generation 不发布终态。
- 成功/失败/取消后均停止 lease monitor 并清理执行工作目录。

永久验收：

- Node Agent Executor run `35297453169`
  - API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Portable Deployment run `35297453136`
  - production API：success
  - Ubuntu 24.04：success
  - Windows latest：success

本轮补充永久 guard 后，`node_agent.py`、`node_agent_executor_loop.py` 以及入口/单并发测试均已进入两套永久 workflow。

**下一主线：Remote TRAINING Runtime。**

目标不是让远端 Agent 访问中央 SQLite/NFS，而是继续沿用当前已验证的控制面与对象存储协议：

1. 将训练输入变成 portable dataset/bundle object contract。
2. Agent 节点下载并完整校验 dataset/model base。
3. 节点本地调用真实 Ultralytics/Paddle training runtime。
4. progress / metrics / logs 继续回到中央 durable task truth。
5. cancel / lease loss 精确终止训练进程树并释放 GPU/CPU/RAM/临时文件。
6. best/last 模型通过统一 `ModelArtifactService` / object storage 回传并验证。
7. 只有 server-confirmed 模型资产完成后才允许训练任务 finalization。

