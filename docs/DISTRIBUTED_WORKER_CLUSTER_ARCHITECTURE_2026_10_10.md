# 畅联云算法训练平台｜分布式 Worker 集群与轻量控制端架构需求

> 日期：2026-10-10
>
> 类型：**用户确认的目标需求 + 当前代码差距评估 + 待开发/验收清单**
>
> 开发仓库：`jorsamj/aixunlianpingtai`；唯一长期分支：`feature/external-algorithm-publishing`。
>
> 本次审阅代码基线：`e3ff6e90013ea5b84fb5644a1d36d75216529b43`、`VERSION.txt=42.24.342`。这是审阅时快照，不是未来 HEAD。
>
> **状态：SPEC / NOT IMPLEMENTED BY THIS DOCUMENT。** 本次仅记录需求并提交文档，不修改代码、数据库、节点配置或生产部署。已存在的实现不因本文重新标记为 CLOSED；所有生产效果仍需实际部署和 UAT 核实。

## 1. 最终产品决策

目标架构固定为：**轻量阿里云控制端 + 多台能力可配置的 Worker/Agent 服务器 + NAS/OSS/S3/MinIO 存储 + 单一中央调度器及持久化任务队列。**

1. 控制端只承担 Web/API、身份/权限、项目与算法管理、轻量数据库操作、正式数据受控提交、调度/租约/心跳、日志状态、版本与外部畅联发布协调。不在 Web 请求线程或低配控制端默认执行大批 ZIP、图片处理、模型推理、训练、数据集打包等重负载。
2. **所有重 CPU/GPU/内存/磁盘/网络 I/O 的可移植任务，优先交给有对应能力的 Worker。** ZIP 扫描/格式解析、批量图片哈希/质量清洗、批量 AI 预标注、视频抽帧、数据集准备/缓存、训练、模型转换/评测都属于候选任务。不能因为 CPU 任务不需要 GPU 就默认留给控制端。
3. 统一 Worker/Node Agent 安装与管理入口，按节点能力启用执行组件；内部可多子进程、多资源池，不等于所有能力共享一个串行执行槽，也不等于拆成多个相互独立的平台或调度器。
4. 控制端如果硬件足够强，**允许另行部署本机 Worker**，像其他节点一样注册、授予能力、接受容量准入与资源限额。低配控制端默认不分配重计算；控制端的关键 Web/API、数据库和租约心跳需要保留资源预算。
5. 唯一业务 Owner 不变：TaskRepository/Task Runtime、CentralTaskAllocator、ServiceNodeRepository、AnnotationRepository (Ground Truth)、MaterialRepository、StorageSource/StorageManager、Dataset Revision/训练 Snapshot、ModelArtifact/External Publication 均不可创建平行替代物。

## 2. 目标部署拓扑及职责

```text
                         阿里云控制端（低配亦可）
 Web/API + 轻量控制 Worker + canonical DB/正式提交 + Queue/Scheduler
                   |               |
         HTTP 心跳 / 领取 / 租约     | 任务/版本/素材元数据
                   v               v
  Worker A      Worker B       Worker C       Worker D        可选本机 Worker
  GPU训练       训练+清洗+导入   训练+清洗       GPU训练          仅经授权和配额
                +标签统一(目标)
                   \              |             /
                     NAS（素材原件）/ OSS、S3、MinIO（跨节点中转与产物）
                     Worker 本地 SSD 临时快照/缓存/训练工作区
```

**部署单元与代码入口：**
- `app.py` 对外提供控制端 Web/API。
- `task_worker.py` 当前仍负责需要正式数据库/`DATA_DIR` 的本地后台任务，控制端保留轻量 owner 和安全提交职责。现有 `--roles all` 是训练 Worker + 非训练后台 Worker 的兼容监督模式，**不是独立远程 Agent 安装方式**。
- `node_agent.py` 是部署在独立服务器上的远程 Agent 入口，通过控制端 HTTP API 心跳、领取、执行并回传。远程节点**不得直接共享或写中央 SQLite、不得以 NFS 共享 SQLite 代替传输合同**。
- 重计算逐步从控制端迁移到 Agent 时，应保留已有 task/owner，延伸版本化 portable execution contract；真正写入正式 GT/索引/任务状态必须由唯一 owner 在受控事务内完成。

## 3. 用户确认的 A/B/C/D 节点能力与路由语义

