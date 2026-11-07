> **42.24.553 接续**：既有原生协议、人工审核、草稿、转池和正式GT边界复用；本轮补安全推理容量/并发/乱序恢复。专项见 [双实例安全推理](WEVISONE_DUAL_GPU_INFERENCE_P0_2026_11_07.md)。真实4070仍未验证，未修改生产服务。

# 畅联云算法训练平台｜WeVisOne-VL 可选专用适配器 P0

**开发日期**：2026-11-06

## 42.24.543｜宿舍 person / tangzhe 混淆：原生查询描述闭环

**发现的真实代码缺陷**：在 42.24.542 及以前，WeVisOne `WeVisOneVisionProvider._request` 丢弃通用 `prompt`，固定向专用 `/v1/vision/detect` 传入 `query=["person","tangzhe"]`。因此用户在任务创建页粘贴“床上是 tangzhe、站立是 person”的长提示词，**事实上并未传给原生检测服务**。不能把这一现象简单归咎于模型不听指令。

**修复**：

1. 原有模型配置编辑窗仅当选择 `wevisone_vl` 时展示“标签定位描述”，支持每个正式标签 `code` 对应一条独立自然语言检测查询；内置可编辑宿舍示例：`person` 限定床外站立/行走真人、排除灭火器；`tangzhe` 限定床上躺卧（有/无被子；蓝床单只能作线索，不能单独认定有人）。不增加第二套配置中心或任务流程。
2. 仍使用原生请求 `{"image":DataURI,"query":[...]}`，只替换 `detect` 中的 `query` 内容，不发送假设存在的聊天 `prompt` 字段。`segment`、`matting` 不受影响。
3. 在专用 Provider 内把查询描述加入**本次冻结标签的受约束别名映射**，把原生响应里匹配描述的 `label` 映射回正式 `person`/`tangzhe` code，再沿用原图像素坐标、Candidate、人工审核和 GT 合同；错误标签、重复或歧义描述、控制串、越界坐标仍拒绝，不静默改成空框。
4. 为防止误导，创建 AI 标注任务时若选择 WeVisOne，步骤四改为“实际原生标签查询”预览，隐藏对该 Provider 无效的通用提示词编辑项；切换到 Qwen/Gemma/Ollama 等通用 Provider 时恢复原编辑功能。配置从已保存的单一模型配置与任务快照传递；历史任务不回写。
5. 旧客户端 PUT 若不带新字段，继续保留已有描述；显式传 `{}` 可清空。通用 Provider 不保存该专用字段。包含请求体、映射、非法描述、配置存取和前端模型选择等回归。

**验证及尚待完成**：本地 Python WeVisOne/配置 API 71/71、Node 1546/1546 通过，`node --check`、`git diff --check` 通过。已增加真实浏览器隔离用例，但本地没有 Chromium 可执行文件，且完整 Playwright 配置依赖当前环境未安装的 `uvicorn`，**浏览器用例不能冒称通过**，须以 CI 结果为准。**现场 4070 WeVisOne 2B 的实际姿态分类尚未回归**，因此不能宣称已经消除所有误分类；请先用同一批床上躺卧、床外站立、角落灭火器、空床负样本在原模型配置窗“验证坐标”中逐图核验。若 2B 对长查询不支持或仍把躺卧识别为 `person`，需回到模型自身能力、原生服务查询处理及人工标注/数据微调治理，不能虚构自动重分类结果。生产/4070 服务和正式数据库/GT/模型均未在本次开发中修改；准确 Git SHA、远端 CI 应以推送后记录为准。

以下历史合同章节记录了修复前的版本行为（例如此前固定 `query` 的描述），不代表 543 新行为。

**准确基线**：`42.24.537` / `611e35d05ade6f93d9eb82e1b19f01f336d0358d`

**基线完成版本**：`42.24.538` / `1ee43b80676bafe3d9edc74711e87a8f58673b96`

**本次合同修复版本**：`42.24.539`（准确远端 SHA、CI 见推送后证据；4070 现场仍待验证）

**4070 现场空目标回包勘误版本**：`42.24.541`（准确 SHA、CI 应以新提交为准）

**Chrome 回归合同收口候选**：`42.24.542`（起点 `42.24.541 / 1a497012a64eab10c57b1a3006ea1cef517d9a6f`；提交后的 SHA、CI 以 GitHub 为准）

**唯一分支**：`feature/external-algorithm-publishing`
**生产/4070 运行环境**：未修改、未重启、未写入数据

