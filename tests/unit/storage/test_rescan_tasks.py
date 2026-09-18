from __future__ import annotations

from platform_core.material_repository import MaterialRepository
from platform_core.storage.import_candidates import RescanCandidateStore
from platform_core.storage.import_tasks import MANIFEST_REF
from platform_core.storage.rescan_tasks import prepare_remote_rescan_review
from platform_core.task_runtime import ArtifactStore


def material(image_id: str, object_key: str, digest: str, *, etag: str | None = None):
    return {
        "id": image_id,
        "filename": object_key.rsplit("/", 1)[-1],
        "stored_name": object_key.rsplit("/", 1)[-1],
        "storage_source_id": "s3-a",
        "storage_type": "s3",
        "object_key": object_key,
        "content_sha256": digest,
        "size_bytes": 100,
        "etag": etag if etag is not None else f"etag-{image_id}",
        "width": 64,
        "height": 48,
        "processing_status": "processed",
        "labels": [],
        "box_count": 0,
        "created_at": f"2026-09-19T00:00:0{image_id[-1]}+00:00",
    }


def candidate(object_key: str, digest: str, *, etag: str, size_bytes: int = 100):
    return {
        "object_key": object_key,
        "filename": object_key.rsplit("/", 1)[-1],
        "storage_source_id": "s3-a",
        "storage_type": "s3",
        "content_sha256": digest,
        "size_bytes": size_bytes,
        "etag": etag,
        "width": 64,
        "height": 48,
        "status": "IMPORTABLE",
        "error": "",
    }


def test_remote_rescan_review_projects_incremental_categories_and_selects_only_new(tmp_path):
    data_dir = tmp_path / "data"
    project_id = "project-rescan"
    materials = MaterialRepository(data_dir / "projects" / project_id)
    materials.upsert_many([
        material("old-1", "images/unchanged.jpg", "a" * 64, etag="etag-unchanged"),
        material("old-2", "images/changed.jpg", "b" * 64, etag="etag-changed-old"),
        material("old-3", "images/missing.jpg", "c" * 64, etag="etag-missing"),
        material("old-4", "images/etag-only.jpg", "f" * 64, etag="etag-before"),
    ])

    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    task_id = "remote-rescan-1"
    manifest = artifacts.artifact_path(task_id, MANIFEST_REF)
    store = RescanCandidateStore(manifest)
    materials.snapshot_storage_references(manifest, "s3-a")
    store.upsert_many([
        candidate("images/unchanged.jpg", "a" * 64, etag="etag-unchanged"),
        candidate("images/changed.jpg", "d" * 64, etag="etag-changed-new"),
        candidate("images/new.jpg", "e" * 64, etag="etag-new"),
        candidate("images/etag-only.jpg", "f" * 64, etag="etag-after"),
    ])

    result = prepare_remote_rescan_review(
        data_dir=data_dir,
        artifacts=artifacts,
        task_id=task_id,
        project_id=project_id,
        storage_source_id="s3-a",
    )

    assert result["execution_mode"] == "agent"
    assert result["counts"] == {
        "CHANGED": 2,
        "MISSING": 1,
        "NEW": 1,
        "UNCHANGED": 1,
    }
    projected = RescanCandidateStore(manifest)
    assert list(projected.iter_category_keys("NEW")) == ["images/new.jpg"]
    selection = projected.confirm(projected.iter_category_keys("NEW"))
    assert selection.selected_count == 1
    assert [row["object_key"] for row in projected.pending_index_batch()] == [
        "images/new.jpg"
    ]
