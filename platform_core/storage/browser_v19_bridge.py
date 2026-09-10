from __future__ import annotations

"""Compatibility bridge from the visible v19 browser ZIP UI to MATERIAL_IMPORT.

The browser still uploads into ``projects/<project>/import_jobs/<job>/source.zip``.
This module makes the v19 worker thread orchestration-only: heavy ZIP validation,
extraction, YOLO discovery, image hash/verify and indexing run in the durable
Storage Worker.

The bridge deliberately keeps the old job.json contract bounded.  It stores a
small image-id sample for old review UI compatibility, never 10k/50k/100k IDs.
"""

import json
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from platform_core.annotations import atomic_write_json
from platform_core.labels import ensure_stable_label_ids, project_label_file_lock
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus

from .import_candidates import ImportCandidateStore
from .import_confirmation import confirm_import, mapping_suggestions
from .import_tasks import MANIFEST_REF, SCAN_RESULT_REF


_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_TERMINAL = {
    TaskStatus.SUCCEEDED,
    TaskStatus.PARTIAL_SUCCESS,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.BLOCKED_BY_ENVIRONMENT,
    TaskStatus.BLOCKED_BY_HARDWARE,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_dir(data_dir: Path, project_id: str, job_id: str) -> Path:
    if not _SAFE_JOB_ID.fullmatch(str(job_id)):
        raise ValueError("invalid browser import job id")
    project_root = (data_dir / "projects" / str(project_id)).resolve()
    root = (project_root / "import_jobs").resolve()
    directory = (root / str(job_id)).resolve()
    if root not in directory.parents:
        raise ValueError("browser import job escapes project root")
    return directory


def _job_file(data_dir: Path, project_id: str, job_id: str) -> Path:
    return _job_dir(data_dir, project_id, job_id) / "job.json"


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write_job(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temp_name)
    try:
        import os
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return value


def _update_job(path: Path, **changes) -> dict[str, Any]:
    current = _read_json(path, {})
    if not isinstance(current, dict):
        current = {}
    current.update(changes)
    return _write_job(path, current)


def _runtime(data_dir: Path) -> tuple[TaskRepository, ArtifactStore]:
    runtime = data_dir / "task_runtime"
    return (
        TaskRepository(runtime / "tasks.sqlite3"),
        ArtifactStore(runtime / "artifacts"),
    )


def _label_rows(meta_path: Path) -> list[dict[str, Any]]:
    with project_label_file_lock(meta_path):
        meta = _read_json(meta_path, {})
        if not isinstance(meta, dict):
            raise ValueError("project meta is invalid")
        changed = ensure_stable_label_ids(meta)
        if changed:
            atomic_write_json(meta_path, meta)
        rows = []
        labels = list(meta.get("labels") or [])
        label_meta = list(meta.get("label_meta") or [])
        for index, code in enumerate(labels):
            item = dict(label_meta[index]) if index < len(label_meta) and isinstance(label_meta[index], dict) else {}
            item["code"] = str(code)
            item.setdefault("display_name", str(code))
            item.setdefault("status", "active")
            rows.append(item)
        return rows


def _create_label(meta_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    with project_label_file_lock(meta_path):
        meta = _read_json(meta_path, {})
        if not isinstance(meta, dict):
            raise ValueError("project meta is invalid")
        ensure_stable_label_ids(meta)
        labels = meta.setdefault("labels", [])
        label_meta = meta.setdefault("label_meta", [])
        while len(label_meta) < len(labels):
            label_meta.append({})
        label_id = str(spec.get("label_id") or "")
        code = str(spec.get("code") or "")
        for index, existing_code in enumerate(labels):
            item = label_meta[index] if isinstance(label_meta[index], dict) else {}
            if str(item.get("label_id") or "") == label_id:
                return {**item, "code": str(existing_code)}
            if str(existing_code) == code:
                raise ValueError(f"platform label code already exists: {code}")
        labels.append(code)
        item = {
            "label_id": label_id,
            "code": code,
            "display_name": str(spec.get("display_name") or code),
            "status": "active",
            "aliases": [],
            "provenance": str(spec.get("provenance") or "legacy_browser_import"),
        }
        label_meta.append(item)
        atomic_write_json(meta_path, meta)
        return dict(item)


def _safe_code(name: str, class_id: int, occupied: set[str]) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "").strip()).strip("_-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"class_{class_id}"
    normalized = normalized[:64]
    if normalized not in occupied:
        return normalized
    base = f"class_{class_id}"
    candidate = base
    suffix = 1
    while candidate in occupied:
        suffix += 1
        candidate = f"{base}_{suffix}"
    return candidate[:64]


def _selection_keys(target_prefix: str, selected_paths: Iterable[str]) -> list[str] | None:
    values = []
    prefix = str(target_prefix).strip("/")
    for raw in selected_paths:
        value = str(raw or "").replace("\\", "/").lstrip("/")
        if not value:
            continue
        if value.startswith("../") or "/../" in value or value == "..":
            raise ValueError("selected browser import path escapes archive root")
        values.append(f"{prefix}/{value}" if prefix else value)
    return values or None


def _auto_confirm(
    data_dir: Path,
    project_id: str,
    task_id: str,
    target_prefix: str,
    selected_paths: Iterable[str],
    repository: TaskRepository,
    artifacts: ArtifactStore,
) -> None:
    task = repository.get(task_id)
    if task is None or task.status is not TaskStatus.AWAITING_CONFIRMATION:
        return
    store = ImportCandidateStore(
        artifacts.artifact_path(task_id, MANIFEST_REF),
        import_id=task_id,
    )
    meta_path = data_dir / "projects" / project_id / "meta.json"
    labels = _label_rows(meta_path)
    suggestions = mapping_suggestions(store.external_classes(), labels)
    actions: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    for row in suggestions:
        class_id = int(row["class_id"])
        key = str(class_id)
        target_id = str(row.get("suggested_target_label_id") or "")
        if target_id:
            actions[key] = {"action": "map", "target_label_id": target_id}
            continue
        unresolved.append(f"{class_id}:{str(row.get('name') or '')}")
    if unresolved:
        raise ValueError(
            "YOLO 外部标签无法唯一映射到现有平台标签："
            + ", ".join(unresolved[:20])
            + "。请使用服务器素材导入的标签映射确认页处理后再导入；系统不会自动创建标签。"
        )
    confirm_import(
        store,
        artifacts,
        task_id,
        object_keys=_selection_keys(target_prefix, selected_paths),
        class_actions=actions,
        accept_quality_report=True,
        labels=labels,
        create_label=lambda spec: _create_label(meta_path, spec),
    )
    repository.resume_after_confirmation(task_id)


def _outcome_summary(store: ImportCandidateStore, limit: int = 500) -> tuple[list[str], int, dict[str, int]]:
    with store._connect() as database:
        total = int(database.execute("SELECT COUNT(*) FROM indexing_outcomes").fetchone()[0])
        ids = [str(row[0]) for row in database.execute(
            "SELECT image_id FROM indexing_outcomes ORDER BY object_key LIMIT ?",
            (max(1, min(int(limit), 2000)),),
        )]
        row = database.execute(
            "SELECT COALESCE(SUM(annotations_written),0),COALESCE(SUM(boxes_imported),0),"
            "COALESCE(SUM(boxes_skipped),0),COALESCE(SUM(negative_samples),0) "
            "FROM indexing_outcomes"
        ).fetchone()
    metrics = {
        "annotated_images": int(row[0]),
        "boxes": int(row[1]),
        "boxes_skipped": int(row[2]),
        "negative_samples": int(row[3]),
    }
    return ids, total, metrics


def _mirror_task(
    data_dir: Path,
    project_id: str,
    job_id: str,
    selected_paths: Iterable[str],
    *,
    allow_confirm: bool,
) -> dict[str, Any]:
    path = _job_file(data_dir, project_id, job_id)
    job = _read_json(path, {})
    if not isinstance(job, dict):
        return {}
    task_id = str(job.get("durable_task_id") or "")
    if not task_id:
        return job
    repository, artifacts = _runtime(data_dir)
    task = repository.get(task_id)
    if task is None:
        return _update_job(
            path,
            status="failed",
            stage="持久化导入任务丢失",
            error="MATERIAL_IMPORT task no longer exists",
            progress=100,
        )
    request = artifacts.read_json(task_id, task.payload_ref, default={})
    target_prefix = str((request or {}).get("target_prefix") or "")
    if task.status is TaskStatus.AWAITING_CONFIRMATION and allow_confirm:
        _auto_confirm(
            data_dir, project_id, task_id, target_prefix, selected_paths,
            repository, artifacts,
        )
        task = repository.get(task_id) or task

    if task.status in _TERMINAL:
        if task.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
            store = ImportCandidateStore(
                artifacts.artifact_path(task_id, MANIFEST_REF), import_id=task_id,
            )
            ids, total, metrics = _outcome_summary(store)
            final = artifacts.read_json(task_id, task.result_ref or "scan/final.json", default={})
            scan = artifacts.read_json(task_id, SCAN_RESULT_REF, default={})
            quality = (scan or {}).get("quality") if isinstance(scan, dict) else {}
            warnings = []
            if isinstance(quality, dict) and quality.get("issues"):
                warnings.append("部分 YOLO 标注存在质量问题，已按质量报告规则跳过或裁剪。")
            report = {
                "detected_format": "YOLO",
                "imported_images": int((final or {}).get("selected") or total),
                "annotated_images": metrics["annotated_images"],
                "boxes": metrics["boxes"],
                "boxes_skipped": metrics["boxes_skipped"],
                "negative_samples": metrics["negative_samples"],
                "warnings": warnings,
                "durable_task_id": task_id,
            }
            return _update_job(
                path,
                status="done",
                stage="导入完成",
                progress=100,
                processed=report["imported_images"],
                message=f"已导入 {report['imported_images']} 张图片",
                report=report,
                imported_image_ids=ids,
                imported_image_ids_truncated=(total > len(ids)),
                durable_task_id=task_id,
                durable_status=task.status.value,
                finished_at=_now(),
            )
        return _update_job(
            path,
            status="failed" if task.status is not TaskStatus.CANCELLED else "failed",
            stage="导入失败" if task.status is not TaskStatus.CANCELLED else "导入已取消",
            progress=100,
            error=str(task.error or task.current_item or task.status.value),
            message=str(task.error or task.current_item or task.status.value),
            durable_task_id=task_id,
            durable_status=task.status.value,
            finished_at=_now(),
        )

    legacy_progress = max(3.0, min(99.0, float(task.progress or 0)))
    return _update_job(
        path,
        status="running",
        stage=str(task.stage or "后台导入中"),
        progress=legacy_progress,
        processed=int(job.get("processed") or 0),
        message=str(task.current_item or "Storage Worker 正在处理 ZIP"),
        durable_task_id=task_id,
        durable_status=task.status.value,
    )


def run_browser_v19_bridge(
    data_dir: str | Path,
    project_id: str,
    dataset_id: str,
    job_id: str,
    selected_paths: Iterable[str],
) -> bool:
    """Create/reconcile one durable MATERIAL_IMPORT and block only as orchestrator.

    Returns True when this bridge owns the job.  The old v19 parser should not be
    called afterwards.  Exceptions are converted into the legacy job.json error
    contract so the Uvicorn request thread is never the heavy import executor.
    """
    del dataset_id  # unified material pool; dataset grouping is not a training contract
    root = Path(data_dir).resolve()
    path = _job_file(root, project_id, job_id)
    job = _read_json(path, {})
    if not isinstance(job, dict):
        return False
    archive = _job_dir(root, project_id, job_id) / "source.zip"
    if not archive.is_file():
        _update_job(path, status="failed", stage="ZIP 文件不存在", progress=100,
                    error="uploaded source.zip is missing")
        return True
    selected = tuple(str(value) for value in selected_paths if str(value))
    started = time.monotonic()
    try:
        repository, artifacts = _runtime(root)
        task_id = str(job.get("durable_task_id") or "")
        if not task_id:
            task_id = uuid.uuid4().hex[:12]
            target_prefix = f"browser_imports/{job_id}-{task_id}"
            request = {
                "mode": "browser_zip",
                "storage_source_id": "default_local",
                "browser_job_id": job_id,
                "target_prefix": target_prefix,
                "recursive": True,
                "import_format": "auto",
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
                path,
                status="running",
                stage="已进入 Storage Worker 队列",
                progress=3,
                message="ZIP 后台导入已切换到持久化 Worker",
                durable_task_id=task_id,
                durable_status=TaskStatus.QUEUED.value,
                processing_started_at=_now(),
            )

        while True:
            current = _mirror_task(
                root,
                project_id,
                job_id,
                selected,
                allow_confirm=True,
            )
            if str(current.get("status") or "") in {"done", "failed"}:
                elapsed = round(time.monotonic() - started, 3)
                if current.get("processing_seconds") is None:
                    _update_job(path, processing_seconds=elapsed, eta_seconds=0)
                return True
            time.sleep(0.5)
    except Exception as error:
        _update_job(
            path,
            status="failed",
            stage="持久化 ZIP 导入失败",
            progress=100,
            error=f"{type(error).__name__}: {error}",
            message=str(error),
            processing_seconds=round(time.monotonic() - started, 3),
            eta_seconds=0,
            finished_at=_now(),
        )
        return True


def reconcile_v19_job(
    data_dir: str | Path,
    project_id: str,
    job_id: str,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh a legacy job from its durable task after process/UI restart."""
    value = dict(job or {})
    if not value.get("durable_task_id"):
        return value
    selected = value.get("selected_paths") or []
    try:
        return _mirror_task(
            Path(data_dir).resolve(), project_id, job_id, selected,
            allow_confirm=True,
        )
    except Exception:
        # GET compatibility must remain readable even if recovery diagnostics fail.
        return value
