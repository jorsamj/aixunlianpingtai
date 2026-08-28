import json
import base64
import hashlib
import math
import re
import os
import shutil
import subprocess
import sys
import time
import threading
import uuid
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image, ImageDraw

from platform_core.annotations import annotation_summary, atomic_write_json, normalize_boxes
from platform_core.algorithms import (
    choose_iteration_base,
    create_algorithm as create_algorithm_asset,
    delete_algorithm as delete_algorithm_asset,
    list_algorithms as list_algorithm_assets,
    save_algorithms as save_algorithm_assets,
    update_algorithm as update_algorithm_asset,
)
from platform_core import auto_label as auto_label_core
from platform_core.bootstrap import choose_project, choose_requested_project
from platform_core.config import choose_data_dir
from platform_core.errors import PlatformError, error_body
from platform_core.labels import active_label_options
from platform_core.materials import delete_material_files, initial_processing_status, mark_ready
from platform_core.prompts import render_prompt, template_version_id, version_template
from platform_core.quality import compute_quality
from platform_core.reports import build_algorithm_report, build_version_report
from platform_core.secrets import KeyringSecretStore, secret_ref
from platform_core.snapshots import build_snapshot, persist_snapshot

BASE_DIR = Path(__file__).resolve().parent
def _read_app_version() -> str:
    env_v = os.environ.get("MC_PLATFORM_VERSION", "").strip()
    if env_v:
        return env_v
    try:
        v = (BASE_DIR / "VERSION.txt").read_text(encoding="utf-8", errors="ignore").strip()
        if v:
            return v
    except Exception:
        pass
    return "42.14.0"

APP_VERSION = _read_app_version()
STATIC_DIR = BASE_DIR / "static"
PROCESS_REGISTRY: Dict[str, subprocess.Popen] = {}

# v34: 持久化数据目录。默认放到用户目录，避免页面刷新、重启、升级版本后素材/数据丢失。
# 如需强制使用当前程序目录下的 data，可在 start.bat 中设置 MC_TRAIN_DATA_DIR=%~dp0data。
def _default_data_dir() -> Path:
    custom = os.environ.get("MC_TRAIN_DATA_DIR")
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        candidates = [
            root / "XJAlgo" / "data",
            root / "XiaojiangAlgorithmTrain" / "data",
            BASE_DIR / "data",
        ]
    else:
        candidates = [BASE_DIR / "data"]
    return choose_data_dir(Path(custom) if custom else None, candidates)

DATA_DIR = _default_data_dir()

PROJECTS_FILE = DATA_DIR / "projects.json"
SERVERS_FILE = DATA_DIR / "train_servers.json"
LOCAL_MODELS_FILE = DATA_DIR / "local_models_scan.json"
ULTRALYTICS_ENV_FILE = DATA_DIR / "ultralytics_env.json"
PADDLE_ENV_FILE = DATA_DIR / "paddle_env.json"
PRELABEL_SERVICES_FILE = DATA_DIR / "prelabel_services.json"
MODEL_CONFIGS_FILE = DATA_DIR / "model_configs.json"
PROMPT_LIBRARY_FILE = DATA_DIR / "prompt_library.json"
MODEL_SECRET_STORE: Any = None

DATA_DIR.mkdir(parents=True, exist_ok=True)
if not PROJECTS_FILE.exists():
    PROJECTS_FILE.write_text("[]", encoding="utf-8")
if not SERVERS_FILE.exists():
    SERVERS_FILE.write_text("[]", encoding="utf-8")
if not LOCAL_MODELS_FILE.exists():
    LOCAL_MODELS_FILE.write_text("[]", encoding="utf-8")
if not ULTRALYTICS_ENV_FILE.exists():
    ULTRALYTICS_ENV_FILE.write_text("{}", encoding="utf-8")
if not PADDLE_ENV_FILE.exists():
    PADDLE_ENV_FILE.write_text("{}", encoding="utf-8")
if not PRELABEL_SERVICES_FILE.exists():
    PRELABEL_SERVICES_FILE.write_text("[]", encoding="utf-8")
if not MODEL_CONFIGS_FILE.exists():
    MODEL_CONFIGS_FILE.write_text("[]", encoding="utf-8")
if not PROMPT_LIBRARY_FILE.exists():
    PROMPT_LIBRARY_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="畅联云算法训练", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")


_HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

_HTTP_ERROR_SOLUTIONS = {
    400: "请检查输入内容后重试。",
    401: "请重新登录或检查访问凭据。",
    403: "请确认当前账号具备操作权限。",
    404: "请刷新列表并确认目标仍然存在。",
    409: "请刷新页面，确认当前状态后重试。",
    422: "请检查必填项和字段格式。",
    503: "请稍后重试；若持续失败，请检查对应服务状态。",
}


@app.exception_handler(PlatformError)
async def platform_error_handler(_request: Request, exc: PlatformError):
    return JSONResponse(status_code=exc.status_code, content=error_body(exc))


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        message = str(exc.detail.get("message") or "操作失败")
        detail = json.dumps(exc.detail, ensure_ascii=False)
    else:
        message = str(exc.detail or "操作失败")
        detail = message
    error = PlatformError(
        code=_HTTP_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}"),
        message=message,
        detail=detail,
        solution=_HTTP_ERROR_SOLUTIONS.get(exc.status_code, "请稍后重试或查看服务日志。"),
        status_code=exc.status_code,
    )
    return JSONResponse(status_code=exc.status_code, content=error_body(error), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    error = PlatformError(
        code="VALIDATION_ERROR",
        message="提交的数据不完整或格式不正确",
        detail=json.dumps(exc.errors(), ensure_ascii=False),
        solution="请检查必填项和字段格式。",
        status_code=422,
    )
    return JSONResponse(status_code=422, content=error_body(error))

@app.get("/api/system/version")
def system_version():
    return {
        "version": APP_VERSION,
        "name": "畅联云算法训练",
        "data_dir": str(DATA_DIR),
        "base_dir": str(BASE_DIR),
        "persistent": True,
    }

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
LABEL_EXTS = {".txt"}
MODEL_EXTS = {".pt", ".pth", ".onnx", ".engine", ".rknn", ".bmodel", ".om", ".pdparams", ".pdmodel", ".pdiparams"}
MODEL_CONFIG_NAMES = {"infer_cfg.yml", "infer_cfg.yaml", "inference.yml", "inference.yaml", "deploy.yml", "deploy.yaml", "model.yml", "model.yaml"}
PADDLEX_SERVICE_FILE_NAMES = {"human_service.py", "download_model.py", "service.py", "app.py"}
SKIP_SCAN_DIRS = {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)", "appdata", "node_modules", ".git", ".venv", "venv", "__pycache__"}


TRAINING_CATALOG: Dict[str, Any] = {
    "frameworks": [
        {
            "key": "ultralytics",
            "name": "Ultralytics YOLO",
            "status": "ready",
            "description": "当前可直接训练，适合本机快速跑通。基础模型使用 .pt。",
        },
        {
            "key": "paddle",
            "name": "飞桨 PaddleX / PaddleDetection",
            "status": "configured",
            "description": "平台可导出 COCO 数据集并按预置命令模板执行训练；需要本机已安装 PaddleDetection/PaddleX。",
        },
    ],
    "algorithms": [
        {
            "key": "yolo11n_det",
            "framework": "ultralytics",
            "name": "YOLO11n 目标检测",
            "short_name": "YOLO11n",
            "task": "detect",
            "base_model": "yolo11n.pt",
            "recommended": True,
            "default_epochs": 30,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "最轻量，适合 CPU/普通笔记本先跑通安全帽、人员、烟火等目标检测流程。",
        },
        {
            "key": "yolo11s_det",
            "framework": "ultralytics",
            "name": "YOLO11s 目标检测",
            "short_name": "YOLO11s",
            "task": "detect",
            "base_model": "yolo11s.pt",
            "recommended": False,
            "default_epochs": 50,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "比 n 版更准一些，建议有 NVIDIA 显卡或训练服务器时使用。",
        },
        {
            "key": "yolo11m_det",
            "framework": "ultralytics",
            "name": "YOLO11m 目标检测",
            "short_name": "YOLO11m",
            "task": "detect",
            "base_model": "yolo11m.pt",
            "recommended": False,
            "default_epochs": 80,
            "default_imgsz": 640,
            "default_batch": 2,
            "description": "中等模型，精度更高但资源占用更大，本机 CPU 不建议首选。",
        },
        {
            "key": "paddledet_ppyoloe_s",
            "framework": "paddle",
            "name": "PP-YOLOE-S 目标检测",
            "short_name": "PP-YOLOE-S",
            "task": "detect",
            "base_model": "PP-YOLOE-S",
            "recommended": True,
            "default_epochs": 30,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "飞桨轻量目标检测路线，适合后续闭源/国产化项目验证。需要本机配置 PaddleDetection。",
            "command_template": "{python} {paddledet_dir}\\tools\\train.py -c {paddledet_dir}\\configs\\ppyoloe\\ppyoloe_crn_s_300e_coco.yml -o TrainDataset.dataset_dir={dataset_dir} TrainDataset.anno_path={train_json} EvalDataset.dataset_dir={dataset_dir} EvalDataset.anno_path={val_json} epoch={epochs} batch_size={batch} save_dir={run_dir}",
        },
        {
            "key": "paddledet_ppyoloe_plus_s",
            "framework": "paddle",
            "name": "PP-YOLOE+ S 目标检测",
            "short_name": "PP-YOLOE+ S",
            "task": "detect",
            "base_model": "PP-YOLOE_plus-S",
            "recommended": False,
            "default_epochs": 50,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "飞桨 PP-YOLOE+ 小模型，适合正式效果对比。需要本机配置 PaddleDetection。",
            "command_template": "{python} {paddledet_dir}\\tools\\train.py -c {paddledet_dir}\\configs\\ppyoloe\\ppyoloe_plus_crn_s_80e_coco.yml -o TrainDataset.dataset_dir={dataset_dir} TrainDataset.anno_path={train_json} EvalDataset.dataset_dir={dataset_dir} EvalDataset.anno_path={val_json} epoch={epochs} batch_size={batch} save_dir={run_dir}",
        },
        {
            "key": "paddlex_human_pretrain",
            "framework": "paddle",
            "name": "PaddleX PP-YOLOE-S_human 人员检测源",
            "short_name": "PP-YOLOE-S_human",
            "task": "detect",
            "base_model": "PP-YOLOE-S_human",
            "recommended": False,
            "default_epochs": 30,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "更适合先作为人员检测预标注源；如要训练，需要本机具备对应 PaddleX/PaddleDetection 训练能力。",
            "command_template": "{python} {paddledet_dir}\\tools\\train.py -c {paddledet_dir}\\configs\\ppyoloe\\ppyoloe_crn_s_300e_coco.yml -o TrainDataset.dataset_dir={dataset_dir} TrainDataset.anno_path={train_json} EvalDataset.dataset_dir={dataset_dir} EvalDataset.anno_path={val_json} epoch={epochs} batch_size={batch} save_dir={run_dir}",
        },
    ],
}


def get_algorithm_config(key: str) -> Optional[Dict[str, Any]]:
    for item in TRAINING_CATALOG["algorithms"]:
        if item["key"] == key:
            return item
    return None


def _norm_path(path: Any) -> str:
    return str(path or "").strip().strip('"')


def _safe_key(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", text.replace("\\", "/"))
    text = re.sub(r"_+", "_", text).strip("_").lower()
    return text[:160] or uuid.uuid4().hex[:8]


def _parse_paddle_config_name(config_path: Path, paddledet_dir: Path) -> Dict[str, Any]:
    """把 PaddleDetection 的 yml 配置识别成训练页能理解的算法项。"""
    rel = str(config_path.relative_to(paddledet_dir)).replace("\\", "/") if str(config_path).startswith(str(paddledet_dir)) else config_path.name
    parts = [x.lower() for x in Path(rel).parts]
    stem = config_path.stem.lower()
    rel_lower = rel.lower()

    family = "PaddleDetection"
    family_key = "paddledet"
    if "picodet" in rel_lower:
        family, family_key = "PicoDet", "picodet"
    elif "ppyoloe" in rel_lower:
        family, family_key = ("PP-YOLOE+" if "plus" in stem or "+" in stem else "PP-YOLOE"), "ppyoloe"
    elif "ppyolo" in rel_lower:
        family, family_key = "PP-YOLO", "ppyolo"
    elif "rtdetr" in rel_lower or "rt_detr" in rel_lower:
        family, family_key = "RT-DETR", "rtdetr"
    elif "yolov3" in rel_lower:
        family, family_key = "YOLOv3", "yolov3"
    elif "faster_rcnn" in rel_lower:
        family, family_key = "Faster R-CNN", "faster_rcnn"
    elif "cascade_rcnn" in rel_lower:
        family, family_key = "Cascade R-CNN", "cascade_rcnn"
    elif "mask_rcnn" in rel_lower:
        family, family_key = "Mask R-CNN", "mask_rcnn"
    elif "ssd" in rel_lower:
        family, family_key = "SSD", "ssd"
    elif "retinanet" in rel_lower:
        family, family_key = "RetinaNet", "retinanet"
    elif "fcos" in rel_lower:
        family, family_key = "FCOS", "fcos"
    elif "centernet" in rel_lower:
        family, family_key = "CenterNet", "centernet"
    elif "detr" in rel_lower:
        family, family_key = "DETR", "detr"

    size = ""
    # 常见 xs/s/m/l/x 规格
    m = re.search(r"(?:^|_)(xs|s|m|l|x)(?:_|$)", stem)
    if m:
        size = m.group(1).upper()
    else:
        m = re.search(r"(?:^|_)(tiny|nano|small|large)(?:_|$)", stem)
        if m:
            size = m.group(1).upper()
        else:
            m = re.search(r"(?:^|_)(r18|r34|r50|r101|r152)(?:_|$)", stem)
            if m:
                size = m.group(1).upper()

    img = ""
    m = re.search(r"(?:^|_)(320|416|512|608|640|800|1024|1280)(?:_|$)", stem)
    if m:
        img = m.group(1)

    dataset = "COCO" if "coco" in stem else ("VOC" if "voc" in stem else "")
    backbone = "LCNet" if "lcnet" in stem else ("CRN" if "crn" in stem else ("ResNet" if "resnet" in stem or re.search(r"r\d+", stem) else ""))

    title = family
    if size:
        title += f" {size}"
    if img:
        title += f" {img}"
    title += " 目标检测"
    if backbone:
        title += f" / {backbone}"

    default_imgsz = int(img) if img else 640
    default_batch = 4
    # CPU 环境下优先保守；大模型默认 batch 小一点
    if size in {"L", "X", "R101", "R152"} or family_key in {"rtdetr", "faster_rcnn", "cascade_rcnn", "mask_rcnn"}:
        default_batch = 1
    elif size in {"M", "R50"}:
        default_batch = 2

    rel_key = _safe_key(rel)
    config_path_str = str(config_path)
    # PaddleDetection CLI 常见 COCO 覆盖项。数据集由平台导出成 COCO。
    # 注意：部分算法的配置层级不同，命令失败时可在日志中看到明确原因，后续可按算法单独修正模板。
    cmd = (
        '"{python}" "{paddledet_dir}\\tools\\train.py" {paddle_eval_option} '
        f'-c "{config_path_str}" '
        '-o TrainDataset.dataset_dir="{dataset_dir}" '
        'TrainDataset.anno_path="{train_json}" '
        'EvalDataset.dataset_dir="{dataset_dir}" '
        'EvalDataset.anno_path="{val_json}" '
        'TrainDataset.image_dir="" EvalDataset.image_dir="" '
        'epoch={epochs} worker_num=0 '
        'TrainReader.batch_size={batch} EvalReader.batch_size={batch} '
        '{paddle_class_options} {paddle_lr_options} '
        'use_gpu=False save_dir="{run_dir}" {pretrain_option}'
    )
    return {
        "key": f"paddledet_{rel_key}",
        "framework": "paddle",
        "engine": "PaddleDetection",
        "name": title,
        "short_name": title.replace(" 目标检测", ""),
        "task": "detect",
        "family": family,
        "family_key": family_key,
        "size": size,
        "imgsz": default_imgsz,
        "dataset": dataset,
        "backbone": backbone,
        "base_model": Path(config_path).name,
        "config_path": config_path_str,
        "config_relpath": rel,
        "recommended": family_key in {"picodet", "ppyoloe"} and (size in {"XS", "S", ""}),
        "default_epochs": 30,
        "default_imgsz": default_imgsz,
        "default_batch": default_batch,
        "description": f"从 PaddleDetection 配置文件自动识别：{rel}。训练时平台会导出 COCO 数据集并调用 tools/train.py。v26 支持在训练任务里动态开启/关闭 COCO 评估，默认关闭以避免小数据集类别映射中断；训练完成后可用检测台对比效果。",
        "command_template": cmd,
    }


def scan_paddledet_algorithms(paddledet_dir: str, max_items: int = 500) -> Dict[str, Any]:
    root = Path(_norm_path(paddledet_dir))
    if not root.exists():
        return {"ok": False, "items": [], "total": 0, "error": "PaddleDetection 目录不存在"}
    configs = root / "configs"
    if not configs.exists():
        return {"ok": False, "items": [], "total": 0, "error": "没有找到 configs 目录"}
    skip_dirs = {"_base_", "base", "application", "legacy_model", "runtime", "datasets", "common", "deploy"}
    skip_names = {"runtime.yml", "optimizer.yml", "reader.yml", "ppyolo_reader.yml", "ppyoloe_reader.yml", "picodet_reader.yml"}
    items: List[Dict[str, Any]] = []
    skipped = 0
    for fp in configs.rglob("*.yml"):
        try:
            rel_parts = [x.lower() for x in fp.relative_to(configs).parts[:-1]]
            name = fp.name.lower()
            if any(x in skip_dirs for x in rel_parts):
                skipped += 1
                continue
            if name in skip_names or name.startswith("_") or "reader" in name or "optimizer" in name or "runtime" in name or "_test" in name or name.startswith("test") or name in {"ppyolo_test.yml", "ppyoloe_test.yml"}:
                skipped += 1
                continue
            # README 配套、量化/蒸馏/部署配置先不直接作为“训练算法”展示
            if any(k in name for k in ["quant", "slim", "distill", "prune", "infer", "deploy"]):
                skipped += 1
                continue
            item = _parse_paddle_config_name(fp, root)
            items.append(item)
            if len(items) >= max_items:
                break
        except Exception:
            skipped += 1
    items.sort(key=lambda x: (
        0 if x.get("family_key") == "picodet" else 1 if x.get("family_key") == "ppyoloe" else 2,
        x.get("family", ""),
        x.get("default_batch", 99),
        x.get("default_imgsz", 9999),
        x.get("name", ""),
    ))
    families: Dict[str, int] = {}
    for it in items:
        families[it.get("family", "其他")] = families.get(it.get("family", "其他"), 0) + 1
    return {"ok": True, "items": items, "total": len(items), "families": families, "skipped": skipped, "configs_dir": str(configs)}


def scan_paddle_weights(paddledet_dir: str = "", extra_roots: Optional[List[str]] = None, max_items: int = 200) -> List[Dict[str, Any]]:
    roots: List[Path] = []
    for r in extra_roots or []:
        if r:
            roots.append(Path(_norm_path(r)))
    if paddledet_dir:
        pd = Path(_norm_path(paddledet_dir))
        roots.extend([pd / "output", pd / "pretrained", pd / "weights", pd.parent / "PaddleModels"])
    # 用户当前路径常用目录
    roots.extend([BASE_DIR.parent / "PaddleModels", BASE_DIR.parent / "models"])
    seen = set()
    items: List[Dict[str, Any]] = []
    for root in roots:
        if not root.exists() or str(root).lower() in seen:
            continue
        seen.add(str(root).lower())
        try:
            for fp in root.rglob("*.pdparams"):
                if fp.is_file() and fp.stat().st_size > 0:
                    items.append({
                        "label": f"飞桨权重：{fp.name}",
                        "value": str(fp),
                        "framework": "paddle",
                        "source": "local_pdparams",
                        "size_mb": round(fp.stat().st_size / 1024 / 1024, 2),
                    })
                    if len(items) >= max_items:
                        return items
        except Exception:
            continue
    return items


def get_paddle_algorithm_by_key(key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    # 先查固定目录，再查当前保存的 PaddleDetection 环境
    penv = get_active_paddle_env() if 'get_active_paddle_env' in globals() else {}
    scan = scan_paddledet_algorithms(penv.get("paddledet_dir", "")) if penv.get("paddledet_dir") else {"items": []}
    for item in scan.get("items", []):
        if item.get("key") == key:
            return item
    # 兜底静态目录
    for item in TRAINING_CATALOG["algorithms"]:
        if item.get("key") == key:
            return item
    return None


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt_value(value: Any) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(str(value)[:26], fmt)
        except Exception:
            pass
    return None


def _human_seconds(seconds: Any) -> str:
    try:
        seconds = int(max(0, float(seconds)))
    except Exception:
        return "-"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}小时{m}分"
    if m:
        return f"{m}分{s}秒"
    return f"{s}秒"


def _job_log_text(project_id: str, job_id: str, limit: int = 120000) -> str:
    f = project_dir(project_id) / "jobs" / job_id / "train.log"
    if not f.exists():
        return ""
    try:
        return f.read_text(encoding="utf-8", errors="ignore")[-limit:]
    except Exception:
        return ""


def _infer_epoch_from_log(log_text: str, total_epochs: int) -> int:
    if not log_text or not total_epochs:
        return 0
    cur = 0
    # Ultralytics 常见：1/30、2/30；只取分母等于训练轮次的值，避免 1/1 batch 被误判。
    for a, b in re.findall(r"(?<!\d)(\d{1,5})\s*/\s*(\d{1,5})(?!\d)", log_text):
        try:
            aa, bb = int(a), int(b)
            if bb == int(total_epochs) and 0 <= aa <= bb:
                cur = max(cur, aa)
        except Exception:
            pass
    # PaddleDetection 部分日志可能出现 epoch: 3 或 Epoch 3。
    for a in re.findall(r"(?:epoch|Epoch)[:=\s\[]+(\d{1,5})", log_text):
        try:
            aa = int(a)
            if 0 <= aa <= int(total_epochs):
                cur = max(cur, aa)
        except Exception:
            pass
    return cur



def _pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid or 0)
        if pid <= 0:
            return False
        import psutil
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _terminate_pid_tree(pid: Any) -> bool:
    try:
        import psutil
        proc = psutil.Process(int(pid))
        children = proc.children(recursive=True)
        for child in children:
            try: child.terminate()
            except Exception: pass
        try: proc.terminate()
        except Exception: pass
        _, alive = psutil.wait_procs(children + [proc], timeout=3)
        for item in alive:
            try: item.kill()
            except Exception: pass
        return True
    except Exception:
        return False


def enrich_job_runtime(project_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    if not job:
        return job
    job_id = job.get("id") or ""
    proc = PROCESS_REGISTRY.get(job_id) if job_id else None
    status = job.get("status") or "queued"
    if proc:
        code = proc.poll()
        if code is None and status in {"queued", "waiting", "pending"}:
            status = "running"
            job["status"] = "running"
            job["message"] = job.get("message") or "训练中"
            job.setdefault("started_at", job.get("updated_at") or now_iso())
        elif code is not None:
            PROCESS_REGISTRY.pop(job_id, None)
            # The worker writes its final artifact metadata immediately before exiting.
            # Re-read after poll() observes exit so a stale in-flight request cannot
            # overwrite that successful result with an inferred failure.
            persisted = read_json(project_dir(project_id) / "jobs" / job_id / "job.json", {})
            if persisted.get("status") in {"done", "finished", "completed", "failed", "stopped"}:
                job = persisted
                status = job.get("status") or status
            if status in {"queued", "running", "waiting", "pending"}:
                # 正常情况下 worker 会写 done/failed；如果服务刚好轮询到进程已退但文件未回写，则兜底。
                job["status"] = "done" if code == 0 else "failed"
                job["message"] = "训练完成" if code == 0 else f"训练进程退出码：{code}"
                job.setdefault("finished_at", now_iso())
    # 服务重启后 PROCESS_REGISTRY 会丢失，但 worker 可能仍在运行。使用持久化 pid 恢复状态判断。
    status = job.get("status") or status
    if not proc and job.get("target") != "remote" and status in {"queued", "running", "waiting", "pending"} and job.get("pid"):
        if _pid_alive(job.get("pid")):
            job["status"] = "running"
            status = "running"
            job["message"] = job.get("message") or "训练中"
        else:
            # 正常 worker 会在退出前把状态改为 done/failed；若仍是 running，说明异常退出。
            job["status"] = "failed"
            status = "failed"
            job["message"] = "训练进程已结束，但没有写入成功结果，请查看训练日志"
            job.setdefault("finished_at", now_iso())
    total = int(job.get("epochs") or 0)
    log_text = _job_log_text(project_id, job_id)
    cur = _infer_epoch_from_log(log_text, total)
    if status in {"done", "finished"}:
        cur = total or cur
        progress = 100
    elif status in {"failed", "stopped"}:
        progress = int(min(99, round((cur / total) * 100))) if total and cur else int(job.get("progress_percent") or 0)
    else:
        progress = int(min(99, round((cur / total) * 100))) if total and cur else int(job.get("progress_percent") or 0)
    started = _parse_dt_value(job.get("started_at") or job.get("created_at"))
    elapsed = int((datetime.now() - started).total_seconds()) if started else 0
    # 暂停期间不计入真实训练耗时/ETA。
    paused_seconds = int(job.get("paused_seconds") or 0)
    if status == "paused" and job.get("paused_at"):
        pdt = _parse_dt_value(job.get("paused_at"))
        if pdt:
            paused_seconds += max(0, int((datetime.now() - pdt).total_seconds()))
    elapsed = max(0, elapsed - paused_seconds)
    eta = None
    if status == "running" and total and cur and elapsed > 0:
        eta = int(max(0, elapsed * (total - cur) / max(1, cur)))
    elif status in {"done", "finished", "completed", "failed", "stopped"}:
        eta = 0
    elif status == "paused":
        eta = None
    job["current_epoch"] = cur
    job["total_epochs"] = total
    job["progress_percent"] = progress
    job["elapsed_seconds"] = elapsed
    job["elapsed_text"] = _human_seconds(elapsed) if elapsed else "-"
    job["eta_seconds"] = eta
    job["eta_text"] = _human_seconds(eta) if eta is not None else "估算中"
    job["status_text"] = {"queued":"排队中", "running":"训练中", "paused":"已暂停", "done":"已完成", "finished":"已完成", "completed":"已完成", "failed":"失败", "stopped":"已停止"}.get(status, status)
    if job.get("status") in {"done","finished","completed","failed","stopped"} and job.get("asset_algorithm_id"):
        try:
            _v48_archive_training_version(project_id, job)
        except Exception as archive_error:
            job["version_archive_error"] = str(archive_error)
    return job


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


def project_dir(project_id: str) -> Path:
    return DATA_DIR / "projects" / project_id


def get_project(project_id: str) -> Dict[str, Any]:
    meta = project_dir(project_id) / "meta.json"
    if not meta.exists():
        raise HTTPException(status_code=404, detail="项目不存在")
    return read_json(meta, {})


def save_project(project: Dict[str, Any]):
    project["updated_at"] = now_iso()
    write_json(project_dir(project["id"]) / "meta.json", project)
    projects = read_json(PROJECTS_FILE, [])
    found = False
    for i, item in enumerate(projects):
        if item["id"] == project["id"]:
            projects[i] = project
            found = True
            break
    if not found:
        projects.append(project)
    write_json(PROJECTS_FILE, projects)


def safe_filename(filename: str) -> str:
    name = Path(filename).name.replace(" ", "_")
    safe = "".join(c for c in name if c.isalnum() or c in "._-()[]{}+@#中文标签数据集模型训练")
    return safe.strip(".") or "file"


def image_info(path: Path) -> Dict[str, Any]:
    with Image.open(path) as img:
        return {"width": img.width, "height": img.height}


def ensure_project_dirs(pid: str):
    p = project_dir(pid)
    for d in ["uploads", "annotations", "dataset", "paddle_dataset", "runs", "models", "jobs", "predictions", "imports", "exports", "prelabels", "videos", "frame_tasks", "prelabel_tasks"]:
        (p / d).mkdir(parents=True, exist_ok=True)


def load_images(project_id: str) -> List[Dict[str, Any]]:
    return read_json(project_dir(project_id) / "images.json", [])


def save_images(project_id: str, images: List[Dict[str, Any]]):
    write_json(project_dir(project_id) / "images.json", images)


def normalize_label(name: str) -> str:
    return str(name or "").strip().replace(" ", "_")

def default_label_color(index: int) -> str:
    palette = ["#2563eb", "#16a34a", "#dc2626", "#ea580c", "#7c3aed", "#0891b2", "#be123c", "#4b5563", "#65a30d", "#ca8a04"]
    return palette[index % len(palette)]


def ensure_label(project: Dict[str, Any], label: str) -> int:
    label = normalize_label(label)
    if not label:
        raise HTTPException(status_code=400, detail="标签不能为空")
    labels = project.setdefault("labels", [])
    for i, item in enumerate(labels):
        if item == label:
            return i
    labels.append(label)
    meta = project.setdefault("label_meta", [])
    meta.append({"code": label, "display_name": label, "color": default_label_color(len(labels)-1), "type": "bbox", "hotkey": str(len(labels)) if len(labels) <= 9 else ""})
    save_project(project)
    return len(labels) - 1


def get_label_id(project: Dict[str, Any], label: str) -> int:
    label = normalize_label(label)
    if label not in project.get("labels", []):
        return ensure_label(project, label)
    return project["labels"].index(label)


def is_image_file(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def read_yaml_names(path: Path) -> List[str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names = data.get("names", [])
        if isinstance(names, dict):
            return [str(names[k]) for k in sorted(names.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))]
        if isinstance(names, list):
            return [str(x) for x in names]
    except Exception:
        return []
    return []


def yolo_line_to_box(line: str, img_w: int, img_h: int) -> Optional[Dict[str, Any]]:
    parts = line.strip().split()
    if len(parts) < 5:
        return None
    try:
        cls = int(float(parts[0]))
        xc, yc, bw, bh = map(float, parts[1:5])
        x1 = (xc - bw / 2) * img_w
        y1 = (yc - bh / 2) * img_h
        x2 = (xc + bw / 2) * img_w
        y2 = (yc + bh / 2) * img_h
        x1 = max(0, min(x1, img_w))
        x2 = max(0, min(x2, img_w))
        y1 = max(0, min(y1, img_h))
        y2 = max(0, min(y2, img_h))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        return {"class_id": cls, "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2)}
    except Exception:
        return None


def box_to_yolo_line(b: Dict[str, Any], w: int, h: int) -> str:
    x_center = ((b["x1"] + b["x2"]) / 2) / w
    y_center = ((b["y1"] + b["y2"]) / 2) / h
    bw = (b["x2"] - b["x1"]) / w
    bh = (b["y2"] - b["y1"]) / h
    return f"{int(b['class_id'])} {x_center:.6f} {y_center:.6f} {bw:.6f} {bh:.6f}"


_IMAGE_BATCH_CTX = threading.local()
_V50_IMPORT_LOCK_GUARD = threading.Lock()
_V50_IMPORT_LOCKS: Dict[str, threading.RLock] = {}

def _v50_project_import_lock(project_id: str) -> threading.RLock:
    with _V50_IMPORT_LOCK_GUARD:
        lock = _V50_IMPORT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.RLock()
            _V50_IMPORT_LOCKS[project_id] = lock
        return lock

def _v50_active_image_batch(project_id: str):
    batch = getattr(_IMAGE_BATCH_CTX, "batch", None)
    if batch and batch.get("project_id") == project_id:
        return batch
    return None

def _v50_begin_image_batch(project_id: str):
    images = load_images(project_id)
    _IMAGE_BATCH_CTX.batch = {
        "project_id": project_id,
        "images": images,
        "by_id": {str(x.get("id")): x for x in images},
        "dirty": False,
    }

def _v50_end_image_batch(save: bool = True):
    batch = getattr(_IMAGE_BATCH_CTX, "batch", None)
    try:
        if save and batch and batch.get("dirty"):
            save_images(batch["project_id"], batch["images"])
    finally:
        _IMAGE_BATCH_CTX.batch = None

def _v50_mark_image_processed(project_id: str, image_id: str, annotated: bool = False):
    batch = _v50_active_image_batch(project_id)
    if batch:
        img = batch["by_id"].get(str(image_id))
        if img is not None and annotated:
            img["processing_status"] = "processed"
            img["annotated_at"] = now_iso()
            batch["dirty"] = True
        return
    if not annotated:
        return
    images = load_images(project_id)
    changed = False
    for img in images:
        if str(img.get("id")) == str(image_id):
            img["processing_status"] = "processed"
            img["annotated_at"] = now_iso()
            changed = True
            break
    if changed:
        save_images(project_id, images)

def write_annotation(project_id: str, image_id: str, boxes: List[Dict[str, Any]]):
    updated = now_iso()
    atomic_write_json(project_dir(project_id) / "annotations" / f"{image_id}.json", {
        "image_id": image_id,
        "boxes": boxes,
        "updated_at": updated,
    })
    # v42.11：把标注摘要同步进 images.json。列表页/首次启动无需逐张再次读取 annotation json，
    # 同时保留前 32 个框用于数据卡片和预览叠加显示。
    summary = annotation_summary(boxes)
    batch = _v50_active_image_batch(project_id)
    images = batch.get("images") if batch else load_images(project_id)
    changed = False
    for img in images:
        if str(img.get("id")) != str(image_id):
            continue
        img.update(summary)
        img["annotation_summary_at"] = updated
        if boxes:
            img["processing_status"] = "processed"
            img["annotated_at"] = updated
        changed = True
        if batch:
            batch["dirty"] = True
        break
    if changed and not batch:
        save_images(project_id, images)


def read_annotation(project_id: str, image_id: str) -> Dict[str, Any]:
    return read_json(project_dir(project_id) / "annotations" / f"{image_id}.json", {"image_id": image_id, "boxes": []})


def add_image_record(project_id: str, src: Path, original_name: str, source_type: str = "raw", dataset_id: str = "default") -> Optional[Dict[str, Any]]:
    p = project_dir(project_id)
    ext = src.suffix.lower()
    if ext not in IMAGE_EXTS:
        return None
    img_id = uuid.uuid4().hex[:16]
    dst_name = f"{img_id}{ext}"
    dst = p / "uploads" / dst_name
    shutil.copy2(src, dst)
    try:
        info = image_info(dst)
    except Exception:
        dst.unlink(missing_ok=True)
        return None
    record = {
        "id": img_id,
        "filename": original_name,
        "stored_name": dst_name,
        "url": f"/data/projects/{project_id}/uploads/{dst_name}",
        "width": info["width"],
        "height": info["height"],
        "source_type": source_type,
        "dataset_id": dataset_id or "default",
        "split": "unassigned",
        "processing_status": initial_processing_status(has_valid_boxes=False),
        "size_bytes": int(dst.stat().st_size) if dst.exists() else 0,
        "created_at": now_iso(),
    }
    batch = _v50_active_image_batch(project_id)
    if batch:
        batch["images"].append(record)
        batch["by_id"][str(img_id)] = record
        batch["dirty"] = True
    else:
        images = load_images(project_id)
        images.append(record)
        save_images(project_id, images)
    if not (p / "annotations" / f"{img_id}.json").exists():
        write_annotation(project_id, img_id, [])
    return record


def zip_dir(src_dir: Path, zip_path: Path):
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir))


@app.get("/", response_class=HTMLResponse)
def index():
    # 禁止浏览器缓存旧首页。版本升级后必须立即加载当前静态资源，避免“代码里有部署转换但页面看不到”。
    return HTMLResponse(
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "time": now_iso(), "base_dir": str(BASE_DIR), "engines": ["ultralytics", "paddle_command"], "ui":"v42.14"}


class ProjectCreate(BaseModel):
    name: str
    labels: Optional[List[Any]] = None
    description: Optional[str] = ""
    label_meta: Optional[List[Dict[str, Any]]] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@app.get("/api/projects")
def list_projects():
    return read_json(PROJECTS_FILE, [])


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate):
    project = get_project(project_id)
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="项目名称不能为空")
        project["name"] = payload.name.strip()
    if payload.description is not None:
        project["description"] = payload.description or ""
    save_project(project)
    return project


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    projects = read_json(PROJECTS_FILE, [])
    if not any(p.get("id") == project_id for p in projects):
        raise HTTPException(status_code=404, detail="项目不存在")
    write_json(PROJECTS_FILE, [p for p in projects if p.get("id") != project_id])
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
    return {"ok": True}


def datasets_file(project_id: str) -> Path:
    return project_dir(project_id) / "datasets.json"


def ensure_default_datasets(project_id: str) -> List[Dict[str, Any]]:
    f = datasets_file(project_id)
    ds = read_json(f, [])
    if not ds:
        ds = [{"id":"default", "name":"默认数据集", "description":"", "created_at": now_iso(), "updated_at": now_iso()}]
        write_json(f, ds)
    return ds


class DatasetReq(BaseModel):
    name: str
    description: Optional[str] = ""


@app.get("/api/projects/{project_id}/datasets")
def list_datasets(project_id: str):
    get_project(project_id)
    datasets = ensure_default_datasets(project_id)
    images = load_images(project_id)
    result = []
    for ds in datasets:
        dsid = ds.get("id") or "default"
        imgs = [x for x in images if x.get("dataset_id", "default") == dsid]
        annotated = 0; boxes = 0
        for img in imgs:
            ann = read_annotation(project_id, img["id"])
            cnt = len(ann.get("boxes", []))
            boxes += cnt
            if cnt:
                annotated += 1
        result.append({**ds, "images": len(imgs), "annotated_images": annotated, "boxes": boxes})
    return {"ok": True, "items": result}


@app.post("/api/projects/{project_id}/datasets")
def create_dataset(project_id: str, payload: DatasetReq):
    get_project(project_id)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="数据集名称不能为空")
    ds = ensure_default_datasets(project_id)
    item = {"id": uuid.uuid4().hex[:12], "name": payload.name.strip(), "description": payload.description or "", "created_at": now_iso(), "updated_at": now_iso()}
    ds.append(item)
    write_json(datasets_file(project_id), ds)
    return item


@app.put("/api/projects/{project_id}/datasets/{dataset_id}")
def update_dataset(project_id: str, dataset_id: str, payload: DatasetReq):
    get_project(project_id)
    ds = ensure_default_datasets(project_id)
    for item in ds:
        if item.get("id") == dataset_id:
            item["name"] = payload.name.strip() or item.get("name", "数据集")
            item["description"] = payload.description or ""
            item["updated_at"] = now_iso()
            write_json(datasets_file(project_id), ds)
            return item
    raise HTTPException(status_code=404, detail="数据集不存在")


@app.delete("/api/projects/{project_id}/datasets/{dataset_id}")
def delete_dataset(project_id: str, dataset_id: str):
    if dataset_id == "default":
        raise HTTPException(status_code=400, detail="默认数据集不能删除")
    get_project(project_id)
    ds = ensure_default_datasets(project_id)
    if not any(x.get("id") == dataset_id for x in ds):
        raise HTTPException(status_code=404, detail="数据集不存在")
    # 删除该数据集下的图片和标注
    images = load_images(project_id)
    kept = []
    p = project_dir(project_id)
    for img in images:
        if img.get("dataset_id", "default") == dataset_id:
            (p / "uploads" / img.get("stored_name", "")).unlink(missing_ok=True)
            (p / "annotations" / f"{img.get('id')}.json").unlink(missing_ok=True)
        else:
            kept.append(img)
    save_images(project_id, kept)
    write_json(datasets_file(project_id), [x for x in ds if x.get("id") != dataset_id])
    return {"ok": True}


@app.get("/api/system/recommendation")
def system_recommendation():
    cpu = os.cpu_count() or 1
    ram_gb = None
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 1)
    except Exception:
        ram_gb = 0
    cuda = False
    gpu_name = "None"
    try:
        import torch
        cuda = bool(torch.cuda.is_available())
        if cuda:
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        pass
    if cuda:
        rec = {"device":"0", "model":"yolo11s.pt", "epochs":50, "imgsz":640, "batch":8, "reason":"检测到 CUDA，推荐使用 YOLO11s 进行首轮效果验证。"}
    elif ram_gb and ram_gb >= 24 and cpu >= 12:
        rec = {"device":"cpu", "model":"yolo11n.pt", "epochs":20, "imgsz":640, "batch":4, "reason":"未检测到 CUDA，但 CPU/内存较充足，推荐 YOLO11n + CPU 小批量训练。"}
    else:
        rec = {"device":"cpu", "model":"yolo11n.pt", "epochs":10, "imgsz":416, "batch":2, "reason":"未检测到 CUDA，推荐降低图片尺寸和 batch，先跑通流程。"}
    return {"ok": True, "cpu_count": cpu, "ram_gb": ram_gb, "cuda": cuda, "gpu": gpu_name, "recommendation": rec}


@app.post("/api/projects")
def create_project(payload: ProjectCreate):
    labels = []
    label_meta = []
    raw_label_meta = payload.label_meta or []
    for idx, x in enumerate(payload.labels or []):
        display_name = ""
        color = ""
        if isinstance(x, dict):
            code = normalize_label(x.get("code") or x.get("name") or x.get("label") or "")
            display_name = str(x.get("display_name") or x.get("zh") or x.get("name") or code)
            color = str(x.get("color") or "")
        else:
            code = normalize_label(x)
            if idx < len(raw_label_meta) and isinstance(raw_label_meta[idx], dict):
                display_name = str(raw_label_meta[idx].get("display_name") or raw_label_meta[idx].get("name") or code)
                color = str(raw_label_meta[idx].get("color") or "")
            else:
                display_name = code
        if code and code not in labels:
            labels.append(code)
            label_meta.append({"code": code, "display_name": display_name or code, "color": color or default_label_color(len(labels)-1), "type": "bbox", "hotkey": str(len(labels)) if len(labels) <= 9 else ""})
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    # 项目创建不再强制填写标签；标签在数据集/标注环节维护。
    pid = uuid.uuid4().hex[:12]
    ensure_project_dirs(pid)
    project = {
        "id": pid,
        "name": payload.name.strip(),
        "description": payload.description or "",
        "labels": labels,
        "label_meta": label_meta,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    save_project(project)
    write_json(project_dir(pid) / "images.json", [])
    return project


@app.get("/api/projects/{project_id}")
def read_project(project_id: str):
    project = get_project(project_id)
    images = load_images(project_id)
    sync_jobs_index(project_id)
    jobs = read_json(project_dir(project_id) / "jobs" / "index.json", [])
    models = list_models_internal(project_id)
    annotated = 0
    boxes = 0
    for img in images:
        ann = read_annotation(project_id, img["id"])
        cnt = len(ann.get("boxes", []))
        boxes += cnt
        if cnt:
            annotated += 1
    return {"project": project, "images": len(images), "annotated_images": annotated, "boxes": boxes, "jobs": jobs, "models": models}


class AddLabelReq(BaseModel):
    label: str
    display_name: Optional[str] = ""
    color: Optional[str] = ""


@app.post("/api/projects/{project_id}/labels")
def add_label(project_id: str, payload: AddLabelReq):
    project = get_project(project_id)
    idx = ensure_label(project, payload.label)
    project = get_project(project_id)
    meta = project.setdefault("label_meta", [])
    while len(meta) < len(project.get("labels", [])):
        code = project["labels"][len(meta)]
        meta.append({"code": code, "display_name": code, "color": default_label_color(len(meta)), "type": "bbox", "hotkey": str(len(meta)+1) if len(meta) < 9 else ""})
    if idx < len(meta):
        if payload.display_name:
            meta[idx]["display_name"] = payload.display_name
        if payload.color:
            meta[idx]["color"] = payload.color
    save_project(project)
    return {"ok": True, "class_id": idx, "labels": project["labels"], "label_meta": project.get("label_meta", [])}


@app.post("/api/projects/{project_id}/images")
async def upload_images(project_id: str, files: List[UploadFile] = File(...), dataset_id: str = Form("default")):
    get_project(project_id)
    p = project_dir(project_id)
    uploaded, failed = [], []
    batch_id = uuid.uuid4().hex[:12]
    started = time.time()
    # v42.11：分块写盘，避免多张大图一次性占满内存；逐文件返回失败原因。
    for file in files:
        filename = safe_filename(file.filename or "image.jpg")
        ext = Path(filename).suffix.lower()
        if ext not in IMAGE_EXTS:
            failed.append({"name": filename, "reason": "不支持的图片格式"})
            continue
        tmp = p / "imports" / f"upload_{uuid.uuid4().hex}{ext}"
        try:
            with tmp.open("wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            if not tmp.exists() or tmp.stat().st_size <= 0:
                failed.append({"name": filename, "reason": "文件为空"})
                continue
            record = add_image_record(project_id, tmp, filename, "raw", dataset_id)
            if record:
                uploaded.append(record)
            else:
                failed.append({"name": filename, "reason": "图片损坏或无法识别"})
        except Exception as e:
            failed.append({"name": filename, "reason": str(e)})
        finally:
            tmp.unlink(missing_ok=True)
    return {
        "batch_id": batch_id,
        "uploaded": uploaded, "failed": failed,
        "uploaded_image_ids": [str(item.get("id")) for item in uploaded],
        "uploaded_count": len(uploaded), "failed_count": len(failed),
        "elapsed_seconds": round(max(0.0, time.time()-started), 2),
        "total": len(load_images(project_id))
    }


_ANNOTATION_INDEX_LOCK = threading.Lock()
_ANNOTATION_INDEX_RUNNING: set = set()
_ANNOTATION_INDEX_STATUS: Dict[str, Dict[str, Any]] = {}

def _v52_annotation_index_worker(project_id: str):
    try:
        images = load_images(project_id)
        pending = [x for x in images if not x.get("annotation_summary_at")]
        total = len(pending)
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": True, "total": total, "processed": 0, "started_at": now_iso()}
        if not total:
            return
        by_id = {str(x.get("id")): x for x in images}
        for i, img in enumerate(pending, 1):
            anns = read_annotation(project_id, str(img.get("id")))
            boxes = anns.get("boxes", []) if isinstance(anns, dict) else []
            img["box_count"] = len(boxes)
            img["annotated"] = bool(boxes)
            img["labels"] = sorted({str(b.get("label") or "").strip() for b in boxes if str(b.get("label") or "").strip()})
            img["annotation_preview"] = [{k: b.get(k) for k in ("class_id","label","x1","y1","x2","y2")} for b in boxes[:32]]
            img["annotation_summary_at"] = anns.get("updated_at") or now_iso()
            if boxes:
                img["processing_status"] = "processed"
            if i % 100 == 0 or i == total:
                _ANNOTATION_INDEX_STATUS[project_id] = {"running": True, "total": total, "processed": i, "started_at": _ANNOTATION_INDEX_STATUS.get(project_id,{}).get("started_at"), "updated_at": now_iso()}
        save_images(project_id, list(by_id.values()))
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": False, "total": total, "processed": total, "finished_at": now_iso()}
    except Exception as e:
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": False, "error": str(e), "finished_at": now_iso()}
    finally:
        with _ANNOTATION_INDEX_LOCK:
            _ANNOTATION_INDEX_RUNNING.discard(project_id)

def _v52_schedule_annotation_index(project_id: str, images: Optional[List[Dict[str, Any]]] = None):
    rows = images if images is not None else load_images(project_id)
    pending = sum(1 for x in rows if not x.get("annotation_summary_at"))
    if not pending:
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": False, "total": 0, "processed": 0}
        return
    with _ANNOTATION_INDEX_LOCK:
        if project_id in _ANNOTATION_INDEX_RUNNING:
            return
        _ANNOTATION_INDEX_RUNNING.add(project_id)
    _ANNOTATION_INDEX_STATUS[project_id] = {"running": True, "total": pending, "processed": 0, "queued_at": now_iso()}
    threading.Thread(target=_v52_annotation_index_worker, args=(project_id,), daemon=True).start()

@app.get("/api/projects/{project_id}/images")
def list_images(project_id: str, dataset_id: Optional[str] = None):
    get_project(project_id)
    all_images = load_images(project_id)
    changed = False
    # v42.12：旧数据的标注摘要迁移改为后台索引，首屏不再逐张读取 annotation JSON。
    # 已有摘要直接返回；缺摘要的图片先以轻量元数据返回，后台完成后前端自动刷新一次。
    if any(not x.get("annotation_summary_at") for x in all_images):
        _v52_schedule_annotation_index(project_id, all_images)
    for img in all_images:
        img.setdefault("box_count", 0)
        img.setdefault("annotated", bool(img.get("box_count")))
        img.setdefault("labels", [])
        img.setdefault("annotation_preview", [])
        if not img.get("size_bytes"):
            try:
                img["size_bytes"] = int((project_dir(project_id) / "uploads" / img.get("stored_name", "")).stat().st_size)
            except Exception:
                img["size_bytes"] = 0
            changed = True
        img["split"] = (img.get("split") or "unassigned").lower()
        img["processing_status"] = "processed" if int(img.get("box_count") or 0)>0 else (img.get("processing_status") or ("processed" if img.get("cleaned_at") else "unprocessed"))
        img["annotation_index_pending"] = not bool(img.get("annotation_summary_at"))
    if changed:
        save_images(project_id, all_images)
    images = all_images
    if dataset_id:
        images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
    return images

@app.get('/api/v52/projects/{project_id}/annotation-index/status')
def v52_annotation_index_status(project_id: str):
    get_project(project_id)
    rows = load_images(project_id)
    pending = sum(1 for x in rows if not x.get('annotation_summary_at'))
    status = dict(_ANNOTATION_INDEX_STATUS.get(project_id) or {})
    status.setdefault('running', project_id in _ANNOTATION_INDEX_RUNNING)
    status['pending'] = pending
    status['total_images'] = len(rows)
    return {'ok': True, **status}


@app.delete("/api/projects/{project_id}/images/{image_id}")
def delete_image(project_id: str, image_id: str):
    get_project(project_id)
    p = project_dir(project_id)
    images = load_images(project_id)
    target = None
    kept = []
    for img in images:
        if img["id"] == image_id:
            target = img
        else:
            kept.append(img)
    if not target:
        raise HTTPException(status_code=404, detail="图片不存在")
    (p / "uploads" / target["stored_name"]).unlink(missing_ok=True)
    (p / "annotations" / f"{image_id}.json").unlink(missing_ok=True)
    save_images(project_id, kept)
    return {"ok": True}




class V46BatchDeleteImagesReq(BaseModel):
    image_ids: List[str]


@app.post("/api/v46/projects/{project_id}/images/batch-delete")
def v46_batch_delete_images(project_id: str, payload: V46BatchDeleteImagesReq):
    get_project(project_id)
    ids = {str(x) for x in (payload.image_ids or []) if str(x).strip()}
    if not ids:
        return {"ok": True, "deleted": 0, "deleted_images": [], "failed_items": []}
    p = project_dir(project_id)
    images = load_images(project_id)
    kept = []
    deleted_images = []
    failed_items = []
    found_ids = set()
    for img in images:
        image_id = str(img.get("id"))
        if image_id not in ids:
            kept.append(img)
            continue
        found_ids.add(image_id)
        errors = delete_material_files(p, img)
        if errors:
            kept.append(img)
            failed_items.append({"id": image_id, "filename": img.get("filename"), "errors": errors})
            continue
        deleted_images.append({"id": image_id, "filename": img.get("filename")})
    for missing_id in sorted(ids - found_ids):
        failed_items.append({"id": missing_id, "filename": "", "errors": ["图片不存在"]})
    if deleted_images:
        save_images(project_id, kept)
    return {
        "ok": not failed_items,
        "deleted": len(deleted_images),
        "deleted_images": deleted_images,
        "failed_items": failed_items,
    }


@app.post("/api/projects/{project_id}/import/yolo_zip")
async def import_yolo_zip(project_id: str, file: UploadFile = File(...), dataset_id: str = Form("default")):
    project = get_project(project_id)
    p = project_dir(project_id)
    name = safe_filename(file.filename or "dataset.zip")
    if Path(name).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="请上传 zip 压缩包")
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / "imports" / f"yolo_{import_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / "imports" / f"{import_id}.zip"
    zip_path.write_bytes(await file.read())
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"zip 解压失败：{e}")

    yaml_files = list(temp_dir.rglob("data.yaml")) + list(temp_dir.rglob("*.yaml")) + list(temp_dir.rglob("*.yml"))
    imported_names = []
    for yf in yaml_files:
        imported_names = read_yaml_names(yf)
        if imported_names:
            break
    if not imported_names:
        imported_names = project.get("labels", [])

    # 先把导入数据的标签补充到项目中，保证类目名称不丢失
    for label in imported_names:
        if label:
            ensure_label(project, label)
    project = get_project(project_id)

    all_label_files = [x for x in temp_dir.rglob("*.txt") if x.name.lower() not in {"classes.txt", "obj.names"}]
    label_by_stem: Dict[str, List[Path]] = {}
    for lf in all_label_files:
        label_by_stem.setdefault(lf.stem, []).append(lf)

    image_files = [x for x in temp_dir.rglob("*") if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    imported = []
    annotated = 0
    skipped_labels = 0
    for img_path in image_files:
        record = add_image_record(project_id, img_path, img_path.name, "imported_yolo", dataset_id)
        if not record:
            continue
        label_file = None
        candidates = label_by_stem.get(img_path.stem, [])
        if candidates:
            # 优先选路径中包含 labels 的文件
            label_file = next((x for x in candidates if "labels" in [p.lower() for p in x.parts]), candidates[0])
        boxes = []
        if label_file and label_file.exists():
            lines = label_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in lines:
                box = yolo_line_to_box(line, record["width"], record["height"])
                if not box:
                    continue
                old_cls = box["class_id"]
                if old_cls < len(imported_names):
                    label = normalize_label(imported_names[old_cls])
                    new_cls = get_label_id(project, label)
                elif old_cls < len(project.get("labels", [])):
                    new_cls = old_cls
                else:
                    skipped_labels += 1
                    continue
                box["class_id"] = new_cls
                box["label"] = get_project(project_id)["labels"][new_cls]
                box["id"] = uuid.uuid4().hex[:10]
                boxes.append(box)
        write_annotation(project_id, record["id"], boxes)
        if boxes:
            annotated += 1
        imported.append(record)

    shutil.rmtree(temp_dir, ignore_errors=True)
    return {
        "ok": True,
        "imported_images": len(imported),
        "annotated_images": annotated,
        "labels": get_project(project_id)["labels"],
        "skipped_labels": skipped_labels,
        "message": "已导入 YOLO 数据集。系统已把 YOLO txt 转成平台内部标注，可继续编辑。",
    }


@app.post("/api/projects/{project_id}/import/labels")
async def import_label_files(project_id: str, files: List[UploadFile] = File(...)):
    project = get_project(project_id)
    p = project_dir(project_id)
    images = load_images(project_id)
    by_stem = {Path(img["filename"]).stem: img for img in images}
    by_stored_stem = {Path(img["stored_name"]).stem: img for img in images}
    matched = 0
    boxes_count = 0
    temp_dir = p / "imports" / f"labels_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    label_paths: List[Path] = []
    for f in files:
        fname = safe_filename(f.filename or "label.txt")
        ext = Path(fname).suffix.lower()
        raw = await f.read()
        if ext == ".zip":
            zp = temp_dir / fname
            zp.write_bytes(raw)
            try:
                with zipfile.ZipFile(zp, "r") as zf:
                    zf.extractall(temp_dir)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"标签 zip 解压失败：{e}")
        elif ext == ".txt":
            lp = temp_dir / fname
            lp.write_bytes(raw)
            label_paths.append(lp)
    label_paths.extend([x for x in temp_dir.rglob("*.txt") if x.name.lower() not in {"classes.txt", "obj.names"}])
    seen = set()
    unique_paths = []
    for lp in label_paths:
        if lp not in seen:
            unique_paths.append(lp); seen.add(lp)
    for lp in unique_paths:
        img = by_stem.get(lp.stem) or by_stored_stem.get(lp.stem)
        if not img:
            continue
        boxes = []
        for line in lp.read_text(encoding="utf-8", errors="ignore").splitlines():
            box = yolo_line_to_box(line, img["width"], img["height"])
            if not box:
                continue
            if box["class_id"] >= len(project["labels"]):
                continue
            box["id"] = uuid.uuid4().hex[:10]
            box["label"] = project["labels"][box["class_id"]]
            boxes.append(box)
        write_annotation(project_id, img["id"], boxes)
        matched += 1
        boxes_count += len(boxes)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return {"ok": True, "matched_images": matched, "boxes": boxes_count}




# -----------------------------
# COCO / VOC annotated dataset import
# -----------------------------
@app.post("/api/projects/{project_id}/import/coco_zip")
async def import_coco_zip(project_id: str, file: UploadFile = File(...), dataset_id: str = Form("default")):
    project = get_project(project_id)
    p = project_dir(project_id)
    name = safe_filename(file.filename or "coco_dataset.zip")
    if Path(name).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="请上传 COCO 数据集 zip")
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / "imports" / f"coco_{import_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / "imports" / f"{import_id}.zip"
    zip_path.write_bytes(await file.read())
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"zip 解压失败：{e}")
    json_files = [x for x in temp_dir.rglob("*.json") if x.is_file()]
    if not json_files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="未找到 COCO json 标注文件")
    ann_json = next((x for x in json_files if "train" in x.name.lower() or "instance" in x.name.lower()), json_files[0])
    try:
        coco = json.loads(ann_json.read_text(encoding="utf-8"))
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"COCO json 读取失败：{e}")
    cats = sorted(coco.get("categories", []), key=lambda c: int(c.get("id", 0)))
    cat_to_label = {}
    for c in cats:
        label = normalize_label(c.get("name") or f"class_{c.get('id')}")
        ensure_label(project, label)
        cat_to_label[int(c.get("id"))] = label
    project = get_project(project_id)
    cat_to_class = {cid: get_label_id(project, label) for cid, label in cat_to_label.items()}
    images_payload = coco.get("images", [])
    anns_by_img: Dict[int, List[Dict[str, Any]]] = {}
    for ann in coco.get("annotations", []):
        try:
            anns_by_img.setdefault(int(ann.get("image_id")), []).append(ann)
        except Exception:
            pass
    # Build quick image lookup by relative path and basename
    image_files = [x for x in temp_dir.rglob("*") if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    by_rel = {str(x.relative_to(temp_dir)).replace("\\", "/"): x for x in image_files}
    by_name: Dict[str, Path] = {}
    for x in image_files:
        by_name.setdefault(x.name, x)
    imported = []
    annotated = 0
    boxes_total = 0
    for im in images_payload:
        file_name = str(im.get("file_name") or "").replace("\\", "/")
        src = by_rel.get(file_name) or by_name.get(Path(file_name).name)
        if not src or not src.exists():
            continue
        record = add_image_record(project_id, src, Path(file_name).name, "imported_coco")
        if not record:
            continue
        boxes = []
        for ann in anns_by_img.get(int(im.get("id")), []):
            cid = int(ann.get("category_id", -1))
            if cid not in cat_to_class:
                continue
            bbox = ann.get("bbox") or []
            if len(bbox) < 4:
                continue
            x, y, w, h = [float(v) for v in bbox[:4]]
            if w <= 1 or h <= 1:
                continue
            class_id = cat_to_class[cid]
            boxes.append({
                "id": uuid.uuid4().hex[:10],
                "class_id": class_id,
                "label": get_project(project_id)["labels"][class_id],
                "x1": round(max(0, x), 2),
                "y1": round(max(0, y), 2),
                "x2": round(min(record["width"], x + w), 2),
                "y2": round(min(record["height"], y + h), 2),
            })
        write_annotation(project_id, record["id"], boxes)
        imported.append(record)
        if boxes:
            annotated += 1
            boxes_total += len(boxes)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return {"ok": True, "imported_images": len(imported), "annotated_images": annotated, "boxes": boxes_total, "labels": get_project(project_id).get("labels", []), "message": "已导入 COCO 数据集并转换为平台内部标注。"}


@app.post("/api/projects/{project_id}/import/voc_zip")
async def import_voc_zip(project_id: str, file: UploadFile = File(...), dataset_id: str = Form("default")):
    import xml.etree.ElementTree as ET
    project = get_project(project_id)
    p = project_dir(project_id)
    name = safe_filename(file.filename or "voc_dataset.zip")
    if Path(name).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="请上传 VOC 数据集 zip")
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / "imports" / f"voc_{import_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / "imports" / f"{import_id}.zip"
    zip_path.write_bytes(await file.read())
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"zip 解压失败：{e}")
    image_files = [x for x in temp_dir.rglob("*") if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    by_name = {x.name: x for x in image_files}
    by_stem = {x.stem: x for x in image_files}
    imported = []
    annotated = 0
    boxes_total = 0
    for xp in temp_dir.rglob("*.xml"):
        try:
            root = ET.parse(xp).getroot()
        except Exception:
            continue
        filename = (root.findtext("filename") or "").strip()
        src = by_name.get(filename) or by_stem.get(xp.stem)
        if not src:
            continue
        record = add_image_record(project_id, src, src.name, "imported_voc")
        if not record:
            continue
        boxes = []
        for obj in root.findall("object"):
            label = normalize_label(obj.findtext("name") or "object")
            if not label:
                continue
            class_id = ensure_label(project, label)
            project = get_project(project_id)
            bb = obj.find("bndbox")
            if bb is None:
                continue
            try:
                x1 = float(bb.findtext("xmin")); y1 = float(bb.findtext("ymin")); x2 = float(bb.findtext("xmax")); y2 = float(bb.findtext("ymax"))
            except Exception:
                continue
            if x2 - x1 < 1 or y2 - y1 < 1:
                continue
            boxes.append({"id": uuid.uuid4().hex[:10], "class_id": class_id, "label": project["labels"][class_id], "x1": round(max(0,x1),2), "y1": round(max(0,y1),2), "x2": round(min(record["width"],x2),2), "y2": round(min(record["height"],y2),2)})
        write_annotation(project_id, record["id"], boxes)
        imported.append(record)
        if boxes:
            annotated += 1
            boxes_total += len(boxes)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return {"ok": True, "imported_images": len(imported), "annotated_images": annotated, "boxes": boxes_total, "labels": get_project(project_id).get("labels", []), "message": "已导入 Pascal VOC 数据集并转换为平台内部标注。"}

@app.get("/api/projects/{project_id}/annotations/{image_id}")
def get_annotation(project_id: str, image_id: str):
    get_project(project_id)
    images = load_images(project_id)
    img = next((x for x in images if x["id"] == image_id), None)
    if not img:
        raise HTTPException(status_code=404, detail="图片不存在")
    ann = read_annotation(project_id, image_id)
    return {"ok": True, **ann, "image": img, "annotation": ann}


class AnnotationSave(BaseModel):
    boxes: List[Dict[str, Any]]


@app.post("/api/projects/{project_id}/annotations/{image_id}")
def save_annotation(project_id: str, image_id: str, payload: AnnotationSave):
    project = get_project(project_id)
    images = load_images(project_id)
    img = next((x for x in images if x["id"] == image_id), None)
    if not img:
        raise HTTPException(status_code=404, detail="图片不存在")
    label_ids = {
        str(item["code"]): int(item["class_id"])
        for item in active_label_options(project_label_items(project))
    }
    try:
        clean_boxes = normalize_boxes(
            payload.boxes,
            int(img.get("width") or 0),
            int(img.get("height") or 0),
            label_ids,
        )
    except KeyError as error:
        missing_label = str(error.args[0] or "")
        raise PlatformError(
            code="ANNOTATION_LABEL_NOT_FOUND",
            message="标注保存失败",
            detail=f"标签 {missing_label} 不在标签库中",
            solution="请到配置中心的标签管理中创建或启用该标签。",
            status_code=422,
        ) from error
    except ValueError as error:
        raise PlatformError(
            code="ANNOTATION_INVALID_BOX",
            message="标注保存失败",
            detail=str(error),
            solution="请检查标注框是否位于图片内部且宽高大于零。",
            status_code=422,
        ) from error
    write_annotation(project_id, image_id, clean_boxes)
    fresh = next((x for x in load_images(project_id) if str(x.get("id")) == str(image_id)), img)
    return {"ok": True, "image": fresh, "annotation": read_annotation(project_id, image_id), "saved_boxes": len(clean_boxes)}


class BuildDatasetReq(BaseModel):
    train_ratio: float = 0.8
    include_empty: bool = False
    dataset_id: Optional[str] = None


@app.post("/api/projects/{project_id}/dataset/build")
def build_dataset(project_id: str, payload: BuildDatasetReq):
    project = get_project(project_id)
    p = project_dir(project_id)
    images = load_images(project_id)
    if payload.dataset_id:
        images = [img for img in images if img.get("dataset_id", "default") == payload.dataset_id]
    selected = []
    empty_count = 0
    for img in images:
        ann = read_annotation(project_id, img["id"])
        if ann.get("boxes") or payload.include_empty:
            selected.append((img, ann))
            if not ann.get("boxes"):
                empty_count += 1
    if not selected:
        raise HTTPException(status_code=400, detail="没有可生成的数据。请先上传图片并标注，或勾选包含未标注图片。")
    ratio = max(0.5, min(float(payload.train_ratio), 0.95))
    selected = sorted(selected, key=lambda x: x[0]["id"])
    if len(selected) == 1:
        train_items = selected
        val_items = selected
    else:
        split = max(1, min(len(selected) - 1, int(len(selected) * ratio)))
        train_items = selected[:split]
        val_items = selected[split:]
    dataset = p / "dataset"
    if dataset.exists():
        shutil.rmtree(dataset)
    for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
        (dataset / sub).mkdir(parents=True, exist_ok=True)
    counts = {"train": 0, "val": 0, "boxes": 0, "empty_images": empty_count}

    def copy_items(items: List[Tuple[Dict[str, Any], Dict[str, Any]]], part: str):
        for img, ann in items:
            src = p / "uploads" / img["stored_name"]
            dst_img = dataset / "images" / part / img["stored_name"]
            shutil.copy2(src, dst_img)
            label_path = dataset / "labels" / part / f"{Path(img['stored_name']).stem}.txt"
            lines = []
            for b in ann.get("boxes", []):
                if int(b.get("class_id", -1)) < 0 or int(b.get("class_id", -1)) >= len(project["labels"]):
                    continue
                lines.append(box_to_yolo_line(b, img["width"], img["height"]))
                counts["boxes"] += 1
            label_path.write_text("\n".join(lines), encoding="utf-8")
            counts[part] += 1

    copy_items(train_items, "train")
    copy_items(val_items, "val")
    data_yaml = {
        "path": str(dataset).replace("\\", "/"),
        "train": "images/train",
        "val": "images/val",
        "names": {i: label for i, label in enumerate(project["labels"])},
    }
    yaml_path = dataset / "data.yaml"
    yaml_path.write_text(yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "dataset": str(dataset), "data_yaml": str(yaml_path), "counts": counts, "labels": project["labels"]}


@app.get("/api/projects/{project_id}/dataset/download")
def download_dataset(project_id: str):
    get_project(project_id)
    dataset = project_dir(project_id) / "dataset"
    yaml_path = dataset / "data.yaml"
    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail="请先生成数据集")
    zip_path = project_dir(project_id) / "exports" / "yolo_dataset.zip"
    zip_dir(dataset, zip_path)
    return FileResponse(zip_path, filename=f"{project_id}_yolo_dataset.zip")






# -----------------------------
# Paddle / COCO dataset export
# -----------------------------
class BuildPaddleDatasetReq(BaseModel):
    train_ratio: float = 0.8
    include_empty: bool = False


def _coco_image_item(img: Dict[str, Any], idx: int, file_name: str) -> Dict[str, Any]:
    return {
        "id": idx,
        "file_name": file_name,
        "width": int(img["width"]),
        "height": int(img["height"]),
    }


def _coco_ann_item(ann_id: int, img_id: int, b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        x1 = float(b["x1"]); y1 = float(b["y1"]); x2 = float(b["x2"]); y2 = float(b["y2"])
        w = max(0.0, x2 - x1); h = max(0.0, y2 - y1)
        if w < 1 or h < 1:
            return None
        return {
            "id": ann_id,
            "image_id": img_id,
            "category_id": int(b["class_id"]) + 1,
            "bbox": [round(x1, 2), round(y1, 2), round(w, 2), round(h, 2)],
            "area": round(w * h, 2),
            "iscrowd": 0,
            "segmentation": [],
        }
    except Exception:
        return None


def build_paddle_dataset_internal(project_id: str, train_ratio: float = 0.8, include_empty: bool = False, dataset_id: Optional[str] = None) -> Dict[str, Any]:
    """Export internal annotations to a COCO-style dataset usable by PaddleX/PaddleDetection."""
    project = get_project(project_id)
    p = project_dir(project_id)
    images = load_images(project_id)
    if dataset_id:
        images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
    selected: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    empty_count = 0
    for img in images:
        ann = read_annotation(project_id, img["id"])
        if ann.get("boxes") or include_empty:
            selected.append((img, ann))
            if not ann.get("boxes"):
                empty_count += 1
    if not selected:
        raise HTTPException(status_code=400, detail="没有可生成的飞桨数据。请先上传图片并标注，或勾选包含未标注图片。")
    ratio = max(0.5, min(float(train_ratio), 0.95))
    selected = sorted(selected, key=lambda x: x[0]["id"])
    if len(selected) == 1:
        train_items = selected
        val_items = selected
    else:
        split = max(1, min(len(selected) - 1, int(len(selected) * ratio)))
        train_items = selected[:split]
        val_items = selected[split:]

    dataset = p / "paddle_dataset"
    if dataset.exists():
        shutil.rmtree(dataset)
    for sub in ["images/train", "images/val", "annotations"]:
        (dataset / sub).mkdir(parents=True, exist_ok=True)

    labels = [str(x) for x in project.get("labels", []) if str(x).strip()]
    if not labels:
        raise HTTPException(status_code=400, detail="当前项目没有标签，无法生成飞桨数据集。请先在标签库中添加类别。")
    # PaddleDetection + COCO：categories 使用 1-based id；模型输出 class index 是 0-based，
    # PaddleDetection 会按 categories 顺序建立 label_to_cat_id_map。
    # 关键是：annotation.category_id 必须只出现在 categories 里，同时训练配置 num_classes 必须等于 len(labels)。
    categories = [{"id": i + 1, "name": label, "supercategory": "object"} for i, label in enumerate(labels)]
    counts = {"train": 0, "val": 0, "boxes": 0, "train_boxes": 0, "val_boxes": 0, "empty_images": empty_count, "class_count": len(labels)}

    def write_part(items: List[Tuple[Dict[str, Any], Dict[str, Any]]], part: str, json_name: str):
        coco_images = []
        coco_anns = []
        ann_id = 1
        for idx, (img, ann) in enumerate(items, start=1):
            src = p / "uploads" / img["stored_name"]
            dst_name = img["stored_name"]
            dst = dataset / "images" / part / dst_name
            shutil.copy2(src, dst)
            coco_images.append(_coco_image_item(img, idx, f"images/{part}/{dst_name}"))
            for b in ann.get("boxes", []):
                cid = int(b.get("class_id", -1))
                if cid < 0 or cid >= len(labels):
                    continue
                item = _coco_ann_item(ann_id, idx, b)
                if item:
                    # 再次兜底：确保 COCO category_id 落在 categories 里，避免评估阶段 KeyError。
                    if int(item.get("category_id", -1)) not in {c["id"] for c in categories}:
                        continue
                    coco_anns.append(item)
                    ann_id += 1
                    counts["boxes"] += 1
                    counts[f"{part}_boxes"] += 1
            counts[part] += 1
        payload = {"images": coco_images, "annotations": coco_anns, "categories": categories}
        out = dataset / "annotations" / json_name
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)

    train_json = write_part(train_items, "train", "instance_train.json")
    val_json = write_part(val_items, "val", "instance_val.json")
    label_list = dataset / "label_list.txt"
    label_list.write_text("\n".join(project.get("labels", [])), encoding="utf-8")
    readme = dataset / "README.txt"
    readme.write_text(
        "这是平台导出的 COCO/Paddle 数据集。\n"
        "常见用途：PaddleX/PaddleDetection 训练。\n"
        "训练集标注：annotations/instance_train.json\n"
        "验证集标注：annotations/instance_val.json\n"
        "图片目录：images/train、images/val\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "dataset": str(dataset),
        "train_json": train_json,
        "val_json": val_json,
        "label_list": str(label_list),
        "counts": counts,
        "labels": labels,
        "message": "已生成飞桨/COCO格式数据集。可用于 PaddleX/PaddleDetection 训练命令。",
    }


@app.post("/api/projects/{project_id}/dataset/build_paddle")
def build_paddle_dataset(project_id: str, payload: BuildPaddleDatasetReq):
    return build_paddle_dataset_internal(project_id, payload.train_ratio, payload.include_empty, getattr(payload, "dataset_id", None))


@app.get("/api/projects/{project_id}/dataset/download_paddle")
def download_paddle_dataset(project_id: str):
    get_project(project_id)
    dataset = project_dir(project_id) / "paddle_dataset"
    if not (dataset / "annotations" / "instance_train.json").exists():
        raise HTTPException(status_code=404, detail="请先生成飞桨/COCO数据集")
    zip_path = project_dir(project_id) / "exports" / "paddle_coco_dataset.zip"
    zip_dir(dataset, zip_path)
    return FileResponse(zip_path, filename=f"{project_id}_paddle_coco_dataset.zip")


# -----------------------------
# Pre-label service integration
# -----------------------------
class PrelabelServiceReq(BaseModel):
    name: str
    detect_url: str
    health_url: Optional[str] = ""
    request_mode: str = "json_base64"  # json_base64 / multipart_file
    image_field: str = "image"
    threshold: float = 0.5
    target_label: str = "person"


class PrelabelRunReq(BaseModel):
    service_id: Optional[str] = None
    detect_url: Optional[str] = None
    request_mode: str = "json_base64"
    image_field: str = "image"
    threshold: float = 0.5
    target_label: str = "person"
    image_ids: Optional[List[str]] = None
    overwrite: bool = False


def list_prelabel_services_internal() -> List[Dict[str, Any]]:
    return read_json(PRELABEL_SERVICES_FILE, [])


@app.get("/api/prelabel_services")
def list_prelabel_services():
    return list_prelabel_services_internal()


@app.post("/api/prelabel_services")
def save_prelabel_service(payload: PrelabelServiceReq):
    name = payload.name.strip()
    detect_url = payload.detect_url.strip()
    if not name or not detect_url:
        raise HTTPException(status_code=400, detail="服务名称和检测地址不能为空")
    item = {
        "id": uuid.uuid4().hex[:10],
        "name": name,
        "detect_url": detect_url,
        "health_url": (payload.health_url or "").strip(),
        "request_mode": payload.request_mode,
        "image_field": payload.image_field or "image",
        "threshold": float(payload.threshold),
        "target_label": normalize_label(payload.target_label or "person"),
        "created_at": now_iso(),
    }
    services = list_prelabel_services_internal()
    services.insert(0, item)
    write_json(PRELABEL_SERVICES_FILE, services[:30])
    return item


@app.delete("/api/prelabel_services/{service_id}")
def delete_prelabel_service(service_id: str):
    services = [s for s in list_prelabel_services_internal() if s.get("id") != service_id]
    write_json(PRELABEL_SERVICES_FILE, services)
    return {"ok": True}


@app.post("/api/prelabel_services/test")
def test_prelabel_service(payload: PrelabelServiceReq):
    url = (payload.health_url or payload.detect_url).strip()
    try:
        r = requests.get(url, timeout=8)
        return {"ok": True, "status_code": r.status_code, "response": r.json() if "json" in r.headers.get("content-type", "") else r.text[:1000]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败：{e}")


def resolve_prelabel_config(payload: PrelabelRunReq) -> Dict[str, Any]:
    if payload.service_id:
        svc = next((s for s in list_prelabel_services_internal() if s.get("id") == payload.service_id), None)
        if not svc:
            raise HTTPException(status_code=400, detail="预标注服务不存在")
        return svc
    if payload.detect_url:
        return {
            "id": "manual",
            "name": "手动地址",
            "detect_url": payload.detect_url.strip(),
            "request_mode": payload.request_mode,
            "image_field": payload.image_field or "image",
            "threshold": float(payload.threshold),
            "target_label": normalize_label(payload.target_label or "person"),
        }
    raise HTTPException(status_code=400, detail="请选择或填写预标注服务地址")


def parse_detection_objects(data: Any, target_label: str, threshold: float) -> List[Dict[str, Any]]:
    """Accept common outputs: objects/detections/boxes with bbox/bbox_2d/coordinate."""
    objects: List[Any] = []
    if isinstance(data, dict):
        for key in ["objects", "detections", "results", "boxes", "bboxes"]:
            v = data.get(key)
            if isinstance(v, list):
                objects.extend(v)
        for key in ["result", "res", "data"]:
            if isinstance(data.get(key), dict):
                objects.extend(parse_detection_objects(data[key], target_label, threshold))
    elif isinstance(data, list):
        objects.extend(data)

    parsed: List[Dict[str, Any]] = []
    for obj in objects:
        label = target_label
        score = 1.0
        coord = None
        if isinstance(obj, dict):
            label = str(obj.get("label") or obj.get("class") or obj.get("category") or obj.get("name") or target_label)
            score = obj.get("confidence", obj.get("score", obj.get("conf", 1.0)))
            coord = obj.get("bbox_2d") or obj.get("bbox") or obj.get("box") or obj.get("coordinate") or obj.get("rect")
        elif isinstance(obj, list) and len(obj) >= 4:
            coord = obj[:4]
        try:
            score = float(score)
        except Exception:
            score = 0.0
        if score < threshold:
            continue
        if isinstance(coord, dict):
            try:
                x = float(coord.get("x", coord.get("left", 0)))
                y = float(coord.get("y", coord.get("top", 0)))
                w = float(coord.get("width", coord.get("w", 0)))
                h = float(coord.get("height", coord.get("h", 0)))
                coord = [x, y, x + w, y + h]
            except Exception:
                continue
        if not isinstance(coord, list) or len(coord) < 4:
            continue
        try:
            x1, y1, x2, y2 = [float(v) for v in coord[:4]]
        except Exception:
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        parsed.append({"label": label, "confidence": score, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return parsed


def call_prelabel_service(cfg: Dict[str, Any], image_path: Path) -> Dict[str, Any]:
    detect_url = cfg.get("detect_url")
    if not detect_url:
        raise ValueError("预标注检测地址为空")
    threshold = float(cfg.get("threshold", 0.5))
    mode = cfg.get("request_mode") or "json_base64"
    field = cfg.get("image_field") or "image"
    if mode == "multipart_file":
        with image_path.open("rb") as fp:
            r = requests.post(detect_url, files={field: (image_path.name, fp, "application/octet-stream")}, data={"threshold": str(threshold)}, timeout=120)
    else:
        raw = image_path.read_bytes()
        payload = {field: base64.b64encode(raw).decode("utf-8"), "threshold": threshold}
        r = requests.post(detect_url, json=payload, timeout=120)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


@app.post("/api/projects/{project_id}/prelabel/run")
def run_prelabel(project_id: str, payload: PrelabelRunReq):
    project = get_project(project_id)
    p = project_dir(project_id)
    cfg = resolve_prelabel_config(payload)
    target_label = normalize_label(cfg.get("target_label") or payload.target_label or "person")
    class_id = ensure_label(project, target_label)
    project = get_project(project_id)
    image_ids = set(payload.image_ids or [])
    images = load_images(project_id)
    if image_ids:
        images = [img for img in images if img["id"] in image_ids]
    if not images:
        raise HTTPException(status_code=400, detail="没有可预标注的图片")
    total_boxes = 0
    processed = 0
    errors = []
    for img in images:
        img_path = p / "uploads" / img["stored_name"]
        try:
            raw = call_prelabel_service(cfg, img_path)
            detections = parse_detection_objects(raw, target_label, float(cfg.get("threshold", 0.5)))
            new_boxes = []
            for det in detections:
                x1 = max(0, min(float(det["x1"]), img["width"]))
                y1 = max(0, min(float(det["y1"]), img["height"]))
                x2 = max(0, min(float(det["x2"]), img["width"]))
                y2 = max(0, min(float(det["y2"]), img["height"]))
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                new_boxes.append({
                    "id": uuid.uuid4().hex[:10],
                    "class_id": class_id,
                    "label": target_label,
                    "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
                    "source": "prelabel", "confidence": round(float(det.get("confidence", 0)), 4),
                })
            old = read_annotation(project_id, img["id"]).get("boxes", [])
            if payload.overwrite:
                merged = [b for b in old if int(b.get("class_id", -1)) != class_id] + new_boxes
            else:
                merged = old + new_boxes
            write_annotation(project_id, img["id"], merged)
            total_boxes += len(new_boxes)
            processed += 1
        except Exception as e:
            errors.append({"image": img.get("filename"), "error": str(e)})
    return {"ok": True, "processed_images": processed, "boxes_added": total_boxes, "target_label": target_label, "labels": get_project(project_id).get("labels", []), "errors": errors[:20]}

class LocalModelScanReq(BaseModel):
    roots: Optional[List[str]] = None
    max_results: int = 3000


class UltralyticsEnvDetectReq(BaseModel):
    roots: Optional[List[str]] = None


class UltralyticsEnvSelectReq(BaseModel):
    python_path: str
    yolo_path: Optional[str] = ""
    root: Optional[str] = ""


def _path_exists(p: str) -> bool:
    try:
        return bool(p) and Path(p).exists()
    except Exception:
        return False


def _is_absolute_path_text(p: str) -> bool:
    if not p:
        return False
    try:
        return Path(p).is_absolute() or bool(re.match(r"^[A-Za-z]:[\\/]", p))
    except Exception:
        return False


def default_ultralytics_roots() -> List[str]:
    roots: List[str] = []
    if os.name == "nt":
        roots.extend([
            r"D:\lab\yolosuanfa\Ultralytics",
            r"D:\lab\yolosuanfa",
            str(BASE_DIR),
        ])
        for letter in "DECF":
            p = f"{letter}:\\"
            if Path(p).exists():
                roots.append(p)
    else:
        roots.extend([str(BASE_DIR), str(Path.home()), "/mnt/data"])
    # 去重但保序
    out = []
    for r in roots:
        if r and r not in out:
            out.append(r)
    return out[:8]


def _candidate_python_paths(root: Path) -> List[Path]:
    paths: List[Path] = []
    # 用户可能直接填 .venv，也可能填 Ultralytics 根目录，也可能填 python.exe/yolo.exe
    if root.is_file():
        name = root.name.lower()
        if name == "python.exe" or name == "python":
            paths.append(root)
        elif name.startswith("yolo"):
            scripts = root.parent
            for py in [scripts / "python.exe", scripts / "python"]:
                if py.exists():
                    paths.append(py)
        return paths
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "Scripts" / "python.exe",
        root / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / "venv" / "bin" / "python",
        root / "bin" / "python",
    ]
    for p in candidates:
        if p.exists() and p not in paths:
            paths.append(p)
    return paths


def _find_pt_models_near(root: Path, limit: int = 30) -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []
    search_roots = []
    if root.is_file():
        search_roots.append(root.parent)
    else:
        search_roots.extend([root, root / "models", root / "weights"])
    seen = set()
    for sr in search_roots:
        if not sr.exists() or not sr.is_dir():
            continue
        try:
            for p in sr.glob("*.pt"):
                if str(p) in seen:
                    continue
                seen.add(str(p))
                try:
                    stat = p.stat()
                    models.append({
                        "name": p.name,
                        "path": str(p),
                        "size_mb": round(stat.st_size / 1024 / 1024, 2),
                        "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception:
                    models.append({"name": p.name, "path": str(p)})
                if len(models) >= limit:
                    return models
        except Exception:
            pass
    return models


def _check_ultralytics_python(py: Path, root: Path) -> Optional[Dict[str, Any]]:
    code = (
        "import json, sys\n"
        "try:\n"
        " import ultralytics\n"
        " print(json.dumps({'ok': True, 'version': getattr(ultralytics, '__version__', ''), 'package_path': getattr(ultralytics, '__file__', '')}, ensure_ascii=False))\n"
        "except Exception as e:\n"
        " print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))\n"
    )
    try:
        cp = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=15)
        line = (cp.stdout or cp.stderr or "").strip().splitlines()[-1] if (cp.stdout or cp.stderr) else ""
        data = json.loads(line) if line else {"ok": False, "error": "无输出"}
        if not data.get("ok"):
            return None
        scripts = py.parent
        yolo = scripts / ("yolo.exe" if os.name == "nt" else "yolo")
        item = {
            "ok": True,
            "root": str(root),
            "python_path": str(py),
            "yolo_path": str(yolo) if yolo.exists() else "",
            "version": data.get("version", ""),
            "package_path": data.get("package_path", ""),
            "models": _find_pt_models_near(root),
            "updated_at": now_iso(),
        }
        return item
    except Exception:
        return None


def detect_ultralytics_env_internal(roots: Optional[List[str]]) -> Dict[str, Any]:
    root_paths = normalize_scan_roots(roots or default_ultralytics_roots())
    candidates: List[Dict[str, Any]] = []
    seen_py = set()
    for root in root_paths:
        # 如果用户给的是父目录，额外检查一层常见子目录，避免扫全盘。
        probe_roots = [root]
        for sub in ["Ultralytics", "ultralytics", "yolosuanfa\\Ultralytics", "lab\\yolosuanfa\\Ultralytics"]:
            p = root / sub
            if p.exists():
                probe_roots.append(p)
        for pr in probe_roots:
            for py in _candidate_python_paths(pr):
                key = str(py).lower()
                if key in seen_py:
                    continue
                seen_py.add(key)
                found = _check_ultralytics_python(py, pr)
                if found:
                    candidates.append(found)
    active = read_json(ULTRALYTICS_ENV_FILE, {})
    payload = {"ok": True, "active": active if isinstance(active, dict) else {}, "candidates": candidates, "roots": [str(x) for x in root_paths], "updated_at": now_iso()}
    # 如果当前没有保存环境，但检测到一个，就自动设为 active，减少用户操作。
    if candidates and not payload["active"].get("python_path"):
        write_json(ULTRALYTICS_ENV_FILE, candidates[0])
        payload["active"] = candidates[0]
    return payload


_ACTIVE_ULTRA_RUNTIME_CACHE: Dict[str, Any] = {}

def get_active_ultralytics_env() -> Dict[str, Any]:
    global _ACTIVE_ULTRA_RUNTIME_CACHE
    cached=_ACTIVE_ULTRA_RUNTIME_CACHE if isinstance(_ACTIVE_ULTRA_RUNTIME_CACHE,dict) else {}
    cpy=str(cached.get("python_path") or "")
    if cpy and _path_exists(cpy): return dict(cached)
    env=read_json(ULTRALYTICS_ENV_FILE,{})
    if isinstance(env,dict):
        py=str(env.get("python_path") or "")
        if py and _path_exists(py):
            checked=_check_ultralytics_python(Path(py),Path(str(env.get("root") or BASE_DIR)))
            if checked:
                merged={**env,**checked}; _ACTIVE_ULTRA_RUNTIME_CACHE=merged; return dict(merged)
    try:
        checked=_check_ultralytics_python(Path(sys.executable),BASE_DIR)
        if checked:
            checked["name"]="平台内置 Ultralytics"; write_json(ULTRALYTICS_ENV_FILE,checked); _ACTIVE_ULTRA_RUNTIME_CACHE=checked; return dict(checked)
    except Exception: pass
    return {}
def ultralytics_runtime_python() -> str:
    env = get_active_ultralytics_env()
    if env.get("python_path"):
        return env["python_path"]
    return sys.executable


def resolve_ultralytics_model_path(model_value: str) -> str:
    value = (model_value or "").strip()
    if not value:
        return value
    if _is_absolute_path_text(value) or "/" in value or "\\" in value:
        return value
    env = get_active_ultralytics_env()
    root = env.get("root")
    if root:
        p = Path(root) / value
        if p.exists():
            return str(p)
    return value


def default_scan_roots() -> List[str]:
    """Return practical default roots for Windows first, then local dev paths."""
    roots: List[str] = []
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if Path(root).exists():
                roots.append(root)
    else:
        # For development/testing in Linux/macOS. On the user's Windows machine this branch will not be used.
        for root in [str(BASE_DIR), str(DATA_DIR), "/mnt/data", str(Path.home())]:
            if Path(root).exists() and root not in roots:
                roots.append(root)
    return roots[:8]


def normalize_scan_roots(roots: Optional[List[str]]) -> List[Path]:
    if not roots:
        roots = default_scan_roots()
    paths: List[Path] = []
    for root in roots:
        if not root:
            continue
        # 用户可能在文本框里用逗号、分号或换行混输，这里做宽松拆分。
        parts = []
        for chunk in str(root).replace(";", "\n").replace(",", "\n").splitlines():
            chunk = chunk.strip().strip('"').strip("'")
            if chunk:
                parts.append(chunk)
        for item in parts:
            path = Path(item).expanduser()
            if path.exists() and path not in paths:
                paths.append(path)
    return paths


def is_model_candidate(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in MODEL_EXTS:
        return True
    if name in MODEL_CONFIG_NAMES:
        return True
    # 飞桨/PaddleX 服务经常不是模型文件，而是 human_service.py 里 create_model("PP-YOLOE-S_human")。
    # 这里只宽松检查小型 Python 文件，避免全盘读取大文件。
    if suffix == ".py" and (name in PADDLEX_SERVICE_FILE_NAMES or "paddlex" in str(path).lower() or "yolo" in str(path).lower()):
        try:
            if path.stat().st_size > 300_000:
                return False
            text = path.read_text(encoding="utf-8", errors="ignore")[:20000].lower()
            return "paddlex" in text and "create_model" in text
        except Exception:
            return False
    return False


def classify_model_file(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    name = path.name.lower()
    path_text = str(path).lower()
    framework = "未知/通用"
    framework_key = "other"
    model_type = suffix.lstrip(".") if suffix else "config"
    trainable_current = False
    trainable_paddle = False
    inferable = False
    selectable_as_base = False
    action = "仅记录路径"
    note = ""
    detected_model_name = ""

    if suffix == ".py":
        text = ""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:50000]
        except Exception:
            pass
        match = re.search(r"create_model\(\s*[\"']([^\"']+)[\"']", text)
        detected_model_name = match.group(1) if match else ""
        framework = "PaddleX / 飞桨服务脚本"
        framework_key = "paddle_service"
        model_type = f"PaddleX 内置模型：{detected_model_name}" if detected_model_name else "PaddleX 服务脚本"
        inferable = True
        selectable_as_base = True
        action = "可登记为飞桨模型源/辅助标注服务；不是当前 Ultralytics 训练权重"
        note = "你上传的 human_service.py 就属于这种：通过 create_model 加载模型，包里没有独立训练权重文件。"
    elif suffix == ".pt":
        framework = "Ultralytics / PyTorch YOLO"
        framework_key = "ultralytics"
        model_type = "pt 训练权重"
        trainable_current = True
        inferable = True
        selectable_as_base = True
        action = "可直接作为当前平台基础模型继续训练"
        note = "适合填入训练页的“基础模型”。"
    elif suffix == ".pth":
        framework = "PyTorch 权重"
        framework_key = "pytorch"
        model_type = "pth 权重"
        inferable = False
        action = "需确认具体框架"
        note = "可能是 PyTorch 权重，但不一定是 Ultralytics YOLO，当前平台不能保证直接训练。"
    elif suffix == ".pdparams":
        framework = "PaddleDetection / 飞桨"
        framework_key = "paddle"
        model_type = "pdparams 训练权重"
        trainable_paddle = True
        inferable = False
        selectable_as_base = True
        action = "可用于 PaddleDetection/PaddleX 继续训练；不能放进 Ultralytics 训练命令"
        note = "这是飞桨训练权重，不是 Ultralytics .pt，不能直接填到当前 YOLO 训练命令里。"
    elif suffix in {".pdmodel", ".pdiparams"}:
        framework = "Paddle Inference / 飞桨推理模型"
        framework_key = "paddle_infer"
        model_type = suffix.lstrip(".")
        inferable = True
        action = "可用于飞桨推理或辅助标注"
        note = "通常是导出后的推理模型，不能直接继续训练。"
    elif suffix == ".onnx":
        framework = "ONNX 推理模型"
        framework_key = "onnx"
        model_type = "onnx"
        inferable = True
        action = "可推理/部署/辅助标注"
        note = "一般不能继续训练。"
    elif suffix == ".engine":
        framework = "TensorRT 推理模型"
        framework_key = "tensorrt"
        model_type = "engine"
        inferable = True
        action = "仅推理部署"
        note = "NVIDIA TensorRT 引擎，不能继续训练。"
    elif suffix == ".rknn":
        framework = "瑞芯微 RKNN 推理模型"
        framework_key = "rknn"
        model_type = "rknn"
        inferable = True
        action = "仅推理部署"
        note = "NPU 部署格式，不能继续训练。"
    elif suffix == ".bmodel":
        framework = "算能 BMRuntime 推理模型"
        framework_key = "sophon"
        model_type = "bmodel"
        inferable = True
        action = "仅推理部署"
        note = "算能部署格式，不能继续训练。"
    elif name in MODEL_CONFIG_NAMES:
        if "paddle" in path_text or "infer" in name or "deploy" in name:
            framework = "PaddleDetection / 飞桨配置"
            framework_key = "paddle_config"
        model_type = "配置文件"
        inferable = False
        action = "辅助识别模型包"
        note = "通常需要和 .pdmodel/.pdiparams/.pdparams 放在同一模型目录里看。"

    # 目录名/路径再辅助判断一次
    if framework == "未知/通用" and "paddle" in path_text:
        framework = "PaddleDetection / 飞桨"
        framework_key = "paddle"
    if framework == "未知/通用" and ("yolo" in path_text or name.startswith("yolo") or name in {"best.pt", "last.pt"}):
        framework = "YOLO 相关"
        framework_key = "yolo_related"

    try:
        stat = path.stat()
        size_mb = round(stat.st_size / 1024 / 1024, 2)
        updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        size_mb = 0
        updated_at = ""

    return {
        "name": path.name,
        "path": str(path),
        "dir": str(path.parent),
        "suffix": suffix,
        "framework": framework,
        "framework_key": framework_key,
        "model_type": model_type,
        "detected_model_name": detected_model_name,
        "size_mb": size_mb,
        "updated_at": updated_at,
        "trainable_current_platform": trainable_current,
        "trainable_paddle": trainable_paddle,
        "inferable": inferable,
        "selectable_as_base": selectable_as_base,
        "recommended_action": action,
        "note": note,
    }


def scan_local_models_internal(roots: Optional[List[str]], max_results: int = 3000) -> Dict[str, Any]:
    root_paths = normalize_scan_roots(roots)
    max_results = max(50, min(int(max_results or 3000), 20000))
    results: List[Dict[str, Any]] = []
    scanned_dirs = 0
    errors: List[str] = []
    start = time.time()

    for root in root_paths:
        if len(results) >= max_results:
            break
        if root.is_file():
            if is_model_candidate(root):
                results.append(classify_model_file(root))
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                scanned_dirs += 1
                # 跳过明显无关/超大的目录，避免扫盘过慢。保留 Users/工作目录/缓存目录。
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_SCAN_DIRS]
                for fn in filenames:
                    if len(results) >= max_results:
                        break
                    fp = Path(dirpath) / fn
                    if is_model_candidate(fp):
                        results.append(classify_model_file(fp))
                if len(results) >= max_results:
                    break
        except Exception as e:
            errors.append(f"{root}: {e}")

    # 去重并按可训练优先、修改时间倒序
    dedup: Dict[str, Dict[str, Any]] = {}
    for item in results:
        dedup[item["path"]] = item
    rows = list(dedup.values())
    rows.sort(key=lambda x: (not x.get("trainable_current_platform"), not x.get("trainable_paddle"), x.get("updated_at", "")), reverse=False)
    # 上面 reverse=False 会让 trainable True 靠前但更新时间旧靠前，不理想；重新显式排序
    rows.sort(key=lambda x: (1 if x.get("trainable_current_platform") else 0, 1 if x.get("trainable_paddle") else 0, x.get("updated_at", "")), reverse=True)
    payload = {
        "ok": True,
        "roots": [str(x) for x in root_paths],
        "total": len(rows),
        "scanned_dirs": scanned_dirs,
        "seconds": round(time.time() - start, 2),
        "items": rows,
        "errors": errors[:20],
        "updated_at": now_iso(),
    }
    write_json(LOCAL_MODELS_FILE, payload)
    return payload


@app.get("/api/local_models")
def list_local_models():
    data = read_json(LOCAL_MODELS_FILE, {})
    if isinstance(data, list):
        return {"ok": True, "items": data, "total": len(data), "roots": [], "updated_at": ""}
    return data or {"ok": True, "items": [], "total": 0, "roots": [], "updated_at": ""}


@app.post("/api/local_models/scan")
def scan_local_models(payload: LocalModelScanReq):
    return scan_local_models_internal(payload.roots, payload.max_results)


@app.get("/api/ultralytics_env")
def get_ultralytics_env():
    active = read_json(ULTRALYTICS_ENV_FILE, {})
    if not isinstance(active, dict):
        active = {}
    return {"ok": True, "active": active, "updated_at": now_iso()}


@app.post("/api/ultralytics_env/detect")
def detect_ultralytics_env(payload: UltralyticsEnvDetectReq):
    return detect_ultralytics_env_internal(payload.roots)


@app.post("/api/ultralytics_env/select")
def select_ultralytics_env(payload: UltralyticsEnvSelectReq):
    py = Path(payload.python_path.strip().strip('"'))
    if not py.exists():
        raise HTTPException(status_code=400, detail="python.exe 路径不存在")
    root = Path(payload.root.strip().strip('"')) if payload.root else py.parent.parent
    found = _check_ultralytics_python(py, root)
    if not found:
        raise HTTPException(status_code=400, detail="这个 Python 环境没有检测到 ultralytics 包")
    if payload.yolo_path:
        found["yolo_path"] = payload.yolo_path
    write_json(ULTRALYTICS_ENV_FILE, found)
    global _ACTIVE_ULTRA_RUNTIME_CACHE
    _ACTIVE_ULTRA_RUNTIME_CACHE = dict(found)
    return {"ok": True, "active": found}


@app.get("/api/training_catalog")
def training_catalog():
    return {"ok": True, **TRAINING_CATALOG}


@app.get("/api/base_models")
def list_base_models(project_id: Optional[str] = None):
    """训练页基础模型下拉框。区分 Ultralytics 可训练权重和飞桨模型源。"""
    items: List[Dict[str, Any]] = []
    for name in ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt"]:
        items.append({
            "label": f"官方 Ultralytics：{name}",
            "value": name,
            "source": "official",
            "framework_key": "ultralytics",
            "train_framework": "ultralytics",
            "trainable": True,
            "note": "首次训练会自动下载权重。"
        })
    active_env = get_active_ultralytics_env()
    for m in active_env.get("models", []) if isinstance(active_env.get("models", []), list) else []:
        if str(m.get("path", "")).lower().endswith(".pt"):
            items.append({
                "label": f"已检测 Ultralytics 环境模型：{m.get('name')}",
                "value": m.get("path"),
                "source": "ultralytics_env",
                "framework_key": "ultralytics",
                "train_framework": "ultralytics",
                "trainable": True,
                "note": f"来自已保存 Ultralytics 环境：{active_env.get('root', '')}"
            })
    if project_id:
        try:
            for m in list_models_internal(project_id):
                if m.get("type") == "pt":
                    items.append({
                        "label": f"当前项目模型：{m['name']}",
                        "value": m["path"],
                        "source": "project",
                        "framework_key": "ultralytics",
                        "train_framework": "ultralytics",
                        "trainable": True,
                        "note": "可基于上一次 best.pt 继续训练。"
                    })
        except Exception:
            pass
    local = read_json(LOCAL_MODELS_FILE, {})
    for m in (local.get("items", []) if isinstance(local, dict) else []):
        if m.get("trainable_current_platform"):
            items.append({
                "label": f"本机 .pt：{m.get('name')}",
                "value": m.get("path"),
                "source": "local_scan",
                "framework_key": "ultralytics",
                "train_framework": "ultralytics",
                "trainable": True,
                "note": m.get("note") or "本机路径只适合本机训练。"
            })
        elif m.get("trainable_paddle"):
            items.append({
                "label": f"本机飞桨权重：{m.get('name')}",
                "value": m.get("path"),
                "source": "local_scan",
                "framework_key": "paddle",
                "train_framework": "paddle",
                "trainable": False,
                "note": "这是飞桨训练权重，需要 PaddleX/PaddleDetection 训练执行器；不能直接用于 Ultralytics 训练。"
            })
        elif m.get("framework_key") == "paddle_service":
            model_name = m.get("detected_model_name") or "PP-YOLOE-S_human"
            items.append({
                "label": f"飞桨服务脚本：{model_name}",
                "value": model_name,
                "source": "local_scan",
                "framework_key": "paddle_service",
                "train_framework": "paddle",
                "trainable": False,
                "note": "这是通过 create_model 加载的服务脚本，可用于推理/预标注；不是独立训练权重。"
            })
    return {"ok": True, "items": items}




def _remote_capabilities(server: Dict[str, Any]) -> Dict[str, Any]:
    base_url = str(server.get("base_url", "")).rstrip("/")
    if not base_url:
        return {"ok": False, "error": "服务器地址为空"}
    try:
        headers = {"X-API-Key": server.get("api_key", "") or ""}
        r = requests.get(f"{base_url}/api/remote/health", headers=headers, timeout=4)
        r.raise_for_status()
        data = r.json()
        # 兼容旧版远程服务：没有 capabilities 时给默认 Ultralytics 能力
        if "algorithms" not in data:
            data["algorithms"] = [
                {"key":"yolo11n_det","name":"YOLO11n 目标检测","framework":"ultralytics","base_model":"yolo11n.pt","default_epochs":30,"default_imgsz":640,"default_batch":4},
                {"key":"yolo11s_det","name":"YOLO11s 目标检测","framework":"ultralytics","base_model":"yolo11s.pt","default_epochs":50,"default_imgsz":640,"default_batch":4},
                {"key":"yolo11m_det","name":"YOLO11m 目标检测","framework":"ultralytics","base_model":"yolo11m.pt","default_epochs":80,"default_imgsz":640,"default_batch":2},
            ]
        if "base_models" not in data:
            data["base_models"] = [
                {"label":"yolo11n.pt","value":"yolo11n.pt","framework":"ultralytics"},
                {"label":"yolo11s.pt","value":"yolo11s.pt","framework":"ultralytics"},
                {"label":"yolo11m.pt","value":"yolo11m.pt","framework":"ultralytics"},
            ]
        return {"ok": True, **data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/training_options")
def training_options(project_id: Optional[str] = None):
    """给训练页用：先读已接入训练环境，再按环境返回可用算法/模型。前端不再硬编码训练算法。"""
    options: List[Dict[str, Any]] = []
    # 本机 Ultralytics
    ultra = get_active_ultralytics_env()
    if ultra:
        algs = [a for a in TRAINING_CATALOG["algorithms"] if a.get("framework") == "ultralytics"]
        models = []
        for m in ultra.get("models", []) if isinstance(ultra.get("models", []), list) else []:
            if str(m.get("path", "")).lower().endswith(".pt"):
                models.append({"label": m.get("name") or Path(m.get("path", "")).name, "value": m.get("path"), "framework":"ultralytics", "source":"env"})
        # 不在页面硬塞所有官方模型。训练算法/权重优先来自已检测环境或项目模型。
        # 如果环境里一个 .pt 都没有，才给一个 YOLO11n 默认兜底（Ultralytics 首次训练可自动下载）。
        if not models:
            models.append({"label": "yolo11n.pt（默认，可自动下载）", "value": "yolo11n.pt", "framework":"ultralytics", "source":"official"})
        if project_id:
            try:
                for m in list_models_internal(project_id):
                    if m.get("type") == "pt":
                        models.append({"label": f"项目模型：{m.get('name')}", "value": m.get("path"), "framework":"ultralytics", "source":"project"})
            except Exception:
                pass
        # 训练算法从当前训练资源读取。Ultralytics 本质是同一个 detect 训练器，yolo11n/s/m 是基础权重/模型规模。
        available = " ".join([str(x.get("label", "")) + " " + str(x.get("value", "")) for x in models]).lower()
        algs = []
        for a in [x for x in TRAINING_CATALOG["algorithms"] if x.get("framework") == "ultralytics"]:
            bm = str(a.get("base_model", "")).lower()
            if bm and (bm in available or not models):
                algs.append(a)
        if not algs:
            algs = [a for a in TRAINING_CATALOG["algorithms"] if a.get("key") == "yolo11n_det"]
        options.append({
            "id":"local_ultralytics",
            "name": ultra.get("name") or "本机 Ultralytics",
            "type":"local",
            "framework":"ultralytics",
            "status":"ready",
            "python_path": ultra.get("python_path"),
            "root": ultra.get("root"),
            "version": ultra.get("version"),
            "algorithms": algs,
            "base_models": models,
        })
    # 本机飞桨：v21 起不再写死 PP-YOLOE，而是扫描 PaddleDetection/configs 下真实可训练配置。
    paddle = get_active_paddle_env()
    if paddle and (paddle.get("python_path") or paddle.get("paddledet_dir") or paddle.get("paddlex_dir")):
        py_ok = bool(paddle.get("python_path") and Path(paddle.get("python_path", "")).exists())
        pd_dir = paddle.get("paddledet_dir", "")
        scan = scan_paddledet_algorithms(pd_dir) if pd_dir else {"ok": False, "items": [], "error": "未配置 PaddleDetection 目录"}
        algs = scan.get("items", []) or [a for a in TRAINING_CATALOG["algorithms"] if a.get("framework") == "paddle"]
        weights = [{"label": "使用配置默认预训练权重 / 自动下载", "value": "", "framework":"paddle", "source":"default"}]
        weights.extend(scan_paddle_weights(pd_dir))
        status = "ready" if py_ok and scan.get("ok") and algs else ("warning" if py_ok else "offline")
        options.append({
            "id":"local_paddle",
            "name": paddle.get("name") or "本机飞桨",
            "type":"local",
            "framework":"paddle",
            "status": status,
            "python_path": paddle.get("python_path"),
            "paddledet_dir": pd_dir,
            "paddlex_dir": paddle.get("paddlex_dir"),
            "algorithms": algs,
            "base_models": weights,
            "scan": {"ok": scan.get("ok"), "total": scan.get("total", 0), "families": scan.get("families", {}), "error": scan.get("error", "")},
        })
    # 远程训练服务器
    for s in read_json(SERVERS_FILE, []):
        caps = _remote_capabilities(s)
        options.append({
            "id": f"server:{s.get('id')}",
            "server_id": s.get("id"),
            "name": s.get("name") or s.get("base_url"),
            "type":"server",
            "framework": caps.get("framework", "ultralytics") if caps.get("ok") else "unknown",
            "status":"ready" if caps.get("ok") else "offline",
            "base_url": s.get("base_url"),
            "error": caps.get("error"),
            "algorithms": caps.get("algorithms", []),
            "base_models": caps.get("base_models", []),
        })
    return {"ok": True, "targets": options}


class TrainServerReq(BaseModel):
    name: str
    base_url: str
    api_key: Optional[str] = ""




class PaddleEnvReq(BaseModel):
    name: str = "本机飞桨"
    python_path: Optional[str] = ""
    paddledet_dir: Optional[str] = ""
    paddlex_dir: Optional[str] = ""


def get_active_paddle_env() -> Dict[str, Any]:
    env = read_json(PADDLE_ENV_FILE, {})
    if not isinstance(env, dict):
        return {}
    return env


@app.get("/api/paddle_env")
def get_paddle_env():
    return {"ok": True, "active": get_active_paddle_env(), "updated_at": now_iso()}


@app.post("/api/paddle_env/select")
def select_paddle_env(payload: PaddleEnvReq):
    env = {
        "name": payload.name or "本机飞桨",
        "python_path": (payload.python_path or sys.executable).strip().strip('"'),
        "paddledet_dir": (payload.paddledet_dir or r"D:\PaddleDetection").strip().strip('"'),
        "paddlex_dir": (payload.paddlex_dir or r"D:\PaddleX").strip().strip('"'),
        "updated_at": now_iso(),
    }
    if env["python_path"] and not Path(env["python_path"]).exists():
        raise HTTPException(status_code=400, detail="飞桨 Python 路径不存在")
    if env["paddledet_dir"] and not Path(env["paddledet_dir"]).exists():
        # 允许先保存但标记不可训练，避免用户只是先配置地址
        env["warning"] = "PaddleDetection 目录不存在，飞桨训练会失败；请先安装或修正目录。"
    else:
        scan = scan_paddledet_algorithms(env.get("paddledet_dir", ""))
        env["algorithm_scan"] = {"ok": scan.get("ok"), "total": scan.get("total", 0), "families": scan.get("families", {}), "error": scan.get("error", "")}
    write_json(PADDLE_ENV_FILE, env)
    return {"ok": True, "active": env}


@app.post("/api/paddle_env/test")
def test_paddle_env(payload: PaddleEnvReq):
    py = (payload.python_path or sys.executable).strip().strip('"')
    if not Path(py).exists():
        raise HTTPException(status_code=400, detail="Python 路径不存在")
    code = "import json\nmods={}\nfor m in ['paddle','paddlex']:\n    try:\n        mod=__import__(m); mods[m]=getattr(mod,'__version__','installed')\n    except Exception as e:\n        mods[m]='missing:'+str(e)\nprint(json.dumps(mods, ensure_ascii=False))"
    try:
        cp = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=20)
        out = (cp.stdout or cp.stderr or "").strip()
        data = json.loads(out.splitlines()[-1]) if out else {}
        alg_scan = scan_paddledet_algorithms(payload.paddledet_dir or "") if payload.paddledet_dir else {"ok": False, "items": [], "total": 0, "families": {}, "error": "未填写 PaddleDetection 目录"}
        return {"ok": True, "python_path": py, "modules": data, "paddledet_exists": Path(payload.paddledet_dir or "").exists(), "paddlex_exists": Path(payload.paddlex_dir or "").exists(), "algorithm_scan": {"ok": alg_scan.get("ok"), "total": alg_scan.get("total",0), "families": alg_scan.get("families",{}), "error": alg_scan.get("error","")}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"检测失败：{e}")


def default_paddle_roots() -> List[str]:
    roots: List[str] = []
    if os.name == "nt":
        roots.extend([
            r"D:\PaddleDetection",
            r"D:\PaddleX",
            r"D:\lab\PaddleDetection",
            r"D:\lab\PaddleX",
            r"D:\lab\yolosuanfa",
            str(BASE_DIR),
        ])
        for letter in "DECF":
            root = Path(f"{letter}:\\")
            if root.exists():
                roots.append(str(root))
    else:
        roots.extend([str(BASE_DIR), str(Path.home()), "/mnt/data"])
    out=[]
    for r in roots:
        if r and r not in out:
            out.append(r)
    return out[:12]


def _detect_paddle_candidate(root: Path) -> Optional[Dict[str, Any]]:
    python_paths = _candidate_python_paths(root)
    if root.is_file() and root.name.lower() in {"python.exe", "python"}:
        python_paths = [root]
    # 如果用户填的是 PaddleDetection 目录，本身可能没有 venv，兜底用当前 Python 做模块检测。
    if not python_paths and root.exists():
        python_paths = [Path(sys.executable)]
    paddledet_dir = ""
    paddlex_dir = ""
    if root.exists() and root.is_dir():
        candidates = [root, root / "PaddleDetection", root.parent / "PaddleDetection"]
        paddledet_dir = str(next((x for x in candidates if (x / "tools" / "train.py").exists()), ""))
        x_candidates = [root, root / "PaddleX", root.parent / "PaddleX"]
        paddlex_dir = str(next((x for x in x_candidates if x.exists() and ("paddlex" in x.name.lower() or (x / "paddlex").exists())), ""))
    for py in python_paths[:3]:
        if not py.exists():
            continue
        mods = test_paddle_env(PaddleEnvReq(python_path=str(py), paddledet_dir=paddledet_dir, paddlex_dir=paddlex_dir))
        module_info = mods.get("modules", {})
        has_paddle = str(module_info.get("paddle", "")).startswith("missing:") is False and bool(module_info.get("paddle"))
        has_paddlex = str(module_info.get("paddlex", "")).startswith("missing:") is False and bool(module_info.get("paddlex"))
        if has_paddle or has_paddlex or paddledet_dir or paddlex_dir:
            return {
                "name": "本机飞桨",
                "python_path": str(py),
                "paddledet_dir": paddledet_dir,
                "paddlex_dir": paddlex_dir,
                "modules": module_info,
                "paddle_version": module_info.get("paddle", ""),
                "paddlex_version": module_info.get("paddlex", ""),
                "algorithm_scan": scan_paddledet_algorithms(paddledet_dir) if paddledet_dir else {"ok": False, "total": 0, "families": {}},
                "status": "ready" if has_paddle or has_paddlex else "warning",
                "root": str(root),
            }
    return None



@app.get("/api/paddle_env/algorithms")
def list_paddle_env_algorithms():
    env = get_active_paddle_env()
    scan = scan_paddledet_algorithms(env.get("paddledet_dir", "")) if env.get("paddledet_dir") else {"ok": False, "items": [], "total": 0, "families": {}, "error": "未配置 PaddleDetection 目录"}
    return {"ok": True, **scan}


@app.post("/api/paddle_env/algorithms/scan")
def scan_paddle_env_algorithms(payload: PaddleEnvReq):
    scan = scan_paddledet_algorithms(payload.paddledet_dir or "")
    return {"ok": True, **scan}


class PaddleDetectReq(BaseModel):
    roots: Optional[List[str]] = None


@app.post("/api/paddle_env/detect")
def detect_paddle_env(payload: PaddleDetectReq):
    roots = payload.roots or default_paddle_roots()
    candidates=[]
    seen=set()
    for r in roots:
        if not r:
            continue
        root = Path(str(r).strip().strip('"')).expanduser()
        key=str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            c=_detect_paddle_candidate(root)
            if c:
                candidates.append(c)
        except Exception:
            pass
        if len(candidates)>=10:
            break
    active = candidates[0] if candidates else {}
    return {"ok": True, "candidates": candidates, "active": active}

@app.get("/api/train_servers")
def list_train_servers():
    return read_json(SERVERS_FILE, [])


@app.post("/api/train_servers")
def save_train_server(payload: TrainServerReq):
    name = payload.name.strip()
    base_url = payload.base_url.strip().rstrip("/")
    if not name or not base_url:
        raise HTTPException(status_code=400, detail="服务器名称和地址不能为空")
    servers = read_json(SERVERS_FILE, [])
    server_id = uuid.uuid4().hex[:10]
    item = {"id": server_id, "name": name, "base_url": base_url, "api_key": payload.api_key or "", "created_at": now_iso()}
    servers.insert(0, item)
    write_json(SERVERS_FILE, servers[:20])
    return item


@app.delete("/api/train_servers/{server_id}")
def delete_train_server(server_id: str):
    servers = [s for s in read_json(SERVERS_FILE, []) if s.get("id") != server_id]
    write_json(SERVERS_FILE, servers)
    return {"ok": True}


@app.post("/api/train_servers/test")
def test_train_server(payload: TrainServerReq):
    base_url = payload.base_url.strip().rstrip("/")
    try:
        headers = {"X-API-Key": payload.api_key or ""}
        r = requests.get(f"{base_url}/api/remote/health", headers=headers, timeout=8)
        r.raise_for_status()
        return {"ok": True, "response": r.json()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败：{e}")


class TrainReq(BaseModel):
    framework: str = "ultralytics"  # ultralytics / paddle
    algorithm: Optional[str] = "yolo11n_det"
    algorithm_asset_id: Optional[str] = ""
    model: str = "yolo11n.pt"
    epochs: int = 50
    imgsz: int = 640
    batch: int = 8
    device: str = "cpu"
    train_ratio: float = 0.8
    include_empty: bool = False
    dataset_id: Optional[str] = None
    target: str = "local"  # local / remote
    server_id: Optional[str] = None
    remote_url: Optional[str] = None
    api_key: Optional[str] = ""
    paddle_command: Optional[str] = ""
    # v20 进阶训练参数，Ultralytics 本机训练生效。
    patience: int = 100
    workers: int = 0
    optimizer: str = "auto"
    lr0: float = 0.01
    lrf: float = 0.01
    weight_decay: float = 0.0005
    close_mosaic: int = 10
    mosaic: float = 1.0
    cache: str = "False"
    single_cls: bool = False
    pretrained: bool = True
    rect: bool = False
    amp: bool = True
    cos_lr: bool = False
    freeze: int = 0
    # v42.5 更完整的 Ultralytics 训练配置。保持官方默认值，普通用户可直接使用默认配置。
    momentum: float = 0.937
    warmup_epochs: float = 3.0
    save_period: int = -1
    seed: int = 0
    deterministic: bool = True
    multi_scale: float = 0.0
    hsv_h: float = 0.015
    hsv_s: float = 0.7
    hsv_v: float = 0.4
    degrees: float = 0.0
    translate: float = 0.1
    scale: float = 0.5
    shear: float = 0.0
    perspective: float = 0.0
    flipud: float = 0.0
    fliplr: float = 0.5
    mixup: float = 0.0
    # 飞桨专用：平台会按小数据集/CPU自动生成安全覆盖项。
    paddle_lr: Optional[float] = None
    # 飞桨专用：是否在训练过程中启用 COCO 评估。默认关闭，避免小数据集/类别映射中断训练。
    paddle_eval: bool = False
    # v42.4 数据选择与阶段质量门禁
    train_labels: Optional[List[str]] = None
    val_labels: Optional[List[str]] = None
    train_image_ids: Optional[List[str]] = None
    val_image_ids: Optional[List[str]] = None
    train_max_samples: int = 0
    val_max_samples: int = 0
    eval_interval: int = 0
    eval_metric: str = "map50"
    continue_threshold: float = 0.0
    stop_threshold: float = 0.0
    auto_supplement: bool = False
    supplement_count: int = 0
    # v42.7 AI mid-training intervention. The AI is advisory within constrained actions; Ground Truth metrics stay authoritative.
    ai_intervention_enabled: bool = False
    ai_intervention_epochs: Optional[List[int]] = None
    ai_model_config_id: Optional[str] = ""
    ai_eval_samples: int = 20
    ai_action_mode: str = "auto"  # auto / advise
    ai_extra_epochs: int = 20
    ai_max_rounds: int = 1
    # v42.8：训练任务队列与训练完成后的自动转换。
    queue_priority: int = 50
    auto_convert_targets: Optional[List[str]] = None


def validate_train_request(payload: TrainReq):
    """Fail before spawning a training process, so invalid UI values never become opaque worker errors."""
    if int(payload.epochs) < 1:
        raise HTTPException(status_code=400, detail="训练轮次 epochs 必须大于等于 1")
    if int(payload.imgsz) < 32:
        raise HTTPException(status_code=400, detail="图片尺寸 imgsz 不能小于 32")
    if int(payload.batch) == 0 or int(payload.batch) < -1:
        raise HTTPException(status_code=400, detail="batch 只能是正整数或 -1（Ultralytics 自动批大小）")
    if int(payload.patience) < 0:
        raise HTTPException(status_code=400, detail="patience 不能小于 0")
    if int(payload.workers) < 0:
        raise HTTPException(status_code=400, detail="workers 不能小于 0")
    allowed_optimizers = {"auto", "sgd", "adam", "adamw", "nadam", "radam", "rmsprop"}
    if str(payload.optimizer or "auto").strip().lower() not in allowed_optimizers:
        raise HTTPException(status_code=400, detail="不支持的 optimizer。可选：auto / SGD / Adam / AdamW / NAdam / RAdam / RMSProp")
    if not (0 < float(payload.lr0) <= 1):
        raise HTTPException(status_code=400, detail="lr0 必须在 0~1 之间")
    if not (0 <= float(payload.lrf) <= 1):
        raise HTTPException(status_code=400, detail="lrf 必须在 0~1 之间")
    if float(payload.weight_decay) < 0:
        raise HTTPException(status_code=400, detail="weight_decay 不能小于 0")
    if int(payload.close_mosaic) < 0:
        raise HTTPException(status_code=400, detail="close_mosaic 不能小于 0")
    if not (0 <= float(payload.mosaic) <= 1):
        raise HTTPException(status_code=400, detail="mosaic 必须在 0~1 之间")
    if int(payload.freeze) < 0:
        raise HTTPException(status_code=400, detail="freeze 不能小于 0")
    if not (0 <= float(payload.momentum) <= 1):
        raise HTTPException(status_code=400, detail="momentum 必须在 0~1 之间")
    if float(payload.warmup_epochs) < 0:
        raise HTTPException(status_code=400, detail="warmup_epochs 不能小于 0")
    if float(payload.multi_scale) < 0 or float(payload.multi_scale) > 1:
        raise HTTPException(status_code=400, detail="multi_scale 必须在 0~1 之间")
    for name in ["hsv_h","hsv_s","hsv_v","translate","scale","perspective","flipud","fliplr","mixup"]:
        value=float(getattr(payload,name))
        if value < 0 or value > 1:
            raise HTTPException(status_code=400, detail=f"{name} 必须在 0~1 之间")
    if int(payload.eval_interval) < 0 or int(payload.val_max_samples) < 0:
        raise HTTPException(status_code=400, detail="阶段检查轮次和试验集抽查数量不能小于 0")
    if payload.continue_threshold and payload.stop_threshold and float(payload.continue_threshold) >= float(payload.stop_threshold):
        raise HTTPException(status_code=400, detail="继续训练下限必须小于提前完成阈值")
    # v42.8 起训练阶段不再支持 AI 中途介入；质量门禁完全由试验集 Ground Truth 指标决定。
    payload.ai_intervention_enabled = False
    payload.ai_intervention_epochs = []
    payload.ai_model_config_id = ""
    if int(payload.queue_priority or 0) < 0 or int(payload.queue_priority or 0) > 999:
        raise HTTPException(status_code=400, detail="任务优先级必须在 0~999 之间")
    allowed_auto = {"ascend", "rockchip", "sophon"}
    bad_auto = [x for x in (payload.auto_convert_targets or []) if x not in allowed_auto]
    if bad_auto:
        raise HTTPException(status_code=400, detail="自动转换仅支持：华为 Atlas / 瑞芯微 / 算能")
    cache = str(payload.cache).strip().lower()
    if cache not in {"false", "true", "0", "1", "ram", "disk", "none", ""}:
        raise HTTPException(status_code=400, detail="cache 只支持：关闭 / 内存缓存 / 磁盘缓存")


def check_ultralytics_train_runtime(python_path: str):
    """Quick import test before creating a job. It catches broken external environments immediately."""
    try:
        cp = subprocess.run(
            [python_path, "-c", "import torch, torchvision, ultralytics; from ultralytics import YOLO; print(torch.__version__, torchvision.__version__, ultralytics.__version__)"],
            cwd=str(BASE_DIR), capture_output=True, text=True, errors="replace", timeout=30,
            env={**os.environ.copy(), "PYTHONUTF8":"1", "PYTHONIOENCODING":"utf-8"},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"训练环境检查失败：{e}")
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "未知错误").strip().splitlines()
        raise HTTPException(status_code=400, detail="训练环境不可用：" + " | ".join(detail[-5:]))
    return (cp.stdout or "").strip()


def _safe_paddle_lr(payload_lr: float, image_count: int = 0, is_cpu: bool = True) -> float:
    """PaddleDetection 原始 COCO 配置学习率通常偏高；小数据/CPU默认降到安全值。"""
    try:
        lr = float(payload_lr or 0)
    except Exception:
        lr = 0.0
    # 用户未设置、设置过高、或数据量很小时，一律用保守学习率，避免 NaN。
    if lr <= 0 or lr >= 0.01 or image_count < 200 or is_cpu:
        return 0.001
    return max(1e-5, min(lr, 0.005))


def _paddle_family_key(alg: Optional[Dict[str, Any]]) -> str:
    return str((alg or {}).get("family_key") or (alg or {}).get("family") or "").lower().replace("-", "_")


@app.post("/api/projects/{project_id}/train/start")
def start_train(project_id: str, payload: TrainReq):
    get_project(project_id)
    validate_train_request(payload)
    p = project_dir(project_id)
    framework = (payload.framework or "ultralytics").strip().lower()
    iteration_base = _v54_iteration_base(project_id, payload.algorithm_asset_id or "", framework)
    model_value = (iteration_base or {}).get("path") or (payload.model or "").strip()
    alg = get_algorithm_config(payload.algorithm or "")
    if not alg and framework == "paddle":
        alg = get_paddle_algorithm_by_key(payload.algorithm or "")
    if alg and alg.get("framework") != framework:
        raise HTTPException(status_code=400, detail="训练算法与训练框架不匹配，请重新选择。")
    # Ultralytics needs a default .pt model. PaddleDetection must keep this empty unless user selected a real .pdparams.
    # If we put the yml file name here, PaddleDetection will receive pretrain_weights=xxx.yml and fail/behave incorrectly.
    if not model_value and alg and framework == "ultralytics":
        model_value = alg.get("base_model") or ""

    if framework not in {"ultralytics", "paddle"}:
        raise HTTPException(status_code=400, detail="训练框架只支持 ultralytics 或 paddle")

    if framework == "ultralytics":
        if model_value.lower().endswith((".pdparams", ".pdmodel", ".pdiparams", ".onnx", ".engine", ".rknn", ".bmodel")) or model_value.startswith("PP-"):
            raise HTTPException(
                status_code=400,
                detail="这个基础模型不是 Ultralytics .pt 训练权重，不能用于当前 YOLO 训练。请选择 yolo11n.pt、项目 best.pt 或本机扫描到的 .pt。",
            )
        model_value = resolve_ultralytics_model_path(model_value)
        build = build_dataset(project_id, BuildDatasetReq(train_ratio=payload.train_ratio, include_empty=payload.include_empty, dataset_id=payload.dataset_id))
    else:
        if payload.target == "remote":
            raise HTTPException(status_code=400, detail="当前飞桨训练执行器先支持本机命令模式；远程飞桨训练后续可用训练服务器单独部署。")
        cmd_tmpl = (payload.paddle_command or "").strip()
        if not cmd_tmpl and alg:
            cmd_tmpl = alg.get("command_template", "")
        if not cmd_tmpl:
            raise HTTPException(
                status_code=400,
                detail="当前飞桨算法没有可用训练模板。请先在训练页选择 PP-YOLOE/PP-YOLOE+ 等预置算法，或切换到 Ultralytics。",
            )
        payload.paddle_command = cmd_tmpl
        build = build_paddle_dataset_internal(project_id, payload.train_ratio, payload.include_empty, payload.dataset_id)

    job_id = uuid.uuid4().hex[:12]
    job_dir = p / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    job_file = job_dir / "job.json"
    log_file = job_dir / "train.log"
    prefix = "paddle" if framework == "paddle" else "train"
    run_name = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    asset_algorithm = next((x for x in list_algorithms_internal(project_id) if x.get("id") == (payload.algorithm_asset_id or "")), None)
    job = {
        "id": job_id,
        "project_id": project_id,
        "asset_algorithm_id": (asset_algorithm or {}).get("id", ""),
        "asset_algorithm_name": (asset_algorithm or {}).get("name", ""),
        "status": "queued",
        "target": payload.target,
        "framework": framework,
        "algorithm": payload.algorithm or "",
        "algorithm_name": (alg or {}).get("name", ""),
        "algorithm_config_path": (alg or {}).get("config_path", ""),
        "algorithm_family": (alg or {}).get("family", ""),
        "model": model_value or ("使用配置默认预训练权重 / 自动下载" if framework == "paddle" else model_value),
        "epochs": max(1, int(payload.epochs)),
        "imgsz": max(128, int(payload.imgsz)),
        "batch": int(payload.batch),
        "device": payload.device,
        "run_name": run_name,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "log_file": str(log_file),
        "message": "等待启动",
    }
    if framework == "ultralytics":
        active_env = get_active_ultralytics_env()
        if active_env:
            job["ultralytics_env"] = {"python_path": active_env.get("python_path"), "root": active_env.get("root"), "version": active_env.get("version")}
    if framework == "paddle":
        job["paddle_command"] = payload.paddle_command
        job["num_classes"] = len(build.get("labels", []) or [])
        job["labels"] = build.get("labels", [])
        job["paddle_lr0"] = _safe_paddle_lr(payload.lr0, int((build.get("counts") or {}).get("train", 0)), str(payload.device).lower() == "cpu")
        job["paddle_eval"] = bool(payload.paddle_eval)
        job["dataset_counts"] = build.get("counts", {})
    write_json(job_file, job)
    add_job_to_index(project_id, job)

    if framework == "ultralytics" and payload.target == "remote":
        server = resolve_server(payload)
        dataset_zip = job_dir / "dataset.zip"
        zip_dir(p / "dataset", dataset_zip)
        try:
            with dataset_zip.open("rb") as fp:
                files = {"dataset_zip": ("dataset.zip", fp, "application/zip")}
                model_fp = None
                model_path = Path(model_value)
                if model_path.is_file():
                    model_fp = model_path.open("rb")
                    files["model_file"] = (model_path.name, model_fp, "application/octet-stream")
                data = {
                    "model": model_path.name if model_fp else model_value,
                    "epochs": str(job["epochs"]), "imgsz": str(job["imgsz"]), "batch": str(job["batch"]),
                    "device": payload.device, "run_name": run_name,
                    "patience": str(payload.patience), "workers": str(payload.workers), "optimizer": payload.optimizer or "auto",
                    "lr0": str(payload.lr0), "lrf": str(payload.lrf), "weight_decay": str(payload.weight_decay),
                    "close_mosaic": str(payload.close_mosaic), "mosaic": str(payload.mosaic), "cache": str(payload.cache),
                    "single_cls": str(payload.single_cls).lower(), "pretrained": str(payload.pretrained).lower(), "rect": str(payload.rect).lower(),
                    "amp": str(payload.amp).lower(), "cos_lr": str(payload.cos_lr).lower(), "freeze": str(payload.freeze),
                    "momentum": str(payload.momentum), "warmup_epochs": str(payload.warmup_epochs), "save_period": str(payload.save_period),
                    "seed": str(payload.seed), "deterministic": str(payload.deterministic).lower(), "multi_scale": str(payload.multi_scale),
                    "hsv_h": str(payload.hsv_h), "hsv_s": str(payload.hsv_s), "hsv_v": str(payload.hsv_v),
                    "degrees": str(payload.degrees), "translate": str(payload.translate), "scale": str(payload.scale),
                    "shear": str(payload.shear), "perspective": str(payload.perspective), "flipud": str(payload.flipud),
                    "fliplr": str(payload.fliplr), "mixup": str(payload.mixup),
                }
                headers = {"X-API-Key": server.get("api_key", "")}
                try:
                    r = requests.post(f"{server['base_url'].rstrip('/')}/api/remote/train", data=data, files=files, headers=headers, timeout=120)
                finally:
                    if model_fp:
                        model_fp.close()
                r.raise_for_status()
                remote = r.json()
            job.update({
                "status": "running",
                "message": "远程训练已启动",
                "remote": {"server_id": server.get("id"), "name": server.get("name"), "base_url": server["base_url"], "api_key": server.get("api_key", ""), "job_id": remote.get("job_id")},
                "updated_at": now_iso(),
            })
            write_json(job_file, job)
            sync_jobs_index(project_id)
            return {"ok": True, "job": job, "dataset": build}
        except Exception as e:
            job.update({"status": "failed", "message": f"远程训练启动失败：{e}", "updated_at": now_iso()})
            write_json(job_file, job); sync_jobs_index(project_id)
            raise HTTPException(status_code=500, detail=job["message"])

    if framework == "paddle":
        cmd = [
            sys.executable,
            str(BASE_DIR / "paddle_worker.py"),
            "--project-dir", str(p),
            "--dataset-dir", build["dataset"],
            "--train-json", build["train_json"],
            "--val-json", build["val_json"],
            "--label-list", build["label_list"],
            "--model", model_value,
            "--epochs", str(job["epochs"]),
            "--batch", str(job["batch"]),
            "--device", payload.device,
            "--job-id", job_id,
            "--run-name", run_name,
            "--command-template", payload.paddle_command or "",
            "--num-classes", str(len(build.get("labels", []) or [])),
            "--family", _paddle_family_key(alg),
            "--lr0", str(_safe_paddle_lr(payload.lr0, int((build.get("counts") or {}).get("train", 0)), str(payload.device).lower() == "cpu")),
        ]
        if bool(payload.paddle_eval):
            cmd.append("--enable-eval")
    else:
        cmd = [
            ultralytics_runtime_python(),
            str(BASE_DIR / "train_worker.py"),
            "--project-dir", str(p),
            "--data", build["data_yaml"],
            "--model", model_value,
            "--epochs", str(job["epochs"]),
            "--imgsz", str(job["imgsz"]),
            "--batch", str(job["batch"]),
            "--device", payload.device,
            "--job-id", job_id,
            "--run-name", run_name,
            "--patience", str(payload.patience), "--workers", str(payload.workers), "--optimizer", payload.optimizer or "auto",
            "--lr0", str(payload.lr0), "--lrf", str(payload.lrf), "--weight-decay", str(payload.weight_decay),
            "--close-mosaic", str(payload.close_mosaic), "--mosaic", str(payload.mosaic), "--cache", str(payload.cache),
            "--single-cls", str(payload.single_cls).lower(), "--pretrained", str(payload.pretrained).lower(), "--rect", str(payload.rect).lower(),
            "--amp", str(payload.amp).lower(), "--cos-lr", str(payload.cos_lr).lower(), "--freeze", str(payload.freeze),
        ]
    proc_env = os.environ.copy()
    proc_env.setdefault("PYTHONIOENCODING", "utf-8")
    proc_env.setdefault("PYTHONUTF8", "1")
    if framework == "paddle":
        penv = get_active_paddle_env()
        if penv.get("paddledet_dir"):
            proc_env["PADDLEDETECTION_DIR"] = penv.get("paddledet_dir", "")
        if penv.get("paddlex_dir"):
            proc_env["PADDLEX_DIR"] = penv.get("paddlex_dir", "")
        if penv.get("python_path"):
            proc_env["PADDLE_PYTHON"] = penv.get("python_path", "")
            job["paddle_env"] = penv
            write_json(job_file, job)
    if framework == "ultralytics":
        job["runtime_check"] = check_ultralytics_train_runtime(ultralytics_runtime_python())
        write_json(job_file, job)
    with log_file.open("ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(BASE_DIR), env=proc_env)
    PROCESS_REGISTRY[job_id] = proc
    job.update({"status": "running", "message": "训练已启动", "pid": proc.pid, "started_at": now_iso(), "updated_at": now_iso()})
    write_json(job_file, job)
    sync_jobs_index(project_id)
    return {"ok": True, "job": job, "dataset": build}


def resolve_server(payload: TrainReq) -> Dict[str, Any]:
    servers = read_json(SERVERS_FILE, [])
    if payload.server_id:
        server = next((s for s in servers if s.get("id") == payload.server_id), None)
        if not server:
            raise HTTPException(status_code=400, detail="训练服务器不存在")
        return server
    if payload.remote_url:
        return {"id": "manual", "name": "手动地址", "base_url": payload.remote_url.strip().rstrip("/"), "api_key": payload.api_key or ""}
    raise HTTPException(status_code=400, detail="请选择或填写远程训练服务器")


def add_job_to_index(project_id: str, job: Dict[str, Any]):
    jobs_index_file = project_dir(project_id) / "jobs" / "index.json"
    jobs = read_json(jobs_index_file, [])
    jobs.insert(0, job)
    write_json(jobs_index_file, jobs[:50])


@app.get("/api/projects/{project_id}/jobs")
def list_jobs(project_id: str):
    get_project(project_id)
    sync_jobs_index(project_id)
    try: _v48_dispatch_training_queues(project_id)
    except Exception: pass
    sync_jobs_index(project_id)
    rows = read_json(project_dir(project_id) / "jobs" / "index.json", [])
    out=[]
    for row in rows:
        jf=project_dir(project_id)/"jobs"/str(row.get("id") or "")/"job.json"
        full=read_json(jf,row) if jf.exists() else row
        full=enrich_job_runtime(project_id,full)
        if jf.exists(): write_json(jf,full)
        out.append(full)
    return out


@app.get("/api/projects/{project_id}/jobs/{job_id}")
def job_status(project_id: str, job_id: str):
    get_project(project_id)
    job_file = project_dir(project_id) / "jobs" / job_id / "job.json"
    if not job_file.exists():
        raise HTTPException(status_code=404, detail="训练任务不存在")
    job = read_json(job_file, {})
    if job.get("target") == "remote" and job.get("status") in {"queued", "running"}:
        job = sync_remote_job(project_id, job_id)
    job = enrich_job_runtime(project_id, job)
    write_json(job_file, job)
    try: _v48_dispatch_training_queues(project_id)
    except Exception: pass
    sync_jobs_index(project_id)
    return read_json(job_file, job)


@app.get("/api/projects/{project_id}/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(project_id: str, job_id: str):
    get_project(project_id)
    job = read_json(project_dir(project_id) / "jobs" / job_id / "job.json", {})
    if job.get("target") == "remote" and job.get("status") in {"queued", "running"}:
        job = sync_remote_job(project_id, job_id)
    log_file = project_dir(project_id) / "jobs" / job_id / "train.log"
    if not log_file.exists():
        return "暂无日志"
    text = log_file.read_text(encoding="utf-8", errors="ignore")
    return text[-80000:]


@app.post("/api/projects/{project_id}/jobs/{job_id}/stop")
def stop_job(project_id: str, job_id: str):
    get_project(project_id)
    job_file = project_dir(project_id) / "jobs" / job_id / "job.json"
    job = read_json(job_file, {})
    if job.get("target") == "remote" and job.get("remote"):
        try:
            remote = job["remote"]
            headers = {"X-API-Key": remote.get("api_key", "")}
            requests.post(f"{remote['base_url'].rstrip('/')}/api/remote/jobs/{remote['job_id']}/stop", headers=headers, timeout=8)
        except Exception:
            pass
        job.update({"status": "stopped", "message": "用户手动停止远程训练", "updated_at": now_iso()})
        write_json(job_file, job); sync_jobs_index(project_id)
        return {"ok": True}
    proc = PROCESS_REGISTRY.get(job_id)
    if proc:
        proc.terminate(); time.sleep(1)
        if proc.poll() is None:
            proc.kill()
        PROCESS_REGISTRY.pop(job_id, None)
    elif job.get("pid") and _pid_alive(job.get("pid")):
        if not _terminate_pid_tree(job.get("pid")):
            return {"ok": False, "message": "训练进程仍在运行，但平台无法停止它。请查看任务 PID 并手工结束。"}
    else:
        return {"ok": False, "message": "训练进程已经结束，当前没有可停止的进程"}
    job.update({"status": "stopped", "message": "用户手动停止", "finished_at": now_iso(), "updated_at": now_iso()})
    write_json(job_file, job)
    sync_jobs_index(project_id)
    return {"ok": True}


def sync_remote_job(project_id: str, job_id: str) -> Dict[str, Any]:
    p = project_dir(project_id)
    job_file = p / "jobs" / job_id / "job.json"
    job = read_json(job_file, {})
    remote = job.get("remote") or {}
    if not remote.get("base_url") or not remote.get("job_id"):
        return job
    base_url = remote["base_url"].rstrip("/")
    headers = {"X-API-Key": remote.get("api_key", "")}
    log_file = p / "jobs" / job_id / "train.log"
    try:
        r = requests.get(f"{base_url}/api/remote/jobs/{remote['job_id']}", headers=headers, timeout=10)
        r.raise_for_status()
        remote_job = r.json()
        job.update({
            "status": remote_job.get("status", job.get("status")),
            "message": remote_job.get("message", job.get("message")),
            "updated_at": now_iso(),
            "remote_status": remote_job,
        })
        lr = requests.get(f"{base_url}/api/remote/jobs/{remote['job_id']}/log", headers=headers, timeout=15)
        if lr.ok:
            log_file.write_text(lr.text, encoding="utf-8", errors="ignore")
        if job["status"] == "done" and not job.get("remote_models_pulled"):
            pulled = []
            for model_name in remote_job.get("models", []):
                try:
                    mr = requests.get(f"{base_url}/api/remote/jobs/{remote['job_id']}/models/{Path(model_name).name}", headers=headers, timeout=120)
                    if mr.ok and mr.content:
                        dst = p / "models" / f"{job['run_name']}_remote_{Path(model_name).name}"
                        dst.write_bytes(mr.content)
                        pulled.append(str(dst))
                except Exception:
                    pass
            job["models"] = pulled
            job["remote_models_pulled"] = True
            if pulled:
                job["message"] = "远程训练完成，模型已拉回本机"
        write_json(job_file, job)
    except Exception as e:
        log_file.write_text((log_file.read_text(encoding="utf-8", errors="ignore") if log_file.exists() else "") + f"\n[{now_iso()}] 同步远程任务失败：{e}\n", encoding="utf-8")
    return job


def sync_jobs_index(project_id: str):
    p = project_dir(project_id)
    jobs_dir = p / "jobs"
    jobs = []
    for child in jobs_dir.iterdir() if jobs_dir.exists() else []:
        jf = child / "job.json"
        if jf.exists():
            job = read_json(jf, {})
            job = enrich_job_runtime(project_id, job)
            # 让列表状态和倒计时及时落盘，页面刷新/轮询都能看到最新状态。
            try:
                write_json(jf, job)
            except Exception:
                pass
            jobs.append(job)
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    write_json(jobs_dir / "index.json", jobs[:50])


def list_models_internal(project_id: str) -> List[Dict[str, Any]]:
    p = project_dir(project_id)
    models_dir = p / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    # 建立模型文件 -> 训练任务映射，便于发布为算法版本时自动绑定训练报告。
    model_to_job: Dict[str, Dict[str, Any]] = {}
    jobs_dir = p / "jobs"
    for jf in jobs_dir.glob("*/job.json") if jobs_dir.exists() else []:
        job = read_json(jf, {})
        for m in job.get("models", []) or []:
            try:
                model_to_job[str(Path(m).resolve()).lower()] = job
                model_to_job[Path(m).name.lower()] = job
            except Exception:
                pass
    rows = []
    for f in sorted([x for x in models_dir.iterdir() if x.is_file() and x.suffix.lower() in MODEL_EXTS], key=lambda x: x.stat().st_mtime, reverse=True):
        job = model_to_job.get(str(f.resolve()).lower()) or model_to_job.get(f.name.lower()) or {}
        typ = f.suffix.lower().lstrip('.')
        cfg_path = ""
        if typ in {"pdparams", "pdmodel", "pdiparams"}:
            # 优先使用训练任务记录的算法配置；否则尝试找同名前缀的 yml/yaml。
            cfg_path = job.get("generated_config_path") or job.get("algorithm_config_path", "")
            for cand in [f.with_suffix(".yml"), f.with_suffix(".yaml")]:
                if not cfg_path and cand.exists():
                    cfg_path = str(cand)
        rows.append({
            "name": f.name,
            "path": str(f),
            "url": f"/data/projects/{project_id}/models/{f.name}",
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "type": typ,
            "updated_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "job_id": job.get("id", ""),
            "job_name": job.get("algorithm_name", ""),
            "framework": job.get("framework", ""),
            "config_path": cfg_path,
            "family_key": job.get("algorithm_family", "") or job.get("family_key", ""),
            "num_classes": job.get("num_classes", 0),
            "report_ready": bool(job),
        })
    return rows


@app.get("/api/projects/{project_id}/models")
def list_models(project_id: str):
    get_project(project_id)
    return list_models_internal(project_id)


@app.get("/api/projects/{project_id}/models/{model_name}/download")
def download_model(project_id: str, model_name: str):
    get_project(project_id)
    path = project_dir(project_id) / "models" / safe_filename(model_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="模型不存在")
    return FileResponse(path, filename=path.name)


@app.post("/api/projects/{project_id}/predict")
async def predict_image(
    project_id: str,
    model_name: str = Form(...),
    conf: float = Form(0.25),
    file: UploadFile = File(...),
):
    project = get_project(project_id)
    p = project_dir(project_id)
    model_path = p / "models" / safe_filename(model_name)
    if not model_path.exists():
        raise HTTPException(status_code=404, detail="模型不存在，请先训练模型")
    ext = Path(file.filename or "test.jpg").suffix.lower()
    if ext not in IMAGE_EXTS:
        ext = ".jpg"
    pred_id = uuid.uuid4().hex[:12]
    in_path = p / "predictions" / f"{pred_id}_input{ext}"
    out_path = p / "predictions" / f"{pred_id}_result.jpg"
    in_path.write_bytes(await file.read())
    try:
        from ultralytics import YOLO
        model = YOLO(str(model_path))
        results = model.predict(source=str(in_path), conf=float(conf), save=False, verbose=False)
        result = results[0]
        detections = []
        names = result.names
        img = Image.open(in_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        for box in result.boxes:
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0])
            score = float(box.conf[0])
            label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id)
            detections.append({
                "class_id": cls_id,
                "label": label,
                "confidence": round(score, 4),
                "x1": round(xyxy[0], 2), "y1": round(xyxy[1], 2), "x2": round(xyxy[2], 2), "y2": round(xyxy[3], 2),
            })
            x1, y1, x2, y2 = xyxy
            draw.rectangle([x1, y1, x2, y2], outline=(255, 30, 30), width=3)
            text = f"{label} {score:.2f}"
            draw.rectangle([x1, max(0, y1 - 24), x1 + min(320, len(text) * 12 + 10), y1], fill=(255, 30, 30))
            draw.text((x1 + 4, max(0, y1 - 21)), text, fill=(255, 255, 255))
        img.save(out_path, quality=92)
        return {"ok": True, "detections": detections, "image_url": f"/data/projects/{project_id}/predictions/{out_path.name}", "labels": project["labels"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预测失败：{e}")


@app.post("/api/projects/{project_id}/export/onnx")
def export_onnx(project_id: str, model_name: str = Form(...)):
    get_project(project_id)
    p = project_dir(project_id)
    model_path = p / "models" / safe_filename(model_name)
    if not model_path.exists():
        raise HTTPException(status_code=404, detail="模型不存在")
    if model_path.suffix.lower() == ".onnx":
        return {"ok": True, "onnx": str(model_path), "download_url": f"/data/projects/{project_id}/models/{model_path.name}"}
    try:
        from ultralytics import YOLO
        model = YOLO(str(model_path))
        exported = model.export(format="onnx")
        exported_path = Path(exported)
        dst = p / "models" / f"{model_path.stem}.onnx"
        if exported_path.exists():
            shutil.copy2(exported_path, dst)
        return {"ok": True, "onnx": str(dst), "download_url": f"/data/projects/{project_id}/models/{dst.name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败：{e}")

# ============================================================
# v12 产品化接口：数据集分组、训练任务删除、算法版本、模型测试耗时
# ============================================================

APP_DISPLAY_NAME = "畅联云算法训练"

class ImagePatchReq(BaseModel):
    split: Optional[str] = None  # train / val / test
    dataset_id: Optional[str] = None

class BatchSplitReq(BaseModel):
    train: float = 0.7
    val: float = 0.2
    test: float = 0.1
    include_unannotated: bool = True

class LabelUpdateReq(BaseModel):
    code: Optional[str] = None
    display_name: Optional[str] = None
    color: Optional[str] = None
    hotkey: Optional[str] = None

class AlgorithmReq(BaseModel):
    name: str
    remark: Optional[str] = ""
    industry: Optional[str] = ""
    algorithm_type: Optional[str] = ""

class AlgorithmVersionReq(BaseModel):
    model_name: str
    model_source: str = "project"  # project / local
    local_path: Optional[str] = ""
    job_id: Optional[str] = ""
    version_name: Optional[str] = ""
    remark: Optional[str] = ""

class VersionPatchReq(BaseModel):
    version_name: Optional[str] = None
    remark: Optional[str] = None


def algorithms_file(project_id: str) -> Path:
    return project_dir(project_id) / "algorithms.json"


def list_algorithms_internal(project_id: str) -> List[Dict[str, Any]]:
    """Fast algorithm asset read. Existing report snapshots are reused."""
    get_project(project_id)
    data = list_algorithm_assets(algorithms_file(project_id))
    changed = False
    for a in data:
        for k,v0 in {"versions":[],"industry":"","algorithm_type":"","created_at":now_iso()}.items():
            if k not in a: a[k]=v0; changed=True
        if "updated_at" not in a: a["updated_at"]=a.get("created_at") or now_iso(); changed=True
        for i,v in enumerate(a.get("versions",[]),start=1):
            if "version_no" not in v: v["version_no"]=i; changed=True
            if "status" not in v: v["status"]="已归属"; changed=True
            if "created_at" not in v: v["created_at"]=now_iso(); changed=True
            if not v.get("report") and (v.get("job_id") or v.get("stored_path")):
                try:
                    sp=Path(v.get("stored_path","")) if v.get("stored_path") else None
                    fresh=job_report(project_id,v.get("job_id",""),sp)
                    if fresh: v["report"]=fresh; v["report_updated_at"]=now_iso(); changed=True
                except Exception: pass
    if changed: write_json(algorithms_file(project_id),data)
    return data

def save_algorithms_internal(project_id: str, data: List[Dict[str, Any]]):
    save_algorithm_assets(algorithms_file(project_id), data)


def used_model_keys(project_id: str) -> set:
    keys = set()
    for a in list_algorithms_internal(project_id):
        for v in a.get("versions", []):
            if v.get("model_key"):
                keys.add(v.get("model_key"))
    return keys


def resolve_any_model_path(project_id: str, model_name: str = "", model_source: str = "project", local_path: str = "") -> Tuple[Path, str, str]:
    p = project_dir(project_id)
    model_source = model_source or "project"
    if model_source == "local":
        path = Path(local_path or model_name or "").expanduser()
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="本机模型文件不存在")
        return path, path.name, f"local::{path}"
    if model_name.startswith("local::"):
        path = Path(model_name.split("local::", 1)[1])
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="本机模型文件不存在")
        return path, path.name, f"local::{path}"
    path = p / "models" / safe_filename(model_name)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="项目模型不存在")
    return path, path.name, f"project::{path.name}"


def job_report(project_id: str, job_id: str = "", model_path: Optional[Path] = None) -> Dict[str, Any]:
    report: Dict[str, Any] = {"来源": "手动归属"}
    if job_id:
        jf = project_dir(project_id) / "jobs" / job_id / "job.json"
        job = read_json(jf, {})
        if job:
            report = {
                "训练任务": job.get("id") or job_id,
                "训练框架": "Ultralytics" if job.get("framework") == "ultralytics" else "飞桨",
                "训练算法": job.get("algorithm_name") or job.get("algorithm") or "-",
                "基础模型": Path(str(job.get("model", ""))).name if job.get("model") else "-",
                "数据集": job.get("dataset_name") or job.get("dataset_id") or "-",
                "训练图片": job.get("dataset_counts", {}).get("train", "-"),
                "试验图片": job.get("dataset_counts", {}).get("val", "-"),
                "评测图片": job.get("dataset_counts", {}).get("test", "-"),
                "标注框": job.get("dataset_counts", {}).get("boxes", "-"),
                "轮次": job.get("epochs"),
                "图片尺寸": job.get("imgsz"),
                "批大小": job.get("batch"),
                "设备": job.get("device"),
                "进阶参数": json.dumps(job.get("advanced_params", {}), ensure_ascii=False) if job.get("advanced_params") else "-",
                "开始时间": job.get("created_at"),
                "结束时间": job.get("finished_at") or job.get("updated_at"),
                "训练状态": job.get("status"),
            }
            try:
                if job.get("created_at") and job.get("finished_at"):
                    t1 = datetime.strptime(job["created_at"], "%Y-%m-%d %H:%M:%S")
                    t2 = datetime.strptime(job["finished_at"], "%Y-%m-%d %H:%M:%S")
                    report["训练耗时"] = str(t2 - t1)
            except Exception:
                pass
            # 尝试读取 Ultralytics results.csv 的最后一行指标
            run_dir = Path(job.get("run_dir", "")) if job.get("run_dir") else None
            results_csv = run_dir / "results.csv" if run_dir else None
            if results_csv and results_csv.exists():
                try:
                    lines = results_csv.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                    if len(lines) >= 2:
                        headers = [h.strip() for h in lines[0].split(',')]
                        values = [v.strip() for v in lines[-1].split(',')]
                        metrics = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
                        # 常见关键指标，字段名不同版本可能带空格
                        for key in list(metrics.keys()):
                            low = key.lower()
                            if "map50" in low or "precision" in low or "recall" in low or "box_loss" in low:
                                report[key] = metrics[key]
                except Exception:
                    pass
    if model_path and model_path.exists():
        report["模型文件"] = model_path.name
        report["模型大小"] = f"{model_path.stat().st_size / 1024 / 1024:.2f} MB"
        report["更新时间"] = datetime.fromtimestamp(model_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return report


def project_label_items(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = project.get("labels", [])
    meta = project.get("label_meta", [])
    items = []
    for i, code in enumerate(labels):
        m = meta[i] if i < len(meta) and isinstance(meta[i], dict) else {}
        display_name = m.get("display_name") or code
        items.append({
            "class_id": i,
            "code": code,
            "display_name": display_name,
            "display_name_zh": display_name,
            "color": m.get("color") or default_label_color(i),
            "type": m.get("type") or "bbox",
            "hotkey": m.get("hotkey") or (str(i+1) if i < 9 else ""),
            "status": m.get("status") or "active",
        })
    return items


def normalize_box_for_project(project_id: str, img: Dict[str, Any], box: Dict[str, Any], create_label: bool = True) -> Optional[Dict[str, Any]]:
    """把前端/导入的框统一清洗成可训练框。
    修复常见问题：class_id 缺失、class_id 字符串、只有 label、标签名与编码不一致、坐标反向/越界。
    """
    project = get_project(project_id)
    labels = project.setdefault("labels", [])
    try:
        # 优先用 label 反查，避免前端 class_id 与后端标签顺序不一致导致跳过。
        raw_label = normalize_label(str(box.get("label") or box.get("code") or ""))
        raw_class = box.get("class_id", None)
        class_id = None
        if raw_label and raw_label in labels:
            class_id = labels.index(raw_label)
        elif raw_label and create_label:
            class_id = ensure_label(project, raw_label)
            project = get_project(project_id)
            labels = project.get("labels", [])
        else:
            try:
                class_id = int(raw_class)
            except Exception:
                class_id = None
        if class_id is None or class_id < 0 or class_id >= len(labels):
            return None
        x1 = float(box.get("x1")); y1 = float(box.get("y1")); x2 = float(box.get("x2")); y2 = float(box.get("y2"))
    except Exception:
        return None
    w = float(img.get("width") or 1); h = float(img.get("height") or 1)
    x1, x2 = sorted([max(0.0, min(x1, w)), max(0.0, min(x2, w))])
    y1, y2 = sorted([max(0.0, min(y1, h)), max(0.0, min(y2, h))])
    if x2 - x1 < 3 or y2 - y1 < 3:
        return None
    return {
        "id": box.get("id") or uuid.uuid4().hex[:10],
        "class_id": int(class_id),
        "label": labels[int(class_id)],
        "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
    }


def dataset_quality_report(project_id: str, dataset_id: Optional[str] = None, include_empty: bool = False) -> Dict[str, Any]:
    project = get_project(project_id)
    images = load_images(project_id)
    if dataset_id:
        images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
    result = {
        "image_count": len(images),
        "annotated_images": 0,
        "box_count": 0,
        "splits": {"unassigned": {"images": 0, "boxes": 0}, "train": {"images": 0, "boxes": 0}, "val": {"images": 0, "boxes": 0}, "test": {"images": 0, "boxes": 0}},
        "label_usage": {label: 0 for label in project.get("labels", [])},
        "invalid_boxes": 0,
        "empty_images": 0,
        "can_train": False,
        "warnings": [],
    }
    for img in images:
        split = (img.get("split") or "unassigned").lower()
        if split not in result["splits"]:
            split = "unassigned"
        ann = read_annotation(project_id, img["id"])
        clean = []
        for b in ann.get("boxes", []):
            nb = normalize_box_for_project(project_id, img, b, create_label=False)
            if nb:
                clean.append(nb)
            else:
                result["invalid_boxes"] += 1
        if clean or include_empty:
            result["splits"][split]["images"] += 1
        if clean:
            result["annotated_images"] += 1
        else:
            result["empty_images"] += 1
        for b in clean:
            result["box_count"] += 1
            result["splits"][split]["boxes"] += 1
            label = project.get("labels", [])[int(b["class_id"])] if int(b["class_id"]) < len(project.get("labels", [])) else str(b["class_id"])
            result["label_usage"][label] = result["label_usage"].get(label, 0) + 1
    if result["image_count"] == 0:
        result["warnings"].append("当前数据集没有图片")
    if result["box_count"] == 0:
        result["warnings"].append("当前数据集没有有效标注框，无法训练出目标检测模型")
    if result["splits"]["train"]["boxes"] == 0:
        result["warnings"].append("训练集没有有效标注框")
    if result["splits"]["val"]["boxes"] == 0:
        result["warnings"].append("试验集没有有效标注框，训练过程中无法进行独立验证")
    if result["splits"]["test"]["boxes"] == 0:
        result["warnings"].append("评测集没有有效标注框，训练完成后无法进行独立最终评测")
    unused = [k for k, v in result["label_usage"].items() if v == 0]
    if unused:
        result["warnings"].append("以下标签没有样本：" + "、".join(unused))
    result["can_train"] = result["splits"]["train"]["boxes"] > 0 and result["box_count"] > 0
    return result


@app.get("/api/v12/app_info")
def v12_app_info():
    return {"ok": True, "name": APP_DISPLAY_NAME, "version": APP_VERSION}


@app.get("/api/v12/projects/{project_id}/labels")
def v12_list_labels(project_id: str):
    project = get_project(project_id)
    return {"ok": True, "items": active_label_options(project_label_items(project))}


@app.put("/api/v12/projects/{project_id}/labels/{class_id}")
def v12_update_label(project_id: str, class_id: int, payload: LabelUpdateReq):
    project = get_project(project_id)
    labels = project.get("labels", [])
    if class_id < 0 or class_id >= len(labels):
        raise HTTPException(status_code=404, detail="标签不存在")
    if payload.code:
        code = normalize_label(payload.code)
        if not code:
            raise HTTPException(status_code=400, detail="标签编码不能为空")
        if code != labels[class_id] and code in labels:
            raise HTTPException(status_code=400, detail="标签编码已存在")
        labels[class_id] = code
        # 同步已有标注中的 label 字段，不改 class_id
        for img in load_images(project_id):
            ann = read_annotation(project_id, img["id"])
            changed = False
            for b in ann.get("boxes", []):
                if int(b.get("class_id", -1)) == class_id:
                    b["label"] = code; changed = True
            if changed:
                write_annotation(project_id, img["id"], ann.get("boxes", []))
    meta = project.setdefault("label_meta", [])
    while len(meta) < len(labels):
        idx = len(meta)
        meta.append({"code": labels[idx], "display_name": labels[idx], "color": default_label_color(idx), "type": "bbox", "hotkey": str(idx+1) if idx < 9 else ""})
    m = meta[class_id]
    m["code"] = labels[class_id]
    if payload.display_name is not None:
        m["display_name"] = payload.display_name or labels[class_id]
    if payload.color:
        m["color"] = payload.color
    if payload.hotkey is not None:
        m["hotkey"] = payload.hotkey
    save_project(project)
    return {"ok": True, "items": project_label_items(project)}


@app.delete("/api/v12/projects/{project_id}/labels/{class_id}")
def v12_delete_label(project_id: str, class_id: int):
    project = get_project(project_id)
    labels = project.get("labels", [])
    if class_id < 0 or class_id >= len(labels):
        raise HTTPException(status_code=404, detail="标签不存在")
    # 已被框使用时不允许删除；若删除的是未使用标签，后续 class_id 必须整体前移，避免类别错位。
    image_anns = []
    for img in load_images(project_id):
        ann = read_annotation(project_id, img["id"])
        boxes = ann.get("boxes", [])
        if any(int(b.get("class_id", -1)) == class_id for b in boxes):
            raise HTTPException(status_code=400, detail="该标签已被标注框使用，不能直接删除")
        image_anns.append((img["id"], boxes))
    labels.pop(class_id)
    meta = project.get("label_meta", [])
    if class_id < len(meta):
        meta.pop(class_id)
    # First persist the new schema, then rewrite boxes whose class index shifted.
    save_project(project)
    for image_id, boxes in image_anns:
        changed = False
        for b in boxes:
            try:
                cid = int(b.get("class_id", -1))
            except Exception:
                cid = -1
            if cid > class_id:
                b["class_id"] = cid - 1
                changed = True
        if changed:
            write_annotation(project_id, image_id, boxes)
    return {"ok": True, "items": project_label_items(get_project(project_id))}


@app.patch("/api/v12/projects/{project_id}/images/{image_id}")
def v12_patch_image(project_id: str, image_id: str, payload: ImagePatchReq):
    get_project(project_id)
    images = load_images(project_id)
    ok = False
    for img in images:
        if img.get("id") == image_id:
            if payload.split is not None:
                split = (payload.split or "unassigned").lower()
                if split not in {"train", "val", "test", "unassigned"}:
                    raise HTTPException(status_code=400, detail="数据用途只能是未处理、训练集、试验集或评测集")
                img["split"] = split
            if payload.dataset_id is not None:
                img["dataset_id"] = payload.dataset_id or "default"
            img["updated_at"] = now_iso()
            ok = True
            break
    if not ok:
        raise HTTPException(status_code=404, detail="图片不存在")
    save_images(project_id, images)
    return {"ok": True}


class BatchImageSplitReq(BaseModel):
    image_ids: List[str] = []
    split: str = "unassigned"
    dataset_id: Optional[str] = None
    filter: Optional[str] = None  # all / marked / unmarked / train / val / test
    scope: str = "selected"  # selected / filtered / dataset


@app.post("/api/v20/projects/{project_id}/images/batch_split")
def v20_batch_image_split(project_id: str, payload: BatchImageSplitReq):
    get_project(project_id)
    split = (payload.split or "unassigned").lower()
    if split not in {"train", "val", "test", "unassigned"}:
        raise HTTPException(status_code=400, detail="数据用途只能是未处理、训练集、试验集或评测集")
    images = load_images(project_id)
    target_ids = set(payload.image_ids or [])
    scope = (payload.scope or "selected").lower()
    dataset_id = payload.dataset_id or None
    filt = (payload.filter or "all").lower()

    def match_filter(img: Dict[str, Any]) -> bool:
        if dataset_id and img.get("dataset_id", "default") != dataset_id:
            return False
        if scope == "dataset":
            return True
        if scope == "filtered":
            box_count = len(read_annotation(project_id, img["id"]).get("boxes", []))
            cur_split = (img.get("split") or "unassigned").lower()
            if filt == "marked":
                return box_count > 0
            if filt == "unmarked":
                return box_count == 0
            if filt in {"train", "val", "test", "unassigned"}:
                return cur_split == filt
            return True
        return img.get("id") in target_ids

    changed = 0
    for img in images:
        if match_filter(img):
            img["split"] = split
            img["updated_at"] = now_iso()
            changed += 1
    if changed == 0:
        raise HTTPException(status_code=400, detail="没有匹配到可移动的素材")
    save_images(project_id, images)
    return {"ok": True, "changed": changed, "split": split}


@app.post("/api/v12/projects/{project_id}/datasets/{dataset_id}/auto_split")
def v12_auto_split(project_id: str, dataset_id: str, payload: BatchSplitReq):
    get_project(project_id)
    images = [x for x in load_images(project_id) if x.get("dataset_id", "default") == dataset_id]
    if not payload.include_unannotated:
        images = [img for img in images if read_annotation(project_id, img["id"]).get("boxes")]
    if not images:
        raise HTTPException(status_code=400, detail="该数据集暂无图片")
    images = sorted(images, key=lambda x: x.get("id", ""))
    total = len(images)
    train_n = max(1, int(total * payload.train))
    val_n = max(0, int(total * payload.val))
    if train_n + val_n > total:
        val_n = max(0, total - train_n)
    ids_train = {x["id"] for x in images[:train_n]}
    ids_val = {x["id"] for x in images[train_n:train_n+val_n]}
    all_images = load_images(project_id)
    counts = {"train": 0, "val": 0, "test": 0}
    for img in all_images:
        if img.get("dataset_id", "default") != dataset_id:
            continue
        if img["id"] in ids_train:
            img["split"] = "train"
        elif img["id"] in ids_val:
            img["split"] = "val"
        else:
            img["split"] = "test"
        counts[img["split"]] += 1
    save_images(project_id, all_images)
    return {"ok": True, "counts": counts}


def dataset_items_by_split(project_id: str, dataset_id: Optional[str], include_empty: bool = False) -> Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]]:
    images = load_images(project_id)
    if dataset_id:
        images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
    result = {"train": [], "val": [], "test": []}
    for img in sorted(images, key=lambda x: x.get("id", "")):
        ann = read_annotation(project_id, img["id"])
        if not ann.get("boxes") and not include_empty:
            continue
        split = (img.get("split") or "train").lower()
        if split not in result:
            split = "train"
        result[split].append((img, ann))
    # 若用户只传了训练集，自动给评测集兜底，避免 YOLO val 为空
    if not result["val"] and result["train"]:
        result["val"] = result["train"][-max(1, min(len(result["train"]), max(1, len(result["train"]) // 5))):]
    if not result["test"]:
        result["test"] = []
    return result


def build_yolo_dataset_v12(project_id: str, dataset_id: Optional[str] = None, include_empty: bool = False) -> Dict[str, Any]:
    project = get_project(project_id)
    p = project_dir(project_id)
    parts = dataset_items_by_split(project_id, dataset_id, include_empty)
    if not any(parts.values()):
        raise HTTPException(status_code=400, detail="没有可训练数据。请先上传并标注图片。")
    # 训练前质检：有图片不等于有训练目标，必须有有效标注框。
    report = dataset_quality_report(project_id, dataset_id, include_empty)
    if not report.get("can_train"):
        raise HTTPException(status_code=400, detail="当前数据集没有有效训练框：" + "；".join(report.get("warnings", [])))
    dataset = p / "dataset"
    if dataset.exists():
        shutil.rmtree(dataset)
    for sub in ["images/train", "images/val", "images/test", "labels/train", "labels/val", "labels/test"]:
        (dataset / sub).mkdir(parents=True, exist_ok=True)
    counts = {"train": 0, "val": 0, "test": 0, "boxes": 0, "train_boxes": 0, "val_boxes": 0, "test_boxes": 0, "invalid_boxes": 0}
    for part, items in parts.items():
        for img, ann in items:
            src = p / "uploads" / img["stored_name"]
            if not src.exists():
                continue
            clean = []
            for b in ann.get("boxes", []):
                nb = normalize_box_for_project(project_id, img, b, create_label=False)
                if nb:
                    clean.append(nb)
                else:
                    counts["invalid_boxes"] += 1
            if not clean and not include_empty:
                continue
            shutil.copy2(src, dataset / "images" / part / img["stored_name"])
            lines = []
            for b in clean:
                lines.append(box_to_yolo_line(b, img["width"], img["height"]))
            (dataset / "labels" / part / f"{Path(img['stored_name']).stem}.txt").write_text("\n".join(lines), encoding="utf-8")
            counts[part] += 1
            counts["boxes"] += len(lines)
            counts[f"{part}_boxes"] += len(lines)
    if counts["train_boxes"] == 0:
        raise HTTPException(status_code=400, detail="训练集没有有效标注框，请先在数据集里保存标注并重新生成训练文件。")
    if counts["val_boxes"] == 0 and counts["train_boxes"] > 0:
        # 兜底：若评测集为空，用训练集副本做 val，保证 Ultralytics 不会出现 no labels found。
        for f in (dataset / "images" / "train").glob("*"):
            shutil.copy2(f, dataset / "images" / "val" / f.name)
        for f in (dataset / "labels" / "train").glob("*.txt"):
            shutil.copy2(f, dataset / "labels" / "val" / f.name)
        counts["val"] = counts["train"]
        counts["val_boxes"] = counts["train_boxes"]
    data_yaml = {
        "path": str(dataset).replace("\\", "/"),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {i: label for i, label in enumerate(get_project(project_id).get("labels", []))},
    }
    yaml_path = dataset / "data.yaml"
    yaml_path.write_text(yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "dataset": str(dataset), "data_yaml": str(yaml_path), "counts": counts, "labels": get_project(project_id).get("labels", []), "quality": report}


@app.post("/api/v12/projects/{project_id}/dataset/build")
def v12_build_dataset(project_id: str, payload: BuildDatasetReq):
    return build_yolo_dataset_v12(project_id, payload.dataset_id, payload.include_empty)


@app.get("/api/v17/projects/{project_id}/datasets/{dataset_id}/quality")
def v17_dataset_quality(project_id: str, dataset_id: str, include_empty: bool = False):
    return {"ok": True, "quality": dataset_quality_report(project_id, dataset_id, include_empty)}


def build_coco_dataset_v12(project_id: str, dataset_id: Optional[str] = None, include_empty: bool = False) -> Dict[str, Any]:
    project = get_project(project_id)
    p = project_dir(project_id)
    parts = dataset_items_by_split(project_id, dataset_id, include_empty)
    if not any(parts.values()):
        raise HTTPException(status_code=400, detail="没有可导出的数据")
    dataset = p / "paddle_dataset"
    if dataset.exists():
        shutil.rmtree(dataset)
    for sub in ["images/train", "images/val", "images/test", "annotations"]:
        (dataset / sub).mkdir(parents=True, exist_ok=True)
    categories = [{"id": i + 1, "name": label, "supercategory": "object"} for i, label in enumerate(project.get("labels", []))]
    counts = {"train": 0, "val": 0, "test": 0, "boxes": 0}
    def write_part(part: str, json_name: str):
        coco_images = []; coco_anns = []; ann_id = 1
        for idx, (img, ann) in enumerate(parts[part], start=1):
            src = p / "uploads" / img["stored_name"]
            if not src.exists(): continue
            shutil.copy2(src, dataset / "images" / part / img["stored_name"])
            coco_images.append(_coco_image_item(img, idx, f"images/{part}/{img['stored_name']}"))
            for b in ann.get("boxes", []):
                item = _coco_ann_item(ann_id, idx, b)
                if item:
                    coco_anns.append(item); ann_id += 1; counts["boxes"] += 1
            counts[part] += 1
        out = dataset / "annotations" / json_name
        out.write_text(json.dumps({"images": coco_images, "annotations": coco_anns, "categories": categories}, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)
    train_json = write_part("train", "instance_train.json")
    val_json = write_part("val", "instance_val.json")
    test_json = write_part("test", "instance_test.json")
    label_list = dataset / "label_list.txt"
    label_list.write_text("\n".join(project.get("labels", [])), encoding="utf-8")
    return {"ok": True, "dataset": str(dataset), "train_json": train_json, "val_json": val_json, "test_json": test_json, "label_list": str(label_list), "counts": counts, "labels": project.get("labels", [])}


@app.get("/api/v12/projects/{project_id}/datasets/{dataset_id}/export/{fmt}")
def v12_export_dataset(project_id: str, dataset_id: str, fmt: str):
    get_project(project_id)
    fmt = fmt.lower()
    if fmt in {"yolo", "ultralytics"}:
        build = build_yolo_dataset_v12(project_id, dataset_id, include_empty=True)
        src = Path(build["dataset"])
        filename = f"{project_id}_{dataset_id}_YOLO数据集.zip"
    elif fmt in {"coco", "paddle"}:
        build = build_coco_dataset_v12(project_id, dataset_id, include_empty=True)
        src = Path(build["dataset"])
        filename = f"{project_id}_{dataset_id}_COCO数据集.zip"
    else:
        raise HTTPException(status_code=400, detail="导出格式只支持 YOLO 或 COCO")
    zip_path = project_dir(project_id) / "exports" / filename
    zip_dir(src, zip_path)
    return FileResponse(zip_path, filename=filename)


@app.get("/api/v12/projects/{project_id}/datasets/{dataset_id}/summary")
def v12_dataset_summary(project_id: str, dataset_id: str):
    get_project(project_id)
    images = [x for x in load_images(project_id) if x.get("dataset_id", "default") == dataset_id]
    counts = {"train": 0, "val": 0, "test": 0, "unmarked": 0, "images": len(images), "boxes": 0, "annotated": 0}
    for img in images:
        split = (img.get("split") or "train").lower()
        if split not in {"train", "val", "test"}: split = "train"
        counts[split] += 1
        ann = read_annotation(project_id, img["id"])
        boxes = len(ann.get("boxes", []))
        counts["boxes"] += boxes
        if boxes: counts["annotated"] += 1
        else: counts["unmarked"] += 1
    return {"ok": True, "summary": counts}



def _v44_labels_in_ann(ann: Dict[str, Any]) -> set:
    return {str(b.get("label") or "").strip() for b in ann.get("boxes", []) if str(b.get("label") or "").strip()}

def build_yolo_dataset_v44(project_id: str, payload: TrainReq) -> Dict[str, Any]:
    """Build one immutable training snapshot from the project's single logical data pool.
    train uses split=train, validation/试验集 uses split=val, final evaluation uses split=test.
    Optional label filters only select samples; source annotations are never modified.
    """
    project = get_project(project_id)
    p = project_dir(project_id)
    train_filter = {normalize_label(x) for x in (payload.train_labels or []) if normalize_label(x)}
    val_filter = {normalize_label(x) for x in (payload.val_labels or []) if normalize_label(x)}
    train_ids = set(payload.train_image_ids or [])
    val_ids = set(payload.val_image_ids or [])
    groups = {"train": [], "val": [], "test": []}
    for img in sorted(load_images(project_id), key=lambda x: x.get("id", "")):
        split = (img.get("split") or "unassigned").lower()
        if split not in groups:
            continue
        if split == "train" and train_ids and img.get("id") not in train_ids:
            continue
        if split == "val" and val_ids and img.get("id") not in val_ids:
            continue
        ann = read_annotation(project_id, img["id"])
        clean=[]
        for b in ann.get("boxes", []):
            nb=normalize_box_for_project(project_id,img,b,create_label=False)
            if nb: clean.append(nb)
        if not clean and not payload.include_empty:
            continue
        labs={str(b.get("label") or "") for b in clean}
        filt=train_filter if split=="train" else val_filter if split=="val" else set()
        if filt and not labs.intersection(filt):
            continue
        groups[split].append((img,{"boxes":clean}))
    if payload.train_max_samples and payload.train_max_samples>0:
        groups["train"]=groups["train"][:int(payload.train_max_samples)]
    # v42.8：试验集快照保留全部所选数据。val_max_samples 只控制“每隔 N 轮门禁检查”时的随机抽样数量；
    # 0 表示每次检查使用全部试验集，避免把抽样数量错误地固化成整个训练任务的试验集大小。
    if not groups["train"]:
        raise HTTPException(status_code=400,detail="训练集没有符合条件的已标注素材")
    if not groups["val"]:
        raise HTTPException(status_code=400,detail="试验集没有符合条件的已标注素材。请先把素材划入试验集。")
    dataset = p / "dataset_snapshots" / f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
    for sub in ["images/train","images/val","images/test","labels/train","labels/val","labels/test"]:
        (dataset/sub).mkdir(parents=True,exist_ok=True)
    counts={"train":0,"val":0,"test":0,"boxes":0,"train_boxes":0,"val_boxes":0,"test_boxes":0}
    selected_ids={"train":[],"val":[],"test":[]}
    for part,items in groups.items():
        for img,ann in items:
            src=p/"uploads"/img["stored_name"]
            if not src.exists(): continue
            shutil.copy2(src,dataset/"images"/part/img["stored_name"])
            lines=[box_to_yolo_line(b,img["width"],img["height"]) for b in ann.get("boxes",[])]
            (dataset/"labels"/part/f"{Path(img['stored_name']).stem}.txt").write_text("\n".join(lines),encoding="utf-8")
            counts[part]+=1;counts["boxes"]+=len(lines);counts[f"{part}_boxes"]+=len(lines);selected_ids[part].append(img["id"])
    data_yaml={"path":str(dataset).replace("\\\\","/"),"train":"images/train","val":"images/val","test":"images/test","names":{i:l for i,l in enumerate(project.get("labels",[]))}}
    yaml_path=dataset/"data.yaml";yaml_path.write_text(yaml.safe_dump(data_yaml,allow_unicode=True,sort_keys=False),encoding="utf-8")
    return {"ok":True,"dataset":str(dataset),"data_yaml":str(yaml_path),"counts":counts,"labels":project.get("labels",[]),"selected_ids":selected_ids,"filters":{"train_labels":sorted(train_filter),"val_labels":sorted(val_filter),"train_image_ids":sorted(train_ids),"val_image_ids":sorted(val_ids)}}



def _v54_iteration_base(project_id: str, algorithm_id: str, framework: str) -> Optional[Dict[str, Any]]:
    """Use the newest usable algorithm version as the next iteration base model."""
    if not algorithm_id:
        return None
    algo = next((a for a in list_algorithms_internal(project_id) if str(a.get("id")) == str(algorithm_id)), None)
    if not algo:
        return None
    selection = choose_iteration_base(algo.get("versions") or [], "", framework)
    if selection["base_selection_reason"] == "mother_model":
        return None
    path = Path(selection["base_model_path"])
    latest = sorted(
        algo.get("versions") or [],
        key=lambda row: str(row.get("finished_at") or row.get("created_at") or row.get("version_name") or ""),
        reverse=True,
    )
    return {
        **selection,
        "algorithm_id": algo.get("id"), "algorithm_name": algo.get("name"),
        "version_id": selection["base_version_id"], "version_name": selection["base_version_name"],
        "path": str(path), "model_name": path.name,
        "is_latest_version": bool(latest and str(latest[0].get("id")) == str(selection["base_version_id"])),
        "latest_version_name": (latest[0] if latest else {}).get("version_name") or "",
    }

@app.post("/api/v12/projects/{project_id}/train/start")
def v12_start_train(project_id: str, payload: TrainReq):
    get_project(project_id)
    validate_train_request(payload)
    p = project_dir(project_id)
    framework = (payload.framework or "ultralytics").strip().lower()
    alg = get_algorithm_config(payload.algorithm or "")
    asset_algorithm = next((x for x in list_algorithms_internal(project_id) if x.get("id") == (payload.algorithm_asset_id or "")), None)
    mother_model = (payload.model or "").strip() or (alg or {}).get("base_model", "")
    base_selection = choose_iteration_base((asset_algorithm or {}).get("versions") or [], mother_model, framework)
    iteration_base = _v54_iteration_base(project_id, payload.algorithm_asset_id or "", framework)
    model_value = base_selection["base_model_path"]
    if framework != "ultralytics":
        # 飞桨真实训练仍走旧执行器，但数据集改用 COCO split 导出
        return start_train(project_id, payload)
    if not model_value:
        raise HTTPException(status_code=400, detail="请选择基础模型权重")
    if model_value.lower().endswith((".pdparams", ".pdmodel", ".pdiparams", ".onnx", ".engine", ".rknn", ".bmodel")) or model_value.startswith("PP-"):
        raise HTTPException(status_code=400, detail="基础模型与训练框架冲突。Ultralytics 只能选择 .pt 权重。")
    model_value = resolve_ultralytics_model_path(model_value)
    base_selection["base_model_path"] = model_value
    # v42.4: one logical data pool; train/val/test are sample roles rather than separate named datasets.
    preflight = dataset_quality_report(project_id, None, payload.include_empty)
    if not preflight.get("can_train"):
        raise HTTPException(status_code=400, detail="数据不可训练：" + "；".join(preflight.get("warnings", [])))
    build = build_yolo_dataset_v44(project_id, payload)
    selected = build.get("selected_ids") or {}
    selected_ids = set(selected.get("train") or []) | set(selected.get("val") or [])
    snapshot_images = []
    for image in load_images(project_id):
        if str(image.get("id")) not in {str(value) for value in selected_ids}:
            continue
        annotation = read_annotation(project_id, str(image.get("id")))
        snapshot_images.append({**image, "boxes": annotation.get("boxes") or []})
    snapshot = build_snapshot(
        snapshot_images,
        selected.get("train") or [],
        selected.get("val") or [],
        active_label_options(project_label_items(get_project(project_id))),
        seed=int(payload.seed or 0),
    )
    snapshot_path = persist_snapshot(p / "snapshots", snapshot)
    job_id = uuid.uuid4().hex[:12]
    run_name = f"train_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[:4]}"
    job_dir = p / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    log_file = job_dir / "train.log"
    dataset_name = ""
    for ds in ensure_default_datasets(project_id):
        if ds.get("id") == payload.dataset_id:
            dataset_name = ds.get("name", "")
            break
    asset_algorithm = asset_algorithm or next((x for x in list_algorithms_internal(project_id) if x.get("id") == (payload.algorithm_asset_id or "")), None)
    job = {
        "id": job_id,
        "status": "queued",
        "target": payload.target,
        "asset_algorithm_id": (asset_algorithm or {}).get("id", ""),
        "asset_algorithm_name": (asset_algorithm or {}).get("name", ""),
        "framework": "ultralytics",
        "algorithm": payload.algorithm or "",
        "algorithm_name": (alg or {}).get("name") or "YOLO 目标检测",
        "model": model_value,
        "base_version_id": base_selection["base_version_id"],
        "base_version_name": base_selection["base_version_name"],
        "base_model_path": base_selection["base_model_path"],
        "base_model_kind": base_selection["base_model_kind"],
        "base_selection_reason": base_selection["base_selection_reason"],
        "training_base": ({"mode":"previous_version", **iteration_base} if iteration_base else {"mode":"mother_model", "model": model_value}),
        "parent_version_id": (iteration_base or {}).get("version_id", ""),
        "parent_version_name": (iteration_base or {}).get("version_name", ""),
        "epochs": max(1, int(payload.epochs)),
        "imgsz": max(128, int(payload.imgsz)),
        "batch": int(payload.batch),
        "device": payload.device,
        "advanced_params": {
            "patience": payload.patience, "workers": payload.workers, "optimizer": payload.optimizer,
            "lr0": payload.lr0, "lrf": payload.lrf, "weight_decay": payload.weight_decay,
            "close_mosaic": payload.close_mosaic, "mosaic": payload.mosaic, "cache": payload.cache,
            "single_cls": payload.single_cls, "pretrained": payload.pretrained, "rect": payload.rect,
            "amp": payload.amp, "cos_lr": payload.cos_lr, "freeze": payload.freeze,
            "momentum": payload.momentum, "warmup_epochs": payload.warmup_epochs, "save_period": payload.save_period,
            "seed": payload.seed, "deterministic": payload.deterministic, "multi_scale": payload.multi_scale,
            "hsv_h": payload.hsv_h, "hsv_s": payload.hsv_s, "hsv_v": payload.hsv_v,
            "degrees": payload.degrees, "translate": payload.translate, "scale": payload.scale, "shear": payload.shear,
            "perspective": payload.perspective, "flipud": payload.flipud, "fliplr": payload.fliplr, "mixup": payload.mixup,
        },
        "requested_train_params": {
            "epochs": max(1, int(payload.epochs)), "imgsz": max(128, int(payload.imgsz)),
            "batch": int(payload.batch), "device": payload.device,
            "patience": payload.patience, "workers": payload.workers, "optimizer": payload.optimizer,
            "lr0": payload.lr0, "lrf": payload.lrf, "weight_decay": payload.weight_decay,
            "close_mosaic": payload.close_mosaic, "mosaic": payload.mosaic, "cache": payload.cache,
            "single_cls": payload.single_cls, "pretrained": payload.pretrained, "rect": payload.rect,
            "amp": payload.amp, "cos_lr": payload.cos_lr, "freeze": payload.freeze,
            "momentum": payload.momentum, "warmup_epochs": payload.warmup_epochs, "save_period": payload.save_period,
            "seed": payload.seed, "deterministic": payload.deterministic, "multi_scale": payload.multi_scale,
            "hsv_h": payload.hsv_h, "hsv_s": payload.hsv_s, "hsv_v": payload.hsv_v,
            "degrees": payload.degrees, "translate": payload.translate, "scale": payload.scale,
            "shear": payload.shear, "perspective": payload.perspective,
            "flipud": payload.flipud, "fliplr": payload.fliplr, "mixup": payload.mixup,
        },
        "dataset_id": "__all__",
        "dataset_name": "全部数据",
        "dataset_counts": build.get("counts", {}),
        "dataset_selected_ids": build.get("selected_ids", {}),
        "data_filters": build.get("filters", {}),
        "dataset_snapshot": build.get("dataset", ""),
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_path": str(snapshot_path),
        "data_yaml": build.get("data_yaml", ""),
        "quality_gate": {"eval_interval": int(payload.eval_interval or 0), "metric": payload.eval_metric or "map50", "continue_threshold": float(payload.continue_threshold or 0), "stop_threshold": float(payload.stop_threshold or 0), "stage_eval_samples": int(payload.val_max_samples or 0)},
        "ai_intervention": {"enabled": False},
        "queue_priority": int(payload.queue_priority or 50),
        "auto_convert_targets": list(payload.auto_convert_targets or []),
        "train_request": payload.dict(),
        "run_name": run_name,
        "run_dir": str(p / "runs" / run_name),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "log_file": str(log_file),
        "message": "等待启动",
    }
    active_env = get_active_ultralytics_env()
    if active_env:
        job["ultralytics_env"] = {"python_path": active_env.get("python_path"), "root": active_env.get("root"), "version": active_env.get("version")}
    # v42.8：训练任务统一进入资源队列。算法列表是唯一训练入口，任务页只负责运行/历史管理。
    if payload.target == "remote":
        server = resolve_server(payload)
        job["execution_resource"] = {"type":"remote","id":server.get("id") or payload.server_id or "remote","name":server.get("name") or "远程训练服务器","base_url":server.get("base_url") or ""}
        job["resource_key"] = f"remote:{server.get('id') or payload.server_id or server.get('base_url') or 'remote'}"
    else:
        env = get_active_ultralytics_env() or {}
        job["execution_resource"] = {"type":"local","id":"local","name":env.get("name") or "本机训练环境","root":env.get("root") or ""}
        job["resource_key"] = "local:default"
    job["queued_at"] = now_iso()
    job["message"] = "已进入训练队列"
    write_json(job_dir / "job.json", job)
    add_job_to_index(project_id, job)
    _v48_dispatch_training_queues(project_id)
    latest = read_json(job_dir / "job.json", job)
    return {"ok": True, "job": latest, "dataset": build}

    # v42.0.1: v12 页面选择“远程训练”时必须真正提交远程服务器，不能静默落到本机执行。
    if payload.target == "remote":
        server = resolve_server(payload)
        dataset_zip = job_dir / "dataset.zip"
        zip_dir(Path(build["dataset"]), dataset_zip)
        try:
            with dataset_zip.open("rb") as fp:
                files = {"dataset_zip": ("dataset.zip", fp, "application/zip")}
                model_fp = None
                model_path = Path(model_value)
                if model_path.is_file():
                    model_fp = model_path.open("rb")
                    files["model_file"] = (model_path.name, model_fp, "application/octet-stream")
                data = {
                    "model": model_path.name if model_fp else model_value,
                    "epochs": str(job["epochs"]), "imgsz": str(job["imgsz"]), "batch": str(job["batch"]),
                    "device": payload.device, "run_name": run_name,
                    "patience": str(payload.patience), "workers": str(payload.workers), "optimizer": payload.optimizer or "auto",
                    "lr0": str(payload.lr0), "lrf": str(payload.lrf), "weight_decay": str(payload.weight_decay),
                    "close_mosaic": str(payload.close_mosaic), "mosaic": str(payload.mosaic), "cache": str(payload.cache),
                    "single_cls": str(payload.single_cls).lower(), "pretrained": str(payload.pretrained).lower(), "rect": str(payload.rect).lower(),
                    "amp": str(payload.amp).lower(), "cos_lr": str(payload.cos_lr).lower(), "freeze": str(payload.freeze),
                }
                headers = {"X-API-Key": server.get("api_key", "")}
                try:
                    r = requests.post(f"{server['base_url'].rstrip('/')}/api/remote/train", data=data, files=files, headers=headers, timeout=120)
                finally:
                    if model_fp:
                        model_fp.close()
                r.raise_for_status()
                remote = r.json()
            job.update({
                "status": "running", "message": "远程训练已启动",
                "remote": {"server_id": server.get("id"), "name": server.get("name"), "base_url": server["base_url"], "api_key": server.get("api_key", ""), "job_id": remote.get("job_id")},
                "updated_at": now_iso(),
            })
            write_json(job_dir / "job.json", job)
            sync_jobs_index(project_id)
            return {"ok": True, "job": job, "dataset": build}
        except Exception as e:
            job.update({"status": "failed", "message": f"远程训练启动失败：{e}", "updated_at": now_iso()})
            write_json(job_dir / "job.json", job)
            sync_jobs_index(project_id)
            raise HTTPException(status_code=500, detail=job["message"])

    ai_cfg_path = ""
    if payload.ai_intervention_enabled:
        cfgs=_v35_items(MODEL_CONFIGS_FILE)
        cfg=next((x for x in cfgs if x.get('id')==(payload.ai_model_config_id or '')),None) or next((x for x in cfgs if x.get('default_for_training_ai')),None)
        if cfg:
            ai_cfg_path=str(job_dir / "ai_intervention_config.json")
            write_json(Path(ai_cfg_path), cfg)
            job["ai_intervention"]["model_name"] = cfg.get("name") or cfg.get("model_name") or "AI模型"
            write_json(job_dir / "job.json", job)
    cmd = [
        ultralytics_runtime_python(), str(BASE_DIR / "train_worker.py"),
        "--project-dir", str(p), "--data", build["data_yaml"], "--model", model_value,
        "--epochs", str(job["epochs"]), "--imgsz", str(job["imgsz"]), "--batch", str(job["batch"]),
        "--device", payload.device, "--job-id", job_id, "--run-name", run_name,
        "--patience", str(payload.patience), "--workers", str(payload.workers), "--optimizer", payload.optimizer or "auto",
        "--lr0", str(payload.lr0), "--lrf", str(payload.lrf), "--weight-decay", str(payload.weight_decay),
        "--close-mosaic", str(payload.close_mosaic), "--mosaic", str(payload.mosaic), "--cache", str(payload.cache),
        "--single-cls", str(payload.single_cls).lower(), "--pretrained", str(payload.pretrained).lower(), "--rect", str(payload.rect).lower(),
        "--amp", str(payload.amp).lower(), "--cos-lr", str(payload.cos_lr).lower(), "--freeze", str(payload.freeze),
        "--momentum", str(payload.momentum), "--warmup-epochs", str(payload.warmup_epochs), "--save-period", str(payload.save_period),
        "--seed", str(payload.seed), "--deterministic", str(payload.deterministic).lower(), "--multi-scale", str(payload.multi_scale),
        "--hsv-h", str(payload.hsv_h), "--hsv-s", str(payload.hsv_s), "--hsv-v", str(payload.hsv_v),
        "--degrees", str(payload.degrees), "--translate", str(payload.translate), "--scale", str(payload.scale), "--shear", str(payload.shear),
        "--perspective", str(payload.perspective), "--flipud", str(payload.flipud), "--fliplr", str(payload.fliplr), "--mixup", str(payload.mixup),
        "--val-max-samples", str(int(payload.val_max_samples or 0)),
        "--eval-interval", str(int(payload.eval_interval or 0)), "--eval-metric", str(payload.eval_metric or "map50"),
        "--continue-threshold", str(float(payload.continue_threshold or 0)), "--stop-threshold", str(float(payload.stop_threshold or 0)),
        "--auto-supplement", str(bool(payload.auto_supplement)).lower(), "--supplement-count", str(int(payload.supplement_count or 0)),
        "--ai-intervention", str(bool(payload.ai_intervention_enabled)).lower(),
        "--ai-intervention-epochs", ",".join(str(int(x)) for x in sorted({int(x) for x in (payload.ai_intervention_epochs or []) if int(x)>0})),
        "--ai-config", ai_cfg_path, "--ai-eval-samples", str(int(payload.ai_eval_samples or 20)),
        "--ai-action-mode", str(payload.ai_action_mode or "auto"), "--ai-extra-epochs", str(int(payload.ai_extra_epochs or 20)),
        "--ai-max-rounds", str(int(payload.ai_max_rounds or 1)),
    ]
    job["runtime_check"] = check_ultralytics_train_runtime(ultralytics_runtime_python())
    write_json(job_dir / "job.json", job)
    with log_file.open("ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(BASE_DIR), env={**os.environ.copy(), "PYTHONUTF8":"1", "PYTHONIOENCODING":"utf-8"})
    PROCESS_REGISTRY[job_id] = proc
    job.update({"status": "running", "message": "训练已启动", "pid": proc.pid, "started_at": now_iso(), "updated_at": now_iso()})
    write_json(job_dir / "job.json", job)
    sync_jobs_index(project_id)
    return {"ok": True, "job": job, "dataset": build}



# ============================== v42.8 training queue ==============================
V48_TRAIN_QUEUE_LOCK = threading.RLock()


def _v48_resource_key(job: Dict[str, Any]) -> str:
    return str(job.get("resource_key") or ("remote:" + str((job.get("remote") or {}).get("server_id") or "remote") if job.get("target") == "remote" else "local:default"))


def _v48_all_job_files(project_id: str) -> List[Path]:
    root = project_dir(project_id) / "jobs"
    return [x / "job.json" for x in root.iterdir() if x.is_dir() and (x / "job.json").exists()] if root.exists() else []


def _v48_launch_saved_job(project_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(job.get("id") or "")
    jf = project_dir(project_id) / "jobs" / job_id / "job.json"
    if not job_id or not jf.exists():
        raise RuntimeError("训练任务文件不存在")
    payload = TrainReq(**(job.get("train_request") or {}))
    payload.ai_intervention_enabled = False
    payload.ai_intervention_epochs = []
    p = project_dir(project_id)
    job_dir = jf.parent
    log_file = job_dir / "train.log"
    model_value = str(job.get("model") or payload.model or "")
    run_name = str(job.get("run_name") or f"train_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[:4]}")
    data_yaml = str(job.get("data_yaml") or "")
    if not data_yaml or not Path(data_yaml).exists():
        raise RuntimeError("训练快照不存在，无法启动任务")

    if payload.target == "remote":
        server = resolve_server(payload)
        dataset_zip = job_dir / "dataset.zip"
        if not dataset_zip.exists():
            zip_dir(Path(job.get("dataset_snapshot") or Path(data_yaml).parent), dataset_zip)
        with dataset_zip.open("rb") as fp:
            files = {"dataset_zip": ("dataset.zip", fp, "application/zip")}
            model_fp = None
            model_path = Path(model_value)
            if model_path.is_file():
                model_fp = model_path.open("rb")
                files["model_file"] = (model_path.name, model_fp, "application/octet-stream")
            data = {
                "model": model_path.name if model_fp else model_value,
                "epochs": str(job.get("epochs") or payload.epochs), "imgsz": str(job.get("imgsz") or payload.imgsz), "batch": str(job.get("batch") or payload.batch),
                "device": payload.device, "run_name": run_name,
                "patience": str(payload.patience), "workers": str(payload.workers), "optimizer": payload.optimizer or "auto",
                "lr0": str(payload.lr0), "lrf": str(payload.lrf), "weight_decay": str(payload.weight_decay),
                "close_mosaic": str(payload.close_mosaic), "mosaic": str(payload.mosaic), "cache": str(payload.cache),
                "single_cls": str(payload.single_cls).lower(), "pretrained": str(payload.pretrained).lower(), "rect": str(payload.rect).lower(),
                "amp": str(payload.amp).lower(), "cos_lr": str(payload.cos_lr).lower(), "freeze": str(payload.freeze),
                "eval_interval": str(int(payload.eval_interval or 0)), "eval_metric": str(payload.eval_metric or "map50"),
                "continue_threshold": str(float(payload.continue_threshold or 0)), "stop_threshold": str(float(payload.stop_threshold or 0)),
                "val_max_samples": str(int(payload.val_max_samples or 0)),
            }
            headers = {"X-API-Key": server.get("api_key", "")}
            try:
                r = requests.post(f"{server['base_url'].rstrip('/')}/api/remote/train", data=data, files=files, headers=headers, timeout=120)
            finally:
                if model_fp: model_fp.close()
            r.raise_for_status()
            remote = r.json()
        job.update({
            "status":"running", "message":"远程训练已启动", "started_at":now_iso(),
            "remote":{"server_id":server.get("id"),"name":server.get("name"),"base_url":server["base_url"],"api_key":server.get("api_key", ""),"job_id":remote.get("job_id")},
            "updated_at":now_iso(),
        })
        write_json(jf, job)
        return job

    # local Ultralytics worker
    runtime = check_ultralytics_train_runtime(ultralytics_runtime_python())
    cmd = [
        ultralytics_runtime_python(), str(BASE_DIR / "train_worker.py"),
        "--project-dir", str(p), "--data", data_yaml, "--model", model_value,
        "--epochs", str(job.get("epochs") or payload.epochs), "--imgsz", str(job.get("imgsz") or payload.imgsz), "--batch", str(job.get("batch") or payload.batch),
        "--device", payload.device, "--job-id", job_id, "--run-name", run_name,
        "--patience", str(payload.patience), "--workers", str(payload.workers), "--optimizer", payload.optimizer or "auto",
        "--lr0", str(payload.lr0), "--lrf", str(payload.lrf), "--weight-decay", str(payload.weight_decay),
        "--close-mosaic", str(payload.close_mosaic), "--mosaic", str(payload.mosaic), "--cache", str(payload.cache),
        "--single-cls", str(payload.single_cls).lower(), "--pretrained", str(payload.pretrained).lower(), "--rect", str(payload.rect).lower(),
        "--amp", str(payload.amp).lower(), "--cos-lr", str(payload.cos_lr).lower(), "--freeze", str(payload.freeze),
        "--momentum", str(payload.momentum), "--warmup-epochs", str(payload.warmup_epochs), "--save-period", str(payload.save_period),
        "--seed", str(payload.seed), "--deterministic", str(payload.deterministic).lower(), "--multi-scale", str(payload.multi_scale),
        "--hsv-h", str(payload.hsv_h), "--hsv-s", str(payload.hsv_s), "--hsv-v", str(payload.hsv_v),
        "--degrees", str(payload.degrees), "--translate", str(payload.translate), "--scale", str(payload.scale), "--shear", str(payload.shear),
        "--perspective", str(payload.perspective), "--flipud", str(payload.flipud), "--fliplr", str(payload.fliplr), "--mixup", str(payload.mixup),
        "--val-max-samples", str(int(payload.val_max_samples or 0)),
        "--eval-interval", str(int(payload.eval_interval or 0)), "--eval-metric", str(payload.eval_metric or "map50"),
        "--continue-threshold", str(float(payload.continue_threshold or 0)), "--stop-threshold", str(float(payload.stop_threshold or 0)),
        "--auto-supplement", "false", "--supplement-count", "0", "--ai-intervention", "false",
    ]
    job["runtime_check"] = runtime
    with log_file.open("ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(BASE_DIR), env={**os.environ.copy(), "PYTHONUTF8":"1", "PYTHONIOENCODING":"utf-8"})
    PROCESS_REGISTRY[job_id] = proc
    job.update({"status":"running","message":"训练已启动","pid":proc.pid,"started_at":now_iso(),"updated_at":now_iso()})
    write_json(jf, job)
    return job


def _v48_dispatch_training_queues(project_id: str) -> None:
    """One running/paused training per selected resource. Higher queue_priority runs first."""
    with V48_TRAIN_QUEUE_LOCK:
        rows=[]
        for jf in _v48_all_job_files(project_id):
            j=read_json(jf,{})
            if j: rows.append((jf,j))
        busy={_v48_resource_key(j) for _,j in rows if j.get("status") in {"running","paused"}}
        queued=sorted([(jf,j) for jf,j in rows if j.get("status")=="queued"], key=lambda z:(-int(z[1].get("queue_priority") or 0), str(z[1].get("queued_at") or z[1].get("created_at") or "")))
        for jf,j in queued:
            key=_v48_resource_key(j)
            if key in busy: continue
            try:
                _v48_launch_saved_job(project_id,j); busy.add(key)
            except Exception as e:
                j.update(status="failed",message=f"训练启动失败：{e}",finished_at=now_iso(),updated_at=now_iso(),never_started=True)
                write_json(jf,j)


@app.post("/api/v48/projects/{project_id}/jobs/{job_id}/promote")
def v48_promote_job(project_id: str, job_id: str):
    jf=project_dir(project_id)/"jobs"/job_id/"job.json"; job=read_json(jf,{})
    if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
    if job.get("status")!="queued": raise HTTPException(status_code=400,detail="只有排队中的任务可以插队")
    peers=[read_json(x,{}) for x in _v48_all_job_files(project_id)]
    mx=max([int(x.get("queue_priority") or 0) for x in peers if _v48_resource_key(x)==_v48_resource_key(job)] or [50])
    job["queue_priority"]=mx+1; job["promoted_at"]=now_iso(); job["message"]="已插队到当前资源队列最前"; write_json(jf,job)
    _v48_dispatch_training_queues(project_id); sync_jobs_index(project_id)
    return read_json(jf,job)


def _v48_suspend_tree(pid: Any, resume: bool=False):
    import psutil
    proc=psutil.Process(int(pid)); children=proc.children(recursive=True)
    for x in children + [proc]:
        try: x.resume() if resume else x.suspend()
        except Exception: pass


@app.post("/api/v48/projects/{project_id}/jobs/{job_id}/pause")
def v48_pause_job(project_id: str, job_id: str):
    jf=project_dir(project_id)/"jobs"/job_id/"job.json"; job=read_json(jf,{})
    if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
    if job.get("status")!="running": raise HTTPException(status_code=400,detail="只有训练中的任务可以暂停")
    if job.get("target")=="remote":
        remote=job.get("remote") or {}; base=str(remote.get("base_url") or "").rstrip("/")
        if not base: raise HTTPException(status_code=400,detail="远程任务缺少服务地址")
        r=requests.post(f"{base}/api/remote/jobs/{remote.get('job_id')}/pause",headers={"X-API-Key":remote.get("api_key","")},timeout=10)
        if not r.ok: raise HTTPException(status_code=400,detail="远程服务器暂不支持暂停："+r.text[:300])
    else:
        if not job.get("pid") or not _pid_alive(job.get("pid")): raise HTTPException(status_code=400,detail="训练进程不存在")
        _v48_suspend_tree(job.get("pid"),False)
    job.update(status="paused",message="训练已暂停",paused_at=now_iso(),updated_at=now_iso()); write_json(jf,job); sync_jobs_index(project_id)
    return job


@app.post("/api/v48/projects/{project_id}/jobs/{job_id}/resume")
def v48_resume_job(project_id: str, job_id: str):
    jf=project_dir(project_id)/"jobs"/job_id/"job.json"; job=read_json(jf,{})
    if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
    if job.get("status")!="paused": raise HTTPException(status_code=400,detail="只有已暂停任务可以继续")
    if job.get("target")=="remote":
        remote=job.get("remote") or {}; base=str(remote.get("base_url") or "").rstrip("/")
        r=requests.post(f"{base}/api/remote/jobs/{remote.get('job_id')}/resume",headers={"X-API-Key":remote.get("api_key","")},timeout=10)
        if not r.ok: raise HTTPException(status_code=400,detail="远程服务器继续失败："+r.text[:300])
    else:
        if not job.get("pid") or not _pid_alive(job.get("pid")): raise HTTPException(status_code=400,detail="训练进程不存在")
        _v48_suspend_tree(job.get("pid"),True)
    if job.get("paused_at"):
        pdt = _parse_dt_value(job.get("paused_at"))
        if pdt:
            job["paused_seconds"] = int(job.get("paused_seconds") or 0) + max(0, int((datetime.now() - pdt).total_seconds()))
    job.update(status="running",message="训练已继续",resumed_at=now_iso(),paused_at="",updated_at=now_iso()); write_json(jf,job); sync_jobs_index(project_id)
    return job


@app.post("/api/v48/projects/{project_id}/jobs/{job_id}/stop")
def v48_stop_job(project_id: str, job_id: str):
    jf=project_dir(project_id)/"jobs"/job_id/"job.json"; job=read_json(jf,{})
    if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
    was_queued = job.get("status") == "queued"
    if was_queued:
        job.update(status="stopped",message="用户取消排队",finished_at=now_iso(),updated_at=now_iso(),never_started=True); write_json(jf,job)
    elif job.get("status") in {"running","paused"}:
        if job.get("target")=="remote":
            remote=job.get("remote") or {}
            try: requests.post(f"{str(remote.get('base_url') or '').rstrip('/')}/api/remote/jobs/{remote.get('job_id')}/stop",headers={"X-API-Key":remote.get("api_key","")},timeout=10)
            except Exception: pass
        else:
            _terminate_pid_tree(job.get("pid")); PROCESS_REGISTRY.pop(job_id,None)
        job.update(status="stopped",message="用户手动停止",finished_at=now_iso(),updated_at=now_iso()); write_json(jf,job)
    # 只有真正开始过训练的任务才形成算法版本；纯排队后取消不属于一次算法迭代。
    if not was_queued:
        _v48_archive_training_version(project_id,job)
    _v48_dispatch_training_queues(project_id); sync_jobs_index(project_id)
    return read_json(jf,job)


@app.delete("/api/v12/projects/{project_id}/jobs/{job_id}")
def v12_delete_job(project_id: str, job_id: str):
    get_project(project_id)
    # 先尝试停止
    proc = PROCESS_REGISTRY.get(job_id)
    if proc and proc.poll() is None:
        try: proc.terminate()
        except Exception: pass
        PROCESS_REGISTRY.pop(job_id, None)
    shutil.rmtree(project_dir(project_id) / "jobs" / job_id, ignore_errors=True)
    try: _v48_dispatch_training_queues(project_id)
    except Exception: pass
    sync_jobs_index(project_id)
    return {"ok": True}


@app.get("/api/v12/projects/{project_id}/algorithms")
def v12_list_algorithms(project_id: str):
    algos = list_algorithms_internal(project_id)
    return {"ok": True, "items": algos}


@app.post("/api/v12/projects/{project_id}/algorithms")
def v12_create_algorithm(project_id: str, payload: AlgorithmReq):
    get_project(project_id)
    item = create_algorithm_asset(algorithms_file(project_id), payload.model_dump(), now_iso())
    return {"ok": True, "algorithm": item}


@app.put("/api/v12/projects/{project_id}/algorithms/{algorithm_id}")
def v12_update_algorithm(project_id: str, algorithm_id: str, payload: AlgorithmReq):
    item = update_algorithm_asset(algorithms_file(project_id), algorithm_id, payload.model_dump(), now_iso())
    return {"ok": True, "algorithm": item}


@app.delete("/api/v12/projects/{project_id}/algorithms/{algorithm_id}")
def v12_delete_algorithm(project_id: str, algorithm_id: str):
    delete_algorithm_asset(algorithms_file(project_id), algorithm_id)
    return {"ok": True}


@app.get("/api/v12/projects/{project_id}/publish/pending")
def v12_pending_models(project_id: str):
    used = used_model_keys(project_id)
    rows = []
    for m in list_models_internal(project_id):
        key = f"project::{m['name']}"
        if key not in used and m.get("type") in {"pt", "onnx", "pdparams", "pdmodel", "pdiparams"}:
            rows.append({**m, "model_key": key})
    return {"ok": True, "items": rows}


@app.post("/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions")
def v12_assign_version(project_id: str, algorithm_id: str, payload: AlgorithmVersionReq):
    algos = list_algorithms_internal(project_id)
    algo = next((a for a in algos if a.get("id") == algorithm_id), None)
    if not algo:
        raise HTTPException(status_code=404, detail="算法不存在")
    model_path, model_name, model_key = resolve_any_model_path(project_id, payload.model_name, payload.model_source, payload.local_path or "")
    if model_key in used_model_keys(project_id):
        raise HTTPException(status_code=400, detail="该模型已经归属到算法版本中")
    version_id = uuid.uuid4().hex[:12]
    version_no = len(algo.get("versions", [])) + 1
    # v42.8 起版本号统一按训练完成/归档时间生成：YYYYMMDDHHMMSS。
    # 即便从历史兼容入口手工归属，也不再生成 V1/V2 之类的版本号。
    version_ts_source = now_iso()
    if payload.job_id:
        try:
            _jf = project_dir(project_id) / "jobs" / str(payload.job_id) / "job.json"
            _j = read_json(_jf, {}) if _jf.exists() else {}
            version_ts_source = _j.get("finished_at") or _j.get("updated_at") or version_ts_source
        except Exception:
            pass
    version_name_auto = ''.join(ch for ch in str(version_ts_source) if ch.isdigit())[:14]
    if len(version_name_auto) < 14:
        version_name_auto = datetime.now().strftime("%Y%m%d%H%M%S")
    # 拷贝一份到算法版本目录，确保后续可下载、可追溯
    version_dir = project_dir(project_id) / "algorithm_versions" / algorithm_id / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    version_file = version_dir / model_path.name
    shutil.copy2(model_path, version_file)
    bound_job_id = payload.job_id or ""
    if not bound_job_id:
        for m in list_models_internal(project_id):
            if m.get("name") == model_name or str(Path(m.get("path", ""))).lower() == str(model_path).lower():
                bound_job_id = m.get("job_id", "")
                break
    report = job_report(project_id, bound_job_id, version_file)
    version = {
        "id": version_id,
        "version_no": version_no,
        "version_name": version_name_auto,
        "model_name": model_name,
        "model_key": model_key,
        "stored_path": str(version_file),
        "type": model_path.suffix.lower().lstrip('.'),
        "size_mb": round(version_file.stat().st_size / 1024 / 1024, 2),
        "job_id": bound_job_id,
        "remark": payload.remark or "",
        "report": report,
        "report_updated_at": now_iso(),
        "status": "已归属",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    algo.setdefault("versions", []).insert(0, version)
    algo["updated_at"] = now_iso()
    save_algorithms_internal(project_id, algos)
    return {"ok": True, "version": version}


@app.put("/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}")
def v12_update_version(project_id: str, algorithm_id: str, version_id: str, payload: VersionPatchReq):
    algos = list_algorithms_internal(project_id)
    for a in algos:
        if a.get("id") == algorithm_id:
            for v in a.get("versions", []):
                if v.get("id") == version_id:
                    # v42.8 起版本号由训练结束时间唯一生成，不允许人工改写。
                    if payload.remark is not None: v["remark"] = payload.remark or ""
                    v["updated_at"] = now_iso(); a["updated_at"] = now_iso()
                    save_algorithms_internal(project_id, algos)
                    return v
    raise HTTPException(status_code=404, detail="版本不存在")


@app.delete("/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}")
def v12_delete_version(project_id: str, algorithm_id: str, version_id: str):
    algos = list_algorithms_internal(project_id)
    for a in algos:
        if a.get("id") == algorithm_id:
            target = next((v for v in a.get("versions", []) if v.get("id") == version_id), None)
            if not target:
                raise HTTPException(status_code=404, detail="版本不存在")
            try:
                stored = str(target.get("stored_path") or "").strip()
                if stored:
                    sp = Path(stored).resolve()
                    root = (project_dir(project_id) / "algorithm_versions" / algorithm_id).resolve()
                    # 只允许删除算法版本专属目录，避免空路径 Path("") 误指向当前目录。
                    if sp.exists() and (root == sp.parent or root in sp.parents):
                        version_folder = sp.parent
                        if root in version_folder.parents or version_folder == root:
                            shutil.rmtree(version_folder, ignore_errors=True)
            except Exception:
                pass
            a["versions"] = [v for v in a.get("versions", []) if v.get("id") != version_id]
            a["updated_at"] = now_iso()
            save_algorithms_internal(project_id, algos)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="算法不存在")


@app.get("/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/download")
def v12_download_version(project_id: str, algorithm_id: str, version_id: str):
    algos = list_algorithms_internal(project_id)
    for a in algos:
        if a.get("id") == algorithm_id:
            for v in a.get("versions", []):
                if v.get("id") == version_id:
                    path = Path(v.get("stored_path", ""))
                    if not path.exists():
                        raise HTTPException(status_code=404, detail="模型文件不存在")
                    return FileResponse(path, filename=path.name)
    raise HTTPException(status_code=404, detail="版本不存在")


# ============================== v42.8 automatic algorithm versions ==============================
def _v48_version_name_from_job(job: Dict[str, Any]) -> str:
    raw=str(job.get("finished_at") or job.get("updated_at") or now_iso())
    digits="".join(ch for ch in raw if ch.isdigit())
    return (digits[:14] if len(digits)>=14 else datetime.now().strftime("%Y%m%d%H%M%S"))


def _v48_find_job_model(project_id: str, job: Dict[str, Any]) -> Optional[Path]:
    candidates=[]
    for key in ("verified_models","models"):
        for x in job.get(key) or []:
            candidates.append(Path(str(x)))
    run_dir=Path(str(job.get("run_dir") or project_dir(project_id)/"runs"/str(job.get("run_name") or "")))
    candidates += [run_dir/"weights"/"best.pt", run_dir/"weights"/"last.pt"]
    for m in list_models_internal(project_id):
        if m.get("job_id")==job.get("id"):
            candidates.append(Path(str(m.get("path") or "")))
    seen=set()
    for x in candidates:
        try:
            r=x.resolve()
        except Exception:
            r=x
        if str(r) in seen: continue
        seen.add(str(r))
        if x.is_file() and x.suffix.lower() in {".pt",".onnx",".pdparams",".pdmodel",".pdiparams"}:
            return x
    return None


def _v48_metric_from_job(job: Dict[str, Any], metric: str="map50") -> Optional[float]:
    metric=(metric or "map50").lower()
    report=job.get("training_report") or {}
    metrics=report.get("metrics") or {}
    aliases={
        "map50":["metrics/mAP50(B)","metrics/map50(b)","map50"],
        "precision":["metrics/precision(B)","metrics/precision(b)","precision"],
        "recall":["metrics/recall(B)","metrics/recall(b)","recall"],
    }
    for want in aliases.get(metric,aliases["map50"]):
        for k,v in metrics.items():
            if str(k).lower()==want.lower():
                try:return float(v)
                except Exception:pass
    # stage gate events are persisted even when training is manually stopped later.
    for ev in reversed(job.get("gate_events") or []):
        if str(ev.get("metric") or "").lower()==metric and ev.get("value") is not None:
            try:return float(ev.get("value"))
            except Exception:pass
    # fallback to results.csv for interrupted/stopped tasks.
    run_dir=Path(str(job.get("run_dir") or "")); csvp=run_dir/"results.csv" if run_dir else None
    if csvp and csvp.exists():
        try:
            lines=csvp.read_text(encoding="utf-8",errors="ignore").strip().splitlines()
            if len(lines)>=2:
                hs=[x.strip() for x in lines[0].split(',')]; vs=[x.strip() for x in lines[-1].split(',')]
                for i,k in enumerate(hs):
                    low=k.lower().replace(" ","")
                    hit=(metric=="map50" and "map50" in low and "95" not in low) or (metric=="precision" and "precision" in low) or (metric=="recall" and "recall" in low)
                    if hit and i<len(vs): return float(vs[i])
        except Exception: pass
    return None


def _v48_quality_reached(job: Dict[str, Any]) -> bool:
    gate=job.get("quality_gate") or {}; target=float(gate.get("stop_threshold") or 0)
    if target<=0:return False
    value=_v48_metric_from_job(job,str(gate.get("metric") or "map50"))
    return value is not None and value>=target


def _v48_auto_convert_version(project_id: str, algorithm_id: str, version: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    targets=list(job.get("auto_convert_targets") or [])
    summary={"requested":targets,"jobs":[],"errors":[]}
    if not targets or not version.get("stored_path") or not _v48_quality_reached(job):
        return summary
    resources=_builtin_deploy_resources()+_load_saved_deploy_resources()
    for target in targets:
        resource=next((r for r in resources if r.get("status")=="ready" and target in (r.get("targets") or [])),None)
        if not resource:
            summary["errors"].append({"target":target,"message":"没有已检测通过的对应部署资源"});continue
        params={"input_size":int(job.get("imgsz") or 640),"precision":"fp16"}
        if target=="sophon": params["chip"]="bm1684x"
        elif target=="rockchip": params["chip"]="rk3588"
        elif target=="ascend":
            socs=resource.get("detected_soc_versions") or (resource.get("remote_health") or {}).get("soc_versions") or []
            if not socs:
                summary["errors"].append({"target":target,"message":"Atlas 自动转换需要部署资源检测出 soc_version"});continue
            params["soc_version"]=socs[0]
        try:
            r=v39_create_deploy_job(project_id,DeployJobReq(source_id=f"version::{algorithm_id}::{version.get('id')}",target=target,resource_id=str(resource.get("id")),params=params,dataset_id="default",calibration_split="train",calibration_count=100))
            summary["jobs"].append({"target":target,"job_id":(r.get("job") or {}).get("id"),"resource_name":resource.get("name")})
        except Exception as e:
            summary["errors"].append({"target":target,"message":str(getattr(e,"detail",e))})
    return summary


def _v48_archive_training_version(project_id: str, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not job or job.get("auto_version_id") or job.get("never_started"):
        return None
    if job.get("status") not in {"done","finished","completed","failed","stopped"}:
        return None
    algorithm_id=str(job.get("asset_algorithm_id") or "")
    if not algorithm_id:return None
    algos=list_algorithms_internal(project_id); algo=next((a for a in algos if a.get("id")==algorithm_id),None)
    if not algo:return None
    version_name=_v48_version_name_from_job(job)
    # Idempotence across restarts: same training task can archive only once.
    existing=next((v for v in (algo.get("versions") or []) if v.get("job_id")==job.get("id")),None)
    if existing:
        job["auto_version_id"]=existing.get("id");job["auto_version_name"]=existing.get("version_name");
        try:write_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)
        except Exception:pass
        return existing
    version_id=uuid.uuid4().hex[:12]; model_path=_v48_find_job_model(project_id,job); stored_path=""; model_name=""; size_mb=0.0; model_type=""
    if model_path:
        vd=project_dir(project_id)/"algorithm_versions"/algorithm_id/version_id;vd.mkdir(parents=True,exist_ok=True)
        dst=vd/model_path.name;shutil.copy2(model_path,dst);stored_path=str(dst);model_name=dst.name;size_mb=round(dst.stat().st_size/1024/1024,2);model_type=dst.suffix.lower().lstrip('.')
    rep=job_report(project_id,str(job.get("id") or ""),Path(stored_path) if stored_path else None)
    accuracy=_v48_metric_from_job(job,"map50")
    version={
        "id":version_id,"version_no":len(algo.get("versions") or [])+1,"version_name":version_name,
        "model_name":model_name,"model_key":f"job::{job.get('id')}::{version_name}","stored_path":stored_path,"type":model_type,"size_mb":size_mb,
        "job_id":job.get("id"),"remark":"训练结束自动生成版本","report":rep,"report_updated_at":now_iso(),
        "accuracy":accuracy,"accuracy_metric":"mAP50","quality_reached":_v48_quality_reached(job),"training_status":job.get("status"),
        "status":"可用" if stored_path else "无可用模型产物","created_at":job.get("finished_at") or now_iso(),"updated_at":now_iso(),
    }
    algo.setdefault("versions",[]).insert(0,version);algo["updated_at"]=now_iso();save_algorithms_internal(project_id,algos)
    job["auto_version_id"]=version_id;job["auto_version_name"]=version_name
    try:write_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)
    except Exception:pass
    version["auto_conversion"]=_v48_auto_convert_version(project_id,algorithm_id,version,job)
    save_algorithms_internal(project_id,algos)
    try:
        job["auto_conversion"]=version.get("auto_conversion");write_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)
    except Exception:pass
    return version


# v16：测试环境选择。测试不再强制使用平台自身 Python，支持指定 Ultralytics / 飞桨环境。
def _module_available(python_path: str, module_name: str) -> Dict[str, Any]:
    try:
        cp = subprocess.run(
            [python_path, "-c", f"import {module_name}, json; print(json.dumps({{'ok': True, 'version': getattr({module_name}, '__version__', ''), 'path': getattr({module_name}, '__file__', '')}}, ensure_ascii=False))"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="ignore",
        )
        out = (cp.stdout or cp.stderr or "").strip()
        if cp.returncode != 0:
            return {"ok": False, "error": out or f"无法导入 {module_name}"}
        return json.loads(out.splitlines()[-1]) if out else {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def inference_env_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    # 平台内置环境：只有装了对应包才可用。
    u = _module_available(sys.executable, "ultralytics")
    items.append({
        "id": "platform_ultralytics",
        "name": "平台内置 Ultralytics",
        "framework": "ultralytics",
        "python_path": sys.executable,
        "status": "ready" if u.get("ok") else "missing",
        "version": u.get("version", ""),
        "note": "使用当前平台 .venv。" if u.get("ok") else "当前平台环境未安装 ultralytics，测试时请选择已安装的 Ultralytics 环境。",
    })
    active_u = get_active_ultralytics_env()
    if active_u and active_u.get("python_path"):
        py = str(active_u.get("python_path"))
        ok = Path(py).exists()
        items.insert(0, {
            "id": "active_ultralytics",
            "name": active_u.get("name") or "已检测 Ultralytics 环境",
            "framework": "ultralytics",
            "python_path": py,
            "root": active_u.get("root"),
            "status": "ready" if ok else "missing",
            "version": active_u.get("version", ""),
            "note": f"{active_u.get('root','')}" if ok else "python.exe 不存在，请重新检测环境。",
        })
    p_env = get_active_paddle_env()
    if p_env and p_env.get("python_path"):
        py = str(p_env.get("python_path"))
        ok = Path(py).exists()
        paddledet_dir = p_env.get("paddledet_dir") or ""
        infer_py = Path(paddledet_dir) / "tools" / "infer.py" if paddledet_dir else Path("")
        ppdet = _module_available(py, "ppdet") if ok else {"ok": False, "error": "python.exe 不存在"}
        paddlex = _module_available(py, "paddlex") if ok else {"ok": False, "error": "python.exe 不存在"}
        pdet_ready = ok and (ppdet.get("ok") or infer_py.exists())
        px_ready = ok and paddlex.get("ok")
        if pdet_ready and px_ready:
            status, note = "ready", "PaddleDetection / PaddleX 均可用，可测试飞桨训练模型和内置模型。"
        elif pdet_ready:
            status, note = "ready", "PaddleDetection 可用，可测试平台训练出的 .pdparams；未检测到 paddlex，PaddleX 内置模型可能不可用。"
        elif px_ready:
            status, note = "ready", "PaddleX 可用，可测试 PaddleX 内置模型；未检测到 PaddleDetection 推理入口。"
        else:
            status, note = "missing", f"飞桨推理环境不可用：ppdet={ppdet.get('error','未检测到')}；paddlex={paddlex.get('error','未检测到')}"
        items.append({
            "id": "active_paddle",
            "name": p_env.get("name") or "本机飞桨环境",
            "framework": "paddle",
            "python_path": py,
            "paddledet_dir": paddledet_dir,
            "paddlex_dir": p_env.get("paddlex_dir"),
            "status": status,
            "version": ppdet.get("version", "") or paddlex.get("version", ""),
            "note": note,
        })
    # 训练服务器作为可选项展示，但当前测试接口先不调用远程推理；避免误导，标记为 coming。
    for s in read_json(SERVERS_FILE, []):
        items.append({
            "id": f"server:{s.get('id')}",
            "name": s.get("name") or s.get("base_url") or "训练服务器",
            "framework": "server",
            "status": "coming",
            "base_url": s.get("base_url"),
            "note": "已登记训练服务器；模型测试请先使用本机 Ultralytics / 飞桨环境。",
        })
    return items


@app.get("/api/v16/inference_envs")
def v16_inference_envs():
    return {"ok": True, "items": inference_env_items()}


def resolve_inference_python(framework: str, env_id: str = "") -> str:
    framework = (framework or "ultralytics").lower()
    env_id = env_id or ""
    envs = inference_env_items()
    # 指定环境优先。
    if env_id:
        hit = next((e for e in envs if e.get("id") == env_id), None)
        if not hit:
            raise HTTPException(status_code=400, detail="测试环境不存在，请重新选择。")
        if hit.get("framework") != framework:
            raise HTTPException(status_code=400, detail="测试环境与模型框架不匹配，请重新选择。")
        if hit.get("status") not in {"ready", "warning"}:
            raise HTTPException(status_code=400, detail=hit.get("note") or "测试环境不可用。")
        py = hit.get("python_path")
        if not py or not Path(py).exists():
            raise HTTPException(status_code=400, detail="测试环境 python.exe 不存在。")
        return py
    # 没指定时：优先选已检测 Ultralytics，再选平台内置。
    for e in envs:
        if e.get("framework") == framework and e.get("status") == "ready" and e.get("python_path"):
            return e["python_path"]
    raise HTTPException(status_code=400, detail="没有可用的测试环境。请先在训练资源中检测 Ultralytics 或配置飞桨环境。")


def run_predict_by_env(framework: str, python_path: str, model_value: str, input_path: Path, output_path: Path, conf: float) -> Dict[str, Any]:
    framework = (framework or "ultralytics").lower()
    runner = BASE_DIR / ("predict_paddle_runner.py" if framework == "paddle" else "predict_ultralytics_runner.py")
    if not runner.exists():
        raise HTTPException(status_code=500, detail=f"测试执行器不存在：{runner.name}")
    cmd = [python_path, str(runner), "--model", str(model_value), "--input", str(input_path), "--output", str(output_path), "--conf", str(conf)]
    try:
        env = os.environ.copy()
        penv = get_active_paddle_env() if framework == "paddle" else {}
        if framework == "paddle" and penv.get("paddledet_dir"):
            env["PADDLEDETECTION_DIR"] = penv.get("paddledet_dir", "")
        if framework == "paddle" and penv.get("paddlex_dir"):
            env["PADDLEX_DIR"] = penv.get("paddlex_dir", "")
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="ignore", env=env)
        out = (cp.stdout or "").strip()
        err = (cp.stderr or "").strip()
        if cp.returncode != 0:
            raise HTTPException(status_code=500, detail=(err or out or f"测试进程退出码：{cp.returncode}")[-2000:])
        if not out:
            raise HTTPException(status_code=500, detail="测试执行器没有返回结果。")
        # 输出中可能混有框架日志，取最后一个 JSON 行。
        data = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                data = json.loads(line)
                break
        if not data:
            raise HTTPException(status_code=500, detail=(out + "\n" + err)[-2000:])
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试失败：{e}")


@app.post("/api/v12/projects/{project_id}/predict")
async def v12_predict_image(
    project_id: str,
    model_name: str = Form(""),
    model_source: str = Form("project"),
    local_path: str = Form(""),
    algorithm_id: str = Form(""),
    version_id: str = Form(""),
    conf: float = Form(0.25),
    inference_framework: str = Form("ultralytics"),
    inference_env_id: str = Form(""),
    file: UploadFile = File(...),
):
    project = get_project(project_id)
    p = project_dir(project_id)
    (p / "predictions").mkdir(parents=True, exist_ok=True)
    framework = (inference_framework or "ultralytics").lower()
    source = (model_source or "project").lower()
    model_value = ""

    # 解析模型来源。v27 修复：原始模型 builtin、算法版本、项目模型、本机模型、飞桨模型统一收口，避免 model_path 未定义。
    try:
        if framework == "paddle" or source in {"paddle_builtin", "paddle_model"} or str(model_name).startswith("paddledet::"):
            framework = "paddle"
            if source == "local" and local_path:
                model_value = local_path.replace("local::", "", 1)
            else:
                model_value = model_name or "PP-YOLOE-S_human"
        else:
            framework = "ultralytics"
            if source == "builtin":
                model_value = resolve_ultralytics_model_path(model_name or "yolo11n.pt")
            elif algorithm_id and version_id:
                algos = list_algorithms_internal(project_id)
                version = None
                for a in algos:
                    if a.get("id") == algorithm_id:
                        version = next((x for x in a.get("versions", []) if x.get("id") == version_id), None)
                        break
                if not version:
                    raise HTTPException(status_code=404, detail="算法版本不存在")
                model_path = Path(version.get("stored_path", ""))
                if not model_path.exists():
                    raise HTTPException(status_code=404, detail="算法版本模型文件不存在")
                model_value = str(model_path)
            else:
                model_path, _, _ = resolve_any_model_path(project_id, model_name, source, local_path)
                model_value = str(model_path)
        if not model_value:
            raise HTTPException(status_code=400, detail="测试模型为空，请重新选择模型。")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析测试模型失败：{e}")

    ext = Path(file.filename or "test.jpg").suffix.lower()
    if ext not in IMAGE_EXTS:
        ext = ".jpg"
    pred_id = uuid.uuid4().hex[:12]
    in_path = p / "predictions" / f"{pred_id}_input{ext}"
    out_path = p / "predictions" / f"{pred_id}_result.jpg"
    in_path.write_bytes(await file.read())

    python_path = resolve_inference_python(framework, inference_env_id)
    data = run_predict_by_env(framework, python_path, str(model_value), in_path, out_path, float(conf))
    return {
        "ok": True,
        "detections": data.get("detections", []),
        "image_url": f"/data/projects/{project_id}/predictions/{out_path.name}",
        "labels": project.get("labels", []),
        "elapsed_ms": data.get("elapsed_ms", 0),
        "model": data.get("model") or Path(str(model_value)).name,
        "engine": data.get("engine") or framework,
        "python_path": python_path,
        "note": data.get("note", ""),
    }




def _project_label_names(project: Dict[str, Any]) -> List[str]:
    out = []
    for i, x in enumerate(project.get("labels", []) or []):
        if isinstance(x, dict):
            name = x.get("name") or x.get("display_name") or x.get("code") or str(i)
        else:
            name = str(x)
        name = str(name).strip()
        if name:
            out.append(name)
    return out


def _labels_b64(labels: List[str]) -> str:
    try:
        raw = json.dumps(labels or [], ensure_ascii=False).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    except Exception:
        return ""


@app.get("/api/v12/projects/{project_id}/test_models")
def v12_test_models(project_id: str):
    project = get_project(project_id)
    project_label_names = _project_label_names(project)
    project_labels_token = _labels_b64(project_label_names)
    items = []
    # 检测台常用“原始模型”，用于和训练后的新模型做同图对比。
    items.append({"label": "原始模型：YOLO11n 官方预训练", "model_name": "yolo11n.pt", "model_source": "builtin", "framework": "ultralytics", "path": "yolo11n.pt"})
    items.append({"label": "原始模型：YOLO11s 官方预训练", "model_name": "yolo11s.pt", "model_source": "builtin", "framework": "ultralytics", "path": "yolo11s.pt"})
    for m in list_models_internal(project_id):
        if m.get("type") == "pt":
            items.append({"label": f"项目模型：{m['name']}", "model_name": m["name"], "model_source": "project", "framework": "ultralytics", "path": m.get("path")})
        elif m.get("type") in {"pdparams", "pdmodel", "pdiparams"}:
            cfg = m.get("config_path", "") or ""
            fam = m.get("family_key", "") or ""
            nc = m.get("num_classes", 0) or 0
            labels_token = project_labels_token
            encoded = f"paddledet::{m.get('path','')}::{cfg}::{fam}::{nc}::{labels_token}"
            items.append({"label": f"飞桨模型：{m['name']}", "model_name": encoded, "model_source": "paddle_model", "framework": "paddle", "path": m.get("path"), "config_path": cfg, "labels": project_label_names})
    local = read_json(LOCAL_MODELS_FILE, {})
    for m in (local.get("items", []) if isinstance(local, dict) else []):
        if str(m.get("path", "")).lower().endswith(".pt"):
            items.append({"label": f"本机模型：{m.get('name')}", "model_name": f"local::{m.get('path')}", "model_source": "local", "path": m.get("path")})
    active_env = get_active_ultralytics_env()
    for m in active_env.get("models", []) if isinstance(active_env.get("models", []), list) else []:
        if str(m.get("path", "")).lower().endswith(".pt"):
            items.append({"label": f"Ultralytics环境：{m.get('name')}", "model_name": f"local::{m.get('path')}", "model_source": "local", "path": m.get("path")})
    # 飞桨内置/配置模型：只有检测到 paddlex 时才展示，避免误选后 Internal Server Error。
    p_env = get_active_paddle_env()
    if p_env and p_env.get("python_path") and Path(str(p_env.get("python_path"))).exists():
        try:
            px = _module_available(str(p_env.get("python_path")), "paddlex")
        except Exception:
            px = {"ok": False}
        if px.get("ok"):
            items.append({"label": "飞桨内置：PP-YOLOE-S_human 人员检测", "model_name": "PP-YOLOE-S_human", "model_source": "paddle_builtin", "framework": "paddle", "path": "PP-YOLOE-S_human"})
    # 算法版本
    for a in list_algorithms_internal(project_id):
        for v in a.get("versions", []):
            if str(v.get("stored_path", "")).lower().endswith(".pt"):
                items.append({"label": f"算法版本：{a.get('name')} / {v.get('version_name')}", "algorithm_id": a.get("id"), "version_id": v.get("id"), "model_source": "algorithm_version", "framework": "ultralytics", "path": v.get("stored_path")})
    return {"ok": True, "items": items}


# -----------------------------
# v18 robust annotated dataset import
# -----------------------------

def _v18_safe_extract(zip_path: Path, dest: Path, progress_cb=None):
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path, 'r') as zf:
        members=[m for m in zf.infolist() if m.filename and not m.filename.endswith('/')]
        total=max(1,len(members))
        for idx, member in enumerate(members, 1):
            name = member.filename.replace('\\', '/')
            if name.startswith('/') or '..' in Path(name).parts:
                raise HTTPException(status_code=400, detail=f'压缩包包含不安全路径：{name}')
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest)):
                raise HTTPException(status_code=400, detail=f'压缩包包含越权路径：{name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out, length=1024*1024)
            if progress_cb and (idx==1 or idx==total or idx%20==0):
                progress_cb(idx,total,f'正在解压 {idx}/{total} 个文件')


def _v18_split_from_path(path: Path) -> str:
    parts = [x.lower() for x in path.parts]
    if any(x in parts for x in ['valid', 'val', 'validation']):
        return 'val'
    if 'test' in parts or 'testing' in parts:
        return 'test'
    return 'train'


def _v18_set_image_split(project_id: str, image_id: str, split: str):
    batch = _v50_active_image_batch(project_id)
    if batch:
        img = batch["by_id"].get(str(image_id))
        if img is not None:
            img['split'] = split if split in {'train','val','test'} else 'train'
            img['updated_at'] = now_iso()
            batch['dirty'] = True
        return
    images = load_images(project_id)
    for img in images:
        if img.get('id') == image_id:
            img['split'] = split if split in {'train','val','test'} else 'train'
            img['updated_at'] = now_iso()
            break
    save_images(project_id, images)


def _v18_read_names_from_text_file(path: Path) -> List[str]:
    try:
        lines = [normalize_label(x) for x in path.read_text(encoding='utf-8', errors='ignore').splitlines()]
        return [x for x in lines if x]
    except Exception:
        return []


def _v18_collect_class_names(root: Path, label_files: Optional[List[Path]] = None) -> List[str]:
    # 常见格式：data.yaml / classes.txt / obj.names / _darknet.labels
    for yf in list(root.rglob('data.yaml')) + list(root.rglob('*.yaml')) + list(root.rglob('*.yml')):
        names = read_yaml_names(yf)
        if names:
            return [normalize_label(x) for x in names]
    for fn in ['classes.txt', 'obj.names', '_darknet.labels']:
        for cf in root.rglob(fn):
            names = _v18_read_names_from_text_file(cf)
            if names:
                return names
    # 无类别文件时，从 YOLO txt 最大 class_id 自动生成 class_0..class_n
    max_cls = -1
    for lf in label_files or []:
        try:
            for line in lf.read_text(encoding='utf-8', errors='ignore').splitlines():
                ps = line.strip().split()
                if len(ps) >= 5:
                    max_cls = max(max_cls, int(float(ps[0])))
        except Exception:
            pass
    if max_cls >= 0:
        return [f'class_{i}' for i in range(max_cls + 1)]
    return []


def _v18_image_lookup(root: Path):
    imgs = [x for x in root.rglob('*') if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    by_name: Dict[str, Path] = {}
    by_stem: Dict[str, List[Path]] = {}
    by_rel: Dict[str, Path] = {}
    for x in imgs:
        by_name.setdefault(x.name, x)
        by_stem.setdefault(x.stem, []).append(x)
        try:
            by_rel[str(x.relative_to(root)).replace('\\','/')] = x
        except Exception:
            pass
    return imgs, by_name, by_stem, by_rel


def _v18_import_coco(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any], progress_cb=None) -> bool:
    json_files = []
    for jp in root.rglob('*.json'):
        try:
            data = json.loads(jp.read_text(encoding='utf-8', errors='ignore'))
            if isinstance(data, dict) and isinstance(data.get('images'), list) and isinstance(data.get('annotations'), list) and isinstance(data.get('categories'), list):
                json_files.append((jp, data))
        except Exception:
            continue
    if not json_files:
        return False
    project = get_project(project_id)
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    total_expected=sum(len(coco.get('images',[])) for _,coco in json_files) or 1
    progress_done=0
    for ann_json, coco in json_files:
        split = _v18_split_from_path(ann_json)
        cats = sorted(coco.get('categories', []), key=lambda c: int(c.get('id', 0)))
        cat_to_class = {}
        for c in cats:
            label = normalize_label(c.get('name') or f'class_{c.get("id")}')
            cid = int(c.get('id'))
            cat_to_class[cid] = ensure_label(project, label)
            project = get_project(project_id)
        anns_by_img: Dict[int, List[Dict[str, Any]]] = {}
        for a in coco.get('annotations', []):
            try:
                anns_by_img.setdefault(int(a.get('image_id')), []).append(a)
            except Exception:
                pass
        for im in coco.get('images', []):
            file_name = str(im.get('file_name') or '').replace('\\','/')
            src = by_rel.get(file_name) or by_name.get(Path(file_name).name)
            if not src and Path(file_name).stem in by_stem:
                src = by_stem[Path(file_name).stem][0]
            if not src or not src.exists():
                report['missing_images'] += 1
                continue
            rec = add_image_record(project_id, src, Path(file_name).name or src.name, 'imported_coco', dataset_id)
            if not rec:
                report['skipped_images'] += 1
                continue
            _v18_set_image_split(project_id, rec['id'], split)
            boxes=[]
            for a in anns_by_img.get(int(im.get('id')), []):
                cid = int(a.get('category_id', -1))
                if cid not in cat_to_class:
                    continue
                bbox = a.get('bbox') or []
                if len(bbox) < 4:
                    continue
                x,y,w,h = [float(v) for v in bbox[:4]]
                if w < 2 or h < 2:
                    report['invalid_boxes'] += 1
                    continue
                cls = cat_to_class[cid]
                boxes.append({'id':uuid.uuid4().hex[:10], 'class_id':cls, 'label':get_project(project_id)['labels'][cls], 'x1':round(max(0,x),2), 'y1':round(max(0,y),2), 'x2':round(min(rec['width'],x+w),2), 'y2':round(min(rec['height'],y+h),2)})
            write_annotation(project_id, rec['id'], boxes)
            report.setdefault('imported_image_ids', []).append(rec['id'])
            for _b in boxes:
                _lab = str(_b.get('label') or '').strip()
                if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
            report['imported_images'] += 1
            report['boxes'] += len(boxes)
            if boxes: report['annotated_images'] += 1
            progress_done += 1
            if progress_cb and (progress_done==1 or progress_done==total_expected or progress_done%20==0): progress_cb(progress_done,total_expected,f'正在导入 COCO 图片 {progress_done}/{total_expected}')
    report['detected_format'] = 'COCO'
    return True


def _v18_import_voc(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any], progress_cb=None) -> bool:
    import xml.etree.ElementTree as ET
    xml_files = list(root.rglob('*.xml'))
    if not xml_files:
        return False
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    project = get_project(project_id)
    any_imported = False
    total_expected=max(1,len(xml_files)); progress_done=0
    for xp in xml_files:
        try:
            r = ET.parse(xp).getroot()
        except Exception:
            continue
        filename = (r.findtext('filename') or '').strip()
        src = by_name.get(filename) or by_stem.get(Path(filename).stem if filename else xp.stem, [None])[0]
        if not src:
            report['missing_images'] += 1
            continue
        rec = add_image_record(project_id, src, src.name, 'imported_voc', dataset_id)
        if not rec:
            report['skipped_images'] += 1
            continue
        _v18_set_image_split(project_id, rec['id'], _v18_split_from_path(xp))
        boxes=[]
        for obj in r.findall('object'):
            label = normalize_label(obj.findtext('name') or 'object')
            if not label: continue
            cls = ensure_label(project, label); project = get_project(project_id)
            bb = obj.find('bndbox')
            if bb is None: continue
            try:
                x1=float(bb.findtext('xmin')); y1=float(bb.findtext('ymin')); x2=float(bb.findtext('xmax')); y2=float(bb.findtext('ymax'))
            except Exception:
                report['invalid_boxes'] += 1
                continue
            if x2-x1<2 or y2-y1<2:
                report['invalid_boxes'] += 1
                continue
            boxes.append({'id':uuid.uuid4().hex[:10], 'class_id':cls, 'label':project['labels'][cls], 'x1':round(max(0,x1),2), 'y1':round(max(0,y1),2), 'x2':round(min(rec['width'],x2),2), 'y2':round(min(rec['height'],y2),2)})
        write_annotation(project_id, rec['id'], boxes)
        report.setdefault('imported_image_ids', []).append(rec['id'])
        for _b in boxes:
            _lab = str(_b.get('label') or '').strip()
            if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
        report['imported_images'] += 1; report['boxes'] += len(boxes)
        if boxes: report['annotated_images'] += 1
        any_imported = True
        progress_done += 1
        if progress_cb and (progress_done==1 or progress_done==total_expected or progress_done%20==0): progress_cb(progress_done,total_expected,f'正在导入 VOC 图片 {progress_done}/{total_expected}')
    if any_imported:
        report['detected_format'] = 'Pascal VOC'
    return any_imported


def _v18_import_yolo(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any], progress_cb=None) -> bool:
    label_files = [x for x in root.rglob('*.txt') if x.name.lower() not in {'classes.txt','obj.names','_darknet.labels','train.txt','val.txt','test.txt'}]
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    if not image_files:
        return False
    names = _v18_collect_class_names(root, label_files)
    project = get_project(project_id)
    if names:
        for n in names:
            ensure_label(project, n)
        project = get_project(project_id)
    elif not project.get('labels'):
        ensure_label(project, 'object'); project = get_project(project_id)
        names = ['object']
    imported_names = names or project.get('labels', [])
    label_by_stem: Dict[str, List[Path]] = {}
    for lf in label_files:
        label_by_stem.setdefault(lf.stem, []).append(lf)
    any_imported = False
    total_expected=max(1,len(image_files)); progress_done=0
    for img in image_files:
        rec = add_image_record(project_id, img, img.name, 'imported_yolo', dataset_id)
        if not rec:
            report['skipped_images'] += 1
            continue
        split = _v18_split_from_path(img)
        _v18_set_image_split(project_id, rec['id'], split)
        cands = label_by_stem.get(img.stem, [])
        label_file = None
        if cands:
            # 优先选与图片同 split 且路径包含 labels 的 txt
            img_split = _v18_split_from_path(img)
            same_split = [x for x in cands if _v18_split_from_path(x) == img_split]
            label_file = next((x for x in same_split if any(part.lower()=='labels' for part in x.parts)), same_split[0] if same_split else cands[0])
        boxes=[]
        if label_file and label_file.exists():
            for line in label_file.read_text(encoding='utf-8', errors='ignore').splitlines():
                box = yolo_line_to_box(line, rec['width'], rec['height'])
                if not box:
                    report['invalid_boxes'] += 1
                    continue
                old_cls = int(box.get('class_id', -1))
                if old_cls < 0:
                    report['invalid_boxes'] += 1
                    continue
                if old_cls < len(imported_names):
                    label = normalize_label(imported_names[old_cls])
                    new_cls = get_label_id(project, label)
                    project = get_project(project_id)
                elif old_cls < len(project.get('labels', [])):
                    new_cls = old_cls
                else:
                    report['skipped_labels'] += 1
                    continue
                box['class_id'] = new_cls
                box['label'] = get_project(project_id)['labels'][new_cls]
                box['id'] = uuid.uuid4().hex[:10]
                boxes.append(box)
        else:
            report['unmatched_labels'] += 1
        write_annotation(project_id, rec['id'], boxes)
        report.setdefault('imported_image_ids', []).append(rec['id'])
        for _b in boxes:
            _lab = str(_b.get('label') or '').strip()
            if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
        report['imported_images'] += 1; report['boxes'] += len(boxes)
        if boxes: report['annotated_images'] += 1
        any_imported = True
        progress_done += 1
        if progress_cb and (progress_done==1 or progress_done==total_expected or progress_done%20==0): progress_cb(progress_done,total_expected,f'正在导入 YOLO 图片 {progress_done}/{total_expected}')
    if any_imported:
        report['detected_format'] = 'YOLO'
    return any_imported


@app.post('/api/v18/projects/{project_id}/datasets/{dataset_id}/import')
async def v18_import_dataset_auto(project_id: str, dataset_id: str, file: UploadFile = File(...)):
    get_project(project_id)
    p = project_dir(project_id)
    filename = safe_filename(file.filename or 'dataset.zip')
    ext = Path(filename).suffix.lower()
    if ext != '.zip':
        raise HTTPException(status_code=400, detail='请上传 zip 压缩包。支持 YOLO / COCO / Pascal VOC 常见数据集结构。')
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / 'imports' / f'v18_{import_id}'
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / 'imports' / f'v18_{import_id}.zip'
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail='上传文件为空')
    zip_path.write_bytes(raw)
    report = {
        'ok': True,
        'file_name': filename,
        'file_size_mb': round(len(raw)/1024/1024, 2),
        'detected_format': '未知',
        'imported_images': 0,
        'annotated_images': 0,
        'boxes': 0,
        'missing_images': 0,
        'skipped_images': 0,
        'invalid_boxes': 0,
        'skipped_labels': 0,
        'unmatched_labels': 0,
        'labels': [],
        'warnings': [],
        'imported_image_ids': [],
        'label_box_counts': {},
    }
    try:
        _v18_safe_extract(zip_path, temp_dir)
        files_count = sum(1 for x in temp_dir.rglob('*') if x.is_file())
        if files_count == 0:
            raise HTTPException(status_code=400, detail='压缩包里没有文件')
        # 优先 COCO，其次 VOC，最后 YOLO。Roboflow YOLO 会走 YOLO；Roboflow COCO 会走 COCO。
        imported = _v18_import_coco(project_id, temp_dir, dataset_id, report)
        if not imported:
            imported = _v18_import_voc(project_id, temp_dir, dataset_id, report)
        if not imported:
            imported = _v18_import_yolo(project_id, temp_dir, dataset_id, report)
        if not imported or report['imported_images'] == 0:
            raise HTTPException(status_code=400, detail='没有识别到可导入的数据集。请确认压缩包里包含图片，以及 YOLO txt / COCO json / VOC xml 标注文件。')
        if report['boxes'] == 0:
            report['warnings'].append('已导入图片，但没有导入到有效标注框。请检查类别文件、txt/json/xml 标注是否存在，或在页面中重新标注。')
        report['labels'] = get_project(project_id).get('labels', [])
        return report
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)


# -----------------------------
# v19 background import jobs + selectable parsing
# -----------------------------
class V19ImportStartReq(BaseModel):
    selected_paths: Optional[List[str]] = None


def v19_import_jobs_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "import_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def v19_job_dir(project_id: str, job_id: str) -> Path:
    return v19_import_jobs_dir(project_id) / job_id


def v19_job_file(project_id: str, job_id: str) -> Path:
    return v19_job_dir(project_id, job_id) / "job.json"


def v19_normalize_zip_path(name: str) -> str:
    return str(name or "").replace("\\", "/").lstrip("/")


def v19_read_job(project_id: str, job_id: str) -> Dict[str, Any]:
    f = v19_job_file(project_id, job_id)
    if not f.exists():
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return read_json(f, {})


def v19_write_job(project_id: str, job: Dict[str, Any]):
    job["updated_at"] = now_iso()
    f = v19_job_file(project_id, job["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    write_json(f, job)


def v19_update_job(project_id: str, job_id: str, **kwargs):
    try:
        job = v19_read_job(project_id, job_id)
        job.update(kwargs)
        v19_write_job(project_id, job)
    except Exception:
        pass


def v19_scan_zip(zip_path: Path) -> Dict[str, Any]:
    images: List[Dict[str, Any]] = []
    hints = set()
    file_count = 0
    total_size = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = v19_normalize_zip_path(info.filename)
            if not name or name.endswith("/"):
                continue
            file_count += 1
            total_size += max(0, int(getattr(info, "file_size", 0) or 0))
            low = name.lower()
            suffix = Path(low).suffix
            if suffix in IMAGE_EXTS:
                images.append({
                    "path": name,
                    "name": Path(name).name,
                    "split": _v18_split_from_path(Path(name)),
                    "size_kb": round((info.file_size or 0) / 1024, 1),
                })
            if low.endswith("data.yaml") or low.endswith("data.yml") or "/labels/" in low:
                hints.add("YOLO")
            if low.endswith(".json") and ("coco" in low or "annotation" in low or "_annotations" in low):
                hints.add("COCO")
            if low.endswith(".xml"):
                hints.add("VOC")
    return {
        "file_count": file_count,
        "image_count": len(images),
        "images": images,
        "format_hints": sorted(hints) or ["未知"],
        "uncompressed_size_mb": round(total_size / 1024 / 1024, 2),
    }


def v19_copy_selected_tree(extracted: Path, selected_root: Path, selected_paths: List[str]):
    selected = {v19_normalize_zip_path(x) for x in selected_paths if x}
    selected_root.mkdir(parents=True, exist_ok=True)
    # 复制全部标注/配置文件，图片只复制用户选择的，解析时就不会把未选图片导入进来。
    for f in extracted.rglob("*"):
        if not f.is_file():
            continue
        rel = v19_normalize_zip_path(str(f.relative_to(extracted)))
        is_img = f.suffix.lower() in IMAGE_EXTS
        if is_img and rel not in selected:
            continue
        dst = selected_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)


def v19_build_report_base(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "batch_id": job.get("batch_id") or job.get("id"),
        "file_name": job.get("file_name", ""),
        "file_size_mb": job.get("file_size_mb", 0),
        "detected_format": "未知",
        "imported_images": 0,
        "annotated_images": 0,
        "boxes": 0,
        "missing_images": 0,
        "skipped_images": 0,
        "invalid_boxes": 0,
        "skipped_labels": 0,
        "unmatched_labels": 0,
        "labels": [],
        "warnings": [],
        "imported_image_ids": [],
        "label_box_counts": {},
    }


def v19_import_worker(project_id: str, dataset_id: str, job_id: str, selected_paths: List[str]):
    job = v19_read_job(project_id, job_id)
    processing_started = time.time()
    job_dir = v19_job_dir(project_id, job_id)
    zip_path = job_dir / "source.zip"
    extracted = job_dir / "extracted"
    selected_root = job_dir / "selected_root"
    selected_paths = [v19_normalize_zip_path(x) for x in selected_paths if x]
    total_selected = len(selected_paths) or int(job.get("image_count", 0) or 0)
    report = v19_build_report_base(job)
    lock = _v50_project_import_lock(project_id)
    try:
        # 同一项目的压缩包导入串行执行，避免两个大包同时覆盖 images.json。
        with lock:
            _v50_begin_image_batch(project_id)
            try:
                v19_update_job(project_id, job_id, status="running", stage="正在解压数据集", progress=8,
                               total_selected=total_selected, processed=0, message="后台解析已开始",
                               processing_started_at=now_iso())
                if extracted.exists():
                    shutil.rmtree(extracted, ignore_errors=True)
                extracted.mkdir(parents=True, exist_ok=True)
                def extract_progress(done,total,msg):
                    frac=done/max(1,total); prog=8+frac*24
                    elapsed=max(0.01,time.time()-processing_started)
                    eta=max(0.0,elapsed/max(0.01,prog)*max(0.0,100-prog))
                    v19_update_job(project_id, job_id, stage="正在解压数据集", progress=round(prog,1), processed=done, total_files=total, message=msg, processing_seconds=round(elapsed,1), eta_seconds=round(eta,1))
                _v18_safe_extract(zip_path, extracted, extract_progress)
                v19_update_job(project_id, job_id, stage="正在准备解析范围", progress=34, processed=0)
                parse_root = extracted
                if selected_paths:
                    if selected_root.exists():
                        shutil.rmtree(selected_root, ignore_errors=True)
                    v19_copy_selected_tree(extracted, selected_root, selected_paths)
                    parse_root = selected_root
                v19_update_job(project_id, job_id, stage="正在识别标注格式", progress=38, processed=0)
                imported = False
                def import_progress(done,total,msg):
                    frac=done/max(1,total); prog=45+frac*50
                    elapsed=max(0.01,time.time()-processing_started)
                    eta=max(0.0,elapsed/max(0.01,prog)*max(0.0,100-prog))
                    v19_update_job(project_id, job_id, stage=msg, progress=round(prog,1), processed=done, total_selected=total, message=msg, processing_seconds=round(elapsed,1), eta_seconds=round(eta,1))
                v19_update_job(project_id, job_id, stage="正在解析 COCO / VOC / YOLO 标注", progress=44, processed=0)
                imported = _v18_import_coco(project_id, parse_root, dataset_id, report, import_progress)
                if not imported:
                    v19_update_job(project_id, job_id, stage="正在解析 VOC 标注", progress=44, processed=0)
                    imported = _v18_import_voc(project_id, parse_root, dataset_id, report, import_progress)
                if not imported:
                    v19_update_job(project_id, job_id, stage="正在解析 YOLO / 原始图片", progress=44, processed=0)
                    imported = _v18_import_yolo(project_id, parse_root, dataset_id, report, import_progress)
                if not imported or report.get("imported_images", 0) == 0:
                    raise RuntimeError("没有识别到可导入的数据。请确认 ZIP 内包含图片，并检查目录结构是否正确。")
                if report.get("boxes", 0) == 0:
                    report.setdefault("warnings", []).append(
                        "图片已导入，但未识别到有效标注。素材将进入未处理；如本来应带标注，请检查 YOLO txt / COCO json / VOC xml 结构。"
                    )
                if report.get("missing_images", 0):
                    report.setdefault("warnings", []).append(f"有 {report.get('missing_images')} 条标注找不到对应图片。")
                if report.get("unmatched_labels", 0):
                    report.setdefault("warnings", []).append(f"有 {report.get('unmatched_labels')} 张图片未匹配到对应标注文件。")
                if report.get("invalid_boxes", 0):
                    report.setdefault("warnings", []).append(f"忽略了 {report.get('invalid_boxes')} 个无效标注框。")
                if report.get("skipped_images", 0):
                    report.setdefault("warnings", []).append(f"有 {report.get('skipped_images')} 张图片导入失败或被跳过。")
                report["labels"] = get_project(project_id).get("labels", [])
            finally:
                # 批量导入期间只在这里写一次 images.json，避免每张图片都整表读写造成大 ZIP 极慢。
                _v50_end_image_batch(save=True)
        processing_seconds = round(max(0.0, time.time() - processing_started), 2)
        v19_update_job(
            project_id, job_id, status="done", stage="导入完成", progress=100,
            processed=report.get("imported_images", 0), report=report,
            processing_seconds=processing_seconds, finished_at=now_iso(),
            message=f"导入完成：{report.get('imported_images',0)} 图，{report.get('annotated_images',0)} 张带标注，{report.get('boxes',0)} 框",
        )
    except HTTPException as e:
        _v50_end_image_batch(save=True)
        v19_update_job(project_id, job_id, status="failed", stage="导入失败", progress=100,
                       error=str(e.detail), report=report,
                       processing_seconds=round(max(0.0, time.time()-processing_started),2),
                       finished_at=now_iso(), message=str(e.detail))
    except Exception as e:
        _v50_end_image_batch(save=True)
        v19_update_job(project_id, job_id, status="failed", stage="导入失败", progress=100,
                       error=str(e), report=report,
                       processing_seconds=round(max(0.0, time.time()-processing_started),2),
                       finished_at=now_iso(), message=str(e))
    finally:
        shutil.rmtree(extracted, ignore_errors=True)
        shutil.rmtree(selected_root, ignore_errors=True)


@app.post("/api/v19/projects/{project_id}/datasets/{dataset_id}/import/jobs")
async def v19_create_import_job(project_id: str, dataset_id: str, file: UploadFile = File(...)):
    get_project(project_id)
    filename = safe_filename(file.filename or "dataset.zip")
    if Path(filename).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="文件类型不支持：请上传 .zip 压缩包。")
    job_id = uuid.uuid4().hex[:10]
    jd = v19_job_dir(project_id, job_id)
    jd.mkdir(parents=True, exist_ok=True)
    zip_path = jd / "source.zip"
    upload_started = time.time()
    uploaded_bytes = 0
    try:
        # 分块落盘，避免大 ZIP 一次性读入内存。
        with zip_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                uploaded_bytes += len(chunk)
    except Exception as e:
        shutil.rmtree(jd, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"文件接收失败：{e}")
    upload_seconds = round(max(0.0, time.time() - upload_started), 2)
    if uploaded_bytes <= 0:
        shutil.rmtree(jd, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传失败：ZIP 文件为空。")
    scan_started = time.time()
    try:
        scan = v19_scan_zip(zip_path)
    except zipfile.BadZipFile:
        shutil.rmtree(jd, ignore_errors=True)
        raise HTTPException(status_code=400, detail="ZIP 校验失败：压缩包已损坏、格式不正确或不是有效 ZIP。")
    except Exception as e:
        shutil.rmtree(jd, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"ZIP 校验失败：{e}")
    scan_seconds = round(max(0.0, time.time() - scan_started), 2)
    if scan.get("image_count", 0) == 0:
        shutil.rmtree(jd, ignore_errors=True)
        raise HTTPException(status_code=400, detail="ZIP 内容不匹配：压缩包内没有识别到支持的图片文件。")
    job = {
        "id": job_id, "project_id": project_id, "dataset_id": dataset_id,
        "batch_id": job_id,
        "file_name": filename, "file_size_mb": round(uploaded_bytes / 1024 / 1024, 2),
        "uploaded_bytes": uploaded_bytes, "upload_seconds": upload_seconds, "scan_seconds": scan_seconds,
        "status": "selecting", "stage": "上传与校验完成", "progress": 0,
        "message": "上传与ZIP校验完成，等待开始后台导入",
        "created_at": now_iso(), "uploaded_at": now_iso(), "updated_at": now_iso(), **scan,
    }
    v19_write_job(project_id, job)
    return job


@app.post("/api/v19/projects/{project_id}/import/jobs/{job_id}/start")
def v19_start_import_job(project_id: str, job_id: str, payload: V19ImportStartReq):
    job = v19_read_job(project_id, job_id)
    if job.get("status") == "running":
        return job
    if job.get("status") not in {"selecting", "failed"}:
        raise HTTPException(status_code=400, detail="当前导入任务状态不允许重新开始")
    selected_paths = payload.selected_paths or []
    if selected_paths:
        allowed = {x.get("path") for x in job.get("images", [])}
        selected_paths = [x for x in selected_paths if x in allowed]
        if not selected_paths:
            raise HTTPException(status_code=400, detail="没有选择有效图片")
    import threading
    v19_update_job(project_id, job_id, status="running", stage="准备后台解析", progress=3, selected_count=len(selected_paths) or job.get("image_count", 0), message="已缩放到后台解析")
    th = threading.Thread(target=v19_import_worker, args=(project_id, job.get("dataset_id") or "default", job_id, selected_paths), daemon=True)
    th.start()
    return v19_read_job(project_id, job_id)


@app.get("/api/v19/projects/{project_id}/import/jobs")
def v19_list_import_jobs(project_id: str):
    get_project(project_id)
    jobs = []
    d = v19_import_jobs_dir(project_id)
    for jf in d.glob("*/job.json"):
        job = read_json(jf, {})
        if job:
            # 列表里最多返回前 300 个图片候选，避免巨大 JSON 卡页面；详情接口返回完整。
            if isinstance(job.get("images"), list) and len(job["images"]) > 300:
                job = {**job, "images": job["images"][:300], "images_truncated": True}
            jobs.append(job)
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"ok": True, "items": jobs}


@app.get("/api/v19/projects/{project_id}/import/jobs/{job_id}")
def v19_get_import_job(project_id: str, job_id: str):
    return v19_read_job(project_id, job_id)


@app.delete("/api/v19/projects/{project_id}/import/jobs/{job_id}")
def v19_delete_import_job(project_id: str, job_id: str):
    v19_read_job(project_id, job_id)
    shutil.rmtree(v19_job_dir(project_id, job_id), ignore_errors=True)
    return {"ok": True}

# ============================================================
# v30: 模型/算法导出包 + 部署环境选择
# ============================================================
class ModelExportReq(BaseModel):
    model_name: str
    model_source: str = "project"
    local_path: Optional[str] = ""
    algorithm_id: Optional[str] = ""
    version_id: Optional[str] = ""
    deployment_target: str = "platform_package"  # platform_package / paddledet_weight / paddledet_infer / ultralytics_onnx / sophon_prepare
    export_config: Optional[Dict[str, Any]] = None
    include_report: bool = True
    include_dataset_labels: bool = True
    try_convert: bool = False


def _find_model_meta(project_id: str, model_path: Path, model_name: str = "") -> Dict[str, Any]:
    for m in list_models_internal(project_id):
        try:
            if Path(m.get("path", "")).resolve() == model_path.resolve() or m.get("name") == model_name or m.get("name") == model_path.name:
                return m
        except Exception:
            if m.get("name") == model_name or m.get("name") == model_path.name:
                return m
    return {}


def _copy_if_exists(src: Any, dst: Path):
    try:
        p = Path(str(src))
        if src and p.exists() and p.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            return True
    except Exception:
        pass
    return False


def _zip_dir(src_dir: Path, zip_path: Path):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir))


def _export_label_name(x: Any, i: int) -> str:
    if isinstance(x, dict):
        return str(x.get("name") or x.get("display_name") or x.get("code") or f"class_{i}")
    if x is None:
        return f"class_{i}"
    return str(x)


def _export_labels(project: Dict[str, Any], meta: Dict[str, Any], job: Dict[str, Any]) -> List[str]:
    raw = job.get("labels") or meta.get("labels") or project.get("labels") or []
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("labels") or []
    if not isinstance(raw, list):
        raw = []
    names = [_export_label_name(x, i).strip() for i, x in enumerate(raw)]
    names = [x for x in names if x]
    n = int(meta.get("num_classes") or job.get("num_classes") or len(names) or 0)
    while n and len(names) < n:
        names.append(f"class_{len(names)}")
    return names


def _find_job_for_model(project_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    jid = meta.get("job_id") or ""
    if not jid:
        return {}
    jf = project_dir(project_id) / "jobs" / jid / "job.json"
    return read_json(jf, {}) if jf.exists() else {}


def _copy_model_related_files(model_path: Path, model_dir: Path) -> List[str]:
    model_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    if model_path.exists() and model_path.is_file():
        dst = model_dir / model_path.name
        shutil.copy2(model_path, dst)
        copied.append(dst.name)
    if model_path.suffix.lower() in {".pdmodel", ".pdiparams"}:
        stem = Path(str(model_path.with_suffix("")))
        for cand in [model_path.with_suffix(".pdmodel"), model_path.with_suffix(".pdiparams"), Path(str(stem) + ".pdiparams.info"), model_path.with_suffix(".yml"), model_path.with_suffix(".yaml")]:
            if cand.exists() and cand.is_file() and cand.name not in copied:
                shutil.copy2(cand, model_dir / cand.name)
                copied.append(cand.name)
    return copied


def _write_export_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="ignore")


def _write_export_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_export_yaml(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _build_export_config(payload: ModelExportReq, model_path: Path, framework: str, labels: List[str]) -> Dict[str, Any]:
    cfg = dict(payload.export_config or {})
    target = payload.deployment_target or "platform_package"
    def _int(key, default):
        try:
            return int(cfg.get(key, default))
        except Exception:
            return default
    def _float(key, default):
        try:
            return float(cfg.get(key, default))
        except Exception:
            return default
    conf = {
        "deployment_target": target,
        "framework": framework,
        "input_size": _int("input_size", 320 if framework == "paddle" else 640),
        "confidence": _float("confidence", 0.25),
        "device": str(cfg.get("device") or "cpu"),
        "precision": str(cfg.get("precision") or "fp32"),
        "runtime": str(cfg.get("runtime") or target),
        "include_source_model": bool(cfg.get("include_source_model", True)),
        "try_convert": bool(payload.try_convert),
        "label_count": len(labels),
        "labels": labels,
        "model_file": f"model/{model_path.name}",
    }
    if target == "sophon_prepare":
        conf.update({
            "target_chip": str(cfg.get("target_chip") or "bm1684x/bm1688/cv186ah 待确认"),
            "quantization": str(cfg.get("quantization") or "fp32"),
            "note": "本包是算能/边缘盒子转换准备包，不直接等于 bmodel。需在目标设备工具链中继续转换、量化和验证。",
        })
    elif target == "paddledet_infer":
        conf.update({"expected_outputs": ["inference_model/*.pdmodel", "inference_model/*.pdiparams", "inference_model/infer_cfg.yml"]})
    elif target == "ultralytics_onnx":
        conf.update({
            "onnx_dynamic": bool(cfg.get("onnx_dynamic", False)),
            "onnx_simplify": bool(cfg.get("onnx_simplify", False)),
            "onnx_opset": _int("onnx_opset", 12),
            "expected_outputs": ["converted/*.onnx"],
        })
    return conf


def _try_export_paddledet_infer(project_id: str, python_path: str, model_path: Path, meta: Dict[str, Any], out_dir: Path, export_conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    penv = get_active_paddle_env()
    paddledet_dir = Path(str(penv.get("paddledet_dir", "")))
    cfg = Path(str(meta.get("config_path") or meta.get("generated_config_path") or meta.get("algorithm_config_path") or ""))
    result = {"ok": False, "note": "", "outputs": []}
    if not python_path or not Path(python_path).exists():
        result["note"] = "未转换：飞桨 python.exe 不存在。已保留 PaddleDetection 权重部署包。"
        return result
    if not paddledet_dir.exists():
        result["note"] = "未转换：PaddleDetection 目录不存在。已保留 PaddleDetection 权重部署包。"
        return result
    export_py = paddledet_dir / "tools" / "export_model.py"
    if not export_py.exists():
        result["note"] = "未转换：PaddleDetection tools/export_model.py 不存在。已保留 PaddleDetection 权重部署包。"
        return result
    if not cfg.exists() or not cfg.is_file():
        result["note"] = "未转换：没有找到该模型训练时使用的 yml 配置。已保留 PaddleDetection 权重部署包。"
        return result
    infer_out = out_dir / "inference_model"
    infer_out.mkdir(parents=True, exist_ok=True)
    num_classes = int(meta.get("num_classes") or 0)
    fam = (meta.get("family_key") or "").lower()
    class_opts = []
    if num_classes > 0:
        class_opts.append(f"num_classes={num_classes}")
        if "picodet" in fam:
            class_opts.append(f"PicoHead.num_classes={num_classes}")
        elif "ppyoloe" in fam:
            class_opts.append(f"PPYOLOEHead.num_classes={num_classes}")
        elif "ppyolo" in fam or "yolov3" in fam:
            class_opts.append(f"YOLOv3Head.num_classes={num_classes}")
    cmd = [python_path, str(export_py), "-c", str(cfg), "-o", f"weights={str(model_path)}", "use_gpu=False", f"save_dir={str(infer_out)}"] + class_opts
    try:
        cp = subprocess.run(cmd, cwd=str(paddledet_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        _write_export_text(out_dir / "export_model_command.txt", " ".join(cmd) + "\n\nSTDOUT:\n" + (cp.stdout or "") + "\n\nSTDERR:\n" + (cp.stderr or ""))
        outs = [str(x.relative_to(out_dir)) for x in infer_out.rglob("*") if x.is_file()]
        result["outputs"] = outs
        if cp.returncode == 0 and outs:
            result["ok"] = True
            result["note"] = "已生成 Paddle 推理模型。可在 PaddleDetection/Paddle Inference 方向继续部署。"
        elif cp.returncode == 0:
            result["note"] = "export_model.py 已执行成功，但未发现推理模型文件，请查看转换日志。"
        else:
            tail = ((cp.stderr or "") + "\n" + (cp.stdout or ""))[-1200:]
            result["note"] = "推理模型转换失败，已保留原始权重和转换日志。原因摘要：" + tail
        return result
    except Exception as e:
        result["note"] = f"推理模型转换异常，已保留原始权重包：{e}"
        return result


def _try_export_ultralytics_onnx(project_id: str, model_path: Path, out_dir: Path, export_conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"ok": False, "note": "", "outputs": []}
    if model_path.suffix.lower() != ".pt":
        result["note"] = "未转换：只有 Ultralytics .pt 支持导出 ONNX。已生成平台模型包。"
        return result
    conf = export_conf or {}
    py = ultralytics_runtime_python()
    script = out_dir / "export_onnx.py"
    imgsz = int(conf.get("input_size") or 640)
    opset = int(conf.get("onnx_opset") or 12)
    dynamic = "True" if conf.get("onnx_dynamic") else "False"
    simplify = "True" if conf.get("onnx_simplify") else "False"
    _write_export_text(script, f'''
from pathlib import Path
from ultralytics import YOLO
model_path = r"{str(model_path)}"
out_dir = Path(r"{str(out_dir)}")
out_dir.mkdir(parents=True, exist_ok=True)
model = YOLO(model_path)
res = model.export(format="onnx", imgsz={imgsz}, opset={opset}, dynamic={dynamic}, simplify={simplify})
print(res)
''')
    try:
        cp = subprocess.run([py, str(script)], cwd=str(out_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        _write_export_text(out_dir / "export_onnx_command.txt", f'"{py}" "{script}"\n\nSTDOUT:\n{cp.stdout or ""}\n\nSTDERR:\n{cp.stderr or ""}')
        candidates = []
        for root in [out_dir, model_path.parent]:
            if root.exists():
                candidates += [x for x in root.glob("*.onnx") if x.is_file()]
        candidates = sorted(set(candidates), key=lambda x: x.stat().st_mtime, reverse=True)
        for ep in candidates[:3]:
            dst = out_dir / ep.name
            if ep.resolve() != dst.resolve():
                shutil.copy2(ep, dst)
        outs = [str(x.relative_to(out_dir)) for x in out_dir.glob("*.onnx")]
        result["outputs"] = outs
        if cp.returncode == 0 and outs:
            result["ok"] = True
            result["note"] = "已生成 Ultralytics ONNX 推理包。"
        elif cp.returncode == 0:
            result["note"] = "ONNX 导出命令已执行，但没有找到 .onnx 输出文件，请查看转换日志。"
        else:
            tail = ((cp.stderr or "") + "\n" + (cp.stdout or ""))[-1200:]
            result["note"] = "ONNX 转换失败，已保留原始 .pt 和转换日志。原因摘要：" + tail
        return result
    except Exception as e:
        result["note"] = f"ONNX 转换异常，已保留原始 .pt 包：{e}"
        return result


def _create_target_deploy_files(work: Path, target: str, metadata: Dict[str, Any], export_conf: Dict[str, Any], convert_result: Dict[str, Any]):
    cfg_dir = work / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    _write_export_json(cfg_dir / "deployment_config.json", export_conf)
    _write_export_yaml(cfg_dir / "deployment_config.yaml", export_conf)
    if target == "platform_package":
        _write_export_text(cfg_dir / "平台验证说明.md", "# 平台验证包\n\n用于本机检测台、项目归档和后续转换。导入时请使用 model_meta.json、labels/ 和 model/。\n")
    elif target == "paddledet_weight":
        _write_export_yaml(cfg_dir / "paddledet_weight_deploy.yaml", {
            "runtime": "PaddleDetection",
            "model": metadata.get("model_file", f"model/{metadata.get('model_name')}"),
            "config": metadata.get("config_file", "config/原始训练配置缺失"),
            "labels": "labels/label_list.txt",
            "num_classes": metadata.get("num_classes"),
            "device": export_conf.get("device", "cpu"),
        })
    elif target == "paddledet_infer":
        _write_export_yaml(cfg_dir / "paddle_inference_deploy.yaml", {
            "runtime": "Paddle Inference / PaddleDetection export_model",
            "source_weight": metadata.get("model_file"),
            "inference_model_dir": "inference_model/",
            "labels": "labels/label_list.txt",
            "conversion_ok": bool(convert_result.get("ok")),
            "conversion_outputs": convert_result.get("outputs", []),
        })
    elif target == "ultralytics_onnx":
        _write_export_yaml(cfg_dir / "onnx_deploy.yaml", {
            "runtime": "ONNXRuntime / OpenVINO / TensorRT 可继续适配",
            "source_pt": metadata.get("model_file"),
            "onnx_outputs": convert_result.get("outputs", []),
            "input_size": export_conf.get("input_size"),
            "confidence": export_conf.get("confidence"),
            "conversion_ok": bool(convert_result.get("ok")),
        })
    elif target == "sophon_prepare":
        _write_export_yaml(cfg_dir / "sophon_prepare.yaml", {
            "runtime": "Sophon/BM/NPU conversion prepare package",
            "source_model": metadata.get("model_file"),
            "labels": "labels/label_list.txt",
            "target_chip": export_conf.get("target_chip"),
            "precision": export_conf.get("precision"),
            "quantization": export_conf.get("quantization"),
            "input_size": export_conf.get("input_size"),
            "next_step": "使用算能官方转换工具链生成 bmodel，并在目标盒子上校验输入输出、类别和阈值。",
        })


def _do_export_model_package(project_id: str, payload: ModelExportReq):
    project = get_project(project_id)
    p = project_dir(project_id)
    if payload.algorithm_id and payload.version_id:
        model_path = None
        model_name = payload.model_name or "algorithm_version_model"
        model_key = ""
        for a in list_algorithms_internal(project_id):
            if a.get("id") == payload.algorithm_id:
                v = next((x for x in a.get("versions", []) if x.get("id") == payload.version_id), None)
                if v:
                    model_path = Path(v.get("stored_path", "")); model_name = v.get("model_name") or model_path.name
                    model_key = f"algorithm::{payload.algorithm_id}::{payload.version_id}"
                break
        if not model_path or not model_path.exists() or not model_path.is_file():
            raise HTTPException(status_code=404, detail="算法版本模型不存在。")
    else:
        model_path, model_name, model_key = resolve_any_model_path(project_id, payload.model_name, payload.model_source, payload.local_path or "")
    meta = _find_model_meta(project_id, model_path, model_name)
    job = _find_job_for_model(project_id, meta)
    target = (payload.deployment_target or "platform_package").strip()
    if target not in {"platform_package", "paddledet_weight", "paddledet_infer", "ultralytics_onnx", "sophon_prepare"}:
        raise HTTPException(status_code=400, detail=f"不支持的导出目标：{target}")
    suffix = model_path.suffix.lower()
    framework = meta.get("framework") or ("paddle" if suffix in {".pdparams", ".pdmodel", ".pdiparams"} else "ultralytics" if suffix == ".pt" else "unknown")
    if target.startswith("paddledet") and framework != "paddle":
        raise HTTPException(status_code=400, detail="当前导出目标是飞桨部署包，但所选模型不是飞桨模型。请选择 .pdparams/.pdmodel/.pdiparams。")
    if target == "ultralytics_onnx" and suffix != ".pt":
        raise HTTPException(status_code=400, detail="ONNX 导出目前只支持 Ultralytics .pt 模型。")
    labels = _export_labels(project, meta, job)
    export_conf = _build_export_config(payload, model_path, framework, labels)
    export_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    pkg_name = f"export_{safe_filename(model_path.stem)}_{target}_{export_id}"
    work = p / "exports" / pkg_name
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    copied_models = _copy_model_related_files(model_path, work / "model")
    cfg_path = meta.get("config_path") or meta.get("generated_config_path") or meta.get("algorithm_config_path") or job.get("generated_config_path") or job.get("algorithm_config_path") or ""
    cfg_file = ""
    if cfg_path and _copy_if_exists(cfg_path, work / "config" / Path(str(cfg_path)).name):
        cfg_file = f"config/{Path(str(cfg_path)).name}"
    if payload.include_dataset_labels:
        (work / "labels").mkdir(parents=True, exist_ok=True)
        _write_export_text(work / "labels" / "label_list.txt", "\n".join(labels))
        _write_export_json(work / "labels" / "labels.json", labels)
    if payload.include_report:
        report_dir = work / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        if job:
            jf = p / "jobs" / str(meta.get("job_id")) / "job.json"
            if jf.exists(): shutil.copy2(jf, report_dir / "job.json")
            for log_name in ["train.log", "log.txt"]:
                lf = p / "jobs" / str(meta.get("job_id")) / log_name
                if lf.exists(): shutil.copy2(lf, report_dir / log_name)
        try:
            _write_export_json(report_dir / "train_report.json", job_report(project_id, meta.get("job_id", ""), model_path))
        except Exception as e:
            _write_export_text(report_dir / "train_report_error.txt", str(e))

    convert_result = {"ok": False, "note": "", "outputs": []}
    if target == "paddledet_infer":
        penv = get_active_paddle_env()
        convert_result = _try_export_paddledet_infer(project_id, penv.get("python_path", ""), model_path, {**meta, "config_path": cfg_path}, work, export_conf)
    elif target == "ultralytics_onnx":
        convert_result = _try_export_ultralytics_onnx(project_id, model_path, work / "converted", export_conf)
    elif target == "sophon_prepare":
        convert_result = {"ok": True, "note": "已生成算能/边缘部署准备包；该包用于后续芯片工具链转换，不直接等于可运行 bmodel。", "outputs": []}
    elif target == "paddledet_weight":
        convert_result = {"ok": True, "note": "已生成 PaddleDetection 权重部署包；可继续用 PaddleDetection 配置 + .pdparams 加载部署。", "outputs": []}
    else:
        convert_result = {"ok": True, "note": "已生成平台验证包；适合本机检测台、归档和后续转换。", "outputs": []}

    metadata = {
        "export_id": export_id,
        "export_time": now_iso(),
        "project_id": project_id,
        "project_name": project.get("name"),
        "model_name": model_path.name,
        "model_file": f"model/{model_path.name}",
        "model_path_source": str(model_path),
        "model_key": model_key,
        "model_type": suffix.lstrip("."),
        "deployment_target": target,
        "framework": framework,
        "num_classes": int(meta.get("num_classes") or job.get("num_classes") or len(labels) or 0),
        "labels": labels,
        "config_path_source": str(cfg_path or ""),
        "config_file": cfg_file,
        "job_id": meta.get("job_id", ""),
        "job_name": meta.get("job_name", ""),
        "export_config": export_conf,
        "conversion": convert_result,
        "copied_models": copied_models,
    }
    _write_export_json(work / "model_meta.json", metadata)
    _create_target_deploy_files(work, target, metadata, export_conf, convert_result)
    note = convert_result.get("note") or "导出包已生成。"
    readme = f"""# 畅联云算法导出包

模型：{model_path.name}
导出目标：{target}
框架：{framework}
类别数：{metadata['num_classes']}
导出时间：{metadata['export_time']}

## 导出结果
{note}

## 目录
- model/：模型文件，飞桨推理模型会包含关联文件
- config/：部署目标配置、运行参数、转换说明
- labels/：标签列表
- report/：训练报告和训练日志（如勾选）
- converted/：Ultralytics ONNX 转换产物（如选择）
- inference_model/：PaddleDetection export_model 推理模型（如选择且转换成功）

## 使用提醒
1. 平台验证包：直接用于本系统检测台、项目归档和交接。
2. PaddleDetection 权重包：用于飞桨代码环境继续加载 .pdparams。
3. Paddle 推理模型：优先看 inference_model 目录；若转换失败，请查看 export_model_command.txt。
4. ONNX 包：优先看 converted 目录；若转换失败，请查看 export_onnx_command.txt。
5. 算能/边缘盒子准备包：不是最终 bmodel，需继续使用目标芯片工具链转换、量化和实机验证。

## 蒸馏说明
导出不是蒸馏。蒸馏需要教师模型、学生模型、蒸馏数据和单独训练任务。
"""
    _write_export_text(work / "README.md", readme)
    zip_path = p / "exports" / f"{pkg_name}.zip"
    _zip_dir(work, zip_path)
    return {
        "ok": True,
        "name": zip_path.name,
        "download_url": f"/data/projects/{project_id}/exports/{zip_path.name}",
        "path": str(zip_path),
        "note": note,
        "metadata": metadata,
        "conversion_ok": bool(convert_result.get("ok")),
    }


@app.post("/api/v30/projects/{project_id}/model-export")
def v30_export_model_package(project_id: str, payload: ModelExportReq):
    try:
        return _do_export_model_package(project_id, payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败：{type(e).__name__}: {e}")


@app.post("/api/v32/projects/{project_id}/model-export")
def v32_export_model_package(project_id: str, payload: ModelExportReq):
    return v30_export_model_package(project_id, payload)


# -----------------------------
# v33 视频切帧任务 + 素材库自动标注任务
# -----------------------------
import threading
import math

VIDEO_EXTS_V33 = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".mpeg", ".mpg", ".webm", ".m4v"}
_v33_task_lock = threading.RLock()


def _v33_tasks_file(project_id: str, kind: str) -> Path:
    ensure_project_dirs(project_id)
    return project_dir(project_id) / f"{kind}.json"


def _v33_load_tasks(project_id: str, kind: str) -> List[Dict[str, Any]]:
    with _v33_task_lock:
        return read_json(_v33_tasks_file(project_id, kind), [])


def _v33_save_tasks(project_id: str, kind: str, tasks: List[Dict[str, Any]]):
    with _v33_task_lock:
        write_json(_v33_tasks_file(project_id, kind), tasks)


def _v33_update_task(project_id: str, kind: str, task_id: str, **updates):
    with _v33_task_lock:
        tasks = read_json(_v33_tasks_file(project_id, kind), [])
        found = False
        for t in tasks:
            if t.get("id") == task_id:
                t.update(updates)
                t["updated_at"] = now_iso()
                found = True
                break
        if found:
            write_json(_v33_tasks_file(project_id, kind), tasks)


def _v33_get_task(project_id: str, kind: str, task_id: str) -> Optional[Dict[str, Any]]:
    return next((x for x in _v33_load_tasks(project_id, kind) if x.get("id") == task_id), None)


def _v33_set_image_split(project_id: str, image_id: str, split: str):
    images = load_images(project_id)
    for img in images:
        if img.get("id") == image_id:
            img["split"] = split or "unassigned"
            img["updated_at"] = now_iso()
            break
    save_images(project_id, images)


def _v33_run_video_frame_task(project_id: str, task_id: str):
    task = _v33_get_task(project_id, "video_frame_tasks", task_id)
    if not task:
        return
    try:
        try:
            import cv2  # type: ignore
        except Exception as e:
            raise RuntimeError(f"当前平台环境缺少 OpenCV，无法切帧。请安装 opencv-python。原始错误：{e}")

        video_path = Path(task["video_path"])
        if not video_path.exists():
            raise RuntimeError("视频文件不存在，可能已被删除")
        _v33_update_task(project_id, "video_frame_tasks", task_id, status="running", status_text="切帧中", started_at=now_iso(), progress=0)
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError("视频无法打开，请确认格式是否为 mp4/avi/mov/mkv 等常见视频格式")
        source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = round(total_frames / source_fps, 2) if total_frames else 0
        requested_fps = float(task.get("extract_fps") or 0)
        interval_seconds = float(task.get("interval_seconds") or 1.0)
        max_frames = int(task.get("max_frames") or 0)
        if requested_fps > 0:
            step = max(1, int(round(source_fps / requested_fps)))
            frequency_text = f"每秒 {requested_fps:g} 帧"
        else:
            step = max(1, int(round(source_fps * max(0.05, interval_seconds))))
            frequency_text = f"每 {interval_seconds:g} 秒 1 帧"
        dataset_id = task.get("dataset_id") or "default"
        split = task.get("split") or "unassigned"
        out_dir = project_dir(project_id) / "frame_tasks" / task_id / "frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = 0
        processed = 0
        started_ts = time.time()
        frame_indices: List[int]
        if total_frames > 0:
            frame_indices = list(range(0, total_frames, step))
            if max_frames > 0:
                frame_indices = frame_indices[:max_frames]
            iterator = frame_indices
            total_to_visit = len(frame_indices)
            for frame_idx in iterator:
                cur = _v33_get_task(project_id, "video_frame_tasks", task_id) or {}
                if cur.get("stop_requested"):
                    _v33_update_task(project_id, "video_frame_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                    cap.release()
                    return
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_idx))
                ok, frame = cap.read()
                processed += 1
                if not ok or frame is None:
                    continue
                ts = frame_idx / source_fps
                fname = f"{video_path.stem}_frame_{frame_idx:08d}_{ts:.2f}s.jpg".replace(":", "_")
                temp = out_dir / fname
                cv2.imwrite(str(temp), frame)
                rec = add_image_record(project_id, temp, fname, source_type="video_frame", dataset_id=dataset_id)
                if rec:
                    rec["video_task_id"] = task_id
                    rec["frame_index"] = int(frame_idx)
                    rec["frame_time_seconds"] = round(ts, 3)
                    _v33_set_image_split(project_id, rec["id"], split)
                    saved += 1
                progress = int(processed / max(1, total_to_visit) * 100)
                if saved % 5 == 0 or processed == total_to_visit:
                    elapsed=max(0.001,time.time()-started_ts);eta_seconds=int(max(0,elapsed/max(1,processed)*(total_to_visit-processed)))
                    _v33_update_task(project_id, "video_frame_tasks", task_id, progress=progress, extracted_frames=saved, processed_frames=processed, source_fps=round(source_fps, 3), duration_seconds=duration, frequency_text=frequency_text, elapsed_seconds=int(elapsed), eta_seconds=eta_seconds)
        else:
            frame_idx = 0
            while True:
                cur = _v33_get_task(project_id, "video_frame_tasks", task_id) or {}
                if cur.get("stop_requested"):
                    _v33_update_task(project_id, "video_frame_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                    cap.release()
                    return
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                if frame_idx % step == 0:
                    ts = frame_idx / source_fps
                    fname = f"{video_path.stem}_frame_{frame_idx:08d}_{ts:.2f}s.jpg".replace(":", "_")
                    temp = out_dir / fname
                    cv2.imwrite(str(temp), frame)
                    rec = add_image_record(project_id, temp, fname, source_type="video_frame", dataset_id=dataset_id)
                    if rec:
                        _v33_set_image_split(project_id, rec["id"], split)
                        saved += 1
                        if max_frames > 0 and saved >= max_frames:
                            break
                frame_idx += 1
                processed += 1
                if saved % 5 == 0:
                    _v33_update_task(project_id, "video_frame_tasks", task_id, extracted_frames=saved, processed_frames=processed, source_fps=round(source_fps, 3), frequency_text=frequency_text)
        cap.release()
        _v33_update_task(project_id, "video_frame_tasks", task_id, status="done", status_text="已完成", progress=100, extracted_frames=saved, processed_frames=processed, source_fps=round(source_fps, 3), duration_seconds=duration, frequency_text=frequency_text, finished_at=now_iso())
    except Exception as e:
        _v33_update_task(project_id, "video_frame_tasks", task_id, status="failed", status_text="失败", error=str(e), finished_at=now_iso())


@app.get("/api/v33/projects/{project_id}/video-tasks")
def v33_list_video_tasks(project_id: str):
    get_project(project_id)
    return {"items": _v33_load_tasks(project_id, "video_frame_tasks")}


@app.get("/api/v33/projects/{project_id}/video-tasks/{task_id}")
def v33_get_video_task(project_id: str, task_id: str):
    get_project(project_id)
    t = _v33_get_task(project_id, "video_frame_tasks", task_id)
    if not t:
        raise HTTPException(status_code=404, detail="切帧任务不存在")
    return t


@app.post("/api/v33/projects/{project_id}/video-tasks/{task_id}/stop")
def v33_stop_video_task(project_id: str, task_id: str):
    get_project(project_id)
    if not _v33_get_task(project_id, "video_frame_tasks", task_id):
        raise HTTPException(status_code=404, detail="切帧任务不存在")
    _v33_update_task(project_id, "video_frame_tasks", task_id, stop_requested=True, status_text="正在停止")
    return {"ok": True}


@app.post("/api/v33/projects/{project_id}/video-tasks")
async def v33_create_video_task(
    project_id: str,
    video: UploadFile = File(...),
    dataset_id: str = Form("default"),
    split: str = Form("unassigned"),
    interval_seconds: float = Form(1.0),
    extract_fps: float = Form(0.0),
    max_frames: int = Form(0),
):
    get_project(project_id)
    ensure_project_dirs(project_id)
    filename = safe_filename(video.filename or "video.mp4")
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTS_V33:
        raise HTTPException(status_code=400, detail="仅支持 mp4、avi、mov、mkv、flv、wmv、webm 等常见视频格式")
    task_id = uuid.uuid4().hex[:12]
    video_dir = project_dir(project_id) / "videos" / task_id
    video_dir.mkdir(parents=True, exist_ok=True)
    video_path = video_dir / filename
    with video_path.open("wb") as fp:
        while True:
            chunk = await video.read(1024 * 1024)
            if not chunk:
                break
            fp.write(chunk)
    task = {
        "id": task_id,
        "video_name": filename,
        "video_path": str(video_path),
        "dataset_id": dataset_id or "default",
        "split": split or "unassigned",
        "interval_seconds": float(interval_seconds or 1.0),
        "extract_fps": float(extract_fps or 0.0),
        "max_frames": int(max_frames or 0),
        "status": "queued",
        "status_text": "排队中",
        "progress": 0,
        "extracted_frames": 0,
        "processed_frames": 0,
        "stop_requested": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    tasks = _v33_load_tasks(project_id, "video_frame_tasks")
    tasks.insert(0, task)
    _v33_save_tasks(project_id, "video_frame_tasks", tasks[:100])
    th = threading.Thread(target=_v33_run_video_frame_task, args=(project_id, task_id), daemon=True)
    th.start()
    return task


class V33PrelabelTaskReq(BaseModel):
    service_id: Optional[str] = None
    detect_url: Optional[str] = None
    request_mode: str = "json_base64"
    image_field: str = "image"
    threshold: float = 0.5
    target_label: str = "person"
    image_ids: Optional[List[str]] = None
    overwrite: bool = False
    task_name: Optional[str] = "自动标注任务"


def _v33_run_prelabel_task(project_id: str, task_id: str, payload: Dict[str, Any]):
    try:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="running", status_text="自动标注中", started_at=now_iso())
        cfg = resolve_prelabel_config(PrelabelRunReq(**payload))
        project = get_project(project_id)
        target_label = normalize_label(cfg.get("target_label") or payload.get("target_label") or "person")
        class_id = ensure_label(project, target_label)
        project = get_project(project_id)
        ids = set(payload.get("image_ids") or [])
        images = load_images(project_id)
        dataset_id = str(payload.get("dataset_id") or "").strip()
        if dataset_id and dataset_id not in {"__all__", "all"}:
            images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
        if ids:
            images = [img for img in images if img.get("id") in ids]
        total = len(images)
        if not total:
            raise RuntimeError("没有可自动标注的图片")
        boxes_added = 0
        processed = 0
        started_ts = time.time()
        errors: List[Dict[str, Any]] = []
        for img in images:
            cur = _v33_get_task(project_id, "prelabel_tasks", task_id) or {}
            if cur.get("stop_requested"):
                _v33_update_task(project_id, "prelabel_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                return
            img_path = project_dir(project_id) / "uploads" / img.get("stored_name", "")
            try:
                raw = call_prelabel_service(cfg, img_path)
                detections = parse_detection_objects(raw, target_label, float(cfg.get("threshold", 0.5)))
                new_boxes = []
                for det in detections:
                    x1 = max(0, min(float(det["x1"]), img["width"]))
                    y1 = max(0, min(float(det["y1"]), img["height"]))
                    x2 = max(0, min(float(det["x2"]), img["width"]))
                    y2 = max(0, min(float(det["y2"]), img["height"]))
                    if x2 - x1 < 3 or y2 - y1 < 3:
                        continue
                    new_boxes.append({
                        "id": uuid.uuid4().hex[:10], "class_id": class_id, "label": target_label,
                        "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
                        "source": "prelabel_task", "confidence": round(float(det.get("confidence", 0)), 4),
                    })
                old = read_annotation(project_id, img["id"]).get("boxes", [])
                if payload.get("overwrite"):
                    merged = [b for b in old if int(b.get("class_id", -1)) != class_id] + new_boxes
                else:
                    merged = old + new_boxes
                write_annotation(project_id, img["id"], merged)
                boxes_added += len(new_boxes)
            except Exception as e:
                errors.append({"image": img.get("filename"), "error": str(e)})
            processed += 1
            if processed % 2 == 0 or processed == total:
                elapsed = max(0.001, time.time() - started_ts)
                eta_seconds = int(max(0, elapsed / max(1, processed) * (total - processed)))
                _v33_update_task(project_id, "prelabel_tasks", task_id, processed_images=processed, total_images=total, boxes_added=boxes_added, progress=int(processed / max(1, total) * 100), elapsed_seconds=int(elapsed), eta_seconds=eta_seconds, errors=errors[-20:])
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="done", status_text="已完成", progress=100, processed_images=processed, total_images=total, boxes_added=boxes_added, errors=errors[-20:], finished_at=now_iso(), labels=get_project(project_id).get("labels", []))
    except Exception as e:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="failed", status_text="失败", error=str(e), finished_at=now_iso())


@app.get("/api/v33/projects/{project_id}/prelabel-tasks")
def v33_list_prelabel_tasks(project_id: str):
    get_project(project_id)
    return {"items": _v33_load_tasks(project_id, "prelabel_tasks")}


@app.post("/api/v33/projects/{project_id}/prelabel-tasks/{task_id}/stop")
def v33_stop_prelabel_task(project_id: str, task_id: str):
    get_project(project_id)
    if not _v33_get_task(project_id, "prelabel_tasks", task_id):
        raise HTTPException(status_code=404, detail="自动标注任务不存在")
    _v33_update_task(project_id, "prelabel_tasks", task_id, stop_requested=True, status_text="正在停止")
    return {"ok": True}


@app.post("/api/v33/projects/{project_id}/prelabel-tasks")
def v33_create_prelabel_task(project_id: str, payload: V33PrelabelTaskReq):
    get_project(project_id)
    data = payload.dict()
    # 先解析一次，尽早发现服务不存在或地址为空。
    resolve_prelabel_config(PrelabelRunReq(**data))
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "name": data.get("task_name") or "自动标注任务",
        "target_label": normalize_label(data.get("target_label") or "person"),
        "threshold": float(data.get("threshold") or 0.5),
        "status": "queued",
        "status_text": "排队中",
        "progress": 0,
        "processed_images": 0,
        "total_images": len(data.get("image_ids") or []),
        "boxes_added": 0,
        "stop_requested": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "dataset_id": data.get("dataset_id") or "default",
        "request_payload": data,
    }
    tasks = _v33_load_tasks(project_id, "prelabel_tasks")
    tasks.insert(0, task)
    _v33_save_tasks(project_id, "prelabel_tasks", tasks[:100])
    th = threading.Thread(target=_v33_run_prelabel_task, args=(project_id, task_id, data), daemon=True)
    th.start()
    return task

# ============================================================
# v35: model configuration + prompt library + framework-aware auto labeling
# ============================================================
class V35ModelConfigReq(BaseModel):
    name: str
    provider_type: str = "local"  # local / cloud
    provider_adapter: Optional[str] = ""
    model_kind: str = "vision_detect"  # vision_detect / vlm / custom_http
    base_url: Optional[str] = ""
    detect_url: Optional[str] = ""
    health_url: Optional[str] = ""
    api_key: Optional[str] = ""
    model_name: Optional[str] = ""
    request_mode: str = "json_base64"  # json_base64 / multipart_file
    image_field: str = "image"
    prompt_field: str = "prompt"
    threshold_field: str = "threshold"
    headers_json: Optional[Dict[str, Any]] = None
    remark: Optional[str] = ""
    # v42.7: keep ordinary-user workflows simple; the system uses these templates automatically.
    annotation_prompt_template: Optional[str] = ""
    training_intervention_prompt: Optional[str] = ""
    default_for_annotation: bool = False
    default_for_training_ai: bool = False


class V35PromptTemplateReq(BaseModel):
    name: str
    framework: str = "ultralytics"  # ultralytics / paddle / common
    task_type: str = "目标检测"
    labels: Optional[List[str]] = None
    prompt: str
    output_schema: str = "bbox_json"
    model_config_id: Optional[str] = ""
    threshold: float = 0.5
    save_format: str = "internal"  # internal / yolo / paddle
    overwrite: bool = False
    remark: Optional[str] = ""


class V35PromptPreviewReq(BaseModel):
    prompt: str
    labels: Optional[List[Dict[str, Any]]] = None
    image_width: int = 640
    image_height: int = 480
    business_instruction: str = ""


class V35PrelabelTaskReq(BaseModel):
    model_config_id: Optional[str] = None
    prompt_template_id: Optional[str] = None
    detect_url: Optional[str] = None
    request_mode: str = "json_base64"
    image_field: str = "image"
    prompt: Optional[str] = ""
    prompt_field: str = "prompt"
    threshold: float = 0.5
    target_label: str = "person"
    image_ids: Optional[List[str]] = None
    overwrite: bool = False
    task_name: Optional[str] = "自动标注任务"
    training_framework: str = "internal"  # internal / ultralytics / paddle
    dataset_id: Optional[str] = "default"
    include_empty: bool = False


def _v35_items(file_path: Path) -> List[Dict[str, Any]]:
    return read_json(file_path, [])


def _v35_save_items(file_path: Path, items: List[Dict[str, Any]]):
    write_json(file_path, items)


def _v35_prompt_items() -> List[Dict[str, Any]]:
    items = _v35_items(PROMPT_LIBRARY_FILE)
    changed = False
    migrated: List[Dict[str, Any]] = []
    for item in items:
        if item.get("version_id") and item.get("version"):
            migrated.append(item)
            continue
        migrated.append(version_template(
            item,
            template_id=str(item.get("id") or uuid.uuid4().hex[:12]),
            now=str(item.get("updated_at") or item.get("created_at") or now_iso()),
        ))
        changed = True
    if changed:
        _v35_save_items(PROMPT_LIBRARY_FILE, migrated)
    return migrated


def _v35_validate_prompt(prompt: str):
    try:
        render_prompt(prompt, labels=[], width=1, height=1, business_instruction="")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _v35_secret_store():
    global MODEL_SECRET_STORE
    if MODEL_SECRET_STORE is not None:
        return MODEL_SECRET_STORE
    try:
        MODEL_SECRET_STORE = KeyringSecretStore()
        return MODEL_SECRET_STORE
    except Exception as error:
        raise PlatformError(
            code="SECRET_STORE_UNAVAILABLE",
            message="系统无法安全保存模型密钥",
            detail=str(error),
            solution="请执行依赖安装后重启平台；Windows 将使用系统凭据管理器保存 API Key。",
            status_code=503,
        ) from error


def _v35_clean_headers(headers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sensitive = {"authorization", "x-api-key", "api-key", "apikey"}
    return {str(key): value for key, value in (headers or {}).items() if str(key).lower() not in sensitive}


def _v35_model_items() -> List[Dict[str, Any]]:
    items = _v35_items(MODEL_CONFIGS_FILE)
    changed = False
    for item in items:
        legacy = str(item.pop("api_key", "") or "")
        if legacy:
            reference = str(item.get("secret_ref") or secret_ref("model-config", str(item.get("id") or uuid.uuid4().hex[:12])))
            _v35_secret_store().set(reference, legacy)
            item["secret_ref"] = reference
            changed = True
        cleaned = _v35_clean_headers(item.get("headers_json"))
        if cleaned != (item.get("headers_json") or {}):
            item["headers_json"] = cleaned
            changed = True
    if changed:
        _v35_save_items(MODEL_CONFIGS_FILE, items)
    return items


def _v35_sanitize_secret(item: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item)
    out.pop("api_key", None)
    reference = str(out.get("secret_ref") or "")
    masked = _v35_secret_store().masked(reference) if reference else ""
    out.pop("secret_ref", None)
    out["has_api_key"] = bool(masked)
    out["api_key_masked"] = masked
    return out


@app.get("/api/v35/model-configs")
def v35_list_model_configs():
    return {"items": [_v35_sanitize_secret(x) for x in _v35_model_items()]}


@app.post("/api/v35/model-configs")
def v35_save_model_config(payload: V35ModelConfigReq):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    detect_url = (payload.detect_url or payload.base_url or "").strip()
    if not detect_url:
        raise HTTPException(status_code=400, detail="检测接口地址不能为空")
    config_id = uuid.uuid4().hex[:12]
    item = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    api_key = str(item.pop("api_key", "") or "")
    item["headers_json"] = _v35_clean_headers(item.get("headers_json"))
    if api_key:
        reference = secret_ref("model-config", config_id)
        _v35_secret_store().set(reference, api_key)
        item["secret_ref"] = reference
    item.update({"id": config_id, "name": name, "detect_url": detect_url, "created_at": now_iso(), "updated_at": now_iso()})
    items = _v35_model_items()
    items.insert(0, item)
    _v35_save_items(MODEL_CONFIGS_FILE, items[:100])
    return _v35_sanitize_secret(item)


@app.put("/api/v35/model-configs/{config_id}")
def v35_update_model_config(config_id: str, payload: V35ModelConfigReq):
    items = _v35_model_items()
    found = False
    for i, item in enumerate(items):
        if item.get("id") == config_id:
            data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
            api_key = str(data.pop("api_key", "") or "")
            reference = str(item.get("secret_ref") or secret_ref("model-config", config_id))
            if api_key:
                _v35_secret_store().set(reference, api_key)
                data["secret_ref"] = reference
            elif item.get("secret_ref"):
                data["secret_ref"] = item.get("secret_ref")
            data["headers_json"] = _v35_clean_headers(data.get("headers_json"))
            data.update({"id": config_id, "created_at": item.get("created_at") or now_iso(), "updated_at": now_iso()})
            if not data.get("detect_url"):
                data["detect_url"] = data.get("base_url") or item.get("detect_url") or ""
            items[i] = data
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    _v35_save_items(MODEL_CONFIGS_FILE, items)
    return _v35_sanitize_secret(items[i])


@app.delete("/api/v35/model-configs/{config_id}")
def v35_delete_model_config(config_id: str):
    current = _v35_model_items()
    removed = next((x for x in current if x.get("id") == config_id), None)
    items = [x for x in current if x.get("id") != config_id]
    _v35_save_items(MODEL_CONFIGS_FILE, items)
    if removed and removed.get("secret_ref"):
        _v35_secret_store().delete(str(removed.get("secret_ref")))
    return {"ok": True}


@app.post("/api/v35/model-configs/test")
def v35_test_model_config(payload: V35ModelConfigReq):
    url = (payload.health_url or payload.detect_url or payload.base_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="接口地址为空")
    headers = dict(payload.headers_json or {})
    if payload.api_key:
        headers.setdefault("Authorization", f"Bearer {payload.api_key}")
    try:
        r = requests.get(url, headers=headers, timeout=8)
        text = r.text[:1200]
        body: Any = text
        if "json" in r.headers.get("content-type", ""):
            try:
                body = r.json()
            except Exception:
                pass
        return {"ok": True, "status_code": r.status_code, "response": body}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败：{e}")


@app.post("/api/v35/model-configs/{config_id}/test-annotation")
def v35_test_saved_model_annotation(config_id: str):
    cfg = next((item for item in _v35_model_items() if item.get("id") == config_id), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    runtime_cfg = dict(cfg)
    reference = str(cfg.get("secret_ref") or "")
    runtime_cfg["_api_key"] = _v35_secret_store().get(reference) if reference else ""
    try:
        provider = auto_label_core.provider_factory(runtime_cfg)
        buffer = BytesIO()
        Image.new("RGB", (128, 128), "white").save(buffer, format="JPEG")
        response = provider.annotate(
            image_bytes=buffer.getvalue(),
            prompt=(
                "请仅返回 JSON，检测图片中的 fire。"
                "输出格式必须为 boxes 数组，每个框包含 label、confidence、x1、y1、x2、y2。"
            ),
            output_schema=auto_label_core.CANDIDATE_OUTPUT_SCHEMA,
        )
        text = str(response.get("text") or "")
        boxes = auto_label_core.parse_candidate_response(
            text,
            width=128,
            height=128,
            label_ids={"fire": 0},
        )
        return {
            "reachable": True,
            "latency_ms": int(response.get("latency_ms") or 0),
            "provider": response.get("provider") or runtime_cfg.get("provider_type"),
            "model": response.get("model") or runtime_cfg.get("model_name"),
            "request_id": response.get("request_id") or "",
            "raw_preview": text[:500],
            "parsed_boxes": boxes,
        }
    except Exception as error:
        code = str(getattr(error, "code", "MODEL_CONNECTION_TEST_FAILED"))
        solution = str(getattr(error, "solution", "请检查服务地址、API Key、模型名称和模型输出协议。"))
        raise PlatformError(
            code=code,
            message="模型标注连接测试失败",
            detail=str(error),
            solution=solution,
            status_code=400,
        ) from error


@app.get("/api/v35/prompt-templates")
def v35_list_prompt_templates():
    return {"items": _v35_prompt_items()}


@app.post("/api/v35/prompt-templates")
def v35_save_prompt_template(payload: V35PromptTemplateReq):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if not (payload.prompt or "").strip():
        raise HTTPException(status_code=400, detail="提示词不能为空")
    _v35_validate_prompt(payload.prompt)
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    data["name"] = name
    item = version_template(data, template_id=uuid.uuid4().hex[:12], now=now_iso())
    items = _v35_prompt_items()
    items.insert(0, item)
    _v35_save_items(PROMPT_LIBRARY_FILE, items[:200])
    return item


@app.put("/api/v35/prompt-templates/{template_id}")
def v35_update_prompt_template(template_id: str, payload: V35PromptTemplateReq):
    if not (payload.name or "").strip():
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if not (payload.prompt or "").strip():
        raise HTTPException(status_code=400, detail="提示词不能为空")
    _v35_validate_prompt(payload.prompt)
    items = _v35_prompt_items()
    for i, item in enumerate(items):
        if item.get("id") == template_id:
            payload_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
            data = version_template(payload_data, template_id=template_id, now=now_iso(), previous=item)
            items[i] = data
            _v35_save_items(PROMPT_LIBRARY_FILE, items)
            return data
    raise HTTPException(status_code=404, detail="提示词模板不存在")


@app.delete("/api/v35/prompt-templates/{template_id}")
def v35_delete_prompt_template(template_id: str):
    items = [x for x in _v35_prompt_items() if x.get("id") != template_id]
    _v35_save_items(PROMPT_LIBRARY_FILE, items)
    return {"ok": True}


@app.post("/api/v35/prompt-templates/preview")
def v35_preview_prompt_template(payload: V35PromptPreviewReq):
    try:
        rendered = render_prompt(
            payload.prompt,
            labels=payload.labels or [],
            width=payload.image_width,
            height=payload.image_height,
            business_instruction=payload.business_instruction,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"rendered_prompt": rendered, "version_id": template_version_id(payload.prompt)}


def _v35_resolve_model_and_prompt(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    configs = _v35_model_items()
    templates = _v35_prompt_items()
    cfg: Dict[str, Any] = {}
    tpl: Dict[str, Any] = {}
    if payload.get("prompt_template_snapshot"):
        tpl = dict(payload.get("prompt_template_snapshot") or {})
    elif payload.get("prompt_template_id"):
        tpl = next((x for x in templates if x.get("id") == payload.get("prompt_template_id")), {})
        if not tpl:
            raise HTTPException(status_code=400, detail="模型标注模板不存在")
    config_id = payload.get("model_config_id") or tpl.get("model_config_id")
    if config_id:
        cfg = next((x for x in configs if x.get("id") == config_id), {})
        if not cfg:
            raise HTTPException(status_code=400, detail="模型配置不存在")
    else:
        detect_url = (payload.get("detect_url") or "").strip()
        if not detect_url:
            raise HTTPException(status_code=400, detail="请选择模型配置或填写临时检测接口")
        cfg = {
            "id": "manual", "name": "临时接口", "detect_url": detect_url,
            "request_mode": payload.get("request_mode") or "json_base64",
            "image_field": payload.get("image_field") or "image",
            "prompt_field": payload.get("prompt_field") or "prompt",
            "threshold_field": "threshold",
        }
    # template values override if user did not explicitly set.
    return cfg, tpl


def _v35_call_model(cfg: Dict[str, Any], image_path: Path, payload: Dict[str, Any], prompt_text: str, threshold: float) -> Dict[str, Any]:
    url = (cfg.get("detect_url") or cfg.get("base_url") or "").strip()
    if not url:
        raise ValueError("模型检测接口为空")
    headers = dict(cfg.get("headers_json") or {})
    if cfg.get("api_key"):
        headers.setdefault("Authorization", f"Bearer {cfg.get('api_key')}")
    mode = payload.get("request_mode") or cfg.get("request_mode") or "json_base64"
    image_field = payload.get("image_field") or cfg.get("image_field") or "image"
    prompt_field = payload.get("prompt_field") or cfg.get("prompt_field") or "prompt"
    threshold_field = cfg.get("threshold_field") or "threshold"
    if mode == "multipart_file":
        data = {threshold_field: str(threshold)}
        if prompt_text:
            data[prompt_field] = prompt_text
        if cfg.get("model_name"):
            data["model"] = cfg.get("model_name")
        with image_path.open("rb") as fp:
            r = requests.post(url, headers=headers, files={image_field: (image_path.name, fp, "application/octet-stream")}, data=data, timeout=180)
    else:
        raw = image_path.read_bytes()
        body = {
            image_field: base64.b64encode(raw).decode("utf-8"),
            threshold_field: threshold,
        }
        if prompt_text:
            body[prompt_field] = prompt_text
        if cfg.get("model_name"):
            body["model"] = cfg.get("model_name")
        r = requests.post(url, headers=headers, json=body, timeout=180)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def _v35_framework_build_after_prelabel(project_id: str, framework: str, dataset_id: Optional[str], include_empty: bool) -> Dict[str, Any]:
    fw = (framework or "internal").lower()
    if fw in {"ultralytics", "yolo"}:
        res = build_yolo_dataset_v12(project_id, dataset_id, include_empty)
        return {"framework": "ultralytics", "format": "YOLO", "path": res.get("dataset"), "data_yaml": res.get("data_yaml"), "counts": res.get("counts")}
    if fw in {"paddle", "paddledetection", "paddlex"}:
        res = build_paddle_dataset_internal(project_id, dataset_id=dataset_id, include_empty=include_empty)  # type: ignore[arg-type]
        return {"framework": "paddle", "format": "COCO/Paddle", "path": res.get("dataset"), "train_json": res.get("train_json"), "val_json": res.get("val_json"), "counts": res.get("counts")}
    return {"framework": "internal", "format": "平台内部标注", "path": str(project_dir(project_id) / "annotations")}


def _v35_run_prelabel_task(project_id: str, task_id: str, payload: Dict[str, Any]):
    try:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="running", status_text="自动标注中", started_at=now_iso())
        cfg, tpl = _v35_resolve_model_and_prompt(payload)
        prompt_text = payload.get("prompt") or tpl.get("prompt") or ""
        threshold = float(payload.get("threshold") if payload.get("threshold") is not None else tpl.get("threshold", 0.5))
        target_label = normalize_label(payload.get("target_label") or (tpl.get("labels") or ["person"])[0] or "person")
        project = get_project(project_id)
        class_id = ensure_label(project, target_label)
        ids = set(payload.get("image_ids") or [])
        images = load_images(project_id)
        dataset_id = payload.get("dataset_id") or "default"
        if ids:
            images = [img for img in images if img.get("id") in ids]
        else:
            images = [img for img in images if (img.get("dataset_id", "default") == dataset_id)]
        total = len(images)
        if not total:
            raise RuntimeError("没有可自动标注的图片")
        boxes_added = 0
        processed = 0
        started_ts = time.time()
        errors: List[Dict[str, Any]] = []
        for img in images:
            cur = _v33_get_task(project_id, "prelabel_tasks", task_id) or {}
            if cur.get("stop_requested"):
                _v33_update_task(project_id, "prelabel_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                return
            img_path = project_dir(project_id) / "uploads" / img.get("stored_name", "")
            try:
                raw = _v35_call_model(cfg, img_path, payload, prompt_text, threshold)
                detections = parse_detection_objects(raw, target_label, threshold)
                new_boxes = []
                for det in detections:
                    x1 = max(0, min(float(det["x1"]), img["width"]))
                    y1 = max(0, min(float(det["y1"]), img["height"]))
                    x2 = max(0, min(float(det["x2"]), img["width"]))
                    y2 = max(0, min(float(det["y2"]), img["height"]))
                    if x2 - x1 < 3 or y2 - y1 < 3:
                        continue
                    lbl = normalize_label(det.get("label") or target_label)
                    cid = ensure_label(get_project(project_id), lbl)
                    new_boxes.append({
                        "id": uuid.uuid4().hex[:10], "class_id": cid, "label": lbl,
                        "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
                        "source": "model_prelabel", "confidence": round(float(det.get("confidence", 0)), 4),
                        "model_config_id": cfg.get("id"), "prompt_template_id": tpl.get("id", ""),
                    })
                old = read_annotation(project_id, img["id"]).get("boxes", [])
                if payload.get("overwrite"):
                    target_cids = {b.get("class_id") for b in new_boxes}
                    merged = [b for b in old if b.get("class_id") not in target_cids] + new_boxes
                else:
                    merged = old + new_boxes
                write_annotation(project_id, img["id"], merged)
                boxes_added += len(new_boxes)
            except Exception as e:
                errors.append({"image": img.get("filename"), "error": str(e)})
            processed += 1
            if processed % 2 == 0 or processed == total:
                elapsed = max(0.001, time.time() - started_ts)
                eta_seconds = int(max(0, elapsed / max(1, processed) * (total - processed)))
                _v33_update_task(project_id, "prelabel_tasks", task_id, processed_images=processed, total_images=total, boxes_added=boxes_added, progress=int(processed / max(1, total) * 100), elapsed_seconds=int(elapsed), eta_seconds=eta_seconds, errors=errors[-20:])
        if processed and len(errors) >= processed and boxes_added == 0:
            first_error = errors[0].get("error") if errors else "模型没有返回可用标注"
            _v33_update_task(project_id, "prelabel_tasks", task_id, status="failed", status_text="失败", progress=100, processed_images=processed, total_images=total, boxes_added=0, errors=errors[-20:], error=first_error, finished_at=now_iso())
            return
        export_result = {}
        try:
            export_result = _v35_framework_build_after_prelabel(project_id, payload.get("training_framework") or tpl.get("save_format") or "internal", dataset_id, bool(payload.get("include_empty", False)))
        except Exception as e:
            export_result = {"error": str(e), "framework": payload.get("training_framework") or "internal"}
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="done", status_text="已完成", progress=100, processed_images=processed, total_images=total, boxes_added=boxes_added, errors=errors[-20:], export_result=export_result, finished_at=now_iso(), labels=get_project(project_id).get("labels", []))
    except Exception as e:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="failed", status_text="失败", error=str(e), finished_at=now_iso())


@app.post("/api/v35/projects/{project_id}/prelabel-tasks")
def v35_create_prelabel_task(project_id: str, payload: V35PrelabelTaskReq):
    get_project(project_id)
    data = payload.dict()
    cfg, tpl = _v35_resolve_model_and_prompt(data)
    if tpl:
        data["prompt_template_snapshot"] = tpl
    task_id = uuid.uuid4().hex[:12]
    name = data.get("task_name") or tpl.get("name") or "自动标注任务"
    task = {
        "id": task_id,
        "name": name,
        "model_name": cfg.get("name"),
        "prompt_template_name": tpl.get("name", ""),
        "prompt_template_id": tpl.get("id", ""),
        "prompt_template_version": tpl.get("version"),
        "prompt_template_version_id": tpl.get("version_id", ""),
        "target_label": normalize_label(data.get("target_label") or (tpl.get("labels") or ["person"])[0] or "person"),
        "threshold": float(data.get("threshold") or tpl.get("threshold", 0.5)),
        "training_framework": data.get("training_framework") or tpl.get("save_format") or "internal",
        "status": "queued",
        "status_text": "排队中",
        "progress": 0,
        "processed_images": 0,
        "total_images": len(data.get("image_ids") or []),
        "boxes_added": 0,
        "stop_requested": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "dataset_id": data.get("dataset_id") or "default",
        "request_payload": data,
    }
    tasks = _v33_load_tasks(project_id, "prelabel_tasks")
    tasks.insert(0, task)
    _v33_save_tasks(project_id, "prelabel_tasks", tasks[:100])
    th = threading.Thread(target=_v35_run_prelabel_task, args=(project_id, task_id, data), daemon=True)
    th.start()
    return task

# ============================================================
# v36: path / URL source import for local folders, servers, zip/images
# ============================================================
class V36SourceImportScanReq(BaseModel):
    source: str
    source_type: str = "auto"  # auto / local_path / url
    dataset_kind: str = "auto"  # auto / images / yolo / coco / voc


class V36SourceImportStartReq(BaseModel):
    source: str
    source_type: str = "auto"
    dataset_kind: str = "auto"
    task_name: Optional[str] = "地址读取导入"
    split_policy: str = "annotated_train_unannotated_test"  # source / annotated_train_unannotated_test / ratio
    train_ratio: float = 0.8
    val_ratio: float = 0.2
    test_ratio: float = 0.0
    copy_mode: str = "copy"  # reserved
    selected_paths: Optional[List[str]] = None


def _v36_source_jobs_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "source_import_tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _v36_source_job_file(project_id: str, job_id: str) -> Path:
    return _v36_source_jobs_dir(project_id) / f"{job_id}.json"


def _v36_load_source_jobs(project_id: str) -> List[Dict[str, Any]]:
    d = _v36_source_jobs_dir(project_id)
    items = []
    for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            items.append(read_json(f, {}))
        except Exception:
            pass
    return items


def _v36_write_source_job(project_id: str, job: Dict[str, Any]):
    job["updated_at"] = now_iso()
    write_json(_v36_source_job_file(project_id, job["id"]), job)


def _v36_update_source_job(project_id: str, job_id: str, **kwargs):
    f = _v36_source_job_file(project_id, job_id)
    if not f.exists():
        return
    job = read_json(f, {})
    job.update(kwargs)
    _v36_write_source_job(project_id, job)


def _v36_normalize_source(source: str) -> str:
    return str(source or "").strip().strip('"').strip("'")


def _v36_is_url(source: str) -> bool:
    return bool(re.match(r"^https?://", source.strip(), re.I))


def _v36_suffix_from_url(url: str) -> str:
    path = url.split("?", 1)[0].split("#", 1)[0]
    return Path(path).suffix.lower()


def _v36_scan_local_root(root: Path, max_items: int = 5000) -> Dict[str, Any]:
    if not root.exists():
        raise HTTPException(status_code=400, detail=f"路径不存在：{root}")
    files: List[Path] = []
    if root.is_file():
        files = [root]
    else:
        for f in root.rglob("*"):
            if f.is_file():
                files.append(f)
                if len(files) >= max_items:
                    break
    image_files = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
    yolo_labels = [f for f in files if f.suffix.lower() == ".txt" and f.name.lower() not in {'classes.txt','obj.names','_darknet.labels','train.txt','val.txt','test.txt'}]
    coco_files = []
    for f in files:
        if f.suffix.lower() != ".json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict) and isinstance(data.get("images"), list) and isinstance(data.get("annotations"), list) and isinstance(data.get("categories"), list):
                coco_files.append(f)
        except Exception:
            pass
    voc_files = [f for f in files if f.suffix.lower() == ".xml"]
    stems_with_labels = {x.stem for x in yolo_labels} | {x.stem for x in voc_files}
    annotated_by_name = 0
    if coco_files:
        # COCO 可能标注图不与文件同名，先粗略认为 COCO 内图片为已标注候选。
        try:
            coco = json.loads(coco_files[0].read_text(encoding="utf-8", errors="ignore"))
            ann_ids = {int(a.get("image_id")) for a in coco.get("annotations", []) if a.get("image_id") is not None}
            annotated_by_name = len(ann_ids)
        except Exception:
            annotated_by_name = 0
    else:
        annotated_by_name = sum(1 for im in image_files if im.stem in stems_with_labels)
    hints = []
    if coco_files: hints.append("COCO")
    if voc_files: hints.append("VOC")
    if yolo_labels or list(root.rglob("data.yaml")) if root.is_dir() else False: hints.append("YOLO")
    if not hints and image_files: hints.append("普通图片")
    def rel(f: Path) -> str:
        try:
            return str(f.relative_to(root if root.is_dir() else root.parent)).replace("\\", "/")
        except Exception:
            return f.name
    samples = [{"path": rel(f), "name": f.name, "split": _v18_split_from_path(f), "annotated_guess": f.stem in stems_with_labels} for f in image_files[:200]]
    return {
        "source": str(root),
        "source_type": "local_path",
        "exists": True,
        "is_file": root.is_file(),
        "file_count": len(files),
        "image_count": len(image_files),
        "annotated_guess": min(annotated_by_name, len(image_files)),
        "unannotated_guess": max(0, len(image_files) - min(annotated_by_name, len(image_files))),
        "yolo_label_files": len(yolo_labels),
        "coco_files": len(coco_files),
        "voc_files": len(voc_files),
        "format_hints": hints or ["未知"],
        "samples": samples,
        "truncated": len(files) >= max_items,
    }


def _v36_scan_url(source: str) -> Dict[str, Any]:
    url = _v36_normalize_source(source)
    suffix = _v36_suffix_from_url(url)
    try:
        h = requests.head(url, timeout=8, allow_redirects=True)
        content_type = h.headers.get("content-type", "")
        size = int(h.headers.get("content-length") or 0)
    except Exception:
        content_type = ""
        size = 0
    hints: List[str] = []
    if suffix == ".zip" or "zip" in content_type.lower(): hints.append("ZIP数据集")
    elif suffix in IMAGE_EXTS or "image/" in content_type.lower(): hints.append("单张图片")
    elif suffix in {".json"}: hints.append("COCO/JSON")
    else: hints.append("HTTP资源")
    return {"source": url, "source_type": "url", "exists": True, "is_file": True, "file_count": 1, "image_count": 0 if suffix not in IMAGE_EXTS else 1, "annotated_guess": 0, "unannotated_guess": 0 if suffix not in IMAGE_EXTS else 1, "format_hints": hints, "content_type": content_type, "size_mb": round(size/1024/1024, 2) if size else 0, "samples": []}


def _v36_base_report() -> Dict[str, Any]:
    return {"ok": True, "detected_format": "未知", "imported_images": 0, "annotated_images": 0, "unannotated_images": 0, "boxes": 0, "missing_images": 0, "skipped_images": 0, "invalid_boxes": 0, "skipped_labels": 0, "unmatched_labels": 0, "labels": [], "warnings": []}


def _v36_download_source_to_file(url: str, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def _v36_import_single_image(project_id: str, src: Path, dataset_id: str, report: Dict[str, Any]):
    rec = add_image_record(project_id, src, src.name, "source_path", dataset_id)
    if rec:
        _v18_set_image_split(project_id, rec["id"], "test")
        report["imported_images"] += 1
        report["unannotated_images"] += 1
        report["detected_format"] = "普通图片"


def _v36_import_from_root(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any]) -> bool:
    imported = False
    imported = _v18_import_coco(project_id, root, dataset_id, report)
    if not imported:
        imported = _v18_import_voc(project_id, root, dataset_id, report)
    if not imported:
        imported = _v18_import_yolo(project_id, root, dataset_id, report)
    if imported:
        report["unannotated_images"] = max(0, int(report.get("imported_images", 0)) - int(report.get("annotated_images", 0)))
    return imported


def _v36_apply_split_policy(project_id: str, imported_ids: List[str], policy: str, train_ratio: float, val_ratio: float, test_ratio: float) -> Dict[str, int]:
    if not imported_ids:
        return {"train": 0, "val": 0, "test": 0}
    images = load_images(project_id)
    img_map = {x.get("id"): x for x in images if x.get("id") in set(imported_ids)}
    annotated_ids = []
    unannotated_ids = []
    for iid in imported_ids:
        ann = read_annotation(project_id, iid).get("boxes", [])
        if ann:
            annotated_ids.append(iid)
        else:
            unannotated_ids.append(iid)
    counts = {"train": 0, "val": 0, "test": 0}
    policy = (policy or "annotated_train_unannotated_test").lower()
    if policy == "source":
        for iid in imported_ids:
            sp = img_map.get(iid, {}).get("split") or "train"
            if sp not in counts: sp = "train"
            counts[sp] += 1
        return counts
    if policy == "ratio":
        ordered = sorted(imported_ids)
        total = len(ordered)
        tr = max(0.0, min(float(train_ratio or 0.8), 1.0))
        vr = max(0.0, min(float(val_ratio or 0.2), 1.0))
        n_train = min(total, int(total * tr))
        n_val = min(total - n_train, int(total * vr))
        for idx, iid in enumerate(ordered):
            split = "train" if idx < n_train else "val" if idx < n_train + n_val else "test"
            if iid in img_map:
                img_map[iid]["split"] = split
                counts[split] += 1
    else:
        # 默认：有标注的进入训练/评测；无标注的进入试验集，避免误把无标注图用于训练。
        ordered = sorted(annotated_ids)
        n_train = min(len(ordered), max(1, int(len(ordered) * float(train_ratio or 0.8)))) if ordered else 0
        for idx, iid in enumerate(ordered):
            split = "train" if idx < n_train else "val"
            if iid in img_map:
                img_map[iid]["split"] = split
                counts[split] += 1
        for iid in unannotated_ids:
            if iid in img_map:
                img_map[iid]["split"] = "test"
                counts["test"] += 1
    save_images(project_id, images)
    return counts


def _v36_run_source_import(project_id: str, dataset_id: str, job_id: str, payload: Dict[str, Any]):
    job_dir = project_dir(project_id) / "imports" / f"source_{job_id}"
    work_root = job_dir / "work"
    try:
        _v36_update_source_job(project_id, job_id, status="running", status_text="读取中", stage="正在准备来源", progress=5)
        source = _v36_normalize_source(payload.get("source") or "")
        if not source:
            raise RuntimeError("来源地址不能为空")
        before_ids = {x.get("id") for x in load_images(project_id)}
        report = _v36_base_report()
        job_dir.mkdir(parents=True, exist_ok=True)
        work_root.mkdir(parents=True, exist_ok=True)
        if _v36_is_url(source):
            _v36_update_source_job(project_id, job_id, stage="正在下载服务器文件", progress=18)
            suffix = _v36_suffix_from_url(source) or ".bin"
            src_file = job_dir / f"download{suffix}"
            _v36_download_source_to_file(source, src_file)
            if src_file.suffix.lower() == ".zip":
                _v36_update_source_job(project_id, job_id, stage="正在解压数据集", progress=35)
                _v18_safe_extract(src_file, work_root)
                _v36_update_source_job(project_id, job_id, stage="正在解析标注与素材", progress=55)
                ok = _v36_import_from_root(project_id, work_root, dataset_id, report)
                if not ok:
                    raise RuntimeError("没有识别到可导入图片或标注")
            elif src_file.suffix.lower() in IMAGE_EXTS:
                _v36_import_single_image(project_id, src_file, dataset_id, report)
            else:
                raise RuntimeError("当前 URL 仅支持 zip 数据集或单张图片文件")
        else:
            root = Path(source).expanduser()
            _v36_update_source_job(project_id, job_id, stage="正在扫描本机路径", progress=20)
            if not root.exists():
                raise RuntimeError(f"路径不存在：{root}")
            if root.is_file() and root.suffix.lower() == ".zip":
                _v36_update_source_job(project_id, job_id, stage="正在解压数据集", progress=35)
                _v18_safe_extract(root, work_root)
                _v36_update_source_job(project_id, job_id, stage="正在解析标注与素材", progress=55)
                ok = _v36_import_from_root(project_id, work_root, dataset_id, report)
            elif root.is_file() and root.suffix.lower() in IMAGE_EXTS:
                ok = True
                _v36_import_single_image(project_id, root, dataset_id, report)
            elif root.is_dir():
                _v36_update_source_job(project_id, job_id, stage="正在解析目录", progress=45)
                ok = _v36_import_from_root(project_id, root, dataset_id, report)
            else:
                ok = False
            if not ok:
                raise RuntimeError("没有识别到可导入图片或标注。支持目录、zip、图片、YOLO/COCO/VOC 数据集。")
        after = load_images(project_id)
        imported_ids = [x.get("id") for x in after if x.get("id") not in before_ids]
        _v36_update_source_job(project_id, job_id, stage="正在分类训练/评测/试验集", progress=82)
        split_counts = _v36_apply_split_policy(project_id, imported_ids, payload.get("split_policy") or "annotated_train_unannotated_test", float(payload.get("train_ratio") or 0.8), float(payload.get("val_ratio") or 0.2), float(payload.get("test_ratio") or 0.0))
        report["labels"] = get_project(project_id).get("labels", [])
        report["split_counts"] = split_counts
        report["imported_ids"] = imported_ids
        _v36_update_source_job(project_id, job_id, status="done", status_text="已完成", stage="导入完成", progress=100, report=report, imported_images=report.get("imported_images", 0), annotated_images=report.get("annotated_images", 0), boxes=report.get("boxes", 0), split_counts=split_counts, finished_at=now_iso())
    except Exception as e:
        _v36_update_source_job(project_id, job_id, status="failed", status_text="失败", stage="导入失败", progress=100, error=str(e), finished_at=now_iso())
    finally:
        shutil.rmtree(job_dir / "work", ignore_errors=True)


@app.post("/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/scan")
def v36_scan_source_import(project_id: str, dataset_id: str, payload: V36SourceImportScanReq):
    get_project(project_id)
    source = _v36_normalize_source(payload.source)
    if not source:
        raise HTTPException(status_code=400, detail="请填写本机路径或服务器 URL")
    if _v36_is_url(source):
        return {"ok": True, **_v36_scan_url(source)}
    return {"ok": True, **_v36_scan_local_root(Path(source).expanduser())}


@app.get("/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/jobs")
def v36_list_source_import_jobs(project_id: str, dataset_id: str):
    get_project(project_id)
    items = [x for x in _v36_load_source_jobs(project_id) if x.get("dataset_id") == dataset_id]
    return {"items": items[:100]}


@app.post("/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/jobs")
def v36_start_source_import_job(project_id: str, dataset_id: str, payload: V36SourceImportStartReq):
    get_project(project_id)
    source = _v36_normalize_source(payload.source)
    if not source:
        raise HTTPException(status_code=400, detail="请填写本机路径或服务器 URL")
    job_id = uuid.uuid4().hex[:12]
    task = {
        "id": job_id,
        "name": payload.task_name or "地址读取导入",
        "source": source,
        "source_type": "url" if _v36_is_url(source) else "local_path",
        "dataset_id": dataset_id,
        "status": "queued",
        "status_text": "排队中",
        "stage": "等待开始",
        "progress": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    _v36_write_source_job(project_id, task)
    data = payload.dict()
    import threading as _threading
    th = _threading.Thread(target=_v36_run_source_import, args=(project_id, dataset_id, job_id, data), daemon=True)
    th.start()
    return task

# ============================================================
# v39: 部署转换中心（真实工具链）
# - 训练/导出与部署编译分离
# - 支持 ONNX / Paddle Inference / TensorRT / SOPHGO BMODEL / Ascend OM
# - 转换工具不存在时明确阻断，不模拟生成
# - 支持本机资源与 remote_deploy_server 远程转换资源
# ============================================================
import threading

DEPLOY_RESOURCES_FILE = DATA_DIR / "deploy_resources.json"
if not DEPLOY_RESOURCES_FILE.exists():
    DEPLOY_RESOURCES_FILE.write_text("[]", encoding="utf-8")
DEPLOY_PROCESS_REGISTRY: Dict[str, subprocess.Popen] = {}
DEPLOY_REMOTE_THREADS: Dict[str, threading.Thread] = {}


def deploy_root(project_id: str) -> Path:
    get_project(project_id)
    root = project_dir(project_id) / "deployment"
    for d in ["jobs", "artifacts", "tmp"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def _deploy_which(*candidates: str) -> str:
    for c in candidates:
        if not c:
            continue
        try:
            p = Path(str(c))
            if p.exists() and p.is_file():
                return str(p)
        except Exception:
            pass
        found = shutil.which(str(c))
        if found:
            return found
    return ""


def _deploy_cmd_version(cmd: str) -> str:
    if not cmd:
        return ""
    for args in ([cmd, "--version"], [cmd, "-v"], [cmd, "--help"]):
        try:
            cp = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=8)
            txt = (cp.stdout or cp.stderr or "").strip().splitlines()
            if txt:
                return txt[0][:240]
        except Exception:
            pass
    return ""


def _deploy_ultra_info(py: str) -> Dict[str, Any]:
    if not py or not Path(py).exists():
        return {"ok": False, "error": "Python 不存在"}
    try:
        cp = subprocess.run([py, "-c", "import ultralytics,json;print(json.dumps({'version':ultralytics.__version__,'path':ultralytics.__file__},ensure_ascii=False))"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=15)
        if cp.returncode != 0:
            return {"ok": False, "error": (cp.stdout or cp.stderr or "无法导入 ultralytics")[-1200:]}
        return {"ok": True, **json.loads((cp.stdout or "{}").splitlines()[-1])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _deploy_paddle_info(py: str) -> Dict[str, Any]:
    if not py or not Path(py).exists():
        return {"ok": False, "error": "Python 不存在"}
    try:
        cp = subprocess.run([py, "-c", "import paddle,json;print(json.dumps({'version':paddle.__version__,'device':paddle.device.get_device()},ensure_ascii=False))"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=15)
        if cp.returncode != 0:
            return {"ok": False, "error": (cp.stdout or cp.stderr or "无法导入 paddle")[-1200:]}
        return {"ok": True, **json.loads((cp.stdout or "{}").splitlines()[-1])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _builtin_deploy_resources() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    ultra = get_active_ultralytics_env() or {}
    upy = str(ultra.get("python_path") or "")
    ui = _deploy_ultra_info(upy) if upy else {"ok": False}
    rows.append({
        "id": "builtin_ultralytics", "name": "Ultralytics 导出环境", "kind": "ultralytics", "mode": "local", "builtin": True,
        "python_path": upy, "status": "ready" if ui.get("ok") else "missing", "version": ui.get("version", ""),
        "targets": ["onnx"] if ui.get("ok") else [], "message": "可将 .pt 真实导出为 ONNX" if ui.get("ok") else "请先在训练资源启用 Ultralytics 环境",
    })
    penv = get_active_paddle_env() or {}
    ppy = str(penv.get("python_path") or "")
    pd_dir = str(penv.get("paddledet_dir") or "")
    pi = _deploy_paddle_info(ppy) if ppy else {"ok": False}
    pd_ok = bool(pi.get("ok") and pd_dir and (Path(pd_dir) / "tools" / "export_model.py").exists())
    p2o = _deploy_which(str(Path(ppy).parent / "paddle2onnx.exe") if ppy else "", "paddle2onnx")
    rows.append({
        "id": "builtin_paddle", "name": "PaddleDetection 导出环境", "kind": "paddle", "mode": "local", "builtin": True,
        "python_path": ppy, "paddledet_dir": pd_dir, "paddle2onnx_path": p2o,
        "status": "ready" if pd_ok else "missing", "version": pi.get("version", ""),
        "targets": (["paddle_inference"] + (["onnx"] if p2o else [])) if pd_ok else [],
        "message": "可将 .pdparams 导出为 Paddle Inference" + ("，并可转 ONNX" if p2o else "") if pd_ok else "请先在训练资源配置 PaddleDetection",
    })
    return rows


def _load_saved_deploy_resources() -> List[Dict[str, Any]]:
    data = read_json(DEPLOY_RESOURCES_FILE, [])
    return data if isinstance(data, list) else []


def _save_deploy_resources(items: List[Dict[str, Any]]):
    write_json(DEPLOY_RESOURCES_FILE, items)


def _detect_local_deploy_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(item.get("kind") or "").lower()
    item = dict(item)
    item["last_checked_at"] = now_iso()
    item["targets"] = []
    item["status"] = "missing"
    if kind == "tensorrt":
        root = Path(str(item.get("tool_root") or "")) if item.get("tool_root") else None
        trt = _deploy_which(str(item.get("trtexec_path") or ""), str(root / "bin" / "trtexec") if root else "", "trtexec")
        item["trtexec_path"] = trt
        if trt:
            item.update(status="ready", targets=["tensorrt"], version=_deploy_cmd_version(trt), message="TensorRT trtexec 可用；FP32/FP16 可直接编译")
        else:
            item["message"] = "未检测到 trtexec"
    elif kind == "sophon":
        root = Path(str(item.get("tool_root") or "")) if item.get("tool_root") else None
        roots = [root, root / "python" / "tools"] if root else []
        transform = _deploy_which(*[str(r / "model_transform.py") for r in roots], "model_transform.py", "model_transform")
        deploy = _deploy_which(*[str(r / "model_deploy.py") for r in roots], "model_deploy.py", "model_deploy")
        cali = _deploy_which(*[str(r / "run_calibration.py") for r in roots], "run_calibration.py", "run_calibration")
        item.update(model_transform_path=transform, model_deploy_path=deploy, run_calibration_path=cali)
        if transform and deploy:
            item.update(status="ready", targets=["sophon"], version=_deploy_cmd_version(deploy), message="TPU-MLIR 可用；可生成 BMODEL")
        else:
            item["message"] = "未检测到 TPU-MLIR model_transform/model_deploy"
    elif kind == "ascend":
        root = Path(str(item.get("tool_root") or "")) if item.get("tool_root") else None
        ascend_home = str(os.environ.get("ASCEND_HOME_PATH") or os.environ.get("ASCEND_TOOLKIT_HOME") or "").strip()
        home = Path(ascend_home) if ascend_home else None
        candidates = [str(item.get("atc_path") or "")]
        if root:
            candidates += [str(root / "bin" / "atc"), str(root / "bin" / "atc.bin")]
        if home:
            candidates += [str(home / "bin" / "atc"), str(home / "bin" / "atc.bin")]
        candidates += ["atc", "atc.bin"]
        atc = _deploy_which(*candidates)
        item["atc_path"] = atc
        env_candidates = [str(item.get("env_script") or "")]
        if root:
            env_candidates += [str(root / "set_env.sh"), str(root.parent / "set_env.sh")]
        if home:
            env_candidates += [str(home / "set_env.sh"), str(home.parent / "set_env.sh")]
        env_script = next((x for x in env_candidates if x and Path(x).exists()), str(item.get("env_script") or ""))
        item["env_script"] = env_script
        nsmi = _deploy_which("npu-smi")
        item["npu_smi_path"] = nsmi
        item["cann_home"] = ascend_home or (str(root) if root else "")
        socs=[]
        device_text=""
        if nsmi:
            try:
                cp = subprocess.run([nsmi, "info"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=10)
                device_text = (cp.stdout or cp.stderr or "")[-5000:]
                # Different npu-smi releases show names in slightly different forms. Keep only concrete processor names.
                for m in re.findall(r"(?:Chip\s*Name\s*[:：]?\s*|Name\s*[:：]\s*)(?:Ascend\s*)?([0-9A-Za-z_-]+)", device_text, re.I):
                    v = "Ascend" + m.replace(" ", "")
                    if re.search(r"310|910", v, re.I) and v not in socs:
                        socs.append(v)
                for m in re.findall(r"Ascend\s*([0-9]{3,4}[A-Za-z0-9_-]*)", device_text, re.I):
                    v="Ascend"+m.replace(" ","")
                    if v not in socs:socs.append(v)
            except Exception:
                pass
        item["device_info"] = device_text
        item["detected_soc_versions"] = socs
        item["atlas_products"] = ["Atlas 300I Pro", "Atlas 300V", "Atlas 300V Pro", "Atlas 300I Duo", "Atlas 200I SoC A1", "Atlas A2 / 其他"]
        if atc:
            ver=_deploy_cmd_version(atc)
            msg="CANN ATC 可用，可真实编译 Atlas/Ascend OM"
            if socs: msg += "；检测到 " + "、".join(socs[:3])
            elif not nsmi: msg += "；转换机无 NPU 也可转换，部署 SoC 需手工指定"
            item.update(status="ready", targets=["ascend"], version=ver, message=msg, conversion_ready=True, hardware_detected=bool(nsmi and device_text))
        else:
            item.update(message="未检测到 CANN ATC；请安装 CANN Toolkit 或配置 ATC 路径", conversion_ready=False, hardware_detected=bool(nsmi and device_text))
    elif kind == "ultralytics":
        py = str(item.get("python_path") or sys.executable)
        info = _deploy_ultra_info(py)
        item.update(status="ready" if info.get("ok") else "missing", targets=["onnx"] if info.get("ok") else [], version=info.get("version", ""), message="Ultralytics 导出可用" if info.get("ok") else info.get("error", "Ultralytics 不可用"))
    elif kind == "paddle":
        py = str(item.get("python_path") or sys.executable)
        info = _deploy_paddle_info(py)
        pd_raw = str(item.get("paddledet_dir") or "").strip()
        pd = Path(pd_raw) if pd_raw else None
        p2o = _deploy_which(str(item.get("paddle2onnx_path") or ""), "paddle2onnx")
        ok = bool(info.get("ok") and pd and pd.exists() and (pd / "tools" / "export_model.py").exists())
        item.update(status="ready" if ok else "missing", targets=(['paddle_inference'] + (['onnx'] if p2o else [])) if ok else [], version=info.get("version", ""), paddle2onnx_path=p2o, message="PaddleDetection 导出可用" if ok else "PaddleDetection 导出环境不完整")
    else:
        item["message"] = "未知部署资源类型"
    return item


def _detect_remote_deploy_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(item)
    base = str(item.get("base_url") or "").rstrip("/")
    if not base:
        item.update(status="missing", targets=[], message="未填写远程服务地址", last_checked_at=now_iso())
        return item
    try:
        r = requests.get(base + "/api/deploy/health", headers={"X-API-Key": str(item.get("api_key") or "")}, timeout=12)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        item.update(status="ready", targets=data.get("targets", []), version=data.get("version", ""), message="远程部署转换服务可用", remote_health=data, last_checked_at=now_iso())
    except Exception as e:
        item.update(status="missing", targets=[], message=f"远程资源不可用：{e}", last_checked_at=now_iso())
    return item


class DeployResourceReq(BaseModel):
    name: str
    kind: str  # ultralytics / paddle / tensorrt / sophon / ascend / rockchip
    mode: str = "local"  # local / remote
    base_url: str = ""
    api_key: str = ""
    python_path: str = ""
    ultralytics_python: str = ""
    paddledet_dir: str = ""
    paddle2onnx_path: str = ""
    tool_root: str = ""
    trtexec_path: str = ""
    atc_path: str = ""
    env_script: str = ""
    remark: str = ""


@app.get("/api/v39/deploy/resources")
def v39_list_deploy_resources():
    return {"ok": True, "items": _builtin_deploy_resources() + _load_saved_deploy_resources()}


@app.post("/api/v39/deploy/resources")
def v39_create_deploy_resource(payload: DeployResourceReq):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="请输入部署资源名称")
    item = payload.model_dump()
    item.update({"id": uuid.uuid4().hex[:12], "created_at": now_iso(), "updated_at": now_iso(), "status": "unchecked", "targets": []})
    items = _load_saved_deploy_resources(); items.insert(0, item); _save_deploy_resources(items)
    return item


@app.put("/api/v39/deploy/resources/{resource_id}")
def v39_update_deploy_resource(resource_id: str, payload: DeployResourceReq):
    items = _load_saved_deploy_resources()
    for i, x in enumerate(items):
        if x.get("id") == resource_id:
            new = {**x, **payload.model_dump(), "updated_at": now_iso()}
            items[i] = new; _save_deploy_resources(items); return new
    raise HTTPException(status_code=404, detail="部署资源不存在")


@app.delete("/api/v39/deploy/resources/{resource_id}")
def v39_delete_deploy_resource(resource_id: str):
    items = _load_saved_deploy_resources()
    if not any(x.get("id") == resource_id for x in items):
        raise HTTPException(status_code=404, detail="部署资源不存在")
    _save_deploy_resources([x for x in items if x.get("id") != resource_id])
    return {"ok": True}


@app.post("/api/v39/deploy/resources/{resource_id}/detect")
def v39_detect_deploy_resource(resource_id: str):
    if resource_id.startswith("builtin_"):
        item = next((x for x in _builtin_deploy_resources() if x.get("id") == resource_id), None)
        if not item: raise HTTPException(status_code=404, detail="内置部署资源不存在")
        return item
    items = _load_saved_deploy_resources()
    idx = next((i for i,x in enumerate(items) if x.get("id") == resource_id), None)
    if idx is None: raise HTTPException(status_code=404, detail="部署资源不存在")
    item = items[idx]
    checked = _detect_remote_deploy_resource(item) if str(item.get("mode")) == "remote" else _detect_local_deploy_resource(item)
    items[idx] = checked; _save_deploy_resources(items)
    return checked


@app.post("/api/v39/deploy/local/auto-detect")
def v39_detect_local_deploy_resources():
    """只检测当前机器真正存在的部署编译器；不存在的不会伪造为 ready。"""
    items = _load_saved_deploy_resources()
    found = []
    candidates = [
        {"name":"本机瑞芯微 RKNN-Toolkit2", "kind":"rockchip", "mode":"local", "python_path":sys.executable, "tool_root":""},
        {"name":"本机 NVIDIA TensorRT", "kind":"tensorrt", "mode":"local", "tool_root":""},
        {"name":"本机算能 TPU-MLIR", "kind":"sophon", "mode":"local", "tool_root":os.environ.get("TPUC_ROOT", "")},
        {"name":"本机华为 CANN ATC", "kind":"ascend", "mode":"local", "tool_root":os.environ.get("ASCEND_TOOLKIT_HOME", ""), "env_script":"/usr/local/Ascend/ascend-toolkit/set_env.sh" if os.name != 'nt' else ""},
    ]
    for c in candidates:
        chk = _detect_local_deploy_resource({**c, "id": uuid.uuid4().hex[:12], "created_at":now_iso(), "updated_at":now_iso()})
        if chk.get("status") == "ready":
            existing = next((x for x in items if x.get("kind")==chk.get("kind") and x.get("mode")=="local"), None)
            if existing:
                keep_id = existing.get("id")
                keep_created = existing.get("created_at")
                existing.update(chk)
                existing["id"] = keep_id
                if keep_created: existing["created_at"] = keep_created
                existing["updated_at"] = now_iso()
                found.append(existing)
            else:
                items.insert(0, chk); found.append(chk)
    _save_deploy_resources(items)
    return {"ok": True, "found": found, "items": _builtin_deploy_resources() + items}


def _deploy_source_models(project_id: str) -> List[Dict[str, Any]]:
    items=[]
    for m in list_models_internal(project_id):
        ext = "." + str(m.get("type") or "")
        if ext in {".pt", ".pth", ".onnx", ".pdparams", ".pdmodel", ".pdiparams", ".engine", ".bmodel", ".om"}:
            items.append({"id":f"model::{m.get('name')}","kind":"project_model","name":m.get("name"),"path":m.get("path"),"type":m.get("type"),"framework":m.get("framework"),"job_id":m.get("job_id"),"config_path":m.get("config_path"),"size_mb":m.get("size_mb"),"label":m.get("name")})
    for a in list_algorithms_internal(project_id):
        for v in a.get("versions", []) or []:
            p=Path(str(v.get("stored_path") or ""))
            if p.exists():
                items.append({"id":f"version::{a.get('id')}::{v.get('id')}","kind":"algorithm_version","name":v.get("model_name") or p.name,"path":str(p),"type":p.suffix.lower().lstrip('.'),"framework":v.get("report",{}).get("framework", ""),"job_id":v.get("job_id", ""),"config_path":"","size_mb":v.get("size_mb",0),"algorithm_id":a.get("id"),"algorithm_name":a.get("name"),"version_id":v.get("id"),"version_name":v.get("version_name"),"label":f"{a.get('name')} / {v.get('version_name')} / {p.name}"})
    return items


@app.get("/api/v39/projects/{project_id}/deploy/source-models")
def v39_deploy_source_models(project_id: str):
    return {"ok": True, "items": _deploy_source_models(project_id)}


def _resolve_deploy_source(project_id: str, source_id: str) -> Dict[str, Any]:
    row = next((x for x in _deploy_source_models(project_id) if x.get("id") == source_id), None)
    if not row: raise HTTPException(status_code=404, detail="源模型不存在")
    p=Path(str(row.get("path") or ""))
    if not p.exists(): raise HTTPException(status_code=404, detail=f"源模型文件不存在：{p}")
    if not row.get("config_path") and row.get("job_id"):
        jf=project_dir(project_id)/"jobs"/str(row.get("job_id"))/"job.json"
        job=read_json(jf,{})
        row["config_path"] = job.get("generated_config_path") or job.get("algorithm_config_path") or ""
    return row


def _deploy_resource_by_id(resource_id: str) -> Dict[str, Any]:
    for r in _builtin_deploy_resources() + _load_saved_deploy_resources():
        if r.get("id") == resource_id: return r
    raise HTTPException(status_code=404, detail="部署资源不存在")


def _deploy_job_dir(project_id: str, job_id: str) -> Path:
    return deploy_root(project_id)/"jobs"/job_id


def _deploy_prepare_calibration(project_id: str, dataset_id: str, split: str, limit: int, dst: Path) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    images=load_images(project_id)
    selected=[]
    for im in images:
        if dataset_id and im.get("dataset_id","default") != dataset_id: continue
        if split and split != "all" and im.get("split","train") != split: continue
        src=project_dir(project_id)/"uploads"/str(im.get("stored_name") or "")
        if src.exists(): selected.append((src, im))
    if limit>0: selected=selected[:limit]
    for i,(src,im) in enumerate(selected):
        shutil.copy2(src,dst/f"{i:05d}_{safe_filename(im.get('original_name') or src.name)}")
    return len(selected)


class DeployJobReq(BaseModel):
    source_id: str
    target: str  # onnx / paddle_inference / tensorrt / sophon / ascend / rockchip
    resource_id: str
    params: Dict[str, Any] = {}
    dataset_id: str = "default"
    calibration_split: str = "train"
    calibration_count: int = 100


def _write_deploy_job(project_id: str, job: Dict[str, Any]):
    jd=_deploy_job_dir(project_id,job["id"]); jd.mkdir(parents=True,exist_ok=True); write_json(jd/"job.json",job)


def _read_deploy_job(project_id: str, job_id: str) -> Dict[str, Any]:
    jf=_deploy_job_dir(project_id,job_id)/"job.json"
    if not jf.exists(): raise HTTPException(status_code=404,detail="转换任务不存在")
    return read_json(jf,{})


def _safe_extract_zip(zf: zipfile.ZipFile, dst: Path) -> None:
    """Extract zip while rejecting path traversal entries."""
    dst = dst.resolve()
    for member in zf.infolist():
        target = (dst / member.filename).resolve()
        try:
            target.relative_to(dst)
        except ValueError:
            raise RuntimeError(f"ZIP 包含非法路径：{member.filename}")
    zf.extractall(dst)


def _sync_remote_deploy_job(project_id: str, job_id: str):
    jd=_deploy_job_dir(project_id,job_id); jf=jd/"job.json"; job=read_json(jf,{})
    resource=job.get("resource") or {}; base=str(resource.get("base_url") or "").rstrip("/"); key=str(resource.get("api_key") or "")
    try:
        source=Path(job["source_path"]); params=job.get("params") or {}
        files={"source_model":(source.name,source.open("rb"),"application/octet-stream")}
        cfg=Path(str(params.get("config_path") or ""))
        cfg_fp=None
        if cfg.exists(): cfg_fp=cfg.open("rb"); files["config_file"]=(cfg.name,cfg_fp,"application/octet-stream")
        cal_dir=Path(job.get("calibration_dir") or "") if job.get("calibration_dir") else None
        cal_zip=None
        if cal_dir and cal_dir.exists():
            cal_zip=jd/"calibration.zip"
            with zipfile.ZipFile(cal_zip,"w",zipfile.ZIP_DEFLATED) as zf:
                for p in cal_dir.rglob("*"):
                    if p.is_file(): zf.write(p,p.relative_to(cal_dir))
            files["calibration_zip"]=(cal_zip.name,cal_zip.open("rb"),"application/zip")
        job.update({"status":"running","stage":"上传到转换服务器","progress":5,"message":"正在上传源模型","updated_at":now_iso()});write_json(jf,job)
        r=requests.post(base+"/api/deploy/convert",headers={"X-API-Key":key},files=files,data={"target":job.get("target"),"params_json":json.dumps(params,ensure_ascii=False)},timeout=600)
        for v in files.values():
            try:v[1].close()
            except:pass
        if not r.ok: raise RuntimeError(f"远程创建任务失败 HTTP {r.status_code}: {r.text[:1000]}")
        rid=r.json().get("job_id"); job["remote_job_id"]=rid; job["stage"]="远程转换中"; job["progress"]=8; write_json(jf,job)
        while True:
            cur=read_json(jf,{})
            if cur.get("cancel_requested"):
                try:requests.post(base+f"/api/deploy/jobs/{rid}/stop",headers={"X-API-Key":key},timeout=10)
                except:pass
                cur.update(status="stopped",stage="已停止",message="用户停止",updated_at=now_iso());write_json(jf,cur);return
            rr=requests.get(base+f"/api/deploy/jobs/{rid}",headers={"X-API-Key":key},timeout=15)
            if not rr.ok: raise RuntimeError(f"同步远程任务失败：{rr.text[:800]}")
            remote=rr.json()
            lr=requests.get(base+f"/api/deploy/jobs/{rid}/log",headers={"X-API-Key":key},timeout=15)
            if lr.ok:(jd/"convert.log").write_text(lr.text,encoding="utf-8",errors="ignore")
            cur=read_json(jf,{})
            cur.update(status=remote.get("status",cur.get("status")),stage=remote.get("stage",cur.get("stage")),progress=remote.get("progress",cur.get("progress",0)),message=remote.get("message",cur.get("message")),error=remote.get("error",""),updated_at=now_iso(),remote_status=remote)
            write_json(jf,cur)
            if remote.get("status") in {"done","failed","stopped"}: break
            time.sleep(2)
        cur=read_json(jf,{})
        if cur.get("status")=="done":
            zr=requests.get(base+f"/api/deploy/jobs/{rid}/artifacts.zip",headers={"X-API-Key":key},timeout=600)
            if not zr.ok: raise RuntimeError("远程转换完成，但部署产物下载失败："+zr.text[:800])
            zp=jd/"remote_artifacts.zip";zp.write_bytes(zr.content);ad=jd/"artifacts";ad.mkdir(exist_ok=True)
            with zipfile.ZipFile(zp,"r") as zf:_safe_extract_zip(zf,ad)
            outputs=[]
            for p in ad.rglob("*"):
                if p.is_file():outputs.append({"name":p.name,"path":str(p),"rel":str(p.relative_to(jd)),"size_mb":round(p.stat().st_size/1024/1024,3)})
            cur.update(outputs=outputs,finished_at=now_iso(),message="远程转换完成，部署产物已拉回平台",progress=100);write_json(jf,cur)
    except Exception as e:
        cur=read_json(jf,job);cur.update(status="failed",stage="转换失败",message=str(e),error=str(e),finished_at=now_iso(),updated_at=now_iso());write_json(jf,cur)
        with (jd/"convert.log").open("a",encoding="utf-8",errors="ignore") as f:f.write(f"\n[{now_iso()}] 远程转换失败：{e}\n")
    finally:
        DEPLOY_REMOTE_THREADS.pop(job_id,None)


@app.post("/api/v39/projects/{project_id}/deploy/jobs")
def v39_create_deploy_job(project_id: str, payload: DeployJobReq):
    source=_resolve_deploy_source(project_id,payload.source_id);resource=_deploy_resource_by_id(payload.resource_id)
    if resource.get("status") != "ready":
        raise HTTPException(status_code=400, detail="当前部署资源不可用，请先到“部署资源”执行检测")
    if payload.target not in (resource.get("targets") or []):
        # Ultralytics/Paddle 内置资源只做直接导出；芯片转换必须选择对应芯片资源。
        raise HTTPException(status_code=400, detail=f"该资源不支持 {payload.target}。当前支持：{', '.join(resource.get('targets') or []) or '无'}")
    job_id=uuid.uuid4().hex[:12];jd=_deploy_job_dir(project_id,job_id);srcd=jd/"source";srcd.mkdir(parents=True,exist_ok=True)
    src=Path(str(source.get("path")));local_src=srcd/src.name;shutil.copy2(src,local_src)
    params=dict(payload.params or {})
    params.setdefault("config_path",source.get("config_path") or "")
    params.setdefault("model_name",src.stem)

    # 芯片 SDK 的 Python 往往和训练/导出 Python 不是同一个环境。
    # 在任务快照里同时保存 Ultralytics/Paddle 导出环境，确保 .pt/.pdparams 能先真实转 ONNX，再进入厂商编译器。
    resource_for_job=dict(resource)
    ultra_env=get_active_ultralytics_env() or {}
    if ultra_env.get("python_path") and not resource_for_job.get("ultralytics_python"):
        resource_for_job["ultralytics_python"]=ultra_env.get("python_path")
    paddle_env=get_active_paddle_env() or {}
    if paddle_env.get("python_path") and not resource_for_job.get("paddle_python"):
        resource_for_job["paddle_python"]=paddle_env.get("python_path")
    if paddle_env.get("paddledet_dir") and not resource_for_job.get("paddledet_dir"):
        resource_for_job["paddledet_dir"]=paddle_env.get("paddledet_dir")
    if paddle_env.get("paddle2onnx_path") and not resource_for_job.get("paddle2onnx_path"):
        resource_for_job["paddle2onnx_path"]=paddle_env.get("paddle2onnx_path")
    cal_dir=None
    if payload.target in {"sophon", "rockchip"} and str(params.get("precision") or "").lower()=="int8":
        cal_dir=jd/"calibration"
        count=_deploy_prepare_calibration(project_id,payload.dataset_id,payload.calibration_split,max(1,int(payload.calibration_count)),cal_dir)
        if count<=0: raise HTTPException(status_code=400,detail="INT8 转换需要校准图片，但当前选择的数据集/分组没有可用图片")
        params["calibration_count"]=count
    job={"id":job_id,"project_id":project_id,"source_id":payload.source_id,"source_name":src.name,"source_path":str(local_src),"source_meta":source,"target":payload.target,"resource_id":payload.resource_id,"resource":resource_for_job,"params":params,"dataset_id":payload.dataset_id,"calibration_split":payload.calibration_split,"calibration_dir":str(cal_dir) if cal_dir else "","status":"queued","stage":"等待启动","progress":0,"message":"等待启动","created_at":now_iso(),"updated_at":now_iso(),"outputs":[]}
    _write_deploy_job(project_id,job)
    if str(resource.get("mode"))=="remote":
        th=threading.Thread(target=_sync_remote_deploy_job,args=(project_id,job_id),daemon=True);DEPLOY_REMOTE_THREADS[job_id]=th;th.start()
    else:
        log=(jd/"worker.stdout.log").open("ab")
        proc=subprocess.Popen([sys.executable,str(BASE_DIR/"deployment_worker.py"),"--job-dir",str(jd)],cwd=str(BASE_DIR),stdout=log,stderr=subprocess.STDOUT,env={**os.environ.copy(),"PYTHONUTF8":"1","PYTHONIOENCODING":"utf-8"})
        DEPLOY_PROCESS_REGISTRY[job_id]=proc
    return {"ok":True,"job":job}


@app.get("/api/v39/projects/{project_id}/deploy/jobs")
def v39_list_deploy_jobs(project_id: str):
    root=deploy_root(project_id)/"jobs";rows=[]
    for jf in root.glob("*/job.json"):
        j=read_json(jf,{})
        if j:rows.append(j)
    rows.sort(key=lambda x:x.get("created_at",""),reverse=True)
    return {"ok":True,"items":rows[:100]}


@app.get("/api/v39/projects/{project_id}/deploy/jobs/{job_id}")
def v39_get_deploy_job(project_id: str, job_id: str):
    return _read_deploy_job(project_id,job_id)


@app.get("/api/v39/projects/{project_id}/deploy/jobs/{job_id}/log", response_class=PlainTextResponse)
def v39_deploy_job_log(project_id: str, job_id: str):
    jd=_deploy_job_dir(project_id,job_id)
    for p in [jd/"convert.log",jd/"worker.stdout.log"]:
        if p.exists():return p.read_text(encoding="utf-8",errors="ignore")[-160000:]
    return "暂无转换日志"


@app.post("/api/v39/projects/{project_id}/deploy/jobs/{job_id}/stop")
def v39_stop_deploy_job(project_id: str, job_id: str):
    job=_read_deploy_job(project_id,job_id);job["cancel_requested"]=True
    proc=DEPLOY_PROCESS_REGISTRY.get(job_id)
    if proc and proc.poll() is None:
        try:proc.terminate();time.sleep(.5)
        except:pass
        if proc.poll() is None:
            try:proc.kill()
            except:pass
        DEPLOY_PROCESS_REGISTRY.pop(job_id,None)
        job.update(status="stopped",stage="已停止",message="用户停止",updated_at=now_iso())
    _write_deploy_job(project_id,job)
    return {"ok":True}


@app.delete("/api/v39/projects/{project_id}/deploy/jobs/{job_id}")
def v39_delete_deploy_job(project_id: str, job_id: str):
    job=_read_deploy_job(project_id,job_id)
    if job.get("status") in {"running","queued"}:raise HTTPException(status_code=400,detail="运行中的任务请先停止")
    shutil.rmtree(_deploy_job_dir(project_id,job_id),ignore_errors=True)
    return {"ok":True}


@app.get("/api/v39/projects/{project_id}/deploy/artifacts")
def v39_list_deploy_artifacts(project_id: str):
    rows=[]
    for j in v39_list_deploy_jobs(project_id)["items"]:
        if j.get("status")!="done":continue
        for o in j.get("outputs",[]) or []:
            p=Path(str(o.get("path") or ""))
            if not p.exists():continue
            ext=p.suffix.lower().lstrip('.')
            if ext not in {"onnx","engine","bmodel","om","rknn","pdmodel","pdiparams","json","yml","yaml"}:continue
            rows.append({**o,"job_id":j.get("id"),"target":j.get("target"),"resource_name":j.get("resource",{}).get("name"),"source_name":j.get("source_name"),"params":j.get("params",{}),"created_at":j.get("finished_at") or j.get("created_at"),"download_url":f"/api/v39/projects/{project_id}/deploy/jobs/{j.get('id')}/artifact?rel={requests.utils.quote(str(o.get('rel') or ''))}"})
    return {"ok":True,"items":rows}


@app.get("/api/v39/projects/{project_id}/deploy/jobs/{job_id}/artifact")
def v39_download_deploy_artifact(project_id: str, job_id: str, rel: str):
    _read_deploy_job(project_id,job_id)
    jd=_deploy_job_dir(project_id,job_id).resolve();p=(jd/rel).resolve()
    if jd not in p.parents and p!=jd:raise HTTPException(status_code=400,detail="非法文件路径")
    if not p.exists() or not p.is_file():raise HTTPException(status_code=404,detail="部署产物不存在")
    return FileResponse(p,filename=p.name)


@app.get("/api/v39/projects/{project_id}/deploy/jobs/{job_id}/package")
def v39_download_deploy_package(project_id: str, job_id: str):
    job=_read_deploy_job(project_id,job_id);jd=_deploy_job_dir(project_id,job_id);ad=jd/"artifacts"
    if job.get("status")!="done" or not ad.exists():raise HTTPException(status_code=400,detail="当前任务还没有可下载部署产物")
    package=jd/f"deploy_{job_id}.zip"
    with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED) as zf:
        for p in ad.rglob("*"):
            if p.is_file():zf.write(p,Path("model")/p.relative_to(ad))
        for extra,name in [(jd/"job.json","conversion_job.json"),(jd/"convert.log","conversion.log")]:
            if extra.exists():zf.write(extra,name)
    return FileResponse(package,filename=f"{safe_filename(job.get('source_name') or 'model')}_{job.get('target')}_deploy.zip")


# ============================================================
# v40: 组件检测中心
# - 真正检查 Python 包、训练框架、导出工具、芯片编译器与远程转换资源
# - 检测任务后台执行，前端显示真实进度
# ============================================================
COMPONENT_SCAN_DIR = DATA_DIR / "component_scans"
COMPONENT_SCAN_DIR.mkdir(parents=True, exist_ok=True)
COMPONENT_SCAN_THREADS: Dict[str, threading.Thread] = {}


def _v40_component_item(key: str, name: str, status: str, required: bool, version: str = "", path: str = "", detail: str = "", fix: str = "") -> Dict[str, Any]:
    return {"key": key, "name": name, "status": status, "required": required, "version": version, "path": path, "detail": detail, "fix": fix}


def _v40_python_module(py: str, module: str, required: bool = True, dist_name: str = "") -> Dict[str, Any]:
    py = str(py or sys.executable)
    if not Path(py).exists():
        return _v40_component_item(module, module, "missing", required, path=py, detail="Python 路径不存在", fix="配置正确的 Python 环境")
    code=("import importlib,json; m=importlib.import_module(%r); "
          "print(json.dumps({'version':getattr(m,'__version__',''),'path':getattr(m,'__file__','')},ensure_ascii=False))") % module
    try:
        cp=subprocess.run([py,"-c",code],capture_output=True,text=True,encoding="utf-8",errors="ignore",timeout=18)
        if cp.returncode==0:
            data=json.loads((cp.stdout or "{}").splitlines()[-1])
            return _v40_component_item(module, dist_name or module, "ready", required, version=str(data.get("version") or ""), path=str(data.get("path") or ""))
        return _v40_component_item(module, dist_name or module, "missing", required, detail=(cp.stderr or cp.stdout or "导入失败")[-800:], fix=f"在对应环境安装 {dist_name or module}")
    except Exception as e:
        return _v40_component_item(module, dist_name or module, "missing", required, detail=str(e), fix=f"检查 {dist_name or module} 安装")


def _v40_file_check(key: str, name: str, path: str, required: bool=True, fix: str="") -> Dict[str, Any]:
    p=Path(str(path or "")) if path else None
    ok=bool(p and p.exists())
    return _v40_component_item(key,name,"ready" if ok else "missing",required,path=str(p or ""),detail="已找到" if ok else "未找到",fix=fix if not ok else "")


def _v40_capability(name: str, keys: List[str], components: List[Dict[str, Any]], optional_keys: Optional[List[str]]=None) -> Dict[str, Any]:
    optional_keys=set(optional_keys or [])
    mp={x.get("key"):x for x in components}
    required=[mp[k] for k in keys if k in mp and k not in optional_keys]
    optional=[mp[k] for k in keys if k in mp and k in optional_keys]
    if required and all(x.get("status")=="ready" for x in required):
        status="ready"
    elif any(x.get("status")=="ready" for x in required):
        status="warning"
    else:
        status="missing"
    return {"name":name,"status":status,"required":keys,"optional":list(optional_keys),"ready":sum(1 for x in required+optional if x.get("status")=="ready"),"total":len(required)+len(optional)}


def _v40_scan_write(scan_id: str, data: Dict[str, Any]):
    write_json(COMPONENT_SCAN_DIR / f"{scan_id}.json", data)
    if data.get("status")=="done":
        write_json(COMPONENT_SCAN_DIR / "latest.json", data)


def _v40_run_component_scan(scan_id: str):
    jf=COMPONENT_SCAN_DIR/f"{scan_id}.json"
    scan=read_json(jf,{})
    components=[]
    def update(progress:int,stage:str):
        scan.update(status="running",progress=progress,stage=stage,updated_at=now_iso(),components=components)
        _v40_scan_write(scan_id,scan)
    try:
        update(4,"检查平台运行环境")
        pyver=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        components.append(_v40_component_item("python","Python >= 3.10","ready" if sys.version_info >= (3,10) else "missing",True,version=pyver,path=sys.executable,fix="安装 Python 3.10 或更高版本"))
        for mod,label in [("fastapi","FastAPI"),("uvicorn","Uvicorn"),("requests","Requests"),("yaml","PyYAML"),("PIL","Pillow")]:
            components.append(_v40_python_module(sys.executable,mod,True,label))
        update(14,"检查数据与视频组件")
        components.append(_v40_python_module(sys.executable,"cv2",True,"OpenCV"))

        update(25,"检查 Ultralytics 训练与 ONNX 导出")
        ultra=get_active_ultralytics_env() or {}
        upy=str(ultra.get("python_path") or "")
        if upy:
            u=_deploy_ultra_info(upy)
            components.append(_v40_component_item("ultralytics","Ultralytics","ready" if u.get("ok") else "missing",False,version=str(u.get("version") or ""),path=upy,detail=str(u.get("error") or ""),fix="到训练资源配置可用的 Ultralytics Python" if not u.get("ok") else ""))
            components.append(_v40_python_module(upy,"onnx",False,"ONNX"))
            components.append(_v40_python_module(upy,"onnxruntime",False,"ONNX Runtime"))
        else:
            components += [_v40_component_item("ultralytics","Ultralytics","missing",False,detail="未启用训练资源",fix="到训练资源检测并启用 Ultralytics"),_v40_component_item("onnx","ONNX","missing",False,fix="在 Ultralytics 环境安装 onnx"),_v40_component_item("onnxruntime","ONNX Runtime","missing",False,fix="在 Ultralytics 环境安装 onnxruntime")]

        update(40,"检查飞桨训练与推理导出")
        penv=get_active_paddle_env() or {}
        ppy=str(penv.get("python_path") or "")
        pdd=str(penv.get("paddledet_dir") or "")
        if ppy:
            pi=_deploy_paddle_info(ppy)
            components.append(_v40_component_item("paddle","PaddlePaddle","ready" if pi.get("ok") else "missing",False,version=str(pi.get("version") or ""),path=ppy,detail=str(pi.get("error") or ""),fix="到训练资源配置 Paddle 环境" if not pi.get("ok") else ""))
        else:
            components.append(_v40_component_item("paddle","PaddlePaddle","missing",False,detail="未启用飞桨环境",fix="到训练资源配置 Paddle 环境"))
        train_py=str(Path(pdd)/"tools"/"train.py") if pdd else ""
        export_py=str(Path(pdd)/"tools"/"export_model.py") if pdd else ""
        components.append(_v40_file_check("paddledet_train","PaddleDetection train.py",train_py,False,"配置完整 PaddleDetection 源码目录"))
        components.append(_v40_file_check("paddledet_export","PaddleDetection export_model.py",export_py,False,"配置完整 PaddleDetection 源码目录"))
        p2o=_deploy_which(str(Path(ppy).parent/"paddle2onnx.exe") if ppy else "","paddle2onnx")
        components.append(_v40_component_item("paddle2onnx","paddle2onnx","ready" if p2o else "missing",False,path=p2o,detail="跨硬件部署时用于 Paddle → ONNX" if p2o else "未检测到",fix="需要把飞桨模型转 ONNX 时安装 paddle2onnx" if not p2o else ""))

        update(58,"检查本机芯片编译器")
        saved=_load_saved_deploy_resources()
        checked=[]
        for r in saved:
            if str(r.get("mode"))=="remote":
                continue
            try:
                cr=_detect_local_deploy_resource(r)
            except Exception as e:
                cr={**r,"status":"missing","message":str(e),"targets":[]}
            checked.append(cr)
        # Also discover common commands even when the user has not created resource cards yet.
        trt=_deploy_which("trtexec")
        transform=_deploy_which("model_transform.py","model_transform")
        deploy=_deploy_which("model_deploy.py","model_deploy")
        cali=_deploy_which("run_calibration.py","run_calibration")
        atc=_deploy_which("atc","atc.bin")
        nsmi=_deploy_which("npu-smi")
        for r in checked:
            if r.get("kind")=="tensorrt" and r.get("trtexec_path"):trt=r.get("trtexec_path")
            if r.get("kind")=="sophon":
                transform=r.get("model_transform_path") or transform;deploy=r.get("model_deploy_path") or deploy;cali=r.get("run_calibration_path") or cali
            if r.get("kind")=="ascend":
                atc=r.get("atc_path") or atc;nsmi=r.get("npu_smi_path") or nsmi
        components.append(_v40_component_item("trtexec","TensorRT trtexec","ready" if trt else "missing",False,version=_deploy_cmd_version(str(trt or "")),path=str(trt or ""),fix="在 NVIDIA 部署机安装 TensorRT" if not trt else ""))
        components.append(_v40_component_item("tpu_transform","TPU-MLIR model_transform","ready" if transform else "missing",False,path=str(transform or ""),fix="在算能转换机安装并 source TPU-MLIR 环境" if not transform else ""))
        components.append(_v40_component_item("tpu_deploy","TPU-MLIR model_deploy","ready" if deploy else "missing",False,version=_deploy_cmd_version(str(deploy or "")),path=str(deploy or ""),fix="配置 TPU-MLIR" if not deploy else ""))
        components.append(_v40_component_item("tpu_calibration","TPU-MLIR run_calibration","ready" if cali else "missing",False,path=str(cali or ""),detail="INT8 量化需要" if cali else "INT8 BMODEL 需要该组件",fix="配置 TPU-MLIR calibration 工具" if not cali else ""))
        components.append(_v40_component_item("atc","CANN ATC","ready" if atc else "missing",False,version=_deploy_cmd_version(str(atc or "")),path=str(atc or ""),detail="Atlas/Ascend OM 编译器",fix="在华为转换机安装 CANN Toolkit 或配置 ATC 路径" if not atc else ""))
        npu_text="";socs=[]
        if nsmi:
            try:
                cp=subprocess.run([nsmi,"info"],capture_output=True,text=True,encoding="utf-8",errors="ignore",timeout=10)
                npu_text=(cp.stdout or cp.stderr or "")[-5000:]
                for m in re.findall(r"Ascend\\s*([0-9]{3,4}[A-Za-z0-9_-]*)",npu_text,re.I):
                    v="Ascend"+m.replace(" ","")
                    if v not in socs:socs.append(v)
            except Exception:pass
        components.append(_v40_component_item("npu_smi","npu-smi","ready" if nsmi else "warning",False,path=str(nsmi or ""),detail=("检测到："+"、".join(socs)) if socs else ("已安装，可查询 Atlas 芯片" if nsmi else "仅转换 OM 时不是必需；连接真实 Atlas 时用于读取 Chip Name"),fix="连接 Atlas 硬件验证时安装驱动/npu-smi" if not nsmi else ""))

        update(76,"检查远程部署资源")
        remote_rows=[]
        for r in saved:
            if str(r.get("mode"))!="remote":continue
            try: cr=_detect_remote_deploy_resource(r)
            except Exception as e: cr={**r,"status":"missing","message":str(e),"targets":[]}
            remote_rows.append(cr)
            components.append(_v40_component_item("remote_"+str(r.get("id")),"远程部署 · "+str(r.get("name") or r.get("id")),"ready" if cr.get("status")=="ready" else "missing",False,version=str(cr.get("version") or ""),path=str(cr.get("base_url") or ""),detail=str(cr.get("message") or ""),fix="检查远程转换服务与网络/API Key" if cr.get("status")!="ready" else ""))

        update(90,"汇总可用能力")
        capabilities=[]
        capabilities.append(_v40_capability("平台基础运行",["python","fastapi","uvicorn","requests","yaml","PIL","cv2"],components))
        capabilities.append(_v40_capability("Ultralytics 训练",["ultralytics"],components))
        capabilities.append(_v40_capability("Ultralytics → ONNX",["ultralytics","onnx"],components,optional_keys=["onnxruntime"]))
        capabilities.append(_v40_capability("PaddleDetection 训练",["paddle","paddledet_train"],components))
        capabilities.append(_v40_capability("Paddle → Inference",["paddle","paddledet_export"],components))
        capabilities.append(_v40_capability("Paddle → ONNX",["paddle","paddledet_export","paddle2onnx"],components))
        capabilities.append(_v40_capability("算能 BMODEL (F16/BF16/F32)",["tpu_transform","tpu_deploy"],components))
        capabilities.append(_v40_capability("算能 BMODEL (INT8)",["tpu_transform","tpu_deploy","tpu_calibration"],components))
        capabilities.append(_v40_capability("华为 Atlas / Ascend OM",["atc"],components,optional_keys=["npu_smi"]))
        capabilities.append(_v40_capability("NVIDIA TensorRT",["trtexec"],components))
        # Remote resource capabilities can make a target usable even when the platform host lacks local compilers.
        remote_targets=[]
        for r in remote_rows:
            if r.get("status")=="ready":remote_targets += list(r.get("targets") or [])
        for cap in capabilities:
            if cap["name"].startswith("华为") and "ascend" in remote_targets:cap.update(status="ready",remote=True)
            if cap["name"].startswith("算能") and "sophon" in remote_targets:cap.update(status="ready",remote=True)
            if cap["name"].startswith("NVIDIA") and "tensorrt" in remote_targets:cap.update(status="ready",remote=True)
        ready=sum(1 for x in components if x.get("status")=="ready")
        missing=sum(1 for x in components if x.get("status")=="missing")
        warning=sum(1 for x in components if x.get("status")=="warning")
        scan.update(status="done",progress=100,stage="检测完成",updated_at=now_iso(),finished_at=now_iso(),components=components,capabilities=capabilities,summary={"ready":ready,"warning":warning,"missing":missing,"total":len(components)},atlas={"atc_ready":bool(atc),"npu_smi_ready":bool(nsmi),"detected_soc_versions":socs,"note":"OM 转换不要求转换机安装 Atlas NPU，但 --soc_version 必须与最终部署芯片一致"})
        _v40_scan_write(scan_id,scan)
    except Exception as e:
        scan.update(status="failed",stage="检测失败",error=str(e),message=str(e),updated_at=now_iso(),components=components)
        _v40_scan_write(scan_id,scan)
    finally:
        COMPONENT_SCAN_THREADS.pop(scan_id,None)


@app.post("/api/v40/system/components/scan")
def v40_start_component_scan():
    scan_id=uuid.uuid4().hex[:12]
    data={"id":scan_id,"status":"queued","progress":0,"stage":"等待检测","created_at":now_iso(),"updated_at":now_iso(),"components":[],"capabilities":[]}
    _v40_scan_write(scan_id,data)
    th=threading.Thread(target=_v40_run_component_scan,args=(scan_id,),daemon=True)
    COMPONENT_SCAN_THREADS[scan_id]=th;th.start()
    return data


@app.get("/api/v40/system/components/scan/{scan_id}")
def v40_get_component_scan(scan_id: str):
    p=COMPONENT_SCAN_DIR/f"{scan_id}.json"
    if not p.exists():raise HTTPException(status_code=404,detail="检测任务不存在")
    return read_json(p,{})


@app.get("/api/v40/system/components/latest")
def v40_latest_component_scan():
    p=COMPONENT_SCAN_DIR/"latest.json"
    return read_json(p,{"status":"never","progress":0,"components":[],"capabilities":[],"summary":{"ready":0,"warning":0,"missing":0,"total":0}})

# ============================================================
# v41: 部署插件框架 + 瑞芯微 RKNN-Toolkit2
# ============================================================
from deploy_plugins import plugin_catalog as _v41_plugin_catalog


def _v41_rknn_info(py: str) -> Dict[str, Any]:
    py=str(py or '')
    if not py or not Path(py).exists():
        return {'ok':False,'error':'Python 不存在'}
    code="from rknn.api import RKNN; import importlib.metadata as m,json; print(json.dumps({'version':m.version('rknn-toolkit2')},ensure_ascii=False))"
    try:
        cp=subprocess.run([py,'-c',code],capture_output=True,text=True,encoding='utf-8',errors='ignore',timeout=20)
        if cp.returncode!=0:return {'ok':False,'error':(cp.stderr or cp.stdout or 'RKNN-Toolkit2 导入失败')[-1200:]}
        return {'ok':True,**json.loads((cp.stdout or '{}').splitlines()[-1])}
    except Exception as e:return {'ok':False,'error':str(e)}

_v41_old_detect_local_deploy_resource = _detect_local_deploy_resource

def _detect_local_deploy_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    if str(item.get('kind') or '').lower()!='rockchip':
        return _v41_old_detect_local_deploy_resource(item)
    row=dict(item); row['last_checked_at']=now_iso(); row['targets']=[]
    py=str(row.get('python_path') or sys.executable)
    info=_v41_rknn_info(py)
    row['rknn_python']=py
    row['rknn_version']=str(info.get('version') or '')
    row['supported_chips']=['rk3588','rk3576','rk3566','rk3568','rk3562','rv1103','rv1106','rv1103b','rv1106b','rv1126b','rk2118']
    if info.get('ok'):
        row.update(status='ready',targets=['rockchip'],version=row['rknn_version'],message='RKNN-Toolkit2 可用；无需开发板即可把 ONNX 转为 RKNN')
    else:
        row.update(status='missing',message='未检测到 RKNN-Toolkit2：'+str(info.get('error') or ''))
    return row


@app.get('/api/v41/deploy/plugins')
def v41_deploy_plugins():
    saved=_load_saved_deploy_resources(); builtin=_builtin_deploy_resources(); resources=builtin+saved
    rows=[]
    for p in _v41_plugin_catalog():
        matches=[r for r in resources if str(r.get('kind'))==p['id'] or (p['id']=='onnx' and str(r.get('kind')) in {'ultralytics','paddle'})]
        ready=[]
        for r in matches:
            try:
                chk=_detect_remote_deploy_resource(r) if str(r.get('mode'))=='remote' else _detect_local_deploy_resource(r)
            except Exception:chk=r
            if p['id'] in (chk.get('targets') or []) or (p['id']=='onnx' and 'onnx' in (chk.get('targets') or [])):ready.append(chk)
        p['status']='ready' if ready else 'missing'; p['resources']=ready; p['configured_count']=len(matches)
        rows.append(p)
    return {'ok':True,'items':rows,'version':APP_VERSION,'host_os':'windows' if os.name=='nt' else 'linux'}


class V41SdkInstallReq(BaseModel):
    resource_id: str
    wheel_path: str


@app.post('/api/v41/deploy/plugins/rockchip/install-sdk')
def v41_install_rockchip_sdk(payload: V41SdkInstallReq):
    item=next((x for x in _load_saved_deploy_resources() if x.get('id')==payload.resource_id),None)
    if not item or str(item.get('kind'))!='rockchip':
        raise HTTPException(status_code=404,detail='请先新增一个瑞芯微本机部署资源')
    if str(item.get('mode'))!='local':
        raise HTTPException(status_code=400,detail='远程资源请在远程转换节点安装 RKNN-Toolkit2')
    if os.name == 'nt':
        raise HTTPException(status_code=400,detail='RKNN-Toolkit2 官方转换工具链使用 Linux wheel，Windows 本机不要直接安装。请在 WSL2/Linux 转换节点安装 RKNN-Toolkit2，并在“部署资源”新增远程资源。')
    py=str(item.get('python_path') or '')
    if not py:
        raise HTTPException(status_code=400,detail='RKNN-Toolkit2 必须使用独立 Python 环境，不能和平台训练环境混装。请先创建独立 venv/conda，并把 Python 路径填到瑞芯微部署资源。')
    try:
        if Path(py).resolve() == Path(sys.executable).resolve():
            raise HTTPException(status_code=400,detail='RKNN-Toolkit2 官方依赖对 Torch/ONNX 有独立版本约束，禁止安装到平台主 Python。请为 RKNN 单独创建 venv/conda 后填写其 Python 路径。')
    except HTTPException:
        raise
    except Exception:
        pass
    wheel=Path(payload.wheel_path.strip())
    if not wheel.exists() or wheel.suffix.lower()!='.whl':
        raise HTTPException(status_code=400,detail='请选择已下载的官方 RKNN-Toolkit2 .whl 文件')
    try:
        cp=subprocess.run([py,'-m','pip','install',str(wheel)],capture_output=True,text=True,encoding='utf-8',errors='ignore',timeout=900)
    except Exception as e:
        raise HTTPException(status_code=500,detail=f'安装执行失败：{e}')
    if cp.returncode!=0:
        raise HTTPException(status_code=500,detail='RKNN-Toolkit2 安装失败：'+(cp.stderr or cp.stdout or '')[-3000:])
    checked=_detect_local_deploy_resource(item)
    items=_load_saved_deploy_resources()
    for i,x in enumerate(items):
        if x.get('id')==item.get('id'):items[i]=checked
    _save_deploy_resources(items)
    return {'ok':True,'resource':checked,'log':(cp.stdout or '')[-3000:]}


_v41_old_component_scan = _v40_run_component_scan

def _v40_run_component_scan(scan_id: str):
    _v41_old_component_scan(scan_id)
    jf=COMPONENT_SCAN_DIR/f'{scan_id}.json'; scan=read_json(jf,{})
    if scan.get('status')!='done':return
    comps=list(scan.get('components') or []); caps=list(scan.get('capabilities') or [])
    saved=_load_saved_deploy_resources(); local=[r for r in saved if r.get('kind')=='rockchip' and r.get('mode')!='remote']; remote=[r for r in saved if r.get('kind')=='rockchip' and r.get('mode')=='remote']
    ready=False; version=''; detail='未配置 RKNN-Toolkit2 转换资源'
    for r in local:
        chk=_detect_local_deploy_resource(r)
        if chk.get('status')=='ready':ready=True;version=chk.get('version','');detail='本机 RKNN-Toolkit2 可生成 .rknn';break
    if not ready:
        for r in remote:
            chk=_detect_remote_deploy_resource(r)
            if chk.get('status')=='ready' and 'rockchip' in (chk.get('targets') or []):ready=True;version=chk.get('version','');detail='远程 RKNN 转换节点可用';break
    comps.append(_v40_component_item('rknn_toolkit2','RKNN-Toolkit2','ready' if ready else 'missing',False,version=version,detail=detail,fix='配置 Linux 转换节点或为瑞芯微部署资源指定安装了 RKNN-Toolkit2 的 Python 环境' if not ready else ''))
    caps.append({'name':'瑞芯微 RKNN','status':'ready' if ready else 'missing','required':['rknn_toolkit2'],'optional':[],'ready':1 if ready else 0,'total':1,'remote':bool(ready and remote and not local)})
    ready_n=sum(1 for x in comps if x.get('status')=='ready');missing=sum(1 for x in comps if x.get('status')=='missing');warning=sum(1 for x in comps if x.get('status')=='warning')
    scan.update(components=comps,capabilities=caps,summary={'ready':ready_n,'warning':warning,'missing':missing,'total':len(comps)},updated_at=now_iso())
    _v40_scan_write(scan_id,scan)


@app.get('/api/v41/system/deploy-matrix')
def v41_deploy_matrix():
    return {'ok':True,'plugins':_v41_plugin_catalog(),'rule':'源模型 → 通用中间模型 → 厂商插件编译 → 芯片模型；Runtime/Lite2/AscendCL/BMRuntime 属于运行阶段，不是第二次模型转换。'}

# ============================================================
# v42: 算法持续迭代闭环
# - 素材源：目录 / RTSP(含视频URL) / 通用HTTP JSON
# - 自动迭代策略：数据门槛 + 模型指标门槛 + 自动补样 + 自动标注 + 自动重训
# - 所有任务均使用真实数据/真实训练结果；缺少外部源或标注模型时明确停在待处理阶段
# ============================================================
V42_INDUSTRY_TEMPLATES = [
    {"id":"helmet","industry":"工地 / 工业","name":"未佩戴安全帽检测","labels":["person","helmet"],"focus":"人员头部、小目标、遮挡、逆光、远距离","negative":"正确佩戴、帽子/雨伞等相似物、背影","recommended_model":"yolo11s.pt"},
    {"id":"fire_smoke","industry":"消防 / 安防","name":"明火烟雾检测","labels":["fire","smoke"],"focus":"小火苗、早期烟雾、夜间、反光、雾气","negative":"灯光、红色物体、蒸汽、云雾","recommended_model":"yolo11s.pt"},
    {"id":"waterlogging","industry":"防汛 / 城市治理","name":"积水内涝检测","labels":["waterlogging"],"focus":"路面反光、不同水深、夜间、雨天","negative":"正常湿地、阴影、玻璃反射","recommended_model":"yolo11m.pt"},
    {"id":"falling","industry":"养老 / 监所 / 安防","name":"人员倒地检测素材模型","labels":["person_down"],"focus":"侧躺、趴卧、遮挡、不同机位","negative":"坐地、弯腰、床上正常躺卧","recommended_model":"yolo11s.pt"},
    {"id":"intrusion","industry":"园区 / 电力 / 仓储","name":"重点区域人员入侵检测","labels":["person"],"focus":"远距离、小目标、夜间、雨雪、遮挡","negative":"区域外人员、海报人像、屏幕人像","recommended_model":"yolo11s.pt"},
    {"id":"custom","industry":"自定义行业","name":"自定义行业算法","labels":[],"focus":"由业务场景定义","negative":"必须补充容易误报的反例","recommended_model":"yolo11s.pt"},
]


def _v42_file(project_id: str, name: str) -> Path:
    d = project_dir(project_id) / "v42"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.json"


def _v42_list(project_id: str, name: str) -> List[Dict[str, Any]]:
    return read_json(_v42_file(project_id, name), [])


def _v42_save(project_id: str, name: str, rows: List[Dict[str, Any]]) -> None:
    write_json(_v42_file(project_id, name), rows)


def _v42_get(project_id: str, name: str, item_id: str) -> Optional[Dict[str, Any]]:
    return next((x for x in _v42_list(project_id, name) if x.get("id") == item_id), None)


class V42AlgorithmBlueprintReq(BaseModel):
    name: str
    remark: Optional[str] = ""
    industry: Optional[str] = ""
    algorithm_type: Optional[str] = "yolo_ultralytics"
    template_id: Optional[str] = "custom"
    labels: List[str] = []
    focus_scenes: Optional[str] = ""
    negative_scenes: Optional[str] = ""


@app.get('/api/v42/industry-templates')
def v42_industry_templates():
    return {"ok": True, "items": V42_INDUSTRY_TEMPLATES}


@app.get('/api/v42/projects/{project_id}/algorithm-blueprints')
def v42_list_algorithm_blueprints(project_id: str):
    get_project(project_id)
    return {"ok": True, "items": _v42_list(project_id, 'algorithm_blueprints')}


@app.post('/api/v42/projects/{project_id}/algorithm-blueprints')
def v42_create_algorithm_blueprint(project_id: str, payload: V42AlgorithmBlueprintReq):
    get_project(project_id)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail='算法名称不能为空')
    alg = v12_create_algorithm(project_id, AlgorithmReq(
        name=payload.name.strip(), remark=payload.remark or '', industry=payload.industry or '',
        algorithm_type=payload.algorithm_type or 'yolo_ultralytics'
    ))
    project = get_project(project_id)
    for raw in payload.labels or []:
        code = normalize_label(raw)
        if code:
            ensure_label(project, code)
            project = get_project(project_id)
    blueprints = _v42_list(project_id, 'algorithm_blueprints')
    item = {
        "id": uuid.uuid4().hex[:12], "algorithm_id": alg.get("id"), "name": payload.name.strip(),
        "industry": payload.industry or '', "algorithm_type": payload.algorithm_type or 'yolo_ultralytics',
        "template_id": payload.template_id or 'custom',
        "labels": [normalize_label(x) for x in payload.labels if normalize_label(x)],
        "focus_scenes": payload.focus_scenes or '', "negative_scenes": payload.negative_scenes or '',
        "created_at": now_iso(), "updated_at": now_iso()
    }
    blueprints.insert(0, item); _v42_save(project_id, 'algorithm_blueprints', blueprints[:200])
    return {"ok": True, "algorithm": alg, "blueprint": item, "labels": get_project(project_id).get('labels', [])}


V423_DEPLOY_TARGET_NAMES = {
    "onnx": "ONNX 通用模型",
    "paddle_inference": "Paddle Inference",
    "tensorrt": "NVIDIA TensorRT",
    "sophon": "算能 Sophon / BModel",
    "ascend": "华为 Atlas / Ascend OM",
    "rockchip": "瑞芯微 RKNN",
}

@app.get('/api/v42/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/deployments')
def v423_version_deployments(project_id: str, algorithm_id: str, version_id: str):
    get_project(project_id)
    algo = next((a for a in list_algorithms_internal(project_id) if a.get('id') == algorithm_id), None)
    if not algo:
        raise HTTPException(status_code=404, detail='算法不存在')
    version = next((v for v in (algo.get('versions') or []) if v.get('id') == version_id), None)
    if not version:
        raise HTTPException(status_code=404, detail='算法版本不存在')
    rows = []
    for job in v39_list_deploy_jobs(project_id).get('items', []):
        source = job.get('source_meta') or {}
        exact = (source.get('algorithm_id') == algorithm_id and source.get('version_id') == version_id)
        exact = exact or job.get('source_id') == f'version::{algorithm_id}::{version_id}'
        if not exact:
            continue
        outputs = []
        for out in job.get('outputs') or []:
            pp = Path(str(out.get('path') or ''))
            outputs.append({
                'name': out.get('name') or pp.name, 'size_mb': out.get('size_mb'), 'rel': out.get('rel'),
                'exists': bool(pp.exists()),
                'download_url': f"/api/v39/projects/{project_id}/deploy/jobs/{job.get('id')}/artifact?rel={requests.utils.quote(str(out.get('rel') or ''))}" if out.get('rel') else ''
            })
        target = str(job.get('target') or '')
        rows.append({
            'id': job.get('id'), 'target': target, 'target_name': V423_DEPLOY_TARGET_NAMES.get(target, target or '-'),
            'status': job.get('status'), 'stage': job.get('stage'), 'progress': job.get('progress'),
            'resource_name': (job.get('resource') or {}).get('name') or '', 'params': job.get('params') or {},
            'outputs': outputs, 'created_at': job.get('created_at'), 'finished_at': job.get('finished_at'),
            'message': job.get('message') or '', 'error': job.get('error') or ''
        })
    rows.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    return {'ok': True, 'algorithm': {'id': algo.get('id'), 'name': algo.get('name')}, 'version': version, 'items': rows}


class V42SourceReq(BaseModel):
    name: str
    type: str = 'folder'  # folder / rtsp / http_json
    source: str
    headers_json: Optional[str] = ''
    items_path: Optional[str] = 'items'
    image_url_field: Optional[str] = 'image_url'
    enabled: bool = True
    collect_mode: str = 'manual'  # manual / auto
    schedule_type: str = 'interval'  # interval / daily
    schedule_value: str = '60'  # minutes for interval; HH:MM for daily
    dataset_id: str = 'default'
    max_items: int = 50
    interval_seconds: float = 2.0
    remark: Optional[str] = ''


class V42CollectReq(BaseModel):
    dataset_id: str = 'default'
    max_items: int = 50
    interval_seconds: float = 2.0


def _v42_source_last_run(project_id: str, source_id: str) -> Optional[Dict[str, Any]]:
    runs=[r for r in _v42_list(project_id,'collection_runs') if r.get('source_id')==source_id]
    if not runs:return None
    runs.sort(key=lambda x:str(x.get('created_at') or ''),reverse=True)
    return runs[0]

def _v42_source_next_run(item: Dict[str, Any], last_run: Optional[Dict[str, Any]]=None, now: Optional[datetime]=None) -> Optional[str]:
    if not item.get('enabled', True) or item.get('collect_mode','manual')!='auto':return None
    now=now or datetime.now(); typ=item.get('schedule_type') or 'interval'; raw=str(item.get('schedule_value') or '60').strip()
    if typ=='daily':
        try:
            hh,mm=[int(x) for x in raw.split(':',1)]
            hh=max(0,min(23,hh));mm=max(0,min(59,mm))
        except Exception:
            hh,mm=2,0
        candidate=now.replace(hour=hh,minute=mm,second=0,microsecond=0)
        if candidate<=now:
            from datetime import timedelta
            candidate+=timedelta(days=1)
        return candidate.strftime('%Y-%m-%d %H:%M:%S')
    try: minutes=max(1,int(float(raw)))
    except Exception: minutes=60
    from datetime import timedelta
    base=_parse_dt_value((last_run or {}).get('finished_at') or (last_run or {}).get('created_at') or item.get('created_at')) or now
    candidate=base+timedelta(minutes=minutes)
    # New auto sources should be eligible quickly rather than waiting from an old creation timestamp.
    if not last_run and candidate<now:candidate=now
    return candidate.strftime('%Y-%m-%d %H:%M:%S')

def _v42_enrich_source(project_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    out=dict(item); last=_v42_source_last_run(project_id,item.get('id') or '')
    out['last_run']=last
    out['last_completed_at']=(last or {}).get('finished_at') or ''
    out['last_imported']=(last or {}).get('imported',0)
    out['next_run_at']=_v42_source_next_run(item,last)
    if last and last.get('status') in {'queued','running'}:out['runtime_status']=last.get('status')
    elif item.get('enabled') is False:out['runtime_status']='disabled'
    elif last and last.get('status')=='failed':out['runtime_status']='failed'
    else:out['runtime_status']=item.get('status') or 'unchecked'
    return out

@app.get('/api/v42/projects/{project_id}/sources')
def v42_list_sources(project_id: str):
    get_project(project_id); return {"ok": True, "items": [_v42_enrich_source(project_id,x) for x in _v42_list(project_id, 'sources')]}


@app.post('/api/v42/projects/{project_id}/sources')
def v42_create_source(project_id: str, payload: V42SourceReq):
    get_project(project_id)
    if not payload.name.strip() or not payload.source.strip():
        raise HTTPException(status_code=400, detail='名称和来源地址不能为空')
    if payload.type not in {'folder','rtsp','http_json'}:
        raise HTTPException(status_code=400, detail='来源类型只支持 folder / rtsp / http_json')
    if payload.collect_mode not in {'manual','auto'}:
        raise HTTPException(status_code=400, detail='执行方式只支持 manual / auto')
    if payload.schedule_type not in {'interval','daily'}:
        raise HTTPException(status_code=400, detail='自动执行周期只支持 interval / daily')
    rows = _v42_list(project_id, 'sources')
    item = {"id": uuid.uuid4().hex[:12], **payload.dict(), "status":"unchecked", "message":"未检测", "created_at":now_iso(), "updated_at":now_iso()}
    rows.insert(0, item); _v42_save(project_id, 'sources', rows[:100]); return item


@app.put('/api/v42/projects/{project_id}/sources/{source_id}')
def v42_update_source(project_id: str, source_id: str, payload: V42SourceReq):
    rows=_v42_list(project_id,'sources')
    for i,x in enumerate(rows):
        if x.get('id')==source_id:
            rows[i]={**x,**payload.dict(),"updated_at":now_iso()};_v42_save(project_id,'sources',rows);return rows[i]
    raise HTTPException(status_code=404,detail='素材源不存在')


@app.delete('/api/v42/projects/{project_id}/sources/{source_id}')
def v42_delete_source(project_id: str, source_id: str):
    rows=_v42_list(project_id,'sources');_v42_save(project_id,'sources',[x for x in rows if x.get('id')!=source_id]);return {"ok":True}


def _v42_json_path(data: Any, path: str) -> Any:
    cur=data
    for part in [x for x in str(path or '').split('.') if x]:
        if isinstance(cur,dict):cur=cur.get(part)
        else:return None
    return cur


def _v42_source_test(item: Dict[str, Any]) -> Dict[str, Any]:
    typ=item.get('type');src=str(item.get('source') or '').strip()
    if typ=='folder':
        p=Path(src).expanduser(); ok=p.exists(); return {"ok":ok,"message":f"路径可用：{p}" if ok else f"路径不存在：{p}"}
    if typ=='http_json':
        headers={}
        try: headers=json.loads(item.get('headers_json') or '{}')
        except Exception: return {"ok":False,"message":"headers_json 不是合法 JSON"}
        try:
            r=requests.get(src,headers=headers,timeout=8);r.raise_for_status();data=r.json();items=_v42_json_path(data,item.get('items_path') or 'items')
            count=len(items) if isinstance(items,list) else (1 if isinstance(items,dict) else 0)
            return {"ok":True,"message":f"接口可用，读取到 {count} 条候选记录"}
        except Exception as e:return {"ok":False,"message":f"接口连接失败：{e}"}
    if typ=='rtsp':
        try:
            import cv2
            cap=cv2.VideoCapture(src);ok,frame=cap.read();cap.release();return {"ok":bool(ok and frame is not None),"message":"视频流可读取" if ok and frame is not None else "视频流无法读取"}
        except Exception as e:return {"ok":False,"message":f"视频流检测失败：{e}"}
    return {"ok":False,"message":"不支持的素材源类型"}


@app.post('/api/v42/projects/{project_id}/sources/{source_id}/test')
def v42_test_source(project_id: str, source_id: str):
    rows=_v42_list(project_id,'sources');item=next((x for x in rows if x.get('id')==source_id),None)
    if not item:raise HTTPException(status_code=404,detail='素材源不存在')
    result=_v42_source_test(item)
    for x in rows:
        if x.get('id')==source_id:x.update(status='ready' if result['ok'] else 'failed',message=result['message'],last_checked_at=now_iso(),updated_at=now_iso())
    _v42_save(project_id,'sources',rows)
    if not result['ok']: raise HTTPException(status_code=400,detail=result['message'])
    return {"ok":True,**result}


def _v42_collect_status(project_id: str, run_id: str, **kw):
    rows=_v42_list(project_id,'collection_runs')
    for x in rows:
        if x.get('id')==run_id:x.update(**kw,updated_at=now_iso())
    _v42_save(project_id,'collection_runs',rows)


def _v42_run_collect(project_id: str, run_id: str, source: Dict[str, Any], payload: Dict[str, Any]):
    try:
        _v42_collect_status(project_id,run_id,status='running',stage='读取素材',started_at=now_iso())
        typ=source.get('type');src=str(source.get('source') or '').strip();dataset_id=payload.get('dataset_id') or 'default';limit=max(1,min(2000,int(payload.get('max_items') or 50)))
        imported=[];errors=[];tmpdir=project_dir(project_id)/'v42'/'collect_tmp'/run_id;tmpdir.mkdir(parents=True,exist_ok=True)
        if typ=='folder':
            root=Path(src).expanduser()
            if not root.exists():raise RuntimeError(f'路径不存在：{root}')
            files=[root] if root.is_file() else [p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
            for f in files[:limit]:
                rec=add_image_record(project_id,f,f.name,'source_folder',dataset_id)
                if rec: imported.append(rec['id'])
        elif typ=='rtsp':
            import cv2
            cap=cv2.VideoCapture(src)
            if not cap.isOpened():raise RuntimeError('视频/RTSP 无法打开')
            source_fps=float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0;interval=max(.1,float(payload.get('interval_seconds') or 2));step=max(1,int(round(source_fps*interval)));idx=0
            while len(imported)<limit:
                ok,frame=cap.read()
                if not ok or frame is None:break
                if idx%step==0:
                    temp=tmpdir/f'frame_{idx:09d}.jpg';cv2.imwrite(str(temp),frame);rec=add_image_record(project_id,temp,temp.name,'source_rtsp',dataset_id)
                    if rec:imported.append(rec['id'])
                idx+=1
            cap.release()
        elif typ=='http_json':
            headers=json.loads(source.get('headers_json') or '{}');r=requests.get(src,headers=headers,timeout=20);r.raise_for_status();data=r.json();items=_v42_json_path(data,source.get('items_path') or 'items')
            if isinstance(items,dict):items=[items]
            if not isinstance(items,list):raise RuntimeError('接口返回中未找到数组，请检查 items_path')
            fld=source.get('image_url_field') or 'image_url'
            for i,row in enumerate(items[:limit]):
                if not isinstance(row,dict):continue
                url=str(row.get(fld) or '').strip()
                if not url:continue
                try:
                    rr=requests.get(url,timeout=20);rr.raise_for_status();ext=Path(url.split('?',1)[0]).suffix.lower();ext=ext if ext in IMAGE_EXTS else '.jpg';temp=tmpdir/f'api_{i:06d}{ext}';temp.write_bytes(rr.content);rec=add_image_record(project_id,temp,temp.name,'source_http',dataset_id)
                    if rec:imported.append(rec['id'])
                except Exception as e:errors.append(str(e))
        else:raise RuntimeError('不支持的素材源类型')
        _v42_collect_status(project_id,run_id,status='done',stage='完成',progress=100,imported=len(imported),image_ids=imported,errors=errors[-20:],finished_at=now_iso())
    except Exception as e:
        _v42_collect_status(project_id,run_id,status='failed',stage='失败',error=str(e),finished_at=now_iso())


@app.get('/api/v42/projects/{project_id}/collection-runs')
def v42_collection_runs(project_id: str):return {"ok":True,"items":_v42_list(project_id,'collection_runs')}


@app.post('/api/v42/projects/{project_id}/sources/{source_id}/collect')
def v42_collect(project_id: str, source_id: str, payload: V42CollectReq):
    source=_v42_get(project_id,'sources',source_id)
    if not source:raise HTTPException(status_code=404,detail='素材源不存在')
    run={"id":uuid.uuid4().hex[:12],"source_id":source_id,"source_name":source.get('name'),"dataset_id":payload.dataset_id,"status":"queued","stage":"等待采集","progress":0,"imported":0,"created_at":now_iso(),"updated_at":now_iso()}
    rows=_v42_list(project_id,'collection_runs');rows.insert(0,run);_v42_save(project_id,'collection_runs',rows[:100])
    th=threading.Thread(target=_v42_run_collect,args=(project_id,run['id'],source,payload.dict()),daemon=True);th.start();return run



_V42_SOURCE_SCHEDULER_STARTED=False
_V42_SOURCE_SCHEDULER_LOCK=threading.Lock()

def _v42_source_due(project_id: str, source: Dict[str, Any], now: datetime) -> bool:
    if not source.get('enabled',True) or source.get('collect_mode','manual')!='auto':return False
    last=_v42_source_last_run(project_id,source.get('id') or '')
    if last and last.get('status') in {'queued','running'}:return False
    next_at=_parse_dt_value(_v42_source_next_run(source,last,now))
    return bool(next_at and next_at<=now)

def _v42_source_scheduler_once(now: Optional[datetime]=None) -> int:
    launched=0;now=now or datetime.now()
    for project in read_json(PROJECTS_FILE,[]):
        project_id=project.get('id')
        if not project_id:continue
        for source in _v42_list(project_id,'sources'):
            if not _v42_source_due(project_id,source,now):continue
            try:
                v42_collect(project_id,source.get('id'),V42CollectReq(
                    dataset_id=source.get('dataset_id') or 'default',
                    max_items=int(source.get('max_items') or 50),
                    interval_seconds=float(source.get('interval_seconds') or 2.0),
                ));launched+=1
            except Exception:
                pass
    return launched

def _v42_source_scheduler_loop():
    while True:
        try:_v42_source_scheduler_once()
        except Exception:pass
        time.sleep(20)

def _v42_start_source_scheduler():
    global _V42_SOURCE_SCHEDULER_STARTED
    with _V42_SOURCE_SCHEDULER_LOCK:
        if _V42_SOURCE_SCHEDULER_STARTED:return
        _V42_SOURCE_SCHEDULER_STARTED=True
        threading.Thread(target=_v42_source_scheduler_loop,daemon=True,name='v42-source-scheduler').start()

@app.on_event('startup')
def _v42_startup_scheduler():
    _v42_start_source_scheduler()

@app.post('/api/v42/model-configs/{config_id}/test')
def v42_test_saved_model_config(config_id: str):
    item=next((x for x in _v35_items(MODEL_CONFIGS_FILE) if x.get('id')==config_id),None)
    if not item:raise HTTPException(status_code=404,detail='模型配置不存在')
    return v35_test_model_config(V35ModelConfigReq(**item))

@app.post('/api/v42/projects/{project_id}/prelabel-tasks/{task_id}/retry')
def v42_retry_prelabel_task(project_id: str, task_id: str):
    task=_v33_get_task(project_id,'prelabel_tasks',task_id) or {}
    payload=task.get('request_payload')
    if not payload:raise HTTPException(status_code=400,detail='旧任务没有保存创建参数，请重新创建自动标注任务')
    return v35_create_prelabel_task(project_id,V35PrelabelTaskReq(**payload))

class V42PolicyReq(BaseModel):
    name: str
    algorithm_id: Optional[str] = ''
    dataset_id: str = 'default'
    source_id: Optional[str] = ''
    min_images: int = 300
    min_boxes_per_label: int = 100
    min_precision: float = 0.85
    min_recall: float = 0.80
    min_map50: float = 0.85
    use_online_audit: bool = False
    min_audit_samples: int = 20
    min_online_accuracy: float = 0.90
    collect_each_loop: int = 100
    max_loops: int = 2
    auto_collect: bool = True
    auto_prelabel: bool = False
    model_config_id: Optional[str] = ''
    prompt_template_id: Optional[str] = ''
    target_label: Optional[str] = ''
    auto_retrain: bool = True
    framework: str = 'ultralytics'
    algorithm: str = 'yolo11s_det'
    model: str = 'yolo11s.pt'
    epochs: int = 80
    imgsz: int = 640
    batch: int = 8
    device: str = '0'
    target: str = 'local'
    server_id: Optional[str] = ''
    enabled: bool = True


@app.get('/api/v42/projects/{project_id}/iteration-policies')
def v42_policies(project_id: str):get_project(project_id);return {"ok":True,"items":_v42_list(project_id,'iteration_policies')}


@app.post('/api/v42/projects/{project_id}/iteration-policies')
def v42_create_policy(project_id: str,payload:V42PolicyReq):
    get_project(project_id)
    if not payload.name.strip():raise HTTPException(status_code=400,detail='策略名称不能为空')
    rows=_v42_list(project_id,'iteration_policies');item={"id":uuid.uuid4().hex[:12],**payload.dict(),"created_at":now_iso(),"updated_at":now_iso()};rows.insert(0,item);_v42_save(project_id,'iteration_policies',rows[:100]);return item


@app.put('/api/v42/projects/{project_id}/iteration-policies/{policy_id}')
def v42_update_policy(project_id:str,policy_id:str,payload:V42PolicyReq):
    rows=_v42_list(project_id,'iteration_policies')
    for i,x in enumerate(rows):
        if x.get('id')==policy_id:rows[i]={**x,**payload.dict(),"updated_at":now_iso()};_v42_save(project_id,'iteration_policies',rows);return rows[i]
    raise HTTPException(status_code=404,detail='迭代策略不存在')


@app.delete('/api/v42/projects/{project_id}/iteration-policies/{policy_id}')
def v42_delete_policy(project_id:str,policy_id:str):
    rows=_v42_list(project_id,'iteration_policies');_v42_save(project_id,'iteration_policies',[x for x in rows if x.get('id')!=policy_id]);return {"ok":True}


class V42OnlineFeedbackReq(BaseModel):
    algorithm_id: str
    correct: bool
    score: Optional[float] = None
    category: Optional[str] = ''
    reason: Optional[str] = ''
    image_url: Optional[str] = ''
    dataset_id: Optional[str] = ''
    source: Optional[str] = 'external_audit'
    raw: Optional[Dict[str, Any]] = None


def _v42_audit_summary(project_id: str, algorithm_id: str, limit: int = 500) -> Dict[str, Any]:
    rows=[x for x in _v42_list(project_id,'online_feedback') if x.get('algorithm_id')==algorithm_id][:max(1,limit)]
    total=len(rows);correct=sum(1 for x in rows if bool(x.get('correct')))
    cats={}
    for x in rows:
        if x.get('correct'):continue
        k=str(x.get('category') or '其他问题').strip() or '其他问题';cats[k]=cats.get(k,0)+1
    return {"total":total,"correct":correct,"incorrect":total-correct,"accuracy":(correct/total if total else None),"error_categories":cats,"recent":rows[:30]}


@app.get('/api/v42/projects/{project_id}/online-feedback')
def v42_online_feedback(project_id: str, algorithm_id: Optional[str] = None):
    get_project(project_id);rows=_v42_list(project_id,'online_feedback')
    if algorithm_id:rows=[x for x in rows if x.get('algorithm_id')==algorithm_id]
    return {"ok":True,"items":rows[:500],"summary":_v42_audit_summary(project_id,algorithm_id) if algorithm_id else None}


@app.post('/api/v42/projects/{project_id}/online-feedback')
def v42_submit_online_feedback(project_id: str, payload: V42OnlineFeedbackReq):
    get_project(project_id)
    if not next((x for x in list_algorithms_internal(project_id) if x.get('id')==payload.algorithm_id),None):
        raise HTTPException(status_code=404,detail='算法不存在')
    item={"id":uuid.uuid4().hex[:12],**payload.dict(),"created_at":now_iso()}
    # 外部系统/大模型抽查判为错误时，可把原图自动回流到指定数据集；失败只记录原因，不伪造素材。
    if (not payload.correct) and (payload.image_url or '').strip() and (payload.dataset_id or '').strip():
        try:
            rr=requests.get((payload.image_url or '').strip(),timeout=20);rr.raise_for_status()
            ext=Path((payload.image_url or '').split('?',1)[0]).suffix.lower();ext=ext if ext in IMAGE_EXTS else '.jpg'
            tmp=project_dir(project_id)/'v42'/'feedback_tmp';tmp.mkdir(parents=True,exist_ok=True)
            fp=tmp/f"feedback_{item['id']}{ext}";fp.write_bytes(rr.content)
            rec=add_image_record(project_id,fp,fp.name,'online_feedback',payload.dataset_id or 'default')
            item['returned_image_id']=rec.get('id') if rec else ''
        except Exception as e:item['return_error']=str(e)
    rows=_v42_list(project_id,'online_feedback');rows.insert(0,item);_v42_save(project_id,'online_feedback',rows[:5000])
    return {"ok":True,"item":item,"summary":_v42_audit_summary(project_id,payload.algorithm_id)}


def _v42_hygiene_report(project_id: str, dataset_id: str, max_scan: int = 1000) -> Dict[str, Any]:
    import hashlib
    get_project(project_id);rows=[]
    for x in load_images(project_id) or []:
        if str(x.get('dataset_id') or 'default')==str(dataset_id):rows.append(x)
    rows=rows[:max(1,min(5000,max_scan))]
    seen={};dups=[];broken=[];blurry=[];lowres=[];extreme=[]
    try:import cv2
    except Exception:cv2=None
    for x in rows:
        raw_path=str(x.get('path') or '').strip()
        fp=Path(raw_path) if raw_path else (project_dir(project_id)/'uploads'/str(x.get('stored_name') or ''))
        if not fp.exists():broken.append(x.get('id'));continue
        try:
            h=hashlib.sha256(fp.read_bytes()).hexdigest()
            if h in seen:dups.append({"id":x.get('id'),"same_as":seen[h]})
            else:seen[h]=x.get('id')
            if cv2 is not None:
                im=cv2.imread(str(fp))
                if im is None:broken.append(x.get('id'));continue
                hh,ww=im.shape[:2]
                if min(hh,ww)<320:lowres.append(x.get('id'))
                gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
                if float(cv2.Laplacian(gray,cv2.CV_64F).var())<45.0:blurry.append(x.get('id'))
                mean=float(gray.mean())
                if mean<20 or mean>235:extreme.append(x.get('id'))
        except Exception:broken.append(x.get('id'))
    return {"scanned":len(rows),"duplicates":dups,"duplicate_count":len(dups),"broken":broken,"broken_count":len(broken),"blurry":blurry,"blurry_count":len(blurry),"low_resolution":lowres,"low_resolution_count":len(lowres),"extreme_brightness":extreme,"extreme_brightness_count":len(extreme),"note":"自动质检只标记风险样本，不自动删除，避免误删行业难样本。"}


@app.get('/api/v42/projects/{project_id}/datasets/{dataset_id}/hygiene')
def v42_dataset_hygiene(project_id: str, dataset_id: str, max_scan: int = 1000):
    return {"ok":True,"report":_v42_hygiene_report(project_id,dataset_id,max_scan)}


def _v42_publish_job_version(project_id: str, algorithm_id: str, job_id: str) -> Optional[Dict[str, Any]]:
    if not algorithm_id:return None
    models=[m for m in list_models_internal(project_id) if m.get('job_id')==job_id]
    if not models:return None
    models.sort(key=lambda m:(0 if str(m.get('name','')).lower().startswith('best') else 1,0 if m.get('type') in {'pt','pdparams'} else 1,-float(m.get('size_mb') or 0)))
    for m in models:
        try:
            return v12_assign_version(project_id,algorithm_id,AlgorithmVersionReq(model_name=m.get('name') or '',model_source='project',job_id=job_id,version_name='',remark='v42 自动迭代达标后归档'))
        except HTTPException as e:
            if '已经归属' in str(e.detail):continue
            raise
    return None


def _v42_float(v: Any) -> Optional[float]:
    try:return float(str(v).strip())
    except Exception:return None


def _v42_metrics_from_job(project_id: str, job_id: str) -> Dict[str, Any]:
    rep=job_report(project_id,job_id);out={"report":rep,"precision":None,"recall":None,"map50":None}
    for k,v in rep.items():
        low=str(k).lower().replace(' ','')
        num=_v42_float(v)
        if num is None:continue
        if 'precision' in low and out['precision'] is None:out['precision']=num
        if 'recall' in low and out['recall'] is None:out['recall']=num
        if ('map50' in low and '95' not in low) and out['map50'] is None:out['map50']=num
    return out


def _v42_latest_algorithm_job(project_id: str, algorithm_id: str) -> Optional[str]:
    alg=next((x for x in list_algorithms_internal(project_id) if x.get('id')==algorithm_id),None)
    if not alg:return None
    for v in alg.get('versions',[]) or []:
        if v.get('job_id'):return v.get('job_id')
    return None


def _v42_iteration_update(project_id: str, run_id: str, **kw):
    rows=_v42_list(project_id,'iteration_runs')
    for x in rows:
        if x.get('id')==run_id:x.update(**kw,updated_at=now_iso())
    _v42_save(project_id,'iteration_runs',rows)


def _v42_wait_collection(project_id: str, run_id: str, timeout_sec: int=3600) -> Dict[str, Any]:
    start=time.time()
    while time.time()-start<timeout_sec:
        item=_v42_get(project_id,'collection_runs',run_id) or {}
        if item.get('status') in {'done','failed','stopped'}:return item
        time.sleep(2)
    return {"status":"failed","error":"素材采集等待超时"}


def _v42_wait_prelabel(project_id: str, task_id: str, timeout_sec: int=7200) -> Dict[str, Any]:
    start=time.time()
    while time.time()-start<timeout_sec:
        item=_v33_get_task(project_id,'prelabel_tasks',task_id) or {}
        if item.get('status') in {'done','failed','stopped'}:return item
        time.sleep(2)
    return {"status":"failed","error":"自动标注等待超时"}


def _v42_wait_train(project_id: str, job_id: str, timeout_sec: int=86400) -> Dict[str, Any]:
    start=time.time()
    while time.time()-start<timeout_sec:
        try:
            raw=read_json(project_dir(project_id)/'jobs'/job_id/'job.json',{})
            job=enrich_job_runtime(project_id,raw) if raw else {}
        except Exception:
            job=read_json(project_dir(project_id)/'jobs'/job_id/'job.json',{})
        if job.get('status') in {'done','finished','failed','stopped'}:return job
        time.sleep(5)
    return {"status":"failed","message":"训练等待超时"}


def _v42_run_iteration(project_id: str, run_id: str, policy: Dict[str, Any]):
    history=[]
    try:
        _v42_iteration_update(project_id,run_id,status='running',stage='检查数据与模型质量',started_at=now_iso())
        max_loops=max(1,min(10,int(policy.get('max_loops') or 1)))
        current_job_id=_v42_latest_algorithm_job(project_id,str(policy.get('algorithm_id') or ''))
        for loop in range(1,max_loops+1):
            q=dataset_quality_report(project_id,policy.get('dataset_id') or 'default',False)
            scarce=[k for k,v in (q.get('label_usage') or {}).items() if int(v or 0)<int(policy.get('min_boxes_per_label') or 0)]
            data_pass=q.get('image_count',0)>=int(policy.get('min_images') or 0) and not scarce and q.get('can_train')
            job_id=current_job_id
            metrics=_v42_metrics_from_job(project_id,job_id) if job_id else {"precision":None,"recall":None,"map50":None,"report":{}}
            metric_available=all(metrics.get(k) is not None for k in ['precision','recall','map50'])
            metric_pass=metric_available and metrics['precision']>=float(policy.get('min_precision') or 0) and metrics['recall']>=float(policy.get('min_recall') or 0) and metrics['map50']>=float(policy.get('min_map50') or 0)
            audit=_v42_audit_summary(project_id,str(policy.get('algorithm_id') or '')) if policy.get('use_online_audit') else {"total":0,"accuracy":None,"error_categories":{}}
            audit_pass=(not policy.get('use_online_audit')) or (audit.get('total',0)>=int(policy.get('min_audit_samples') or 0) and audit.get('accuracy') is not None and audit.get('accuracy')>=float(policy.get('min_online_accuracy') or 0))
            step={"loop":loop,"quality":q,"scarce_labels":scarce,"metrics":metrics,"audit":audit,"data_pass":data_pass,"metric_pass":metric_pass,"audit_pass":audit_pass,"job_id":job_id,"actions":[]}
            history.append(step);_v42_iteration_update(project_id,run_id,loop=loop,history=history,stage=f'第 {loop} 轮质量判定')
            if data_pass and metric_pass and audit_pass:
                published=_v42_publish_job_version(project_id,str(policy.get('algorithm_id') or ''),job_id) if job_id else None
                if published:step['actions'].append({'type':'publish_version','version':published.get('version')})
                _v42_iteration_update(project_id,run_id,status='done',stage='已达标',result='pass',history=history,finished_at=now_iso());return
            # 数据不足或指标不达标时，先从真实素材源补样。
            if policy.get('auto_collect') and policy.get('source_id'):
                source=_v42_get(project_id,'sources',str(policy.get('source_id')))
                if source:
                    cr=v42_collect(project_id,source['id'],V42CollectReq(dataset_id=policy.get('dataset_id') or 'default',max_items=int(policy.get('collect_each_loop') or 100),interval_seconds=2.0))
                    step['actions'].append({"type":"collect","run_id":cr['id'],"focus_labels":scarce})
                    _v42_iteration_update(project_id,run_id,stage=f'第 {loop} 轮：补充真实素材',history=history)
                    cdone=_v42_wait_collection(project_id,cr['id']);step['actions'][-1]['result']=cdone
                    if cdone.get('status')!='done':
                        _v42_iteration_update(project_id,run_id,status='needs_attention',stage='素材补充失败',result='blocked',history=history,error=cdone.get('error') or '素材补充失败',finished_at=now_iso());return
                    # 自动标注只在用户明确配置模型后执行，不伪造框。
                    new_ids=cdone.get('image_ids') or []
                    if policy.get('auto_prelabel') and new_ids and policy.get('model_config_id'):
                        label=str(policy.get('target_label') or (scarce[0] if scarce else '')).strip()
                        if label:
                            req=V35PrelabelTaskReq(model_config_id=policy.get('model_config_id') or None,prompt_template_id=policy.get('prompt_template_id') or None,target_label=label,image_ids=new_ids,dataset_id=policy.get('dataset_id') or 'default',training_framework=policy.get('framework') or 'ultralytics',task_name=f"自动迭代第{loop}轮·{label}",overwrite=False,include_empty=False)
                            pt=v35_create_prelabel_task(project_id,req);step['actions'].append({"type":"prelabel","task_id":pt['id'],"target_label":label})
                            _v42_iteration_update(project_id,run_id,stage=f'第 {loop} 轮：模型自动标注',history=history)
                            pdone=_v42_wait_prelabel(project_id,pt['id']);step['actions'][-1]['result']=pdone
                            if pdone.get('status')!='done':
                                _v42_iteration_update(project_id,run_id,status='needs_attention',stage='自动标注失败',result='blocked',history=history,error=pdone.get('error') or '自动标注失败',finished_at=now_iso());return
            # 训练前再次确认有真实有效标注；没配置自动标注时应停下来让用户处理，而不是假装自动完成。
            q2=dataset_quality_report(project_id,policy.get('dataset_id') or 'default',False)
            if not q2.get('can_train'):
                _v42_iteration_update(project_id,run_id,status='needs_attention',stage='等待标注',result='blocked',history=history,error='补充素材后仍没有足够有效标注，请配置自动标注模型或人工复核',finished_at=now_iso());return
            if policy.get('auto_retrain'):
                treq=TrainReq(framework=policy.get('framework') or 'ultralytics',algorithm=policy.get('algorithm') or 'yolo11s_det',model=policy.get('model') or 'yolo11s.pt',epochs=int(policy.get('epochs') or 80),imgsz=int(policy.get('imgsz') or 640),batch=int(policy.get('batch') or 8),device=str(policy.get('device') or '0'),dataset_id=policy.get('dataset_id') or 'default',target=policy.get('target') or 'local',server_id=policy.get('server_id') or None)
                _v42_iteration_update(project_id,run_id,stage=f'第 {loop} 轮：自动重训',history=history)
                started=v12_start_train(project_id,treq);jid=started.get('job',{}).get('id');step['actions'].append({"type":"train","job_id":jid})
                if not jid:raise RuntimeError('训练任务创建失败')
                done=_v42_wait_train(project_id,jid);current_job_id=jid;step['actions'][-1]['result']={"status":done.get('status'),"message":done.get('message')}
                if done.get('status') not in {'done','finished'}:
                    _v42_iteration_update(project_id,run_id,status='needs_attention',stage='自动重训失败',result='blocked',history=history,error=done.get('message') or '训练失败',finished_at=now_iso());return
                # 迭代任务直接使用该真实训练任务的指标继续下一轮判定。
                metrics2=_v42_metrics_from_job(project_id,jid);step['trained_metrics']=metrics2;step['trained_job_id']=jid
                if all(metrics2.get(k) is not None for k in ['precision','recall','map50']) and metrics2['precision']>=float(policy.get('min_precision') or 0) and metrics2['recall']>=float(policy.get('min_recall') or 0) and metrics2['map50']>=float(policy.get('min_map50') or 0) and audit_pass:
                    published=_v42_publish_job_version(project_id,str(policy.get('algorithm_id') or ''),jid)
                    if published:step['actions'].append({'type':'publish_version','version':published.get('version')})
                    _v42_iteration_update(project_id,run_id,status='done',stage='自动重训后已达标',result='pass',history=history,finished_at=now_iso());return
            else:
                _v42_iteration_update(project_id,run_id,status='needs_attention',stage='需要重训',result='blocked',history=history,error='策略关闭了自动重训',finished_at=now_iso());return
        _v42_iteration_update(project_id,run_id,status='done',stage='达到最大迭代轮数',result='not_passed',history=history,finished_at=now_iso())
    except Exception as e:
        _v42_iteration_update(project_id,run_id,status='failed',stage='迭代失败',result='failed',history=history,error=str(e),finished_at=now_iso())


@app.get('/api/v42/projects/{project_id}/iteration-runs')
def v42_iteration_runs(project_id:str):return {"ok":True,"items":_v42_list(project_id,'iteration_runs')}


@app.post('/api/v42/projects/{project_id}/iteration-policies/{policy_id}/run')
def v42_run_policy(project_id:str,policy_id:str):
    policy=_v42_get(project_id,'iteration_policies',policy_id)
    if not policy:raise HTTPException(status_code=404,detail='迭代策略不存在')
    run={"id":uuid.uuid4().hex[:12],"policy_id":policy_id,"policy_name":policy.get('name'),"algorithm_id":policy.get('algorithm_id'),"status":"queued","stage":"等待启动","result":"","loop":0,"history":[],"created_at":now_iso(),"updated_at":now_iso()}
    rows=_v42_list(project_id,'iteration_runs');rows.insert(0,run);_v42_save(project_id,'iteration_runs',rows[:100])
    th=threading.Thread(target=_v42_run_iteration,args=(project_id,run['id'],dict(policy)),daemon=True);th.start();return run


@app.get('/api/v42/projects/{project_id}/quality-overview')
def v42_quality_overview(project_id:str):
    get_project(project_id);datasets=ensure_default_datasets(project_id);ds=[]
    for d in datasets:
        try:q=dataset_quality_report(project_id,d.get('id') or 'default',False)
        except Exception as e:q={"image_count":0,"box_count":0,"can_train":False,"warnings":[str(e)]}
        try:hygiene=_v42_hygiene_report(project_id,d.get('id') or 'default',500)
        except Exception as e:hygiene={"scanned":0,"duplicate_count":0,"blurry_count":0,"low_resolution_count":0,"broken_count":0,"error":str(e)}
        ds.append({"id":d.get('id'),"name":d.get('name'),"quality":q,"hygiene":hygiene})
    algos=[]
    for a in list_algorithms_internal(project_id):
        jid=_v42_latest_algorithm_job(project_id,a.get('id') or '');metrics=_v42_metrics_from_job(project_id,jid) if jid else {"precision":None,"recall":None,"map50":None,"report":{}}
        algos.append({"id":a.get('id'),"name":a.get('name'),"versions":len(a.get('versions') or []),"job_id":jid,"metrics":metrics,"online_audit":_v42_audit_summary(project_id,a.get('id') or '')})
    return {"ok":True,"datasets":ds,"algorithms":algos,"sources":_v42_list(project_id,'sources'),"policies":_v42_list(project_id,'iteration_policies'),"runs":_v42_list(project_id,'iteration_runs')[:20]}


# ============================================================
# v42.4: single-pool dataset quality + algorithm quality + reports
# ============================================================
class V44QualityReq(BaseModel):
    split: Optional[str] = None
    labels: Optional[List[str]] = None
    image_ids: Optional[List[str]] = None
    max_samples: int = 0
    snapshot_id: Optional[str] = None


def _v44_image_quality(project_id: str, images: List[Dict[str, Any]]) -> Dict[str, Any]:
    hashes={};low_res=0;total_bytes=0;res_buckets={"small":0,"medium":0,"large":0}
    for img in images[:1500]:
        path=project_dir(project_id)/"uploads"/img.get("stored_name","")
        try:
            total_bytes+=path.stat().st_size
            if min(int(img.get("width") or 0),int(img.get("height") or 0))<320: low_res+=1
            area=int(img.get("width") or 0)*int(img.get("height") or 0)
            res_buckets["small" if area<640*480 else "medium" if area<1920*1080 else "large"]+=1
            h=hashlib.sha1(path.read_bytes()).hexdigest();hashes[h]=hashes.get(h,0)+1
        except Exception: pass
    dup=sum(max(0,n-1) for n in hashes.values())
    return {"duplicate_images":dup,"low_resolution":low_res,"total_size_bytes":total_bytes,"resolution_buckets":res_buckets}


def _v44_dataset_quality(project_id: str, req: Optional[V44QualityReq]=None) -> Dict[str, Any]:
    project=get_project(project_id);images=load_images(project_id);req=req or V44QualityReq()
    split=(req.split or "").lower();wanted={normalize_label(x) for x in (req.labels or []) if normalize_label(x)};wanted_ids={str(x) for x in (req.image_ids or [])}
    if req.snapshot_id:
        snapshot_file=project_dir(project_id)/"snapshots"/f"{req.snapshot_id}.json"
        if not snapshot_file.is_file():raise HTTPException(status_code=404,detail="训练 Snapshot 不存在")
        snapshot=read_json(snapshot_file,{})
        wanted_ids={str(x) for x in (snapshot.get("train_image_ids") or [])+(snapshot.get("val_image_ids") or [])}
    candidates=[]
    for img in sorted(images,key=lambda row:str(row.get("id") or "")):
        sp=(img.get("split") or "unassigned").lower();sp=sp if sp in {"unassigned","train","val","test"} else "unassigned"
        ann=read_annotation(project_id,img["id"]);clean=[];invalid=0
        for box in ann.get("boxes",[]):
            normalized=normalize_box_for_project(project_id,img,box,create_label=False)
            if normalized:clean.append(normalized)
            else:invalid+=1
        labels={box["label"] for box in clean}
        if split and sp!=split:continue
        if wanted_ids and str(img.get("id")) not in wanted_ids:continue
        if wanted and not labels.intersection(wanted):continue
        candidates.append({**img,"split":sp,"boxes":clean,"valid_box_count":len(clean),"invalid_box_count":invalid})
    if req.max_samples and req.max_samples>0:candidates=candidates[:int(req.max_samples)]
    total_bytes=0;resolution_buckets={"small":0,"medium":0,"large":0};label_images={label:0 for label in project.get("labels",[])}
    for row in candidates:
        path=project_dir(project_id)/"uploads"/str(row.get("stored_name") or "")
        try:row["content_hash"]=hashlib.sha1(path.read_bytes()).hexdigest();total_bytes+=path.stat().st_size
        except Exception:pass
        area=int(row.get("width") or 0)*int(row.get("height") or 0);resolution_buckets["small" if area<640*480 else "medium" if area<1920*1080 else "large"]+=1
        for label in {box["label"] for box in row.get("boxes") or []}:label_images[label]=label_images.get(label,0)+1
    quality=compute_quality(candidates,min_width=640,min_height=480)
    quality["dimensions"]=dict(quality["scores"])
    names={"annotation_completeness":"标注完整度","box_validity":"标注有效性","label_balance":"标签均衡度","duplicate_control":"重复控制","resolution_quality":"分辨率质量","split_coverage":"划分完整度"}
    quality["scores"]={names[key]:value for key,value in quality["scores"].items()}
    quality["label_images"]=label_images;quality["total_size_bytes"]=total_bytes;quality["resolution_buckets"]=resolution_buckets
    quality["split_counts"]={key:int(quality.get("split_counts",{}).get(key,0)) for key in ("unassigned","train","val","test")}
    return quality

@app.get('/api/v44/projects/{project_id}/quality-center')
def v44_quality_center(project_id: str):
    dq=_v44_dataset_quality(project_id)
    algs=list_algorithms_internal(project_id);alg_rows=[]
    for a in algs:
        vers=a.get("versions") or [];v=vers[0] if vers else {};rep=v.get("report") or {}
        def metric(name):
            for k,val in rep.items():
                if name in str(k).lower().replace(' ',''):
                    try: return float(val)
                    except Exception: pass
            return None
        p=metric('precision');r=metric('recall');m=metric('map50')
        vals=[x*100 if x is not None and x<=1 else x for x in [p,r,m] if x is not None]
        score=round(sum(vals)/len(vals),1) if vals else None
        alg_rows.append({"id":a.get("id"),"name":a.get("name"),"version":v.get("version_name") or "", "precision":p,"recall":r,"map50":m,"score":score})
    jobs=list_jobs(project_id);done=[j for j in jobs if j.get('status') in {'done','finished','completed'}];failed=[j for j in jobs if j.get('status')=='failed']
    trained_count=sum(1 for x in alg_rows if x['score'] is not None)
    def avg_metric(k):
        vals=[]
        for x in alg_rows:
            v=x.get(k)
            if v is not None: vals.append(v*100 if v<=1 else v)
        return round(sum(vals)/max(1,len(vals)),1)
    version_coverage=round(sum(1 for a in algs if a.get('versions'))/max(1,len(algs))*100,1)
    alg_quality={"algorithms":alg_rows,"trained_count":trained_count,"avg_score":round(sum(x['score'] for x in alg_rows if x['score'] is not None)/max(1,trained_count),1),"avg_precision":avg_metric('precision'),"avg_recall":avg_metric('recall'),"avg_map50":avg_metric('map50'),"train_success_rate":round(len(done)/max(1,len(done)+len(failed))*100,1),"version_coverage":version_coverage}
    return {"ok":True,"dataset":dq,"algorithm":alg_quality,"time":now_iso()}

@app.post('/api/v44/projects/{project_id}/data-quality')
def v44_data_quality(project_id: str, payload: V44QualityReq):
    return {"ok":True,"quality":_v44_dataset_quality(project_id,payload)}

@app.post('/api/v44/model-configs/{config_id}/test')
def v44_test_saved_model_config(config_id: str):
    cfg=next((x for x in _v35_items(MODEL_CONFIGS_FILE) if x.get('id')==config_id),None)
    if not cfg: raise HTTPException(status_code=404,detail='模型配置不存在')
    return v35_test_model_config(V35ModelConfigReq(**cfg))

@app.get('/api/v44/projects/{project_id}/jobs/{job_id}/report')
def v44_training_report(project_id: str, job_id: str):
    get_project(project_id);jf=project_dir(project_id)/'jobs'/job_id/'job.json'
    if not jf.exists(): raise HTTPException(status_code=404,detail='训练任务不存在')
    job=enrich_job_runtime(project_id,read_json(jf,{}));report=job.get('training_report') or {}
    if not report:
        metrics = job.get('metrics') or job.get('final_metrics') or {}
        elapsed = int(job.get('elapsed_seconds') or 0)
        report = {
            'generated_at': now_iso(),
            'framework': job.get('framework') or '',
            'status': job.get('status') or '',
            'metrics': metrics,
            'per_class': [],
            'weak_labels': [],
            'gate_events': job.get('gate_events') or [],
            'summary': {
                'elapsed_seconds': elapsed,
                'epochs': job.get('epochs') or 0,
                'model': job.get('model') or '',
                'dataset_name': job.get('dataset_name') or '全部数据',
                'artifacts': [x for x in [job.get('best_model'), job.get('last_model')] if x],
            },
            'note': '该任务未生成逐类别评测明细；报告仅汇总已记录的训练结果。',
        }
    version_report=build_version_report({**job,'training_report':report})
    version_report['history'] = report.get('history') or _v45_training_history(job)
    version_report['configuration'] = {
        'framework': job.get('framework') or '', 'algorithm_name': job.get('algorithm_name') or '', 'model': job.get('model') or '',
        'epochs': job.get('epochs') or 0, 'imgsz': job.get('imgsz') or 0, 'batch': job.get('batch'), 'device': job.get('device') or '',
        **(job.get('advanced_params') or {})
    }
    version_report['data_summary'] = {
        'counts': job.get('dataset_counts') or {}, 'selected_ids': job.get('dataset_selected_ids') or {},
        'quality_gate': job.get('quality_gate') or {}
    }
    return {"ok":True,"report_type":"version","job":job,"report":version_report}



def _v45_training_history(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    run_dir=Path(job.get('run_dir') or '')
    csv_path=run_dir/'results.csv' if run_dir else Path('')
    if not csv_path.is_file(): return []
    try:
        import csv
        rows=[]
        with csv_path.open('r',encoding='utf-8-sig',errors='replace',newline='') as fp:
            for raw in csv.DictReader(fp):
                def num(*names):
                    for n in names:
                        for k,v in raw.items():
                            if k and k.strip()==n:
                                try:return float(v)
                                except:return None
                    return None
                rows.append({'epoch':int(float(raw.get('epoch') or len(rows)+1))+1,
                             'precision':num('metrics/precision(B)'), 'recall':num('metrics/recall(B)'),
                             'map50':num('metrics/mAP50(B)'), 'map5095':num('metrics/mAP50-95(B)'),
                             'box_loss':num('train/box_loss'), 'cls_loss':num('train/cls_loss'), 'dfl_loss':num('train/dfl_loss'),
                             'val_box_loss':num('val/box_loss'), 'val_cls_loss':num('val/cls_loss')})
        return rows[-500:]
    except Exception:
        return []

class V45ErrorCauseReq(BaseModel):
    model_config_id: str
    limit: int = 12

@app.post('/api/v45/projects/{project_id}/jobs/{job_id}/error-cause-analysis')
def v45_error_cause_analysis(project_id: str, job_id: str, payload: V45ErrorCauseReq):
    """VLM只做错误原因辅助归因。检测是否正确仍由预测框与人工Ground Truth通过IoU/类别客观计算。"""
    get_project(project_id)
    jf=project_dir(project_id)/'jobs'/job_id/'job.json'; job=read_json(jf,{})
    if not job: raise HTTPException(status_code=404,detail='训练任务不存在')
    cfg=next((x for x in _v35_items(MODEL_CONFIGS_FILE) if x.get('id')==payload.model_config_id),None)
    if not cfg: raise HTTPException(status_code=404,detail='模型配置不存在')
    report=job.get('training_report') or {}; errors=[x for x in (report.get('error_samples') or []) if not x.get('analysis_error')][:max(1,min(30,int(payload.limit or 12)))]
    if not errors: raise HTTPException(status_code=400,detail='当前报告没有可分析的错误样本')
    snapshot=Path(job.get('dataset_snapshot') or job.get('dataset_dir') or '')
    if not snapshot.is_dir():
        # v42.4 job没有单独字段时，从data.yaml父目录回推
        sy=Path(job.get('data_yaml') or '')
        if sy.is_file(): snapshot=sy.parent
    results=[]
    for e in errors:
        name=str(e.get('image') or '')
        ip=None
        for part in ('val','train','test'):
            candidate=snapshot/'images'/part/name
            if candidate.is_file(): ip=candidate;break
        if not ip:
            results.append({'image':name,'error':'找不到训练快照图片'});continue
        prompt=(f"你是视觉算法错误归因助手。程序已根据人工Ground Truth和IoU客观确认该图片存在检测错误。"
                f"漏检标签：{','.join(e.get('false_negative_labels') or []) or '无'}；误检标签：{','.join(e.get('false_positive_labels') or []) or '无'}。"
                "请不要重新判断对错，只分析可能导致模型错误的视觉原因，例如小目标、遮挡、夜间、逆光、模糊、相似干扰物、目标边界不清等。"
                "只返回JSON：{\"cause\":\"主要原因\",\"scene\":[\"场景标签\"],\"data_suggestion\":\"建议补充什么训练数据\"}。")
        try:
            raw=_v35_call_model(cfg,ip,{},prompt,0.0)
            results.append({'image':name,'result':raw})
        except Exception as ex:
            results.append({'image':name,'error':str(ex)})
    report['ai_error_analysis']={'model_config_id':payload.model_config_id,'model_name':cfg.get('name'),'generated_at':now_iso(),'items':results}
    job['training_report']=report; write_json(jf,job); sync_jobs_index(project_id)
    return {'ok':True,'analysis':report['ai_error_analysis']}

@app.post('/api/v44/projects/{project_id}/jobs/{job_id}/supplement')
def v44_supplement_training_data(project_id: str, job_id: str):
    jf=project_dir(project_id)/'jobs'/job_id/'job.json';job=read_json(jf,{})
    if not job: raise HTTPException(status_code=404,detail='训练任务不存在')
    weak=set((job.get('training_report') or {}).get('weak_labels') or [])
    if not weak: raise HTTPException(status_code=400,detail='当前报告没有识别出弱标签')
    limit=int((job.get('quality_gate') or {}).get('supplement_count') or 50);images=load_images(project_id);changed=[]
    for img in images:
        if len(changed)>=limit: break
        if (img.get('split') or 'unassigned')!='unassigned': continue
        labs=_v44_labels_in_ann(read_annotation(project_id,img['id']))
        if labs.intersection(weak): img['split']='train';img['updated_at']=now_iso();changed.append(img['id'])
    save_images(project_id,images)
    job['supplemented_image_ids']=changed;job['supplemented_at']=now_iso();write_json(jf,job);sync_jobs_index(project_id)
    return {"ok":True,"changed":len(changed),"weak_labels":sorted(weak)}

# ============================================================
# v42.7: ordinary-user data curation + staged AI annotation
# ============================================================
from collections import defaultdict

class V47ImageEditReq(BaseModel):
    name: Optional[str] = None

@app.put('/api/v47/projects/{project_id}/images/{image_id}')
def v47_edit_image(project_id: str, image_id: str, payload: V47ImageEditReq):
    get_project(project_id)
    images = load_images(project_id)
    target = next((x for x in images if str(x.get('id')) == image_id), None)
    if not target:
        raise HTTPException(status_code=404, detail='图片不存在')
    name = (payload.name or '').strip()
    # Display name may contain Chinese and spaces because the physical stored_name is never changed.
    # Strip path/control characters only, so renaming cannot escape the project or break JSON/UI.
    name = name.replace('\\', '_').replace('/', '_').replace('\x00', '')
    name = ''.join(ch for ch in name if ord(ch) >= 32).strip()[:220]
    if not name:
        raise HTTPException(status_code=400, detail='名称不能为空')
    # Only the business/display name is changed. The stored file name stays stable so annotations and snapshots remain traceable.
    target['filename'] = name
    target['updated_at'] = now_iso()
    save_images(project_id, images)
    ann = read_annotation(project_id, image_id)
    return {'ok': True, 'image': target, 'annotation': ann}


def _v47_file_for(project_id: str, folder: str, task_id: str) -> Path:
    d = project_dir(project_id) / folder
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{task_id}.json'


def _v47_dhash(path: Path) -> int:
    from PIL import Image
    with Image.open(path) as im:
        g = im.convert('L').resize((9, 8))
        vals = list(g.getdata())
    out = 0
    for y in range(8):
        row = vals[y * 9:(y + 1) * 9]
        for x in range(8):
            out = (out << 1) | (1 if row[x] > row[x + 1] else 0)
    return out


def _v47_hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def _v47_image_metrics(path: Path) -> Dict[str, Any]:
    import hashlib
    raw = path.read_bytes()
    exact = hashlib.sha256(raw).hexdigest()
    try:
        import cv2  # type: ignore
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError('OpenCV无法解码图片')
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        # entropy gives a cheap signal for blank/near-blank data
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
        prob = hist / max(1.0, float(hist.sum()))
        import numpy as np
        nz = prob[prob > 0]
        entropy = float(-(nz * np.log2(nz)).sum()) if len(nz) else 0.0
    except Exception:
        from PIL import Image, ImageStat
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = im.size
            g = im.convert('L')
            brightness = float(ImageStat.Stat(g).mean[0])
        blur_score = 0.0
        entropy = 0.0
    return {'width': int(w), 'height': int(h), 'sha256': exact, 'dhash': _v47_dhash(path), 'blur_score': round(blur_score, 3), 'brightness': round(brightness, 3), 'entropy': round(entropy, 3)}


class V47CleanReq(BaseModel):
    image_ids: Optional[List[str]] = None
    exact_duplicate: bool = True
    near_duplicate: bool = True
    near_duplicate_hamming: int = 5
    min_width: int = 320
    min_height: int = 240
    max_width: int = 10000
    max_height: int = 10000
    blur_check: bool = True
    blur_min_laplacian: float = 45.0
    brightness_check: bool = False
    brightness_min: float = 15.0
    brightness_max: float = 245.0
    corrupt_check: bool = True
    task_name: str = '自动清洗任务'


class V47CleanConfirmReq(BaseModel):
    delete_ids: List[str]


def _v47_run_clean_task(project_id: str, task_id: str, payload: Dict[str, Any]):
    try:
        _v33_update_task(project_id, 'clean_tasks', task_id, status='running', status_text='清洗检查中', started_at=now_iso())
        wanted = set(str(x) for x in (payload.get('image_ids') or []))
        images = load_images(project_id)
        if wanted:
            images = [x for x in images if str(x.get('id')) in wanted]
        if not images:
            raise RuntimeError('没有可清洗的图片')
        total = len(images)
        rows: List[Dict[str, Any]] = []
        exact_seen: Dict[str, str] = {}
        # 4x16bit LSH bands keep near-duplicate candidate checks sub-quadratic for large pools.
        bands: Dict[Tuple[int, int], List[Tuple[int, str]]] = defaultdict(list)
        started = time.time()
        pdir = project_dir(project_id)
        for idx, img in enumerate(images, 1):
            cur = _v33_get_task(project_id, 'clean_tasks', task_id) or {}
            if cur.get('stop_requested'):
                _v33_update_task(project_id, 'clean_tasks', task_id, status='stopped', status_text='已停止', finished_at=now_iso())
                return
            issues: List[Dict[str, Any]] = []
            path = pdir / 'uploads' / str(img.get('stored_name') or '')
            metrics: Dict[str, Any] = {}
            try:
                metrics = _v47_image_metrics(path)
                if payload.get('exact_duplicate'):
                    prev = exact_seen.get(metrics['sha256'])
                    if prev:
                        issues.append({'code': 'exact_duplicate', 'name': '重复图', 'detail': '与另一张图片完全相同', 'related_image_id': prev})
                    else:
                        exact_seen[metrics['sha256']] = str(img.get('id'))
                if payload.get('near_duplicate') and not any(x['code'] == 'exact_duplicate' for x in issues):
                    dh = int(metrics['dhash']); candidates: Dict[str, int] = {}
                    for band in range(4):
                        key = (band, (dh >> (band * 16)) & 0xffff)
                        for old_hash, old_id in bands.get(key, []):
                            candidates[old_id] = old_hash
                    threshold = max(0, min(20, int(payload.get('near_duplicate_hamming') or 5)))
                    best = None
                    for old_id, old_hash in candidates.items():
                        dist = _v47_hamming(dh, old_hash)
                        if dist <= threshold and (best is None or dist < best[0]):
                            best = (dist, old_id)
                    if best:
                        issues.append({'code': 'near_duplicate', 'name': '近似重复', 'detail': f'感知哈希距离 {best[0]}', 'related_image_id': best[1]})
                    for band in range(4):
                        key = (band, (dh >> (band * 16)) & 0xffff)
                        bands[key].append((dh, str(img.get('id'))))
                w, h = int(metrics['width']), int(metrics['height'])
                if w < int(payload.get('min_width') or 0) or h < int(payload.get('min_height') or 0):
                    issues.append({'code': 'resolution_low', 'name': '分辨率偏低', 'detail': f'{w}×{h}'})
                if (payload.get('max_width') and w > int(payload.get('max_width'))) or (payload.get('max_height') and h > int(payload.get('max_height'))):
                    issues.append({'code': 'resolution_high', 'name': '分辨率过高', 'detail': f'{w}×{h}'})
                if payload.get('blur_check') and float(metrics.get('blur_score') or 0) < float(payload.get('blur_min_laplacian') or 45):
                    issues.append({'code': 'blur', 'name': '疑似模糊', 'detail': f"清晰度 {metrics.get('blur_score')}"})
                if payload.get('brightness_check'):
                    b = float(metrics.get('brightness') or 0)
                    if b < float(payload.get('brightness_min') or 15):
                        issues.append({'code': 'too_dark', 'name': '疑似过暗', 'detail': f'平均亮度 {b:.1f}'})
                    if b > float(payload.get('brightness_max') or 245):
                        issues.append({'code': 'too_bright', 'name': '疑似过亮', 'detail': f'平均亮度 {b:.1f}'})
            except Exception as e:
                if payload.get('corrupt_check'):
                    issues.append({'code': 'corrupt', 'name': '图片损坏', 'detail': str(e)[:180]})
            if issues:
                rows.append({'image_id': img.get('id'), 'filename': img.get('filename'), 'url': img.get('url'), 'issues': issues, 'metrics': metrics, 'suggest_delete': True})
            if idx % 5 == 0 or idx == total:
                elapsed = max(0.001, time.time() - started)
                eta = int(max(0, elapsed / idx * (total - idx)))
                _v33_update_task(project_id, 'clean_tasks', task_id, processed_images=idx, total_images=total, flagged_images=len(rows), progress=int(idx / total * 100), elapsed_seconds=int(elapsed), eta_seconds=eta)
        result_path = _v47_file_for(project_id, 'clean_results', task_id)
        write_json(result_path, {'task_id': task_id, 'items': rows, 'generated_at': now_iso(), 'rules': payload})
        _v33_update_task(project_id, 'clean_tasks', task_id, status='awaiting_confirmation', status_text='待确认', progress=100, processed_images=total, total_images=total, flagged_images=len(rows), result_file=str(result_path), finished_scan_at=now_iso())
    except Exception as e:
        _v33_update_task(project_id, 'clean_tasks', task_id, status='failed', status_text='失败', error=str(e), finished_at=now_iso())


@app.get('/api/v47/projects/{project_id}/clean-tasks')
def v47_list_clean_tasks(project_id: str):
    get_project(project_id)
    return {'items': _v33_load_tasks(project_id, 'clean_tasks')}


@app.post('/api/v47/projects/{project_id}/clean-tasks')
def v47_create_clean_task(project_id: str, payload: V47CleanReq):
    get_project(project_id)
    task_id = uuid.uuid4().hex[:12]
    data = payload.dict()
    images = load_images(project_id)
    wanted = set(data.get('image_ids') or [])
    total = len([x for x in images if not wanted or x.get('id') in wanted])
    task = {'id': task_id, 'name': data.get('task_name') or '自动清洗任务', 'status': 'queued', 'status_text': '排队中', 'progress': 0, 'processed_images': 0, 'total_images': total, 'flagged_images': 0, 'created_at': now_iso(), 'request_payload': data, 'stop_requested': False}
    tasks = _v33_load_tasks(project_id, 'clean_tasks'); tasks.insert(0, task); _v33_save_tasks(project_id, 'clean_tasks', tasks[:100])
    threading.Thread(target=_v47_run_clean_task, args=(project_id, task_id, data), daemon=True).start()
    return task


@app.post('/api/v47/projects/{project_id}/clean-tasks/{task_id}/stop')
def v47_stop_clean_task(project_id: str, task_id: str):
    if not _v33_get_task(project_id, 'clean_tasks', task_id):
        raise HTTPException(status_code=404, detail='清洗任务不存在')
    _v33_update_task(project_id, 'clean_tasks', task_id, stop_requested=True, status_text='正在停止')
    return {'ok': True}


@app.get('/api/v47/projects/{project_id}/clean-tasks/{task_id}/result')
def v47_clean_result(project_id: str, task_id: str):
    task = _v33_get_task(project_id, 'clean_tasks', task_id)
    if not task:
        raise HTTPException(status_code=404, detail='清洗任务不存在')
    return {'task': task, 'result': read_json(_v47_file_for(project_id, 'clean_results', task_id), {'items': []})}


@app.post('/api/v47/projects/{project_id}/clean-tasks/{task_id}/confirm')
def v47_confirm_clean(project_id: str, task_id: str, payload: V47CleanConfirmReq):
    task = _v33_get_task(project_id, 'clean_tasks', task_id)
    if not task:
        raise HTTPException(status_code=404, detail='清洗任务不存在')
    allowed = {str(x.get('image_id')) for x in read_json(_v47_file_for(project_id, 'clean_results', task_id), {'items': []}).get('items', [])}
    ids = {str(x) for x in payload.delete_ids if str(x) in allowed}
    deleted = 0
    deleted_images = []
    failed_items = []
    if ids:
        res = v46_batch_delete_images(project_id, V46BatchDeleteImagesReq(image_ids=list(ids)))
        deleted = int(res.get('deleted') or 0)
        deleted_images = list(res.get('deleted_images') or [])
        failed_items = list(res.get('failed_items') or [])
    # 清洗确认后，本次扫描范围内未删除的图片全部进入“已处理”。
    req = task.get('request_payload') or {}
    wanted = {str(x) for x in (req.get('image_ids') or []) if str(x)}
    images = load_images(project_id)
    processed_ids = []
    for img in images:
        iid = str(img.get('id'))
        if wanted and iid not in wanted:
            continue
        img['processing_status'] = 'processed'
        img['cleaned_at'] = now_iso()
        img['clean_task_id'] = task_id
        processed_ids.append(iid)
    save_images(project_id, images)
    deleted_ids = [str(item.get('id')) for item in deleted_images]
    _v33_update_task(project_id, 'clean_tasks', task_id, status='done', status_text='已确认', deleted_images=deleted, delete_failures=len(failed_items), processed_confirmed=len(processed_ids), confirmed_at=now_iso(), finished_at=now_iso())
    return {'ok': not failed_items, 'deleted': deleted, 'deleted_ids': deleted_ids, 'deleted_images': deleted_images, 'failed_items': failed_items, 'processed_ids': processed_ids}


class V47AutoLabelReq(BaseModel):
    image_ids: List[str]
    labels_text: Optional[str] = ''
    reference_image_ids: Optional[List[str]] = None
    threshold: float = 0.45
    overwrite: bool = False
    task_name: str = 'AI自动标注任务'
    provider_id: Optional[str] = None
    model_config_id: Optional[str] = None
    prompt_template_id: Optional[str] = None
    business_instruction: str = ''
    preview_count: int = 0

class V47AutoLabelConfirmReq(BaseModel):
    image_ids: Optional[List[str]] = None


def _v47_parse_label_text(text: str) -> List[str]:
    import re
    vals = [normalize_label(x) for x in re.split(r'[、,，;；\n\t]+', text or '') if x.strip()]
    return list(dict.fromkeys(x for x in vals if x))


def _v47_default_annotation_model() -> Dict[str, Any]:
    items = _v35_model_items()
    if not items:
        raise HTTPException(status_code=400, detail='尚未配置可用AI模型，请先在高级功能里的模型配置完成一次配置')
    return next((x for x in items if x.get('default_for_annotation')), items[0])


def _v47_label_catalog(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    meta_by_code = {
        str(item.get('code')): item
        for item in project.get('label_meta', [])
        if isinstance(item, dict) and str(item.get('status') or 'active') == 'active'
    }
    result = []
    for index, item in enumerate(project.get('labels', [])):
        code = normalize_label(item.get('code') if isinstance(item, dict) else item)
        if not code:
            continue
        meta = item if isinstance(item, dict) else meta_by_code.get(code, {})
        if str(meta.get('status') or 'active') != 'active':
            continue
        result.append({
            'code': code,
            'class_id': index,
            'display_name_zh': str(meta.get('display_name_zh') or meta.get('display_name') or code),
        })
    return result


def _v47_build_annotation_prompt(
    cfg: Dict[str, Any],
    labels: List[Dict[str, Any]],
    *,
    width: int,
    height: int,
    business_instruction: str,
    template: str = '',
) -> str:
    template = (template or cfg.get('annotation_prompt_template') or '').strip()
    if not template:
        template = (
            '你是视觉目标检测标注助手。只标注标签库中的目标：{{labels_json}}。'
            '图片尺寸为 {{image_width}}x{{image_height}}。{{business_instruction}}'
            '必须只返回符合此结构的 JSON，不要输出解释或 Markdown：{{output_schema}}'
        )
    if '{{' in template:
        return render_prompt(
            template,
            labels=labels,
            width=width,
            height=height,
            business_instruction=business_instruction,
        )
    return template.replace('{labels}', '、'.join(str(item.get('code')) for item in labels))


def _v47_runtime_provider(payload: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    config_id = str(payload.get('model_config_id') or '')
    provider_id = str(payload.get('provider_id') or '')
    cfg = next((x for x in _v35_model_items() if x.get('id') == config_id or x.get('id') == provider_id), None)
    if cfg:
        runtime_cfg = dict(cfg)
        reference = str(cfg.get('secret_ref') or '')
        runtime_cfg['_api_key'] = _v35_secret_store().get(reference) if reference else ''
        return auto_label_core.provider_factory(runtime_cfg), cfg
    if provider_id:
        return auto_label_core.provider_factory(provider_id), {'id': provider_id, 'name': provider_id}
    cfg = _v47_default_annotation_model()
    runtime_cfg = dict(cfg)
    reference = str(cfg.get('secret_ref') or '')
    runtime_cfg['_api_key'] = _v35_secret_store().get(reference) if reference else ''
    return auto_label_core.provider_factory(runtime_cfg), cfg


def _v47_run_ai_label_task(project_id: str, task_id: str, payload: Dict[str, Any]):
    try:
        _v33_update_task(project_id, 'prelabel_tasks', task_id, status='running', status_text='AI标注中', started_at=now_iso())
        provider, cfg = _v47_runtime_provider(payload)
        labels = list(payload.get('labels') or [])
        project = get_project(project_id)
        catalog = _v47_label_catalog(project)
        selected_catalog = [item for item in catalog if item.get('code') in labels]
        label_ids = {str(item['code']): int(item['class_id']) for item in selected_catalog}
        if set(labels) != set(label_ids):
            missing = sorted(set(labels) - set(label_ids))
            raise RuntimeError('任务包含标签库之外或已停用的标签：' + '、'.join(missing))
        prompt_template = dict(payload.get('prompt_template_snapshot') or {}).get('prompt') or ''
        ids = set(payload.get('image_ids') or [])
        images = [x for x in load_images(project_id) if x.get('id') in ids]
        preview_count = max(0, int(payload.get('preview_count') or 0))
        if preview_count:
            images = images[:preview_count]
        if not images:
            raise RuntimeError('没有可自动标注的图片')
        total = len(images); started = time.time(); candidates: Dict[str, Any] = {}; box_count = 0; errors = []
        for idx, img in enumerate(images, 1):
            cur = _v33_get_task(project_id, 'prelabel_tasks', task_id) or {}
            if cur.get('stop_requested'):
                _v33_update_task(project_id, 'prelabel_tasks', task_id, status='stopped', status_text='已停止', finished_at=now_iso()); return
            path = project_dir(project_id) / 'uploads' / str(img.get('stored_name') or '')
            try:
                prompt = _v47_build_annotation_prompt(
                    cfg,
                    selected_catalog,
                    width=int(img['width']),
                    height=int(img['height']),
                    business_instruction=str(payload.get('business_instruction') or ''),
                    template=prompt_template,
                )
                response = provider.annotate(
                    image_bytes=path.read_bytes(),
                    prompt=prompt,
                    output_schema=auto_label_core.CANDIDATE_OUTPUT_SCHEMA,
                )
                text = str(response.get('text') or '')
                parsed = auto_label_core.parse_candidate_response(
                    text,
                    width=int(img['width']),
                    height=int(img['height']),
                    label_ids=label_ids,
                )
                threshold = float(payload.get('threshold') if payload.get('threshold') is not None else .45)
                parsed = [box for box in parsed if float(box.get('confidence') or 0) >= threshold]
                boxes = auto_label_core.nms_candidates(parsed, iou_threshold=0.5)
                for box in boxes:
                    box.update({
                        'id': uuid.uuid4().hex[:10],
                        'source': 'ai_candidate',
                        'model_config_id': cfg.get('id'),
                        'prompt_template_id': payload.get('prompt_template_id') or '',
                        'prompt_template_version_id': payload.get('prompt_template_version_id') or '',
                    })
                candidates[str(img['id'])] = {
                    'image_id': img['id'],
                    'filename': img.get('filename'),
                    'url': img.get('url'),
                    'status': 'success' if boxes else 'empty',
                    'boxes': boxes,
                    'raw_response_hash': auto_label_core.raw_response_hash(text),
                    'request_id': str(response.get('request_id') or ''),
                    'latency_ms': int(response.get('latency_ms') or 0),
                    'provider': str(response.get('provider') or ''),
                    'model': str(response.get('model') or cfg.get('model_name') or ''),
                }
                box_count += len(boxes)
            except Exception as e:
                error_item = {'image_id': img.get('id'), 'image':img.get('filename'),'error':str(e)}
                errors.append(error_item)
                candidates[str(img['id'])] = {
                    'image_id': img.get('id'), 'filename': img.get('filename'), 'url': img.get('url'),
                    'status': 'failed', 'boxes': [], 'error': str(e),
                }
            if idx % 2 == 0 or idx == total:
                elapsed=max(.001,time.time()-started);eta=int(max(0,elapsed/idx*(total-idx)))
                _v33_update_task(project_id,'prelabel_tasks',task_id,processed_images=idx,total_images=total,boxes_added=box_count,progress=int(idx/total*100),elapsed_seconds=int(elapsed),eta_seconds=eta,errors=errors[-20:])
        result_path = _v47_file_for(project_id, 'prelabel_candidates', task_id)
        write_json(result_path, {
            'task_id': task_id, 'labels': labels, 'model_name': cfg.get('name'),
            'prompt_template_id': payload.get('prompt_template_id') or '',
            'prompt_template_version_id': payload.get('prompt_template_version_id') or '',
            'items': list(candidates.values()), 'generated_at': now_iso(),
        })
        if errors and len(errors) >= total and box_count == 0:
            raise RuntimeError(errors[0]['error'])
        _v33_update_task(project_id,'prelabel_tasks',task_id,status='awaiting_confirmation',status_text='待确认',progress=100,processed_images=total,total_images=total,boxes_added=box_count,candidate_file=str(result_path),model_name=cfg.get('name'),requested_labels=labels,finished_scan_at=now_iso(),errors=errors[-20:])
    except Exception as e:
        _v33_update_task(project_id,'prelabel_tasks',task_id,status='failed',status_text='失败',error=str(e),finished_at=now_iso())


@app.post('/api/v47/projects/{project_id}/ai-label-tasks')
def v47_create_ai_label_task(project_id: str, payload: V47AutoLabelReq):
    project = get_project(project_id)
    labels = _v47_parse_label_text(payload.labels_text or '')
    ref_ids = set(payload.reference_image_ids or [])
    if ref_ids:
        for iid in ref_ids:
            for b in read_annotation(project_id, iid).get('boxes', []):
                lbl = normalize_label(str(b.get('label') or ''))
                if lbl and lbl not in labels: labels.append(lbl)
    if not labels:
        raise HTTPException(status_code=400, detail='请输入标签，或选择至少一张已有标注的参考图片')
    available = {str(item.get('code')) for item in _v47_label_catalog(project)}
    unknown = sorted(set(labels) - available)
    if unknown:
        raise HTTPException(status_code=400, detail='以下标签不在标签库或已停用：' + '、'.join(unknown))
    cfg = next(
        (x for x in _v35_model_items() if x.get('id') in {payload.model_config_id, payload.provider_id}),
        None,
    )
    if not cfg and not payload.provider_id:
        cfg = _v47_default_annotation_model()
    task_id=uuid.uuid4().hex[:12]
    data=payload.model_dump() if hasattr(payload, 'model_dump') else payload.dict()
    data['labels']=labels
    if cfg:
        data['model_config_id']=cfg.get('id')
    template = {}
    if payload.prompt_template_id and payload.prompt_template_id != 'default':
        template = next((x for x in _v35_prompt_items() if x.get('id') == payload.prompt_template_id), None) or {}
        if not template:
            raise HTTPException(status_code=400, detail='提示词模板不存在')
        data['prompt_template_snapshot'] = template
        data['prompt_template_version_id'] = template.get('version_id') or ''
    total = min(len(payload.image_ids), payload.preview_count) if payload.preview_count > 0 else len(payload.image_ids)
    task={'id':task_id,'name':payload.task_name or 'AI自动标注任务','model_name':(cfg or {}).get('name') or payload.provider_id,'requested_labels':labels,'status':'queued','status_text':'排队中','progress':0,'processed_images':0,'total_images':total,'boxes_added':0,'created_at':now_iso(),'request_payload':data,'stop_requested':False,'workflow':'v47_staged_ai','prompt_template_id':template.get('id') or 'default','prompt_template_version_id':template.get('version_id') or ''}
    tasks=_v33_load_tasks(project_id,'prelabel_tasks');tasks.insert(0,task);_v33_save_tasks(project_id,'prelabel_tasks',tasks[:100])
    threading.Thread(target=_v47_run_ai_label_task,args=(project_id,task_id,data),daemon=True).start()
    return task


@app.get('/api/v47/projects/{project_id}/ai-label-tasks/{task_id}/result')
def v47_ai_label_result(project_id: str, task_id: str):
    task=_v33_get_task(project_id,'prelabel_tasks',task_id)
    if not task: raise HTTPException(status_code=404,detail='自动标注任务不存在')
    return {'status': task.get('status'), 'task':task,'result':read_json(_v47_file_for(project_id,'prelabel_candidates',task_id),{'items':[]})}


@app.post('/api/v47/projects/{project_id}/ai-label-tasks/{task_id}/confirm')
def v47_confirm_ai_label(project_id: str, task_id: str, payload: V47AutoLabelConfirmReq):
    task=_v33_get_task(project_id,'prelabel_tasks',task_id)
    if not task: raise HTTPException(status_code=404,detail='自动标注任务不存在')
    if task.get('status') != 'awaiting_confirmation':
        raise HTTPException(status_code=409, detail='只有待确认的候选标注任务可以写入')
    data=read_json(_v47_file_for(project_id,'prelabel_candidates',task_id),{'items':[]})
    allowed = {str(x.get('image_id')) for x in data.get('items',[]) if x.get('status') in {'success', 'empty'}}
    chosen=set(payload.image_ids or allowed)
    if not chosen.issubset(allowed):
        raise HTTPException(status_code=400, detail='确认范围包含不存在或处理失败的图片')
    overwrite=bool((task.get('request_payload') or {}).get('overwrite'))
    applied=0;boxes=0
    for item in data.get('items',[]):
        iid=str(item.get('image_id'))
        if iid not in chosen: continue
        new=[]
        for candidate in item.get('boxes') or []:
            confirmed = dict(candidate)
            confirmed['source'] = 'ai_candidate_confirmed'
            new.append(confirmed)
        old=read_annotation(project_id,iid).get('boxes',[])
        if overwrite:
            cids={x.get('class_id') for x in new};merged=[x for x in old if x.get('class_id') not in cids]+new
        else: merged=old+new
        write_annotation(project_id,iid,merged);applied+=1;boxes+=len(new)
    _v33_update_task(project_id,'prelabel_tasks',task_id,status='done',status_text='已确认',confirmed_images=applied,confirmed_boxes=boxes,confirmed_at=now_iso(),finished_at=now_iso())
    return {'ok':True,'applied_images':applied,'applied_image_ids':sorted(chosen),'boxes_added':boxes,'labels':get_project(project_id).get('labels',[])}



# ============================================================
# v42.12 — import review, batch label remap, explicit ready state
# ============================================================

class V52LabelRemapReq(BaseModel):
    image_ids: List[str]
    source_label: str
    target_label: str

class V52ReadyReq(BaseModel):
    image_ids: List[str]

@app.post('/api/v52/projects/{project_id}/labels/remap')
def v52_remap_import_labels(project_id: str, payload: V52LabelRemapReq):
    get_project(project_id)
    ids = {str(x) for x in (payload.image_ids or []) if str(x).strip()}
    source = normalize_label(payload.source_label)
    target = normalize_label(payload.target_label)
    if not ids:
        raise HTTPException(status_code=400, detail='请选择需要调整标签的素材')
    if not source or not target:
        raise HTTPException(status_code=400, detail='原标签和新标签不能为空')
    if source == target:
        return {'ok': True, 'changed_images': 0, 'changed_boxes': 0, 'source_label': source, 'target_label': target}
    project = get_project(project_id)
    target_id = get_label_id(project, target)
    changed_images = 0
    changed_boxes = 0
    for iid in ids:
        ann = read_annotation(project_id, iid)
        boxes = ann.get('boxes', [])
        changed = False
        for b in boxes:
            if normalize_label(b.get('label')) == source:
                b['label'] = target
                b['class_id'] = target_id
                changed_boxes += 1
                changed = True
        if changed:
            write_annotation(project_id, iid, boxes)
            changed_images += 1
    return {
        'ok': True,
        'changed_images': changed_images,
        'changed_boxes': changed_boxes,
        'source_label': source,
        'target_label': target,
        'labels': get_project(project_id).get('labels', []),
    }

@app.post('/api/v52/projects/{project_id}/images/mark-ready')
def v52_mark_ready(project_id: str, payload: V52ReadyReq):
    get_project(project_id)
    ids = {str(x) for x in (payload.image_ids or []) if str(x).strip()}
    images = load_images(project_id)
    changed = []
    changed_images = []
    now = now_iso()
    for index, img in enumerate(images):
        if str(img.get('id')) not in ids:
            continue
        updated = mark_ready(img, now)
        images[index] = updated
        changed.append(str(updated.get('id')))
        changed_images.append(updated)
    if changed:
        save_images(project_id, images)
    return {'ok': True, 'changed': len(changed), 'image_ids': changed, 'images': changed_images}

@app.get('/api/v52/projects/{project_id}/import/jobs/{job_id}/review')
def v52_import_review(project_id: str, job_id: str):
    job = v19_read_job(project_id, job_id)
    report = job.get('report') or {}
    ids = [str(x) for x in (report.get('imported_image_ids') or [])]
    wanted = set(ids)
    images = [x for x in list_images(project_id) if str(x.get('id')) in wanted]
    counts: Dict[str, int] = {}
    for img in images:
        ann = read_annotation(project_id, str(img.get('id')))
        for b in ann.get('boxes', []):
            label = str(b.get('label') or '').strip()
            if label:
                counts[label] = counts.get(label, 0) + 1
    return {
        'ok': True,
        'job': {'id': job.get('id'), 'file_name': job.get('file_name'), 'status': job.get('status'), 'detected_format': report.get('detected_format')},
        'report': report,
        'image_ids': ids,
        'images': images,
        'label_box_counts': counts,
    }

# ============================================================
# v42.9 — processed/unprocessed data pool + algorithm report
# ============================================================

def _v49_metric_from_report(report: Dict[str, Any], *keys: str):
    metrics = report.get('metrics') or {}
    for key in keys:
        if key in metrics and metrics.get(key) is not None:
            try: return float(metrics.get(key))
            except Exception: pass
    return None

def _v49_job_label_counts(project_id: str, job: Dict[str, Any]) -> Dict[str, int]:
    selected = job.get('dataset_selected_ids') or {}
    ids = list(selected.get('train') or selected.get('train_image_ids') or [])
    if not ids:
        ids = list((job.get('data_summary') or {}).get('selected_ids', {}).get('train') or [])
    counts: Dict[str, int] = {}
    for iid in ids:
        ann = read_annotation(project_id, str(iid))
        for box in ann.get('boxes', []):
            label = str(box.get('label') or '').strip()
            if label:
                counts[label] = counts.get(label, 0) + 1
    return counts

@app.get('/api/v49/projects/{project_id}/algorithms/{algorithm_id}/report')
def v49_algorithm_report(project_id: str, algorithm_id: str):
    algo = next((x for x in list_algorithms_internal(project_id) if x.get('id') == algorithm_id), None)
    if not algo:
        raise HTTPException(status_code=404, detail='算法不存在')
    jobs_dir = project_dir(project_id) / 'jobs'
    jobs = []
    if jobs_dir.exists():
        for jf in jobs_dir.glob('*/job.json'):
            j = read_json(jf, {})
            if j and (j.get('asset_algorithm_id') == algorithm_id or j.get('algorithm_asset_id') == algorithm_id):
                try: j = enrich_job_runtime(project_id, j)
                except Exception: pass
                jobs.append(j)
    jobs.sort(key=lambda x: str(x.get('finished_at') or x.get('created_at') or ''))
    trend=[]; total_label_counts: Dict[str,int]={}; duration=0; success=0
    for j in jobs:
        rep=j.get('training_report') or {}
        m=_v49_metric_from_report(rep,'metrics/mAP50(B)','map50','mAP50')
        if m is None:
            try: m=float((j.get('metrics') or {}).get('map50'))
            except Exception: m=None
        lc=_v49_job_label_counts(project_id,j)
        for k,v in lc.items(): total_label_counts[k]=total_label_counts.get(k,0)+int(v)
        duration += int(j.get('elapsed_seconds') or 0)
        if j.get('status') in {'done','finished','completed'}: success += 1
        trend.append({'job_id':j.get('id'),'version':j.get('auto_version_name') or '', 'finished_at':j.get('finished_at') or j.get('updated_at') or j.get('created_at'), 'map50':m, 'status':j.get('status'), 'labels':lc, 'images':int((j.get('dataset_counts') or {}).get('train') or 0)})
    versions=algo.get('versions') or []
    latest=versions[0] if versions else None
    aggregate=build_algorithm_report(versions)
    return {'ok':True,'report_type':'algorithm','latest_vs_previous':aggregate['latest_vs_previous'],'best_version':aggregate['best_version'],'best_map50':aggregate['best_map50'],'version_trend':aggregate['trend'],'algorithm':{'id':algo.get('id'),'name':algo.get('name'),'industry':algo.get('industry') or '', 'algorithm_type':algo.get('algorithm_type') or '', 'remark':algo.get('remark') or '', 'version_count':len(versions)}, 'summary':{'training_count':len(jobs),'successful_count':success,'total_duration_seconds':duration,'avg_duration_seconds':int(duration/max(1,len(jobs))) if jobs else 0,'label_counts':total_label_counts,'latest_version':latest.get('version_name') if latest else '', 'latest_accuracy': _v49_metric_from_report((latest or {}).get('report') or {},'metrics/mAP50(B)','map50','mAP50') if latest else None}, 'trend':trend, 'jobs':jobs[-20:]}

@app.post('/api/v49/projects/{project_id}/images/mark-processed')
def v49_mark_processed(project_id: str, payload: V46BatchDeleteImagesReq):
    ids={str(x) for x in payload.image_ids or []}; images=load_images(project_id); changed=0
    for img in images:
        if str(img.get('id')) in ids:
            img['processing_status']='processed';img['cleaned_at']=now_iso();changed+=1
    save_images(project_id,images)
    return {'ok':True,'changed':changed}


# ============================================================
# v42.13 — startup bootstrap / warm cache
# ============================================================
_V53_BOOTSTRAP_LOCK = threading.Lock()
_V53_BOOTSTRAP_THREAD: Optional[threading.Thread] = None
_V53_BOOTSTRAP_STATUS: Dict[str, Any] = {"status":"idle","progress":0,"stage":"尚未开始","message":"","started_at":"","finished_at":"","active_project_id":"","error":""}
_V53_BOOTSTRAP_SNAPSHOT: Dict[str, Any] = {}

def _v53_set_bootstrap(progress:int, stage:str, message:str="", **extra):
    _V53_BOOTSTRAP_STATUS.update({"status":"running" if progress<100 else "ready","progress":max(0,min(100,int(progress))),"stage":stage,"message":message,"updated_at":now_iso(),**extra})

def _v53_project_counts(project:Dict[str,Any])->Dict[str,int]:
    pid=str(project.get("id") or "")
    if not pid:return {"images":0,"algorithms":0,"versions":0,"jobs":0}
    images=read_json(project_dir(pid)/"images.json",[]); algs=read_json(project_dir(pid)/"algorithms.json",[]); jobs=read_json(project_dir(pid)/"jobs"/"index.json",[])
    if not isinstance(images,list):images=[]
    if not isinstance(algs,list):algs=[]
    if not isinstance(jobs,list):jobs=[]
    return {"images":len(images),"algorithms":len(algs),"versions":sum(len(a.get("versions") or []) for a in algs if isinstance(a,dict)),"jobs":len(jobs)}

def _v53_choose_project(projects:List[Dict[str,Any]], preferred_project_id:str=""):
    counts={str(project.get("id") or ""):_v53_project_counts(project) for project in projects}
    return choose_project(projects,preferred_project_id,counts)

def _v53_index_annotations_sync(project_id:str, images:List[Dict[str,Any]], base_progress:int, span:int):
    pending=[x for x in images if not x.get("annotation_summary_at")]
    if not pending:return images
    from concurrent.futures import ThreadPoolExecutor, as_completed
    by_id={str(x.get("id")):x for x in images}; total=len(pending); workers=min(8,max(2,os.cpu_count() or 2))
    def one(img):
        iid=str(img.get("id") or ""); ann=read_annotation(project_id,iid); boxes=ann.get("boxes",[]) if isinstance(ann,dict) else []
        return iid,boxes,(ann.get("updated_at") if isinstance(ann,dict) else "") or now_iso()
    done=0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(one,img) for img in pending]):
            iid,boxes,updated=fut.result(); img=by_id.get(iid)
            if not img:continue
            img["box_count"]=len(boxes); img["annotated"]=bool(boxes); img["labels"]=sorted({str(b.get("label") or "").strip() for b in boxes if str(b.get("label") or "").strip()}); img["annotation_preview"]=[{k:b.get(k) for k in ("class_id","label","x1","y1","x2","y2")} for b in boxes[:32]]; img["annotation_summary_at"]=updated
            if boxes:img["processing_status"]="processed"
            done+=1
            if done==total or done%100==0:_v53_set_bootstrap(base_progress+int(span*done/max(1,total)),"整理历史标注索引",f"{done}/{total} 张")
    save_images(project_id,list(by_id.values())); return list(by_id.values())

def _v53_build_snapshot(project_id:str):
    project=get_project(project_id); datasets=ensure_default_datasets(project_id); images=load_images(project_id); labels=project_label_items(project); algorithms=list_algorithms_internal(project_id)
    try:sync_jobs_index(project_id)
    except Exception:pass
    jobs=read_json(project_dir(project_id)/"jobs"/"index.json",[]); jobs=jobs if isinstance(jobs,list) else []
    models=list_models_internal(project_id); targets=(training_options(project_id) or {}).get("targets",[]); inference=(v16_inference_envs() or {}).get("items",[]); rec=system_recommendation(); local=list_local_models()
    try:pending=(v12_pending_models(project_id) or {}).get("items",[])
    except Exception:pending=[]
    try:test_models=(v12_test_models(project_id) or {}).get("items",[])
    except Exception:test_models=[]
    return {"project":project,"datasets":datasets,"images":images,"labels":labels,"algorithms":algorithms,"jobs":jobs,"models":models,"targets":targets,"inference_envs":inference,"recommendation":rec,"local_models":(local or {}).get("items",[]) if isinstance(local,dict) else [],"pending":pending,"test_models":test_models,"generated_at":now_iso()}

def _v53_bootstrap_worker(preferred_project_id:str=""):
    global _V53_BOOTSTRAP_SNAPSHOT
    try:
        _V53_BOOTSTRAP_STATUS.update({"status":"running","progress":1,"stage":"读取平台数据","message":"正在读取项目索引","started_at":now_iso(),"finished_at":"","error":""})
        projects=read_json(PROJECTS_FILE,[]); projects=projects if isinstance(projects,list) else []
        if not projects:projects=[create_project(ProjectCreate(name="默认空间",description="系统自动创建",labels=[]))]
        _v53_set_bootstrap(8,"读取平台数据",f"发现 {len(projects)} 个项目")
        active=_v53_choose_project(projects,preferred_project_id)
        if not active:raise RuntimeError("没有可用项目")
        active_id=str(active.get("id")); _V53_BOOTSTRAP_STATUS["active_project_id"]=active_id; c=_v53_project_counts(active)
        _v53_set_bootstrap(14,"选择数据项目",f"{active.get('name') or active_id} · {c['images']} 张素材 · {c['algorithms']} 个算法")
        total=max(1,len(projects))
        for idx,p in enumerate(projects):
            pid0=str(p.get("id") or "")
            if not pid0:continue
            ensure_project_dirs(pid0); imgs=load_images(pid0); start_p=16+int(44*idx/total); span=max(1,int(44/total)); _v53_set_bootstrap(start_p,"加载素材与标注",f"{p.get('name') or pid0} · {len(imgs)} 张")
            _v53_index_annotations_sync(pid0,imgs,start_p,span); list_algorithms_internal(pid0)
        _v53_set_bootstrap(64,"加载训练记录","正在读取训练任务、模型与算法版本")
        try:sync_jobs_index(active_id)
        except Exception:pass
        list_models_internal(active_id); list_algorithms_internal(active_id)
        _v53_set_bootstrap(74,"校验训练环境","正在确认 Ultralytics / 训练资源"); training_options(active_id)
        _v53_set_bootstrap(84,"读取本机资源","正在读取本机模型缓存与系统能力"); list_local_models(); system_recommendation()
        _v53_set_bootstrap(91,"生成首屏快照","正在整理算法、素材、版本和任务")
        snap=_v53_build_snapshot(active_id); snap["projects"]=[{**p,"bootstrap_counts":_v53_project_counts(p)} for p in projects]; _V53_BOOTSTRAP_SNAPSHOT=snap
        _V53_BOOTSTRAP_STATUS.update({"status":"ready","progress":100,"stage":"平台数据已就绪","message":f"{len(snap.get('images') or [])} 张素材 · {len(snap.get('algorithms') or [])} 个算法","finished_at":now_iso(),"updated_at":now_iso(),"active_project_id":active_id,"error":""})
    except Exception as e:_V53_BOOTSTRAP_STATUS.update({"status":"failed","stage":"启动预加载失败","message":str(e),"error":repr(e),"finished_at":now_iso(),"updated_at":now_iso()})

def _v53_start_bootstrap(preferred_project_id:str="", force:bool=False):
    global _V53_BOOTSTRAP_THREAD
    with _V53_BOOTSTRAP_LOCK:
        if _V53_BOOTSTRAP_THREAD and _V53_BOOTSTRAP_THREAD.is_alive() and not force:return
        if _V53_BOOTSTRAP_STATUS.get("status")=="ready" and not force:return
        _V53_BOOTSTRAP_THREAD=threading.Thread(target=_v53_bootstrap_worker,args=(preferred_project_id,),daemon=True,name="v53-bootstrap"); _V53_BOOTSTRAP_THREAD.start()

@app.on_event("startup")
def _v53_startup_bootstrap():_v53_start_bootstrap()

class V53BootstrapReq(BaseModel):
    preferred_project_id: Optional[str]=""; force: bool=False

@app.post("/api/v53/bootstrap/start")
def v53_bootstrap_start(payload:V53BootstrapReq):_v53_start_bootstrap(payload.preferred_project_id or "",bool(payload.force)); return {"ok":True,**_V53_BOOTSTRAP_STATUS}

@app.get("/api/v53/bootstrap/status")
def v53_bootstrap_status():return {"ok":True,**_V53_BOOTSTRAP_STATUS}

@app.get("/api/v53/bootstrap/snapshot")
def v53_bootstrap_snapshot(preferred_project_id:Optional[str]=""):
    projects=read_json(PROJECTS_FILE,[]); projects=projects if isinstance(projects,list) else []; requested=str(preferred_project_id or ""); counts={str(project.get("id") or ""):_v53_project_counts(project) for project in projects}; chosen=choose_requested_project(projects,requested,counts) if requested else _v53_choose_project(projects,""); chosen_id=str(chosen.get("id")) if chosen else ""
    if _V53_BOOTSTRAP_STATUS.get("status")!="ready":
        if requested and chosen_id==requested:
            snap=_v53_build_snapshot(chosen_id); snap["projects"]=[{**p,"bootstrap_counts":_v53_project_counts(p)} for p in projects]; return {"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**snap}
        raise HTTPException(status_code=503,detail={"message":"平台数据仍在启动预加载",**_V53_BOOTSTRAP_STATUS})
    if chosen_id and chosen_id!=str(_V53_BOOTSTRAP_SNAPSHOT.get("project",{}).get("id") or ""):
        snap=_v53_build_snapshot(chosen_id); snap["projects"]=[{**p,"bootstrap_counts":_v53_project_counts(p)} for p in projects]; return {"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**snap}
    return {"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**_V53_BOOTSTRAP_SNAPSHOT}


# ============================================================
# v42.14 — label schema management / annotation stability
# ============================================================
@app.get('/api/v54/projects/{project_id}/label-schema')
def v54_label_schema(project_id: str):
    project = get_project(project_id)
    items = active_label_options(project_label_items(project))
    usage = {str(x.get('code')): {'images': 0, 'boxes': 0} for x in items}
    for img in load_images(project_id):
        seen = set()
        for b in read_annotation(project_id, str(img.get('id'))).get('boxes', []):
            label = str(b.get('label') or '').strip()
            if not label:
                continue
            usage.setdefault(label, {'images': 0, 'boxes': 0})['boxes'] += 1
            seen.add(label)
        for label in seen:
            usage.setdefault(label, {'images': 0, 'boxes': 0})['images'] += 1
    for x in items:
        x['usage_images'] = usage.get(str(x.get('code')), {}).get('images', 0)
        x['usage_boxes'] = usage.get(str(x.get('code')), {}).get('boxes', 0)
    return {'ok': True, 'items': items}

@app.get('/api/v54/projects/{project_id}/algorithms/{algorithm_id}/iteration-base')
def v54_iteration_base_info(project_id: str, algorithm_id: str, framework: str = 'ultralytics'):
    get_project(project_id)
    return {'ok': True, 'base': _v54_iteration_base(project_id, algorithm_id, framework)}
