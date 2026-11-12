"""Real ONNX protobuf and CPU Runtime regressions for order-only topology repair."""
from __future__ import annotations

import copy
import hashlib

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
from onnx import TensorProto, helper, numpy_helper
from platform_core.conversion import ConversionError
from platform_core.onnx_topology import repair_onnx_topology


def _model(tmp_path, *, fp16=False, height=640, width=640, broken=True):
    value_type = TensorProto.FLOAT16 if fp16 else TensorProto.FLOAT
    inp = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, height, width])
    out = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3 if fp16 else 1, height, width])
    if fp16:
        # Two independent Cast nodes both appear AFTER the consuming Add.
        first = helper.make_node("Cast", ["images"], ["cast_a"], to=value_type, name="cast_a")
        second = helper.make_node("Cast", ["images"], ["cast_b"], to=value_type, name="cast_b")
        add = helper.make_node("Add", ["cast_a", "cast_b"], ["sum"], name="add")
        add_bias = helper.make_node("Add", ["sum", "bias"], ["biased"], name="add_bias")
        last = helper.make_node("Cast", ["biased"], ["output"], to=TensorProto.FLOAT, name="output_cast")
        initializer = [numpy_helper.from_array(np.array(0.1, dtype=np.float16), "bias")]
        ordered = [first, second, add, add_bias, last]
        bad = [add, last, add_bias, second, first]
    else:
        first = helper.make_node("Cast", ["images"], ["graph_input_cast_0"], to=TensorProto.FLOAT, name="input_cast")
        conv = helper.make_node("Conv", ["graph_input_cast_0", "w"], ["conv"], name="/model.0/conv/Conv")
        last = helper.make_node("Identity", ["conv"], ["output"], name="output_identity")
        initializer = [numpy_helper.from_array(np.full((1, 3, 1, 1), .25, np.float32), "w")]
        ordered = [first, conv, last]
        bad = [conv, last, first]
    model = helper.make_model(
        helper.make_graph(bad if broken else ordered, "topology_regression", [inp], [out], initializer),
        opset_imports=[helper.make_operatorsetid("", 12)],
    )
    model.ir_version = min(model.ir_version, 8)
    prop = model.metadata_props.add()
    prop.key, prop.value = "original", "untouched"
    path = tmp_path / ("bad" if broken else "good")
    path = path.with_suffix(".onnx")
    onnx.save(model, str(path))
    return path


@pytest.mark.parametrize("height,width,fp16", [(640, 640, False), (640, 640, True), (800, 800, True)])
def test_real_topology_reorder_checker_runtime_and_semantics(tmp_path, height, width, fp16):
    ort = pytest.importorskip("onnxruntime")
    original = _model(tmp_path, fp16=fp16, height=height, width=width)
    expected = _model(tmp_path, fp16=fp16, height=height, width=width, broken=False)
    with pytest.raises(onnx.checker.ValidationError):
        onnx.checker.check_model(str(original))
    before = original.read_bytes()
    raw = onnx.load(str(original))
    result, evidence = repair_onnx_topology(original, tmp_path)
    assert result != original and evidence["status"] == "reordered"
    assert evidence["moved_nodes"] >= 2
    assert original.read_bytes() == before
    corrected = onnx.load(str(result))
    onnx.checker.check_model(str(result))
    assert sorted(n.SerializeToString() for n in raw.graph.node) == sorted(
        n.SerializeToString() for n in corrected.graph.node
    )
    assert corrected.metadata_props == raw.metadata_props
    assert corrected.opset_import == raw.opset_import
    assert corrected.graph.input == raw.graph.input
    assert corrected.graph.output == raw.graph.output
    assert corrected.graph.initializer == raw.graph.initializer
    assert corrected.graph.node[0].name in ("input_cast", "cast_a", "cast_b")
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 1
    lhs = ort.InferenceSession(str(expected), sess_options=opt, providers=["CPUExecutionProvider"])
    rhs = ort.InferenceSession(str(result), sess_options=opt, providers=["CPUExecutionProvider"])
    data = np.random.default_rng(17).random((1, 3, height, width)).astype(np.float32)
    np.testing.assert_array_equal(lhs.run(None, {"images": data})[0], rhs.run(None, {"images": data})[0])


