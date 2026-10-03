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
def test_platform_loader_resolution_matches_ultralytics_8_4_143(
    train_image_count: int,
    candidate_batch: int,
    candidate_workers: int,
) -> None:
    """Lock platform resource truth to the actual production DataLoader semantics."""
    assert version("ultralytics") == "8.4.143"

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
