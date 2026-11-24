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
    assert source.index("attach_version_if_current(") < source.index(").publish_verified(")
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
    import hashlib
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


def _publish_bundle(tmp_path, snapshot_id, project_id="project-idle"):
    source = _write_bundle(tmp_path / ("source-" + snapshot_id[:6]), snapshot_id=snapshot_id)
    (tmp_path / "data" / "cache" / "training-bundles").mkdir(parents=True, exist_ok=True)
    cache = TrainingBundleCache(tmp_path / "data", project_id, max_bytes=0, ttl_seconds=1)
    entry, _ = cache.publish_verified(source, snapshot_id, verified_files=2)
    return cache, entry


def _expire_entries(*entries):
    for entry in entries:
        _set_access_ns(entry.root, 1)


def test_cache_maintenance_dry_run_reports_without_deleting(monkeypatch, tmp_path):
    snapshot_id = "a" * 64
    cache, entry = _publish_bundle(tmp_path, snapshot_id)
    _expire_entries(entry)
    monkeypatch.setattr(
        training_bundle_cache.time, "time_ns", lambda: 600_000_000_000,
    )
    preview = cache.maintain(dry_run=True)
    assert preview["dry_run"] is True
    assert preview["evicted_entries"] == 0
    assert preview["would_evict_entries"] == 1
    assert preview["would_evict_snapshot_ids"] == [snapshot_id]
    assert preview["after_bytes"] == 0
    assert entry.root.exists(), "dry run must not delete cache content"

    applied = cache.maintain()
    assert applied["evicted_entries"] == 1
    assert not entry.root.exists()


def _training_task_with_snapshot(tmp_path, *, task_id, snapshot_id, status=None):
    from platform_core.task_runtime import (
        ArtifactStore, TaskKind, TaskRecord, TaskRepository,
    )
    runtime = tmp_path / "data" / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    artifacts.atomic_write_json(task_id, "request.json", {
        "snapshot_id": snapshot_id, "schema_version": 4,
    })
    repository.create(TaskRecord.new(
        task_id=task_id,
        project_id="project-idle",
        kind=TaskKind.TRAINING,
        payload_ref="request.json",
        resource_key=f"training:{task_id}",
    ), artifacts=artifacts)
    if status is not None:
        with repository._connect() as database:
            database.execute(
                "UPDATE tasks SET status=? WHERE task_id=?", (status, task_id),
            )
            database.commit()
    return repository, artifacts


def test_idle_bundle_cache_sweep_skips_while_training_task_active(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_TTL_SECONDS_ENV, "1")
    active_snapshot = "b" * 64
    stale_snapshot = "c" * 64
    repository, artifacts = _training_task_with_snapshot(
        tmp_path, task_id="active-training", snapshot_id=active_snapshot,
    )
    _cache_active, active_entry = _publish_bundle(tmp_path, active_snapshot)
    _cache_stale, stale_entry = _publish_bundle(tmp_path, stale_snapshot)
    _expire_entries(active_entry, stale_entry)
    monkeypatch.setattr(
        training_bundle_cache.time, "time_ns", lambda: 600_000_000_000,
    )

    skipped = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts, dry_run=False,
    )
    assert skipped["ran"] is False
    assert skipped["skipped"] == "active_training_tasks"
    assert skipped["active_tasks"] == ["active-training"]
    assert active_entry.root.exists() and stale_entry.root.exists()

    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET status='SUCCEEDED' WHERE task_id='active-training'",
        )
        database.commit()
    preview = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts, dry_run=True,
    )
    assert preview["ran"] is True and preview["dry_run"] is True
    assert preview["totals"]["would_evict_entries"] == 2

    applied = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts, dry_run=False,
    )
    assert applied["ran"] is True
    assert applied["totals"]["evicted_entries"] == 2
    assert applied["errors"] == []
    assert not active_entry.root.exists() and not stale_entry.root.exists()


