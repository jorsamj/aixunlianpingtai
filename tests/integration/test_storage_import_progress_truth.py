from __future__ import annotations

from io import BytesIO

from PIL import Image

from platform_core.storage import LocalStorageProvider, StorageSourceRepository
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_tasks import StorageImportHandler
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


def _jpg(color: str) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), color).save(stream, format="JPEG")
    return stream.getvalue()


def test_confirmed_storage_import_reports_monotonic_indexing_progress(tmp_path, monkeypatch):
    data = tmp_path / "data"
    project_id = "p1"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    (project / "meta.json").write_text('{"labels": []}', encoding="utf-8")

    external = tmp_path / "external"
    provider = LocalStorageProvider("external-a", external)
    provider.upload("incoming/a.jpg", BytesIO(_jpg("red")))
    provider.upload("incoming/b.jpg", BytesIO(_jpg("blue")))
    StorageSourceRepository(data / "storage" / "storage_sources.sqlite3").create({
        "id": "external-a",
        "name": "external",
        "type": "local",
        "config": {"root": str(external)},
    })

    task_root = data / "task_runtime"
    repository = TaskRepository(task_root / "tasks.sqlite3")
    artifacts = ArtifactStore(task_root / "artifacts")
    task = TaskRecord.new(
        "storage-progress",
        project_id,
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        "storage:external-a",
        required_capabilities=("storage.import",),
    )
    artifacts.atomic_write_json(task.task_id, task.payload_ref, {
        "storage_source_id": "external-a",
        "prefix": "incoming",
        "recursive": True,
    })
    repository.create(task)
    scheduler = Scheduler(
        repository,
        artifacts,
        "worker",
        {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)},
        {"storage.import"},
    )

    assert scheduler.run_once() is True
    awaiting = repository.get(task.task_id)
    assert awaiting is not None
    assert awaiting.status is TaskStatus.AWAITING_CONFIRMATION
    assert awaiting.progress == 50

    store = ImportCandidateStore(
        artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3")
    )
    keys = [row["object_key"] for row in store.iter_status("IMPORTABLE")]
    selection = store.confirm(keys)
    artifacts.atomic_write_json(task.task_id, "scan/confirmation.json", {
        "accepted": True,
        "selection_digest": selection.digest,
        "selected_count": selection.selected_count,
        "confirmed_at": selection.confirmed_at,
    })
    resumed = repository.resume_after_confirmation(task.task_id)
    assert resumed.progress == awaiting.progress == 50

    # Force two durable indexing batches so the contract observes intermediate
    # public progress rather than only the terminal 100% finish.
    import platform_core.storage.import_tasks as import_tasks

    monkeypatch.setattr(import_tasks, "BATCH_SIZE", 1)
    original_heartbeat = repository.heartbeat
    indexing_progress: list[float] = []

    def recording_heartbeat(*args, **kwargs):
        result = original_heartbeat(*args, **kwargs)
        if kwargs.get("stage") == "indexing":
            indexing_progress.append(float(result.progress))
        return result

    monkeypatch.setattr(repository, "heartbeat", recording_heartbeat)

    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed is not None
    assert completed.status is TaskStatus.SUCCEEDED
    assert completed.progress == 100

    assert len(indexing_progress) >= 2
    assert indexing_progress == sorted(indexing_progress)
    assert indexing_progress[0] > 50
    assert indexing_progress[-1] == 99
