# 推理、转换 Worker 与厂商 Runtime 闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成通过公共持久任务层调度的部署测试与模型转换 Worker，使 PT、ONNX、TensorRT Engine、Atlas OM、Rockchip RKNN、Sophon BModel 按真实 Runtime 推理，并以可审计命令证据、产物哈希和明确环境/硬件门禁交付。

**Architecture:** 直接消费 `platform_core/task_runtime` 的 `TaskRepository`、`WorkerContext`、`ArtifactStore`、`TaskKind` 和 `TaskStatus`，API 只校验并入队，Worker 按 capability claim 任务。部署域分为共享结果契约、RuntimeAdapter registry、`BaseConverter` + ONNX 准备层 + 四个厂商 ConverterAdapter、资源快照和远程节点协议；厂商 SDK 只存在于隔离 Python/系统工具链中，主平台通过结构化子进程协议调用。

**Tech Stack:** Python 3.11、FastAPI、Pydantic/dataclasses、Pillow/NumPy、Ultralytics、ONNX Runtime、TensorRT、CANN AscendCL、RKNN Runtime/Lite2、Sophon Sail/BMRuntime、pytest、Playwright、PowerShell、Linux shell。

---

## 执行前提与公共接口

本计划不创建第二套任务状态或任务仓库。执行前必须已有：

- `platform_core/task_runtime/models.py`：`TaskStatus` 含 `QUEUED/RUNNING/AWAITING_CONFIRMATION/PARTIAL_SUCCESS/SUCCEEDED/CANCEL_REQUESTED/CANCELLED/FAILED/BLOCKED_BY_ENVIRONMENT/BLOCKED_BY_HARDWARE`；`TaskKind` 至少含 `MODEL_CONVERSION/DEPLOYMENT_TEST`。
- `TaskRepository` 精确方法：`create/get/list/claim_next/heartbeat/request_cancel/finish/retry/release_expired`，签名以公共任务层计划为准。
- `WorkerContext` 提供 `task/lease/repository/artifacts`、`cancel_requested()`、`load_checkpoint()`、`save_checkpoint()`。
- `ArtifactStore` 提供 `atomic_write_json/read_json/append_log/artifact_path`，所有路径由 task id 与相对路径组成并拒绝 traversal。

若上述模块尚未合入，先执行公共任务层计划；本计划的测试应因缺少公共类型而红灯，不得在部署目录复制兼容实现。

## 文件结构

- Create: `platform_core/deployment/contracts.py` — 命令、文件、检测框、四段耗时和推理结果契约。
- Create: `platform_core/deployment/command_runner.py` — 分离 stdout/stderr 并记录 exit code、UTC 时间、耗时和版本。
- Create: `platform_core/deployment/preprocess.py` — letterbox、RGB/BGR、归一化、NCHW 预处理。
- Create: `platform_core/deployment/postprocess.py` — YOLO 导出张量解码、NMS 和坐标还原。
- Create: `platform_core/deployment/runtimes/base.py`
- Create: `platform_core/deployment/runtimes/ultralytics_runtime.py`
- Create: `platform_core/deployment/runtimes/onnx_runtime.py`
- Create: `platform_core/deployment/runtimes/vendor_runtime.py`
- Create: `platform_core/deployment/runtimes/registry.py`
- Create: `platform_core/deployment/runtimes/cache.py` — 模型 SHA、Runtime 版本和资源 fingerprint 驱动的进程内 LRU。
- Create: `runtime_runners/tensorrt_runner.py`
- Create: `runtime_runners/ascend_runner.py`
- Create: `runtime_runners/rknn_runner.py`
- Create: `runtime_runners/sophon_runner.py`
- Create: `platform_core/deployment/converters/base.py`
- Create: `platform_core/deployment/converters/onnx_converter.py`
- Create: `platform_core/deployment/converters/tensorrt_converter.py`
- Create: `platform_core/deployment/converters/ascend_converter.py`
- Create: `platform_core/deployment/converters/rockchip_converter.py`
- Create: `platform_core/deployment/converters/sophon_converter.py`
- Create: `platform_core/deployment/converters/registry.py`
- Create: `platform_core/deployment/resources.py` — capability、resource revision/fingerprint 和平台路由。
- Create: `platform_core/deployment/task_handlers.py` — `MODEL_CONVERSION` 与 `DEPLOYMENT_TEST` handler。
- Create: `deployment_test_worker.py` — 公共 Worker 的部署测试入口。
- Modify: `deployment_worker.py:1-587` — 变为公共 Worker 的模型转换入口并调用 Converter registry。
- Modify: `platform_core/conversion.py:1-87` — 保留兼容导出，转发到新契约/Converter。
- Modify: `deploy_plugins/manager.py:1-43` — 插件元数据绑定 converter/runtime key 和 capability 约束。
- Modify: `app.py:6422-6698, 9074-9775, 9983-10098, 10184-10226` — 入队、查询、取消、资源 revision 和结果 API。
- Modify: `remote_deploy_server.py:1-190` — 全接口鉴权、远程 claim/恢复、密钥脱敏、TLS 提醒和哈希复验。
- Modify: `static/app.js:660-804, 1667-1832, 2897-2981, 3659-3667` — 部署测试页、阶段进度、状态门禁和资源缓存 revision。
- Create: `static/modules/deployment-test.js`
- Modify: `requirements.txt` — 不加入厂商 SDK；仅保留平台安全依赖。
- Modify: `remote_deploy_config.example.json` — TLS、隔离环境和 capability 示例。
- Modify: `README.md:98-end` — 分环境运行与验收命令。
- Create: `tests/unit/test_deployment_contracts.py`
- Create: `tests/unit/test_command_runner.py`
- Create: `tests/unit/test_runtime_registry.py`
- Create: `tests/unit/test_runtime_cache.py`
- Create: `tests/unit/test_preprocess_postprocess.py`
- Create: `tests/unit/test_converter_adapters.py`
- Create: `tests/unit/test_deploy_resource_revision.py`
- Create: `tests/api/test_deployment_test_jobs.py`
- Modify: `tests/api/test_conversion_jobs.py`
- Create: `tests/api/test_remote_deploy_security.py`
- Create: `tests/integration/test_remote_deploy_recovery.py`
- Create: `tests/e2e/test_real_deployment_inference.py`
- Modify: `tests/hardware/test_vendor_conversion.py`
- Create: `tests/hardware/test_vendor_runtime.py`
- Modify: `tests/browser/model-and-conversion.spec.mjs`
- Modify: `pytest.ini:1-4`

