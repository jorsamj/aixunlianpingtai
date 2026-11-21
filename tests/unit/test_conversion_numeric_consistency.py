"""Numerical verification must distinguish measured agreement from missing evidence."""
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
    receipt = json.loads((directory / "result.json").read_text())
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
