from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path

import pytest

from platform_core import training_bundle_cache
from platform_core.training_bundle_cache import TrainingBundleCache


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


def test_verified_bundle_cache_publishes_and_restores_with_image_hardlinks(tmp_path):
    snapshot_id = "a" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-a")

    entry, published = cache.publish_verified(
        source_bundle,
        snapshot_id,
        verified_files=2,
    )
    assert published["published"] is True
    assert published["verified_files"] == 2

    resolved = cache.resolve(snapshot_id)
    assert resolved is not None
    restored, stats = cache.restore(resolved, tmp_path / "task-work")

    cache_image = entry.bundle / "dataset/images/train/img-1.jpg"
    restored_image = restored / "dataset/images/train/img-1.jpg"
    cache_label = entry.bundle / "dataset/labels/train/img-1.txt"
    restored_label = restored / "dataset/labels/train/img-1.txt"
    assert restored_image.read_bytes() == b"train-image-bytes"
    assert stats["hardlinked_images"] == 2
    assert stats["copied_images"] == 0
    assert os.path.samefile(cache_image, restored_image)
    assert not os.path.samefile(cache_label, restored_label)


def test_cache_resolve_rejects_missing_member_without_rehashing_images(monkeypatch, tmp_path):
    snapshot_id = "b" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-b")
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    image = entry.bundle / "dataset/images/train/img-1.jpg"
    image.unlink()

    assert cache.resolve(snapshot_id) is None


def test_cache_restore_falls_back_to_copy_when_hardlink_is_unavailable(monkeypatch, tmp_path):
    snapshot_id = "c" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-c")
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    monkeypatch.setattr(
        training_bundle_cache.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")),
    )
    restored, stats = cache.restore(entry, tmp_path / "task-work")
    assert stats["hardlinked_images"] == 0
    assert stats["copied_images"] == 2
    assert (restored / "dataset/images/test/img-2.jpg").read_bytes() == b"test-image-bytes"


def test_cache_publish_requires_final_verified_file_count(tmp_path):
    snapshot_id = "d" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-d")

    with pytest.raises(ValueError, match="file count"):
        cache.publish_verified(source_bundle, snapshot_id, verified_files=1)
    assert cache.resolve(snapshot_id) is None


def test_cache_is_project_scoped(tmp_path):
    snapshot_id = "e" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    left = TrainingBundleCache(tmp_path / "data", "project-left")
    right = TrainingBundleCache(tmp_path / "data", "project-right")

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