## 一、需求与边界

在原有“模型配置”中增加 `provider_adapter=wevisone_vl`，与通用 OpenAI/火山方舟/阿里云/Ollama 并列。允许多个配置、独立启停、默认标注模型、自动标注任务选择，且不新增第二套配置库、请求中心、缓存、任务或正式 GT。

专用适配器自行完成：模型身份检查、原生 ref/box 和 JSON 检测结果解析、XYXY 坐标明确单位还原、置信度缺失状态、分割/抠图只读预览。通用 Provider 继续使用原来的严格 JSON Schema，**不**因 WeVisOne 而允许缺置信度。

用户可在**同一个模型配置窗口**选择适配方式：

- 通用模型：保留原 API 协议、结构化输出、坐标、提示词等可配置项。
- WeVisOne：仅要求配置名称、模型 ID、服务地址（可选已有密钥）、启用/默认状态。原生协议/输入坐标和内部像素转换由专用 Provider 管理；高级通用字段隐藏。
- 连接测试只验证服务、当前模型和协议可解析；白底样本返回 `boxes=[]` 是合法的，但**不证明识别准确、坐标准确**。
- 上传真实图在原窗口切换“检测画框 / 分割 / 抠图”；检测结果人工核实后才允许确认该配置的坐标。Mask/Alpha/透明 PNG **只是预览，不进入正式 GT**。

## 二、现有架构审计与落点

| 原能力 | 原实现 | 本轮处理 |
|---|---|---|
| 模型配置/密钥 | `app.py` v35 Model Config，`MODEL_CONFIGS_FILE`、`KeyringSecretStore` | 原路由、原文件、原密钥机制；新增适配器字段合法值、启停及唯一默认 |
| Provider | `platform_core/auto_label.py:provider_factory` | 新增明确的 `wevisone_vl` 分支；绝不识别模型名称中的关键字 |
| 通用 OpenAI/Ollama | `platform_core/providers/*vision.py` | 原有协议和请求实现不动 |
| 候选 Schema/NMS | `auto_label.py` | 专用候选 Schema 才允许 `confidence=null`；NMS 对缺值使用稳定确定性次序 |
| 任务执行 | `annotation_task_service.py` | 专用 Provider 显式接收任务冻结允许标签；缺置信度候选不参与数值阈值过滤但保留人工审核 |
| 原图坐标 | `prepare_annotation_image` / `adapt_coordinates` | 继续 EXIF 归正；专用 Provider 把原生 0-1000 按原图宽高分别还原为像素，仅返回 pixel 合同 |
| 审核/GT | CandidateStore、原人工审核、正式 GT Writer | 不更改审核提交/正式 GT 流程；未知置信度呈现“置信度未提供” |
| 前端 UI | `static/app.js` M4 实际 Owner / v35 模型列表 | 在单一原入口动态切换字段、原位测试与预览、状态列表、启停 |

### 与现有任务和保存状态的兼容

- `enabled` 对历史配置缺省为 `true`，不迁移改写老配置。
- 用户创建新任务时停用配置不可选、服务端拒绝；已冻结的任务仍遵守原 Snapshot 可恢复机制。
- 新建和正常编辑模型延用原坐标配置修订，真实样本人工确认在配置改变后失效。
- 启停只改变可用性，不推翻之前的坐标证据；将默认模型停用会同步取消默认标记。
- 新保存模型连接测试保留简短 `last_test`（成功/失败码、时间、是否空结果、模型是否加载），历史无修订模型保持原有连接测试只读合同。
- API Key 不进入响应、日志、候选原文；大图片/Base64 不用于服务端错误详情。

## 三、4070 专用服务 HTTP 合同（42.24.539 勘误；必须实机确认）

42.24.538 曾**错误假设**专用 FastAPI 接收 `image_base64/labels/prompt/model`，以及单图顶层 `mask_image_base64`。用户已明确指出实际 4070 服务不匹配。42.24.539 依照**用户报告的**现有服务字段在平台专用 Provider 中收敛，不修改通用 OpenAI/Ollama，也不修改 4070 服务。

注意：当前开发容器内**没有** `/data/ai-runtime/wevisone-service/app.py`，无法只读核对真实 FastAPI 的 Pydantic 模型、返回值、鉴权及 `model-switch`。下文 JSON 属于**根据用户描述复刻的测试夹具，不是从 4070 抓取的响应**，不能称“与实际服务源码逐字段完全一致”，也不能称“真实接口测试通过”。

