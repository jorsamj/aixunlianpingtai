import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from platform_core.training_devices import resolve_direct_training_assignment

BASE_DIR = Path(__file__).resolve().parent
REMOTE_DIR = Path(os.environ.get("MC_REMOTE_DATA_DIR") or (BASE_DIR / "remote_data")).expanduser().resolve()
JOBS_DIR = REMOTE_DIR / "jobs"
CONFIG_FILE = REMOTE_DIR / "server_config.json"
PROCESS_REGISTRY: Dict[str, subprocess.Popen] = {}
TRAIN_PYTHON = os.environ.get("MC_REMOTE_TRAIN_PYTHON", "").strip() or sys.executable


def safe_extract_zip(zf: zipfile.ZipFile, dst: Path):
    root = dst.resolve()
    for member in zf.infolist():
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}":
            raise HTTPException(status_code=400, detail=f"ZIP 包含不安全路径：{member.filename}")
        target = (dst / member.filename).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"ZIP 包含越界路径：{member.filename}")
    zf.extractall(dst)


def training_runtime_info():
    code = (
        "import json, torch, torchvision, ultralytics; "
        "print(json.dumps({'torch':torch.__version__,'torchvision':torchvision.__version__,"
        "'ultralytics':ultralytics.__version__,'cuda':bool(torch.cuda.is_available()),"
        "'cuda_devices':int(torch.cuda.device_count())}))"
    )
    try:
        cp = subprocess.run([TRAIN_PYTHON, "-c", code], capture_output=True, text=True, errors="replace", timeout=30)
        if cp.returncode == 0:
            return {"ok": True, "python": TRAIN_PYTHON, **json.loads((cp.stdout or "{}").strip().splitlines()[-1])}
        return {"ok": False, "python": TRAIN_PYTHON, "error": (cp.stderr or cp.stdout or "未知错误").strip()[-2000:]}
    except Exception as e:
        return {"ok": False, "python": TRAIN_PYTHON, "error": str(e)}

REMOTE_DIR.mkdir(exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)
if not CONFIG_FILE.exists():
    CONFIG_FILE.write_text(json.dumps({"api_key": ""}, ensure_ascii=False, indent=2), encoding="utf-8")

