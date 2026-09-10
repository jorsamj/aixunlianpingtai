import json
from dataclasses import replace

import pytest

from platform_core.annotation_batches import AnnotationBatch
from platform_core.annotation_runtime import prepare_request
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord


def _runtime_files(tmp_path, *, label_id="lbl-fire"):
    project_dir = tmp_path / "projects" / "project-1"
    project_dir.mkdir(parents=True)
    (project_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "project-1",
                "labels": ["fire"],
                "label_meta": [
                    {
                        "code": "fire",
                        "label_id": label_id,
                        "display_name": "明火",
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "model_configs.json").write_text(
        json.dumps([{"id": "model-1", "model_name": "vision-model"}]),
        encoding="utf-8",
    )


def test_prepare_request_freezes_stable_label_ids_for_review(tmp_path):
    _runtime_files(tmp_path)

    prepared = prepare_request(
        tmp_path,
        "project-1",
        {"labels": ["fire"], "model_config_id": "model-1"},
        runtime=False,
    )

    assert prepared["label_catalog"] == [
        {
            "code": "fire",
            "label_id": "lbl-fire",
            "class_id": 0,
            "display_name_zh": "明火",
        }
    ]


def test_prepare_request_rejects_label_without_stable_identity(tmp_path):
    _runtime_files(tmp_path, label_id="")

    with pytest.raises(ValueError, match="AI_STABLE_LABEL_ID_MISSING"):
        prepare_request(
            tmp_path,
            "project-1",
            {"labels": ["fire"], "model_config_id": "model-1"},
            runtime=False,
        )


class _Manifest:
    def summary(self):
        return {"total": 1}


class _Context:
    def __init__(self, tmp_path):
        self.artifacts = ArtifactStore(tmp_path / "artifacts")
        self.task = replace(
            TaskRecord.new(
                "batch-ai-1",
                "project-1",
                TaskKind.MATERIAL_BATCH,
                "request.json",
                "materials:project-1",
            )
        )


def test_material_batch_freezes_review_scope_before_candidates_can_be_committed(tmp_path, monkeypatch):
    runtime = {
        "labels": ["fire"],
        "label_catalog": [
            {"code": "fire", "label_id": "lbl-fire", "class_id": 0, "display_name_zh": "明火"}
        ],
    }
    monkeypatch.setattr(
        "platform_core.annotation_batches.prepare_request",
        lambda *_args, **_kwargs: dict(runtime),
    )
    monkeypatch.setattr(
        "platform_core.annotation_batches.StorageManager",
        lambda **_kwargs: object(),
    )
    context = _Context(tmp_path)

    batch = AnnotationBatch(
        tmp_path,
        "project-1",
        object(),
        context,
        _Manifest(),
        {"labels": ["fire"]},
    )

    assert batch.configuration_error is None
    assert context.artifacts.read_json("batch-ai-1", "review-scope.json") == {
        "schema_version": 1,
        "labels": ["fire"],
        "label_ids": ["lbl-fire"],
    }
