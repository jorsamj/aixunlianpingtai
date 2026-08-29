# P0 素材持久化、上传分流与真实清洗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保证单张/批量素材上传后永不被后台旧快照覆盖，并让用户可从本次全部缩略图中分别选择真实清洗或无需清洗。

**Architecture:** 新建项目级素材存储仓，所有 `images.json` 变更经过同一把项目锁并使用原子替换；后台索引只提交字段补丁。上传批次和清洗任务持久化，前端使用单一的分页选择器和状态轮询器，停用旧的多层函数包装。

**Tech Stack:** FastAPI、Python `threading.RLock`、Pillow/OpenCV、pytest、ES Modules、Node test、Playwright。

---

## 文件结构

- Create: `platform_core/material_store.py` — 素材索引的项目锁、修订号、原子修改、追加、字段补丁和删除。
- Create: `platform_core/upload_batches.py` — 上传批次持久化与状态汇总。
- Create: `static/modules/material-selection.js` — 分页选择、三态决策和已选数量纯函数。
- Create: `static/modules/task-progress.js` — 清洗/自动标注任务状态转换与轮询决策。
- Modify: `app.py:754-974` — 用素材存储仓替代直接整表写入。
- Modify: `app.py:1255-1370` — 持久化上传批次，后台 annotation 索引改为补丁合并。
- Modify: `app.py:9878-10049` — 清洗执行频率、状态、结果和确认迁移。
- Modify: `app.py:10369-10389` — 无需清洗原子批量迁移。
- Modify: `static/main.mjs` — 导出新的选择和任务状态模块。
- Modify: `static/app.js:2758-2790, 3010-3022, 3192-3225, 3284-3300, 3504-3524` — 删除旧轮询/上传包装，接入唯一的批次工作台。
- Modify: `static/styles.css` — 上传批次分页卡片、三态标识和清洗进度样式。
- Test: `tests/unit/test_material_store.py`
- Test: `tests/unit/test_materials.py`
- Test: `tests/api/test_upload_clean_flow.py`
- Test: `tests/frontend/material-selection.test.mjs`
- Test: `tests/frontend/task-progress.test.mjs`
- Test: `tests/browser/material-workflows.spec.mjs`

### Task 1: 用原子修改仓消除旧快照覆盖

- [ ] **Step 1: 编写能稳定复现丢数据的失败测试**

`tests/unit/test_material_store.py`:

```python
import threading

from platform_core.material_store import MaterialStore


def test_annotation_patch_cannot_overwrite_concurrent_upload(tmp_path):
    store = MaterialStore(tmp_path / "images.json")
    store.upsert({"id": "old", "filename": "old.jpg"})
    stale = store.read().rows
    gate = threading.Barrier(2)

    def background_index():
        gate.wait()
        store.patch({"old": {"annotation_summary_at": "indexed", "box_count": 0}})

    thread = threading.Thread(target=background_index)
    thread.start()
    gate.wait()
    store.upsert({"id": "new", "filename": "new.jpg"})
    thread.join()

    assert [row["id"] for row in store.read().rows] == ["old", "new"]
    assert stale == [{"id": "old", "filename": "old.jpg"}]
    assert store.read().revision >= 3
```

- [ ] **Step 2: 运行测试确认因模块不存在而失败**

Run: `python -m pytest tests/unit/test_material_store.py -v`  
Expected: FAIL with `ModuleNotFoundError: platform_core.material_store`.

- [ ] **Step 3: 实现带修订号的原子素材存储仓**

`platform_core/material_store.py` 核心接口：

