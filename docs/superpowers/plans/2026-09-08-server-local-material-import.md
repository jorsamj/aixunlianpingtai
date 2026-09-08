# Server-Local Material Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable, secure, scalable indexing of server-local directories and server-side ZIP archives without copying indexed materials into project uploads.

**Architecture:** Extend the existing `MATERIAL_IMPORT` workflow with `directory_scan` and `server_zip` modes while retaining legacy/default `storage_scan` for OSS, S3/MinIO, and Remote sources. Persist scan candidates in per-task SQLite, move tasks through `AWAITING_CONFIRMATION`, and resume the same task for batched indexing after confirmation. Keep path resolution inside `LocalStorageProvider` and a focused ZIP extractor, while existing preview, annotation, cleaning, and training continue through `StorageManager`.

**Tech Stack:** Python 3.10-3.12, FastAPI/Pydantic, SQLite, Pillow, `zipfile`, pathlib, existing durable Task Runtime, browser JavaScript modules, Node test runner, Playwright, pytest.

---

## File map

- Create `platform_core/storage/import_candidates.py`: per-task SQLite candidate persistence and aggregate counts.
- Create `platform_core/storage/zip_import.py`: allowed-root ZIP resolution, Zip Slip/Zip Bomb validation, disk checks, task staging, and atomic directory publication.
- Modify `platform_core/storage/local.py`: memory-stable one-pass local traversal capability.
- Modify `platform_core/material_repository.py`: SHA index and chunked content-hash lookup.
- Modify `platform_core/task_runtime/repository.py`: guarded `AWAITING_CONFIRMATION -> QUEUED` transition.
- Modify `platform_core/storage/import_tasks.py`: directory/ZIP phases, candidate batches, checkpoints, confirmation-driven indexing.
- Modify `app.py`: request contracts, public live counters, asynchronous confirmation API, import-root discovery.
- Create `static/modules/server-material-import.js`: request builders, task-state presentation, truthful polling state.
- Modify `static/main.mjs`: expose and install the new import runtime.
- Modify `static/app.js`: three import modes and Local-only server controls in the existing modal.
- Modify `static/styles.css`: only the small controls/status rows required by the existing modal.
- Add focused unit, integration, API, frontend, Playwright, and performance tests listed in the tasks below.
- Modify `VERSION.txt`, `static/index.html`, `static/main.mjs`, and `README.md` only after the implementation and regressions pass.

### Task 1: Persist large scan candidate sets outside JSON

**Files:**
- Create: `platform_core/storage/import_candidates.py`
- Create: `tests/unit/storage/test_import_candidates.py`

- [ ] **Step 1: Write the failing candidate-store tests**

```python
import pytest

from platform_core.storage.import_candidates import ImportCandidateStore


def candidate(key: str, sha: str) -> dict:
    return {
        "object_key": key,
        "filename": key.rsplit("/", 1)[-1],
        "storage_source_id": "local-a",
        "storage_type": "local",
        "content_sha256": sha,
        "size_bytes": 12,
        "etag": "etag",
        "width": 20,
        "height": 10,
        "status": "IMPORTABLE",
        "error": "",
        "selected": 1,
        "indexed": 0,
        "image_id": "",
    }


def test_candidate_store_batches_and_recovery_are_idempotent(tmp_path):
    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    rows = [candidate("a.jpg", "a" * 64), candidate("b.jpg", "b" * 64)]
    assert store.upsert_many(rows) == 2
    assert store.upsert_many(rows) == 0
    assert store.counts() == {"IMPORTABLE": 2}
    assert [row["object_key"] for row in store.iter_status("IMPORTABLE", batch_size=1)] == ["a.jpg", "b.jpg"]


def test_candidate_store_keeps_failures_without_exposing_unbounded_arrays(tmp_path):
    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    store.upsert_many([{
        **candidate("broken.jpg", ""),
        "status": "FAILED",
        "error": "cannot identify image",
    }])
    assert store.counts() == {"FAILED": 1}
    assert store.failure_page(limit=10)[0]["object_key"] == "broken.jpg"


def test_candidate_confirmation_and_image_ids_are_atomic_and_idempotent(tmp_path):
    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    store.upsert_many([candidate("a.jpg", "a" * 64), candidate("b.jpg", "b" * 64)])
    first = store.confirm(["a.jpg"])
    assert store.confirm(["a.jpg"]).digest == first.digest
    with pytest.raises(ValueError, match="conflicting"):
        store.confirm(["b.jpg"])
    store.assign_image_ids("task-1", batch_size=1)
    before = store.pending_index_batch(limit=10)
    store.assign_image_ids("task-1", batch_size=1)
    after = store.pending_index_batch(limit=10)
    assert [row["image_id"] for row in before] == [row["image_id"] for row in after]
    assert len(before) == 1 and before[0]["object_key"] == "a.jpg"
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m pytest tests/unit/storage/test_import_candidates.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: platform_core.storage.import_candidates`.

- [ ] **Step 3: Implement the candidate store**

Create a store with this public contract:

```python
class ImportCandidateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def upsert_many(self, rows: Iterable[Mapping[str, object]]) -> int:
        values = [normalize_candidate(row) for row in rows]
        if not values:
            return 0
        with self._connect() as db:
            before = db.total_changes
            db.executemany(
                """
                INSERT OR IGNORE INTO candidates
                    (object_key, filename, content_sha256, size_bytes, etag,
                     width, height, status, error)
                VALUES (:object_key, :filename, :content_sha256, :size_bytes,
                        :etag, :width, :height, :status, :error)
                """,
                values,
            )
            return db.total_changes - before

    def counts(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM candidates GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def iter_status(self, status: str, batch_size: int = 500):
        last_key = ""
        while True:
            with self._connect() as db:
                rows = db.execute(
                    """SELECT * FROM candidates
                       WHERE status=? AND object_key>?
                       ORDER BY object_key LIMIT ?""",
                    (str(status), last_key, max(1, min(5000, int(batch_size)))),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                last_key = str(row["object_key"])
                yield dict(row)

    def failure_page(self, limit: int = 200) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM candidates WHERE status='FAILED' ORDER BY object_key LIMIT ?",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [dict(row) for row in rows]
```

