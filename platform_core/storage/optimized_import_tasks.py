from __future__ import annotations

"""Scale-oriented MATERIAL_IMPORT worker registration.

The base 42.25 import implementation already keeps YOLO discovery bounded to the
new ZIP subtree and parallelizes local image verification. This module fixes a
remaining small-file bottleneck: ZIP extraction emits progress for chunks and
completed members, while WorkerContext.cancel_requested() and
TaskRepository.heartbeat() both hit SQLite. Calling both on every callback can
turn a 20k/100k-member archive into tens or hundreds of thousands of task-DB
round trips.

Keep recovery checkpoints durable, but throttle lease/progress I/O and cancel
polls to human-scale sub-second/one-second intervals. The extractor itself
continues to stream every byte and validate every member.
"""

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from platform_core.task_runtime import TaskKind, TaskStatus

from .import_tasks import (
    DEFAULT_ZIP_CHECKPOINT_MEMBERS,
    DEFAULT_ZIP_CHECKPOINT_SECONDS,
    _positive_float_env,
    _positive_int_env,
)
from .rescan_tasks import StorageRescanHandler
from .zip_import import (
    ExtractionCancelled,
    ServerZipImportError,
    UnsafeArchive,
    extract_server_zip,
    finalize_server_zip_publication,
)


DEFAULT_ZIP_HEARTBEAT_SECONDS = 1.0
DEFAULT_ZIP_CANCEL_POLL_SECONDS = 0.25


