from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.training_material_picker_api import training_material_picker_router, _public_picker_material, _selection_summary
from platform_core.training_compatibility import TrainingCompatibilityResult
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


def test_picker_public_box_projection_is_bounded_without_changing_gt_count():
    boxes=[{'id':str(i),'label':f'label-{i%3}','x1':1,'y1':1,'x2':2,'y2':2} for i in range(1000)]
    formal={'annotation_state':'annotated','boxes':boxes}
    public=_public_picker_material('p1',_record(1),formal)
    assert public['box_count']==1000
    assert len(public['boxes'])==12
    assert public['boxes_truncated'] is True
    assert public['boxes_preview_only'] is True
    assert len(formal['boxes'])==1000


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


def test_compatibility_missing_label_filter_and_revision_bound_selection(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    project_path = data_dir / "projects" / "p1"
    repo = MaterialRepository(project_path)
    repo.upsert_many([_record(0), _record(1)])
    annotation_revision = AnnotationRepository(project_path).current_revision()
    truth = TrainingCompatibilityResult(
        label_contract={"effective_label_codes": ["fire", "smoke"]},
        issues=tuple({
            "image_id": image_id,
            "issue_type": "partial_review_scope",
            "missing_label_codes": codes,
        } for image_id, codes in (("m0000", ["fire"]), ("m0001", ["smoke"]))),
        material_revision=repo.current_revision(), annotation_revision=annotation_revision,
        selection_truth={"selected_count": 2},
    )
    monkeypatch.setattr(picker_module, "evaluate_training_compatibility_projection", lambda *_args, **_kwargs: truth)
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == "p1" else None,
        lambda: data_dir,
        algorithm_provider=lambda *_args: {"id": "algorithm-1"},
    ))
    client = TestClient(app)
    endpoint = "/api/v62/projects/p1/training-materials/compatibility"
    payload = {"algorithm_asset_id": "algorithm-1", "image_ids": ["m0000", "m0001"],
        "missing_label_code": "smoke", "page": 1, "page_size": 50}
    page = client.post(endpoint, json=payload)
    assert page.status_code == 200, page.text
    assert [row["image_id"] for row in page.json()["items"]] == ["m0001"]
    assert page.json()["filtered_affected_image_count"] == 1

    resolved = client.post(endpoint, json={
        **payload, "selection_action": "RESOLVE_SELECTION",
        "expected_material_revision": repo.current_revision(),
        "expected_annotation_revision": annotation_revision,
        "selection": {"all_filtered": True, "missing_label_code": "smoke"},
    })
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["matching_image_ids"] == ["m0001"]
    wrong = client.post(endpoint, json={
        **payload, "selection_action": "RESOLVE_SELECTION",
        "expected_material_revision": repo.current_revision(),
        "expected_annotation_revision": annotation_revision,
        "selection": {"image_ids": ["m0000"], "missing_label_code": "smoke"},
    })
    assert wrong.status_code == 409


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


def test_iteration_selection_summary_accepts_empty_preview_without_submission_validation(tmp_path, monkeypatch):
    client, _repo = _client(tmp_path)
    # The existing API still returns true pool totals to external callers.
    # Only the submission contract and role index are forbidden for preview.
    import platform_core.training_material_picker_api as picker_api
    monkeypatch.setattr(picker_api, "_role_material_page", lambda *_args, **_kwargs: pytest.fail("empty preview classified task roles"))
    # Exercise the real HTTP route. Router introspection is not portable to
    # CI's FastAPI/Starlette versions, which expose included route wrappers.
    response = client.post("/api/v62/projects/p1/training-materials/selection-summary", json={
        "algorithm_asset_id": "algorithm-a", "base_version_id": "version-v1",
        "image_ids": [], "train_labels": [],
    })
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["requested_count"] == 0
    assert summary["matched_count"] == 0
    assert summary["eligible_count"] == 0
    assert summary["positive_label_codes"] == []
    assert summary["selectable_total"] == 260
    assert summary["eligible_total"] == 230


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