```python
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .annotations import atomic_write_json


_LOCK_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


def lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCK_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("images.json 必须是数组")
    return [dict(row) for row in value]


def read_revision(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def write_revision(path: Path, value: int) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_text(str(int(value)), encoding="utf-8")
    temp.replace(path)


@dataclass(frozen=True)
class MaterialSnapshot:
    revision: int
    rows: list[dict[str, Any]]


class MaterialStore:
    def __init__(self, path: Path):
        self.path = path
        self.revision_path = path.with_suffix(".revision")
        self.lock = lock_for(path.resolve())

    def read(self) -> MaterialSnapshot:
        with self.lock:
            return MaterialSnapshot(read_revision(self.revision_path), read_rows(self.path))

    def mutate(self, fn: Callable[[list[dict]], Any]) -> Any:
        with self.lock:
            rows = read_rows(self.path)
            result = fn(rows)
            atomic_write_json(self.path, rows)
            write_revision(self.revision_path, read_revision(self.revision_path) + 1)
            return result

    def upsert(self, record: Mapping[str, Any]) -> dict:
        value = dict(record)
        def apply(rows):
            index = next((i for i, row in enumerate(rows) if str(row.get("id")) == str(value.get("id"))), None)
            if index is None:
                rows.append(value)
            else:
                rows[index] = {**rows[index], **value}
            return dict(value)
        return self.mutate(apply)

    def patch(self, patches: Mapping[str, Mapping[str, Any]]) -> list[dict]:
        normalized = {str(key): dict(value) for key, value in patches.items()}
        def apply(rows):
            changed = []
            for row in rows:
                patch = normalized.get(str(row.get("id")))
                if patch is not None:
                    row.update(patch)
                    changed.append(dict(row))
            return changed
        return self.mutate(apply)

    def remove(self, image_ids: Iterable[str]) -> list[dict]:
        wanted = {str(value) for value in image_ids}
        def apply(rows):
            removed = [dict(row) for row in rows if str(row.get("id")) in wanted]
            rows[:] = [row for row in rows if str(row.get("id")) not in wanted]
            return removed
        return self.mutate(apply)
```

`atomic_write_json` 必须使用同目录临时文件 + `Path.replace()`；修订号另存 `images.revision`，不改变现有 `images.json` 数组格式。

- [ ] **Step 4: 运行并发测试**

Run: `python -m pytest tests/unit/test_material_store.py -v`  
Expected: PASS; 最终同时存在 `old` 和 `new`。

- [ ] **Step 5: 提交原子存储仓**

```powershell
git add platform_core/material_store.py tests/unit/test_material_store.py
git commit -m "fix: serialize material index mutations"
```

### Task 2: 将所有素材变更迁移到修改仓

- [ ] **Step 1: 增加 API 并发回归测试**

在 `tests/api/test_upload_clean_flow.py` 增加：

```python
def upload_png(client, project_id: str, filename: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (filename, image_bytes("checker"), "image/png"))],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    return response.json()["uploaded"][0]


def test_background_annotation_index_cannot_remove_a_new_upload(client, monkeypatch):
    import threading
    import app as app_module

    project = client.post("/api/projects", json={"name": "index-race", "labels": []}).json()
    pid = project["id"]
    first = upload_png(client, pid, "before.png")
    indexed = threading.Event()
    resume = threading.Event()
    original = app_module.read_annotation

    def paused_read(project_id, image_id):
        value = original(project_id, image_id)
        if image_id == first["id"]:
            indexed.set()
            resume.wait(5)
        return value

    monkeypatch.setattr(app_module, "read_annotation", paused_read)
    thread = threading.Thread(target=app_module._v52_annotation_index_worker, args=(pid,))
    thread.start()
    assert indexed.wait(5)
    second = upload_png(client, pid, "during.png")
    resume.set()
    thread.join(5)
    rows = client.get(f"/api/projects/{pid}/images").json()
    assert {row["id"] for row in rows} >= {first["id"], second["id"]}
```

- [ ] **Step 2: 运行用例并确认旧索引整表回写会导致失败**

Run: `python -m pytest tests/api/test_upload_clean_flow.py::test_background_annotation_index_cannot_remove_a_new_upload -v`  
Expected: FAIL; `during.png` 记录缺失。

- [ ] **Step 3: 在 `app.py` 建立项目存储入口并迁移写点**

```python
def material_store(project_id: str) -> MaterialStore:
    return MaterialStore(project_dir(project_id) / "images.json")


def load_images(project_id: str) -> list[dict]:
    return material_store(project_id).read().rows


def add_image_record(...):
    # 文件已完整落盘且 image_info 成功后
    material_store(project_id).upsert(record)
    return record
```

将 `write_annotation`、`_v52_annotation_index_worker`、单删除/批删除、分组更新、导入、无需清洗和清洗确认的 `load -> mutate -> save_images` 改为 `upsert/patch/remove/mutate`。annotation worker 先在锁外生成：

