from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from PIL import Image

import app as app_module
from platform_core.annotation_repository import AnnotationRepository
from platform_core.online_feedback import OnlineFeedbackRepository


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
    model_path = models / "feedback.pt"
    model_path.write_bytes(b"feedback-model-v1")
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "烟雾抽检算法", "remark": "", "industry": "", "algorithm_type": "detection"},
    )
    algorithm.raise_for_status()
    algorithm_id = algorithm.json()["algorithm"]["id"]
    # Feedback tests need a stable version identity and model SHA, not a
    # fabricated training-success claim. The manual-attachment HTTP endpoint
    # is deliberately fail-closed for safe launch; preserve that production gate.
    version = app_module.attach_algorithm_version_if_current(
        app_module.algorithms_file(project_id),
        algorithm_id,
        {
            "id": uuid.uuid4().hex[:12],
            "version_no": 1,
            "version_name": "feedback-test-fixture",
            "model_name": model_path.name,
            "stored_path": str(model_path),
            "framework": "ultralytics",
            "training_status": "TEST_FIXTURE",
            "artifact_verified": False,
            "trainable": False,
            "created_at": app_module.now_iso(),
        },
        expected_current_version_id=None,
    )
    assert version["artifact_verified"] is False
    assert version["trainable"] is False
    return algorithm_id, version


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
    before = app_module.material_store(project["id"]).count()
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
    assert app_module.material_store(project["id"]).count() == before
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


def _image_bytes(color=(60, 70, 80)):
    import io
    stream = io.BytesIO()
    Image.new("RGB", (96, 72), color).save(stream, format="JPEG")
    return stream.getvalue()


