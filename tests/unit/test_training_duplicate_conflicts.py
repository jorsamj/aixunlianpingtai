from __future__ import annotations

import copy
import json

import pytest

import platform_core.training_splits as splits
from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.training_compatibility import compatibility_page, evaluate_training_compatibility
from platform_core.training_tasks import freeze_training_inputs, resolve_training_selection


def row(image_id, *, sha="a" * 64, state="annotated", scope=("fire",), label="fire", x=1):
    return {"id": image_id, "filename": f"{image_id}.jpg", "content_sha256": sha,
            "size_bytes": 10, "width": 100, "height": 100, "source_available": True,
            "processing_status": "processed", "annotation_state": state,
            "annotation_scope": list(scope), "boxes": ([{"label": label, "x1": x,
            "y1": 1, "x2": 20, "y2": 20}] if state == "annotated" else [])}


def seed(tmp_path, rows):
    project = tmp_path / "projects" / "p"
    materials = MaterialRepository(project)
    materials.upsert_many(rows)
    annotations = [
        {"image_id": value["id"], "annotation_state": value["annotation_state"],
         "annotation_scope": value["annotation_scope"], "boxes": value["boxes"]}
        for value in rows
    ]
    for offset in range(0, len(annotations), 500):
        AnnotationRepository(project).upsert_many(annotations[offset:offset + 500])
    (project / "meta.json").write_text(json.dumps({"labels": ["fire", "smoke"],
        "label_meta": [{"code": "fire", "class_id": 0}, {"code": "smoke", "class_id": 1}]}), encoding="utf-8")
    return project


def request(ids, **extra):
    return {"train_image_ids": list(ids), "train_labels": ["fire"],
            "split_mode": "random_test_from_training_pool", "experiment_percent": 20,
            "validation_percent": 20, **extra}


@pytest.mark.parametrize("change,kind", [
    ({"annotation_state": "confirmed_empty", "boxes": []}, "annotation_state"),
    ({"annotation_scope": ["fire", "smoke"]}, "annotation_scope"),
    ({"boxes": row("z", label="smoke")["boxes"]}, "labels"),
    ({"boxes": row("z", x=3)["boxes"]}, "coordinates"),
    ({"boxes": row("z")["boxes"] * 2}, "box_count"),
])
def test_original_gt_analyzer_reports_specific_conflict_without_mutation(change, kind):
    rows = [row("a"), {**row("b"), **change}]
    original = copy.deepcopy(rows)
    groups = splits.analyze_training_duplicates(rows, ("a", "b"))
    assert len(groups) == 1
    assert groups[0]["issue_type"] == "duplicate_annotation_conflict"
    assert kind in groups[0]["conflict_types"]
    assert rows == original


def test_cross_role_sha_leakage_precedes_different_gt():
    rows = [row("a"), row("b", x=3), row("c", sha="b" * 64)]
    req = splits.SplitRequest(splits.SplitMode.INDEPENDENT_TEST_SET, ("a", "c"), ("b",))
    with pytest.raises(ValueError, match="content hash leakage"):
        splits.build_split_manifest(rows, req, seed=0)


def test_compatibility_reports_real_original_gt_duplicates(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="b" * 64)])
    result = evaluate_training_compatibility(tmp_path, project, request(("a", "b", "c")), {"id": "alg"})
    assert result.summary()["compatible"] is False
    assert result.summary()["affected_image_count"] == 2
    assert result.summary()["duplicate_conflict_image_count"] == 2
    assert result.summary()["duplicate_conflict_group_count"] == 1
    issues = compatibility_page(result)["items"]
    assert {value["image_id"] for value in issues} == {"a", "b"}
    assert all(value["issue_type"] == "duplicate_annotation_conflict" for value in issues)
    assert all(len(value["annotation_digest"]) == 64 for value in issues)
    assert all(value["role"] == "train" and value["box_count"] == 1 for value in issues)
    assert all(value["labels"] == ["fire"] for value in issues)


