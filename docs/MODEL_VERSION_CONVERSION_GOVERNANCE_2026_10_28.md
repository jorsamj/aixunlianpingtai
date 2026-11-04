# 模型版本转换模块专项（2026-10-28）

## 2026-11-04｜42.24.518 转换体验及真实样本数值比较接续

新增历史列表单行化、创建配置摘要、单层弹窗转换流，以及「场景算法实测 → 转换一致性」入口。数值任务复用 `MODEL_CONVERSION` 现有持久 Worker，逐张核验 PT/ONNX 原始张量。若本地具备算能官方 TPU-MLIR 运行环境可选做 BMODEL 离线模拟数值比较，缺 SDK/不兼容会保留未核验状态；**没有新增实机验证，也没有证明正式 BM1688 误报已消除**。实现和验收边界见 [42.24.518 专项任务与进度](CONVERSION_NUMERIC_VERIFICATION_AND_UI_2026_11_04.md)。

## 2026-11-02｜42.24.496 精确 SHA CI 红灯闭环（控制平面测试证据更新）

- 495 已通过 GitHub 仓库接口非强制快进推送，准确 SHA `ab12fbf0c137163fdc9ac6ec9d696ed8748311d4`，推送后本地和远端 HEAD/文件树一致。本次基于该 SHA 继续，版本正常递增，不修改生产。
- 495 `Remote Conversion Runtime` Push 作业 `41406195292` 的 `control-plane` 实测 **377 passed / 3 failed**，三个红项均为原 `tests/api/test_sophon_remote_admission.py` 旧隔离数据把资源声明成 ready 但没有 SDK `last_checked_at`，并期待正式创建再执行完整远程 `_detect_remote_deploy_resource`。新业务规则正确地先以 `not_checked` 409 拒绝，故旧测试无法抵达其原断言。
- 496 仅修正原测试的真实证据前置条件：显式提供已检测时间、把在线性检查隔离为新的 `_remote_conversion_resource_online`，并强断言正式准入**不得再次调用完整远程 SDK 扫描**。保留未选/不支持芯片返回400的负例与有效 BM1688 创建的既有作业记录、远端密钥引用、精度和参数断言。原服务端与页面检测逻辑无第二轮改写。按照 `.github/workflows/remote-conversion-runtime.yml` 的 `control-plane` 完整 Python 清单在本地隔离环境 **380/380 通过**，准确新 SHA GitHub Actions 仍须单独核验，不可借 495 的 PR/其他作业冒充全部 CI 成功。

## 2026-11-02｜42.24.495 P0 SDK 能力证据与可恢复检测（本地验收；生产 SDK/板端待核）

**准确基线**：唯一长期分支 `feature/external-algorithm-publishing`，接续远端 `c94cf17c7e9f1a9204141f0f5f23d673d08725a6` / VERSION `42.24.494`，克隆时工作区干净；该 SHA GitHub 可查询的 PR 工作流 20/20 success，不能替代本提交的 CI。生产最后已知版本 485，未登录服务器核验；本轮不部署、不改生产资源/数据库/任务/权重/OSS。正式新 SHA/Actions 与部署建议必须按本次最终交付回执单独核验。

### 源码根因和原有正确机制

1. `conversion_resource_detection.observe` 把 SDK 能力和运行时可达性混为 `TTL_SECONDS=300`，5分钟必返回 `expired`；`compute_platform_catalog.resolve_chip_capability` 因此拒绝，而 `refreshConvertContract428` 的只读 `/deploy/resolve` 不会启动 SDK 检测。用户多次点击校验仍只得到同一过期结果。
2. 原 `detect` 的 `checking` 是进程局部 `threading.Event`。虽已有资源级 `FileLock`、资源 JSON 原子写、配置 CAS 和 30 秒前端截止，但跨 Web Worker 读取、重启遗留、HTTP超时后恢复没有同一持久进行态。
3. 正式 `/deploy/jobs` 又执行 `_detect_local/_detect_remote/_detect_agent`，与预览依据不一致，远程 `/api/deploy/health` 还会执行完整 SDK 工具探测。SDK 可用状态和在线状态需分开核验。
4. 原资源 `PUT` 仅改名称/备注也刷新 `config_revision`、清空 SDK 证据；自动探测写入的若干衍生工具字段还可能被配置哈希误当用户配置。原厂商动态字典、未适配 Adapter 拒绝、正式任务 request_id 幂等、版本源 fence、Sophon/RKNN 真实芯片/精度约束均予保留。

### 修改后的单一状态与时序

