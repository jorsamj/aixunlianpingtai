# P0 需求基线｜原图 ZIP 与跨节点母模型管理（2026-11-03）

项目：畅联云算法训练平台；唯一开发分支：`feature/external-algorithm-publishing`。
此文记录**目标要求**，实现状态请以同目录 PROGRESS / UAT 为准；不能将目标文字误当已上线功能。

## 用户故事与主流程

1. 用户上传含原图、空 `.txt`、空 VOC object 或 COCO `annotations=[]` 的 ZIP；系统扫描 ZIP 中**实际框**与异常，不能因 `data.yaml` 声称“已标注”。
2. 全空标注直接按 `unannotated` 导入，不预先强制声明正样本/负样本。混合 ZIP 保留已确认的有效框，并将其余原图入库；异常标注要单独提示。
3. ZIP 完成页在单一页面展示“已有正式标注 / 待标注 / 异常”，提供“直接 AI 预标注（推荐）/先清洗后标注/直接人工标注/暂存素材库”；AI 不可用时可以人工处理。批次由服务端冻结，不让前端搬运上万图片 ID。
4. AI 预测仅生成候选框；用户批量/逐张审核后才写正式 GT。空 sidecar 并非经人工确认的负样本，严禁偷偷进入 YOLO 导出。
5. 高级功能→算力与节点→母模型管理，复用原上传、环境发现、服务节点、模型解析和训练调度，不另起控制面。可上传、本机/Agent 按授权目录发现、安全校验、绑定模型资产与节点副本、安装到指定节点。
6. 新算法首次训练可选择 SHA 冻结且通过真实验证的 YOLO Detect `.pt`；显示真实框架、架构、`task`、原始 `names`/`nc`，并冻结模型来源与 GT 类别合同。已有算法版本继续使用原继承链。

### 2026-11-04 补充：旧算法基础模型可见性与异步刷新一致性

7. 已有成功、已校验有效版本的算法，训练创建页“基础模型”必须始终明确显示“从当前有效算法版本的 best.pt 继续训练”等可信继承状态，并保持只读。不能因草稿中残留首次训练时的 `.pt` 名称，在重新加载训练资源后把下拉框设为无选中项。
8. 首次训练只显示当前资源真实可用的 `.pt`，其空状态须有可理解的提示；资源异步加载、重新加载、算法切换时应使用同一模型渲染函数，保持前端选项与服务端训练继承/首次训练合同一致。
9. 浏览器回归至少覆盖旧算法已有有效版本、草稿遗留 `yolo11n.pt`、再次触发资源刷新后下拉仍显示继承信息，且 `selectedIndex` 不为 `-1`；不能仅断言下拉框为 disabled。现有模型安全校验与真实 Worker 继承逻辑不变。

## 数据状态合同

| 对象 | 必须区分 | 关键安全边界 |
| --- | --- | --- |
| ZIP | `RAW_UNANNOTATED` / `MIXED` / `ANNOTATED_VALID` / `ANNOTATION_INVALID` | 类别提示不是正式标注；不能仅凭存在 sidecar 判定 GT |
| 单图 | `unannotated` / `annotated` / `confirmed_empty` / 异常待处理 | 候选框非正式 GT；无目标须带真实审核记录及标签范围 |
| 母模型 | 已登记 / 待校验 / 检测中 / 可训练 / 不兼容 / 校验失败 / 不可用 | `.pt` 的文件名、大小、哈希和存在性不能代替安全兼容性判断 |
| 节点副本 | 不存在 / 安装中 / 已安装且 SHA 一致 / 离线 / 证据过期 | 控制端本机路径绝不能冒充远程 Worker 本机路径 |
| 训练 | 初始化微调 / 断点恢复 | 首次训练使用已有权重≠`resume=True` |

## API、冻结与幂等

