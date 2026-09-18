from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.storage import LocalStorageProvider, StorageSourceRepository
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_confirmation import confirm_import
from platform_core.storage.import_tasks import StorageImportHandler, commit_storage_import
from platform_core.remote_material_import import (
    REMOTE_MATERIAL_STAGING_REF,
    RemoteMaterialStagingStore,
    build_yolo_material_review_archive,
    commit_material_review_archive,
)
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus


def jpg(color):
    stream = BytesIO()
    Image.new("RGB", (32, 24), color).save(stream, format="JPEG")
    return stream.getvalue()


def runtime(tmp_path, files, *, prefix="incoming"):
    data = tmp_path / "data"
    project_id = "p1"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    (project / "meta.json").write_text('{"labels": []}', encoding="utf-8")
    external = tmp_path / "external"
    provider = LocalStorageProvider("external-a", external)
    for key, content in files.items():
        provider.upload(key, BytesIO(content))
    sources = StorageSourceRepository(data / "storage" / "storage_sources.sqlite3")
    sources.create({
        "id": "external-a", "name": "external", "type": "local",
        "config": {"root": str(external)},
    })
    task_root = data / "task_runtime"
    repository = TaskRepository(task_root / "tasks.sqlite3")
    artifacts = ArtifactStore(task_root / "artifacts")
    task = TaskRecord.new(
        "scan-1", project_id, TaskKind.MATERIAL_IMPORT,
        "request.json", "storage:external-a",
    )
    artifacts.atomic_write_json(task.task_id, task.payload_ref, {
        "storage_source_id": "external-a", "prefix": prefix, "recursive": True,
    })
    repository.create(task)
    scheduler = Scheduler(
        repository, artifacts, "worker",
        {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)}, {"storage.import"},
    )
    return data, project, provider, repository, artifacts, task, scheduler


def confirm_all(repository, artifacts, task_id):
    store = ImportCandidateStore(artifacts.artifact_path(task_id, "scan/candidates.sqlite3"))
    keys = [row["object_key"] for row in store.iter_status("IMPORTABLE")]
    selection = store.confirm(keys)
    artifacts.atomic_write_json(task_id, "scan/confirmation.json", {
        "accepted": True,
        "selection_digest": selection.digest,
        "selected_count": selection.selected_count,
        "confirmed_at": selection.confirmed_at,
    })
    repository.resume_after_confirmation(task_id)


def test_existing_source_scan_waits_then_indexes_without_copying(tmp_path):
    env = runtime(tmp_path, {
        "incoming/a.jpg": jpg("red"),
        "incoming/b.png": jpg("blue"),
        "incoming/readme.txt": b"not an image",
    })
    data, project, provider, repository, artifacts, task, scheduler = env

    assert scheduler.run_once() is True
    waiting = repository.get(task.task_id)
    assert waiting.status is TaskStatus.AWAITING_CONFIRMATION
    result = artifacts.read_json(task.task_id, waiting.result_ref)
    assert "candidates" not in result
    assert result["scanned_files"] == 3
    assert result["importable_images"] == 2
    assert result["skipped_files"] == 1
    assert result["stage"] == "awaiting_confirmation"
    assert result["manifest_ref"] == "scan/candidates.sqlite3"
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, result["manifest_ref"]))
    assert store.counts() == {"IMPORTABLE": 2, "SKIPPED": 1}

    confirm_all(repository, artifacts, task.task_id)
    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    final = artifacts.read_json(task.task_id, completed.result_ref)
    assert final["selected"] == final["indexed"] == 2
    assert final["failed"] == 0
    materials = MaterialRepository(project)
    rows = materials.read().rows
    assert materials.count() == 2
    assert {row["storage_source_id"] for row in rows} == {"external-a"}
    assert all(row["stored_name"] for row in rows)
    assert not (project / "uploads").exists()
    assert not (data / "cache" / "materials").exists()
    assert provider.exists("incoming/a.jpg")
    assert provider.exists("incoming/b.png")