`GET {root}/v1/models`

```json
{"data":[{"id":"wevisone-vl-2b"}]}
```

`POST {root}/v1/vision/detect`、`segment`、`matting`，平台专用适配器只发送：

```json
{
  "image":"data:image/jpeg;base64,<图片 Base64>",
  "query":["person"]
}
```

`query` 始终从本次任务**冻结的 canonical 标签 code 列表**生成，不发送用户可编辑的通用提示词；真实图片手动验证使用当次明确指定标签。只在专用 Provider 内做该映射。大小限制：JPEG/PNG/WebP ≤10MB，解码像素 ≤2500 万，任务标签 ≤100；拒绝未支持格式，而非自动丢弃图片。`model_name` 仍作为模型身份检查的配置，`GET /v1/models` 对其进行校验；真实服务在执行途中切换模型的风险尚待现场验证。

按用户描述，专用服务检测响应包含：

```json
{
  "coordinate_system":"xyxy_pixel",
  "boxes":[
    {"label":"person","bbox_xyxy":[128,192,640,768],"bbox_normalized":[100,200,500,800]}
  ],
  "response":"<ref>person</ref><box><100><200><500><800></box>"
}
```

`coordinate_system=xyxy_pixel` 时以 `bbox_xyxy` 为唯一权威原图像素 XYXY，**忽略仅作服务参考的 `bbox_normalized`，不再次缩放**；逐坐标校验有限数字、方向、X/Y 独立的原图尺寸边界，限制单图 300 个框，严格拒绝未知坐标系/范围外标签/无效置信度。只有显式缺少 `confidence` 才保留 `null/unavailable`，不合成概率。任务冻结标签库中的非歧义别名可映射回 canonical code；别名冲突拒绝。服务拒识、错误状态或空框与原始有目标相矛盾时失败，不转成 `[]`。

原 `ref/box`、显式 `coordinate_space=pixel|normalized_1000` 仍保留受约束的兼容分支，但对于上述实际服务形态专门优先读取 `bbox_xyxy`。

无目标可以由 `{"coordinate_system":"xyxy_pixel","boxes":[],"response":"None"}` 表达；**4070 实际回包也会使用 `"<ref>fire</ref><box>none</box>"` 表示当前 `fire` 标签无目标**。在标签允许且原生文本结构完整时，这也是合法的空目标；未知标签、非法坐标、拒识、模型失败，以及 `boxes=[]` 但原始文本含有效检测框的矛盾结果仍直接报错，不得静默折叠为合法空结果。

### 2026-11-06 现场 HTTP 核验与 42.24.541 修复

用户在 4070 `inspur` 机器上执行只读和一次合成图片检测，提供了实际终端输出（**真实 HTTP，非本地自造 mock**）：

- 服务监听 `127.0.0.1:18000`；`GET /openapi.json` 为 HTTP 200，含 `/v1/models`、`/v1/vision/detect`、`/v1/vision/segment`、`/v1/vision/matting`。
- `GET /v1/models` 为 HTTP 200，模型 ID `wevisone-vl-2b`。
- 使用 128×128 白色 JPEG，`POST /v1/vision/detect`，请求 `image` Data URI、`query=["fire"]`，HTTP 200；返回字段含 `model,width,height,response,latency_s,coordinate_system,boxes`。
- **现场原始空目标字段**如下（其余服务元信息省略）：

```json
{"coordinate_system":"xyxy_pixel","boxes":[],"response":"<ref>fire</ref><box>none</box>"}
```

42.24.540 的 `_native_boxes` 将 `<box>none</box>` 视为「目标框格式错误」；即使结构化 `boxes=[]`，外层 `normalize_detection` 也错误地无条件要求 raw 必须有框然后抛矛盾错误。42.24.541 收敛修正为：

1. 仅接受已知原生 `ref/box` 结构内的显式无目标词，标签须在当前冻结允许集合（含非歧义别名）中；普通乱写的坐标文本仍拒绝。
2. 当 `boxes=[]` 时，解析 raw 仅作矛盾检测：确实存在有效框才拒绝；合法 `<box>none</box>` 返回空列表。若结构化 `boxes` 有目标却只声明原生无目标，也明确拒绝。
3. 同标签原始文本同时声明「有目标/无目标」时拒绝，拒识/非 JSON/超时/无效坐标/未知标签仍沿用原错误路径。无目标只代表协议可解析，**不等于模型准确率通过**，更不自动入库 GT。

