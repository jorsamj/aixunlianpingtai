# 畅联云算法训练平台｜2026-10-17 新会话接续与生产前核验（当前有效交接）

> 更新时间：2026-10-17（北京时间）。本文是**阶段交接快照**；每次接手均需重新查询远端 HEAD、精确 SHA 的 GitHub Actions、生产代码版本和真实任务状态。不得用旧 SHA 的 CI 结果代替新 SHA 的验收。
>
> 状态标记：**代码已合并到长期分支 ≠ 生产已部署 ≠ 生产 UAT 已通过**。本文创建前经 GitHub 核验的**代码基线**为 `7de5be0dbbe06953f6ecace2d92496569adcf4e4`；写入本交接文档会生成新的**文档提交 SHA**，不能把该文档提交自动视为原代码 SHA 的 CI 结果。

## 1. 项目身份与基本约束

- 项目：**畅联云算法训练平台**（既有 YOLO/AI 训练、素材管理、标注、质量评测、模型版本及 GPU/Worker 分布式调度系统；不是另建项目）。
- 仓库：`jorsamj/aixunlianpingtai`。
- 唯一长期开发分支：`feature/external-algorithm-publishing`。
- 截至代码基线，`VERSION.txt = 42.24.356`；前端静态资源 cache build 与正式 VERSION 不应混为一谈。
- 不默认合并 `main`、创建 release/tag、修改 VERSION、部署生产、删除正式数据。只有用户明确授权后方可进行这些动作。
- 一律基于当前现有 Owner 进行增量开发，禁止重建第二套素材数据库、任务队列、标注真相源或并行浮层状态控制。
- 关键事实源：MaterialRepository、AnnotationRepository、Snapshot/Test Split、TaskRepository + ArtifactStore、MaterialBatchRuntime62、既有 Scheduler/Worker、模型正式版本与评测产物。

## 2. 远端最新代码与 CI（截至本文创建前）

- 代码 HEAD：`7de5be0dbbe06953f6ecace2d92496569adcf4e4`。
- GitHub Actions：在该精确 SHA 上已查询到 **24 次运行，均为 completed/success**，0 失败 / 0 运行中 / 0 取消。Codex 最终报告为 **61/61 Jobs 成功**；另外 **16 种工作流未触发，不能算通过**。这是**代码 SHA**的结论，文档更新后形成的新 SHA 需单独解释。
- 本地/远端一致、工作区干净、无分叉：来自最近一轮 Codex 报告；GitHub 只能直接核对远端，不能因此独立证明用户本地状态。
- 该基线尚未完成本轮新版的生产部署。真实生产 Git HEAD、VERSION、运行任务和 OSS/S3 状态必须现场只读检查，不可按推测填写。

### 主要近期提交（时间线）

| 提交 | 已完成内容 | 验收边界 |
| --- | --- | --- |
| `1de328cc` | AI 预标注创建弹窗按需加载、真实模型与提示词编辑及任务级冻结；自动清洗全部/指定图片/标签 OR 范围 | 代码/本地及相应 CI；生产任务待验证 |
| `36a62b01` | 独立评测历史问题图片：Bundle 与 Snapshot 身份安全恢复、JPEG/PNG/WebP/BMP、真实格式尺寸、GT/Pred/FP/FN、只读证据诊断和图片交互 | 真实 OSS/S3 和生产历史图片仍待 UAT |
| `7547794b` | 保护 YOLO_SOURCE_CHANGED：相同尺寸不同可信哈希必须拒绝，不可吞并为普通 invalid | 合同测试通过 |
| `85dfb0f5` | 新增 AI 创建及提示词冻结测试进入已有 CI | 精确 SHA 已验收 |
| `3be88817` | 算法/训练行操作菜单共用展示 Owner，约240px宽/44px操作行，定位、键盘和轮询不闪；移除“当前项目 / 默认空间”冗余展示 | 菜单实际响应约23–26ms，不宣称性能大幅提升 |
| `14db6a2b`、`d031565d` | Windows ZIP 临时文件/原子替换安全修复，375px 窄屏内滚动与 CI 合同修复 | 终版 CI 全绿 |
| `9830f1de` | **重复与异常素材 P0**：可见勾选、当前页/全筛选/跨页全选、服务端冻结删除预览、失败保留选择、任务幂等和状态回显、旧审计失效、组内超100分页、图片框对齐与失败藏框 | 隔离环境通过；原生产两次删除未能回溯 |
| `7de5be0d` | 素材治理 Chrome 证据路径使用 Playwright 隔离输出，解决 Ubuntu 缺少 USERPROFILE 的 CI 失败 | 本文创建前的最终代码 SHA，24/24 Actions success |

