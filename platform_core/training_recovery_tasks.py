from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from . import training_hardened_tasks as hardened
from . import training_tasks as base
from .task_runtime import TaskKind
from .training_hardened_tasks import (
    HardenedLabelContractTrainingHandler,
    _best_checkpoint,
)
from .training_label_tasks import _install_scoped_training_hooks


_RECOVERABLE_STAGES = {"final_validation", "post_training"}
_FALSE_FINAL_VALIDATION_HANDSHAKE = (
    "final validation process exited without a trusted completion handshake"
)


def _explicit_checkpoint_retry(context) -> bool:
    retry_of = str(getattr(context.task, "retry_of", None) or "").strip()
    return bool(retry_of)


def _trusted_retry_candidate(context, data_dir: Path) -> dict[str, Any] | None:
    """Resolve an old completed-training checkpoint without mutating task state.

    Recovery is deliberately restricted to an explicit retry of a terminal task.
    Lease recovery or an unrelated rerun must never consume stale failure
    evidence. Snapshot, portable bundle and checkpoint hash are all verified
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
    )
    resource_context_ref = "recovery-resource-context.json"
    context.artifacts.atomic_write_json(
        context.task.task_id,
        resource_context_ref,
        resource_context,
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


def _clear_recovered_failure_state(job_file: Path, job: Mapping[str, Any]) -> dict[str, Any]:
    recovered = dict(job)
    recovered.update(
        failed_at=None,
        failure_stage=None,
        process_returncode=0,
        process_signal=None,
        completion_error=None,
        failure_ref=None,
        checkpoint_available=True,
        recoverable=False,
        recovery_action=None,
        recovery_action_available=False,
        recovery_attempted=True,
        recovery_completed=True,
        recovery_returncode=0,
        recovery_signal=None,
        recovery_error=None,
    )
    base.atomic_write_json(job_file, recovered)
    return recovered


def _resolved_paths(values: Sequence[Any] | None) -> set[str]:
    result: set[str] = set()
    for value in values or ():
        if isinstance(value, Mapping):
            value = value.get("path") or value.get("stored_path") or value.get("source")
        raw = str(value or "").strip()
        if raw:
            result.add(str(Path(raw).resolve()))
    return result


def _reconcile_successful_final_validation(
    *,
    job_file: Path,
    expected_task_id: str,
    expected_snapshot_id: str,
    expected_models_root: Path,
    checkpoint_evidence: Mapping[str, Any],
    expected_recovery: bool,
) -> dict[str, Any] | None:
    """Repair only the mutable job status after a proven successful validator.

    The isolated validator writes ``job.json`` to ``done`` first and then writes
    ``final-validation.json`` with ``success=true`` before exiting 0. Production
    showed one cross-process visibility/overwrite race where the parent observed
    every final job field except the terminal status and then persisted FAILED.

    Treat the immutable validation result as a completion fence only when task,
    snapshot, checkpoint hash and published model paths all match. The repaired
    job must still pass the existing trusted completion contract; otherwise the
    failure remains a failure.
    """

    result_path = job_file.parent / "final-validation.json"
    result = base._json(result_path, {})
    if not isinstance(result, Mapping) or result.get("success") is not True:
        return None
    if str(result.get("task_id") or "") != str(expected_task_id):
        return None
    if str(result.get("snapshot_id") or "") != str(expected_snapshot_id):
        return None
    if bool(result.get("recovery")) is not bool(expected_recovery):
        return None

    checkpoint = _best_checkpoint(checkpoint_evidence)
    if checkpoint is None:
        return None
    checkpoint_path = Path(str(checkpoint.get("path") or "")).resolve()
    checkpoint_sha = str(checkpoint.get("sha256") or "").strip()
    if not checkpoint_path.is_file() or checkpoint_path.stat().st_size <= 0:
        return None
    if not checkpoint_sha or base._sha256(checkpoint_path) != checkpoint_sha:
        return None
    if str(Path(str(result.get("checkpoint") or "")).resolve()) != str(checkpoint_path):
        return None
    if str(result.get("checkpoint_sha256") or "") != checkpoint_sha:
        return None

    models_root = expected_models_root.resolve()
    published = _resolved_paths(result.get("published_models") or [])
    if not published:
        return None
    for raw in published:
        path = Path(raw).resolve()
        try:
            path.relative_to(models_root)
        except ValueError:
            return None
        if not path.is_file() or path.stat().st_size <= 0:
            return None

    job = base._json(job_file, {})
    if not isinstance(job, Mapping) or not job:
        return None
    verified = _resolved_paths(job.get("verified_models") or [])
    if verified != published:
        return None

    repaired = dict(job)
    repaired.update(
        status="done",
        message="训练完成，最终验证通过",
        current_item="最终验证完成",
        progress_percent=100,
        failed_at=None,
        failure_stage=None,
        process_returncode=0,
        process_signal=None,
        completion_error=None,
        failure_ref=None,
        checkpoint_available=True,
        recoverable=False,
        recovery_action=None,
        recovery_action_available=False,
        recovery_attempted=bool(expected_recovery),
        recovery_completed=bool(expected_recovery),
        recovery_returncode=0 if expected_recovery else None,
        recovery_signal=None,
        recovery_error=None,
    )
    if base._training_completion_error(
        repaired,
        expected_task_id=expected_task_id,
        expected_snapshot_id=expected_snapshot_id,
        expected_models_root=models_root,
    ) is not None:
        return None

    base.atomic_write_json(job_file, repaired)
    reread = base._json(job_file, {})
    if not isinstance(reread, Mapping):
        return None
    if base._training_completion_error(
        reread,
        expected_task_id=expected_task_id,
        expected_snapshot_id=expected_snapshot_id,
        expected_models_root=models_root,
    ) is not None:
        return None
    return dict(reread)


def _write_reconciliation_evidence(context, snapshot_id: str, *, recovery: bool, reused: bool) -> None:
    context.artifacts.atomic_write_json(
        context.task.task_id,
        "final-validation-reconciliation.json",
        {
            "schema_version": 1,
            "task_id": context.task.task_id,
            "snapshot_id": snapshot_id,
            "recovery": bool(recovery),
            "reused_existing_success": bool(reused),
            "reason": (
                "reused an already-successful trusted final-validation manifest"
                if reused
                else "validator succeeded but parent observed a stale/non-terminal job status"
            ),
        },
    )


def _run_checkpoint_validation_with_reconciliation(
    *,
    context,
    training_argv: Sequence[str],
    job_file: Path,
    expected_snapshot_id: str,
    expected_models_root: Path,
    checkpoint_evidence: Mapping[str, Any],
    recovery: bool,
) -> dict[str, Any]:
    try:
        return hardened._run_checkpoint_validation(
            context=context,
            training_argv=training_argv,
            job_file=job_file,
            expected_snapshot_id=expected_snapshot_id,
            expected_models_root=expected_models_root,
            checkpoint_evidence=checkpoint_evidence,
            recovery=recovery,
        )
    except RuntimeError as error:
        if _FALSE_FINAL_VALIDATION_HANDSHAKE not in str(error):
            raise
        repaired = _reconcile_successful_final_validation(
            job_file=job_file,
            expected_task_id=context.task.task_id,
            expected_snapshot_id=expected_snapshot_id,
            expected_models_root=expected_models_root,
            checkpoint_evidence=checkpoint_evidence,
            expected_recovery=recovery,
        )
        if repaired is None:
            raise
        _write_reconciliation_evidence(
            context,
            expected_snapshot_id,
            recovery=recovery,
            reused=False,
        )
        return repaired


def _run_hardened_training_process_with_reconciliation(context, argv: Sequence[str], job_file: Path) -> dict[str, Any]:
    try:
        return hardened.run_hardened_training_process(context, argv, job_file)
    except RuntimeError as error:
        if _FALSE_FINAL_VALIDATION_HANDSHAKE not in str(error):
            raise

        snapshot = context.artifacts.read_json(context.task.task_id, "snapshot.json", default={})
        failure = context.artifacts.read_json(context.task.task_id, "failure.json", default={})
        if not isinstance(snapshot, Mapping) or not isinstance(failure, Mapping):
            raise
        snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise
        result = base._json(job_file.parent / "final-validation.json", {})
        if not isinstance(result, Mapping):
            raise
        repaired = _reconcile_successful_final_validation(
            job_file=job_file,
            expected_task_id=context.task.task_id,
            expected_snapshot_id=snapshot_id,
            expected_models_root=job_file.parents[2] / "models",
            checkpoint_evidence=failure,
            expected_recovery=bool(result.get("recovery")),
        )
        if repaired is None:
            raise
        _write_reconciliation_evidence(
            context,
            snapshot_id,
            recovery=bool(result.get("recovery")),
            reused=False,
        )
        return repaired


class RecoveryHardenedLabelContractTrainingHandler(HardenedLabelContractTrainingHandler):
    """Hardened training plus explicit checkpoint-only retry."""

    def __init__(self, data_dir: Path):
        super().__init__(
            data_dir,
            process_runner=_run_hardened_training_process_with_reconciliation,
        )

    def recover(self, context):
        committed = self._committed(context)
        if committed:
            return super().recover(context)

        candidate = _trusted_retry_candidate(context, self.data_dir)
        if candidate is None:
            return super().recover(context)

        project = candidate["project"]
        job = _reconcile_successful_final_validation(
            job_file=candidate["job_file"],
            expected_task_id=context.task.task_id,
            expected_snapshot_id=candidate["snapshot_id"],
            expected_models_root=project / "models",
            checkpoint_evidence=candidate["failure"],
            expected_recovery=True,
        )
        if job is not None:
            _write_reconciliation_evidence(
                context,
                candidate["snapshot_id"],
                recovery=True,
                reused=True,
            )
        else:
            job = _run_checkpoint_validation_with_reconciliation(
                context=context,
                training_argv=candidate["training_argv"],
                job_file=candidate["job_file"],
                expected_snapshot_id=candidate["snapshot_id"],
                expected_models_root=project / "models",
                checkpoint_evidence=candidate["failure"],
                recovery=True,
            )
        job = _clear_recovered_failure_state(candidate["job_file"], job)
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