def test_scan_deduplicates_by_sha_and_records_damaged_images(tmp_path):
    same = jpg("white")
    env = runtime(tmp_path, {
        "incoming/first.jpg": same,
        "incoming/copy.jpg": same,
        "incoming/broken.jpg": b"not a jpeg",
        "outside/ignored.jpg": jpg("black"),
    })
    _data, _project, _provider, repository, artifacts, task, scheduler = env

    assert scheduler.run_once() is True
    assert repository.get(task.task_id).status is TaskStatus.AWAITING_CONFIRMATION
    result = artifacts.read_json(task.task_id, "scan/result.json")
    assert result["scanned_files"] == 3
    assert result["importable_images"] == 1
    assert result["duplicates"] == 1
    assert result["invalid_images"] == 1
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, result["manifest_ref"]))
    assert store.counts() == {"DUPLICATE": 1, "IMPORTABLE": 1, "INVALID": 1}


def test_scan_uses_material_content_hash_duplicate_detection(tmp_path):
    content = jpg("green")
    env = runtime(tmp_path, {"incoming/new-name.jpg": content})
    _data, project, provider, _repository, artifacts, task, scheduler = env
    metadata = provider.stat("incoming/new-name.jpg")
    MaterialRepository(project).upsert({
        "id": "existing", "filename": "elsewhere.jpg", "stored_name": "existing.jpg",
        "storage_source_id": "other", "storage_type": "local",
        "object_key": "elsewhere.jpg", "content_sha256": metadata.sha256,
        "size_bytes": metadata.size_bytes, "labels": [],
    })

    assert scheduler.run_once() is True
    result = artifacts.read_json(task.task_id, "scan/result.json")
    assert result["importable_images"] == 0
    assert result["duplicates"] == 1


def test_recovery_reuses_existing_candidate_manifest_idempotently(tmp_path):
    env = runtime(tmp_path, {
        "incoming/a.jpg": jpg("red"),
        "incoming/b.jpg": jpg("blue"),
    })
    _data, _project, provider, repository, artifacts, task, scheduler = env
    metadata = provider.stat("incoming/a.jpg")
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3"))
    store.upsert_many([{
        "object_key": metadata.key, "filename": "a.jpg",
        "storage_source_id": "external-a", "storage_type": "local",
        "content_sha256": metadata.sha256, "size_bytes": metadata.size_bytes,
        "etag": metadata.etag, "width": 32, "height": 24,
        "status": "IMPORTABLE", "error": "", "duplicate": False,
    }])
    artifacts.atomic_write_json(task.task_id, "checkpoints/worker.json", {"stage": "SCANNING"})

    assert scheduler.run_once() is True
    assert repository.get(task.task_id).status is TaskStatus.AWAITING_CONFIRMATION
    assert store.counts() == {"IMPORTABLE": 2}
    result = artifacts.read_json(task.task_id, "scan/result.json")
    assert result["importable_images"] == 2


def test_indexing_reuses_preassigned_id_after_material_write_retry_window(tmp_path):
    env = runtime(tmp_path, {"incoming/a.jpg": jpg("red")})
    _data, project, _provider, repository, artifacts, task, scheduler = env
    assert scheduler.run_once() is True
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3"))
    row = next(store.iter_status("IMPORTABLE"))
    store.confirm([row["object_key"]])
    store.assign_image_ids(task.task_id)
    pending = store.pending_index_batch()
    image_id = pending[0]["image_id"]
    MaterialRepository(project).upsert({
        "id": image_id, "filename": pending[0]["filename"],
        "stored_name": f"{image_id}.jpg", "storage_source_id": "external-a",
        "storage_type": "local", "object_key": pending[0]["object_key"],
        "content_sha256": pending[0]["content_sha256"],
        "size_bytes": pending[0]["size_bytes"], "labels": [],
    })
    artifacts.atomic_write_json(task.task_id, "scan/confirmation.json", {
        "accepted": True, "selected_count": 1,
    })
    repository.resume_after_confirmation(task.task_id)

    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    assert artifacts.read_json(task.task_id, completed.result_ref)["imported"] == 1
    assert MaterialRepository(project).count() == 1
    assert store.pending_index_batch() == []


