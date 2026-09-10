# 42.25.0 训练语义、稳定性与部署能力收口设计

## 1. 目标与边界

42.25.0 基于 42.24.0 已有架构分阶段收口，不重做 Storage、MaterialRepository、Durable Task、GPU Resource Manager、训练 workspace 隔离和素材分页。

本轮目标是建立一条权威业务链：外部数据扫描与标签映射确认、平台稳定标签、具备作用域的 Ground Truth、按图片精确选材、按已选素材确定训练标签、冻结训练配置与划分、资源预检、真实训练、最终测试、算法版本、部署转换与检测。

明确不做：恢复数据集分组训练、修改 Ultralytics 内部 loss/dataset、复杂 A/B、版本删除、百万级完整能力承诺、与本轮无关的大规模 UI 改版。

## 2. 基线和分支

- 唯一代码基线：`01636b61780361dde91c12ac2732f46d2289b6be`，`VERSION.txt=42.24.0`。
- 开发分支：`feat/42.25.0`。
- 仓库远端 `origin/main` 当前实际为 42.21.1，因此本轮不得以它替代 42.24.0 基线。
- 本轮不修改、不合并 `main`/`master`；完成后只推送开发分支，由用户决定是否合并。

## 3. 权威数据语义

### 3.1 标签身份

外部 `class_id` 只在一次 `import_id`/外部数据集上下文中有效。正式平台 annotation 只引用平台稳定 `label_id`。同名建议映射只用于提示，任何外部类别都必须由用户确认后才能正式入库。

权威链路：

`external(import_id, class_id, label) -> confirmed mapping -> platform label_id -> annotation boxes -> material label summary/filter -> available training labels -> frozen training labels -> task-local YOLO class id -> model version label snapshot`

### 3.2 Annotation 状态和作用域

- `annotation_state` 描述图片整体状态：`unannotated | annotated | confirmed_empty`。
- `annotation_scope` 描述该图已完成完整检查的平台 `label_id` 集合，适用于 `annotated` 和 `confirmed_empty`。
- `positive_label_ids` 从有效 boxes 聚合，不单独维护漂移副本。
- `confirmed_empty_scope` 仅作旧数据兼容；读取时归一到 `annotation_scope`，新写入以 `annotation_scope` 为权威。

YOLO 导入规则：

- TXT 有有效框：`annotated`，`annotation_scope` 为本数据集映射后且未忽略的完整标签合同。
- TXT 存在但为空：`confirmed_empty`，作用域同上。
- TXT 不存在：`unannotated`，`annotation_scope=[]`。

一个标签 `L` 对一张图的训练语义：

- 有 `L` 的有效框：该类别正例。
- 无 `L` 框但 `L in annotation_scope`：该类别合法负例。
- 无 `L` 框且 `L not in annotation_scope`：该类别 Ground Truth 不完整。

### 3.3 训练图片资格

训练任务先按 `image_id` 选择素材，再由服务端按 annotation/作用域统计可训练标签。用户选择并冻结 `training_label_ids` 后，图片按类别判定：

- 至少一个选中类别具备完整 Ground Truth，图片才可能进入任务。
- 过滤未选标签后仍有框：导出选中标签框。
- 过滤后无框：只有 `annotation_scope` 覆盖全部 `training_label_ids` 才能导出空 TXT，成为当前任务的完整无目标图片。
- 对全部选中标签都不完整的图片必须排除并计数，不可自动转成负样本。

## 4. 外部数据导入

扫描阶段只写 durable candidate manifest、外部 annotation、类别统计和样例引用，不写正式 annotation。标签映射页面展示外部 ID/名称、图片数、框数、平台建议及样例框预览；支持映射已有标签、创建新标签、保留原标签、忽略。

确认后原子地将任务重新排队，由 Durable Import Worker 分批建立/匹配素材和写正式 annotation。映射结果必须与 `import_id` 绑定，防止不同数据集的 `class_0` 串线。

导入后修正映射通过独立 Durable Label Remap Task 完成，先显示影响范围，再批量更新平台 annotation/标签索引并写审计记录；不修改外部源文件，也不更换已有 `image_id`。

## 5. 创建训练任务

顺序固定为：

1. 选择训练素材与独立 Test 素材，或配置从训练素材抽取 Test 的比例。
2. 服务端冻结 selection manifest，并聚合有效 Ground Truth。
3. 展示本次素材可训练标签及每标签统计：框数、正例图片、作用域覆盖、合法负例、GT 不完整。
4. 用户选择 `training_label_ids`。
5. 冻结 `training_label_schema_snapshot`。
6. 配置训练参数。
7. Preflight。
8. 创建并调度正式训练任务。

训练合同只接受图片 ID/selection manifest，不恢复 `train_dataset_ids`、`test_dataset_ids` 或通过 dataset 展开素材。

## 6. YOLO 数据快照

