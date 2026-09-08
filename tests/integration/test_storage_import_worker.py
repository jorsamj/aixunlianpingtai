from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from platform_core.material_repository import MaterialRepository
from platform_core.storage import LocalStorageProvider, StorageSourceRepository
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_tasks import StorageImportHandler, commit_storage_import
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus


def jpg(color):
    stream = BytesIO()
    Image.new("RGB", (32, 24), color).save(stream, format="JPEG")
    return stream.getvalue()


def runtime(tmp_path, files, *, prefix="incoming"):
    data = tmp_path / "data"
    project_id = "p1"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    (project / "meta.json").write_text('{"labels": []}', encoding="utf-8")
    external = tmp_path / "external"
    provider = LocalStorageProvider("external-a", external)
    for key, content in files.items():
        provider.upload(key, BytesIO(content))
    sources = StorageSourceRepository(data / "storage" / "storage_sources.sqlite3")
    sources.create({
        "id": "external-a", "name": "external", "type": "local",
        "config": {"root": str(external)},
    })
    task_root = data / "task_runtime"
    repository = TaskRepository(task_root / "tasks.sqlite3")
    artifacts = ArtifactStore(task_root / "artifacts")
    task = TaskRecord.new(
        "scan-1", project_id, TaskKind.MATERIAL_IMPORT,
        "request.json", "storage:external-a",
    )
    artifacts.atomic_write_json(task.task_id, task.payload_ref, {
        "storage_source_id": "external-a", "prefix": prefix, "recursive": True,
    })
    repository.create(task)
    scheduler = Scheduler(
        repository, artifacts, "worker",
        {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)}, {"storage.import"},
    )
    return data, project, provider, repository, artifacts, task, scheduler


def confirm_all(repository, artifacts, task_id):
    store = ImportCandidateStore(artifacts.artifact_path(task_id, "scan/candidates.sqlite3"))
    keys = [row["object_key"] for row in store.iter_status("IMPORTABLE")]
    selection = store.confirm(keys)
    artifacts.atomic_write_json(task_id, "scan/confirmation.json", {
        "accepted": True,
        "selection_digest": selection.digest,
        "selected_count": selection.selected_count,
        "confirmed_at": selection.confirmed_at,
    })
    repository.resume_after_confirmation(task_id)


def test_existing_source_scan_waits_then_indexes_without_copying(tmp_path):
    env = runtime(tmp_path, {
        "incoming/a.jpg": jpg("red"),
        "incoming/b.png": jpg("blue"),
        "incoming/readme.txt": b"not an image",
    })
    data, project, provider, repository, artifacts, task, scheduler = env

    assert scheduler.run_once() is True
    waiting = repository.get(task.task_id)
    assert waiting.status is TaskStatus.AWAITING_CONFIRMATION
    result = artifacts.read_json(task.task_id, waiting.result_ref)
    assert "candidates" not in result
    assert result["scanned_files"] == 3
    assert result["importable_images"] == 2
    assert result["skipped_files"] == 1
    assert result["stage"] == "awaiting_confirmation"
    assert result["manifest_ref"] == "scan/candidates.sqlite3"
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, result["manifest_ref"]))
    assert store.counts() == {"IMPORTABLE": 2, "SKIPPED": 1}

    confirm_all(repository, artifacts, task.task_id)
    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    final = artifacts.read_json(task.task_id, completed.result_ref)
    assert final["selected"] == final["indexed"] == 2
    assert final["failed"] == 0
    materials = MaterialRepository(project)
    rows = materials.read().rows
    assert materials.count() == 2
    assert {row["storage_source_id"] for row in rows} == {"external-a"}
    assert all(row["stored_name"] for row in rows)
    assert not (project / "uploads").exists()
    assert not (data / "cache" / "materials").exists()
    assert provider.exists("incoming/a.jpg")
    assert provider.exists("incoming/b.png")


def test_scan_deduplicates_by_sha_and_records_damaged_images(tmp_path):
    same = jpg("white")
    env = runtime(tmp_path, {
        "incoming/first.jpg": same,
        "incoming/copy.jpg": same,
        "incoming/broken.jpg": b"not a jpeg",
        "outside/ignored.jpg": jpg("black"),
    })
    _data, _project, _provider, repository, artifacts, task, scheduler = env

    assert scheduler.run_once() is True
    assert repository.get(task.task_id).status is TaskStatus.AWAITING_CONFIRMATION
    result = artifacts.read_json(task.task_id, "scan/result.json")
    assert result["scanned_files"] == 3
    assert result["importable_images"] == 1
    assert result["duplicates"] == 1
    assert result["invalid_images"] == 1
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, result["manifest_ref"]))
    assert store.counts() == {"DUPLICATE": 1, "IMPORTABLE": 1, "INVALID": 1}


