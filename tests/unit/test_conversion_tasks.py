import json
from types import SimpleNamespace

from platform_core.deployment.conversion_tasks import (
    _finalize_conversion_job,
    conversion_outcome,
)
from platform_core.task_runtime import TaskStatus


def test_vendor_artifact_without_board_runtime_is_not_passed():
    assert conversion_outcome({"status": "done", "target": "rockchip", "hardware_verified": False}) is TaskStatus.BLOCKED_BY_HARDWARE
    assert conversion_outcome({"status": "done", "target": "ascend", "hardware_verified": False}) is TaskStatus.BLOCKED_BY_HARDWARE


def test_runtime_verified_onnx_conversion_can_succeed():
    assert conversion_outcome({"status": "done", "target": "onnx"}) is TaskStatus.SUCCEEDED


def test_missing_vendor_sdk_is_environment_blocked():
    assert conversion_outcome({"status": "failed", "error_code": "RKNN_TOOLKIT_NOT_FOUND"}) is TaskStatus.BLOCKED_BY_ENVIRONMENT


def test_deliverable_conversion_finalization_requests_existing_publish_owner(
    tmp_path, monkeypatch
):
    requests = []
    monkeypatch.setattr(
        "platform_core.external_publish_request.request_external_auto_publish_for_conversion_if_enabled",
        lambda **kwargs: requests.append(kwargs) or True,
    )

    class FakeArtifacts:
        def __init__(self):
            self.values = {}

        def atomic_write_json(self, task_id, relative_path, value):
            self.values[(task_id, relative_path)] = value

    class FakeContext:
        def __init__(self):
            self.task = SimpleNamespace(task_id="convert-rk", project_id="p1")
            self.artifacts = FakeArtifacts()
            self.last_heartbeat = None

        def assert_current_execution(self):
            return self.task

        def heartbeat(self, **kwargs):
            self.last_heartbeat = kwargs

    job_dir = tmp_path / "projects" / "p1" / "deploy" / "jobs" / "convert-rk"
    job_dir.mkdir(parents=True)
    job_file = job_dir / "job.json"
    job = {
        "id": "convert-rk",
        "status": "done",
        "target": "rockchip",
        "source_trace": {"algorithm_id": "a1", "version_id": "v1"},
        "params": {"chip": "rk3568"},
        "hardware_verified": False,
        "outputs": [{"path": str(job_dir / "artifacts" / "model_rk3568.rknn")}],
    }
    context = FakeContext()

    status, result_ref = _finalize_conversion_job(
        context,
        job_file,
        job,
        recovered_from_completed_work=False,
        data_dir=tmp_path,
    )

    committed = json.loads(job_file.read_text(encoding="utf-8"))
    assert status is TaskStatus.BLOCKED_BY_HARDWARE
    assert result_ref == "conversion/result.json"
    assert committed["status"] == "blocked_by_hardware"
    assert committed["params"]["chip"] == "rk3568"
    assert len(requests) == 1
    assert requests[0]["project_id"] == "p1"
    assert requests[0]["conversion_job"]["status"] == "blocked_by_hardware"


def _numeric_layout(tmp_path):
    deploy = tmp_path / "deployment"
    job_id = "conversion-numeric-1"
    verification = deploy / "numeric-validations" / "nv_0123456789abcdef01234567"
    (verification / "images").mkdir(parents=True)
    (verification / "images" / "frame.png").write_bytes(b"frozen-image")
    job_dir = deploy / "jobs" / job_id
    job_dir.mkdir(parents=True)
    job_path = job_dir / "job.json"
    job_path.write_text(json.dumps({"id": job_id, "project_id": "p1", "status": "done",
                                    "target": "onnx"}), encoding="utf-8")
    source = job_dir / "source.pt"
    onnx = job_dir / "model.onnx"
    source.write_bytes(b"frozen-pt")
    onnx.write_bytes(b"frozen-onnx")
    receipt = {"id": verification.name, "project_id": "p1", "conversion_job_id": job_id,
               "request_id": "numeric-recovery-0001", "precision": "fp32",
               "confidence": 0.25, "nms_iou": 0.7, "input_color_order": "rgb",
               "source_path": str(source), "onnx_path": str(onnx),
               "source_sha256": __import__("hashlib").sha256(b"frozen-pt").hexdigest(),
               "onnx_sha256": __import__("hashlib").sha256(b"frozen-onnx").hexdigest(),
               "image_names": ["frame.png"]}
    (verification / "request.json").write_text(json.dumps(receipt), encoding="utf-8")
    return verification, job_path


