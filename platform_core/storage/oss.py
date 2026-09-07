from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Mapping

from .errors import StorageError, redact_storage_error
from .models import ObjectMetadata, ObjectPage, StorageHealth, StorageType


def _load_oss2():
    import oss2
    return oss2


class OSSStorageProvider:
    storage_type = StorageType.OSS

    def __init__(self, source_id: str, config: Mapping[str, object], credentials: Mapping[str, str]) -> None:
        self.source_id = str(source_id)
        self.endpoint = str(config.get("endpoint") or "").strip()
        self.bucket_name = str(config.get("bucket") or "").strip()
        self.prefix = str(config.get("prefix") or "").strip("/")
        if not self.endpoint or not self.bucket_name:
            raise StorageError(code="STORAGE_CONFIG_INVALID", message="OSS 配置不完整", detail="Endpoint 和 Bucket 为必填项。", solution="请补全阿里云 OSS 配置。")
        try: oss2 = _load_oss2()
        except ImportError as error:
            raise StorageError(code="STORAGE_SDK_MISSING", message="缺少阿里云 OSS SDK", detail="未安装 oss2。", solution="请执行 pip install oss2 后重启服务。") from error
        access_id = str(credentials.get("access_key_id") or "")
        access_secret = str(credentials.get("access_key_secret") or "")
        token = str(credentials.get("security_token") or "")
        if not access_id or not access_secret:
            raise StorageError(code="STORAGE_CREDENTIAL_MISSING", message="OSS 凭据未配置", detail="AccessKey ID 或 AccessKey Secret 为空。", solution="请重新保存 OSS 凭据。")
        auth = oss2.StsAuth(access_id, access_secret, token) if token else oss2.Auth(access_id, access_secret)
        self.oss2 = oss2
        self.bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)

    def _key(self, key):
        value = str(key or "").replace("\\", "/").lstrip("/")
        return f"{self.prefix}/{value}" if self.prefix and value else self.prefix or value

    def _public_key(self, key):
        return key[len(self.prefix) + 1:] if self.prefix and key.startswith(self.prefix + "/") else key

    def _error(self, operation, error):
        raise StorageError(code="STORAGE_OSS_REQUEST_FAILED", message="阿里云 OSS 操作失败", detail=redact_storage_error(f"{operation}: {error}"), solution="请检查 Endpoint、Bucket、凭据和访问权限。", retryable=True, context={"source_id": self.source_id, "operation": operation}) from error

    def health_check(self):
        try: self.bucket.get_bucket_info(); return StorageHealth.available("OSS Bucket 可访问", details={"bucket": self.bucket_name})
        except Exception as error: return StorageHealth.unavailable(redact_storage_error(error), details={"bucket": self.bucket_name})

    def stat(self, object_key):
        try:
            result = self.bucket.get_object_meta(self._key(object_key)); headers = result.headers
            return ObjectMetadata(key=str(object_key), size_bytes=int(headers.get("Content-Length") or 0), etag=str(headers.get("ETag") or ""), content_type=str(headers.get("Content-Type") or "application/octet-stream"), sha256=str(headers.get("x-oss-meta-sha256") or ""), last_modified=str(headers.get("Last-Modified") or ""))
        except Exception as error: self._error("stat", error)

    def exists(self, object_key):
        try: return bool(self.bucket.object_exists(self._key(object_key)))
        except Exception as error: self._error("exists", error)

    def open_reader(self, object_key):
        try: return self.bucket.get_object(self._key(object_key))
        except Exception as error: self._error("read", error)

    def download(self, object_key, destination):
        target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True)
        try: self.bucket.get_object_to_file(self._key(object_key), str(target)); return self.stat(object_key)
        except Exception as error: target.unlink(missing_ok=True); self._error("download", error)

    def upload(self, object_key, source, *, content_type="application/octet-stream", metadata=None):
        stream = Path(source).open("rb") if isinstance(source, (str, Path)) else source; close = isinstance(source, (str, Path))
        headers = {"Content-Type": content_type, **{f"x-oss-meta-{key}": value for key, value in dict(metadata or {}).items()}}
        try: self.bucket.put_object(self._key(object_key), stream, headers=headers); return self.stat(object_key)
        except Exception as error: self._error("upload", error)
        finally:
            if close: stream.close()

    def delete(self, object_key):
        try: self.bucket.delete_object(self._key(object_key))
        except Exception as error: self._error("delete", error)

    def list_objects(self, prefix="", *, recursive=True, cursor=None, limit=1000):
        try:
            iterator = self.oss2.ObjectIterator(self.bucket, prefix=self._key(prefix), marker=cursor or "", delimiter="" if recursive else "/", max_keys=max(1, min(1000, int(limit))))
            items = []
            for item in iterator:
                if getattr(item, "is_prefix", lambda: False)(): continue
                items.append(ObjectMetadata(key=self._public_key(item.key), size_bytes=int(item.size or 0), etag=str(item.etag or ""), last_modified=str(item.last_modified or "")))
                if len(items) >= limit: break
            return ObjectPage(tuple(items), items[-1].key if len(items) >= limit else None)
        except Exception as error: self._error("list", error)

    def generate_preview_url(self, object_key, *, expires_seconds=900):
        try: return self.bucket.sign_url("GET", self._key(object_key), max(1, min(3600, int(expires_seconds))))
        except Exception as error: self._error("presign", error)

    def generate_upload_url(self, object_key, *, expires_seconds=900, content_type="application/octet-stream"):
        try: return self.bucket.sign_url("PUT", self._key(object_key), max(1, min(3600, int(expires_seconds))), headers={"Content-Type": content_type})
        except Exception as error: self._error("presign upload", error)

    def materialize_to_local(self, object_key, destination): return self.download(object_key, destination)

