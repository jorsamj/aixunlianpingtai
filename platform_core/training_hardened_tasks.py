from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import training_tasks as base
from .gpu_resources import update_reservation_evidence
from .task_runtime import TaskKind
from .training_label_tasks import LabelContractTrainingHandler, _install_scoped_training_hooks


_FAILURE_SCHEMA_VERSION = 1
_LOG_TAIL_BYTES = 128 * 1024


def _argv_value(argv: Sequence[str], option: str) -> str | None:
    try:
        index = list(argv).index(option)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return str(argv[index + 1])


def _hardened_worker_argv(argv: Sequence[str]) -> list[str]:
    """Route the existing trainer through the resource-safety bootstrap only."""

    result = list(argv)
    if len(result) < 2 or Path(result[1]).name != "train_worker.py":
        return result
    safe_worker = Path(__file__).resolve().parent.parent / "train_worker_safe.py"
    if not safe_worker.is_file():
        raise FileNotFoundError("training safety bootstrap is missing: train_worker_safe.py")
    result[1] = str(safe_worker)
    return result


def _tail_text(path: Path, limit: int = _LOG_TAIL_BYTES) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - max(1024, int(limit))))
            return stream.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _checkpoint_evidence(argv: Sequence[str], job_file: Path) -> list[dict[str, Any]]:
    run_name = _argv_value(argv, "--run-name") or f"train_{job_file.parent.name}"
    project = job_file.parents[2]
    weights = project / "runs" / run_name / "weights"
    result: list[dict[str, Any]] = []
    for kind in ("best", "last"):
        path = weights / f"{kind}.pt"
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                continue
            result.append(
                {
                    "kind": kind,
                    "path": str(path.resolve()),
                    "size_bytes": path.stat().st_size,
                    "sha256": base._sha256(path),
                }
            )
        except OSError:
            continue
    return result


def _process_signal(returncode: int | None) -> str | None:
    if returncode is None or returncode >= 0 or os.name == "nt":
        return None
    try:
        return signal.Signals(-int(returncode)).name
    except (ValueError, OverflowError):
        return f"SIGNAL_{-int(returncode)}"


def _epoch_evidence(job: Mapping[str, Any], argv: Sequence[str], log_tail: str) -> tuple[int, int]:
    progress = job.get("training_progress") if isinstance(job.get("training_progress"), Mapping) else {}
    completed = base._completion_int(
        job.get("completed_epochs"),
        progress.get("epoch"),
        job.get("current_epoch"),
    )
    requested = base._completion_int(
        job.get("requested_epochs"),
        progress.get("total_epochs"),
        job.get("total_epochs"),
        job.get("epochs"),
        _argv_value(argv, "--epochs"),
    )
    matches = list(re.finditer(r"Epoch\s+(\d+)\s*/\s*(\d+)", log_tail, flags=re.IGNORECASE))
    if matches:
        completed = max(completed, int(matches[-1].group(1)))
        requested = max(requested, int(matches[-1].group(2)))
    finished = list(re.finditer(r"(\d+)\s+epochs completed in", log_tail, flags=re.IGNORECASE))
    if finished:
        completed = max(completed, int(finished[-1].group(1)))
        requested = max(requested, int(finished[-1].group(1)))
    return completed, requested


