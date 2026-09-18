# 畅联云算法训练平台 — Node Control Plane / Central Assignment

更新时间：2026-09-18  
分支：`feature/external-algorithm-publishing`  
正式版本：`VERSION.txt = 42.24.0`

> 本文记录服务节点控制面与中央任务→节点分配的当前真实边界。接手时仍必须先读取远端最新 HEAD，不能把本文中的 SHA 当作固定 checkout 目标。

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 2 — Agent YOLO review + label mapping + AnnotationRepository

2026-09-18，`MATERIAL_IMPORT` 的第二阶段已 CLOSED。Phase 1 的图片 ZIP 跨机器导入保持成立，Phase 2 在同一个 portable review/finalization 框架上新增真实 YOLO 数据集解析：

```text
server_zip + execution_mode=agent + import_format=yolo
```

当前真实链路：

```text
控制面选择服务器 YOLO ZIP + OSS/S3/MinIO 目标存储
→ source ZIP immutable staging(size/SHA256)
→ Agent 下载并安全解包
→ 复用 YoloImportScanner 解析 data.yaml / images / labels
→ Agent 校验图片解码、尺寸、SHA256、同包重复
→ 解析 normalized YOLO boxes / confirmed-empty / invalid sidecar / issue evidence
→ review ZIP:
   meta.json
   review.jsonl
   yolo/annotations.jsonl
   files/<selected candidate bytes>
→ generation-scoped immutable result PUT/confirm
→ 控制面重新下载 review ZIP 并验证：
   task/project/generation/source/prefix/dataset_yaml/classes
   每个 candidate 的 SHA256/size/dimensions
   每条 annotation 的 object key/split/status/box_count
   每个 box 的 line/class/normalized cx/cy/w/h
→ task-owned ImportCandidateStore 保存 external classes + annotation evidence
→ API 对外暴露 quality/external_classes
→ 用户确认 object selection + label_mapping/create_labels + quality acceptance
→ 同一 task 原子恢复为 QUEUED/indexing_queued + storage.import
→ local indexer 发布最终选中图片到目标对象存储并再次验证 SHA256/size
→ external class_id 按冻结 confirmation.label_mapping 映射平台 label code/class_id
→ normalized YOLO boxes 转像素坐标
→ 写 MaterialRepository + AnnotationRepository
→ confirmed_empty 保留为空标注真相
→ finish(SUCCEEDED)
```

关键边界：

- Agent 不打开中央 MaterialRepository / AnnotationRepository / TaskRepository / SQLite，不依赖共享 NFS。
- Agent 不持有 OSS/S3 长期凭据；仍只使用短期 transport contract。
- YOLO annotation evidence 必须先被控制面 server-confirm，再允许用户确认。
- 用户 label mapping 是 durable confirmation truth；indexer 不重新猜标签名称。
- 平台标签在 index 时必须仍为 active；若已失效则 fail closed，不能静默改标签。
- 缺失/invalid sidecar 不得擦除已有正式 annotation。
- `confirmed_empty` 会写正式 AnnotationRepository，不等同于“未标注”。
- 图片对象先完成发布与 hash/size 验证，再提交 Material/Annotation truth。
- Phase 1 的图片模式继续可用；YOLO 支持不是通过旧测试放宽，而是新增真实 Agent parser/review/commit/index 闭环。
- Windows/Linux 仍使用安全相对路径与同一 review bundle contract。

Phase 2 永久验收：

- Remote Material Import `35311171823`
  - production API：success
  - Ubuntu 24.04 contract + Agent→indexer annotation integration：success
  - Windows latest contract + Agent→indexer annotation integration：success
- 临时 draft PR #17 已关闭，**未 merge**。
- 正式 `VERSION.txt` 仍为 `42.24.0`。

Phase 1 历史验收保持：

- Remote Material Import `35308672897`
- Node Agent Executor `35308672844`
- Portable Deployment `35308672842`
- Central Node Assignment `35308672962`

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 3 — staging object lifecycle / GC

2026-09-18，远程素材导入临时对象生命周期已 CLOSED。

治理范围只包含 Agent MATERIAL_IMPORT 的 task-owned staging 对象：

- source ZIP：`remote-execution/<project>/<task>/material-input/...`
- generation-scoped review ZIP：`remote-execution/<project>/<task>/material-review/generation-N/...`

不会触碰正式目标素材对象。

真实策略：

- server-confirm review 成功后，控制面先把 review ZIP、candidate/annotation truth 写入 task artifact。
- result commit 阶段只写 durable cleanup ledger，**不在 result.json/upload-state 落盘前删除远端对象**，避免崩溃后 confirm 重试失去 review。
- task 进入 `AWAITING_CONFIRMATION` 后，storage Worker 的既有 WorkerInstance renew hook 执行精确 cleanup。
- cleanup 前重新验证 exact storage_source_id / object_key / size / SHA256 / task-owned prefix。
- size/hash 不匹配时标记 `CONFLICT`，拒绝删除。
- 对象不存在按幂等 `ABSENT` 完成。
- provider 删除失败记 `PENDING`，不反向把已 server-confirm 的导入任务标失败。
- FAILED/CANCELLED/BLOCKED 等未完成 Agent task 默认保留 7 天（`MC_REMOTE_MATERIAL_STAGING_RETENTION_SECONDS` 可配置）后再回收。
- orphan generation 的精确 review ref 从 task-owned `remote-results/N/upload.json` 恢复，不通过 key 推测。
- GC 每 5 分钟由 `storage` Worker heartbeat hook 节流运行，一次最多分页扫描 100 个任务并持久化 cursor。
- 不新增 timer/scheduler，不在 training-only Worker 读取存储凭据。
- GC 实现禁止 `list_objects` / prefix delete；只执行 exact `provider.delete(key)`。
- cleanup ledger 路径：`remote-material/staging-cleanup.json`。

永久验收：

- Remote Material Import `35312109805`：API / Ubuntu / Windows success。
- Task Runtime Truth `35312109707`：Ubuntu / Windows success。
- Storage Cache Governance `35312109834`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 4 — Agent storage_scan

