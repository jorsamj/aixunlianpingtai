# 畅联云算法训练：运行链路收口与厂商部署设计

**状态：** 已确认（含 2026-08-31 跨平台与 Worker 补充约束）  
**日期：** 2026-08-31  
**适用版本：** v42.19.0 及后续收口版本  
**工作分支：** `feat/windows-p0`

## 1. 目标

在不重做现有产品、不替换现有 FastAPI、静态前端、训练 Worker 和转换 Worker 的前提下，收口以下真实用户链路：

1. 批量选择素材并连续标注，切图不闪烁、不丢框，保存后自动进入下一张。
2. AI 自动标注任务可创建、可见进度、可停止、可恢复、可审核、可全部拒绝，并持续保存候选结果。
3. 视频切帧真实生成图片并一次性或分批入库，刷新与重启后状态和产物一致。
4. 创建训练任务时既能从训练候选池按比例随机抽取试验集，也能分别手动选择训练集和试验集。
5. 算法迭代训练只能以上一个最新可训练版本作为基础权重。
6. 模型测试真实执行推理、生成结果图片，并提供真实阶段和错误反馈。
7. 转换任务只有在真实工具执行且真实产物通过校验后才成功；Atlas、RKNN、TensorRT 的“转换完成”和“目标硬件验证完成”分开记录。
8. Windows 先稳定运行；后续把同一平台部署到 NVIDIA Linux，并通过隔离的厂商转换节点完成 TensorRT、Atlas 和瑞芯微产物生成。
9. Web/API 不再直接承担训练、AI 批量标注、视频切帧、批量清洗、模型转换和长耗时部署测试，所有重任务通过同一持久化调度协议交给专用 Worker。
10. 业务代码、任务快照和 API 不写死盘符、反斜杠、Windows Shell 或 Windows 专用进程语义；同一份任务协议可以在 Windows 与 NVIDIA Linux 执行。

优先级固定为：真实可用 > 稳定 > 数据正确 > 状态正确 > 性能 > 界面表现。

## 2. 现场取证结论

本设计建立在 v42.19.0 的实际运行与真实数据取证上，不以静态代码推断代替运行结果。

| 链路 | 已验证事实 | 当前根因 |
|---|---|---|
| 批量标注 | 选择 10 张约耗时 3.3 秒；连续切图每次约 0.8～1.36 秒 | 每次切图主动关闭整个弹窗并延迟重建；选择一张也重绘整页 |
| AI 标注 | 真实 Ollama 任务一次处理 12,174 张；任务能调用模型 | 请求体随任务列表重复返回；逐图串行；候选仅在全部完成后写盘；无 AI 任务启动恢复 |
| AI 审核 | 候选审核页面存在 | “暂不应用”只关窗；空数组被后端当成“全部应用” |
| AI 进度窗 | 进度、数量、ETA 可显示 | 关闭或最小化后，轮询会再次强制打开弹窗 |
| 视频切帧 | 30 帧测试视频真实生成 3 张图片并入库 | 每一帧多次重写约 2.9 万条素材索引，3 张耗时 24 秒；来源字段在返回副本上修改，未持久化 |
| 训练划分 | 新建任务默认素材数为 0；最新迭代权重已显示正确 | 只有随机比例模式，没有手动训练/试验两组选择 |
| 模型测试 | YOLO11n 真实推理成功并生成结果图 | 每次启动独立 Python、导入框架、加载权重；冷启动约 25 秒，页面只有静态“检测中” |
| ONNX 转换 | 训练成果生成 10.08 MB ONNX；Checker 与 ONNX Runtime 推理通过；清单哈希一致 | 部署资源缓存与创建任务时的资源状态不一致，需人工重新检测 |
| 厂商转换 | 代码会调用 `trtexec`、CANN ATC、RKNN-Toolkit2，并检查目标文件存在 | 当前 Windows 无相应工具链、Docker、NVIDIA GPU 或 WSL Linux，不能实机验证 |
| 跨平台运行 | 大部分文件路径已使用 `pathlib.Path`，训练与转换命令主要使用参数数组 | 页面和飞桨资源仍含固定 `D:\\...` 默认值；飞桨 Worker 使用 `shell=True`；进程注册与线程任务散落在单体 API 中 |

本轮审计确认的 P0 事实：

- AI 审核把空 `image_ids` 当成全部候选，导致“全部拒绝”实际可能全部写入正式标注。
- 人工批量标注直接点上一张、下一张或缩略图时会销毁当前 DOM，未等待保存，存在静默丢框风险。
- AI 和视频使用进程内 daemon 线程，没有启动恢复；任务索引直接覆盖写 JSON，并发创建和进程中断存在丢任务/半截文件风险。
- 视频只有按间隔和 FPS，固定帧数尚未实现；逐帧多次重写完整素材索引，形成明显写放大。
- 部署测试 UI 只提供 PT/Paddle；ONNX 仅做零张量结构验证，TensorRT/OM/RKNN/BModel 没有对应 Runtime 的真实图片推理。
- 厂商产物未实机验证时，当前顶层任务仍写成 `done`；页面会显示“已完成”，不符合真实性门禁。
- 远程转换任务会把包含 API Key 的资源配置写进任务并原样回传；远程配置接口缺少鉴权，属于上线前必须修复的安全阻断项。
- 最终训练 UI 只有按比例随机留出的方式 B；较早的独立选择实现被后置同名函数覆盖，方式 A 没有最终生效。
- 当前页面称作“试验集”的 `val` 被训练期评估、早停和最佳 checkpoint 选择反复使用，实际是验证集；真正独立 `test` 通常为 0。
- 训练快照未记录 test 图片、内容哈希和完整来源，同内容不同 ID 可以跨集合，不能证明无数据泄漏。
- 训练队列只扫描单项目且依赖 Web 请求/页面轮询触发；不同项目可同时启动到同一 GPU，离开页面后后继任务可能不再启动。
- Windows 生成的 `data.yaml` 写入创建端绝对路径，远程 Linux 解压后不重定位，Windows 到 NVIDIA Linux 的真实训练链路尚未闭合。
- Paddle 训练绕过最终随机划分和优先级队列，仍含 `shell=True`，本地/远程高级参数也不等价。

