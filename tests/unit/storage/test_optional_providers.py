from __future__ import annotations

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