def test_freeze_rejects_original_conflict_even_when_projection_hides_it(tmp_path):
    project = seed(tmp_path, [row("a", scope=("fire", "smoke")), row("b", scope=("fire", "smoke"), label="smoke")])
    req = splits.SplitRequest(splits.SplitMode.RANDOM_TEST_FROM_TRAINING_POOL, ("a", "b"), experiment_percent=20)
    selected = resolve_training_selection(project, req)
    projected = [{**value, "boxes": row("x")["boxes"], "annotation_scope": ["fire"]}
                 for value in selected.effective_images]
    with pytest.raises(ValueError, match="duplicate_annotation_conflict"):
        freeze_training_inputs(project, req, seed=0, selection_resolution=selected,
            effective_images=projected, label_schema_override=[{"code": "fire", "class_id": 0}])


@pytest.mark.parametrize("size", [100, 1000, 10000])
def test_duplicate_pages_and_summary_are_bounded(size):
    from platform_core.training_compatibility import TrainingCompatibilityResult
    result = TrainingCompatibilityResult({}, tuple({"image_id": str(index),
        "issue_type": "duplicate_annotation_conflict"} for index in range(size)), 1, 2,
        {"selected_train_image_ids": [str(index) for index in range(size)], "selected_train_count": size})
    body = {**result.summary(), **compatibility_page(result, limit=24)}
    assert len(body["items"]) == 24
    assert "selected_train_image_ids" not in body["selection_truth"]
    assert len(json.dumps(body)) < 8000


def review_payload(project, *, exclude=("b",), original=("a", "b", "c"), test=()):
    return {"original_train_image_ids": list(original), "original_test_image_ids": list(test),
            "excluded_image_ids": list(exclude),
            "material_revision": MaterialRepository(project).current_revision(),
            "annotation_revision": AnnotationRepository(project).current_revision()}


def test_explicit_duplicate_review_excludes_only_new_input_and_keeps_original_truth(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="b" * 64)])
    before = AnnotationRepository(project).get_many(["a", "b", "c"])
    payload = request(("a", "c"), duplicate_review=review_payload(project))
    result = evaluate_training_compatibility(tmp_path, project, payload, {"id": "alg"})
    assert result.summary()["compatible"] is True
    assert result.summary()["duplicate_review"]["excluded_count"] == 1
    assert AnnotationRepository(project).get_many(["a", "b", "c"]) == before


@pytest.mark.parametrize("change,match", [
    ({"excluded_image_ids": ["c"]}, "exclusion"),
    ({"material_revision": 0}, "revision"),
    ({"annotation_revision": 0}, "revision"),
])
def test_duplicate_review_rejects_stale_or_unrelated_exclusion(tmp_path, change, match):
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="b" * 64)])
    review = {**review_payload(project), **change}
    with pytest.raises(ValueError, match=match):
        evaluate_training_compatibility(tmp_path, project, request(("a", "c"), duplicate_review=review), {"id": "alg"})


def test_duplicate_review_cannot_hide_original_cross_role_leakage(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="b" * 64), row("t", sha="c" * 64)])
    review = review_payload(project, original=("a", "c"), test=("b", "t"))
    payload = request(("a", "c"), split_mode="independent_test_set", test_image_ids=["t"],
                      duplicate_review=review)
    with pytest.raises(ValueError, match="content hash leakage"):
        evaluate_training_compatibility(tmp_path, project, payload, {"id": "alg"})


def test_final_review_revision_rejects_post_preflight_manual_edit(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="b" * 64)])
    review = review_payload(project)
    AnnotationRepository(project).upsert_many([{"image_id": "b", "annotation_state": "annotated",
        "annotation_scope": ["fire"], "boxes": row("b")["boxes"]}])
    with pytest.raises(ValueError, match="revision"):
        evaluate_training_compatibility(tmp_path, project, request(("a", "c"), duplicate_review=review), {"id": "alg"})
    fresh = evaluate_training_compatibility(tmp_path, project, request(("a", "b", "c")), {"id": "alg"})
    assert fresh.summary()["compatible"] is True


