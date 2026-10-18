# 畅联云算法训练平台｜训练质量与模型评测可信度专项问题追踪（2026-10-18）

## 接手信息

- 仓库：`jorsamj/aixunlianpingtai`；唯一长期开发分支：`feature/external-algorithm-publishing`。
- 开发起点 HEAD：`e30a676276b741d14c30e1674edf5fc86a6e377b`；正式 `VERSION.txt`：`42.24.356`（不得擅改）。
- 本文为**跨会话持久化的唯一专项进度入口**。每一项必须写明复现证据、影响边界、修复提交、测试结果及后续事项。
- P0/P1 表示工作顺序，而不代表已有确凿生产缺陷。缺陷须经代码路径及失败测试证实；未知的生产状况必须标记“待现场核验”。
- 不重建 MaterialRepository/AnnotationRepository，不自动修改 GT、冻结 Test、Snapshot、历史模型或 103455 张生产素材；不进行生产部署。

## 问题登记与状态

| ID | 优先级 | 问题 | 初始结论 | 状态 | 主要代码 / 验收 |
| --- | --- | --- | --- | --- | --- |
| TQ-01 | P0 | Train/Val/Test 多类正样本及来源覆盖 | 现有分组隔离；完整分层不保证 | **阶段二已提交：Ubuntu/Windows 定向回归通过，生产数据待验收** | `training_splits.py`、`training_tasks.py`；按类独立图片/框/来源证据 |
| TQ-02 | P0 | 视频邻帧、近重复和缺失来源元数据导致疑似泄漏 | 已隔离 SHA/已知关系；未知来源需保留未知状态 | 待核验 | 导入扫描与 split；不可跨组，不能假装未知已安全 |
| TQ-03 | P0 | 训练选择的正式标注质量准入不统一 | CLEAN 审计不等同训练准入 | **第一阶段代码验收：Ubuntu/Windows 定向测试通过；全量及生产验收待核验** | `annotation_quality.py` + freeze；按严重度区分阻断/人工复核 |
| TQ-04 | P0 | 97% 高 Val mAP 的真实可信度 | 无实际任务报告，不能宣告指标伪造 | 待核验 | 指标口径、类别参与数、数据独立性、独立 Test |
| TQ-05 | P0 | Ultralytics `ap_class_index` 与 `box.maps` 类别对应有潜在错配 | 已证实 compact 数组与 dense `maps` 被按位置混用、NumPy 真值判定可能失败 | **修复与 CI 已通过；历史模型报告未重算** | `train_worker.py`、定向 Python 单测；丢类、稀疏 class_id |
| TQ-06 | P0 | 无 GT 类别及独立测试结果可评估性提示 | 总体 mAP 可隐藏测试中无正样本的已声明类别 | **后端修复与 CI 已通过；页面展示待验收** | `training_evaluation.py`、质量中心；不得宣告零样本类别合格 |
| TQ-07 | P0 | Val/Test 推理 `imgsz` 等协议证据未完全统一 | 常规 Val 与双路径盲测未全显式传 imgsz | **修复与 CI 已通过；A800 实际尺寸仍待实测** | `train_worker.py`、`checkpoint_validation_worker.py`；真实推理参数留证 |
| TQ-08 | P0 | 历史受保护重复素材与 GT 训练冲突 | 2531/1041/0 为用户生产截图，代码不应解除保护 | 待生产只读核验 | 历史 Task、Snapshot、重复审计，不删除真实素材 |
| TQ-09 | P1 | 正负与困难样本质量及补充闭环 | 现有困难样本模块；正式 GT 不自动重写 | 待设计 | `hard_sample_mining.py`；误报漏报来源及可复核证据 |
| TQ-10 | P1 | 场景、夜间、相机等分布完整性 | 依赖元数据，不可捏造 | 待设计 | 聚合统计明确已知/未知 |
| TQ-11 | P1 | best.pt→ONNX→RKNN 转换后精度与板端验证 | RKNN converted_unverified 不等于精度合格 | 待硬件核验 | 同测试集/预处理/后处理及芯片实测 |
| TQ-12 | P1 | 检测指标与睡岗/脱岗等业务告警准确率混用 | mAP 不代表事件准确率 | 待设计 | 事件规则/时长/误报每摄像头小时分别展示 |
| TQ-13 | P1 | 质量问题诊断不能直接到可治理对象 | 必须复用现有标注/质量中心 | 待设计 | 质量问题→证据→人工修复→重预检闭环 |

