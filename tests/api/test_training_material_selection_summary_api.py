from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.training_material_picker_api import training_material_picker_router


def _record(index: int, *, annotated: bool = True) -> dict:
    image_id = f"s{index:05d}"
    labels = ["smoke"] if index % 2 == 0 else ["person"]
    if index % 5 == 0:
        labels.append("helmet")
    return {
        "id": image_id,
        "filename": f"summary-{index:05d}.jpg",
        "storage_source_id": "default_local",
        "storage_type": "local",
        "object_key": f"uploads/{image_id}.jpg",
        "content_sha256": f"{index + 1:064x}"[-64:],
        "size_bytes": 1000 + index,
        "processing_status": "processed",
        "box_count": 2 if annotated else 0,
        "annotated": annotated,
        "labels": labels if annotated else [],
        "created_at": f"2026-09-15T12:{(index // 60) % 60:02d}:{index % 60:02d}+00:00",
    }


def _client(tmp_path):
    data_dir = tmp_path / "data"
    project_path = data_dir / "projects" / "p1"
    repository = MaterialRepository(project_path)
    repository.upsert_many([_record(index, annotated=index < 1000) for index in range(1200)])

    annotations = AnnotationRepository(project_path)
    rows = []
    for index in range(1000):
        base_label = "smoke" if index % 2 == 0 else "person"
        labels = [base_label]
        second_label = "helmet" if index % 5 == 0 else base_label
        labels.append(second_label)
        rows.append({
            "image_id": f"s{index:05d}",
            "annotation_state": "annotated",
            "annotation_scope": sorted(set(labels)),
            "boxes": [
                {
                    "id": f"box-{index}-0",
                    "label": base_label,
                    "class_id": 0 if base_label == "smoke" else 1,
                    "x1": 10,
                    "y1": 10,
                    "x2": 30,
                    "y2": 30,
                },
                {
                    "id": f"box-{index}-1",
                    "label": second_label,
                    "class_id": (
                        2 if second_label == "helmet"
                        else (0 if second_label == "smoke" else 1)
                    ),
                    "x1": 40,
                    "y1": 40,
                    "x2": 60,
                    "y2": 60,
                },
            ],
        })
    for offset in range(0, len(rows), 500):
        annotations.upsert_many(
            rows[offset:offset + 500],
            project_material=False,
        )

    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == "p1" else None,
        lambda: data_dir,
    ))
    return TestClient(app)


