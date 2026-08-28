# M3 算法资产、迭代训练、数据质量与双层报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让算法创建、版本迭代、训练快照、真实 YOLO 训练、数据质量和两层报告形成可复现闭环。

**Architecture:** 算法与训练逻辑拆入纯服务；任务创建时生成不可变 Snapshot，并保存基础版本选择证据。Worker 只消费任务记录中的规范化参数，完成后验证权重与指标再归档版本。报告服务分别生成单版本和算法汇总视图。

**Tech Stack:** FastAPI、pytest、Ultralytics、PyTorch、Pillow、Chart.js 或原生 SVG、Playwright。

---

## 文件结构

- Create: `platform_core/algorithms.py`
- Create: `platform_core/snapshots.py`
- Create: `platform_core/quality.py`
- Create: `platform_core/reports.py`
- Create: `static/modules/algorithms.js`
- Create: `static/modules/training.js`
- Create: `static/modules/quality.js`
- Create: `static/modules/reports.js`
- Modify: `app.py:3779-5120` — 算法、训练和版本归档调用服务。
- Modify: `app.py:9334-9495` — 质量和版本报告调用服务。
- Modify: `app.py:9989-10019` — 算法综合报告调用服务。
- Modify: `train_worker.py` — 只消费锁定 Snapshot 和基础模型。
- Test: `tests/unit/test_algorithms.py`
- Test: `tests/unit/test_snapshots.py`
- Test: `tests/unit/test_quality.py`
- Test: `tests/unit/test_reports.py`
- Test: `tests/api/test_algorithm_flow.py`
- Test: `tests/api/test_training_request.py`
- Test: `tests/e2e/test_real_yolo_training.py`
- Test: `tests/browser/training-quality-reports.spec.mjs`

### Task 1: 算法 CRUD 只有一个正式实现

- [ ] **Step 1: 写失败 API 测试**

`tests/api/test_algorithm_flow.py`:

```python
def test_create_algorithm_returns_persisted_asset(client, seeded_project):
    pid, _ = seeded_project
    payload = {"name":"烟火判断","industry":"工业安全","algorithm_type":"ultralytics","remark":""}
    created = client.post(f"/api/v12/projects/{pid}/algorithms", json=payload)
    assert created.status_code == 200
    algorithm = created.json()["algorithm"]
    assert algorithm["name"] == "烟火判断"
    listed = client.get(f"/api/v12/projects/{pid}/algorithms").json()["items"]
    assert [item["id"] for item in listed].count(algorithm["id"]) == 1


def test_duplicate_algorithm_name_is_actionable(client, seeded_project):
    pid, _ = seeded_project
    payload = {"name":"烟火判断","industry":"工业安全","algorithm_type":"ultralytics","remark":""}
    client.post(f"/api/v12/projects/{pid}/algorithms", json=payload)
    response = client.post(f"/api/v12/projects/{pid}/algorithms", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "ALGORITHM_NAME_EXISTS"
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/api/test_algorithm_flow.py -v
```

Expected: 旧响应字段、重复校验或持久化行为不满足测试。

- [ ] **Step 3: 实现 `platform_core/algorithms.py`**

提供 `list_algorithms`、`create_algorithm`、`update_algorithm`、`delete_algorithm` 和 `attach_version`。写入使用原子替换，版本按训练完成时间倒序。

- [ ] **Step 4: 修改 `/api/v12/.../algorithms` 路由只调用服务，旧 Blueprint 路由改为只读兼容或移除创建入口**

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/api/test_algorithm_flow.py -v
git add platform_core/algorithms.py app.py tests/api/test_algorithm_flow.py
git commit -m "fix: use one persisted algorithm asset implementation"
```

### Task 2: 迭代基础模型选择最近可用版本

- [ ] **Step 1: 写失败单元测试**

`tests/unit/test_algorithms.py`:

```python
from pathlib import Path
from platform_core.algorithms import choose_iteration_base


def test_latest_missing_artifact_falls_back_to_previous_usable(tmp_path: Path):
    usable = tmp_path / "best.pt"
    usable.write_bytes(b"real-checkpoint-placeholder-for-selection-test")
    versions = [
        {"id":"v3","version_name":"20260828120000","finished_at":"2026-08-28T12:00:00","best_path":str(tmp_path/'missing.pt')},
        {"id":"v2","version_name":"20260827120000","finished_at":"2026-08-27T12:00:00","best_path":str(usable)},
    ]
    result = choose_iteration_base(versions, "yolo11n.pt")
    assert result["base_version_id"] == "v2"
    assert result["base_model_path"] == str(usable.resolve())
    assert result["base_selection_reason"] == "latest_usable_version"