def test_external_feedback_intake_stages_review_without_material_or_training_side_effect(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    model_sha = app_module.sha256_file(Path(version["stored_path"]))
    payload = {
        "algorithm_id": algorithm_id,
        "version_id": version["id"],
        "model_sha256": model_sha,
        "external_source": "edge-gateway-01",
        "external_sample_id": "camera-12-0001",
        "feedback_type": "needs_correction",
        "detections_json": "[]",
        "confidence": "0.25",
        "note": "边缘端抽检漏检",
    }
    before = app_module.material_store(project["id"]).count()
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/external-intake",
        data=payload,
        files={"file": ("edge.jpg", _image_bytes(), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    feedback = body["feedback"]
    assert body["idempotent"] is False
    assert feedback["status"] == "pending_review"
    assert feedback["source"]["source_channel"] == "external_upload"
    assert feedback["source"]["external_source"] == "edge-gateway-01"
    assert feedback["source"]["external_sample_id"] == "camera-12-0001"
    assert app_module.material_store(project["id"]).count() == before

    repeated = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/external-intake",
        data=payload,
        files={"file": ("edge.jpg", _image_bytes(), "image/jpeg")},
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["feedback"]["id"] == feedback["id"]


def test_external_feedback_intake_rejects_wrong_model_sha_and_sample_identity_conflict(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    model_sha = app_module.sha256_file(Path(version["stored_path"]))
    base = {
        "algorithm_id": algorithm_id,
        "version_id": version["id"],
        "model_sha256": model_sha,
        "external_source": "saas-audit",
        "external_sample_id": "sample-77",
        "feedback_type": "needs_correction",
        "detections_json": "[]",
    }
    wrong = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/external-intake",
        data={**base, "model_sha256": "f" * 64},
        files={"file": ("one.jpg", _image_bytes(), "image/jpeg")},
    )
    assert wrong.status_code == 409
    first = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/external-intake",
        data=base,
        files={"file": ("one.jpg", _image_bytes(), "image/jpeg")},
    )
    assert first.status_code == 201, first.text
    conflict = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/external-intake",
        data=base,
        files={"file": ("one.jpg", _image_bytes((10, 20, 30)), "image/jpeg")},
    )
    assert conflict.status_code == 409
    assert "绑定不同" in conflict.text


def _enable_supplement_action(project_id: str, algorithm_id: str, version_id: str):
    action = {
        "schema_version": 1,
        "action": "supplement_data",
        "status": "confirmed",
        "action_id": "d" * 64,
        "confirmed_at": app_module.now_iso(),
        "automatic_execution": False,
        "requires_user_submit": False,
        "source": {
            "decision_id": "e" * 64,
            "evaluation_id": "f" * 64,
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "dataset_revision_id": "",
            "snapshot_id": "snapshot-feedback",
        },
        "weak_labels": ["smoke"],
        "data_draft": {
            "weak_labels": ["smoke"],
            "problem_samples": [],
            "dataset_revision_id": "",
            "snapshot_id": "snapshot-feedback",
        },
    }
    app_module.update_algorithm_version(
        app_module.algorithms_file(project_id),
        algorithm_id,
        version_id,
        {"confirmed_iteration_action": action},
        now=app_module.now_iso(),
    )
    return action


def test_confirmed_feedback_candidates_freeze_without_revision_or_training_side_effect(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    _enable_supplement_action(project["id"], algorithm_id, version["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.93,
            "x1": 10, "y1": 8, "x2": 60, "y2": 52,
        }],
        suffix="candidate",
    )
    staged = _stage(client, project["id"], prediction_id, "correct")
    confirmed = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "correct",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    snapshots = app_module.project_dir(project["id"]) / "snapshots"
    revisions = app_module.project_dir(project["id"]) / "dataset_revisions"
    before_snapshots = set(snapshots.glob("*.json")) if snapshots.exists() else set()
    before_revisions = set(revisions.glob("*.json")) if revisions.exists() else set()

    listing = client.get(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates"
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 1
    assert body["eligible"] == 1
    candidate = body["items"][0]
    assert candidate["feedback_id"] == staged["id"]
    assert candidate["eligible"] is True

    frozen = client.post(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates/freeze",
        json={"candidates": [{
            "feedback_id": candidate["feedback_id"],
            "candidate_digest": candidate["candidate_digest"],
        }]},
    )
    assert frozen.status_code == 200, frozen.text
    candidate_set = frozen.json()["candidate_set"]
    assert candidate_set["feedback_ids"] == [staged["id"]]
    assert candidate_set["material_ids"] == [confirmed.json()["feedback"]["material_id"]]
    assert candidate_set["automatic_execution"] is False
    assert (set(snapshots.glob("*.json")) if snapshots.exists() else set()) == before_snapshots
    assert (set(revisions.glob("*.json")) if revisions.exists() else set()) == before_revisions

    algorithm = next(
        row for row in app_module.list_algorithms_internal(project["id"])
        if row["id"] == algorithm_id
    )
    persisted = next(row for row in algorithm["versions"] if row["id"] == version["id"])
    assert persisted["supplement_data_candidate_set"]["candidate_set_id"] == candidate_set["candidate_set_id"]

    repeated = client.post(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates/freeze",
        json={"candidates": [{
            "feedback_id": candidate["feedback_id"],
            "candidate_digest": candidate["candidate_digest"],
        }]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True


def test_feedback_candidate_freeze_rejects_stale_annotation_and_excludes_pending(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    _enable_supplement_action(project["id"], algorithm_id, version["id"])

    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.9,
            "x1": 10, "y1": 10, "x2": 50, "y2": 50,
        }],
        suffix="stale-candidate",
    )
    staged = _stage(client, project["id"], prediction_id, "correct")
    confirmed = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "correct",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    pending_prediction, _ = _prediction(
        project["id"], algorithm_id, version, detections=[], suffix="pending-candidate",
    )
    _stage(client, project["id"], pending_prediction, "needs_correction")

    listing = client.get(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates"
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    candidate = listing.json()["items"][0]
    material_id = confirmed.json()["feedback"]["material_id"]

    AnnotationRepository(app_module.project_dir(project["id"])).upsert(
        material_id,
        [{
            "id": "manual-new", "class_id": 0, "label": "smoke",
            "x1": 12, "y1": 12, "x2": 55, "y2": 55,
        }],
        "annotated",
    )
    stale = client.post(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates/freeze",
        json={"candidates": [{
            "feedback_id": candidate["feedback_id"],
            "candidate_digest": candidate["candidate_digest"],
        }]},
    )
    assert stale.status_code == 409
    assert "已经变化" in stale.text



def test_feedback_label_retirement_before_truth_commit_rolls_back_new_material(
    client, monkeypatch,
):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"],
        algorithm_id,
        version,
        detections=[{
            "class_id": 0,
            "label": "smoke",
            "confidence": 0.93,
            "x1": 10,
            "y1": 8,
            "x2": 60,
            "y2": 52,
        }],
        suffix="label-race",
    )
    staged = _stage(client, project["id"], prediction_id, "correct")
    before_materials = app_module.material_store(project["id"]).count()
    before_annotations = AnnotationRepository(
        app_module.project_dir(project["id"])
    ).summary()["total"]

    real_fence = app_module.label_governance_fence
    changed = {"done": False}

    @contextmanager
    def retire_before_truth(project_path, **kwargs):
        if not changed["done"]:
            changed["done"] = True
            meta_path = app_module.project_dir(project["id"]) / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["label_meta"][0]["status"] = "active"
            meta["label_meta"][0]["active"] = False
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False),
                encoding="utf-8",
            )
        with real_fence(project_path, **kwargs):
            yield

    monkeypatch.setattr(
        app_module,
        "label_governance_fence",
        retire_before_truth,
    )
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}/confirm",
        json={
            "expected_feedback_type": "correct",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
        },
    )

    assert response.status_code == 409, response.text
    assert changed["done"] is True
    assert "无法唯一映射到当前项目标签" in response.text
    assert app_module.material_store(project["id"]).count() == before_materials
    assert AnnotationRepository(
        app_module.project_dir(project["id"])
    ).summary()["total"] == before_annotations
    pending = app_module._online_feedback_repository(project["id"]).get(staged["id"])
    assert pending["status"] == "pending_review"


