"""2D-2B2: root-only CI ONNX Runtime under protected systemd, NOT production."""
import hashlib
import json
import os
from pathlib import Path
import stat
from .os_supervisor_authorization import GrantRejected
from .os_supervisor_onnx_cpu_systemd_pilot import (
    IsolatedOnnxCpuSystemdPilot, StagedOnnxCpuPilot, _PREFIX, _PROPERTIES,
    _ROOT, _handle, _sealed_bytes, _trusted_directory,
)

_RUNTIME = Path("/var/lib/changlian-onnxruntime-cpu-pilot/venv")
_PYTHON = str(_RUNTIME / "bin/python3")
_PREFIX_RESULT = "changlian-onnx-ort-result:"
_WORKER = """
import hashlib,json,sys,time
from pathlib import Path
import numpy as np
import onnxruntime as ort
if ort.__version__ != "1.22.1" or np.__version__ != "2.2.6":
    raise SystemExit("RUNTIME_VERSION_MISMATCH")
handle=sys.argv[1]
if len(handle)!=32 or any(x not in "0123456789abcdef" for x in handle):
    raise SystemExit("INVALID_HANDLE")
root=Path("/run/changlian-os-onnx-pilot-"+handle)
meta=json.loads((root/"evidence.json").read_text())
raw=(root/"verified.onnx").read_bytes()
sha=hashlib.sha256(raw).hexdigest()
if len(raw)!=meta["size_bytes"] or sha!=meta["sha256"]:
    raise SystemExit("MODEL_INTEGRITY_MISMATCH")
options=ort.SessionOptions()
options.intra_op_num_threads=1
options.inter_op_num_threads=1
session=ort.InferenceSession(str(root/"verified.onnx"),
    sess_options=options,providers=["CPUExecutionProvider"])
if session.get_providers()!=["CPUExecutionProvider"]:
    raise SystemExit("NON_CPU_PROVIDER")
inputs=session.get_inputs()
outputs=session.get_outputs()
if len(inputs)!=1 or len(outputs)!=1 or inputs[0].type!="tensor(float)":
    raise SystemExit("IO_SCOPE_UNSUPPORTED")
shape=inputs[0].shape
if not shape or any(type(x) is not int or x<1 for x in shape):
    raise SystemExit("SHAPE_UNSUPPORTED")
count=1
for dim in shape:
    count*=dim
    if count>65536:
        raise SystemExit("INPUT_TOO_LARGE")
values=np.arange(count,dtype=np.float32).reshape(shape)
values/=float(count+1)
result=np.ascontiguousarray(session.run(
    [outputs[0].name],{inputs[0].name:values})[0])
if result.dtype!=np.float32 or result.size>65536:
    raise SystemExit("OUTPUT_UNSUPPORTED")
record={
  "model_sha256":sha,
  "input_sha256":hashlib.sha256(values.tobytes()).hexdigest(),
  "output_sha256":hashlib.sha256(result.tobytes()).hexdigest(),
  "input_shape":list(values.shape),
  "output_shape":list(result.shape),
  "provider":"CPUExecutionProvider",
  "onnxruntime_version":ort.__version__,
}
print("changlian-onnx-ort-result:"+json.dumps(record,sort_keys=True),flush=True)
time.sleep(6)
"""
_PROPS = tuple(x for x in _PROPERTIES if not x.startswith(
    ("MemoryMax=", "RuntimeMaxSec=", "CPUQuota="))) + (
    "MemoryMax=768M", "RuntimeMaxSec=45s", "CPUQuota=100%",
)


def build_fixed_onnx_ort_cpu_argv(handle):
    h = _handle(handle)
    return ("/usr/bin/systemd-run", "--system", "--no-ask-password",
            "--unit=changlian-os-" + h + ".service",
            *("--property=" + x for x in _PROPS),
            "--property=ReadOnlyPaths=/run/" + _PREFIX + h,
            "--", _PYTHON, "-I", "-u", "-c", _WORKER, h)


