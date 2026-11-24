"""Numerical verification must distinguish measured agreement from missing evidence."""
import json

import numpy as np
import pytest

from platform_core.deployment.numeric_consistency import (
    compare_tensors, compare_yolo_detections, is_canonical_rgb_preprocessing, make_input, validate_paths, verify_label_identity,
)


def test_identical_tensors_are_consistent_even_when_all_zero():
    value = compare_tensors(np.zeros((1, 5)), np.zeros((1, 5)))
    assert value["comparable"]
    assert value["cosine_similarity"] == 1
    assert value["within_tolerance"]


def test_large_mismatch_is_detected_without_fabricated_accuracy():
    value = compare_tensors(np.array([[1., 2., 3.]]), np.array([[3., 2., 1.]]))
    assert value["comparable"]
    assert not value["within_tolerance"]
    assert value["normalized_mae"] > .1


def test_yolo_detection_comparison_catches_threshold_crossing_hidden_by_tensor_mean():
    # One threshold crossing in many anchors is diluted in MAE and cosine.
    original = np.zeros((1, 5, 1000), dtype=np.float32)
    original[0, :4, :] = np.array([[200], [200], [30], [30]])
    original[0, 4, :] = 0.24
    converted = original.copy()
    converted[0, 4, 1] = 0.26
    assert compare_tensors(original, converted, precision="fp16")["within_tolerance"] is True
    result = compare_yolo_detections(original, converted, class_count=1)
    assert result["comparable"]
    assert result["threshold_crossings"] == 1
    assert result["after_nms_reference"] == 0
    assert result["after_nms_converted"] == 1
    assert result["within_tolerance"] is False


def test_yolo_detection_comparison_checks_class_mapping_and_shape_before_pass():
    original = np.zeros((1, 6, 20), dtype=np.float32)
    original[0, :4, :] = np.array([[100], [100], [20], [20]])
    original[0, 4, 1] = 0.9
    converted = original.copy()
    converted[0, 4, 1], converted[0, 5, 1] = 0.0, 0.9
    result = compare_yolo_detections(original, converted, class_count=2)
    assert result["comparable"] and not result["within_tolerance"]
    assert result["unmatched_reference"] == result["unmatched_converted"] == 1
    assert not compare_yolo_detections(original, converted, class_count=1)["comparable"]


def test_yolo_detection_comparison_does_not_fail_on_suppressed_duplicate_anchor():
    original = np.zeros((1, 5, 20), dtype=np.float32)
    original[0, :4, :] = np.array([[100], [100], [20], [20]])
    original[0, 4, 0] = 0.9
    original[0, 4, 1] = 0.24
    converted = original.copy()
    converted[0, 4, 1] = 0.26
    result = compare_yolo_detections(original, converted, class_count=1)
    assert result["threshold_crossings"] == 1
    assert result["after_nms_reference"] == result["after_nms_converted"] == 1
    assert result["within_tolerance"] is True


def test_numeric_verification_refuses_to_call_noncanonical_deployment_preprocessing_verified():
    canonical = {"pixel_format": "rgb", "channel_format": "nchw", "resize_interpolation": "opencv_linear",
                 "letterbox_mode": "fixed_shape_center", "scale": [1 / 255] * 3}
    assert is_canonical_rgb_preprocessing(canonical)
    assert not is_canonical_rgb_preprocessing({"pixel_format": "rgb", "scale": [1 / 255] * 3})
    assert not is_canonical_rgb_preprocessing({**canonical, "resize_interpolation": "pillow_bilinear"})
    assert not is_canonical_rgb_preprocessing({"letterbox": False})
    assert not is_canonical_rgb_preprocessing({"pixel_format": "bgr"})
    assert not is_canonical_rgb_preprocessing({"scale": [1.0, 1.0, 1.0]})
    assert not is_canonical_rgb_preprocessing({"mean": "bad"})


def test_label_identity_requires_exact_frozen_order_even_when_count_matches():
    schema = [{"class_id": 1, "code": "fire"}, {"class_id": 0, "code": "smoke"}]
    checked = verify_label_identity({0: "smoke", 1: "fire"}, label_codes=["smoke", "fire"], label_schema=schema)
    assert checked["status"] == "verified" and len(checked["mapping_sha256"]) == 64
    assert verify_label_identity({0: "fire", 1: "smoke"}, label_codes=["smoke", "fire"], label_schema=schema)["status"] == "mismatch"
    assert verify_label_identity({0: "smoke", 1: "fire"}, label_codes=["fire", "smoke"], label_schema=schema)["status"] == "conflict"
    assert verify_label_identity({0: "smoke", 1: "fire"})["status"] == "unknown"


def test_different_deployment_thresholds_change_detection_outcome_and_invalid_values_fail_closed():
    original = np.zeros((1, 5, 12), dtype=np.float32)
    original[0, :4, :] = np.array([[100], [100], [15], [15]])
    original[0, 4, 1] = 0.24
    converted = original.copy()
    converted[0, 4, 1] = 0.26
    assert not compare_yolo_detections(original, converted, class_count=1, confidence=0.25)["within_tolerance"]
    assert compare_yolo_detections(original, converted, class_count=1, confidence=0.30)["within_tolerance"]
    assert not compare_yolo_detections(original, converted, class_count=1, confidence=float('nan'))["comparable"]


@pytest.mark.parametrize("unknown_precision", ["int8", "auto", "fp8", "unknown", ""])
def test_unsupported_precision_never_uses_an_implicit_fp16_tolerance(unknown_precision):
    value = compare_tensors(np.ones((1, 3)), np.ones((1, 3)), precision=unknown_precision)
    assert value["comparable"] is False
    assert "容差协议" in value["reason"]
    assert "within_tolerance" not in value


@pytest.mark.parametrize("converted", [np.zeros((1, 4)), np.array([[np.nan, 1.]])])
def test_incomparable_or_invalid_tensors_never_pass(converted):
    value = compare_tensors(np.ones((1, 2)), converted)
    assert value["comparable"] is False
    assert "within_tolerance" not in value


def test_real_image_uses_explicit_rgb_letterbox_and_zero_to_one(tmp_path):
    from PIL import Image

    path = tmp_path / "rect.png"
    Image.new("RGB", (32, 16), (255, 0, 0)).save(path)
    tensor = make_input(path, 64, 64)
    assert tensor.shape == (1, 3, 64, 64)
    assert tensor.dtype == np.float32
    assert np.isclose(tensor[0, 0, 30, 20], 1)
    assert np.isclose(tensor[0, 1, 30, 20], 0)
    assert np.isclose(tensor[0, 0, 0, 0], 114 / 255)