| 节点 | 训练 | 清洗 | ZIP/素材上传导入处理 | 正式标签统一 | 说明 |
|---|---|---|---|---|---|
| A | 是 | 否 | 否 | 否 | 专用训练 |
| B | 是 | 是 | 是 | 是（目标能力，现非远程实现） | 综合计算与素材处理 |
| C | 是 | 是 | 否 | 否 | 训练+清洗 |
| D | 是 | 否 | 否 | 否 | 专用训练 |

### 3.1 必须通过的情景

- **A 空闲、B/C/D 已无可用训练容量，新增训练任务：** 若 A 通过模型/显存/CPU/RAM/SSD/执行槽准入，应立即安排 A，不能因 B 显卡更强而让任务绑定 B 等待。
- **A 空闲、B/C 忙、D 忙，新增清洗任务：** A/D 均无 `cleaning` 授权，不得接单；若 B/C 均无清洗容量，任务必须真实保持等待资源（不伪称已可执行），直至 B/C 释放。
- **B 忙、C 有清洗容量：** 清洗任务交 C；有另一类不兼容任务占用 B，不影响 C 领取。
- **正式标签统一任务：** 用户给定的能力矩阵中**只有 B**有此能力，故应等 B；不能发给 C。早先口述“等 C 空”与同一矩阵冲突，应以**明确配置的能力白名单**为准；若用户确需由 C 处理，先单独授权 C 相应能力并完成真实执行器部署/验证。
- **B 同时训练+清洗：** 按 GPU、CPU、内存、磁盘 I/O 和执行槽预算决定能否并行；如果预算不足，合法任务也只能等待，不能超卖或隐式抢占。
- **双 GPU 服务器：** 如果两块物理 GPU 各自符合任务要求，可以安全并行两项独立训练；不得把不同任务同时错误绑定到被独占的同一块物理 GPU。
- **手动指定节点：** 严格亲和，不可私自溢出到别的服务器；但手动指定同样必须遵守能力/容量/在线准入。

这里的“忙”不是单一布尔状态：**有能力 + 实际上报可执行 + 对该任务有剩余容量**才是可领取条件。

## 4. 中央任务调度必须满足的规则

### 4.1 两个硬门槛，之后才排名

**硬门槛 1 — 授权及运行环境：** 节点启用且心跳有效；任务要求能力属于 `allowed_capabilities ∩ reported_capabilities`；执行器和 Python/驱动/依赖/硬件实际 ready；任务 portable contract、连接模式、Source 可用性及节点亲和符合要求。前端勾选只构成管理员授权，**不得把勾选当作已安装执行能力**。不存在或不支持的能力 fail closed。

**硬门槛 2 — 即时资源容量：** 任务运行时必须持有真实可执行的槽位及 CPU/RAM/GPU UUID+显存/SSD/必要 I/O 预算；同时计入 `ASSIGNED`、`CLAIMED`、`RUNNING`、`CANCEL_REQUESTED`、清理未结束及本机非平台进程的占用。单纯 GPU 利用率和“忙碌惩罚分”不是硬准入，不能替代持久保留、执行中预算和 lease fencing。

**合格节点之间才进行排名：** 默认优先**可立即执行**的节点；然后根据设备性能、预计完成时间、剩余资源、数据本地性、负载均衡等评分。允许选择有真正可用第二块 GPU 的忙碌服务器，但不允许选择已无可执行容量的“更强服务器”阻塞空闲合格节点。

### 4.2 排队、领取、恢复

- 每一项耗时操作应创建既有 Task Runtime 的 durable Task，按优先级/队列顺序管理；不能用页面内存队列、每节点私有新调度器或无限轮询代替。
- 中央 allocator 必须在运行服务中**自动、持续、幂等地推进分配**，任一任务结束/取消/节点上线/资源释放都能唤醒或在有界轮询内接单。不依赖人工调用 `POST /api/v63/scheduler/allocate-next` 或浏览器刷新页面。
- 忙碌节点没有容量时应保持未分配或可安全撤销的等待态；不允许过早把任务锁死在繁忙节点并阻断其他空闲可执行节点。
- 统一并发预算、任务优先级和公平性。普通任务不隐式打断运行训练；只有存在真实可恢复、带清理确认的协议才允许安全抢占。
- Agent 丢心跳/租约过期：清理执行归属、释放保留或在有界恢复流程中重新排队；失效代次的 Agent 不得写 GT、提交产物、发布算法版本；故障后不能同时存在双主人。
- 对离线节点/储存源不可用/不支持的能力区分“等待资源”“等待节点”“环境阻断”“数据准备失败”等真实状态；队列位置与剩余时间不可伪造。

