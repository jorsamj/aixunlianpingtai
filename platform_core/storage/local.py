from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import stat
import uuid
from pathlib import Path, PureWindowsPath
from typing import BinaryIO, Iterator, Mapping

from .errors import StorageError
from .models import ObjectMetadata, ObjectPage, StorageHealth, StorageType


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalStorageProvider:
    storage_type = StorageType.LOCAL

    def __init__(self, source_id: str, root: str | Path) -> None:
        self.source_id = str(source_id)
        self.root = Path(root).expanduser().resolve()

    def _path(self, object_key: str, *, allow_empty: bool = False) -> Path:
        raw = str(object_key or "")
        posix = Path(raw)
        windows = PureWindowsPath(raw)
        invalid = (
            (not raw and not allow_empty)
            or "\x00" in raw
            or "\\" in raw
            or posix.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or ".." in posix.parts
            or ".." in windows.parts
        )
        if invalid:
            raise StorageError(
                code="STORAGE_INVALID_OBJECT_KEY",
                message="素材对象路径无效",
                detail=f"对象路径不能越过存储根目录：{raw!r}",
                solution="请使用相对于存储根目录的正斜杠路径。",
                context={"source_id": self.source_id},
            )
        relative = Path(raw) if raw else Path()
        resolved = (self.root / relative).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise StorageError(
                code="STORAGE_INVALID_OBJECT_KEY",
                message="素材对象路径无效",
                detail="对象路径越过了存储根目录。",
                solution="请检查对象路径。",
                context={"source_id": self.source_id},
            )
        return resolved

    def health_check(self) -> StorageHealth:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.root.is_dir():
                raise NotADirectoryError(str(self.root))
            return StorageHealth.available(
                "本地存储目录可访问", details={"root": str(self.root)}
            )
        except OSError as error:
            return StorageHealth.unavailable(
                f"本地存储目录不可访问：{error}", details={"root": str(self.root)}
            )

    def _metadata(self, path: Path, *, object_key: str | None = None) -> ObjectMetadata:
        stat_result = path.stat()
        return ObjectMetadata(
            key=object_key if object_key is not None else path.relative_to(self.root).as_posix(),
            size_bytes=stat_result.st_size,
            etag=f'"{stat_result.st_mtime_ns:x}-{stat_result.st_size:x}"',
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            sha256=_sha256(path),
            last_modified=str(stat_result.st_mtime_ns),
        )

    def stat(self, object_key: str) -> ObjectMetadata:
        path = self._path(object_key)
        if not path.is_file():
            raise StorageError(
                code="STORAGE_OBJECT_NOT_FOUND",
                message="素材文件不存在",
                detail=f"本地存储中找不到 {object_key}",
                solution="请检查素材是否被外部移动或删除。",
                context={"source_id": self.source_id, "object_key": object_key},
            )
        return self._metadata(path, object_key=Path(object_key).as_posix())

    def _is_link_like(self, path: Path) -> bool:
        try:
            if path.is_symlink():
                return True
            is_junction = getattr(path, "is_junction", None)
            if callable(is_junction) and is_junction():
                return True
            if os.name != "nt":
                return False
            attributes = path.lstat().st_file_attributes
            return bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
            )
        except OSError:
            return True

    def _has_symlink_component(self, path: Path) -> bool:
        relative = path.relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current = current / part
            if self._is_link_like(current):
                return True
        return False

    def _is_import_staging_segment(self, segment: str) -> bool:
        return os.path.normcase(segment) == os.path.normcase(".import-staging")

    def _is_import_staging_path(self, path: Path) -> bool:
        relative = path.relative_to(self.root)
        return bool(relative.parts) and self._is_import_staging_segment(relative.parts[0])

    def iter_objects(
        self, prefix: str = "", *, recursive: bool = True,
    ) -> Iterator[ObjectMetadata]:
        base = self._path(prefix, allow_empty=True)
        requested = self.root / (Path(prefix) if prefix else Path())
        if self._is_import_staging_path(base) or self._has_symlink_component(requested):
            return
        if not base.exists():
            return
        if base.is_file():
            yield self._metadata(base)
            return
        if not base.is_dir():
            return

        pending: list[tuple[bool, Path]] = [(True, base)]
        while pending:
            is_directory, path = pending.pop()
            if not is_directory:
                yield self._metadata(path)
                continue
            directory = path
            with os.scandir(directory) as scan:
                descriptors: list[tuple[str, bool, Path]] = []
                for entry in scan:
                    path = Path(entry.path)
                    if self._is_link_like(path):
                        continue
                    if entry.is_file(follow_symlinks=False):
                        descriptors.append((entry.name, False, path))
                    elif recursive and entry.is_dir(follow_symlinks=False):
                        if directory == self.root and self._is_import_staging_segment(entry.name):
                            continue
                        descriptors.append((f"{entry.name}/", True, path))
            for _key, is_child_directory, path in reversed(
                sorted(descriptors, key=lambda descriptor: descriptor[0])
            ):
                if is_child_directory:
                    pending.append((True, path))
                else:
                    pending.append((False, path))

    def exists(self, object_key: str) -> bool:
        return self._path(object_key).is_file()

    def open_reader(self, object_key: str) -> BinaryIO:
        path = self._path(object_key)
        if not path.is_file():
            self.stat(object_key)
        return path.open("rb")

    def _atomic_copy(self, source: BinaryIO, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".part-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if temporary.stat().st_size <= 0:
                raise OSError("素材文件为空")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def download(self, object_key: str, destination: str | Path) -> ObjectMetadata:
        with self.open_reader(object_key) as source:
            target = Path(destination)
            try:
                self._atomic_copy(source, target)
            except OSError as error:
                raise StorageError(
                    code="STORAGE_DOWNLOAD_FAILED",
                    message="素材下载失败",
                    detail=str(error),
                    solution="请检查目标磁盘空间和目录权限。",
                    retryable=True,
                    context={"source_id": self.source_id, "object_key": object_key},
                ) from error
        metadata = self.stat(object_key)
        return ObjectMetadata(
            key=metadata.key, size_bytes=Path(destination).stat().st_size,
            etag=metadata.etag, content_type=metadata.content_type,
            sha256=_sha256(Path(destination)), last_modified=metadata.last_modified,
        )

    def upload(
        self, object_key: str, source: BinaryIO | str | Path, *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata:
        del content_type, metadata
        destination = self._path(object_key)
        stream = None
        close_stream = False
        try:
            if isinstance(source, (str, Path)):
                stream = Path(source).open("rb")
                close_stream = True
            else:
                stream = source
            self._atomic_copy(stream, destination)
        except Exception as error:
            if isinstance(error, StorageError):
                raise
            raise StorageError(
                code="STORAGE_UPLOAD_FAILED",
                message="素材上传失败",
                detail=str(error),
                solution="请检查源文件、目标目录权限和磁盘空间后重试。",
                retryable=True,
                context={"source_id": self.source_id, "object_key": object_key},
            ) from error
        finally:
            if close_stream and stream is not None:
                stream.close()
        return self.stat(object_key)

    def delete(self, object_key: str) -> None:
        try:
            self._path(object_key).unlink(missing_ok=True)
        except OSError as error:
            raise StorageError(
                code="STORAGE_DELETE_FAILED", message="素材源文件删除失败",
                detail=str(error), solution="请检查文件占用和目录权限。",
                context={"source_id": self.source_id, "object_key": object_key},
            ) from error

    def list_objects(
        self, prefix: str = "", *, recursive: bool = True,
        cursor: str | None = None, limit: int = 1000,
    ) -> ObjectPage:
        base = self._path(prefix, allow_empty=True)
        if not base.exists():
            return ObjectPage(())
        if base.is_file():
            candidates = [base]
        else:
            candidates = list(base.rglob("*") if recursive else base.glob("*"))
        keys = sorted(
            path.relative_to(self.root).as_posix()
            for path in candidates if path.is_file()
        )
        if cursor:
            keys = [key for key in keys if key > str(cursor)]
        bounded = max(1, min(10000, int(limit)))
        visible = keys[:bounded]
        next_cursor = visible[-1] if len(keys) > bounded else None
        return ObjectPage(tuple(self.stat(key) for key in visible), next_cursor)

    def generate_preview_url(self, object_key: str, *, expires_seconds: int = 900) -> str | None:
        del expires_seconds
        self._path(object_key)
        return None

    def generate_upload_url(
        self, object_key: str, *, expires_seconds: int = 900,
        content_type: str = "application/octet-stream",
    ) -> str | None:
        del expires_seconds, content_type
        self._path(object_key)
        return None

    def materialize_to_local(self, object_key: str, destination: str | Path) -> ObjectMetadata:
        return self.download(object_key, destination)
