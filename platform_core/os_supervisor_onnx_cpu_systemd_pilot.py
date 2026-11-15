"""Isolated CI-only root-owned ONNX bytes + fixed systemd CPU read proof.

NOT called by SupervisorService/Node Agent. No signed grant, business Runner,
central lease recheck, result publication, GPU assurance or StopReceipt.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_cpu_systemd import FixedCpuSystemd
from .os_supervisor_onnx_cpu_pilot import CpuOnnxPilotPreflight, _reject_external_data

_ROOT = Path("/run")
_PREFIX = "changlian-os-onnx-pilot-"
_HANDLE = re.compile(r"[0-9a-f]{32}\Z")
# Fixed stdlib workload reads a *real* validated ONNX model, checks its hash.
# It does not execute the graph; full ONNX Runtime already has a separate E2E.
_WORKER = (
    "import hashlib,json,sys,time\n"
    "from pathlib import Path\n"
    "h=sys.argv[1]\n"
    "if len(h)!=32 or any(c not in '0123456789abcdef' for c in h):"
    " raise SystemExit(89)\n"
    "r=Path('/run/changlian-os-onnx-pilot-'+h)\n"
    "m=json.loads((r/'evidence.json').read_text(encoding='utf-8'))\n"
    "b=(r/'verified.onnx').read_bytes()\n"
    "if len(b)!=m['size_bytes'] or hashlib.sha256(b).hexdigest()!=m['sha256']:"
    " raise SystemExit(92)\n"
    "print('changlian-onnx-sandbox-verified:'+m['sha256'],flush=True)\n"
    "time.sleep(5)\n"
)
_PROPERTIES = (
    "Type=exec", "ExitType=cgroup", "RemainAfterExit=yes", "Restart=no",
    "DynamicUser=yes", "NoNewPrivileges=yes", "PrivateDevices=yes",
    "DevicePolicy=closed", "KillMode=control-group", "SendSIGKILL=yes",
    "ProtectSystem=strict", "ProtectHome=yes", "ProtectControlGroups=yes",
    "PrivateTmp=yes", "PrivateNetwork=yes", "RestrictAddressFamilies=AF_UNIX",
    "CapabilityBoundingSet=", "AmbientCapabilities=", "UMask=0077",
    "RuntimeMaxSec=20s", "TimeoutStopSec=4s",
    "MemoryMax=256M", "TasksMax=24", "CPUQuota=50%",
)


def _handle(value: object) -> str:
    if not isinstance(value, str) or not _HANDLE.fullmatch(value):
        raise GrantRejected("CPU_ONNX_SANDBOX_HANDLE_INVALID_HOLD")
    return value


def build_fixed_onnx_cpu_argv(handle: object) -> tuple[str, ...]:
    """Untrusted Agent can select neither command, env, filesystem nor unit."""
    h = _handle(handle)
    return (
        "/usr/bin/systemd-run", "--system", "--no-ask-password",
        "--unit=changlian-os-" + h + ".service",
        *("--property=" + p for p in _PROPERTIES),
        "--property=ReadOnlyPaths=" + str(_ROOT / (_PREFIX + h)),
        "--", "/usr/bin/python3", "-I", "-u", "-c", _WORKER, h,
    )


def _trusted_directory(path: Path) -> None:
    try:
        s = path.lstat()
        if (not stat.S_ISDIR(s.st_mode) or s.st_uid != 0
                or stat.S_IMODE(s.st_mode) != 0o755):
            raise GrantRejected("CPU_ONNX_SANDBOX_DIRECTORY_UNTRUSTED_HOLD")
    except GrantRejected:
        raise
    except OSError as e:
        raise GrantRejected("CPU_ONNX_SANDBOX_DIRECTORY_UNKNOWN_HOLD") from e


def _write_once(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                 0o400)
    try:
        with os.fdopen(fd, "wb", closefd=False) as f:
            f.write(content)
            f.flush()
            os.fsync(fd)
        os.fchmod(fd, 0o444)
    finally:
        os.close(fd)


def _sealed_bytes(path: Path, *, digest: str, length: int) -> None:
    try:
        first = path.lstat()
        if (not stat.S_ISREG(first.st_mode) or first.st_uid != 0
                or first.st_nlink != 1 or stat.S_IMODE(first.st_mode) != 0o444
                or first.st_size != length):
            raise GrantRejected("CPU_ONNX_SANDBOX_FILE_UNTRUSTED_HOLD")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (first.st_dev, first.st_ino):
                raise GrantRejected("CPU_ONNX_SANDBOX_FILE_REPLACED_HOLD")
            with os.fdopen(fd, "rb", closefd=False) as f:
                data = f.read(64 * 1024 * 1024 + 1)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_ctime_ns,
                before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_ctime_ns, after.st_mtime_ns):
                raise GrantRejected("CPU_ONNX_SANDBOX_FILE_REPLACED_HOLD")
            last = path.lstat()
            if (after.st_dev, after.st_ino) != (last.st_dev, last.st_ino):
                raise GrantRejected("CPU_ONNX_SANDBOX_FILE_REPLACED_HOLD")
            if len(data) != length or hashlib.sha256(data).hexdigest() != digest:
                raise GrantRejected("CPU_ONNX_SANDBOX_FILE_HASH_MISMATCH_HOLD")
        finally:
            os.close(fd)
    except GrantRejected:
        raise
    except OSError as e:
        raise GrantRejected("CPU_ONNX_SANDBOX_FILE_UNKNOWN_HOLD") from e


@dataclass(frozen=True)
class StagedOnnxCpuPilot:
    handle: str
    root: Path
    sha256: str
    size_bytes: int
    production_launch_allowed: bool = False
    trusted_stop_receipt_available: bool = False


class IsolatedOnnxCpuSystemdPilot:
    """Only directly callable by isolated root CI. Not registered with RPC."""

    def __init__(self, *, isolated_ci_only: bool = False):
        if isolated_ci_only is not True:
            raise GrantRejected("CPU_ONNX_SANDBOX_DISABLED_HOLD")
        if (platform.system() != "Linux" or not hasattr(os, "geteuid")
                or os.geteuid() != 0):
            raise GrantRejected("CPU_ONNX_SANDBOX_ROOT_LINUX_REQUIRED_HOLD")
        _trusted_directory(_ROOT)
        # Existing backend fails closed if PID1 manager < systemd250.
        self.backend = FixedCpuSystemd()

    def stage(self, proof: CpuOnnxPilotPreflight) -> StagedOnnxCpuPilot:
        if (type(proof) is not CpuOnnxPilotPreflight
                or proof.production_launch_allowed is not False
                or proof.trusted_stop_receipt_available is not False
                or not proof._verified_bytes
                or len(proof._verified_bytes) != proof.size_bytes
                or hashlib.sha256(proof._verified_bytes).hexdigest() != proof.source_sha256):
            raise GrantRejected("CPU_ONNX_SANDBOX_PROOF_UNKNOWN_HOLD")
        # Never trust a preflight flag from an unprivileged Agent.
        _reject_external_data(proof._verified_bytes)
        h = secrets.token_hex(16)
        root = _ROOT / (_PREFIX + h)
        try:
            os.mkdir(root, 0o755)
            os.chmod(root, 0o755)
            _trusted_directory(root)
            _write_once(root / "verified.onnx", proof._verified_bytes)
            manifest = json.dumps(
                {"sha256": proof.source_sha256, "size_bytes": proof.size_bytes},
                separators=(",", ":"), sort_keys=True).encode("ascii")
            _write_once(root / "evidence.json", manifest)
            _sealed_bytes(root / "verified.onnx",
                          digest=proof.source_sha256, length=proof.size_bytes)
            _sealed_bytes(root / "evidence.json",
                          digest=hashlib.sha256(manifest).hexdigest(),
                          length=len(manifest))
        except (OSError, GrantRejected) as e:
            # Only this random, newly-created root, and before any launch.
            if root.is_dir() and root.parent == _ROOT:
                shutil.rmtree(root)
            if isinstance(e, GrantRejected):
                raise
            raise GrantRejected("CPU_ONNX_SANDBOX_STAGE_FAILED_HOLD") from e
        return StagedOnnxCpuPilot(h, root, proof.source_sha256, proof.size_bytes)

    def launch(self, staged: StagedOnnxCpuPilot) -> dict:
        """One-shot CI systemd; on lost ACK, caller MUST inspect, never retry."""
        if type(staged) is not StagedOnnxCpuPilot:
            raise GrantRejected("CPU_ONNX_SANDBOX_SCOPE_INVALID_HOLD")
        h = _handle(staged.handle)
        root = _ROOT / (_PREFIX + h)
        if staged.root != root or staged.production_launch_allowed:
            raise GrantRejected("CPU_ONNX_SANDBOX_SCOPE_INVALID_HOLD")
        _trusted_directory(root)
        _sealed_bytes(root / "verified.onnx", digest=staged.sha256,
                      length=staged.size_bytes)
        evidence = json.dumps({"sha256": staged.sha256,
                               "size_bytes": staged.size_bytes},
                              separators=(",", ":"), sort_keys=True).encode("ascii")
        _sealed_bytes(root / "evidence.json",
                      digest=hashlib.sha256(evidence).hexdigest(), length=len(evidence))
        self.backend._run(list(build_fixed_onnx_cpu_argv(h)))
        unit = "changlian-os-" + h + ".service"
        status = self.backend.snapshot(unit, require_running=True)
        if (status["exec_main_pid"] != str(status["main_pid"])
                or status["control_group"] != "/system.slice/" + unit):
            raise GrantRejected("CPU_ONNX_SANDBOX_OS_IDENTITY_UNKNOWN_HOLD")
        return {**status, "trusted_stop_receipt_available": False,
                "central_recovery_allowed": False}