### Task 1: 建立命令、文件和推理结果契约

**Files:**
- Create: `platform_core/deployment/contracts.py`
- Create: `tests/unit/test_deployment_contracts.py`

- [ ] **Step 1: 写失败契约测试**

```python
from pathlib import Path

from platform_core.deployment.contracts import (
    Detection,
    FileEvidence,
    InferenceTimings,
    RuntimeResult,
)


def test_file_evidence_contains_size_and_sha256(tmp_path: Path):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"real-model")
    row = FileEvidence.from_path(path, role="output").to_dict()
    assert row["size_bytes"] == 10
    assert len(row["sha256"]) == 64


def test_runtime_result_requires_four_non_negative_timings():
    result = RuntimeResult(
        runtime="onnxruntime",
        runtime_version="1.20.1",
        model=FileEvidence(name="m.onnx", size_bytes=1, sha256="a" * 64, role="input"),
        image=FileEvidence(name="in.jpg", size_bytes=1, sha256="b" * 64, role="input"),
        result_image=FileEvidence(name="out.jpg", size_bytes=1, sha256="c" * 64, role="output"),
        detections=[Detection(class_id=0, label="fire", confidence=.9, x1=1, y1=2, x2=3, y2=4)],
        timings=InferenceTimings(preprocess_ms=1, inference_ms=2, postprocess_ms=3, total_ms=6),
        input_spec={"layout": "NCHW", "dtype": "float32"},
        output_spec={"names": ["output0"]},
    )
    assert result.to_dict()["detections"][0]["label"] == "fire"
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/unit/test_deployment_contracts.py -v`  
Expected: FAIL with `ModuleNotFoundError: platform_core.deployment`.

- [ ] **Step 3: 实现不可变契约与校验**

```python
@dataclass(frozen=True)
class InferenceTimings:
    preprocess_ms: float
    inference_ms: float
    postprocess_ms: float
    total_ms: float

    def __post_init__(self):
        values = (self.preprocess_ms, self.inference_ms, self.postprocess_ms, self.total_ms)
        if any(value < 0 for value in values):
            raise ValueError("推理耗时不能为负数")
        if self.total_ms + 1e-6 < sum(values[:3]):
            raise ValueError("total_ms 不能小于三个阶段耗时之和")


@dataclass(frozen=True)
class FileEvidence:
    name: str
    size_bytes: int
    sha256: str
    role: str

    @classmethod
    def from_path(cls, path: Path, *, role: str):
        resolved = Path(path).resolve()
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            raise ValueError(f"证据文件不存在或为空：{resolved.name}")
        return cls(resolved.name, resolved.stat().st_size, sha256_file(resolved), role)

    def to_dict(self):
        return asdict(self)
```

同文件完整定义 `CommandResult`、`Detection`、`RuntimeRequest`、`RuntimeResult`、`ConversionRequest`、`ConversionResult`、`ConversionOutcome`。`RuntimeRequest` 字段固定为 `model_path/image_path/output_path/labels/input_size/confidence/iou`。`RuntimeResult.to_dict()` 先用 `dataclasses.asdict`，再把 `timings` 规范化为 `timings_ms={preprocess,inference,postprocess,total}`；文件只输出 evidence 和 ArtifactStore 相对引用，不得把本机绝对路径或密钥写入公共响应。

- [ ] **Step 4: 运行绿灯并提交**

Run: `python -m pytest tests/unit/test_deployment_contracts.py -v`  
Expected: `2 passed`.

```powershell
git add platform_core/deployment/contracts.py tests/unit/test_deployment_contracts.py
git commit -m "feat: define deployment evidence contracts"
```

### Task 2: 结构化采集 stdout、stderr、exit code、时间和工具版本

**Files:**
- Create: `platform_core/deployment/command_runner.py`
- Create: `tests/unit/test_command_runner.py`

- [ ] **Step 1: 写失败命令采集测试**

```python
import sys

from platform_core.deployment.command_runner import run_command


def test_command_result_keeps_stdout_and_stderr_separate():
    result = run_command([
        sys.executable, "-c",
        "import sys; print('OUT'); print('ERR', file=sys.stderr); raise SystemExit(7)",
    ], tool_name="fixture", tool_version="1.2.3")
    assert result.exit_code == 7
    assert result.stdout.strip() == "OUT"
    assert result.stderr.strip() == "ERR"
    assert result.duration_ms >= 0
    assert result.started_at.endswith("+00:00")
    assert result.finished_at.endswith("+00:00")
    assert result.tool_version == "1.2.3"
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/unit/test_command_runner.py -v`  
Expected: FAIL importing `run_command`.

- [ ] **Step 3: 实现唯一子进程入口**

```python
def run_command(argv, *, tool_name, tool_version, cwd=None, env=None, timeout=None):
    started_wall = datetime.now(timezone.utc)
    started = time.perf_counter()
    completed = subprocess.run(
        [str(value) for value in argv], cwd=str(cwd) if cwd else None,
        env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, shell=False,
    )
    finished_wall = datetime.now(timezone.utc)
    return CommandResult(
        argv=[str(value) for value in argv], cwd=str(Path(cwd).resolve()) if cwd else "",
        stdout=completed.stdout or "", stderr=completed.stderr or "",
        exit_code=completed.returncode,
        started_at=started_wall.isoformat(), finished_at=finished_wall.isoformat(),
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        tool_name=tool_name, tool_version=tool_version,
    )
```

增加 `require_success(result)`，非零时抛出包含 `exit_code` 与 stderr 尾部的 `CommandExecutionError`；日志写入前对 `Authorization`、`X-API-Key`、Bearer 和 SecretStore 值做脱敏。

- [ ] **Step 4: 运行绿灯并提交**

Run: `python -m pytest tests/unit/test_command_runner.py -v`  
Expected: `1 passed`.

```powershell
git add platform_core/deployment/command_runner.py tests/unit/test_command_runner.py
git commit -m "feat: capture auditable subprocess evidence"
```

### Task 3: 实现共享预处理、YOLO 后处理和 PT/ONNX Runtime

