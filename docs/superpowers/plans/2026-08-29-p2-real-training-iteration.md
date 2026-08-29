# P2 随机试验集、真实训练与版本迭代 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户选择的已标注素材真正构建为训练/试验数据快照，每个自动任务使用新随机种子，并确保算法迭代从最新成功权重开始真实训练。

**Architecture:** 数据拆分在服务端完成，任务提交时产生不可变 Snapshot，数据集构建以 Snapshot 的显式 `train_image_ids/val_image_ids` 为准，不再依赖素材的历史 `split`。版本基础选择返回可见证据；最新版本损坏时要求用户明确确认上一可用版本。

**Tech Stack:** FastAPI、Pydantic、Ultralytics/PyTorch、pytest、ES Modules、Playwright。

---

## 文件结构

- Create: `platform_core/training_split.py` — 随机种子生成、自动/手动拆分校验和可复现结果。
- Modify: `platform_core/algorithms.py` — 最新版本/可用版本分离和显式回退确认。
- Modify: `platform_core/snapshots.py` — 保存 split mode、百分比、随机种子、素材角色和父版本证据。
- Create: `static/modules/training-request.js` — 训练表单、自动/手动选材和提交状态纯函数。
- Modify: `app.py:3154-3235` — 扩展 `TrainReq`。
- Modify: `app.py:4034-4095` — 对本次已选素材进行质量预检。
- Modify: `app.py:4445-4675` — 显式 ID 构建数据集、服务端拆分、Snapshot 和训练提交。
- Modify: `app.py:10620-10635` — 迭代基础端点返回需确认状态。
- Modify: `static/main.mjs` — 导出 training request 模块。
- Modify: `static/app.js:3041-3055, 3325-3338, 3534-3543` — 收敛为单一训练弹窗、可见标注选材、试验比例和持久错误。
- Modify: `tests/unit/test_snapshots.py`
- Create: `tests/unit/test_training_split.py`
- Modify: `tests/unit/test_algorithms.py`
- Modify: `tests/api/test_training_request.py`
- Modify: `tests/e2e/test_real_yolo_training.py`
- Modify: `tests/frontend/training.test.mjs`
- Modify: `tests/browser/training-quality-reports.spec.mjs`

### Task 1: 服务端生成每任务新随机拆分并保持可复现

- [ ] **Step 1: 编写随机拆分失败测试**

`tests/unit/test_training_split.py`:

```python
import pytest

from platform_core.training_split import build_training_split


def test_auto_split_uses_requested_percentage_and_has_no_overlap():
    result = build_training_split([f"i{i}" for i in range(10)], mode="random", val_percent=30, seed=123)
    assert len(result.train_image_ids) == 7
    assert len(result.val_image_ids) == 3
    assert set(result.train_image_ids).isdisjoint(result.val_image_ids)


def test_same_seed_reproduces_and_different_seed_changes_membership():
    ids = [f"i{i}" for i in range(20)]
    first = build_training_split(ids, mode="random", val_percent=20, seed=123)
    replay = build_training_split(ids, mode="random", val_percent=20, seed=123)
    another = build_training_split(ids, mode="random", val_percent=20, seed=456)
    assert first == replay
    assert first.val_image_ids != another.val_image_ids


def test_manual_split_rejects_overlap():
    with pytest.raises(ValueError, match="重复"):
        build_training_split([], mode="manual", train_image_ids=["a"], val_image_ids=["a"])
```

- [ ] **Step 2: 运行确认新模块不存在**

Run: `python -m pytest tests/unit/test_training_split.py -v`  
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现自动和手动拆分**

`platform_core/training_split.py`:

```python
import random
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingSplit:
    mode: str
    seed: int
    val_percent: float
    train_image_ids: list[str]
    val_image_ids: list[str]


def build_training_split(selected_ids=(), *, mode="random", val_percent=20,
                         seed=None, train_image_ids=(), val_image_ids=()):
    if mode == "manual":
        train = list(dict.fromkeys(map(str, train_image_ids)))
        val = list(dict.fromkeys(map(str, val_image_ids)))
        if set(train) & set(val):
            raise ValueError("训练素材和试验素材不能重复")
        if not train or not val:
            raise ValueError("手动模式必须同时选择训练素材和试验素材")
        return TrainingSplit("manual", int(seed or 0), 0, train, val)
    ids = list(dict.fromkeys(map(str, selected_ids)))
    if len(ids) < 2:
        raise ValueError("至少需要2张已标注素材")
    percent = max(1.0, min(50.0, float(val_percent)))
    actual_seed = int(seed if seed is not None else secrets.randbits(63))
    random.Random(actual_seed).shuffle(ids)
    count = max(1, min(len(ids) - 1, round(len(ids) * percent / 100)))
    return TrainingSplit("random", actual_seed, percent, ids[count:], ids[:count])
```