def test_pending_feedback_prevents_version_retirement_until_review_finishes(client):
    project = _project(client)
    project_id = project["id"]
    algorithm_id, source_version = _algorithm_version(client, project_id)
    prediction_id, _ = _prediction(
        project_id, algorithm_id, source_version,
        detections=[], suffix="retirement-fence",
    )
    pending = _stage(client, project_id, prediction_id, "needs_correction")
    assert app_module._online_feedback_repository(project_id).pending_version_reference(
        algorithm_id, source_version["id"]
    ) == pending["id"]

    other_path = app_module.project_dir(project_id) / "models" / "feedback-next.pt"
    other_path.write_bytes(b"another-model-for-version-retirement")
    next_version = app_module.attach_algorithm_version_if_current(
        app_module.algorithms_file(project_id),
        algorithm_id,
        {
            "id": uuid.uuid4().hex[:12],
            "version_no": 2,
            "version_name": "feedback-next-fixture",
            "model_name": other_path.name,
            "stored_path": str(other_path),
            "framework": "ultralytics",
            "training_status": "TEST_FIXTURE",
            "artifact_verified": False,
            "trainable": False,
            "created_at": app_module.now_iso(),
        },
        expected_current_version_id=source_version["id"],
    )
    assert next_version["id"] != source_version["id"]

    delete_url = (
        f"/api/v12/projects/{project_id}/algorithms/{algorithm_id}"
        f"/versions/{source_version['id']}"
    )
    blocked = client.delete(delete_url)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ALGORITHM_VERSION_IN_USE"
    assert app_module._online_feedback_repository(project_id).pending_version_reference(
        algorithm_id, source_version["id"]
    ) == pending["id"]
    assert source_version["id"] in {
        v["id"] for algo in app_module.list_algorithms_internal(project_id)
        if algo["id"] == algorithm_id for v in algo["versions"]
    }

    dismissed = client.post(
        f"/api/v63/projects/{project_id}/online-feedback/{pending['id']}/dismiss",
        json={
            "expected_feedback_type": "needs_correction",
            "reason": "review completed",
        },
    )
    assert dismissed.status_code == 200, dismissed.text
    assert app_module._online_feedback_repository(project_id).pending_version_reference(
        algorithm_id, source_version["id"]
    ) == ""

    retired = client.delete(delete_url)
    assert retired.status_code == 200, retired.text