**Files:**
- Create: `platform_core/deployment/preprocess.py`
- Create: `platform_core/deployment/postprocess.py`
- Create: `platform_core/deployment/runtimes/base.py`
- Create: `platform_core/deployment/runtimes/ultralytics_runtime.py`
- Create: `platform_core/deployment/runtimes/onnx_runtime.py`
- Create: `platform_core/deployment/runtimes/cache.py`
- Create: `tests/unit/test_preprocess_postprocess.py`
- Create: `tests/unit/test_runtime_registry.py`
- Create: `tests/unit/test_runtime_cache.py`

- [ ] **Step 1: 写预处理、坐标还原和真实 registry 红灯测试**

```python
import numpy as np
from PIL import Image

from platform_core.deployment.postprocess import decode_yolo
from platform_core.deployment.preprocess import letterbox_nchw
from platform_core.deployment.runtimes.registry import runtime_for_suffix


def test_letterbox_and_decode_restore_original_coordinates():
    tensor, meta = letterbox_nchw(Image.new("RGB", (320, 160)), size=640)
    assert tensor.shape == (1, 3, 640, 640)
    raw = np.zeros((1, 5, 1), dtype=np.float32)
    raw[0, :, 0] = [320, 320, 200, 100, .9]
    rows = decode_yolo(raw, meta=meta, labels=["fire"], confidence=.25, iou=.45)
    assert rows[0].label == "fire"
    assert 0 <= rows[0].x1 < rows[0].x2 <= 320


def test_registry_dispatches_pt_and_onnx_to_distinct_runtimes():
    assert runtime_for_suffix(".pt").runtime_name == "ultralytics"
    assert runtime_for_suffix(".onnx").runtime_name == "onnxruntime"
```

`tests/unit/test_runtime_cache.py`:

```python
from platform_core.deployment.runtimes.cache import RuntimeSessionCache, runtime_cache_key


def test_runtime_cache_key_changes_with_runtime_or_resource():
    first = runtime_cache_key("a" * 64, "onnxruntime", "1.20.1", "cpu-a")
    assert first != runtime_cache_key("a" * 64, "onnxruntime", "1.20.2", "cpu-a")
    assert first != runtime_cache_key("a" * 64, "onnxruntime", "1.20.1", "cpu-b")


def test_runtime_cache_evicts_oldest_session():
    cache = RuntimeSessionCache(max_items=2)
    cache.put("one", object())
    cache.put("two", object())
    cache.put("three", object())
    assert cache.get("one") is None
    assert cache.get("three") is not None
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/unit/test_preprocess_postprocess.py tests/unit/test_runtime_registry.py tests/unit/test_runtime_cache.py -v`  
Expected: FAIL because deployment runtime modules do not exist.

- [ ] **Step 3: 实现 PT 与 ONNX 的真实执行**

`RuntimeAdapter` 精确接口：

```python
from abc import ABC, abstractmethod
from collections.abc import Sequence


class RuntimeAdapter(ABC):
    runtime_name: str
    suffixes: Sequence[str]

    @abstractmethod
    def probe(self, resource: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def infer(self, request: RuntimeRequest, *, resource: dict) -> RuntimeResult:
        raise NotImplementedError
```

`OnnxRuntimeAdapter.infer` 必须使用 `onnxruntime.InferenceSession`，执行 `letterbox_nchw -> session.run -> decode_yolo -> draw/save`，四个 `perf_counter` 区间分别形成 `InferenceTimings`。`UltralyticsRuntimeAdapter` 使用 `YOLO(model).predict`，将框统一为 `Detection`，并把模型加载计入 inference 阶段；两者都生成结果图并以 `FileEvidence` 记录输入、模型、结果图。两者通过 `RuntimeSessionCache(max_items=2)` 缓存已加载模型，结果写入 `cache_hit/model_load_ms/cache_key`。

- [ ] **Step 4: 运行绿灯并提交**

Run: `python -m pytest tests/unit/test_preprocess_postprocess.py tests/unit/test_runtime_registry.py tests/unit/test_runtime_cache.py -v`  
Expected: all tests PASS.

```powershell
git add platform_core/deployment/preprocess.py platform_core/deployment/postprocess.py platform_core/deployment/runtimes tests/unit/test_preprocess_postprocess.py tests/unit/test_runtime_registry.py tests/unit/test_runtime_cache.py
git commit -m "feat: run real pt and onnx deployment inference"
```

### Task 4: 实现四种厂商 RuntimeAdapter 与能力路由

**Files:**
- Create: `platform_core/deployment/runtimes/vendor_runtime.py`
- Create: `runtime_runners/tensorrt_runner.py`
- Create: `runtime_runners/ascend_runner.py`
- Create: `runtime_runners/rknn_runner.py`
- Create: `runtime_runners/sophon_runner.py`
- Modify: `platform_core/deployment/runtimes/registry.py`
- Modify: `deploy_plugins/manager.py:3-37`
- Modify: `tests/unit/test_runtime_registry.py`

- [ ] **Step 1: 写六格式与 capability 红灯测试**

```python
import pytest

from platform_core.deployment.runtimes.registry import select_runtime


@pytest.mark.parametrize("suffix,key", [
    (".engine", "tensorrt"), (".om", "ascend"),
    (".rknn", "rockchip"), (".bmodel", "sophon"),
])
def test_vendor_runtime_requires_matching_capability(suffix, key):
    with pytest.raises(RuntimeError, match="BLOCKED_BY_HARDWARE"):
        select_runtime(suffix, resources=[])
    adapter, resource = select_runtime(suffix, resources=[{
        "id": key, "runtime_key": key, "hardware_verified": True,
        "python_path": "vendor-python", "supported_formats": [suffix],
    }])
    assert adapter.runtime_name == key
    assert resource["id"] == key
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/unit/test_runtime_registry.py -v`  
Expected: four new cases FAIL.

- [ ] **Step 3: 实现外部 runner 协议和真实厂商调用**

`VendorRuntimeAdapter` 只能用配置资源的隔离 Python 调用 runner，读取 runner 最后一行 JSON，并通过 `CommandResult` 保存完整 stdout/stderr/exit/time/tool version。四个 runner 共同接收：

```text
--model <absolute model> --input <absolute image> --output <absolute jpg>
--labels-json <absolute json> --input-size 640 --confidence 0.25 --iou 0.45
```

真实 API 约束：

