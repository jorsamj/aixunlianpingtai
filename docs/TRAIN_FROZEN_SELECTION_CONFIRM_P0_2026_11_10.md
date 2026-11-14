# 42.24.572 训练素材全选冻结引用未进入训练创建 P0

日期：2026-11-10。开发分支：`feature/external-algorithm-publishing`。

## 现场症状与根因

- 训练素材选择器的「全选当前筛选/全选全部」在 20,000+ 张时正确生成 `train_selection_ref` 和 `trainSelectionCount`；确认后草稿刻意不持有海量 `materialIds`。
- 训练创建页、最终确认页以及训练标签组件却仍检查 `materialIds.length`，所以显示 0 张和空标签，造成“选了但没进任务”的假象。
- 训练素材 GT 摘要运行时对冻结引用直接伪造空标签摘要，没有读取原有 `/selection-summary`；兼容性检查则把空 ID 检查错误解释为“通过”。
- 冻结时 `train_labels` 为空，选材后人工勾选标签会改变引用校验摘要；迭代任务提交时还遗漏了 `base_version_id`，因此真实提交可能拒绝引用。

## 修复边界

1. 原训练素材选择器、`TrainingDraftRuntime`、冻结 SQLite manifest 与 Worker 保留；大批量 ID 不下载到前端，`train_image_ids=[]` + `train_selection_ref` 仍是合法提交格式。
2. 原 `/selection-summary` 读取严格身份与版本校验通过的冻结清单，再使用现有 `_selection_summary`、正式 GT 正样本证据生成 `positive_label_codes`、可选/待标注数量；禁止与显式 `image_ids` 混用。
3. 仅非角色过滤的冻结引用允许在选材后改变目标标签；引用仍不可跨项目、算法、基础版本、框架、历史策略、素材/GT/负样本/使用记录修订。按目标正负角色过滤的引用继续绑定原标签。旧版冻结清单维持原严格校验，其他领域自有引用上下文保持原逻辑。
4. 训练标签只从选中清单的正式 GT 正样本读取，不引用全项目标签库假装存在正样本；失败可重试。冻结 2 万张时更改勾选标签不重复扫描 2 万张。
5. 创建页/确认页展示冻结数量及状态；提交携带版本身份。冻结引用的完整标签适配等仍由原正式 TRAINING_PREPARE/Worker 门禁执行，不显示“已通过”错判。
6. 每次新建训练弹窗清空上次冻结引用；不改主数据、训练 Worker、其他报告与 AI 自动标注。

## 验收

- 正常逐张选择仍显示真实数量/标签；全选约 22,015 张确认后显示“已冻结 22,015 张”，GT 摘要能提供所选正样本的标签选择项。
- 人工选择标签后，已冻结的普通选择不丢失、不反复请求全量摘要；训练请求包含 `train_selection_ref`、标签、历史策略、`base_version_id`，不发全量图片 ID。
- 服务端严格拒绝其他算法、混用 ID、不匹配修订与角色过滤后的标签漂移。
- 本地已执行 Node 定向回归、`node --check static/app.js` 与 Python `py_compile`。当前环境未安装 `pytest`、FastAPI 等 Python API 运行依赖，未运行这部分集成测试；未验证真实 4070 22k 数据时延、浏览器交互和最终 CI。未部署/更改生产。
