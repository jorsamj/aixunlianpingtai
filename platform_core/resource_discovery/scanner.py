"""Streaming whole-machine discovery of Python executables and model files.

The scanner deliberately separates visible scan roots (``disk_partitions``
with ``all=False``) from the complete mount table used as traversal
boundaries.  That distinction prevents a scan rooted at ``/`` from wandering
into a network or virtual child mount without hard-coding drive letters or
Linux mount locations.
"""
from __future__ import annotations

import os
import re
import stat as stat_module
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


MODEL_EXTENSIONS = frozenset(
    {
        ".pt",
        ".pth",
        ".onnx",
        ".engine",
        ".rknn",
        ".bmodel",
        ".om",
        ".pdparams",
        ".pdmodel",
        ".pdiparams",
    }
)

_PYTHON_EXECUTABLE = re.compile(
    r"^python(?:3(?:\.\d+)*)?(?:\.exe)?$", re.IGNORECASE
)
_NETWORK_FILESYSTEMS = frozenset(
    {
        "9p",
        "afs",
        "afp",
        "afpfs",
        "beegfs",
        "ceph",
        "ceph-fuse",
        "cifs",
        "cvmfs",
        "davfs",
        "davfs2",
        "fuse.azureblob",
        "fuse.ceph",
        "fuse.gcsfuse",
        "fuse.glusterfs",
        "fuse.goofys",
        "fuse.s3fs",
        "fuse.sshfs",
        "fuse.rclone",
        "glusterfs",
        "gpfs",
        "hdfs",
        "juicefs",
        "lustre",
        "lustre_lite",
        "moosefs",
        "ncpfs",
        "nfs",
        "nfs4",
        "orangefs",
        "panfs",
        "quobyte",
        "smb",
        "smb2",
        "smb3",
        "smbfs",
        "sshfs",
    }
)
_VIRTUAL_FILESYSTEMS = frozenset(
    {
        "autofs",
        "binfmt_misc",
        "bpf",
        "cgroup",
        "cgroup2",
        "configfs",
        "debugfs",
        "devfs",
        "devpts",
        "devtmpfs",
        "efivarfs",
        "fusectl",
        "hugetlbfs",
        "mqueue",
        "nsfs",
        "overlay",
        "proc",
        "pstore",
        "ramfs",
        "rpc_pipefs",
        "securityfs",
        "sysfs",
        "tmpfs",
        "tracefs",
    }
)
_PROGRESS_INTERVAL = 128
_VISITED_SAMPLE_LIMIT = 4096


@dataclass(frozen=True)
class MountInfo:
    """One normalized filesystem mount and its traversal classification."""

    device: str
    mountpoint: Path
    fstype: str
    opts: str
    excluded: bool


@dataclass
class ScanReport:
    """Truthful counters for a streaming discovery pass.

    ``visited_directories`` is a bounded diagnostic sample for tests and
    troubleshooting.  It is intentionally not an exhaustive scan manifest.
    """

    scanned_dirs: int = 0
    python_candidates: int = 0
    validated_environments: int = 0
    models_found: int = 0
    current_path: str = ""
    permission_errors: int = 0
    scan_errors: int = 0
    cancelled: bool = False
    visited_directories: set[Path] = field(default_factory=set)

    def progress(self) -> dict[str, Any]:
        return {
            "scanned_dirs": self.scanned_dirs,
            "python_candidates": self.python_candidates,
            "validated_environments": self.validated_environments,
            "models_found": self.models_found,
            "current_path": self.current_path,
            "permission_errors": self.permission_errors,
        }


ProgressCallback = Callable[[dict[str, Any]], None]
CancelCallback = Callable[[], bool]


def _unescape_mountinfo(value: str) -> str:
    # Linux mountinfo escapes whitespace, backslash, and a few control bytes as
    # three-digit octal sequences.
    return re.sub(
        r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value
    )