- TensorRT：`tensorrt.Runtime.deserialize_cuda_engine`、execution context、CUDA buffer、`execute_async_v3`。
- Atlas：`acl.init`、device/context/stream、`acl.mdl.load_from_file`、dataset/buffer、`acl.mdl.execute`，最后按逆序释放。
- RKNN：板端优先 `rknnlite.api.RKNNLite.load_rknn/init_runtime/inference`；PC 仿真仅允许 `rknn.api.RKNN.init_runtime` 明确配置成功时执行，结果标记 `emulator=true`，不得算硬件通过。
- Sophon：`sophon.sail.Engine(model, device_id, sail.IOMode.SYSIO)`、`process(graph, inputs)`。

每个 runner 使用共享预/后处理函数并输出 `RuntimeResult.to_dict()`；导入 SDK 失败输出 `{"status":"BLOCKED_BY_ENVIRONMENT","error_code":"VENDOR_RUNTIME_IMPORT_FAILED","message":"厂商 Runtime 无法导入","solution":"检查资源配置的隔离 Python 与锁定 SDK 版本"}`，设备初始化失败输出 `BLOCKED_BY_HARDWARE`，不得创建结果图。

- [ ] **Step 4: 运行 registry 绿灯并提交**

Run: `python -m pytest tests/unit/test_runtime_registry.py -v`  
Expected: all cases PASS without importing vendor SDK in the platform Python.

```powershell
git add platform_core/deployment/runtimes runtime_runners deploy_plugins/manager.py tests/unit/test_runtime_registry.py
git commit -m "feat: dispatch vendor models to real hardware runtimes"
```

### Task 5: 通过公共任务层运行部署测试 Worker

**Files:**
- Create: `platform_core/deployment/task_handlers.py`
- Create: `deployment_test_worker.py`
- Create: `tests/api/test_deployment_test_jobs.py`
- Modify: `app.py:6422-6698`

- [ ] **Step 1: 写 API 入队、成功和硬件阻断红灯测试**

```python
from platform_core.task_runtime.models import TaskKind, TaskStatus


def test_deployment_test_api_enqueues_common_task(client, seeded_project, monkeypatch):
    pid, image = seeded_project
    response = client.post(f"/api/v56/projects/{pid}/deployment-tests", json={
        "model_path": "project-model.pt", "image_ids": [image["id"]],
        "confidence": .25, "iou": .45,
    })
    assert response.status_code == 202
    task = response.json()["task"]
    assert task["kind"] == TaskKind.DEPLOYMENT_TEST.value
    assert task["status"] == TaskStatus.QUEUED.value


def test_missing_board_finishes_as_blocked_by_hardware(worker_context_factory):
    context = worker_context_factory(kind=TaskKind.DEPLOYMENT_TEST, payload={
        "model_path": "model.rknn", "image_paths": ["image.jpg"]
    })
    handle_deployment_test(context, resources=[])
    assert context.repository.get(context.task.task_id).status == TaskStatus.BLOCKED_BY_ENVIRONMENT
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/api/test_deployment_test_jobs.py -v`  
Expected: FAIL with route 404 and missing handler.

- [ ] **Step 3: 实现 handler 与薄 Worker 入口**

`handle_deployment_test(context, resources)` 对每张图片 heartbeat，检查 `cancel_requested()`，调用 Runtime registry，将逐图结果原子写到 `results/items/<index>.json`，最终汇总写 `results/summary.json`。成功使用：

```python
context.repository.finish(
    context.task.task_id, context.lease.lease_token,
    status=TaskStatus.SUCCEEDED,
    result_ref="results/summary.json",
)
```

缺少 Runtime/SDK/可执行程序时 finish 为 `BLOCKED_BY_ENVIRONMENT`；Runtime 存在但缺少必需的目标芯片/设备时 finish 为 `BLOCKED_BY_HARDWARE`。在独立 `task_worker.py` 中为 deployment-test 角色注册 `TaskKind.DEPLOYMENT_TEST` handler，capabilities 来自 `resources.py`，不直接扫描用户目录。

- [ ] **Step 4: 将 API 改为有界入队和查询**

新增：

```text
POST /api/v56/projects/{project_id}/deployment-tests
GET  /api/v56/projects/{project_id}/deployment-tests
GET  /api/v56/projects/{project_id}/deployment-tests/{task_id}
GET  /api/v56/projects/{project_id}/deployment-tests/{task_id}/result
POST /api/v56/projects/{project_id}/deployment-tests/{task_id}/cancel
POST /api/v56/projects/{project_id}/deployment-tests/{task_id}/retry
```

旧 `/api/v12/projects/{project_id}/predict` 保留一个版本并内部入队，返回与新接口相同的 `202` 任务摘要，不使旧页面突然断链；迁移时间点写入 README，主 API 不再调用 `subprocess.run`。

- [ ] **Step 5: 运行绿灯并提交**

Run: `python -m pytest tests/api/test_deployment_test_jobs.py -v`  
Expected: all tests PASS.

```powershell
git add platform_core/deployment/task_handlers.py deployment_test_worker.py app.py tests/api/test_deployment_test_jobs.py
git commit -m "feat: queue deployment tests on persistent workers"
```

### Task 6: 部署测试 UI 展示阶段、结果契约与模型缓存

**Files:**
- Create: `static/modules/deployment-test.js`
- Modify: `static/app.js:660-804, 1667-1832`
- Modify: `tests/browser/model-and-conversion.spec.mjs`

- [ ] **Step 1: 写浏览器红灯测试**

```javascript
test('deployment test shows runtime evidence and four timings', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name: '检测台'}).click();
  await page.setInputFiles('[data-testid="deployment-image"]', {
    name: 'fixture.png', mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=', 'base64'),
  });
  await page.getByRole('button', {name: '开始部署测试'}).click();
  await expect(page.getByTestId('deployment-stage')).toContainText(/加载模型|预处理|推理|后处理/);
  await expect(page.getByTestId('deployment-runtime')).toContainText(/ultralytics|onnxruntime/);
  await expect(page.getByTestId('deployment-timings')).toContainText('预处理');
  await expect(page.getByTestId('deployment-timings')).toContainText('总耗时');
  await expect(page.getByTestId('deployment-result-image')).toBeVisible();
});
```

- [ ] **Step 2: 运行并确认红灯**

