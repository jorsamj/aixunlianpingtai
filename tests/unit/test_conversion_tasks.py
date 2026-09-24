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