def test_legacy_candidate_json_is_migrated_and_same_batch_sha_is_indexed_once(tmp_path):
    same = jpg("purple")
    env = runtime(tmp_path, {
        "incoming/original.jpg": same,
        "incoming/copy.jpg": same,
    })
    data, project, provider, repository, artifacts, task, scheduler = env
    candidates = []
    for key in ("incoming/original.jpg", "incoming/copy.jpg"):
        metadata = provider.stat(key)
        candidates.append({
            "object_key": key,
            "filename": Path(key).name,
            "storage_source_id": "external-a",
            "storage_type": "local",
            "content_sha256": metadata.sha256,
            "size_bytes": metadata.size_bytes,
            "etag": metadata.etag,
            "width": 32,
            "height": 24,
        })
    artifacts.atomic_write_json(task.task_id, "scan/result.json", {
        "storage_source_id": "external-a",
        "candidates": candidates,
    })
    lease = repository.claim_next("prepare", (TaskKind.MATERIAL_IMPORT,), {"storage.import"})
    assert lease is not None
    repository.finish(
        task.task_id, lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION, "scan/result.json",
    )

    confirmation = commit_storage_import(data, "p1", artifacts, task.task_id)
    assert confirmation["selected_count"] == 2
    store = ImportCandidateStore(artifacts.artifact_path(task.task_id, "scan/candidates.sqlite3"))
    assert store.counts() == {"IMPORTABLE": 2}
    repository.resume_after_confirmation(task.task_id)

    assert scheduler.run_once() is True
    completed = repository.get(task.task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    final = artifacts.read_json(task.task_id, completed.result_ref)
    assert final["selected"] == final["indexed"] == 2
    assert final["imported"] == 1
    assert final["index_duplicates"] == 1
    assert MaterialRepository(project).count() == 1


def test_agent_review_handoff_publishes_selected_object_before_material_index(tmp_path):
    data = tmp_path / "data"
    project_id = "p-agent-review"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    (project / "meta.json").write_text('{"labels": []}', encoding="utf-8")

    target_root = tmp_path / "target-store"
    provider = LocalStorageProvider("target-store", target_root)
    sources = StorageSourceRepository(data / "storage" / "storage_sources.sqlite3")
    sources.create({
        "id": "target-store",
        "name": "target",
        "type": "local",
        "config": {"root": str(target_root)},
    })

    repository = TaskRepository(data / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data / "task_runtime" / "artifacts")
    task_id = "agent-material-review"
    review_ref = "remote-material/generation-1/review.zip"
    result_ref = "remote-results/1/result.json"
    image = jpg("orange")
    digest = hashlib.sha256(image).hexdigest()
    object_key = "incoming/agent/a.jpg"
    payload_member = "files/a.jpg"

    review_path = artifacts.artifact_path(task_id, review_ref)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(review_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(payload_member, image)
    review_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()

    store = ImportCandidateStore(
        artifacts.artifact_path(task_id, "scan/candidates.sqlite3")
    )
    store.upsert_many([{
        "object_key": object_key,
        "filename": "a.jpg",
        "storage_source_id": "target-store",
        "storage_type": "local",
        "content_sha256": digest,
        "size_bytes": len(image),
        "etag": "",
        "width": 32,
        "height": 24,
        "status": "IMPORTABLE",
        "error": "",
        "duplicate": False,
    }])
    staging = RemoteMaterialStagingStore(
        artifacts.artifact_path(task_id, REMOTE_MATERIAL_STAGING_REF)
    )
    staging.replace_many([{
        "object_key": object_key,
        "payload_member": payload_member,
        "content_sha256": digest,
        "size_bytes": len(image),
    }])
    artifacts.atomic_write_json(task_id, "request.json", {
        "mode": "server_zip",
        "execution_mode": "agent",
        "storage_source_id": "target-store",
        "target_prefix": "incoming/agent",
        "import_format": "images",
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
        },
    })
    artifacts.atomic_write_json(task_id, result_ref, {
        "output_sha256": review_sha,
        "output_size_bytes": review_path.stat().st_size,
        "material_review_archive_ref": review_ref,
        "material_staging_ref": REMOTE_MATERIAL_STAGING_REF,
    })
    task = repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        "material-import:agent:target-store",
        required_capabilities=("agent.remote",),
    ))
    lease = repository.claim_next(
        "agent-review",
        (TaskKind.MATERIAL_IMPORT,),
        {"agent.remote"},
    )
    assert lease is not None
    repository.finish(
        task_id,
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        result_ref,
    )

    selection = store.confirm([object_key])
    artifacts.atomic_write_json(task_id, "scan/confirmation.json", {
        "accepted": True,
        "selection_digest": selection.digest,
        "selected_count": selection.selected_count,
        "confirmed_at": selection.confirmed_at,
    })
    resumed = repository.resume_after_confirmation(
        task_id,
        required_capabilities=("storage.import",),
    )
    assert resumed.status is TaskStatus.QUEUED
    assert resumed.stage == "indexing_queued"
    assert resumed.required_capabilities == ("storage.import",)
    assert not provider.exists(object_key)

    scheduler = Scheduler(
        repository,
        artifacts,
        "local-indexer",
        {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)},
        {"storage.import"},
    )
    assert scheduler.run_once() is True

    completed = repository.get(task_id)
    assert completed is not None
    assert completed.status is TaskStatus.SUCCEEDED
    assert provider.exists(object_key)
    metadata = provider.stat(object_key)
    assert metadata.sha256 == digest
    assert metadata.size_bytes == len(image)
    rows = MaterialRepository(project).read().rows
    assert len(rows) == 1
    assert rows[0]["storage_source_id"] == "target-store"
    assert rows[0]["object_key"] == object_key
    assert rows[0]["content_sha256"] == digest