def test_expected_revision_pair_rejects_drift_and_partial_pair(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", sha="b" * 64)])
    for fields in ({"expected_material_revision": 0, "expected_annotation_revision": 0},
                   {"expected_material_revision": 1}):
        with pytest.raises(ValueError, match="revision"):
            evaluate_training_compatibility(tmp_path, project, request(("a", "b"), **fields), {"id": "alg"})


def test_failed_task_current_diagnosis_never_pretends_to_be_historical_truth(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.task_runtime import ArtifactStore, TaskKind, TaskStatus, TaskRecord
    from dataclasses import replace
    from platform_core.training_recovery_api import training_recovery_router
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="c" * 64),
        row("d", sha="b" * 64), row("e", sha="b" * 64, x=3)])
    artifacts = ArtifactStore(tmp_path / "tasks")
    artifacts.atomic_write_json("old", "payload.json", request(("a", "b", "c", "d", "e")))
    task = replace(TaskRecord.new('old','p',TaskKind.TRAINING,'payload.json','history-contract'),
        status=TaskStatus.FAILED, error="duplicate_annotation_conflict token=secret123")
    class Repository:
        def get(self, task_id):
            return task if task_id == "old" else None
        def list(self, **kwargs):
            return SimpleNamespace(items=[task] if TaskKind.TRAINING in kwargs["kinds"] else [], next_cursor=None)
    app = FastAPI()
    app.include_router(training_recovery_router(lambda _: {"id": "p"}, lambda: Repository(),
        lambda: artifacts, project_path_provider=lambda _: project))
    response = TestClient(app).get("/api/v62/projects/p/training-tasks/old/input-diagnosis?limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["historical_evidence"]["status"] == "insufficient_no_input_freeze"
    assert "secret123" not in json.dumps(body)
    assert body["current_diagnosis"]["evidence_basis"] == "current_canonical_annotations"
    assert body["current_diagnosis"]["issue_count"] == 4
    assert len(body["current_diagnosis"]["items"]) == 1
    assert body['current_diagnosis']['items'][0]['protected'] is False
    assert body['current_diagnosis']['items'][0]['reference_reasons'][0]['reason'] == 'TRAINING_FAILED_REQUEST_ONLY'
    filtered = TestClient(app).get("/api/v62/projects/p/training-tasks/old/input-diagnosis",
        params={"query": "b" * 64, "limit": 2, "page": 1})
    assert filtered.status_code == 200
    assert filtered.json()["current_diagnosis"]["total"] == 2
    assert {item["image_id"] for item in filtered.json()["current_diagnosis"]["items"]} == {"d", "e"}
    assert not artifacts.artifact_path("old", "input-freeze.json").exists()


def test_prepare_conflicting_gt_persists_structured_failure_evidence(tmp_path):
    from types import SimpleNamespace
    from platform_core.remote_training_tasks import TrainingPrepareHandler, RemoteTrainingPreparationError
    from platform_core.task_runtime import ArtifactStore
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="b" * 64)])
    (project / "algorithms.json").write_text(json.dumps([{"id": "alg"}]), encoding="utf-8")
    artifacts = ArtifactStore(tmp_path / "tasks")
    payload = request(("a", "b", "c"), algorithm_asset_id="alg")
    with pytest.raises(RemoteTrainingPreparationError) as error:
        TrainingPrepareHandler(tmp_path)._freeze_request_contract(SimpleNamespace(artifacts=artifacts),
            SimpleNamespace(task_id="target", project_id="p"), payload)
    assert error.value.code == "DUPLICATE_ANNOTATION_CONFLICT"
    evidence = artifacts.read_json("target", "input-preparation-error.json")
    assert evidence["code"] == "DUPLICATE_ANNOTATION_CONFLICT"
    assert evidence["issue_count"] == 2
    assert evidence["ground_truth_source"] == "original_annotation"
    assert not artifacts.artifact_path("target", "input-freeze.json").exists()


