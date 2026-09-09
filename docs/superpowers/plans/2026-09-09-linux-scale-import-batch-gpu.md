# Linux Scale Import, Batch Processing, and GPU Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 20k+ material workflows durable and bounded, import real YOLO annotations safely, schedule and utilize NVIDIA GPUs effectively, isolate source images from training mutations, recover external-source changes, and keep startup responsive. Treat 20k as the production baseline, 100k as the bounded architecture target, and do not claim unverified 1M end-to-end readiness.

**Architecture:** Extend the existing SQLite `TaskRepository`, per-task artifact SQLite manifests, `MaterialRepository`, Storage Providers, Worker Registry, and Scheduler. FastAPI remains a validation/task-creation boundary; scans, selection materialization, annotation conversion, batch mutations, GPU admission, and training run in durable Workers. Existing exact image-ID and unified-material-pool contracts remain authoritative.

**Tech Stack:** Python 3.10–3.12, FastAPI/Pydantic, SQLite/WAL, Pillow, PyYAML, Ultralytics/PyTorch, vanilla JavaScript modules, pathlib, existing task runtime.

---

## File responsibility map

- `platform_core/training_tasks.py`: isolated training bundle creation, device validation, durable training orchestration.
- `train_worker.py`: final CUDA assertion and actual-device evidence.
- `platform_core/gpu_resources.py`: GPU inventory, reservations, admission, auto-tuning inputs, and runtime metrics.
- `platform_core/training_metrics.py`: bounded time-series metrics and rule-based resource diagnosis.
- `platform_core/storage/yolo_import.py`: safe YOLO layout/YAML/box parsing and quality aggregation.
- `platform_core/storage/import_candidates.py`: durable dataset, label-map, and annotation candidate tables.
- `platform_core/storage/import_tasks.py`: scan/index orchestration and annotation persistence.
- `platform_core/storage/rescan_tasks.py`: durable NEW/MISSING/CHANGED source reconciliation.
- `platform_core/annotation_repository.py`: SQLite annotation state/box storage with legacy JSON fallback.
- `platform_core/material_repository.py`: bounded selection and set-based updates.
- `platform_core/material_selection.py`: normalized reusable server-side selection specifications.
- `platform_core/material_batches.py`: durable generic material batch handler.
- `platform_core/task_runtime/models.py`, `platform_core/task_runtime/repository.py`: new task kind and worker-instance leases.
- `platform_core/task_runtime/task_logs.py`: task-created durable logs and subprocess stream capture.
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

The implementation must always copy into a sibling temporary file, fsync it, verify size/SHA256, and publish with `os.replace()`. It must never call `os.link()` or create a symlink. Existing destination files are reusable only when their hash matches the snapshot and they are not the same inode/file ID as the source.

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

- [ ] Add bundle-size calculation and disk-space preflight with configurable reserve. Recheck before each atomic copy; fail explicitly and never fall back to links.
- [ ] Update `materialize_portable_dataset()` to call only `_copy_verified_isolated()`. If an old bundle is a hard link to the source, rebuild it atomically even when its hash matches.
- [ ] Add lifecycle cleanup for orphan `.copy` files and rebuildable task work/bundle directories only; never clean a Storage Source, content cache, or final model artifact.
- [ ] Add one focused proof: create an old source/bundle hard link on the same filesystem, rematerialize, confirm inode separation, overwrite bundle bytes, and assert source bytes, size, and SHA256 are unchanged.
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

YAML parsing must use `yaml.safe_load`; every final object key must stay under the current Storage Source root. Local YAML absolute `path` is allowed only when `resolve()` remains inside that root, then normalized to a relative object key. Multiple YAML candidates fail with `YOLO_YAML_AMBIGUOUS`. Resolve image/label pairs from YAML plus actual layouts including `images/train`, `train/images`, sibling label trees, list files, and same-directory pairs.