## 3. 范围与非目标

### 3.1 本轮范围

- 修复上述入口到最终文件、任务状态和数据索引的完整链路。
- 修复与这些链路直接相关的卡顿、僵尸任务、刷新丢状态、重复执行、错误状态和数据不同步。
- 为 NVIDIA Linux、TensorRT、CANN ATC 和 RKNN-Toolkit2 提供可配置、可检测、可执行的部署边界。
- 使用隔离测试数据和真实本机模型执行验收。

### 3.2 非目标

- 不重新设计整个平台的信息架构或视觉风格。
- 不把现有系统迁移到新的大型框架。
- 不引入与本轮链路无关的业务功能。
- 不用假模型、假进度、空文件、复制改后缀或模拟成功代替真实产物。
- 不在没有目标工具链或目标硬件时声称 Atlas、RKNN、TensorRT 已实机通过。

## 4. 方案选择

采用“保留业务函数、抽离任务执行层”的增量方案。现有页面、API 合同、标注解析、视频处理、训练和转换业务函数继续使用；API 只校验和入队，Scheduler 领取持久化任务，再由不同 Worker 调用这些业务函数。这样可以最少改动业务代码，同时消除重任务运行在 Web 进程内的问题。

当前单机 Windows 和单台 NVIDIA Linux 首先使用 SQLite WAL 作为任务元数据仓库，并把大输入、逐图片结果、日志和产物保存在任务目录。领取任务使用事务化租约，不能依赖进程内字典或只在本进程有效的线程锁。未来需要多机高可用时，可把 `TaskRepository` 切换为 PostgreSQL；Worker Handler 和 API 合同不随之改变。

本轮不强制引入 Celery/Redis。它们不是功能真实可用的前提，且会增加 Windows 开发和本地交付依赖；但调度协议、租约和 Worker 边界必须按可替换方式实现，不能继续把 daemon 线程当成可恢复后台任务。

未采用只修改前端 loading、延迟或刷新频率的方案，因为它不能解决候选未保存、任务重启丢失、素材索引重复重写和真实产物缺失。

### 4.1 跨平台不可破坏约束

- 所有本地路径由 `pathlib.Path`、配置项和环境变量产生；不得在业务代码、页面默认值、数据库或任务协议中写死 `C:\\...`、`D:\\...`，也不得按反斜杠拆分路径。
- API 和前端保存项目内相对产物标识或受控 URL，不把某台 Worker 的绝对路径当作跨机器资源标识。
- 子进程统一使用参数数组、`shell=False`、明确的 `cwd` 和环境快照；Python 子进程使用当前资源配置的解释器或 `sys.executable`，不得拼接 Shell 命令字符串。
- `start.bat` 与 `start.sh` 只作为很薄的系统入口，二者调用同一个 Python Launcher；业务模块不得依赖 `cmd.exe`、PowerShell、Bash 或某个终端窗口存在。
- 暂停、继续、取消和强制终止统一走 `ProcessController`。Windows 的进程组/终止语义和 POSIX signal/process-group 语义只能放在该适配器内部，业务代码不得直接调用平台专有命令。
- Linux 默认数据根目录、模型目录、任务目录和日志目录由部署配置或挂载卷给出；Windows 的 `LOCALAPPDATA` 仅可作为开发默认候选，不能进入生产任务快照。
- 任何运行资源在领取任务前都要声明 `os`、`arch`、Python、GPU/加速卡、驱动、SDK、Runtime 和支持的任务类型；Scheduler 只把任务派给满足能力约束的 Worker。

### 4.2 服务角色与最小拆分

逻辑上固定为七个角色，Windows 开发时可以由同一个 Python 包启动成多个进程，Linux 生产时可分别部署：

1. **Web/API 服务：** 参数校验、权限、任务创建、分页读取、审核决策和产物下载；不执行 CPU/GPU 密集任务。
2. **任务调度服务：** 跨全部项目按任务类型、资源能力、依赖、优先级（数字越小优先级越高）和 FIFO 次序发放租约，处理超时回收和取消请求；同一物理 GPU/加速卡资源键在全平台只能被允许数量的任务占用。
3. **训练 Worker：** 生成不可变数据快照，执行训练，保存 checkpoint、指标和算法版本。
4. **AI 标注 Worker：** 缓存模型/客户端实例，逐项生成并持久化 AI 候选，不直接污染正式标注。
5. **视频/数据处理 Worker：** 读取视频信息、真实切帧、分批入库，并执行大批量清洗、去重和质量计算，全部保存可恢复检查点。
6. **模型转换 Worker：** 执行 ONNX 与厂商 Converter Adapter，采集真实命令、日志、版本、哈希和产物验证结果。
7. **部署测试 Worker：** 按模型格式选择真实 Runtime，执行预处理、推理、后处理和结果图写入。