Use `object_key TEXT PRIMARY KEY`, columns for `storage_source_id`, `storage_type`, `duplicate`, `selected`, `indexed`, `image_id`, and `indexed_at`, plus indexes on `(status, object_key)`, `(selected, indexed, object_key)`, and `content_sha256`. Add atomic methods `find_content_hashes(hashes)`, `confirm(selected_keys)`, `assign_image_ids(task_id, batch_size)`, `mark_indexed(rows)`, and `pending_index_batch(limit)`. `find_content_hashes()` uses the same 500-value chunking rule and lets a later path with the same hash be recorded as `DUPLICATE`. `confirm()` stores one selection digest in the SQLite meta table, returns the same digest for identical repeated confirmation, and raises `ValueError` for a conflicting second selection. `assign_image_ids()` persists deterministic UUID5 IDs before any material insert. `normalize_candidate()` must coerce scalar values, reject empty object keys, and never store provider secrets or absolute local roots.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/unit/storage/test_import_candidates.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add platform_core/storage/import_candidates.py tests/unit/storage/test_import_candidates.py
git commit -m "feat: persist storage import candidates"
```

### Task 2: Add set-based SHA256 duplicate lookup

**Files:**
- Modify: `platform_core/material_repository.py`
- Modify: `tests/unit/test_material_repository.py`

- [ ] **Step 1: Write failing repository tests**

```python
def test_find_existing_content_hashes_is_chunked_and_ignores_blank(tmp_path):
    repository = MaterialRepository(tmp_path / "project")
    rows = []
    for index in range(1201):
        digest = f"{index:064x}"
        rows.append({
            "id": f"image-{index}", "filename": f"{index}.jpg",
            "object_key": f"uploads/{index}.jpg", "content_sha256": digest,
        })
    repository.upsert_many(rows)
    requested = ["", *[f"{index:064x}" for index in range(1300)]]
    found = repository.find_existing_content_hashes(requested)
    assert len(found) == 1201
    assert "" not in found
```

- [ ] **Step 2: Verify the API is absent**

Run: `python -m pytest tests/unit/test_material_repository.py::test_find_existing_content_hashes_is_chunked_and_ignores_blank -q`

Expected: FAIL with `AttributeError: 'MaterialRepository' object has no attribute 'find_existing_content_hashes'`.

- [ ] **Step 3: Add the SHA index and chunked lookup**

Add to `_SCHEMA`:

```sql
CREATE INDEX IF NOT EXISTS ix_materials_content_sha256
    ON materials(content_sha256) WHERE content_sha256 <> '';