```python
patches[image_id] = {
    **annotation_summary(boxes),
    "annotation_summary_at": annotation.get("updated_at") or now_iso(),
}
material_store(project_id).patch(patches)
```

迁移后运行 `rg -n "save_images\(" app.py`，不得留有业务路由整表写入；历史数据迁移也必须通过 `MaterialStore.mutate`。

- [ ] **Step 4: 运行素材、标注、导入和并发回归**

Run: `python -m pytest tests/unit/test_material_store.py tests/unit/test_materials.py tests/api/test_upload_clean_flow.py tests/api/test_annotation_flow.py -v`  
Expected: PASS; 并发用例中新素材仍存在。

- [ ] **Step 5: 提交写点迁移**

```powershell
git add app.py platform_core/material_store.py tests/api/test_upload_clean_flow.py
git commit -m "fix: prevent stale workers from overwriting uploads"
```

### Task 3: 持久化上传批次和三态决策

- [ ] **Step 1: 编写批次刷新与部分决策失败测试**

在 `tests/api/test_upload_clean_flow.py` 增加：

```python
def upload_many_png(client, project_id: str, names: list[str]) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (name, image_bytes("checker"), "image/png")) for name in names],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    return response.json()


def test_upload_batch_survives_reload_and_tracks_mixed_decisions(client):
    pid = client.post("/api/projects", json={"name": "mixed-batch", "labels": []}).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png", "ready.png", "later.png"])
    batch_id = uploaded["batch_id"]
    client.post(f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions", json={
        "clean_image_ids": [uploaded["uploaded"][0]["id"]],
        "ready_image_ids": [uploaded["uploaded"][1]["id"]],
    }).raise_for_status()
    batch = client.get(f"/api/v55/projects/{pid}/upload-batches/{batch_id}").json()
    assert [item["decision"] for item in batch["items"]] == ["clean", "ready", "pending"]
    rows = {row["id"]: row for row in client.get(f"/api/projects/{pid}/images").json()}
    assert rows[uploaded["uploaded"][1]["id"]]["processing_status"] == "processed"
```

- [ ] **Step 2: 运行确认批次查询端点不存在**

Run: `python -m pytest tests/api/test_upload_clean_flow.py -k upload_batch_survives -v`  
Expected: FAIL with HTTP 404.

- [ ] **Step 3: 实现批次文件和决策端点**

`platform_core/upload_batches.py`:

```python
def create_upload_batch(directory: Path, batch_id: str, image_ids: Sequence[str], created_at: str) -> dict:
    value = {"id": batch_id, "created_at": created_at, "items": [
        {"image_id": str(image_id), "decision": "pending"} for image_id in image_ids
    ]}
    atomic_write_json(directory / f"{batch_id}.json", value)
    return value


def apply_decisions(batch: Mapping, clean_ids: set[str], ready_ids: set[str]) -> dict:
    if clean_ids & ready_ids:
        raise ValueError("同一张图片不能同时选择清洗和无需清洗")
    # 只修改本批次中出现的 image_id，其他保持 pending。
```

`POST /api/projects/{project_id}/images` 在全部文件处理完后保存批次。新增：

- `GET /api/v55/projects/{project_id}/upload-batches/{batch_id}`
- `POST /api/v55/projects/{project_id}/upload-batches/{batch_id}/decisions`

上传新素材统一使用 `processing_status=pending_decision`，读取旧记录时将 `unprocessed` 视为兼容别名。决策端点对 `ready_image_ids` 原子设置 `processing_status=processed, clean_decision=skipped`；对 `clean_image_ids` 设置 `processing_status=cleaning`，创建一个清洗任务并返回 `clean_task_id`。清洗扫描完成后对未删除范围设置 `awaiting_confirmation`，用户确认后设置 `processed`。

- [ ] **Step 4: 运行批次和处理状态回归**

Run: `python -m pytest tests/api/test_upload_clean_flow.py tests/unit/test_materials.py -v`  
Expected: PASS; `later.png` 仍为待决定。

- [ ] **Step 5: 提交上传批次**

```powershell
git add platform_core/upload_batches.py app.py tests/api/test_upload_clean_flow.py
git commit -m "feat: persist per-image upload decisions"
```

### Task 4: 让真实清洗稳定进入待确认状态