2026-09-18，Agent `storage_scan` 已 CLOSED：

- 产品入口：素材存储配置 → 对象存储目录；只接受 OSS / S3 / MinIO，显式 `execution_mode=agent`。
- 控制面保存长期凭据，仅通过 execution-fenced broker 提供受 prefix 约束的分页 list 与短期 object GET contract。
- Agent 不接收长期对象存储密钥，不打开中央 SQLite，不依赖 NFS。
- Agent 端 provider 对 list/read 再做 durable prefix、cursor、对象数量、size、ETag、SHA256 约束。
- images / YOLO 均可在对象存储 prefix 上真实 review；YOLO 复用 `YoloImportScanner`。
- review ZIP 只保存 metadata / annotation evidence，原始图片继续留在正式对象存储，不重复上传。
- 控制面 server-confirm review 后才允许 `AWAITING_CONFIRMATION`；用户确认后 local indexer 再次验证原对象 size / ETag / SHA256 并写 MaterialRepository / AnnotationRepository。
- canonical task status 优先于 stale stage，前端、任务 API、PollRegistry 的远程状态语义一致。
- Phase 3 exact-ref GC 与正式 storage_scan 源对象完全隔离。
- classic `static/app.js` 进入永久语法 guard，Real Chrome 覆盖真实 storage_scan 提交流程。

永久验收（代码 HEAD `639cded30a6a2fed67275f19450cb70b4e0a9128`）：

- Remote Material Import `35316129031`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35316128986`：success。
- Central Node Assignment `35316128928`：success。
- Task Runtime Truth `35316128916`：success。
- Portable Deployment `35316129051`、Remote Training `35316128920`、Remote Conversion `35316129033`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote MATERIAL_IMPORT Phase 5 — COCO / Pascal VOC

2026-09-18，COCO / Pascal VOC 的远程 annotation 格式已 CLOSED，范围为 **Agent storage_scan**：

- `DetectionDatasetScanner` 只消费 brokered provider，不读取中央 SQLite/NFS，也不直接写正式项目数据。
- COCO 保留外部 category id/name，解析 images/annotations/categories 与 split；VOC 解析 object/bndbox 并为外部标签生成稳定 class id。
- 原始对象不重新打包；review archive 只携带 candidate + normalized box + split + issue + class mapping evidence。
- server-confirm 对 review schema、candidate coverage、class、normalized box、issue、prefix 再做 fail-closed 校验。
- 用户确认外部类别到平台标签映射后，local indexer 再次校验原对象 size / ETag / SHA256，并写 MaterialRepository / AnnotationRepository。
- XML DOCTYPE / ENTITY 拒绝；对象/标注文件/标注框均有明确上限。
- 产品 UI 只在“对象存储目录”Agent 模式开放 COCO/VOC；本地目录与 server_zip 不误宣称支持。
- dataset_yaml 继续只允许 YOLO。
- Integration 永久覆盖 COCO 与 VOC 从 review → mapping confirmation → local indexing → AnnotationRepository；Real Chrome 覆盖 COCO 实际提交。

永久验收（代码 HEAD `9fb67096718e5ece1b72a2acf601662fe337e1d7`）：

- Remote Material Import `35318574008`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35318574014`、Central Node Assignment `35318574002`：success。
- Task Runtime Truth `35318573876`、Storage Cache Governance `35318573935`：success。
- Portable Deployment `35318573871`、Remote Training `35318573869`、Remote Conversion `35318573929`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote MATERIAL_BATCH/CLEAN Phase 1 — Agent 清洗 / 去重

2026-09-18，Remote CLEAN 已 CLOSED，且继续保持现有唯一 durable owner：`TaskKind.MATERIAL_BATCH + operation=CLEAN`。

- 不存在并行 `TaskKind.CLEANING` handler；本地与远程共享同一 request / selection / result truth。
- local 为默认执行方式；只有显式 `execution_mode=agent` 才要求 `agent.remote`，避免中央 Materials Worker 静默抢任务。
- 后端 preflight 按真实选择范围检查 durable object evidence、OSS/S3/MinIO 存储可移植性与 online cleaning Agent；UI 只消费该 truth。
- Agent 通过 execution-fenced exact-selection broker 分页取选中素材，并按 image_id 获取短期 GET；未选素材读取直接拒绝。
- Agent 无中央 SQLite/NFS、无长期对象存储密钥，仅执行真实图像 metrics 分析。
- 控制面重新执行 `metric_issues + DurableHashIndex`，并把 verified review 提交回既有 `clean_results` 与 MaterialRepository projection。
- 用户确认/删除/保留流程不变；未确认的 durable success 继续投影为“待确认”。
- 前端新增执行位置选择、远程阶段中文状态和实际执行方式标识。
- Remote Cleaning workflow 永久覆盖 API、Ubuntu、Windows、前端 contract 与 Real Chrome。

永久验收（代码 HEAD `b41f784a3765e09a2184453e03e895a1cda0271d`）：

