# -*- coding: utf-8 -*-
"""飞桨检测台执行器。
支持两类：
1. PaddleX 内置模型名，例如 PP-YOLOE-S_human。
2. PaddleDetection 训练权重，格式：paddledet::<weight>::<config>::<family>::<num_classes>
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_use_onednn", "0")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from PIL import Image, ImageDraw


def as_dict(res):
    if isinstance(res, dict):
        return res
    for attr in ["json", "to_json", "to_dict"]:
        if hasattr(res, attr):
            v = getattr(res, attr)
            try:
                v = v() if callable(v) else v
                if isinstance(v, str):
                    return json.loads(v)
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
    return {}


def parse_boxes(data, conf):
    raw = []
    if isinstance(data, dict):
        for key in ["boxes", "objects", "bbox", "detections"]:
            if isinstance(data.get(key), list):
                raw = data.get(key)
                break
        if not raw and isinstance(data.get("res"), dict):
            return parse_boxes(data["res"], conf)
    detections = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        score = float(item.get("score", item.get("confidence", item.get("conf", 1.0))) or 0)
        if score < conf:
            continue
        coord = item.get("coordinate") or item.get("bbox") or item.get("box") or item.get("xyxy")
        if not coord or len(coord) < 4:
            continue
        label = item.get("label") or item.get("category") or item.get("class_name") or str(item.get("cls_id", item.get("class_id", "目标")))
        cls_id = int(item.get("cls_id", item.get("class_id", 0)) or 0)
        x1, y1, x2, y2 = [float(x) for x in coord[:4]]
        # 部分 PaddleX bbox 是 [x,y,w,h]，做一个保守判断。
        if x2 <= x1 or y2 <= y1:
            x2, y2 = x1 + abs(x2), y1 + abs(y2)
        detections.append({
            "class_id": cls_id,
            "label": str(label),
            "confidence": round(score, 4),
            "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
        })
    return detections


def draw_boxes(input_path, output_path, detections):
    img = Image.open(input_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for d in detections:
        x1, y1, x2, y2 = d["x1"], d["y1"], d["x2"], d["y2"]
        draw.rectangle([x1, y1, x2, y2], outline=(16, 185, 129), width=3)
        text = f"{d['label']} {d['confidence']:.2f}"
        draw.rectangle([x1, max(0, y1 - 24), x1 + min(360, len(text) * 12 + 10), y1], fill=(16, 185, 129))
        draw.text((x1 + 4, max(0, y1 - 21)), text, fill=(255, 255, 255))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=92)


def family_class_opts(family, num_classes):
    try:
        n = int(num_classes or 0)
    except Exception:
        n = 0
    if n <= 0:
        return []
    f = (family or "").lower().replace("-", "_")
    if "picodet" in f:
        return [f"PicoHead.num_classes={n}", f"num_classes={n}"]
    if "ppyoloe" in f:
        return [f"PPYOLOEHead.num_classes={n}", f"num_classes={n}"]
    if "ppyolo" in f or "yolov3" in f:
        return [f"YOLOv3Head.num_classes={n}", f"num_classes={n}"]
    if "rtdetr" in f or f == "detr":
        return [f"DETRHead.num_classes={n}", f"RTDETRTransformer.num_classes={n}", f"num_classes={n}"]
    if "ssd" in f:
        return [f"SSDHead.num_classes={n}", f"num_classes={n}"]
    if "fcos" in f:
        return [f"FCOSHead.num_classes={n}", f"num_classes={n}"]
    if "retina" in f:
        return [f"RetinaHead.num_classes={n}", f"num_classes={n}"]
    if "faster" in f or "cascade" in f or "mask" in f:
        return [f"BBoxHead.num_classes={n}", f"MaskHead.num_classes={n}", f"num_classes={n}"]
    return []


def _decode_labels_b64(value):
    if not value:
        return []
    try:
        raw = base64.urlsafe_b64decode(str(value).encode("utf-8") + b"=" * (-len(str(value)) % 4))
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        return []
    return []


def _read_labels_near_weight(weight: Path):
    # 1) 平台项目常规位置：data/projects/<id>/paddle_dataset/label_list.txt
    candidates = []
    try:
        candidates.append(weight.parent / "label_list.txt")
        candidates.append(weight.parent.parent / "paddle_dataset" / "label_list.txt")
        candidates.append(weight.parent.parent / "labels" / "label_list.txt")
        candidates.append(weight.parent.parent / "labels" / "labels.txt")
        # 训练 run 目录旁边有时有 label_list。
        candidates.extend(weight.parent.glob("**/label_list.txt"))
    except Exception:
        pass
    for fp in candidates:
        try:
            if fp and fp.exists():
                labels = [x.strip() for x in fp.read_text(encoding="utf-8", errors="ignore").splitlines() if x.strip()]
                if labels:
                    return labels
        except Exception:
            continue
    return []


def parse_paddledet_model(model):
    # paddledet::<weight>::<config>::<family>::<num_classes>::<labels_b64>
    parts = str(model).split("::")
    if len(parts) >= 2 and parts[0] == "paddledet":
        labels = _decode_labels_b64(parts[5] if len(parts) > 5 else "")
        info = {
            "weight": parts[1],
            "config": parts[2] if len(parts) > 2 else "",
            "family": parts[3] if len(parts) > 3 else "",
            "num_classes": parts[4] if len(parts) > 4 else "0",
            "labels": labels,
        }
        if not info["labels"]:
            info["labels"] = _read_labels_near_weight(Path(info["weight"]))
        if info["labels"] and (not info.get("num_classes") or str(info.get("num_classes")) in {"0", "None"}):
            info["num_classes"] = str(len(info["labels"]))
        return info
    if str(model).lower().endswith((".pdparams", ".pdmodel", ".pdiparams")):
        weight = Path(str(model))
        labels = _read_labels_near_weight(weight)
        return {"weight": str(model), "config": "", "family": "", "num_classes": str(len(labels) if labels else 0), "labels": labels}
    return None




def write_infer_coco(input_path: Path, work_dir: Path, num_classes: int, labels=None):
    """Create a tiny COCO annotation file for PaddleDetection infer.py.
    Important: keep category IDs 1-based, same as platform training export.
    PaddleDetection builds label_to_cat_id_map from COCO categories, while the model head outputs 0-based class indexes.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    ann_dir = work_dir / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    try:
        img = Image.open(input_path)
        width, height = img.size
    except Exception:
        width, height = 0, 0
    clean_labels = [str(x).strip() for x in (labels or []) if str(x).strip()]
    n = max(1, int(num_classes or len(clean_labels) or 1))
    if not clean_labels:
        clean_labels = [f"class_{i}" for i in range(n)]
    if len(clean_labels) < n:
        clean_labels += [f"class_{i}" for i in range(len(clean_labels), n)]
    categories = [{"id": i + 1, "name": clean_labels[i], "supercategory": "object"} for i in range(n)]
    data = {
        "images": [{"id": 1, "file_name": input_path.name, "width": width, "height": height}],
        "annotations": [],
        "categories": categories,
    }
    ann_path = ann_dir / "infer.json"
    ann_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    # 额外写 label_list，便于排查/导出。
    (work_dir / "label_list.txt").write_text("\n".join(clean_labels), encoding="utf-8")
    return work_dir, ann_path, clean_labels