每个 Worker 只读取自己领取的任务；租约包含 `worker_id`、`lease_token`、`leased_at`、`lease_expires_at` 和 `heartbeat_at`。Worker 只能用匹配的 token 更新任务，防止旧进程在超时后覆盖新 Worker 结果。

Scheduler 是唯一启动下一任务的组件，不依赖用户停留在训练页面或某个列表 API 被轮询。插队只重新排序 `QUEUED` 任务，不强占正在运行的任务；暂停是否释放资源由任务类型明确配置，训练默认 checkpoint 式暂停后释放资源。

## 5. 总体架构

本轮拆为三个可独立验收的实施轨道，按顺序交付：

1. **标注任务轨道：** 批量人工标注、AI 标注、任务持久化、审核与恢复。
2. **数据与训练轨道：** 视频切帧批量入库、训练/试验划分和训练快照。
3. **推理与部署轨道：** 模型测试 Worker、部署资源一致性、ONNX 与厂商转换节点。

三个轨道共用以下约束：

- 任务状态必须来自后台持久化记录。
- 结果状态只能在物理文件、数据记录和必要校验全部成功后更新。
- API 列表只返回摘要，较大的输入集合和逐项结果由详情接口读取。
- 所有写入采用原子替换或现有 `MaterialStore` 锁，避免刷新或并发操作破坏 JSON。
- 前端轮询只更新对应组件，不重新创建无关页面或弹窗。
- AI 批量标注、视频切帧、训练、模型导出/转换、大批量清洗和长耗时部署测试一律由 Worker 执行；HTTP 请求只完成有界的参数校验、入队和摘要查询。
- 列表接口必须分页，禁止一次返回全部图片 ID、全部候选或全部日志；Worker 也不得一次把所有大图读入内存。
- 可复用模型在 Worker 启动或第一次使用时加载，并按模型文件哈希/配置版本缓存；禁止每处理一张图片重新加载模型。

## 6. 持久化任务运行层

### 6.1 任务摘要与大字段拆分

继续保留现有项目级任务列表文件，但列表条目不得包含成千上万个图片 ID、完整候选结果或大段响应。

每个 AI 或视频任务使用独立目录：

```text
projects/<project_id>/<task_kind>/<task_id>/
  task.json
  request.json
  checkpoint.json
  chunks/
  task.log
```

- `task.json`：状态、进度、计数、阶段、错误码、可执行建议、心跳和时间。
- `request.json`：图片 ID、标签、模型和提示词版本快照。
- `checkpoint.json`：下一处理位置、已提交分块、重试次数和 Worker 标识。
- `chunks/000001.json`：最多 50 个逐图片结果，使用临时文件加原子替换。
- `task.log`：真实执行日志，不包含 API Key。

任务列表 API 使用公开序列化器移除 `request_payload`、密钥和大数组；详情 API 再按需读取请求和结果。

### 6.2 状态机

任务对外状态采用固定大写枚举：

- `QUEUED`：已经持久化并等待 Worker。
- `RUNNING`：Worker 已持有有效租约并正在执行。
- `AWAITING_CONFIRMATION`：AI 候选已真实生成，等待用户决定，仍属于未完成审核的业务状态。
- `PARTIAL_SUCCESS`：至少一个真实结果成功，同时存在失败项；页面必须显示成功项和失败项。
- `SUCCEEDED`：该任务类型的成功条件全部满足。
- `CANCEL_REQUESTED`：已请求取消，Worker 尚未到安全提交点。
- `CANCELLED`：Worker 已确认停止，不再生成新结果。
- `FAILED`：执行失败且没有达到该任务的最小真实成功条件。
- `BLOCKED_BY_ENVIRONMENT`：缺少 SDK、命令、Runtime、版本或可执行环境，任务未执行成功。
- `BLOCKED_BY_HARDWARE`：产物已完成前置校验，但最终目标 GPU/NPU/开发板验证在当前环境无法进行。

AI 标注任务的正常主路径为 `QUEUED -> RUNNING -> AWAITING_CONFIRMATION -> SUCCEEDED`。部分图片失败但仍有可审核候选时先进入 `AWAITING_CONFIRMATION`，审核完成后进入 `PARTIAL_SUCCESS` 并保留失败清单；如果所有图片均处理完而用户主动不采用候选，任务仍为 `SUCCEEDED`，同时记录 `accepted=false`。

视频、训练、转换和部署测试的正常主路径为 `QUEUED -> RUNNING -> SUCCEEDED`，有可继续使用的部分结果时才允许 `PARTIAL_SUCCESS`。缺少厂商 SDK 或目标硬件时分别进入 `BLOCKED_BY_ENVIRONMENT`、`BLOCKED_BY_HARDWARE`，不得伪装成 `SUCCEEDED`。

