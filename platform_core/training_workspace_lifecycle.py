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
        self._maintenance_cursor = ""

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

    def _consumes_bundle(self, task, candidate):
        # Known original handlers isolate TRAINING bundles to their own task
        # directory. Missing/foreign contracts remain protected, including queued
        # recovery consumers; cache identity alone never means task-bundle sharing.
        try:
            payload = self.artifacts.read_json(candidate.task_id, candidate.payload_ref, default=None)
            if not isinstance(payload, dict) or not payload:
                return True
            if payload.get("training_task_id") == task.task_id:
                return True
            target = str(self._paths(task.task_id)[0]).replace("\\", "/").casefold()
            pending = [payload]
            prepared_ref = payload.get("prepared_input_ref")
            if prepared_ref:
                prepared = self.artifacts.read_json(candidate.task_id, str(prepared_ref), default=None)
                if not isinstance(prepared, dict):
                    return True
                pending.append(prepared)
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
                elif isinstance(item, str):
                    value = item.replace("\\", "/").casefold()
                    if target in value or f"{task.task_id}/work/bundle/" in value + "/":
                        return True
            if candidate.kind is TaskKind.TRAINING:
                return not (payload.get("target") in {"local", "remote"}
                            and payload.get("input_freeze_id") and payload.get("input_freeze_ref"))
            if candidate.kind is TaskKind.TRAINING_PREPARE:
                return not bool(payload.get("training_task_id"))
            # Legacy evaluation contracts lack an explicit workspace ownership
            # guarantee. Keep them until a known, verified reference is available.
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return True

    def _consumers(self, task):
        with closing(self.repository._connect()) as database:
            ids = database.execute(
                "SELECT task_id FROM tasks WHERE project_id=? AND task_id<>? "
                "AND kind IN ('TRAINING','TRAINING_PREPARE','DEPLOYMENT_TEST') "
                "AND status NOT IN ('SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED')",
                (task.project_id, task.task_id),
            ).fetchall()
        return [candidate for row in ids if (candidate := self.repository.get(row[0])) is not None]

    def maintain(self, *, limit=4):
        """One bounded sweep over original terminal task truth; cursor is disposable."""
        limit = max(1, min(16, int(limit)))
        with closing(self.repository._connect()) as database:
            rows = database.execute(
                "SELECT task_id,project_id FROM tasks WHERE kind='TRAINING' "
                "AND status IN ('SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED') "
                "AND finished_at IS NOT NULL AND task_id>? ORDER BY task_id LIMIT ?",
                (self._maintenance_cursor, limit),
            ).fetchall()
        if not rows:
            self._maintenance_cursor = ""
            return {"examined": 0, "deleted": 0}
        deleted = 0
        for task_id, project_id in rows:
            self._maintenance_cursor = task_id
            try:
                bundle, detached = self._paths(task_id)
                if not bundle.exists() and not detached.exists():
                    continue
                truth = self.inspect(project_id, task_id)
                if not truth["eligible"]:
                    continue
                result = self.cleanup(project_id, task_id, actor="automatic-workspace-maintenance",
                    expected_attempt=truth["attempt"], expected_snapshot_id=truth["snapshot_id"])
                deleted += result.get("status") == "deleted"
            except Exception:
                # Original cleanup records deletion failures. Never let maintenance
                # break lease renewal/claiming or authorize deletion after an error.
                continue
        return {"examined": len(rows), "deleted": deleted}

    def _inspect(self, task, active, *, verify_evidence=True):
        blockers = []
        if task.status not in TERMINAL_STATUSES or not task.finished_at:
            blockers.append("TASK_ACTIVE")
        if task.worker_id or task.lease_expires_at:
            blockers.append("EXECUTION_LEASE_PRESENT")
        if task.process_pid:
            try:
                if (psutil.pid_exists(task.process_pid)
                        or (os.name != "nt" and ProcessController._posix_group_exists(task.process_pid))):
                    blockers.append("PROCESS_PRESENT")
                elif not task.process_create_time or not task.process_command_hash:
                    blockers.append("PROCESS_IDENTITY_UNVERIFIED")
            except (OSError, psutil.Error):
                blockers.append("PROCESS_IDENTITY_UNVERIFIED")
        elif task.process_create_time or task.process_command_hash:
            blockers.append("PROCESS_IDENTITY_UNVERIFIED")
        if any(self._consumes_bundle(task, candidate) for candidate in active):
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
            if verify_evidence:
                size = self._tree_bytes(bundle) + self._tree_bytes(detached)
        except (OSError, ValueError):
            blockers.append("UNSAFE_PATH")
        if not verify_evidence:
            pass
        elif task.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
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
        return self._inspect(task, self._consumers(task))

    def history_page(self, project_id, *, after="", limit=20):
        """Read-only dry-run for indexed task bundles; never adopts legacy ownership."""
        limit = max(1, min(20, int(limit)))
        with closing(self.repository._connect()) as database:
            rows = database.execute(
                "SELECT task_id,status FROM tasks WHERE project_id=? AND kind='TRAINING' "
                "AND task_id>? ORDER BY task_id LIMIT ?", (project_id, str(after), limit + 1),
            ).fetchall()
        items = []
        for task_id, status in rows[:limit]:
            try:
                item = self.inspect(project_id, task_id)
            except (OSError, ValueError, KeyError):
                item = {"task_id": task_id, "eligible": False, "blockers": ["WORKSPACE_UNVERIFIED"],
                        "temporary_logical_bytes": None, "scope": "task_work_bundle_only"}
            items.append({**item, "status": status})
        return {"items": items, "next_cursor": rows[limit-1][0] if len(rows) > limit else None,
                "dry_run": True, "scope": "indexed_task_work_bundles", "physical_space_released": None}

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

    def _evidence_stamp(self, task):
        # Stat only under the final DB gate; expensive hashing stays outside.
        refs = {MARKER, "snapshot.json", task.payload_ref, task.result_ref or "result.json",
                "failure.json", "checkpoints/worker.json", "work/bundle/manifest.json"}
        result = self.artifacts.read_json(task.task_id, task.result_ref or "result.json", default={})
        if isinstance(result, dict):
            refs.update(str(model.get("ref")) for model in result.get("verified_models") or []
                        if isinstance(model, dict) and model.get("ref"))
        paths = [self.artifacts.artifact_path(task.task_id, ref) for ref in sorted(refs)]
        project = self.data_dir / "projects" / task.project_id
        paths.extend(project / name for name in ("algorithms.json", "algorithms.sqlite3", "algorithms.sqlite3-wal"))
        stamp = []
        for path in paths:
            if _is_link_like(path):
                raise RuntimeError("UNSAFE_EVIDENCE_PATH")
            try:
                info = path.stat()
                stamp.append((str(path), info.st_ino, info.st_size, info.st_mtime_ns))
            except FileNotFoundError:
                stamp.append((str(path), None))
        return tuple(stamp)

    def cleanup(self, project_id, task_id, *, actor, expected_attempt=None, expected_snapshot_id=None):
        # Lock lives outside the task-owned work tree and holds no business state.
        self.artifacts._validate_task_id(task_id)
        self._paths(task_id)  # Validate lexical task/work ownership before locking.
        with FileLock(str(self.artifacts.root / task_id / "workspace-access.lock"), timeout=5):
            qualified = self.repository.get(task_id)
            if qualified is None or qualified.project_id != project_id or qualified.kind is not TaskKind.TRAINING:
                raise KeyError(task_id)
            evidence_stamp = self._evidence_stamp(qualified)
            truth = self._inspect(qualified, self._consumers(qualified))
            if not truth["eligible"]:
                self.artifacts.append_log(task_id, "logs/workspace-cleanup.jsonl", json.dumps({
                    "status": "refused", "actor": str(actor), "at": utc_now(),
                    "blockers": truth["blockers"], "task_id": task_id,
                }, ensure_ascii=False) + "\n")
                raise RuntimeError(",".join(truth["blockers"]))
            bundle, detached = self._paths(task_id)
            if bundle.exists():
                if detached.exists():
                    raise RuntimeError("PREVIOUS_CLEANUP_PENDING")
                self._archive_evidence(qualified, bundle)
            with self.repository.training_workspace_guard(task_id) as (task, active):
                if task.project_id != project_id or task.kind is not TaskKind.TRAINING:
                    raise KeyError(task_id)
                if expected_attempt is not None and task.attempt != expected_attempt:
                    raise RuntimeError("WORKSPACE_PREVIEW_STALE")
                if expected_snapshot_id is not None:
                    snapshot = self.artifacts.read_json(task_id, "snapshot.json", default={})
                    if snapshot.get("snapshot_id") != expected_snapshot_id:
                        raise RuntimeError("WORKSPACE_PREVIEW_STALE")
                if task != qualified or self._evidence_stamp(task) != evidence_stamp:
                    raise RuntimeError("WORKSPACE_PREVIEW_STALE")
                latest = self._inspect(task, active, verify_evidence=False)
                latest["temporary_logical_bytes"] = truth["temporary_logical_bytes"]
                truth = latest
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
                    receipt = {"schema_version": 1, "task_id": task_id, "attempt": task.attempt,
                        "actor": str(actor), "started_at": utc_now(), "status": "pending",
                        "deleted_logical_bytes": 0, "candidate_logical_bytes": truth["temporary_logical_bytes"]}
                    self.artifacts.atomic_write_json(task_id, RECEIPT, receipt)
                    os.replace(bundle, detached)
                elif receipt.get("task_id") != task_id or receipt.get("attempt") != task.attempt:
                    raise RuntimeError("CLEANUP_RECEIPT_UNVERIFIED")
            # The DB lock covers only the final identity/eligibility check and detach.
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