def test_no_usable_history_uses_mother_model(tmp_path: Path):
    result = choose_iteration_base([], "yolo11n.pt")
    assert result["base_version_id"] is None
    assert result["base_model_path"] == "yolo11n.pt"
    assert result["base_selection_reason"] == "mother_model"
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_algorithms.py -v
```

- [ ] **Step 3: 实现选择函数并替换 `app.py:4418-4443`**

仅允许 `.pt` 或 Paddle 对应可训练权重作为迭代基础；ONNX、engine、OM、RKNN 不可用于继续训练。

- [ ] **Step 4: 任务创建写入五个基础字段**

```python
job.update(base_version_id=base["base_version_id"], base_version_name=base["base_version_name"], base_model_path=base["base_model_path"], base_model_kind=base["base_model_kind"], base_selection_reason=base["base_selection_reason"])
```

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_algorithms.py -v
git add platform_core/algorithms.py app.py tests/unit/test_algorithms.py
git commit -m "fix: continue training from latest usable algorithm version"
```

### Task 3: 创建不可变训练 Snapshot

- [ ] **Step 1: 写失败测试**

`tests/unit/test_snapshots.py`:

```python
from platform_core.snapshots import build_snapshot


def test_snapshot_contains_only_processed_images_and_is_deterministic():
    images = [
        {"id":"b","processing_status":"processed","labels":["smoke"]},
        {"id":"a","processing_status":"processed","labels":["fire"]},
        {"id":"c","processing_status":"unprocessed","labels":[]},
    ]
    first = build_snapshot(images, ["a"], ["b"], [{"code":"fire"},{"code":"smoke"}], seed=42)
    second = build_snapshot(images, ["a"], ["b"], [{"code":"fire"},{"code":"smoke"}], seed=42)
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["train_image_ids"] == ["a"]
    assert first["val_image_ids"] == ["b"]
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_snapshots.py -v
```

- [ ] **Step 3: 实现 Snapshot 服务**

Snapshot JSON 保存排序后的图片 ID、每张 annotation hash、标签 Schema、每标签数量、seed、创建时间和 SHA-256 `snapshot_id`。保存到 `projects/<pid>/snapshots/<snapshot_id>.json`，已存在时内容必须一致。

- [ ] **Step 4: 修改训练 API 先创建 Snapshot 再入队**

任务只引用 Snapshot；训练中素材变化不得改变当前任务的数据 YAML。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_snapshots.py -v
git add platform_core/snapshots.py app.py tests/unit/test_snapshots.py
git commit -m "feat: lock reproducible training snapshots"
```

### Task 4: Worker 真实消费模型、Snapshot 和全部参数

- [ ] **Step 1: 写失败训练请求测试**

`tests/api/test_training_request.py` 构造任务，断言 job.json 中的 `model` 等于 `base_model_path`，`snapshot_id` 存在，常用与高级训练参数完整写入 `requested_train_params`。

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/api/test_training_request.py -v
```

- [ ] **Step 3: 修改 `train_worker.py:366-594`**

Worker 从 job/snapshot 生成 data.yaml；调用 `YOLO(actual_model).train(**train_args)`。禁止 UI 参数只保存不传入。将 `actual_model`、`actual_train_params` 和 Ultralytics 版本写回 job.json。

- [ ] **Step 4: 训练完成后验证权重可加载**

```python
from ultralytics import YOLO
verified = YOLO(str(best_or_last))
assert verified.model is not None
```

没有 best/last 时失败；不得归档占位模型。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/api/test_training_request.py -v
git add train_worker.py app.py tests/api/test_training_request.py
git commit -m "fix: train from locked snapshot with actual requested parameters"
```

### Task 5: 数据质量使用真实选定素材

- [ ] **Step 1: 写失败质量测试**

`tests/unit/test_quality.py`:

```python
from platform_core.quality import compute_quality


def test_quality_reports_label_imbalance_and_low_resolution():
    rows = [
        {"id":"a","width":1280,"height":720,"boxes":[{"label":"fire"},{"label":"fire"}]},
        {"id":"b","width":320,"height":240,"boxes":[{"label":"smoke"}]},
    ]
    result = compute_quality(rows, min_width=640, min_height=480)
    assert result["label_counts"] == {"fire":2,"smoke":1}
    assert result["low_resolution"] == 1
    assert len(result["radar"]) == 6
    assert any("smoke" in item for item in result["suggestions"])
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_quality.py -v
```

- [ ] **Step 3: 实现六维质量计算**

每个维度输出 0-100 分、原始计数和解释；综合分使用明确权重并写入响应，避免前端自行计算。

- [ ] **Step 4: 修改 `/api/v44/.../data-quality` 只计算请求中的图片 ID 或 Snapshot**

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_quality.py -v
git add platform_core/quality.py app.py tests/unit/test_quality.py
git commit -m "feat: calculate explainable snapshot data quality"
```

### Task 6: 单版本报告和算法综合报告分层

