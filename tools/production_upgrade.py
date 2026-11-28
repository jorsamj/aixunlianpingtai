#!/usr/bin/env python3
"""Guarded release of the existing Git-worktree systemd production installation.

This operator-invoked tool validates branch/worktree/service/task state and
performs a pinned fast-forward plus tracked-file permission normalization.  It
can additionally take a verified, per-database transaction-consistent snapshot
of the control-plane SQLite databases before an upgrade, and restore that
snapshot during an explicit, acknowledged rollback.  The snapshot is not a
cross-database atomic or disaster-recovery backup (see M10-B below).

Backup scope is limited to the control-plane SQLite databases:
  task_runtime/tasks.sqlite3
  storage/storage_sources.sqlite3
  model_artifacts/artifacts.sqlite3
  external_algorithm_publish/publications.sqlite3
  projects/<project_id>/*.sqlite3   (top-level files only)

Task artifacts and material/media objects are content-addressed immutable
files and are NOT backed up by this tool; ``backup.json`` records that scope in
its ``exclusions`` list so an operator never mistakes the snapshot for a full
data backup.  Git cannot restore database changes, and this tool never claims
otherwise.  Nothing in this module is executed automatically by the platform.

M10-A coordination contract
---------------------------
A database restore and an application-version rollback are separate, explicit
actions:

* ``restore_data_backup(..., app_sha=None)`` restores only the recorded SQLite
  databases and returns ``application_rollback="not_requested"``.  The caller
  must not infer that the application code changed.
* ``restore_data_backup(..., app_sha=<40 hex>)`` / ``--rollback-application-to``
  performs a coordinated rollback: verify backup -> validate clean worktree and
  allowed ancestor -> fail-closed schema compatibility -> stop services ->
  non-destructive ``git checkout --detach <app_sha>`` -> restore tracked file
  modes -> restore databases -> start -> verify application SHA, restored
  database SHA256/quick_check and web health.  A failure leaves the services
  stopped and never performs a second automatic rollback.

``backup.json`` is bound to the application identity (previous/target SHA,
``VERSION.txt``, build id), the absolute data directory, the probed database
schema and the explicit backup scope/exclusions.  Schema compatibility is
fail-closed: an unreadable backup database, an unknown database kind or an
unreadable expected schema version blocks a coordinated rollback instead of
guessing a migration direction.

M10-B consistency boundary
--------------------------
A backup is a per-database SQLite online-backup snapshot, not a cross-database
atomic or business-consistent snapshot.  ``write_silence`` is therefore
``unverified`` with an explicit reason, and read-only runtime probes record
active tasks, unreleased execution-resource holds, the worker build marker and
recently heartbeating service agents; any positive probe refuses the backup by
default and ``--force-idle`` only records the override without claiming
consistency.  Raw material/media objects, model files, training
artifacts/checkpoints and other project business files are explicitly out of
scope: this tool must never be described as a disaster-recovery backup.

N6.1 remaining safety boundaries
--------------------------------
* Application identity binding: ``backup.json`` records the deployed frontend
  build identity (``static/vue-catalog/offline-assets.json`` and
  ``static/vue-app/offline-assets.json`` receipts, ``UI_BUILD_VERSION`` and the
  verified worktree asset hashes) and a Python dependency fingerprint
  (``requirements*.txt`` digests plus installed key distributions).  Both are
  explicit ``unavailable`` when they cannot be read; the frontend build
  receipts are gitignored build output, so a coordinated rollback cannot
  restore them from Git and the rollback result reports that explicitly.
* systemd configuration: before/after ``--apply`` upgrade the unit files,
  drop-ins and environment files are hashed read-only and compared.  A
  difference is reported as an explicit risk field; this tool never edits a
  unit or environment file.
* After the services are stopped, the runtime activity probes (active tasks,
  unreleased holds, agent heartbeats, worker build marker) are re-checked and
  any positive evidence fails closed.  Only the explicit ``--force-idle``
  override records a forced decision; the tool never forces automatically.
* A coordinated rollback deliberately leaves the worktree on a detached HEAD.
  A later ``--target`` upgrade is refused until the release branch is restored
  explicitly (the exact ``git switch`` command is printed); this tool never
  switches branches or merges on its own.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.metadata
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

BRANCH = "feature/external-algorithm-publishing"
TERMINAL_STATES = frozenset({
    "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED",
    "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE",
})
WEB_UNIT = "changlian-web.service"
WORKER_UNIT = "changlian-worker.service"

BACKUP_SCHEMA_VERSION = 1
BACKUP_MANIFEST_NAME = "backup.json"
DEFAULT_MAX_BACKUP_BYTES = 512 * 1024 * 1024
BACKUP_SPACE_MULTIPLIER = 2
BACKUP_SPACE_RESERVE_BYTES = 64 * 1024 * 1024
PRE_ROLLBACK_DIRECTORY = "pre-rollback"
CONTROL_DATABASE_RELATIVE_PATHS = (
    Path("task_runtime") / "tasks.sqlite3",
    Path("storage") / "storage_sources.sqlite3",
    Path("model_artifacts") / "artifacts.sqlite3",
    Path("external_algorithm_publish") / "publications.sqlite3",
)
PROJECT_DATABASE_GLOB = "*.sqlite3"
BACKUP_EXCLUSIONS = (
    {
        "path": "task_runtime/artifacts/**",
        "reason": (
            "content-addressed immutable task artifacts (payloads, selections, "
            "logs, reports) are not backed up by this tool"
        ),
    },
    {
        "path": "projects/<project_id>/** (non-SQLite files)",
        "reason": (
            "material/media objects stored under the project directory (the "
            "default local storage root) are immutable content-addressed files "
            "and are not backed up; only the top-level *.sqlite3 catalogs are"
        ),
    },
    {
        "path": "storage/<source_id>/**",
        "reason": (
            "local storage source roots are not backed up; remote/S3/OSS "
            "objects live outside this host"
        ),
    },
    {
        "path": "model_artifacts/** and external_algorithm_publish/** "
                "(except the SQLite database files)",
        "reason": (
            "model weight/publication payload files and configuration are not "
            "backed up by this tool; only the SQLite catalogs are captured"
        ),
    },
    {
        "path": "cache/**, imports/**, external_cleanup_recovery/**, "
                "*.lock, *.log",
        "reason": (
            "regenerable caches, import staging, cleanup recovery records, "
            "locks and logs are not backed up"
        ),
    },
    {
        "path": "material/media objects (project storage roots, object-key files)",
        "reason": (
            "raw material/media bytes are immutable content-addressed objects "
            "and are NOT backed up by this tool; they are not recoverable from "
            "this snapshot"
        ),
    },
    {
        "path": "model files and weights (*.pt, *.onnx, *.bmodel, *.sophon and "
                "model_artifacts/** non-SQLite payloads)",
        "reason": (
            "model weight files and converted model payloads are NOT backed up; "
            "re-install/transfer them through their owning system"
        ),
    },
    {
        "path": "training artifacts and checkpoints (task_runtime/artifacts/**, "
                "**/checkpoints/**, training logs and reports)",
        "reason": (
            "training artifacts and checkpoints are content-addressed task "
            "payloads and are NOT backed up by this tool"
        ),
    },
    {
        "path": "other project business files under projects/<project_id>/** "
                "(non-SQLite files, algorithm JSON sidecars, imports)",
        "reason": (
            "project business files other than the top-level SQLite catalogs "
            "are NOT backed up by this tool"
        ),
    },
)

VERSION_FILE_NAME = "VERSION.txt"
WORKER_BUILD_MARKER_RELATIVE_PATH = Path("task_runtime") / "worker-build.json"
HEARTBEAT_TTL_SECONDS = 45  # Mirrors platform_core.service_nodes.HEARTBEAT_TTL_SECONDS.
WRITE_SILENCE_UNVERIFIED = "unverified"
WRITE_SILENCE_REASON = (
    "control-plane services were not stopped and the snapshot is a per-database "
    "SQLite online backup; cross-database write silence and business "
    "consistency cannot be proven"
)
BACKUP_SCOPE_DESCRIPTION = (
    "control-plane SQLite catalogs only: task_runtime/tasks.sqlite3, "
    "storage/storage_sources.sqlite3, model_artifacts/artifacts.sqlite3, "
    "external_algorithm_publish/publications.sqlite3 and top-level "
    "projects/<project_id>/*.sqlite3 files"
)
CONSISTENCY_STATEMENT = {
    "snapshot_kind": "per_database_online_backup",
    "cross_database_atomic": False,
    "business_consistency": "unverified",
    "disaster_recovery": False,
    "note": (
        "NOT a disaster-recovery backup. Only the control-plane SQLite "
        "catalogs listed in backup_scope are captured; raw material/media "
        "objects, model files, training artifacts/checkpoints and other "
        "project business files are excluded (see exclusions)."
    ),
}

# N6.1: deployed frontend build identity receipts and the Python dependency
# fingerprint bound into backup.json.  The frontend build output directories
# are gitignored, so these receipts identify the deployed build but cannot be
# restored by a Git checkout during a coordinated rollback.
FRONTEND_BUILD_RECEIPTS = (
    "static/vue-catalog/offline-assets.json",
    "static/vue-app/offline-assets.json",
)
UI_BUILD_VERSION_PATH = "static/main.mjs"
PYTHON_REQUIREMENTS_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "remote_web_requirements.txt",
)
KEY_PYTHON_DISTRIBUTIONS = (
    "fastapi",
    "uvicorn",
    "starlette",
    "pydantic",
    "python-multipart",
    "pillow",
    "pyyaml",
    "requests",
    "ultralytics",
    "opencv-python",
    "onnx",
    "onnxruntime",
    "torch",
    "torchvision",
    "psutil",
    "keyring",
    "cryptography",
    "filelock",
    "boto3",
    "oss2",
)
SYSTEMD_CONFIG_RISK_CODE = "SYSTEMD_CONFIGURATION_CHANGED_DURING_UPGRADE"

# Read-only schema expectations used by the coordinated rollback fail-closed
# check.  ``source_path``/``version_pattern`` describe where the running code
# declares the schema version it expects; ``tables`` is the critical
# table/column whitelist that must already exist in the backup database.
SCHEMA_REQUIREMENTS: dict[str, dict] = {
    "tasks": {
        "source_path": "platform_core/task_runtime/repository.py",
        "version_pattern": r"^_SCHEMA_VERSION\s*=\s*(\d+)\s*$",
        "version_probe": "user_version",
        "tables": {
            "tasks": ("task_id", "project_id", "kind", "status"),
            "worker_instances": ("instance_key", "worker_id", "build_id"),
            "execution_resource_holds": ("task_id", "node_id", "state"),
        },
    },
    "storage_sources": {
        "source_path": None,
        "version_pattern": None,
        "version_probe": "none",
        "tables": {"storage_sources": ("id", "name", "type", "config_json")},
    },
    "model_artifacts": {
        "source_path": None,
        "version_pattern": None,
        "version_probe": "none",
        "tables": {
            "model_artifacts": (
                "artifact_id", "project_id", "version_id", "target", "sha256",
            ),
        },
    },
    "publications": {
        "source_path": "platform_core/external_algorithm_publish.py",
        "version_pattern": r"^PUBLICATION_SCHEMA_VERSION\s*=\s*(\d+)\s*$",
        "version_probe": "none",
        "tables": {
            "external_version_publications": (
                "publication_key", "project_id", "algorithm_id", "version_id",
            ),
            "external_model_artifacts": ("artifact_id", "publication_key"),
            "external_artifact_publications": ("mapping_id", "artifact_id"),
        },
    },
    "materials": {
        "source_path": "platform_core/material_repository.py",
        "version_pattern": r"^_SCHEMA_VERSION\s*=\s*(\d+)\s*$",
        "version_probe": "user_version",
        "tables": {
            "materials": ("id", "storage_source_id", "object_key", "payload_json"),
        },
    },
    "annotations": {
        "source_path": "platform_core/annotation_repository.py",
        "version_pattern": r"^_SCHEMA_VERSION\s*=\s*(\d+)\s*$",
        "version_probe": "user_version",
        "tables": {
            "annotations": ("image_id", "annotation_state", "version"),
        },
    },
    "algorithms": {
        "source_path": "platform_core/algorithm_sql_store.py",
        "version_pattern": r"^SCHEMA_VERSION\s*=\s*(\d+)\s*$",
        "version_probe": "meta",
        "meta_table": "algorithm_store_meta",
        "meta_key": "schema_version",
        "tables": {
            "algorithms": ("id", "project_id", "name"),
            "algorithm_versions": ("id", "algorithm_id"),
        },
    },
    "online_feedback": {
        "source_path": "platform_core/online_feedback.py",
        "version_pattern": r"^SCHEMA_VERSION\s*=\s*(\d+)\s*$",
        "version_probe": "none",
        "tables": {
            "online_feedback": (
                "id", "prediction_id", "status", "algorithm_id", "version_id",
            ),
        },
    },
    "material_history_index": {
        "source_path": None,
        "version_pattern": None,
        "version_probe": "none",
        "tables": {"references_by_image": ("image_id", "reasons_json")},
    },
    "training_scope_review_plans": {
        "source_path": None,
        "version_pattern": None,
        "version_probe": "none",
        "tables": {"plans": ("id", "project_id"), "items": ("plan_id", "image_id")},
    },
}
PROJECT_DATABASE_KINDS = {
    "materials.sqlite3": "materials",
    "annotations.sqlite3": "annotations",
    "algorithms.sqlite3": "algorithms",
    "online_feedback.sqlite3": "online_feedback",
    "material-history-reference-index.sqlite3": "material_history_index",
    "training_scope_review_plans.sqlite3": "training_scope_review_plans",
}
APPLICATION_ROLLBACK_NOT_REQUESTED = "not_requested"
APPLICATION_ROLLBACK_PLANNED = "planned"
APPLICATION_ROLLBACK_APPLIED = "applied"


class UpgradeRefused(RuntimeError):
    pass


class PartialRestoreFailed(UpgradeRefused):
    """A database restore failed after replacing at least one database file.

    ``diagnostics`` is the structured ``partial_restore`` report (which files
    were replaced/failed/not attempted plus the pre-rollback safety snapshot).
    Services are left stopped; a retry is idempotent because already-restored
    files are re-verified and skipped.
    """

    def __init__(self, message: str, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics


def command(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False,
    )
    if proc.returncode:
        raise UpgradeRefused(
            f"{' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _git_output(repo: Path, *args: str) -> tuple[int, str, str]:
    """Read-only git probe that never raises; returns (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        return 127, "", str(exc)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _read_code_text(repo: Path | None, sha: str | None, relative_path: str) -> str | None:
    """Read one repository source file from the worktree or a commit (read-only)."""
    if repo is None:
        return None
    repo = Path(repo)
    if sha is not None:
        code, output, _ = _git_output(repo, "show", f"{sha}:{relative_path}")
        return output if code == 0 and output else None
    candidate = repo / relative_path
    if candidate.is_symlink() or not candidate.is_file():
        return None
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        return None


def read_application_version(repo: Path | None) -> str:
    """Read VERSION.txt content; record ``unavailable`` when it cannot be read."""
    text = _read_code_text(repo, None, VERSION_FILE_NAME)
    if text is None:
        return "unavailable"
    value = text.strip()
    return value if value else "unavailable"


_BUILD_FINGERPRINT_FILES = (
    "app.py",
    "launcher.py",
    "task_worker.py",
    "train_worker.py",
    "platform_core/task_runtime/repository.py",
    "platform_core/training_tasks.py",
)


def resolve_build_identity(repo: Path | None) -> str:
    """Equivalent read-only build id of platform_core.build_identity.resolve_build_id.

    The production platform resolves its build id from MC_BUILD_REVISION, the
    worktree HEAD, or a bounded source fingerprint.  This tool reproduces that
    resolution without importing the platform package.
    """
    explicit = os.environ.get("MC_BUILD_REVISION", "").strip()
    if explicit:
        return explicit[:128]
    if repo is None:
        return "unavailable"
    root = Path(repo).resolve()
    if (root / ".git").exists():
        code, output, _ = _git_output(root, "rev-parse", "HEAD")
        if code == 0 and re.fullmatch(r"[0-9a-f]{40}", output):
            return output
    digest = hashlib.sha256()
    count = 0
    for relative in _BUILD_FINGERPRINT_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        count += 1
    return f"src-{digest.hexdigest()[:20]}" if count else "unavailable"


def _read_repo_bytes(
    repo: Path | None, sha: str | None, relative_path: str,
) -> bytes | None:
    """Read one repository file as bytes from the worktree or a commit (read-only)."""
    if repo is None:
        return None
    repo = Path(repo)
    if sha is not None:
        try:
            proc = subprocess.run(
                ["git", "show", f"{sha}:{relative_path}"],
                cwd=repo, capture_output=True, check=False,
            )
        except OSError:
            return None
        return proc.stdout if proc.returncode == 0 and proc.stdout else None
    candidate = repo / relative_path
    if candidate.is_symlink() or not candidate.is_file():
        return None
    try:
        return candidate.read_bytes()
    except OSError:
        return None


def _safe_relative_asset_name(name: object) -> str | None:
    """Validate a receipt asset path; reject traversal, absolute and URI names."""
    if not isinstance(name, str) or not name:
        return None
    if name.startswith("/") or "\\" in name or ":" in name:
        return None
    if any(part in ("", ".", "..") for part in name.split("/")):
        return None
    return name


def _frontend_receipt_entry(
    repo: Path,
    relative_path: str,
    *,
    source_sha: str | None,
) -> dict:
    """Parse and (for a worktree read) re-hash one frontend build receipt."""
    directory = PurePosixPath(relative_path).parent
    entry: dict = {
        "path": relative_path,
        "status": "unavailable",
        "reason": None,
        "receipt_sha256": None,
        "bytes": None,
        "receipt_code_sha": None,
        "build_origin": None,
        "asset_count": None,
        "assets_digest": None,
        "asset_verification": "code_ref" if source_sha else "worktree_hashes",
        "verified_asset_bytes": 0,
        "verified_asset_errors": [],
    }
    raw = _read_repo_bytes(repo, source_sha, relative_path)
    if raw is None:
        entry["reason"] = "RECEIPT_MISSING"
        return entry
    entry["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    entry["bytes"] = len(raw)
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        entry["status"] = "invalid"
        entry["reason"] = f"RECEIPT_UNPARSEABLE: {exc}"
        return entry
    assets = receipt.get("assets") if isinstance(receipt, dict) else None
    if not isinstance(assets, dict):
        entry["status"] = "invalid"
        entry["reason"] = "RECEIPT_ASSETS_INVALID"
        return entry
    recorded_sha = receipt.get("sha")
    entry["receipt_code_sha"] = recorded_sha if isinstance(recorded_sha, str) else None
    origin = receipt.get("build_origin")
    entry["build_origin"] = origin if isinstance(origin, str) else None
    normalized: dict[str, dict] = {}
    problems: list[str] = []
    for name, record in assets.items():
        safe_name = _safe_relative_asset_name(name)
        if safe_name is None:
            problems.append(f"UNSAFE_ASSET_NAME:{name!r}")
            continue
        sha256 = record.get("sha256") if isinstance(record, dict) else None
        size = record.get("bytes") if isinstance(record, dict) else None
        if (
            not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            problems.append(f"INVALID_ASSET_RECORD:{name!r}")
            continue
        normalized[safe_name] = {"sha256": sha256, "bytes": size}
    entry["asset_count"] = len(normalized)
    entry["assets_digest"] = (
        hashlib.sha256(_canonical_json(normalized)).hexdigest()
        if normalized else None
    )
    if problems:
        entry["status"] = "invalid"
        entry["reason"] = "; ".join(problems[:5])
        return entry
    if source_sha is None:
        # The receipt only proves something if the deployed bytes still match
        # it.  A rebuilt or partially copied build must not read as clean.
        for name, record in sorted(normalized.items()):
            data = _read_repo_bytes(repo, None, str(directory / name))
            if data is None:
                entry["verified_asset_errors"].append(f"MISSING_ASSET:{name}")
                continue
            if len(data) != record["bytes"]:
                entry["verified_asset_errors"].append(f"ASSET_SIZE_MISMATCH:{name}")
                continue
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                entry["verified_asset_errors"].append(f"ASSET_SHA256_MISMATCH:{name}")
                continue
            entry["verified_asset_bytes"] += len(data)
        if entry["verified_asset_errors"]:
            entry["status"] = "invalid"
            entry["reason"] = "; ".join(entry["verified_asset_errors"][:5])
            return entry
    entry["status"] = "ok"
    return entry


def resolve_frontend_build_identity(
    repo: Path | None,
    *,
    code_sha: str | None = None,
    expected_code_sha: str | None = None,
) -> dict:
    """Read-only deployed frontend build identity (N6.1).

    ``repo`` is read from the worktree unless ``code_sha`` names a commit to
    read instead.  The known build receipts are parsed, unsafe asset names are
    rejected, every worktree asset is re-hashed (a receipt that no longer
    matches the deployed bytes is ``invalid``), and the receipt code SHA is
    compared with ``expected_code_sha`` when both are full 40-character SHAs.
    The returned ``identity`` is a stable digest of the parsed receipts; it is
    ``unavailable`` with an explicit reason when nothing can be proven.
    """
    result: dict = {
        "status": "unavailable",
        "reason": "NO_REPOSITORY_REFERENCE",
        "identity": None,
        "receipt_code_sha": None,
        "build_origin": None,
        "matches_code_sha": "unknown",
        "expected_code_sha": expected_code_sha,
        "source": "code" if code_sha is not None else "worktree",
        "ui_build_version": None,
        "verified_asset_bytes": 0,
        "receipts": [],
    }
    if repo is None:
        return result
    repo = Path(repo)
    receipts = [
        _frontend_receipt_entry(repo, relative_path, source_sha=code_sha)
        for relative_path in FRONTEND_BUILD_RECEIPTS
    ]
    result["receipts"] = receipts
    ok = [entry for entry in receipts if entry["status"] == "ok"]
    invalid = [entry for entry in receipts if entry["status"] == "invalid"]
    missing = [entry["path"] for entry in receipts if entry["status"] == "unavailable"]
    if ok:
        result["identity"] = hashlib.sha256(_canonical_json(
            {entry["path"]: entry["receipt_sha256"] for entry in ok}
        )).hexdigest()
        result["verified_asset_bytes"] = sum(
            entry["verified_asset_bytes"] for entry in ok
        )
        receipt_code_sha = next(
            (
                entry["receipt_code_sha"]
                for entry in ok
                if isinstance(entry["receipt_code_sha"], str)
                and re.fullmatch(r"[0-9a-f]{40}", entry["receipt_code_sha"])
            ),
            None,
        )
        result["receipt_code_sha"] = receipt_code_sha
        result["build_origin"] = next(
            (entry["build_origin"] for entry in ok if entry["build_origin"]),
            None,
        )
        if (
            receipt_code_sha is not None
            and isinstance(expected_code_sha, str)
            and re.fullmatch(r"[0-9a-f]{40}", expected_code_sha)
        ):
            result["matches_code_sha"] = receipt_code_sha == expected_code_sha
    ui_build = _read_repo_bytes(repo, code_sha, UI_BUILD_VERSION_PATH)
    if ui_build is not None:
        try:
            ui_build_text = ui_build.decode("utf-8")
        except UnicodeDecodeError:
            ui_build_text = ""
        match = re.search(
            r"UI_BUILD_VERSION\s*=\s*'([^'\r\n]{1,128})'", ui_build_text,
        )
        if match is not None:
            result["ui_build_version"] = match.group(1)
    if invalid:
        result["status"] = "invalid"
        result["reason"] = "; ".join(
            f"{entry['path']}: {entry['reason']}" for entry in invalid[:3]
        )
    elif not ok:
        result["status"] = "unavailable"
        result["reason"] = "FRONTEND_BUILD_RECEIPTS_UNAVAILABLE: " + ", ".join(missing)
    elif missing:
        result["status"] = "partial"
        result["reason"] = "MISSING_RECEIPTS: " + ", ".join(missing)
    else:
        result["status"] = "ok"
    return result


def _installed_distribution_version(name: str) -> str | None:
    """Read one installed distribution version; ``None`` when unavailable."""
    try:
        return importlib.metadata.version(name)
    except (importlib.metadata.PackageNotFoundError, ValueError):
        return None
    except Exception:  # noqa: BLE001 - never let a metadata quirk fail a backup
        return None


def resolve_python_dependency_fingerprint(
    repo: Path | None, *, code_sha: str | None = None,
) -> dict:
    """Read-only Python dependency fingerprint (N6.1).

    Records the digest of every present requirements file and the installed
    versions of the key distributions.  Everything is best effort: missing
    requirements and unavailable package metadata are recorded as explicit
    ``unavailable`` values instead of being guessed, and this never installs or
    upgrades anything.
    """
    result: dict = {
        "status": "unavailable",
        "reason": "NO_REQUIREMENTS_AND_NO_INSTALLED_PACKAGES",
        "requirements": [],
        "requirements_digest": None,
        "installed": {},
        "installed_count": 0,
        "key_packages": list(KEY_PYTHON_DISTRIBUTIONS),
        "fingerprint": None,
        "source": "code" if code_sha is not None else "worktree",
    }
    requirements: list[dict] = []
    if repo is not None:
        for relative_path in PYTHON_REQUIREMENTS_FILES:
            raw = _read_repo_bytes(repo, code_sha, relative_path)
            if raw is None:
                continue
            requirements.append({
                "path": relative_path,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
    result["requirements"] = requirements
    if requirements:
        result["requirements_digest"] = hashlib.sha256(_canonical_json(
            {entry["path"]: entry["sha256"] for entry in requirements}
        )).hexdigest()
    installed: dict[str, str] = {}
    for name in KEY_PYTHON_DISTRIBUTIONS:
        version = _installed_distribution_version(name)
        if version:
            installed[name] = version
    result["installed"] = installed
    result["installed_count"] = len(installed)
    payload = {
        "requirements": result["requirements_digest"],
        "installed": installed,
    }
    if result["requirements_digest"] is not None or installed:
        result["fingerprint"] = hashlib.sha256(
            _canonical_json(payload)
        ).hexdigest()
        result["status"] = (
            "ok" if result["requirements_digest"] is not None and installed
            else "partial"
        )
        result["reason"] = None
    return result


def _unavailable_frontend_identity(reason: str) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "identity": None,
        "receipt_code_sha": None,
        "build_origin": None,
        "matches_code_sha": "unknown",
        "expected_code_sha": None,
        "source": "none",
        "ui_build_version": None,
        "verified_asset_bytes": 0,
        "receipts": [],
    }


def _unavailable_python_dependencies(reason: str) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "requirements": [],
        "requirements_digest": None,
        "installed": {},
        "installed_count": 0,
        "key_packages": list(KEY_PYTHON_DISTRIBUTIONS),
        "fingerprint": None,
        "source": "none",
    }


def assess_application_identity_binding(
    manifest: dict, repo: Path | None, *, app_sha: str | None,
) -> dict:
    """Compare the backup's recorded identities with what is deployed now.

    This never changes data or code.  It records explicit ``risks`` when the
    deployed frontend build changed since the backup, when that build receipt
    is bound to a different code SHA than the rollback target, or when the
    Python environment drifted.  The frontend build output is gitignored build
    output, so ``frontend_build.restorable_by_git`` documents that a Git
    checkout cannot restore it.
    """
    recorded_frontend = manifest.get("frontend_build")
    if not isinstance(recorded_frontend, dict):
        recorded_frontend = _unavailable_frontend_identity(
            "MANIFEST_PREDATES_FRONTEND_BUILD_BINDING"
        )
    recorded_dependencies = manifest.get("python_dependencies")
    if not isinstance(recorded_dependencies, dict):
        recorded_dependencies = _unavailable_python_dependencies(
            "MANIFEST_PREDATES_PYTHON_DEPENDENCY_BINDING"
        )
    if repo is None:
        current_frontend = _unavailable_frontend_identity("NO_REPOSITORY_REFERENCE")
        current_dependencies = _unavailable_python_dependencies(
            "NO_REPOSITORY_REFERENCE"
        )
        target_frontend = _unavailable_frontend_identity("NO_REPOSITORY_REFERENCE")
    else:
        repo = Path(repo)
        current_frontend = resolve_frontend_build_identity(repo)
        current_dependencies = resolve_python_dependency_fingerprint(repo)
        if isinstance(app_sha, str) and re.fullmatch(r"[0-9a-f]{40}", app_sha):
            target_frontend = resolve_frontend_build_identity(
                repo, code_sha=app_sha, expected_code_sha=app_sha,
            )
        else:
            target_frontend = _unavailable_frontend_identity("NO_TARGET_CODE_SHA")

    risks: list[str] = []

    def _identity_state(
        recorded: dict, current: dict,
    ) -> bool | str:
        recorded_ok = (
            recorded.get("status") in ("ok", "partial")
            and isinstance(recorded.get("identity"), str)
        )
        current_ok = (
            current.get("status") in ("ok", "partial")
            and isinstance(current.get("identity"), str)
        )
        if not recorded_ok or not current_ok:
            return "unknown"
        return hmac.compare_digest(recorded["identity"], current["identity"])

    frontend_matches = _identity_state(recorded_frontend, current_frontend)
    if frontend_matches is False:
        risks.append("FRONTEND_BUILD_CHANGED_SINCE_BACKUP")
    if recorded_frontend.get("status") == "unavailable":
        risks.append("FRONTEND_BUILD_IDENTITY_UNAVAILABLE")
    recorded_receipt_sha = recorded_frontend.get("receipt_code_sha")
    recorded_receipt_matches_backup_code: bool | str = "unknown"
    previous_sha = manifest.get("previous_sha")
    if (
        isinstance(recorded_receipt_sha, str)
        and re.fullmatch(r"[0-9a-f]{40}", recorded_receipt_sha)
        and isinstance(previous_sha, str)
        and re.fullmatch(r"[0-9a-f]{40}", previous_sha)
    ):
        recorded_receipt_matches_backup_code = recorded_receipt_sha == previous_sha
        if not recorded_receipt_matches_backup_code:
            risks.append("FRONTEND_BUILD_BOUND_TO_DIFFERENT_BACKUP_CODE_SHA")
    current_receipt_sha = current_frontend.get("receipt_code_sha")
    receipt_sha_matches: bool | str = "unknown"
    if (
        isinstance(current_receipt_sha, str)
        and re.fullmatch(r"[0-9a-f]{40}", current_receipt_sha)
        and isinstance(app_sha, str)
        and re.fullmatch(r"[0-9a-f]{40}", app_sha)
    ):
        receipt_sha_matches = current_receipt_sha == app_sha
        if not receipt_sha_matches:
            risks.append("FRONTEND_BUILD_BOUND_TO_DIFFERENT_CODE_SHA")
    restorable_by_git = target_frontend.get("status") in ("ok", "partial")
    frontend = {
        "recorded_status": recorded_frontend.get("status"),
        "recorded_identity": recorded_frontend.get("identity"),
        "recorded_receipt_code_sha": recorded_receipt_sha,
        "recorded_build_origin": recorded_frontend.get("build_origin"),
        "recorded_ui_build_version": recorded_frontend.get("ui_build_version"),
        "current_status": current_frontend.get("status"),
        "current_identity": current_frontend.get("identity"),
        "current_receipt_code_sha": current_frontend.get("receipt_code_sha"),
        "matches_recorded": frontend_matches,
        "target_code_sha": app_sha,
        "recorded_receipt_sha_matches_backup_code": (
            recorded_receipt_matches_backup_code
        ),
        "receipt_sha_matches_target_code": receipt_sha_matches,
        "restorable_by_git": restorable_by_git,
        "target_code_receipt_status": target_frontend.get("status"),
        "target_code_receipt_reason": target_frontend.get("reason"),
        "not_restorable_by_git_reason": (
            None if restorable_by_git
            else "frontend build receipts are gitignored build output; a Git "
                 "checkout cannot restore static/vue-catalog or static/vue-app"
        ),
    }

    recorded_installed = recorded_dependencies.get("installed")
    if not isinstance(recorded_installed, dict):
        recorded_installed = {}
    current_installed = current_dependencies.get("installed")
    if not isinstance(current_installed, dict):
        current_installed = {}
    changed_packages: dict[str, dict] = {}
    for name in sorted(set(recorded_installed) | set(current_installed)):
        before = recorded_installed.get(name)
        after = current_installed.get(name)
        if before != after:
            changed_packages[name] = {"backup": before, "current": after}
    if recorded_installed and current_installed:
        installed_matches: bool | str = not changed_packages
    else:
        installed_matches = "unknown"
    if installed_matches is False:
        risks.append("PYTHON_DEPENDENCY_VERSION_DRIFT")
    if recorded_dependencies.get("status") == "unavailable":
        risks.append("PYTHON_DEPENDENCIES_IDENTITY_UNAVAILABLE")
    recorded_requirements_digest = recorded_dependencies.get(
        "requirements_digest"
    )
    current_requirements_digest = current_dependencies.get("requirements_digest")
    if isinstance(recorded_requirements_digest, str) and isinstance(
        current_requirements_digest, str
    ):
        requirements_match: bool | str = hmac.compare_digest(
            recorded_requirements_digest, current_requirements_digest,
        )
        if requirements_match is False:
            risks.append("PYTHON_REQUIREMENTS_CHANGED_SINCE_BACKUP")
    else:
        requirements_match = "unknown"
    dependencies = {
        "recorded_status": recorded_dependencies.get("status"),
        "recorded_fingerprint": recorded_dependencies.get("fingerprint"),
        "recorded_requirements_digest": recorded_requirements_digest,
        "recorded_installed_count": recorded_dependencies.get("installed_count"),
        "current_status": current_dependencies.get("status"),
        "current_fingerprint": current_dependencies.get("fingerprint"),
        "current_requirements_digest": current_requirements_digest,
        "installed_matches": installed_matches,
        "requirements_match": requirements_match,
        "changed_packages": changed_packages,
    }
    return {
        "status": "checked",
        "target_code_sha": app_sha,
        "frontend_build": frontend,
        "python_dependencies": dependencies,
        "risks": sorted(set(risks)),
        "binding_note": (
            "recorded identities come from backup.json and are compared with "
            "the deployed worktree now; this tool does not mutate the frontend "
            "build, Python packages, requirements or Git branches"
        ),
    }


def _systemctl(*args: str) -> str:
    """Single, monkeypatchable entry point for every systemd interaction."""
    return command("systemctl", *args)


def _hash_config_file(path: object) -> dict:
    """Read-only hash of one unit/drop-in/environment file for later diffing."""
    entry: dict = {
        "path": str(path),
        "status": "missing",
        "sha256": None,
        "bytes": None,
        "symlink_target": None,
    }
    try:
        candidate = Path(str(path))
        if candidate.is_symlink():
            entry["status"] = "symlink"
            try:
                entry["symlink_target"] = os.readlink(candidate)
            except OSError:
                entry["symlink_target"] = None
        if not candidate.exists():
            if entry["status"] == "symlink":
                entry["status"] = "broken_symlink"
            return entry
        if candidate.is_dir():
            entry["status"] = "not_a_file"
            return entry
        payload = candidate.read_bytes()
        entry["sha256"] = hashlib.sha256(payload).hexdigest()
        entry["bytes"] = len(payload)
        if entry["status"] != "symlink":
            entry["status"] = "readable"
    except OSError as exc:
        entry["status"] = "unreadable"
        entry["error"] = str(exc)
    return entry


def _systemd_environment_file_paths(value: str) -> list[str]:
    """Extract file paths from ``systemctl show -p EnvironmentFiles`` output."""
    paths: list[str] = []
    for token in (value or "").split():
        stripped = token.strip().strip("\"'")
        if not stripped or stripped.startswith("(") or stripped.startswith("-"):
            continue
        if (
            stripped.startswith("/")
            or stripped.startswith(".")
            or Path(stripped).is_absolute()
        ):
            paths.append(stripped)
    return paths


def capture_systemd_configuration(
    units: tuple[str, ...] = (WEB_UNIT, WORKER_UNIT),
) -> dict:
    """Read-only snapshot of unit files, drop-ins and environment files.

    Raw ``Environment=`` values are never recorded (they may contain secrets);
    only their digest and the number of keys are captured.  The snapshot is
    used to detect configuration drift caused by an upgrade; nothing here
    writes a unit file, drop-in or environment file.
    """
    snapshot: dict = {"probe": "ok", "units": {}, "errors": []}
    for unit in units:
        entry: dict = {
            "unit": unit,
            "probe": "ok",
            "fragment_path": None,
            "fragment": None,
            "drop_in_paths": [],
            "drop_ins": [],
            "environment_files": [],
            "environment_file_hashes": [],
            "environment_digest": None,
            "environment_key_count": None,
        }
        try:
            fragment_path = command(
                "systemctl", "show", unit, "--value", "-p", "FragmentPath",
            ).strip()
            drop_in_value = command(
                "systemctl", "show", unit, "--value", "-p", "DropInPaths",
            )
            env_files_value = command(
                "systemctl", "show", unit, "--value", "-p", "EnvironmentFiles",
            )
            environment_value = command(
                "systemctl", "show", unit, "--value", "-p", "Environment",
            )
        except (UpgradeRefused, OSError) as exc:
            entry["probe"] = "unavailable"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            snapshot["errors"].append(f"{unit}: {entry['error']}")
            snapshot["probe"] = "partial"
            snapshot["units"][unit] = entry
            continue
        entry["fragment_path"] = fragment_path or None
        if fragment_path:
            entry["fragment"] = _hash_config_file(fragment_path)
            if entry["fragment"]["status"] not in ("readable", "symlink"):
                snapshot["probe"] = "partial"
                snapshot["errors"].append(
                    f"{unit}: fragment {entry['fragment']['status']}"
                )
        for drop_in in (drop_in_value or "").split():
            entry["drop_in_paths"].append(drop_in)
            drop_in_hash = _hash_config_file(drop_in)
            entry["drop_ins"].append(drop_in_hash)
            if drop_in_hash["status"] not in ("readable", "symlink"):
                snapshot["probe"] = "partial"
        for env_file in _systemd_environment_file_paths(env_files_value):
            entry["environment_files"].append(env_file)
            env_hash = _hash_config_file(env_file)
            entry["environment_file_hashes"].append(env_hash)
            if env_hash["status"] not in ("readable", "symlink"):
                snapshot["probe"] = "partial"
        environment_text = environment_value or ""
        entry["environment_digest"] = hashlib.sha256(
            environment_text.encode("utf-8", "surrogatepass")
        ).hexdigest()
        entry["environment_key_count"] = len({
            token.split("=", 1)[0]
            for token in environment_text.split()
            if "=" in token
        })
        snapshot["units"][unit] = entry
    return snapshot


def _systemd_config_fingerprint(entry: dict) -> object:
    """Comparable projection of one unit snapshot (no raw environment values)."""
    if not isinstance(entry, dict) or entry.get("probe") != "ok":
        return None

    def _file_state(config: object) -> object:
        if not isinstance(config, dict):
            return None
        return (
            config.get("status"),
            config.get("sha256"),
            config.get("symlink_target"),
        )

    return {
        "fragment_path": entry.get("fragment_path"),
        "fragment": _file_state(entry.get("fragment")),
        "drop_in_paths": list(entry.get("drop_in_paths") or ()),
        "drop_ins": [
            _file_state(item) for item in entry.get("drop_ins") or ()
        ],
        "environment_files": list(entry.get("environment_files") or ()),
        "environment_file_hashes": [
            _file_state(item)
            for item in entry.get("environment_file_hashes") or ()
        ],
        "environment_digest": entry.get("environment_digest"),
        "environment_key_count": entry.get("environment_key_count"),
    }


def compare_systemd_configuration(before: dict, after: dict) -> dict:
    """Compare two read-only snapshots; a difference is an explicit risk only."""
    before_units = before.get("units") if isinstance(before, dict) else {}
    after_units = after.get("units") if isinstance(after, dict) else {}
    if not isinstance(before_units, dict) or not isinstance(after_units, dict):
        return {
            "status": "unavailable",
            "risk": None,
            "changed_units": [],
            "detail": "SNAPSHOT_INVALID",
        }
    changed_units: list[str] = []
    for unit in sorted(set(before_units) | set(after_units)):
        before_state = _systemd_config_fingerprint(before_units.get(unit, {}))
        after_state = _systemd_config_fingerprint(after_units.get(unit, {}))
        if before_state != after_state:
            changed_units.append(unit)
    probes = {
        str(before.get("probe")), str(after.get("probe")),
    }
    if "unavailable" in probes or before.get("probe") == "partial" or (
        after.get("probe") == "partial"
    ):
        status = "partial" if changed_units else "unavailable"
    elif changed_units:
        status = "changed"
    else:
        status = "unchanged"
    return {
        "status": status,
        "risk": SYSTEMD_CONFIG_RISK_CODE if changed_units else None,
        "changed_units": changed_units,
        "probe_before": before.get("probe"),
        "probe_after": after.get("probe"),
        "errors": list(before.get("errors") or ())
        + list(after.get("errors") or ()),
        "note": (
            "read-only unit/environment file comparison; this tool never "
            "rewrites a systemd unit, drop-in or environment file"
        ),
    }


def require_idle_tasks(
    data_dir: Path, *, block_code: str = "ACTIVE_TASKS_BLOCK_UPGRADE",
) -> None:
    path = data_dir / "task_runtime" / "tasks.sqlite3"
    if not path.is_file():
        raise UpgradeRefused(f"TASK_DB_MISSING: cannot prove task idleness: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=3)) as db:
            db.execute("PRAGMA busy_timeout=3000")
            # Keep the bound parameters in sync with the declared terminal
            # states. Unknown and NULL statuses must fail closed.
            terminal_states = tuple(sorted(TERMINAL_STATES))
            placeholders = ",".join("?" for _ in terminal_states)
            rows = db.execute(
                "SELECT task_id, status FROM tasks "
                f"WHERE status IS NULL OR status NOT IN ({placeholders}) LIMIT 6",
                terminal_states,
            ).fetchall()
    except sqlite3.Error as exc:
        raise UpgradeRefused(f"TASK_STATUS_UNAVAILABLE: {exc}") from exc
    if rows:
        examples = ", ".join(f"{task_id}:{status}" for task_id, status in rows[:5])
        raise UpgradeRefused(f"{block_code}: {examples}")


def restore_tracked_code_modes(repo: Path) -> int:
    """Restore Git 100644/100755 file modes; do not chmod untracked data."""
    entries = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z"], cwd=repo,
    ).split(b"\0")
    fixed = 0
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0]
        if mode not in (b"100644", b"100755"):
            continue
        file = repo / os.fsdecode(raw_path)
        if file.is_symlink() or not file.is_file():
            raise UpgradeRefused(f"CODE_WORKTREE_FILE_MISSING: {file}")
        expected = 0o755 if mode == b"100755" else 0o644
        if stat.S_IMODE(file.stat().st_mode) != expected:
            file.chmod(expected)
            fixed += 1
        parent = file.parent
        while parent == repo or repo in parent.parents:
            current = stat.S_IMODE(parent.stat().st_mode)
            if current & 0o055 != 0o055:
                parent.chmod(current | 0o055)
            if parent == repo:
                break
            parent = parent.parent
    return fixed


def verify_service_code_access(repo: Path, unit: str) -> None:
    service_user = command("systemctl", "show", unit, "--value", "-p", "User")
    if not service_user:
        return  # Unspecified systemd User means root.
    for name in ("app.py", "task_worker.py", "train_worker.py",
                 "platform_core/service_nodes.py", "platform_core/training_precision.py"):
        command("runuser", "-u", service_user, "--", "test", "-r", str(repo / name))


def wait_web_health(timeout: float = 45.0) -> dict:
    url = "http://127.0.0.1:8010/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                result = json.load(response)
            if isinstance(result, dict) and result.get("ok") is True:
                return result
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise UpgradeRefused("WEB_HEALTH_TIMEOUT: Web did not return ok=true")


# ---------------------------------------------------------------------------
# Backup primitives
# ---------------------------------------------------------------------------

def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    # "rb+" keeps the descriptor writable on Windows where os.fsync rejects a
    # read-only handle; the file is always one this tool just created.
    with path.open("rb+") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return  # Windows cannot open directories this way; best effort only.
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    _fsync_directory(path.parent)


def _sqlite_sidecars(path: Path) -> tuple[Path, ...]:
    return (
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )


def _remove_sqlite_sidecars(path: Path) -> None:
    for sidecar in _sqlite_sidecars(path):
        try:
            if sidecar.is_file() or sidecar.is_symlink():
                sidecar.unlink()
        except OSError:
            pass


def _cleanup_sqlite_temporary(path: Path) -> None:
    for candidate in (path, *_sqlite_sidecars(path)):
        try:
            if candidate.is_file() or candidate.is_symlink():
                candidate.unlink()
        except OSError:
            pass


def _open_readonly_database(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30)


def _quick_check_database(path: Path) -> str:
    """Return ``ok`` or raise for a database file that must be readable."""
    try:
        connection = _open_readonly_database(path)
    except sqlite3.Error as exc:
        raise UpgradeRefused(
            f"BACKUP_SQLITE_QUICK_CHECK_FAILED: cannot open {path}: {exc}"
        ) from exc
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        row = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise UpgradeRefused(
            f"BACKUP_SQLITE_QUICK_CHECK_FAILED: {path}: {exc}"
        ) from exc
    finally:
        connection.close()
    if not row or row[0] != "ok":
        raise UpgradeRefused(
            f"BACKUP_SQLITE_QUICK_CHECK_FAILED: {path}: {row!r}"
        )
    return "ok"


# ---------------------------------------------------------------------------
# Runtime write-silence probes (read-only; M10-B)
# ---------------------------------------------------------------------------

def _read_optional_json_object(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _probe_relational_table(
    connection: sqlite3.Connection, table: str,
) -> list[str] | None:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
    ).fetchone()
    if row is None:
        return None
    quoted = table.replace('"', '""')
    return [str(item[1]) for item in connection.execute(f'PRAGMA table_info("{quoted}")')]


def probe_runtime_activity(data_dir: Path, *, repo: Path | None = None) -> dict:
    """Read-only M10-B probes: active tasks, resource holds, build marker, agents.

    Every probe is independent and best-effort: an unavailable probe is recorded
    as ``unavailable`` (with a reason) instead of being treated as idle.  A
    positive probe must block a normal backup; ``--force-idle`` only records the
    override and never turns this into a consistency claim.
    """
    data_dir = Path(data_dir).resolve()
    activity: dict = {
        "active_tasks": {"probe": "unavailable", "reason": "TASK_DB_MISSING"},
        "unreleased_holds": {"probe": "unavailable", "reason": "TASK_DB_MISSING"},
        "worker_build_marker": {"probe": "unavailable", "reason": "TASK_DB_MISSING"},
        "active_agents": {"probe": "unavailable", "reason": "TASK_DB_MISSING"},
        "blocking": [],
        "unknown": [],
    }
    task_database = data_dir / "task_runtime" / "tasks.sqlite3"
    connection: sqlite3.Connection | None = None
    if task_database.is_file() and not task_database.is_symlink():
        try:
            connection = _open_readonly_database(task_database)
            connection.execute("PRAGMA busy_timeout=3000")
        except sqlite3.Error as exc:
            connection = None
            for name in ("active_tasks", "unreleased_holds", "active_agents"):
                activity[name] = {"probe": "unavailable", "reason": f"OPEN_FAILED: {exc}"}
    try:
        if connection is not None:
            # 1. Non-terminal tasks.
            try:
                columns = _probe_relational_table(connection, "tasks")
                if columns is None:
                    activity["active_tasks"] = {
                        "probe": "unavailable", "reason": "TABLE_MISSING",
                    }
                elif {"task_id", "status"} <= set(columns):
                    terminal_states = tuple(sorted(TERMINAL_STATES))
                    placeholders = ",".join("?" for _ in terminal_states)
                    rows = connection.execute(
                        "SELECT task_id, status FROM tasks "
                        f"WHERE status IS NULL OR status NOT IN ({placeholders}) "
                        "ORDER BY task_id LIMIT 6",
                        terminal_states,
                    ).fetchall()
                    activity["active_tasks"] = {
                        "probe": "ok",
                        "count": len(rows),
                        "examples": [
                            f"{task_id}:{status}" for task_id, status in rows[:5]
                        ],
                    }
                else:
                    activity["active_tasks"] = {
                        "probe": "unavailable", "reason": "REQUIRED_COLUMNS_MISSING",
                    }
            except sqlite3.Error as exc:
                activity["active_tasks"] = {
                    "probe": "unavailable", "reason": f"READ_FAILED: {exc}",
                }
            # 2. Unreleased execution-resource holds.
            try:
                hold_columns = _probe_relational_table(
                    connection, "execution_resource_holds",
                )
                if hold_columns is None:
                    activity["unreleased_holds"] = {
                        "probe": "unavailable", "reason": "TABLE_MISSING",
                    }
                elif "state" not in hold_columns:
                    activity["unreleased_holds"] = {
                        "probe": "unavailable", "reason": "REQUIRED_COLUMNS_MISSING",
                    }
                else:
                    rows = connection.execute(
                        "SELECT task_id, state FROM execution_resource_holds "
                        "WHERE state IS NULL OR state <> 'RELEASED' "
                        "ORDER BY task_id LIMIT 6"
                    ).fetchall()
                    activity["unreleased_holds"] = {
                        "probe": "ok",
                        "count": len(rows),
                        "examples": [
                            f"{task_id}:{state}" for task_id, state in rows[:5]
                        ],
                    }
            except sqlite3.Error as exc:
                activity["unreleased_holds"] = {
                    "probe": "unavailable", "reason": f"READ_FAILED: {exc}",
                }
            # 3. Recently heartbeating / busy service agents.
            try:
                node_columns = _probe_relational_table(connection, "service_nodes")
                if node_columns is None:
                    activity["active_agents"] = {
                        "probe": "unavailable", "reason": "TABLE_MISSING",
                    }
                else:
                    wanted = {
                        "node_id", "enabled", "last_heartbeat_at", "active_tasks_json",
                    } - set(node_columns)
                    if wanted:
                        activity["active_agents"] = {
                            "probe": "unavailable",
                            "reason": "REQUIRED_COLUMNS_MISSING",
                        }
                    else:
                        now = datetime.now(timezone.utc)
                        active: list[str] = []
                        for node_id, enabled, heartbeat_at, tasks_json in connection.execute(
                            "SELECT node_id, enabled, last_heartbeat_at, "
                            "active_tasks_json FROM service_nodes"
                        ).fetchall():
                            if int(enabled or 0) != 1:
                                continue
                            busy = False
                            try:
                                reported = json.loads(tasks_json or "[]")
                                busy = bool(reported)
                            except ValueError:
                                busy = True  # Unparseable agent state is not idle.
                            if not busy:
                                if heartbeat_at:
                                    heartbeat = _parse_utc_timestamp(heartbeat_at)
                                    if heartbeat is None:
                                        busy = True  # Unparseable heartbeat is not idle.
                                    else:
                                        busy = (
                                            now - heartbeat
                                        ).total_seconds() <= HEARTBEAT_TTL_SECONDS
                            if busy:
                                active.append(str(node_id))
                        activity["active_agents"] = {
                            "probe": "ok",
                            "count": len(active),
                            "examples": active[:5],
                            "heartbeat_ttl_seconds": HEARTBEAT_TTL_SECONDS,
                        }
            except sqlite3.Error as exc:
                activity["active_agents"] = {
                    "probe": "unavailable", "reason": f"READ_FAILED: {exc}",
                }
    finally:
        if connection is not None:
            connection.close()

    # 4. Worker build marker (task_worker writes it on startup).
    marker_path = data_dir / WORKER_BUILD_MARKER_RELATIVE_PATH
    if marker_path.is_symlink() or not marker_path.is_file():
        activity["worker_build_marker"] = {
            "probe": "ok", "present": False, "build_id": None,
        }
    else:
        marker = _read_optional_json_object(marker_path)
        if marker is None:
            activity["worker_build_marker"] = {
                "probe": "unavailable", "present": True, "reason": "UNREADABLE",
            }
        else:
            marker_build_id = str(marker.get("build_id") or "").strip() or None
            current_build_id = resolve_build_identity(repo) if repo is not None else "unavailable"
            if marker_build_id is None:
                matches: object = "unknown"
            elif current_build_id in ("", "unavailable"):
                matches = "unknown"
            else:
                matches = marker_build_id == current_build_id
            activity["worker_build_marker"] = {
                "probe": "ok",
                "present": True,
                "build_id": marker_build_id,
                "current_build_id": current_build_id,
                "matches_current_build": matches,
            }

    # Derive the blocking/unknown sets.  Positive evidence blocks; unavailable
    # evidence is recorded and only blocks a strict --require-idle-only backup.
    blocking: list[str] = []
    unknown: list[str] = []
    if activity["active_tasks"].get("probe") == "ok":
        if activity["active_tasks"].get("count"):
            blocking.append("ACTIVE_TASKS_BLOCK_BACKUP")
    else:
        unknown.append("active_tasks")
    if activity["unreleased_holds"].get("probe") == "ok":
        if activity["unreleased_holds"].get("count"):
            blocking.append("UNRELEASED_RESOURCE_HOLDS_BLOCK_BACKUP")
    else:
        unknown.append("unreleased_holds")
    if activity["active_agents"].get("probe") == "ok":
        if activity["active_agents"].get("count"):
            blocking.append("ACTIVE_AGENTS_BLOCK_BACKUP")
    else:
        unknown.append("active_agents")
    marker = activity["worker_build_marker"]
    if marker.get("probe") != "ok":
        unknown.append("worker_build_marker")
    elif marker.get("present") and marker.get("matches_current_build") is False:
        blocking.append("WORKER_BUILD_MISMATCH_BLOCK_BACKUP")
    elif marker.get("present") and marker.get("matches_current_build") == "unknown":
        unknown.append("worker_build_marker")
    activity["blocking"] = blocking
    activity["unknown"] = unknown
    activity["write_silence"] = WRITE_SILENCE_UNVERIFIED
    activity["write_silence_reason"] = WRITE_SILENCE_REASON
    return activity


def enforce_backup_write_silence(
    activity: dict, *, force_idle: bool, require_idle_only: bool,
) -> dict:
    """Refuse a backup that observed runtime activity; record forced overrides."""
    reasons = list(activity.get("blocking") or ())
    if force_idle:
        return {
            "forced": bool(reasons),
            "forced_reasons": reasons,
            "status": WRITE_SILENCE_UNVERIFIED,
            "reason": WRITE_SILENCE_REASON,
        }
    if reasons:
        details = {
            name: activity[name]
            for name in ("active_tasks", "unreleased_holds", "active_agents",
                         "worker_build_marker")
            if activity.get(name, {}).get("count")
            or activity.get(name, {}).get("matches_current_build") is False
        }
        raise UpgradeRefused(
            f"{reasons[0]}: runtime activity/consistency probe is not idle: "
            f"{json.dumps(details, ensure_ascii=False, sort_keys=True)}. "
            "Finish/cancel the work, release the holds, wait for agents to go "
            "idle, or pass --force-idle only after accepting that the snapshot "
            "is not business-consistent (write_silence stays unverified)."
        )
    if require_idle_only and activity.get("unknown"):
        raise UpgradeRefused(
            "IDLE_PROBE_UNKNOWN_BLOCK_BACKUP: --require-idle-only was requested "
            "but the following read-only probes are unavailable: "
            f"{activity['unknown']}. This tool will not treat unknown as idle."
        )
    return {
        "forced": False,
        "forced_reasons": [],
        "status": WRITE_SILENCE_UNVERIFIED,
        "reason": WRITE_SILENCE_REASON,
    }


def require_post_stop_idle(
    data_dir: Path,
    *,
    repo: Path | None = None,
    block_code: str,
    force_idle: bool = False,
) -> dict:
    """Re-check runtime activity after the services were stopped (N6.1).

    The pre-stop gates already refuse active tasks; this second read-only pass
    covers the remaining evidence (unreleased execution-resource holds, recent
    agent heartbeats and the worker build marker) once the services are down.
    Positive evidence fails closed unless the operator passed the explicit
    ``--force-idle`` override, which is recorded and never claims consistency.
    """
    activity = probe_runtime_activity(Path(data_dir), repo=repo)
    try:
        gate = enforce_backup_write_silence(
            activity, force_idle=force_idle, require_idle_only=False,
        )
    except UpgradeRefused as exc:
        raise UpgradeRefused(
            f"{block_code}: the post-stop read-only activity recheck still "
            f"observed runtime activity; refusing to continue automatically: {exc}"
        ) from exc
    return {
        "block_code": block_code,
        "status": "forced" if gate.get("forced") else "verified",
        "forced": bool(gate.get("forced")),
        "forced_reasons": list(gate.get("forced_reasons") or ()),
        "unknown": list(activity.get("unknown") or ()),
        "write_silence": WRITE_SILENCE_UNVERIFIED,
        "write_silence_reason": WRITE_SILENCE_REASON,
        "activity": activity,
    }


# ---------------------------------------------------------------------------
# Schema probing and fail-closed compatibility (M10-A)
# ---------------------------------------------------------------------------

def probe_database_schema(path: Path) -> dict:
    """Bounded read-only probe: user_version, tables, key columns, meta versions."""
    try:
        connection = _open_readonly_database(Path(path))
    except (sqlite3.Error, OSError) as exc:
        return {"status": "unreadable", "error": str(exc)}
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = [
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        table_columns: dict[str, list[str]] = {}
        for table in tables:
            quoted = table.replace('"', '""')
            table_columns[table] = [
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{quoted}")')
            ]
        meta_versions: dict[str, dict[str, str]] = {}
        columns = table_columns.get("algorithm_store_meta")
        if columns and {"key", "value"} <= set(columns):
            for key, value in connection.execute(
                "SELECT key, value FROM algorithm_store_meta"
            ):
                meta_versions.setdefault("algorithm_store_meta", {})[
                    str(key)
                ] = str(value)
        return {
            "status": "ok",
            "user_version": user_version,
            "tables": tables,
            "table_columns": table_columns,
            "meta_versions": meta_versions,
        }
    except sqlite3.Error as exc:
        return {"status": "unreadable", "error": str(exc)}
    finally:
        connection.close()


def _classify_database(relative_path: str) -> str:
    normalized = str(relative_path).replace("\\", "/")
    if normalized == "task_runtime/tasks.sqlite3":
        return "tasks"
    if normalized == "storage/storage_sources.sqlite3":
        return "storage_sources"
    if normalized == "model_artifacts/artifacts.sqlite3":
        return "model_artifacts"
    if normalized == "external_algorithm_publish/publications.sqlite3":
        return "publications"
    parts = normalized.split("/")
    if len(parts) == 3 and parts[0] == "projects" and parts[1] and parts[2]:
        return PROJECT_DATABASE_KINDS.get(parts[2], "unknown")
    return "unknown"


def _extract_expected_schema_version(
    repo: Path | None, code_sha: str | None, requirement: dict,
) -> int | None:
    source_path = requirement.get("source_path")
    pattern = requirement.get("version_pattern")
    if not source_path or not pattern:
        return None
    text = _read_code_text(repo, code_sha, source_path)
    if text is None:
        return None
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


_BLOCKING_SCHEMA_CODES = frozenset({
    "UNKNOWN_DATABASE_KIND",
    "BACKUP_SCHEMA_UNREADABLE",
    "EXPECTED_SCHEMA_VERSION_UNAVAILABLE",
    "BACKUP_SCHEMA_VERSION_UNKNOWN",
})


def assess_backup_schema_compatibility(
    backup_dir: Path,
    manifest: dict,
    *,
    repo: Path | None,
    code_sha: str | None = None,
) -> dict:
    """Compare backup database schema against the code that would run it.

    Fail-closed: an unknown database kind, an unreadable database or a schema
    version the target code does not declare blocks the rollback instead of
    guessing a migration direction.  A version mismatch or a missing critical
    table/column is reported as incompatible.
    """
    backup_dir = Path(backup_dir).resolve()
    databases: list[dict] = []
    blocking: list[dict] = []
    for entry in manifest["entries"]:
        relative_path = entry["relative_path"]
        kind = _classify_database(relative_path)
        probe = probe_database_schema(backup_dir / relative_path)
        record: dict = {
            "relative_path": relative_path,
            "kind": kind,
            "status": "unverified",
            "expected_version": None,
            "actual_version": None,
            "version_probe": None,
            "reasons": [],
        }
        reasons: list[dict] = []
        requirement = SCHEMA_REQUIREMENTS.get(kind)
        if requirement is None:
            reasons.append({
                "code": "UNKNOWN_DATABASE_KIND",
                "message": (
                    "no schema expectation is declared for this database; "
                    "compatibility cannot be proven"
                ),
            })
        elif probe["status"] != "ok":
            reasons.append({
                "code": "BACKUP_SCHEMA_UNREADABLE",
                "message": probe.get("error") or "database could not be probed",
            })
        else:
            expected: int | None = None
            if requirement.get("source_path"):
                expected = _extract_expected_schema_version(repo, code_sha, requirement)
                record["expected_version"] = expected
                if expected is None:
                    reasons.append({
                        "code": "EXPECTED_SCHEMA_VERSION_UNAVAILABLE",
                        "message": (
                            f"cannot read the expected schema version declared by "
                            f"{requirement['source_path']} "
                            f"(code_sha={code_sha or 'worktree'})"
                        ),
                    })
            version_probe = requirement.get("version_probe", "none")
            record["version_probe"] = version_probe
            if not reasons and version_probe == "user_version" and expected is not None:
                actual = probe.get("user_version")
                record["actual_version"] = actual
                if not isinstance(actual, int) or isinstance(actual, bool):
                    reasons.append({
                        "code": "BACKUP_SCHEMA_VERSION_UNKNOWN",
                        "message": "PRAGMA user_version could not be detected",
                    })
                elif actual != expected:
                    reasons.append({
                        "code": "SCHEMA_VERSION_MISMATCH",
                        "expected": expected,
                        "actual": actual,
                        "message": (
                            "backup user_version differs from the target code "
                            "expectation; migration direction is not guessed"
                        ),
                    })
            elif not reasons and version_probe == "meta":
                meta_table = str(requirement.get("meta_table") or "")
                meta_key = str(requirement.get("meta_key") or "")
                actual_text = (
                    probe.get("meta_versions", {}).get(meta_table, {}).get(meta_key)
                )
                actual = (
                    int(actual_text)
                    if isinstance(actual_text, str) and actual_text.isdigit()
                    else None
                )
                record["actual_version"] = actual
                if expected is None:
                    pass  # Already reported as unavailable above.
                elif actual is None:
                    reasons.append({
                        "code": "BACKUP_SCHEMA_VERSION_UNKNOWN",
                        "message": (
                            f"{meta_table}.{meta_key} schema version marker is "
                            "absent or unreadable"
                        ),
                    })
                elif actual != expected:
                    reasons.append({
                        "code": "SCHEMA_VERSION_MISMATCH",
                        "expected": expected,
                        "actual": actual,
                        "message": (
                            "backup metadata schema version differs from the "
                            "target code expectation; migration direction is not "
                            "guessed"
                        ),
                    })
            if not reasons:
                available_tables = set(probe.get("tables") or ())
                table_columns = probe.get("table_columns") or {}
                for table, required_columns in requirement["tables"].items():
                    if table not in available_tables:
                        reasons.append({
                            "code": "MISSING_TABLE",
                            "table": table,
                            "message": (
                                "critical table expected by the target code is "
                                "absent from the backup database"
                            ),
                        })
                        continue
                    present = set(table_columns.get(table) or ())
                    missing = [
                        column for column in required_columns if column not in present
                    ]
                    if missing:
                        reasons.append({
                            "code": "MISSING_COLUMNS",
                            "table": table,
                            "columns": missing,
                            "message": (
                                "critical columns expected by the target code are "
                                "absent from the backup database"
                            ),
                        })
            if not reasons and requirement.get("source_path") and version_probe == "none":
                # The code declares a schema version but the database does not
                # store one; the structural whitelist is the best available proof.
                record["version_not_recorded_in_database"] = True
        record["reasons"] = reasons
        if reasons:
            codes = {item["code"] for item in reasons}
            record["status"] = (
                "blocked" if codes & _BLOCKING_SCHEMA_CODES else "incompatible"
            )
        else:
            record["status"] = "compatible"
        databases.append(record)
        if record["status"] != "compatible":
            blocking.append({
                "relative_path": relative_path,
                "kind": kind,
                "status": record["status"],
                "reasons": reasons,
            })
    if any(item["status"] == "blocked" for item in blocking):
        status = "blocked"
    elif blocking:
        status = "incompatible"
    else:
        status = "compatible"
    return {
        "status": status,
        "code_sha": code_sha,
        "databases": databases,
        "blocking": blocking,
    }


def _raise_for_schema_assessment(assessment: dict) -> None:
    """Raise with distinct, explicit codes for incompatible vs unprovable schema."""
    if assessment.get("status") == "compatible":
        return
    payload = json.dumps(assessment.get("blocking"), ensure_ascii=False, sort_keys=True)
    if assessment.get("status") == "blocked":
        raise UpgradeRefused(
            "APPLICATION_ROLLBACK_BLOCKED: schema compatibility cannot be proven "
            f"for the verified backup: {payload}. Refusing to start the target "
            "code against a database whose schema is unknown to this tool."
        )
    raise UpgradeRefused(
        "BACKUP_SCHEMA_INCOMPATIBLE: the backup database schema does not match "
        f"the code that would run: {payload}. Refusing to start the old "
        "database; migration direction is not guessed."
    )


def _copy_database(source: Path, destination: Path, *, readonly: bool) -> None:
    if readonly:
        source_connection = _open_readonly_database(source)
    else:
        # Fallback for a WAL database whose read-only open cannot create the
        # shared-memory file; the backup API still takes a consistent read
        # snapshot and does not write business rows.
        source_connection = sqlite3.connect(source, timeout=30)
    try:
        source_connection.execute("PRAGMA busy_timeout=30000")
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
            # A WAL source makes the copy WAL-mode; switch it to a standalone
            # rollback-journal database so the snapshot has no sidecar files.
            destination_connection.execute("PRAGMA journal_mode=DELETE")
            row = destination_connection.execute("PRAGMA quick_check").fetchone()
            if not row or row[0] != "ok":
                raise UpgradeRefused(
                    f"BACKUP_SQLITE_QUICK_CHECK_FAILED: {source}: {row!r}"
                )
            destination_connection.commit()
        finally:
            destination_connection.close()
    finally:
        source_connection.close()


def _snapshot_sqlite(source: Path, destination: Path) -> dict:
    """Consistency snapshot of one SQLite database via the online backup API."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".snapshot-tmp")
    _cleanup_sqlite_temporary(temporary)
    try:
        try:
            _copy_database(source, temporary, readonly=True)
        except sqlite3.OperationalError:
            _cleanup_sqlite_temporary(temporary)
            try:
                _copy_database(source, temporary, readonly=False)
            except sqlite3.Error as exc:
                raise UpgradeRefused(
                    f"BACKUP_SQLITE_SNAPSHOT_FAILED: {source}: {exc}"
                ) from exc
        except sqlite3.Error as exc:
            raise UpgradeRefused(
                f"BACKUP_SQLITE_SNAPSHOT_FAILED: {source}: {exc}"
            ) from exc
        _fsync_file(temporary)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        _cleanup_sqlite_temporary(temporary)
        raise
    _cleanup_sqlite_temporary(temporary)
    return {
        "size_bytes": destination.stat().st_size,
        "sha256": _sha256_file(destination),
        "sqlite_quick_check": "ok",
    }


def _discover_control_databases(data_dir: Path) -> list[Path]:
    """Top-level control-plane SQLite catalogs; never descends into artifacts."""
    data_dir = Path(data_dir).resolve()
    found: list[Path] = []
    for relative in CONTROL_DATABASE_RELATIVE_PATHS:
        candidate = data_dir / relative
        if candidate.is_symlink() or not candidate.is_file():
            continue
        found.append(candidate)
    projects = data_dir / "projects"
    if projects.is_dir() and not projects.is_symlink():
        for project in sorted(projects.iterdir(), key=lambda item: item.name):
            if project.is_symlink() or not project.is_dir():
                continue
            for database in sorted(
                project.glob(PROJECT_DATABASE_GLOB), key=lambda item: item.name,
            ):
                if database.is_symlink() or not database.is_file():
                    continue
                found.append(database)
    resolved: list[Path] = []
    for candidate in found:
        path = candidate.resolve()
        if not path.is_relative_to(data_dir):
            raise UpgradeRefused(f"UNSAFE_CONTROL_DATABASE_PATH: {candidate}")
        resolved.append(path)
    return sorted(dict.fromkeys(resolved), key=lambda item: item.as_posix())


def _database_footprint(path: Path) -> int:
    total = path.stat().st_size
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        try:
            if sidecar.is_file():
                total += sidecar.stat().st_size
        except OSError:
            pass
    return total


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def _format_timestamp(now: datetime | float | str | None) -> str:
    if now is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(now, datetime):
        moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(timezone.utc)
    elif isinstance(now, (int, float)):
        moment = datetime.fromtimestamp(now, tz=timezone.utc)
    elif isinstance(now, str):
        return now
    else:  # pragma: no cover - defensive
        raise UpgradeRefused(f"INVALID_BACKUP_TIMESTAMP: {now!r}")
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _manifest_digest(manifest: dict) -> str:
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def _validate_relative_database_path(relative_path: object) -> str:
    if not isinstance(relative_path, str) or not relative_path:
        raise UpgradeRefused(f"BACKUP_MANIFEST_CORRUPT: invalid relative_path {relative_path!r}")
    path = Path(relative_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or "\\" in relative_path
        or path.as_posix() != relative_path
    ):
        raise UpgradeRefused(
            f"BACKUP_MANIFEST_CORRUPT: unsafe relative_path {relative_path!r}"
        )
    return relative_path


def load_backup_manifest(backup_dir: Path) -> dict:
    """Load and structurally validate ``backup.json`` (no file verification)."""
    manifest_path = Path(backup_dir) / BACKUP_MANIFEST_NAME
    if not manifest_path.is_file():
        raise UpgradeRefused(f"BACKUP_MANIFEST_MISSING: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpgradeRefused(f"BACKUP_MANIFEST_CORRUPT: {exc}") from exc
    if not isinstance(manifest, dict):
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: manifest root must be an object")
    required = (
        "schema_version", "created_at", "previous_sha", "target_sha", "data_dir",
        "platform", "entries", "total_bytes", "exclusions", "manifest_sha256",
    )
    missing = [key for key in required if key not in manifest]
    if missing:
        raise UpgradeRefused(f"BACKUP_MANIFEST_CORRUPT: missing fields {missing}")
    if manifest["schema_version"] != BACKUP_SCHEMA_VERSION:
        raise UpgradeRefused(
            "BACKUP_SCHEMA_UNSUPPORTED: "
            f"schema_version={manifest['schema_version']!r}"
        )
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"]:
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: created_at must be a string")
    if not isinstance(manifest["previous_sha"], str) or re.fullmatch(
        r"[0-9a-f]{40}", manifest["previous_sha"]
    ) is None:
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: invalid previous_sha")
    target_sha = manifest["target_sha"]
    if target_sha is not None and (
        not isinstance(target_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", target_sha) is None
    ):
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: invalid target_sha")
    if not isinstance(manifest["data_dir"], str) or not manifest["data_dir"]:
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: invalid data_dir")
    if not isinstance(manifest["platform"], str) or not manifest["platform"]:
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: invalid platform")
    entries = manifest["entries"]
    if not isinstance(entries, list) or not entries:
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: entries must be a non-empty list")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: entry must be an object")
        for key in ("relative_path", "size_bytes", "sha256", "sqlite_quick_check"):
            if key not in entry:
                raise UpgradeRefused(f"BACKUP_MANIFEST_CORRUPT: entry missing {key}")
        relative_path = _validate_relative_database_path(entry["relative_path"])
        if relative_path in seen:
            raise UpgradeRefused(
                f"BACKUP_MANIFEST_CORRUPT: duplicate entry {relative_path}"
            )
        seen.add(relative_path)
        size = entry["size_bytes"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise UpgradeRefused(
                f"BACKUP_MANIFEST_CORRUPT: invalid size for {relative_path}"
            )
        if not isinstance(entry["sha256"], str) or re.fullmatch(
            r"[0-9a-f]{64}", entry["sha256"]
        ) is None:
            raise UpgradeRefused(
                f"BACKUP_MANIFEST_CORRUPT: invalid sha256 for {relative_path}"
            )
        if entry["sqlite_quick_check"] != "ok":
            raise UpgradeRefused(
                f"BACKUP_MANIFEST_CORRUPT: recorded quick_check is not ok for {relative_path}"
            )
    total_bytes = manifest["total_bytes"]
    if not isinstance(total_bytes, int) or isinstance(total_bytes, bool) or total_bytes < 0:
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: invalid total_bytes")
    if not isinstance(manifest["exclusions"], list):
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: exclusions must be a list")
    for key in ("application_version", "build_id", "write_silence"):
        if key in manifest and not isinstance(manifest[key], str):
            raise UpgradeRefused(f"BACKUP_MANIFEST_CORRUPT: {key} must be a string")
    for key in (
        "application", "backup_scope", "write_silence_detail", "consistency",
        "frontend_build", "python_dependencies",
    ):
        if key in manifest and not isinstance(manifest[key], dict):
            raise UpgradeRefused(f"BACKUP_MANIFEST_CORRUPT: {key} must be an object")
    for entry in entries:
        schema = entry.get("schema")
        if schema is not None and not isinstance(schema, dict):
            raise UpgradeRefused(
                "BACKUP_MANIFEST_CORRUPT: entry schema must be an object"
            )
    if not isinstance(manifest["manifest_sha256"], str) or re.fullmatch(
        r"[0-9a-f]{64}", manifest["manifest_sha256"]
    ) is None:
        raise UpgradeRefused("BACKUP_MANIFEST_CORRUPT: invalid manifest_sha256")
    return manifest


def verify_data_backup(backup_dir: Path) -> dict:
    """Recompute the manifest digest and every recorded file hash/quick_check."""
    backup_dir = Path(backup_dir).resolve()
    manifest = load_backup_manifest(backup_dir)
    expected_digest = _manifest_digest(manifest)
    if not hmac.compare_digest(manifest["manifest_sha256"], expected_digest):
        raise UpgradeRefused(
            "BACKUP_MANIFEST_DIGEST_MISMATCH: backup.json was modified after it "
            f"was written ({manifest['manifest_sha256']} != {expected_digest})"
        )
    verified_entries: list[dict] = []
    total_bytes = 0
    for entry in manifest["entries"]:
        relative_path = entry["relative_path"]
        path = (backup_dir / relative_path).resolve()
        if not path.is_relative_to(backup_dir):
            raise UpgradeRefused(
                f"BACKUP_MANIFEST_CORRUPT: entry escapes backup dir: {relative_path}"
            )
        if not path.is_file():
            raise UpgradeRefused(f"BACKUP_FILE_MISSING: {path}")
        size = path.stat().st_size
        if size != entry["size_bytes"]:
            raise UpgradeRefused(
                f"BACKUP_FILE_SIZE_MISMATCH: {relative_path} expected "
                f"{entry['size_bytes']} bytes, found {size}"
            )
        digest = _sha256_file(path)
        if not hmac.compare_digest(digest, entry["sha256"]):
            raise UpgradeRefused(
                f"BACKUP_FILE_SHA256_MISMATCH: {relative_path} expected "
                f"{entry['sha256']}, found {digest}"
            )
        quick_check = _quick_check_database(path)
        if quick_check != "ok":
            raise UpgradeRefused(
                f"BACKUP_SQLITE_QUICK_CHECK_FAILED: {relative_path}"
            )
        total_bytes += size
        verified_entries.append(dict(entry))
    if total_bytes != manifest["total_bytes"]:
        raise UpgradeRefused(
            "BACKUP_MANIFEST_CORRUPT: total_bytes does not match entry sizes "
            f"({manifest['total_bytes']} != {total_bytes})"
        )
    return {
        "ok": True,
        "backup_dir": str(backup_dir),
        "manifest_sha256": manifest["manifest_sha256"],
        "total_bytes": total_bytes,
        "entries_verified": len(verified_entries),
        "entries": verified_entries,
        "manifest": manifest,
    }


def _create_backup(
    data_dir: Path,
    backup_dir: Path,
    *,
    previous_sha: str,
    target_sha: str | None,
    max_backup_bytes: int = DEFAULT_MAX_BACKUP_BYTES,
    now: datetime | float | str | None = None,
    purpose: str | None = None,
    require_idle: bool = True,
    repo: Path | None = None,
    force_idle: bool = False,
    require_idle_only: bool = False,
) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", str(previous_sha or "")) is None:
        raise UpgradeRefused(
            "PREVIOUS_SHA_REQUIRED: a reviewed 40-character current commit SHA is required"
        )
    if target_sha is not None and re.fullmatch(r"[0-9a-f]{40}", str(target_sha)) is None:
        raise UpgradeRefused(
            "TARGET_SHA_REQUIRED: a reviewed 40-character target commit SHA is required"
        )
    if not isinstance(max_backup_bytes, int) or max_backup_bytes <= 0:
        raise UpgradeRefused("BACKUP_SIZE_LIMIT_INVALID: max_backup_bytes must be positive")

    data_dir = Path(data_dir).resolve()
    repo_path = Path(repo).resolve() if repo is not None else None
    backup_dir = Path(backup_dir)
    resolved_backup_dir = backup_dir.resolve()
    if resolved_backup_dir == data_dir or data_dir in resolved_backup_dir.parents:
        raise UpgradeRefused(
            "BACKUP_DIR_INSIDE_DATA_DIR: the backup directory must not live "
            f"inside the data directory ({backup_dir} is inside {data_dir})"
        )
    if backup_dir.exists() or backup_dir.is_symlink():
        if not backup_dir.is_dir() or backup_dir.is_symlink():
            raise UpgradeRefused(f"BACKUP_DIR_NOT_A_DIRECTORY: {backup_dir}")
        if any(backup_dir.iterdir()):
            raise UpgradeRefused(f"BACKUP_DIR_NOT_EMPTY: {backup_dir}")
        raise UpgradeRefused(
            f"BACKUP_DIR_EXISTS: refusing to reuse an existing directory {backup_dir}"
        )

    databases = _discover_control_databases(data_dir)
    if not databases:
        raise UpgradeRefused(
            "NO_CONTROL_DATABASE_FOUND: no control-plane SQLite database was "
            f"found under {data_dir}"
        )
    if require_idle and not force_idle:
        require_idle_tasks(data_dir)
    # M10-B: read-only write-silence probes.  Positive evidence refuses a normal
    # backup; --force-idle records the override without claiming consistency.
    activity = probe_runtime_activity(data_dir, repo=repo_path)
    forced_info = enforce_backup_write_silence(
        activity, force_idle=force_idle, require_idle_only=require_idle_only,
    )
    footprint = sum(_database_footprint(database) for database in databases)
    if footprint > max_backup_bytes:
        raise UpgradeRefused(
            "BACKUP_TOO_LARGE: control-plane databases need "
            f"{footprint} bytes but the limit is {max_backup_bytes} bytes"
        )
    required_bytes = footprint * BACKUP_SPACE_MULTIPLIER + BACKUP_SPACE_RESERVE_BYTES
    free_bytes = shutil.disk_usage(_existing_ancestor(resolved_backup_dir)).free
    if free_bytes < required_bytes:
        raise UpgradeRefused(
            "INSUFFICIENT_BACKUP_SPACE: the backup volume has "
            f"{free_bytes} free bytes but {required_bytes} are required"
        )

    backup_dir.mkdir(parents=True, exist_ok=False)
    try:
        entries: list[dict] = []
        schema_versions: dict[str, object] = {}
        for database in databases:
            relative_path = database.relative_to(data_dir).as_posix()
            snapshot = _snapshot_sqlite(database, backup_dir / relative_path)
            schema = probe_database_schema(backup_dir / relative_path)
            if schema.get("status") == "ok":
                schema_versions[relative_path] = schema["user_version"]
                entries.append({
                    "relative_path": relative_path,
                    **snapshot,
                    "schema": {
                        "user_version": schema["user_version"],
                        "tables": schema["tables"],
                        "kind": _classify_database(relative_path),
                    },
                })
            else:
                schema_versions[relative_path] = "unknown"
                entries.append({
                    "relative_path": relative_path,
                    **snapshot,
                    "schema": {
                        "user_version": "unknown",
                        "tables": [],
                        "kind": _classify_database(relative_path),
                        "probe_error": schema.get("error"),
                    },
                })
        entries.sort(key=lambda entry: entry["relative_path"])
        total_bytes = sum(entry["size_bytes"] for entry in entries)
        application_version = read_application_version(repo_path)
        build_id = resolve_build_identity(repo_path)
        # N6.1: bind the snapshot to the deployed frontend build identity and
        # to the Python dependency fingerprint (explicitly unavailable when it
        # cannot be read; never guessed, never installed/updated here).
        frontend_build = resolve_frontend_build_identity(
            repo_path, expected_code_sha=previous_sha,
        )
        python_dependencies = resolve_python_dependency_fingerprint(repo_path)
        write_silence_detail = {
            **activity,
            "forced": forced_info["forced"],
            "forced_reasons": list(forced_info["forced_reasons"]),
            "status": WRITE_SILENCE_UNVERIFIED,
            "reason": WRITE_SILENCE_REASON,
        }
        manifest: dict = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "created_at": _format_timestamp(now),
            "previous_sha": previous_sha,
            "target_sha": target_sha,
            "data_dir": str(data_dir),
            "platform": sys.platform,
            "entries": entries,
            "total_bytes": total_bytes,
            "exclusions": [dict(item) for item in BACKUP_EXCLUSIONS],
            # Application identity the backup is bound to (M10-A).
            "application_version": application_version,
            "build_id": build_id,
            "frontend_build": frontend_build,
            "python_dependencies": python_dependencies,
            "application": {
                "version": application_version,
                "build_id": build_id,
                "previous_sha": previous_sha,
                "target_sha": target_sha,
                "data_dir": str(data_dir),
                "repo": str(repo_path) if repo_path is not None else None,
            },
            "schema_versions": schema_versions,
            "backup_scope": {
                "description": BACKUP_SCOPE_DESCRIPTION,
                "included_patterns": [
                    "task_runtime/tasks.sqlite3",
                    "storage/storage_sources.sqlite3",
                    "model_artifacts/artifacts.sqlite3",
                    "external_algorithm_publish/publications.sqlite3",
                    "projects/<project_id>/*.sqlite3 (top-level SQLite files)",
                ],
                "database_entries": [entry["relative_path"] for entry in entries],
            },
            # M10-B: explicit consistency boundary, never a disaster-recovery claim.
            "write_silence": WRITE_SILENCE_UNVERIFIED,
            "write_silence_detail": write_silence_detail,
            "consistency": dict(CONSISTENCY_STATEMENT),
        }
        if purpose is not None:
            manifest["purpose"] = purpose
        manifest["manifest_sha256"] = _manifest_digest(manifest)
        _atomic_write_bytes(
            backup_dir / BACKUP_MANIFEST_NAME,
            _canonical_json(manifest) + b"\n",
        )
    except BaseException:
        # The directory was created by this call, so a failed attempt must not
        # leave a half-written backup that a later run would treat as existing.
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise

    result = dict(manifest)
    result["backup_dir"] = str(resolved_backup_dir)
    result["verified"] = True
    return result


def create_data_backup(
    data_dir: Path,
    backup_dir: Path,
    *,
    previous_sha: str,
    target_sha: str | None = None,
    max_backup_bytes: int = DEFAULT_MAX_BACKUP_BYTES,
    now: datetime | float | str | None = None,
    repo: Path | None = None,
    force_idle: bool = False,
    require_idle_only: bool = False,
) -> dict:
    """Create and self-verify a per-database snapshot of control-plane SQLite DBs.

    The snapshot is NOT a disaster-recovery or cross-database business-consistent
    backup: ``backup.json`` records ``write_silence="unverified"`` and the
    explicit exclusions, and holds/workers/agents are probed read-only.
    """
    result = _create_backup(
        data_dir, backup_dir,
        previous_sha=previous_sha,
        target_sha=target_sha,
        max_backup_bytes=max_backup_bytes,
        now=now,
        repo=repo,
        force_idle=force_idle,
        require_idle_only=require_idle_only,
    )
    verification = verify_data_backup(Path(result["backup_dir"]))
    if verification["manifest_sha256"] != result["manifest_sha256"]:
        raise UpgradeRefused("BACKUP_VERIFICATION_MISMATCH: manifest changed after creation")
    result["entries_verified"] = verification["entries_verified"]
    return result


# ---------------------------------------------------------------------------
# Rollback primitives
# ---------------------------------------------------------------------------

def _require_apply_privileges() -> None:
    """Monkeypatchable POSIX-root gate for a real data restore."""
    if os.name != "posix":
        raise UpgradeRefused(
            "ROLLBACK_REQUIRES_POSIX: restoring control-plane databases is "
            "supported only on the Linux systemd host"
        )
    if os.geteuid() != 0:
        raise UpgradeRefused(
            "ROOT_REQUIRED: run --rollback --apply from the authorized host"
        )


def _require_upgrade_privileges(apply: bool) -> None:
    """Monkeypatchable host/root gate for the code upgrade itself."""
    if os.name != "posix":
        raise UpgradeRefused("Linux systemd host required")
    if apply and os.geteuid() != 0:
        raise UpgradeRefused("ROOT_REQUIRED: run the upgrade from the authorized host")


def _unique_directory(parent: Path, name: str) -> Path:
    candidate = parent / name
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = parent / f"{name}-{counter}"
        counter += 1
    return candidate


def _create_pre_rollback_safety_backup(
    backup_dir: Path, data_dir: Path, manifest: dict,
    *, repo: Path | None = None,
) -> dict:
    """Snapshot the current control-plane DBs before overwriting them."""
    current_databases = _discover_control_databases(data_dir)
    if not current_databases:
        return {
            "safety_backup_dir": None,
            "safety_backup_manifest_sha256": None,
            "safety_backup_skipped": "NO_CURRENT_CONTROL_DATABASE",
        }
    current_sha = manifest.get("target_sha") or manifest["previous_sha"]
    destination = _unique_directory(
        Path(backup_dir) / PRE_ROLLBACK_DIRECTORY,
        _format_timestamp(None).replace("-", "").replace(":", ""),
    )
    # This is the last-resort snapshot taken right before the overwrite: never
    # let a runtime-activity probe block it, but record any forced override.
    result = _create_backup(
        data_dir, destination,
        previous_sha=current_sha,
        target_sha=manifest["previous_sha"],
        now=None,
        purpose="pre-rollback",
        require_idle=False,
        repo=repo,
        force_idle=True,
    )
    verification = verify_data_backup(destination)
    return {
        "safety_backup_dir": str(destination.resolve()),
        "safety_backup_manifest_sha256": verification["manifest_sha256"],
        "safety_backup_skipped": None,
    }


def _replace_database_file(source: Path, target: Path) -> None:
    """Atomically replace one database file and drop stale WAL/journal sidecars."""
    target.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = (
        stat.S_IMODE(target.stat().st_mode) if target.is_file() else None
    )
    # A stale WAL/journal would replay pre-rollback pages over the restored
    # database; remove sidecars before the atomic replace.
    _remove_sqlite_sidecars(target)
    temporary = target.with_name(target.name + ".restore-tmp")
    _cleanup_sqlite_temporary(temporary)
    try:
        with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if previous_mode is not None:
            os.chmod(temporary, previous_mode)
        os.replace(temporary, target)
    except BaseException:
        _cleanup_sqlite_temporary(temporary)
        raise
    _fsync_directory(target.parent)


def _restore_backup_files_with_diagnostics(
    backup_dir: Path, data_dir: Path, manifest: dict,
) -> dict:
    """Restore every recorded database, collecting a structured per-file report.

    A file that already matches the verified manifest is re-verified and skipped
    (idempotent manual retry).  A per-file failure stops further replacements and
    is recorded instead of being masked; the caller keeps services stopped.
    """
    backup_dir = Path(backup_dir).resolve()
    data_dir = Path(data_dir).resolve()
    report: dict = {
        "entries_total": len(manifest["entries"]),
        "restored": [],
        "already_restored": [],
        "failed": [],
        "not_attempted": [],
    }
    failure_encountered = False
    for entry in manifest["entries"]:
        relative_path = entry["relative_path"]
        if failure_encountered:
            report["not_attempted"].append(relative_path)
            continue
        try:
            source = (backup_dir / relative_path).resolve()
            if not source.is_relative_to(backup_dir) or not source.is_file():
                raise UpgradeRefused(f"BACKUP_FILE_MISSING: {source}")
            target = (data_dir / relative_path).resolve()
            if not target.is_relative_to(data_dir):
                raise UpgradeRefused(
                    "BACKUP_MANIFEST_CORRUPT: entry escapes data dir: "
                    f"{relative_path}"
                )
            if (
                target.is_file()
                and target.stat().st_size == entry["size_bytes"]
                and hmac.compare_digest(_sha256_file(target), entry["sha256"])
            ):
                report["already_restored"].append(relative_path)
                continue
            _replace_database_file(source, target)
            report["restored"].append(relative_path)
        except Exception as exc:  # noqa: BLE001 - recorded, never masked
            failure_encountered = True
            report["failed"].append({
                "relative_path": relative_path,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return report


def _verify_restored_files(data_dir: Path, manifest: dict) -> dict:
    """Strict post-replace check: exact SHA256 and readable SQLite content."""
    data_dir = Path(data_dir).resolve()
    for entry in manifest["entries"]:
        relative_path = entry["relative_path"]
        path = data_dir / relative_path
        if not path.is_file():
            raise UpgradeRefused(f"RESTORED_DATABASE_MISSING: {path}")
        size = path.stat().st_size
        if size != entry["size_bytes"]:
            raise UpgradeRefused(
                f"RESTORED_DATABASE_SIZE_MISMATCH: {relative_path} expected "
                f"{entry['size_bytes']} bytes, found {size}"
            )
        digest = _sha256_file(path)
        if not hmac.compare_digest(digest, entry["sha256"]):
            raise UpgradeRefused(
                f"RESTORED_DATABASE_SHA256_MISMATCH: {relative_path}"
            )
        _quick_check_database(path)
    return {"restored_sha256_verified": True, "restored_quick_check": "ok"}


def _post_start_database_check(data_dir: Path, manifest: dict) -> dict:
    """After services start: readable DBs plus an informational hash comparison."""
    data_dir = Path(data_dir).resolve()
    mismatches: dict[str, dict[str, str]] = {}
    for entry in manifest["entries"]:
        relative_path = entry["relative_path"]
        path = data_dir / relative_path
        _quick_check_database(path)
        digest = _sha256_file(path)
        if not hmac.compare_digest(digest, entry["sha256"]):
            mismatches[relative_path] = {
                "expected": entry["sha256"],
                "found": digest,
            }
    return {
        "post_start_quick_check": "ok",
        "post_start_sha256_unchanged": not mismatches,
        "post_start_sha256_mismatches": mismatches,
    }


# ---------------------------------------------------------------------------
# Coordinated application-version rollback (M10-A)
# ---------------------------------------------------------------------------

def _git_head(repo: Path) -> str | None:
    code, output, _ = _git_output(Path(repo), "rev-parse", "HEAD")
    if code == 0 and re.fullmatch(r"[0-9a-f]{40}", output):
        return output
    return None


def _git_commit_exists(repo: Path, sha: str) -> bool:
    code, _, _ = _git_output(Path(repo), "cat-file", "-e", f"{sha}^{{commit}}")
    return code == 0


def _git_is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    code, _, _ = _git_output(
        Path(repo), "merge-base", "--is-ancestor", ancestor, descendant,
    )
    return code == 0


def validate_application_rollback_context(
    manifest: dict, repo: Path, app_sha: str,
) -> dict:
    """Validate the requested application rollback target before touching anything.

    The target must be the backup's ``previous_sha`` or one of its ancestors
    (``git merge-base --is-ancestor``), the worktree must be clean on the
    release branch, and the commit must exist locally.  Only read-only git
    probes run here; no checkout, reset, clean or stash happens.
    """
    repo = Path(repo).resolve()
    if not (repo / ".git").exists():
        raise UpgradeRefused(
            "APPLICATION_ROLLBACK_BLOCKED: --repo is not a Git worktree; a "
            f"coordinated application rollback is impossible ({repo})"
        )
    if re.fullmatch(r"[0-9a-f]{40}", app_sha) is None:
        raise UpgradeRefused(
            "APPLICATION_SHA_REQUIRED: a full 40-character commit SHA is required"
        )
    if not _git_commit_exists(repo, app_sha):
        raise UpgradeRefused(
            f"APPLICATION_ROLLBACK_BLOCKED: commit {app_sha} does not exist in {repo}"
        )
    previous_sha = manifest["previous_sha"]
    head = _git_head(repo)
    if head is None:
        raise UpgradeRefused(
            "APPLICATION_ROLLBACK_BLOCKED: cannot determine the current HEAD"
        )
    branch = _git_output(repo, "branch", "--show-current")[1]
    # A retry after a partial coordinated failure is already detached at the
    # target SHA; allow it to converge without requiring a branch checkout.
    already_detached_at_target = not branch and head == app_sha
    if not already_detached_at_target:
        if branch != BRANCH:
            raise UpgradeRefused(
                "APPLICATION_ROLLBACK_BLOCKED: wrong branch "
                f"{branch!r}; expected {BRANCH!r}"
            )
        dirty = _git_output(repo, "status", "--porcelain")[1]
        if dirty:
            raise UpgradeRefused(
                "DIRTY_CODE_WORKTREE: review or remove local changes before a "
                f"coordinated rollback ({dirty.splitlines()[:5]})"
            )
    if app_sha != previous_sha and not _git_is_ancestor(repo, app_sha, previous_sha):
        raise UpgradeRefused(
            "APPLICATION_ROLLBACK_TARGET_NOT_ANCESTOR: "
            f"{app_sha} is neither the backup previous_sha {previous_sha} nor "
            "one of its ancestors. Refusing to roll the application code back "
            "across an unproven history."
        )
    return {
        "repo": str(repo),
        "app_sha": app_sha,
        "previous_sha": previous_sha,
        "head_before": head,
        "branch_before": branch,
        "already_detached_at_target": already_detached_at_target,
        "checkout_required": head != app_sha,
        "ancestor_of_previous_sha": app_sha != previous_sha,
    }


def _checkout_application_version(repo: Path, context: dict) -> None:
    """Non-destructive ``git checkout --detach`` to the validated target SHA.

    This function never calls ``git reset``, ``git clean`` or ``git stash``;
    local files are only replaced by Git's own checkout semantics for tracked
    files (the worktree was proven clean beforehand).
    """
    if not context["checkout_required"]:
        return
    command("git", "checkout", "--detach", context["app_sha"], cwd=Path(repo))


def _stop_services_quietly() -> None:
    for unit in (WORKER_UNIT, WEB_UNIT):
        try:
            _systemctl("stop", unit)
        except Exception:  # noqa: BLE001 - best effort on the failure path
            pass


def restore_data_backup(
    backup_dir: Path,
    data_dir: Path,
    *,
    apply: bool,
    acknowledge_data_restore: bool,
    force: bool = False,
    app_sha: str | None = None,
    repo: Path | None = None,
    force_idle: bool = False,
) -> dict:
    """Verify a backup and, when explicitly applied, restore its control DBs.

    Database restore and application-version rollback are separate actions:

    * ``app_sha is None`` restores only the recorded database files and returns
      ``application_rollback="not_requested"``; the caller must not assume the
      application code changed.
    * ``app_sha=<sha>`` performs the coordinated rollback: the target must be the
      backup's ``previous_sha`` or an ancestor, the backup schema must be proven
      compatible with the target code (fail-closed), the worktree is left clean
      before a non-destructive detached checkout, and after startup both the
      application HEAD and every restored database SHA256/quick_check are
      verified.  A failure keeps services stopped and never issues a second
      automatic rollback.

    Only the database files recorded in the manifest are replaced; databases
    created after the backup are intentionally left in place (this tool never
    deletes business data).  A strict SHA256/quick_check check runs right after
    the atomic replacement with services stopped; after startup the same files
    are checked for readability and compared again, because the platform
    re-asserts WAL mode and may checkpoint on first connection.
    """
    backup_dir = Path(backup_dir).resolve()
    data_dir = Path(data_dir).resolve()
    repo_path = Path(repo).resolve() if repo is not None else None
    verification = verify_data_backup(backup_dir)
    manifest = verification["manifest"]
    recorded_data_dir = Path(str(manifest.get("data_dir") or "")).resolve()
    if recorded_data_dir != data_dir:
        raise UpgradeRefused(
            "BACKUP_DATA_DIR_MISMATCH: the verified backup was taken from "
            f"{recorded_data_dir} but the restore target is {data_dir}; refusing "
            "to restore a backup into a different data directory"
        )
    forced = bool(force)
    coordinated = app_sha is not None
    application_rollback = APPLICATION_ROLLBACK_NOT_REQUESTED
    application_context: dict = {}
    schema_assessment: dict = {
        "status": "not_checked",
        "reason": (
            "no repository/code reference was supplied; database-only restore "
            "keeps its historical behaviour and does not verify schema "
            "compatibility"
        ),
        "databases": [],
        "blocking": [],
    }
    requested_sha: str | None = None
    if coordinated:
        requested_sha = str(app_sha).strip()
        if re.fullmatch(r"[0-9a-f]{40}", requested_sha) is None:
            raise UpgradeRefused(
                "APPLICATION_SHA_REQUIRED: a full 40-character commit SHA is "
                "required for --rollback-application-to"
            )
        if repo_path is None:
            raise UpgradeRefused(
                "APPLICATION_ROLLBACK_BLOCKED: a coordinated application "
                "rollback requires --repo pointing at the Git worktree"
            )
        application_context = validate_application_rollback_context(
            manifest, repo_path, requested_sha,
        )
        schema_assessment = assess_backup_schema_compatibility(
            backup_dir, manifest, repo=repo_path, code_sha=requested_sha,
        )
        _raise_for_schema_assessment(schema_assessment)
        application_rollback = APPLICATION_ROLLBACK_PLANNED
    elif repo_path is not None:
        # A database-only rollback still fails closed when a code reference is
        # available: the currently running worktree code must understand the DB.
        schema_assessment = assess_backup_schema_compatibility(
            backup_dir, manifest, repo=repo_path, code_sha=None,
        )
        _raise_for_schema_assessment(schema_assessment)

    # N6.1: bind the recorded frontend build identity / Python dependency
    # fingerprint to what is deployed now.  This is read-only and never blocks
    # by itself; an explicit risk list is attached to the result.
    identity_reference_sha = (
        requested_sha if coordinated else (
            _git_head(repo_path) if repo_path is not None else None
        )
    )
    application_identity_binding = assess_application_identity_binding(
        manifest, repo_path, app_sha=identity_reference_sha,
    )
    identity_risks = list(application_identity_binding.get("risks") or ())

    runtime_activity = probe_runtime_activity(data_dir, repo=repo_path)
    summary = {
        "backup_dir": str(backup_dir),
        "data_dir": str(data_dir),
        "manifest_sha256": manifest["manifest_sha256"],
        "previous_sha": manifest["previous_sha"],
        "target_sha": manifest["target_sha"],
        "total_bytes": manifest["total_bytes"],
        "entries": [entry["relative_path"] for entry in manifest["entries"]],
        "application_rollback": application_rollback,
        "application_sha": requested_sha,
        "schema_status": schema_assessment.get("status"),
        "schema_assessment": schema_assessment,
        "runtime_activity": runtime_activity,
        "application_identity_binding": application_identity_binding,
        "identity_risks": identity_risks,
    }
    if identity_risks:
        print(
            "APPLICATION_IDENTITY_RISK: "
            + json.dumps(
                {
                    "risks": identity_risks,
                    "frontend_build": application_identity_binding.get(
                        "frontend_build"
                    ),
                    "python_dependencies": application_identity_binding.get(
                        "python_dependencies"
                    ),
                },
                ensure_ascii=False, sort_keys=True,
            ),
            file=sys.stderr,
        )
    if not apply:
        return {
            "mode": "DRY RUN",
            "applied": False,
            "forced": forced,
            "application_sha_verified": None,
            "database_sha256_verified": None,
            **summary,
        }

    _require_apply_privileges()
    if not acknowledge_data_restore:
        raise UpgradeRefused(
            "DATA_RESTORE_NOT_ACKNOWLEDGED: pass --acknowledge-data-restore "
            "only after accepting that the current control-plane databases will "
            "be replaced by the verified backup"
        )
    override_idle = forced or force_idle
    if not override_idle:
        require_idle_tasks(data_dir, block_code="ACTIVE_TASKS_BLOCK_ROLLBACK")
    runtime_gate = enforce_backup_write_silence(
        runtime_activity,
        force_idle=override_idle,
        require_idle_only=False,
    )

    safety = _create_pre_rollback_safety_backup(
        backup_dir, data_dir, manifest, repo=repo_path,
    )
    code_switched = False
    post_stop_activity: dict | None = None
    try:
        _systemctl("stop", WORKER_UNIT)
        _systemctl("stop", WEB_UNIT)
        post_stop_activity = require_post_stop_idle(
            data_dir, repo=repo_path,
            block_code="POST_STOP_ACTIVITY_BLOCK_ROLLBACK",
            force_idle=override_idle,
        )
        print(
            "POST-STOP IDLE PROBE: "
            f"{post_stop_activity['status']} "
            f"forced_reasons={post_stop_activity['forced_reasons']} "
            "(write_silence stays unverified; this is not a consistency claim)."
        )
        if coordinated:
            _checkout_application_version(repo_path, application_context)
            code_switched = True
            changed = restore_tracked_code_modes(repo_path)
            print(f"Code permissions normalized: {changed} tracked files.")
            checked_out = _git_head(repo_path)
            if checked_out != requested_sha:
                raise UpgradeRefused(
                    "APPLICATION_SHA_MISMATCH: checkout produced "
                    f"{checked_out} instead of {requested_sha}"
                )
        restoration = _restore_backup_files_with_diagnostics(
            backup_dir, data_dir, manifest,
        )
        if restoration["failed"]:
            diagnostics = {
                "partial_restore": restoration,
                "safety_backup_dir": safety.get("safety_backup_dir"),
                "safety_backup_manifest_sha256": safety.get(
                    "safety_backup_manifest_sha256"
                ),
                "services": "stopped",
                "application_sha": requested_sha,
                "post_stop_activity": post_stop_activity,
                "identity_risks": identity_risks,
                "retry": (
                    "Rerun the same command after re-verifying the backup; "
                    "databases that already match the manifest are re-verified "
                    "and skipped, so a manual retry converges."
                ),
            }
            safety_location = (
                safety.get("safety_backup_dir")
                or "<none: no current control database>"
            )
            raise PartialRestoreFailed(
                "PARTIAL_RESTORE: "
                f"{len(restoration['failed'])} of "
                f"{restoration['entries_total']} database files failed to "
                f"restore; services are stopped. Pre-rollback safety backup: "
                f"{safety_location}. No automatic second rollback was attempted.",
                diagnostics,
            )
        restored = _verify_restored_files(data_dir, manifest)
        _systemctl("start", WEB_UNIT)
        health = wait_web_health()
        _systemctl("start", WORKER_UNIT)
        if _systemctl("is-active", WORKER_UNIT) != "active":
            raise UpgradeRefused("WORKER_NOT_ACTIVE_AFTER_ROLLBACK")
        post_start = _post_start_database_check(data_dir, manifest)
        if not post_start["post_start_sha256_unchanged"]:
            print(
                "WARNING: post-start database hashes differ from the verified "
                "backup manifest (services may have checkpointed or migrated); "
                f"mismatches={sorted(post_start['post_start_sha256_mismatches'])}",
                file=sys.stderr,
            )
        application_sha_verified: bool | None = None
        if coordinated:
            actual_head = _git_head(repo_path)
            application_sha_verified = actual_head == requested_sha
            if not application_sha_verified:
                raise UpgradeRefused(
                    "APPLICATION_SHA_VERIFY_FAILED: HEAD is "
                    f"{actual_head} after the coordinated rollback, expected "
                    f"{requested_sha}"
                )
        entries_restored = (
            len(restoration["restored"]) + len(restoration["already_restored"])
        )
        branch_restore_command = (
            f"git -C {repo_path} switch {BRANCH}" if coordinated else None
        )
        result = {
            "mode": "APPLIED",
            "applied": True,
            "forced": forced,
            **summary,
            "forced_idle": bool(force_idle),
            "runtime_gate": runtime_gate,
            "post_stop_activity": post_stop_activity,
            "application_rollback": (
                APPLICATION_ROLLBACK_APPLIED
                if coordinated else APPLICATION_ROLLBACK_NOT_REQUESTED
            ),
            "application_sha": requested_sha,
            "application_sha_verified": application_sha_verified,
            "application_context": application_context,
            "code_switched": code_switched,
            "detached_head": bool(coordinated),
            "branch_restore_required": bool(coordinated),
            "branch_restore_command": branch_restore_command,
            "database_sha256_verified": True,
            "schema_status": schema_assessment.get("status"),
            "health": health,
            "entries_restored": entries_restored,
            "partial_restore": restoration,
            "web_health_version": health.get("version") if isinstance(health, dict) else None,
            **restored,
            **post_start,
            **safety,
        }
        print(
            "ROLLBACK VERIFIED: "
            f"application_rollback={result['application_rollback']} "
            f"application_sha_verified={application_sha_verified} "
            f"database_sha256_verified=True "
            f"schema_status={result['schema_status']} "
            f"health={json.dumps(health, ensure_ascii=False, sort_keys=True)} "
            f"entries_restored={entries_restored} "
            f"identity_risks={identity_risks}"
        )
        if coordinated:
            print(
                "CODE ROLLED BACK (detached): "
                f"{requested_sha}. A later --target upgrade is refused until "
                "the release branch is restored explicitly: "
                f"{branch_restore_command}. This tool does not restore the "
                "previous branch checkout automatically and never auto-merges."
            )
            print(
                "FRONTEND BUILD: not restorable by Git (gitignored build "
                "output); restore static/vue-catalog and static/vue-app from "
                "the matching build if the deployed UI must match the "
                f"rollback target {requested_sha}. "
                f"frontend_restorable_by_git="
                f"{result['application_identity_binding']['frontend_build']['restorable_by_git']}"
            )
        return result
    except PartialRestoreFailed:
        _stop_services_quietly()
        print(
            "STOPPED: partial database restore failure; services were left "
            "stopped and no automatic second rollback was attempted. See the "
            "structured partial_restore diagnostics for replaced/failed/"
            "untouched databases.",
            file=sys.stderr,
        )
        raise
    except Exception:
        # Never mask a partially applied migration state with an automatic
        # second rollback; keep services down and point at the safety snapshot.
        _stop_services_quietly()
        safety_location = safety.get("safety_backup_dir") or "<none: no current control database>"
        code_note = (
            f" Code worktree is left checked out at {requested_sha}."
            if coordinated and code_switched else ""
        )
        print(
            "STOPPED: rollback failed after services were stopped; services were "
            f"left stopped.{code_note} Pre-rollback safety backup: "
            f"{safety_location}. This tool will not automatically roll the data "
            "or the application code back again.",
            file=sys.stderr,
        )
        raise


# ---------------------------------------------------------------------------
# Upgrade entry point
# ---------------------------------------------------------------------------

def upgrade(repo: Path, data_dir: Path, target: str, apply: bool,
            acknowledge_no_backup: bool,
            backup_dir: Path | None = None,
            force_idle: bool = False) -> None:
    repo = repo.resolve()
    os.umask(0o022)
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise UpgradeRefused("TARGET_SHA_REQUIRED: supply a reviewed 40-character commit SHA")
    _require_upgrade_privileges(apply)
    branch_restore_command = f"git -C {repo} switch {BRANCH}"
    current_branch = command("git", "branch", "--show-current", cwd=repo)
    if not current_branch:
        # N6.1: a coordinated rollback deliberately leaves a detached HEAD.
        # This tool never switches branches or merges on its own; the operator
        # must restore the release branch explicitly before the next upgrade.
        _, detached_head, _ = _git_output(repo, "rev-parse", "HEAD")
        detached_note = (
            f" at {detached_head[:12]}" if re.fullmatch(r"[0-9a-f]{40}", detached_head)
            else ""
        )
        raise UpgradeRefused(
            "DETACHED_HEAD_UPGRADE_BLOCKED: the worktree is in detached HEAD "
            f"state{detached_note}. A coordinated rollback leaves a detached "
            "HEAD on purpose; this tool never switches branches automatically. "
            "Restore the release branch explicitly first: "
            f"{branch_restore_command}   (or: git -C {repo} checkout {BRANCH}) "
            "then re-run --target."
        )
    if current_branch != BRANCH:
        raise UpgradeRefused(f"WRONG_BRANCH: {current_branch}")
    if command("git", "status", "--porcelain", cwd=repo):
        raise UpgradeRefused("DIRTY_CODE_WORKTREE: review local changes before upgrading")
    previous = command("git", "rev-parse", "HEAD", cwd=repo)
    require_idle_tasks(data_dir)
    for unit in (WEB_UNIT, WORKER_UNIT):
        if command("systemctl", "is-active", unit) != "active":
            raise UpgradeRefused(f"SERVICE_NOT_HEALTHY_BEFORE_UPGRADE: {unit}")
    # N6.1 item 2: read-only systemd configuration snapshot taken before the
    # services are touched; it is compared after the upgrade and never edited.
    systemd_config_before = capture_systemd_configuration() if apply else None
    command("git", "fetch", "--no-tags", "origin", BRANCH, cwd=repo)
    command("git", "merge-base", "--is-ancestor", previous, target, cwd=repo)
    command("git", "merge-base", "--is-ancestor", target, "FETCH_HEAD", cwd=repo)
    print(f"Verified {previous[:12]} -> {target[:12]} ({BRANCH}); no active tasks.")
    if not apply:
        print("DRY RUN: no services stopped, no code changed.")
        if backup_dir is not None:
            print(
                "DRY RUN: --apply would create and verify a control-plane "
                f"database backup in {backup_dir} before switching code."
            )
        return
    if backup_dir is None:
        if not acknowledge_no_backup:
            raise UpgradeRefused(
                "DATA_BACKUP_REQUIRED: pass --backup-dir PATH to snapshot the "
                "control-plane SQLite databases, or pass "
                "--acknowledge-no-data-backup only after accepting that Git "
                "cannot restore database changes"
            )
        backup = None
    else:
        backup = create_data_backup(
            data_dir, backup_dir, previous_sha=previous, target_sha=target,
            repo=repo, force_idle=force_idle,
        )
        print(
            f"Backup verified: {backup['backup_dir']} "
            f"entries={len(backup['entries'])} bytes={backup['total_bytes']} "
            f"manifest={backup['manifest_sha256'][:12]} target={target[:12]}"
        )
    command("systemctl", "stop", WORKER_UNIT)
    command("systemctl", "stop", WEB_UNIT)
    switched = False
    try:
        require_idle_tasks(data_dir)
        # N6.1 item 3: second read-only activity recheck after the services
        # stopped (holds/heartbeats/worker marker); positive evidence fails
        # closed and --force-idle is the only explicit override.
        post_stop_activity = require_post_stop_idle(
            data_dir, repo=repo,
            block_code="POST_STOP_ACTIVITY_BLOCK_UPGRADE",
            force_idle=force_idle,
        )
        print(
            "POST-STOP IDLE PROBE: "
            f"{post_stop_activity['status']} "
            f"forced_reasons={post_stop_activity['forced_reasons']} "
            "(write_silence stays unverified; this is not a consistency claim)."
        )
        command("git", "merge", "--ff-only", target, cwd=repo)
        switched = True
        changed = restore_tracked_code_modes(repo)
        print(f"Code permissions normalized: {changed} tracked files.")
        verify_service_code_access(repo, WEB_UNIT)
        verify_service_code_access(repo, WORKER_UNIT)
        command("systemctl", "start", WEB_UNIT)
        health = wait_web_health()
        command("systemctl", "start", WORKER_UNIT)
        time.sleep(2)
        if command("systemctl", "is-active", WORKER_UNIT) != "active":
            raise UpgradeRefused("WORKER_NOT_ACTIVE_AFTER_UPGRADE")
        actual = command("git", "rev-parse", "HEAD", cwd=repo)
        if actual != target:
            raise UpgradeRefused("TARGET_MISMATCH_AFTER_UPGRADE")
        if backup is not None and backup.get("target_sha") != target:
            raise UpgradeRefused(
                "BACKUP_TARGET_SHA_MISMATCH: backup manifest does not record "
                f"the deployed target {target}"
            )
        if systemd_config_before is not None:
            systemd_configuration = compare_systemd_configuration(
                systemd_config_before, capture_systemd_configuration(),
            )
            if systemd_configuration["risk"]:
                print(
                    "SYSTEMD_CONFIGURATION_RISK: "
                    + json.dumps(systemd_configuration, ensure_ascii=False,
                                 sort_keys=True),
                    file=sys.stderr,
                )
            else:
                print(
                    "SYSTEMD_CONFIGURATION: unchanged during the upgrade "
                    "(read-only comparison; units/environment files were "
                    "never edited by this tool)."
                )
        if backup is None:
            # Preserve the historical output for the pre-existing invocation.
            print(f"SUCCESS: {target[:12]} Web={health.get('version')} Worker=active")
        else:
            print(
                f"SUCCESS: {target[:12]} Web={health.get('version')} "
                f"Worker=active. Backup={backup['backup_dir']} "
                f"manifest={backup['manifest_sha256'][:12]}"
            )
    except Exception:
        if systemd_config_before is not None:
            try:
                observed_configuration = compare_systemd_configuration(
                    systemd_config_before, capture_systemd_configuration(),
                )
                if observed_configuration["status"] in ("changed", "partial"):
                    print(
                        "SYSTEMD_CONFIGURATION_RISK_ON_FAILURE: "
                        + json.dumps(observed_configuration, ensure_ascii=False,
                                     sort_keys=True),
                        file=sys.stderr,
                    )
            except Exception:  # noqa: BLE001 - never mask the original failure
                pass
        if not switched:
            # No code was switched; restore the previous running services.
            subprocess.run(["systemctl", "start", WEB_UNIT], check=False)
            subprocess.run(["systemctl", "start", WORKER_UNIT], check=False)
        else:
            # Never silently revert code against potentially migrated business state.
            subprocess.run(["systemctl", "stop", WORKER_UNIT], check=False)
            subprocess.run(["systemctl", "stop", WEB_UNIT], check=False)
            backup_note = (
                f" Pre-upgrade backup: {backup['backup_dir']}"
                if backup is not None else ""
            )
            print(f"STOPPED: inspected target={target}; previous={previous}. "
                  "Business data was not restored or modified by this tool."
                  f"{backup_note}", file=sys.stderr)
        raise


def _print_backup_result(result: dict) -> None:
    frontend_build = result.get("frontend_build")
    if not isinstance(frontend_build, dict):
        frontend_build = {}
    python_dependencies = result.get("python_dependencies")
    if not isinstance(python_dependencies, dict):
        python_dependencies = {}
    print(json.dumps({
        "mode": "BACKUP_ONLY",
        "backup_dir": result["backup_dir"],
        "manifest_sha256": result["manifest_sha256"],
        "previous_sha": result["previous_sha"],
        "target_sha": result["target_sha"],
        "total_bytes": result["total_bytes"],
        "entries": [entry["relative_path"] for entry in result["entries"]],
        "entries_verified": result.get("entries_verified"),
        "application_version": result.get("application_version"),
        "build_id": result.get("build_id"),
        "frontend_build": {
            key: frontend_build.get(key)
            for key in (
                "status", "reason", "identity", "receipt_code_sha",
                "build_origin", "matches_code_sha", "ui_build_version",
                "verified_asset_bytes",
            )
        },
        "python_dependencies": {
            key: python_dependencies.get(key)
            for key in (
                "status", "reason", "fingerprint", "requirements_digest",
                "installed_count",
            )
        },
        "schema_versions": result.get("schema_versions"),
        "write_silence": result.get("write_silence"),
        "write_silence_detail": result.get("write_silence_detail"),
        "consistency": result.get("consistency"),
        "backup_scope": result.get("backup_scope"),
        "exclusions": [item["path"] for item in result["exclusions"]],
    }, ensure_ascii=False, indent=2))


def _git_worktree_or_none(repo: Path) -> Path | None:
    candidate = Path(repo).resolve()
    return candidate if (candidate / ".git").exists() else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Backup scope: control-plane SQLite databases only "
            "(task_runtime/tasks.sqlite3, storage/storage_sources.sqlite3, "
            "model_artifacts/artifacts.sqlite3, "
            "external_algorithm_publish/publications.sqlite3, "
            "projects/<project_id>/*.sqlite3).\n"
            "NOT backed up: raw material/media objects, model files/weights, "
            "training artifacts/checkpoints, and other project business files. "
            "This is NOT a disaster-recovery backup; backup.json records "
            "write_silence=unverified and the explicit exclusions.\n"
            "Git cannot restore database changes: --rollback restores only the "
            "database files recorded in the verified manifest. Databases created "
            "after the backup are not deleted.\n"
            "Database restore and application rollback are separate actions: "
            "--rollback alone never changes application code "
            "(application_rollback=not_requested). Use "
            "--rollback-application-to <40-hex-SHA> to additionally require the "
            "target SHA to be the backup previous_sha or an ancestor, verify the "
            "backup database schema against that code (fail-closed) and perform "
            "a non-destructive detached checkout before the restore.\n"
            "Application identity binding: backup.json records the deployed "
            "frontend build identity (static/vue-catalog/offline-assets.json and "
            "static/vue-app/offline-assets.json receipts, UI_BUILD_VERSION) and "
            "a Python dependency fingerprint (requirements*.txt digests plus "
            "installed key distributions). Unreadable identities are recorded as "
            "explicit 'unavailable', never guessed. The frontend build "
            "directories are gitignored, so --rollback cannot restore them from "
            "Git; the rollback result reports that risk explicitly.\n"
            "Detached HEAD: a coordinated --rollback leaves a detached HEAD. A "
            "later --target upgrade is refused with the exact 'git switch' "
            "command until the release branch is restored explicitly; this tool "
            "never switches branches or merges on its own.\n"
            "systemd configuration: an --apply upgrade hashes the unit files, "
            "drop-ins and environment files before and after and reports "
            "SYSTEMD_CONFIGURATION_CHANGED_DURING_UPGRADE as an explicit risk; it "
            "never edits them.\n"
            "Post-stop recheck: after the services stop, runtime activity "
            "(active tasks, unreleased holds, agent heartbeats, worker build "
            "marker) is re-probed and positive evidence fails closed; only the "
            "explicit --force-idle override records a forced decision."
        ),
    )
    parser.add_argument("--repo", type=Path, default=Path("/data/platform/aixunlianpingtai"))
    parser.add_argument("--data-dir", type=Path, default=Path("/data/platform-data"))
    parser.add_argument(
        "--target", default=None,
        help="pinned, CI-verified Git commit SHA (required unless --backup-only/--rollback)",
    )
    parser.add_argument("--apply", action="store_true",
                        help="actually switch code/services (upgrade) or restore data (rollback)")
    parser.add_argument("--acknowledge-no-data-backup", action="store_true",
                        help="accept that no data backup is taken and Git cannot restore database changes")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="empty/new directory for the verified control-plane database backup")
    parser.add_argument("--backup-only", action="store_true",
                        help="only create and verify a control-plane database backup; never touches services")
    parser.add_argument("--rollback", action="store_true",
                        help="verify and (with --apply) restore the control-plane databases from --backup-dir")
    parser.add_argument("--rollback-application-to", default=None, metavar="SHA",
                        help="with --rollback: explicitly roll the application code back to this "
                             "40-hex SHA (must be the backup previous_sha or an ancestor); performs "
                             "a non-destructive detached checkout coordinated with the database restore")
    parser.add_argument("--force", action="store_true",
                        help="with --rollback --apply: skip the idle-task gate (still requires --acknowledge-data-restore)")
    parser.add_argument("--force-idle", action="store_true",
                        help="with --backup-only/--rollback/--apply upgrade: override active-task/"
                             "resource-hold/agent/build-marker probes; backup.json records forced and "
                             "write_silence stays unverified (no consistency claim)")
    parser.add_argument("--require-idle-only", action="store_true",
                        help="with --backup-only: also refuse when a read-only idleness probe is "
                             "unavailable (unknown is never treated as idle)")
    parser.add_argument("--acknowledge-data-restore", action="store_true",
                        help="explicitly accept that current control-plane databases will be replaced")
    args = parser.parse_args()
    try:
        if args.backup_only and args.rollback:
            raise UpgradeRefused(
                "CONFLICTING_MODES: --backup-only and --rollback are mutually exclusive"
            )
        if args.rollback_application_to is not None and not args.rollback:
            raise UpgradeRefused(
                "CONFLICTING_MODES: --rollback-application-to requires --rollback"
            )
        if args.backup_only:
            if args.backup_dir is None:
                raise UpgradeRefused(
                    "BACKUP_DIR_REQUIRED: --backup-only requires --backup-dir PATH"
                )
            if args.rollback_application_to is not None:
                raise UpgradeRefused(
                    "CONFLICTING_MODES: --rollback-application-to requires --rollback"
                )
            repo_path = args.repo.resolve()
            previous = command("git", "rev-parse", "HEAD", cwd=repo_path)
            result = create_data_backup(
                args.data_dir, args.backup_dir,
                previous_sha=previous, target_sha=args.target,
                repo=_git_worktree_or_none(repo_path),
                force_idle=args.force_idle,
                require_idle_only=args.require_idle_only,
            )
            _print_backup_result(result)
            return 0
        if args.rollback:
            if args.backup_dir is None:
                raise UpgradeRefused(
                    "BACKUP_DIR_REQUIRED: --rollback requires --backup-dir PATH"
                )
            if args.rollback_application_to is not None:
                repo_path: Path | None = args.repo.resolve()
            else:
                repo_path = _git_worktree_or_none(args.repo)
            result = restore_data_backup(
                args.backup_dir, args.data_dir,
                apply=args.apply,
                acknowledge_data_restore=args.acknowledge_data_restore,
                force=args.force,
                app_sha=args.rollback_application_to,
                repo=repo_path,
                force_idle=args.force_idle,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.target is None:
            raise UpgradeRefused(
                "TARGET_SHA_REQUIRED: supply a reviewed 40-character commit SHA"
            )
        upgrade(args.repo, args.data_dir, args.target, args.apply,
                args.acknowledge_no_data_backup, backup_dir=args.backup_dir,
                force_idle=args.force_idle)
        return 0
    except PartialRestoreFailed as exc:
        print(json.dumps(
            {"mode": "PARTIAL_RESTORE", **exc.diagnostics},
            ensure_ascii=False, indent=2,
        ))
        print(f"DEPLOYMENT_REFUSED: {exc}", file=sys.stderr)
        return 1
    except (UpgradeRefused, OSError, subprocess.CalledProcessError) as exc:
        print(f"DEPLOYMENT_REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
