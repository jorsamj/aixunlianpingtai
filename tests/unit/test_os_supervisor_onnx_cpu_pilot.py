"""Admission tests: restricted source, params and no execution authority."""
import hashlib
from copy import deepcopy
import pytest

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_onnx_cpu_pilot import preflight_existing_onnx_cpu_pilot


def sample(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    src = folder / "model.onnx"
    src.write_bytes(b"test-bytes-not-a-real-onnx")
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
