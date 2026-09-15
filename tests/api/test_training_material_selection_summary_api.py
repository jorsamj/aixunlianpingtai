from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    repository = MaterialRepository(data_dir / "projects" / "p1")
    repository.upsert_many([_record(index, annotated=index < 1000) for index in range(1200)])
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