def test_selection_summary_aggregates_selected_ids_without_returning_material_rows(tmp_path):
    client = _client(tmp_path)
    requested = [f"s{index:05d}" for index in range(1100)] + ["missing-material", "s00001"]
    response = client.post(
        "/api/v62/projects/p1/training-materials/selection-summary",
        json={"image_ids": requested},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["requested_count"] == 1101
    assert body["matched_count"] == 1100
    assert body["eligible_count"] == 1000
    assert body["eligible_total"] == 1000
    assert body["box_count"] == 2000
    assert body["label_counts"]["smoke"] == 500
    assert body["label_counts"]["person"] == 500
    assert body["label_counts"]["helmet"] == 200
    assert set(body["label_codes"]) == {"smoke", "person", "helmet"}
    assert "items" not in body


def test_selection_summary_empty_selection_still_returns_available_training_total(tmp_path):
    client = _client(tmp_path)
    response = client.post(
        "/api/v62/projects/p1/training-materials/selection-summary",
        json={"image_ids": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["requested_count"] == 0
    assert body["eligible_count"] == 0
    assert body["eligible_total"] == 1000
    assert body["label_codes"] == []


def test_selection_summary_rejects_non_list_ids(tmp_path):
    client = _client(tmp_path)
    response = client.post(
        "/api/v62/projects/p1/training-materials/selection-summary",
        json={"image_ids": "s00001"},
    )
    assert response.status_code == 422


def _compatibility_client(tmp_path):
    data_dir = tmp_path / "data"
    project_path = data_dir / "projects" / "p1"
    project_path.mkdir(parents=True)
    (project_path / "meta.json").write_text(
        json.dumps({
            "label_meta": [
                {"code": "helmet", "class_id": 0, "active": True},
                {"code": "person", "class_id": 1, "active": True},
            ],
        }),
        encoding="utf-8",
    )
    materials = MaterialRepository(project_path)
    materials.upsert_many([
        {
            **_record(1),
            "id": "partial",
            "filename": "partial.jpg",
            "labels": ["helmet"],
            "dataset_id": "default",
        },
        {
            **_record(2),
            "id": "complete",
            "filename": "complete.jpg",
            "labels": ["person"],
            "dataset_id": "default",
        },
    ])
    annotations = AnnotationRepository(project_path)
    annotations.upsert(
        "partial",
        [{"label": "helmet", "class_id": 0, "x1": 1, "y1": 1, "x2": 10, "y2": 10}],
        annotation_state="annotated",
        annotation_scope=["helmet"],
        project_material=False,
    )
    annotations.upsert(
        "complete",
        [{"label": "person", "class_id": 1, "x1": 1, "y1": 1, "x2": 10, "y2": 10}],
        annotation_state="annotated",
        annotation_scope=["helmet", "person"],
        project_material=False,
    )
    algorithm = {"id": "alg-1", "versions": []}
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == "p1" else None,
        lambda: data_dir,
        algorithm_provider=lambda project_id, algorithm_id: (
            algorithm if project_id == "p1" and algorithm_id == "alg-1" else None
        ),
    ))
    return TestClient(app)


def test_training_compatibility_lists_all_missing_labels(tmp_path):
    client = _compatibility_client(tmp_path)

    response = client.post(
        "/api/v62/projects/p1/training-materials/compatibility",
        json={
            "algorithm_asset_id": "alg-1",
            "image_ids": ["partial", "complete"],
            "train_labels": ["helmet", "person"],
            "model": "yolo11n.pt",
            "framework": "ultralytics",
            "split_mode": "random_test_from_training_pool",
            "experiment_percent": 20,
            "validation_percent": 20,
            "limit": 50,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["issue_count"] == 1
    assert body["effective_label_codes"] == ["helmet", "person"]
    assert body["items"][0]["image_id"] == "partial"
    assert body["items"][0]["missing_label_codes"] == ["person"]
    assert body["items"][0]["filename"] == "partial.jpg"
    assert body["items"][0]["thumbnail_url"].endswith(
        "/training-materials/partial/thumbnail?size=192"
    )


def test_training_compatibility_accepts_final_training_submit_payload(tmp_path):
    client = _compatibility_client(tmp_path)

    response = client.post(
        "/api/v62/projects/p1/training-materials/compatibility",
        json={
            "algorithm_asset_id": "alg-1",
            "train_image_ids": ["partial", "complete"],
            "test_image_ids": [],
            "train_labels": ["helmet", "person"],
            "model": "yolo11n.pt",
            "framework": "ultralytics",
            "split_mode": "random_test_from_training_pool",
            "experiment_percent": 20,
            "validation_percent": 20,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["issue_count"] == 1
    assert response.json()["items"][0]["image_id"] == "partial"


def test_training_compatibility_rejects_unknown_algorithm(tmp_path):
    client = _compatibility_client(tmp_path)

    response = client.post(
        "/api/v62/projects/p1/training-materials/compatibility",
        json={
            "algorithm_asset_id": "missing",
            "image_ids": ["partial"],
            "train_labels": ["helmet"],
        },
    )

    assert response.status_code == 404


def test_training_compatibility_passes_after_explicit_partial_review(tmp_path):
    client = _compatibility_client(tmp_path)
    project_path = tmp_path / "data" / "projects" / "p1"
    annotations = AnnotationRepository(project_path)
    current = annotations.get("partial")
    saved = annotations.upsert(
        "partial",
        current["boxes"],
        annotation_state="annotated",
        annotation_scope=["helmet", "person"],
        expected_version=current["version"],
        project_material=False,
    )
    assert saved["annotation_scope"] == ["helmet", "person"]

    response = client.post(
        "/api/v62/projects/p1/training-materials/compatibility",
        json={
            "algorithm_asset_id": "alg-1",
            "image_ids": ["partial", "complete"],
            "train_labels": ["helmet", "person"],
            "model": "yolo11n.pt",
            "framework": "ultralytics",
            "split_mode": "random_test_from_training_pool",
            "experiment_percent": 20,
            "validation_percent": 20,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["compatible"] is True
    assert response.json()["issue_count"] == 0