def test_iteration_picker_first_page_does_not_build_all_candidate_role_index(tmp_path, monkeypatch):
    import platform_core.training_label_tasks as labels
    monkeypatch.setattr(labels, "resolve_training_label_contract", lambda *args, **kwargs: {
        "effective_label_codes": ["smoke", "person"]})
    _, repository = _client(tmp_path)
    monkeypatch.setattr(picker_module, "_cached_role_index",
        lambda *args, **kwargs: pytest.fail("first page scanned all candidate GT"))
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id}, repository.project_path.parents[1],
        algorithm_provider=lambda *args: {"id": "algorithm"}))
    with TestClient(app) as client:
        response = client.post("/api/v62/projects/p1/training-materials/role-page", json={
            "algorithm_asset_id": "algorithm", "history_policy": "include_history",
            "defer_role_counts": True, "page": 1, "page_size": 20,
            "sort_order": "newest",
        })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == 260
    assert len(result["items"]) == 20
    assert result["sample_role_counts"] is None
    assert result["role_counts_complete"] is False
    assert result["effective_label_codes"] == ["smoke", "person"]
    assert all(row["sample_role"] in {
        "positive", "confirmed_negative", "pending_negative", "pending_review"
    } for row in result["items"])


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
    monkeypatch.setattr(NegativePool, 'candidate_ids', lambda *a, **k: (_ for _ in ()).throw(AssertionError('page must not expand the entire pool')))
    pool.members(['m0000','m0001'],category_ids=[a],algorithm_id='a')
    pool.members(['m0002'],category_ids=[b],algorithm_id='a')
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
        pool.members(['m0001'],action='remove',algorithm_id='a')
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


def test_picker_deferred_count_serves_first_page_without_full_scan(tmp_path, monkeypatch):
    client, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)

    def forbidden_count(*_args, **_kwargs):
        raise AssertionError("deferred picker must not calculate the entire filtered pool")

    monkeypatch.setattr(picker_module, "_gt_filtered_count_snapshot", forbidden_count)
    first = picker_module._gt_material_filter_page(
        repository, annotations, limit=20, page=1, count_mode="deferred",
    )
    assert len(first["items"]) == 20
    assert first["total"] is None
    assert first["has_next"] is True

    endpoint = "/api/v62/projects/p1/training-materials"
    public_first = client.get(endpoint, params={"page": 1, "page_size": 20, "count_mode": "deferred"})
    assert public_first.status_code == 200
    assert public_first.json()["total"] is None
    assert public_first.json()["has_next"] is True
    public_last = client.get(endpoint, params={"page": 14, "page_size": 20, "count_mode": "deferred"})
    assert public_last.status_code == 200
    assert public_last.json()["items"] == []
    assert public_last.json()["has_next"] is False


def test_selected_summary_preview_does_not_scan_unselected_pool(tmp_path, monkeypatch):
    client, _repository = _client(tmp_path)

    def forbidden_totals(*_args, **_kwargs):
        raise AssertionError("selected-only label preview must not scan entire project")

    monkeypatch.setattr(picker_module, "_cached_pool_training_totals", forbidden_totals)
    result = client.post(
        "/api/v62/projects/p1/training-materials/selection-summary",
        json={"image_ids": ["m0000", "m0001"], "summary_only": True},
    )
    assert result.status_code == 200
    assert result.json()["positive_label_codes"] == ["person", "smoke"]
    assert result.json()["selectable_total"] is None
    assert result.json()["eligible_total"] is None


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
    assert "negative_pool_revision" in filtered_body
    assert "negative_confirmation_revision" in filtered_body

    all_available = client.post(
        "/api/v62/projects/p1/training-materials/bulk-selection",
        json={"query": "ignored", "labels": ["person"], "all_available": True},
    )
    assert all_available.status_code == 200
    all_body = all_available.json()
    assert all_body["selection_mode"] == "all_available"
    assert all_body["total"] == 260
    assert len(all_body["items"]) == 260
    assert "negative_pool_revision" in all_body
    assert "negative_confirmation_revision" in all_body

    test_only = client.post(
        "/api/v62/projects/p1/training-materials/bulk-selection",
        json={"query": "", "labels": [], "all_available": True, "role": "test"},
    )
    assert test_only.status_code == 200
    assert test_only.json()["total"] == 230
    assert len(test_only.json()["items"]) == 230


def test_training_picker_large_selection_opt_in_uses_existing_frozen_reference(tmp_path, monkeypatch):
    _, repository = _client(tmp_path)
    limits = []

    def sentinel_page(*_args, **kwargs):
        limits.append(kwargs['limit'])
        return {'items':['m0000'], 'has_next':True}

    monkeypatch.setattr(picker_module, '_gt_material_filter_page', sentinel_page)
    router = training_material_picker_router(
        lambda project_id: {'id':project_id}, lambda:tmp_path/'data')
    endpoint = next(route.endpoint for route in router.routes
                    if route.path.endswith('/training-materials/bulk-selection'))
    with pytest.raises(HTTPException) as raised:
        endpoint('p1', {'algorithm_asset_id':'a', 'role':'train',
                        'prefer_reference_over':2000})
    assert raised.value.status_code == 422
    assert '超过单次选择上限 2000 张' in raised.value.detail
    assert limits == [2000]
    # Other callers, including independent Test, keep the original 50k limit.
    with pytest.raises(HTTPException):
        endpoint('p1', {'role':'test', 'prefer_reference_over':2000})
    assert limits[-1] == picker_module.MAX_SELECTION_SUMMARY_IDS


