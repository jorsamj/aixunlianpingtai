"""Durable, content-addressed mother-model metadata; never unpickle in Web.

An uploaded checkpoint is *not* training evidence. Verification is performed by
the dedicated probe only when an actual operating-system sandbox is present.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import shutil
import subprocess
import sys
import time
import zipfile

from filelock import FileLock


_VERIFY_HIDDEN_ROOTS = ("/root", "/home", "/data", "/workspace", "/tmp", "/var", "/mnt", "/run")
_VERIFY_OUTPUT_LIMIT = 128 * 1024
_VERIFY_TIMEOUT_SECONDS = 60
_VERIFY_STALE_SECONDS = 180

# Exact SHA256 and byte counts published for the official Ultralytics assets
# release v8.4.0. A filename alone must never authorize pickle deserialization.
# https://github.com/ultralytics/assets/releases/tag/v8.4.0
_OFFICIAL_YOLO11_DETECT = {
    "yolo11n.pt": (5613764, "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1"),
    "yolo11s.pt": (19313732, "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5"),
    "yolo11m.pt": (40684120, "d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95"),
}
_COCO80_NAMES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
)


def verifier_environment_status(*, python_executable: str | None = None) -> dict:
    """Cheap configuration check only; never imports Torch or reads a PT.

    CONFIGURED does not imply that Linux namespaces work. The actual sandbox
    launch is verified by the explicit per-asset validation operation.
    """
    if sys.platform != "linux" or not shutil.which("bwrap"):
        return {"status": "UNAVAILABLE", "code": "PT_SANDBOX_NOT_CONFIGURED"}
    requested = python_executable or os.environ.get("MC_MOTHER_MODEL_VERIFY_PYTHON") or sys.executable
    if not Path(requested).is_absolute():
        return {"status": "UNAVAILABLE", "code": "PT_VERIFY_PYTHON_NOT_CONFIGURED"}
    try:
        executable = Path(os.path.abspath(requested))
        resolved = executable.resolve(strict=True)
    except (OSError, RuntimeError):
        return {"status": "UNAVAILABLE", "code": "PT_VERIFY_PYTHON_NOT_CONFIGURED"}
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return {"status": "UNAVAILABLE", "code": "PT_VERIFY_PYTHON_NOT_CONFIGURED"}
    if any(any(path == Path(root) or Path(root) in path.parents for root in _VERIFY_HIDDEN_ROOTS)
           for path in (executable, resolved)):
        return {"status": "UNAVAILABLE", "code": "PT_PYTHON_RUNTIME_NOT_ISOLATABLE"}
    return {"status": "CONFIGURED", "code": "", "runtime": "configured_python" if os.environ.get("MC_MOTHER_MODEL_VERIFY_PYTHON") else "web_python"}


def public_asset_status(row: dict, *, now: float | None = None) -> dict:
    """Project an interrupted old CHECKING attempt without a write on GET."""
    result = dict(row)
    try:
        started = float(result.get("validation_started_at") or 0)
    except (TypeError, ValueError):
        started = 0
    if result.get("validation_status") == "CHECKING" and started and (time.time() if now is None else now) - started > _VERIFY_STALE_SECONDS:
        result.update(validation_status="INTERRUPTED", validation_error="PT_VERIFY_INTERRUPTED", trainable=False)
    return result


def _run_bounded_probe(command: list[str], *, timeout: int = _VERIFY_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """Drain child output without unbounded memory and terminate its process group."""
    streams: dict[object, bytearray] = {}
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, env={}, start_new_session=True)
    try:
        with selectors.DefaultSelector() as watcher:
            for stream in (proc.stdout, proc.stderr):
                assert stream is not None
                watcher.register(stream, selectors.EVENT_READ)
                streams[stream] = bytearray()
            deadline = time.monotonic() + timeout
            while watcher.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                for key, _ in watcher.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        watcher.unregister(key.fileobj)
                        continue
                    if sum(len(part) for part in streams.values()) + len(chunk) > _VERIFY_OUTPUT_LIMIT:
                        raise OverflowError("mother-model verifier exceeded bounded output")
                    streams[key.fileobj].extend(chunk)
            proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        return (proc.returncode,
                bytes(streams[proc.stdout]).decode("utf-8", errors="replace"),
                bytes(streams[proc.stderr]).decode("utf-8", errors="replace"))
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


def registry_path(data_dir: Path) -> Path:
    return Path(data_dir) / "models" / ".mother-model-assets.json"


def list_assets(data_dir: Path) -> list[dict]:
    path = registry_path(data_dir)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return []
    return list(body.get("items", [])) if isinstance(body, dict) else []


def put_asset(data_dir: Path, row: dict) -> dict:
    path = registry_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=30):
        rows = list_assets(data_dir)
        index = next((i for i, item in enumerate(rows) if item.get("asset_id") == row["asset_id"]), -1)
        merged = {**(rows[index] if index >= 0 else {}), **row}
        if index < 0:
            rows.append(merged)
        else:
            rows[index] = merged
        temp = path.with_name("." + path.name + "." + os.urandom(6).hex() + ".tmp")
        try:
            with temp.open("x", encoding="utf-8") as stream:
                json.dump({"schema_version": 1, "items": rows}, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return merged


def get_asset(data_dir: Path, asset_id: str) -> dict | None:
    return next((row for row in list_assets(data_dir) if row.get("asset_id") == asset_id), None)


def initial_asset(data_dir: Path, path: Path, sha256: str, *, source: str = "upload") -> dict:
    asset_id = "pt_" + sha256[:24]
    existing = get_asset(data_dir, asset_id)
    if existing:
        return existing
    return put_asset(data_dir, {
        "asset_id": asset_id,
        "name": path.name,
        "sha256": sha256,
        "size_bytes": path.stat().st_size,
        "path": str(path.resolve()),
        "source": source,
        "node_locations": [{"node_id": "controller", "state": "PRESENT", "sha256": sha256}],
        "validation_status": "UNVERIFIED",
        "trainable": False,
        "inference_compatible": False,
        "names": [],
        "task": "unknown",
        "framework": "unknown",
        "created_at": time.time(),
    })


def _check_torch_container(path: Path) -> tuple[bool, str]:
    """Only structural validation; never execute a pickle payload."""
    if not path.is_file() or path.suffix.lower() != ".pt" or path.stat().st_size < 1024:
        return False, "PT_FILE_INVALID"
    if not zipfile.is_zipfile(path):
        return False, "PT_ARCHIVE_UNSUPPORTED"
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 200_000 or not any(i.filename.endswith("/data.pkl") for i in infos):
                return False, "PT_CHECKPOINT_STRUCTURE_INVALID"
            if any(i.file_size > 100 * 1024 * 1024 for i in infos if i.filename.endswith("/data.pkl")):
                return False, "PT_PICKLE_TOO_LARGE"
    except (OSError, ValueError, zipfile.BadZipFile):
        return False, "PT_ARCHIVE_CORRUPT"
    return True, ""


def verify_trusted_official_checkpoint(path: Path) -> dict | None:
    """Verify a pinned official release by bytes, without importing Torch.

    Unknown or modified weights return None and must retain the existing
    sandbox-only route. Never infer trust from a YOLO-looking filename.
    """
    expected = _OFFICIAL_YOLO11_DETECT.get(path.name.lower())
    if not expected or path.is_symlink() or not path.is_file():
        return None
    expected_size, expected_sha = expected
    if path.stat().st_size != expected_size:
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha:
            return None
        structurally_valid, _ = _check_torch_container(path)
        if not structurally_valid:
            return None
    except (OSError, ValueError):
        return None
    return {
        "validation_status": "VERIFIED", "validation_error": "", "trainable": True,
        "inference_compatible": True, "framework": "ultralytics", "task": "detect",
        "names": list(_COCO80_NAMES), "nc": len(_COCO80_NAMES),
        "architecture": "DetectionModel", "verification_method": "official_release_sha256",
        "official_release": "ultralytics/assets:v8.4.0",
    }


def verify_checkpoint_in_sandbox(path: Path, *, python_executable: str | None = None) -> dict:
    """Load YOLO solely in a no-network, read-only, unprivileged bubblewrap guest.

    Absence of working namespaces is an explicit stop, never a fallback to
    ``torch.load(weights_only=False)`` in the control service.
    """
    valid, reason = _check_torch_container(path)
    if not valid:
        return {"validation_status": "INVALID", "validation_error": reason, "trainable": False}
    environment = verifier_environment_status(python_executable=python_executable)
    if environment["status"] != "CONFIGURED":
        return {"validation_status": "SANDBOX_UNAVAILABLE", "validation_error": environment["code"], "trainable": False}
    wrapper = shutil.which("bwrap")
    # Keep the venv/bin/python symlink path: resolving it to /usr/bin/python
    # would silently discard the virtualenv's site-packages and pyvenv.cfg.
    python = Path(os.path.abspath(python_executable or os.environ.get("MC_MOTHER_MODEL_VERIFY_PYTHON") or sys.executable))
    probe = '''import json,sys,resource
resource.setrlimit(resource.RLIMIT_CPU,(55,60))
resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))
try:
 from ultralytics import YOLO
except Exception:
 print("MODEL_PROBE_ENV:PT_VERIFY_DEPENDENCY_MISSING")
 sys.exit(44)
model=YOLO(sys.argv[1])
names=model.names or {}
if isinstance(names,dict): names=[str(names[k]) for k in sorted(names,key=lambda k:int(k))]
else: names=list(map(str,names))
task=str(getattr(model,"task", "unknown"))
architecture=type(model.model).__name__
print("MODEL_PROBE_JSON:"+json.dumps({"task":task,"names":names,"nc":len(names),"architecture":architecture,"framework":"ultralytics"}))
'''
    command = [wrapper, "--die-with-parent", "--unshare-all", "--new-session",
               "--ro-bind", "/", "/", "--tmpfs", "/tmp", "--tmpfs", "/home",
               "--tmpfs", "/root", "--tmpfs", "/data", "--tmpfs", "/workspace",
               "--tmpfs", "/var", "--tmpfs", "/mnt", "--tmpfs", "/run",
               "--ro-bind", str(path.resolve()), "/tmp/model.pt", "--proc", "/proc",
               "--dev", "/dev", "--chdir", "/tmp", "--uid", "65534", "--gid", "65534",
               "--clearenv", "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin",
               "--setenv", "PYTHONNOUSERSITE", "1", "--setenv", "HF_HUB_OFFLINE", "1",
               "--setenv", "WANDB_MODE", "disabled", "--setenv", "OMP_NUM_THREADS", "1",
               str(python), "-I", "-c", probe, "/tmp/model.pt"]
    try:
        returncode, stdout, stderr = _run_bounded_probe(command)
    except subprocess.TimeoutExpired:
        return {"validation_status": "FAILED", "validation_error": "PT_VERIFY_TIMEOUT", "trainable": False}
    except OverflowError:
        return {"validation_status": "FAILED", "validation_error": "PT_VERIFY_OUTPUT_LIMIT", "trainable": False}
    except OSError:
        return {"validation_status": "SANDBOX_UNAVAILABLE", "validation_error": "PT_SANDBOX_NOT_EXECUTABLE", "trainable": False}
    if returncode:
        if returncode == 44 and "MODEL_PROBE_ENV:PT_VERIFY_DEPENDENCY_MISSING" in stdout:
            return {"validation_status": "SANDBOX_UNAVAILABLE", "validation_error": "PT_VERIFY_DEPENDENCY_MISSING", "trainable": False}
        failure = stderr.lower()
        error = "PT_SANDBOX_NOT_EXECUTABLE" if any(marker in failure for marker in ("namespace", "bwrap:", "operation not permitted")) else "PT_MODEL_LOAD_FAILED"
        return {"validation_status": "SANDBOX_UNAVAILABLE" if error.endswith("NOT_EXECUTABLE") else "INVALID",
                "validation_error": error, "trainable": False}
    lines = [line.removeprefix("MODEL_PROBE_JSON:") for line in stdout.splitlines() if line.startswith("MODEL_PROBE_JSON:")]
    try:
        meta = json.loads(lines[-1])
        names = meta["names"]
        if not isinstance(names, list) or len(names) != meta["nc"] or not all(isinstance(s, str) for s in names):
            raise ValueError("invalid class list")
        if meta.get("task") != "detect" or not names or len(names) > 10_000:
            return {**meta, "validation_status": "INCOMPATIBLE", "validation_error": "PT_TASK_NOT_DETECT", "trainable": False}
        return {**meta, "validation_status": "VERIFIED", "validation_error": "", "trainable": True}
    except (ValueError, TypeError, KeyError, IndexError):
        return {"validation_status": "INVALID", "validation_error": "PT_PROBE_OUTPUT_INVALID", "trainable": False}


def asset_selection(data_dir: Path, asset_id: str) -> dict | None:
    row = get_asset(data_dir, asset_id)
    if not row or row.get("validation_status") != "VERIFIED" or row.get("trainable") is not True:
        return None
    path = Path(str(row.get("path") or ""))
    if not path.is_file() or path.stat().st_size != row.get("size_bytes"):
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return row if digest.hexdigest() == row.get("sha256") else None