def _root_runtime_verified():
    dirs = (Path("/var"), Path("/var/lib"), _RUNTIME.parent,
            _RUNTIME, _RUNTIME / "bin",
            _RUNTIME / "lib", _RUNTIME / "lib/python3.12",
            _RUNTIME / "lib/python3.12/site-packages")
    try:
        for p in dirs:
            s = p.lstat()
            if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                raise GrantRejected("ORT_RUNTIME_MUTABLE_HOLD")
        py = Path(_PYTHON)
        link = py.lstat()
        target = py.resolve(strict=True)
        s = target.stat()
        cfg = (_RUNTIME / "pyvenv.cfg").lstat()
        if (link.st_uid != 0
                # Linux symlink mode 0777 is ignored by the kernel. Trust only
                # a root-owned link resolving to our exact fixed OS binary.
                or (not stat.S_ISLNK(link.st_mode)
                    and (not stat.S_ISREG(link.st_mode)
                         or link.st_mode & 0o022))
                or target != Path("/usr/bin/python3.12")
                or not stat.S_ISREG(s.st_mode) or s.st_uid != 0
                or s.st_mode & 0o022 or not stat.S_ISREG(cfg.st_mode)
                or cfg.st_uid != 0 or cfg.st_mode & 0o022):
            raise GrantRejected("ORT_RUNTIME_INTERPRETER_HOLD")
        for root, dirs, files in os.walk(
                _RUNTIME / "lib/python3.12/site-packages", followlinks=False):
            for name in dirs + files:
                s = (Path(root) / name).lstat()
                if s.st_uid != 0 or s.st_mode & 0o022 or not (
                        stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):
                    raise GrantRejected("ORT_RUNTIME_PACKAGE_MUTABLE_HOLD")
    except GrantRejected:
        raise
    except OSError as exc:
        raise GrantRejected("ORT_RUNTIME_UNAVAILABLE_HOLD") from exc


class IsolatedOnnxOrtSystemdPilot(IsolatedOnnxCpuSystemdPilot):
    """Not registered to SupervisorService or any real Agent execution path."""

    def launch(self, staged):
        if type(staged) is not StagedOnnxCpuPilot:
            raise GrantRejected("ORT_SCOPE_INVALID_HOLD")
        h = _handle(staged.handle)
        root = _ROOT / (_PREFIX + h)
        if (staged.root != root or staged.production_launch_allowed
                or staged.trusted_stop_receipt_available):
            raise GrantRejected("ORT_SCOPE_INVALID_HOLD")
        _trusted_directory(root)
        _sealed_bytes(root / "verified.onnx",
                      digest=staged.sha256, length=staged.size_bytes)
        record = json.dumps({"sha256": staged.sha256,
                             "size_bytes": staged.size_bytes},
                            separators=(",", ":"), sort_keys=True).encode("ascii")
        _sealed_bytes(root / "evidence.json",
                      digest=hashlib.sha256(record).hexdigest(),
                      length=len(record))
        _root_runtime_verified()
        self.backend._run(list(build_fixed_onnx_ort_cpu_argv(h)))
        unit = "changlian-os-" + h + ".service"
        status = self.backend.snapshot(unit, require_running=True)
        if (status["exec_main_pid"] != str(status["main_pid"])
                or status["control_group"] != "/system.slice/" + unit):
            raise GrantRejected("ORT_OS_IDENTITY_UNKNOWN_HOLD")
        return {**status, "production_launch_allowed": False,
                "trusted_stop_receipt_available": False,
                "central_recovery_allowed": False}


def parse_ort_result_log(log: bytes, expected_sha: str):
    if not isinstance(log, bytes):
        raise GrantRejected("ORT_LOG_INVALID_HOLD")
    lines = [s[len(_PREFIX_RESULT):] for s in
             log.decode("utf-8", errors="replace").splitlines()
             if s.startswith(_PREFIX_RESULT)]
    if len(lines) != 1:
        raise GrantRejected("ORT_RESULT_MISSING_HOLD")
    try:
        record = json.loads(lines[0])
    except ValueError as exc:
        raise GrantRejected("ORT_RESULT_INVALID_HOLD") from exc
    required = {"model_sha256", "input_sha256", "output_sha256", "input_shape",
                "output_shape", "provider", "onnxruntime_version"}
    if (not isinstance(record, dict) or set(record) != required
            or record["model_sha256"] != expected_sha
            or record["provider"] != "CPUExecutionProvider"
            or record["onnxruntime_version"] != "1.22.1"
            or not all(isinstance(record[x], str) and len(record[x]) == 64
                       and all(c in "0123456789abcdef" for c in record[x])
                       for x in ("model_sha256", "input_sha256", "output_sha256"))
            or not all(isinstance(record[x], list) and record[x]
                       and all(type(n) is int and n > 0 for n in record[x])
                       for x in ("input_shape", "output_shape"))):
        raise GrantRejected("ORT_RESULT_SCOPE_INVALID_HOLD")
    return record