- [ ] Implement the exact box rules from the design: zero/nonfinite/unknown/fully-outside skipped; every box with positive intersection clipped; large overflow recorded as a warning rather than discarded; empty TXT confirmed negative; missing TXT unannotated.
- [ ] Extend candidate SQLite initialization additively with `dataset_manifest`, `candidate_annotations`, and `label_mapping`; add batch insert/read methods and aggregated quality queries. Do not place all boxes in `result.json`.
- [ ] Update `_scan()` so `import_format=auto|images|yolo`; images mode preserves current behavior, auto uses a unique YAML when present, yolo requires it.
- [ ] Add one table-driven parser test covering valid, zero-area, minor clipping, severe-but-intersecting clipping, fully outside, empty file, missing class, invalid numeric values, allowed in-root absolute Local path, rejected escaped path, and both common directory layouts.
- [ ] Run only `py_compile` for changed modules and `python -m pytest tests/unit/storage/test_yolo_import.py -q`.
- [ ] Commit: `feat: scan yolo annotations with quality rules`.

### Task 3: Confirm label mappings and persist platform annotations

**Files:**
- Modify: `platform_core/storage/import_candidates.py`
- Modify: `platform_core/storage/import_tasks.py`
- Create: `platform_core/annotation_repository.py`
- Modify: `platform_core/annotations.py`
- Modify: `platform_core/training_tasks.py`
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
- [ ] Add an SQLite `AnnotationRepository` keyed by image ID with `annotation_state=unannotated|annotated|confirmed_empty`, version/content digest, boxes, and timestamps. New writes use SQLite; reads fall back to legacy `annotations/<image_id>.json` and migrate lazily on update. Do not bulk-delete or rewrite old files.
- [ ] During `_index_confirmed()`, first batch match `storage_source_id + object_key`. Existing material keeps its image ID and receives supplemental/updated annotation; only new object keys allocate IDs. Batch material upserts first, then write normalized annotations by stable image ID.
- [ ] Mark valid nonempty annotations `annotation_state=annotated`; empty TXT `annotation_state=confirmed_empty`, `negative_sample=true`; missing TXT remains `unannotated`. Maintain old `annotated` fields only as compatibility projections.
- [ ] Update training eligibility so both `annotated` and `confirmed_empty` enter YOLO datasets; confirmed-empty samples intentionally have no label rows/files. Never require `box_count > 0` for a known negative.
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
- Create: `platform_core/task_runtime/task_logs.py`
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/worker_registry.py`
- Modify: `app.py`

- [ ] Add `TaskKind.MATERIAL_BATCH` and storage worker registration capability `materials.batch`.
- [ ] Implement per-task `selection.sqlite3` with stable image IDs and `PENDING/RUNNING/SUCCEEDED/FAILED` row state.
- [ ] Implement `MaterialBatchHandler.run/recover` stages: `selecting`, `executing`, `finalizing`. Revision is checked only between estimate and confirmed creation. After task creation, materialize the immutable ID manifest promptly and never fail because an unrelated later repository revision changed.
- [ ] Create the real task log artifact when a durable task is created; set `log_ref` only after creation succeeds. Provide append/capture helpers so Worker and child-process stdout/stderr are tied to task ID.
- [ ] Add operation adapters for `MARK_CLEAN_SKIPPED`, `CLEAN`, `DELETE_INDEX`, `DELETE_SOURCE`, `ADD_LABELS`, `REMOVE_LABELS`, and `AI_ANNOTATE`. Reuse current cleaning/annotation/storage services; do not duplicate algorithms.
- [ ] Implement `DELETE_SOURCE` as tombstone manifest → source delete → platform index delete. Partial failures retain the index, full storage reference, error, and retry state. Never delete the index first.
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

The probe subprocess imports Torch, returns CUDA availability/count/names/UUID/version, and never changes an explicit request to CPU. Normalize legacy `0` to `cuda:0` only at API boundaries; preserve `auto` until Scheduler assignment.

- [ ] Add `GET /api/v62/training-devices`. Return GPU devices first, CPU last, and recommended `cuda:0` when available.
- [ ] Change `TrainReq.device` default to `auto`; `_enqueue_explicit_training()` persists canonical `requested_device` without prematurely binding `auto`. Explicit CUDA failures are terminal; no fallback.
- [ ] Before constructing argv, Training Worker uses its selected training Python and `require_training_device()` for the Scheduler-assigned device.
- [ ] Run `py_compile` for the three files.
- [ ] Commit: `fix: prefer verified cuda training devices`.

### Task 8: Add GPU Resource Manager and admission control

**Files:**
- Create: `platform_core/gpu_resources.py`
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/task_runtime/scheduler.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `task_worker.py`
- Modify: `app.py`

- [ ] Add additive SQLite tables for GPU inventory, bounded samples, and TTL reservations. Persist GPU UUID/index/model/total and free memory/utilization, reserved memory, task/worker owner, policy, and lease timestamps.
- [ ] Probe live GPU metrics through NVML when installed, otherwise structured `nvidia-smi`; use Torch device discovery only as a validation fallback, never fake utilization.
- [ ] Implement Scheduler scoring for `auto`: available memory after reservations and safety margin, current task count, recent utilization, and device health. Spread independent tasks across free GPUs before sharing.
- [ ] Implement `gpu_policy=auto|exclusive|shared`, default auto/exclusive-first. Enforce configurable max tasks, memory reserve, max reserved ratio, worker slot, and evidence-based sharing admission. When evidence is insufficient, keep queued.
- [ ] Atomically reserve before training claim/start, renew with task lease, release on completion, and recover expired reservations. Explicit `cuda:N` waits for that GPU; no resource path falls back to CPU.
- [ ] Expose a compact read-only GPU resource summary and queue reason for task details. Do not expose an operationally misleading one-task `resource_key` as the complete scheduler.
- [ ] Run Python syntax checks. Real multi-GPU and sharing behavior remains a Linux/NVIDIA manual acceptance item unless this machine exposes those devices.
- [ ] Commit: `feat: schedule training against gpu reservations`.

### Task 9: Add automatic training resource tuning and runtime diagnosis

**Files:**
- Create: `platform_core/training_metrics.py`
- Modify: `platform_core/gpu_resources.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `train_worker.py`
- Modify: `app.py`
- Modify: `static/modules/training-devices.js`
- Modify: `static/app.js`

