# 畅联云算法训练 v42.24.0

面向视觉算法生产流程的一体化平台，覆盖素材上传、数据清洗、人工与 AI 标注、训练任务调度、算法版本迭代、模型转换和部署测试。

当前优先保证 Windows 本机开发与 CPU 闭环可运行；同一套任务协议、相对路径和 Worker 机制可迁移到 NVIDIA Linux。华为 Atlas、瑞芯微 RKNN、NVIDIA TensorRT 和算能 Sophon 等能力只有在对应 SDK、Runtime 与硬件验证通过后才会标记成功，不使用假进度、空产物或改后缀文件模拟结果。

## 当前版本重点

### 素材与数据清洗

- 服务器目录、ZIP 和对象存储扫描可识别 YOLO `data.yaml`/`names`、图片与同名 `.txt` 标注；确认时显式完成 YOLO 类别到平台标签 `code` 的映射，并把无框负样本保存为 `annotation_state=confirmed_empty`。
- 单张或批量上传后立即显示缩略图，上传记录和素材索引持久化，刷新后仍可读取。
- 未处理素材支持批量选择、批量清洗和批量无需清洗；无需清洗的素材直接进入已处理区。
- 清洗使用 Pillow/OpenCV 检查损坏、精确重复、近似重复、尺寸、模糊度与亮度等问题。
- 清洗扫描结果先进入确认环节，确认前不会删除图片；删除时同步处理素材文件和标注文件。
- 数据列表支持文件名搜索和多标签筛选。标签选项来自统一标签库，多标签使用 OR 逻辑，命中任意选中标签即可显示。

### 多来源存储与服务器素材导入

- 统一素材池支持 Local、阿里云 OSS、S3/MinIO 和 Remote Server；标签、素材 ID 与物理存储来源彼此独立。
- 远程素材只建立 `image_id → storage_source_id → object_key` 索引，训练、标注和清洗通过 `StorageManager` 解析，不会因导入而全量复制到平台上传目录。
- Local 目录扫描使用流式遍历；扫描候选写入每任务独立的 SQLite manifest，结果 JSON 只保存汇总与 manifest 引用。
- 扫描按对象路径和内容 SHA256 去重；确认导入通过正式的原子状态转换重新进入队列，由 Worker 分批、幂等建立索引。
- 服务器 ZIP 只接受允许导入目录内的相对路径，先进行 Zip Slip/Zip Bomb/磁盘空间检查并解压到任务 staging；目标目录已存在时默认拒绝覆盖。
- 关闭扫描弹窗只停止浏览器轮询，不会取消后台 durable task；重新打开页面可以继续读取任务状态。
- 存储源重扫描使用持久任务区分 `NEW / MISSING / CHANGED / UNCHANGED`，确认前不修改索引；变更素材会失效内容缓存并把已有标注标记为待复核，扫描仍是只建索引、不全量复制。
- 大批量删除索引、删除源文件、无需清洗、清洗和 AI 标注统一通过服务端持久任务执行；筛选结果在确认时冻结为不可变 SQLite manifest，并提供真实进度、失败示例、重试、取消与任务日志。`CLEAN` 只检查并产出复核结果，`AI_ANNOTATE` 由 Worker 生成候选后进入人工审核。

### 人工标注

- 标签统一在“配置中心 → 标签管理”维护，标注窗口不创建或删除标签。
- 英文 `code` 是训练、导入和导出的稳定标识；中文 `display_name` 用于业务界面展示。
- 支持矩形框新建、拖动、缩放、改标签、删除、撤销、重做及画布缩放。
- 支持批量标注：左侧缩略图队列、中央稳定画布、右侧标注框信息。
- 切换图片前会等待保存；稳定画布不会因切图反复销毁，过期接口响应不能覆盖当前图片。
- 保存成功后同步更新素材摘要、标注数量和缩略图框；重新进入页面仍可恢复正式标注。

### AI 自动标注

- 支持配置火山方舟、阿里云千问、本地 OpenAI 兼容服务和 Ollama 等视觉模型。
- 每个模型配置可保存接口地址、模型名称、API Key、提示词模板、置信度等参数。
- AI 标注由后台 Worker 执行，页面读取后端真实进度、已处理数量、失败数量、当前图片和错误原因。
- 候选结果独立持久化，不会自动污染正式标注。
- 候选结果支持全部接受、部分接受、修改后接受、全部拒绝和暂不处理。
- 用户全部拒绝后任务仍可正常结束，并记录 `accepted=false`，正式标注保持不变。

### 视频切帧