def test_already_correct_model_is_not_rewritten(tmp_path):
    correct = _model(tmp_path, broken=False)
    digest = hashlib.sha256(correct.read_bytes()).hexdigest()
    result, evidence = repair_onnx_topology(correct, tmp_path)
    assert result == correct and evidence["applied"] is False
    assert hashlib.sha256(correct.read_bytes()).hexdigest() == digest


def test_missing_producer_rejected(tmp_path):
    path = _model(tmp_path)
    model = onnx.load(str(path))
    model.graph.node[0].input[0] = "does_not_exist"
    onnx.save(model, str(path))
    with pytest.raises(ConversionError, match="缺少生产者") as exc:
        repair_onnx_topology(path, tmp_path)
    assert exc.value.code == "ONNX_GRAPH_TOPOLOGY_INVALID"


def test_duplicate_producer_rejected(tmp_path):
    path = _model(tmp_path)
    model = onnx.load(str(path))
    model.graph.node[1].output[0] = "conv"
    onnx.save(model, str(path))
    with pytest.raises(ConversionError, match="SSA") as exc:
        repair_onnx_topology(path, tmp_path)
    assert exc.value.code == "ONNX_GRAPH_TOPOLOGY_INVALID"


def test_cycle_is_rejected_without_materializing_output(tmp_path):
    path = _model(tmp_path)
    model = onnx.load(str(path))
    model.graph.node[2].input[0] = "conv"
    model.graph.node[0].input[0] = "graph_input_cast_0"
    model.graph.node[2].output[0] = "graph_input_cast_0"
    onnx.save(model, str(path))
    with pytest.raises(ConversionError, match="循环") as exc:
        repair_onnx_topology(path, tmp_path)
    assert exc.value.code == "ONNX_GRAPH_TOPOLOGY_INVALID"


def test_subgraph_rejected_if_reorder_required(tmp_path):
    path = _model(tmp_path)
    model = onnx.load(str(path))
    body = helper.make_graph([], "nested", [], [])
    model.graph.node[1].attribute.append(helper.make_attribute("nested", body))
    onnx.save(model, str(path))
    with pytest.raises(ConversionError, match="子图"):
        repair_onnx_topology(path, tmp_path)


def test_external_weight_rejected_if_reorder_required(tmp_path):
    path = _model(tmp_path)
    model = onnx.load(str(path))
    model.graph.initializer[0].data_location = TensorProto.EXTERNAL
    model.graph.initializer[0].ClearField("raw_data")
    onnx.save(model, str(path))
    with pytest.raises(ConversionError, match="外部权重"):
        repair_onnx_topology(path, tmp_path)


def test_corrupt_or_mismatched_graph_never_reuses_old_repair(tmp_path):
    path = _model(tmp_path)
    stale = tmp_path / "bad_topology_sorted.onnx"
    stale.write_bytes(b"old-stale-file")
    model = onnx.load(str(path))
    model.graph.node[0].input[0] = "missing"
    onnx.save(model, str(path))
    with pytest.raises(ConversionError):
        repair_onnx_topology(path, tmp_path)
    assert stale.read_bytes() == b"old-stale-file"


def test_prepare_onnx_repairs_before_color_adapter_and_runtime_checks(tmp_path, monkeypatch):
    ort = pytest.importorskip("onnxruntime")
    import deployment_worker as worker
    source = _model(tmp_path, fp16=True, height=640, width=640)
    work = tmp_path / "work"
    work.mkdir()
    params = {"kind": "onnx", "precision": "fp16", "batch": 1, "input_size": 640}
    result = worker.prepare_onnx(source, work, {}, params, tmp_path / "run.log")
    assert params["onnx_topology_evidence"]["applied"] is True
    check = worker.validate_onnx_runtime(result, params, tmp_path / "run.log", expected_precision="fp16")
    assert check["checker"] == "passed" and check["output_count"] == 1
    assert "FLOAT16" in check["floating_tensor_types"]


def test_runtime_load_failure_has_its_own_error_code(tmp_path, monkeypatch):
    ort = pytest.importorskip("onnxruntime")
    import deployment_worker as worker
    path = _model(tmp_path, broken=False)
    monkeypatch.setattr(ort, "InferenceSession", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad runtime")))
    with pytest.raises(ConversionError) as exc:
        worker.validate_onnx_runtime(path, {"kind": "onnx", "input_size": 640}, tmp_path / "log.txt")
    assert exc.value.code == "ONNX_RUNTIME_LOAD_FAILED"