`stage` 单独记录 `LOADING_MODEL`、`PREPROCESSING`、`INFERRING`、`POSTPROCESSING`、`WRITING_RESULT` 等执行阶段，不能把阶段字符串混作任务最终状态。

每个运行任务至少每 10 秒更新 `heartbeat_at`。Scheduler/Worker 启动时：

- `QUEUED` 任务可被重新领取。
- `RUNNING` 且租约/心跳过期的任务从最近检查点恢复。
- 无法恢复的任务进入 `FAILED`，记录明确错误和可重试操作。
- `AWAITING_CONFIRMATION`、`SUCCEEDED`、`CANCELLED` 和阻断状态不重新执行。

### 6.3 停止、继续和重试

- 取消只在当前图片、当前帧或当前训练检查点安全提交后生效。
- 暂停保留检查点和已有结果。
- 继续从检查点后第一项开始，不重复调用已经成功的图片。
- 重试只处理失败项或从失败检查点继续。
- 同一任务同一图片结果以 `(task_id, image_id)` 保证幂等。
- 训练暂停/继续若底层框架不能安全原地挂起，则在最近一次可加载 checkpoint 结束进程，继续时创建新的执行尝试并从该 checkpoint 恢复；页面不得把“冻结进程”伪装成可靠暂停。

## 7. 批量人工标注

### 7.1 单实例标注器

批量模式保持现有三栏工作台：左侧虚拟化缩略图/列表、中央稳定标注画布、右侧当前图片的标签选择与标注信息。标签的新增、删除、启停和中英文对照仍只在配置中心管理；工作台只消费标签库，不在每个标注框旁重复展示整个标签库。

批量模式只创建一次标注弹窗和一次画布实例。切换图片时仅更新：

- 当前图片资源；
- 当前图片的标注框；
- 当前序号、保存状态和框列表；
- 左侧当前项高亮。

禁止在切图过程中调用 `closeModal()` 或重建整个标注器 DOM。

### 7.2 请求与画布一致性

- 每次切图生成递增的加载令牌。
- 旧图片请求晚返回时，如果令牌不匹配则丢弃，不能覆盖当前画布。
- 当前图片与相邻两张图片预加载。
- 左侧队列只渲染可视项和少量缓冲项；大批量任务不一次创建全部缩略图节点。

### 7.3 保存语义

- 自动保存队列串行执行，同一图片只允许一个在途保存。
- “保存并继续”必须等待服务端返回、重新读取摘要确认后再切到下一张。
- `Ctrl+S`、上一张、下一张和侧边栏切换使用同一个保存函数。
- 保存失败时保留当前画布和未保存标识，不自动跳过。
- 缩略图框数和中文标签在保存成功后局部更新，不重绘整个数据集页面。

## 8. AI 自动标注

### 8.1 执行与结果保存

- 每处理完一张图片，结果进入内存分块；最多 50 张或 10 秒即原子提交一个结果块。
- 已提交块更新检查点和任务计数。
- 任务停止、进程异常或服务重启时，已提交结果可继续审核，不重新计算。
- 所有图片失败且无候选时任务为 `FAILED`；部分失败时进入 `AWAITING_CONFIRMATION` 并展示失败清单。
- 本机 Ollama 默认单并发，避免显存和 CPU 抢占；在线 HTTP 模型使用受控小并发，并遵守重试和限流响应。
- 本地模型实例、在线 Provider 客户端和提示词模板快照以配置版本作为缓存键；Worker 不得每张图片重新初始化模型或客户端。
- 每个失败项保存稳定错误码，至少区分：`MODEL_NOT_FOUND`、`MODEL_LOAD_FAILED`、`OUT_OF_MEMORY`、`IMAGE_INVALID`、`INFERENCE_FAILED`、`PROVIDER_UNREACHABLE`、`PROVIDER_RATE_LIMITED`、`INVALID_PROVIDER_RESPONSE` 和 `UNKNOWN_LABEL`。

### 8.2 进度页面

自动标注页面展示：

- 当前阶段与状态；
- 已处理/总数、成功、空结果和失败数量；
- 候选框数量、真实耗时和动态 ETA；
- 最近错误和解决建议；
- 停止、继续、重试失败项、查看候选和审核结果。
- 当前图片名称/缩略图、实际已完成数量、总数量和失败数量；例如 `AI 标注中 38 / 120（31.7%）`，数值只来自已经提交的结果块。

关闭或最小化进度窗口只改变显示状态，不停止任务，也不允许轮询重新强制打开窗口。切换页面后任务继续；返回页面或刷新后从后台摘要恢复显示。

### 8.3 审核结果

审核接口明确区分：

- `image_ids` 未提供：确认全部可用候选。
- `image_ids` 为非空数组：只确认所选图片。
- `image_ids` 为空数组且 `decision=reject_all`：不写入任何正式标注，任务完成。

确认页面支持全部接受、部分接受、修改后接受和全部拒绝。修改仅写回该 AI 任务的候选版本，用户明确接受后才由审核服务原子写入正式标注。

确认写入后，候选框的 `source` 更新为 `ai_candidate_confirmed`。拒绝不删除候选审计文件，只记录 `confirmed_images=0`、`confirmed_boxes=0`、`decision=reject_all`、`accepted=false`，最终任务状态为 `SUCCEEDED`。接受全部或部分时记录 `accepted=true`、所选图片和候选版本。未审核时 `accepted=null`，任何候选都不得进入训练快照。