- 视频任务由后台 Worker 执行，支持按秒间隔、目标 FPS 和固定帧数三种抽帧方式。
- 实际生成的图片会写入素材库，任务结果记录视频信息、计划帧数、已提取数量、输出与失败原因。
- 固定帧数模式按视频真实帧范围生成不重复采样位置，不只创建数据库占位记录。

### 训练任务与算法迭代

- 每次训练把图片、标签、快照和 YAML 复制到任务专属工作包，拒绝符号链接、硬链接和 reparse point，训练过程不会写回或依赖源素材链接。
- 创建训练任务时按图片素材选择，不再把数据集作为训练选择单位。
- 训练入口不依赖任何数据集分组记录，底层与界面都默认不选素材；逐张勾选不会重建缩略图列表。
- 每次打开训练弹窗默认全部不选，支持逐张勾选、全选、全部不选、筛选结果全选和筛选结果反选。
- 训练候选只包含已处理、已正式标注且文件存在的素材；标签仅用于筛选。
- 支持两种试验集方式：
  - 从本次训练素材中按任意合理百分比随机抽取；
  - 单独选择独立试验素材。
- 后台再从非试验素材中抽取验证集，并按来源组进行划分，避免同来源数据泄漏。
- GPU 任务贯穿记录 `requested_device / assigned_device / actual_device`；Resource Manager 基于真实可见 GPU 与显存预留进行 admission，训练进程校验租约、GPU 身份和实际设备后才启动。
- 自动资源策略会解析实际 `batch / workers / cache`，记录原因、GPU/CPU/IO 采样、epoch 时长和吞吐指标；手动策略仍保留显式参数合同。
- 任务快照保存最终训练、验证、试验素材 ID、数量、比例、随机种子和来源，可追溯且刷新后不改变。
- 首次训练使用所选母模型；已有合格算法版本时，下一次训练强制锁定最新可训练版本权重，不能退回母模型。
- 任务优先级范围为 1–999，数字越小优先级越高；同一资源同优先级按进入队列时间排序。
- 支持排队任务插队，以及运行任务暂停、继续和停止。进程控制会校验持久化的进程身份。
- 高级训练参数默认折叠并提供默认值，包含 Epoch、Batch、图片尺寸、优化器、学习率、数据增强、阶段评估和达标阈值等。
- 训练完成后形成新的算法版本；算法综合报告和单版本训练报告分别保存。

### 模型转换与部署测试

- 转换任务由独立 Worker 执行，记录输入、输出、命令、标准输出、标准错误、退出码、耗时、工具版本、文件大小和 SHA256。
- 通用路径优先执行真实 PT → ONNX 导出，并使用 ONNX Checker 与 ONNX Runtime 验证。
- 部署资源页面会检测转换工具、版本、目标芯片和运行环境；资源不可用时明确显示缺少项。
- 部署测试通过后台 Worker 调用对应真实 Runtime，结果包含检测框、类别、置信度和预处理/推理/后处理/总耗时。
- 当前机器没有厂商 SDK、Runtime 或硬件时返回 `BLOCKED_BY_ENVIRONMENT` 或 `BLOCKED_BY_HARDWARE`，不会显示测试成功。

### 本机训练环境与模型发现

- Ultralytics 环境检测与模型文件检测已经解耦：Python、Ultralytics、Torch、TorchVision 和 CUDA 均可正常导入时，即使没有 `yolo11n.pt`，环境仍可判定为可用。
- 一键检测先发现当前解释器、PATH、Conda、venv/.venv、AppData、Program Files 和已保存环境；候选 Python 会由真实子进程执行导入探测。
- 快速发现不足时可创建后台全机深度检测任务；Windows 动态枚举本地磁盘，Linux 枚举合理挂载点，并跳过虚拟或网络文件系统。
- 本机模型支持指定目录扫描和后台全机扫描，覆盖 PT/PTH/ONNX/Engine/RKNN/BModel/OM/Paddle 等格式；结果持久化分页展示，刷新页面不会自动重新扫描。
- 官方 YOLO 模型按环境模型目录、Ultralytics `weights_dir`、已扫描缓存、项目目录、平台缓存和当前目录依次解析；未找到时显示“未下载/可下载”，不会把环境误判为失败。
- 启动器在 Linux 上优先复用当前已经通过 CUDA 探测的 PyTorch 环境，不会为本轮 Windows 启动流程主动覆盖成 CPU Torch。

## 运行架构

```text
浏览器
  │
  ▼
FastAPI Web/API
  │  创建任务、读取状态、审核候选、下载产物
  ▼
SQLite 任务仓库 + ArtifactStore
  │  按优先级、FIFO、资源能力发放租约
  ▼
Task Worker / Scheduler
  ├─ annotation       AI 自动标注
  ├─ video            视频切帧
  ├─ training         Ultralytics 持久训练
  ├─ conversion       ONNX/厂商模型转换
  └─ deployment-test  真实 Runtime 推理测试
```

