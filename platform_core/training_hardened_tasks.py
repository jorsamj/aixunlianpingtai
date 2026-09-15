from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
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
FINAL_VALIDATION_WORKERS_ENV = "TRAINING_FINAL_VALIDATION_WORKERS"
FINAL_VALIDATION_BATCH_ENV = "TRAINING_FINAL_VALIDATION_BATCH"
DEFAULT_FINAL_VALIDATION_WORKERS = 0
DEFAULT_FINAL_VALIDATION_BATCH = 1


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


def _best_checkpoint(evidence: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for item in evidence.get("checkpoints") or []:
        if isinstance(item, Mapping) and str(item.get("kind") or "") == "best":
            return item
    return None


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


def _training_loop_checkpoint_ready(
    *,
    argv: Sequence[str],
    job_file: Path,
    job: Mapping[str, Any],
    log_path: Path,
) -> dict[str, Any] | None:
    """Return durable checkpoint evidence as soon as Ultralytics finishes its train loop.

    Ultralytics logs ``N epochs completed in`` immediately before its extra
    best-checkpoint final validation.  The parent Worker uses that durable marker
    plus a hashed best.pt to stop the long-lived training process before the
    high-shared-memory final validation can run in the same process lifetime.
    """

    tail = _tail_text(log_path)
    if "epochs completed in" not in tail.lower():
        return None
    checkpoints = _checkpoint_evidence(argv, job_file)
    if not any(str(item.get("kind") or "") == "best" for item in checkpoints):
        return None
    completed_epochs, requested_epochs = _epoch_evidence(job, argv, tail)
    if completed_epochs <= 0:
        return None
    return {
        "completed_epochs": completed_epochs,
        "requested_epochs": requested_epochs,
        "training_loop_completed": True,
        "checkpoint_available": True,
        "checkpoints": checkpoints,
    }


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
    has_best = any(str(item.get("kind") or "") == "best" for item in checkpoints)
    training_loop_completed = bool(
        completed_epochs > 0
        and "epochs completed in" in tail.lower()
        and has_best
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
    recoverable = bool(training_loop_completed and has_best)
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
        "recovery_action_available": recoverable,
        "recovery_note": (
            "Checkpoint evidence is preserved and can be revalidated in an isolated low-memory process."
            if recoverable
            else None
        ),
        "log_tail": tail[-16384:] if tail else "",
    }


def _failure_message(evidence: Mapping[str, Any]) -> str:
    returncode = evidence.get("process_returncode")
    process_signal = evidence.get("process_signal")
    stage = str(evidence.get("failure_stage") or "")
    process_label = "final validation process" if stage == "final_validation" and evidence.get("recovery_attempted") else "training process"
    if process_signal:
        primary = f"{process_label} terminated by {process_signal} (returncode={returncode})"
    elif returncode not in (None, 0):
        primary = f"{process_label} exited with returncode={returncode}"
    else:
        primary = f"{process_label} exited without a trusted completion handshake"
    details = [
        f"stage={evidence.get('failure_stage')}",
        f"completion_handshake={evidence.get('completion_error')}",
        f"checkpoint_available={str(bool(evidence.get('checkpoint_available'))).lower()}",
        f"recoverable={str(bool(evidence.get('recoverable'))).lower()}",
    ]
    if evidence.get("recoverable"):
        details.append("recovery_action=revalidate_checkpoint")
    if evidence.get("recovery_attempted"):
        details.append("recovery_attempted=true")
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
        recovery_action_available=evidence.get("recovery_action_available"),
        recovery_attempted=evidence.get("recovery_attempted"),
        recovery_returncode=evidence.get("recovery_returncode"),
        recovery_signal=evidence.get("recovery_signal"),
        recovery_error=evidence.get("recovery_error"),
        failure_ref="failure.json",
        message=_failure_message(evidence),
    )
    base.atomic_write_json(job_file, updated)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def final_validation_resource_profile() -> dict[str, Any]:
    return {
        "workers": _env_int(
            FINAL_VALIDATION_WORKERS_ENV,
            DEFAULT_FINAL_VALIDATION_WORKERS,
            minimum=0,
            maximum=8,
        ),
        "batch": _env_int(
            FINAL_VALIDATION_BATCH_ENV,
            DEFAULT_FINAL_VALIDATION_BATCH,
            minimum=1,
            maximum=64,
        ),
        "cache": False,
        "reason": "isolated final checkpoint validation",
    }