def test_bulk_filtered_ids_avoids_duplicate_exact_gt_count(tmp_path, monkeypatch):
    client, repository = _client(tmp_path)
    original = picker_module._gt_material_filter_page
    count_modes = []

    def record_page(*args, **kwargs):
        count_modes.append(kwargs.get('count_mode'))
        return original(*args, **kwargs)

    monkeypatch.setattr(picker_module, '_gt_material_filter_page', record_page)
    annotations = AnnotationRepository(repository.project_path)
    ids, total = picker_module._bulk_filtered_ids(
        repository, annotations, labels=('smoke',), filters={'label_mode': 'any'})
    assert total == len(ids) == 115
    assert count_modes == ['deferred']


def test_bulk_filtered_ids_still_rejects_results_over_original_cap(tmp_path, monkeypatch):
    _, repository = _client(tmp_path)
    monkeypatch.setattr(picker_module, '_gt_material_filter_page',
                        lambda *_args, **_kwargs: {'items': ['m0000'], 'has_next': True})
    with pytest.raises(ValueError, match='超过单次选择上限'):
        picker_module._bulk_filtered_ids(repository, AnnotationRepository(repository.project_path),
                                         filters={'label_mode': 'any'})


@pytest.mark.parametrize("source", ["pool", "confirmation"])
def test_training_picker_bulk_refuses_changed_negative_evidence(tmp_path, monkeypatch, source):
    _, repository = _client(tmp_path)
    # Exercise the unchanged real router endpoint without a TestClient portal;
    # this environment's Starlette TestClient cannot finish an HTTP exchange.
    router = training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == "p1" else None,
        lambda: tmp_path / "data",
    )
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/training-materials/bulk-selection"))
    if source == "pool":
        owner = picker_module.NegativePool
        name = "revision"
    else:
        owner = AnnotationRepository
        name = "task_negative_confirmation_revision"
    original = getattr(owner, name)
    reads = 0

    def changed_after_snapshot(self):
        nonlocal reads
        reads += 1
        revision = original(self)
        return revision if reads == 1 else f"{revision}-changed"

    monkeypatch.setattr(owner, name, changed_after_snapshot)
    with pytest.raises(HTTPException) as raised:
        endpoint("p1", {"algorithm_asset_id": "algo", "all_available": True})
    assert raised.value.status_code == 422
    assert "负样本池或确认记录已更新" in raised.value.detail


def test_training_picker_thumbnail_is_lazy_cached(tmp_path, monkeypatch):
    client, repository = _client(tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (900, 600), "white").save(source)
    calls = {"count": 0}

    def materialize(_self, _value, *, read_only=False):
        assert read_only is True
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


def test_training_picker_thumbnail_legacy_missing_digest_does_not_mutate_material(tmp_path, monkeypatch):
    """A thumbnail GET must not repair canonical Material metadata as a side effect."""
    import hashlib

    data_dir = tmp_path / "data"
    project_dir = data_dir / "projects" / "p1"
    source = project_dir / "uploads" / "legacy.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (400, 250), "white").save(source)
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    repository = MaterialRepository(project_dir)
    repository.upsert({
        "id": "legacy-no-digest", "filename": "legacy.png",
        "storage_source_id": "default_local", "storage_type": "local",
        "object_key": "uploads/legacy.png", "content_sha256": "",
        "size_bytes": 0, "processing_status": "processed",
    })
    original_record = repository.get("legacy-no-digest")
    original_revision = repository.current_revision()
    materialize_calls = []
    original_materialize = picker_module.StorageManager.materialize

    def tracked_materialize(manager, value, *, read_only=False):
        materialize_calls.append(read_only)
        return original_materialize(manager, value, read_only=read_only)

    monkeypatch.setattr(picker_module.StorageManager, "materialize", tracked_materialize)
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == "p1" else None,
        lambda: data_dir,
    ))

    with TestClient(app) as client:
        endpoint = "/api/v62/projects/p1/training-materials/legacy-no-digest/thumbnail?size=192"
        first = client.get(endpoint)
        second = client.get(endpoint)
        assert first.status_code == second.status_code == 200
        assert first.content == second.content
    thumbnails = list((data_dir / "cache" / "training-thumbnails").rglob("*.jpg"))
    assert len(thumbnails) == 1, "unchanged source identity should reuse one thumbnail"
    assert materialize_calls == [True], "warm GET must reuse the first immutable thumbnail"
    assert repository.current_revision() == original_revision
    assert repository.get("legacy-no-digest") == original_record
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_sha


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
    # Unannotated candidates require explicit task confirmation; they do not
    # automatically become formal GT or confirmed negatives.
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
        assert kwargs == {"require_positive_evidence": False, "include_base_weight_digest": False}
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
    assert "negative_pool_revision" in bulk.json()
    assert "negative_confirmation_revision" in bulk.json()


