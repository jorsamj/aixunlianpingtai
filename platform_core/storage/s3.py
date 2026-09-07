from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Mapping

from .errors import StorageError, redact_storage_error
from .models import ObjectMetadata, ObjectPage, StorageHealth, StorageType


def _load_boto3():
    import boto3
    return boto3


class S3StorageProvider:
    storage_type = StorageType.S3

    def __init__(self, source_id: str, config: Mapping[str, object], credentials: Mapping[str, str]) -> None:
        self.source_id = str(source_id)
        self.endpoint = str(config.get("endpoint") or "").strip() or None
        self.bucket = str(config.get("bucket") or "").strip()
        self.region = str(config.get("region") or "").strip() or None
        self.prefix = str(config.get("prefix") or "").strip("/")
        self.use_ssl = bool(config.get("use_ssl", True))
        if not self.bucket:
            raise StorageError(code="STORAGE_CONFIG_INVALID", message="S3 配置不完整", detail="Bucket 为必填项。", solution="请补全 S3 存储配置。")
        try:
            boto3 = _load_boto3()
        except ImportError as error:
            raise StorageError(code="STORAGE_SDK_MISSING", message="缺少 S3 SDK", detail="未安装 boto3。", solution="请执行 pip install boto3 后重启服务。") from error
        try:
            self.client = boto3.client(
                "s3", endpoint_url=self.endpoint, region_name=self.region, use_ssl=self.use_ssl,
                aws_access_key_id=credentials.get("access_key_id"),
                aws_secret_access_key=credentials.get("secret_access_key"),
                aws_session_token=credentials.get("session_token"),
            )
        except Exception as error:
            raise StorageError(code="STORAGE_CONFIG_INVALID", message="S3 客户端初始化失败", detail=redact_storage_error(error), solution="请检查 Endpoint、Region 和凭据。") from error

    def _key(self, object_key: str) -> str:
        key = str(object_key or "").replace("\\", "/").lstrip("/")
        return f"{self.prefix}/{key}" if self.prefix and key else self.prefix or key

    def _public_key(self, key: str) -> str:
        if self.prefix and key.startswith(self.prefix + "/"):
            return key[len(self.prefix) + 1:]
        return key

    def _error(self, operation: str, error: Exception):
        raise StorageError(code="STORAGE_S3_REQUEST_FAILED", message="S3 操作失败", detail=redact_storage_error(f"{operation}: {error}"), solution="请检查 Endpoint、Bucket、凭据和访问权限。", retryable=True, context={"source_id": self.source_id, "operation": operation}) from error

    def health_check(self) -> StorageHealth:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return StorageHealth.available("S3 Bucket 可访问", details={"bucket": self.bucket})
        except Exception as error:
            return StorageHealth.unavailable(redact_storage_error(error), details={"bucket": self.bucket})

    def stat(self, object_key: str) -> ObjectMetadata:
        try:
            item = self.client.head_object(Bucket=self.bucket, Key=self._key(object_key))
            return ObjectMetadata(key=str(object_key), size_bytes=int(item.get("ContentLength") or 0), etag=str(item.get("ETag") or ""), content_type=str(item.get("ContentType") or "application/octet-stream"), sha256=str((item.get("Metadata") or {}).get("sha256") or ""), last_modified=str(item.get("LastModified") or ""))
        except Exception as error:
            self._error("stat", error)

    def exists(self, object_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(object_key)); return True
        except Exception as error:
            response = getattr(error, "response", {}) or {}
            if str((response.get("Error") or {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}:
                return False
            self._error("exists", error)

    def open_reader(self, object_key: str) -> BinaryIO:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(object_key))["Body"]
        except Exception as error:
            self._error("read", error)

    def download(self, object_key: str, destination: str | Path) -> ObjectMetadata:
        target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("wb") as stream:
                self.client.download_fileobj(self.bucket, self._key(object_key), stream)
            return self.stat(object_key)
        except Exception as error:
            target.unlink(missing_ok=True); self._error("download", error)

    def upload(self, object_key: str, source: BinaryIO | str | Path, *, content_type: str = "application/octet-stream", metadata: Mapping[str, str] | None = None) -> ObjectMetadata:
        stream = Path(source).open("rb") if isinstance(source, (str, Path)) else source
        close = isinstance(source, (str, Path))
        try:
            self.client.upload_fileobj(stream, self.bucket, self._key(object_key), ExtraArgs={"ContentType": content_type, "Metadata": dict(metadata or {})})
            return self.stat(object_key)
        except Exception as error:
            self._error("upload", error)
        finally:
            if close: stream.close()

    def delete(self, object_key: str) -> None:
        try: self.client.delete_object(Bucket=self.bucket, Key=self._key(object_key))
        except Exception as error: self._error("delete", error)

    def list_objects(self, prefix: str = "", *, recursive: bool = True, cursor: str | None = None, limit: int = 1000) -> ObjectPage:
        params = {"Bucket": self.bucket, "Prefix": self._key(prefix), "MaxKeys": max(1, min(1000, int(limit)))}
        if cursor: params["ContinuationToken"] = cursor
        if not recursive: params["Delimiter"] = "/"
        try:
            body = self.client.list_objects_v2(**params)
            items = tuple(ObjectMetadata(key=self._public_key(str(item["Key"])), size_bytes=int(item.get("Size") or 0), etag=str(item.get("ETag") or ""), last_modified=str(item.get("LastModified") or "")) for item in body.get("Contents") or [])
            return ObjectPage(items, body.get("NextContinuationToken"))
        except Exception as error: self._error("list", error)

    def generate_preview_url(self, object_key: str, *, expires_seconds: int = 900) -> str | None:
        try: return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": self._key(object_key)}, ExpiresIn=max(1, min(3600, int(expires_seconds))))
        except Exception as error: self._error("presign", error)

    def generate_upload_url(self, object_key: str, *, expires_seconds: int = 900, content_type: str = "application/octet-stream") -> str | None:
        try: return self.client.generate_presigned_url("put_object", Params={"Bucket": self.bucket, "Key": self._key(object_key), "ContentType": content_type}, ExpiresIn=max(1, min(3600, int(expires_seconds))))
        except Exception as error: self._error("presign upload", error)

    def materialize_to_local(self, object_key: str, destination: str | Path) -> ObjectMetadata:
        return self.download(object_key, destination)

