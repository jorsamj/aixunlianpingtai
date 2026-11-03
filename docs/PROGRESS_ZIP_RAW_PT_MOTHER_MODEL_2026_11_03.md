# 2026-11-03 开发进度｜原图 ZIP、母模型资产与首次训练

工作基线：`feature/external-algorithm-publishing`、开始时本地/远端 `5e708bc4fce5c0a0facaa02f1d6d426871fb40d6`。
本轮仅修改代码/文档；不触碰生产服务器、真实素材/模型、数据库或训练任务。此为**进行中交接记录，未达到整项 P0 完成标准**。

| 里程碑 | 当前状态 | 已写入代码的内容 | 尚未完成的阻断项 |
| --- | --- | --- | --- |
| P0-1 ZIP 扫描/原图 | 部分实现，待 Python 集成 | 全空 sidecar 与 schema hints 脱钩；原图无需正负样本确认；混合 `scan_kind`、空 GT 不转 `confirmed_empty`；COCO/VOC 漏清单原图补入 | 精确逐图异常分类/孤立 sidecar/冲突计数、1k/10k 真实性能、数据库集成验证 |
| P0-2 ZIP→AI/人工 | 部分实现 | ZIP 结果四路径操作；AI `source_batch_id` 后端解析并冻结待标注 ID；人工批次 150 张翻页；既有清洗整理入口 | 清洗结束自动衔接 AI、AI/人工全链路真机验收、AI 离线引导、批次修订与性能负载 |
| P0-3 母模型验证 | 部分实现 | 上传后登记内容地址资产；`asset_id`/SHA 状态；基于 bubblewrap 的可选隔离探测；原始 `names`/task；未通过校验禁止训练 | 真实官方/自定义 PT 与 Ultralytics 8.4.127 环境验证、沙箱目录兼容、跨进程持久校验队列及人机交互完善 |
| P0-4 跨节点发现/安装 | **已实现安装协议，待 CI/现场验收** | Agent 授权目录发现；管理端登记；新增 `MODEL_INSTALL` 中心任务、严格节点绑定、租约鉴权流传输、内容哈希校验、原子文件落盘、任务代次回执、取消与同内容重用 | 本批 Python CI、真实 Agent 网络断连/磁盘不足、远程模型环境检验、实际训练使用已安装副本 |
| P0-5 首训/视觉/性能 | 部分实现 | 高级“母模型管理”单层 Tab；训练下拉仅提供已验证资产；训练标签合同保留原始 names 并阻止同 nc 语义错位；远程 Agent 可按冻结 SHA 优先复用已安装模型，否则回退对象存储 | 真实版本检测头适配、GPU 首训日志、真实 Chrome 三视口、冷热性能测量、最终 CI |

## 本轮具体变更

- `app.py`：v19 ZIP 分类、导入 GT 与完整图片集合、AI 按 ZIP 批次创建、人工分页；母模型登记/校验 API、首次训练安全挡板。
- `platform_core/mother_model_assets.py`：内容寻址登记/幂等、仅结构检查、可选 OS 沙箱 YOLO 验证；没有隔离能力时**拒绝校验**，绝不直接 Web 反序列化。
- `platform_core/training_label_tasks.py`：原始母模型有序标签/sha 与新算法 GT 的合同记录和错位阻断。
- `static/app.js`、`static/modules/zip-import-runtime.js`：ZIP 四操作、批次化 AI/人工工作台，不叠加第二层弹窗。
- `static/modules/advanced-navigation.js`、`static/modules/resource-discovery.js`、`static/modules/training-submit.js`、`static/styles.css`：高级母模型页面、校验入口、明确就绪状态与单层样式。
- 增加 API/前端测试；修订原有误把空 sidecar 当正式 GT 的过时断言。

## 已执行验证与限制

- `python3 -m py_compile app.py platform_core/mother_model_assets.py platform_core/training_label_tasks.py`：通过。
- `node --check` 涉及的 JS：通过。
- `node --test tests/frontend/zip-mother-workflows-p0.test.mjs tests/frontend/zip-import-durable-runtime.test.mjs`：37/37 通过。
- `node --test tests/frontend/advanced-navigation.test.mjs tests/frontend/training-submit.test.mjs`：64/64 通过。
- `npm test` 全量：当前执行容器缺 `@uppy/core` 依赖，出现 `ERR_MODULE_NOT_FOUND`；**不可宣称全绿**。
- Python API/pytest：当前执行容器缺 `fastapi`、`filelock`、`pytest`，无法运行 API/集成用例。
- 本机没有可用 GPU 和实际 A800/4070 Agent；未执行 PT 真正成功安全解码、Worker 首训、节点永久安装。当前容器 `bwrap` 无权限创建 namespace，验证应呈 `SANDBOX_UNAVAILABLE`，不是成功。
- 真实 Chrome 交互和目标 P95：**尚未验收**。不能把前端回归当成视觉/性能证据。

## 未完成前严禁的宣称与下一步

