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


def test_mode_a_uses_exact_independent_test_images_and_derives_validation_from_selected_training_images():
    rows = [image(str(index), "train-ds", f"h{index}", f"g{index}") for index in range(10)]
    rows.append(image("test", "test-ds", "ht", "gt"))
    rows.append(image("not-selected", "train-ds", "hidden", "hidden-group"))
    request = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=tuple(str(index) for index in range(10)),
        test_image_ids=("test",),
        validation_percent=20,
    )
    manifest = build_split_manifest(rows, request, seed=19)
    assert manifest.counts == {"train": 8, "validation": 2, "test": 1, "total": 11}
    assert manifest.requested["test_source"] == "independent_materials"
    assert manifest.ids["test"] == ("test",)
    assert "not-selected" not in set().union(*map(set, manifest.ids.values()))


def test_mode_b_draws_test_first_then_validation_without_leakage():
    rows = [image(str(index), "source", f"h{index}", f"g{index}") for index in range(20)]
    request = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(str(index) for index in range(20)),
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
        train_image_ids=("a", "c"),
        test_image_ids=("b",),
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
            train_image_ids=("a", "b", "c", "d", "e", "f"),
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
        "train_image_ids": ("a", "b", "c"),
        "experiment_percent": 20,
        "validation_percent": 20,
    }
    values[field] = value
    with pytest.raises(ValueError, match=field):
        SplitRequest(**values)


def test_missing_requested_material_is_rejected_instead_of_expanding_a_dataset():
    rows = [image("a", "shared", "ha", "ga"), image("b", "shared", "hb", "gb")]
    request = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=("a", "missing"),
        experiment_percent=20,
        validation_percent=20,
    )

    with pytest.raises(ValueError, match="不存在"):
        build_split_manifest(rows, request, seed=7)


def test_train_and_independent_test_material_cannot_overlap():
    with pytest.raises(ValueError, match="不能重复"):
        SplitRequest(
            mode=SplitMode.INDEPENDENT_TEST_SET,
            train_image_ids=("a", "b"),
            test_image_ids=("b",),
            validation_percent=20,
        )


def test_random_test_split_preserves_two_source_groups_for_train_and_validation():
    rows = [
        image("a", "unused", "ha", "ga"),
        image("b", "unused", "hb", "gb"),
        image("c", "unused", "hc", "gc"),
    ]
    manifest = build_split_manifest(
        rows,
        SplitRequest(
            mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
            train_image_ids=("a", "b", "c"),
            experiment_percent=60,
            validation_percent=50,
        ),
        seed=3,
    )
    assert manifest.counts == {"train": 1, "validation": 1, "test": 1, "total": 3}


def test_unannotated_material_without_boxes_is_rejected():
    rows = [
        image("a", "unused", "ha", "ga"),
        image("b", "unused", "hb", "gb"),
        image("c", "unused", "hc", "gc"),
    ]
    rows[1]["boxes"] = []
    rows[1]["annotation_state"] = "unannotated"
    request = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=("a", "b", "c"),
        experiment_percent=20,
        validation_percent=20,
    )
    with pytest.raises(ValueError, match="确认负样本"):
        build_split_manifest(rows, request, seed=4)


def test_confirmed_empty_material_is_a_valid_negative_sample():
    rows = [
        image("a", "unused", "ha", "ga"),
        image("b", "unused", "hb", "gb"),
        image("c", "unused", "hc", "gc"),
        image("d", "unused", "hd", "gd"),
        image("e", "unused", "he", "ge"),
        image("negative", "unused", "hn", "gn"),
    ]
    rows[-1]["boxes"] = []
    rows[-1]["annotation_state"] = "confirmed_empty"
    rows[-1]["annotation_scope"] = ["fire"]
    rows[-1]["annotated"] = True
    request = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(row["id"] for row in rows),
        experiment_percent=20,
        validation_percent=20,
    )

    manifest = build_split_manifest(rows, request, seed=4)
    assert "negative" in set().union(*(set(ids) for ids in manifest.ids.values()))


def test_legacy_confirmed_empty_without_scope_uses_global_scope_compatibility():
    rows = [
        image("a", "unused", "ha", "ga"),
        image("b", "unused", "hb", "gb"),
        image("c", "unused", "hc", "gc"),
        image("d", "unused", "hd", "gd"),
        image("e", "unused", "he", "ge"),
        image("negative", "unused", "hn", "gn"),
    ]
    rows[-1]["boxes"] = []
    rows[-1]["annotation_state"] = "confirmed_empty"
    rows[-1]["annotated"] = True

    manifest = build_split_manifest(
        rows,
        SplitRequest(
            mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
            train_image_ids=tuple(row["id"] for row in rows),
            experiment_percent=20,
            validation_percent=20,
        ),
        seed=5,
    )
    assert "negative" in set().union(*(set(ids) for ids in manifest.ids.values()))