def test_pending_correct_feedback_pins_label_rename_delete_and_remap_retirement(client):
    from platform_core.material_batches import BatchRequestError, _retire_merged_source_labels

    created = client.post("/api/projects", json={
        "name": f"feedback-label-pin-{uuid.uuid4().hex[:8]}",
        "labels": ["smoke", "helmet"],
    })
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    algorithm_id, version = _algorithm_version(client, project_id)
    prediction_id, _ = _prediction(
        project_id, algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.93,
            "x1": 10, "y1": 8, "x2": 60, "y2": 52,
        }],
    )
    staged = _stage(client, project_id, prediction_id, "correct")
    assert app_module._online_feedback_repository(project_id).pending_label_reference(
        ["smoke"]
    ) == staged["id"]

    changed = client.put(
        f"/api/v12/projects/{project_id}/labels/0", json={"code": "smoking"},
    )
    assert changed.status_code == 409, changed.text
    deleted = client.delete(f"/api/v12/projects/{project_id}/labels/0")
    assert deleted.status_code == 409, deleted.text

    with pytest.raises(BatchRequestError) as conflict:
        _retire_merged_source_labels(
            app_module.DATA_DIR, project_id, ["smoke"], "helmet",
        )
    assert conflict.value.code == "ONLINE_FEEDBACK_LABEL_ACTIVE"

    # A different label is not pinned by smoke predictions.
    unrelated = client.delete(f"/api/v12/projects/{project_id}/labels/1")
    assert unrelated.status_code == 200, unrelated.text

    dismissed = client.post(
        f"/api/v63/projects/{project_id}/online-feedback/{staged['id']}/dismiss",
        json={"expected_feedback_type": "correct", "reason": "review handled"},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert app_module._online_feedback_repository(project_id).pending_label_reference(
        ["smoke"]
    ) == ""
    renamed = client.put(
        f"/api/v12/projects/{project_id}/labels/0", json={"code": "smoking"},
    )
    assert renamed.status_code == 200, renamed.text


def test_stage_correct_prediction_rejects_retired_frozen_label(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.93,
            "x1": 10, "y1": 8, "x2": 60, "y2": 52,
        }],
    )
    deleted = client.delete(f"/api/v12/projects/{project['id']}/labels/0")
    assert deleted.status_code == 200, deleted.text
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback",
        json={
            "prediction_id": prediction_id,
            "feedback_type": "correct",
            "note": "retired source label",
        },
    )
    assert response.status_code == 409, response.text
    assert app_module._online_feedback_repository(project["id"]).list(
        status="pending_review"
    ) == []


def _review_annotation(client, project_id: str, image_id: str, boxes, labels=None):
    """Save formal GT through the existing annotation review API (the Owner)."""
    current = client.get(f"/api/projects/{project_id}/annotations/{image_id}").json()
    response = client.post(
        f"/api/projects/{project_id}/annotations/{image_id}",
        json={
            "boxes": boxes,
            "expected_version": current["annotation"]["version"],
            "source_content_sha256": current["image"]["content_sha256"],
            "reviewed_label_codes": list(labels or [box["label"] for box in boxes]),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client, project_id, feedback_id, feedback_type, request_id="", **extra):
    return client.post(
        f"/api/v63/projects/{project_id}/online-feedback/{feedback_id}/confirm",
        json={
            "expected_feedback_type": feedback_type,
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
            "request_id": request_id,
            **extra,
        },
    )


def test_feedback_evidence_retains_prediction_identity_and_never_rewrites_it(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, image_path = _prediction(
        project["id"],
        algorithm_id,
        version,
        detections=[{
            "class_id": 0,
            "label": "smoke",
            "confidence": 0.93,
            "x1": 10,
            "y1": 8,
            "x2": 60,
            "y2": 52,
        }],
        suffix="evidence-retained",
    )
    evidence_path = (
        app_module.project_dir(project["id"]) / "predictions"
        / f"{prediction_id}.evidence.json"
    )
    evidence_before = evidence_path.read_bytes()
    staged_response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback",
        json={
            "prediction_id": prediction_id,
            "feedback_type": "needs_correction",
            "note": "定位偏移，部分目标框需要修正",
            "correction_kind": "inaccurate_box",
        },
    )
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()["feedback"]
    detail = client.get(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}"
    ).json()["feedback"]

    assert detail["prediction_id"] == prediction_id
    assert detail["project_id"] == project["id"]
    assert detail["algorithm_id"] == algorithm_id
    assert detail["version_id"] == version["id"]
    assert detail["model_sha256"] == app_module.sha256_file(Path(version["stored_path"]))
    assert detail["input_sha256"] == app_module.sha256_file(image_path)
    assert detail["feedback_type"] == "needs_correction"
    assert detail["correction_kind"] == "inaccurate_box"
    assert detail["note"].startswith("定位偏移")
    assert detail["created_at"]
    detection = detail["source"]["detections"][0]
    assert (detection["class_id"], detection["label"], detection["confidence"]) == (
        0, "smoke", 0.93,
    )
    assert (detection["x1"], detection["y1"], detection["x2"], detection["y2"]) == (
        10, 8, 60, 52,
    )

    confirmed = _confirm(client, project["id"], staged["id"], "needs_correction")
    assert confirmed.status_code == 200, confirmed.text
    # The original prediction evidence file is never rewritten by feedback or
    # review; only the feedback owner stores a copy of the frozen prediction.
    assert evidence_path.read_bytes() == evidence_before
    stored = OnlineFeedbackRepository(
        app_module.project_dir(project["id"])
    ).get(staged["id"])
    assert stored["payload"]["source"]["detections"][0]["label"] == "smoke"