- 现有 ZIP 扫描、v19 导入与 GT 存储为唯一权威；`scan_kind` 和统计从服务器产生。
- 现有 `POST /api/v60/projects/{project_id}/annotation-tasks` 扩展 `source_batch_id`，与显式 `image_ids` 互斥；服务端从成功导入的报告解析全部图片，以正式 GT 过滤未标注集，冻结到任务 `request.json`；`request_id` 保持幂等。
- 人工工作台采用按 `cursor/limit` 读取 ZIP 未标注子集；不拼全量 URL/页面列表。
- `POST /api/v63/base-models/upload` 继续实现流式存储、同名异哈希冲突；返回 `asset_id` 与准确验证状态。`GET /api/v63/base-models/assets` 只读登记证据，不运行重量级扫描；`POST /api/v63/base-models/assets/{asset_id}/verify` 触发隔离校验。
- 完整目标还包括按节点受控扫描、拉取/安装任务、`node_id+sha256` 副本合同、明确传输渠道、断网恢复与部署审计；未实现不能通过虚拟状态/按钮掩盖。
- 节点安装任务采用现有 `TaskKind.MODEL_INSTALL`、`model-upload` 能力、中心节点分配与 Agent 租约；`POST /api/v63/base-models/assets/{asset_id}/install` 只能传系统登记的 `node_id`，不能传远程绝对路径。上传至管理端的资产只有通过隔离校验才能分发。实际传输是同租约鉴权的流式 `agent-artifact-v1`，不要求 OSS；Worker 只写预配置 `MC_AGENT_MODEL_INSTALL_DIR` 或存在的 `MC_TRAIN_DATA_DIR/models`。接收字节必须与冻结大小、SHA256 一致，采用临时文件+原子落盘，提交任务代次绑定回执后方可进入 `SUCCEEDED`；允许精确取消，失败保留源资产。
- `GET /api/v63/base-models/installations` 返回真实任务进度与已完成的代次回执；不能用“已发现路径”或“传输进度100%”代替已成功安装，也不能把 Agent SHA256 回执冒充模型在该节点上的 YOLO/训练兼容性证明。
- 节点发现的初步合同：Agent 可以通过 `MC_AGENT_MODEL_SCAN_ROOTS` 显式授权目录（若数据目录存在也含 `MC_TRAIN_DATA_DIR/models`），后台最多扫描 8 根/1500 目录/20000 项、5 层、64 个 PT；心跳仅提供发现证据。管理端可从**已有本机扫描缓存**显式登记模型资产，任何发现结果均不可越过独立验证和真实节点安装直接进入训练。
- 训练提交应使用不可变 `asset_id+sha256`，Worker 开始前复核、回填实际权重和类别/检测头策略，不允许仅按 `nc` 相同默认兼容。
- 远程首次训练如引用的模型对象 `sha256+size_bytes` 与当前 Agent 的 `managed-{sha256}.pt` 安装副本完全一致，Agent 应**优先经流式哈希核验复制为本任务独立输入**，避免对相同节点重复网络下载；副本不存在、软链接或字节不匹配时自动回退既有对象存储下载，不将“副本已安装”冒充训练兼容性。远程训练保留现有对象存储模型合同与素材/结果传输通道，不能未经证明声称无 OSS 全流程首训可用。

## UX 与质量门槛

- 单层导入/配置页面：禁用弹窗套抽屉、弹窗套弹窗；同一页面完成后续选择，避免刷新跳动。
- 沿用已有 CSS/JS 生命周期、通知、任务中心；不增加另一套请求/缓存、无意义卡片或大量说明文字。
- 首屏操作 ≤100ms 反馈（目标，必须实测）；列表已缓存 P95 ≤500ms；10k 张图片不能在浏览器同步拉取或 DOM 渲染。模型内容检测/节点部署在后台执行。
- 1366×768 / 1440×900 / 1920×1080 / 移动宽度验收，不允许旧请求污染新页面。
- 按任务书 ZIP-01…08、PT-01…07、TR-01…02、UI-01、PERF-01 执行功能/安全/异常/性能测试，UAT 中逐条保留实际证据。

## 开发权限

仅可在长期分支增量开发与推送，不 merge main、release、force push；不得修改生产 DB、素材、正式 GT、任务、GPU 训练或生产服务。部署另行授权。

## 技术依据

- [Ultralytics Detect Dataset](https://docs.ultralytics.com/datasets/detect/)：标注缺失与背景数据的训练含义需由平台谨慎管控。
- [Ultralytics Train](https://docs.ultralytics.com/modes/train/)：预训练微调和 resume 区别。
- [PyTorch torch.load](https://docs.pytorch.org/docs/stable/generated/torch.load.html)：不要在 Web 主进程执行不可信 checkpoint 反序列化。
- [CVAT 自动标注](https://docs.cvat.ai/docs/annotation/auto-annotation/automatic-annotation/)：候选预测与人工审核分开。
