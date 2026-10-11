from __future__ import annotations

from importlib.metadata import version

import pytest
from ultralytics.data.build import build_dataloader

from platform_core.training_metrics import effective_loader_resources


@pytest.mark.parametrize(
    ("train_image_count", "candidate_batch", "candidate_workers"),
    [
        (1, 100, 2),
        (11, 100, 2),
        (100, 50, 2),
        (10_000, 128, 2),
    ],
)
def test_platform_loader_resolution_matches_pinned_ultralytics_8_4_127(
    train_image_count: int,
    candidate_batch: int,
    candidate_workers: int,
) -> None:
    """Lock platform resource truth to the actual production DataLoader semantics."""
    assert version("ultralytics") == "8.4.127"

    expected = effective_loader_resources(
        train_image_count=train_image_count,
        batch=candidate_batch,
        workers=candidate_workers,
    )
    loader = build_dataloader(
        range(train_image_count),
        batch=candidate_batch,
        workers=candidate_workers,
        shuffle=False,
        rank=-1,
        drop_last=False,
        device="cpu",
    )
    try:
        assert loader.batch_size == expected["effective_batch"]
        assert loader.num_workers == expected["effective_workers"]
        assert len(loader) == expected["loader_batches"]
    finally:
        loader.close()


def test_tiny_dataset_case_matches_production_failure_shape() -> None:
    """The 11-image incident must resolve to one real batch and zero loader workers."""
    expected = effective_loader_resources(
        train_image_count=11,
        batch=100,
        workers=2,
    )
    loader = build_dataloader(
        range(11),
        batch=100,
        workers=2,
        shuffle=False,
        rank=-1,
        drop_last=False,
        device="cpu",
    )
    try:
        assert expected["effective_batch"] == 11
        assert expected["loader_batches"] == 1
        assert expected["effective_workers"] == 0
        assert loader.batch_size == 11
        assert len(loader) == 1
        assert loader.num_workers == 0
    finally:
        loader.close()



def test_installed_ultralytics_amp_checker_is_the_validated_pinned_api() -> None:
    """Real installed source check: keep scoped Worker interception version-specific."""
    import inspect
    from ultralytics.engine import trainer
    from ultralytics.utils import checks

    assert version("ultralytics") == "8.4.127"
    assert trainer.check_amp is checks.check_amp
    source = inspect.getsource(checks.check_amp)
    assert 'YOLO("yolo26n.pt")' in source
    assert "checks passed" in source
    assert "except ConnectionError" in source
    assert "checks skipped" in source


def test_missing_reference_with_pinned_library_never_enters_asset_download(tmp_path, monkeypatch):
    """Exercise preflight using the REAL installed Ultralytics module, not a stub."""
    from types import SimpleNamespace
    import ultralytics
    from platform_core import training_precision

    project = tmp_path / "projects" / "p"
    project.mkdir(parents=True)
    monkeypatch.delenv("MC_AMP_CHECK_MODEL", raising=False)
    monkeypatch.setattr(training_precision, "_local_amp_reference", lambda *args: None)
    invoked = []
    monkeypatch.setattr(training_precision, "cuda_numeric_amp_probe",
                        lambda t: invoked.append(t) or True)
    monkeypatch.setattr(training_precision, "_reference_amp_check",
                        lambda *args: pytest.fail("reference check must not start without local yolo26n.pt"))
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    result = training_precision.preflight_worker_amp(
        requested_amp=True, torch=fake_torch, ultralytics=ultralytics,
        train_model=object(), project_dir=project)
    assert invoked == [fake_torch]
    assert result.method == "cuda_numeric" and result.enabled and result.reference_model == ""
