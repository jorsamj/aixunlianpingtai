from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.online_feedback import build_supplement_candidate_set
from platform_core.remote_training_tasks import RemoteTrainingPrepareHandler
from platform_core.storage.models import ObjectMetadata
from platform_core.storage.source_repository import StorageSource, StorageSourceRepository
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


class FakeCredentials:
    def get(self, _reference):
        return {}


class FakeConfigRepository:
    def __init__(self, source_id):
        self.source_id = source_id

    def config(self):
        return {
            "schema_version": 1,
            "storage_source_id": self.source_id,
            "object_prefix": "model-assets",
            "auto_upload_enabled": True,
        }


class FakeModelArtifacts:
    def __init__(self, source_id):
        self.repository = FakeConfigRepository(source_id)


class FakeObjectProvider:
    def __init__(self):
        self.objects = {}
        self.upload_calls = []

    def exists(self, key):
        return str(key) in self.objects

    def upload(self, key, source, *, content_type="application/octet-stream", metadata=None):
        data = Path(source).read_bytes()
        self.objects[str(key)] = {
            "data": data,
            "content_type": content_type,
            "sha256": str((metadata or {}).get("sha256") or ""),
        }
        self.upload_calls.append((str(key), dict(metadata or {})))
        return self.stat(key)

    def stat(self, key):
        item = self.objects[str(key)]
        return ObjectMetadata(
            key=str(key),
            size_bytes=len(item["data"]),
            content_type=item["content_type"],
            sha256=item["sha256"],
        )


def _build_project(data_dir: Path):
    project_id = "project-remote-training"
    project = data_dir / "projects" / project_id
    (project / "uploads").mkdir(parents=True)
    (project / "annotations").mkdir()
    (project / "models").mkdir()
    (project / "jobs").mkdir()
    (project / "meta.json").write_text(
        json.dumps({
            "id": project_id,
            "labels": ["fire"],
            "label_meta": [{"code": "fire", "class_id": 0}],
        }),
        encoding="utf-8",
    )
    rows = []
    for index in range(5):
        image_id = f"image-{index}"
        path = project / "uploads" / f"{image_id}.jpg"
        Image.new("RGB", (64, 64), (20 * index, 10, 10)).save(path, format="JPEG")
        rows.append({
            "id": image_id,
            "dataset_id": "pool",
            "stored_name": path.name,
            "filename": path.name,
            "storage_source_id": "default_local",
            "storage_type": "local",
            "object_key": f"uploads/{path.name}",
            "width": 64,
            "height": 64,
            "size_bytes": path.stat().st_size,
            "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "processing_status": "processed",
            "annotated": True,
            "group_id": image_id,
        })
        (project / "annotations" / f"{image_id}.json").write_text(
            json.dumps({
                "image_id": image_id,
                "boxes": [{
                    "label": "fire",
                    "class_id": 0,
                    "x1": 5,
                    "y1": 5,
                    "x2": 40,
                    "y2": 40,
                }],
            }),
            encoding="utf-8",
        )
    (project / "images.json").write_text(json.dumps(rows), encoding="utf-8")
    (project / "algorithms.json").write_text(
        json.dumps([{
            "id": "algorithm-fire",
            "name": "fire",
            "versions": [],
        }]),
        encoding="utf-8",
    )
    # Initializes default_local for StorageManager materialization.
    StorageSourceRepository(data_dir / "storage" / "storage_sources.sqlite3")
    return project_id