- [ ] **Step 1: 写失败报告测试**

`tests/unit/test_reports.py`:

```python
from platform_core.reports import build_version_report, build_algorithm_report


def test_version_report_keeps_snapshot_and_base_version():
    report = build_version_report({"metrics":{"map50":0.91},"snapshot_id":"s1","base_version_id":"v1"})
    assert report["snapshot_id"] == "s1"
    assert report["base_version_id"] == "v1"
    assert report["metrics"]["map50"] == 0.91


def test_algorithm_report_compares_latest_two_versions():
    report = build_algorithm_report([
        {"version_name":"20260827120000","metrics":{"map50":0.80}},
        {"version_name":"20260828120000","metrics":{"map50":0.90}},
    ])
    assert report["latest_vs_previous"]["map50_delta"] == 0.10
    assert report["best_version"] == "20260828120000"
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_reports.py -v
```

- [ ] **Step 3: 实现报告服务**

单版本报告读取本次 metrics、CSV、confusion matrix、错误样本、Snapshot、训练配置、阶段门禁和产物。算法报告只做历史聚合、最佳版本和相邻版本对比，不伪造单版本细节。

- [ ] **Step 4: 修改 `/api/v44/.../jobs/{job_id}/report` 和 `/api/v49/.../algorithms/{id}/report`**

两个端点返回不同 schema，并各自带 `report_type`。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_reports.py -v
git add platform_core/reports.py app.py tests/unit/test_reports.py
git commit -m "feat: separate version and algorithm training reports"
```

### Task 7: 前端训练弹窗、质量图表和双层报告

- [ ] **Step 1: 写浏览器失败测试**

`tests/browser/training-quality-reports.spec.mjs` 断言：算法行有训练入口；训练弹窗显示当前最新版本和本次基础版本；打开质量弹窗后训练弹窗仍在栈中；质量页有六维图表和标签分布；算法报告与版本报告入口均存在。

- [ ] **Step 2: 运行并确认失败**

```powershell
npx playwright test tests/browser/training-quality-reports.spec.mjs
```

- [ ] **Step 3: 实现 `algorithms.js`、`training.js`、`quality.js`、`reports.js`**

训练任务页只显示进行中与历史记录。训练弹窗默认展示常用参数，高级参数折叠。质量图使用同一响应渲染雷达和标签柱状图。

- [ ] **Step 4: 删除 `static/app.js` 中受影响算法/训练/质量的历史 override**

使用 `rg -n "renderAlgorithms|openTrain|data-quality|algorithm.*report" static/app.js` 确认最终只剩兼容转发，无重复业务实现。

- [ ] **Step 5: 运行并提交**

```powershell
npm test
npx playwright test tests/browser/training-quality-reports.spec.mjs
node --check static/app.js
git add static tests/browser/training-quality-reports.spec.mjs
git commit -m "feat: expose iteration base quality charts and two report levels"
```

### Task 8: 最小真实 YOLO 端到端训练

- [ ] **Step 1: 写 `tests/e2e/test_real_yolo_training.py`**

测试使用 4 张合成图片和真实矩形标注，创建算法、Snapshot 和 1 Epoch CPU 任务；轮询到终态并断言：

```python
assert job["status"] in {"done", "completed", "finished"}
assert Path(job["best_path"] or job["last_path"]).exists()
assert job["artifact_verified"] is True
assert job["auto_version_id"]
assert version_report["report_type"] == "version"
```

- [ ] **Step 2: 运行并观察真实失败**

```powershell
python -m pytest tests/e2e/test_real_yolo_training.py -v -s
```

Expected: 首次在模型下载、参数、Snapshot 或版本归档的真实断点失败；记录具体证据。

- [ ] **Step 3: 只修复测试揭示的真实链路断点**

不得用跳过权重校验、写假 metrics 或生成空 `.pt` 使测试通过。

- [ ] **Step 4: 运行 M3 全套验证**

```powershell
python -m pytest tests/unit/test_algorithms.py tests/unit/test_snapshots.py tests/unit/test_quality.py tests/unit/test_reports.py tests/api/test_algorithm_flow.py tests/api/test_training_request.py tests/e2e/test_real_yolo_training.py -v -s
npx playwright test tests/browser/training-quality-reports.spec.mjs
```

Expected: 全部退出码 0，真实训练产物可加载。

- [ ] **Step 5: 提交 M3**

```powershell
git add .
git commit -m "test: prove reproducible iterative yolo training and reports"
```

## M3 验收门禁

- 创建算法立即显示且重启保留。
- 第二轮训练使用最近可用版本权重并记录原因。
- Snapshot 冻结且可复现。
- 真实 Worker 产生可加载 best/last、指标和算法版本。
- 数据质量使用当前选择或 Snapshot 数据。
- 算法综合报告和单版本报告数据口径分离。

