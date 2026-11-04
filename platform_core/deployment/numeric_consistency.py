"""Offline PT/ONNX numerical comparison on identical real image tensors.

This is not a BMODEL hardware inference test or an accuracy evaluation.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def compare_tensors(reference, converted, *, precision: str = "fp32") -> dict:
    import numpy as np

    a, b = np.asarray(reference), np.asarray(converted)
    if a.shape != b.shape or not a.size or not b.size:
        return {"comparable": False, "reason": "输出形状不一致或输出为空", "pt_shape": list(a.shape), "onnx_shape": list(b.shape)}
    if not np.issubdtype(a.dtype, np.number) or not np.issubdtype(b.dtype, np.number):
        return {"comparable": False, "reason": "输出包含非数值张量"}
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return {"comparable": False, "reason": "输出包含 NaN 或 Infinity"}
    x, y = a.astype(np.float64).ravel(), b.astype(np.float64).ravel()
    delta = np.abs(x - y)
    denominator = np.linalg.norm(x) * np.linalg.norm(y)
    cosine = float(np.dot(x, y) / denominator) if denominator > 0 else (1.0 if np.array_equal(x, y) else 0.0)
    normalized_mae = float(delta.mean() / max(float(np.mean(np.abs(x))), 1e-6))
    limit = {"fp32": 0.005, "fp16": 0.05, "bf16": 0.07}.get(str(precision).lower())
    if limit is None:
        return {"comparable": False, "reason": f"目标精度 {precision} 尚无可信数值容差协议，不得判定一致",
                "shape": list(a.shape), "element_count": int(a.size)}
    return {
        "comparable": True,
        "shape": list(a.shape), "element_count": int(a.size),
        "mean_abs_error": float(delta.mean()),
        "p95_abs_error": float(np.percentile(delta, 95)),
        "max_abs_error": float(delta.max()),
        "normalized_mae": normalized_mae,
        "cosine_similarity": cosine,
        "within_tolerance": normalized_mae <= limit and cosine >= 0.999,
        "normalized_mae_limit": limit,
    }


def make_input(image_path: Path, height: int, width: int):
    """YOLO-style rectangular letterbox, RGB, 0..1, NCHW. No augmentation."""
    import numpy as np
    from PIL import Image

    with Image.open(image_path) as im:
        image = im.convert("RGB")
        original_w, original_h = image.size
        ratio = min(width / original_w, height / original_h)
        new_w = max(1, round(original_w * ratio))
        new_h = max(1, round(original_h * ratio))
        image = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
        pixels = np.full((height, width, 3), 114, dtype=np.uint8)
        x = round((width - new_w) / 2 - 0.1)
        y = round((height - new_h) / 2 - 0.1)
        pixels[y:y + new_h, x:x + new_w] = np.asarray(image)
    return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None].astype(np.float32) / 255.0)


def _primary_pt_output(value):
    if isinstance(value, (tuple, list)):
        value = value[0]
    if not hasattr(value, "detach"):
        raise ValueError("PT 模型没有返回可比较的原始数值张量")
    return value.detach().cpu().numpy()


def _simulate_bmodel(input_tensor, input_name: str, model: Path, python_path: str):
    """Use Sophon's official model_runner when present, not tpu hardware."""
    import numpy as np

    runner = Path(__file__).resolve().parents[2] / "conversion_sophon_offline_runner.py"
    executable = shutil.which(python_path) if python_path else None
    if not executable or not runner.is_file():
        raise RuntimeError("未配置本机可用的 Sophon SDK Python／模型模拟器")
    with tempfile.TemporaryDirectory(prefix="sophon-numeric-") as temp:
        directory = Path(temp)
        input_file, output_file = directory / "input.npz", directory / "output.npz"
        np.savez(input_file, **{input_name: input_tensor})
        process = subprocess.run(
            [executable, str(runner), "--model", str(model), "--input", str(input_file), "--output", str(output_file)],
            cwd=str(directory), capture_output=True, text=True, timeout=180, check=False,
        )
        if process.returncode or not output_file.is_file():
            raise RuntimeError("Sophon 官方离线模拟器不可用或执行失败：" + (process.stderr or process.stdout or "无输出")[-300:])
        with np.load(output_file, allow_pickle=False) as data:
            if len(data.files) != 1:
                raise ValueError("Sophon 模拟器返回多输出，当前无法安全映射到 ONNX 单输出")
            return data[data.files[0]].copy()


def validate_paths(source_path: Path, onnx_path: Path, images: list[Path], *, expected_source_sha: str = "", expected_onnx_sha: str = "") -> None:
    if source_path.suffix.lower() not in {".pt", ".pth"}:
        raise ValueError("源模型不是 PT，无法执行 PT／ONNX 双端数值比较")
    if onnx_path.suffix.lower() != ".onnx":
        raise ValueError("转换产物缺少 ONNX 中间模型")
    for path in [source_path, onnx_path, *images]:
        if not path.is_file():
            raise FileNotFoundError(f"验证输入已不存在：{path.name}")
    if not images:
        raise ValueError("至少选择一张真实图片进行数值验证")
    for candidate,expected,label in ((source_path, expected_source_sha, "源 PT"),(onnx_path,expected_onnx_sha,"ONNX")):
        if expected:
            hasher = hashlib.sha256()
            with candidate.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
            if hasher.hexdigest() != expected:
                raise ValueError(f"{label} SHA256 不一致，拒绝对错误的模型出具报告")


