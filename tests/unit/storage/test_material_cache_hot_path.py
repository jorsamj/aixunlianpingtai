"""Material cache: one hash per cold miss and cancellation-safe temp cleanup."""

from __future__ import annotations

import hashlib

import pytest

from platform_core.storage import cache as cache_module
from platform_core.storage.cache import MaterialCache
from platform_core.storage.errors import StorageError


class _Provider:
    """Writes deterministic bytes for one object key and counts the calls."""

    source_id = "test-source"

    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = 0

    def materialize_to_local(self, object_key, target):
        self.calls += 1
        from pathlib import Path

        Path(target).write_bytes(self.payload)


def test_cold_miss_hashes_the_bytes_once(tmp_path, monkeypatch):
    payload = b"frozen-material-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    cache = MaterialCache(tmp_path / "cache")
    provider = _Provider(payload)
    hashed: list[str] = []
    real_file_sha256 = cache_module.file_sha256

    def counting(path):
        hashed.append(str(path))
        return real_file_sha256(path)

    monkeypatch.setattr(cache_module, "file_sha256", counting)
    materialized = cache.materialize(provider, "uploads/a.bin", expected_sha256=digest)
    assert materialized.path.is_file()
    assert provider.calls == 1
    # Exactly one content hash: the pre-rename verification. Re-hashing the final
    # name would read the same bytes twice for every freshly materialized material.
    assert len(hashed) == 1

    # A warm hit reads the file once to verify it and never downloads again.
    hit = cache.materialize(provider, "uploads/a.bin", expected_sha256=digest)
    assert hit.cache_hit is True and provider.calls == 1
    assert len(hashed) == 2


def test_cancellation_removes_the_partial_download(tmp_path):
    payload = b"bytes"

    class _Cancelled(_Provider):
        def materialize_to_local(self, object_key, target):
            from pathlib import Path

            Path(target).write_bytes(payload)
            raise KeyboardInterrupt()

    cache = MaterialCache(tmp_path / "cache")
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(KeyboardInterrupt):
        cache.materialize(_Cancelled(payload), "uploads/b.bin", expected_sha256=digest)
    leftovers = list((tmp_path / "cache").rglob(".part-*.tmp"))
    assert leftovers == []


def test_sha_mismatch_still_fails_and_leaves_no_partial(tmp_path):
    cache = MaterialCache(tmp_path / "cache")
    expected = hashlib.sha256(b"good").hexdigest()
    with pytest.raises(StorageError) as mismatch:
        cache.materialize(_Provider(b"bad"), "uploads/c.bin", expected_sha256=expected)
    assert mismatch.value.code == "STORAGE_SHA256_MISMATCH"
    assert list((tmp_path / "cache").rglob(".part-*.tmp")) == []
    assert not list((tmp_path / "cache").rglob("*.bin"))
