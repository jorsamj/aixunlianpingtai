# Ultralytics Resource Discovery and Whole-Machine Model Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple Ultralytics runtime availability from checkpoint presence, add durable cross-platform Python-environment discovery and whole-machine model scanning, and resolve official YOLO checkpoints without misclassifying a healthy environment as failed.

**Architecture:** Add one focused resource-discovery package and one `RESOURCE_DISCOVERY` durable Task Runtime handler. Keep `ultralytics_env.json` as the backward-compatible record of the user-selected environment, persist discovered environments and model-file cache in SQLite, and expose existing API names as asynchronous task-creation endpoints. A central model resolver returns structured `FOUND` or `MISSING` results plus an independent `downloadable` flag and is shared by training options and deployment tests.

**Tech Stack:** Python 3.10-3.12, FastAPI/Pydantic, SQLite, `subprocess` with `shell=False`, `psutil`, `os.scandir`, existing durable Task Runtime, browser JavaScript modules, Node test runner, Playwright, pytest.

---

## Non-negotiable behavior

- Environment availability depends only on the selected Python and real imports/probes for Ultralytics, Torch, TorchVision, TorchVision ops, CUDA, and GPU inventory. No `.pt` file participates in that decision.
- CPU-only is a valid `AVAILABLE` environment when the required imports and TorchVision ops work.
- Official names `yolo11n.pt`, `yolo11s.pt`, and `yolo11m.pt` may be `MISSING` with `downloadable=true`; that state never changes environment availability.
- GET/refresh reads cache only. POST detection creates a durable task and returns HTTP 202 without performing a whole-machine scan in the request thread.
- Fast discovery does not reuse `SKIP_SCAN_DIRS`. In particular, AppData, Program Files, `.venv`, and `venv` remain eligible.
- Unknown scan totals use `progress_determinate=false`; the UI displays counters and current path, never a fabricated percentage.
- All discovered environments are returned. The recommendation is deterministic, but selection remains an explicit user action.
- No task in this plan modifies or merges `main`.

## File map

- Create `platform_core/resource_discovery/__init__.py`: public discovery contracts.
- Create `platform_core/resource_discovery/cache.py`: SQLite environment/model cache.
- Create `platform_core/resource_discovery/probe.py`: candidate-Python subprocess validation and recommendation ranking.
- Create `platform_core/resource_discovery/candidates.py`: bounded fast Python discovery.
- Create `platform_core/resource_discovery/scanner.py`: local mount enumeration and streaming deep scans.
- Create `platform_core/resource_discovery/model_resolver.py`: ordered checkpoint resolution and downloadable official references.
- Create `platform_core/resource_discovery/tasks.py`: durable environment/model discovery handler.
- Modify `platform_core/task_runtime/models.py`: add `RESOURCE_DISCOVERY`.
- Modify `platform_core/worker_registry.py`: add the `discovery` worker role.
- Modify `platform_core/deployment/inference_tasks.py`: distinguish local files from downloadable official references.
- Modify `app.py`: thin compatibility APIs, task APIs, cache reads, explicit environment selection, and resolver integration.
- Create `static/modules/resource-discovery.js`: task polling, cached results, environment selection, and model scan controls.
- Modify `static/main.mjs`, `static/app.js`, and `static/styles.css`: install the module and integrate it into the existing training-resource page.
- Add the focused tests listed in each task.
- Modify `VERSION.txt`, browser cache versions, `README.md`, and `docs/codex-handoff.md` only in the final combined regression task across all three plans.

### Task 1: Persist discovery results without changing the active environment contract

**Files:**
- Create: `platform_core/resource_discovery/__init__.py`
- Create: `platform_core/resource_discovery/cache.py`
- Create: `tests/unit/resource_discovery/test_discovery_cache.py`

- [ ] **Step 1: Write failing cache tests**

Create tests proving that environment candidates and model files are independently replaceable, all Python environments survive one scan, model rows are paginated, and reopening the repository returns the same cache:

```python
from platform_core.resource_discovery.cache import DiscoveryCache


def test_environment_cache_keeps_all_candidates_and_recommendation(tmp_path):
    cache = DiscoveryCache(tmp_path / "resource-discovery.sqlite3")
    cache.replace_environments("scan-1", [
        {"python_path": "/cpu/python", "status": "AVAILABLE", "cuda_available": False, "recommendation_rank": 20},
        {"python_path": "/gpu/python", "status": "AVAILABLE", "cuda_available": True, "recommendation_rank": 100},
    ], generation=1)
    rows = cache.list_environments()
    assert [row["python_path"] for row in rows] == ["/gpu/python", "/cpu/python"]
    assert rows[0]["recommended"] is True


def test_model_cache_is_persistent_and_paged(tmp_path):
    path = tmp_path / "resource-discovery.sqlite3"
    cache = DiscoveryCache(path)
    cache.replace_models("scan-2", [
        {"path": f"/models/{index}.onnx", "name": f"{index}.onnx", "format": "onnx", "size_bytes": index, "modified_at": "2026-09-08T00:00:00Z", "volume": "/models"}
        for index in range(1201)
    ], generation=1)
    page = DiscoveryCache(path).list_models(limit=500)
    assert len(page.items) == 500
    assert page.next_cursor
    assert DiscoveryCache(path).model_count() == 1201


def test_older_scan_cannot_overwrite_a_newer_completed_generation(tmp_path):
    cache = DiscoveryCache(tmp_path / "resource-discovery.sqlite3")
    cache.replace_environments("newer", [{"python_path": "/new/python", "status": "AVAILABLE"}], generation=2)
    cache.replace_environments("older", [{"python_path": "/old/python", "status": "AVAILABLE"}], generation=1)
    assert [row["python_path"] for row in cache.list_environments()] == ["/new/python"]


def test_generation_is_allocated_monotonically_at_task_creation(tmp_path):
    cache = DiscoveryCache(tmp_path / "resource-discovery.sqlite3")
    assert cache.next_generation("environment") == 1
    assert cache.next_generation("environment") == 2
    assert cache.next_generation("models") == 1
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `python -m pytest tests/unit/resource_discovery/test_discovery_cache.py -q`

Expected: collection FAILS with `ModuleNotFoundError: platform_core.resource_discovery`.

- [ ] **Step 3: Implement the SQLite cache**

Use WAL mode and tables `environment_candidates`, `model_files`, and `cache_meta`. The cache path is `DATA_DIR / "resource_discovery.sqlite3"`. Environment identity is normalized `python_path`; model identity is normalized absolute `path`. Required public contract: atomic `next_generation(cache_kind)`, `replace_environments(scan_id, rows, generation)`, `list_environments()`, `replace_models(scan_id, rows, generation)`, `list_models(limit=200, cursor=None)`, `find_models_by_name(names)`, `model_count()`, and `metadata()`. `list_models()` returns a frozen `ModelPage(items: tuple[dict, ...], next_cursor: str | None)` and rejects malformed cursors with `ValueError`.

`replace_*` must use one transaction and temporary `scan_id` ownership so a failed scan leaves the previous completed cache intact. Its monotonic generation check prevents an older, slower task from replacing a newer completed cache. Store probe errors as data, never secrets or environment variables. Rank rows by `recommendation_rank DESC, python_path ASC`. Set `recommended=true` only on the first `AVAILABLE` row.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/unit/resource_discovery/test_discovery_cache.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Independent review and commit**

After spec and code-quality reviewers approve the uncommitted diff:

```bash
git add platform_core/resource_discovery tests/unit/resource_discovery/test_discovery_cache.py
git commit -m "feat: persist local resource discovery cache"
```

### Task 2: Probe Python environments independently from checkpoints

**Files:**
- Create: `platform_core/resource_discovery/probe.py`
- Create: `tests/unit/resource_discovery/test_ultralytics_probe.py`
- Modify: `tests/unit/test_portable_resource_discovery.py`

- [ ] **Step 1: Add failing probe and ranking tests**

Cover a healthy CPU environment with no model, independent import failures, TorchVision NMS execution, CUDA device inventory, UTF-8 output, timeout, and ranking:

```python
def test_probe_is_available_without_any_checkpoint(fake_python_probe):
    fake_python_probe.returns({
        "python_version": "3.11.9", "ultralytics": {"ok": True, "version": "8.4.127"},
        "torch": {"ok": True, "version": "2.6.0"},
        "torchvision": {"ok": True, "version": "0.21.0", "ops_ok": True},
        "cuda_available": False, "gpu_count": 0, "gpu_names": [], "weights_dir": "/weights",
    })
    result = probe_python_environment(fake_python_probe.python)
    assert result["status"] == "AVAILABLE"
    assert result["model_status"] == "NOT_CHECKED"


