# -*- coding: utf-8 -*-
"""独立 Ultralytics 测试执行器。
由平台后端用指定 Python 环境调用，避免平台自身环境缺少 ultralytics 时测试失败。
"""
import argparse
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()

    start = time.perf_counter()
    model = YOLO(args.model)
    results = model.predict(source=args.input, conf=args.conf, save=False, verbose=False)
    result = results[0]
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
    print(json.dumps({"ok": True, "detections": detections, "elapsed_ms": elapsed_ms, "engine": "ultralytics", "model": Path(args.model).name}, ensure_ascii=False))


if __name__ == "__main__":
    main()