- [ ] Add `resource_strategy=auto|manual` and advanced fields. Keep them collapsed in the UI; auto is default.
- [ ] Resolve batch from actual assigned-GPU free memory, model scale, imgsz, safety margin, and Ultralytics/PyTorch autobatch or bounded probe. Persist resolved value and evidence. OOM retry only steps batch down to a configured minimum and then fails.
- [ ] Resolve workers from available CPUs, concurrent training reservations, OS process constraints, storage source/cache status, and IO pressure; do not use `workers=0` as Linux/GPU default.
- [ ] Resolve cache as `ram|disk|false` from dataset bytes, RAM/disk headroom, and remote material cache state. Manual values are validated, not silently replaced.
- [ ] Write actual batch/workers/cache, GPU/VRAM and CPU samples, images/sec, epoch duration, and total duration to bounded per-task metrics SQLite/Artifact. Sample GPU/CPU at low frequency and collect epoch metrics from the training callback/process.
- [ ] Implement deterministic windowed diagnoses for batch headroom, data-loading/decoding/IO bottleneck, healthy utilization, and memory pressure. Page shows only device, effective values, throughput, resource summary, and one diagnosis.
- [ ] Run Python/JavaScript syntax checks. Do not claim A800 optimization until the user reruns representative data and compares images/sec/epoch duration against the existing batch=4/workers=0 baseline.
- [ ] Commit: `feat: tune and observe gpu training resources`.

### Task 10: Preserve the assigned GPU through the real Ultralytics process

**Files:**
- Modify: `platform_core/training_tasks.py`
- Modify: `train_worker.py`
- Create: `static/modules/training-devices.js`
- Modify: `static/main.mjs`
- Modify: `static/app.js`