def _mountinfo_fallback() -> list[MountInfo]:
    rows: list[MountInfo] = []
    try:
        with Path("/proc/self/mountinfo").open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                fields = raw_line.rstrip("\n").split()
                if "-" not in fields or len(fields) < 10:
                    continue
                separator = fields.index("-")
                if separator + 2 >= len(fields):
                    continue
                mountpoint = _unescape_mountinfo(fields[4])
                fstype = fields[separator + 1]
                device = _unescape_mountinfo(fields[separator + 2])
                opts = ",".join((fields[5], fields[separator + 3] if separator + 3 < len(fields) else ""))
                rows.append(_make_mount(device, mountpoint, fstype, opts))
    except (OSError, UnicodeError, ValueError):
        return []
    return rows


def _is_excluded_filesystem(device: str, mountpoint: str, fstype: str, opts: str) -> bool:
    fs = str(fstype or "").strip().lower()
    option_set = {item.strip().lower() for item in str(opts or "").split(",")}
    device_text = str(device or "").strip().lower()
    mount_text = str(mountpoint or "").strip().lower()
    if fs in _NETWORK_FILESYSTEMS or fs.startswith(("nfs", "smb", "cifs")):
        return True
    if fs in _VIRTUAL_FILESYSTEMS or fs.startswith("cgroup"):
        return True
    if "remote" in option_set or "network" in option_set or "_netdev" in option_set:
        return True
    if device_text.startswith(("//", "\\\\")) or mount_text.startswith(("//", "\\\\")):
        return True
    return False


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


def _mount_path(value: object, platform: str) -> Path:
    raw = str(value or ("C:/" if platform.startswith("win") else "/"))
    # Preserve mocked/serialized platform paths when discovery policy is tested
    # on a different host OS. Actual scans use the current platform and these
    # still resolve to native Path objects.
    if platform.startswith("win"):
        raw = raw.replace("\\", "/")
    return Path(raw)


def _make_mount(
    device: object,
    mountpoint: object,
    fstype: object,
    opts: object,
    *,
    platform: str | None = None,
) -> MountInfo:
    platform_name = (platform or sys.platform).lower()
    point = _mount_path(mountpoint, platform_name)
    device_text = str(device or "")
    fs_text = str(fstype or "")
    opts_text = str(opts or "")
    return MountInfo(
        device=device_text,
        mountpoint=point,
        fstype=fs_text,
        opts=opts_text,
        excluded=_is_excluded_filesystem(
            device_text, os.fspath(point), fs_text, opts_text
        ),
    )


def _partition_mounts(*, include_all: bool, platform: str | None = None) -> list[MountInfo]:
    platform_name = (platform or sys.platform).lower()
    try:
        partitions = psutil.disk_partitions(all=include_all)
    except (OSError, RuntimeError):
        partitions = []
    mounts = [
        _make_mount(
            getattr(partition, "device", ""),
            getattr(partition, "mountpoint", os.sep),
            getattr(partition, "fstype", ""),
            getattr(partition, "opts", ""),
            platform=platform_name,
        )
        for partition in partitions
    ]
    if include_all and not mounts and platform_name.startswith("linux"):
        mounts = _mountinfo_fallback()
    return mounts


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def _contains(parent: Path, child: Path) -> bool:
    try:
        return os.path.commonpath((_path_key(parent), _path_key(child))) == _path_key(parent)
    except (OSError, ValueError):
        return False


def local_scan_roots(*, platform: str | None = None) -> list[Path]:
    """Return all visible local filesystem roots without fixed drive letters."""

    result: list[Path] = []
    seen: set[str] = set()
    for mount in _partition_mounts(include_all=False, platform=platform):
        if mount.excluded:
            continue
        key = _path_key(mount.mountpoint)
        if key in seen:
            continue
        seen.add(key)
        result.append(mount.mountpoint)
    return result


