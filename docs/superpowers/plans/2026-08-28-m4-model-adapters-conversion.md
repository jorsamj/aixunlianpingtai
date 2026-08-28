# M4 本地/在线模型自动标注与真实模型转换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持火山、千问、本地 OpenAI 兼容视觉服务和 Ollama 生成可审核候选标注，并通过真实厂商工具转换 Atlas、RK3588/RK3568 和 NVIDIA 产物。

**Architecture:** 模型配置、Secret、提示词、协议适配和候选标注分别建模；所有提供商输出统一 CandidateAnnotation。转换使用 PT→ONNX→厂商编译器两阶段流水线，产物带完整 manifest，并区分“已转换”和“已实机验证”。

**Tech Stack:** requests/httpx、Pydantic、keyring、火山方舟兼容 API、阿里云百炼兼容 API、vLLM、Ollama、ONNX、ATC、RKNN-Toolkit2、TensorRT、pytest、Playwright。

---

## 文件结构

- Create: `platform_core/secrets.py`
- Create: `platform_core/prompts.py`
- Create: `platform_core/providers/base.py`
- Create: `platform_core/providers/openai_vision.py`
- Create: `platform_core/providers/ollama_vision.py`
- Create: `platform_core/auto_label.py`
- Create: `platform_core/conversion.py`
- Create: `static/modules/model_config.js`
- Create: `static/modules/auto_annotation.js`
- Create: `static/modules/conversion.js`
- Modify: `requirements.txt` — 增加安全 Secret 后端依赖。
- Modify: `app.py:7014-7378` — 模型配置与提示词调用服务。
- Modify: `app.py:9743-9874` — 自动标注任务调用适配层。
- Modify: `app.py:7897-8565` — 转换资源与任务调用转换服务。
- Modify: `deployment_worker.py`
- Modify: `rknn_convert_runner.py`
- Test: `tests/unit/test_secrets.py`
- Test: `tests/unit/test_prompts.py`
- Test: `tests/unit/test_provider_parsing.py`
- Test: `tests/unit/test_conversion.py`
- Test: `tests/api/test_model_configs.py`
- Test: `tests/api/test_auto_label_candidates.py`
- Test: `tests/api/test_conversion_jobs.py`
- Test: `tests/integration/test_fake_vision_provider.py`
- Test: `tests/hardware/test_vendor_conversion.py`
- Test: `tests/browser/model-and-conversion.spec.mjs`

### Task 1: Secret 不进入 JSON、响应或日志

- [ ] **Step 1: 写失败 Secret 测试**

`tests/unit/test_secrets.py`:

```python
from platform_core.secrets import MemorySecretStore, secret_ref


def test_secret_reference_does_not_contain_value():
    store = MemorySecretStore()
    ref = secret_ref("model-config", "volc-1")
    store.set(ref, "secret-token")
    assert store.get(ref) == "secret-token"
    assert "secret-token" not in ref


def test_masked_value_never_returns_full_secret():
    store = MemorySecretStore()
    ref = secret_ref("model-config", "qwen-1")
    store.set(ref, "sk-1234567890")
    assert store.masked(ref) == "sk-****7890"
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_secrets.py -v
```

- [ ] **Step 3: 实现 SecretStore**

`platform_core/secrets.py` 定义 `SecretStore` protocol、测试用 `MemorySecretStore` 和 Windows `KeyringSecretStore`。配置 JSON 只保存 `secret_ref`。Linux 第二阶段允许 `env:ARK_API_KEY` 等环境变量引用。

`requirements.txt` 追加并固定主版本：

```text
keyring>=25.6,<26
```

- [ ] **Step 4: 修改模型配置保存接口**

接收 `api_key` 时立即写入 SecretStore；返回值只包含 `has_api_key` 和 masked 值。日志过滤 `Authorization`、`api_key`、Bearer token。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_secrets.py -v
git add platform_core/secrets.py app.py requirements.txt tests/unit/test_secrets.py
git commit -m "feat: store model credentials outside json and logs"
```

### Task 2: 提示词模板版本化并注入受控变量

- [ ] **Step 1: 写失败模板测试**

`tests/unit/test_prompts.py`:

```python
import pytest
from platform_core.prompts import render_prompt


def test_prompt_injects_labels_and_image_size():
    result = render_prompt(
        "检测 {{labels_json}}，图片尺寸 {{image_width}}x{{image_height}}。{{output_schema}}",
        labels=[{"code":"fire","display_name_zh":"明火"}],
        width=640,
        height=480,
        business_instruction="只标注可见火焰",
    )
    assert '"code": "fire"' in result
    assert "640x480" in result
    assert '"boxes"' in result