- Remote Cleaning `35324894972`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35324894991`：success。
- Central Node Assignment `35324894963`：success。
- Task Runtime Truth `35324895005`：success。
- Portable Deployment `35324894993`：success。
- Remote Material Import `35324894988`：success。
- Remote Training `35324895079`、Remote Conversion `35324894962`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Remote MODEL_CONVERSION Phase 2 — Rockchip RKNN

2026-09-18，Rockchip RKNN Agent conversion 已 CLOSED。

- 细粒度 capability：ONNX 继续使用 `conversion`；RKNN 使用 `conversion.rknn`。
- Node Agent 通过真实 RKNN-Toolkit2 Python import/version probe 后才上报 `conversion.rknn`，runtime truth 包含 supported_chips。
- 控制面仅把 online + agent + effective `conversion.rknn` + probe available 的节点作为 Rockchip 转换资源。
- portable Agent 当前严格支持 RK3568 / RK3576，FP16、batch=1、静态 shape；INT8 未关闭。
- RKNN 输出由节点本地 RKNN-Toolkit2 真转换，Agent 只接受唯一非空 `.rknn`。
- Agent/result transport 继续使用 execution generation、immutable PUT、size/SHA256、server-confirm fencing。
- 控制面 commit 后将 `.rknn` 写回既有 deployment job artifacts；不会产生另一套厂商产物 truth。
- 转换成功只记为 `converted_unverified`，`hardware_verified=false`；没有板端 Runtime 验证就不能升级为已验证。
- 前端已同步 RK3576，资源是否可用完全来自后端 effective capability/probe truth。
- “RK3578”不作为 RKNN target：官方 Toolkit 当前列出的是 RK3576。现场若有“3578”设备，必须先做真实 SoC 识别。

永久验收（代码 HEAD `5a02aa5ba03e94cc731bfd0e62437c57738efab1`）：

- Remote Conversion Runtime `35330889750`：control-plane / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35330889657`、Central Node Assignment `35330889375`：success。
- Task Runtime Truth `35330889784`、Portable Deployment `35330889497`：success。
- Remote Material Import `35330889535`、Remote Training `35330889384`、Remote Cleaning `35330889291`：success。
- `VERSION.txt` 仍为 `42.24.0`。

## 0. 最新关闭：Rockchip RKNN 板端 Runtime 验证协议 / 产品闭环

2026-09-18，RKNN 板端验证的软件链路已 CLOSED：

- 新增细粒度 `deployment-test.rknn` capability。
- Agent 只有真实识别 Linux arm64/aarch64 的 RK3568/RK3566 family 或 RK3576，并可导入 RKNNLite 后才会上报能力。
- heartbeat 发布 `rknn_board` runtime truth，调度要求 target chip 与节点真实 SoC 完全匹配。
- 复用现有 `DEPLOYMENT_TEST` durable task，不新增板端验证数据库/第二套任务真相。
- RKNN 模型与测试图通过 portable verified object contract 下发；Agent 不打开中央 SQLite/NFS。
- 节点真实调用 `RKNNLite.load_rknn → init_runtime → inference`，回传推理耗时、输出数量和输出 shape。
- server-confirm 前后均校验原 conversion artifact 的 size/SHA256，模型在任务期间发生变化则 fail closed。
- 只有可信板端 runtime evidence 才能把原 conversion job/manifest 改成 `hardware_verified=true`。
- 产品部署中心已增加“板端验证”入口和验证成功状态展示；Real Chrome 覆盖完整页面流。

永久软件验收（代码 HEAD `05c7b93339414ac028214fd3d046dfdf7977c0a1`）：

- Remote RKNN Board Runtime Protocol `35335720990`：API / Ubuntu / Windows / Real Chrome success。
- Remote Conversion Runtime `35335720906`：success。
- Node Agent Executor `35335720915`、Central Node Assignment `35335720909`：success。
- Task Runtime Truth `35335720969`、Portable Deployment `35335720910`：success。
- Remote Material Import `35335720921`、Remote Training `35335720913`、Remote Cleaning `35335721027`：success。
- `VERSION.txt` 仍为 `42.24.0`。

**仍然 OPEN：**

1. 真实 RK3568 / RK3576 实物设备接入后的硬件 acceptance；CI 不含真实 NPU 板卡，不能把协议测试冒充成现场实机验收。
2. RKNN INT8 calibration portable transport。
3. 如果未来需要 COCO/VOC Agent server_zip，再按真实 portable transport 单独闭环。
4. TensorRT / Sophon / Ascend 暂不推进。

## 0. 最新关闭：Rockchip RKNN INT8 calibration portable transport

2026-09-18，RKNN INT8 Agent calibration 已 CLOSED：

- Rockchip Agent 资源通过统一后端 truth 暴露 `supported_precisions=["fp16","int8"]`；前端不自行推断。
- 创建 INT8 任务前冻结 calibration snapshot，绑定 dataset/split/MaterialRepository revision 与精确 object refs。
- calibration item 必须携带稳定 object_key / size / SHA256；只允许 OSS/S3/MinIO portable 对象，控制面本地路径不进入 Agent contract。
- Agent start 时为每张冻结校准图签发短期 GET，下载后逐张校验 hash/size；snapshot/count/实际文件数不一致直接 fail closed。
- 节点本地 `deployment_worker.py` 生成 `rknn_dataset.txt`，真实交给 RKNN-Toolkit2 执行 INT8 build。
- output publication、generation fencing、server-confirm 与 deployment job artifact truth 完全复用已 CLOSED 的 RKNN FP16 链路。
- INT8 成功仍是 `converted_unverified`，必须经过真实匹配板卡 RKNNLite task 才能设置 `hardware_verified=true`。
- 产品 UI 已加入 INT8 校准数据集 / split / count，并按 resource `supported_precisions` 动态启用。
- Remote Conversion 专项永久覆盖 calibration snapshot、Agent 下载/校验、API 无残留失败以及 Real Chrome INT8 提交。

永久验收（代码 HEAD `314757c1601420640acedc074e9aeb795e8a2097`）：