## 具体执行约束与顺序

1. **优先修复指标真相 TQ-05**：先证明类别失配，再最小范围修复；保留 Ultralytics 指标真相；不得补造历史指标。修复同时验收稀疏类别、多类别、缺失类别、单类别。
2. 随后 TQ-06/TQ-07：记录指标支持范围与模型推理协议，先保证评测可信。
3. 之后 TQ-01/TQ-03：以真实训练选择质量为对象，保留关联组和冻结合同；如果不可分层不得静默牺牲隔离。
4. TQ-02/TQ-04/TQ-08 需要生产和原始图像证据，不能用 Mock 或模拟断言“现场已解决”。
5. P1 按最小增量逐项收口，避免一个巨大 PR/提交改变训练数据真相。
6. 每项变更都必须追加：`提交 SHA`、`测试名称/通过数`、`CI exact SHA`、`未验证项`。失败测试不能删除或标为跳过。

## 需要现场核验的历史证据

- 重复素材截图口径：总 103455；问题 2531；问题组 1041；删除计划 0，未实际执行删除。
- 重复 GT 内容 SHA256：`0dcb43b6fa1c0678d1c4094c93403678aae9cbaac28419c2fbf4cfd9120c5e9e`。
- 冲突图片 ID：`57512edb455f4b16`、`11916bbdb5c64595`。
- 用户反馈约 97% mAP，尚无对应实际模型、Val/Test 协议、各类支持数量，不能断言是真实泛化或漏数假象。

## 本轮结果区

- 2026-10-18：登记全部 13 项，专项问题登记提交 `632447488725797f16a87e033a41b1bfb56ed0f2`。
- 2026-10-18：TQ-07 显式传递 `imgsz` 到常规 Val 和双路径盲测，新增实际推理 `predict_imgsz`、`predict_conf`、`predict_nms_iou` 的协议归档；协议 SHA 随图片尺寸变化而变化，旧报告不伪补协议参数；增加 Python AST 调用链保护及协议身份回归测试。未在 A800 上实测，等待最新 SHA CI。
- 2026-10-18：TQ-06 首轮 CI 曾有明确回归：对 no-GT 类别的 `None` 召回率执行 `float()` 导致盲测失败，Release Regression / Remote Training Runtime 实际日志均命中。现修改弱类别排序只遍历已有正 GT 的 `scored`，保留 no-GT 类别单独诊断并重跑最终 CI。
- 2026-10-18：TQ-06 补全独立测试类别覆盖合同：按模型类别目录补齐无 GT、无预测类别；无正 GT 类的 Precision/Recall/AP 标记 N/A，不再伪装为实测 0；保留 FP 证据；宏观 mAP 仍仅基于 GT 正样本类别；新版 evaluation truth 持久化 `class_coverage`，决策层将缺少 Test GT 的类别列为人工复核，不更改历史评测；已添加高分但缺少类别覆盖的回归测试，待 CI。
- 2026-10-18：TQ-05 在 `train_worker.py::build_report_from_metrics` 修复：紧凑数组按 `ap_class_index` 关联真实 class_id；`box.ap` 按位置读取，`box.maps` 仅按 class_id 索引；NumPy 数组不再使用 `or []` 真值判断。缺少身份映射时不伪造每类指标，仅保留独立总体指标与明确的 `report_error`；新增稀疏类别、无指标类别、NumPy、无映射、非法索引单测。已加入 Training Final Validation Hardening 和 Release Regression 的真实 Python 测试步骤，需以最终 SHA 验收。未处理历史版本指标重算。

## 第一批 CI 验收记录（2026-10-18）

