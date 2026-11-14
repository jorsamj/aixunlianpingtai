"""TQ-01 v2 grouped multilabel holdout regressions.

Legacy split requests are intentionally left on the historic replay path.
"""
import hashlib

import pytest

from platform_core.training_splits import SplitMode, SplitRequest, build_split_manifest


def row(image_id, labels, *, source=None, near=None, negative=False):
    return {
        "id": image_id,
        "annotation_state": "confirmed_empty" if negative else "annotated",
        "annotation_scope": ["*"] if negative else list(labels),
        "boxes": [] if negative else [{"label": label} for label in labels],
        "content_sha256": hashlib.sha256(image_id.encode("utf-8")).hexdigest(),
        "stored_name": f"{image_id}.jpg",
        "video_task_id": source,
        "near_duplicate_group_id": near,
    }


def make_request(rows, *, experiment=20, validation=20):
    return SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(item["id"] for item in rows),
        experiment_percent=experiment,
        validation_percent=validation,
    )


def role_for(manifest, image_id):
    return next(role for role, ids in manifest.ids.items() if image_id in ids)


def test_multilabel_split_covers_all_roles_when_independent_components_allow():
    rows = [
        row(f"fire-{i}", ["fire"], source=f"fire-camera-{i}")
        for i in range(6)
    ] + [
        row(f"smoke-{i}", ["smoke"], source=f"smoke-camera-{i}")
        for i in range(6)
    ] + [
        row(f"both-{i}", ["fire", "smoke"], source=f"both-camera-{i}")
        for i in range(6)
    ] + [
        row(f"negative-{i}", [], negative=True, source=f"negative-camera-{i}")
        for i in range(6)
    ]
    manifest = build_split_manifest(rows, make_request(rows), seed=99,
                                    split_strategy="multilabel_grouped_v2")
    assert manifest.requested["split_strategy"] == "multilabel_grouped_v2"
    for role in ("train", "validation", "test"):
        role_rows = [r for r in rows if r["id"] in manifest.ids[role]]
        labels = {box["label"] for r in role_rows for box in r["boxes"]}
        assert labels == {"fire", "smoke"}, (role, manifest.ids)
        assert any(r["annotation_state"] == "confirmed_empty" for r in role_rows)
    assert build_split_manifest(rows, make_request(rows), seed=99,
                                split_strategy="multilabel_grouped_v2").ids == manifest.ids


def test_rare_two_component_class_remains_train_and_validation_not_test():
    rows = [row(f"fire-{i}", ["fire"]) for i in range(15)]
    rows.extend([row(f"rare-{i}", ["sleep"]) for i in range(2)])
    manifest = build_split_manifest(rows, make_request(rows), seed=4,
                                    split_strategy="multilabel_grouped_v2")
    assert {"rare-0", "rare-1"} <= set(manifest.ids["train"]) | set(manifest.ids["validation"])
    assert len({"rare-0", "rare-1"} & set(manifest.ids["train"])) == 1
    assert len({"rare-0", "rare-1"} & set(manifest.ids["validation"])) == 1
    assert not {"rare-0", "rare-1"} & set(manifest.ids["test"])


def test_video_and_near_duplicate_component_never_cross_roles():
    rows = [
        row(f"fire-{i}", ["fire"], source=f"fire-session-{i}")
        for i in range(12)
    ]
    rows[0]["video_task_id"] = "same-video"
    rows[1]["video_task_id"] = "same-video"
    rows[2]["near_duplicate_group_id"] = "near-a"
    rows[3]["near_duplicate_group_id"] = "near-a"
    rows[4]["near_duplicate_group_id"] = "near-a"
    manifest = build_split_manifest(rows, make_request(rows), seed=13,
                                    split_strategy="multilabel_grouped_v2")
    assert role_for(manifest, "fire-0") == role_for(manifest, "fire-1")
    assert len({role_for(manifest, f"fire-{i}") for i in (2, 3, 4)}) == 1


def test_independent_fixed_test_stays_exact_and_cannot_accept_connected_training():
    rows = [row(f"fire-{i}", ["fire"], source=f"session-{i}") for i in range(12)]
    req = SplitRequest(mode=SplitMode.INDEPENDENT_TEST_SET,
                       train_image_ids=tuple(r["id"] for r in rows[:-2]),
                       test_image_ids=("fire-10", "fire-11"), validation_percent=20)
    manifest = build_split_manifest(rows, req, seed=5,
                                    split_strategy="multilabel_grouped_v2")
    assert manifest.ids["test"] == ("fire-10", "fire-11")
    rows[0]["video_task_id"] = "session-10"
    with pytest.raises(ValueError, match="leakage"):
        build_split_manifest(rows, req, seed=5, split_strategy="multilabel_grouped_v2")


def test_legacy_manifest_still_uses_existing_replay_contract():
    rows = [row(f"fire-{i}", ["fire"]) for i in range(20)]
    req = make_request(rows, experiment=25)
    implicit = build_split_manifest(rows, req, seed=42)
    explicit = build_split_manifest(rows, req, seed=42, split_strategy="legacy_v1")
    assert implicit == explicit
    assert "split_strategy" not in implicit.requested


def test_v2_scales_to_20k_disjoint_components_and_keeps_target_sizes():
    rows = [row(f"fire-{i}", ["fire", "smoke"] if i % 17 == 0 else ["fire"])
            for i in range(20_000)]
    req = make_request(rows)
    manifest = build_split_manifest(rows, req, seed=11,
                                    split_strategy="multilabel_grouped_v2")
    assert manifest.counts == {"train": 12_000, "validation": 4_000,
                               "test": 4_000, "total": 20_000}
    assert len({image_id for group in manifest.ids.values() for image_id in group}) == 20_000
    for role in ("train", "validation", "test"):
        assert any(int(image_id.split("-")[-1]) % 17 == 0
                   for image_id in manifest.ids[role])
