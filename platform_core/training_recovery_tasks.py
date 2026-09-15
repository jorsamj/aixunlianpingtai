from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import training_tasks as base
from .task_runtime import TaskKind
from .training_hardened_tasks import (
    HardenedLabelContractTrainingHandler,
    _best_checkpoint,
    _run_checkpoint_validation,
)
from .training_label_tasks import _install_scoped_training_hooks


_RECOVERABLE_STAGES = {"final_validation", "post_training"}


def _explicit_checkpoint_retry(context) -> bool:
    retry_of = str(getattr(context.task, "retry_of", None) or "").strip()
    return bool(retry_of)


def _trusted_retry_candidate(context, data_dir: Path) -> dict[str, Any] | None:
    """Resolve an old completed-training checkpoint without mutating task state.

    Recovery is deliberately restricted to an explicit retry of a terminal task.
    Lease recovery or an unrelated rerun must never consume stale failure
    evidence.  Snapshot, portable bundle and checkpoint hash are all verified
    before the expensive final validator is allowed to start.
    """

    if not _explicit_checkpoint_retry(context):
        return None

    failure = context.artifacts.read_json(context.task.task_id, "failure.json", default={})
    if not isinstance(failure, Mapping):
        return None
    if str(failure.get("task_id") or "") != str(context.task.task_id):
        return None
    if str(failure.get("project_id") or "") != str(context.task.project_id):
        return None
    if str(failure.get("failure_stage") or "") not in _RECOVERABLE_STAGES:
        return None
    if failure.get("training_loop_completed") is not True or failure.get("recoverable") is not True:
        return None

    checkpoint = _best_checkpoint(failure)
    if checkpoint is None:
        return None

    project = (Path(data_dir) / "projects" / context.task.project_id).resolve()
    job_file = project / "jobs" / context.task.task_id / "job.json"
    job = base._json(job_file, {})
    if not isinstance(job, Mapping) or not job:
        return None

    snapshot = context.artifacts.read_json(context.task.task_id, "snapshot.json", default={})
    if not isinstance(snapshot, Mapping):
        return None
    snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
    if not snapshot_id or str(job.get("snapshot_id") or "").strip() != snapshot_id:
        return None

    manifest_path = context.artifacts.artifact_path(
        context.task.task_id,
        "work/bundle/manifest.json",
    )
    try:
        verification = base.verify_portable_dataset(manifest_path)
    except Exception:
        return None
    if str(verification.get("snapshot_id") or "").strip() != snapshot_id:
        return None

    runtime_yaml = context.artifacts.artifact_path(
        context.task.task_id,
        "work/runtime-data.yaml",
    )
    if not runtime_yaml.is_file() or runtime_yaml.stat().st_size <= 0:
        return None

    checkpoint_path = Path(str(checkpoint.get("path") or "")).resolve()
    runs_root = (project / "runs").resolve()
    try:
        checkpoint_path.relative_to(runs_root)
    except ValueError:
        return None
    if checkpoint_path.parent.name != "weights" or not checkpoint_path.is_file():
        return None
    if checkpoint_path.stat().st_size <= 0:
        return None
    expected_sha = str(checkpoint.get("sha256") or "").strip()
    if not expected_sha or base._sha256(checkpoint_path) != expected_sha:
        return None

    assignment = context.artifacts.read_json(context.task.task_id, "assignment.json", default={})
    if not isinstance(assignment, Mapping):
        return None
    if assignment.get("lease_token") != context.lease.lease_token:
        return None
    if assignment.get("worker_id") != context.lease.worker_id:
        return None
    assigned_device = str(assignment.get("assigned_device") or "").strip()
    if not assigned_device:
        return None

    resource_context_ref = "recovery-resource-context.json"
    context.artifacts.atomic_write_json(
        context.task.task_id,
        resource_context_ref,
        {
            "gpu_uuid": assignment.get("gpu_uuid"),
            "reserved_bytes": assignment.get("reserved_bytes"),
            "recovery": True,
        },
    )

    payload = context.artifacts.read_json(
        context.task.task_id,
        context.task.payload_ref,
        default={},
    )
    if not isinstance(payload, Mapping):
        return None

    run_name = checkpoint_path.parent.parent.name
    training_argv = [
        base._training_python(Path(data_dir)),
        str(Path(__file__).resolve().parent.parent / "train_worker_safe.py"),
        "--project-dir",
        str(project),
        "--data",
        str(runtime_yaml),
        "--run-name",
        run_name,
        "--epochs",
        str(int(job.get("requested_epochs") or job.get("total_epochs") or job.get("epochs") or payload.get("epochs") or 0)),
        "--imgsz",
        str(int(job.get("imgsz") or payload.get("imgsz") or 640)),
        "--assigned-device",
        assigned_device,
        "--resource-context",
        str(context.artifacts.artifact_path(context.task.task_id, resource_context_ref)),
        "--val-max-samples",
        str(int(payload.get("val_max_samples") or 0)),
    ]

    return {
        "failure": dict(failure),
        "project": project,
        "job_file": job_file,
        "job": dict(job),
        "snapshot_id": snapshot_id,
        "payload": dict(payload),
        "training_argv": training_argv,
    }


class RecoveryHardenedLabelContractTrainingHandler(HardenedLabelContractTrainingHandler):
    """Add explicit checkpoint-only retry on top of the hardened training owner."""

    def recover(self, context):
        committed = self._committed(context)
        if committed:
            return super().recover(context)

        candidate = _trusted_retry_candidate(context, self.data_dir)
        if candidate is None:
            return super().recover(context)

        project = candidate["project"]
        job = _run_checkpoint_validation(
            context=context,
            training_argv=candidate["training_argv"],
            job_file=candidate["job_file"],
            expected_snapshot_id=candidate["snapshot_id"],
            expected_models_root=project / "models",
            checkpoint_evidence=candidate["failure"],
            recovery=True,
        )
        outcome = self._finalize_completed_job(
            context,
            candidate["payload"],
            project,
            job,
            recovered=True,
        )

        contract = context.artifacts.read_json(
            context.task.task_id,
            "label-contract.json",
            default={},
        )
        if isinstance(contract, Mapping) and contract:
            self._persist_result_contract(context, project, contract)
        return outcome


def worker_registration(data_dir: Path):
    _install_scoped_training_hooks()
    return {
        "handlers": {
            TaskKind.TRAINING: RecoveryHardenedLabelContractTrainingHandler(data_dir),
        },
        "capabilities": {"training.ultralytics"},
    }