增加了现场真实空目标 JSON 形状的单测及 `/api/v35/model-configs/{id}/test-annotation` API 回归，先复现 RED，再修复 GREEN。**这个核验只覆盖空目标检测**；4070 服务源码、含目标/多目标实图、分割与抠图真实返回、Chrome 1920/1366/768 及任务到正式 GT 的现场完整链路仍待独立验收。平台和 WeVisOne 的现场服务/模型/业务数据均未由本轮改动。

按用户报告，分割/抠图响应的权威字段是实例数组：

```json
{
  "instances":[
    {"label":"person","mask_png":"<PNG Base64>","cutout_png":"<PNG Base64>"},
    {"label":"person","mask_png":"<PNG Base64>","cutout_png":"<PNG Base64>"}
  ]
}
```

每个实例独立核验/展示 PNG Mask 与透明前景，UI 原模型窗口原位分组展示多个目标；实例 ≤32，单个 Base64 ≤1400 万字符，总量 ≤2800 万字符；`instances=[]` 是明确无目标预览。原顶层旧预览字段仅留兼容，**分割/抠图始终不提交任何 GT、无候选提交收据**。凡实际服务字段与此不一致，须先取得现场 `app.py` 或脱敏响应，在原 Provider 内再作定向修复。

### 坐标证据

例如 1280×960 原图，原生 `<100><200><500><800>` → 像素 `(128,192,640,768)`；1920×1080 → `(192,216,960,864)`。`image_width` 与 `image_height` **分别**缩放 X、Y；`pixel` 响应不再变换；EXIF 先由原项目归正。不能从测试框通过直接得出画框正确结论。

## 四、API 改动

| API | 本轮合同 |
|---|---|
| `POST/PUT /api/v35/model-configs` | `provider_adapter=wevisone_vl`、`enabled`、原 `model_name/base_url`；专用字段服务器锁定 pixel/XYXY/top-left/auto |
| `PATCH /api/v35/model-configs/{id}/availability` | `{"enabled":true|false}`；原配置文件原锁内更新，不重建配置系统 |
| `POST /api/v35/model-configs/{id}/test-annotation` | 专用模型先 GET `/models` 确认当前加载，再 POST `/detect`，返回 `no_target / model_loaded / protocol_valid / coordinate_confirmed` 与实际结果；持久保存有限测试证据 |
| `POST /api/v35/model-configs/{id}/verify-coordinates` | 扩展 `operation=detect|segment|matting`；默认检测使用原确认收据；分割/抠图只读预览，不生成收据、不保存 GT |
| `POST /api/v35/model-configs/{id}/confirm-coordinates` | 保持原先 Revision/收据/真实框/人工确认围栏，不因协议测试通过自动确认 |

## 五、测试记录

**42.24.542 Chrome CI 红灯诊断／修复记录**（不改变 WeVisOne 接口与产品运行时代码）：