def test_cuda_environment_is_recommended_before_cpu():
    ranked = rank_environments([
        {"python_path": "/cpu/python", "status": "AVAILABLE", "cuda_available": False, "torchvision_ops_ok": True},
        {"python_path": "/gpu/python", "status": "AVAILABLE", "cuda_available": True, "torchvision_ops_ok": True},
    ])
    assert ranked[0]["python_path"] == "/gpu/python"
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/unit/resource_discovery/test_ultralytics_probe.py tests/unit/test_portable_resource_discovery.py -q`

Expected: FAIL because the new probe functions do not exist.

- [ ] **Step 3: Implement one bounded subprocess probe**

Run the candidate interpreter with `shell=False`, a 30-second timeout, UTF-8 replacement decoding, and one JSON result. The child script must independently capture exceptions for each import and execute a tiny CPU NMS call:

```python
boxes = torch.tensor([[0.0, 0.0, 10.0, 10.0]])
scores = torch.tensor([0.9])
torchvision.ops.nms(boxes, scores, 0.5)
```

It must return Python executable/version, module versions/errors, `weights_dir`, `torch.cuda.is_available()`, GPU count/names, and a compatibility summary. `status` is `AVAILABLE` only when Ultralytics, Torch, TorchVision, and NMS pass; missing CUDA remains valid CPU availability. Do not inspect or load `.pt` files in this module.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/unit/resource_discovery/test_ultralytics_probe.py tests/unit/test_portable_resource_discovery.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Independent review and commit**

```bash
git add platform_core/resource_discovery/probe.py tests/unit/resource_discovery/test_ultralytics_probe.py tests/unit/test_portable_resource_discovery.py
git commit -m "fix: decouple ultralytics probes from model files"
```

### Task 3: Discover fast Python candidates without excluding real environments

**Files:**
- Create: `platform_core/resource_discovery/candidates.py`
- Create: `tests/unit/resource_discovery/test_python_candidates.py`

- [ ] **Step 1: Write failing discovery tests**

Tests must construct isolated fake directory layouts and monkeypatch PATH, `VIRTUAL_ENV`, `CONDA_PREFIX`, saved environment content, user home, AppData, Program Files, and `conda env list --json` output:

```python
def test_fast_candidates_include_appdata_venv_and_conda(fake_layout):
    rows = discover_fast_python_candidates(fake_layout.context)
    paths = {row.path for row in rows}
    assert fake_layout.appdata_python in paths
    assert fake_layout.dot_venv_python in paths
    assert fake_layout.conda_python in paths


def test_fast_candidates_are_deduplicated_but_keep_sources(fake_layout):
    rows = discover_fast_python_candidates(fake_layout.context)
    match = next(row for row in rows if row.path == fake_layout.dot_venv_python)
    assert set(match.sources) >= {"project_venv", "virtual_env"}


def test_every_path_python_is_returned_and_cuda_can_rank_later(fake_layout):
    rows = discover_fast_python_candidates(fake_layout.context)
    assert fake_layout.path_cpu_python in {row.path for row in rows}
    assert fake_layout.path_cuda_python in {row.path for row in rows}
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/unit/resource_discovery/test_python_candidates.py -q`

Expected: FAIL because the candidate module is absent.

- [ ] **Step 3: Implement bounded fast discovery**

Check, without recursive whole-disk traversal: current `sys.executable`, saved active environment, every PATH entry containing `python`/`python3` rather than only `shutil.which()`'s first match, `VIRTUAL_ENV`, `CONDA_PREFIX`, Conda JSON output, project `.venv`/`venv`, user-local Python installs, AppData Python, Program Files Python/Conda roots, and Ultralytics configuration hints. Configuration inputs are the saved environment's `python_path`, `root`, and `weights_dir`, plus every `MC_ULTRALYTICS_ROOTS` entry. Platform-specific path shapes must be guarded by `os.name`/`sys.platform` and assembled with `Path`; no fixed `C:\\` or `D:\\` literals. Do not import or reuse `SKIP_SCAN_DIRS`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/unit/resource_discovery/test_python_candidates.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Independent review and commit**

```bash
git add platform_core/resource_discovery/candidates.py tests/unit/resource_discovery/test_python_candidates.py
git commit -m "feat: discover local python environments"
```

### Task 4: Stream whole-machine Python and model scans across local mounts

**Files:**
- Create: `platform_core/resource_discovery/scanner.py`
- Create: `tests/unit/resource_discovery/test_machine_scanner.py`
- Create: `tests/performance/test_resource_discovery_scale.py`

- [ ] **Step 1: Add failing mount, permission, extension, and scale tests**

Required cases: multiple Windows fixed disks returned by `psutil.disk_partitions(all=False)`, multiple Linux local mounts, distinct mocked results for `disk_partitions(all=False)` scan roots and `disk_partitions(all=True)` traversal boundaries, exclusion of network/virtual child mounts while scanning `/`, permission errors counted rather than raised, all required model extensions, and 10,001 files with bounded Python allocation.

```python
def test_windows_local_roots_are_not_hardcoded(monkeypatch):
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: [
        part("C:\\", "NTFS", "rw,fixed"), part("F:\\", "NTFS", "rw,fixed"), part("Z:\\", "smb", "rw,remote")
    ])
    assert local_scan_roots(platform="win32") == [Path("C:/"), Path("F:/")]