- **能力快照**：仍由原 `deploy_resources.json` 资源行持久化，`detection_config_key` 与 `config_revision` 锚定 SDK 关键配置，已配置本地 Python/工具根目录/环境脚本以轻量 `stat` 指纹识别路径变化；`detection_environment_fingerprint` 与 `last_checked_at` 同步保存。**5分钟后仍可用**，七天为保守的定期复核边界（`604800s`），不是心跳 TTL，也绝不单靠放大 TTL 当作证据。SDK 原地安装包变更未触及上述配置路径时可能在复核前不可见，真实编译 Worker 仍独立验证，作为已知剩余风险。
- **资源检测**：原同步 `POST /deploy/resources/{id}/detect` 保持兼容；新增有界 `POST /deploy/resources/{id}/detect/start` 和只读 `GET /deploy/resources/{id}/detect/status`。启动把 `detection_run:{id,state,started_at,config_key,owner_pid/started_at/host}` 原子记录于**同一资源行**，后台复用原 detector 和跨进程资源 FileLock，完成后 CAS 按配置与 run ID 回写并清掉 checking。进程消失/PID 复用时尽快标记 `expired`，跨主机或未能核验所有权时最迟在10分钟运行租约后可再检测；旧 run 永不覆盖新配置。没有第二份 SDK 结果库。Web 进程中断后可能需要用户手动重新启动检测，不能宣称已实现跨重启任务继续执行。
- **前端**：仅用户显式点「检测当前资源」才 POST start；已在检测的资源无需再 POST，打开弹窗从既有资源 GET 恢复并只读轮询 status。每次查询用原30秒 deadline；最多等待120秒，之后提示后台仍可能执行，可关闭/刷新，不将 HTTP 超时判成芯片不支持。每次状态变更废弃旧 resolve 响应和签名缓存，当前 form/project/ticket 的结果才渲染；关闭只废弃 UI 请求，不杀服务端共享扫描。检测完成自动对当前厂商/资源/芯片重新 resolve；真正不可用、失败、过期、未适配仍禁止提交。
- **正式提交**：所有非内置转换资源（Sophon/RKNN/Atlas/TensorRT/自定义 ONNX、Paddle/Agent/远程）统一先检查 `observe` 的有效能力证据；芯片型资源再用后端 `resolve_conversion_contract` 进行与预览一致的芯片/精度权威准入，内置 ONNX/Paddle 仍依其原环境实检。正式 POST 不再重复执行本地/远程完整 SDK 探测；本地轻量检查配置路径、Agent 实时确认授权节点、远程执行带鉴权的无 SDK 扫描 `/api/deploy/ping` 检查在线及配置/服务版本。新的远程服务 `/api/deploy/health` 也回传 `config_revision`；旧远程版本返回404时一次性回退既有 `/health`（有真实扫描开销，后续升级远程服务可消除）。远程链接失败为503、配置变化409，不伪装为 SDK 不兼容。运行时实际编译及硬件验收仍由既有 Worker/任务机制执行，正式 request_id 幂等不变。
- **诊断**：原 `resolve.timings_ms` 保留 source/resource/contract/total；资源的 `detection_timings_ms` 记录 SDK/远程/Agent 探测和跨进程锁等待真实耗时（绝不记录命令、凭据、模型或正式图片）。异步时服务器连接耗时与 SDK 计算时间不能相加或混称。存储持久化的单独耗时尚未形成端到端完整 P95 仪表盘。

### 本地验证及部署边界

- Python 原 SDK 状态、动态目录、正式创建、异步单飞/失败/配置变更 CAS/死亡进程及**两个独立 Web Worker 子进程**、远程 ping/密钥脱敏、Sophon/RKNN/TensorRT/ONNX/Paddle 准入与转换任务集成，完整相关集合 **182 通过、1 deselected**。仅排除先前在本地隔离版 TestClient 中无法结束的既有 `test_missing_job_record_http`，并未宣称全库 Python 通过；上一个扩大回归子集已独立 **142/142**。跨进程子测试须在允许创建 Worker 的权限下运行；容器受限模式不能据此判断业务失败。完整前端 Node **1491/1491**（包含 SDK 轮询不重复 resolve、动态 age 不重发）。
- Chrome `model-and-conversion.spec.mjs` 初轮 **15/18**；将旧 `/detect` 夹具接至 `/detect/start` 后通过，将审核页故意被紧凑 CSS 隐藏的说明改为内容验证、旧版不存在的“配置部署资源”按钮改为实际“检测当前资源/刷新资源”入口，真实 Chrome 整份 **18/18 全绿**。这是隔离 UI/HTTP 证据，不等于真实 SDK、编译或板端通过。准确新 SHA GitHub Actions 仍须推送后核验。无真实 A800 算能工具链、RKNN、Atlas、TensorRT、Agent/远程、实际目标板或生产浏览器代理测量，不能说现场故障已闭环。
- **暂不直接建议生产部署**：先验证远程服务 ping 升级/旧版回退、至少一种本地及远程芯片检测的实际失败/超时/恢复、并行多 Web Worker 与进程重启、正式任务创建的 SDK/设备真实准入；最后核对准确提交的 CI 再逐步灰度。绝不修改现有正式资源、任务与模型权重以做上述验证。

