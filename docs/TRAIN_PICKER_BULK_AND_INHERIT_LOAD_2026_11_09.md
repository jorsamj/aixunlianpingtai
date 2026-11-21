# 2026-11-09｜42.24.568 训练素材批量选择与上一版本继承读取专项

## 现象与授权范围

- 大约 2 万多张素材执行训练创建弹窗的批量选择时长时间等待。
- “上一版本继承 / 自动继承”长时间显示“正在读取继承标签”。
- 本轮仅修改已有训练素材选择和继承标签预览，保持 GT、训练标签冻结、训练创建、任务/数据资产、历史资格与负样本审批链路不变；不部署 4070/A800。

## 已查明的代码原因

1. `GET /api/v62/projects/{project_id}/training-labels/inherited` 原来通过 `list_algorithms_internal(project_id)` 读取整个项目算法及版本，再找当前算法；当前项目规模约 110 算法 / 1,100 版本，历史评测和标签合同字段较大。改为原已有的 `list_algorithms_internal(project_id, algorithm_id=..., summary_only=True)`，继承标签仍使用原 `inherited_training_label_preview()` 和冻结 schema 规则。
2. 训练素材批量操作原先允许 `/bulk-selection` 一次返回最多 50,000 个 ID；2 万 ID 会由浏览器保存成大集合、逐项操作并生成已选列表。原已存在 `/selection-reference` 服务器冻结选择，仅在超过 5 万时才兜底。现在仅对**当前没有已手工选择项**的 `train` “全选当前筛选/全选可用”启用更早的 2,000 张直接 ID 上限：已知总数超过 2,000 时直接调用原冻结接口，否则以 `prefer_reference_over=2000` 做有界 ID 探测，超限后沿用原 idempotent request_id 冻结流程。已有手工选择项不得被新冻结范围静默替换，仍采用原显式 ID 逻辑。小范围选择、跨页逐项多选、反选和独立 Test 不改变原行为/5 万上限。
3. 原 `TrainingLabelRuntime.refresh()` 只要正式素材标签摘要仍在读取，就把已经返回的上版标签也呈现为“正在读取继承标签”。现在上版标签返回后可独立先显示；“本次新增标签”继续等待正式素材标签摘要，绝不把历史标签或页面推测冒充当前素材 GT。

## 不变量

- 仍由原 `TrainingMaterialUsage`、`AnnotationRepository`、`TrainingLabelRuntime`、`training_selection_reference` 提供正式事实；不建第二套选择中心或缓存。
- 服务器冻结选择的上下文包含算法、版本、策略、GT/历史/负样本修订；创建训练任务时仍由原链路重新核实和冻结。
- 超限转换为原服务器冻结引用，不把半截 ID 视为完整选择；选择中失败不能写入训练数据。
- 明确保留训练/Test 互斥、已训练/冻结 Test、负样本池及已确认标签约束。

## 定向测试与待验

- 后端 `tests/api/test_training_material_picker_api.py` 新增 opt-in 上限触发测试，验证 2,000 张只应用于请求该优化的 train，Test 仍是 50,000；原全量选择及角色筛选测试继续保留。
- 前端 `tests/frontend/training-material-picker-runtime.test.mjs` 和 `tests/frontend/training-labels.test.mjs` 检查两条分支、原冻结 Owner、继承标签与素材摘要独立呈现。
- 当前环境缺少完整 API 依赖，已运行 JS 自动测试和 Python 语法检查，完整 API 运行测试需在原 GitHub CI 执行；无 4070 实机性能测量，不承诺 2 万张选择必然低于某一秒数。
- 部署后按“已知总数超过 2,000 / 未知总数 / 小筛选 / 独立 Test / 继承标签 / 修改素材后失效”检查首次等待时间、冻结数量、跨页成员预览与最终训练冻结资格。