Run: `npx playwright test tests/browser/model-and-conversion.spec.mjs -g "deployment test"`  
Expected: FAIL because the new controls and staged API do not exist.

- [ ] **Step 3: 实现轮询、状态和缓存展示**

`deployment-test.js` 导出 `pollDeploymentTest`、`renderRuntimeResult`、`statusPresentation`。模型 cache key 必须包含 `model.sha256 + runtime + runtime_version + resource_fingerprint`；Worker 进程内缓存已加载 session/engine，LRU 上限 2，任务结果记录 `cache_hit` 和 `model_load_ms`。UI 对 `BLOCKED_BY_ENVIRONMENT/HARDWARE` 显示独立处理建议，不把它们渲染为失败或成功。

- [ ] **Step 4: 运行绿灯并提交**

```powershell
npm test
npx playwright test tests/browser/model-and-conversion.spec.mjs -g "deployment test"
git add static/modules/deployment-test.js static/app.js tests/browser/model-and-conversion.spec.mjs
git commit -m "feat: show staged deployment inference evidence"
```

### Task 7: 建立 BaseConverter、ONNX 准备层和四厂商 Adapter

**Files:**
- Create: `platform_core/deployment/converters/base.py`
- Create: `platform_core/deployment/converters/onnx_converter.py`
- Create: `platform_core/deployment/converters/tensorrt_converter.py`
- Create: `platform_core/deployment/converters/ascend_converter.py`
- Create: `platform_core/deployment/converters/rockchip_converter.py`
- Create: `platform_core/deployment/converters/sophon_converter.py`
- Create: `platform_core/deployment/converters/registry.py`
- Create: `tests/unit/test_converter_adapters.py`
- Modify: `platform_core/conversion.py:1-87`

- [ ] **Step 1: 写 Adapter 选择和生命周期红灯测试**

```python
from platform_core.deployment.converters.registry import converter_for_target


def test_converter_registry_has_onnx_and_four_vendor_adapters():
    assert converter_for_target("onnx").converter_name == "onnx"
    assert converter_for_target("tensorrt").converter_name == "tensorrt"
    assert converter_for_target("ascend").converter_name == "ascend"
    assert converter_for_target("rockchip").converter_name == "rockchip"
    assert converter_for_target("sophon").converter_name == "sophon"


def test_converter_distinguishes_missing_runtime_from_missing_hardware(fake_context):
    converter = converter_for_target("rockchip")
    missing_runtime = converter.classify_outcome(
        converted=True, runtime_verified=False, runtime_available=False, hardware_available=False,
    )
    missing_board = converter.classify_outcome(
        converted=True, runtime_verified=False, runtime_available=True, hardware_available=False,
    )
    assert missing_runtime.status.value == "BLOCKED_BY_ENVIRONMENT"
    assert missing_board.status.value == "BLOCKED_BY_HARDWARE"
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/unit/test_converter_adapters.py -v`  
Expected: FAIL importing converter registry.

- [ ] **Step 3: 实现精确基类和共享 ONNX 层**

```python
from abc import ABC, abstractmethod
from pathlib import Path

from platform_core.task_runtime.models import TaskStatus

from platform_core.deployment.contracts import (
    ConversionOutcome,
    ConversionRequest,
    ConversionResult,
    FileEvidence,
)


class BaseConverter(ABC):
    converter_name: str
    target: str

    @abstractmethod
    def probe(self, resource: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def convert(self, request: ConversionRequest, *, resource: dict) -> ConversionResult:
        raise NotImplementedError

    @abstractmethod
    def validate_artifact(self, path: Path, *, request: ConversionRequest) -> FileEvidence:
        raise NotImplementedError

    def classify_outcome(self, *, converted: bool, runtime_verified: bool,
                         runtime_available: bool, hardware_available: bool) -> ConversionOutcome:
        if not converted:
            return ConversionOutcome(TaskStatus.FAILED, "转换未产生有效产物")
        if not runtime_available:
            return ConversionOutcome(TaskStatus.BLOCKED_BY_ENVIRONMENT, "产物已生成，当前 Worker 缺少目标 Runtime")
        if not hardware_available:
            return ConversionOutcome(TaskStatus.BLOCKED_BY_HARDWARE, "产物已生成，当前 Worker 缺少目标硬件")
        if not runtime_verified:
            return ConversionOutcome(TaskStatus.FAILED, "Runtime 存在但未通过真实推理验证")
        return ConversionOutcome(TaskStatus.SUCCEEDED, "转换和目标 Runtime 验证通过")
```

`OnnxConverter` 负责 PT/Paddle/既有 ONNX 到统一 ONNX，并执行 Checker + ONNX Runtime 真实图片推理。`TensorRTConverter`、`AscendConverter`、`RockchipConverter`、`SophonConverter` 只实现厂商编译参数和产物验证，统一经 `run_command` 运行。

- [ ] **Step 4: 运行绿灯并提交**

Run: `python -m pytest tests/unit/test_converter_adapters.py tests/unit/test_conversion.py -v`  
Expected: all tests PASS.

```powershell
git add platform_core/deployment/converters platform_core/conversion.py tests/unit/test_converter_adapters.py tests/unit/test_conversion.py
git commit -m "refactor: isolate onnx and vendor converter adapters"
```

### Task 8: 将 deployment_worker 迁移到公共任务层与证据 manifest

**Files:**
- Modify: `deployment_worker.py:1-587`
- Modify: `platform_core/deployment/task_handlers.py`
- Modify: `tests/api/test_conversion_jobs.py`
- Modify: `tests/e2e/test_real_onnx_conversion.py`

- [ ] **Step 1: 写命令证据和状态门禁红灯测试**

```python
def test_conversion_manifest_contains_command_and_file_evidence(conversion_result):
    manifest = conversion_result["manifest"]
    command = manifest["commands"][0]
    assert set(command) >= {"stdout", "stderr", "exit_code", "started_at", "finished_at", "duration_ms", "tool_name", "tool_version"}
    assert set(manifest["source"]) >= {"name", "size_bytes", "sha256"}
    assert all(set(row) >= {"name", "size_bytes", "sha256"} for row in manifest["outputs"])


def test_missing_vendor_sdk_blocks_environment_without_fake_artifact(run_conversion):
    task = run_conversion(target="ascend", resources=[])
    assert task.status.value == "BLOCKED_BY_ENVIRONMENT"
    assert not task.result_ref
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/api/test_conversion_jobs.py -v`  
Expected: FAIL because current jobs use `done/failed` and merged logs.