- [ ] **Step 1: 增加清洗进度、终态和局部失败测试**

在 `tests/api/test_upload_clean_flow.py` 增加：

```python
def seed_cleaning_inputs(client):
    import app as app_module

    project = client.post("/api/projects", json={"name": "clean-terminal", "labels": []}).json()
    pid = project["id"]
    uploaded = upload_many_png(client, pid, ["normal.png", "duplicate.png", "corrupt.png"])
    corrupt = uploaded["uploaded"][2]
    (app_module.project_dir(pid) / "uploads" / corrupt["stored_name"]).write_bytes(b"broken-image")
    return pid, uploaded["uploaded_image_ids"]


def poll_clean_states(client, project_id: str, task_id: str, timeout: float = 15) -> list[str]:
    states = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v47/projects/{project_id}/clean-tasks/{task_id}/result").json()
        status = body["task"]["status"]
        if not states or states[-1] != status:
            states.append(status)
        if status in {"awaiting_confirmation", "failed", "stopped"}:
            return states
        time.sleep(0.05)
    raise AssertionError(f"clean task {task_id} did not finish: {states}")


def test_clean_task_reaches_review_and_keeps_corrupt_item_as_a_result(client):
    pid, image_ids = seed_cleaning_inputs(client)
    task = client.post(f"/api/v47/projects/{pid}/clean-tasks", json={
        "image_ids": image_ids, "corrupt_check": True, "task_name": "terminal-state"
    }).json()
    states = poll_clean_states(client, pid, task["id"])
    assert states[-1] == "awaiting_confirmation"
    result = client.get(f"/api/v47/projects/{pid}/clean-tasks/{task['id']}/result").json()
    assert result["task"]["progress"] == 100
    assert any(issue["code"] == "corrupt" for item in result["result"]["items"] for issue in item["issues"])
```

- [ ] **Step 2: 运行现有和新增清洗测试并保留旧行为证据**

Run: `python -m pytest tests/api/test_upload_clean_flow.py -v`  
Expected: 新增用例在损坏样本输入/状态记录不完整时 FAIL。

- [ ] **Step 3: 减少任务 JSON 写入并保存阶段信息**

在 `_v47_run_clean_task` 中每张仍执行 `_v47_image_metrics`，但进度只在“每 50 张、500ms 或最后一张”时写入：

```python
if idx == total or idx - last_saved_count >= 50 or time.monotonic() - last_saved_at >= 0.5:
    update_clean_task(
        stage="scanning",
        processed_images=idx,
        total_images=total,
        flagged_images=len(rows),
        progress=round(idx / total * 100),
        heartbeat_at=now_iso(),
    )
```

扫描成功后以一次原子任务更新写入 `status=awaiting_confirmation, stage=review, progress=100`。图片损坏记为 `corrupt` 问题，不使整个任务失败。

- [ ] **Step 4: 验证真实 OpenCV/Pillow 检测和确认迁移**

Run: `python -m pytest tests/api/test_upload_clean_flow.py -v`  
Expected: PASS; 重复、模糊和损坏样本有明确结果，确认后未删除项进入已处理。

- [ ] **Step 5: 提交清洗任务改造**

```powershell
git add app.py tests/api/test_upload_clean_flow.py
git commit -m "fix: complete real cleaning tasks with recoverable progress"
```

### Task 5: 用单一前端状态机替代“清洗中”假死弹窗

- [ ] **Step 1: 编写终态跳转和三态选择失败测试**

`tests/frontend/task-progress.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {nextTaskView, shouldPoll} from '../../static/modules/task-progress.js';

test('cleaning automatically opens review at awaiting_confirmation', () => {
  assert.equal(nextTaskView({status: 'awaiting_confirmation'}), 'review');
  assert.equal(shouldPoll({status: 'awaiting_confirmation'}), false);
});

test('failed and stopped tasks never keep the running view', () => {
  assert.equal(nextTaskView({status: 'failed'}), 'failed');
  assert.equal(nextTaskView({status: 'stopped'}), 'stopped');
});
```

`tests/frontend/material-selection.test.mjs`:

```javascript
test('one upload batch can contain clean ready and pending images', () => {
  const state = assignDecision(createSelection(['a', 'b', 'c']), ['a'], 'clean');
  const mixed = assignDecision(state, ['b'], 'ready');
  assert.deepEqual(decisionGroups(mixed), {clean: ['a'], ready: ['b'], pending: ['c']});
});
```