- 42.24.541 的 [Frontend Runtime Stabilization run 42173016886](https://github.com/jorsamj/aixunlianpingtai/actions/runs/42173016886) 首轮及一次失败作业重跑，均有 Chrome 浏览器分片红灯；其他 21 个工作流查询时成功。`exit code 1` 是测试进程最终退出码，不是独立的 WeVisOne HTTP 故障。
- `advanced-menu-integration.spec.mjs` 仍查找精确 `新增提示词`，实际原 UI 的提示词标签页按钮叫 `新增模板`；`model-api-protocol.spec.mjs` 查找 `新增模型`，实际模型列表按钮叫 `新增视觉模型`，保存后行操作叫 `配置` 而不是 `编辑`。同步核对 `model-and-conversion.spec.mjs` 的旧四项 Provider 预期（当前多一个可选 WeVisOne）。改为基于原面板作用域的明确可见按钮，而非修改业务 UI 适应旧测试。
- 重跑中的 `material-workflows.spec.mjs` 在 Annotorious 绘制后 `.a9s-inner` 首次位置读取得到 `null`；使用对 **非 null、正宽、正高** 的 5s 有界重试跨越 SVG 投影的 DOM 替换窗口，保留真实鼠标选框、拖拽、缩放、保存、刷新和缩略图验证，失败超过 5s 仍红灯，绝不跳过。
- 本地 `node --check` 四份浏览器用例通过，Node 全量 **1544/1544** 成功。当前环境无 Chrome 可执行文件且缺少 `uvicorn`，尚不能把本地语法和单测当作完整浏览器实测；准确新版 Chrome 和全部 CI 待精确 SHA 推送后核验。

本地已执行（本次工作区）：

- **42.24.538：Node 全量 1540/1540，Python 定向 91/91 通过**。
- **42.24.539 本地新增合同修复：Python 定向 108/108，通过**（检测 Data URI + query 请求、像素框、多个目标、拒识/HTTP 422/超时、冻结别名、图片大小、分割多实例、真实图确认与 v60 候选人工审核后才写 GT）。
- **42.24.539 Node 全量 1542/1542 通过**，其中新增 2 条专用/通用并列、单窗多实例预览的 Owner 回归。
- **42.24.539 Python 扩展定向 204/204 通过**，额外包含原 OpenAI 兼容协议、坐标合同与多批标注服务测试。
- 一次额外原 API 测试集合 `80 passed / 1 failed`，失败为 `test_auto_label_candidates_do_not_modify_annotation_until_confirmed` 仍调用已正式退休的 v47 API，当前返回预期 HTTP 410；该旧测试不在上述 89 项定向集内。本次未恢复退休路由。
- Python 编译检查、`node --check static/app.js`、`git diff --check` 通过（以最新提交前复查为准）。

- Python `test_wevisone_provider.py`：显式 factory、空目标/拒识、越界/未知类别、缺置信度、任意宽高坐标、像素不二次缩放、Mask PNG、多实例、Worker 不过滤未提供分数。
- API `test_model_configs.py`：原通用模型回归、Keyring 脱敏、专用设置强制、默认互斥、启停、模型未加载、白底样本、只读分割。
- Node 模型配置 Owner、页面请求竞态等专项回归；完整 Node 套件必须报告实际总数和结果，不以单独用例代替全量。

**明确未完成的验收**：

1. 4070 实际 `/data/ai-runtime/wevisone-service/app.py` 请求体、响应字段、鉴权和实际 `model-switch` 模型身份验收。**仍未获得现场代码与网络权限；现有夹具不是实机回包。**
2. 4070 真正“人员睡觉/遮挡/白墙”等业务样本的检测准确率与坐标偏移验证。
3. 分割/抠图的真实 Mask/Alpha/透明前景输出形状和叠图视觉验收。
4. 1920/1366/768 的真实 Chrome 截图和交互验收：Playwright Chromium 先前无法下载；本次浏览器扩展不连接，云端 Chrome 打开本地调试页面返回 `ERR_CONNECTION_REFUSED`。不能用 DOM/Node 结果冒充视觉通过。
5. 新提交准确 SHA 的 GitHub CI、A800/4070 生产升级与数据性能：尚未完成。

因此当前阶段可标注为 **平台合同修复 + 用户报告字段的合成协议测试**，不能宣称 P0 实机/真实 UI 全部验收通过。用户须提供脱敏 `/data/ai-runtime/wevisone-service/app.py` 或开放一个授权的测试实例，才能完成服务真实合同审计。

## 六、4070 上线与回滚要求

正式上线前由运维在目标服务器只读比对 `/data/ai-runtime/wevisone-service/app.py` 的 FastAPI 路由与请求体；对齐上述合同后以真实图片分别测检测/分割/抠图。任何变更前单独备份原 `app.py`、服务配置和 `model-switch` 文件，不改 CUDA/PyTorch/vLLM/已有 Qwen 环境。若适配服务调整，使用单独服务副本预发布、确认结果后受控切换，并保留按文件与服务单元回滚。平台原版本可通过原部署机制回退到 `42.24.537 / 611e35d`，正式 GT 不涉及迁移或回滚。

## 七、待完成验收清单

- [x] 基线 Git SHA 与 VERSION 精确核验
- [x] 专用适配与通用并列；未提供置信度不伪造
- [x] 本地任务候选保持人工审核合同，分割/抠图不写 GT
- [x] 既有配置/安全储存/前端原 Owner 复用
- [x] 修复平台与用户报告的 WeVisOne FastAPI 请求/响应字段不一致
- [x] 多实例只读预览，未评分候选进入人工审核后才允许 GT 入库（合成回归）
- [ ] 4070 服务 `app.py` 源码逐字段审计和真实 HTTP 请求/响应确认
- [ ] 真实含目标图的框位置、分割、抠图人工确认
- [ ] 1920px、1366px、768px 真实浏览器截图并复测
- [ ] 精确新 SHA 的全量 CI 和真实生产/UAT 验收
