# Linux Scale Import, Batch Processing, and GPU Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 20k–1M material workflows durable and bounded, import real YOLO annotations safely, run NVIDIA training on the selected CUDA device, isolate source images from training mutations, and keep startup responsive.

**Architecture:** Extend the existing SQLite `TaskRepository`, per-task artifact SQLite manifests, `MaterialRepository`, Storage Providers, and Worker Registry. FastAPI remains a validation/task-creation boundary; scans, selection materialization, annotation conversion, batch mutations, and training run in durable Workers. Existing exact image-ID and unified-material-pool contracts remain authoritative.

**Tech Stack:** Python 3.10–3.12, FastAPI/Pydantic, SQLite/WAL, Pillow, PyYAML, Ultralytics/PyTorch, vanilla JavaScript modules, pathlib, existing task runtime.

---

## File responsibility map

- `platform_core/training_tasks.py`: isolated training bundle creation, device validation, durable training orchestration.
- `train_worker.py`: final CUDA assertion and actual-device evidence.
- `platform_core/storage/yolo_import.py`: safe YOLO layout/YAML/box parsing and quality aggregation.
- `platform_core/storage/import_candidates.py`: durable dataset, label-map, and annotation candidate tables.
- `platform_core/storage/import_tasks.py`: scan/index orchestration and annotation persistence.
- `platform_core/material_repository.py`: bounded selection and set-based updates.
- `platform_core/material_selection.py`: normalized reusable server-side selection specifications.
- `platform_core/material_batches.py`: durable generic material batch handler.
- `platform_core/task_runtime/models.py`, `platform_core/task_runtime/repository.py`: new task kind and worker-instance leases.
- `platform_core/worker_registry.py`, `task_worker.py`, `launcher.py`: batch registration and duplicate worker prevention.
- `platform_core/training_devices.py`: canonical device discovery/normalization/probing.
- `app.py`: thin request models and APIs delegating to the modules above.
- `static/modules/material-batches.js`: scope/count/task progress runtime.
- `static/modules/server-material-import.js`: format/mapping/quality review model.
- `static/modules/training-devices.js`: device picker and exact durable training payload.
- `static/modules/material-pagination-runtime.js`, `static/main.mjs`, `static/app.js`: install runtimes and remove browser-side all-ID expansion/full-pool startup paths.

### Task 1: Isolate training bundle files from source materials

**Files:**
- Modify: `platform_core/training_tasks.py`
- Create: `tests/unit/test_training_bundle_isolation.py`

- [ ] Replace `_copy_or_link_verified()` with `_copy_verified_isolated()`.

The implementation must always copy into a sibling temporary file, fsync it, verify size/SHA256, and publish with `os.replace()`. It must never call `os.link()` or create a symlink. Existing destination files are reusable only when their hash matches the snapshot.

```python
def _copy_verified_isolated(source: Path, destination: Path, expected_hash: str) -> None:
    if not source.is_file() or source.stat().st_size <= 0:
        raise FileNotFoundError(...)
    if _sha256(source) != expected_hash:
        raise ValueError(...)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256(destination) != expected_hash:
            raise ValueError(...)
        return
    fd, temp_name = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.", suffix=".copy")
    temporary = Path(temp_name)
    try:
        with source.open("rb") as input_stream, os.fdopen(fd, "wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if temporary.stat().st_size <= 0 or _sha256(temporary) != expected_hash:
            raise OSError(...)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
```

- [ ] Update `materialize_portable_dataset()` to call only `_copy_verified_isolated()`.
- [ ] Add one focused proof: create source and bundle on the same filesystem, materialize, overwrite bundle bytes, and assert source bytes, size, and SHA256 are unchanged; where meaningful, assert inode differs.
- [ ] Run only:

```powershell
python -m py_compile platform_core/training_tasks.py
python -m pytest tests/unit/test_training_bundle_isolation.py -q
```

- [ ] Commit: `fix: isolate training bundles from source materials`.

### Task 2: Add safe YOLO dataset scanner and quality analysis

**Files:**
- Create: `platform_core/storage/yolo_import.py`
- Modify: `platform_core/storage/import_candidates.py`
- Modify: `platform_core/storage/import_tasks.py`
- Modify: `platform_core/storage/__init__.py`
- Create: `tests/unit/storage/test_yolo_import.py`

- [ ] Implement `YoloDatasetScanner` with these public types:

```python
@dataclass(frozen=True)
class YoloDatasetLayout:
    yaml_key: str
    split_image_roots: dict[str, tuple[str, ...]]
    names: dict[int, str]

@dataclass(frozen=True)
class ParsedYoloBox:
    external_class_id: int
    class_name: str
    cx: float
    cy: float
    width: float
    height: float
    action: str
    line_number: int

def discover_yolo_layout(provider, prefix: str, dataset_yaml: str = "") -> YoloDatasetLayout: ...
def parse_yolo_text(text: str, names: Mapping[int, str], object_key: str) -> ParseResult: ...
```

