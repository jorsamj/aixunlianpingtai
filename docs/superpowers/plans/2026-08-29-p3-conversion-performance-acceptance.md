# P3 真实转换资源、性能与一体化验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让转换弹窗立即显示真实资源状态，真实生成并校验 ONNX，对未配置的 TensorRT/Atlas/RKNN 给出明确信息，最后在 Windows 完成上传、清洗、标注、训练和转换的组合验收。

**Architecture:** 转换能力分为“快速缓存概况”和“显式真实检测”两层，页面不等待多个外部工具同步扫描。转换 worker 只对非空真实产物写 manifest；端到端测试与真实 CPU 训练/真实 ONNX 测试分层，以便既能快速回归又能证明真实可用。

**Tech Stack:** FastAPI、Ultralytics、ONNX/ONNX Runtime、pytest、Playwright、Windows PowerShell。

---

## 文件结构

- Create: `platform_core/resource_cache.py` — 转换资源 TTL 缓存、后台刷新和最后检测时间。
- Modify: `platform_core/conversion.py` — ONNX 产物加载校验和 manifest 验证状态。
- Modify: `app.py:7897-8240` — 资源快速列表、显式刷新和单资源检测。
- Modify: `deployment_worker.py` — ONNX 真实导出/加载校验与厂商失败证据。
- Create: `static/modules/deploy-resources.js` — 资源概况、后台刷新和按钮可用性纯函数。
- Modify: `static/main.mjs`
- Modify: `static/app.js:1662-1690, 2875-2955` — 转换页资源状态和提交反馈。
- Modify: `static/styles.css` — 资源骨架、缺失组件和转换进度。
- Create: `tests/unit/test_resource_cache.py`
- Modify: `tests/unit/test_conversion.py`
- Modify: `tests/api/test_conversion_jobs.py`
- Create: `tests/e2e/test_real_onnx_conversion.py`
- Modify: `tests/browser/model-and-conversion.spec.mjs`
- Create: `tests/browser/integrated-workflow.spec.mjs`
- Modify: `tools/test_server.py`
- Modify: `README.md` — Windows 验收启动、真实资源和未验证边界。

### Task 1: 转换资源列表立即返回，真实检测显式触发

- [ ] **Step 1: 编写缓存命中和过期刷新失败测试**

`tests/unit/test_resource_cache.py`:

```python
from platform_core.resource_cache import ResourceCache


def test_cached_resources_return_without_running_detector_twice():
    calls = []
    cache = ResourceCache(ttl_seconds=30)
    detector = lambda: calls.append(1) or [{"id": "onnx", "status": "ready"}]
    assert cache.get_or_refresh(detector)["items"][0]["status"] == "ready"
    assert cache.get_or_refresh(detector)["items"][0]["status"] == "ready"
    assert len(calls) == 1


def test_stale_value_is_returned_while_one_background_refresh_runs():
    cache = ResourceCache(ttl_seconds=0)
    cache.replace([{"id": "atlas", "status": "missing"}])
    first = cache.snapshot()
    assert first["items"][0]["status"] == "missing"
    assert first["stale"] is True
```

- [ ] **Step 2: 运行确认模块不存在**

Run: `python -m pytest tests/unit/test_resource_cache.py -v`  
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现线程安全 TTL 缓存**

```python
import threading
import time
from copy import deepcopy


class ResourceCache:
    def __init__(self, ttl_seconds: float = 30):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._items = []
        self._updated_at = 0.0
        self._refreshing = False

    def snapshot(self):
        with self._lock:
            age = max(0.0, time.monotonic() - self._updated_at)
            return {"items": deepcopy(self._items), "stale": age >= self.ttl_seconds,
                    "refreshing": self._refreshing, "age_seconds": round(age, 3)}

    def get_or_refresh(self, detector):
        current = self.snapshot()
        if current["items"] and not current["stale"]:
            return current
        self.replace(detector())
        return self.snapshot()
```