- [ ] **Step 2: 运行并确认新 ES 模块不存在**

Run: `npm test`  
Expected: FAIL with module-not-found for `task-progress.js` or `material-selection.js`.

- [ ] **Step 3: 实现纯函数并从 `static/main.mjs` 导出**

```javascript
export const RUNNING_TASK_STATUSES = new Set(['queued', 'running']);
export function shouldPoll(task) { return RUNNING_TASK_STATUSES.has(task?.status); }
export function nextTaskView(task) {
  if (task?.status === 'awaiting_confirmation') return 'review';
  if (task?.status === 'failed') return 'failed';
  if (task?.status === 'stopped' || task?.status === 'cancelled') return 'stopped';
  if (task?.status === 'done' || task?.status === 'succeeded') return 'done';
  return 'progress';
}
```

`material-selection.js` 用 `Map<imageId, 'pending'|'clean'|'ready'>` 保存决策，`pageRows(rows,page,pageSize)` 只返回当前页。

- [ ] **Step 4: 将 `showTaskProgress427` 和所有 `doUploadImages426/openBatch414` 包装收敛为一套实现**

轮询每次调用 `renderTask(task)`；当 `nextTaskView(task)==='review'` 时立即调用 `reviewClean427(task.id)`。上传成功直接使用 API 返回的 `uploaded` 列表打开分页批次工作台，不再用 `setInterval` 扫描 DOM 推测上传是否完成。

修改后执行：

```powershell
rg -n "const upload414=|const oldImageUpload412=|querySelector\('\.alert\.ok'\)|showTaskProgress427" static/app.js
```

Expected: 只留一个上传实现和一个任务进度实现，无 DOM 轮询包装。

- [ ] **Step 5: 运行前端测试并提交**

```powershell
npm test
node --check static/app.js
git add static/modules/material-selection.js static/modules/task-progress.js static/main.mjs static/app.js static/styles.css tests/frontend
git commit -m "fix: unify upload decisions and cleaning task transitions"
```

Expected: frontend tests PASS; `static/app.js` 语法检查通过。

### Task 6: 浏览器验证上传、分流、清洗和刷新闭环

- [ ] **Step 1: 扩展 `tests/browser/material-workflows.spec.mjs`**

新用例上传 5 张图片，在同一批次中将 2 张设为需清洗、2 张设为无需清洗、1 张保持待决定；断言全部缩略图存在且决策数量为 2/2/1。提交后等待清洗页自动进入“清洗结果确认”，完成确认后刷新页面，断言无需清洗和清洗保留项在已处理，待决定项在未处理。

- [ ] **Step 2: 运行并保留旧弹窗卡住的失败证据**

Run: `npx playwright test tests/browser/material-workflows.spec.mjs --grep "mixed upload batch"`  
Expected: FAIL before UI consolidation.

- [ ] **Step 3: 修复可访问名称、分页、选择计数和终态跳转**

每个卡片使用 `data-testid="upload-batch-item-{image_id}"`，批次计数使用 `data-testid="upload-decision-counts"`，清洗结果弹窗使用可读标题“清洗结果确认”。

- [ ] **Step 4: 运行 P0 全套验证**

```powershell
python -m pytest tests/unit/test_material_store.py tests/unit/test_materials.py tests/api/test_upload_clean_flow.py tests/api/test_annotation_flow.py -v
npm test
npx playwright test tests/browser/material-workflows.spec.mjs
```

Expected: 全部退出码 0。

- [ ] **Step 5: 提交 P0 闭环证据**

```powershell
git add tests/browser/material-workflows.spec.mjs
git commit -m "test: prove persistent upload and real cleaning workflow"
```

## P0 验收门禁

- 后台 annotation 索引与新上传并发时，新素材记录不丢失。
- 上传后直接显示本批全部缩略图，且同一批次可同时存在需清洗、无需清洗和待决定。
- 无需清洗的未标注图片进入已处理。
- 清洗使用真实 Pillow/OpenCV 指标，完成后自动进入结果确认。
- 数千/数万张选材时只渲染当前页，不创建全量 DOM。
