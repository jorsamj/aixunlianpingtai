from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from platform_core.storage import OSSStorageProvider, S3StorageProvider, StorageError


def test_oss_platform_upload_forbids_same_key_overwrite_by_default(monkeypatch):
    import platform_core.storage.oss as module
    captured = {}

    class FakeAuth:
        def __init__(self, *_args):
            pass

    class FakeBucket:
        def __init__(self, *_args):
            pass

        def put_object(self, key, stream, headers=None):
            captured["key"] = key
            captured["headers"] = dict(headers or {})
            captured["body"] = stream.read()

        def get_object_meta(self, _key):
            return SimpleNamespace(headers={
                "Content-Length": "3",
                "ETag": "etag",
                "x-oss-meta-sha256": "a" * 64,
            })

    monkeypatch.setattr(
        module,
        "_load_oss2",
        lambda: SimpleNamespace(Auth=FakeAuth, StsAuth=FakeAuth, Bucket=FakeBucket),
    )
    provider = OSSStorageProvider(
        "oss",
        {"endpoint": "oss.example.com", "bucket": "materials", "prefix": "vision"},
        {"access_key_id": "id", "access_key_secret": "secret"},
    )

    provider.upload("a.jpg", BytesIO(b"abc"), metadata={"sha256": "a" * 64})

    assert captured["key"] == "vision/a.jpg"
    assert captured["headers"]["x-oss-forbid-overwrite"] == "true"


def test_oss_same_key_conflict_returns_specific_storage_error(monkeypatch):
    import platform_core.storage.oss as module

    class Conflict(Exception):
        status = 409
        code = "FileAlreadyExists"

    class FakeAuth:
        def __init__(self, *_args):
            pass

    class FakeBucket:
        def __init__(self, *_args):
            pass

        def put_object(self, *_args, **_kwargs):
            raise Conflict("exists")

    monkeypatch.setattr(
        module,
        "_load_oss2",
        lambda: SimpleNamespace(Auth=FakeAuth, StsAuth=FakeAuth, Bucket=FakeBucket),
    )
    provider = OSSStorageProvider(
        "oss",
        {"endpoint": "oss.example.com", "bucket": "materials"},
        {"access_key_id": "id", "access_key_secret": "secret"},
    )

    with pytest.raises(StorageError) as captured:
        provider.upload("same.jpg", BytesIO(b"abc"))

    assert captured.value.code == "STORAGE_OBJECT_EXISTS"


def test_s3_platform_upload_uses_if_none_match_by_default(monkeypatch):
    import platform_core.storage.s3 as module
    captured = {}

    class FakeClient:
        def put_object(self, **kwargs):
            captured.update(kwargs)

        def head_object(self, **_kwargs):
            return {"ContentLength": 3, "ETag": "etag", "Metadata": {"sha256": "a" * 64}}

    fake_client = FakeClient()
    monkeypatch.setattr(
        module,
        "_load_boto3",
        lambda: SimpleNamespace(client=lambda *_args, **_kwargs: fake_client),
    )
    provider = S3StorageProvider("s3", {"bucket": "materials", "prefix": "vision"}, {})

    provider.upload("a.jpg", BytesIO(b"abc"), metadata={"sha256": "a" * 64})

    assert captured["Key"] == "vision/a.jpg"
    assert captured["IfNoneMatch"] == "*"


def test_s3_legacy_overwrite_requires_explicit_opt_out(monkeypatch):
    import platform_core.storage.s3 as module
    captured = {}

    class FakeClient:
        def upload_fileobj(self, stream, bucket, key, ExtraArgs=None):
            captured.update({"bucket": bucket, "key": key, "extra": ExtraArgs, "body": stream.read()})

        def head_object(self, **_kwargs):
            return {"ContentLength": 3, "ETag": "etag", "Metadata": {}}

    fake_client = FakeClient()
    monkeypatch.setattr(
        module,
        "_load_boto3",
        lambda: SimpleNamespace(client=lambda *_args, **_kwargs: fake_client),
    )
    provider = S3StorageProvider(
        "s3",
        {"bucket": "materials", "protect_existing_objects": False},
        {},
    )

    provider.upload("a.jpg", BytesIO(b"abc"))

    assert captured["key"] == "a.jpg"


def test_oss_presigned_upload_contract_binds_forbid_overwrite_header(monkeypatch):
    import platform_core.storage.oss as module
    captured = {}

    class FakeAuth:
        def __init__(self, *_args):
            pass

    class FakeBucket:
        def __init__(self, *_args):
            pass

        def sign_url(self, method, key, expires, headers=None):
            captured.update({
                "method": method,
                "key": key,
                "expires": expires,
                "headers": dict(headers or {}),
            })
            return "https://oss.example.com/signed"

    monkeypatch.setattr(
        module,
        "_load_oss2",
        lambda: SimpleNamespace(Auth=FakeAuth, StsAuth=FakeAuth, Bucket=FakeBucket),
    )
    provider = OSSStorageProvider(
        "oss",
        {"endpoint": "oss.example.com", "bucket": "materials", "prefix": "vision"},
        {"access_key_id": "id", "access_key_secret": "secret"},
    )

    contract = provider.generate_upload_contract(
        "incoming/a.jpg",
        expires_seconds=7200,
        content_type="image/jpeg",
    )

    assert captured == {
        "method": "PUT",
        "key": "vision/incoming/a.jpg",
        "expires": 3600,
        "headers": {
            "Content-Type": "image/jpeg",
            "x-oss-forbid-overwrite": "true",
        },
    }
    assert contract["method"] == "PUT"
    assert contract["headers"] == captured["headers"]
    assert contract["overwrite_protected"] is True
    assert contract["expires_seconds"] == 3600


