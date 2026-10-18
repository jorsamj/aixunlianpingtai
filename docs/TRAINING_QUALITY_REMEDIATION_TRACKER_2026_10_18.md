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
| TQ-01 | P0 | Train/Val/Test 多类正样本及来源覆盖 | 现有分组隔离；完整分层不保证 | 待修复 | `training_splits.py`、`training_tasks.py`；按类独立图片/框/来源证据 |
| TQ-02 | P0 | 视频邻帧、近重复和缺失来源元数据导致疑似泄漏 | 已隔离 SHA/已知关系；未知来源需保留未知状态 | 待核验 | 导入扫描与 split；不可跨组，不能假装未知已安全 |
| TQ-03 | P0 | 训练选择的正式标注质量准入不统一 | CLEAN 审计不等同训练准入 | 待修复 | `annotation_quality.py` + freeze；按严重度区分阻断/人工复核 |
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

## 下一批严格顺序

1. TQ-01：带可信来源关系的多类别/分组划分与正样本分布合同；先做隔离失败用例，不放宽跨组保护。
2. TQ-03：针对当前训练选择而非过去 CLEAN 任务的正式标注质量检查；按错误/警告/需人工确认分类。
3. TQ-02、TQ-04、TQ-08：按真实生产来源、97% 模型实际报告和历史 2531 张保护引用做只读验收；不使用模拟数据宣称生产已解决。
4. P1：困难样本、场景覆盖、RKNN 板端实测和业务准确率专项逐项完成。

