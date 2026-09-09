from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import zipfile

import pytest
from PIL import Image

from platform_core.material_repository import MaterialRepository
from platform_core.storage import StorageSourceRepository
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_tasks import StorageImportHandler
from platform_core.storage import import_tasks
from platform_core.storage.zip_import import OWNER_MARKER
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


def jpg(color: str) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), color).save(stream, format="JPEG")
    return stream.getvalue()


def write_zip(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


class Runtime:
    def __init__(
        self, tmp_path: Path, monkeypatch, files: dict[str, bytes], *,
        target="fire", source_type="local",
    ):
        self.data = tmp_path / "data"
        self.project_id = "p1"
        self.project = self.data / "projects" / self.project_id
        self.project.mkdir(parents=True)
        (self.project / "meta.json").write_text('{"labels": []}', encoding="utf-8")
        self.import_dir = tmp_path / "server-imports"
        self.storage_root = tmp_path / "external"
        self.source_id = "external-a"
        StorageSourceRepository(self.data / "storage" / "storage_sources.sqlite3").create({
            "id": self.source_id,
            "name": "external",
            "type": source_type,
            "config": (
                {"root": str(self.storage_root)}
                if source_type == "local"
                else {"endpoint": "http://127.0.0.1:1", "bucket": "unused"}
            ),
        })
        monkeypatch.setenv("MC_SERVER_IMPORT_DIR", str(self.import_dir))
        self.archive = self.import_dir / "fire.zip"
        write_zip(self.archive, files)
        task_root = self.data / "task_runtime"
        self.repository = TaskRepository(task_root / "tasks.sqlite3")
        self.artifacts = ArtifactStore(task_root / "artifacts")
        self.task = TaskRecord.new(
            "zip-1", self.project_id, TaskKind.MATERIAL_IMPORT,
            "request.json", f"storage:{self.source_id}",
        )
        self.artifacts.atomic_write_json(self.task.task_id, self.task.payload_ref, {
            "mode": "server_zip",
            "zip_path": "fire.zip",
            "storage_source_id": self.source_id,
            "target_prefix": target,
            "recursive": True,
        })
        self.repository.create(self.task)

    def scheduler(self) -> Scheduler:
        return Scheduler(
            self.repository,
            self.artifacts,
            "worker",
            {TaskKind.MATERIAL_IMPORT: StorageImportHandler(self.data)},
            {"storage.import"},
            lease_seconds=3,
        )

    def confirm_and_run(self) -> None:
        store = ImportCandidateStore(
            self.artifacts.artifact_path(self.task.task_id, "scan/candidates.sqlite3")
        )
        selection = store.confirm(
            row["object_key"] for row in store.iter_status("IMPORTABLE")
        )
        self.artifacts.atomic_write_json(self.task.task_id, "scan/confirmation.json", {
            "accepted": True,
            "selection_digest": selection.digest,
            "selected_count": selection.selected_count,
            "confirmed_at": selection.confirmed_at,
        })
        self.repository.resume_after_confirmation(self.task.task_id)
        assert self.scheduler().run_once() is True

    def recover_lease(self) -> None:
        self.repository.release_expired(datetime.now(timezone.utc) + timedelta(minutes=1))


def test_server_zip_extracts_scans_waits_and_indexes_without_upload_copy(tmp_path, monkeypatch):
    env = Runtime(tmp_path, monkeypatch, {
        "images/a.jpg": jpg("red"),
        "images/nested/b.jpg": jpg("blue"),
        "labels/a.txt": b"0 0.5 0.5 0.2 0.2\n",
        "data.yaml": b"names: [fire]\n",
    })

    assert env.scheduler().run_once() is True
    waiting = env.repository.get(env.task.task_id)
    assert waiting.status is TaskStatus.AWAITING_CONFIRMATION
    result = env.artifacts.read_json(env.task.task_id, waiting.result_ref)
    assert result["mode"] == "server_zip"
    assert result["importable_images"] == 2
    assert result["skipped_files"] == 2
    assert not (env.project / "uploads").exists()
    assert not (env.storage_root / "fire" / OWNER_MARKER).exists()

    env.confirm_and_run()
    assert env.repository.get(env.task.task_id).status is TaskStatus.SUCCEEDED
    materials = MaterialRepository(env.project)
    assert materials.count() == 2
    assert {row["object_key"] for row in materials.read().rows} == {
        "fire/images/a.jpg", "fire/images/nested/b.jpg",
    }
    assert not (env.project / "uploads").exists()


def test_server_zip_refuses_existing_nonempty_target_with_structured_error(tmp_path, monkeypatch):
    env = Runtime(tmp_path, monkeypatch, {"a.jpg": jpg("red")})
    target = env.storage_root / "fire"
    target.mkdir(parents=True)
    original = target / "existing.txt"
    original.write_text("preserve", encoding="utf-8")

    assert env.scheduler().run_once() is True
    failed = env.repository.get(env.task.task_id)
    assert failed.status is TaskStatus.FAILED
    result = env.artifacts.read_json(env.task.task_id, failed.result_ref)
    assert result["error"]["code"] == "ZIP_TARGET_EXISTS"
    assert result["error"]["solution"]
    assert original.read_text(encoding="utf-8") == "preserve"
    assert not (env.storage_root / ".import-staging" / env.task.task_id).exists()


def test_server_zip_rejects_nonlocal_source_before_provider_connection(tmp_path, monkeypatch):
    env = Runtime(
        tmp_path, monkeypatch, {"a.jpg": jpg("red")}, source_type="s3",
    )

    assert env.scheduler().run_once() is True
    failed = env.repository.get(env.task.task_id)
    assert failed.status is TaskStatus.FAILED
    result = env.artifacts.read_json(env.task.task_id, failed.result_ref)
    assert result["error"]["code"] == "ZIP_LOCAL_STORAGE_REQUIRED"


def test_server_zip_cancel_cleans_only_its_staging(tmp_path, monkeypatch):
    env = Runtime(tmp_path, monkeypatch, {"a.jpg": jpg("red")})
    other = env.storage_root / ".import-staging" / "other-task" / "keep.txt"
    other.parent.mkdir(parents=True)
    other.write_text("keep", encoding="utf-8")
    original_extract = import_tasks.extract_server_zip

    def request_cancel(*args, **kwargs):
        callback = kwargs["on_progress"]

        def cancelling(progress):
            env.repository.request_cancel(env.task.task_id)
            return callback(progress)

        kwargs["on_progress"] = cancelling
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(import_tasks, "extract_server_zip", request_cancel)
    assert env.scheduler().run_once() is True
    assert env.repository.get(env.task.task_id).status is TaskStatus.CANCELLED
    error = env.artifacts.read_json(env.task.task_id, "scan/error.json")
    assert error["error"]["code"] == "ZIP_CANCELLED"
    assert error["extracted_bytes"] > 0
    assert other.read_text(encoding="utf-8") == "keep"
    assert not (env.storage_root / ".import-staging" / env.task.task_id).exists()
    assert not (env.storage_root / "fire").exists()


@pytest.mark.parametrize("crash_window", ["staging", "published"])
def test_server_zip_recovers_crash_windows_and_indexes_once(
    tmp_path, monkeypatch, crash_window,
):
    env = Runtime(tmp_path, monkeypatch, {
        "images/a.jpg": jpg("red"),
        "images/b.jpg": jpg("blue"),
    })
    original_extract = import_tasks.extract_server_zip

    if crash_window == "staging":
        def crash(*args, **kwargs):
            callback = kwargs["on_progress"]

            def after_first(progress):
                result = callback(progress)
                if progress.completed_member is not None:
                    raise SystemExit("crash in staging")
                return result

            kwargs["on_progress"] = after_first
            return original_extract(*args, **kwargs)
    else:
        def crash(*args, **kwargs):
            original_extract(*args, **kwargs)
            raise SystemExit("crash after publication")

    monkeypatch.setattr(import_tasks, "extract_server_zip", crash)
    with pytest.raises(SystemExit):
        env.scheduler().run_once()
    monkeypatch.setattr(import_tasks, "extract_server_zip", original_extract)
    env.recover_lease()

    assert env.scheduler().run_once() is True
    assert env.repository.get(env.task.task_id).status is TaskStatus.AWAITING_CONFIRMATION
    env.confirm_and_run()
    assert env.repository.get(env.task.task_id).status is TaskStatus.SUCCEEDED
    assert MaterialRepository(env.project).count() == 2
    assert len({row["id"] for row in MaterialRepository(env.project).read().rows}) == 2
    assert not (env.storage_root / "fire" / OWNER_MARKER).exists()
    assert not (env.storage_root / ".import-staging" / env.task.task_id).exists()