## 9. 视频切帧与素材入库

### 9.1 三种真实切帧模式

- `interval_seconds`：按秒间隔提取。
- `target_fps`：按目标 FPS 提取。
- `fixed_count`：在完整时长上均匀选择固定帧数，去重首尾相同帧。

Worker 优先使用检测到的 FFmpeg/FFprobe 参数数组执行，并解析真实时长、帧率和帧数；没有 FFmpeg 时允许使用项目现有 OpenCV 解码作为 Windows 开发回退，但必须在任务快照中记录实际执行器和版本。两种执行器都必须实际生成可打开的图片文件，禁止只生成数据库记录。

任务摘要至少保存 `duration_seconds`、`source_fps`、`estimated_frames`、`extracted_frames`、`progress_percent`、`output_artifact_prefix`、执行器、失败原因和失败帧。API/页面使用受控产物 URL 展示输出位置，不暴露或依赖 Worker 的绝对目录。

### 9.2 分块写入

- 切帧 Worker 每次处理最多 50 个输出作为一个入库批次。
- 图片文件、空标注文件和完整素材记录准备完成后，一次调用 `MaterialStore.mutate()` 提交。
- `video_task_id`、`frame_index`、`frame_time_seconds`、`split` 和 `processing_status` 在提交前写入记录。
- 每个已提交批次更新任务检查点和 `output_image_ids`。

这消除每一帧对大型 `images.json` 的多次全量重写。

### 9.3 恢复与幂等

- `(video_task_id, frame_index)` 作为任务内唯一键。
- 重启恢复时跳过已入库帧，从下一帧继续。
- 失败时保留已经提交的真实帧，并显示“部分完成”；重试不产生重复素材。
- 停止时保留已提交批次，未提交临时文件安全清理。

### 9.4 前端预计值

浏览器选择视频后使用视频元数据计算时长和预计帧数；无法解析时明确显示“将在服务端读取视频信息”，不能一直停留在无反馈状态。最终值只以后端 FFprobe/OpenCV 的实际读取结果为准。切出的图片和空标注记录完成同一批次提交后，必须能直接在素材库/数据集中分页读取和继续清洗、标注。

## 10. 训练、验证与试验素材

### 10.1 两种划分模式

创建训练任务增加 `split_mode`：

- `independent_test_set`：用户选择训练候选池和独立试验数据集/素材；独立试验素材不参与梯度训练和训练中的超参数选择。
- `random_test_from_training_pool`：用户选择训练候选池，并输入任意合理 `experiment_percent`（界面快捷值含 5%、10%、15%、20%）。后端每次创建任务生成新的 `test_seed`，先从候选池抽出试验集，再对剩余素材划分训练集与验证集。

两种模式初始选择都为 0，不沿用上次任务选择。

训练集、验证集和试验集语义必须分开：

- **训练集：** 参与权重优化。
- **验证集：** 训练期间评估、早停和选择最佳 checkpoint；`validation_percent` 作为收起的进阶参数提供已填好的默认值。
- **试验集：** 训练完成后独立评估，不参与训练过程中的选择。

随机模式固定执行顺序：先用 `test_seed` 抽试验集，再用独立的 `validation_seed` 从剩余池划分训练/验证集。不能把一次前端数组打乱当作可追溯划分。

### 10.2 后端校验

- 训练、验证与试验图片 ID 两两不重复。
- 同一内容哈希/来源指纹的重复图片不能跨集合，即使图片 ID 不同也要阻止数据泄漏并报告冲突项。
- 图片必须存在、属于当前项目、已处理且具有有效正式标注；未确认 AI 候选不得进入任何训练快照。
- 独立试验模式必须有训练候选池和独立试验素材；随机模式按实际候选数量计算，至少为训练、验证和试验各保留一张，否则拒绝创建并说明最少数量。
- 最终 `train_image_ids`、`validation_image_ids`、`test_image_ids`、三个集合的内容哈希、`split_mode`、比例、两个随机种子、算法版本、标签表和源数据快照 ID 写入不可变训练快照。
- 重试同一个任务必须复用已记录快照和种子；新建任务可以产生新的随机试验集，且其结果可按任务 ID 完整追溯。
- 视频连续帧、同一导入批次或同一采集源具有可用 group key 时，默认整组落入同一集合，防止相邻帧跨集合造成隐性泄漏；任务详情记录采用的分组规则。
- 远程训练包只保存相对 manifest。Linux Worker 解压后在自己的任务根目录重建 `data.yaml.path`，所有解析路径必须留在受控解压根内；Windows 绝对路径不得进入远程 YAML。
- 本地与远程 Worker 从同一不可变请求快照读取全部高级参数，完成后保存 requested/actual 对照，禁止远程静默丢参数。

任务详情必须显示：训练集数量、验证集数量、试验集数量、试验集来源、试验集抽样比例、验证比例、随机种子、数据快照 ID 和泄漏检查结果。

### 10.3 迭代基础模型

