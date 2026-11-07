"""Task-owned training workspace retention, using the original task/artifact owners.

Only newly attested local work/bundle directories can be detached. Historical
bundles, canonical storage, shared caches, checkpoints and models are outside
this allowlist. No production scan or cleanup runs merely by importing this module.
"""
from __future__ import annotations

import hashlib
import errno
import json
import logging
import os
import sqlite3
import shutil
import stat
import time
import uuid
from contextlib import closing, nullcontext
from datetime import datetime, timezone
from pathlib import Path

import psutil
from filelock import FileLock, Timeout

from .algorithm_sql_store import AlgorithmSqlStore
from .task_runtime.models import TaskKind, TaskStatus, utc_now
from .task_runtime.repository import TERMINAL_STATUSES
from .task_runtime.process_control import ProcessController
from .training_bundle_cache import _is_link_like, _resolve_relative
from .training_prepare_child import ensure_training_prepare_child


MARKER = "workspace-lifecycle.json"
RECEIPT = "workspace-cleanup.json"
EVIDENCE = "evidence/bundle"
ARCHIVE_PROOF = "evidence/archive-proof.json"
MAINTENANCE_LOCK = "workspace-maintenance.lock"
MAX_RETRY_DELAY_SECONDS = 3600
MAX_AUTOMATIC_IO_RETRIES = 8
DEFAULT_ARCHIVE_RESERVE_BYTES = 2 * 1024 ** 3


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
        # Repair the same Web-created deterministic child after an interrupted
        # parent/child commit; settle impossible parents with terminal children.
        # Both operations are bounded and leave live worker leases untouched.
        self._repair_missing_training_prepare_children(limit=8)
        self.repository.settle_stranded_training_preparations(limit=8)
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
                receipt = self.artifacts.read_json(task_id, RECEIPT, default={})
                if receipt.get("automatic_paused") or float(receipt.get("next_retry_epoch") or 0) > time.time():
                    continue
                # Avoid a second full tree walk/model hash and let cleanup's
                # task-scoped owner lock serialize the expensive preflight.
                result = self.cleanup(project_id, task_id, actor="automatic-workspace-maintenance")
                deleted += result.get("status") == "deleted"
            except Exception as error:
                # cleanup already persists a classified diagnostic. Never let
                # maintenance failure interfere with task claiming or renewal.
                if not isinstance(error, (RuntimeError, OSError, Timeout)):
                    self._record_maintenance_wait(task_id, "retryable", [type(error).__name__])
        return {"examined": len(rows), "deleted": deleted}

    def _repair_missing_training_prepare_children(self, *, limit=8):
        with closing(self.repository._connect()) as database:
            rows = database.execute(
                """SELECT parent.task_id, parent.project_id, parent.created_at,
                          parent.priority, parent.payload_ref
                     FROM tasks AS parent
                     LEFT JOIN tasks AS child ON child.task_id='trainprep_' || parent.task_id
                    WHERE parent.kind='TRAINING' AND parent.status='QUEUED'
                      AND parent.required_capabilities='["training.input.ready"]'
                      AND parent.stage='training_input_pending' AND child.task_id IS NULL
                    ORDER BY parent.created_at LIMIT ?""",
                (max(1, min(20, int(limit))),),
            ).fetchall()
        if not rows:
            return
        locks_dir = self.data_dir / "task_runtime" / "training_create_locks"
        locks_dir.mkdir(parents=True, exist_ok=True)
        for row in rows:
            task_id = str(row["task_id"])
            try:
                # Give the HTTP creator time to finish its normal two inserts.
                if datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(
                    str(row["created_at"]),
                ).timestamp() < 45:
                    continue
                self.artifacts._validate_task_id(task_id)
                with FileLock(str(locks_dir / f"{task_id}.lock"), timeout=0):
                    parent = self.repository.get(task_id)
                    if (parent is None or parent.status is not TaskStatus.QUEUED
                            or parent.stage != "training_input_pending"
                            or parent.required_capabilities != ("training.input.ready",)
                            or self.repository.get(f"trainprep_{task_id}") is not None):
                        continue
                    payload = self.artifacts.read_json(task_id, parent.payload_ref, default={})
                    if (not isinstance(payload, dict)
                            or payload.get("training_prepare_task_id") != f"trainprep_{task_id}"
                            or payload.get("training_input_state") != "PREPARING"
                            or payload.get("project_id", parent.project_id) != parent.project_id):
                        self.repository.fail_queued_precondition(
                            task_id, "TRAINING_PREPARATION_PAYLOAD_INVALID: 无法恢复训练准备任务",
                            stage="training_input_preparation_failed",
                        )
                        continue
                    ensure_training_prepare_child(
                        self.repository, self.artifacts, parent.project_id, task_id,
                        f"trainprep_{task_id}", parent.priority,
                    )
            except (Timeout, OSError, ValueError, KeyError, sqlite3.OperationalError) as error:
                # Existing scheduler retry and original task are authoritative;
                # the next maintenance iteration can retry the same recovery.
                logging.getLogger(__name__).debug("training preparation repair deferred: %s", error)

    def _record_maintenance_wait(self, task_id, status, blockers):
        """Diagnostics never replace an in-flight detach receipt or authorize deletion."""
        try:
            self._paths(task_id)
            with FileLock(str(self.artifacts.root / task_id / "workspace-access.lock"), timeout=0):
                previous = self.artifacts.read_json(task_id, RECEIPT, default={})
                if (previous.get("status") in {"pending", "deleted"}
                        or previous.get("status") == "retryable" and "candidate_logical_bytes" in previous):
                    return
                count = int(previous.get("attempt_count") or 0) + 1
                delay = min(MAX_RETRY_DELAY_SECONDS, 30 * 2 ** min(count - 1, 7))
                self.artifacts.atomic_write_json(task_id, RECEIPT, {
                    "schema_version": 1, "task_id": task_id, "status": status,
                    "blockers": blockers, "updated_at": utc_now(), "last_attempt_at": utc_now(),
                    "attempt_count": count, "next_retry_epoch": time.time() + delay,
                    "scope": "task_work_bundle_only", "deleted_logical_bytes": 0,
                    "physical_space_released": None,
                })
        except Timeout:
            # Another process holds the short reader/detach lock. This is a
            # normal skip, not an unavailable diagnostic worth warning on.
            return
        except Exception:
            # A busy workspace or unavailable artifact store cannot grant cleanup.
            logging.getLogger(__name__).warning("Workspace maintenance diagnostic unavailable task_id=%s", task_id)

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

    @staticmethod
    def _file_identity(path):
        if _is_link_like(path):
            raise RuntimeError("UNSAFE_EVIDENCE_PATH")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("UNSAFE_EVIDENCE_PATH")
        return [info.st_ino, info.st_size, info.st_mtime_ns]

    @staticmethod
    def _require_archive_space(path, required_bytes):
        # A reserve is a safety threshold, not a prediction of physical bytes
        # ultimately released. The OS may still report ENOSPC concurrently.
        try:
            reserve = int(os.environ.get("CHANG_LIAN_ARCHIVE_MIN_FREE_BYTES",
                                         str(DEFAULT_ARCHIVE_RESERVE_BYTES)))
        except (TypeError, ValueError) as error:
            raise RuntimeError("DISK_SPACE_INSUFFICIENT") from error
        if reserve < 0:
            raise RuntimeError("DISK_SPACE_INSUFFICIENT")
        # shutil.disk_usage works on Windows and POSIX. os.statvfs is POSIX
        # only and would turn every Windows archive into an unexpected 503.
        if shutil.disk_usage(path).free < reserve + int(required_bytes):
            raise RuntimeError("DISK_SPACE_INSUFFICIENT")

    def _archive_evidence(self, task, bundle):
        """Retain metadata and actual report error images, never the entire cohort."""
        # `bundle` can be either the original work/bundle or the task-owned
        # work/.bundle-reclaim after an interrupted atomic detach. Resolve the
        # manifest from the validated source directory in both cases.
        manifest_path = _resolve_relative(bundle, "manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError("BUNDLE_MANIFEST_UNVERIFIED") from error
        if not isinstance(manifest, dict):
            raise RuntimeError("BUNDLE_MANIFEST_UNVERIFIED")
        snapshot = self.artifacts.read_json(task.task_id, "snapshot.json", default={})
        if manifest.get("snapshot_id") != snapshot.get("snapshot_id"):
            raise RuntimeError("BUNDLE_MANIFEST_UNVERIFIED")
        result = self.artifacts.read_json(task.task_id, task.result_ref or "result.json", default={})
        evaluation = ((result.get("training_report") or {}).get("test_result") or {})
        samples = list(evaluation.get("error_samples") or [])
        samples.extend(evaluation.get("sample_evidence") or [])
        # The complete outcome index exceeds the Top200 box evidence. Retain
        # every abnormal image, but do not copy the complete correct cohort.
        samples.extend(row for row in evaluation.get("sample_outcomes") or []
                       if row.get("fp_count") or row.get("fn_count"))
        members = [row for rows in manifest.get("splits", {}).values() for row in rows]
        by_id, by_name = {}, {}
        for row in members:
            by_id.setdefault(row.get("image_id"), []).append(row)
            by_name.setdefault(Path(str(row.get("image_ref") or "")).name, []).append(row)
        refs = {"manifest.json", "snapshot.json", "dataset-revision.json", "dataset/data.yaml"}
        # Preserve all small GT labels as evidence. Original formal GT is untouched.
        refs.update(str(row["label_ref"]) for row in members if row.get("label_ref"))
        for sample in samples:
            matches = (by_id.get(sample["image_id"], []) if sample.get("image_id")
                       else by_name.get(sample.get("image"), []))
            if len(matches) != 1:
                raise RuntimeError("REPORT_IMAGE_IDENTITY_UNVERIFIED")
            row = matches[0]
            if (sample.get("image") and Path(str(row.get("image_ref") or "")).name != sample["image"]):
                raise RuntimeError("REPORT_IMAGE_IDENTITY_UNVERIFIED")
            if (sample.get("image_content_sha256")
                    and sample["image_content_sha256"] != row.get("content_sha256")):
                raise RuntimeError("REPORT_IMAGE_HASH_MISMATCH")
            if row["image_ref"] in refs:
                continue
            image = _resolve_relative(bundle, row["image_ref"])
            if _sha(image) != row.get("content_sha256"):
                raise RuntimeError("REPORT_IMAGE_HASH_MISMATCH")
            refs.add(row["image_ref"])
        identity = {
            "task_id": task.task_id, "project_id": task.project_id,
            "attempt": task.attempt, "snapshot_id": snapshot.get("snapshot_id"),
            "manifest_sha256": _sha(_resolve_relative(bundle, "manifest.json")),
            "result_sha256": _sha(self.artifacts.artifact_path(task.task_id, task.result_ref or "result.json"))
                if self.artifacts.artifact_path(task.task_id, task.result_ref or "result.json").is_file() else None,
            "refs_sha256": hashlib.sha256(json.dumps(sorted(refs), ensure_ascii=False).encode()).hexdigest(),
        }
        previous = self.artifacts.read_json(task.task_id, ARCHIVE_PROOF, default={})
        verified_before = (previous.get("files") or {}) if previous.get("identity") == identity else {}
        verified = {}
        for ref in sorted(refs):
            source = _resolve_relative(bundle, ref)
            if not source.is_file():
                if ref == "manifest.json" or any(row.get("label_ref") == ref for row in members):
                    raise RuntimeError("REPORT_EVIDENCE_MISSING")
                continue
            target = _resolve_relative(self.artifacts.root / task.task_id, EVIDENCE + "/" + ref)
            target.parent.mkdir(parents=True, exist_ok=True)
            source_identity = self._file_identity(source)
            known = verified_before.get(ref)
            if (isinstance(known, dict) and known.get("source_identity") == source_identity
                    and target.is_file() and known.get("target_identity") == self._file_identity(target)):
                verified[ref] = known
                continue
            if known and known.get("source_identity") != source_identity:
                raise RuntimeError("REPORT_EVIDENCE_CHANGED")
            source_sha = _sha(source)
            if target.is_file() and _sha(target) == source_sha:
                # A previous interrupted archive copied this file correctly.
                # Reuse it without another copy/fsync/replace cycle.
                verified[ref] = {"sha256": source_sha, "source_identity": source_identity,
                                 "target_identity": self._file_identity(target)}
                continue
            temporary = target.with_name("." + target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                self._require_archive_space(target.parent, source_identity[1])
                shutil.copyfile(source, temporary)
                if self._file_identity(source) != source_identity or _sha(temporary) != source_sha:
                    raise RuntimeError("REPORT_EVIDENCE_COPY_CHANGED")
                with temporary.open("r+b") as stream:
                    os.fsync(stream.fileno())
                # A report reader holds this lock through hash verification
                # and streaming. Swap one verified file at a time, never hold
                # the reader lock during copying or hashing the whole set.
                with FileLock(str(self.artifacts.root / task.task_id / "workspace-access.lock"), timeout=5):
                    os.replace(temporary, target)
                    if os.name != "nt":
                        descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
            finally:
                # Only this invocation's uniquely named temporary may be
                # removed. Other owners' orphans are never guessed at.
                temporary.unlink(missing_ok=True)
            verified[ref] = {"sha256": source_sha, "source_identity": source_identity,
                             "target_identity": self._file_identity(target)}
        for ref, evidence in verified.items():
            if (self._file_identity(_resolve_relative(bundle, ref)) != evidence["source_identity"]
                    or self._file_identity(_resolve_relative(self.artifacts.root / task.task_id,
                                                            EVIDENCE + "/" + ref)) != evidence["target_identity"]):
                raise RuntimeError("REPORT_EVIDENCE_CHANGED")
        # This is a task-scoped attestation of already verified bytes, not a
        # second task truth source. A crash before the atomic proof write simply
        # causes the next attempt to verify/reuse existing target files.
        self.artifacts.atomic_write_json(task.task_id, ARCHIVE_PROOF, {
            "schema_version": 1, "status": "complete", "identity": identity,
            "files": verified, "completed_at": utc_now(),
        })

    def _delete_detached(self, path):
        self._tree_bytes(path)  # Recheck lexical tree before recursive deletion.
        if path.exists():
            shutil.rmtree(path)

    def _evidence_stamp(self, task):
        # Task-owned files only: unrelated project SQL/WAL writes are not a
        # change of this training task's version or model evidence.
        refs = {MARKER, "snapshot.json", task.payload_ref, task.result_ref or "result.json",
                "failure.json", "checkpoints/worker.json", "work/bundle/manifest.json"}
        result = self.artifacts.read_json(task.task_id, task.result_ref or "result.json", default={})
        if isinstance(result, dict):
            refs.update(str(model.get("ref")) for model in result.get("verified_models") or []
                        if isinstance(model, dict) and model.get("ref"))
        paths = [self.artifacts.artifact_path(task.task_id, ref) for ref in sorted(refs)]
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
        phase = {"value": "owner_lock"}
        started = time.monotonic()
        try:
            return self._cleanup_owned(project_id, task_id, actor=actor,
                expected_attempt=expected_attempt, expected_snapshot_id=expected_snapshot_id,
                phase=phase)
        except Timeout as error:
            if phase["value"] == "owner_lock" and str(actor).startswith("automatic"):
                # The other Worker owns this expensive archive. Ordinary
                # contention is neither a failure nor a loggable warning.
                return {"task_id": task_id, "status": "skipped_busy"}
            self._record_cleanup_failure(task_id, actor, phase["value"], error,
                (time.monotonic() - started) * 1000)
            raise
        except (RuntimeError, OSError, sqlite3.Error) as error:
            self._record_cleanup_failure(task_id, actor, phase["value"], error,
                (time.monotonic() - started) * 1000)
            raise

    @staticmethod
    def _failure_classification(phase, error):
        if isinstance(error, Timeout):
            return "WORKSPACE_BUSY", True
        if isinstance(error, OSError):
            if error.errno == errno.ENOSPC:
                return "DISK_SPACE_INSUFFICIENT", True
            if isinstance(error, FileNotFoundError):
                return "ARCHIVE_SOURCE_MISSING" if phase == "archive" else "WORKSPACE_IO_FAILURE", True
            return ({"archive": "ARCHIVE_IO_FAILURE", "detach": "DETACH_IO_FAILURE",
                     "delete": "DELETE_IO_FAILURE"}.get(phase, "WORKSPACE_IO_FAILURE"), True)
        if isinstance(error, sqlite3.Error):
            return "WORKSPACE_DATABASE_BUSY", True
        message = str(error)
        if message == "WORKSPACE_PREVIEW_STALE":
            return message, True
        if message == "DISK_SPACE_INSUFFICIENT":
            return message, True
        if message in {"ARCHIVE_INCOMPLETE", "PREVIOUS_CLEANUP_PENDING"}:
            return message, True
        return (message if message and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" for c in message)
                else "WORKSPACE_PROTECTED"), False

    def _record_cleanup_failure(self, task_id, actor, phase, error, duration_ms):
        code, retryable = self._failure_classification(phase, error)
        diagnostic_id = uuid.uuid4().hex
        for key, value in (("workspace_code", code), ("workspace_retryable", retryable),
                           ("workspace_stage", phase), ("workspace_diagnostic_id", diagnostic_id)):
            try:
                setattr(error, key, value)
            except (AttributeError, TypeError):
                pass
        detail = {"task_id": task_id, "diagnostic_id": diagnostic_id,
                  "actor_kind": "automatic" if str(actor).startswith("automatic") else "manual",
                  "stage": phase, "code": code, "exception_type": type(error).__name__,
                  "errno": getattr(error, "errno", None),
                  "duration_ms": round(duration_ms, 2), "at": utc_now()}
        logging.getLogger(__name__).warning("Workspace cleanup failure %s", json.dumps(detail))
        try:
            self.artifacts.append_log(task_id, "logs/workspace-cleanup.jsonl",
                                      json.dumps(detail, ensure_ascii=False) + "\n")
            with FileLock(str(self.artifacts.root / task_id / "workspace-access.lock"), timeout=0):
                previous = self.artifacts.read_json(task_id, RECEIPT, default={})
                if previous.get("status") == "deleted":
                    return
                count = int(previous.get("attempt_count") or 0) + 1
                delay = min(MAX_RETRY_DELAY_SECONDS, 30 * 2 ** min(count - 1, 7))
                actor_kind = detail["actor_kind"]
                paused = (actor_kind == "automatic" and retryable and count >= MAX_AUTOMATIC_IO_RETRIES
                          and code in {"ARCHIVE_IO_FAILURE", "ARCHIVE_SOURCE_MISSING",
                                       "DISK_SPACE_INSUFFICIENT", "DETACH_IO_FAILURE",
                                       "DELETE_IO_FAILURE", "WORKSPACE_IO_FAILURE"})
                self.artifacts.atomic_write_json(task_id, RECEIPT, {
                    **previous, "schema_version": 1, "task_id": task_id,
                    "status": "retryable" if retryable else "blocked",
                    "blockers": [code], "last_attempt_at": utc_now(),
                    "updated_at": utc_now(), "attempt_count": count,
                    "next_retry_epoch": time.time() + delay,
                    "automatic_paused": paused,
                    "stage": phase, "diagnostic_id": diagnostic_id,
                    "deleted_logical_bytes": 0, "physical_space_released": None,
                    "scope": "task_work_bundle_only",
                })
        except (OSError, RuntimeError, Timeout, ValueError):
            # A failed diagnostic write never changes the cleanup decision.
            pass

    def _cleanup_owned(self, project_id, task_id, *, actor, expected_attempt, expected_snapshot_id, phase):
        # This extra *lock*, not a second task owner, prevents two Workers from
        # doing the same expensive archive; released by the OS after a crash.
        self.artifacts._validate_task_id(task_id)
        self._paths(task_id)
        with FileLock(str(self.artifacts.root / task_id / MAINTENANCE_LOCK),
                      timeout=0 if str(actor).startswith("automatic") else 5):
            phase["value"] = "preflight"
            qualified = self.repository.get(task_id)
            if qualified is None or qualified.project_id != project_id or qualified.kind is not TaskKind.TRAINING:
                raise KeyError(task_id)
            if expected_attempt is not None and qualified.attempt != expected_attempt:
                raise RuntimeError("WORKSPACE_PREVIEW_STALE")
            if expected_snapshot_id is not None:
                current_snapshot = self.artifacts.read_json(task_id, "snapshot.json", default={})
                if current_snapshot.get("snapshot_id") != expected_snapshot_id:
                    raise RuntimeError("WORKSPACE_PREVIEW_STALE")
            evidence_stamp = self._evidence_stamp(qualified)
            truth = self._inspect(qualified, self._consumers(qualified))
            if not truth["eligible"]:
                self.artifacts.append_log(task_id, "logs/workspace-cleanup.jsonl", json.dumps({
                    "status": "refused", "actor": str(actor), "at": utc_now(),
                    "blockers": truth["blockers"], "task_id": task_id,
                }, ensure_ascii=False) + "\n")
                raise RuntimeError(",".join(truth["blockers"]))
            version_guard = nullcontext()
            if qualified.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
                snapshot = self.artifacts.read_json(task_id, "snapshot.json", default={})
                result = self.artifacts.read_json(task_id, qualified.result_ref or "result.json", default={})
                models = result.get("verified_models") or []
                catalog = AlgorithmSqlStore(self.data_dir / "projects" / project_id / "algorithms.json")
                version_ids = catalog.verified_training_version_identity_readonly(
                    task_id, snapshot.get("snapshot_id"), models)
                if not version_ids:
                    raise RuntimeError("MODEL_VERSION_CHANGED")
                version_guard = catalog.verified_training_version_guard(
                    task_id, snapshot.get("snapshot_id"), models, version_ids)
            bundle, detached = self._paths(task_id)
            if bundle.exists():
                if detached.exists():
                    raise RuntimeError("PREVIOUS_CLEANUP_PENDING")
                phase["value"] = "archive"
                self._archive_evidence(qualified, bundle)
            elif detached.exists():
                # Recovery after a crash of an older Worker: prove the
                # evidence before completing deletion, never trust receipt only.
                phase["value"] = "archive"
                self._archive_evidence(qualified, detached)
            phase["value"] = "final_gate"
            with FileLock(str(self.artifacts.root / task_id / "workspace-access.lock"), timeout=5):
                with self.repository.training_workspace_guard(task_id) as (task, active):
                    with version_guard:
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
                            raise RuntimeError(",".join(truth["blockers"]))
                        bundle, detached = self._paths(task_id)
                        receipt = self.artifacts.read_json(task_id, RECEIPT, default={})
                        if not bundle.exists() and not detached.exists():
                            if (receipt.get("status") in {"pending", "retryable"}
                                    and "candidate_logical_bytes" in receipt):
                                receipt = {**receipt, "status": "deleted", "finished_at": utc_now(),
                                    "deleted_logical_bytes": receipt["candidate_logical_bytes"],
                                    "physical_space_released": None}
                                self.artifacts.atomic_write_json(task_id, RECEIPT, receipt)
                            return {**truth, "status": "already_clean", "deleted_logical_bytes": 0}
                        proof = self.artifacts.read_json(task_id, ARCHIVE_PROOF, default={})
                        if (proof.get("status") != "complete"
                                or proof.get("identity", {}).get("task_id") != task_id
                                or proof.get("identity", {}).get("attempt") != task.attempt):
                            raise RuntimeError("ARCHIVE_INCOMPLETE")
                        if bundle.exists():
                            if detached.exists():
                                raise RuntimeError("PREVIOUS_CLEANUP_PENDING")
                            receipt = {"schema_version": 1, "task_id": task_id, "attempt": task.attempt,
                                "actor": str(actor), "started_at": utc_now(), "status": "pending",
                                "deleted_logical_bytes": 0,
                                "candidate_logical_bytes": truth["temporary_logical_bytes"]}
                            self.artifacts.atomic_write_json(task_id, RECEIPT, receipt)
                            phase["value"] = "detach"
                            os.replace(bundle, detached)
                        elif receipt.get("task_id") != task_id or receipt.get("attempt") != task.attempt:
                            raise RuntimeError("CLEANUP_RECEIPT_UNVERIFIED")
            # The DB lock covers only the final identity/eligibility check and detach.
            phase["value"] = "delete"
            try:
                self._delete_detached(detached)
            except OSError as error:
                self.artifacts.atomic_write_json(task_id, RECEIPT, {
                    **receipt, "status": "retryable", "error": type(error).__name__, "updated_at": utc_now(),
                })
                raise
            phase["value"] = "confirm"
            receipt = {**receipt, "status": "deleted", "finished_at": utc_now(),
                "deleted_logical_bytes": receipt["candidate_logical_bytes"], "physical_space_released": None}
            self.artifacts.atomic_write_json(task_id, RECEIPT, receipt)
            self.artifacts.append_log(task_id, "logs/workspace-cleanup.jsonl", json.dumps(receipt, ensure_ascii=False) + "\n")
            return receipt