- [ ] **Step 4: 运行随机拆分测试**

Run: `python -m pytest tests/unit/test_training_split.py -v`  
Expected: PASS.

- [ ] **Step 5: 提交拆分服务**

```powershell
git add platform_core/training_split.py tests/unit/test_training_split.py
git commit -m "feat: create reproducible random validation splits"
```

### Task 2: 训练数据集以明确角色 ID 为准，不再受历史 split 字段阻断

- [ ] **Step 1: 增加未分组素材仍可训练的失败 API 测试**

在 `tests/api/test_training_request.py` 新增：

```python
def upload_annotated_image(client, project_id: str, filename: str, label: str) -> dict:
    uploaded = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (filename, _image_bytes("gray"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    class_id = {"fire": 0, "smoke": 1}[label]
    response = client.post(f"/api/projects/{project_id}/annotations/{uploaded['id']}", json={
        "boxes": [{"class_id": class_id, "label": label, "x1": 20, "y1": 20, "x2": 90, "y2": 90}]
    })
    response.raise_for_status()
    return uploaded


def create_algorithm(client, project_id: str) -> str:
    response = client.post(f"/api/v12/projects/{project_id}/algorithms", json={
        "name": "显式角色训练", "industry": "测试", "algorithm_type": "yolo_ultralytics", "remark": ""
    })
    response.raise_for_status()
    return response.json()["algorithm"]["id"]


def minimal_train_request(algorithm_id: str) -> dict:
    return {
        "framework": "ultralytics", "algorithm": "yolo11n_det",
        "algorithm_asset_id": algorithm_id, "model": "yolo11n.pt",
        "epochs": 1, "imgsz": 128, "batch": 2, "device": "cpu", "workers": 0,
    }


def test_explicit_training_roles_ignore_historical_material_split(client, seeded_project, monkeypatch):
    import app as app_module
    pid, first = seeded_project
    client.post(f"/api/projects/{pid}/annotations/{first['id']}", json={
        "boxes": [{"class_id": 0, "label": "fire", "x1": 20, "y1": 20, "x2": 90, "y2": 90}]
    }).raise_for_status()
    second = upload_annotated_image(client, pid, "second.jpg", "smoke")
    # 两张保持 upload 默认 unassigned，不 PATCH split。
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues", lambda _pid: None)
    algorithm_id = create_algorithm(client, pid)
    response = client.post(f"/api/v12/projects/{pid}/train/start", json={
        **minimal_train_request(algorithm_id),
        "split_mode": "manual",
        "train_image_ids": [first["id"]],
        "val_image_ids": [second["id"]],
    })
    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["dataset_counts"]["train"] == 1
    assert job["dataset_counts"]["val"] == 1
```

- [ ] **Step 2: 运行确认 `build_yolo_dataset_v44` 丢弃 `unassigned` 而失败**

Run: `python -m pytest tests/api/test_training_request.py::test_explicit_training_roles_ignore_historical_material_split -v`  
Expected: FAIL with empty training/validation dataset.

- [ ] **Step 3: 重写 `build_yolo_dataset_v44` 的角色选择**

```python
role_by_id = {str(image_id): "train" for image_id in payload.train_image_ids or []}
role_by_id.update({str(image_id): "val" for image_id in payload.val_image_ids or []})
for image in load_images(project_id):
    role = role_by_id.get(str(image["id"]))
    if role is None:
        continue
    annotation = read_annotation(project_id, image["id"])
    boxes = validate_training_boxes(annotation.get("boxes") or [], label_ids)
    if not boxes and not payload.include_empty:
        raise HTTPException(status_code=422, detail=f"训练素材 {image['filename']} 没有有效标注框")
    groups[role].append((image, {"boxes": boxes}))
```

`test` 角色仍可在未来从任务快照扩展，本次训练必须保证 train/val 都非空。

- [ ] **Step 4: 运行数据构建和 Snapshot 回归**

Run: `python -m pytest tests/api/test_training_request.py tests/unit/test_snapshots.py -v`  
Expected: PASS.

- [ ] **Step 5: 提交显式角色数据集**

```powershell
git add app.py tests/api/test_training_request.py
git commit -m "fix: build training datasets from explicit task roles"
```

### Task 3: 扩展训练请求和 Snapshot，由后端材化每次随机结果

- [ ] **Step 1: 编写连续自动任务不同但单任务可复现的失败测试**

