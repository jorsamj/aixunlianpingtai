from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

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