```

Add this method, preserving the existing 500-parameter policy:

```python
def find_existing_content_hashes(self, hashes: Iterable[str]) -> set[str]:
    normalized = list(dict.fromkeys(
        str(value or "").strip().lower() for value in hashes
        if str(value or "").strip()
    ))
    found: set[str] = set()
    with self._connect() as database:
        for start in range(0, len(normalized), 500):
            chunk = normalized[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = database.execute(
                f"SELECT DISTINCT content_sha256 FROM materials "
                f"WHERE content_sha256 IN ({placeholders})",
                chunk,
            ).fetchall()
            found.update(str(row[0]) for row in rows)
    return found
```

- [ ] **Step 4: Run repository unit and scale tests**

Run: `python -m pytest tests/unit/test_material_repository.py tests/performance/test_material_repository_scale.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_core/material_repository.py tests/unit/test_material_repository.py
git commit -m "perf: add chunked material hash lookup"
```

### Task 3: Stream Local Provider traversal in one pass

**Files:**
- Modify: `platform_core/storage/local.py`
- Modify: `tests/unit/storage/test_local_provider.py`
- Create: `tests/performance/test_local_storage_scan_scale.py`

- [ ] **Step 1: Add failing traversal tests**

```python
def test_local_provider_iter_objects_is_recursive_stable_and_bounded(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    for key in ("z.jpg", "a/2.jpg", "a/1.jpg", "a/deep/3.jpg", "skip.txt"):
        provider.upload(key, BytesIO(key.encode()))
    keys = [item.key for item in provider.iter_objects("a", recursive=True)]
    assert keys == ["a/1.jpg", "a/2.jpg", "a/deep/3.jpg"]
    shallow = [item.key for item in provider.iter_objects("a", recursive=False)]
    assert shallow == ["a/1.jpg", "a/2.jpg"]


def test_local_provider_iter_objects_rejects_prefix_escape(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    with pytest.raises(StorageError) as captured:
        list(provider.iter_objects("../outside", recursive=True))
    assert captured.value.code == "STORAGE_INVALID_OBJECT_KEY"
```

The scale test creates 10,001 empty image-named files under `tmp_path`, consumes the iterator once, asserts the count, and uses `tracemalloc` to require peak Python allocation below 64 MiB.

- [ ] **Step 2: Run and verify the missing iterator failure**

Run: `python -m pytest tests/unit/storage/test_local_provider.py tests/performance/test_local_storage_scan_scale.py -q`

Expected: FAIL because `iter_objects` does not exist.

- [ ] **Step 3: Implement deterministic streaming traversal**

Add a metadata helper that accepts a known path so traversal does not resolve and hash the same key through `stat()` twice:

```python
def _metadata(self, path: Path) -> ObjectMetadata:
    relative = path.relative_to(self.root).as_posix()
    stat = path.stat()
    return ObjectMetadata(
        key=relative,
        size_bytes=stat.st_size,
        etag=f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
        content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        sha256=_sha256(path),
        last_modified=str(stat.st_mtime_ns),
    )

def iter_objects(self, prefix: str = "", *, recursive: bool = True):
    base = self._path(prefix, allow_empty=True)
    if not base.exists():
        return
    if base.is_file():
        yield self._metadata(base)
        return
    if not recursive:
        for path in sorted(base.iterdir(), key=lambda value: value.name):
            if path.is_file() and not path.is_symlink():
                yield self._metadata(path)
        return
    for current, directories, files in os.walk(base, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if not (Path(current) / name).is_symlink()
            and not (Path(current) == self.root and name == ".import-staging")
        )
        for name in sorted(files):
            path = Path(current) / name
            if path.is_file() and not path.is_symlink():
                yield self._metadata(path)
```

Make `stat()` delegate to `_metadata(path)`. Do not remove or change the existing `list_objects()` public contract in this task.

- [ ] **Step 4: Run local-provider and scale tests**

Run: `python -m pytest tests/unit/storage/test_local_provider.py tests/performance/test_local_storage_scan_scale.py -q`

Expected: all tests PASS; the scale test prints count, elapsed seconds, and peak memory under `-s`.

- [ ] **Step 5: Commit**

```bash
git add platform_core/storage/local.py tests/unit/storage/test_local_provider.py tests/performance/test_local_storage_scan_scale.py
git commit -m "perf: stream server-local material scans"
```

### Task 4: Build a secure server ZIP extractor

**Files:**
- Create: `platform_core/storage/zip_import.py`
- Create: `tests/unit/storage/test_zip_import.py`

- [ ] **Step 1: Write failing security and extraction tests**

```python
import stat
import zipfile

import pytest

from platform_core.storage.zip_import import (
    ArchiveLimitExceeded,
    InsufficientDiskSpace,
    TargetDirectoryExists,
    UnsafeArchive,
    extract_server_zip,
    resolve_server_zip,
)


@pytest.mark.parametrize("name", ["../escape.jpg", "/abs.jpg", "C:/drive.jpg", r"..\escape.jpg"])
def test_server_zip_rejects_escape_names(tmp_path, name):
    archive = tmp_path / "imports" / "bad.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, b"image")
    with pytest.raises(UnsafeArchive):
        extract_server_zip(archive, tmp_path / "datasets", "fire", task_id="task-1")


def test_server_zip_rejects_symlink_members(tmp_path):
    archive = tmp_path / "bad-link.zip"
    info = zipfile.ZipInfo("link.jpg")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(info, "../../etc/passwd")
    with pytest.raises(UnsafeArchive):
        extract_server_zip(archive, tmp_path / "datasets", "fire", task_id="task-1")


def test_server_zip_rejects_existing_nonempty_target_without_touching_it(tmp_path):
    target = tmp_path / "datasets"
    (target / "fire").mkdir(parents=True)
    (target / "fire" / "a.jpg").write_bytes(b"old")
    archive = tmp_path / "new.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("a.jpg", b"new")
    with pytest.raises(TargetDirectoryExists, match="目标目录已存在"):
        extract_server_zip(archive, target, "fire", task_id="task-1")
    assert (target / "fire" / "a.jpg").read_bytes() == b"old"
    assert not (target / ".import-staging" / "task-1").exists()


def test_server_zip_checks_space_before_writing(tmp_path, monkeypatch):
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("a.jpg", b"x" * 4096)
    monkeypatch.setattr("platform_core.storage.zip_import.shutil.disk_usage", lambda _p: (8192, 8192, 1))
    with pytest.raises(InsufficientDiskSpace):
        extract_server_zip(archive, tmp_path / "datasets", "fire", task_id="task-1")
    assert not (tmp_path / "datasets" / "fire" / "a.jpg").exists()


def test_server_zip_extracts_to_staging_then_publishes_once(tmp_path):
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nested/a.jpg", b"image")
    root = tmp_path / "datasets"
    report = extract_server_zip(archive, root, "fire", task_id="task-1")
    assert (root / "fire" / "nested" / "a.jpg").read_bytes() == b"image"
    assert report.published_prefix == "fire"
    assert not (root / ".import-staging" / "task-1").exists()


def test_server_zip_rejects_zip_bomb_limits_before_writing(tmp_path, monkeypatch):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("huge.jpg", b"0" * 8192)
    monkeypatch.setenv("MC_ZIP_MAX_SINGLE_BYTES", "1024")
    with pytest.raises(ArchiveLimitExceeded, match="单文件"):
        extract_server_zip(archive, tmp_path / "datasets", "fire", task_id="task-1")
    assert not (tmp_path / "datasets" / "fire").exists()


def test_resolve_server_zip_stays_inside_allowed_root(tmp_path):
    allowed = tmp_path / "imports"
    allowed.mkdir()
    (allowed / "good.zip").write_bytes(b"PK")
    assert resolve_server_zip(allowed, "good.zip") == (allowed / "good.zip").resolve()
    with pytest.raises(UnsafeArchive):
        resolve_server_zip(allowed, "../secret.zip")
```

Add separate tests for nested directories, corrupted ZIP, duplicate normalized member names, member-count limit, total-size limit, compression-ratio limit, special device entries, actual-byte overflow, mid-extraction disk exhaustion, cancellation cleanup, and recovery publication markers.

- [ ] **Step 2: Run and verify the missing module failure**

Run: `python -m pytest tests/unit/storage/test_zip_import.py -q`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Implement archive validation and disk preflight**

Use `PurePosixPath` and `PureWindowsPath` together:

```python
def safe_member_path(name: str) -> PurePosixPath:
    raw = str(name or "")
    normalized = raw.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(raw)
    if (
        not normalized or "\x00" in normalized or posix.is_absolute()
        or windows.is_absolute() or bool(windows.drive)
        or ".." in posix.parts or ".." in windows.parts
    ):
        raise UnsafeArchive(f"ZIP 包含不安全路径：{raw}")
    return posix

def is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)

def required_disk_bytes(infos: Iterable[zipfile.ZipInfo], margin_ratio: float = 0.15) -> int:
    declared = sum(max(0, int(info.file_size)) for info in infos if not info.is_dir())
    return declared + max(64 * 1024 * 1024, int(declared * margin_ratio))
```

`resolve_server_zip()` and the target resolver must use `Path.resolve()` plus `relative_to()` containment, reject a source file symlink, and require a nonempty target prefix. Read configurable limits from `MC_ZIP_MAX_MEMBERS`, `MC_ZIP_MAX_SINGLE_BYTES`, `MC_ZIP_MAX_TOTAL_BYTES`, `MC_ZIP_MAX_RATIO`, `MC_ZIP_DISK_MARGIN_BYTES`, and `MC_ZIP_DISK_MARGIN_RATIO`. Defaults must permit the documented 100 GB use case while still bounding archive expansion.

All ZIP domain failures derive from `ServerZipImportError` and expose `code`, `message`, `detail`, `solution`, and numeric `context`. Use stable codes including `ZIP_SOURCE_OUTSIDE_IMPORT_ROOT`, `ZIP_INVALID_ARCHIVE`, `ZIP_UNSAFE_MEMBER`, `ZIP_LIMIT_EXCEEDED`, `ZIP_DISK_SPACE_INSUFFICIENT`, `ZIP_TARGET_EXISTS`, and `ZIP_ACTUAL_SIZE_EXCEEDED`.

- [ ] **Step 4: Implement resumable streaming extraction**

The function signature is:

```python
def extract_server_zip(
    archive_path: str | Path,
    target_root: str | Path,
    target_prefix: str,
    *,
    task_id: str,
    completed: Mapping[str, Mapping[str, object]] | None = None,
    on_progress: Callable[[ExtractionProgress], None] | None = None,
) -> ExtractionReport:
```

It must validate all members, Zip Bomb limits, the nonempty target, and disk space before opening the first staging destination. The only write root is:

```text
<target_root>/.import-staging/<task_id>/payload
```

For each regular file, stream 1 MiB chunks into staging `.part-<uuid>.tmp`, update SHA256 and actual byte counters, reject actual bytes beyond the member declaration or task safety ceiling, periodically recheck free disk, `fsync`, and `os.replace` only inside staging. Validate CRC by reading each member to EOF.

After every member is verified, write `.mc-import-owner.json` containing the task ID inside payload. If the formal target exists and is nonempty, raise `TargetDirectoryExists` without modifying it. If it exists and is empty, remove only that empty directory. Publish with `os.replace(payload, target)` on the same filesystem, persist/report the published state, remove the ownership marker, and clean only `.import-staging/<task_id>`. On controlled failure or cancellation, remove only this task staging. On process death, leave it for `recover()`.

- [ ] **Step 5: Run ZIP unit tests**

Run: `python -m pytest tests/unit/storage/test_zip_import.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_core/storage/zip_import.py tests/unit/storage/test_zip_import.py
git commit -m "feat: safely extract server-side material archives"
```

### Task 5: Guarded confirmation requeue in Task Runtime

**Files:**
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `tests/unit/task_runtime/test_repository.py`

- [ ] **Step 1: Write the failing transition test**

```python
def test_resume_after_confirmation_requeues_only_waiting_task(repository):
    task = repository.create(TaskRecord.new(
        "import-1", "project", TaskKind.MATERIAL_IMPORT,
        "request.json", "storage:local",
    ))
    lease = repository.claim_next("worker", (TaskKind.MATERIAL_IMPORT,), {"storage.import"}, 30)
    waiting = repository.finish(
        task.task_id, lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION, "scan/result.json",
    )
    resumed = repository.resume_after_confirmation(task.task_id)
    assert resumed.status is TaskStatus.QUEUED
    assert resumed.stage == "indexing_queued"
    assert resumed.progress == 0
    same = repository.resume_after_confirmation(task.task_id)
    assert same.status is TaskStatus.QUEUED
    assert same.accepted is True
```

Add tests proving an already accepted `QUEUED / indexing_queued`, `RUNNING / indexing`, or terminal `SUCCEEDED` import remains idempotent, while an initial `QUEUED`, unrelated `RUNNING`, rejected task, and `FAILED` task raise `ValueError` instead of being modified.

- [ ] **Step 2: Verify the method is absent**

Run: `python -m pytest tests/unit/task_runtime/test_repository.py::test_resume_after_confirmation_requeues_only_waiting_task -q`

Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement the atomic guarded transition**

```python
def resume_after_confirmation(self, task_id: str) -> TaskRecord:
    now = utc_now()
    with self._connect() as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT * FROM tasks WHERE task_id=?", (str(task_id),)
        ).fetchone()
        if row is None:
            database.rollback()
            raise KeyError(task_id)
        current = _from_row(row)
        if (
            current.accepted is True
            and (
                (current.status is TaskStatus.QUEUED and current.stage == "indexing_queued")
                or (current.status is TaskStatus.RUNNING and current.stage == "indexing")
                or current.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}
            )
        ):
            database.commit()
            return current
        if current.status is not TaskStatus.AWAITING_CONFIRMATION:
            database.rollback()
            raise ValueError("task is not awaiting confirmation")
        database.execute(
            """UPDATE tasks SET status='QUEUED', stage='indexing_queued',
               progress=0, current_item=NULL, error=NULL, accepted=1,
               finished_at=NULL, updated_at=?, worker_id=NULL,
               lease_token=NULL, lease_expires_at=NULL WHERE task_id=?""",
            (now, str(task_id)),
        )
        database.commit()
    result = self.get(task_id)
    if result is None:
        raise KeyError(task_id)
    return result