def test_unknown_template_variable_is_rejected():
    with pytest.raises(ValueError, match="未知模板变量"):
        render_prompt("{{api_key}}", labels=[], width=1, height=1, business_instruction="")
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_prompts.py -v
```

- [ ] **Step 3: 实现严格变量白名单与版本 hash**

允许变量仅为 `labels_json`、`image_width`、`image_height`、`business_instruction`、`output_schema`。模板保存时生成不可变版本 ID，任务记录模板 ID 与版本。

- [ ] **Step 4: 修改 `/api/v35/prompt-templates` 使用模板服务**

提供预览端点，预览不发起模型调用。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_prompts.py -v
git add platform_core/prompts.py app.py tests/unit/test_prompts.py
git commit -m "feat: version safe auto-annotation prompt templates"
```

### Task 3: 统一候选标注协议和严格解析

- [ ] **Step 1: 写失败解析测试**

`tests/unit/test_provider_parsing.py`:

```python
import pytest
from platform_core.auto_label import parse_candidate_response


def test_valid_boxes_are_normalized():
    result = parse_candidate_response(
        '{"boxes":[{"label":"fire","confidence":0.9,"x1":10,"y1":20,"x2":100,"y2":120}]}',
        width=640,
        height=480,
        label_ids={"fire":0},
    )
    assert result[0]["class_id"] == 0
    assert result[0]["label"] == "fire"


def test_unknown_label_and_out_of_bounds_are_rejected():
    with pytest.raises(ValueError):
        parse_candidate_response(
            '{"boxes":[{"label":"unknown","confidence":0.9,"x1":-1,"y1":0,"x2":700,"y2":10}]}',
            width=640,
            height=480,
            label_ids={"fire":0},
        )
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_provider_parsing.py -v
```

- [ ] **Step 3: 实现 CandidateAnnotation Pydantic 模型**

协议字段为 `label`、`confidence`、`x1`、`y1`、`x2`、`y2`。解析器允许移除模型常见的外层 Markdown fence，但最终内容必须是一个 JSON object；未知标签和越界框按图片失败，不静默丢弃。

- [ ] **Step 4: 加入 NMS/重复框规则并保留原始响应 hash**

任务结果记录 `raw_response_hash`、解析错误、耗时和 provider request ID，不保存敏感 header。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_provider_parsing.py -v
git add platform_core/auto_label.py platform_core/providers/base.py tests/unit/test_provider_parsing.py
git commit -m "feat: validate provider output as candidate annotations"
```

### Task 4: 火山、千问和本地 OpenAI 兼容适配器

- [ ] **Step 1: 写失败集成测试服务器**

`tests/integration/test_fake_vision_provider.py` 使用本地 FastAPI 假服务接收 `messages`、图片 data URL、prompt 和 `response_format`，返回合法 boxes JSON；测试适配器发送 Bearer token、解析响应并不泄漏 token。

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/integration/test_fake_vision_provider.py -v
```

- [ ] **Step 3: 实现 `OpenAICompatibleVisionProvider`**

配置预设：

```python
PRESETS = {
    "volcengine_ark": {"base_url":"https://ark.cn-beijing.volces.com/api/v3", "api":"chat_completions"},
    "aliyun_qwen": {"base_url":"", "api":"chat_completions"},
    "local_openai": {"base_url":"http://127.0.0.1:8000/v1", "api":"chat_completions"},
}
```

千问 Base URL 必须由用户按地域/Workspace 配置；火山和千问都优先请求 JSON Schema，服务不支持时回退到 JSON Object + 服务端严格校验。

- [ ] **Step 4: 增加测试连接接口**

测试连接必须返回 `reachable`、`latency_ms`、`provider`、`model`、`raw_preview`、`parsed_boxes` 和明确错误，不写 annotation。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/integration/test_fake_vision_provider.py tests/api/test_model_configs.py -v
git add platform_core/providers app.py tests/integration tests/api/test_model_configs.py
git commit -m "feat: connect volc qwen and local openai vision providers"
```

### Task 5: Ollama 本地视觉适配器

- [ ] **Step 1: 扩展假服务测试覆盖 `/api/chat` 的 `images` 与 `format` JSON Schema**

- [ ] **Step 2: 运行并确认 Ollama 用例失败**

```powershell
python -m pytest tests/integration/test_fake_vision_provider.py -k ollama -v
```

- [ ] **Step 3: 实现 `OllamaVisionProvider`**

默认 Base URL `http://127.0.0.1:11434`；请求 `stream:false`，图片使用 Base64，`format` 传 boxes JSON Schema。模型名不写死。