@pytest.mark.parametrize(
    "correction_kind,detections",
    [
        ("missed_detection", []),
        ("wrong_class", [{
            "class_id": 0, "label": "smoke", "confidence": 0.8,
            "x1": 10, "y1": 10, "x2": 50, "y2": 50,
        }]),
        ("inaccurate_box", [{
            "class_id": 0, "label": "smoke", "confidence": 0.8,
            "x1": 10, "y1": 10, "x2": 50, "y2": 50,
        }]),
        ("partial_correction", [{
            "class_id": 0, "label": "smoke", "confidence": 0.8,
            "x1": 10, "y1": 10, "x2": 50, "y2": 50,
        }]),
    ],
)
def test_correction_feedback_only_enters_candidate_until_human_review(
    client, correction_kind, detections,
):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    _enable_supplement_action(project["id"], algorithm_id, version["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=detections, suffix=f"correction-{correction_kind}",
    )
    staged = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback",
        json={
            "prediction_id": prediction_id,
            "feedback_type": "needs_correction",
            "note": correction_kind,
            "correction_kind": correction_kind,
        },
    ).json()["feedback"]
    confirmed = _confirm(client, project["id"], staged["id"], "needs_correction")
    assert confirmed.status_code == 200, confirmed.text
    feedback = confirmed.json()["feedback"]
    assert feedback["status"] == "confirmed"
    assert feedback["result"]["candidate_only"] is True
    assert feedback["result"]["gt_written"] is False
    assert feedback["result"]["gt_recorded"] is False
    assert feedback["result"]["annotation_action"] == "manual_annotation_required"
    assert feedback["result"]["correction_kind"] == correction_kind
    assert feedback["result"]["review"]["actor_id"]
    assert "gt_receipt" not in feedback["result"]

    material_id = feedback["material_id"]
    before_review = AnnotationRepository(
        app_module.project_dir(project["id"])
    ).get(material_id)
    assert before_review["annotation_state"] == "unannotated"
    assert before_review["boxes"] == []

    listing = client.get(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates"
    )
    assert listing.status_code == 200, listing.text
    item = listing.json()["items"][0]
    assert item["eligible"] is False
    assert "ANNOTATION_REQUIRED" in item["reason_codes"]
    assert item["correction_kind"] == correction_kind

    _review_annotation(
        client, project["id"], material_id,
        [{
            "class_id": 0, "label": "smoke",
            "x1": 12, "y1": 12, "x2": 55, "y2": 55,
        }],
        ["smoke"],
    )
    reviewed_listing = client.get(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates"
    )
    reviewed = reviewed_listing.json()["items"][0]
    assert reviewed["eligible"] is True
    annotation = AnnotationRepository(
        app_module.project_dir(project["id"])
    ).get(material_id)
    assert reviewed["annotation_hash"] == annotation["content_digest"]
    assert reviewed["annotation_version"] == annotation["version"]
    assert reviewed["correction_kind"] == correction_kind

    frozen = client.post(
        f"/api/v63/projects/{project['id']}/algorithms/{algorithm_id}/versions/"
        f"{version['id']}/supplement-data-candidates/freeze",
        json={"candidates": [{
            "feedback_id": reviewed["feedback_id"],
            "candidate_digest": reviewed["candidate_digest"],
        }]},
    )
    assert frozen.status_code == 200, frozen.text
    frozen_candidate = frozen.json()["candidate_set"]["candidates"][0]
    assert frozen_candidate["feedback_id"] == staged["id"]
    assert frozen_candidate["correction_kind"] == correction_kind
    assert frozen_candidate["annotation_hash"] == annotation["content_digest"]


