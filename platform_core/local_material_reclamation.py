"""Explicit offline-only physical reclamation of a proven retired local original.

No schema/new database, canonical GT mutation, cache deletion or remote CAS claim.
The original task artifacts journal the detach/delete; all evidence is fail-closed.
"""
from __future__ import annotations

import json
import os
import re
import threading
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from datetime import datetime, timezone

import psutil
from filelock import Timeout

from .material_repository import (MaterialRepository, MATERIAL_READ_SCHEMA_VERSIONS, material_annotation_lifecycle_fence, normalize_material,
    existing_sqlite_reader as _readonly, metadata_evidence_digest as _digest)
from .storage.local import LocalStorageProvider, controlled_local_startup_guard
from .storage.cache import file_sha256
from .storage.source_repository import storage_source_lifecycle_fence
from .training_bundle_cache import _is_link_like
from .task_runtime.process_control import ProcessController


class LocalMaterialReclamationService:
    def __init__(self, data_dir, task_repository, task_artifacts, *, controlled_local_writers=False):
        self.data_dir = Path(data_dir).resolve()
        self.repository, self.artifacts = task_repository, task_artifacts
        self.controlled_local_writers = controlled_local_writers
        self._validate_runtime_paths()

    def _validate_runtime_paths(self):
        runtime = self.data_dir / "task_runtime"
        expected_artifacts = runtime / "artifacts"
        expected_database = runtime / "tasks.sqlite3"
        for path in (runtime, expected_artifacts, expected_database):
            if _is_link_like(path):
                raise ValueError("unsafe task runtime evidence path")
        if (Path(self.repository.path).resolve() != expected_database
                or Path(self.artifacts.root) != expected_artifacts):
            raise ValueError("task evidence must use the canonical data task_runtime owners")

    @staticmethod
    def _identifier(value):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(value)):
            raise ValueError("invalid reclamation identity")
        return str(value)

    def _projects(self):
        root = self.data_dir / "projects"
        if _is_link_like(root):
            raise ValueError("unsafe projects root")
        projects = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)
        if any(_is_link_like(path) for path in projects):
            raise ValueError("unsafe project root")
        return projects

    @staticmethod
    def _local_disk(path):
        if str(path).startswith("\\\\"):
            return False
        if os.name == "nt":
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(str(Path(path).anchor)) == 3
        allowed = {"ext2", "ext3", "ext4", "xfs", "btrfs", "apfs", "hfs", "hfsplus", "ntfs", "tmpfs", "overlay"}
        partitions = [part for part in psutil.disk_partitions(all=True)
                      if path.is_relative_to(Path(part.mountpoint))]
        if not partitions:
            return False
        closest = max(partitions, key=lambda part: len(part.mountpoint))
        return closest.fstype.lower() in allowed

    def _offline_blockers(self):
        blockers = []
        for thread in threading.enumerate():
            if thread is threading.main_thread():
                continue
            target = getattr(thread, "_target", None)
            # This original publisher only consumes model artifacts, never raw
            # project uploads. Match code identity, not a user-controlled name.
            if (getattr(target, "__module__", "") == "platform_core.external_algorithm_publish"
                    and getattr(target, "__qualname__", "") == "external_algorithm_publish_router.<locals>.worker_loop"):
                continue
            blockers.append("UNKNOWN_INPROCESS_CONSUMER")
        # Bare-Path legacy HTTP handlers have not all been converted. Never run
        # physical deletion inside a webserver or alongside platform processes.
        known = {"app.py", "task_worker.py", "train_worker.py", "train_worker_safe.py",
                 "train_checkpoint_resume_worker.py", "node_agent.py", "main.py", "paddle_worker.py",
                 "deployment_worker.py", "checkpoint_validation_worker.py"}
        for process in psutil.process_iter(["pid", "name", "exe", "cmdline", "cwd"], ad_value=None):
            info = process.info
            name = str(info.get("name") or "").lower().removesuffix(".exe")
            executable = info.get("exe")
            if name in {"uvicorn", "gunicorn", "task_worker", "node_agent", "train_worker"}:
                blockers.append("OFFLINE_MAINTENANCE_REQUIRED")
            if (info["pid"] != os.getpid() and executable and Path(executable).is_absolute()
                    and Path(executable).resolve().is_relative_to(Path(__file__).resolve().parent.parent)):
                blockers.append("UNKNOWN_PLATFORM_PROCESS")
            command = info.get("cmdline")
            words = [str(word).lower() for word in command or []]
            if info["pid"] != os.getpid():
                data_token = os.path.normcase(str(self.data_dir)).replace("\\", "/")
                cwd = info.get("cwd")
                if any(data_token in os.path.normcase(word).replace("\\", "/") for word in words) or (cwd and Path(cwd).resolve().is_relative_to(self.data_dir)):
                    blockers.append("UNKNOWN_DATA_PROCESS")
            if any(Path(word).name in known | {"uvicorn", "gunicorn", "node_agent"} for word in words):
                blockers.append("OFFLINE_MAINTENANCE_REQUIRED")
            if "python" not in name:
                continue
            if command is None:
                blockers.append("PROCESS_INSPECTION_UNKNOWN")
                continue
            if any(marker in " ".join(words) for marker in ("multiprocessing", "spawn_main", "forkserver", "resource_tracker")):
                blockers.append("UNKNOWN_PLATFORM_CHILD_PROCESS")
            platform = any(Path(word).name in known | {"uvicorn", "gunicorn", "node_agent"} or word in {"uvicorn", "gunicorn", "node_agent"} for word in words)
            if platform:
                blockers.append("OFFLINE_MAINTENANCE_REQUIRED")
            elif info["pid"] != os.getpid():
                cwd = info.get("cwd")
                if cwd is None:
                    blockers.append("PROCESS_INSPECTION_UNKNOWN")
                elif (Path(cwd).resolve().is_relative_to(self.data_dir)
                      or Path(cwd).resolve() == Path(__file__).resolve().parent.parent):
                    blockers.append("UNKNOWN_DATA_PROCESS")
        return blockers

    def _task_evidence(self, db):
        blockers, evidence = [], []
        rows = db.execute("SELECT task_id,project_id,kind,status,worker_id,lease_expires_at,process_pid,process_create_time,process_command_hash FROM tasks ORDER BY task_id").fetchall()
        for row in rows:
            evidence.append(tuple(row))
            if row["status"] not in {"SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED"}:
                blockers.append("ACTIVE_TASK")
            if row["worker_id"] or row["lease_expires_at"]:
                blockers.append("TASK_LEASE_PRESENT")
            if row["process_pid"]:
                try:
                    if (psutil.pid_exists(int(row["process_pid"])) or
                            (os.name != "nt" and ProcessController._posix_group_exists(int(row["process_pid"])))):
                        blockers.append("PROCESS_PRESENT")
                    elif not row["process_create_time"] or not row["process_command_hash"]:
                        blockers.append("PROCESS_INSPECTION_UNKNOWN")
                except (OSError, psutil.Error):
                    blockers.append("PROCESS_INSPECTION_UNKNOWN")
            elif row["process_create_time"] or row["process_command_hash"]:
                blockers.append("PROCESS_INSPECTION_UNKNOWN")
            task_root = self.artifacts.root / self.artifacts._validate_task_id(row["task_id"])
            if _is_link_like(task_root) or _is_link_like(task_root / "failure.json"):
                blockers.append("TASK_EVIDENCE_UNVERIFIED")
                continue
            failure = self.artifacts.read_json(row["task_id"], "failure.json", default={})
            if (task_root / "failure.json").exists() and (not isinstance(failure, dict)
                    or type(failure.get("recoverable")) is not bool):
                blockers.append("UNKNOWN_RECOVERY_EVIDENCE")
            elif isinstance(failure, dict) and (failure.get("recoverable") or failure.get("checkpoint_available") or failure.get("recovery_action")):
                blockers.append("RECOVERY_DEPENDENCY")
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='worker_instances'").fetchone()
        if exists:
            now = datetime.now(timezone.utc).isoformat()
            for row in db.execute("SELECT instance_key,pid,expires_at FROM worker_instances ORDER BY instance_key"):
                evidence.append(tuple(row))
                if row["expires_at"] > now or psutil.pid_exists(int(row["pid"])):
                    blockers.append("WORKER_INSTANCE_PRESENT")
        return blockers, evidence

    def _source_configuration(self):
        path = self.data_dir / "storage/storage_sources.sqlite3"
        with closing(_readonly(path)) as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM storage_sources ORDER BY id")]
        # Other sources may point at a canonical path via a custom root. They
        # remain unsupported rather than assuming all remote aliases are absent.
        if len(rows) != 1 or rows[0]["id"] != "default_local" or rows[0]["type"] != "local" or not rows[0]["enabled"] or json.loads(rows[0]["config_json"]).get("root"):
            raise ValueError("unsupported custom/shared storage configuration")
        return rows

    @staticmethod
    def _file_identity(path):
        current = path
        while current.parent != current:
            if _is_link_like(current):
                raise ValueError("unsafe source link")
            current = current.parent
        info = path.stat()
        if not path.is_file() or info.st_nlink != 1 or info.st_size <= 0:
            raise ValueError("source is shared, special or empty")
        before = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        from PIL import Image
        with Image.open(path) as image:
            if image.format not in {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}:
                raise ValueError("unsupported original image format")
            image.verify()
        digest = file_sha256(path)
        after = path.stat()
        if before != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("source changed while hashing")
        return {"device": info.st_dev, "inode": info.st_ino, "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns, "sha256": digest}

    def _snapshot(self, project_id, retirement_task_id, image_id, *, quarantined=None, absent_identity=None):
        self._validate_runtime_paths()
        project_id, retirement_task_id, image_id = map(self._identifier, (project_id, retirement_task_id, image_id))
        blockers = []
        if not self.controlled_local_writers or os.environ.get("MC_CONTROLLED_LOCAL_MATERIAL_GC") != "1":
            blockers.append("CONTROLLED_MODE_REQUIRED")
        blockers.extend(self._offline_blockers())
        projects = self._projects()
        selected = self.data_dir / "projects" / project_id
        with closing(_readonly(selected / "materials.sqlite3")) as db:
            row = db.execute("SELECT * FROM material_retirements WHERE task_id=? AND image_id=?", (retirement_task_id, image_id)).fetchone()
            if row is None:
                raise KeyError("retired material does not exist")
            retired = dict(row)
        normalized = normalize_material(json.loads(retired["payload_json"]))
        if normalized["id"] != image_id or normalized["content_sha256"] != retired["content_sha256"] or normalized["storage_type"] != "local":
            blockers.append("RETIREMENT_IDENTITY_UNVERIFIED")
        if retired["storage_source_id"] != "default_local" or normalized["storage_source_id"] != "default_local" or normalized["object_key"] != retired["object_key"] or not retired["object_key"].startswith("uploads/"):
            blockers.append("UNSUPPORTED_STORAGE")
        original = selected / retired["object_key"]
        if original.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
            blockers.append("UNSUPPORTED_CONTENT_TYPE")
        with closing(_readonly(self.repository.path)) as db:
            owner_task = db.execute("SELECT project_id,kind FROM tasks WHERE task_id=?", (retirement_task_id,)).fetchone()
        if owner_task is None or owner_task["project_id"] != project_id or owner_task["kind"] != "MATERIAL_BATCH":
            blockers.append("RETIREMENT_OWNER_UNVERIFIED")
        if not original.resolve().is_relative_to(selected.resolve()):
            blockers.append("UNSAFE_PATH")
        if not self._local_disk(original):
            blockers.append("UNSUPPORTED_FILESYSTEM")
        inventories, references = [], []
        for project in projects:
            dbpath = project / "materials.sqlite3"
            if not dbpath.is_file():
                blockers.append("UNKNOWN_PROJECT_INDEX")
                continue
            try:
                with closing(_readonly(dbpath)) as db:
                    if db.execute("PRAGMA user_version").fetchone()[0] not in MATERIAL_READ_SCHEMA_VERSIONS:
                        blockers.append("UNKNOWN_PROJECT_INDEX")
                        continue
                    live = [dict(row) for row in db.execute("SELECT id,payload_json,storage_source_id,object_key FROM materials ORDER BY id")]
                    old = [dict(row) for row in db.execute("SELECT * FROM material_retirements ORDER BY task_id,image_id")]
                    deferred = [dict(row) for row in db.execute("SELECT * FROM material_cleanup_deferred ORDER BY cleanup_id")]
                    revision = db.execute("SELECT value FROM material_meta WHERE key='revision'").fetchone()[0]
                inventories.append([project.name, revision, live, old, deferred])
                for deferred_row in deferred:
                    pending = normalize_material(json.loads(deferred_row["payload_json"]))
                    if pending["storage_source_id"] != "default_local" or (project / pending["object_key"]).resolve() == original.resolve():
                        blockers.append("DEFERRED_CONSUMER_UNVERIFIED")
                # Legacy JSON can contain identities no longer indexed. Until a
                # dedicated manifest proves its shadow semantics, refuse it.
                if (project / "images.json").exists():
                    blockers.append("LEGACY_INDEX_UNVERIFIED")
                for live_row in live:
                    payload = normalize_material(json.loads(live_row["payload_json"]))
                    if payload["storage_source_id"] != "default_local" or (payload["storage_source_id"], payload["object_key"]) != (live_row["storage_source_id"], live_row["object_key"]):
                        blockers.append("UNKNOWN_PROJECT_INDEX")
                    candidate = project / payload["object_key"]
                    raw_path = str(payload.get("path") or payload.get("stored_path") or "")
                    if (payload["storage_source_id"] == "default_local" and candidate.resolve() == original.resolve()) or (raw_path and Path(raw_path).is_absolute() and Path(raw_path).resolve() == original.resolve()):
                        blockers.append("LIVE_REFERENCE")
                for old_row in old:
                    if old_row["storage_source_id"] != "default_local":
                        blockers.append("UNKNOWN_PROJECT_INDEX")
                    if old_row["storage_source_id"] == "default_local" and (project / old_row["object_key"]).resolve() == original.resolve():
                        references.append([project.name, old_row["task_id"], old_row["image_id"]])
                        if old_row["content_sha256"] != retired["content_sha256"]:
                            blockers.append("RETIRED_REFERENCE_CONFLICT")
                for folder in ("jobs", "runs", "deploy_jobs", "clean_jobs", "predictions"):
                    root = project / folder
                    if root.exists():
                        for entry in root.iterdir():
                            if _is_link_like(entry):
                                blockers.append("LEGACY_CONSUMER_UNVERIFIED")
                                continue
                            task_id = entry.name[6:] if folder == "runs" and entry.name.startswith("train_") else entry.name
                            with closing(_readonly(self.repository.path)) as task_db:
                                known = task_db.execute("SELECT project_id,status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
                            if known is None or known["project_id"] != project.name or known["status"] not in {"SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED"}:
                                blockers.append("LEGACY_CONSUMER_UNVERIFIED")
                            elif known["status"] in {"FAILED", "CANCELLED"} and entry.is_dir() and any(entry.rglob("*.pt")):
                                blockers.append("RECOVERY_DEPENDENCY")
            except (ValueError, OSError, KeyError, sqlite3.Error):
                blockers.append("UNKNOWN_PROJECT_INDEX")
        try:
            config = self._source_configuration()
        except (ValueError, OSError, sqlite3.Error):
            config = None
            blockers.append("UNSUPPORTED_SOURCE_CONFIGURATION")
        with closing(_readonly(self.repository.path)) as db:
            task_blockers, tasks = self._task_evidence(db)
        blockers.extend(task_blockers)
        known_owners = {(row[0], row[1], row[2]) for row in tasks if len(row) >= 4}
        if any((retired_task, project_name, "MATERIAL_BATCH") not in known_owners
               for project_name, retired_task, retired_image in references):
            blockers.append("RETIREMENT_OWNER_UNVERIFIED")
        identity = None
        source = Path(quarantined) if quarantined is not None else original
        try:
            identity = self._file_identity(source)
            if (not re.fullmatch(r"[0-9a-f]{64}", retired["content_sha256"])
                    or identity["sha256"] != retired["content_sha256"]
                    or identity["size_bytes"] != int(normalized.get("size_bytes") or 0)):
                blockers.append("SOURCE_IDENTITY_MISMATCH")
        except FileNotFoundError:
            if absent_identity is not None:
                identity = absent_identity
            else:
                blockers.append("SOURCE_MISSING")
        except (ValueError, OSError):
            blockers.append("SOURCE_IDENTITY_UNVERIFIED")
        evidence = {"projects": inventories, "references": references, "configuration": config,
                    "tasks": tasks, "retired": retired, "identity": identity}
        return {"eligible": not blockers, "blockers": sorted(set(blockers)), "fingerprint": _digest(evidence),
                "source": str(original), "source_identity": identity, "retired_references": references,
                "mode": "offline-controlled-local-only", "physical_space_released": None,
                "_evidence": evidence, "_projects": [str(project) for project in projects]}

    def preview(self, project_id, retirement_task_id, image_id):
        return self._snapshot(project_id, retirement_task_id, image_id)

    def _receipt_path(self, task_id, ref):
        self._validate_runtime_paths()
        current = self.artifacts.root
        for part in (self._identifier(task_id), *Path(ref).parts):
            current = current / part
            if _is_link_like(current):
                raise RuntimeError("UNSAFE_RECLAMATION_RECEIPT")
        return current

    def _write_receipt(self, task_id, ref, receipt):
        path = self._receipt_path(task_id, ref)
        payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
        self.artifacts.atomic_write_json(task_id, ref, {**payload, "receipt_digest": _digest(payload)})
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _unlink_quarantined(self, path):
        path.unlink()

    @staticmethod
    def _audit_key(request, operation_id):
        return _digest({"request": request, "operation_id": operation_id})

    def _audit_references(self, receipt, *, preflight=False, absent=False):
        key = self._audit_key(receipt["request"], receipt["operation_id"])
        for project_name, retired_task, retired_image in receipt["retired_references"]:
            owner = object.__new__(MaterialRepository)
            owner.project_path = self.data_dir / "projects" / project_name
            owner.path = owner.project_path / "materials.sqlite3"
            if preflight:
                with closing(_readonly(owner.path)) as db:
                    old = db.execute("SELECT action,old_sha256,new_sha256 FROM material_storage_audit WHERE task_id=? AND image_id=?",
                                     ("physical_" + key, retired_image)).fetchone()
                if old and (old["action"] not in {"PHYSICAL_RECLAIMED", "PHYSICAL_ABSENT_AFTER_DETACH"}
                            or old["old_sha256"] != receipt["source_identity"]["sha256"] or old["new_sha256"] != ""):
                    raise RuntimeError("RECLAMATION_AUDIT_CONFLICT")
            else:
                owner.record_physical_reclamation_audit(key, retired_image, receipt["source_identity"]["sha256"], absent=absent)

    def apply(self, project_id, retirement_task_id, image_id, *, expected_fingerprint,
              operation_id, confirmed=False, actor=""):
        self._validate_runtime_paths()
        if confirmed is not True or not str(actor).strip():
            raise ValueError("explicit confirmation and real actor are required")
        operation_id = self._identifier(operation_id)
        self._identifier(retirement_task_id)
        ref = f"physical-reclamation/{operation_id}.json"
        self._receipt_path(retirement_task_id, ref)
        receipt = self.artifacts.read_json(retirement_task_id, ref, default={})
        request = [str(project_id), str(retirement_task_id), str(image_id)]
        if receipt:
            if receipt.get("receipt_digest") != _digest({key: value for key, value in receipt.items() if key != "receipt_digest"}):
                raise RuntimeError("RECLAMATION_RECEIPT_UNVERIFIED")
            with closing(_readonly(self.data_dir / "projects" / self._identifier(project_id) / "materials.sqlite3")) as db:
                current_retirement = db.execute("SELECT * FROM material_retirements WHERE task_id=? AND image_id=?", (retirement_task_id, image_id)).fetchone()
            if current_retirement is None or _digest(dict(current_retirement)) != receipt.get("retirement_digest"):
                raise RuntimeError("RECLAMATION_RECEIPT_UNVERIFIED")
            if receipt.get("request") != request or receipt.get("fingerprint") != expected_fingerprint:
                raise RuntimeError("RECLAMATION_OPERATION_CONFLICT")
            if receipt.get("status") in {"deleted", "absent_after_detach"}:
                return {**receipt, "status": "already_deleted" if receipt["status"] == "deleted" else "already_absent", "deleted_logical_bytes": 0}
        try:
            with ExitStack() as stack:
                stack.enter_context(controlled_local_startup_guard(self.data_dir, timeout=0))
                projects = self._projects()
                for project in projects:
                    stack.enter_context(material_annotation_lifecycle_fence(project, timeout=0))
                sources = self.data_dir / "storage/storage_sources.sqlite3"
                stack.enter_context(storage_source_lifecycle_fence(sources, timeout=0))
                selected = self.data_dir / "projects" / self._identifier(project_id)
                if receipt:
                    quarantine = Path(receipt["quarantine"])
                    original = Path(receipt["source"])
                    expected_quarantine = selected / ".material-reclaim" / operation_id
                    if quarantine != expected_quarantine:
                        raise RuntimeError("RECLAMATION_RECEIPT_UNVERIFIED")
                    if original.exists() and quarantine.exists():
                        raise RuntimeError("RECLAMATION_SOURCE_REAPPEARED")
                else:
                    quarantine = selected / ".material-reclaim" / operation_id
                    original = None
                absent_after_detach = bool(receipt and receipt.get("status") == "detached" and not original.exists() and not quarantine.exists())
                truth = self._snapshot(project_id, retirement_task_id, image_id,
                    quarantined=quarantine if quarantine.exists() else None,
                    absent_identity=receipt["source_identity"] if absent_after_detach else None)
                if not truth["eligible"]:
                    raise RuntimeError(",".join(truth["blockers"]))
                detached_resume = bool(receipt and not Path(truth["source"]).exists()
                                       and (quarantine.exists() or absent_after_detach))
                if detached_resume:
                    if truth["retired_references"] != receipt["retired_references"]:
                        raise RuntimeError("RECLAMATION_PREVIEW_STALE")
                elif truth["fingerprint"] != expected_fingerprint:
                    raise RuntimeError("RECLAMATION_PREVIEW_STALE")
                original = Path(truth["source"])
                if receipt and truth["source_identity"] != receipt["source_identity"]:
                    raise RuntimeError("RECLAMATION_RECEIPT_UNVERIFIED")
                provider = LocalStorageProvider("default_local", selected)
                stack.enter_context(provider.byte_lease(original.relative_to(selected).as_posix(), timeout=0))
                # Rehash only the selected file under its byte lease; no task DB
                # write transaction is held during hashing/inventory preparation.
                checked = (receipt["source_identity"] if absent_after_detach else
                    self._file_identity(quarantine if quarantine.exists() else original))
                if checked != truth["source_identity"]:
                    raise RuntimeError("RECLAMATION_PREVIEW_STALE")
                if _is_link_like(quarantine.parent) or _is_link_like(quarantine):
                    raise RuntimeError("UNSAFE_QUARANTINE")
                quarantine.parent.mkdir(exist_ok=True)
                receipt = {"schema_version": 1, "status": "detached" if absent_after_detach else "prepared", "request": request,
                    "fingerprint": expected_fingerprint, "operation_id": operation_id, "actor": str(actor),
                    "retirement_digest": _digest(truth["_evidence"]["retired"]),
                    "source": str(original), "quarantine": str(quarantine), "source_identity": checked,
                    "retired_references": truth["retired_references"], "deleted_logical_bytes": 0,
                    "physical_space_released": None}
                self._audit_references(receipt, preflight=True)
                self._write_receipt(retirement_task_id, ref, receipt)
                with self.repository.source_reclamation_guard() as db:
                    current_blockers, current_tasks = self._task_evidence(db)
                    if current_blockers or self._offline_blockers() or current_tasks != truth["_evidence"]["tasks"]:
                        raise RuntimeError("RECLAMATION_PREVIEW_STALE")
                    if self._projects() != projects:
                        raise RuntimeError("RECLAMATION_PREVIEW_STALE")
                    if absent_after_detach:
                        receipt.update(status="absent_after_detach", deleted_logical_bytes=0)
                        self._audit_references(receipt, absent=True)
                        self._write_receipt(retirement_task_id, ref, receipt)
                        return receipt
                    active_source = quarantine if quarantine.exists() else original
                    info = active_source.stat()
                    if (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns, info.st_nlink) != (checked["inode"], checked["device"], checked["size_bytes"], checked["mtime_ns"], 1):
                        raise RuntimeError("RECLAMATION_PREVIEW_STALE")
                    if not quarantine.exists():
                        os.replace(original, quarantine)
                    receipt["status"] = "detached"
                    self._write_receipt(retirement_task_id, ref, receipt)
                    self._unlink_quarantined(quarantine)
                self._audit_references(receipt)
                receipt.update(status="deleted", deleted_logical_bytes=checked["size_bytes"],
                               deleted_at=datetime.now(timezone.utc).isoformat())
                self._write_receipt(retirement_task_id, ref, receipt)
                return receipt
        except Timeout as error:
            raise RuntimeError("SOURCE_OR_REFERENCE_BUSY") from error