- **被完整验收的代码 SHA**：`5a949611a00a129cebeb3670770ca3f6c6030ee5`，对应 TQ-05、TQ-06、TQ-07 的修复和针对性测试。
- GitHub Actions（该 SHA 实际触发的）：**25/25 success**、0 failure、0 in progress、0 cancelled。
- Jobs：**64/64 success**；逐次独立核验每个工作流的 Job 结果。
- 重点工作流：`v42.25 Release Regression`、`Training Final Validation Hardening`、`Remote Training Runtime`、`Frontend Runtime Stabilization` 均成功。
- TQ-05：按 `ap_class_index` 取真实 class_id；NumPy 类型安全和稀疏、未测类回归。
- TQ-06：新增 `class_coverage`，no-GT 类指标 N/A，宏观平均仍只统计可评估类别；CI 中发现并修复“弱类别排序对 None 调用 float”回归，证明跨 Ubuntu/Windows 检查。
- TQ-07：常规 Val 与双路径 Blind Test 显式传入 `imgsz`，盲测协议记录实际 `predict_imgsz`/`predict_conf`/`predict_nms_iou`，不同尺寸有不同协议 ID。
- **验收范围声明**：实际触发的 25 类工作流已通过，并不意味着未触发的其余工作流被验证。没有生产 A800 或 RKNN 板端实测；没有修改历史 GT、Test、Snapshot 或生产素材；没有部署、重启服务、改变 `VERSION.txt`。
- 第一批已完成 3/13 项“代码层 P0 修复”，**还有 10 项待办**。TQ-06 前端“无法评估”状态可读性、TQ-07 真实生产预处理/图片尺寸验收仍是后续补充项，不得宣告整体生产质量验收完成。

## TQ-01 阶段一（2026-10-18）

- 仅将可信视频/拍摄会话来源标记为来源已知；普通 group_id 与视觉近重复组只用于隔离，不冒充真实拍摄来源。
- 在训练输入冻结质量证据中加入逐类**正样本图片数**、**标注框数**、**不可拆分组件数**、各集合**confirmed_empty 负样本数**、可靠来源字段已知/未知数量。
- 对训练类别在独立 Test 缺少正样本发出不参与对应类别评测的警告；不虚构样本量、不用阈值/百分比分数冒充真实准确率。
- 新输入冻结启用 schema_version=1 的附加 `class_coverage`；老冻结仍计算旧结构，恢复校验时根据旧记录是否携带新字段判断，避免历史冻结因新版诊断新增字段而无法复验。
- **阶段二尚未实现**：真正多类别分层/抽组优化，必须结合 20k 组规模性能、固定 Test、SHA 关联组、旧快照重放、无法满足稀有类的可解释诊断，单独开发验证。
- 提交和最终 SHA 的 CI 请以本轮实际运行结果为准。没有生产数据或 OSS/A800 操作。

## 下一批严格顺序

1. TQ-01：带可信来源关系的多类别/分组划分与正样本分布合同；先做隔离失败用例，不放宽跨组保护。
2. TQ-03：针对当前训练选择而非过去 CLEAN 任务的正式标注质量检查；按错误/警告/需人工确认分类。
3. TQ-02、TQ-04、TQ-08：按真实生产来源、97% 模型实际报告和历史 2531 张保护引用做只读验收；不使用模拟数据宣称生产已解决。
4. P1：困难样本、场景覆盖、RKNN 板端实测和业务准确率专项逐项完成。


## TQ-01 阶段二｜2026-10-18 分组多标签分层代码候选

- **根因（经代码审计）**：旧 `_select_grouped` 仅以单组图片数量做精确子集和优化，未把各类别正样本/confirmed_empty 负样本纳入目标，因此能出现某一类别全部进入 Train 或缺失 Test 的情况；已有去重和关联组件隔离本身正确，不得放松。
- **修改文件**：`platform_core/training_splits.py`、`platform_core/training_tasks.py`、`tests/unit/test_training_stratification_v2.py`、`.github/workflows/v42.25-release-regression.yml`、本追踪文档。
- **实施**：新冻结采用 `multilabel_grouped_v2`，以不可拆分组件为原子单元进行稀缺类别优先覆盖与多类图片数量欠额填充，负样本纳入平衡；随机 Test 阶段在可能时为训练/验证保留两组，Val 阶段为 Train 保留至少一组；仍保留 SHA/视频/拍摄会话/近重复关联组隔离、固定独立 Test 原名单和独占 Test 的不可变约束。
- **旧任务兼容**：旧冻结无 `split_strategy` 标记时继续走 `legacy_v1`，不按新算法重排历史 Snapshot；新冻结在 digest 与恢复时记录、复核相同策略。
- **诊断**：新策略在 `input_quality.class_coverage` 下留存 `partition_diagnostics`（类别组件供给、实际覆盖集合、缺口原因）。当类组件不足、固定 Test 缺少正样本或多类耦合/配额限制时，不谎称类别已独立评测通过。
- **测试设计**：包含多类+负样本跨 Train/Val/Test、两组稀有类、同视频及已知近重复、固定 Test 不能迁移、旧策略重放、20k 不可拆分组规模。
- **提交 SHA**：算法、冻结版本化及首轮测试 `53fc6fcffd1621d90b54481454dd5e82023b6979`；将定向新测试加入 Ubuntu/Windows Training Input Integrity 的后续提交 `3c1d222550f711918cd249febd07e028ee711611`。
- **定向测试实测**：Training Input Integrity 同一 Git SHA `3c1d2225` 的 Windows、Ubuntu 24.04 均通过；每系统 split 相关测试 **23/23 passed**（包含新增 6 个分层回归），其余同一作业测试批次分别 **30/30、62/62、2/2 passed**。新测试未跳过。
- **CI 核验边界**：在代码/CI 补强提交 `3c1d2225`，GitHub Actions 连接器返回的首页 **20/20 success、0 failure、0 in progress**；该接口只返回首页 20 个工作流，未见到的其余可能触发工作流尚不能声称成功。生产 A800、真实来源分布、独立 Test 现场验收仍待完成；不得把代码通过等同真实泛化准确率已提高。
- **安全边界**：未执行生产数据修正、素材删除、Test 迁移、生产部署或 VERSION 修改；TQ-02/TQ-03/TQ-04/TQ-08 等任务保持原有待办状态。