```

- [ ] **Step 4: Run Task Runtime tests**

Run: `python -m pytest tests/unit/task_runtime -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_core/task_runtime/repository.py tests/unit/task_runtime/test_repository.py
git commit -m "feat: resume confirmed durable import tasks"
```

### Task 6: Make directory imports scalable and confirmation-driven

**Files:**
- Modify: `platform_core/storage/import_tasks.py`
- Modify: `tests/integration/test_storage_import_worker.py`

- [ ] **Step 1: Rewrite integration expectations as failing tests**

Change the first scan test to require `TaskStatus.AWAITING_CONFIRMATION`, assert that `scan/result.json` has no `candidates` array, and assert that `ImportCandidateStore` contains the two candidates. Add tests for content-SHA duplicate detection, damaged images, prefix scanning, and recovery from an existing candidate DB.

Core assertion:

```python
completed = repository.get(task.task_id)
assert completed.status is TaskStatus.AWAITING_CONFIRMATION
result = artifacts.read_json(task.task_id, completed.result_ref)
assert "candidates" not in result
assert result["importable_images"] == 2
candidate_db = artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3")
assert ImportCandidateStore(candidate_db).counts() == {"IMPORTABLE": 2, "SKIPPED": 1}
```

- [ ] **Step 2: Run the integration tests and observe old behavior**

Run: `python -m pytest tests/integration/test_storage_import_worker.py -q`

Expected: FAIL because the old handler returns `SUCCEEDED` and stores candidates in JSON.

- [ ] **Step 3: Add provider-capability iteration and batched candidate writes**

Use a capability helper instead of storage-type branching:

```python
def iter_provider_objects(provider, prefix: str, recursive: bool):
    streaming = getattr(provider, "iter_objects", None)
    if callable(streaming):
        yield from streaming(prefix, recursive=recursive)
        return
    cursor = None
    while True:
        page = provider.list_objects(prefix, recursive=recursive, cursor=cursor, limit=500)
        yield from page.items
        if not page.next_cursor:
            return
        cursor = page.next_cursor