def test_correction_kind_is_rejected_for_direct_truth_feedback(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.9,
            "x1": 10, "y1": 10, "x2": 50, "y2": 50,
        }],
    )
    response = client.post(
        f"/api/v63/projects/{project['id']}/online-feedback",
        json={
            "prediction_id": prediction_id,
            "feedback_type": "correct",
            "note": "试图携带修正类型",
            "correction_kind": "wrong_class",
        },
    )
    assert response.status_code == 409, response.text
    assert "只能进入候选" in response.text
    assert app_module._online_feedback_repository(project["id"]).list() == []


def test_correct_confirm_persists_review_evidence_and_idempotent_gt_receipt(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.93,
            "x1": 10, "y1": 8, "x2": 60, "y2": 52,
        }],
        suffix="receipt",
    )
    staged = _stage(client, project["id"], prediction_id, "correct")
    confirmed = _confirm(
        client, project["id"], staged["id"], "correct", request_id="review-op-1",
    )
    assert confirmed.status_code == 200, confirmed.text
    feedback = confirmed.json()["feedback"]
    receipt = feedback["result"]["gt_receipt"]
    assert feedback["result"]["gt_written"] is True
    assert feedback["result"]["gt_recorded"] is True
    assert feedback["result"]["review"]["request_id"] == "review-op-1"
    assert feedback["result"]["review"]["actor_id"]
    assert receipt["feedback_id"] == staged["id"]
    assert receipt["project_id"] == project["id"]
    assert receipt["algorithm_id"] == algorithm_id
    assert receipt["version_id"] == version["id"]
    assert receipt["annotation_state"] == "annotated"
    assert receipt["annotation_version"] == 1
    assert receipt["box_count"] == 1
    assert receipt["labels"] == ["smoke"]
    assert len(receipt["annotation_content_digest"]) == 64
    assert receipt["gt_write"] == "written"
    assert receipt["review_request_id"] == "review-op-1"

    annotation = AnnotationRepository(
        app_module.project_dir(project["id"])
    ).get(feedback["material_id"])
    assert receipt["annotation_content_digest"] == annotation["content_digest"]
    assert receipt["annotation_version"] == annotation["version"]

    repeated = _confirm(
        client, project["id"], staged["id"], "correct", request_id="review-op-1",
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    repeated_feedback = repeated.json()["feedback"]
    assert repeated_feedback["result"]["gt_receipt"] == receipt
    # The receipt is durable: the original feedback record read back exposes the
    # exact same formal-GT identity after the response was returned.
    persisted_feedback = client.get(
        f"/api/v63/projects/{project['id']}/online-feedback/{staged['id']}"
    ).json()["feedback"]
    assert persisted_feedback["result"]["gt_receipt"] == receipt
    assert persisted_feedback["result"]["review"]["request_id"] == "review-op-1"
    repeated_annotation = AnnotationRepository(
        app_module.project_dir(project["id"])
    ).get(feedback["material_id"])
    assert repeated_annotation["version"] == annotation["version"] == 1
    refs = app_module.material_store(project["id"]).get(
        feedback["material_id"]
    )["online_feedback_refs"]
    assert [row["feedback_id"] for row in refs] == [staged["id"]]


def test_false_positive_confirm_persists_grounded_negative_receipt(client):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.77,
            "x1": 5, "y1": 5, "x2": 30, "y2": 30,
        }],
        suffix="negative-receipt",
    )
    staged = _stage(client, project["id"], prediction_id, "false_positive")
    confirmed = _confirm(
        client, project["id"], staged["id"], "false_positive",
        confirm_all_labels_absent=True,
    )
    assert confirmed.status_code == 200, confirmed.text
    feedback = confirmed.json()["feedback"]
    receipt = feedback["result"]["gt_receipt"]
    assert feedback["result"]["gt_written"] is True
    assert feedback["result"]["gt_recorded"] is True
    assert receipt["annotation_state"] == "confirmed_empty"
    assert receipt["box_count"] == 0
    assert receipt["labels"] == []
    assert receipt["gt_write"] == "written"
    assert receipt["annotation_version"] == 1
    repeated = _confirm(
        client, project["id"], staged["id"], "false_positive",
        confirm_all_labels_absent=True,
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["feedback"]["result"]["gt_receipt"] == receipt


def test_gt_write_with_lost_confirm_response_recovers_without_duplicate_gt(client, monkeypatch):
    project = _project(client)
    algorithm_id, version = _algorithm_version(client, project["id"])
    prediction_id, _ = _prediction(
        project["id"], algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.93,
            "x1": 10, "y1": 8, "x2": 60, "y2": 52,
        }],
        suffix="lost-response",
    )
    staged = _stage(client, project["id"], prediction_id, "correct")
    original_finalize = OnlineFeedbackRepository.finalize
    state = {"raised": False}

    def lose_first_response(self, *args, **kwargs):
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("simulated lost confirm response after GT write")
        return original_finalize(self, *args, **kwargs)

    monkeypatch.setattr(OnlineFeedbackRepository, "finalize", lose_first_response)
    with pytest.raises(RuntimeError):
        _confirm(client, project["id"], staged["id"], "correct", request_id="retry-op")
    # GT was really written before the simulated response loss; feedback is
    # still pending so the client can safely retry the same review.
    pending = app_module._online_feedback_repository(project["id"]).get(staged["id"])
    assert pending["status"] == "pending_review"
    written_material = app_module.material_store(project["id"]).get_by_content_sha256(
        pending["input_sha256"]
    )
    assert written_material is not None
    written = AnnotationRepository(app_module.project_dir(project["id"])).get(
        written_material["id"]
    )
    assert written["annotation_state"] == "annotated"
    assert written["version"] == 1

    monkeypatch.setattr(OnlineFeedbackRepository, "finalize", original_finalize)
    recovered = _confirm(
        client, project["id"], staged["id"], "correct", request_id="retry-op",
    )
    assert recovered.status_code == 200, recovered.text
    feedback = recovered.json()["feedback"]
    receipt = feedback["result"]["gt_receipt"]
    assert feedback["status"] == "confirmed"
    # This retry did not write GT again; it recovered the existing formal truth.
    assert feedback["result"]["gt_written"] is False
    assert feedback["result"]["gt_recorded"] is True
    assert feedback["result"]["annotation_action"] == "prediction_matches_existing_truth"
    assert receipt["gt_write"] == "already_present"
    assert receipt["annotation_version"] == 1
    assert receipt["review_request_id"] == "retry-op"
    recorded = AnnotationRepository(app_module.project_dir(project["id"])).get(
        written_material["id"]
    )
    assert recorded["version"] == 1, "lost response must never duplicate the GT write"
    refs = app_module.material_store(project["id"]).get(
        written_material["id"]
    )["online_feedback_refs"]
    assert [row["feedback_id"] for row in refs] == [staged["id"]]


