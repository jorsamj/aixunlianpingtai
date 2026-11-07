from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi import HTTPException


def test_p2_reviewed_mining_preview_adoption_reuses_original_candidate_set_and_protects_test(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from platform_core.task_runtime import ArtifactStore, TaskKind, TaskStatus
    from platform_core.annotation_candidates import CandidateStore, CandidateDecision
    platform, project, rows, _, _ = _setup(monkeypatch, tmp_path)
    task_id = 'reviewed-mining'
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    request = {'mode': 'hard_sample_yolo', 'image_ids': ['training-a'], 'source_hashes': {'training-a': 'a' * 64},
        'mining_algorithm_id': 'algo', 'mining_version_id': 'v1', 'mining_model_sha256': 'f' * 64}
    artifacts.atomic_write_json(task_id, 'request.json', request)
    store = CandidateStore(artifacts, task_id=task_id)
    store.initialize(labels=['person'], total_images=1)
    store.append_items([{'image_id': 'training-a', 'status': 'empty', 'boxes': []}])
    store.apply_decisions([CandidateDecision('training-a', True)])
    store.record_commit_summaries([{'image_id': 'training-a', 'box_count': 0, 'labels': [],
        'annotation_state': 'confirmed_empty', 'annotation_origin': 'ai_confirmed'}])
    rows[0].update(width=100, height=80)
    annotation = {'annotation_state': 'confirmed_empty', 'content_digest': 'd' * 64,
                  'annotation_origin': 'ai_confirmed', 'annotation_scope': ['person'], 'boxes': []}
    class Annotations:
        def __init__(self, *args): pass
        def get_many(self, ids): return {key: dict(annotation) for key in ids}
    task = SimpleNamespace(kind=TaskKind.AI_ANNOTATION, status=TaskStatus.SUCCEEDED, result_ref='result.json', payload_ref='request.json')
    version = {'id': 'v1'}
    monkeypatch.setattr(platform, '_advanced_evaluation_context', lambda *a: (version, {'model_sha256': 'f' * 64}))
    monkeypatch.setattr(platform, '_require_annotation_review_task', lambda *a: task)
    monkeypatch.setattr(platform, 'shared_task_artifacts', lambda: artifacts)
    monkeypatch.setattr(platform, 'AnnotationRepository', Annotations)
    action = {'status': 'confirmed', 'action': 'supplement_data', 'action_id': 'e' * 64,
              'source': {'algorithm_id': 'algo', 'version_id': 'v1'}}
    monkeypatch.setattr(platform, '_supplement_data_action', lambda *a: ({'id': 'algo'}, version, action))
    monkeypatch.setattr(platform, 'algorithms_file', lambda _: project / 'algorithms.json')
    def update(path, algorithm_id, version_id, patch, **kwargs):
        version.update(patch);return dict(version)
    monkeypatch.setattr(platform, 'update_algorithm_version', update)
    preview = platform.preview_reviewed_mining('project', 'algo', 'v1', task_id)
    assert preview['items'][0]['eligible'] is True
    assert not (project / 'online_feedback.sqlite3').exists()
    selection = platform.FreezeReviewedMiningReq(confirmed=True, candidates=[{'image_id': 'training-a', 'candidate_digest': preview['items'][0]['candidate_digest']}])
    first = platform.adopt_reviewed_mining('project', 'algo', 'v1', task_id, selection)
    second = platform.adopt_reviewed_mining('project', 'algo', 'v1', task_id, selection)
    assert first['candidate_set']['material_ids'] == ['training-a']
    assert first['candidate_set']['automatic_execution'] is False and second['idempotent'] is True
    from platform_core.online_feedback import OnlineFeedbackRepository
    feedback = OnlineFeedbackRepository(project).get(first['candidate_set']['feedback_ids'][0])
    assert feedback['payload']['source']['source_channel'] == 'hard_sample_review'
    annotation['content_digest'] = 'b' * 64
    with pytest.raises(HTTPException) as changed:
        platform.adopt_reviewed_mining('project', 'algo', 'v1', task_id, selection)
    assert changed.value.status_code == 409
    (project / 'snapshots' / ('c' * 64 + '.json')).write_text(json.dumps({'test_image_ids': ['training-a']}), encoding='utf-8')
    with pytest.raises(HTTPException) as protected:
        platform.preview_reviewed_mining('project', 'algo', 'v1', task_id)
    assert 'FROZEN_TEST' in str(protected.value.detail)
    task.status = TaskStatus.RUNNING
    with pytest.raises(HTTPException) as active:
        platform.preview_reviewed_mining('project', 'algo', 'v1', task_id)
    assert active.value.status_code == 409


def _setup(monkeypatch, tmp_path: Path):
    import app as platform

    path = tmp_path / "trusted-best.pt"
    path.write_bytes(b"trusted pretrained weight fixture")
    project = tmp_path / "project"
    (project / "snapshots").mkdir(parents=True)
    (project / "snapshots" / ("c" * 64 + ".json")).write_text(json.dumps({
        "snapshot_id": "c" * 64,
        "label_schema": [{"code": "person", "class_id": 0}],
        "test_image_ids": [], "images": [],
    }), encoding="utf-8")

    rows = [
        {"id": "training-a", "content_sha256": "a" * 64,
         "annotation_state": "unannotated", "box_count": 0},
        {"id": "training-b", "content_sha256": "b" * 64,
         "annotation_state": "unannotated", "box_count": 0},
    ]
    class Material:
        def get_many(self, ids):
            return [dict(row) for row in rows if row["id"] in ids]
    tasks = {}
    class Repository:
        def get(self, task_id):
            return tasks.get(task_id)
        def create(self, record):
            assert record.task_id not in tasks
            tasks[record.task_id] = record
            return record
    payloads = {}
    class Artifacts:
        def atomic_write_json(self, task_id, ref, content):
            payloads[task_id] = dict(content)
    monkeypatch.setattr(platform, "get_project", lambda _: {"id": "project"})
    monkeypatch.setattr(platform, "project_dir", lambda _: project)
    monkeypatch.setattr(platform, "_algorithm_version_for_action",
                        lambda p, a, v: ({"id": a}, {"id": v, "best_path": str(path),
                                              "snapshot_id": "c" * 64}))
    monkeypatch.setattr(platform, "material_store", lambda _: Material())
    monkeypatch.setattr(platform, "_annotation_label_catalog",
                        lambda _: [{"code": "person", "class_id": 0}])
    monkeypatch.setattr(platform, "shared_task_repository", lambda: Repository())
    monkeypatch.setattr(platform, "shared_task_artifacts", lambda: Artifacts())
    monkeypatch.setattr(platform, "_storage_source_fence", lambda: nullcontext())
    monkeypatch.setattr(platform, "public_annotation_task", lambda record: {
        "id": record.task_id, "status": record.status.value,
        "kind": record.kind.value, "required_capabilities": record.required_capabilities,
    })
    return platform, project, rows, tasks, payloads


def test_one_durable_annotation_task_is_created_for_existing_training_material(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    result = platform.create_hard_sample_mining("project", "algorithm", "v2",
        platform.HardSampleMiningCreateReq(image_ids=["training-a"], source="existing"))
    assert result["status"] == "QUEUED"
    assert result["kind"] == "AI_ANNOTATION"
    assert result["required_capabilities"] == ("mining.ultralytics",)
    request = payloads[result["id"]]
    assert request["mode"] == "hard_sample_yolo"
    assert request["source_hashes"] == {"training-a": "a" * 64}
    assert request["labels"] == ["person"]
    assert request["overwrite"] is False
    assert request["mining_snapshot_id"] == "c" * 64
    assert request["mining_snapshot_sha256"]
    assert request["mining_model_sha256"]
    assert len(tasks) == 1


def test_frozen_test_or_same_bytes_cannot_be_mined(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    (project / "snapshots" / ("d" * 64 + ".json")).write_text(json.dumps({
        "test_image_ids": ["training-b"],
        "images": [{"image_id": "training-b", "content_sha256": "b" * 64}],
    }), encoding="utf-8")
    with pytest.raises(HTTPException) as ex:
        platform.create_hard_sample_mining("project", "algorithm", "v2",
            platform.HardSampleMiningCreateReq(image_ids=["training-b"]))
    assert ex.value.status_code == 409
    assert not tasks
    rows[0]["content_sha256"] = "b" * 64
    with pytest.raises(HTTPException) as ex:
        platform.create_hard_sample_mining("project", "algorithm", "v2",
            platform.HardSampleMiningCreateReq(image_ids=["training-a"]))
    assert ex.value.status_code == 409
    assert not payloads


def test_upload_retry_reuses_existing_task_identity(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    a = platform._enqueue_hard_sample_mining(
        "project", "algorithm", "v2", ["training-a"],
        source="upload", request_key="upload-123")
    b = platform._enqueue_hard_sample_mining(
        "project", "algorithm", "v2", ["training-a"],
        source="upload", request_key="upload-123")
    assert a == b
    assert len(tasks) == 1


def test_automatic_mining_never_relabels_already_annotated_material(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    rows[0]["annotation_state"] = "annotated"
    with pytest.raises(HTTPException) as ex:
        platform._enqueue_hard_sample_mining(
            "project", "algorithm", "v2", ["training-a"], source="upload")
    assert ex.value.status_code == 409
    assert not tasks