- [ ] **Step 3: 实现 MODEL_CONVERSION handler**

handler 使用 `converter_for_target`，每个命令证据写 `evidence/commands/<sequence>.json`，manifest 写 `artifacts/manifest.json`。缺 SDK/可执行文件时顶层任务为 `BLOCKED_BY_ENVIRONMENT`；已生成转换产物但缺 Runtime 时，manifest 记录 `conversion_state=CONVERTED_UNVERIFIED`，顶层任务仍为 `BLOCKED_BY_ENVIRONMENT`；Runtime 存在但缺目标硬件时顶层任务为 `BLOCKED_BY_HARDWARE`；只有真实 Runtime 图片推理成功才 `SUCCEEDED`。在独立 `task_worker.py` 中为 conversion 角色注册 `TaskKind.MODEL_CONVERSION` handler。

- [ ] **Step 4: 运行绿灯并提交**

Run: `python -m pytest tests/api/test_conversion_jobs.py tests/e2e/test_real_onnx_conversion.py -v`  
Expected: all tests PASS; ONNX 任务为 `SUCCEEDED`，未配置厂商 SDK 的任务为 `BLOCKED_BY_ENVIRONMENT`。

```powershell
git add deployment_worker.py platform_core/deployment/task_handlers.py tests/api/test_conversion_jobs.py tests/e2e/test_real_onnx_conversion.py
git commit -m "refactor: run conversions through persistent task handlers"
```

### Task 9: 统一资源 revision、Windows/Linux 路由和隔离安装规则

**Files:**
- Create: `platform_core/deployment/resources.py`
- Create: `tests/unit/test_deploy_resource_revision.py`
- Modify: `app.py:9143-9469, 9983-10098`
- Modify: `static/app.js:1725-1770, 3724-3782`
- Modify: `deploy_plugins/manager.py:3-37`

- [ ] **Step 1: 写资源修改失效和 capability 路由红灯测试**

```python
from platform_core.deployment.resources import ResourceSnapshot, route_capability


def test_editing_resource_invalidates_previous_ready_revision():
    old = ResourceSnapshot.detected({"id": "r1", "python_path": "/old/python"}, targets=["rockchip"])
    edited = old.apply_config({"python_path": "/new/python"})
    assert edited.status == "unchecked"
    assert edited.targets == []
    assert edited.revision > old.revision


def test_windows_never_claims_linux_vendor_conversion():
    assert route_capability("windows", "amd64", "rockchip", resources=[]) is None
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/unit/test_deploy_resource_revision.py -v`  
Expected: FAIL because resource snapshots do not exist.

- [ ] **Step 3: 实现 revision/fingerprint 与 claim capability**

fingerprint 为规范化 `{os,arch,python,tool_paths,tool_versions,runtime_versions,devices,targets}` 的 SHA256。资源配置任何字段变化都 `revision += 1`、`status=unchecked`、`targets=[]`；创建 task 时保存 revision/fingerprint，Worker claim 时必须完全匹配。Windows 仅声明 PT/ONNX CPU 和已真实探测的 NVIDIA Runtime；CANN、RKNN Toolkit2、TPU-MLIR 由 Linux 隔离节点声明。

前端缓存必须验证 `Date.now() - cached.ts < ttl` 且 `cached.revision == server.revision`；不满足立即读取 API，不再无限使用 localStorage。

- [ ] **Step 4: 加入安全隔离安装门禁**

平台 API 不执行 `pip install`。删除/停用 `app.py:10037-10070` 的安装接口，改为返回 `409` 和精确命令模板：

```text
python3 -m venv /opt/xjalgo/rknn-venv
/opt/xjalgo/rknn-venv/bin/python -m pip install --require-hashes -r rknn-runtime.lock
```

命令只写入管理员文档，由管理员在节点执行；主 Python 路径与 vendor Python 路径相同则资源检测失败。

- [ ] **Step 5: 运行绿灯并提交**

Run: `python -m pytest tests/unit/test_deploy_resource_revision.py tests/unit/test_resource_cache.py -v`  
Expected: all tests PASS.

```powershell
git add platform_core/deployment/resources.py app.py static/app.js deploy_plugins/manager.py tests/unit/test_deploy_resource_revision.py
git commit -m "fix: route deployment tasks by fresh capabilities"
```

### Task 10: 加固远程服务鉴权、密钥边界、TLS 与下载完整性

**Files:**
- Modify: `remote_deploy_server.py:1-190`
- Modify: `remote_deploy_config.example.json`
- Create: `tests/api/test_remote_deploy_security.py`
- Modify: `app.py:9363-9377, 9579-9633`

- [ ] **Step 1: 写全接口鉴权和密钥不回流红灯测试**

```python
import pytest


@pytest.mark.parametrize("method,path", [
    ("get", "/api/deploy/health"),
    ("post", "/api/deploy/config"),
    ("post", "/api/deploy/convert"),
    ("get", "/api/deploy/jobs/missing"),
    ("get", "/api/deploy/jobs/missing/log"),
    ("post", "/api/deploy/jobs/missing/stop"),
    ("get", "/api/deploy/jobs/missing/artifacts.zip"),
])
def test_every_remote_endpoint_requires_key(remote_client, method, path):
    response = getattr(remote_client, method)(path)
    assert response.status_code == 401


def test_remote_job_response_never_contains_api_key(remote_client, auth_headers, seeded_remote_job):
    body = remote_client.get(f"/api/deploy/jobs/{seeded_remote_job}", headers=auth_headers).text
    assert "deploy-secret" not in body
    assert "api_key" not in body
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/api/test_remote_deploy_security.py -v`  
Expected: `/api/deploy/config` is not 401 and job response contains resource configuration.

- [ ] **Step 3: 实现全局认证依赖与公开 DTO**

为所有 `/api/deploy/*` 路由使用 `Depends(require_api_key)`；首次配置只允许 loopback 请求并要求一次性 bootstrap token。远程 job 只保存 `resource_id/resource_fingerprint`，不保存 API Key；返回 DTO 删除 `secret_ref`、headers、完整绝对路径。比较密钥用 `hmac.compare_digest`。

配置 `public_base_url` 为 `http://` 时 health 返回：

