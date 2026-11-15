"""Admission tests: restricted source, params and no execution authority."""
import hashlib
from copy import deepcopy
import pytest
import onnx
from onnx import TensorProto, helper

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_onnx_cpu_pilot import (
    preflight_existing_onnx_cpu_pilot, materialize_cpu_pilot_snapshot,
)


def sample(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    src = folder / "model.onnx"
    graph = helper.make_graph(
        [helper.make_node("Identity", ["x"], ["y"])], "fixture",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 32, 32])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 3, 32, 32])])
    model = helper.make_model(graph, opset_imports=[helper.make_operatorsetid("", 12)])
    model.ir_version = 8
    onnx.save(model, src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    payload = {
        "schema_version": 1, "task_kind": "MODEL_CONVERSION",
        "transport": "object-storage-v1", "target": "onnx",
        "params": {"input_size": 32, "batch": 1, "opset": 12,
                   "dynamic": False, "simplify": False, "precision": "fp32"},
        "source": {"type": "object", "download": {
            "method": "GET", "file_name": src.name, "sha256": sha,
            "size_bytes": src.stat().st_size}},
        "source_trace": {"sha256": sha},
        "output": {"type": "object", "storage_ref": {},
                   "upload_protocol": "prepare-after-local-hash-v1"},
    }
    return payload, src


def test_narrow_preflight_never_grants_execution(tmp_path):
    payload, src = sample(tmp_path)
    result = preflight_existing_onnx_cpu_pilot(
        payload, source_file=src, trusted_workdir=tmp_path)
    assert result.source_sha256 == payload["source_trace"]["sha256"]
    assert result.runner_profile == "onnx-cpu-validate-v1"
    assert not result.production_launch_allowed
    assert not result.hardware_verified
    assert not result.trusted_stop_receipt_available


@pytest.mark.parametrize("field,value", [
    ("target", "rockchip"), ("target", "onnx; /bin/sh"),
    ("task_kind", "TRAINING"), ("transport", "direct-file"),
])
def test_wrong_scope_is_denied(tmp_path, field, value):
    payload, src = sample(tmp_path)
    payload[field] = value
    with pytest.raises(GrantRejected, match="SCOPE_UNSUPPORTED_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=src, trusted_workdir=tmp_path)


@pytest.mark.parametrize("field,value", [
    ("batch", 2), ("batch", True), ("input_size", 8192),
    ("opset", 18), ("dynamic", True), ("simplify", True),
    ("precision", "fp16"),
])
def test_non_cpu_or_expanded_parameters_are_denied(tmp_path, field, value):
    payload, src = sample(tmp_path)
    payload["params"][field] = value
    with pytest.raises(GrantRejected, match="PARAMS_UNSUPPORTED_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=src, trusted_workdir=tmp_path)


def test_extra_commands_paths_gpu_and_calibration_are_denied(tmp_path):
    payload, src = sample(tmp_path)
    for extra in ("command", "env", "cwd", "gpu_uuid", "calibration"):
        candidate = deepcopy(payload)
        candidate[extra] = "/bin/sh"
        with pytest.raises(GrantRejected, match="SCOPE_UNSUPPORTED_HOLD"):
            preflight_existing_onnx_cpu_pilot(
                candidate, source_file=src, trusted_workdir=tmp_path)
    payload["params"]["device"] = "cuda:0"
    with pytest.raises(GrantRejected, match="PARAMS_UNSUPPORTED_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=src, trusted_workdir=tmp_path)


def test_hash_size_suffix_and_file_boundary_rejected(tmp_path):
    payload, src = sample(tmp_path)
    for name, value in (("sha256", "f"*64), ("size_bytes", 1),
                        ("file_name", "model.pt")):
        candidate=deepcopy(payload)
        candidate["source"]["download"][name]=value
        with pytest.raises(GrantRejected):
            preflight_existing_onnx_cpu_pilot(
                candidate, source_file=src, trusted_workdir=tmp_path)
    outside=tmp_path / "outside.onnx"
    outside.write_bytes(src.read_bytes())
    with pytest.raises(GrantRejected, match="FILE_BOUNDARY_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=outside, trusted_workdir=tmp_path)
    src.unlink()
    src.symlink_to(outside)
    with pytest.raises(GrantRejected, match="FILE_BOUNDARY_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=src, trusted_workdir=tmp_path)


def replace_model(payload, src, model):
    data = model.SerializeToString()
    src.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    payload["source"]["download"].update(sha256=digest, size_bytes=len(data))
    payload["source_trace"]["sha256"] = digest


@pytest.mark.parametrize("nest", ["initializer", "nested", "attribute",
                                    "sparse", "training"])
def test_external_data_in_any_nested_tensor_must_hold(tmp_path, nest):
    payload, src = sample(tmp_path)
    model = onnx.load(src)
    t = TensorProto()
    t.name, t.data_type = "x", TensorProto.FLOAT
    t.dims.append(1)
    t.data_location = TensorProto.EXTERNAL
    entry = t.external_data.add()
    entry.key, entry.value = "location", "../../outside-data"
    if nest == "initializer":
        model.graph.initializer.add().CopyFrom(t)
    elif nest == "nested":
        g = helper.make_graph([], "nested", [], [], initializer=[t])
        model.graph.node[0].attribute.add().g.CopyFrom(g)
    elif nest == "attribute":
        model.graph.node[0].attribute.add().t.CopyFrom(t)
    elif nest == "sparse":
        model.graph.sparse_initializer.add().values.CopyFrom(t)
    else:
        model.training_info.add().initialization.CopyFrom(
            helper.make_graph([], "training", [], [], initializer=[t]))
    replace_model(payload, src, model)
    with pytest.raises(GrantRejected, match="ONNX_EXTERNAL_DATA_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=src, trusted_workdir=tmp_path)


def test_invalid_proto_is_not_accepted_by_sha_alone(tmp_path):
    payload, src = sample(tmp_path)
    raw = b"not a model protobuf"
    src.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    payload["source"]["download"].update(sha256=sha, size_bytes=len(raw))
    payload["source_trace"]["sha256"] = sha
    with pytest.raises(GrantRejected, match="ONNX_PROTO_INVALID_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=src, trusted_workdir=tmp_path)


def test_hardlink_must_hold(tmp_path):
    import os
    payload, src = sample(tmp_path)
    os.link(src, tmp_path / "second-hardlink")
    with pytest.raises(GrantRejected, match="FILE_BOUNDARY_HOLD"):
        preflight_existing_onnx_cpu_pilot(
            payload, source_file=src, trusted_workdir=tmp_path)


def test_pinned_bytes_snapshot_does_not_reopen_replaced_source(tmp_path):
    payload, src = sample(tmp_path)
    original = src.read_bytes()
    proof = preflight_existing_onnx_cpu_pilot(
        payload, source_file=src, trusted_workdir=tmp_path)
    src.unlink()
    src.write_bytes(b"attacker-replaced-after-preflight")
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    output = materialize_cpu_pilot_snapshot(proof, destination_dir=snapshot_dir)
    assert output.name == "verified.onnx"
    assert output.read_bytes() == original
    with pytest.raises(GrantRejected, match="SNAPSHOT_WRITE_HOLD"):
        materialize_cpu_pilot_snapshot(proof, destination_dir=snapshot_dir)
