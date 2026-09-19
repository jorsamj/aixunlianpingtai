from __future__ import annotations

from types import SimpleNamespace

import pytest

from platform_core.annotation_repository import AnnotationRepository
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


def test_rescan_annotation_source_evidence_tracks_sidecar_yaml_split_and_boxes(tmp_path):
    store = RescanCandidateStore(tmp_path / "manifest.sqlite3")
    store.inventory_many([
        {"object_key": "data.yaml", "size_bytes": 40, "etag": "yaml-etag", "sha256": "1" * 64},
        {"object_key": "labels/train/a.txt", "size_bytes": 20, "etag": "label-etag", "sha256": "2" * 64},
    ])
    store.manifest_many([{
        "object_key": "images/train/a.jpg", "split": "train", "yaml_key": "data.yaml",
    }])
    store.set_label_mapping({0: "smoke"})
    store.annotation_batch(
        [{
            "object_key": "images/train/a.jpg",
            "label_key": "labels/train/a.txt",
            "annotation_status": "annotated",
            "box_count": 1,
        }],
        [{
            "object_key": "images/train/a.jpg", "line_number": 1, "class_id": 0,
            "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.25, "clipped": False,
        }],
        [],
    )
    first = store.annotation_source_evidence(
        ["images/train/a.jpg"], source_format="yolo",
    )["images/train/a.jpg"]
    assert first["label_object"]["sha256"] == "2" * 64
    assert first["dataset_object"]["sha256"] == "1" * 64
    assert first["split"] == "train"
    assert first["box_count"] == 1

    store.inventory_many([{
        "object_key": "labels/train/a.txt",
        "size_bytes": 21,
        "etag": "label-etag-2",
        "sha256": "3" * 64,
    }])
    second = store.annotation_source_evidence(
        ["images/train/a.jpg"], source_format="yolo",
    )["images/train/a.jpg"]
    assert second["source_digest"] != first["source_digest"]

    store.restart_annotation_deltas()
    store.annotation_delta_batch([{
        "object_key": "images/train/a.jpg",
        "category": "ANNOTATION_CHANGED",
        "source_evidence": second,
    }])
    assert store.annotation_summary()["counts"] == {"ANNOTATION_CHANGED": 1}


def test_yolo_annotation_delta_distinguishes_new_change_conflict_and_removed(tmp_path):
    data_dir = tmp_path / "data"
    project_id = "project-yolo-delta"
    project_path = data_dir / "projects" / project_id
    project_path.mkdir(parents=True)
    (project_path / "meta.json").write_text(
        '{"labels":["smoke"],"label_meta":[{"status":"active"}]}',
        encoding="utf-8",
    )
    materials = MaterialRepository(project_path)
    annotations = AnnotationRepository(project_path)
    rows = [
        material("old-1", "images/train/new-source.jpg", "a" * 64),
        material("old-2", "images/train/changed.jpg", "b" * 64),
        material("old-3", "images/train/conflict.jpg", "c" * 64),
        material("old-4", "images/train/removed.jpg", "d" * 64),
    ]
    rows[1]["external_annotation"] = {
        "source_format": "yolo", "source_digest": "old-source",
        "synced_annotation_hash": "",
        "annotation_status": "annotated",
    }
    rows[2]["external_annotation"] = {
        "source_format": "yolo", "source_digest": "old-conflict",
        "synced_annotation_hash": "previous-platform-hash",
        "annotation_status": "annotated",
    }
    rows[3]["external_annotation"] = {
        "source_format": "yolo", "source_digest": "old-removed",
        "synced_annotation_hash": "",
        "annotation_status": "annotated",
    }
    materials.upsert_many(rows)
    annotations.upsert("old-3", [{
        "id": "old-3-1", "label": "smoke", "class_id": 0,
        "x1": 5, "y1": 5, "x2": 20, "y2": 20,
    }])
    conflict = annotations.get("old-3")
    rows[2]["external_annotation"]["synced_annotation_hash"] = "different-from-" + conflict["content_digest"][:8]
    materials.patch({"old-3": {"external_annotation": rows[2]["external_annotation"]}})

    store = RescanCandidateStore(tmp_path / "manifest.sqlite3")
    materials.snapshot_storage_references(store.path, "s3-a")
    candidates = [
        candidate(row["object_key"], row["content_sha256"], etag=row["etag"])
        for row in rows
    ]
    store.upsert_many(candidates)
    store.inventory_many([
        {"object_key": "data.yaml", "size_bytes": 10, "etag": "yaml", "sha256": "1" * 64},
        {"object_key": "labels/train/new-source.txt", "size_bytes": 10, "etag": "n", "sha256": "2" * 64},
        {"object_key": "labels/train/changed.txt", "size_bytes": 10, "etag": "c", "sha256": "3" * 64},
        {"object_key": "labels/train/conflict.txt", "size_bytes": 10, "etag": "x", "sha256": "4" * 64},
    ])
    store.set_label_mapping({0: "smoke"})
    for key, label_key, status in [
        ("images/train/new-source.jpg", "labels/train/new-source.txt", "annotated"),
        ("images/train/changed.jpg", "labels/train/changed.txt", "annotated"),
        ("images/train/conflict.jpg", "labels/train/conflict.txt", "annotated"),
        ("images/train/removed.jpg", None, "unannotated"),
    ]:
        store.manifest_many([{"object_key": key, "split": "train", "yaml_key": "data.yaml"}])
        boxes = [] if status == "unannotated" else [{
            "object_key": key, "line_number": 1, "class_id": 0,
            "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2, "clipped": False,
        }]
        store.annotation_batch([{
            "object_key": key, "label_key": label_key,
            "annotation_status": status, "box_count": len(boxes),
        }], boxes, [])

    from platform_core.storage.rescan_tasks import _build_annotation_deltas
    summary = _build_annotation_deltas(
        store, project_path, source_format="yolo",
    )
    assert summary["counts"]["ANNOTATION_CONFLICT"] >= 1
    assert summary["counts"]["ANNOTATION_REMOVED"] == 1
    assert (
        summary["counts"].get("ANNOTATION_NEW", 0)
        + summary["counts"].get("ANNOTATION_CONFLICT", 0)
    ) >= 2