def test_model_scan_skips_denied_directory_and_continues(tmp_path, denied_scandir):
    report = scan_model_files([tmp_path], on_item=lambda _row: None)
    assert report.permission_errors == 1
    assert report.models_found == 1


def test_scanning_root_never_enters_excluded_child_mounts(fake_mount_tree):
    report = scan_model_files([fake_mount_tree.root], on_item=lambda _row: None)
    assert fake_mount_tree.proc not in report.visited_directories
    assert fake_mount_tree.nfs not in report.visited_directories
    assert fake_mount_tree.local_data in report.visited_directories
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/unit/resource_discovery/test_machine_scanner.py tests/performance/test_resource_discovery_scale.py -q`

Expected: FAIL because the scanner module is absent.

- [ ] **Step 3: Implement streaming traversal**

Use `psutil.disk_partitions(all=False)` to choose user-visible local scan roots and explicit filesystem classification. Separately call `psutil.disk_partitions(all=True)` (with `/proc/self/mountinfo` as the Linux fallback when psutil cannot expose the full table) to build the traversal-boundary map. Exclude network filesystems plus `proc`, `sysfs`, `devtmpfs`, `tmpfs`, `cgroup`, `overlay`, and similar virtual mounts. Build a longest-mount-path lookup from that complete boundary table: before entering every directory, determine its owning mount; reject excluded child mounts even when traversal started at `/`, and avoid revisiting a permitted child mount already scheduled as a separate root. Traverse with an iterative `os.scandir` stack, never `list(rglob())`, never collect all directory entries, and never reuse the model/material `SKIP_SCAN_DIRS`. Skip symlinks and junction loops using stable directory identities where available.

Python mode recognizes actual candidate executable names and yields paths for later subprocess validation. Model mode recognizes exactly:

```python
MODEL_EXTENSIONS = {
    ".pt", ".pth", ".onnx", ".engine", ".rknn", ".bmodel", ".om",
    ".pdparams", ".pdmodel", ".pdiparams",
}
```

Each model row includes name, absolute path, format, size bytes, modified time, and volume/mount. Progress callbacks contain `scanned_dirs`, `python_candidates`, `validated_environments`, `models_found`, `current_path`, and `permission_errors`; they contain no percentage.

- [ ] **Step 4: Run scanner and scale tests**

Run: `python -m pytest tests/unit/resource_discovery/test_machine_scanner.py tests/performance/test_resource_discovery_scale.py -q -s`

Expected: all tests PASS and peak allocation remains below the test's 64 MiB limit.

- [ ] **Step 5: Independent review and commit**

```bash
git add platform_core/resource_discovery/scanner.py tests/unit/resource_discovery/test_machine_scanner.py tests/performance/test_resource_discovery_scale.py
git commit -m "feat: stream whole-machine resource scans"
```

### Task 5: Run environment and model discovery as durable tasks

**Files:**
- Modify: `platform_core/task_runtime/models.py`
- Modify: `platform_core/worker_registry.py`
- Create: `platform_core/resource_discovery/tasks.py`
- Modify: `app.py`
- Create: `tests/unit/resource_discovery/test_discovery_tasks.py`
- Create: `tests/api/test_resource_discovery_api.py`
- Create: `tests/unit/test_task_worker_entrypoint.py`

- [ ] **Step 1: Write failing Task Runtime and API tests**

Verify `RESOURCE_DISCOVERY` registration, `task_worker.py --roles discovery --check`, HTTP 202 latency, task persistence, auto fast-to-deep fallback only when no valid environment is found, forced full scan, truthful counters, cancellation, recovery, cached GET behavior, and no scan call during GET:

```python
def test_ultralytics_detection_returns_before_worker_runs(client, monkeypatch):
    monkeypatch.setattr("platform_core.resource_discovery.tasks.discover_fast_python_candidates", blocking_discovery)
    started = time.perf_counter()
    response = client.post("/api/ultralytics_env/detect", json={"scope": "auto"})
    assert response.status_code == 202
    assert time.perf_counter() - started < 0.5
    assert response.json()["status"] == "QUEUED"