```python
def seed_training_pool(client, count: int):
    project = client.post("/api/projects", json={
        "name": "random-split-pool",
        "labels": [{"code": "fire", "display_name": "明火"}, {"code": "smoke", "display_name": "烟雾"}],
    }).json()
    image_ids = []
    for index in range(count):
        label = "fire" if index % 2 == 0 else "smoke"
        image = upload_annotated_image(client, project["id"], f"sample-{index}.jpg", label)
        image_ids.append(image["id"])
    return project["id"], create_algorithm(client, project["id"]), image_ids


def test_random_split_is_generated_per_job_and_persisted(client, monkeypatch):
    import json
    from pathlib import Path
    import app as app_module
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues", lambda _pid: None)
    pid, algorithm_id, image_ids = seed_training_pool(client, count=10)
    payload = {**minimal_train_request(algorithm_id), "split_mode": "random",
               "selected_image_ids": image_ids, "val_percent": 30}
    first = client.post(f"/api/v12/projects/{pid}/train/start", json=payload).json()["job"]
    second = client.post(f"/api/v12/projects/{pid}/train/start", json=payload).json()["job"]
    assert first["split_seed"] != second["split_seed"]
    assert len(first["val_image_ids"]) == len(second["val_image_ids"]) == 3
    snapshot = json.loads(Path(first["snapshot_path"]).read_text(encoding="utf-8"))
    replay = build_training_split(image_ids, mode="random", val_percent=30, seed=first["split_seed"])
    assert snapshot["val_image_ids"] == sorted(replay.val_image_ids)
```

- [ ] **Step 2: 运行确认当前客户端固定 seed 不满足用例**

Run: `python -m pytest tests/api/test_training_request.py -k random_split_is_generated -v`  
Expected: FAIL because `selected_image_ids/split_mode/val_percent` are not materialized by the backend.

- [ ] **Step 3: 扩展 `TrainReq` 并在 `v12_start_train` 最前面生成 split**

```python
from typing import Literal

from pydantic import Field


class TrainReq(BaseModel):
    split_mode: Literal["random", "manual"] = "random"
    selected_image_ids: list[str] = Field(default_factory=list)
    val_percent: float = 20.0
    split_seed: int | None = None
    train_image_ids: list[str] = Field(default_factory=list)
    val_image_ids: list[str] = Field(default_factory=list)
    confirmed_base_version_id: str = ""
    # 保留现有训练参数字段
```

`v12_start_train` 调用 `build_training_split`，将结果写回局部 payload 副本，再进行本次已选素材质量检查。job 和 Snapshot 同时保存 `split_mode`、`val_percent`、`split_seed`、`train_image_ids`、`val_image_ids`。

- [ ] **Step 4: 运行 API/Snapshot 回归**

Run: `python -m pytest tests/unit/test_training_split.py tests/unit/test_snapshots.py tests/api/test_training_request.py -v`  
Expected: PASS.

- [ ] **Step 5: 提交后端训练快照**

```powershell
git add platform_core/training_split.py platform_core/snapshots.py app.py tests/unit/test_snapshots.py tests/api/test_training_request.py
git commit -m "feat: persist per-job training and validation snapshots"
```

### Task 4: 版本迭代必须使用最新成功权重，回退时需明确确认

- [ ] **Step 1: 增加最新版本损坏和上一可用版本测试**

`tests/unit/test_algorithms.py`:

```python
def test_missing_latest_version_requires_explicit_fallback_confirmation(tmp_path):
    usable = tmp_path / "v1.pt"
    usable.write_bytes(b"checkpoint")
    result = inspect_iteration_base([
        {"id": "v2", "version_name": "V2", "finished_at": "2026-08-29T02:00:00", "best_path": str(tmp_path / "missing.pt")},
        {"id": "v1", "version_name": "V1", "finished_at": "2026-08-29T01:00:00", "best_path": str(usable)},
    ], "mother.pt", "ultralytics")
    assert result["requires_confirmation"] is True
    assert result["latest_version_id"] == "v2"
    assert result["suggested_base_version_id"] == "v1"
```

- [ ] **Step 2: 运行确认当前 `choose_iteration_base` 静默跳过 V2**

Run: `python -m pytest tests/unit/test_algorithms.py -v`  
Expected: FAIL; old result has no `requires_confirmation`.

- [ ] **Step 3: 实现 `inspect_iteration_base` 并保留 `choose_iteration_base` 兼容入口**

`inspect_iteration_base` 同时返回 latest version 和 latest usable version。当两者不同时，`v12_start_train` 要求 `confirmed_base_version_id == suggested_base_version_id`，否则返回 `409 ITERATION_BASE_CONFIRMATION_REQUIRED`，不回退母模型。

- [ ] **Step 4: 运行算法/API 回归**

Run: `python -m pytest tests/unit/test_algorithms.py tests/api/test_training_request.py -v`  
Expected: PASS; job 中 `base_version_id/base_model_path/parent_version_id` 与实际权重一致。

- [ ] **Step 5: 提交版本继承规则**

```powershell
git add platform_core/algorithms.py app.py tests/unit/test_algorithms.py tests/api/test_training_request.py
git commit -m "fix: require explicit evidence for iteration base selection"
```

