from platform_core.task_runtime import TaskKind
from platform_core.worker_registry import build_worker_registration


def test_all_roles_skip_unimplemented_optional_packages_without_losing_real_handlers(tmp_path):
    handlers, capabilities = build_worker_registration(tmp_path, {"all"})
    assert TaskKind.VIDEO_FRAMES in handlers
    assert TaskKind.TRAINING in handlers
    assert "opencv" in capabilities
    assert "training.ultralytics" in capabilities
