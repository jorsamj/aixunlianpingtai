"""2C-02: official, immutable PT source preflight without pickle deserialization.

Reuse the EXISTING mother-model SHA256 pinned release table, not a new model
asset registry. This is only an exact-allowlist admission: platform-created
trained PT, model registry flags, database records and arbitrary downloaded
checkpoints are NOT trusted by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import os
import stat

from .mother_model_assets import _OFFICIAL_YOLO11_DETECT, _check_torch_container
from .os_supervisor_authorization import GrantRejected

_ORIGIN = "ultralytics-assets-v8.4.0-pinned-sha256"


def _hold(code: str) -> None:
    raise GrantRejected("PT_OFFICIAL_SOURCE_" + code + "_HOLD")


@dataclass(frozen=True, slots=True)
class VerifiedPinnedOfficialPt:
    source_name: str
    source_sha256: str
    size_bytes: int
    origin: str = _ORIGIN
    # Metadata never conveys independent execution authority.
    launch_authorized: bool = False
    result_publish_allowed: bool = False
    trusted_stop_receipt_available: bool = False


def pinned_official_pt_binding(
    *, source_name: object, source_sha256: object, source_size_bytes: object,
) -> VerifiedPinnedOfficialPt:
    """Check CENTRAL frozen source tuple against our compiled official pin.

    Filename-only, self-declared source_trace, database VERIFIED and a
    caller-provided sha256 are insufficient: expected bytes must equal the
    compiled release pin, which is NOT writable by the caller.
    """
    if (type(source_name) is not str
            or type(source_sha256) is not str
            or type(source_size_bytes) is not int):
        _hold("METADATA_SCHEMA_INVALID")
    pin = _OFFICIAL_YOLO11_DETECT.get(source_name)
    if (pin is None or not hmac.compare_digest(source_sha256, pin[1])
            or source_size_bytes != pin[0]):
        _hold("NOT_PINNED_RELEASE")
    return VerifiedPinnedOfficialPt(source_name, pin[1], pin[0])


def verify_local_pinned_official_pt(
    path: Path, *, source_name: object, source_sha256: object,
    source_size_bytes: object,
) -> VerifiedPinnedOfficialPt:
    """Read-only, exact-size digest + safe container check. NO torch.load().

    This deliberately accepts a temporary downloaded cache: its bytes are
    independently checked against an immutable code pin before being frozen
    into the root-owned work directory. No path in this function runs code.
    """
    pinned = pinned_official_pt_binding(
        source_name=source_name, source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
    )
    if not isinstance(path, Path) or path.name != pinned.source_name:
        _hold("SOURCE_PATH_OR_NAME_INVALID")
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode)
                or info.st_size != pinned.size_bytes
                or info.st_nlink != 1):
            _hold("SOURCE_FILE_NOT_REGULAR_UNIQUE")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags)
        try:
            actual = os.fstat(fd)
            if (not stat.S_ISREG(actual.st_mode)
                    or (actual.st_dev, actual.st_ino, actual.st_size)
                    != (info.st_dev, info.st_ino, info.st_size)
                    or actual.st_nlink != 1):
                _hold("SOURCE_FILE_REPLACED")
            sha = hashlib.sha256()
            count = 0
            while part := os.read(fd, 1024 * 1024):
                count += len(part)
                if count > pinned.size_bytes:
                    _hold("SOURCE_EXCEEDS_PIN")
                sha.update(part)
            after = os.fstat(fd)
            if ((after.st_dev, after.st_ino, after.st_size,
                 after.st_mtime_ns, after.st_ctime_ns)
                != (actual.st_dev, actual.st_ino, actual.st_size,
                    actual.st_mtime_ns, actual.st_ctime_ns)):
                _hold("SOURCE_MUTATED_DURING_READ")
        finally:
            os.close(fd)
        if (count != pinned.size_bytes
                or not hmac.compare_digest(sha.hexdigest(), pinned.source_sha256)):
            _hold("SOURCE_SHA256_MISMATCH")
        valid, _ = _check_torch_container(path)
        if not valid:
            _hold("TORCH_ARCHIVE_STRUCTURE_INVALID")
    except GrantRejected:
        raise
    except (OSError, ValueError) as exc:
        raise GrantRejected("PT_OFFICIAL_SOURCE_IO_UNVERIFIED_HOLD") from exc
    return pinned
