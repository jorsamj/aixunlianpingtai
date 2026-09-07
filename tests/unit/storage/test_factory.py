from __future__ import annotations

import pytest

from platform_core.storage import LocalStorageProvider, StorageError, StorageProviderFactory, StorageSource


def source(**changes):
    values = dict(
        id="default_local", name="平台本地存储", type="local", config={}, enabled=True
    )
    values.update(changes)
    return StorageSource(**values)


def test_factory_builds_default_local_provider_at_project_root(tmp_path):
    project = tmp_path / "data" / "projects" / "p1"
    factory = StorageProviderFactory(data_dir=tmp_path / "data", project_dir=project)
    provider = factory.create(source())
    assert isinstance(provider, LocalStorageProvider)
    assert provider.root == project.resolve()


def test_factory_resolves_custom_relative_local_root_under_data_dir(tmp_path):
    factory = StorageProviderFactory(data_dir=tmp_path / "data", project_dir=tmp_path / "project")
    provider = factory.create(source(id="local-b", name="local b", config={"root": "external/materials"}, is_default=False))
    assert provider.root == (tmp_path / "data" / "external" / "materials").resolve()


def test_factory_rejects_disabled_source(tmp_path):
    factory = StorageProviderFactory(data_dir=tmp_path, project_dir=tmp_path / "project")
    with pytest.raises(StorageError) as captured:
        factory.create(source(enabled=False))
    assert captured.value.code == "STORAGE_SOURCE_DISABLED"
