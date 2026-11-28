"""Real PT -> ONNX -> PT/ONNX numeric comparison for W9 delivery evidence.

Scope: CPU-only, random-weight YOLO11n built from the packaged YAML (no weight
download), deterministic real images inside pytest tmp_path. This is real
execution of the same export/comparison/evidence code, not a trained-model
accuracy or board/hardware acceptance run. Hardware and trained-checkpoint
quality remain NOT VERIFIED.

N5.1: the real matrix covers FP32 / FP16 / opset 11+12 / static / dynamic input /
frozen imgsz / simplify (when onnxslim is importable), with onnx.checker, a real
ONNX Runtime CPU load, observed input/output dtypes, tensor MAE/P95/cosine and
detection box/class/IoU evidence. A combination that the environment cannot
produce or run is recorded as BLOCKED_BY_ENVIRONMENT / BLOCKED_BY_RUNTIME with
the real error text; it is never silently skipped and reported as verified.
"""
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
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
onnx = MODULES["onnx"]

CANONICAL_PREPROCESSING = {
    "owner": "caller", "pixel_format": "rgb", "channel_format": "nchw",
    "resize_interpolation": "opencv_linear", "letterbox_mode": "fixed_shape_center",
    "letterbox": True, "pad_value": 114, "nms": "external",
    "mean": [0.0, 0.0, 0.0], "scale": [1.0 / 255] * 3,
}
MATRIX_STATUSES = {"VERIFIED", "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_RUNTIME", "NOT_VERIFIED"}
_SIMPLIFIER = next(
    (name for name in ("onnxslim", "onnxsim") if importlib.util.find_spec(name) is not None),
    "",
)


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


def _params(*, precision="fp32", opset=12, dynamic=False, simplify=False) -> dict:
    return {
        "input_size": 96, "batch": 1, "opset": opset, "dynamic": dynamic,
        "simplify": simplify, "precision": precision,
        "input_color_order": "rgb", "source_color_order": "rgb",
        "preprocessing": dict(CANONICAL_PREPROCESSING),
    }


