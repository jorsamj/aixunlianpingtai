"""Real PT -> ONNX -> PT/ONNX numeric comparison for W9 delivery evidence.

Scope: CPU-only, random-weight YOLO11n built from the packaged YAML (no weight
download), deterministic real images inside pytest tmp_path. This is real
execution of the same export/comparison code, not a trained-model accuracy or
board/hardware acceptance run. Hardware and trained-checkpoint quality remain
NOT VERIFIED.
"""
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_MODULES = ("torch", "ultralytics", "onnx", "onnxruntime", "numpy", "cv2", "PIL")
MISSING = []
MODULES = {}
for _name in REQUIRED_MODULES:
    try:
        MODULES[_name] = importlib.import_module(_name)
    except Exception as _error:  # noqa: BLE001 - environment evidence
        MISSING.append(f"{_name}: {type(_error).__name__}: {_error}")
if MISSING:
    _reason = ("NOT VERIFIED: 真实 PT/ONNX 数值比较依赖缺失，未执行任何真实导出或比较 -> "
               + "; ".join(MISSING))
    if os.environ.get("XJALGO_REQUIRE_REAL_PT_ONNX") == "1":
        pytest.fail(_reason, pytrace=False)
    pytest.skip(_reason, allow_module_level=True)

np = MODULES["numpy"]
torch = MODULES["torch"]
YOLO = MODULES["ultralytics"].YOLO
Image = MODULES["PIL"].Image
ort = MODULES["onnxruntime"]

