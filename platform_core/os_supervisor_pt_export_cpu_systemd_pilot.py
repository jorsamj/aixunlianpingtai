"""CI-only trusted YOLO11n PT -> ONNX under an isolated CPU systemd unit.

No business process, Agent, SupervisorService, HTTP route or central scheduler
imports this module. Source PT is generated from a pinned local model YAML
within the pinned, root-owned runtime; it is NEVER downloaded or accepted from
the Agent. PT is a Python pickle: an arbitrary SHA256 does NOT make it safe.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_cpu_systemd import FixedCpuSystemd
from .os_supervisor_onnx_cpu_systemd_pilot import (
    _handle, _sealed_bytes, _trusted_directory, _write_once,
)

_ROOT = Path("/run")
_PREFIX = "changlian-os-pt-pilot-"
_OUT_PREFIX = "changlian-pt-output-"
_RUNTIME = Path("/var/lib/changlian-pt-export-cpu-pilot/venv")
_PYTHON = "/var/lib/changlian-pt-export-cpu-pilot/venv/bin/python3"
_SOURCE = "source.pt"
_MANIFEST = "evidence.json"
_PROOF_PREFIX = "changlian-pt-export-proof:"
_MAX_BYTES = 64 * 1024 * 1024
# Trusted source is compiled from the pinned package's bundled YAML, no net.
_GENERATOR = """
from ultralytics import YOLO
from ultralytics import __version__
import sys
assert __version__ == "8.4.127"
model = YOLO("yolo11n.yaml")
model.save(sys.argv[1])
"""
# This worker is immutable, root-owned program text supplied by the codebase.
# RuntimeDirectory belongs only to the isolated DynamicUser during execution.
_WORKER = """
import hashlib, json, os, shutil, sys
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
import torch
from ultralytics import YOLO, __version__
if __version__ != "8.4.127" or torch.__version__ != "2.5.0+cpu":
    raise SystemExit("UNPINNED_MODEL_RUNTIME")
h = sys.argv[1]
if len(h) != 32 or any(c not in "0123456789abcdef" for c in h):
    raise SystemExit("INVALID_HANDLE")
