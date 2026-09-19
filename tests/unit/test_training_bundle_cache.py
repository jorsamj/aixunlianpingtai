from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path

import pytest

from platform_core import training_bundle_cache
from platform_core.training_bundle_cache import (
    CACHE_MAX_BYTES_ENV,
    CACHE_TTL_SECONDS_ENV,
    TrainingBundleCache,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_bundle(root: Path, *, snapshot_id: str) -> Path:
    bundle = root / "bundle"
    image_train = bundle / "dataset/images/train/img-1.jpg"
    image_test = bundle / "dataset/images/test/img-2.jpg"
    label_train = bundle / "dataset/labels/train/img-1.txt"
    label_test = bundle / "evaluation/ground_truth/test/img-2.txt"
    data_yaml = bundle / "dataset/data.yaml"
    snapshot = bundle / "snapshot.json"
    for path in (image_train, image_test, label_train, label_test, data_yaml, snapshot):
        path.parent.mkdir(parents=True, exist_ok=True)
    train_payload = b"train-image-bytes"
    test_payload = b"test-image-bytes"
    image_train.write_bytes(train_payload)
    image_test.write_bytes(test_payload)
    label_train.write_text("0 0.5 0.5 0.2 0.2", encoding="utf-8")
    label_test.write_text("0 0.4 0.4 0.1 0.1", encoding="utf-8")
    data_yaml.write_text("path: .\ntrain: images/train\nval: images/validation\n", encoding="utf-8")
    snapshot_payload = {"snapshot_id": snapshot_id, "schema_version": 3}
    snapshot.write_text(json.dumps(snapshot_payload, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "snapshot_id": snapshot_id,
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": training_bundle_cache._sha256(snapshot),
        "data_yaml_ref": "dataset/data.yaml",
        "splits": {
            "train": [
                {
                    "image_id": "img-1",
                    "image_ref": "dataset/images/train/img-1.jpg",
                    "label_ref": "dataset/labels/train/img-1.txt",
                    "content_sha256": _sha256_bytes(train_payload),
                    "size_bytes": len(train_payload),
                    "label_sha256": training_bundle_cache._sha256(label_train),
                }
            ],
            "validation": [],
            "test": [
                {
                    "image_id": "img-2",
                    "image_ref": "dataset/images/test/img-2.jpg",
                    "label_ref": "evaluation/ground_truth/test/img-2.txt",
                    "content_sha256": _sha256_bytes(test_payload),
                    "size_bytes": len(test_payload),
                    "label_sha256": training_bundle_cache._sha256(label_test),
                }
            ],
        },
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return bundle


def _set_access_ns(entry_root: Path, value: int) -> None:
    (entry_root / "access.json").write_text(
        json.dumps(
            {
                "last_access_ns": value,
                "last_accessed_at": "1970-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )



def test_verified_bundle_cache_restores_isolated_trainer_writable_images(tmp_path):
    snapshot_id = "a" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-a", max_bytes=0, ttl_seconds=0)

    entry, published = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)
    assert published["published"] is True
    assert published["verified_files"] == 2
    assert published["bundle_bytes"] == entry.bundle_bytes
    assert published["maintenance"]["evicted_entries"] == 0

    resolved = cache.resolve(snapshot_id)
    assert resolved is not None
    restored, stats = cache.restore(resolved, tmp_path / "task-work")

    cache_image = entry.bundle / "dataset/images/train/img-1.jpg"
    restored_image = restored / "dataset/images/train/img-1.jpg"
    cache_label = entry.bundle / "dataset/labels/train/img-1.txt"
    restored_label = restored / "dataset/labels/train/img-1.txt"
    assert restored_image.read_bytes() == b"train-image-bytes"
    assert stats["hardlinked_images"] == 0
    assert stats["hardlinked_image_bytes"] == 0
    assert stats["copied_images"] == 2
    assert stats["copied_image_bytes"] == len(b"train-image-bytes") + len(b"test-image-bytes")
    assert stats["cache_bundle_bytes"] == entry.bundle_bytes
    assert stats["cache_last_access_ns"] > 0
    assert not os.path.samefile(cache_image, restored_image)
    assert not os.path.samefile(cache_label, restored_label)

    restored_image.write_bytes(b"rewritten-by-trainer")
    assert cache_image.read_bytes() == b"train-image-bytes"

def test_cache_resolve_rejects_missing_member_without_rehashing_images(monkeypatch, tmp_path):
    snapshot_id = "b" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-b", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    image = entry.bundle / "dataset/images/train/img-1.jpg"
    image.unlink()

    assert cache.resolve(snapshot_id) is None



def test_cache_restore_never_attempts_image_hardlinks(monkeypatch, tmp_path):
    snapshot_id = "c" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-c", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    monkeypatch.setattr(
        training_bundle_cache.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hardlink must not be used")),
    )
    restored, stats = cache.restore(entry, tmp_path / "task-work")
    assert stats["hardlinked_images"] == 0
    assert stats["hardlinked_image_bytes"] == 0
    assert stats["copied_images"] == 2
    assert stats["copied_image_bytes"] == len(b"train-image-bytes") + len(b"test-image-bytes")
    assert (restored / "dataset/images/test/img-2.jpg").read_bytes() == b"test-image-bytes"

def test_cache_publish_requires_final_verified_file_count(tmp_path):
    snapshot_id = "d" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-d", max_bytes=0, ttl_seconds=0)

    with pytest.raises(ValueError, match="file count"):
        cache.publish_verified(source_bundle, snapshot_id, verified_files=1)
    assert cache.resolve(snapshot_id) is None


def test_cache_is_project_scoped(tmp_path):
    snapshot_id = "e" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    left = TrainingBundleCache(tmp_path / "data", "project-left", max_bytes=0, ttl_seconds=0)
    right = TrainingBundleCache(tmp_path / "data", "project-right", max_bytes=0, ttl_seconds=0)

    left.publish_verified(source_bundle, snapshot_id, verified_files=2)
    assert left.resolve(snapshot_id) is not None
    assert right.resolve(snapshot_id) is None


def test_indexed_cache_lookup_requires_locked_hash_and_size():
    from platform_core.training_tasks import _indexed_content_identity_ready

    assert _indexed_content_identity_ready(
        [{"content_sha256": "f" * 64, "size_bytes": 123}]
    )
    assert not _indexed_content_identity_ready(
        [{"content_sha256": "", "size_bytes": 123}]
    )
    assert not _indexed_content_identity_ready(
        [{"content_sha256": "f" * 64, "size_bytes": 0}]
    )


def test_cache_resolve_rejects_tampered_label(tmp_path):
    snapshot_id = "1" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-label-integrity", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    (entry.bundle / "dataset/labels/train/img-1.txt").write_text(
        "0 0.1 0.1 0.1 0.1", encoding="utf-8"
    )
    assert cache.resolve(snapshot_id) is None


def test_cache_resolve_rejects_tampered_data_yaml(tmp_path):
    snapshot_id = "2" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-yaml-integrity", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    (entry.bundle / "dataset/data.yaml").write_text(
        "path: .\ntrain: images/other\n", encoding="utf-8"
    )
    assert cache.resolve(snapshot_id) is None


def test_cache_resolve_rejects_in_bundle_symlink_component(tmp_path):
    snapshot_id = "3" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-link-integrity", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    data_yaml = entry.bundle / "dataset/data.yaml"
    target = entry.bundle / "dataset/data-target.yaml"
    target.write_bytes(data_yaml.read_bytes())
    data_yaml.unlink()
    try:
        data_yaml.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")
    assert cache.resolve(snapshot_id) is None


def test_cache_publication_is_ordered_after_algorithm_version_attachment():
    import inspect

    from platform_core.training_tasks import TrainingHandler

    source = inspect.getsource(TrainingHandler._finalize_completed_job)
    assert source.index("attach_version(") < source.index(").publish_verified(")
    assert source.index(").publish_verified(") < source.index('"stage": "committed"')


def test_cache_resolve_refreshes_lru_access_metadata(monkeypatch, tmp_path):
    snapshot_id = "4" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-access", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    expected = 9_000_000_000
    monkeypatch.setattr(training_bundle_cache.time, "time_ns", lambda: expected)
    resolved = cache.resolve(snapshot_id)

    assert resolved is not None
    assert resolved.last_access_ns == expected
    access = json.loads((entry.root / "access.json").read_text(encoding="utf-8"))
    assert access["last_access_ns"] == expected


def test_cache_ttl_expiry_blocks_reuse_and_maintenance_evicts(monkeypatch, tmp_path):
    snapshot_id = "5" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-ttl", max_bytes=0, ttl_seconds=1)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)
    _set_access_ns(entry.root, 1)

    monkeypatch.setattr(
        training_bundle_cache.time,
        "time_ns",
        lambda: 600_000_000_000,
    )
    assert cache.resolve(snapshot_id) is None

    maintenance = cache.maintain()
    assert maintenance["ttl_evictions"] == 1
    assert maintenance["evicted_entries"] == 1
    assert maintenance["after_bytes"] == 0
    assert not entry.root.exists()


def test_cache_quota_evicts_lru_entry_but_protects_new_publish(tmp_path):
    first_id = "6" * 64
    second_id = "7" * 64
    first_source = _write_bundle(tmp_path / "source-first", snapshot_id=first_id)
    second_source = _write_bundle(tmp_path / "source-second", snapshot_id=second_id)
    unbounded = TrainingBundleCache(
        tmp_path / "data",
        "project-quota",
        max_bytes=0,
        ttl_seconds=0,
    )
    first, _ = unbounded.publish_verified(first_source, first_id, verified_files=2)
    _set_access_ns(first.root, 1)

    bounded = TrainingBundleCache(
        tmp_path / "data",
        "project-quota",
        max_bytes=first.bundle_bytes + 1,
        ttl_seconds=0,
    )
    second, published = bounded.publish_verified(
        second_source,
        second_id,
        verified_files=2,
    )

    maintenance = published["maintenance"]
    assert maintenance["quota_evictions"] == 1
    assert maintenance["evicted_snapshot_ids"] == [first_id]
    assert maintenance["over_budget_bytes"] == 0
    assert bounded.resolve(first_id) is None
    assert bounded.resolve(second_id) is not None
    assert second.root.exists()


def test_cache_maintenance_skips_locked_active_entry(monkeypatch, tmp_path):
    snapshot_id = "8" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-active", max_bytes=0, ttl_seconds=1)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)
    _set_access_ns(entry.root, 1)
    monkeypatch.setattr(
        training_bundle_cache.time,
        "time_ns",
        lambda: 600_000_000_000,
    )

    with cache._lock(snapshot_id):
        maintenance = cache.maintain()

    assert maintenance["skipped_locked"] == 1
    assert maintenance["evicted_entries"] == 0
    assert entry.root.exists()


def test_cache_lifecycle_environment_requires_non_negative_integer(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_MAX_BYTES_ENV, "-1")
    with pytest.raises(ValueError, match=CACHE_MAX_BYTES_ENV):
        TrainingBundleCache(tmp_path / "data", "project-config")

    monkeypatch.delenv(CACHE_MAX_BYTES_ENV)
    monkeypatch.setenv(CACHE_TTL_SECONDS_ENV, "not-a-number")
    with pytest.raises(ValueError, match=CACHE_TTL_SECONDS_ENV):
        TrainingBundleCache(tmp_path / "data", "project-config")

def test_cache_schema_v2_is_rejected_after_writable_hardlink_fix(tmp_path):
    snapshot_id = "0" * 64
    source_bundle = _write_bundle(tmp_path / "source-schema", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-schema", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)
    marker_path = entry.root / "cache.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["schema_version"] = 2
    marker_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")

    assert cache.resolve(snapshot_id) is None



def test_cache_restore_preserves_dataset_revision_evidence(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    snapshot_id = "a" * 64
    revision_id = "b" * 64
    (source / "snapshot.json").write_text(
        json.dumps({"snapshot_id": snapshot_id, "dataset_revision_id": revision_id}),
        encoding="utf-8",
    )
    (source / "dataset-revision.json").write_text(
        json.dumps({"dataset_revision_id": revision_id}),
        encoding="utf-8",
    )
    (source / "data.yaml").write_text("path: .\n", encoding="utf-8")
    (source / "images").mkdir()
    (source / "labels").mkdir()
    (source / "images" / "a.jpg").write_bytes(b"jpeg")
    (source / "labels" / "a.txt").write_text("", encoding="utf-8")
    import hashlib, json
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 3,
        "snapshot_id": snapshot_id,
        "dataset_revision_id": revision_id,
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": sha(source / "snapshot.json"),
        "dataset_revision_ref": "dataset-revision.json",
        "dataset_revision_sha256": sha(source / "dataset-revision.json"),
        "data_yaml_ref": "data.yaml",
        "splits": {"train": [{
            "image_id": "a",
            "image_ref": "images/a.jpg",
            "label_ref": "labels/a.txt",
            "size_bytes": 4,
            "label_sha256": sha(source / "labels" / "a.txt"),
        }], "validation": [], "test": []},
    }
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    cache = TrainingBundleCache(tmp_path / "data", "project", max_bytes=0, ttl_seconds=0)
    entry, _ = cache.publish_verified(source, snapshot_id, verified_files=1)
    restored, _ = cache.restore(entry, tmp_path / "work")
    assert (restored / "dataset-revision.json").read_bytes() == (source / "dataset-revision.json").read_bytes()
