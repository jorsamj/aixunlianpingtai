from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.training_material_picker_api import training_material_picker_router, _public_picker_material, _selection_summary
import platform_core.training_material_picker_api as picker_module


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


def test_picker_objective_annotation_issue_is_not_target_role_or_generic_review():
    material = _record(1)
    annotation = {"annotation_state":"annotated", "boxes":[{
        "label":"person", "x1":10, "y1":10, "x2":50, "y2":60}]}
    assert _public_picker_material("p1", material, annotation)["annotation_issue_type"] == ""
    assert _public_picker_material("p1", {**material,"source_available":False}, annotation)["annotation_issue_type"] == "material_unavailable"
    assert _public_picker_material("p1", {**material,"annotation_needs_review":True}, annotation)["annotation_issue_type"] == "annotation_needs_review"
    assert _public_picker_material("p1", {**material,"annotation_source_content_sha256":"f"*64}, annotation)["annotation_issue_type"] == "stale_ground_truth"
    assert _public_picker_material("p1", material, {"annotation_state":"annotated", "boxes":[]})["annotation_issue_type"] == "invalid_annotation"


def test_new_label_evidence_does_not_accept_unavailable_source_or_invalid_formal_box(tmp_path):
    client, repo = _client(tmp_path)
    repo.patch({"m0000":{"source_available":False}})
    AnnotationRepository(repo.project_path).upsert(
        "m0250", [{"label":"helmet","x1":80,"y1":30,"x2":10,"y2":100}],
        annotation_state="annotated",annotation_scope=["helmet"],project_material=False)
    response = client.post("/api/v62/projects/p1/training-materials/selection-summary",
        json={"image_ids":["m0000","m0250"]})
    assert response.status_code == 200, response.text
    assert response.json()["label_codes"] == ["helmet", "smoke"]
    assert response.json()["positive_label_codes"] == []


def test_iteration_selection_summary_accepts_empty_preview_without_submission_validation(tmp_path):
    client, _repo = _client(tmp_path)
    # Invoke the registered FastAPI endpoint directly as well: this contract
    # remains deterministic on test hosts where TestClient's loop can stall.
    route = next(route for route in client.app.routes
                 if route.path.endswith("/training-materials/selection-summary"))
    summary = route.endpoint("p1", {
        "algorithm_asset_id": "algorithm-a", "base_version_id": "version-v1",
        "image_ids": [], "train_labels": [],
    })
    assert summary["requested_count"] == 0
    assert summary["matched_count"] == 0
    assert summary["eligible_count"] == 0
    assert summary["positive_label_codes"] == []


def test_selection_positive_evidence_rejects_concurrent_material_revision(tmp_path, monkeypatch):
    _, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    original = annotations.get_many
    changed = False

    def concurrent_change(ids):
        nonlocal changed
        result = original(ids)
        if not changed:
            changed = True
            repository.patch({"m0000":{"size_bytes":98765}})
        return result

    monkeypatch.setattr(annotations, "get_many", concurrent_change)
    with pytest.raises(ValueError, match="已变化"):
        _selection_summary(repository, annotations, ["m0000"])


def test_picker_target_issue_is_explained_without_relaxing_negative_review(tmp_path, monkeypatch):
    import platform_core.training_label_tasks as labels
    monkeypatch.setattr(labels, "resolve_training_label_contract", lambda *args, **kwargs: {
        "effective_label_codes": ["smoke"]})
    _, repo = _client(tmp_path)
    repo.patch({"m0000":{"source_available":False}})
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id:{"id":project_id},repo.project_path.parents[1],
        algorithm_provider=lambda *args:{"id":"algorithm"}))
    with TestClient(app) as client:
        result = client.post("/api/v62/projects/p1/training-materials/role-page", json={
            "algorithm_asset_id":"algorithm", "history_policy":"include_history", "query":"material-0000"})
        assert result.status_code == 200, result.text
        row = result.json()["items"][0]
        assert row["sample_role"] == "pending_review"
        assert row["sample_role_issue_type"] == "annotation_needs_review"
        assert row["annotation_issue_type"] == "material_unavailable"