YAML parsing must use `yaml.safe_load`; every joined object key must stay under the scanned prefix. Multiple YAML candidates fail with `YOLO_YAML_AMBIGUOUS`.

- [ ] Implement the exact box rules from the design: zero/nonfinite/unknown/outside skipped, <=5% overflow clipped, >5% overflow skipped, empty TXT confirmed negative, missing TXT unannotated.
- [ ] Extend candidate SQLite initialization additively with `dataset_manifest`, `candidate_annotations`, and `label_mapping`; add batch insert/read methods and aggregated quality queries. Do not place all boxes in `result.json`.
- [ ] Update `_scan()` so `import_format=auto|images|yolo`; images mode preserves current behavior, auto uses a unique YAML when present, yolo requires it.
- [ ] Add one table-driven parser test covering valid, zero-area, minor clipping, severe overflow, empty file, missing class, and invalid numeric values.
- [ ] Run only `py_compile` for changed modules and `python -m pytest tests/unit/storage/test_yolo_import.py -q`.
- [ ] Commit: `feat: scan yolo annotations with quality rules`.

### Task 3: Confirm label mappings and persist platform annotations

**Files:**
- Modify: `platform_core/storage/import_candidates.py`
- Modify: `platform_core/storage/import_tasks.py`
- Modify: `platform_core/annotations.py`
- Modify: `app.py`
- Modify: `static/modules/server-material-import.js`
- Modify: `static/app.js`
- Modify: `static/styles.css`

- [ ] Extend `StorageImportScanReq` with `import_format` and optional relative `dataset_yaml`; reject COCO/VOC with an explicit not-supported response rather than silently importing only images.
- [ ] Extend public scan result with bounded quality aggregates and external class mapping suggestions; redact absolute paths.
- [ ] Extend confirmation payload:

```python
class StorageImportConfirmReq(BaseModel):
    object_keys: Optional[List[str]] = None
    label_mapping: Dict[str, str] = {}
    create_labels: List[ImportLabelCreate] = []
    accept_quality_report: bool = False
```

- [ ] Validate that every external class with accepted boxes maps by name to exactly one active platform label or one explicitly created label. Persist mapping digest in `scan/confirmation.json`; replay with the same digest is idempotent, conflicting replay returns 409.
- [ ] During `_index_confirmed()`, batch material upserts first, then write normalized annotation JSON by stable image ID. Mark valid nonempty annotations `annotated=true`; empty TXT `annotated=true`, `annotation_state=confirmed_empty`, `negative_sample=true`; missing TXT remains unannotated.
- [ ] Add indexing checkpoint counters `annotations_written`, `boxes_imported`, `boxes_skipped`, `negative_samples` and reconcile all selected candidates before success.
- [ ] Update import review UI to select Images/YOLO, show quality totals/examples, and require unresolved label mappings before enabling confirm. Existing storage/ZIP modes remain intact.
- [ ] Run `py_compile` and `node --check` for changed files. Only add a focused API test if compilation or manual payload inspection exposes a concrete failure.
- [ ] Commit: `feat: import confirmed yolo annotations`.

### Task 4: Add reusable server-side selection and set-based repository operations

**Files:**
- Create: `platform_core/material_selection.py`
- Modify: `platform_core/material_repository.py`
- Modify: `platform_core/material_repository_batch.py`

- [ ] Define `MaterialFilters`, `SelectionScope`, and `MaterialSelectionSpec`. Reject unknown fields, cap explicit ID payloads, and normalize labels/source IDs without changing OR semantics.
- [ ] Make one SQL filter builder authoritative for `list_page`, `count_filtered`, and `iter_filtered_ids`.
- [ ] Add `current_revision()`, keyset `iter_filtered_ids()`, `patch_many()`, `patch_filtered()`, `add_labels_many()`, `remove_labels_many()`, and bounded `remove_many()`.
- [ ] Use a temporary SQLite ID table or <=500-ID chunks. Do not interpolate arbitrary field names; expose a fixed allowlist of mutable material fields.
- [ ] Ensure each batch updates structured columns, `material_labels`, normalized `payload_json`, and revision in one transaction. No new hot path may call `mutate()`.
- [ ] Run `py_compile`. If an SQLite variable-limit or payload consistency failure appears, run only the existing material repository targeted test that reproduces it.
- [ ] Commit: `perf: add bounded material selection updates`.

### Task 5: Implement durable generic material batch tasks

**Files:**
- Create: `platform_core/material_batches.py`
- Modify: `platform_core/task_runtime/models.py`
- Modify: `platform_core/worker_registry.py`
- Modify: `app.py`