def test_cached_environment_get_does_not_rescan(client, monkeypatch):
    monkeypatch.setattr("platform_core.resource_discovery.tasks.scan_python_candidates", forbidden_call)
    response = client.get("/api/ultralytics_env")
    assert response.status_code == 200


def test_empty_active_reads_never_probe_or_write_selection(client, monkeypatch, tmp_path):
    import app as app_module

    active_file = tmp_path / "ultralytics_env.json"
    monkeypatch.setattr(app_module, "ULTRALYTICS_ENV_FILE", active_file)
    monkeypatch.setattr(app_module, "_ACTIVE_ULTRA_RUNTIME_CACHE", {})
    monkeypatch.setattr(app_module, "_check_ultralytics_python", forbidden_call)
    monkeypatch.setattr("platform_core.resource_discovery.probe.probe_python_environment", forbidden_call)
    assert client.get("/api/ultralytics_env").status_code == 200
    assert client.get("/api/base_models").status_code == 200
    assert client.get("/api/training_options").status_code == 200
    assert not active_file.exists()
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/unit/resource_discovery/test_discovery_tasks.py tests/api/test_resource_discovery_api.py -q`

Expected: FAIL because the new task kind/handler and asynchronous contracts do not exist.

- [ ] **Step 3: Implement the handler and thin APIs**

Add `TaskKind.RESOURCE_DISCOVERY`, worker role `discovery`, capability `resource.discovery`, and one payload discriminator. These machine-scoped tasks use `project_id="__system__"`. Environment scans use `resource_key="local-resource-discovery:environment"`; model scans use `resource_key="local-resource-discovery:models"`, so only one scan of each type runs at once while the two independent caches may progress concurrently. At task creation the API atomically calls `DiscoveryCache.next_generation(discovery_type)` and persists that generation in `request.json`; the Worker may publish only that generation or a newer one:

```python
{"discovery_type": "ultralytics_environment", "scope": "auto|fast|full", "roots": []}
{"discovery_type": "local_models", "scope": "directory|full", "roots": []}
```

`auto` runs fast discovery and validates every unique candidate. It deep-scans only when fast discovery produces zero `AVAILABLE` environments. `full` runs fast plus deep and returns all unique environments. The handler writes live `progress.json` artifacts after bounded batches and heartbeats `stage`/`current_item`; public task APIs merge the artifact counters and return `progress_determinate=false`.

Preserve compatibility endpoints:

- `POST /api/ultralytics_env/detect` -> create task, HTTP 202.
- `GET /api/ultralytics_env` -> selected active environment plus cached candidates and last scan metadata.
- `POST /api/local_models/scan` -> create directory or full scan task, HTTP 202.
- `GET /api/local_models` -> cached paginated model results.
- `GET /api/resource-discovery/tasks/{task_id}` -> durable status and counters.
- `POST /api/resource-discovery/tasks/{task_id}/cancel` -> cancellation.

The HTTP route must never call the scanner. Recovery may safely repeat discovery because completed cache replacement is atomic.

Replace the current side-effecting behavior of `get_active_ultralytics_env()`: it may read and validate the shape/existence of a previously selected interpreter, but it must not run a probe, select `sys.executable`, or write `ultralytics_env.json`. `/api/ultralytics_env/select` performs the new full probe, rejects non-`AVAILABLE` candidates, and is the only environment-selection route allowed to persist active state. Add API assertions that confirmation persists selection and all read-only training/base-model/environment calls leave an empty active file untouched.

- [ ] **Step 4: Run Task Runtime, API, and worker-registration tests**

Run: `python -m pytest tests/unit/resource_discovery/test_discovery_tasks.py tests/api/test_resource_discovery_api.py tests/unit/test_task_worker_entrypoint.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Independent review and commit**

