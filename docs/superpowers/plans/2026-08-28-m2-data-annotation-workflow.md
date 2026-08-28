# M2 标签、素材、上传、清洗与人工标注 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让标签、素材处理状态、上传批次、清洗和矩形标注形成真实持久化且跨页面一致的数据闭环。

**Architecture:** `platform_core` 中建立标签、annotation 和素材工作流服务；旧 API 路由只做输入输出适配。前端使用标签库统一筛选和标注下拉，保存后用后端返回的完整素材对象局部替换状态。

**Tech Stack:** FastAPI、Pydantic、Pillow、OpenCV、pytest、ES Modules、Playwright。

---

## 文件结构

- Create: `platform_core/labels.py`
- Create: `platform_core/annotations.py`
- Create: `platform_core/materials.py`
- Create: `static/modules/labels.js`
- Create: `static/modules/materials.js`
- Create: `static/modules/annotation.js`
- Create: `static/modules/upload.js`
- Create: `static/modules/cleaning.js`
- Modify: `app.py:718-935` — 图片与 annotation 存取调用服务。
- Modify: `app.py:4004-4087` — 标签 API 调用服务。
- Modify: `app.py:9498-9988` — 素材、清洗、候选标注确认调用服务。
- Modify: `static/app.js` — 移除对应业务 override。
- Test: `tests/unit/test_labels.py`
- Test: `tests/unit/test_annotations.py`
- Test: `tests/unit/test_materials.py`
- Test: `tests/api/test_annotation_flow.py`
- Test: `tests/api/test_upload_clean_flow.py`
- Test: `tests/frontend/materials.test.mjs`
- Test: `tests/browser/annotation-flow.spec.mjs`
- Test: `tests/browser/upload-clean-flow.spec.mjs`

### Task 1: 标签库成为唯一权威来源

- [ ] **Step 1: 写失败单元测试**

`tests/unit/test_labels.py`:

```python
from platform_core.labels import active_label_options, labels_match_any


LABELS = [
    {"class_id": 0, "code": "fire", "display_name_zh": "明火", "status": "active"},
    {"class_id": 1, "code": "smoke", "display_name_zh": "烟雾", "status": "active"},
    {"class_id": 2, "code": "helmet", "display_name_zh": "安全帽", "status": "disabled"},
]


def test_only_active_labels_are_selectable():
    assert [item["code"] for item in active_label_options(LABELS)] == ["fire", "smoke"]


def test_material_filter_uses_or_logic():
    assert labels_match_any(["fire"], {"smoke", "fire"})
    assert labels_match_any(["smoke"], {"smoke", "fire"})
    assert not labels_match_any(["person"], {"smoke", "fire"})
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_labels.py -v
```

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现标签纯函数**

`platform_core/labels.py`:

```python
from typing import Iterable, Mapping, Sequence


def active_label_options(items: Sequence[Mapping]) -> list[dict]:
    return [dict(item) for item in items if str(item.get("status") or "active") == "active"]


def labels_match_any(image_labels: Iterable[str], selected: set[str]) -> bool:
    return not selected or bool({str(x) for x in image_labels} & selected)


def label_by_code(items: Sequence[Mapping], code: str) -> dict:
    match = next((dict(item) for item in items if str(item.get("code")) == str(code)), None)
    if not match:
        raise KeyError(code)
    return match
```

- [ ] **Step 4: 将 `/api/v54/.../label-schema` 和 `/api/v12/.../labels` 统一调用 `project_label_items` + `active_label_options`**

响应必须包含 `code`、`display_name_zh`、`status`、使用图片数和框数；前端不得从图片列表推导筛选标签。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_labels.py -v
git add platform_core/labels.py app.py tests/unit/test_labels.py
git commit -m "fix: make label schema the only material filter source"
```

Expected: 2 passed。

### Task 2: annotation 原子保存与摘要同步

- [ ] **Step 1: 写失败单元测试**

`tests/unit/test_annotations.py`:

```python
import pytest
from platform_core.annotations import normalize_boxes, annotation_summary


def test_invalid_coordinates_are_rejected():
    with pytest.raises(ValueError, match="坐标"):
        normalize_boxes([{"label":"fire","x1":20,"y1":10,"x2":10,"y2":30}], 100, 100, {"fire":0})


