from __future__ import annotations

from io import BytesIO

import pytest

from platform_core.storage import (
    ObjectMetadata,
    StorageError,
    StorageHealth,
    StorageProvider,
    StorageType,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("local", StorageType.LOCAL),
        ("OSS", StorageType.OSS),
        ("aws_s3", StorageType.S3),
        ("minio", StorageType.S3),
        ("remote_server", StorageType.REMOTE),
    ],
)
def test_storage_type_normalizes_supported_aliases(value, expected):
    assert StorageType.parse(value) is expected


def test_storage_type_rejects_unknown_value():
    with pytest.raises(ValueError, match="unsupported storage type"):
        StorageType.parse("ftp")


def test_storage_domain_records_are_immutable_and_public():
    metadata = ObjectMetadata(
        key="materials/a.jpg",
        size_bytes=12,
        etag="abc",
        content_type="image/jpeg",
        sha256="f" * 64,
    )
    health = StorageHealth.available("connected", details={"bucket": "images"})

    assert metadata.key == "materials/a.jpg"
    assert health.ok is True
    assert health.status == "AVAILABLE"
    assert health.details == {"bucket": "images"}
    with pytest.raises(Exception):
        metadata.key = "changed.jpg"  # type: ignore[misc]


def test_storage_error_redacts_credentials_from_public_payload():
    error = StorageError(
        code="STORAGE_AUTH_FAILED",
        message="对象存储认证失败",
        detail="Authorization: Bearer secret-token api_key=top-secret sk-live-1234567890123456",
        solution="请检查访问凭据。",
        retryable=False,
    )

    payload = error.to_public_dict()
    serialized = str(payload)
    assert payload["code"] == "STORAGE_AUTH_FAILED"
    assert payload["retryable"] is False
    assert "secret-token" not in serialized
    assert "top-secret" not in serialized
    assert "sk-live" not in serialized
    assert "[REDACTED]" in serialized


def test_provider_protocol_declares_the_complete_storage_surface():
    required = {
        "health_check",
        "stat",
        "exists",
        "open_reader",
        "download",
        "upload",
        "delete",
        "list_objects",
        "generate_preview_url",
        "generate_upload_url",
        "materialize_to_local",
    }
    assert required <= set(StorageProvider.__protocol_attrs__)

    class CompleteProvider:
        source_id = "test"
        storage_type = StorageType.LOCAL

        def health_check(self): ...
        def stat(self, object_key): ...
        def exists(self, object_key): ...
        def open_reader(self, object_key): return BytesIO()
        def download(self, object_key, destination): ...
        def upload(self, object_key, source, **kwargs): ...
        def delete(self, object_key): ...
        def list_objects(self, prefix="", **kwargs): ...
        def generate_preview_url(self, object_key, **kwargs): ...
        def generate_upload_url(self, object_key, **kwargs): ...
        def materialize_to_local(self, object_key, destination): ...

    assert isinstance(CompleteProvider(), StorageProvider)