def test_missing_source_and_source_hash_are_hard_rejections(tmp_path):
    pt, onnx, image = (tmp_path / name for name in ("model.pt", "model.onnx", "test.jpg"))
    for p in (pt, onnx, image):
        p.write_bytes(b"real-only-fixture")
    validate_paths(pt, onnx, [image])
    with pytest.raises(ValueError, match="SHA256"):
        validate_paths(pt, onnx, [image], expected_source_sha="deadbeef")
    with pytest.raises(ValueError, match="至少"):
        validate_paths(pt, onnx, [])
    with pytest.raises(ValueError, match="源模型不是 PT"):
        validate_paths(onnx, onnx, [image])


def test_worker_does_not_say_success_when_dependencies_or_models_fail(tmp_path, monkeypatch):
    import json
    from platform_core.deployment import numeric_consistency as numeric

    directory = tmp_path / "run"
    (directory / "images").mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({
        "source_path": "missing.pt", "onnx_path": "missing.onnx",
        "image_names": ["a.jpg"], "precision": "fp16",
    }), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        numeric.run_verification_directory(directory)
    receipt = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == "unavailable"
    assert receipt["bmodel_verified"] is False


def test_sophon_simulation_without_configured_vendor_sdk_is_unavailable():
    from platform_core.deployment.numeric_consistency import _simulate_bmodel

    with pytest.raises(RuntimeError, match="Sophon SDK"):
        _simulate_bmodel(np.ones((1, 3, 32, 32), dtype=np.float32), "images", __import__("pathlib").Path("fake.bmodel"), "")


def test_missing_expected_bmodel_is_unavailable_without_hiding_pt_onnx_result(tmp_path, monkeypatch):
    import contextlib
    import sys
    from types import SimpleNamespace
    from PIL import Image
    from platform_core.deployment.numeric_consistency import verify_images

    pt, onnx, picture = (tmp_path / name for name in ("model.pt", "model.onnx", "test.png"))
    pt.write_bytes(b"original")
    onnx.write_bytes(b"converted")
    Image.new("RGB", (32, 32), (10, 20, 30)).save(picture)

    class Tensor:
        def __init__(self, value):
            self.value = value

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.value

    class Model:
        def cpu(self):
            return self

        def eval(self):
            return self

        def float(self):
            return self

        def __call__(self, value):
            return Tensor(np.ones((1, 5), dtype=np.float32))

    class Session:
        def get_inputs(self):
            return [SimpleNamespace(name="images", shape=[1, 3, 32, 32], type="tensor(float)")]

        def get_outputs(self):
            return [SimpleNamespace(name="output")]

        def run(self, _outputs, _inputs):
            return [np.ones((1, 5), dtype=np.float32)]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=contextlib.nullcontext, from_numpy=Tensor))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *args, **kwargs: Session()))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda _path: SimpleNamespace(model=Model())))

    result = verify_images(pt, onnx, [picture], precision="fp32", bmodel_expected=True)
    assert result["verdict"] == "not_comparable"  # Raw 2-D tensor has no supported detection output.
    assert result["bmodel_numeric_status"] == "unavailable"
    assert "BMODEL 文件不存在" in result["bmodel_numeric_error"]
    assert result["bmodel_verified"] is False
    assert result["hardware_verified"] is False


def test_verification_verdict_does_not_claim_consistency_when_nms_detection_changes(tmp_path, monkeypatch):
    import contextlib
    import sys
    from types import SimpleNamespace
    from PIL import Image
    from platform_core.deployment.numeric_consistency import verify_images

    pt, onnx, image = (tmp_path / name for name in ("best.pt", "best.onnx", "frame.png"))
    pt.write_bytes(b"isolated-source")
    onnx.write_bytes(b"isolated-onnx")
    Image.new("RGB", (32, 32), (123, 92, 30)).save(image)
    original = np.zeros((1, 5, 1000), dtype=np.float32)
    original[0, :4, :] = np.array([[200], [200], [30], [30]])
    original[0, 4, :] = 0.24
    converted = original.copy()
    converted[0, 4, 0] = 0.26

    class Tensor:
        def __init__(self, value): self.value = value
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return self.value

    class Model:
        names = {0: "fight"}
        def cpu(self): return self
        def eval(self): return self
        def float(self): return self
        def __call__(self, value): return Tensor(original)

    class Session:
        def get_inputs(self): return [SimpleNamespace(name="images", shape=[1, 3, 32, 32], type="tensor(float)")]
        def get_outputs(self): return [SimpleNamespace(name="output")]
        def run(self, outputs, inputs): return [converted]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=contextlib.nullcontext, from_numpy=Tensor))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *args, **kwargs: Session()))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda path: SimpleNamespace(model=Model(), names={0: "fight"})))
    result = verify_images(pt, onnx, [image], precision="fp16", label_codes=["fight"])
    assert result["raw_verdict"] == "consistent"
    assert result["verdict"] == "difference_detected"
    assert result["detection_status"] == "difference_detected"
    assert result["images"][0]["detection"]["threshold_crossings"] == 1


def test_sophon_adapter_reads_only_actual_offline_runner_output(monkeypatch):
    from types import SimpleNamespace
    from platform_core.deployment import numeric_consistency as numeric

    monkeypatch.setattr(numeric.shutil, "which", lambda path: "/sdk/bin/python")

    def fake_runner(argv, **kwargs):
        output = __import__("pathlib").Path(argv[argv.index("--output") + 1])
        np.savez(output, predictions=np.ones((1, 5), dtype=np.float32))
        assert "--model" in argv and "--input" in argv
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(numeric.subprocess, "run", fake_runner)
    observed = numeric._simulate_bmodel(np.ones((1, 3, 32, 32), dtype=np.float32), "images", __import__("pathlib").Path("model.bmodel"), "/sdk/bin/python")
    np.testing.assert_array_equal(observed, np.ones((1, 5), dtype=np.float32))