```

Accumulate no more than 500 normalized candidate records before `ImportCandidateStore.upsert_many()`. Query material SHA duplicates once per batch with `find_existing_content_hashes()`, query hashes already seen in the candidate store once per batch with `find_content_hashes()`, and maintain a batch-local set. The first object for one SHA is `IMPORTABLE`; every later object with the same SHA is persisted as `DUPLICATE` so counts remain auditable.

Write `scan/result.json` as aggregate data only:

```python
result = {
    "mode": mode,
    "storage_source_id": source.id,
    "prefix": prefix,
    "recursive": recursive,
    "scanned_files": scanned,
    "importable_images": counts.get("IMPORTABLE", 0),
    "duplicates": counts.get("DUPLICATE", 0),
    "invalid_images": counts.get("INVALID", 0),
    "skipped_files": counts.get("SKIPPED", 0),
    "failed": counts.get("FAILED", 0),
    "scanned": scanned,
    "importable": counts.get("IMPORTABLE", 0),
    "manifest_ref": "scan/candidates.sqlite3",
    "failure_examples": store.failure_page(limit=200),
}
```

Return `TaskStatus.AWAITING_CONFIRMATION` and `scan/result.json`.

- [ ] **Step 4: Replace synchronous commit with worker indexing**

Add `_index_confirmed(context, request, store)` that reads the candidate-store confirmation state, calls `assign_image_ids(task_id, batch_size=500)` before any material insert, iterates selected/unindexed rows in batches of 500, rechecks storage reference and SHA duplicates in set-based queries, writes `MaterialRepository.upsert_many()`, marks those exact candidate rows indexed, and checkpoints aggregate counts after every batch. It returns `SUCCEEDED` with `scan/final.json` only when candidate, indexed, duplicate, skipped, and failed counts reconcile.

Use this dispatch at the top of `run()` and `recover()`:

```python
confirmation = context.artifacts.read_json(
    context.task.task_id, "scan/confirmation.json", default=None
)
if isinstance(confirmation, dict) and confirmation.get("accepted") is True:
    return self._index_confirmed(context, request)
return self._scan(context, request)
```

The generated material rows must retain stable logical `stored_name` while omitting any physical project-upload copy.

Add `load_legacy_candidates()` for historical tasks whose `scan/result.json` contains a small `candidates` array. On first confirmation/index recovery, import those rows into `scan/candidates.sqlite3` once and continue through the new batch pipeline. New scans must never write the legacy array.

- [ ] **Step 5: Run import-worker and repository tests**

Run: `python -m pytest tests/integration/test_storage_import_worker.py tests/unit/test_material_repository.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_core/storage/import_tasks.py tests/integration/test_storage_import_worker.py
git commit -m "feat: make local storage scans durable and scalable"
```

### Task 7: Add durable server ZIP mode and recovery

**Files:**
- Modify: `platform_core/storage/import_tasks.py`
- Create: `tests/integration/test_server_zip_import_worker.py`

- [ ] **Step 1: Write failing ZIP worker tests**

Create real JPEG bytes with Pillow and real ZIP archives. Tests must cover normal nested extraction through task staging, non-image skips, existing nonempty target rejection, unsafe archive failure, Zip Bomb limits, damaged ZIP failure, initial and mid-stream disk-space failure, cancellation cleanup, and restart recovery.

Core success test:

```python
def test_server_zip_extracts_scans_waits_and_indexes_without_upload_copy(runtime_fixture):
    env = runtime_fixture
    archive = env.import_dir / "fire.zip"
    write_zip(archive, {
        "images/a.jpg": jpg("red"),
        "images/nested/b.jpg": jpg("blue"),
        "labels/a.txt": b"0 0.5 0.5 0.2 0.2\n",
        "data.yaml": b"names: [fire]\n",
    })
    task = env.create_import({
        "mode": "server_zip", "zip_path": "fire.zip",
        "storage_source_id": env.source_id, "target_prefix": "fire",
        "recursive": True,
    })
    env.run_worker()
    waiting = env.repository.get(task.task_id)
    assert waiting.status is TaskStatus.AWAITING_CONFIRMATION
    result = env.artifacts.read_json(task.task_id, waiting.result_ref)
    assert result["importable_images"] == 2
    assert result["skipped_files"] == 2
    assert not (env.project_dir / "uploads").exists()
    env.confirm_and_run(task.task_id)
    assert env.repository.get(task.task_id).status is TaskStatus.SUCCEEDED
    assert MaterialRepository(env.project_dir).count() == 2
```

Recovery tests cover both crash windows: interrupt after the first staged member, and interrupt immediately after atomic publication but before the published checkpoint. Release the expired lease, run a new scheduler, and assert it validates/reuses completed staging files or the task-owned publication marker, removes stale `.part-*`, never adopts another task's target, and indexes every image exactly once.

- [ ] **Step 2: Run and verify server ZIP mode is unsupported**

Run: `python -m pytest tests/integration/test_server_zip_import_worker.py -q`

Expected: FAIL because `server_zip` mode and its progress/checkpoint fields do not exist.

- [ ] **Step 3: Add ZIP validation/extraction stage**

Resolve the allowed import directory as:

```python
def server_import_dir(data_dir: Path) -> Path:
    configured = os.environ.get("MC_SERVER_IMPORT_DIR", "").strip()
    return (Path(configured).expanduser() if configured else data_dir / "imports").resolve()
```

Require `StorageType.LOCAL`, obtain the physical root only from the provider, require a nonempty target prefix, and call `extract_server_zip(..., task_id=context.task.task_id)` with a callback that writes real checkpoint fields and heartbeats:

```python
def on_extract(progress):
    checkpoint.update({
        "stage": "extracting",
        "extracted_files": progress.files,
        "extracted_bytes": progress.bytes,
        "declared_bytes": progress.declared_bytes,
        "current_file": progress.current_file,
    })
    context.save_checkpoint(checkpoint)
    context.repository.heartbeat(
        context.task.task_id, context.lease.lease_token,
        progress=progress.percent,
        stage="extracting",
        current_item=(
            f"已解压 {progress.files} 个文件 · {progress.bytes} 字节 · "
            f"当前 {progress.current_file}"
        ),
    )