def test_s3_presigned_upload_contract_binds_if_none_match_header(monkeypatch):
    import platform_core.storage.s3 as module
    captured = {}

    class FakeClient:
        def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
            captured.update({
                "operation": operation,
                "params": dict(Params or {}),
                "expires": ExpiresIn,
            })
            return "https://s3.example.com/signed"

    fake_client = FakeClient()
    monkeypatch.setattr(
        module,
        "_load_boto3",
        lambda: SimpleNamespace(client=lambda *_args, **_kwargs: fake_client),
    )
    provider = S3StorageProvider("s3", {"bucket": "materials", "prefix": "vision"}, {})

    contract = provider.generate_upload_contract(
        "incoming/a.jpg",
        expires_seconds=0,
        content_type="image/jpeg",
    )

    assert captured == {
        "operation": "put_object",
        "params": {
            "Bucket": "materials",
            "Key": "vision/incoming/a.jpg",
            "ContentType": "image/jpeg",
            "IfNoneMatch": "*",
        },
        "expires": 1,
    }
    assert contract["headers"] == {
        "Content-Type": "image/jpeg",
        "If-None-Match": "*",
    }
    assert contract["overwrite_protected"] is True
    assert contract["expires_seconds"] == 1


def test_s3_presigned_upload_contract_legacy_mode_is_explicitly_unprotected(monkeypatch):
    import platform_core.storage.s3 as module
    captured = {}

    class FakeClient:
        def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
            captured.update({
                "operation": operation,
                "params": dict(Params or {}),
                "expires": ExpiresIn,
            })
            return "https://s3.example.com/signed"

    fake_client = FakeClient()
    monkeypatch.setattr(
        module,
        "_load_boto3",
        lambda: SimpleNamespace(client=lambda *_args, **_kwargs: fake_client),
    )
    provider = S3StorageProvider(
        "s3",
        {"bucket": "materials", "protect_existing_objects": False},
        {},
    )

    contract = provider.generate_upload_contract("a.jpg")

    assert "IfNoneMatch" not in captured["params"]
    assert contract["headers"] == {"Content-Type": "application/octet-stream"}
    assert contract["overwrite_protected"] is False


def test_s3_generate_upload_url_delegates_to_protected_contract(monkeypatch):
    import platform_core.storage.s3 as module
    captured = {}

    class FakeClient:
        def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
            captured.update({
                "operation": operation,
                "params": dict(Params or {}),
                "expires": ExpiresIn,
            })
            return "https://s3.example.com/signed"

    fake_client = FakeClient()
    monkeypatch.setattr(
        module,
        "_load_boto3",
        lambda: SimpleNamespace(client=lambda *_args, **_kwargs: fake_client),
    )
    provider = S3StorageProvider("s3", {"bucket": "materials"}, {})

    url = provider.generate_upload_url("same.jpg", content_type="image/jpeg")

    assert url == "https://s3.example.com/signed"
    assert captured["params"]["IfNoneMatch"] == "*"
    assert captured["params"]["ContentType"] == "image/jpeg"


def test_s3_real_sdk_presign_uses_sigv4_and_signs_conditional_headers():
    provider = S3StorageProvider(
        "s3-real-signing",
        {"bucket": "materials", "region": "us-east-1", "prefix": "vision"},
        {"access_key_id": "test-access", "secret_access_key": "test-secret"},
    )

    contract = provider.generate_upload_contract(
        "incoming/a.jpg",
        expires_seconds=60,
        content_type="image/jpeg",
    )

    query = parse_qs(urlsplit(str(contract["url"])).query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    signed_headers = set(query["X-Amz-SignedHeaders"][0].split(";"))
    assert {"content-type", "host", "if-none-match"}.issubset(signed_headers)
    assert contract["headers"]["If-None-Match"] == "*"


def test_oss_real_sdk_presign_accepts_conditional_signed_headers_without_network():
    provider = OSSStorageProvider(
        "oss-real-signing",
        {
            "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
            "bucket": "materials",
            "prefix": "vision",
        },
        {"access_key_id": "test-access", "access_key_secret": "test-secret"},
    )

    contract = provider.generate_upload_contract(
        "incoming/a.jpg",
        expires_seconds=60,
        content_type="image/jpeg",
    )

    assert str(contract["url"]).startswith("https://")
    assert contract["headers"] == {
        "Content-Type": "image/jpeg",
        "x-oss-forbid-overwrite": "true",
    }
    assert contract["overwrite_protected"] is True
