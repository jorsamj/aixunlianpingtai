from platform_core.task_runtime import TaskKind
from platform_core.worker_registry import build_worker_registration, resolve_worker_registration


def test_all_roles_skip_unimplemented_optional_packages_without_losing_real_handlers(tmp_path):
    handlers, capabilities = build_worker_registration(tmp_path, {"all"})
    assert TaskKind.VIDEO_FRAMES in handlers
    assert TaskKind.TRAINING in handlers
    assert TaskKind.TRAINING_PREPARE in handlers
    assert "opencv" in capabilities
    assert "training.ultralytics" in capabilities
    assert "training.prepare" in capabilities


def test_worker_registration_reports_roles_that_actually_loaded(tmp_path):
    registration = resolve_worker_registration(tmp_path, {"training"})

    assert registration.roles == frozenset({"training"})
    assert TaskKind.TRAINING in registration.handlers
    assert "training.ultralytics" in registration.capabilities


def test_remote_training_preparation_is_a_separate_background_role(tmp_path):
    registration = resolve_worker_registration(tmp_path, {"training-prep"})

    assert registration.roles == frozenset({"training-prep"})
    assert set(registration.handlers) == {TaskKind.TRAINING_PREPARE}
    assert registration.capabilities == frozenset({"training.prepare"})
