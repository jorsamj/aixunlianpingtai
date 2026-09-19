from __future__ import annotations

from types import SimpleNamespace

import pytest

from platform_core.material_repository import MaterialRepository
from platform_core.storage.import_candidates import RescanCandidateStore
from platform_core.storage.import_tasks import MANIFEST_REF
from platform_core.storage.rescan_tasks import StorageRescanHandler, prepare_remote_rescan_review
from platform_core.task_runtime import ArtifactStore, TaskStatus


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


class _StatOnlyProvider:
    def __init__(self, metadata):
        self.metadata = metadata
        self.stat_calls = []

    def stat(self, key):
        self.stat_calls.append(str(key))
        return self.metadata

    def open_reader(self, _key):
        raise AssertionError("remote Agent rescan confirmation must not re-read object bodies")


class _ApplyContext:
    def __init__(self, artifacts, task_id, project_id):
        self.artifacts = artifacts
        self.task = SimpleNamespace(task_id=task_id, project_id=project_id)
        self.checkpoints = []

    def check(self, _current="", force=False):
        return None

    def save_checkpoint(self, value):
        self.checkpoints.append(dict(value))


def test_remote_rescan_apply_uses_stat_identity_not_central_body_reads(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    project_id = "project-remote-apply"
    task_id = "remote-rescan-apply"
    materials = MaterialRepository(data_dir / "projects" / project_id)
    current = material("old-1", "images/unchanged.jpg", "a" * 64)
    materials.upsert(current)

    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    store = RescanCandidateStore(artifacts.artifact_path(task_id, MANIFEST_REF))
    row = {
        **candidate(
            "images/unchanged.jpg",
            "a" * 64,
            etag=current["etag"],
            size_bytes=current["size_bytes"],
        ),
        "old_sha256": "a" * 64,
        "category": "UNCHANGED",
    }
    store.object_batch([row])
    store.set_meta("scan_complete", True)
    store.confirm_policy({"new": "ignore", "missing": "ignore", "changed": "ignore"})

    provider = _StatOnlyProvider(SimpleNamespace(
        size_bytes=current["size_bytes"],
        etag=current["etag"],
        sha256=current["content_sha256"],
    ))
    handler = StorageRescanHandler(data_dir)
    monkeypatch.setattr(
        handler,
        "_inspect_verified",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("central image inspection must not run for Agent review")
        ),
    )
    context = _ApplyContext(artifacts, task_id, project_id)

    status, result_ref = handler._apply_rescan(
        context,
        SimpleNamespace(id="s3-a"),
        provider,
        store,
        materials,
        {"execution_mode": "agent"},
    )

    assert status is TaskStatus.SUCCEEDED
    assert result_ref == "rescan/final.json"
    assert provider.stat_calls == ["images/unchanged.jpg"]
    assert materials.get("old-1")["source_status"] == "AVAILABLE"


def test_remote_rescan_stat_verification_rejects_changed_etag():
    provider = _StatOnlyProvider(SimpleNamespace(
        size_bytes=100,
        etag="etag-after",
        sha256="a" * 64,
    ))
    with pytest.raises(ValueError, match="identity changed"):
        StorageRescanHandler._verify_remote_review_object(
            provider,
            candidate("images/a.jpg", "a" * 64, etag="etag-before"),
        )