def _runtime(data_dir: Path, project_id: str, *, supplement_candidate_set=None):
    runtime = data_dir / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    target_id = "train_remote_target"
    prep_id = "trainprep_train_remote_target"
    target_payload = {
        "schema_version": 3,
        "framework": "ultralytics",
        "target": "remote",
        "remote_input_state": "PREPARING",
        "remote_prepare_task_id": prep_id,
        "algorithm_asset_id": "algorithm-fire",
        "model": "yolo11n.pt",
        "split_mode": "independent_test_set",
        "train_image_ids": ["image-0", "image-1", "image-2", "image-3"],
        "test_image_ids": ["image-4"],
        "validation_percent": 25,
        "experiment_percent": None,
        "epochs": 3,
        "imgsz": 640,
        "batch": 4,
        "requested_device": "auto",
        "device": "auto",
    }
    if supplement_candidate_set is not None:
        target_payload["supplement_candidate_set"] = dict(supplement_candidate_set)
    artifacts.atomic_write_json(target_id, "payload.json", target_payload)
    repository.create(TaskRecord.new(
        target_id,
        project_id,
        TaskKind.TRAINING,
        "payload.json",
        "training:remote:scheduler",
        required_capabilities=("training.ultralytics",),
    ))
    artifacts.atomic_write_json(
        prep_id,
        "payload.json",
        {
            "schema_version": 1,
            "training_task_id": target_id,
            "project_id": project_id,
        },
    )
    repository.create(TaskRecord.new(
        prep_id,
        project_id,
        TaskKind.TRAINING_PREPARE,
        "payload.json",
        f"training-prepare:{project_id}",
        required_capabilities=("training.prepare",),
    ))
    return repository, artifacts, target_id, prep_id


def _remote_source():
    return StorageSource(
        id="training-object-store",
        name="Training Object Store",
        type="s3",
        config={"bucket": "training"},
        enabled=True,
    )


class FakeSources:
    def __init__(self, value):
        self.value = value

    def get(self, source_id):
        return self.value if str(source_id) == self.value.id else None


