from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from PIL import Image
import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.errors import PlatformError
from platform_core.material_repository import MaterialRepository
from platform_core.online_feedback import build_supplement_candidate_set
import platform_core.remote_training_tasks as remote_training_tasks_module
from platform_core.remote_training_tasks import (
    RemoteTrainingPreparationError,
    RemoteTrainingPrepareHandler,
)
from platform_core.storage.models import ObjectMetadata
from platform_core.storage.source_repository import StorageSource, StorageSourceRepository
from platform_core.task_runtime import (
    ArtifactStore,
    ExecutionFencedError,
    FencedTaskRepository,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
    WorkerContext,
)


class FakeCredentials:
    def get(self, _reference):
        return {}


@pytest.mark.parametrize('include_policy', [True, False])
def test_explicit_history_policy_rechecks_usage_and_freezes_robustness(tmp_path, include_policy):
    from types import SimpleNamespace
    from platform_core.training_material_usage import TrainingMaterialUsage
    data_dir = tmp_path / 'data'
    project_id = _build_project(data_dir)
    project = data_dir / 'projects' / project_id
    repository, artifacts, target_id, _prep_id = _runtime(data_dir, project_id)
    payload = artifacts.read_json(target_id, 'payload.json')
    payload.update(schema_version=4, train_labels=['fire'],
        robustness_policy={'mode': 'enabled', 'selection': {'mode': 'ratio', 'ratio': 100}})
    if include_policy:
        payload['history_policy'] = 'new_for_algorithm'
    index = TrainingMaterialUsage(repository)
    material = MaterialRepository(project).get('image-0')
    index.record_selected(project_id, 'algorithm-fire', 'prior', {'snapshot_id': 'prior-snapshot',
        'images': [{'image_id': 'image-0', 'role': 'train', 'content_sha256': material['content_sha256']}]})
    index.record_execution('prior', first_batch=True)
    handler = RemoteTrainingPrepareHandler(data_dir)
    updated = handler._freeze_request_contract(SimpleNamespace(artifacts=artifacts, repository=repository, run_owned=lambda operation: operation()),
        repository.get(target_id), payload)
    assert 'image-0' not in updated['train_image_ids']
    frozen = artifacts.read_json(target_id, updated['input_freeze_ref'])
    assert frozen['history_admission']['excluded_train_image_ids'] == ['image-0']
    assert frozen['robustness_policy']['enabled'] is True
    assert index.query_filter(project_id, 'algorithm-fire', [MaterialRepository(project).get('image-1')])['by_image_id']['image-1']['state'] == 'selected'


