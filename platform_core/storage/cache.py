from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from filelock import FileLock, Timeout

from .base import StorageProvider
from .errors import StorageError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CACHE_FILE = re.compile(r"^([0-9a-f]{64})(\.[a-z0-9]{1,12}|\.bin)$")
MATERIAL_CACHE_MAX_BYTES_ENV = "MATERIAL_CACHE_MAX_BYTES"
MATERIAL_CACHE_TTL_SECONDS_ENV = "MATERIAL_CACHE_TTL_SECONDS"
MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS_ENV = "MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS"
MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS_ENV = "MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS"
DEFAULT_MATERIAL_CACHE_MAX_BYTES = 128 * 1024 * 1024 * 1024
DEFAULT_MATERIAL_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
DEFAULT_MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS = 5 * 60
DEFAULT_MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS = 10 * 60


def _configured_non_negative_int(name: str, default: int, override: int | None) -> int:
    raw: int | str = override if override is not None else os.environ.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class MaterializedFile:
    path: Path
    content_sha256: str
    size_bytes: int
    cache_hit: bool


@dataclass(frozen=True)
class _CacheCandidate:
    path: Path
    size_bytes: int
    last_access_ns: int


class MaterialCache:
    """Worker-local, content-addressed cache for remote material objects.

    Cached payloads are immutable by SHA256. File mtime is intentionally used as
    mutable access metadata so lifecycle maintenance does not need one sidecar per
    object. Cleanup is best-effort and always respects the same per-object lock as
    materialization.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int | None = None,
        ttl_seconds: int | None = None,
        maintenance_interval_seconds: int | None = None,
        recent_access_grace_seconds: int | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.max_bytes = _configured_non_negative_int(
            MATERIAL_CACHE_MAX_BYTES_ENV,
            DEFAULT_MATERIAL_CACHE_MAX_BYTES,
            max_bytes,
        )
        self.ttl_seconds = _configured_non_negative_int(
            MATERIAL_CACHE_TTL_SECONDS_ENV,
            DEFAULT_MATERIAL_CACHE_TTL_SECONDS,
            ttl_seconds,
        )
        self.maintenance_interval_seconds = _configured_non_negative_int(
            MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS_ENV,
            DEFAULT_MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS,
            maintenance_interval_seconds,
        )
        self.recent_access_grace_seconds = _configured_non_negative_int(
            MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS_ENV,
            DEFAULT_MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS,
            recent_access_grace_seconds,
        )
        self._last_maintenance_monotonic = 0.0

    @staticmethod
    def _suffix(value: str) -> str:
        suffix = str(value or "").lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
            return ".bin"
        return suffix

    def path_for(self, content_sha256: str, suffix: str = ".bin") -> Path:
        expected = str(content_sha256 or "").lower()
        if not _SHA256.fullmatch(expected):
            raise ValueError("expected SHA256 must contain 64 lowercase hexadecimal characters")
        return self.root / expected[:2] / f"{expected}{self._suffix(suffix)}"

    def _valid(self, path: Path, expected: str) -> bool:
        return path.is_file() and path.stat().st_size > 0 and file_sha256(path) == expected

    @staticmethod
    def _touch(path: Path, *, now_ns: int | None = None) -> None:
        try:
            if now_ns is None:
                os.utime(path, None)
            else:
                os.utime(path, ns=(int(now_ns), int(now_ns)))
        except OSError:
            # Access metadata must never turn a valid cache hit into a task failure.
            pass

    def _candidate_files(self) -> list[_CacheCandidate]:
        if not self.root.exists():
            return []
        candidates: list[_CacheCandidate] = []
        try:
            prefixes = list(self.root.iterdir())
        except OSError:
            return []
        for prefix in prefixes:
            try:
                if prefix.is_symlink() or not prefix.is_dir() or not re.fullmatch(r"[0-9a-f]{2}", prefix.name):
                    continue
                items = list(prefix.iterdir())
            except OSError:
                continue
            for path in items:
                match = _CACHE_FILE.fullmatch(path.name)
                if not match or match.group(1)[:2] != prefix.name:
                    continue
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    info = path.stat()
                except OSError:
                    continue
                if info.st_size <= 0:
                    continue
                candidates.append(
                    _CacheCandidate(
                        path=path,
                        size_bytes=int(info.st_size),
                        last_access_ns=int(info.st_mtime_ns),
                    )
                )
        return candidates

    def _protected_paths(self, values: Iterable[str | Path]) -> set[Path]:
        protected: set[Path] = set()
        for value in values:
            try:
                candidate = Path(value).resolve()
                candidate.relative_to(self.root)
            except (OSError, ValueError):
                continue
            protected.add(candidate)
        return protected

    def maintain(
        self,
        *,
        protect_paths: Iterable[str | Path] = (),
        now_ns: int | None = None,
    ) -> dict[str, int]:
        """Apply TTL/LRU lifecycle limits without touching recent or locked files."""
        current_ns = int(time.time_ns() if now_ns is None else now_ns)
        protected = self._protected_paths(protect_paths)
        candidates = self._candidate_files()
        before_bytes = sum(item.size_bytes for item in candidates)
        retained_bytes = before_bytes
        evicted_files = 0
        evicted_bytes = 0
        ttl_evictions = 0
        quota_evictions = 0
        skipped_recent = 0
        skipped_locked = 0
        skipped_protected = 0
        eviction_failures = 0
        removed: set[Path] = set()
        grace_ns = self.recent_access_grace_seconds * 1_000_000_000

        def evict(candidate: _CacheCandidate, *, reason: str) -> bool:
            nonlocal retained_bytes, evicted_files, evicted_bytes
            nonlocal ttl_evictions, quota_evictions
            nonlocal skipped_recent, skipped_locked, skipped_protected, eviction_failures
            resolved = candidate.path.resolve()
            if resolved in protected:
                skipped_protected += 1
                return False
            try:
                resolved.relative_to(self.root)
            except ValueError:
                eviction_failures += 1
                return False
            try:
                latest = candidate.path.stat()
            except FileNotFoundError:
                retained_bytes = max(0, retained_bytes - candidate.size_bytes)
                removed.add(resolved)
                return True
            except OSError:
                eviction_failures += 1
                return False
            if grace_ns > 0 and current_ns - int(latest.st_mtime_ns) <= grace_ns:
                skipped_recent += 1
                return False
            try:
                lock = FileLock(str(candidate.path) + ".lock", timeout=0)
                with lock:
                    try:
                        latest = candidate.path.stat()
                    except FileNotFoundError:
                        retained_bytes = max(0, retained_bytes - candidate.size_bytes)
                        removed.add(resolved)
                        return True
                    if grace_ns > 0 and current_ns - int(latest.st_mtime_ns) <= grace_ns:
                        skipped_recent += 1
                        return False
                    size = int(latest.st_size)
                    candidate.path.unlink()
            except Timeout:
                skipped_locked += 1
                return False
            except OSError:
                eviction_failures += 1
                return False
            retained_bytes = max(0, retained_bytes - size)
            evicted_files += 1
            evicted_bytes += size
            if reason == "ttl":
                ttl_evictions += 1
            else:
                quota_evictions += 1
            removed.add(resolved)
            return True

        if self.ttl_seconds > 0:
            ttl_ns = self.ttl_seconds * 1_000_000_000
            for candidate in sorted(candidates, key=lambda item: (item.last_access_ns, str(item.path))):
                if current_ns - candidate.last_access_ns > ttl_ns:
                    evict(candidate, reason="ttl")

        if self.max_bytes > 0 and retained_bytes > self.max_bytes:
            for candidate in sorted(candidates, key=lambda item: (item.last_access_ns, str(item.path))):
                if retained_bytes <= self.max_bytes:
                    break
                if candidate.path.resolve() in removed:
                    continue
                evict(candidate, reason="quota")

        return {
            "max_bytes": self.max_bytes,
            "ttl_seconds": self.ttl_seconds,
            "maintenance_interval_seconds": self.maintenance_interval_seconds,
            "recent_access_grace_seconds": self.recent_access_grace_seconds,
            "scanned_files": len(candidates),
            "before_bytes": before_bytes,
            "after_bytes": retained_bytes,
            "evicted_files": evicted_files,
            "evicted_bytes": evicted_bytes,
            "ttl_evictions": ttl_evictions,
            "quota_evictions": quota_evictions,
            "skipped_recent": skipped_recent,
            "skipped_locked": skipped_locked,
            "skipped_protected": skipped_protected,
            "eviction_failures": eviction_failures,
            "over_budget_bytes": (
                max(0, retained_bytes - self.max_bytes)
                if self.max_bytes > 0
                else 0
            ),
        }

    def _maybe_maintain(self, *, protect_path: Path) -> None:
        interval = self.maintenance_interval_seconds
        now = time.monotonic()
        if interval > 0 and self._last_maintenance_monotonic and now - self._last_maintenance_monotonic < interval:
            return
        self._last_maintenance_monotonic = now
        try:
            self.maintain(protect_paths=(protect_path,))
        except Exception:
            # Cache cleanup is an optimization. It must never make source access fail.
            return

    def materialize(
        self, provider: StorageProvider, object_key: str, *,
        expected_sha256: str, suffix: str = ".bin",
    ) -> MaterializedFile:
        expected = str(expected_sha256 or "").lower()
        target = self.path_for(expected, suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._maybe_maintain(protect_path=target)
        lock = FileLock(str(target) + ".lock", timeout=300)
        with lock:
            if self._valid(target, expected):
                self._touch(target)
                return MaterializedFile(target, expected, target.stat().st_size, True)
            target.unlink(missing_ok=True)
            temporary = target.parent / f".part-{uuid.uuid4().hex}.tmp"
            try:
                provider.materialize_to_local(object_key, temporary)
                if not temporary.is_file() or temporary.stat().st_size <= 0:
                    raise StorageError(
                        code="STORAGE_EMPTY_OBJECT", message="远程素材为空",
                        detail=f"下载后的素材 {object_key} 为零字节。",
                        solution="请检查源对象是否上传完整。",
                        context={"source_id": provider.source_id, "object_key": object_key},
                    )
                actual = file_sha256(temporary)
                if actual != expected:
                    raise StorageError(
                        code="STORAGE_SHA256_MISMATCH", message="素材完整性校验失败",
                        detail=f"素材 {object_key} 的 SHA256 与索引记录不一致。",
                        solution="请重新扫描或重新上传该素材，禁止继续训练。",
                        context={"source_id": provider.source_id, "object_key": object_key, "expected_sha256": expected, "actual_sha256": actual},
                    )
                os.replace(temporary, target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            if not self._valid(target, expected):
                target.unlink(missing_ok=True)
                raise StorageError(
                    code="STORAGE_CACHE_WRITE_FAILED", message="素材缓存写入失败",
                    detail=f"缓存文件 {target.name} 未通过最终校验。",
                    solution="请检查缓存目录权限和磁盘空间。",
                    context={"source_id": provider.source_id, "object_key": object_key},
                )
            self._touch(target)
            return MaterializedFile(target, expected, target.stat().st_size, False)