### 4.3 当前差距（基于审阅 SHA）

- `platform_core/task_node_assignments.py` 中 `_online_nodes` 已过滤启用、在线、允许且上报的能力，也要求远程任务显式 portable contract。
- `CentralTaskAllocator.assign_next()` 已有优先级、GPU 选择、队列和分配资源评分；**训练评分当前允许繁忙但显存充裕节点压过空闲小节点**；清洗只是对空闲节点排序优先，未把所有执行中非 GPU 任务的真实剩余容量作为硬准入。
- `NodeAgentExecutorLoop.run_once()` 当前为**单任务执行循环**；中央层虽存在两张 GPU 预留的测试，但不代表一个 Agent 进程能同时运行多项任务。
- 存在 `/api/v63/scheduler/allocate-next` 与 Agent claim/start 协议；**未在已审阅启动入口中确认中央常驻自动分配驱动闭环**。仍需审查所有实际服务启动与用户部署版本，不能把 API 可调用当作自动调度已验收。
- 已有 lease/generation/heartbeat 逻辑，但真实多机异常、网络分区、取消/超时/恢复和最终产物发布仍需端到端 UAT。

## 5. 计算工作负载的归属清单

| 操作 | 最终执行建议 | 正式数据最终 Owner / 注意事项 | 当前远程 Agent 判断 |
|---|---|---|---|
| 用户/权限/项目/算法元数据 | 控制端 | 现有业务 API/DB | 不应外移 |
| 标签增删改/少量标注提交 | 浏览器交互 + 控制端 | AnnotationRepository/标签治理 fence | 保留控制端 |
| 手工画框与缩放 | 用户浏览器 | 保存时才进入正式提交 | 不需要 Worker |
| ZIP 大包扫描/解压/格式/图片校验 | 素材 Worker | 上传/ImportCandidate + 正式确认 | `MATERIAL_IMPORT` 部分已支持 |
| 素材批量扫描、哈希、去重与导入分析 | 素材 Worker | Material/Storage Repository 原子提交 | 部分已支持，区分远程扫描与最终本地入库 |
| 数据清洗、图片质量分析 | CPU Worker 或综合 GPU 节点 | 统一 CLEAN 结果确认；GT 不直接受远程覆盖 | portable CLEAN 已有执行器 |
| AI 预标注/图片识别 | GPU/模型 Worker | CandidateStore → 人工审核 → AnnotationRepository | **未确认现有 Node Agent 支持 AI 标注任务** |
| 批量标注解析/映射/一致性审计 | CPU Worker | AnnotationRepository 唯一正式 GT | 需按操作拆分评估远程合同 |
| 正式标签统一/重映射 | Worker 做大型扫描/计划；控制端受控提交 | `MATERIAL_BATCH/REMAP_ANNOTATION_LABELS` + AnnotationRepository / Material projection | **尚无可配置的远程标签统一执行器** |
| 视频抽帧 | CPU/视频 Worker | 视频任务已有本地 owner | Node Agent 当前不支持 `VIDEO_FRAMES` |
| 训练集快照生成/ZIP 包装/数据缓存 | 尽量 GPU 或 NAS 邻近 Worker | Freeze/Snapshot/sha/标签/拆分 canonical 不变 | 当前重步骤仍在 control-side TrainingPrepare |
| YOLO 训练/评测 | GPU Worker | Task Runtime + ModelArtifact | 远程训练已有执行器，现场待验证 |
| 模型转换、部署验证 | 适配硬件的 Worker | Canonical Conversion/Deployment owner | 部分远程执行器已支持 |
| 持续视频推理业务 | 独立推理 Worker/服务 | 与训练资源隔离、需要明确产品合同 | 不得假定已并入统一 Agent |
| OSS 模型归档/外部畅联发布 | 控制端协调 + 存储传输 | Canonical ModelArtifact/External Publication | 保留中央最终确认 |