## 2026-11-02｜42.24.490 显式 SDK 检测网络截止，禁止弹窗无限等待

接 489 `516ff3955c075dcbfa682542e78754dcf122df89`（该 SHA 完整 CI 在本次接续时尚未全部完成）；生产保持 485。不改变 488 SDK 后端/资源持久身份/5分钟证据有效期或 489 过期资源可选重检语义。

- 最后入口复核：`refreshVersionConversionResources428(true)` 原主动检测 POST 直接调用 `api`，没有 `withRequestDeadline`，网络/TCP/TLS/Agent 挂起可能让 `conversionResourcesLoading416` 不结束。旧 `/deploy/resolve` 已有 30秒截止，两条请求生命周期不一致，不能简单宣称已完全防无限 Loading。
- 在原 `conversionRead428` 增可选操作名，原读/resolve 默认语义不变；显式 `/deploy/resources/{id}/detect` 使用**同一个已存在的 30秒 AbortController 截止**与准确的“转换资源检测”标签。超时进入原 `catch/finally`，释放 Loading、明确反馈、保留尚有效的其他资源；可按原“刷新资源”查看 SDK 检测是否已在服务端完成，或明确再次检测。前端 timeout 不是 SDK 不支持证据，后端同资源 FileLock/CAS 去重仍生效；不增加30秒期限。
- 原资源前端自动化新增“检测 POST 截止→可再次检测，不无限等待”；专项 31/31、完整 Node **1472/1472 passed**。准确490 GitHub Actions/真实 SDK 与生产网络 P95 待独立验收。无数据库结构变更、不触碰 Worker/正式任务、权重、OSS。

## 2026-11-02｜42.24.489 过期/待检资源可主动检测（488 后续交互闭环）

准确远端 488 `eb84b27fd2dc550821800f066219bcd7947b2804`，原 **Remote Conversion Runtime Push 4/4 jobs success**（Ubuntu/Windows Agent、Control Plane、真实 Chrome）；完整同 SHA Actions 49 条仍在进行时，不能借用其结果认定 489。继续唯一开发分支，生产仍 485 未部署。

- 发现剩余真问题：488 转换弹窗资源下拉仅列 `ready`，首开时若该目标只有检测已过期/待检测/检测失败的已配置资源，`检测当前资源` 按钮无法选中它，用户即使想重新检测也会走普通读取，无法在原弹窗恢复。网络或 SDK 过期与芯片不支持无关。
- 原生 `refreshConvertResource428` 将 **所有匹配当前目标的已配置资源** 作为可选检测对象、优先选仍有效的 ready 资源，旧选择不静默跳转；非 ready 资源带准确检测状态。`ready` 数组仍单独用于正式创建门禁；后端 `resolve` 和正式 `POST` 的有效能力校验一律不放松。检测后保留用户源版本、目标芯片和有效参数。
- 原前端自动化补过期显式重检→恢复可转换、断言提交在重检前锁定，更新旧“离线不可见”假设为“离线可选检测但不可提交”。`static/app.js` 缓存标记升至 489；无 Python/SQLite/资源 schema/SDK/Worker/OSS 修改。隔离资源专项 **30/30**、完整 Node **1471/1471** 通过；489 精确 SHA Actions/Chrome 待独立核对。原 488 单版本 SQLite 0/2000 历史文件对照和真实性能限制仍在以下章节，不改变生产口径。

## 2026-11-02｜42.24.488 多厂商转换状态、定向解析与多进程检测（开发中，CI/生产待独立验收）

本轮承接 42.24.487（远端开发分支 SHA `377e95b3319eca0f350f8d014843a084f98f1a00`，上一轮已确认 39/39 Actions 绿色）；生产已知 42.24.485，不涉及部署。唯一允许开发分支 `feature/external-algorithm-publishing`，不 merge/tag/release/force push，不修改正式数据库、权重、Task、OSS、硬件或畅联云发布记录。下述测试/提交回执在本批完成后按准确 488 SHA 更新，不能借用 487 的 CI。

### 已确认的源码缺陷与非缺陷

