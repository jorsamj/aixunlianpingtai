"""Numerical verification must distinguish measured agreement from missing evidence."""
import numpy as np
import pytest

from platform_core.deployment.numeric_consistency import (
    compare_tensors, make_input, validate_paths,
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