**特别提醒：** 当前 `task_node_capability(MATERIAL_BATCH)` 将 `CLEAN` 映射到 `cleaning`、`AI_ANNOTATE` 映射到 `annotation`、其余操作归入 `material-import`，**这不等于** Agent 的 `material-import` Runner 可以执行所有 MaterialBatch 操作。当前远程清洗 Runner 只处理 `MATERIAL_BATCH/CLEAN`；`REMAP_ANNOTATION_LABELS` 创建时使用 `materials.batch` 本地 Worker。不能因节点勾选了“素材导入”就认定它能远程合并正式标签。

“标签标注”区分浏览器人工标注（本地 UI + 轻量正式写）、AI 预标注（算力执行）、批量导入标签映射与正式标签统一（有独立审核/原子提交）。不允许把后两者简化成 Worker 任意直接写中央数据库。

## 6. NAS、OSS 与训练数据流转

### 6.1 目标数据通路

- NAS 可以作为大量训练原图的存储源；素材索引只保存稳定身份（image_id、source_id、object_key、sha256/size 等），不要求把所有原图复制到阿里云。
- 创建任务时控制端冻结**精确素材、标签/GT 范围、分组防泄漏的 train/validation/test 划分、母模型身份与数据集 Revision**；不能先训练、后重新划分测试数据。
- Worker 根据授权、版本化且可校验的数据读取合同，从 NAS（网络可达且合法挂载）或 OSS/S3/MinIO **只转存选中素材到 Worker 本地 SSD**，校验完整性和 SHA256，生成不可变 YOLO 快照，训练全过程从本地工作区读取；支持命中可证明匹配的缓存和孤儿/过期缓存 GC。
- 对外传输尽可能走对象存储直达 Worker，不要把大型图片在控制端无谓地下载再上传。保留现有 Bundle 路线作为兼容/回退，迁移时不能拆开 Ground Truth、snapshot、版本 identity 的唯一 owner。
- 本地/NAS 的挂载由部署环境负责；**Node Agent 不能凭控制端路径字符串自动读取远程 NAS**。显式 portable contract、授权、可达性、健康检查是前提。
- 正式 GT、Source 配置/Secret、原始素材不可被旧任务/非法路径覆盖。Worker 不应凭任务请求擅自挂载 NAS 或获得所有存储密钥。

### 6.2 当前实现边界

现有 `TrainingPrepareHandler` 可把所选素材生成 portable dataset/Bundle，经 **OSS/S3/MinIO** 中转至 GPU Agent，本机 SSD 上运行训练；远程目标选择 local-only 存储当前可触发 `REMOTE_TRAINING_STORAGE_NOT_PORTABLE`。此实现存在控制端大型数据准备/哈希/压缩与 OSS 中转开销。

“GPU Worker 直接读取 NAS/OSS、自己完成整个 Snapshot 构造”的数据通路**尚非已完成的现有实现**；列为性能架构优化，需可重复的数据一致性与真实跨机验收后才能切换默认。

## 7. Worker 安装与部署模型

用户目标：**同一套 Worker/Agent 安装包，节点按能力配置；不为训练、ZIP、清洗、标注、模型检测分别维护互不关联的独立平台。**

### 7.1 必须落实

- 控制端添加节点后产生节点身份/安全 Token；Agent 运行环境安装包可按训练、ZIP、清洗、标注、转换、评测等能力加载可用的执行器。
- 管理端展示：管理员允许能力、Agent 实际上报能力、环境检查状态、并发/资源配额、当前运行任务，明确区分三个维度。
- 同一 Agent 管理入口可以监管多个隔离子进程/执行槽；GPU 训练、CPU 清洗、ZIP 扫描共享同一中央调度与 TaskRepository，不共享一个必须串行的执行线程。
- 控制端如果同时部署本机 Agent，本机计算仍须注册成节点、通过授权与容量准入，保护 Web/数据库资源；不能通过本地捷径绕过调度与 task lease。
- 操作系统服务建议 systemd 常驻、自启动、重启后安全恢复；每个节点维护独立工作区和缓存，不复制控制端数据库；Windows 开发/Linux NVIDIA 生产继续跨平台。
- 高风险能力只在环境探测通过后才上报；能力未安装或版本不兼容时置 unavailable，不是假“已就绪”。

### 7.2 不可误认为已经实现