- [ ] In `_training_argv()`, translate Scheduler-assigned canonical `cuda:0` to Ultralytics CLI `0` only when appending `--device`. Preserve `requested_device`, `assigned_device`, and `actual_device` separately in payload/job/result; append resolved batch/workers/cache.
- [ ] In `train_worker.py`, set parser default to `auto`, require a concrete assigned device before training, validate CUDA before loading/training, and update job JSON before `model.train()` with all three device fields, GPU UUID/name/index, Torch/CUDA versions, PID, effective Ultralytics argument, batch/workers/cache.
- [ ] After training starts, never overwrite actual-device evidence with configuration-only data. Add it to the durable result and task detail.
- [ ] Change latest training UI to load `/api/v62/training-devices`, render auto plus concrete devices, default to auto/GPU recommendation, show scheduling policy, and display unavailable devices as disabled.
- [ ] Change the latest submit path to `split_mode + train_image_ids/test_image_ids`; remove `selected_image_ids` from the generated payload so `/api/v12/.../train/start` always uses `_enqueue_explicit_training()`.
- [ ] Keep independent test-set and random test-percent modes. Training material selection remains exact image ID; do not add dataset IDs.
- [ ] Run Python/JavaScript syntax checks. Real A800 execution is deferred to the documented Linux acceptance because this workspace is Windows.
- [ ] Commit: `fix: keep assigned cuda device through training execution`.

### Task 11: Prevent accidental duplicate all-role Workers

**Files:**
- Modify: `platform_core/task_runtime/repository.py`
- Create: `platform_core/task_runtime/worker_instances.py`
- Modify: `platform_core/task_runtime/__init__.py`
- Modify: `task_worker.py`
- Modify: `launcher.py`

- [ ] Add an additive `worker_instances` table keyed by SHA256 of resolved data dir, hostname, and sorted roles. Store owner token, worker ID, PID, start/heartbeat/expiry.
- [ ] Implement atomic `acquire`, `renew`, and owner-checked `release`. Expired rows can be replaced; active rows raise `DuplicateWorkerInstance` with the existing worker/PID.
- [ ] Add `--allow-parallel`; without it, `task_worker.py --roles all` acquires slot `default`. Role-specific workers naturally use different keys.
- [ ] Require explicit named training slots for intentional parallel workers and register them with GPU Resource Manager. Duplicate all-role launch remains rejected even when GPU sharing is configured.
- [ ] Renew the instance lease around scheduler loops and release in `finally`. Existing task leases remain unchanged.
- [ ] Make launcher pass a stable descriptive worker ID. If a duplicate exists, show a clear message rather than starting another process.
- [ ] Run Python syntax checks only unless a concrete SQLite acquisition failure appears.
- [ ] Commit: `fix: prevent duplicate local worker instances`.

### Task 12: Add Storage Source rescan and change recovery

**Files:**
- Create: `platform_core/storage/rescan_tasks.py`
- Modify: `platform_core/storage/import_candidates.py`
- Modify: `platform_core/worker_registry.py`
- Modify: `platform_core/material_repository.py`
- Modify: `platform_core/storage/manager.py`
- Modify: `app.py`
- Modify: `static/modules/server-material-import.js`
- Modify: `static/app.js`

- [ ] Add a durable rescan task for Local/OSS/S3/Remote. Stream provider objects into a task SQLite manifest and batch compare by `storage_source_id + object_key`, size, etag, and verified SHA256 where needed.
- [ ] Classify `NEW`, `MISSING`, `CHANGED`, and `UNCHANGED`; return bounded totals/examples and wait for confirmation before mutating the platform index.
- [ ] Confirmed NEW items reuse import indexing. MISSING items become explicitly unavailable by default rather than immediately deleted. CHANGED items update storage metadata, invalidate matching content cache, append audit history, and mark existing annotation for review without erasing it.
- [ ] Make `SOURCE_CONTENT_CHANGED` training failures link to this rescan/reconcile path. Rescan remains index-only and never copies the entire external source locally.
- [ ] Ensure delete-source and rescan manifests are independently recoverable and cannot race into silent index loss; use existing task/resource leases.
- [ ] Run Python/JavaScript syntax checks only unless a direct rescan path exposes a concrete failure.
- [ ] Commit: `feat: reconcile external storage changes`.

