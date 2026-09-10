import hashlib
import json
from types import SimpleNamespace

from platform_core.deployment.conversion_tasks import _publish_result, conversion_outcome
from platform_core.task_runtime import ArtifactStore, TaskStatus


def test_vendor_conversion_succeeds_even_when_board_validation_is_pending():
    assert conversion_outcome({"status": "done", "target": "rockchip", "hardware_verified": False}) is TaskStatus.SUCCEEDED
    assert conversion_outcome({"status": "done", "target": "ascend", "hardware_verified": False}) is TaskStatus.SUCCEEDED


def test_runtime_verified_onnx_conversion_can_succeed():
    assert conversion_outcome({"status": "done", "target": "onnx"}) is TaskStatus.SUCCEEDED


def test_missing_vendor_sdk_is_environment_blocked():
    assert conversion_outcome({"status": "failed", "error_code": "RKNN_TOOLKIT_NOT_FOUND"}) is TaskStatus.BLOCKED_BY_ENVIRONMENT


def test_cancelled_conversion_is_cancelled():
    assert conversion_outcome({"status": "stopped", "target": "rockchip"}) is TaskStatus.CANCELLED


def _completed_vendor_job(tmp_path):
    job_dir = tmp_path / "conversion-job"
    artifacts = job_dir / "artifacts"
    artifacts.mkdir(parents=True)
    output = artifacts / "model.rknn"
    payload = b"real-rknn-output"
    output.write_bytes(payload)
    job = {
        "id": "convert-1",
        "status": "done",
        "target": "rockchip",
        "hardware_verified": False,
        "manifest_path": str(artifacts / "manifest.json"),
        "outputs": [{"name": output.name, "path": str(output)}],
    }
    (artifacts / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": job["id"],
                "target": {"kind": "rockchip"},
                "outputs": [
                    {
                        "name": output.name,
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    job_file = job_dir / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    job["_job_file"] = str(job_file)
    context = SimpleNamespace(
        task=SimpleNamespace(task_id="task-1"),
        artifacts=ArtifactStore(tmp_path / "task-artifacts"),
    )
    return job, context, output, job_file


def test_publish_success_verifies_artifact_and_keeps_board_pending(tmp_path):
    job, context, _output, job_file = _completed_vendor_job(tmp_path)

    status, result_ref = _publish_result(context, job)

    assert status is TaskStatus.SUCCEEDED
    assert result_ref == "conversion/result.json"
    persisted = json.loads(job_file.read_text(encoding="utf-8"))
    assert persisted["artifact_verified"] is True
    assert persisted["conversion_status"] == "converted"
    assert persisted["board_validation_status"] == "pending"
    assert "板端待验证" in persisted["stage"]
    result = context.artifacts.read_json("task-1", result_ref)
    assert result["artifact_verified"] is True
    assert result["board_validation_status"] == "pending"


def test_done_job_with_tampered_artifact_is_failed(tmp_path):
    job, context, output, job_file = _completed_vendor_job(tmp_path)
    output.write_bytes(b"tampered")

    status, result_ref = _publish_result(context, job)

    assert status is TaskStatus.FAILED
    persisted = json.loads(job_file.read_text(encoding="utf-8"))
    assert persisted["status"] == "failed"
    assert persisted["artifact_verified"] is False
    assert persisted["conversion_status"] == "artifact_verification_failed"
    assert persisted["error_code"] == "CONVERSION_ARTIFACT_VERIFICATION_FAILED"
    result = context.artifacts.read_json("task-1", result_ref)
    assert result["artifact_verified"] is False


def test_done_job_rejects_manifest_output_path_escape(tmp_path):
    job, context, _output, _job_file = _completed_vendor_job(tmp_path)
    outside = tmp_path / "outside.rknn"
    outside.write_bytes(b"outside")
    manifest = json.loads(open(job["manifest_path"], "r", encoding="utf-8").read())
    manifest["outputs"] = [
        {
            "name": "../outside.rknn",
            "size_bytes": outside.stat().st_size,
            "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
        }
    ]
    open(job["manifest_path"], "w", encoding="utf-8").write(json.dumps(manifest))

    status, _result_ref = _publish_result(context, job)

    assert status is TaskStatus.FAILED
    assert job["error_code"] == "CONVERSION_ARTIFACT_VERIFICATION_FAILED"