def test_false_positive_recovery_rejects_incomplete_negative_scope(client):
    created = client.post("/api/projects", json={
        "name": f"feedback-negative-scope-{uuid.uuid4().hex[:8]}",
        "labels": ["smoke", "fire"],
    })
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    algorithm_id, version = _algorithm_version(client, project_id)
    prediction_id, input_path = _prediction(
        project_id, algorithm_id, version,
        detections=[{
            "class_id": 0, "label": "smoke", "confidence": 0.8,
            "x1": 10, "y1": 10, "x2": 50, "y2": 50,
        }],
        suffix="partial-negative",
    )
    material = app_module.add_image_record(
        project_id, input_path, "partial-negative.jpg", "raw",
        "default", "default_local",
        content_sha256=app_module.sha256_file(input_path),
    )
    assert material is not None
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(material["id"], [], "confirmed_empty", annotation_scope=["smoke"])
    staged = _stage(client, project_id, prediction_id, "false_positive")
    blocked = _confirm(
        client, project_id, staged["id"], "false_positive",
        confirm_all_labels_absent=True,
    )
    # An existing negative that never reviewed the second active label cannot be
    # acknowledged as "all active labels absent"; the feedback stays reviewable.
    assert blocked.status_code == 409, blocked.text
    assert "正式标注在复核期间发生变化" in blocked.text
    staging = app_module._online_feedback_repository(project_id).get(staged["id"])
    assert staging["status"] == "pending_review"
    annotations.upsert(
        material["id"], [], "confirmed_empty", annotation_scope=["smoke", "fire"],
    )
    recovered = _confirm(
        client, project_id, staged["id"], "false_positive",
        confirm_all_labels_absent=True,
    )
    assert recovered.status_code == 200, recovered.text
    receipt = recovered.json()["feedback"]["result"]["gt_receipt"]
    assert receipt["gt_write"] == "already_present"
    assert set(receipt["annotation_scope"]) == {"smoke", "fire"}