- 首次训练使用算法创建时选择的母模型。
- 有成功且权重校验通过的可训练版本后，后续训练强制使用该算法最新可训练成功版本的实际权重。
- 前端只展示锁定结果，不提供切回母模型或旧版本的选择控件。
- 创建任务时再次由后端解析最新版本，防止弹窗打开期间产生新版本导致过期选择。
- 失败、停止、缺失权重或校验失败的历史记录可以保留，但不得成为下一轮训练基础，也不能遮蔽更早的最新成功可训练版本。

## 11. 模型部署测试

### 11.1 持久部署测试 Worker

部署测试使用独立长驻进程，并按格式选择真实 Runtime：

- PT/PTH：Ultralytics/PyTorch Runtime。
- ONNX：ONNX Runtime。
- TensorRT Engine：TensorRT Runtime；不能用 ONNX Runtime 代替。
- OM：AscendCL/ACL 和可用 Atlas 设备。
- RKNN：RKNPU Runtime 与匹配的 RK3568/RK3588 设备。
- BModel：BMRuntime 与匹配的算能设备。

- 任务通过文件队列提交，主 API 不在事件循环内执行框架推理。
- Worker 按真实模型路径缓存最近使用的模型，模型文件哈希变化时自动失效。
- 同一 Worker 串行使用模型，避免线程不安全和显存争抢。
- Paddle 等独立环境继续使用隔离执行器，但也通过任务状态返回结果。
- 上传图片、选择模型、排队、推理和结果展示形成同一个可追溯任务；长耗时测试切页或刷新后继续存在。

### 11.2 成功条件

只有同时满足以下条件才进入 `SUCCEEDED`：

- 推理执行器退出成功；
- 结构化结果可解析；
- 结果图片真实存在且可由 PIL/OpenCV 打开；
- 检测框、类别和置信度来自实际模型输出，而非固定示例；
- 返回的模型、Runtime、设备和耗时来自实际执行器。

页面分别显示预处理耗时、模型推理耗时、后处理耗时和总耗时，并展示带框结果图、类别、置信度。超时、模型不存在、结果文件缺失或输出无法解析进入 `FAILED`。缺少 RKNN/Atlas/算能 Runtime 或对应板卡时进入 `BLOCKED_BY_ENVIRONMENT` 或 `BLOCKED_BY_HARDWARE`，页面明确显示当前环境无法执行真实板端测试，绝不能返回“测试成功”。

## 12. 转换、部署资源与目标验证

### 12.1 Converter Adapter 合同

转换执行层提供 `BaseConverter`，至少包含：

```text
detect_environment() -> EnvironmentReport
prepare_input() -> Artifact
convert() -> ExecutionResult
validate_artifact() -> ValidationResult
runtime_verify() -> RuntimeVerification
```

具体实现为 `OnnxConverter`、`NvidiaTensorRTConverter`、`HuaweiAtlasConverter`、`RockchipRKNNConverter` 和 `SophonConverter`。厂商转换统一先完成 PT/PTH/Paddle 到 ONNX 的真实中间阶段，再由目标 Adapter 处理；已经是合格 ONNX 时复用并记录其哈希。

每个转换尝试必须持久化：标准输出、标准错误、退出码、开始/完成时间、转换耗时、转换工具和版本、输入模型及 SHA256、输出模型及 SHA256、输出大小、命令参数数组（脱敏）、环境报告、最终状态和失败原因。日志文件与结构化摘要分开，任何密钥不得进入二者。

`convert()` 返回退出码 0 仍不等于成功；只有输出文件存在、非 0 字节且 `validate_artifact()` 通过后，才算真实转换产物生成。`runtime_verify()` 必须使用对应目标 Runtime，不能以 ONNX Checker 代替 TensorRT/OM/RKNN/BModel 验证。

### 12.2 资源状态一致性

- 部署资源列表、资源检测和创建任务使用同一个检测结果与失效时间规则。
- 创建任务前执行轻量、同步的关键工具确认，不能让刚显示 `ready` 的同一资源立即被判为不可用。
- 工具版本、Python 路径、目标列表和最后检测时间一起进入任务快照。
- 环境报告必须列出 OS/架构、工具、版本、缺失组件、要求版本、安装说明和可由 Worker 实际执行的检查命令。Windows 不支持的厂商转换应在入队前路由到满足能力的 Linux Worker，不能在 Windows 后端拼接 Linux 命令。

### 12.3 真实转换成功条件

- ONNX：文件存在、ONNX Checker 通过、ONNX Runtime 至少完成一次输入推理。
- TensorRT：`trtexec` 成功、`.engine` 存在，并在目标 NVIDIA 环境成功反序列化和最小推理。
- Atlas：CANN ATC 成功、`.om` 存在；目标 Atlas 环境加载并最小推理后才标记硬件通过。
- RKNN：RKNN-Toolkit2 成功、`.rknn` 存在；对应 RK3568/RK3588 板端 Runtime 加载并最小推理后才标记硬件通过。

转换清单保留：源模型哈希、ONNX 哈希、目标参数、工具版本、输出哈希、目标芯片、验证环境和验证时间。

状态固定区分：