def test_recovered_successful_verification_reuses_durable_result(tmp_path):
    import json
    from types import SimpleNamespace
    from platform_core.deployment.conversion_tasks import run_numeric_verification
    from platform_core.task_runtime import TaskStatus

    directory = tmp_path / "verification"
    directory.mkdir()
    (directory / "request.json").write_text("{}")
    (directory / "result.json").write_text(json.dumps({"status": "completed", "verdict": "difference_detected", "hardware_verified": False}))
    worker = tmp_path / "worker.py"
    worker.write_text("# not launched on recovery\n")

    class Artifacts:
        def __init__(self):
            self.entries = {}

        def atomic_write_json(self, task_id, name, result):
            self.entries[(task_id, name)] = result

    class Context:
        def __init__(self):
            self.artifacts = Artifacts()
            self.task = SimpleNamespace(task_id="verification-id")

        def assert_current_execution(self):
            return self.task

        def heartbeat(self, **kwargs):
            assert kwargs["progress"] == 100

    context = Context()
    status, result_ref = run_numeric_verification(context, {"verification_dir": str(directory), "worker_path": str(worker)})
    assert status is TaskStatus.SUCCEEDED
    assert context.artifacts.entries[("verification-id", result_ref)]["verdict"] == "difference_detected"


def _detection_tensor(rows, class_count=2):
    """Single-output YOLO11 XYWH + class-score tensor with an unambiguous layout."""
    fields = 4 + class_count
    value = np.zeros((1, fields, len(rows)), dtype=np.float32)
    for index, (xywh, scores) in enumerate(rows):
        value[0, :4, index] = xywh
        value[0, 4:4 + len(scores), index] = scores
    return value


@pytest.mark.parametrize("original_size,expected", [
    ((240, 120), {"scale_x": 64 / 240, "scale_y": 32 / 120, "pad_x": 0.0, "pad_y": 16.0}),
    ((120, 240), {"scale_x": 32 / 120, "scale_y": 64 / 240, "pad_x": 16.0, "pad_y": 0.0}),
    ((97, 61), {"scale_x": 64 / 97, "scale_y": 40 / 61, "pad_x": 0.0, "pad_y": 12.0}),
])
def test_letterbox_geometry_maps_real_boxes_back_to_original_pixels(tmp_path, original_size, expected):
    from PIL import Image
    from platform_core.auto_label import adapt_coordinates
    from platform_core.deployment.numeric_consistency import (
        compare_yolo_detections, make_input_with_geometry,
    )

    width, height = original_size
    picture = tmp_path / "rect.png"
    Image.new("RGB", (width, height), (30, 60, 90)).save(picture)
    prepared = make_input_with_geometry(picture, 64, 64)
    geometry = prepared["geometry"]
    assert prepared["original_size"] == [width, height]
    for key, value in expected.items():
        assert geometry[key] == pytest.approx(value, rel=1e-12), key
    # Real image tensor has exactly the frozen shape and canonical letterbox padding.
    assert prepared["tensor"].shape == (1, 3, 64, 64)
    content_center_x = geometry["pad_x"] + 0.5 * 64 * geometry["scale_x"]
    content_center_y = geometry["pad_y"] + 0.5 * 64 * geometry["scale_y"]
    half = 4.0
    box = [content_center_x - half, content_center_y - half, content_center_x + half, content_center_y + half]
    xywh = [box[0] + half, box[1] + half, 2 * half, 2 * half]
    tensor = _detection_tensor([(xywh, [0.9, 0.0])])
    compared = compare_yolo_detections(tensor, tensor.copy(), class_count=2,
                                       geometry=geometry, original_size=prepared["original_size"])
    assert compared["comparable"] and compared["within_tolerance"]
    entry = compared["reference_detections"][0]
    assert entry["box_xyxy_input"] == [round(float(value), 3) for value in box]
    expected_original = adapt_coordinates(
        box, width=width, height=height, coordinate_space="pixel", coordinate_order="xyxy",
        coordinate_origin="top_left", geometry=geometry,
    )
    # The detection tensor is float32; geometry math is float64. Allow the
    # float32 quantisation of the input box, not a different mapping formula.
    assert len(entry["box_xyxy_original"]) == 4
    for observed, expected_value in zip(entry["box_xyxy_original"], expected_original):
        assert observed == pytest.approx(float(expected_value), abs=0.002)
    assert entry["coordinate_error"] == ""
    x1, y1, x2, y2 = entry["box_xyxy_original"]
    assert 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
    assert compared["original_coordinates"]["status"] == "mapped"
    assert compared["original_coordinates"]["mapped"] == 2


def test_detection_comparison_reports_mean_iou_and_per_class_counts():
    from platform_core.deployment.numeric_consistency import compare_yolo_detections

    reference = _detection_tensor([
        ([20.0, 20.0, 10.0, 10.0], [0.9, 0.0]),
        ([60.0, 60.0, 10.0, 10.0], [0.8, 0.0]),
        ([100.0, 100.0, 10.0, 10.0], [0.0, 0.7]),
    ])
    converted = reference.copy()
    converted[0, :4, 2] = [150.0, 150.0, 10.0, 10.0]  # same class, disjoint -> unmatched pair
    compared = compare_yolo_detections(reference, converted, class_count=2)
    assert compared["comparable"] and not compared["within_tolerance"]
    assert compared["matched_pairs"] == 2 and compared["mean_matched_iou"] == 1.0
    assert compared["unmatched_reference"] == compared["unmatched_converted"] == 1
    per_class = {row["class_id"]: row for row in compared["per_class"]}
    assert per_class[0] == {"class_id": 0, "reference_boxes": 2, "converted_boxes": 2,
                            "matched_pairs": 2, "unmatched_reference": 0,
                            "unmatched_converted": 0, "mean_matched_iou": 1.0}
    assert per_class[1]["reference_boxes"] == per_class[1]["converted_boxes"] == 1
    assert per_class[1]["unmatched_reference"] == per_class[1]["unmatched_converted"] == 1
    assert per_class[1]["matched_pairs"] == 0 and per_class[1]["mean_matched_iou"] is None
    assert compared["reference_detections"][0]["box_xyxy_original"] is None
    assert compared["reference_detections"][0]["coordinate_error"] == "PREPROCESSING_GEOMETRY_UNAVAILABLE"
    assert compared["original_coordinates"]["status"] == "unavailable"


