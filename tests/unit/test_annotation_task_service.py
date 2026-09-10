from dataclasses import replace
from pathlib import Path

import pytest

from platform_core.annotation_candidates import CandidateDecision, CandidateStore
from platform_core.annotation_task_service import _public_error, commit_candidate_decisions, run_ai_annotation
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskStatus


class FakeRepository:
    def __init__(self, task):
        self.task = task
        self.heartbeats = []

    def get(self, _task_id):
        return self.task

    def heartbeat(self, task_id, lease_token, progress=None, stage=None, current_item=None):
        self.heartbeats.append((task_id, lease_token, progress, stage, current_item))
        return self.task


class FakeContext:
    def __init__(self, tmp_path: Path):
        self.artifacts = ArtifactStore(tmp_path)
        self.task = replace(TaskRecord.new(
            "ai-1", "project-1", TaskKind.AI_ANNOTATION, "request.json",
            "vision:model-1", required_capabilities=("vision_provider",),
        ), status=TaskStatus.RUNNING)
        self.lease = type("Lease", (), {"lease_token": "lease-1"})()
        self.repository = FakeRepository(self.task)
        self._cancelled = False

    def cancel_requested(self):
        return self._cancelled

    def load_checkpoint(self):
        return self.artifacts.read_json("ai-1", "checkpoints/worker.json", default={})

    def save_checkpoint(self, value):
        self.artifacts.atomic_write_json("ai-1", "checkpoints/worker.json", value)


def test_worker_enters_review_with_partial_generation_summary(tmp_path, monkeypatch):
    context = FakeContext(tmp_path)
    context.artifacts.atomic_write_json("ai-1", "request.json", {
        "image_ids": ["one", "two"], "labels": ["fire"], "threshold": 0.45,
        "model_config_id": "model-1", "overwrite": False,
    })
    monkeypatch.setattr(
        "platform_core.annotation_task_service.load_task_images",
        lambda _project, _ids: [
            {"id": "one", "filename": "one.jpg", "width": 100, "height": 100, "path": "one.jpg"},
            {"id": "two", "filename": "two.jpg", "width": 100, "height": 100, "path": "two.jpg"},
        ],
    )

    def annotate(_request, image):
        if image["id"] == "two":
            raise RuntimeError("timeout")
        return {"boxes": [{"id": "box-1", "label": "fire"}]}

    outcome = run_ai_annotation(context, annotate=annotate)
    assert outcome.status is TaskStatus.AWAITING_CONFIRMATION
    assert outcome.generation_partial is True
    assert context.load_checkpoint()["next_index"] == 2
    assert CandidateStore(context.artifacts, task_id="ai-1").summary()["failed"] == 1
    assert context.repository.heartbeats[-1][2] == 100


def test_worker_freezes_stable_review_scope_for_real_runtime(tmp_path, monkeypatch):
    context = FakeContext(tmp_path)
    context.artifacts.atomic_write_json("ai-1", "request.json", {
        "image_ids": ["one"], "labels": ["fire"], "threshold": 0.45,
        "model_config_id": "model-1", "overwrite": False,
    })
    monkeypatch.setattr(
        "platform_core.annotation_task_service._prepare_runtime_request",
        lambda _project, request: {
            **request,
            "label_catalog": [{"code": "fire", "label_id": "lbl-fire", "class_id": 0}],
        },
    )
    monkeypatch.setattr(
        "platform_core.annotation_task_service.load_task_images",
        lambda *_: [{"id": "one", "filename": "one.jpg", "width": 100, "height": 100, "path": "one.jpg"}],
    )
    monkeypatch.setattr(
        "platform_core.annotation_task_service.annotate_one",
        lambda *_: {"boxes": []},
    )

    # Pass the module function itself after monkeypatch so run_ai_annotation
    # follows the real-runtime preparation branch.
    from platform_core import annotation_task_service as service
    outcome = run_ai_annotation(context, annotate=service.annotate_one)

    assert outcome.status is TaskStatus.AWAITING_CONFIRMATION
    assert context.artifacts.read_json("ai-1", "review-scope.json") == {
        "schema_version": 1,
        "labels": ["fire"],
        "label_ids": ["lbl-fire"],
    }


def test_worker_stops_at_cancel_boundary_without_processing_more_images(tmp_path, monkeypatch):
    context = FakeContext(tmp_path)
    context._cancelled = True
    context.artifacts.atomic_write_json("ai-1", "request.json", {
        "image_ids": ["one"], "labels": ["fire"], "threshold": 0.45,
        "model_config_id": "model-1", "overwrite": False,
    })
    monkeypatch.setattr("platform_core.annotation_task_service.load_task_images", lambda *_: [{"id": "one"}])

    def must_not_run(*_args):
        raise AssertionError("provider must not be called")

    outcome = run_ai_annotation(context, annotate=must_not_run)
    assert outcome.status is TaskStatus.CANCELLED


