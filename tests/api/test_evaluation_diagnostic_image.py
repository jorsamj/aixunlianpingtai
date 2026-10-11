from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _setup(monkeypatch, tmp_path: Path):
    import app as platform
    project_id = "evaluation-project"
    algorithm_id = "algo"
    version_id = "v1"
    digest = "a" * 64
    root = tmp_path / "projects" / project_id
    (root / "snapshots").mkdir(parents=True)
    (root / "snapshots" / f"{digest}.json").write_text(json.dumps({
        "snapshot_id": digest,
        "test_image_ids": ["test-image", "train-image"],
        "images": [
            {"image_id": "test-image", "content_sha256": "b" * 64},
            {"image_id": "train-image", "content_sha256": "c" * 64},
        ],
    }), encoding="utf-8")
    image = root / "readonly-test.jpg"
    image.write_bytes(b"frozen-image")
    version = {"id": version_id, "evaluation": {
        "status": "succeeded", "snapshot_id": digest,
        "error_samples": [{"image": "readonly-test.jpg", "fp_count": 1, "fn_count": 1}]
    }}
    monkeypatch.setattr(platform, "get_project", lambda _: {"id": project_id})
    monkeypatch.setattr(platform, "list_algorithms_internal", lambda _: [{
        "id": algorithm_id, "versions": [version]
    }])
    monkeypatch.setattr(platform, "project_dir", lambda _: root)
    rows = [
        {"id": "test-image", "stored_name": "readonly-test.jpg", "content_sha256": "b" * 64},
        {"id": "train-image", "stored_name": "train.jpg", "content_sha256": "c" * 64},
    ]
    class Repository:
        def __init__(self, root): self.root = root
        def get_many(self, ids): return [row for row in rows if row["id"] in ids]
    monkeypatch.setattr(platform, "MaterialRepository", Repository)
    class Manager:
        def material(self, image_id):
            assert image_id == "test-image"
            return {"id": image_id}
        def materialize(self, value):
            return SimpleNamespace(path=image)
    monkeypatch.setattr(platform, "storage_manager", lambda _: Manager())
    return platform, version, rows, root, image


def test_evaluation_image_is_read_only_and_exactly_bound_to_frozen_material(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    result = platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", "readonly-test.jpg")
    assert Path(result.path) == image
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("name", ["train.jpg", "other.jpg", "../readonly-test.jpg", ".."])
def test_test_preview_never_reads_unlisted_or_unsafe_paths(monkeypatch, tmp_path, name):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", name)
    assert ex.value.status_code == 404


def test_changed_frozen_image_fails_closed_before_file_read(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    rows[0]["content_sha256"] = "d" * 64
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert ex.value.status_code == 409


def test_missing_snapshot_fails_closed_and_does_not_use_current_training_pool(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    version["evaluation"]["snapshot_id"] = "0" * 64
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert ex.value.status_code == 409


def test_duplicate_source_filenames_are_not_ambiguously_served(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    rows[1]["stored_name"] = image.name
    rows[1]["content_sha256"] = "c" * 64
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert ex.value.status_code == 409


def test_20k_named_frozen_test_preview_only_fetches_one_material(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    snapshot_path = root / "snapshots" / ("a" * 64 + ".json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["images"][0]["stored_name"] = image.name
    snapshot["images"][1]["stored_name"] = "train.jpg"
    for index in range(20_000):
        image_id = f"test-other-{index:05d}"
        snapshot["test_image_ids"].append(image_id)
        snapshot["images"].append({
            "image_id": image_id, "stored_name": f"test-other-{index:05d}.jpg",
            "content_sha256": "d" * 64,
        })
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    original = platform.MaterialRepository
    read_ids = []
    class ObservedRepository(original):
        def get_many(self, ids):
            read_ids.append(tuple(ids))
            return super().get_many(ids)
    monkeypatch.setattr(platform, "MaterialRepository", ObservedRepository)

    result = platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert Path(result.path) == image
    assert read_ids == [("test-image",)]


def test_legacy_unnamed_frozen_test_preview_reads_bounded_batches(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    snapshot_path = root / "snapshots" / ("a" * 64 + ".json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    for index in range(1_201):
        image_id = f"legacy-{index:05d}"
        snapshot["test_image_ids"].append(image_id)
        snapshot["images"].append({"image_id": image_id, "content_sha256": "d" * 64})
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    original = platform.MaterialRepository
    calls = []
    class ObservedRepository(original):
        def get_many(self, ids):
            calls.append(tuple(ids))
            assert len(ids) <= 500
            return super().get_many(ids)
    monkeypatch.setattr(platform, "MaterialRepository", ObservedRepository)

    result = platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert Path(result.path) == image
    assert len(calls) == 3
    assert sum(len(ids) for ids in calls) == len(snapshot["test_image_ids"])