def test_summary_contains_preview_and_status():
    boxes = normalize_boxes([{"label":"fire","x1":1,"y1":2,"x2":20,"y2":30}], 100, 100, {"fire":0})
    summary = annotation_summary(boxes)
    assert summary["labels"] == ["fire"]
    assert summary["box_count"] == 1
    assert summary["annotation_status"] == "annotated"
    assert summary["annotation_preview"][0]["label"] == "fire"
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_annotations.py -v
```

Expected: FAIL，目标模块不存在。

- [ ] **Step 3: 实现坐标规范化、摘要和原子 JSON 写入**

`platform_core/annotations.py` 必须使用：

```python
def atomic_write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
```

`normalize_boxes` 将数值转为 float，验证有限值和图片边界，并根据标签 code 写入稳定 class_id。`annotation_summary` 返回 labels、box_count、annotation_status 和最多 32 个预览框。

- [ ] **Step 4: 修改 `app.py:860-925` 的 `write_annotation` 使用新服务并返回完整素材对象**

保存响应格式：

```json
{"ok":true,"annotation":{"boxes":[]},"image":{"id":"...","labels":[],"box_count":0,"annotation_status":"unannotated","annotation_preview":[]}}
```

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_annotations.py -v
git add platform_core/annotations.py app.py tests/unit/test_annotations.py
git commit -m "fix: atomically persist annotations and material summaries"
```

### Task 3: API 证明刷新后 annotation 仍存在

- [ ] **Step 1: 写失败 API 测试**

`tests/api/test_annotation_flow.py`:

```python
def test_save_reload_and_thumbnail_summary_match(client, seeded_project):
    pid, image = seeded_project
    saved = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes":[{"label":"fire","x1":10,"y1":10,"x2":80,"y2":90}]},
    )
    assert saved.status_code == 200
    material = saved.json()["image"]
    assert material["labels"] == ["fire"]
    assert material["box_count"] == 1
    reloaded = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert reloaded["boxes"] == saved.json()["annotation"]["boxes"]
    listed = client.get(f"/api/projects/{pid}/images?dataset_id=default").json()
    row = next(item for item in listed if item["id"] == image["id"])
    assert row["annotation_preview"] == material["annotation_preview"]
```

- [ ] **Step 2: 运行并确认旧响应或摘要不一致导致失败**

```powershell
python -m pytest tests/api/test_annotation_flow.py -v
```

- [ ] **Step 3: 修复 annotation POST 路由的输入模型、标签校验和返回值**

禁止保存未知标签；错误使用 `ANNOTATION_LABEL_NOT_FOUND`。有框时设置 `processing_status=processed`。

- [ ] **Step 4: 运行回归**

```powershell
python -m pytest tests/unit/test_annotations.py tests/api/test_annotation_flow.py -v
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```powershell
git add app.py tests/api/test_annotation_flow.py
git commit -m "test: prove annotation survives reload and updates preview"
```

### Task 4: 素材处理状态和上传批次

- [ ] **Step 1: 写失败状态测试**

`tests/unit/test_materials.py`:

```python
from platform_core.materials import initial_processing_status, mark_ready


def test_imported_annotation_is_processed():
    assert initial_processing_status(has_valid_boxes=True) == "processed"


def test_raw_upload_is_unprocessed():
    assert initial_processing_status(has_valid_boxes=False) == "unprocessed"


def test_mark_ready_records_explicit_decision():
    result = mark_ready({"id":"i1","processing_status":"unprocessed"}, "2026-08-28T10:00:00")
    assert result["processing_status"] == "processed"
    assert result["clean_skipped"] is True
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_materials.py -v
```

- [ ] **Step 3: 实现状态函数并应用到单图、多图和 ZIP 导入**

所有上传响应增加 `batch_id` 和 `uploaded_image_ids`。ZIP job report 保留 `imported_image_ids`，供统一批次窗口读取。

- [ ] **Step 4: 修改 `/api/v52/.../images/mark-ready` 返回规范化的 `images` 列表**

前端使用返回列表局部替换，不调用 `loadAll()`。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/unit/test_materials.py -v
git add platform_core/materials.py app.py tests/unit/test_materials.py
git commit -m "feat: separate material processing and annotation status"
```

### Task 5: 两阶段清洗必须只删除确认项

- [ ] **Step 1: 写失败 API 测试**