1. 不能标“全部完成”“正常可训练无堵点”“跨服务器模型部署就绪”或“CI 已全绿”。
2. 优先安装项目锁定依赖并执行 Python API/ZIP、母模型安全测试；据真实返回修复问题。
3. 补 Agent MODEL_DISCOVERY / MODEL_INSTALL 控制面及 allowlist、资产副本/调度节点约束，修复校验后台恢复。
4. 在隔离 YOLO 8.4.127 + GPU 下测同标签、不同标签、COCO 迁移与真实 Worker 加载，保留哈希/日志证据。
5. 完成真实浏览器、性能和 CI；正式变更/部署必须另获用户授权。

## 2026-11-04 接续增量：节点只读发现与管理端模型登记

- 2026-11-03 先前远端提交：`653a33cd2a662ea95f445178c0d362361d3baed5`；本轮以相同 Git 文件树为基线增量开发。
- `platform_core/mother_model_inventory.py`：仅授权路径、最多 8 个根、1500 目录/20000 目录项、64 个 `.pt`、深度 5 的后台扫描；不读权重内容/不 unpickle/不跨软链接；扫描结果全部 `DISCOVERED_UNVERIFIED`。
- `node_agent.py`：支持 `MC_AGENT_MODEL_SCAN_ROOTS`（Linux 冒号、Windows 分号分隔）及 `--mother-model-roots`；有 `MC_TRAIN_DATA_DIR/models` 则纳入已有本机模型目录。按不短于 30 秒的间隔异步刷新，心跳只读上次结果，不扫描整台主机。
- `app.py`：`GET /api/v63/base-models/node-inventory` 仅聚合现有已登记 Agent 的心跳缓存；离线节点显示 `OFFLINE`，未经验证的路径绝不可训练。`POST /api/v63/base-models/discovered/register` 只允许按**现有持久本机模型扫描缓存精确路径**显式登记，通过有界内容复制及 SHA256 确认后成为待校验资产；不能提交任意服务器绝对路径。
- `platform_core/resource_discovery/cache.py`：按原扫描缓存的 normalized_path 精确查找，未修改底层扫描缓存、索引策略。
- `static/modules/resource-discovery.js`、`static/styles.css`：高级母模型同页展示管理端已发现模型与远程节点清单，提供管理端“登记”单步操作；无额外弹窗、无定期深扫；保持响应快、结果可信。
- `tests/unit/test_mother_model_inventory.py`：5 个独立可运行的隔离测试通过。相关 68 项 Node 试验通过；Python 语法检查通过；**真实 FastAPI、Agent→管理端 HTTP、A800/4070 安装及训练仍未执行**。
- **关键限制**：Agent 模型发现 ≠ 模型已安装、通过兼容性检验或可训练。指定节点上传/安装任务仍缺；不得因扫描成功将 PT 暴露给训练选择器。生产环境和数据不动。
- 后续审计补强：Agent 扫描还限制单条路径上报长度，拒绝跟随符号链接及跨设备目录，以控制心跳载荷并防止目录扫描意外进入子挂载盘；仍需真实 4070/A800 节点验证这些边界。

## 2026-11-04 接续增量：指定节点安装与受控流式传输（待新版本 CI）

- `platform_core/task_runtime/models.py`、`task_node_assignments.py`：新增 `MODEL_INSTALL`，仍使用**原中心调度/节点分配/租约/取消**，仅允许严格 node affinity + Agent `model-upload` 能力的在线节点。没有 OSS 时也可由现有 Agent 带令牌从管理端流式领取 PT，不开放任意远程路径或通用文件写接口。
- `app.py`：新增 `POST .../assets/{asset_id}/install` 创建精确模型/节点任务、在活动任务上去重；`GET .../installations`、`POST .../installations/{task_id}/cancel` 提供真实状态；新的控制端 payload resolver 只传 `asset_id/sha256/size_bytes`，节点 ID 与指定分配节点校验，不传管理端路径。
- `platform_core/agent_execution.py`、`node_agent_executor_runtime.py`：`/mother-model/read` 与 `/mother-model/receipt` 均要求本次有效 Agent 身份+执行代次+租约所有权。流读取每块复核所有权，完成回执需与持久任务冻结的 asset/node/size/sha 一致；没有当前代次回执不得宣称 `SUCCEEDED`。
- 新建 `platform_core/node_agent_model_install_runtime.py`：只允许写节点管理员配置的本地目录，按完整 SHA256 命名，边下载边验大小/hash，临时文件 fsync+原子 rename；重复内容先核验并重用，不同字节拒绝覆盖。Agent 遇取消/撤销租约将停止，失败不动管理端源资产。`node_agent.py` 只有目录真实可写才上报 `model-upload`，目录参数为 `MC_AGENT_MODEL_INSTALL_DIR`/`--mother-model-install-dir`，可回退已有数据目录的 `models`。
- `static/modules/resource-discovery.js`、`static/styles.css`：高级母模型单层页面展示各副本的任务/节点与 SHA 完成状态、真实异步进度、安装/取消按钮；不套新弹窗、远程发现仍显示“待验证”。
- 新增 `tests/unit/test_agent_model_install_runtime.py` 的成功/幂等、坏字节 hash、目标软链拒绝、指定节点调度、回执/代次/成功挡板回归；前端专项本地 `103/103` 通过，`py_compile` 与 `node --check` 通过。本地未安装 `pytest` / FastAPI，故**Python 用例尚未运行**，必须等 GitHub Actions 正确运行后才能更新状态。
- 上一稳定远端 `4de909010f180ba3e593bfb182d425f707d0929c` 的 GitHub Actions **20/20 success**（2026-11-04 核查）。本次新协议尚无远端提交或 CI 结果；不可援引上一版本绿色测试保证本次功能。
- **剩余 P0**：按固定生产 Ultralytics 8.4.127 在隔离 Worker 上验证本机自定义 PT、真实 GPU 首训和标签头迁移；校验已安装副本能否由远程训练直接优先复用（现有远程训练多通过 OSS 对象合同准备权重）、无 OSS 环境部署/断点续传/多 GB 行为，视觉 Chrome 三视口及 P95 性能；部署生产仍需另行授权。