def test_negative_pool_filter_parity_and_role_cache_revision(tmp_path, monkeypatch):
    from platform_core.negative_pool import NegativePool
    import platform_core.training_label_tasks as labels
    monkeypatch.setattr(labels, 'resolve_training_label_contract', lambda *a, **k: {'effective_label_codes':['smoke']})
    _,repository=_client(tmp_path)
    pool=NegativePool(repository)
    a=pool.category(name='手机')['id']; b=pool.category(name='反光')['id']
    pool.members(['m0000','m0001'],category_ids=[a])
    pool.members(['m0002'],category_ids=[b])
    assert pool.candidate_ids([a])==['m0000','m0001']
    revision=pool.revision()
    app=FastAPI()
    app.include_router(training_material_picker_router(lambda p:{'id':p},repository.project_path.parents[1],algorithm_provider=lambda *a:{'id':'a'}))
    with TestClient(app) as client:
        endpoint='/api/v62/projects/p1/training-materials'
        query={'negative_pool_only':True,'negative_category_id':a,'history_policy':'include_history'}
        page=client.get(endpoint,params=query)
        assert page.status_code==200,page.text
        assert {r['id'] for r in page.json()['items']}=={'m0000','m0001'}
        body={'negative_pool_only':True,'negative_category_ids':[a],'history_policy':'include_history','algorithm_asset_id':'a'}
        roles=client.post(endpoint+'/role-page',json=body)
        assert roles.status_code==200,roles.text
        assert roles.json()['sample_role_counts']['positive']==1
        assert roles.json()['sample_role_counts']['pending_negative']==1
        bulk=client.post(endpoint+'/bulk-selection',json=body)
        assert bulk.status_code==200,bulk.text
        assert set(bulk.json()['items'])=={'m0000','m0001'}
        pool.members(['m0001'],action='remove')
        assert pool.revision()!=revision
        updated=client.post(endpoint+'/role-page',json=body)
        assert updated.status_code==200,updated.text
        assert updated.json()['total']==1


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


def test_formal_gt_filtered_count_reused_and_invalidated_by_both_revisions(tmp_path, monkeypatch):
    client, repository = _client(tmp_path)
    statements = []
    connect = sqlite3.connect

    def tracked_connect(path, *args, **kwargs):
        database = connect(path, *args, **kwargs)
        if str(path) == str(repository.path):
            database.set_trace_callback(statements.append)
        return database

    monkeypatch.setattr(picker_module.sqlite3, "connect", tracked_connect)
    endpoint = "/api/v62/projects/p1/training-materials"
    filters = [("label", "smoke"), ("limit", "30")]

    first = client.get(endpoint, params=filters)
    second = client.get(endpoint, params=[*filters, ("page", "2")])
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 115

    def count_queries():
        return [sql for sql in statements if "SELECT COUNT(*) FROM materials m" in sql]

    assert len(count_queries()) == 1, "same GT/material revisions should reuse the exact filtered count"

    AnnotationRepository(repository.project_path).upsert(
        "m0000", [{"id": "changed-label", "label": "person", "class_id": 1,
                   "x1": 40, "y1": 20, "x2": 200, "y2": 100}],
        "annotated", project_material=False,
    )
    after_gt_change = client.get(endpoint, params=filters)
    assert after_gt_change.status_code == 200
    assert after_gt_change.json()["total"] == 114
    assert len(count_queries()) == 2

    repository.patch_many(["m0002"], {"processing_status": "pending_decision"})
    after_material_change = client.get(endpoint, params=filters)
    assert after_material_change.status_code == 200
    assert after_material_change.json()["total"] == 113
    assert len(count_queries()) == 3


def test_gt_page_reuses_attached_snapshot_for_negative_revisions(tmp_path, monkeypatch):
    """A filtered page must not reopen both DBs after its page snapshot ends."""
    from platform_core.negative_pool import NegativePool

    _client_instance, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    pool = NegativePool(repository)
    pool.category(name="已审核负样本")
    expected_pool_revision = pool.revision()
    with sqlite3.connect(annotations.path) as database:
        database.execute(
            "CREATE TABLE task_negative_confirmations ("
            "receipt_id TEXT PRIMARY KEY, context_key TEXT NOT NULL, evidence_json TEXT NOT NULL)"
        )
        database.execute(
            "INSERT INTO task_negative_confirmations VALUES ('receipt-1','task-1','{}')"
        )

    def unexpected_extra_connection(*args, **kwargs):
        raise AssertionError("revision metadata must come from the attached page snapshot")

    monkeypatch.setattr(annotations, "task_negative_confirmation_revision", unexpected_extra_connection)
    monkeypatch.setattr(NegativePool, "revision", unexpected_extra_connection)
    page = picker_module._gt_material_filter_page(
        repository, annotations, limit=20, labels=("smoke",), include_payload=False,
    )
    assert page["total"] == 115
    assert page["negative_confirmation_revision"] == 1
    assert page["negative_pool_revision"] == expected_pool_revision