```json
{"transport_security":"warning","message":"生产远程转换必须通过 HTTPS 或受控内网反向代理"}
```

主平台 UI 明确显示该提醒，不把 HTTP 标成安全连接。

- [ ] **Step 4: 下载后复验 manifest**

`app.py:9621-9628` 解压后逐项重算 `size_bytes/sha256`，manifest 缺文件、额外目标模型或 hash 不一致时删除本次临时解压目录并 finish `FAILED`，error code 为 `REMOTE_ARTIFACT_INTEGRITY_FAILED`。

- [ ] **Step 5: 运行绿灯并提交**

Run: `python -m pytest tests/api/test_remote_deploy_security.py tests/api/test_deploy_resource_secrets.py -v`  
Expected: all tests PASS.

```powershell
git add remote_deploy_server.py remote_deploy_config.example.json app.py tests/api/test_remote_deploy_security.py
git commit -m "security: authenticate and verify remote deployment jobs"
```

### Task 11: 远程/本机重启恢复、租约和取消进程树

**Files:**
- Create: `tests/integration/test_remote_deploy_recovery.py`
- Modify: `remote_deploy_server.py`
- Modify: `app.py:9579-9731`
- Modify: `deployment_worker.py`
- Modify: `deployment_test_worker.py`

- [ ] **Step 1: 写租约过期恢复与远程 job 重连红灯测试**

```python
def test_restart_releases_expired_local_deployment_lease(task_repository, clock):
    lease = task_repository.claim_next("dead-worker", [TaskKind.MODEL_CONVERSION], {}, lease_seconds=1)
    clock.advance(seconds=2)
    assert task_repository.release_expired(now=clock.now()) == 1
    assert task_repository.get(lease.task.id).status == TaskStatus.QUEUED


def test_platform_restart_resumes_remote_job_polling(remote_harness):
    task_id, remote_id = remote_harness.seed_running_pair()
    remote_harness.restart_platform_sync()
    remote_harness.remote_finish(remote_id)
    assert remote_harness.wait(task_id).status == TaskStatus.BLOCKED_BY_HARDWARE
```

- [ ] **Step 2: 运行并确认红灯**

Run: `python -m pytest tests/integration/test_remote_deploy_recovery.py -v`  
Expected: FAIL because deploy registries and daemon threads are memory-only.

- [ ] **Step 3: 使用公共 lease/checkpoint 恢复**

Worker 启动先调用 `release_expired()`；长命令每 5 秒 heartbeat。checkpoint 保存 `remote_job_id`、最后远程 revision、已下载证据清单；平台启动扫描 `RUNNING/CANCEL_REQUESTED` 的远程部署 task 并重新建立同步。不得依赖 `DEPLOY_PROCESS_REGISTRY` 或 `DEPLOY_REMOTE_THREADS` 判断持久状态。

取消流程固定为 `request_cancel -> WorkerContext.cancel_requested -> 终止整个进程树 -> finish(CANCELLED)`。Windows 和 Linux 都通过公共 `process_control.py` 的 `psutil` 进程树适配器和新进程组实现，业务代码不调用 `taskkill`、批处理或 shell 字符串；停止后 Adapter 不得回写成功。

- [ ] **Step 4: 运行绿灯并提交**

Run: `python -m pytest tests/integration/test_remote_deploy_recovery.py -v`  
Expected: all tests PASS.

```powershell
git add remote_deploy_server.py app.py deployment_worker.py deployment_test_worker.py tests/integration/test_remote_deploy_recovery.py
git commit -m "fix: recover deployment work across process restarts"
```

### Task 12: 当前硬件门控测试覆盖六格式

**Files:**
- Create: `tests/e2e/test_real_deployment_inference.py`
- Modify: `tests/hardware/test_vendor_conversion.py`
- Create: `tests/hardware/test_vendor_runtime.py`
- Modify: `pytest.ini:1-4`

- [ ] **Step 1: 写 Windows CPU PT/ONNX 真实图片验收**

```python
import shutil
from pathlib import Path

import pytest
from PIL import Image
from ultralytics import YOLO

from platform_core.deployment.contracts import RuntimeRequest
from platform_core.deployment.runtimes.registry import runtime_for_suffix


@pytest.fixture(scope="session")
def real_yolo_artifacts(tmp_path_factory):
    import os
    root = Path(__file__).resolve().parents[2]
    source = Path(os.environ.get("XJALGO_REAL_PT") or (root / "yolo11n.pt"))
    if not source.is_file():
        pytest.skip("BLOCKED_BY_ENVIRONMENT: 未配置 XJALGO_REAL_PT 验收权重")
    work = tmp_path_factory.mktemp("real-deployment")
    pt = work / "yolo11n.pt"
    shutil.copy2(source, pt)
    onnx = Path(YOLO(str(pt)).export(format="onnx", imgsz=128, opset=12, simplify=False))
    return {".pt": pt, ".onnx": onnx}


@pytest.fixture
def inference_image(tmp_path):
    path = tmp_path / "input.png"
    Image.new("RGB", (128, 96), (128, 128, 128)).save(path)
    return path


@pytest.mark.real_model
@pytest.mark.parametrize("suffix,runtime", [(".pt", "ultralytics"), (".onnx", "onnxruntime")])
def test_real_image_inference_has_evidence(real_yolo_artifacts, inference_image, tmp_path, suffix, runtime):
    request = RuntimeRequest(
        model_path=real_yolo_artifacts[suffix], image_path=inference_image,
        output_path=tmp_path / f"result-{runtime}.jpg", labels=[],
        input_size=128, confidence=.25, iou=.45,
    )
    result = runtime_for_suffix(suffix).infer(request, resource={}).to_dict()
    assert result["runtime"] == runtime
    assert request.output_path.is_file()
    assert result["result_image"]["size_bytes"] > 0
    assert result["result_image"]["sha256"]
    assert set(result["timings_ms"]) == {"preprocess", "inference", "postprocess", "total"}
    assert isinstance(result["detections"], list)
    assert all(set(row) >= {"class_id", "label", "confidence", "x1", "y1", "x2", "y2"} for row in result["detections"])
    assert result["model"]["sha256"]
    assert result["image"]["sha256"]
```

- [ ] **Step 2: 写厂商转换与 Runtime 环境变量门控**

