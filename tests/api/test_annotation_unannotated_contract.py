"""An explicitly cleared GT is pending work, never a reviewed negative."""
import pytest

import app as app_module


BOX = {"id": "last-box", "label": "fire", "x1": 10, "y1": 10,
       "x2": 80, "y2": 90}


def _initial(pid, image):
    return app_module.write_annotation(
        pid, image["id"], [BOX], "annotated",
        annotation_scope=["fire", "smoke"],
    )


def _post(client, pid, image, initial, **overrides):
    payload = {
        "boxes": [], "annotation_state": "unannotated",
        "expected_version": initial["version"],
        "source_content_sha256": image["content_sha256"],
        **overrides,
    }
    return client.post(f"/api/projects/{pid}/annotations/{image['id']}", json=payload)


def test_delete_last_box_persists_pending_and_clears_review_evidence(client, seeded_project):
    pid, image = seeded_project
    initial = _initial(pid, image)
    response = _post(client, pid, image, initial, reviewed_label_codes=["fire"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["annotation"]["version"] == initial["version"] + 1
    assert body["annotation"]["annotation_state"] == "unannotated"
    assert body["annotation"]["boxes"] == []
    assert body["annotation"]["annotation_scope"] == []
    assert body["reviewed_label_codes_added"] == []
    assert body["review_evidence"]["annotation_scope"] == []
    assert body["image"]["annotation_state"] == "unannotated"
    assert body["image"]["annotated"] is False
    assert body["image"]["box_count"] == 0
    reloaded = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert reloaded["annotation"] == body["annotation"]
    assert app_module._v50_annotation_repository(pid).get(image["id"])["annotation_scope"] == []


def test_pending_state_cannot_contain_boxes(client, seeded_project):
    pid, image = seeded_project
    initial = _initial(pid, image)
    response = _post(client, pid, image, initial, boxes=[BOX])
    assert response.status_code == 422
    assert response.json()["code"] == "ANNOTATION_STATE_BOXES_MISMATCH"
    assert app_module.read_annotation(pid, image["id"])["version"] == initial["version"]


def test_confirmed_empty_requires_current_explicit_review_even_with_old_scope(client, seeded_project):
    pid, image = seeded_project
    initial = _initial(pid, image)
    response = _post(client, pid, image, initial, annotation_state="confirmed_empty")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ANNOTATION_REVIEW_LABEL_REQUIRED"
    assert app_module.read_annotation(pid, image["id"])["version"] == initial["version"]


@pytest.mark.parametrize(("overrides", "code", "status"), [
    ({"expected_version": 0}, "ANNOTATION_CONCURRENT_MODIFICATION", 409),
    ({"expected_version": None}, "ANNOTATION_EXPECTED_VERSION_REQUIRED", 422),
    ({"source_content_sha256": "f" * 64}, "ANNOTATION_MATERIAL_GENERATION_CHANGED", 409),
    ({"source_content_sha256": None}, "ANNOTATION_MATERIAL_GENERATION_REQUIRED", 422),
    ({"reviewed_label_codes": ["retired"]}, "ANNOTATION_LABEL_STATE_CHANGED", 409),
    ({"reviewed_label_codes": ["*"]}, "ANNOTATION_REVIEW_SCOPE_WILDCARD_FORBIDDEN", 422),
])
def test_pending_save_keeps_version_sha_and_label_guards(client, seeded_project, overrides, code, status):
    pid, image = seeded_project
    initial = _initial(pid, image)
    response = _post(client, pid, image, initial, **overrides)
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert app_module.read_annotation(pid, image["id"])["content_digest"] == initial["content_digest"]


def test_new_negative_scope_does_not_reuse_former_positive_review(client, seeded_project):
    pid, image = seeded_project
    initial = _initial(pid, image)
    response = _post(client, pid, image, initial, annotation_state="confirmed_empty",
                     reviewed_label_codes=["smoke"])
    assert response.status_code == 200, response.text
    assert response.json()["annotation"]["annotation_scope"] == ["smoke"]


def _row(pid, image):
    return {**app_module.material_store(pid).get(image["id"]),
            **app_module.read_annotation(pid, image["id"]), "id": image["id"]}


def _manifest(row):
    from platform_core.training_splits import SplitManifest, SplitMode
    iid = row["id"]
    return SplitManifest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        ids={"train": (iid,), "validation": (), "test": ()},
        counts={"train": 1, "validation": 0, "test": 0, "total": 1},
        requested={}, actual_ratios={"train": 1.0, "validation": 0.0, "test": 0.0},
        groups={iid: "single"}, content_hashes={iid: row["content_sha256"]},
        test_seed=1, validation_seed=2,
    )


def test_cleared_gt_excluded_from_supervision_and_cannot_be_empty_yolo(client, seeded_project):
    from platform_core.snapshots import build_snapshot
    from platform_core.training_splits import SplitMode, SplitRequest
    from platform_core.training_tasks import resolve_training_selection

    pid, image = seeded_project
    initial = _initial(pid, image)
    materials = app_module.material_store(pid)
    retained = {**materials.get(image["id"]), "id": "retained-positive"}
    materials.upsert(retained)
    app_module.write_annotation(pid, retained["id"], [BOX], "annotated",
                                annotation_scope=["fire", "smoke"])
    response = _post(client, pid, image, initial)
    assert response.status_code == 200, response.text
    pending = _row(pid, image)
    request = SplitRequest(mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
                           train_image_ids=(image["id"], retained["id"]), experiment_percent=20)
    resolution = resolve_training_selection(app_module.project_dir(pid), request)
    assert resolution.pending_annotation_image_ids == (image["id"],)
    assert resolution.effective_split.train_image_ids == (retained["id"],)
    assert [row["id"] for row in resolution.effective_images] == [retained["id"]]
    with pytest.raises(ValueError):
        build_snapshot([pending], _manifest(pending), [{"code": "fire", "class_id": 0}])
    with pytest.raises(ValueError):
        resolve_training_selection(app_module.project_dir(pid), SplitRequest(
            mode=SplitMode.INDEPENDENT_TEST_SET, train_image_ids=(retained["id"],),
            test_image_ids=(image["id"],)))


def test_frozen_gt_history_unchanged_and_explicit_negative_exports_empty_yolo(
    client, seeded_project, tmp_path,
):
    from platform_core.snapshots import build_snapshot, persist_snapshot
    from platform_core.training_tasks import materialize_portable_dataset

    pid, image = seeded_project
    initial = _initial(pid, image)
    before = _row(pid, image)
    schema = [{"code": "fire", "class_id": 0}, {"code": "smoke", "class_id": 1}]
    frozen = build_snapshot([before], _manifest(before), schema)
    frozen_path = persist_snapshot(tmp_path / "history", frozen)
    frozen_bytes = frozen_path.read_bytes()
    cleared = _post(client, pid, image, initial)
    assert cleared.status_code == 200, cleared.text
    assert frozen_path.read_bytes() == frozen_bytes
    # Re-export the frozen rows; current GT clearing cannot rewrite a historical task.
    source = app_module.project_dir(pid) / "uploads" / image["stored_name"]
    bundle = materialize_portable_dataset(tmp_path / "historical-task", frozen, [before],
                                          lambda _row: source, safety_reserve_bytes=0)
    label = bundle / "dataset" / "labels" / "train" / f"{image['id']}.txt"
    assert label.read_text(encoding="utf-8").strip().startswith("0 ")
    confirmed = _post(client, pid, image, cleared.json()["annotation"],
                      annotation_state="confirmed_empty", reviewed_label_codes=["fire", "smoke"])
    assert confirmed.status_code == 200, confirmed.text
    negative = _row(pid, image)
    negative_snapshot = build_snapshot([negative], _manifest(negative), schema)
    bundle = materialize_portable_dataset(tmp_path / "negative-task", negative_snapshot, [negative],
                                          lambda _row: source, safety_reserve_bytes=0)
    label = bundle / "dataset" / "labels" / "train" / f"{image['id']}.txt"
    assert label.is_file()
    assert label.read_bytes() == b""
    assert frozen_path.read_bytes() == frozen_bytes


@pytest.mark.parametrize("patch", [{"source_available": False}, {"_dataset_delete_claim": "deleting"}])
def test_pending_save_rejects_unavailable_material(client, seeded_project, patch):
    pid, image = seeded_project
    initial = _initial(pid, image)
    app_module.material_store(pid).patch({image["id"]: patch})
    response = _post(client, pid, image, initial)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ANNOTATION_MATERIAL_UNAVAILABLE"
    assert app_module.read_annotation(pid, image["id"])["content_digest"] == initial["content_digest"]
