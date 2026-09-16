from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from platform_core.material_repository import MaterialRepository
from platform_core.training_material_picker_api import training_material_picker_router


def _record(index: int, *, annotated: bool = True) -> dict:
    image_id = f"m{index:04d}"
    return {
        "id": image_id,
        "filename": f"material-{index:04d}.jpg",
        "storage_source_id": "default_local",
        "storage_type": "local",
        "object_key": f"uploads/{image_id}.jpg",
        "content_sha256": f"{index + 1:064x}"[-64:],
        "size_bytes": 1024 + index,
        "processing_status": "processed",
        "box_count": 1 if annotated else 0,
        "annotated": annotated,
        "labels": ["smoke"] if index % 2 == 0 else ["person"],
        "created_at": f"2026-09-15T12:{index // 60:02d}:{index % 60:02d}+00:00",
    }


def _client(tmp_path):
    data_dir = tmp_path / "data"
    project_path = data_dir / "projects" / "p1"
    repository = MaterialRepository(project_path)
    repository.upsert_many([_record(index, annotated=index < 230) for index in range(260)])
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == "p1" else None,
        lambda: data_dir,
    ))
    return TestClient(app), repository


def test_training_picker_is_server_paged_and_filtered(tmp_path):
    client, _repository = _client(tmp_path)

    first = client.get("/api/v62/projects/p1/training-materials", params={"limit": 120})
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 230
    assert body["limit"] == 120
    assert len(body["items"]) == 120
    assert body["next_cursor"]
    assert all(item["annotated"] is True for item in body["items"])
    assert all("thumbnail_url" in item and "content_url" in item for item in body["items"])
    assert all("size=192" in item["thumbnail_url"] for item in body["items"])

    second = client.get(
        "/api/v62/projects/p1/training-materials",
        params={"limit": 120, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 110
    assert {item["id"] for item in body["items"]}.isdisjoint({item["id"] for item in second_body["items"]})

    smoke = client.get(
        "/api/v62/projects/p1/training-materials",
        params=[("limit", "120"), ("label", "smoke")],
    )
    assert smoke.status_code == 200
    assert smoke.json()["total"] == 115
    assert all("smoke" in item["labels"] for item in smoke.json()["items"])

    search = client.get(
        "/api/v62/projects/p1/training-materials",
        params={"query": "material-0007"},
    )
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["id"] == "m0007"


def test_training_picker_ids_support_explicit_bulk_selection_without_full_rows(tmp_path):
    client, _repository = _client(tmp_path)
    cursor = None
    ids = []
    totals = set()
    while True:
        params = [("limit", "80"), ("label", "person")]
        if cursor:
            params.append(("cursor", cursor))
        response = client.get("/api/v62/projects/p1/training-materials/ids", params=params)
        assert response.status_code == 200
        body = response.json()
        ids.extend(body["items"])
        totals.add(body["total"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert totals == {115}
    assert len(ids) == 115
    assert len(set(ids)) == 115


def test_training_picker_thumbnail_is_lazy_cached(tmp_path, monkeypatch):
    client, repository = _client(tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (900, 600), "white").save(source)
    calls = {"count": 0}

    def materialize(_self, _value):
        calls["count"] += 1
        return SimpleNamespace(path=source)

    monkeypatch.setattr(
        "platform_core.training_material_picker_api.StorageManager.materialize",
        materialize,
    )

    first = client.get("/api/v62/projects/p1/training-materials/m0001/thumbnail?size=256")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("image/jpeg")
    assert "max-age=604800" in first.headers.get("cache-control", "")
    assert calls["count"] == 1

    second = client.get("/api/v62/projects/p1/training-materials/m0001/thumbnail?size=256")
    assert second.status_code == 200
    assert calls["count"] == 1
    with Image.open(source) as original:
        assert original.size == (900, 600)
    assert repository.get("m0001") is not None