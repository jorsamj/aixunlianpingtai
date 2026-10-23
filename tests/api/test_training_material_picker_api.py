from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
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
        "labels": (["smoke"] if index % 2 == 0 else ["person"]) if annotated else [],
        "width": 400,
        "height": 200,
        "created_at": f"2026-09-15T12:{index // 60:02d}:{index % 60:02d}+00:00",
    }


def _client(tmp_path):
    data_dir = tmp_path / "data"
    project_path = data_dir / "projects" / "p1"
    repository = MaterialRepository(project_path)
    repository.upsert_many([_record(index, annotated=index < 230) for index in range(260)])
    AnnotationRepository(project_path).upsert_many([
        {
            "image_id": f"m{index:04d}",
            "annotation_state": "annotated",
            "boxes": [{
                "id": f"box-{index}",
                "label": "smoke" if index % 2 == 0 else "person",
                "class_id": 0 if index % 2 == 0 else 1,
                "x1": 40,
                "y1": 20,
                "x2": 200,
                "y2": 100,
            }],
        }
        for index in range(230)
    ])
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == "p1" else None,
        lambda: data_dir,
    ))
    return TestClient(app), repository


def test_training_picker_is_server_paged_and_filtered(tmp_path):
    client, _repository = _client(tmp_path)

    default_page = client.get("/api/v62/projects/p1/training-materials")
    assert default_page.status_code == 200
    assert default_page.json()["limit"] == 60
    assert len(default_page.json()["items"]) == 60

    first = client.get("/api/v62/projects/p1/training-materials", params={"limit": 120})
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 260
    assert body["limit"] == 120
    assert len(body["items"]) == 120
    assert body["next_cursor"]
    assert all(item["annotated"] is True for item in body["items"])
    assert all("thumbnail_url" in item and "content_url" in item for item in body["items"])
    assert all("size=192" in item["thumbnail_url"] for item in body["items"])

    too_large = client.get("/api/v62/projects/p1/training-materials", params={"limit": 121})
    assert too_large.status_code == 422

    second = client.get(
        "/api/v62/projects/p1/training-materials",
        params={"limit": 120, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 120
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


def test_training_picker_batch_reads_formal_annotation_truth_for_current_page(tmp_path, monkeypatch):
    client, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    annotations.upsert("m0001", [], "confirmed_empty", project_material=False)
    annotations.upsert("m0002", [], "unannotated", project_material=False)
    calls = []
    original = AnnotationRepository.get_many

    def tracked_get_many(self, image_ids):
        ids = list(image_ids)
        calls.append(ids)
        return original(self, ids)

    monkeypatch.setattr(AnnotationRepository, "get_many", tracked_get_many)
    response = client.get("/api/v62/projects/p1/training-materials", params={"limit": 60})

    assert response.status_code == 200
    items = {item["image_id"]: item for item in response.json()["items"]}
    assert len(calls) == 1
    assert len(calls[0]) == 60
    assert items["m0000"]["width"] == 400
    assert items["m0000"]["height"] == 200
    assert items["m0000"]["annotation_state"] == "annotated"
    assert items["m0000"]["boxes"][0]["x1"] == 40
    assert items["m0001"]["annotation_state"] == "confirmed_empty"
    assert items["m0001"]["boxes"] == []
    assert items["m0002"]["annotation_state"] == "unannotated"
    assert items["m0002"]["boxes"] == []


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


def test_training_picker_bulk_selection_resolves_filtered_ids_in_one_request(tmp_path):
    client, _repository = _client(tmp_path)

    filtered = client.post(
        "/api/v62/projects/p1/training-materials/bulk-selection",
        json={"query": "", "labels": ["smoke"], "all_available": False},
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["selection_mode"] == "filtered"
    assert filtered_body["total"] == 115
    assert len(filtered_body["items"]) == 115
    assert len(set(filtered_body["items"])) == 115

    all_available = client.post(
        "/api/v62/projects/p1/training-materials/bulk-selection",
        json={"query": "ignored", "labels": ["person"], "all_available": True},
    )
    assert all_available.status_code == 200
    all_body = all_available.json()
    assert all_body["selection_mode"] == "all_available"
    assert all_body["total"] == 260
    assert len(all_body["items"]) == 260

    test_only = client.post(
        "/api/v62/projects/p1/training-materials/bulk-selection",
        json={"query": "", "labels": [], "all_available": True, "role": "test"},
    )
    assert test_only.status_code == 200
    assert test_only.json()["total"] == 230
    assert len(test_only.json()["items"]) == 230


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


def test_cleaned_unannotated_material_is_selectable_but_not_counted_as_ground_truth(tmp_path):
    client, _repository = _client(tmp_path)

    page = client.get(
        "/api/v62/projects/p1/training-materials",
        params={"limit": 60, "query": "material-0250"},
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == "m0250"
    assert item["processing_status"] == "processed"
    assert item["annotation_state"] == "unannotated"
    assert item["training_state"] == "pending_annotation"
    assert item["annotated"] is False

    summary = client.post(
        "/api/v62/projects/p1/training-materials/selection-summary",
        json={"image_ids": ["m0000", "m0001", "m0250"]},
    )
    assert summary.status_code == 200
    facts = summary.json()
    assert facts["matched_count"] == 3
    assert facts["selectable_count"] == 3
    assert facts["eligible_count"] == 2
    assert facts["pending_annotation_count"] == 1
    assert facts["selectable_total"] == 260
    assert facts["eligible_total"] == 230
    assert facts["pending_annotation_total"] == 30



def test_training_picker_summary_and_test_bulk_ignore_stale_material_annotation_projection(
    tmp_path,
):
    client, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)

    # Material projection intentionally remains the opposite of formal GT.
    assert repository.get("m0000")["annotated"] is True
    assert repository.get("m0250")["annotated"] is False
    annotations.upsert(
        "m0000",
        [],
        "unannotated",
        project_material=False,
    )
    annotations.upsert(
        "m0250",
        [{
            "id": "formal-smoke-250",
            "label": "smoke",
            "class_id": 0,
            "x1": 40,
            "y1": 20,
            "x2": 200,
            "y2": 100,
        }],
        "annotated",
        annotation_scope=["smoke"],
        project_material=False,
    )

    summary = client.post(
        "/api/v62/projects/p1/training-materials/selection-summary",
        json={"image_ids": ["m0000", "m0250"]},
    )
    assert summary.status_code == 200, summary.text
    facts = summary.json()
    assert facts["matched_count"] == 2
    assert facts["selectable_count"] == 2
    assert facts["eligible_count"] == 1
    assert facts["pending_annotation_count"] == 1
    assert facts["box_count"] == 1
    assert facts["label_codes"] == ["smoke"]
    assert facts["label_counts"] == {"smoke": 1}
    assert facts["size_bytes"] == repository.get("m0250")["size_bytes"]
    assert facts["eligible_total"] == 230
    assert facts["pending_annotation_total"] == 30

    selected = client.post(
        "/api/v62/projects/p1/training-materials/bulk-selection",
        json={
            "query": "",
            "labels": [],
            "all_available": True,
            "role": "test",
        },
    )
    assert selected.status_code == 200, selected.text
    body = selected.json()
    assert body["total"] == 230
    assert "m0000" not in body["items"]
    assert "m0250" in body["items"]

    label_page = client.get(
        "/api/v62/projects/p1/training-materials",
        params=[("limit", "120"), ("label", "smoke")],
    )
    assert label_page.status_code == 200, label_page.text
    label_page_body = label_page.json()
    label_page_ids = {item["id"] for item in label_page_body["items"]}
    assert label_page_body["total"] == 115
    assert "m0000" not in label_page_ids
    assert "m0250" in label_page_ids

    label_ids = client.get(
        "/api/v62/projects/p1/training-materials/ids",
        params=[("limit", "500"), ("label", "smoke")],
    )
    assert label_ids.status_code == 200, label_ids.text
    label_ids_body = label_ids.json()
    assert label_ids_body["total"] == 115
    assert "m0000" not in label_ids_body["items"]
    assert "m0250" in label_ids_body["items"]

    label_bulk = client.post(
        "/api/v62/projects/p1/training-materials/bulk-selection",
        json={
            "query": "",
            "labels": ["smoke"],
            "all_available": False,
            "role": "train",
        },
    )
    assert label_bulk.status_code == 200, label_bulk.text
    label_bulk_body = label_bulk.json()
    assert label_bulk_body["total"] == 115
    assert "m0000" not in label_bulk_body["items"]
    assert "m0250" in label_bulk_body["items"]


def test_training_picker_creation_time_order_across_pages_and_formal_labels(tmp_path):
    client, _ = _client(tmp_path)
    endpoint = "/api/v62/projects/p1/training-materials"
    for order, expected in (
        ("newest", ["m0259", "m0258", "m0257"]),
        ("oldest", ["m0000", "m0001", "m0002"]),
    ):
        first = client.get(endpoint, params={"page": 1, "page_size": 3, "sort_order": order})
        assert first.status_code == 200, first.text
        assert [row["id"] for row in first.json()["items"]] == expected
        second = client.get(endpoint, params={"page": 2, "page_size": 3, "sort_order": order})
        assert second.status_code == 200, second.text
        assert {row["id"] for row in first.json()["items"]}.isdisjoint(
            {row["id"] for row in second.json()["items"]}
        )
    smoke = client.get(endpoint, params=[("page", "1"), ("page_size", "2"),
                                         ("label", "smoke"), ("sort_order", "newest")])
    assert smoke.status_code == 200, smoke.text
    assert [row["id"] for row in smoke.json()["items"]] == ["m0228", "m0226"]
    assert client.get(endpoint, params={"sort_order": "invalid"}).status_code == 422


def test_training_picker_newest_cursor_has_no_duplicate_materials(tmp_path):
    client, _ = _client(tmp_path)
    endpoint = "/api/v62/projects/p1/training-materials"
    first = client.get(endpoint, params={"limit": 3, "sort_order": "newest"})
    assert first.status_code == 200, first.text
    assert [row["id"] for row in first.json()["items"]] == ["m0259", "m0258", "m0257"]
    second = client.get(endpoint, params={
        "limit": 3, "sort_order": "newest",
        "cursor": first.json()["next_cursor"],
    })
    assert second.status_code == 200, second.text
    assert [row["id"] for row in second.json()["items"]] == ["m0256", "m0255", "m0254"]


def test_task_role_sql_page_uses_formal_scope_and_bounds_payload(tmp_path, monkeypatch):
    from platform_core.training_material_picker_api import _role_material_page
    client, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    old = annotations.get("m0001")
    annotations.upsert("m0001", old["boxes"], "annotated", annotation_scope=["person", "smoke"])
    # The material's denormalized labels must not determine the task role.
    result = _role_material_page(repository, annotations, {"effective_label_codes": ["smoke"]}, limit=2)
    assert result["sample_role_counts"] == {"positive": 115, "confirmed_negative": 1, "pending_review": 144}
    assert len(result["items"]) == 2
    pending = _role_material_page(repository, annotations, {"effective_label_codes": ["smoke"]},
                                  labels=["person"], sample_role="pending_review", limit=3)
    assert pending["total"] == 114
    assert len(pending["items"]) == 3
    assert all(row["sample_role"] == "pending_review" for row in pending["items"])
    selected = _role_material_page(repository, annotations, {"effective_label_codes": ["smoke"]},
                                   image_ids=["m0000", "m0001", "m0259"], limit=1)
    assert selected["sample_role_counts"] == {"positive": 1, "confirmed_negative": 1, "pending_review": 1}


def test_role_page_and_review_keep_existing_formal_callback(tmp_path, monkeypatch):
    import platform_core.training_label_tasks as labels
    def preview_contract(*args, **kwargs):
        assert kwargs == {"require_positive_evidence": False}
        return {"effective_label_codes": ["smoke"]}
    monkeypatch.setattr(labels, "resolve_training_label_contract", preview_contract)
    _, repository = _client(tmp_path)
    calls = []
    def review(project, item, codes, actor):
        calls.append((project, item, codes, actor))
        if item["image_id"] == "m0003":
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail="stale GT")
    app = FastAPI()
    app.include_router(training_material_picker_router(lambda p: {"id": p}, repository.project_path.parents[1],
        algorithm_provider=lambda *a: {"id": "a"}, review_negative_provider=review,
        actor_provider=lambda request, project: {"id": "reviewer"},
        compatibility_payload_provider=lambda *args: (_ for _ in ()).throw(AssertionError("full admission on preview"))))
    client = TestClient(app)
    endpoint = "/api/v62/projects/p1/training-materials"
    page = client.post(endpoint + "/role-page", json={"algorithm_asset_id": "a", "train_labels": ["smoke"],
                                                       "sample_role": "pending_review", "page_size": 2})
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 145
    row = page.json()["items"][0]
    assert row["annotation_version"] == 1
    assert row["boxes"] and row["source_content_sha256"] and row["content_url"]
    payload = {"algorithm_asset_id": "a", "items": [{"image_id": "m0001"}, {"image_id": "m0003"}]}
    assert client.post(endpoint + "/review-negative", json=payload).status_code == 422
    assert not calls
    response = client.post(endpoint + "/review-negative", json={**payload, "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["succeeded"] == ["m0001"]
    assert response.json()["failures"] == [{"image_id": "m0003", "status_code": 409, "message": "stale GT"}]
    assert calls[0][2:] == (["smoke"], {"id": "reviewer"})
    assert client.post(endpoint + "/review-negative", json={**payload, "confirmed": True,
        "items": [{"image_id": str(i)} for i in range(51)]}).status_code == 422
    bulk = client.post(endpoint + "/bulk-selection", json={"algorithm_asset_id": "a", "sample_role": "positive"})
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["total"] == 115


def test_ten_thousand_candidates_role_page_returns_only_requested_page(tmp_path):
    from platform_core.training_material_picker_api import _role_material_page
    repository = MaterialRepository(tmp_path / "large")
    repository.upsert_many([_record(i, annotated=False) for i in range(10000)])
    annotations = AnnotationRepository(repository.project_path)
    for offset in range(0,3500,500):
        annotations.upsert_many([{"image_id":f"m{i:04d}","annotation_state":"annotated",
            "annotation_scope":["vest" if i<500 else "person"],
            "boxes":[{"label":"vest" if i<500 else "person","x1":10,"y1":10,"x2":40,"y2":50}]} for i in range(offset,offset+500)])
    initial = _role_material_page(repository, annotations, {"effective_label_codes":["vest"]},
                                 image_ids=[f"m{i:04d}" for i in range(3500)], limit=1)
    assert initial["sample_role_counts"] == {"positive":500,"confirmed_negative":0,"pending_review":3000}
    result = _role_material_page(repository, annotations,
                                 {"effective_label_codes": ["vest"]}, page=100, limit=50)
    assert result["total"] == 10000
    assert result["sample_role_counts"]["pending_review"] == 9500
    assert len(result["items"]) == 50
    assert result["page"] == 100