def test_freeze_rechecks_original_gt_changed_after_selection_resolution(tmp_path):
    rows = [row(str(index), sha=f"{index + 1:064x}") for index in range(8)]
    project = seed(tmp_path, rows)
    req = splits.SplitRequest(splits.SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        tuple(value["id"] for value in rows), experiment_percent=20)
    selected = resolve_training_selection(project, req)
    AnnotationRepository(project).upsert_many([{"image_id": "0", "annotation_state": "annotated",
        "annotation_scope": ["fire"], "boxes": row("0", x=3)["boxes"]}])
    with pytest.raises(ValueError, match="selection changed"):
        freeze_training_inputs(project, req, seed=0, selection_resolution=selected,
            label_schema_override=[{"code": "fire", "class_id": 0}])


@pytest.mark.parametrize("state", ["annotated", "confirmed_empty", "unannotated"])
def test_identical_original_gt_is_described_without_choosing_ground_truth(state):
    groups = splits.analyze_training_duplicates([row("a", state=state), row("b", state=state)], ("a", "b"))
    assert groups[0]["issue_type"] == "duplicate_identical"
    assert groups[0]["conflict_types"] == []


def test_duplicate_group_paging_can_find_sha_without_returning_group_members(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", x=5)])
    result = evaluate_training_compatibility(tmp_path, project, request(("a", "b", "c")), {"id": "alg"})
    page = compatibility_page(result, query="a" * 64, issue_type="duplicate_annotation_conflict", page_size=2)
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert all(value["duplicate_group_size"] == 3 and value["annotation_version"] > 0 for value in page["items"])
    assert all("image_ids" not in value and "boxes" not in value for value in page["items"])


def test_annotation_scope_and_box_order_do_not_create_false_duplicate_conflict():
    a = row("a", scope=("fire", "smoke"))
    a["boxes"] += row("z", label="smoke", x=3)["boxes"]
    b = {**a, "id": "b", "annotation_scope": ["smoke", "fire"], "boxes": list(reversed(a["boxes"]))}
    assert splits.analyze_training_duplicates([a, b], ("a", "b"))[0]["issue_type"] == "duplicate_identical"


def test_preflight_reports_cross_role_sha_before_unannotated_test_gate(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", state="unannotated"), row("c", sha="b" * 64)])
    payload = request(("a", "c"), split_mode="independent_test_set", test_image_ids=["b"])
    result = evaluate_training_compatibility(tmp_path, project, payload, {"id": "alg"})
    assert result.summary()["issue_counts"]["content_hash_leakage"] == 2
    assert result.issues[0]["issue_type"] == "content_hash_leakage"
    assert next(item for item in result.issues if item["image_id"] == "b")["annotation_state"] == "unannotated"


def test_prepare_records_leakage_before_unannotated_test_gate(tmp_path):
    from types import SimpleNamespace
    from platform_core.remote_training_tasks import TrainingPrepareHandler, RemoteTrainingPreparationError
    from platform_core.task_runtime import ArtifactStore
    project = seed(tmp_path, [row("a"), row("b", state="unannotated"), row("c", sha="b" * 64)])
    (project / "algorithms.json").write_text(json.dumps([{"id": "alg"}]), encoding="utf-8")
    artifacts = ArtifactStore(tmp_path / "tasks")
    payload = request(("a", "c"), split_mode="independent_test_set", test_image_ids=["b"],
        experiment_percent=None, algorithm_asset_id="alg")
    with pytest.raises(RemoteTrainingPreparationError) as error:
        TrainingPrepareHandler(tmp_path)._freeze_request_contract(SimpleNamespace(artifacts=artifacts),
            SimpleNamespace(task_id="target", project_id="p"), payload)
    assert error.value.code == "CONTENT_HASH_LEAKAGE"
    assert artifacts.read_json("target", "input-preparation-error.json")["code"] == "CONTENT_HASH_LEAKAGE"


@pytest.mark.parametrize("writer", ["material", "annotation"])
def test_freeze_rechecks_revision_after_manifest_build_even_inside_lifecycle_fence(tmp_path, monkeypatch, writer):
    import platform_core.training_tasks as tasks
    from platform_core.material_repository import material_annotation_lifecycle_fence
    rows = [row(str(index), sha=f"{index + 1:064x}") for index in range(8)]
    project = seed(tmp_path, rows)
    req = splits.SplitRequest(splits.SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        tuple(value["id"] for value in rows), experiment_percent=20)
    selected = resolve_training_selection(project, req)
    original = tasks.build_split_manifest
    def write_during_manifest(*args, **kwargs):
        if writer == "material":
            MaterialRepository(project).patch({"0": {"content_sha256": "f" * 64}})
        else:
            AnnotationRepository(project).upsert_many([{"image_id": "0", "annotation_state": "annotated",
                "annotation_scope": ["fire"], "boxes": row("0", x=3)["boxes"]}])
        return original(*args, **kwargs)
    monkeypatch.setattr(tasks, "build_split_manifest", write_during_manifest)
    with material_annotation_lifecycle_fence(project), pytest.raises(ValueError, match="selection changed"):
        freeze_training_inputs(project, req, seed=0, selection_resolution=selected,
            label_schema_override=[{"code": "fire", "class_id": 0}])


@pytest.mark.parametrize("field,value", [
    ("original_train_image_ids", 1), ("original_train_image_ids", "a"),
    ("original_test_image_ids", {}), ("excluded_image_ids", True),
    ("excluded_image_ids", [None]), ("original_train_image_ids", ["a", "a"]),
])
def test_malformed_duplicate_review_returns_validation_error(tmp_path, field, value):
    project = seed(tmp_path, [row("a"), row("b", x=3), row("c", sha="b" * 64)])
    review = {**review_payload(project), field: value}
    with pytest.raises(ValueError):
        evaluate_training_compatibility(tmp_path, project, request(("a", "c"), duplicate_review=review), {"id": "alg"})


def test_direct_freeze_rejects_cross_role_sha_before_unannotated_test_gate(tmp_path):
    project = seed(tmp_path, [row("a"), row("b", state="unannotated"), row("c", sha="b" * 64)])
    req = splits.SplitRequest(splits.SplitMode.INDEPENDENT_TEST_SET, ("a", "c"), ("b",))
    with pytest.raises(ValueError, match="content hash leakage"):
        freeze_training_inputs(project, req, seed=0)


def test_historical_requested_split_does_not_inherit_effective_benchmark_mode(tmp_path):
    from platform_core.training_compatibility import diagnose_training_duplicates
    project = seed(tmp_path, [row("a"), row("b", x=3)])
    payload = request(("a", "b"), split_mode="independent_test_set", test_image_ids=["old-test"],
        requested_split={"mode": "random_test_from_training_pool", "train_image_ids": ["a", "b"],
            "test_image_ids": [], "experiment_percent": 20, "validation_percent": 20})
    result = diagnose_training_duplicates(project, payload)
    assert result.summary()["affected_image_count"] == 2


def test_current_history_diagnosis_omits_deleted_indices_without_rewriting_original_selection(tmp_path):
    from platform_core.training_compatibility import diagnose_training_duplicates
    project = seed(tmp_path, [row('a'), row('b', x=3)])
    payload = request(('a', 'b', 'deleted-old-index'))
    original = copy.deepcopy(payload)
    result = diagnose_training_duplicates(project, payload, current_only=True)
    assert result.summary()['affected_image_count'] == 2
    assert result.selection_truth['missing_current_image_count'] == 1
    assert payload == original
    with pytest.raises(ValueError):
        diagnose_training_duplicates(project, payload)


@pytest.mark.parametrize("size", [100, 1000, 10000])
def test_canonical_duplicate_preflight_has_bounded_page_at_scale(tmp_path, size):
    import time
    project = seed(tmp_path, [row(str(i), x=1 + i % 2) for i in range(size)])
    started = time.perf_counter()
    result = evaluate_training_compatibility(tmp_path, project, request(map(str, range(size))), {"id": "alg"})
    response = {**result.summary(), **compatibility_page(result, page=1, page_size=24)}
    elapsed = time.perf_counter() - started
    assert response["affected_image_count"] == size
    assert len(response["items"]) == 24
    assert len(json.dumps(response)) < 50000
    print(f"canonical_preflight size={size} elapsed={elapsed:.3f}s response_bytes={len(json.dumps(response))}")
def test_gt_conflict_diagnosis_separates_observation_from_cause_and_measures_iou():
    from platform_core.training_compatibility import diagnose_annotation_conflict
    first = {'id': 'a', 'content_sha256': 'same', 'width': 100, 'height': 100,
             'annotation_state': 'annotated', 'annotation_scope': ['person'],
             'import_batch_id': 'zip-a', 'boxes': [{'label': 'person', 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 10}]}
    second = {**first, 'id': 'b', 'import_batch_id': 'zip-b',
              'boxes': [{'label': 'person', 'x1': 5, 'y1': 0, 'x2': 15, 'y2': 10}]}
    result = diagnose_annotation_conflict([first, second], {'person': 0})
    assert 'COORDINATE_DIFFERENCE' in result['observations']
    assert 'DIFFERENT_IMPORT_BATCHES' in result['observations']
    assert result['pairs'][0]['matches'][0]['iou'] == pytest.approx(1 / 3)
    assert result['pairs'][0]['matches'][0]['max_pixel_delta'] == 5
    assert result['root_cause_status'] == 'UNDETERMINED'
    assert result['proven_mapping_error_count'] == 0
    assert result['requires_human_review'] is True


def test_gt_mapping_evidence_requires_canonical_id_not_zip_source_id():
    from platform_core.training_compatibility import diagnose_annotation_conflict
    row = {'id': 'a', 'content_sha256': 'same', 'annotation_state': 'annotated',
           'annotation_scope': ['person'], 'boxes': [
               {'label': 'person', 'class_id': 7, 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 10}]}
    assert diagnose_annotation_conflict([row], {'person': 0})['proven_mapping_error_count'] == 0
    canonical = {**row, 'boxes': [{**row['boxes'][0], 'canonical_project_class_id': 7}]}
    result = diagnose_annotation_conflict([canonical], {'person': 0})
    assert result['proven_mapping_error_count'] == 1
    assert result['mapping_evidence'][0]['expected_class_id'] == 0
    assert result['root_cause_status'] == 'CANONICAL_ID_MISMATCH_PROVEN'


def test_gt_comparison_invalid_geometry_and_missing_provenance_remain_unknown():
    from platform_core.training_compatibility import diagnose_annotation_conflict
    a = {'id': 'a', 'content_sha256': 'same', 'annotation_scope': ['vehicle'],
         'boxes': [{'label': 'person', 'x1': float('nan'), 'y1': 0, 'x2': 2, 'y2': 2}]}
    result = diagnose_annotation_conflict([a, {**a, 'id': 'b', 'boxes': []}], {'person': 0})
    assert 'SCOPE_BOX_MISMATCH' in result['observations']
    assert 'BOX_COUNT_DIFFERENCE' in result['observations']
    assert result['pairs'][0]['geometry_status'] == 'UNVERIFIABLE'
    assert result['pairs'][0]['matches'] == []
    assert result['provenance_status'] == 'INCOMPLETE'

def test_gt_import_mapping_difference_uses_verified_confirmation_and_source_taxonomy():
    from platform_core.training_compatibility import diagnose_annotation_conflict
    common = {'content_sha256': 'same', 'annotation_state': 'annotated'}
    rows = [{**common, 'id': task, 'annotation_scope': [label], 'boxes': [
        {'label': label, 'source_task_id': task, 'import_batch_id': task, 'source_class_id': '0',
         'x1': 0, 'y1': 0, 'x2': 10, 'y2': 10}]}
        for task, label in [('zip-a', 'fire'), ('zip-b', 'smoke')]]
    confirmations = {task: {'external_classes': [{'class_id': '0', 'name': 'source-person'}],
        'label_mapping': {'0': label}, 'verified_task_owner': True,
        'members': {task: [('0', (0, 0, 10, 10))]}}
        for task, label in [('zip-a', 'fire'), ('zip-b', 'smoke')]}
    result = diagnose_annotation_conflict(rows, {'fire': 0, 'smoke': 1}, confirmations)
    assert 'VERIFIED_IMPORT_MAPPING_DIFFERENCE' in result['observations']
    assert result['verified_import_mapping_difference_count'] == 1
    assert result['requires_human_review']
    assert result['provenance_status'] == 'RECORDED'
    unverified = diagnose_annotation_conflict(rows, {'fire': 0, 'smoke': 1})
    assert unverified['verified_import_mapping_difference_count'] == 0
    confirmations['zip-b']['external_classes'][0]['name'] = 'different-taxonomy'
    assert diagnose_annotation_conflict(rows, {}, confirmations)['verified_import_mapping_difference_count'] == 0


def test_explicit_selection_adjustment_accepts_missing_scope_and_cross_role_exclusion(tmp_path):
    from platform_core.training_compatibility import validate_duplicate_review
    project = seed(tmp_path, [row('a'), row('b', scope=()), row('c', sha='b' * 64), row('t', sha='c' * 64)])
    review = {**review_payload(project, exclude=('b',), original=('a', 'c'), test=('b', 't')),
              'review_kind': 'EXPLICIT_SELECTION_ADJUSTMENT'}
    payload = request(('a', 'c'), split_mode='independent_test_set', test_image_ids=['t'], duplicate_review=review)
    split = splits.SplitRequest(splits.SplitMode.INDEPENDENT_TEST_SET, ('a', 'c'), ('t',))
    normalized = validate_duplicate_review(project, payload, split)
    assert normalized['review_kind'] == 'EXPLICIT_SELECTION_ADJUSTMENT'
    assert evaluate_training_compatibility(tmp_path, project, payload, {'id': 'alg'}).summary()['compatible'] is True
    assert AnnotationRepository(project).get('b')['annotation_scope'] == []


@pytest.mark.parametrize('change,match', [
    ({'excluded_image_ids': ['foreign']}, 'exclusion'),
    ({'original_train_image_ids': ['a', 'missing', 'b']}, 'missing'),
    ({'material_revision': -1}, 'revision'),
    ({'annotation_revision': -1}, 'revision'),
    ({'original_test_image_ids': ['a']}, 'roles'),
    ({'review_kind': 'UNTRUSTED_KIND'}, 'kind'),
])
def test_explicit_selection_adjustment_rejects_forged_scope(tmp_path, change, match):
    from platform_core.training_compatibility import validate_duplicate_review
    project = seed(tmp_path, [row('a'), row('b', scope=()), row('c', sha='b' * 64)])
    review = {**review_payload(project), 'review_kind': 'EXPLICIT_SELECTION_ADJUSTMENT', **change}
    with pytest.raises(ValueError, match=match):
        validate_duplicate_review(project, request(('a', 'c'), duplicate_review=review),
            splits.SplitRequest(splits.SplitMode.RANDOM_TEST_FROM_TRAINING_POOL, ('a', 'c'), experiment_percent=20))


def test_explicit_selection_adjustment_benchmark_normalization_preserves_kind(tmp_path):
    from platform_core.training_compatibility import normalize_benchmark_duplicate_review
    project = seed(tmp_path, [row('a'), row('b', scope=(), sha='d' * 64), row('c', sha='b' * 64), row('t', sha='c' * 64)])
    review = {**review_payload(project), 'review_kind': 'EXPLICIT_SELECTION_ADJUSTMENT'}
    payload = request(('a', 'c'), duplicate_review=review)
    resolved = splits.SplitRequest(splits.SplitMode.INDEPENDENT_TEST_SET, ('a', 'c'), ('t',))
    normalized = normalize_benchmark_duplicate_review(project, payload, resolved)
    assert normalized['review_kind'] == review['review_kind']
    assert normalized['original_test_image_ids'] == ['t']
    assert normalized['excluded_image_ids'] == ['b']