- `CONVERTED_UNVERIFIED`：真实转换产物已生成且格式校验通过，但尚未在目标硬件验证；不是最终 PASS。
- `HARDWARE_VERIFIED`：目标 Runtime 已加载并执行最小真实推理。
- `BLOCKED_BY_ENVIRONMENT`：缺少转换 SDK/命令/兼容运行环境，没有生成合格目标产物。
- `BLOCKED_BY_HARDWARE`：目标产物已生成，但缺少对应 GPU/NPU/开发板，无法完成最后实机验证。

### 12.4 Linux 转换节点

Windows 主平台通过现有远程部署资源调用 Linux 转换节点：

- NVIDIA Linux 节点：Ultralytics、ONNX、TensorRT。
- CANN Linux 环境：Atlas ATC。
- RKNN Linux x86_64 环境：RKNN-Toolkit2。

三个厂商环境使用独立容器或独立虚拟环境。远程服务必须：

- 强制非空 API Key，启动时为空则拒绝对非 loopback 地址监听；
- 所有配置、探测、创建、查询、停止和产物接口都要求鉴权；
- 由反向代理提供 TLS；
- 任务、日志和产物目录使用持久卷；
- 服务重启后恢复或明确失败正在运行的任务；
- 不在日志和任务 JSON 中写入密钥；
- 远程服务返回任务前使用公开 DTO 删除密钥、环境变量和内部绝对路径，主平台也不得把完整远程响应原样存入前端可见字段；
- 主平台下载远程产物后安全解压，并按清单复算每个文件 SHA256、大小、源任务和目标参数；不一致时进入 `FAILED`，不得发布产物。

### 12.5 自动安装边界

- 只允许在专用虚拟环境或专用容器中安装已锁定版本、可校验来源且支持当前 OS/架构的 Python 级依赖。
- 自动安装前先做空间、网络、版本冲突和权限预检，记录安装命令与结果；失败不得破坏主平台运行环境。
- NVIDIA 驱动、CUDA、TensorRT 系统组件、CANN、RKNN 板端 Runtime、TPU-MLIR 系统镜像等需要管理员权限或严格版本配套的组件，不在 Web 请求中自动安装；系统给出官方要求、缺少项和可复制命令，由对应 Linux Worker/运维环境完成。
- 不安装与模型转换无关的 Codex 插件来代替厂商 SDK。

## 13. Windows 到 NVIDIA Linux 的迁移边界

### 13.1 Windows 阶段

- 使用当前代码和可配置数据根目录完成开发、页面、CPU 测试、素材、数据集、清洗、人工/AI 标注、视频切帧、小型真实训练、PT/ONNX 模型测试和 ONNX 验收。
- 当前 Windows 若具有受支持的厂商 Python 工具，也只执行官方明确支持的转换；不通过路径或命令兼容技巧伪装 Linux 工具可用。
- 厂商转换通过远程资源调用 Linux 节点。
- 不在 Windows 主 Python 中混装 CANN 或 RKNN 依赖。

### 13.2 NVIDIA Linux 阶段

- 主平台、训练 Worker、推理 Worker 和 TensorRT Worker运行在 NVIDIA Linux。
- CUDA 训练、TensorRT 构建、GPU 推理和生产任务由具备对应能力标签的 NVIDIA Linux Worker 执行。
- 主机安装匹配的 NVIDIA Driver、Docker 和 NVIDIA Container Toolkit。
- 数据目录、模型、任务、日志和转换产物全部挂载为持久卷。
- 启动检查必须验证 `nvidia-smi`、容器 GPU 可见性、PyTorch CUDA、Ultralytics 和可写数据卷。
- TensorRT Engine 默认在最终目标 GPU 环境构建和验证，因为序列化 Engine 受平台、TensorRT 版本和 GPU 架构约束。

Atlas、Rockchip 和 Sophon 不与 NVIDIA Worker 混装工具链；分别由 CANN Converter Worker、RKNN Converter Worker 和 TPU-MLIR Converter Worker 执行。主平台只交换任务快照、相对产物标识、哈希和状态，不共享某台机器的绝对路径。

官方依据：

- NVIDIA Container Toolkit 安装与运行时配置：<https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>
- TensorRT Engine 版本、硬件和平台兼容性：<https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/engine-compatibility.html>
- RKNN-Toolkit2 PC 转换与板端 Runtime 分工：<https://github.com/airockchip/rknn-toolkit2>
- 华为 CANN ATC Linux 转换工具：<https://www.hiascend.com/doc_center/source/zh/canncommercial/60RC1/inferapplicationdev/atctool/CANN%206.0.RC1%20ATC%E5%B7%A5%E5%85%B7%E4%BD%BF%E7%94%A8%E6%8C%87%E5%8D%97%2001.pdf>
- CVAT 自动标注函数与执行代理边界：<https://docs.cvat.ai/docs/api_sdk/sdk/auto-annotation/>
- ClearML Worker/Queue 的重任务与资源队列边界：<https://clear.ml/docs/latest/docs/fundamentals/agents_and_queues/>
- NVIDIA Triton 模型加载与不可用状态管理：<https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_management.html>
- NVIDIA Triton 对排队、输入处理、推理和输出处理耗时的分项度量：<https://docs.nvidia.com/deeplearning/triton-inference-server/archives/triton-inference-server-2640/user-guide/docs/model_analyzer/docs/metrics.html>

## 14. 错误处理

所有链路统一返回：