- Remote Conversion Runtime `35340943761`：control-plane / Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35340943851`：success。
- Node Agent Executor `35340943850`、Central Node Assignment `35340943861`：success。
- Task Runtime Truth `35340943758`、Portable Deployment `35340943913`：success。
- Remote Material Import `35340943781`、Remote Training `35340943764`、Remote Cleaning `35340943815`：success。
- `VERSION.txt` 仍为 `42.24.0`。

**仍然 OPEN：**

1. 真实用户自有 RK3568 / RK3576 板卡现场 acceptance；CI 只证明软件协议。
2. 若现场所谓“RK3578”设备存在，必须先读取真实 SoC compatible，再决定映射，不能直接当 RK3576。
3. COCO/VOC Agent server_zip 仍未关闭。
4. TensorRT / Sophon / Ascend 暂不推进。

## 0. 最新关闭：Rockchip 实机接入软件工具链

2026-09-18，Rockchip 板端 Agent onboarding 软件链路已 CLOSED：

- `node_agent.py --doctor` 对请求 capability 做 strict fail-closed 预检；失败返回非零并输出具体 issue。
- 新增 Linux/systemd 安装器 `tools/install_rockchip_agent.sh`，安装与每次服务启动前都执行 doctor。
- Token 使用 root-owned `0600` EnvironmentFile；不进入 `ExecStart` / process argv。
- 默认板端 capability 为 `deployment-test.rknn`，不把板端节点误配置为 RKNN 转换节点。
- 服务节点 UI 增加 Rockchip 板端快捷预设、RKNN capability 中文标签、真实 SoC/RKNNLite/RKNN-Toolkit2 runtime 展示。
- 一次性 Token 弹窗提供 doctor 与 systemd 安装命令；systemd 命令不回显 Token。
- 普通 Agent/Linux/Windows 路径保持兼容。
- Real Chrome 覆盖：创建 Rockchip 板端节点 → 快捷预设 → 保存一次性 Token → doctor/systemd 命令展示。

永久验收（代码 HEAD `b8caf7753994988d5161321c2536ae75e64d3252`）：

- Service Node UI `35342366446`：Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35342366573`：API / Ubuntu / Windows / Real Chrome success。
- Remote Conversion Runtime `35342369723`、Node Agent Executor `35342369838`、Central Node Assignment `35342369780`：success。
- Remote Training `35342369831`、Remote Material Import `35342369794`：success。
- Task Runtime Truth `35342369798`、Portable Deployment `35342369765`：success。
- `VERSION.txt` 仍为 `42.24.0`。

**仍然 OPEN：**

1. 用户真实 RK3568 / RK3576 板卡的现场 hardware acceptance。
2. 若设备被销售/标注为“RK3578”，先读取真实 SoC compatible，不能直接映射为 RK3576。
3. COCO/VOC Agent server_zip 仍未关闭。
4. TensorRT / Sophon / Ascend 暂不推进。

**下一主线：Rockchip 真实板卡 acceptance。**

必须复用已 CLOSED 的 `deployment-test.rknn` durable truth。只有真实板卡 Agent ONLINE 且 effective capability 为 `deployment-test.rknn`，并成功执行目标 `.rknn` 的 RKNNLite inference 后，具体 conversion job 才允许写 `hardware_verified=true`。软件 CI 不能代替现场 NPU 验收。

## 0. 最新关闭：Remote MODEL_CONVERSION / ONNX Runtime

2026-09-18，`MODEL_CONVERSION` 已成为继 `DEPLOYMENT_TEST`、`TRAINING` 之后第三个真实跨机器 portable task kind。当前 CLOSED 范围明确为 **ONNX**；TensorRT / RKNN / Sophon / Ascend 等厂商 SDK 目标仍按节点真实环境单独实现，不能借 ONNX closure 宣称远程可用。

核心文件：

- `platform_core/node_agent_conversion_runtime.py`
- `platform_core/node_agent_executor_loop.py`
- `platform_core/remote_execution_transport.py`
- `platform_core/task_node_assignments.py`
- `deployment_worker.py`
- `node_agent.py`
- `tests/unit/test_node_agent_conversion_runtime.py`
- `tests/api/test_conversion_portable_contract.py`
- `.github/workflows/remote-conversion-runtime.yml`

当前真实链路：

```text
部署中心选择显式 mode=agent 的 ONNX 转换资源
→ 资源状态来自 ServiceNodeRegistry
→ 只有 fresh / enabled / effective conversion Agent 才 ready
→ 输入必须是 verified model asset / immutable object reference
→ 创建 MODEL_CONVERSION durable task(execution_mode=agent)
→ legacy conversion Worker 因 agent.remote capability fence 无法自抢
→ Central Scheduler 只分配给 Agent connection_mode
→ Agent claim / start 获得当前 execution generation
→ start payload 仅包含 signed object download + portable params
→ 节点本地下载源模型并校验 size/SHA256
→ 节点本地 Python + 节点本地 deployment_worker.py
→ 真实 subprocess 执行 Ultralytics ONNX export
→ deployment_worker 使用 ONNX Runtime 做真实 runtime verification
→ heartbeat / bounded logs / progress
→ cancel / lease loss / Agent shutdown：精确终止 ProcessIdentity 进程树
→ 本地 ONNX 重新计算 SHA256 + size
→ result-upload/prepare
→ generation-scoped immutable PUT
→ result-upload/confirm
→ server-side finalization fence
→ 控制面从对象存储重新下载并复核 size/SHA256
→ 写回 deploy/jobs/<task>/artifacts/model.onnx + manifest.json + job.json
→ finish(SUCCEEDED)
→ deployment center 继续使用原有产物列表/下载 truth
→ 清理 Agent execution workdir
```

关键边界：

- Agent conversion runtime 不打开中央 SQLite，不依赖 NFS，也不执行控制面的 `job_dir / worker_path / python_path`。
- 节点只使用本机 `deployment_worker.py` 和本机 Ultralytics Python。
- start 前会再次检查“当前 Agent 是否仍有对应 runner + effective capability”；如果 runner 未注册、恢复不安全或 capability 已撤销，**不会调用 start_execution**，只让 assignment lease 失效/重分配。
- Agent 启动会清理 persisted conversion ProcessIdentity；清理无法证明时 runner `ready=false`，heartbeat 动态撤销 `conversion`。
- 源模型下载严格校验 Content-Length / size / SHA256。
- 远程成功只接受 `job.status=done + runtime_verified=true + validation_status=runtime_verified + manifest runtime_verified`。
- Agent 输出必须唯一且非空的 `.onnx`；未通过 runtime verification 不允许上传成功结果。
- 输出 PUT 继续绑定 Content-Length + SHA256 metadata + no-overwrite，并按 execution generation 隔离。
- server-side conversion commit 再次下载对象并校验 hash/size，防止“对象存储成功但部署中心没有产物”的半闭环。
- 已验证 ONNX 最终落回既有部署产物目录，因此现有产物列表、下载、打包逻辑继续使用同一 truth。
- 产品不会自动把所有 ONNX 转换迁移到 Agent；只有用户显式选择 `mode=agent` 资源才走远程。
- `mode=agent` 资源没有在线 effective `conversion` 服务节点时显示不可用，创建时也会再次检查。
- portable staging 对 Agent 资源失败时 fail closed，禁止静默回退 local。
- 当前 remote conversion CLOSED 仅包含 ONNX；厂商转换目标仍保持原真实边界。