def build_checkpoint_validation_argv(
    *,
    training_argv: Sequence[str],
    job_file: Path,
    task_id: str,
    snapshot_id: str,
    checkpoint: Mapping[str, Any],
    recovery: bool,
    profile: Mapping[str, Any] | None = None,
) -> list[str]:
    root = Path(__file__).resolve().parent.parent
    script = root / "checkpoint_validation_worker.py"
    if not script.is_file():
        raise FileNotFoundError("checkpoint validation worker is missing")
    runtime = dict(profile or final_validation_resource_profile())
    project_dir = str(job_file.parents[2])
    python = str(training_argv[0]) if training_argv else sys.executable
    data = _argv_value(training_argv, "--data")
    run_name = _argv_value(training_argv, "--run-name") or f"train_{task_id}"
    assigned_device = _argv_value(training_argv, "--assigned-device") or _argv_value(training_argv, "--device") or "cpu"
    if not data:
        raise ValueError("training data path is missing from the durable training command")
    argv = [
        python,
        str(script),
        "--project-dir",
        project_dir,
        "--data",
        data,
        "--task-id",
        task_id,
        "--snapshot-id",
        snapshot_id,
        "--run-name",
        run_name,
        "--checkpoint",
        str(checkpoint.get("path") or ""),
        "--checkpoint-sha256",
        str(checkpoint.get("sha256") or ""),
        "--assigned-device",
        assigned_device,
        "--imgsz",
        str(_argv_value(training_argv, "--imgsz") or 640),
        "--batch",
        str(runtime["batch"]),
        "--workers",
        str(runtime["workers"]),
        "--val-max-samples",
        str(_argv_value(training_argv, "--val-max-samples") or 0),
        "--requested-epochs",
        str(_argv_value(training_argv, "--epochs") or 0),
    ]
    resource_context = _argv_value(training_argv, "--resource-context")
    if resource_context:
        argv.extend(["--resource-context", resource_context])
    if recovery:
        argv.append("--recovery")
    return argv


