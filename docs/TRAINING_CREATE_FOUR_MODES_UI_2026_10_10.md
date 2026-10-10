## 2026-10-10｜四模式训练创建 CI 修复（42.24.345，待全量复验）

- 实际核对基线 `2e01bde1ee362060c23a82be1fad2c5e44341bf3` / `42.24.344` 的 6 个失败 Workflow、对应失败 Job 的原始日志；Remote Material Import 两次触发为同一缓存键测试根因。
- Training Create First Open：训练弹窗 Browser 测试使用已删除的全局高级展开按钮和旧弹窗标题；改为现有“创建训练任务”及数据划分原生 disclosure，训练素材/固定 Benchmark/标签规则仍继续检查。
- Frontend Runtime Stabilization：对应旧标题、旧高级配置与创建提交文案、TrainingDraft 写入顺序的断言漂移，已按可见真 UI 更新；导航与标签的真实操作仍须 Chrome 复验。
- Training Task Visibility / Algorithm SQL Store：同一 `four modes freeze only training semantics` 前端测试揭露生产链缺陷：`trainingDraftToRequest` 通过 `createTrainingDraft` 把历史 `gpuPolicy:auto` 覆盖掉 builder 的 `exclusive`；现在四模式规范化统一强制独占。保留中央 TaskScheduler、GPU Reservation 和 Worker 运行前真实资源决议。
- Remote Material Import 两次：原测试把 `app.js?v=42.25.333` 当成永远不变的字面缓存版本；现在验证版本不回退到旧修复点，同时入口缓存版本实际升级至 `42.25.345`。
- 自定义模式取消“兼容自动隔离”选项；普通模式不显示 Batch/Workers 专业设置；标签搜索、勾选、正式 GT、首次母模型、续训有效版本继承、60/20/20 比例以及单一 TrainingSubmit Owner 均保留。
- 本次只修改对应最小生产文件、前端测试、Browser 测试和现有文档，不另建 Owner、不删减安全测试；最新精确 HEAD 的全量 Linux/Windows/Chrome CI 仍待核验，真实 NVIDIA 同卡阻塞/双卡并发、OSS、Agent、10k/20k 素材 UAT 仍需现场执行。**不合并 main、tag、release、部署生产。**

# 2026-10-10｜训练创建弹窗四模式极简改造与标签合同

> 开发分支：`feature/external-algorithm-publishing`
> 版本：`42.24.344`
> 状态：代码和定向测试已提交。GitHub Actions 当前 HEAD 以及真实浏览器/生产 NVIDIA GPU 验收须以实际结果为准。本轮未合并 main、未 tag/release、未部署生产。

## 一、需求及范围

本批仅对“创建训练任务”进行视觉与表单交互收敛，不重新实现任何 Dataset/Label/Annotation/Task/Training owner：

- 弹窗标题“创建训练任务”，算法名称只在算法区展示一次；算法身份不可编辑；仅任务优先级可改。
- 首次训练母模型仍从已就绪的 `.pt` 中选择，续训锁定当前有效版本的训练权重；任务 ID 由现有模块生成，只在内部控件保留兼容，不显示给普通用户。
- 训练素材、数据划分、标签合同仍沿用精确 image IDs、既有 train/val/test split、canonical `TrainingLabelRuntime` 和独立 Benchmark 复用流程。弹窗末尾显示独立“训练标签”区域，带搜索、原本的正式标签复选框、既有继承/新增选择状态；`train_labels` 仍必须来自显式选择；首次训练无显式标签时禁止提交；迭代由服务器维护上一有效版本标签。
- 默认显示四种训练模式：快速 / 完整 / 复杂 / 自定义；模式在已有 `TrainingDraftRuntime` 唯一草稿中保存为 `trainingMode`，下发 `training_mode`，不创建第二套表单 owner、请求 owner 或轮询。
- 非自定义模式只展示训练轮次、图片尺寸、GPU 独占及“启动前自动适配”状态；自定义时才显示 CPU/GPU、Batch、Workers、Cache、Precision 以及已有完整专业参数设置按钮。
- modal 宽度 868px 以内，普通内容字体 14～20px，标签全宽、多列、底部固定创建按钮，兼容 1366×768 和窄屏。