### 最新素材治理回归证据

- 本地报告：Node 24 **978/978**；Python 定向 **41/41**；真实 Chrome 定向 **21/21**。
- CI 报告：Ubuntu Node **978/978**、Chrome **95/95**、Release Python 两组 **456 passed / 176 passed**；均以对应日志为准。
- 隔离测试：126 张同图重复图删 125、保留 1；另有 125 张异常测试图中的冻结 Test 保护 1、删 124；**只删索引和对应标注，未删除共享原始文件**。
- 别将隔离项目/本地 Task ID 当成生产数据。详见 `docs/MATERIAL_INTEGRITY_P0_ACCEPTANCE_2026_10_17.md`。

## 3. 本轮最重要的现场投诉与代码层处理

用户在【数据集 → 重复与异常素材】反馈：
1. 看不到可以勾选的位置，没有全选。
2. 第一次点击删除提示等待，第二次报错。
3. 异常图片依然在页面中。
4. 缩略图/标注框预览异常。

**已查明、已在代码修复的路径**：

- 旧 `deleteMaterialIntegrity47` 在 estimate/create 前就 `closeModal()`，提交失败丢失操作上下文；现改为失败保留选择和弹窗。
- 旧普通 `DELETE_INDEX` 终态未统一失效旧审计，导致**索引已删除但旧审计列表仍有原问题组**；现终态刷新并使旧审计过期，提醒重新审计。
- 删除后重用旧 selection revision 可出现 `MATERIAL_REVISION_CHANGED` 409；**这是可复现路径，并未证实是生产第二次报错的唯一原因**。
- 旧问题组详情只拉取前100张、不继续 cursor；旧无图片尺寸降级为 `1×1` SVG、缩放层不匹配、图片失败不藏框；已修复。
- 旧治理流程重复调用 modal 形成堆栈与按钮重叠；现复用既有治理弹窗 Owner。
- 新版先做后端冻结删除预览，再确认 durable DELETE_INDEX；重复图每组至少保留 1 张；不同 GT 必须人工指定 keeper；Test/历史引用/无法核验扫描受到保护。**全选范围不是无条件全删**。
- 当前产品 `DELETE_INDEX` 只删 Material 索引及 Annotation 正式标注；共享物理原图仍可存在；需要区分“列表缓存未刷新 / 索引残留 / 存储原文件保留 / Task 失败或部分成功”。

**仍未解决的生产事实缺口（P0）**：

- 现场第一次和第二次删除操作的**原始 Task ID / 创建时间 / 状态 / Worker / total / succeeded / failed / error code / 日志**未取得。
- 未核实用户那一批生产异常图所在 Project、最近一次 `AUDIT_MATERIAL_INTEGRITY` 快照、删除计划 Revision、实际 Material/Annotation 数量及 Storage 是否仍有对象。
- 所以不能称“生产两次删除原因已证实”“生产异常图片已清理”或“生产 UAT 通过”。

## 4. 下一会话的优先级

### P0-A：只读现场核验，**先不部署、先不删除**

请用户在真实 GPU/生产主机提供只读检查结果，或仅在用户授权且已有安全连接时查询：

1. `cd /data/platform/aixunlianpingtai`，查看 `git rev-parse HEAD`、`cat VERSION.txt`、`git status --short`；
2. `systemctl is-active changlian-web.service changlian-worker.service`，`curl -fsS http://127.0.0.1:8010/api/health`；
3. `nvidia-smi`、`free -h`、`df -h /data /data/platform-data`；
4. 检查当前 TRAINING / MATERIAL_BATCH / AI_ANNOTATION / CONVERSION 是否有 QUEUED/RUNNING/WAITING_RESOURCE，以决定后续维护窗口；
5. 从现有 TaskRepository/只读 task API 查询最近 `AUDIT_MATERIAL_INTEGRITY` 与 `DELETE_INDEX` Task 和状态，**只读 SQLite 模式**，不要私自修改 Task JSON/数据库；
6. 对照项目素材列表和标注仓库，查证是真正索引仍存在还是源文件仍存在；核对真实 OSS/S3 可访问性和独立评测预览缺失错误码；
7. 输出具体证据和安全恢复/下一步建议，保护日志中的密钥、Token、内部存储凭据。