def _validation_failure_evidence(
    *,
    context,
    base_evidence: Mapping[str, Any],
    returncode: int | None,
    completion_error: str,
    validation_result: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = dict(base_evidence)
    evidence.update(
        schema_version=_FAILURE_SCHEMA_VERSION,
        task_id=str(context.task.task_id),
        project_id=str(context.task.project_id),
        failed_at=datetime.now(timezone.utc).isoformat(),
        failure_stage="final_validation",
        process_returncode=returncode,
        process_signal=_process_signal(returncode),
        completion_error=str(completion_error),
        checkpoint_available=bool(base_evidence.get("checkpoints")),
        recoverable=bool(_best_checkpoint(base_evidence)),
        recovery_action="revalidate_checkpoint" if _best_checkpoint(base_evidence) else None,
        recovery_action_available=bool(_best_checkpoint(base_evidence)),
        recovery_attempted=True,
        recovery_returncode=returncode,
        recovery_signal=_process_signal(returncode),
        recovery_error=str(validation_result.get("error") or completion_error),
        final_validation_result=dict(validation_result),
    )
    return evidence


def _run_checkpoint_validation(
    *,
    context,
    training_argv: Sequence[str],
    job_file: Path,
    expected_snapshot_id: str,
    expected_models_root: Path,
    checkpoint_evidence: Mapping[str, Any],
    recovery: bool,
) -> dict[str, Any]:
    checkpoint = _best_checkpoint(checkpoint_evidence)
    if checkpoint is None:
        raise RuntimeError("trusted best.pt checkpoint is unavailable for final validation")
    checkpoint_path = Path(str(checkpoint.get("path") or ""))
    if not checkpoint_path.is_file() or checkpoint_path.stat().st_size <= 0:
        raise RuntimeError("trusted best.pt checkpoint disappeared before final validation")
    if base._sha256(checkpoint_path) != str(checkpoint.get("sha256") or ""):
        raise RuntimeError("trusted best.pt checkpoint changed before final validation")

    profile = final_validation_resource_profile()
    argv = build_checkpoint_validation_argv(
        training_argv=training_argv,
        job_file=job_file,
        task_id=context.task.task_id,
        snapshot_id=expected_snapshot_id,
        checkpoint=checkpoint,
        recovery=recovery,
        profile=profile,
    )
    root = Path(__file__).resolve().parent.parent
    log_path = job_file.parent / "final-validation.log"
    result_path = job_file.parent / "final-validation.json"
    controller = base.ProcessController()

    context.repository.heartbeat(
        context.task.task_id,
        context.lease.lease_token,
        progress=96,
        stage="recovering_checkpoint" if recovery else "final_validation",
        current_item=("恢复 checkpoint，正在独立验证" if recovery else "训练完成，正在独立验证最佳模型"),
    )

    launched = None
    try:
        with log_path.open("a", encoding="utf-8", newline="") as log:
            launched = base.launch_process(
                argv,
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
            while launched.process.poll() is None:
                if context.cancel_requested():
                    controller.terminate_tree(launched.identity)
                    raise InterruptedError("training cancelled during final validation")
                context.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                    progress=97,
                    stage="final_validation",
                    current_item="独立验证 best.pt",
                )
                time.sleep(0.25)
    finally:
        if log_path.is_file():
            destination = context.artifacts.artifact_path(context.task.task_id, "final-validation.log")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(log_path, destination)
        if result_path.is_file():
            result = base._json(result_path, {})
            if isinstance(result, Mapping):
                context.artifacts.atomic_write_json(context.task.task_id, "final-validation.json", dict(result))

    job = base._json(job_file, {})
    if context.cancel_requested():
        raise InterruptedError("training cancelled during final validation")
    completion_error = base._training_completion_error(
        job,
        expected_task_id=context.task.task_id,
        expected_snapshot_id=expected_snapshot_id or None,
        expected_models_root=expected_models_root,
    )
    if launched is not None and launched.process.returncode == 0 and completion_error is None:
        return job

    result = base._json(result_path, {}) if result_path.is_file() else {}
    evidence = _validation_failure_evidence(
        context=context,
        base_evidence=checkpoint_evidence,
        returncode=launched.process.returncode if launched is not None else None,
        completion_error=completion_error or "final validation process failed",
        validation_result=result if isinstance(result, Mapping) else {},
    )
    _persist_failure(context, job_file, job, evidence)
    raise RuntimeError(_failure_message(evidence))


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
    controller = base.ProcessController()
    checkpoint_ready: dict[str, Any] | None = None
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
                ready = _training_loop_checkpoint_ready(
                    argv=launch_argv,
                    job_file=job_file,
                    job=job,
                    log_path=log_path,
                )
                if ready is not None:
                    checkpoint_ready = ready
                    context.repository.heartbeat(
                        context.task.task_id,
                        context.lease.lease_token,
                        progress=95,
                        stage="cleaning_training_process",
                        current_item="训练主循环完成，正在释放训练进程资源",
                    )
                    try:
                        controller.terminate_tree(launched.identity)
                    except PermissionError as error:
                        checkpoint_ready = None
                        context.repository.heartbeat(
                            context.task.task_id,
                            context.lease.lease_token,
                            progress=95,
                            stage="cleaning_training_process",
                            current_item=f"waiting for verified process cleanup: {error}",
                        )
                        time.sleep(0.25)
                        continue
                    break

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

    if checkpoint_ready is not None:
        return _run_checkpoint_validation(
            context=context,
            training_argv=launch_argv,
            job_file=job_file,
            expected_snapshot_id=expected_snapshot_id,
            expected_models_root=expected_models_root,
            checkpoint_evidence=checkpoint_ready,
            recovery=False,
        )

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
    if evidence.get("recoverable") and _best_checkpoint(evidence) is not None:
        context.artifacts.atomic_write_json(
            context.task.task_id,
            "training-process-failure.json",
            dict(evidence),
        )
        if launched is not None:
            try:
                controller.terminate_tree(launched.identity)
            except PermissionError as cleanup_error:
                evidence = dict(evidence)
                evidence["recovery_attempted"] = False
                evidence["recovery_error"] = f"old training process cleanup failed: {cleanup_error}"
                _persist_failure(context, job_file, job, evidence)
                raise RuntimeError(_failure_message(evidence)) from cleanup_error
        return _run_checkpoint_validation(
            context=context,
            training_argv=launch_argv,
            job_file=job_file,
            expected_snapshot_id=expected_snapshot_id,
            expected_models_root=expected_models_root,
            checkpoint_evidence=evidence,
            recovery=True,
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