def build_training_failure_evidence(
    *,
    task_id: str,
    project_id: str,
    argv: Sequence[str],
    job_file: Path,
    job: Mapping[str, Any],
    returncode: int | None,
    completion_error: str,
    log_path: Path,
) -> dict[str, Any]:
    """Build bounded, evidence-only failure truth for a terminated trainer.

    SIGKILL is recorded as SIGKILL, not guessed to mean OOM. Kernel/cgroup logs
    remain the authority for determining whether an external kill was caused by
    host memory pressure.
    """

    tail = _tail_text(log_path)
    checkpoints = _checkpoint_evidence(argv, job_file)
    completed_epochs, requested_epochs = _epoch_evidence(job, argv, tail)
    training_loop_completed = bool(
        requested_epochs > 0
        and completed_epochs >= requested_epochs
        and "epochs completed in" in tail.lower()
    )
    final_validation_started = bool(
        training_loop_completed
        and re.search(r"\bValidating\s+.+best\.pt", tail, flags=re.IGNORECASE)
    )
    if final_validation_started:
        failure_stage = "final_validation"
    elif training_loop_completed and checkpoints:
        failure_stage = "post_training"
    else:
        failure_stage = "training_process"
    recoverable = bool(training_loop_completed and checkpoints)
    process_signal = _process_signal(returncode)
    return {
        "schema_version": _FAILURE_SCHEMA_VERSION,
        "task_id": str(task_id),
        "project_id": str(project_id),
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "failure_stage": failure_stage,
        "process_returncode": returncode,
        "process_signal": process_signal,
        "completion_error": str(completion_error),
        "last_job_message": str(job.get("message") or "").strip() or None,
        "completed_epochs": completed_epochs,
        "requested_epochs": requested_epochs,
        "training_loop_completed": training_loop_completed,
        "checkpoint_available": bool(checkpoints),
        "checkpoints": checkpoints,
        "recoverable": recoverable,
        "recovery_action": "revalidate_checkpoint" if recoverable else None,
        "recovery_action_available": False,
        "recovery_note": (
            "Checkpoint evidence is preserved. A validation-only recovery task/API must verify the checkpoint "
            "before an official algorithm version can be published."
            if recoverable
            else None
        ),
        "log_tail": tail[-16384:] if tail else "",
    }


def _failure_message(evidence: Mapping[str, Any]) -> str:
    returncode = evidence.get("process_returncode")
    process_signal = evidence.get("process_signal")
    if process_signal:
        primary = f"training process terminated by {process_signal} (returncode={returncode})"
    elif returncode not in (None, 0):
        primary = f"training process exited with returncode={returncode}"
    else:
        primary = "training process exited without a trusted completion handshake"
    details = [
        f"stage={evidence.get('failure_stage')}",
        f"completion_handshake={evidence.get('completion_error')}",
        f"checkpoint_available={str(bool(evidence.get('checkpoint_available'))).lower()}",
        f"recoverable={str(bool(evidence.get('recoverable'))).lower()}",
    ]
    if evidence.get("recoverable"):
        details.append("recovery_action=revalidate_checkpoint")
    return primary + "; " + "; ".join(details)


def _persist_failure(context, job_file: Path, job: Mapping[str, Any], evidence: Mapping[str, Any]) -> None:
    context.artifacts.atomic_write_json(context.task.task_id, "failure.json", dict(evidence))
    updated = dict(job)
    updated.update(
        status="failed",
        failed_at=evidence.get("failed_at"),
        failure_stage=evidence.get("failure_stage"),
        process_returncode=evidence.get("process_returncode"),
        process_signal=evidence.get("process_signal"),
        completion_error=evidence.get("completion_error"),
        checkpoint_available=evidence.get("checkpoint_available"),
        recoverable=evidence.get("recoverable"),
        recovery_action=evidence.get("recovery_action"),
        failure_ref="failure.json",
        message=_failure_message(evidence),
    )
    base.atomic_write_json(job_file, updated)