- [ ] **Step 4: 对未启动 Ollama 返回可操作错误**

错误 code 为 `MODEL_SERVICE_UNREACHABLE`，solution 包含检查本地服务地址和模型是否已加载，不自动下载模型。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/integration/test_fake_vision_provider.py -v
git add platform_core/providers/ollama_vision.py tests/integration/test_fake_vision_provider.py
git commit -m "feat: support local ollama vision annotations"
```

### Task 6: 自动标注任务只产生候选，确认后才写入

- [ ] **Step 1: 写失败 API 测试**

`tests/api/test_auto_label_candidates.py`:

```python
import time

import pytest


class FakeVisionProvider:
    def annotate(self, *, image_bytes, prompt, output_schema):
        return {
            "text": '{"boxes":[{"label":"fire","confidence":0.95,"x1":10,"y1":10,"x2":80,"y2":80}]}',
            "request_id": "fake-request-1",
        }


@pytest.fixture
def fake_provider(monkeypatch):
    monkeypatch.setattr(
        "platform_core.auto_label.provider_factory",
        lambda provider_id: FakeVisionProvider(),
    )
    return "fake-provider"


def wait_for_task(client, pid, task_id, expected, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v47/projects/{pid}/ai-label-tasks/{task_id}/result")
        response.raise_for_status()
        body = response.json()
        if body.get("status") == expected:
            return body
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not reach {expected}")


def test_auto_label_candidates_do_not_modify_annotation_until_confirmed(
    client, seeded_project, fake_provider
):
    pid, image = seeded_project
    task = client.post(f"/api/v47/projects/{pid}/ai-label-tasks", json={
        "image_ids":[image["id"]], "labels_text":"fire", "provider_id":fake_provider, "prompt_template_id":"default"
    }).json()
    wait_for_task(client, pid, task["id"], "awaiting_confirmation")
    assert client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()["boxes"] == []
    result = client.get(f"/api/v47/projects/{pid}/ai-label-tasks/{task['id']}/result").json()
    assert result["result"]["items"][0]["boxes"]
    client.post(f"/api/v47/projects/{pid}/ai-label-tasks/{task['id']}/confirm", json={"image_ids":[image["id"]]})
    assert client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()["boxes"]
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/api/test_auto_label_candidates.py -v
```

- [ ] **Step 3: 重构 `app.py:9743-9874`**

任务状态为 queued → running → awaiting_confirmation → done/failed/stopped。结果逐图记录成功、无目标、解析失败和接口失败。确认接口调用 M2 annotation 服务。`platform_core.auto_label.provider_factory(provider_id)` 是唯一适配器创建入口，生产环境从配置和 SecretStore 构建，测试可安全替换为本地假服务。

- [ ] **Step 4: 加入批量前预览**

正式任务创建接口支持 `preview_count`；默认先跑少量图片，用户确认后再启动完整批次。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/api/test_auto_label_candidates.py -v
git add platform_core/auto_label.py app.py tests/api/test_auto_label_candidates.py
git commit -m "fix: keep ai labels as reviewable candidates until confirmation"
```

### Task 7: 转换 manifest 和目标参数校验

- [ ] **Step 1: 写失败转换单元测试**

`tests/unit/test_conversion.py`:

```python
import pytest
from platform_core.conversion import validate_target, build_manifest


def test_rknn_chip_must_be_explicit():
    with pytest.raises(ValueError, match="rk3588|rk3568"):
        validate_target("rockchip", {})


def test_manifest_records_source_tool_and_validation_state():
    manifest = build_manifest(
        source={"version_id":"v1","sha256":"abc"},
        target={"kind":"rockchip","chip":"rk3588"},
        tool={"name":"rknn-toolkit2","version":"2.3.2"},
        outputs=[{"name":"model.rknn","sha256":"def"}],
        hardware_verified=False,
    )
    assert manifest["target"]["chip"] == "rk3588"
    assert manifest["status"] == "converted_unverified"
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_conversion.py -v
```

- [ ] **Step 3: 实现转换参数验证与 manifest**

Atlas 必须有 `soc_version`；Rockchip 必须明确 `rk3588` 或 `rk3568`；TensorRT 必须记录精度和目标环境。INT8 必须有 calibration Snapshot。

- [ ] **Step 4: 转换任务保存源模型和 ONNX SHA-256**

产物目录必须包含 `manifest.json`、技术日志和真实输出文件。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_conversion.py -v
git add platform_core/conversion.py app.py tests/unit/test_conversion.py
git commit -m "feat: validate hardware targets and trace conversion manifests"
```

### Task 8: 厂商真实编译器与明确失败

- [ ] **Step 1: 写失败 API 测试**

`tests/api/test_conversion_jobs.py` 使用临时 PATH，断言缺少 ATC/RKNN/TensorRT 时任务为 failed，code 分别为 `ATC_NOT_FOUND`、`RKNN_TOOLKIT_NOT_FOUND`、`TENSORRT_NOT_FOUND`，且目标产物不存在。

- [ ] **Step 2: 运行并确认旧错误信息或假产物导致失败**

```powershell
python -m pytest tests/api/test_conversion_jobs.py -v
```

- [ ] **Step 3: 修改 `deployment_worker.py` 与 `rknn_convert_runner.py`**

执行链：验证源 PT → 真实导出 ONNX → ONNX Runtime 对照 → 调用 ATC/RKNN-Toolkit2/trtexec → 验证产物非空 → 写 manifest。任何子进程非零退出都失败并保留 stdout/stderr。

- [ ] **Step 4: 增加硬件标记测试**

`tests/hardware/test_vendor_conversion.py` 使用 pytest marker `hardware`：仅在对应 SDK 环境变量明确提供时执行真实转换；产物必须可被厂商工具加载。未提供时不算通过，只在普通回归中验证明确失败路径。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/api/test_conversion_jobs.py -v
git add deployment_worker.py rknn_convert_runner.py platform_core/conversion.py tests/api/test_conversion_jobs.py tests/hardware/test_vendor_conversion.py
git commit -m "fix: require real vendor compiler outputs"
```

### Task 9: 模型配置、候选审核和转换前端

- [ ] **Step 1: 写浏览器失败测试**

`tests/browser/model-and-conversion.spec.mjs` 断言：配置中心可选择火山、千问、本地 OpenAI、Ollama；可编辑提示词并测试图片；API Key 不回显；自动标注展示候选框并需确认；转换必须选择 Atlas soc、RK3588/RK3568 或 TensorRT 参数。

- [ ] **Step 2: 运行并确认失败**

```powershell
npx playwright test tests/browser/model-and-conversion.spec.mjs
```

- [ ] **Step 3: 实现 `model_config.js` 与 `auto_annotation.js`**

基础模式只显示提供商、模型、提示词和测试连接；高级模式显示 Base URL、超时、重试和并发。测试结果展示候选框，但不写正式 annotation。

- [ ] **Step 4: 实现 `conversion.js`**

转换页面先显示能力矩阵和资源状态；缺 SDK 时按钮保留但点击显示明确解决方式。版本行显示所有转换记录、产物、manifest 和“已转换/已实机验证”状态。

- [ ] **Step 5: 运行并提交**

```powershell
npm test
npx playwright test tests/browser/model-and-conversion.spec.mjs
git add static tests/browser/model-and-conversion.spec.mjs
git commit -m "feat: configure vision providers review candidates and launch real conversion"
```

### Task 10: M4 完整验证

- [ ] **Step 1: 运行假服务自动标注闭环**

```powershell
python -m pytest tests/unit/test_secrets.py tests/unit/test_prompts.py tests/unit/test_provider_parsing.py tests/integration/test_fake_vision_provider.py tests/api/test_model_configs.py tests/api/test_auto_label_candidates.py -v
```

- [ ] **Step 2: 运行转换失败与 manifest 回归**

```powershell
python -m pytest tests/unit/test_conversion.py tests/api/test_conversion_jobs.py -v
```

- [ ] **Step 3: 使用用户提供的火山或千问测试凭据做一次手工连接测试**

只在用户于配置 UI 中输入密钥后执行；记录脱敏 provider、model、请求 ID、延迟、解析框数和结果截图，不读取或复制密钥。

- [ ] **Step 4: 在具备对应 SDK 的转换资源运行硬件测试**

```powershell
python -m pytest tests/hardware/test_vendor_conversion.py -m hardware -v -s
```

Expected: 只对实际已配置环境宣称通过；未提供 SDK 的目标保持“未实机验证”。

- [ ] **Step 5: 运行浏览器回归并提交 M4**

```powershell
npx playwright test tests/browser/model-and-conversion.spec.mjs
git add .
git commit -m "test: verify provider candidates secrets and vendor conversion contracts"
```

## M4 验收门禁

- 火山、千问、本地 OpenAI 兼容服务和 Ollama 均有真实连接适配器。
- 提示词可配置、版本化和预览。
- API Key 不在 JSON、响应和日志中泄漏。
- 模型输出先成为候选，确认后才写 annotation。
- Atlas、RK3588、RK3568 和 TensorRT 只调用真实 SDK。
- 缺 SDK 时明确失败，无占位产物。
- 产物可追溯源版本、ONNX、参数、工具版本和验证状态。