```

After extraction, scan exactly the resolved target prefix through the same candidate pipeline from Task 6.

- [ ] **Step 4: Add recovery semantics**

Persist completed member metadata under `checkpoints/worker.json`. `recover()` must validate completed staging files by size/SHA before treating them as done. If the target contains the matching task ownership marker, recover the just-published directory and finalize its checkpoint; a nonempty target without that marker fails. If confirmation exists, go directly to indexing; if publication completed, resume scanning; otherwise resume extraction. Controlled failure/cancellation cleans only `<root>/.import-staging/<task_id>`.

Catch `ServerZipImportError` inside the handler, write its structured public fields plus live counters to `scan/error.json`, and return `(TaskStatus.FAILED, "scan/error.json")`. The public API and UI read `result.error` so error code, free bytes, required bytes, written bytes, and solution remain visible instead of being reduced to a generic exception string.

- [ ] **Step 5: Run ZIP worker and security tests**

Run: `python -m pytest tests/unit/storage/test_zip_import.py tests/integration/test_server_zip_import_worker.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_core/storage/import_tasks.py tests/integration/test_server_zip_import_worker.py
git commit -m "feat: add durable server zip material imports"
```

### Task 8: Expose truthful asynchronous import APIs

**Files:**
- Modify: `app.py`
- Modify: `tests/api/test_storage_upload.py`
- Create: `tests/api/test_server_material_import.py`

- [ ] **Step 1: Write failing API contract tests**

```python
def test_server_zip_api_accepts_relative_allowed_path_and_local_target(client, project, local_source, tmp_path, monkeypatch):
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    write_image_zip(import_dir / "fire.zip")
    monkeypatch.setenv("MC_SERVER_IMPORT_DIR", str(import_dir))
    response = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={
            "mode": "server_zip", "zip_path": "fire.zip",
            "storage_source_id": local_source["id"], "target_prefix": "fire",
            "recursive": True,
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"


def test_server_zip_api_rejects_non_local_target(client, project, s3_source):
    response = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={
            "mode": "server_zip", "zip_path": "fire.zip",
            "storage_source_id": s3_source["id"], "target_prefix": "fire",
        },
    )
    assert response.status_code == 422
    assert "本地存储" in response.text


def test_confirm_requeues_same_task_instead_of_indexing_in_http_thread(client, waiting_import_task):
    response = client.post(
        f"/api/v61/projects/{waiting_import_task.project_id}/storage-imports/"
        f"{waiting_import_task.task_id}/confirm",
        json={},
    )
    assert response.status_code == 202
    assert response.json()["task_id"] == waiting_import_task.task_id
    assert response.json()["status"] == "QUEUED"
    assert response.json()["stage"] == "indexing_queued"
```

Add rejection tests for paths outside `MC_SERVER_IMPORT_DIR`, disabled sources, unknown modes, and confirmation before scanning completes.

- [ ] **Step 2: Run API tests and verify contract failures**

Run: `python -m pytest tests/api/test_storage_upload.py tests/api/test_server_material_import.py -q`

Expected: FAIL because the Pydantic request has no mode/ZIP fields and confirmation requires `SUCCEEDED`.

- [ ] **Step 3: Extend request validation**

Use a model validator so invalid combinations fail before task creation:

```python
class StorageImportScanReq(BaseModel):
    mode: Literal["storage_scan", "directory_scan", "server_zip"] = "storage_scan"
    storage_source_id: str
    prefix: str = ""
    recursive: bool = True
    zip_path: Optional[str] = None
    target_prefix: str = ""

    @model_validator(mode="after")
    def validate_mode_fields(self):
        if self.mode == "server_zip" and not str(self.zip_path or "").strip():
            raise ValueError("服务器 ZIP 模式必须选择 ZIP 文件")
        if self.mode != "server_zip" and self.zip_path:
            raise ValueError("目录扫描不能提交 ZIP 文件")
        return self
```

The route must verify source existence/enabled state and require `source.type == "local"` only for `directory_scan` and `server_zip`. A request without `mode` remains `storage_scan` and must continue to support Local, OSS, S3/MinIO, and Remote providers. Store only relative ZIP path in `request.json`.

- [ ] **Step 4: Return live real counters and asynchronous confirmation**

Read the task checkpoint in `_public_storage_import_task()` and expose a bounded `metrics` mapping containing numeric counters and current file, without absolute roots or secrets.

Confirmation writes:

```python
candidate_store = ImportCandidateStore(
    shared_task_artifacts().artifact_path(task_id, "scan/candidates.sqlite3")
)
selection = candidate_store.confirm(payload.object_keys)
shared_task_artifacts().atomic_write_json(
    task_id, "scan/confirmation.json",
    {
        "accepted": True,
        "selection_digest": selection.digest,
        "selected_count": selection.selected_count,
        "confirmed_at": selection.confirmed_at,
    },
)
updated = shared_task_repository().resume_after_confirmation(task_id)
return JSONResponse(status_code=202, content=_public_storage_import_task(updated))
```

Do not store a 100k-key selection array in JSON. `ImportCandidateStore.confirm()` applies selected flags and the selection digest in one SQLite transaction. Require `TaskStatus.AWAITING_CONFIRMATION` for the first confirmation. On an identical repeat, return the queued/running/completed task; reject conflicting selection digests. `app.py` must not update the task table directly and must not call `complete_review()`.

- [ ] **Step 5: Run focused API and import integration tests**

Run: `python -m pytest tests/api/test_storage_upload.py tests/api/test_server_material_import.py tests/integration/test_storage_import_worker.py tests/integration/test_server_zip_import_worker.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/api/test_storage_upload.py tests/api/test_server_material_import.py
git commit -m "feat: expose durable server material import api"
```

### Task 9: Add truthful frontend task presentation

**Files:**
- Create: `static/modules/server-material-import.js`
- Create: `tests/frontend/server-material-import.test.mjs`
- Modify: `static/main.mjs`

- [ ] **Step 1: Write failing Node tests**

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildServerImportRequest,
  serverImportView,
} from '../../static/modules/server-material-import.js';

test('directory request contains only source-relative fields', () => {
  assert.deepEqual(buildServerImportRequest({
    mode: 'directory_scan', storageSourceId: 'local-a', prefix: 'fire/2026', recursive: true,
  }), {
    mode: 'directory_scan', storage_source_id: 'local-a', prefix: 'fire/2026', recursive: true,
  });
});

test('zip request never turns the archive into a browser upload', () => {
  assert.deepEqual(buildServerImportRequest({
    mode: 'server_zip', storageSourceId: 'local-a', zipPath: 'fire.zip', targetPrefix: 'fire',
  }), {
    mode: 'server_zip', storage_source_id: 'local-a', zip_path: 'fire.zip', target_prefix: 'fire', recursive: true,
  });
});

test('unknown-total scan view contains real counters and no fabricated percent', () => {
  const view = serverImportView({
    status: 'RUNNING', stage: 'scanning', progress: 58,
    metrics: {scanned_files: 15420, importable_images: 14886, duplicates: 522, failed: 12},
    current_item: 'fire/a.jpg',
  });
  assert.match(view.text, /已扫描 15420/);
  assert.equal(view.showPercent, false);
  assert.equal(view.text.includes('58%'), false);
});

test('awaiting confirmation and indexing are distinct actions', () => {
  assert.equal(serverImportView({status: 'AWAITING_CONFIRMATION'}).canConfirm, true);
  assert.equal(serverImportView({status: 'RUNNING', stage: 'indexing'}).canConfirm, false);
});
```