当前 `node_agent.py` 已可运行 `TRAINING`、`MATERIAL_IMPORT`、`MATERIAL_BATCH/CLEAN`、模型转换和部署测试相关 Runner；`AI_ANNOTATION`、`VIDEO_FRAMES`、正式标签统一、所有“模型上传/评测”并不因前端能够勾选相关名称而自动拥有可执行远程 Runner。对于本地 `task_worker.py --roles all`，只是本机 Worker 监督/隔离模式，不是远程 HTTP Agent 替代品。

## 8. 新增 Worker/服务节点报错：现场待确认 + 已确认代码缺陷

**用户现场反馈：新增 Worker 节点弹出错误；尚未提供完整错误、HTTP 状态和生产服务日志，因此不能据此断言接口本身失败。**

审阅开发分支已确认：
- 前端请求 `POST /api/v63/service-nodes`；后端 `service_node_router` 通过 `training_recovery_router` 间接挂载，不能误报为“没有路由”。
- `static/modules/service-node-runtime.js` 创建成功后 **先 refresh 列表、再展示只返回一次的 Agent Token**。如果 POST 成功但后续 GET 失败，前端可能提示“创建失败”，且首次 Token 界面未显示，重复点击又可能收到 `SERVICE_NODE_EXISTS`。这属于真实 UI 生命周期风险，**但不等于已经认定用户现场的唯一原因**。
- 待现场区分：HTTP 401/403、404、409（重复 ID）、422（ID/能力校验）、500（运行时/数据库/部署），以及创建后刷新/Token 显示失败；查看 `changlian-web.service` 脱敏日志、生产 HEAD 与 Agent 注册心跳。
- 预期修复：创建成功与后续列表刷新分离，Token 优先安全展示或受保护地交付；避免假失败与重复提交；错误展示后端原始结构化错误码，不记录/泄漏 Token。

## 9. 建议优先级与阶段划分（不代表已开工）

| 优先级 | 工作项 | 实施/验收条件 |
|---|---|---|
| P0 | 定位“新增节点报错”，修复 POST 成功但刷新失败导致 Token 不展示 | 现场 API 证据 + 模拟 POST 成功/GET 失败的浏览器回归 |
| P0 | 中央持续自动分配/资源释放唤醒的闭环 | 无人工点击 / 浏览器刷新的端到端自动接单 |
| P0 | 节点能力硬授权、Agent ready、任务 portable 合同和真实剩余容量硬准入 | A/B/C/D 混合能力矩阵；禁止非法派发、忙碌假准入 |
| P0 | 低配控制端重负载边界梳理 | ZIP/哈希/清洗/推理/数据准备不占据 Web 主线程；保留轻量正式提交 |
| P1 | 单机多 GPU、CPU 清洗/ZIP 多执行槽的进程级隔离、配额和回收 | GPU UUID 独占或明确共享；CPU/RAM/disk 预算；无 OOM/双执行 |
| P1 | AI 预标注、视频抽帧、标签 remap/audit 的远程执行合同 | 保留现有 CandidateStore、AnnotationRepository、MaterialBatch final owner |
| P1 | 让素材从 NAS/OSS 直达 Worker 本地 SSD，控制端只负责 freeze/许可 | SHA、Revision、split leakage、重试、幂等缓存、真实传输测量 |
| P1 | 节点网络故障与 Agent 重启后租约/任务/缓存恢复 | 分区、心跳过期、重复领取、过期代次提交均 fail closed |
| P2 | Worker 一键安装、能力探测、配置/诊断、systemd 生命周期和运维 UI | 多版本兼容、日志与容量展示、无 Token 泄漏 |

**实施策略：** 先复现具体问题、跑现有回归，再最小批次推进；禁止大范围重构/平行 Owner/新任务状态机。每批必须刷新实际远端 HEAD/测试和准确 CI 结论，queued != passed。

## 10. 验收用例与禁止回退的安全合同