## TQ-03 初步代码审计（暂未修复）

- `platform_core/annotation_quality.py::_audit_boxes` 已有无效/越界/极小/重复框和标签目录检查，但是 `audit_cleaning_annotations` 只针对冻结 CLEAN 选择执行，所有单图问题默认以 warning 记录，并不能自动成为当前训练选择的分级准入。
- `platform_core/training_splits.py::_valid_annotation` 只验证 annotated 非空和 confirmed_empty 无框/范围，不检查坐标是否有限、几何有效性及类别目录有效性；`freeze_training_inputs` 未复用 CLEAN 审核。
- 因此 TQ-03 **真实缺口成立**。下一阶段应复用单图审计检查，对本次选择在 Freeze 前实现“阻断/警告/人工复核”准入，并把可重放的质量证据纳入新冻结合同。完整 GT/训练投影差异需区别合法训练任务标签过滤与非法丢框，不能简单要求投影与原始 GT 完全相同。
- 保持生产只读、不得自动修改 Ground Truth。当前仅审计，**不声称 TQ-03 已修复**。

## TQ-03 第一阶段｜训练前正式标注只读质量准入（2026-10-18）

- **真实根因**：CLEAN 标注审核具有图片框校验，但没有用于本次训练输入 Freeze；旧冻结只检查标注状态/重复冲突，不提前对越界、零面积、非有限坐标、标签目录不一致做分级阻断。
- **修改文件**：`platform_core/annotation_quality.py`、`platform_core/training_tasks.py`、`tests/unit/test_training_annotation_admission.py`、`.github/workflows/training-input-integrity.yml`、`.github/workflows/v42.25-release-regression.yml`、本文件。
- **修复原则**：对当前冻结、已完成训练标签投影的正式 GT 进行只读扫描；阻断确定性无效框/标签/状态，极小框、极大框、疑似重复框及未复核标志归入人工复核，未知尺寸等归人工复核；`confirmed_empty` 明确支持合法负样本。对 `xyxy` 与 `cxcywh`（归一化或像素）按现有 YOLO 导出语义判断。不得自动删除、改写正式 GT 或修改固定 Test。
- **性能**：只遍历本次已在 Freeze 内存中的选择、不重复全项目查询；每图最多 32 框做高成本两两 IoU，超出时仍检查所有框的精确重复和非法几何，并明确记录 `box_pairwise_unchecked`，不得谎称完成全量近重检查。
- **冻结证据**：新冻结 `input_quality.annotation_admission` 留存 severity counts、issue counts、少量示例 ID、审核范围和未知尺寸数量；恢复时从相同冻结行重算证据；老冻结不具有此键时继续旧质量合同验证。
- **验收项**：越界、零面积、NaN、无效类、归一化中心宽高越界；负样本、合法框、极小/重复框人工复核；大量框降级判定；新旧输入冻结兼容。需进一步核对 GT 到投影的合法标签过滤和历史留存语义；本阶段只核查**投影后的本次训练 GT**，不宣称对被合法过滤的所有来源框完成审核。
- **待办/风险**：未在 A800/生产 103455 张素材上执行；缺失尺寸仅提示人工复核，不会假装已完成边界检查；对同 SHA 不同原始 GT 冲突仍交给现有重复安全审计；UI 阻断/警告/复核展示与实际正式数据验收尚待继续。
- **修复代码 SHA**：`ae31b946ee1acc8b107d5db808f26dd36e3170da`（Fast-forward 推送至长期开发分支，未修改 VERSION）；本轮单独代码修复涵盖 `annotation_quality`、`training_tasks`、新增 11 项冻结质量单测及两个 CI 工作流测试路径。
- **单元/回归验收**：GitHub Actions `Training Input Integrity` 的 Windows latest 与 Ubuntu 24.04 两个 Job 均为 success。各平台拆分+标注准入组合测试 **34/34 passed**，其余同一作业批次 **30/30、62/62、2/2 passed**，未使用跳过。新测试验收及此前 TQ-01 23/23 分组回归均有证据。
- **CI 范围声明**：代码 SHA `ae31b946` 最终读取的 GitHub 工作流首页 **20/20 success、0 failure、0 in progress**；Remote Training Runtime 实际 4/4 Job 成功。该检索接口只返回首页最多 20 条，未触发/未列出的其他工作流不得算作通过。完整首次 Actions、生产 A800 训练及真实素材来源还需另行验收。
- **状态**：第一阶段只读阻断/复核与冻结证据**代码已完成，定向验收通过**。TQ-03 的原始 GT 与合法标签投影完整交叉核验、前端分级展示、现场回归属于后续阶段；TQ-03 不标记“完全解决”。