## 2026-11-04 接续增量：已安装母模型与远程首训协同

- `platform_core/node_agent_training_runtime.py` + `node_agent.py`：使用已授权的 `MC_AGENT_MODEL_INSTALL_DIR`，仅针对经过远程准备、带冻结 `size_bytes/sha256` 的对象权重查找 `managed-{sha}.pt`；复制过程中流式核验 SHA 和大小，构建训练任务自己的权重副本。未安装、文件不符或符号链接则继续使用原有下载校验流程，绝不直接引用控制端磁盘路径。
- `tests/unit/test_node_agent_training_runtime.py`：新增成功命中与任务隔离、损坏/缺失/软链接回退四类用例。当前执行容器未安装 pytest 等依赖，须由 CI 验证。
- **不会省略远程训练原有对象存储准备阶段**：输入图片和结果传输仍依赖原始合同；这项是 Agent 下载优化与真正加载指定 PT 的衔接，不应解释为“无 OSS 全远程训练已打通”。
- 已实际快进推送基础安装协议与相关文档至长期开发分支 `0da5379e5f2b40c4f72437d8ffffb373282c77b4`；精确 SHA 的 20 条 Actions **16 成功、4 失败**。4 个失败工作流均为新路由参数漏列的同一过时 AST 测试断言，其余对应工作流 Job 已通过；本段增量尚待下一次提交与 CI。
- 首轮安装提交的多个 API 分片暴露同一个过时静态断言：`tests/api/test_runtime_router_app_mount.py` 未列出新增 `agent_model_install_asset_provider`；已补精确允许集合，并断言仅调用既有已验证资产登记。单独通过 AST 守卫运行。原安装测试虽已提交，但原 `node-agent-executor.yml` 并未执行新测试文件；本批已将 `test_agent_model_install_runtime.py` 以及安装 Runner 加入 Linux/Windows 的路径触发、语法和 Pytest 实际清单，不能把旧分片绿灯计为已验证安装。
- `c461f7a31505e13ae7e6a707321816d05259dc15` 的准确 GitHub Actions 结果是 **18/20 成功、2 失败**。两项红灯 `Remote Training Runtime` 与 `Node Agent Executor` 的 Windows 测试均为新增缓存回退单测使用 Linux 分隔符的路径断言；Linux 对应测试和安装 Runner 双平台合同均通过。当前已用 `Path(result)` 比较消除 Windows 路径假失败，并在缺失 symlink 创建权限时明确标记跳过；待下一次提交复验。

### 上一提交 GitHub Actions 红灯治理

远端 `653a33cd` 的 20 项工作流完成后为 **16 成功、4 失败**，不能沿用“排队中”或“全绿”结论。已从失败 Job 日志确认以下回归并在本次工作树修正：

1. `platform_core/training_label_tasks.py` 新增母模型原始标签合同误用了未定义的 `include_weight_digest`，应使用公开函数实际入参 `include_base_weight_digest`；此前导致大量训练标签/输入/远程 API 用例抛 `NameError`。
2. v19 纯原图 ZIP 本应允许用户**可选**明确申报正样本或负样本；先前 `sample_classification_required=False` 同时意外跳过自愿的分类归属。已更改为默认无需分类，但显式提交仍走原有验证/归属流程。
3. 新增的 ZIP 测试错误地期望浏览器进度 JSON 内包含所有 `imported_image_ids`；原系统早已将大数组归档为单独报告以避免页面卡顿。测试调整为调用既有 ZIP 审核/明细读路径，不让前端重新回传上万 ID。
4. 外部平台测试对 `TaskKind.TRAINING_PREPARE` 的源码静态断言引用了旧位置；当前真实代码已委托 `platform_core/training_prepare_child.py`。测试同时校验委托与唯一子任务所有者。

本地 Python 依赖不齐，以上后端修复**尚待新提交的真实 GitHub CI 回归**；不得据静态检查宣称已经通过。
