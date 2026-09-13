from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from platform_core.material_repository import MaterialRepository
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


def _jpg() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), "red").save(stream, format="JPEG")
    return stream.getvalue()


def _runtime(tmp_path: Path):
    data = tmp_path / "data"
    project_id = "p1"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    (project / "meta.json").write_text('{"labels": []}', encoding="utf-8")

    external = tmp_path / "external"
    provider = LocalStorageProvider("external-a", external)
    provider.upload("incoming/a.jpg", BytesIO(_jpg()))
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
        "index-cancel-1",
        project_id,
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        "storage:external-a",
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
    return data, project, repository, artifacts, task, scheduler


def test_cancel_during_index_preflight_prevents_material_business_write(tmp_path: Path, monkeypatch):
    _data, project, repository, artifacts, task, scheduler = _runtime(tmp_path)

    # Real scan first: the task must genuinely reach human confirmation.
    assert scheduler.run_once() is True
    assert repository.get(task.task_id).status is TaskStatus.AWAITING_CONFIRMATION
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
    repository.resume_after_confirmation(task.task_id)

    original = MaterialRepository.get_by_storage_references
    injected = False

    def preflight_then_cancel(self, references):
        nonlocal injected
        result = original(self, references)
        if not injected:
            injected = True
            # Cancellation becomes durable after preflight has started but before
            # any material/annotation business write should be allowed to begin.
            repository.request_cancel(task.task_id)
        return result

    monkeypatch.setattr(
        MaterialRepository,
        "get_by_storage_references",
        preflight_then_cancel,
    )

    assert scheduler.run_once() is True
    cancelled = repository.get(task.task_id)
    assert cancelled.status is TaskStatus.CANCELLED

    # Stop means no new business write may start after cancellation became truth.
    assert MaterialRepository(project).count() == 0
    pending = store.pending_index_batch()
    assert len(pending) == 1
    assert not bool(pending[0]["indexed"])
    assert artifacts.read_json(task.task_id, "result.json", default=None) is None