`tests/api/test_upload_clean_flow.py` 创建三张合成图片，其中一张重复、一张模糊、一张正常；为重复图片写 annotation。测试扫描后取消一个建议项，再确认删除，断言只有选中项的图片、annotation 和索引消失。

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/api/test_upload_clean_flow.py -v
```

- [ ] **Step 3: 重构 `app.py:9578-9738` 调用 `platform_core/materials.py`**

扫描结果每项必须包含：`image_id`、`filename`、`issues[{code,name,detail}]`、`suggest_delete`。确认接口只接受 `delete_ids`，逐项级联删除并返回 `deleted_images` 和 `failed_items`。

- [ ] **Step 4: 运行 API 回归**

```powershell
python -m pytest tests/api/test_upload_clean_flow.py -v
```

Expected: 通过，取消项仍存在且 annotation 完整。

- [ ] **Step 5: 提交**

```powershell
git add platform_core/materials.py app.py tests/api/test_upload_clean_flow.py
git commit -m "fix: make cleaning a confirmed cascading operation"
```

### Task 6: 前端素材、标签和标注局部同步

- [ ] **Step 1: 写失败前端测试**

`tests/frontend/materials.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {replaceMaterial, filterByAnyLabel} from '../../static/modules/materials.js';

test('saved annotation replaces only its material', () => {
  const before=[{id:'a',box_count:0},{id:'b',box_count:2}];
  const after=replaceMaterial(before,{id:'a',box_count:1,labels:['fire']});
  assert.deepEqual(after[0],{id:'a',box_count:1,labels:['fire']});
  assert.equal(after[1],before[1]);
});

test('multi label filter is OR', () => {
  const rows=[{id:'a',labels:['fire']},{id:'b',labels:['smoke']},{id:'c',labels:['person']}];
  assert.deepEqual(filterByAnyLabel(rows,new Set(['fire','smoke'])).map(x=>x.id),['a','b']);
});
```

- [ ] **Step 2: 运行并确认失败**

```powershell
npm test
```

- [ ] **Step 3: 实现 `labels.js`、`materials.js`、`annotation.js`**

`annotation.js` 保存成功后调用 `replaceMaterial`，重绘当前缩略图和预览，不执行 `location.reload()` 或 `loadAll()`。标注侧栏只显示标签选择，不显示“管理标签”。

- [ ] **Step 4: 实现未处理页和导入批次窗口**

未处理工具栏显示“批量清洗”“批量无需清洗”；单图、多图和 ZIP 成功后统一调用 `openImportBatch(batchId, imageIds)`。

- [ ] **Step 5: 运行并提交**

```powershell
npm test
node --check static/app.js
git add static/modules static/app.js tests/frontend/materials.test.mjs
git commit -m "feat: synchronize material cards with persisted annotations"
```

### Task 7: 浏览器端完整标注和清洗回归

- [ ] **Step 1: 写 `tests/browser/annotation-flow.spec.mjs`**

测试步骤：创建标签 `fire/明火` → 上传合成图片 → 无需清洗 → 打开标注 → 画框 → 保存 → 关闭 → 缩略图显示 1 框 → 打开预览显示红框 → 刷新 → 状态仍一致。

- [ ] **Step 2: 写 `tests/browser/upload-clean-flow.spec.mjs`**

测试步骤：上传多图 → 出现本批次窗口 → 全选/反选 → 批量清洗 → 查看问题 → 取消一个删除 → 确认 → 只删除选中项。

- [ ] **Step 3: 运行并记录旧界面失败证据**

```powershell
npx playwright test tests/browser/annotation-flow.spec.mjs tests/browser/upload-clean-flow.spec.mjs
```

- [ ] **Step 4: 修复可访问名称、事件绑定和弹窗栈直至通过**

不得用固定坐标规避 DOM 交互问题；按钮必须有稳定名称或 `data-testid`。

- [ ] **Step 5: 运行 M2 全套并提交**

```powershell
python -m pytest tests/unit/test_labels.py tests/unit/test_annotations.py tests/unit/test_materials.py tests/api/test_annotation_flow.py tests/api/test_upload_clean_flow.py -v
npm test
npx playwright test tests/browser/annotation-flow.spec.mjs tests/browser/upload-clean-flow.spec.mjs
git add .
git commit -m "test: verify material cleaning and annotation lifecycle"
```

## M2 验收门禁

- 标签筛选和标注下拉只来自标签库。
- 标注编辑器不维护全局标签。
- 保存 annotation 后刷新仍存在，卡片、缩略图和预览一致。
- 未处理页与上传批次均提供清洗和无需清洗。
- 清洗只删除最终确认项并级联删除 annotation。
- 全部自动化数据写入隔离目录。