- `code`：稳定错误码；
- `message`：用户可读说明；
- `solution`：可执行解决步骤；
- `retryable`：是否允许直接重试；
- `task_id`：存在后台任务时返回；
- `details`：仅包含不敏感的执行上下文。

典型错误必须单独区分：模型服务不可达、限流、响应不是合法 JSON、标签不在标签库、图片文件缺失、视频解码失败、训练素材不足、基础版本文件缺失、转换 SDK 缺失、目标芯片参数无效、产物缺失和目标 Runtime 验证失败。

## 15. 测试与验收

### 15.1 数据隔离

- 自动化和压力测试必须把 `MC_TRAIN_DATA_DIR` 指向临时目录。
- 除人工确认的端到端验收外，不向用户现有项目写入测试素材。
- 测试结束精确清理本轮生成的临时项目、测试视频和测试任务。

### 15.2 自动化测试

- 单元测试：状态机、租约、任务公开序列化、检查点、幂等键、空选择拒绝、三集合训练划分、内容哈希泄漏阻止、资源缓存一致性、Converter Adapter 和清单校验。
- API 测试：创建、暂停、继续、取消、失败、重试、分页读取、刷新读取、服务重启恢复、多个任务并存、旧租约拒绝写回、远程接口鉴权、密钥不回流和下载产物哈希复验。
- 浏览器测试：批量选择、50 张连续切图、保存后自动下一张、关闭进度窗不重开、刷新恢复、独立/随机试验集、AI 全部/部分/修改/拒绝审核和部署推理结果展示。
- 跨平台静态与运行测试：生产模块不得出现固定盘符或 `shell=True`；Windows 与 Linux CI 都执行路径、命令参数、SQLite 任务仓库和 Worker 领取测试。
- 性能测试：大图片列表分页、缩略图虚拟化、AI 结果分块、视频批量入库和任务列表摘要大小设置明确阈值，失败即回归。
- 回归测试：现有后端、前端和浏览器测试套件全部通过。

### 15.3 真实 Windows 验收

1. 连续选择至少 50 张素材，选择操作不触发全页重绘。
2. 顺序和随机连续切换至少 100 次，覆盖不少于 50 张不同图片；Canvas 实例不销毁、弹窗/框不消失、无白屏、旧响应不覆盖当前图片、保存数据与缩略图一致。
3. 使用当前真实 Ollama 模型完成至少 10 张 AI 标注，候选分块文件真实存在；刷新和重启后可继续。
4. 分别验证全部接受、部分接受和全部拒绝；全部拒绝正式标注写入数量为 0。
5. 使用短视频和较长视频完成切帧；30 帧/3 输出的小视频在当前机器目标耗时不超过 5 秒。
6. 完成一次独立试验集任务和一次按比例随机试验集任务；训练/验证/试验三集合无 ID 或内容哈希泄漏，快照、数据库和页面详情一致。
7. 完成至少一次真实 1 epoch 小数据训练，生成可加载的 `best.pt` 或 `last.pt`。
8. 同一模型连续推理三次，冷启动允许显示真实加载阶段，热启动单次目标不超过 5 秒。
9. 从训练权重生成 ONNX，独立执行 Checker 和 ONNX Runtime 推理并核对哈希。

10. 在隔离数据根目录下连续创建、取消、重试多类任务并重启 Web、Scheduler 和 Worker，状态、检查点、数据库和文件保持一致。

### 15.4 厂商实机验收

- NVIDIA：在目标服务器生成 `.engine`，反序列化并执行真实图片推理。
- Atlas：在目标 CANN/Atlas 环境生成 `.om`，加载并执行真实图片推理。
- RK3568 与 RK3588：分别生成目标匹配 `.rknn`，在对应板端加载并执行真实图片推理。

没有对应服务器或开发板时，这些项目必须保留为 `BLOCKED_BY_HARDWARE` 和“当前无法真实验证”，不得转写为已完成。

## 16. 完成定义与证据

任何功能只有同时满足以下条件才可标记完成：

```text
代码完成
+ 实际启动
+ 实际执行
+ 结果文件真实存在且非 0 字节
+ 数据库/任务仓库状态正确
+ 前端状态和最终结果一致
+ 自动化测试通过
+ 连续操作与相关回归通过
```

转换功能额外要求真实 Converter 退出码为 0、结构化日志完整、输出 SHA256/大小可核对、格式校验通过，并由对应 Runtime 成功加载和最小推理后才是最终 PASS。缺硬件时只能是 `BLOCKED_BY_HARDWARE`，缺 SDK/Runtime 时只能是 `BLOCKED_BY_ENVIRONMENT`。

验收记录按任务保存：测试环境、输入、操作步骤、任务 ID、数据库快照、输出文件、哈希、关键日志、页面截图、自动测试结果和尚未通过项。测试一次成功、第二次失败仍判定失败；小数据成功但规定批量压力明显卡顿仍判定未完成。

## 17. 交付分解

由于本设计覆盖三个可独立验收的子系统，实施计划拆为三份并顺序执行：

1. 标注任务稳定性与可恢复执行计划。
2. 视频、素材批量入库与训练划分计划。
3. 推理、部署资源与厂商转换计划。

每份计划都遵循测试先行、小步提交和完成后真实浏览器回归。前一计划通过验收后再进入下一计划，避免多条链路同时修改导致回归难以定位。
