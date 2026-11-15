"""OS-owned pinning of Supervisor public key and control-plane private signer.

No path is accepted from Agent requests. Files are never created by runtime.
Exact owner/mode + O_NOFOLLOW on the opened fd protect key provenance.
These loaders are inert until an explicitly opted-in CPU trial is configured.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

from .os_supervisor_authorization import GrantRejected

SUPERVISOR_KEY_PATH = Path("/etc/changlian-os-supervisor/issuer.ed25519.pub")
CONTROL_KEY_PATH = Path("/etc/changlian-control/supervisor-cpu-issuer.ed25519.key")


def _read_pinned_key(path: Path, *, required_owner: int) -> bytes:
    """Read raw 32-byte Ed25519 key without following symlink indirections."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise GrantRejected("SUPERVISOR_KEY_OS_UNAVAILABLE_HOLD")
    try:
        directory = path.parent.lstat()
        if (not stat.S_ISDIR(directory.st_mode)
                or path.parent.is_symlink()
                or directory.st_uid != required_owner
                or stat.S_IMODE(directory.st_mode) != 0o700):
            raise GrantRejected("SUPERVISOR_KEY_DIRECTORY_UNTRUSTED_HOLD")
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode)
                    or info.st_uid != required_owner
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise GrantRejected("SUPERVISOR_KEY_FILE_UNTRUSTED_HOLD")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                key = stream.read(33)
            if len(key) != 32:
                raise GrantRejected("SUPERVISOR_KEY_LENGTH_INVALID_HOLD")
            return key
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        raise GrantRejected("SUPERVISOR_KEY_UNAVAILABLE_HOLD") from exc


def load_supervisor_public_key() -> Ed25519PublicKey:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise GrantRejected("SUPERVISOR_KEY_ROOT_REQUIRED_HOLD")
    return Ed25519PublicKey.from_public_bytes(
        _read_pinned_key(SUPERVISOR_KEY_PATH, required_owner=0))


def load_control_issuer_private_key() -> Ed25519PrivateKey:
    if not hasattr(os, "geteuid"):
        raise GrantRejected("CENTRAL_KEY_RUNTIME_UNTRUSTED_HOLD")
    return Ed25519PrivateKey.from_private_bytes(
        _read_pinned_key(CONTROL_KEY_PATH, required_owner=os.geteuid()))
