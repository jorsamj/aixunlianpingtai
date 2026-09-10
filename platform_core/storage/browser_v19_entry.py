from __future__ import annotations

"""Entry gate for routing the visible v19 browser upload into MATERIAL_IMPORT.

Only ZIPs with exactly one YOLO dataset YAML are claimed. COCO/VOC or ambiguous
archives intentionally fall back to the legacy compatibility parser until those
formats have equivalent durable import support. The heavy work never runs here:
this module only inspects the ZIP central directory, creates a durable task, and
then delegates progress mirroring to ``browser_v19_bridge``.
"""

import zipfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Iterable

from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus

from .browser_v19_bridge import (
    _job_dir,
    _read_json,
    _runtime,
    _update_job,
    run_browser_v19_bridge,
)
from .zip_import import ServerZipImportError, safe_member_path


_YAML_NAMES = {"data.yaml", "dataset.yaml"}


def discover_browser_yolo_yaml(archive: str | Path) -> str | None:
    """Return the unique safe YOLO YAML member or None for legacy fallback."""
    path = Path(archive)
    try:
        with zipfile.ZipFile(path, "r") as stream:
            candidates: list[str] = []
            for member in stream.infolist():
                if member.is_dir():
                    continue
                safe = safe_member_path(member.orig_filename).as_posix()
                if PurePosixPath(safe).name.lower() in _YAML_NAMES:
                    candidates.append(safe)
                    if len(candidates) > 1:
                        return None
            return candidates[0] if len(candidates) == 1 else None
    except (OSError, zipfile.BadZipFile, ServerZipImportError):
        return None


def try_run_browser_v19_bridge(
    data_dir: str | Path,
    project_id: str,
    dataset_id: str,
    job_id: str,
    selected_paths: Iterable[str],
) -> bool:
    """Claim one modern YOLO browser ZIP and hand it to the Storage Worker.

    ``False`` means the caller may use the legacy parser because this archive is
    not yet supported by the durable path. Once a durable task id exists this
    function always owns the job; it must never silently fall back after a
    partial durable execution.
    """
    root = Path(data_dir).resolve()
    job_directory = _job_dir(root, project_id, job_id)
    job_path = job_directory / "job.json"
    job = _read_json(job_path, {})
    if not isinstance(job, dict):
        return False

    selected = tuple(str(value) for value in selected_paths if str(value))
    if job.get("durable_task_id"):
        return run_browser_v19_bridge(root, project_id, dataset_id, job_id, selected)

    archive = job_directory / "source.zip"
    dataset_yaml = discover_browser_yolo_yaml(archive)
    if not dataset_yaml:
        return False

    repository, artifacts = _runtime(root)
    task_id = uuid.uuid4().hex[:12]
    target_prefix = f"browser_imports/{job_id}-{task_id}"
    request = {
        "mode": "browser_zip",
        "storage_source_id": "default_local",
        "browser_job_id": str(job_id),
        "target_prefix": target_prefix,
        "recursive": True,
        "import_format": "yolo",
        "dataset_yaml": f"{target_prefix}/{dataset_yaml}",
    }
    artifacts.atomic_write_json(task_id, "request.json", request)
    repository.create(
        TaskRecord.new(
            task_id,
            project_id,
            TaskKind.MATERIAL_IMPORT,
            "request.json",
            "storage:default_local",
            required_capabilities=("storage.import",),
        ),
        artifacts=artifacts,
    )
    _update_job(
        job_path,
        status="running",
        stage="已进入 Storage Worker 队列",
        progress=3,
        message="YOLO ZIP 后台导入已切换到持久化 Worker",
        durable_task_id=task_id,
        durable_status=TaskStatus.QUEUED.value,
        durable_dataset_yaml=dataset_yaml,
        selected_paths=list(selected),
    )
    return run_browser_v19_bridge(root, project_id, dataset_id, job_id, selected)
