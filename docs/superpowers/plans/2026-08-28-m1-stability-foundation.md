# M1 稳定基础与交互审计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立隔离测试、恢复机制、统一错误和唯一交互入口，确保 Windows 启动与历史数据只读兼容稳定。

**Architecture:** 新建 `platform_core` 提供数据目录、错误和启动选择纯函数；FastAPI 旧路由调用这些函数。前端先建立独立的 API、状态、弹窗和动作注册模块，并用浏览器审计确认关键入口不再静默失败。

**Tech Stack:** FastAPI、Pydantic、pytest、Node.js ES Modules、Playwright、PowerShell。

---

## 文件结构

- Create: `.gitignore` — 排除运行数据、环境、缓存和视觉草稿。
- Create: `requirements-dev.txt` — Python 测试依赖。
- Create: `package.json` — 前端单测与浏览器测试入口。
- Create: `playwright.config.mjs` — 本机浏览器回归配置。
- Create: `tools/test_server.py` — 浏览器测试专用隔离服务。
- Create: `platform_core/config.py` — 数据目录选择。
- Create: `platform_core/errors.py` — 统一业务错误。
- Create: `platform_core/bootstrap.py` — 项目计数和启动项目选择。
- Create: `static/modules/api.js` — 统一 API 错误解析。
- Create: `static/modules/modal.js` — 弹窗栈。
- Create: `static/modules/actions.js` — 唯一动作注册。
- Modify: `app.py` — 注册错误处理器并调用新模块。
- Modify: `static/index.html` — 加载模块入口。
- Modify: `static/app.js` — 删除已迁移动作的覆盖实现。
- Test: `tests/conftest.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_bootstrap.py`
- Test: `tests/api/test_error_contract.py`
- Test: `tests/frontend/api.test.mjs`
- Test: `tests/frontend/modal.test.mjs`
- Test: `tests/browser/core-actions.spec.mjs`
- Test: `tests/e2e/test_windows_startup.py`

### Task 1: 建立可回退基线和隔离测试目录

- [ ] **Step 1: 初始化本地 Git 基线**

Run:

```powershell
git init
git config user.name "Codex Local"
git config user.email "codex-local@localhost"
```

Expected: `Initialized empty Git repository`；配置仅作用于当前仓库。

- [ ] **Step 2: 写 `.gitignore`**

```gitignore
__pycache__/
*.pyc
.pytest_cache/
node_modules/
test-results/
playwright-report/
.superpowers/
.venv/
data/
artifacts/test-runs/
```

- [ ] **Step 3: 提交未修改业务代码的基线**

```powershell
git add .gitignore *.py *.bat *.ps1 *.txt requirements.txt static deploy_plugins tools docs
git commit -m "chore: baseline v42.14 before p0 stabilization"
```

Expected: commit succeeds；`git status --short` 只显示后续新增测试文件。

- [ ] **Step 4: 写测试依赖入口**

`requirements-dev.txt`:

```text
-r requirements.txt
pytest>=8.3,<9
httpx>=0.27,<1
```

`package.json`:

```json
{
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test tests/frontend/*.test.mjs",
    "test:browser": "playwright test"
  },
  "devDependencies": {
    "@playwright/test": "^1.55.0"
  }
}
```

- [ ] **Step 5: 安装测试依赖并提交**

先创建 `tests/conftest.py`，保证导入 `app.py` 前已经切换到一次性测试目录，绝不读取或写入 `%LOCALAPPDATA%` 的生产数据：

```python
import io
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from PIL import Image


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="xjalgo-pytest-")).resolve()
os.environ["MC_TRAIN_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["MC_PLATFORM_VERSION"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def seeded_project(client):
    project = client.post("/api/projects", json={
        "name": f"test-{uuid.uuid4().hex[:8]}",
        "description": "isolated test project",
        "labels": [
            {"code": "fire", "display_name": "明火"},
            {"code": "smoke", "display_name": "烟雾"},
        ],
    }).json()
    image_bytes = io.BytesIO()
    Image.new("RGB", (128, 128), "white").save(image_bytes, format="JPEG")
    upload = client.post(
        f"/api/projects/{project['id']}/images",
        files=[("files", ("seed.jpg", image_bytes.getvalue(), "image/jpeg"))],
        data={"dataset_id": "default"},
    )
    upload.raise_for_status()
    return project["id"], upload.json()["uploaded"][0]
```