- [ ] Add `TaskKind.MATERIAL_BATCH` and storage worker registration capability `materials.batch`.
- [ ] Implement per-task `selection.sqlite3` with stable image IDs and `PENDING/RUNNING/SUCCEEDED/FAILED` row state.
- [ ] Implement `MaterialBatchHandler.run/recover` stages: `selecting`, `executing`, `finalizing`. `FILTERED` checks repository revision before materializing IDs; mismatch fails with `MATERIAL_SELECTION_REVISION_CHANGED`.
- [ ] Add operation adapters for `MARK_CLEAN_SKIPPED`, `CLEAN`, `DELETE_INDEX`, `DELETE_SOURCE`, `ADD_LABELS`, `REMOVE_LABELS`, and `AI_ANNOTATE`. Reuse current cleaning/annotation/storage services; do not duplicate algorithms.
- [ ] Add APIs:

```text
POST /api/v62/projects/{project_id}/material-batches/estimate
POST /api/v62/projects/{project_id}/material-batches
GET  /api/v62/projects/{project_id}/material-batches/{task_id}
POST /api/v62/projects/{project_id}/material-batches/{task_id}/cancel
```

Creation returns 202 immediately. Public state exposes true total/processed/succeeded/failed/current/error examples. `DELETE_SOURCE` still requires `confirmation=DELETE_SOURCE`.
- [ ] Run `py_compile`. Do not run unrelated clean/AI/deletion suites unless a concrete compile/runtime failure requires one targeted test.
- [ ] Commit: `feat: run material batches as durable tasks`.

### Task 6: Replace browser all-ID expansion with explicit batch scopes

**Files:**
- Create: `static/modules/material-batches.js`
- Modify: `static/modules/material-pagination-runtime.js`
- Modify: `static/main.mjs`
- Modify: `static/app.js`
- Modify: `static/styles.css`

- [ ] Remove production calls to `materialFilteredIds61()` for filtered clean/ready/delete/label operations. Keep the function only as a temporary compatibility wrapper if another untouched legacy page still needs it.
- [ ] Build `FILTERED` selection specs from the exact current server filters; current page and current selected use bounded explicit IDs.
- [ ] Add a three-scope chooser with exact labels: `当前页`, `全部筛选结果`, `当前已选`.
- [ ] Call estimate first and show operation plus exact count. The confirm button creates a task using the returned repository revision.
- [ ] Add persistent task dock/polling; closing UI aborts polling only. On refresh, restore active task IDs from localStorage and GET their current state.
- [ ] Route existing no-clean, clean, delete, tag, and AI bulk buttons through this runtime.
- [ ] Run `node --check` for changed JavaScript files and `git diff --check`.
- [ ] Commit: `feat: add scoped material batch controls`.

### Task 7: Discover and validate canonical training devices

**Files:**
- Create: `platform_core/training_devices.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `app.py`

- [ ] Implement:

```python
@dataclass(frozen=True)
class TrainingDevice:
    value: str          # cpu or cuda:<index>
    label: str
    available: bool
    gpu_name: str = ""

