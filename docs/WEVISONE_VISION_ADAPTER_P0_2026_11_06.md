# 畅联云算法训练平台｜WeVisOne-VL 可选专用适配器 P0

**开发日期**：2026-11-06

**准确基线**：`42.24.537` / `611e35d05ade6f93d9eb82e1b19f01f336d0358d`

**开发版本**：`42.24.538`（待 CI/现场复核）

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

## 三、4070 专用服务 HTTP 合同（必须实机确认）

本轮代码仅有平台仓库，**没有** `/data/ai-runtime/wevisone-service/app.py` 的实际内容，也没有访问 4070 的权限。腾讯官方模型代码定义原生结果 token，但**不定义用户现有 FastAPI 服务的 HTTP JSON 请求字段**。以下是本轮平台侧明确采用的专用服务合同，不能声称用户已有服务已经符合：

`GET {root}/v1/models`

```json
{"data":[{"id":"wevisone-vl-2b"}]}
```

`POST {root}/v1/vision/detect`、`segment`、`matting`，请求体：

```json
{
  "model":"wevisone-vl-2b",
  "image_base64":"<纯 Base64 编码的 JPEG/PNG>",
  "labels":["person"],
  "prompt":"<业务说明>"
}
```

检测成功响应为以下任一明确形式：

```json
{"coordinate_space":"normalized_1000","boxes":[{"label":"person","bbox":[100,200,500,800]}]}
```

```json
{"coordinate_space":"pixel","boxes":[{"label":"person","x1":128,"y1":192,"x2":640,"y2":768,"confidence":0.83}]}
```

```json
{"response":"<ref>person</ref><box><100><200><500><800></box>"}
```

无目标必须明确为 `{"boxes":[]}`、`{"no_target":true}` 或 `{"response":"None"}`。未知结构、拒识和模型失败直接报错；不能折叠为合法空结果。JSON 检测有框必须提供 `coordinate_space`，禁止根据数值大小猜坐标单位。原生 ref/box 唯一按 0-1000 处理。

分割/抠图成功响应可提供 `mask_image_base64`、`alpha_matte_base64`、`foreground_base64` 的 PNG Base64 任意子集；至少一张图，禁止任意 HTML/SVG/外链图片。最大图像限制与只读预览限制在平台端验证。实际 4070 服务如果使用不同字段，须在它的**专用**服务端对齐或根据其真实代码调整此 Provider，不能改变通用适配器。

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

本地已执行（本次工作区）：

- **Node 全量：1540/1540 通过**，包含模型配置 Owner 与导航竞态；原测试曾要求打开第二层结果弹窗，已按新同窗行为更新断言。
- **Python 定向：91/91 通过**（模型配置 API、WeVisOne 多目标/超时、原 AI Task Runtime/冻结配置/持久候选审核）。
- 一次额外原 API 测试集合 `80 passed / 1 failed`，失败为 `test_auto_label_candidates_do_not_modify_annotation_until_confirmed` 仍调用已正式退休的 v47 API，当前返回预期 HTTP 410；该旧测试不在上述 89 项定向集内。本次未恢复退休路由。
- Python 编译检查、`node --check static/app.js`、`git diff --check` 通过（以最新提交前复查为准）。

- Python `test_wevisone_provider.py`：显式 factory、空目标/拒识、越界/未知类别、缺置信度、任意宽高坐标、像素不二次缩放、Mask PNG、Worker 不过滤未提供分数。
- API `test_model_configs.py`：原通用模型回归、Keyring 脱敏、专用设置强制、默认互斥、启停、模型未加载、白底样本、只读分割。
- Node 模型配置 Owner、页面请求竞态等专项回归；完整 Node 套件必须报告实际总数和结果，不以单独用例代替全量。

**明确未完成的验收**：

1. 4070 实际 `/data/ai-runtime/wevisone-service/app.py` 请求体、响应字段、鉴权和实际 `model-switch` 模型身份验收。未获得现场代码与网络权限。
2. 4070 真正“人员睡觉/遮挡/白墙”等业务样本的检测准确率与坐标偏移验证。
3. 分割/抠图的真实 Mask/Alpha/透明前景输出形状和叠图视觉验收。
4. 1920/1366/768 的真实 Chrome 截图和交互验收：当前环境 Playwright Chromium 下载返回 0 MiB 非 ZIP，无法获得浏览器二进制。不能用 DOM/Node 结果冒充视觉通过。
5. 新提交准确 SHA 的 GitHub CI、A800/4070 生产升级与数据性能：尚未完成。

因此当前阶段可标注为 **代码实现 + 合成协议测试**，不能宣称 P0 实机/真实 UI 全部验收通过。

## 六、4070 上线与回滚要求

正式上线前由运维在目标服务器只读比对 `/data/ai-runtime/wevisone-service/app.py` 的 FastAPI 路由与请求体；对齐上述合同后以真实图片分别测检测/分割/抠图。任何变更前单独备份原 `app.py`、服务配置和 `model-switch` 文件，不改 CUDA/PyTorch/vLLM/已有 Qwen 环境。若适配服务调整，使用单独服务副本预发布、确认结果后受控切换，并保留按文件与服务单元回滚。平台原版本可通过原部署机制回退到 `42.24.537 / 611e35d`，正式 GT 不涉及迁移或回滚。

## 七、待完成验收清单

- [x] 基线 Git SHA 与 VERSION 精确核验
- [x] 专用适配与通用并列；未提供置信度不伪造
- [x] 本地任务候选保持人工审核合同，分割/抠图不写 GT
- [x] 既有配置/安全储存/前端原 Owner 复用
- [ ] 4070 服务 HTTP 请求/响应真实确认
- [ ] 真实含目标图的框位置、分割、抠图人工确认
- [ ] 1920px、1366px、768px 真实浏览器截图并复测
- [ ] 精确新 SHA 的全量 CI 和真实生产/UAT 验收