def test_partial_positive_scope_review_uses_per_image_truth_and_fails_closed(tmp_path, monkeypatch):
    import platform_core.training_label_tasks as labels
    monkeypatch.setattr(labels, "resolve_training_label_contract", lambda *_args, **_kwargs: {
        "effective_label_codes": ["person", "smoke"]})
    _, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    for image_id, scope in (("m0000", ["smoke"]), ("m0001", ["person"]), ("m0002", ["smoke"])):
        original = annotations.get(image_id)
        annotations.upsert(image_id, original["boxes"], "annotated", annotation_scope=scope)
    repository.patch({"m0002": {"source_available": False}})
    calls = []
    def review(project, item, codes, actor):
        calls.append((project, item["image_id"], codes, actor["actor_id"]))
    app = FastAPI()
    app.include_router(training_material_picker_router(lambda project: {"id": project},
        repository.project_path.parents[1], algorithm_provider=lambda *_: {"id": "a"},
        review_negative_provider=review,
        actor_provider=lambda request, project: {"actor_id": "trusted-reviewer"}))
    client = TestClient(app)
    endpoint = "/api/v62/projects/p1/training-materials/review-scopes"
    revision = {"expected_material_revision": repository.current_revision(),
                "expected_annotation_revision": annotations.current_revision()}
    def item(image_id, codes):
        material = repository.get(image_id)
        annotation = annotations.get(image_id)
        return {"image_id": image_id, "reviewed_label_codes": codes,
                "expected_version": annotation["version"],
                "source_content_sha256": material["content_sha256"]}
    payload = {"algorithm_asset_id": "a", "train_labels": ["person", "smoke"],
               **revision, "items": [item("m0000", ["person"]), item("m0001", ["smoke"])]}
    assert client.post(endpoint, json=payload).status_code == 422
    assert client.post(endpoint, json={**payload, "confirmed": True,
        "expected_annotation_revision": revision["expected_annotation_revision"] + 1}).status_code == 409
    result = client.post(endpoint, json={**payload, "confirmed": True,
        "items": [*payload["items"], item("m0002", ["person"]),
                  item("m0001", ["person"])]})
    assert result.status_code == 422  # Repeated image IDs cannot bypass per-image audit.
    result = client.post(endpoint, json={**payload, "confirmed": True,
        "items": [*payload["items"], item("m0002", ["person"]),
                  item("m0259", ["person"])]})
    assert result.status_code == 200, result.text
    assert result.json()["succeeded"] == ["m0000", "m0001"]
    assert {row["image_id"] for row in result.json()["failures"]} == {"m0002", "m0259"}
    assert calls == [("p1", "m0000", ["person"], "trusted-reviewer"),
                     ("p1", "m0001", ["smoke"], "trusted-reviewer")]
    wrong = client.post(endpoint, json={**payload, "confirmed": True,
        "items": [item("m0001", ["person"])]})
    assert wrong.json()["succeeded"] == []
    assert wrong.json()["failures"]


def _scope_plan_fixture(tmp_path, monkeypatch, *, count=64, blocked=False, crash_after_save=False):
    import platform_core.training_label_tasks as labels
    monkeypatch.setattr(labels, "resolve_training_label_contract", lambda *_args, **_kwargs: {
        "effective_label_codes": ["person", "head"]})
    data_dir = tmp_path / "data"
    repository = MaterialRepository(data_dir / "projects" / "p1")
    ids = [f"m{i:04d}" for i in range(count)]
    repository.upsert_many([_record(i) for i in range(count)])
    annotations = AnnotationRepository(repository.project_path)
    annotations.upsert_many([{"image_id":image_id, "annotation_state":"annotated",
        "annotation_scope":["person"], "boxes":[{"label":"person", "x1":10,"y1":10,"x2":80,"y2":90}]}
        for image_id in ids])
    issues = tuple({"image_id":image_id,
        "issue_type":"stale_ground_truth" if blocked and index==count-1 else "partial_review_scope",
        "missing_label_codes":["head"]} for index,image_id in enumerate(ids))
    truth = TrainingCompatibilityResult({"effective_label_codes":["person","head"]},
        issues, repository.current_revision(), annotations.current_revision(), {"selected_train_count":count})
    monkeypatch.setattr(picker_module, "evaluate_training_compatibility_projection", lambda *_a, **_kw: truth)
    calls = []
    def review(_project, item, codes, actor):
        calls.append(item["image_id"])
        image_id = item["image_id"]
        original = annotations.get(image_id)
        annotations.upsert(image_id, original["boxes"], annotation_state="annotated",
            annotation_scope=sorted(set(original["annotation_scope"])|set(codes)),
            expected_version=item["expected_version"],
            source_content_sha256=item["source_content_sha256"],
            reviewed_label_codes=codes,
            review_evidence={"actor_id":actor["actor_id"],"reviewed_label_codes":codes,
                "source_content_sha256":item["source_content_sha256"]})
        if crash_after_save and len(calls)==1:
            raise RuntimeError("simulated worker crash after formal GT commit")
    actor = {"id":"reviewer-one"}
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id":project_id} if project_id == "p1" else None,
        lambda: data_dir, algorithm_provider=lambda *_: {"id":"algorithm"},
        review_negative_provider=review,
        actor_provider=lambda _request, _project: {"actor_id":actor["id"]}))
    return TestClient(app), repository, annotations, ids, calls, actor