def test_agent_storage_scan_indexes_existing_verified_object_without_reupload(tmp_path):
    data = tmp_path / "data"
    project_id = "p-agent-storage-scan"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    (project / "meta.json").write_text('{"labels": []}', encoding="utf-8")

    target_root = tmp_path / "scan-target"
    provider = LocalStorageProvider("scan-target", target_root)
    provider.health_check()
    object_key = "incoming/scan/a.jpg"
    image = jpg("blue")
    provider.upload(object_key, BytesIO(image), content_type="image/jpeg")
    before = provider.stat(object_key)

    sources = StorageSourceRepository(data / "storage" / "storage_sources.sqlite3")
    sources.create({
        "id": "scan-target",
        "name": "scan-target",
        "type": "local",
        "config": {"root": str(target_root)},
    })
    repository = TaskRepository(data / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data / "task_runtime" / "artifacts")
    task_id = "agent-storage-scan"
    review_ref = "remote-material/generation-1/review.zip"
    review_path = artifacts.artifact_path(task_id, review_ref)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(review_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("meta.json", "{}")
    review_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()

    store = ImportCandidateStore(
        artifacts.artifact_path(task_id, "scan/candidates.sqlite3")
    )
    store.upsert_many([{
        "object_key": object_key,
        "filename": "a.jpg",
        "storage_source_id": "scan-target",
        "storage_type": "local",
        "content_sha256": before.sha256,
        "size_bytes": before.size_bytes,
        "etag": before.etag,
        "width": 32,
        "height": 24,
        "status": "IMPORTABLE",
        "error": "",
        "duplicate": False,
    }])
    RemoteMaterialStagingStore(
        artifacts.artifact_path(task_id, REMOTE_MATERIAL_STAGING_REF)
    ).replace_many([])
    artifacts.atomic_write_json(task_id, "request.json", {
        "mode": "storage_scan",
        "execution_mode": "agent",
        "storage_source_id": "scan-target",
        "prefix": "incoming/scan",
        "recursive": True,
        "import_format": "images",
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "material_import": {
                "schema_version": 1,
                "mode": "storage_scan",
            },
        },
    })
    result_ref = "remote-results/1/result.json"
    artifacts.atomic_write_json(task_id, result_ref, {
        "output_sha256": review_sha,
        "output_size_bytes": review_path.stat().st_size,
        "material_review_archive_ref": review_ref,
        "material_staging_ref": REMOTE_MATERIAL_STAGING_REF,
    })
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        "material-import:agent:scan-target",
        required_capabilities=("agent.remote",),
    ))
    lease = repository.claim_next(
        "agent-scan",
        (TaskKind.MATERIAL_IMPORT,),
        {"agent.remote"},
    )
    assert lease is not None
    repository.finish(
        task_id,
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        result_ref,
    )
    selection = store.confirm([object_key])
    artifacts.atomic_write_json(task_id, "scan/confirmation.json", {
        "accepted": True,
        "selection_digest": selection.digest,
        "selected_count": selection.selected_count,
        "confirmed_at": selection.confirmed_at,
    })
    repository.resume_after_confirmation(
        task_id,
        required_capabilities=("storage.import",),
    )

    scheduler = Scheduler(
        repository,
        artifacts,
        "local-indexer",
        {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)},
        {"storage.import"},
    )
    assert scheduler.run_once() is True

    completed = repository.get(task_id)
    assert completed is not None
    assert completed.status is TaskStatus.SUCCEEDED
    after = provider.stat(object_key)
    assert after.etag == before.etag
    assert after.sha256 == before.sha256
    rows = MaterialRepository(project).read().rows
    assert len(rows) == 1
    assert rows[0]["storage_source_id"] == "scan-target"
    assert rows[0]["object_key"] == object_key
    assert rows[0]["content_sha256"] == before.sha256