def test_crash_between_evidence_and_state_converges_through_durable_recovery(tmp_path, monkeypatch):
    from platform_core.deployment import numeric_consistency as numeric
    from platform_core.deployment.conversion_tasks import run_numeric_verification

    verification, job_path = _numeric_layout(tmp_path)
    calls = {"verify": 0}

    def stub_verify(*args, **kwargs):
        calls["verify"] += 1
        return {"status": "completed", "verdict": "consistent", "raw_verdict": "consistent",
                "detection_status": "consistent", "sample_count": 1,
                "protocol": numeric.PROTOCOL, "precision": "fp32",
                "created_at": "2026-11-24T00:00:00+00:00",
                "completed_at": "2026-11-24T00:00:00+00:00",
                "hardware_verified": False, "ground_truth_used": False}

    monkeypatch.setattr(numeric, "verify_images", stub_verify)
    real_project = numeric.project_numeric_status
    monkeypatch.setattr(numeric, "project_numeric_status",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("crash window")))
    import pytest
    with pytest.raises(RuntimeError, match="crash window"):
        numeric.run_verification_directory(verification)
    # Evidence is complete and immutable; the conversion state is untouched.
    result = json.loads((verification / "result.json").read_text(encoding="utf-8"))
    evidence = result["verification"]
    evidence_path = verification / "evidence" / (evidence["verification_id"] + ".json")
    assert evidence_path.is_file()
    assert json.loads(job_path.read_text(encoding="utf-8")).get("numeric_status") is None

    monkeypatch.setattr(numeric, "project_numeric_status", real_project)
    worker = tmp_path / "worker.py"
    worker.write_text("# the durable recovery path must not launch the worker again\n", encoding="utf-8")

    class FakeArtifacts:
        def __init__(self):
            self.values = {}

        def atomic_write_json(self, task_id, relative_path, value):
            self.values[(task_id, relative_path)] = value

    class FakeContext:
        def __init__(self):
            self.task = SimpleNamespace(task_id="numeric-task")
            self.artifacts = FakeArtifacts()
            self.heartbeats = []

        def assert_current_execution(self):
            return self.task

        def heartbeat(self, **kwargs):
            self.heartbeats.append(kwargs)

    context = FakeContext()
    status, result_ref = run_numeric_verification(
        context, {"verification_dir": str(verification), "worker_path": str(worker)})
    assert status is TaskStatus.SUCCEEDED
    assert calls["verify"] == 1  # inference is never rerun on recovery
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["numeric_status"] == "consistent"
    assert job["numeric_validation"]["verification_id"] == evidence["verification_id"]
    published = context.artifacts.values[(context.task.task_id, result_ref)]
    assert published["status_projection"]["status"] == "projected"
    assert context.heartbeats[-1]["progress"] == 100
    # A second recovery is idempotent: no rewrite of the published summary.
    before = job_path.read_bytes()
    again = FakeContext()
    status_again, _ = run_numeric_verification(
        again, {"verification_dir": str(verification), "worker_path": str(worker)})
    assert status_again is TaskStatus.SUCCEEDED and calls["verify"] == 1
    assert job_path.read_bytes() == before


# ---------------------------------------------------------------------------
# N5.2: all conversion job.json writers (worker progress/finalize + numeric
# evidence projection) must share the same lock identity and whole-file
# replacement contract. The projection fields must never be lost or torn.
# ---------------------------------------------------------------------------
def test_conversion_job_writers_share_lock_and_keep_numeric_projection(tmp_path):
    import deployment_worker as worker
    from platform_core.deployment.conversion_tasks import _write

    job_path = tmp_path / "job.json"
    projection = {
        "verification_id": "nv_" + "1" * 32, "status": "completed",
        "verdict": "consistent", "content_digest": "d" * 64,
        "evidence_ref": "numeric-validations/nv_x/evidence/nv_x.json",
    }
    job_path.write_text(json.dumps({
        "id": "convert-1", "status": "running", "progress": 10,
        "numeric_status": "consistent", "publication_status": "numeric_consistent_delivery_evidence_incomplete",
        "numeric_validation": projection,
    }), encoding="utf-8")
    # The worker progress writer must keep an existing numeric projection intact
    # and must not leave a torn temporary record behind.
    updated = worker.update(job_path, progress=55, stage="导出 ONNX")
    on_disk = json.loads(job_path.read_text(encoding="utf-8"))
    assert updated["progress"] == 55 and on_disk["progress"] == 55
    assert on_disk["numeric_status"] == "consistent"
    assert on_disk["numeric_validation"] == projection
    assert not list(job_path.parent.glob(".job.json.*.tmp"))
    # The durable finalizer writes through the same lock + atomic replacement.
    _write(job_path, {**on_disk, "status": "done", "progress": 100})
    committed = json.loads(job_path.read_text(encoding="utf-8"))
    assert committed["status"] == "done" and committed["progress"] == 100
    assert committed["numeric_validation"] == projection
    assert not list(job_path.parent.glob(".job.json.*.tmp"))
    # Evidence-ref identity survives both writers byte-for-byte.
    assert committed["numeric_validation"]["verification_id"] == projection["verification_id"]
    assert committed["numeric_validation"]["content_digest"] == projection["content_digest"]