def test_dynamic_spatial_input_without_frozen_size_is_not_comparable_not_fallback_640():
    from types import SimpleNamespace
    from platform_core.deployment.numeric_consistency import (
        DYNAMIC_INPUT_WITHOUT_FROZEN_CODE, _resolve_input_contract,
    )

    dynamic = SimpleNamespace(shape=[1, 3, "height", "width"])
    unresolved = _resolve_input_contract(dynamic, input_shapes=None, frozen_imgsz=None)
    assert unresolved["status"] == "not_comparable"
    assert unresolved["code"] == DYNAMIC_INPUT_WITHOUT_FROZEN_CODE
    assert unresolved["dynamic_resolution"] == "not_comparable"
    assert "640" in unresolved["reason"]
    assert unresolved["resolved_input_shape"] is None
    frozen_imgsz = _resolve_input_contract(dynamic, input_shapes=None, frozen_imgsz=[64, 96])
    assert frozen_imgsz["status"] == "resolved"
    assert frozen_imgsz["resolved_input_shape"] == [1, 3, 64, 96]
    assert frozen_imgsz["dynamic_resolution"] == "frozen_imgsz"
    assert frozen_imgsz["input_shape_source"] == "frozen_imgsz"
    assert frozen_imgsz["dynamic_resolution_reason"]
    frozen_manifest = _resolve_input_contract(dynamic, input_shapes=[[1, 3, 128, 160]], frozen_imgsz=None)
    assert frozen_manifest["status"] == "resolved"
    assert frozen_manifest["resolved_input_shape"] == [1, 3, 128, 160]
    assert frozen_manifest["input_shape_source"] == "frozen_manifest"
    # A dynamic batch needs an explicit frozen batch=1; it is never assumed.
    dynamic_axes = SimpleNamespace(shape=["batch", 3, "height", "width"])
    dynamic_batch = _resolve_input_contract(dynamic_axes, input_shapes=None, frozen_imgsz=[64, 96])
    assert dynamic_batch["status"] == "not_comparable"
    assert dynamic_batch["code"] == "DYNAMIC_BATCH_WITHOUT_FROZEN_BATCH"
    frozen_batch = _resolve_input_contract(dynamic_axes, input_shapes=None, frozen_imgsz=[64, 96], frozen_batch=1)
    assert frozen_batch["status"] == "resolved"
    assert frozen_batch["resolved_input_shape"] == [1, 3, 64, 96]
    assert frozen_batch["dynamic_resolution"] == "frozen_imgsz"
    assert frozen_batch["batch_source"] == "frozen_batch"
    assert _resolve_input_contract(
        SimpleNamespace(shape=[2, 3, 64, 64]), input_shapes=None, frozen_imgsz=None,
    )["code"] == "NON_SINGLE_IMAGE_BATCH"


def test_static_input_shape_from_manifest_must_match_graph_and_never_conflict():
    from types import SimpleNamespace
    from platform_core.deployment.numeric_consistency import _resolve_input_contract

    static = SimpleNamespace(shape=[1, 3, 64, 64])
    matched = _resolve_input_contract(static, input_shapes=[[1, 3, 64, 64]], frozen_imgsz=[64, 64])
    assert matched["status"] == "resolved"
    assert matched["dynamic_resolution"] == "static"
    assert matched["input_shape_source"] == "frozen_manifest"
    conflict = _resolve_input_contract(static, input_shapes=[[1, 3, 32, 32]], frozen_imgsz=None)
    assert conflict["status"] == "not_comparable" and conflict["code"] == "INPUT_SHAPE_CONFLICT"
    out_of_range = _resolve_input_contract(
        SimpleNamespace(shape=[1, 3, 8192, 8192]), input_shapes=None, frozen_imgsz=None)
    assert out_of_range["status"] == "not_comparable" and out_of_range["code"] == "INPUT_SIZE_OUT_OF_RANGE"


def test_dynamic_onnx_session_is_reported_not_comparable_without_frozen_imgsz(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from PIL import Image
    from platform_core.deployment.numeric_consistency import verify_images

    pt, onnx, picture = (tmp_path / name for name in ("model.pt", "model.onnx", "frame.png"))
    pt.write_bytes(b"not-loaded-for-dynamic-contract")
    onnx.write_bytes(b"not-loaded-for-dynamic-contract")
    Image.new("RGB", (32, 32), (1, 2, 3)).save(picture)

    class Session:
        def get_inputs(self):
            return [SimpleNamespace(name="images", shape=[1, 3, "height", "width"], type="tensor(float)")]

        def get_outputs(self):
            return [SimpleNamespace(name="output")]

        def run(self, *_args, **_kwargs):
            raise AssertionError("动态输入未冻结尺寸时不得执行推理")

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *args, **kwargs: Session()))
    result = verify_images(pt, onnx, [picture], precision="fp32")
    assert result["status"] == "completed"
    assert result["verdict"] == "not_comparable" and result["raw_verdict"] == "not_comparable"
    assert result["rejection"]["code"] == "DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ"
    assert result["dynamic_resolution"] == "not_comparable"
    assert result["sample_count"] == 0 and result["images"] == []
    assert result["hardware_verified"] is False


def test_non_rgb_input_is_rejected_with_explicit_reason_code(tmp_path):
    from platform_core.deployment.numeric_consistency import NON_RGB_INPUT_CODE, verify_images

    pt, onnx, picture = (tmp_path / name for name in ("model.pt", "model.onnx", "frame.png"))
    pt.write_bytes(b"source")
    onnx.write_bytes(b"converted")
    picture.write_bytes(b"image-not-opened-for-bgr-rejection")
    result = verify_images(pt, onnx, [picture], precision="fp32", input_color_order="bgr")
    assert result["status"] == "completed"
    assert result["verdict"] == "not_comparable"
    assert result["rejection"] == {
        "code": NON_RGB_INPUT_CODE,
        "reason": "该产物使用非 RGB 输入颜色适配；当前原始张量核验仅支持 RGB 同输入，不能冒充通过",
    }
    assert result["input_color_space"] == "bgr"
    assert result["sample_count"] == 0 and result["images"] == []
    assert result["ground_truth_used"] is False and result["hardware_verified"] is False