def _reviewable_store(tmp_path: Path, task_id: str, *, status="success", boxes=None):
    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id=task_id, page_size=50)
    store.initialize(labels=["fire"], total_images=1)
    artifacts.atomic_write_json(task_id, "review-scope.json", {
        "schema_version": 1, "labels": ["fire"], "label_ids": ["lbl-fire"],
    })
    store.append_items([{
        "image_id": "image-1", "status": status,
        "boxes": list(boxes or []),
    }])
    store.apply_decisions([CandidateDecision(image_id="image-1", accepted=True)])
    return store


def test_commit_replay_does_not_duplicate_candidate_boxes(tmp_path, monkeypatch):
    store = _reviewable_store(tmp_path, "commit-1", boxes=[{
        "id": "candidate-1", "class_id": 0, "label": "fire", "label_id": "lbl-fire",
        "x1": 1, "y1": 1, "x2": 20, "y2": 20,
    }])
    current = {"boxes": [], "annotation_scope": []}
    monkeypatch.setattr(
        "platform_core.annotation_task_service.read_formal_annotation",
        lambda _project, _image: {"boxes": list(current["boxes"]), "annotation_scope": list(current["annotation_scope"])},
    )

    def write(_project, _image, boxes, *, annotation_state, annotation_scope):
        current["boxes"] = list(boxes)
        current["annotation_state"] = annotation_state
        current["annotation_scope"] = list(annotation_scope)

    monkeypatch.setattr("platform_core.annotation_task_service.write_formal_annotation", write)
    first = commit_candidate_decisions("project-1", "commit-1", store, overwrite=False)
    second = commit_candidate_decisions("project-1", "commit-1", store, overwrite=False)

    assert first["boxes_added"] == 1
    assert first["image_summaries"] == [{
        "image_id": "image-1", "box_count": 1, "labels": ["fire"],
        "annotation_state": "annotated", "annotation_scope": ["lbl-fire"],
    }]
    assert second["boxes_added"] == 0
    assert [box["candidate_id"] for box in current["boxes"]] == ["candidate-1"]
    assert current["boxes"][0]["source_task_id"] == "commit-1"
    assert current["annotation_scope"] == ["lbl-fire"]


def test_accepting_empty_candidate_creates_explicit_scoped_negative(tmp_path, monkeypatch):
    store = _reviewable_store(tmp_path, "commit-empty", status="empty", boxes=[])
    writes = []
    monkeypatch.setattr(
        "platform_core.annotation_task_service.read_formal_annotation",
        lambda *_: {"boxes": [], "annotation_state": "unannotated", "annotation_scope": []},
    )
    monkeypatch.setattr(
        "platform_core.annotation_task_service.write_formal_annotation",
        lambda _project, _image, boxes, **kwargs: writes.append((boxes, kwargs)),
    )

    result = commit_candidate_decisions("project-1", "commit-empty", store, overwrite=False)

    assert result["boxes_added"] == 0
    assert result["confirmed_scope"] == ["lbl-fire"]
    assert writes == [([], {"annotation_state": "confirmed_empty", "annotation_scope": ["lbl-fire"]})]
    assert result["image_summaries"][0]["annotation_state"] == "confirmed_empty"


def test_accepting_empty_for_new_scope_preserves_existing_other_label_boxes(tmp_path, monkeypatch):
    store = _reviewable_store(tmp_path, "commit-empty-existing", status="empty", boxes=[])
    existing = [{"id": "smoke-1", "label": "smoke", "label_id": "lbl-smoke", "class_id": 1}]
    writes = []
    monkeypatch.setattr(
        "platform_core.annotation_task_service.read_formal_annotation",
        lambda *_: {"boxes": existing, "annotation_state": "annotated", "annotation_scope": ["lbl-smoke"]},
    )
    monkeypatch.setattr(
        "platform_core.annotation_task_service.write_formal_annotation",
        lambda _project, _image, boxes, **kwargs: writes.append((boxes, kwargs)),
    )

    commit_candidate_decisions("project-1", "commit-empty-existing", store, overwrite=False)

    assert writes == [(existing, {
        "annotation_state": "annotated",
        "annotation_scope": ["lbl-smoke", "lbl-fire"],
    })]


def test_commit_requires_frozen_review_scope(tmp_path):
    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id="missing-scope", page_size=50)
    store.initialize(labels=["fire"], total_images=1)
    store.append_items([{"image_id": "image-1", "status": "empty", "boxes": []}])
    store.apply_decisions([CandidateDecision(image_id="image-1", accepted=True)])

    with pytest.raises(ValueError, match="review scope contract is missing"):
        commit_candidate_decisions("project-1", "missing-scope", store, overwrite=False)


def test_public_worker_error_redacts_common_secret_shapes():
    error = RuntimeError("Authorization: Bearer secret-token api_key=very-secret sk-12345678901234567890")
    public = _public_error(error)
    assert "secret-token" not in public
    assert "very-secret" not in public
    assert "sk-12345678901234567890" not in public
    assert "[REDACTED]" in public