def test_idle_bundle_cache_sweep_protects_snapshot_of_active_task_in_dry_run(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv(CACHE_TTL_SECONDS_ENV, "1")
    protected_snapshot = "d" * 64
    other_snapshot = "e" * 64
    repository, artifacts = _training_task_with_snapshot(
        tmp_path, task_id="cancel-requested", snapshot_id=protected_snapshot,
    )
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id='cancel-requested'",
        )
        database.commit()
    _cache_a, protected_entry = _publish_bundle(tmp_path, protected_snapshot)
    _cache_b, other_entry = _publish_bundle(tmp_path, other_snapshot)
    _expire_entries(protected_entry, other_entry)
    monkeypatch.setattr(
        training_bundle_cache.time, "time_ns", lambda: 600_000_000_000,
    )
    preview = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts, dry_run=True,
    )
    assert preview["ran"] is True
    assert preview["protected_snapshot_count"] == 1
    assert preview["totals"]["would_evict_entries"] == 1
    assert protected_entry.root.exists() and other_entry.root.exists()
    project = preview["projects"][0]
    assert project["skipped_protected"] >= 1


def test_idle_bundle_cache_sweep_isolates_broken_project(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_TTL_SECONDS_ENV, "1")
    good_snapshot = "f" * 64
    repository, artifacts = _training_task_with_snapshot(
        tmp_path, task_id="done-training", snapshot_id="0" * 64, status="SUCCEEDED",
    )
    _cache, good_entry = _publish_bundle(tmp_path, good_snapshot, project_id="project-good")
    base = tmp_path / "data" / "cache" / "training-bundles"
    (base / "project-broken").mkdir(parents=True, exist_ok=True)
    _expire_entries(good_entry)

    original_init = training_bundle_cache.TrainingBundleCache

    class ExplodingCache(original_init):
        def __init__(self, data_dir, project_id, **kwargs):
            super().__init__(data_dir, project_id, **kwargs)
            if project_id == "project-broken":
                raise RuntimeError("injected broken cache project")

    monkeypatch.setattr(training_bundle_cache, "TrainingBundleCache", ExplodingCache)
    result = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts, dry_run=False,
    )
    assert result["ran"] is True
    assert [item["project_id"] for item in result["errors"]] == ["project-broken"]
    assert not good_entry.root.exists()


def test_bundle_cache_maintenance_interval_environment(monkeypatch):
    monkeypatch.delenv(
        training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_SECONDS_ENV,
        raising=False,
    )
    # Scheduled cache maintenance is opt-in by default: a new/upgraded
    # deployment must not start scanning project caches silently.
    assert training_bundle_cache.DEFAULT_TRAINING_BUNDLE_CACHE_MAINTENANCE_SECONDS == 0
    assert (
        training_bundle_cache.training_bundle_cache_maintenance_interval_seconds()
        == 0
    )
    monkeypatch.setenv(
        training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_SECONDS_ENV, "0",
    )
    assert training_bundle_cache.training_bundle_cache_maintenance_interval_seconds() == 0
    monkeypatch.setenv(
        training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_SECONDS_ENV, "-5",
    )
    assert training_bundle_cache.training_bundle_cache_maintenance_interval_seconds() == 0
    monkeypatch.setenv(
        training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_SECONDS_ENV, "not-a-number",
    )
    assert training_bundle_cache.training_bundle_cache_maintenance_interval_seconds() == 0
    monkeypatch.setenv(
        training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_SECONDS_ENV, "3600",
    )
    assert training_bundle_cache.training_bundle_cache_maintenance_interval_seconds() == 3600


def test_scheduled_cache_maintenance_delete_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv(
        training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_DELETE_ENV,
        raising=False,
    )
    assert training_bundle_cache.training_bundle_cache_maintenance_delete_enabled() is False
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv(
            training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_DELETE_ENV, value,
        )
        assert (
            training_bundle_cache.training_bundle_cache_maintenance_delete_enabled()
            is False
        ), value
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(
            training_bundle_cache.TRAINING_BUNDLE_CACHE_MAINTENANCE_DELETE_ENV, value,
        )
        assert (
            training_bundle_cache.training_bundle_cache_maintenance_delete_enabled()
            is True
        ), value


