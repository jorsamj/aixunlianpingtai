from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from platform_core.storage import MaterialCache, ObjectMetadata, StorageError


class DownloadProvider:
    source_id = "remote-a"

    def __init__(self, content: bytes):
        self.content = content
        self.downloads = 0
        self.lock = threading.Lock()

    def materialize_to_local(self, object_key, destination):
        del object_key
        with self.lock:
            self.downloads += 1
        time.sleep(0.02)
        Path(destination).write_bytes(self.content)
        return ObjectMetadata(key="a.jpg", size_bytes=len(self.content))


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_cache_first_materialization_misses_and_second_hits(tmp_path):
    content = b"remote-image"
    provider = DownloadProvider(content)
    cache = MaterialCache(tmp_path / "cache")

    first = cache.materialize(provider, "materials/a.jpg", expected_sha256=sha(content), suffix=".jpg")
    second = cache.materialize(provider, "materials/a.jpg", expected_sha256=sha(content), suffix=".jpg")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.path == second.path
    assert second.path.read_bytes() == content
    assert provider.downloads == 1


def test_cache_concurrent_same_hash_only_downloads_once(tmp_path):
    content = b"shared-content"
    provider = DownloadProvider(content)
    cache = MaterialCache(tmp_path / "cache")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda _index: cache.materialize(provider, "a.jpg", expected_sha256=sha(content), suffix=".jpg"),
            range(8),
        ))

    assert provider.downloads == 1
    assert sum(not item.cache_hit for item in results) == 1
    assert all(item.path.read_bytes() == content for item in results)


def test_cache_rejects_zero_byte_and_hash_mismatch_without_publishing_file(tmp_path):
    cache = MaterialCache(tmp_path / "cache")
    empty = DownloadProvider(b"")
    with pytest.raises(StorageError) as zero:
        cache.materialize(empty, "a.jpg", expected_sha256=sha(b"expected"), suffix=".jpg")
    assert zero.value.code == "STORAGE_EMPTY_OBJECT"

    wrong = DownloadProvider(b"wrong")
    expected = sha(b"right")
    with pytest.raises(StorageError) as mismatch:
        cache.materialize(wrong, "a.jpg", expected_sha256=expected, suffix=".jpg")
    assert mismatch.value.code == "STORAGE_SHA256_MISMATCH"
    assert not list((tmp_path / "cache").rglob(f"{expected}.jpg"))
    assert not list((tmp_path / "cache").rglob(".part-*.tmp"))


def test_corrupt_existing_cache_is_replaced_from_source(tmp_path):
    content = b"correct"
    expected = sha(content)
    cache = MaterialCache(tmp_path / "cache")
    target = cache.path_for(expected, ".jpg")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt")
    provider = DownloadProvider(content)

    result = cache.materialize(provider, "a.jpg", expected_sha256=expected, suffix=".jpg")
    assert result.cache_hit is False
    assert result.path.read_bytes() == content
    assert provider.downloads == 1