CANONICAL_PREPROCESSING = {
    "owner": "caller", "pixel_format": "rgb", "channel_format": "nchw",
    "resize_interpolation": "opencv_linear", "letterbox_mode": "fixed_shape_center",
    "letterbox": True, "pad_value": 114, "nms": "external",
    "mean": [0.0, 0.0, 0.0], "scale": [1.0 / 255] * 3,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_real_image(path: Path, width: int, height: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    Image.fromarray(pixels, mode="RGB").save(path)


def _run_worker(job_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"), "--job-dir", str(job_dir)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600,
    )


@pytest.fixture(scope="module")
def real_conversion(tmp_path_factory):
    """Build random weights from the packaged YAML, then use the real worker export."""
    base = tmp_path_factory.mktemp("real-pt-onnx")
    job_dir = base / "job"
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    model = YOLO("yolo11n.yaml")
    source = source_dir / "yolo11n-random.pt"
    model.save(str(source))
    source_sha = _sha256(source)
    job = {
        "id": "real-pt-onnx-numeric",
        "status": "queued",
        "target": "onnx",
        "source_id": "local-yolo11n-random",
        "source_path": str(source),
        "source_trace": {"source_id": "local-yolo11n-random", "sha256": source_sha},
        "resource": {"id": "builtin_ultralytics", "name": "Ultralytics", "python_path": sys.executable},
        "params": {
            "input_size": 96, "batch": 1, "opset": 12, "dynamic": False,
            "simplify": False, "precision": "fp32",
            "input_color_order": "rgb", "source_color_order": "rgb",
            "preprocessing": dict(CANONICAL_PREPROCESSING),
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    completed = _run_worker(job_dir)
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-12000:]
    final_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert final_job["status"] == "done", final_job
    manifest = json.loads(Path(final_job["manifest_path"]).read_text(encoding="utf-8"))
    onnx_name = next(row["name"] for row in manifest["outputs"] if row["name"].endswith(".onnx"))
    images = base / "images"
    images.mkdir()
    _write_real_image(images / "wide.png", 240, 120, 11)
    _write_real_image(images / "narrow.png", 97, 61, 12)
    return {
        "base": base, "job_dir": job_dir, "source": source, "source_sha": source_sha,
        "final_job": final_job, "manifest": manifest,
        "onnx": job_dir / "artifacts" / onnx_name,
        "onnx_sha": manifest["onnx"]["sha256"],
        "images": [images / "wide.png", images / "narrow.png"],
    }


@pytest.fixture(scope="module")
def real_numeric(real_conversion):
    from platform_core.deployment.numeric_consistency import verify_images
    return verify_images(
        real_conversion["source"], real_conversion["onnx"], real_conversion["images"],
        precision="fp32",
        expected_source_sha=real_conversion["source_sha"],
        expected_onnx_sha=real_conversion["onnx_sha"],
        input_color_order="rgb",
        preprocessing=dict(CANONICAL_PREPROCESSING),
        input_shapes=real_conversion["manifest"]["onnx"]["input_shapes"],
        frozen_imgsz=real_conversion["manifest"]["source_manifest"]["export"]["imgsz"],
        # Random PyTorch initialization yields class scores around 1.6e-4.
        # A lowered comparison threshold only exercises the real box decode;
        # deployment confidence thresholds are NOT validated by this evidence.
        confidence=0.00001,
        nms_iou=0.7,
    )


def test_real_conversion_freezes_onnx_io_and_source_manifest_digest(real_conversion):
    from platform_core.conversion import verify_source_manifest_digest
    manifest = real_conversion["manifest"]
    final_job = real_conversion["final_job"]
    assert manifest["onnx"]["checker"] == "passed"
    assert manifest["onnx"]["runtime"] == "onnxruntime"
    assert manifest["onnx"]["input_shapes"] == [[1, 3, 96, 96]]
    assert manifest["onnx"]["output_shapes"] == [[1, 84, 189]]
    assert manifest["onnx"]["output_types"] == ["tensor(float)"]
    assert manifest["onnx"]["output_inferred_shapes"] == [[1, 84, 189]]
    assert manifest["onnx"]["output_dtypes"] == ["float32"]
    assert manifest["hardware_verified"] is False
    integrity = verify_source_manifest_digest(manifest)
    assert integrity["present"] and integrity["valid"], integrity
    assert len(manifest["manifest_digest"]) == 64
    document = manifest["source_manifest"]
    assert document["schema_version"] == 1
    assert document["source"]["sha256"] == real_conversion["source_sha"]
    assert document["source"]["file_name"] == "yolo11n-random.pt"
    assert document["source"]["sha256_recheck"]["status"] == "matched"
    assert document["onnx"]["sha256"] == real_conversion["onnx_sha"] == _sha256(real_conversion["onnx"])
    assert document["export"]["opset"] == 12
    assert document["export"]["batch"] == 1
    assert document["export"]["imgsz"] == [96, 96]
    assert document["export"]["dynamic"] is False
    assert document["export"]["precision"] == "fp32"
    assert document["tool"]["name"] == "ultralytics-export"
    dependencies = document["tool"]["dependencies"]
    assert dependencies["torch"] == torch.__version__
    assert dependencies["ultralytics"] == MODULES["ultralytics"].__version__
    assert final_job["manifest_digest"] == manifest["manifest_digest"]
    assert final_job["source_sha256_recheck"]["status"] == "matched"
    evidence = final_job["execution_evidence"]
    assert evidence["onnx_output_shapes"] == [[1, 84, 189]]
    assert evidence["onnx_output_dtypes"] == ["float32"]
    assert evidence["manifest_digest"] == manifest["manifest_digest"]
    # Tampering with the frozen source/ONNX identity must invalidate the digest.
    tampered = json.loads(json.dumps(manifest))
    tampered["source_manifest"]["onnx"]["sha256"] = "0" * 64
    assert verify_source_manifest_digest(tampered)["valid"] is False


def test_real_pt_onnx_numeric_metrics_and_detection_evidence(real_numeric):
    result = real_numeric
    assert result["status"] == "completed"
    assert result["sample_count"] == 2
    assert result["hardware_verified"] is False
    assert result["ground_truth_used"] is False
    assert result["bmodel_verified"] is False
    assert result["input_color_space"] == "rgb"
    assert result["verdict"] == "consistent", result.get("label_identity")
    assert result["input_contract"]["status"] == "resolved"
    assert result["input_contract"]["input_shape_source"] == "frozen_manifest"
    assert result["dynamic_resolution"] == "static"
    # Real imported runtime versions, never fabricated.
    for name in ("torch", "ultralytics", "onnx", "onnxruntime", "numpy", "cv2"):
        observed = result["runtime_versions"][name]
        expected = getattr(MODULES[name], "__version__", None)
        assert observed["version"] == expected and observed["error"] is None, (name, observed)
    for row in result["images"]:
        assert row["comparable"] is True and row["within_tolerance"] is True
        assert row["element_count"] == 84 * 189
        assert row["mean_abs_error"] >= 0
        assert row["p95_abs_error"] >= 0
        assert row["max_abs_error"] >= 0
        assert 0.999 <= row["cosine_similarity"] <= 1.0
        assert row["normalized_mae"] <= row["normalized_mae_limit"]
        detection = row["detection"]
        assert detection["comparable"] is True
        assert detection["within_tolerance"] is True
        assert detection["class_count"] == 80
        assert detection["matched_pairs"] == detection["after_nms_reference"] == detection["after_nms_converted"]
        assert detection["mean_matched_iou"] is not None and detection["mean_matched_iou"] >= 0.95
        assert isinstance(detection["per_class"], list) and detection["per_class"]
        for class_row in detection["per_class"]:
            assert class_row["reference_boxes"] == class_row["converted_boxes"]
            assert class_row["unmatched_reference"] == class_row["unmatched_converted"] == 0
        assert detection["reference_detections"] and detection["converted_detections"]
        for entry in detection["reference_detections"] + detection["converted_detections"]:
            assert len(entry["box_xyxy_input"]) == 4
            assert entry["box_xyxy"] == entry["box_xyxy_input"]
            assert "box_xyxy_original" in entry
            original = entry["box_xyxy_original"]
            if original is not None:
                width, height = row["original_size"]
                assert 0 <= original[0] < original[2] <= width
                assert 0 <= original[1] < original[3] <= height
            else:
                assert entry["coordinate_error"]
        coordinates = detection["original_coordinates"]
        assert coordinates["status"] in {"mapped", "partial", "unmapped"}
        assert coordinates["mapped"] + coordinates["unmapped"] == (
            len(detection["reference_detections"]) + len(detection["converted_detections"]))
    wide, narrow = result["images"]
    assert wide["original_size"] == [240, 120]
    assert wide["input_geometry"] == {
        "width": 96, "height": 96, "scale_x": 0.4, "scale_y": 0.4,
        "pad_x": 0.0, "pad_y": 24.0, "crop_x": 0.0, "crop_y": 0.0,
    }
    assert narrow["original_size"] == [97, 61]
    assert narrow["input_geometry"]["pad_y"] == 18.0


def test_real_geometry_restores_in_bounds_boxes_to_original_pixels(real_conversion):
    """Use the real exported ONNX layout and real LetterBox geometry for the mapping."""
    from platform_core.auto_label import adapt_coordinates
    from platform_core.deployment.numeric_consistency import (
        compare_yolo_detections, make_input_with_geometry,
    )

    image = real_conversion["images"][0]  # 240x120 wide image
    prepared = make_input_with_geometry(image, 96, 96)
    geometry, original_size = prepared["geometry"], prepared["original_size"]
    session = ort.InferenceSession(str(real_conversion["onnx"]), providers=["CPUExecutionProvider"])
    input_meta = session.get_inputs()[0]
    raw = session.run(None, {input_meta.name: prepared["tensor"].astype(np.float32)})[0]
    class_count = raw.shape[1] - 4
    candidates = np.zeros((1, raw.shape[1], raw.shape[2]), dtype=np.float32)
    # Content region in the 96x96 LetterBox is y=24..72; this box stays inside it.
    candidates[0, 0:4, 0] = [48.0, 48.0, 16.0, 16.0]  # center XYWH in input pixels
    candidates[0, 4 + min(5, class_count - 1), 0] = 0.9
    compared = compare_yolo_detections(
        candidates, candidates.copy(), class_count=class_count, confidence=0.25,
        geometry=geometry, original_size=original_size,
    )
    assert compared["comparable"] and compared["within_tolerance"]
    assert compared["after_nms_reference"] == compared["after_nms_converted"] == 1
    entry = compared["reference_detections"][0]
    assert entry["box_xyxy_input"] == [40.0, 40.0, 56.0, 56.0]
    expected = adapt_coordinates(
        [40.0, 40.0, 56.0, 56.0], width=original_size[0], height=original_size[1],
        coordinate_space="pixel", coordinate_order="xyxy", coordinate_origin="top_left",
        geometry=geometry,
    )
    assert entry["box_xyxy_original"] == [round(float(value), 3) for value in expected]
    assert entry["box_xyxy_original"] == [100.0, 40.0, 140.0, 80.0]
    assert 0 <= entry["box_xyxy_original"][0] < entry["box_xyxy_original"][2] <= 240
    assert 0 <= entry["box_xyxy_original"][1] < entry["box_xyxy_original"][3] <= 120
    assert entry["coordinate_error"] == ""
    assert compared["original_coordinates"]["status"] == "mapped"
    assert compared["original_coordinates"]["mapped"] == 2
    assert compared["original_coordinates"]["unmapped"] == 0
    assert compared["original_coordinates"]["geometry"] == geometry


@pytest.fixture(scope="module")
def real_dynamic_conversion(tmp_path_factory):
    """Real dynamic-shape export: the comparison may only use explicitly frozen sizes."""
    base = tmp_path_factory.mktemp("real-pt-onnx-dynamic")
    job_dir = base / "job"
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    model = YOLO("yolo11n.yaml")
    source = source_dir / "yolo11n-random.pt"
    model.save(str(source))
    source_sha = _sha256(source)
    job = {
        "id": "real-pt-onnx-numeric-dynamic", "status": "queued", "target": "onnx",
        "source_id": "local-yolo11n-random", "source_path": str(source),
        "source_trace": {"source_id": "local-yolo11n-random", "sha256": source_sha},
        "resource": {"id": "builtin_ultralytics", "name": "Ultralytics", "python_path": sys.executable},
        "params": {
            "input_size": 96, "batch": 1, "opset": 12, "dynamic": True,
            "simplify": False, "precision": "fp32",
            "input_color_order": "rgb", "source_color_order": "rgb",
            "preprocessing": dict(CANONICAL_PREPROCESSING),
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    completed = _run_worker(job_dir)
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-12000:]
    final_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert final_job["status"] == "done", final_job
    manifest = json.loads(Path(final_job["manifest_path"]).read_text(encoding="utf-8"))
    onnx_name = next(row["name"] for row in manifest["outputs"] if row["name"].endswith(".onnx"))
    image = base / "dynamic.png"
    _write_real_image(image, 160, 90, 21)
    return {"source": source, "source_sha": source_sha, "final_job": final_job,
            "manifest": manifest, "onnx": job_dir / "artifacts" / onnx_name,
            "onnx_sha": manifest["onnx"]["sha256"], "image": image, "base": base}


def test_real_dynamic_onnx_uses_frozen_imgsz_and_never_silent_640(real_dynamic_conversion):
    from platform_core.deployment.numeric_consistency import verify_images

    frozen = real_dynamic_conversion
    graph_shape = frozen["manifest"]["onnx"]["input_shapes"]
    assert any(not isinstance(dim, int) for row in graph_shape for dim in row), graph_shape
    assert frozen["manifest"]["source_manifest"]["export"]["dynamic"] is True
    arguments = dict(
        precision="fp32",
        expected_source_sha=frozen["source_sha"],
        expected_onnx_sha=frozen["onnx_sha"],
        input_color_order="rgb",
        preprocessing=dict(CANONICAL_PREPROCESSING),
        input_shapes=graph_shape,
        confidence=0.00001,
    )
    refused = verify_images(frozen["source"], frozen["onnx"], [frozen["image"]], **arguments)
    assert refused["status"] == "completed"
    assert refused["verdict"] == "not_comparable"
    assert refused["rejection"]["code"] in {
        "DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ", "DYNAMIC_BATCH_WITHOUT_FROZEN_BATCH"}
    assert refused["dynamic_resolution"] == "not_comparable"
    assert refused["sample_count"] == 0
    assert refused["hardware_verified"] is False
    # With the batch explicitly frozen but no imgsz, the spatial refusal is the
    # explicit no-silent-640 code rather than any fabricated size.
    spatial_refusal = verify_images(
        frozen["source"], frozen["onnx"], [frozen["image"]], **arguments,
        frozen_batch=frozen["final_job"]["params"]["batch"],
    )
    assert spatial_refusal["verdict"] == "not_comparable"
    assert spatial_refusal["rejection"]["code"] == "DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ"
    assert "640" in spatial_refusal["rejection"]["reason"]

    frozen_result = verify_images(
        frozen["source"], frozen["onnx"], [frozen["image"]], **arguments,
        frozen_imgsz=frozen["manifest"]["source_manifest"]["export"]["imgsz"],
        frozen_batch=frozen["final_job"]["params"]["batch"],
    )
    assert frozen_result["status"] == "completed"
    assert frozen_result["verdict"] == "consistent", frozen_result.get("label_identity")
    assert frozen_result["dynamic_resolution"] == "frozen_imgsz"
    assert frozen_result["dynamic_resolution_reason"]
    assert frozen_result["input_contract"]["resolved_input_shape"] == [1, 3, 96, 96]
    assert frozen_result["input_contract"]["batch_source"] == "frozen_batch"
    assert frozen_result["sample_count"] == 1
    row = frozen_result["images"][0]
    assert row["comparable"] is True and row["detection"]["comparable"] is True
    assert row["cosine_similarity"] >= 0.999
    assert row["original_size"] == [160, 90]
    assert frozen_result["hardware_verified"] is False
    assert frozen_result["runtime_versions"]["onnxruntime"]["version"] == MODULES["onnxruntime"].__version__
