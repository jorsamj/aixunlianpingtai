#!/usr/bin/env python3
"""Guarded release of the existing Git-worktree systemd production installation.

This operator-invoked tool validates branch/worktree/service/task state and
performs a pinned fast-forward plus tracked-file permission normalization.  It
can additionally take a verified, transaction-consistent snapshot of the
control-plane SQLite databases before an upgrade, and restore that snapshot
during an explicit, acknowledged rollback.

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
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
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
from pathlib import Path

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
)


class UpgradeRefused(RuntimeError):
    pass


def command(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False,
    )
    if proc.returncode:
        raise UpgradeRefused(
            f"{' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _systemctl(*args: str) -> str:
    """Single, monkeypatchable entry point for every systemd interaction."""
    return command("systemctl", *args)


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
    if require_idle:
        require_idle_tasks(data_dir)
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
        for database in databases:
            relative_path = database.relative_to(data_dir).as_posix()
            snapshot = _snapshot_sqlite(database, backup_dir / relative_path)
            entries.append({"relative_path": relative_path, **snapshot})
        entries.sort(key=lambda entry: entry["relative_path"])
        total_bytes = sum(entry["size_bytes"] for entry in entries)
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
) -> dict:
    """Create and self-verify a consistency snapshot of control-plane SQLite DBs."""
    result = _create_backup(
        data_dir, backup_dir,
        previous_sha=previous_sha,
        target_sha=target_sha,
        max_backup_bytes=max_backup_bytes,
        now=now,
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
    result = _create_backup(
        data_dir, destination,
        previous_sha=current_sha,
        target_sha=manifest["previous_sha"],
        now=None,
        purpose="pre-rollback",
        require_idle=False,
    )
    verification = verify_data_backup(destination)
    return {
        "safety_backup_dir": str(destination.resolve()),
        "safety_backup_manifest_sha256": verification["manifest_sha256"],
        "safety_backup_skipped": None,
    }


def _restore_backup_files(backup_dir: Path, data_dir: Path, manifest: dict) -> int:
    """Atomically replace each recorded database and drop stale WAL sidecars."""
    backup_dir = Path(backup_dir).resolve()
    data_dir = Path(data_dir).resolve()
    restored = 0
    for entry in manifest["entries"]:
        relative_path = entry["relative_path"]
        source = (backup_dir / relative_path).resolve()
        if not source.is_relative_to(backup_dir) or not source.is_file():
            raise UpgradeRefused(f"BACKUP_FILE_MISSING: {source}")
        target = (data_dir / relative_path).resolve()
        if not target.is_relative_to(data_dir):
            raise UpgradeRefused(
                f"BACKUP_MANIFEST_CORRUPT: entry escapes data dir: {relative_path}"
            )
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
        restored += 1
    return restored


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


def restore_data_backup(
    backup_dir: Path,
    data_dir: Path,
    *,
    apply: bool,
    acknowledge_data_restore: bool,
    force: bool = False,
) -> dict:
    """Verify a backup and, when explicitly applied, restore its control DBs.

    Only the database files recorded in the manifest are replaced; databases
    created after the backup are intentionally left in place (this tool never
    deletes business data).  A strict SHA256/quick_check check runs right after
    the atomic replacement with services stopped; after startup the same files
    are checked for readability and compared again, because the platform
    re-asserts WAL mode and may checkpoint on first connection.
    """
    backup_dir = Path(backup_dir).resolve()
    data_dir = Path(data_dir).resolve()
    verification = verify_data_backup(backup_dir)
    manifest = verification["manifest"]
    forced = bool(force)
    summary = {
        "backup_dir": str(backup_dir),
        "data_dir": str(data_dir),
        "manifest_sha256": manifest["manifest_sha256"],
        "previous_sha": manifest["previous_sha"],
        "target_sha": manifest["target_sha"],
        "total_bytes": manifest["total_bytes"],
        "entries": [entry["relative_path"] for entry in manifest["entries"]],
    }
    if not apply:
        return {
            "mode": "DRY RUN",
            "applied": False,
            "forced": forced,
            **summary,
        }

    _require_apply_privileges()
    if not acknowledge_data_restore:
        raise UpgradeRefused(
            "DATA_RESTORE_NOT_ACKNOWLEDGED: pass --acknowledge-data-restore "
            "only after accepting that the current control-plane databases will "
            "be replaced by the verified backup"
        )
    if not forced:
        require_idle_tasks(data_dir, block_code="ACTIVE_TASKS_BLOCK_ROLLBACK")

    safety = _create_pre_rollback_safety_backup(backup_dir, data_dir, manifest)
    try:
        _systemctl("stop", WORKER_UNIT)
        _systemctl("stop", WEB_UNIT)
        restored_entries = _restore_backup_files(backup_dir, data_dir, manifest)
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
        return {
            "mode": "APPLIED",
            "applied": True,
            "forced": forced,
            "entries_restored": restored_entries,
            "web_health_version": health.get("version") if isinstance(health, dict) else None,
            **restored,
            **post_start,
            **safety,
            **summary,
        }
    except Exception:
        # Never mask a partially applied migration state with an automatic
        # second rollback; keep services down and point at the safety snapshot.
        for unit in (WORKER_UNIT, WEB_UNIT):
            try:
                _systemctl("stop", unit)
            except Exception:
                pass
        safety_location = safety.get("safety_backup_dir") or "<none: no current control database>"
        print(
            "STOPPED: rollback failed after services were stopped; services were "
            f"left stopped. Pre-rollback safety backup: {safety_location}. "
            "This tool will not automatically roll the data back again.",
            file=sys.stderr,
        )
        raise


# ---------------------------------------------------------------------------
# Upgrade entry point
# ---------------------------------------------------------------------------

def upgrade(repo: Path, data_dir: Path, target: str, apply: bool,
            acknowledge_no_backup: bool,
            backup_dir: Path | None = None) -> None:
    repo = repo.resolve()
    os.umask(0o022)
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise UpgradeRefused("TARGET_SHA_REQUIRED: supply a reviewed 40-character commit SHA")
    _require_upgrade_privileges(apply)
    current_branch = command("git", "branch", "--show-current", cwd=repo)
    if current_branch != BRANCH:
        raise UpgradeRefused(f"WRONG_BRANCH: {current_branch}")
    if command("git", "status", "--porcelain", cwd=repo):
        raise UpgradeRefused("DIRTY_CODE_WORKTREE: review local changes before upgrading")
    previous = command("git", "rev-parse", "HEAD", cwd=repo)
    require_idle_tasks(data_dir)
    for unit in (WEB_UNIT, WORKER_UNIT):
        if command("systemctl", "is-active", unit) != "active":
            raise UpgradeRefused(f"SERVICE_NOT_HEALTHY_BEFORE_UPGRADE: {unit}")
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
    print(json.dumps({
        "mode": "BACKUP_ONLY",
        "backup_dir": result["backup_dir"],
        "manifest_sha256": result["manifest_sha256"],
        "previous_sha": result["previous_sha"],
        "target_sha": result["target_sha"],
        "total_bytes": result["total_bytes"],
        "entries": [entry["relative_path"] for entry in result["entries"]],
        "entries_verified": result.get("entries_verified"),
        "exclusions": [item["path"] for item in result["exclusions"]],
    }, ensure_ascii=False, indent=2))


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
            "Task artifacts and material/media files are content-addressed "
            "immutable data and are NOT backed up (see backup.json "
            "exclusions).\n"
            "Git cannot restore database changes: --rollback restores only the "
            "database files recorded in the verified manifest. Databases created "
            "after the backup are not deleted."
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
    parser.add_argument("--force", action="store_true",
                        help="with --rollback --apply: skip the idle-task gate (still requires --acknowledge-data-restore)")
    parser.add_argument("--acknowledge-data-restore", action="store_true",
                        help="explicitly accept that current control-plane databases will be replaced")
    args = parser.parse_args()
    try:
        if args.backup_only and args.rollback:
            raise UpgradeRefused(
                "CONFLICTING_MODES: --backup-only and --rollback are mutually exclusive"
            )
        if args.backup_only:
            if args.backup_dir is None:
                raise UpgradeRefused(
                    "BACKUP_DIR_REQUIRED: --backup-only requires --backup-dir PATH"
                )
            previous = command("git", "rev-parse", "HEAD", cwd=args.repo.resolve())
            result = create_data_backup(
                args.data_dir, args.backup_dir,
                previous_sha=previous, target_sha=args.target,
            )
            _print_backup_result(result)
            return 0
        if args.rollback:
            if args.backup_dir is None:
                raise UpgradeRefused(
                    "BACKUP_DIR_REQUIRED: --rollback requires --backup-dir PATH"
                )
            result = restore_data_backup(
                args.backup_dir, args.data_dir,
                apply=args.apply,
                acknowledge_data_restore=args.acknowledge_data_restore,
                force=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.target is None:
            raise UpgradeRefused(
                "TARGET_SHA_REQUIRED: supply a reviewed 40-character commit SHA"
            )
        upgrade(args.repo, args.data_dir, args.target, args.apply,
                args.acknowledge_no_data_backup, backup_dir=args.backup_dir)
        return 0
    except (UpgradeRefused, OSError, subprocess.CalledProcessError) as exc:
        print(f"DEPLOYMENT_REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
