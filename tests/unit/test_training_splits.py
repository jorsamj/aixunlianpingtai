import pytest

from platform_core.training_splits import SplitMode, SplitRequest, build_split_manifest


def image(image_id, dataset, content_hash, group, source="upload"):
    return {
        "id": image_id,
        "dataset_id": dataset,
        "content_sha256": content_hash,
        "group_id": group,
        "source_type": source,
        "processing_status": "processed",
        "stored_name": f"{image_id}.jpg",
        "boxes": [{"label": "fire"}],
    }


def test_mode_a_uses_independent_test_and_derives_validation_from_training_pool():
    rows = [image(str(index), "train-ds", f"h{index}", f"g{index}") for index in range(10)]
    rows.append(image("test", "test-ds", "ht", "gt"))
    request = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_dataset_ids=("train-ds",),
        test_dataset_ids=("test-ds",),
        validation_percent=20,
    )
    manifest = build_split_manifest(rows, request, seed=19)
    assert manifest.counts == {"train": 8, "validation": 2, "test": 1, "total": 11}
    assert manifest.requested["test_source"] == "independent_dataset"
    assert manifest.ids["test"] == ("test",)


def test_mode_b_draws_test_first_then_validation_without_leakage():
    rows = [image(str(index), "source", f"h{index}", f"g{index}") for index in range(20)]
    request = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_dataset_ids=("source",),
        experiment_percent=25,
        validation_percent=20,
    )
    manifest = build_split_manifest(rows, request, seed=42)
    assert manifest.counts == {"train": 12, "validation": 3, "test": 5, "total": 20}
    assert manifest.requested["test_source"] == "random_from_training_pool"
    assert not set(manifest.ids["train"]) & set(manifest.ids["validation"])
    assert not set(manifest.ids["test"]) & (
        set(manifest.ids["train"]) | set(manifest.ids["validation"])
    )
    assert build_split_manifest(rows, request, seed=42).ids == manifest.ids


def test_content_hash_crossing_splits_is_rejected():
    rows = [
        image("a", "train", "same", "group-a"),
        image("b", "test", "same", "group-b"),
        image("c", "train", "unique", "group-c"),
    ]
    request = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_dataset_ids=("train",),
        test_dataset_ids=("test",),
        validation_percent=50,
    )
    with pytest.raises(ValueError, match="content hash leakage"):
        build_split_manifest(rows, request, seed=1)


def test_group_is_never_split_between_roles():
    rows = [
        image("a", "source", "ha", "video-1"),
        image("b", "source", "hb", "video-1"),
        image("c", "source", "hc", "video-2"),
        image("d", "source", "hd", "video-3"),
        image("e", "source", "he", "video-4"),
        image("f", "source", "hf", "video-5"),
    ]
    manifest = build_split_manifest(
        rows,
        SplitRequest(
            mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
            train_dataset_ids=("source",),
            experiment_percent=20,
            validation_percent=20,
        ),
        seed=7,
    )
    roles = {
        image_id: role
        for role, image_ids in manifest.ids.items()
        for image_id in image_ids
    }
    assert roles["a"] == roles["b"]


@pytest.mark.parametrize("field,value", [("validation_percent", 0), ("experiment_percent", 100)])
def test_invalid_percentages_are_rejected(field, value):
    values = {
        "mode": SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        "train_dataset_ids": ("source",),
        "experiment_percent": 20,
        "validation_percent": 20,
    }
    values[field] = value
    with pytest.raises(ValueError, match=field):
        SplitRequest(**values)
