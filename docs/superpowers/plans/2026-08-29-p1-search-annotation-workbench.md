# P1 素材搜索、标签边界与真实标注工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让素材按文件名、中英文标签和状态正确搜索，并让标注的画框、编辑、保存、刷新、缩略图与训练选材预览使用同一份真实数据。

**Architecture:** 后端提供可分页的素材查询端点，标签查询只使用配置中心标签库。标注端点原子写入并返回规范化素材摘要；前端使用共用 annotation overlay renderer 更新素材库、预览和训练选材。

**Tech Stack:** FastAPI、pytest、ES Modules、SVG/DOM overlay、Node test、Playwright。

---

## 文件结构

- Create: `platform_core/material_search.py` — 搜索文本归一化、标签中英文映射、状态筛选和分页。
- Create: `static/modules/material-query.js` — 查询参数、debounce 和分页结果状态。
- Create: `static/modules/annotation-overlay.js` — 图片像素坐标到百分比叠加层的纯函数。
- Modify: `platform_core/annotations.py` — 稳定 annotation hash、输入校验和规范化摘要。
- Modify: `app.py:884-934, 1336-1370` — annotation 保存返回与素材查询。
- Modify: `app.py:10390-10525` — 标签统计/标注摘要存储使用 P0 修改仓。
- Modify: `static/main.mjs` — 导出 material query 和 annotation overlay。
- Modify: `static/app.js:3235-3330, 3350-3490` — 素材查询、卡片、预览、标注保存和标签选择。
- Modify: `static/styles.css` — 标注框、搜索加载/空状态和配置中心标签管理样式。
- Test: `tests/unit/test_material_search.py`
- Test: `tests/unit/test_annotations.py`
- Test: `tests/api/test_annotation_flow.py`
- Test: `tests/frontend/material-query.test.mjs`
- Test: `tests/frontend/annotation-overlay.test.mjs`
- Test: `tests/browser/material-workflows.spec.mjs`

### Task 1: 服务端分页搜索覆盖文件名、中英文标签和状态

- [ ] **Step 1: 编写失败单元测试**

`tests/unit/test_material_search.py`:

```python
from platform_core.material_search import query_materials


def test_search_matches_filename_english_and_chinese_label():
    rows = [
        {"id": "1", "filename": "flood.jpg", "labels": ["water"], "processing_status": "processed", "annotated": True},
        {"id": "2", "filename": "smoke.jpg", "labels": ["smoke"], "processing_status": "unprocessed", "annotated": False},
    ]
    labels = [
        {"code": "water", "display_name_zh": "内涝", "status": "active"},
        {"code": "smoke", "display_name_zh": "烟雾", "status": "active"},
    ]
    assert [row["id"] for row in query_materials(rows, labels, q="内涝").items] == ["1"]
    assert [row["id"] for row in query_materials(rows, labels, q="water").items] == ["1"]
    assert [row["id"] for row in query_materials(rows, labels, q="smoke.jpg").items] == ["2"]


def test_filters_and_pagination_are_applied_before_rendering():
    rows = [
        {"id": str(index), "filename": f"image-{index}.jpg", "labels": [],
         "processing_status": "processed", "annotated": False}
        for index in range(105)
    ]
    result = query_materials(rows, [], processing_status="processed", page=2, page_size=40)
    assert result.total == 105
    assert len(result.items) == 40
    assert result.page == 2
```

- [ ] **Step 2: 运行确认新搜索模块不存在**

Run: `python -m pytest tests/unit/test_material_search.py -v`  
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现稳定的查询纯函数**

`platform_core/material_search.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialPage:
    items: list[dict]
    total: int
    page: int
    page_size: int


def query_materials(rows, labels, *, q="", processing_status=None,
                    annotation_status=None, label_codes=(), page=1, page_size=60):
    label_text = {
        str(item["code"]): f"{item['code']} {item.get('display_name_zh') or item.get('display_name') or ''}".casefold()
        for item in labels if item.get("code") and item.get("status", "active") == "active"
    }
    needle = str(q or "").strip().casefold()
    selected = {str(code) for code in label_codes}
    matched = []
    for row in rows:
        codes = {str(code) for code in row.get("labels") or []}
        haystack = " ".join([str(row.get("filename") or ""), *(label_text.get(code, code) for code in codes)]).casefold()
        if needle and needle not in haystack:
            continue
        if processing_status and str(row.get("processing_status")) != processing_status:
            continue
        if annotation_status == "annotated" and not row.get("annotated"):
            continue
        if annotation_status == "unannotated" and row.get("annotated"):
            continue
        if selected and not (codes & selected):
            continue
        matched.append(dict(row))
    size = max(1, min(int(page_size), 200))
    current = max(1, int(page))
    start = (current - 1) * size
    return MaterialPage(matched[start:start + size], len(matched), current, size)
```