- **真实重复扫描**：旧 `app.py::_resolve_deploy_source` 不辨源身份，一律 `_deploy_source_models`，先 `list_models_internal` 扫所有 `jobs/*/job.json`、模型目录，再 `list_algorithms_internal` 读所有算法和版本；旧 `_conversion_contract_for_source` 为明确版本再读一次全算法列表，创建路径又读取。当前 `AlgorithmSqlStore.read_one(algorithm_id)` 已有可信单算法 SQL API，复用而不新建仓储。
- **初始芯片状态不实**：旧 `static/app.js::applyConversionChipOptions428` 对全部 enabled 芯片写死“待校验”；其余 `applyConversionContract428` 已从后端 `chip_options` 覆盖，但网络失败时旧文本容易误导。目录已有 `conversion_catalog_metadata` 的每资源证据；需要对资源 ID、SDK 检测时间/状态一致性做精确绑定，不能让另一个资源的能力代表当前选择。
- **多进程竞争**：原 `conversion_resource_detection.detect` 只在单 Web 进程内用线程锁/缓存合并显式检测，资源 JSON 由普通写入覆盖，原更新 `updated_at` 仅秒级，且检测的配置检查和写回不在同一持久临界区。多个 Web Worker 可重复检测或晚写覆盖新的资源配置。
- **已有机制不重复建设**：原动态厂商/芯片目录及 implemented Adapter、通用 ONNX/Paddle/TensorRT 与 Sophon/RKNN/Atlas、300 秒 TTL、选中资源主动检测、同配置浏览器 resolve 去重/取消/失败手动重试、POST 正式创建的重检/幂等、编译和板端验证分离已经存在。寒武纪等无 Adapter 保留 `not_adapted`，不构造假 SDK 成功。
- **网络事实**：用户某次 Chrome `/deploy/resolve` 在 `Initial connection` 约 30.02 秒，未见对应 Web 日志；服务端健康/无鉴权请求较快不证明带真实参数 resolve 的执行时间。浏览器代理/TCP/TLS/NAT/反向代理与应用 SQL 等待须分段归因，不能把 30 秒连接阶段当作 Python 计算缺陷；保留有界超时，不抬高到 60/120 秒。

### 本批原 Owner 内的变化

1. 明确 `version::<algorithm_id>::<version_id>` 源只读 `AlgorithmSqlStore.read_one`，保留原当前版本投影与缺失历史报告的**单版本**按需读取，输出仍为既有 source/meta/trace 格式；请求内部临时版本快照供合同和任务创建复用，持久 `source_meta` 不包含私有快照。旧 `model::` 自由模型来源保留原血缘扫描以免丢失历史 job 关联；这是尚未进一步优化的兼容路径。
2. `compute_platform_catalog` 使用唯一后端芯片状态文案，识别当前资源检测中/过期/失败；目录投影返回逐资源 status_label/检测时间/state，前端只在 resource_id、检测时间、检测状态同时匹配时显示该能力。匹配不到显示“等待兼容性解析”，不假称可用/不可用；未适配、停用、未选资源与显式 SDK 状态有独立说明。正式创建按钮仍以最新服务端 ready 合同为准，过期资源不得作为 ready 资源提交。
3. 复用现有 `conversion_resource_detection` 与持久部署资源文件；同 resource_id 的主动检测增加跨进程 FileLock，进锁后重新核对配置/已落盘检测时间，跨进程重复请求复用真实持久观察；写入前以文件锁读回核对配置身份。SDK 探测抛错会把已存在的失败观察持久化，不能让旧 ready 继续冒充有效 SDK；配置更新生成 `config_revision`（旧行兼容），清除过期探测回执，变更期间晚检测 fail-closed 409；资源 JSON 原子替换，配置/删除和旧版内联密钥迁移串行化；不同资源检测不互锁。单个显式批量本机自动检测保留原 Owner，回写仅覆盖未被编辑/重新检测的行，响应亦只反馈实际接受的最新记录。
4. 既有 opt-in 性能诊断白名单增加精确 `/api/v39/projects/{id}/deploy/resolve` POST 和 `/api/v39/deploy/catalog` GET；原 `_resolve_deploy_source`/资源读取/合同解析记录有限固定阶段标量，算法 SQL 仓储在显式诊断时复用原计时连接，不记录 SQL、ID、参数、Token 或密钥。仍区分浏览器 TCP/TLS 与服务端请求，`sqlite_lock_wait_ms` 无直接测量时保持 null。

### 验收与未完成项（按实际回执更新）

