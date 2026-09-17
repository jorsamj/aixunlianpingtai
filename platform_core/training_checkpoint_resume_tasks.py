from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import training_recovery_tasks as recovery
from . import training_tasks as base
from .task_runtime import TaskKind
from .training_label_tasks import _install_scoped_training_hooks


RESUME_MODE = "training_checkpoint_resume"
RESUME_STAGE = "resuming_training"


def _result_csv_epoch(run_dir: Path) -> int:
    path = run_dir / "results.csv"
    try:
        lines = [line for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    except OSError:
        return 0
    return max(0, len(lines) - 1)


def _job_epoch(job: Mapping[str, Any]) -> int:
    progress = job.get("training_progress") if isinstance(job.get("training_progress"), Mapping) else {}
    return base._completion_int(job.get("current_epoch"), progress.get("epoch"), job.get("completed_epochs"))


def _requested_epochs(job: Mapping[str, Any], payload: Mapping[str, Any]) -> int:
    progress = job.get("training_progress") if isinstance(job.get("training_progress"), Mapping) else {}
    return base._completion_int(
        job.get("requested_epochs"),
        progress.get("total_epochs"),
        job.get("total_epochs"),
        job.get("epochs"),
        payload.get("epochs"),
    )


def _resume_rejection(reason: str, **evidence: Any) -> dict[str, Any]:
    return {"eligible": False, "reason": str(reason), **evidence}


def inspect_training_resume_candidate(context, data_dir: Path) -> dict[str, Any]:
    """Return evidence for same-task Ultralytics last.pt resume admission.

    This is intentionally different from the existing final-validation retry.
    It only admits a lease-recovered durable task whose training loop did not
    finish. The task-local Snapshot, portable bundle, runtime YAML, job identity,
    checkpoint path/hash and the *new* Scheduler assignment must all agree.
    """

    if str(getattr(context.task, "retry_of", None) or "").strip():
        return _resume_rejection("explicit_retry_uses_existing_recovery_contract")
    if int(getattr(context.task, "attempt", 0) or 0) <= 1:
        return _resume_rejection("task_has_not_been_reclaimed")

    project = (Path(data_dir) / "projects" / context.task.project_id).resolve()
    job_file = project / "jobs" / context.task.task_id / "job.json"
    job = base._json(job_file, {})
    if not isinstance(job, Mapping) or not job:
        return _resume_rejection("job_state_missing")
    if str(job.get("task_id") or job.get("id") or "") != str(context.task.task_id):
        return _resume_rejection("job_identity_mismatch")
    if str(job.get("status") or "").lower() == "done":
        return _resume_rejection("training_already_done")
    if job.get("training_loop_completed") is True:
        return _resume_rejection("training_loop_already_completed")
    if str(job.get("failure_stage") or "") in {"post_training", "final_validation"}:
        return _resume_rejection("post_training_failure_uses_validation_recovery")
    if job.get("ai_continuation") and str(job.get("recovery_state") or "") != "training":
        return _resume_rejection("ai_continuation_resume_requires_explicit_recovery")

    payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
    if not isinstance(payload, Mapping):
        return _resume_rejection("task_payload_missing")
    snapshot = context.artifacts.read_json(context.task.task_id, "snapshot.json", default={})
    if not isinstance(snapshot, Mapping):
        return _resume_rejection("snapshot_missing")
    snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
    if not snapshot_id or str(job.get("snapshot_id") or "").strip() != snapshot_id:
        return _resume_rejection("snapshot_identity_mismatch")

    manifest_path = context.artifacts.artifact_path(context.task.task_id, "work/bundle/manifest.json")
    try:
        verification = base._verify_materialized_dataset_evidence(manifest_path)
    except Exception as error:
        return _resume_rejection("portable_bundle_verification_failed", detail=str(error))
    if str(verification.get("snapshot_id") or "") != snapshot_id:
        return _resume_rejection("portable_bundle_snapshot_mismatch")

    runtime_yaml = context.artifacts.artifact_path(context.task.task_id, "work/runtime-data.yaml")
    if not runtime_yaml.is_file() or runtime_yaml.stat().st_size <= 0:
        return _resume_rejection("runtime_yaml_missing")

    run_name = f"train_{context.task.task_id}"
    runs_root = (project / "runs").resolve()
    run_dir = (runs_root / run_name).resolve()
    try:
        run_dir.relative_to(runs_root)
    except ValueError:
        return _resume_rejection("run_path_invalid")
    checkpoint = (run_dir / "weights" / "last.pt").resolve()
    if not checkpoint.is_file() or checkpoint.stat().st_size <= 0:
        return _resume_rejection("last_checkpoint_missing")

    completed = max(_job_epoch(job), _result_csv_epoch(run_dir))
    requested = _requested_epochs(job, payload)
    if completed <= 0:
        return _resume_rejection("no_completed_epoch_evidence")
    if requested <= 0 or completed >= requested:
        return _resume_rejection(
            "checkpoint_is_not_incomplete_training",
            completed_epochs=completed,
            requested_epochs=requested,
        )

    assignment = context.artifacts.read_json(context.task.task_id, "assignment.json", default={})
    if not isinstance(assignment, Mapping):
        return _resume_rejection("scheduler_assignment_missing")
    if assignment.get("lease_token") != context.lease.lease_token:
        return _resume_rejection("scheduler_assignment_stale")
    if assignment.get("worker_id") != context.lease.worker_id:
        return _resume_rejection("scheduler_worker_mismatch")
    assigned_device = str(assignment.get("assigned_device") or "").strip()
    if not assigned_device:
        return _resume_rejection("scheduler_device_missing")

    old_resource_context = context.artifacts.read_json(
        context.task.task_id,
        "resource-context.json",
        default={},
    )
    resource_context = dict(old_resource_context) if isinstance(old_resource_context, Mapping) else {}
    resource_context.update(
        gpu_uuid=assignment.get("gpu_uuid"),
        reserved_bytes=assignment.get("reserved_bytes"),
        recovery=True,
        recovery_mode=RESUME_MODE,
    )
    resource_context_ref = "resume-resource-context.json"
    context.artifacts.atomic_write_json(context.task.task_id, resource_context_ref, resource_context)

    checkpoint_sha = base._sha256(checkpoint)
    requested_device = str(payload.get("requested_device", payload.get("device", "auto")))
    python = base._training_python(Path(data_dir))
    argv = [
        python,
        str(Path(__file__).resolve().parent.parent / "train_checkpoint_resume_worker.py"),
        "--project-dir",
        str(project),
        "--data",
        str(runtime_yaml),
        "--run-name",
        run_name,
        "--job-id",
        context.task.task_id,
        "--snapshot-id",
        snapshot_id,
        "--resume-checkpoint",
        str(checkpoint),
        "--resume-checkpoint-sha256",
        checkpoint_sha,
        "--resume-from-epoch",
        str(completed),
        "--epochs",
        str(requested),
        "--imgsz",
        str(int(job.get("imgsz") or payload.get("imgsz") or 640)),
        "--assigned-device",
        assigned_device,
        "--requested-device",
        requested_device,
        "--resource-context",
        str(context.artifacts.artifact_path(context.task.task_id, resource_context_ref)),
        "--resource-resolution",
        str(context.artifacts.artifact_path(context.task.task_id, "resolved-resources.json")),
        "--metrics-db",
        str(context.artifacts.artifact_path(context.task.task_id, "training-metrics.sqlite3")),
        "--val-max-samples",
        str(int(payload.get("val_max_samples") or 0)),
    ]
    return {
        "eligible": True,
        "reason": "trusted_last_checkpoint",
        "project": project,
        "job_file": job_file,
        "job": dict(job),
        "payload": dict(payload),
        "snapshot_id": snapshot_id,
        "run_name": run_name,
        "resume_from_epoch": completed,
        "requested_epochs": requested,
        "checkpoint_path": checkpoint,
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_size_bytes": checkpoint.stat().st_size,
        "assigned_device": assigned_device,
        "argv": argv,
        "verification": dict(verification),
    }


def _publish_resume_admission(context, candidate: Mapping[str, Any]) -> None:
    context.artifacts.atomic_write_json(
        context.task.task_id,
        "checkpoint-resume.json",
        {
            "schema_version": 1,
            "task_id": context.task.task_id,
            "project_id": context.task.project_id,
            "mode": RESUME_MODE,
            "eligible": True,
            "resume_from_epoch": int(candidate["resume_from_epoch"]),
            "requested_epochs": int(candidate["requested_epochs"]),
            "checkpoint": {
                "filename": Path(candidate["checkpoint_path"]).name,
                "path": str(candidate["checkpoint_path"]),
                "sha256": str(candidate["checkpoint_sha256"]),
                "size_bytes": int(candidate["checkpoint_size_bytes"]),
            },
            "snapshot_id": str(candidate["snapshot_id"]),
            "assigned_device": str(candidate["assigned_device"]),
            "verification_mode": str((candidate.get("verification") or {}).get("verification_mode") or ""),
        },
    )


def _mark_resume_job(candidate: Mapping[str, Any]) -> None:
    job = dict(candidate["job"])
    job.update(
        status="running",
        recovery_mode=RESUME_MODE,
        recovery_state="admitted",
        recovery_auto=True,
        recovery_attempted=True,
        recovery_completed=False,
        recovery_error=None,
        resume_from_epoch=int(candidate["resume_from_epoch"]),
        requested_epochs=int(candidate["requested_epochs"]),
        assigned_device=str(candidate["assigned_device"]),
        checkpoint_available=True,
        current_item=f"从 Epoch {int(candidate['resume_from_epoch'])} 恢复训练",
        message=(
            f"Worker 已接管中断任务，将从可信 last.pt 的 Epoch "
            f"{int(candidate['resume_from_epoch'])}/{int(candidate['requested_epochs'])} 继续训练"
        ),
    )
    base.atomic_write_json(Path(candidate["job_file"]), job)


class CheckpointResumeRecoveryHandler(recovery.RecoveryHardenedLabelContractTrainingHandler):
    """Add same-task training-loop resume without changing final-validation retry."""

    def recover(self, context):
        committed = self._committed(context)
        if committed:
            return super().recover(context)

        # Keep the already-CLOSED explicit final-validation recovery contract as
        # the first owner for retry tasks.
        if recovery._trusted_retry_candidate(context, self.data_dir) is not None:
            return super().recover(context)

        candidate = inspect_training_resume_candidate(context, self.data_dir)
        if not candidate.get("eligible"):
            context.artifacts.atomic_write_json(
                context.task.task_id,
                "checkpoint-resume.json",
                {
                    "schema_version": 1,
                    "task_id": context.task.task_id,
                    "project_id": context.task.project_id,
                    "mode": RESUME_MODE,
                    "eligible": False,
                    "reason": candidate.get("reason"),
                    "detail": candidate.get("detail"),
                },
            )
            if int(getattr(context.task, "attempt", 0) or 0) > 1:
                context.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                    stage="restarting_training",
                    current_item="没有可信训练断点，按原训练配置重新执行",
                )
            return super().recover(context)

        _publish_resume_admission(context, candidate)
        _mark_resume_job(candidate)
        current_progress = max(
            20.0,
            float(candidate["job"].get("progress_percent") or 0.0),
        )
        context.repository.heartbeat(
            context.task.task_id,
            context.lease.lease_token,
            progress=min(94.0, current_progress),
            stage=RESUME_STAGE,
            current_item=(
                f"从 Epoch {int(candidate['resume_from_epoch'])}/"
                f"{int(candidate['requested_epochs'])} 恢复训练"
            ),
        )

        job = recovery._run_hardened_training_process_with_reconciliation(
            context,
            candidate["argv"],
            Path(candidate["job_file"]),
        )
        finished_job = dict(job)
        finished_job.update(
            recovery_mode=RESUME_MODE,
            recovery_state="completed",
            recovery_auto=True,
            recovery_attempted=True,
            recovery_completed=True,
            recovery_error=None,
            resume_from_epoch=int(candidate["resume_from_epoch"]),
        )
        base.atomic_write_json(Path(candidate["job_file"]), finished_job)

        outcome = self._finalize_completed_job(
            context,
            candidate["payload"],
            candidate["project"],
            finished_job,
            recovered=True,
        )
        contract = context.artifacts.read_json(
            context.task.task_id,
            "label-contract.json",
            default={},
        )
        if isinstance(contract, Mapping) and contract:
            self._persist_result_contract(context, candidate["project"], contract)
        return outcome


def worker_registration(data_dir: Path):
    _install_scoped_training_hooks()
    return {
        "handlers": {TaskKind.TRAINING: CheckpointResumeRecoveryHandler(data_dir)},
        "capabilities": {"training.ultralytics"},
    }