## 二、模式合同（首次 / 有效上一版本续训）

| 模式 | Epoch 首训/续训 | 图片尺寸 | 资源策略 | 其他 |
|---|---|---|---|---|
| 快速训练 | 30 / 20 | 640 | Auto + Performance | GPU Exclusive，Worker 启动前冻结 |
| 完整训练（默认） | 150 / 80 | 640 | Auto + Performance | GPU Exclusive，Worker 启动前冻结 |
| 复杂训练 | 250 / 150 | 800 | Auto + Performance | GPU Exclusive，Worker 启动前冻结；确保硬件兼容 |
| 自定义配置 | 显式用户设置 | 显式用户设置 | Manual | Batch/Workers/Cache 等请求保持原值；不满足预算 fail-closed |

- 模式的 Epoch、imgsz 由唯一 `static/modules/training-submit.js:trainingModePreset` 给出；非自定义预设从提交参数中过滤掉历史手动高级配置，防止切换后隐藏参数影响训练。
- `static/modules/training-draft.js` 是 draft / exact material IDs / explicit labels / split / priority 的唯一 Owner；切换非自定义时清除历史 Batch/Workers/Cache override，避免隐形手动设置。
- 现有 `platform_core/training_metrics.py` 仍是最终 Auto 资源决议 Owner，在真实 GPU 分配及节点条件核验后冻结 Batch/Workers/Cache。自定义使用原有 strict manual validator，训练时不做暗中调小。
- `app.py.TrainReq.training_mode` 为可选字段，对旧 API 调用继续兼容；新四模式的预设只允许 auto，自定义只允许 manual。后台已有 train_labels、model、priority、split、安全 preflight、版本冻结和目标评测链不变。

## 三、修改文件

- `static/app.js`：沿用 `openTrainingCreateDialog429` / `renderSplit` / `TrainingDraftRuntime`，重构弹窗 DOM 为简洁纵向布局；四模式单选；仅自定义展示资源和高级表单；保留正式训练标签容器 `trainUiLabelSlot`，通过 `trainingLabelContractPanel` 原样挂载，不复刻标签业务逻辑。
- `static/training-create-modal.css`：仅 modal 作用域内的响应式布局、字号、标签多列、模式卡及底部固定操作区。
- `static/modules/training-draft.js`：草稿单一字段 `trainingMode`，预设清理隐藏手动资源参数，保留无模式字段的历史 manual/auto 兼容。
- `static/modules/training-submit.js`：唯一训练模式预设映射；submit 仍由 `TrainingSubmitRuntime` 统一处理。
- `app.py`：可选 `training_mode` 类型及 Auto/Manual 预设硬约束。
- 定向测试：`tests/frontend/training-draft.test.mjs`、`tests/frontend/training-submit.test.mjs`、`tests/frontend/zip-label-evidence-and-simple-training-ui.test.mjs`、`tests/unit/test_training_scheduler_target.py`、`tests/browser/training-create-first-open.spec.mjs`、`tests/browser/training-label-selector.spec.mjs`。

## 四、已执行 / 待执行

- 已执行：JS 源码 V8 语法验证；纯逻辑模拟四种模式初训/续训的参数、manual 与 auto 独占隔离、首次训练无标签拒绝提交、旧 manual 草稿兼容。以上仅限静态/纯函数验证，不是浏览器或 Worker 真机测试。
- GitHub Actions exact-HEAD 全绿：**PENDING**。
- Real Chrome：创建→首次母模型→选择素材→标签勾选→划分比例→模式切换→自定义高级参数→创建 durable task→关闭弹窗，以及续训固定权重/既有标签与 benchmark 复用：**PENDING**。
- 目标训练节点上的 Batch / Workers / Cache 真机资源冻结与 GPU 独占：沿用上一批 `docs/TRAINING_PERFORMANCE_EXCLUSIVE_2026_10_10.md` 的硬件验收 OPEN 条目。

**必须保证标签、素材和任务身份真实合同；不得为了 UI 简化通过降低/删除断言换绿灯。**