`refresh_in_background(detector)` 必须使用 `_refreshing` 防止同一时间重复扫描。

- [ ] **Step 4: 将 `/api/v39/deploy/resources` 分为快速查询与显式刷新**

GET 返回 `{items, stale, refreshing, updated_at}`，缓存空时先返回内置资源的 `unchecked/missing` 概况并启动一个后台刷新。`POST /api/v39/deploy/resources/refresh` 用于用户显式刷新；`POST .../{id}/detect` 仍可同步验证单个资源。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_resource_cache.py tests/api/test_conversion_jobs.py -v
git add platform_core/resource_cache.py app.py tests/unit/test_resource_cache.py
git commit -m "perf: return conversion resources from a refreshable cache"
```

### Task 2: 转换页立即显示可用、缺失和刷新中状态

- [ ] **Step 1: 编写资源展示纯函数失败测试**

`tests/frontend/deploy-resources.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {resourcePresentation, canSubmitConversion} from '../../static/modules/deploy-resources.js';

test('missing vendor tool gives a visible setup message', () => {
  assert.deepEqual(resourcePresentation({kind: 'ascend', status: 'missing', message: '未检测到 CANN ATC'}), {
    tone: 'missing', title: '华为 Atlas · 未配置', detail: '未检测到 CANN ATC'
  });
});

test('only ready resource can submit a real conversion', () => {
  assert.equal(canSubmitConversion({status: 'ready', conversion_ready: true}), true);
  assert.equal(canSubmitConversion({status: 'missing'}), false);
});
```

- [ ] **Step 2: 运行确认新模块不存在**

Run: `npm test`  
Expected: FAIL importing `deploy-resources.js`.

- [ ] **Step 3: 实现资源展示模型并导出到 `PlatformCore`**

`resourcePresentation` 对 `ready/missing/unchecked/error` 生成稳定的 title、detail 和 tone；保留服务端 message，不用“稍后重试”覆盖具体缺失项。

- [ ] **Step 4: 改造转换弹窗**

弹窗打开时先渲染缓存 items；`stale/refreshing` 只显示非阻塞的“正在后台刷新”。可用资源显示“开始转换”；缺失资源显示组件、路径和“重新检测”，不显示假的可提交按钮。提交后立即显示 job ID 和状态，失败保留 error code/solution。

- [ ] **Step 5: 运行前端测试并提交**

```powershell
npm test
node --check static/app.js
git add static/modules/deploy-resources.js static/main.mjs static/app.js static/styles.css tests/frontend/deploy-resources.test.mjs
git commit -m "fix: show conversion capability before background detection finishes"
```

### Task 3: 真实 ONNX 转换必须可加载，厂商目标缺 SDK 必须明确失败

- [ ] **Step 1: 扩展转换单元/API 失败测试**

`tests/unit/test_conversion.py` 新增：

```python
def test_manifest_rejects_unvalidated_onnx_output(tmp_path):
    output = tmp_path / "broken.onnx"
    output.write_bytes(b"not an onnx model")
    with pytest.raises(ValueError, match="ONNX"):
        verified_onnx_record(output)
```

`tests/api/test_conversion_jobs.py` 保留当前 `ATC_NOT_FOUND/RKNN_TOOLKIT_NOT_FOUND/TENSORRT_NOT_FOUND` 用例，并断言 `artifacts` 目录无目标后缀产物且 job 包含 `solution`。

- [ ] **Step 2: 运行确认假 ONNX 仅按非空文件会被接受**

Run: `python -m pytest tests/unit/test_conversion.py tests/api/test_conversion_jobs.py -v`  
Expected: new ONNX validation test FAIL.

- [ ] **Step 3: 实现 ONNX 加载校验**

```python
def verified_onnx_record(path: Path) -> dict:
    import onnx
    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    inputs = [value.name for value in model.graph.input]
    outputs = [value.name for value in model.graph.output]
    if not inputs or not outputs:
        raise ValueError("ONNX 模型缺少输入或输出")
    return {**file_record(path), "validated": True, "inputs": inputs, "outputs": outputs}
