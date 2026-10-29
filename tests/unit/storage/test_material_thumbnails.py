import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from platform_core.storage.cache import MaterialCache, file_sha256


def source(tmp_path):
    path = tmp_path / "original.jpg"
    image = Image.new("RGB", (800, 400), "red")
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)
    return path


def test_thumbnail_exif_fit_cached_and_regenerated_after_damage(tmp_path):
    original = source(tmp_path)
    original_bytes = original.read_bytes()
    cache = MaterialCache(tmp_path / "cache")
    calls = []
    def fetch():
        calls.append(True)
        return original
    result = cache.thumbnail(file_sha256(original), fetch, max_edge=200)
    with Image.open(result) as image:
        assert image.size == (100, 200)
    assert cache.thumbnail(file_sha256(original), fetch, max_edge=200) == result
    assert len(calls) == 1
    result.write_bytes(b"corrupt")
    rebuilt = cache.thumbnail(file_sha256(original), fetch, max_edge=200)
    assert rebuilt == result and len(calls) == 2
    assert file_sha256(rebuilt) == rebuilt.stem
    assert original.read_bytes() == original_bytes


def test_concurrent_thumbnail_creation_uses_original_cache_lock(tmp_path):
    original = source(tmp_path)
    cache = MaterialCache(tmp_path / "cache")
    calls = []
    def fetch():
        calls.append(True)
        return original
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: cache.thumbnail(file_sha256(original), fetch, max_edge=120), range(4)))
    assert len(set(paths)) == 1
    assert len(calls) == 1


def test_thumbnail_files_obey_original_cache_quota_and_regenerate(tmp_path):
    original = source(tmp_path)
    cache = MaterialCache(tmp_path / "cache", max_bytes=1, recent_access_grace_seconds=0)
    path = cache.thumbnail(file_sha256(original), lambda: original, max_edge=120)
    assert path.exists()
    result = cache.maintain()
    assert result["evicted_files"] >= 1
    assert not path.exists()
    assert cache.thumbnail(file_sha256(original), lambda: original, max_edge=120).exists()


def test_thumbnail_rejects_source_identity_change_and_unknown_hash(tmp_path):
    original = source(tmp_path)
    cache = MaterialCache(tmp_path / "cache")
    with pytest.raises(ValueError):
        cache.thumbnail("", lambda: original)
    with pytest.raises(ValueError, match="source"):
        cache.thumbnail("b" * 64, lambda: original)
    assert not list((tmp_path / "cache").rglob("*.jpg"))


def test_manager_thumbnail_is_readonly_and_valid_hit_never_materializes_again(tmp_path, monkeypatch):
    from platform_core.material_repository import MaterialRepository
    from platform_core.storage.manager import StorageManager
    data = tmp_path / "data"
    project = data / "projects/p"
    (project / "uploads").mkdir(parents=True)
    original = source(project / "uploads")
    owner = MaterialRepository(project)
    owner.upsert({"id": "image", "filename": original.name, "content_sha256": file_sha256(original), "size_bytes": 0})
    manager = StorageManager(data_dir=data, project_id="p", materials=owner)
    before = owner.get("image")
    thumbnail = manager.thumbnail("image", max_edge=120)
    assert thumbnail.exists() and owner.get("image") == before
    monkeypatch.setattr(manager, "materialize", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("cache hit refetched source")))
    assert manager.thumbnail("image", max_edge=120) == thumbnail
    owner.upsert({**before, "content_sha256": ""})
    with pytest.raises(ValueError):
        manager.thumbnail("image")
    assert not owner.get("image")["content_sha256"]


def test_existing_cache_maintenance_respects_thumbnail_response_lock(tmp_path):
    from filelock import FileLock
    original = source(tmp_path)
    cache = MaterialCache(tmp_path / "cache", max_bytes=1, recent_access_grace_seconds=0)
    thumbnail = cache.thumbnail(file_sha256(original), lambda: original, max_edge=120)
    with FileLock(str(thumbnail) + ".lock"):
        result = cache.maintain()
        assert thumbnail.exists()
        assert result["skipped_locked"] >= 1
    cache.maintain()
    assert not thumbnail.exists()


def test_http_lease_uses_one_hash_and_blocks_eviction(tmp_path, monkeypatch):
    from platform_core.storage import cache as cache_module
    original = source(tmp_path)
    cache = MaterialCache(tmp_path / "cache", max_bytes=1, recent_access_grace_seconds=0)
    digest = file_sha256(original)
    thumbnail = cache.thumbnail(digest, lambda: original, max_edge=120)
    calls = []
    original_hash = cache_module.file_sha256

    def counted(path):
        calls.append(str(path))
        return original_hash(path)

    monkeypatch.setattr(cache_module, "file_sha256", counted)
    path, lease = cache.thumbnail(digest, lambda: (_ for _ in ()).throw(AssertionError("cache miss")),
                                  max_edge=120, hold_verified_lock=True)
    try:
        assert path == thumbnail
        assert calls == [str(thumbnail)]
        assert cache.maintain()["skipped_locked"] >= 1
        assert thumbnail.exists()
    finally:
        lease.release()