```bash
git add platform_core/task_runtime/models.py platform_core/worker_registry.py platform_core/resource_discovery/tasks.py app.py tests/unit/resource_discovery/test_discovery_tasks.py tests/api/test_resource_discovery_api.py tests/unit/test_task_worker_entrypoint.py
git commit -m "feat: run local discovery as durable tasks"
```

### Task 6: Resolve official YOLO models without poisoning environment status

**Files:**
- Create: `platform_core/resource_discovery/model_resolver.py`
- Modify: `platform_core/deployment/inference_tasks.py`
- Modify: `app.py`
- Create: `tests/unit/resource_discovery/test_model_resolver.py`
- Create: `tests/unit/test_inference_tasks.py`
- Modify: `tests/api/test_deployment_test_runtime.py`

- [ ] **Step 1: Write failing ordered-resolution and deployment tests**

Test the exact search priority, `weights_dir`, scanned-cache lookup, project model directories, default Ultralytics cache directories, cwd compatibility, missing official status, and strict failure for missing nonofficial paths:

```python
def test_missing_official_model_is_downloadable_not_environment_failure(resolver):
    result = resolver.resolve("yolo11n.pt", project_id="project-a")
    assert result.status == "MISSING"
    assert result.downloadable is True
    assert result.environment_status == "AVAILABLE"


def test_weights_dir_precedes_scanned_and_project_models(resolver, weights_dir):
    expected = weights_dir / "yolo11n.pt"
    expected.write_bytes(b"weights")
    assert resolver.resolve("yolo11n.pt", project_id="project-a").path == expected


def test_deployment_task_accepts_downloadable_official_reference(client, seeded_project, monkeypatch):
    response = create_builtin_deployment_test(client, seeded_project, "yolo11n.pt")
    assert response.status_code == 202
    request = load_request(response.json()["id"])
    assert request["model_reference"] == "yolo11n.pt"
    assert request["model_reference_type"] == "official_downloadable"
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/unit/resource_discovery/test_model_resolver.py tests/api/test_deployment_test_runtime.py -q`

Expected: FAIL because resolution is still current-root-only and the Worker requires `Path.is_file()`.

- [ ] **Step 3: Implement structured resolution and safe official download behavior**

Create immutable `ModelResolution` with `status`, `path`, `reference`, `source`, `downloadable`, `environment_status`, and `searched_locations`. Search in this order:

1. selected environment model directories;
2. selected environment's probed Ultralytics `weights_dir`;
3. `DiscoveryCache.find_models_by_name()`;
4. project model directories and persisted algorithm versions;
5. platform-appropriate Ultralytics cache/default weight directories;
6. current working directory for compatibility only.

Only the explicit allowlist `{yolo11n.pt, yolo11s.pt, yolo11m.pt}` is downloadable. Deployment requests store a real local `model_path` when found; otherwise they store the official `model_reference` and `model_reference_type=official_downloadable`. `DeploymentTestHandler` keeps strict `Path.is_file()` for local/project/conversion artifacts but passes the allowlisted official reference to `predict_ultralytics_runner.py`, allowing Ultralytics to perform a real first-use download. Runner failure output becomes the task's real failure reason; no fake success or fallback image is allowed.

Update training/base-model APIs to return model status and downloadability independently from environment status. Keep `resolve_ultralytics_model_path()` only as a backward-compatible wrapper around the structured resolver.

- [ ] **Step 4: Run resolver, deployment, training-request, and inference tests**