class OptimizedStorageImportHandler(StorageRescanHandler):
    """Preserve rescan behavior while throttling ordinary server-ZIP DB traffic."""

    def _server_zip(self, context, request):
        live_state: dict[str, Any] = {}
        try:
            _source, _provider, root, target_prefix, zip_path, archive = (
                self._server_zip_source(context, request)
            )
            checkpoint = context.load_checkpoint()
            saved = checkpoint.get("zip_import")
            saved = dict(saved) if isinstance(saved, dict) else {}
            if saved.get("published") is True:
                if (
                    saved.get("target_prefix") != target_prefix
                    or saved.get("zip_path") != zip_path
                ):
                    raise UnsafeArchive(
                        "Server ZIP request no longer matches its durable checkpoint",
                        code="ZIP_CHECKPOINT_MISMATCH",
                        solution="Create a new import task instead of changing a running task.",
                    )
                finalize_server_zip_publication(
                    root, target_prefix, task_id=context.task.task_id,
                )
            else:
                completed = saved.get("completed_members")
                completed = completed if isinstance(completed, dict) else {}
                checkpoint_members = _positive_int_env(
                    "MC_ZIP_CHECKPOINT_MEMBERS",
                    DEFAULT_ZIP_CHECKPOINT_MEMBERS,
                    100_000,
                )
                checkpoint_seconds = _positive_float_env(
                    "MC_ZIP_CHECKPOINT_SECONDS",
                    DEFAULT_ZIP_CHECKPOINT_SECONDS,
                    3600.0,
                )
                heartbeat_seconds = _positive_float_env(
                    "MC_ZIP_HEARTBEAT_SECONDS",
                    DEFAULT_ZIP_HEARTBEAT_SECONDS,
                    10.0,
                )
                cancel_poll_seconds = _positive_float_env(
                    "MC_ZIP_CANCEL_POLL_SECONDS",
                    DEFAULT_ZIP_CANCEL_POLL_SECONDS,
                    5.0,
                )
                last_checkpoint_files = len(completed)
                last_checkpoint_at = time.monotonic()
                last_heartbeat_at = 0.0
                last_cancel_poll_at = 0.0
                checkpoint_saves = 0
                heartbeat_writes = 0
                cancel_checks = 0
                cancel_requested = False

                def poll_cancel(now: float, *, force: bool = False) -> bool:
                    nonlocal last_cancel_poll_at, cancel_checks, cancel_requested
                    if force or now - last_cancel_poll_at >= cancel_poll_seconds:
                        cancel_requested = bool(context.cancel_requested())
                        cancel_checks += 1
                        last_cancel_poll_at = now
                    return cancel_requested

                def emit_heartbeat(progress, now: float, *, force: bool = False) -> None:
                    nonlocal last_heartbeat_at, heartbeat_writes
                    if not force and now - last_heartbeat_at < heartbeat_seconds:
                        return
                    percent = (
                        min(45.0, 45.0 * progress.extracted_bytes / progress.declared_bytes)
                        if progress.declared_bytes else 0.0
                    )
                    context.repository.heartbeat(
                        context.task.task_id,
                        context.lease.lease_token,
                        progress=percent,
                        stage="extracting",
                        current_item=(
                            f"已解压 {progress.extracted_files} 个文件 · "
                            f"{progress.extracted_bytes} 字节 · 当前 {progress.current_member}"
                        ),
                    )
                    heartbeat_writes += 1
                    last_heartbeat_at = now

                def on_extract(progress):
                    nonlocal last_checkpoint_files, last_checkpoint_at, checkpoint_saves
                    if progress.completed_member is not None:
                        completed[progress.completed_member.name] = asdict(
                            progress.completed_member
                        )
                    state = {
                        "zip_path": zip_path,
                        "target_prefix": target_prefix,
                        "published": False,
                        "completed_members": completed,
                        "extracted_files": progress.extracted_files,
                        "extracted_bytes": progress.extracted_bytes,
                        "declared_files": progress.declared_files,
                        "declared_bytes": progress.declared_bytes,
                        "current_file": progress.current_member,
                        "checkpoint_saves": checkpoint_saves,
                        "heartbeat_writes": heartbeat_writes,
                        "cancel_checks": cancel_checks,
                    }
                    live_state.clear()
                    live_state.update(state)
                    now = time.monotonic()
                    completed_delta = progress.extracted_files - last_checkpoint_files
                    final_member = (
                        progress.completed_member is not None
                        and progress.declared_files > 0
                        and progress.extracted_files >= progress.declared_files
                    )
                    due = (
                        progress.completed_member is not None
                        and (
                            completed_delta >= checkpoint_members
                            or now - last_checkpoint_at >= checkpoint_seconds
                            or final_member
                        )
                    )
                    if due:
                        checkpoint_saves += 1
                        state["checkpoint_saves"] = checkpoint_saves
                        context.save_checkpoint({"stage": "extracting", "zip_import": state})
                        last_checkpoint_files = progress.extracted_files
                        last_checkpoint_at = now
                    emit_heartbeat(progress, now, force=final_member)
                    return not poll_cancel(now, force=final_member)

                now = time.monotonic()
                if poll_cancel(now, force=True):
                    return TaskStatus.CANCELLED, None
                report = extract_server_zip(
                    archive,
                    root,
                    target_prefix,
                    task_id=context.task.task_id,
                    completed=completed,
                    on_progress=on_extract,
                )
                state = {
                    "zip_path": zip_path,
                    "target_prefix": target_prefix,
                    "published": True,
                    "completed_members": {
                        name: asdict(record) for name, record in report.members.items()
                    },
                    "extracted_files": report.extracted_files,
                    "extracted_bytes": report.extracted_bytes,
                    "declared_files": report.extracted_files,
                    "declared_bytes": report.extracted_bytes,
                    "current_file": "",
                    "checkpoint_saves": checkpoint_saves,
                    "heartbeat_writes": heartbeat_writes,
                    "cancel_checks": cancel_checks,
                }
                context.save_checkpoint({"stage": "published", "zip_import": state})
                finalize_server_zip_publication(
                    root, target_prefix, task_id=context.task.task_id,
                )

            scan_request = dict(request)
            scan_request["prefix"] = target_prefix
            scan_request["recursive"] = bool(request.get("recursive", True))
            return self._scan(context, scan_request)
        except ExtractionCancelled as error:
            return TaskStatus.CANCELLED, self._zip_error(context, error, live_state)
        except ServerZipImportError as error:
            return TaskStatus.FAILED, self._zip_error(context, error, live_state)


def worker_registration(data_dir: Path):
    # Keep label-remap registration from the storage role while swapping only
    # MATERIAL_IMPORT to the scale-safe handler.
    from platform_core.label_remap_tasks import LabelRemapHandler

    return {
        "handlers": {
            TaskKind.MATERIAL_IMPORT: OptimizedStorageImportHandler(data_dir),
            TaskKind.LABEL_REMAP: LabelRemapHandler(data_dir),
        },
        "capabilities": {
            "storage.import",
            "storage.rescan",
            "storage.label_remap",
        },
    }
