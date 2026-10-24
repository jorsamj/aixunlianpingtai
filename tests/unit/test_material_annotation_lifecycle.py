import threading
import uuid

import pytest

from platform_core.material_repository import (
    AnnotationMaterialLifecycleError,
    AnnotationProjectionConflictError,
    MaterialRepository,
    material_annotation_lifecycle_fence,
)
from platform_core.annotation_repository import AnnotationRepository


def material(image_id="image-1", content_sha256="a" * 64, **extra):
    return {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "stored_name": f"{image_id}.jpg",
        "storage_source_id": "default_local",
        "storage_type": "local",
        "object_key": f"uploads/{image_id}.jpg",
        "content_sha256": content_sha256,
        "size_bytes": 10,
        **extra,
    }


def test_lifecycle_fence_serializes_other_threads(tmp_path):
    entered = threading.Event()
    completed = threading.Event()

    def contender():
        entered.set()
        with material_annotation_lifecycle_fence(tmp_path):
            completed.set()

    with material_annotation_lifecycle_fence(tmp_path):
        thread = threading.Thread(target=contender)
        thread.start()
        assert entered.wait(2)
        assert not completed.wait(0.1)
    thread.join(2)

    assert not thread.is_alive()
    assert completed.is_set()


def test_formal_annotation_admission_rejects_missing_delete_claim_and_stale_content(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert(material())

    admitted = repository.assert_formal_annotation_admission({"image-1": "a" * 64})
    assert admitted["image-1"]["content_sha256"] == "a" * 64

    with pytest.raises(AnnotationMaterialLifecycleError, match="does not exist"):
        repository.assert_formal_annotation_admission({"missing": "a" * 64})

    repository.patch({"image-1": {"_dataset_delete_claim": "delete-token"}})
    with pytest.raises(AnnotationMaterialLifecycleError, match="being deleted"):
        repository.assert_formal_annotation_admission({"image-1": "a" * 64})

    repository.patch({"image-1": {"_dataset_delete_claim": None}})
    with pytest.raises(AnnotationMaterialLifecycleError, match="content changed"):
        repository.assert_formal_annotation_admission({"image-1": "b" * 64})


def test_rescan_content_commit_waits_for_lifecycle_fence(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert(material())
    started = threading.Event()
    completed = threading.Event()

    def rescan():
        started.set()
        repository.reconcile_storage_batch(
            "rescan-1",
            "default_local",
            [{
                "object_key": "uploads/image-1.jpg",
                "category": "CHANGED",
                "old_sha256": "a" * 64,
                "content_sha256": "b" * 64,
                "size_bytes": 11,
                "etag": "next",
                "width": 20,
                "height": 20,
            }],
        )
        completed.set()

    with material_annotation_lifecycle_fence(tmp_path):
        thread = threading.Thread(target=rescan)
        thread.start()
        assert started.wait(2)
        assert not completed.wait(0.1)
        admitted = repository.assert_formal_annotation_admission(
            {"image-1": "a" * 64}
        )
        assert admitted["image-1"]["content_sha256"] == "a" * 64
    thread.join(2)

    assert not thread.is_alive()
    assert completed.is_set()
    assert repository.get("image-1")["content_sha256"] == "b" * 64


def test_h1_annotation_commit_then_h2_rescan_keeps_gt_stale_not_rebound(
    tmp_path, monkeypatch,
):
    materials = MaterialRepository(tmp_path)
    materials.upsert(material())
    annotations = AnnotationRepository(tmp_path)
    admitted = threading.Event()
    resume = threading.Event()
    original = MaterialRepository.assert_formal_annotation_admission

    def pause_after_admission(self, expected):
        result = original(self, expected)
        if threading.current_thread().name == "annotation-h1":
            admitted.set()
            assert resume.wait(2)
        return result

    monkeypatch.setattr(
        MaterialRepository, "assert_formal_annotation_admission", pause_after_admission
    )
    errors = []

    def commit_h1():
        try:
            annotations.upsert(
                "image-1",
                [],
                annotation_state="confirmed_empty",
                source_content_sha256="a" * 64,
            )
        except BaseException as error:
            errors.append(error)

    annotation_thread = threading.Thread(target=commit_h1, name="annotation-h1")
    annotation_thread.start()
    assert admitted.wait(2)
    rescan_done = threading.Event()

    def commit_h2():
        materials.reconcile_storage_batch(
            "rescan-h2",
            "default_local",
            [{
                "object_key": "uploads/image-1.jpg",
                "category": "CHANGED",
                "old_sha256": "a" * 64,
                "content_sha256": "b" * 64,
                "size_bytes": 11,
                "etag": "h2",
                "width": 20,
                "height": 20,
            }],
        )
        rescan_done.set()

    rescan_thread = threading.Thread(target=commit_h2, name="rescan-h2")
    rescan_thread.start()
    assert not rescan_done.wait(0.1)
    resume.set()
    annotation_thread.join(2)
    rescan_thread.join(2)

    assert not errors
    assert not annotation_thread.is_alive()
    assert not rescan_thread.is_alive()
    current = materials.get("image-1")
    assert current["content_sha256"] == "b" * 64
    assert current["annotation_source_content_sha256"] == "a" * 64
    assert current["annotation_needs_review"] is True
    assert current["annotation_review_reason"] == "SOURCE_CONTENT_CHANGED"


def test_annotation_commit_wins_then_dataset_delete_removes_latest_gt(
    tmp_path, monkeypatch,
):
    materials = MaterialRepository(tmp_path)
    materials.upsert(material(dataset_id="dataset-1"))
    annotations = AnnotationRepository(tmp_path)
    admitted = threading.Event()
    resume = threading.Event()
    original = MaterialRepository.assert_formal_annotation_admission

    def pause_after_admission(self, expected):
        result = original(self, expected)
        if threading.current_thread().name == "annotation-before-delete":
            admitted.set()
            assert resume.wait(2)
        return result

    monkeypatch.setattr(
        MaterialRepository, "assert_formal_annotation_admission", pause_after_admission
    )
    writer_error = []

    def write_annotation():
        try:
            annotations.upsert(
                "image-1",
                [],
                annotation_state="confirmed_empty",
                source_content_sha256="a" * 64,
            )
        except BaseException as error:
            writer_error.append(error)

    writer = threading.Thread(target=write_annotation, name="annotation-before-delete")
    writer.start()
    assert admitted.wait(2)
    deleted = threading.Event()

    def delete_material():
        token = uuid.uuid4().hex
        with material_annotation_lifecycle_fence(tmp_path):
            materials.patch({"image-1": {"_dataset_delete_claim": token}})
            annotations.prepare_delete(token, ["image-1"])
            materials.remove(["image-1"])
            annotations.finalize_delete(token)
            annotations.complete_delete(token)
        deleted.set()

    deleter = threading.Thread(target=delete_material, name="dataset-delete")
    deleter.start()
    assert not deleted.wait(0.1)
    resume.set()
    writer.join(2)
    deleter.join(2)

    assert not writer_error
    assert deleted.is_set()
    assert materials.get("image-1") is None
    assert not annotations.exists("image-1")


def test_delete_claim_blocks_old_page_and_recovery_allows_fresh_commit(tmp_path):
    materials = MaterialRepository(tmp_path)
    materials.upsert(material(_dataset_delete_claim="delete-token"))
    annotations = AnnotationRepository(tmp_path)

    with pytest.raises(AnnotationMaterialLifecycleError, match="being deleted"):
        annotations.upsert(
            "image-1",
            [],
            annotation_state="confirmed_empty",
            source_content_sha256="a" * 64,
        )
    assert not annotations.exists("image-1")

    materials.patch({"image-1": {"_dataset_delete_claim": None}})
    saved = annotations.upsert(
        "image-1",
        [],
        annotation_state="confirmed_empty",
        source_content_sha256="a" * 64,
    )
    assert saved["annotation_state"] == "confirmed_empty"


def test_annotation_projection_is_monotonic_and_updates_indexes_atomically(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert(material())
    newest = {
        "annotation_version": 2,
        "annotation_hash": "b" * 64,
        "annotation_state": "annotated",
        "annotation_scope": ["fire"],
        "annotated": True,
        "box_count": 1,
        "labels": ["fire"],
        "label_counts": {"fire": 1},
    }
    stale = {
        "annotation_version": 1,
        "annotation_hash": "a" * 64,
        "annotation_state": "annotated",
        "annotation_scope": ["smoke"],
        "annotated": True,
        "box_count": 2,
        "labels": ["smoke"],
        "label_counts": {"smoke": 2},
    }

    assert repository.patch_annotation_projections({"image-1": newest})
    assert repository.patch_annotation_projections({"image-1": stale}) == []
    assert repository.patch_annotation_projections({"image-1": newest}) == []

    current = repository.get("image-1")
    assert current["annotation_version"] == 2
    assert current["annotation_hash"] == "b" * 64
    assert current["labels"] == ["fire"]
    assert current["annotation_scope"] == ["fire"]
    assert repository.label_usage()["fire"]["boxes"] == 1
    assert "smoke" not in repository.label_usage()


def test_same_projection_version_with_different_digest_fails_closed(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert(material())
    repository.patch_annotation_projections({
        "image-1": {
            "annotation_version": 3,
            "annotation_hash": "c" * 64,
            "annotation_state": "confirmed_empty",
            "annotation_scope": ["fire"],
            "annotated": True,
            "box_count": 0,
            "labels": [],
        }
    })

    with pytest.raises(AnnotationProjectionConflictError, match="version 3"):
        repository.patch_annotation_projections({
            "image-1": {
                "annotation_version": 3,
                "annotation_hash": "d" * 64,
                "annotation_state": "annotated",
                "annotation_scope": ["smoke"],
                "annotated": True,
                "box_count": 1,
                "labels": ["smoke"],
            }
        })

    current = repository.get("image-1")
    assert current["annotation_hash"] == "c" * 64
    assert current["annotation_scope"] == ["fire"]