def _label_from_id(cid, labels):
    try:
        cid_int = int(cid)
    except Exception:
        return str(cid)
    # PaddleDetection COCO result commonly uses category_id (1-based). Some result files may use class_id (0-based).
    if labels:
        if 1 <= cid_int <= len(labels):
            return labels[cid_int - 1]
        if 0 <= cid_int < len(labels):
            return labels[cid_int]
    return f"class_{cid_int}"


def parse_paddledet_json_results(outdir: Path, conf: float, labels=None, max_results: int = 80):
    """Parse PaddleDetection result JSON files into structured rows.
    v31: add --save_results support, label mapping, de-dup, top-K sorting.
    """
    labels = [str(x).strip() for x in (labels or []) if str(x).strip()]
    detections = []
    candidates = []
    for name in ["bbox.json", "bbox_results.json", "det_results.json", "infer_results.json", "results.json"]:
        candidates.extend(outdir.rglob(name))
    candidates.extend([p for p in outdir.rglob("*.json") if "bbox" in p.name.lower() or "result" in p.name.lower()])
    seen = set()
    for jf in candidates:
        if str(jf) in seen:
            continue
        if "infer_dataset" in str(jf):
            continue
        seen.add(str(jf))
        try:
            data = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("bbox") or data.get("boxes") or data.get("results") or data.get("detections") or []
            if isinstance(rows, dict):
                rows = rows.get("bbox") or rows.get("boxes") or rows.get("results") or []
        else:
            rows = []
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            try:
                score = float(item.get("score", item.get("confidence", item.get("conf", 0))) or 0)
            except Exception:
                score = 0
            if score < conf:
                continue
            bbox = item.get("bbox") or item.get("coordinate") or item.get("box") or item.get("xyxy")
            if not bbox or len(bbox) < 4:
                continue
            try:
                a, b, c, d = [float(x) for x in bbox[:4]]
            except Exception:
                continue
            # COCO bbox is [x,y,w,h]. If field name says xyxy, use xyxy.
            if item.get("xyxy") is not None:
                x1, y1, x2, y2 = a, b, c, d
            else:
                x1, y1, x2, y2 = a, b, a + max(0.0, c), b + max(0.0, d)
            cid = item.get("category_id", item.get("class_id", item.get("cls_id", 0)))
            label = item.get("label") or item.get("category") or item.get("class_name") or _label_from_id(cid, labels)
            detections.append({
                "class_id": int(cid or 0),
                "label": str(label),
                "confidence": round(score, 4),
                "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
            })
    # 去重：同类、相近坐标保留高分。
    uniq = {}
    for d in sorted(detections, key=lambda x: x.get("confidence", 0), reverse=True):
        key = (d["label"], round(d["x1"] / 4), round(d["y1"] / 4), round(d["x2"] / 4), round(d["y2"] / 4))
        if key not in uniq:
            uniq[key] = d
    dets = list(uniq.values())
    dets.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return dets[:max_results]