再安装依赖：

```powershell
python -m pip install -r requirements-dev.txt
npm install
git add requirements-dev.txt package.json package-lock.json tests/conftest.py
git commit -m "test: add p0 regression harness"
```

Expected: Python 与 Node 安装退出码均为 0。

### Task 2: 数据目录选择必须保护历史数据

- [ ] **Step 1: 写失败测试**

`tests/unit/test_config.py`:

```python
from pathlib import Path
from platform_core.config import choose_data_dir


def test_explicit_data_dir_always_wins(tmp_path: Path):
    explicit = tmp_path / "explicit"
    old = tmp_path / "XiaojiangAlgorithmTrain" / "data"
    new = tmp_path / "XJAlgo" / "data"
    assert choose_data_dir(explicit, [old, new]) == explicit.resolve()


def test_non_empty_legacy_dir_beats_empty_new_dir(tmp_path: Path):
    old = tmp_path / "XiaojiangAlgorithmTrain" / "data"
    new = tmp_path / "XJAlgo" / "data"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "projects.json").write_text('[{"id":"p1"}]', encoding="utf-8")
    (new / "projects.json").write_text('[]', encoding="utf-8")
    assert choose_data_dir(None, [new, old]) == old.resolve()
```

- [ ] **Step 2: 验证测试按预期失败**

```powershell
python -m pytest tests/unit/test_config.py -v
```

Expected: FAIL，原因是 `platform_core.config` 尚不存在。

- [ ] **Step 3: 实现最小选择函数**

`platform_core/config.py`:

```python
import json
from pathlib import Path
from typing import Iterable, Optional


def _project_count(path: Path) -> int:
    try:
        value = json.loads((path / "projects.json").read_text(encoding="utf-8"))
        return len(value) if isinstance(value, list) else 0
    except Exception:
        return 0


def choose_data_dir(explicit: Optional[Path], candidates: Iterable[Path]) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    resolved = [Path(item).expanduser().resolve() for item in candidates]
    populated = [item for item in resolved if _project_count(item) > 0]
    return max(populated, key=_project_count) if populated else resolved[0]
```

- [ ] **Step 4: 修改 `app.py:27-117` 使用 `choose_data_dir`，删除自动复制数据逻辑**

Windows candidates 必须按以下顺序传入：

```python
[
    local_root / "XJAlgo" / "data",
    local_root / "XiaojiangAlgorithmTrain" / "data",
    BASE_DIR / "data",
]
```

- [ ] **Step 5: 运行测试并提交**

```powershell
python -m pytest tests/unit/test_config.py -v
git add platform_core/config.py app.py tests/unit/test_config.py
git commit -m "fix: preserve populated historical data directory"
```

Expected: 2 passed。

### Task 3: 启动项目选择只选择真实有数据的项目

- [ ] **Step 1: 写失败测试**

`tests/unit/test_bootstrap.py`:

```python
from platform_core.bootstrap import choose_project


def test_empty_preferred_project_does_not_hide_populated_project():
    projects = [
        {"id": "empty", "updated_at": "2026-08-28"},
        {"id": "real", "updated_at": "2026-08-27"},
    ]
    counts = {
        "empty": {"images": 0, "algorithms": 0, "versions": 0, "jobs": 0},
        "real": {"images": 100, "algorithms": 2, "versions": 3, "jobs": 4},
    }
    assert choose_project(projects, "empty", counts)["id"] == "real"
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/unit/test_bootstrap.py -v
```

Expected: FAIL，模块或函数缺失。

- [ ] **Step 3: 实现纯函数并替换 `app.py:10049-10149` 内对应逻辑**

`platform_core/bootstrap.py`:

```python
from typing import Any, Dict, List, Optional


def _score(item: Dict[str, int]) -> int:
    return item.get("images", 0) * 100 + item.get("algorithms", 0) * 25 + item.get("versions", 0) * 10 + item.get("jobs", 0)


def choose_project(projects: List[Dict[str, Any]], preferred_id: str, counts: Dict[str, Dict[str, int]]) -> Optional[Dict[str, Any]]:
    if not projects:
        return None
    preferred = next((p for p in projects if str(p.get("id")) == str(preferred_id)), None)
    if preferred and _score(counts.get(str(preferred["id"]), {})) > 0:
        return preferred
    ranked = sorted(projects, key=lambda p: (_score(counts.get(str(p.get("id")), {})), str(p.get("updated_at") or "")), reverse=True)
    return ranked[0]
```

- [ ] **Step 4: 运行启动快照 API 回归**

```powershell
python -m pytest tests/unit/test_bootstrap.py -v
```

Expected: 1 passed。

- [ ] **Step 5: 提交**

```powershell
git add platform_core/bootstrap.py app.py tests/unit/test_bootstrap.py
git commit -m "fix: bootstrap populated project instead of stale empty selection"
```

### Task 4: 统一 API 错误结构

- [ ] **Step 1: 写失败 API 测试**

`tests/api/test_error_contract.py`:

```python
def test_missing_label_uses_actionable_error_contract(client):
    response = client.get("/api/v54/projects/not-found/label-schema")
    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["code"]
    assert body["message"]
    assert body["detail"]
    assert "solution" in body
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/api/test_error_contract.py -v
```

Expected: FAIL，当前响应只有 FastAPI `detail`。

- [ ] **Step 3: 实现业务错误和异常处理器**

`platform_core/errors.py`:

```python
from dataclasses import dataclass


@dataclass
class PlatformError(Exception):
    code: str
    message: str
    detail: str
    solution: str = ""
    status_code: int = 400


def error_body(error: PlatformError) -> dict:
    return {
        "ok": False,
        "code": error.code,
        "message": error.message,
        "detail": error.detail,
        "solution": error.solution,
    }
```

在 `app.py` 注册 `PlatformError` 与 `HTTPException` 的 JSON handler，使所有接口返回同一结构。

- [ ] **Step 4: 运行 API 回归**

```powershell
python -m pytest tests/api/test_error_contract.py -v
```

Expected: 1 passed。

- [ ] **Step 5: 提交**

```powershell
git add platform_core/errors.py app.py tests/api/test_error_contract.py
git commit -m "feat: standardize actionable api errors"
```

### Task 5: 前端 API、弹窗栈与唯一动作注册

- [ ] **Step 1: 写失败 Node 测试**

`tests/frontend/modal.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {createModalStack} from '../../static/modules/modal.js';

test('closing a child modal preserves its parent', () => {
  const stack = createModalStack();
  stack.push({id: 'training'});
  stack.push({id: 'quality'});
  assert.equal(stack.pop().id, 'quality');
  assert.equal(stack.peek().id, 'training');
});
```

`tests/frontend/api.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {messageFromApiError} from '../../static/modules/api.js';

test('api error includes detail and solution', () => {
  assert.equal(
    messageFromApiError({message:'标注保存失败', detail:'标签不存在', solution:'请创建标签'}),
    '标注保存失败：标签不存在\n建议：请创建标签'
  );
});
```

- [ ] **Step 2: 运行并确认失败**

```powershell
npm test
```

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现最小模块**

`static/modules/modal.js`:

```javascript
export function createModalStack(){
  const items=[];
  return {push:x=>items.push(x), pop:()=>items.pop(), peek:()=>items.at(-1), size:()=>items.length};
}
```

`static/modules/api.js`:

```javascript
export function messageFromApiError(e={}){
  const base=e.detail?`${e.message||'操作失败'}：${e.detail}`:(e.message||'操作失败');
  return e.solution?`${base}\n建议：${e.solution}`:base;
}
```

`static/modules/actions.js` 导出 `registerAction(name, handler)`，重复注册同名动作时抛错；由新模块统一绑定关键按钮。

- [ ] **Step 4: 在 `static/index.html` 增加模块入口，在 `static/app.js` 删除已迁移动作的重复绑定**