def test_feedback_is_scoped_to_owning_project_and_algorithm_version(client):
    first_project = _project(client)
    first_algorithm_id, first_version = _algorithm_version(client, first_project["id"])
    prediction_id, _ = _prediction(
        first_project["id"], first_algorithm_id, first_version,
        detections=[], suffix="project-scope",
    )
    first_evidence = (
        app_module.project_dir(first_project["id"]) / "predictions"
        / f"{prediction_id}.evidence.json"
    )
    # Real prediction registration stamps the owning project into the file.
    evidence_value = json.loads(first_evidence.read_text(encoding="utf-8"))
    evidence_value["project_id"] = first_project["id"]
    first_evidence.write_text(json.dumps(evidence_value), encoding="utf-8")
    staged = _stage(client, first_project["id"], prediction_id, "needs_correction")

    other_project = _project(client)
    other_algorithm_id, other_version = _algorithm_version(client, other_project["id"])
    listing = client.get(
        f"/api/v63/projects/{other_project['id']}/online-feedback"
    )
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    blocked = client.get(
        f"/api/v63/projects/{other_project['id']}/online-feedback/{staged['id']}"
    )
    assert blocked.status_code == 404
    blocked_confirm = _confirm(
        client, other_project["id"], staged["id"], "needs_correction",
    )
    assert blocked_confirm.status_code == 404
    assert app_module._online_feedback_repository(
        first_project["id"]
    ).get(staged["id"])["status"] == "pending_review"

    # A copied prediction evidence file keeps its owning project identity and
    # cannot be replayed as another project's feedback input.
    target_root = app_module.project_dir(other_project["id"]) / "predictions"
    target_root.mkdir(parents=True, exist_ok=True)
    (target_root / f"{prediction_id}.evidence.json").write_bytes(
        first_evidence.read_bytes()
    )
    copied = client.post(
        f"/api/v63/projects/{other_project['id']}/online-feedback",
        json={"prediction_id": prediction_id, "feedback_type": "needs_correction"},
    )
    assert copied.status_code == 409, copied.text
    assert "项目归属" in copied.text
    assert app_module._online_feedback_repository(
        other_project["id"]
    ).list() == []

    # The other project's algorithm versions never see the first project's
    # confirmed feedback candidate set.
    enable = _enable_supplement_action(
        other_project["id"], other_algorithm_id, other_version["id"],
    )
    assert enable["source"]["version_id"] == other_version["id"]
    other_candidates = client.get(
        f"/api/v63/projects/{other_project['id']}/algorithms/{other_algorithm_id}/"
        f"versions/{other_version['id']}/supplement-data-candidates"
    )
    assert other_candidates.status_code == 200, other_candidates.text
    assert other_candidates.json()["total"] == 0
    assert other_algorithm_id != first_algorithm_id