def verify_images(source_path: Path, onnx_path: Path, images: list[Path], *, precision: str, expected_source_sha: str = "", expected_onnx_sha: str = "", input_color_order: str = "rgb", bmodel_path: Path | None = None, bmodel_sha256: str = "", bmodel_expected: bool = False, sophon_python: str = "", progress=None) -> dict:
    validate_paths(source_path, onnx_path, images, expected_source_sha=expected_source_sha, expected_onnx_sha=expected_onnx_sha)
    if str(input_color_order).lower() != "rgb":
        raise ValueError("该产物使用非 RGB 输入颜色适配；当前原始张量核验仅支持 RGB 同输入，不能冒充通过")
    if bmodel_path and bmodel_path.is_file():
        if bmodel_sha256:
            digest = hashlib.sha256()
            with bmodel_path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != bmodel_sha256:
                raise ValueError("BMODEL SHA256 与转换产物不一致，不能出具数值报告")
    import numpy as np
    import onnxruntime as ort
    import torch
    from ultralytics import YOLO

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    if len(inputs) != 1 or len(session.get_outputs()) != 1:
        raise ValueError("ONNX 输入／输出不是单张量；暂不能进行可靠的原始输出对齐")
    input_meta = inputs[0]
    shape = list(input_meta.shape)
    if len(shape) != 4 or shape[1] != 3:
        raise ValueError("ONNX 输入不符合单图 NCHW 三通道合同")
    height = shape[2] if isinstance(shape[2], int) else 640
    width = shape[3] if isinstance(shape[3], int) else 640
    if not (32 <= height <= 4096 and 32 <= width <= 4096):
        raise ValueError("ONNX 输入尺寸不在可安全验证范围内")
    pt = YOLO(str(source_path)).model.cpu().eval().float()
    results = []
    simulator_error = "BMODEL 文件不存在或未在当前转换产物目录中" if (bmodel_expected or bmodel_path) and (not bmodel_path or not bmodel_path.is_file()) else ""
    for i, image in enumerate(images):
        tensor = make_input(image, height, width)
        with torch.inference_mode():
            reference = _primary_pt_output(pt(torch.from_numpy(tensor)))
        dtype = np.float16 if input_meta.type == "tensor(float16)" else np.float32
        converted = session.run(None, {input_meta.name: tensor.astype(dtype)})[0]
        metrics = compare_tensors(reference, converted, precision=precision)
        if bmodel_path and bmodel_path.is_file() and not simulator_error:
            try:
                bmodel_output = _simulate_bmodel(tensor, input_meta.name, bmodel_path, sophon_python)
                metrics["onnx_bmodel"] = compare_tensors(converted, bmodel_output, precision=precision)
            except Exception as error:
                simulator_error = str(error)
        results.append({"image": image.name, **metrics})
        if progress:
            progress(i + 1, len(images))
    compatible = all(row.get("comparable") for row in results)
    matching = compatible and all(row.get("within_tolerance") for row in results)
    bmodel_requested = bool(bmodel_expected or bmodel_path)
    bmodel_compared = bool(bmodel_path and bmodel_path.is_file()) and all(row.get("onnx_bmodel", {}).get("comparable") for row in results)
    bmodel_matching = bmodel_compared and all(row["onnx_bmodel"].get("within_tolerance") for row in results)
    return {
        "protocol": "pt-onnx-raw-tensor-v1",
        "verdict": "consistent" if matching else ("difference_detected" if compatible else "not_comparable"),
        "status": "completed", "sample_count": len(results), "precision": precision,
        "source": "PT", "compared": "ONNX", "bmodel_verified": False,
        "hardware_verified": False, "ground_truth_used": False,
        "bmodel_numeric_status": "consistent" if bmodel_matching else ("difference_detected" if bmodel_compared else "unavailable" if bmodel_requested else "not_applicable"),
        "bmodel_numeric_error": simulator_error,
        "scope_note": "同图 RGB Letterbox 输入下比较 PT／ONNX 原始张量；若本机存在 Sophon 官方模拟器则另行比较 ONNX／BMODEL，模拟器不代表板端实机或场景准确率。",
        "images": results,
    }


def run_verification_directory(directory: Path) -> None:
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    result_path = directory / "result.json"

    def record(value):
        result_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def progress(done, total):
        record({"status": "running", "progress": round(100 * done / total, 2), "stage": f"正在比较 {done}/{total} 张图片"})

    try:
        record({"status": "running", "progress": 2, "stage": "加载 PT 和 ONNX 推理运行时"})
        result = verify_images(
            Path(request["source_path"]), Path(request["onnx_path"]),
            [directory / "images" / name for name in request["image_names"]],
            precision=request["precision"], expected_source_sha=request.get("source_sha256", ""),
            expected_onnx_sha=request.get("onnx_sha256", ""),
            input_color_order=request.get("input_color_order", "rgb"),
            bmodel_path=Path(request["bmodel_path"]) if request.get("bmodel_path") else None,
            bmodel_sha256=request.get("bmodel_sha256", ""), bmodel_expected=bool(request.get("bmodel_expected")),
            sophon_python=request.get("sophon_python", ""),
            progress=progress,
        )
        record({**result, "progress": 100, "stage": "数值比较已完成"})
    except Exception as error:
        record({"status": "failed", "progress": 100, "stage": "验证无法完成", "error": str(error), "verdict": "unavailable", "bmodel_verified": False})
        raise