def mount_boundaries(*, platform: str | None = None) -> tuple[MountInfo, ...]:
    """Return the complete, longest-path-first traversal boundary table."""

    mounts = _partition_mounts(include_all=True, platform=platform)
    unique: dict[str, MountInfo] = {}
    for mount in mounts:
        unique[_path_key(mount.mountpoint)] = mount
    return tuple(
        sorted(unique.values(), key=lambda item: len(_path_key(item.mountpoint)), reverse=True)
    )


def _owning_mount(path: Path, mounts: Sequence[MountInfo]) -> MountInfo | None:
    for mount in mounts:  # Caller supplies longest-path-first rows.
        if _contains(mount.mountpoint, path):
            return mount
    return None


def _directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    inode = int(getattr(metadata, "st_ino", 0) or 0)
    device = int(getattr(metadata, "st_dev", 0) or 0)
    return (device, inode) if inode else None


def _is_reparse_entry(entry: os.DirEntry[str]) -> bool:
    try:
        if entry.is_symlink():
            return True
        metadata = entry.stat(follow_symlinks=False)
        attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
        marker = int(getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
        return bool(marker and attributes & marker)
    except OSError:
        return True


def _should_cancel(
    cancel_requested: CancelCallback | None, stop_event: Any | None
) -> bool:
    if cancel_requested is not None and cancel_requested():
        return True
    return bool(stop_event is not None and stop_event.is_set())


def _emit_progress(report: ScanReport, callback: ProgressCallback | None) -> None:
    if callback is not None:
        callback(report.progress())


def _model_row(path: Path, metadata: os.stat_result, volume: str) -> dict[str, Any]:
    modified = float(metadata.st_mtime)
    return {
        "path": os.fspath(_absolute_path(path)),
        "name": path.name,
        "format": path.suffix.lower().lstrip("."),
        "size_bytes": max(0, int(metadata.st_size)),
        "mtime": modified,
        "modified_at": datetime.fromtimestamp(modified, timezone.utc).isoformat(),
        "volume": volume,
    }


def _scan(
    roots: Iterable[str | os.PathLike[str]] | None,
    *,
    mode: str,
    on_item: Callable[[Any], None] | None,
    on_progress: ProgressCallback | None,
    cancel_requested: CancelCallback | None,
    stop_event: Any | None,
    progress_every: int,
    platform: str | None,
) -> ScanReport:
    report = ScanReport()
    root_rows = local_scan_roots(platform=platform) if roots is None else [_absolute_path(root) for root in roots]
    deduplicated: list[Path] = []
    scheduled: set[str] = set()
    for root in root_rows:
        key = _path_key(root)
        if key not in scheduled:
            scheduled.add(key)
            deduplicated.append(root)

    boundaries = mount_boundaries(platform=platform)
    seen_directories: set[tuple[int, int]] = set()
    emit_every = max(1, int(progress_every or _PROGRESS_INTERVAL))
    visited_entries = 0

    def process_file(path: Path, metadata: os.stat_result, owner: MountInfo | None) -> None:
        name = path.name
        if mode == "python":
            if not _PYTHON_EXECUTABLE.fullmatch(name):
                return
            if not (platform or sys.platform).startswith("win") and not os.access(path, os.X_OK):
                return
            report.python_candidates += 1
            if on_item is not None:
                on_item(_absolute_path(path))
            return
        if path.suffix.lower() not in MODEL_EXTENSIONS:
            return
        report.models_found += 1
        if on_item is not None:
            on_item(
                _model_row(
                    path,
                    metadata,
                    os.fspath(owner.mountpoint) if owner is not None else path.anchor,
                )
            )

    for root in deduplicated:
        if _should_cancel(cancel_requested, stop_event):
            report.cancelled = True
            break
        try:
            if root.is_file():
                metadata = root.stat()
                process_file(root, metadata, _owning_mount(root, boundaries))
                continue
        except PermissionError:
            report.permission_errors += 1
            continue
        except OSError:
            report.scan_errors += 1
            continue

        root_owner = _owning_mount(root, boundaries)
        # Each frame is (directory, open scandir iterator).  Opening children
        # one at a time makes allocation proportional to depth, not tree size.
        frames: list[tuple[Path, os.ScandirIterator[str] | None]] = [(root, None)]
        try:
            while frames:
                if _should_cancel(cancel_requested, stop_event):
                    report.cancelled = True
                    break
                directory, iterator = frames[-1]
                if iterator is None:
                    owner = _owning_mount(directory, boundaries)
                    if owner is not None and owner.excluded and owner != root_owner:
                        frames.pop()
                        continue
                    directory_key = _path_key(directory)
                    if directory_key != _path_key(root) and directory_key in scheduled:
                        frames.pop()
                        continue
                    identity = _directory_identity(directory)
                    if identity is not None and identity in seen_directories:
                        frames.pop()
                        continue
                    if identity is not None:
                        seen_directories.add(identity)
                    try:
                        iterator = os.scandir(directory)
                    except PermissionError:
                        report.permission_errors += 1
                        frames.pop()
                        continue
                    except OSError:
                        report.scan_errors += 1
                        frames.pop()
                        continue
                    frames[-1] = (directory, iterator)
                    report.scanned_dirs += 1
                    report.current_path = os.fspath(directory)
                    if len(report.visited_directories) < _VISITED_SAMPLE_LIMIT:
                        report.visited_directories.add(directory)
                    if report.scanned_dirs % emit_every == 0:
                        _emit_progress(report, on_progress)
                try:
                    entry = next(iterator)
                except StopIteration:
                    iterator.close()
                    frames.pop()
                    continue
                except PermissionError:
                    report.permission_errors += 1
                    iterator.close()
                    frames.pop()
                    continue
                except OSError:
                    report.scan_errors += 1
                    iterator.close()
                    frames.pop()
                    continue

                visited_entries += 1
                entry_path = Path(entry.path)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not _is_reparse_entry(entry):
                            frames.append((entry_path, None))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                except PermissionError:
                    report.permission_errors += 1
                    continue
                except OSError:
                    report.scan_errors += 1
                    continue
                process_file(entry_path, metadata, _owning_mount(entry_path, boundaries))
                if visited_entries % emit_every == 0:
                    report.current_path = os.fspath(entry_path)
                    _emit_progress(report, on_progress)
        finally:
            for _, iterator in frames:
                if iterator is not None:
                    iterator.close()
        if report.cancelled:
            break

    _emit_progress(report, on_progress)
    return report


def scan_python_candidates(
    roots: Iterable[str | os.PathLike[str]] | None = None,
    *,
    on_item: Callable[[Path], None] | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
    stop_event: Any | None = None,
    progress_every: int = _PROGRESS_INTERVAL,
    platform: str | None = None,
) -> ScanReport:
    """Stream real Python executable candidates for later subprocess probing."""

    return _scan(
        roots,
        mode="python",
        on_item=on_item,
        on_progress=on_progress,
        cancel_requested=cancel_requested,
        stop_event=stop_event,
        progress_every=progress_every,
        platform=platform,
    )


def scan_model_files(
    roots: Iterable[str | os.PathLike[str]] | None = None,
    *,
    on_item: Callable[[dict[str, Any]], None] | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
    stop_event: Any | None = None,
    progress_every: int = _PROGRESS_INTERVAL,
    platform: str | None = None,
) -> ScanReport:
    """Stream supported model files without loading models into CPU or GPU."""

    return _scan(
        roots,
        mode="model",
        on_item=on_item,
        on_progress=on_progress,
        cancel_requested=cancel_requested,
        stop_event=stop_event,
        progress_every=progress_every,
        platform=platform,
    )


__all__ = [
    "MODEL_EXTENSIONS",
    "MountInfo",
    "ScanReport",
    "local_scan_roots",
    "mount_boundaries",
    "scan_model_files",
    "scan_python_candidates",
]