def test_gt_page_rejects_stale_negative_pool_filter_snapshot(tmp_path, monkeypatch):
    """Membership changed after prefiltering must never masquerade as a fresh GT page."""
    from platform_core.negative_pool import NegativePool

    _client_instance, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    pool = NegativePool(repository)
    category = pool.category(name="安全教育")['id']
    pool.members(["m0000"], category_ids=[category])
    original_pool_filters = picker_module._pool_filters

    def changed_after_selection(*args, **kwargs):
        selected = original_pool_filters(*args, **kwargs)
        pool.members(["m0002"], category_ids=[category])
        return selected

    monkeypatch.setattr(picker_module, "_pool_filters", changed_after_selection)
    with pytest.raises(ValueError, match="负样本池已更新"):
        picker_module._gt_material_filter_page(
            repository, annotations, limit=20, include_payload=False,
            filters={"negative_pool_only": True, "negative_category_ids": [category]},
        )


def test_role_page_rejects_stale_negative_pool_filter_snapshot(tmp_path, monkeypatch):
    from platform_core.negative_pool import NegativePool

    _client_instance, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    pool = NegativePool(repository)
    category = pool.category(name="行为风险")['id']
    pool.members(["m0000"], category_ids=[category])
    original_pool_filters = picker_module._pool_filters

    def changed_after_selection(*args, **kwargs):
        selected = original_pool_filters(*args, **kwargs)
        pool.members(["m0002"], category_ids=[category])
        return selected

    monkeypatch.setattr(picker_module, "_pool_filters", changed_after_selection)
    monkeypatch.setattr(picker_module, "_cached_role_index", lambda *args: (("m0000", "positive"),))
    with pytest.raises(ValueError, match="负样本池已更新"):
        picker_module._role_material_page(
            repository, annotations, {"effective_label_codes": ["smoke"]},
            include_payload=False,
            filters={"negative_pool_only": True, "negative_category_ids": [category]},
        )


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
    assert facts["positive_label_codes"] == ["smoke"]
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
    assert result["sample_role_counts"] == {"positive": 115, "confirmed_negative": 1, "pending_negative": 144, "pending_review": 0}
    assert len(result["items"]) == 2
    pending = _role_material_page(repository, annotations, {"effective_label_codes": ["smoke"]},
                                  labels=["person"], sample_role="pending_negative", limit=3)
    assert pending["total"] == 114
    assert len(pending["items"]) == 3
    assert all(row["sample_role"] == "pending_negative" for row in pending["items"])
    selected = _role_material_page(repository, annotations, {"effective_label_codes": ["smoke"]},
                                   image_ids=["m0000", "m0001", "m0259"], limit=1)
    assert selected["sample_role_counts"] == {"positive": 1, "confirmed_negative": 1, "pending_negative": 1, "pending_review": 0}


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
                                                       "sample_role": "pending_negative", "page_size": 2})
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
    assert initial["sample_role_counts"] == {"positive":500,"confirmed_negative":0,"pending_negative":3000,"pending_review":0}
    result = _role_material_page(repository, annotations,
                                 {"effective_label_codes": ["vest"]}, page=100, limit=50)
    assert result["total"] == 10000
    assert result["sample_role_counts"]["pending_negative"] == 9500
    assert len(result["items"]) == 50
    assert result["page"] == 100

def test_picker_shared_source_time_formal_state_filters(tmp_path):
    client, repository = _client(tmp_path)
    repository.upsert({**_record(259, annotated=False), 'storage_source_id':'remote-a'})
    params = {'storage_source_id':'remote-a', 'annotation_state':'unannotated', 'created_from':'2026-09-15', 'page':1}
    result = client.get('/api/v62/projects/p1/training-materials', params=params)
    assert result.status_code == 200
    assert result.json()['total'] == 1
    bulk = client.post('/api/v62/projects/p1/training-materials/bulk-selection', json={**params, 'storage_source_ids':['remote-a']})
    assert bulk.status_code == 200
    assert bulk.json()['items'] == ['m0259']

