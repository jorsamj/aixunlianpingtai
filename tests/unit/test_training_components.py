import pytest

from platform_core.training_splits import SplitMode, SplitRequest, build_split_manifest


def image(image_id, content_hash, *, group="", video="", source_group="", boxes=None, **extra):
    row = {
        "id": image_id,
        "dataset_id": "source",
        "content_sha256": content_hash,
        "group_id": group,
        "video_task_id": video,
        "source_group_id": source_group,
        "processing_status": "processed",
        "stored_name": f"{image_id}.jpg",
        "annotation_state": "annotated",
        "annotated": True,
        "boxes": boxes if boxes is not None else [
            {"label": "fire", "class_id": 0, "x1": 1, "y1": 2, "x2": 10, "y2": 12}
        ],
    }
    row.update(extra)
    return row


def random_request(*ids):
    return SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(ids),
        experiment_percent=20,
        validation_percent=20,
    )


def test_identical_content_and_annotation_is_canonicalized_before_split():
    rows = [
        image("a", "same"),
        image("b", "same"),
        image("c", "hc"),
        image("d", "hd"),
        image("e", "he"),
        image("f", "hf"),
        image("g", "hg"),
    ]
    manifest = build_split_manifest(
        rows, random_request("a", "b", "c", "d", "e", "f", "g"), seed=7
    )

    assigned = set().union(*(set(ids) for ids in manifest.ids.values()))
    assert "a" in assigned
    assert "b" not in assigned
    assert manifest.excluded_duplicate_ids == ("b",)
    assert manifest.duplicate_groups == {"same": ("a", "b")}
    assert manifest.counts["total"] == 6


def test_duplicate_content_with_different_annotations_is_rejected_before_split():
    rows = [
        image("a", "same"),
        image(
            "b",
            "same",
            boxes=[
                {"label": "fire", "class_id": 0, "x1": 4, "y1": 5, "x2": 14, "y2": 15}
            ],
        ),
        image("c", "hc"),
        image("d", "hd"),
        image("e", "he"),
        image("f", "hf"),
    ]

    with pytest.raises(ValueError, match="duplicate_annotation_conflict"):
        build_split_manifest(
            rows, random_request("a", "b", "c", "d", "e", "f"), seed=3
        )


def test_legacy_missing_scope_matches_explicit_scope_when_boxes_are_identical():
    rows = [
        image("legacy", "same"),
        image("new", "same", annotation_scope=["fire"]),
        image("c", "hc"),
        image("d", "hd"),
        image("e", "he"),
        image("f", "hf"),
        image("g", "hg"),
    ]

    manifest = build_split_manifest(
        rows,
        random_request("legacy", "new", "c", "d", "e", "f", "g"),
        seed=13,
    )

    assert manifest.excluded_duplicate_ids == ("new",)
    assert manifest.duplicate_groups == {"same": ("legacy", "new")}


def test_component_relations_are_transitive_across_source_fields():
    rows = [
        image("a", "ha", group="capture-a"),
        image("b", "hb", group="capture-a", video="video-7"),
        image("c", "hc", video="video-7"),
        image("d", "hd", group="capture-d"),
        image("e", "he", group="capture-e"),
        image("f", "hf", group="capture-f"),
        image("g", "hg", group="capture-g"),
        image("h", "hh", group="capture-h"),
    ]
    manifest = build_split_manifest(
        rows, random_request("a", "b", "c", "d", "e", "f", "g", "h"), seed=11
    )
    roles = {
        image_id: role
        for role, image_ids in manifest.ids.items()
        for image_id in image_ids
    }

    assert roles["a"] == roles["b"] == roles["c"]
    assert manifest.groups["a"] == manifest.groups["b"] == manifest.groups["c"]


def test_camera_relation_is_scoped_to_same_capture_session():
    rows = [
        image("a", "ha", camera_id="cam-1", session_id="morning"),
        image("b", "hb", camera_id="cam-1", session_id="morning"),
        image("c", "hc", camera_id="cam-1", session_id="evening"),
        image("d", "hd", camera_id="cam-2", session_id="morning"),
        image("e", "he"),
        image("f", "hf"),
        image("g", "hg"),
        image("h", "hh"),
    ]
    manifest = build_split_manifest(
        rows, random_request("a", "b", "c", "d", "e", "f", "g", "h"), seed=15
    )

    assert manifest.groups["a"] == manifest.groups["b"]
    assert manifest.groups["a"] != manifest.groups["c"]
    assert manifest.groups["a"] != manifest.groups["d"]


def test_file_identity_is_an_inseparable_component_relation():
    rows = [
        image("a", "ha", stored_name="shared.JPG"),
        image("b", "hb", stored_name="shared.jpg"),
        image("c", "hc"),
        image("d", "hd"),
        image("e", "he"),
        image("f", "hf"),
    ]
    manifest = build_split_manifest(
        rows, random_request("a", "b", "c", "d", "e", "f"), seed=9
    )
    roles = {
        image_id: role
        for role, image_ids in manifest.ids.items()
        for image_id in image_ids
    }
    assert roles["a"] == roles["b"]


def test_identical_duplicate_cannot_bridge_explicit_train_and_test_roles():
    rows = [
        image("train-copy", "same"),
        image("test-copy", "same"),
        image("a", "ha"),
        image("b", "hb"),
    ]
    request = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=("train-copy", "a", "b"),
        test_image_ids=("test-copy",),
        validation_percent=50,
    )

    with pytest.raises(ValueError, match="content hash leakage"):
        build_split_manifest(rows, request, seed=1)
