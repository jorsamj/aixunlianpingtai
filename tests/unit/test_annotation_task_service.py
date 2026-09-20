from dataclasses import replace
from pathlib import Path

import pytest

from platform_core.annotation_candidates import CandidateDecision, CandidateStore
from platform_core.annotation_task_service import _public_error, commit_candidate_decisions, run_ai_annotation
from platform_core.task_runtime import ArtifactStore, ExecutionFencedError, TaskKind, TaskRecord, TaskStatus


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
        self._fenced = False
        self.fail_checkpoint_once = False

    def assert_current_execution(self):
        if self._fenced:
            raise ExecutionFencedError("task execution is fenced")
        return self.task

    def cancel_requested(self):
        self.assert_current_execution()
        return self._cancelled

    def heartbeat(self, progress=None, stage=None, current_item=None):
        self.assert_current_execution()
        return self.repository.heartbeat(
            self.task.task_id,
            self.lease.lease_token,
            progress=progress,
            stage=stage,
            current_item=current_item,
        )

    def load_checkpoint(self):
        return self.artifacts.read_json("ai-1", "checkpoints/worker.json", default={})

    def save_checkpoint(self, value):
        if self.fail_checkpoint_once:
            self.fail_checkpoint_once = False
            raise RuntimeError("checkpoint write interrupted")
        self.artifacts.atomic_write_json("ai-1", "checkpoints/worker.json", value)


def _install_two_images(context, monkeypatch):
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


def test_worker_enters_review_with_partial_generation_summary(tmp_path, monkeypatch):
    context = FakeContext(tmp_path)
    _install_two_images(context, monkeypatch)

    def annotate(_request, image):
        if image["id"] == "two":
            raise RuntimeError("timeout")
        return {"boxes": [{"id": "box-1", "label": "fire"}]}

    outcome = run_ai_annotation(context, annotate=annotate)
    assert outcome.status is TaskStatus.AWAITING_CONFIRMATION
    assert outcome.generation_partial is True
    assert context.load_checkpoint()["next_index"] == 2
    assert context.load_checkpoint()["source"] == "candidate_store"
    assert CandidateStore(context.artifacts, task_id="ai-1").summary()["failed"] == 1
    assert context.repository.heartbeats[-1][2] == 70


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


def test_candidate_store_ahead_of_checkpoint_skips_completed_provider_call_on_recovery(tmp_path, monkeypatch):
    context = FakeContext(tmp_path)
    _install_two_images(context, monkeypatch)
    calls = []

    def annotate(_request, image):
        calls.append(image["id"])
        return {"boxes": [{"id": f"box-{image['id']}", "label": "fire"}]}

    # Simulate a process dying after the first candidate SQLite transaction
    # committed but before worker.json could advance.
    context.fail_checkpoint_once = True
    with pytest.raises(RuntimeError, match="checkpoint write interrupted"):
        run_ai_annotation(context, annotate=annotate)

    store = CandidateStore(context.artifacts, task_id="ai-1")
    assert store.generation_prefix(["one", "two"]) == {
        "next_index": 1,
        "succeeded": 1,
        "failed": 0,
    }
    assert context.load_checkpoint() == {}
    assert calls == ["one"]

    outcome = run_ai_annotation(context, annotate=annotate)
    assert outcome.status is TaskStatus.AWAITING_CONFIRMATION
    # The durable candidate row is recovery truth, so image "one" is not billed twice.
    assert calls == ["one", "two"]
    assert context.load_checkpoint()["next_index"] == 2
    assert store.summary()["total"] == 2


def test_provider_result_cannot_commit_after_execution_is_fenced(tmp_path, monkeypatch):
    context = FakeContext(tmp_path)
    context.artifacts.atomic_write_json("ai-1", "request.json", {
        "image_ids": ["one"], "labels": ["fire"], "threshold": 0.45,
        "model_config_id": "model-1", "overwrite": False,
    })
    monkeypatch.setattr(
        "platform_core.annotation_task_service.load_task_images",
        lambda *_: [{"id": "one", "filename": "one.jpg", "width": 100, "height": 100, "path": "one.jpg"}],
    )

    def annotate(_request, _image):
        context._fenced = True
        return {"boxes": [{"id": "late-box", "label": "fire"}]}

    with pytest.raises(ExecutionFencedError):
        run_ai_annotation(context, annotate=annotate)

    # The manifest may exist, but stale model output must not become candidate truth.
    context._fenced = False
    assert CandidateStore(context.artifacts, task_id="ai-1").summary()["total"] == 0