Windows 一键启动时，启动器会使用同一个数据根目录启动 Web/API 和一个 `--roles all` 的任务 Worker。相同数据目录、主机、角色和默认 slot 的重复 Worker 会被拒绝；有意并行必须显式使用 `--allow-parallel --worker-slot NAME`，训练并行还需命名 `--training-slot`。Linux 生产环境可以按角色拆分多个 Worker，并通过能力标签把 CUDA、TensorRT、CANN、RKNN 或 TPU-MLIR 任务发送到正确节点。

启动快照只加载项目核心元数据、计数和当前分页，不再为每个项目全量读取素材或遍历全部标注目录；资源发现与模型全盘扫描也不会阻塞首屏 bootstrap。

当前通用持久任务 Worker 的训练能力标识为 `training.ultralytics`。PaddleDetection 仍通过项目已有的独立 Paddle/远程训练执行环境接入，不应把它描述为已注册到该通用 Worker。

持久化任务状态包括：

```text
QUEUED
RUNNING
AWAITING_CONFIRMATION
PARTIAL_SUCCESS
SUCCEEDED
CANCEL_REQUESTED
CANCELLED
FAILED
BLOCKED_BY_ENVIRONMENT
BLOCKED_BY_HARDWARE
```

## Windows 快速启动

### 环境要求

- Windows 10/11 64 位；
- 64 位 Python 3.10–3.12，推荐 Python 3.12；
- 首次安装依赖需要能够访问 Python 包源；
- 视频切帧依赖 OpenCV 可用的视频解码能力；遇到系统缺少的编码格式时，需要补充对应 FFmpeg/编解码环境；
- NVIDIA GPU 训练还需要匹配的驱动、CUDA 与 PyTorch 环境；无 GPU 时可进行 CPU 小规模验证。

### 获取代码

```powershell
git clone https://github.com/jorsamj/aixunlianpingtai.git
cd aixunlianpingtai
```

### 推荐启动

双击 `start.bat`，或在 PowerShell 中运行：

```powershell
.\start.ps1
```

启动器会：

1. 检查 Python 版本；
2. 创建或复用平台独立虚拟环境；
3. 安装并实际导入检查核心依赖；
4. 启动后台任务 Worker 和 Uvicorn API；
5. 完成数据预加载后打开 `http://127.0.0.1:8010/`。

如果当前 Python 环境已经安装全部依赖，可以运行：

```powershell
.\start_no_venv.bat
```

常用环境变量：

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `MC_PORT` | Web/API 端口 | `8010` |
| `MC_HOST` | Web/API 监听地址 | `0.0.0.0` |
| `MC_TRAIN_DATA_DIR` | 素材、任务数据库和产物根目录 | 平台自动解析的用户数据目录 |
| `MC_TRAIN_VENV_DIR` | 指定平台虚拟环境目录 | 按 Python/平台版本隔离 |
| `MC_SKIP_VENV` | 设为 `1` 时使用当前 Python | 未设置 |
| `MC_PIP_INDEX_URL` | 自定义 Python 包镜像 | 自动选择 |

不要把业务数据放进 Git 仓库。模型权重、任务数据库、上传素材和转换产物应放在 `MC_TRAIN_DATA_DIR` 或独立模型目录中。

### 环境诊断

```powershell
.\diagnose_runtime.bat
python task_worker.py --data-dir "D:\your-data" --roles all --check
```

第二条命令只检查 Worker 注册、任务数据库位置、产物目录和能力，不执行任务。

## NVIDIA Linux 与厂商转换节点

正式生产建议把数据、模型、任务数据库、日志和产物放在持久卷中，并按角色部署进程：

- NVIDIA Linux：Web/API、训练 Worker、部署测试 Worker、ONNX/TensorRT 转换 Worker；
- 华为 CANN Linux：Atlas/Ascend Converter Worker；
- RKNN Linux x86_64：RKNN-Toolkit2 Converter Worker；
- 算能 Linux：TPU-MLIR Converter Worker。

远程训练节点示例：

```bash
export MC_REMOTE_DATA_DIR=/srv/changlian/data
export MC_REMOTE_HOST=0.0.0.0
export MC_REMOTE_PORT=8020
./start_remote_server.sh
```

远程部署转换服务示例：

```bash
export PYTHON_BIN=/opt/vendor-env/bin/python
export DEPLOY_SERVER_PORT=8030
./start_remote_deploy_server.sh
```

生产环境还应在反向代理层配置 TLS、访问控制和防火墙，并为远程接口设置非空 API Key。TensorRT Engine 通常应在最终目标 GPU、CUDA 与 TensorRT 版本环境中构建和验证。

