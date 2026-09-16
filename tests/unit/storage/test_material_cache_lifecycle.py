from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from filelock import FileLock

from platform_core.storage.cache import MaterialCache


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _cached(cache: MaterialCache, content: bytes, *, suffix: str = ".jpg") -> Path:
    path = cache.path_for(_sha(content), suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_material_cache_ttl_evicts_old_content_but_keeps_recent_access(tmp_path):
    cache = MaterialCache(
        tmp_path / "cache",
        max_bytes=0,
        ttl_seconds=60,
        maintenance_interval_seconds=0,
        recent_access_grace_seconds=10,
    )
    old_path = _cached(cache, b"old")
    recent_path = _cached(cache, b"recent")
    now_ns = 2_000_000_000_000
    os.utime(old_path, ns=(now_ns - 120_000_000_000, now_ns - 120_000_000_000))
    os.utime(recent_path, ns=(now_ns - 5_000_000_000, now_ns - 5_000_000_000))

    result = cache.maintain(now_ns=now_ns)

    assert old_path.exists() is False
    assert recent_path.exists() is True
    assert result["ttl_evictions"] == 1
    assert result["evicted_files"] == 1


def test_material_cache_quota_uses_lru_and_never_evicts_explicitly_protected_file(tmp_path):
    cache = MaterialCache(
        tmp_path / "cache",
        max_bytes=8,
        ttl_seconds=0,
        maintenance_interval_seconds=0,
        recent_access_grace_seconds=0,
    )
    now_ns = 3_000_000_000_000
    oldest = _cached(cache, b"aaaa")
    middle = _cached(cache, b"bbbb")
    newest = _cached(cache, b"cccc")
    os.utime(oldest, ns=(now_ns - 30_000_000_000, now_ns - 30_000_000_000))
    os.utime(middle, ns=(now_ns - 20_000_000_000, now_ns - 20_000_000_000))
    os.utime(newest, ns=(now_ns - 10_000_000_000, now_ns - 10_000_000_000))

    result = cache.maintain(protect_paths=(oldest,), now_ns=now_ns)

    assert oldest.exists() is True
    assert middle.exists() is False
    assert newest.exists() is True
    assert result["quota_evictions"] == 1
    assert result["skipped_protected"] >= 1
    assert result["after_bytes"] <= 8


def test_material_cache_maintenance_skips_locked_file_instead_of_forcing_delete(tmp_path):
    cache = MaterialCache(
        tmp_path / "cache",
        max_bytes=1,
        ttl_seconds=0,
        maintenance_interval_seconds=0,
        recent_access_grace_seconds=0,
    )
    target = _cached(cache, b"locked-content")
    lock = FileLock(str(target) + ".lock", timeout=0)

    with lock:
        result = cache.maintain(now_ns=4_000_000_000_000)

    assert target.exists() is True
    assert result["skipped_locked"] == 1
    assert result["over_budget_bytes"] > 0


def test_material_cache_lifecycle_can_be_configured_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MATERIAL_CACHE_MAX_BYTES", "123")
    monkeypatch.setenv("MATERIAL_CACHE_TTL_SECONDS", "456")
    monkeypatch.setenv("MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS", "7")
    monkeypatch.setenv("MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS", "8")

    cache = MaterialCache(tmp_path / "cache")

    assert cache.max_bytes == 123
    assert cache.ttl_seconds == 456
    assert cache.maintenance_interval_seconds == 7
    assert cache.recent_access_grace_seconds == 8


def test_material_cache_maintenance_publishes_compact_observability_snapshot(tmp_path):
    cache = MaterialCache(
        tmp_path / "cache",
        max_bytes=1024,
        ttl_seconds=3600,
        maintenance_interval_seconds=0,
        recent_access_grace_seconds=0,
    )
    _cached(cache, b"visible")

    result = cache.maintain(now_ns=5_000_000_000_000)
    status = json.loads((cache.root / "status.json").read_text(encoding="utf-8"))

    assert status["cache_scope"] == "worker_local"
    assert status["cache_kind"] == "remote_material_content"
    assert status["after_bytes"] == result["after_bytes"]
    assert status["max_bytes"] == 1024
    assert status["ttl_seconds"] == 3600
    assert status["generated_at"]
