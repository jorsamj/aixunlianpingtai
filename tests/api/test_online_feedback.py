from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from PIL import Image

import app as app_module
from platform_core.annotation_repository import AnnotationRepository


def _project(client):
    response = client.post("/api/projects", json={
        "name": f"online-feedback-{uuid.uuid4().hex[:8]}",
        "labels": ["smoke"],
    })
    response.raise_for_status()
    return response.json()


def _algorithm_version(client, project_id: str):
    models = app_module.project_dir(project_id) / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "feedback.pt").write_bytes(b"feedback-model-v1")
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "烟雾抽检算法", "remark": "", "industry": "", "algorithm_type": "detection"},
    )
    algorithm.raise_for_status()
    algorithm_id = algorithm.json()["algorithm"]["id"]
    version = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions",
        json={
            "model_name": "feedback.pt",
            "model_source": "project",
            "version_name": "",
            "remark": "",
        },
    )
    version.raise_for_status()
    return algorithm_id, version.json()["version"]


def _prediction(project_id: str, algorithm_id: str, version: dict, *, detections, suffix=""):
    prediction_id = ("feed" + uuid.uuid4().hex)[:12]
    root = app_module.project_dir(project_id) / "predictions"
    root.mkdir(parents=True, exist_ok=True)
    image_path = root / f"{prediction_id}_input.jpg"
    Image.new("RGB", (96, 72), (80, 80, 80)).save(image_path, format="JPEG")
    model_path = Path(version["stored_path"])
    evidence = {
        "schema_version": 1,
        "prediction_id": prediction_id,
        "algorithm_id": algorithm_id,
        "version_id": version["id"],
        "model_sha256": app_module.sha256_file(model_path),
        "input_sha256": app_module.sha256_file(image_path),
        "original_filename": f"camera-{suffix or prediction_id}.jpg",
        "input_file": image_path.name,
        "width": 96,
        "height": 72,
        "confidence": 0.25,
        "engine": "ultralytics",
        "detections": detections,
        "created_at": app_module.now_iso(),
    }
    app_module.write_json(root / f"{prediction_id}.evidence.json", evidence)
    return prediction_id, image_path


def _stage(client, project_id: str, prediction_id: str, feedback_type: str):
    response = client.post(
        f"/api/v63/projects/{project_id}/online-feedback",
        json={
            "prediction_id": prediction_id,
            "feedback_type": feedback_type,
            "note": "人工抽检",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["feedback"]


def test_correct_prediction_promotes_sample_and_prediction_boxes(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.93,
            "x1": 10, "y1": 8, "x2": 60, "y2": 52,
        }],
    )
    staged = _stage(client, project["id"], prediction_id, "correct")
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "correct",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert response.status_code == 200, response.text
    feedback = response.json()["feedback"]
    assert feedback["status"] == "confirmed"
    assert feedback["result"]["annotation_action"] == "prediction_confirmed_as_truth"
    material = app_module.material_store(project["id"]).get(feedback["material_id"])
    assert material["source_type"] == "online_feedback"
    assert material["processing_status"] == "processed"
    assert material["online_feedback_refs"][-1]["version_id"] == version["id"]
    annotation = AnnotationRepository(app_module.project_dir(project["id"])).get(material["id"])
    assert annotation["annotation_state"] == "annotated"
    assert annotation["boxes"][0]["label"] == "smoke"


def test_false_positive_requires_explicit_global_negative_confirmation(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.77,
            "x1": 5, "y1": 5, "x2": 30, "y2": 30,
        }],
        suffix="negative",
    )
    staged = _stage(client, project["id"], prediction_id, "false_positive")
    blocked = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "false_positive",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert blocked.status_code == 409
    accepted = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "false_positive",
            "dataset_id": "default",
            "confirm_all_labels_absent": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    material_id = accepted.json()["feedback"]["material_id"]
    annotation = AnnotationRepository(app_module.project_dir(project["id"])).get(material_id)
    assert annotation["annotation_state"] == "confirmed_empty"
    assert annotation["annotation_scope"] == ["smoke"]


def test_needs_correction_promotes_only_to_manual_annotation_queue(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version, detections=[], suffix="missed",
    )
    staged = _stage(client, project["id"], prediction_id, "needs_correction")
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "needs_correction",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert response.status_code == 200, response.text
    feedback = response.json()["feedback"]
    assert feedback["result"]["annotation_action"] == "manual_annotation_required"
    material = app_module.material_store(project["id"]).get(feedback["material_id"])
    assert material["processing_status"] == "pending_decision"
    assert material["online_feedback_needs_review"] is True
    annotation = AnnotationRepository(app_module.project_dir(project["id"])).get(material["id"])
    assert annotation["annotation_state"] == "unannotated"


