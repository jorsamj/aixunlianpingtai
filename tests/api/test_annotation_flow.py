import pytest

def test_save_reload_and_thumbnail_summary_match(client, seeded_project):
    pid, image = seeded_project
    saved = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": [{"label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 90}]},
    )
    assert saved.status_code == 200
    material = saved.json()["image"]
    assert material["labels"] == ["fire"]
    assert material["box_count"] == 1
    assert material["annotation_status"] == "annotated"
    reloaded = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert reloaded["boxes"] == saved.json()["annotation"]["boxes"]
    listed = client.get(f"/api/projects/{pid}/images?dataset_id=default").json()
    row = next(item for item in listed if item["id"] == image["id"])
    assert row["annotation_preview"] == material["annotation_preview"]


def test_unknown_annotation_label_is_rejected(client, seeded_project):
    pid, image = seeded_project
    response = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": [{"label": "not-in-library", "x1": 1, "y1": 1, "x2": 20, "y2": 20}]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ANNOTATION_LABEL_NOT_FOUND"



def test_empty_annotation_requires_explicit_no_target_confirmation(client, seeded_project):
    pid, image = seeded_project
    rejected = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": []},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ANNOTATION_EMPTY_CONFIRMATION_REQUIRED"

    confirmed = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": [], "annotation_state": "confirmed_empty"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["saved_boxes"] == 0
    assert body["annotation"]["boxes"] == []
    assert body["annotation"]["annotation_state"] == "confirmed_empty"



def test_manual_save_preserves_ai_provenance_and_derives_mixed_origin(client, seeded_project):
    import app as app_module

    pid, image = seeded_project
    ai_box = {
        "id": "ai-box-1",
        "class_id": 0,
        "label": "fire",
        "x1": 10,
        "y1": 10,
        "x2": 50,
        "y2": 50,
        "source": "ai_candidate_confirmed",
        "source_task_id": "ai-task-1",
        "candidate_id": "candidate-1",
        "confidence": 0.93,
    }
    app_module.write_annotation(
        pid, image["id"], [ai_box],
        annotation_state="annotated",
        annotation_origin="ai_confirmed",
    )

    saved = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={
            "boxes": [
                {
                    "id": "ai-box-1",
                    "label": "fire",
                    "x1": 12,
                    "y1": 12,
                    "x2": 52,
                    "y2": 52,
                    "source": "manual",
                },
                {
                    "id": "manual-box-1",
                    "label": "fire",
                    "x1": 60,
                    "y1": 20,
                    "x2": 90,
                    "y2": 70,
                    "source": "ai_candidate_confirmed",
                },
            ]
        },
    )

    assert saved.status_code == 200
    body = saved.json()
    boxes = {box["id"]: box for box in body["annotation"]["boxes"]}
    assert boxes["ai-box-1"]["source"] == "ai_candidate_confirmed"
    assert boxes["ai-box-1"]["source_task_id"] == "ai-task-1"
    assert boxes["ai-box-1"]["candidate_id"] == "candidate-1"
    assert boxes["manual-box-1"]["source"] == "manual"
    assert body["image"]["annotation_origin"] == "mixed"



def test_annotation_reindex_preserves_legacy_material_provenance():
    import inspect
    import app as app_module

    imported = app_module._annotation_summary_for_material_index(
        [{"id": "legacy", "label": "fire", "class_id": 0,
          "x1": 1, "y1": 1, "x2": 20, "y2": 20}],
        "annotated",
        {"source_type": "imported_yolo"},
    )
    assert imported["annotation_origin"] == "imported"

    ai_empty = app_module._annotation_summary_for_material_index(
        [],
        "confirmed_empty",
        {"annotation_origin": "ai_confirmed"},
    )
    assert ai_empty["annotation_origin"] == "ai_confirmed"

    explicit_ai = app_module._annotation_summary_for_material_index(
        [{"id": "ai", "label": "fire", "class_id": 0,
          "x1": 1, "y1": 1, "x2": 20, "y2": 20,
          "source": "ai_candidate_confirmed"}],
        "annotated",
        {"annotation_origin": "manual", "source_type": "imported_yolo"},
    )
    assert explicit_ai["annotation_origin"] == "ai_confirmed"

    assert "_annotation_summary_for_material_index" in inspect.getsource(
        app_module._v52_annotation_index_worker
    )
    assert "_annotation_summary_for_material_index" in inspect.getsource(
        app_module._v53_index_annotations_sync
    )



def test_manual_save_recovers_legacy_ai_origin_without_box_source(client, seeded_project):
    import app as app_module

    pid, image = seeded_project
    app_module.write_annotation(
        pid,
        image["id"],
        [{
            "id": "legacy-ai-box",
            "class_id": 0,
            "label": "fire",
            "x1": 10,
            "y1": 10,
            "x2": 50,
            "y2": 50,
        }],
        annotation_state="annotated",
        annotation_origin="ai_confirmed",
    )

    saved = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={
            "boxes": [
                {
                    "id": "legacy-ai-box",
                    "label": "fire",
                    "x1": 12,
                    "y1": 12,
                    "x2": 52,
                    "y2": 52,
                },
                {
                    "id": "new-manual-box",
                    "label": "fire",
                    "x1": 60,
                    "y1": 20,
                    "x2": 90,
                    "y2": 70,
                },
            ]
        },
    )

    assert saved.status_code == 200, saved.text
    body = saved.json()
    boxes = {box["id"]: box for box in body["annotation"]["boxes"]}
    assert boxes["legacy-ai-box"]["source"] == "ai_candidate_confirmed"
    assert boxes["new-manual-box"]["source"] == "manual"
    assert body["image"]["annotation_origin"] == "mixed"

    assert app_module._annotation_box_source_fallback({
        "annotation_origin": "manual",
        "source_type": "imported_yolo",
    }) == "manual"
    assert app_module._annotation_box_source_fallback({
        "source_type": "imported_coco",
    }) == "imported"


def test_manual_annotation_get_and_save_do_not_scan_full_material_library(client, seeded_project, monkeypatch):
    import app as app_module

    pid, image = seeded_project
    monkeypatch.setattr(
        app_module,
        "load_images",
        lambda *_args, **_kwargs: pytest.fail(
            "single-image annotation GET/save must use indexed material lookup"
        ),
    )

    loaded = client.get(f"/api/projects/{pid}/annotations/{image['id']}")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["image"]["id"] == image["id"]

    saved = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": [{"label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 90}]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["image"]["id"] == image["id"]
    assert saved.json()["image"]["box_count"] == 1
