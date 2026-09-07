from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock

from .base import StorageProvider
from .errors import StorageError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


class MaterialCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

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

    def materialize(
        self, provider: StorageProvider, object_key: str, *,
        expected_sha256: str, suffix: str = ".bin",
    ) -> MaterializedFile:
        expected = str(expected_sha256 or "").lower()
        target = self.path_for(expected, suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(target) + ".lock", timeout=300)
        with lock:
            if self._valid(target, expected):
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
            return MaterializedFile(target, expected, target.stat().st_size, False)