```

`deployment_worker.py` 只有在 `verified_onnx_record` 成功后才将 ONNX 写入 manifest。厂商工具缺失时先写明确失败 job，不复制/改名 ONNX 作为目标产物。

- [ ] **Step 4: 运行转换回归**

Run: `python -m pytest tests/unit/test_conversion.py tests/api/test_conversion_jobs.py -v`  
Expected: PASS.

- [ ] **Step 5: 提交产物验证**

```powershell
git add platform_core/conversion.py deployment_worker.py tests/unit/test_conversion.py tests/api/test_conversion_jobs.py
git commit -m "fix: validate real onnx and vendor conversion artifacts"
```

### Task 4: 使用真实 YOLO 权重完成 ONNX 导出与加载验收

- [ ] **Step 1: 创建 `tests/e2e/test_real_onnx_conversion.py`**

```python
import json
import subprocess
import sys
from pathlib import Path

import onnx


ROOT = Path(__file__).resolve().parents[2]


def local_yolo_checkpoint() -> Path:
    candidates = [ROOT / "yolo11n.pt", *(parent / "yolo11n.pt" for parent in ROOT.parents)]
    checkpoint = next((path for path in candidates if path.is_file()), None)
    assert checkpoint is not None, "真实 ONNX 验收需要已准备的 yolo11n.pt"
    return checkpoint