def test_remote_training_prepare_handler_builds_bundle_and_activates_target(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(data_dir, project_id)
    source = _remote_source()
    provider = FakeObjectProvider()
    handler = RemoteTrainingPrepareHandler(
        data_dir,
        sources=FakeSources(source),
        credentials=FakeCredentials(),
        provider_factory=lambda _project_id, _source, _secret: provider,
        model_artifacts=FakeModelArtifacts(source.id),
    )
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-prep-worker",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    )

    assert scheduler.run_once() is True

    prep = repository.get(prep_id)
    target = repository.get(target_id)
    assert prep is not None and prep.status is TaskStatus.SUCCEEDED
    assert target is not None and target.status is TaskStatus.QUEUED

    payload = artifacts.read_json(target_id, "payload.json")
    assert payload["remote_input_state"] == "READY"
    remote = payload["remote_execution"]
    assert remote["version"] == 1
    assert remote["task_kind"] == "TRAINING"
    assert remote["transport"] == "object-storage-v1"
    training = remote["training"]
    assert training["schema_version"] == 2
    assert training["framework"] == "ultralytics"
    assert training["snapshot_id"]
    assert len(training["dataset_revision_id"]) == 64
    assert training["model"]["type"] == "official"
    assert training["model"]["reference"] == "yolo11n.pt"
    bundle = training["bundle"]
    assert bundle["storage_source_id"] == source.id
    assert bundle["object_key"].startswith("training-bundles/")
    assert len(bundle["sha256"]) == 64
    assert bundle["size_bytes"] > 0
    assert bundle["member_count"] > 0
    assert bundle["verified_files"] == 5

    assert (artifacts.artifact_path(target_id, "snapshot.json")).is_file()
    assert (artifacts.artifact_path(target_id, "dataset-revision.json")).is_file()
    manifest = artifacts.read_json(target_id, "work/bundle/manifest.json")
    assert manifest["dataset_revision_id"] == training["dataset_revision_id"]
    assert manifest["dataset_revision_ref"] == "dataset-revision.json"
    assert (artifacts.artifact_path(target_id, "remote-training/training-bundle.zip")).is_file()
    assert provider.upload_calls
    prep_result = artifacts.read_json(prep_id, prep.result_ref)
    assert prep_result["training_task_id"] == target_id
    assert prep_result["status"] == "ready"
    assert prep_result["dataset_revision_id"] == training["dataset_revision_id"]
    assert "url" not in str(prep_result).lower()


def test_remote_training_prepare_failure_blocks_target_instead_of_leaving_it_queued(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(data_dir, project_id)
    source = _remote_source()
    handler = RemoteTrainingPrepareHandler(
        data_dir,
        sources=FakeSources(source),
        credentials=FakeCredentials(),
        provider_factory=lambda _project_id, _source, _secret: FakeObjectProvider(),
        model_artifacts=FakeModelArtifacts(""),
    )
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-prep-worker",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    )

    assert scheduler.run_once() is True

    prep = repository.get(prep_id)
    target = repository.get(target_id)
    assert prep is not None and prep.status is TaskStatus.FAILED
    assert target is not None
    assert target.status is TaskStatus.BLOCKED_BY_ENVIRONMENT
    assert target.stage == "remote_input_preparation_failed"
    assert "REMOTE_TRAINING_STORAGE_REQUIRED" in str(target.error)
    payload = artifacts.read_json(target_id, "payload.json")
    assert payload["remote_input_state"] == "PREPARING"
    assert "remote_execution" not in payload


def test_remote_training_prepare_freezes_feedback_subset_without_agent_feedback_dependency(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    project = data_dir / "projects" / project_id
    materials = MaterialRepository(project)
    material = materials.get("image-0")
    assert material is not None
    annotation = AnnotationRepository(project).upsert(
        "image-0",
        [{
            "id": "image-0-feedback",
            "label": "fire",
            "class_id": 0,
            "x1": 5, "y1": 5, "x2": 40, "y2": 40,
        }],
        "annotated",
    )
    candidate_set = build_supplement_candidate_set(
        {
            "status": "confirmed",
            "action": "supplement_data",
            "action_id": "a" * 64,
            "source": {
                "algorithm_id": "algorithm-fire",
                "version_id": "version-feedback",
            },
        },
        [{
            "eligible": True,
            "feedback_id": "feedback-image-0",
            "feedback_type": "correct",
            "material_id": "image-0",
            "candidate_digest": "b" * 64,
            "annotation_hash": annotation["content_digest"],
            "annotation_state": "annotated",
            "labels": ["fire"],
            "model_sha256": "c" * 64,
            "input_sha256": material["content_sha256"],
            "confirmed_at": "2026-09-19T00:00:00Z",
            "algorithm_id": "algorithm-fire",
            "version_id": "version-feedback",
        }],
        frozen_at="2026-09-19T00:01:00Z",
    )
    repository, artifacts, target_id, prep_id = _runtime(
        data_dir,
        project_id,
        supplement_candidate_set=candidate_set,
    )
    source = _remote_source()
    provider = FakeObjectProvider()
    handler = RemoteTrainingPrepareHandler(
        data_dir,
        sources=FakeSources(source),
        credentials=FakeCredentials(),
        provider_factory=lambda _project_id, _source, _secret: provider,
        model_artifacts=FakeModelArtifacts(source.id),
    )
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-prep-feedback-worker",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    )

    assert scheduler.run_once() is True
    assert repository.get(prep_id).status is TaskStatus.SUCCEEDED
    payload = artifacts.read_json(target_id, "payload.json")
    remote_training = payload["remote_execution"]["training"]
    provenance = remote_training["supplement_provenance"]
    assert provenance["candidate_set_id"] == candidate_set["candidate_set_id"]
    assert provenance["adopted_feedback_ids"] == ["feedback-image-0"]
    assert provenance["adopted_material_ids"] == ["image-0"]
    assert provenance["adopted_candidate_count"] == 1
    assert provenance["automatic_execution"] is False
    assert "supplement_candidate_set" not in remote_training

    snapshot = artifacts.read_json(target_id, "snapshot.json")
    revision = artifacts.read_json(target_id, "dataset-revision.json")
    assert snapshot["supplement_provenance"]["adoption_id"] == provenance["adoption_id"]
    assert revision["supplement_provenance"]["adoption_id"] == provenance["adoption_id"]