def test_runtime_versions_record_actual_versions_and_explicit_import_failures(tmp_path, monkeypatch):
    import contextlib
    import sys
    from types import SimpleNamespace
    from PIL import Image
    from platform_core.deployment import numeric_consistency as numeric

    assert set(numeric.runtime_versions()) == set(numeric.RUNTIME_MODULES)
    observed = numeric.runtime_versions()
    assert observed["numpy"]["version"] == np.__version__ and observed["numpy"]["error"] is None
    pt, onnx, image = (tmp_path / name for name in ("best.pt", "best.onnx", "frame.png"))
    pt.write_bytes(b"isolated-source")
    onnx.write_bytes(b"isolated-onnx")
    Image.new("RGB", (32, 32), (10, 20, 30)).save(image)

    class Tensor:
        def __init__(self, value): self.value = value
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return self.value

    class Model:
        names = {0: "fight"}
        def cpu(self): return self
        def eval(self): return self
        def float(self): return self
        def __call__(self, value): return Tensor(np.ones((1, 5), dtype=np.float32))

    class Session:
        def get_inputs(self): return [SimpleNamespace(name="images", shape=[1, 3, 32, 32], type="tensor(float)")]
        def get_outputs(self): return [SimpleNamespace(name="output")]
        def run(self, outputs, inputs): return [np.ones((1, 5), dtype=np.float32)]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=contextlib.nullcontext, from_numpy=Tensor))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *args, **kwargs: Session()))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda path: SimpleNamespace(model=Model(), names={0: "fight"})))
    result = numeric.verify_images(pt, onnx, [image], precision="fp32")
    versions = result["runtime_versions"]
    assert set(versions) == set(numeric.RUNTIME_MODULES)
    for name, row in versions.items():
        assert set(row) == {"version", "error"}
        assert row["version"] is None or isinstance(row["version"], str)
        assert row["error"] is None or isinstance(row["error"], str)
        assert (row["version"] is None) == bool(row["error"])
    # Mocked modules expose no __version__: the report records the failure, not a fake value.
    assert versions["torch"]["version"] is None and "未暴露" in versions["torch"]["error"]
    assert versions["onnx"]["version"] == __import__("onnx").__version__
    assert versions["cv2"]["version"] == __import__("cv2").__version__
    assert result["input_color_space"] == "rgb"
    assert result["dynamic_resolution"] == "static"
    assert result["input_contract"]["status"] == "resolved"
    assert result["input_contract"]["frozen_input_shapes"] is None
    assert result["input_contract"]["input_shape_source"] == "onnx_graph_static"


def _job_layout(tmp_path, *, job_id="conversion-1", project_id="p1"):
    deploy = tmp_path / "deployment"
    verification = deploy / "numeric-validations" / "nv_0123456789abcdef01234567"
    verification.mkdir(parents=True)
    (verification / "images").mkdir()
    (verification / "request.json").write_text("{}", encoding="utf-8")
    job_dir = deploy / "jobs" / job_id
    job_dir.mkdir(parents=True)
    job = {"id": job_id, "project_id": project_id, "status": "done", "numeric_status": None,
           "publication_status": None}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    receipt = {"id": verification.name, "project_id": project_id, "conversion_job_id": job_id}
    return verification, job_dir / "job.json", receipt


@pytest.mark.parametrize("verdict,expected_numeric,expected_publication", [
    ("consistent", "consistent", "numeric_consistent_delivery_evidence_incomplete"),
    ("difference_detected", "difference_detected", "blocked_numeric_difference"),
    ("not_comparable", "not_comparable", "blocked_numeric_not_comparable"),
    ("contract_mismatch", "not_comparable", "blocked_numeric_not_comparable"),
])
def test_numeric_verdict_projects_into_existing_conversion_job_json(tmp_path, verdict, expected_numeric, expected_publication):
    from platform_core.deployment.numeric_consistency import project_numeric_status

    verification, job_path, receipt = _job_layout(tmp_path)
    projection = project_numeric_status(verification, receipt, {
        "status": "completed", "verdict": verdict, "raw_verdict": "consistent",
        "detection_status": "consistent", "sample_count": 2, "protocol": "pt-onnx-raw-and-detection-v4",
        "precision": "fp32", "completed_at": "2026-11-24T00:00:00+00:00",
    })
    assert projection["status"] == "projected"
    assert projection["numeric_status"] == expected_numeric
    assert projection["publication_status"] == expected_publication
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["numeric_status"] == expected_numeric
    assert job["publication_status"] == expected_publication
    assert job["numeric_validation"]["verdict"] == verdict
    assert job["numeric_validation"]["hardware_verified"] is False
    assert job["numeric_validation"]["ground_truth_used"] is False
    assert job["numeric_validation"]["result_ref"].endswith("/result.json")
    assert not list(job_path.parent.glob(".job.json.*.tmp"))


def test_numeric_projection_failure_maps_to_unavailable_and_missing_job_never_crashes(tmp_path):
    from platform_core.deployment.numeric_consistency import project_numeric_status

    verification, job_path, receipt = _job_layout(tmp_path)
    projection = project_numeric_status(verification, receipt, {"status": "failed", "error": "boom"})
    assert projection["numeric_status"] == "unavailable"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["numeric_status"] == "unavailable"
    assert job["publication_status"] == "blocked_numeric_unavailable"
    assert job["numeric_validation"]["status"] == "failed"
    missing_receipt = {"id": "nv_x", "project_id": "p1", "conversion_job_id": "missing-job"}
    assert project_numeric_status(verification, missing_receipt, {"status": "completed"})["status"] == "unavailable"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert project_numeric_status(outside, receipt, {"status": "completed"})["status"] == "unavailable"
    assert project_numeric_status(verification, {"conversion_job_id": ""}, {})["status"] == "skipped"


def test_worker_success_path_writes_verdict_back_to_conversion_job(tmp_path, monkeypatch):
    import contextlib
    import sys
    from types import SimpleNamespace
    from platform_core.deployment import numeric_consistency as numeric

    verification, job_path, receipt = _job_layout(tmp_path)
    receipt.update({"source_path": "source.pt", "onnx_path": "model.onnx",
                    "image_names": ["a.png"], "precision": "fp32"})
    (verification / "request.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(numeric, "verify_images", lambda *args, **kwargs: {
        "status": "completed", "verdict": "consistent", "raw_verdict": "consistent",
        "detection_status": "consistent", "sample_count": 1, "protocol": numeric.PROTOCOL,
        "precision": "fp32", "hardware_verified": False, "ground_truth_used": False,
        "completed_at": "2026-11-24T00:00:00+00:00",
    })
    numeric.run_verification_directory(verification)
    result = json.loads((verification / "result.json").read_text(encoding="utf-8"))
    assert result["verdict"] == "consistent"
    assert result["status_projection"]["status"] == "projected"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["numeric_status"] == "consistent"
    assert job["publication_status"] == "numeric_consistent_delivery_evidence_incomplete"