def _scope_plan_request(repository, annotations, ids, selection):
    return {"algorithm_asset_id":"algorithm", "train_labels":["person","head"],
        "train_image_ids":ids, "expected_material_revision":repository.current_revision(),
        "expected_annotation_revision":annotations.current_revision(), "selection":selection}


def test_cross_page_formal_scope_plan_is_bounded_durable_and_preserves_boxes(tmp_path, monkeypatch):
    client, repository, annotations, ids, calls, actor = _scope_plan_fixture(
        tmp_path, monkeypatch, count=64, blocked=True)
    path = "/api/v62/projects/p1/training-materials/review-scope-plans"
    payload = _scope_plan_request(repository, annotations, ids,
        {"all_filtered":True, "excluded_image_ids":["m0001"]})
    planned = client.post(path, json=payload)
    assert planned.status_code == 200, planned.text
    plan = planned.json()
    assert (plan["selected_count"],plan["pending"],plan["blocked"]) == (63,62,1)
    assert plan["problems"][0]["image_id"] == "m0063"
    task = plan["task_id"]
    assert client.post(f"{path}/{task}/execute",json={"max_items":20}).status_code == 422
    assert client.post(f"{path}/{task}/execute",json={"confirmed":True,"max_items":51}).status_code == 422
    results = []
    while True:
        result = client.post(f"{path}/{task}/execute",json={"confirmed":True,"max_items":20})
        assert result.status_code == 200, result.text
        results.append(result.json()["step_processed"])
        if result.json()["done"]:
            break
    assert results == [20,20,20,2]
    assert len(calls) == 62 and len(set(calls)) == 62
    assert client.get(f"{path}/{task}").json()["succeeded"] == 62
    assert client.post(f"{path}/{task}/execute",json={"confirmed":True}).json()["step_processed"] == 0
    problems = client.get(f"{path}/{task}/results",params={"state":"problems","limit":20})
    assert problems.status_code == 200 and problems.json()["total"] == 1
    assert problems.json()["items"][0]["image_id"] == "m0063"
    all_results = client.get(f"{path}/{task}/results",params={"state":"all","limit":20}).json()
    assert all_results["total"] == 63 and all_results["next_cursor"] == "20"
    assert len(client.get(f"{path}/{task}/results",params={"state":"all","cursor":60,"limit":20}).json()["items"]) == 3
    assert client.get(f"{path}/{task}/results",params={"state":"unexpected"}).status_code == 422
    assert repository.current_revision() > payload["expected_material_revision"]
    original = annotations.get("m0000")
    assert len(original["boxes"]) == 1 and original["boxes"][0]["label"] == "person"
    assert set(original["annotation_scope"]) == {"person","head"}
    evidence = annotations.negative_review_evidence("m0000", 1, actor["id"], ["head"],
        repository.get("m0000")["content_sha256"])
    assert evidence and evidence["annotation_version"] == original["version"]
    assert "head" not in annotations.get("m0063")["annotation_scope"]
    assert "head" not in annotations.get("m0001")["annotation_scope"]


