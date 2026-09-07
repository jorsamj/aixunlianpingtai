from __future__ import annotations

import os
import uuid
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Mapping

import requests

from .errors import StorageError, redact_storage_error
from .models import ObjectMetadata, ObjectPage, StorageHealth, StorageType


def _object(value: Mapping) -> ObjectMetadata:
    return ObjectMetadata(
        key=str(value.get("key") or ""), size_bytes=int(value.get("size_bytes") or 0),
        etag=str(value.get("etag") or ""), content_type=str(value.get("content_type") or "application/octet-stream"),
        sha256=str(value.get("sha256") or ""), last_modified=str(value.get("last_modified") or ""),
    )


class RemoteStorageProvider:
    storage_type = StorageType.REMOTE

    def __init__(self, source_id: str, config: Mapping[str, object], credentials: Mapping[str, str]) -> None:
        self.source_id = str(source_id)
        self.base_url = str(config.get("base_url") or "").strip().rstrip("/")
        self.namespace = str(config.get("namespace") or "default").strip()
        self.timeout = max(1.0, min(300.0, float(config.get("timeout_seconds") or 30)))
        self.token = str(credentials.get("token") or credentials.get("api_key") or "")
        if not self.base_url or not self.namespace:
            raise StorageError(code="STORAGE_CONFIG_INVALID", message="远程素材源配置不完整", detail="base_url 和 namespace 为必填项。", solution="请补全远程素材源配置。")
        if not self.token:
            raise StorageError(code="STORAGE_CREDENTIAL_MISSING", message="远程素材源凭据未配置", detail="API Token 为空。", solution="请重新保存远程素材源凭据。")

    @property
    def headers(self):
        return {"X-API-Key": self.token}

    @property
    def objects_url(self):
        return self.base_url + "/api/material-storage/v1/objects"

    def _raise(self, operation: str, error: Exception):
        status = getattr(getattr(error, "response", None), "status_code", None)
        detail = f"{operation} failed"
        if status:
            detail += f" with HTTP {status}"
        response_text = getattr(getattr(error, "response", None), "text", "")
        if response_text:
            detail += ": " + response_text[:500]
        elif str(error):
            detail += ": " + str(error)
        raise StorageError(
            code="STORAGE_REMOTE_REQUEST_FAILED", message="远程素材服务器请求失败",
            detail=redact_storage_error(detail), solution="请检查服务器地址、Token、网络和远程服务日志。",
            retryable=not status or int(status) >= 500,
            context={"source_id": self.source_id, "operation": operation},
        ) from error

    def health_check(self) -> StorageHealth:
        try:
            response = requests.get(self.base_url + "/api/material-storage/v1/health", headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                return StorageHealth.unavailable("remote server reported unavailable")
            return StorageHealth.available("远程素材服务器可访问", details={"protocol_version": body.get("protocol_version")})
        except Exception as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            return StorageHealth.unavailable(redact_storage_error(f"remote connection failed{f' with HTTP {status}' if status else ''}: {error}"))

    def stat(self, object_key: str) -> ObjectMetadata:
        try:
            response = requests.get(self.objects_url + "/meta", params={"namespace": self.namespace, "key": object_key}, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return _object(response.json())
        except Exception as error:
            self._raise("stat", error)

    def exists(self, object_key: str) -> bool:
        try:
            response = requests.get(self.objects_url + "/meta", params={"namespace": self.namespace, "key": object_key}, headers=self.headers, timeout=self.timeout)
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return True
        except Exception as error:
            self._raise("exists", error)

    def open_reader(self, object_key: str) -> BinaryIO:
        try:
            response = requests.get(self.objects_url + "/content", params={"namespace": self.namespace, "key": object_key}, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return BytesIO(response.content)
        except Exception as error:
            self._raise("read", error)

    def download(self, object_key: str, destination: str | Path) -> ObjectMetadata:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".part-{uuid.uuid4().hex}.tmp"
        try:
            with requests.get(self.objects_url + "/content", params={"namespace": self.namespace, "key": object_key}, headers=self.headers, timeout=self.timeout, stream=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            stream.write(chunk)
                    stream.flush(); os.fsync(stream.fileno())
            if temporary.stat().st_size <= 0:
                raise OSError("downloaded object is empty")
            os.replace(temporary, target)
            return self.stat(object_key)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            if isinstance(error, StorageError):
                raise
            self._raise("download", error)

    def upload(self, object_key: str, source: BinaryIO | str | Path, *, content_type: str = "application/octet-stream", metadata: Mapping[str, str] | None = None) -> ObjectMetadata:
        del metadata
        stream = Path(source).open("rb") if isinstance(source, (str, Path)) else source
        close_stream = isinstance(source, (str, Path))
        try:
            response = requests.put(self.objects_url, params={"namespace": self.namespace, "key": object_key}, headers={**self.headers, "Content-Type": content_type}, data=stream, timeout=self.timeout)
            response.raise_for_status()
            return _object(response.json())
        except Exception as error:
            self._raise("upload", error)
        finally:
            if close_stream:
                stream.close()

    def delete(self, object_key: str) -> None:
        try:
            response = requests.delete(self.objects_url, params={"namespace": self.namespace, "key": object_key}, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
        except Exception as error:
            self._raise("delete", error)

    def list_objects(self, prefix: str = "", *, recursive: bool = True, cursor: str | None = None, limit: int = 1000) -> ObjectPage:
        try:
            response = requests.get(self.objects_url + "/list", params={"namespace": self.namespace, "prefix": prefix, "recursive": str(bool(recursive)).lower(), "cursor": cursor, "limit": limit}, headers=self.headers, timeout=self.timeout)
            response.raise_for_status(); body = response.json()
            return ObjectPage(tuple(_object(item) for item in body.get("items") or []), body.get("next_cursor"))
        except Exception as error:
            self._raise("list", error)

    def generate_preview_url(self, object_key: str, *, expires_seconds: int = 900) -> str | None:
        try:
            response = requests.post(self.objects_url + "/presign", params={"namespace": self.namespace, "key": object_key, "expires_seconds": expires_seconds}, headers=self.headers, timeout=self.timeout)
            response.raise_for_status(); return str(response.json().get("url") or "") or None
        except Exception as error:
            self._raise("presign", error)

    def generate_upload_url(self, object_key: str, *, expires_seconds: int = 900, content_type: str = "application/octet-stream") -> str | None:
        del object_key, expires_seconds, content_type
        return None

    def materialize_to_local(self, object_key: str, destination: str | Path) -> ObjectMetadata:
        return self.download(object_key, destination)
