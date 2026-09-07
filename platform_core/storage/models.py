from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class StorageType(str, Enum):
    LOCAL = "local"
    OSS = "oss"
    S3 = "s3"
    REMOTE = "remote"

    @classmethod
    def parse(cls, value: object) -> "StorageType":
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "local": cls.LOCAL,
            "oss": cls.OSS,
            "aliyun_oss": cls.OSS,
            "s3": cls.S3,
            "aws": cls.S3,
            "aws_s3": cls.S3,
            "minio": cls.S3,
            "s3_compatible": cls.S3,
            "remote": cls.REMOTE,
            "remote_server": cls.REMOTE,
            "http": cls.REMOTE,
        }
        try:
            return aliases[normalized]
        except KeyError as error:
            raise ValueError(f"unsupported storage type: {value}") from error


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    size_bytes: int
    etag: str = ""
    content_type: str = "application/octet-stream"
    sha256: str = ""
    last_modified: str = ""


@dataclass(frozen=True)
class StorageHealth:
    ok: bool
    status: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def available(
        cls, message: str = "available", *, details: Mapping[str, Any] | None = None
    ) -> "StorageHealth":
        return cls(True, "AVAILABLE", str(message), dict(details or {}))

    @classmethod
    def unavailable(
        cls, message: str, *, details: Mapping[str, Any] | None = None
    ) -> "StorageHealth":
        return cls(False, "UNAVAILABLE", str(message), dict(details or {}))


@dataclass(frozen=True)
class ObjectPage:
    items: tuple[ObjectMetadata, ...]
    next_cursor: str | None = None