def test_agent_yolo_review_label_mapping_writes_annotation_repository(tmp_path):
    data = tmp_path / "data"
    project_id = "p-agent-yolo-review"
    project = data / "projects" / project_id
    project.mkdir(parents=True)
    platform_labels = [
        {"code": "smoke", "display_name": "吸烟", "status": "active"},
        {"code": "fire", "display_name": "烟火", "status": "active"},
    ]
    (project / "meta.json").write_text(
        json.dumps({
            "labels": ["smoke", "fire"],
            "label_meta": platform_labels,
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    source_root = tmp_path / "agent-yolo-source"
    for relative, color in (
        ("images/train/positive.jpg", "red"),
        ("images/val/negative.jpg", "blue"),
    ):
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpg(color))
    (source_root / "labels/train").mkdir(parents=True)
    (source_root / "labels/val").mkdir(parents=True)
    (source_root / "labels/train/positive.txt").write_text(
        "0 0.5 0.5 0.5 0.5\n1 0.25 0.25 0.25 0.5\n",
        encoding="utf-8",
    )
    (source_root / "labels/val/negative.txt").write_text("", encoding="utf-8")
    (source_root / "data.yaml").write_text(
        "path: .\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: cigarette\n"
        "  1: flame\n",
        encoding="utf-8",
    )

    target_root = tmp_path / "target-store-yolo"
    provider = LocalStorageProvider("target-yolo", target_root)
    sources = StorageSourceRepository(data / "storage" / "storage_sources.sqlite3")
    sources.create({
        "id": "target-yolo",
        "name": "target-yolo",
        "type": "local",
        "config": {"root": str(target_root)},
    })

    repository = TaskRepository(data / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data / "task_runtime" / "artifacts")
    task_id = "agent-yolo-review"
    generation = 1
    target_prefix = "incoming/yolo"

    review = build_yolo_material_review_archive(
        source_root,
        tmp_path / "agent-yolo-review.zip",
        task_id=task_id,
        project_id=project_id,
        execution_generation=generation,
        storage_source_id="target-yolo",
        storage_type="local",
        target_prefix=target_prefix,
        dataset_yaml="data.yaml",
    )
    assert review["candidate_count"] == 2
    assert review["classes"] == [
        {"class_id": 0, "name": "cigarette"},
        {"class_id": 1, "name": "flame"},
    ]

    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id=task_id,
        project_id=project_id,
        execution_generation=generation,
        archive_path=review["path"],
        archive_sha256=review["sha256"],
        archive_size_bytes=review["size_bytes"],
        expected_source_id="target-yolo",
        expected_storage_type="local",
        expected_prefix=target_prefix,
        expected_import_format="yolo",
        expected_dataset_yaml="data.yaml",
        platform_labels=platform_labels,
    )
    assert committed["material_review_committed"] is True

    store = ImportCandidateStore(
        artifacts.artifact_path(task_id, "scan/candidates.sqlite3")
    )
    classes = store.external_classes()
    assert classes == [
        {"class_id": 0, "name": "cigarette"},
        {"class_id": 1, "name": "flame"},
    ]
    candidate_keys = [
        row["object_key"]
        for row in store.iter_status("IMPORTABLE")
    ]
    assert len(candidate_keys) == 2
    candidate_annotations = store.annotations_for_keys(candidate_keys)
    assert sorted(
        row["annotation_status"] for row in candidate_annotations.values()
    ) == ["annotated", "confirmed_empty"]

    confirmation = confirm_import(
        store,
        artifacts,
        task_id,
        object_keys=candidate_keys,
        label_mapping={"0": "smoke", "1": "fire"},
        create_labels=[],
        accept_quality_report=True,
        labels=platform_labels,
        create_label=lambda code: code,
    )
    assert confirmation["label_mapping"] == {"0": "smoke", "1": "fire"}
    assert confirmation["selected_count"] == 2

    result_ref = "remote-results/1/result.json"
    durable_review = artifacts.artifact_path(
        task_id,
        committed["material_review_archive_ref"],
    )
    artifacts.atomic_write_json(task_id, "request.json", {
        "mode": "server_zip",
        "execution_mode": "agent",
        "storage_source_id": "target-yolo",
        "target_prefix": target_prefix,
        "import_format": "yolo",
        "dataset_yaml": "data.yaml",
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
        },
    })
    artifacts.atomic_write_json(task_id, result_ref, {
        "output_sha256": hashlib.sha256(durable_review.read_bytes()).hexdigest(),
        "output_size_bytes": durable_review.stat().st_size,
        "material_review_archive_ref": committed["material_review_archive_ref"],
        "material_staging_ref": committed["material_staging_ref"],
    })
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        "material-import:agent:target-yolo",
        required_capabilities=("agent.remote",),
    ))
    lease = repository.claim_next(
        "agent-yolo-review",
        (TaskKind.MATERIAL_IMPORT,),
        {"agent.remote"},
    )
    assert lease is not None
    repository.finish(
        task_id,
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        result_ref,
    )
    resumed = repository.resume_after_confirmation(
        task_id,
        required_capabilities=("storage.import",),
    )
    assert resumed.status is TaskStatus.QUEUED

    scheduler = Scheduler(
        repository,
        artifacts,
        "local-yolo-indexer",
        {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data)},
        {"storage.import"},
    )
    assert scheduler.run_once() is True
    completed = repository.get(task_id)
    assert completed is not None
    assert completed.status is TaskStatus.SUCCEEDED

    materials = MaterialRepository(project).read().rows
    assert len(materials) == 2
    by_name = {row["filename"]: row for row in materials}
    positive = by_name["positive.jpg"]
    negative = by_name["negative.jpg"]
    assert positive["storage_source_id"] == "target-yolo"
    assert positive["object_key"] == "incoming/yolo/images/train/positive.jpg"
    assert negative["object_key"] == "incoming/yolo/images/val/negative.jpg"
    assert provider.exists(positive["object_key"])
    assert provider.exists(negative["object_key"])

    annotations = AnnotationRepository(project)
    positive_ann = annotations.get(positive["id"])
    negative_ann = annotations.get(negative["id"])
    assert positive_ann is not None
    assert positive_ann["annotation_state"] == "annotated"
    assert [(box["label"], box["class_id"]) for box in positive_ann["boxes"]] == [
        ("smoke", 0),
        ("fire", 1),
    ]
    # Source image is 32x24. Normalized YOLO boxes must be converted to pixels.
    smoke_box, fire_box = positive_ann["boxes"]
    assert (smoke_box["x1"], smoke_box["y1"], smoke_box["x2"], smoke_box["y2"]) == (
        8.0, 6.0, 24.0, 18.0,
    )
    assert (fire_box["x1"], fire_box["y1"], fire_box["x2"], fire_box["y2"]) == (
        4.0, 0.0, 12.0, 12.0,
    )
    assert negative_ann is not None
    assert negative_ann["annotation_state"] == "confirmed_empty"
    assert negative_ann["boxes"] == []
    assert positive["imported_split"] == "train"
    assert negative["imported_split"] == "val"

    final = artifacts.read_json(task_id, completed.result_ref)
    assert final["annotations_written"] == 2
    assert final["boxes_imported"] == 2
    assert final["negative_samples"] == 1