def normalize_device(value: str) -> str: ...
def discover_training_devices(python_path: str) -> DeviceReport: ...
def require_training_device(python_path: str, requested: str) -> TrainingDeviceEvidence: ...
```

The probe subprocess imports Torch, returns CUDA availability/count/names/version, and never changes the request to CPU. Normalize legacy `0` to `cuda:0` only at API boundaries.

- [ ] Add `GET /api/v62/training-devices`. Return GPU devices first, CPU last, and recommended `cuda:0` when available.
- [ ] Change `TrainReq.device` default to `auto`; `_enqueue_explicit_training()` resolves `auto` once and persists canonical `requested_device`. Its resource key is `training:gpu:0` or `training:cpu`.
- [ ] Before constructing argv, Training Worker uses its selected training Python and `require_training_device()`. CUDA failures are explicit and terminal; no fallback.
- [ ] Run `py_compile` for the three files.
- [ ] Commit: `fix: prefer verified cuda training devices`.

### Task 8: Preserve the selected GPU through the real Ultralytics process

**Files:**
- Modify: `platform_core/training_tasks.py`
- Modify: `train_worker.py`
- Create: `static/modules/training-devices.js`
- Modify: `static/main.mjs`
- Modify: `static/app.js`

- [ ] In `_training_argv()`, translate canonical `cuda:0` to Ultralytics CLI `0` only when appending `--device`. Preserve canonical value in payload/job/result.
- [ ] In `train_worker.py`, set parser default to `auto`, validate CUDA before loading/training, and update job JSON before `model.train()` with `requested_device`, `actual_device`, GPU name/index, Torch/CUDA versions, PID, and effective Ultralytics argument.
- [ ] After training starts, never overwrite actual-device evidence with configuration-only data. Add it to the durable result and task detail.
- [ ] Change latest training UI to load `/api/v62/training-devices`, render a select, default to recommended GPU, and display unavailable devices as disabled.
- [ ] Change the latest submit path to `split_mode + train_image_ids/test_image_ids`; remove `selected_image_ids` from the generated payload so `/api/v12/.../train/start` always uses `_enqueue_explicit_training()`.
- [ ] Keep independent test-set and random test-percent modes. Training material selection remains exact image ID; do not add dataset IDs.
- [ ] Run Python/JavaScript syntax checks. Real A800 execution is deferred to the documented Linux acceptance because this workspace is Windows.
- [ ] Commit: `fix: keep cuda device through training execution`.

### Task 9: Prevent accidental duplicate all-role Workers

**Files:**
- Modify: `platform_core/task_runtime/repository.py`
- Create: `platform_core/task_runtime/worker_instances.py`
- Modify: `platform_core/task_runtime/__init__.py`
- Modify: `task_worker.py`
- Modify: `launcher.py`

- [ ] Add an additive `worker_instances` table keyed by SHA256 of resolved data dir, hostname, and sorted roles. Store owner token, worker ID, PID, start/heartbeat/expiry.
- [ ] Implement atomic `acquire`, `renew`, and owner-checked `release`. Expired rows can be replaced; active rows raise `DuplicateWorkerInstance` with the existing worker/PID.
- [ ] Add `--allow-parallel`; without it, `task_worker.py --roles all` acquires slot `default`. Role-specific workers naturally use different keys.
- [ ] Renew the instance lease around scheduler loops and release in `finally`. Existing task leases remain unchanged.
- [ ] Make launcher pass a stable descriptive worker ID. If a duplicate exists, show a clear message rather than starting another process.
- [ ] Run Python syntax checks only unless a concrete SQLite acquisition failure appears.
- [ ] Commit: `fix: prevent duplicate local worker instances`.

### Task 10: Remove full material loading from startup and refreshed workflows

**Files:**
- Modify: `app.py`
- Modify: `static/modules/material-pagination-runtime.js`
- Modify: `static/app.js`
- Modify: `static/main.mjs`

- [ ] Split `_v53_build_snapshot()` output into core metadata plus material summary. Omit full `images`; return counts/revision and at most the current 48-row material page through the existing paginated endpoint.
- [ ] Stop bootstrap worker from calling `load_images()` for every project merely to count; use `MaterialRepository.count()` and targeted migration checks.
- [ ] Remove training and batch-enabled pages from `FULL_MATERIAL_PAGES` after their selectors use server pagination/selection specs. Keep only untouched workflows that still require the pool, and document them as remaining work if any.
- [ ] Make refresh load current-page dependencies only. Prevent repeated full `loadAll()` calls from resource/task buttons when a narrower loader exists.
- [ ] Ensure background bootstrap is not blocked by resource discovery, all-material annotation reads, or model full scans.
- [ ] Run Python/JavaScript syntax checks and inspect the startup snapshot response construction. Do not run browser E2E unless syntax or direct startup produces a specific failure.
- [ ] Commit: `perf: keep startup and refresh material-bounded`.

### Task 11: Release metadata and bounded validation handoff

**Files:**
- Modify: `VERSION.txt`
- Modify: `README.md`
- Modify: `docs/codex-handoff.md`
- Modify: `static/index.html`
- Modify: `static/main.mjs`
- Modify: `static/app.js`

- [ ] Bump version to `42.24.0` and unify cache/version strings.
- [ ] Document the exact new task/API/device contracts and compatibility boundary.
- [ ] Run one final syntax/build pass only across files changed by this plan; do not run full pytest/Node/Playwright without a new concrete failure signal or explicit user approval.
- [ ] Record truthful unverified items: real 20k dataset rerun, real OSS/S3/Remote annotated import, and real A800 training.
- [ ] Provide Linux/A800 minimal acceptance commands:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
ps -ef | grep '[t]rain_worker.py'
nvidia-smi pmon -s um -c 5
```

Expected evidence: task detail shows `requested_device=cuda:0`; train-worker argv contains `--device 0`; job/result `actual_device=cuda:0` and GPU name match; `nvidia-smi` shows the training PID consuming GPU memory/utilization. Any missing evidence is not a GPU PASS.
- [ ] Commit: `release: prepare version 42.24.0`.

## Plan self-review

- Every requested symptom maps to a task: YOLO/labels/quality (2–3), all batch operations/browser IDs/recovery (4–6), GPU chain (7–8), hard-link safety (1), duplicate workers (9), refresh latency (10).
- Training remains image-ID based and Storage Source remains independent.
- Only two new focused unit-test files are planned: hard-link isolation is explicitly required, and YOLO parser tolerance is a critical deterministic boundary. Other validation stops at compile/syntax unless a specific failure appears.
- No task merges or modifies `main`.

