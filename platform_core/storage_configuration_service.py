"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from fastapi import HTTPException
from .storage_configuration_contracts import StorageSourceCreateReq, StorageSourceUpdateReq

import uuid
import sqlite3
from platform_core.errors import PlatformError
from platform_core.model_artifacts import ModelArtifactService
from platform_core.secrets import secret_ref
from platform_core.storage import StorageError
from platform_core.storage.source_repository import (
    StorageSourceConflictError,
    StorageSourceOperationBlocked,
)

@dataclass(frozen=True)
class StorageConfigurationDependencies:
    DATA_DIR: Callable[..., Any]
    _assert_storage_source_mutation_allowed: Callable[..., Any]
    _public_storage_source: Callable[..., Any]
    _raise_storage_error: Callable[..., Any]
    _storage_source_fence: Callable[..., Any]
    _validate_storage_source_config: Callable[..., Any]
    algorithms_file: Callable[..., Any]
    project_dir: Callable[..., Any]
    storage_credentials: Callable[..., Any]
    storage_source_repository: Callable[..., Any]


class StorageConfigurationService:
    def __init__(self, dependencies: StorageConfigurationDependencies):
        self.dependencies = dependencies

    def list_storage_sources(self, ):
        return {"items": [self.dependencies._public_storage_source(source) for source in self.dependencies.storage_source_repository().list()]}

    def create_storage_source(self, payload: StorageSourceCreateReq):
        source_id = str(payload.id or f"storage_{uuid.uuid4().hex[:12]}")
        source_type = self.dependencies._validate_storage_source_config(payload.type, payload.config)
        reference = secret_ref("storage-source", source_id) if payload.credentials else ""
        repository = self.dependencies.storage_source_repository()
        try:
            # Source creation and retirement share a canonical lifecycle fence.
            # This also protects a retired credential reference from being reused
            # by a concurrent create with the same source ID.
            with self.dependencies._storage_source_fence():
                source = repository.create({
                    "id": source_id, "name": payload.name, "type": source_type,
                    "config": payload.config, "secret_ref": reference, "enabled": payload.enabled,
                })
                if payload.credentials:
                    try:
                        self.dependencies.storage_credentials().set(reference, payload.credentials)
                    except Exception:
                        repository.delete(source_id)
                        raise
                return self.dependencies._public_storage_source(source)
        except StorageSourceConflictError as error:
            raise HTTPException(status_code=409, detail="存储源名称或 ID 已存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="存储源名称或 ID 已存在") from error

    def update_storage_source(self, source_id: str, payload: StorageSourceUpdateReq):
        repository = self.dependencies.storage_source_repository()
        changes = payload.model_dump(exclude_unset=True)
        credentials = changes.pop("credentials", None)
        clear_credentials = bool(changes.pop("clear_credentials", False))
        changes = {key: value for key, value in changes.items() if value is not None}
        with self.dependencies._storage_source_fence():
            current = repository.get(source_id)
            if current is None:
                raise HTTPException(status_code=404, detail="存储源不存在")
            if "config" in changes:
                self.dependencies._validate_storage_source_config(current.type, changes["config"])
            destructive = (
                ("config" in changes and changes["config"] != current.config)
                or (changes.get("enabled") is False and current.enabled)
                or credentials is not None
                or clear_credentials
            )
            if destructive:
                self.dependencies._assert_storage_source_mutation_allowed(source_id)

            secret_store = self.dependencies.storage_credentials()
            old_reference = str(current.secret_ref or "")
            new_reference = ""
            replace_credentials = credentials is not None and bool(credentials)
            clear_secret = (credentials is not None and not credentials) or clear_credentials
            if replace_credentials:
                # Version the Keyring reference.  A failed SQLite commit can then
                # delete only the unpublished value without damaging generation A.
                new_reference = secret_ref(
                    "storage-source",
                    f"{source_id}-generation-{uuid.uuid4().hex}",
                )
                secret_store.set(new_reference, credentials)
                changes["secret_ref"] = new_reference
            elif clear_secret:
                changes["secret_ref"] = ""

            original = {
                "name": current.name,
                "config": current.config,
                "secret_ref": current.secret_ref,
                "enabled": current.enabled,
            }
            try:
                updated = repository.update(source_id, changes)
                if old_reference and (replace_credentials or clear_secret):
                    try:
                        secret_store.delete(old_reference)
                    except Exception:
                        # Restore the complete previous source generation.  The
                        # newly written Secret is not published after rollback.
                        repository.update(source_id, original)
                        if new_reference:
                            try:
                                secret_store.delete(new_reference)
                            except Exception:
                                pass
                        raise
                return self.dependencies._public_storage_source(updated)
            except Exception as error:
                if new_reference:
                    try:
                        secret_store.delete(new_reference)
                    except Exception:
                        pass
                if isinstance(error, ValueError):
                    raise HTTPException(status_code=409, detail=str(error)) from error
                if isinstance(error, sqlite3.IntegrityError):
                    raise HTTPException(status_code=409, detail="存储源名称已存在") from error
                raise

    def set_default_storage_source(self, source_id: str):
        try:
            # Default selection must not race source retirement, which could
            # otherwise leave the repository without a valid default source.
            with self.dependencies._storage_source_fence():
                return self.dependencies._public_storage_source(self.dependencies.storage_source_repository().set_default(source_id))
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def test_storage_source(self, source_id: str):
        repository = self.dependencies.storage_source_repository()
        source = repository.get(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="存储源不存在")
        try:
            result = ModelArtifactService(
                data_dir=self.dependencies.DATA_DIR(),
                project_dir=self.dependencies.project_dir,
                algorithms_file=self.dependencies.algorithms_file,
                storage_sources_factory=self.dependencies.storage_source_repository,
                storage_credentials_factory=self.dependencies.storage_credentials,
            ).test_storage(source_id)
        except StorageError as error:
            repository.record_health(source_id, ok=False, message=str(error))
            self.dependencies._raise_storage_error(error)
        except PlatformError as error:
            repository.record_health(source_id, ok=False, message=str(error.message or error))
            raise PlatformError(
                "STORAGE_HEALTH_CHECK_FAILED",
                "存储连接或完整读写测试失败",
                str(error.detail or error.message or error),
                str(error.solution or "请检查存储源配置和权限后重试。"),
                int(error.status_code or 503),
            ) from error
        message = str(result.get("message") or "存储连接与读写删除测试通过")
        repository.record_health(source_id, ok=True, message=message)
        return {
            "ok": True,
            "health": {
                "ok": True,
                "status": "AVAILABLE",
                "message": message,
                "details": dict(result.get("stages") or {}),
            },
            "source": self.dependencies._public_storage_source(repository.get(source_id)),
        }

    def delete_storage_source(self, source_id: str):
        repository = self.dependencies.storage_source_repository()
        # Match update_source's existing canonical lifecycle fence. In-flight
        # final Material commits and destructive source retirement must serialize.
        with self.dependencies._storage_source_fence():
            source = repository.get(source_id)
            if source is None:
                raise HTTPException(status_code=404, detail="存储源不存在")
            self.dependencies._assert_storage_source_mutation_allowed(source_id)
            try:
                repository.delete(source_id)
            except StorageSourceOperationBlocked as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            # Retired credentials are no longer available to any committed
            # material. Keep deletion within the fence to prevent reuse races.
            if source.secret_ref:
                self.dependencies.storage_credentials().delete(source.secret_ref)
        return {"ok": True, "deleted_id": source_id}
