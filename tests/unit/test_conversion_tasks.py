from platform_core.deployment.conversion_tasks import conversion_outcome
from platform_core.task_runtime import TaskStatus


def test_vendor_conversion_succeeds_even_when_board_validation_is_pending():
    assert conversion_outcome({"status": "done", "target": "rockchip", "hardware_verified": False}) is TaskStatus.SUCCEEDED
    assert conversion_outcome({"status": "done", "target": "ascend", "hardware_verified": False}) is TaskStatus.SUCCEEDED


def test_runtime_verified_onnx_conversion_can_succeed():
    assert conversion_outcome({"status": "done", "target": "onnx"}) is TaskStatus.SUCCEEDED


def test_missing_vendor_sdk_is_environment_blocked():
    assert conversion_outcome({"status": "failed", "error_code": "RKNN_TOOLKIT_NOT_FOUND"}) is TaskStatus.BLOCKED_BY_ENVIRONMENT


def test_cancelled_conversion_is_cancelled():
    assert conversion_outcome({"status": "stopped", "target": "rockchip"}) is TaskStatus.CANCELLED