最终永久验收：

- Remote Conversion Runtime `35306100598`
  - control-plane：success
  - Ubuntu 24.04 Agent：success
  - Windows latest Agent：success
- Node Agent Executor `35306100599`
  - API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Central Node Assignment `35306100621`
  - API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Portable Deployment `35306100612`
  - production API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Remote Training Runtime `35306100615`
  - production API：success
  - Ubuntu 24.04：success
  - Windows latest：success

临时 draft PR #15 仅用于读取 PR-triggered Actions，已关闭，**未 merge**。  
当前 formal `VERSION.txt` 仍为 `42.24.0`。

**下一主线：Remote MATERIAL_IMPORT Runtime。**

目标：把素材导入节点做成第四个真实 portable task kind，优先覆盖“ZIP / 图片批量导入 → 解包/解析 → 标签格式识别/转换 → 清洗前置检查 → 上传配置的 OSS/S3/MinIO → 中央 MaterialRepository 只提交已验证 metadata/object refs”。不能让远程节点直接打开中央 `images.sqlite3` / `annotations.sqlite3`，也不能依赖共享 NFS。

## 0.1. 最新关闭：Remote TRAINING Runtime

2026-09-18，`TRAINING` 已成为继 `DEPLOYMENT_TEST` 之后第二个真实跨机器 portable task kind。  
这不是旧 `remote_train_server.py` 的 ZIP 上传旁路，也不要求远端节点访问控制面 SQLite / NFS。

核心文件：

- `platform_core/remote_training_tasks.py`
- `platform_core/remote_training_transport.py`
- `platform_core/remote_training_results.py`
- `platform_core/node_agent_training_runtime.py`
- `platform_core/node_agent_executor_loop.py`
- `platform_core/agent_execution.py`
- `node_agent.py`

当前真实链路：

```text
POST /api/v12/.../train/start(target=remote)
→ 创建目标 TRAINING(QUEUED, remote_input_state=PREPARING)
→ 创建独立 TRAINING_PREPARE durable task
→ training-prep Worker 锁定 split / snapshot
→ 生成或复用 verified portable training bundle
→ 安全 ZIP 归档 + SHA256 / size / member_count / snapshot_id
→ 上传 OSS / S3 / MinIO，并再次验证服务端对象证据
→ 首次母模型使用 allow-listed official reference；
  迭代训练强制使用最新可训练上一版本并转为 verified model asset
→ 目标 TRAINING payload 原子升级为 READY + remote_execution
→ Central Scheduler 只把 target=remote TRAINING 分给 Agent node
→ Agent claim / start，获得唯一 execution generation
→ 下载并验证 bundle / base model
→ 节点本地 Python + 节点本地 train_worker.py 启动真实 subprocess
→ heartbeat / bounded log / progress
→ cancel / lease loss / Agent shutdown：按 ProcessIdentity 精确终止进程树
→ 训练自然结束后仍先证明 DataLoader/子进程树清理完成
→ best / last 本地重新计算 SHA256 + size
→ training-models/prepare → generation-scoped immutable PUT → confirm
→ 生成 manifest-only training result bundle
→ result prepare / PUT / confirm
→ server-side finalization gate
→ verified model assets 写回 ModelArtifactService / 算法版本 truth
→ finish(SUCCEEDED / PARTIAL_SUCCESS)
→ 清理 execution workdir
```

关键边界：

- `TRAINING_PREPARE` 是独立 background Worker，不占 GPU training Worker。
- 明确 `target=remote` 的训练在 portable contract 未 READY 前既不能发给 Agent，也不能回退本机节点。
- portable bundle 解包拒绝绝对路径、`..`、反斜杠逃逸、symlink、重复成员和超出 durable evidence 的展开。
- Agent training runtime 不 import 中央 `TaskRepository`、不打开 `tasks.sqlite3`、不要求共享 NFS。
- 远程 Agent 不接受控制面 `python_path / runner_path / stored_path` 作为本机路径。
- 当前远程训练执行器为 Ultralytics；Paddle remote training 尚未宣称 CLOSED。
- success / cancel / fence / shutdown 前都要求本机进程树状态可证明；清理无法验证时 fail closed，并保留 process identity 供恢复。
- process identity 持久化不包含 Node / Assignment / Execution secret。
- Agent 当前实现能力为 `deployment-test + training`；`training` 只有在 `AgentTrainingRunner.ready` 时才进入 heartbeat 的 effective capabilities。
- 若启动恢复发现旧训练进程无法安全终止，Agent 会动态撤销 `training` capability，而不是继续领取新训练。
- 结果与模型对象均按 execution generation / immutable key 隔离；旧 generation 不能覆盖新代。
- finalization 之前必须完成 server-confirmed 模型与结果校验；Agent 自报路径不是模型 truth。
- 修复了一个真实 Agent 参数缺省问题：portable params 中缺失/显式 `None` 现在正确回退默认值，不再触发 `int(None)` 导致训练在 subprocess 启动前失败。

最终永久验收（当前实现 HEAD 的 PR-triggered validation）：

- Remote Training Runtime `35303815439`
  - Ubuntu 24.04：success
  - Windows latest：success
  - production API：success
- Node Agent Executor `35303815460`
  - Ubuntu 24.04：success
  - Windows latest：success
  - API：success
- Central Node Assignment `35303815499`
  - Ubuntu 24.04：success
  - Windows latest：success
  - API：success
- Portable Deployment `35303815438`
  - Ubuntu 24.04：success
  - Windows latest：success
  - production API：success

临时 draft PR #14 仅用于验证，已关闭，**未 merge**。

当前 formal `VERSION.txt` 仍为 `42.24.0`。

**下一主线：Remote MODEL_CONVERSION Runtime。**