def test_scope_plan_fails_closed_on_stale_snapshot_wrong_owner_and_changed_gt(tmp_path, monkeypatch):
    client, repository, annotations, ids, calls, actor = _scope_plan_fixture(tmp_path, monkeypatch, count=3)
    path = "/api/v62/projects/p1/training-materials/review-scope-plans"
    payload = _scope_plan_request(repository, annotations, ids, {"image_ids":[ids[0],ids[1]]})
    wrong = client.post(path, json={**payload,"expected_annotation_revision":12345})
    assert wrong.status_code == 409
    wrong = client.post(path, json={**payload,"selection":{"image_ids":["non-member"]}})
    assert wrong.status_code == 409
    assert client.post(path, json={**payload,"selection":[]}).status_code == 422
    plan = client.post(path,json=payload).json()
    actor["id"] = "different-reviewer"
    assert client.get(f"{path}/{plan['task_id']}").status_code == 404
    assert client.get(f"{path}/{plan['task_id']}/results").status_code == 404
    assert client.post(f"{path}/{plan['task_id']}/execute",json={"confirmed":True}).status_code == 404
    actor["id"] = "reviewer-one"
    # Another user changes GT after planning: no old-version absence assertion.
    annotations.upsert(ids[0],annotations.get(ids[0])["boxes"],"annotated",annotation_scope=["person","helmet"])
    response = client.post(f"{path}/{plan['task_id']}/execute",json={"confirmed":True,"max_items":2})
    assert response.status_code == 200, response.text
    assert response.json()["failed"] == 1 and response.json()["succeeded"] == 1
    assert response.json()["done"]
    assert calls == [ids[1]]
    assert "head" not in annotations.get(ids[0])["annotation_scope"]


def test_scope_plan_reconciles_crash_after_gt_commit_without_second_review(tmp_path, monkeypatch):
    client, repository, annotations, ids, calls, _actor = _scope_plan_fixture(
        tmp_path, monkeypatch, count=1, crash_after_save=True)
    path = "/api/v62/projects/p1/training-materials/review-scope-plans"
    plan = client.post(path,json=_scope_plan_request(repository,annotations,ids,{"all_filtered":True})).json()
    task = plan['task_id']
    with pytest.raises(RuntimeError,match="simulated worker crash"):
        client.post(f"{path}/{task}/execute",json={"confirmed":True})
    assert client.get(f"{path}/{task}").json()["pending"] == 1
    recovered = client.post(f"{path}/{task}/execute",json={"confirmed":True})
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["succeeded"] == 1 and recovered.json()["done"]
    assert calls == ids


def test_scope_plan_rechecks_each_material_source_after_other_gt_writes(tmp_path, monkeypatch):
    client, repository, annotations, ids, calls, _actor = _scope_plan_fixture(tmp_path, monkeypatch, count=3)
    path = "/api/v62/projects/p1/training-materials/review-scope-plans"
    plan = client.post(path,json=_scope_plan_request(repository,annotations,ids,{"all_filtered":True})).json()
    first = client.post(f"{path}/{plan['task_id']}/execute",json={"confirmed":True,"max_items":1})
    assert first.status_code == 200 and first.json()["succeeded"] == 1
    # Both formal annotation projection and an unrelated material edit bump
    # the global material revision. They must not invalidate a distinct image
    # whose frozen SHA and GT CAS still match; a lost source must fail closed.
    repository.patch({ids[1]:{"source_available":False}})
    rest = client.post(f"{path}/{plan['task_id']}/execute",json={"confirmed":True,"max_items":2})
    assert rest.status_code == 200, rest.text
    assert (rest.json()["succeeded"],rest.json()["failed"]) == (2,1)
    assert calls == [ids[0],ids[2]]


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
    assert result["sample_role_counts"]["pending_review"] == 0
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
    assert page.json()['total']==260
    assert next(r for r in page.json()['items'] if r['id']=='m0001')['training_usage']['excluded'] is True
    bulk=client.post(endpoint+'/bulk-selection',json={'algorithm_asset_id':'algo','all_available':True})
    assert bulk.status_code==200
    assert len(bulk.json()['items'])==259
    assert 'm0001' not in bulk.json()['items']
    forged=client.post(endpoint+'/bulk-selection',json={'algorithm_asset_id':'algo','browse_only':True})
    assert forged.status_code==200 and 'm0001' not in forged.json()['items']
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
    for scope,expected in [('current_only',['m0001','m0003']),('other_only',['m0002'])]:
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
    assert {'m0000','m0001'} <= ids
    assert all(r['training_usage']['excluded'] for r in page['items'] if r['id'] in {'m0000','m0001'})
    bulk=client.post('/api/v62/projects/p1/training-materials/bulk-selection',json={'algorithm_asset_id':'a'}).json()
    assert 'm0000' not in bulk['items'] and 'm0001' not in bulk['items']
    assert page['total']==260 and len(bulk['items'])==258