def test_scan_uses_material_content_hash_duplicate_detection(tmp_path):
    content = jpg("green")
    env = runtime(tmp_path, {"incoming/new-name.jpg": content})
    _data, project, provider, _repository, artifacts, task, scheduler = env
    metadata = provider.stat("incoming/new-name.jpg")
    MaterialRepository(project).upsert({
        "id": "existing", "filename": "elsewhere.jpg", "stored_name": "existing.jpg",
        "storage_source_id": "other", "storage_type": "local",
        "object_key": "elsewhere.jpg", "content_sha256": metadata.sha256,
        "size_bytes": metadata.size_bytes, "labels": [],
    })

    assert scheduler.run_once() is True
    result = artifacts.read_json(task.task_id, "scan/result.json")
    assert result["importable_images"] == 0
    assert result["duplicates"] == 1


def test_recovery_reuses_existing_candidate_manifest_idempotently(tmp_path):
    env = runtime(tmp_path, {
        "incoming/a.jpg": jpg("red"),
        "incoming/b.jpg": jpg("blue"),
    })
    _data, _project, provider, repository, artifacts, task, scheduler = env
    metadata = provider.stat("incoming/a.jpg")
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3"))
    store.upsert_many([{
        "object_key": metadata.key, "filename": "a.jpg",
        "storage_source_id": "external-a", "storage_type": "local",
        "content_sha256": metadata.sha256, "size_bytes": metadata.size_bytes,
        "etag": metadata.etag, "width": 32, "height": 24,
        "status": "IMPORTABLE", "error": "", "duplicate": False,
    }])
    artifacts.atomic_write_json(task.task_id, "checkpoints/worker.json", {"stage": "SCANNING"})

    assert scheduler.run_once() is True
    assert repository.get(task.task_id).status is TaskStatus.AWAITING_CONFIRMATION
    assert store.counts() == {"IMPORTABLE": 2}
    result = artifacts.read_json(task.task_id, "scan/result.json")
    assert result["importable_images"] == 2


def test_indexing_reuses_preassigned_id_after_material_write_retry_window(tmp_path):
    env = runtime(tmp_path, {"incoming/a.jpg": jpg("red")})
    _data, project, _provider, repository, artifacts, task, scheduler = env
    assert scheduler.run_once() is True
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3"))
    row = next(store.iter_status("IMPORTABLE"))
    store.confirm([row["object_key"]])
    store.assign_image_ids(task.task_id)
    pending = store.pending_index_batch()
    image_id = pending[0]["image_id"]
    MaterialRepository(project).upsert({
        "id": image_id, "filename": pending[0]["filename"],
        "stored_name": f"{image_id}.jpg", "storage_source_id": "external-a",
        "storage_type": "local", "object_key": pending[0]["object_key"],
        "content_sha256": pending[0]["content_sha256"],
        "size_bytes": pending[0]["size_bytes"], "labels": [],
    })
    artifacts.atomic_write_json(task.task_id, "scan/confirmation.json", {
        "accepted": True, "selected_count": 1,
    })
    repository.resume_after_confirmation(task.task_id)

    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    assert artifacts.read_json(task.task_id, completed.result_ref)["imported"] == 1
    assert MaterialRepository(project).count() == 1
    assert store.pending_index_batch() == []


def test_legacy_candidate_json_is_migrated_and_same_batch_sha_is_indexed_once(tmp_path):
    same = jpg("purple")
    env = runtime(tmp_path, {
        "incoming/original.jpg": same,
        "incoming/copy.jpg": same,
    })
    data, project, provider, repository, artifacts, task, scheduler = env
    candidates = []
    for key in ("incoming/original.jpg", "incoming/copy.jpg"):
        metadata = provider.stat(key)
        candidates.append({
            "object_key": key,
            "filename": Path(key).name,
            "storage_source_id": "external-a",
            "storage_type": "local",
            "content_sha256": metadata.sha256,
            "size_bytes": metadata.size_bytes,
            "etag": metadata.etag,
            "width": 32,
            "height": 24,
        })
    artifacts.atomic_write_json(task.task_id, "scan/result.json", {
        "storage_source_id": "external-a",
        "candidates": candidates,
    })
    lease = repository.claim_next("prepare", (TaskKind.MATERIAL_IMPORT,), {"storage.import"})
    assert lease is not None
    repository.finish(
        task.task_id, lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION, "scan/result.json",
    )

    confirmation = commit_storage_import(data, "p1", artifacts, task.task_id)
    assert confirmation["selected_count"] == 2
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3"))
    assert store.counts() == {"IMPORTABLE": 2}
    repository.resume_after_confirmation(task.task_id)

    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    final = artifacts.read_json(task.task_id, completed.result_ref)
    assert final["selected"] == final["indexed"] == 2
    assert final["imported"] == 1
    assert final["index_duplicates"] == 1
    assert MaterialRepository(project).count() == 1
