# P0-06A｜训练素材冻结引用替换与自动增强输入一致性：精准修复记录

- 日期：2026-11-14
- 代码/文档审计基线：`26c09c8ed8081e6ff2c8b3d888f4108f4a5e5288`（GitHub Actions **22/22 success**，其中前端 Chrome 第一分片同 SHA 重跑通过）
- 仅开发分支：`feature/external-algorithm-publishing`
- 本次范围：选择器原有冻结引用被新的小范围批量选择替换时，必须保证最终确认的选择与草稿一致。**不变更后端训练协议、GT、Worker、GPU 租约、数据库或生产环境。**
- 本次新代码准确 SHA / Actions：提交后重新核验，不使用上一个 SHA 的 CI 冒充本轮结果。

## 一、已确认的确定性缺陷

`static/modules/training-material-picker-runtime.js`：
1. 用户在训练素材选择器通过 `selection-reference` 冻结大于 2,000 张（如 22,015 张），此时 `picker.reference` 非空、`picker.selected` 为空。
2. 用户调整筛选得到一个小于等于 2,000 张的结果，再点击“全选当前筛选结果”。`resolveBulkSelection()` 使用 `bulk-selection` 返回显式 ID 列表，而不是新冻结引用。
3. 旧 `bulkAction()` 向 `picker.selected` 添加这些 ID，**但未清空旧 `picker.reference`**。于是界面记录了新选材，`confirmTrainMaterialPickerV3()` 又优先 `if (picker.reference)` 将**旧引用及旧计数**写回草稿，并清空 `materialIds`。
4. 该路径不会正确反映用户新的小范围选择。代码可确定，实际生产任务是否曾触发还需现场核验。

### 精准修复

只有在新的显式批量结果 **HTTP 成功、数量、五项修订版本匹配、批量请求和当前筛选身份一致** 后，才把原 `picker.reference` 置空并清除其旧显式集合，再应用新选择 ID。网络失败、超限、过期响应或修订不符时不动旧引用和既有选择；此前“历史逐项选择 + 当前筛选批量选择”的显式并集语义不变。

新增真实选择器 runtime 单元回归：先建立 22,015 张旧冻结引用，接收两条小筛选素材，点击确认后核查草稿 `materialIds` 恰为新两条、`trainSelectionRef` 为空且 `trainSelectionCount=0`；不能仍提交旧引用。

## 二、P0-06 训练输入链只读审计（不等于现场闭环）

| 阶段 | 源码合同 | 本轮验收边界 |
|---|---|---|
| 筛选全选 | `training-material-picker-runtime.js`：大于 2,000 张可用 `selection-reference`，小范围走 `bulk-selection` | 本次只修冻结引用→新显式选择切换 |
| 草稿、提交 | `training-draft.js`：有 `trainSelectionRef` 时 `train_image_ids=[]`，单独提交 `train_selection_ref`；显式选择使用 ID 数组 | 不改 POST 合同，未新建真实任务 |
| 服务端冻结引用 | `training_selection_reference.py`：SQLite 冻结清单有 count/SHA256/上下文修订，`validate_payload_references` 对照持久展开 ID | 不修改清单或修订 |
| TRAINING_PREPARE | `remote_training_tasks.py`：生成 `input-request-selection.json`、`input-freeze.json` 和 `selection_counts`（selected/effective/pending/test） | 正式 GT、实际剔除数量与 20k/30k 现场仍需对账 |
| 自动生成 | `training_robustness.py`：在**原始分组拆分之后**，仅对 Train 创建 RGB/YUV 解码差异 PNG，并复制对应 YOLO 标签；保留源图/组关联、变换与哈希证据 | 目前只确认此类**颜色差异**生成；不能宣称已实现不同分辨率/视频输入规格的自动生成 |
| 训练 Worker | `training_tasks.py`：构建/校验 portable bundle、将派生图加入 Train、写入 `robustness_summary`，独立 Validation/Test 无增强 | 代码合同存在，尚需正式数据实测有效原图/衍生图/训练输入总数 |

## 三、本轮后续验收

1. **代码 CI**：新代码 SHA 的 Node 测试、Chrome 选择器回归、训练输入完整性 GitHub Actions 需验证；失败时只修根因。
2. **真实数据的只读现场核验**：在获得生产只读访问条件后，以现有任务对照冻结 count/SHA256 → 父任务不可变 ID/引用 → Prepare 的 selected/effective/pending/test → materialized Train 原图/衍生图以及 Worker 接收清单。不输出图片、素材 ID 或密钥；未核实数字不能标“通过”。
3. **功能差距另列**：用户要求按不同视频输入规格自动生成训练素材；目前代码仅确认 CSC 颜色差异增强，分辨率/裁剪/补边等不能算本轮已实现。先制定配置、边框坐标、来源去重、分组拆分与磁盘限额合同，再单独立项。
