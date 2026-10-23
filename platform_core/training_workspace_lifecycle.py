"""Task-owned training workspace retention, using the original task/artifact owners.

Only newly attested local work/bundle directories can be detached. Historical
bundles, canonical storage, shared caches, checkpoints and models are outside
this allowlist. No production scan or cleanup runs merely by importing this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from contextlib import closing
from pathlib import Path

import psutil
from filelock import FileLock

from .algorithm_sql_store import AlgorithmSqlStore
from .task_runtime.models import TaskKind, TaskStatus, utc_now
from .task_runtime.repository import TERMINAL_STATUSES
from .task_runtime.process_control import ProcessController
from .training_bundle_cache import _is_link_like, _resolve_relative


MARKER = "workspace-lifecycle.json"
RECEIPT = "workspace-cleanup.json"
EVIDENCE = "evidence/bundle"


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mark_training_workspace(artifacts, task, snapshot, input_freeze_id):
    """Called by the assigned TRAINING Worker before creating its own copy."""
    artifacts.atomic_write_json(task.task_id, MARKER, {
        "schema_version": 1, "task_id": task.task_id, "project_id": task.project_id,
        "snapshot_id": snapshot["snapshot_id"], "input_freeze_id": input_freeze_id,
        "attempt": task.attempt, "owned_paths": ["work/bundle"],
    })


class TrainingWorkspaceLifecycle:
    def __init__(self, data_dir, repository, artifacts):
        self.data_dir = Path(data_dir).resolve()
        self.repository = repository
        self.artifacts = artifacts

    def _paths(self, task_id):
        self.artifacts._validate_task_id(task_id)
        # Inspect lexical ancestors before resolve can hide junctions/symlinks.
        current = self.artifacts.root
        for part in (task_id, "work"):
            current = current / part
            if _is_link_like(current):
                raise ValueError("workspace ancestor is a link/reparse point")
        return current / "bundle", current / ".bundle-reclaim"

    @staticmethod
    def _tree_bytes(root):
        if not root.exists() and not _is_link_like(root):
            return 0
        pending, size = [root], 0
        while pending:
            path = pending.pop()
            if _is_link_like(path):
                raise ValueError("workspace contains a link/reparse point")
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                pending.extend(path.iterdir())
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                size += info.st_size
            else:
                raise ValueError("workspace contains shared or special files")
        return size

    def _model_evidence(self, task, snapshot):
        result = self.artifacts.read_json(task.task_id, task.result_ref or "result.json", default={})
        checkpoint = self.artifacts.read_json(task.task_id, "checkpoints/worker.json", default={})
        if (not isinstance(result, dict) or result.get("snapshot_id") != snapshot.get("snapshot_id")
                or checkpoint.get("stage") != "committed" or checkpoint.get("result_ref") != "result.json"
                or not result.get("verified_models")):
            return False
        for model in result["verified_models"]:
            ref = str(model.get("ref") or "")
            if not ref.startswith("outputs/"):
                return False
            path = self.artifacts.artifact_path(task.task_id, ref)
            if (not path.is_file() or _is_link_like(path)
                    or path.stat().st_size != model.get("size_bytes") or _sha(path) != model.get("sha256")):
                return False
        algorithms = self.data_dir / "projects" / task.project_id / "algorithms.json"
        return AlgorithmSqlStore(algorithms).has_verified_training_version_readonly(
            task.task_id, snapshot.get("snapshot_id"), result["verified_models"],
        )

    def _recovery_dependency(self, task):
        failure = self.artifacts.read_json(task.task_id, "failure.json", default={})
        if (failure.get("recoverable") or failure.get("checkpoint_available")
                or failure.get("checkpoints") or failure.get("recovery_action")):
            return True
        project = self.data_dir / "projects" / task.project_id
        runs = project / "runs"
        if _is_link_like(runs):
            return True
        if runs.is_dir():
            for root in runs.iterdir():
                if not root.name.startswith("train_" + task.task_id):
                    continue
                # An unknown link or any checkpoint keeps the whole bundle.
                if _is_link_like(root):
                    return True
                for path in root.rglob("*"):
                    if _is_link_like(path) or path.suffix.lower() == ".pt":
                        return True
        return False

    def _inspect(self, task, active):
        blockers = []
        if task.status not in TERMINAL_STATUSES or not task.finished_at:
            blockers.append("TASK_ACTIVE")
        if task.worker_id or task.lease_expires_at:
            blockers.append("EXECUTION_LEASE_PRESENT")
        if task.process_pid and (psutil.pid_exists(task.process_pid)
                or (os.name != "nt" and ProcessController._posix_group_exists(task.process_pid))):
            blockers.append("PROCESS_PRESENT")
        if active:
            blockers.append("ACTIVE_CONSUMER")
        marker = self.artifacts.read_json(task.task_id, MARKER, default={})
        snapshot = self.artifacts.read_json(task.task_id, "snapshot.json", default={})
        payload = self.artifacts.read_json(task.task_id, task.payload_ref, default={})
        if not (marker.get("schema_version") == 1 and marker.get("task_id") == task.task_id
                and marker.get("project_id") == task.project_id
                and marker.get("snapshot_id") == snapshot.get("snapshot_id")
                and marker.get("input_freeze_id") == payload.get("input_freeze_id")
                and marker.get("attempt") == task.attempt
                and marker.get("owned_paths") == ["work/bundle"]
                and payload.get("target") == "local"):
            blockers.append("OWNERSHIP_UNVERIFIED")
        size = 0
        try:
            bundle, detached = self._paths(task.task_id)
            size = self._tree_bytes(bundle) + self._tree_bytes(detached)
        except (OSError, ValueError):
            blockers.append("UNSAFE_PATH")
        if task.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
            if not self._model_evidence(task, snapshot):
                blockers.append("MODEL_EVIDENCE_UNVERIFIED")
        elif self._recovery_dependency(task):
            blockers.append("RECOVERY_DEPENDENCY")
        return {"task_id": task.task_id, "project_id": task.project_id,
                "eligible": not blockers, "blockers": blockers, "temporary_logical_bytes": size,
                "scope": "task_work_bundle_only", "physical_space_released": None,
                "attempt": task.attempt, "snapshot_id": snapshot.get("snapshot_id")}

    def inspect(self, project_id, task_id):
        task = self.repository.get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.TRAINING:
            raise KeyError(task_id)
        # Read-only: no schema, marker, evidence or audit writes.
        with closing(self.repository._connect()) as database:
            active = database.execute(
                "SELECT task_id FROM tasks WHERE project_id=? AND task_id<>? "
                "AND kind IN ('TRAINING','TRAINING_PREPARE','DEPLOYMENT_TEST') "
                "AND status IN ('RUNNING','CANCEL_REQUESTED','AWAITING_CONFIRMATION')",
                (project_id, task_id),
            ).fetchall()
        return self._inspect(task, active)

    def _archive_evidence(self, task, bundle):
        """Retain metadata and actual report error images, never the entire cohort."""
        manifest = self.artifacts.read_json(task.task_id, "work/bundle/manifest.json", default=None)
        if not isinstance(manifest, dict):
            raise RuntimeError("BUNDLE_MANIFEST_UNVERIFIED")
        snapshot = self.artifacts.read_json(task.task_id, "snapshot.json", default={})
        if manifest.get("snapshot_id") != snapshot.get("snapshot_id"):
            raise RuntimeError("BUNDLE_MANIFEST_UNVERIFIED")
        result = self.artifacts.read_json(task.task_id, task.result_ref or "result.json", default={})
        samples = ((result.get("training_report") or {}).get("test_result") or {}).get("error_samples") or []
        members = [row for rows in manifest.get("splits", {}).values() for row in rows]
        refs = {"manifest.json", "snapshot.json", "dataset-revision.json", "dataset/data.yaml"}
        # Preserve all small GT labels as evidence. Original formal GT is untouched.
        refs.update(str(row["label_ref"]) for row in members if row.get("label_ref"))
        for sample in samples:
            matches = [row for row in members if
                (sample.get("image_id") and row.get("image_id") == sample["image_id"])
                or Path(str(row.get("image_ref") or "")).name == sample.get("image")]
            if len(matches) != 1:
                raise RuntimeError("REPORT_IMAGE_IDENTITY_UNVERIFIED")
            row = matches[0]
            image = _resolve_relative(bundle, row["image_ref"])
            if _sha(image) != row.get("content_sha256"):
                raise RuntimeError("REPORT_IMAGE_HASH_MISMATCH")
            refs.add(row["image_ref"])
        for ref in sorted(refs):
            source = _resolve_relative(bundle, ref)
            if not source.is_file():
                if ref == "manifest.json" or any(row.get("label_ref") == ref for row in members):
                    raise RuntimeError("REPORT_EVIDENCE_MISSING")
                continue
            target = _resolve_relative(self.artifacts.root / task.task_id, EVIDENCE + "/" + ref)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name("." + target.name + ".tmp")
            if _is_link_like(temporary):
                raise RuntimeError("UNSAFE_EVIDENCE_PATH")
            shutil.copyfile(source, temporary)
            if _sha(source) != _sha(temporary):
                temporary.unlink(missing_ok=True)
                raise RuntimeError("REPORT_EVIDENCE_COPY_CHANGED")
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            if os.name != "nt":
                descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)

    def _delete_detached(self, path):
        self._tree_bytes(path)  # Recheck lexical tree before recursive deletion.
        if path.exists():
            shutil.rmtree(path)

    def cleanup(self, project_id, task_id, *, actor, expected_attempt=None, expected_snapshot_id=None):
        # Lock lives outside the task-owned work tree and holds no business state.
        self.artifacts._validate_task_id(task_id)
        self._paths(task_id)  # Validate lexical task/work ownership before locking.
        with FileLock(str(self.artifacts.root / task_id / "workspace-access.lock"), timeout=5):
            with self.repository.training_workspace_guard(task_id) as (task, active):
                if task.project_id != project_id or task.kind is not TaskKind.TRAINING:
                    raise KeyError(task_id)
                if expected_attempt is not None and task.attempt != expected_attempt:
                    raise RuntimeError("WORKSPACE_PREVIEW_STALE")
                if expected_snapshot_id is not None:
                    snapshot = self.artifacts.read_json(task_id, "snapshot.json", default={})
                    if snapshot.get("snapshot_id") != expected_snapshot_id:
                        raise RuntimeError("WORKSPACE_PREVIEW_STALE")
                truth = self._inspect(task, active)
                if not truth["eligible"]:
                    self.artifacts.append_log(task_id, "logs/workspace-cleanup.jsonl", json.dumps({
                        "status": "refused", "actor": str(actor), "at": utc_now(),
                        "blockers": truth["blockers"], "task_id": task_id,
                    }, ensure_ascii=False) + "\n")
                    raise RuntimeError(",".join(truth["blockers"]))
                bundle, detached = self._paths(task_id)
                receipt = self.artifacts.read_json(task_id, RECEIPT, default={})
                if not bundle.exists() and not detached.exists():
                    if receipt.get("status") in {"pending", "retryable"}:
                        receipt = {**receipt, "status": "deleted", "finished_at": utc_now(),
                            "deleted_logical_bytes": receipt["candidate_logical_bytes"],
                            "physical_space_released": None}
                        self.artifacts.atomic_write_json(task_id, RECEIPT, receipt)
                    return {**truth, "status": "already_clean", "deleted_logical_bytes": 0}
                if bundle.exists():
                    if detached.exists():
                        raise RuntimeError("PREVIOUS_CLEANUP_PENDING")
                    self._archive_evidence(task, bundle)
                    receipt = {"schema_version": 1, "task_id": task_id, "attempt": task.attempt,
                        "actor": str(actor), "started_at": utc_now(), "status": "pending",
                        "deleted_logical_bytes": 0, "candidate_logical_bytes": truth["temporary_logical_bytes"]}
                    self.artifacts.atomic_write_json(task_id, RECEIPT, receipt)
                    os.replace(bundle, detached)
                elif receipt.get("task_id") != task_id or receipt.get("attempt") != task.attempt:
                    raise RuntimeError("CLEANUP_RECEIPT_UNVERIFIED")
            # The DB lock covers only eligibility/archival/detach, never bulk unlink.
            try:
                self._delete_detached(detached)
            except OSError as error:
                self.artifacts.atomic_write_json(task_id, RECEIPT, {
                    **receipt, "status": "retryable", "error": type(error).__name__, "updated_at": utc_now(),
                })
                raise
            receipt = {**receipt, "status": "deleted", "finished_at": utc_now(),
                "deleted_logical_bytes": receipt["candidate_logical_bytes"], "physical_space_released": None}
            self.artifacts.atomic_write_json(task_id, RECEIPT, receipt)
            self.artifacts.append_log(task_id, "logs/workspace-cleanup.jsonl", json.dumps(receipt, ensure_ascii=False) + "\n")
            return receipt
