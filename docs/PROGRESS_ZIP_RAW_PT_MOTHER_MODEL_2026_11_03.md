# 2026-11-03 开发进度｜原图 ZIP、母模型资产与首次训练

工作基线：`feature/external-algorithm-publishing`、开始时本地/远端 `5e708bc4fce5c0a0facaa02f1d6d426871fb40d6`。
本轮仅修改代码/文档；不触碰生产服务器、真实素材/模型、数据库或训练任务。此为**进行中交接记录，未达到整项 P0 完成标准**。

| 里程碑 | 当前状态 | 已写入代码的内容 | 尚未完成的阻断项 |
| --- | --- | --- | --- |
| P0-1 ZIP 扫描/原图 | 部分实现，待 Python 集成 | 全空 sidecar 与 schema hints 脱钩；原图无需正负样本确认；混合 `scan_kind`、空 GT 不转 `confirmed_empty`；COCO/VOC 漏清单原图补入 | 精确逐图异常分类/孤立 sidecar/冲突计数、1k/10k 真实性能、数据库集成验证 |
| P0-2 ZIP→AI/人工 | 部分实现 | ZIP 结果四路径操作；AI `source_batch_id` 后端解析并冻结待标注 ID；人工批次 150 张翻页；既有清洗整理入口 | 清洗结束自动衔接 AI、AI/人工全链路真机验收、AI 离线引导、批次修订与性能负载 |
| P0-3 母模型验证 | 部分实现 | 上传后登记内容地址资产；`asset_id`/SHA 状态；基于 bubblewrap 的可选隔离探测；原始 `names`/task；未通过校验禁止训练 | 真实官方/自定义 PT 与 Ultralytics 8.4.127 环境验证、沙箱目录兼容、跨进程持久校验队列及人机交互完善 |
| P0-4 跨节点发现/安装 | **发现链路部分实现；安装未实现** | Agent 授权目录后台有界发现；现有心跳携带未验证 PT 清单；管理端单层展示节点/离线状态；管理端本机已扫描 PT 可明确登记为资产 | Agent 到节点的安装/持久任务、模型校验及副本 SHA、调度节点匹配、无 OSS 回退、真实现场验证 |
| P0-5 首训/视觉/性能 | 部分实现 | 高级“母模型管理”单层 Tab；训练下拉仅提供已验证资产；训练标签合同保留原始 names 并阻止同 nc 语义错位 | 远程 Worker 指定节点、重建检测头的真实版本适配、GPU 首训日志、真实 Chrome 三视口、冷热性能测量、最终 CI |

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

### 上一提交 GitHub Actions 红灯治理

远端 `653a33cd` 的 20 项工作流完成后为 **16 成功、4 失败**，不能沿用“排队中”或“全绿”结论。已从失败 Job 日志确认以下回归并在本次工作树修正：

1. `platform_core/training_label_tasks.py` 新增母模型原始标签合同误用了未定义的 `include_weight_digest`，应使用公开函数实际入参 `include_base_weight_digest`；此前导致大量训练标签/输入/远程 API 用例抛 `NameError`。
2. v19 纯原图 ZIP 本应允许用户**可选**明确申报正样本或负样本；先前 `sample_classification_required=False` 同时意外跳过自愿的分类归属。已更改为默认无需分类，但显式提交仍走原有验证/归属流程。
3. 新增的 ZIP 测试错误地期望浏览器进度 JSON 内包含所有 `imported_image_ids`；原系统早已将大数组归档为单独报告以避免页面卡顿。测试调整为调用既有 ZIP 审核/明细读路径，不让前端重新回传上万 ID。
4. 外部平台测试对 `TaskKind.TRAINING_PREPARE` 的源码静态断言引用了旧位置；当前真实代码已委托 `platform_core/training_prepare_child.py`。测试同时校验委托与唯一子任务所有者。

本地 Python 依赖不齐，以上后端修复**尚待新提交的真实 GitHub CI 回归**；不得据静态检查宣称已经通过。