`tests/hardware/test_vendor_runtime.py` 参数精确为：

```text
XJALGO_VENDOR_TARGET=tensorrt|ascend|rockchip|sophon
XJALGO_VENDOR_MODEL=<absolute path>
XJALGO_VENDOR_IMAGE=<absolute path>
XJALGO_VENDOR_PYTHON=<isolated python>
XJALGO_VENDOR_RESOURCE_JSON=<absolute capability json>
```

变量缺失时测试 `pytest.skip` 的理由必须以 `BLOCKED_BY_HARDWARE:` 或 `BLOCKED_BY_ENVIRONMENT:` 开头；CI 汇总 skip reason，不把 skip 计为通过。变量齐全时必须真实加载模型、生成结果图、返回框和四段耗时，并核对模型/输入/结果 SHA256。

- [ ] **Step 3: 运行当前主机门控**

```powershell
python -m pytest tests/e2e/test_real_deployment_inference.py -m real_model -v -s
python -m pytest tests/hardware/test_vendor_conversion.py tests/hardware/test_vendor_runtime.py -m hardware -v -rs
```

Expected on the audited Windows host: PT/ONNX PASS；TensorRT/Atlas/RKNN/Sophon 均显示明确 `BLOCKED_BY_ENVIRONMENT` 或 `BLOCKED_BY_HARDWARE` skip reason，0 个厂商目标被报告为实机通过。

- [ ] **Step 4: 在每类真实硬件节点运行**

Linux/NVIDIA、Atlas、RK3568、RK3588、BM1684X/BM1688 分别执行：

```bash
python -m pytest tests/hardware/test_vendor_conversion.py tests/hardware/test_vendor_runtime.py -m hardware -v -s
```

Expected: 当前节点对应 target PASS；不属于该节点的 target 保持带门禁原因的 skip。RK3568 和 RK3588 必须分别留存报告，不能互相替代。

- [ ] **Step 5: 提交硬件矩阵**

```powershell
git add tests/e2e/test_real_deployment_inference.py tests/hardware/test_vendor_conversion.py tests/hardware/test_vendor_runtime.py pytest.ini
git commit -m "test: gate deployment claims on real runtimes"
```

### Task 13: 完整回归、文档和交付门禁

**Files:**
- Modify: `README.md:98-end`
- Modify: `remote_deploy_config.example.json`
- Modify: `tests/browser/model-and-conversion.spec.mjs`

- [ ] **Step 1: 文档化 Windows/Linux 能力和状态语义**

README 明确列出：Windows CPU 的 PT/ONNX；NVIDIA Linux 的 TensorRT；CANN/Atlas 的 OM；Linux converter + RK3568/RK3588 板端的 RKNN；TPU-MLIR + BMRuntime 的 BModel。记录 `BLOCKED_BY_ENVIRONMENT` 与 `BLOCKED_BY_HARDWARE` 不是失败也不是成功，只有 Runtime 真实图片推理完成才 `SUCCEEDED`。厂商 SDK 仅装在独立 venv/conda/容器或节点系统环境，禁止安装进平台主 Python。

- [ ] **Step 2: 运行静态和非硬件回归**

```powershell
python -m compileall platform_core deployment_worker.py deployment_test_worker.py remote_deploy_server.py runtime_runners
python -m pytest tests/unit tests/api tests/integration tests/e2e/test_real_onnx_conversion.py tests/e2e/test_real_deployment_inference.py -v
npm test
node --check static/app.js
npx playwright test tests/browser/model-and-conversion.spec.mjs
```

Expected: every command exits 0；不存在 vendor SDK 的平台 Python 不导入 TensorRT/ACL/RKNN/Sophon 包。

- [ ] **Step 3: 扫描状态、密钥和占位产物反模式**

```powershell
rg -n "status=['\"]done|converted_unverified|api_key.*resource|stderr=subprocess.STDOUT" deployment_worker.py deployment_test_worker.py remote_deploy_server.py platform_core/deployment app.py
rg -n "BLOCKED_BY_ENVIRONMENT|BLOCKED_BY_HARDWARE" platform_core/deployment tests
```

Expected: 第一条无业务命中；第二条在 handler、Adapter 和测试中均有命中。随后执行：

```powershell
python -m pytest tests/api/test_remote_deploy_security.py tests/integration/test_remote_deploy_recovery.py -v
```

Expected: all tests PASS，响应与日志中无测试 API Key。

- [ ] **Step 4: 运行当前硬件报告并保存 CI artifact**

Run: `python -m pytest tests/hardware -m hardware -v -rs --junitxml=test-results/vendor-hardware.xml`  
Expected: XML 明确区分 PASS 与以 `BLOCKED_BY_*` 开头的 skip；当前 Windows 不出现厂商 Runtime PASS。

- [ ] **Step 5: 提交最终文档与验收更新**

```powershell
git add README.md remote_deploy_config.example.json tests/browser/model-and-conversion.spec.mjs
git commit -m "docs: record verified deployment runtime boundaries"
```

## 最终验收门禁

- API 不直接执行长耗时推理/转换，只创建公共 `DEPLOYMENT_TEST` 或 `MODEL_CONVERSION` task。
- PT、ONNX、Engine、OM、RKNN、BModel 均由对应 RuntimeAdapter 分派；结果含结果图、框、类别、置信度和四段耗时。
- 所有外部命令保留分离 stdout/stderr、exit code、UTC 时间、耗时、工具版本、输入/输出大小与 SHA256。
- ONNX 准备层与 TensorRT/Ascend/Rockchip/Sophon 四 Adapter 不再散落在 Worker 分支中。
- 缺 SDK 使用 `BLOCKED_BY_ENVIRONMENT`；缺目标 GPU/NPU/开发板使用 `BLOCKED_BY_HARDWARE`；二者不渲染为成功。
- 资源修改立即失效旧 revision；调度只向 fingerprint/capability 匹配的 Windows/Linux Worker 发任务。
- 远程服务所有接口鉴权，API Key 不进入 job、响应、日志或回传状态；HTTP 有 TLS 警告；下载产物逐项复验 SHA256。
- 平台或远程节点重启后任务依靠 lease/checkpoint 恢复，取消会终止整个进程树且不能回写成功。
- 厂商 SDK 不安装到平台主 Python；当前无硬件环境只产生可审计门禁结果，不产生实机通过声明。
