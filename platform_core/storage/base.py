from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Mapping, Protocol, runtime_checkable

from .models import ObjectMetadata, ObjectPage, StorageHealth, StorageType


@runtime_checkable
class StorageProvider(Protocol):
    source_id: str
    storage_type: StorageType

    def health_check(self) -> StorageHealth: ...

    def stat(self, object_key: str) -> ObjectMetadata: ...

    def exists(self, object_key: str) -> bool: ...

    def open_reader(self, object_key: str) -> BinaryIO: ...

    def download(self, object_key: str, destination: str | Path) -> ObjectMetadata: ...

    def upload(
        self,
        object_key: str,
        source: BinaryIO | str | Path,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata: ...

    def delete(self, object_key: str) -> None: ...

    def list_objects(
        self,
        prefix: str = "",
        *,
        recursive: bool = True,
        cursor: str | None = None,
        limit: int = 1000,
    ) -> ObjectPage: ...

    def generate_preview_url(self, object_key: str, *, expires_seconds: int = 900) -> str | None: ...

    def generate_upload_url(
        self,
        object_key: str,
        *,
        expires_seconds: int = 900,
        content_type: str = "application/octet-stream",
    ) -> str | None: ...

    def materialize_to_local(self, object_key: str, destination: str | Path) -> ObjectMetadata: ...