现有 conversion handler 仍包含中央 `job_dir / worker_path / python_path` 等 path-bound 语义，不能直接发到远端 Agent。下一阶段应沿用已关闭的 portable execution 框架：

1. 输入模型必须来自 verified model asset / object reference。
2. 转换工具与 Python/SDK 路径由节点本地 capability/runtime 决定，禁止复制中央绝对路径。
3. Agent-side conversion subprocess 继续受 execution lease / cancel / exact process-tree fencing。
4. 转换输出先本地 hash/size，再 immutable object upload + server confirm。
5. server-confirmed conversion asset 完成后才允许 finalization。
6. Windows 可支持其真实可运行的转换；需要 NVIDIA/Linux/厂商 SDK 的目标按节点 capability 精确调度，不伪装跨平台可用。

## 1. 已关闭：服务节点控制面

已实现真实服务节点 registry + Agent heartbeat，不是页面模拟数据。

核心文件：

- `platform_core/service_nodes.py`
- `platform_core/node_agent_runtime.py`
- `node_agent.py`
- `static/modules/service-node-runtime.js`
- `static/service-node-bootstrap.mjs`
- `static/service-nodes.css`

节点支持：

- 新增 / 编辑 / 删除 / 启用 / 禁用。
- 一次性 Agent Token；数据库只保存 hash。
- Bearer Token heartbeat 鉴权。
- `ONLINE / OFFLINE / DISABLED / NEVER_CONNECTED`。
- allowed / reported / effective capabilities 分离。
- CPU、内存、磁盘、GPU、显存、温度、利用率、Torch、CUDA、Agent 进程资源。
- Worker / durable task 投影。
- Windows / Linux 跨平台 Agent 本机探测。
- `nvidia-smi` 通过 `shell=False` 调用。

用户级节点能力：

`training`、`material-import`、`cleaning`、`annotation`、`video`、`conversion`、`deployment-test`、`model-upload`。

服务节点后端 focused CI 已通过；服务节点 UI 的 frontend + Real Chrome CI 已通过。

## 2. 已关闭：中央 durable task → node assignment

核心文件：

- `platform_core/task_node_assignments.py`
- `platform_core/training_recovery_api.py`
- `task_worker.py`
- `tests/unit/test_task_node_assignments.py`
- `tests/api/test_central_scheduler_api.py`
- `.github/workflows/central-node-assignment.yml`

中央 assignment 是控制面 truth，但**不是第二套 task 状态机**。

表：

`task_node_assignments`

关键约束：

- `(task_id, generation)` 主键。
- 对 `ASSIGNED / CLAIMED` 建 partial unique index，保证一个 task 同时最多一个 active assignment。
- 调度事务使用 `BEGIN IMMEDIATE`。
- schema 初始化发生在调度事务之前，禁止在 `BEGIN IMMEDIATE` 后执行 `executescript()`，避免 SQLite 隐式提交破坏原子性。
- resolved execution config 会持久化 node、capability、device、GPU、build、runtime snapshot。
- TRAINING 优先按可用显存，其次 RAM / CPU，并对节点现有 active assignment 施加高权重负载惩罚。
- MATERIAL_BATCH 根据真实 operation 映射到 cleaning / annotation / material-import。

当前中央调度 API：

- `GET /api/v63/scheduler/assignments`
- `POST /api/v63/scheduler/allocate-next`
- `POST /api/v63/scheduler/assignments/{task_id}/release`

中央 assignment 已经从现有单一 additive runtime-router 集成点挂入，不新增第二个 `app.py` route owner。

## 3. 已关闭：旧 Worker 自抢 fencing

`task_worker.py` 已改为：

`AssignmentAwareFencedTaskRepository`

当 queued task 已存在 active central assignment 时，legacy Worker 的 `claim_next()` 必须拒绝自抢，并保留：

`CENTRAL_NODE_ASSIGNED: waiting for Agent execution on node <node_id>`

assignment 释放后，旧 Worker 可恢复正常 claim。

这保证了迁移期不会出现：

- Central Scheduler 已把任务分给 A 节点；
- 旧 Worker 又从共享 SQLite 把同一任务抢走；

这种双执行竞争。

## 4. CI 验收

Central Node Assignment permanent workflow：

`.github/workflows/central-node-assignment.yml`

验证 run：

`35288111906`

结果：

- API：success
- Ubuntu 24.04 contract：success
- Windows latest contract：success

覆盖：

- 在线 / stale / disabled / capability mismatch 节点选择。
- TRAINING 最优节点和多 GPU 选择。
- execution snapshot 持久化。
- MATERIAL_BATCH capability 映射。
- 并发 `allocate-next` 只产生一个 active assignment。
- assignment claim / lease expiry reclaim。
- release 后 generation + 1。
- central assignment 对 legacy Worker 的永久 fencing。
- schema script 不在 assignment transaction 内执行。
- Scheduler API allocate/list/release。
- `VERSION.txt == 42.24.0`。
- `git diff --check`。

用于读取 PR-triggered Actions 详情的临时草稿 PR 已关闭，未 merge `main`。

## 5. 当前明确不做的假方案

不要让远端 Agent 直接运行现有 `task_worker.py` 去访问控制面的 SQLite / NFS，然后把它称为“多机调度”。

原因：

- SQLite over NFS 不是最终可靠控制面。
- 会把 DB 文件锁、artifact 路径、进程恢复、租约边界扩散到远端节点。
- 中央控制面无法稳定成为唯一任务 truth。

因此远端执行必须通过后续 HTTP Agent executor protocol。

## 6. 已关闭：HTTP Agent Executor Control Protocol

控制面已经把“中央 assignment”安全转换成唯一真实 execution lease，不要求远端 Agent 访问中央 SQLite / NFS。

核心文件：

- `platform_core/agent_execution.py`
- `platform_core/service_nodes.py`
- `platform_core/training_recovery_api.py`
- `tests/unit/test_agent_execution.py`
- `tests/api/test_agent_executor_api.py`
- `.github/workflows/node-agent-executor.yml`

已实现协议：

