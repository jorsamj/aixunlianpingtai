"""Regression tests for explicit model input RGB/BGR conversion."""
from pathlib import Path

import pytest

from platform_core.color_adapter import ColorAdapterError, adapt_onnx_color_input, color_contract
from platform_core.conversion import validate_target


def test_legacy_and_explicit_color_contract():
    assert color_contract({}) is None
    assert color_contract({"input_color_order": "rgb"}) == {
        "source_color_order": "rgb", "input_color_order": "rgb"
    }
    assert validate_target("onnx", {"input_color_order": "bgr"})["input_color_order"] == "bgr"
    with pytest.raises(ColorAdapterError):
        color_contract({"input_color_order": "bgr; rm -rf /"})
    with pytest.raises(ColorAdapterError):
        color_contract({"source_color_order": "BGR"})
    with pytest.raises(ValueError):
        validate_target("paddle_inference", {"input_color_order": "bgr"})


def _onnx_identity(tmp_path: Path, channels: int = 3) -> Path:
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    inp = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, channels, 32, 32])
    out = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, channels, 32, 32])
    graph = helper.make_graph([helper.make_node("Identity", ["images"], ["output"])], "rgb_test", [inp], [out])
    model = helper.make_model(graph, opset_imports=[helper.make_operatorsetid("", 12)])
    # CI environments may contain older ONNX Runtime; pin model to compatible IR.
    model.ir_version = min(model.ir_version, 8)
    path = tmp_path / "source.onnx"
    onnx.save(model, str(path))
    return path


def test_bgr_adapter_is_real_and_numerically_equivalent(tmp_path):
    np = pytest.importorskip("numpy")
    ort = pytest.importorskip("onnxruntime")
    source = _onnx_identity(tmp_path)
    before = source.read_bytes()
    output, evidence = adapt_onnx_color_input(
        source, tmp_path / "out", {"source_color_order": "rgb", "input_color_order": "bgr"}
    )
    assert source.read_bytes() == before
    assert output != source
    assert evidence["applied"] is True
    assert evidence["verified"] is True
    reference = ort.InferenceSession(str(source), providers=["CPUExecutionProvider"])
    adapted = ort.InferenceSession(str(output), providers=["CPUExecutionProvider"])
    rgb = np.arange(3 * 32 * 32, dtype=np.float32).reshape(1, 3, 32, 32) / 3000
    bgr = np.ascontiguousarray(rgb[:, ::-1, :, :])
    np.testing.assert_array_equal(
        reference.run(None, {"images": rgb})[0],
        adapted.run(None, {"images": bgr})[0],
    )


def test_rgb_default_is_unmodified(tmp_path):
    source = _onnx_identity(tmp_path)
    output, evidence = adapt_onnx_color_input(
        source, tmp_path / "out", {"source_color_order": "rgb", "input_color_order": "rgb"}
    )
    assert output == source
    assert evidence["applied"] is False


def test_wrong_channels_fail_closed(tmp_path):
    pytest.importorskip("onnxruntime")
    source = _onnx_identity(tmp_path, channels=1)
    with pytest.raises(ColorAdapterError, match="通道"):
        adapt_onnx_color_input(source, tmp_path / "out", {"input_color_order": "bgr"})
