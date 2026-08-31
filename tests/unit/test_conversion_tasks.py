from platform_core.deployment.conversion_tasks import conversion_outcome
from platform_core.task_runtime import TaskStatus


def test_vendor_artifact_without_board_runtime_is_not_passed():
    assert conversion_outcome({"status": "done", "target": "rockchip", "hardware_verified": False}) is TaskStatus.BLOCKED_BY_HARDWARE
    assert conversion_outcome({"status": "done", "target": "ascend", "hardware_verified": False}) is TaskStatus.BLOCKED_BY_HARDWARE


def test_runtime_verified_onnx_conversion_can_succeed():
    assert conversion_outcome({"status": "done", "target": "onnx"}) is TaskStatus.SUCCEEDED


def test_missing_vendor_sdk_is_environment_blocked():
    assert conversion_outcome({"status": "failed", "error_code": "RKNN_TOOLKIT_NOT_FOUND"}) is TaskStatus.BLOCKED_BY_ENVIRONMENT