# ---------------------------------------------------------------------------
# M10-C: evidence-first publication bound to the conversion identity.
# ---------------------------------------------------------------------------
ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
_STUB_PROTOCOL = "pt-onnx-raw-and-detection-v4"


def _conversion_manifest(*, onnx_path, onnx_sha, source_sha, imgsz=(64, 64)):
    import sys
    from platform_core.conversion import build_source_manifest, source_manifest_digest

    source_manifest = build_source_manifest(
        source={"sha256": source_sha, "size_bytes": 1, "file_name": "best.pt",
                "algorithm_id": "a1", "version_id": "v1", "label_codes": ["fire"]},
        export={"opset": 12, "dynamic": False, "simplify": False, "batch": 1,
                "imgsz": list(imgsz), "precision": "fp32", "half": False},
        tool={"name": "ultralytics-export", "version": "8.4.0",
              "python_path": sys.executable, "dependencies": {}},
        onnx={"name": onnx_path.name, "sha256": onnx_sha,
              "size_bytes": onnx_path.stat().st_size, "opset_imports": [],
              "input_shapes": [[1, 3, *imgsz]], "input_types": ["tensor(float)"],
              "input_names": ["images"], "output_shapes": [], "output_types": [],
              "output_names": ["output0"], "output_inferred_shapes": [], "output_dtypes": [],
              "floating_tensor_types": []},
        outputs=[{"name": onnx_path.name, "sha256": onnx_sha,
                  "size_bytes": onnx_path.stat().st_size}],
    )
    manifest = {
        "job_id": "conversion-full-1", "status": "done",
        "source": {"sha256": source_sha},
        "onnx": {"sha256": onnx_sha, "input_shapes": [[1, 3, *imgsz]],
                 "output_names": ["output0"]},
        "tool": {"name": "ultralytics-export", "version": "8.4.0"},
        "outputs": [{"name": onnx_path.name, "sha256": onnx_sha,
                     "size_bytes": onnx_path.stat().st_size}],
        "source_manifest": source_manifest,
    }
    manifest["manifest_digest"] = source_manifest_digest(manifest)
    return manifest


def _full_numeric_layout(tmp_path, *, directory_name="nv_0123456789abcdef01234567"):
    from pathlib import Path
    from platform_core.conversion import sha256_file

    deploy = tmp_path / "deployment"
    job_id, project_id = "conversion-full-1", "p1"
    job_dir = deploy / "jobs" / job_id
    (job_dir / "source").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    source = job_dir / "source" / "best.pt"
    onnx = job_dir / "artifacts" / "model.onnx"
    source.write_bytes(b"frozen-pt-bytes")
    onnx.write_bytes(b"frozen-onnx-bytes")
    source_sha, onnx_sha = sha256_file(source), sha256_file(onnx)
    manifest = _conversion_manifest(onnx_path=onnx, onnx_sha=onnx_sha, source_sha=source_sha)
    manifest_path = job_dir / "artifacts" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    job = {
        "id": job_id, "project_id": project_id, "status": "done", "target": "onnx",
        "source_path": str(source),
        "source_trace": {"algorithm_id": "a1", "version_id": "v1", "sha256": source_sha},
        "params": {"precision": "fp32"},
        "manifest_path": str(manifest_path), "manifest_digest": manifest["manifest_digest"],
        "outputs": [{"name": onnx.name, "path": str(onnx), "sha256": onnx_sha,
                     "size_bytes": onnx.stat().st_size}],
    }
    job_path = job_dir / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    verification = deploy / "numeric-validations" / directory_name
    (verification / "images").mkdir(parents=True, exist_ok=True)
    names = ["image_01.png", "image_02.png"]
    for index, name in enumerate(names):
        (verification / "images" / name).write_bytes(f"image-bytes-{index}".encode())
    receipt = {
        "id": verification.name, "project_id": project_id, "conversion_job_id": job_id,
        "request_id": "request-identity-0001", "created_at": "2026-11-24T00:00:00+00:00",
        "source_path": str(source), "onnx_path": str(onnx),
        "source_sha256": source_sha, "onnx_sha256": onnx_sha,
        "bmodel_path": "", "bmodel_sha256": "", "bmodel_expected": False,
        "precision": "fp32", "confidence": 0.25, "nms_iou": 0.7,
        "input_color_order": "rgb",
        "preprocessing": {"pixel_format": "rgb", "channel_format": "nchw"},
        "input_shapes": [[1, 3, 64, 64]], "frozen_imgsz": [64, 64], "frozen_batch": 1,
        "label_codes": ["fire"], "label_schema": [], "image_names": names,
    }
    (verification / "request.json").write_text(json.dumps(receipt), encoding="utf-8")
    return {"deploy": deploy, "job_dir": job_dir, "job_path": job_path,
            "verification": verification, "receipt": receipt, "job": job,
            "manifest": manifest, "source": source, "onnx": onnx,
            "source_sha": source_sha, "onnx_sha": onnx_sha, "image_names": names}


def _stub_numeric_result(*, verdict="consistent", unmatched=0):
    return {
        "protocol": _STUB_PROTOCOL, "status": "completed",
        "raw_verdict": "consistent" if verdict == "consistent" else "difference_detected",
        "verdict": verdict, "detection_status": verdict,
        "comparison_confidence": 0.25, "comparison_nms_iou": 0.7,
        "sample_count": 2, "precision": "fp32",
        "hardware_verified": False, "ground_truth_used": False, "bmodel_verified": False,
        "bmodel_numeric_status": "not_applicable", "bmodel_detection_status": "not_applicable",
        "bmodel_numeric_error": "", "deployment_preprocessing_aligned": True,
        "label_identity": {"status": "verified", "mapping_sha256": "a" * 64},
        "input_color_space": "rgb",
        "input_contract": {"status": "resolved", "resolved_input_shape": [1, 3, 64, 64],
                           "input_shape_source": "frozen_manifest"},
        "dynamic_resolution": "static", "dynamic_resolution_reason": "",
        "runtime_versions": {"numpy": {"version": np.__version__, "error": None}},
        "rejection": None, "scope_note": "",
        "completed_at": "2026-11-24T00:00:00+00:00",
        "images": [
            {"image": "image_01.png", "comparable": True, "within_tolerance": verdict == "consistent",
             "normalized_mae": 0.0001, "cosine_similarity": 0.99999, "max_abs_error": 0.01,
             "detection": {"comparable": True, "within_tolerance": verdict == "consistent",
                           "matched_pairs": 2, "unmatched_reference": unmatched,
                           "unmatched_converted": 0, "threshold_crossings": 0,
                           "mean_matched_iou": 0.998 if not unmatched else None,
                           "original_coordinates": {"status": "mapped"}}},
            {"image": "image_02.png", "comparable": True, "within_tolerance": True,
             "normalized_mae": 0.0002, "cosine_similarity": 0.99998, "max_abs_error": 0.02,
             "detection": {"comparable": True, "within_tolerance": verdict == "consistent",
                           "matched_pairs": 1, "unmatched_reference": 0,
                           "unmatched_converted": 0, "threshold_crossings": 0,
                           "mean_matched_iou": 0.997,
                           "original_coordinates": {"status": "mapped"}}},
        ],
    }


