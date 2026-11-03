# 训练历史宽松准入与来源组自动划分 P0（2026-11-03）

## 原因与修复目标

真实工单 `train_7c434416939449e7bb2ecc66` 的输入准备阶段报出“无法在保留训练类别正样本、来源关联组及剩余集合的前提下划分留出集”。在 42.24.512 隔离代码核对中确认两个独立的可复现缺陷：

1. 历史使用投影覆盖不完整时，`unknown` 素材即使没有已知训练暴露，也会进入 `forbidden_test_image_ids`；创建时放宽若不贯通 Worker/结果提交，正式 Test 又会被旧严格检查阻断。
2. `multilabel_grouped_v2` 把 `confirmed_empty` 当作需要预留两个来源组的检测类别；在 fire、smoke 各两个独立来源组和两个负样本来源组的受控样本上，修复前直接报出与生产工单相同的划分错误。**该隔离复现不等于生产工单根因已现场确认。**

## 新增合同与安全边界

- 沿用现有 `TrainingMaterialUsage` 及 Task SQLite；先区分 `healthy`、`uninitialized`、`incompatible`、`corrupt`、`unavailable`，只初始化真正不存在的使用投影表。不在训练请求内重建历史、不把表损坏伪装为历史未使用。
- 业务新策略 `history_policy_version=assumed_unseen_v1`、`schema_version=2`：在索引健康时，素材历史 `unknown` 可以按未训练准入，但证据仍保留未知；`historical_independence=assumed_unseen`，不能伪造成 `unused` 或 `verified_independent`。
- 已知训练/验证集暴露、活动任务的角色预留、SHA256、原图与衍生图、同视频/采集组以及已核实模型祖先的训练暴露继续严格拦截。已损坏或身份不匹配的模型权重不能借“未知历史”放行。
- 有效已核验父模型若缺少早期 Task/Snapshot 可按 `assumed_unseen` 继续新任务；已有已知祖先的暴露仍保持有效。固定 Benchmark 复用仅对其已严格核验的来源合同开放。
- 历史任务无 `schema_version=2` 时继续原严格评分路径；新任务历史准入随 `input-freeze.json`、Task payload 一起冻结，原 Worker 评分栅栏在执行与模型结果提交时再次核对已知暴露及索引健康，防止晚期漏检。
- 新版本的评价 `historical_independence` 与既有 `benchmark_scope.binding_level` 分开存放；真实指标可以展示，但 `assumed_unseen` 不得进入严格同基准比较或固定 Benchmark 复用。质量展示无论 mAP 高低都需显示该状态。
- 负样本仍可为训练保留一个完整来源组，不再因 Test/Val 两次保留被全部锁住；划分失败时最多尝试六次确定性、受资源限制的分组顺序及有界后备方案，不拆分关联来源，不删除正式 GT，不动旧任务划分。

## 代码责任区域

| 模块 | 职责 |
| --- | --- |
| `training_material_usage.py` | 索引健康、准入合同、父模型血缘、冻结 Test 复核 |
| `training_splits.py` | 负样本分组、确定性有限备选与诊断 |
| `training_tasks.py` / `remote_execution_transport.py` | 本地/远程正式 Test 和评价可信度一致 |
| `training_evaluation.py` | 评价记录身份与历史可信度解耦、同基准比较保护 |
| `remote_training_tasks.py` / `app.py` | 固定 Benchmark 复用资格保护 |
| `static/modules/reports.js` / `quality-detection-workbench.js` | 真实指标与历史假定状态并列展示 |

## 验收证据与边界

- 修复前：6 个隔离来源组（fire 2、smoke 2、confirmed_empty 2），现有 v2 划分器抛出生产相同错误。
- 修复后：同一组样本在 seed=7 下分出 Train/Val/Test；重复计算角色结果完全一致，火与烟真实类别仍留在 Train；各角色不可拆分来源互不交叉。
- 使用独立加载 Python 模块的隔离核验：健康未覆盖历史状态下 Test `assumed_unseen` 准入；新增同 SHA 的已知训练暴露后 Test 正确拒绝。
- `python -m py_compile` 对变更后端模块通过；Node 定向 `metric-credibility-report`、`scenario-evaluation`、`training-submit` 总计 87/87 通过。
- 已尝试执行完整 `npm test`；因当前容器没有安装正式依赖 `@uppy/core`，涉及 Uppy 的既有测试无法导入，完整前端测试未通过，不能把此环境缺依赖报告为业务回归通过。
- 已补 Python 单元测试：父模型 Snapshot 缺失且权重 SHA 已核验、索引结构损坏拒绝、已知同 SHA 暴露再拦截、负样本分组与不拆组、低 mAP 历史可信度和严格 Benchmark 禁入。这些测试需要在 GitHub Actions 的完整 Python 环境中验收；当前执行容器未安装 `pytest`、`filelock`、`fastapi`，不能称本机 Python pytest 已通过。
- 尚未进行真实生产 Task 原始 Snapshot 的分组诊断、真实 A800 训练、20 万素材生产 P95、真实浏览器多视口及部署测试。不得凭隔离测试声称生产故障已恢复。

## 兼容与上线注意

旧 Snapshot / Input Freeze / GT / 版本 / 素材 / 任务均不改写。对于旧历史不完整索引，新任务采取有依据的宽松准入，**不以此替代严格独立 Benchmark**。上线前需完成准确提交 SHA 的 GitHub CI；生产部署由用户独立决定。生产工单保持失败事实，通过**新建**合法 fire/smoke 任务验证，不修改旧状态。

如用户仍遇到 20 万素材 Picker/标签加载超时，应按独立的前端/SQL 性能专项排查，不能由本轮数据划分修复替代。