def test_feedback_confirm_rejects_changed_prediction_input(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, image_path = _prediction(
        project["id"], algorithm_id, version, detections=[], suffix="changed",
    )
    staged = _stage(client, project["id"], prediction_id, "needs_correction")
    Image.new("RGB", (96, 72), (10, 10, 10)).save(image_path, format="JPEG")
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "needs_correction",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert response.status_code == 409
    assert "测试图片" in response.text


def test_feedback_list_does_not_expose_prediction_file_path(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version, detections=[], suffix="public",
    )
    _stage(client, project["id"], prediction_id, "needs_correction")
    response = client.get(f"/api/v63/projects/{project['id']}/online-feedback")
    assert response.status_code == 200
    row = response.json()["items"][0]
    assert "input_file" not in row["source"]
    assert row["source"]["detection_count"] == 0


def test_correct_feedback_recovers_when_existing_truth_exactly_matches_prediction(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    detections = [{
        "class_id": 0, "label": "smoke", "confidence": 0.93,
        "x1": 10, "y1": 8, "x2": 60, "y2": 52,
    }]
    prediction_id, input_path = _prediction(
        project["id"], algorithm_id, version, detections=detections, suffix="recovery",
    )
    staged = _stage(client, project["id"], prediction_id, "correct")

    material = app_module.add_image_record(
        project["id"], input_path, "recovery.jpg", "online_feedback",
        "default", "default_local",
        content_sha256=app_module.sha256_file(input_path),
    )
    assert material is not None
    AnnotationRepository(app_module.project_dir(project["id"])).upsert(
        material["id"],
        [{
            "id": f"feedback-{prediction_id}-0",
            "class_id": 0, "label": "smoke",
            "x1": 10.0, "y1": 8.0, "x2": 60.0, "y2": 52.0,
        }],
        "annotated",
    )

    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "correct",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert response.status_code == 200, response.text
    feedback = response.json()["feedback"]
    assert feedback["material_id"] == material["id"]
    assert feedback["result"]["material_reused"] is True
    assert feedback["result"]["annotation_action"] == "prediction_matches_existing_truth"


def test_correct_feedback_rejects_different_existing_truth(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, input_path = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.93,
            "x1": 10, "y1": 8, "x2": 60, "y2": 52,
        }],
        suffix="conflict",
    )
    staged = _stage(client, project["id"], prediction_id, "correct")
    material = app_module.add_image_record(
        project["id"], input_path, "conflict.jpg", "raw",
        "default", "default_local",
        content_sha256=app_module.sha256_file(input_path),
    )
    assert material is not None
    AnnotationRepository(app_module.project_dir(project["id"])).upsert(
        material["id"],
        [{
            "id": "manual-box", "class_id": 0, "label": "smoke",
            "x1": 1, "y1": 2, "x2": 20, "y2": 25,
        }],
        "annotated",
    )
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "correct",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert response.status_code == 409
    assert "不能覆盖" in response.text


def test_pending_feedback_can_be_dismissed_without_material_side_effect(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version, detections=[], suffix="dismiss",
    )
    staged = _stage(client, project["id"], prediction_id, "needs_correction")
    before = len(app_module.material_store(project["id"]).list())
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/dismiss",
        json={
            "expected_feedback_type": "needs_correction",
            "reason": "不是有效现场样本",
        },
    )
    assert response.status_code == 200, response.text
    feedback = response.json()["feedback"]
    assert feedback["status"] == "dismissed"
    assert feedback["material_id"] == ""
    assert feedback["result"]["dismissed"] is True
    assert len(app_module.material_store(project["id"]).list()) == before
    repeated = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/dismiss",
        json={
            "expected_feedback_type": "needs_correction",
            "reason": "重复忽略",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True


def test_legacy_v42_feedback_and_auto_iteration_writes_are_gone(client):
    project = _project(client)
    algorithm_id, _ = _algorithm_version(client, project["id"])
    feedback = client.post(
        f"/api/v42/projects/{project['id']}/online-feedback",
        json={
            "algorithm_id": algorithm_id,
            "correct": False,
            "score": 0.1,
            "category": "漏检",
            "reason": "legacy should not write",
            "image_url": "https://127.0.0.1/should-not-fetch.jpg",
            "dataset_id": "default",
            "source": "legacy",
        },
    )
    assert feedback.status_code == 410
    assert app_module._v42_list(project["id"], "online_feedback") == []