## TQ-03 第二阶段：原始 GT → 任务投影一致性（2026-10-18）

- **确认根因**：第一阶段的 `_training_annotation_admission` 针对投影后的训练标签做几何准入。被任务标签筛除的原始框没有进入该检查；但这些排除框仍用于训练图片像素遮挡/擦除，非法框可延迟到 Worker 的 `_apply_training_projection` 阶段才触发错误。已有 `project_training_rows` 是唯一合法投影算法，不应该再开发一套任务投影。
- **本轮变更**：在现有 `freeze_training_inputs` 中增加 `_training_source_projection_admission`，复用现有单图审核：先对同次围栏读取的**完整来源 GT** 检查非法框、框坐标、来源类别，之后用原有 `project_training_rows` 从相同原始行重新计算合法投影并逐图片比较 `boxes`、`annotation_scope`、`source_annotation_hash`、`training_excluded_boxes`、投影政策、投影摘要、任务负样本标记及素材基本身份。禁止静默丢框或用伪造投影摘要绕过原始标注。
- **保持合法规则**：任务不需要的标签允许被排除，仍必须保留 `training_excluded_boxes` 并执行原像素擦除；仅剩排除类的图片可以成为 `negative_origin=redacted_unselected_labels` 任务本地负样本。整个过程只读，原始 GT 不被回写/删除。已存在的独立 Test 和同 SHA 重复保护不放宽。
- **新版冻结证据**：`input_quality.source_ground_truth_admission` 记录原始 GT 的审核结论，`projection_consistency` 记录核验图片数、排除框总数及任务本地负样本数。两者包含在 `input_freeze_id` 中；恢复不读取会变化的实时 GT，而是验证原始源 GT 摘要清单、审核元数据和冻结摘要。源 GT 原始框不会双份写入冻结合同，恢复时不能冒充重新审计了历史 GT。
- **兼容性**：历史冻结不含此两字段，仍走原重放逻辑。旧任务、Snapshot、版本报告和 VERSION 不修改。
- **新增测试**：原 GT 被排除框为零面积时冻结阻断；合法排除框与 task-local negative 不被误杀；伪造已选择框/排除框/政策摘要/审核范围/负样本标记无法通过；原始 GT 后来更改也不影响历史冻结重放。
- **修改文件**：`platform_core/training_tasks.py`、`tests/unit/test_training_annotation_admission.py`、本文；继续使用已存在的 Training Input Integrity、Release Regression 测试入口，无需新建架构。
- **待验收**：代码提交 SHA、定向 Python/Ubuntu/Windows、完整 GitHub CI 以及原 A800 生产数据均以实际核验为准；UI 对人工复核提示的集中展示仍需后续单独验收。