def test_usage_maintenance_dry_run_interrupt_and_resume_preserves_owners(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from platform_core.training_usage_maintenance import rebuild_owner_batch
    from platform_core.training_material_usage import TrainingMaterialUsage
    from platform_core.training_tasks import resolve_training_input_freeze
    from platform_core.training_splits import SplitMode, SplitRequest
    data_dir = tmp_path/'data'
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, _prep_id = _runtime(data_dir, project_id)
    payload = artifacts.read_json(target_id, 'payload.json')
    payload.update(schema_version=4, train_labels=['fire'])
    updated = RemoteTrainingPrepareHandler(data_dir)._freeze_request_contract(
        SimpleNamespace(artifacts=artifacts, repository=repository, run_owned=lambda fn: fn()),
        repository.get(target_id), payload)
    frozen = artifacts.read_json(target_id, updated['input_freeze_ref'])
    split = frozen['split']
    _rows, _schema, _manifest, snapshot = resolve_training_input_freeze(frozen, SplitRequest(
        mode=SplitMode(split['mode']), train_image_ids=tuple(split['train_image_ids']),
        test_image_ids=tuple(split['test_image_ids']), validation_percent=split['validation_percent'],
        experiment_percent=split['experiment_percent']), seed=split['seed'])
    artifacts.atomic_write_json(target_id, 'payload.json', updated)
    artifacts.atomic_write_json(target_id, 'snapshot.json', snapshot)
    job = data_dir/'projects'/project_id/'jobs'/target_id/'job.json'
    job.parent.mkdir(parents=True)
    job.write_text(json.dumps({'id': target_id, 'snapshot_id': snapshot['snapshot_id'],
        'training_started': True, 'status': 'FAILED'}))
    owner_task = repository.get(target_id)
    material_bytes = (data_dir/'projects'/project_id/'uploads'/'image-0.jpg').read_bytes()
    dry = rebuild_owner_batch(data_dir, project_id)
    assert dry['eligible_task_ids'] == [target_id]
    assert not (data_dir/'task_runtime'/'maintenance').exists()
    original = TrainingMaterialUsage.record_selected
    def interrupt_after_write(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError('simulated interruption')
    monkeypatch.setattr(TrainingMaterialUsage, 'record_selected', interrupt_after_write)
    with pytest.raises(RuntimeError, match='interruption'):
        rebuild_owner_batch(data_dir, project_id, apply=True)
    monkeypatch.setattr(TrainingMaterialUsage, 'record_selected', original)
    resumed = rebuild_owner_batch(data_dir, project_id, apply=True)
    assert resumed['complete_scan'] is True
    assert rebuild_owner_batch(data_dir, project_id, apply=True)['scanned'] == 0
    with closing_connection(repository.path) as database:
        assert database.execute('SELECT COUNT(*) FROM training_material_usage').fetchone()[0] == 5
    assert repository.get(target_id) == owner_task
    assert (data_dir/'projects'/project_id/'uploads'/'image-0.jpg').read_bytes() == material_bytes
    assert TrainingMaterialUsage(repository).query_filter(project_id, 'algorithm-fire',
        [MaterialRepository(data_dir/'projects'/project_id).get('image-0')])['by_image_id']['image-0']['state'] in {'possible','selected'}


def test_historical_test_observation_survives_removed_training_work_directory(tmp_path):
    from types import SimpleNamespace
    from platform_core.training_usage_maintenance import rebuild_owner_batch
    from platform_core.training_material_usage import TrainingMaterialUsage
    from platform_core.training_tasks import resolve_training_input_freeze
    from platform_core.training_splits import SplitMode, SplitRequest
    data_dir = tmp_path / 'data'
    project_id = _build_project(data_dir)
    repository, artifacts, task_id, _prep_id = _runtime(data_dir, project_id)
    payload = artifacts.read_json(task_id, 'payload.json')
    payload.update(schema_version=4, train_labels=['fire'])
    updated = RemoteTrainingPrepareHandler(data_dir)._freeze_request_contract(
        SimpleNamespace(artifacts=artifacts, repository=repository, run_owned=lambda fn: fn()),
        repository.get(task_id), payload)
    frozen = artifacts.read_json(task_id, updated['input_freeze_ref'])
    split = frozen['split']
    _, _, _, snapshot = resolve_training_input_freeze(frozen, SplitRequest(
        mode=SplitMode(split['mode']), train_image_ids=tuple(split['train_image_ids']),
        test_image_ids=tuple(split['test_image_ids']), validation_percent=split['validation_percent'],
        experiment_percent=split['experiment_percent']), seed=split['seed'])
    artifacts.atomic_write_json(task_id, 'payload.json', updated)
    artifacts.atomic_write_json(task_id, 'snapshot.json', snapshot)
    artifacts.atomic_write_json(task_id, 'result.json', {
        'snapshot_id': snapshot['snapshot_id'],
        'dataset_revision_id': snapshot['dataset_revision_id'],
        'training_report': {'test_result': {'status': 'succeeded', 'image_count': 1}},
    })
    # The original training directory/job.json is intentionally absent.
    with sqlite3.connect(repository.path) as db:
        db.execute("UPDATE tasks SET status='SUCCEEDED',result_ref='result.json' WHERE task_id=?", (task_id,))
    rebuild_owner_batch(data_dir, project_id, apply=True)
    index = TrainingMaterialUsage(repository)
    image = MaterialRepository(data_dir / 'projects' / project_id).get('image-4')
    fact = index.query_filter(project_id, 'algorithm-fire', [image], exclude_used=False)
    assert fact['by_image_id']['image-4']['benchmark_protected'] is True


def closing_connection(path):
    from contextlib import closing
    return closing(sqlite3.connect(path))


def test_external_training_preflight_preserves_canonical_failure_code(tmp_path, monkeypatch):
    class FailingService:
        def __init__(self, **_kwargs):
            pass

        def training_preflight(self, **_kwargs):
            raise PlatformError(
                "EXTERNAL_ALGORITHM_INACTIVE",
                "该外部算法已停用，不能训练",
                "algorithm-fire",
                "请先在新畅联恢复算法。",
                409,
            )

    monkeypatch.setattr(
        remote_training_tasks_module,
        "ExternalAlgorithmPlatformService",
        FailingService,
    )
    handler = RemoteTrainingPrepareHandler(tmp_path / "data")

    with pytest.raises(RemoteTrainingPreparationError) as captured:
        handler._refresh_external_algorithm(
            "project-1",
            {
                "id": "algorithm-fire",
                "source_type": "EXTERNAL",
                "provider_type": "CHANG_LIAN",
            },
        )

    assert captured.value.code == "EXTERNAL_ALGORITHM_INACTIVE"
    assert str(captured.value) == "该外部算法已停用，不能训练"
    assert captured.value.target_status is TaskStatus.FAILED


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
    # A prepared weight is shared by the control-plane staging path. The test
    # proves remote preparation transfers it as an object, never an official URL.
    (project / "models" / "yolo11n.pt").write_bytes(b"preinstalled-yolo11n-weight" * 128)
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


def test_remote_official_filename_never_becomes_agent_download_contract(tmp_path):
    project_id = _build_project(tmp_path)
    handler = RemoteTrainingPrepareHandler(tmp_path)
    with pytest.raises(RemoteTrainingPreparationError) as captured:
        handler._prepare_base_model(
            provider=FakeObjectProvider(),
            source_id="test-oss",
            project_id=project_id,
            task_id="train_remote_unprepared",
            payload={
                "framework": "ultralytics",
                "algorithm_asset_id": "algorithm-fire",
                "model": "yolo11n.pt",
            },
        )
    assert captured.value.code == "REMOTE_TRAINING_BASE_MODEL_NOT_PREPARED"


def _runtime(
    data_dir: Path,
    project_id: str,
    *,
    supplement_candidate_set=None,
    repository_type=TaskRepository,
):
    runtime = data_dir / "task_runtime"
    repository = repository_type(runtime / "tasks.sqlite3")
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
        "model": str(data_dir / "projects" / project_id / "models" / "yolo11n.pt"),
        "split_mode": "independent_test_set",
        "train_image_ids": ["image-0", "image-1", "image-2", "image-3"],
        "test_image_ids": ["image-4"],
        "validation_percent": 25,
        "experiment_percent": None,
        "epochs": 3,
        "imgsz": 640,
        "batch": 4,
        "resource_strategy": "auto",
        "resource_profile": "performance",
        "gpu_policy": "exclusive",
        "precision": "fp16",
        "time": 2.5,
        "requested_device": "auto",
        "device": "auto",
        "label_contract": {
            "schema_version": 1,
            "algorithm_id": "algorithm-fire",
            "effective_label_codes": ["fire"],
            "effective_label_schema": [
                {"code": "fire", "class_id": 0, "canonical_project_class_id": 0}
            ],
            "base_training_mode": "mother_model_init",
            "strict_resume": False,
            "optimizer_state_resumed": False,
        },
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


@pytest.mark.parametrize("schema_version", [3, 4])
def test_remote_training_prepare_handler_freezes_indices_and_activates_target(tmp_path, monkeypatch, schema_version):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(data_dir, project_id)
    if schema_version == 4:
        payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
        payload.update(schema_version=4, training_input_state="PREPARING", train_labels=["fire"])
        artifacts.atomic_write_json(target_id, "payload.json", payload)
    source = _remote_source()
    provider = FakeObjectProvider()
    handler = RemoteTrainingPrepareHandler(
        data_dir,
        sources=FakeSources(source),
        credentials=FakeCredentials(),
        provider_factory=lambda _project_id, _source, _secret: provider,
        model_artifacts=FakeModelArtifacts(source.id),
    )
    from contextlib import contextmanager
    original_fence = remote_training_tasks_module.material_annotation_lifecycle_fence
    original_refresh = handler._refresh_external_algorithm
    original_freeze = remote_training_tasks_module.freeze_training_inputs
    locked = False
    calls = []
    @contextmanager
    def tracked_fence(project):
        nonlocal locked
        with original_fence(project):
            locked = True
            try:
                yield
            finally:
                locked = False
    def refresh(*args):
        assert not locked, "external HTTP must not block canonical GT editing"
        calls.append("refresh")
        return original_refresh(*args)
    def freeze(*args, **kwargs):
        if schema_version == 4:
            assert locked, "canonical freeze must hold the annotation lifecycle fence"
        calls.append("freeze")
        return original_freeze(*args, **kwargs)
    monkeypatch.setattr(remote_training_tasks_module, "material_annotation_lifecycle_fence", tracked_fence)
    monkeypatch.setattr(remote_training_tasks_module, "freeze_training_inputs", freeze)
    monkeypatch.setattr(handler, "_refresh_external_algorithm", refresh)
    original_benchmark = handler._resolve_benchmark_reuse
    original_review = remote_training_tasks_module.validate_duplicate_review
    def benchmark(*args, **kwargs):
        assert locked, "benchmark GT validation and selection must share the freeze fence"
        return original_benchmark(*args, **kwargs)
    def review(*args, **kwargs):
        assert locked, "expected revisions must be validated within the selection fence"
        return original_review(*args, **kwargs)
    monkeypatch.setattr(handler, "_resolve_benchmark_reuse", benchmark)
    monkeypatch.setattr(remote_training_tasks_module, "validate_duplicate_review", review)
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-prep-worker",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    )

    assert scheduler.run_once() is True
    if schema_version == 4:
        assert calls[:2] == ["refresh", "freeze"]

    prep = repository.get(prep_id)
    target = repository.get(target_id)
    assert prep is not None and prep.status is TaskStatus.SUCCEEDED, prep.error if prep else "missing prep"
    assert target is not None and target.status is TaskStatus.QUEUED
    assert not artifacts.artifact_path(target_id, "work/bundle").exists()
    assert not artifacts.artifact_path(target_id, "remote-training/training-bundle.zip").exists()
    assert not any(key.startswith("training-bundles/") for key, _ in provider.upload_calls)

    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    assert payload["remote_input_state"] == "READY"
    remote = payload["remote_execution"]
    assert remote["version"] == 1
    assert remote["task_kind"] == "TRAINING"
    assert remote["transport"] == "object-storage-v1"
    training = remote["training"]
    assert training["schema_version"] == 3
    assert training["framework"] == "ultralytics"
    assert training["snapshot_id"]
    assert len(training["dataset_revision_id"]) == 64
    assert training["label_codes"] == ["fire"]
    assert training["label_schema"][0]["code"] == "fire"
    assert training["label_contract"]["algorithm_id"] == "algorithm-fire"
    assert training["label_contract"]["effective_label_codes"] == ["fire"]
    assert training["model"]["type"] == "object"
    assert training["model"]["file_name"] == "yolo11n.pt"
    assert training["model"]["size_bytes"] > 1024
    assert len(training["model"]["sha256"]) == 64
    assert any(key.startswith("training-input-models/") for key, _ in provider.upload_calls)
    assert training["params"]["runtime_stop_policy"] == "target_only"
    assert training["params"]["resource_strategy"] == "auto"
    assert training["params"]["resource_profile"] == "performance"
    assert training["params"]["gpu_policy"] == "exclusive"
    assert training["params"]["precision"] == "fp16"
    assert training["params"]["time"] == 2.5
    assert training["dataset_bytes"] > 0
    assert training["decoded_dataset_bytes"] == 5 * (640 ** 2) * 3
    assert training["inputs"] == {"type": "frozen-manifest-v1", "input_freeze_id": payload["input_freeze_id"]}
    assert "bundle" not in training
    assert artifacts.artifact_path(target_id, "snapshot.json").is_file()
    project_snapshot = data_dir / "projects" / project_id / "snapshots" / (training["snapshot_id"] + ".json")
    assert project_snapshot.is_file()
    assert json.loads(project_snapshot.read_text(encoding="utf-8")) == artifacts.read_json(target_id, "snapshot.json")
    assert artifacts.artifact_path(target_id, "dataset-revision.json").is_file()
    plan = artifacts.read_json(target_id, "input-plan/manifest.json")
    assert plan["snapshot_id"] == training["snapshot_id"]
    assert plan["materialization_state"] == "DEFERRED"
    assert not artifacts.artifact_path(target_id, "remote-training/training-bundle.zip").exists()
    assert provider.upload_calls
    prep_result = artifacts.read_json(prep_id, prep.result_ref)
    assert prep_result["training_task_id"] == target_id
    assert prep_result["status"] == "ready"
    assert prep_result["dataset_revision_id"] == training["dataset_revision_id"]
    assert "url" not in str(prep_result).lower()

    # The execution transport replays frozen GT and streams original bytes;
    # it must not materialize/cache an entire controller-side dataset.
    from types import SimpleNamespace
    from platform_core.remote_training_inputs import training_inputs
    transport = SimpleNamespace(data_dir=data_dir, task_artifacts=artifacts,
        storage_credentials_factory=lambda: FakeCredentials())
    frozen_gt = artifacts.read_json(target_id, artifacts.read_json(target_id, repository.get(target_id).payload_ref).get("input_freeze_ref") or "input-freeze.json")["images"][0]["boxes"]
    AnnotationRepository(data_dir / "projects" / project_id).upsert("image-0", [], "unannotated")
    manifest = training_inputs(transport, target, payload)
    assert manifest["freeze"]["images"][0]["boxes"] == frozen_gt
    assert manifest["freeze"]["source_input_freeze_id"] == payload["input_freeze_id"]
    assert all("stored_path" not in row and "path" not in row for row in manifest["freeze"]["images"])
    streamed = training_inputs(transport, target, payload, image_id="image-0")
    try:
        body = streamed["reader"].read()
    finally:
        streamed["reader"].close()
    assert hashlib.sha256(body).hexdigest() == streamed["sha256"]
    assert len(body) == streamed["size_bytes"]
    with pytest.raises(ValueError, match="not in frozen"):
        training_inputs(transport, target, payload, image_id="not-selected")
    assert not artifacts.artifact_path(target_id, "work/bundle").exists()


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
    assert target.stage == "training_input_preparation_failed"
    assert "REMOTE_TRAINING_STORAGE_REQUIRED" in str(target.error)
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    assert payload["remote_input_state"] == "PREPARING"
    assert "remote_execution" not in payload


def test_training_prepare_persists_all_scope_drift_issues_before_failure(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    project = data_dir / "projects" / project_id
    meta = json.loads((project / "meta.json").read_text(encoding="utf-8"))
    meta["labels"].append("smoke")
    meta["label_meta"].append({"code": "smoke", "class_id": 1})
    (project / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    AnnotationRepository(project).upsert(
        "image-3",
        [{
            "id": "image-3-smoke",
            "label": "smoke",
            "class_id": 1,
            "x1": 5,
            "y1": 5,
            "x2": 40,
            "y2": 40,
        }],
        "annotated",
        annotation_scope=["fire", "smoke"],
    )
    repository, artifacts, target_id, prep_id = _runtime(data_dir, project_id)
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload["schema_version"] = 4
    payload["training_input_state"] = "PREPARING"
    payload["train_labels"] = ["fire", "smoke"]
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    handler = RemoteTrainingPrepareHandler(data_dir)
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-prep-scope-drift",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    )

    assert scheduler.run_once() is True

    prep = repository.get(prep_id)
    target = repository.get(target_id)
    assert prep is not None and prep.status is TaskStatus.FAILED
    assert target is not None and target.status is TaskStatus.FAILED
    assert "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE" in str(target.error)
    manifest = artifacts.read_json(target_id, "input-compatibility/manifest.json")
    assert manifest["issue_count"] == 4
    assert manifest["required_label_codes"] == ["fire", "smoke"]
    page = artifacts.read_json(target_id, manifest["pages"][0]["ref"])
    assert len(page) == 4
    assert all(item["missing_label_codes"] == ["smoke"] for item in page)


def test_queued_prepare_refreezes_remaining_original_scope_and_archives_request(tmp_path):
    from types import SimpleNamespace
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    project = data_dir / "projects" / project_id
    repository, artifacts, target_id, _prep_id = _runtime(data_dir, project_id)
    materials = MaterialRepository(project)
    annotations = AnnotationRepository(project)
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    original = list(payload["train_image_ids"])
    payload.update(schema_version=4, train_labels=["fire"],
        expected_material_revision=materials.current_revision(),
        expected_annotation_revision=annotations.current_revision())
    materials.remove_many(["image-1"])
    annotations.remove(["image-1"])
    # An unrelated new image must never replace the removed requested identity.
    materials.upsert_many([{**materials.get("image-0"), "id": "outside"}])
    handler = RemoteTrainingPrepareHandler(data_dir)
    updated = handler._freeze_request_contract(
        SimpleNamespace(artifacts=artifacts, repository=repository, run_owned=lambda fn: fn()),
        repository.get(target_id), payload)
    assert updated["train_image_ids"] == ["image-0", "image-2", "image-3"]
    assert updated["input_selection_recheck"]["removed_image_ids"] == ["image-1"]
    assert updated["input_selection_recheck"]["requested_train_count"] == 4
    request = artifacts.read_json(target_id, "input-request-selection.json")
    assert request["train_image_ids"] == original
    frozen = artifacts.read_json(target_id, updated['input_freeze_ref'])
    assert frozen["input_freeze_id"] == updated["input_freeze_id"]
    assert "outside" not in updated["train_image_ids"]
    assert (project / "uploads/image-1.jpg").is_file()


def test_training_prepare_persists_revision_drift_error_without_creating_freeze(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(data_dir, project_id)
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, expected_material_revision=0, expected_annotation_revision=0)
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    scheduler = Scheduler(repository, artifacts, "prep-revision-drift",
        {TaskKind.TRAINING_PREPARE: RemoteTrainingPrepareHandler(data_dir)}, {"training.prepare"})
    assert scheduler.run_once() is True
    assert repository.get(target_id).status is TaskStatus.FAILED
    evidence = artifacts.read_json(target_id, "input-preparation-error.json", default={})
    assert evidence["code"] == "TRAINING_REVIEW_STALE"
    assert evidence["input_freeze_created"] is False
    assert evidence["task_id"] == target_id
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


def test_prepare_never_overwrites_freeze_published_before_payload_crash(tmp_path):
    from types import SimpleNamespace
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, _prep_id = _runtime(data_dir, project_id)
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, train_labels=["fire"])
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = SimpleNamespace(artifacts=artifacts, repository=repository, run_owned=lambda fn: fn())
    first = handler._freeze_request_contract(context, repository.get(target_id), payload)
    original = artifacts.read_json(target_id,first['input_freeze_ref'])
    MaterialRepository(data_dir / "projects" / project_id).remove_many(["image-1"])
    resumed = handler._freeze_request_contract(context, repository.get(target_id), payload)
    assert resumed == first
    assert artifacts.read_json(target_id,first['input_freeze_ref']) == original
    assert repository.get(target_id).payload_ref == 'payload.json'  # receipt is not a Task commit


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
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
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


def test_reclaimed_training_prepare_attempt_validates_and_activates_once(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(
        data_dir,
        project_id,
        repository_type=FencedTaskRepository,
    )
    first = repository.claim_next(
        "dead-preparer",
        [TaskKind.TRAINING_PREPARE],
        {"training.prepare"},
        lease_seconds=1,
    )
    assert first is not None and first.task.task_id == prep_id
    assert repository.release_expired("2999-01-01T00:00:00+00:00") == 1

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
        "recovery-preparer",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    )

    assert scheduler.run_once() is True
    prep = repository.get(prep_id)
    target = repository.get(target_id)
    assert prep is not None and prep.status is TaskStatus.SUCCEEDED, prep.error if prep else "missing"
    assert prep.attempt == 2
    assert target is not None and target.status is TaskStatus.QUEUED
    assert target.required_capabilities == ("training.ultralytics",)
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    assert payload["training_input_state"] == "READY"
    assert payload["remote_prepare_task_id"] == prep_id
    assert artifacts.read_json(prep_id, "result.json")["status"] == "ready"


def test_recovery_validates_ready_artifacts_without_reuploading_or_reactivating(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(
        data_dir,
        project_id,
        repository_type=FencedTaskRepository,
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
    first = repository.claim_next(
        "preparer-before-crash",
        [TaskKind.TRAINING_PREPARE],
        {"training.prepare"},
        lease_seconds=30,
    )
    assert first is not None
    context = WorkerContext(first.task, first, repository, artifacts, lease_seconds=30)
    status, result_ref = handler.run(context)
    assert status is TaskStatus.SUCCEEDED and result_ref == "result.json"
    upload_count = len(provider.upload_calls)
    activated = repository.get(target_id)
    assert activated is not None
    activated_contract = (activated.resource_key, activated.required_capabilities)

    # Simulate process death after durable parent publication but before the
    # preparation task itself was finished by Scheduler.
    assert repository.release_expired("2999-01-01T00:00:00+00:00") == 1
    Scheduler(
        repository,
        artifacts,
        "recovery-preparer",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    ).run_once()

    recovered = repository.get(prep_id)
    parent = repository.get(target_id)
    assert recovered is not None and recovered.status is TaskStatus.SUCCEEDED, (
        recovered.error if recovered else "missing preparation task"
    )
    assert recovered.attempt == 2
    assert parent is not None
    assert (parent.resource_key, parent.required_capabilities) == activated_contract
    assert len(provider.upload_calls) == upload_count
    assert artifacts.read_json(prep_id, "result.json")["status"] == "ready"


def test_recovery_rejects_corrupted_ready_freeze_instead_of_reusing_it(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(
        data_dir,
        project_id,
        repository_type=FencedTaskRepository,
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
    first = repository.claim_next(
        "preparer-before-corruption",
        [TaskKind.TRAINING_PREPARE],
        {"training.prepare"},
        lease_seconds=30,
    )
    assert first is not None
    context = WorkerContext(first.task, first, repository, artifacts, lease_seconds=30)
    assert handler.run(context)[0] is TaskStatus.SUCCEEDED
    frozen = artifacts.read_json(target_id, artifacts.read_json(target_id, repository.get(target_id).payload_ref).get("input_freeze_ref") or "input-freeze.json")
    frozen["images"][0]["boxes"][0]["x1"] = 0
    # Deliberate out-of-protocol corruption must fail SHA verification, never
    # fall back to the legacy mirror or rewind an already committed READY.
    import os
    frozen_ref = artifacts.read_json(target_id, repository.get(target_id).payload_ref)['input_freeze_ref']
    corrupt_path = artifacts.root / target_id / frozen_ref
    if os.name == 'nt': corrupt_path = Path('\\\\?\\' + str(corrupt_path))
    corrupt_path.write_text(json.dumps(frozen), encoding='utf-8')
    assert repository.release_expired("2999-01-01T00:00:00+00:00") == 1

    Scheduler(
        repository,
        artifacts,
        "recovery-preparer",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    ).run_once()

    recovered = repository.get(prep_id)
    parent = repository.get(target_id)
    assert recovered is not None and recovered.status is TaskStatus.FAILED
    assert "PAYLOAD_INTEGRITY_ERROR" in str(recovered.error)
    assert parent is not None and parent.status is TaskStatus.QUEUED
    assert parent.error is None


def test_fenced_training_preparer_cannot_fail_queued_parent(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(
        data_dir,
        project_id,
        repository_type=FencedTaskRepository,
    )
    lease = repository.claim_next(
        "stale-preparer",
        [TaskKind.TRAINING_PREPARE],
        {"training.prepare"},
    )
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)
    context.mark_lease_lost()
    handler = RemoteTrainingPrepareHandler(data_dir)

    with pytest.raises(ExecutionFencedError):
        handler.run(context)

    target = repository.get(target_id)
    assert target is not None and target.status is TaskStatus.QUEUED
    assert target.error is None


def test_transient_prepare_sqlite_error_does_not_fail_parent(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, _prep_id = _runtime(
        data_dir,
        project_id,
        repository_type=FencedTaskRepository,
    )
    lease = repository.claim_next(
        "busy-preparer",
        [TaskKind.TRAINING_PREPARE],
        {"training.prepare"},
    )
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)
    handler = RemoteTrainingPrepareHandler(data_dir)

    def raise_busy(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(handler, "_target", raise_busy)

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        handler.run(context)

    target = repository.get(target_id)
    assert target is not None and target.status is TaskStatus.QUEUED
    assert target.error is None


def test_cancelled_training_parent_is_not_reactivated_by_prepare_recovery(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(
        data_dir,
        project_id,
        repository_type=FencedTaskRepository,
    )
    first = repository.claim_next(
        "dead-preparer",
        [TaskKind.TRAINING_PREPARE],
        {"training.prepare"},
        lease_seconds=1,
    )
    assert first is not None
    assert repository.release_expired("2999-01-01T00:00:00+00:00") == 1
    repository.request_cancel(target_id)

    handler = RemoteTrainingPrepareHandler(data_dir)
    Scheduler(
        repository,
        artifacts,
        "recovery-preparer",
        {TaskKind.TRAINING_PREPARE: handler},
        {"training.prepare"},
    ).run_once()

    target = repository.get(target_id)
    assert target is not None and target.status is TaskStatus.CANCELLED
    assert target.required_capabilities == ("training.ultralytics",)
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    assert payload["remote_input_state"] == "PREPARING"


# GOV: a queued request is an exact candidate set, never a fresh project filter.
def _queued_recheck(materials,split):
    import platform_core.training_tasks as module
    fn=getattr(module,'revalidate_queued_training_selection',None)
    assert callable(fn),'queued preparation must revalidate only its original exact candidate IDs'
    return fn(materials,split)


def test_queued_selection_10000_to_9500_does_not_add_new_project_images(tmp_path):
    from platform_core.training_splits import SplitRequest,SplitMode
    materials=MaterialRepository(tmp_path/'projects'/'queued')
    original=tuple(f'image-{i:05d}' for i in range(10000))
    materials.upsert_many([{'id':key,'filename':key+'.jpg'} for key in original[500:]]+[{'id':'outside-original','filename':'outside.jpg'},{'id':'test-original','filename':'test.jpg'}])
    split=SplitRequest(SplitMode.INDEPENDENT_TEST_SET,original,('test-original',))
    effective,report=_queued_recheck(materials,split)
    assert effective.train_image_ids==original[500:]
    assert effective.test_image_ids==('test-original',)
    assert 'outside-original' not in effective.train_image_ids
    assert report['requested_train_count']==10000
    assert report['remaining_train_count']==9500
    assert len(report['removed_image_ids'])==500


@pytest.mark.parametrize('remaining,test_present,code',[(1,True,'TRAINING_SELECTION_INSUFFICIENT'),(3,False,'TRAINING_TEST_SELECTION_INSUFFICIENT')])
def test_queued_selection_refuses_insufficient_original_scope(tmp_path,remaining,test_present,code):
    from platform_core.training_splits import SplitRequest,SplitMode
    materials=MaterialRepository(tmp_path/'projects'/'queued')
    materials.upsert_many([{'id':f'image-{i}','filename':f'{i}.jpg'} for i in range(remaining)]+([{'id':'test','filename':'t.jpg'}] if test_present else []))
    split=SplitRequest(SplitMode.INDEPENDENT_TEST_SET,('image-0','image-1','image-2'),('test',))
    with pytest.raises(ValueError,match=code):_queued_recheck(materials,split)



def test_target_negative_receipts_survive_prepare_freeze_and_real_dataset(tmp_path):
    from types import SimpleNamespace
    from platform_core.training_label_tasks import resolve_training_label_contract, task_negative_identity, _ORIGINAL_SELECTED_PROJECT_IMAGES
    from platform_core.training_tasks import resolve_training_input_freeze, materialize_portable_dataset
    from platform_core.training_splits import SplitRequest, SplitMode
    data_dir=tmp_path/'data'; pid=_build_project(data_dir); project=data_dir/'projects'/pid
    meta=json.loads((project/'meta.json').read_text());meta['labels'].append('person');meta['label_meta'].append({'code':'person','class_id':1})
    (project/'meta.json').write_text(json.dumps(meta))
    annotations=AnnotationRepository(project)
    annotations.upsert('image-1',[],annotation_state='unannotated',annotation_scope=[])
    person={'label':'person','x1':5,'y1':5,'x2':40,'y2':40}
    annotations.upsert('image-2',[person],annotation_state='annotated',annotation_scope=['person'])
    annotations.upsert('image-3',[person,dict(person,label='fire')],annotation_state='annotated',annotation_scope=['person','fire'])
    repository,artifacts,target_id,_=_runtime(data_dir,pid)
    payload=artifacts.read_json(target_id,repository.get(target_id).payload_ref);payload.update(schema_version=4,train_labels=['fire'],validation_percent=50,seed=1)
    algorithm={'id':'algorithm-fire','versions':[]}
    contract=resolve_training_label_contract(data_dir,project,payload,algorithm,require_positive_evidence=False)
    originals=_ORIGINAL_SELECTED_PROJECT_IMAGES(MaterialRepository(project),project,payload['train_image_ids'])
    evidences=[task_negative_identity(row,contract) for row in originals if row['id'] in ['image-1','image-2']]
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.negative_pool import NegativePool
    from platform_core.training_material_picker_api import training_material_picker_router
    from platform_core.training_selection_reference import freeze_selection, read_selection, selection_context
    pool=NegativePool(MaterialRepository(project))
    category=pool.category(name='reflections')['id']
    pool.members(['image-1','image-2'],category_ids=[category])
    assert pool.candidate_ids(algorithm_id='algorithm-fire')==[]
    # Project-level membership alone no longer satisfies a target-algorithm
    # negative filter; the legal flow must also associate the algorithm.
    pool.members(['image-1','image-2'], algorithm_id='algorithm-fire')
    assert pool.candidate_ids(algorithm_id='algorithm-fire')==['image-1','image-2']
    source=freeze_selection(data_dir,selection_context(data_dir,pid,payload),
                            [i for i in payload['train_image_ids'] if i != 'image-2'])
    app=FastAPI()
    app.include_router(training_material_picker_router(lambda p:{'id':p} if p==pid else None,
        lambda:data_dir,algorithm_provider=lambda p,a:algorithm if a=='algorithm-fire' else None,
        actor_provider=lambda request, project_id:{'actor_id':'test'}))
    endpoint=f'/api/v62/projects/{pid}/training-materials/selection-union'
    client=TestClient(app)
    confirmation={**payload, 'train_image_ids':[], 'image_ids':['image-1','image-2'],
                  'rebind_train_reference':source['selection_ref']}
    preview=client.post(endpoint.replace('selection-union','negative-preview'),json=confirmation)
    assert preview.status_code==200,preview.text
    assert preview.json()['pending_count']==2
    confirm_url=endpoint.replace('selection-union','confirm-negatives')
    confirmed=client.post(confirm_url,json={**confirmation,'confirmed':True,'proof_digest':preview.json()['proof_digest']})
    assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()['confirmed_count']==2
    assert confirmed.json()['count']==source['count']
    assert confirmed.json()['selection_ref']!=source['selection_ref']
    request={**payload,'positive_ref':confirmed.json()['selection_ref'],'negative_ids':['image-1','image-2']}
    assert client.post(endpoint,json={**request,'test_image_ids':['image-2']}).status_code==422
    frozen_negatives=client.post(endpoint.replace('union','reference'),json={
        **payload, 'negative_pool_only':True, 'negative_category_ids':[category],
        'sample_role':'confirmed_negative', 'history_policy':payload.get('history_policy','new_for_algorithm'),
    })
    assert frozen_negatives.status_code==200,frozen_negatives.text
    assert frozen_negatives.json()['count']==2
    assert client.post(endpoint,json={**request,'positive_ref':frozen_negatives.json()['selection_ref']}).status_code==422
    paired=client.post(endpoint,json={**request,'negative_ids':[],
        'negative_ref':frozen_negatives.json()['selection_ref']})
    assert paired.status_code==200,paired.text
    assert paired.json()['count']==len(payload['train_image_ids'])
    from uuid import uuid4
    revisions = client.get(endpoint.replace('selection-union', 'revision'),
                           params={'algorithm_asset_id': 'algorithm-fire'}).json()
    request.update(request_id=str(uuid4()), expected_revisions=revisions)
    stale = {**revisions, 'annotation_revision': -1}
    assert client.post(endpoint, json={**request, 'expected_revisions': stale}).status_code == 409
    merged=client.post(endpoint,json=request)
    assert merged.status_code==200,merged.text
    assert client.post(endpoint, json=request).json() == merged.json()
    different = {**request, 'negative_ids': ['image-1']}
    assert client.post(endpoint, json=different).status_code == 422
    assert client.post(endpoint, json={**different, 'request_id': str(uuid4())}).json()['selection_ref'] != merged.json()['selection_ref']
    assert set(merged.json())=={'selection_ref','count'}
    payload['train_selection_ref']=merged.json()['selection_ref']
    payload['train_image_ids']=read_selection(data_dir,payload['train_selection_ref'],selection_context(data_dir,pid,payload))
    assert merged.json()['count']==len(payload['train_image_ids'])
    from platform_core.training_compatibility import evaluate_training_compatibility
    assert not evaluate_training_compatibility(data_dir,project,payload,algorithm).issues
    before=annotations.get_many(payload['train_image_ids']);source_bytes={r['id']:(project/'uploads'/r['stored_name']).read_bytes() for r in originals}
    updated=RemoteTrainingPrepareHandler(data_dir)._freeze_request_contract(SimpleNamespace(artifacts=artifacts,repository=repository,run_owned=lambda operation:operation()),repository.get(target_id),payload)
    frozen=artifacts.read_json(target_id,updated['input_freeze_ref']);split=frozen['split']
    rows,schema,manifest,snapshot=resolve_training_input_freeze(frozen,SplitRequest(mode=SplitMode(split['mode']),train_image_ids=tuple(split['train_image_ids']),test_image_ids=tuple(split['test_image_ids']),validation_percent=split['validation_percent'],experiment_percent=split['experiment_percent']),seed=split['seed'])
    assert {r['id'] for r in rows} >= {'image-1','image-2','image-3'}
    snapshot_by_id={r['image_id']:r for r in snapshot['images']}
    from platform_core.training_reader_views import _split_sample_evidence
    distribution=_split_sample_evidence(snapshot,snapshot['snapshot_id'])
    assert distribution
    negative_counts=frozen['input_quality']['class_coverage']['role_confirmed_negative_image_counts']
    assert sum(negative_counts.values())==2
    for role in ('train','validation','test'):
        assert negative_counts[role]==sum(snapshot_by_id[i]['box_count']==0 for i in manifest.ids[role])
        assert distribution[role]['confirmed_negative']==negative_counts[role]
    assert snapshot_by_id['image-1']['task_negative_confirmation']['receipt_id']==evidences[0]['receipt_id']
    output=materialize_portable_dataset(tmp_path/'actual-task',snapshot,rows,lambda row:project/'uploads'/row['stored_name'],safety_reserve_bytes=0)
    for iid in ['image-1','image-2','image-3']:
        role=snapshot_by_id[iid]['role'];text=(output/f'dataset/labels/{role}/{iid}.txt').read_text()
        assert text.startswith('0 ') if iid=='image-3' else text==''
        assert (output/f'dataset/images/{role}/{iid}.jpg').read_bytes()==source_bytes[iid]
    assert annotations.get_many(payload['train_image_ids'])==before
    import yaml
    exported=yaml.safe_load((output/'dataset/data.yaml').read_text())
    assert exported['names']=={0:'fire'}
    assert exported['train']=='images/train' and exported['val']=='images/validation'
    assert 'test' not in exported
    pool.members(['image-3'])
    assert client.post(endpoint,json=request).status_code==409


def test_training_publication_claim_anchor_and_historical_formal_test(tmp_path, monkeypatch):
    from platform_core.training_execution_inputs import anchor_execution, read_execution_inputs
    from platform_core.training_material_usage import assert_frozen_formal_test
    from platform_core.task_runtime.payload_publications import VERSION_REF
    data_dir=tmp_path/'data'
    project_id=_build_project(data_dir)
    repository,artifacts,target_id,prep_id=_runtime(data_dir,project_id,repository_type=FencedTaskRepository)
    request=artifacts.read_json(target_id,'payload.json')
    request.update(schema_version=4,training_input_state='PREPARING',train_labels=['fire'])
    artifacts.atomic_write_json(target_id,'payload.json',request)
    source=_remote_source()
    provider=FakeObjectProvider()
    handler=RemoteTrainingPrepareHandler(data_dir,sources=FakeSources(source),credentials=FakeCredentials(),
        provider_factory=lambda *_:provider,model_artifacts=FakeModelArtifacts(source.id))
    phases=[]
    actual_publish=repository.publish_training_payload
    def record_phase(parent_id, **kwargs):
        phase=kwargs['publication'].identity.data['phase']
        if phase=='training.ready':
            current=repository.get(parent_id)
            prior=artifacts.read_payload_publication_receipt(parent_id,VERSION_REF.fullmatch(current.payload_ref)['operation'])
            assert prior.identity.data['phase']=='training.freeze'
        result=actual_publish(parent_id,**kwargs)
        phases.append(phase)
        if phase=='training.freeze':
            assert result.task.required_capabilities==('training.input.ready',)
        return result
    monkeypatch.setattr(repository,'publish_training_payload',record_phase)
    assert Scheduler(repository,artifacts,'preparer',{TaskKind.TRAINING_PREPARE:handler},{'training.prepare'}).run_once()
    assert phases==['training.freeze','training.ready']
    assert repository.get(prep_id).status is TaskStatus.SUCCEEDED
    lease=repository.claim_next('trainer',[TaskKind.TRAINING],{'training.ultralytics'})
    assert lease is not None and lease.task.attempt==1
    context=WorkerContext(lease.task,lease,repository,artifacts)
    payload=artifacts.read_payload_version(target_id,lease.task.payload_ref).data
    anchor_ref=anchor_execution(context,payload)
    anchor,bound,docs=read_execution_inputs(artifacts,project_id,target_id,1,lease.task.payload_ref,anchor_ref)
    assert bound==payload and anchor['attempt']==lease.task.attempt
    assert_frozen_formal_test(data_dir/'projects'/project_id,target_id,payload['snapshot_id'],
        execution_attempt=1,execution_payload_ref=lease.task.payload_ref,execution_anchor_ref=anchor_ref)
    with repository._connect() as database:
        database.execute("UPDATE tasks SET attempt=2,payload_ref='future-input.json' WHERE task_id=?",(target_id,))
    assert_frozen_formal_test(data_dir/'projects'/project_id,target_id,payload['snapshot_id'],
        execution_attempt=1,execution_payload_ref=lease.task.payload_ref,execution_anchor_ref=anchor_ref)
    with pytest.raises((ValueError,FileNotFoundError)):
        assert_frozen_formal_test(data_dir/'projects'/project_id,target_id,payload['snapshot_id'],
            execution_attempt=2,execution_payload_ref=lease.task.payload_ref,
            execution_anchor_ref='execution-inputs/v1/attempt-2.json')
    with pytest.raises(ValueError,match='execution anchor required'):
        assert_frozen_formal_test(data_dir/'projects'/project_id,target_id,payload['snapshot_id'])
    with repository._connect() as database:
        database.execute("UPDATE tasks SET status='FAILED' WHERE task_id=?",(target_id,))
    assert repository.delete_terminal(target_id,project_id=project_id,kind=TaskKind.TRAINING)
    assert_frozen_formal_test(data_dir/'projects'/project_id,target_id,payload['snapshot_id'],
        execution_attempt=1,execution_payload_ref=lease.task.payload_ref,execution_anchor_ref=anchor_ref)



def test_ready_receipt_before_database_commit_resumes_in_new_preparation_lease(tmp_path,monkeypatch):
    data_dir=tmp_path/'data'
    project_id=_build_project(data_dir)
    repository,artifacts,target_id,prep_id=_runtime(data_dir,project_id,repository_type=FencedTaskRepository)
    source=_remote_source()
    provider=FakeObjectProvider()
    handler=RemoteTrainingPrepareHandler(data_dir,sources=FakeSources(source),credentials=FakeCredentials(),
        provider_factory=lambda *_:provider,model_artifacts=FakeModelArtifacts(source.id))
    first=repository.claim_next('first',[TaskKind.TRAINING_PREPARE],{'training.prepare'})
    context=WorkerContext(first.task,first,repository,artifacts)
    actual=repository.publish_training_payload
    proposals=[]
    def fail_ready(parent_id,**kwargs):
        if kwargs['publication'].identity.data['phase']=='training.ready':
            proposals.append(kwargs['publication'])
            raise sqlite3.OperationalError('database is locked')
        return actual(parent_id,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(repository,'publish_training_payload',fail_ready)
        with pytest.raises(sqlite3.OperationalError):handler.run(context)
    parent=repository.get(target_id)
    assert parent.required_capabilities==('training.input.ready',)
    assert parent.status is TaskStatus.QUEUED and len(proposals)==1
    uploads=list(provider.upload_calls)
    repository.release_expired('2999-01-01T00:00:00+00:00')
    second=repository.claim_next('second',[TaskKind.TRAINING_PREPARE],{'training.prepare'})
    assert second is not None and second.task.attempt==2
    successor=WorkerContext(second.task,second,repository,artifacts)
    assert handler.recover(successor)[0] is TaskStatus.SUCCEEDED
    assert repository.get(target_id).payload_ref==proposals[0].version.payload_ref
    assert provider.upload_calls==uploads
    with pytest.raises(ExecutionFencedError):handler.run(context)


def test_fixed_zip_references_prepare_and_materialize_exact_three_roles(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app as app_module
    from platform_core.snapshots import persist_snapshot
    from platform_core.training_material_picker_api import training_material_picker_router
    from platform_core.training_reader_views import report_display
    from platform_core.training_selection_reference import validate_payload_references
    from platform_core.training_splits import SplitRequest, build_split_manifest
    from platform_core.training_tasks import materialize_portable_dataset, resolve_training_input_freeze

    data = tmp_path / 'data'
    pid = _build_project(data)
    project = data / 'projects' / pid
    repo, artifacts, task_id, _ = _runtime(data, pid)
    store = MaterialRepository(project)
    gt = AnnotationRepository(project)
    gt.upsert('image-1', [], annotation_state='confirmed_empty', annotation_scope=['fire'])
    gt.upsert('image-4', [], annotation_state='unannotated', annotation_scope=[])
    before_gt = gt.get_many([f'image-{i}' for i in range(5)])
    roles = ('train', 'train', 'val', 'test', 'unassigned')
    for index, role in enumerate(roles):
        folder = 'images/' + role
        store.patch({f'image-{index}': {'import_batch_id': 'zip-one', 'source_task_id': 'zip-one',
            'zip_folder_source': {'job_id': 'zip-one', 'source_zip_sha256': 'a'*64, 'source_scan_digest': 'b'*64,
                'rule_digest': 'c'*64, 'source_path': folder + ('/negative.jpg' if index == 1 else '/same.jpg'),
                'classification_status': 'applied', 'usage_intent': role, 'folder_key': folder}}})
    payload = artifacts.read_json(task_id, 'payload.json')
    for field in ('train_image_ids', 'test_image_ids'):
        payload.pop(field)
    payload.update(split_mode='fixed_zip_train_val_test', validation_percent=None, experiment_percent=None,
                   zip_source_job_ids=['zip-one'], train_labels=['fire'])
    app = FastAPI()
    app.include_router(training_material_picker_router(lambda p: {'id':p} if p==pid else None,
        lambda: data, algorithm_provider=lambda p,a: {'id':a,'versions':[]} if a=='algorithm-fire' else None))
    client = TestClient(app)
    base = f'/api/v62/projects/{pid}/training-materials/zip-fixed-'
    assert client.get(base+'sources').json()['items'][0]['job_id'] == 'zip-one'
    missing = client.post(base+'split-preview', json={**payload,'zip_source_job_ids':['foreign-job']})
    assert missing.json()['issue_count'] > 0 and 'preview_digest' not in missing.json()
    preview = client.post(base+'split-preview', json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()['issue_count'] == 0, preview.text
    assert preview.json()['unassigned'] == 1
    assert preview.json()['roles']['train']['confirmed_negative'] == 1
    intent = {**payload, 'preview_digest': preview.json()['preview_digest'], 'request_id': str(uuid4())}
    assert client.post(base+'split-freeze', json={**intent,'preview_digest':'stale'}).status_code == 409
    refs = client.post(base+'split-freeze', json=intent)
    assert refs.status_code == 200, refs.text
    assert client.post(base+'split-freeze', json=intent).json() == refs.json()
    monkeypatch.setattr(app_module, 'DATA_DIR', data)
    request = app_module.TrainReq.model_validate({**payload, **refs.json()})
    for bad in ({'benchmark_scope_id':'old'}, {'validation_percent':20},
                {'validation_selection_ref': refs.json()['test_selection_ref']}):
        with pytest.raises(ValueError):
            app_module._explicit_training_split(app_module.TrainReq.model_validate({**payload, **refs.json(), **bad}), pid)
    split = app_module._explicit_training_split(request, pid)
    payload.update(refs.json(), train_image_ids=list(split.train_image_ids),
                   validation_image_ids=list(split.validation_image_ids), test_image_ids=list(split.test_image_ids))
    context = SimpleNamespace(artifacts=artifacts, repository=repo, run_owned=lambda run: run())
    updated = RemoteTrainingPrepareHandler(data)._freeze_request_contract(context, repo.get(task_id), payload)
    frozen = artifacts.read_json(task_id, updated['input_freeze_ref'])
    assert frozen['zip_source_proof']['jobs']['zip-one']['rule_digest'] == 'c'*64
    rows, _, manifest, snapshot = resolve_training_input_freeze(frozen, split, seed=0)
    expected = {'train':('image-0','image-1'), 'validation':('image-2',), 'test':('image-3',)}
    assert manifest.ids == expected
    assert build_split_manifest(rows, split, seed=456).ids == expected
    with pytest.raises(ValueError, match='HISTORY_EXPOSURE'):
        build_split_manifest(rows, split, seed=0, forbidden_test_image_ids=('image-3',))
    damaged = {**frozen, 'zip_source_proof':{}}
    with pytest.raises(ValueError, match='digest mismatch'):
        resolve_training_input_freeze(damaged, split, seed=0)
    for field, value, pattern in [('source_group_id','same-source','leakage'),
                                  ('content_sha256',rows[0]['content_sha256'],'leakage')]:
        broken = [dict(row) for row in rows]
        broken[0][field] = broken[2][field] = value
        with pytest.raises(ValueError, match=pattern):
            build_split_manifest(broken, split, seed=0)
    bundle = materialize_portable_dataset(tmp_path/'task',snapshot,rows,
                                          lambda row: project/'uploads'/row['stored_name'],safety_reserve_bytes=0)
    for role, expected_ids in expected.items():
        assert tuple(sorted(path.stem for path in (bundle/'dataset/images'/role).glob('*.jpg'))) == expected_ids
    assert (bundle/'dataset/labels/train/image-1.txt').read_bytes() == b''
    assert (bundle/'evaluation/ground_truth/test/image-3.txt').read_text().startswith('0 ')
    assert 'val: images/validation' in (bundle/'dataset/data.yaml').read_text()
    assert 'test:' not in (bundle/'dataset/data.yaml').read_text()
    assert gt.get_many([f'image-{i}' for i in range(5)]) == before_gt
    persist_snapshot(project/'snapshots',snapshot)
    artifacts.atomic_write_json(task_id,'payload.json',updated)
    display = report_display(task_id,repo.get(task_id),artifacts,project/'jobs'/task_id/'job.json')
    assert display['fixed_zip_split']['state'] == 'VERIFIED'
    assert display['fixed_zip_split']['counts']['validation'] == 1
    with sqlite3.connect(repo.path) as db:
        assert dict(db.execute('SELECT image_id,role FROM training_material_usage WHERE task_id=?',(task_id,))) == {
            image:role for role, ids in expected.items() for image in ids}
    store.patch({'image-2': {'source_available':False}})
    with pytest.raises(ValueError):
        validate_payload_references(data,pid,payload)

# --- W11/W12 training lifecycle closure (P0-1 freezes, P0-3 base ancestry) ---

def _freeze_context(artifacts, repository):
    from types import SimpleNamespace
    return SimpleNamespace(artifacts=artifacts, repository=repository,
                           run_owned=lambda operation: operation())


def test_freeze_retry_after_publication_interruption_replays_fixed_identity(tmp_path, monkeypatch):
    """Evidence written before a crash must replay, never be overwritten."""
    from platform_core.task_runtime.payload_publications import EVIDENCE_REF
    from platform_core.training_tasks import (
        _training_input_freeze_digest,
        resolve_training_input_freeze,
    )
    from platform_core.training_splits import SplitMode, SplitRequest

    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, _prep_id = _runtime(data_dir, project_id)
    payload = artifacts.read_json(target_id, "payload.json")
    payload.update(schema_version=4, train_labels=["fire"])
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = _freeze_context(artifacts, repository)

    def interrupted(*_args, **_kwargs):
        raise RuntimeError("simulated process death after immutable evidence write")

    with monkeypatch.context() as patch:
        patch.setattr(remote_training_tasks_module, "publication", interrupted)
        with pytest.raises(RuntimeError, match="simulated process death"):
            handler._freeze_request_contract(context, repository.get(target_id), payload)
    evidence_root = artifacts.root / target_id / "evidence-versions" / "v1"
    original_evidence = {
        path.name: path.read_bytes()
        for path in evidence_root.iterdir() if path.is_file()
    }
    assert original_evidence
    assert artifacts.artifact_path(target_id, "input-request-selection.json").is_file()
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()

    updated = handler._freeze_request_contract(context, repository.get(target_id), payload)
    refs = {key: str(updated[key]) for key in
            ("input_freeze_ref", "snapshot_ref", "dataset_revision_ref")}
    assert all(EVIDENCE_REF.fullmatch(value) for value in refs.values()), refs
    frozen = artifacts.read_json(target_id, refs["input_freeze_ref"])
    snapshot = artifacts.read_json(target_id, refs["snapshot_ref"])
    revision = artifacts.read_json(target_id, refs["dataset_revision_ref"])
    assert frozen["input_freeze_id"] == _training_input_freeze_digest(frozen)
    assert snapshot["snapshot_id"] == frozen["snapshot_id"] == updated["snapshot_id"]
    assert snapshot["dataset_revision_id"] == frozen["dataset_revision_id"] \
        == revision["dataset_revision_id"] == updated["dataset_revision_id"]

    split = frozen["split"]
    _rows, _schema, _manifest, reproduced = resolve_training_input_freeze(
        frozen,
        SplitRequest(mode=SplitMode(split["mode"]),
                     train_image_ids=tuple(split["train_image_ids"]),
                     test_image_ids=tuple(split["test_image_ids"]),
                     validation_percent=split["validation_percent"],
                     experiment_percent=split["experiment_percent"]),
        seed=split["seed"],
    )
    assert reproduced["snapshot_id"] == updated["snapshot_id"]
    # The fixed publication identity is intact and no first-attempt receipt leaked.
    assert len(list((artifacts.root / target_id / "payload-publications" / "v1").iterdir())) == 1
    for name, raw in original_evidence.items():
        path = evidence_root / name
        assert path.is_file() and path.read_bytes() == raw
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


def test_legacy_unbound_freeze_evidence_fails_with_explicit_code_and_is_preserved(tmp_path):
    """A legacy half-commit cannot be replayed, so it fails closed untouched."""
    from platform_core.task_runtime import FencedTaskRepository, WorkerContext

    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    repository, artifacts, target_id, prep_id = _runtime(
        data_dir, project_id, repository_type=FencedTaskRepository)
    payload = artifacts.read_json(target_id, "payload.json")
    payload.update(schema_version=4, train_labels=["fire"])
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    legacy_freeze = {"schema_version": 1, "snapshot_id": "legacy-unbound",
                     "input_freeze_id": "legacy-half-commit"}
    artifacts.atomic_write_json(target_id, "input-freeze.json", legacy_freeze)
    original_bytes = artifacts.artifact_path(target_id, "input-freeze.json").read_bytes()
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = _freeze_context(artifacts, repository)

    with pytest.raises(RemoteTrainingPreparationError) as direct:
        handler._freeze_request_contract(context, repository.get(target_id), payload)
    assert direct.value.code == "TRAINING_FREEZE_PUBLICATION_INCOMPLETE"
    assert artifacts.artifact_path(target_id, "input-freeze.json").read_bytes() == original_bytes
    assert not artifacts.artifact_path(target_id, "input-request-selection.json").exists()

    lease = repository.claim_next("legacy-preparer", [TaskKind.TRAINING_PREPARE],
                                  {"training.prepare"})
    assert lease is not None
    with pytest.raises(RemoteTrainingPreparationError) as raised:
        handler.run(WorkerContext(lease.task, lease, repository, artifacts))
    assert raised.value.code == "TRAINING_FREEZE_PUBLICATION_INCOMPLETE"
    parent = repository.get(target_id)
    assert parent is not None and parent.status is TaskStatus.FAILED
    assert "TRAINING_FREEZE_PUBLICATION_INCOMPLETE" in str(parent.error)
    evidence = artifacts.read_json(target_id, "input-preparation-error.json")
    assert evidence["code"] == "TRAINING_FREEZE_PUBLICATION_INCOMPLETE"
    assert evidence["input_freeze_created"] is True
    assert artifacts.artifact_path(target_id, "input-freeze.json").read_bytes() == original_bytes


def _seed_algorithm_versions(data_dir, project_id, versions, current_version_id):
    from platform_core.algorithms import save_algorithms
    path = data_dir / "projects" / project_id / "algorithms.json"
    save_algorithms(path, [{
        "id": "algorithm-fire",
        "name": "fire",
        "source_type": "LOCAL",
        "current_version_id": current_version_id,
        "versions": versions,
    }])


def _iteration_version(project, version_id, created_at):
    weight = project / f"{version_id}.pt"
    weight.write_bytes(f"verified-checkpoint-{version_id}".encode())
    return {
        "id": version_id,
        "version_name": version_id,
        "created_at": created_at,
        "finished_at": created_at,
        "stored_path": str(weight),
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
        "label_schema": [{"code": "fire", "class_id": 0}],
    }


def test_create_time_reference_version_blocks_silent_iteration_base_drift(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir)
    project = data_dir / "projects" / project_id
    repository, artifacts, target_id, _prep_id = _runtime(data_dir, project_id)
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = _freeze_context(artifacts, repository)
    v1 = _iteration_version(project, "version-v1", "2026-01-01T00:00:00+00:00")
    _seed_algorithm_versions(data_dir, project_id, [v1], "version-v1")
    base_payload = artifacts.read_json(target_id, "payload.json")
    base_payload.update(schema_version=4, train_labels=["fire"])

    fenced_payload = {**base_payload, "reference_version_id": "version-v1"}
    artifacts.atomic_write_json(target_id, "payload.json", fenced_payload)
    updated = handler._freeze_request_contract(
        context, repository.get(target_id), fenced_payload)
    assert updated["base_version_id"] == "version-v1"
    assert updated["reference_version_id"] == "version-v1"
    assert updated["base_version_ancestry_verified"] is True

    v2 = _iteration_version(project, "version-v2", "2026-02-01T00:00:00+00:00")
    from platform_core.algorithms import attach_version
    attach_version(data_dir / "projects" / project_id / "algorithms.json",
                   "algorithm-fire", v2)

    drifted_id = "train_remote_drifted"
    drifted_payload = {**base_payload, "reference_version_id": "version-v1"}
    artifacts.atomic_write_json(drifted_id, "payload.json", drifted_payload)
    repository.create(TaskRecord.new(drifted_id, project_id, TaskKind.TRAINING,
                                     "payload.json", "training:remote:scheduler",
                                     required_capabilities=("training.ultralytics",)))
    with pytest.raises(RemoteTrainingPreparationError) as raised:
        handler._freeze_request_contract(
            context, repository.get(drifted_id), drifted_payload)
    assert raised.value.code == "TRAINING_BASE_ANCESTRY_CHANGED"
    assert not artifacts.artifact_path(drifted_id, "input-freeze.json").exists()
    assert artifacts.read_json(drifted_id, "input-request-selection.json") is not None

    legacy_id = "train_remote_legacy_client"
    legacy_payload = dict(base_payload)  # Old client/task: no create-time fence field.
    artifacts.atomic_write_json(legacy_id, "payload.json", legacy_payload)
    repository.create(TaskRecord.new(legacy_id, project_id, TaskKind.TRAINING,
                                     "payload.json", "training:remote:scheduler",
                                     required_capabilities=("training.ultralytics",)))
    legacy_updated = handler._freeze_request_contract(
        context, repository.get(legacy_id), legacy_payload)
    assert legacy_updated["base_version_id"] == "version-v2"
    assert legacy_updated["reference_version_id"] == ""
    assert legacy_updated["base_version_ancestry_verified"] is False