def test_picker_fast_sql_excludes_pending_and_permanent_test_even_with_history_reuse(tmp_path):
    import json
    import sqlite3
    from platform_core.training_material_usage import TrainingMaterialUsage
    from platform_core.training_material_picker_api import _picker_filter_sql, _attach_usage_exclusion

    path = tmp_path / 'tasks.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE tasks(task_id TEXT PRIMARY KEY,status TEXT)')
        db.execute("INSERT INTO tasks VALUES('test-owner','RUNNING')")
    index = TrainingMaterialUsage(path)
    index.record_selected('p', 'a', 'test-owner', {'snapshot_id': 's', 'images': [
        {'image_id': 'benchmark', 'role': 'test', 'content_sha256': 'a' * 64},
    ]}, enforce_isolation=True)

    def eligible_count():
        filters = {'__usage_sql_exclusion': {'path': str(path), 'project_id': 'p',
            'algorithm_id': 'a', 'role': 'train', 'revision': index.read_revision(),
            'include_train_history': False, 'has_task_statuses': True}}
        clauses, params = _picker_filter_sql(filters)
        with sqlite3.connect(':memory:', uri=True) as db:
            db.execute('CREATE TABLE materials(id TEXT,content_sha256 TEXT,payload_json TEXT)')
            db.execute('INSERT INTO materials VALUES(?,?,?)', ('new-upload', 'a' * 64, json.dumps({})))
            _attach_usage_exclusion(db, filters)
            return db.execute('SELECT COUNT(*) FROM materials m WHERE ' + ' AND '.join(clauses), params).fetchone()[0]

    assert eligible_count() == 0
    with sqlite3.connect(path) as db:
        db.execute("UPDATE tasks SET status='FAILED' WHERE task_id='test-owner'")
    assert eligible_count() == 1
    index.record_execution('test-owner', test_observed=True)
    assert eligible_count() == 0


def test_robustness_preview_reuses_thumbnail_without_modifying_source(tmp_path, monkeypatch):
    import base64
    from io import BytesIO
    client, repository = _client(tmp_path)
    source = tmp_path / "preview.png"
    Image.new("RGB", (40, 24), (180, 60, 25)).save(source)
    before = source.read_bytes()
    row = repository.get("m0001")
    def preview_materialize(*_args, read_only=False):
        assert read_only is True
        return SimpleNamespace(path=source)
    monkeypatch.setattr("platform_core.training_material_picker_api.StorageManager.materialize", preview_materialize)
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