- 新增和扩展原动态目录 API、资源检测单测、原生 JS 资源/芯片回归；保留现有多厂商合同及资源资格。真实 SDK/Agent/板端检测不在隔离开发环境执行，不能用 synthetic fixture 冒充能力。
- 隔离 Python 转换合同/资源/幂等/模型/多厂商等 **271 passed、1 deselected**；完整前端原生 JS **1470/1470 passed**（包含在正常子进程权限下运行的 Uppy）。部分旧 `TestClient` 复合 HTTP/性能诊断用例在当前隔离环境挂起，须核对准确 SHA GitHub CI，不得把中断测试算作通过；独立硬件及真实 Chrome/所有 Actions 待提交后验收。SDK 异常持久化、批量检测并发编辑和同资源重复检测、网络连接与 SDK 失败区分均有新回归。
- 隔离性能对照（Python 3.12、临时 SQLite `AlgorithmSqlStore` 的真实定向 `read_one`、本地版本合同、相同资源证据；每组40次温调用）：同一版本、项目下 **0 个**无关 `job.json` 时总延迟近似 P95 **3.827ms**、P50 **1.590ms**；增加 **2,000 个**无关文件后 P95 **2.871ms**、P50 **1.877ms**。该对照仅证明本机定向解析不随着这些历史文件明显增长；不是旧版本全扫描的完整对照、真实21k数据/冷启动、WAN 或生产指标，也不能证明通用 `model::` 入口已经优化。
- P0 **仍需要授权的只读现场验收**：浏览器 HAR（连接/代理/TTFB）、同 request_id 的 Server-Timing、真实 21k/历史任务规模 SQL/P95、两 Web Worker 连续检测/资源编辑、多目标 SDK/Agent 与芯片真实工具链。性能方向目标：温能力 P95≤200ms、单模型 resolve P95≤500ms、必要弹窗 P95≤2s；这些均非已达标结论。
- **安全/部署**：无数据库 schema 迁移，现有资源 JSON 仅在用户显式新增/编辑/检测时写入可选 `config_revision` 和新版状态字段；旧检测读取和项目数据不用回填。生产 485→488 必须另外核部署差异、无活动任务、备份、明确授权和回滚，不能自动升级生产。

本文件为附件b7318d04本轮唯一需求/实现/验收依据；不替代既有RGB/BGR颜色适配与SDK真实性专项。基线2c5311c6 / VERSION42.24.397已fetch一致，原负样本任务最终CI收尾独立提交92203c8c，原未提交训练模板/5944与其他工作树保留。不开生产、不删模型/缓存，不扩到训练配置或素材管理。

## 需求与审计

目标：正式转换弹窗立即展示；目录/资源/历史独立截止、错误及重试；读取已有检测与主动SDK检测解耦；最终创建仍权威核验。原卡片/任务/幂等/队列/Worker/ModelArtifact/下载/血缘继续使用；增加明确的详情与状态/设备/芯片/精度/CSC/日期筛选和有界分页。

已有：RGB/BGR ONNX Gather入口适配及数值校验、原SDK检测、厂商/芯片动态目录、目标专属参数、原任务快照/manifest、单资源手动检测、原PollRegistry只轮询活动任务。不得把RGB/BGR或训练augmentation当YUV CSC。

真实缺口：openNewConvertCore416在资源+历史+目录Promise.all后才打开；历史窗口同样等待网络。打开资源force读取、resolve反复主动检测，远程单次timeout12秒；catalog/resolve缺局部截止与精确Modal失效。高级值跨目标共用；资源检测失败可能静默选另一个资源。版本历史先扫描全项目job.json再截100，逐条durable查询，老版本可能被截断；缓存无TTL。四CSC/device_default/none在转换端均未实现。

## 设计与边界

沿原Owner渐进加载，分源状态/重试保留编辑；精确项目/源版本/表单/config epoch、局部Abort/截止。复用ResourceCache按选中资源配置指纹缓存/合并检测，转换表单使用只读资源查询，不开启全节点SDK检测；显式检测与最终创建校验分开。历史只维护可重建派生投影/按需分页，不建立第二套转换任务真相。

CSC仅处理明确原始8位Y'CbCr输入NV12/I420/平面YUV444，四预设对应601 Kr=.299/Kb=.114或709 Kr=.2126/Kb=.0722，Limited为Y16/219、C128/224，Full为Y0/255、C128/255；输出实际RGB/BGR uint8，限定nearest chroma与量化规则。不是RGB编码/同逆变换、HSV或改文件metadata。none不适配；device_default不猜实际矩阵；历史缺失显示历史未记录。

现平台不能控制外部业务BMCV/VPP调用，四预设先明确为contract_only：生成参数合同/可执行参考解码器/说明，applied=false、device_observed=unknown、board NOT VERIFIED。需显式接受推理端配合；要求模型产物独立完成而平台不支持时拒绝。禁止将编译成功视作板端验证。保留原通道适配，分别记录requested CSC、参考数值验证、真实执行位置和板端证据。未知Adapter不给“四模式已支持”承诺。

