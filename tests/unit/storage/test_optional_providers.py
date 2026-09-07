from __future__ import annotations

from types import SimpleNamespace

import pytest

from platform_core.storage import OSSStorageProvider, S3StorageProvider, StorageError


@pytest.mark.parametrize(
    "factory",
    [
        lambda: S3StorageProvider("s3", {"endpoint": "", "bucket": ""}, {}),
        lambda: OSSStorageProvider("oss", {"endpoint": "", "bucket": ""}, {}),
    ],
)
def test_object_provider_rejects_incomplete_configuration_before_network(factory):
    with pytest.raises(StorageError) as captured:
        factory()
    assert captured.value.code == "STORAGE_CONFIG_INVALID"


def test_s3_provider_requires_real_sdk(monkeypatch):
    import platform_core.storage.s3 as module
    monkeypatch.setattr(module, "_load_boto3", lambda: (_ for _ in ()).throw(ImportError("boto3 missing")))
    with pytest.raises(StorageError) as captured:
        S3StorageProvider("s3", {"endpoint": "http://127.0.0.1:9000", "bucket": "materials"}, {})
    assert captured.value.code == "STORAGE_SDK_MISSING"


def test_oss_provider_requires_real_sdk(monkeypatch):
    import platform_core.storage.oss as module
    monkeypatch.setattr(module, "_load_oss2", lambda: (_ for _ in ()).throw(ImportError("oss2 missing")))
    with pytest.raises(StorageError) as captured:
        OSSStorageProvider("oss", {"endpoint": "oss-cn-hangzhou.aliyuncs.com", "bucket": "materials"}, {})
    assert captured.value.code == "STORAGE_SDK_MISSING"


def test_oss_pagination_marker_keeps_configured_prefix(monkeypatch):
    import platform_core.storage.oss as module

    captured = {}

    class FakeAuth:
        def __init__(self, *_args):
            pass

    class FakeBucket:
        def __init__(self, *_args):
            pass

    def fake_iterator(_bucket, **kwargs):
        captured.update(kwargs)
        return iter([
            SimpleNamespace(
                key="vision/incoming/next.jpg",
                size=123,
                etag="etag",
                last_modified="now",
                is_prefix=lambda: False,
            )
        ])

    fake_oss2 = SimpleNamespace(Auth=FakeAuth, StsAuth=FakeAuth, Bucket=FakeBucket, ObjectIterator=fake_iterator)
    monkeypatch.setattr(module, "_load_oss2", lambda: fake_oss2)

    provider = OSSStorageProvider(
        "oss",
        {"endpoint": "oss.example.com", "bucket": "materials", "prefix": "vision"},
        {"access_key_id": "id", "access_key_secret": "secret"},
    )
    page = provider.list_objects("incoming", cursor="incoming/previous.jpg", limit=1)

    assert captured["prefix"] == "vision/incoming"
    assert captured["marker"] == "vision/incoming/previous.jpg"
    assert [item.key for item in page.items] == ["incoming/next.jpg"]
    assert page.next_cursor == "incoming/next.jpg"
