"""Bounded, resumable ZIP extraction followed by a same-filesystem publication.

The configured roots must be controlled by the server, not writable by archive
submitters. One worker may use a task_id at a time. Call resolve_server_zip for
request-supplied source paths before passing the resulting path to the extractor.

MC_ZIP_* defaults permit 100 GiB imports: 1,000,000 members, 128 GiB per file,
512 GiB total, compression ratio 1,000, and disk headroom max(1 GiB, 5%). Invalid
configuration fails closed. Progress callbacks may return False or raise
ExtractionCancelled to cancel. Other callback exceptions retain their cause.
SystemExit (or process termination) deliberately leaves recoverable staging.
Publication keeps its ownership marker until the caller durably checkpoints the
published report and calls finalize_server_zip_publication.
"""

from __future__ import annotations

import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
import errno
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
from typing import Any
from uuid import uuid4
import zipfile


CHUNK_BYTES = 1024 * 1024
OWNER_MARKER = ".mc-import-owner.json"
STAGING_DIRECTORY = ".import-staging"


class ServerZipImportError(Exception):
    code = "ZIP_INVALID_ARCHIVE"
    default_solution = "Check the archive and import configuration, then retry."

    def __init__(
        self, message: str, *, code: str | None = None, detail: str = "",
        solution: str | None = None, context: Mapping[str, int | float] | None = None,
    ):
        self.code = code or type(self).code
        self.message = str(message)
        self.detail = str(detail or message)
        self.solution = solution or self.default_solution
        self.context = dict(context or {})
        super().__init__(self.message)


class UnsafeArchive(ServerZipImportError):
    code = "ZIP_UNSAFE_MEMBER"
    default_solution = "Rebuild the ZIP with safe relative paths and regular files only."


class ArchiveLimitExceeded(ServerZipImportError):
    code = "ZIP_LIMIT_EXCEEDED"
    default_solution = "Split the archive or ask the administrator to adjust MC_ZIP_* limits."


class ActualSizeExceeded(ArchiveLimitExceeded):
    code = "ZIP_ACTUAL_SIZE_EXCEEDED"
    default_solution = "Rebuild the archive; streamed data exceeded its declared or configured size."


class InsufficientDiskSpace(ServerZipImportError):
    code = "ZIP_DISK_SPACE_INSUFFICIENT"
    default_solution = "Free space on the target disk, select a disk with more space, or import a smaller ZIP."


class TargetDirectoryExists(ServerZipImportError):
    code = "ZIP_TARGET_EXISTS"
    default_solution = "Choose a new target prefix or an empty directory; imports do not merge or overwrite."


class ExtractionCancelled(ServerZipImportError):
    code = "ZIP_CANCELLED"
    default_solution = "Retry the import when ready; incomplete staging for this task has been cleaned."


@dataclass(frozen=True)
class ZipImportLimits:
    max_members: int = 1_000_000
    max_single_bytes: int = 128 * 1024**3
    max_total_bytes: int = 512 * 1024**3
    max_ratio: float = 1000.0
    disk_margin_bytes: int = 1024**3
    disk_margin_ratio: float = 0.05


@dataclass(frozen=True)
class MemberRecord:
    name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ExtractionProgress:
    current_member: str
    extracted_files: int
    extracted_bytes: int
    declared_files: int
    declared_bytes: int
    completed_member: MemberRecord | None = None


@dataclass(frozen=True)
class ExtractionReport:
    task_id: str
    published_prefix: str
    published: bool
    extracted_files: int
    extracted_bytes: int
    members: dict[str, MemberRecord] = field(default_factory=dict)
    marker_pending: bool = True


def read_limits() -> ZipImportLimits:
    defaults = ZipImportLimits()
    values: dict[str, int | float] = {}
    for name in defaults.__dataclass_fields__:
        env_name = f"MC_ZIP_{name.upper()}"
        raw = os.environ.get(env_name)
        default = getattr(defaults, name)
        try:
            value = type(default)(raw) if raw is not None else default
            minimum = 0 if name.startswith("disk_margin_") else 1
            if not math.isfinite(value) or value < minimum:
                raise ValueError("value is outside the allowed range")
            if isinstance(value, int) and value > 2**63 - 1:
                raise ValueError("integer exceeds the supported 64-bit range")
        except (ValueError, TypeError, OverflowError) as error:
            raise ArchiveLimitExceeded(
                "Invalid ZIP import limit configuration", detail=f"{env_name} is not a valid finite limit.",
                solution=f"Set {env_name} to a finite {'non-negative' if name.startswith('disk_margin_') else 'positive'} number.",
            ) from error
        values[name] = value
    return ZipImportLimits(**values)