def test_role_index_cache_reuses_across_pages_and_invalidates_gt(tmp_path):
    from platform_core.training_material_picker_api import _role_material_page, _cached_role_index
    _client_unused, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    contract = {'effective_label_codes':['smoke']}
    _cached_role_index.cache_clear()
    first = _role_material_page(repository,annotations,contract,page=1,limit=20)
    second = _role_material_page(repository,annotations,contract,page=2,limit=20)
    assert _cached_role_index.cache_info().misses == 1
    assert _cached_role_index.cache_info().hits == 1
    assert set(r['id'] for r in first['items']).isdisjoint(r['id'] for r in second['items'])
    annotations.upsert('m0259', boxes=[], annotation_state='confirmed_empty',annotation_scope=['smoke'])
    _role_material_page(repository,annotations,contract,page=1,limit=20)
    assert _cached_role_index.cache_info().misses == 2


def test_picker_scoped_page_bulk_and_history_unknown(tmp_path):
    client, _ = _client(tmp_path)
    endpoint='/api/v62/projects/p1/training-materials'
    payload={'image_ids':['m0001','m0259'], 'usage_state':'unknown','page_size':1}
    page=client.post(endpoint+'/page',json=payload)
    assert page.status_code == 200
    assert page.json()['total']==2
    bulk=client.post(endpoint+'/bulk-selection',json={**payload,'all_available':True})
    assert bulk.status_code==200
    assert set(bulk.json()['items'])=={'m0001','m0259'}
    unknown=client.get(endpoint,params={'usage_state':'unused','page':1})
    assert unknown.status_code==200
    assert unknown.json()['total']==0, 'missing history coverage is not proof of unused'

def test_picker_default_history_policy_and_all_bulk_are_consistent(tmp_path):
    import sqlite3
    from platform_core.training_material_usage import TrainingMaterialUsage
    client, repository = _client(tmp_path)
    task_path=repository.project_path.parent.parent/'task_runtime'/'tasks.sqlite3'
    task_path.parent.mkdir(parents=True,exist_ok=True)
    sqlite3.connect(task_path).close()
    usage=TrainingMaterialUsage(task_path)
    usage.record_selected('p1','algo','used-task',{'snapshot_id':'s','images':[{'image_id':'m0001','role':'train'}]})
    usage.record_execution('used-task',completed_epoch=True)
    endpoint='/api/v62/projects/p1/training-materials'
    page=client.get(endpoint,params={'algorithm_asset_id':'algo','page':1})
    assert page.status_code==200
    assert page.json()['total']==259
    bulk=client.post(endpoint+'/bulk-selection',json={'algorithm_asset_id':'algo','all_available':True})
    assert bulk.status_code==200
    assert len(bulk.json()['items'])==259
    assert 'm0001' not in bulk.json()['items']
    included=client.get(endpoint,params={'algorithm_asset_id':'algo','usage_state':'used','history_policy':'include_history','page':1})
    assert included.status_code==200
    assert included.json()['total']==1
    history=client.post(endpoint+'/history',json={'algorithm_asset_id':'algo','image_id':'m0001'})
    assert history.status_code==200
    assert history.json()['items'][0]['task_id']=='used-task'
    assert history.json()['items'][0]['version_id'] is None

def test_picker_current_other_history_scopes_bulk_and_bounded_details(tmp_path):
    import sqlite3
    from platform_core.training_material_usage import TrainingMaterialUsage
    client, repo = _client(tmp_path)
    path=repo.project_path.parent.parent/'task_runtime'/'tasks.sqlite3'
    path.parent.mkdir(parents=True,exist_ok=True)
    sqlite3.connect(path).close()
    usage=TrainingMaterialUsage(path)
    for image_id,algorithm,task in [('m0001','a','ta'),('m0002','b','tb'),('m0003','a','tca'),('m0003','b','tcb')]:
        usage.record_selected('p1',algorithm,task,{'snapshot_id':task,'images':[{'image_id':image_id,'role':'train'}]})
        usage.record_execution(task,completed_epoch=True)
    endpoint='/api/v62/projects/p1/training-materials'
    for scope,expected in [('current_only',['m0001']),('other_only',['m0002'])]:
        body={'algorithm_asset_id':'a','history_policy':'include_history','history_scope':scope}
        page=client.get(endpoint,params={**body,'page':1})
        assert page.status_code==200,page.text
        assert [r['id'] for r in page.json()['items']]==expected
        bulk=client.post(endpoint+'/bulk-selection',json=body)
        assert bulk.status_code==200,bulk.text
        assert bulk.json()['items']==expected
        assert 'history_details' not in page.json()['items'][0]['training_usage']
    default=client.post(endpoint+'/bulk-selection',json={'algorithm_asset_id':'a','history_scope':'other_only'})
    assert default.json()['items']==['m0002'],'other usage is not automatically excluded'
    details=client.post(endpoint+'/history',json={'algorithm_asset_id':'a','image_id':'m0003','page_size':1})
    assert details.status_code==200,details.text
    assert details.json()['total']==2
    assert len(details.json()['items'])==1
    assert details.json()['summary']['training_task_count']==2
    assert details.json()['summary']['algorithm_ids']==['a','b']
    assert details.json()['summary']['last_completed_at'] is None