## 转换能力与验证边界

| 目标格式 | Windows 开发机 | Linux/目标设备 | 判定成功的最低条件 |
| --- | --- | --- | --- |
| ONNX | 已支持 | 已支持 | 导出成功、文件非空、Checker 通过、ONNX Runtime 推理通过 |
| TensorRT `.engine` | 仅在安装兼容 `trtexec` 时可执行 | NVIDIA GPU + CUDA + TensorRT | 构建成功，并在目标 TensorRT Runtime 反序列化和推理 |
| Atlas `.om` | 通常通过远程 CANN 节点 | CANN/ATC + Atlas | ATC 成功；目标设备加载和推理后才算硬件验证 |
| RKNN `.rknn` | 通常通过 Linux/WSL2 转换节点 | RKNN-Toolkit2 + RK3568/RK3588 | 转换成功；匹配芯片 Runtime 加载和推理 |
| Sophon `.bmodel` | 通常通过远程 TPU-MLIR 节点 | TPU-MLIR + 算能设备 | 编译成功；BMRuntime 加载和推理 |

只有当前置转换和目标 Runtime 验证都具备证据时才是最终 PASS。生成真实产物但尚无目标硬件时，必须保留为“已转换、未实机验证”或 `BLOCKED_BY_HARDWARE`。

## 开发与测试

安装开发依赖：

```powershell
python -m pip install -r requirements-dev.txt
npm ci
```

运行完整自动化测试：

```powershell
python -m pytest -q
npm test
npm run test:browser
```

运行真实 CPU 训练和 ONNX 转换验收：

```powershell
python -m pytest tests/e2e/test_real_yolo_training.py tests/e2e/test_real_onnx_conversion.py -v -s
```

厂商硬件测试只有显式提供环境后才运行：

```powershell
$env:XJALGO_VENDOR_TARGET = "tensorrt"   # ascend / rockchip / tensorrt
$env:XJALGO_VENDOR_TEST_ONNX = "D:\models\verified.onnx"
$env:XJALGO_TRTEXEC_PATH = "C:\path\to\trtexec.exe"
$env:XJALGO_TENSORRT_ENVIRONMENT = "RTX 4090 / CUDA 12.x / TensorRT 10.x"
python -m pytest tests/hardware/test_vendor_conversion.py -v -s
```

没有设置目标、源 ONNX 和对应 SDK 参数时，该测试会明确跳过，不能据此宣称厂商转换通过。

### 当前回归与验证边界

以下是 v42.21.1 的历史自动化回归基线，不覆盖 v42.24.0 本轮新增代码：

- Python：248 项通过，2 项因当前环境条件跳过；
- 前端 Node 测试：40 项通过；
- Playwright 浏览器真实操作：14 项通过；
- JavaScript 语法和 Git 差异检查通过。

浏览器回归覆盖创建算法、素材上传、手工/批量标注与刷新恢复、标签筛选、清洗入口、AI 候选审核、转换资源、训练素材精确选择、最新版本迭代和优先级队列。

v42.24.0 本轮只在 Windows 工作树做发布差异核对，未执行实际启动、浏览器 E2E 或自动化测试。真实 20k 数据集重跑、付费 AI 服务、OSS/S3/Remote 标注导入，以及 A800 多 GPU 的调度、共享、资源参数和吞吐均未验证；不能宣称百万规模端到端已验证。Atlas、RKNN、TensorRT 和 Sophon 的最终目标硬件验证仍必须在对应服务器或开发板上单独完成。

## 目录说明

```text
app.py                         FastAPI Web/API
launcher.py                    Windows 一键启动器
task_worker.py                 通用任务 Worker 与 Scheduler 入口
platform_core/task_runtime/    持久任务、租约、调度与产物存储
platform_core/storage/         多来源存储 Provider、解析与缓存
platform_core/discovery/       本机环境/模型发现、持久缓存与后台扫描
platform_core/training_tasks.py
platform_core/video_tasks.py
platform_core/annotation_task_service.py
platform_core/deployment/      转换与部署测试任务
static/                        当前 Web 前端
tests/                         单元、API、集成、E2E、浏览器和硬件测试
docs/superpowers/specs/        已确认的关键设计约束
docs/superpowers/plans/        分阶段实施与验收计划
```

## 真实性原则

平台判断功能完成时遵循：

```text
代码完成
+ 实际启动
+ 实际执行
+ 结果文件存在且非 0 字节
+ 数据库/任务状态正确
+ 前端状态与结果一致
+ 自动化测试通过
+ 相关回归通过
```

缺少 SDK、Runtime、驱动或目标硬件时应报告具体阻塞条件，不以“理论可行”替代实际验证。