### Task 13: Remove full material loading from startup and refreshed workflows

**Files:**
- Modify: `app.py`
- Modify: `static/modules/material-pagination-runtime.js`
- Modify: `static/app.js`
- Modify: `static/main.mjs`

- [ ] Split `_v53_build_snapshot()` output into core metadata plus material summary. Omit full `images`; return counts/revision and at most the current 48-row material page through the existing paginated endpoint.
- [ ] Stop bootstrap worker from calling `load_images()` for every project merely to count; use `MaterialRepository.count()` and targeted migration checks.
- [ ] Replace startup annotation-directory walks with AnnotationRepository count/summary queries; legacy JSON fallback is per-image/lazy, never a refresh-time full scan.
- [ ] Remove training and batch-enabled pages from `FULL_MATERIAL_PAGES` after their selectors use server pagination/selection specs. Keep only untouched workflows that still require the pool, and document them as remaining work if any.
- [ ] Make refresh load current-page dependencies only. Prevent repeated full `loadAll()` calls from resource/task buttons when a narrower loader exists.
- [ ] Ensure background bootstrap is not blocked by resource discovery, all-material annotation reads, or model full scans.
- [ ] Run Python/JavaScript syntax checks and inspect the startup snapshot response construction. Do not run browser E2E unless syntax or direct startup produces a specific failure.
- [ ] Commit: `perf: keep startup and refresh material-bounded`.

### Task 14: Release metadata and bounded validation handoff

**Files:**
- Modify: `VERSION.txt`
- Modify: `README.md`
- Modify: `docs/codex-handoff.md`
- Modify: `static/index.html`
- Modify: `static/main.mjs`
- Modify: `static/app.js`

- [ ] Bump version to `42.24.0` and unify cache/version strings only after every implementation task has at least passed its stated syntax/build gate.
- [ ] Document the exact new task/API/device contracts and compatibility boundary.
- [ ] Run one final syntax/build pass only across files changed by this plan; do not run full pytest/Node/Playwright without a new concrete failure signal or explicit user approval.
- [ ] Record truthful unverified items: real 20k dataset rerun, real OSS/S3/Remote annotated import, and real A800 training.
- [ ] Provide Linux/A800 minimal acceptance commands:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
ps -ef | grep '[t]rain_worker.py'
nvidia-smi pmon -s um -c 5
```

Expected evidence: task detail shows requested/assigned/actual device consistently; train-worker argv contains the assigned `--device`; job/result GPU UUID/name and PID match `nvidia-smi`; metrics contain real samples, effective batch/workers/cache, images/sec and epoch duration. Compare a representative run with the existing A800 `batch=4/workers=0` baseline. Sharing requires two deliberately created tasks and reservation/admission evidence; it is not proven by two accidentally launched workers. Any missing evidence is not a PASS for that capability.
- [ ] Commit: `release: prepare version 42.24.0`.

## Plan self-review

- Every requested symptom maps to a task: YOLO/layout/labels/negative samples/supplemental annotations (2–3), all batch operations/browser IDs/recovery/logs (4–6), GPU discovery/scheduling/tuning/device evidence (7–10), hard-link safety (1), duplicate workers (11), Storage Source reconciliation (12), refresh/annotation indexing (13).
- Training remains image-ID based and Storage Source remains independent.
- Only two new focused unit-test files are planned: hard-link isolation is explicitly required, and YOLO parser tolerance is a critical deterministic boundary. Other validation stops at compile/syntax unless a specific failure appears.
- A800 CUDA/GPU training is an accepted user-reported baseline, but new scheduling, auto-tuning, sharing, and metrics remain unverified until rerun in Linux/NVIDIA; the Windows workspace cannot certify them.
- 100 万级 is not claimed as end-to-end validated. SQLite repositories/manifests remove known linear-memory and small-file bottlenecks, but real capacity/backup/maintenance validation remains explicit follow-up evidence.
- No task merges or modifies `main`.
