# Cache-first Page Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make startup and page navigation cache-first while preserving page-specific authoritative refresh and durable mutation truth.

**Architecture:** Retain v53 as the initial state snapshot and reuse existing state/page runtimes. Remove only the redundant authoritative refreshes, reuse request-local backend counts, prioritize v61 page rows ahead of auxiliary totals, and read label usage from the existing MaterialRepository SQLite projection.

**Tech Stack:** FastAPI, Python SQLite repositories, browser JavaScript modules, Node test runner, Playwright.

---

### Task 1: Lock the request-budget and first-paint contracts

**Files:**
- Create: `tests/browser/page-loading-performance.spec.mjs`
- Create: `tests/frontend/cache-first-page-loading.test.mjs`

- [ ] **Step 1: Write the failing startup/browser test**

Record API request start/end timestamps from before `page.goto('/')`, then navigate through `算法列表 → 训练任务 → 数据集 → 服务节点`. Assert startup has one snapshot request and no `refresh=true`; each navigation paints its target shell before unrelated requests; training has at most one jobs GET; dataset uses v61 only; service nodes does not request snapshot, algorithms, jobs, or materials.

```javascript
const requests = [];
page.on('request', request => requests.push({url: new URL(request.url()), started: performance.now()}));
await page.goto('/');
await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
const startupSnapshots = requests.filter(row => row.url.pathname === '/api/v53/bootstrap/snapshot');
expect(startupSnapshots).toHaveLength(1);
expect(startupSnapshots[0].url.searchParams.get('refresh')).not.toBe('true');
```

- [ ] **Step 2: Run the browser test and verify RED**

Run: `npx playwright test tests/browser/page-loading-performance.spec.mjs`

Expected: FAIL because startup includes `/api/v53/bootstrap/snapshot?...refresh=true` and a second snapshot request.

- [ ] **Step 3: Write the failing source/runtime test**

Assert that `loadCore412` accepts an authoritative option, `refresh=true` appears only behind that option, startup does not await `refreshCurrentPage413`, and `extras412` does not load `jobs` or `modelConfigs` already present in the snapshot.

```javascript
assert.match(source, /loadCore412=async function\(\{authoritative=false\}=\{\}\)/);
assert.doesNotMatch(startupBlock, /await window\.refreshCurrentPage413/);
assert.doesNotMatch(extrasBlock, /\/jobs|modelConfigs|model-configs/);
```

- [ ] **Step 4: Run the source/runtime test and verify RED**

Run: `node --test tests/frontend/cache-first-page-loading.test.mjs`

Expected: FAIL on the unconditional `refresh=true`, startup broad refresh, and duplicate extras requests.

### Task 2: Make v53 request work single-pass

**Files:**
- Modify: `app.py` around `_v53_project_counts()` and `v53_bootstrap_snapshot()`
- Modify: `tests/api/test_material_response_performance.py`

- [ ] **Step 1: Write the failing API test**

Monkeypatch `_v53_project_counts` with a call counter, request a refreshed snapshot for three projects, and assert every project is counted exactly once. Also assert the refreshed snapshot replaces `_V53_BOOTSTRAP_SNAPSHOT` so later cache-first reads see authoritative truth.

```python
calls = []
monkeypatch.setattr(app_module, "_v53_project_counts", lambda project: calls.append(project["id"]) or {"images": 1})
response = app_module.v53_bootstrap_snapshot("p2", refresh=True)
assert calls == ["p1", "p2", "p3"]
assert app_module._V53_BOOTSTRAP_SNAPSHOT["project"]["id"] == "p2"
```

- [ ] **Step 2: Run the API test and verify RED**

Run: `python -m pytest tests/api/test_material_response_performance.py -q`

Expected: FAIL because counts are currently recalculated for `bootstrap_counts` and refreshed snapshots are not retained.

- [ ] **Step 3: Implement request-local count reuse**

Build one `counts` mapping at the start of the endpoint, pass it into project selection, and construct every `bootstrap_counts` from that mapping. When refresh or project-switch rebuilds a snapshot, atomically assign that snapshot to `_V53_BOOTSTRAP_SNAPSHOT` before returning it.

```python
counts = {str(project.get("id") or ""): _v53_project_counts(project) for project in projects}
chosen = choose_requested_project(projects, requested, counts) if requested else _v53_choose_project(projects, "", counts)
snap["projects"] = [{**project, "bootstrap_counts": counts.get(str(project.get("id") or ""), {})} for project in projects]
_V53_BOOTSTRAP_SNAPSHOT = snap
```

- [ ] **Step 4: Run the API test and verify GREEN**

Run: `python -m pytest tests/api/test_material_response_performance.py -q`

Expected: all tests pass.

### Task 3: Remove startup duplication and prioritize page owners

**Files:**
- Modify: `static/app.js` around `loadCore412`, `extras412`, `refreshCurrentPage413`, `__clInit`, and refresh-button ownership
- Modify: `static/main.mjs` around runtime startup and NavigationStability
- Modify: `static/modules/material-pagination-runtime.js`
- Modify: `static/index.html` cache versions only for files changed in this task

- [ ] **Step 1: Implement cache-first core loading**

Change `loadCore412({authoritative = false})` so its snapshot URL appends `refresh=true` only when authoritative. Apply `model_configs` from the snapshot. Remove jobs/model-config reads from `extras412`.