def _stub_verify(monkeypatch, result=None, *, counter=None):
    from platform_core.deployment import numeric_consistency as numeric

    payload = json.loads(json.dumps(result or _stub_numeric_result()))

    def verify(*args, **kwargs):
        if counter is not None:
            counter["calls"] = counter.get("calls", 0) + 1
        return json.loads(json.dumps(payload))

    monkeypatch.setattr(numeric, "verify_images", verify)
    return verify


def test_complete_evidence_is_persisted_before_state_and_binds_conversion_identity(tmp_path, monkeypatch):
    from platform_core.deployment import numeric_consistency as numeric

    layout = _full_numeric_layout(tmp_path)
    _stub_verify(monkeypatch, _stub_numeric_result())
    observed = {}
    real_project = numeric.project_numeric_status

    def guard(directory, request, result):
        evidence_files = sorted((__import__("pathlib").Path(directory) / "evidence").glob("*.json"))
        observed["evidence_before_projection"] = len(evidence_files) == 1
        if evidence_files:
            observed["evidence_complete"] = bool(
                json.loads(evidence_files[0].read_text(encoding="utf-8"))["verification"]["content_digest"])
        return real_project(directory, request, result)

    monkeypatch.setattr(numeric, "project_numeric_status", guard)
    final = numeric.run_verification_directory(layout["verification"])
    assert observed == {"evidence_before_projection": True, "evidence_complete": True}
    result = json.loads((layout["verification"] / "result.json").read_text(encoding="utf-8"))
    verification = result["verification"]
    identity = verification["identity"]
    assert identity["status"] == "verified"
    assert identity["availability"] == {key: "present" for key in numeric.VERIFICATION_IDENTITY_FIELDS}
    assert identity["project_id"] == "p1"
    assert identity["algorithm_id"] == "a1"
    assert identity["version_id"] == "v1"
    assert identity["conversion_job_id"] == "conversion-full-1"
    assert identity["source_pt_sha256"] == layout["source_sha"]
    assert identity["onnx_sha256"] == layout["onnx_sha"]
    assert identity["target_artifact_sha256"] == layout["onnx_sha"]
    assert identity["manifest_digest"] == layout["manifest"]["manifest_digest"]
    assert identity["manifest_integrity"]["status"] == "digest_verified"
    samples = verification["sample_set"]
    assert samples["count"] == 2 and samples["status"] == "available"
    assert [row["name"] for row in samples["images"]] == layout["image_names"]
    for row in samples["images"]:
        assert row["sha256"] == numeric.sha256_file(layout["verification"] / "images" / row["name"])
    assert len(samples["digest"]) == 64
    parameters = verification["parameters"]
    assert parameters["precision"] == "fp32"
    assert parameters["confidence"] == 0.25 and parameters["nms_iou"] == 0.7
    assert parameters["imgsz"] == [64, 64] and parameters["batch"] == 1
    assert parameters["input_color_order"] == "rgb"
    assert len(parameters["digest"]) == 64
    summary = verification["result_summary"]
    assert summary["verdict"] == "consistent"
    assert summary["detection"]["matched_pairs"] == 3
    assert summary["metrics"]["cosine_similarity_min"] == 0.99998
    assert final["status_projection"]["status"] == "projected"
    job = json.loads(layout["job_path"].read_text(encoding="utf-8"))
    published = job["numeric_validation"]
    assert job["numeric_status"] == "consistent"
    assert published["verification_id"] == verification["verification_id"]
    assert published["binding_status"] == "verified"
    assert published["identity"]["manifest_digest"] == layout["manifest"]["manifest_digest"]
    assert published["identity"]["onnx_sha256"] == layout["onnx_sha"]
    assert published["sample_set"]["digest"] == samples["digest"]
    assert published["summary"]["verdict"] == "consistent"
    assert published["evidence_ref"].endswith(verification["verification_id"] + ".json")
    assert (layout["verification"] / "evidence" /
            (verification["verification_id"] + ".json")).is_file()


