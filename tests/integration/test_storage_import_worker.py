from __future__ import annotations

from io import BytesIO

from PIL import Image

from platform_core.material_repository import MaterialRepository
from platform_core.storage import LocalStorageProvider, StorageSourceRepository
from platform_core.storage.import_tasks import StorageImportHandler, commit_storage_import
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus


def jpg(color):
    stream = BytesIO(); Image.new("RGB", (32, 24), color).save(stream, format="JPEG"); return stream.getvalue()


def test_existing_source_scan_and_confirm_indexes_without_copying(tmp_path):
    data = tmp_path / "data"
    project_id = "p1"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    (project / "meta.json").write_text('{"labels": []}', encoding="utf-8")
    external = tmp_path / "external"
    provider = LocalStorageProvider("external-a", external)
    provider.upload("incoming/a.jpg", BytesIO(jpg("red")), content_type="image/jpeg")
    provider.upload("incoming/b.png", BytesIO(jpg("blue")), content_type="image/png")
    provider.upload("incoming/readme.txt", BytesIO(b"not an image"))
    sources = StorageSourceRepository(data / "storage" / "storage_sources.sqlite3")
    sources.create({"id": "external-a", "name": "external", "type": "local", "config": {"root": str(external)}})
    runtime = data / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    task = TaskRecord.new("scan-1", project_id, TaskKind.MATERIAL_IMPORT, "request.json", "storage:external-a")
    artifacts.atomic_write_json(task.task_id, task.payload_ref, {"storage_source_id": "external-a", "prefix": "incoming", "recursive": True})
    repository.create(task)
    scheduler = Scheduler(repository, artifacts, "worker", {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)}, {"storage.import"})

    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    assert completed.progress == 100
    result = artifacts.read_json(task.task_id, completed.result_ref)
    assert result["scanned_files"] == 3
    assert result["importable_images"] == 2
    assert result["scanned"] == result["scanned_files"]
    assert result["importable"] == result["importable_images"]
    assert result["failed"] == 0

    confirmed = commit_storage_import(data, project_id, artifacts, task.task_id)
    assert confirmed["imported"] == 2
    materials = MaterialRepository(project)
    rows = materials.read().rows
    assert materials.count() == 2
    assert {row["storage_source_id"] for row in rows} == {"external-a"}
    assert all(row["stored_name"] for row in rows)
    assert {row["stored_name"].rsplit(".", 1)[-1] for row in rows} == {"jpg", "png"}
    assert not (project / "uploads").exists()
    assert not (data / "cache" / "materials").exists()
    assert provider.exists("incoming/a.jpg")
    assert provider.exists("incoming/b.png")


def test_second_scan_reports_existing_source_keys_as_duplicates(tmp_path):
    data = tmp_path / "data"; project_id = "p1"; project = data / "projects" / project_id
    project.mkdir(parents=True); (project / "meta.json").write_text('{}', encoding="utf-8")
    external = tmp_path / "external"; provider = LocalStorageProvider("external", external)
    metadata = provider.upload("a.jpg", BytesIO(jpg("white")))
    sources = StorageSourceRepository(data / "storage" / "storage_sources.sqlite3")
    sources.create({"id": "external", "name": "external", "type": "local", "config": {"root": str(external)}})
    MaterialRepository(project).upsert({"id": "old", "filename": "a.jpg", "storage_source_id": "external", "storage_type": "local", "object_key": "a.jpg", "content_sha256": metadata.sha256, "labels": []})
    runtime = data / "task_runtime"; repository = TaskRepository(runtime / "tasks.sqlite3"); artifacts = ArtifactStore(runtime / "artifacts")
    task = TaskRecord.new("scan-duplicate", project_id, TaskKind.MATERIAL_IMPORT, "request.json", "storage:external")
    artifacts.atomic_write_json(task.task_id, task.payload_ref, {"storage_source_id": "external", "prefix": "", "recursive": True})
    repository.create(task)
    Scheduler(repository, artifacts, "worker", {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)}, {"storage.import"}).run_once()
    result = artifacts.read_json(task.task_id, "scan/result.json")
    assert result["duplicates"] == 1
    assert result["importable_images"] == 0
    assert result["importable"] == 0
