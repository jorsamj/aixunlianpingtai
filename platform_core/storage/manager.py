from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Callable, Mapping

from filelock import FileLock

from platform_core.material_repository import MaterialRepository, normalize_material
from platform_core.secrets import SecretCredentialStore

from .base import StorageProvider
from .cache import MaterialCache, MaterializedFile, file_sha256
from .errors import StorageError
from .factory import StorageProviderFactory
from .models import ObjectMetadata, StorageType
from .source_repository import StorageSource, StorageSourceRepository


ProviderResolver = Callable[[StorageSource, Mapping[str, str]], StorageProvider]


class StorageManager:
    def __init__(
        self, *, data_dir: str | Path, project_id: str,
        materials: MaterialRepository | None = None,
        sources: StorageSourceRepository | None = None,
        credentials: SecretCredentialStore | None = None,
        provider_resolver: ProviderResolver | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.project_id = str(project_id)
        self.project_dir = self.data_dir / "projects" / self.project_id
        self.materials = materials or MaterialRepository(self.project_dir)
        self.sources = sources or StorageSourceRepository(self.data_dir / "storage" / "storage_sources.sqlite3")
        self.credentials = credentials
        self._provider_resolver = provider_resolver
        self.cache = MaterialCache(self.data_dir / "cache" / "materials")
        self._providers: dict[str, StorageProvider] = {}

    def provider_for(self, source_id: str) -> StorageProvider:
        normalized = str(source_id or "default_local")
        cached = self._providers.get(normalized)
        if cached is not None:
            return cached
        source = self.sources.get(normalized)
        if source is None:
            raise StorageError(
                code="STORAGE_SOURCE_NOT_FOUND", message="素材存储源不存在",
                detail=f"找不到存储源 {normalized}。",
                solution="请恢复该存储源配置或重新建立素材索引。",
                context={"source_id": normalized},
            )
        secret: Mapping[str, str] = {}
        if source.secret_ref and self.credentials is not None:
            secret = self.credentials.get(source.secret_ref) or {}
        if self._provider_resolver is not None:
            provider = self._provider_resolver(source, secret)
        else:
            provider = StorageProviderFactory(
                data_dir=self.data_dir, project_dir=self.project_dir,
                credentials={source.id: secret},
            ).create(source)
        self._providers[normalized] = provider
        return provider

    def material(self, value: str | Mapping[str, object]) -> dict:
        if isinstance(value, str):
            row = self.materials.get(value)
            if row is None:
                raise StorageError(
                    code="MATERIAL_NOT_FOUND", message="素材不存在",
                    detail=f"找不到素材 {value}。", solution="请刷新素材列表。",
                    context={"image_id": value},
                )
            return normalize_material(row)
        return normalize_material(value)

    def materialize(self, value: str | Mapping[str, object]) -> MaterializedFile:
        row = self.material(value)
        if row.get('source_available') is False:
            raise StorageError(code='SOURCE_UNAVAILABLE', message='素材源文件不可用',
                solution='请恢复源文件后，在存储源配置中重新扫描并确认恢复。',
                context={'image_id': row['id'], 'source_id': row['storage_source_id']})
        provider = self.provider_for(str(row["storage_source_id"]))
        object_key = str(row["object_key"])
        expected = str(row.get("content_sha256") or "")
        suffix = Path(str(row.get("filename") or object_key)).suffix or Path(object_key).suffix
        if provider.storage_type is StorageType.LOCAL:
            local_path = provider._path(object_key) if hasattr(provider, "_path") else None
            metadata = provider.stat(object_key)
            actual = metadata.sha256 or (file_sha256(local_path) if local_path else "")
            if expected and actual != expected:
                raise StorageError(
                    code="SOURCE_CONTENT_CHANGED", message="素材完整性校验失败",
                    detail=f"素材 {row['id']} 的本地文件已发生变化。",
                    solution="请在存储源配置中重新扫描，确认内容变化后恢复索引，并复核已有标注。",
                    context={"image_id": row["id"], "source_id": provider.source_id, "object_key": object_key},
                )
            if not expected or int(row.get("size_bytes") or 0) != metadata.size_bytes:
                self.materials.patch({str(row["id"]): {"content_sha256": actual, "size_bytes": metadata.size_bytes, "etag": metadata.etag}})
            if local_path is None:
                return self.cache.materialize(provider, object_key, expected_sha256=actual, suffix=suffix)
            return MaterializedFile(local_path, actual, metadata.size_bytes, True)
        if not expected:
            metadata = provider.stat(object_key)
            expected = metadata.sha256
            if not expected:
                raise StorageError(
                    code="STORAGE_HASH_MISSING", message="远程素材缺少内容哈希",
                    detail=f"素材 {row['id']} 没有可验证的 SHA256。",
                    solution="请重新扫描或重新上传素材以建立完整性信息。",
                    context={"image_id": row["id"], "source_id": provider.source_id},
                )
            self.materials.patch({str(row["id"]): {"content_sha256": expected, "size_bytes": metadata.size_bytes, "etag": metadata.etag}})
        try:
            return self.cache.materialize(provider, object_key, expected_sha256=expected, suffix=suffix)
        except StorageError as error:
            if error.code != 'STORAGE_SHA256_MISMATCH':
                raise
            raise StorageError(code='SOURCE_CONTENT_CHANGED', message='素材源内容已变化',
                detail=error.detail,
                solution='请在存储源配置中重新扫描，确认内容变化后恢复索引，并复核已有标注。',
                context=error.context) from error

    def invalidate_content_cache(self, content_sha256: str, filename: str) -> None:
        """Safe adapter for the current content-addressed cache; never touches sources."""
        if not content_sha256:
            return
        target = self.cache.path_for(content_sha256, Path(filename).suffix).resolve()
        if not target.is_relative_to(self.cache.root):
            raise ValueError('cache invalidation escaped cache root')
        if not target.parent.exists():
            return
        with FileLock(str(target) + '.lock', timeout=30):
            target.unlink(missing_ok=True)

    def preview_url(self, value: str | Mapping[str, object], *, expires_seconds: int = 900) -> str | None:
        row = self.material(value)
        return self.provider_for(str(row["storage_source_id"])).generate_preview_url(
            str(row["object_key"]), expires_seconds=expires_seconds
        )

    def open_reader(self, value: str | Mapping[str, object]) -> BinaryIO:
        row = self.material(value)
        return self.provider_for(str(row["storage_source_id"])).open_reader(str(row["object_key"]))

    def upload_object(
        self, source_id: str, object_key: str, source: BinaryIO | str | Path,
        *, content_type: str = "application/octet-stream",
    ) -> ObjectMetadata:
        return self.provider_for(source_id).upload(object_key, source, content_type=content_type)

    def delete_source_file(self, value: str | Mapping[str, object]) -> None:
        row = self.material(value)
        self.provider_for(str(row["storage_source_id"])).delete(str(row["object_key"]))