def test_publication_failure_after_evidence_leaves_state_unpublished_and_retry_converges(tmp_path, monkeypatch):
    from platform_core.deployment import numeric_consistency as numeric

    layout = _full_numeric_layout(tmp_path)
    counter = {}
    _stub_verify(monkeypatch, _stub_numeric_result(), counter=counter)
    real_project = numeric.project_numeric_status

    def crash(*args, **kwargs):
        raise RuntimeError("state write failed")

    monkeypatch.setattr(numeric, "project_numeric_status", crash)
    with pytest.raises(RuntimeError, match="state write failed"):
        numeric.run_verification_directory(layout["verification"])
    result = json.loads((layout["verification"] / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    evidence = result["verification"]
    assert evidence["content_digest"] and evidence["verification_id"]
    evidence_path = layout["verification"] / "evidence" / (evidence["verification_id"] + ".json")
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["verification"]["content_digest"] == evidence["content_digest"]
    job = json.loads(layout["job_path"].read_text(encoding="utf-8"))
    assert job.get("numeric_status") is None and not job.get("numeric_validation")
    # Restart: inference is never rerun, only the idempotent publication.
    monkeypatch.setattr(numeric, "project_numeric_status", real_project)
    recovered = numeric.run_verification_directory(layout["verification"])
    assert counter["calls"] == 1
    assert recovered["status_projection"]["status"] == "projected"
    job_after = json.loads(layout["job_path"].read_text(encoding="utf-8"))
    assert job_after["numeric_status"] == "consistent"
    assert job_after["numeric_validation"]["verification_id"] == evidence["verification_id"]
    # A further replay of the same identity result must not rewrite the summary.
    before_job = layout["job_path"].read_bytes()
    before_evidence = evidence_path.read_bytes()
    replay = numeric.run_verification_directory(layout["verification"])
    assert counter["calls"] == 1
    assert replay["status_projection"]["status"] == "already_projected"
    assert layout["job_path"].read_bytes() == before_job
    assert evidence_path.read_bytes() == before_evidence


def test_identity_change_after_publication_returns_stale_and_preserves_old_evidence(tmp_path, monkeypatch):
    from platform_core.deployment import numeric_consistency as numeric

    layout = _full_numeric_layout(tmp_path)
    _stub_verify(monkeypatch, _stub_numeric_result())
    numeric.run_verification_directory(layout["verification"])
    job = json.loads(layout["job_path"].read_text(encoding="utf-8"))
    published = dict(job["numeric_validation"])
    evidence_id = published["verification_id"]
    evidence_path = layout["verification"] / "evidence" / (evidence_id + ".json")
    before_evidence = evidence_path.read_bytes()
    before_result = json.loads((layout["verification"] / "result.json").read_text(encoding="utf-8"))
    # 1) The conversion record now claims another source identity.
    changed = json.loads(layout["job_path"].read_text(encoding="utf-8"))
    changed["source_trace"]["sha256"] = "b" * 64
    layout["job_path"].write_text(json.dumps(changed), encoding="utf-8")
    stale = numeric.reconcile_numeric_verification(layout["verification"])
    assert stale["status_projection"]["status"] == "stale"
    assert stale["status_projection"]["code"] == numeric.STALE_VERIFICATION_CODE
    after = json.loads(layout["job_path"].read_text(encoding="utf-8"))
    assert after["numeric_status"] == "consistent"
    assert after["numeric_validation"] == published
    assert evidence_path.read_bytes() == before_evidence
    assert stale["verification"]["content_digest"] == before_result["verification"]["content_digest"]
    # 2) The artifact bytes themselves changed (record/request unchanged).
    restored = json.loads(json.dumps(changed))
    restored["source_trace"]["sha256"] = layout["source_sha"]
    layout["job_path"].write_text(json.dumps(restored), encoding="utf-8")
    layout["onnx"].write_bytes(b"replaced-onnx-bytes")
    stale_again = numeric.reconcile_numeric_verification(layout["verification"])
    assert stale_again["status_projection"]["status"] == "stale"
    assert layout["job_path"].read_text(encoding="utf-8") and \
        json.loads(layout["job_path"].read_text(encoding="utf-8"))["numeric_validation"] == published
    assert evidence_path.read_bytes() == before_evidence


def test_conflicting_evidence_for_same_identity_fails_closed_without_overwriting(tmp_path, monkeypatch):
    from platform_core.deployment import numeric_consistency as numeric

    layout = _full_numeric_layout(tmp_path)
    _stub_verify(monkeypatch, _stub_numeric_result())
    numeric.run_verification_directory(layout["verification"])
    result_path = layout["verification"] / "result.json"
    first = json.loads(result_path.read_text(encoding="utf-8"))
    evidence_path = layout["verification"] / "evidence" / (first["verification"]["verification_id"] + ".json")
    before_evidence = evidence_path.read_bytes()
    before_job = layout["job_path"].read_bytes()
    result_path.unlink()  # force a full re-verification with the same identity/params
    _stub_verify(monkeypatch, _stub_numeric_result(verdict="difference_detected", unmatched=1))
    with pytest.raises(numeric.VerificationEvidenceConflict) as raised:
        numeric.run_verification_directory(layout["verification"])
    assert numeric.EVIDENCE_CONFLICT_CODE in str(raised.value)
    assert evidence_path.read_bytes() == before_evidence
    assert layout["job_path"].read_bytes() == before_job


_CONCURRENCY_CHILD = '''
import json, sys, time
from pathlib import Path
sys.path.insert(0, __ROOT__)
from platform_core.deployment import numeric_consistency as numeric

directory = Path(sys.argv[1])
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

def slow_verify(*args, **kwargs):
    time.sleep(0.5)
    return json.loads(json.dumps(payload))

numeric.verify_images = slow_verify
final = numeric.run_verification_directory(directory)
print(json.dumps({"projection": (final.get("status_projection") or {}).get("status"),
                  "verification_id": final["verification"]["verification_id"]}, ensure_ascii=False))
'''


def test_two_concurrent_verifications_of_same_identity_publish_exactly_once(tmp_path, monkeypatch):
    import subprocess
    import sys
    from platform_core.deployment import numeric_consistency as numeric

    first = _full_numeric_layout(tmp_path, directory_name="nv_0123456789abcdef01234567")
    second = tmp_path / "deployment" / "numeric-validations" / "nv_89abcdef0123456789abcdef"
    (second / "images").mkdir(parents=True)
    for name in first["image_names"]:
        (second / "images" / name).write_bytes((first["verification"] / "images" / name).read_bytes())
    receipt = dict(first["receipt"])
    receipt["id"] = second.name
    (second / "request.json").write_text(json.dumps(receipt), encoding="utf-8")
    script = tmp_path / "numeric_child.py"
    script.write_text(_CONCURRENCY_CHILD.replace("__ROOT__", repr(str(ROOT))), encoding="utf-8")
    stub = tmp_path / "stub-result.json"
    stub.write_text(json.dumps(_stub_numeric_result()), encoding="utf-8")
    processes = [
        subprocess.Popen([sys.executable, str(script), str(directory), str(stub)],
                         cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for directory in (first["verification"], second)
    ]
    outputs = [process.communicate(timeout=180) for process in processes]
    for process, (stdout, stderr) in zip(processes, outputs):
        assert process.returncode == 0, (stdout + stderr)[-8000:]
    parsed = [json.loads(stdout.strip().splitlines()[-1]) for stdout, _ in outputs]
    assert sorted(row["projection"] for row in parsed) == ["already_projected", "projected"]
    assert len({row["verification_id"] for row in parsed}) == 1
    job = json.loads(first["job_path"].read_text(encoding="utf-8"))
    assert job["numeric_status"] == "consistent"
    assert job["numeric_validation"]["verification_id"] == parsed[0]["verification_id"]
    assert job["numeric_validation"]["status"] == "completed"