def test_provider_result_is_discarded_when_cancel_arrives_during_inference(tmp_path, monkeypatch):
    context = FakeContext(tmp_path)
    context.artifacts.atomic_write_json("ai-1", "request.json", {
        "image_ids": ["one"], "labels": ["fire"], "threshold": 0.45,
        "model_config_id": "model-1", "overwrite": False,
    })
    monkeypatch.setattr(
        "platform_core.annotation_task_service.load_task_images",
        lambda *_: [{"id": "one", "filename": "one.jpg", "width": 100, "height": 100, "path": "one.jpg"}],
    )

    def annotate(_request, _image):
        context._cancelled = True
        return {"boxes": [{"id": "cancelled-box", "label": "fire"}]}

    outcome = run_ai_annotation(context, annotate=annotate)
    assert outcome.status is TaskStatus.CANCELLED
    assert CandidateStore(context.artifacts, task_id="ai-1").summary()["total"] == 0


def test_commit_replay_does_not_duplicate_candidate_boxes(tmp_path, monkeypatch):
    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id="commit-1", page_size=50)
    store.initialize(labels=["fire"], total_images=1)
    store.append_items([{
        "image_id": "image-1", "status": "success",
        "boxes": [{"id": "candidate-1", "class_id": 0, "label": "fire",
                   "x1": 1, "y1": 1, "x2": 20, "y2": 20}],
    }])
    store.apply_decisions([CandidateDecision(image_id="image-1", accepted=True)])
    written = []
    monkeypatch.setattr(
        "platform_core.annotation_task_service.read_formal_annotation",
        lambda _project, _image: {"boxes": list(written)},
    )
    monkeypatch.setattr(
        "platform_core.annotation_task_service.write_formal_annotation",
        lambda _project, _image, boxes: written.__setitem__(slice(None), boxes),
    )
    first = commit_candidate_decisions("project-1", "commit-1", store, overwrite=False)
    second = commit_candidate_decisions("project-1", "commit-1", store, overwrite=False)
    assert first["boxes_added"] == 1
    assert first["image_summaries"] == [{"image_id": "image-1", "box_count": 1, "labels": ["fire"]}]
    assert second["boxes_added"] == 0
    assert [box["candidate_id"] for box in written] == ["candidate-1"]
    assert written[0]["source_task_id"] == "commit-1"


def test_candidate_label_revalidation_is_fail_closed_even_without_explicit_mapping(tmp_path):
    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id="catalog-revalidate", page_size=50)
    store.initialize(labels=["fire"], total_images=1)
    store.append_items([{
        "image_id": "image-1",
        "status": "success",
        "boxes": [{"id": "box-1", "class_id": 0, "label": "fire",
                   "x1": 1, "y1": 1, "x2": 20, "y2": 20}],
    }])

    # An unchanged label name may receive a different project class_id after
    # catalog maintenance. Review commit must repair the canonical identity.
    store.remap_labels({}, {"fire": 4})
    assert store.get("image-1")["boxes"][0]["class_id"] == 4

    # If the previously confirmed label is no longer active, do not silently
    # write stale candidate truth into AnnotationRepository.
    with pytest.raises(ValueError, match="candidate label is unavailable"):
        store.remap_labels({}, {"smoke": 1})


def test_public_worker_error_redacts_common_secret_shapes():
    error = RuntimeError("Authorization: Bearer secret-token api_key=very-secret sk-12345678901234567890")
    public = _public_error(error)
    assert "secret-token" not in public
    assert "very-secret" not in public
    assert "sk-12345678901234567890" not in public
    assert "[REDACTED]" in public