def test_thumbnail_failure_is_retryable_without_original_redirect(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    def unavailable(*args, **kwargs):
        raise OSError('isolated unavailable source')
    monkeypatch.setattr(picker_module.StorageManager,'materialize',unavailable)
    response=client.get('/api/v62/projects/p1/training-materials/m0001/thumbnail',follow_redirects=False)
    assert response.status_code==503
    assert 'location' not in response.headers
    assert response.json()['detail']['code']=='THUMBNAIL_UNAVAILABLE'


def test_large_filter_freezes_reference_without_returning_all_ids(tmp_path):
    from platform_core.training_selection_reference import selection_context,read_selection,validate_payload_references
    client,repository=_client(tmp_path)
    repository.upsert_many([{'id':f'large{i:06d}','filename':f'large{i:06d}.jpg',
        'object_key':f'{i}.jpg','processing_status':'processed','content_sha256':f'{i+1000:064x}'} for i in range(50001)])
    payload={'algorithm_asset_id':'a','role':'train','history_policy':'include_history',
        'query':'large','train_labels':['smoke'],'framework':'ultralytics','base_version_id':''}
    endpoint='/api/v62/projects/p1/training-materials'
    receipt=client.post(endpoint+'/selection-reference',json=payload)
    assert receipt.status_code==200,receipt.text
    assert receipt.json()['count']==50001
    assert len(receipt.content)<500 and 'items' not in receipt.json()
    reference=receipt.json()['selection_ref']
    data=repository.project_path.parent.parent
    ids=read_selection(data,reference,selection_context(data,'p1',payload))
    assert len(ids)==50001
    validate_payload_references(data,'p1',{**payload,'train_selection_ref':reference,'train_image_ids':ids})
    subset=client.post(endpoint+'/selection-membership',json={**payload,'selection_ref':reference,'image_ids':ids[:60]})
    assert subset.status_code==200 and len(subset.json()['items'])==60
    forged=client.post(endpoint+'/selection-membership',json={**payload,'algorithm_asset_id':'other','selection_ref':reference,'image_ids':ids[:1]})
    assert forged.status_code==422
    repository.patch({ids[0]:{'filename':'changed.jpg'}})
    with pytest.raises(ValueError):validate_payload_references(data,'p1',{**payload,'train_selection_ref':reference,'train_image_ids':ids})


def test_role_frozen_selection_uses_forward_cursor_and_preserves_role(tmp_path, monkeypatch):
    import platform_core.training_label_tasks as label_tasks
    from platform_core.training_selection_reference import read_selection, selection_context

    _, repository = _client(tmp_path)
    monkeypatch.setattr(label_tasks, 'resolve_training_label_contract',
                        lambda *_args, **_kwargs: {'effective_label_codes': ['smoke']})
    cursors = []
    revision_fields = {'repository_revision': repository.current_revision(),
                       'annotation_revision': AnnotationRepository(repository.project_path).current_revision()}

    def bounded_role_page(_repository, _annotations, _contract, *, cursor=None,
                          sample_role='', filters=None, **_kwargs):
        assert sample_role == ''  # classify each forward page; never rescan the role index
        assert filters['__role_target'] == {'labels': ['smoke'], 'negative': False}
        cursors.append(cursor)
        if not cursor:
            return {'items': [{'id': 'm0000', 'sample_role': 'positive'},
                              {'id': 'm0001', 'sample_role': 'pending_negative'}],
                    'next_cursor': 'next-page', **revision_fields}
        assert cursor == 'next-page'
        return {'items': [{'id': 'm0002', 'sample_role': 'positive'}], 'next_cursor': None,
                **revision_fields}

    monkeypatch.setattr(picker_module, '_role_material_page', bounded_role_page)
    router = training_material_picker_router(
        lambda project_id: {'id': project_id}, lambda: tmp_path / 'data',
        algorithm_provider=lambda _project, algorithm_id: {'id': algorithm_id},
    )
    endpoint = next(route.endpoint for route in router.routes
                    if route.path.endswith('/training-materials/selection-reference'))
    payload = {'algorithm_asset_id': 'a', 'role': 'train', 'history_policy': 'include_history',
               'train_labels': ['smoke'], 'framework': 'ultralytics', 'sample_role': 'positive'}
    receipt = endpoint('p1', payload)
    assert receipt['count'] == 2
    assert cursors == ['', 'next-page']
    ids = read_selection(tmp_path / 'data', receipt['selection_ref'],
                         selection_context(tmp_path / 'data', 'p1', payload))
    assert ids == ['m0000', 'm0002']


def test_forward_role_paging_matches_existing_exact_role_scope(tmp_path):
    from platform_core.training_material_picker_api import _role_material_page, _iter_forward_role_ids

    _, repository = _client(tmp_path)
    annotations = AnnotationRepository(repository.project_path)
    contract = {'effective_label_codes': ['smoke']}
    expected = _role_material_page(repository, annotations, contract,
                                   sample_role='positive', limit=500, include_payload=False)
    cursor = ''
    selected = []
    for _ in range(20):
        chunk = _role_material_page(repository, annotations, contract, cursor=cursor,
                                    limit=23, sort_order='oldest',
                                    filters={'__role_target': {'labels': ['smoke'], 'negative': False}},
                                    defer_role_counts=True, count_mode='deferred')
        selected.extend(row['id'] for row in chunk['items'] if row['sample_role'] == 'positive')
        cursor = chunk['next_cursor']
        if not cursor:
            break
    else:
        pytest.fail('cursor traversal did not finish')
    assert selected == [row['id'] for row in expected['items']]

    # Verify the shared forward iterator against the original exact-role
    # index for every role and both orders, including zero-match roles.
    for order in ('oldest', 'newest'):
        for role in ('positive', 'confirmed_negative', 'pending_negative', 'pending_review'):
            original = _role_material_page(repository, annotations, contract,
                                           sample_role=role, limit=260,
                                           sort_order=order, include_payload=False)
            forward = list(_iter_forward_role_ids(repository, annotations, contract,
                sample_role=role, sort_order=order, page_size=23))
            assert forward == [row['id'] for row in original['items']], (order, role)


def test_bulk_role_selection_no_longer_builds_full_role_index(tmp_path, monkeypatch):
    import platform_core.training_label_tasks as label_tasks

    _, repository = _client(tmp_path)
    monkeypatch.setattr(label_tasks, 'resolve_training_label_contract',
                        lambda *_args, **_kwargs: {'effective_label_codes': ['smoke']})
    monkeypatch.setattr(picker_module, '_cached_role_index',
                        lambda *_args, **_kwargs: pytest.fail('bulk role selection built a full role index'))
    router = training_material_picker_router(
        lambda project_id: {'id': project_id}, lambda: tmp_path / 'data',
        algorithm_provider=lambda _project, algorithm_id: {'id': algorithm_id},
    )
    endpoint = next(route.endpoint for route in router.routes
                    if route.path.endswith('/training-materials/bulk-selection'))
    body = endpoint('p1', {'algorithm_asset_id': 'a', 'role': 'train',
                           'history_policy': 'include_history', 'train_labels': ['smoke'],
                           'sample_role': 'positive'})
    assert body['total'] == len(body['items']) == 115
    assert body['items'] == [f'm{index:04d}' for index in range(0, 230, 2)]
