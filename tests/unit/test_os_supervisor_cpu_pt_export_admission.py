"""2D-2D2B2A: PT→ONNX CPU admission is not an OS execution grant."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import pytest

from platform_core.node_agent_executor_runtime import RemoteExecutionLease
from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_cpu_pt_export_admission import (
    FrozenPtExportAdmission, VerifiedPtBytes,
)

PT_BYTES = b"fake-pickle-bytes-not-to-be-loaded" * 3
DIGEST = hashlib.sha256(PT_BYTES).hexdigest()


def fake_lease(**overrides):
    payload = {
        "schema_version": 1,
        "task_kind": "MODEL_CONVERSION", "transport": "object-storage-v1",
        "target": "onnx",
        "params": {"input_size": 640, "batch": 1, "opset": 12,
                   "dynamic": False, "simplify": False},
        "source": {"type": "object", "artifact_id": "ci-source",
                   "download": {"method": "GET",
                                "url": "https://objects.example.test/test.pt",
                                "headers": {"X-Test-Signature": "ci-secret"},
                                "file_name": "source.pt",
                                "size_bytes": len(PT_BYTES), "sha256": DIGEST}},
        "source_trace": {"sha256": DIGEST, "source_id": "ci-version"},
        "output": {"type": "object",
                   "storage_ref": {"storage_source_id": "models",
                                   "object_key": "results/task/model.onnx",
                                   "file_name": "model.onnx"},
                   "upload_protocol": "prepare-after-local-hash-v1"},
    }
    payload.update(overrides.pop("payload_overrides", {}))
    return RemoteExecutionLease(
        task_id=overrides.pop("task_id", "conversion_cpu_987"),
        kind=overrides.pop("kind", "MODEL_CONVERSION"),
        project_id="ci", generation=overrides.pop("generation", 3),
        lease_token=overrides.pop("lease_token", "private-lease-token"),
        lease_expires_at="2030-01-01T00:00:00+00:00",
        worker_id=overrides.pop("worker_id", "agent:cpu-node"),
        payload=payload, assignment={}, transport={},
    )


def candidate(lease=None):
    return FrozenPtExportAdmission.from_central_lease(lease or fake_lease())


def test_frozen_pt_lease_fingerprints_original_central_attempt():
    l = fake_lease()
    c = candidate(l)
    assert c.task_id == l.task_id
    assert c.task_attempt == l.generation
    assert c.node_id == "cpu-node" and c.worker_id == "agent:cpu-node"
    assert c.execution_lease_sha256 == hashlib.sha256(
        l.lease_token.encode()).hexdigest()
    assert c.profile == "pt-to-onnx-cpu-untrusted-admission-v1"
    assert not c.production_launch_allowed
    assert not c.gpu_allowed
    assert not c.trusted_stop_receipt_available
    assert not c.result_publish_allowed
    assert "private-lease-token" not in repr(c)
    assert "objects.example.test" not in repr(c)
    with pytest.raises(FrozenInstanceError):
        c.input_size = 100


def test_exact_pt_bytes_and_canonical_nonexecutable_manifest():
    l = fake_lease()
    c = candidate(l)
    proof = c.verify_downloaded_stream([PT_BYTES[:5], PT_BYTES[5:]])
    assert proof == VerifiedPtBytes(DIGEST, len(PT_BYTES))
    assert not proof.pickle_safe
    assert not proof.model_runtime_verified
    manifest = c.freeze_nonexecutable_manifest(proof)
    m = json.loads(manifest)
    assert m["task_attempt"] == l.generation
    assert m["source"] == {
        "name": "source.pt", "sha256": DIGEST, "size_bytes": len(PT_BYTES)}
    assert m["target"]["kind"] == "onnx"
    assert m["execution_authorized"] is False
    assert m["untrusted_pt_pickle"] is True
    assert m["result_publish_allowed"] is False
    assert c.freeze_nonexecutable_manifest(proof) == manifest
    for forbidden in (b"https://", b"ci-secret", b"private-lease-token",
                      b"/bin/sh", b"argv", b"shell", b"gpu:0"):
        assert forbidden not in manifest
    with pytest.raises(GrantRejected, match="CENTRAL_SIGNED_PROFILE_NOT_ADMITTED_HOLD"):
        c.request_systemd_launch()
    with pytest.raises(GrantRejected, match="RESULT_TRANSACTION_NOT_ADMITTED_HOLD"):
        c.request_result_publish()


@pytest.mark.parametrize("parts", [
    [PT_BYTES[:-1]], [PT_BYTES + b"x"], [b"tampered" + PT_BYTES[8:]],
])
def test_pt_content_or_size_mismatch_holds(parts):
    with pytest.raises(GrantRejected, match="HOLD"):
        candidate().verify_downloaded_stream(parts)


@pytest.mark.parametrize("parts", [PT_BYTES, "bytes", [memoryview(PT_BYTES)],
                                     [bytearray(PT_BYTES)], [None]])
def test_stream_requires_exact_byte_chunks(parts):
    with pytest.raises(GrantRejected, match="HOLD"):
        candidate().verify_downloaded_stream(parts)


@pytest.mark.parametrize("field,value", [
    ("sha256", "0" * 64), ("size_bytes", 0), ("size_bytes", True),
    ("pickle_safe", True), ("model_runtime_verified", True),
    ("executable_grant_available", True),
])
def test_forged_download_proof_cannot_be_promoted(field, value):
    c = candidate()
    proof = VerifiedPtBytes(DIGEST, len(PT_BYTES))
    with pytest.raises(GrantRejected, match="HOLD"):
        c.freeze_nonexecutable_manifest(replace(proof, **{field: value}))


@pytest.mark.parametrize("changes", [
    {"kind": "TRAINING"},
    {"generation": 0},
    {"generation": True},
    {"task_id": "../escaped"},
    {"worker_id": "worker:local"},
    {"worker_id": "agent:../../outside"},
    {"lease_token": ""},
    {"payload_overrides": {"target": "rockchip"}},
    {"payload_overrides": {"transport": "local"}},
    {"payload_overrides": {"schema_version": True}},
    {"payload_overrides": {"command": "/bin/sh"}},
    {"payload_overrides": {"calibration": {"images": []}}},
])
def test_unsupported_central_scope_is_rejected(changes):
    with pytest.raises(GrantRejected, match="HOLD"):
        candidate(fake_lease(**changes))


@pytest.mark.parametrize("updates", [
    {"batch": 2}, {"batch": True}, {"opset": 13}, {"opset": True},
    {"dynamic": True}, {"dynamic": 0}, {"simplify": True},
    {"input_size": 8192}, {"input_size": "640"},
    {"shell": "echo pwn"}, {"env": {"PYTHONPATH": "/tmp"}},
])
def test_pt_export_params_are_fixed_cpu_only(updates):
    l = fake_lease()
    params = {**l.payload["params"], **updates}
    with pytest.raises(GrantRejected, match="HOLD"):
        candidate(fake_lease(payload_overrides={"params": params}))


@pytest.mark.parametrize("changes", [
    {"file_name": "../unsafe.pt"}, {"file_name": "source.onnx"},
    {"file_name": "source.pth"}, {"file_name": "evil..pt"},
    {"size_bytes": 0}, {"size_bytes": True},
    {"size_bytes": 513 * 1024 * 1024},
    {"sha256": "0"*64}, {"sha256": "zz"},
    {"method": "POST"}, {"url": "file:///etc/passwd"},
    {"url": "http://not-tls/test.pt"},
    {"url": "https://user:secret@example.test/pt"},
    {"url": "https://example.test/pt#fragment"},
    {"shell": "/bin/sh"},
])
def test_source_transport_and_name_fail_closed(changes):
    l = fake_lease()
    p = dict(l.payload)
    p["source"] = {**p["source"], "download": {
        **p["source"]["download"], **changes}}
    with pytest.raises(GrantRejected, match="HOLD"):
        candidate(fake_lease(payload_overrides={"source": p["source"]}))


def test_source_trace_digest_must_match_downloaded_bytes():
    with pytest.raises(GrantRejected, match="HOLD"):
        candidate(fake_lease(payload_overrides={
            "source_trace": {"sha256": "0"*64}}))


@pytest.mark.parametrize("name", [
    "../out.onnx", "model.pt", "model..onnx", "/tmp/out.onnx", "",
])
def test_result_name_cannot_be_untrusted_path(name):
    l = fake_lease()
    output = dict(l.payload["output"])
    output["storage_ref"] = {
        **output["storage_ref"], "file_name": name,
    }
    with pytest.raises(GrantRejected, match="HOLD"):
        candidate(fake_lease(payload_overrides={"output": output}))


def test_download_headers_are_not_copied_or_allowed_to_inject_lines():
    l = fake_lease()
    src = dict(l.payload["source"])
    for headers in ({"X-Test": "a\r\nInjected: yes"},
                    {"bad\nheader": "safe"}):
        source = {**src, "download": {
            **src["download"], "headers": headers,
        }}
        with pytest.raises(GrantRejected, match="HOLD"):
            candidate(fake_lease(payload_overrides={"source": source}))