def test_picker_history_uses_original_version_identity_and_real_task_time(tmp_path):
    import sqlite3
    from platform_core.training_material_usage import TrainingMaterialUsage
    _unused, repository = _client(tmp_path)
    path=repository.project_path.parent.parent/'task_runtime'/'tasks.sqlite3'
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE tasks(task_id TEXT,project_id TEXT,kind TEXT,status TEXT,stage TEXT,created_at TEXT,finished_at TEXT)')
        db.execute("INSERT INTO tasks VALUES('job','p1','TRAINING','SUCCEEDED','done','2026-10-27T01:00:00Z','2026-10-27T02:00:00Z')")
    index=TrainingMaterialUsage(path)
    index.record_selected('p1','a','job',{'snapshot_id':'trusted','images':[{'image_id':'m0001','role':'train'}]})
    index.record_execution('job',completed_epoch=True)
    algorithm={'id':'a','name':'算法A','versions':[{'id':'v-real','training_job_id':'job','snapshot_id':'trusted'},
        {'id':'v-wrong','training_job_id':'job','snapshot_id':'wrong'}]}
    app=FastAPI()
    app.include_router(training_material_picker_router(lambda _: {'id':'p1'}, lambda:repository.project_path.parent.parent,
        algorithm_provider=lambda project_id,algorithm_id:algorithm if algorithm_id=='a' else None))
    result=TestClient(app).post('/api/v62/projects/p1/training-materials/history',json={'algorithm_asset_id':'a','image_id':'m0001'})
    assert result.status_code==200,result.text
    body=result.json()
    assert body['items'][0]['version_id']=='v-real'
    assert body['items'][0]['algorithm_name']=='算法A'
    assert body['summary']['last_completed_at']=='2026-10-27T02:00:00Z'
    assert body['summary']['training_task_count']==1


def test_picker_history_filters_original_and_derived_source_consistently(tmp_path):
    from platform_core.training_material_usage import TrainingMaterialUsage
    from platform_core.task_runtime.repository import TaskRepository
    client,repository=_client(tmp_path)
    task_path=repository.project_path.parent.parent/'task_runtime'/'tasks.sqlite3'
    TaskRepository(task_path)
    index=TrainingMaterialUsage(task_path)
    original=repository.get('m0000')
    index.record_selected('p1','a','past',{'snapshot_id':'s','images':[
        {'image_id':'m0000','role':'train','content_sha256':original['content_sha256']}]})
    index.record_execution('past',completed_epoch=True)
    repository.patch({'m0001':{'source_root_id':'m0000'}})
    page=client.get('/api/v62/projects/p1/training-materials',params={'algorithm_asset_id':'a','limit':120}).json()
    ids={row['id'] for row in page['items']}
    assert 'm0000' not in ids and 'm0001' not in ids
    bulk=client.post('/api/v62/projects/p1/training-materials/bulk-selection',json={'algorithm_asset_id':'a'}).json()
    assert 'm0000' not in bulk['items'] and 'm0001' not in bulk['items']
    assert page['total']==258 and len(bulk['items'])==258


def test_robustness_preview_reuses_thumbnail_without_modifying_source(tmp_path, monkeypatch):
    import base64
    from io import BytesIO
    client, repository = _client(tmp_path)
    source = tmp_path / "preview.png"
    Image.new("RGB", (40, 24), (180, 60, 25)).save(source)
    before = source.read_bytes()
    row = repository.get("m0001")
    monkeypatch.setattr("platform_core.training_material_picker_api.StorageManager.materialize", lambda *a: SimpleNamespace(path=source))
    for preset in ("bt601_limited", "bt601_full", "bt709_limited", "bt709_full"):
        response = client.get(f"/api/v62/projects/p1/training-materials/m0001/robustness-preview?preset={preset}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scope"] == "thumbnail_preview_only"
        assert body["pixel_changed"] is True
        with Image.open(BytesIO(base64.b64decode(body["after"].split(",")[1]))) as result:
            assert result.size == (40, 24)
    assert source.read_bytes() == before
    assert repository.get("m0001") == row
    assert client.get("/api/v62/projects/p1/training-materials/m0001/robustness-preview?preset=invalid").status_code == 422