```text
Task QUEUED
→ CentralTaskAllocator 选择 node
→ Agent 用 Node Token claim 自己的 assignment
→ 控制面签发 Assignment Lease Token
→ Agent start
→ 控制面在 BEGIN IMMEDIATE 内再次验证：
   Node Token / enabled / heartbeat / capability / Assignment Lease
→ 唯一 QUEUED → RUNNING
→ tasks.attempt + 1 作为 execution generation
→ 签发 Execution Lease Token
→ assignment RELEASED(reason=execution_started)
→ Agent heartbeat / log / begin-finalization / finish
→ 中央 TaskRepository 继续作为唯一任务 truth
```

三个 token / fence 的职责不可混用：

1. **Node Token**：证明请求来自哪个已登记服务节点；支持 rotate，旧 token 立即失效。
2. **Assignment Lease Token**：只允许该节点启动这一条已 claim assignment；不能重复 start。
3. **Execution Lease Token + generation**：只允许当前执行代 heartbeat / log / finalization / finish；旧 generation 永久失效。

关键生产语义：

- start 的 `QUEUED → RUNNING` 与 assignment 释放在同一个 `BEGIN IMMEDIATE` 事务。
- Node Token 在 start 事务内再次对照最新 `token_hash`，堵住“前置鉴权后刚好 rotate”的并发窗口。
- 启动前必须先证明 task payload 可读；payload 缺失/损坏时 task 仍保持 QUEUED。
- 节点 disabled 后不再 claim/start 新任务，但已有有效 execution 仍可 heartbeat/finish，避免只能等 lease 超时。
- RUNNING task 的 cancellation truth 仍由中央 TaskRepository 决定；`CANCEL_REQUESTED` 只能 finish 为 `CANCELLED`。
- `begin_finalization` 沿用现有 finalization/cancel 原子语义。
- remote log 只能追加到 task 自己的服务端 `log_ref`，单次 64 KiB 限制，并受 execution fence。
- 控制面不会接受远端 PID 作为本机进程 PID；远端进程树后续由 Agent 本机负责终止。
- start 响应明确声明：
  - `shared_sqlite_required = false`
  - `shared_nfs_required = false`
  - 大型 artifact 使用后续 object-storage transport。

控制面 API：

- `POST /api/v63/node-executor/{node_id}/assignments/claim`
- `POST /api/v63/node-executor/{node_id}/assignments/{task_id}/start`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/heartbeat`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/logs`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/begin-finalization`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/finish`

永久 CI：

`.github/workflows/node-agent-executor.yml`

验证 run：

`35288805083`

结果：

- API：success
- Ubuntu 24.04 contract：success
- Windows latest contract：success

覆盖了单次原子 start、错误/重复 assignment token、跨节点冒领、disabled 节点收尾、取消优先、finalization、remote log、lease expiry 后 generation fencing、Node Token rotate race、payload 缺失不启动、非法 generation 422、以及 VERSION / source guards。

临时 CI 草稿 PR #7 已关闭，未 merge。

## 7. 已关闭：Remote Portability Gate + Production Runtime Mount

为防止“中央绝对路径任务被误发到远程 Agent”，中央调度现在区分：

- `connection_mode=local`：允许现有 legacy/path-bound task，适用于控制面与 Worker 共机或明确共享本地运行环境。
- `connection_mode=agent`：只有任务显式携带版本化 `remote_execution` portable contract 才能成为调度候选。

当前 contract：

```json
{
  "version": 1,
  "task_kind": "<TaskKind.value>",
  "transport": "object-storage-v1 | agent-artifact-v1"
}
```

关键约束：

- 不根据旧 payload 中的路径“猜测”任务是否可远程执行；无 contract 一律 fail closed。
- contract 的 `version`、`task_kind`、`transport` 必须全部匹配。
- Scheduler 的 `resolved_execution_config.remote_execution` 只保存白名单字段，不复制 signed URL、凭据、中央绝对路径或任意嵌套数据。
- legacy task 在只有 agent 节点时保持 `QUEUED`，不会制造一个必失败的远程 assignment。
- local 节点仍保持旧任务兼容能力。
- HTTP Agent executor 测试任务已经显式使用 portable contract，避免测试绕过真实生产语义。

Portability gate 验收：

- Central Node Assignment run `35290891091`：API / Ubuntu / Windows 全绿。
- Node Agent Executor run `35290891208`：API / Ubuntu / Windows 全绿。

同时修复了一个实际生产挂载缺口：此前 v62/v63 runtime 子路由只在 focused test 中直接实例化，生产 `app.py` 没有挂载组合 router。现在生产 app 只挂载一次：

```python
app.include_router(training_recovery_router(
    get_project, shared_task_repository, shared_task_artifacts,
))
```

由 `platform_core/training_recovery_api.py` 继续单一拥有：

- training recovery
- training material picker
- service nodes
- central scheduler
- node executor

新增 AST 永久契约，禁止漏挂载、重复挂载或把 v63 子路由重新散落到 `app.py`。

Production mount 验收：

- Central Node Assignment run `35291195275`：API / Ubuntu / Windows 全绿。
- Node Agent Executor run `35291195262`：API / Ubuntu / Windows 全绿。
- 临时 CI PR #9 / #10 均已关闭，未 merge。

## 8. 已关闭：Portable Deployment Transport

部署测试已经成为第一个具备真实 portable transport contract 的 task kind。

当前 durable task 只保存对象存储引用和完整性证据，不保存临时签名 URL：

- 测试图片：`storage_source_id / object_key / sha256 / size_bytes / content_type`
- 项目模型：复用统一 `ModelArtifactService` 的 OSS / S3 / MinIO 资产。
- 官方模型：仅保存 allow-listed model reference。
- 输出：只保存 durable storage ref；Agent start 不再收到中央 `input_path / model_path / runner_path / python_path`。

`start` 仅为输入/模型生成短期 GET；输出使用 `prepare-after-local-hash-v1`，不在 start 阶段提前签 PUT。

验收：

- Portable Deployment run `35292400487`：production API / Ubuntu / Windows 全绿。
- 同批 Agent run `35292068629`、Central run `35292068610` 全绿。
- 临时 CI PR #11 已关闭，未 merge。

