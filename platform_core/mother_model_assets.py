"""Durable, content-addressed mother-model metadata; never unpickle in Web.

An uploaded checkpoint is *not* training evidence. Verification is performed by
the dedicated probe only when an actual operating-system sandbox is present.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

from filelock import FileLock


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


def verify_checkpoint_in_sandbox(path: Path, *, python_executable: str | None = None) -> dict:
    """Load YOLO solely in a no-network, read-only, unprivileged bubblewrap guest.

    Absence of working namespaces is an explicit stop, never a fallback to
    ``torch.load(weights_only=False)`` in the control service.
    """
    valid, reason = _check_torch_container(path)
    if not valid:
        return {"validation_status": "INVALID", "validation_error": reason, "trainable": False}
    wrapper = shutil.which("bwrap")
    if not wrapper or sys.platform != "linux":
        return {"validation_status": "SANDBOX_UNAVAILABLE", "validation_error": "PT_SANDBOX_NOT_CONFIGURED", "trainable": False}
    python = Path(python_executable or sys.executable).resolve()
    # All parent directories are read-only. Hide users' data and writable
    # runtime paths; expose exactly one checkpoint under an inert mount name.
    if any(str(python).startswith(prefix) for prefix in ("/root/", "/home/", "/data/", "/workspace/")):
        return {"validation_status": "SANDBOX_UNAVAILABLE", "validation_error": "PT_PYTHON_RUNTIME_NOT_ISOLATABLE", "trainable": False}
    probe = '''import json,sys
from ultralytics import YOLO
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
        completed = subprocess.run(command, capture_output=True, text=True, timeout=35, env={})
    except (OSError, subprocess.TimeoutExpired):
        return {"validation_status": "SANDBOX_UNAVAILABLE", "validation_error": "PT_SANDBOX_NOT_EXECUTABLE", "trainable": False}
    if completed.returncode:
        error = "PT_SANDBOX_NOT_EXECUTABLE" if "namespace" in completed.stderr.lower() else "PT_MODEL_LOAD_FAILED"
        return {"validation_status": "SANDBOX_UNAVAILABLE" if error.endswith("NOT_EXECUTABLE") else "INVALID",
                "validation_error": error, "trainable": False}
    lines = [line.removeprefix("MODEL_PROBE_JSON:") for line in completed.stdout.splitlines() if line.startswith("MODEL_PROBE_JSON:")]
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