```javascript
window.loadCore412=async function({authoritative=false}={}){
  const suffix=authoritative?'&refresh=true':'';
  const snapshot=await api(`/api/v53/bootstrap/snapshot?preferred_project_id=${encodeURIComponent(id)}${suffix}`);
  state.jobs=snapshot.jobs||[];
  state.modelConfigs=snapshot.model_configs||[];
};
```

- [ ] **Step 2: Remove the startup broad refresh**

After `loadStartupSnapshot413(false)`, set `uiReady`, render cached state immediately, and do not await `refreshCurrentPage413`. Explicit refresh calls `refreshCurrentPage413({authoritative: true})`.

```javascript
await window.loadStartupSnapshot413(false);
state.uiReady=true;
render();
// Refresh button only:
await window.refreshCurrentPage413({authoritative:true});
```

- [ ] **Step 3: Start stale page-specific refresh only**

After the runtime modules are installed, use snapshot `generated_at` to decide whether the algorithm owner needs a silent `AlgorithmListRuntime.refresh`. Training remains under TrainingTaskRuntime/PollRegistry, dataset under v61 pagination, and service nodes under ServiceNodeRuntime.

```javascript
const age=Date.now()-Number(state.__coreSnapshotGeneratedAt||0);
if(state.page==='算法列表'&&age>5000) void algorithmListRuntime.refresh({render:true,minAgeMs:5000});
```

- [ ] **Step 4: Prioritize the current v61 page**

Fetch and paint the current material page before awaiting the two status totals. Update totals only if the request serial/page is still current. Do not run the separate summary enhancement while the dataset page is active.

```javascript
const materialPage=await fetchMaterialPage61(requestedCursor);
commitMaterialPage(materialPage);
void Promise.all([fetchStatusTotal61('unprocessed'),fetchStatusTotal61('processed')])
  .then(([unprocessed,processed])=>commitTotalsIfCurrent(serial,expectedPage,unprocessed,processed));
```

- [ ] **Step 5: Run frontend and browser tests and verify GREEN**

Run:

```text
node --test tests/frontend/cache-first-page-loading.test.mjs tests/frontend/material-pagination-runtime.test.mjs
npx playwright test tests/browser/page-loading-performance.spec.mjs tests/browser/material-pagination-performance.spec.mjs tests/browser/algorithm-list-performance.spec.mjs tests/browser/training-task-performance.spec.mjs
```

Expected: all targeted tests pass and the browser inventory prints the post-fix request table.

### Task 4: Make label-schema an index-only read

**Files:**
- Modify: `platform_core/material_repository.py`
- Modify: `app.py` in `v54_label_schema()`
- Create: `tests/api/test_label_schema_performance.py`

- [ ] **Step 1: Write the failing endpoint test**

Seed materials with existing `label_counts`, monkeypatch `load_images`, `read_annotation`, and `MaterialRepository.patch` to fail if called, then request label schema and assert correct `usage_images/usage_boxes`.

```python
monkeypatch.setattr(app_module, "load_images", lambda *_: pytest.fail("ordinary label GET scanned all images"))
monkeypatch.setattr(app_module, "read_annotation", lambda *_: pytest.fail("ordinary label GET read annotations"))
response = client.get(f"/api/v54/projects/{project_id}/label-schema")
assert response.json()["items"][0]["usage_boxes"] == 3
```

- [ ] **Step 2: Run the endpoint test and verify RED**

Run: `python -m pytest tests/api/test_label_schema_performance.py -q`

Expected: FAIL because current GET calls `load_images` and may call `read_annotation`/`patch`.

- [ ] **Step 3: Add an existing-index aggregate**

Add `MaterialRepository.label_usage()` using SQLite `json_each(payload_json, '$.label_counts')`, returning per-label image and box totals. Change label-schema GET to use it without annotation reads or writes.

```python
rows = database.execute("""
    SELECT CAST(entry.key AS TEXT) AS label_code,
           COUNT(DISTINCT materials.id) AS images,
           SUM(CAST(entry.value AS INTEGER)) AS boxes
    FROM materials, json_each(materials.payload_json, '$.label_counts') AS entry
    WHERE CAST(entry.value AS INTEGER) > 0
    GROUP BY entry.key
""").fetchall()
```

- [ ] **Step 4: Run the endpoint test and verify GREEN**

Run: `python -m pytest tests/api/test_label_schema_performance.py -q`

Expected: all tests pass.

### Task 5: Verify, document, and commit

**Files:**
- Modify: `docs/CODEX_HANDOFF_2026-09-21.md`
- Modify: `docs/PROJECT_HANDOFF_CURRENT.md`
- Modify: `docs/CODEX_CURRENT_STATE.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Re-run the targeted API/frontend/browser tests**

Do not run the full pytest or full integration suite. Capture counts, duplicate URLs, slowest request, snapshot count, refresh flag, and click-to-visible time from the browser inventory.

- [ ] **Step 2: Run syntax and diff checks**

Run `node --check` on changed JavaScript modules, `git diff --check`, and confirm `VERSION.txt` remains `42.24.0`.

- [ ] **Step 3: Update current handoff documents**

Record the exact owner changes, request-chain before/after evidence, tests, and the fact that Actions/full suites were not run.

- [ ] **Step 4: Commit the implementation**

Stage only this batch and commit with `perf: make page loading cache first`.
