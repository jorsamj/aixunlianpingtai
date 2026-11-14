"""Pure PaddleDetection configuration-to-training-catalog projection.

Preserves the previous API-entry-point identifiers, description, command
template, model-family detection, and training defaults without side effects.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict


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


