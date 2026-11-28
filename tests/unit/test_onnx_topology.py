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


# ---------------------------------------------------------------------------
# N5.1: FP16 Cast->Conv chain with float16 Initializer and Constant nodes.
# The order-only repair must not change tensor edges, Cast attributes, float16
# weight bytes or Constant tensor attributes; output must stay bit-identical.
# ---------------------------------------------------------------------------
def _fp16_conv_constant_model(tmp_path, *, broken=True):
    height = width = 96
    inp = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, height, width])
    out = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 2, height, width])
    input_cast = helper.make_node(
        "Cast", ["images"], ["x16"], to=TensorProto.FLOAT16, name="graph_input_cast")
    conv = helper.make_node(
        "Conv", ["x16", "w16"], ["conv16"], name="/model.0/conv/Conv")
    constant = helper.make_node(
        "Constant", [], ["c16"], name="fp16_bias_constant",
        value=numpy_helper.from_array(np.full((1, 2, 1, 1), 0.25, dtype=np.float16), name="c16_value"))
    add = helper.make_node("Add", ["conv16", "c16"], ["sum16"], name="fp16_add")
    output_cast = helper.make_node(
        "Cast", ["sum16"], ["output"], to=TensorProto.FLOAT, name="graph_output_cast")
    initializer = [
        numpy_helper.from_array(np.full((2, 3, 1, 1), 0.5, dtype=np.float16), "w16"),
    ]
    ordered = [input_cast, constant, conv, add, output_cast]
    bad = [conv, output_cast, constant, add, input_cast]
    graph = helper.make_graph(
        bad if broken else ordered, "fp16_cast_conv_constant", [inp], [out], initializer)
    model = helper.make_model(
        graph, opset_imports=[helper.make_operatorsetid("", 12)],
    )
    model.ir_version = min(model.ir_version, 8)
    path = tmp_path / ("fp16_bad" if broken else "fp16_good")
    path = path.with_suffix(".onnx")
    onnx.save(model, str(path))
    return path


def test_fp16_cast_conv_constant_reorder_preserves_bytes_and_output(tmp_path):
    ort = pytest.importorskip("onnxruntime")
    original = _fp16_conv_constant_model(tmp_path)
    expected = _fp16_conv_constant_model(tmp_path, broken=False)
    with pytest.raises(onnx.checker.ValidationError):
        onnx.checker.check_model(str(original))
    before = original.read_bytes()
    raw = onnx.load(str(original))
    result, evidence = repair_onnx_topology(original, tmp_path)
    assert result != original
    assert evidence["status"] == "reordered"
    assert evidence["applied"] is True
    assert evidence["moved_nodes"] >= 4
    assert evidence["checker"] == "passed"
    assert original.read_bytes() == before
    corrected = onnx.load(str(result))
    onnx.checker.check_model(str(result))
    # Node protobuf bytes (Cast attributes included) and the float16 Initializer
    # are preserved as an exact multiset / byte sequence; only order changed.
    assert sorted(n.SerializeToString() for n in raw.graph.node) == sorted(
        n.SerializeToString() for n in corrected.graph.node)
    assert [t.SerializeToString() for t in raw.graph.initializer] == [
        t.SerializeToString() for t in corrected.graph.initializer]
    assert {t.data_type for t in corrected.graph.initializer} == {TensorProto.FLOAT16}
    casts = [n for n in corrected.graph.node if n.op_type == "Cast"]
    assert {n.attribute[0].i for n in casts} == {TensorProto.FLOAT16, TensorProto.FLOAT}
    constants = [n for n in corrected.graph.node if n.op_type == "Constant"]
    assert len(constants) == 1
    value_attr = next(a for a in constants[0].attribute if a.name == "value")
    assert value_attr.t.data_type == TensorProto.FLOAT16
    assert value_attr.t.SerializeToString() == \
        raw_node_constant_bytes(raw, "fp16_bias_constant")
    # The float16 Cast node must be produced before its Conv consumer.
    ops = [n.op_type for n in corrected.graph.node]
    assert ops.index("Cast") < ops.index("Conv")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    left = ort.InferenceSession(str(expected), sess_options=options, providers=["CPUExecutionProvider"])
    right = ort.InferenceSession(str(result), sess_options=options, providers=["CPUExecutionProvider"])
    data = np.random.default_rng(23).random((1, 3, 96, 96)).astype(np.float32)
    assert [meta.type for meta in right.get_inputs()] == ["tensor(float)"]
    assert [meta.type for meta in right.get_outputs()] == ["tensor(float)"]
    np.testing.assert_array_equal(
        left.run(None, {"images": data})[0], right.run(None, {"images": data})[0])


def raw_node_constant_bytes(model, node_name: str) -> bytes:
    node = next(n for n in model.graph.node if n.name == node_name)
    value = next(a for a in node.attribute if a.name == "value")
    return value.t.SerializeToString()


def test_fp16_cast_conv_constant_already_ordered_is_untouched(tmp_path):
    correct = _fp16_conv_constant_model(tmp_path, broken=False)
    digest = hashlib.sha256(correct.read_bytes()).hexdigest()
    result, evidence = repair_onnx_topology(correct, tmp_path)
    assert result == correct
    assert evidence["applied"] is False
    assert hashlib.sha256(correct.read_bytes()).hexdigest() == digest
