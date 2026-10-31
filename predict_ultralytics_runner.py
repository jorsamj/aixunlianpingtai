# -*- coding: utf-8 -*-
"""独立 Ultralytics 测试执行器。
由平台后端用指定 Python 环境调用，避免平台自身环境缺少 ultralytics 时测试失败。
"""
import argparse
import json
import time
import os
from pathlib import Path

from PIL import Image, ImageDraw
from ultralytics import YOLO


def publish_phase(phase):
    destination = os.environ.get("CHANGLIAN_DEPLOYMENT_PROGRESS")
    if destination:
        path = Path(destination)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({"phase": phase}), encoding="utf-8")
        os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", default="")
    args = parser.parse_args()

    start = time.perf_counter()
    publish_phase("PREPARING_MODEL")
    model = YOLO(args.model)
    predict_args = {
        "source": args.input,
        "conf": args.conf,
        "save": False,
        "verbose": False,
    }
    if str(args.device or "").strip():
        predict_args["device"] = str(args.device).strip()
    publish_phase("INFERENCING")
    results = model.predict(**predict_args)
    publish_phase("GENERATING_RESULT")
    result = results[0]
    speed = getattr(result, "speed", {}) or {}
    names = result.names
    detections = []
    img = Image.open(args.input).convert("RGB")
    draw = ImageDraw.Draw(img)
    for box in result.boxes:
        xyxy = [float(x) for x in box.xyxy[0].tolist()]
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
        draw.rectangle([x1, y1, x2, y2], outline=(21, 132, 255), width=3)
        text = f"{label} {score:.2f}"
        draw.rectangle([x1, max(0, y1 - 24), x1 + min(360, len(text) * 12 + 10), y1], fill=(21, 132, 255))
        draw.text((x1 + 4, max(0, y1 - 21)), text, fill=(255, 255, 255))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output, quality=92)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    print(json.dumps({
        "ok": True,
        "detections": detections,
        "preprocess_ms": round(float(speed.get("preprocess") or 0), 2),
        "inference_ms": round(float(speed.get("inference") or 0), 2),
        "postprocess_ms": round(float(speed.get("postprocess") or 0), 2),
        "elapsed_ms": elapsed_ms,
        "engine": "ultralytics",
        "model": Path(args.model).name,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