1. A/B/C/D 按第 3 节配置：仅 A 空且可训练时立刻分配 A；清洗只有 B/C eligible；统一标签只能 B eligible（若 C 未授权，不能发 C）。
2. B/C 都忙无清洗容量：清洗真实排队；C 释放后自动开始；A/D 始终不运行清洗。
3. 单台双 GPU 可并行训练两项、第三项排队；GPU UUID/映射一致，Agent 能真实并行执行、更新进度、释放资源。
4. B 正在 CPU 清洗且有足够 GPU/CPU/RAM/SSD 预算时可并行训练；预算不足时必须等待而非超卖。
5. 强机器 B 无训练剩余容量、弱机器 A 满足训练准入：A 赢得分配；强机器 B 有第二张空闲 GPU 时才参与合格节点排序。
6. 手动 pin A 不会溢出到 B；A offline/能力撤回时等待明确原因，不悄悄改派。
7. Agent 心跳失联/进程被杀/租约过期/进程残留，过期 generation 不能二次写结果；同一任务只能单次正式提交。
8. 新增节点 POST 成功但 GET 失败时仍能显示 Token，提示“已创建但列表刷新失败”，不伪造创建失败。
9. Agent 勾选不存在 Runner 的能力，不得作为 ready；不能将 `MATERIAL_BATCH/REMAP_ANNOTATION_LABELS` 误发给 ZIP `material-import` Runner。
10. 大型 ZIP/清洗/标注的耗时计算运行在 Worker；控制端 Web/API p95、心跳延迟与内存/磁盘峰值在目标低配机器预算内（阈值在现场根据硬件明确定义，不编造指标）。
11. NAS/OSS/MinIO 读取失败、短下载、SHA 不一致、原文件被删除时失败关闭；训练不混用旧 GT；缓存只复用相同 SHA/Revision 的 immutable Snapshot。
12. 图片标签 remap 正式 AnnotationRepository 与 Material 缩略展示一致；处理后必要审计受控，保持 `confirmed_empty`、人工确认、AI 候选与精确 train/val/test frozen split 语义。
13. 强控制端同时部署 Worker 时启用同样节点心跳和资源限制；低配控制端不启动重计算且功能保持正常。
14. 升级部署前验证跨服务器版本兼容、Python/CUDA 环境、对象存储读写权限、系统服务、网络 ACL、任务级权限和隔离。
15. 真实 Ubuntu/NVIDIA、NAS、OSS/S3/MinIO 及 1k/10k/20k 规模试验必须分别报告；只有测试真正完成/通过才能标记 VERIFIED。

**永久不变：** 不改写已有 GT/任务/版本身份，不合并 `main`，不 tag/release，不放宽/删除现有测试；本规范提交本身不表示代码实现、CI 通过或已部署。

## 11. 代码核验入口（截至审阅 SHA）

- `platform_core/task_node_assignments.py`：节点能力判断、GPU/清洗评分、硬准入差距、`CentralTaskAllocator`。
- `platform_core/service_nodes.py` 与 `static/modules/service-node-runtime.js`：节点白名单、心跳及新增节点表单/Token 生命周期。
- `platform_core/task_runtime/repository.py`：TaskRepository durable queue/lease 与资源等待状态。
- `platform_core/node_agent_executor_loop.py`、`node_agent.py`：Agent 支持的远程执行器及串行循环。
- `platform_core/worker_registry.py`、`platform_core/worker_supervisor.py`、`task_worker.py`：本地 Worker roles / all 兼容隔离。
- `platform_core/material_batches.py`：`MATERIAL_BATCH`、`REMAP_ANNOTATION_LABELS`、`AUDIT_LABEL_INTEGRITY`、`CLEAN` 正式 Owner。
- `platform_core/node_agent_cleaning_runtime.py`、`platform_core/node_agent_material_runtime.py`：Agent 清洗 / ZIP 预扫描实际执行范围。
- `platform_core/remote_training_tasks.py`、`platform_core/remote_training_transport.py`、`platform_core/node_agent_training_runtime.py`：TrainingPrepare、Bundle 对象存储传输、GPU 训练执行。
- `tests/unit/test_task_node_assignments.py`：混合能力/多 GPU 分配与“强忙节点仍可胜出”的当前测试行为；后续修订应新增反映用户硬准入的测试，而不是简单删除既有安全守卫。
- `tests/browser/service-node-management.spec.mjs` 与 `tests/api/test_service_node_api.py`：服务节点创建/心跳正常路径，缺 POST 成功但刷新失败的 Token 回归。

## 12. 本次文档提交记录

本批只新增本规范，并在 `docs/PROJECT_HANDOFF_CURRENT.md` 增加文档入口；**未改业务代码、`VERSION.txt`、测试或生产配置**。项目其他 OPEN/PENDING UAT 项目不因本次需求文档而关闭。