模块入口：

```html
<script type="module" src="/static/main.js?v=43.0.0"></script>
```

- [ ] **Step 5: 运行前端测试并提交**

```powershell
npm test
node --check static/app.js
git add static/modules static/main.js static/index.html static/app.js tests/frontend
git commit -m "refactor: add single frontend action and modal foundations"
```

Expected: Node 测试全部通过，语法检查退出码 0。

### Task 6: 浏览器关键入口审计

- [ ] **Step 1: 写失败浏览器测试**

`tests/browser/core-actions.spec.mjs`:

```javascript
import {test, expect} from '@playwright/test';

test('core navigation and create algorithm action respond without console errors', async ({page}) => {
  const errors=[];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', {name:/算法列表/}).click();
  await page.getByRole('button', {name:/新建算法|创建算法/}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByText('算法名称')).toBeVisible();
  expect(errors).toEqual([]);
});
```

- [ ] **Step 2: 配置隔离 WebServer 并运行失败测试**

`tools/test_server.py`：

```python
import os
import tempfile
from pathlib import Path

import uvicorn


test_data_dir = Path(tempfile.mkdtemp(prefix="xjalgo-browser-")).resolve()
os.environ["MC_TRAIN_DATA_DIR"] = str(test_data_dir)
os.environ["MC_PLATFORM_VERSION"] = "browser-test"
uvicorn.run("app:app", host="127.0.0.1", port=8011, log_level="warning")
```

`playwright.config.mjs`：

```javascript
import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 60_000,
  use: {
    baseURL: 'http://127.0.0.1:8011',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: 'python tools/test_server.py',
    url: 'http://127.0.0.1:8011/api/health',
    reuseExistingServer: false,
    timeout: 120_000
  }
});
```

```powershell
npx playwright test tests/browser/core-actions.spec.mjs
```

Expected: 在旧按钮无反应或弹窗不存在处 FAIL。

- [ ] **Step 3: 修复导航和创建算法动作只走动作注册表**

删除同一按钮的 inline handler 与 override，仅保留 `data-action="algorithm.create"`，模块入口通过事件委托调用注册动作。

- [ ] **Step 4: 运行浏览器测试**

```powershell
npx playwright test tests/browser/core-actions.spec.mjs
```

Expected: 1 passed，控制台异常数组为空。

- [ ] **Step 5: 提交**

```powershell
git add static tests/browser playwright.config.mjs tools/test_server.py
git commit -m "fix: make core navigation and algorithm action observable"
```

### Task 7: Windows 启动与数据预热验收

- [ ] **Step 1: 写启动失败测试**

`tests/e2e/test_windows_startup.py` 启动一个临时端口，设置临时 `MC_TRAIN_DATA_DIR`，等待 `/api/v53/bootstrap/status`，断言 `ready` 且首页为 200。

- [ ] **Step 2: 运行测试并记录失败阶段**

```powershell
python -m pytest tests/e2e/test_windows_startup.py -v
```

Expected: 若 launcher/bootstrap 仍写死端口或目录则 FAIL，并显示对应阶段。

- [ ] **Step 3: 修改 `launcher.py` 使健康检查、预热和浏览器打开全部使用同一 `MC_PORT` 与数据目录**

保留 5 步启动输出；预热失败时不打开浏览器。

- [ ] **Step 4: 运行完整 M1 验证**

```powershell
python -m pytest tests/unit tests/api/test_error_contract.py tests/e2e/test_windows_startup.py -v
npm test
npx playwright test tests/browser/core-actions.spec.mjs
node --check static/app.js
```

Expected: 全部退出码 0。

- [ ] **Step 5: 提交 M1**

```powershell
git add launcher.py tests
git commit -m "test: verify windows bootstrap and p0 interaction foundation"
```

## M1 验收门禁

- 历史业务数据目录只读识别正确。
- 自动测试全部写入隔离目录。
- 项目选择不会被空历史 projectId 覆盖。
- API 失败有统一可理解结构。
- 关键导航和创建算法按钮有可观察响应。
- Windows 服务启动、预热和首页访问通过。
