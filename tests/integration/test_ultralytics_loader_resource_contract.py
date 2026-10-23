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



def test_reference_preflight_blocks_download_and_restores_pinned_downloader(tmp_path, monkeypatch):
    """Exercise the real v8.4.127 downloader import seam without requiring a GPU."""
    from types import SimpleNamespace
    import ultralytics
    from ultralytics.engine import trainer
    from ultralytics.utils import downloads
    import ultralytics.utils as utils
    from platform_core.training_precision import _reference_amp_check

    check_file = tmp_path / "yolo26n.pt"
    check_file.write_bytes(b"fixture")
    (tmp_path / "bus.jpg").write_bytes(b"fixture")
    monkeypatch.setattr(utils, "ASSETS", tmp_path)
    loaded = []
    monkeypatch.setattr(ultralytics, "YOLO", lambda path: loaded.append(path) or object())

    class Model:
        def to(self, device):
            assert device == "cuda:0"
            return self
        def cpu(self):
            return self

    original_download = downloads.attempt_download_asset

    def assert_no_network(model):
        assert model is train_model.model
        # This is the actual downloader that torch_safe_load imports at runtime.
        with pytest.raises(FileNotFoundError, match="AMP_REFERENCE_DOWNLOAD_BLOCKED"):
            downloads.attempt_download_asset("missing-check-weight.pt")
        return True

    monkeypatch.setattr(trainer, "check_amp", assert_no_network)
    train_model = SimpleNamespace(model=Model())
    assert not _reference_amp_check(None, ultralytics, train_model, check_file)
    assert loaded == [str(check_file)]
    assert downloads.attempt_download_asset is original_download
    # Success is NOT claimed merely because a library function returned True:
    # the original checker must also have emitted its passing result.
