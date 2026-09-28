import json

import pytest

import platform_core.annotation_runtime as annotation_runtime


def _write_project(tmp_path):
    project_dir = tmp_path / "projects" / "p1"
    project_dir.mkdir(parents=True)
    (project_dir / "meta.json").write_text(
        json.dumps({
            "id": "p1",
            "labels": [{"code": "fire", "status": "active", "display_name_zh": "火焰"}],
            "label_meta": [],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "prompt_library.json").write_text("[]", encoding="utf-8")
    return project_dir


def _model(model_name="vision-v1", detect_url="http://vision-v1.local/v1"):
    return {
        "id": "model-1",
        "name": "视觉模型一",
        "model_name": model_name,
        "provider_type": "local_openai",
        "provider_adapter": "local_openai",
        "detect_url": detect_url,
        "secret_ref": "xjalgo:model-config:model-1",
        "headers_json": {
            "X-Trace": "keep",
            "Authorization": "Bearer must-not-freeze",
            "X-Api-Key": "must-not-freeze",
        },
        "updated_at": "2026-09-28T06:20:00Z",
    }


def test_submit_freezes_safe_model_snapshot_and_revision(tmp_path):
    _write_project(tmp_path)
    frozen = annotation_runtime.prepare_request(
        tmp_path,
        "p1",
        {
            "image_ids": ["image-1"],
            "labels": ["fire"],
            "model_config_id": "model-1",
            "threshold": 0.45,
        },
        runtime=False,
        model_configs=[_model()],
    )

    assert frozen["schema_version"] == 2
    assert frozen["model_config_id"] == "model-1"
    assert frozen["model_config_name"] == "视觉模型一"
    assert frozen["model_provider"] == "local_openai"
    assert len(frozen["model_config_revision"]) == 64
    assert frozen["model_config_snapshot"]["model_name"] == "vision-v1"
    assert frozen["model_config_snapshot"]["detect_url"] == "http://vision-v1.local/v1"
    assert frozen["model_config_snapshot"]["secret_ref"] == "xjalgo:model-config:model-1"
    assert frozen["model_config_snapshot"]["headers_json"] == {"X-Trace": "keep"}
    assert "api_key" not in frozen["model_config_snapshot"]
    assert "_api_key" not in frozen["model_config_snapshot"]


def test_runtime_uses_frozen_model_snapshot_even_after_live_config_changes(tmp_path, monkeypatch):
    _write_project(tmp_path)
    frozen = annotation_runtime.prepare_request(
        tmp_path,
        "p1",
        {
            "image_ids": ["image-1"],
            "labels": ["fire"],
            "model_config_id": "model-1",
        },
        runtime=False,
        model_configs=[_model()],
    )

    # Simulate editing the saved model after the task was already queued.
    (tmp_path / "model_configs.json").write_text(
        json.dumps([_model("vision-v2", "http://vision-v2.local/v1")], ensure_ascii=False),
        encoding="utf-8",
    )
    captured = {}

    class FakeSecrets:
        def get(self, reference):
            assert reference == "xjalgo:model-config:model-1"
            return "frozen-secret-reference-value"

    def fake_provider(config):
        captured.update(config)
        return object()

    monkeypatch.setattr(annotation_runtime, "KeyringSecretStore", FakeSecrets)
    monkeypatch.setattr(annotation_runtime, "provider_factory", fake_provider)

    runtime = annotation_runtime.prepare_request(
        tmp_path,
        "p1",
        frozen,
        runtime=True,
    )

    assert captured["model_name"] == "vision-v1"
    assert captured["detect_url"] == "http://vision-v1.local/v1"
    assert captured["_api_key"] == "frozen-secret-reference-value"
    assert captured["headers_json"] == {"X-Trace": "keep"}
    assert runtime["_provider_config"]["model_name"] == "vision-v1"
    assert runtime["_provider_config"]["detect_url"] == "http://vision-v1.local/v1"
    assert "secret_ref" not in runtime["_provider_config"]
    assert "_api_key" not in runtime["_provider_config"]


def test_runtime_fails_closed_if_frozen_model_snapshot_is_tampered(tmp_path):
    _write_project(tmp_path)
    frozen = annotation_runtime.prepare_request(
        tmp_path,
        "p1",
        {
            "image_ids": ["image-1"],
            "labels": ["fire"],
            "model_config_id": "model-1",
        },
        runtime=False,
        model_configs=[_model()],
    )
    frozen["model_config_snapshot"]["model_name"] = "tampered-model"

    with pytest.raises(ValueError, match="AI_MODEL_CONFIG_SNAPSHOT_MISMATCH"):
        annotation_runtime.prepare_request(tmp_path, "p1", frozen, runtime=True)


def test_raw_provider_identifier_is_not_an_execution_owner(tmp_path):
    _write_project(tmp_path)

    with pytest.raises(ValueError, match="AI_MODEL_CONFIG_NOT_FOUND"):
        annotation_runtime.prepare_request(
            tmp_path,
            "p1",
            {
                "image_ids": ["image-1"],
                "labels": ["fire"],
                "provider_id": "temporary-http-provider",
            },
            runtime=False,
            model_configs=[_model()],
        )


def test_reference_labels_use_bounded_repository_batches_without_full_scan(tmp_path, monkeypatch):
    _write_project(tmp_path)
    reference_ids = [f"reference-{index:04d}" for index in range(1_001)]
    batches = []

    class FakeAnnotations:
        def __init__(self, _project_dir):
            pass

        def get_many(self, ids):
            batch = list(ids)
            batches.append(batch)
            assert len(batch) <= 500
            return {
                image_id: {
                    "image_id": image_id,
                    "boxes": [{"label": "fire", "class_id": 0}],
                }
                for image_id in batch
            }

    monkeypatch.setattr(
        "platform_core.annotation_repository.AnnotationRepository",
        FakeAnnotations,
    )

    frozen = annotation_runtime.prepare_request(
        tmp_path,
        "p1",
        {
            "image_ids": ["image-1"],
            "reference_image_ids": reference_ids,
            "model_config_id": "model-1",
        },
        runtime=False,
        model_configs=[_model()],
    )

    assert [len(batch) for batch in batches] == [500, 500, 1]
    assert frozen["reference_image_ids"] == reference_ids
    assert frozen["labels"] == ["fire"]