def _run_export_job(
    tmp_path_factory, label: str, *, params: dict, job_id: str = "",
    allow_failure: bool = False,
) -> dict:
    """Create a random-weight PT, then run the real deployment worker export."""
    base = tmp_path_factory.mktemp(label)
    deploy = base / "deployment"
    job_id = job_id or f"{label}-job"
    job_dir = deploy / "jobs" / job_id
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    model = YOLO("yolo11n.yaml")
    source = source_dir / "yolo11n-random.pt"
    model.save(str(source))
    source_sha = _sha256(source)
    job = {
        "id": job_id,
        "project_id": "p1",
        "status": "queued",
        "target": "onnx",
        "source_id": "local-yolo11n-random",
        "source_path": str(source),
        "source_trace": {
            "source_id": "local-yolo11n-random", "sha256": source_sha,
            "algorithm_id": "a1", "version_id": "v1",
        },
        "resource": {"id": "builtin_ultralytics", "name": "Ultralytics", "python_path": sys.executable},
        "params": dict(params),
    }
    (job_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    completed = _run_worker(job_dir)
    final_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    if completed.returncode != 0 or final_job.get("status") != "done":
        # Real exporter/runtime refusal: record the actual error text instead of
        # pretending the combination passed. Only the caller decides whether the
        # environment is allowed to block this combination.
        error_text = (
            f"worker rc={completed.returncode}; status={final_job.get('status')}; "
            f"error={final_job.get('error_code') or ''}: {final_job.get('error') or ''}\n"
            + (completed.stdout + completed.stderr)[-8000:]
        )
        blocked = {
            "label": label, "blocked_by_environment": True, "error": error_text,
            "base": base, "deploy": deploy, "job_dir": job_dir,
            "job_id": job_id, "final_job": final_job,
        }
        assert allow_failure, error_text
        return blocked
    manifest = json.loads(Path(final_job["manifest_path"]).read_text(encoding="utf-8"))
    onnx_name = next(row["name"] for row in manifest["outputs"] if row["name"].endswith(".onnx"))
    images = base / "images"
    images.mkdir()
    _write_real_image(images / "wide.png", 240, 120, 11)
    _write_real_image(images / "narrow.png", 97, 61, 12)
    return {
        "label": label, "base": base, "deploy": deploy, "job_dir": job_dir,
        "job_id": job_id, "source": source, "source_sha": source_sha,
        "final_job": final_job, "manifest": manifest,
        "onnx": job_dir / "artifacts" / onnx_name,
        "onnx_sha": manifest["onnx"]["sha256"],
        "images": [images / "wide.png", images / "narrow.png"],
        # The worker keeps the untouched exporter output next to its repaired copy.
        "raw_export": job_dir / "work" / f"{source.stem}.onnx",
    }


def _verify_real(layout: dict, *, precision: str, dynamic: bool = False, nms_iou: float = 0.7) -> dict:
    from platform_core.deployment.numeric_consistency import verify_images
    export = layout["manifest"]["source_manifest"]["export"]
    return verify_images(
        layout["source"], layout["onnx"], layout["images"],
        precision=precision,
        expected_source_sha=layout["source_sha"],
        expected_onnx_sha=layout["onnx_sha"],
        input_color_order="rgb",
        preprocessing=dict(CANONICAL_PREPROCESSING),
        input_shapes=layout["manifest"]["onnx"]["input_shapes"],
        frozen_imgsz=export["imgsz"],
        frozen_batch=1 if dynamic else None,
        # Random PyTorch initialization yields class scores around 1.6e-4.
        # A lowered comparison threshold only exercises the real box decode;
        # deployment confidence thresholds are NOT validated by this evidence.
        confidence=0.00001,
        nms_iou=nms_iou,
    )


def _publish_numeric_evidence(layout: dict, *, label: str) -> dict:
    """Run the real evidence-first verification directory path for one export."""
    from platform_core.deployment.numeric_consistency import run_verification_directory

    deploy = layout["deploy"]
    verification = deploy / "numeric-validations" / f"nv_real_{label}"
    images_dir = verification / "images"
    images_dir.mkdir(parents=True)
    names = []
    for index, image in enumerate(layout["images"]):
        name = f"image_{index:02d}.png"
        shutil.copy2(image, images_dir / name)
        names.append(name)
    export = layout["manifest"]["source_manifest"]["export"]
    request = {
        "id": verification.name, "project_id": "p1",
        "conversion_job_id": layout["job_id"],
        "request_id": f"req-real-{label}-0001",
        "source_path": str(layout["source"]), "onnx_path": str(layout["onnx"]),
        "source_sha256": layout["source_sha"], "onnx_sha256": layout["onnx_sha"],
        "bmodel_path": "", "bmodel_sha256": "", "bmodel_expected": False,
        "precision": export["precision"], "confidence": 0.00001, "nms_iou": 0.7,
        "input_color_order": "rgb", "preprocessing": dict(CANONICAL_PREPROCESSING),
        "input_shapes": layout["manifest"]["onnx"]["input_shapes"],
        "frozen_imgsz": export["imgsz"], "frozen_batch": 1,
        "label_codes": None, "label_schema": None, "image_names": names,
    }
    (verification / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    final = run_verification_directory(verification)
    result = json.loads((verification / "result.json").read_text(encoding="utf-8"))
    return {"verification": verification, "request": request, "final": final, "result": result}


@pytest.fixture(scope="module")
def real_conversion(tmp_path_factory):
    """Build random weights from the packaged YAML, then use the real worker export."""
    return _run_export_job(
        tmp_path_factory, "real-pt-onnx-fp32", params=_params(), job_id="real-pt-onnx-numeric",
    )


@pytest.fixture(scope="module")
def real_numeric(real_conversion):
    return _verify_real(real_conversion, precision="fp32")


@pytest.fixture(scope="module")
def real_fp16_conversion(tmp_path_factory):
    return _run_export_job(
        tmp_path_factory, "real-pt-onnx-fp16", params=_params(precision="fp16"),
        job_id="real-pt-onnx-fp16", allow_failure=True,
    )


@pytest.fixture(scope="module")
def real_fp16_evidence(real_fp16_conversion):
    if real_fp16_conversion.get("blocked_by_environment"):
        return {"conversion": real_fp16_conversion,
                "blocked_by_environment": True, "error": real_fp16_conversion["error"]}
    evidence = _publish_numeric_evidence(real_fp16_conversion, label="fp16")
    published_job = json.loads(
        (real_fp16_conversion["job_dir"] / "job.json").read_text(encoding="utf-8"))
    return {"conversion": real_fp16_conversion, "published_job": published_job, **evidence}


@pytest.fixture(scope="module")
def real_simplify_conversion(tmp_path_factory):
    if not _SIMPLIFIER:
        return {
            "label": "real-pt-onnx-simplify", "blocked_by_environment": True,
            "error": "NOT VERIFIED: 未安装 onnxslim/onnxsim，simplify 组合未执行真实导出",
        }
    return _run_export_job(
        tmp_path_factory, "real-pt-onnx-simplify", params=_params(simplify=True),
        job_id="real-pt-onnx-simplify",
    )


@pytest.fixture(scope="module")
def real_opset11_conversion(tmp_path_factory):
    return _run_export_job(
        tmp_path_factory, "real-pt-onnx-opset11", params=_params(opset=11),
        job_id="real-pt-onnx-opset11",
    )


@pytest.fixture(scope="module")
def real_dynamic_conversion(tmp_path_factory):
    """Real dynamic-shape export: the comparison may only use explicitly frozen sizes."""
    layout = _run_export_job(
        tmp_path_factory, "real-pt-onnx-dynamic", params=_params(dynamic=True),
        job_id="real-pt-onnx-numeric-dynamic",
    )
    image = layout["base"] / "dynamic.png"
    _write_real_image(image, 160, 90, 21)
    return {**layout, "images": [image]}


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
    refused = verify_images(frozen["source"], frozen["onnx"], [frozen["images"][0]], **arguments)
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
        frozen["source"], frozen["onnx"], [frozen["images"][0]], **arguments,
        frozen_batch=frozen["final_job"]["params"]["batch"],
    )
    assert spatial_refusal["verdict"] == "not_comparable"
    assert spatial_refusal["rejection"]["code"] == "DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ"
    assert "640" in spatial_refusal["rejection"]["reason"]

    frozen_result = verify_images(
        frozen["source"], frozen["onnx"], [frozen["images"][0]], **arguments,
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


# ---------------------------------------------------------------------------
# N5.1: real FP16 export -> historical Cast/Conv topology failure -> order-only
# repair -> Checker + real ORT CPU load -> numeric evidence + delivery preflight.
# ---------------------------------------------------------------------------
def test_real_fp16_export_repairs_cast_conv_topology_and_io_dtypes(real_fp16_conversion):
    conversion = real_fp16_conversion
    if conversion.get("blocked_by_environment"):
        # Real attempt failed: the only legal status for this combination is the
        # recorded environment block text, never a fabricated verification.
        assert conversion["error"].strip()
        pytest.skip("FP16 export BLOCKED_BY_ENVIRONMENT: " + conversion["error"][-500:])
    final_job = conversion["final_job"]
    manifest = conversion["manifest"]
    export = manifest["source_manifest"]["export"]
    assert export["precision"] == "fp16" and export["half"] is True
    assert export["opset"] == 12 and export["dynamic"] is False and export["simplify"] is False
    topology = final_job["execution_evidence"]["onnx_topology"]
    assert topology["applied"] is True
    assert topology["status"] == "reordered"
    assert topology["moved_nodes"] > 0
    assert topology["node_count"] > topology["moved_nodes"]
    assert topology["checker"] == "passed"
    assert topology["runtime"] == "passed"
    assert manifest["onnx"]["checker"] == "passed"
    assert manifest["onnx"]["runtime"] == "onnxruntime"
    assert "FLOAT16" in manifest["onnx"]["floating_tensor_types"]
    # The exporter casts float16 compute back to float32 at the graph boundary.
    assert manifest["onnx"]["input_types"] == ["tensor(float)"]
    assert manifest["onnx"]["output_types"] == ["tensor(float)"]
    assert manifest["onnx"]["output_dtypes"] == ["float32"]
    repaired = onnx.load(str(conversion["onnx"]), load_external_data=False)
    onnx.checker.check_model(repaired)
    session = ort.InferenceSession(str(conversion["onnx"]), providers=["CPUExecutionProvider"])
    input_meta = session.get_inputs()[0]
    assert input_meta.type == "tensor(float)"
    output = session.run(
        None, {input_meta.name: np.zeros((1, 3, 96, 96), dtype=np.float32)},
    )[0]
    assert output.shape == (1, 84, 189)
    assert output.dtype == np.float32
    assert np.all(np.isfinite(output))
    # Historical failure evidence: the untouched exporter output really is
    # topologically unsorted in this environment (real checker error recorded).
    raw = conversion["raw_export"]
    raw_error = ""
    if raw.is_file():
        raw_model = onnx.load(str(raw), load_external_data=False)
        try:
            onnx.checker.check_model(raw_model)
        except Exception as error:  # noqa: BLE001 - real environment evidence
            raw_error = f"{type(error).__name__}: {error}"
        assert raw_error, "原始导出文件必须真实经过 Checker；允许通过但需记录"
        assert "topologically sorted" in raw_error or "graph_input_cast" in raw_error
        # The repair only changes node order: node protobuf bytes and all
        # initializers (float16 weights) are preserved byte-for-byte as a multiset.
        assert sorted(node.SerializeToString() for node in raw_model.graph.node) == sorted(
            node.SerializeToString() for node in repaired.graph.node)
        assert [t.SerializeToString() for t in raw_model.graph.initializer] == [
            t.SerializeToString() for t in repaired.graph.initializer]
        assert {t.data_type for t in repaired.graph.initializer} == {onnx.TensorProto.FLOAT16}


def test_real_fp16_numeric_evidence_is_delivery_eligible(real_fp16_evidence):
    from platform_core.deployment.numeric_consistency import assert_delivery_quality_eligibility

    layout = real_fp16_evidence
    if layout.get("blocked_by_environment"):
        pytest.skip("FP16 BLOCKED_BY_ENVIRONMENT: " + layout["error"][-500:])
    result = layout["result"]
    assert result["status"] == "completed"
    assert result["verdict"] == "consistent", result.get("label_identity")
    assert result["raw_verdict"] == "consistent"
    assert result["detection_status"] == "consistent"
    assert result["sample_count"] == 2
    assert result["precision"] == "fp16"
    assert result["hardware_verified"] is False
    assert result["runtime_versions"]["onnxruntime"]["version"] == MODULES["onnxruntime"].__version__
    assert result["status_projection"]["status"] == "projected"
    for row in result["images"]:
        assert row["comparable"] is True and row["within_tolerance"] is True
        assert row["element_count"] == 84 * 189
        assert row["p95_abs_error"] >= 0
        assert 0.999 <= row["cosine_similarity"] <= 1.0
        assert row["normalized_mae"] <= row["normalized_mae_limit"]
        assert row["detection"]["comparable"] is True
        assert row["detection"]["within_tolerance"] is True
        assert row["detection"]["mean_matched_iou"] >= 0.95
    verdict = assert_delivery_quality_eligibility(layout["verification"])
    assert verdict["eligible"] is True, verdict
    assert verdict["code"] == ""
    assert verdict["identity_complete"] is True
    assert verdict["binding_status"] == "verified"
    assert verdict["projection_status"] == "bound"
    assert verdict["sample_set_status"] == "available"
    assert verdict["numeric_status_sufficient_for_eligibility"] is False
    assert verdict["hardware_verified"] is False
    assert verdict["manifest_digest"] == layout["final"]["verification"]["identity"]["manifest_digest"]
    published_job = layout["published_job"]
    assert published_job["numeric_status"] == "consistent"
    assert published_job["numeric_validation"]["verification_id"] == verdict["verification_id"]
    assert published_job["numeric_validation"]["content_digest"] == verdict["content_digest"]
    assert published_job["numeric_validation"]["hardware_verified"] is False


def test_real_fp16_artifact_preflight_is_formal_activation_not_hardware_acceptance(real_fp16_evidence):
    from platform_core.model_artifacts import delivery_artifact_quality_preflight

    layout = real_fp16_evidence
    if layout.get("blocked_by_environment"):
        pytest.skip("FP16 BLOCKED_BY_ENVIRONMENT: " + layout["error"][-500:])
    conversion = layout["conversion"]
    job = layout["published_job"]
    base_metadata = {
        "manifest_digest": conversion["manifest"]["manifest_digest"],
        "manifest_integrity_status": "digest_verified",
        "conversion_identity_verified": True,
        "runtime_verified": True,
        "hardware_verified": False,
        "numeric_status": "consistent",
        "numeric_validation": job["numeric_validation"],
    }
    artifact = {
        "artifact_id": "real-fp16-artifact", "target": "onnx",
        "file_name": conversion["onnx"].name,
        "source_path": str(conversion["onnx"]),
        "sha256": conversion["onnx_sha"], "metadata": base_metadata,
    }
    preflight = delivery_artifact_quality_preflight(conversion["deploy"], artifact)
    assert preflight["formal_activation_eligible"] is True, preflight
    assert preflight["present_as_formal_activation"] is True
    assert preflight["delivery_presentation"] == "FORMAL_ACTIVATION"
    assert preflight["attachment_delivery_allowed"] is True
    assert preflight["hardware_acceptance"] == "NOT_VERIFIED"
    assert preflight["present_as_hardware_accepted"] is False
    assert preflight["numeric_status_alone_is_sufficient"] is False
    assert preflight["model_sha_matches"] is True
    assert preflight["manifest_digest"] == conversion["manifest"]["manifest_digest"]
    assert preflight["numeric_evidence"]["eligible"] is True
    assert preflight["numeric_evidence"]["verdict"] == "consistent"
    # A mutable numeric_status claiming "consistent" without readable evidence is
    # a legal attachment, but never a formal activation or hardware acceptance.
    unverified = {
        **artifact,
        "metadata": {
            **base_metadata, "numeric_status": "consistent", "numeric_validation": {},
        },
    }
    attachment = delivery_artifact_quality_preflight(conversion["deploy"], unverified)
    assert attachment["formal_activation_eligible"] is False
    assert attachment["present_as_formal_activation"] is False
    assert attachment["delivery_presentation"] == "UNVERIFIED_ATTACHMENT"
    assert attachment["attachment_delivery_allowed"] is True
    assert attachment["hardware_acceptance"] == "NOT_VERIFIED"
    assert "NUMERIC_EVIDENCE_MISSING" in attachment["reasons"]
    assert "NUMERIC_STATUS_WITHOUT_EVIDENCE" in attachment["reasons"]


# ---------------------------------------------------------------------------
# N5.1: the actual combination matrix with status + real evidence summary.
# ---------------------------------------------------------------------------
def _matrix_status(conversion: dict, numeric: dict | None, *, blocked_by_environment="", blocked_by_runtime="") -> str:
    if blocked_by_environment:
        return "BLOCKED_BY_ENVIRONMENT"
    if blocked_by_runtime:
        return "BLOCKED_BY_RUNTIME"
    manifest = conversion.get("manifest") or {}
    checked = (manifest.get("onnx") or {}).get("checker") == "passed"
    runtime = (manifest.get("onnx") or {}).get("runtime") == "onnxruntime"
    consistent = bool(numeric) and numeric.get("status") == "completed" \
        and numeric.get("verdict") == "consistent"
    return "VERIFIED" if (checked and runtime and consistent) else "NOT_VERIFIED"


def _matrix_evidence(conversion: dict, numeric: dict | None, *, error: str = "") -> dict:
    manifest = conversion.get("manifest") or {}
    onnx_block = manifest.get("onnx") or {}
    export = (manifest.get("source_manifest") or {}).get("export") or {}
    topology = ((conversion.get("final_job") or {}).get("execution_evidence") or {}).get("onnx_topology") or {}
    rows = (numeric or {}).get("images") or []
    return {
        "opset": export.get("opset"), "dynamic": export.get("dynamic"),
        "precision": export.get("precision"), "simplify": export.get("simplify"),
        "imgsz": export.get("imgsz"),
        "checker": onnx_block.get("checker"), "runtime": onnx_block.get("runtime"),
        "input_types": onnx_block.get("input_types"),
        "output_types": onnx_block.get("output_types"),
        "output_dtypes": onnx_block.get("output_dtypes"),
        "floating_tensor_types": onnx_block.get("floating_tensor_types"),
        "topology_applied": topology.get("applied"),
        "topology_moved_nodes": topology.get("moved_nodes"),
        "numeric_verdict": (numeric or {}).get("verdict"),
        "detection_status": (numeric or {}).get("detection_status"),
        "max_p95_abs_error": max((row.get("p95_abs_error") or 0) for row in rows) if rows else None,
        "min_cosine_similarity": min((row.get("cosine_similarity") or 0) for row in rows) if rows else None,
        "max_normalized_mae": max((row.get("normalized_mae") or 0) for row in rows) if rows else None,
        "min_matched_iou": min(
            (row["detection"].get("mean_matched_iou") or 0) for row in rows
            if row.get("detection")) if rows else None,
        "error": str(error)[:1000],
    }


@pytest.fixture(scope="module")
def real_matrix(
    real_conversion, real_numeric, real_fp16_evidence, real_simplify_conversion,
    real_opset11_conversion, real_dynamic_conversion,
):
    rows = []
    rows.append({
        "combination": "fp32-static-opset12", "status": _matrix_status(real_conversion, real_numeric),
        "evidence": _matrix_evidence(real_conversion, real_numeric),
    })
    fp16_conversion = real_fp16_evidence["conversion"]
    if real_fp16_evidence.get("blocked_by_environment"):
        rows.append({
            "combination": "fp16-static-opset12",
            "status": _matrix_status(
                {}, None, blocked_by_environment=real_fp16_evidence["error"]),
            "evidence": {"precision": "fp16", "error": real_fp16_evidence["error"]},
        })
    else:
        rows.append({
            "combination": "fp16-static-opset12",
            "status": _matrix_status(fp16_conversion, real_fp16_evidence["result"]),
            "evidence": _matrix_evidence(fp16_conversion, real_fp16_evidence["result"]),
        })
    simplify = real_simplify_conversion
    if simplify.get("blocked_by_environment"):
        rows.append({
            "combination": "fp32-static-opset12-simplify",
            "status": _matrix_status({}, None, blocked_by_environment=simplify["error"]),
            "evidence": {"simplifier": _SIMPLIFIER, "error": simplify["error"]},
        })
    else:
        simplify_numeric = _verify_real(simplify, precision="fp32")
        rows.append({
            "combination": "fp32-static-opset12-simplify",
            "status": _matrix_status(simplify, simplify_numeric),
            "evidence": {**_matrix_evidence(simplify, simplify_numeric), "simplifier": _SIMPLIFIER},
        })
    opset11_numeric = _verify_real(real_opset11_conversion, precision="fp32")
    rows.append({
        "combination": "fp32-static-opset11",
        "status": _matrix_status(real_opset11_conversion, opset11_numeric),
        "evidence": _matrix_evidence(real_opset11_conversion, opset11_numeric),
    })
    dynamic_numeric = _verify_real(real_dynamic_conversion, precision="fp32", dynamic=True)
    rows.append({
        "combination": "fp32-dynamic-opset12-frozen-imgsz",
        "status": _matrix_status(real_dynamic_conversion, dynamic_numeric),
        "evidence": _matrix_evidence(real_dynamic_conversion, dynamic_numeric),
    })
    from platform_core.deployment.numeric_consistency import verify_images
    refusal = verify_images(
        real_dynamic_conversion["source"], real_dynamic_conversion["onnx"],
        [real_dynamic_conversion["images"][0]], precision="fp32",
        expected_source_sha=real_dynamic_conversion["source_sha"],
        expected_onnx_sha=real_dynamic_conversion["onnx_sha"],
        input_color_order="rgb", preprocessing=dict(CANONICAL_PREPROCESSING),
        input_shapes=real_dynamic_conversion["manifest"]["onnx"]["input_shapes"],
        frozen_batch=real_dynamic_conversion["final_job"]["params"]["batch"],
        confidence=0.00001,
    )
    rows.append({
        "combination": "fp32-dynamic-opset12-no-frozen-imgsz",
        "status": _matrix_status(real_dynamic_conversion, refusal),
        "evidence": {
            **_matrix_evidence(real_dynamic_conversion, refusal),
            "rejection_code": (refusal.get("rejection") or {}).get("code"),
            "rejection_reason": (refusal.get("rejection") or {}).get("reason"),
        },
    })
    return rows


def test_real_conversion_matrix_records_honest_status_and_evidence(real_matrix):
    rows = {row["combination"]: row for row in real_matrix}
    assert {
        "fp32-static-opset12", "fp16-static-opset12", "fp32-static-opset12-simplify",
        "fp32-static-opset11", "fp32-dynamic-opset12-frozen-imgsz",
        "fp32-dynamic-opset12-no-frozen-imgsz",
    } <= set(rows)
    print("REAL_PT_ONNX_MATRIX=" + json.dumps(
        [{
            "combination": row["combination"], "status": row["status"],
            "precision": row["evidence"].get("precision"),
            "opset": row["evidence"].get("opset"),
            "dynamic": row["evidence"].get("dynamic"),
            "simplify": row["evidence"].get("simplify"),
            "topology_moved": row["evidence"].get("topology_moved_nodes"),
            "max_p95_abs_error": row["evidence"].get("max_p95_abs_error"),
            "min_cosine": row["evidence"].get("min_cosine_similarity"),
            "max_normalized_mae": row["evidence"].get("max_normalized_mae"),
            "min_matched_iou": row["evidence"].get("min_matched_iou"),
            "rejection_code": row["evidence"].get("rejection_code"),
            "error": str(row["evidence"].get("error") or "")[:200],
        } for row in real_matrix],
        ensure_ascii=False, default=str))
    for row in real_matrix:
        assert row["status"] in MATRIX_STATUSES, row
        evidence = row["evidence"]
        if row["status"] == "VERIFIED":
            # Verified only with a real checker pass, real ORT run and a measured
            # consistent numeric verdict; no status is inferred from config.
            assert evidence["checker"] == "passed", row
            assert evidence["runtime"] == "onnxruntime", row
            assert evidence["numeric_verdict"] == "consistent", row
            assert evidence["detection_status"] == "consistent", row
            assert evidence["max_p95_abs_error"] is not None, row
            assert evidence["min_cosine_similarity"] is not None, row
            assert 0.999 <= evidence["min_cosine_similarity"] <= 1.0, row
            assert evidence["max_normalized_mae"] <= 0.05, row
            assert evidence["min_matched_iou"] >= 0.95, row
            assert evidence["output_dtypes"] == ["float32"], row
        elif row["status"] in {"BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_RUNTIME"}:
            assert evidence.get("error"), row
    fp32 = rows["fp32-static-opset12"]["evidence"]
    assert fp32["opset"] == 12 and fp32["precision"] == "fp32"
    assert fp32["dynamic"] is False and fp32["simplify"] is False
    fp16 = rows["fp16-static-opset12"]["evidence"]
    if rows["fp16-static-opset12"]["status"] == "VERIFIED":
        assert fp16["precision"] == "fp16"
        assert "FLOAT16" in (fp16["floating_tensor_types"] or [])
        assert fp16["topology_applied"] is True
        assert fp16["topology_moved_nodes"] > 0
        assert fp16["input_types"] == ["tensor(float)"]
        assert fp16["output_dtypes"] == ["float32"]
    else:
        assert rows["fp16-static-opset12"]["evidence"]["error"]
    dynamic = rows["fp32-dynamic-opset12-frozen-imgsz"]["evidence"]
    assert dynamic["dynamic"] is True
    assert rows["fp32-dynamic-opset12-frozen-imgsz"]["status"] == "VERIFIED"
    no_frozen = rows["fp32-dynamic-opset12-no-frozen-imgsz"]["evidence"]
    assert no_frozen["rejection_code"] == "DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ"
    assert "640" in no_frozen["rejection_reason"]