生产目录、service、health URL 是既有部署资料的参考值，**需现场确认**。不要假设服务器上的 Git HEAD 已等于 GitHub 最新分支。

### P0-B：生产部署准备，**取得用户单独授权后才能执行**

- 先确定当前生产代码是否有未提交修改、是否在直接 Git 工作目录运行，确保 `/data/platform-data` 和数据库/归档等持久数据已备份，核对恢复点与磁盘空间。
- 检查是否有活动训练/清洗/导入/转换；选择维护窗口。不能随意中断真实任务。
- 先审计代码跨度内的迁移/启动兼容、Worker 能力、离线模型、OSS 凭据可用性；区别新增静态缓存键与正式 VERSION。
- 用户确认后再提供/执行完整、可复制的安全部署命令。部署后做 health/web/worker、页面、真实历史评测、素材治理和 OSS/S3 的受控 UAT，并保留回滚。
- 用户过去偏好“一整段命令，直接复制一次执行；不要生成脚本文件”；**但当前任务未授权部署**，不可自行执行。

### P1：已知尚未完成的工作（非本轮生产阻断即不要抢跑）

- 真实 A800 离线训练/FP16 AMP 数值预检及 FP32 回退，模型本地权重、远端 Worker、转换至 RKNN 的真机验收。
- AI 困难样本挖掘已基于既有 AI_ANNOTATION / CandidateStore 做过第一批开发，但 **ZIP 导入后自动挖掘、远端 GPU 模型分发、完整定向增强/严格基准续训闭环**未确认完成。
- 真实 GPU、OSS、20k 真正素材吞吐/延迟测试、生产评测图片历史 Bundle/Snapshot 完整性未闭环。
- 源平台业务实际用量、策略准确率、单位排行及 OSS 物理容量等缺少权威数据源的指标不能凭推断伪造（详见现有 Owner/总览文档）。

## 5. 下一会话接手的第一步（必须执行）

1. 阅读本文件，并优先读：
   - `AGENTS.md`
   - `docs/CODEX_CURRENT_STATE.md`
   - `docs/MATERIAL_INTEGRITY_P0_ACCEPTANCE_2026_10_17.md`
   - `docs/ROW_ACTION_MENU_ACCEPTANCE_2026_10_16.md`
   - `docs/EVALUATION_DIAGNOSTICS_P0_2026_10_12.md`
   - `docs/DUAL_FEATURE_CI_ACCEPTANCE_2026_10_16.md`
   - 必要时 `docs/AMP_OFFLINE_COMPATIBILITY_2026_10_11.md`、`docs/VNEXT_MODEL_QUALITY_2026_10_13.md`
2. 核验远端 HEAD、精确 SHA Actions，而不是复制上述历史 CI 结论。
3. 先输出「已完成 / 未完成 / 生产待证实 / 风险」四类事实，不得把历史快照说明当成已成功部署。
4. 如果用户只要求查进度，**只读不修改**；需要开发、推送、部署时分清授权范围。
5. 本次写入 Git 的交接文档是文档性提交，`VERSION.txt` 不变、不改变程序核心逻辑。该提交产生的新 HEAD 若无 CI 运行，应明确为“文档提交 CI 未触发/待核验”。

## 6. 原则与安全红线

- 不能从失败列表上直接批量移除未经确认的 Test/历史引用或互相冲突的 Ground Truth。
- 严格保留 Worker capability 白名单、独占 GPU 调度、离线模型与 AMP、Snapshot 冻结 Test 数据隔离。
- 用户的生产数据和模型证据只能以真实 API/SQL/Artifact/日志确认，不得以 Chrome mock 或隔离夹具当成生产事实。
- 不得在未授权时部署、重启服务、清库、强推或修改正式 VERSION；提交文档必须在**长期开发分支**而不是 main。

## 7. 新会话快速口令

“请继续接手畅联云算法训练平台。先阅读 `docs/HANDOFF_2026_10_17_CURRENT.md` 及其中引用的当前文档，实时核对 `feature/external-algorithm-publishing` 最新 HEAD/CI。上轮代码基线 7de5be0d、VERSION 42.24.356，素材治理 P0 和近期 UI、独立评测/AI 标注已进入长期分支，代码 CI 成功但未部署生产。首要任务是只读核对 A800 当前部署及生产两次 DELETE_INDEX 的 Task/日志/素材真相；在新授权前只核验、不删除、不部署、不修改 VERSION。区分代码已完成、CI 通过、生产未验收。”