官方依据：[BM1688 BMCV接口](https://doc.sophgo.com/bm1688_sdk-docs/v1.8/docs_latest_release/docs/bmcv/bmcv_demo/bmcv_api/bmcv_image_vpp_basic.html)、[ITU-R BT.709](https://www.itu.int/dms_pubrec/itu-r/rec/bt/r-rec-bt.709-6-201506-i!!pdf-e.pdf)。文档中的默认值不推广为所有设备/摄像头实测。

## 阶段与实际进度

|阶段|状态|实际实现|验收证据|
|---|---|---|---|
|A 审计/最小方案|已验收|原Owner调用链、颜色适配、SDK/历史瓶颈及边界已确认|代码审计及下述受控对比|
|B 渐进加载/检测|已验收|正式表单立即展示，源/目录/资源独立状态和重试；单资源检测、300秒TTL及同配置并发合并；预览不探测|资源合同、API及Chrome；最终代码f2af4af3的41/115 CI成功|
|C CSC统一合同/产物|已验收|四预设、none/default、显式接受外部预处理；原本地/远程/Agent任务传递、Worker、manifest、参考包和下载接通|真实微型ONNX Worker与参考CLI、远程真实性/提交失败回滚；板端未验证|
|D 记录卡片/筛选/历史性能|已验收|详情折叠、6种服务端筛选、20条分页、全版本总数、增量文件投影及仅活动任务overlay|1000条隔离记录、历史API及Chrome分页/展开保持|
|E 必要自测/截图/CI|已验收|本地必要检查已通过，VERSION42.24.398；最终代码f2af4af3准确CI通过；文档自身按其提交Checks独立核验|不借用03728393或其他提交绿色|

## 实现与选择

- 前端仍为原转换表单和Modal Owner、Page/表单epoch、原API与PollRegistry。加载失败保持表单，独立重试；资源失败不偷偷切换另一资源。厂商/芯片响应、resolve均有局部截止/取消/迟到隔离。高级参数按目标保存，已编辑输入尺寸、精度、RGB/BGR不被异步默认值覆盖。
- GET resources使用`detect_missing=false`，catalog只读观察；原默认接口兼容。资源状态包含检测时间、TTL及可用/检测中/未检测/过期/不可用/失败。手动检测只运行选中资源；配置指纹变化使结果失效，保存前校验updated_at防止晚响应覆盖新配置。原创建接口和Worker的SDK/模型/硬件权威检查保留，缓存不代替最终校验。resolve返回分段timings_ms，不记录凭据。
- 版本历史复用原job.json和durable Task，不建新表。最多16项目派生投影，目录元数据TTL不超过1秒，文件签名变化才重读JSON；只对活动任务查真实状态。首次冷读仍需读取现有记录；不可读记录明确complete=false，不伪装全量成功。投影只保留源身份，不保留冻结GT/Snapshot大正文。
- 原通用v39任务列表合同（最后100条）保留，本轮优化的是v42版本历史视图；不能声称通用列表已全面优化。旧source_meta/source_id记录与日期结束日兼容。
- 已有ONNX复用与原验证保留；新增的只是预览shape的有界文件签名缓存，最终创建仍重新读取。未新增跨任务PT导出缓存：现有export工具版本与完整配置身份不足以证明安全复用，避免错用中间成果。未关闭原源SHA、ONNX/ORT、SDK和产物验证。
- CSC派生合同由后端从请求重算，不能伪造csc_contract。远程Sophon必须与冻结请求、manifest和可信参考包逐字节哈希相符。Agent结果由服务端原提交Owner重建参考包；SQLite/job持久提交失败会回滚本次新增或覆盖的两个参考文件。原模型/审计不动。
- 辅助产物为`csc_deployment_contract.json`和`csc_deployment_reference.zip`；ZIP含参考Python、README及合同，文件哈希可追溯。通过原登记ZIP下载，不扩宽.py/.md业务文件权限，不执行远端提供的未知Python。

### CSC能力与数学约定

Sophon/RKNN/Ascend/TensorRT/ONNX当前均仅具备**生成外部部署约定和可执行参考解码器**的能力，四模式须明确选择原始YUV布局并勾选推理端接入确认。Paddle或未知自定义适配器不开放四模式；要求嵌入模型独立完成时明确拒绝。不能将此能力误称为设备SDK已经应用。

输入为紧密排列8位Y′CbCr，NV12=Y+UV、I420=Y/U/V、YUV444=平面Y/U/V；420尺寸须为偶数，色度nearest repeat，不假设SDK色度位置/stride；无gamma/传递函数转换。输出HWC uint8 RGB或原模型合同要求的BGR，float64计算，乘255、裁剪、floor(x+0.5)。后续resize/mean/scale/布局仍由原预处理合同处理，不能对已经解码RGB再重复CSC。

|预设|系数|范围|同一Y=100,Cb=90,Cr=240的实际RGB|
|---|---|---|---|
|BT.601 Limited|Kr=.299,Kb=.114|Y=(Y-16)/219,C=(C-128)/224|[255,22,21]|
|BT.601 Full|Kr=.299,Kb=.114|Y=Y/255,C=(C-128)/255|[255,33,33]|
|BT.709 Limited|Kr=.2126,Kb=.0722|Y=(Y-16)/219,C=(C-128)/224|[255,46,18]|
|BT.709 Full|Kr=.2126,Kb=.0722|Y=Y/255,C=(C-128)/255|[255,55,29]|

矩阵R=Y+2(1-Kr)Cr、B=Y+2(1-Kb)Cb，G按Kg=1-Kr-Kb推导。相同原始YUV分别解码，未通过RGB编码/匹配逆变换抵消；不是HSV。三种布局、黑白端点、RGB/BGR、输入不变、重复结果一致均有必要断言。

none明确不额外适配；device_default不推测设备矩阵；历史缺失显示“历史未记录”。requested preset、参考数学实现、device_observed分开记录；所有新合同仍`applied=false`、`device_observed=unknown`、板端`NOT VERIFIED`。原用户A800/BM1688数值仅作问题背景，本轮没有其原始帧/张量，不声称重现该设备结果。

## 性能与视觉证据

[原始受控记录](artifacts/conversion-modal-controlled-20261028/timing.json)：同一隔离Chrome与源版本，资源GET固定等待1200ms，旧2c5311c6 app在内存route提供；旧弹窗1380ms、新36ms，资源/历史/目录各1请求。原[修改前](artifacts/conversion-modal-controlled-20261028/baseline.png)及[修改后](artifacts/conversion-modal-controlled-20261028/progressive.png)保留。后续CI测试读取已记录旧基线（不依赖浅克隆旧commit，不重新声称测量旧代码），当前实时检查见[current-timing-check.json](artifacts/conversion-modal-controlled-20261028/current-timing-check.json)，79ms且资源响应前表单已经出现。

1000条隔离Windows job记录：首次1000 JSON、10活动overlay、3146.527ms；紧接热读0 JSON/0元数据扫描、10 overlay、1.448ms；一条变化后1 JSON/999复用、11 overlay、28.994ms。含临时磁盘/测试观察开销；这些不是生产延迟或提升百分比。真实A800/OSS/NAS、生产源模型大小和编译耗时仍NOT VERIFIED。

1366×768补验仅运行CSC用例1次通过：真实wheel滚到底部，提交可见可点击、无横向溢出，见[小屏截图](artifacts/conversion-modal-controlled-20261028/current-csc-create-1366.png)。

当前[CSC配置](artifacts/conversion-modal-controlled-20261028/current-csc-create-1920.png)与[历史详情](artifacts/conversion-modal-controlled-20261028/current-history-details-1920.png)为真实Chrome隔离接口截图（1920×1440），不冒充生产真实业务记录。

## 必要测试、问题与修复

只执行受影响检查，不在本地全仓回归。相同状态通过项不因等待重复执行，以下分组有重叠，不相加作虚假总数：

|检查|实际结果|
|---|---|
|CSC/资源/1000记录历史三个新模块最终检查|20 passed，0 failed，0 skipped|
|原conversion、remote conversion、color adapter、portable API相关回归|81 passed（后续ZIP修改另行定向验证）|
|动态目录/resolve API|16 passed；新增真实旧job分页API另1 passed|
|实际微型ONNX Worker、参考CLI、远程可信ZIP、Agent成功/回滚|最终6 passed，0 failed；无GPU|
|最终本地创建CSC兼容、板端truth投影、资源TTL|4 passed；BGR继承单项1 passed|
|最终受影响Node与版本入口|41 passed，0 failed，0 skipped|
|真实Chrome|渐进失败重试、原Sophon矩形FP32/BGR、当前受控时间、CSC提交、历史筛选分页/展开保持分别通过；末三项3/3通过|
|语法/工作流|py_compile通过，workflow YAML解析3 jobs，git diff --check通过|

发现问题均记录真实过程：API首次7项失败为resolve_chip_capability漏导入，已修复后16通过；审查发现旧Sophon preprocessing BGR未传入CSC输出顺序，已修复并新增最小边界验证；异步resolve曾重置用户BGR，原编辑标识已补齐并用原Chrome回归；直接发布.py/.md不符合原文件安全后缀，改为已有ZIP登记，不降低权限；Agent提交失败辅助文件回滚已验证。未通过删除测试、跳过断言或放宽真实硬件验证获得绿色。

## 文件与接续

实际业务文件：static/app.js、static/styles.css、static/index.html、app.py、deployment_worker.py、platform_core/conversion.py、conversion_csc.py、conversion_resource_detection.py、conversion_history.py、remote_conversion_runtime.py、node_agent_conversion_runtime.py、remote_execution_transport.py；相应原测试与现有remote-conversion工作流接线。VERSION.txt仅本轮递增398。

首次提交ea213f1fdc384cffce63c60c81ed4f89b8ba4dc4已正常推送，但CI检出三项需修正：精简传输环境顶层导入NumPy、原启动Owner禁止新MutationObserver、原RKNN板端验证按钮被详情折叠。已将NumPy延迟至像素解码（不扩CI依赖），清理沿原Modal beforeClose且精确form/ticket处理，板端验证/停止等操作保持卡片直接可用；不削弱原测试。修正后Python24通过，standalone无site-packages合同/参考ZIP生成通过，Node50通过，原RKNN板端完整流程及慢资源Chrome2/2通过。最初-S直接导入包会因原filelock依赖失败，改runpy单独验证CSC依赖边界，不宣称整个平台无第三方依赖。VERSION398不二次递增。最终修正SHA和CI待核验。03728393（上一负样本文档）已21/21 Actions、57/57 Checks成功，与本轮无关，不能用作本轮验收。

接续仅处理准确SHA CI真实失败或本专项剩余验证；不重建训练、GT、任务、缓存或Modal。生产SDK/远程Agent/板端/BMCV接入、真实母模型大文件、生产接口耗时和用户给定A800/BM1688帧尚未验证，需授权环境独立实测。关闭或不选CSC不依赖参考模块执行；原模型与下载保留。未生产部署、安装依赖、转换真实模型或删除用户文件。

### 后续CI兼容性修正

b763105cd41387a86981d583b4697fea4f96e509保留首轮修复。后续CI发现旧history源码守卫与Chrome route仅接受无query地址，分页请求落入真实404；现仅将原夹具更新为query-keyed缓存、force/signal及分页地址，保留并增强节点稳定、并发去重、只刷新活动任务、终态自动显示产物/下载和UNKNOWN防重断言，未删或跳过测试。定向Node21/21、原进度/缓存/产物Chrome3/3、原pending/rejected恢复Chrome2/2通过。额外只读检查发现ZIP create_system会随Windows/Linux不同，原用例追加断言先RED再固定为3，最小ZIP与远程篡改验证2/2 GREEN，LF/时间/权限同样固定。此变更不影响原始模型及旧无CSC任务；新CSC远程执行要求兼容的同版参考合同，不能混用未升级Worker并宣称成功。

a4bec87e16a5cbacaac8ceb5340352c36e7968b0后续CI仍检出deployment-runtime-source中一条手动刷新旧函数签名；已同步为当前filter/page+signal并增强abort/project/epoch/DOM隔离断言，单文件11/11通过。未修改业务代码或工作流。最终以接续新SHA验收，不能把a4或b763当全绿。

最终交付检查补齐详情原已有数据的展示：同一证据区同时呈现source_identity/SHA、请求参数、有效参数、完整执行/SDK证据，避免API已返回而页面只显示精度摘要；没有新接口或状态来源。原服务端筛选Chrome用例额外断言源SHA/SDK并更新真实截图，1/1通过；入口缓存449与版本Owner10/10通过。

## 最终代码验收与交接（2026-10-28）

最终业务/测试提交：`f2af4af35e45b86920bbddcc63aa13df816d178b`，VERSION `42.24.398`，已正常推送唯一长期分支。GitHub准确绑定41/41 Actions、115/115 Checks全部success，0 failure/cancelled/skipped/pending；[完整只读回执](artifacts/conversion-modal-controlled-20261028/code-ci-f2af4af3.json)。该结论不使用旧SHA绿色，首推及夹具/依赖边界失败过程保留在本文件。仅取消本会话e002被后继提交取代的2项未完成检查，未改其他会话CI。

软件范围A–E已验收。后续不得重复建设Owner或将“contract_only”改报为板端应用成功；真实外部SDK/设备BMCV集成、生产大模型/OSS/NAS性能、用户原始帧与张量对比均NOT VERIFIED。没有生产部署、生产数据修改或真实GPU训练。

本次仅补写验收文档/索引和代码SHA回执，不改变f2af4af3业务。文档所在实际提交的CI须从其GitHub Checks独立核对，最终交付提供该提交HEAD及结果；不能拿上述代码CI替代文档提交自身检查。下轮接续先fetch并保护当前工作树、5944及训练模板WIP，只在授权的真实环境补验或处理真实反馈；旧任务CSC缺失保持未知，原母模型及其他版本产物继续保护。

## 2026-11-04 接续：42.24.519 配置显隐真实 Chrome 修正

数值一致性验证及转换工作台重构见 `CONVERSION_NUMERIC_VERIFICATION_AND_UI_2026_11_04.md`。`42.24.518` 远端 20 个 Actions 中 19 绿，`Remote Conversion Runtime/real-chrome` 因 RKNN INT8 校准区被新增的高级折叠容器遮挡而失败；同一审查发现 ONNX、TensorRT、算能配置控件的折叠可见性风险。`42.24.519` 只修正原控件 DOM 展示层级和回归断言，不重写转换 Owner 或降低校准约束。Node 1522/1522 通过；真实 Chrome 与后续 CI 需以此轮提交单独核实。生产数据、模型产物、原始 GT 均未修改。