app = FastAPI(title="畅联云算法远程训练服务器", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# The remote job record is shared with train_worker (inner record) and with the
# central platform's job writers. It uses the same one lock identity and the same
# whole-file atomic replacement as ``app._write_job_json`` /
# ``deployment_worker.update``: ``<job.json>.lock`` + read-under-lock -> mutate ->
# os.replace. Every remote write below goes through these helpers so a progress,
# cancellation or report fact can never be torn or silently dropped.
JOB_RECORD_IO_DEADLINE_SECONDS = 15.0
CANCELLATION_STATUSES = frozenset({"stopped", "cancelled", "canceled", "cancelling"})
TERMINAL_JOB_STATUSES = CANCELLATION_STATUSES | frozenset({
    "done", "completed", "finished", "failed",
})
_SYNCED_INNER_FIELDS = frozenset({
    "status", "message", "finished_at", "models", "run_dir", "updated_at",
    "training_report", "training_outcome", "gate_events",
})


def _filelock_module():
    """Lazy import: a remote install without filelock must never write unlocked."""
    try:
        import filelock
    except ImportError as error:  # pragma: no cover - deployment guard
        raise HTTPException(
            status_code=503,
            detail="远程服务器缺少 filelock 依赖，拒绝对任务记录做无锁写入",
        ) from error
    return filelock


def _job_record_lock(job_file: Path):
    """One effective lock for the shared job.json (same suffix as the platform)."""
    return _filelock_module().FileLock(
        str(job_file) + ".lock", timeout=30, thread_local=False
    )


def _read_job_record(job_file: Path, *, strict: bool = True) -> Dict[str, Any]:
    """Read a job record, tolerating transient Windows sharing denials.

    ``strict`` writers never degrade an unreadable/corrupt record to an empty
    document (that would drop fields another owner set); callers that only
    project a nested record may read leniently.
    """
    deadline = time.monotonic() + JOB_RECORD_IO_DEADLINE_SECONDS
    while True:
        try:
            raw = job_file.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return {}
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        if strict:
            raise HTTPException(status_code=503, detail="任务记录损坏，拒绝覆盖已有证据")
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_write_job_record(job_file: Path, value: Dict[str, Any]) -> None:
    job_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=job_file.parent, prefix=f".{job_file.name}.", suffix=".tmp"
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            descriptor = -1
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + JOB_RECORD_IO_DEADLINE_SECONDS
        delay = 0.005
        while True:
            try:
                os.replace(temporary, job_file)
                break
            except PermissionError:
                # A reader may briefly hold the record open; a persistent
                # denial is raised rather than reported as a successful write.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(delay)
                delay = min(0.2, delay * 2)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _update_job_record(
    job_file: Path,
    mutate: Callable[[Dict[str, Any]], None],
    *,
    create: bool = True,
) -> Dict[str, Any]:
    """Merge into the latest on-disk record under the shared lock, then replace atomically."""
    timeout_error = _filelock_module().Timeout

    if create:
        job_file.parent.mkdir(parents=True, exist_ok=True)
    elif not job_file.parent.is_dir():
        # The lock file itself needs an existing directory; a missing job dir
        # means there is no record to update (never recreate a removed job).
        return {}
    try:
        with _job_record_lock(job_file):
            if not create and not job_file.exists():
                return {}
            job = _read_job_record(job_file)
            mutate(job)
            _atomic_write_job_record(job_file, job)
            return job
    except timeout_error as error:
        raise HTTPException(
            status_code=503, detail="任务记录正在被其他写入者更新，请稍后重试"
        ) from error


def _transition_to_running(job: Dict[str, Any]) -> None:
    """Start transition that never resurrects a job already stopped by the user."""
    persisted = str(job.get("status") or "").strip().lower()
    if persisted in CANCELLATION_STATUSES:
        print(
            f"[job-record] start superseded by persisted status={persisted!r} ({job.get('id')})",
            file=sys.stderr,
            flush=True,
        )
        return
    job.update(status="running", message="训练中", updated_at=now_iso())


def check_key(x_api_key: str = ""):
    cfg = read_json(CONFIG_FILE, {"api_key": ""})
    need = cfg.get("api_key") or ""
    if need and x_api_key != need:
        raise HTTPException(status_code=401, detail="API Key 不正确")


def find_data_yaml(dataset_dir: Path) -> Path:
    candidates = list(dataset_dir.rglob("data.yaml")) + list(dataset_dir.rglob("*.yaml")) + list(dataset_dir.rglob("*.yml"))
    if not candidates:
        raise HTTPException(status_code=400, detail="数据集中没有找到 data.yaml")
    return candidates[0]


@app.get("/api/remote/health")
def health(x_api_key: str = Header(default="")):
    check_key(x_api_key)
    models = []
    for p in list(BASE_DIR.glob("*.pt")) + list((BASE_DIR / "models").glob("*.pt")) if (BASE_DIR / "models").exists() else list(BASE_DIR.glob("*.pt")):
        try:
            models.append({"label": p.name, "value": str(p), "framework": "ultralytics", "source": "server_file"})
        except Exception:
            pass
    for name in ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt"]:
        if not any(m.get("label") == name for m in models):
            models.append({"label": name, "value": name, "framework": "ultralytics", "source": "official"})
    algorithms = [
        {"key":"yolo11n_det","name":"YOLO11n 目标检测","framework":"ultralytics","base_model":"yolo11n.pt","default_epochs":30,"default_imgsz":640,"default_batch":4},
        {"key":"yolo11s_det","name":"YOLO11s 目标检测","framework":"ultralytics","base_model":"yolo11s.pt","default_epochs":50,"default_imgsz":640,"default_batch":4},
        {"key":"yolo11m_det","name":"YOLO11m 目标检测","framework":"ultralytics","base_model":"yolo11m.pt","default_epochs":80,"default_imgsz":640,"default_batch":2},
    ]
    rt = training_runtime_info()
    return {"ok": bool(rt.get("ok")), "time": now_iso(), "server": "mc-yolo-remote-trainer", "base_dir": str(BASE_DIR), "framework": "ultralytics", "training_runtime": rt, "algorithms": algorithms, "base_models": models}


@app.post("/api/remote/train")
async def remote_train(
    dataset_zip: UploadFile = File(...),
    model_file: Optional[UploadFile] = File(default=None),
    model: str = Form("yolo11n.pt"),
    epochs: int = Form(50), imgsz: int = Form(640), batch: int = Form(8), device: str = Form("0"),
    run_name: str = Form("remote_train"),
    patience: int = Form(100), workers: int = Form(0), optimizer: str = Form("auto"),
    lr0: float = Form(0.01), lrf: float = Form(0.01), weight_decay: float = Form(0.0005),
    close_mosaic: int = Form(10), mosaic: float = Form(1.0), cache: str = Form("False"),
    single_cls: str = Form("false"), pretrained: str = Form("true"), rect: str = Form("false"),
    amp: str = Form("true"), cos_lr: str = Form("false"), freeze: int = Form(0),
    eval_interval: int = Form(0), eval_metric: str = Form("map50"),
    continue_threshold: float = Form(0.0), stop_threshold: float = Form(0.0), val_max_samples: int = Form(0),
    x_api_key: str = Header(default=""),
):
    check_key(x_api_key)
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    dataset_dir = job_dir / "dataset"
    job_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    zip_path = job_dir / "dataset.zip"
    zip_path.write_bytes(await dataset_zip.read())
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extract_zip(zf, dataset_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"数据集解压失败：{e}")
    rt = training_runtime_info()
    if not rt.get("ok"):
        raise HTTPException(status_code=400, detail="远程训练 Python 不可用：" + str(rt.get("error") or "未知错误"))
    try:
        requested_device, assigned_device = resolve_direct_training_assignment(
            device,
            cuda_available=bool(rt.get("cuda")),
            cuda_devices=int(rt.get("cuda_devices") or 0),
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"训练设备不可用：{error}") from error
    if model_file is not None and model_file.filename:
        model_dir = job_dir / "input_model"
        model_dir.mkdir(exist_ok=True)
        model_name = Path(model_file.filename).name
        if not model_name.lower().endswith('.pt'):
            raise HTTPException(status_code=400, detail="上传的训练基础模型必须是 .pt")
        model_path = model_dir / model_name
        model_path.write_bytes(await model_file.read())
        model = str(model_path)
    data_yaml = find_data_yaml(dataset_dir)
    job = {
        "id": job_id,
        "status": "queued",
        "message": "等待启动",
        "model": model,
        "epochs": int(epochs),
        "imgsz": int(imgsz),
        "batch": int(batch),
        "device": assigned_device,
        "requested_device": requested_device,
        "assigned_device": assigned_device,
        "run_name": run_name,
        "advanced_params": {"patience":patience,"workers":workers,"optimizer":optimizer,"lr0":lr0,"lrf":lrf,"weight_decay":weight_decay,"close_mosaic":close_mosaic,"mosaic":mosaic,"cache":cache,"single_cls":single_cls,"pretrained":pretrained,"rect":rect,"amp":amp,"cos_lr":cos_lr,"freeze":freeze},
        "quality_gate": {"eval_interval":int(eval_interval),"metric":eval_metric,"continue_threshold":float(continue_threshold),"stop_threshold":float(stop_threshold),"stage_eval_samples":int(val_max_samples)},
        "training_runtime": rt,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "models": [],
    }
    _update_job_record(job_dir / "job.json", lambda record: record.update(job))
    log_file = job_dir / "train.log"
    cmd = [
        TRAIN_PYTHON,
        str(BASE_DIR / "train_worker.py"),
        "--project-dir", str(job_dir),
        "--data", str(data_yaml),
        "--model", model,
        "--epochs", str(max(1, int(epochs))),
        "--imgsz", str(max(128, int(imgsz))),
        "--batch", str(int(batch)),
        "--device", assigned_device,
        "--assigned-device", assigned_device,
        "--requested-device", requested_device,
        "--job-id", job_id, "--run-name", run_name,
        "--patience", str(patience), "--workers", str(workers), "--optimizer", optimizer or "auto",
        "--lr0", str(lr0), "--lrf", str(lrf), "--weight-decay", str(weight_decay),
        "--close-mosaic", str(close_mosaic), "--mosaic", str(mosaic), "--cache", str(cache),
        "--single-cls", str(single_cls), "--pretrained", str(pretrained), "--rect", str(rect),
        "--amp", str(amp), "--cos-lr", str(cos_lr), "--freeze", str(freeze),
        "--val-max-samples", str(int(val_max_samples)), "--eval-interval", str(int(eval_interval)), "--eval-metric", str(eval_metric or "map50"),
        "--continue-threshold", str(float(continue_threshold)), "--stop-threshold", str(float(stop_threshold)), "--ai-intervention", "false",
    ]
    # train_worker expects project_dir/jobs/job_id/job.json
    inner_job_dir = job_dir / "jobs" / job_id
    _update_job_record(inner_job_dir / "job.json", lambda record: record.update(job))
    with log_file.open("ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(BASE_DIR))
    PROCESS_REGISTRY[job_id] = proc
    # A stop arriving between launch and this write must stay stopped: the
    # transition only applies when the persisted record is still queued.
    _update_job_record(job_dir / "job.json", _transition_to_running)
    return {"ok": True, "job_id": job_id, "status": "running"}


def sync_job(job_id: str) -> Dict[str, Any]:
    job_dir = JOBS_DIR / job_id
    job_file = job_dir / "job.json"
    if not job_file.exists():
        raise HTTPException(status_code=404, detail="任务不存在")
    # The Worker owns the inner record; project its facts read-only, then merge
    # them into the outer record under the outer record's lock so a concurrent
    # pause/resume/stop can never be overwritten by this stale snapshot.
    inner_job = _read_job_record(job_dir / "jobs" / job_id / "job.json", strict=False)

    def merge(record: Dict[str, Any]) -> None:
        if inner_job:
            fields = {k: v for k, v in inner_job.items() if k in _SYNCED_INNER_FIELDS}
            persisted = str(record.get("status") or "").strip().lower()
            projected = str(fields.get("status") or "").strip().lower()
            if persisted == "paused":
                fields.pop("status", None)
                fields.pop("message", None)
            elif persisted in CANCELLATION_STATUSES and projected not in TERMINAL_JOB_STATUSES:
                # A late worker progress write must not revive a stopped job.
                fields.pop("status", None)
                fields.pop("message", None)
            record.update(fields)
        # remote API model names are returned as file names only
        models_dir = job_dir / "models"
        if models_dir.exists():
            record["models"] = [
                x.name for x in models_dir.iterdir()
                if x.is_file() and x.suffix.lower() in {".pt", ".onnx", ".engine"}
            ]

    job = _update_job_record(job_file, merge, create=False)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    proc = PROCESS_REGISTRY.get(job_id)
    if proc and proc.poll() is not None:
        PROCESS_REGISTRY.pop(job_id, None)
    return job


@app.get("/api/remote/jobs/{job_id}")
def remote_job(job_id: str, x_api_key: str = Header(default="")):
    check_key(x_api_key)
    return sync_job(job_id)


@app.get("/api/remote/jobs/{job_id}/log", response_class=PlainTextResponse)
def remote_log(job_id: str, x_api_key: str = Header(default="")):
    check_key(x_api_key)
    log_file = JOBS_DIR / job_id / "train.log"
    if not log_file.exists():
        return "暂无日志"
    return log_file.read_text(encoding="utf-8", errors="ignore")[-100000:]



def _remote_suspend_tree(job_id: str, resume: bool=False):
    proc=PROCESS_REGISTRY.get(job_id)
    if not proc or proc.poll() is not None: raise HTTPException(status_code=400,detail="训练进程不存在")
    try:
        import psutil
        root=psutil.Process(proc.pid); children=root.children(recursive=True)
        for x in children+[root]:
            try: x.resume() if resume else x.suspend()
            except Exception: pass
    except Exception as e:
        raise HTTPException(status_code=500,detail=f"暂停/继续进程失败：{e}")


@app.post("/api/remote/jobs/{job_id}/pause")
def pause_remote_job(job_id: str, x_api_key: str = Header(default="")):
    check_key(x_api_key)
    job_dir = JOBS_DIR / job_id

    def pause(record: Dict[str, Any]) -> None:
        # Status check, process suspension and the record write share one
        # critical section: a stop cannot land between them and be overwritten.
        if record.get("status") != "running":
            raise HTTPException(status_code=400, detail="只有训练中的任务可以暂停")
        _remote_suspend_tree(job_id, False)
        record.update(status="paused", message="训练已暂停", paused_at=now_iso(), updated_at=now_iso())

    job = _update_job_record(job_dir / "job.json", pause, create=False)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.post("/api/remote/jobs/{job_id}/resume")
def resume_remote_job(job_id: str, x_api_key: str = Header(default="")):
    check_key(x_api_key)
    job_dir = JOBS_DIR / job_id

    def resume(record: Dict[str, Any]) -> None:
        if record.get("status") != "paused":
            raise HTTPException(status_code=400, detail="只有已暂停任务可以继续")
        _remote_suspend_tree(job_id, True)
        record.update(status="running", message="训练已继续", resumed_at=now_iso(), updated_at=now_iso())

    job = _update_job_record(job_dir / "job.json", resume, create=False)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.post("/api/remote/jobs/{job_id}/stop")
def stop_remote_job(job_id: str, x_api_key: str = Header(default="")):
    check_key(x_api_key)
    proc = PROCESS_REGISTRY.get(job_id)
    if proc:
        proc.terminate(); time.sleep(1)
        if proc.poll() is None:
            proc.kill()
        PROCESS_REGISTRY.pop(job_id, None)
    job_dir = JOBS_DIR / job_id

    def stop(record: Dict[str, Any]) -> None:
        record.update({"status": "stopped", "message": "用户停止",
                       "finished_at": now_iso(), "updated_at": now_iso()})

    # Merge into each existing record under its own lock; never recreate one and
    # never write back a snapshot that predates the Worker's latest progress.
    for jf in (job_dir / "job.json", job_dir / "jobs" / job_id / "job.json"):
        _update_job_record(jf, stop, create=False)
    return {"ok": True}


@app.get("/api/remote/jobs/{job_id}/models/{model_name}")
def download_remote_model(job_id: str, model_name: str, x_api_key: str = Header(default="")):
    check_key(x_api_key)
    path = JOBS_DIR / job_id / "models" / Path(model_name).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="模型不存在")
    return FileResponse(path, filename=path.name)


class ConfigReq(BaseModel):
    api_key: str = ""


@app.post("/api/remote/config")
def set_config(payload: ConfigReq):
    write_json(CONFIG_FILE, {"api_key": payload.api_key or ""})
    return {"ok": True, "api_key_enabled": bool(payload.api_key)}