### Task 5: 统一训练弹窗、可见标注选材和提交反馈

- [ ] **Step 1: 编写训练请求与表单状态失败测试**

`tests/frontend/training.test.mjs`:

```javascript
import {buildTrainingRequest, trainingSubmitState} from '../../static/modules/training-request.js';

test('random mode sends one pool and a configurable validation percentage', () => {
  const request = buildTrainingRequest({mode: 'random', selectedIds: ['a', 'b', 'c'], valPercent: 33});
  assert.deepEqual(request, {split_mode: 'random', selected_image_ids: ['a', 'b', 'c'], val_percent: 33});
});

test('manual mode sends separate non-overlapping roles', () => {
  const request = buildTrainingRequest({mode: 'manual', trainIds: ['a', 'b'], valIds: ['c']});
  assert.deepEqual(request, {split_mode: 'manual', train_image_ids: ['a', 'b'], val_image_ids: ['c']});
});

test('submission failure remains visible in the dialog', () => {
  assert.deepEqual(trainingSubmitState('failed', '训练集没有标注'), {busy: false, message: '训练集没有标注', tone: 'error'});
});
```

- [ ] **Step 2: 运行确认请求模块不存在**

Run: `npm test`  
Expected: FAIL importing `training-request.js`.

- [ ] **Step 3: 实现请求模块并收敛训练页面**

训练弹窗增加“自动随机抽取/手动指定”切换、`1..50%` 试验集百分比和分别选材的标签页签。`renderTrainPicker429` 使用 P1 的 `renderOverlayHtml`，每张显示标注框和中英文标签。

`submitTrain429` 不再在浏览器调用 `splitIds429`；它立即禁用按钮，将服务端返回的任务号写入弹窗。API 失败时保留弹窗并在 `#trainingSubmitMessage` 显示错误和 solution。

- [ ] **Step 4: 运行前端测试**

Run: `npm test; node --check static/app.js`  
Expected: PASS and exit code 0.

- [ ] **Step 5: 提交训练弹窗**

```powershell
git add static/modules/training-request.js static/main.mjs static/app.js static/styles.css tests/frontend/training.test.mjs
git commit -m "feat: submit visible random or manual training roles"
```

### Task 6: 真实运行两代 YOLO 训练并验证权重继承

- [ ] **Step 1: 扩展 `tests/e2e/test_real_yolo_training.py` 为两次真实训练**

第一次使用 4 张真实合成图、1 epoch、CPU、128 尺寸，等待生成可加载 `best.pt`。第二次使用同一 algorithm asset 再启动 1 epoch，断言：

```python
from platform_core.conversion import sha256_file

assert second_job["base_version_id"] == first_job["auto_version_id"]
assert sha256_file(Path(second_job["base_model_path"])) == sha256_file(Path(first_artifact))
assert second_job["base_selection_reason"] == "latest_usable_version"
assert second_job["artifact_verified"] is True
```

- [ ] **Step 2: 运行 API 与浏览器用例并保留当前失败证据**

```powershell
python -m pytest tests/api/test_training_request.py -v
npx playwright test tests/browser/training-quality-reports.spec.mjs
```

Expected: 新随机比例/标注叠加断言在旧 UI 上 FAIL。

- [ ] **Step 3: 扩展浏览器用例**

`training-quality-reports.spec.mjs` 断言：标注选材卡片有 `.annotation-overlay-box`；试验集比例可设为 30；点击开始后立即显示“正在提交”；成功显示任务号；拦截 422 时弹窗内显示持久错误。

- [ ] **Step 4: 运行 P2 全套，包含真实两代 CPU 训练**

```powershell
python -m pytest tests/unit/test_training_split.py tests/unit/test_snapshots.py tests/unit/test_algorithms.py tests/api/test_training_request.py -v
npm test
npx playwright test tests/browser/training-quality-reports.spec.mjs
python -m pytest tests/e2e/test_real_yolo_training.py -v -s
```

Expected: 全部退出码 0；两次训练都生成可加载权重，第二次的基础路径等于第一次产物。

- [ ] **Step 5: 提交 P2 真实验收证据**

```powershell
git add tests/e2e/test_real_yolo_training.py tests/browser/training-quality-reports.spec.mjs
git commit -m "test: prove real random-split iterative yolo training"
```

## P2 验收门禁

- 自动模式每个任务产生新 seed，且每个任务可通过 seed 复现。
- 手动模式可分别选择训练素材和试验素材。
- 数据集以任务快照的明确角色为准，不受素材历史 split 字段影响。
- 训练选材显示标注框和中英文标签。
- 点击开始训练必须立即反馈任务号或可操作错误。
- 第二代真实训练的起始权重是第一代的最新成功产物。