root = Path("/run/changlian-os-pt-pilot-" + h)
out = Path("/run/changlian-pt-output-" + h)
record = json.loads((root / "evidence.json").read_text("ascii"))
raw = (root / "source.pt").read_bytes()
if len(raw) != record["size_bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
    raise SystemExit("PT_INPUT_DIGEST_MISMATCH")
if not out.is_dir():
    raise SystemExit("NO_DYNAMIC_USER_OUTPUT")
os.environ["YOLO_CONFIG_DIR"] = str(out)
shutil.copyfile(root / "source.pt", out / "source.pt")
# Only the trusted CI-generated fixture may cross this pickle load boundary.
yolo = YOLO(str(out / "source.pt"))
assert yolo.task == "detect"
model = yolo.model.cpu().eval()
torch.set_num_threads(1)
x = torch.linspace(0.0, 1.0, steps=3072, dtype=torch.float32).reshape(1, 3, 32, 32)
with torch.no_grad():
    expected = model(x)
expected = expected[0] if isinstance(expected, (tuple, list)) else expected
expected = expected.detach().cpu().numpy()
exported = yolo.export(format="onnx", imgsz=32, batch=1, opset=12,
                       dynamic=False, simplify=False, device="cpu", verbose=False)
onnx_path = Path(exported)
if onnx_path != out / "source.onnx" or not onnx_path.is_file():
    raise SystemExit("UNEXPECTED_EXPORT_OUTPUT")
onnx.checker.check_model(str(onnx_path), full_check=False)
opts = ort.SessionOptions()
opts.intra_op_num_threads = 1
opts.inter_op_num_threads = 1
session = ort.InferenceSession(str(onnx_path),
                             sess_options=opts, providers=["CPUExecutionProvider"])
if session.get_providers() != ["CPUExecutionProvider"]:
    raise SystemExit("NON_CPU_ONNX_PROVIDER")
inputs = session.get_inputs()
outputs = session.get_outputs()
if len(inputs) != 1 or len(outputs) != 1:
    raise SystemExit("UNEXPECTED_ONNX_IO")
actual = session.run([outputs[0].name], {inputs[0].name:x.numpy()})[0]
if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
    raise SystemExit("ONNX_SHAPE_OR_FINITE_MISMATCH")
max_abs = float(np.max(np.abs(actual - expected)))
if not np.allclose(actual, expected, rtol=1e-3, atol=1e-3):
    raise SystemExit("ONNX_NUMERIC_MISMATCH")
body = {
    "source_sha256": record["sha256"],
    "onnx_sha256": hashlib.sha256(onnx_path.read_bytes()).hexdigest(),
    "onnx_size_bytes": onnx_path.stat().st_size,
    "input_shape": list(x.shape),
    "output_shape": list(actual.shape),
    "input_sha256": hashlib.sha256(x.numpy().tobytes()).hexdigest(),
    "cpu_provider": session.get_providers()[0],
    "max_abs_error": max_abs,
    "runtime": __version__,
    "opset": 12,
}
print("changlian-pt-export-proof:" + json.dumps(body, sort_keys=True), flush=True)
"""
_PROPS = (
    "Type=exec", "ExitType=cgroup", "RemainAfterExit=yes", "Restart=no",
    "DynamicUser=yes", "NoNewPrivileges=yes", "PrivateDevices=yes",
    "DevicePolicy=closed", "KillMode=control-group", "SendSIGKILL=yes",
    "ProtectSystem=strict", "ProtectHome=yes", "ProtectControlGroups=yes",
    "PrivateTmp=yes", "PrivateNetwork=yes", "RestrictAddressFamilies=AF_UNIX",
    "CapabilityBoundingSet=", "AmbientCapabilities=", "UMask=0077",
    "MemoryMax=4G", "TasksMax=64", "CPUQuota=200%",
    "RuntimeMaxSec=180s", "TimeoutStopSec=5s",
)


def _hold(code: str) -> None:
    raise GrantRejected("PT_CPU_" + code + "_HOLD")


def _check_runtime() -> None:
    # No binary, Python import directory, torch/onnxlib, or YAML is writable
    # by the unprivileged worker. Avoid trusting an Agent-provided interpreter.
    dirs = (
        Path("/var"), Path("/var/lib"), _RUNTIME.parent, _RUNTIME,
        _RUNTIME / "bin", _RUNTIME / "lib",
        _RUNTIME / "lib/python3.12",
        _RUNTIME / "lib/python3.12/site-packages",
    )
    try:
        for p in dirs:
            info = p.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                _hold("RUNTIME_DIRECTORY_MUTABLE")
        py = Path(_PYTHON)
        info = py.lstat()
        real = py.resolve(strict=True)
        if (info.st_uid != 0 or real != Path("/usr/bin/python3.12")
                or not stat.S_ISREG(real.stat().st_mode)
                or real.stat().st_uid != 0
                or real.stat().st_mode & 0o022):
            _hold("RUNTIME_INTERPRETER_INVALID")
        cfg = (_RUNTIME / "pyvenv.cfg").lstat()
        if not stat.S_ISREG(cfg.st_mode) or cfg.st_uid != 0 or cfg.st_mode & 0o022:
            _hold("RUNTIME_CONFIG_UNTRUSTED")
        for root, dirs, files in os.walk(
                _RUNTIME / "lib/python3.12/site-packages", followlinks=False):
            for item in dirs + files:
                entry = Path(root) / item
                info = entry.lstat()
                if info.st_uid != 0:
                    _hold("RUNTIME_PACKAGE_MUTABLE")
                if stat.S_ISLNK(info.st_mode):
                    resolved = entry.resolve(strict=True)
                    if (not resolved.is_relative_to(_RUNTIME)
                            or resolved.stat().st_uid != 0
                            or resolved.stat().st_mode & 0o022):
                        _hold("RUNTIME_PACKAGE_LINK_UNTRUSTED")
                elif (not (stat.S_ISDIR(info.st_mode)
                           or stat.S_ISREG(info.st_mode))
                      or info.st_mode & 0o022):
                    _hold("RUNTIME_PACKAGE_MUTABLE")
    except GrantRejected:
        raise
    except OSError as exc:
        raise GrantRejected("PT_CPU_RUNTIME_UNAVAILABLE_HOLD") from exc


def build_fixed_pt_cpu_argv(handle: object) -> tuple[str, ...]:
    h = _handle(handle)
    return (
        "/usr/bin/systemd-run", "--system", "--no-ask-password",
        "--unit=changlian-os-" + h + ".service",
        *("--property=" + p for p in _PROPS),
        "--property=ReadOnlyPaths=/run/" + _PREFIX + h,
        "--property=RuntimeDirectory=" + _OUT_PREFIX + h,
        "--property=RuntimeDirectoryMode=0700",
        "--property=RuntimeDirectoryPreserve=yes",
        "--", _PYTHON, "-I", "-u", "-c", _WORKER, h,
    )


@dataclass(frozen=True)
class StagedPtCpuFixture:
    handle: str
    root: Path
    source_sha256: str
    source_size_bytes: int
    trusted_ci_generated: bool = True
    production_launch_allowed: bool = False
    result_publish_allowed: bool = False
    trusted_stop_receipt_available: bool = False


class IsolatedPtExportCpuPilot:
    """Unreachable from production unless directly constructed by CI root."""

    def __init__(self, *, isolated_ci_only: bool = False):
        if isolated_ci_only is not True:
            _hold("DISABLED")
        if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            _hold("LINUX_ROOT_REQUIRED")
        _trusted_directory(_ROOT)
        _check_runtime()
        self.backend = FixedCpuSystemd()  # requires live systemd>=250

    def generate_trusted_fixture(self) -> StagedPtCpuFixture:
        """Create the ONLY allowed pickle in a freshly protected root dir."""
        handle = secrets.token_hex(16)
        path = _ROOT / (_PREFIX + handle)
        try:
            os.mkdir(path, mode=0o755)
            os.chmod(path, 0o755)
            _trusted_directory(path)
            target = path / _SOURCE
            subprocess.run(
                [_PYTHON, "-I", "-c", _GENERATOR, str(target)],
                timeout=100, check=True, capture_output=True,
                env={"PATH": "/usr/bin:/bin", "HOME": "/root",
                     "CUDA_VISIBLE_DEVICES": "", "YOLO_OFFLINE": "1"},
            )
            raw = target.read_bytes()
            if not 0 < len(raw) <= _MAX_BYTES:
                _hold("GENERATED_WEIGHT_SIZE_INVALID")
            sha = hashlib.sha256(raw).hexdigest()
            os.chmod(target, 0o444)
            manifest = json.dumps(
                {"sha256": sha, "size_bytes": len(raw), "origin": "trusted-ci-generated-yolo11n"},
                separators=(",", ":"), sort_keys=True).encode("ascii")
            _write_once(path / _MANIFEST, manifest)
            _sealed_bytes(target, digest=sha, length=len(raw))
            _sealed_bytes(path / _MANIFEST,
                          digest=hashlib.sha256(manifest).hexdigest(),
                          length=len(manifest))
        except (OSError, subprocess.SubprocessError, GrantRejected) as exc:
            if path.is_dir():
                shutil.rmtree(path)
            if isinstance(exc, GrantRejected):
                raise
            raise GrantRejected("PT_CPU_GENERATOR_FAILED_HOLD") from exc
        return StagedPtCpuFixture(handle, path, sha, len(raw))

    def rebind_trusted_fixture(
        self, staged: StagedPtCpuFixture, journal_handle: str,
    ) -> StagedPtCpuFixture:
        """Move a locally GENERATED fixture onto the original OS journal handle.

        This is an isolated CI-only staging action. Never load or copy an
        Agent-supplied pickle; both directories are root-only /run paths.
        Original fixture handle is invalid after the atomic rename.
        """
        if (type(staged) is not StagedPtCpuFixture
                or staged.trusted_ci_generated is not True
                or staged.production_launch_allowed is not False
                or staged.result_publish_allowed is not False
                or staged.trusted_stop_receipt_available is not False):
            _hold("REBOUND_FIXTURE_NOT_TRUSTED")
        old = _handle(staged.handle)
        new = _handle(journal_handle)
        if old == new or staged.root != _ROOT / (_PREFIX + old):
            _hold("REBOUND_HANDLE_NOT_INDEPENDENT")
        _trusted_directory(staged.root)
        _sealed_bytes(
            staged.root / _SOURCE, digest=staged.source_sha256,
            length=staged.source_size_bytes,
        )
        manifest = json.dumps(
            {"sha256": staged.source_sha256, "size_bytes": staged.source_size_bytes,
             "origin": "trusted-ci-generated-yolo11n"},
            separators=(",", ":"), sort_keys=True,
        ).encode("ascii")
        _sealed_bytes(
            staged.root / _MANIFEST, digest=hashlib.sha256(manifest).hexdigest(),
            length=len(manifest),
        )
        target = _ROOT / (_PREFIX + new)
        if target.exists() or target.is_symlink():
            _hold("REBOUND_TARGET_ALREADY_PRESENT")
        try:
            os.rename(staged.root, target)
        except OSError as exc:
            raise GrantRejected("PT_CPU_REBOUND_RENAME_UNVERIFIED_HOLD") from exc
        _trusted_directory(target)
        return StagedPtCpuFixture(
            handle=new, root=target,
            source_sha256=staged.source_sha256,
            source_size_bytes=staged.source_size_bytes,
        )

    def launch(self, staged: StagedPtCpuFixture) -> dict:
        if (type(staged) is not StagedPtCpuFixture
                or staged.trusted_ci_generated is not True
                or staged.production_launch_allowed is not False
                or staged.result_publish_allowed is not False):
            _hold("STAGED_SCOPE_INVALID")
        h = _handle(staged.handle)
        root = _ROOT / (_PREFIX + h)
        if staged.root != root:
            _hold("STAGED_ROOT_MISMATCH")
        _trusted_directory(root)
        _sealed_bytes(root / _SOURCE,
                      digest=staged.source_sha256,
                      length=staged.source_size_bytes)
        manifest = json.dumps(
            {"sha256": staged.source_sha256,
             "size_bytes": staged.source_size_bytes,
             "origin": "trusted-ci-generated-yolo11n"},
            separators=(",", ":"), sort_keys=True).encode("ascii")
        _sealed_bytes(root / _MANIFEST, digest=hashlib.sha256(manifest).hexdigest(),
                      length=len(manifest))
        # Durable one-shot marker BEFORE any systemd-run. A lost response never
        # authorizes a second execution even if the unit disappears.
        try:
            _write_once(root / ".launch-consumed", b"consumed")
        except FileExistsError as exc:
            raise GrantRejected("PT_CPU_LAUNCH_ALREADY_CONSUMED_HOLD") from exc
        self.backend._run(list(build_fixed_pt_cpu_argv(h)))
        unit = "changlian-os-" + h + ".service"
        status = self.backend.snapshot(unit, require_running=True)
        if (status["exec_main_pid"] != str(status["main_pid"])
                or status["control_group"] != "/system.slice/" + unit):
            _hold("OS_IDENTITY_UNVERIFIED")
        return {
            **status, "production_launch_allowed": False,
            "result_publish_allowed": False,
            "trusted_stop_receipt_available": False,
        }


    def read_export_proof_log(self, first: dict) -> bytes:
        """Read ONLY exact-prefix result records from the original InvocationID.

        The generic journal parser would also encounter a giant systemd
        ExecStart line containing the multi-line fixed Python program; that
        untrusted diagnostic entry can break line-oriented JSON parsing.
        Filtering by proof prefix avoids treating it as model evidence.
        """
        if not isinstance(first, dict):
            _hold("PROOF_ORIGINAL_IDENTITY_MISSING")
        unit, invocation = first.get("unit_name"), first.get("invocation_id")
        if (not isinstance(unit, str)
                or not re.fullmatch(r"changlian-os-[0-9a-f]{32}\.service", unit)
                or not isinstance(invocation, str)
                or not re.fullmatch(r"[0-9a-f]{32}", invocation)):
            _hold("PROOF_ORIGINAL_IDENTITY_INVALID")
        self.backend.inspect(unit, invocation)
        args = [
            "/usr/bin/journalctl", "--system", "--quiet", "--no-pager",
            "--output=json", "--lines=+32", "--unit", unit,
            "_SYSTEMD_INVOCATION_ID=" + invocation,
            "--grep=^changlian-pt-export-proof:",
        ]
        try:
            outcome = subprocess.run(
                args, shell=False, capture_output=True, text=True,
                timeout=7, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GrantRejected("PT_CPU_PROOF_JOURNAL_UNAVAILABLE_HOLD") from exc
        # journalctl --grep has exit status 1 when no matching message has
        # arrived YET; this is not proof of success or failure.
        if outcome.returncode == 1 and not outcome.stdout.strip() and not outcome.stderr.strip():
            return b""
        if (outcome.returncode != 0
                or len(outcome.stdout.encode("utf-8")) > 16384):
            _hold("PROOF_JOURNAL_COMMAND_FAILED")
        raw = outcome.stdout
        records = []
        try:
            for line in raw.splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if (not isinstance(entry, dict)
                        or entry.get("_SYSTEMD_UNIT") != unit
                        or entry.get("_SYSTEMD_INVOCATION_ID") != invocation
                        or not isinstance(entry.get("MESSAGE"), str)
                        or not entry["MESSAGE"].startswith(_PROOF_PREFIX)):
                    _hold("PROOF_JOURNAL_IDENTITY_MISMATCH")
                records.append(entry["MESSAGE"])
        except (ValueError, TypeError) as exc:
            raise GrantRejected("PT_CPU_PROOF_JOURNAL_INVALID_HOLD") from exc
        return ("\n".join(records)).encode("utf-8")


def parse_pt_export_log(data: bytes, source_sha: str) -> dict:
    if not isinstance(data, bytes) or not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        _hold("LOG_SCOPE_INVALID")
    records = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        if line.startswith(_PROOF_PREFIX):
            try:
                records.append(json.loads(line[len(_PROOF_PREFIX):]))
            except (ValueError, TypeError) as exc:
                raise GrantRejected("PT_CPU_PROOF_INVALID_HOLD") from exc
    if len(records) != 1:
        _hold("PROOF_ABSENT_OR_REPEATED")
    r = records[0]
    required = {
        "source_sha256", "onnx_sha256", "onnx_size_bytes", "input_shape",
        "output_shape", "input_sha256", "cpu_provider", "max_abs_error",
        "runtime", "opset",
    }
    if (not isinstance(r, dict) or set(r) != required
            or r["source_sha256"] != source_sha
            or not isinstance(r["onnx_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", r["onnx_sha256"])
            or type(r["onnx_size_bytes"]) is not int or r["onnx_size_bytes"] <= 0
            or r["input_shape"] != [1, 3, 32, 32]
            or not isinstance(r["output_shape"], list)
            or len(r["output_shape"]) != 3
            or not all(type(v) is int and v > 0 for v in r["output_shape"])
            or not isinstance(r["input_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", r["input_sha256"])
            or r["cpu_provider"] != "CPUExecutionProvider"
            or r["runtime"] != "8.4.127"
            or r["opset"] != 12
            or type(r["max_abs_error"]) not in (int, float)
            or not 0 <= r["max_abs_error"] < 0.001):
        _hold("PROOF_CONTENT_INVALID")
    return r