def required_disk_bytes(
    declared_bytes: int, limits: ZipImportLimits | None = None, *, written_bytes: int = 0,
) -> int:
    """Remaining declared bytes plus the original archive's fixed headroom."""
    limits = limits or read_limits()
    ratio_margin = int((Decimal(declared_bytes) * Decimal(str(limits.disk_margin_ratio))).to_integral_value(rounding=ROUND_CEILING))
    return max(0, declared_bytes - written_bytes) + max(limits.disk_margin_bytes, ratio_margin)


def safe_member_path(name: str) -> PurePosixPath:
    """Normalize both slash styles without accepting POSIX or Windows escapes."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise UnsafeArchive("Empty or NUL-containing member path")
    windows = PureWindowsPath(name)
    posix = PurePosixPath(name.replace("\\", "/"))
    if windows.drive or windows.root or posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise UnsafeArchive("Archive path must remain relative", detail="Drive, absolute, empty and parent-traversal paths are not allowed.")
    for part in posix.parts:
        # Also reject NTFS streams, DOS devices and names which Windows aliases.
        stem = part.split(".", 1)[0].upper()
        reserved = stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved = reserved or (len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789¹²³")
        if ":" in part or part.endswith((".", " ")) or reserved or any(ord(char) < 32 for char in part):
            raise UnsafeArchive("Archive path has an unsafe Windows filename", detail=repr(name))
    return posix


def _error_context(error: BaseException) -> dict[str, int]:
    """Expose only numeric diagnostics; exception text may contain server paths."""
    return {"errno": error.errno} if isinstance(error, OSError) and isinstance(error.errno, int) else {}


def _lstat(path: Path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise UnsafeArchive("Could not inspect an import path", code="ZIP_INVALID_ARCHIVE", context=_error_context(error)) from error


def _is_link_or_reparse(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x0400)


def _plain_info(path: Path):
    info = _lstat(path)
    if info is not None and _is_link_or_reparse(info):
        raise UnsafeArchive("Symbolic links, junctions and reparse points are not allowed")
    return info


def _root_path(root: os.PathLike[str] | str) -> Path:
    path = Path(root).absolute()
    info = _plain_info(path)
    if info is not None and not stat.S_ISDIR(info.st_mode):
        raise UnsafeArchive("Import root must be a directory")
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise UnsafeArchive("Could not resolve the configured import root", context=_error_context(error)) from error


def _under(root: Path, relative: PurePosixPath) -> Path:
    _plain_info(root)
    path = root
    for part in relative.parts:
        path = path / part
        _plain_info(path)
    try:
        path.resolve().relative_to(root)
    except (ValueError, RuntimeError) as error:
        raise UnsafeArchive("Import path escapes its root", detail=relative.as_posix()) from error
    except OSError as error:
        raise UnsafeArchive("Could not resolve an import path", code="ZIP_INVALID_ARCHIVE", detail=relative.as_posix(), context=_error_context(error)) from error
    return path


def _regular_zip(path: Path) -> Path:
    info = _plain_info(path)
    if info is None or not stat.S_ISREG(info.st_mode) or path.suffix.lower() != ".zip":
        raise UnsafeArchive(
            "ZIP source must be an existing regular .zip file", code="ZIP_INVALID_ARCHIVE",
            solution="Place a regular ZIP file in MC_SERVER_IMPORT_DIR and provide its relative path.",
        )
    return path


def resolve_server_zip(allowed_root: os.PathLike[str] | str, relative_zip_path: str) -> Path:
    """Resolve a request path strictly within MC_SERVER_IMPORT_DIR semantics."""
    try:
        relative = safe_member_path(os.fspath(relative_zip_path))
    except (UnsafeArchive, TypeError) as error:
        raise UnsafeArchive(
            "ZIP source must be relative to the allowed import root", code="ZIP_SOURCE_OUTSIDE_IMPORT_ROOT",
            detail="The supplied ZIP path is not a safe relative path.", solution="Use a relative .zip path inside MC_SERVER_IMPORT_DIR.",
        ) from error
    root = _root_path(allowed_root)
    return _regular_zip(_under(root, relative))


def _key(path: PurePosixPath | str) -> str:
    return os.path.normcase(str(path).replace("\\", "/"))


def _inspect_archive(archive: zipfile.ZipFile, limits: ZipImportLimits):
    entries = archive.infolist()
    if len(entries) > limits.max_members:
        raise ArchiveLimitExceeded("ZIP member count exceeds the configured limit", context={"members": len(entries), "max_members": limits.max_members})
    planned: list[tuple[zipfile.ZipInfo, PurePosixPath, bool]] = []
    types: dict[str, bool] = {}
    total = 0
    supported = {zipfile.ZIP_STORED: True, zipfile.ZIP_DEFLATED: zipfile.zlib is not None,
                 zipfile.ZIP_BZIP2: zipfile.bz2 is not None, zipfile.ZIP_LZMA: zipfile.lzma is not None}
    for member in entries:
        # ZipInfo.filename truncates at NUL; orig_filename preserves it.
        path = safe_member_path(member.orig_filename)
        if member.flag_bits & (0x01 | 0x20 | 0x40 | 0x2000) or not supported.get(member.compress_type, False):
            raise UnsafeArchive("Encrypted or unsupported ZIP member", code="ZIP_INVALID_ARCHIVE", detail=member.filename)
        kind = stat.S_IFMT(member.external_attr >> 16)
        directory = member.filename.replace("\\", "/").endswith("/") or kind == stat.S_IFDIR
        if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or member.external_attr & (0x40 | 0x0400):
            raise UnsafeArchive("ZIP contains a link, device or other special member", detail=member.filename)
        if directory and (member.file_size != 0 or kind == stat.S_IFREG):
            raise UnsafeArchive("ZIP directory has inconsistent metadata", detail=member.filename)
        key = _key(path)
        if key == _key(OWNER_MARKER) or key in types:
            raise UnsafeArchive("ZIP has a duplicate or reserved normalized path", detail=member.filename)
        types[key] = directory
        if member.file_size < 0 or member.compress_size < 0:
            raise UnsafeArchive("ZIP has invalid size metadata", code="ZIP_INVALID_ARCHIVE", detail=member.filename)
        if member.file_size > limits.max_single_bytes:
            raise ArchiveLimitExceeded("ZIP member exceeds the single-file limit", detail=member.filename, context={"declared_bytes": member.file_size, "max_single_bytes": limits.max_single_bytes})
        total += member.file_size
        if total > limits.max_total_bytes:
            raise ArchiveLimitExceeded("ZIP exceeds the total uncompressed limit", context={"declared_bytes": total, "max_total_bytes": limits.max_total_bytes})
        if member.file_size > member.compress_size * limits.max_ratio:
            raise ArchiveLimitExceeded("ZIP compression ratio exceeds the limit", detail=member.filename, context={"declared_bytes": member.file_size, "compressed_bytes": member.compress_size, "max_ratio": limits.max_ratio})
        planned.append((member, path, directory))
    for _, path, _ in planned:
        if any(types.get(_key(parent)) is False for parent in path.parents if parent.parts):
            raise UnsafeArchive("ZIP uses a file as another member's parent directory", detail=str(path))
    return planned, total


def _nearest_existing(path: Path) -> Path:
    while _plain_info(path) is None:
        path = path.parent
    return path


def _disk_error(root: Path, declared: int, written: int, limits: ZipImportLimits, *, free: int | None = None):
    if free is None:
        try:
            free = shutil.disk_usage(_nearest_existing(root)).free
        except OSError:
            free = -1
    required = required_disk_bytes(declared, limits, written_bytes=written)
    return InsufficientDiskSpace(
        "Insufficient free space for ZIP extraction",
        detail=f"Free: {free} bytes; required: {required} bytes; written: {written} bytes.",
        context={"free_bytes": free, "required_bytes": required, "written_bytes": written},
    )


def _check_disk(root: Path, declared: int, written: int, limits: ZipImportLimits):
    free = shutil.disk_usage(_nearest_existing(root)).free
    if free < required_disk_bytes(declared, limits, written_bytes=written):
        raise _disk_error(root, declared, written, limits, free=free)


def _tree(path: Path):
    """Inspect without following link-like entries, including Windows reparse points."""
    info = _plain_info(path)
    if info is None:
        return
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafeArchive("Staging or target must be a directory")
    with os.scandir(path) as entries:
        children = [Path(entry.path) for entry in entries]
    for child in children:
        info = _plain_info(child)
        if info is None:
            raise UnsafeArchive("Import directory changed during inspection")
        directory = stat.S_ISDIR(info.st_mode)
        if not directory and not stat.S_ISREG(info.st_mode):
            raise UnsafeArchive("Import directory contains a special file")
        yield child, directory
        if directory:
            yield from _tree(child)


def _mkdir_under(root: Path, relative: PurePosixPath) -> Path:
    path = root
    for part in relative.parts:
        path = _under(root, PurePosixPath(*(path / part).relative_to(root).parts))
        path.mkdir(mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(_plain_info(path).st_mode):
            raise UnsafeArchive("Import path is not a directory", detail=relative.as_posix())
    return path


def _cleanup_task(root: Path, task_id: str):
    """The only recursive deletion is the validated, exact task directory."""
    staging = _under(root, PurePosixPath(STAGING_DIRECTORY))
    task = _under(root, PurePosixPath(STAGING_DIRECTORY, task_id))
    if _plain_info(task) is None:
        return
    if task.resolve().relative_to(staging.resolve()).parts != (task_id,):
        raise UnsafeArchive("Refusing to clean a staging directory outside this task")
    # Refuse cleanup when a link/reparse point could redirect any traversal.
    for _ in _tree(task):
        pass
    shutil.rmtree(task)


def _expected_paths(planned):
    files = {_key(path) for _, path, directory in planned if not directory}
    directories = {_key(path) for _, path, directory in planned if directory}
    for _, path, _ in planned:
        directories.update(_key(parent) for parent in path.parents if parent.parts)
    return files, directories


def _owner_matches(directory: Path, task_id: str) -> bool:
    marker = directory / OWNER_MARKER
    info = _plain_info(marker)
    if info is None or not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        return False
    try:
        with marker.open("r", encoding="utf-8") as stream:
            owner = json.loads(stream.read(4097))
        return isinstance(owner, dict) and owner.get("task_id") == task_id
    except ValueError:
        return False
    except OSError as error:
        raise UnsafeArchive("Could not read the publication ownership marker", code="ZIP_INVALID_ARCHIVE", context=_error_context(error)) from error


def _prepare_payload(payload: Path, task_id: str, planned):
    files, directories = _expected_paths(planned)
    for path, directory in _tree(payload):
        relative = PurePosixPath(*path.relative_to(payload).parts)
        key = _key(relative)
        if directory and key in directories:
            continue
        if not directory and key in files:
            continue
        if not directory and key == _key(OWNER_MARKER) and _owner_matches(payload, task_id):
            path.unlink()
        elif not directory and path.name.startswith(".part-") and path.name.endswith(".tmp"):
            path.unlink()
        else:
            raise UnsafeArchive("Staging contains files not present in this archive", detail=str(relative))


def _verified_record(path: Path, member: zipfile.ZipInfo, name: str, candidate: Any) -> MemberRecord | None:
    if isinstance(candidate, MemberRecord):
        candidate = {"name": candidate.name, "size_bytes": candidate.size_bytes, "sha256": candidate.sha256}
    if not isinstance(candidate, Mapping):
        return None
    size, digest = candidate.get("size_bytes"), candidate.get("sha256")
    if candidate.get("name") != name or type(size) is not int or size != member.file_size:
        return None
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        return None
    info = _plain_info(path)
    if info is None or not stat.S_ISREG(info.st_mode) or info.st_size != size:
        return None
    actual = 0
    sha = hashlib.sha256()
    crc = 0
    with path.open("rb") as stream:
        while chunk := stream.read(min(CHUNK_BYTES, size - actual + 1)):
            actual += len(chunk)
            if actual > size:
                return None
            sha.update(chunk)
            crc = binascii.crc32(chunk, crc)
    if actual != size or sha.hexdigest() != digest.lower() or crc != member.CRC:
        return None
    return MemberRecord(name, actual, sha.hexdigest())


def _recover_published(target: Path, task_id: str, prefix: str, planned, completed):
    info = _plain_info(target)
    if info is None:
        return None
    if not stat.S_ISDIR(info.st_mode):
        raise TargetDirectoryExists("Target prefix already exists", detail=prefix)
    if not any(target.iterdir()):
        return None
    error = TargetDirectoryExists("Target directory is not empty", detail=prefix)
    if completed is None or not _owner_matches(target, task_id):
        raise error
    files, directories = _expected_paths(planned)
    for path, directory in _tree(target):
        key = _key(PurePosixPath(*path.relative_to(target).parts))
        if key not in (directories if directory else files | {_key(OWNER_MARKER)}):
            raise error
    records = {}
    for member, path, directory in planned:
        if not directory:
            name = path.as_posix()
            verified = _verified_record(_under(target, path), member, name, completed.get(name))
            if verified is None:
                raise error
            records[name] = verified
    return ExtractionReport(task_id, prefix, True, len(records), sum(item.size_bytes for item in records.values()), records)


def _emit(callback, progress: ExtractionProgress):
    if callback is None:
        return
    try:
        if callback(progress) is False:
            raise ExtractionCancelled("ZIP import was cancelled")
    except ExtractionCancelled as error:
        raise ExtractionCancelled("ZIP import was cancelled") from error
    except Exception as error:
        raise ExtractionCancelled("ZIP progress callback failed", detail="The progress callback could not complete.", context=_error_context(error)) from error


def _write_owner(payload: Path, task_id: str):
    temporary = payload / f".part-{uuid4().hex}.tmp"
    with temporary.open("xb") as stream:
        stream.write(json.dumps({"task_id": task_id}, ensure_ascii=True).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, payload / OWNER_MARKER)


def _publication_target(target_root, target_prefix: str, task_id: str):
    prefix = safe_member_path(target_prefix)
    task = safe_member_path(task_id)
    if len(task.parts) != 1 or task.as_posix() != task_id:
        raise UnsafeArchive("task_id must be one safe path component")
    if _key(prefix.parts[0]) == _key(STAGING_DIRECTORY):
        raise UnsafeArchive("Target prefix cannot overlap the import staging directory")
    root = _root_path(target_root)
    return root, _under(root, prefix), prefix


def _fsync_directory(path: Path):
    # The Windows CRT cannot open directory descriptors for os.fsync.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}:
                raise
    finally:
        os.close(descriptor)


def finalize_server_zip_publication(
    target_root: os.PathLike[str] | str, target_prefix: str, *, task_id: str,
) -> bool:
    """Remove only this task's owner marker after a durable published checkpoint.

    Returns True when the marker was removed, or False if an existing valid
    target already has no marker. A missing target or mismatched owner fails.
    The caller must checkpoint publication before invoking this function.
    """
    try:
        _, target, prefix = _publication_target(target_root, target_prefix, task_id)
        info = _plain_info(target)
        if info is None or not stat.S_ISDIR(info.st_mode):
            raise UnsafeArchive("Published target must be an existing directory", code="ZIP_INVALID_ARCHIVE", detail=prefix.as_posix())
        marker = target / OWNER_MARKER
        if _plain_info(marker) is None:
            _fsync_directory(target)
            return False
        if not _owner_matches(target, task_id):
            raise TargetDirectoryExists("Publication owner does not match this task", detail=prefix.as_posix())
        marker.unlink()
        _fsync_directory(target)
        return True
    except ServerZipImportError:
        raise
    except OSError as error:
        raise UnsafeArchive("Could not finalize ZIP publication", code="ZIP_INVALID_ARCHIVE", context=_error_context(error)) from error


def extract_server_zip(
    archive_path: os.PathLike[str] | str, target_root: os.PathLike[str] | str, target_prefix: str, *,
    task_id: str, completed: Mapping[str, MemberRecord | Mapping[str, Any]] | None = None,
    on_progress: Callable[[ExtractionProgress], object] | None = None,
) -> ExtractionReport:
    """Validate completely, stream into this task's payload, then publish atomically.

    ``completed`` is a persisted mapping of normalized names to MemberRecord (or
    its dataclasses.asdict representation). Every candidate is checked against
    the current file's size, SHA-256 and archive CRC before skipping a read.
    A published report has marker_pending=True. Persist the published checkpoint
    before calling finalize_server_zip_publication; extraction never removes it.
    """
    limits = read_limits()
    root, target, prefix = _publication_target(target_root, target_prefix, task_id)
    task_dir = _under(root, PurePosixPath(STAGING_DIRECTORY, task_id))
    payload = _under(root, PurePosixPath(STAGING_DIRECTORY, task_id, "payload"))
    source = _regular_zip(Path(archive_path).absolute())
    if completed is not None and not isinstance(completed, Mapping):
        raise UnsafeArchive("Completed member metadata must be a mapping")
    owns_staging = False
    declared = written = extracted_files = 0
    try:
        with zipfile.ZipFile(source, "r") as archive:
            planned, declared = _inspect_archive(archive, limits)
            declared_files = sum(not directory for _, _, directory in planned)
            recovered = _recover_published(target, task_id, prefix.as_posix(), planned, completed)
            if recovered is not None:
                _cleanup_task(root, task_id)
                return recovered
            # Inspect existing staging before acquiring it; never follow a link
            # even when attempting failure cleanup.
            for _ in _tree(task_dir):
                pass
            if _nearest_existing(root).stat().st_dev != _nearest_existing(target.parent).stat().st_dev:
                raise UnsafeArchive("Staging and target must be on the same filesystem")
            _check_disk(root, declared, 0, limits)
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            _mkdir_under(root, PurePosixPath(STAGING_DIRECTORY, task_id))
            owns_staging = True
            _mkdir_under(root, PurePosixPath(STAGING_DIRECTORY, task_id, "payload"))
            _prepare_payload(payload, task_id, planned)
            records: dict[str, MemberRecord] = {}
            for member, relative, directory in planned:
                name = relative.as_posix()
                if directory:
                    _mkdir_under(payload, relative)
                    continue
                _mkdir_under(payload, relative.parent)
                destination = _under(payload, relative)
                verified = _verified_record(destination, member, name, (completed or {}).get(name))
                if verified is None:
                    temporary = destination.with_name(f".part-{uuid4().hex}.tmp")
                    actual = 0
                    digest = hashlib.sha256()
                    with archive.open(member, "r") as reader, temporary.open("xb") as writer:
                        while chunk := reader.read(CHUNK_BYTES):
                            next_actual, next_written = actual + len(chunk), written + len(chunk)
                            if next_actual > min(member.file_size, limits.max_single_bytes) or next_written > min(declared, limits.max_total_bytes):
                                raise ActualSizeExceeded(
                                    "Streamed ZIP data exceeds its size ceiling", detail=name,
                                    context={"member_bytes": next_actual, "member_declared_bytes": member.file_size,
                                             "actual_bytes": next_written, "declared_bytes": declared,
                                             "max_single_bytes": limits.max_single_bytes, "max_total_bytes": limits.max_total_bytes,
                                             "written_bytes": written},
                                )
                            # Recheck every chunk, including remaining data and
                            # fixed safety headroom, rather than only at start.
                            _check_disk(root, declared, written, limits)
                            writer.write(chunk)
                            digest.update(chunk)
                            actual, written = next_actual, next_written
                            _emit(on_progress, ExtractionProgress(name, extracted_files, written, declared_files, declared))
                        if actual != member.file_size:
                            raise UnsafeArchive("ZIP member ended before its declared size", code="ZIP_INVALID_ARCHIVE", detail=name)
                        writer.flush()
                        os.fsync(writer.fileno())
                    # Reading to EOF above also lets ZipExtFile validate CRC.
                    os.replace(temporary, destination)
                    verified = MemberRecord(name, actual, digest.hexdigest())
                else:
                    written += verified.size_bytes
                records[name] = verified
                extracted_files += 1
                _emit(on_progress, ExtractionProgress(name, extracted_files, written, declared_files, declared, verified))
            _check_disk(root, declared, written, limits)
            _write_owner(payload, task_id)
            # Resolve and inspect again immediately before the single directory
            # rename. rmdir can remove only an empty pre-existing target.
            target = _under(root, prefix)
            info = _plain_info(target)
            if info is not None:
                if not stat.S_ISDIR(info.st_mode) or any(target.iterdir()):
                    raise TargetDirectoryExists("Target directory appeared or became nonempty during extraction", detail=prefix.as_posix())
                target.rmdir()
            _mkdir_under(root, prefix.parent)
            if payload.stat().st_dev != target.parent.stat().st_dev:
                raise UnsafeArchive("Staging and target must be on the same filesystem")
            os.replace(payload, target)
            _fsync_directory(target)
            _fsync_directory(target.parent)
            _cleanup_task(root, task_id)
            return ExtractionReport(task_id, prefix.as_posix(), True, extracted_files, written, records)
    except (Exception, KeyboardInterrupt) as error:
        if owns_staging:
            try:
                _cleanup_task(root, task_id)
            except (OSError, ServerZipImportError):
                if hasattr(error, "add_note"):
                    error.add_note("Task staging cleanup was refused or failed; the task directory was left in place.")
        if isinstance(error, ServerZipImportError):
            raise
        if isinstance(error, KeyboardInterrupt):
            raise ExtractionCancelled("ZIP import was interrupted") from error
        if isinstance(error, OSError) and error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}:
            raise _disk_error(root, declared, written, limits) from error
        raise UnsafeArchive("ZIP import failed", code="ZIP_INVALID_ARCHIVE", detail="Could not read, verify, or publish the ZIP archive.", context=_error_context(error)) from error