## 9. 已关闭：Hash-bound Remote Result Publication

远程部署测试的结果发布已经进入 execution fencing，不再接受“Agent 上传一个文件后直接说成功”。

真实链路：

```text
Agent 本地推理完成
→ Agent 本地计算 output SHA256 + size
→ POST result-upload/prepare
→ 控制面验证 Node Token + Execution Lease + generation
→ 控制面生成 generation-scoped object key
→ 签发绑定 Content-Length + SHA256 metadata + 禁止覆盖的短期 PUT
→ Agent PUT
→ POST result-upload/confirm
→ 控制面 stat 对象并核对 size + SHA256 metadata
→ durable finalization transaction 原子决定 cancellation 或 commit
→ 写 remote-results/<generation>/result.json
→ /finish(SUCCEEDED) 强制使用服务端 confirmed result_ref
```

关键 fencing：

- 实际结果 key 为 `.../output/generation-N/result.jpg`，旧 generation 的 signed PUT 不会占用新 generation 的对象。
- S3 / MinIO 签名绑定 `Content-Type`、`Content-Length`、`x-amz-meta-sha256`、`If-None-Match: *`。
- OSS 签名绑定 `Content-Type`、`Content-Length`、`x-oss-meta-sha256`、`x-oss-forbid-overwrite: true`。
- signed PUT URL 只返回给当前 Agent，不写 Scheduler truth，也不写 durable upload state。
- `remote-results/<generation>/upload.json` 只保存 hash / size / storage ref / node / generation。
- 已上传但 confirm 前断线时，只要对象现有 size/hash 完全一致，prepare 可幂等恢复；冲突对象 fail closed。
- confirm 时对象缺少 SHA256 metadata、size 不符、hash 不符均禁止成功。
- confirm 在对象验证后复用 `begin_finalization()` 的数据库事务作为 commit gate，cancel 与 result publication 不能同时获胜。
- portable deployment 未 confirm 前禁止 `begin-finalization`，也禁止 `finish(SUCCEEDED/PARTIAL_SUCCESS)`。
- Agent 自报的 `result_ref` 不可信；成功 finish 强制使用当前 generation 的服务端 confirmed result_ref。

新增控制面 API：

- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/result-upload/prepare`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/result-upload/confirm`

验收：

- Node Agent Executor run `35295427105`：API / Ubuntu / Windows 全绿。
- Portable Deployment run `35295427110`：production API / Ubuntu / Windows 全绿。
- Central Node Assignment run `35295427100`：API / Ubuntu / Windows 全绿。
- 临时 CI PR #12 已关闭，未 merge。

## 10. 已关闭：Agent-side Real Deployment Runtime

远程部署测试现在已经真正由 `node_agent.py` 在服务节点本机执行，不再只是控制面协议或模拟 handler。

核心文件：

- `platform_core/node_agent_executor_runtime.py`
- `platform_core/node_agent_deployment_runtime.py`
- `platform_core/node_agent_executor_loop.py`
- `node_agent.py`
- `tests/unit/test_node_agent_deployment_runtime.py`
- `tests/unit/test_node_agent_executor_loop.py`
- `tests/unit/test_node_agent_entrypoint.py`

真实链路：

```text
Node Agent heartbeat ONLINE
→ 单并发 executor loop claim assignment
→ /start 获取 Execution Lease + sanitized portable payload
→ task-local workdir
→ 下载输入 / 项目模型并校验 size + SHA256
→ 官方模型仅允许 allow-list reference
→ 使用节点本地 Python + 节点本地 runner
→ 启动真实 subprocess
→ ExecutionLeaseMonitor 周期 heartbeat / cancel / fence
→ cancel / lease 丢失 / Agent shutdown 时按 ProcessIdentity 精确终止进程树
→ 本地结果计算 SHA256 + size
→ result-upload/prepare
→ generation-scoped PUT
→ result-upload/confirm
→ begin-finalization
→ finish(SUCCEEDED)
→ 清理 task-local workdir
```

关键边界：

- Agent runtime / executor loop 不 import 中央 `TaskRepository`、不打开 `tasks.sqlite3`、不依赖共享 NFS。
- `node_agent.py` 只向控制面上报当前 build **真实可执行** 的远程能力；当前只开放 `deployment-test`，不会虚报 training / conversion。
- executor 只有在首次 heartbeat 成功后才启动；Agent 尚未被控制面确认在线时不会抢任务。
- 当前 executor 单并发，避免同一 Agent build 在资源隔离尚未扩展前并行抢多个部署测试。
- 输入/模型下载逐块验证长度和 SHA256；临时文件完成验证后才原子替换。
- 节点 runner 必须位于 Agent runtime root，禁止把控制面 `runner_path/python_path` 当成远端路径。
- lease/cancel/shutdown 都会终止精确子进程树；stale generation 不发布终态。
- 成功/失败/取消后均停止 lease monitor 并清理执行工作目录。

永久验收：

- Node Agent Executor run `35297453169`
  - API：success
  - Ubuntu 24.04：success
  - Windows latest：success
- Portable Deployment run `35297453136`
  - production API：success
  - Ubuntu 24.04：success
  - Windows latest：success

本轮补充永久 guard 后，`node_agent.py`、`node_agent_executor_loop.py` 以及入口/单并发测试均已进入两套永久 workflow。

**下一主线：Remote TRAINING Runtime。**

目标不是让远端 Agent 访问中央 SQLite/NFS，而是继续沿用当前已验证的控制面与对象存储协议：

1. 将训练输入变成 portable dataset/bundle object contract。
2. Agent 节点下载并完整校验 dataset/model base。
3. 节点本地调用真实 Ultralytics/Paddle training runtime。
4. progress / metrics / logs 继续回到中央 durable task truth。
5. cancel / lease loss 精确终止训练进程树并释放 GPU/CPU/RAM/临时文件。
6. best/last 模型通过统一 `ModelArtifactService` / object storage 回传并验证。
7. 只有 server-confirmed 模型资产完成后才允许训练任务 finalization。

