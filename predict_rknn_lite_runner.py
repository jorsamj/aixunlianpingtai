"""Minimal Rockchip board runtime verification runner using RKNN-Toolkit-Lite2.

This runner proves that an already-converted .rknn model can be loaded,
RKNN Runtime can initialize the NPU, and at least one real inference completes.
It does not claim detection accuracy or decode model-specific YOLO outputs.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--input-size", required=True, type=int)
    parser.add_argument("--chip", required=True)
    args = parser.parse_args()

    model = Path(args.model).expanduser().resolve()
    image_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if model.suffix.lower() != ".rknn" or not model.is_file() or model.stat().st_size <= 0:
        raise SystemExit("RKNN model is missing or invalid")
    if not image_path.is_file() or image_path.stat().st_size <= 0:
        raise SystemExit("verification image is missing or empty")
    if args.input_size < 32 or args.input_size > 4096:
        raise SystemExit("input-size is out of range")
    chip = str(args.chip or "").strip().lower()
    if chip not in {"rk3568", "rk3576"}:
        raise SystemExit("unsupported Rockchip verification target")

    try:
        import numpy as np
        from PIL import Image
        from rknnlite.api import RKNNLite
    except Exception as error:
        raise SystemExit(f"RKNNLite runtime dependencies unavailable: {error}")

    runtime = RKNNLite()
    try:
        started = time.perf_counter()
        ret = runtime.load_rknn(str(model))
        if ret not in (None, 0):
            raise RuntimeError(f"RKNNLite.load_rknn failed: {ret}")
        load_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        ret = runtime.init_runtime()
        if ret not in (None, 0):
            raise RuntimeError(f"RKNNLite.init_runtime failed: {ret}")
        init_ms = (time.perf_counter() - started) * 1000.0

        image = Image.open(image_path).convert("RGB")
        resized = image.resize((args.input_size, args.input_size))
        tensor = np.asarray(resized, dtype=np.uint8)
        tensor = np.expand_dims(tensor, axis=0)

        started = time.perf_counter()
        outputs = runtime.inference(inputs=[tensor])
        inference_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(outputs, (list, tuple)) or not outputs:
            raise RuntimeError("RKNNLite inference returned no outputs")

        output_shapes = []
        for item in outputs[:32]:
            shape = list(getattr(item, "shape", ()) or ())
            output_shapes.append([int(value) for value in shape[:8]])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="JPEG", quality=90)

        print(json.dumps({
            "ok": True,
            "engine": "rknn-lite2",
            "runtime_format": "rknn",
            "chip": chip,
            "model": model.name,
            "preprocess_ms": round(load_ms + init_ms, 3),
            "inference_ms": round(inference_ms, 3),
            "output_count": len(outputs),
            "output_shapes": output_shapes,
            "note": "hardware runtime verification only; output decoding/accuracy is not evaluated",
        }, ensure_ascii=False))
        return 0
    finally:
        try:
            runtime.release()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