平台稳定 `label_id` 不等于 YOLO 类别序号。每个任务按冻结标签顺序生成连续的临时映射：`0..N-1 -> platform label_id/code/display_name`，重写 TXT 并生成只包含本次标签的 `data.yaml names`。

快照继续使用真实隔离副本，禁止 hardlink/symlink。Train/Validation workspace 在训练阶段仅包含 Train 和 Validation。Test ID 自任务创建起存在于 sealed Split Manifest，但 Test 文件与 Ground Truth 只在 best 模型确定后的 Final Evaluation 阶段物化。

## 7. Preflight 与配置一致性

Preflight 必须在 Ultralytics 启动前阻断：标签快照与 data.yaml 不一致、选中类别无正样本、Train/Validation/Test 泄漏、文件缺失或 SHA 变化、annotation 状态/作用域冲突、磁盘/RAM/SHM/GPU 资源不足、显式 GPU 不可用。

训练参数全链路保存三层：

- `requested_config`：用户请求。
- `effective_config`：平台调优/约束后的值及原因。
- `actual_config`：子进程真实执行值和实际设备。

页面、API、Task payload、Worker、`train_worker.py`、Ultralytics argv 必须覆盖用户列出的所有参数；任何调整都必须可见，禁止静默改变。

## 8. Host/GPU 资源保护

复用 42.24.0 GPU Resource Manager，补充 Host Resource Guard。自动 batch/workers/cache 同时考虑 available RAM、`/dev/shm`、CPU、IO、imgsz、augmentation 和 GPU 显存。自动模式允许训练前降 workers/batch、关闭 cache 或延迟调度，但记录原因；训练开始后不随意修改影响结果的核心参数。

运行时记录 RAM/SHM/CPU/GPU/吞吐/epoch 时间并生成简单诊断。用户请求 GPU 时资源不足保持 QUEUED 或明确失败，不回退 CPU。

## 9. Worker 与子进程生命周期

TaskRepository 的 SQLite 打开/事务失败必须记录绝对路径、目录/权限/磁盘/挂载信息，有限退避重试；持续失败进入明确 degraded/error 状态，不退出调度主循环，也不创建另一份空库。

训练子进程身份至少保存：`task_id`、PID、process start time、关键 cmdline、process group/session、worker launch token、assigned GPU。恢复或取消时必须联合校验；无法可靠确认时禁止仅凭 PID kill。Worker 异常退出后，新 Worker 必须接管已验证子进程或安全终止，并修正任务状态。

EarlyStopping 是正常 TRAIN_COMPLETED。若 best.pt/last.pt 已存在而 Validation/Test/报告/版本生成失败，任务进入 `POST_PROCESSING_FAILED`，保留模型并支持从已有 best.pt 重试后处理。

## 10. 算法版本

算法增加权威 `current_version_id`。回退只改变当前指针，不删除、不修改历史版本。默认检测、继续训练、转换都基于该指针；从 V3 继续训练生成 V6 时，`parent_version_id=V3`。每个版本保留标签快照、训练任务、参数、Split Manifest、模型、指标和部署记录。

## 11. 部署与检测

- “部署转换”改为转换能力/环境配置中心，按 Atlas、RKNN、Sophon、ONNX 分别真实检测 Python/SDK/Toolkit/版本和平台参数。
- 转换从算法版本发起，读取能力中心的环境与默认配置，创建 Durable Conversion Task。
- “部署产物”统一展示转换记录、主产物、辅助产物、日志、SHA256 和板端验证状态。
- 删除“测试发布”的菜单、路由、页面和遗留 polling/Toast/Promise/事件；“检测台”保留在算法管理下并默认使用 `current_version_id`。

缺少对应 SDK/Runtime/硬件时必须显示真实 `NOT VERIFIED`/“转换成功，板端待验证”，不得伪造部署或板端测试成功。

## 12. 前端性能与生命周期

前端收口为单一权威 bootstrap 和页面生命周期：`enter -> request -> render -> poll -> leave/dispose`。页面离开时取消请求与定时器；请求使用 AbortController/request token/context guard；旧响应不得覆盖当前页面。

首屏只加载当前页面必要数据，素材/算法/任务列表使用服务端分页、count、summary 和缓存。轮询仅局部更新字段，不重建整页、不重排稳定列表；缩略图预留尺寸；保留筛选、分页、Tab、展开态和滚动位置。

训练任务主标题使用算法 `display_name -> name -> code -> task_id fallback`，任务 ID 作为次级信息。

## 13. 验证与完成条件

每个 Task 独立 commit。优先做 Python compile/import、JavaScript syntax 和 API/payload/Worker 合同检查；只有具体失败信号、核心数据安全或仓库规则要求时才做定向测试。禁止先跑整套 pytest 或长时间挂起测试。

没有真实 Linux/A800/2 万素材/Atlas/RK3568/Sophon 环境的部分必须标记 `NOT VERIFIED`，并给出最小人工验收步骤。所有 Task 完成后才更新 `VERSION.txt` 为 42.25.0、生成 release commit 并推送开发分支。
