from dataclasses import replace
from pathlib import Path

from platform_core.annotation_candidates import CandidateStore
from platform_core.annotation_task_service import run_ai_annotation
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