- [ ] **Step 2: Verify the new module is absent**

Run: `node --test tests/frontend/server-material-import.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 3: Implement pure request/view helpers**

```javascript
export function buildServerImportRequest(values = {}) {
  const mode = String(values.mode || 'directory_scan');
  const source = String(values.storageSourceId || '').trim();
  if (!source) throw new Error('请选择本地存储源');
  if (mode === 'directory_scan') return {
    mode, storage_source_id: source,
    prefix: String(values.prefix || '').trim(),
    recursive: values.recursive !== false,
  };
  if (mode === 'server_zip') {
    const zipPath = String(values.zipPath || '').trim();
    if (!zipPath) throw new Error('请选择服务器 ZIP');
    return {
      mode, storage_source_id: source, zip_path: zipPath,
      target_prefix: String(values.targetPrefix || '').trim(), recursive: true,
    };
  }
  throw new Error(`不支持的导入方式：${mode}`);
}

export function serverImportView(task = {}) {
  const status = String(task.status || 'QUEUED').toUpperCase();
  const stage = String(task.stage || '').toLowerCase();
  const metrics = task.metrics || {};
  const text = stage === 'extracting'
    ? `已解压 ${Number(metrics.extracted_files || 0)} 个文件 · ${Number(metrics.extracted_bytes || 0)} 字节 · 当前 ${task.current_item || '-'}`
    : stage === 'scanning'
      ? `已扫描 ${Number(metrics.scanned_files || 0)} · 可导入 ${Number(metrics.importable_images || 0)} · 重复 ${Number(metrics.duplicates || 0)} · 失败 ${Number(metrics.failed || 0)} · 当前 ${task.current_item || '-'}`
      : stage === 'indexing'
        ? `正在建立索引 ${Number(metrics.indexed || 0)} / ${Number(metrics.selected || 0)}`
        : status === 'QUEUED' ? '任务已进入 Storage Worker 队列' : stage || status;
  return {
    status, stage, text,
    active: ['QUEUED', 'RUNNING'].includes(status),
    canConfirm: status === 'AWAITING_CONFIRMATION',
    showPercent: stage === 'extracting' && Number(metrics.declared_bytes || 0) > 0,
    terminal: ['SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED', 'BLOCKED_BY_ENVIRONMENT'].includes(status),
  };
}
```

- [ ] **Step 4: Export helpers through `PlatformCore`**

Import the new module in `static/main.mjs`, expose it as `PlatformCore.serverMaterialImport`, and leave installation to Task 10 after legacy globals exist.

- [ ] **Step 5: Run all frontend unit tests**

Run: `node --test tests/frontend/*.test.mjs`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add static/modules/server-material-import.js tests/frontend/server-material-import.test.mjs static/main.mjs
git commit -m "feat: model truthful server import ui states"
```

### Task 10: Integrate three import modes into the existing modal

**Files:**
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Modify: `static/main.mjs`
- Modify: `tests/frontend/storage-source-ui.test.mjs`
- Modify: `tests/frontend/storage-import-progress.test.mjs`
- Create: `tests/playwright/server-material-import.spec.js`

- [ ] **Step 1: Add failing source and browser-flow tests**

Extend the frontend source test to require all three labels and Local filtering:

```javascript
assert.match(block, /浏览器上传/);
assert.match(block, /服务器本地目录/);
assert.match(block, /服务器 ZIP/);
assert.match(block, /source\.type===['"]local['"]/);
assert.doesNotMatch(block, /train_dataset_ids|test_dataset_ids/);
```

Playwright creates a Local source, opens “从存储导入素材”, selects directory mode, starts a real scan, closes the modal while it runs, reopens the import view, and verifies the task still reaches waiting confirmation. A second flow confirms and waits for `SUCCEEDED` before asserting the material appears.

- [ ] **Step 2: Run and observe missing controls**

Run: `node --test tests/frontend/storage-source-ui.test.mjs tests/frontend/storage-import-progress.test.mjs`

Run: `npx playwright test tests/playwright/server-material-import.spec.js`

Expected: frontend or Playwright assertions FAIL because the modal has one generic scan form.

- [ ] **Step 3: Replace only the existing import-modal renderer**

Keep the existing page and styling. Render three radio/tab buttons and two server panels. Filter server targets with:

```javascript
const localSources = storageApi().enabledStorageSources(state.storageSources61)
  .filter(source => source.type === 'local');
```

Browser upload delegates to the existing `openDataUpload426()`. Directory and ZIP panels use relative inputs, not a server-wide filesystem browser.

- [ ] **Step 4: Install durable polling and confirmation**

Use one `AbortController` per open modal. Closing the modal aborts only fetch polling. It must not call a task cancel endpoint.

```javascript
async function pollServerImport(projectId, taskId, render, signal) {
  while (!signal.aborted) {
    const task = await responseJson(await fetch(
      `/api/v61/projects/${encodeURIComponent(projectId)}/storage-imports/${encodeURIComponent(taskId)}`,
      {signal},
    ));
    render(task);
    const view = serverImportView(task);
    if (!view.active) return task;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, 1200);
      signal.addEventListener('abort', () => { clearTimeout(timer); reject(signal.reason); }, {once: true});
    });
  }
  throw signal.reason || new DOMException('Polling stopped', 'AbortError');
}
```

After confirmation returns `202`, continue polling the same task through indexing to `SUCCEEDED`. Show backend errors verbatim through the existing escaped error renderer.

- [ ] **Step 5: Run frontend and Playwright tests**

Run: `node --test tests/frontend/*.test.mjs`

Expected: all frontend tests PASS.

Run: `npx playwright test tests/playwright/server-material-import.spec.js`

Expected: all new Playwright scenarios PASS.

- [ ] **Step 6: Commit**

```bash
git add static/app.js static/styles.css static/main.mjs tests/frontend/storage-source-ui.test.mjs tests/frontend/storage-import-progress.test.mjs tests/playwright/server-material-import.spec.js
git commit -m "feat: add server material import workflow ui"
```

### Task 11: Verify the indexed Local material lifecycle end to end

**Files:**
- Create: `tests/integration/test_server_local_material_flow.py`
- Modify: `tests/api/test_material_storage_deletion.py`

- [ ] **Step 1: Add real lifecycle tests**

Build one Local source outside the project directory and import JPEGs through the durable scan/confirm flow. The test then performs real API calls for content preview and annotation save/read, calls `StorageManager.materialize()`, builds a training snapshot with exact `train_image_ids`, and verifies deletion semantics.

Core invariants:

```python
assert source_file.is_file()
assert not (project_dir / "uploads").exists()
assert client.get(material["url"]).content == source_file.read_bytes()
assert client.put(annotation_url, json={"boxes": boxes}).status_code == 200
assert client.get(annotation_url).json()["boxes"] == boxes
resolved = manager.materialize(material)
assert resolved.path.read_bytes() == source_file.read_bytes()
assert snapshot["images"][0]["image_id"] == material["id"]
assert snapshot["images"][0]["content_sha256"] == material["content_sha256"]
```

Default index deletion must leave `source_file` present. A separate request with the existing explicit source-delete confirmation token must remove it.

- [ ] **Step 2: Run and expose any cross-chain regression**

Run: `python -m pytest tests/integration/test_server_local_material_flow.py tests/api/test_material_storage_deletion.py -q`

Expected: tests PASS if all existing consumers already use `StorageManager`; any failure must be fixed only in the responsible existing consumer and covered by its focused test.

- [ ] **Step 3: Run training-worker mixed-source regression**

Run: `python -m pytest tests/integration/test_training_task_worker.py tests/integration/test_remote_training_manifest.py tests/e2e/test_real_durable_training.py -q`

Expected: all tests PASS and the submitted training contract contains only `train_image_ids` and `test_image_ids`.

- [ ] **Step 4: Commit lifecycle coverage**

```bash
git add tests/integration/test_server_local_material_flow.py tests/api/test_material_storage_deletion.py
git commit -m "test: cover server-local material lifecycle"
```

### Task 12: Scale, full regression, version, and release evidence

**Files:**
- Modify: `VERSION.txt`
- Modify: `static/index.html`
- Modify: `static/main.mjs`
- Modify: `README.md`
- Modify: `docs/codex-handoff.md`

- [ ] **Step 1: Run the 10k scan benchmark with evidence**

Run: `python -m pytest tests/performance/test_local_storage_scan_scale.py -q -s`

Expected: PASS with at least 10,001 files, elapsed time, and peak allocation printed; no project `uploads` directory exists.

- [ ] **Step 2: Attempt the 100k benchmark**

Run: `$env:MC_RUN_100K_STORAGE_TEST='1'; python -m pytest tests/performance/test_local_storage_scan_scale.py -q -s`

Expected: PASS when the host has sufficient time/disk. Record exact elapsed time, peak memory, candidate/material row counts, and duplicate-copy count. If the environment cannot complete it, retain the skip/failure evidence and report it as not verified.

- [ ] **Step 3: Run all backend tests**

Run: `python -m pytest -q`

Expected: record exact `passed`, `failed`, and `skipped`; do not proceed to release metadata with failures.

- [ ] **Step 4: Run all frontend tests**

Run: `node --test tests/frontend/*.test.mjs`

Expected: record exact pass/fail totals.

- [ ] **Step 5: Run all Playwright tests**

Run: `npx playwright test`

Expected: record exact pass/fail/skip totals.

- [ ] **Step 6: Perform a real Windows startup smoke test**

Start the platform with the documented Windows launcher, verify `/api/health`, create a Local source under a temporary external directory, execute directory scan and ZIP import through the browser, confirm both, refresh the page, and verify the indexed images still preview. Stop only the processes started by this test.

Expected: API, Worker, database, task states, and browser agree; no indexed source image is copied into project uploads.

- [ ] **Step 7: Update release metadata to 42.23.0**

Set `VERSION.txt`, `static/index.html`, static cache query strings, `static/main.mjs` badge text, README current-version text, and `docs/codex-handoff.md` to `42.23.0`. Document server directory/ZIP behavior, security boundary, `MC_SERVER_IMPORT_DIR`, and the explicit non-support of server-ZIP YOLO txt annotations.

- [ ] **Step 8: Verify version consistency**

Run: `rg -n "42\.22\.4|422204" VERSION.txt README.md static docs/codex-handoff.md`

Expected: no stale runtime/cache version references remain in the changed release surfaces.

- [ ] **Step 9: Commit release metadata**

```bash
git add VERSION.txt README.md docs/codex-handoff.md static/index.html static/main.mjs
git commit -m "chore: release server material imports v42.23.0"
```

- [ ] **Step 10: Run final verification after the last commit**

Run: `python -m pytest -q`

Run: `node --test tests/frontend/*.test.mjs`

Run: `npx playwright test`

Run: `git status --short --branch`

Expected: exact test totals are recorded and the worktree is clean on `feat/windows-p0`.

- [ ] **Step 11: Push only the feature branch and verify remote parity**

```bash
git push origin feat/windows-p0
git rev-parse HEAD
git rev-parse origin/feat/windows-p0
```

Expected: both SHAs are identical. Do not checkout, modify, merge, or push `main`.