- [ ] **Step 4: 新增分页 API 并运行测试**

`GET /api/v55/projects/{project_id}/materials` 接受 `q`、`processing_status`、`annotation_status`、重复 `label`、`page`、`page_size`，返回：

```json
{"items":[],"total":0,"page":1,"page_size":60,"revision":12}
```

Run: `python -m pytest tests/unit/test_material_search.py tests/api/test_annotation_flow.py -v`  
Expected: PASS.

- [ ] **Step 5: 提交搜索服务**

```powershell
git add platform_core/material_search.py app.py tests/unit/test_material_search.py
git commit -m "feat: add paginated material search across labels and states"
```

### Task 2: 前端搜索延迟触发并只渲染当前页

- [ ] **Step 1: 编写查询参数和过期响应失败测试**

`tests/frontend/material-query.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {buildMaterialQuery, latestOnly} from '../../static/modules/material-query.js';

test('query contains global text status annotation and repeated labels', () => {
  assert.equal(buildMaterialQuery({q: '内涝', status: 'processed', annotation: 'annotated', labels: ['water', 'rain'], page: 2}),
    'q=%E5%86%85%E6%B6%9D&processing_status=processed&annotation_status=annotated&label=water&label=rain&page=2&page_size=60');
});

test('a slow old search result cannot overwrite the latest query', async () => {
  const gate = latestOnly();
  const old = gate.begin();
  const current = gate.begin();
  assert.equal(gate.accept(old), false);
  assert.equal(gate.accept(current), true);
});
```

- [ ] **Step 2: 运行确认模块不存在**

Run: `npm test`  
Expected: FAIL importing `material-query.js`.

- [ ] **Step 3: 实现查询模块并接入 `static/main.mjs`**

```javascript
export function debounce(fn, wait = 250) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}

export function latestOnly() {
  let revision = 0;
  return {begin: () => ++revision, accept: token => token === revision};
}
```

`buildMaterialQuery` 使用 `URLSearchParams.append('label', code)` 保留多选 OR 语义。

- [ ] **Step 4: 收敛 `dataRows412/renderData412Cards` 为 API 页状态**

页面状态保存 `{items,total,page,pageSize,loading,error,queryToken}`。`oninput` 调用 250ms debounce；只有最新 token 的响应能替换卡片。批量操作必须传递明确的 `selectedIds` 或当前查询条件，不使用浏览器内全量 `state.images` 推测范围。

- [ ] **Step 5: 运行并提交**

```powershell
npm test
node --check static/app.js
git add static/modules/material-query.js static/main.mjs static/app.js tests/frontend/material-query.test.mjs
git commit -m "fix: make material search responsive and paginated"
```

### Task 3: 强化 annotation 原子保存、hash 和服务端回读

- [ ] **Step 1: 增加“只有真实持久化后才成功”的失败测试**

`tests/api/test_annotation_flow.py`:

```python
def test_annotation_response_is_the_persisted_canonical_value(client, seeded_project):
    pid, image = seeded_project
    response = client.post(f"/api/projects/{pid}/annotations/{image['id']}", json={"boxes": [
        {"label": "fire", "x1": 10.12345, "y1": 12.12345, "x2": 80.98765, "y2": 90.98765}
    ]})
    response.raise_for_status()
    body = response.json()
    disk = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert body["annotation"] == disk
    assert body["image"]["annotation_hash"]
    assert body["image"]["annotation_preview"] == disk["boxes"]
```

- [ ] **Step 2: 运行确认当前摘要缺少 hash 或响应不是回读值**

Run: `python -m pytest tests/api/test_annotation_flow.py::test_annotation_response_is_the_persisted_canonical_value -v`  
Expected: FAIL on `annotation_hash` or canonical equality.

- [ ] **Step 3: 在 `platform_core/annotations.py` 生成稳定 hash**

```python
def annotation_hash(boxes: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(list(boxes), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def annotation_summary(boxes):
    normalized = [preview_box(box) for box in boxes]
    return {
        "annotated": bool(normalized),
        "annotation_status": "annotated" if normalized else "unannotated",
        "box_count": len(normalized),
        "labels": sorted({box["label"] for box in normalized}),
        "annotation_preview": normalized[:64],
        "annotation_hash": annotation_hash(normalized),
    }
```

