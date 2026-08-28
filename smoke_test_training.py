from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    from ultralytics import YOLO
    import torch
    import ultralytics

    root = Path(tempfile.mkdtemp(prefix="xjalgo_train_smoke_"))
    try:
        for split in ["train", "val"]:
            (root / "images" / split).mkdir(parents=True, exist_ok=True)
            (root / "labels" / split).mkdir(parents=True, exist_ok=True)
        # Four deterministic synthetic detection samples. The goal is pipeline validation, not accuracy.
        samples = [("train", 0), ("train", 1), ("train", 2), ("val", 3)]
        for split, idx in samples:
            im = Image.new("RGB", (128, 128), "white")
            d = ImageDraw.Draw(im)
            x1, y1, x2, y2 = 30 + idx, 28, 92, 96
            d.rectangle((x1, y1, x2, y2), outline="black", width=3)
            name = f"sample_{idx}.jpg"
            im.save(root / "images" / split / name)
            xc=((x1+x2)/2)/128; yc=((y1+y2)/2)/128; w=(x2-x1)/128; h=(y2-y1)/128
            (root / "labels" / split / f"sample_{idx}.txt").write_text(f"0 {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n", encoding="utf-8")
        yaml_path = root / "data.yaml"
        yaml_path.write_text(f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: object\n", encoding="utf-8")
        out = root / "runs"
        model = YOLO("yolo11n.yaml")
        model.train(data=str(yaml_path), epochs=1, imgsz=128, batch=2, device="cpu", workers=0, project=str(out), name="smoke", exist_ok=True, verbose=False, plots=False)
        best = out / "smoke" / "weights" / "best.pt"
        if not best.exists():
            raise RuntimeError("未生成 best.pt")
        verified = YOLO(str(best))
        sample = root / "images" / "val" / "sample_3.jpg"
        predictions = verified.predict(source=str(sample), imgsz=128, device="cpu", verbose=False)
        if not predictions:
            raise RuntimeError("best.pt 推理没有返回结果对象")
        exported = verified.export(format="onnx", imgsz=128, batch=1, device="cpu", simplify=True)
        onnx_path = Path(str(exported))
        if not onnx_path.exists() or onnx_path.suffix.lower() != ".onnx":
            raise RuntimeError(f"ONNX 导出失败：{exported}")
        result = {
            "ok": True, "torch": torch.__version__, "ultralytics": ultralytics.__version__,
            "best_pt": str(best), "best_size": best.stat().st_size,
            "inference_ok": True, "onnx": str(onnx_path), "onnx_size": onnx_path.stat().st_size,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
