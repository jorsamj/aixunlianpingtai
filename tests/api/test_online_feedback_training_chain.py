"""End-to-end: online feedback -> human review -> formal GT -> next-round training.

Uses the real tmp-SQLite project/GT/Material/Task owners. No GPU, no real
training process: the durable TRAINING_PREPARE freeze (snapshot + dataset
revision + payload provenance) is the next-round boundary under test.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image

import app as app_module
from platform_core.annotation_repository import AnnotationRepository
from platform_core.algorithms import save_algorithms


def _image_bytes(color) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(stream, format="JPEG")
    return stream.getvalue()


def _upload(client, project_id: str, name: str, raw: bytes) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (name, raw, "image/jpeg"))],
        data={"dataset_id": "default"},
    )
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def _save_reviewed_annotation(client, project_id: str, image_id: str, boxes, labels):
    current = client.get(
        f"/api/projects/{project_id}/annotations/{image_id}"
    ).json()
    response = client.post(
        f"/api/projects/{project_id}/annotations/{image_id}",
        json={
            "boxes": boxes,
            "expected_version": current["annotation"]["version"],
            "source_content_sha256": current["image"]["content_sha256"],
            "reviewed_label_codes": list(labels),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _training_ready(client, project_id: str, image: dict, boxes, labels) -> dict:
    _save_reviewed_annotation(client, project_id, image["id"], boxes, labels)
    app_module.material_store(project_id).patch({
        image["id"]: {"processing_status": "processed"},
    })
    return image


def _seed_verified_parent_training_evidence(
    client, project_id, algorithm_id, version_id, snapshot_id,
):
    """Real parent Task/Snapshot so a continuation has provable lineage."""
    from dataclasses import replace
    from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus
    from platform_core.training_material_usage import TrainingMaterialUsage

    parent_image = _upload(
        client, project_id, f"parent-{version_id}.jpg", _image_bytes((13, 89, 173)),
    )
    _training_ready(
        client, project_id, parent_image,
        [{"class_id": 0, "label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 80}],
        ["fire"],
    )
    parent_id = f"verified-parent-{version_id}"
    parent = replace(
        TaskRecord.new(parent_id, project_id, TaskKind.TRAINING, "payload.json", "cpu"),
        status=TaskStatus.SUCCEEDED,
    )
    app_module.shared_task_repository().create(
        parent, artifacts=app_module.shared_task_artifacts(),
    )
    material = app_module.material_store(project_id).get(parent_image["id"])
    app_module.shared_task_artifacts().atomic_write_json(parent_id, "snapshot.json", {
        "snapshot_id": snapshot_id,
        "images": [{
            "image_id": parent_image["id"],
            "role": "train",
            "content_sha256": material["content_sha256"],
        }],
    })
    TrainingMaterialUsage(app_module.shared_task_repository()).mark_coverage(
        project_id, algorithm_id, complete=True,
    )
    return parent_id, parent_image


def _freeze_admitted_training(task_id: str) -> dict:
    """Run only the TRAINING_PREPARE contract phase, without trainer startup."""
    from platform_core.remote_training_tasks import TrainingPrepareHandler
    from platform_core.task_runtime import TaskKind, WorkerContext
    from platform_core.task_runtime.preparation_publication import publish_training

    target = app_module.shared_task_repository().get(task_id)
    assert target is not None
    payload = app_module.shared_task_artifacts().read_json(task_id, target.payload_ref)
    handler = TrainingPrepareHandler(app_module.DATA_DIR)
    repository = app_module.shared_task_repository()
    lease = None
    for _ in range(100):
        lease = repository.claim_next(
            "feedback-chain-freezer",
            [TaskKind.TRAINING_PREPARE],
            {"training.prepare"},
            admission=lambda database, candidate, *args: (
                candidate["task_id"] == f"trainprep_{task_id}", "test target",
            ),
        )
        if lease is not None:
            break
    assert lease is not None and lease.task.task_id == f"trainprep_{task_id}"
    context = WorkerContext(
        lease.task, lease, repository, app_module.shared_task_artifacts(),
    )
    try:
        frozen_payload = handler._freeze_request_contract(context, target, payload)
        published = publish_training(context, target, "training.freeze", frozen_payload)
        handler._publish_prepared_job(published.task, frozen_payload)
    finally:
        with repository._connect() as database:
            database.execute(
                "UPDATE tasks SET status='QUEUED',stage='queued',worker_id=NULL,"
                "lease_token=NULL,lease_expires_at=NULL WHERE task_id=? AND lease_token=?",
                (lease.task.task_id, lease.lease_token),
            )
    return frozen_payload


def _prediction_evidence(
    project_id: str, algorithm_id: str, version: dict, raw: bytes, detections,
):
    prediction_id = "feedbackchain" + uuid.uuid4().hex[:8]
    root = app_module.project_dir(project_id) / "predictions"
    root.mkdir(parents=True, exist_ok=True)
    input_path = root / f"{prediction_id}_input.jpg"
    input_path.write_bytes(raw)
    evidence = {
        "schema_version": 1,
        "prediction_id": prediction_id,
        "project_id": project_id,
        "algorithm_id": algorithm_id,
        "version_id": version["id"],
        "model_sha256": app_module.sha256_file(Path(version["stored_path"])),
        "input_sha256": app_module.sha256_file(input_path),
        "original_filename": f"feedback-{prediction_id}.jpg",
        "input_file": input_path.name,
        "width": 128,
        "height": 128,
        "confidence": 0.25,
        "engine": "ultralytics",
        "detections": detections,
        "created_at": app_module.now_iso(),
    }
    app_module.write_json(root / f"{prediction_id}.evidence.json", evidence)
    return prediction_id


def test_online_feedback_reviewed_gt_flows_into_frozen_training_provenance(client):
    created = client.post("/api/projects", json={
        "name": f"feedback-chain-{uuid.uuid4().hex[:8]}",
        "labels": [
            {"code": "fire", "display_name": "明火"},
            {"code": "smoke", "display_name": "烟雾"},
        ],
    })
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "反馈补数据链路算法", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    algorithm_id = algorithm["id"]
    version_id = "feedback-chain-base"
    parent_snapshot_id = "d" * 64
    parent_task_id, _parent_image = _seed_verified_parent_training_evidence(
        client, project_id, algorithm_id, version_id, parent_snapshot_id,
    )
    model_path = app_module.project_dir(project_id) / "feedback-chain.pt"
    model_path.write_bytes(b"verified-feedback-chain-base")
    action = {
        "status": "confirmed",
        "action": "supplement_data",
        "action_id": "a" * 64,
        "source": {"algorithm_id": algorithm_id, "version_id": version_id},
    }
    algorithms = app_module.list_algorithms_internal(project_id)
    target = next(row for row in algorithms if row["id"] == algorithm_id)
    target["current_version_id"] = version_id
    target["versions"] = [{
        "id": version_id,
        "version_name": "20261124000000",
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "training_job_id": parent_task_id,
        "snapshot_id": parent_snapshot_id,
        "trainable": True,
        "framework": "ultralytics",
        "stored_path": str(model_path),
        "label_schema": [{"code": "fire", "class_id": 0, "canonical_project_class_id": 0}],
        "confirmed_iteration_action": action,
    }]
    save_algorithms(app_module.algorithms_file(project_id), algorithms)
    version = target["versions"][0]

    # A reviewed material that already owns valid formal GT. The partial
    # correction must add a missed target without deleting this existing box.
    reviewed_raw = _image_bytes((41, 97, 151))
    reviewed_image = _upload(client, project_id, "reviewed-target.jpg", reviewed_raw)
    existing_box = {
        "class_id": 0, "label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 80,
    }
    _training_ready(client, project_id, reviewed_image, [existing_box], ["fire"])
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    gt_before = annotations.get(reviewed_image["id"])
    assert gt_before["annotation_state"] == "annotated"
    assert len(gt_before["boxes"]) == 1
    gt_before_version = int(gt_before["version"])

    third = _upload(client, project_id, "third.jpg", _image_bytes((181, 144, 51)))
    _training_ready(
        client, project_id, third,
        [{"class_id": 0, "label": "fire", "x1": 20, "y1": 20, "x2": 90, "y2": 90}],
        ["fire"],
    )
    fourth = _upload(client, project_id, "fourth.jpg", _image_bytes((73, 168, 92)))
    _training_ready(
        client, project_id, fourth,
        [{"class_id": 0, "label": "fire", "x1": 15, "y1": 25, "x2": 75, "y2": 95}],
        ["fire"],
    )

    prediction_id = _prediction_evidence(
        project_id, algorithm_id, version, reviewed_raw,
        detections=[{
            "class_id": 0, "label": "fire", "confidence": 0.88,
            "x1": 10, "y1": 10, "x2": 80, "y2": 80,
        }],
    )
    staged = client.post(
        f"/api/v63/projects/{project_id}/online-feedback",
        json={
            "prediction_id": prediction_id,
            "feedback_type": "needs_correction",
            "note": "漏检第二个目标，其余目标框正确",
            "correction_kind": "partial_correction",
        },
    )
    assert staged.status_code == 201, staged.text
    feedback = staged.json()["feedback"]
    confirmed = client.post(
        f"/api/v63/projects/{project_id}/online-feedback/{feedback['id']}/confirm",
        json={
            "expected_feedback_type": "needs_correction",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
            "request_id": "feedback-chain-review",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_feedback = confirmed.json()["feedback"]
    assert confirmed_feedback["result"]["candidate_only"] is True
    assert confirmed_feedback["result"]["gt_written"] is False
    assert confirmed_feedback["result"]["gt_recorded"] is False

    # Feedback itself never wrote GT: the pre-existing formal annotation is
    # byte/version-identical until a human saves the review edit.
    gt_pending = annotations.get(confirmed_feedback["material_id"])
    assert gt_pending["annotation_state"] == "annotated"
    assert gt_pending["version"] == gt_before_version
    assert gt_pending["content_digest"] == gt_before["content_digest"]
    assert len(gt_pending["boxes"]) == 1
    material = app_module.material_store(project_id).get(confirmed_feedback["material_id"])
    assert material["id"] == reviewed_image["id"]
    assert material["processing_status"] == "pending_decision"

    # Human review through the existing annotation API: add only the missed
    # target, keep the already-valid box untouched (partial correction).
    missed_box = {
        "class_id": 0, "label": "fire", "x1": 30, "y1": 60, "x2": 70, "y2": 110,
    }
    _save_reviewed_annotation(
        client, project_id, reviewed_image["id"], [existing_box, missed_box], ["fire"],
    )
    gt_reviewed = annotations.get(reviewed_image["id"])
    assert gt_reviewed["version"] == gt_before_version + 1
    assert len(gt_reviewed["boxes"]) == 2
    reviewed_box = next(row for row in gt_reviewed["boxes"] if row["x1"] == 10)
    assert (reviewed_box["x2"], reviewed_box["y2"]) == (80, 80)
    assert sorted(
        (row["label"], row["x1"], row["y1"], row["x2"], row["y2"])
        for row in gt_reviewed["boxes"]
    ) == [
        ("fire", 10, 10, 80, 80),
        ("fire", 30, 60, 70, 110),
    ]

    listing = client.get(
        f"/api/v63/projects/{project_id}/algorithms/{algorithm_id}/versions/"
        f"{version_id}/supplement-data-candidates"
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    candidate = listing.json()["items"][0]
    assert candidate["feedback_id"] == feedback["id"]
    assert candidate["eligible"] is True
    assert candidate["correction_kind"] == "partial_correction"
    assert candidate["annotation_hash"] == gt_reviewed["content_digest"]

    frozen = client.post(
        f"/api/v63/projects/{project_id}/algorithms/{algorithm_id}/versions/"
        f"{version_id}/supplement-data-candidates/freeze",
        json={"candidates": [{
            "feedback_id": candidate["feedback_id"],
            "candidate_digest": candidate["candidate_digest"],
        }]},
    )
    assert frozen.status_code == 200, frozen.text
    candidate_set = frozen.json()["candidate_set"]
    assert candidate_set["material_ids"] == [reviewed_image["id"]]
    assert candidate_set["feedback_ids"] == [feedback["id"]]
    base_version_before_training = next(
        row
        for row in next(
            algo for algo in app_module.list_algorithms_internal(project_id)
            if algo["id"] == algorithm_id
        )["versions"]
        if row["id"] == version_id
    )
    assert base_version_before_training["snapshot_id"] == parent_snapshot_id
    assert base_version_before_training["artifact_verified"] is True

    # Training creation carries the frozen supplement source identity.
    train_request = {
        "framework": "ultralytics",
        "algorithm_asset_id": algorithm_id,
        "model": "yolo11n.pt",
        "split_mode": "random_test_from_training_pool",
        "train_image_ids": [
            reviewed_image["id"], third["id"], fourth["id"],
        ],
        "test_image_ids": [],
        "experiment_percent": 20,
        "validation_percent": 20,
        "device": "cpu",
        "supplement_candidate_set_id": candidate_set["candidate_set_id"],
    }
    started = client.post(f"/api/v12/projects/{project_id}/train/start", json=train_request)
    assert started.status_code == 202, started.text
    task_id = started.json()["task"]["task_id"]
    task_record = app_module.shared_task_repository().get(task_id)
    assert task_record is not None
    task_payload = app_module.shared_task_artifacts().read_json(
        task_id, task_record.payload_ref, default={},
    )
    assert task_payload["supplement_candidate_set_id"] == candidate_set["candidate_set_id"]
    job = app_module.read_json(
        app_module.project_dir(project_id) / "jobs" / task_id / "job.json", {},
    )
    assert job["supplement_candidate_set_id"] == candidate_set["candidate_set_id"]

    frozen_payload = _freeze_admitted_training(task_id)
    assert (
        frozen_payload["supplement_candidate_set"]["candidate_set_id"]
        == candidate_set["candidate_set_id"]
    )
    snapshot = app_module.shared_task_artifacts().read_json(
        task_id, frozen_payload["snapshot_ref"],
    )
    provenance = snapshot["supplement_provenance"]
    assert provenance["candidate_set_id"] == candidate_set["candidate_set_id"]
    assert provenance["adopted_feedback_ids"] == [feedback["id"]]
    assert provenance["adopted_material_ids"] == [reviewed_image["id"]]
    assert provenance["automatic_execution"] is False

    # The frozen snapshot contains the real human-reviewed sample, not a
    # synthetic placeholder: exact GT hash, two boxes (partial correction kept
    # the existing one), and the reviewed label contract.
    snapshot_row = next(
        row for row in snapshot["images"] if row["image_id"] == reviewed_image["id"]
    )
    assert snapshot_row["annotation_hash"] == gt_reviewed["content_digest"]
    assert snapshot_row["box_count"] == 2
    assert snapshot_row["labels"] == ["fire"]
    assert snapshot_row["annotation_state"] == "annotated"
    assert snapshot["label_counts"]["fire"] >= 2

    revision = app_module.shared_task_artifacts().read_json(
        task_id, frozen_payload["dataset_revision_ref"],
    )
    assert (
        revision["supplement_provenance"]["adoption_id"]
        == provenance["adoption_id"]
    )

    # The frozen training payload carries enough real source identity to
    # deterministically rebuild the same provenance (it is not a display label).
    from platform_core.online_feedback import build_supplement_training_provenance
    reviewed_material = app_module.material_store(project_id).get(reviewed_image["id"])
    rebuilt = build_supplement_training_provenance(
        frozen_payload["supplement_candidate_set"],
        frozen_payload["train_image_ids"],
        [{
            "id": reviewed_image["id"],
            "content_sha256": reviewed_material["content_sha256"],
            "annotation_hash": gt_reviewed["content_digest"],
            "annotation_state": "annotated",
        }],
    )
    assert rebuilt["adoption_id"] == provenance["adoption_id"]
    assert rebuilt["adopted_feedback_ids"] == [feedback["id"]]
    assert rebuilt["automatic_execution"] is False

    # The historical base model/version was never rewritten by this chain, and
    # the next-round training was only queued for preparation -- no trainer was
    # started and no new model version was attached/replaced.
    algorithms_after = app_module.list_algorithms_internal(project_id)
    algorithm_after = next(row for row in algorithms_after if row["id"] == algorithm_id)
    base_version_after = next(
        row for row in algorithm_after["versions"] if row["id"] == version_id
    )
    for immutable_key in (
        "id", "snapshot_id", "training_job_id", "training_lineage",
        "artifact_verified", "stored_path", "trainable", "framework",
        "label_schema", "supplement_data_candidate_set",
    ):
        assert (
            base_version_after.get(immutable_key)
            == base_version_before_training.get(immutable_key)
        ), f"historical model identity changed: {immutable_key}"
    assert len(algorithm_after["versions"]) == 1
    assert app_module.shared_task_repository().get(task_id).status.value == "QUEUED"

    # Repeat review of the already-confirmed feedback returns the same receipt;
    # it never re-enters GT and never changes the frozen candidate identity.
    repeated = client.post(
        f"/api/v63/projects/{project_id}/online-feedback/{feedback['id']}/confirm",
        json={
            "expected_feedback_type": "needs_correction",
            "dataset_id": "default",
            "confirm_all_labels_absent": False,
            "request_id": "feedback-chain-review",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["feedback"]["material_id"] == reviewed_image["id"]
    assert annotations.get(reviewed_image["id"])["version"] == gt_before_version + 1