`write_annotation` 原子写入后重新 `read_annotation`，用读回值生成摘要并通过 P0 `MaterialStore.patch`更新。

- [ ] **Step 4: 运行标注单元/API 回归**

Run: `python -m pytest tests/unit/test_annotations.py tests/api/test_annotation_flow.py -v`  
Expected: PASS.

- [ ] **Step 5: 提交 annotation 持久化加固**

```powershell
git add platform_core/annotations.py app.py tests/unit/test_annotations.py tests/api/test_annotation_flow.py
git commit -m "fix: verify persisted annotations before updating previews"
```

### Task 4: 共用标注叠加层并严格分离标签使用/管理

- [ ] **Step 1: 编写坐标叠加层和标签显示失败测试**

`tests/frontend/annotation-overlay.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {overlayBoxes} from '../../static/modules/annotation-overlay.js';

test('overlay uses image coordinates and central label metadata', () => {
  const result = overlayBoxes({width: 200, height: 100}, [
    {label: 'fire', x1: 20, y1: 10, x2: 120, y2: 60}
  ], [{code: 'fire', display_name_zh: '明火', color: '#ff0000'}]);
  assert.deepEqual(result[0], {
    label: 'fire', displayName: 'fire · 明火', color: '#ff0000',
    left: 10, top: 10, width: 50, height: 50
  });
});
```

- [ ] **Step 2: 运行确认共用叠加层尚未存在**

Run: `npm test`  
Expected: FAIL importing `annotation-overlay.js`.

- [ ] **Step 3: 实现 `overlayBoxes` 并导出到 `PlatformCore.annotation`**

坐标百分比限定为 0..100，非法框不渲染；标签名称格式为 `code · display_name_zh`，颜色只来自配置中心标签数据。

- [ ] **Step 4: 替换素材卡片、图片预览和训练选材的三份叠加实现**

`card412`、`previewData429` 和 `renderTrainPicker429` 都调用同一 `renderOverlayHtml(image, state.labels)`。标注弹窗保留“选择已有标签”，但不包含管理标签按钮、新增表单或删除入口；这些入口只在“配置中心 -> 标签管理”。

- [ ] **Step 5: 运行前端回归并提交**

```powershell
npm test
node --check static/app.js
git add static/modules/annotation-overlay.js static/main.mjs static/app.js static/styles.css tests/frontend/annotation-overlay.test.mjs
git commit -m "feat: share persisted annotation overlays across material views"
```

### Task 5: 浏览器验证搜索和完整标注生命周期

- [ ] **Step 1: 扩展 `tests/browser/material-workflows.spec.mjs`**

用例 A 使用 `water/内涝` 标签和文件名，分别搜索“内涝”、`water`、文件名与“已处理 + 已标注”。用例 B 画框、移动、缩放、删除、撤销、重新画框并保存，然后关闭/刷新，断言卡片、预览和重新打开标注器的坐标一致。

- [ ] **Step 2: 运行新用例并确认旧搜索只匹配文件名**

Run: `npx playwright test tests/browser/material-workflows.spec.mjs`  
Expected: FAIL on Chinese label search before the new endpoint is wired.

- [ ] **Step 3: 修正标注编辑器指针映射、按钮可访问名和保存状态**

保存按钮给出 `保存中… -> 已保存 · N框 / 保存失败：原因`；失败不清空未保存标记。每个标注框具有 `data-label-code`和稳定 `data-testid`。

- [ ] **Step 4: 运行 P1 全套验证**

```powershell
python -m pytest tests/unit/test_material_search.py tests/unit/test_annotations.py tests/api/test_annotation_flow.py -v
npm test
npx playwright test tests/browser/material-workflows.spec.mjs
```

Expected: 全部退出码 0。

- [ ] **Step 5: 提交 P1 闭环证据**

```powershell
git add tests/browser/material-workflows.spec.mjs
git commit -m "test: prove searchable persistent annotation workflow"
```

## P1 验收门禁

- 搜索覆盖文件名、英文标签、中文名称、处理和标注状态。
- 数万张数据下前端只渲染当前页，过期搜索响应不覆盖新结果。
- 标注框的画、改、删、撤销、保存和刷新均使用真实持久数据。
- 素材卡片、预览和训练选材显示相同的标注框和中英文标签。
- 标注页只选择标签，标签管理只在配置中心。
