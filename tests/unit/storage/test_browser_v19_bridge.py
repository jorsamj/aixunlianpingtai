from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import platform_core.storage.browser_v19_entry as entry
from platform_core.storage.browser_v19_entry import discover_browser_yolo_yaml
from platform_core.storage.optimized_import_tasks import OptimizedStorageImportHandler
from platform_core.task_runtime import TaskKind, TaskRepository


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as stream:
        for name, value in members.items():
            stream.writestr(name, value)
    return path


def _browser_job(data_dir: Path, project_id="project-1", job_id="browser-job"):
    directory = data_dir / "projects" / project_id / "import_jobs" / job_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "job.json").write_text(
        json.dumps({"id": job_id, "status": "selecting"}), encoding="utf-8"
    )
    return directory


def test_unique_nested_dataset_yaml_is_claimable(tmp_path):
    archive = _write_zip(tmp_path / "source.zip", {
        "wrapper/data.yaml": b"names: [cat]\ntrain: images\n",
        "wrapper/images/a.jpg": b"image",
    })
    assert discover_browser_yolo_yaml(archive) == "wrapper/data.yaml"


def test_ambiguous_or_non_yolo_zip_falls_back(tmp_path):
    ambiguous = _write_zip(tmp_path / "ambiguous.zip", {
        "a/data.yaml": b"names: [a]\ntrain: images\n",
        "b/dataset.yaml": b"names: [b]\ntrain: images\n",
    })
    plain = _write_zip(tmp_path / "plain.zip", {"images/a.jpg": b"image"})
    assert discover_browser_yolo_yaml(ambiguous) is None
    assert discover_browser_yolo_yaml(plain) is None


def test_entry_creates_durable_material_import_and_freezes_selection(tmp_path, monkeypatch):
    project_id, job_id = "project-1", "browser-job"
    directory = _browser_job(tmp_path, project_id, job_id)
    _write_zip(directory / "source.zip", {
        "dataset/data.yaml": b"names: [cat]\ntrain: images\n",
        "dataset/images/a.jpg": b"image",
        "dataset/labels/a.txt": b"0 .5 .5 .2 .2\n",
    })
    delegated = []
    monkeypatch.setattr(
        entry,
        "run_browser_v19_bridge",
        lambda *args: delegated.append(args) or True,
    )

    assert entry.try_run_browser_v19_bridge(
        tmp_path, project_id, "legacy-dataset", job_id, ["dataset/images/a.jpg"]
    ) is True

    job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    assert job["durable_task_id"]
    assert job["selected_paths"] == ["dataset/images/a.jpg"]
    assert job["durable_dataset_yaml"] == "dataset/data.yaml"
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    task = repository.get(job["durable_task_id"])
    assert task is not None
    assert task.kind is TaskKind.MATERIAL_IMPORT
    assert task.required_capabilities == ("storage.import",)
    payload = json.loads(
        (tmp_path / "task_runtime" / "artifacts" / task.task_id / "request.json").read_text(encoding="utf-8")
    )
    assert payload["mode"] == "browser_zip"
    assert payload["import_format"] == "yolo"
    assert payload["dataset_yaml"].endswith("/dataset/data.yaml")
    assert len(delegated) == 1


def test_entry_does_not_create_task_for_unsupported_archive(tmp_path, monkeypatch):
    directory = _browser_job(tmp_path)
    _write_zip(directory / "source.zip", {"annotations.json": b"{}", "images/a.jpg": b"image"})
    monkeypatch.setattr(entry, "run_browser_v19_bridge", lambda *_args: pytest.fail("must not delegate"))
    assert entry.try_run_browser_v19_bridge(
        tmp_path, "project-1", "legacy-dataset", "browser-job", []
    ) is False
    assert not (tmp_path / "task_runtime" / "tasks.sqlite3").exists()


def test_optimized_worker_resolves_browser_zip_inside_project_root(tmp_path):
    project_id, job_id = "project-1", "browser-job"
    directory = _browser_job(tmp_path, project_id, job_id)
    archive = _write_zip(directory / "source.zip", {
        "data.yaml": b"names: [cat]\ntrain: images\n",
        "images/a.jpg": b"image",
    })
    handler = OptimizedStorageImportHandler(tmp_path)
    context = SimpleNamespace(task=SimpleNamespace(project_id=project_id, task_id="task-123"))
    source, provider, root, prefix, zip_path, resolved = handler._server_zip_source(
        context,
        {
            "mode": "browser_zip",
            "storage_source_id": "default_local",
            "browser_job_id": job_id,
            "target_prefix": "browser_imports/task-123",
        },
    )
    assert source.id == "default_local"
    assert provider.root == (tmp_path / "projects" / project_id).resolve()
    assert root == provider.root
    assert prefix == "browser_imports/task-123"
    assert zip_path == f"{job_id}/source.zip"
    assert resolved == archive.resolve()


@pytest.mark.parametrize("job_id", ["../escape", "a/b", "", ".."])
def test_browser_worker_rejects_unsafe_job_id(tmp_path, job_id):
    handler = OptimizedStorageImportHandler(tmp_path)
    context = SimpleNamespace(task=SimpleNamespace(project_id="project-1", task_id="task-123"))
    with pytest.raises(Exception):
        handler._server_zip_source(
            context,
            {"mode": "browser_zip", "storage_source_id": "default_local", "browser_job_id": job_id},
        )