Run: `python -m pytest tests/unit/resource_discovery/test_model_resolver.py tests/api/test_deployment_test_runtime.py tests/api/test_training_request.py tests/unit/test_inference_tasks.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Independent review and commit**

```bash
git add platform_core/resource_discovery/model_resolver.py platform_core/deployment/inference_tasks.py app.py tests/unit/resource_discovery/test_model_resolver.py tests/api/test_deployment_test_runtime.py tests/api/test_training_request.py tests/unit/test_inference_tasks.py
git commit -m "fix: resolve downloadable ultralytics models"
```

### Task 7: Present truthful resource discovery and explicit selection in the existing UI

**Files:**
- Create: `static/modules/resource-discovery.js`
- Modify: `static/main.mjs`
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Create: `tests/frontend/resource-discovery-ui.test.mjs`
- Create: `tests/e2e/test_resource_discovery_ui.py`

- [ ] **Step 1: Write failing frontend source/runtime tests**

Assert that the final installed runtime creates and polls durable tasks, never selects `candidates[0]`, labels the button `一键检测`, renders indeterminate progress with the required counters, lists every environment, requires explicit selection, retains directory model scan, adds `全机扫描模型`, and reloads cached data without POSTing:

```javascript
test('resource discovery never auto-selects the first python', () => {
  assert.doesNotMatch(finalRuntime, /candidates\s*\[\s*0\s*\].*select/s);
  assert.match(finalRuntime, /一键检测/);
  assert.match(finalRuntime, /全机扫描模型/);
  assert.match(finalRuntime, /progress_determinate/);
  for (const label of ['已扫描目录','Python 候选','已验证环境','当前路径','权限失败']) {
    assert.match(finalRuntime, new RegExp(label));
  }
});
```

- [ ] **Step 2: Run and verify failure**

Run: `node --test tests/frontend/resource-discovery-ui.test.mjs`

Expected: FAIL because the current final runtime synchronously detects and auto-selects the first result.

- [ ] **Step 3: Implement the module and existing-page integration**

Install a single runtime from `static/main.mjs`. Replace both legacy “一键检测常用目录” call paths with task creation and polling. Show cached last-detected time and source, live indeterminate counters, all candidate cards, recommendation reason, CPU/CUDA/GPU details, module versions/errors, and a user-confirm button. Do not invoke `/select` until that button is clicked.

For models, keep a specified-directory action and add `全机扫描模型`; both poll the same durable task contract and display cached results after completion. Closing the modal stops browser polling only and does not cancel the Worker. Page refresh calls only GET cache endpoints.

- [ ] **Step 4: Run Node and Playwright focused tests**

Run: `node --test tests/frontend/resource-discovery-ui.test.mjs tests/frontend/*.test.mjs`

Run: `python -m pytest tests/e2e/test_resource_discovery_ui.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Independent review and commit**

```bash
git add static/modules/resource-discovery.js static/main.mjs static/app.js static/styles.css tests/frontend/resource-discovery-ui.test.mjs tests/e2e/test_resource_discovery_ui.py
git commit -m "feat: add durable local resource discovery ui"
```

### Task 8: Real Windows verification and cross-platform regression evidence

**Files:**
- Create: `tests/integration/test_resource_discovery_real.py`
- Modify: `tests/unit/test_launcher_torch_policy.py`
- Modify: `tests/unit/test_launcher_workers.py`
- Modify only after all three plans pass: `VERSION.txt`, `static/index.html`, `static/main.mjs`, `README.md`, `docs/codex-handoff.md`

- [ ] **Step 1: Run a real no-checkpoint environment probe**

Create a temporary working directory containing no `.pt`, run the selected Python probe from that directory, and assert `status=AVAILABLE` when imports pass. Record actual Python, Ultralytics, Torch, TorchVision, CUDA, and GPU values. This test skips with an explicit reason only if the machine truly lacks Ultralytics.

Run: `python -m pytest tests/integration/test_resource_discovery_real.py::test_real_environment_available_without_checkpoint -q -s`

Expected: PASS, or SKIP with the exact missing runtime reason; never FAIL with `测试模型不存在`.

- [ ] **Step 2: Run real Windows task/API/UI checks**

Start the API and `task_worker.py --roles discovery`, create an environment-detection task, observe it reach a terminal state, verify cache persistence after API restart, scan a controlled directory containing every supported extension, and run the focused Playwright flow. Record task IDs and counters in `docs/codex-handoff.md`.

- [ ] **Step 3: Run cross-platform and NVIDIA-protection tests**

Run:

```bash
python -m pytest tests/unit/resource_discovery tests/api/test_resource_discovery_api.py tests/api/test_deployment_test_runtime.py tests/unit/test_launcher_torch_policy.py tests/unit/test_launcher_workers.py -q
```

Expected: all tests PASS. The launcher tests must prove an existing `torch.cuda.is_available()==True` environment never receives a CPU Torch install command. Linux mount behavior may be unit-tested on Windows; it is marked `未真实验证` until executed on Linux.

- [ ] **Step 4: Preserve server-import scale evidence in the combined gate**

Run the required 10k benchmark:

```powershell
python -m pytest tests/performance/test_local_storage_scan_scale.py -q -s
```

Then attempt the 100k benchmark:

```powershell
$env:MC_RUN_100K_STORAGE_TEST='1'
python -m pytest tests/performance/test_local_storage_scan_scale.py -q -s
```

Record elapsed time, peak memory, candidate/material row counts, and duplicate-copy count. Insufficient host time/disk is recorded as `未验证` with the real skip/failure; it is never rewritten as PASS.

- [ ] **Step 5: Perform the real Windows combined startup/browser acceptance**

Start the platform using the documented Windows launcher and its normal Worker orchestration. Verify `/api/health`; run server-directory import and server-ZIP import from the browser; confirm indexing; refresh; verify preview; run Ultralytics environment detection; explicitly select one environment; run controlled-directory model scan; then restart API and prove both caches remain. Confirm no indexed external image was copied into project uploads. Stop only processes started by this acceptance run.

- [ ] **Step 6: Run the complete combined regression only after the other two plans are complete**

Run:

```bash
python -m pytest -q
node --test tests/frontend/*.test.mjs
npx playwright test
```

Record exact passed/failed/skipped counts. Any failure blocks version update and blocks progress.

- [ ] **Step 7: Upgrade version and release documentation once**

Upgrade once to `42.23.0` only after all three plans and all full regressions pass. Update `VERSION.txt`, every browser cache query, README capability/limitation sections, and `docs/codex-handoff.md`. Document server directory/ZIP behavior, security boundary, `MC_SERVER_IMPORT_DIR`, explicit non-support of server-ZIP YOLO txt annotations, resource-discovery behavior, and whether Windows, Linux/NVIDIA, real CUDA, 100k scale, and real whole-machine scans were executed or remain unverified.

- [ ] **Step 8: Verify version consistency before review**

Run: `rg -n "42\.22\.4|422204" VERSION.txt README.md static docs/codex-handoff.md`

Expected: no stale runtime/cache version references remain in changed release surfaces.

- [ ] **Step 9: Independent final review and commit**

After final spec and code-quality review approves the complete three-plan diff:

```bash
git add VERSION.txt static/index.html static/main.mjs README.md docs/codex-handoff.md tests/integration/test_resource_discovery_real.py tests/unit/test_launcher_torch_policy.py tests/unit/test_launcher_workers.py
git commit -m "chore: release verified local resources v42.23.0"
```

- [ ] **Step 10: Re-run all suites after the final commit**

Run `python -m pytest -q`, `node --test tests/frontend/*.test.mjs`, `npx playwright test`, and `git status --short --branch` again. Record exact totals and require a clean `feat/windows-p0` worktree.

- [ ] **Step 11: Push only the feature branch and prove remote parity**

```bash
git push origin feat/windows-p0
git rev-parse HEAD
git rev-parse origin/feat/windows-p0
```

Expected: both SHAs are identical. Do not checkout, modify, merge, or push `main`.

## Cross-plan dependency and execution order

Execute sequentially with no parallel implementers:

1. `2026-09-08-nvidia-launcher-safety.md` Tasks 1-3. This protects the known-good CUDA environment before any new detection path is allowed to select or bootstrap Python.
2. `2026-09-08-server-local-material-import.md` Tasks 1-8. Complete candidate persistence, SHA lookup, local streaming, ZIP safety, confirmation requeue, Worker phases, and backend APIs.
3. This plan Tasks 1-6. Complete discovery persistence, probes, scanners, durable APIs, and model resolution before UI integration.
4. `2026-09-08-server-local-material-import.md` Tasks 9-11. Complete import UI and lifecycle verification against the now-stable Worker/API baseline.
5. This plan Task 7. Complete resource-discovery UI without colliding with earlier `static/app.js` work.
6. Run both plans' focused end-to-end checks, then execute one combined final regression and one version upgrade using this plan Task 8. The server-import plan Task 12 is absorbed into this combined final gate; do not perform an earlier version bump.

For every task, the controller enforces this order: implement with TDD, run the task's focused tests, perform independent specification review, perform independent code-quality review, fix and re-review all findings, then commit. No implementer starts the next task while any test or review finding remains open.
