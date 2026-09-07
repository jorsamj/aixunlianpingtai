from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .base import StorageProvider
from .errors import StorageError
from .local import LocalStorageProvider
from .models import StorageType
from .source_repository import StorageSource


class StorageProviderFactory:
    def __init__(
        self, *, data_dir: str | Path, project_dir: str | Path,
        credentials: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.project_dir = Path(project_dir).resolve()
        self.credentials = credentials or {}

    def create(self, source: StorageSource) -> StorageProvider:
        if not source.enabled:
            raise StorageError(
                code="STORAGE_SOURCE_DISABLED", message="素材存储源已停用",
                detail=f"存储源 {source.name} 当前不可用于素材操作。",
                solution="请在素材存储配置中启用该存储源。",
                context={"source_id": source.id},
            )
        source_type = StorageType.parse(source.type)
        if source_type is StorageType.LOCAL:
            configured = str(source.config.get("root") or "").strip()
            if source.id == "default_local" and not configured:
                root = self.project_dir
            else:
                root = Path(configured) if configured else self.data_dir / "storage" / source.id
                if not root.is_absolute():
                    root = self.data_dir / root
            return LocalStorageProvider(source.id, root)
        raise StorageError(
            code="STORAGE_PROVIDER_UNAVAILABLE",
            message="当前存储 Provider 尚不可用",
            detail=f"尚未加载 {source_type.value} Provider。",
            solution="请安装对应 SDK 并配置 Worker。",
            context={"source_id": source.id, "storage_type": source_type.value},
        )