def run_hardened_training_process(context, argv: Sequence[str], job_file: Path) -> dict[str, Any]:
    artifact_log = context.artifacts.artifact_path(context.task.task_id, context.task.log_ref)
    artifact_log.parent.mkdir(parents=True, exist_ok=True)
    log_path = job_file.parent / "train.log"
    root = Path(__file__).resolve().parent.parent
    snapshot = context.artifacts.read_json(context.task.task_id, "snapshot.json", default={})
    expected_snapshot_id = (
        str(snapshot.get("snapshot_id") or "").strip()
        if isinstance(snapshot, Mapping)
        else ""
    )
    expected_models_root = (job_file.parent.parent.parent / "models").resolve()
    launch_argv = _hardened_worker_argv(argv)
    launched = None
    try:
        with log_path.open("a", encoding="utf-8", newline="") as log:
            launched = base.launch_process(
                launch_argv,
                cwd=root,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            context.repository.bind_process(
                context.task.task_id,
                context.lease.lease_token,
                launched.identity,
            )
            controller = base.ProcessController()
            next_metrics = 0.0
            completion_seen_at = None
            while launched.process.poll() is None:
                if context.cancel_requested():
                    try:
                        controller.terminate_tree(launched.identity)
                    except PermissionError as error:
                        context.repository.heartbeat(
                            context.task.task_id,
                            context.lease.lease_token,
                            stage="cancelling",
                            current_item=f"waiting for verified process cleanup: {error}",
                        )
                        time.sleep(0.25)
                        continue
                    raise InterruptedError("training cancelled")
                job = base._json(job_file, {})
                if base._training_completion_error(
                    job,
                    expected_task_id=context.task.task_id,
                    expected_snapshot_id=expected_snapshot_id or None,
                    expected_models_root=expected_models_root,
                ) is None:
                    completion_seen_at = completion_seen_at or time.monotonic()
                    context.repository.heartbeat(
                        context.task.task_id,
                        context.lease.lease_token,
                        progress=95,
                        stage="finalizing",
                        current_item="verified training complete; finalizing",
                    )
                    if time.monotonic() - completion_seen_at >= base.TRAINING_COMPLETION_GRACE_SECONDS:
                        try:
                            controller.terminate_tree(launched.identity)
                        except PermissionError as error:
                            context.repository.heartbeat(
                                context.task.task_id,
                                context.lease.lease_token,
                                progress=95,
                                stage="finalizing",
                                current_item=f"waiting for verified process cleanup: {error}",
                            )
                            time.sleep(0.25)
                            continue
                        break
                    time.sleep(0.1)
                    continue
                completion_seen_at = None
                current_task = context.repository.get(context.task.task_id)
                if current_task is not None and current_task.stage == "paused":
                    context.repository.heartbeat(
                        context.task.task_id,
                        context.lease.lease_token,
                        stage="paused",
                    )
                    time.sleep(0.25)
                    continue
                if time.monotonic() >= next_metrics:
                    metrics = base.read_metrics(
                        context.artifacts.artifact_path(context.task.task_id, "training-metrics.sqlite3")
                    )
                    update_reservation_evidence(context.repository, context.lease, metrics)
                    next_metrics = time.monotonic() + 5
                progress = float(job.get("progress_percent") or 20)
                current = str(job.get("current_item") or job.get("current_epoch") or "") or None
                context.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                    progress=max(20, min(95, progress)),
                    stage="training",
                    current_item=current,
                )
                time.sleep(0.25)
    finally:
        if log_path.is_file():
            shutil.copy2(log_path, artifact_log)

    job = base._json(job_file, {})
    if context.cancel_requested():
        raise InterruptedError("training cancelled")
    completion_error = base._training_completion_error(
        job,
        expected_task_id=context.task.task_id,
        expected_snapshot_id=expected_snapshot_id or None,
        expected_models_root=expected_models_root,
    )
    if completion_error is None:
        return job

    returncode = launched.process.returncode if launched is not None else None
    evidence = build_training_failure_evidence(
        task_id=context.task.task_id,
        project_id=context.task.project_id,
        argv=launch_argv,
        job_file=job_file,
        job=job,
        returncode=returncode,
        completion_error=completion_error,
        log_path=log_path,
    )
    _persist_failure(context, job_file, job, evidence)
    raise RuntimeError(_failure_message(evidence))


class HardenedLabelContractTrainingHandler(LabelContractTrainingHandler):
    pass


def worker_registration(data_dir: Path):
    _install_scoped_training_hooks()
    return {
        "handlers": {
            TaskKind.TRAINING: HardenedLabelContractTrainingHandler(
                data_dir,
                process_runner=run_hardened_training_process,
            )
        },
        "capabilities": {"training.ultralytics"},
    }
