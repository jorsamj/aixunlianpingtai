from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from platform_core import annotation_batches
from platform_core.annotation_batches import AnnotationBatch
from platform_core.task_runtime import ArtifactStore


class _Manifest:
    def __init__(self):
        self.transitions = []

    def summary(self, current=None):
        succeeded = sum(1 for _ids, state, _error in self.transitions if state == "succeeded")
        failed = sum(1 for _ids, state, _error in self.transitions if state == "failed")
        return {
            "total": 1,
            "processed": succeeded + failed,
            "succeeded": succeeded,
            "failed": failed,
            "current_image_id": current,
            "current": current,
        }

    def transition(self, ids, state, error=None):
        self.transitions.append((list(ids), state, error))


class _Materials:
    def __init__(self, image_path: Path):
        self.image_path = image_path

    def get_many(self, _ids):
        return [{"id": "image-1", "filename": self.image_path.name}]


class _Context:
    def __init__(self, tmp_path: Path):
        self.task = SimpleNamespace(task_id="annotation-task-1", project_id="project-1")
        self.artifacts = ArtifactStore(tmp_path / "artifacts")
        self.checkpoints = []

    def save_checkpoint(self, value):
        self.checkpoints.append(dict(value))


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "source.jpg"
    Image.new("RGB", (16, 12), "white").save(path)
    return path


def _build_batch(tmp_path: Path, monkeypatch, *, on_materialize=None):
    image_path = _image(tmp_path)
    context = _Context(tmp_path)
    manifest = _Manifest()
    materials = _Materials(image_path)
    monkeypatch.setattr(annotation_batches, "prepare_request", lambda *_args, **_kwargs: object())

    def materialize(_self, _material):
        if on_materialize is not None:
            on_materialize()
        return SimpleNamespace(path=image_path)

    monkeypatch.setattr(annotation_batches.StorageManager, "materialize", materialize)
    batch = AnnotationBatch(tmp_path, "project-1", materials, context, manifest, {"labels": ["person"]})
    return batch, context, manifest, materials


def test_cancel_during_materialize_prevents_billable_inference(tmp_path: Path, monkeypatch):
    cancelled = False
    inference_calls = 0

    def cancel_during_materialize():
        nonlocal cancelled
        cancelled = True

    batch, _context, manifest, materials = _build_batch(
        tmp_path, monkeypatch, on_materialize=cancel_during_materialize
    )

    def annotate(_runtime, _image):
        nonlocal inference_calls
        inference_calls += 1
        return {"boxes": []}

    monkeypatch.setattr(annotation_batches, "annotate_one", annotate)

    def check_active(_context, _stage="processing", _current=None, _progress=None):
        if cancelled:
            raise InterruptedError("material batch cancelled")

    with pytest.raises(InterruptedError, match="cancel"):
        batch.process(materials, [{"image_id": "image-1"}], check_active)

    assert inference_calls == 0
    assert batch.store.get("image-1") is None
    assert not any(state == "succeeded" for _ids, state, _error in manifest.transitions)


def test_cancel_during_inference_prevents_candidate_commit(tmp_path: Path, monkeypatch):
    cancelled = False
    batch, _context, manifest, materials = _build_batch(tmp_path, monkeypatch)

    def annotate(_runtime, _image):
        nonlocal cancelled
        cancelled = True
        return {
            "boxes": [
                {"label": "person", "x1": 1, "y1": 1, "x2": 8, "y2": 8}
            ]
        }

    monkeypatch.setattr(annotation_batches, "annotate_one", annotate)

    def check_active(_context, _stage="processing", _current=None, _progress=None):
        if cancelled:
            raise InterruptedError("material batch cancelled")

    with pytest.raises(InterruptedError, match="cancel"):
        batch.process(materials, [{"image_id": "image-1"}], check_active)

    assert batch.store.get("image-1") is None
    assert not any(state == "succeeded" for _ids, state, _error in manifest.transitions)