def run_paddledet(model, input_path, output_path, conf):
    info = parse_paddledet_model(model)
    if not info:
        return None
    weight = Path(info["weight"])
    if not weight.exists():
        raise FileNotFoundError(f"飞桨权重不存在：{weight}")
    config = Path(info.get("config") or "")
    if not config.exists():
        # 同目录兜底查找配置。
        for c in list(weight.parent.glob("*.yml")) + list(weight.parent.glob("*.yaml")):
            config = c
            break
    if not config.exists():
        raise FileNotFoundError("没有找到 PaddleDetection 推理配置。请确认该 .pdparams 来自平台训练任务，或同目录存在 .yml 配置。")
    paddledet_dir = Path(os.environ.get("PADDLEDETECTION_DIR") or config.parents[1])
    infer_py = paddledet_dir / "tools" / "infer.py"
    if not infer_py.exists():
        raise FileNotFoundError(f"PaddleDetection infer.py 不存在：{infer_py}")
    outdir = Path(output_path).parent / (Path(output_path).stem + "_paddledet")
    outdir.mkdir(parents=True, exist_ok=True)
    infer_ds_dir, infer_ann, labels = write_infer_coco(input_path, outdir / "infer_dataset", info.get("num_classes") or 1, info.get("labels") or [])
    class_opts = family_class_opts(info.get("family"), info.get("num_classes") or len(labels))
    dataset_opts = [
        f"weights={str(weight)}",
        "use_gpu=False",
        # Critical for PaddleDetection infer.py: do not let original COCO config search dataset/coco/annotations/instances_val2017.json.
        f"TestDataset.dataset_dir={str(infer_ds_dir)}",
        f"TestDataset.anno_path=annotations/infer.json",
        "TestDataset.image_dir=",
        f"EvalDataset.dataset_dir={str(infer_ds_dir)}",
        f"EvalDataset.anno_path=annotations/infer.json",
        "EvalDataset.image_dir=",
    ]
    opts = dataset_opts + class_opts
    cmd = [sys.executable, str(infer_py), "-c", str(config), "--infer_img", str(input_path), "--output_dir", str(outdir), "--draw_threshold", str(conf), "--save_results", "True", "-o"] + opts
    cp = subprocess.run(cmd, cwd=str(paddledet_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if cp.returncode != 0:
        raw = (cp.stderr or cp.stdout or f"PaddleDetection 推理退出码：{cp.returncode}")[-4000:]
        friendly = raw
        if "dataset/coco" in raw and "instances_val2017.json" in raw:
            friendly = "PaddleDetection 推理仍在读取原始 COCO 验证集路径，说明当前配置里的 TestDataset 没有被覆盖成功。请使用 v29 重新检测，或选择平台训练生成的 .pdparams。\n\n" + raw
        raise RuntimeError(friendly)
    # 找输出图片。PaddleDetection 通常输出到 output_dir/输入文件名。
    candidates = list(outdir.rglob(Path(input_path).name)) + list(outdir.rglob("*.jpg")) + list(outdir.rglob("*.png"))
    # 排除临时输入/原图，优先用 PaddleDetection 输出图。
    candidates = [x for x in candidates if x.resolve() != input_path.resolve() and "infer_dataset" not in str(x)] or candidates
    if candidates:
        shutil.copy2(candidates[0], output_path)
    else:
        # 没找到绘制结果时，至少保留原图，避免前端空白。
        shutil.copy2(input_path, output_path)
    detections = parse_paddledet_json_results(outdir, conf, labels=labels, max_results=80)
    if detections:
        # 用平台解析出的结构化结果重绘，避免 0.01 低阈值时 PaddleDetection 原图满屏文字无法阅读。
        draw_boxes(input_path, output_path, detections)
        note = "PaddleDetection检测已完成，已解析结构化明细并按置信度最多展示80个候选框。"
        if conf < 0.05:
            note += " 当前置信度低于0.05，属于调试模式，低分框多不代表模型可用；正式判断建议用0.10或0.25。"
    else:
        # PaddleDetection 有些版本只输出绘制图，不输出结构化 JSON；前端至少展示图片。
        note = "PaddleDetection检测已完成；未解析到结构化bbox明细。建议升级到当前版本并确认推理命令包含 --save_results。"
    return {"ok": True, "detections": detections, "engine": "paddledetection", "model": weight.name, "note": note, "labels": labels}


def run_paddlex_builtin(model_name, input_path, output_path, conf):
    from paddlex import create_model
    model = create_model(model_name or "PP-YOLOE-S_human")
    preds = model.predict(str(input_path))
    if not isinstance(preds, list):
        try:
            preds = list(preds)
        except Exception:
            preds = [preds]
    data = as_dict(preds[0]) if preds else {}
    detections = parse_boxes(data, conf)
    draw_boxes(input_path, output_path, detections)
    return {"ok": True, "detections": detections, "engine": "paddlex", "model": model_name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="PP-YOLOE-S_human")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()
    start = time.perf_counter()
    input_path = Path(args.input)
    output_path = Path(args.output)
    pd_res = run_paddledet(args.model, input_path, output_path, args.conf)
    if pd_res is None:
        pd_res = run_paddlex_builtin(args.model or "PP-YOLOE-S_human", input_path, output_path, args.conf)
    pd_res["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
    print(json.dumps(pd_res, ensure_ascii=False))


if __name__ == "__main__":
    main()