def test_real_yolo_checkpoint_exports_and_loads_as_onnx(tmp_path):
    job_dir = tmp_path / "onnx-job"
    job_dir.mkdir()
    source = local_yolo_checkpoint()
    job = {
        "id": "real-onnx", "status": "queued", "target": "onnx",
        "source_id": "local-yolo11n", "source_path": str(source),
        "source_trace": {"source_id": "local-yolo11n", "sha256": "calculated-by-worker"},
        "resource": {"id": "builtin_ultralytics", "name": "Ultralytics", "python_path": sys.executable},
        "params": {"input_size": 128, "batch": 1, "opset": 12, "dynamic": False, "simplify": False},
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"), "--job-dir", str(job_dir)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=300,
    )
    final_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-12000:]
    assert final_job["status"] == "done", final_job
    manifest = json.loads(Path(final_job["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["onnx"]["checker"] == "passed"
    onnx_output = next(item for item in manifest["outputs"] if item["name"].endswith(".onnx"))
    assert onnx_output["sha256"]
    assert onnx_output["size_bytes"] > 0
    model = onnx.load(str(job_dir / "artifacts" / onnx_output["name"]))
    onnx.checker.check_model(model)
```

用例不允许在缺少本地权重时静默 skip；Windows 真实验收前必须按项目安装流程准备 `yolo11n.pt`。

- [ ] **Step 2: 运行真实 ONNX 用例**

Run: `python -m pytest tests/e2e/test_real_onnx_conversion.py -v -s`  
Expected: PASS only when a real `.onnx` is exported and loaded; 任何伪造或改名文件都会失败。

- [ ] **Step 3: 扩展 `tests/browser/model-and-conversion.spec.mjs`**

拦截首次资源响应为 `stale:true, refreshing:true`，断言弹窗仍在 1 秒内显示 ONNX/TensorRT/Atlas/RKNN 卡片；随后返回新状态并断言页面无刷新更新。

- [ ] **Step 4: 运行浏览器与真实 ONNX 测试**

```powershell
npx playwright test tests/browser/model-and-conversion.spec.mjs
python -m pytest tests/e2e/test_real_onnx_conversion.py -v -s
```

Expected: 全部退出码 0。

- [ ] **Step 5: 提交 ONNX 真实证据**

```powershell
git add tests/e2e/test_real_onnx_conversion.py tests/browser/model-and-conversion.spec.mjs
git commit -m "test: prove real onnx conversion and responsive resources"
```

### Task 5: 数万张素材性能和一体化浏览器闭环

- [ ] **Step 1: 新增性能与一体化失败用例**

`tests/unit/test_material_search.py` 用 30,000 条记录断言返回 items 不超过 page size；不使用过于脆弱的绝对时间门槛。`tests/browser/integrated-workflow.spec.mjs` 使用独立项目执行：

1. 上传 4 张图片并看到 4 张缩略图。
2. 2 张需清洗、2 张无需清洗，完成清洗确认。
3. 在配置中心创建 `fire/明火`，返回素材页对图片画框并保存。
4. 搜索“明火”找到已标注图片。
5. 创建算法，打开训练弹窗，看到标注框，设置试验比例并提交。
6. 打开转换弹窗，在资源尚未刷新完成时仍能看到能力卡片。

- [ ] **Step 2: 运行新一体化用例并记录第一个真实断点**

Run: `npx playwright test tests/browser/integrated-workflow.spec.mjs --trace on`  
Expected: 在尚未完成 P0-P2 时 FAIL，失败 trace 用于对应修复。

- [ ] **Step 3: 修正跨页状态刷新和稳定测试标识**

所有主按钮和任务反馈增加稳定 `data-testid`；页面切换后从服务端修订号确认是否需要刷新素材，不用固定 sleep 掩盖竞态。

- [ ] **Step 4: 运行完整非硬件回归**

```powershell
python -m pytest tests/unit tests/api tests/integration tests/e2e/test_windows_startup.py -v
npm test
npx playwright test
```

Expected: 全部退出码 0。厂商硬件测试不在未配置 SDK 的 Windows 机器上伪装通过。

- [ ] **Step 5: 提交一体化闭环**

```powershell
git add tests/unit/test_material_search.py tests/browser/integrated-workflow.spec.mjs static/app.js
git commit -m "test: verify integrated material training conversion workflow"
```

### Task 6: Windows 真实启动验收与文档化

- [ ] **Step 1: 运行 Windows 启动测试**

Run: `python -m pytest tests/e2e/test_windows_startup.py -v`  
Expected: PASS; 启动脚本正确使用项目环境和可配置数据目录。

- [ ] **Step 2: 在隔离测试目录启动完整服务并检查健康端点**

```powershell
$env:MC_TRAIN_DATA_DIR="$env:TEMP\xjalgo-windows-acceptance"
python tools/test_server.py
```

另一终端运行 `Invoke-RestMethod http://127.0.0.1:8011/api/health`，Expected: 返回版本和 `ok=true`。验收后停止该隔离服务，不删除用户正式数据。

- [ ] **Step 3: 在 `README.md` 记录真实能力边界**

文档列出：Windows 上传/清洗/标注/真实 CPU/CUDA 训练/ONNX 转换；TensorRT 需 NVIDIA CUDA+TensorRT；Atlas 需 CANN ATC；RK3588/RK3568 需 RKNN-Toolkit2。不得将“未实机验证”写成“已支持成功”。

- [ ] **Step 4: 运行最终真实测试**

```powershell
python -m pytest tests/e2e/test_real_yolo_training.py tests/e2e/test_real_onnx_conversion.py -v -s
```

Expected: 真实训练两代与真实 ONNX 加载全部通过。

- [ ] **Step 5: 提交 Windows 验收文档**

```powershell
git add README.md tests/e2e/test_windows_startup.py
git commit -m "docs: record verified Windows training and conversion capabilities"
```

## P3 验收门禁

- 转换弹窗立即显示资源概况，不因同步工具扫描白屏或卡住。
- ONNX 是真实可加载模型，manifest 包含 hash、输入和输出校验。
- TensorRT、Atlas、RKNN 缺少工具链时明确失败且无假产物。
- 一体化浏览器用例能从上传走到训练提交和转换资源显示。
- Windows 真实两代 YOLO 训练和真实 ONNX 转换均通过。
- 厂商硬件能力只按实际已配置 SDK/硬件报告，不做伪证。
