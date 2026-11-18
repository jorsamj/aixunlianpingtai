"""Immutable Payload files and proposals; deliberately no Task database access.

Cooperative application boundary, not protection against arbitrary same-user
filesystem writes. Windows supports process-crash recovery, not a promise of
cross-filesystem/SQLite power-loss atomicity.
"""
from __future__ import annotations

import hashlib
import errno
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping

from .models import TaskKind, TaskRecord

PROTOCOL = "task-payload-publication-v1"
DEFAULT_MAX_PAYLOAD_BYTES = 64 * 1024 * 1024
RESERVED_NAMES = frozenset({"payload-versions", "payload-publications", ".payload-staging-v1"})
HEX = r"[0-9a-f]{64}"
VERSION_REF = re.compile(rf"(?P<prefix>scenario/)?payload-versions/v1/(?P<operation>{HEX})/sha256-(?P<digest>{HEX})\.json\Z")
PHASE_KINDS = {"training.freeze": "TRAINING", "training.ready": "TRAINING", "deployment.ready": "DEPLOYMENT_TEST"}


class PayloadPublicationError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _fail(code: str, detail: str):
    raise PayloadPublicationError(code, detail)


def _json_bytes(value: Any) -> bytes:
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                _fail("PUBLICATION_INVALID_JSON", "JSON keys must be strings")
            for child in item.values():
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)
    try:
        check(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        _fail("PUBLICATION_INVALID_JSON", str(error))


def _safe_relative(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        _fail("PAYLOAD_INVALID_REF", "reference must be text")
    parts = value.split("/")
    if not value or PureWindowsPath(value).drive or any(
        not part or part in {".", ".."} or part.endswith((".", " "))
        or any(char in part for char in '\\:<>"|?*\x00')
        or any(ord(char) < 32 for char in part)
        or PureWindowsPath(part).is_reserved() for part in parts
    ):
        _fail("PAYLOAD_INVALID_REF", "safe relative path required")
    return tuple(parts)


def is_reserved_path(parts) -> bool:
    return any(str(part).casefold() in RESERVED_NAMES for part in parts)


def _native_name(path: Path):
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        return "\\\\?\\" + str(path)
    return path


@dataclass(frozen=True, init=False)
class PayloadPublicationIdentity:
    """Detached canonical business intent; execution tokens are never stored."""
    canonical: bytes

    def __init__(self, *, task_id: str, project_id: str, kind: str, phase: str,
                 expected_ref: str, expected_parent_attempt: int, intent: Mapping[str, Any]):
        if len(_safe_relative(task_id)) != 1:
            _fail("PUBLICATION_INVALID_IDENTITY", "task_id must be one component")
        if not isinstance(project_id, str) or not project_id or not isinstance(intent, dict):
            _fail("PUBLICATION_INVALID_IDENTITY", "project and intent required")
        if kind not in {item.value for item in TaskKind} or (phase != "create" and PHASE_KINDS.get(phase) != kind):
            _fail("PUBLICATION_INVALID_IDENTITY", "kind/phase mismatch")
        if type(expected_parent_attempt) is not int or expected_parent_attempt < 0:
            _fail("PUBLICATION_INVALID_IDENTITY", "nonnegative parent attempt required")
        if phase == "create":
            if expected_ref != "":
                _fail("PUBLICATION_INVALID_IDENTITY", "create cannot replace an existing reference")
        else:
            _safe_relative(expected_ref)
        object.__setattr__(self, "canonical", _json_bytes(dict(
            protocol=PROTOCOL, task_id=task_id, project_id=project_id, parent_kind=kind,
            phase=phase, expected_payload_ref=expected_ref,
            expected_parent_attempt=expected_parent_attempt, intent=intent)))

    @property
    def data(self) -> dict:
        return json.loads(self.canonical)

    @property
    def operation_id(self) -> str:
        return hashlib.sha256(self.canonical).hexdigest()

    @property
    def task_id(self) -> str:
        return self.data["task_id"]

    @property
    def prefix(self) -> str:
        return "scenario/" if self.data["parent_kind"] == "DEPLOYMENT_TEST" else ""


def _activation(value, phase: str) -> dict:
    value = {} if value is None else value
    if not isinstance(value, dict) or value.keys() - {"resource_key", "required_capabilities", "stage"}:
        _fail("PUBLICATION_INVALID_ACTIVATION", "only resource_key/capabilities/stage may be proposed")
    if value and phase not in {"training.ready", "deployment.ready"}:
        _fail("PUBLICATION_INVALID_ACTIVATION", "only READY can propose activation fields")
    for key in ("resource_key", "stage"):
        if key in value and (not isinstance(value[key], str) or not value[key]):
            _fail("PUBLICATION_INVALID_ACTIVATION", f"invalid {key}")
    if "required_capabilities" in value and (
        not isinstance(value["required_capabilities"], (list, tuple))
        or any(not isinstance(item, str) or not item for item in value["required_capabilities"])
    ):
        _fail("PUBLICATION_INVALID_ACTIVATION", "invalid capabilities")
    return json.loads(_json_bytes(value))


@dataclass(frozen=True)
class VerifiedPayload:
    task_id: str
    payload_ref: str
    raw: bytes

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def data(self) -> Any:
        return json.loads(self.raw)


@dataclass(frozen=True)
class PreparedPayloadPublication:
    identity: PayloadPublicationIdentity
    version: VerifiedPayload
    receipt_bytes: bytes

    @property
    def operation_id(self) -> str:
        return self.identity.operation_id

    @property
    def metadata(self) -> dict:
        return json.loads(self.receipt_bytes)


@dataclass(frozen=True)
class PayloadPublicationResult:
    """Returned only after the Repository transaction commits successfully."""
    outcome: str
    task: TaskRecord
    operation_id: str


class PayloadVersionStore:
    def __init__(self, root: Path, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
                 max_receipt_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES):
        if type(max_payload_bytes) is not int or max_payload_bytes < 1:
            raise ValueError("max_payload_bytes must be positive")
        if type(max_receipt_bytes) is not int or max_receipt_bytes < 1:
            raise ValueError("max_receipt_bytes must be positive")
        self.root = root
        self.limit = max_payload_bytes
        self.receipt_limit = max_receipt_bytes

    def _check_backend(self):
        """Admit known local backends only; hard-link failures still fail closed."""
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            volume_path = kernel.GetVolumePathNameW
            volume_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            volume_path.restype = wintypes.BOOL
            drive_type = kernel.GetDriveTypeW
            drive_type.argtypes = [wintypes.LPCWSTR]
            drive_type.restype = wintypes.UINT
            volume_info = kernel.GetVolumeInformationW
            volume_info.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                    ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
            volume_info.restype = wintypes.BOOL
            volume = ctypes.create_unicode_buffer(32768)
            filesystem = ctypes.create_unicode_buffer(128)
            supported = (volume_path(str(self.root), volume, len(volume))
                         and drive_type(volume.value) == 3  # DRIVE_FIXED; no SMB/removable media
                         and volume_info(volume.value, None, 0, None, None, None, filesystem, len(filesystem))
                         and filesystem.value == "NTFS")
        elif sys.platform.startswith("linux"):
            try:
                mounts = []
                for line in Path("/proc/self/mountinfo").read_text().splitlines():
                    left, right = line.split(" - ", 1)
                    mount = Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), left.split()[4]))
                    if mount == self.root or mount in self.root.parents:
                        mounts.append((len(mount.parts), right.split()[0]))
                filesystem = max(mounts)[1] if mounts else "unknown"
                # tmpfs is process-crash only; overlay durability depends on its
                # backing store. Neither implies a power-loss guarantee.
                supported = filesystem in {"ext2", "ext3", "ext4", "xfs", "btrfs", "tmpfs", "overlay"}
            except (OSError, ValueError, IndexError):
                supported = False
        else:
            supported = False
        if not supported:
            _fail("PAYLOAD_PUBLICATION_BACKEND_UNSUPPORTED", "requires supported local Linux filesystem or fixed NTFS volume")

    def _path(self, task_id: str, ref: str) -> Path:
        if len(_safe_relative(task_id)) != 1:
            _fail("PAYLOAD_UNSAFE_PATH", "task id must be one component")
        path = self.root
        for part in (task_id, *_safe_relative(ref)):
            path = path / part
            try:
                info = os.lstat(_native_name(path))
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                _fail("PAYLOAD_UNSAFE_PATH", "symlink/reparse point in version path")
        return path

    def _mkdir(self, task_id: str, ref: str) -> Path:
        # Validate before and after mkdir; same-user adversarial rename races are
        # outside this cooperative protocol (no claim of OS permission isolation).
        target = self._path(task_id, ref)
        Path(_native_name(target)).mkdir(parents=True, exist_ok=True)
        self._path(task_id, ref)
        return target

    def _read(self, path: Path, *, limit=None) -> bytes:
        limit = self.limit if limit is None else limit
        try:
            if not stat.S_ISREG(os.lstat(_native_name(path)).st_mode):
                _fail("PAYLOAD_UNSAFE_PATH", "ordinary file required")
            descriptor = os.open(_native_name(path), os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    _fail("PAYLOAD_UNSAFE_PATH", "ordinary file required")
                raw = stream.read(limit + 1)
        except FileNotFoundError:
            _fail("PAYLOAD_VERSION_MISSING", str(path.name))
        except OSError as error:
            _fail("PAYLOAD_READ_FAILED", str(error))
        if len(raw) > limit:
            _fail("PAYLOAD_SIZE_LIMIT", f"configured limit is {limit} bytes")
        return raw

    @staticmethod
    def _sync_directory(path: Path):
        if os.name != "posix":
            return  # Windows: no portable directory fsync/power-loss promise.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _publish(self, task_id: str, ref: str, raw: bytes, before_publish: Callable[[], None], *, limit=None):
        limit = self.limit if limit is None else limit
        if len(raw) > limit:
            _fail("PAYLOAD_SIZE_LIMIT", f"configured limit is {limit} bytes")
        self._check_backend()
        name = None
        try:
            path = self._path(task_id, ref)
            parent_ref = ref.rsplit("/", 1)[0]
            self._mkdir(task_id, parent_ref)
            staging = self._mkdir(task_id, ".payload-staging-v1")
            descriptor, name = tempfile.mkstemp(dir=_native_name(staging), prefix="proposal-", suffix=".tmp")
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temp = Path(name)
            if self._read(temp, limit=limit) != raw:
                _fail("PAYLOAD_INTEGRITY_ERROR", "private write verification failed")
            before_publish()
            self._path(task_id, ref)
            try:
                # CreateHardLinkW still needs extended-length names even when
                # Python open/mkdir already accept the long version path.
                os.link(_native_name(temp), _native_name(path))  # no replace; no fallback
            except FileExistsError:
                if self._read(path, limit=limit) != raw:
                    _fail("PUBLICATION_OPERATION_CONFLICT", "immutable destination already has different bytes")
            # Re-sync on idempotent retry as a previous directory fsync may fail.
            current = path.parent
            while True:
                self._sync_directory(current)
                if current == self.root:
                    self._sync_directory(current.parent)
                    break
                current = current.parent
        except OSError as error:
            unsupported = error.errno in {errno.EXDEV, errno.ENOTSUP, errno.ENOSYS} or getattr(error, "winerror", None) in {1, 17, 50}
            _fail("PAYLOAD_PUBLICATION_BACKEND_UNSUPPORTED" if unsupported else "PAYLOAD_PUBLICATION_IO_ERROR", str(error))
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)

    def read_payload_version(self, task_id: str, payload_ref: str) -> VerifiedPayload:
        match = VERSION_REF.fullmatch(payload_ref) if isinstance(payload_ref, str) else None
        if match is None:
            _fail("PAYLOAD_INVALID_REF", "v1 digest-bound reference required")
        raw = self._read(self._path(task_id, payload_ref))
        if hashlib.sha256(raw).hexdigest() != match["digest"]:
            _fail("PAYLOAD_INTEGRITY_ERROR", "bytes do not match reference digest")
        try:
            # Reject nonfinite numbers too, even for out-of-protocol hash refs.
            data = json.loads(raw)
            _json_bytes(data)
        except (ValueError, UnicodeError, RecursionError) as error:
            _fail("PAYLOAD_INTEGRITY_ERROR", str(error))
        return VerifiedPayload(task_id, payload_ref, raw)

    def read_payload_publication_receipt(self, task_id: str, operation_id: str, *, identity=None) -> PreparedPayloadPublication:
        if not isinstance(operation_id, str) or re.fullmatch(HEX, operation_id) is None:
            _fail("PUBLICATION_INVALID_IDENTITY", "invalid operation id")
        # The domain is known from the supplied identity, otherwise discover the
        # two fixed locations; ambiguous receipts are rejected, never guessed.
        prefixes = [identity.prefix] if identity is not None else ["", "scenario/"]
        found = []
        for prefix in prefixes:
            path = self._path(task_id, f"{prefix}payload-publications/v1/{operation_id}.json")
            if os.path.lexists(_native_name(path)):
                found.append((prefix, self._read(path, limit=self.receipt_limit)))
        if len(found) != 1:
            _fail("PAYLOAD_VERSION_MISSING" if not found else "PUBLICATION_INVALID_RECEIPT", "expected one immutable receipt")
        prefix, raw = found[0]
        try:
            receipt = json.loads(raw)
            if not isinstance(receipt, dict) or set(receipt) != {"identity", "operation_id", "new_ref", "digest", "size", "activation"}:
                raise ValueError("receipt fields")
            fields = dict(receipt["identity"])
            if fields.pop("protocol") != PROTOCOL:
                raise ValueError("protocol")
            actual = PayloadPublicationIdentity(
                task_id=fields.pop("task_id"), project_id=fields.pop("project_id"),
                kind=fields.pop("parent_kind"), phase=fields.pop("phase"),
                expected_ref=fields.pop("expected_payload_ref"),
                expected_parent_attempt=fields.pop("expected_parent_attempt"), intent=fields.pop("intent"))
            if fields or actual.task_id != task_id or actual.prefix != prefix or actual.operation_id != operation_id or receipt["operation_id"] != operation_id:
                raise ValueError("identity binding")
            if identity is not None and actual != identity:
                _fail("PUBLICATION_IDENTITY_MISMATCH", "receipt does not match requested business intent")
            activation = _activation(receipt["activation"], actual.data["phase"])
            match = VERSION_REF.fullmatch(receipt["new_ref"])
            if match is None or match["operation"] != operation_id or (match["prefix"] or "") != prefix or match["digest"] != receipt["digest"]:
                raise ValueError("version binding")
            if type(receipt["size"]) is not int or receipt["size"] < 0 or _json_bytes(receipt) != raw or activation != receipt["activation"]:
                raise ValueError("noncanonical receipt")
        except PayloadPublicationError:
            raise
        except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as error:
            _fail("PUBLICATION_INVALID_RECEIPT", str(error))
        version = self.read_payload_version(task_id, receipt["new_ref"])
        if len(version.raw) != receipt["size"]:
            _fail("PAYLOAD_INTEGRITY_ERROR", "receipt size mismatch")
        return PreparedPayloadPublication(actual, version, raw)

    def prepare_payload_publication(self, identity: PayloadPublicationIdentity, payload: Any, *, activation=None, before_publish=lambda: None) -> PreparedPayloadPublication:
        if not isinstance(identity, PayloadPublicationIdentity):
            _fail("PUBLICATION_INVALID_IDENTITY", "typed identity required")
        raw = _json_bytes(payload)
        digest = hashlib.sha256(raw).hexdigest()
        operation_id = identity.operation_id
        ref = f"{identity.prefix}payload-versions/v1/{operation_id}/sha256-{digest}.json"
        activation = _activation(activation, identity.data["phase"])
        receipt = _json_bytes(dict(identity=identity.data, operation_id=operation_id, new_ref=ref,
                                   digest=digest, size=len(raw), activation=activation))
        if len(raw) > self.limit or len(receipt) > self.receipt_limit:
            _fail("PAYLOAD_SIZE_LIMIT", "payload or receipt exceeds its configured byte limit")
        self._publish(identity.task_id, ref, raw, before_publish)
        self._publish(identity.task_id, f"{identity.prefix}payload-publications/v1/{operation_id}.json", receipt, before_publish, limit=self.receipt_limit)
        result = self.read_payload_publication_receipt(identity.task_id, operation_id, identity=identity)
        before_publish()
        return result