def test_idle_bundle_cache_sweep_defaults_to_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_TTL_SECONDS_ENV, "1")
    snapshot_id = "1" * 64
    repository, artifacts = _training_task_with_snapshot(
        tmp_path, task_id="done-training", snapshot_id=snapshot_id, status="SUCCEEDED",
    )
    _cache, entry = _publish_bundle(tmp_path, snapshot_id)
    _expire_entries(entry)
    monkeypatch.setattr(
        training_bundle_cache.time, "time_ns", lambda: 600_000_000_000,
    )
    preview = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts,
    )
    assert preview["dry_run"] is True
    assert preview["totals"]["would_evict_entries"] == 1
    assert preview["totals"]["evicted_entries"] == 0
    assert entry.root.exists(), "a scheduled sweep without opt-in must not delete"


def test_sweep_aborts_deletion_when_a_task_appears_mid_scan(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_TTL_SECONDS_ENV, "1")
    snapshot_id = "2" * 64
    repository, artifacts = _training_task_with_snapshot(
        tmp_path, task_id="done-training", snapshot_id=snapshot_id, status="SUCCEEDED",
    )
    _cache, entry = _publish_bundle(tmp_path, snapshot_id)
    _expire_entries(entry)
    monkeypatch.setattr(
        training_bundle_cache.time, "time_ns", lambda: 600_000_000_000,
    )
    initial = {"task_ids": [], "hold_task_ids": [], "snapshot_ids": []}
    raced = {"task_ids": ["new-task"], "hold_task_ids": [], "snapshot_ids": []}
    calls = {"count": 0}

    def fake_protection(_repository, _artifacts):
        calls["count"] += 1
        return dict(initial if calls["count"] == 1 else raced)

    monkeypatch.setattr(
        training_bundle_cache, "active_training_cache_protection", fake_protection,
    )
    result = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts, dry_run=False,
    )
    assert result["ran"] is True
    assert result["aborted"] == "protection_changed_during_scan"
    assert result["protection_rechecks"] == 1
    assert entry.root.exists(), "a task created during the scan must abort deletion"


def test_unreleased_resource_hold_blocks_actual_cache_deletion(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_TTL_SECONDS_ENV, "1")
    snapshot_id = "3" * 64
    repository, artifacts = _training_task_with_snapshot(
        tmp_path, task_id="held-terminal", snapshot_id=snapshot_id, status="SUCCEEDED",
    )
    with repository._connect() as database:
        database.execute(
            "CREATE TABLE IF NOT EXISTS execution_resource_holds ("
            "task_id TEXT PRIMARY KEY, node_id TEXT, assignment_generation INTEGER,"
            "execution_attempt INTEGER, gpu_uuid TEXT, state TEXT,"
            "proof_sha256 TEXT, proof_type TEXT, updated_at TEXT)"
        )
        database.execute(
            "INSERT OR REPLACE INTO execution_resource_holds VALUES"
            "('held-terminal','node-1',1,1,'GPU-A','HELD',NULL,NULL,'2026-11-24')"
        )
        database.commit()
    _cache, entry = _publish_bundle(tmp_path, snapshot_id)
    _expire_entries(entry)
    monkeypatch.setattr(
        training_bundle_cache.time, "time_ns", lambda: 600_000_000_000,
    )
    protection = training_bundle_cache.active_training_cache_protection(
        repository, artifacts,
    )
    assert protection["hold_task_ids"] == ["held-terminal"]
    assert snapshot_id in protection["snapshot_ids"]
    result = training_bundle_cache.maintain_all_training_bundle_caches(
        tmp_path / "data", repository, artifacts, dry_run=False,
    )
    assert result["ran"] is False
    assert result["skipped"] == "unreleased_resource_holds"
    assert entry.root.exists()
